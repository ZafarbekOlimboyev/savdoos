# -*- coding: utf-8 -*-
"""QURUQ YURISH — har 1C qatorini tasniflaydi va rekonsiliatsiya qiladi. BAZAGA YOZMAYDI.

ASOSIY TOIFA (har qator AYNAN bittasida; ustuvorlik yuqoridan pastga):
  EXCLUDED       papka / o'chirish belgisi / tovar emas — migratsiyaga kirmaydi
  BLOCKED        tuzatib bo'lmaydigan muammo (GUID yo'q/buzuq/takror, saqlangan identitet buzuq,
                 fayl ichida barkod to'qnashuvi, aniqlik yo'qolishi, xarakteristika...)
  DELETED_MATCH  maqsad — o'chirilgan BinOS mahsuloti: REACTIVATE yoki SKIP (yoki CREATE) qarori kerak
  AMBIGUOUS      bir nechta nomzod, dalillar ziddiyati, nomzod BOSHQA identitetga tegishli
                 (IDENTITY_CONFLICT) yoki bir nechta qator bitta mahsulotni ko'rsatadi (MANY_TO_ONE)
  EXACT_MATCH    (company_id, '1c', GUID) BinOS'da bor — yagona avtomatik bog'lanish
  CANDIDATE      GUID yo'q, lekin artikul/barkod/nom/PLU AYNAN bitta bo'sh mahsulotni ko'rsatadi.
                 ⚠️  BU BOG'LANISH EMAS: operator ANIQ `LINK` qarori bermaguncha hech narsa
                     birlashtirilmaydi.
  NEW            hech qanday dalil yo'q — yangi mahsulot taklifi

Qo'shimcha kodlar: `block` (apply'ni to'xtatadi), `decide` (siyosat/qaror kerak), `info`.
Har nomzod uchun FAKTLAR (birlik, nom farqi, identitet, partiya, qoldiq, barkodlar) hisobotga
yoziladi — reja (mapping.py) qaysi mahsulot tanlansa ham AYNI darvozalarni shu faktlar bo'yicha
qo'llaydi. Hisobot DETERMINISTIK; `report_sha256` vaqt belgilarisiz hisoblanadi.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, localcontext

from . import REPORT_SCHEMA_VERSION, SCHEMA_VERSION
from .bundle import Bundle, parse_ts
from .catalog import CatalogSnapshot, barcode_owners, plu_key
from .normalize import (NIL_GUID, NProduct, build_unit_table, gtin_key, norm_unit_key,
                        normalize_product)

PRIMARY = ("EXCLUDED", "BLOCKED", "DELETED_MATCH", "AMBIGUOUS", "EXACT_MATCH", "CANDIDATE", "NEW")
TARGETED = ("EXACT_MATCH", "CANDIDATE", "DELETED_MATCH")
ZERO = Decimal("0")


def _d(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


def _row_sort_key(n: NProduct):
    return (0 if n.guid else 1, n.guid or "", n.code or "", n.article or "", n.name or "", n.idx)


def exclusion_reason(n: NProduct) -> str | None:
    if n.is_folder:
        return "folder"
    if n.deletion_mark:
        return "deletion_mark"
    if n.kind != "goods":
        return f"kind:{n.kind}"
    return None


# ── Rekonsiliatsiya: XOM fayldan MUSTAQIL hisob (normalizer ishlatilmaydi) ────
_RAW_NUM = re.compile(r"-?[0-9]{1,20}(?:\.[0-9]{1,12})?")
_MANIFEST_NUM = re.compile(r"-?[0-9]{1,40}(?:\.[0-9]{1,12})?")      # N qator yig'indisi 20 xonadan oshishi mumkin
_RAW_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _raw_num(s) -> Decimal | None:
    return Decimal(s) if isinstance(s, str) and _RAW_NUM.fullmatch(s) else None


def raw_totals(data: dict) -> dict:
    sel = data["selection"]
    selected = sorted(set(sel["warehouse_guids"]))
    retail = sel["retail_price_type_guid"]
    purchase = sel.get("purchase_price_type_guid")
    all_wh = sorted({w["guid"] for w in data["warehouses"]})
    by_wh_all = {w: ZERO for w in all_wh}
    rows_wh_all = {w: 0 for w in all_wh}
    guids: set[str] = set()
    bad_guid = bc = invalid_qty_sel = invalid_qty_unsel = neg_rows_sel = 0
    status = Counter()
    pstatus = Counter()
    prices: list[Decimal] = []
    for p in data["products"]:
        g = p.get("guid")
        if isinstance(g, str) and _RAW_GUID.fullmatch(g) and g.lower() != NIL_GUID:
            guids.add(g.lower())
        else:
            bad_guid += 1
        bc += len(p["barcodes"])
        pv = next((x.get("value") for x in p["prices"] if x["price_type_guid"] == retail), None)
        if pv is None:
            status["absent"] += 1
        else:
            v = _raw_num(pv)
            if v is None:
                status["invalid"] += 1
            else:
                prices.append(v)
                status["negative" if v < 0 else "zero" if v == 0 else "positive"] += 1
        if purchase is None:
            pstatus["not_selected"] += 1
        else:
            pp = next((x.get("value") for x in p["prices"] if x["price_type_guid"] == purchase), None)
            pv2 = _raw_num(pp) if pp is not None else None
            pstatus["absent" if pp is None else "invalid" if pv2 is None else
                    "negative" if pv2 < 0 else "zero" if pv2 == 0 else "positive"] += 1
        for st in p["stock"]:
            w = st["warehouse_guid"]
            rows_wh_all[w] += 1
            q = _raw_num(st["qty"])
            if q is None:
                if w in selected:
                    invalid_qty_sel += 1
                else:
                    invalid_qty_unsel += 1
                continue
            by_wh_all[w] += q
            if w in selected and q < 0:
                neg_rows_sel += 1
    return {
        "sku_count": len(data["products"]),
        "guid_valid_distinct": len(guids),
        "guid_missing_or_invalid_rows": bad_guid,
        "barcode_entries": bc,
        "retail_price_absent": status["absent"], "retail_price_invalid": status["invalid"],
        "retail_price_zero": status["zero"], "retail_price_negative": status["negative"],
        "retail_price_positive": status["positive"],
        "retail_price_min": _d(min(prices)) if prices else None,
        "retail_price_max": _d(max(prices)) if prices else None,
        **{f"purchase_price_{k}": pstatus[k] for k in PURCHASE_STATUSES},
        "stock_by_warehouse": {w: _d(by_wh_all[w]) for w in selected},
        "stock_total_qty": _d(sum((by_wh_all[w] for w in selected), ZERO)),
        "stock_unselected_total_qty": _d(sum((v for w, v in by_wh_all.items() if w not in selected), ZERO)),
        "stock_by_warehouse_all": {w: _d(v) for w, v in by_wh_all.items()},
        "stock_rows_by_warehouse_all": dict(rows_wh_all),
        "invalid_qty_rows_selected": invalid_qty_sel,
        "invalid_qty_rows_unselected": invalid_qty_unsel,
        "negative_stock_rows_selected": neg_rows_sel,
    }


PURCHASE_STATUSES = ("not_selected", "absent", "invalid", "negative", "zero", "positive")


def bucket_totals(ns: list[NProduct], selected: list[str]) -> dict:
    by_wh = {w: ZERO for w in selected}
    unsel = ZERO
    for n in ns:
        for w, q in n.stock_by_warehouse.items():
            by_wh[w] += q
        unsel += sum(n.stock_unselected.values(), ZERO)
    status = Counter(n.retail_status for n in ns)
    pstatus = Counter(n.purchase_status for n in ns)
    prices = [n.retail_price for n in ns if n.retail_price is not None]
    return {
        "sku_count": len(ns),
        "guid_valid_distinct": len({n.guid for n in ns if n.guid}),
        "guid_missing_or_invalid_rows": sum(1 for n in ns if not n.guid),
        "barcode_entries": sum(len(n.barcodes) + n.barcodes_dup_dropped for n in ns),
        "barcodes_kept": sum(len(n.barcodes) for n in ns),
        "barcodes_valid_kept": sum(1 for n in ns for b in n.barcodes if b.valid),
        "barcodes_valid_distinct": len({b.value for n in ns for b in n.barcodes if b.valid}),
        "barcode_duplicates_dropped": sum(n.barcodes_dup_dropped for n in ns),
        "retail_price_absent": status["absent"], "retail_price_invalid": status["invalid"],
        "retail_price_zero": status["zero"], "retail_price_negative": status["negative"],
        "retail_price_positive": status["positive"],
        "retail_price_min": _d(min(prices)) if prices else None,
        "retail_price_max": _d(max(prices)) if prices else None,
        **{f"purchase_price_{k}": pstatus[k] for k in PURCHASE_STATUSES},
        "stock_by_warehouse": {w: _d(v) for w, v in by_wh.items()},
        "stock_total_qty": _d(sum(by_wh.values(), ZERO)),
        "stock_unselected_total_qty": _d(unsel),
        "invalid_qty_rows_selected": sum(n.invalid_qty_rows for n in ns),
        "invalid_qty_rows_unselected": sum(n.invalid_qty_unselected_rows for n in ns),
        "negative_stock_rows_selected": sum(n.negative_stock_rows for n in ns),
        "negative_stock_products": sum(1 for n in ns if n.negative_stock_rows),
        "zero_stock_products": sum(1 for n in ns if "ZERO_STOCK" in n.info),
        "missing_stock_products": sum(1 for n in ns if n.stock_rows_selected == 0),
    }


def _dec_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return Decimal(a) == Decimal(b)


def reconcile(data: dict, rows: list[NProduct], bucket_of: dict[int, str]) -> dict:
    """Hisob ayniyati: XOM 1C = migratsiyaga yaroqli (BinOS preview) + BLOCKED + EXCLUDED."""
    selected = sorted(set(data["selection"]["warehouse_guids"]))
    raw = raw_totals(data)
    names = ("migratable", "blocked", "excluded")
    b = {k: bucket_totals([n for n in rows if bucket_of[n.idx] == k], selected) for k in names}
    ids: dict[str, dict] = {}

    def ident(key, rawv, parts, dec=False):
        s = sum((Decimal(p) for p in parts), ZERO) if dec else sum(parts)
        ok = _dec_eq(rawv, _d(s)) if dec else rawv == s
        ids[key] = {"raw": rawv, "sum_of_buckets": _d(s) if dec else s, "ok": ok}

    for k in ("sku_count", "guid_missing_or_invalid_rows", "barcode_entries", "retail_price_absent",
              "retail_price_invalid", "retail_price_zero", "retail_price_negative", "retail_price_positive",
              "invalid_qty_rows_selected", "invalid_qty_rows_unselected", "negative_stock_rows_selected",
              *(f"purchase_price_{k}" for k in PURCHASE_STATUSES)):
        ident(k, raw[k], [b[x][k] for x in names])
    all_guids = {n.guid for n in rows if n.guid}
    ids["guid_valid_distinct"] = {"raw": raw["guid_valid_distinct"], "sum_of_buckets": len(all_guids),
                                  "ok": raw["guid_valid_distinct"] == len(all_guids)}
    for w in selected:
        ident(f"stock_qty[{w}]", raw["stock_by_warehouse"][w], [b[x]["stock_by_warehouse"][w] for x in names], dec=True)
    ident("stock_total_qty", raw["stock_total_qty"], [b[x]["stock_total_qty"] for x in names], dec=True)
    ident("stock_unselected_total_qty", raw["stock_unselected_total_qty"],
          [b[x]["stock_unselected_total_qty"] for x in names], dec=True)
    pmins = [b[x]["retail_price_min"] for x in names if b[x]["retail_price_min"] is not None]
    pmaxs = [b[x]["retail_price_max"] for x in names if b[x]["retail_price_max"] is not None]
    ids["retail_price_min"] = {"raw": raw["retail_price_min"], "sum_of_buckets": _d(min(map(Decimal, pmins))) if pmins else None,
                               "ok": _dec_eq(raw["retail_price_min"], _d(min(map(Decimal, pmins))) if pmins else None)}
    ids["retail_price_max"] = {"raw": raw["retail_price_max"], "sum_of_buckets": _d(max(map(Decimal, pmaxs))) if pmaxs else None,
                               "ok": _dec_eq(raw["retail_price_max"], _d(max(map(Decimal, pmaxs))) if pmaxs else None)}
    mcheck = manifest_check(data, raw)
    ok = all(v["ok"] for v in ids.values()) and mcheck["stock_qty_by_warehouse_ok"]
    return {"source_1c_raw": raw, "buckets": b, "binos_preview": b["migratable"], "identities": ids,
            "manifest": mcheck, "ok": ok}


def manifest_check(data: dict, raw: dict) -> dict:
    declared = data["manifest"]["stock_qty_by_warehouse"]
    diffs = {}
    for w in sorted(set(declared) | set(raw["stock_by_warehouse"])):
        dv, rv = declared.get(w), raw["stock_by_warehouse"].get(w)
        if not (isinstance(dv, str) and _MANIFEST_NUM.fullmatch(dv) and rv is not None and Decimal(dv) == Decimal(rv)):
            diffs[w] = {"manifest": dv, "recomputed": rv}
    return {"counts_verified_at_load": True, "stock_qty_by_warehouse_ok": not diffs, "diffs": diffs}


# ── Asosiy tasniflash ───────────────────────────────────────────────────────
def _lot(p: dict) -> bool:
    return bool(p["track_lots"] or p["track_expiry"] or p["lots_activated"])


def _facts(snap: CatalogSnapshot, pid: str, n: NProduct, evidence: set[str], norm_key) -> dict:
    p = snap.products[pid]
    own = bool(n.guid) and pid in snap.by_external.get(n.guid, set())
    claimed = p["external_id"] is not None and not own
    row_unit_known = n.unit_code is not None and n.unit_code in snap.units
    if not row_unit_known or p["unit_code"] is None:
        unit = "unverifiable"
    else:
        unit = "same" if n.unit_code == p["unit_code"] else "differs"
    plu_k = plu_key(p["plu_code"])
    lot = _lot(p)
    problem = snap.identity_problem.get(pid)
    return {
        "product_id": pid, "evidence": sorted(evidence), "name": p["name"], "article_code": p["article_code"],
        "sku": p["sku"], "source_system": p["source_system"], "external_id": p["external_id"],
        "deleted": p["deleted"], "is_active": p["is_active"], "claimed": claimed, "identity_problem": problem,
        "unit_code": p["unit_code"], "unit": unit,
        "name_differs": bool(n.name) and norm_key(n.name) != norm_key(p["name"]),
        "is_weighted": p["is_weighted"], "plu_code": p["plu_code"],
        "plu_conflicts": sorted(snap.by_plu.get(plu_k, set()) - {pid}) if plu_k is not None else [],
        "lot_tracked": lot, "sell_price": p["sell_price"], "buy_price": p["buy_price"],
        "barcodes": sorted(snap.barcodes_of.get(pid, ())),
        "inventory": {b: _d(q) for b, q in sorted(snap.inventory_of.get(pid, {}).items()) if q != 0},
        "linkable": not claimed and not lot and not p["deleted"] and problem is None,
    }


def classify(bundle: Bundle, snap: CatalogSnapshot, unit_names: dict[str, str] | None = None) -> dict:
    """Barcha Decimal yig'indilar 60 xonali kontekstda: 20+12 xonali qiymatlar jami yuvarlanmaydi."""
    with localcontext() as ctx:
        ctx.prec = 60
        return _classify(bundle, snap, unit_names)


