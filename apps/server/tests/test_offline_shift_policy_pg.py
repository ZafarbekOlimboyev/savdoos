# -*- coding: utf-8 -*-
"""P9 — OFFLINE REPLAY'NING PUL OQIBATI, HAQIQIY POSTGRES.

⚠️  NEGA ALOHIDA FAYL VA NEGA POSTGRES. Bu yerdagi tasdiqlar `cash` SXEMASIGA tegishli:
    `cash_enabled()` faqat u bor bo'lganda rost bo'ladi, cutover (T0) majburlashi esa
    AYNAN shu yo'ldan o'tadi (`services/sales.py` -> `cutover_guard.require_post_t0_till`
    -> `reject_closed_shift_replay`). SQLite'da `cash` sxemasi UMUMAN yo'q, ya'ni bu
    tekshiruvlar u yerda «yashil» bo'lib HECH NARSANI isbotlamasdi.

USHLANADIGAN NUQSON: «ochiq smena bor edi» degan tasdiq offline chekning KEYINCHALIK
qabul qilinishini KAFOLATLAMAYDI. Post-T0 naqd do'konda smena YOPILGANDAN keyin kelgan
replay `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY` bilan RAD etiladi — pul esa allaqachon
olingan. Bu fayl shu haqiqatni QOTIRADI: kassa darvozasi (P9) uni to'sa OLMAYDI, shu bois
u alohida, ochiq xavf sifatida hisobotda turadi va yechimi EGA qaroriga qoldiriladi.

IKKINCHI TASDIQ: rad etilgan replay HECH NARSA yozmaydi — na savdo, na ledger legi, na
qoldiq chiqimi. Aks holda dead-letter'dagi chekni qayta yuborish pulni IKKI MARTA
kiritardi (`Do not implement automatic retries that could duplicate financial
transactions` talabining baza tomoni).
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from tests.test_cash_custody_correction import NOW, _dokon, _hisob, _pul, _smena, _t0
from tests.test_check_defs_pg import pg_target  # noqa: F401
from tests.test_receiving_correction_pg import _baza

NARX = Decimal("100")


# ══ YORDAMCHILAR ════════════════════════════════════════════════════════════

def _mahsulot(S, d, *, qty=50):
    """KUZATUVSIZ mahsulot + qoldiq (partiya mantig'i bu sinovga aloqador emas)."""
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    s = S()
    try:
        unit = s.query(Unit).filter(Unit.code == "dona").first() or s.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=d["cid"], name="P9 " + uuid.uuid4().hex[:6],
                    article_code="P9-" + uuid.uuid4().hex[:6], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=Decimal("50"), base_sell_price=NARX,
                    tax_rate=0, track_lots=False)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=d["bid"],
                        qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        s.commit()
        return p.id
    finally:
        s.close()


def _replay(S, d, pid, *, at, cu=None):
    """`/sync/push` bilan AYNI chaqiruv: offline replay (`honor_price_snapshot=True`)."""
    from app.models.auth import Employee
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    s = S()
    try:
        emp = s.get(Employee, d["emp"])
        data = SaleCreate(client_uuid=(cu or uuid.uuid4()), payment_method="cash",
                          items=[{"product_id": pid, "qty": 1, "unit_price": NARX}],
                          given_amount=NARX)
        sale = create_sale(s, emp, data, at=at, honor_price_snapshot=True)
        s.commit()
        return sale.id
    finally:
        s.close()


