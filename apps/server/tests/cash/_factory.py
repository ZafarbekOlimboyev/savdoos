# -*- coding: utf-8 -*-
"""Cash testlari uchun yordamchilar — yaroqli qatorlarni quradi."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.cash import CashAccount, CashLedgerEntry, CashShift


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def make_account(db, env, type_, *, currency="UZS", status="ACTIVE", branch_id=None) -> CashAccount:
    a = CashAccount(
        tenant_id=env.company_id,
        branch_id=branch_id or env.branch_id,
        type=type_,
        currency=currency,
        status=status,
        created_at=env.now,
    )
    db.add(a)
    db.commit()
    return a


def open_shift(db, env, account, *, status="OPEN") -> CashShift:
    sh = CashShift(
        tenant_id=env.company_id,
        cash_account_id=account.id,
        branch_id=account.branch_id,
        account_type=account.type,
        status=status,
        opened_at=env.now,
        opened_by=env.employee_id,
        version=1,
    )
    db.add(sh)
    db.commit()
    return sh


def build_entry(env, account, *, shift=None, **over) -> CashLedgerEntry:
    d = dict(
        tenant_id=env.company_id,
        cash_account_id=account.id,
        branch_id=account.branch_id,
        account_type=account.type,
        shift_id=(shift.id if shift is not None else None),
        posting_kind=("ON_SHIFT" if shift is not None else "OFF_SHIFT"),
        source_type="SALE",
        source_id=uuid.uuid4(),
        leg_index=0,
        direction="IN",
        category="SALE",
        amount=Decimal("1000.00"),
        currency=account.currency,
        device_occurred_at=env.now,
        server_received_at=env.now,
        recorded_at=env.now,
        actor_id=env.employee_id,
        idempotency_key=str(uuid.uuid4()),
        provenance="NORMAL",
    )
    d.update(over)
    return CashLedgerEntry(**d)


def post_entry(db, env, account, *, shift=None, **over) -> CashLedgerEntry:
    e = build_entry(env, account, shift=shift, **over)
    db.add(e)
    db.commit()
    return e


def assert_rejects(db, action, needle: str | None = None):
    """action()' constraint/trigger bilan rad etilishini kutadi; sessiyani tozalaydi."""
    with pytest.raises(Exception) as ei:
        action()
    db.rollback()
    if needle is not None:
        assert needle.lower() in str(ei.value).lower(), f"expected '{needle}' in: {ei.value}"
    return ei.value

# ══ PHASE 1: SEYF ONBOARDING (ochilish attestatsiyasi) ══════════════════════
#
# ⚠️  NEGA HAR SEYF UCHUN KERAK. Phase 1 dan boshlab attestatsiyasiz SEYF OPERATSION
#     EMAS: unga posting ham, inkassa ham RAD etiladi (`SAFE_OPENING_REQUIRED`).
#     Bu ATAYLAB: noma'lum qoldiq NOL deb olinmaydi. Shu bois testlar ham haqiqiy
#     do'kon kabi avval attestatsiya qiladi — gard TESTDA AYLANIB O'TILMAYDI.
#
# ⚠️  Standart `KNOWN_ZERO`: yangi test seyfi BO'SH, va bo'sh seyf ledger legi
#     YOZMAYDI — ya'ni mavjud testlarning balans/parity hisoblari O'ZGARMAYDI.
_MANAGER_ROLE = "menejer"


def manager(db, env, *, company_id=None):
    """Attestatsiya uchun MENEJER roli bilan xodim (rol kodi `_is_manager_plus` uchun MUHIM)."""
    from app.models.auth import Employee, Role
    # ⚠️  ROL SEANS BOSHIDA yaratiladi (`conftest.py`) — bu yerda YARATILMAYDI: `roles`
    #     jadvalini test PAYTIDA o'zgartirish 30+ yordamchining tartibsiz
    #     `db.query(Role).first()` chaqiruvini seans o'rtasida ANIQLANMAGAN qilardi.
    r = db.query(Role).filter(Role.code == _MANAGER_ROLE).first()
    if r is None:                       # boshqa conftest (masalan ildiz to'plami) uchun zaxira
        r = Role(code=_MANAGER_ROLE, name="Menejer")
        db.add(r)
        db.flush()
    cid = company_id or env.company_id
    # MAVJUD menejerni QAYTA ISHLATAMIZ: har seyf uchun yangi xodim yaratish xodim
    # sonini sanaydigan testlarni buzardi.
    e = (db.query(Employee)
         .filter(Employee.company_id == cid, Employee.role_id == r.id)
         .first())
    if e is None:
        e = Employee(company_id=cid, full_name="Attestator", role_id=r.id)
        db.add(e)
        db.commit()
        db.refresh(e)
    e.role                      # rol yuklansin (`_is_manager_plus` unga qaraydi)
    return e


def open_safe(db, env, account, *, amount="0", ref="TEST-OPENING", emp=None, company_id=None):
    """SEYFni ISHGA TAYYOR qiladi — HAQIQIY xizmat orqali (qoida qayta yozilmaydi).

    `amount=0` -> `KNOWN_ZERO` (ledger legi YO'Q). Musbat summa -> `COUNTED` (bitta IN legi).
    """
    from decimal import Decimal as _D

    from app.services.cash import safe_opening as _so
    amt = _D(str(amount))
    kind = "COUNTED" if amt > 0 else "KNOWN_ZERO"
    who = emp or manager(db, env, company_id=company_id or account.tenant_id)
    row, _st = _so.attest_opening(db, who, account=account, kind=kind, counted_amount=amt,
                                  counted_at=account.created_at, attestation_ref=ref)
    return row
