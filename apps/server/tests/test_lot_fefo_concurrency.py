# -*- coding: utf-8 -*-
"""PHASE 2 — HAQIQIY POSTGRES: konkurrentlik va tranzaksiya chegarasi.

⚠️  NEGA SQLite YETMAYDI. `with_for_update()` SQLite'da BEZARAR NO-OP. Ya'ni
    mahalliy to'plam «ikki kassa bir partiyani sotdi» holatini UMUMAN o'lchamaydi
    va qulf mantig'idagi xato JIMGINA o'tib ketardi. Bu loyihada aynan shunday
    dialekt bo'shlig'i ilgari ham bo'lgan (`BOOLEAN DEFAULT 0`).
"""
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

NOW = datetime.now(timezone.utc)
D10 = (NOW + timedelta(days=10)).date()
SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def pg():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp())
    u = srv.get_uri()
    url = ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, timeout=900,
                       env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()
        try:
            srv.cleanup()
        except Exception:      # noqa: BLE001
            pass


def _mk(eng):
    """⚠️  ILOVA BILAN AYNI sozlama. `Session(eng)` da `autoflush=True` bo'ladi,
    ilova esa `autoflush=False` ishlatadi (app/db/session.py:45). Farq testni
    BOSHQA tizimni o'lchaydigan qilib qo'yardi — va aynan shunday bo'ldi:
    autoflush qisman flush chaqirib, FK tartibini buzgan edi."""
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False,
                        class_=Session)()


def _seed(eng, *, lot_qty):
    """Bitta kompaniya + filial + xodim + KUZATUVLI mahsulot + bitta partiya."""
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory, StockBatch
    from app.models.org import Branch, Company
    s = _mk(eng)
    co = Company(id=uuid.uuid4(), name="C", code="c" + uuid.uuid4().hex[:8], currency="UZS")
    s.add(co); s.flush()
    br = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B",
                timezone="Asia/Tashkent", is_active=True)
    s.add(br); s.flush()
    role = s.query(Role).first()
    unit = s.query(Unit).first()
    emp = Employee(id=uuid.uuid4(), company_id=co.id, full_name="K",
                   phone="+9989" + uuid.uuid4().int.__str__()[:8], role_id=role.id)
    s.add(emp); s.flush()
    p = Product(id=uuid.uuid4(), company_id=co.id, name="Konkurrent " + uuid.uuid4().hex[:6],
                article_code="K-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                track_lots=True, track_expiry=False, lots_activated_at=NOW)
    s.add(p); s.flush()
    s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=br.id,
                    qty=Decimal(str(lot_qty)), min_qty=0, updated_at=NOW))
    s.add(StockBatch(id=uuid.uuid4(), company_id=co.id, branch_id=br.id, product_id=p.id,
                     qty=Decimal(str(lot_qty)), received_qty=Decimal(str(lot_qty)),
                     remaining_qty=Decimal(str(lot_qty)), unit_cost=Decimal("50"),
                     expiry_date=D10, status="open", source_type="receiving",
                     client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                     updated_at=NOW, row_version=1))
    s.commit()
    out = (co.id, br.id, emp.id, p.id)
    s.close()
    return out


def _concurrent(eng, fn_a, fn_b):
    """Ikki tranzaksiyani AYNI lahzada boshlaydi (tests/cash naqshi)."""
    barrier = threading.Barrier(2)
    out = {}

    def wrap(key, fn):
        s = _mk(eng)
        try:
            barrier.wait(timeout=20)
            out[key] = fn(s)
        except Exception as e:      # noqa: BLE001
            out[key] = e
        finally:
            s.close()

    ta = threading.Thread(target=wrap, args=("a", fn_a))
    tb = threading.Thread(target=wrap, args=("b", fn_b))
    ta.start(); tb.start(); ta.join(); tb.join()
    return out.get("a"), out.get("b")


def _sell_fn(emp_id, pid, qty):
    from app.models.auth import Employee
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale

    def go(s: Session):
        emp = s.get(Employee, emp_id)
        return create_sale(s, emp, SaleCreate(
            items=[{"product_id": str(pid), "qty": qty, "unit_price": 100}],
            payment_method="cash", given_amount=qty * 100 + 1000,
            client_uuid=uuid.uuid4()))
    return go


