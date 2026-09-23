import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import actor_branch, get_current_employee, require
from app.db.session import get_db
from app.services import doc_seq as _DS
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
from app.models.receiving import Receiving, ReceivingCorrection
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
            # §7 IDEMPOTENTLIK KONFLIKTI: AYNI source (client_uuid) qayta yuborilsa, LEKIN BOSHQA
            # custody hisobi bilan kelsa -> BALAND OVOZDA rad. Jimgina yangi hisobga post qilish
            # yoki eskisini jimgina saqlab qolish IKKALASI ham noto'g'ri (audit yolg'on bo'lardi).
            if (data.cash_account_id is not None and ex.cash_account_id is not None
                    and str(data.cash_account_id) != str(ex.cash_account_id)):
                from app.services.cash import cutover_guard as _cg0
                raise HTTPException(409, f"{_cg0.ERR_CUSTODY_INVALID}: bu amal allaqachon boshqa naqd "
                                         f"hisob bilan yozilgan ({ex.cash_account_id}) — qayta yuborishda "
                                         "hisobni o'zgartirib bo'lmaydi.")
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

    if data.status not in {"received", "debt"}:
        raise HTTPException(400, "Noto'g'ri holat (received yoki debt)")
    status = PurchaseStatus.debt if data.status == "debt" else PurchaseStatus.received
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    from app.core.validate import guard_amount
    guard_amount(total, "Hujjat jami summasi")  # Numeric(14,2) yig'indi overflow -> do'stona 400

    pur = Purchase(
        doc_no=_DS.next_no(db, emp.company_id, _DS.PURCHASE)[1],   # atomik hisoblagich
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
    # ⚠️  PARTIYA DARVOZASI. Bu HAM kirim yo'li, lekin `lots` maydonini BILMAYDI.
    #     Phase 1 partiyani FAQAT `/receiving/commit` orqali tug'diradi; bu yerda
    #     kuzatuvli mahsulot qabul qilinsa partiyasiz qoldiq paydo bo'lardi.
    from app.services import stock_gate as _SG
    _SG.http_assert_untracked(db, [i.product_id for i in data.items],
                              "xarid (partiyasiz kirim)")
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
    # ⚠️  PARTIYA DARVOZASI QAYTA — QOLDIQ QATORLARI USHLANGACH (Phase 5B, W). Yuqoridagi
    #     tekshiruv qulfdan OLDIN: `/lots/enable` qatorni ushlab commit qilsa, xarid ESKI
    #     javob bilan partiyasiz qoldiq kiritardi. Qulf halqasi YO'Q qatorni qulflamaydi
    #     (sikl uni qulfsiz o'qiydi yoki yaratadi), shu bois tekshiruv sikl va FLUSH'dan
    #     KEYIN: har qator endi yo qulflangan, yo INSERT/UPDATE qilingan — yoqish bizdan
    #     oldin commit qila olmaydi, yangi SELECT esa haqiqatni ko'radi.
    #     Kuzatuvsiz xaridda: yozuvlar biroz ERTAROQ flush bo'ladi + BITTA SELECT.
    db.flush()
    _SG.http_assert_untracked(db, [i.product_id for i in data.items],
                              "xarid (partiyasiz kirim)")

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
        # §2 PURCHASE CUSTODY: post-T0 naqd xarid AYNAN fizik custody hisobini talab qiladi.
        # Smena bor -> manba = shift.till_id. Smenasiz bo'lsa -> HOZIRCHA FAIL-CLOSED: filial
        # bo'yicha TAXMIN QILINMAYDI (ilgari branch-guess qilinardi yoki JIMGINA ledger'siz
        # o'tib ketardi). Explicit cash_account_id so'rov shakli — keyingi qadam (docs).
        from app.models.enums import ShiftStatus as _ShSt3
        from app.models.shifts import Shift as _Shift3
        from app.services.cash import cutover_guard as _cg
        _psh = (db.query(_Shift3).filter(_Shift3.cashier_id == emp.id,
                                         _Shift3.status == _ShSt3.open).first())
        # §2: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT cash_account_id.
        _pacc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id, branch_id=branch.id,
                                            operation="cash_purchase", shift=_psh,
                                            cash_account_id=data.cash_account_id)
        _cr.on_cash_purchase(db, emp, branch_id=branch.id, purchase_id=pur.id, cash_amount=total,
                             cash_account_id=(_pacc.id if _pacc else None))
        if _pacc is not None:
            pur.cash_account_id = _pacc.id          # §5 audit identity (additive, nullable)
            db.add(pur)
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
        db.query(PurchaseItem, Product.name, Product.unit_id, Product.base_sell_price,
                 Product.track_lots, Product.track_expiry)
        .join(Product, Product.id == PurchaseItem.product_id)
        .filter(PurchaseItem.purchase_id == pur.id)
        .all()
    )
    items = []
    for it, pname, unit_id, sell, track_lots, track_expiry in rows:
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
            # Partiya bayroqlari (QO'SHIMCHA maydon — eski mijoz e'tiborsiz qoldiradi).
            # UI kuzatuvli qatorda miqdor/narx/o'chirishni QULFLAYDI: server ularni
            # baribir rad etadi (409), lekin operator buni tugmani bosgandan
            # KEYIN emas, oldin bilishi kerak.
            "track_lots": bool(track_lots), "track_expiry": bool(track_expiry),
        })
    # ── TUZATISH KO'RINISHI (Phase 5D) — QO'SHIMCHA, faqat O'QISH maydonlari ──
    #  ⚠️  Eski mijoz bu kalitlarni e'tiborsiz qoldiradi. Manager esa operatorga
    #      tugmani bosishdan OLDIN aytishi kerak: qaysi kogortada qancha qoldi,
    #      qanchasi allaqachon harakatlangan va IDENTIFIKATSIYASI hali
    #      tuzatilishi mumkinmi. Buni frontend O'ZI hisoblab chiqarmasin — aks
    #      holda ekran server qoidasi (`lot_correction.untouched`) bilan bir kun
    #      ajralib ketardi.
    rec_id, corrections, blocked, custody = _correction_view(db, emp, pur, items)
    # Phase 5G: HUJJAT filiali va uning BIZNES sanasi (tuzatishdagi yangi partiya muddati
    # shu sanadan oldin bo'lmasligi kerak). Ilgari mijoz sanani `/lots/products/{id}` dan —
    # ya'ni XODIM filialidan — olardi; ko'p filialda bu boshqa filial sanasi bo'lishi mumkin.
    from app.services import lot_policy as _LPd
    _dbr = db.get(Branch, pur.branch_id) if pur.branch_id else None
    return {
        "id": str(pur.id), "doc_no": pur.doc_no,
        "branch_id": str(pur.branch_id) if pur.branch_id else None,
        "branch_name": _dbr.name if _dbr is not None else None,
        "business_date": (_LPd.business_date(db, pur.branch_id).isoformat()
                          if pur.branch_id else None),
        "supplier": sup.name if sup else "—",
        "supplier_id": str(pur.supplier_id) if pur.supplier_id else None,
        "date": pur.purchase_date.isoformat(), "status": pur.status.value,
        "payment": "credit" if pur.status in (PurchaseStatus.debt, PurchaseStatus.partial) else "cash",
        "subtotal": float(pur.subtotal), "total": float(pur.total), "paid_amount": float(pur.paid_amount or 0),
        "items": items,
        "receiving_id": rec_id,
        "correctable": blocked is None,
        "correction_blocked_reason": blocked,
        "corrections": corrections,
        # ⚠️  KASSA CUSTODY — QO'SHIMCHA, faqat O'QISH bloki (§A.3). Eski mijoz uni
        #     e'tiborsiz qoldiradi. Qaror SERVERNIKI: `lot_correction.cash_custody_view`
        #     yozuvchi bilan AYNI funksiyani (`preview_cash_custody`) bajaradi, shu bois
        #     ekran «mumkin» deb ko'rsatib, server 400 beradigan holat tug'ilmaydi.
        "cash_custody": custody,
    }


