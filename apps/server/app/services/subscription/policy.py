# -*- coding: utf-8 -*-
"""Majburlash siyosati — QAYSI amal qaysi holatda mumkin (Phase 6A/2).

Bu modul MA'LUMOT: matritsa shu yerda, marshrutlarga ulash esa keyingi bosqichda.
Shunday qilinganining sababi — smena yopish istisnosi endpoint yozilishidan OLDIN
test bilan qulflansin: kassada ochiq smena obuna tugagani sabab yarim tunda
qolib ketmasligi kodga emas, TESTGA bog'langan bo'lsin.

⚠️  `RESTRICTED` — «do'kon o'chdi» DEGANI EMAS. O'qish, hisobot, eksport, login va
    hisob/to'lov yo'llari OCHIQ qoladi: aks holda operator to'lash uchun ham kira
    olmasdi va ma'lumotini ko'chirib ololmasdi.
⚠️  `GRACE` da yozuv MUMKIN — faqat ogohlantirish ko'rsatiladi. Grace'ning butun
    ma'nosi shu: to'lov kechikkan, lekin ish to'xtamaydi.
"""
from __future__ import annotations

from app.models.enums import SubscriptionStatus

# ── Amal toifalari ───────────────────────────────────────────────────────────
#  Nomlar marshrut yo'llaridan EMAS, BIZNES ma'nosidan olingan: yo'l o'zgarsa
#  matritsa o'zgarmasin.
SALE = "sale"
RETURN = "return"
RECEIVING = "receiving"
RECEIVING_CORRECTION = "receiving_correction"
INVENTORY_COUNT = "inventory_count"
WRITE_OFF = "write_off"
TRANSFER = "transfer"
CASH_OP = "cash_op"
SHIFT_OPEN = "shift_open"
SHIFT_CLOSE = "shift_close"
CUSTOMER_DEBT = "customer_debt"
SUPPLIER = "supplier"
PRODUCT = "product"
BRANCH = "branch"
LOT = "lot"
OPERATIONAL_SETTING = "operational_setting"
#  Majburlashdan TASHQARIDAGI yo'llar (obuna holati ularga TA'SIR QILMAYDI).
AUTH = "auth"
BILLING = "billing"
ADMIN = "admin"
READ = "read"

#: Obuna holatidan QAT'I NAZAR doim ochiq toifalar.
ALWAYS_ALLOWED: frozenset[str] = frozenset({AUTH, BILLING, ADMIN, READ})

#: Yangi biznes yozuvi toifalari — `RESTRICTED` da to'siladi (istisno pastda).
BUSINESS_WRITE: frozenset[str] = frozenset({
    SALE, RETURN, RECEIVING, RECEIVING_CORRECTION, INVENTORY_COUNT, WRITE_OFF,
    TRANSFER, CASH_OP, SHIFT_OPEN, CUSTOMER_DEBT, SUPPLIER, PRODUCT, BRANCH,
    LOT, OPERATIONAL_SETTING,
})

#: ⚠️  YAGONA ISTISNO. Smena yopish `RESTRICTED` da ham MUMKIN.
#      Sabab: smena yopish YANGI biznes hodisasi emas — u OCHIQ hodisani
#      yakunlaydi. To'silsa kassada ochiq smena qolardi, pul qoldig'i
#      hisoblanmasdi va kassir ertasi kuni ham yangi smena ocholmasdi
#      (chunki eskisi ochiq). Ya'ni cheklov do'konni qutqarish o'rniga
#      uni qulflab qo'yardi.
SAFE_RECOVERY: frozenset[str] = frozenset({SHIFT_CLOSE})

#: Barcha ma'lum toifalar — qo'riqchi test shu to'plamga tayanadi.
ALL_CATEGORIES: frozenset[str] = ALWAYS_ALLOWED | BUSINESS_WRITE | SAFE_RECOVERY


def is_allowed(category: str, effective_status: str | None, *, managed: bool) -> bool:
    """Shu toifadagi amal ruxsat etiladimi.

    `managed=False` (obuna yozuvi yo'q) -> HAR DOIM ruxsat: grandfathering.
    """
    if category not in ALL_CATEGORIES:
        raise ValueError(f"noma'lum toifa: {category!r} — matritsaga qo'shing")
    if not managed:
        return True
    if category in ALWAYS_ALLOWED or category in SAFE_RECOVERY:
        return True
    if effective_status == SubscriptionStatus.RESTRICTED.value:
        return False
    #  ACTIVE va GRACE — yozuv mumkin (GRACE da ogohlantirish bilan).
    return True