def _state(eng, pid, bid):
    from app.models.inventory import Inventory, StockBatch
    s = _mk(eng)
    inv = s.query(Inventory).filter(Inventory.product_id == pid,
                                    Inventory.branch_id == bid).first()
    lots = s.query(StockBatch).filter(StockBatch.product_id == pid).all()
    out = (Decimal(str(inv.qty)), [Decimal(str(l.remaining_qty)) for l in lots],
           [l.source_type for l in lots])
    s.close()
    return out


# ══ IKKI KASSA — BITTA PARTIYA ══════════════════════════════════════════════

def test_IKKI_kassa_AYNI_5_donani_sotolmaydi(pg):
    """Lot A = 5. Ikkala kassa 4 tadan so'raydi.

    Kutilgan: BITTASI o'tadi, ikkinchisi RAD etiladi. Partiya HECH QACHON
    manfiyga tushmaydi (-3 bo'lib qolmaydi).
    """
    cid, bid, eid, pid = _seed(pg, lot_qty=5)
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 4), _sell_fn(eid, pid, 4))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    assert len(oks) == 1, f"ikkalasi ham o'tdi -> oversell! a={ra} b={rb}"
    assert len(errs) == 1, f"ikkalasi ham yiqildi: a={ra} b={rb}"
    inv, rems, _ = _state(pg, pid, bid)
    assert all(r >= 0 for r in rems), f"partiya MANFIYGA tushdi: {rems}"
    assert inv == Decimal("1.000"), inv
    assert sum(rems) == inv, "invariant buzildi"


def test_konkurrent_sotuvdan_keyin_INVARIANT_saqlanadi(pg):
    cid, bid, eid, pid = _seed(pg, lot_qty=10)
    _concurrent(pg, _sell_fn(eid, pid, 3), _sell_fn(eid, pid, 3))
    from app.services import stock_invariant as SI
    s = _mk(pg)
    try:
        rep = SI.check(s, cid, [pid])
        assert rep.ok, [str(m) for m in rep.mismatches]
    finally:
        s.close()


def test_ikkalasi_ham_sigsa_IKKALASI_ham_otadi(pg):
    """Musbat nazorat: qulf ortiqcha rad etmasin."""
    cid, bid, eid, pid = _seed(pg, lot_qty=10)
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 4), _sell_fn(eid, pid, 4))
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    assert not errs, f"qulf ortiqcha rad etdi: {errs}"
    inv, rems, _ = _state(pg, pid, bid)
    assert inv == Decimal("2.000") and sum(rems) == inv


# ══ TRANZAKSIYA CHEGARASI — HAR BOSQICHDAN KEYIN ROLLBACK ═══════════════════

@pytest.mark.parametrize("nuqta", ["ulush", "partiya", "qoldiq", "harakat", "naqd"])
def test_har_bosqichdan_keyingi_xato_BUTUN_sotuvni_QAYTARADI(pg, monkeypatch, nuqta):
    """Bitta tranzaksiya: biror bosqichdan keyin yiqilsa HECH NARSA qolmasin."""
    from app.models.sales import Sale
    from app.services import lot_fefo as LF
    cid, bid, eid, pid = _seed(pg, lot_qty=10)
    inv0, rems0, _ = _state(pg, pid, bid)

    # Har nuqta uchun sotuv oqimidagi mos qadamdan KEYIN portlatamiz.
    if nuqta == "ulush":
        _orig = LF.apply
        def boom(*a, **k):
            _orig(*a, **k)
            raise RuntimeError("sun'iy xato: ulushdan keyin")
        monkeypatch.setattr(LF, "apply", boom)
    elif nuqta == "partiya":
        _orig = LF.plan
        def boom(*a, **k):
            r = _orig(*a, **k)
            raise RuntimeError("sun'iy xato: taqsimotdan keyin")
        monkeypatch.setattr(LF, "plan", boom)
    else:
        import app.services.sales as S
        _key = {"qoldiq": "_D", "harakat": "_D", "naqd": "_D"}
        # Qoldiq/harakat/naqd bosqichlari uchun eng kech nuqta: commit OLDIDAN.
        from app.services import stock_invariant as _SI
        _orig = _SI.assert_ok
        def boom(*a, **k):
            _orig(*a, **k)
            raise RuntimeError(f"sun'iy xato: {nuqta} dan keyin")
        monkeypatch.setattr(_SI, "assert_ok", boom)

    s = _mk(pg)
    try:
        with pytest.raises(Exception):
            _sell_fn(eid, pid, 4)(s)
    finally:
        s.rollback()
        s.close()

    inv1, rems1, _ = _state(pg, pid, bid)
    assert inv1 == inv0, f"{nuqta}: qoldiq o'zgardi {inv0} -> {inv1}"
    assert rems1 == rems0, f"{nuqta}: partiya qoldig'i o'zgardi"
    s = _mk(pg)
    try:
        assert s.query(Sale).filter(Sale.company_id == cid).count() == 0, \
            f"{nuqta}: yiqilgan sotuv bazada QOLDI"
        from app.models.inventory import SaleItemLotAllocation
        assert s.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == pid).count() == 0, \
            f"{nuqta}: ulushlar QOLDI"
    finally:
        s.close()


