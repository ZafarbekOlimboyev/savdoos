# -*- coding: utf-8 -*-
"""BIRLIK DARVOZASI — bo'linmas birlikda KASR miqdor qabul qilinmaydi.

INVARIANT (serverda majburiy):

    Unit.allow_fraction == False  ->  miqdor MATEMATIK BUTUN bo'lishi SHART
    Unit.allow_fraction == True   ->  kasr miqdor ruxsat

Misollar: `dona`/`upak` (allow_fraction=False) uchun `1`, `2`, `2.0`, `2.000` — O'TADI;
`0.5`, `1.5`, `2.001`, `0.25` — RAD. `kg`/`litr` (True) uchun hammasi o'tadi.

NEGA DARVOZA KERAK
==================
`units.allow_fraction` ustuni BIRINCHI kundan beri bor (`db/schema.sql:170`), lekin
uni server biznes yozuvchilari TEKSHIRMASDI. Natijada `0.5 dona` sotuv, kirim,
hisobdan chiqarish, sanoq va qaytarish orqali bazaga tushardi va qoldiq
`3.5 dona` kabi FIZIK MA'NOSIZ holatga kelardi.

⚠️  MASSHTAB ≠ BUTUNLIK. Repoda allaqachon `_uch_xona()` kabi tekshiruvlar bor —
    ular miqdorda 3 tadan ortiq kasr xona YO'QLIGINI tekshiradi. `2.001` esa
    masshtab bo'yicha YAROQLI, lekin `dona` uchun MA'NOSIZ. Shu bois bu darvoza
    masshtabga emas, `to_integral_value()` ga tayanadi.

QOIDALAR
========
* **Yaxlitlash YO'Q.** `0.5 dona` ni `1` ga yoki `0` ga aylantirish TAQIQ — bu
  so'ralgan miqdorni JIM o'zgartirish bo'lardi. Faqat RAD etiladi.
* **Mijozga ishonilmaydi.** `allow_fraction` FAQAT bazadan
  (`Product.unit_id -> Unit.allow_fraction`) o'qiladi. Klient yuborgan birlik
  yoki bayroq e'tiborga OLINMAYDI.
* **XOM qator, AGREGATSIYADAN OLDIN.** Ko'p qatorli yo'llarda har qator ALOHIDA
  tekshiriladi. Aks holda `0.5 dona + 0.5 dona = 1 dona` arifmetika bilan
  "yuvilib", yaroqsiz kirish yaroqli jamiga aylanardi.
* **Mutatsiyadan OLDIN.** Rad etish hech qanday qism-o'zgarish qoldirmasligi
  SHART (sotuv/qator/qoldiq/harakat/to'lov — hammasi tegilmagan).

NEGA `HTTPException(400)` VA `ValueError` EMAS
==============================================
`/sync/push` xatoni HTTP holati bo'yicha klassifikatsiya qiladi
(`api/v1/sync.py`): `>=500` yoki `409` — TRANZIENT (`retry: True`, klient
outbox'da saqlab QAYTA URADI), qolgani — PERMANENT (`retry: False`, dead-letter).
Xom `ValueError` esa catch-all'ga tushib `{"ok": false, "error": "server"}`
berardi: `retry` kaliti YO'Q va operator uchun matn FOYDASIZ.

Shu bois: **400 + tushunarli matn**. Bu `app/core/validate.py` (`guard_amount`)
konvensiyasiga ham mos. Barqaror `X-Error-Code` QO'SHILMAYDI — `error_codes.py`
dagi kodlar partiya invariantlari uchun va HAMMASI 409, ya'ni TRANZIENT; miqdor
validatsiyasiga kod berish uni qayta-urinadigan qilib qo'yardi.

`products.unit_id` — **NOT NULL** (`db/schema.sql:212`), ya'ni har mahsulotning
birligi BOR va `allow_fraction` doim yechiladi. Mahsulot umuman topilmasa — bu
boshqa xato (mavjud yo'llar uni o'zi rad etadi), bu darvoza esa noma'lum
mahsulotni JIM kasrli deb hisoblamaydi: u ro'yxatda bo'lmasa, tekshirilmaydi va
chaqiruvchining o'z "mahsulot topilmadi" tekshiruvi ishlaydi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Product, Unit

#: Bo'linmas birlikda kasr miqdor kelganda operatorga ko'rsatiladigan matn.
#: Bu matn ayni paytda klient tarjima lug'atining KALITI bo'lishi mumkin
#: (`packages/shared/src/lib/serverErrors*.ts` naqshi) — o'zgartirishda lug'atni ham yangilang.
FRACTION_NOT_ALLOWED = "Bu mahsulot faqat butun miqdorda o'lchanadi — kasr miqdor kiritilmaydi"


def is_integral(value) -> bool:
    """Qiymat MATEMATIK butunmi (`2`, `2.0`, `2.000` -> True; `0.5`, `2.001` -> False).

    `Decimal(str(v))` — repo konvensiyasi: sxemalarda miqdor `float` bo'lib keladi
    (`qty: float = Field(gt=0, ...)`), va `str()` orqali o'tish ikkilik float
    artefaktini (`0.1 -> 0.1000000000000000055`) keltirib chiqarmaydi.
    Float modulo (`v % 1 == 0`) ISHLATILMAYDI — u aynan shu artefaktda yiqiladi.
    """
    if value is None or value == "":
        return False          # miqdor YO'Q — jim «butun» deb hisoblanmaydi (fail-closed)
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    if not d.is_finite():
        return False
    return d == d.to_integral_value()


def fraction_map(db: Session, product_ids: Iterable) -> dict[uuid.UUID, bool]:
    """`product_id -> allow_fraction` xaritasi — BITTA so'rov bilan.

    Ko'p qatorli yozuvchilar (savat, kirim, sanoq) uchun N+1 ni oldini oladi:
    chaqiruvchi hamma mahsulot id'sini bir marta beradi va xaritani qayta ishlatadi.
    Ro'yxatda bo'lmagan id — xaritada YO'Q (qarang modul sarlavhasi).
    """
    ids = {p for p in product_ids if p is not None}
    if not ids:
        return {}
    rows = db.execute(
        select(Product.id, Unit.allow_fraction).join(Unit, Product.unit_id == Unit.id)
        .where(Product.id.in_(ids))
    ).all()
    return {pid: bool(frac) for pid, frac in rows}


# ⚠️  `code_fraction_map` ATAYLAB YO'Q (ilgari bor edi, OLIB TASHLANDI).
#     U `unit.code -> allow_fraction` ni KLIENT yuborgan satr bo'yicha yechardi va
#     ikki FAIL-OPEN teshigi ochardi: katta-kichik harf (`"DONA"` topilmaydi) va
#     berilmagan/noma'lum kod (tekshirilmaydi) — holbuki yozuvchi `.lower()` va
#     zaxira birlik bilan baribir `dona` mahsulot yaratardi. Bu modulning O'Z
#     qoidasiga ham qarshi edi (yuqoriga qarang: «Mijozga ishonilmaydi»).
#     YANGI mahsulot yo'llari endi `unit_fraction_map` ga YECHILGAN `unit_id` beradi
#     — aynan yozuvchining o'zi ishlatadigan ifoda bilan.


def unit_fraction_map(db: Session, unit_ids: Iterable) -> dict[uuid.UUID, bool]:
    """`unit.id -> allow_fraction` — birlik ID bo'yicha yechilgan yo'llar uchun. BITTA so'rov.

    Mahsulot YARATISH yo'llari birlikni allaqachon `unit_id` ga yechib qo'yadi
    (`products._bulk_create_once`, `catalog_import_v2.initial_create`), shu bois
    kod bo'yicha QAYTA yechish kerak emas.
    """
    ids = {u for u in unit_ids if u is not None}
    if not ids:
        return {}
    rows = db.execute(select(Unit.id, Unit.allow_fraction).where(Unit.id.in_(ids))).all()
    return {uid: bool(frac) for uid, frac in rows}


def check_qty(allow_fraction: bool | None, qty) -> bool:
    """Bitta qiymat shu birlik uchun yaroqlimi. `allow_fraction=None` -> tekshirilmaydi."""
    if allow_fraction is None or allow_fraction:
        return True
    return is_integral(qty)


def assert_qty(allow_fraction: bool | None, qty, *, name: str | None = None,
               label: str | None = None) -> None:
    """Bitta qiymatni tekshiradi; buzuqda 400. Mahsulot ID'siz (yaratish yo'llari) ishlatiladi."""
    if not check_qty(allow_fraction, qty):
        raise HTTPException(400, _compose(name, qty, label))


def message(qty, *, name: str | None = None, label: str | None = None) -> str:
    """Operator matni — MAHSULOT HALI YO'Q bo'lgan yo'llar uchun (nom qatordan keladi)."""
    return _compose(name, qty, label)


