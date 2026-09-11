# -*- coding: utf-8 -*-
"""FAYZAN — PHASE 1 dan KEYINGI TEKSHIRUV. FAQAT O'QISH.

    python scripts/fayzan_verify_phase1.py --plan fayzan_commit_plan.json

⚠️  Bu skript HECH NARSA YOZMAYDI. Ulanish `default_transaction_read_only=on`
    bilan ochiladi — yozuv urinishini BAZANING O'ZI rad etadi.

⚠️  Kredensiallar Railway'dan shu jarayonning ichida olinadi va CHOP ETILMAYDI.

Tekshiradi: mahsulot soni, tenant invariantlari, birlik, tarozi/PLU, artikul va
SKU noyobligi, narx/qoldiq/asosiy barkodni ARTEFAKT bilan qator-ba-qator,
StockMovement soni va turlari.
"""
import argparse
import collections
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RW = os.path.join("C:\\", "Users", "Developer", "nodejs", "node-v20.18.0-win-x64", "railway.cmd")
PROJECT = "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
PROD_ENV = "1d0edbf9-652e-44ae-b4ca-ca58d6c8106f"
PG_SVC = "ac01439d-cfed-47cc-b096-cdc6f8faa379"
COMPANY = "8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5"

EXPECT = {"products": 7137, "companies": 1, "branches": 1, "employees": 2,
          "sales": 0, "shifts": 0, "cash_ledger_entries": 0,
          "reconciliation_records": 0, "stock_movements": 4891}
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def dsn() -> str:
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pvars.gql")
    with open(q, "w", encoding="utf-8") as f:
        f.write("query($pid: String!, $eid: String!, $sid: String!) "
                "{ variables(projectId: $pid, environmentId: $eid, serviceId: $sid) }")
    try:
        raw = subprocess.run([RW, "api", "-f", q, "--var", f"pid={PROJECT}",
                              "--var", f"eid={PROD_ENV}", "--var", f"sid={PG_SVC}"],
                             capture_output=True, text=True, timeout=120).stdout
        V = json.loads(raw)["data"]["variables"]
        return (f"postgresql://{V['PGUSER']}:{V['PGPASSWORD']}@{V['RAILWAY_TCP_PROXY_DOMAIN']}:"
                f"{V['RAILWAY_TCP_PROXY_PORT']}/{V['PGDATABASE']}"
                "?sslmode=prefer&options=-c%20default_transaction_read_only%3Don")
    finally:
        try:
            os.remove(q)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    want = {i["name"]: i for i in plan["final_items"]}

    import psycopg
    ok = True
    with psycopg.connect(dsn(), connect_timeout=30) as con, con.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            print("XATO: read-only kafolatlanmadi — to'xtatildi")
            return 1
        say("sessiya read_only = on")

        say("")
        say("=== KUTILGAN SANOQLAR ===")
        qs = {
            "companies": ("SELECT count(*) FROM companies", ()),
            "branches": ("SELECT count(*) FROM branches WHERE company_id=%s", (COMPANY,)),
            "employees": ("SELECT count(*) FROM employees WHERE company_id=%s", (COMPANY,)),
            "products": ("SELECT count(*) FROM products WHERE company_id=%s AND deleted_at IS NULL", (COMPANY,)),
            "sales": ("SELECT count(*) FROM sales WHERE company_id=%s", (COMPANY,)),
            "shifts": ("SELECT count(*) FROM shifts s JOIN branches b ON b.id=s.branch_id "
                       "WHERE b.company_id=%s", (COMPANY,)),
            "cash_ledger_entries": ("SELECT count(*) FROM cash.cash_ledger_entries WHERE tenant_id=%s", (COMPANY,)),
            "reconciliation_records": ("SELECT count(*) FROM cash.reconciliation_records WHERE tenant_id=%s", (COMPANY,)),
            "stock_movements": ("SELECT count(*) FROM stock_movements sm JOIN products p ON p.id=sm.product_id "
                                "WHERE p.company_id=%s", (COMPANY,)),
        }
        for k, (q, p) in qs.items():
            try:
                cur.execute(q, p)
                got = cur.fetchone()[0]
            except Exception as e:
                con.rollback()
                got = f"?({type(e).__name__})"
            good = got == EXPECT[k]
            ok &= good
            say(f"  {'OK  ' if good else 'XATO'} | {k:24} kutilgan={EXPECT[k]:<6} aslida={got}")

        say("")
        say("=== KATALOG SIFATI ===")
        cur.execute("""SELECT count(*), count(DISTINCT article_code), count(DISTINCT sku),
                              count(*) FILTER (WHERE is_weighted),
                              count(*) FILTER (WHERE plu_code IS NOT NULL),
                              count(*) FILTER (WHERE category_id IS NOT NULL)
                       FROM products WHERE company_id=%s AND deleted_at IS NULL""", (COMPANY,))
        n, na, ns, nw, npl, nc = cur.fetchone()
        for lbl, got, exp in (("artikul NOYOB", na, n), ("sku NOYOB", ns, n),
                              ("is_weighted", nw, 0), ("plu_code", npl, 0),
                              ("kategoriyali", nc, 0)):
            good = got == exp
            ok &= good
            say(f"  {'OK  ' if good else 'XATO'} | {lbl:24} kutilgan={exp:<6} aslida={got}")

        cur.execute("""SELECT u.code, count(*) FROM products p JOIN units u ON u.id=p.unit_id
                       WHERE p.company_id=%s AND p.deleted_at IS NULL GROUP BY u.code""", (COMPANY,))
        units = dict(cur.fetchall())
        good = units == {"dona": EXPECT["products"]}
        ok &= good
        say(f"  {'OK  ' if good else 'XATO'} | {'o`lchov birligi':24} {units}")

        say("")
        say("=== StockMovement TURLARI ===")
        cur.execute("""SELECT sm.type::text, sm.ref_type, count(*) FROM stock_movements sm
                       JOIN products p ON p.id=sm.product_id WHERE p.company_id=%s
                       GROUP BY 1,2 ORDER BY 3 DESC""", (COMPANY,))
        rows = cur.fetchall()
        for t, rt, c in rows:
            say(f"    {t} / {rt} : {c}")
        bad = [r for r in rows if r[0] != "adjustment" or r[1] not in ("import", "product_create")]
        ok &= not bad
        say(f"  {'OK  ' if not bad else 'XATO'} | inventarizatsiyadan boshqa harakat: {len(bad)}")

        say("")
        say("=== ARTEFAKT BILAN QATOR-BA-QATOR ===")
        cur.execute("""SELECT p.name, p.base_buy_price, p.base_sell_price,
                              coalesce((SELECT sum(i.qty) FROM inventory i WHERE i.product_id=p.id),0),
                              (SELECT string_agg(b.barcode, ',' ORDER BY b.barcode)
                                 FROM product_barcodes b WHERE b.product_id=p.id)
                       FROM products p WHERE p.company_id=%s AND p.deleted_at IS NULL""", (COMPANY,))
        seen = miss = bad_sell = bad_buy = bad_stock = bad_bc = 0
        for nm, buy, sell, qty, bcs in cur.fetchall():
            it = want.get(nm)
            if it is None:
                continue                       # bazadagi 8 namuna — rejada yo'q
            seen += 1
            if abs(float(sell) - it["sell_price"]) > 1e-6:
                bad_sell += 1
            if abs(float(buy) - it["buy_price"]) > 1e-6:
                bad_buy += 1
            if abs(float(qty) - it["stock"]) > 1e-6:
                bad_stock += 1
            if it.get("barcode") and it["barcode"] not in (bcs or "").split(","):
                bad_bc += 1
        miss = len(want) - seen
        for lbl, v in (("rejadan topilgan", seen), ("YO'Q", miss), ("sotish farqi", bad_sell),
                       ("kelish farqi", bad_buy), ("qoldiq farqi", bad_stock),
                       ("asosiy barkod yo'q", bad_bc)):
            good = (v == len(want)) if lbl == "rejadan topilgan" else (v == 0)
            ok &= good
            say(f"  {'OK  ' if good else 'XATO'} | {lbl:24} {v}")

        say("")
        say("=== BARKOD (Phase 2 HALI QILINMAGAN) ===")
        cur.execute("SELECT count(*) FROM product_barcodes WHERE company_id=%s", (COMPANY,))
        nb = cur.fetchone()[0]
        good = nb == 7035
        ok &= good
        say(f"  {'OK  ' if good else 'XATO'} | barkod jami kutilgan=7035 aslida={nb}")
        say("    (5 mavjud asosiy + 7030 yangi asosiy; 5568 qo'shimcha — Phase 2)")

    say("")
    say(f"=== XULOSA: {'PHASE 1 TO`LIQ TOZA' if ok else 'FARQ BOR — PHASE 2 NI BOSHLAMANG'} ===")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fayzan_verify_phase1.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
