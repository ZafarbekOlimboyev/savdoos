import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import actor_branch, get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.catalog import Product, Unit
from app.models.purchasing import (
    Purchase,
    PurchaseItem,
    PurchaseReturn,
    Supplier,
    SupplierLedger,
    SupplierPayment,
)
from app.models.receiving import Receiving
from app.schemas.purchase import PurchaseCreate, PurchaseOut, SupplierOut

router = APIRouter(tags=["purchases"])


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    return (
        db.query(Supplier)
        .filter(Supplier.company_id == emp.company_id, Supplier.deleted_at.is_(None))
        .order_by(Supplier.name)
        .all()
    )


class SupplierIn(BaseModel):
    name: str
    phone: str | None = None


def _supplier_phone(db: Session, company_id, raw: str | None, exclude_id=None):
    """Ta'minotchi telefonini normallashtirib tekshiradi (format + do'kon ichida takror)."""
    from app.core.security import norm_phone
    from app.core.validate import require_phone
    phone = norm_phone(raw) or None
    require_phone(phone or "")
    if phone:
        q = db.query(Supplier).filter(
            Supplier.company_id == company_id, Supplier.phone == phone, Supplier.deleted_at.is_(None))
        if exclude_id is not None:
            q = q.filter(Supplier.id != exclude_id)
        if db.query(q.exists()).scalar():
            raise HTTPException(409, "Bu telefon do'konda allaqachon band")
    return phone


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(
    data: SupplierIn,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    from app.core.validate import clean_name
    name = clean_name(data.name, "Yetkazib beruvchi nomi")
    phone = _supplier_phone(db, emp.company_id, data.phone)
    s = Supplier(company_id=emp.company_id, name=name, phone=phone)
    db.add(s)
    db.flush()
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "supplier", s.id, after={"name": s.name})
    db.commit()
    db.refresh(s)
    return s


class SupplierEdit(BaseModel):
    name: str | None = None
    phone: str | None = None


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def edit_supplier(
    supplier_id: uuid.UUID,
    data: SupplierEdit,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    before = {"name": s.name, "phone": s.phone}
    if data.name is not None:
        from app.core.validate import clean_name
        s.name = clean_name(data.name, "Yetkazib beruvchi nomi")
    if data.phone is not None:
        s.phone = _supplier_phone(db, emp.company_id, data.phone, exclude_id=s.id)
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "supplier", s.id,
              before=before, after={"name": s.name, "phone": s.phone})
    db.commit()
    db.refresh(s)
    return s


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    # Balansi bor ta'minotchini o'chirib bo'lmaydi (delete_customer bilan izchil) — aks holда qarз
    # yetim qolиб, to'lash/ko'rish imkoni yo'qolарди (list/detail/pay hammasi deleted'ni yashiradi).
    if s.balance and Decimal(str(s.balance)) != 0:
        raise HTTPException(400, "Balansi bor yetkazib beruvchini o'chirib bo'lmaydi — avval qarzni yoping")
    from datetime import datetime, timezone
    s.deleted_at = datetime.now(timezone.utc)
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "delete", "supplier", s.id, before={"name": s.name})
    db.commit()
    return {"ok": True}


