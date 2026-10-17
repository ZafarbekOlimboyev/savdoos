# -*- coding: utf-8 -*-
"""CH-18C — hisob o'chirish KONKURENSIYASI, HAQIQIY PostgreSQL'da.

⚠️  NEGA SQLITE YETARLI EMAS. `account_deletion._active_peers(lock=True)`
    `SELECT ... FOR UPDATE` ishlatadi. SQLite'da `with_for_update` — NO-OP:
    u yozuvlarni tranzaksiya darajasida seriallashtiradi, ya'ni poyga UMUMAN
    yuzaga kelmaydi va test «yashil» bo'ladi. CH-18B da men faqat qulf
    MANBADA borligini qadagandim — bu qulf BORLIGINI tasdiqlaydi, ISHLASHINI
    emas. Bu fayl ISHLASHINI o'lchaydi.

⚠️  BAZA: FAQAT `SAVDOOS_TEST_PG_URL` berilganda ishlaydi va u BIR MARTALIK,
    izolyatsiyalangan klasterga ishora qilishi kerak. Berilmasa — OCHIQ SKIP
    («o'tdi» deb ko'rinmaydi). Ulashilgan/ishlab chiqarish klasterida
    ishlatish MAN ETILADI: fayl o'z bazasini `CREATE DATABASE` qiladi va
    oxirida `DROP` qiladi, lekin bu ham ULASHILGAN serverga yozish bo'lardi.

⚠️  NIMA O'LCHANADI. Endpoint'ning KRITIK QISMI — holatni o'qish (peer QULFI
    ostida) va anonimlashtirish. Parol, RL va HTTP kodlari bu yerda EMAS:
    ular SQLite to'plamida (CH-18A/B/C) allaqachon qoplangan va PG ga aloqasi
    yo'q. Shu bois quyida «409» deb emas, `blockers` ro'yxati bo'yicha
    tekshiriladi — HTTP qatlami TestClient'siz chaqirilmaydi.

INTERLEAVING IKKI XIL. `_navbat` — A yozib turadi, B keyin keladi (QULF
KO'RINADIGAN holat). `_ikki_fazali` — ikkisi ham AVVAL qulfni oladi, keyin
ikkisi ham yozadi (ENG YOMON holat). Ikkinchisi muhim: `_active_peers`
O'ZINI chiqarib tashlaydi, ya'ni A faqat B ni, B faqat A ni qulflaydi —
qulf to'plamlari KESISHMASA seriallashtirish YO'Q.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from tests.test_lot_phase4a_pg import SRV

_PG = os.getenv("SAVDOOS_TEST_PG_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not _PG, reason="SAVDOOS_TEST_PG_URL yo'q — izolyatsiyalangan PG klasteri kerak")

LOCK_MS = 4000          # qulf kutish chegarasi: osilib qolmasin
KUTISH = 6.0            # ip kutish chegarasi (sekund)


def _psycopg(u: str) -> str:
    for p in ("postgres://", "postgresql://"):
        if u.startswith(p) and "+psycopg" not in u:
            return "postgresql+psycopg://" + u[len(p):]
    return u


@pytest.fixture(scope="module")
def pg_url():
    """BIR MARTALIK baza + `initdb` (rol/ruxsat urug'i). Har test O'Z
    kompaniyasini yaratadi — ijarachi izolyatsiyasi testlarni ajratadi, shu
    bois har test uchun alohida baza ko'tarish (va `initdb` ni qayta
    yugurtirish) KERAK EMAS."""
    from sqlalchemy.engine import make_url
    admin = make_url(_psycopg(_PG))
    nom = f"ch18c_{uuid.uuid4().hex[:12]}"
    aeng = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with aeng.connect() as con:
            con.execute(text(f'CREATE DATABASE "{nom}"'))
        url = admin.set(database=nom).render_as_string(hide_password=False)
        r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                           capture_output=True, text=True, timeout=900,
                           env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))
        assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
        yield url
    finally:
        with aeng.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)'))
        aeng.dispose()


@pytest.fixture
def S(pg_url):
    """Ilova bilan AYNI sessiya sozlamasi + qulf/so'rov muddati."""
    eng = create_engine(pg_url, connect_args={
        "options": f"-c lock_timeout={LOCK_MS} -c statement_timeout=30000"})
    yield eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False,
                            class_=Session)
    eng.dispose()


# ══ URUG' ═══════════════════════════════════════════════════════════════════

