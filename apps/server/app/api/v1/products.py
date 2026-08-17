import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.inventory import Inventory
from app.schemas.catalog import CategoryOut, ProductBulkCreate, ProductOut
from app.services.audit import log as audit_log

router = APIRouter(tags=["catalog"])


def _stock_map(db: Session) -> dict:
    rows = db.query(Inventory.product_id, func.sum(Inventory.qty)).group_by(Inventory.product_id).all()
    return {pid: float(q or 0) for pid, q in rows}


def _to_out(p: Product, stock: dict) -> ProductOut:
    return ProductOut(
        id=p.id,
        article_code=p.article_code,
        name=p.name,
        category_id=p.category_id,
        base_buy_price=float(p.base_buy_price),
        base_sell_price=float(p.base_sell_price),
        tax_rate=float(p.tax_rate),
        is_active=p.is_active,
        barcodes=[b.barcode for b in p.barcodes],
        stock=stock.get(p.id, 0.0),
    )


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    query = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)
    )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.article_code.ilike(like)))
    products = query.order_by(Product.name).all()
    stock = _stock_map(db)
    return [_to_out(p, stock) for p in products]


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
    seq = db.query(Product).filter(Product.company_id == emp.company_id).count()
    for row in data.items:
        if not row.name.strip():
            continue
        seq += 1
        art = row.article_code or f"4-700000-160{200 + seq:03d}"
        p = Product(
            company_id=emp.company_id,
            article_code=art,
            name=row.name.strip(),
            category_id=row.category_id,
            unit_id=unit_map.get(row.unit_code, next(iter(unit_map.values()))),
            base_buy_price=row.buy_price,
            base_sell_price=row.sell_price,
            created_by=emp.id,   # kim qo'shdi
        )
        db.add(p)
        db.flush()
        if row.barcode:
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
    db.commit()
    stock = _stock_map(db)
    return [_to_out(p, stock) for p in created]


class ProductUpdate(BaseModel):
    name: str | None = None
    category_id: uuid.UUID | None = None
    buy_price: float | None = None
    sell_price: float | None = None
    is_active: bool | None = None


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
    return {
        "id": str(p.id), "article_code": p.article_code, "name": p.name,
        "category_id": str(p.category_id) if p.category_id else None,
        "base_buy_price": float(p.base_buy_price), "base_sell_price": float(p.base_sell_price),
        "is_active": p.is_active,
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
    if data.category_id is not None:
        p.category_id = data.category_id
    if data.buy_price is not None:
        p.base_buy_price = data.buy_price
    if data.sell_price is not None:
        p.base_sell_price = data.sell_price
    if data.is_active is not None:
        p.is_active = data.is_active
    audit_log(db, emp.id, "update", "product", p.id, after=data.model_dump(exclude_none=True))
    db.commit()
    db.refresh(p)
    return _to_out(p, _stock_map(db))


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
    buy: float = 0
    sell: float = 0
    stock: float = 0
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
