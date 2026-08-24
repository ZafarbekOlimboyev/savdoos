import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.inventory import Inventory, StockMovement
from app.models.enums import MovementType
from app.schemas.catalog import CategoryOut, ProductBulkCreate, ProductOut
from app.services.audit import log as audit_log

router = APIRouter(tags=["catalog"])


def _stock_map(db: Session) -> dict:
    rows = db.query(Inventory.product_id, func.sum(Inventory.qty)).group_by(Inventory.product_id).all()
    return {pid: float(q or 0) for pid, q in rows}


def _min_map(db: Session) -> dict:
    rows = db.query(Inventory.product_id, func.max(Inventory.min_qty)).group_by(Inventory.product_id).all()
    return {pid: float(m or 0) for pid, m in rows}


def _unit_map(db: Session) -> dict:
    return {u.id: u.code for u in db.query(Unit).all()}


def _sold_map(db: Session, company_id) -> dict:
    """So'nggi 30 kunda mahsulot bo'yicha sotilgan miqdor (POS'da 'eng ko'p sotilgan' tartibi)."""
    from datetime import timedelta
    from app.models.sales import Sale, SaleItem
    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        db.query(SaleItem.product_id, func.coalesce(func.sum(SaleItem.qty), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == company_id, Sale.sold_at >= since)
        .group_by(SaleItem.product_id)
        .all()
    )
    return {pid: float(q or 0) for pid, q in rows}


def _to_out(p: Product, stock: dict, mins: dict | None = None, units: dict | None = None, sold: dict | None = None) -> ProductOut:
    mins = mins or {}
    units = units or {}
    sold = sold or {}
    return ProductOut(
        id=p.id,
        article_code=p.article_code,
        sku=p.sku,
        name=p.name,
        category_id=p.category_id,
        base_buy_price=float(p.base_buy_price),
        base_sell_price=float(p.base_sell_price),
        tax_rate=float(p.tax_rate),
        is_active=p.is_active,
        barcodes=[b.barcode for b in p.barcodes],
        stock=stock.get(p.id, 0.0),
        min_stock=mins.get(p.id, 0.0),
        unit_code=units.get(p.unit_id),
        expiry_date=p.expiry_date,
        is_weighted=bool(p.is_weighted),
        plu_code=p.plu_code,
        scale_sync=bool(p.scale_sync),
        sold_qty=sold.get(p.id, 0.0),
    )


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    archived: bool = False,
    include_archived: bool = False,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    # Standart — faqat FAOL mahsulotlar; archived=true — arxivlanganlar; include_archived=true —
    # hammasi (POS: 0-qoldiq/arxiv tovar ham skaner/qidiruvda topilib sotilishi uchun).
    query = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None),
    )
    if not include_archived:
        query = query.filter(Product.is_active.is_(not archived))
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if q:
        like = f"%{q}%"
        bc = db.query(ProductBarcode.product_id).filter(ProductBarcode.barcode.ilike(like)).subquery()
        query = query.filter(or_(
            Product.name.ilike(like),
            Product.article_code.ilike(like),
            Product.sku.ilike(like),
            Product.id.in_(db.query(bc.c.product_id)),
        ))
    products = query.order_by(Product.name).all()
    stock, mins, units = _stock_map(db), _min_map(db), _unit_map(db)
    sold = _sold_map(db, emp.company_id)
    return [_to_out(p, stock, mins, units, sold) for p in products]


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    cats = (
        db.query(Category)
        .filter(Category.company_id == emp.company_id, Category.deleted_at.is_(None))
        .order_by(Category.sort_order, Category.name)
        .all()
    )
    return cats


