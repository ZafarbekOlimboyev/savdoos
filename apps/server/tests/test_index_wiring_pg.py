# -*- coding: utf-8 -*-
"""INDEKS KAFOLATI JONLI PUL YOZUVCHILARIDA — HAQIQIY Postgres, HAQIQIY marshrutlar.

NEGA BU FAYL BOR
================
`index_guard.require_index` ilgali FAQAT uch joyda simlangan edi (`doc_seq`,
`subscription/lifecycle`, `subscription/payments`). Idempotentlik indekslari esa
`IDEMPOTENCY_INDEXES` da turardi: ularning yo'qolishi boot'ni YIQITMAYDI va faqat
`/health/ready` ni qizil qiladi — tayyorlik esa BIRORTA yozuvni to'smaydi
(`required_schema.unique_index_problems` va `index_guard` modul izohlari buni aytadi).

O'lchangan (shu harness bilan, tuzatishdan OLDIN): `ux_recv_corr_client` va
`ux_returns_client_uuid` ni DROP qilib haqiqiy yozuvchini chaqirganda yozuv O'TIB
KETARDI — hech narsa fail-closed emasdi. Bu fayl endi teskarisini qadab qo'yadi.

⚠️  BITTA KLASTER. `tests/test_check_defs_pg.pg_target` har test uchun yangi pgserver
    ko'taradi; mashina resursi cheklangan (600+ yetim postgres commit limitini
    tugatgani o'lchangan). Shu bois modul doirasida BITTA klaster ishlatiladi.
⚠️  `tests/cash/conftest.py` ning umumiy klasteri YARAMAYDI: u faqat 8 ta idempotentlik
    indeksini qo'lda yaratadi va `ux_recv_corr_client` ULARDA YO'Q. To'liq `app.initdb`
    kerak — `_baza()` aynan shuni bajaradi.
⚠️  Har DDL dan keyin `ig.reset_cache()`: gard musbat hukmni TTL davomida keshlaydi
    (hujjatlashtirilgan, SAFE-03 da [0,300] s ga cheklangan). Keshni bo'shatmasak
    o'lchov TTL ni, mahsulotni emas o'lchagan bo'lardi.
"""
from __future__ import annotations

import tempfile
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core import index_guard as ig
from app.core import required_schema as rs
from tests.test_receiving_correction_pg import (QTY, _baza, _bekor, _dokon,  # noqa: F401
                                                _emp, _hisobdan, _qabul)

#  Simlangan (indeks, jadval) juftliklari — `grep require_index(db` bilan izchil.
SIMLANGAN = [
    ("ux_doc_counter", "doc_counters"),
    ("ux_subscriptions_company", "subscriptions"),
    ("ux_subpay_client_uuid", "subscription_payments"),
    ("ux_sales_company_client_uuid", "sales"),
    ("ux_returns_client_uuid", "returns"),
    ("ux_receivings_client_uuid", "receivings"),
    ("ux_recv_corr_client", "receiving_corrections"),
    ("ux_purchases_client_uuid", "purchases"),
    ("ux_stockmov_client_prod_type", "stock_movements"),
    ("ux_cashmov_client_uuid_all", "cash_movements"),
]

#  DROP dan keyin AYNAN tiklash uchun — `app/initdb.py` DDL'idan ko'chirilgan.
TIKLASH = {
    "ux_returns_client_uuid":
        "CREATE UNIQUE INDEX ux_returns_client_uuid ON returns (company_id, client_uuid) "
        "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
    "ux_sales_company_client_uuid":
        "CREATE UNIQUE INDEX ux_sales_company_client_uuid ON sales (company_id, client_uuid) "
        "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
    "ux_receivings_client_uuid":
        "CREATE UNIQUE INDEX ux_receivings_client_uuid ON receivings (company_id, client_uuid) "
        "WHERE client_uuid IS NOT NULL",
    "ux_recv_corr_client":
        "CREATE UNIQUE INDEX ux_recv_corr_client ON receiving_corrections "
        "(company_id, client_uuid)",
    "ux_stockmov_client_prod_type":
        "CREATE UNIQUE INDEX ux_stockmov_client_prod_type ON stock_movements "
        "(client_uuid, product_id, type) WHERE client_uuid IS NOT NULL",
    "ux_purchases_client_uuid":
        "CREATE UNIQUE INDEX ux_purchases_client_uuid ON purchases "
        "(company_id, client_uuid) WHERE client_uuid IS NOT NULL AND deleted_at IS NULL",
    "ux_cashmov_client_uuid_all":
        "CREATE UNIQUE INDEX ux_cashmov_client_uuid_all ON cash_movements "
        "(client_uuid) WHERE client_uuid IS NOT NULL",
}


@pytest.fixture(scope="module")
def pg1():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(prefix="idxwire_"))
    u = srv.get_uri()
    url = ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)
    eng, S = _baza(url)
    try:
        yield eng, S
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)
def _kesh():
    ig.reset_cache()
    yield
    ig.reset_cache()


def _ddl(eng, sql):
    with eng.begin() as con:
        con.execute(text(sql))
    ig.reset_cache()