# ══ PHASE 2.5 — CHEK RAQAMI ARTIQ SERIALIZATOR EMAS ═════════════════════════

def test_IKKI_kassa_HAR_XIL_chek_raqami_oladi(pg):
    """Zaxira YETARLI -> ikkala sotuv ham o'tadi va raqamlar HAR XIL.

    ⚠️  Phase 2 da bu MUMKIN EMAS edi: `Sale` qatori `receipt_no="TMP"` bilan
        tranzaksiya boshida yozilardi va `UNIQUE(company_id, receipt_no)` ikki
        parallel sotuvni AYNAN shu satrda to'qnashtirardi. Ya'ni chek raqami
        butun sotuvni serializatsiya qilardi va qulf isbotini imkonsiz qilardi.
    """
    from app.models.sales import Sale
    cid, bid, eid, pid = _seed(pg, lot_qty=50)
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 5), _sell_fn(eid, pid, 5))
    errs = [r for r in (ra, rb) if isinstance(r, Exception)]
    assert not errs, f"chek raqami hamon to'qnashmoqda: {errs}"
    nos = sorted(r.receipt_no for r in (ra, rb))
    assert len(set(nos)) == 2, f"bir xil chek raqami: {nos}"
    s = _mk(pg)
    try:
        assert s.query(Sale).filter(Sale.company_id == cid).count() == 2
    finally:
        s.close()


def test_chek_raqamlari_UZLUKSIZ(pg):
    """Hisoblagich uzluksiz — `SEQUENCE` bo'lsa bekor qilinganda raqam yo'qolardi."""
    cid, bid, eid, pid = _seed(pg, lot_qty=50)
    nos = []
    for _ in range(4):
        s = _mk(pg)
        try:
            nos.append(int(_sell_fn(eid, pid, 1)(s).receipt_no.lstrip("#")))
        finally:
            s.close()
    assert nos == list(range(nos[0], nos[0] + 4)), nos


def test_yiqilgan_sotuv_RAQAMNI_yoqotmaydi(pg):
    """Bekor qilingan tranzaksiya hisoblagichni ham qaytaradi (uzluksizlik)."""
    from app.services import stock_invariant as _SI
    cid, bid, eid, pid = _seed(pg, lot_qty=50)
    s = _mk(pg)
    try:
        first = int(_sell_fn(eid, pid, 1)(s).receipt_no.lstrip("#"))
    finally:
        s.close()
    # Sun'iy yiqilish: invariant darvozasi commit'dan oldin portlaydi.
    _orig = _SI.assert_ok
    try:
        _SI.assert_ok = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sun'iy"))
        s = _mk(pg)
        try:
            try:
                _sell_fn(eid, pid, 1)(s)
            except Exception:      # noqa: BLE001
                pass
        finally:
            s.rollback(); s.close()
    finally:
        _SI.assert_ok = _orig
    s = _mk(pg)
    try:
        nxt = int(_sell_fn(eid, pid, 1)(s).receipt_no.lstrip("#"))
    finally:
        s.close()
    assert nxt == first + 1, f"yiqilgan sotuv raqam yo'qotdi: {first} -> {nxt}"


# ══ PHASE 2.5 — HAQIQIY QULF ISBOTI ═════════════════════════════════════════