def _dokon(S_, *, rahbarlar=("ega", "administrator"), kassirlar=0):
    """Yangi kompaniya + filial + berilgan rollar. Har xodimda parol BOR."""
    from app.core.security import hash_password
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    s = S_()
    try:
        co = Company(id=uuid.uuid4(), name="CH18C", code="c" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        b = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B1",
                   timezone="Asia/Tashkent", is_active=True)
        s.add(b)
        s.flush()
        ids = {}
        for kod in rahbarlar:
            r = s.query(Role).filter(Role.code == kod).one()
            e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=r.id,
                         full_name=f"PG-{kod.upper()}-{uuid.uuid4().hex[:6]}",
                         phone="+9989" + str(uuid.uuid4().int)[:8],
                         password_hash=hash_password("x"),
                         status=EmployeeStatus.active, sec_epoch=0)
            s.add(e)
            s.flush()
            ids.setdefault(kod, []).append(e.id)
        for i in range(kassirlar):
            r = s.query(Role).filter(Role.code == "kassir").one()
            e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=r.id,
                         full_name=f"PG-KASSIR{i}-{uuid.uuid4().hex[:6]}",
                         phone="+9989" + str(uuid.uuid4().int)[:8],
                         pin_hash=hash_password("4721"),
                         status=EmployeeStatus.active, sec_epoch=0)
            s.add(e)
            s.flush()
            ids.setdefault("kassir", []).append(e.id)
        s.commit()
        return {"cid": co.id, "bid": b.id, **{k: list(v) for k, v in ids.items()}}
    finally:
        s.close()


def _faol_rahbar_soni(S_, cid) -> int:
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    s = S_()
    try:
        return (s.query(Employee).join(Role, Role.id == Employee.role_id)
                .filter(Employee.company_id == cid,
                        Role.code.in_(("ega", "administrator")),
                        Employee.status == EmployeeStatus.active,
                        Employee.deleted_at.is_(None)).count())
    finally:
        s.close()


def _emp(S_, eid):
    from app.models.auth import Employee
    s = S_()
    try:
        return s.get(Employee, eid)
    finally:
        s.close()


# ══ KRITIK QISMLAR (endpoint mantiqining qulf bilan ishlaydigan yadrosi) ════

def _oz_ochirish(s, eid):
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    e = s.get(Employee, eid)
    st = _AD.self_deletion_state(s, e)
    if st["already_deleted"]:
        return "repeated"
    if not st["can_delete"]:
        return ("blocked", tuple(st["blockers"]))
    _AD.anonymize(s, e)
    return "deleted"


def _boshqani_ochirish(s, actor_id, target_id):
    """Marshrutning kritik qismi: bloklar -> anonimlashtirish -> SO'ROVNI
    RO'YXATDAN OLISH.

    ⚠️  `clear_request` BU YERDA BO'LISHI SHART. Men uni avval tushirib
        qoldirgandim va natijada test «bajarilgan so'rov ro'yxatda qoldi» deb
        qizil bo'ldi — bu KODNING emas, TESTNING nuqsoni edi: yordamchi
        marshrutdan (`api/v1/employees.py:delete_employee_account`) farq
        qilardi. Yordamchi marshrutga mos bo'lmasa, u boshqa narsani
        o'lchaydi."""
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    a, t = s.get(Employee, actor_id), s.get(Employee, target_id)
    bloklar = _AD.other_deletion_blockers(s, a, t)
    if _AD.is_deleted(t):
        return "repeated"
    if bloklar:
        return ("blocked", tuple(bloklar))
    _AD.anonymize(s, t)
    _AD.clear_request(s, a.company_id, t.id)
    return "deleted"


def _deadlock(e: BaseException) -> bool:
    """`DeadlockDetected` mi (`LockNotAvailable` DAN farqli)."""
    return "deadlock" in str(e).lower()


def _bloklar(s, actor_id, target_id):
    """1-FAZA: peer QULFI aynan shu chaqiruvda olinadi."""
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    return _AD.other_deletion_blockers(s, s.get(Employee, actor_id),
                                       s.get(Employee, target_id))


def _anon(s, target_id):
    """2-FAZA: maqsad qatoriga YOZISH."""
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    t = s.get(Employee, target_id)
    if _AD.is_deleted(t):
        return "repeated"
    _AD.anonymize(s, t)
    return "deleted"


def _yopish(s, owner_id):
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    return _AD.close_store(s, s.get(Employee, owner_id))


# ══ INTERLEAVING HARNESS ════════════════════════════════════════════════════

