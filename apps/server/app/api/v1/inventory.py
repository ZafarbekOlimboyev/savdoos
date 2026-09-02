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
def movements(limit: int = 20, offset: int = 0, product_id: uuid.UUID | None = None,
              emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    # QA WH-020: endi hisobot.view talab qilinadi (kassir ombor ledgerini ko'rmasin).
    from app.models.auth import Employee as Emp

    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)
    query = (
        db.query(StockMovement, Product.name, Emp.full_name, Branch.name)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(Emp, Emp.id == StockMovement.employee_id)
        .outerjoin(Branch, Branch.id == StockMovement.branch_id)
        .filter(Product.company_id == emp.company_id)
    )
    if bset is not None:
        query = query.filter(StockMovement.branch_id.in_(bset))
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    # QA WH-013: manfiy limit Postgres'da 500 berardi (LIMIT -1) — endi 1..100 ga qisiladi.
    _lim = max(1, min(limit, 100))
    _off = max(0, min(offset, 100000))
    rows = query.order_by(StockMovement.created_at.desc()).offset(_off).limit(_lim).all()
    out = []
    for m, name, who, brname in rows:
        label, direction = MOVE_LABEL.get(m.type.value, (m.type.value, "in"))
        # Tuzatish/inventarizatsiya IKKI tomonlama — yo'nalish qty ishorasidan
        if m.type.value in ("adjustment", "count_adjust"):
            direction = "out" if float(m.qty) < 0 else "in"
        # QA WH-015: inventarizatsiya generik 'Tuzatish' emas — ref_type'dan aniqlanadi
        if m.type.value == "adjustment" and (m.ref_type or "") == "count":
            label = MOVE_LABEL["count_adjust"][0]
        out.append({
            "type": label,
            "direction": direction,
            "name": name,
            "qty": float(m.qty),
            "employee": who or "—",
            "branch": brname or "—",     # QA WH-014: ko'p-filial admin qaysi filialdaligini ko'rsin
            "reason": m.reason,
            "at": m.created_at,
        })
    return out


def _low_cross_check(inv, prod_name: str, crossed: list) -> None:
    """QA WH-009: min-chegara kesib o'tilishini HAR kamaytiruvchi amal belgilaydi (ilgari faqat
    sotuv). low_alerted dedup — bir kesishda bitta push."""
    if inv is not None and Decimal(str(inv.qty)) <= Decimal(str(inv.min_qty or 0)) and not bool(inv.low_alerted):
        inv.low_alerted = True
        crossed.append((prod_name, float(inv.qty)))


def _push_low(db, company_id, crossed: list, branch_name: str | None = None) -> None:
    if crossed:
        try:
            from app.services import push
            push.notify_low_stock(db, company_id, crossed, branch_name=branch_name)
        except Exception:  # noqa: BLE001
            pass


def _resolve_write_branch(db: Session, emp: Employee, branch_id: uuid.UUID | None):
    """QA WH-002: mobil endi filialni ANIQ tanlab yuboradi (ega/ko'p-filial). Berilmasa —
    eski xulq (actor_branch). Berilsa: o'z kompaniyasi + faol + ko'rish doirasida bo'lishi shart."""
    from app.core.deps import actor_branch, visible_branches
    if branch_id is None:
        return actor_branch(emp, db) or _first_branch(db, emp.company_id)
    b = db.get(Branch, branch_id)
    if not b or b.company_id != emp.company_id or b.deleted_at is not None:
        raise HTTPException(400, "Filial topilmadi")
    if not b.is_active:
        raise HTTPException(400, "Filial nofaol — amal bajarib bo'lmaydi")
    _vb = visible_branches(emp, db)
    if _vb is not None and b.id not in _vb:
        raise HTTPException(403, "Ruxsat yo'q: bu filial sizga biriktirilmagan")
    return b


class WriteoffIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)  # brak | expired | inventory | ...
    client_uuid: uuid.UUID | None = None  # idempotentlik — timeout'да qayta yuborishда ikki marta kamaymasin
    branch_id: uuid.UUID | None = None    # QA WH-002: qaysi filialdan chiqarish (berilmasa actor)