def _ishlat(S, fn):
    """-> ("OK", natija) | ("RAD", status, kod) | ("XATO", tur, matn)."""
    s = S()
    try:
        out = fn(s)
        s.commit()
        return ("OK", out)
    except HTTPException as e:
        s.rollback()
        return ("RAD", e.status_code, (e.headers or {}).get("X-Error-Code"))
    except Exception as e:                                   # noqa: BLE001
        s.rollback()
        return ("XATO", type(e).__name__, str(e)[:120])
    finally:
        s.close()


class _ochirilgan:
    """Indeksni DROP qiladi va chiqishda AYNAN tiklaydi — test yiqilsa HAM.

    ⚠️  NEGA KONTEKST MENEJERI. Modul doirasida BITTA klaster ishlatiladi, ya'ni
        o'chirilgan indeks keyingi testlarga OQIB O'TADI. `try/finally` bo'lmasa
        bitta yiqilish qolgan testlarni ham buzadi va mutatsiya isboti yolg'on
        signal berardi (o'lchangan: hamma gard olib tashlanganda bitta test
        tasodifan YASHIL chiqdi, chunki undan oldingisi indeksni tiklamagan edi).
    """

    def __init__(self, eng, ix):
        self.eng, self.ix = eng, ix

    def __enter__(self):
        with self.eng.begin() as con:
            con.execute(text(f"DROP INDEX {self.ix}"))
        ig.reset_cache()
        return self

    def __exit__(self, *exc):
        with self.eng.begin() as con:
            con.execute(text(TIKLASH[self.ix]))
        ig.reset_cache()
        return False


def _kutilgan_rad(natija, label):
    assert natija[0] == "RAD", f"{label}: yozuv O'TIB KETDI -> {natija}"
    assert natija[1] == 409, f"{label}: {natija}"
    assert natija[2] == ig.SCHEMA_GUARANTEE_MISSING, f"{label}: {natija}"


# ══ 1. SHAKL DARVOZASI — e'lon qilingan shakl HAQIQIY bazaga mos ═══════════

def test_PG_SIMLANGAN_indekslarning_SHAKLI_bazaga_MOS(pg1):
    """⚠️  BU TEST UZILISHDAN SAQLAYDI. E'lon qilingan ustun/predikat `initdb` qurgan
        indeksdan farq qilsa, gard HAR so'rovda 409 berib sotuv, qaytarish, qabul,
        xarid va kassa amalini TO'XTATARDI. Shu bois moslik O'LCHANADI.
    """
    eng, _S = pg1
    defs = rs.index_definition_states(eng)
    for ix, tbl in SIMLANGAN:
        assert ix in rs.REQUIRED_INDEX_DEFINITIONS, f"{ix} shakl ro'yxatida yo'q"
        assert defs.get(ix) == rs.IX_DEF_OK, (ix, defs.get(ix))
        assert ig.index_state(eng, ix, tbl) == ig.OK, (ix, tbl)
    #  Tayyorlik ham yashil qolishi kerak: aks holda operator soxta qizil ko'rardi.
    assert rs.index_definition_problems(eng) == []


# ══ 2. HAQIQIY YOZUVCHILAR: indeks YO'Q -> 409, qayta tiklangach -> o'tadi ══

def test_PG_QABUL_indeks_yoq_bolsa_RAD(pg1):
    """`POST /receiving/commit` — eng keng jonli pul yozuvchisi (bayroqsiz, har tenant)."""
    eng, S = pg1
    d = _dokon(S)
    oldin = _qabul(S, d)                       # indeks SOG'LOM -> o'tadi
    assert oldin.get("rec") is not None
    d2 = _dokon(S)
    with _ochirilgan(eng, "ux_receivings_client_uuid"):
        with pytest.raises(HTTPException) as ei:
            _qabul(S, d2)
        assert ei.value.status_code == 409
        assert (ei.value.headers or {}).get("X-Error-Code") == ig.SCHEMA_GUARANTEE_MISSING
    assert _qabul(S, _dokon(S)).get("rec") is not None    # tiklangach QAYTA ishlaydi


def test_PG_QABULNI_TUZATISH_indeks_yoq_bolsa_RAD(pg1):
    """`POST /receiving/{id}/corrections` — REQUIRED + DEFINITIONS, lekin yozuvchi
    ilgari qo'riqlanmagan edi (o'lchangan: DROP dan keyin tuzatish O'TIB KETARDI)."""
    eng, S = pg1
    d = _dokon(S)
    d.update(_qabul(S, d))
    assert _ishlat(S, _bekor(d, cu=uuid.uuid4()))[0] == "OK"
    d2 = _dokon(S)
    d2.update(_qabul(S, d2))
    with _ochirilgan(eng, "ux_recv_corr_client"):
        _kutilgan_rad(_ishlat(S, _bekor(d2, cu=uuid.uuid4())), "tuzatish")
    assert _ishlat(S, _bekor(d2, cu=uuid.uuid4()))[0] == "OK"


