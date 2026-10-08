# -*- coding: utf-8 -*-
"""`POST /historical/events` — JURNAL: takror, konflikt va HALOKAT TIKLANISHI.

EGA SHARTI, SO'ZMA-SO'Z: «Journal separate-session reservation bo'lsin va
IN_PROGRESS crashdan keyin abadiy 409 bermasin. Same event_key recovery
canonical state'ni tekshirib finalize yoki safe replay qilsin.»

HALOKAT OYNALARI (`services/historical_journal.py` sarlavhasi)
==============================================================
W1  rezervatsiya commit'idan OLDIN            -> hech narsa yo'q, keyingisi YANGI
W2  rezervatsiyadan keyin, yozuvchidan OLDIN  -> `started`, biznes qatori YO'Q
W3  yozuvchidan KEYIN, finalize'dan OLDIN     -> `started`, biznes qatori BOR  <-- ega ko'rsatgan oyna
W4  finalize'dan keyin                        -> `done`, saqlangan javob

W3 ni SIMULYATSIYA QILISH USULI. `finalise` ni yiqitamiz: yozuvchi o'z
tanasini allaqachon commit qilgan, jurnalning UPDATE'i esa commit bo'lmaydi.
Jarayonni haqiqatan o'ldirish bilan BAYT-AYNAN holat chiqadi, chunki
yozuvchi commit qilgandan keyin jurnal yangilanishining commit bo'lmasligi —
ikki holatda ham AYNI durable natija. Shundan keyin AYNI `event_key` qayta
yuboriladi va u YANGI sessiyada («restart») tiklanishi shart.

⚠️  NEGA BU TEST BO'SH EMAS. Agar rezervatsiya biznes sessiyasida yozilsa,
    `create_sale` ning retry'i (`services/sales.py:128-133`) `db.rollback()`
    bilan jurnal qatorini YO'Q QILARDI va bu test «qator yo'q» deb yiqilardi.
    Ya'ni test alohida-sessiya qarorining O'ZINI ham qadaydi.
"""
import uuid
from datetime import timedelta

import pytest

from tests._hist_scene import (D0, db_, env, jurnal, kalit, post, sahna,
                               smena_ochish)


def _halokat(monkeypatch):
    """`finalise` ni yiqitadi — W3 oynasi."""
    import app.services.historical_journal as HJ

    def _yiq(*a, **k):
        raise RuntimeError("HALOKAT SIMULYATSIYASI")
    monkeypatch.setattr(HJ, "finalise", _yiq)


# ══ 1. TAKROR — AYNI KALIT, AYNI MAZMUN ═════════════════════════════════

def test_TAKROR_ayni_natija_va_BITTA_biznes_qatori(client):
    from app.models.shifts import Shift
    s = sahna()
    e = env(s, event_type="shift_open", payload={"opening_cash": 1000},
            seq=["d1", "open"])
    r1, r2 = post(client, e), post(client, e)
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert r1.json()["duplicate"] is False
    assert r2.json()["duplicate"] is True
    assert r1.json()["result_id"] == r2.json()["result_id"], "natija SILJIDI"
    with db_() as db:
        n = db.query(Shift.id).filter(
            Shift.client_uuid == kalit(s, "d1", "open")).count()
        assert n == 1, f"{n} ta smena — DUBLIKAT"


def test_TAKROR_saqlangan_javobni_AYNAN_qaytaradi(client):
    s = sahna()
    sid = smena_ochish(client, s, opening=1000)
    yop = env(s, event_type="shift_close", at=D0 + timedelta(hours=9),
              payload={"shift_id": sid, "counted_cash": 1000}, seq=["d1", "close"])
    r1, r2 = post(client, yop), post(client, yop)
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert r2.json()["duplicate"] is True
    assert r1.json()["result"] == r2.json()["result"], "javob o'zgardi"


# ══ 2. KONFLIKT — AYNI KALIT, BOSHQA NARSA ══════════════════════════════