def _yop(S, sid):
    """Smenani YOPADI (kassirning o'zi yopgandek — holat + `closed_at`)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        sh = s.get(Shift, sid)
        sh.status = ShiftStatus.closed
        sh.closed_at = NOW - timedelta(minutes=30)
        s.commit()
    finally:
        s.close()


def _sanoq(S, d):
    """(savdolar soni, ledger qatorlari soni) — MAVJUDLIK emas, SON bilan o'lchanadi."""
    from sqlalchemy import text
    from app.models.sales import Sale
    s = S()
    try:
        savdo = s.query(Sale).filter(Sale.company_id == d["cid"]).count()
        # ⚠️  JADVAL NOMI: `cash.cash_ledger_entries` (DDL: `cash_ddl_v1.sql:174`).
        #     Ilgari bu yerda `cash.ledger_entry` yozilgan edi — bunday jadval YO'Q, va
        #     `except Exception -> leg = 0` xatoni YUTARDI. Natijada `leg` DOIM 0 bo'lib:
        #       · `…ochiq_smena_replay_QABUL_va_ledgerga_YOZILADI` DOIM qizil edi
        #         (`assert 0 > 0`) — garchi leg BAZAGA YOZILGAN bo'lsa ham;
        #       · `…yopilgan_smenaga_naqd_replay_RAD_ETILADI` va
        #         `…takror_client_uuid_ledgerga_IKKINCHI_leg_yozmaydi` ning LEDGER
        #         tasdiqlari BEKORGA ishlardi (0 == 0), ya'ni yashil bo'lib turib
        #         hech narsani isbotlamasdi.
        #
        # ⚠️  `try/except` OLIB TASHLANDI. Bu fayl PG-ga bog'langan (`pg_target`) va
        #     butun maqsadi ledger tasdiqlari — jadval o'qilmasa sinov JIM o'tmasin,
        #     BALAND yiqilsin.
        leg = s.execute(text("SELECT count(*) FROM cash.cash_ledger_entries "
                             "WHERE tenant_id = :t"), {"t": str(d["cid"])}).scalar() or 0
        return savdo, leg
    finally:
        s.close()


# ══ 1. YOPILGAN SMENAGA NAQD REPLAY — RAD ══════════════════════════════════

def test_post_t0_yopilgan_smenaga_naqd_replay_RAD_ETILADI(pg_target):  # noqa: F811
    """«Smena ochiq edi» KAFOLAT EMAS: smena yopilgach o'sha oynadagi chek rad etiladi.

    Bu — P9 darvozasi to'sa OLMAYDIGAN qoldiq xavf: qaror kassada, savdo paytida
    qabul qilinadi, smena esa KEYIN yopiladi."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    _t0(S, d)                                       # majburlash FAOL (cutover o'tmishda)
    pid = _mahsulot(S, d)
    sid = _smena(S, d, till=till)                   # opened_at = NOW - 2 soat
    ichida = NOW - timedelta(hours=1)               # smena OYNASI ichidagi savdo vaqti

    # 1) Smena OCHIQ ekan — replay QABUL qilinadi (mavjud xulq buzilmagan).
    _replay(S, d, pid, at=ichida)
    savdo1, _ = _sanoq(S, d)
    assert savdo1 == 1

    # 2) Smena YOPILADI (kassir kunni yopdi), qurilma esa hali offline edi.
    _yop(S, sid)

    # 3) AYNI oynadagi keyingi chek — RAD. Pul allaqachon olingan.
    oldin = _sanoq(S, d)
    with pytest.raises(HTTPException) as ex:
        _replay(S, d, pid, at=ichida)
    assert ex.value.status_code == 400, ex.value.detail
    assert "CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY" in str(ex.value.detail), ex.value.detail

    # 4) IZSIZ: na savdo, na ledger legi. Dead-letter'dan qayta yuborish pulni
    #    IKKI MARTA kiritmasligi uchun bu SHART.
    assert _sanoq(S, d) == oldin


# ══ 2. SMENA OCHIQ BO'LSA — PUL LEDGERGA TUSHADI ═══════════════════════════

def test_post_t0_ochiq_smena_replay_QABUL_va_ledgerga_YOZILADI(pg_target):  # noqa: F811
    """Ijobiy nazorat: darvoza faqat YOPILGAN smenaga tegishli. Ochiq smenada offline
    chek qabul qilinadi VA naqd ledgerga tushadi — aks holda yuqoridagi sinov «hamma
    narsa rad etiladi» degani bo'lib hech narsani isbotlamasdi."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    _t0(S, d)
    pid = _mahsulot(S, d)
    _smena(S, d, till=till)
    oldin_savdo, oldin_leg = _sanoq(S, d)
    _replay(S, d, pid, at=NOW - timedelta(hours=1))
    keyin_savdo, keyin_leg = _sanoq(S, d)
    assert keyin_savdo == oldin_savdo + 1
    assert keyin_leg > oldin_leg, "naqd offline savdo ledgerga leg YOZISHI kerak"


