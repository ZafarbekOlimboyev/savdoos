# -*- coding: utf-8 -*-
"""TAROZI ETIKETKASI (vaznli EAN-13) — server tomondagi o'qish (Phase 5G, `GET /products/scan`).

⚠️  POS BILAN AYNAN BIR XIL QOIDA. Yagona manba — `packages/shared/src/lib/scaleBarcode.ts`
    (POS kassasi `POSKassa.tsx` shu moduldan o'qiydi). Bu fayl uning Python nusxasi va ikkalasi
    BITTA vektor fayli bilan tekshiriladi: `tests/fixtures/scale_barcodes.json` (repo ildizida)
    — vitest (`tests/scale-barcode.test.ts`) va pytest (`apps/server/tests/test_scale_barcodes.py`).
    Qoida o'zgarsa — IKKALASI va vektorlar birga o'zgaradi, aks holda sinov qizaradi.

FORMAT: 13 raqam, birinchisi "2":  2 + PLU(6) + gramm(5) + nazorat(1).
    · Nazorat raqami TEKSHIRILMAYDI (POS xulqi).
    · Gramm 0 bo'lsa etiketka VAZNLI deb qabul QILINMAYDI (POS `grams > 0` sharti).
    · PLU mahsulotning `plu_code` i bilan JS `parseInt(String(plu_code), 10)` semantikasida
      solishtiriladi — ya'ni yetakchi nollar va oxiridagi raqam bo'lmagan qism e'tiborsiz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NON_DIGIT = re.compile(r"[^0-9]")
# JS `parseInt(s, 10)`: boshidagi bo'shliqni tashlaydi, ixtiyoriy ishora, keyin ASCII raqamlar.
_JS_INT = re.compile(r"\s*([+-]?)([0-9]+)")


@dataclass(frozen=True)
class ScaleLabel:
    plu: int
    grams: int

    @property
    def qty(self) -> str:
        """Kilogramm, AYNAN 3 kasr xonali satr (float EMAS): 1234 g -> "1.234"."""
        return f"{self.grams // 1000}.{self.grams % 1000:03d}"


def digits_only(raw) -> str:
    """Faqat ASCII raqamlar (JS `/\\D/g` bilan AYNI; yetakchi nollar SAQLANADI)."""
    return _NON_DIGIT.sub("", str(raw or ""))


def parse(raw) -> ScaleLabel | None:
    """Vaznli etiketka bo'lsa `ScaleLabel`, aks holda `None`."""
    d = digits_only(raw)
    if len(d) != 13 or d[0] != "2":
        return None
    plu, grams = int(d[1:7]), int(d[7:12])
    if grams <= 0:
        return None
    return ScaleLabel(plu=plu, grams=grams)


def js_parse_int(value) -> int | None:
    """JS `parseInt(String(value), 10)`; NaN -> `None`."""
    m = _JS_INT.match(str(value))
    if not m:
        return None
    n = int(m.group(2))
    return -n if m.group(1) == "-" else n


def plu_matches(plu_code, plu: int) -> bool:
    """POS: `p.plu_code && parseInt(String(p.plu_code), 10) === pluNum`."""
    if not plu_code:
        return False
    return js_parse_int(plu_code) == plu