def test_BOSHQA_MAZMUN_konflikt_409(client):
    s = sahna()
    seq = ["d1", "open"]
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 1000}, seq=seq)).status_code == 200
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 2222}, seq=seq))
    assert r.status_code == 409 and "BOSHQA mazmun" in r.text, r.text


def test_BOSHQA_FILIAL_konflikt_409(client):
    """EGA QARORI (Ruling 4): branch kalitda EMAS, lekin hash'da va saqlanadi.

    ⚠️  NEGA KALITDA EMAS. `event_key` allaqachon do'kon+reja nom maydonidan
        chiqadi, ya'ni konstruksiya bo'yicha noyob. Branch'ni kalitga qo'shish
        kontraktni BO'SHATARDI — ayni reja hodisasini HAR FILIALDA bir marta
        yozishga ruxsat berardi. Shu bois: KONFLIKT, takror emas.

    ⚠️  Ikkinchi aktor kerak: 7-darvoza `actor_branch` tengligini talab qiladi
        va bir aktorning ikki biriktirilgan filialidan eng ESKISI tanlanadi.
    """
    s = sahna()
    seq = ["d1", "open"]
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 1000}, seq=seq)).status_code == 200
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 1000},
                         seq=seq, branch=s["b"], actor=s["eid_b"]))
    assert r.status_code == 409, r.text
    assert "BOSHQA filial" in r.text, (
        f"filial konflikti ALOHIDA diagnoz bo'lishi kerak, mazmun konflikti "
        f"emas: {r.text[:200]}")


def test_BOSHQA_HODISA_TURI_konflikt_409(client):
    s = sahna()
    seq = ["d1", "x"]
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 0}, seq=seq)).status_code == 200
    r = post(client, env(s, event_type="cash_payin", seq=seq,
                         payload={"type": "payin", "amount": 100}))
    assert r.status_code == 409 and "BOSHQA hodisa turi" in r.text, r.text


def test_BOSHQA_AKTOR_konflikt_409(client):
    """Aktor hash ichida: boshqa xodim bilan kelgan takror jimgina ikkinchi
    biznes qatori yaratmasin.

    Bu `create_sale` ning o'z xulqiga mos — `_replay_mismatch` kassirni
    solishtiradi va farq qilsa rad etadi.
    """
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.enums import EmployeeStatus
    from tests._hist_scene import NOW
    s = sahna()
    seq = ["d1", "payin"]
    smena_ochish(client, s, opening=5000)
    assert post(client, env(s, event_type="cash_payin", seq=seq,
                            payload={"type": "payin", "amount": 100})).status_code == 200
    #  AYNI A filialiga biriktirilgan IKKINCHI aktor (7-darvozadan o'tsin).
    with db_() as db:
        role = db.query(Role).filter(Role.code == "ega").one()
        e2 = Employee(id=uuid.uuid4(), company_id=uuid.UUID(s["cid"]),
                      role_id=role.id, full_name="D3 aktor A2",
                      phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                      status=EmployeeStatus.active, sec_epoch=0)
        db.add(e2)
        db.flush()
        db.add(EmployeeBranch(employee_id=e2.id, branch_id=uuid.UUID(s["a"])))
        db.commit()
        e2id = str(e2.id)
    r = post(client, env(s, event_type="cash_payin", seq=seq, actor=e2id,
                         payload={"type": "payin", "amount": 100}))
    assert r.status_code == 409 and "BOSHQA mazmun" in r.text, r.text


# ══ 3. HASH BARQARORLIGI (servis darajasida, HTTP'siz) ══════════════════

def test_HASH_ayni_payload_AYNI_hash():
    from app.services import historical_journal as HJ
    a = HJ.canonical(event_type="sale", occurred_at=D0, branch_id="b1",
                     actor_employee_id="e1",
                     payload={"items": [{"qty": 2, "price": 10}]})
    b = HJ.canonical(event_type="sale", occurred_at=D0, branch_id="b1",
                     actor_employee_id="e1",
                     payload={"items": [{"price": 10, "qty": 2}]})   # kalit tartibi
    assert HJ.payload_hash(a) == HJ.payload_hash(b), "kalit tartibi hash'ni o'zgartirdi"


