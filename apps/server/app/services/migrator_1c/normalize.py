# -*- coding: utf-8 -*-
"""Normallashtirish — 1C qatorini YO'QOTISHSIZ kanonik ko'rinishga keltirish.

Hech narsa "tuzatilmaydi" va jimgina o'zgartirilmaydi:
  · GUID    — faqat 8-4-4-4-12 hex shakli; katta harf -> kichik. Boshqa shakl = INVALID_GUID.
  · Decimal — faqat ASCII `-?[0-9]{1,20}(\\.[0-9]{1,12})?` (to'liq moslik). Ustun aniqligidan ortiq
              nol bo'lmagan xona = PRECISION_LOSS (yuvarlanmaydi). float UMUMAN ishlatilmaydi.
  · Barkod  — faqat chekka probel olinadi. Raqamdan boshqa belgi yoki 6-14 dan tashqari uzunlik
              = INVALID_BARCODE (belgilar O'CHIRILMAYDI). Oldingi nollar SAQLANADI.
  · Kod / artikul / PLU — matn; oldingi nollar SAQLANADI (PLU faqat BinOS qoidasi bo'yicha kanonik).
  · Birlik  — faqat ANIQ jadval orqali. Jadvalda yo'q = birlik kodi None (tasnifda UNKNOWN_UNIT).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NIL_GUID = "00000000-0000-0000-0000-000000000000"
DECIMAL_RE = re.compile(r"-?[0-9]{1,20}(?:\.[0-9]{1,12})?")
QTY_PLACES = 3                           # inventory.qty Numeric(14,3)
PRICE_PLACES = 2                         # products.base_*_price Numeric(14,2)
QTY_SCALE = Decimal("0.001")
PRICE_SCALE = Decimal("0.01")
QTY_MAX = Decimal("99999999999.999")
PRICE_MAX = Decimal("999999999999.99")

# ANIQ birlik jadvali — 1C nomi (kichik harf, oxirgi nuqtasiz) -> BinOS `units.code`.
DEFAULT_UNIT_NAMES = {
    "шт": "dona", "штука": "dona", "штук": "dona", "pcs": "dona", "dona": "dona",
    "кг": "kg", "килограмм": "kg", "kg": "kg",
    "л": "litr", "литр": "litr", "litr": "litr",
    "упак": "upak", "уп": "upak", "упаковка": "upak", "upak": "upak",
}
# OKEI (Общероссийский классификатор единиц измерения) — faqat nom BO'LMASA ishlatiladi.
DEFAULT_UNIT_OKEI = {"796": "dona", "166": "kg", "112": "litr", "778": "upak"}


def is_decimal_text(s) -> bool:
    return isinstance(s, str) and DECIMAL_RE.fullmatch(s) is not None


def canon_guid(raw):
    """-> (kanonik_guid | None, muammo_kodi | None)."""
    if raw is None or str(raw).strip() == "":
        return None, "MISSING_GUID"
    s = str(raw)
    if GUID_RE.fullmatch(s) is None:           # atrofidagi probel ham, qavs ham — RAD
        return None, "INVALID_GUID"
    g = s.lower()
    if g == NIL_GUID:
        return None, "INVALID_GUID"
    return g, None


def parse_decimal(raw):
    """-> (Decimal | None, muammo | None). None = qiymat YO'Q (muammo emas)."""
    if raw is None:
        return None, None
    if not is_decimal_text(raw):
        return None, "INVALID_NUMBER"
    return Decimal(raw), None


def fits_scale(d: Decimal, places: int) -> bool:
    """quantize ISHLATILMAYDI (28 xonadan katta sonlarda InvalidOperation beradi)."""
    with localcontext() as ctx:
        ctx.prec = 60
        exp = d.normalize().as_tuple().exponent
    return exp >= -places


_UNIT_TAIL = re.compile(r"[\s.]+$")


def norm_unit_key(name: str) -> str:
    """IDEMPOTENT: `norm(norm(x)) == norm(x)` — dry-run va apply jadvali AYNI kalitlardan quriladi."""
    return _UNIT_TAIL.sub("", (name or "").strip().lower())


@dataclass
class NBarcode:
    raw: str
    value: str
    type: str | None
    valid: bool
    search_keys: tuple[str, ...]      # FAQAT nomzod/egalik qidirish uchun (saqlanmaydi)


