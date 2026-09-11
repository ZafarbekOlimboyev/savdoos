# -*- coding: utf-8 -*-
"""FAYZAN — PHASE 2: 5568 QO'SHIMCHA shtrix-kodni qo'shish (OPERATOR).

    # 1) QURUQ SINOV — hech narsa yozilmaydi (STANDART):
    python scripts/fayzan_barcodes_phase2.py --set phase2_barcodes.json

    # 2) FAQAT boss ruxsat bergach:
    python scripts/fayzan_barcodes_phase2.py --set phase2_barcodes.json --commit

⚠️  STANDART REJIM — QURUQ SINOV. `--commit` bo'lmasa `/products/barcodes/import`
    UMUMAN chaqirilmaydi (faqat login + o'qish + logout).

⚠️  FAQAT SHTRIX-KOD. Bu skript mahsulot yaratmaydi, narx/qoldiq/birlikka
    tegmaydi, savdo/smena/kassa yozuvi qilmaydi. Yagona yozuv chaqiruvi —
    `/products/barcodes/import`.

⚠️  TEGILMAYDI: 454 tarozi mahsuloti, 214 takror nom guruhi, 9 zarar narxli,
    20 kelish narxsiz mahsulot, kategoriyalar.

⚠️  Parol `getpass` bilan yashirin olinadi; parol/token CHOP ETILMAYDI.
"""
import argparse
import collections
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request

