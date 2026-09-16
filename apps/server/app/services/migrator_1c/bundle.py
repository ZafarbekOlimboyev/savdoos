# -*- coding: utf-8 -*-
"""1C eksport fayli — `binos-1c-v1`: yuklash, SHA256 tekshiruvi, qat'iy tiplar.

QOIDALAR (hammasi FAIL-CLOSED):
  · Fayl baytlarining SHA256'si qayta hisoblanadi va yonidagi `.sha256` bilan solishtiriladi.
  · Identifikator (guid, code, article, barkod, PLU) JSON SONI bo'lsa — butun fayl RAD.
    Sabab: `0000123` son sifatida `123` bo'lib qoladi va bu yo'qotishni keyin tiklab bo'lmaydi.
  · Miqdor va narx faqat MATN (`"12.500"`). JSON soni (float/int), NaN, Infinity qabul qilinmaydi.
  · Har darajada takror kalit — RAD. Noma'lum kalit — RAD (whitelist): yangi maydon faqat
    `schema_version` oshirilganda qo'shiladi, aks holda mazmun xeshi nimani qamrashi noaniq bo'lardi.
  · Manifestdagi qator sanoqlari fayl mazmuniga AYNAN teng bo'lmasa — RAD.
  · `exported_at` / `snapshot_at` — ISO 8601, VAQT ZONASI bilan.

Qiymat FORMATI (mahsulot GUID'i, Decimal matni) qator darajasida `normalize.py` da kodlanadi:
bitta buzuq qator butun eksportni yashirmasligi kerak.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext

from . import SCHEMA_VERSION, SOURCE_SYSTEM

UTF8_BOM = b"\xef\xbb\xbf"
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
KINDS = ("goods", "service", "set", "other")
STRUCT_GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
COUNT_RE = re.compile(r"[0-9]{1,12}")
_NUM_RE = re.compile(r"-?[0-9]{1,20}(?:\.[0-9]{1,12})?")

TOP_KEYS = {"schema_version", "source_system", "export_id", "exported_at", "snapshot_at", "infobase", "extractor",
            "warehouses", "price_types", "selection", "products", "manifest"}
INFOBASE_KEYS = {"platform_version", "configuration_name", "configuration_version", "infobase_id"}
EXTRACTOR_KEYS = {"name", "version"}
WAREHOUSE_KEYS = {"guid", "code", "name"}
SELECTION_KEYS = {"warehouse_guids", "retail_price_type_guid", "purchase_price_type_guid"}
PRODUCT_KEYS = {"guid", "code", "article", "name", "kind", "is_folder", "deletion_mark", "has_characteristics",
                "has_series", "unit", "is_weighted", "plu", "barcodes", "prices", "stock"}
UNIT_KEYS = {"name", "code"}
BARCODE_KEYS = {"value", "type"}
PRICE_KEYS = {"price_type_guid", "value"}
STOCK_KEYS = {"warehouse_guid", "qty"}
MANIFEST_KEYS = {"product_count", "barcode_count", "price_count", "stock_row_count", "stock_qty_by_warehouse"}


class BundleError(ValueError):
    """Fayl tuzilmasi buzuq yoki imzosi mos emas — quruq yurish HAM boshlanmaydi."""


@dataclass(frozen=True)
class Bundle:
    data: dict
    file_sha256: str
    content_sha256: str
    size_bytes: int

    @property
    def products(self) -> list[dict]:
        return self.data["products"]


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_sidecar(text: str) -> str:
    """`<hex>  fayl_nomi` yoki faqat `<hex>`. UTF-8 BOM (1C / PowerShell yozadi) e'tiborsiz."""
    tok = (text or "").lstrip("﻿").strip().split()
    if not tok or len(tok[0]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in tok[0]):
        raise BundleError("sha256 yon fayli yaroqsiz (64 belgili hex kutiladi)")
    return tok[0].lower()


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise BundleError(f"JSON obyektida takror kalit: {k!r}")
        out[k] = v
    return out


def _reject_float(s):
    raise BundleError(f"JSON son (float/NaN/Infinity) taqiqlangan: {s} — qiymatni MATN sifatida yozing")


def _reject_int(s):
    raise BundleError(f"JSON son (int) taqiqlangan: {s} — qiymatni MATN sifatida yozing")


def strict_json_loads(text: str, allow_int: bool = False):
    """Operator fayllari (hisobot, mapping, birlik jadvali) uchun ham AYNI qat'iylik:
    takror kalit, float, NaN/Infinity RAD. `allow_int` — hisobotdagi qator raqamlari uchun."""
    try:
        return json.loads(text, object_pairs_hook=_no_dupes, parse_float=_reject_float,
                          parse_int=(int if allow_int else _reject_int), parse_constant=_reject_float)
    except json.JSONDecodeError as e:
        raise BundleError(f"JSON buzuq: {e}") from e


