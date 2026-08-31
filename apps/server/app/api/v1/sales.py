import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import MovementType, ReturnReason
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.sales import Return, ReturnItem, Sale
from app.schemas.sales import ReturnCreate, SaleCreate, SaleOut
from app.services.sales import create_sale

router = APIRouter(tags=["sales"])


def _period_start_utc(db: Session, company_id, period: str | None):
    """'today|week|month' boshlanishi — DO'KON mahalliy vaqti bo'yicha (UTC emas).
    Ilgari UTC yarim tun ishlatilib, hisobotlar bilan ~5-6 soat farq chiqardi."""
    if not period or period in ("all",):
        return None
    from datetime import timedelta as _td

    from app.api.v1.reports import _store_tz
    LOCAL = _store_tz(db, company_id)
    now_l = datetime.now(timezone.utc).astimezone(LOCAL)
    if period == "today":
        s = now_l.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        # "Hafta" = so'nggi 7 MAHALLIY kun (bugun + oldingi 6) — reports._window/dashboard bilan
        # izchil (ilgari ISO-dushanba edi -> bir xil "hafta" jami ekranlarда har xil chiqаrdi).
        s = now_l.replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=6)
    elif period == "month":
        s = now_l.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return None
    return s.astimezone(timezone.utc)


@router.post("/sales", response_model=SaleOut)
def new_sale(
    data: SaleCreate,
    emp: Employee = Depends(require("kassa.sell")),
    db: Session = Depends(get_db),
):
    return create_sale(db, emp, data)


@router.get("/sales/summary")
def sales_summary(
    method: str | None = None,
    cashier: str | None = None,
    period: str | None = None,
    current_shift: bool = False,
    q: str | None = None,
    emp: Employee = Depends(require("sotuvlar.view")),
    db: Session = Depends(get_db),
):
    from datetime import timedelta

    from app.models.auth import Employee as Emp
    from app.models.sales import SalePayment

    from app.core.deps import visible_branches
    base = db.query(Sale).filter(Sale.company_id == emp.company_id, Sale.deleted_at.is_(None))
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali savdosi
    if _bset is not None:
        base = base.filter(Sale.branch_id.in_(_bset))
    if q:
        from app.core.validate import like_escape as _le
        base = base.filter(Sale.receipt_no.ilike(f"%{_le(q)}%", escape="\\"))
    if cashier:
        cids = db.query(Emp.id).filter(Emp.full_name == cashier).subquery()
        base = base.filter(Sale.cashier_id.in_(db.query(cids.c.id)))
    if method:
        mq = db.query(SalePayment.sale_id).filter(SalePayment.method_code == method).subquery()
        base = base.filter(Sale.id.in_(db.query(mq.c.sale_id)))
    if current_shift:
        from app.models.enums import ShiftStatus as _SS
        from app.models.shifts import Shift as _Shift
        _sh = db.query(_Shift).filter(_Shift.cashier_id == emp.id, _Shift.status == _SS.open).first()
        if not _sh:
            return {"count": 0, "total": 0.0, "by_method": {}}
        base = base.filter(Sale.shift_id == _sh.id)
    if period:
        startp = _period_start_utc(db, emp.company_id, period)
        if startp:
            base = base.filter(Sale.sold_at >= startp)
    total = float(base.with_entities(func.coalesce(func.sum(Sale.total), 0)).scalar() or 0)
    count = base.with_entities(func.count(Sale.id)).scalar() or 0
    # IN(ids) o'rniga subquery-join — katta ma'lumotda ham bitta SQL (SQLite 999-limitiga urilmaydi)
    ids_sq = base.with_entities(Sale.id).subquery()
    rows = (
        db.query(SalePayment.method_code, func.coalesce(func.sum(SalePayment.amount), 0))
        .filter(SalePayment.sale_id.in_(db.query(ids_sq.c.id)))
        .group_by(SalePayment.method_code)
        .all()
    )
    by_method = {m: float(a) for m, a in rows}
    return {"count": count, "total": total, "by_method": by_method}


