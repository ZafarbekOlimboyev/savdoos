# -*- coding: utf-8 -*-
"""NAMUNA chek — sozlama oldindan ko'rinishi va sinov chop etishi uchun (Phase 5F).

⚠️  BAZAGA HECH NARSA YOZILMAYDI: faqat shablon/do'kon ma'lumoti O'QILADI, qolgani
    sintetik. `test: true`, raqam «TEST», `doc.id` yo'q — bu hujjat hech qayerda
    mavjud emas va hech qanday hisobotga tushmaydi (`tests/test_receipt_no_writes.py`
    barcha jadvallar izi bilan isbotlaydi).
⚠️  Summalar HAQIQIY chek qoidasi bilan hisoblanadi (butun so'mga yaxlitlash, to'lovlar
    yig'indisi = jami): namuna renderer'ning arifmetika tekshiruvini ham sinaydi.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.org import Branch, Company
from app.services.receipt.dto import (_logo_ref, assemble, branch_tz, iso_utc, local_str, money,
                                      qty, totals_block)
from app.services.receipt.settings import resolve_for_branch, resolve_store

KINDS = ("sale", "mixed", "return", "long")
SAMPLE_NUMBER = "TEST"
# Shtrix-kod/QR namunasi: aniq TEST belgisi — skanerlansa hech qanday chekka mos kelmaydi.
SAMPLE_UID = "TEST000000"

# (nom, miqdor, narx, birlik, og'irlikli, qator chegirmasi)
_SALE = [
    ("Non «Buxanka»", "2", "3500", "dona", False, "0"),
    ("Sut 3,2% 1 l", "1", "12000", "dona", False, "0"),
    ("Pomidor (issiqxona)", "0.347", "18900", "kg", True, "0"),
    ("Choy «Ahmad» 100 g", "1", "24500", "dona", False, "0"),
]
_MIXED = [
    ("Guruch «Lazer» 1 kg", "3", "16000", "dona", False, "1500"),
    ("Qo'y go'shti (lahm)", "1.254", "98000", "kg", True, "0"),
    ("Молоко «Простоквашино» 2,5%", "2", "14500", "dona", False, "0"),
    ("Kungaboqar yog'i 1 l", "1", "21000", "dona", False, "1000"),
]
_RETURN = [
    ("Sut 3,2% 1 l", "1", "12000", "dona", False, "0"),
    ("Olma «Semerenko»", "0.815", "16000", "kg", True, "0"),
]
_LONG_NAMES = [
    ("Молоко пастеризованное «Простоквашино» 3,2% 930 мл", "dona", False),
    ("Көмөч нан «Токмок» — жаңы бышырылган, 400 г", "dona", False),
    ("Балмуздак «Үлгү» ванилдүү, 80 г", "dona", False),
    ("Oʻzbekiston choyi «Gʻallaorol» koʻk choy, 100 g", "dona", False),
    ("Ўзбекистон шакари оқ, қадоқланган 1 кг — ҳалол", "dona", False),
    ("Qoʻy goʻshti (lahm) — yangi soʻyilgan, 1-nav", "kg", True),
    ("Superuzunmahsulotnomibo'shliqsiz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", "dona", False),
    ("Бадыраң (тепличный), сорт «Өрнөк»", "kg", True),
]


def _lines(spec) -> tuple[list, Decimal, Decimal]:
    out, subtotal, disc = [], Decimal("0"), Decimal("0")
    for name, q, price, unit, weighted, d in spec:
        qd, pd, dd = Decimal(q), Decimal(price), Decimal(d)
        gross = (qd * pd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({"name": name, "qty": qty(qd), "unit": unit, "weighted": weighted,
                    "unit_price": money(pd), "gross": money(gross), "discount": money(dd),
                    "total": money(gross - dd)})
        subtotal += gross
        disc += dd
    return out, subtotal, disc


def _long_spec() -> list:
    spec = []
    for i in range(120):
        name, unit, weighted = _LONG_NAMES[i % len(_LONG_NAMES)]
        if weighted:
            q = "0.001" if i % 16 == 5 else f"{(i % 7) + 1}.{(i * 37) % 1000:03d}"
        else:
            q = str((i % 4) + 1)
        price = str(1000 + (i * 7919) % 250_000)
        disc = str((i % 5) * 500) if i % 5 == 0 and i else "0"
        spec.append((f"{i + 1:03d} {name}", q, price, unit, weighted, disc))
    # Katta summa: chek kengligi 9–10 xonali jamini ham sig'dirishini tekshiradi.
    spec.append(("Televizor 75\" QLED (kafolat 3 yil)", "39", "25200000", "dona", False, "345000"))
    return spec


def build_sample(db: Session, emp, branch: Branch, kind: str, *,
                 now: datetime | None = None) -> dict:
    company = db.get(Company, emp.company_id)
    eff, _, _ = resolve_for_branch(db, emp.company_id, branch)
    store = resolve_store(db, company, branch, eff)
    tzname, tz = branch_tz(branch)
    now = now or datetime.now(timezone.utc)
    currency = (company.currency if company else None) or "UZS"
    is_return = kind == "return"
    spec = {"sale": _SALE, "mixed": _MIXED, "return": _RETURN, "long": None}[kind] or _long_spec()
    lines, subtotal, line_disc = _lines(spec)
    doc_disc = Decimal("2000") if kind in ("mixed", "long") else Decimal("0")
    total = (subtotal - line_disc - doc_disc).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    payments: list = []
    refund = original = None
    if is_return:
        # Qaytarish: qator summasi = jami (chegirma yo'q), yaxlitlash — ochiq qator.
        for ln in lines:
            ln["discount"] = "0.00"
            ln["total"] = ln["gross"]
        line_disc = Decimal("0")
        refund = {"method": "cash", "amount": money(total)}
        original = {"id": None, "number": SAMPLE_NUMBER, "uid": None,
                    "issued_at_local": local_str(now, tz)}
    elif kind == "sale":
        given = (total / Decimal("10000")).to_integral_value(rounding=ROUND_CEILING) * 10000
        payments = [{"method": "cash", "amount": money(total), "given": money(given),
                     "change": money(given - total)}]
    else:
        cash = (total * Decimal("0.2")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        qr = (total * Decimal("0.1")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        card = total - cash - qr
        given = (cash / Decimal("1000")).to_integral_value(rounding=ROUND_CEILING) * Decimal("1000")
        payments = [{"method": "cash", "amount": money(cash), "given": money(given),
                     "change": money(given - cash)},
                    {"method": "card", "amount": money(card), "given": None, "change": None},
                    {"method": "qr", "amount": money(qr), "given": None, "change": None}]

    doc = {"id": None, "number": SAMPLE_NUMBER, "uid": None if is_return else SAMPLE_UID,
           "issued_at": iso_utc(now), "issued_at_local": local_str(now, tz), "tz": tzname,
           "is_offline": False, "status": "completed"}
    actor = {"cashier": emp.full_name, "till_code": "TEST", "terminal": None}
    customer = {"name": "TEST"} if eff["show_customer"] else None
    return assemble(
        kind="RETURN" if is_return else "SALE", test=True, doc=doc, store=store, actor=actor,
        customer=customer, lines=lines,
        totals=totals_block(currency, subtotal, line_disc, Decimal("0") if is_return else doc_disc,
                            total),
        payments=payments, refund=refund, original=original, eff=eff,
        logo=_logo_ref(db, emp.company_id, branch.id, eff))
