# -*- coding: utf-8 -*-
"""FAYZAN — 5-10 ta HAQIQIY mahsulot bilan NAMUNA IMPORT (operator yurgizadi).

    # 1) QURUQ SINOV — hech narsa yozilmaydi (standart rejim):
    python scripts/fayzan_sample_import.py --file <namuna.xlsx>

    # 2) FAQAT boss ruxsat bergach — haqiqiy yozuv:
    python scripts/fayzan_sample_import.py --file <namuna.xlsx> --commit

⚠️  STANDART REJIM — QURUQ SINOV. `--commit` bo'lmasa skript FAQAT
    `POST /products/import/preview` chaqiradi; bu endpoint hech narsa
    yozmaydi (bazaga faqat SELECT qiladi).

⚠️  Parol `getpass` bilan YASHIRIN olinadi — ekranga chiqmaydi, faylga va
    logga yozilmaydi. Token chop etilmaydi.

⚠️  MOLIYAVIY AMAL YO'Q: savdo, smena, kassa harakati, CashLedgerEntry —
    hech biri yaratilmaydi. Faqat mahsulot + boshlang'ich qoldiq.

⚠️  ATAYLAB XATO LOGIN QILINMAYDI (haqiqiy mijozda auth qoldig'i qolmasin).
"""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

P = "https://savdoos-production.up.railway.app/api/v1"
COLS = {"Наименование": "name", "Артикул": "article", "Категория": "category",
        "Цена закупки": "buy", "Цена продажи": "sell", "Остаток": "stock",
        "Штрихкод": "barcode", "name": "name", "article": "article",
        "category": "category", "buy": "buy", "sell": "sell", "stock": "stock",
        "barcode": "barcode"}