@dataclass
class NProduct:
    idx: int
    guid: str | None
    guid_raw: str | None
    code: str | None
    article: str | None
    name: str | None
    kind: str
    is_folder: bool
    deletion_mark: bool
    has_characteristics: bool
    has_series: bool
    unit_source: str | None
    unit_okei: str | None
    unit_code: str | None
    is_weighted: bool
    plu_source: str | None
    plu: str | None
    barcodes: list[NBarcode]
    barcodes_dup_dropped: int
    retail_price: Decimal | None
    retail_status: str                          # absent | invalid | negative | zero | positive
    purchase_price: Decimal | None              # 0 -> None (BinOS kelish narxi "0" bilan USTIGA YOZILMAYDI)
    purchase_status: str                        # not_selected | absent | invalid | negative | zero | positive
    stock_by_warehouse: dict[str, Decimal]      # FAQAT tanlangan omborlar
    stock_unselected: dict[str, Decimal]        # tanlanmagan omborlar (hisobotda ko'rinadi, migratsiya qilinmaydi)
    stock_total: Decimal
    stock_rows_selected: int
    negative_stock_rows: int = 0
    invalid_qty_rows: int = 0
    invalid_qty_unselected_rows: int = 0
    block: set[str] = field(default_factory=set)      # apply'ni to'xtatadi
    decide: set[str] = field(default_factory=set)     # operator qarori / siyosat kerak
    info: set[str] = field(default_factory=set)       # faqat ma'lumot


def _clean_text(raw, p: NProduct):
    if raw is None:
        return None
    s = str(raw)
    t = s.strip()
    if t != s:
        p.info.add("WHITESPACE_TRIMMED")
    return t or None


def normalize_barcode(raw: str, typ: str | None) -> NBarcode:
    v = raw.strip()
    valid = v.isascii() and v.isdigit() and 6 <= len(v) <= 14
    keys: tuple[str, ...] = ()
    if valid:
        k = {v}
        if len(v) == 12:
            k.add("0" + v)                      # UPC-A <-> EAN-13 (bitta GTIN)
        if len(v) == 13 and v.startswith("0"):
            k.add(v[1:])
        keys = tuple(sorted(k))
    return NBarcode(raw=raw, value=v, type=typ, valid=valid, search_keys=keys)


def gtin_key(value: str) -> str:
    """To'qnashuvlarni sanash uchun YAGONA kanonik kalit (12 va 0+12 xonali — bitta GTIN)."""
    if value.isascii() and value.isdigit() and len(value) in (12, 13):
        return value.zfill(13)
    return value


def build_unit_table(extra_names: dict[str, str] | None) -> dict[str, str]:
    table = dict(DEFAULT_UNIT_NAMES)
    if extra_names:
        norm: dict[str, str] = {}
        for k, v in extra_names.items():
            if not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip():
                raise ValueError(f"birlik jadvali: kalit va qiymat bo'sh bo'lmagan matn bo'lishi kerak ({k!r}: {v!r})")
            nk = norm_unit_key(k)
            if not nk:
                raise ValueError(f"birlik jadvali: kalit normallashganda bo'sh bo'ladi ({k!r})")
            if nk in norm and norm[nk] != v:
                raise ValueError(f"birlik jadvali: '{k}' normallashganda boshqa kalit bilan to'qnashadi ({nk})")
            norm[nk] = v
        table.update(norm)
    return table


def resolve_unit(unit: dict | None, table: dict[str, str]):
    """-> (manba_nomi, okei, binos_code | None). Jadvalda yo'q -> binos_code None."""
    if not unit:
        return None, None, None
    name = (unit.get("name") or "").strip()
    okei = (unit.get("code") or "").strip() or None
    if name:
        return name, okei, table.get(norm_unit_key(name))
    return None, okei, DEFAULT_UNIT_OKEI.get(okei or "")