def test_HAQIQIY_qulf_isboti_oversell_YOQ(pg):
    """Lot A = 5, ikkala kassa 4 tadan.

    ⚠️  SAQLANISH QONUNI bilan tekshiriladi, yakuniy raqamlar bilan EMAS.
        Avvalgi tahrir `len(oks) == 1` va `inv == 1` deb yozilgandi va u
        ZAIF edi: yo'qolgan yangilanishda (lost update) IKKALA sotuv ham
        commit bo'ladi, lekin yakuniy qoldiq baribir 1 bo'lib ko'rinadi —
        ya'ni kitob to'g'ri, ombor esa bo'sh. Buni o'lchov bilan ko'rdim:

            QULFSIZ -> sotuvlar=2  qoldiq=1.000  partiyalar=[1.000]
            (5 donadan 8 dona sotilgan)

        To'g'ri savol: SOTILGAN miqdor KAMAYGAN miqdorga tengmi.
    """
    from app.models.sales import Sale, SaleItem
    cid, bid, eid, pid = _seed(pg, lot_qty=5)
    inv0, rems0, _ = _state(pg, pid, bid)
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 4), _sell_fn(eid, pid, 4))
    inv1, rems1, _ = _state(pg, pid, bid)

    s = _mk(pg)
    try:
        sold = s.query(func.coalesce(func.sum(SaleItem.qty), 0)).join(
            Sale, Sale.id == SaleItem.sale_id).filter(
            Sale.company_id == cid).scalar()
    finally:
        s.close()
    sold = Decimal(str(sold or 0))
    consumed = inv0 - inv1
    assert sold == consumed, (
        f"SAQLANISH BUZILDI: {sold} dona sotilgan, lekin qoldiq faqat "
        f"{consumed} kamaygan (yo'qolgan yangilanish)")
    assert sold <= inv0, f"{inv0} donadan {sold} dona sotildi -> OVERSELL"
    assert all(r >= 0 for r in rems1), f"JISMONIY partiya manfiy: {rems1}"
    assert sum(rems1) == inv1, "invariant buzildi"


def test_qarz_jadvali_konkurrentlikda_ham_TOZA(pg):
    """Konkurrent onlayn sotuvlar QARZ yaratmasligi shart (faqat replay yaratadi)."""
    from app.models.inventory import LotShortfall
    cid, bid, eid, pid = _seed(pg, lot_qty=5)
    _concurrent(pg, _sell_fn(eid, pid, 4), _sell_fn(eid, pid, 4))
    s = _mk(pg)
    try:
        assert s.query(LotShortfall).filter(
            LotShortfall.product_id == pid).count() == 0
    finally:
        s.close()

def test_OLTI_kassa_BARCHASI_otadi(pg):
    """6 ta parallel sotuv — HAMMASI o'tishi va raqamlar NOYOB bo'lishi shart.

    ⚠️  BU TEST TAQSIMLAGICHNI O'LCHAYDI. Eski `count()+1` da parallel sotuvlar
        BIR XIL raqam olib `UNIQUE(company_id, receipt_no)` ni buzardi; retry
        o'rami esa ATIGI 3 urinish beradi. Ikki oqimda retry odatda yetardi
        (shu bois kichik sinov nuqsonni KO'RMASDI), lekin oqim soni oshgach
        urinishlar tugab, sotuv «Kassa band — qayta urinib ko'ring» (409) bilan
        RAD etiladi. Ya'ni eski yo'lda konkurrentlik CHEKLANGAN edi.
    """
    import threading
    from app.models.sales import Sale
    cid, bid, eid, pid = _seed(pg, lot_qty=500)
    N = 6
    out = {}
    barrier = threading.Barrier(N)

    def go(k):
        s = _mk(pg)
        try:
            barrier.wait(timeout=30)
            out[k] = _sell_fn(eid, pid, 1)(s)
        except Exception as e:      # noqa: BLE001
            out[k] = e
        finally:
            s.close()

    ts = [threading.Thread(target=go, args=(i,)) for i in range(N)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    errs = [v for v in out.values() if isinstance(v, Exception)]
    assert not errs, f"{len(errs)}/{N} sotuv RAD etildi: {[str(e)[:70] for e in errs]}"
    nos = [v.receipt_no for v in out.values()]
    assert len(set(nos)) == N, f"chek raqamlari takrorlandi: {sorted(nos)}"
    s = _mk(pg)
    try:
        assert s.query(Sale).filter(Sale.company_id == cid).count() == N
    finally:
        s.close()