def test_HASH_RO_YXAT_tartibi_MUHIM():
    """⚠️  Ro'yxat tartibi SAQLANADI (saralanmaydi).

    `lot_correction.py:195-197` bilan ayni sabab: tartib pastki oqimdagi
    kalitlarga kiradi, ya'ni tartib o'zgarishi BOSHQA so'rov demakdir.
    """
    from app.services import historical_journal as HJ
    k = dict(event_type="sale", occurred_at=D0, branch_id="b1",
             actor_employee_id="e1")
    a = HJ.canonical(**k, payload={"items": [{"qty": 1}, {"qty": 2}]})
    b = HJ.canonical(**k, payload={"items": [{"qty": 2}, {"qty": 1}]})
    assert HJ.payload_hash(a) != HJ.payload_hash(b)


def test_HASH_son_shakli_AHAMIYATSIZ_haqiqiy_yolda():
    """SON-tipli maydon turli matn shaklida kelsa ham AYNI hash.

    ⚠️  TEST HAQIQIY YO'LDAN O'TADI (`strict DTO` -> `model_dump(mode="json")`),
        `canonical()` ga xom lug'at bermaydi. Sabab: `_norm` xom SATRNI ataylab
        sonlashtirmaydi (pastdagi teskari kafolatga qarang), son-tipli maydonga
        kelgan `"2.000"` esa pydantic tomonidan `2.0` ga aylantiriladi. Ya'ni
        kanonlashtirish ikki qatlamning BIRGA ishlashi natijasi va shartnoma
        aynan shu birgalik.

    Aks holda ayni so'rov turli shaklda kelib YOLG'ON KONFLIKT berardi.
    """
    from app.api.v1.historical_exec import _ShiftOpenP
    from app.services import historical_journal as HJ
    k = dict(event_type="shift_open", occurred_at=D0, branch_id="b1",
             actor_employee_id="e1")

    def _h(xom):
        return HJ.payload_hash(HJ.canonical(
            **k, payload=_ShiftOpenP(opening_cash=xom).model_dump(mode="json")))

    hashlar = {_h(x) for x in ("2.000", "2", 2, 2.0)}
    assert len(hashlar) == 1, f"son shakli hash'ni o'zgartirdi: {hashlar}"
    #  ...lekin HAQIQIY farq SEZILISHI shart.
    assert _h(2.5) not in hashlar


def test_HASH_SATR_tipli_maydon_SONLASHTIRILMAYDI():
    """TESKARI KAFOLAT: `_norm` satrni son deb normallashtirmasin.

    ⚠️  NEGA MUHIM. Agar kanonlashtirish satrlarni ham sonlashtirsa,
        `reason="2.000"` va `reason="2"` BITTA hash berardi, ya'ni mazmunan
        BOSHQA ikki hodisa «takror» bo'lib ko'rinardi va ikkinchisi jimgina
        birinchining javobini olardi. Bu — ma'lumot yo'qotish, tezlik emas.
    """
    from app.api.v1.historical_exec import _CashPayinP
    from app.services import historical_journal as HJ
    k = dict(event_type="cash_payin", occurred_at=D0, branch_id="b1",
             actor_employee_id="e1")

    def _h(reason):
        return HJ.payload_hash(HJ.canonical(
            **k, payload=_CashPayinP(type="payin", amount=1,
                                     reason=reason).model_dump(mode="json")))

    assert _h("2.000") != _h("2"), "satr-tipli maydon sonlashtirilgan"


def test_HASH_BRANCH_va_AKTORNI_qamraydi():
    """Ega qarori: branch hash'da. Aktor ham."""
    from app.services import historical_journal as HJ
    k = dict(event_type="sale", occurred_at=D0, payload={"qty": 1})
    h1 = HJ.payload_hash(HJ.canonical(**k, branch_id="b1", actor_employee_id="e1"))
    h2 = HJ.payload_hash(HJ.canonical(**k, branch_id="b2", actor_employee_id="e1"))
    h3 = HJ.payload_hash(HJ.canonical(**k, branch_id="b1", actor_employee_id="e2"))
    assert len({h1, h2, h3}) == 3, "branch yoki aktor hash'ga kirmagan"


