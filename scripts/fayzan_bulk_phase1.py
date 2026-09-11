# -*- coding: utf-8 -*-
"""FAYZAN — PHASE 1: 7129 mahsulotni `/products/bulk` orqali yozish (OPERATOR).

    # 1) QURUQ SINOV — hech narsa yozilmaydi (STANDART):
    python scripts/fayzan_bulk_phase1.py --plan fayzan_commit_plan.json

    # 2) FAQAT boss ruxsat bergach:
    python scripts/fayzan_bulk_phase1.py --plan fayzan_commit_plan.json --commit

⚠️  STANDART REJIM — QURUQ SINOV. `--commit` bo'lmasa birorta so'rov ham
    yuborilmaydi (faqat login + o'qish + logout).

⚠️  FAQAT PHASE 1. Bu skriptda `/products/barcodes/import` chaqiruvi YO'Q —
    5568 qo'shimcha barkod ALOHIDA bosqichda, tekshiruvdan KEYIN qo'shiladi.

⚠️  BIRINCHI XATODA TO'XTAYDI. Partiya kutilmagan javob bersa qolgan
    partiyalar YUBORILMAYDI.

⚠️  Parol `getpass` bilan yashirin olinadi. Parol/token HECH QACHON
    chop etilmaydi va faylga yozilmaydi.

⚠️  MOLIYAVIY AMAL YO'Q: savdo, smena, kassa harakati, CashLedgerEntry —
    hech biri yaratilmaydi. Faqat mahsulot + boshlang'ich qoldiq.
"""
import argparse
import collections
import getpass
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

P = "https://savdoos-production.up.railway.app/api/v1"
EXPECT_ROWS = 7129
EXPECT_BATCHES = 15
EXPECT_SHA = "9752bf89b80dc212d4466d4343c9161b19bcf0b08e1c0096acd4dbfc78f10d18"
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


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
    except Exception as e:                      # tarmoq uzilishi ham TO'XTATADI
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="HAQIQIY yozuv (busiz — faqat quruq sinov)")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    items, batches, B = plan["final_items"], plan["batches"], plan["batch_size"]

    # ── REJANI TEKSHIRISH (tarmoqqa chiqishdan OLDIN) ───────────────────
    say("=== REJA TEKSHIRUVI ===")
    hard = []
    if len(items) != EXPECT_ROWS:
        hard.append(f"qator soni {len(items)} != {EXPECT_ROWS}")
    if len(batches) != EXPECT_BATCHES:
        hard.append(f"partiya soni {len(batches)} != {EXPECT_BATCHES}")
    if plan["overall_sha256"] != EXPECT_SHA:
        hard.append("umumiy checksum KUTILGANIDAN FARQ QILADI")
    if max(b["rows"] for b in batches) > 500:
        hard.append("partiya 500 qatordan katta")
    for n, b in enumerate(batches, start=1):
        chunk = items[(n - 1) * B:(n - 1) * B + b["rows"]]
        if sha(chunk) != b["sha256"]:
            hard.append(f"{n}-partiya checksum MOS EMAS")
    units = collections.Counter(i["unit_code"] for i in items)
    if set(units) != {"dona"}:
        hard.append(f"o'lchov birligi: {dict(units)}")
    for fld in ("client_uuid", "name"):
        if len({i[fld] for i in items}) != len(items):
            hard.append(f"{fld} TAKRORI bor")
    bcs = [i["barcode"] for i in items if i.get("barcode")]
    if len(bcs) != len(set(bcs)):
        hard.append("asosiy barkod TAKRORI bor")
    say(f"  qatorlar={len(items)} partiyalar={len(batches)} maks={max(b['rows'] for b in batches)}")
    say(f"  umumiy sha256={plan['overall_sha256']}")
    say(f"  birlik={dict(units)} | barkodli={len(bcs)} | barkodsiz={len(items)-len(bcs)}")
    if hard:
        for h in hard:
            say(f"  XATO | {h}")
        print("\nTO'XTATILDI — reja kutilganidan farq qiladi. Hech narsa yuborilmadi.")
        _save()
        return 1
    say("  reja KUTILGANIGA TO'LIQ MOS")

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

    # ── BOSHLANG'ICH HOLAT ──────────────────────────────────────────────
    st, b = call("GET", "/products?include_archived=true", None, tok)
    if st != 200:
        say(f"XATO: katalog o'qilmadi (HTTP {st})")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    before = json.loads(b)
    say(f"boshlang'ich mahsulot: {len(before)}")
    if len(before) != 8:
        say(f"TO'XTATILDI: 8 ta mahsulot kutilgandi, {len(before)} ta bor.")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    have = {p["name"].strip().lower() for p in before}
    clash = [i["name"] for i in items if i["name"].strip().lower() in have]
    if clash:
        say(f"TO'XTATILDI: rejada bazada MAVJUD nom bor: {clash[:5]}")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 1
    say("bazadagi 8 nom bilan to'qnashuv: 0")

    if not a.commit:
        say("\n>>> QURUQ SINOV TUGADI — birorta partiya yuborilmadi.")
        say(">>> Haqiqiy yozuv uchun: --commit (faqat boss ruxsatidan keyin).")
        call("POST", "/auth/logout", None, tok)
        _save()
        return 0

    # ── PHASE 1: PARTIYALAR ─────────────────────────────────────────────
    say("")
    say("=== PHASE 1 — /products/bulk ===")
    say(f"{'#':>3} {'kutilgan':>8} {'yaratildi':>9} {'HTTP':>5}  {'vaqt':>6}  checksum")
    total_made, t0 = 0, time.perf_counter()
    for n, bm in enumerate(batches, start=1):
        chunk = items[(n - 1) * B:(n - 1) * B + bm["rows"]]
        t = time.perf_counter()
        st, body = call("POST", "/products/bulk", {"items": chunk}, tok)
        dt = time.perf_counter() - t
        made = 0
        if st == 200:
            try:
                made = len(json.loads(body))
            except Exception:
                st = -1
        say(f"{n:>3} {bm['rows']:>8} {made:>9} {st:>5}  {dt:>5.1f}s  {bm['sha256'][:16]}")
        if st != 200 or made != bm["rows"]:
            say("")
            say(f"!!! {n}-PARTIYADA KUTILMAGAN JAVOB — TO'XTATILDI !!!")
            say(f"    HTTP={st} yaratildi={made} kutilgan={bm['rows']}")
            say(f"    javob: {body[:400]}")
            say(f"    yuborilmagan partiyalar: {[x['batch'] for x in batches[n:]]}")
            say(f"    shu paytgacha yaratilgan: {total_made}")
            call("POST", "/auth/logout", None, tok)
            _save()
            return 1
        total_made += made

    say("")
    say(f"BARCHA {len(batches)} PARTIYA MUVAFFAQIYATLI | yaratildi={total_made} "
        f"| vaqt={time.perf_counter()-t0:.0f}s")

    st, b = call("GET", "/products?include_archived=true", None, tok)
    after = json.loads(b) if st == 200 else []
    say(f"katalogdagi mahsulot: {len(before)} -> {len(after)}  "
        f"(kutilgan {len(before) + EXPECT_ROWS})")
    say("")
    say(">>> PHASE 1 TUGADI. QO'SHIMCHA BARKODLAR HALI QO'SHILMADI (Phase 2).")
    say(">>> Endi tekshiruvni yurgizing: scripts/fayzan_verify_phase1.py")
    call("POST", "/auth/logout", None, tok)
    say("sessiya yopildi")
    _save()
    return 0


def _save():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fayzan_bulk_phase1.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)


if __name__ == "__main__":
    sys.exit(main())
