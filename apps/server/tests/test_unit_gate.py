# -*- coding: utf-8 -*-
"""Q1 — BIRLIK DARVOZASI (markaziy invariant) uchun birlik testlari.

    Unit.allow_fraction == False -> miqdor MATEMATIK BUTUN bo'lishi SHART
    Unit.allow_fraction == True  -> kasr ruxsat

Bu fayl FAQAT `app/services/unit_gate.py` ni o'lchaydi (bazasiz qism + bazali
xarita). Yozuvchilar (sotuv, kirim, hisobdan chiqarish, sanoq, qaytarish)
alohida fayllarda sinaladi.
"""
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services import unit_gate as UG

# Brief'dagi matritsa — AYNAN shu qiymatlar.
BUTUN_YAROQLI = [1, 2, "2.0", "2.000", 2.0, Decimal("2.000"), 0, 100, "1e2"]
BUTUN_YAROQSIZ = ["0.5", "1.5", "2.001", "0.25", 0.5, 1.5, 2.001, 0.25, Decimal("0.001")]
KASR_YAROQLI = ["0.5", "1.5", "2.001", 0.5, 1.5, 2.001, 0.426, 1, "2.000"]


# ── is_integral: sof matematika, bazasiz ────────────────────────────────────
@pytest.mark.parametrize("v", BUTUN_YAROQLI)
def test_is_integral_butun(v):
    assert UG.is_integral(v) is True, v


@pytest.mark.parametrize("v", BUTUN_YAROQSIZ)
def test_is_integral_kasr(v):
    assert UG.is_integral(v) is False, v


def test_is_integral_float_artefaktida_YIQILMAYDI():
    """Float modulo (`v % 1 == 0`) aynan shu joyda yiqilardi — `Decimal(str(v))` esa yo'q."""
    assert UG.is_integral(0.1 + 0.2) is False          # 0.30000000000000004
    assert UG.is_integral(3 * 0.1) is False            # 0.30000000000000004
    assert UG.is_integral(1e18) is True
    # 2.0000000000000004 (float artefakti) BUTUN EMAS — jim yaxlitlanmasin.
    assert UG.is_integral(2 + 4e-16) is False


def test_is_integral_yaroqsiz_kirish_RAD():
    for bad in ("abc", "", None, float("nan"), float("inf"), float("-inf")):
        assert UG.is_integral(bad) is False, bad


# ── check_qty: birlik bayrog'i bilan ───────────────────────────────────────
def test_check_qty_bolinmas_vs_kasr():
    for v in BUTUN_YAROQLI:
        assert UG.check_qty(False, v) is True, v
    for v in BUTUN_YAROQSIZ:
        assert UG.check_qty(False, v) is False, v
    for v in KASR_YAROQLI:
        assert UG.check_qty(True, v) is True, v


def test_check_qty_None_tekshirmaydi():
    """Birlik NOMA'LUM (xaritada yo'q) — bu darvoza rad etmaydi; chaqiruvchining
    o'z «mahsulot topilmadi» tekshiruvi ishlaydi (qarang modul sarlavhasi)."""
    assert UG.check_qty(None, "0.5") is True


# ── Bazali qism: fraction_map + validate_* ────────────────────────────────
def _mahsulot(db, cid, unit_code: str, nom: str):
    """Berilgan birlik kodidagi mahsulot (seed birliklari: dona/upak=False, kg/litr=True)."""
    from app.models.catalog import Product, Unit
    u = db.query(Unit).filter_by(code=unit_code).first()
    assert u is not None, f"seed birligi yo'q: {unit_code}"
    p = Product(company_id=cid, name=nom, unit_id=u.id, article_code=uuid.uuid4().hex[:12],
                base_sell_price=1000, base_buy_price=500)
    db.add(p)
    db.flush()
    return p, u


@pytest.fixture()
def muhit(client):
    """Bitta do'kon + dona/kg mahsulotlari (to'g'ridan-to'g'ri bazada — API yo'li emas)."""
    from tests.test_receipt_settings import _db, _dokon
    d = _dokon(client, name="Birlik darvozasi")
    with _db() as db:
        cid = uuid.UUID(d["cid"])
        p_dona, u_dona = _mahsulot(db, cid, "dona", "Non (dona)")
        p_kg, u_kg = _mahsulot(db, cid, "kg", "Shakar (kg)")
        p_upak, _ = _mahsulot(db, cid, "upak", "Choy (upak)")
        db.commit()
        out = {"cid": cid, "dona": p_dona.id, "kg": p_kg.id, "upak": p_upak.id,
               "h": d["h"], "u_dona": u_dona.id, "u_kg": u_kg.id}
    return out


def test_seed_birliklari_kutilgandek(muhit):
    """`dona`/`upak` bo'linmas, `kg`/`litr` kasrli — kontraktning asosi."""
    from app.models.catalog import Unit
    from tests.test_receipt_settings import _db
    with _db() as db:
        got = {u.code: u.allow_fraction for u in db.query(Unit).all()}
    assert got.get("dona") is False and got.get("upak") is False
    assert got.get("kg") is True and got.get("litr") is True