def validate_lines(db: Session, lines: Iterable[tuple], *, label: str | None = None) -> None:
    """XOM qatorlarni AGREGATSIYADAN OLDIN tekshiradi; birinchi buzuqda 400.

    `lines` — `(product_id, qty)` juftliklari. Ayni mahsulot bir necha qatorda
    kelsa HAR BIRI alohida tekshiriladi: aynan shu `0.5 + 0.5 = 1` yuvilishini
    to'sadi.

    Hech narsa o'zgartirmaydi va hech narsa qaytarmaydi — faqat rad etadi.
    """
    pairs = [(pid, qty) for pid, qty in lines]
    if not pairs:
        return
    fmap = fraction_map(db, (pid for pid, _ in pairs))
    for pid, qty in pairs:
        if not check_qty(fmap.get(pid), qty):
            raise HTTPException(400, _message(db, pid, qty, label))


def validate_one(db: Session, product_id, qty, *, label: str | None = None) -> None:
    """Bitta mahsulot/miqdor uchun qisqa yo'l (`validate_lines` ning bir qatori)."""
    validate_lines(db, [(product_id, qty)], label=label)


def validate_with_map(fmap: Mapping, lines: Iterable[tuple], *, db: Session | None = None,
                      label: str | None = None) -> None:
    """Xarita ALLAQACHON yuklangan bo'lsa (bulk yozuvchilar) — qo'shimcha so'rovsiz.

    `db` berilsa xato matni mahsulot nomi bilan boyitiladi; berilmasa umumiy matn.
    """
    for pid, qty in lines:
        if not check_qty(fmap.get(pid), qty):
            raise HTTPException(400, _message(db, pid, qty, label))