def _classify(bundle: Bundle, snap: CatalogSnapshot, unit_names: dict[str, str] | None) -> dict:
    from app.services.catalog_match import norm_key

    data = bundle.data
    sel = data["selection"]
    table = build_unit_table(unit_names)                        # to'qnashuvli jadval -> ValueError
    unit_extra = {norm_unit_key(k): v for k, v in (unit_names or {}).items()}
    rows = [normalize_product(i, p, sel, table) for i, p in enumerate(data["products"])]
    excl = {n.idx: exclusion_reason(n) for n in rows}
    active = [n for n in rows if excl[n.idx] is None]

    # 0) birlik BinOS jadvalida BORMI (operator xaritasi mavjud bo'lmagan kodni ko'rsatishi mumkin)
    for n in active:
        if n.unit_code is None or n.unit_code not in snap.units:
            n.decide.add("UNKNOWN_UNIT")

    # 1) FAYL ICHIDAGI TAKRORLAR — HAR nusxa belgilanadi (tartibga bog'liq emas)
    gcount = Counter(n.guid for n in rows if n.guid)
    for n in rows:
        if n.guid and gcount[n.guid] > 1:
            n.block.add("DUPLICATE_GUID")
    bc_index: dict[str, set[int]] = {}
    ident_uses: dict[str, set[int]] = {}
    code_uses: dict[str, set[int]] = {}
    plu_index: dict[str, set[int]] = {}
    name_index: dict[str, set[int]] = {}
    for n in active:
        for b in n.barcodes:
            if b.valid:
                bc_index.setdefault(gtin_key(b.value), set()).add(n.idx)
        for v in {n.article, n.code} - {None}:
            ident_uses.setdefault(v, set()).add(n.idx)
        if n.code:
            code_uses.setdefault(n.code, set()).add(n.idx)
        if n.plu:
            plu_index.setdefault(n.plu, set()).add(n.idx)
        nk = norm_key(n.name) if n.name else ""
        if nk:
            name_index.setdefault(nk, set()).add(n.idx)
    bc_collisions = {k: v for k, v in bc_index.items() if len(v) > 1}
    for owners in bc_collisions.values():
        for i in owners:
            rows[i].block.add("BARCODE_COLLISION_IN_BUNDLE")

    def used_by_other(value, idx) -> bool:
        u = ident_uses.get(value) if value else None          # O(1): nusxa to'plam yaratilmaydi
        return u is not None and (len(u) > 1 or idx not in u)

    for n in active:
        if n.article and used_by_other(n.article, n.idx):
            n.decide.add("ARTICLE_COLLISION_IN_BUNDLE")
        if n.code and len(code_uses.get(n.code, ())) > 1:
            n.info.add("CODE_DUPLICATE_IN_BUNDLE")
        if n.plu and len(plu_index[n.plu]) > 1:
            n.decide.add("PLU_COLLISION")
        if n.name and len(name_index.get(norm_key(n.name), ())) > 1:
            n.info.add("NAME_DUPLICATE_IN_BUNDLE")

    # 2) DALILLAR: GUID identiteti va nomzodlar
    ev: dict[int, dict] = {}
    for n in rows:
        exact = sorted(snap.by_external.get(n.guid, ())) if n.guid else []
        cands: dict[str, set[str]] = {}
        amb: list[str] = []

        def add(pids, kind, key):
            for pid in pids:
                cands.setdefault(pid, set()).add(kind)
            if len(pids) > 1:
                amb.append(f"{kind}:{key}")

        if n.article:
            add(snap.by_article.get(n.article, set()), "article", n.article)
        bc_owner_map: dict[str, list[str]] = {}
        for b in n.barcodes:
            if b.valid:
                owners = barcode_owners(snap, b.value)
                bc_owner_map[b.value] = sorted(owners)
                add(owners, "barcode", b.value)
        if n.name and norm_key(n.name):
            add(snap.by_name.get(norm_key(n.name), set()), "name", n.name)
        plu_owners = sorted(snap.by_plu.get(n.plu, set())) if n.plu else []
        if n.plu:
            add(set(plu_owners), "plu", n.plu)
        for pid in exact:
            cands.setdefault(pid, set()).add("guid")
        other_src = sorted(snap.guid_other_source.get(n.guid, ())) if n.guid else []
        for pid in other_src:                             # ayni GUID boshqa manba nomi bilan — egasi KO'RINSIN
            cands.setdefault(pid, set()).add("guid_other_source")
        ev[n.idx] = {"exact": exact, "cands": cands, "amb": sorted(set(amb)), "bc_owners": bc_owner_map,
                     "plu_owners": plu_owners, "primary": None, "target": None, "other_src": other_src,
                     "evidence_target": None}

    # 3) ASOSIY TOIFA
    for n in rows:
        e = ev[n.idx]
        if excl[n.idx]:
            e["primary"] = "EXCLUDED"
            continue
        exact, cands = e["exact"], e["cands"]
        if n.guid and n.guid in snap.guid_other_source:
            n.block.add("GUID_OWNED_BY_OTHER_SOURCE")          # boshqa manba nomi bilan saqlangan ayni GUID
        if len(exact) > 1:
            n.block.add("IDENTITY_DUPLICATE_IN_BINOS")
            e["primary"] = "BLOCKED"
            continue
        if exact:
            pid = exact[0]
            if pid in snap.identity_problem:
                n.block.add(snap.identity_problem[pid])
            e["primary"] = "DELETED_MATCH" if snap.products[pid]["deleted"] else "EXACT_MATCH"
            e["target"] = pid
            e["via_guid"] = True
            continue
        claimed = {pid for pid in cands if snap.products[pid]["external_id"] is not None}
        if not cands:
            e["primary"] = "NEW"
        elif claimed:
            n.decide.add("IDENTITY_CONFLICT")        # BOSHQA identitetli mahsulotga LINK imkonsiz
            e["primary"] = "AMBIGUOUS"
        elif len(cands) == 1 and not e["amb"]:
            pid = next(iter(cands))
            e["primary"] = "DELETED_MATCH" if snap.products[pid]["deleted"] else "CANDIDATE"
            e["target"] = pid
        else:
            e["primary"] = "AMBIGUOUS"

    # 4) BIR NECHTA qator BITTA mahsulotga (GUID'siz dalil bilan) — hammasi AMBIGUOUS, qaror kerak
    by_target: dict[str, list[int]] = {}
    for n in rows:
        e = ev[n.idx]
        if e["primary"] in TARGETED and not e.get("via_guid"):
            by_target.setdefault(e["target"], []).append(n.idx)
    for pid, idxs in by_target.items():
        if len(idxs) > 1:
            for i in idxs:
                rows[i].decide.add("MANY_TO_ONE")
                # nishon qaror uchun tozalanadi, lekin qator o'tkazib yuborilsa mahsulot SHU qatorniki bo'lib qoladi
                ev[i]["evidence_target"] = ev[i]["target"]
                ev[i]["primary"], ev[i]["target"] = "AMBIGUOUS", None

    # 5) Maqsad bilan solishtirish kodlari
    for n in rows:
        e = ev[n.idx]
        if e["primary"] not in TARGETED:
            continue
        t = e["target"]
        p = snap.products[t]
        if _lot(p):
            n.block.add("TARGET_LOT_TRACKED")
        if n.name and norm_key(n.name) != norm_key(p["name"]):
            n.info.add("NAME_DIFFERS")
        if "UNKNOWN_UNIT" not in n.decide and n.unit_code != p["unit_code"]:
            n.decide.add("UNIT_DIFFERS")
        if n.retail_price is not None and Decimal(p["sell_price"]) != n.retail_price:
            n.info.add("PRICE_CHANGES")
        if n.purchase_price is not None and Decimal(p["buy_price"]) != n.purchase_price:
            n.info.add("PURCHASE_PRICE_CHANGES")
        if snap.barcodes_of.get(t, set()) - {b.value for b in n.barcodes}:
            n.info.add("EXTRA_BINOS_BARCODES")
        if any(set(o) - {t} for o in e["bc_owners"].values()):
            n.decide.add("BARCODE_OWNED_BY_OTHER_PRODUCT")
        if p["deleted"]:
            k = plu_key(p["plu_code"])
            if k is not None and snap.by_plu.get(k, set()) - {t}:
                n.decide.add("REACTIVATE_PLU_CONFLICT")
        if p["external_id"] is not None and not e.get("via_guid"):
            n.block.add("IDENTITY_CONFLICT")             # bo'lishi mumkin emas (3-qadam), himoya
    for n in rows:
        e = ev[n.idx]
        if e["primary"] != "EXCLUDED" and n.block:
            e["primary"] = "BLOCKED"

    # 6) BinOS tomoni: har tirik mahsulot — maqsadmi, faqat nomzodmi, umuman tilga olinmaganmi
    referenced: dict[str, list[int]] = {}
    targeted: dict[str, int] = {}
    for n in rows:
        e = ev[n.idx]
        for pid in e["cands"]:
            referenced.setdefault(pid, []).append(n.idx)
        if e["primary"] in TARGETED:
            targeted[e["target"]] = n.idx
    live = []
    for pid, p in sorted(snap.products.items()):
        if p["deleted"]:
            continue
        live.append({
            "product_id": pid, "name": p["name"], "article_code": p["article_code"],
            "source_system": p["source_system"], "external_id": p["external_id"], "is_active": p["is_active"],
            "lot_tracked": _lot(p),
            "inventory": {b: _d(q) for b, q in sorted(snap.inventory_of.get(pid, {}).items()) if q != 0},
            "referenced_by_rows": sorted(set(referenced.get(pid, []))),
            "target_of_row": targeted.get(pid),
            "status": ("targeted" if pid in targeted else "unresolved_candidate" if pid in referenced
                       else "not_in_source"),
        })

    # 7) Eskirgan snapshot: allaqachon qo'llangan eksport bu eksportdan YANGI yoki TENG
    snap_at = parse_ts(data["snapshot_at"], "snapshot_at")
    newer = []
    for j in snap.committed_1c_jobs:
        if j.get("snapshot_at"):
            try:
                if parse_ts(j["snapshot_at"], "job.snapshot_at") >= snap_at:
                    newer.append({"job_id": j["id"], "snapshot_at": j["snapshot_at"], "status": j["status"]})
            except Exception:                        # noqa: BLE001 — buzuq yozuv ham "eskirgan" deb hisoblanadi
                newer.append({"job_id": j["id"], "snapshot_at": j["snapshot_at"], "status": j["status"]})

    # 8) Hisobot qatorlari
    all_articles = snap.article_codes
    report_rows = []
    for n in sorted(rows, key=_row_sort_key):
        e = ev[n.idx]
        is_excl = e["primary"] == "EXCLUDED"
        cands = e["cands"]
        report_rows.append({
            "row": n.idx, "guid": n.guid, "guid_raw": n.guid_raw if not n.guid else None,
            "code": n.code, "article": n.article, "name": n.name, "kind": n.kind,
            "classification": e["primary"], "excluded_reason": excl[n.idx],
            "block": sorted(n.block), "decide": sorted(n.decide), "info": sorted(n.info),
            "exact_product_id": e["exact"][0] if len(e["exact"]) == 1 else None,
            "target_product_id": e["target"] if e["primary"] in TARGETED else None,
            # qator o'tkazib yuborilsa qaysi BinOS mahsuloti "o'tkazib yuborilgan qator mahsuloti" hisoblanadi
            "row_targets": sorted(set(e["exact"]) | set(e["other_src"])
                                  | {x for x in (e["target"], e["evidence_target"]) if x}),
            "candidates": ([{"product_id": pid, "evidence": sorted(v)} for pid, v in sorted(cands.items())]
                           if is_excl else
                           [_facts(snap, pid, n, v, norm_key) for pid, v in sorted(cands.items())]),
            "ambiguous_keys": e["amb"],
            "unit": {"source": n.unit_source, "okei": n.unit_okei, "binos": n.unit_code,
                     "known": n.unit_code is not None and n.unit_code in snap.units},
            "is_weighted": n.is_weighted, "plu": n.plu, "plu_source": n.plu_source, "plu_owners": e["plu_owners"],
            "retail_price": _d(n.retail_price), "retail_status": n.retail_status,
            "purchase_price": _d(n.purchase_price), "purchase_status": n.purchase_status,
            "stock_total": _d(n.stock_total),
            "stock_by_warehouse": {k: _d(v) for k, v in sorted(n.stock_by_warehouse.items())},
            "stock_unselected": {k: _d(v) for k, v in sorted(n.stock_unselected.items())},
            "barcodes": [{"value": b.value, "type": b.type, "valid": b.valid,
                          "owners": e["bc_owners"].get(b.value, [])} for b in n.barcodes],
            "barcodes_dup_dropped": n.barcodes_dup_dropped,
            "article_taken_in_binos": n.article is not None and n.article in all_articles,
            "code_taken_in_binos": n.code is not None and n.code in all_articles,
            "article_used_by_other_rows": used_by_other(n.article, n.idx) if not is_excl else False,
            "code_used_by_other_rows": used_by_other(n.code, n.idx) if not is_excl else False,
            "fallback_article": f"1C-{n.guid}" if n.guid else None,
            "fallback_article_taken": bool(n.guid) and f"1C-{n.guid}" in all_articles,
        })

    prim = Counter(r["classification"] for r in report_rows)
    act_rows = [r for r in report_rows if r["classification"] != "EXCLUDED"]
    codes = Counter(c for r in act_rows for grp in ("block", "decide", "info") for c in r[grp])
    codes_excluded = Counter(c for r in report_rows if r["classification"] == "EXCLUDED"
                             for grp in ("block", "decide", "info") for c in r[grp])
    bucket_of = {n.idx: ("excluded" if ev[n.idx]["primary"] == "EXCLUDED"
                         else "blocked" if ev[n.idx]["primary"] == "BLOCKED" else "migratable") for n in rows}
    recon = reconcile(data, rows, bucket_of)

    wh_with_stock = sorted({st["warehouse_guid"] for p in data["products"] for st in p["stock"]
                            if _raw_num(st["qty"]) not in (None, ZERO)})
    pt_with_values = sorted({pr["price_type_guid"] for p in data["products"] for pr in p["prices"]
                             if pr.get("value") is not None})
    gdup = {g for g, c in gcount.items() if c > 1}
    live_status = Counter(x["status"] for x in live)
    summary = {
        "total_1c_products": len(rows),
        "valid_unique_guid_rows": sum(1 for n in rows if n.guid and n.guid not in gdup),
        "duplicate_guid_rows": sum(1 for n in rows if n.guid in gdup),
        "duplicate_guid_distinct": len(gdup),
        "missing_guid_rows": sum(1 for n in rows if "MISSING_GUID" in n.block),
        "invalid_guid_rows": sum(1 for n in rows if "INVALID_GUID" in n.block),
        **{k.lower(): prim.get(k, 0) for k in PRIMARY},
        "excluded_by_reason": dict(sorted(Counter(excl[n.idx] for n in rows if excl[n.idx]).items())),
        "migratable_rows": sum(1 for r in report_rows if r["classification"] in ("EXACT_MATCH", "CANDIDATE",
                                                                                   "DELETED_MATCH", "AMBIGUOUS", "NEW")),
        "barcode_collisions_in_bundle": len(bc_collisions),
        "barcode_collision_rows": codes.get("BARCODE_COLLISION_IN_BUNDLE", 0),
        "barcode_owned_by_other_rows": codes.get("BARCODE_OWNED_BY_OTHER_PRODUCT", 0),
        "article_collision_rows": codes.get("ARTICLE_COLLISION_IN_BUNDLE", 0),
        "identity_conflict_rows": codes.get("IDENTITY_CONFLICT", 0),
        "identity_format_mismatch_rows": codes.get("IDENTITY_FORMAT_MISMATCH", 0)
        + codes.get("IDENTITY_DUPLICATE_IN_BINOS", 0),
        "many_to_one_rows": codes.get("MANY_TO_ONE", 0),
        "retail_price_absent": sum(1 for n in active if n.retail_status == "absent"),
        "retail_price_invalid": sum(1 for n in active if n.retail_status == "invalid"),
        "retail_price_zero": sum(1 for n in active if n.retail_status == "zero"),
        "retail_price_negative": sum(1 for n in active if n.retail_status == "negative"),
        **{f"purchase_price_{k}": sum(1 for n in active if n.purchase_status == k) for k in PURCHASE_STATUSES},
        "purchase_price_changes_rows": codes.get("PURCHASE_PRICE_CHANGES", 0),
        "invalid_qty_unselected_rows": codes.get("INVALID_QTY_UNSELECTED_WAREHOUSE", 0),
        "guid_owned_by_other_source_rows": codes.get("GUID_OWNED_BY_OTHER_SOURCE", 0),
        "missing_stock_rows": codes.get("MISSING_STOCK", 0),
        "stock_only_in_unselected_warehouse_rows": codes.get("STOCK_ONLY_IN_UNSELECTED_WAREHOUSE", 0),
        "stock_in_unselected_warehouse_rows": codes.get("STOCK_IN_UNSELECTED_WAREHOUSE", 0)
        + codes.get("STOCK_ONLY_IN_UNSELECTED_WAREHOUSE", 0),
        "unselected_warehouse_stock_qty": _d(sum((sum(n.stock_unselected.values(), ZERO) for n in active), ZERO)),
        "zero_stock_rows": codes.get("ZERO_STOCK", 0),
        "negative_stock_rows": sum(n.negative_stock_rows for n in active),
        "negative_stock_products": sum(1 for n in active if n.negative_stock_rows),
        "unknown_unit_rows": codes.get("UNKNOWN_UNIT", 0),
        "unknown_unit_names": sorted({(n.unit_source or f"okei:{n.unit_okei}") + (f"->{n.unit_code}" if n.unit_code else "")
                                      for n in active if "UNKNOWN_UNIT" in n.decide}),
        "unit_differs_rows": codes.get("UNIT_DIFFERS", 0),
        "invalid_barcode_rows": codes.get("INVALID_BARCODE", 0),
        "precision_loss_rows": sum(1 for n in active if {"PRECISION_LOSS_QTY", "PRECISION_LOSS_PRICE"} & n.block),
        "out_of_range_rows": sum(1 for n in active if {"QTY_OUT_OF_RANGE", "PRICE_OUT_OF_RANGE"} & n.block),
        "plu_collision_rows": sum(1 for r in act_rows if {"PLU_COLLISION", "REACTIVATE_PLU_CONFLICT"} & set(r["decide"])),
        "invalid_plu_rows": codes.get("INVALID_PLU", 0),
        "characteristics_rows": codes.get("CHARACTERISTICS_UNSUPPORTED", 0),
        "lot_data_rows": codes.get("LOT_DATA_PRESENT", 0),
        "warehouses_with_stock": wh_with_stock,
        "multiple_warehouses": len(wh_with_stock) > 1,
        "price_types_with_values": pt_with_values,
        "multiple_price_types": len(pt_with_values) > 1,
        "binos_live_products": len(live),
        "binos_targeted": live_status.get("targeted", 0),
        "binos_unresolved_candidates": live_status.get("unresolved_candidate", 0),
        "binos_not_in_source": live_status.get("not_in_source", 0),
        "stale_snapshot": bool(newer),
    }
    snapshot_id = snapshot_id_for(bundle)
    already = [j for j in snap.committed_1c_jobs
               if j["snapshot_id"] == snapshot_id or j["content_sha256"] == bundle.content_sha256]
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "bundle": {
            "schema_version": SCHEMA_VERSION, "file_sha256": bundle.file_sha256,
            "content_sha256": bundle.content_sha256, "size_bytes": bundle.size_bytes,
            "export_id": data["export_id"], "exported_at": data["exported_at"], "snapshot_at": data["snapshot_at"],
            "infobase": data["infobase"], "extractor": data["extractor"],
            "warehouses": sorted(data["warehouses"], key=lambda w: w["guid"]),
            "price_types": sorted(data["price_types"], key=lambda p: p["guid"]),
            "selection": {**sel, "warehouse_guids": sorted(sel["warehouse_guids"])},
        },
        "unit_names_extra": dict(sorted(unit_extra.items())),
        "binos": {
            "company_id": snap.company_id, "company_code": snap.company_code,
            "catalog_fingerprint": snap.fingerprint,
            "catalog_mode": snap.catalog_setting.get("mode", "PRE_LIVE"),
            "cutover_at": snap.catalog_setting.get("cutover_at"),
            "units": sorted(snap.units),
            "products": len(snap.products),
            "products_live": len(live),
            "products_active": sum(1 for x in live if x["is_active"]),
            "products_with_1c_guid": sum(len(v) for v in snap.by_external.values()),
            "identity_problems": dict(sorted(snap.identity_problem.items())),
            "barcodes": len(snap.barcodes),
            "inventory_rows": len(snap.inventory),
            "inventory_qty_total": _d(sum(snap.inventory.values(), ZERO)),
            "branches": sorted(snap.branches.values(), key=lambda b: b["id"]),
            "tracked_products": sum(1 for p in snap.products.values() if _lot(p)),
            "movement_ref_types": dict(sorted(snap.movement_ref_types.items())),
            "committed_1c_jobs": snap.committed_1c_jobs,
            "already_applied_jobs": already,
            "newer_or_equal_snapshot_jobs": newer,
        },
        "summary": summary,
        "codes": dict(sorted(codes.items())),
        "codes_excluded_rows": dict(sorted(codes_excluded.items())),
        "reconciliation": recon,
        "binos_live_products": live,
        "rows": report_rows,
    }
    report["report_sha256"] = report_hash(report)
    return report