def test_fraction_map_bazadan_oqiydi(muhit):
    from tests.test_receipt_settings import _db
    with _db() as db:
        m = UG.fraction_map(db, [muhit["dona"], muhit["kg"], muhit["upak"]])
    assert m[muhit["dona"]] is False
    assert m[muhit["upak"]] is False
    assert m[muhit["kg"]] is True


def test_fraction_map_BITTA_sorov(muhit):
    """N+1 bo'lmasin: 3 mahsulot uchun ham BITTA SELECT."""
    from sqlalchemy import event
    from tests.test_receipt_settings import _db
    with _db() as db:
        bind = db.get_bind()
        n = []

        def _count(*_a, **_k):
            n.append(1)

        event.listen(bind, "before_cursor_execute", _count)
        try:
            UG.fraction_map(db, [muhit["dona"], muhit["kg"], muhit["upak"]])
        finally:
            event.remove(bind, "before_cursor_execute", _count)
    assert len(n) == 1, f"so'rov soni {len(n)} (N+1 regressiyasi)"


def test_fraction_map_notanish_id_XARITADA_YOQ(muhit):
    from tests.test_receipt_settings import _db
    begona = uuid.uuid4()
    with _db() as db:
        m = UG.fraction_map(db, [muhit["dona"], begona])
    assert begona not in m
    assert UG.check_qty(m.get(begona), "0.5") is True   # tekshirilmaydi


def test_fraction_map_bosh_royxat(muhit):
    from tests.test_receipt_settings import _db
    with _db() as db:
        assert UG.fraction_map(db, []) == {}
        assert UG.fraction_map(db, [None, None]) == {}


# ── validate_lines: XOM qator, AGREGATSIYADAN OLDIN ───────────────────────
def test_validate_lines_butun_otadi(muhit):
    from tests.test_receipt_settings import _db
    with _db() as db:
        UG.validate_lines(db, [(muhit["dona"], 2), (muhit["dona"], "3.000"),
                               (muhit["upak"], 1), (muhit["kg"], "0.426")])


@pytest.mark.parametrize("bad", ["0.5", "1.5", "2.001", "0.25"])
def test_validate_lines_kasr_RAD(muhit, bad):
    from tests.test_receipt_settings import _db
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            UG.validate_lines(db, [(muhit["dona"], bad)])
    assert e.value.status_code == 400
    assert UG.FRACTION_NOT_ALLOWED in e.value.detail
    assert "Non (dona)" in e.value.detail        # mahsulot nomi matnda
    assert e.value.headers is None or "X-Error-Code" not in (e.value.headers or {})


def test_validate_lines_AGREGATSIYA_YUVISHI_TOSILADI(muhit):
    """0.5 + 0.5 = 1 — jami BUTUN, lekin HAR QATOR alohida tekshiriladi va RAD etiladi.

    Bu darvozaning MA'NOSI: agar validatsiya yig'indidan keyin bo'lsa, yaroqsiz
    kirish arifmetika bilan «yuvilib» o'tib ketardi.
    """
    from tests.test_receipt_settings import _db
    jami = Decimal("0.5") + Decimal("0.5")
    assert jami == Decimal("1") and UG.is_integral(jami)    # jami YAROQLI ko'rinadi
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            UG.validate_lines(db, [(muhit["dona"], "0.5"), (muhit["dona"], "0.5")])
    assert e.value.status_code == 400


def test_validate_lines_kasr_birlik_TEGILMAYDI(muhit):
    from tests.test_receipt_settings import _db
    with _db() as db:
        UG.validate_lines(db, [(muhit["kg"], "0.5"), (muhit["kg"], "1.5"),
                               (muhit["kg"], "2.001"), (muhit["kg"], "0.426")])


def test_validate_one_va_with_map(muhit):
    from tests.test_receipt_settings import _db
    with _db() as db:
        UG.validate_one(db, muhit["kg"], "0.5")
        with pytest.raises(HTTPException):
            UG.validate_one(db, muhit["dona"], "0.5")
        fmap = UG.fraction_map(db, [muhit["dona"], muhit["kg"]])
    # Xarita bilan — qo'shimcha so'rovsiz (db=None)
    UG.validate_with_map(fmap, [(muhit["kg"], "0.5"), (muhit["dona"], 3)])
    with pytest.raises(HTTPException) as e:
        UG.validate_with_map(fmap, [(muhit["dona"], "0.5")])
    assert e.value.status_code == 400


def test_validate_lines_YAXLITLAMAYDI(muhit):
    """Darvoza faqat RAD etadi — qiymatni O'ZGARTIRMAYDI (yaxlitlash/kesish TAQIQ)."""
    from tests.test_receipt_settings import _db
    lines = [(muhit["dona"], "0.5")]
    with _db() as db:
        with pytest.raises(HTTPException):
            UG.validate_lines(db, lines)
    assert lines == [(muhit["dona"], "0.5")]     # kirish o'zgarmagan
