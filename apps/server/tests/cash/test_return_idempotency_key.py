# -*- coding: utf-8 -*-
"""QAYTARISH IDEMPOTENTLIK KALITI — UY KONTRAKTI (haqiqiy Postgres, haqiqiy marshrut).

NEGA BU FAYL BOR
================
`error_codes.IDEMPOTENCY_KEY_REUSED` izohi butun repo uchun kontraktni belgilaydi:
«ayni kalit bilan kelgan so'rovning MODDIY maydonlari saqlangan amalnikidan farq
qilsa, bu TAKROR emas — yangi amal. U YOZILMAYDI va «ok» ham DEYILMAYDI: aks holda
kassir pulni yozildi deb o'ylardi». Naqsh `cashops.replay_answer`,
`purchases._supplier_replay`, `shifts`, `receiving`, `lot_correction` da qo'llangan.

`POST /returns` kontraktning IKKALA yarmini ham bajarmasdi. O'lchangan (shu fayldagi
harness bilan, haqiqiy PG, sxema BUTUNLAY SOG'LOM): qty=2 naqd qaytarishdan keyin
AYNI kalit bilan qty=5, so'ng CARD yuborilganda uchala javob ham `QAY-1001, 200.0`
qaytardi va `duplicate` belgisi ham qo'yilmadi — ya'ni kassirga 500 so'm karta
qaytarildi deb AYTILARDI, holbuki 200 so'm naqd, BIR MARTA qaytgan.

Bu oqim nazariy emas: POS kalitni ekran ochilganda yaratadi va FAQAT muvaffaqiyatdan
keyin yangilaydi (`packages/shared/src/screens/Returns.tsx:53,109`) — yiqilgan
urinishdan keyin kassir summani tuzatib qayta yuborsa kalit AYNI qoladi.

⚠️  KALIT YO'QLIGI bu yerda SINALADI, lekin TUZATILMAYDI: `client_uuid` berilmasa
    dedup umuman qilinmaydi va bu repo bo'ylab bir xil kontrakt
    (`cashops.replay_answer`: `if client_uuid is None: return None`). Test uni
    QADAB QO'YADI, ya'ni kelajakdagi o'zgarish ATAYLAB bo'ladi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core import error_codes as EC
from app.models.cash import CashLedgerEntry
from app.models.sales import Return
#  Fixture'lar MAVJUD testdan: u haqiqiy marshrut funksiyasini haqiqiy PG sessiyasi
#  bilan chaqiradi va dual-write JONLI (`dual_write_enabled()` SQLite'da DOIM False).
from tests.cash.test_return_cash_posting import (  # noqa: F401
    _emp, _lots, _sell, _session, _shift, env, till)


def _post(cashenv, sale_id, pid, qty, *, cu, method="cash", restock=True,
          reason="customer"):
    """Marshrut funksiyasini AYNAN berilgan `client_uuid` bilan chaqiradi (None ham)."""
    from app.api.v1.sales import create_return
    from app.schemas.sales import ReturnCreate
    s = _session(cashenv)
    try:
        return create_return(ReturnCreate(
            original_sale_id=sale_id, reason=reason, restock=restock,
            refund_method=method, client_uuid=cu,
            items=[{"product_id": str(pid), "qty": qty, "unit_price": 0}]),
            emp=_emp(s, cashenv), db=s)
    finally:
        s.close()


def _soni(cashenv, sale_id):
    s = _session(cashenv)
    try:
        rets = s.query(Return).filter(Return.original_sale_id == sale_id).count()
        legs = s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.source_type == "RETURN").count()
        mov = s.execute(text("SELECT count(*) FROM cash_movements")).scalar()
        return rets, legs, mov
    finally:
        s.close()


# ══ 1. AYNI KALIT, AYNI AMAL -> BIRINCHI JAVOB + `duplicate: true` ═════════

def test_PG_AYNI_kalit_AYNI_amal_duplicate_belgisi_bilan(env):
    """Haqiqiy takror RAD ETILMAYDI — birinchi javob qaytadi, lekin BELGILANADI.

    ⚠️  `duplicate` belgisi uy kontraktining yarmi: mijoz «bu yangi yozuv emas»
        deb bila olishi kerak (`cashops.py:86`, `purchases.py:136`, `receiving.py:149`).
    """
    cashenv, _till, pid = env
    sale = _sell(cashenv, pid, qty=10, price=100)
    K = uuid.uuid4()
    r1 = _post(cashenv, sale.id, pid, 2, cu=K)
    oldin = _soni(cashenv, sale.id)
    r2 = _post(cashenv, sale.id, pid, 2, cu=K)
    assert str(r1["id"]) == str(r2["id"])
    assert r2.get("duplicate") is True, "takror BELGILANMADI"
    assert r2["return_no"] == r1["return_no"] and r2["total"] == r1["total"]
    assert _soni(cashenv, sale.id) == oldin, "takror yangi yozuv qo'shdi"


# ══ 2. AYNI KALIT, BOSHQA AMAL -> 409 va HECH NARSA YOZILMAYDI ════════════

@pytest.mark.parametrize("kw,label", [
    ({"qty": 5}, "MIQDOR boshqa"),
    ({"method": "card"}, "TO'LOV USULI boshqa"),
    ({"restock": False}, "OMBORGA QAYTISH boshqa"),
    ({"reason": "defect"}, "SABAB boshqa"),
])
def test_PG_AYNI_kalit_BOSHQA_amal_409_va_YOZILMAYDI(env, kw, label):
    cashenv, _till, pid = env
    sale = _sell(cashenv, pid, qty=10, price=100)
    K = uuid.uuid4()
    r1 = _post(cashenv, sale.id, pid, 2, cu=K)
    oldin = _soni(cashenv, sale.id)
    lot_oldin = _lots(cashenv, pid)

    qty = kw.pop("qty", 2)
    with pytest.raises(HTTPException) as ei:
        _post(cashenv, sale.id, pid, qty, cu=K, **kw)

    assert ei.value.status_code == 409, label
    #  Kod SARLAVHADA — mijoz uni dasturiy taniydi va `serverErrors.ts` tarjima qiladi.
    assert ei.value.headers.get(EC.HEADER) == EC.IDEMPOTENCY_KEY_REUSED, label
    assert str(ei.value.detail).startswith("IDEMPOTENCY_KEY_REUSED: "), label
    #  HECH NARSA yozilmadi: qaytarish ham, ledger legi ham, kassa harakati ham, partiya ham.
    assert _soni(cashenv, sale.id) == oldin, label
    assert _lots(cashenv, pid) == lot_oldin, label
    #  Birinchi qaytarish JOYIDA va o'zgarmagan.
    s = _session(cashenv)
    try:
        ex = s.query(Return).filter(Return.client_uuid == K).one()
        assert str(ex.id) == str(r1["id"]) and float(ex.total) == r1["total"]
    finally:
        s.close()


def test_PG_RAD_etilgandan_keyin_YANGI_kalit_bilan_otadi(env):
    """409 dan keyin mijoz YANGI kalit bilan qaytadan yuborishi kerak — va o'tadi."""
    cashenv, _till, pid = env
    sale = _sell(cashenv, pid, qty=10, price=100)
    K = uuid.uuid4()
    _post(cashenv, sale.id, pid, 2, cu=K)
    with pytest.raises(HTTPException):
        _post(cashenv, sale.id, pid, 5, cu=K)
    r = _post(cashenv, sale.id, pid, 5, cu=uuid.uuid4())      # YANGI kalit
    assert r.get("duplicate") is not True
    assert _soni(cashenv, sale.id)[0] == 2


