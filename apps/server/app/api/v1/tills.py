# -*- coding: utf-8 -*-
"""TILL (fizik cash drawer) lifecycle — CRUD + activate/deactivate (DYNAMIC TILL model).

Branch 0..N TILL. Admin kerak bo'lganda yangi kassa (TILL) qo'shadi, nomini o'zgartiradi, faollashtiradi
yoki o'chiradi (deactivate = ARCHIVED). Tarixiy ishlatilган TILL HARD DELETE QILINMAYDI (Sale/Shift/
Return/Ledger uni ko'rsatadi) — faqat deactivate. TILL id (UUID) barqaror identity; label = fizik
identity (till_identity konvensiyasi). Cash subsystem faqat Postgres — SQLite/cash-disabled'да 400.

FILIAL DOIRASI (Phase 5F): kassa/seyf va `/cash-setup` KANONIK `visible_branches` bo'yicha
cheklanadi — boshqa endpointlar bilan AYNI qoida:
  · ro'yxat JIMGINA filtrlanadi (ko'rinmaydigan filial kassasi ro'yxatga tushmaydi);
  · aniq `branch_id` yoki bitta hisob ko'rinmaydigan filialdan bo'lsa — begona tenant bilan
    AYNI 404 (IDOR: filial/kassa mavjudligi oshkor bo'lmaydi);
  · YANGI kassa/seyf ko'rinmaydigan filialga — 403 (inventory `_resolve_write_branch` pretsedenti);
    begona tenant filiali avvalgidek 400 "Filial topilmadi".
Ilgari filialga biriktirilgan administrator boshqa filial kassasini arxivlay/o'chira, kassir esa
butun do'kon kassalarini (terminal UUID'lari bilan) o'qiy olardi.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import actor_branch, get_current_employee, require, require_any, visible_branches
from app.db.session import get_db
from app.models.auth import Employee
from app.models.org import Branch, Terminal
from app.services.cash import retrofit as _cr
from app.services.cash import till_identity as _ti

router = APIRouter(tags=["tills"])

# O'QISH darvozasi (`/tills`, `/safes`). Iste'molchilar: POS smena ekrani (kassir — kassa.sell/
# kassa.view), Manager «Kassalar» (sidebar sozlamalar.view talab qiladi; yozuv sozlamalar.edit)
# va hisobot o'quvchisi (naqd hisobotlar kassa kodini ko'rsatadi). Ilgari bu yerda FAQAT
# autentifikatsiya edi — ombor xodimi ham terminal bog'lanishlari bilan kassa ro'yxatini olardi.
TILL_READ_PERMS = ("kassa.sell", "kassa.view", "sozlamalar.view", "sozlamalar.edit", "hisobot.view")


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


def _in_scope(vb: set | None, branch_id) -> bool:
    """`visible_branches` to'plamida bormi (None = cheklovsiz). Satr bo'yicha solishtiriladi:
    to'plam elementlari va ustun qiymati turli manbadan (UUID/str) kelishi mumkin."""
    return vb is None or str(branch_id) in {str(b) for b in vb}


def _readable_branch(db: Session, emp: Employee, branch_id) -> Branch:
    """O'qish uchun ANIQ so'ralgan filial: shu kompaniyaniki VA ko'rish doirasida — aks holda 404.

    Ko'rinmaydigan filial begona tenant (yoki mavjud bo'lmagan id) bilan AYNI javob oladi:
    aks holda javob farqi boshqa filial id'si mavjudligini tasdiqlovchi oracle bo'lardi.
    O'chirilgan/nofaol filial (o'z doirasida) avvalgidek o'qiladi — arxiv tarixi yopilmaydi."""
    br = db.get(Branch, branch_id)
    if br is None or str(br.company_id) != str(emp.company_id):
        raise HTTPException(404, "Filial topilmadi")
    if not _in_scope(visible_branches(emp, db), br.id):
        raise HTTPException(404, "Filial topilmadi")
    return br


def _writable_branch(db: Session, emp: Employee, branch_id) -> Branch:
    """YANGI kassa/seyf filiali. Begona tenant/o'chirilgan -> 400 (avvalgi shartnoma, o'zgarmagan);
    shu do'konning, lekin xodimga biriktirilmagan filiali -> 403 (inventory pretsedenti).
    Tartib muhim: tenant tekshiruvi OLDIN — begona filialga 403 berilsa, u mavjudligini
    oshkor qilardi."""
    br = db.get(Branch, branch_id)
    if br is None or str(br.company_id) != str(emp.company_id) or br.deleted_at is not None:
        raise HTTPException(400, "Filial topilmadi")
    if not _in_scope(visible_branches(emp, db), br.id):
        raise HTTPException(403, "Ruxsat yo'q: bu filial sizga biriktirilmagan")
    return br


