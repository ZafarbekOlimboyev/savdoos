import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.core.validate import clean_name
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Category, Product, ProductBarcode, Unit
from app.models.inventory import Inventory, StockMovement
from app.models.enums import MovementType
from app.schemas.catalog import CategoryOut, ProductBulkCreate, ProductOut
from app.services.audit import log as audit_log

router = APIRouter(tags=["catalog"])


# ── Kiritma validatsiyasi (ownership + format) ───────────────────────────
def _norm_barcode(raw: str | None) -> str | None:
    """Shtrix-kodni faqat raqamlarga keltiradi (skaner o'qishi bilan bir xil,
    ~product_by_barcode'ga mos) va mantiqiy uzunlikni (6-14) tekshiradi.
    Noto'g'ri/bo'sh -> None."""
    bc = "".join(ch for ch in (raw or "") if ch.isdigit())
    return bc if 6 <= len(bc) <= 14 else None


def _valid_plu(plu: str) -> bool:
    """EAN-13 PLU: faqat raqam, 1-5 xona."""
    return plu.isdigit() and 1 <= len(plu) <= 5


def _require_own_category(db: Session, cid: uuid.UUID, company_id) -> None:
    """category_id o'z kompaniyasiga tegishli va o'chirilmagan bo'lishi shart."""
    c = db.get(Category, cid)
    if not c or c.company_id != company_id or c.deleted_at is not None:
        raise HTTPException(400, "Kategoriya topilmadi")


def _require_own_parent(db: Session, parent_id, company_id) -> None:
    """Ota-kategoriya (parent_id) — o'z kompaniyasidan va o'chirilmagan; None ixtiyoriy."""
    if parent_id is None:
        return
    c = db.get(Category, parent_id)
    if not c or c.company_id != company_id or c.deleted_at is not None:
        raise HTTPException(400, "Ota-kategoriya topilmadi")


def _reject_dup_category(db: Session, name: str, company_id, exclude_id=None) -> None:
    """Bir kompaniya ichida bir xil nomli (registrga bog'liqsiz) kategoriya bo'lmasin."""
    q = db.query(Category).filter(
        Category.company_id == company_id,
        Category.deleted_at.is_(None),
        func.lower(Category.name) == name.lower(),
    )
    if exclude_id is not None:
        q = q.filter(Category.id != exclude_id)
    if q.first():
        raise HTTPException(409, "Bu kategoriya nomi allaqachon mavjud")


def _stock_map(db: Session, company_id, branches=None) -> dict:
    # FAQAT shu kompaniya inventarizatsiyasi (ilgari BARCHA tenant qoldig'ini yuklardi — perf).
    # branches (set) berilса — faqat o'sha filiallar qoldig'i (filialга bog'langan xodим boshqa
    # filial qoldig'ini ko'rmasin).
    q = (db.query(Inventory.product_id, func.sum(Inventory.qty))
         .join(Product, Product.id == Inventory.product_id)
         .filter(Product.company_id == company_id))
    if branches is not None:
        q = q.filter(Inventory.branch_id.in_(branches))
    return {pid: float(qq or 0) for pid, qq in q.group_by(Inventory.product_id).all()}