def test_PG_HISOBDAN_CHIQARISH_indeks_yoq_bolsa_RAD(pg1):
    """`POST /inventory/writeoff` — DELTA yozuv: dedup qulfdan OLDIN o'qiladi,
    shu bois konkurrent takrorni faqat indeks to'sadi."""
    eng, S = pg1
    d = _dokon(S)
    d.update(_qabul(S, d))
    assert _ishlat(S, _hisobdan(d, qty=1))[0] == "OK"
    with _ochirilgan(eng, "ux_stockmov_client_prod_type"):
        _kutilgan_rad(_ishlat(S, _hisobdan(d, qty=1)), "writeoff")
    assert _ishlat(S, _hisobdan(d, qty=1))[0] == "OK"


def _sotuv_fn(d, qty=1):
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    return lambda s: create_sale(s, _emp(s, d), SaleCreate(
        items=[{"product_id": str(d["pid"]), "qty": qty, "unit_price": 100}],
        payment_method="card", client_uuid=uuid.uuid4())).id


def _kuzatuvsiz(S, d, qty=Decimal("50")):
    """Sotuv/qaytarish yo'li uchun partiya kuzatuvini o'chiradi (bu yerda o'lchov INDEKS)."""
    from app.models.catalog import Product
    from app.models.inventory import Inventory
    s = S()
    try:
        s.get(Product, d["pid"]).track_lots = False
        s.query(Inventory).filter(Inventory.product_id == d["pid"]).one().qty = qty
        s.commit()
    finally:
        s.close()


def test_PG_SOTUV_indeks_yoq_bolsa_RAD(pg1):
    """`POST /sales` va `/sync/push` — offline qayta push yo'li. Dedup QULFSIZ SELECT,
    `receipt_no` noyobligi esa takrorni USHLAMAYDI (raqam ketma-ket beriladi)."""
    eng, S = pg1
    d = _dokon(S)
    _kuzatuvsiz(S, d)
    assert _ishlat(S, _sotuv_fn(d))[0] == "OK"
    with _ochirilgan(eng, "ux_sales_company_client_uuid"):
        _kutilgan_rad(_ishlat(S, _sotuv_fn(d)), "sotuv")
    assert _ishlat(S, _sotuv_fn(d))[0] == "OK"


def test_PG_QAYTARISH_indeks_yoq_bolsa_RAD(pg1):
    """`POST /returns` — o'lchangan: tuzatishdan OLDIN DROP dan keyin ham O'TIB KETARDI."""
    from app.schemas.sales import ReturnCreate
    eng, S = pg1
    d = _dokon(S)
    _kuzatuvsiz(S, d)
    sale_id = _ishlat(S, _sotuv_fn(d, qty=10))[1]

    def qaytar(s):
        from app.api.v1.sales import create_return
        return create_return(ReturnCreate(
            original_sale_id=sale_id, reason="customer", restock=False,
            refund_method="card", client_uuid=uuid.uuid4(),
            items=[{"product_id": str(d["pid"]), "qty": 1, "unit_price": 0}]),
            emp=_emp(s, d), db=s)

    assert _ishlat(S, qaytar)[0] == "OK"
    with _ochirilgan(eng, "ux_returns_client_uuid"):
        _kutilgan_rad(_ishlat(S, qaytar), "qaytarish")
    assert _ishlat(S, qaytar)[0] == "OK"


# ══ 3. GARD DARAJASIDA: qolgan simlangan yozuvchilar ham fail-closed ═══════

@pytest.mark.parametrize("ix,tbl,label", [
    ("ux_purchases_client_uuid", "purchases", "xarid"),
    ("ux_cashmov_client_uuid_all", "cash_movements", "kassa amali"),
])
def test_PG_qolgan_simlangan_indekslar_DROP_da_BAD_va_require_index_RAD(pg1, ix, tbl, label):
    """⚠️  Bu ikki yozuvchi uchun to'liq HTTP oqimi alohida o'rnatish talab qiladi
        (xarid hujjati; ochiq smena + kassa). Shu bois bu yerda GARDning o'zi
        o'lchanadi: indeks yo'qolsa holat BAD bo'ladi va `require_index` 409 beradi —
        ya'ni ayni chaqiruv yozuvchining boshida turganda yozuv boshlanmaydi ham.
        Yozuvchining gardni AYNAN chaqirishi `test_WIRING_royxati` da qadab qo'yilgan.
    """
    eng, _S = pg1
    assert ig.index_state(eng, ix, tbl) == ig.OK
    with eng.begin() as con:
        con.execute(text(f"DROP INDEX {ix}"))
    ig.reset_cache()
    try:
        assert ig.index_state(eng, ix, tbl) == ig.BAD, label
        with pytest.raises(HTTPException) as ei:
            ig.require_index(eng, ix, tbl, operation=label)
        assert ei.value.status_code == 409
        assert (ei.value.headers or {}).get("X-Error-Code") == ig.SCHEMA_GUARANTEE_MISSING
    finally:
        with eng.begin() as con:
            con.execute(text(TIKLASH[ix]))
        ig.reset_cache()
