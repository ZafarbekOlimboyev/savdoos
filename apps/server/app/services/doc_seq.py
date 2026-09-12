# -*- coding: utf-8 -*-
"""HUJJAT RAQAMI TAQSIMLAGICHI — `count()+1` poygasining o'rniga.

NIMA NOTO'G'RI EDI
==================
Chek/qaytarish/kirim raqamlari `count()+1` dan olinardi:

    seq = db.query(Sale).filter(Sale.company_id == cid).count()
    sale.receipt_no = f"#{1287 + seq}"

Ikki kassa AYNI PAYTDA sotsa ikkalasi ham bir xil `count()` ni o'qiydi va bir
xil raqam beradi -> `UNIQUE(company_id, receipt_no)` buziladi -> tranzaksiya
bekor -> retry. Konkurrentlik retry bilan «hal qilinardi», ya'ni ikkinchi
kassa ishini QAYTADAN qilardi.

⚠️  SOTUVDA BUNDAN HAM YOMONI BOR EDI. `Sale` qatori `receipt_no="TMP"` bilan
    tranzaksiyaning ENG BOSHIDA yoziladi va darhol flush qilinadi. `UNIQUE(
    company_id, receipt_no)` esa ikki parallel sotuvni AYNAN shu `'TMP'` satrida
    to'qnashtiradi — ya'ni butun sotuv tranzaksiyasi kompaniya bo'yicha
    SERIALIZATSIYA qilinardi, hali hech qanday qoldiq o'qilmasdan turib.
    Aynan shu narsa Phase 2 da «ikki kassa bir partiyani sotdi» sinovini
    tasodifan yashil qilib, partiya/qoldiq qulflarini ISBOTLASHGA yo'l
    bermagan edi.

YECHIM
======
1. Vaqtinchalik raqam HAR SOTUV UCHUN NOYOB (`TMP-<uuid>`), ya'ni boshlang'ich
   flush endi hech kim bilan to'qnashmaydi.
2. Haqiqiy raqam kompaniya-doiraviy hisoblagich qatoridan BITTA atomik SQL
   bilan olinadi (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`), va u
   COMMIT'dan oldin, imkon qadar KECH olinadi — qulf ushlab turiladigan oyna
   shunda eng qisqa bo'ladi.

⚠️  UZLUKSIZLIK (gapless) ATAYLAB SAQLANDI. Postgres `SEQUENCE` konkurrentlik
    uchun qulayroq, lekin u bekor qilingan tranzaksiyalarda RAQAM YO'QOTADI.
    Chek raqami — buxgalteriya hujjati; «#1288 dan keyin #1290» degan uzilish
    tekshiruvda tushuntirib bo'lmaydigan savol tug'diradi. Hisoblagich qatori
    esa tranzaksiya bilan birga qaytadi, ya'ni raqamlar uzluksiz qoladi.
    Buning narxi — qisqa serializatsiya oynasi, va u ONGLI kelishuv.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.org import DocCounter

# Turlar — hisoblagich kaliti (`company_id` bilan birga NOYOB).
SALE = "sale"
RETURN = "return"
PURCHASE = "purchase"

# Mavjud formatlar va ularning tarixiy boshlanish nuqtalari. Ular O'ZGARMAYDI:
# jonli bazada allaqachon `#1288`, `QAY-1001`, `KIR-1043` ko'rinishidagi
# raqamlar bor va format o'zgarsa hisobotlar/cheklar uzilardi.
def _spec():
    from app.models.purchasing import Purchase
    from app.models.sales import Return, Sale
    return {
        SALE:     {"prefix": "#",    "base": 1287, "model": Sale,     "col": "receipt_no"},
        RETURN:   {"prefix": "QAY-", "base": 1000, "model": Return,   "col": "return_no"},
        PURCHASE: {"prefix": "KIR-", "base": 1042, "model": Purchase, "col": "doc_no"},
    }


class _Lazy(dict):
    def __missing__(self, k):
        self.update(_spec())
        return dict.__getitem__(self, k)

    def __contains__(self, k):
        return k in (SALE, RETURN, PURCHASE)


SPEC = _Lazy()


def tmp_value(kind: str) -> str:
    """To'qnashmaydigan vaqtinchalik raqam (faqat sotuv yo'lida kerak)."""
    return f"TMP-{kind}-{uuid.uuid4().hex}"


def _seed(db: Session, company_id, kind: str) -> int:
    """Mavjud bazadagi ENG KATTA raqamdan davom etadi.

    ⚠️  `count()` EMAS. O'chirilgan yoki bekor qilingan hujjat bo'lsa `count()`
        allaqachon ishlatilgan raqamni QAYTA berardi va `UNIQUE` buzilardi.
        Shu bois mavjud qiymatlardan raqamli qism ajratib olinadi.
    """
    sp = SPEC[kind]
    col = getattr(sp["model"], sp["col"])
    rows = db.execute(
        select(col).where(sp["model"].company_id == company_id)
    ).all()
    mx = sp["base"]
    # ⚠️  FAQAT SHU HISOBLAGICHNING FORMATI. Ilgari namuna `(\d+)\s*$` edi va u
    #     har qanday qiymatning OXIRGI raqamlarini olardi — ya'ni bu hisoblagichga
    #     UMUMAN tegishli bo'lmagan hujjatlar ham seed'ga qo'shilardi:
    #
    #       `/reports/history/seed` yozgan `H<1C raqami>`  -> chek raqami sakrardi;
    #       tasodifiy heksa id (`R3f9637078513`)           -> 9 637 078 513, ya'ni
    #                                                          `INTEGER` chegarasidan
    #                                                          OSHIB KETARDI va
    #                                                          hisoblagich INSERT'i
    #                                                          `NumericValueOutOfRange`
    #                                                          bilan yiqilardi.
    #
    #     Ikkinchisi TASODIFGA bog'liq (heksa satr 10+ raqam bilan tugashi ~1%),
    #     ya'ni u jonli bazada ham kutilmaganda otilishi mumkin edi. Endi qiymat
    #     AYNAN `prefiks + raqamlar` bo'lishi shart.
    pat = re.compile(re.escape(sp["prefix"]) + r"(\d+)")
    for (val,) in rows:
        m = pat.fullmatch((val or "").strip())
        if m:
            mx = max(mx, int(m.group(1)))
    # ⚠️  `doc_counters.next_value` — `INTEGER`. Filtr buni deyarli imkonsiz
    #     qiladi, lekin jonli bazada haqiqatan shunday katta raqam bo'lsa,
    #     tushunarli xato xom `DataError` dan yaxshiroq.
    if mx >= 2_000_000_000:
        raise ValueError(
            f"«{kind}» hisoblagichi uchun boshlang'ich qiymat juda katta ({mx}). "
            f"Bazadagi hujjat raqamlarini tekshiring — `next_value` INTEGER.")
    return mx + 1


def allocate(db: Session, company_id, kind: str) -> int:
    """Keyingi raqamni ATOMIK oladi va qaytaradi.

    ⚠️  XOM SQL ISHLATILMAYDI. `UUID` tipi dialektga qarab har xil saqlanadi:
        Postgres'da native `uuid`, SQLite'da CHAR(32) — CHIZIQCHASIZ. Xom
        matnli parametr SQLite'da HECH QACHON mos kelmasdi va har chaqiruv
        yangi hisoblagich qatori yaratardi. ORM/Core konstruktsiyalari tipni
        o'zi to'g'ri o'giradi.
    """
    if kind not in SPEC:
        raise ValueError(f"noma'lum hujjat turi: {kind}")

    def _bump():
        return db.execute(
            update(DocCounter)
            .where(DocCounter.company_id == company_id, DocCounter.kind == kind)
            .values(next_value=DocCounter.next_value + 1)
            .returning(DocCounter.next_value)
        ).fetchone()

    # ODATIY YO'L: bitta indeksli UPDATE ... RETURNING.
    row = _bump()
    if row is not None:
        return int(row[0])

    # BIRINCHI MARTA: mavjud hujjatlardan davom etamiz.
    seed = _seed(db, company_id, kind)
    sp = db.begin_nested()          # poyga bo'lsa FAQAT shu INSERT qaytsin
    try:
        db.add(DocCounter(id=uuid.uuid4(), company_id=company_id, kind=kind,
                          next_value=seed))
        db.flush()
        sp.commit()
        return int(seed)
    except IntegrityError:
        # Boshqa tranzaksiya bizdan oldin yaratdi -> oddiy oshirishga tushamiz.
        sp.rollback()
        row = _bump()
        if row is None:      # noqa: SIM108 — bu yerga tushish MUMKIN EMAS
            raise
        return int(row[0])


def next_no(db: Session, company_id, kind: str) -> tuple[int, str]:
    """(raqam, formatlangan qiymat) — masalan (1288, "#1288")."""
    n = allocate(db, company_id, kind)
    return n, f"{SPEC[kind]['prefix']}{n}"
