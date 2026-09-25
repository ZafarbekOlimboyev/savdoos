# -*- coding: utf-8 -*-
"""TAROZI ETIKETKASI (vaznli EAN-13) — server tomondagi o'qish (Phase 5G, `GET /products/scan`).

⚠️  POS BILAN AYNAN BIR XIL QOIDA. Yagona manba — `packages/shared/src/lib/scaleBarcode.ts`
    (POS kassasi `POSKassa.tsx` shu moduldan o'qiydi). Bu fayl uning Python nusxasi va ikkalasi
    BITTA vektor fayli bilan tekshiriladi: `tests/fixtures/scale_barcodes.json` (repo ildizida)
    — vitest (`tests/scale-barcode.test.ts`) va pytest (`apps/server/tests/test_scale_barcodes.py`).
    Qoida o'zgarsa — IKKALASI va vektorlar birga o'zgaradi, aks holda sinov qizaradi.

FORMAT (Fayzan do'konidan olingan REAL etiketkalar bilan tasdiqlangan):

    27 + PLU(5) + GRAMM(5) + EAN-13 nazorat(1)   = 13 raqam

    · Prefiks AYNAN "27". Oldin faqat birinchi raqam ("2") tekshirilardi — u holda prefiksning
      ikkinchi raqami PLU maydoniga oqib kirib, PLU 700000 ga surilardi (2700537004264 -> 700537).
    · PLU — 5 xonali SATR, yetakchi nollar SAQLANADI: "00537". Songa AYLANTIRILMAYDI.
    · GRAMM maydoni (8-12-raqamlar) — VAZN, narx EMAS. Real etiketka dalili:
        2700537004264 -> 0.426 kg x 350 = 149.10 (etiketkada AYNAN shu summa)
        2700349000560 -> 0.056 kg x 580 =  32.48 (etiketkada AYNAN shu summa)
    · Gramm 0 bo'lsa etiketka VAZNLI deb qabul QILINMAYDI.
    · Nazorat raqami TEKSHIRILADI: mos kelmasa — tarozi etiketkasi emas (`None`).

ETIKETKADAGI KOD <-> BARKOD PLU <-> BinOS `plu_code` (chalkashmasin):

    etiketkada bosilgan KOD   000537   (6 xona, tarozi shunday chop etadi)
    barkod ichidagi PLU       00537    (5 xona — kanonik shakl, shu modul qaytaradi)
    BinOS `products.plu_code` 537      (yetakchi nolsiz — QA PC-013, DB da shunday saqlanadi)

Uchalasi BITTA tarozi tovarini bildiradi; `plu_matches` ikkala tomonni 5 xonaga to'ldirib
solishtiradi, shuning uchun DB dagi "537" etiketkadagi "00537" ga MOS keladi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NON_DIGIT = re.compile(r"[^0-9]")

#: Etiketka prefiksi — AYNAN shu ikki raqam.
SCALE_PREFIX = "27"
#: Kanonik PLU uzunligi (barkod ichidagi maydon).
PLU_DIGITS = 5


@dataclass(frozen=True)
class ScaleLabel:
    prefix: str
    plu: str        # AYNAN 5 belgi, yetakchi nollar bilan: "00537"
    grams: int
    checksum: int

    @property
    def qty(self) -> str:
        """Kilogramm, AYNAN 3 kasr xonali satr (float EMAS): 1234 g -> "1.234"."""
        return f"{self.grams // 1000}.{self.grams % 1000:03d}"


def digits_only(raw) -> str:
    """Faqat ASCII raqamlar (JS `/\\D/g` bilan AYNI; yetakchi nollar SAQLANADI).

    ⚠️  `str(raw or "")` EMAS: son `0` falsy bo'lgani uchun u bo'sh satrga aylanardi va
        PLU `0` hech qachon mos kelmasdi. JS tomoni `String(raw ?? "")` — faqat null/undefined
        ni almashtiradi, ya'ni bu satr parity nuqsonini yopadi (vektor: `plu_code` "0" ~ 0).
    """
    return _NON_DIGIT.sub("", "" if raw is None else str(raw))


def ean13_checksum(body12: str) -> int:
    """EAN-13 nazorat raqami: og'irliklar chapdan 1,3,1,3…; `(10 - sum % 10) % 10`."""
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(body12))
    return (10 - total % 10) % 10


def normalize_plu(raw) -> str | None:
    """PLU kanonik shakli: faqat raqamlar, 5 xonaga to'ldiriladi.

    "537" -> "00537" · "00537" -> "00537" · "12a" -> "00012" · "" yoki 6+ xona -> `None`.
    6 xonali kiritma ATAYLAB rad etiladi — etiketkada bosilgan 6 xonali KOD (000537) bilan
    chalkashmasin: barkod maydoni 5 xonali.
    """
    d = digits_only(raw)
    if not d or len(d) > PLU_DIGITS:
        return None
    return d.rjust(PLU_DIGITS, "0")


def parse(raw) -> ScaleLabel | None:
    """Vaznli etiketka bo'lsa `ScaleLabel`, aks holda `None`."""
    d = digits_only(raw)
    if len(d) != 13 or d[:2] != SCALE_PREFIX:
        return None
    checksum = int(d[12])
    if ean13_checksum(d[:12]) != checksum:
        return None
    grams = int(d[7:12])
    if grams <= 0:
        return None
    return ScaleLabel(prefix=SCALE_PREFIX, plu=d[2:7], grams=grams, checksum=checksum)


def plu_matches(plu_code, plu) -> bool:
    """Ikkala tomon 5 xonaga to'ldirilib solishtiriladi (POS `pluMatches` bilan AYNI)."""
    a, b = normalize_plu(plu_code), normalize_plu(plu)
    return a is not None and b is not None and a == b
