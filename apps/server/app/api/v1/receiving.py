"""Mobil "Tovar qabul qilish" — nakladnoy skani → AI o'qish → moslash → omborga kirim.

Xavfsizlik: AI natijasi FAQAT taklif; ombor faqat foydalanuvchi tasdig'idan keyin o'zgaradi.
Har qabul audit uchun saqlanadi (rasm + AI dastlabki + yakuniy tahrir)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierLedger
from app.models.receiving import Receiving
from app.services.receiving_ai import match_products, read_invoice

router = APIRouter(tags=["receiving"])

_DEFAULT_SUPPLIER = "Qabul (mobil)"


class ScanIn(BaseModel):
    image_b64: str = Field(max_length=15_000_000)   # ~11MB rasm shifti — cheksiz yuklashга qarshi
    media_type: str = Field(default="image/jpeg", max_length=60)


@router.post("/receiving/scan")
def scan(data: ScanIn, emp: Employee = Depends(require("xaridlar.edit")), db: Session = Depends(get_db)):
    """Rasmni AI bilan o'qib, mavjud mahsulotlar bilan moslashtiradi. OMBORNI O'ZGARTIRMAYDI.
    AI-vision xarajat qiladi va xaridlar oqimining bir qismi — 'xaridlar.edit' ruxsati kerak."""
    units = {u.id: u.code for u in db.query(Unit).all()}
    prods = (
        db.query(Product)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None))
        .all()
    )
    plist = [{"id": str(p.id), "name": p.name, "unit_code": units.get(p.unit_id, "dona"),
              "base_buy_price": float(p.base_buy_price)} for p in prods]
    names = [p["name"] for p in plist]
    rows, source = read_invoice(data.image_b64, data.media_type, names)
    if source.startswith("error:"):
        raise HTTPException(502, f"AI o'qishda xato: {source[6:]}")
    items = match_products(rows, plist)
    return {"source": source, "items": items, "ai_raw": rows}


class CommitItem(BaseModel):
    product_id: uuid.UUID | None = None       # mavjud mahsulot
    new_name: str | None = Field(default=None, max_length=200)  # yoki yangi mahsulot (bazada yo'q)
    new_sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    new_category_id: uuid.UUID | None = None  # yangi mahsulot uchun kategoriya (ixtiyoriy)
    new_barcode: str | None = Field(default=None, max_length=64)  # skanerlangan shtrix-kod (bazada yo'q bo'lsa mahsulotga biriktiriladi)
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    ai_name: str | None = None
    unit: str | None = None
    # Yangi mahsulot uchun qo'shimcha (mobil kirim — Manager formasi bilan paritet):
    new_plu: str | None = Field(default=None, max_length=10)       # tarozi PLU (kg mahsulot)
    new_is_weighted: bool | None = None                             # kg/tarozi mahsulotimi
    new_min_qty: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # min qoldiq


class CommitIn(BaseModel):
    items: list[CommitItem] = Field(max_length=1000)
    image_b64: str | None = Field(default=None, max_length=15_000_000)
    source: str = Field(default="ai", max_length=20)
    ai_raw: list = Field(default=[], max_length=2000)
    supplier_id: uuid.UUID | None = None
    payment: Literal["cash", "credit"] = "cash"   # qarzga olindi -> beruvchi balansi oshadi
    client_uuid: uuid.UUID | None = None


@router.post("/receiving/commit")
def commit(data: CommitIn, emp: Employee = Depends(require("xaridlar.edit")), db: Session = Depends(get_db)):
    # doc_no (KIR-...) count()+1 asosida beriladi — boshqa ta'minotchili ikki kirim/xarid AYNI PAYTDA
    # bir xil raqam olib UNIQUE(company_id, doc_no) buzardi (500). create_purchase kabi retry o'raymiz:
    # to'qnashuvda tranzaksiya bekor bo'lib, qayta urinishda count() yangi raqam beradi.
    # (client_uuid dedup ichki funksiyada "duplicate" qaytaradi — IntegrityError chiqarmaydi, retrysiz.)
    from sqlalchemy.exc import IntegrityError as _IEwrap
    from app.services.cash.errors import CashPostingError as _CPE
    _last: Exception | None = None
    for _try in range(3):
        try:
            return _commit_once(data, emp, db)
        except _IEwrap as e:
            db.rollback()
            _last = e
        except _CPE:
            # KONKURRENT DUBLIKAT IDEMPOTENTLIGI: naqd qabul endi OUT·PURCHASE_OUT post qiladi va
            # sufficiency tekshiradi. Bir xil client_uuid'li ikki konkurrent qabulда g'olib oqim
            # kassani kamaytirib commit qilса, YUTQAZGAN dublikat OUT-sufficiency'да CashPostingError
            # (INSUFFICIENT_CASH) olishi mumkin — commit-time client_uuid guard'gача yetmай. Bu XATO
            # EMAS: operatsiya g'olib orqali MUVAFFAQ bo'lган. client_uuid bilan Receiving mavjud bo'lса
            # idempotent dublikatni qaytaramiz; aks holда — HAQIQIY domain-error (yetarsiz naqd/arxiv
            # hisob/valyuta) -> qayta ko'taramiz.
            db.rollback()
            if data.client_uuid:
                ex = db.query(Receiving).filter(
                    Receiving.client_uuid == data.client_uuid,
                    Receiving.company_id == emp.company_id).first()
                if ex:
                    return {"ok": True, "receiving_id": str(ex.id), "duplicate": True}
            raise
    raise HTTPException(409, "Qabul hujjati band — qayta urinib ko'ring") from _last


def _commit_once(data: CommitIn, emp: Employee, db: Session):
    if data.client_uuid:
        ex = db.query(Receiving).filter(
            Receiving.client_uuid == data.client_uuid, Receiving.company_id == emp.company_id
        ).first()
        if ex:
            return {"ok": True, "receiving_id": str(ex.id), "duplicate": True}
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")

    from app.core.deps import actor_branch
    branch = (actor_branch(emp, db)  # kirim xodim filialiga (ko'p-filial: sotuv bilan izchil)
              or db.query(Branch).filter(
                  Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    # Yetkazib beruvchi — berilmasa "Qabul (mobil)" avto
    # QATOR QULFI: qarz-qabulda sup.balance RMW (quyida) bir vaqtdagi to'lov/kirim bilan yo'qolmasin
    # va SupplierLedger.balance_after haqiqiy balansga teng bo'lsin (create_purchase/edit_purchase/
    # pay_supplier bilan izchil — ilgari faqat receiving qulflamasdi).
    sup = None
    if data.supplier_id:
        sup = db.query(Supplier).filter(Supplier.id == data.supplier_id).with_for_update().first()
        # O'chirилган ta'minотchига qarз-qabul biriktирмаймиз — aks holда qarз yashirин qolарди
        # (create_purchase/pay_supplier ham deleted_at ni tekshiradi).
        if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
            raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if sup is None:
        sup = db.query(Supplier).filter(
            Supplier.company_id == emp.company_id, Supplier.name == _DEFAULT_SUPPLIER,
            Supplier.deleted_at.is_(None)).with_for_update().first()
        if sup is None:
            sup = Supplier(company_id=emp.company_id, name=_DEFAULT_SUPPLIER)
            db.add(sup)
            db.flush()

    all_units = db.query(Unit).all()
    units = {u.id: u.code for u in all_units}
    unit_by_code = {u.code: u.id for u in all_units}   # tanlangan birlik (kg/litr/...) uchun
    default_unit_id = all_units[0].id if all_units else None
    now = datetime.now(timezone.utc)
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    from app.core.validate import guard_amount
    guard_amount(total, "Hujjat jami summasi")  # Numeric(14,2) yig'indi overflow -> do'stona 400
    is_credit = data.payment == "credit"
    from app.api.v1.reports import _biz_date
    seq = db.query(Purchase).filter(Purchase.company_id == emp.company_id).count()
    pur = Purchase(
        doc_no=f"KIR-{1042 + seq + 1}", company_id=emp.company_id, branch_id=branch.id,
        supplier_id=sup.id, employee_id=emp.id, purchase_date=_biz_date(db, emp.company_id),
        status=PurchaseStatus.debt if is_credit else PurchaseStatus.received,
        subtotal=total, total=total, paid_amount=Decimal("0") if is_credit else total,
    )
    db.add(pur)
    db.flush()

    results = []
    final_items = []
    total_qty = Decimal("0")
    # QATOR QULFI (deadlock oldini olish): tegiladigan mavjud mahsulotlar Inventory qatorlarini
    # DASTAVVAL bir xil GLOBAL tartibda (product_id) qulflaymiz — boshqa BARCHA yozuvchilar (sotuv/
    # qaytarish/xarid/writeoff/transfer) shu tartibda qulflaydi, aks holda AB-BA deadlock (500).
    # MUHIM: new_name item quyidagi DEDUP (lower(name)) orqali MAVJUD mahsulotga bog'lanishi mumkin —
    # uni ham oldindan qulflaymiz, aks holda loop ichida item-tartibda qulflab deadlock bo'lardi.
    # Haqiqatan yangi (dedup topmaydigan) nomlar tranzaksiya-ichi yaratiladi -> deadlock bermaydi.
    _lock_pids = {i.product_id for i in data.items if i.product_id}
    _new_names = [i.new_name.strip() for i in data.items
                  if not i.product_id and i.new_name and i.new_name.strip()]
    if _new_names:
        _ex = db.query(Product.id).filter(
            Product.company_id == emp.company_id, Product.deleted_at.is_(None),
            func.lower(Product.name).in_([n.lower() for n in _new_names])).all()
        _lock_pids |= {r[0] for r in _ex}
    for _pid in sorted(_lock_pids, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for i in data.items:
        _is_new_prod = False   # shu itemda HAQIQATAN yangi mahsulot yaratildimi (mavjud/dedup emas)
        # Yangi mahsulot uchun kategoriya (berilsa — shu kompaniyaniki bo'lishi shart)
        cat_id = None
        if i.new_category_id:
            from app.models.catalog import Category as _Cat
            _c = db.get(_Cat, i.new_category_id)
            if _c and _c.company_id == emp.company_id and _c.deleted_at is None:
                cat_id = _c.id
        if i.product_id:
            prod = db.get(Product, i.product_id)
            if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
                raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        elif i.new_name and i.new_name.strip():
            nm = i.new_name.strip()
            # Dedup: shu nomli faol mahsulot bo'lsa — yangisini yaratmay, o'shanga kirim qilamiz
            existing = (
                db.query(Product)
                .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                        func.lower(Product.name) == nm.lower())
                .first()
            )
            if existing is not None:
                prod = existing
            else:
                # Bazada yo'q — yangi mahsulot (kelish narxi = unit_cost, sotish = new_sell yoki +20%)
                cost0 = Decimal(str(i.unit_cost))
                sell0 = Decimal(str(i.new_sell_price)) if i.new_sell_price is not None else (cost0 * Decimal("1.2"))
                pseq = db.query(Product).filter(Product.company_id == emp.company_id).count()
                # Birlik: kirimда tanlangani (i.unit — 'dona/kg/litr/upak') — ilgari e'tiborsiz edi
                _uid = unit_by_code.get((i.unit or "").strip().lower()) or default_unit_id
                # Tarozi (kg) mahsuloti: PLU noyob bo'lishi shart (kompaniya doirasida)
                _weighted = bool(i.new_is_weighted) or (i.unit or "").strip().lower() == "kg"
                from app.api.v1.products import _norm_plu as _nplu
                _plu = _nplu(i.new_plu)   # QA PC-013: kanonik shakl (yetakchi nolsiz), 1-5 raqam
                if _plu is not None:
                    _clash = db.query(Product).filter(
                        Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                        Product.plu_code == _plu).first()
                    if _clash:
                        raise HTTPException(409, f"PLU {_plu} band ({_clash.name}) — boshqa PLU kiriting: {nm}")
                prod = Product(company_id=emp.company_id, name=nm, category_id=cat_id,
                               article_code=f"R-{1000 + pseq + 1}", sku=str(20000 + pseq + 1),
                               unit_id=_uid, base_buy_price=cost0, base_sell_price=sell0,
                               tax_rate=Decimal("12"),
                               is_weighted=_weighted, plu_code=_plu)
                db.add(prod)
                db.flush()
                _is_new_prod = True
        else:
            raise HTTPException(400, "Mahsulot yoki yangi nom kerak")
        # Narxlar yangilanishi: kelish narxi (unit_cost>0) va sotish narxi (new_sell_price berilsa)
        # bazadagidan farq qilsa — mahsulot kartochkasida ham yangilanadi (foydalanuvchi so'rovi).
        if i.unit_cost and Decimal(str(i.unit_cost)) != Decimal(str(prod.base_buy_price)):
            prod.base_buy_price = Decimal(str(i.unit_cost))
        if i.new_sell_price is not None and Decimal(str(i.new_sell_price)) > 0 \
                and Decimal(str(i.new_sell_price)) != Decimal(str(prod.base_sell_price)):
            prod.base_sell_price = Decimal(str(i.new_sell_price))
        if cat_id and prod.category_id is None:
            prod.category_id = cat_id
        # Kirim kelgan mahsulot arxivda bo'lsa — avtomatik faolga qaytadi (qoldiq endi bor)
        if not prod.is_active:
            prod.is_active = True
        # Skanerlangan shtrix-kod bazada yo'q bo'lsa — shu mahsulotga biriktiramiz
        # (yangi mahsulotga ham, mavjudga ham; band bo'lsa jimgina o'tkazamiz)
        if i.new_barcode:
            from app.api.v1.products import _norm_barcode as _nbc
            bc = _nbc(i.new_barcode)  # 6-14 raqam (butun tizimда bir xil); noto'g'ri -> None
            # QA PC-003: bandlik endi KOMPANIYA doirasida tekshiriladi (global emas)
            if bc and not db.query(ProductBarcode).filter(
                    ProductBarcode.company_id == emp.company_id, ProductBarcode.barcode == bc).first():
                db.add(ProductBarcode(product_id=prod.id, company_id=emp.company_id, barcode=bc, is_primary=False))
        qty, cost = Decimal(str(i.qty)), Decimal(str(i.unit_cost))
        line_total = qty * cost
        # Numeric(14,2) sig'imidan oshsa Postgres "numeric field overflow" bilan qulaydi
        # (qty·cost 1e9·1e9=1e18 gacha bo'lishi mumkin) — do'st xabar bilan to'xtatamiz.
        if line_total > Decimal("999999999999.99"):
            raise HTTPException(400, f"'{prod.name}' qatori summasi juda katta (miqdor×narx {line_total:g}) — miqdor yoki narxni tekshiring")
        total_qty += qty
        db.add(PurchaseItem(purchase_id=pur.id, product_id=prod.id, qty=qty,
                            unit_cost=cost, line_total=line_total))
        # QATOR QULFI: qoldiq RMW bir vaqtдаги sotuv/kirim bilan STALE o'qib yo'qolмасин
        # (balance_after ham to'g'ri qatор qiymatини aks ettirsin).
        inv = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == branch.id).with_for_update().first()
        old_qty = float(inv.qty) if inv else 0.0
        if inv is None:
            inv = Inventory(product_id=prod.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        # Min qoldiq — FAQAT haqiqatan yangi yaratilgan mahsulotга (mavjud yoki dedup-mahsulotning
        # menejer sozlagan kam-qoldiq chegarasini kirim jarayonida jimgina almashtirmaslik uchun).
        if i.new_min_qty is not None and _is_new_prod:
            inv.min_qty = Decimal(str(i.new_min_qty))
        inv.qty = Decimal(str(inv.qty)) + qty
        inv.updated_at = now
        if inv.qty > Decimal(str(inv.min_qty or 0)):
            inv.low_alerted = False  # min ustiga chiqdi — keyingi tushishda yana ogohlantiriladi
        db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.purchase_in,
                            qty=qty, unit_cost=cost, balance_after=inv.qty, ref_type="receiving",
                            ref_id=pur.id, employee_id=emp.id, created_at=now))
        _uc = units.get(prod.unit_id, "dona")
        results.append({"product": prod.name, "old_qty": old_qty, "added": float(qty),
                        "new_qty": float(inv.qty), "unit": _uc})
        final_items.append({"product_id": str(prod.id), "name": prod.name, "qty": float(qty),
                            "unit_cost": float(cost), "ai_name": i.ai_name, "unit": i.unit or _uc})

    # Qarzga olindi — yetkazib beruvchi balansi oshadi (biz qarzmiz)
    if is_credit:
        sup.balance = Decimal(str(sup.balance or 0)) + total
        db.add(SupplierLedger(supplier_id=sup.id, type=CreditTxnType.charge, amount=total,
                              balance_after=sup.balance, ref_type="receiving", ref_id=pur.id, created_at=now))
    else:
        # Phase 2b — NAQD qabul (received) -> OUT·PURCHASE_OUT: create_purchase bilan IZCHIL; §07
        # off-ledger teshigini receiving tomonда HAM yopadi (ilgari receiving naqd xaridi kassani
        # jimgina kamaytirardi, ledgerда OUT yo'q edi -> keyingi qaytarish ham mumkin emasди).
        # source_type=PURCHASE, source_id=pur.id, leg_index=0 (asl xarid — PURCHASE_RETURN'дан farqli).
        # Summa = PERSISTED total (=paid_amount). Guarded/commit=False (SQLite/xaritalanmagan filialда
        # no-op) -> Purchase+ombor+ledger BIR tranzaksiyada (§05). Yetarsiz naqd/arxiv hisob/valyuta
        # -> CashPostingError -> butun qabul ROLLBACK.
        from app.services.cash import retrofit as _cr
        _cr.on_cash_purchase(db, emp, branch_id=branch.id, purchase_id=pur.id, cash_amount=total)

    rec = Receiving(
        company_id=emp.company_id, branch_id=branch.id, employee_id=emp.id, purchase_id=pur.id,
        source=data.source, image_b64=data.image_b64, ai_raw=data.ai_raw, final_items=final_items,
        total_types=len(final_items), total_qty=total_qty, committed_at=now, client_uuid=data.client_uuid,
    )
    db.add(rec)
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_receivings_client_uuid) ushlади:
        # butun tranzaksiya (ombor + xarid) bekor bo'ladi, birinchисининг natijasини qaytaramiz.
        db.rollback()
        if data.client_uuid:
            ex2 = db.query(Receiving).filter(
                Receiving.client_uuid == data.client_uuid, Receiving.company_id == emp.company_id).first()
            if ex2:
                return {"ok": True, "receiving_id": str(ex2.id), "duplicate": True}
        raise
    db.refresh(rec)
    return {"ok": True, "receiving_id": str(rec.id), "purchase_id": str(pur.id),
            "doc_no": pur.doc_no, "results": results, "payment": data.payment,
            "supplier": sup.name, "total_types": len(final_items), "total_qty": float(total_qty)}


@router.get("/receiving")
def history(limit: int = 50, emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим — faqat o'z filiali qabullari
    q = (
        db.query(Receiving)
        .filter(Receiving.company_id == emp.company_id, Receiving.committed_at.isnot(None))
    )
    if _vb is not None:
        q = q.filter(Receiving.branch_id.in_(_vb))
    rows = q.order_by(Receiving.committed_at.desc()).limit(max(1, min(limit, 200))).all()
    return [{
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
    } for r in rows]


@router.get("/receiving/{receiving_id}")
def detail(receiving_id: uuid.UUID, emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    r = db.get(Receiving, receiving_id)
    if not r or r.company_id != emp.company_id:
        raise HTTPException(404, "Qabul topilmadi")
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # boshqa filial qabulini ochib bo'lmaydi (IDOR)
    if _vb is not None and r.branch_id not in _vb:
        raise HTTPException(404, "Qabul topilmadi")
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    return {
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
        "items": r.final_items, "ai_raw": r.ai_raw, "image_b64": r.image_b64,
    }
