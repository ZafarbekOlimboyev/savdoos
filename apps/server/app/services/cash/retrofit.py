"""Phase 2b — mavjud biznes-servislarni CashPostingService'ga ulash (dual-write).

Har hook GUARD ostida: cash quyi tizimi FAQAT Postgres (schema/trigger) — SQLite (dev/test)'da
va cash hisobi HALI xaritalanmagan filialda NO-OP (legacy oqim davom etadi, sinmaydi).
Aktiv bo'lганда: cash leg chaqiruvchining O'SHA tranzaksiyasiga qo'shiladi (commit=False) —
source + ledger ATOMIK (kontrakt §14). ledger cash.cash_ledger_entries'ga FAQAT CashPostingService
orqali yoziladi (to'g'ridan-to'g'ri yozuv yo'q).

MUHIM: dual-write смена ochilishidan (opening float) boshlab aktiv bo'lса, ledger balansи legacy
kassa balansига TENG bo'ladi — shунda OUT-sufficiency to'g'ri ishlaydi. Xaritalanmagan/eski ochiq
смена — cash.shift yo'q -> sotuv OFF_SHIFT (anomaliya, migratsiya hал qiladi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.cash import (
    CashAccount,
    CashCategory,
    CashDirection,
    CashShift,
    CashSourceType,
)
from app.services.cash import adapters
from app.services.cash import repositories as repo
from app.services.cash import lifecycle as _lifecycle  # noqa: F401  (test/keyingi faza uchun)

_CASH_READY: dict = {}   # bind-url -> bool (schema mavjudligi cache)


def _now():
    return datetime.now(timezone.utc)


def cash_enabled(db: Session) -> bool:
    """Postgres VA `cash` schema mavjud bo'lsa True. Aks holda dual-write no-op."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    key = str(bind.url)
    if key not in _CASH_READY:
        row = db.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'")).first()
        _CASH_READY[key] = row is not None
    return _CASH_READY[key]


def resolve_till(db: Session, tenant_id, branch_id) -> CashAccount | None:
    """Filialning ACTIVE TILL hisobi (xaritalanмаган bo'lsa None -> dual-write skip)."""
    return repo.find_account(db, tenant_id, branch_id, "TILL")


def resolve_safe(db: Session, tenant_id, branch_id) -> CashAccount | None:
    return repo.find_account(db, tenant_id, branch_id, "SAFE")


def _open_cash_shift_id(db: Session, tenant_id, till: CashAccount):
    sh = repo.open_shift_for_account(db, tenant_id, till.id)
    return sh.id if sh is not None else None


# ── Shift lifecycle (dual-write) ─────────────────────────────────────────────
def on_shift_open(db: Session, emp, *, branch_id, legacy_shift_id, opening_cash=0) -> CashShift | None:
    """Legacy смена ochilганда cash.shift ochadi (+ opening float). commit=False."""
    if not cash_enabled(db):
        return None
    tenant = emp.company_id
    till = resolve_till(db, tenant, branch_id)
    if till is None:
        return None
    sh = CashShift(tenant_id=tenant, cash_account_id=till.id, branch_id=till.branch_id,
                   account_type="TILL", status="OPEN", opened_at=_now(),
                   opened_by=getattr(emp, "id", None), version=1)
    db.add(sh)
    db.flush()
    if float(opening_cash or 0) > 0:
        adapters.opening_float(db, emp, cash_account_id=till.id, source_id=legacy_shift_id,
                               amount=opening_cash, origin_shift_id=sh.id, commit=False)
    return sh


def on_shift_close(db: Session, emp, *, branch_id, counted_cash=0):
    """Legacy смена yopilganda cash.shift ni yopadi + reconciliation snapshot. commit=False."""
    if not cash_enabled(db):
        return None
    tenant = emp.company_id
    till = resolve_till(db, tenant, branch_id)
    if till is None:
        return None
    sh = repo.open_shift_for_account(db, tenant, till.id)
    if sh is None:
        return None
    expected = repo.shift_expected_cash(db, tenant, sh.id)
    now = _now()
    sh.status = "CLOSED"
    sh.closed_at = now
    sh.closed_by = getattr(emp, "id", None)
    rec = _lifecycle._new_recon(db, tenant, shift_id=sh.id, snapshot=expected,
                                counted=_lifecycle._D(counted_cash),
                                diff=_lifecycle._D(counted_cash) - expected, now=now)
    db.add(rec)
    db.flush()
    return rec


# ── Posting hooks (dual-write) — hammasi guarded + commit=False ─────────────
def _shift_ctx(db, emp, branch_id):
    """(till, cash_shift_id) — dual-write faol bo'lsa; aks holда (None, None)."""
    if not cash_enabled(db):
        return None, None
    till = resolve_till(db, emp.company_id, branch_id)
    if till is None:
        return None, None
    return till, _open_cash_shift_id(db, emp.company_id, till)