@router.get("/sales/cashiers")
def sale_cashiers(emp: Employee = Depends(require("sotuvlar.view")), db: Session = Depends(get_db)):
    from app.models.auth import Employee as Emp

    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)
    q = (
        db.query(Emp.full_name)
        .join(Sale, Sale.cashier_id == Emp.id)
        .filter(Sale.company_id == emp.company_id)
    )
    if _bset is not None:
        q = q.filter(Sale.branch_id.in_(_bset))
    return [r[0] for r in q.distinct().all()]


@router.get("/sales")
def list_sales(
    limit: int = 50,
    method: str | None = None,
    cashier: str | None = None,
    period: str | None = None,   # today | week | month
    current_shift: bool = False,  # faqat kassirning ochiq smenasi (Sotuvlarim)
    q: str | None = None,
    emp: Employee = Depends(require("sotuvlar.view")),
    db: Session = Depends(get_db),
):
    from datetime import timedelta

    from app.models.auth import Employee as Emp
    from app.models.sales import SaleItem, SalePayment

    from app.core.deps import visible_branches
    query = (
        db.query(Sale, Emp.full_name)
        .join(Emp, Emp.id == Sale.cashier_id)
        .filter(Sale.company_id == emp.company_id, Sale.deleted_at.is_(None))
    )
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali savdosi
    if _bset is not None:
        query = query.filter(Sale.branch_id.in_(_bset))
    if current_shift:
        from app.models.enums import ShiftStatus as _SS
        from app.models.shifts import Shift as _Shift
        _sh = db.query(_Shift).filter(_Shift.cashier_id == emp.id, _Shift.status == _SS.open).first()
        if not _sh:
            return []
        query = query.filter(Sale.shift_id == _sh.id)
    if q:
        from app.core.validate import like_escape as _le
        query = query.filter(Sale.receipt_no.ilike(f"%{_le(q)}%", escape="\\"))
    if cashier:
        query = query.filter(Emp.full_name == cashier)
    if method:
        mq = db.query(SalePayment.sale_id).filter(SalePayment.method_code == method).subquery()
        query = query.filter(Sale.id.in_(db.query(mq.c.sale_id)))
    if period:
        start = _period_start_utc(db, emp.company_id, period)
        if start:
            query = query.filter(Sale.sold_at >= start)
    rows = query.order_by(Sale.sold_at.desc()).limit(min(limit, 300)).all()

    # N+1 EMAS: to'lov usuli, miqdor va birinchi mahsulot BITTA-BITTA guruh so'rov bilan (300 satr
    # uchun 900 emas 3 so'rov). Ilgari har satrga 3 so'rov ketardi.
    _ids = [s.id for s, _ in rows]
    pay_map: dict = {}
    qty_map: dict = {}
    name_map: dict = {}
    if _ids:
        for sid, mc in db.query(SalePayment.sale_id, SalePayment.method_code).filter(SalePayment.sale_id.in_(_ids)).all():
            pay_map.setdefault(sid, mc)   # birinchi usul
        qty_map = {sid: float(q or 0) for sid, q in
                   db.query(SaleItem.sale_id, func.coalesce(func.sum(SaleItem.qty), 0))
                   .filter(SaleItem.sale_id.in_(_ids)).group_by(SaleItem.sale_id).all()}
        for sid, nm in db.query(SaleItem.sale_id, SaleItem.name_snapshot).filter(SaleItem.sale_id.in_(_ids)).all():
            name_map.setdefault(sid, nm)  # birinchi mahsulot
    out = []
    for s, cashier_name in rows:
        out.append({
            "id": str(s.id),
            "receipt_no": s.receipt_no,
            "sold_at": s.sold_at,
            "cashier": cashier_name,
            "method": pay_map.get(s.id, "cash"),
            "item_count": qty_map.get(s.id, 0.0),
            "first_item": name_map.get(s.id, ""),
            "total": float(s.total),
        })
    return out