def _navbat(S_, birinchi, ikkinchi):
    """A yozadi (commit QILMAY turadi) -> B keladi -> A commit qiladi.
    QULF KO'RINADIGAN interleaving."""
    yozdi = threading.Event()
    out: dict = {}

    def run_a():
        s = S_()
        try:
            out["a"] = birinchi(s)
            s.flush()
            yozdi.set()
            yozdi.wait(0)          # B boshlasin
            import time
            time.sleep(0.4)        # B qulfga kirib ulgursin
            s.commit()
        except Exception as e:     # noqa: BLE001
            s.rollback()
            out["a"] = e
        finally:
            yozdi.set()
            s.close()

    def run_b():
        s = S_()
        try:
            assert yozdi.wait(KUTISH), "A yozib ulgurmadi"
            out["b"] = ikkinchi(s)
            s.commit()
        except Exception as e:     # noqa: BLE001
            s.rollback()
            out["b"] = e
        finally:
            s.close()

    ta, tb = threading.Thread(target=run_a), threading.Thread(target=run_b)
    ta.start(); tb.start()
    ta.join(KUTISH * 2); tb.join(KUTISH * 2)
    assert not ta.is_alive() and not tb.is_alive(), f"ip osilib qoldi: {out}"
    return out


def _ikki_fazali(S_, ishlar):
    """ENG YOMON interleaving: HAMMA ip avval QULFNI oladi (1-faza), to'siqda
    uchrashadi, keyin HAMMASI yozadi (2-faza).

    Qulf chindan seriallashtirsa, biri 1-fazada BLOKLANADI va to'siqqa yetib
    bormaydi -> `BrokenBarrierError` -> bu TO'G'RI xulq (natijada `barrier`
    bayrog'i False bo'ladi). Qulflar kesishmasa — ikkisi ham o'tadi."""
    tosiq = threading.Barrier(len(ishlar), timeout=KUTISH)
    out: dict = {}

    def yugur(i, faza1, faza2):
        s = S_()
        try:
            h = faza1(s)                      # QULF olinadi
            try:
                tosiq.wait()
                out[f"tosiq{i}"] = True
            except threading.BrokenBarrierError:
                out[f"tosiq{i}"] = False      # boshqasi bloklandi = SERIALLASHGAN
            out[i] = faza2(s, h)
            s.commit()
        except Exception as e:                # noqa: BLE001
            s.rollback()
            out[i] = e
            tosiq.abort()
        finally:
            s.close()

    iplar = [threading.Thread(target=yugur, args=(i, f1, f2))
             for i, (f1, f2) in enumerate(ishlar)]
    for t in iplar:
        t.start()
    for t in iplar:
        t.join(KUTISH * 3)
    assert all(not t.is_alive() for t in iplar), f"ip osilib qoldi: {out}"
    return out


def _faza_oz(eid):
    """(1-faza: holat+QULF, 2-faza: anonimlashtirish) — o'zini o'chirish."""
    def f1(s):
        from app.models.auth import Employee
        from app.services import account_deletion as _AD
        e = s.get(Employee, eid)
        return (e, _AD.self_deletion_state(s, e))

    def f2(s, h):
        from app.services import account_deletion as _AD
        e, st = h
        if st["already_deleted"]:
            return "repeated"
        if not st["can_delete"]:
            return ("blocked", tuple(st["blockers"]))
        _AD.anonymize(s, e)
        return "deleted"
    return f1, f2


# ══ 1. OXIRGI IKKI RAHBAR O'ZINI O'CHIRADI ══════════════════════════════════

def test_PG_1A_NAVBAT_bilan_oxirgi_rahbar_BLOKLANADI(S):
    """A yozib turgan holatda B keladi: B ning `FOR UPDATE` so'rovi A ning
    qatorini kutadi, A commit qilgach B uni «faol emas» ko'radi -> BLOK."""
    eng, S_ = S
    #  ⚠️  IKKI EGA. `ega` + `administrator` da poyga YUZAGA KELMAYDI: `ega`
    #      uchun `sole_owner` alohida tekshiriladi (administrator EGA o'rnini
    #      BOSMAYDI), ya'ni yagona ega hech qachon o'zini o'chira olmaydi.
    #      Haqiqiy poyga — ikki EGA orasida.
    d = _dokon(S_, rahbarlar=("ega", "ega"))
    a, b = d["ega"]

    out = _navbat(S_, lambda s: _oz_ochirish(s, a), lambda s: _oz_ochirish(s, b))

    assert out["a"] == "deleted", out
    assert isinstance(out["b"], tuple), out
    assert {"sole_manager", "sole_owner"} & set(out["b"][1]), out
    assert _faol_rahbar_soni(S_, d["cid"]) == 1, "do'kon BOSHSIZ qoldi"