# ── Tip tekshiruvi ─────────────────────────────────────────────────────────
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise BundleError(msg)


def _keys(obj: dict, allowed: set[str], where: str) -> None:
    extra = set(obj) - allowed
    _need(not extra, f"{where}: noma'lum kalit(lar) {sorted(extra)} — schema_version {SCHEMA_VERSION} da yo'q")


def _opt_str(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(v is None or isinstance(v, str), f"{where}.{key} matn yoki null bo'lishi kerak")


def _req_str(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(isinstance(v, str) and v.strip() != "", f"{where}.{key} bo'sh bo'lmagan matn bo'lishi kerak")


def _opt_bool(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(v is None or isinstance(v, bool), f"{where}.{key} true/false yoki null bo'lishi kerak")


def _struct_guid(v, where: str) -> None:
    _need(isinstance(v, str) and STRUCT_GUID_RE.fullmatch(v) is not None,
          f"{where} — kichik harfli kanonik GUID (8-4-4-4-12) bo'lishi kerak: {v!r}")


def parse_ts(v: str, where: str) -> datetime:
    try:
        ts = datetime.fromisoformat(v)
    except (TypeError, ValueError) as e:
        raise BundleError(f"{where} ISO 8601 emas: {v!r}") from e
    _need(ts.tzinfo is not None, f"{where} vaqt zonasi (offset) bilan bo'lishi kerak: {v!r}")
    return ts


def _validate(d: dict) -> None:
    _need(isinstance(d, dict), "ildiz JSON obyekt bo'lishi kerak")
    _keys(d, TOP_KEYS, "bundle")
    _need(d.get("schema_version") == SCHEMA_VERSION,
          f"schema_version '{d.get('schema_version')}' — faqat '{SCHEMA_VERSION}' qo'llanadi")
    _need(d.get("source_system") == SOURCE_SYSTEM, f"source_system faqat '{SOURCE_SYSTEM}'")
    for k in ("export_id", "exported_at", "snapshot_at"):
        _req_str(d, k, "bundle")
    parse_ts(d["exported_at"], "exported_at")
    parse_ts(d["snapshot_at"], "snapshot_at")
    for k, allowed in (("infobase", INFOBASE_KEYS), ("extractor", EXTRACTOR_KEYS), ("selection", SELECTION_KEYS),
                       ("manifest", MANIFEST_KEYS)):
        _need(isinstance(d.get(k), dict), f"bundle.{k} obyekt bo'lishi kerak")
        _keys(d[k], allowed, k)
    for k in ("platform_version", "configuration_name", "configuration_version"):
        _req_str(d["infobase"], k, "infobase")
    _opt_str(d["infobase"], "infobase_id", "infobase")
    for k in ("name", "version"):
        _req_str(d["extractor"], k, "extractor")
    for k in ("warehouses", "price_types", "products"):
        _need(isinstance(d.get(k), list), f"bundle.{k} ro'yxat bo'lishi kerak")
    for grp in ("warehouses", "price_types"):
        for i, w in enumerate(d[grp]):
            where = f"{grp}[{i}]"
            _need(isinstance(w, dict), f"{where} obyekt bo'lishi kerak")
            _keys(w, WAREHOUSE_KEYS, where)
            _struct_guid(w.get("guid"), where + ".guid")
            _opt_str(w, "code", where)
            _opt_str(w, "name", where)
    sel = d["selection"]
    _need(isinstance(sel.get("warehouse_guids"), list) and sel["warehouse_guids"],
          "selection.warehouse_guids — kamida bitta ombor GUID'i")
    for w in sel["warehouse_guids"]:
        _struct_guid(w, "selection.warehouse_guids[]")
    _need(len(set(sel["warehouse_guids"])) == len(sel["warehouse_guids"]), "selection.warehouse_guids ichida takror")
    _struct_guid(sel.get("retail_price_type_guid"), "selection.retail_price_type_guid")
    if sel.get("purchase_price_type_guid") is not None:
        _struct_guid(sel["purchase_price_type_guid"], "selection.purchase_price_type_guid")
        _need(sel["purchase_price_type_guid"] != sel["retail_price_type_guid"],
              "selection: kelish narxi turi chakana narx turi bilan BIR XIL — tannarx chakana narxga teng bo'lib qolardi")
    wh = {w["guid"] for w in d["warehouses"]}
    pt = {p["guid"] for p in d["price_types"]}
    _need(len(wh) == len(d["warehouses"]), "warehouses ichida takror GUID")
    _need(len(pt) == len(d["price_types"]), "price_types ichida takror GUID")
    _need(set(sel["warehouse_guids"]) <= wh, "selection.warehouse_guids ro'yxatda yo'q omborni ko'rsatadi")
    _need(sel["retail_price_type_guid"] in pt, "selection.retail_price_type_guid ro'yxatda yo'q")
    if sel.get("purchase_price_type_guid") is not None:
        _need(sel["purchase_price_type_guid"] in pt, "selection.purchase_price_type_guid ro'yxatda yo'q")

    for i, p in enumerate(d["products"]):
        where = f"products[{i}]"
        _need(isinstance(p, dict), f"{where} obyekt bo'lishi kerak")
        _keys(p, PRODUCT_KEYS, where)
        for k in ("guid", "code", "article", "name", "plu"):
            _opt_str(p, k, where)
        _need(p.get("kind") in KINDS, f"{where}.kind — {KINDS} dan biri")
        for k in ("is_folder", "deletion_mark", "has_characteristics", "has_series"):
            _need(isinstance(p.get(k), bool), f"{where}.{k} true/false bo'lishi kerak")
        _opt_bool(p, "is_weighted", where)
        u = p.get("unit")
        _need(u is None or isinstance(u, dict), f"{where}.unit obyekt yoki null")
        if isinstance(u, dict):
            _keys(u, UNIT_KEYS, where + ".unit")
            _opt_str(u, "name", where + ".unit")
            _opt_str(u, "code", where + ".unit")
        _need(isinstance(p.get("barcodes"), list), f"{where}.barcodes ro'yxat")
        for j, b in enumerate(p["barcodes"]):
            _need(isinstance(b, dict) and isinstance(b.get("value"), str),
                  f"{where}.barcodes[{j}].value matn bo'lishi kerak")
            _keys(b, BARCODE_KEYS, f"{where}.barcodes[{j}]")
            _opt_str(b, "type", f"{where}.barcodes[{j}]")
        _need(isinstance(p.get("prices"), list), f"{where}.prices ro'yxat")
        for j, pr in enumerate(p["prices"]):
            _need(isinstance(pr, dict), f"{where}.prices[{j}] obyekt")
            _keys(pr, PRICE_KEYS, f"{where}.prices[{j}]")
            _opt_str(pr, "value", f"{where}.prices[{j}]")
            _need(isinstance(pr.get("price_type_guid"), str) and pr["price_type_guid"] in pt,
                  f"{where}.prices[{j}] noma'lum narx turi")
        _need(len({pr["price_type_guid"] for pr in p["prices"]}) == len(p["prices"]),
              f"{where}.prices ichida bitta narx turi ikki marta")
        _need(isinstance(p.get("stock"), list), f"{where}.stock ro'yxat")
        for j, st in enumerate(p["stock"]):
            _need(isinstance(st, dict), f"{where}.stock[{j}] obyekt")
            _keys(st, STOCK_KEYS, f"{where}.stock[{j}]")
            _need(isinstance(st.get("qty"), str), f"{where}.stock[{j}].qty matn bo'lishi kerak")
            _need(isinstance(st.get("warehouse_guid"), str) and st["warehouse_guid"] in wh,
                  f"{where}.stock[{j}] noma'lum ombor")
        _need(len({st["warehouse_guid"] for st in p["stock"]}) == len(p["stock"]),
              f"{where}.stock ichida bitta ombor ikki marta")

    m = d["manifest"]
    for k in ("product_count", "barcode_count", "price_count", "stock_row_count"):
        _need(isinstance(m.get(k), str) and COUNT_RE.fullmatch(m[k]) is not None,
              f"manifest.{k} ASCII raqamli MATN bo'lishi kerak")
    counts = {
        "product_count": len(d["products"]),
        "barcode_count": sum(len(p["barcodes"]) for p in d["products"]),
        "price_count": sum(len(p["prices"]) for p in d["products"]),
        "stock_row_count": sum(len(p["stock"]) for p in d["products"]),
    }
    for k, v in counts.items():
        _need(int(m[k]) == v, f"manifest.{k}={m[k]}, faylda {v} — eksport to'liq emas yoki buzilgan")
    sq = m.get("stock_qty_by_warehouse")
    _need(isinstance(sq, dict), "manifest.stock_qty_by_warehouse obyekt")
    _need(set(sq) == set(sel["warehouse_guids"]),
          "manifest.stock_qty_by_warehouse AYNAN tanlangan omborlar uchun bo'lishi kerak")
    _need(all(isinstance(v, str) and _NUM_RE.fullmatch(v) for v in sq.values()),
          "manifest.stock_qty_by_warehouse qiymatlari Decimal MATN bo'lishi kerak")


# ── Kanonik mazmun xeshi (v2) ───────────────────────────────────────────────
def _canon_num(v):
    """Qiymati teng sonlar bir xil matn beradi ('12.500' == '12.5'); buzuq matn o'zicha qoladi."""
    if isinstance(v, str) and _NUM_RE.fullmatch(v):
        with localcontext() as ctx:
            ctx.prec = 60
            n = Decimal(v).normalize()
        s = format(n, "f")
        return "0" if s in ("-0", "0") else s
    return v


def _canon_guid_text(v):
    from .normalize import canon_guid
    g, _ = canon_guid(v)
    return g if g else v


def canonical_projection(d: dict) -> dict:
    """Mazmun xeshi hisoblanadigan KANONIK proyeksiya — ma'lum maydonlar, yo'q kalit = null."""
    def prod(p):
        u = p.get("unit") or None
        return {
            "guid": _canon_guid_text(p.get("guid")), "code": p.get("code"), "article": p.get("article"),
            "name": p.get("name"), "kind": p.get("kind"), "is_folder": p.get("is_folder"),
            "deletion_mark": p.get("deletion_mark"), "has_characteristics": p.get("has_characteristics"),
            "has_series": p.get("has_series"),
            "unit": None if u is None else {"name": u.get("name"), "code": u.get("code")},
            "is_weighted": p.get("is_weighted"), "plu": p.get("plu"),
            "barcodes": sorted(([b["value"].strip(), b.get("type")] for b in p["barcodes"]),
                               key=lambda x: (x[0], x[1] is None, x[1] or "")),
            "prices": sorted([pr["price_type_guid"], _canon_num(pr.get("value"))] for pr in p["prices"]),
            "stock": sorted([st["warehouse_guid"], _canon_num(st["qty"])] for st in p["stock"]),
        }
    sel = d["selection"]
    return {
        "schema_version": d["schema_version"], "source_system": d["source_system"],
        "snapshot_at": parse_ts(d["snapshot_at"], "snapshot_at").astimezone(timezone.utc).isoformat(),
        "warehouses": sorted([w["guid"], w.get("code"), w.get("name")] for w in d["warehouses"]),
        "price_types": sorted([p["guid"], p.get("code"), p.get("name")] for p in d["price_types"]),
        "selection": {"warehouse_guids": sorted(sel["warehouse_guids"]),
                      "retail_price_type_guid": sel["retail_price_type_guid"],
                      "purchase_price_type_guid": sel.get("purchase_price_type_guid")},
        "products": sorted(json.dumps(prod(p), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                           for p in d["products"]),
    }


def content_hash(d: dict) -> str:
    """Mazmun xeshi: fayl formatlanishi, qator tartibi, eksport vaqti/ID'si, extractor versiyasi,
    GUID harf registri, son yozuvi ('12.5' / '12.500') va null/yo'q kalit farqidan MUSTAQIL.
    Ko'plik saqlanadi: [X] va [X, X] turli xesh."""
    proj = canonical_projection(d)
    h = hashlib.sha256()
    h.update(b"binos-1c-content-v2\x00")
    head = {k: v for k, v in proj.items() if k != "products"}
    h.update(json.dumps(head, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    h.update(b"\x00" + str(len(proj["products"])).encode() + b"\x00")
    for line in proj["products"]:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def load_bytes(raw: bytes, expected_sha256: str | None) -> Bundle:
    """Baytlardan bundle. `expected_sha256` berilsa — mos kelishi SHART."""
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError(f"fayl juda katta: {len(raw)} bayt")
    file_sha = sha256_bytes(raw)
    if expected_sha256 is not None and file_sha != expected_sha256.lower():
        raise BundleError(f"SHA256 mos emas: fayl {file_sha}, kutilgan {expected_sha256.lower()}")
    body = raw[len(UTF8_BOM):] if raw.startswith(UTF8_BOM) else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise BundleError(f"fayl UTF-8 emas: {e}") from e
    data = strict_json_loads(text)
    try:                                   # JSON escape bilan kelgan yolg'iz surrogate UTF-8 ga yozilmaydi
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as e:
        raise BundleError(f"faylda UTF-8 bo'lmagan belgi (yolg'iz surrogate): {e.reason}") from e
    _validate(data)
    return Bundle(data=data, file_sha256=file_sha, content_sha256=content_hash(data), size_bytes=len(raw))


def load_file(path: str, sha256_path: str | None = None, require_sidecar: bool = True) -> Bundle:
    with open(path, "rb") as f:
        raw = f.read()
    expected = None
    sp = sha256_path or (path + ".sha256")
    try:
        with open(sp, encoding="utf-8-sig") as f:
            expected = read_sidecar(f.read())
    except FileNotFoundError:
        if require_sidecar:
            raise BundleError(f"SHA256 yon fayli topilmadi: {sp}") from None
    return load_bytes(raw, expected)