# ══ 4. HALOKAT TIKLANISHI — EGA SHARTINING MARKAZI ══════════════════════

@pytest.mark.parametrize("turi", ["shift_open", "sale", "cash_payin", "writeoff"])
def test_HALOKAT_W3_tiklanadi_va_DUBLIKAT_yoq(client, monkeypatch, turi):
    """Yozuvchi commit qilgan, finalize ULGURMAGAN -> qayta yuborishda TIKLANADI.

    Tasdiqlanadi: (a) halokatdan keyin jurnal `started`, biznes qatori BOR;
    (b) ayni kalit qayta yuborilsa 200 va `recovered: true`; (c) biznes
    qatori HAMON BITTA; (d) jurnal `done` va `result_id` to'ldirilgan.
    """
    from app.models.inventory import StockMovement
    from app.models.sales import Sale
    from app.models.shifts import CashMovement, Shift
    s = sahna()
    if turi in ("sale", "cash_payin", "writeoff"):
        smena_ochish(client, s, opening=5000)

    seq = ["d1", turi]
    payloadlar = {
        "shift_open": {"opening_cash": 1000},
        "sale": {"items": [{"product_id": s["pid"], "qty": 2, "price": 100}],
                 "payments": [{"method": "cash", "amount": 200}]},
        "cash_payin": {"type": "payin", "amount": 300, "reason": "kirim"},
        "writeoff": {"product_id": s["pid"], "qty": 1, "reason": "brak",
                     "branch_id": s["a"]},
    }
    e = env(s, event_type=turi, at=D0 + timedelta(hours=2),
            payload=payloadlar[turi], seq=seq)

    #  ── (a) HALOKAT ────────────────────────────────────────────────────────
    _halokat(monkeypatch)
    with pytest.raises(RuntimeError, match="HALOKAT"):
        post(client, e)

    k = kalit(s, *seq)
    row = jurnal(s["cid"], event_key=k)
    assert row is not None, "rezervatsiya YO'Q — alohida sessiyada commit bo'lmagan"
    assert row.status == "started", f"holat={row.status}"
    assert row.result_id is None and row.response_json is None

    def _sanoq():
        with db_() as db:
            if turi == "shift_open":
                return db.query(Shift.id).filter(Shift.client_uuid == k).count()
            if turi == "sale":
                return db.query(Sale.id).filter(Sale.client_uuid == k).count()
            if turi == "cash_payin":
                return db.query(CashMovement.id).filter(
                    CashMovement.client_uuid == k).count()
            return db.query(StockMovement.id).filter(
                StockMovement.client_uuid == k).count()

    assert _sanoq() == 1, (
        f"yozuvchi commit qilmagan — W3 oynasi qurilmadi ({turi})")

    #  ── (b) «RESTART»: halokat olib tashlanadi, AYNI kalit qayta yuboriladi ─
    monkeypatch.undo()
    r = post(client, e)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("recovered") is True, f"tiklanmadi: {j}"
    assert j["duplicate"] is True

    #  ── (c) DUBLIKAT YO'Q ─────────────────────────────────────────────────
    assert _sanoq() == 1, f"DUBLIKAT yozildi ({turi})"

    #  ── (d) jurnal YAKUNLANDI ─────────────────────────────────────────────
    row = jurnal(s["cid"], event_key=k)
    assert row.status == "done" and row.result_id is not None, row.status