def _acc(db, emp, till_id, *, kind="TILL"):
    """SHU tenant VA xodim KO'RA OLADIGAN filial hisobini yuklaydi (yo'q/boshqa tenant/boshqa tur/
    ko'rinmaydigan filial -> 404). Ko'rinmaydigan filial begona tenant bilan AYNI javob oladi —
    filialga biriktirilgan administrator boshqa filial kassasini arxivlay/o'chira olmasin."""
    from app.models.cash import CashAccount
    a = db.get(CashAccount, till_id)
    if (a is None or str(a.tenant_id) != str(emp.company_id) or a.type != kind
            or not _in_scope(visible_branches(emp, db), a.branch_id)):
        raise HTTPException(404, ("Kassa (TILL) topilmadi" if kind == "TILL" else "Seyf topilmadi"))
    return a


def _list_accounts(db: Session, emp: Employee, kind: str, branch_id, active_only: bool,
                   mine: bool) -> list[dict]:
    """`/tills` va `/safes` ro'yxati — BITTA doira qoidasi (ikkisi ajralib ketmasin).

    Tartib: aniq `branch_id` (ko'rinishi tekshiriladi) > `mine` (actor_branch) > ko'rinadigan
    filiallar. `mine` ATAYLAB `visible_branches` bilan kesishtirilmaydi: smena ochish va savdo
    AYNAN `actor_branch` ga yoziladi (biriktirilgan filial nofaol bo'lsa — birinchi faol filial),
    kassa tanlash ro'yxati o'sha yozuv filialidan boshqacha bo'lsa, kassir smena ocholmay
    qolardi."""
    _require_cash(db)
    from app.models.cash import CashAccount
    q = select(CashAccount).where(CashAccount.tenant_id == emp.company_id, CashAccount.type == kind)
    if branch_id is not None:
        _readable_branch(db, emp, branch_id)
        q = q.where(CashAccount.branch_id == branch_id)
    elif mine:
        _br = actor_branch(emp, db)
        if _br is None:
            return []
        q = q.where(CashAccount.branch_id == _br.id)
    else:
        vb = visible_branches(emp, db)
        if vb is not None:
            q = q.where(CashAccount.branch_id.in_(list(vb)))
    if active_only:
        q = q.where(CashAccount.status == "ACTIVE")
    # ORDER BY: ilgari tartib heap'ga bog'liq edi (UPDATE/VACUUM dan keyin o'zgarardi) —
    # POS tanlash ro'yxati va Manager jadvali har ochilishda boshqacha chiqmasin.
    q = q.order_by(CashAccount.created_at, CashAccount.id)
    return [_out(a) for a in db.scalars(q).all()]


def _out(a) -> dict:
    p = _ti.parse_label(a.label) or {}
    return {"id": str(a.id), "branch_id": str(a.branch_id), "type": a.type,
            "code": p.get("checkout_code"), "label": a.label,
            "terminal_id": (str(p.get("terminal_id")) if p.get("terminal_id") else None),
            "currency": a.currency, "status": a.status, "active": a.status == "ACTIVE"}


@router.get("/tills")
def list_tills(branch_id: uuid.UUID | None = None, active_only: bool = False, mine: bool = False,
               emp: Employee = Depends(require_any(*TILL_READ_PERMS)),
               db: Session = Depends(get_db)):
    """Filial(lar)ning TILL'lari. Tenant izolyatsiyasi HAR DOIM (tenant_id == emp.company_id),
    filial doirasi — `visible_branches` (`_list_accounts`).

    POS uchun (§2): `?mine=true&active_only=true` -> FAQAT kassirning JORIY filiali va FAQAT ACTIVE.
    Kassir smena ochishда AYNAN kassani tanlashi uchun shu ro'yxat ishlatiladi; boshqa filial yoki
    ARCHIVED kassa ro'yxatga TUSHMAYDI (aks holda tanlash mumkin bo'lib, keyin server rad etardi).
    O'qish `TILL_READ_PERMS` dan birini talab qiladi; YOZISH (create/rename/archive) avvalgidek
    `sozlamalar.edit`. `active_only` standarti O'ZGARMAGAN (False — arxiv kassalar ham
    ko'rinadi)."""
    return _list_accounts(db, emp, "TILL", branch_id, active_only, mine)