def normalize_product(idx: int, p: dict, selection: dict, table: dict[str, str]) -> NProduct:
    guid, gprob = canon_guid(p.get("guid"))
    np = NProduct(
        idx=idx, guid=guid, guid_raw=p.get("guid"), code=None, article=None, name=None,
        kind=p["kind"], is_folder=p["is_folder"], deletion_mark=p["deletion_mark"],
        has_characteristics=p["has_characteristics"], has_series=p["has_series"],
        unit_source=None, unit_okei=None, unit_code=None, is_weighted=False,
        plu_source=p.get("plu"), plu=None, barcodes=[], barcodes_dup_dropped=0, retail_price=None,
        retail_status="absent", purchase_price=None, purchase_status="not_selected",
        stock_by_warehouse={}, stock_unselected={},
        stock_total=Decimal("0"), stock_rows_selected=0)
    if gprob:
        np.block.add(gprob)
    np.code = _clean_text(p.get("code"), np)
    np.article = _clean_text(p.get("article"), np)
    np.name = _clean_text(p.get("name"), np)
    if not np.name:
        np.block.add("MISSING_NAME")

    np.unit_source, np.unit_okei, np.unit_code = resolve_unit(p.get("unit"), table)
    np.is_weighted = bool(p["is_weighted"]) if p.get("is_weighted") is not None else (np.unit_code == "kg")

    if p.get("plu") is not None:
        s = p["plu"].strip()
        if s.isascii() and s.isdigit() and 1 <= len(s) <= 5:
            np.plu = str(int(s))
            if np.plu != s:
                np.info.add("PLU_LEADING_ZEROS")
        elif s:
            np.decide.add("INVALID_PLU")

    seen: set[str] = set()
    for b in p["barcodes"]:
        nb = normalize_barcode(b["value"], b.get("type"))
        if nb.value != nb.raw:
            np.info.add("WHITESPACE_TRIMMED")
        if nb.value in seen:
            np.info.add("DUPLICATE_BARCODE_IN_ROW")
            np.barcodes_dup_dropped += 1
            continue
        seen.add(nb.value)
        if not nb.valid:
            np.decide.add("INVALID_BARCODE")
        np.barcodes.append(nb)

    by_type = {pr["price_type_guid"]: pr.get("value") for pr in p["prices"]}
    rp, prob = parse_decimal(by_type.get(selection["retail_price_type_guid"]))
    if prob:
        np.block.add("INVALID_PRICE")
        np.retail_status = "invalid"
    elif rp is None:
        np.decide.add("MISSING_PRICE")
        np.retail_status = "absent"
    else:
        np.retail_price = rp
        if rp < 0:
            np.block.add("NEGATIVE_PRICE")
            np.retail_status = "negative"
        elif rp == 0:
            np.decide.add("ZERO_PRICE")
            np.retail_status = "zero"
        else:
            np.retail_status = "positive"
        if abs(rp) > PRICE_MAX:
            np.block.add("PRICE_OUT_OF_RANGE")
        elif not fits_scale(rp, PRICE_PLACES):
            np.block.add("PRECISION_LOSS_PRICE")
    pur_guid = selection.get("purchase_price_type_guid")
    if pur_guid:
        pp, prob = parse_decimal(by_type.get(pur_guid))
        if prob:
            np.block.add("INVALID_PURCHASE_PRICE")
            np.purchase_status = "invalid"
        elif pp is None:
            np.info.add("MISSING_PURCHASE_PRICE")
            np.purchase_status = "absent"
        else:
            if pp < 0:
                np.block.add("NEGATIVE_PURCHASE_PRICE")
                np.purchase_status = "negative"
            elif pp == 0:
                # 1C'da to'ldirilmagan kelish narxi odatda "0": BinOS tannarxini nol bilan almashtirish
                # COGS'ni nolga tushirardi. Qiymat YOZILMAYDI va bu hisobotda ko'rinadi.
                np.info.add("ZERO_PURCHASE_PRICE")
                np.purchase_status = "zero"
            else:
                np.purchase_status = "positive"
            if abs(pp) > PRICE_MAX:
                np.block.add("PRICE_OUT_OF_RANGE")
            elif not fits_scale(pp, PRICE_PLACES):
                np.block.add("PRECISION_LOSS_PRICE")
            np.purchase_price = pp if pp != 0 else None
    if any(v is not None for k, v in by_type.items() if k not in {selection["retail_price_type_guid"], pur_guid}):
        np.info.add("PRICE_FOR_UNSELECTED_TYPE")

    selected = set(selection["warehouse_guids"])
    total = Decimal("0")
    for st in p["stock"]:
        q, prob = parse_decimal(st["qty"])
        if st["warehouse_guid"] not in selected:
            if prob or q is None:
                np.invalid_qty_unselected_rows += 1
                np.info.add("INVALID_QTY_UNSELECTED_WAREHOUSE")
            else:
                np.stock_unselected[st["warehouse_guid"]] = q
            continue
        np.stock_rows_selected += 1
        if prob or q is None:
            np.block.add("INVALID_QTY")
            np.invalid_qty_rows += 1
            continue
        if abs(q) > QTY_MAX:
            np.block.add("QTY_OUT_OF_RANGE")
        elif not fits_scale(q, QTY_PLACES):
            np.block.add("PRECISION_LOSS_QTY")
        np.stock_by_warehouse[st["warehouse_guid"]] = q
        total += q
        if q < 0:
            np.decide.add("NEGATIVE_STOCK")
            np.negative_stock_rows += 1
    np.stock_total = total
    has_unselected = bool(np.stock_unselected) or np.invalid_qty_unselected_rows > 0
    if np.stock_rows_selected == 0:
        np.info.add("STOCK_ONLY_IN_UNSELECTED_WAREHOUSE" if has_unselected else "MISSING_STOCK")
    elif has_unselected:
        np.info.add("STOCK_IN_UNSELECTED_WAREHOUSE")
    if np.stock_rows_selected > 0 and np.invalid_qty_rows == 0 and all(q == 0 for q in np.stock_by_warehouse.values()):
        np.info.add("ZERO_STOCK")
    if abs(total) > QTY_MAX:
        np.block.add("QTY_OUT_OF_RANGE")

    if np.has_characteristics:
        np.block.add("CHARACTERISTICS_UNSUPPORTED")
    if np.has_series:
        np.info.add("LOT_DATA_PRESENT")
    return np


def normalize_bundle(data: dict, unit_names: dict[str, str] | None = None) -> list[NProduct]:
    table = build_unit_table(unit_names)
    return [normalize_product(i, p, data["selection"], table) for i, p in enumerate(data["products"])]