@router.post("/products/bulk", response_model=list[ProductOut])
def bulk_create(
    data: ProductBulkCreate,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    unit_map = {u.code: u.id for u in db.query(Unit).all()}
    branch = None
    from app.models.org import Branch

    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    now = datetime.now(timezone.utc)
    created = []
    seen_plu: set[str] = set()
    seen_art: set[str] = set()
    seq = db.query(Product).filter(Product.company_id == emp.company_id).count()
    for row in data.items:
        if not row.name.strip():
            continue
        plu = (row.plu_code or "").strip() or None
        if plu:
            if plu in seen_plu or db.query(Product).filter(Product.company_id == emp.company_id, Product.plu_code == plu, Product.deleted_at.is_(None)).first():
                raise HTTPException(400, f"PLU kodi band: {plu}")
            seen_plu.add(plu)
        seq += 1
        art = row.article_code or f"4-700000-160{200 + seq:03d}"
        if art in seen_art or db.query(Product).filter(Product.company_id == emp.company_id, Product.article_code == art).first():
            raise HTTPException(400, f"Artikul band: {art}")
        seen_art.add(art)
        if row.unit_code and row.unit_code not in unit_map:
            raise HTTPException(400, "Noto'g'ri o'lchov birligi")
        p = Product(
            company_id=emp.company_id,
            article_code=art,
            sku=row.sku or str(10025 + seq),
            name=row.name.strip(),
            category_id=row.category_id,
            unit_id=unit_map.get(row.unit_code, next(iter(unit_map.values()))),
            base_buy_price=row.buy_price,
            base_sell_price=row.sell_price,
            expiry_date=row.expiry_date,
            is_weighted=row.is_weighted,
            plu_code=plu,
            scale_sync=row.scale_sync,
            created_by=emp.id,   # kim qo'shdi
        )
        db.add(p)
        db.flush()
        if row.barcode:
            dup = db.query(ProductBarcode).filter(ProductBarcode.barcode == row.barcode).first()
            if dup:
                raise HTTPException(400, f"Barcode allaqachon mavjud: {row.barcode}")
            db.add(ProductBarcode(product_id=p.id, barcode=row.barcode))
        if branch:
            db.add(
                Inventory(
                    product_id=p.id,
                    branch_id=branch.id,
                    qty=row.stock,
                    min_qty=row.min_qty,
                    updated_at=now,
                )
            )
        audit_log(db, emp.id, "create", "product", p.id, after={"name": p.name, "article": art})
        created.append(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "PLU kodi band")
    stock, mins, units = _stock_map(db), _min_map(db), _unit_map(db)
    return [_to_out(p, stock, mins, units) for p in created]


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    category_id: str | None = None   # "" — kategoriyani bo'shatish
    buy_price: float | None = Field(default=None, ge=0)
    sell_price: float | None = Field(default=None, ge=0)
    min_qty: float | None = Field(default=None, ge=0)
    expiry_date: str | None = None
    is_active: bool | None = None
    is_weighted: bool | None = None
    plu_code: str | None = None
    scale_sync: bool | None = None
    unit_code: str | None = None


@router.get("/products/{product_id}")
def product_detail(
    product_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    p = db.get(Product, product_id)
    if not p or p.company_id != emp.company_id:
        raise HTTPException(404, "Mahsulot topilmadi")
    creator = None
    if p.created_by:
        creator = db.query(Employee.full_name).filter(Employee.id == p.created_by).scalar()

    # Zaxira: joriy qoldiq + minimal qoldiq
    stock = db.query(func.coalesce(func.sum(Inventory.qty), 0)).filter(Inventory.product_id == p.id).scalar()
    min_stock = db.query(func.coalesce(func.max(Inventory.min_qty), 0)).filter(Inventory.product_id == p.id).scalar()

    # Bu oy kirim / chiqim (StockMovement ledger)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    moves = db.query(StockMovement.type, func.coalesce(func.sum(func.abs(StockMovement.qty)), 0)).filter(
        StockMovement.product_id == p.id, StockMovement.created_at >= month_start
    ).group_by(StockMovement.type).all()
    IN = {MovementType.purchase_in, MovementType.return_in, MovementType.transfer_in}
    OUT = {MovementType.sale_out, MovementType.writeoff, MovementType.transfer_out}
    month_in = sum(float(v) for t, v in moves if t in IN)
    month_out = sum(float(v) for t, v in moves if t in OUT)

    buy, sell = float(p.base_buy_price), float(p.base_sell_price)
    return {
        "id": str(p.id), "article_code": p.article_code, "sku": p.sku, "name": p.name,
        "category_id": str(p.category_id) if p.category_id else None,
        "base_buy_price": buy, "base_sell_price": sell,
        "profit_unit": sell - buy,
        "stock": float(stock or 0), "min_stock": float(min_stock or 0),
        "expiry_date": p.expiry_date,
        "month_in": month_in, "month_out": month_out,
        "unit_code": _unit_map(db).get(p.unit_id),
        "is_active": p.is_active,
        "is_weighted": bool(p.is_weighted), "plu_code": p.plu_code, "scale_sync": bool(p.scale_sync),
        "created_by_name": creator or "—",
        "created_at": p.created_at,
        "barcodes": [b.barcode for b in p.barcodes],
    }


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    p = db.get(Product, product_id)
    if not p or p.company_id != emp.company_id or p.deleted_at is not None:
        raise HTTPException(404, "Mahsulot topilmadi")
    if data.name is not None:
        p.name = data.name
    if data.sku is not None:
        p.sku = data.sku
    if data.category_id is not None:
        try:
            p.category_id = uuid.UUID(data.category_id) if data.category_id else None
        except ValueError:
            raise HTTPException(422, "category_id UUID formatda bo'lishi kerak")
    if data.buy_price is not None:
        p.base_buy_price = data.buy_price
    if data.sell_price is not None:
        p.base_sell_price = data.sell_price
    if data.expiry_date is not None:
        from datetime import date as _date
        try:
            p.expiry_date = _date.fromisoformat(data.expiry_date) if data.expiry_date else None
        except ValueError:
            raise HTTPException(422, "expiry_date ISO formatda bo'lishi kerak (YYYY-MM-DD)")
    if data.is_active is not None:
        p.is_active = data.is_active
    if data.min_qty is not None:
        inv = db.query(Inventory).filter(Inventory.product_id == p.id).first()
        if inv:
            inv.min_qty = data.min_qty
    if data.is_weighted is not None:
        p.is_weighted = data.is_weighted
    if data.unit_code is not None:
        um = {u.code: u.id for u in db.query(Unit).all()}
        if data.unit_code not in um:
            raise HTTPException(422, "Noto'g'ri o'lchov birligi")
        p.unit_id = um[data.unit_code]
    if data.scale_sync is not None:
        p.scale_sync = data.scale_sync
    if data.plu_code is not None:
        plu = data.plu_code.strip() or None
        if plu:
            dup = db.query(Product).filter(Product.company_id == emp.company_id, Product.plu_code == plu, Product.id != p.id, Product.deleted_at.is_(None)).first()
            if dup:
                raise HTTPException(400, f"PLU kodi band: {plu} ({dup.name})")
        p.plu_code = plu
    audit_log(db, emp.id, "update", "product", p.id, after=data.model_dump(exclude_none=True))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "PLU kodi band")
    db.refresh(p)
    return _to_out(p, _stock_map(db), _min_map(db), _unit_map(db))