def snapshot_id_for(bundle: Bundle) -> str:
    return f"1c-bundle:{bundle.file_sha256}"


# Muhitga bog'liq maydonlar (vaqt, davomiylik, read-only isboti, ulanish identiteti) XESHGA KIRMAYDI:
# apply hisobotni QAYTA hisoblaydi va ular mazmun bo'lmagani uchun soxta drift bermasligi kerak.
# Ulanish identiteti ALOHIDA tekshiriladi: apply ulangan baza hisobotdagi `database` bilan AYNAN teng
# bo'lishini talab qiladi (guard.assert_apply_allowed).
NON_CONTENT_KEYS = ("report_sha256", "generated_at", "duration_ms", "read_only_proof", "database")


def report_hash(report: dict) -> str:
    body = {k: v for k, v in report.items() if k not in NON_CONTENT_KEYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def report_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, ensure_ascii=False, indent=1, default=str)


def summary_text(report: dict) -> str:
    s = report["summary"]
    rc = report["reconciliation"]
    raw, pv = rc["source_1c_raw"], rc["binos_preview"]
    b = report["binos"]
    bad_ids = [k for k, v in rc["identities"].items() if not v["ok"]]
    stale_txt = ("HA — " + str(b["newer_or_equal_snapshot_jobs"])) if s["stale_snapshot"] else "yo'q"
    lines = [
        f"1C eksport: {report['bundle']['export_id']} · sha256 {report['bundle']['file_sha256'][:16]}… · "
        f"{report['bundle']['infobase']['configuration_name']} {report['bundle']['infobase']['configuration_version']} · "
        f"snapshot {report['bundle']['snapshot_at']}",
        f"BinOS: {b['company_code']} · katalog {b['catalog_mode']} · tirik mahsulot {b['products_live']} "
        f"(faol {b['products_active']}) · barkod {b['barcodes']} · 1C GUID'li {b['products_with_1c_guid']} · "
        f"kuzatuvli {b['tracked_products']}",
        "",
        f"1C qatorlari: {s['total_1c_products']} = GUID noyob {s['valid_unique_guid_rows']} + takror qator "
        f"{s['duplicate_guid_rows']} ({s['duplicate_guid_distinct']} GUID) + yo'q {s['missing_guid_rows']} + "
        f"buzuq {s['invalid_guid_rows']}",
        f"Exact: {s['exact_match']} · Candidate: {s['candidate']} · New: {s['new']} · Ambiguous: {s['ambiguous']} · "
        f"Deleted match: {s['deleted_match']} · Blocked: {s['blocked']} · Excluded: {s['excluded']} {s['excluded_by_reason']}",
        f"Barkod to'qnashuvi (fayl ichida): {s['barcode_collisions_in_bundle']} ({s['barcode_collision_rows']} qator) · "
        f"boshqa mahsulotniki: {s['barcode_owned_by_other_rows']} · artikul to'qnashuvi: {s['article_collision_rows']} · "
        f"identitet ziddiyati: {s['identity_conflict_rows']} · identitet formati: {s['identity_format_mismatch_rows']} · "
        f"many-to-one: {s['many_to_one_rows']}",
        f"Chakana narx — yo'q: {s['retail_price_absent']} · buzuq: {s['retail_price_invalid']} · 0: {s['retail_price_zero']} · "
        f"manfiy: {s['retail_price_negative']} · Kelish narxi — yo'q: {s['purchase_price_absent']} · "
        f"buzuq: {s['purchase_price_invalid']} · 0 (yozilmaydi): {s['purchase_price_zero']} · "
        f"manfiy: {s['purchase_price_negative']} · o'zgaradi: {s['purchase_price_changes_rows']}",
        f"Qoldiq — qatori yo'q: {s['missing_stock_rows']} · faqat tanlanmagan omborda: {s['stock_only_in_unselected_warehouse_rows']} · "
        f"0: {s['zero_stock_rows']} · manfiy (mahsulot×ombor): {s['negative_stock_rows']} / mahsulot {s['negative_stock_products']} · "
        f"tanlanmagan omborlardagi jami: {s['unselected_warehouse_stock_qty']} "
        f"(buzuq qator {s['invalid_qty_unselected_rows']})",
        f"Noma'lum birlik: {s['unknown_unit_rows']} {s['unknown_unit_names']} · birlik farqi: {s['unit_differs_rows']} · "
        f"buzuq barkod: {s['invalid_barcode_rows']} · aniqlik yo'qolishi: {s['precision_loss_rows']} · "
        f"chegaradan tashqari: {s['out_of_range_rows']} · PLU: {s['plu_collision_rows']} (buzuq {s['invalid_plu_rows']}) · "
        f"xarakteristika: {s['characteristics_rows']} · seriya/lot: {s['lot_data_rows']}",
        f"Qoldiqli omborlar: {len(s['warehouses_with_stock'])} · qiymatli narx turlari: {len(s['price_types_with_values'])}",
        f"BinOS tirik mahsulotlari: maqsad {s['binos_targeted']} · faqat nomzod {s['binos_unresolved_candidates']} · "
        f"1C'da umuman yo'q {s['binos_not_in_source']}",
        f"Eskirgan snapshot: {stale_txt} · allaqachon qo'llangan: {len(b['already_applied_jobs'])}",
        "",
        f"Rekonsiliatsiya: {'MOS' if rc['ok'] else 'MOS EMAS ' + str(bad_ids)} "
        f"(1C xom = BinOS preview + BLOCKED + EXCLUDED)",
        f"  1C xom:   SKU {raw['sku_count']} · GUID {raw['guid_valid_distinct']} · barkod {raw['barcode_entries']} · "
        f"narxli {raw['retail_price_positive'] + raw['retail_price_zero'] + raw['retail_price_negative']} · "
        f"qoldiq {raw['stock_total_qty']} {raw['stock_by_warehouse']} · narx {raw['retail_price_min']}..{raw['retail_price_max']}",
        f"  preview:  SKU {pv['sku_count']} · GUID {pv['guid_valid_distinct']} · barkod {pv['barcodes_valid_distinct']} · "
        f"narxli {pv['retail_price_positive'] + pv['retail_price_zero']} · qoldiq {pv['stock_total_qty']} "
        f"{pv['stock_by_warehouse']} · 0 qoldiq {pv['zero_stock_products']} · manfiy {pv['negative_stock_products']} · "
        f"narx {pv['retail_price_min']}..{pv['retail_price_max']} · narxsiz {pv['retail_price_absent']}",
        f"report_sha256: {report['report_sha256']}",
    ]
    return "\n".join(lines)


__all__ = ["classify", "report_hash", "report_json", "summary_text", "snapshot_id_for", "raw_totals",
           "bucket_totals", "reconcile", "exclusion_reason", "NON_CONTENT_KEYS"]
