# -*- coding: utf-8 -*-
"""TILL (fizik cash drawer) lifecycle — CRUD + activate/deactivate (DYNAMIC TILL model).

Branch 0..N TILL. Admin kerak bo'lganda yangi kassa (TILL) qo'shadi, nomini o'zgartiradi, faollashtiradi
yoki o'chiradi (deactivate = ARCHIVED). Tarixiy ishlatilган TILL HARD DELETE QILINMAYDI (Sale/Shift/
Return/Ledger uni ko'rsatadi) — faqat deactivate. TILL id (UUID) barqaror identity; label = fizik
identity (till_identity konvensiyasi). Cash subsystem faqat Postgres — SQLite/cash-disabled'да 400.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.org import Branch, Terminal
from app.services.cash import retrofit as _cr
from app.services.cash import till_identity as _ti

router = APIRouter(tags=["tills"])


class TillCreate(BaseModel):
    branch_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)     # (tenant, branch) doirasida barqaror identity
    label: str | None = Field(default=None, max_length=120)   # inson-nomi (Kassa 1) — ixtiyoriy
    terminal_id: uuid.UUID | None = None
    currency: str | None = Field(default=None, max_length=3)


class TillUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)   # rename (display identity)
    active: bool | None = None                          # True=faollashtirish, False=deactivate (ARCHIVED)


def _require_cash(db: Session) -> None:
    if not _cr.cash_enabled(db):
        raise HTTPException(400, "Cash quyi tizimi yoqilmagan (Postgres + cash schema kerak)")


def _acc(db, emp, till_id):
    """SHU tenant TILL hisobini yuklaydi (yo'q/boshqa tenant/SAFE -> 404)."""
    from app.models.cash import CashAccount
    a = db.get(CashAccount, till_id)
    if a is None or str(a.tenant_id) != str(emp.company_id) or a.type != "TILL":
        raise HTTPException(404, "Kassa (TILL) topilmadi")
    return a


def _out(a) -> dict:
    p = _ti.parse_label(a.label) or {}
    return {"id": str(a.id), "branch_id": str(a.branch_id), "type": a.type,
            "code": p.get("checkout_code"), "label": a.label,
            "terminal_id": (str(p.get("terminal_id")) if p.get("terminal_id") else None),
            "currency": a.currency, "status": a.status, "active": a.status == "ACTIVE"}


@router.get("/tills")
def list_tills(branch_id: uuid.UUID | None = None, active_only: bool = False, mine: bool = False,
               emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Filial(lar)ning TILL'lari. Tenant izolyatsiyasi HAR DOIM (tenant_id == emp.company_id).

    POS uchun (§2): `?mine=true&active_only=true` -> FAQAT kassirning JORIY filiali va FAQAT ACTIVE.
    Kassir smena ochishда AYNAN kassani tanlashi uchun shu ro'yxat ishlatiladi; boshqa filial yoki
    ARCHIVED kassa ro'yxatga TUSHMAYDI (aks holda tanlash mumkin bo'lib, keyin server rad etardi).
    O'qish uchun qo'shimcha ruxsat TALAB QILINMAYDI (get_current_employee) — YOZISH (create/rename/
    archive) esa avvalgidek `sozlamalar.edit` da qoladi."""
    _require_cash(db)
    from app.models.cash import CashAccount
    q = select(CashAccount).where(CashAccount.tenant_id == emp.company_id, CashAccount.type == "TILL")
    if mine and branch_id is None:
        from app.core.deps import actor_branch
        _br = actor_branch(emp, db)
        if _br is None:
            return []
        branch_id = _br.id
    if branch_id is not None:
        q = q.where(CashAccount.branch_id == branch_id)
    if active_only:
        q = q.where(CashAccount.status == "ACTIVE")
    return [_out(a) for a in db.scalars(q).all()]


@router.post("/tills")
def create_till(data: TillCreate, emp: Employee = Depends(require("sozlamalar.edit")),
                db: Session = Depends(get_db)):
    """Yangi FIZIK kassa (TILL). IDEMPOTENT: (tenant, branch, code) mavjud bo'lса o'shani qaytaradi.
    Migration TALAB QILMAYDI — istalgan payt (cutover'дан keyin ham) qo'shsa bo'ladi."""
    _require_cash(db)
    from datetime import datetime, timezone
    from app.models.cash import CashAccount
    br = db.get(Branch, data.branch_id)
    if br is None or str(br.company_id) != str(emp.company_id) or br.deleted_at is not None:
        raise HTTPException(400, "Filial topilmadi")
    if data.terminal_id is not None:
        t = db.get(Terminal, data.terminal_id)
        if t is None or str(t.branch_id) != str(data.branch_id):
            raise HTTPException(400, "Terminal topilmadi yoki bu filialga tegishli emas")
    code = data.code.strip()
    if " " in code:
        raise HTTPException(400, "Kassa kodида bo'sh joy bo'lmaydi (masalan TILL-01)")
    existing = _ti.find_till_by_checkout(db, emp.company_id, data.branch_id, code)
    if existing is not None:
        return _out(existing)
    cur = ((data.currency or _company_currency(db, emp) or "UZS") or "UZS").strip().upper()[:3]
    acc = CashAccount(tenant_id=emp.company_id, branch_id=data.branch_id, type="TILL",
                      currency=cur, status="ACTIVE",
                      label=_ti.till_label(code, data.terminal_id), created_at=datetime.now(timezone.utc))
    db.add(acc); db.commit(); db.refresh(acc)
    return _out(acc)


@router.patch("/tills/{till_id}")
def update_till(till_id: uuid.UUID, data: TillUpdate,
                emp: Employee = Depends(require("sozlamalar.edit")), db: Session = Depends(get_db)):
    """RENAME (code — display identity; terminal binding SAQLANADI) va/yoki ACTIVATE/DEACTIVATE.
    TILL id (UUID) barqaror; eski Sale/Receipt snapshot bilan xavfsiz (RC6). Deactivate = ARCHIVED."""
    _require_cash(db)
    a = _acc(db, emp, till_id)
    if data.code is not None:
        code = data.code.strip()
        if not code or " " in code:
            raise HTTPException(400, "Kassa kodi noto'g'ri (bo'sh joysiz)")
        term = _ti.account_terminal_id(a)                # terminal binding SAQLANADI
        other = _ti.find_till_by_checkout(db, emp.company_id, a.branch_id, code)
        if other is not None and str(other.id) != str(a.id):
            raise HTTPException(400, f"Bu filialда '{code}' kodли kassa allaqачон bor")
        a.label = _ti.till_label(code, term)
    if data.active is not None:
        if not data.active and a.status == "ACTIVE":
            # §10: OCHIQ smena shu kassaga bog'langan bo'lsa — ARXIVLASH RAD ETILADI. Aks holda
            # smena "yaroqsiz TILL"ga bog'langan holda qoladi: readiness uni TAYYOR deb ko'rsatardi
            # (has_till), runtime esa T0'dan keyin TILL_INVALID bilan smena o'rtasida to'xtatardi.
            from app.models.enums import ShiftStatus as _SS
            from app.models.shifts import Shift as _Sh
            _open = db.query(_Sh.id).filter(_Sh.till_id == a.id, _Sh.status == _SS.open,
                                            _Sh.deleted_at.is_(None)).first()
            if _open is None:
                # Ledger tomonidagi OCHIQ cash.shift ham to'sqinlik qiladi: legacy smena yopilgan,
                # lekin cash.shift ochiq qolgan holat mumkin (dual-write guarded no-op bo'lsa).
                from app.models.cash import CashShift as _CSh
                _open = db.query(_CSh.id).filter(_CSh.cash_account_id == a.id,
                                                 _CSh.status == "OPEN").first()
            if _open is not None:
                raise HTTPException(409, "Bu kassada OCHIQ smena bor — avval smenani yoping, "
                                         "keyin kassani arxivlang.")
        a.status = "ACTIVE" if data.active else "ARCHIVED"
    db.add(a); db.commit(); db.refresh(a)
    return _out(a)


@router.delete("/tills/{till_id}")
def delete_till(till_id: uuid.UUID, emp: Employee = Depends(require("sozlamalar.edit")),
                db: Session = Depends(get_db)):
    """HARD DELETE — FAQAT hech qachon ishlatilmagan (referenced EMAS) TILL uchun (xato yaratilган).
    Tarixiy ishlatilган TILL O'CHIRILMAYDI (400) — audit izi buzilmasin; o'rniga deactivate ishlating."""
    _require_cash(db)
    a = _acc(db, emp, till_id)
    if till_referenced(db, till_id):
        raise HTTPException(400, "Bu kassa tarixда ishlatilган (savdo/smena/ledger) — o'chirib bo'lmaydi. "
                                 "O'rniga deactivate qiling.")
    db.delete(a); db.commit()
    return {"ok": True, "deleted": str(till_id)}


def till_referenced(db: Session, till_id) -> bool:
    """TILL Sale/Shift/Return/CashLedgerEntry/CashShift'да ishlatilганmi (hard-delete taqiqi)."""
    from app.models.cash import CashLedgerEntry, CashShift
    from app.models.sales import Return, Sale
    from app.models.shifts import Shift
    checks = [
        select(Sale.id).where(Sale.till_id == till_id),
        select(Shift.id).where(Shift.till_id == till_id),
        select(Return.id).where(Return.till_id == till_id),
        select(CashLedgerEntry.id).where(CashLedgerEntry.cash_account_id == till_id),
        select(CashShift.id).where(CashShift.cash_account_id == till_id),
    ]
    return any(db.execute(q.limit(1)).first() is not None for q in checks)


def _company_currency(db, emp):
    from app.models.org import Company
    co = db.get(Company, emp.company_id)
    return (co.currency if co else None)