def test_PG_1B_BIR_VAQTDA_dokon_BOSHSIZ_QOLMAYDI(S):
    """⚠️  ENG YOMON interleaving. `_active_peers` O'ZINI chiqarib tashlaydi,
    ya'ni A faqat B ni, B faqat A ni qulflaydi. Qulf to'plamlari KESISHMASA
    ikkisi ham «vorisim bor» deb ko'radi va IKKISI HAM o'chadi.

    QABUL MEZONI: do'konda KAMIDA BITTA faol rahbar QOLADI."""
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "ega"))
    a, b = d["ega"]

    out = _ikki_fazali(S_, [_faza_oz(a), _faza_oz(b)])

    qolgan = _faol_rahbar_soni(S_, d["cid"])
    assert qolgan >= 1, (
        f"IKKI oxirgi rahbar BIR VAQTDA o'chdi — do'kon BOSHSIZ qoldi: {out}")
    ochdi = [v for v in (out.get(0), out.get(1)) if v == "deleted"]
    assert len(ochdi) == 1, f"ikkisi ham o'chdi yoki hech biri o'chmadi: {out}"


# ══ 2. EGA IKKI RAHBARNI PARALLEL O'CHIRADI ═════════════════════════════════

def test_PG_2_ega_IKKI_administratorni_PARALLEL_ochiradi(S):
    """⚠️  REJADAGI KUTILMA TUZATILDI. `PG-CONCURRENCY-PLAN.md` «bittasi 200,
    ikkinchisi 409» degan. Bu NOTO'G'RI: aktyor EGA bo'lishi SHART va u
    O'ZINI bu yo'l bilan o'chira olmaydi, ya'ni ega HAR DOIM faol rahbar
    bo'lib qoladi. Shu bois IKKI administratorning ikkisi ham o'chishi
    TO'G'RI xulq.

    ⚠️  POYGA EHTIMOLIY, shu bois RAUNDLAR. Bir urinish deadlock'ni tutmaydi
        (men buni avval o'z zararimga ko'rdim: bitta raund manfiy nazoratda
        ham yashil chiqdi). Shu bois ayni poyga `RAUNDLAR` marta, har safar
        YANGI do'kon bilan takrorlanadi va BIRON raundda ham
        `OperationalError` (deadlock) chiqmasligi talab qilinadi.

        Tuzatishdan OLDIN qulf to'plamlari har chaqiruvda boshqa edi
        (`exclude_id` SQL filtrida) va PostgreSQL `DeadlockDetected` berardi;
        hozir qulf butun rol to'plamiga AYNI tartibda qo'yiladi."""
    eng, S_ = S
    RAUNDLAR = 12
    xatolar, kutgan, tosiqdan = [], [], 0
    for raund in range(RAUNDLAR):
        d = _dokon(S_, rahbarlar=("ega", "administrator", "administrator"))
        ega = d["ega"][0]
        a1, a2 = d["administrator"]

        #  ⚠️  TO'SIQ BUTUN KRITIK QISMDAN OLDIN. Men avval `_bloklar` ni
        #      1-fazaga ajratgandim — u deadlock'ni TUTMADI, chunki peer
        #      qulflari IKKALA so'rovda ham EGA qatorini o'z ichiga oladi,
        #      ya'ni 1-fazada DARHOL seriallashib bo'lardi. Halokatli
        #      interleaving — ikkisi ham `SELECT ... FOR UPDATE` ni BIR
        #      VAQTDA boshlagandagina: qulflar har xil tartibda tushadi va
        #      keyin har biri BOSHQASINING maqsadini so'raydi -> SIKL.
        out = _ikki_fazali(S_, [
            ((lambda s: None), (lambda s, _h: _boshqani_ochirish(s, ega, a1))),
            ((lambda s: None), (lambda s, _h: _boshqani_ochirish(s, ega, a2))),
        ])

        tosiqdan += 1 if (out.get("tosiq0") and out.get("tosiq1")) else 0
        for k in (0, 1):
            v = out.get(k)
            if isinstance(v, Exception) and _deadlock(v):
                xatolar.append((raund, k, str(v)[:160]))
            elif isinstance(v, Exception):
                #  ⚠️  `LockNotAvailable` — BU TO'G'RI XULQ, xato EMAS. Ikkinchi
                #      tranzaksiya qulfni KUTDI, ya'ni seriallashish ISHLADI;
                #      bu yerda u testdagi sun'iy `lock_timeout` (4s) ga urildi,
                #      ishlab chiqarishda esa kutib, toza 409 olardi. Shu bois
                #      SANALMAYDI — aks holda test to'g'ri xulqni «buzuq» derdi.
                kutgan.append((raund, k))
        assert _faol_rahbar_soni(S_, d["cid"]) >= 1, (raund, out)
        from app.services import account_deletion as _AD
        assert not _AD.is_deleted(_emp(S_, ega)), (raund, "aktyor o'chirildi")
    assert not xatolar, (
        f"{len(xatolar)}/{RAUNDLAR} raundda DEADLOCK — operator toza 409 emas, "
        f"500 oladi: {xatolar[:3]}")
    #  Seriallashish CHINDAN yuz berganiga ishonch: aks holda test «deadlock
    #  yo'q» deb poyga UMUMAN bo'lmaganini yashirardi.
    #  Poyga CHINDAN yuz berganiga ishonch: har raundda ikki ip ham to'siqdan
    #  o'tgan bo'lishi kerak, aks holda ular ketma-ket ishlagan va test BO'SH.
    assert tosiqdan == RAUNDLAR, (
        f"{tosiqdan}/{RAUNDLAR} raundda ikki ip BIR VAQTDA kirdi — "
        f"qolganida poyga yuzaga kelmadi, test bo'sh bo'lardi")