NUM = {"buy", "sell", "stock"}
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(P + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def load_rows(path):
    """.xlsx / .xls / .json dan import qatorlarini o'qiydi (LOKAL, tarmoqsiz)."""
    if path.lower().endswith(".json"):
        return json.load(open(path, encoding="utf-8"))["rows"]
    import pandas as pd
    df = pd.read_excel(path, sheet_name=0, dtype=object)
    out = []
    for _, rec in df.iterrows():
        row = {}
        for col, val in rec.items():
            k = COLS.get(str(col).strip())
            if not k or val is None or (isinstance(val, float) and val != val):
                continue
            s = str(val).strip()
            if s == "":
                continue
            row[k] = float(s.replace(",", ".")) if k in NUM else s
        if row.get("name"):
            out.append(row)
    return out


def local_check(rows):
    """Serverga bormasdan LOKAL tekshiruv — backend qoidalarining nusxasi."""
    bad = []
    for i, r in enumerate(rows, 1):
        if not str(r.get("name", "")).strip():
            bad.append(f"{i}-qator: nom bo'sh")
        if float(r.get("sell") or 0) <= 0:
            bad.append(f"{i}-qator: sotish narxi <= 0 (backend 'error' qiladi)")
        if float(r.get("buy") or 0) < 0:
            bad.append(f"{i}-qator: kelish narxi manfiy")
        if float(r.get("stock") or 0) < 0:
            bad.append(f"{i}-qator: qoldiq manfiy (0 ga tushiring)")
        bc = "".join(c for c in str(r.get("barcode") or "") if c.isdigit())
        if r.get("barcode") and not (6 <= len(bc) <= 14):
            bad.append(f"{i}-qator: barcode 6-14 raqam emas — backend TASHLAYDI "
                       "(mahsulot baribir yaratiladi)")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="namuna .xlsx / .xls / .json")
    ap.add_argument("--commit", action="store_true",
                    help="HAQIQIY yozuv (busiz — faqat quruq sinov)")
    a = ap.parse_args()

    rows = load_rows(a.file)
    say(f"fayl: {os.path.basename(a.file)} | qatorlar: {len(rows)}")
    if not rows:
        print("XATO: qator topilmadi.")
        return 1
    if len(rows) > 10:
        print(f"XATO: namuna 10 qatordan oshmasin ({len(rows)} ta). "
              "To'liq import ALOHIDA bosqich.")
        return 1

    say("")
    say("=== LOKAL TEKSHIRUV (tarmoqsiz) ===")
    bad = local_check(rows)
    for b in bad:
        say("  OGOH | " + b)
    if not bad:
        say("  hammasi backend qoidalariga mos")

    say("")
    say("=== QATORLAR ===")
    for r in rows:
        say(f"  {str(r['name'])[:42]:42} | art={r.get('article') or 'AVTO':12} "
            f"| kelish={float(r.get('buy') or 0):>8.2f} "
            f"| sotish={float(r.get('sell') or 0):>8.2f} "
            f"| qoldiq={float(r.get('stock') or 0):>8.3f} "
            f"| bc={r.get('barcode') or '-'}")

    phone = input("\nEga telefoni (+996...): ").strip()
    pw = getpass.getpass("Ega paroli (ekranga chiqmaydi): ")
    st, b = call("POST", "/auth/login/password", {"phone": phone, "password": pw})
    pw = None
    if st != 200:
        print(f"XATO: kirish bo'lmadi (HTTP {st}).")
        return 1
    tok = json.loads(b)["access_token"]
    emp = json.loads(b)["employee"]
    say("")
    say(f"kirdi: {emp.get('full_name')} | rol={emp.get('role')} "
        f"| do'kon={emp.get('company_code')}")

    # ── QURUQ SINOV: preview hech narsa YOZMAYDI ────────────────────────
    st, b = call("POST", "/products/import/preview", {"rows": rows}, tok)
    say("")
    say(f"=== QURUQ SINOV (preview) — HTTP {st} ===")
    if st != 200:
        say("  " + b[:400])
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    pv = json.loads(b)
    say(f"  jami={pv['total']}  YANGI={pv['new']}  "
        f"MAVJUD(tashlanadi)={pv['existing']}  XATO={pv['error']}")
    for s in pv.get("sample", []):
        say(f"    {s['status']:8} | {s['name'][:44]:44} | artikul={s['article']}")

    if not a.commit:
        say("")
        say(">>> QURUQ SINOV TUGADI — bazaga HECH NARSA yozilmadi.")
        say(">>> Haqiqiy import uchun: --commit qo'shing (faqat boss ruxsatidan keyin).")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 0

    if pv["new"] != len(rows):
        say("")
        say(f"TO'XTATILDI: {len(rows)} qatordan faqat {pv['new']} tasi YANGI. "
            "Namuna toza bo'lishi shart — avval sababni aniqlang.")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1

    # ── HAQIQIY YOZUV ───────────────────────────────────────────────────
    st, b = call("POST", "/products/import/commit", {"rows": rows}, tok)
    say("")
    say(f"=== IMPORT (commit) — HTTP {st} ===")
    if st != 200:
        say("  " + b[:400])
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    res = json.loads(b)
    d = res["detail"]
    say(f"  import={res['imported']} tashlandi={res['skipped']}")
    say(f"  sabablar: xato={d['error']} nom_band={d['name_exists']} "
        f"artikul_band={d['article_busy']} barcode_tashlandi={d['barcode_dropped']} "
        f"kategoriya_topilmadi={d['category_missing']}")

    # ── TEKSHIRUV ───────────────────────────────────────────────────────
    say("")
    say("=== TEKSHIRUV (o'qish) ===")
    ok = res["imported"] == len(rows) and res["skipped"] == 0
    for r in rows:
        q = urllib.parse.quote(str(r["name"])[:30])
        st, b = call("GET", f"/products?q={q}", None, tok)
        hit = None
        if st == 200:
            for pr in json.loads(b):
                if pr["name"].strip() == str(r["name"]).strip():
                    hit = pr
                    break
        if not hit:
            ok = False
            say(f"  YO'Q | {str(r['name'])[:40]}")
            continue
        s_ok = abs(float(hit.get("stock") or 0) - float(r.get("stock") or 0)) < 1e-6
        p_ok = abs(float(hit.get("base_sell_price") or 0) - float(r.get("sell") or 0)) < 1e-6
        b_ok = (not r.get("barcode")) or (str(r["barcode"]) in (hit.get("barcodes") or []))
        ok = ok and s_ok and p_ok and b_ok
        say(f"  {'OK  ' if (s_ok and p_ok and b_ok) else 'XATO'} | {hit['name'][:36]:36} "
            f"| art={hit.get('article_code')} | narx={hit.get('base_sell_price')} "
            f"| qoldiq={hit.get('stock')} "
            f"| barcode={'bor' if hit.get('barcodes') else 'yoq'}")

    say("")
    say("=== NATIJA: " + ("NAMUNA IMPORT MUVAFFAQIYATLI" if ok
                          else "NAMUNA IMPORTDA FARQ BOR") + " ===")
    call("POST", "/auth/logout", None, tok)
    say("sessiya yopildi")
    _save()
    return 0 if ok else 1


def _save():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "fayzan_sample_import.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)


if __name__ == "__main__":
    sys.exit(main())
