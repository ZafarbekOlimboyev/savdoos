# -*- coding: utf-8 -*-
"""Parol siyosati — do'konni boshqaradigan hisoblar uchun.

⚠️  ILGARI: yagona shart `len(new) < 6` edi. Ya'ni `123456`, `parol1`, `qwerty`
    kabi qiymatlar do'konning BUTUN boshqaruvini himoya qilardi.

TANLOV: uzunlik + ma'lum arzon qiymatlarni rad etish. "Kamida bitta katta harf,
bitta raqam va bitta belgi" kabi retsept ATAYLAB YO'Q — u odamlarni `Parol1!`
kabi taxmin qilinadigan naqshlarga majburlaydi va entropiyaga deyarli qo'shmaydi.
Uzun ibora (passphrase) esa ruxsat etiladi va rag'batlantiriladi.

⚠️  MAKSIMAL UZUNLIK — bu XAVFSIZLIK sharti, qulaylik emas:

    1) bcrypt kirishning FAQAT dastlabki 72 BAYTINI hisobga oladi. `hash_password`
       uzunini qo'lda qisqartiradi, ya'ni 200 belgilik paroldan faqat 72 bayti
       ahamiyatli — foydalanuvchi buni BILMASDAN o'zini himoyalangan deb o'ylardi.
    2) Chegarasiz parol — hisoblash DoS yuzasi: har urinish bcrypt'ni ishga
       tushiradi va juda uzun kirish qo'shimcha xotira/CPU yeydi.

    Shu bois 72 BAYTdan uzun parol JIM QISQARTIRILMAYDI — aniq rad etiladi.
"""
from __future__ import annotations

import re
import unicodedata

MIN_LEN = 12          # boshqaruv hisobi uchun; ibora yozish oson
MAX_BYTES = 72        # bcrypt hisobga oladigan chegara (jim qisqartirish YO'Q)
MIN_UNIQUE = 4        # "aaaaaaaaaaaa" kabi qiymatlarni to'sadi

# Ochiq ro'yxatlarda eng ko'p uchraydigan va standart qiymatlar.
_TRIVIAL = frozenset({
    "password", "passw0rd", "parol", "parool", "qwerty", "qwertyuiop",
    "123456", "1234567", "12345678", "123456789", "1234567890",
    "admin", "administrator", "root", "letmein", "welcome", "iloveyou",
    "changeme", "change-me", "secret", "default", "test", "testing",
    "savdoos", "kassa", "dokon", "magazin", "abc123", "111111", "000000",
})


def password_policy_problem(raw: str | None) -> str | None:
    """Siyosatni buzsa — SABABNI qaytaradi, aks holda None.

    Parolning O'ZI hech qachon qaytarilmaydi va loglanmaydi."""
    pw = raw or ""
    if not pw:
        return "bo'sh"

    nbytes = len(pw.encode("utf-8"))
    if nbytes > MAX_BYTES:
        # ⚠️  JIM QISQARTIRMAYMIZ: foydalanuvchi 200 belgilik parol qo'ydim deb
        #     o'ylab, aslida 72 bayt bilan himoyalangan bo'lardi.
        return (f"juda uzun ({nbytes} bayt, ko'pi bilan {MAX_BYTES}) — "
                "bcrypt undan ortig'ini hisobga olmaydi")
    if len(pw) < MIN_LEN:
        return f"juda qisqa ({len(pw)} belgi, kamida {MIN_LEN} kerak)"

    norm = unicodedata.normalize("NFKC", pw).casefold()
    stripped = re.sub(r"[^a-z0-9]", "", norm)
    if norm in _TRIVIAL or stripped in _TRIVIAL:
        return "juda ko'p uchraydigan qiymat"
    for t in _TRIVIAL:
        if len(t) >= 5 and stripped.startswith(t):
            return "ma'lum arzon qiymatdan boshlanadi"

    if len(set(pw)) < MIN_UNIQUE:
        return f"entropiyasi past ({len(set(pw))} xil belgi) — takrorlanuvchi naqsh"

    # Ketma-ket bir xil belgilar yoki oddiy o'suvchi ketma-ketlik
    if re.search(r"(.)\1{5,}", pw):
        return "bir xil belgi ketma-ket takrorlanadi"
    return None
