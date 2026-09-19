# -*- coding: utf-8 -*-
"""KANONIK chek DTO — `binos.receipt.v1` (Phase 5F).

⚠️  BUXGALTERIYA HAQIQATI SERVERDA. Chekdagi har summa bazadagi SAQLANGAN
    qiymatdan olinadi (Sale.total, SaleItem.line_total, SalePayment.amount) —
    hech narsa qayta narxlanmaydi va mijoz summa to'qimaydi. Chek HAR DOIM
    qo'shiladi:
        subtotal − line_discount − doc_discount + rounding == total
    `rounding` — butun so'mga yaxlitlash (va eski ma'lumotdagi har qanday qoldiq)
    ning OCHIQ qatori; u yashirilsa chek arifmetikasi xaridor ko'z o'ngida
    «noto'g'ri» chiqardi.
⚠️  SNAPSHOT'LAR. Kassir, filial, TILL, terminal va mahsulot nomi SOTUV
    lahzasidagi suratdan olinadi: keyinroq qayta nomlash eski chek nusxasini
    o'zgartirmaydi. Surat bo'lmasa (eski qator) — joriy nomga qaytiladi.
⚠️  FAQAT O'QISH. Bu modul sotuv/qaytarish yozish yo'lidan HECH QACHON
    chaqirilmaydi (chop etish — commit'dan keyingi alohida so'rov) va bazaga
    hech narsa yozmaydi.
⚠️  Summalar MUSBAT; qaytarish belgisini (−) renderer qo'yadi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import literal_column
from sqlalchemy.orm import Session

from app.models.org import Branch, Company
from app.services.receipt import codes
from app.services.receipt.settings import resolve_for_branch, resolve_store, template_of

SCHEMA = "binos.receipt.v1"
DEFAULT_TZ = "Asia/Tashkent"
_C = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")


# ── RAQAM / VAQT ─────────────────────────────────────────────────────────────
def _dec(v) -> Decimal:
    if v is None:
        return _ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _m(v) -> Decimal:
    return _dec(v).quantize(_C, rounding=ROUND_HALF_UP)


def money(v) -> str:
    """ANIQ 2 xona, eksponentsiz, «-0.00» siz."""
    d = _m(v)
    if d == 0:
        d = Decimal("0.00")
    return format(d, "f")


def qty(v) -> str:
    d = _dec(v).quantize(_Q3, rounding=ROUND_HALF_UP)
    if d == 0:
        d = Decimal("0.000")
    return format(d, "f")


def _aware(dt: datetime) -> datetime:
    # SQLite `DateTime(timezone=True)` ni sodda (naive) qaytaradi — qiymat UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _aware(dt).astimezone(timezone.utc).isoformat(timespec="seconds")


def branch_tz(branch: Branch | None) -> tuple[str, timezone]:
    """Filial vaqt zonasi — hisobotlar bilan AYNI sobit-offset jadvali (DST yo'q)."""
    from app.api.v1.reports import _TZ_OFFSETS
    name = branch.timezone if branch is not None and branch.timezone in _TZ_OFFSETS else DEFAULT_TZ
    return name, timezone(timedelta(hours=_TZ_OFFSETS[name]))


def local_str(dt: datetime | None, tz: timezone) -> str | None:
    if dt is None:
        return None
    return _aware(dt).astimezone(tz).strftime("%d.%m.%Y %H:%M")


# ── YORDAMCHI O'QISHLAR ──────────────────────────────────────────────────────
def _physical_order(db: Session, table: str):
    """Kiritish tartibi.

    ⚠️  `sale_items`/`return_items` da pozitsiya ustuni YO'Q va `id` — tasodifiy
        uuid4. Qatorlar bitta tranzaksiyada savat tartibida kiritiladi, shu bois
        fizik tartib (PG `ctid`, SQLite `rowid`) = savat tartibi. Bu boshqa
        ekranlar (`SaleOut.items`) ko'rsatadigan tartib bilan AYNI, faqat ANIQ
        yozilgan — rejaga qarab o'zgarmaydi."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return literal_column(f"{table}.ctid")
    if dialect == "sqlite":
        return literal_column(f"{table}.rowid")
    return None


def _ordered(db: Session, model, fk_col, parent_id, table: str) -> list:
    q = db.query(model).filter(fk_col == parent_id)
    order = _physical_order(db, table)
    return q.order_by(order).all() if order is not None else q.all()


def _products(db: Session, product_ids) -> dict:
    from app.models.catalog import Product
    ids = {p for p in product_ids if p is not None}
    if not ids:
        return {}
    rows = (db.query(Product.id, Product.name, Product.is_weighted, Product.unit_id)
            .filter(Product.id.in_(ids)).all())
    return {r[0]: r for r in rows}


def _units(db: Session, unit_ids) -> dict:
    from app.models.catalog import Unit
    ids = {u for u in unit_ids if u is not None}
    if not ids:
        return {}
    return {r[0]: r[1] for r in db.query(Unit.id, Unit.code).filter(Unit.id.in_(ids)).all()}


def _employee_name(db: Session, emp_id) -> str | None:
    from app.models.auth import Employee
    if emp_id is None:
        return None
    row = db.query(Employee.full_name).filter(Employee.id == emp_id).first()
    return row[0] if row else None


def _terminal_name(db: Session, terminal_id) -> str | None:
    from app.models.org import Terminal
    if terminal_id is None:
        return None
    row = db.query(Terminal.name).filter(Terminal.id == terminal_id).first()
    return row[0] if row else None


def _customer(db: Session, company_id, customer_id, show: bool) -> dict | None:
    # ⚠️  MAXFIYLIK: shablon ruxsat bermasa mijoz ismi DTO'ga UMUMAN kirmaydi
    #     (faqat renderer yashirishiga tayanilmaydi).
    if not show or customer_id is None:
        return None
    from app.models.customers import Customer
    row = (db.query(Customer.full_name)
           .filter(Customer.id == customer_id, Customer.company_id == company_id).first())
    return {"name": row[0]} if row and row[0] else None


def _till_code(db: Session, till_id) -> str | None:
    """Qaytarishda TILL surati yo'q — kassa hisobidan (faqat Postgres `cash` sxemasi)."""
    if till_id is None or db.get_bind().dialect.name != "postgresql":
        return None
    try:
        with db.begin_nested():
            from app.models.cash import CashAccount
            acc = db.get(CashAccount, till_id)
            label = acc.label if acc is not None else None
    except Exception:            # noqa: BLE001 — sxema yo'q/eski: TILL kodi shunchaki chiqmaydi
        return None
    if acc is None:
        return None
    from app.services.cash import till_identity as _ti
    return (_ti.parse_label(label) or {}).get("checkout_code")


def _logo_ref(db: Session, company_id, branch_id, eff: dict) -> dict | None:
    """{id, sha256} — bitlar `/receipt/profile` dan keladi (DTO yengil qoladi)."""
    if not eff.get("show_logo") or not eff.get("logo_id"):
        return None
    from app.models.receipt import ReceiptLogo
    from app.services.receipt.settings import logo_allowed, parse_uuid
    lid = parse_uuid(eff["logo_id"])
    if lid is None:
        return None
    row = (db.query(ReceiptLogo.id, ReceiptLogo.sha256, ReceiptLogo.company_id,
                    ReceiptLogo.branch_id)
           .filter(ReceiptLogo.id == lid).first())
    if row is None or not logo_allowed(row[2], row[3], company_id, branch_id):
        return None
    return {"id": str(row[0]), "sha256": row[1]}


def qr_for(eff: dict, uid: str | None) -> dict | None:
    mode = eff.get("qr_mode")
    if mode == "receipt_id" and uid:
        return codes.qr_block("receipt_id", uid)
    if mode == "store_url" and eff.get("qr_url"):
        return codes.qr_block("store_url", eff["qr_url"])
    return None


def assemble(*, kind: str, test: bool, doc: dict, store: dict, actor: dict, customer, lines: list,
             totals: dict, payments: list, refund, original, eff: dict, logo) -> dict:
    uid = doc.get("uid")
    return {
        "schema": SCHEMA,
        "kind": kind,
        "test": test,
        "provisional": False,
        "doc": doc,
        "store": store,
        "actor": actor,
        "customer": customer,
        "lines": lines,
        "totals": totals,
        "payments": payments,
        "refund": refund,
        "original": original,
        "barcode": codes.barcode_block(uid) if eff.get("show_barcode") and uid else None,
        "qr": qr_for(eff, uid),
        "logo": logo,
        "template": template_of(eff),
    }


def totals_block(currency: str, subtotal: Decimal, line_discount: Decimal, doc_discount: Decimal,
                 total: Decimal) -> dict:
    rounding = total - (subtotal - line_discount - doc_discount)
    return {"currency": currency, "subtotal": money(subtotal),
            "line_discount": money(line_discount), "doc_discount": money(doc_discount),
            "rounding": money(rounding), "total": money(total)}


# ── SOTUV ────────────────────────────────────────────────────────────────────
def build_sale_receipt(db: Session, sale) -> dict:
    from app.models.sales import SaleItem, SalePayment
    company = db.get(Company, sale.company_id)
    branch = db.get(Branch, sale.branch_id)
    eff, _, _ = resolve_for_branch(db, sale.company_id, branch)
    store = resolve_store(db, company, branch, eff, branch_name=sale.branch_name_snapshot)
    tzname, tz = branch_tz(branch)

    items = _ordered(db, SaleItem, SaleItem.sale_id, sale.id, "sale_items")
    prods = _products(db, [it.product_id for it in items])
    units = _units(db, [it.unit_id or (prods[it.product_id][3] if it.product_id in prods else None)
                        for it in items])
    lines = []
    subtotal = line_disc = _ZERO
    for it in items:
        p = prods.get(it.product_id)
        q = _dec(it.qty).quantize(_Q3, rounding=ROUND_HALF_UP)
        price = _m(it.unit_price)
        gross = _m(q * price)
        disc = _m(it.discount)
        unit_id = it.unit_id or (p[3] if p is not None else None)
        lines.append({"name": it.name_snapshot or (p[1] if p is not None else ""),
                      "qty": qty(q), "unit": units.get(unit_id),
                      "weighted": bool(p[2]) if p is not None else False,
                      "unit_price": money(price), "gross": money(gross),
                      "discount": money(disc), "total": money(it.line_total)})
        subtotal += gross
        line_disc += disc

    pays = (db.query(SalePayment).filter(SalePayment.sale_id == sale.id)
            .order_by(SalePayment.paid_at, SalePayment.id).all())
    payments = [{"method": p.method_code, "amount": money(p.amount),
                 "given": money(p.given_amount) if p.given_amount is not None else None,
                 "change": money(p.change_amount) if p.change_amount is not None else None}
                for p in pays]

    status = sale.status.value if hasattr(sale.status, "value") else str(sale.status)
    doc = {"id": str(sale.id), "number": sale.receipt_no, "uid": sale.uid or None,
           "issued_at": iso_utc(sale.sold_at), "issued_at_local": local_str(sale.sold_at, tz),
           "tz": tzname, "is_offline": bool(sale.is_offline), "status": status}
    actor = {"cashier": sale.cashier_name_snapshot or _employee_name(db, sale.cashier_id),
             "till_code": sale.till_code_snapshot,
             "terminal": sale.terminal_name_snapshot or _terminal_name(db, sale.terminal_id)}
    currency = sale.currency or (company.currency if company else None) or "UZS"
    return assemble(
        kind="SALE", test=False, doc=doc, store=store, actor=actor,
        customer=_customer(db, sale.company_id, sale.customer_id, eff["show_customer"]),
        lines=lines,
        totals=totals_block(currency, subtotal, line_disc, _m(sale.discount_total), _m(sale.total)),
        payments=payments, refund=None, original=None, eff=eff,
        logo=_logo_ref(db, sale.company_id, sale.branch_id, eff))


# ── QAYTARISH ────────────────────────────────────────────────────────────────
def build_return_receipt(db: Session, ret) -> dict:
    from app.models.sales import ReturnItem, Sale, SaleItem
    company = db.get(Company, ret.company_id)
    branch = db.get(Branch, ret.branch_id)
    eff, _, _ = resolve_for_branch(db, ret.company_id, branch)
    store = resolve_store(db, company, branch, eff)
    tzname, tz = branch_tz(branch)

    items = _ordered(db, ReturnItem, ReturnItem.return_id, ret.id, "return_items")
    si_ids = {it.sale_item_id for it in items if it.sale_item_id is not None}
    snaps = ({r[0]: r for r in db.query(SaleItem.id, SaleItem.name_snapshot, SaleItem.unit_id)
              .filter(SaleItem.id.in_(si_ids)).all()} if si_ids else {})
    prods = _products(db, [it.product_id for it in items])

    def _unit_id(it):
        s = snaps.get(it.sale_item_id)
        if s is not None and s[2] is not None:
            return s[2]
        p = prods.get(it.product_id)
        return p[3] if p is not None else None

    units = _units(db, [_unit_id(it) for it in items])
    lines = []
    subtotal = _ZERO
    for it in items:
        s = snaps.get(it.sale_item_id)
        p = prods.get(it.product_id)
        q = _dec(it.qty).quantize(_Q3, rounding=ROUND_HALF_UP)
        price = _m(it.unit_price)
        total = _m(it.line_total)
        name = (s[1] if s is not None and s[1] else None) or (p[1] if p is not None else "")
        lines.append({"name": name, "qty": qty(q), "unit": units.get(_unit_id(it)),
                      "weighted": bool(p[2]) if p is not None else False,
                      "unit_price": money(price), "gross": money(q * price),
                      "discount": "0.00", "total": money(total)})
        subtotal += total

    original = None
    if ret.original_sale_id is not None:
        # Asl chek FAQAT havola (raqam, sana). Xodim asl chekni ko'ra olmasa ham yangi
        # ma'lumot ochilmaydi: raqam qaytarish ro'yxatida (`GET /returns`) ham ko'rinadi.
        o = (db.query(Sale.id, Sale.receipt_no, Sale.uid, Sale.sold_at, Sale.branch_id)
             .filter(Sale.id == ret.original_sale_id, Sale.company_id == ret.company_id).first())
        if o is not None:
            _, otz = branch_tz(db.get(Branch, o[4]) if o[4] is not None else None)
            original = {"id": str(o[0]), "number": o[1], "uid": o[2] or None,
                        "issued_at_local": local_str(o[3], otz)}

    doc = {"id": str(ret.id), "number": ret.return_no, "uid": None,
           "issued_at": iso_utc(ret.created_at), "issued_at_local": local_str(ret.created_at, tz),
           "tz": tzname, "is_offline": False, "status": "completed"}
    actor = {"cashier": _employee_name(db, ret.cashier_id),
             "till_code": _till_code(db, ret.till_id),
             "terminal": _terminal_name(db, ret.terminal_id)}
    currency = (company.currency if company else None) or "UZS"
    total = _m(ret.total)
    return assemble(
        kind="RETURN", test=False, doc=doc, store=store, actor=actor,
        customer=_customer(db, ret.company_id, ret.customer_id, eff["show_customer"]),
        lines=lines, totals=totals_block(currency, subtotal, _ZERO, _ZERO, total),
        payments=[], refund={"method": ret.refund_method, "amount": money(total)},
        original=original, eff=eff, logo=_logo_ref(db, ret.company_id, ret.branch_id, eff))