@router.get("/purchases")
def list_purchases(emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим — faqat o'z filiali xaridlari
    q = (
        db.query(Purchase, Supplier.name)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .filter(Purchase.company_id == emp.company_id, Purchase.deleted_at.is_(None))
    )
    if _vb is not None:
        q = q.filter(Purchase.branch_id.in_(_vb))
    rows = q.order_by(Purchase.purchase_date.desc(), Purchase.doc_no.desc()).all()
    return [
        {
            "id": str(p.id),
            "doc_no": p.doc_no,
            "supplier": name,
            "date": p.purchase_date.isoformat(),
            "total": float(p.total),
            "status": p.status.value,
        }
        for p, name in rows
    ]


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(
    data: PurchaseCreate,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    # Hujjat raqami (doc_no) count() asosida beriladi — ikki xodim AYNI PAYTDA kirim qilsa bir xil
    # raqam chiqib UNIQUE(company_id, doc_no) buzilardi (500). create_sale kabi retry o'raymiz:
    # to'qnashuvда tranzaksiya bekor bo'lиб, qayta urinishда count() yangi raqam beradi.
    # (client_uuid dedup ichда IntegrityError chiqармасдан mavjudini qайтаради — retry qilinмайди.)
    from sqlalchemy.exc import IntegrityError as _IEwrap
    _last: Exception | None = None
    for _try in range(3):
        try:
            return _create_purchase_once(data, emp, db)
        except _IEwrap as e:
            db.rollback()
            _last = e
    raise HTTPException(409, "Xarid hujjati band — qayta urinib ko'ring") from _last


def _create_purchase_once(data: PurchaseCreate, emp: Employee, db: Session):
    if data.client_uuid:
        ex = db.query(Purchase).filter(
            Purchase.client_uuid == data.client_uuid, Purchase.company_id == emp.company_id
        ).first()
        if ex:
            return ex
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    # QATOR QULFI: qarз (debt) kirimда sup.balance RMW bir vaqtдаги to'lov bilan yo'qolмасин.
    sup = db.query(Supplier).filter(Supplier.id == data.supplier_id).with_for_update().first()
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    branch = (actor_branch(emp, db)  # xarid xodim filialiga (ko'p-filial: sotuv bilan izchil)
              or db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    from app.api.v1.reports import _biz_date
    now = datetime.now(timezone.utc)
    seq = db.query(Purchase).filter(Purchase.company_id == emp.company_id).count()
    if data.status not in {"received", "debt"}:
        raise HTTPException(400, "Noto'g'ri holat (received yoki debt)")
    status = PurchaseStatus.debt if data.status == "debt" else PurchaseStatus.received
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    from app.core.validate import guard_amount
    guard_amount(total, "Hujjat jami summasi")  # Numeric(14,2) yig'indi overflow -> do'stona 400

    pur = Purchase(
        doc_no=f"KIR-{1042 + seq + 1}",
        company_id=emp.company_id,
        branch_id=branch.id,
        supplier_id=data.supplier_id,
        employee_id=emp.id,
        purchase_date=_biz_date(db, emp.company_id),  # do'kon MAHALLIY sanasi (UTC emas)
        status=status,
        subtotal=total,
        total=total,
        paid_amount=Decimal("0") if status == PurchaseStatus.debt else total,
        client_uuid=data.client_uuid,
    )
    db.add(pur)
    db.flush()

    # QATOR QULFI (deadlock + lost-update): tegiladigan Inventory qatorlarini DASTAVVAL bir xil
    # global tartibda (product_id) qulflaymiz — bir vaqtdagi sotuv/kirim qoldiqni yo'qotmasin.
    for _pid in sorted({i.product_id for i in data.items}, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for i in data.items:
        prod = db.get(Product, i.product_id)
        if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        qty = Decimal(str(i.qty))
        cost = Decimal(str(i.unit_cost))
        _line = qty * cost
        guard_amount(_line, f"'{prod.name}' qatori summasi")  # qty*narx 1e18 gacha -> Numeric(14,2) overflow
        db.add(
            PurchaseItem(
                purchase_id=pur.id, product_id=i.product_id, qty=qty, unit_cost=cost,
                line_total=_line,
            )
        )
        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == i.product_id, Inventory.branch_id == branch.id)
            .first()
        )
        if inv is None:
            inv = Inventory(product_id=i.product_id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = Decimal(str(inv.qty)) + qty
        inv.updated_at = now
        if inv.qty > Decimal(str(inv.min_qty or 0)):
            inv.low_alerted = False  # restok — keyingi kam-qoldiqda yana push ketsin
        db.add(
            StockMovement(
                product_id=i.product_id, branch_id=branch.id, type=MovementType.purchase_in,
                qty=qty, unit_cost=cost, balance_after=inv.qty, ref_type="purchase",
                ref_id=pur.id, employee_id=emp.id, created_at=now,
            )
        )

    # qarzga bo'lsa — beruvchi balansi oshadi
    if status == PurchaseStatus.debt:
        sup = db.get(Supplier, data.supplier_id)
        sup.balance = Decimal(str(sup.balance)) + total
        db.add(
            SupplierLedger(
                supplier_id=sup.id, type=CreditTxnType.charge, amount=total,
                balance_after=sup.balance, ref_type="purchase", ref_id=pur.id, created_at=now,
            )
        )

    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "purchase", pur.id,
              after={"doc_no": pur.doc_no, "total": float(pur.total), "status": pur.status.value})
    # Phase 2b dual-write (guarded) — ASOSIY TESHIK (§07): NAQD (received) xarid endi kassadan
    # OUT·PURCHASE_OUT sifatida chiqadi (ilgari CashMovement yo'q edi -> kassa jimgina kamayardi).
    # SQLite/xaritalanmagan filialда no-op; source+ledger BIR tranzaksiyada (atomik).
    if status == PurchaseStatus.received:
        from app.services.cash import retrofit as _cr
        _cr.on_cash_purchase(db, emp, branch_id=branch.id, purchase_id=pur.id, cash_amount=total)
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_purchases_client_uuid) ushlади:
        # ikki marta stock-in/qarz emas, birinchисини qaytaramiz.
        db.rollback()
        if data.client_uuid:
            ex2 = db.query(Purchase).filter(
                Purchase.client_uuid == data.client_uuid, Purchase.company_id == emp.company_id).first()
            if ex2:
                return ex2
        raise
    db.refresh(pur)
    return pur


# ═══ KIRIM (xarid hujjati) BATAFSIL + TAHRIR ═══
@router.get("/purchases/{purchase_id}")
def purchase_detail(
    purchase_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    """Bitta kirim + uning jonli mahsulot qatorlari (tahrirlash uchun)."""
    pur = db.get(Purchase, purchase_id)
    if not pur or pur.company_id != emp.company_id or pur.deleted_at is not None:
        raise HTTPException(404, "Kirim topilmadi")
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # boshqa filial hujjatini ochib bo'lmaydi (IDOR)
    if _vb is not None and pur.branch_id not in _vb:
        raise HTTPException(404, "Kirim topilmadi")
    sup = db.get(Supplier, pur.supplier_id) if pur.supplier_id else None
    branch = (actor_branch(emp, db)  # xarid xodim filialiga (ko'p-filial: sotuv bilan izchil)
              or db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    units = {u.id: u.code for u in db.query(Unit).all()}
    rows = (
        db.query(PurchaseItem, Product.name, Product.unit_id, Product.base_sell_price)
        .join(Product, Product.id == PurchaseItem.product_id)
        .filter(PurchaseItem.purchase_id == pur.id)
        .all()
    )
    items = []
    for it, pname, unit_id, sell in rows:
        inv = None
        if branch:
            inv = (
                db.query(Inventory)
                .filter(Inventory.product_id == it.product_id, Inventory.branch_id == branch.id)
                .first()
            )
        items.append({
            "id": str(it.id), "product_id": str(it.product_id), "name": pname,
            "qty": float(it.qty), "unit_cost": float(it.unit_cost), "line_total": float(it.line_total),
            "sell_price": float(sell or 0),
            "unit": units.get(unit_id, "dona"), "stock": float(inv.qty) if inv else 0.0,
        })
    return {
        "id": str(pur.id), "doc_no": pur.doc_no,
        "supplier": sup.name if sup else "—",
        "supplier_id": str(pur.supplier_id) if pur.supplier_id else None,
        "date": pur.purchase_date.isoformat(), "status": pur.status.value,
        "payment": "credit" if pur.status in (PurchaseStatus.debt, PurchaseStatus.partial) else "cash",
        "subtotal": float(pur.subtotal), "total": float(pur.total), "paid_amount": float(pur.paid_amount or 0),
        "items": items,
    }


class PItemEdit(BaseModel):
    id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # mahsulot sotish narxi


class PurchaseEdit(BaseModel):
    items: list[PItemEdit] = []       # mavjud qatorlarni qty/narx bilan yangilash
    removed: list[uuid.UUID] = []      # o'chiriladigan qator id'lari
    client_uuid: uuid.UUID | None = None


@router.patch("/purchases/{purchase_id}")
def edit_purchase(
    purchase_id: uuid.UUID,
    data: PurchaseEdit,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    """Kirim mahsulotlarini tahrirlash: qty/narx o'zgartirish yoki qatorni o'chirish.
    Ombor qoldig'i (append-only StockMovement=adjustment), xarid jami va — hali qarz bo'lsa —
    yetkazib beruvchi balansi mos ravishda AVTO to'g'rilanadi. StockMovement immutable —
    eski yozuv o'zgармaydi, faqat kompensatsiya (tuzatish) harakati qo'shiladi.
    QA PR-002: Purchase qatori FOR UPDATE bilan qulflanadi (parallel/double-submit stok+qarz
    ikki marta kamaymasin); QA PR-002 idempotentlik: client_uuid berilsa shu edit allaqachon
    qo'llangan bo'lsa qayta ishlamaydi."""
    pur = db.get(Purchase, purchase_id)
    if not pur or pur.company_id != emp.company_id or pur.deleted_at is not None:
        raise HTTPException(404, "Kirim topilmadi")
    # FILIAL IZOLYATSIYASI (GET bilan izchil): boshqa filial hujjatini tahrirlab bo'lmaydi (IDOR).
    # Aks holда filialга bog'langan xodим ko'ra olmaydigan xaridini o'zgartirib, o'z filialiга qoldiq
    # "in'ektsiya" qilardi (reconcile actor_branch'ga yozardi).
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)
    if _vb is not None and pur.branch_id not in _vb:
        raise HTTPException(404, "Kirim topilmadi")
    # QA PR-002: HUJJAT QULFI + SNAPSHOT YANGILASH — pur qatorini FOR UPDATE bilan qulflaymiz va
    # qulf ostida qayta o'qiymiz. Ilgari pur.total/paid_amount qulf OLDIDAN o'qilardi (stale) —
    # ikki parallel/double-submit edit ikkalasi ham eski total'dan delta hisoblab stok/qarzni 2x
    # kamaytirardi (real-Postgres: 100->80 ikki marta -> stok 60). Endi 2-edit qulf ostida
    # yangilangan qatorni (qty=80) o'qib delta=0 hisoblaydi — idempotent.
    pur = db.query(Purchase).filter(Purchase.id == pur.id).with_for_update().first()
    db.refresh(pur)
    # QULF OSTIDA deleted_at QAYTA TEKSHIR: line 367 tekshiruvi qulfdan OLDIN — parallel to'liq-bekor
    # (cancel) shu orada commit qilib deleted_at o'rnatgan bo'lsa, biz endi o'chirilган xaridni qayta
    # cancel-branch'ga tushirib IKKINCHI PurchaseReturn (ikki marta IN·PURCHASE_RETURN) yozardik.
    if pur.deleted_at is not None:
        raise HTTPException(404, "Kirim topilmadi")
    # Reconcile XARID O'Z filialiга yoziladi (actor_branch EMAS) — aks holда ko'p-filialда tahrir
    # noto'g'ri filial qoldig'ини o'zgартарди (qoldiq boshqa filialга ketardi).
    # QA WH-008: filial o'chirilgan bo'lsa tahrir BLOKLANADI — ilgari fallback birinchi faol
    # filialga tushib, u yerda umuman bo'lmagan xarid uchun stok o'zgartirardi.
    branch = db.query(Branch).filter(Branch.id == pur.branch_id, Branch.deleted_at.is_(None)).first()
    if not branch:
        raise HTTPException(400, "Xarid filiali o'chirilgan — tahrirlab bo'lmaydi")
    # QATOR QULFI: balans RMW (quyида) bir vaqtдаги to'lov/kirim bilan yo'qolмасин (pay_supplier bilan izchil).
    sup = (db.query(Supplier).filter(Supplier.id == pur.supplier_id).with_for_update().first()
           if pur.supplier_id else None)
    # QA PR-008: Supplier qulfini olgach pur'ni QAYTA refresh — parallel pay_supplier (u sup'ni
    # qulflaydi) pur.paid_amount'ni o'zgartirgan bo'lsa, biz endi yangi qiymatni o'qiymiz (status
    # to'g'ri hisoblanadi, to'liq-to'langan xarid vaqtincha 'debt' bo'lib qolmaydi).
    db.refresh(pur)
    now = datetime.now(timezone.utc)

    existing = {it.id: it for it in db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).all()}
    for rid in data.removed:
        if rid not in existing:
            raise HTTPException(400, "Qator topilmadi")
    for upd in data.items:
        if upd.id not in existing:
            raise HTTPException(400, "Qator topilmadi")

    _names: dict = {}

    def _pname(pid):
        if pid not in _names:
            p = db.get(Product, pid)
            _names[pid] = p.name if p else str(pid)
        return _names[pid]

    def _reconcile(product_id, delta, cost):
        """inv.qty += delta (ishorali); tuzatish harakati qo'shiladi. Qoldiq manfiy bo'lmasin."""
        if delta == 0:
            return
        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == product_id, Inventory.branch_id == branch.id)
            .with_for_update()
            .first()
        )
        cur = Decimal(str(inv.qty)) if inv else Decimal("0")
        new_qty = cur + delta
        # QA WH-019: guard faqat KAMAYTIRUVCHI delta uchun — qoldiq (oversell tufayli) manfiy
        # bo'lsa OSHIRUVCHI tahrir ham bloklanardi (holatni yaxshilaydigan amal taqiqlanardi).
        if delta < 0 and new_qty < 0:
            raise HTTPException(400, f"Ombor qoldig'i yetarli emas: {_pname(product_id)} (qoldiq {cur})")
        if inv is None:
            inv = Inventory(product_id=product_id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = new_qty
        inv.updated_at = now
        db.add(StockMovement(
            product_id=product_id, branch_id=branch.id, type=MovementType.adjustment,
            qty=delta, unit_cost=cost, balance_after=inv.qty, ref_type="purchase_edit",
            ref_id=pur.id, employee_id=emp.id, created_at=now,
        ))

    old_total = Decimal(str(pur.total))

    # DEADLOCK oldini olish: tegадиган Inventory qatorlarини DASTAVVAL bir xil GLOBAL tartибда
    # (product_id) qulflaymiz (sotuv/qaytarish bilan izchil) — _reconcile keyin qayta o'qиганда
    # qator allaqачон qulflangan (no-op).
    _touched = {existing[rid].product_id for rid in data.removed if rid in existing} | \
               {existing[upd.id].product_id for upd in data.items if upd.id in existing}
    for _pid in sorted(_touched, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()

    # 1) O'chirish
    for rid in data.removed:
        it = existing.pop(rid)
        _reconcile(it.product_id, -Decimal(str(it.qty)), Decimal(str(it.unit_cost)))
        db.delete(it)

    # 2) Yangilash (qty/narx)
    for upd in data.items:
        it = existing.get(upd.id)
        if it is None:
            continue
        new_qty = Decimal(str(upd.qty))
        new_cost = Decimal(str(upd.unit_cost))
        _reconcile(it.product_id, new_qty - Decimal(str(it.qty)), new_cost)
        it.qty = new_qty
        it.unit_cost = new_cost
        from app.core.validate import guard_amount
        it.line_total = guard_amount(new_qty * new_cost, "Qator summasi")  # Numeric(14,2) overflow -> 400
        # Sotish narxi berilsa — mahsulot kartochkasi ham yangilanadi
        if upd.sell_price is not None and upd.sell_price > 0:
            prod = db.get(Product, it.product_id)
            if prod is not None and Decimal(str(upd.sell_price)) != Decimal(str(prod.base_sell_price)):
                prod.base_sell_price = Decimal(str(upd.sell_price))

    db.flush()
    remaining = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == pur.id).all()
    new_total = sum((Decimal(str(it.line_total)) for it in remaining), Decimal("0"))
    from app.core.validate import guard_amount as _guard_amount
    _guard_amount(new_total, "Hujjat jami summasi")  # Numeric(14,2) yig'indi overflow -> do'stona 400

    # Yetkazib beruvchi qarzini to'g'rilash — faqat hali to'lanmagan qismi (outstanding) o'zgarsa
    paid = Decimal(str(pur.paid_amount or 0))
    # 0'ga CHEKLAMAYMIZ: xarid to'langandan pastroqqa tushirilса, ortiqcha to'lov (paid - new_total)
    # yetkazib beruvchi balansini MANFIY qiladi (ta'minotchi do'konga qarzdor). Ilgari max(0)
    # ortiqchani jimgina yo'qotardi. delta = new_total - old_total (paid qisqaradi).
    old_out = old_total - paid
    new_out = new_total - paid
    delta_out = new_out - old_out
    # FAQAT ledgerga CHARGE yozgan (debt/nasiya) xaridlar balansni o'zgartiradi. Naqd (received)
    # xarid kassa/smena orqali hisoblanadi, SupplierLedger'ga umuman tegmagan — uni tahrirlaganда
    # delta_out'ni balansga qo'shsak, asossiz manfiy qarz in'ektsiya bo'lib begona qarzni yeb qo'yardi.
    # QA PR-001: charge ref_type IKKI xil bo'lishi mumkin — Manager xaridi 'purchase',
    # mobil kredit-qabul (receiving.commit) 'receiving'. Ilgari faqat 'purchase' izlanib,
    # receiving-manbali kredit xaridni tahrir/bekor qilganda qarz UMUMAN rollback bo'lmasdi
    # (osilib qolardi, keyingi to'lovda ortiqcha naqd chiqardi).
    _charged = sup is not None and db.query(SupplierLedger.id).filter(
        SupplierLedger.supplier_id == pur.supplier_id, SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.ref_id == pur.id, SupplierLedger.type == CreditTxnType.charge).first() is not None
    if _charged and delta_out != 0:
        sup.balance = Decimal(str(sup.balance or 0)) + delta_out
        db.add(SupplierLedger(
            supplier_id=sup.id, type=CreditTxnType.adjustment, amount=delta_out,
            balance_after=sup.balance, ref_type="purchase_edit", ref_id=pur.id, created_at=now,
        ))

    pur.subtotal = new_total
    pur.total = new_total
    if not remaining:
        pur.status = PurchaseStatus.cancelled
        pur.deleted_at = now
    elif not _charged:
        # QA PR-004: NAQD (received) xarid — ledgerga charge yozmagan, paid_amount = kassa
        # artefakti (to'lov emas). Uni new_total vs paid bo'yicha 'partial/debt' qilib bo'lmaydi:
        # aks holda summani oshirganda soxta qarz yaratilib, pay_supplier FIFO'ni buzardi (phantom
        # payable). Naqd xarid HAR DOIM 'received' qoladi + paid_amount total'ga tenglashtiriladi.
        pur.status = PurchaseStatus.received
        pur.paid_amount = new_total
    elif new_total <= paid:
        pur.status = PurchaseStatus.received
    elif paid > 0:
        pur.status = PurchaseStatus.partial
    else:
        pur.status = PurchaseStatus.debt

    # Bog'langan Receiving snapshotini yangilaymiz (tarix/hisobot izchil bo'lsin)
    rec = db.query(Receiving).filter(Receiving.purchase_id == pur.id).first()
    if rec is not None:
        umap = {u.id: u.code for u in db.query(Unit).all()}
        fi, tq = [], Decimal("0")
        for it in remaining:
            p = db.get(Product, it.product_id)
            fi.append({"product_id": str(it.product_id), "name": p.name if p else "",
                       "qty": float(it.qty), "unit_cost": float(it.unit_cost), "ai_name": None,
                       "unit": umap.get(p.unit_id if p else None, "dona")})
            tq += Decimal(str(it.qty))
        rec.final_items = fi
        rec.total_types = len(fi)
        rec.total_qty = tq

    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "edit", "purchase", pur.id,
              after={"name": pur.doc_no, "total": float(new_total), "items": len(remaining)})

    # Phase 2b — PURCHASE RETURN dual-write (guarded): NAQD (received) xarid KAMAYTIRILSA/BEKOR
    # qilinса, create'даги OUT·PURCHASE_OUT'ni qisman qaytaramiz -> IN·PURCHASE_RETURN. Manba =
    # ALOHIDA PurchaseReturn hodisasi (create leg bilan cle_uq_business TO'QNASHMAYDI; bir xariddan
    # ko'p qaytarish mustaqil). FAQAT naqd (`not _charged`): debt xarid SupplierLedger orqali
    # (kassa tegilmaydi). Idempotency: pur FOR UPDATE qulf ostида — retry'да paid==new_total ->
    # ret_amt 0 -> yozilmaydi; to'liq bekor deleted_at bilan bir martalik. NAQD summa butun-som
    # ([[whole-som-payments]]). Ko'r: app/db/cash/PURCHASE_RETURN_identity.md.
    _ret_amt = paid - new_total
    if not _charged and _ret_amt > 0:
        pr = PurchaseReturn(company_id=pur.company_id, purchase_id=pur.id, branch_id=pur.branch_id,
                            amount=_ret_amt, reason="edit/cancel", employee_id=emp.id,
                            client_uuid=data.client_uuid, created_at=now)
        db.add(pr)
        db.flush()   # pr.id — ledger source_id sifatida kerak (SQLite'да guard no-op qiladi)
        from app.services.cash import retrofit as _cr
        # purchase_id — hook create'даги OUT·PURCHASE_OUT mavjudligini tekshiradi (mos OUT bo'lмаса
        # phantom IN yozmaydi: mobil receiving naqd xaridi / parallel-run pre-cutover).
        _cr.on_purchase_return(db, emp, branch_id=pur.branch_id, purchase_id=pur.id,
                               purchase_return_id=pr.id, cash_amount=_ret_amt)

    db.commit()
    return {"ok": True, "id": str(pur.id), "total": float(new_total),
            "cancelled": len(remaining) == 0, "status": pur.status.value}


class SupplierPaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    method: str = "cash"
    client_uuid: uuid.UUID | None = None   # offline idempotentlik (qayta yuborishда ikki marta to'lamaslik)


@router.post("/suppliers/{supplier_id}/payments")
def pay_supplier(
    supplier_id: uuid.UUID,
    data: SupplierPaymentIn,
    emp: Employee = Depends(require("xaridlar.edit")),
    db: Session = Depends(get_db),
):
    # QATOR QULFI: bir vaqtда ikki to'lov (yoki to'lov + kirim) sup.balance/paid_amount'ni STALE
    # o'qib yo'qotмасин (pay_credit mijoz uchun shunday qulflaydi — parity). Postgres'да muhim.
    sup = db.query(Supplier).filter(Supplier.id == supplier_id).with_for_update().first()
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if data.method not in {"cash", "card", "qr"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.method}")
    # Idempotentlik — offline qayta yuborish ikki marta to'lamasin (mijoz pay_credit bilan izchil)
    if data.client_uuid:
        ex = (
            db.query(SupplierPayment)
            .filter(SupplierPayment.client_uuid == data.client_uuid, SupplierPayment.supplier_id == sup.id)
            .first()
        )
        if ex:
            return {"supplier_id": str(sup.id), "balance": float(sup.balance), "paid": float(ex.amount), "duplicate": True}
    now = datetime.now(timezone.utc)
    # Overpayment — qarzdan oshig'i qabul qilinmaydi (mijoz pay_credit bilan izchil)
    bal = Decimal(str(sup.balance or 0))
    amt = min(Decimal(str(data.amount)), bal) if bal > 0 else Decimal("0")
    if amt <= 0:
        raise HTTPException(400, "Bu yetkazib beruvchiga qarz yo'q")
    pay = SupplierPayment(supplier_id=sup.id, amount=amt, method=data.method, paid_at=now,
                          employee_id=emp.id, created_at=now, client_uuid=data.client_uuid)
    db.add(pay)
    db.flush()
    sup.balance = bal - amt
    db.add(SupplierLedger(
        supplier_id=sup.id, type=CreditTxnType.payment, amount=-amt,
        balance_after=sup.balance, ref_type="payment", ref_id=pay.id, created_at=now,
    ))
    # NAQD ta'minotчи to'lovi kassaдан chiqadi — to'lagan xodимнинг OCHIQ smenasига payout
    # yoziladi (aks holда smena "kutilgan naqd" bilan hisobот kassasi mos kelmасди). Hisobот
    # cashflow bu payout'ни "Ta'minotчи" prefiksi bilan chiqarib tashlaйди (SupplierPayment'дан
    # allaqачон sanaладı — ikki marta hisoblanмасин; qarz to'lovи naqди bilan izchil naqsh).
    if data.method == "cash":
        from app.models.enums import CashMovementType as _CMT
        from app.models.enums import ShiftStatus as _ShSt
        from app.models.shifts import CashMovement as _CM
        from app.models.shifts import Shift as _Shift
        _sh = db.query(_Shift).filter(_Shift.cashier_id == emp.id, _Shift.status == _ShSt.open).first()
        if _sh:
            db.add(_CM(shift_id=_sh.id, type=_CMT.payout, amount=amt,
                       reason=f"Ta'minotchi · {sup.name}", employee_id=emp.id, created_at=now))
    # To'lovni eng eski qarzdagi xaridlarga taqsimlaymiz (paid_amount/status yangilanadi)
    remaining = amt
    debts = (
        db.query(Purchase)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == sup.id,
                # 'partial' ham qarzdor — ilgari faqat 'debt' olinib, qisman to'langan
                # xarid abadiy chala qolardi
                Purchase.status.in_([PurchaseStatus.debt, PurchaseStatus.partial]))
        .order_by(Purchase.purchase_date, Purchase.created_at)
        .all()
    )
    for pur in debts:
        if remaining <= 0:
            break
        due = Decimal(str(pur.total)) - Decimal(str(pur.paid_amount or 0))
        if due <= 0:
            pur.status = PurchaseStatus.received
            continue
        pay_part = min(due, remaining)
        pur.paid_amount = Decimal(str(pur.paid_amount or 0)) + pay_part
        remaining -= pay_part
        if Decimal(str(pur.paid_amount)) >= Decimal(str(pur.total)):
            pur.status = PurchaseStatus.received
        else:
            pur.status = PurchaseStatus.partial  # qisman to'landi — holat aniq ko'rinsin
    # Phase 2b dual-write (guarded): NAQD ta'minotchi to'lovi -> OUT·SUPPLIER_OUT. SQLite'da no-op.
    # Yetarli naqd yo'q bo'lsa CashPostingService rad etadi -> BUTUN tranzaksiya (SupplierPayment+AP+
    # taqsimot) rollback (§03). source+AP+ledger atomik.
    if data.method == "cash":
        from app.services.cash import retrofit as _cr
        _cr.on_supplier_payment(db, emp, branch_id=(_sh.branch_id if _sh else None), payment_id=pay.id, cash_amount=amt)
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_suppay_client_uuid) ushlади.
        db.rollback()
        s2 = db.get(Supplier, supplier_id)
        return {"supplier_id": str(supplier_id), "balance": float(s2.balance) if s2 else 0.0,
                "paid": float(amt), "duplicate": True}
    return {"supplier_id": str(sup.id), "balance": float(sup.balance), "paid": float(amt)}


