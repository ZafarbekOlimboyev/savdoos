"""Savdo yaratish — chek + qatorlar (snapshot) + ombor harakati + qarz daftari.

Bitta tranzaksiyada: sale, sale_items (narx/tannarx muzlatiladi), sale_payment,
stock_movements (sale_out), inventory kamayadi, nasiya bo'lsa credit_transactions.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.customers import CreditTransaction, Customer
from app.models.enums import CreditTxnType, MovementType, ShiftStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.sales import Sale, SaleItem, SalePayment
from app.models.shifts import Shift
from app.schemas.sales import SaleCreate


def _D(x) -> Decimal:
    return Decimal(str(x or 0))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_sale(db: Session, emp, data: SaleCreate, at: datetime | None = None) -> Sale:
    # `at` — ixtiyoriy: sotuv vaqtini orqaga sanash uchun (demo/seed). Berilmasa — hozir.
    # 1) Idempotentlik — offline kassa qayta push qilsa ikki marta yozilmaydi
    # (kompaniya bo'yicha cheklangan — boshqa tenant'ning client_uuid'i mos kelmasin)
    if data.client_uuid:
        existing = db.query(Sale).filter(
            Sale.client_uuid == data.client_uuid, Sale.company_id == emp.company_id
        ).first()
        if existing:
            return existing

    if not data.items:
        raise HTTPException(400, "Savat bo'sh")

    # Mijoz berilsa — HAR DOIM shu kompaniyaniki bo'lishi shart (to'lov usulidan qat'i nazar;
    # aks holda naqd savdo begona tenant mijoziga bog'lanib, statistikasini ifloslantirardi).
    if data.customer_id:
        _cust = db.get(Customer, data.customer_id)
        if not _cust or _cust.company_id != emp.company_id:
            raise HTTPException(400, "Mijoz topilmadi")

    if data.payment_method not in {"cash", "card", "qr", "credit"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.payment_method}")

    # Filial: kassir biriktirilgan filial (EmployeeBranch) — bo'lmasa birinchi filial.
    # Ilgari doim birinchi filial olinardi; ko'p-filial do'konda savdo noto'g'ri filialga yozilardi.
    from app.models.auth import EmployeeBranch as _EB
    branch = (
        db.query(Branch)
        .join(_EB, _EB.branch_id == Branch.id)
        .filter(_EB.employee_id == emp.id, Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
        .first()
    ) or (
        db.query(Branch)
        .filter(Branch.company_id == emp.company_id, Branch.deleted_at.is_(None))
        .first()
    )
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    shift = (
        db.query(Shift)
        .filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open)
        .first()
    )
    if shift is None:
        # Sozlamalarda "smena majburiy" yoqilgan bo'lsa — ochiq smenasiz savdo taqiqlanadi
        from app.models.settings import Setting
        _sec = db.query(Setting).filter(
            Setting.company_id == emp.company_id, Setting.key == "security"
        ).first()
        if ((_sec.value if _sec else {}) or {}).get("force_shift"):
            raise HTTPException(400, "Ochiq smena yo'q — avval smenani oching")

    now = at or _now()
    sale = Sale(
        company_id=emp.company_id,
        branch_id=branch.id,
        cashier_id=emp.id,
        shift_id=shift.id if shift else None,
        customer_id=data.customer_id,
        subtotal=Decimal("0"),
        discount_total=_D(data.discount_total),
        total=Decimal("0"),
        cost_total=Decimal("0"),
        tax_total=Decimal("0"),
        sold_at=now,
        receipt_no="TMP",
        client_uuid=data.client_uuid,
    )
    db.add(sale)
    db.flush()  # sale.id kerak

    # "allow_oversell" yoqilgan bo'lsa — qoldiq 0/manfiy bo'lsa ham sotishga ruxsat
    # (omborda qolib ketgan, ro'yxatga olinmagan yoki qoldig'i xato tovarlar ham sotilsin).
    from app.models.settings import Setting as _SecS
    _sc = db.query(_SecS).filter(_SecS.company_id == emp.company_id, _SecS.key == "security").first()
    allow_oversell = bool(((_sc.value if _sc else {}) or {}).get("allow_oversell"))

    subtotal = Decimal("0")
    cost_total = Decimal("0")
    items_discount = Decimal("0")
    _crossed_low: list = []  # kam-qoldiqqa yangi tushgan mahsulotlar (push uchun)
    for it in data.items:
        p = db.get(Product, it.product_id)
        if not p or p.company_id != emp.company_id or p.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {it.product_id}")
        qty = _D(it.qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if qty <= 0:
            raise HTTPException(400, "Miqdor noto'g'ri")
        price = _D(p.base_sell_price)
        ucost = _D(p.base_buy_price)
        idisc = _D(it.discount)
        if idisc > qty * price:
            raise HTTPException(400, "Chegirma mahsulot summasidan oshdi")
        line = qty * price - idisc

        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == p.id, Inventory.branch_id == branch.id)
            .first()
        )
        available = _D(inv.qty) if inv is not None else Decimal("0")
        if qty > available and not allow_oversell:
            raise HTTPException(400, f"Yetarli qoldiq yo'q: {p.name} (qoldiq: {available})")

        subtotal += qty * price
        cost_total += qty * ucost
        items_discount += idisc

        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=p.id,
                name_snapshot=p.name,
                article_snapshot=p.article_code,
                qty=qty,
                unit_price=price,          # SNAPSHOT
                unit_cost=ucost,           # SNAPSHOT (marja analitikasi)
                discount=idisc,
                tax_rate=p.tax_rate,
                line_total=line,
                unit_id=p.unit_id,
            )
        )

        if inv is None:
            inv = Inventory(product_id=p.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        inv.qty = _D(inv.qty) - qty
        inv.updated_at = now
        # Kam-qoldiqqa "kesib o'tish" — 1 marta bildirishnoma uchun belgilaymiz (dedup)
        if inv.qty <= _D(inv.min_qty) and not bool(inv.low_alerted):
            inv.low_alerted = True
            _crossed_low.append((p.name, float(inv.qty)))
        db.add(
            StockMovement(
                product_id=p.id,
                branch_id=branch.id,
                type=MovementType.sale_out,
                qty=-qty,
                unit_cost=ucost,
                balance_after=inv.qty,
                ref_type="sale",
                ref_id=sale.id,
                employee_id=emp.id,
                created_at=now,
            )
        )

    total = subtotal - items_discount - _D(data.discount_total)
    if total < 0:
        raise HTTPException(400, "Chegirma jami summadan oshib ketdi")
    # Naqd som'da kasr (tiyin) yo'q — jami summani butun som'ga yaxlitlaymiz. Tarozida tortilgan
    # mahsulotlar kasr summa berishi mumkin (masalan 4162.5); to'lovlar (naqd/aralash) shu
    # yaxlitlangan summaga tekshiriladi, POS ham fmt() bilan aynan shu qiymatni ko'rsatadi.
    total = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sale.subtotal = subtotal
    sale.cost_total = cost_total
    sale.total = total

    seq = db.query(Sale).filter(Sale.company_id == emp.company_id).count()
    sale.receipt_no = f"#{1287 + seq}"
    sale.uid = now.strftime("%y%m%d") + str(1287 + seq)

    _METHODS = {"cash", "card", "qr", "credit"}
    credit_amt = Decimal("0")  # nasiya qismi (yagona yoki split)

    if data.payments:
        # ── ARALASH (split) to'lov ── summalar jamiga TENG bo'lishi shart
        if total <= 0:
            raise HTTPException(400, "Bo'sh chek uchun to'lov bo'lmaydi")
        paid = Decimal("0")
        for pmt in data.payments:
            if pmt.method not in _METHODS:
                raise HTTPException(400, f"Noto'g'ri to'lov usuli: {pmt.method}")
            amt = _D(pmt.amount)
            paid += amt
            if pmt.method == "credit":
                credit_amt += amt
        # 0.5 = butun som yaxlitlash chegarasi. Eski POS kasr summa (masalan 4162.5) yuborishi
        # mumkin, total esa butunga (4163) yaxlitlangan — shu farqni qabul qilamiz. Yangi POS
        # butun summalar yuboradi, ular butun total bilan ANIQ mos kelishi kerak (abs 0 yoki >=1).
        if abs(paid - total) > Decimal("0.5"):
            raise HTTPException(400, f"To'lovlar yig'indisi ({paid}) jami summaga ({total}) teng emas")
        for pmt in data.payments:
            db.add(SalePayment(sale_id=sale.id, method_code=pmt.method, amount=_D(pmt.amount),
                               given_amount=None, change_amount=None, paid_at=now))
    else:
        # ── YAGONA to'lov (mavjud mantiq) ──
        method = data.payment_method
        if method not in _METHODS:
            raise HTTPException(400, f"Noto'g'ri to'lov usuli: {method}")
        given = _D(data.given_amount) if data.given_amount is not None else total
        # sub-som yaxlitlashga chidamli: eski POS aniq kasr summa (4162.5) yuborsa, yaxlitlangan
        # total (4163) dan 0.5 kam bo'lishi mumkin — buni yetarli deb qabul qilamiz.
        if method == "cash" and given < total - Decimal("0.5"):
            raise HTTPException(400, "Berilgan summa yetarli emas")
        if method == "credit":
            credit_amt = total
        db.add(
            SalePayment(
                sale_id=sale.id,
                method_code=method,
                amount=total,
                given_amount=given if method == "cash" else None,
                # qaytim manfiy bo'lmasin (eski mijoz kasr summa berib total dan 0.5 kam bo'lsa)
                change_amount=max(Decimal("0"), given - total) if method == "cash" else None,
                paid_at=now,
            )
        )

    # Nasiya (qarz) qismi — mijoz balansiga yoziladi (yagona yoki split, faqat credit ulushi)
    if credit_amt > 0:
        if not data.customer_id:
            raise HTTPException(400, "Nasiya uchun mijoz tanlanishi shart")
        cust = db.get(Customer, data.customer_id)
        if not cust or cust.company_id != emp.company_id:
            raise HTTPException(400, "Mijoz topilmadi")
        cust.credit_balance = _D(cust.credit_balance) + credit_amt
        db.add(
            CreditTransaction(
                customer_id=cust.id,
                type=CreditTxnType.charge,
                amount=credit_amt,
                balance_after=cust.credit_balance,
                sale_id=sale.id,
                employee_id=emp.id,
                created_at=now,
            )
        )

    db.commit()
    db.refresh(sale)
    # Kam-qoldiq push (best-effort — asosiy oqimni hech qachon buzmaydi)
    if _crossed_low:
        try:
            from app.services import push
            push.notify_low_stock(db, emp.company_id, _crossed_low)
        except Exception:  # noqa: BLE001
            pass
    return sale