def on_cash_sale(db, emp, *, branch_id, sale_id, cash_amount, device_occurred_at=None):
    """Sotuvning NAQD qismi -> IN·SALE (kartа/QR qismi ledger'ga tegmaydi)."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=sale_id,
                              amount=cash_amount, origin_shift_id=shift_id,
                              device_occurred_at=device_occurred_at, commit=False)


def on_cash_refund(db, emp, *, branch_id, return_id, cash_amount):
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.cash_refund(db, emp, cash_account_id=till.id, source_id=return_id,
                                amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_debt_payment(db, emp, *, branch_id, payment_id, cash_amount):
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.debt_payment(db, emp, cash_account_id=till.id, source_id=payment_id,
                                 amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_supplier_payment(db, emp, *, branch_id, payment_id, cash_amount):
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.supplier_payment(db, emp, cash_account_id=till.id, source_id=payment_id,
                                     amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_cash_purchase(db, emp, *, branch_id, purchase_id, cash_amount):
    """XARID NAQD to'lansa -> OUT·PURCHASE_OUT. Bu — asosiy off-ledger teshigini yopadi (§07)."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=purchase_id,
                                  amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_purchase_return(db, emp, *, branch_id, purchase_id, purchase_return_id, cash_amount):
    """NAQD xarid qaytarilsa (received xarid kamaytirish/bekor) -> IN·PURCHASE_RETURN.
    source_id = PurchaseReturn HODISASI id'si (asl purchase_id EMAS) — create leg'i bilan
    to'qnashmaydi, bir xariddan ko'p qaytarish mustaqil ([[PURCHASE_RETURN_identity]]).

    FAQAT create'да HAQIQATAN OUT·PURCHASE_OUT post qilingan xarid uchun qaytaradi: aks holда
    (mobil `receiving` naqd xaridi on_cash_purchase CHAQIRMAYDI; yoki parallel-run'да cash
    aktivlashuvidan OLDIN yaratilган xarid) mos OUT leg yo'q -> qaytarish PHANTOM naqd IN
    yaratardi. OUT leg bo'lmasa -> qaytariladigan naqd yo'q -> skip (kassa buzilmaydi)."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    # Create'даги OUT·PURCHASE_OUT (PURCHASE·purchase_id·0) mavjudligini tekshir — reversal EMAS,
    # faqat haqiqatан chiqqan naqdni qaytaramiz (kontrakt: qaytarish OUT'ning aksi bo'lсин).
    orig = repo.get_entry_by_business_key(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id, 0)
    if orig is None:
        return None
    return adapters.purchase_return(db, emp, cash_account_id=till.id, source_id=purchase_return_id,
                                    amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_cash_purchase_increase(db, emp, *, branch_id, purchase_id, extra_amount):
    """NAQD (received) xarid create'даги OUT·PURCHASE_OUT (leg-0)'дан KEYIN summasi OSHIRILса, faqat
    QO'SHIMCHA fizik naqd chiqishini yozadi -> OUT·PURCHASE_OUT. Asl leg-0'ни O'ZGARTIRMAYDI (immutable):
    source_type=PURCHASE, source_id=purchase_id (asl bilan bir xil), leg_index=KEYINGI bo'sh (>=1) —
    cle_uq_business leg-0 bilan TO'QNASHMAYDI, append-only. Original xaridni IKKI marta hisoblamaydi
    (leg-0 asl summada qoladi; bu leg faqat DELTA'ni tutadi).

    Gate (on_purchase_return bilan simmetrik): asl OUT·PURCHASE_OUT (leg-0) MAVJUD bo'lса post qiladi;
    aks holда (mobil receiving naqd xaridi leg-0 yozmaган, yoki parallel-run'да cash aktivlashuvidan
    OLDIN yaratilган xarid) SKIP — backfill current_total (oshirilган summani O'Z ICHIGA olgan) orqali
    net'ni tiklaydi, shu bois phantom qo'shimcha OUT yozmaymiz."""
    if float(extra_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    orig = repo.get_entry_by_business_key(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id, 0)
    if orig is None:
        return None
    next_idx = repo.next_leg_index(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id)
    return adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=purchase_id,
                                  amount=extra_amount, origin_shift_id=shift_id, leg_index=next_idx,
                                  commit=False)


# CashMovement turlari (legacy) -> ledger. payout ("Naqd topshirish") — MANUAL kassa drain:
# OUT·CASH_OUT (collection/inkassa bilan bir buket; source_id=movement.id noyob -> identity to'qnashmaydi).
# DIQQAT: refund/supplier/debt SOYA payout/payin'lari BU YO'LDAN o'tmaydi (ular biznes-endpoint'да
# to'g'ridan-to'g'ri CashMovement sifatida yoziladi, on_cash_op CHAQIRILMAYDI) -> ikki marta post yo'q.
_CASHOP_MAP = {
    "payin": ("manual_cash_in",),         # IN·CASH_IN
    "payout": ("manual_cash_out",),        # OUT·CASH_OUT — manual naqd topshirish (kassa drain)
    "expense": ("expense",),               # OUT·EXPENSE
    "collection": ("manual_cash_out",),   # inkassatsiya — kassadан naqd chiqishi (OUT·CASH_OUT)
}


def on_cash_op(db, emp, *, branch_id, kind, amount, movement_id):
    """Legacy CashMovement (payin/payout/expense/collection) -> mos ledger legи."""
    fn = {"payin": adapters.manual_cash_in, "payout": adapters.manual_cash_out,
          "expense": adapters.expense, "collection": adapters.manual_cash_out}.get(kind)
    if fn is None or float(amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return fn(db, emp, cash_account_id=till.id, source_id=movement_id, amount=amount,
             origin_shift_id=shift_id, commit=False)