P = "https://savdoos-production.up.railway.app/api/v1"
EXPECT_ROWS = 5568
EXPECT_PRODUCTS = 7137
EXPECT_BARCODES_BEFORE = 7035
EXPECT_BARCODES_AFTER = 12603
BATCH = 1000
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def call(method, path, body=None, token=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(P + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, help="phase2_barcodes.json (nom + barkod)")
    ap.add_argument("--commit", action="store_true",
                    help="HAQIQIY yozuv (busiz — faqat quruq sinov)")
    a = ap.parse_args()

    rows = json.load(open(a.set, encoding="utf-8"))["rows"]
    say("=== TO'PLAM TEKSHIRUVI (tarmoqqa chiqishdan OLDIN) ===")
    hard = []
    if len(rows) != EXPECT_ROWS:
        hard.append(f"qator soni {len(rows)} != {EXPECT_ROWS}")
    bad_fmt = [r for r in rows if not (str(r["barcode"]).isdigit()
                                       and 6 <= len(str(r["barcode"])) <= 14)]
    if bad_fmt:
        hard.append(f"format buzilgan barkod: {len(bad_fmt)}")
    c = collections.Counter(r["barcode"] for r in rows)
    dup = [b for b, n in c.items() if n > 1]
    if dup:
        hard.append(f"to'plam ichida takror barkod: {len(dup)}")
    byb = collections.defaultdict(set)
    for r in rows:
        byb[r["barcode"]].add(r["name"])
    multi = [b for b, v in byb.items() if len(v) > 1]
    if multi:
        hard.append(f"bitta barkod bir nechta mahsulotda: {len(multi)}")
    say(f"  qatorlar={len(rows)} | noyob barkod={len(c)} | maqsad mahsulot={len({r['name'] for r in rows})}")
    if hard:
        for h in hard:
            say(f"  XATO | {h}")
        print("\nTO'XTATILDI — to'plam kutilganidan farq qiladi.")
        _save()
        return 1
    say("  to'plam KUTILGANIGA MOS")

    phone = input("\nEga telefoni (+996...): ").strip()
    pw = getpass.getpass("Ega paroli (ekranga chiqmaydi): ")
    st, b = call("POST", "/auth/login/password", {"phone": phone, "password": pw})
    pw = None
    if st != 200:
        print(f"XATO: kirish bo'lmadi (HTTP {st}).")
        return 1
    tok = json.loads(b)["access_token"]
    emp = json.loads(b)["employee"]
    say(f"\nkirdi: {emp.get('full_name')} | rol={emp.get('role')} | do'kon={emp.get('company_code')}")

    # ── JONLI HOLAT ─────────────────────────────────────────────────────
    st, b = call("GET", "/products?include_archived=true", None, tok)
    if st != 200:
        say(f"XATO: katalog o'qilmadi (HTTP {st})")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    prods = json.loads(b)
    idmap = {p["name"]: p["id"] for p in prods}
    have = {bc for p in prods for bc in (p.get("barcodes") or [])}
    say(f"\n=== PRODUCTION HOZIRGI HOLAT ===")
    say(f"  mahsulot : {len(prods)}   (kutilgan {EXPECT_PRODUCTS})")
    say(f"  barkod   : {len(have)}   (kutilgan {EXPECT_BARCODES_BEFORE})")
    stop = []
    if len(prods) != EXPECT_PRODUCTS:
        stop.append(f"mahsulot soni {len(prods)} != {EXPECT_PRODUCTS}")
    if len(have) != EXPECT_BARCODES_BEFORE:
        stop.append(f"barkod soni {len(have)} != {EXPECT_BARCODES_BEFORE}")

    # ── JONLI HOLAT bilan SOLISHTIRISH ──────────────────────────────────
    miss = [r["name"] for r in rows if r["name"] not in idmap]
    coll = [r["barcode"] for r in rows if r["barcode"] in have]
    say(f"\n=== SOLISHTIRISH ===")
    say(f"  maqsad mahsulot BAZADA YO'Q     : {len(miss)}  {miss[:3]}")
    say(f"  BAZADAGI barkod bilan to'qnashuv: {len(coll)}  {coll[:3]}")
    if miss:
        stop.append(f"{len(miss)} maqsad mahsulot topilmadi")
    if coll:
        stop.append(f"{len(coll)} barkod allaqachon band")
    say(f"\n  kutilgan YAKUNIY barkod soni: {len(have)} + {len(rows)} = {len(have)+len(rows)}"
        f"   (kutilgan {EXPECT_BARCODES_AFTER})")
    if len(have) + len(rows) != EXPECT_BARCODES_AFTER:
        stop.append("yakuniy barkod soni kutilganidan farq qiladi")

    if stop:
        say("")
        for s in stop:
            say(f"  XATO | {s}")
        print("\nTO'XTATILDI — hech narsa yuborilmadi.")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    say("  hammasi kutilganidek")

    if not a.commit:
        say("")
        say(">>> QURUQ SINOV TUGADI — /products/barcodes/import CHAQIRILMADI.")
        say(">>> Haqiqiy yozuv uchun: --commit (faqat boss ruxsatidan keyin).")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 0

    # ── PHASE 2 ─────────────────────────────────────────────────────────
    payload = [{"product_id": idmap[r["name"]], "barcode": r["barcode"]} for r in rows]
    say("")
    say("=== PHASE 2 — /products/barcodes/import ===")
    say(f"{'#':>3} {'yuborildi':>9} {'added':>7} {'skipped':>8} {'HTTP':>5}  {'vaqt':>6}")
    total_add = total_skip = 0
    t0 = time.perf_counter()
    for n, s in enumerate(range(0, len(payload), BATCH), start=1):
        chunk = payload[s:s + BATCH]
        t = time.perf_counter()
        st, body = call("POST", "/products/barcodes/import", {"rows": chunk}, tok)
        dt = time.perf_counter() - t
        add = skip = -1
        if st == 200:
            try:
                j = json.loads(body)
                add, skip = j["added"], j["skipped"]
            except Exception:
                st = -1
        say(f"{n:>3} {len(chunk):>9} {add:>7} {skip:>8} {st:>5}  {dt:>5.1f}s")
        if st != 200 or add != len(chunk) or skip != 0:
            say("")
            say(f"!!! {n}-PARTIYADA KUTILMAGAN JAVOB — TO'XTATILDI !!!")
            say(f"    HTTP={st} added={add} skipped={skip} kutilgan added={len(chunk)} skipped=0")
            say(f"    javob: {body[:300]}")
            say(f"    yuborilmagan qatorlar: {len(payload) - s - len(chunk)}")
            call("POST", "/auth/logout", None, tok)
            _save()
            return 1
        total_add += add
        total_skip += skip

    say("")
    say(f"TUGADI | added={total_add} skipped={total_skip} | vaqt={time.perf_counter()-t0:.0f}s")
    st, b = call("GET", "/products?include_archived=true", None, tok)
    after = {bc for p in json.loads(b) for bc in (p.get("barcodes") or [])} if st == 200 else set()
    say(f"barkod: {len(have)} -> {len(after)}   (kutilgan {EXPECT_BARCODES_AFTER})")
    say("")
    say(">>> Endi tekshiruvni yurgizing: scripts/fayzan_verify_phase2.py")
    call("POST", "/auth/logout", None, tok)
    say("sessiya yopildi")
    _save()
    return 0


def _save():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fayzan_barcodes_phase2.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)


if __name__ == "__main__":
    sys.exit(main())