@router.get("/suppliers/{supplier_id}/ledger")
def supplier_ledger(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.company_id != emp.company_id:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    rows = (
        db.query(SupplierLedger)
        .filter(SupplierLedger.supplier_id == supplier_id)
        .order_by(SupplierLedger.created_at.desc())
        .all()
    )
    return [
        {"type": r.type.value, "amount": float(r.amount), "balance_after": float(r.balance_after),
         "ref_type": r.ref_type, "at": r.created_at}
        for r in rows
    ]


@router.get("/suppliers/{supplier_id}")
def supplier_detail(
    supplier_id: uuid.UUID,
    emp: Employee = Depends(require("xaridlar.view")),
    db: Session = Depends(get_db),
):
    """Yetkazib beruvchi batafsili: qarz (balans), xaridlar tarixi, yetkazgan mahsulotlar."""
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
        raise HTTPException(404, "Yetkazib beruvchi topilmadi")

    # Xarid hujjatlari (so'nggi)
    purchases = (
        db.query(Purchase)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == supplier_id,
                Purchase.deleted_at.is_(None))
        .order_by(Purchase.purchase_date.desc(), Purchase.doc_no.desc())
        .all()
    )
    purchase_count = len(purchases)
    total_purchased = float(sum((p.total for p in purchases), Decimal("0")))
    recent = [
        {"id": str(p.id), "doc_no": p.doc_no, "date": p.purchase_date.isoformat(),
         "total": float(p.total), "status": p.status.value}
        for p in purchases[:40]
    ]

    # Yetkazgan mahsulotlar (agregat: nom + jami miqdor + jami summa + kutilayotgan foyda)
    prod_rows = (
        db.query(Product.name,
                 func.coalesce(func.sum(PurchaseItem.qty), 0),
                 func.coalesce(func.sum(PurchaseItem.qty * PurchaseItem.unit_cost), 0),
                 Product.base_sell_price)
        .join(PurchaseItem, PurchaseItem.product_id == Product.id)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.company_id == emp.company_id, Purchase.supplier_id == supplier_id,
                Purchase.deleted_at.is_(None))
        .group_by(Product.id, Product.name, Product.base_sell_price)
        .order_by(func.sum(PurchaseItem.qty * PurchaseItem.unit_cost).desc())
        .all()
    )
    products = []
    total_qty = 0.0
    expected_profit = 0.0
    for name, qty, cost, sell in prod_rows:
        q = float(qty or 0)
        c = float(cost or 0)
        s = float(sell or 0)
        prof = q * s - c   # joriy sotuv narxida olib kelingan tovardan kutilayotgan foyda
        products.append({"name": name, "qty": q, "cost": c, "profit": prof})
        total_qty += q
        expected_profit += prof

    paid_total = float(sum((p.paid_amount or Decimal("0") for p in purchases), Decimal("0")))
    avg_purchase = (total_purchased / purchase_count) if purchase_count else 0.0
    profit_margin = (expected_profit / total_purchased * 100) if total_purchased else 0.0
    last_purchase = purchases[0].purchase_date.isoformat() if purchases else None
    top_qty = max(products, key=lambda x: x["qty"], default=None)
    top_profit = max(products, key=lambda x: x["profit"], default=None)

    return {
        "id": str(sup.id), "name": sup.name, "phone": sup.phone,
        "balance": float(sup.balance),
        "purchase_count": purchase_count,
        "total_purchased": total_purchased,
        "paid_total": paid_total,
        "product_types": len(products),
        "total_qty": total_qty,
        "avg_purchase": avg_purchase,
        "expected_profit": expected_profit,
        "profit_margin": profit_margin,
        "last_purchase": last_purchase,
        "top_qty_product": {"name": top_qty["name"], "qty": top_qty["qty"]} if top_qty else None,
        "top_profit_product": {"name": top_profit["name"], "profit": top_profit["profit"]} if top_profit else None,
        "products": products,
        "recent_purchases": recent,
    }