# ══ 3. TAKROR REPLAY — PUL IKKI MARTA YOZILMAYDI ═══════════════════════════

def test_takror_client_uuid_ledgerga_IKKINCHI_leg_yozmaydi(pg_target):  # noqa: F811
    """Qayta ulanish sikli bir chekni bir necha marta yuboradi. `client_uuid`
    idempotentligi BAZA darajasida ham ushlansin: qator SONI o'zgarmasin."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    _t0(S, d)
    pid = _mahsulot(S, d)
    _smena(S, d, till=till)
    cu = uuid.uuid4()
    _replay(S, d, pid, at=NOW - timedelta(hours=1), cu=cu)
    birinchi = _sanoq(S, d)
    _replay(S, d, pid, at=NOW - timedelta(hours=1), cu=cu)
    assert _sanoq(S, d) == birinchi, "takror yuborish yangi savdo/leg YOZMASLIGI kerak"


# ══ 4. SIYOSAT MARSHRUTI POST-T0 DA YOLG'ON «ALLOWED» BERMASIN ═════════════
#
# Tanqidiy sharh topgan nuqson: `force_shift` o'chiq bo'lsa marshrut smena bo'lmasa ham
# ALLOWED qaytarardi. Lekin post-T0 naqd do'konda `require_post_t0_till` AYNAN kassa
# (TILL) talab qiladi va bunday chek QAYTA YUBORILGANDA ALBATTA 400 oladi — ya'ni
# «ALLOWED» pul olishga YOLG'ON ruxsat bo'lardi. Bu poyga emas, DETERMINIK holat.

def _qaror(S, d, **kw):
    """Marshrut funksiyasini TO'G'RIDAN-TO'G'RI chaqiradi (TestClient PG'ga ulanmagan)."""
    from app.api.v1.shifts import offline_sale_policy
    from app.models.auth import Employee
    s = S()
    try:
        return offline_sale_policy(emp=s.get(Employee, d["emp"]), db=s, **kw)
    finally:
        s.close()


def test_post_t0_smenasiz_ALLOWED_BERILMAYDI(pg_target):  # noqa: F811
    """T0 o'tgan, `force_shift` O'CHIQ, smena YO'Q -> replay `TILL_REQUIRED_AFTER_CUTOVER`
    bilan rad etilardi. Marshrut buni OLDINDAN aytadi."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    _hisob(S, d)
    _t0(S, d)
    j = _qaror(S, d)
    assert j["mode"] == "BLOCKED", j
    assert j["reason"] == "TILL_REQUIRED_AFTER_CUTOVER", j


def test_post_t0_LEGACY_smena_till_siz_ALLOWED_BERILMAYDI(pg_target):  # noqa: F811
    """Smena bor, lekin `till_id` YO'Q (T0'ni kesib o'tgan legacy smena) ->
    `LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER` (400). ALLOWED deyish mumkin emas."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    _hisob(S, d)
    _t0(S, d)
    _smena(S, d, till=None)                     # LEGACY: till_id YO'Q
    j = _qaror(S, d)
    assert j["mode"] == "BLOCKED", j
    assert j["reason"] == "LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER", j


def test_post_t0_TILLLI_ochiq_smena_ALLOWED(pg_target):  # noqa: F811
    """Ijobiy nazorat: to'g'ri sozlangan post-T0 do'kon offline savdo qila oladi."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    _t0(S, d)
    _smena(S, d, till=till)
    assert _qaror(S, d) == {"mode": "ALLOWED", "reason": None}


def test_pre_t0_smenasiz_ALLOWED(pg_target):  # noqa: F811
    """T0 YO'Q (legacy do'kon) va siyosat o'chiq — mavjud xulq SAQLANADI."""
    eng, S = _baza(pg_target)
    d = _dokon(S)
    _hisob(S, d)
    assert _qaror(S, d) == {"mode": "ALLOWED", "reason": None}