def _message(db: Session | None, product_id, qty, label: str | None) -> str:
    """Operator uchun matn: nima, qancha, qaysi mahsulot."""
    name = None
    if db is not None and product_id is not None:
        try:
            name = db.execute(select(Product.name).where(Product.id == product_id)).scalar()
        except Exception:  # noqa: BLE001 — xato matni uchun so'rov hech qachon asosiy xatoni yashirmasin
            name = None
    return _compose(name, qty, label)


def _compose(name: str | None, qty, label: str | None) -> str:
    parts = [FRACTION_NOT_ALLOWED]
    if name:
        parts.append(f"«{name}»")
    if label:
        parts.append(f"({label})")
    try:
        parts.append(f"— kiritilgan: {Decimal(str(qty)).normalize():f}")
    except (InvalidOperation, ValueError, TypeError):
        parts.append(f"— kiritilgan: {qty}")
    return " ".join(parts)


# ── BIRLIK ALMASHTIRISH (retroaktiv buzilish) ──────────────────────────────
#
# ⚠️  `PATCH /products/{id}` `unit_code` ni ALMASHTIRA oladi. Bu miqdor YOZMAYDI,
#     lekin invariantni MAVJUD miqdorlar ostidan buzadi: `kg` (3.5) -> `dona`
#     bo'lsa, qoldiq `3.5 dona` bo'lib qoladi va yuqoridagi barcha darvozalar
#     chetlab o'tiladi. Shu bois almashtirishning O'ZI tekshiriladi.
#     Yaxlitlash YO'Q — faqat RAD (ega qoldiqni avval butunga keltirsin).

