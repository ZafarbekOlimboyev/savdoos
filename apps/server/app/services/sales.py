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


def create_sale(db: Session, emp, data: SaleCreate, at: datetime | None = None,
                honor_price_snapshot: bool = False) -> Sale:
    """Chek raqami count() asosida — ikkita kassa AYNI PAYTDA sotsa, bir xil raqam
    chiqib UNIQUE(company_id, receipt_no) buziladi (500). Retry o'rab qo'yamiz:
    to'qnashuvda tranzaksiya bekor bo'lib, qайта urinishда yangi raqam olinadi.
    honor_price_snapshot (QA PC-001): FAQAT /sync/push (offline replay) True beradi —
    chekdagi narx kassada naqd olingan paytdagi narx bo'lib yoziladi."""
    from sqlalchemy.exc import IntegrityError
    last_err: Exception | None = None
    for _try in range(3):
        try:
            return _create_sale_once(db, emp, data, at, honor_price_snapshot)
        except IntegrityError as e:
            db.rollback()
            last_err = e
    raise HTTPException(409, "Kassa band — qayta urinib ko'ring") from last_err


def _create_sale_once(db: Session, emp, data: SaleCreate, at: datetime | None = None,
                      honor_price_snapshot: bool = False) -> Sale:
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
        # O'chirilган mijozга savdo/nasiya biriktirмаймиз — aks holда qarz qarzdorlar
        # hisobotидан yashirин qolарди (soft-delete filtrи u yerда bor).
        if not _cust or _cust.company_id != emp.company_id or _cust.deleted_at is not None:
            raise HTTPException(400, "Mijoz topilmadi")

    if data.payment_method not in {"cash", "card", "qr", "credit"}:
        raise HTTPException(400, f"Noto'g'ri to'lov usuli: {data.payment_method}")

    # Filial: kassir biriktirilgan filial (EmployeeBranch) — bo'lmasa birinchi filial.
    # Ilgari doim birinchi filial olinardi; ko'p-filial do'konda savdo noto'g'ri filialga yozilardi.
    # actor_branch bilan BIR XIL qoida: deterministik tartib + nofaol filialga yangi savdo yozilmaydi.
    from app.core.deps import actor_branch as _ab
    branch = _ab(emp, db)
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    now = at or _now()
    # QA PAY-02: OFFLINE replay (honor_price_snapshot) — savdo sold_at bo'yicha JISMONAN qaysi smenada
    # olingan bo'lsa o'shanga bog'lanadi (flush paytidagi ochiq smenaga EMAS). Aks holda offline naqd
    # yopilgan A smenasiga tushmay NULL yoki keyingi B smenaga yozilib kassa 'expected'i buzilardi
    # (A soxta kamomad / B soxta ortiqcha). Onlayn savdoda (at=None) — joriy ochiq smena (o'zgarishsiz).
    if honor_price_snapshot and at is not None:
        shift = (
            db.query(Shift)
            .filter(Shift.cashier_id == emp.id, Shift.opened_at <= now,
                    ((Shift.closed_at.is_(None)) | (Shift.closed_at >= now)))
            .order_by(Shift.opened_at.desc())
            .first()
        )
    else:
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
    _price_diffs: list = []  # QA PC-001: offline snapshot != joriy narx — audit izi uchun
    # DEADLOCK oldini olish: Inventory qatorlarини DASTAVVAL bir xil GLOBAL tartибда (product_id)
    # qulflaymiz — aks holда ikki chek [A,B] va [B,A] tartибда kelса Postgres'да AB-BA deadlock
    # bo'lиб bittasi 500 berardi. Bu yerда FAQAT qulf olamiz; chek qatorlari tartиби o'zgармайди
    # (asosiy sikl quyида mijoz yuborган tartибда ishlaydi — qator allaqачон qulflangan, no-op).
    for _pid in sorted({it.product_id for it in data.items}, key=str):
        _r = db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
        if _r is None:
            # QA WH-017: qator yo'q bo'lsa SHU YERDA (global tartibda) yaratib qulflaymiz —
            # keyingi item-tartibli INSERT poygalari sinfi yo'qoladi (to'qnashuv flush'da
            # otilib create_sale retry-o'ramiga tushadi).
            db.add(Inventory(product_id=_pid, branch_id=branch.id, qty=Decimal("0"), updated_at=now))
            db.flush()
            db.query(Inventory).filter(
                Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    for it in data.items:
        p = db.get(Product, it.product_id)
        if not p or p.company_id != emp.company_id or p.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {it.product_id}")
        qty = _D(it.qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if qty <= 0:
            raise HTTPException(400, "Miqdor noto'g'ri")
        # QA PC-001: offline replay'da (honor_price_snapshot) chek KASSADA urilgan paytdagi
        # narxda yoziladi — mijozdan naqd O'SHA narxda olingan; flush paytidagi yangi narxda
        # yozish kassa naqdi va bazani jimgina farqlantirardi. Onlayn savdoda snapshot
        # E'TIBORGA OLINMAYDI (narx-manipulyatsiya yopiq) — mos kelmasa 409 (quyida).
        price = _D(p.base_sell_price)
        if honor_price_snapshot and it.unit_price is not None:
            _snap = _D(it.unit_price)
            if _snap != price:
                _price_diffs.append({"product": p.name, "snapshot": float(_snap), "current": float(price)})
            price = _snap
        ucost = _D(p.base_buy_price)
        idisc = _D(it.discount)
        if idisc > qty * price:
            raise HTTPException(400, "Chegirma mahsulot summasidan oshdi")
        line = qty * price - idisc
        from app.core.validate import guard_amount
        guard_amount(qty * price, f"'{p.name}' qatori summasi")  # Numeric(14,2) overflow -> do'stona 400

        # QATOR QULFI (with_for_update): ikki kassir bir vaqtда oxirgi donani sotса ham
        # qoldiq manfiy bo'lmasin (Postgres'да satr qulflanadi; SQLite'да bezarar no-op).
        inv = (
            db.query(Inventory)
            .filter(Inventory.product_id == p.id, Inventory.branch_id == branch.id)
            .with_for_update()
            .first()
        )
        available = _D(inv.qty) if inv is not None else Decimal("0")
        # QA WH-007: OFFLINE REPLAY (honor_price_snapshot) stok-guard'dan o'tadi — tovar kassada
        # JISMONAN allaqachon sotilgan, pul olingan; flush paytida qoldiq yetmasa ham chek
        # yozilishi SHART (qoldiq manfiyga tushadi, keyin inventarizatsiya tuzatadi). Aks holda
        # chek dead-letter bo'lib pul olingan savdo bazadan butunlay yo'qolardi.
        if qty > available and not allow_oversell and not honor_price_snapshot:
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
    # QA SB-006: 'Maksimal chegirma %' (Setting tax.max_disc) ilgari DEKORATIV edi — hech qayerda
    # enforce qilinmasdi (API orqali 100% chegirma o'tardi). Endi jami chegirma foizi cap'lanadi.
    _total_disc = items_discount + _D(data.discount_total)
    if _total_disc > 0 and subtotal > 0:
        from app.models.settings import Setting as _Set
        _trow = db.query(_Set).filter(_Set.company_id == emp.company_id, _Set.key == "tax").first()
        try:
            _cap = float(((_trow.value if _trow else {}) or {}).get("max_disc") or 0)
        except (TypeError, ValueError):
            _cap = 0.0
        if 0 < _cap <= 100:
            _pct = float(_total_disc) / float(subtotal) * 100.0
            if _pct > _cap + 0.01:
                raise HTTPException(400, f"Chegirma limiti oshdi: {_pct:.1f}% > {_cap:g}% (sozlamadagi maksimal)")
    from app.core.validate import guard_amount as _guard_amount
    _guard_amount(subtotal, "Chek jami summasi")      # Numeric(14,2) yig'indi overflow -> do'stona 400
    _guard_amount(cost_total, "Chek tannarx summasi")
    # Naqd som'da kasr (tiyin) yo'q — jami summani butun som'ga yaxlitlaymiz. Tarozida tortilgan
    # mahsulotlar kasr summa berishi mumkin (masalan 4162.5); to'lovlar (naqd/aralash) shu
    # yaxlitlangan summaga tekshiriladi, POS ham fmt() bilan aynan shu qiymatni ko'rsatadi.
    total = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    # QA PAY-07: bo'sh/0-summa chek uchun to'lov yozilmaydi (yagona va split yo'l IZCHIL — ilgari
    # faqat split rad etardi, yagona to'lov 0-total chekni yakunlab yuborardi).
    if total <= 0:
        raise HTTPException(400, "Bo'sh chek — to'lov summasi 0")
    # QA PC-001: ONLAYN savdoda POS ko'rsatgan jami bilan server hisobi mos kelishi SHART —
    # savat ochiq turganda narx o'zgargan bo'lsa mijoz X to'lab bazaga Y yozilardi (jimgina).
    # 409 → POS katalog/savatni yangilab kassirga yangi narxni ko'rsatadi. QA PAY-08: tolerans
    # split-to'lov toleransi bilan bir xil (0.5) — ikkalasi ham butun-som yaxlitlash chekkasi;
    # ilgari 1 so'm bo'lib, 1 so'mlik narx-farqi yagona to'lovda jimgina o'tib, aralashda 400 berardi.
    if not honor_price_snapshot and data.expected_total is not None:
        _exp = _D(data.expected_total)
        if abs(total - _exp) > Decimal("0.5"):
            raise HTTPException(409, "Narxlar yangilandi — savat qayta hisoblandi, tekshirib qayta urining")
    if _price_diffs:
        # Offline chek eski narxda yozildi — bu QAROR (kassa naqdiga mos), lekin iz qoldiramiz.
        from app.services.audit import log as _audit_log
        _audit_log(db, emp.id, "update", "sale", sale.id,
                   after={"offline_price_snapshot": _price_diffs[:20]})
    sale.subtotal = subtotal
    sale.cost_total = cost_total
    sale.total = total

    seq = db.query(Sale).filter(Sale.company_id == emp.company_id).count()
    sale.receipt_no = f"#{1287 + seq}"
    sale.uid = now.strftime("%y%m%d") + str(1287 + seq)

    _METHODS = {"cash", "card", "qr", "credit"}
    # O'CHIRILGAN to'lov usullari server tomonda majburlanadi — POS yashirса ham (yoki offline
    # replay/soxta so'rov) o'chirilган usul (masalan nasiya) bilan savdo yaratib bo'lmaydi.
    # Odatда bo'sh (hamma yoniq) — arzon so'rov; faqat aniq o'chirilganini rad etamiz.
    from app.models.settings import PaymentMethod as _PM
    _disabled = {c for (c,) in db.query(_PM.code).filter(
        _PM.company_id == emp.company_id, _PM.is_enabled.is_(False)).all()}
    credit_amt = Decimal("0")  # nasiya qismi (yagona yoki split)

    if data.payments:
        # ── ARALASH (split) to'lov ── summalar jamiga TENG bo'lishi shart
        if total <= 0:
            raise HTTPException(400, "Bo'sh chek uchun to'lov bo'lmaydi")
        paid = Decimal("0")
        for pmt in data.payments:
            if pmt.method not in _METHODS:
                raise HTTPException(400, f"Noto'g'ri to'lov usuli: {pmt.method}")
            if pmt.method in _disabled:
                raise HTTPException(400, f"To'lov usuli o'chirilgan: {pmt.method}")
            paid += _D(pmt.amount)
        # 0.5 = butun som yaxlitlash chegarasi. Eski POS kasr summa (masalan 4162.5) yuborishi
        # mumkin, total esa butunga (4163) yaxlitlangan — shu farqni qabul qilamiz. Yangi POS
        # butun summalar yuboradi, ular butun total bilan ANIQ mos kelishi kerak (abs 0 yoki >=1).
        if abs(paid - total) > Decimal("0.5"):
            raise HTTPException(400, f"To'lovlar yig'indisi ({paid}) jami summaga ({total}) teng emas")
        # QA PAY-09: saqlanadigan summalar BUTUN som'ga yaxlitlanib yig'indisi total'ga AYNAN teng
        # bo'ladi (invariant: Σ SalePayment.amount == Sale.total). Kasr klient (99.5→total 100) 0.5
        # tolerans bilan qabul qilinsa ham, oxirgi qator qoldiqni yutib total bilan tekislaydi.
        # Kredit ulushi ham SAQLANGAN (yaxlitlangan) summadan hisoblanadi — mijoz balansi qatorga mos.
        _n = len(data.payments)
        _acc = Decimal("0")
        for _i, pmt in enumerate(data.payments):
            _amt = (total - _acc) if _i == _n - 1 else _D(pmt.amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            _acc += _amt
            if pmt.method == "credit":
                credit_amt += _amt
            db.add(SalePayment(sale_id=sale.id, method_code=pmt.method, amount=_amt,
                               given_amount=None, change_amount=None, paid_at=now))
    else:
        # ── YAGONA to'lov (mavjud mantiq) ──
        method = data.payment_method
        if method not in _METHODS:
            raise HTTPException(400, f"Noto'g'ri to'lov usuli: {method}")
        if method in _disabled:
            raise HTTPException(400, f"To'lov usuli o'chirilgan: {method}")
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

    # QA PAY-01: QR to'lov — POS xpay txn_id yuborsa server QrPayment'ni TASDIQLAYDI (COMPLETED,
    # summasi mos, avval ishlatilmagan) va ISHLATADI (consume: qp.sale_id). Aks holda soxta/bekor/
    # qayta-ishlatilgan QR bilan "to'langan" chek yozilardi (QR-002). txn_id yuborilmasa (manual QR
    # rejimi — kassir ko'z bilan tasdiqlaydi) eski xatti-harakat saqlanadi. QrPayment qulfi Inventory'dan
    # KEYIN, Customer'dan OLDIN — sale yo'lida qulf tartibi izchil (Inv→QR→Cust), return QR'ni tegmaydi.
    _qr_amt = (sum((_D(p.amount) for p in data.payments if p.method == "qr"), Decimal("0"))
               if data.payments else (total if data.payment_method == "qr" else Decimal("0")))
    if _qr_amt > 0 and data.qr_txn_id:
        from app.models.payments import QrPayment
        qp = (db.query(QrPayment)
              .filter(QrPayment.txn_id == data.qr_txn_id, QrPayment.company_id == emp.company_id)
              .with_for_update().first())
        if not qp:
            raise HTTPException(400, "QR to'lov topilmadi")
        if qp.status != "COMPLETED":
            raise HTTPException(400, f"QR to'lov tasdiqlanmagan (holat: {qp.status})")
        if qp.sale_id is not None and qp.sale_id != sale.id:
            raise HTTPException(400, "Bu QR to'lov allaqachon boshqa savdoda ishlatilgan")
        if abs(_D(qp.amount) - _qr_amt) > Decimal("1"):
            raise HTTPException(400, "QR to'lov summasi savdo summasiga mos emas")
        qp.sale_id = sale.id

    # Nasiya (qarz) qismi — mijoz balansiga yoziladi (yagona yoki split, faqat credit ulushi)
    if credit_amt > 0:
        if not data.customer_id:
            raise HTTPException(400, "Nasiya uchun mijoz tanlanishi shart")
        # QATOR QULFI: bir vaqtда ikki kredit op (savdo/to'lov/qaytarish) balansни STALE o'qib
        # yo'qotmasin — mijoz kam/ko'p yozilmasin.
        # QA CC-001: mijoz yuqorida (:66) tenant-tekshiruvi uchun db.get bilan QULFSIZ identity-map'ga
        # yuklangan. with_for_update DB qulfini oladi, LEKIN o'sha KESH obyektni qaytaradi va
        # credit_balance'ni yangilamaydi (populate_existing yo'q) — qulf oldidagi STALE qiymat qolib,
        # parallel nasiya-savdo lost-update berardi (balance != ledger). refresh qulf ostidagi
        # HAQIQIY qiymatni o'qiydi.
        cust = (db.query(Customer).filter(Customer.id == data.customer_id)
                .with_for_update().first())
        if not cust or cust.company_id != emp.company_id:
            raise HTTPException(400, "Mijoz topilmadi")
        db.refresh(cust)
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
            push.notify_low_stock(db, emp.company_id, _crossed_low, branch_name=branch.name)
        except Exception:  # noqa: BLE001
            pass
    return sale