def test_HALOKAT_shift_close_VAQT_GUVOHI_bilan_tiklanadi(client, monkeypatch):
    """`shift_close` — KALITI UMUMAN YO'Q hodisa, ega alohida ko'rsatgan.

    ⚠️  NEGA ENG QIYIN HOLAT. `close_shift_svc` `client_uuid` olmaydi va
        legacy `shifts` jadvali YOPGAN xodimni qayd etmaydi, ya'ni
        `status == closed` ni POS orqali yopilgan smena ham qondiradi. Takror
        chaqiruv esa 400 «Smena allaqachon yopilgan» beradi — ya'ni
        «tushmagan» deb o'qilsa hodisa ABADIY qotib qolardi.

        Yagona portativ atributsiya guvohi — `closed_at`: u `resolve_at(at)`
        dan yoziladi (`services/shifts.py:236`), ya'ni TARIXIY lahzaga teng
        bo'ladi; odam yoki POS yopsa devor-soati muhrlanadi.
    """
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = sahna()
    sid = smena_ochish(client, s, opening=1000)
    yopilish = D0 + timedelta(hours=9)
    e = env(s, event_type="shift_close", at=yopilish,
            payload={"shift_id": sid, "counted_cash": 1000}, seq=["d1", "close"])

    _halokat(monkeypatch)
    with pytest.raises(RuntimeError, match="HALOKAT"):
        post(client, e)

    k = kalit(s, "d1", "close")
    row = jurnal(s["cid"], event_key=k)
    assert row.status == "started"
    with db_() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        assert sh.status == ShiftStatus.closed, "yopilish commit bo'lmagan"

    #  Takror chaqiruv o'zi 400 berardi — tiklanish ZOND bilan bo'ladi.
    monkeypatch.undo()
    r = post(client, e)
    assert r.status_code == 200, (
        f"tiklanmadi — kalitsiz hodisa abadiy qotib qoldi: {r.text[:300]}")
    j = r.json()
    assert j.get("recovered") is True and j["result_id"] == sid, j
    #  Javob qatordan TIKLANADI (yozuvchi javobi saqlanmagan edi).
    assert j["result"]["counted_cash"] == 1000, j["result"]


def test_HALOKAT_VAQT_GUVOHI_mos_kelmasa_TIKLANMAYDI(client, monkeypatch):
    """Guvoh bo'sh emas: `closed_at` boshqa bo'lsa zond «tushmagan» deydi.

    ⚠️  Bu testsiz yuqoridagi tiklanish SOXTA POZITIV bo'lishi mumkin edi —
        ya'ni zond har qanday yopilgan smenani «bizning ishimiz» deb
        hisoblardi.
    """
    from app.models.shifts import Shift
    s = sahna()
    sid = smena_ochish(client, s, opening=1000)
    yopilish = D0 + timedelta(hours=9)
    e = env(s, event_type="shift_close", at=yopilish,
            payload={"shift_id": sid, "counted_cash": 1000}, seq=["d1", "close"])
    _halokat(monkeypatch)
    with pytest.raises(RuntimeError, match="HALOKAT"):
        post(client, e)
    #  Smenani «boshqa kimsa boshqa vaqtda yopgan» holatiga keltiramiz.
    with db_() as db:
        db.get(Shift, uuid.UUID(sid)).closed_at = yopilish + timedelta(hours=1)
        db.commit()
    monkeypatch.undo()
    r = post(client, e)
    #  Zond «tushmagan» deydi -> qayta dispatch -> yozuvchi 400 beradi.
    #  MUHIMI: jim «muvaffaqiyat» DEB HISOBLANMAYDI.
    assert r.status_code != 200, (
        f"zond SOXTA POZITIV berdi — vaqt guvohi ishlamayapti: {r.text[:200]}")