def _fractional_balances(db: Session, product_id) -> list:
    """Mahsulotning MAVJUD kasr fizik miqdorlari: `Inventory.qty` + OCHIQ partiyalar.

    Ikkisi ham fizik miqdor va ikkisi ham kasr bo'la oladi (eski ma'lumotda yoki
    darvoza qo'yilishidan oldin yozilgan qatorlarda).
    """
    from app.models.inventory import Inventory, StockBatch
    bad = []
    for (q,) in db.execute(
            select(Inventory.qty).where(Inventory.product_id == product_id)).all():
        if q is not None and not is_integral(q):
            bad.append(q)
    for (q,) in db.execute(
            select(StockBatch.remaining_qty)
            .where(StockBatch.product_id == product_id, StockBatch.remaining_qty > 0)).all():
        if q is not None and not is_integral(q):
            bad.append(q)
    return bad


def _balances_text(bad: list) -> str:
    return ", ".join(format(Decimal(str(b)).normalize(), "f") for b in bad[:5])


def assert_unit_switch_safe(db: Session, product_id, new_unit_id, *,
                            product_name: str | None = None) -> None:
    """Bo'linmas birlikka o'tishda mavjud KASR miqdorlar bo'lsa — 400.

    Yangi birlik kasrli bo'lsa (`kg`/`litr`) — hech narsa tekshirilmaydi.
    """
    allow = unit_fraction_map(db, [new_unit_id]).get(new_unit_id)
    if allow is None or allow:
        return                      # birlik topilmadi (chaqiruvchi o'zi rad etadi) yoki kasr ruxsat
    bad = _fractional_balances(db, product_id)
    if bad:
        nom = f"«{product_name}» " if product_name else ""
        raise HTTPException(
            400,
            f"{nom}o'lchov birligini bo'linmas birlikka o'zgartirib bo'lmaydi: mavjud "
            f"qoldiq KASR ({_balances_text(bad)}). Avval qoldiqni butun miqdorga "
            f"keltiring (sanoq yoki hisobdan chiqarish).")


def assert_balance_integral(db: Session, product_id, *, label: str | None = None) -> None:
    """Mahsulotning JORIY qoldig'i o'z birligiga mos bo'lmasa — 400.

    Miqdor YOZMAYDIGAN, lekin mavjud qoldiqni O'ZGARMAS holatga MUHRLAB QO'YADIGAN
    amallar uchun (`/lots/enable` ning `legacy` shoxi: `open_legacy_lot(qty=have)`).
    Bunday amal eski ma'lumotdagi `3.5 dona` ni qaytarib bo'lmaydigan kogortaga
    aylantirardi.

    ⚠️  Bu RAD ETISH, tuzatish EMAS: qoldiq hech qachon yaxlitlanmaydi. Yagona
        tuzatish yo'li — operatorning o'zi (`/inventory/count`).
    """
    allow = fraction_map(db, [product_id]).get(product_id)
    if allow is None or allow:
        return
    bad = _fractional_balances(db, product_id)
    if bad:
        qay = f" ({label})" if label else ""
        raise HTTPException(
            400,
            f"{FRACTION_NOT_ALLOWED}{qay} — mahsulotning JORIY qoldig'i kasr "
            f"({_balances_text(bad)}). Avval qoldiqni butun miqdorga keltiring "
            f"(`/inventory/count`), keyin bu amalni qayta bajaring.")