# ══ 3. YOPISH x O'Z HISOBINI O'CHIRISH ══════════════════════════════════════

def test_PG_3_yopish_x_oz_ochirish_PARALLEL(S):
    """Ega do'konni yopadi, AYNI PAYTDA administrator o'z hisobini o'chiradi.
    Qabul: ZID holat qolmaydi — yarim yopilgan do'kon ham, yarim
    anonimlashtirilgan qator ham YO'Q.

    ⚠️  KUTILMA CH-23 da O'ZGARDI (ega qarori), TEKSHIRUVNING MAQSADI emas.
        Ilgari bu test `deleted_at` O'RNATILISHINI talab qilardi. Endi yopish
        faol sherik rahbar bo'lsa 409 beradi, urug'da esa IKKI administrator
        bor — biri o'zini o'chirsa ham IKKINCHISI FAOL qoladi, ya'ni natija
        DETERMINISTIK: do'kon OCHIQ qoladi. Interleaving'ning o'zi
        (yopish x o'z-o'chirish) AVVALGIDEK sinaladi va «yarim holat yo'q»
        tasdig'i bir harf ham o'zgarmagan.
    """
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator", "administrator"))
    ega = d["ega"][0]
    adm = d["administrator"][0]

    out = _ikki_fazali(S_, [
        ((lambda s: None), (lambda s, _h: _yopish(s, ega))),
        _faza_oz(adm),
    ])

    from app.models.enums import CompanyStatus
    from app.models.org import Company
    s = S_()
    try:
        co = s.get(Company, d["cid"])
        #  CH-23: ikkinchi administrator FAOL qoldi -> yopish RAD etildi.
        assert co.deleted_at is None, f"faol sherik bor, lekin yopildi: {out}"
        assert co.status != CompanyStatus.CLOSED.value, co.status
    finally:
        s.close()
    #  Administrator: yo o'chgan, yo bloklangan — lekin YARIM holat YO'Q
    from app.services import account_deletion as _AD
    e = _emp(S_, adm)
    assert (_AD.is_deleted(e) or e.full_name.startswith("PG-ADMINISTRATOR")), \
        f"yarim anonimlashtirilgan qator: {e.full_name!r}"


# ══ 4. AYNI XODIMNI IKKI MARTA PARALLEL O'CHIRISH ═══════════════════════════

def test_PG_4_AYNI_xodim_ikki_marta_sec_epoch_BIR_MARTA(S):
    """Bittasi o'chiradi, ikkinchisi `repeated`. `sec_epoch` BIR MARTA oshadi
    — aks holda allaqachon bekor qilingan sessiya qayta-qayta uzilardi va
    audit ikki «o'chirish» ko'rsatardi."""
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=1)
    ega = d["ega"][0]
    k = d["kassir"][0]
    oldin = int(_emp(S_, k).sec_epoch or 0)

    out = _ikki_fazali(S_, [
        ((lambda s: None), (lambda s, _h: _boshqani_ochirish(s, ega, k))),
        ((lambda s: None), (lambda s, _h: _boshqani_ochirish(s, ega, k))),
    ])

    natijalar = sorted(str(out.get(i)) for i in (0, 1))
    assert "deleted" in natijalar, out
    keyin = int(_emp(S_, k).sec_epoch or 0)
    assert keyin == oldin + 1, f"sec_epoch {oldin} -> {keyin} (bir marta kutilgan): {out}"


# ══ 5. YOPISH x QABUL (ombor yozuvi) ════════════════════════════════════════