@router.get("/sales/find")
def find_sale(
    q: str,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Chekni UID (barcode) yoki chek raqami bo'yicha topish — Qaytarishlar uchun.
    Har mahsulot barcode'i bilan (skanerlab tasdiqlash uchun)."""
    from app.models.auth import Employee as Emp
    from app.models.catalog import ProductBarcode
    from app.models.sales import SaleItem, SalePayment

    from app.core.deps import visible_branches
    term = q.strip().lstrip("#")
    if not term:
        raise HTTPException(400, "Bo'sh so'rov")
    _bset = visible_branches(emp, db)  # boshqa filial chekini topib qaytarib bo'lmasin
    sale = (
        db.query(Sale)
        .filter(
            Sale.company_id == emp.company_id,
            Sale.deleted_at.is_(None),
            (Sale.uid == term) | (Sale.receipt_no == term) | (Sale.receipt_no == "#" + term),
            *((Sale.branch_id.in_(_bset),) if _bset is not None else ()),
        )
        .first()
    )
    if not sale:
        raise HTTPException(404, "Chek topilmadi")
    cashier = db.query(Emp.full_name).filter(Emp.id == sale.cashier_id).scalar()
    method = db.query(SalePayment.method_code).filter(SalePayment.sale_id == sale.id).first()
    items = []
    for it in db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all():
        # BARCHA barcode'lar — mahsulotning istalgan kodi skanersa mos kelsin
        bcs = [b[0] for b in db.query(ProductBarcode.barcode)
               .filter(ProductBarcode.product_id == it.product_id).all()]
        items.append({
            "product_id": str(it.product_id),
            "name": it.name_snapshot,
            "qty": float(it.qty),
            "unit_price": float(it.unit_price),
            "barcode": bcs[0] if bcs else "",   # eski klientlar uchun
            "barcodes": bcs,
        })
    return {
        "id": str(sale.id), "receipt_no": sale.receipt_no, "uid": sale.uid or "",
        "method": method[0] if method else "cash", "sold_at": sale.sold_at,
        "cashier": cashier, "total": float(sale.total), "items": items,
    }


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    from app.core.deps import visible_branches
    sale = db.get(Sale, sale_id)
    if not sale or sale.company_id != emp.company_id:
        raise HTTPException(404, "Chek topilmadi")
    _bset = visible_branches(emp, db)  # boshqa filial chekini id bo'yicha ochib bo'lmasin (IDOR)
    if _bset is not None and sale.branch_id not in _bset:
        raise HTTPException(404, "Chek topilmadi")
    return sale


@router.get("/returns")
def list_returns(
    period: str = "month",
    emp: Employee = Depends(require("qaytarishlar.view")),
    db: Session = Depends(get_db),
):
    """Ega/menejer NAZORATI: qabul qilingan qaytarishlar tarixi (ro'yxat + KPI).
    period: today | week | month | all."""
    # Davr do'kon MAHALLIY kalendari bo'yicha (hisobotlar bilan izchil — ilgari UTC + rolling edi).
    from app.api.v1.reports import _window
    start, _end = _window(db, emp.company_id, period)

    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)  # filialга bog'langan — faqat o'z filiali qaytarishlari
    _rb = (Return.branch_id.in_(_bset),) if _bset is not None else ()
    rets = (
        db.query(Return)
        .filter(Return.company_id == emp.company_id, Return.deleted_at.is_(None), Return.created_at >= start, *_rb)
        .order_by(Return.created_at.desc()).limit(300).all()
    )
    from app.models.customers import Customer
    ids = [r.id for r in rets]
    cash = {e.id: e.full_name for e in db.query(Employee).filter(Employee.company_id == emp.company_id).all()}
    sale_ids = [r.original_sale_id for r in rets if r.original_sale_id]
    receipts = ({s.id: s.receipt_no for s in db.query(Sale.id, Sale.receipt_no).filter(Sale.id.in_(sale_ids)).all()}
                if sale_ids else {})
    cust_ids = [r.customer_id for r in rets if r.customer_id]
    custs = ({cu.id: cu.full_name for cu in db.query(Customer.id, Customer.full_name).filter(Customer.id.in_(cust_ids)).all()}
             if cust_ids else {})
    items_map: dict = {}
    if ids:
        ri_rows = db.query(ReturnItem).filter(ReturnItem.return_id.in_(ids)).all()
        pids = {ri.product_id for ri in ri_rows}
        prod = ({p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.id.in_(pids)).all()}
                if pids else {})
        for ri in ri_rows:
            items_map.setdefault(ri.return_id, []).append({
                "name": prod.get(ri.product_id, "?"), "qty": float(ri.qty),
                "unit_price": float(ri.unit_price), "line_total": float(ri.line_total)})

    # KPI — ro'yxat 300-limitidan MUSTAQIL (butun davr bo'yicha agregat)
    _base = db.query(Return).filter(
        Return.company_id == emp.company_id, Return.deleted_at.is_(None), Return.created_at >= start, *_rb)
    kpi_count = _base.count()
    kpi_total = float(_base.with_entities(func.coalesce(func.sum(Return.total), 0)).scalar() or 0)
    restocked = _base.filter(Return.restock.is_(True)).count()
    writeoff = kpi_count - restocked

    out = []
    by_reason: dict = {}
    for r in rets:
        rc = r.reason.value if hasattr(r.reason, "value") else str(r.reason)
        by_reason[rc] = by_reason.get(rc, 0) + 1
        out.append({
            "id": str(r.id), "return_no": r.return_no, "at": r.created_at,
            "cashier": cash.get(r.cashier_id), "receipt_no": receipts.get(r.original_sale_id),
            "customer": custs.get(r.customer_id), "note": r.note,
            "reason": rc, "refund_method": r.refund_method, "total": float(r.total),
            "restock": bool(r.restock), "items": items_map.get(r.id, []),
        })
    return {
        "kpi": {"count": kpi_count, "total": kpi_total, "restocked": restocked, "writeoff": writeoff},
        "by_reason": by_reason, "returns": out,
    }


