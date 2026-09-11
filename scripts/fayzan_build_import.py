# -*- coding: utf-8 -*-
"""FAYZAN — 1С eksportidan IMPORT ARTEFAKTINI qurish (LOKAL, tarmoqsiz).

    python scripts/fayzan_build_import.py --src "C:\\...\\Telegram Desktop" -o artefakt.json

⚠️  BU SKRIPT HECH NARSA IMPORT QILMAYDI. U faqat .xls fayllarni o'qib,
    normallashtirib, tasniflab, JSON artefakt va batafsil hisobot yozadi.
    Tarmoqqa UMUMAN chiqmaydi.

⚠️  HECH QANDAY QAROR JIMGINA QABUL QILINMAYDI. Har bir chiqarib tashlash va
    har bir tuzatish (manfiy qoldiq -> 0) aniq SON bilan hisobotda ko'rinadi.

TASNIF (nima kiradi, nima kutadi):
  · kiradi   — nomi NOYOB, sotish narxi > 0, birligi «шт»
  · KUTADI   — birligi «кг» (tarozi): is_weighted/plu_code tasdiqlanmagan
  · KUTADI   — nomi TAKRORLANADIGAN guruhlar: 1С bir nechta HAR XIL mahsulotni
               bitta nom bilan chiqargan; qaysi narx qaysi tovarники ekani
               manbada YO'Q. Bu — do'kon egasi hal qiladigan savol.
  · chiqadi  — sotish narxi yo'q (sotib bo'lmaydi)
"""
import argparse
import collections
import importlib.util
import json
import os
import pathlib
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SRC = pathlib.Path(__file__).resolve().parents[1] / "apps" / "server" / "tools" / "import_1c.py"
_spec = importlib.util.spec_from_file_location("import_1c", _SRC)
IC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IC)

# SavdoOS `units` jadvalidagi kodlar. 1С birligini SHU YERDA aniq belgilaymiz —
# import endpointi birlik bermasa tartibsiz `SELECT`ning 1-qatorini oladi.
UNIT_MAP = {"шт": "dona", "кг": "kg", "л": "litr", "упак": "upak"}
DEFAULT_UNIT = "dona"

LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def build(src: pathlib.Path):
    sena = src / "sena.xls"
    astatka = src / "astatka.xls"
    spisok9 = src / "Список9.xls"
    for f in (sena, astatka, spisok9):
        if not f.exists():
            sys.exit(f"XATO: fayl topilmadi: {f}")

    say("=== 1. MANBA ===")
    rows_sena = IC.load_file(str(sena))
    rows_ast = IC.load_file(str(astatka))
    rows_bc = IC.load_file(str(spisok9))
    say(f"  sena.xls     nomli qatorlar : {len(rows_sena)}")
    say(f"  astatka.xls  nomli qatorlar : {len(rows_ast)}")
    say(f"  Список9.xls  barkod qatori  : {len(rows_bc)}")

    # ── Nom bo'yicha guruhlash (TAKROR nomlarni KO'RISH uchun) ──────────
    sena_by = collections.defaultdict(list)
    for r in rows_sena:
        sena_by[IC.norm_key(r["name"])].append(r)
    ast_by = {}
    for r in rows_ast:
        ast_by.setdefault(IC.norm_key(r["name"]), r)
    bc_by = collections.defaultdict(list)
    for r in rows_bc:
        d = IC._digits(r.get("barcode"))
        if d:
            k = IC.norm_key(r["name"])
            if d not in bc_by[k]:
                bc_by[k].append(d)

    say()
    say("=== 2. NOM TAKRORI (1С bir nechta tovarni bitta nom bilan chiqargan) ===")
    dup_keys = {k for k, v in sena_by.items() if len(v) > 1}
    dup_rows = sum(len(sena_by[k]) for k in dup_keys)
    confl = 0
    for k in dup_keys:
        v = sena_by[k]
        if len({r.get("sell") for r in v}) > 1 or len({r.get("buy") for r in v}) > 1:
            confl += 1
    say(f"  takrorlanadigan nom guruhlari : {len(dup_keys)}")
    say(f"  ularga tegishli xom qatorlar  : {dup_rows}")
    say(f"  narxi ZIDDIYATLI guruhlar     : {confl}")
    say(f"  nom bo'yicha import qilinsa YO'QOLADIGAN mahsulot: {dup_rows - len(dup_keys)}")
    say("  -> BU GURUHLAR ARTEFAKTGA KIRMAYDI (do'kon egasi hal qilishi kerak)")

    # ── Yagona nomli mahsulotlar ────────────────────────────────────────
    uniq = {k: v[0] for k, v in sena_by.items() if len(v) == 1}
    say()
    say(f"=== 3. YAGONA nomli mahsulotlar: {len(uniq)} ===")

    kept, excluded = [], []
    neg_fixed = neg_total = 0
    unit_counts = collections.Counter()
    blank_stock = 0

    for k, r in sorted(uniq.items()):
        a = ast_by.get(k)
        unit_raw = (a or {}).get("unit")
        unit_counts[unit_raw or "(qoldiq fayli yo'q)"] += 1
        sell = r.get("sell")
        buy = r.get("buy")
        stock = (a or {}).get("stock")

        if sell is None or sell <= 0:
            excluded.append((k, r["name"], "sotish narxi yo'q", sell, unit_raw))
            continue
        if unit_raw == "кг":
            excluded.append((k, r["name"], "tarozi (кг) — tasdiqlanmagan", sell, unit_raw))
            continue

        if stock is None:
            blank_stock += 1
            stock = 0.0
        elif stock < 0:
            neg_fixed += 1
            neg_total += stock
            stock = 0.0

        bcs = bc_by.get(k, [])
        kept.append({
            "key": k,
            "name": r["name"],
            "buy": round(float(buy), 2) if buy is not None and buy >= 0 else 0.0,
            "sell": round(float(sell), 2),
            "stock": round(float(stock), 3),
            "unit_code": UNIT_MAP.get(unit_raw, DEFAULT_UNIT),
            "barcodes": sorted(bcs),
        })

    say()
    say("=== 4. MANFIY QOLDIQ (STEP 3) ===")
    all_neg = [r for r in rows_ast if (r.get("stock") or 0) < 0]
    say(f"  A. manbadagi MANFIY qoldiqli qatorlar : {len(all_neg)}")
    say(f"     jami manfiy miqdor                 : {sum(r['stock'] for r in all_neg):.3f}")
    say(f"  B. shulardan ARTEFAKTGA kirganlari    : {neg_fixed}")
    say(f"     ularning jami manfiy miqdori       : {neg_total:.3f}")
    say(f"  qoldiq ustuni BO'SH bo'lganlar        : {blank_stock}  -> 0 qilindi")
    say("  qoida: boshlang'ich qoldiq = max(manba, 0) — HAR BIRI yuqorida sanalgan")

    say()
    say("=== 5. O'LCHOV BIRLIGI (STEP 6) ===")
    for u, n in unit_counts.most_common():
        say(f"  {str(u):24} -> {UNIT_MAP.get(u, DEFAULT_UNIT) if u in UNIT_MAP else DEFAULT_UNIT:6} | {n}")
    say("  birlik ARTEFAKTDA aniq ko'rsatiladi — tartibsiz SELECT'ga tayanilmaydi")

    say()
    say("=== 6. BARKOD (STEP 5) ===")
    dist = collections.Counter(min(len(r["barcodes"]), 6) for r in kept)
    for n in sorted(dist):
        say(f"  {n if n < 6 else '6+'} barkod : {dist[n]}")
    with_bc = sum(1 for r in kept if r["barcodes"])
    multi = sum(1 for r in kept if len(r["barcodes"]) > 1)
    total_bc = sum(len(r["barcodes"]) for r in kept)
    say(f"  barkodi BOR : {with_bc} | barkodi YO'Q : {len(kept) - with_bc}")
    say(f"  bir nechta barkodli : {multi} | JAMI noyob barkod : {total_bc}")
    primary = {r["barcodes"][0] for r in kept if r["barcodes"]}
    say(f"  ASOSIY barkod (eng kichigi — deterministik) : {len(primary)}")
    say(f"  qo'shimcha barkod (keyin alohida endpoint)  : {total_bc - len(primary)}")
    seen, coll = set(), 0
    for r in kept:
        for b in r["barcodes"]:
            if b in seen:
                coll += 1
            seen.add(b)
        continue
    say(f"  mahsulotlararo barkod TO'QNASHUVI : {coll}")

    say()
    say("=== 7. CHIQARIB TASHLANGANLAR ===")
    why = collections.Counter(e[2] for e in excluded)
    for w, n in why.most_common():
        say(f"  {w:34} : {n}")
    say(f"  JAMI chiqarib tashlangan : {len(excluded)}")

    # ── Artefakt ────────────────────────────────────────────────────────
    ns = uuid.UUID("f0000000-0000-4000-8000-000000000001")   # Fayzan uchun barqaror ad
    rows_api, bulk, extra_bc = [], [], []
    for r in kept:
        row = {"name": r["name"], "buy": r["buy"], "sell": r["sell"], "stock": r["stock"]}
        if r["barcodes"]:
            row["barcode"] = r["barcodes"][0]
        rows_api.append(row)
        bulk.append({
            "name": r["name"],
            "unit_code": r["unit_code"],          # ANIQ birlik — STEP 6
            "buy_price": r["buy"], "sell_price": r["sell"],
            "stock": r["stock"], "min_qty": 0,
            "is_weighted": False, "plu_code": None,
            **({"barcode": r["barcodes"][0]} if r["barcodes"] else {}),
            "client_uuid": str(uuid.uuid5(ns, r["key"])),   # qayta yurgizish idempotent
        })
        for b in r["barcodes"][1:]:
            extra_bc.append({"name": r["name"], "barcode": b})

    say()
    say("=== 8. ARTEFAKT ===")
    say(f"  import qatorlari (preview/commit shakli) : {len(rows_api)}")
    say(f"  bulk qatorlari (birlik bilan)            : {len(bulk)}")
    say(f"  keyin qo'shiladigan qo'shimcha barkod    : {len(extra_bc)}")
    say(f"  narx qamrovi  : {sum(1 for r in kept if r['sell'] > 0)} / {len(kept)}")
    say(f"  kelish qamrovi: {sum(1 for r in kept if r['buy'] > 0)} / {len(kept)}")
    say(f"  qoldiq qamrovi: {sum(1 for r in kept if r['stock'] > 0)} / {len(kept)}")

    return {
        "rows": rows_api,
        "bulk_items": bulk,
        "extra_barcodes": extra_bc,
        "excluded": [{"name": n, "reason": w, "sell": s, "unit": u}
                     for _, n, w, s, u in excluded],
        "duplicate_name_groups": [
            {"name": sena_by[k][0]["name"], "rows": len(sena_by[k]),
             "sells": sorted({r.get("sell") for r in sena_by[k] if r.get("sell") is not None}),
             "buys": sorted({r.get("buy") for r in sena_by[k] if r.get("buy") is not None})}
            for k in sorted(dup_keys)],
        "summary": {
            "source_rows_sena": len(rows_sena),
            "source_rows_astatka": len(rows_ast),
            "source_rows_barcodes": len(rows_bc),
            "unique_names_sena": len(sena_by),
            "duplicate_name_groups": len(dup_keys),
            "duplicate_name_rows": dup_rows,
            "duplicate_name_conflicting": confl,
            "final_products": len(kept),
            "excluded_total": len(excluded),
            "excluded_by_reason": dict(why),
            "negative_stock_source_rows": len(all_neg),
            "negative_stock_source_total": round(sum(r["stock"] for r in all_neg), 3),
            "negative_stock_adjusted": neg_fixed,
            "negative_stock_adjusted_total": round(neg_total, 3),
            "blank_stock_zeroed": blank_stock,
            "with_barcode": with_bc,
            "without_barcode": len(kept) - with_bc,
            "multi_barcode": multi,
            "unique_barcodes": total_bc,
            "extra_barcodes": len(extra_bc),
            "barcode_collisions": coll,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"C:\Users\Developer\Downloads\Telegram Desktop")
    ap.add_argument("-o", "--out", default="fayzan_artefakt.json")
    a = ap.parse_args()

    art = build(pathlib.Path(a.src))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    say()
    say(f"artefakt yozildi: {a.out}  ({os.path.getsize(a.out)/1024/1024:.2f} MB)")
    with open(os.path.splitext(a.out)[0] + ".out", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    say("HECH NARSA IMPORT QILINMADI — bu faqat quruq yurish artefakti.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
