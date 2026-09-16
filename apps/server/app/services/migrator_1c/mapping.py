# -*- coding: utf-8 -*-
"""Operator qarorlari (`binos-1c-mapping-v1`) -> DETERMINISTIK apply rejasi. Bazaga tegmaydi.

Mapping fayli AYNAN bitta quruq yurish hisobotiga bog'lanadi (`report_sha256`) va u hisobot
AYNAN bitta bundle'ga (`bundle_file_sha256`) va AYNAN bitta katalog holatiga (barmoq izi)
bog'langan. Shu bois operator ko'rgan narsa bilan qo'llanadigan narsa farq qila olmaydi.

QOIDALAR:
  · EXACT_MATCH — yagona avtomatik LINK (GUID bir xil).
  · CANDIDATE / AMBIGUOUS / DELETED_MATCH — ANIQ qaror SHART; LINK faqat hisobotda
    `linkable` deb ko'rsatilgan nomzodga (ixtiyoriy mahsulotga birlashtirish YO'Q).
  · Har darvoza TANLANGAN maqsad bo'yicha qo'llanadi (birlik, nom, barkod egasi, PLU, partiya) —
    qator toifasidan qat'i nazar. Siyosat ANIQ yozilishi SHART — "standart" qiymat yo'q.
  · Bitta BinOS mahsuloti faqat BITTA 1C qatoriga bog'lanadi.
  · Reja YOZILADIGAN narsani to'liq o'z ichiga oladi: qo'shiladigan/tashlanadigan barkodlar,
    yangi mahsulot artikuli, PLU, har filial uchun eski va yangi qoldiq, o'chiriladigan mahsulotlar.
    Apply rejadan boshqa narsani hisoblamaydi; post-tekshiruv shu rejani bazadan isbotlaydi.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, localcontext

from . import MAPPING_SCHEMA_VERSION

ACTIONS = ("LINK", "CREATE", "SKIP", "REACTIVATE")
POLICY_CHOICES = {
    "new_products": ("create", "skip"),
    "blocked_rows": ("skip",),
    "negative_stock": ("block", "zero"),
    "missing_price": ("block", "skip_row", "keep_binos_price"),
    "unknown_unit": ("block", "skip_row"),
    # Birlik farq qilsa 1C narxi/qoldig'i BOSHQA birlikdagi mahsulotga yozilmaydi: avval BinOS birligi
    # tuzatiladi va quruq yurish qaytadan qilinadi. Konvertatsiya V1 da YO'Q.
    "unit_differs": ("block", "skip_row"),
    "invalid_barcode": ("skip_barcode",),
    "barcode_owned_by_other": ("skip_barcode", "block"),
    "article_collision": ("generate_article",),
    "plu_collision": ("drop_plu", "block"),
    "names": ("keep_binos", "use_1c"),
    "unmapped_branch_stock": ("keep", "close"),
    "binos_missing_from_source": ("keep", "deactivate_and_zero"),
    "skipped_row_products": ("keep", "deactivate_and_zero"),
}
MAPPING_KEYS = {"schema_version", "company_code", "bundle_file_sha256", "report_sha256", "mode", "approved_by",
                "approved_at", "warehouse_branch", "policies", "decisions"}
DECISION_KEYS = {"action", "product_id", "note"}
ZERO = Decimal("0")


class MappingError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} ta muammo: " + "; ".join(problems[:20]))
        self.problems = problems


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def mapping_sha256(mapping: dict) -> str:
    return _sha(mapping)


def deterministic_product_id(job_id, guid: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID(str(job_id)), f"product:{guid}")


def _f(v: Decimal) -> str:
    return format(v, "f")


# ── Shablon — operator to'ldiradi ───────────────────────────────────────────
def build_template(report: dict) -> dict:
    """Qaror talab qiladigan har qator uchun bo'sh qaror + nomzodlar ro'yxati.

    ⚠️  Shablon hech narsani TASDIQLAMAYDI: `action` bo'sh qoldiriladi va reja bo'sh qarorni
        RAD etadi. `_` bilan boshlanadigan kalitlar faqat operatorga yordam (reja ularni o'qimaydi).
    """
    decisions = {}
    for r in report["rows"]:
        cls = r["classification"]
        if cls not in ("CANDIDATE", "AMBIGUOUS", "DELETED_MATCH") or not r["guid"]:
            continue
        if cls == "DELETED_MATCH":
            allowed = ["REACTIVATE", "SKIP"] + ([] if r["exact_product_id"] else ["CREATE"])
        else:
            allowed = (["LINK"] if any(c["linkable"] for c in r["candidates"]) else []) + ["CREATE", "SKIP"]
        decisions[r["guid"]] = {
            "action": "", "_classification": cls, "_name": r["name"], "_code": r["code"], "_allowed": allowed,
            "_decide": r["decide"],
            "_candidates": [{"product_id": c["product_id"], "name": c["name"], "evidence": c["evidence"],
                             "linkable": c["linkable"], "unit": c["unit"], "claimed": c["claimed"],
                             "deleted": c["deleted"]} for c in r["candidates"]],
        }
    act = [r for r in report["rows"] if r["classification"] not in ("EXCLUDED", "BLOCKED")]
    codes = set(report["codes"])
    s = report["summary"]
    need = set()
    if s["new"]:
        need.add("new_products")
    if s["blocked"]:
        need |= {"blocked_rows", "skipped_row_products"}
    for code, key in (("NEGATIVE_STOCK", "negative_stock"), ("UNKNOWN_UNIT", "unknown_unit"),
                      ("INVALID_BARCODE", "invalid_barcode"), ("ARTICLE_COLLISION_IN_BUNDLE", "article_collision"),
                      ("PLU_COLLISION", "plu_collision"), ("INVALID_PLU", "plu_collision"),
                      ("REACTIVATE_PLU_CONFLICT", "plu_collision")):
        if code in codes:
            need.add(key)
    for r in act:
        if r["retail_status"] in ("absent", "zero"):
            need.add("missing_price")
        if any(b["owners"] for b in r["barcodes"]):
            need.add("barcode_owned_by_other")
        if r["plu_owners"]:
            need.add("plu_collision")
        for c in r["candidates"]:
            if c["unit"] != "same":
                need.add("unit_differs")
            if c["name_differs"]:
                need.add("names")
            if c["inventory"]:
                need.add("unmapped_branch_stock")
    if s["binos_live_products"]:
        need.add("binos_missing_from_source")
    if any(p["inventory"] for p in report["binos_live_products"]):
        need.add("unmapped_branch_stock")
    # har qanday qator (EXACT/LINK ham) keyinchalik SKIP yoki siyosat bilan o'tkazilishi mumkin
    if s["binos_live_products"] and any(r["row_targets"] or r["candidates"] for r in act):
        need.add("skipped_row_products")
    if any(c["plu_code"] for r in act if r["classification"] == "DELETED_MATCH" for c in r["candidates"]):
        need.add("plu_collision")
    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "company_code": report["binos"]["company_code"],
        "bundle_file_sha256": report["bundle"]["file_sha256"],
        "report_sha256": report["report_sha256"],
        "mode": "CUTOVER_REFRESH" if report["binos"]["products_live"] else "INITIAL_CREATE",
        "approved_by": "",
        "approved_at": "",
        "warehouse_branch": {w: "" for w in report["bundle"]["selection"]["warehouse_guids"]},
        "policies": {k: "" for k in sorted(need)},
        "_policy_choices": {k: list(v) for k, v in POLICY_CHOICES.items() if k in need},
        "decisions": decisions,
    }


# ── Tekshiruv va reja ───────────────────────────────────────────────────────
def build_plan(report: dict, mapping: dict) -> dict:
    """Hisobot + mapping -> reja. Birorta muammo bo'lsa HECH QANDAY reja qaytmaydi (MappingError)."""
    with localcontext() as ctx:
        ctx.prec = 60
        return _build_plan(report, mapping)


def _build_plan(report: dict, mapping: dict) -> dict:
    from .classify import report_hash

    P: list[str] = []
    if not isinstance(mapping, dict):
        raise MappingError(["mapping JSON obyekt emas"])
    for k in mapping:
        if k not in MAPPING_KEYS and not k.startswith("_"):
            P.append(f"mapping'da noma'lum kalit: {k}")
    if mapping.get("schema_version") != MAPPING_SCHEMA_VERSION:
        P.append(f"mapping schema_version '{mapping.get('schema_version')}'")
    if report_hash(report) != report.get("report_sha256"):
        P.append("hisobot xeshi o'z mazmuniga mos emas (hisobot tahrirlangan)")
    if mapping.get("report_sha256") != report.get("report_sha256"):
        P.append("mapping BOSHQA quruq yurish hisobotiga tegishli (report_sha256 mos emas)")
    if mapping.get("bundle_file_sha256") != report["bundle"]["file_sha256"]:
        P.append("mapping BOSHQA eksport fayliga tegishli (bundle_file_sha256 mos emas)")
    if mapping.get("company_code") != report["binos"]["company_code"]:
        P.append("mapping BOSHQA do'konga tegishli")
    for k in ("approved_by", "approved_at"):
        if not isinstance(mapping.get(k), str) or not mapping[k].strip():
            P.append(f"mapping.{k} bo'sh yoki matn emas — tasdiq egasi va vaqti majburiy")
    if not report["reconciliation"]["ok"]:
        P.append("rekonsiliatsiya MOS EMAS — apply mumkin emas")
    if report["binos"]["already_applied_jobs"]:
        P.append("bu eksport (fayl yoki mazmun) ALLAQACHON qo'llangan")
    if report["binos"]["newer_or_equal_snapshot_jobs"]:
        P.append("eskirgan snapshot: bu eksportdan yangi (yoki teng) 1C snapshot'i allaqachon qo'llangan "
                 f"{report['binos']['newer_or_equal_snapshot_jobs']}")
    if report["binos"]["catalog_mode"] == "LIVE" or report["binos"]["cutover_at"]:
        P.append("katalog LIVE (NORMAL_OPERATION) — 1C snapshot'i endi qo'llanmaydi")
    if report["binos"]["tracked_products"]:
        P.append("partiya kuzatuvi yoqilgan mahsulotlar bor — Migrator V1 ularga tegmaydi")

    mode = mapping.get("mode")
    if mode not in ("CUTOVER_REFRESH", "INITIAL_CREATE"):
        P.append(f"mode '{mode}' — CUTOVER_REFRESH yoki INITIAL_CREATE")
    if mode == "INITIAL_CREATE" and report["binos"]["products_live"]:
        P.append("INITIAL_CREATE faqat bo'sh katalogga (tirik mahsulot bor)")

    pol = mapping.get("policies")
    if not isinstance(pol, dict):
        P.append("policies obyekt bo'lishi kerak")
        pol = {}
    for k, v in pol.items():
        if k not in POLICY_CHOICES:
            P.append(f"noma'lum siyosat: {k}")
        elif v not in POLICY_CHOICES[k]:
            P.append(f"siyosat {k}='{v}' — ruxsat: {POLICY_CHOICES[k]}")

    def need(key: str, why: str):
        v = pol.get(key)
        if v not in POLICY_CHOICES[key]:
            P.append(f"siyosat '{key}' ANIQ berilishi shart ({why})")
            return None
        return v

    branches = {b["id"]: b for b in report["binos"]["branches"]}
    wb = mapping.get("warehouse_branch")
    if not isinstance(wb, dict):
        P.append("warehouse_branch obyekt bo'lishi kerak")
        wb = {}
    sel = report["bundle"]["selection"]["warehouse_guids"]
    if sorted(wb) != sorted(sel):
        P.append(f"warehouse_branch AYNAN tanlangan omborlarni qamrashi shart: {sel}")
    for w, b in wb.items():
        if not isinstance(b, str) or b not in branches or branches[b]["deleted"]:
            P.append(f"ombor {w} -> filial '{b}' mavjud emas yoki o'chirilgan")
    if len(set(map(str, wb.values()))) != len(wb):
        P.append("ikki ombor bitta filialga — V1 da qo'llanmaydi (qoldiqni yig'ish taxmin bo'lardi)")
    mapped_branches = {b for b in wb.values() if isinstance(b, str)}

    decisions = mapping.get("decisions")
    if not isinstance(decisions, dict):
        P.append("decisions obyekt bo'lishi kerak")
        decisions = {}
    rows_by_guid = {r["guid"]: r for r in report["rows"] if r["guid"]}
    for g, d in decisions.items():
        if g not in rows_by_guid:
            P.append(f"qaror hisobotda yo'q GUID uchun: {g}")
        if not isinstance(d, dict):
            P.append(f"{g}: qaror obyekt bo'lishi kerak")
            continue
        for k in d:
            if k not in DECISION_KEYS and not k.startswith("_"):
                P.append(f"{g}: qarorda noma'lum kalit '{k}'")
        if "product_id" in d and d["product_id"] is not None and not isinstance(d["product_id"], str):
            P.append(f"{g}: product_id matn bo'lishi kerak")
        if "action" in d and not isinstance(d["action"], str):
            P.append(f"{g}: action matn bo'lishi kerak")

    ops: list[dict] = []
    skipped: list[dict] = []
    used_targets: dict[str, str] = {}
    skipped_targets: dict[str, str] = {}
    articles_assigned: set[str] = set()

    def skip(r, why, targets):
        """`targets` — o'tkazib yuborilgan qatorning AYNAN qaysi mahsulot(lar)i: operator tanlagan LINK/REACTIVATE
        maqsadi, yoki qaror berilmagan qator uchun hisobotdagi `row_targets`. CREATE qarori berilgan qatorda —
        bo'sh (operator nomzodni rad etgan; u `binos_missing_from_source` ga tushadi)."""
        skipped.append({"row": r["row"], "guid": r["guid"], "why": why})
        for t in targets:
            skipped_targets.setdefault(t, r["guid"] or f"row {r['row']}")

    for r in report["rows"]:
        g, cls = r["guid"], r["classification"]
        who = g or f"row {r['row']}"
        d = decisions.get(g) if g else None
        d = d if isinstance(d, dict) else {}
        act = d.get("action") if isinstance(d.get("action"), str) else ""
        dpid = d.get("product_id") if isinstance(d.get("product_id"), str) else None
        if act and act not in ACTIONS:
            P.append(f"{who}: noma'lum amal '{act}'")
            continue
        cand = {c["product_id"]: c for c in r["candidates"]} if cls != "EXCLUDED" else {}

        # ── 1) amal va maqsad ────────────────────────────────────────────
        target = None
        if cls == "EXCLUDED":
            if act and act != "SKIP":
                P.append(f"{who}: EXCLUDED qator faqat SKIP")
            skipped.append({"row": r["row"], "guid": g, "why": f"EXCLUDED:{r['excluded_reason']}"})
            continue
        if cls == "BLOCKED":
            if act and act != "SKIP":
                P.append(f"{who}: BLOCKED qator faqat SKIP ({r['block']})")
                continue
            if not act and need("blocked_rows", f"BLOCKED qatorlar bor, masalan {who} {r['block']}") is None:
                continue
            skip(r, "BLOCKED:" + ",".join(r["block"]), r["row_targets"])
            continue
        if cls == "EXACT_MATCH":
            if act in ("", "LINK"):
                if dpid not in (None, r["exact_product_id"]):
                    P.append(f"{who}: EXACT_MATCH boshqa mahsulotga LINK qilinmaydi")
                    continue
                act, target = "LINK", r["exact_product_id"]
            elif act != "SKIP":
                P.append(f"{who}: EXACT_MATCH uchun faqat LINK yoki SKIP")
                continue
        elif cls == "NEW":
            if not act:
                v = need("new_products", "NEW qatorlar bor")
                if v is None:
                    continue
                act = "CREATE" if v == "create" else "SKIP"
            elif act not in ("CREATE", "SKIP"):
                P.append(f"{who}: NEW qator faqat CREATE yoki SKIP")
                continue
        elif cls in ("CANDIDATE", "AMBIGUOUS"):
            if not act:
                P.append(f"{who}: {cls} — ANIQ qaror SHART (LINK/CREATE/SKIP)")
                continue
            if act == "LINK":
                pid = dpid
                allowed = {c["product_id"] for c in r["candidates"] if c["linkable"]}
                if cls == "CANDIDATE":
                    allowed &= {r["target_product_id"]}
                if pid not in allowed:
                    P.append(f"{who}: LINK faqat hisobotdagi bog'lanishi mumkin nomzodga ({sorted(allowed)}), "
                             f"berilgan '{pid}'")
                    continue
                target = pid
            elif act == "REACTIVATE":
                P.append(f"{who}: REACTIVATE faqat DELETED_MATCH uchun")
                continue
        elif cls == "DELETED_MATCH":
            if act == "REACTIVATE":
                pid = dpid or r["target_product_id"]
                c = cand.get(pid)
                if pid != r["target_product_id"] or c is None:
                    P.append(f"{who}: REACTIVATE faqat hisobotdagi o'chirilgan mahsulotga")
                    continue
                if c["claimed"] or c["lot_tracked"] or c["identity_problem"] or not c["deleted"]:
                    P.append(f"{who}: {pid} ni tiklab bo'lmaydi (boshqa identitet/partiya/holat)")
                    continue
                target = pid
            elif act == "CREATE" and r["exact_product_id"]:
                P.append(f"{who}: GUID o'chirilgan mahsulotga tegishli — CREATE ikkinchi identitet bo'lardi")
                continue
            elif act not in ("SKIP", "CREATE"):
                allowed = "REACTIVATE/SKIP" + ("" if r["exact_product_id"] else "/CREATE")
                P.append(f"{who}: DELETED_MATCH — {allowed} qarori SHART")
                continue
        if act == "SKIP":
            skip(r, f"{cls}:SKIP", r["row_targets"])
            continue
        if act == "CREATE" and not g:
            P.append(f"{who}: GUID'siz qatordan mahsulot yaratilmaydi")
            continue

        tf = cand.get(target) if target else None
        if target and tf is None:
            P.append(f"{who}: maqsad {target} hisobot nomzodlarida yo'q")
            continue
        if act == "LINK" and (tf["lot_tracked"] or tf["identity_problem"] or tf["deleted"] or tf["claimed"]):
            P.append(f"{who}: {target} ga LINK mumkin emas (partiya/identitet/o'chirilgan)")
            continue
        codes = set(r["decide"])
        failed = False
        chosen = [target] if target else []                # siyosat qatorni o'tkazsa — mahsulot shu

        # ── 2) birlik ────────────────────────────────────────────────────
        if "UNKNOWN_UNIT" in codes:
            v = need("unknown_unit", f"noma'lum birlik {r['unit']}")
            if v is None:
                continue
            if v == "block":
                P.append(f"{who}: noma'lum birlik ({r['unit']}) va siyosat 'block'")
                continue
            skip(r, "UNKNOWN_UNIT", chosen)
            continue
        if act in ("LINK", "REACTIVATE") and tf["unit"] != "same":
            v = need("unit_differs", f"birlik farqi: 1C {r['unit']['binos']} / BinOS {tf['unit_code']}")
            if v is None:
                continue
            if v == "block":
                P.append(f"{who}: birlik farq qiladi (1C {r['unit']['binos']}, BinOS {tf['unit_code']}) va siyosat 'block'")
                continue
            if v == "skip_row":
                skip(r, "UNIT_DIFFERS", chosen)
                continue

        # ── 3) narx ──────────────────────────────────────────────────────
        sell = r["retail_price"]
        if r["retail_status"] in ("absent", "zero"):
            v = need("missing_price", "narxsiz / 0 narxli qatorlar")
            if v is None:
                continue
            if v == "block":
                P.append(f"{who}: narx {r['retail_status']} va siyosat 'block'")
                continue
            if v == "skip_row":
                skip(r, "MISSING_PRICE", chosen)
                continue
            if act == "CREATE" or Decimal(tf["sell_price"]) <= 0:
                # BinOS'da ham sotuv narxi yo'q — narxsiz mahsulot sotuvga chiqarilmaydi (CREATE bilan AYNI qoida)
                skip(r, "MISSING_PRICE_NO_BINOS_PRICE", chosen)
                continue
            sell = None                                 # LINK/REACTIVATE: BinOS narxi saqlanadi
        elif r["retail_status"] != "positive":
            P.append(f"{who}: narx holati '{r['retail_status']}' — qator BLOCKED bo'lishi kerak edi")
            continue

        # ── 4) qoldiq (tanlangan omborlar -> filiallar) ───────────────────
        stock_wh = dict(r["stock_by_warehouse"])
        if "NEGATIVE_STOCK" in codes:
            v = need("negative_stock", "manfiy qoldiq")
            if v is None:
                continue
            if v == "block":
                P.append(f"{who}: manfiy qoldiq va siyosat 'block'")
                continue
            stock_wh = {w: ("0" if Decimal(q) < 0 else q) for w, q in stock_wh.items()}
        final: dict[str, str] = {}
        for w in sel:
            b = wb.get(w)
            if isinstance(b, str):
                final[b] = _f(Decimal(stock_wh.get(w, "0")))
        before = dict(tf["inventory"]) if tf else {}
        unmapped = {b: q for b, q in before.items() if b not in mapped_branches}
        if unmapped:
            v = need("unmapped_branch_stock", f"{target} ning xaritalanmagan filiallarda qoldig'i bor {unmapped}")
            if v is None:
                continue
            if v == "close":
                for b in unmapped:
                    final[b] = "0"

        # ── 5) barkodlar ─────────────────────────────────────────────────
        add, bskip, existing = [], [], []
        have = set(tf["barcodes"]) if tf else set()
        for bc in r["barcodes"]:
            if bc["value"] in have:
                existing.append(bc["value"])             # maqsadda AYNAN shu satr bor — hech narsa yozilmaydi
                continue
            if not bc["valid"]:
                if need("invalid_barcode", "buzuq barkod") is None:
                    failed = True
                    break
                bskip.append({"value": bc["value"], "reason": "INVALID_BARCODE", "owners": []})
                continue
            others = sorted(set(bc["owners"]) - ({target} if target else set()))
            if others:
                v = need("barcode_owned_by_other", f"barkod {bc['value']} boshqa mahsulotda {others}")
                if v is None or v == "block":
                    if v == "block":
                        P.append(f"{who}: barkod {bc['value']} boshqa mahsulotda {others} va siyosat 'block'")
                    failed = True
                    break
                bskip.append({"value": bc["value"], "reason": "OWNED_BY_OTHER_PRODUCT", "owners": others})
                continue
            add.append(bc["value"])
        if failed:
            continue

        # ── 6) PLU ───────────────────────────────────────────────────────
        plu, clear_plu = None, False
        if act == "CREATE":
            plu = r["plu"]
            if "INVALID_PLU" in codes and need("plu_collision", "buzuq PLU") is None:
                continue
            if plu and (r["plu_owners"] or "PLU_COLLISION" in codes):
                v = need("plu_collision", f"PLU {plu} band / takror")
                if v is None:
                    continue
                if v == "block":
                    P.append(f"{who}: PLU {plu} band va siyosat 'block'")
                    continue
                plu = None
        elif act == "REACTIVATE" and tf["plu_code"] and tf["plu_conflicts"]:
            v = need("plu_collision", f"tiklanadigan {target} ning PLU'si {tf['plu_code']} band")
            if v is None:
                continue
            if v == "block":
                P.append(f"{who}: tiklanadigan mahsulot PLU'si {tf['plu_code']} band va siyosat 'block'")
                continue
            clear_plu = True

        # ── 7) nom ───────────────────────────────────────────────────────
        update_name = None
        if act in ("LINK", "REACTIVATE") and tf["name_differs"]:
            v = need("names", "nom farqi")
            if v is None:
                continue
            update_name = r["name"] if v == "use_1c" else None

        # ── 8) yangi mahsulot artikuli ───────────────────────────────────
        create = None
        if act == "CREATE":
            if "ARTICLE_COLLISION_IN_BUNDLE" in codes and need("article_collision", "artikul takrori") is None:
                continue
            article = None
            for val, taken, used in ((r["article"], r["article_taken_in_binos"], r["article_used_by_other_rows"]),
                                     (r["code"], r["code_taken_in_binos"], r["code_used_by_other_rows"])):
                if val and not taken and not used and val not in articles_assigned:
                    article = val
                    break
            if article is None:
                article = r["fallback_article"]
                if r["fallback_article_taken"] or article in articles_assigned:
                    P.append(f"{who}: artikul uchun bo'sh qiymat yo'q ({article} band)")
                    continue
            articles_assigned.add(article)
            create = {"name": r["name"], "unit_code": r["unit"]["binos"], "is_weighted": r["is_weighted"],
                      "plu": plu, "sku": r["code"], "article_code": article}

        if target:
            if target in used_targets:
                P.append(f"{who}: mahsulot {target} allaqachon {used_targets[target]} ga bog'langan")
                continue
            used_targets[target] = g
        ops.append({
            "guid": g, "row": r["row"], "action": act, "classification": cls,
            "product_id": target, "set_identity": act in ("LINK", "REACTIVATE") and tf["external_id"] is None,
            "activate": act == "LINK" and not tf["is_active"],
            "sell_price": sell, "buy_price": r["purchase_price"], "update_name": update_name,
            "create": create, "clear_plu": clear_plu,
            "barcodes_add": sorted(add), "barcodes_existing": sorted(existing),
            "barcodes_skipped": sorted(bskip, key=lambda x: x["value"]),
            "target_had_barcodes": bool(have),
            "inventory_before": dict(sorted(before.items())),
            "stock_final": dict(sorted(final.items())),
        })

    # ── PLU rejaning O'ZI ichida: yaratilayotgan va tiklanayotgan mahsulotlar ─
    from .catalog import plu_key
    claims: dict[str, list[dict]] = {}
    for o in ops:
        if o["create"] and o["create"]["plu"]:
            claims.setdefault(plu_key(o["create"]["plu"]), []).append(o)
        elif o["action"] == "REACTIVATE" and not o["clear_plu"]:
            tf = next(c for c in rows_by_guid[o["guid"]]["candidates"] if c["product_id"] == o["product_id"])
            if plu_key(tf["plu_code"]) is not None:
                claims.setdefault(plu_key(tf["plu_code"]), []).append(o)
    for k, os_ in sorted(claims.items()):
        if len(os_) > 1:
            v = need("plu_collision", f"reja ichida PLU {k} bir nechta mahsulotga")
            if v == "block":
                P.append(f"reja ichida PLU {k} {[o['guid'] for o in os_]} va siyosat 'block'")
            elif v == "drop_plu":
                for o in os_:
                    if o["create"]:
                        o["create"]["plu"] = None
                    else:
                        o["clear_plu"] = True

    # ── Qarordan KEYIN bog'lanmagan tirik mahsulotlar ──────────────────────
    deactivate, kept = [], []
    for p in report["binos_live_products"]:
        pid = p["product_id"]
        if pid in used_targets:
            continue
        nonzero = {b: q for b, q in p["inventory"].items() if Decimal(q) != 0}
        if not p["is_active"] and not nonzero:
            continue                                     # arxivda va qoldiqsiz — o'zgartiriladigan narsa yo'q
        key = "skipped_row_products" if pid in skipped_targets else "binos_missing_from_source"
        why = (f"{pid} qatori o'tkazib yuborildi ({skipped_targets[pid]})" if pid in skipped_targets
               else f"{pid} 1C'da bog'lanmadi ({p['status']})")
        v = need(key, why)
        if v is None:
            continue
        entry = {"product_id": pid, "reason": key, "status": p["status"], "was_active": p["is_active"],
                 "inventory_before": dict(sorted(nonzero.items())), "close": {}}
        if v == "deactivate_and_zero":
            if p["lot_tracked"]:
                P.append(f"{pid}: partiya kuzatuvli — o'chirib/nollab bo'lmaydi")
                continue
            close = {b: q for b, q in nonzero.items() if b in mapped_branches}
            unmapped = {b: q for b, q in nonzero.items() if b not in mapped_branches}
            if unmapped:
                u = need("unmapped_branch_stock", f"o'chiriladigan {pid} ning xaritalanmagan filialda qoldig'i bor {unmapped}")
                if u is None:
                    continue
                if u == "close":
                    close.update(unmapped)
            entry["close"] = dict(sorted(close.items()))
            deactivate.append(entry)
        else:
            kept.append(entry)

    if P:
        raise MappingError(sorted(set(P)))

    ops.sort(key=lambda o: o["guid"])
    deactivate.sort(key=lambda x: x["product_id"])
    kept.sort(key=lambda x: x["product_id"])
    plan = {
        "company_code": report["binos"]["company_code"], "company_id": report["binos"]["company_id"],
        "mode": mode, "bundle_file_sha256": report["bundle"]["file_sha256"],
        "bundle_content_sha256": report["bundle"]["content_sha256"],
        "snapshot_at": report["bundle"]["snapshot_at"], "export_id": report["bundle"]["export_id"],
        "report_sha256": report["report_sha256"], "mapping_sha256": mapping_sha256(mapping),
        "catalog_fingerprint": report["binos"]["catalog_fingerprint"],
        "warehouse_branch": dict(sorted(wb.items())),
        "policies": dict(sorted(pol.items())),
        "ops": ops, "skipped": sorted(skipped, key=lambda s: (s["guid"] or "", s["row"])),
        "deactivate": deactivate, "kept_unlinked": kept,
        "expected": expected_of(ops, deactivate, mapped_branches),
        "approved_by": mapping.get("approved_by"), "approved_at": mapping.get("approved_at"),
    }
    plan["plan_sha256"] = _sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def movements_of(ops: list[dict], deactivate: list[dict]) -> list[dict]:
    """Reja bo'yicha AYNAN qaysi harakatlar yoziladi (CREATE mahsulot id'si apply'da ma'lum bo'ladi)."""
    out = []
    for o in ops:
        for b, fq in o["stock_final"].items():
            cur = Decimal(o["inventory_before"].get(b, "0"))
            tgt = Decimal(fq)
            if cur != 0:
                out.append({"guid": o["guid"], "product_id": o["product_id"], "branch_id": b, "kind": "close",
                            "qty": _f(-cur), "balance_after": "0"})
            if tgt != 0:
                out.append({"guid": o["guid"], "product_id": o["product_id"], "branch_id": b, "kind": "open",
                            "qty": _f(tgt), "balance_after": _f(tgt)})
    for x in deactivate:
        for b, q in x["close"].items():
            if Decimal(q) != 0:
                out.append({"guid": None, "product_id": x["product_id"], "branch_id": b, "kind": "close_missing",
                            "qty": _f(-Decimal(q)), "balance_after": "0"})
    return out


def expected_of(ops: list[dict], deactivate: list[dict], mapped_branches) -> dict:
    mv = movements_of(ops, deactivate)
    open_by, close_by, after_by = {}, {}, {}
    for m in mv:
        tgt = open_by if m["kind"] == "open" else close_by
        tgt[m["branch_id"]] = tgt.get(m["branch_id"], ZERO) + abs(Decimal(m["qty"]))
    for o in ops:
        for b, q in o["stock_final"].items():
            if b in mapped_branches:
                after_by[b] = after_by.get(b, ZERO) + Decimal(q)
    return {
        "ops": len(ops),
        "link": sum(1 for o in ops if o["action"] == "LINK"),
        "create": sum(1 for o in ops if o["action"] == "CREATE"),
        "reactivate": sum(1 for o in ops if o["action"] == "REACTIVATE"),
        "identity_set": sum(1 for o in ops if o["set_identity"]),
        "activate": sum(1 for o in ops if o["activate"]),
        "prices_set": sum(1 for o in ops if o["sell_price"] is not None and o["action"] != "CREATE"),
        "buy_prices_set": sum(1 for o in ops if o["buy_price"] is not None and o["action"] != "CREATE"),
        "names_set": sum(1 for o in ops if o["update_name"]),
        "barcodes_add": sum(len(o["barcodes_add"]) for o in ops),
        "barcodes_skipped": sum(len(o["barcodes_skipped"]) for o in ops),
        "deactivate": len(deactivate),
        "movements_total": len(mv),
        "movements_open": sum(1 for m in mv if m["kind"] == "open"),
        "movements_close": sum(1 for m in mv if m["kind"] == "close"),
        "movements_close_missing": sum(1 for m in mv if m["kind"] == "close_missing"),
        "open_qty_by_branch": {b: _f(v) for b, v in sorted(open_by.items())},
        "close_qty_by_branch": {b: _f(v) for b, v in sorted(close_by.items())},
        "stock_after_by_mapped_branch": {b: _f(v) for b, v in sorted(after_by.items())},
    }