@router.post("/returns")
def create_return(
    data: ReturnCreate,
    emp: Employee = Depends(require("qaytarishlar.create")),
    db: Session = Depends(get_db),
):
    from app.models.customers import CreditTransaction, Customer
    from app.models.enums import CashMovementType, CreditTxnType, SaleStatus, ShiftStatus
    from app.models.sales import SaleItem
    from app.models.shifts import CashMovement, Shift

    # Idempotentlik — offline kassa qayta yuborsa ikki marta yozilmaydi
    if data.client_uuid:
        ex = db.query(Return).filter(
            Return.client_uuid == data.client_uuid, Return.company_id == emp.company_id
        ).first()
        if ex:
            return {"id": str(ex.id), "return_no": ex.return_no, "total": float(ex.total)}

    # Sabab enum'ini oldindan tekshiramiz — yaroqsiz qiymat 500 emas, 400 qaytarsin
    try:
        _reason = ReturnReason(data.reason)
    except ValueError:
        raise HTTPException(400, f"Noto'g'ri qaytarish sababi: {data.reason}")
    # Qaytarish to'lov usuli — faqat ruxsat etilgan qiymatlar (aks holда axlat yozilardi)
    if data.refund_method not in {"cash", "card", "qr", "credit"}:
        raise HTTPException(400, "Noto'g'ri qaytarish to'lov usuli")

    if not data.items:
        raise HTTPException(400, "Qaytarish uchun mahsulot tanlanmagan")
    for i in data.items:
        if i.qty <= 0:
            raise HTTPException(400, "Qaytarish miqdori noto'g'ri")

    # ── Xavfsizlik nazorati (soxta naqd qaytarishga qarshi) ──
    # Chek raqamisiz (asl chek tanlanmagan) qaytarishda miqdor cheklanmaydi. Agar bunday
    # qaytarish NAQD bo'lsa, kassir soxta "100000 dona qaytdi" yozib kassadan pul chiqarishi
    # mumkin edi. Shu sababli naqd pul qaytarish uchun asl chek MAJBURIY. Chek-siz qaytarish
    # faqat pulsiz (omborga qaytarish / restock) holatida ruxsat etiladi.
    if data.original_sale_id is None and data.refund_method == "cash":
        raise HTTPException(400, "Naqd qaytarish uchun asl chekni tanlang — chek raqamisiz naqd qaytarish mumkin emas")

    from app.core.deps import actor_branch
    branch = (actor_branch(emp, db)  # qaytarish xodim filialiga yoziladi (ko'p-filialда to'g'ri)
              or db.query(Branch).filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None)).first())
    now = datetime.now(timezone.utc)

    # Asl chek bo'yicha limit: har mahsulot uchun (sotilgan − oldin qaytarilgan) dan oshmasin
    original = None
    if data.original_sale_id:
        # QATOR QULFI: bir chekni bir vaqtда ikki marta (turli client_uuid bilan) qaytарish
        # "sotilгандан oshмасин" tekshiруvини chetlab o'tиб ikki marta pul/restок berardi (TOCTOU).
        # Asl chekni qulflaymiz — shu chekка qaytаришлар KETMA-KET bajarилади.
        original = (db.query(Sale).filter(Sale.id == data.original_sale_id)
                    .with_for_update().first())
        if not original or original.company_id != emp.company_id:
            raise HTTPException(404, "Asl chek topilmadi")
        # Filial izolyatsiyasi: boshqa filial chekiga qaytarish yozib bo'lmaydi (IDOR + ombor
        # noto'g'ri filialга tushardi). get_sale/find_sale kabi visible_branches bilan cheklaymiz.
        from app.core.deps import visible_branches
        _vb = visible_branches(emp, db)
        if _vb is not None and original.branch_id not in _vb:
            raise HTTPException(404, "Asl chek topilmadi")
        # ── Soxta naqд qaytarishga qarshi (nasiya) ──
        # Nasiyaga (qarzga) olingan, hali TO'LANMAGAN chek naqд/karta qaytarilса — kassadан pul
        # chiqib ketardi, mijoz esa qarzдор qolаверарди (do'kon ikki marta zarar). Bunday chekни
        # faqat 'qarz' usulида qaytarish mumkin (mijoz qarзидан ayiriladi). Chek nasiya bo'lmаса
        # yoki qarз allaqачон to'langan bo'lса (balans <= 0) — oddiy qaytarish.
        if data.refund_method != "credit" and original.customer_id:
            from app.models.sales import SalePayment as _SP
            _credit_charge = db.query(func.coalesce(func.sum(_SP.amount), 0)).filter(
                _SP.sale_id == original.id, _SP.method_code == "credit").scalar() or 0
            if Decimal(str(_credit_charge)) > 0:
                _cust0 = db.get(Customer, original.customer_id)
                if _cust0 and Decimal(str(_cust0.credit_balance)) > 0:
                    raise HTTPException(400, "Nasiya (qarz) chek to'lanmаган — qaytarish usuli 'qarz' bo'lishi kerak (mijoz qarзидан ayiriladi)")
        sold: dict = {}
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            sold[si.product_id] = sold.get(si.product_id, Decimal("0")) + Decimal(str(si.qty))
        prev_returns = db.query(Return.id).filter(Return.original_sale_id == original.id).all()
        prev_ids = [r[0] for r in prev_returns]
        if prev_ids:
            for ri in db.query(ReturnItem).filter(ReturnItem.return_id.in_(prev_ids)).all():
                sold[ri.product_id] = sold.get(ri.product_id, Decimal("0")) - Decimal(str(ri.qty))
        want: dict = {}
        for i in data.items:
            want[i.product_id] = want.get(i.product_id, Decimal("0")) + Decimal(str(i.qty))
        for _pid, _wq in want.items():
            left = sold.get(_pid)
            if left is None:
                raise HTTPException(400, "Mahsulot bu chekda yo'q")
            if _wq > left:
                raise HTTPException(400, f"Qaytarish miqdori sotilganidan oshiq (qoldi: {left})")

    # Qaytariladigan birlik narxi asl chek snapshotidan olinadi (mijoz yuborgan narxga ishonilmaydi);
    # chek chegirmasi proporsional hisobga olinadi -> qaytarilgan summa to'langanidan oshmaydi.
    eff_unit: dict = {}
    if original is not None:
        agg: dict = {}
        sum_lines = Decimal("0")
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            q, l = agg.get(si.product_id, (Decimal("0"), Decimal("0")))
            agg[si.product_id] = (q + Decimal(str(si.qty)), l + Decimal(str(si.line_total)))
            sum_lines += Decimal(str(si.line_total))
        # line_total allaqachon mahsulot chegirmasini hisobga olgan; ratio faqat chek (header) chegirmasini proporsional taqsimlaydi
        ratio = (Decimal(str(original.total)) / sum_lines) if sum_lines > 0 else Decimal("1")
        for pid, (q, l) in agg.items():
            eff_unit[pid] = (l / q * ratio) if q > 0 else Decimal("0")

    sell_of: dict = {}  # chek-siz qaytarish narx-shifti (mahsulotning joriy sotish narxi)

    def _unit(i):
        if original is not None:
            return eff_unit.get(i.product_id, Decimal("0"))
        # CHEK YO'Q: mijoz narxni ixtiyoriy yubora olmaydi — aks holda kassadan cheksiz pul
        # chiqarish mumkin edi. Narx mahsulotning joriy sotish narxidan OSHMAYDI.
        u = Decimal(str(i.unit_price))
        cap = sell_of.get(i.product_id, Decimal("0"))
        if cap > 0 and u > cap:
            u = cap
        return u

    # Har product_id haqiqiy va SHU kompaniyaniki bo'lishi shart (ghost/begona -> 400).
    for i in data.items:
        _pr = db.get(Product, i.product_id)
        if not _pr or _pr.company_id != emp.company_id or _pr.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        sell_of[i.product_id] = Decimal(str(_pr.base_sell_price))

    # Tannarx snapshoti — hisobotlarda qaytarilgan COGS to'g'ri netlanishi uchun SHART.
    # Asl chekdan (SaleItem.unit_cost), bo'lmasa mahsulotning joriy olish narxidan.
    cost_of: dict = {}
    if original is not None:
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            cost_of[si.product_id] = Decimal(str(si.unit_cost))
    for i in data.items:
        if i.product_id not in cost_of:
            _pr = db.get(Product, i.product_id)
            cost_of[i.product_id] = Decimal(str(_pr.base_buy_price)) if _pr else Decimal("0")

    # Qaytarish summasi BUTUN som'да (tarozi kasr qiymati — naqd yarim-som bo'lmaydi; sotuv ham
    # butun som'ga yaxlitlaydi, izchillik uchun ROUND_HALF_UP).
    from decimal import ROUND_HALF_UP as _RHU
    total = sum((Decimal(str(i.qty)) * _unit(i) for i in data.items), Decimal("0")).quantize(Decimal("1"), rounding=_RHU)

    # ── Qaytarish usuli asl chek TENDERIga cheklanadi (kredit BO'LMAGAN cheklар uchun) ──
    # Karta/QR bilan to'langan chekni NAQD qaytarib kassadан pul chiqариб ketиш (yoki split
    # chekда naqд qismдан ortiq naqд qaytarish) mumkin edi — kassa haqiqатда olинмаган pulни
    # yo'qotardi, smena/kassa hisobi buzиларди. Har usul (cash/card/qr) uchun: shu usulда
    # to'langan − shu usulда oldin qaytарilган ≥ hozirgi qaytarish. Kredit cheklarни yuqoridаги
    # nasiya guard boshqaradi (to'langan qarз naqди CustomerPayment bo'lgani uchun bu yerда emas).
    if original is not None and data.refund_method in ("cash", "card", "qr"):
        from app.models.sales import SalePayment as _SPm
        _has_credit = db.query(_SPm.id).filter(
            _SPm.sale_id == original.id, _SPm.method_code == "credit").first()
        if not _has_credit:
            _paid_m = db.query(func.coalesce(func.sum(_SPm.amount), 0)).filter(
                _SPm.sale_id == original.id, _SPm.method_code == data.refund_method).scalar() or 0
            _prev_m = db.query(func.coalesce(func.sum(Return.total), 0)).filter(
                Return.original_sale_id == original.id,
                Return.refund_method == data.refund_method).scalar() or 0
            _avail_m = Decimal(str(_paid_m)) - Decimal(str(_prev_m))
            if total > _avail_m + Decimal("0.5"):
                raise HTTPException(400, f"'{data.refund_method}' usulида qaytариш mumkin summадан oshди (mavjud: {_avail_m:g}) — asl chek shu usulда shuncha to'langан")

    seq = db.query(Return).filter(Return.company_id == emp.company_id).count()
    ret = Return(
        return_no=f"QAY-{1000 + seq + 1}",
        original_sale_id=data.original_sale_id,
        company_id=emp.company_id,
        branch_id=branch.id,
        cashier_id=emp.id,
        # Mijoz asl chekdan ko'chiriladi — Qaytarishlar nazoratida ko'rinishi uchun
        # (ilgari hech qachon yozilmas edi, "Mijoz" doim bo'sh chiqardi)
        customer_id=original.customer_id if original else None,
        reason=_reason,
        restock=data.restock,
        refund_method=data.refund_method,
        total=total,
        client_uuid=data.client_uuid,
    )
    db.add(ret)
    db.flush()
    # QATOR QULFI (deadlock + lost-update oldini olish): qaytarish tegадиган Inventory qatorlarини
    # DASTAVVAL bir xil GLOBAL tartибда (product_id) qulflaymiz — sotuv/writeoff/boshqa qaytarish
    # bilan bir vaqtда restock/writeoff STALE qoldiqни yozиб yo'qotмасин.
    for _pid in sorted({i.product_id for i in data.items}, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for i in data.items:
        u = _unit(i)
        line = Decimal(str(i.qty)) * u
        db.add(
            ReturnItem(
                return_id=ret.id,
                product_id=i.product_id,
                qty=i.qty,
                unit_price=u,
                unit_cost=cost_of.get(i.product_id, Decimal("0")),
                line_total=line,
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
        if data.restock:  # omborga qaytdi
            inv.qty = Decimal(str(inv.qty)) + Decimal(str(i.qty))
            inv.updated_at = now
            db.add(
                StockMovement(
                    product_id=i.product_id,
                    branch_id=branch.id,
                    type=MovementType.return_in,
                    qty=Decimal(str(i.qty)),
                    balance_after=inv.qty,
                    ref_type="return",
                    ref_id=ret.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )
        else:  # mol qaytdi, lekin yaroqsiz — hisobdan chiqariladi
            # Inventarni HAQIQATAN o'zgartiramiz (return_in +qty, keyin writeoff -qty), shunda
            # balance_after == o'sha paytdagi Inventory.qty (fantom qoldiq bo'lmaydi). Net = 0.
            inv.qty = Decimal(str(inv.qty)) + Decimal(str(i.qty))
            inv.updated_at = now
            db.add(
                StockMovement(
                    product_id=i.product_id,
                    branch_id=branch.id,
                    type=MovementType.return_in,
                    qty=Decimal(str(i.qty)),
                    balance_after=inv.qty,
                    ref_type="return",
                    ref_id=ret.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )
            inv.qty = Decimal(str(inv.qty)) - Decimal(str(i.qty))
            inv.updated_at = now
            db.add(
                StockMovement(
                    product_id=i.product_id,
                    branch_id=branch.id,
                    type=MovementType.writeoff,
                    qty=Decimal(str(-i.qty)),
                    balance_after=inv.qty,
                    ref_type="return",
                    ref_id=ret.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )

    # Naqd qaytarish — kassirning ochiq smenasidan chiqim (g'azna hisobi to'g'ri bo'lsin).
    # OCHIQ SMENA SHART: aks holда naqд kassадан chiqади-yu, hech qanday till yozуvи qolмасди
    # (smena "kutilган naqд" bilan haqiqiy kassа mos kelмасди; audit izи yo'q edi).
    if data.refund_method == "cash":
        shift = (
            db.query(Shift)
            .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
            .first()
        )
        if not shift:
            raise HTTPException(400, "Naqd qaytarish uchun ochiq smena kerak — avval smenani oching")
        db.add(
            CashMovement(
                shift_id=shift.id,
                type=CashMovementType.payout,
                amount=total,
                reason=f"Qaytarish {ret.return_no}",
                employee_id=emp.id,
                created_at=now,
            )
        )

    # Nasiya cheki qaytarilsa — mijoz qarzidan ayiriladi
    if data.refund_method == "credit" and original and original.customer_id:
        # QATOR QULFI: bir vaqtда savdo/to'lov bilan balansни STALE o'qib yo'qotmasin.
        cust = (db.query(Customer).filter(Customer.id == original.customer_id)
                .with_for_update().first())
        if cust:
            # 0'га cheklaMAYMIZ: agar qaytarish qarzдан katta bo'lsa, balans MANFIY bo'ladi
            # (do'kon mijozга qarzdor — do'kon krediti). Ilgari max(0) ortiqchani JIMGINA yo'qotardi.
            cust.credit_balance = Decimal(str(cust.credit_balance)) - total
            db.add(
                CreditTransaction(
                    customer_id=cust.id,
                    type=CreditTxnType.adjustment,
                    amount=-total,
                    balance_after=cust.credit_balance,
                    sale_id=original.id,
                    employee_id=emp.id,
                    created_at=now,
                )
            )

    # Asl chek statusi
    db.flush()  # joriy qaytarish qatorlari ham hisobga kirsin (autoflush o'chiq)
    if original is not None:
        sold_total: dict = {}
        for si in db.query(SaleItem).filter(SaleItem.sale_id == original.id).all():
            sold_total[si.product_id] = sold_total.get(si.product_id, Decimal("0")) + Decimal(str(si.qty))
        ret_ids = [r[0] for r in db.query(Return.id).filter(Return.original_sale_id == original.id).all()]
        returned: dict = {}
        for ri in db.query(ReturnItem).filter(ReturnItem.return_id.in_(ret_ids)).all():
            returned[ri.product_id] = returned.get(ri.product_id, Decimal("0")) + Decimal(str(ri.qty))
        fully = all(returned.get(pid, Decimal("0")) >= q for pid, q in sold_total.items())
        original.status = SaleStatus.refunded if fully else SaleStatus.partially_refunded

    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_returns_client_uuid) ushlади:
        # ikki marta pul/restок emas, birinchисининг natijasини qaytaramiz.
        db.rollback()
        if data.client_uuid:
            ex2 = db.query(Return).filter(
                Return.client_uuid == data.client_uuid, Return.company_id == emp.company_id).first()
            if ex2:
                return {"id": str(ex2.id), "return_no": ex2.return_no, "total": float(ex2.total), "duplicate": True}
        raise
    return {"id": str(ret.id), "return_no": ret.return_no, "total": float(total)}
