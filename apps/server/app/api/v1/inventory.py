import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import MovementType
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch

router = APIRouter(tags=["inventory"])


def _first_branch(db: Session, company_id):
    b = db.query(Branch).filter(Branch.company_id == company_id, Branch.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(400, "Filial topilmadi")
    return b


def _get_product(db: Session, product_id, company_id):
    p = db.get(Product, product_id)
    if not p or p.company_id != company_id or p.deleted_at is not None:
        raise HTTPException(400, f"Mahsulot topilmadi: {product_id}")
    return p

MOVE_LABEL = {
    "purchase_in": ("Kirim", "in"),
    "return_in": ("Qaytdi", "in"),
    "sale_out": ("Sotildi", "out"),
    "writeoff": ("Hisobdan", "out"),
    "adjustment": ("Tuzatish", "in"),
    "transfer_in": ("Transfer keldi", "in"),
    "transfer_out": ("Transfer ketdi", "out"),
    "count_adjust": ("Inventarizatsiya", "in"),
}


@router.get("/inventory/overview")
def overview(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)  # filialга bog'langan xodim — faqat o'z filiali qoldig'i
    total = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)
    ).count()
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    out = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= 0)
    )
    # "Bugun" — do'kon MAHALLIY kuni (hisobotlar bilan izchil); UTC sana ofset tufayli noto'g'ri edi.
    from app.api.v1.reports import _store_tz
    LOCAL = _store_tz(db, emp.company_id)
    day0 = (datetime.now(timezone.utc).astimezone(LOCAL)
            .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
    moves_today = (
        db.query(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .filter(Product.company_id == emp.company_id,  # tenant izolyatsiyasi
                StockMovement.created_at >= day0)
    )
    if bset is not None:
        low = low.filter(Inventory.branch_id.in_(bset))
        out = out.filter(Inventory.branch_id.in_(bset))
        moves_today = moves_today.filter(StockMovement.branch_id.in_(bset))
    return {"total_products": total, "low_count": low.count(), "out_count": out.count(), "moves_today": moves_today.count()}


@router.get("/inventory/movements")
def movements(limit: int = 20, product_id: uuid.UUID | None = None,
              emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.models.auth import Employee as Emp

    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)
    query = (
        db.query(StockMovement, Product.name, Emp.full_name)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(Emp, Emp.id == StockMovement.employee_id)
        .filter(Product.company_id == emp.company_id)
    )
    if bset is not None:
        query = query.filter(StockMovement.branch_id.in_(bset))
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    rows = query.order_by(StockMovement.created_at.desc()).limit(min(limit, 100)).all()
    out = []
    for m, name, who in rows:
        label, direction = MOVE_LABEL.get(m.type.value, (m.type.value, "in"))
        # Tuzatish/inventarizatsiya IKKI tomonlama — yo'nalish qty ishorasidan
        if m.type.value in ("adjustment", "count_adjust"):
            direction = "out" if float(m.qty) < 0 else "in"
        out.append({
            "type": label,
            "direction": direction,
            "name": name,
            "qty": float(m.qty),
            "employee": who or "—",
            "at": m.created_at,
        })
    return out


class WriteoffIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)  # brak | expired | inventory | ...
    client_uuid: uuid.UUID | None = None  # idempotentlik — timeout'да qayta yuborishда ikki marta kamaymasin


@router.post("/inventory/writeoff")
def writeoff(data: WriteoffIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Hisobdan chiqarish (brak/muddati o'tgan/inventar) — qoldiqni kamaytiradi + ledger."""
    from app.core.deps import actor_branch
    # DEDUP: shu client_uuid bilan writeoff allaqachon bo'lgan bo'lsa — qayta kamaytirmaymiz.
    if data.client_uuid:
        dup = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.type == MovementType.writeoff).first()
        if dup:
            return {"ok": True, "duplicate": True}
    branch = actor_branch(emp, db) or _first_branch(db, emp.company_id)  # xodim filialiga yoziladi
    prod = _get_product(db, data.product_id, emp.company_id)
    qty = Decimal(str(data.qty))
    # QATOR QULFI: sotuv (services/sales.py) qatorni with_for_update bilan qulflaydi;
    # writeoff qulflamasa Postgres'да bir vaqtдаги sotuv/writeoff STALE qoldiqni o'qib
    # tekshiruvдан o'tib qoldiqни yo'qotardi (lost update / oversell). Endi qulflanadi.
    inv = (db.query(Inventory)
           .filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id)
           .with_for_update().first())
    have = Decimal(str(inv.qty)) if inv else Decimal("0")
    if qty > have:
        raise HTTPException(400, f"Yetarli qoldiq yo'q: {prod.name} (qoldiq: {have:g})")
    now = datetime.now(timezone.utc)
    inv.qty = have - qty
    inv.updated_at = now
    db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.writeoff,
                         qty=-qty, balance_after=inv.qty, ref_type="writeoff", reason=data.reason,
                         employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
    db.commit()
    return {"ok": True, "product": prod.name, "new_qty": float(inv.qty)}


class CountItem(BaseModel):
    product_id: uuid.UUID
    counted: float = Field(ge=0, le=1e9, allow_inf_nan=False)  # absurd katta sanoq qoldiqni buzmasin


class CountIn(BaseModel):
    items: list[CountItem] = Field(max_length=20000)  # massiv-DoS oldini olish


@router.post("/inventory/count")
def stock_count(data: CountIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Inventarizatsiya — sanoq bilan tizim qoldig'ini solishtiradi; farqqa tuzatish yozadi."""
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    from app.core.deps import actor_branch
    branch = actor_branch(emp, db) or _first_branch(db, emp.company_id)  # xodim filialiga yoziladi
    now = datetime.now(timezone.utc)
    results = []
    changed = 0
    # QATOR QULFI: sanoq inv.qty ni counted'ga MUTLAQ o'rnatadi — bir vaqtдаги sotuv o'rtада bo'lса
    # (qulfsiz) yo'qolардi. Qatorlarni DASTAVVAL bir xil tartibda (product_id) qulflaymiz.
    for _pid in sorted({it.product_id for it in data.items}, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for it in data.items:
        prod = _get_product(db, it.product_id, emp.company_id)
        counted = Decimal(str(it.counted))
        inv = db.query(Inventory).filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id).first()
        if inv is None:
            inv = Inventory(product_id=prod.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        old = Decimal(str(inv.qty))
        diff = counted - old
        if diff != 0:
            changed += 1
            inv.qty = counted
            inv.updated_at = now
            if counted > Decimal(str(inv.min_qty or 0)):
                inv.low_alerted = False
            db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.adjustment,
                                 qty=diff, balance_after=counted, ref_type="count", reason="inventarizatsiya",
                                 employee_id=emp.id, created_at=now))
        results.append({"product": prod.name, "old": float(old), "counted": float(counted), "diff": float(diff)})
    db.commit()
    return {"ok": True, "changed": changed, "results": results}


@router.get("/inventory/low")
def low_stock(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)
    q = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= Inventory.min_qty)
    )
    if _bset is not None:
        q = q.filter(Inventory.branch_id.in_(_bset))
    rows = q.order_by(Inventory.qty).all()
    return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]