# Qator darajasidagi to'siq matni — MAHSULOT bo'yicha (hujjat bo'yicha emas).
SHORTFALL_BLOCK = ("Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga "
                   "bog'lang, keyin bu qatorni tuzating.")


def _correction_view(db: Session, emp: Employee, pur: Purchase, items: list):
    """`items` ga `lots` ni QO'SHADI; (receiving_id, tuzatishlar, to'siq, kassa bloki).

    ⚠️  SERVER QARORI, MIJOZ HISOBI EMAS. «Tuzatsa bo'ladimi» savolining javobi
        `services/lot_correction.py` dagi AYNI predikatlardan chiqadi
        (`untouched`, `open_shortfall_products`) — ikki joyda ikki xil hisob
        operatorga «mumkin» deb ko'rsatib, server 409 berardi.

    ⚠️  KOGORTALAR MAHSULOT BO'YICHA BOG'LANADI. Qabul partiyasida
        `purchase_item_id` NULL (`/receiving/commit` uni yozmaydi — kanonik
        bog'lanish `receiving_id`), shu bois bir mahsulot ikki qatorda kelsa
        kogortalar IKKALA qatorda ham ko'rinadi. Buni «tuzatib» qo'yish uchun
        taxmin qilish kerak bo'lardi.
    """
    from app.models.inventory import StockBatch
    from app.services import lot_correction as _LC

    # ⚠️  KALITLAR HAR YO'LDA BOR. Hujjat darajasidagi to'siqda ham (`rec is None`,
    #     partiyasiz qabul) qator kalitlari BO'LISHI shart: mijoz `undefined` ni
    #     «tuzatsa bo'ladi» deb o'qimasin.
    for it in items:
        it["correctable"] = False
        it["correction_blocked_reason"] = None
    # ⚠️  KASSA BLOKI HAM HAR YO'LDA. U hujjat DARAJASIDAGI holat (qarzmi/naqdmi,
    #     T0 o'tganmi, aktyorning smenasi bormi) — partiyalarga BOG'LIQ EMAS, shu
    #     bois quyidagi erta qaytishlarda ham AYNI shakl qaytadi: mijozda `undefined`
    #     bo'lib «hech narsa kerak emas» deb o'qilmasin.
    custody = _LC.cash_custody_view(db, emp, pur)
    rec = db.query(Receiving).filter(Receiving.purchase_id == pur.id).first()
    rows = (db.query(ReceivingCorrection)
            .filter(ReceivingCorrection.company_id == emp.company_id,
                    ReceivingCorrection.purchase_id == pur.id)
            .order_by(ReceivingCorrection.created_at.desc()).all())
    names = (dict(db.query(Employee.id, Employee.full_name)
                  .filter(Employee.company_id == emp.company_id).all()) if rows else {})
    corrections = [{"id": str(r.id), "at": r.created_at, "reason": r.reason,
                    "delta_total": float(r.delta_total or 0),
                    "employee": names.get(r.employee_id, "—")} for r in rows]
    if rec is None:
        return None, corrections, ("Bu hujjatga bog'langan qabul yo'q — tuzatish "
                                   "faqat qabul hujjati orqali bajariladi."), custody
    batches = (db.query(StockBatch)
               .filter(StockBatch.company_id == emp.company_id,
                       StockBatch.receiving_id == rec.id)
               .order_by(StockBatch.received_at, StockBatch.id).all())
    if not batches:
        return str(rec.id), corrections, ("Bu qabul partiya yaratmagan — tuzatish "
                                          "oqimi faqat partiyali qabul uchun."), custody
    sums = _LC.alloc_sums(db, [b.id for b in batches])
    # ⚠️  QATOR NARXI DECIMAL HOLDA — `doc_unit_cost` pul asosini AYNAN yozuvchi
    #     bilan bir xil hisoblasin (float orqali o'tkazish tiyin farqini tug'dirardi).
    line_cost = {str(i.id): i.unit_cost for i in db.query(PurchaseItem)
                 .filter(PurchaseItem.purchase_id == pur.id).all()}
    batch_by_id = {str(b.id): b for b in batches}
    by_pid: dict = {}
    for b in batches:
        by_pid.setdefault(str(b.product_id), []).append({
            "id": str(b.id), "batch_no": b.batch_no,
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "received_qty": float(b.received_qty or 0),
            "remaining_qty": float(b.remaining_qty or 0),
            # GROSS harakat: qaytib kelgan tovar kogorta identifikatsiyasi
            # ishlatilganini BEKOR QILMAYDI (`lot_correction.moved` izohi).
            "consumed_qty": float(_LC.moved(sums.get(str(b.id)))),
            "unit_cost": float(b.unit_cost or 0), "status": b.status,
            "correctable": _LC.untouched(b, sums.get(str(b.id))),
        })
    # ⚠️  QARZ TO'SIG'I — MAHSULOT BO'YICHA, HUJJAT BO'YICHA EMAS. Server ham
    #     aynan shu mahsulotni rad etadi (`lot_correction` darvozasi so'rovdagi
    #     qatorlarning mahsulotlarini tekshiradi), shu bois 3-qatordagi bitta
    #     yopilmagan qarz butun nakladnoyni tuzatib bo'lmaydigan qilib
    #     ko'rsatmasin: operator 7-qatordagi xatoni baribir tuzata oladi.
    qarzli = {str(p) for p in _LC.open_shortfall_products(
        db, emp.company_id, {b.product_id for b in batches}, pur.branch_id)}
    for it in items:
        # ⚠️  `doc_unit_cost` — KOGORTANI TESKARI QILISH HUJJATDAN QANCHA OLIB
        #     TASHLASHI (va demak kassadan qancha qaytishi). U SERVERDA,
        #     `lot_correction.doc_unit_cost` bilan AYNI qoidadan hisoblanadi va
        #     shu bois ekran bilan yozuvchi IKKI XIL asosdan foydalana OLMAYDI:
        #     ilgari ekran qaytimni KOGORTA narxida (`unit_cost`), yozuvchi esa
        #     QATOR narxida hisoblardi — oldingi tuzatish qo'ygan kogortada ular
        #     qarama-qarshi tomonga ajralardi.
        # ⚠️  QATOR BO'YICHA NUSXA: bitta mahsulot ikki qatorda kelsa kogorta
        #     ikkala qatorda ko'rinadi (yuqoridagi izoh), qator narxi esa HAR
        #     XIL bo'lishi mumkin — umumiy `dict` ga yozish ikkinchi qatorning
        #     raqamini birinchisiga ham yopishtirardi.
        lc = line_cost.get(it["id"])
        it["lots"] = [
            {**lot, "doc_unit_cost": float(
                _LC.doc_unit_cost(batch_by_id.get(lot["id"]), lc))}
            for lot in by_pid.get(it["product_id"], [])]
        blok = SHORTFALL_BLOCK if it["product_id"] in qarzli else None
        it["correctable"] = blok is None
        it["correction_blocked_reason"] = blok
        if blok is not None:
            for lot in it["lots"]:
                lot["correctable"] = False
                lot["blocked_reason"] = blok
    blocked = None
    if db.query(Branch).filter(Branch.id == pur.branch_id,
                               Branch.deleted_at.is_(None)).first() is None:
        blocked = "Xarid filiali o'chirilgan — tuzatib bo'lmaydi."
    return str(rec.id), corrections, blocked, custody