@router.post("/inventory/writeoff")
def writeoff(data: WriteoffIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Hisobdan chiqarish (brak/muddati o'tgan/inventar) — qoldiqni kamaytiradi + ledger."""
    # DEDUP: shu client_uuid bilan writeoff allaqachon bo'lgan bo'lsa — qayta kamaytirmaymiz.
    if data.client_uuid:
        dup = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.type == MovementType.writeoff).first()
        if dup:
            return {"ok": True, "duplicate": True}
    branch = _resolve_write_branch(db, emp, data.branch_id)
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
    _crossed: list = []
    _low_cross_check(inv, prod.name, _crossed)   # QA WH-009: writeoff kesishi ham push beradi
    db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.writeoff,
                         qty=-qty, balance_after=inv.qty, ref_type="writeoff", reason=data.reason,
                         employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
    # SELECT-dedup (yuqorida) race'ga chidamli emas — ikki konkurrent takror qoldiqni 2x kamaytirardi.
    # DB unique indeksi (ux_stockmov_client_prod_type) ikkinchisini ushlaydi -> tranzaksiya bekor, dublikat javob.
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        db.rollback()
        if data.client_uuid:
            return {"ok": True, "duplicate": True}
        raise
    _push_low(db, emp.company_id, _crossed, branch.name)
    return {"ok": True, "product": prod.name, "new_qty": float(inv.qty)}


class CountItem(BaseModel):
    product_id: uuid.UUID
    counted: float = Field(ge=0, le=1e9, allow_inf_nan=False)  # absurd katta sanoq qoldiqni buzmasin


class CountIn(BaseModel):
    items: list[CountItem] = Field(max_length=20000)  # massiv-DoS oldini olish
    client_uuid: uuid.UUID | None = None  # QA WH-023: offline retry idempotentligi (writeoff bilan izchil)
    branch_id: uuid.UUID | None = None    # QA WH-002: qaysi filial sanalmoqda (berilmasa actor)


@router.post("/inventory/count")
def stock_count(data: CountIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Inventarizatsiya — sanoq bilan tizim qoldig'ini solishtiradi; farqqa tuzatish yozadi.
    QA WH-001: yangi (qator yo'q) mahsulotga parallel yozuvchi bilan INSERT poygasi xom 500
    berardi (real-Postgres isbot) — endi boshqa ombor-yozuvchilardagi 3x retry-o'ram."""
    from sqlalchemy.exc import IntegrityError as _IE
    for _try in range(3):
        try:
            return _stock_count_once(data, emp, db)
        except _IE:
            db.rollback()   # parallel INSERT to'qnashuvi — keyingi urinishda qator mavjud
    raise HTTPException(409, "Ombor band — sanoqni qayta yuboring")


def _stock_count_once(data: CountIn, emp: Employee, db: Session):
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    # DEDUP (QA WH-023): shu client_uuid bilan sanoq allaqachon qo'llangan bo'lsa — qayta emas.
    if data.client_uuid:
        dup = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.type == MovementType.adjustment).first()
        if dup:
            return {"ok": True, "duplicate": True, "changed": 0, "results": []}
    branch = _resolve_write_branch(db, emp, data.branch_id)
    now = datetime.now(timezone.utc)
    results = []
    changed = 0
    _crossed: list = []
    # QATOR QULFI: sanoq inv.qty ni counted'ga MUTLAQ o'rnatadi — bir vaqtдаги sotuv o'rtада bo'lса
    # (qulfsiz) yo'qolардi. Qatorlarni DASTAVVAL bir xil tartibda (product_id) qulflaymiz.
    # QA WH-001: qator YO'Q bo'lsa shu yerda 0-qoldiq bilan YARATIB qulflaymiz — pre-lock'dan
    # keyin paydo bo'lgan qatorni qulfsiz o'qish (lost-update oynasi) yopiladi; parallel INSERT
    # to'qnashuvi flush'da otilib retry-o'ramga tushadi.
    for _pid in sorted({it.product_id for it in data.items}, key=str):
        _row = db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
        if _row is None:
            db.add(Inventory(product_id=_pid, branch_id=branch.id, qty=Decimal("0"), updated_at=now))
            db.flush()
            db.query(Inventory).filter(
                Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for it in data.items:
        prod = _get_product(db, it.product_id, emp.company_id)
        counted = Decimal(str(it.counted))
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id)
               .with_for_update().first())   # QA WH-001: o'qish ham qulf ostida
        old = Decimal(str(inv.qty))
        diff = counted - old
        if diff != 0:
            changed += 1
            inv.qty = counted
            inv.updated_at = now
            if counted > Decimal(str(inv.min_qty or 0)):
                inv.low_alerted = False
            else:
                _low_cross_check(inv, prod.name, _crossed)   # QA WH-009: pastga tuzatish ham ogohlantiradi
            db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.adjustment,
                                 qty=diff, balance_after=counted, ref_type="count", reason="inventarizatsiya",
                                 employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
        results.append({"product": prod.name, "old": float(old), "counted": float(counted), "diff": float(diff)})
    db.commit()
    _push_low(db, emp.company_id, _crossed, branch.name)
    return {"ok": True, "changed": changed, "results": results}


@router.get("/inventory/low")
def low_stock(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    # QA WH-020: hisobot.view darvozasi. QA WH-010: min_qty>0 sharti — aks holda katta katalogda
    # (Fayzan: import min=0) har qty=0 mahsulot '0<=0' bilan ro'yxatni bosardi; limit ham qo'shildi.
    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)
    q = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True),
                Inventory.min_qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    if _bset is not None:
        q = q.filter(Inventory.branch_id.in_(_bset))
    rows = q.order_by(Inventory.qty).limit(200).all()
    return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]