def test_HALOKAT_W2_yozuvchiga_yetmagan_bolsa_QAYTA_bajariladi(client, monkeypatch):
    """W2: rezervatsiya bor, biznes qatori YO'Q -> qayta yuborishda BAJARILADI.

    ⚠️  `started` qatori ABADIY 409 BERMASLIGINING ikkinchi yarmi: tiklanish
        «tushgan» deb ham, «qotib qolgan» deb ham taxmin qilmaydi — biznes
        jadvalini O'QIYDI va natijaga qarab finalize yoki BAJARADI.
    """
    from app.models.shifts import Shift
    s = sahna()
    seq = ["d1", "open"]
    e = env(s, event_type="shift_open", payload={"opening_cash": 1000}, seq=seq)
    k = kalit(s, *seq)

    #  Dispatch'ni yiqitamiz (yozuvchiga YETIB BORMAYDI).
    #  ⚠️  `ValueError` ATAYLAB, `RuntimeError` EMAS: tarixiy qatlamning
    #      `RuntimeError` i endi BAJARUVCHI SHARTNOMASI rad etishi hisoblanadi
    #      va 409 ga aylanadi. Halokatni modellashtirish uchun kutilMAGAN
    #      sinf kerak — u yuqoriga chiqadi, xuddi jarayon o'lgandek.
    import app.api.v1.historical_exec as HX
    monkeypatch.setattr(HX, "_dispatch_retry",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            ValueError("DISPATCH YIQILDI")))
    with pytest.raises(ValueError, match="DISPATCH"):
        post(client, e)

    row = jurnal(s["cid"], event_key=k)
    assert row is not None and row.status == "failed", (
        f"holat={getattr(row, 'status', None)} — dispatch xatosi `failed` "
        f"bo'lishi kerak")
    with db_() as db:
        assert db.query(Shift.id).filter(Shift.client_uuid == k).count() == 0

    #  Qayta yuborish: zond hech narsa topmaydi -> AYNI qator qayta ishlatiladi.
    monkeypatch.undo()
    r = post(client, e)
    assert r.status_code == 200, r.text
    assert r.json()["duplicate"] is False, r.json()
    with db_() as db:
        assert db.query(Shift.id).filter(Shift.client_uuid == k).count() == 1
    row = jurnal(s["cid"], event_key=k)
    assert row.status == "done"
    #  Yangi kalit MINTILMAGAN — jurnal qatori BITTA.
    assert len([x for x in jurnal(s["cid"]) if x.event_key == k]) == 1


def test_REZERVATSIYA_dispatchdan_OLDIN_commit_qilinadi(client, monkeypatch):
    """Rezervatsiya biznes tranzaksiyasining ROLLBACK'idan OMON QOLADI.

    ⚠️  SHU TEST NIMANI ISBOTLAYDI VA NIMANI ISBOTLAMAYDI — halol chegara.

        ISBOTLAYDI: rezervatsiya DISPATCHDAN OLDIN commit qilinadi, shu bois
        biznes tranzaksiyasi rollback bo'lsa ham qator QOLADI. Agar `claim`
        faqat `flush` qilsa, yozuvchining `db.rollback()` i qatorni
        sessiyadan CHIQARIB TASHLARDI (o'lchangan: SQLAlchemy 2.0.52) va
        noyob indeks hakamlik qilmasdi — `create_sale` ning retry halqasi
        (`services/sales.py:128-133`) aynan shu yo'ldan yuradi.

        ISBOTLAMAYDI: jurnal ALOHIDA sessiyada ekanini. `claim` darhol commit
        qilgani uchun umumiy sessiyada ham qator durable bo'ladi, ya'ni bu
        testni alohida-sessiya mutatsiyasi OQIB O'TADI. Alohida sessiyaning
        jonli qiymati Postgres'da ko'rinadi (aborted tranzaksiyada `mark_failed`
        izni YOZA OLADI) va u `tests/cash/test_historical_journal_pg.py` da
        o'lchanadi.
    """
    import app.api.v1.historical_exec as HX
    s = sahna()
    seq = ["d1", "x"]
    monkeypatch.setattr(HX, "_dispatch_retry",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            ValueError("BIZNES YIQILDI")))
    with pytest.raises(ValueError, match="BIZNES"):
        post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, seq=seq))
    row = jurnal(s["cid"], event_key=kalit(s, *seq))
    assert row is not None, (
        "jurnal qatori YO'Q — rezervatsiya biznes sessiyasida yozilgan va "
        "rollback uni o'chirib tashlagan")
    assert row.error and "BIZNES" in row.error, row.error