@router.post("/tills")
def create_till(data: TillCreate, emp: Employee = Depends(require("sozlamalar.edit")),
                db: Session = Depends(get_db)):
    """Yangi FIZIK kassa (TILL). IDEMPOTENT: (tenant, branch, code) mavjud bo'lса o'shani qaytaradi.
    Migration TALAB QILMAYDI — istalgan payt (cutover'дан keyin ham) qo'shsa bo'ladi."""
    _require_cash(db)
    from datetime import datetime, timezone
    from app.models.cash import CashAccount
    # Idempotent qaytarishdan OLDIN: aks holda ko'rinmaydigan filialdagi mavjud kassa (kod bo'yicha)
    # 403 o'rniga to'liq qaytib, doira chetlab o'tilardi.
    _writable_branch(db, emp, data.branch_id)
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


class SafeCreate(BaseModel):
    branch_id: uuid.UUID
    code: str = Field(default="SAFE", min_length=1, max_length=64)
    currency: str | None = Field(default=None, max_length=3)


@router.get("/cash-setup")
def cash_setup_state(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Do'konning naqd sozlanish holati (Manager sozlash ekrani uchun).

    Migration tushunchalari (T0, backfill, historical_till_unknown, shadow compare) BU YERDA
    KO'RSATILMAYDI — ular operator/ichki vositalar uchun. Oddiy savdogar faqat "qaysi filialda
    nechta kassa bor" degan savolni ko'radi.

    FAQAT ko'rinadigan filiallar (Phase 5F): «Kassalar» ekrani har qatordagi filial uchun
    `/tills?branch_id=` so'raydi — ro'yxatda ko'rinmaydigan filial qolsa, u 404 olib butun ekran
    yiqilardi (va filial nomi/kassa soni boshqa filial xodimiga oshkor bo'lardi)."""
    _require_cash(db)
    from app.services.cash import tenant as _t
    return _t.onboarding_state(db, emp.company_id, branch_ids=visible_branches(emp, db))


@router.post("/safes")
def create_safe(data: SafeCreate, emp: Employee = Depends(require("sozlamalar.edit")),
                db: Session = Depends(get_db)):
    """Filial SEYFI (SAFE) — FAQAT operator ATAYLAB so'raganda. AVTOMATIK YARATILMAYDI.
    Filial 0..N SAFE bo'lishi mumkin; SAFE faqat inkassa (TILL->SAFE) uchun kerak.
    IDEMPOTENT: shu filialda ACTIVE SAFE bo'lsa o'shani qaytaradi."""
    _require_cash(db)
    from datetime import datetime, timezone
    from app.models.cash import CashAccount
    _writable_branch(db, emp, data.branch_id)    # idempotent qaytarishdan OLDIN (create_till kabi)
    code = data.code.strip()
    if not code or " " in code:
        raise HTTPException(400, "Seyf kodida bo'sh joy bo'lmaydi")
    # IDEMPOTENT KOD BO'YICHA (kassa bilan izchil). Filial 0..N SAFE bo'lishi mumkin, shu bois
    # "filialda seyf bor" degan sababli qaytarib yubormaymiz — aks holda ikkinchi seyf
    # yaratib bo'lmasdi va §8 dagi 0..N modeli buzilardi.
    from app.models.cash import CashAccount as _CA0
    for a in db.scalars(select(_CA0).where(_CA0.tenant_id == emp.company_id,
                                           _CA0.branch_id == data.branch_id,
                                           _CA0.type == "SAFE",
                                           _CA0.status == "ACTIVE")).all():
        if _ti.account_checkout_code(a) == code:
            return _out(a)
    cur = ((data.currency or _company_currency(db, emp) or "UZS") or "UZS").strip().upper()[:3]
    acc = CashAccount(tenant_id=emp.company_id, branch_id=data.branch_id, type="SAFE",
                      currency=cur, status="ACTIVE", label=_ti.safe_label(code),
                      created_at=datetime.now(timezone.utc))
    db.add(acc); db.commit(); db.refresh(acc)
    return _out(acc)


@router.get("/safes")
def list_safes(branch_id: uuid.UUID | None = None, active_only: bool = True, mine: bool = False,
               emp: Employee = Depends(require_any(*TILL_READ_PERMS)),
               db: Session = Depends(get_db)):
    """Filial seyflari. SAFE MAJBURIY EMAS — bo'sh ro'yxat QONUNIY holat.
    Darvoza va filial doirasi `/tills` bilan AYNI; `active_only` standarti O'ZGARMAGAN (True)."""
    return _list_accounts(db, emp, "SAFE", branch_id, active_only, mine)


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