@router.delete("/products/{product_id}")
def delete_product(
    product_id: uuid.UUID,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    p = db.get(Product, product_id)
    if not p or p.company_id != emp.company_id:
        raise HTTPException(404, "Mahsulot topilmadi")
    p.deleted_at = datetime.now(timezone.utc)   # soft-delete (ma'lumot yo'qolmaydi)
    p.is_active = False
    db.query(ProductBarcode).filter(ProductBarcode.product_id == p.id).delete()  # barcode qayta ishlatilishi mumkin bo'lsin (PLU kabi)
    audit_log(db, emp.id, "delete", "product", p.id, before={"name": p.name})
    db.commit()
    return {"ok": True}


# ── Kategoriya CRUD ──────────────────────────────────────────────────────
class CategoryIn(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


@router.post("/categories", response_model=CategoryOut)
def create_category(
    data: CategoryIn,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    n = db.query(Category).filter(Category.company_id == emp.company_id).count()
    c = Category(company_id=emp.company_id, name=data.name, parent_id=data.parent_id, sort_order=n)
    db.add(c)
    db.flush()
    audit_log(db, emp.id, "create", "category", c.id, after={"name": c.name})
    db.commit()
    db.refresh(c)
    return c


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    data: CategoryIn,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Category, category_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Kategoriya topilmadi")
    c.name = data.name
    db.commit()
    db.refresh(c)
    return c


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: uuid.UUID,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    c = db.get(Category, category_id)
    if not c or c.company_id != emp.company_id:
        raise HTTPException(404, "Kategoriya topilmadi")
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


# ── Import (Excel/CSV/1C) ────────────────────────────────────────────────
class ImportRowIn(BaseModel):
    name: str
    article: str | None = None
    category: str | None = None
    buy: float = Field(default=0, allow_inf_nan=False)
    sell: float = Field(default=0, allow_inf_nan=False)
    stock: float = Field(default=0, allow_inf_nan=False)
    barcode: str | None = None


class ImportBody(BaseModel):
    rows: list[ImportRowIn]


def _classify(rows: list[ImportRowIn], existing_names: set[str]):
    new = existing = error = 0
    sample = []
    for r in rows:
        if not r.name.strip() or r.sell <= 0:
            st = "error"; error += 1
        elif r.name.strip().lower() in existing_names:
            st = "existing"; existing += 1
        else:
            st = "new"; new += 1
        if len(sample) < 6:
            sample.append({"name": r.name or "(bo'sh)", "article": r.article or "avto", "category": r.category or "—", "status": st})
    return new, existing, error, sample


@router.post("/products/import/preview")
def import_preview(
    body: ImportBody,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    existing = {p.name.strip().lower() for p in db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)).all()}
    new, exist, error, sample = _classify(body.rows, existing)
    return {"total": len(body.rows), "new": new, "existing": exist, "error": error, "sample": sample}


@router.post("/products/import/commit")
def import_commit(
    body: ImportBody,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    from app.models.org import Branch

    unit_id = {u.code: u.id for u in db.query(Unit).all()}
    default_unit = next(iter(unit_id.values()))
    cat_id = {c.name.lower(): c.id for c in db.query(Category).filter(
        Category.company_id == emp.company_id, Category.deleted_at.is_(None)).all()}
    existing = {p.name.strip().lower() for p in db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)).all()}
    branch = db.query(Branch).filter(Branch.company_id == emp.company_id).first()
    now = datetime.now(timezone.utc)
    seq = db.query(Product).filter(Product.company_id == emp.company_id).count()
    imported = 0
    for r in body.rows:
        key = r.name.strip().lower()
        if not r.name.strip() or r.sell <= 0 or key in existing:
            continue
        seq += 1
        p = Product(
            company_id=emp.company_id,
            article_code=(r.article or f"4-700000-160{200 + seq:03d}"),
            sku=str(10025 + seq),
            name=r.name.strip(),
            category_id=cat_id.get((r.category or "").lower()),
            unit_id=default_unit,
            base_buy_price=r.buy, base_sell_price=r.sell, tax_rate=12,
            created_by=emp.id,
        )
        db.add(p)
        db.flush()
        if r.barcode:
            db.add(ProductBarcode(product_id=p.id, barcode=r.barcode))
        if branch:
            db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=r.stock, min_qty=0, updated_at=now))
        audit_log(db, emp.id, "create", "product", p.id, after={"name": p.name, "source": "import"})
        existing.add(key)
        imported += 1
    db.commit()
    return {"imported": imported}