def _min_map(db: Session, company_id, branches=None) -> dict:
    q = (db.query(Inventory.product_id, func.max(Inventory.min_qty))
         .join(Product, Product.id == Inventory.product_id)
         .filter(Product.company_id == company_id))
    if branches is not None:
        q = q.filter(Inventory.branch_id.in_(branches))
    return {pid: float(m or 0) for pid, m in q.group_by(Inventory.product_id).all()}


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
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим — faqat o'z filial(lar)i qoldig'i
    stock = _stock_map(db, emp.company_id, _vb)
    mins = _min_map(db, emp.company_id, _vb)
    units = _unit_map(db)
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
    from app.core.deps import actor_branch
    from app.models.org import Branch
    # Boshlang'ich qoldiq xodим filialiga (ko'p-filialда birinchi filialga emas — sotuv bilan izchil).
    branch = (actor_branch(emp, db)
              or db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    now = datetime.now(timezone.utc)
    created = []
    seen_plu: set[str] = set()
    seen_art: set[str] = set()
    seen_bc: set[str] = set()
    own_cats = {c.id for c in db.query(Category).filter(
        Category.company_id == emp.company_id, Category.deleted_at.is_(None)).all()}
    seq = db.query(Product).filter(Product.company_id == emp.company_id).count()
    for row in data.items:
        if not row.name.strip():
            continue
        # category_id — faqat o'z kompaniyasidan (None ruxsat: kategoriyasiz)
        if row.category_id is not None and row.category_id not in own_cats:
            raise HTTPException(400, "Kategoriya topilmadi")
        plu = (row.plu_code or "").strip() or None
        if plu:
            if not _valid_plu(plu):
                raise HTTPException(400, "PLU kodi 1-5 raqam bo'lishi kerak")
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
            bc = _norm_barcode(row.barcode)
            if not bc:
                raise HTTPException(400, f"Shtrix-kod noto'g'ri (6-14 raqam): {row.barcode}")
            if bc in seen_bc or db.query(ProductBarcode).filter(ProductBarcode.barcode == bc).first():
                raise HTTPException(400, f"Barcode allaqachon mavjud: {bc}")
            seen_bc.add(bc)
            db.add(ProductBarcode(product_id=p.id, barcode=bc))
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
    stock, mins, units = _stock_map(db, emp.company_id), _min_map(db, emp.company_id), _unit_map(db)
    return [_to_out(p, stock, mins, units) for p in created]


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    category_id: str | None = None   # "" — kategoriyani bo'shatish
    # le=1e9 — ProductCreate bilan izchil VA Numeric(14,2) ustuniga sig'adi (1e12 overflow berardi).
    buy_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    min_qty: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    expiry_date: str | None = None
    is_active: bool | None = None
    is_weighted: bool | None = None
    plu_code: str | None = None
    scale_sync: bool | None = None
    unit_code: str | None = None


@router.get("/products/guess-category")
def guess_category(
    name: str,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Yangi mahsulot nomiga qarab kategoriya TAXMINI — do'konning O'Z katalogidan
    eng o'xshash nomli mahsulot topilib, uning kategoriyasi qaytariladi.
    (AI o'rniga har do'konga moslashuvchan evristika: 'Coca-Cola 1.5L' -> mavjud
    'Coca-Cola 0.5L' -> Ichimliklar.) Topilmasa null.
    DIQQAT: /products/{product_id} dan OLDIN turishi shart."""
    q = (name or "").strip().lower()
    words = {w for w in q.replace("-", " ").split() if len(w) >= 3}
    if not words:
        return {"category_id": None, "category_name": None}
    rows = (
        db.query(Product.name, Product.category_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                Product.category_id.isnot(None))
        .all()
    )
    best_id, best_score = None, 0
    for pname, cid in rows:
        pw = {w for w in pname.lower().replace("-", " ").split() if len(w) >= 3}
        score = len(words & pw)
        if score > best_score:
            best_id, best_score = cid, score
    if best_id is None:
        return {"category_id": None, "category_name": None}
    from app.models.catalog import Category as _Cat
    c = db.get(_Cat, best_id)
    return {"category_id": str(best_id), "category_name": c.name if c else None}


@router.get("/products/catalog-version")
def catalog_version(
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Katalog 'versiyasi' — juda yengil (og'ir ma'lumot yo'q). Mobil ilova buni
    saqlab qo'yadi; keyingi safar shu bir xil bo'lsa telefon xotirasidagi nusxadan
    ishlaydi (qayta yuklamaydi). Mahsulot qo'shilsa/o'zgarsa/arxivlansa yoki barcode
    qo'shilsa — qiymat o'zgaradi va ilova bir marta yangilaydi.
    DIQQAT: bu marshrut /products/{product_id} dan OLDIN turishi shart (aks holda
    'catalog-version' UUID sifatida o'qilib, xato beradi)."""
    cnt, last = (
        db.query(func.count(Product.id), func.max(Product.updated_at))
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None))
        .one()
    )
    bc_cnt = (
        db.query(func.count(ProductBarcode.id))
        .join(Product, Product.id == ProductBarcode.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None))
        .scalar()
    )
    rev = f"{cnt or 0}:{int((last.timestamp() if last else 0))}:{bc_cnt or 0}"
    return {"rev": rev, "count": cnt or 0}


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

    # Zaxira: joriy qoldiq + minimal qoldiq — filialга bog'langan xodим faqat o'z filial(lar)ini
    # ko'radi (list_products/overview bilan izchil; ilgari BARCHA filial qoldig'ini ko'rsatарди).
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)
    _bf = (Inventory.branch_id.in_(_vb),) if _vb is not None else ()
    stock = db.query(func.coalesce(func.sum(Inventory.qty), 0)).filter(Inventory.product_id == p.id, *_bf).scalar()
    min_stock = db.query(func.coalesce(func.max(Inventory.min_qty), 0)).filter(Inventory.product_id == p.id, *_bf).scalar()

    # Bu oy kirim / chiqim (StockMovement ledger)
    _mbf = (StockMovement.branch_id.in_(_vb),) if _vb is not None else ()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    moves = db.query(StockMovement.type, func.coalesce(func.sum(func.abs(StockMovement.qty)), 0)).filter(
        StockMovement.product_id == p.id, StockMovement.created_at >= month_start, *_mbf
    ).group_by(StockMovement.type).all()
    IN = {MovementType.purchase_in, MovementType.return_in, MovementType.transfer_in}
    OUT = {MovementType.sale_out, MovementType.writeoff, MovementType.transfer_out}
    month_in = sum(float(v) for t, v in moves if t in IN)
    month_out = sum(float(v) for t, v in moves if t in OUT)

    buy, sell = float(p.base_buy_price), float(p.base_sell_price)

    # Sotuv statistikasi (SaleItem ledger) — 7 va 30 kunlik: soni, tushum, foyda
    from datetime import timedelta as _td
    from app.models.sales import Sale as _Sale, SaleItem as _SI
    now = datetime.now(timezone.utc)

    def _sales_since(days):
        since = now - _td(days=days)
        qty, rev, cost = (
            db.query(
                func.coalesce(func.sum(_SI.qty), 0),
                func.coalesce(func.sum(_SI.qty * _SI.unit_price), 0),
                func.coalesce(func.sum(_SI.qty * _SI.unit_cost), 0),
            )
            .join(_Sale, _Sale.id == _SI.sale_id)
            .filter(_Sale.company_id == emp.company_id, _SI.product_id == p.id,
                    _Sale.sold_at >= since)
            .one()
        )
        return {"qty": float(qty or 0), "revenue": float(rev or 0),
                "profit": float((rev or 0) - (cost or 0))}

    last_sold = (
        db.query(func.max(_Sale.sold_at))
        .join(_SI, _SI.sale_id == _Sale.id)
        .filter(_Sale.company_id == emp.company_id, _SI.product_id == p.id)
        .scalar()
    )

    return {
        "id": str(p.id), "article_code": p.article_code, "sku": p.sku, "name": p.name,
        "category_id": str(p.category_id) if p.category_id else None,
        "base_buy_price": buy, "base_sell_price": sell,
        "profit_unit": sell - buy,
        "margin_pct": round((sell - buy) / sell * 100, 1) if sell > 0 else 0,
        "stock": float(stock or 0), "min_stock": float(min_stock or 0),
        "expiry_date": p.expiry_date,
        "sales_7d": _sales_since(7), "sales_30d": _sales_since(30),
        "last_sold_at": last_sold,
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
        p.name = clean_name(data.name, "Mahsulot nomi")
    if data.sku is not None:
        p.sku = data.sku
    if data.category_id is not None:
        if data.category_id:
            try:
                cid = uuid.UUID(data.category_id)
            except ValueError:
                raise HTTPException(422, "category_id UUID formatda bo'lishi kerak")
            _require_own_category(db, cid, emp.company_id)  # begona/o'chirilgan kategoriya rad
            p.category_id = cid
        else:
            p.category_id = None   # "" — kategoriyani bo'shatish
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
        # Kam-qoldiq chegарasini xodим filialidaги qatorга yozamiz (ilgari IXTIYORIY filial
        # qatoriга tushardi — ko'p-filialда noto'g'ri filial min_qty'si o'zgarardi).
        from app.core.deps import actor_branch
        _ab = actor_branch(emp, db)
        _q = db.query(Inventory).filter(Inventory.product_id == p.id)
        if _ab:
            _q = _q.filter(Inventory.branch_id == _ab.id)
        inv = _q.first()
        if inv:
            inv.min_qty = data.min_qty
        elif _ab:
            db.add(Inventory(product_id=p.id, branch_id=_ab.id, qty=0,
                             min_qty=data.min_qty, updated_at=datetime.now(timezone.utc)))
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
            if not _valid_plu(plu):
                raise HTTPException(400, "PLU kodi 1-5 raqam bo'lishi kerak")
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
    return _to_out(p, _stock_map(db, emp.company_id), _min_map(db, emp.company_id), _unit_map(db))


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
    name = clean_name(data.name, "Kategoriya nomi")
    _require_own_parent(db, data.parent_id, emp.company_id)   # begona ota-kategoriya rad
    _reject_dup_category(db, name, emp.company_id)            # takror nom rad (409)
    n = db.query(Category).filter(Category.company_id == emp.company_id).count()
    c = Category(company_id=emp.company_id, name=name, parent_id=data.parent_id, sort_order=n)
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
    name = clean_name(data.name, "Kategoriya nomi")
    _reject_dup_category(db, name, emp.company_id, exclude_id=c.id)   # o'zidan boshqa takror rad
    c.name = name
    if data.parent_id is not None:
        _require_own_parent(db, data.parent_id, emp.company_id)       # begona ota-kategoriya rad
        c.parent_id = data.parent_id
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
    # ge=0/le=1e9 — ProductCreate bilan izchil: manfiy tannarx (COGS/foyda buzardi) yoki
    # manfiy/absurd qoldiq (StockMovement'siz Inventory'ni buzardi) yozilmasin.
    buy: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    stock: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    barcode: str | None = None


class ImportBody(BaseModel):
    rows: list[ImportRowIn] = Field(max_length=20000)  # massiv-DoS oldini olish


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
    existing_bc = {b for (b,) in db.query(ProductBarcode.barcode).all()}  # barcode global unique
    seen_bc: set[str] = set()
    # Artikul (company+article_code) QATTIQ noyob — takror artikul flush'да IntegrityError berib
    # BUTUN importni 500 qilardi. Band artikulли qatorни jimgina o'tkazamiz (o'chirilгани ham,
    # constraint qisman emas). seen_art — shu import ichидаги takrorlar.
    existing_art = {a for (a,) in db.query(Product.article_code).filter(
        Product.company_id == emp.company_id).all()}
    seen_art: set[str] = set()
    from app.core.deps import actor_branch
    branch = (actor_branch(emp, db)  # import qoldig'i xodим filialiga (ko'p-filialда izchil)
              or db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    now = datetime.now(timezone.utc)
    seq = db.query(Product).filter(Product.company_id == emp.company_id).count()
    imported = 0
    for r in body.rows:
        key = r.name.strip().lower()
        if not r.name.strip() or r.sell <= 0 or key in existing:
            continue
        seq += 1
        art = (r.article or "").strip() or f"4-700000-160{200 + seq:03d}"
        if art in existing_art or art in seen_art:
            continue  # artikul band — bu qatorни o'tkazamiz (butun import 500 bo'lmasin)
        seen_art.add(art)
        p = Product(
            company_id=emp.company_id,
            article_code=art,
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
            bc = _norm_barcode(r.barcode)   # digits-only + uzunlik 6-14
            if bc and bc not in existing_bc and bc not in seen_bc:   # band/takror — jimgina o'tkaziladi (500 emas)
                db.add(ProductBarcode(product_id=p.id, barcode=bc))
                seen_bc.add(bc)
        if branch:
            db.add(Inventory(product_id=p.id, branch_id=branch.id, qty=r.stock, min_qty=0, updated_at=now))
        audit_log(db, emp.id, "create", "product", p.id, after={"name": p.name, "source": "import"})
        existing.add(key)
        imported += 1
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:  # kutilmagan noyoblik to'qnashuvi — 500 emas, aniq 400
        db.rollback()
        raise HTTPException(400, "Import bekor qilindi — takroriy artikul/shtrix-kod")
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
        bc = _norm_barcode(r.barcode)   # digits-only + uzunlik 6-14 (skaner o'qishiga mos)
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
    stock, mins, units = _stock_map(db, emp.company_id), _min_map(db, emp.company_id), _unit_map(db)
    return _to_out(row, stock, mins, units)
