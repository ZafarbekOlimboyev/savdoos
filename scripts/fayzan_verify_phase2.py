# -*- coding: utf-8 -*-
"""FAYZAN — PHASE 2 dan KEYINGI TEKSHIRUV. FAQAT O'QISH.

    python scripts/fayzan_verify_phase2.py --set phase2_barcodes.json

⚠️  HECH NARSA YOZMAYDI. Ulanish `default_transaction_read_only=on` bilan
    ochiladi — yozuv urinishini BAZANING O'ZI rad etadi.

⚠️  Kredensiallar Railway'dan shu jarayon ichida olinadi, CHOP ETILMAYDI.

Tekshiradi: sanoqlar, 5568 qo'shimcha barkodning HAR BIRI kerakli mahsulotda
ekani, ushlab qolingan guruhlarga TEGILMAGANI, va mahsulot/qoldiq/narx/harakat
Phase 1 dagidek qolgani.
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

EXPECT = {"products": 7137, "product_barcodes": 12603, "stock_movements": 4891,
          "companies": 1, "branches": 1, "employees": 2, "sales": 0, "shifts": 0,
          "cash_ledger_entries": 0, "reconciliation_records": 0, "inventory": 7137}
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def dsn() -> str:
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_p2vars.gql")
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
    ap.add_argument("--set", required=True)
    ap.add_argument("--plan", help="fayzan_commit_plan.json (narx/qoldiq solishtiruvi uchun)")
    a = ap.parse_args()
    sec = json.load(open(a.set, encoding="utf-8"))["rows"]

    import psycopg
    ok = True
    with psycopg.connect(dsn(), connect_timeout=30) as con, con.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            print("XATO: read-only kafolatlanmadi")
            return 1
        say("sessiya read_only = on")

        say("")
        say("=== KUTILGAN SANOQLAR ===")
        qs = {
            "companies": ("SELECT count(*) FROM companies", ()),
            "branches": ("SELECT count(*) FROM branches WHERE company_id=%s", (COMPANY,)),
            "employees": ("SELECT count(*) FROM employees WHERE company_id=%s", (COMPANY,)),
            "products": ("SELECT count(*) FROM products WHERE company_id=%s AND deleted_at IS NULL", (COMPANY,)),
            "product_barcodes": ("SELECT count(*) FROM product_barcodes WHERE company_id=%s", (COMPANY,)),
            "inventory": ("SELECT count(*) FROM inventory i JOIN products p ON p.id=i.product_id "
                          "WHERE p.company_id=%s", (COMPANY,)),
            "stock_movements": ("SELECT count(*) FROM stock_movements sm JOIN products p ON p.id=sm.product_id "
                                "WHERE p.company_id=%s", (COMPANY,)),
            "sales": ("SELECT count(*) FROM sales WHERE company_id=%s", (COMPANY,)),
            "shifts": ("SELECT count(*) FROM shifts s JOIN branches b ON b.id=s.branch_id "
                       "WHERE b.company_id=%s", (COMPANY,)),
            "cash_ledger_entries": ("SELECT count(*) FROM cash.cash_ledger_entries WHERE tenant_id=%s", (COMPANY,)),
            "reconciliation_records": ("SELECT count(*) FROM cash.reconciliation_records WHERE tenant_id=%s", (COMPANY,)),
        }
        for k, (q, prm) in qs.items():
            try:
                cur.execute(q, prm)
                got = cur.fetchone()[0]
            except Exception as e:
                con.rollback()
                got = f"?({type(e).__name__})"
            good = got == EXPECT[k]
            ok &= good
            say(f"  {'OK  ' if good else 'XATO'} | {k:24} kutilgan={EXPECT[k]:<7} aslida={got}")

        say("")
        say("=== 5568 QO'SHIMCHA BARKOD KERAKLI MAHSULOTDAMI ===")
        cur.execute("""SELECT b.barcode, p.name FROM product_barcodes b
                       JOIN products p ON p.id=b.product_id
                       WHERE b.company_id=%s""", (COMPANY,))
        owner = dict(cur.fetchall())
        miss = [x for x in sec if x["barcode"] not in owner]
        wrong = [x for x in sec if x["barcode"] in owner and owner[x["barcode"]] != x["name"]]
        say(f"  {'OK  ' if not miss else 'XATO'} | bazada YO'Q            : {len(miss)}  "
            f"{[m['barcode'] for m in miss[:3]]}")
        say(f"  {'OK  ' if not wrong else 'XATO'} | NOTO'G'RI mahsulotda   : {len(wrong)}  "
            f"{[(w['barcode'], owner[w['barcode']][:24]) for w in wrong[:3]]}")
        ok &= not miss and not wrong

        cur.execute("""SELECT count(*) FROM (SELECT barcode FROM product_barcodes
                       WHERE company_id=%s GROUP BY barcode HAVING count(*)>1) t""", (COMPANY,))
        dupbc = cur.fetchone()[0]
        say(f"  {'OK  ' if dupbc == 0 else 'XATO'} | takrorlangan barkod    : {dupbc}")
        ok &= dupbc == 0

        cur.execute("""SELECT count(*) FROM product_barcodes b LEFT JOIN products p ON p.id=b.product_id
                       WHERE b.company_id=%s AND (p.id IS NULL OR p.company_id <> b.company_id)""",
                    (COMPANY,))
        orph = cur.fetchone()[0]
        say(f"  {'OK  ' if orph == 0 else 'XATO'} | egasiz/begona havola   : {orph}")
        ok &= orph == 0

        say("")
        say("=== KATALOG PHASE 1 DAGIDEK QOLDIMI ===")
        cur.execute("""SELECT count(*) FILTER (WHERE is_weighted),
                              count(*) FILTER (WHERE plu_code IS NOT NULL),
                              count(*) FILTER (WHERE category_id IS NOT NULL),
                              count(DISTINCT article_code), count(*)
                       FROM products WHERE company_id=%s AND deleted_at IS NULL""", (COMPANY,))
        nw, npl, nc, na, n = cur.fetchone()
        for lbl, got, exp in (("is_weighted", nw, 0), ("plu_code", npl, 0),
                              ("kategoriyali", nc, 0), ("artikul NOYOB", na, n)):
            good = got == exp
            ok &= good
            say(f"  {'OK  ' if good else 'XATO'} | {lbl:24} kutilgan={exp:<7} aslida={got}")
        cur.execute("""SELECT u.code, count(*) FROM products p JOIN units u ON u.id=p.unit_id
                       WHERE p.company_id=%s AND p.deleted_at IS NULL GROUP BY u.code""", (COMPANY,))
        units = dict(cur.fetchall())
        good = units == {"dona": EXPECT["products"]}
        ok &= good
        say(f"  {'OK  ' if good else 'XATO'} | {'o`lchov birligi':24} {units}")

        cur.execute("""SELECT sm.type::text, sm.ref_type, count(*) FROM stock_movements sm
                       JOIN products p ON p.id=sm.product_id WHERE p.company_id=%s
                       GROUP BY 1,2 ORDER BY 3 DESC""", (COMPANY,))
        rows = cur.fetchall()
        say("")
        say("=== StockMovement (o'zgarmasligi shart) ===")
        for t, rt, cnt in rows:
            say(f"    {t} / {rt} : {cnt}")
        bad = [r for r in rows if r[0] != "adjustment" or r[1] not in ("import", "product_create")]
        ok &= not bad
        say(f"  {'OK  ' if not bad else 'XATO'} | inventarizatsiyadan boshqa harakat: {len(bad)}")

        if a.plan:
            plan = json.load(open(a.plan, encoding="utf-8"))
            want = {i["name"]: i for i in plan["final_items"]}
            cur.execute("""SELECT p.name, p.base_buy_price, p.base_sell_price,
                                  coalesce((SELECT sum(i.qty) FROM inventory i WHERE i.product_id=p.id),0)
                           FROM products p WHERE p.company_id=%s AND p.deleted_at IS NULL""", (COMPANY,))
            bp = bs = bq = seen = 0
            for nm, buy, sell, qty in cur.fetchall():
                it = want.get(nm)
                if not it:
                    continue
                seen += 1
                bp += abs(float(buy) - it["buy_price"]) > 1e-6
                bs += abs(float(sell) - it["sell_price"]) > 1e-6
                bq += abs(float(qty) - it["stock"]) > 1e-6
            say("")
            say("=== NARX/QOLDIQ O'ZGARMAGANMI (Phase 1 rejasi bilan) ===")
            for lbl, v, exp in (("solishtirildi", seen, len(want)), ("kelish farqi", bp, 0),
                                ("sotish farqi", bs, 0), ("qoldiq farqi", bq, 0)):
                good = v == exp
                ok &= good
                say(f"  {'OK  ' if good else 'XATO'} | {lbl:24} {v}")

        say("")
        say("=== TEGILMASLIGI SHART BO'LGANLAR ===")
        cur.execute("SELECT count(*) FROM categories WHERE company_id=%s", (COMPANY,))
        say(f"  kategoriyalar : {cur.fetchone()[0]}  (0 bo'lishi kerak)")
        say("  454 tarozi · 214 takror nom guruhi · 9 zarar narxli · 20 kelishsiz")
        say("  -> ular hech qachon yaratilmagan, demak tegilmagan (mahsulot soni 7137)")

    say("")
    say(f"=== XULOSA: {'PHASE 2 TO`LIQ TOZA' if ok else 'FARQ BOR'} ===")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fayzan_verify_phase2.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