def _lock_guard(db: Session, emp: Employee, pur: Purchase) -> None:
    """Hujjatda tuzatish bo'lsa — eski kirim tahriri RAD etiladi (Phase 5D).

    Barqaror kod MATNGA qo'shilmaydi: u `X-Error-Code` sarlavhasiga ketadi
    (`app/core/error_codes.py` izohi)."""
    from app.core import error_codes as _EC
    from app.services import lot_correction as _LC
    if _LC.doc_has_correction(db, emp.company_id, pur.id):
        raise HTTPException(
            409, "Bu kirim tuzatilgan — eski tahrir yo'li hujjat jamini qatorlardan "
                 "QAYTA hisoblab, tuzatishni jimgina teskari qilardi. O'zgartirish "
                 "uchun yangi tuzatish yarating.",
            headers=_EC.headers(_EC.LOT_CORRECTION_DOC_LOCKED))


class PItemEdit(BaseModel):
    id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # mahsulot sotish narxi


class PurchaseEdit(BaseModel):
    items: list[PItemEdit] = []       # mavjud qatorlarni qty/narx bilan yangilash
    removed: list[uuid.UUID] = []      # o'chiriladigan qator id'lari
    client_uuid: uuid.UUID | None = None
    # §1 EXPLICIT CUSTODY: smenasiz naqd amali uchun fizik hisob (TILL yoki SAFE) AYNAN
    # ko'rsatiladi. Ochiq smena bo'lsa server shift.till_id ni ishlatadi va bu maydon unga
    # TENG bo'lishi kerak (override QILIB BO'LMAYDI). Legacy/pre-T0 uchun nullable.
    cash_account_id: uuid.UUID | None = None


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
    # ⚠️  TUZATILGAN HUJJAT — ESKI TAHRIR YO'LI YOPIQ (Phase 5D). Bu yo'l hujjat
    #     jamini `purchase_items` dan QAYTA hisoblaydi, tuzatish esa AYNAN o'sha
    #     qatorlarni tegilmagan holda qoldirib faqat hosila summalarni siljitgan
    #     edi — ya'ni bitta saqlash tuzatishni JIMGINA teskari qilardi (qarz va
    #     kassa esa o'z holicha qolardi). Bu yerda arzon, qulfsiz tekshiruv;
    #     HAL QILUVCHISI quyida, hujjat qulfi ostida.
    _lock_guard(db, emp, pur)
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
    # ⚠️  TUZATISH DARVOZASI — QULF OSTIDA QAYTA (Phase 5D). Yuqoridagi tekshiruv
    #     qulfdan OLDIN: biz qulfni kutayotganda parallel tuzatish commit qilgan
    #     bo'lsa, eski javob bilan davom etib uni jimgina teskari qilardik.
    _lock_guard(db, emp, pur)
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

    def _c2(v):
        """Tannarxni ustun aniqligida (NUMERIC(14,2)) solishtirish uchun kvantlash.

        Float bilan solishtirish («700.0 != 700.00») har saqlashda «narx o'zgardi»
        deb yolg'on ko'rsatardi — va shu bilan tegilmagan qatorni ham rad etardi.
        """
        return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _reconcile(product_id, delta, cost):
        """inv.qty += delta (ishorali); tuzatish harakati qo'shiladi. Qoldiq manfiy bo'lmasin."""
        if delta == 0:
            return
        # ⚠️  PARTIYA DARVOZASI (eng tor joy — HAR chaqiruv shu yerdan o'tadi).
        #     Tahrir qoldiqni ISHORALI delta bilan siljitadi va qaysi partiya
        #     o'zgarishini bilmaydi. Kuzatuvli mahsulotда bu Phase 2/3 ishi.
        from app.services import stock_gate as _SGe
        _SGe.http_assert_untracked(db, [product_id], "xarid tahriri")
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

    # ⚠️  PARTIYALI QATORDA TANNARX MUZLAGAN — TAHRIR RAD ETILADI.
    #     Miqdor o'zgarishi va qatorni o'chirish allaqachon `_reconcile` ichidagi
    #     darvozadan 409 oladi, lekin FAQAT TANNARX o'zgarishi delta=0 bo'lgani
    #     uchun darvozagacha YETIB BORMASDI: `PurchaseItem.unit_cost` yangilanib,
    #     `StockBatch.unit_cost` ESKI qolardi — bir hujjatda ikki xil tannarx,
    #     ya'ni COGS va yetkazib beruvchi qarzi jimgina ajralardi.
    #     Bayroq QULFDAN KEYIN, bazadan QAYTA o'qiladi (`tracked_ids`): parallel
    #     `/lots/enable` shu orada yoqilgan bo'lsa, eski (keshlangan) qiymat
    #     tahrirni o'tkazib yuborardi.
    from app.services import stock_gate as _SGc
    _narx_pid = {existing[upd.id].product_id for upd in data.items
                 if upd.id in existing
                 and _c2(upd.unit_cost) != _c2(existing[upd.id].unit_cost)}
    if _narx_pid:
        for _pid in sorted(_SGc.tracked_ids(db, _narx_pid), key=str):
            # ⚠️  MASLAHAT BAJARILADIGAN BO'LSIN (Phase 5C review, C-2). Ilgari bu yerda
            #     «kirimni bekor qilib, qayta qabul qiling» deyilardi — lekin kuzatuvli
            #     qatorni o'chirish HAM shu endpointda `stock_gate` bilan 409 oladi:
            #     operator ikkinchi, boshqacha rad javobiga borardi.
            raise HTTPException(409, f"'{_pname(_pid)}' partiya bo'yicha "
                                     f"kuzatiladi — kirim narxini tahrirlab bo'lmaydi: partiya "
                                     f"tannarxi qabul paytida yozilgan va hujjat bilan jimgina "
                                     f"ajralib qolardi. Kuzatuvli hujjat hozircha bekor ham "
                                     f"qilinmaydi — tuzatish uchun qo'llab-quvvatlashga "
                                     f"murojaat qiling.")

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
        # §2 PURCHASE CUSTODY: post-T0 naqd xarid AYNAN fizik custody hisobini talab qiladi.
        # Smena bor -> manba = shift.till_id. Smenasiz bo'lsa -> HOZIRCHA FAIL-CLOSED: filial
        # bo'yicha TAXMIN QILINMAYDI (ilgari branch-guess qilinardi yoki JIMGINA ledger'siz
        # o'tib ketardi). Explicit cash_account_id so'rov shakli — keyingi qadam (docs).
        from app.models.enums import ShiftStatus as _ShSt3
        from app.models.shifts import Shift as _Shift3
        from app.services.cash import cutover_guard as _cg
        _psh = (db.query(_Shift3).filter(_Shift3.cashier_id == emp.id,
                                         _Shift3.status == _ShSt3.open).first())
        # §2: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT cash_account_id.
        _pacc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id, branch_id=pur.branch_id,
                                            operation="purchase_return_cash", shift=_psh,
                                            cash_account_id=data.cash_account_id)
        _cr.on_purchase_return(db, emp, branch_id=pur.branch_id, purchase_id=pur.id,
                               purchase_return_id=pr.id, cash_amount=_ret_amt,
                               cash_account_id=(_pacc.id if _pacc else None))
        if _pacc is not None:
            pr.cash_account_id = _pacc.id           # §5 audit identity
            db.add(pr)
    elif not _charged and _ret_amt < 0:
        # NAQD (received) xarid summasi OSHIRILDI (new_total > paid) -> QO'SHIMCHA fizik naqd chiqadi.
        # Asl OUT·PURCHASE_OUT (leg-0) O'ZGARMAYDI; delta (new_total - paid) yangi leg (>=1) sifatida
        # yoziladi (immutable append; leg-0 bilan to'qnashmaydi; original ikki marta hisoblanmaydi).
        # Idempotent: retry'да pur.total==new_total -> paid==new_total -> _ret_amt==0 -> yozilmaydi.
        # Ко'р: app/db/cash/PURCHASE_RETURN_identity.md (simmetrik decrease tomoni).
        from app.services.cash import retrofit as _cr
        # §2 PURCHASE CUSTODY: post-T0 naqd xarid AYNAN fizik custody hisobini talab qiladi.
        # Smena bor -> manba = shift.till_id. Smenasiz bo'lsa -> HOZIRCHA FAIL-CLOSED: filial
        # bo'yicha TAXMIN QILINMAYDI (ilgari branch-guess qilinardi yoki JIMGINA ledger'siz
        # o'tib ketardi). Explicit cash_account_id so'rov shakli — keyingi qadam (docs).
        from app.models.enums import ShiftStatus as _ShSt3
        from app.models.shifts import Shift as _Shift3
        from app.services.cash import cutover_guard as _cg
        _psh = (db.query(_Shift3).filter(_Shift3.cashier_id == emp.id,
                                         _Shift3.status == _ShSt3.open).first())
        # §2: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT cash_account_id.
        _pacc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id, branch_id=pur.branch_id,
                                            operation="cash_purchase_increase", shift=_psh,
                                            cash_account_id=data.cash_account_id)
        _cr.on_cash_purchase_increase(db, emp, branch_id=pur.branch_id, purchase_id=pur.id,
                                      extra_amount=(new_total - paid),
                                      cash_account_id=(_pacc.id if _pacc else None))

    db.commit()
    return {"ok": True, "id": str(pur.id), "total": float(new_total),
            "cancelled": len(remaining) == 0, "status": pur.status.value}


class SupplierPaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    method: str = "cash"
    client_uuid: uuid.UUID | None = None   # offline idempotentlik (qayta yuborishда ikki marta to'lamaslik)
    # §1 EXPLICIT CUSTODY: smenasiz naqd amali uchun fizik hisob (TILL yoki SAFE) AYNAN
    # ko'rsatiladi. Ochiq smena bo'lsa server shift.till_id ni ishlatadi va bu maydon unga
    # TENG bo'lishi kerak (override QILIB BO'LMAYDI). Legacy/pre-T0 uchun nullable.
    cash_account_id: uuid.UUID | None = None


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
            # §7 IDEMPOTENTLIK KONFLIKTI: AYNI source (client_uuid) qayta yuborilsa, LEKIN BOSHQA
            # custody hisobi bilan kelsa -> BALAND OVOZDA rad. Jimgina yangi hisobga post qilish
            # yoki eskisini jimgina saqlab qolish IKKALASI ham noto'g'ri (audit yolg'on bo'lardi).
            if (data.cash_account_id is not None and ex.cash_account_id is not None
                    and str(data.cash_account_id) != str(ex.cash_account_id)):
                from app.services.cash import cutover_guard as _cg0
                raise HTTPException(409, f"{_cg0.ERR_CUSTODY_INVALID}: bu amal allaqachon boshqa naqd "
                                         f"hisob bilan yozilgan ({ex.cash_account_id}) — qayta yuborishda "
                                         "hisobni o'zgartirib bo'lmaydi.")
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
        from app.models.shifts import CashMovement as _CM
        from app.services.cash import custody_preview as _CP
        # §8 T0 GUARD (_sh HAL QILINGACH): post-T0 naqd ta'minotchi to'lovi fizik custody hisobini
        # TALAB qiladi (smenasiz naqd chiqishi custody yozuvisiz qolmasin).
        from app.services.cash import cutover_guard as _cg
        # §2 FILIAL DOIRASI (Phase 5G, `customers.pay_credit` tuzatishining AYNI o'zi): smenasiz
        # holatda custody filiali = `actor_branch`. Ilgari bu yerga `None` uzatilardi va
        # `require_custody_account` filial tekshiruvini O'TKAZIB YUBORARDI — ya'ni do'kondagi
        # ISTALGAN filialning TILL/SAFE hisobidan naqd chiqarib yuborish mumkin edi.
        # ⚠️  Smena va custody filiali YAGONA yordamchidan (`custody_preview.supplier_payment_ctx`):
        #     `GET /cash/custody-preview?operation=supplier_payment` AYNI kontekstni quruq yuritadi.
        _cust_br, _sh = _CP.supplier_payment_ctx(db, emp)
        _sp_acc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id,
                                              branch_id=_cust_br,
                                              operation=_CP.OP_SUPPLIER, shift=_sh,
                                              cash_account_id=data.cash_account_id)
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
        _cr.on_supplier_payment(db, emp, branch_id=(_sh.branch_id if _sh else None),
                                payment_id=pay.id, cash_amount=amt,
                                cash_account_id=(_sp_acc.id if _sp_acc else None))
        if _sp_acc is not None:
            pay.cash_account_id = _sp_acc.id        # §5 audit identity
            db.add(pay)
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
    recent = [
        {"id": str(p.id), "doc_no": p.doc_no, "date": p.purchase_date.isoformat(),
         "total": float(p.total), "status": p.status.value}
        for p in purchases[:40]
    ]

    # Yetkazgan mahsulotlar (agregat: nom + jami miqdor + jami summa + kutilayotgan foyda)
    prod_rows = (
        db.query(Product.id, Product.name,
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
    # ⚠️  IKKI MANBA — IKKI XIL RAQAM. `purchase_items` ni tuzatish ATAYLAB
    #     o'zgartirmaydi (ular «aslida nima yozilgan» ning yozuvi), faqat hosila
    #     `Purchase.total` siljiydi. Shu bois hisobotning ikki tomoni ajralib
    #     ketardi: hujjat jami TUZATILGAN, mahsulot ustuni esa TUZATILMAGAN —
    #     va marja YOLG'ON chiqardi. Endi IKKALA tomon ham AYNI qatorlardan
    #     tug'iladi: mahsulot agregati + tuzatish deltasi (`lot_correction`
    #     bilan AYNI hisob), jami esa shu ustunning YIG'INDISI.
    from app.services import lot_correction as _LC
    deltas = _LC.deltas_by_product(db, emp.company_id, [p.id for p in purchases])
    products = []
    total_qty = 0.0
    expected_profit = 0.0
    total_purchased = 0.0
    for pid, name, qty, cost, sell in prod_rows:
        q = float(qty or 0)
        c = float(Decimal(str(cost or 0)) + deltas.get(str(pid), Decimal("0")))
        s = float(sell or 0)
        prof = q * s - c   # joriy sotuv narxida olib kelingan tovardan kutilayotgan foyda
        products.append({"name": name, "qty": q, "cost": c, "profit": prof})
        total_qty += q
        expected_profit += prof
        total_purchased += c

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