# ── Mavjud mahsulotlarga shtrix-kod qo'shish (id bo'yicha, ko'p barkod) ────────
class BarcodeRowIn(BaseModel):
    product_id: uuid.UUID
    barcode: str


class BarcodeImportBody(BaseModel):
    rows: list[BarcodeRowIn] = Field(max_length=20000)


@router.post("/products/barcodes/import")
def import_barcodes(
    body: BarcodeImportBody,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """Mavjud mahsulotlarga (product_id bo'yicha) shtrix-kod qo'shadi. Idempotent:
    band (global unique) yoki takror barkod — jimgina o'tkaziladi. Boshqa tenant mahsuloti rad etiladi."""
    own = {pid for (pid,) in db.query(Product.id).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)).all()}
    existing = {b for (b,) in db.query(ProductBarcode.barcode).all()}
    added = skipped = 0
    seen: set[str] = set()
    for r in body.rows:
        bc = (r.barcode or "").strip()
        if not bc or r.product_id not in own or bc in existing or bc in seen:
            skipped += 1
            continue
        db.add(ProductBarcode(product_id=r.product_id, barcode=bc, is_primary=False))
        seen.add(bc)
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


@router.post("/products/archive-empty")
def archive_empty(emp: Employee = Depends(require("mahsulotlar.edit")), db: Session = Depends(get_db)):
    """Qoldig'i <= 0 bo'lgan FAOL mahsulotlarni arxivga (is_active=False) o'tkazadi. Qaytariladi."""
    stock_sub = (
        db.query(Inventory.product_id, func.coalesce(func.sum(Inventory.qty), 0).label("q"))
        .group_by(Inventory.product_id).subquery()
    )
    prods = (
        db.query(Product)
        .outerjoin(stock_sub, stock_sub.c.product_id == Product.id)
        .filter(
            Product.company_id == emp.company_id,
            Product.deleted_at.is_(None),
            Product.is_active.is_(True),
            func.coalesce(stock_sub.c.q, 0) <= 0,
        )
        .all()
    )
    for p in prods:
        p.is_active = False
    db.commit()
    return {"archived": len(prods)}