# ══ 3. MAVJUD KONTRAKTNI QADAB QO'YISH (o'zgartirilmagan xulq) ════════════

def test_PG_KALITSIZ_dedup_QILINMAYDI_repo_kontrakti(env):
    """`client_uuid` yo'q -> idempotentlik yo'q. Bu BUTUN REPO kontrakti.

    ⚠️  BU TEST NUQSONNI EMAS, QARORNI qadaydi. `cashops.replay_answer:49`
        (`if client_uuid is None: return None`) ayni qoidani `/cash/ops`,
        `/shifts`, `/receiving` uchun ham belgilaydi. Shu bois `/returns` ni
        yolg'iz o'zini majburiy qilish uni qolganlardan FARQLI qilardi.
        Agar ega kontraktni o'zgartirishni tanlasa — shu test QIZIL bo'ladi va
        o'zgarish ATAYLAB bo'lganini ko'rsatadi.
    """
    cashenv, _till, pid = env
    sale = _sell(cashenv, pid, qty=10, price=100)
    r1 = _post(cashenv, sale.id, pid, 2, cu=None)
    oldin = _soni(cashenv, sale.id)
    r2 = _post(cashenv, sale.id, pid, 2, cu=None)
    assert str(r1["id"]) != str(r2["id"]), "kalitsiz takror dedup QILINDI"
    keyin = _soni(cashenv, sale.id)
    assert keyin[0] == oldin[0] + 1
    assert keyin[1] == oldin[1] + 1, "ikkinchi ledger legi yozilmadi"
    assert keyin[2] == oldin[2] + 1, "ikkinchi kassa harakati yozilmadi"