def test_INDEKS_yoq_bolsa_YOZUV_BOSHLANMAYDI(client, monkeypatch):
    """`require_index` fail-closed: kafolat isbotlanmasa rezervatsiya yo'q.

    ⚠️  NEGA MUHIM. `ux_hist_plan_event` — `shift_open` va `shift_close` uchun
        YAGONA tranzaksion hakam (`ux_shifts_client_uuid` butun repoda MAVJUD
        EMAS, `close_shift_svc` esa kalit umuman olmaydi). Indeks yo'q bo'lsa
        dedup faqat SELECT-oldin-tekshiruviga tayanardi — klassik TOCTOU.
    """
    import app.core.index_guard as IG
    s = sahna()
    asl = IG.index_state
    chaqirildi = []

    def _faqat_jurnal(bind, index, table, **kw):
        #  ⚠️  FAQAT O'Z INDEKSIMIZ buziladi. Ilgari bu yerda `index_state`
        #      GLOBAL almashtirilgan edi va 409 ni `open_shift_svc` ning O'Z
        #      gardi (`ux_shifts_cashier_open`, `services/shifts.py:101`)
        #      berardi — ya'ni test o'z gardini UMUMAN o'lchamasdi va
        #      mutatsiya (gardni olib tashlash) OQIB KETARDI.
        if index == "ux_hist_plan_event":
            chaqirildi.append(index)
            return "BAD"
        return asl(bind, index, table, **kw)

    monkeypatch.setattr(IG, "index_state", _faqat_jurnal)
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 409, r.text
    assert chaqirildi == ["ux_hist_plan_event"], (
        "jurnal indeksi gardi UMUMAN chaqirilmagan")
    from tests._hist_scene import yozuv_yoq
    yozuv_yoq(s["cid"])


def test_HALOKAT_FAILED_qatori_HAM_tiklanadi(client, monkeypatch):
    """`failed` deb belgilangan qator ham ZONDLANADI — qotib qolish YO'Q.

    ⚠️  QOPLANMAGAN HOLAT EDI. `mark_failed` istisno bo'yicha qo'yiladi, istisno
        esa yozuvchi COMMIT QILGANDAN KEYIN ham yuzaga kelishi mumkin (masalan
        natija id'sini o'qishda yoki `_bajar` ning keyingi qatorlarida). Agar
        `failed` zondsiz «qayta bajaramiz» deb olinsa, `shift_close` uchun qayta
        dispatch 400 «Smena allaqachon yopilgan» berib hodisani ABADIY QOTIRIB
        qo'yardi — ya'ni ayni taqiqlangan holat, faqat `started` emas `failed`
        nomi ostida.

    Bu yerda yozuvchi HAQIQATAN ishlatiladi, so'ng istisno ko'tariladi: qator
    `failed`, biznes qatori esa MAVJUD.
    """
    import app.api.v1.historical_exec as HX
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = sahna()
    sid = smena_ochish(client, s, opening=1000)
    yopilish = D0 + timedelta(hours=9)
    e = env(s, event_type="shift_close", at=yopilish,
            payload={"shift_id": sid, "counted_cash": 1000}, seq=["d1", "close"])

    asl = HX._dispatch_retry

    def _ishlat_va_yiq(*a, **kw):
        asl(*a, **kw)                     # YOZUVCHI haqiqatan ishlaydi (commit)
        raise ValueError("FINALIZEDAN OLDIN YIQILDI")

    monkeypatch.setattr(HX, "_dispatch_retry", _ishlat_va_yiq)
    with pytest.raises(ValueError, match="FINALIZEDAN OLDIN"):
        post(client, e)

    k = kalit(s, "d1", "close")
    row = jurnal(s["cid"], event_key=k)
    assert row.status == "failed", f"holat={row.status}"
    with db_() as db:
        assert db.get(Shift, uuid.UUID(sid)).status == ShiftStatus.closed, (
            "yozuvchi commit qilmagan — sahna qurilmadi")

    #  Qayta yuborish: `failed` bo'lsa ham ZOND ishlaydi va TIKLAYDI.
    monkeypatch.undo()
    r = post(client, e)
    assert r.status_code == 200, (
        f"`failed` qatori qotib qoldi — zond ishlamagan: {r.text[:300]}")
    assert r.json().get("recovered") is True, r.json()
    assert r.json()["result_id"] == sid
    row = jurnal(s["cid"], event_key=k)
    assert row.status == "done" and row.error is None, (row.status, row.error)