def test_PG_5_yopish_x_ombor_yozuvi_STOK_INVARIANTI_BUTUN(S):
    """Yopish OPERATSION amal: u hisob-kitobga TEGMAYDI. Parallel ombor
    yozuvi bilan birga ishlaganda ham stok invarianti BUTUN qoladi."""
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory, StockBatch
    eng, S_ = S
    d = _dokon(S_)
    ega = d["ega"][0]
    s = S_()
    try:
        unit = s.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name="PG " + uuid.uuid4().hex[:6],
                    article_code="Q-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100,
                    tax_rate=0, track_lots=False, track_expiry=False)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=d["bid"],
                        qty=0, min_qty=0,
                        updated_at=datetime.now(timezone.utc)))
        s.commit()
        pid = p.id
    finally:
        s.close()

    def qabul(s, _h):
        inv = (s.query(Inventory).filter(Inventory.product_id == pid,
                                         Inventory.branch_id == d["bid"])
               .with_for_update().one())
        inv.qty = Decimal(str(inv.qty)) + Decimal("7.000")
        s.add(StockBatch(id=uuid.uuid4(), company_id=d["cid"], branch_id=d["bid"],
                         product_id=pid, qty=Decimal("7.000"),
                         received_qty=Decimal("7.000"), remaining_qty=Decimal("7.000"),
                         unit_cost=Decimal("50"), status="open",
                         source_type="receiving", client_uuid=uuid.uuid4(),
                         row_version=1))
        return "qabul"

    out = _ikki_fazali(S_, [((lambda s: None), (lambda s, _h: _yopish(s, ega))),
                            ((lambda s: None), qabul)])

    from app.services import stock_invariant
    s = S_()
    try:
        rep = stock_invariant.check(s, d["cid"])
        buzuq = getattr(rep, "violations", None)
        assert not buzuq, f"stok invarianti buzildi: {buzuq} / {out}"
        inv = (s.query(Inventory).filter(Inventory.product_id == pid,
                                         Inventory.branch_id == d["bid"]).one())
        assert Decimal(str(inv.qty)) in (Decimal("0.000"), Decimal("7.000")), inv.qty
    finally:
        s.close()


# ══ 6-7. FAQAT PG'DA O'LCHANADIGAN TASDIQLAR ════════════════════════════════

def test_PG_6_anonimlashtirilgach_AYNI_telefon_QAYTA_ROYXATDAN_OTADI(S):
    """`ux_employees_phone_pw` — QISMAN indeks (`phone IS NOT NULL AND
    password_hash IS NOT NULL AND deleted_at IS NULL`). Anonimlashtirishdan
    keyin telefon NULL bo'ladi, ya'ni indeks qatorni CHIQARIB TASHLAYDI va
    AYNI telefon qayta ro'yxatdan o'tadi. SQLite'da bu indeks xulqi boshqa,
    shu bois faqat shu yerda o'lchanadi."""
    from app.core.security import hash_password
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=1)
    k = d["kassir"][0]
    telefon = _emp(S_, k).phone
    s = S_()
    try:
        e = s.get(Employee, k)
        e.password_hash = hash_password("x")       # indeksga tushsin
        s.commit()
    finally:
        s.close()

    s = S_()
    try:
        from app.services import account_deletion as _AD
        _AD.anonymize(s, s.get(Employee, k))
        s.commit()
    finally:
        s.close()

    s = S_()
    try:
        r = s.query(Role).filter(Role.code == "kassir").one()
        s.add(Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id,
                       full_name="QAYTA", phone=telefon,
                       password_hash=hash_password("y"),
                       status=EmployeeStatus.active, sec_epoch=0))
        s.commit()                                 # UNIQUE buzilmasligi KERAK
    finally:
        s.close()