def test_PG_indeks_YOQ_bolsa_ketma_ket_dedup_ISHLAYDI(env):
    """`ux_returns_client_uuid` yo'q bo'lsa ham KETMA-KET takror dedup qilinadi.

    ⚠️  Indeks KONKURRENT takror uchun oxirgi to'siq; ketma-ket yo'lda ishni dedup
        SELECT bajaradi. Shu bois indeksning yo'qolishi bu testda KO'RINMAYDI —
        aynan shu sabab u `IDEMPOTENCY_INDEXES` da (tayyorlik qizil, boot yiqilmaydi)
        va yozuv tomoni `require_index` bilan QO'RIQLANMAGAN. Bu holat hisobotda
        alohida bloker sifatida qayd etilgan, bu fazada tuzatilmadi.
    """
    cashenv, _till, pid = env
    with cashenv.engine.begin() as con:
        con.execute(text("DROP INDEX IF EXISTS ux_returns_client_uuid"))
    try:
        sale = _sell(cashenv, pid, qty=10, price=100)
        K = uuid.uuid4()
        r1 = _post(cashenv, sale.id, pid, 2, cu=K)
        r2 = _post(cashenv, sale.id, pid, 2, cu=K)
        assert str(r1["id"]) == str(r2["id"]) and r2.get("duplicate") is True
        #  Moddiy farq indeks bo'lmasa HAM 409 beradi — gard ilovada, indeksda emas.
        with pytest.raises(HTTPException) as ei:
            _post(cashenv, sale.id, pid, 5, cu=K)
        assert ei.value.headers.get(EC.HEADER) == EC.IDEMPOTENCY_KEY_REUSED
    finally:
        with cashenv.engine.begin() as con:
            con.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_returns_client_uuid "
                "ON returns (company_id, client_uuid) "
                "WHERE client_uuid IS NOT NULL AND deleted_at IS NULL"))


def test_PG_AYNI_kalit_BOSHQA_ijarachi_TOQNASHMAYDI(env):
    """Dedup doirasi — KOMPANIYA. Boshqa kompaniyaning ayni kaliti to'smaydi.

    ⚠️  So'rov `Return.company_id == emp.company_id` bilan filtrlanadi va indeks ham
        `(company_id, client_uuid)` — ya'ni doira ikki joyda ham ijarachi.
    """
    cashenv, _till, pid = env
    sale = _sell(cashenv, pid, qty=10, price=100)
    K = uuid.uuid4()
    r1 = _post(cashenv, sale.id, pid, 2, cu=K)
    s = _session(cashenv)
    try:
        #  Boshqa kompaniyaning AYNI kalitli qatori dedupga TUSHMASLIGI kerak.
        begona = s.query(Return).filter(Return.client_uuid == K,
                                        Return.company_id != cashenv.company_id).count()
        meni = s.query(Return).filter(Return.client_uuid == K,
                                      Return.company_id == cashenv.company_id).count()
    finally:
        s.close()
    assert begona == 0 and meni == 1
    assert str(_post(cashenv, sale.id, pid, 2, cu=K)["id"]) == str(r1["id"])