# ── Bulk kategoriyalash (AI avto-kategoriya natijasini qo'llash) ────────────
class CategorizeRowIn(BaseModel):
    product_id: uuid.UUID
    category_id: uuid.UUID


class CategorizeBody(BaseModel):
    rows: list[CategorizeRowIn] = Field(max_length=20000)


@router.post("/products/categorize")
def categorize_bulk(
    body: CategorizeBody,
    emp: Employee = Depends(require("mahsulotlar.edit")),
    db: Session = Depends(get_db),
):
    """Mahsulotlarga kategoriya biriktiradi (bulk). Faqat o'z kompaniyasining mahsulot/kategoriyasi."""
    own_cats = {c.id for c in db.query(Category).filter(
        Category.company_id == emp.company_id, Category.deleted_at.is_(None)).all()}
    own_prods = {pid for (pid,) in db.query(Product.id).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)).all()}
    updated = skipped = 0
    by_prod = {}
    for r in body.rows:
        if r.product_id in own_prods and r.category_id in own_cats:
            by_prod[r.product_id] = r.category_id
        else:
            skipped += 1
    for pid, cid in by_prod.items():
        db.query(Product).filter(Product.id == pid).update({"category_id": cid})
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


@router.get("/products/by-barcode/{code}", response_model=ProductOut | None)
def product_by_barcode(
    code: str,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Shtrix-kod bo'yicha aniq mahsulot (mobil qo'lda kirim skaneri uchun).
    Topilmasa null — chaqiruvchi 'yangi mahsulot' rejimiga o'tadi va kodni saqlaydi."""
    bc = "".join(ch for ch in code if ch.isdigit())
    if not bc:
        return None
    row = (
        db.query(Product)
        .join(ProductBarcode, ProductBarcode.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                ProductBarcode.barcode == bc)
        .first()
    )
    if not row:
        return None
    stock, mins, units = _stock_map(db), _min_map(db), _unit_map(db)
    return _to_out(row, stock, mins, units)