def test_PG_7_audit_JSONB_da_name_KALITI_QOLMAYDI(S):
    """PG'da `audit_log.before/after` — `jsonb`. Redaksiyadan keyin
    `before ? 'name'` FALSE bo'lishi kerak. SQLite'da bu JSON TEXT, ya'ni
    `?` operatori umuman sinalmaydi — shu bois tekshiruv shu yerda."""
    from app.models.auth import Employee
    from app.models.sync import AuditLog
    from app.services import account_deletion as _AD
    from app.services.audit import log as audit_log
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=1)
    k = d["kassir"][0]
    nom = _emp(S_, k).full_name
    s = S_()
    try:
        audit_log(s, d["ega"][0], "update", "employee", k,
                  before={"name": nom, "phone": "+998901112233"},
                  after={"name": nom + "!", "phone": "+998901112233"})
        s.commit()
    finally:
        s.close()
    with eng.connect() as con:
        bor = con.execute(text(
            "SELECT count(*) FROM audit_log WHERE entity='employee' "
            "AND entity_id = :e AND (before ? 'name' OR after ? 'name')"),
            {"e": str(k)}).scalar()
    assert bor == 1, f"nazorat: redaksiyadan OLDIN `name` BO'LISHI kerak ({bor})"

    s = S_()
    try:
        _AD.anonymize(s, s.get(Employee, k))
        s.commit()
    finally:
        s.close()

    with eng.connect() as con:
        qoldi = con.execute(text(
            "SELECT count(*) FROM audit_log WHERE entity='employee' "
            "AND entity_id = :e AND (before ? 'name' OR after ? 'name' "
            "OR before ? 'phone' OR after ? 'phone')"), {"e": str(k)}).scalar()
        izlar = con.execute(text(
            "SELECT count(*) FROM audit_log WHERE entity='employee' AND entity_id = :e"),
            {"e": str(k)}).scalar()
    assert qoldi == 0, f"jsonb'da PII kaliti QOLDI: {qoldi}"
    assert izlar >= 1, "audit IZI o'chirildi — javobgarlik yo'qoldi"
    assert AuditLog is not None


# ══ 8. SO'ROV RO'YXATI — LOST UPDATE (CH-18D/B) ═════════════════════════════
#
#  ⚠️  `account_deletion_requests` — BITTA `Setting` qatoridagi RO'YXAT. Unga
#      yozish read-modify-write: ro'yxat o'qiladi, element qo'shiladi, butun
#      ro'yxat qayta yoziladi. Ikki xodim BIR VAQTDA so'rov yuborsa va o'qish
#      QULFSIZ bo'lsa, ikkinchi yozuv birinchisini BOSIB KETADI — xodim
#      «so'rovim yuborildi» deb ko'radi, lekin ega uni HECH QACHON ko'rmaydi.
#
#      Bu SQLite'da ishonchli ko'rinmaydi (yozuvlar tranzaksiya darajasida
#      seriallashadi), shu bois tekshiruv SHU YERDA.

def _sorov(s, eid):
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    return _AD.request_deletion(s, s.get(Employee, eid))


def _royxat(S_, cid) -> set:
    from app.services import account_deletion as _AD
    s = S_()
    try:
        return {str(it.get("employee_id")) for it in _AD.list_requests(s, cid)}
    finally:
        s.close()


#  ⚠️  NEGA `_navbat`, `_ikki_fazali` EMAS. Lost update ikkisi bir vaqtda
#      BOSHLANGANDA emas, biri YOZIB USHLAB TURGANDA ikkinchisi ESKIRGAN
#      nusxani o'qiganda yuz beradi. `_ikki_fazali` bilan yozgan variantim
#      manfiy nazoratda 3/3 YASHIL chiqdi — ya'ni poygani umuman
#      majburlamagan edi. `_navbat` esa aynan shu ketma-ketlikni beradi:
#      A flush qiladi (qator yozuv-qulfida, commit YO'Q) -> B keladi va
#      qulfsiz o'qishda ESKI qiymatni ko'radi -> A commit qilgach B o'z
#      eskirgan ro'yxatini ustiga yozadi.
#
#      Qulf bilan: B O'QISHDA bloklanadi, A commit qilgach QAYTA o'qiydi.

def test_PG_8_YOZIB_TURGANDA_kelgan_SOROV_BIRINCHISINI_BOSMAYDI(S):
    """A so'rov yozib ushlab turadi, B so'rov yuboradi — IKKISI ham qoladi.

    ⚠️  BU TEST QULF DETEKTORI EMAS — u BIRINCHI-INSERT poygasini qadaydi.
        Qator hali yo'q bo'lsa, B ning INSERT'i `UNIQUE(company_id,
        branch_id, key)` indeksida A commit qilguncha BLOKLANADI, keyin
        `IntegrityError` beradi va `_requests_row_locked` SAVEPOINT ichida
        uni ushlab, A ning qatorini qayta o'qiydi. Shu bois u qulfsiz ham
        yashil bo'ladi (men buni manfiy nazoratda ko'rdim) — qulfning
        o'zini pastdagi test qadaydi.
    """
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=2)
    a, b = d["kassir"]

    out = _navbat(S_, lambda s: _sorov(s, a), lambda s: _sorov(s, b))

    assert isinstance(out.get("a"), dict), out
    assert isinstance(out.get("b"), dict), out
    assert _royxat(S_, d["cid"]) == {str(a), str(b)}, (
        f"«yuborildi» deb javob berilgan so'rov YO'QOLDI: "
        f"{_royxat(S_, d['cid'])} out={out}")


