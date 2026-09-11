# -*- coding: utf-8 -*-
"""FAYZAN — to'liq artefaktni QURUQ YURGIZISH (`/products/import/preview`).

    python scripts/fayzan_preview.py --file fayzan_artefakt.json

⚠️  BU SKRIPTDA IMPORT YO'LI UMUMAN YO'Q. U faqat `/products/import/preview`
    ni chaqiradi — bu endpoint bazaga faqat `SELECT` qiladi va hech narsa
    yozmaydi. `commit` chaqiruvi kodda MAVJUD EMAS, shuning uchun bu skript
    xato bilan ham mahsulot yarata olmaydi.

⚠️  Parol `getpass` bilan YASHIRIN olinadi. Token chop etilmaydi.

⚠️  ATAYLAB XATO LOGIN QILINMAYDI.
"""
import argparse
import collections
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

P = "https://savdoos-production.up.railway.app/api/v1"
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
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="fayzan_build_import.py chiqargan artefakt")
    a = ap.parse_args()

    art = json.load(open(a.file, encoding="utf-8"))
    rows = art["rows"]
    s = art.get("summary", {})
    payload = len(json.dumps({"rows": rows}).encode())
    say(f"artefakt : {os.path.basename(a.file)}")
    say(f"qatorlar : {len(rows)}   | tana hajmi: {payload/1024/1024:.2f} MB (chegara 20 MB)")
    say(f"chiqarilgan: {s.get('excluded_total')} | takror nom guruhlari: "
        f"{s.get('duplicate_name_groups')} ({s.get('duplicate_name_rows')} qator)")

    if len(rows) > 20000:
        print("XATO: 20000 qatordan oshdi — backend chegarasi.")
        return 1

    # ── Lokal tekshiruv (tarmoqqa chiqishdan OLDIN) ─────────────────────
    bad = collections.Counter()
    for r in rows:
        if not str(r.get("name", "")).strip():
            bad["nom bo'sh"] += 1
        if float(r.get("sell") or 0) <= 0:
            bad["sotish <= 0"] += 1
        if float(r.get("buy") or 0) < 0:
            bad["kelish manfiy"] += 1
        if float(r.get("stock") or 0) < 0:
            bad["qoldiq manfiy"] += 1
        bc = "".join(c for c in str(r.get("barcode") or "") if c.isdigit())
        if r.get("barcode") and not (6 <= len(bc) <= 14):
            bad["barcode 6-14 emas"] += 1
    say()
    say("=== LOKAL TEKSHIRUV (backend qoidalari) ===")
    say("  " + (str(dict(bad)) if bad else "toza — birorta qator backend qoidasini buzmaydi"))
    if bad:
        print("XATO: artefaktda qoidabuzar qator bor — avval fayzan_build_import.py ni tuzating.")
        return 1

    phone = input("\nEga telefoni (+996...): ").strip()
    pw = getpass.getpass("Ega paroli (ekranga chiqmaydi): ")
    st, b = call("POST", "/auth/login/password", {"phone": phone, "password": pw})
    pw = None
    if st != 200:
        print(f"XATO: kirish bo'lmadi (HTTP {st}).")
        return 1
    tok = json.loads(b)["access_token"]
    emp = json.loads(b)["employee"]
    say()
    say(f"kirdi: {emp.get('full_name')} | rol={emp.get('role')} | do'kon={emp.get('company_code')}")

    # ── Bazadagi HOZIRGI katalog ────────────────────────────────────────
    st, b = call("GET", "/products?include_archived=true", None, tok)
    have = {p["name"].strip().lower() for p in json.loads(b)} if st == 200 else set()
    say(f"bazada hozir mahsulot: {len(have)}")

    # ── QURUQ YURISH ────────────────────────────────────────────────────
    st, b = call("POST", "/products/import/preview", {"rows": rows}, tok)
    say()
    say(f"=== QURUQ YURISH (preview) — HTTP {st} ===")
    if st != 200:
        say("  " + b[:600])
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    pv = json.loads(b)
    say(f"  jami    = {pv['total']}")
    say(f"  YANGI   = {pv['new']}")
    say(f"  MAVJUD  = {pv['existing']}   (tashlanadi — bazada allaqachon bor)")
    say(f"  XATO    = {pv['error']}")
    say()
    for x in pv.get("sample", []):
        say(f"    {x['status']:8} | {x['name'][:48]:48} | artikul={x['article']}")

    # ── Mustaqil solishtirish ───────────────────────────────────────────
    mine_existing = [r["name"] for r in rows if r["name"].strip().lower() in have]
    say()
    say("=== MUSTAQIL SOLISHTIRISH (lokal hisob) ===")
    say(f"  bazadagi nom bilan mos keladigan artefakt qatorlari : {len(mine_existing)}")
    for n in mine_existing[:12]:
        say(f"    - {n[:56]}")
    agree = len(mine_existing) == pv["existing"]
    say(f"  server MAVJUD={pv['existing']} | lokal={len(mine_existing)} -> "
        f"{'MOS' if agree else 'FARQ BOR — tekshiring'}")
    say(f"  YANGI + MAVJUD + XATO = {pv['new'] + pv['existing'] + pv['error']} "
        f"(jami {pv['total']} bo'lishi kerak)")

    call("POST", "/auth/logout", None, tok)
    say()
    say("sessiya yopildi")
    say(">>> HECH NARSA IMPORT QILINMADI. Bu skriptda commit yo'li YO'Q.")
    _save()
    return 0 if agree else 1


def _save():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fayzan_preview.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)


if __name__ == "__main__":
    sys.exit(main())
