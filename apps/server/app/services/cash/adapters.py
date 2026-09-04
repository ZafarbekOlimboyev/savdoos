"""CashPostingService — fokuslangan operatsiya adapterlari (kontrakt §13).

Har operatsiya uchun to'g'ri direction/category/source_type ni o'rnatib, yagona
`cash_posting_service.post()` (yoki post_transfer/post_reversal) ni chaqiruvchi yupqa
o'ramlar. Mavjud biznes-servislarни HALI retrofit qilmaymiz — bu kanonik posting
chegarasi + fokuslangan interfeys (§22).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.cash import CashCategory, CashDirection, CashSourceType
from app.services.cash.commands import PostingCommand, ReversalCommand, TransferCommand
from app.services.cash.posting import cash_posting_service as _svc


def _post(db, emp, *, cash_account_id, direction, category, source_type, source_id, amount,
          origin_shift_id=None, leg_index=0, currency=None, device_occurred_at=None,
          idempotency_key=None, origin_device_id=None, allow_negative=False, negative_reason=None,
          provenance="NORMAL", reconstruction_reason=None, reconstruction_source_ref=None,
          commit=True):
    cmd = PostingCommand(
        cash_account_id=cash_account_id, source_type=source_type, source_id=source_id,
        direction=direction, category=category, amount=Decimal(str(amount)),
        origin_shift_id=origin_shift_id, leg_index=leg_index, currency=currency,
        device_occurred_at=device_occurred_at, idempotency_key=idempotency_key,
        origin_device_id=origin_device_id, allow_negative=allow_negative,
        negative_reason=negative_reason, provenance=provenance,
        reconstruction_reason=reconstruction_reason, reconstruction_source_ref=reconstruction_source_ref,
    )
    return _svc.post(db, emp, cmd, commit=commit)


def cash_sale(db, emp, *, cash_account_id, source_id, amount, origin_shift_id, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.IN.value,
                 category=CashCategory.SALE.value, source_type=CashSourceType.SALE.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def cash_refund(db, emp, *, cash_account_id, source_id, amount, origin_shift_id, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.REFUND.value, source_type=CashSourceType.RETURN.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def debt_payment(db, emp, *, cash_account_id, source_id, amount, origin_shift_id, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.IN.value,
                 category=CashCategory.DEBT_IN.value, source_type=CashSourceType.CUSTOMER_PAYMENT.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def supplier_payment(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.SUPPLIER_OUT.value, source_type=CashSourceType.SUPPLIER_PAYMENT.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def cash_purchase(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.PURCHASE_OUT.value, source_type=CashSourceType.PURCHASE.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def purchase_return(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    # source_id = PurchaseReturn HODISASI id'si (asl purchase_id EMAS) — source_type PURCHASE_RETURN
    # bo'lgani uchun create'даги PURCHASE+purchase_id+0 leg'i bilan cle_uq_business TO'QNASHMAYDI.
    # reverses_id ISHLATILMAYDI: qaytarish alohida IN·PURCHASE_RETURN hodisa, reversal emas.
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.IN.value,
                 category=CashCategory.PURCHASE_RETURN.value, source_type=CashSourceType.PURCHASE_RETURN.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def manual_cash_in(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.IN.value,
                 category=CashCategory.CASH_IN.value, source_type=CashSourceType.CASH_OP.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def manual_cash_out(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.CASH_OUT.value, source_type=CashSourceType.CASH_OP.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def expense(db, emp, *, cash_account_id, source_id, amount, origin_shift_id=None, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.EXPENSE.value, source_type=CashSourceType.CASH_OP.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def adjustment(db, emp, *, cash_account_id, source_id, amount, direction, origin_shift_id=None, **kw):
    """Manual tuzatish — menejer+ (servis _authorize'да tekshiradi)."""
    return _post(db, emp, cash_account_id=cash_account_id, direction=direction,
                 category=CashCategory.ADJUSTMENT.value, source_type=CashSourceType.CASH_OP.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def opening_float(db, emp, *, cash_account_id, source_id, amount, origin_shift_id, **kw):
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.IN.value,
                 category=CashCategory.OPENING.value, source_type=CashSourceType.SHIFT_OPEN.value,
                 source_id=source_id, amount=amount, origin_shift_id=origin_shift_id, **kw)


def bank_deposit(db, emp, *, cash_account_id, source_id, amount, **kw):
    """SAFE -> BANK: yagona OUT·BANK_DEPOSIT (transfer header YO'Q)."""
    return _post(db, emp, cash_account_id=cash_account_id, direction=CashDirection.OUT.value,
                 category=CashCategory.BANK_DEPOSIT.value, source_type=CashSourceType.CASH_OP.value,
                 source_id=source_id, amount=amount, **kw)


def transfer(db, emp, *, from_account_id, to_account_id, amount, source_id=None, commit=True, **kw):
    tc = TransferCommand(from_account_id=from_account_id, to_account_id=to_account_id,
                         amount=Decimal(str(amount)), source_id=source_id or uuid.uuid4(), **kw)
    return _svc.post_transfer(db, emp, tc, commit=commit)


def reversal(db, emp, *, reverses_id, source_id=None, commit=True, **kw):
    rc = ReversalCommand(reverses_id=reverses_id, source_id=source_id or uuid.uuid4(),
                         cash_account_id=None, **kw)
    return _svc.post_reversal(db, emp, rc, commit=commit)