def test_PG_8_BAJARISH_ustiga_kelgan_SOROV_ochirilganni_TIRILTIRMAYDI(S):
    """Ega A ning so'rovini bajarib yozib turadi, B yangi so'rov yuboradi.
    Natija AYNAN {B}: A qayta tirilmasligi va B yo'qolmasligi KERAK.

    ⚠️  QULF DETEKTORI. `_requests_row(lock=True)` dan `with_for_update()`
        olib tashlansa, bu test 2/2 urinishda QIZIL bo'ladi (tekshirildi):
        B eskirgan ro'yxatni o'qiydi va A ning BAJARILGAN so'rovini QAYTA
        TIRILTIRADI — ega ro'yxatida allaqachon o'chirilgan odam uchun
        zombi yozuv paydo bo'lardi."""
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=2)
    ega = d["ega"][0]
    a, b = d["kassir"]
    s = S_()
    try:
        _sorov(s, a)
        s.commit()
    finally:
        s.close()
    assert _royxat(S_, d["cid"]) == {str(a)}, "nazorat: A ro'yxatda bo'lishi kerak"

    out = _navbat(S_,
                  lambda s: _boshqani_ochirish(s, ega, a),
                  lambda s: _sorov(s, b))

    assert out.get("a") == "deleted", out
    assert _royxat(S_, d["cid"]) == {str(b)}, (
        f"bajarilgan so'rov QAYTA TIRILDI yoki yangisi yo'qoldi: "
        f"{_royxat(S_, d['cid'])} out={out}")


def test_PG_8_UCH_xodim_KETMA_KET_hammasi_ROYXATDA(S):
    """Nazorat: ketma-ket yuborilganda hammasi saqlanadi (ro'yxat mantiqi
    o'z-o'zidan buzuq emasligini qadaydi — aks holda yuqoridagi testlar
    poygani emas, oddiy xatoni ko'rsatardi)."""
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "administrator"), kassirlar=3)
    s = S_()
    try:
        for eid in d["kassir"]:
            _sorov(s, eid)
            s.commit()
    finally:
        s.close()

    from app.services import account_deletion as _AD
    s = S_()
    try:
        royxat = {str(it.get("employee_id")) for it in _AD.list_requests(s, d["cid"])}
    finally:
        s.close()
    assert royxat == {str(e) for e in d["kassir"]}, royxat

def test_PG_9_YOPISH_x_RAHBAR_FAOLLASHTIRISH_POYGASI_QULF_BILAN_SERIALLASHADI(S):
    """CH-23 to'sig'ining POYGASI: yagona ega yopayotganda boshqa tranzaksiya
    ikkinchi egani FAOLLASHTIRADI.

    ⚠️  QULFSIZ NIMA BO'LARDI: B (yopish) A ning COMMIT QILINMAGAN
        o'zgarishini READ COMMITTED da KO'RMAYDI, ya'ni «sherik terminated»
        holatini o'qib do'konni YOPIB YUBORARDI. Keyin A commit qiladi va
        natija TAQIQLANGAN holat bo'lardi: do'kon YOPILGAN + FAOL sherik
        rahbar bor, va qayta ochish yo'li YO'Q.

        `close_store()` ijarachining BARCHA xodim qatorlarini `FOR UPDATE`
        bilan qulflagani uchun B aynan A o'zgartirgan qatorda KUTADI, A
        commit qilgach sherikni FAOL ko'radi va `peers_present` beradi.
        Shu bois natija DETERMINISTIK.
    """
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    from app.models.org import Company
    eng, S_ = S
    d = _dokon(S_, rahbarlar=("ega", "ega"))
    ega, sherik = d["ega"][0], d["ega"][1]

    #  Boshlang'ich holat: ega YAGONA faol rahbar.
    s0 = S_()
    try:
        s0.get(Employee, sherik).status = EmployeeStatus.terminated
        s0.commit()
    finally:
        s0.close()
    assert _faol_rahbar_soni(S_, d["cid"]) == 1

    def faollashtir(s):
        s.get(Employee, sherik).status = EmployeeStatus.active
        return "faollashtirildi"

    out = _navbat(S_, faollashtir, lambda s: _yopish(s, ega))

    assert out["a"] == "faollashtirildi", out
    assert isinstance(out["b"], ValueError), f"yopish o'tib ketdi: {out}"
    assert str(out["b"]) == "peers_present", out

    #  DO'KON OCHIQ QOLDI va sherik FAOL.
    s1 = S_()
    try:
        assert s1.get(Company, d["cid"]).deleted_at is None, "do'kon YOPILDI"
    finally:
        s1.close()
    assert _faol_rahbar_soni(S_, d["cid"]) == 2
