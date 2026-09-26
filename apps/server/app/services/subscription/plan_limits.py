# -*- coding: utf-8 -*-
"""Tarif va uning limitlari — O'QISH TARTIBI (Phase 6A).

NEGA MIRROR EMAS
================
Tarif hozir IKKI joyda bo'lishi mumkin edi: yangi `subscriptions`/`plans` jadvallari va
eski `Setting(key='plan')` JSON qatori. Ikkalasiga ham YOZISH (mirror) ikki haqiqat manbai
demakdir — ular bir kun ajralib ketadi. Shu bois yozuv FAQAT bitta joyga boradi, o'qish esa
tartib bilan: obuna bo'lsa undan, aks holda eskisidan.

ESKI KODLARNING XARITASI
========================
Eski tarif kodlari (`api/v1/admin.py:_PLANS`) va ularning ANIQ, hujjatlashtirilgan ma'nosi
(`api/v1/branches.py:4` — «start = 1 filial · start+ = 5 filial · business = cheksiz (999)»):

    start   -> 1 filial,   10 xodim
    start+  -> 5 filial,   30 xodim
    business-> 999 filial, 999 xodim   (ya'ni ALLAQACHON cheksiz yuqori pog'ona)

⚠️  XARITA HECH QACHON LIMITNI KAMAYTIRMAYDI. Agar `start+` (5 filial) yangi `START` (1 filial)
    ga xaritalanganda, 3 filialli do'kon bir kechada limit buzuvchiga aylanardi. Shu bois
    pog'onalar TARTIBI saqlanadi:

    start    -> START
    start+   -> BUSINESS
    business -> NETWORK      (eski «cheksiz» yangi eng yuqori pog'onaga)

⚠️  BU XARITA MA'LUMOTNI QAYTA YOZMAYDI. U faqat (a) ko'rsatish va (b) adminni do'konni
    ro'yxatga olayotganda TAKLIF qilingan tarif uchun ishlatiladi. Ro'yxatga olinmagan
    do'kon limitlari ESKI jadvaldan o'qilishda davom etadi — ya'ni grandfathering avtomatik.
"""
from __future__ import annotations

#: Eski kod -> yangi kanonik kod. `start+` kanonik tarif EMAS, faqat alias.
LEGACY_PLAN_ALIAS: dict[str, str] = {
    "start": "START",
    "start+": "BUSINESS",
    "business": "NETWORK",
}

#: Kanonik tarif kodlari (yagona haqiqat manbai — `plans.code` shu to'plamdan).
CANONICAL_PLANS: tuple[str, ...] = ("PILOT", "START", "BUSINESS", "NETWORK")


#  ⚠️  IKKI NAMESPACE, IKKI FUNKSIYA — VA BU ATAYLAB.
#
#      `"business"` satri IKKALA namespace'da ham mavjud:
#        · ESKI kod `business`  = 999 filial / 999 xodim (ya'ni CHEKSIZ yuqori pog'ona),
#        · YANGI kanonik `BUSINESS` = o'rta pog'ona.
#
#      Bitta "aqlli" funksiya ularni satrdan ajrata OLMAYDI va eski `business` do'konini
#      jimgina yangi `BUSINESS` ga tushirardi — bu LIMIT KAMAYISHI, aynan biz taqiqlagan
#      narsa. Shu bois chaqiruvchi qiymat QAYSI manbadan kelganini AYTISHI shart:
#      `settings['plan']` dan kelgan qiymat -> `canonical_from_legacy`, admin/API dan
#      kelgan qiymat -> `canonical_plan_code`. Taxmin qiladigan uchinchi yo'l YO'Q.


def canonical_from_legacy(code: str | None) -> str | None:
    """ESKI namespace (`settings['plan']`) qiymatini kanonik kodga xaritalaydi.

    Faqat alias jadvalidan qaraydi. Yangi kanonik kod berilsa ham -> `None`
    (u eski qiymat emas, chaqiruvchi noto'g'ri funksiyani ishlatgan)."""
    if not code:
        return None
    return LEGACY_PLAN_ALIAS.get(code.strip().lower())


def canonical_plan_code(code: str | None) -> str | None:
    """YANGI namespace qiymatini tekshiradi (registrga sezgir emas).

    Eski kodni QABUL QILMAYDI: `"business"` -> `None`, chunki u yangi `BUSINESS`
    degani emas (yuqoridagi izoh)."""
    if not code:
        return None
    c = code.strip()
    #  Eski kod yangi kod qiyofasida kelib qolmasin: `business` va `start` ikkala
    #  namespace'da ham uchraydi, shu bois REGISTR ham hisobga olinadi — kanonik
    #  kodlar DOIM katta harfda yoziladi.
    return c if c in CANONICAL_PLANS else None
