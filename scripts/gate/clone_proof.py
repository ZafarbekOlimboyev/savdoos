# -*- coding: utf-8 -*-
"""GATE — PRODUCTION-CLONE PROOF. Runs ONLY in the ephemeral GitHub runner.

Target: postgres:18 container restored from the PRE-DEPLOY production backup artifact and
migrated by the TARGET code. Never production (the URL must be local).

    python scripts/gate/clone_proof.py prod-mode    # server: APP_ENV=production + RAILWAY_ENVIRONMENT_NAME=production
    python scripts/gate/clone_proof.py functional   # server: APP_ENV=staging (lot activation allowed ONLY here)

All synthetic data is created in NEW tenants inside the clone. The Fayzan copy is only READ
(GET report endpoints) and its fingerprint is re-checked after the functional run.
"""
import base64
import concurrent.futures as cf
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg

BASE = os.environ.get("GATE_BASE", "http://127.0.0.1:8000") + "/api/v1"
DB = os.environ["CLONE_DATABASE_URL"]
if "@localhost" not in DB and "@127.0.0.1" not in DB:
    raise SystemExit("REFUSED: clone database must be local")
VKEY = os.environ["VENDOR_ADMIN_KEY"]
VTOTP = os.environ["VENDOR_TOTP_SECRET"]
TARGET = os.environ["TARGET_SHA"]
OUT = os.environ.get("GATE_OUT", "gate-out")
ROOT = os.getcwd()
STEPS = []
D10 = (date.today() + timedelta(days=10)).isoformat()
D20 = (date.today() + timedelta(days=20)).isoformat()
C2 = Decimal("0.01")


def rec(name, ok, note=""):
    STEPS.append({"step": name, "ok": bool(ok), "note": str(note)[:300]})
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {note}" if note != "" else ""), flush=True)
    return bool(ok)


def call(method, path, body=None, token=None, headers=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, (json.loads(raw) if raw else {})
            except json.JSONDecodeError:
                return r.status, {"_non_json_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}


def q(sql, params=(), one=False):
    with psycopg.connect(DB, connect_timeout=30) as c, c.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        c.rollback()
    if one:
        return rows[0] if rows else None
    return rows


def totp(secret):
    s = secret.strip().upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def vendor_session():
    st, r = call("POST", "/admin/login", {"otp": totp(VTOTP)}, headers={"X-Vendor-Key": VKEY})
    if st != 200:
        raise SystemExit(f"vendor login failed: HTTP {st} {r}")
    return r["session"]


def new_tenant(vs, tag):
    code = tag + uuid.uuid4().hex[:8]
    phone = "+99890" + str(uuid.uuid4().int)[:7]
    pw = "G!" + uuid.uuid4().hex[:14] + "Aa9"
    st, r = call("POST", "/admin/companies", {
        "company_name": f"Gate {tag}", "company_code": code, "owner_name": "Gate owner",
        "owner_phone": phone, "owner_password": pw, "plan": "business",
        "timezone": "Asia/Tashkent"}, headers={"X-Vendor-Session": vs})
    if st not in (200, 201):
        raise SystemExit(f"tenant provisioning failed: HTTP {st} {r}")
    cid = r.get("company_id") or r.get("id")
    st, lr = call("POST", "/auth/login/password", {"phone": phone, "password": pw})
    if st != 200:
        raise SystemExit(f"owner login failed: HTTP {st} {lr}")
    return str(cid), lr["access_token"], code


def fayzan_fingerprint():
    return q("""
      SELECT (SELECT count(*) FROM products p JOIN companies c ON c.id=p.company_id WHERE c.code='fayzan1'),
             (SELECT md5(coalesce(string_agg(p.id::text||p.updated_at::text||coalesce(p.name,''), '' ORDER BY p.id),''))
                FROM products p JOIN companies c ON c.id=p.company_id WHERE c.code='fayzan1'),
             (SELECT coalesce(sum(i.qty),0)::text FROM inventory i JOIN products p ON p.id=i.product_id
                JOIN companies c ON c.id=p.company_id WHERE c.code='fayzan1'),
             (SELECT count(*) FROM stock_movements m JOIN products p ON p.id=m.product_id
                JOIN companies c ON c.id=p.company_id WHERE c.code='fayzan1'),
             (SELECT count(*) FROM sales s JOIN companies c ON c.id=s.company_id WHERE c.code='fayzan1'),
             (SELECT count(*) FROM returns r JOIN companies c ON c.id=r.company_id WHERE c.code='fayzan1'),
             (SELECT count(*) FROM product_barcodes b JOIN companies c ON c.id=b.company_id WHERE c.code='fayzan1')
    """, one=True)


# ══ PROD-MODE ════════════════════════════════════════════════════════════════
def prod_mode():
    print("── PROD-MODE server: APP_ENV=production, RAILWAY_ENVIRONMENT_NAME=production ──")
    st, h = call("GET", "/health")
    rec("P1 GET /health = 200", st == 200, f"HTTP {st}")
    b = (h or {}).get("build") or {}
    rec("P2 build.commit == target SHA (runner-injected platform var; plumbing only)", b.get("commit") == TARGET, b.get("commit"))
    rec("P3 build.environment=production AND platform_environment=production",
        b.get("environment") == "production" and b.get("platform_environment") == "production", json.dumps(b))
    st, rd = call("GET", "/health/ready")
    checks = (rd or {}).get("checks") or {}
    rec("P4 GET /health/ready = 200, all checks true (catalog_v2_schema = required_schema)",
        st == 200 and bool(checks) and all(checks.values()), json.dumps(checks))
    blob = (json.dumps(h) + json.dumps(rd)).lower()
    leaks = [w for w in ("postgres", "rehearsal", "localhost", "5432", "password", "traceback",
                         "select ", "psycopg", "railway.internal", "sqlalchemy") if w in blob]
    rec("P5 health payloads expose no DB host/user/password/SQL/driver/proxy text", not leaks, str(leaks))

    vs = vendor_session()
    cid, T, code = new_tenant(vs, "gp")
    rec("P6 synthetic tenant provisioned INSIDE THE CLONE", bool(cid), code)
    st, r = call("POST", "/products/bulk", {"items": [{"name": "Gate-P", "sell_price": 100, "buy_price": 60,
                                                        "unit_code": "dona", "stock": 0}]}, token=T)
    pid = r[0]["id"]
    call("POST", "/lots/timezone/confirm", {}, token=T)
    for label, body in (("track_expiry=true", {"product_id": pid, "reason": "gate", "track_expiry": True}),
                        ("track_expiry=false", {"product_id": pid, "reason": "gate", "track_expiry": False}),
                        ("unknown product id", {"product_id": str(uuid.uuid4()), "reason": "gate"})):
        st, r = call("POST", "/lots/enable", body, token=T)
        rec(f"P7 POST /lots/enable ({label}) = 403", st == 403, f"HTTP {st} {str(r.get('detail'))[:100]}")
    row = q("SELECT coalesce(track_lots,false), coalesce(track_expiry,false), lots_activated_at "
            "FROM products WHERE id=%s", (pid,), one=True)
    rec("P8 product flags unchanged after refused activation", tuple(row) == (False, False, None), str(row))
    g = q("SELECT (SELECT count(*) FROM products WHERE track_lots), (SELECT count(*) FROM products WHERE track_expiry), "
          "(SELECT count(*) FROM stock_batches), (SELECT count(*) FROM sale_item_lot_allocations), "
          "(SELECT count(*) FROM lot_shortfalls), (SELECT count(*) FROM return_item_lot_allocations), "
          "(SELECT count(*) FROM stock_movement_lot_allocations)", one=True)
    rec("P9 whole clone: 0 tracked, 0 expiry-tracked, all 5 lot tables = 0", all(v == 0 for v in g), str(g))

    # ── Fayzan copy: every GET report/lot/inventory/sales endpoint, READ ONLY ──
    sys.path.insert(0, os.path.join(ROOT, "apps", "server"))
    from app.core.security import create_access_token
    from app.main import app as fastapi_app
    emp = q("SELECT e.id::text, e.company_id::text, r.code, coalesce(e.sec_epoch,0) FROM employees e "
            "JOIN roles r ON r.id=e.role_id JOIN companies c ON c.id=e.company_id "
            "WHERE c.code='fayzan1' AND e.deleted_at IS NULL AND e.status::text='active' "
            "ORDER BY (r.code='ega') DESC, e.created_at LIMIT 1", one=True)
    rec("P10 Fayzan copy present in clone with an active owner", emp is not None, str(emp and emp[2]))
    if emp is None:
        return
    FT = create_access_token(emp[0], {"role": emp[2], "company_id": emp[1], "sv": int(emp[3])})
    before = fayzan_fingerprint()
    prefixes = ("/api/v1/reports", "/api/v1/lots", "/api/v1/inventory", "/api/v1/sales", "/api/v1/returns",
                "/api/v1/shifts", "/api/v1/purchases", "/api/v1/receiving", "/api/v1/products", "/api/v1/dashboard")
    # FastAPI 0.14x keeps included routers LAZILY (`_IncludedRouter`): `app.routes` does not list
    # them. The OpenAPI document is the complete, flattened route table.
    paths = sorted(p for p, ops in fastapi_app.openapi().get("paths", {}).items()
                   if "get" in ops and p.startswith(prefixes) and "{" not in p)
    rec("P10b GET endpoints enumerated (a vacuous smoke is a failed smoke)", len(paths) >= 15, str(len(paths)))
    results, fivexx = [], []
    for p in paths:
        variants = [p]
        if p.startswith("/api/v1/reports"):
            variants += [p + "?period=day", p + "?period=week", p + "?period=month", p + "?period=year"]
        for v in variants:
            t0 = time.time()
            st, body = call("GET", v[len("/api/v1"):], token=FT, timeout=300)
            ms = int((time.time() - t0) * 1000)
            results.append({"path": v, "status": st, "ms": ms})
            if st >= 500:
                fivexx.append(v)
    slow = sorted(results, key=lambda x: -x["ms"])[:5]
    print("    Fayzan GET smoke:", len(results), "calls;", "slowest:", slow)
    rec(f"P11 Fayzan copy: {len(results)} GET calls over {len(paths)} endpoints, ZERO 5xx", not fivexx, str(fivexx))
    rec("P12 P&L response carries the new accounting keys (serialization)",
        all(k in call("GET", "/reports/pnl?period=month", token=FT)[1]
            for k in ("revenue_known_cost", "revenue_mixed_cost", "revenue_estimated_cost", "revenue_cost_unknown",
                      "cogs_known", "cogs_estimated", "cogs_unknown", "gross_profit_known", "gross_profit_basis")), "")
    rec("P13 Fayzan copy fingerprint unchanged by GET smoke", fayzan_fingerprint() == before, str(before))
    with open(os.path.join(OUT, "fayzan_get_smoke.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)


# ══ FUNCTIONAL ═══════════════════════════════════════════════════════════════
def functional():  # noqa: C901
    print("── FUNCTIONAL server: APP_ENV=staging on the clone ──")
    fz_before = fayzan_fingerprint()
    vs = vendor_session()
    cid, T, code = new_tenant(vs, "gf")
    rec("F0 synthetic tenant provisioned INSIDE THE CLONE", bool(cid), code)
    st, br = call("GET", "/branches", token=T)
    branch_id = (br.get("branches") if isinstance(br, dict) else br)[0]["id"]
    st, till = call("POST", "/tills", {"branch_id": branch_id, "code": "K1", "label": "Kassa 1"}, token=T)
    till_id = str(till.get("id"))
    rec("F0 till created", st in (200, 201) and till.get("id"), f"HTTP {st}")
    st, sup = call("GET", "/suppliers", token=T)
    sup_id = (sup[0]["id"] if isinstance(sup, list) and sup else
              call("POST", "/suppliers", {"name": "Gate supplier"}, token=T)[1]["id"])
    st, sh = call("POST", "/shifts/open", {"opening_cash": 100000000, "till_id": till_id}, token=T)
    rec("F0 shift opened on the till", st in (200, 201), f"HTTP {st}")

    def product(name, buy, sell=100):
        _s, _r = call("POST", "/products/bulk", {"items": [
            {"name": name, "sell_price": sell, "buy_price": buy, "unit_code": "dona", "stock": 0}]}, token=T)
        return _r[0]["id"]

    def recv_plain(pid, qty, cost):
        return call("POST", "/receiving/commit", {
            "items": [{"product_id": pid, "qty": qty, "unit_cost": cost, "unit": "dona"}],
            "supplier_id": sup_id, "payment": "credit", "client_uuid": str(uuid.uuid4()), "source": "manual"}, token=T)

    def recv_lot(pid, qty, cost, exp, nm="L"):
        return call("POST", "/receiving/commit", {
            "items": [{"product_id": pid, "qty": qty, "unit_cost": cost, "unit": "dona",
                       "lots": [{"qty": qty, "unit_cost": cost, "expiry_date": exp, "batch_number": nm}]}],
            "supplier_id": sup_id, "payment": "credit", "client_uuid": str(uuid.uuid4()), "source": "manual"}, token=T)

    def sell(pid, qty, price=100, method="cash", payments=None, given=None):
        body = {"items": [{"product_id": pid, "qty": qty, "unit_price": price}],
                "payment_method": method, "till_id": till_id, "client_uuid": str(uuid.uuid4())}
        if payments:
            body["payments"] = payments
        if given is not None:
            body["given_amount"] = given
        elif method == "cash" and not payments:
            body["given_amount"] = 100000000
        return call("POST", "/sales", body, token=T)

    def ret(sale_id, pid, qty, restock=True, method="cash"):
        return call("POST", "/returns", {
            "original_sale_id": sale_id, "reason": "customer", "restock": restock, "refund_method": method,
            "client_uuid": str(uuid.uuid4()), "items": [{"product_id": pid, "qty": qty, "unit_price": 0}]}, token=T)

    def legs(src, sid):
        return [tuple(x) for x in q(
            "SELECT direction::text, amount::text, cash_account_id::text FROM cash.cash_ledger_entries "
            "WHERE tenant_id=%s AND source_type::text=%s AND source_id=%s ORDER BY leg_index",
            (cid, src, sid))]

    def si_cost(sale_id, pid):
        r = q("SELECT cost_total, coalesce(cost_unresolved,0) FROM sale_items WHERE sale_id=%s AND product_id=%s",
              (sale_id, pid), one=True)
        return (float(r[0]), float(r[1])) if r else (None, None)

    def lots_of(pid):
        return [(s, float(qq), float(u)) for s, qq, u in q(
            "SELECT source_type, remaining_qty, unit_cost FROM stock_batches WHERE product_id=%s ORDER BY created_at", (pid,))]

    def pnl():
        return call("GET", "/reports/pnl?period=month", token=T)[1]

    def snap(name):
        g = lambda u: call("GET", u, token=T)[1]        # noqa: E731
        p = g("/reports/pnl?period=month")
        ov = g("/reports/overview?period=month")
        det = g("/reports/detail?period=month")
        tp = g("/reports/top-products?period=month&limit=100")

        def named(rows, k="profit"):
            for x in (rows or []):
                if x.get("name") == name:
                    return float(x.get(k) or 0)
            return 0.0
        return {"pnl.net": p["net"], "pnl.cogs": p["cogs"], "pnl.gross_profit": p["gross_profit"],
                "summary": g("/reports/summary")["today_profit"], "dashboard": g("/reports/dashboard")["today_profit"],
                "overview": ov["kpi"]["profit"], "top": named(tp), "detail": named(det.get("abc"))}

    def d(a, b):
        return {k: round(b[k] - a[k], 2) for k in a}

    # ── A + B + J + E: untracked cash sale, exact ledger IN leg, exact COGS, cash refund OUT leg ──
    print("\n── A/B/J/E untracked cash sale -> ledger IN -> exact COGS -> cash refund -> ledger OUT ──")
    pa = product("A-Milk", 60)
    rec("A1 receiving 10 @60 (untracked product)", recv_plain(pa, 10, 60)[0] == 200)
    s0 = snap("A-Milk")
    st, sa = sell(pa, 1)
    rec("A2 untracked cash sale = 200", st == 200, f"HTTP {st} {str(sa)[:120]}")
    rec("A3 product stays untracked; zero lot rows for it",
        q("SELECT coalesce(track_lots,false) FROM products WHERE id=%s", (pa,), one=True)[0] is False
        and q("SELECT count(*) FROM stock_batches WHERE product_id=%s", (pa,), one=True)[0] == 0)
    lg = legs("SALE", sa["id"])
    rec("B1 cash sale -> exactly ONE ledger leg", len(lg) == 1, str(lg))
    rec("B2 leg: IN, amount 100.00, posted to the sale's till",
        len(lg) == 1 and lg[0][0] == "IN" and Decimal(lg[0][1]) == Decimal("100.00") and lg[0][2] == till_id, str(lg))
    ct, cu = si_cost(sa["id"], pa)
    rec("J1 exact COGS untracked: cost_total 60.00, cost_unresolved 0", (ct, cu) == (60.0, 0.0), f"{ct}/{cu}")
    s1 = snap("A-Milk")
    rec("J2 sale profit +40 on P&L", d(s0, s1)["pnl.gross_profit"] == 40.0, str(d(s0, s1)["pnl.gross_profit"]))
    st, ra = ret(sa["id"], pa, 1)
    rec("E1 cash refund (restock) = 200", st == 200, f"HTTP {st} {str(ra)[:120]}")
    lg = legs("RETURN", ra["id"])
    rec("E2 cash refund -> exactly ONE leg: OUT, amount == refund total, same till",
        len(lg) == 1 and lg[0][0] == "OUT" and Decimal(lg[0][1]) == Decimal(str(ra["total"])).quantize(C2)
        and lg[0][2] == till_id, f"{lg} total={ra.get('total')}")
    s2 = snap("A-Milk")
    da = d(s1, s2)
    rec("E3 refund deltas: revenue -100, COGS -60, profit -40",
        (da["pnl.net"], da["pnl.cogs"], da["pnl.gross_profit"]) == (-100.0, -60.0, -40.0), str(da))
    for k in ("summary", "dashboard", "overview", "top", "detail"):
        rec(f"E4 {k} delta -40", da[k] == -40.0, str(da[k]))
    ja = d(s0, s2)
    rec("E5 net after full restock return: revenue 0 / COGS 0 / profit 0",
        (ja["pnl.net"], ja["pnl.cogs"], ja["pnl.gross_profit"]) == (0.0, 0.0, 0.0), str(ja))

    # ── C + F: card/QR sale and refund never touch the physical cash ledger ──
    print("\n── C/F card and QR: no physical cash leg ──")
    pc = product("C-Card", 60)
    recv_plain(pc, 10, 60)
    for m in ("card", "qr"):
        st, sx = sell(pc, 1, method=m)
        rec(f"C1 {m} sale = 200", st == 200, f"HTTP {st} {str(sx)[:120]}")
        rec(f"C2 {m} sale -> ZERO ledger legs", st == 200 and legs("SALE", sx["id"]) == [], str(st == 200 and legs("SALE", sx["id"])))
        st, rx = ret(sx["id"], pc, 1, method=m)
        rec(f"F1 {m} refund = 200", st == 200, f"HTTP {st} {str(rx)[:120]}")
        rec(f"F2 {m} refund -> ZERO ledger legs", st == 200 and legs("RETURN", rx["id"]) == [], str(st == 200 and legs("RETURN", rx["id"])))

    # ── D: mixed payment posts the cash portion only ──
    print("\n── D mixed payment: cash portion only ──")
    pm = product("D-Mix", 60)
    recv_plain(pm, 10, 60)
    split = [{"method": "cash", "amount": 60}, {"method": "card", "amount": 40}]
    st, sm = sell(pm, 1, payments=split)
    if st != 200:
        st, sm = sell(pm, 1, payments=split, given=60)
    rec("D1 mixed cash 60 + card 40 sale = 200", st == 200, f"HTTP {st} {str(sm)[:160]}")
    lg = legs("SALE", sm["id"]) if st == 200 else []
    rec("D2 mixed -> exactly ONE leg: IN 60.00 (cash portion only)",
        len(lg) == 1 and lg[0][0] == "IN" and Decimal(lg[0][1]) == Decimal("60.00"), str(lg))

    # ── K: damaged return (restock=False) does not restore COGS ──
    print("\n── K damaged return ──")
    pk = product("K-Bread", 60)
    recv_plain(pk, 10, 60)
    t0 = snap("K-Bread")
    st, sk = sell(pk, 1)
    t1 = snap("K-Bread")
    st, rk = ret(sk["id"], pk, 1, restock=False)
    rec("K1 damaged return = 200", st == 200, f"HTTP {st}")
    t2 = snap("K-Bread")
    dk = d(t1, t2)
    rec("K2 deltas: revenue -100, COGS 0 (not restored), profit -100",
        (dk["pnl.net"], dk["pnl.cogs"], dk["pnl.gross_profit"]) == (-100.0, 0.0, -100.0), str(dk))
    jk = d(t0, t2)
    rec("K3 net: revenue 0 / COGS 60 / result -60",
        (jk["pnl.net"], jk["pnl.cogs"], jk["pnl.gross_profit"]) == (0.0, 60.0, -60.0), str(jk))
    lg = legs("RETURN", rk["id"])
    rec("K4 damaged cash refund still posts exactly ONE OUT leg of 100.00",
        len(lg) == 1 and lg[0][0] == "OUT" and Decimal(lg[0][1]) == Decimal("100.00"), str(lg))

    # ── J (tracked): exact FEFO COGS from two document-priced lots ──
    print("\n── J tracked exact COGS (FEFO over two document-priced lots) ──")
    pj = product("J-Tracked", 50)
    call("POST", "/lots/timezone/confirm", {}, token=T)
    st, _ = call("POST", "/lots/enable", {"product_id": pj, "reason": "gate", "track_expiry": True}, token=T)
    rec("J3 lot tracking enabled (staging-mode clone server only)", st == 200, f"HTTP {st}")
    recv_lot(pj, 1, 90, D10, "J90")
    recv_lot(pj, 1, 50, D20, "J50")
    j0 = pnl()
    st, sj = sell(pj, 2)
    rec("J4 tracked sale of 2 = 200", st == 200, f"HTTP {st}")
    ct, cu = si_cost(sj["id"], pj)
    rec("J5 exact tracked COGS: cost_total 140.00, cost_unresolved 0", (ct, cu) == (140.0, 0.0), f"{ct}/{cu}")
    j1 = pnl()
    rec("J6 cogs_known +140, cogs_estimated +0",
        round(j1["cogs_known"] - j0["cogs_known"], 2) == 140.0 and round(j1["cogs_estimated"] - j0["cogs_estimated"], 2) == 0.0,
        f"{round(j1['cogs_known'] - j0['cogs_known'], 2)}/{round(j1['cogs_estimated'] - j0['cogs_estimated'], 2)}")

    # ── N (part): return_unattributed resale is ESTIMATED, not exact ──
    print("\n── N/C return_unattributed resale ──")
    pn = product("N-Oil", 50)
    call("POST", "/lots/enable", {"product_id": pn, "reason": "gate", "track_expiry": True}, token=T)
    cu1 = str(uuid.uuid4())
    st, rp = call("POST", "/sync/push", {"sales": [{"client_uuid": cu1, "payment_method": "cash", "given_amount": 9999999,
                                                    "items": [{"product_id": pn, "qty": 2, "unit_price": 100}]}]}, token=T)
    rec("N1 offline sale with no lots accepted (2 = shortfall)",
        st == 200 and (rp.get("results") or [{}])[0].get("ok") is True, f"HTTP {st}")
    off = q("SELECT id::text FROM sales WHERE client_uuid=%s", (cu1,), one=True)[0]
    st, _ = ret(off, pn, 2)
    rec("N2 customer returned the 2 units", st == 200, f"HTTP {st}")
    pl = [x for x in lots_of(pn) if x[0] == "return_unattributed"]
    rec("N3 return_unattributed lot 2 @50 exists", len(pl) == 1 and pl[0][1] == 2.0 and pl[0][2] == 50.0, str(pl))
    recv_lot(pn, 2, 90, D20, "N90")
    st, sfs = call("GET", "/lots/shortfalls", token=T)
    sf = [x for x in (sfs.get("items") or sfs.get("shortfalls") or []) if str(x.get("product_id")) == str(pn)]
    b90 = q("SELECT id::text FROM stock_batches WHERE product_id=%s AND unit_cost=90", (pn,), one=True)[0]
    st, _ = call("POST", f"/lots/shortfalls/{sf[0]['id']}/resolve",
                 {"stock_batch_id": b90, "qty": 2, "reason": "found"}, token=T)
    rec("N4 shortfall resolved", st == 200, f"HTTP {st}")
    c0 = pnl()
    st, sc = sell(pn, 2)
    ct, cu = si_cost(sc["id"], pn)
    rec("N5 resale of estimated lot: cost_total 100, cost_unresolved 100", (ct, cu) == (100.0, 100.0), f"{ct}/{cu}")
    c1 = pnl()
    rec("N6 cogs_estimated +100, cogs_known +0",
        round(c1["cogs_estimated"] - c0["cogs_estimated"], 2) == 100.0 and round(c1["cogs_known"] - c0["cogs_known"], 2) == 0.0,
        f"{round(c1['cogs_estimated'] - c0['cogs_estimated'], 2)}/{round(c1['cogs_known'] - c0['cogs_known'], 2)}")

    # ── M: mixed known 90 + estimated 50 ──
    print("\n── M mixed known 90 + estimated 50 ──")
    pmx = product("M-Rice", 50)
    call("POST", "/lots/enable", {"product_id": pmx, "reason": "gate", "track_expiry": True}, token=T)
    cu2 = str(uuid.uuid4())
    call("POST", "/sync/push", {"sales": [{"client_uuid": cu2, "payment_method": "cash", "given_amount": 9999999,
                                           "items": [{"product_id": pmx, "qty": 1, "unit_price": 100}]}]}, token=T)
    off2 = q("SELECT id::text FROM sales WHERE client_uuid=%s", (cu2,), one=True)[0]
    ret(off2, pmx, 1)
    rec("M1 one estimated unit (return_unattributed) created",
        any(x[0] == "return_unattributed" and x[1] == 1.0 for x in lots_of(pmx)))
    recv_lot(pmx, 1, 90, D20, "M90")
    st, sfs = call("GET", "/lots/shortfalls", token=T)
    sfm = [x for x in (sfs.get("items") or sfs.get("shortfalls") or []) if str(x.get("product_id")) == str(pmx)]
    bm = q("SELECT id::text FROM stock_batches WHERE product_id=%s AND unit_cost=90 AND remaining_qty>0", (pmx,), one=True)[0]
    call("POST", f"/lots/shortfalls/{sfm[0]['id']}/resolve", {"stock_batch_id": bm, "qty": 1, "reason": "found"}, token=T)
    recv_lot(pmx, 1, 90, D10, "M90b")
    m0 = pnl()
    st, smx = sell(pmx, 2)
    rec("M2 2 units sold (1 estimated + 1 document-priced)", st == 200, f"HTTP {st}")
    ct, cu = si_cost(smx["id"], pmx)
    rec("M3 row cost_total 140, cost_unresolved 50", (ct, cu) == (140.0, 50.0), f"{ct}/{cu}")
    m1 = pnl()
    mk, me = round(m1["cogs_known"] - m0["cogs_known"], 2), round(m1["cogs_estimated"] - m0["cogs_estimated"], 2)
    rec("M4 cogs_known +90", mk == 90.0, str(mk))
    rec("M5 cogs_estimated +50", me == 50.0, str(me))
    rec("M6 known + estimated = 140 (no double count)", mk + me == 140.0, str(mk + me))

    # ── L: history seed unknown / estimated ──
    print("\n── L history unknown / estimated ──")
    e0 = pnl()
    st, _ = call("POST", "/reports/history/seed", {"rows": [
        {"no": uuid.uuid4().hex[:8], "date": date.today().strftime("%d.%m.%Y") + " 10:00:00", "revenue": 500000}]}, token=T)
    rec("L1 unknown-basis history row written", st == 200, f"HTTP {st}")
    e1 = pnl()
    rec("L2 revenue_cost_unknown +500000",
        round(e1["revenue_cost_unknown"] - e0["revenue_cost_unknown"], 2) == 500000.0,
        str(round(e1["revenue_cost_unknown"] - e0["revenue_cost_unknown"], 2)))
    rec("L3 cogs_known +0 and revenue_known_cost +0 (no fabricated cost)",
        round(e1["cogs_known"] - e0["cogs_known"], 2) == 0.0 and round(e1["revenue_known_cost"] - e0["revenue_known_cost"], 2) == 0.0)
    rec("L4 gross_profit_basis = partial_unknown", e1.get("gross_profit_basis") == "partial_unknown", e1.get("gross_profit_basis"))
    f0 = pnl()
    st, _ = call("POST", "/reports/history/seed", {
        "rows": [{"no": uuid.uuid4().hex[:8], "date": date.today().strftime("%d.%m.%Y") + " 11:00:00", "revenue": 400000}],
        "cost_ratio": 0.75, "cost_basis": "estimated"}, token=T)
    rec("L5 estimated-basis history row written", st == 200, f"HTTP {st}")
    f1 = pnl()
    rec("L6 revenue_estimated_cost +400000, cogs_estimated +300000, cogs_known +0",
        round(f1["revenue_estimated_cost"] - f0["revenue_estimated_cost"], 2) == 400000.0
        and round(f1["cogs_estimated"] - f0["cogs_estimated"], 2) == 300000.0
        and round(f1["cogs_known"] - f0["cogs_known"], 2) == 0.0)

    # ── G / H / I: document numbering under concurrency ──
    print("\n── G/H/I numbering under concurrency ──")
    pg = product("G-Conc", 10, sell=20)
    recv_plain(pg, 200, 10)
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda _i: sell(pg, 1, price=20), range(12)))
    codes = [s for s, _r in res]
    rec("G1 12 concurrent cash sales all = 200", codes.count(200) == 12, str(codes))
    ok_sales = [r for s, r in res if s == 200]
    nums = sorted(int(re.fullmatch(r"#(\d+)", r["receipt_no"]).group(1)) for r in ok_sales)
    rec("G2 concurrent receipts unique and contiguous", nums == list(range(nums[0], nums[0] + len(nums))), str(nums))
    rec("G3 each concurrent cash sale has exactly ONE IN leg of 20.00",
        all(legs("SALE", r["id"]) and len(legs("SALE", r["id"])) == 1 and Decimal(legs("SALE", r["id"])[0][1]) == Decimal("20.00")
            for r in ok_sales))
    with cf.ThreadPoolExecutor(4) as ex:
        rr = list(ex.map(lambda r: ret(r["id"], pg, 1), ok_sales[:4]))
    rec("H1 4 concurrent returns all = 200", [s for s, _ in rr].count(200) == 4, str([s for s, _ in rr]))
    with cf.ThreadPoolExecutor(4) as ex:
        pr = list(ex.map(lambda _i: recv_plain(pg, 5, 10), range(4)))
    rec("I1 4 concurrent receivings all = 200", [s for s, _ in pr].count(200) == 4, str([s for s, _ in pr]))

    all_r = sorted(int(x[0][1:]) for x in q("SELECT receipt_no FROM sales WHERE company_id=%s AND receipt_no LIKE '#%%'", (cid,)))
    rec("G4 ALL tenant receipts gapless from #1288", all_r == list(range(1288, 1288 + len(all_r))),
        f"n={len(all_r)} first={all_r[:2]} last={all_r[-2:]}")
    rec("G5 no leftover TMP receipt numbers", q("SELECT count(*) FROM sales WHERE company_id=%s AND receipt_no LIKE 'TMP%%'", (cid,), one=True)[0] == 0)
    all_q = sorted(int(x[0][4:]) for x in q("SELECT return_no FROM returns WHERE company_id=%s", (cid,)))
    rec("H2 ALL tenant return numbers unique and gapless from QAY-1001", all_q == list(range(1001, 1001 + len(all_q))),
        f"n={len(all_q)} first={all_q[:2]} last={all_q[-2:]}")
    all_k = sorted(int(x[0][4:]) for x in q("SELECT doc_no FROM purchases WHERE company_id=%s", (cid,)))
    rec("I2 ALL tenant purchase/receiving numbers unique and gapless from KIR-1043",
        all_k == list(range(1043, 1043 + len(all_k))), f"n={len(all_k)} first={all_k[:2]} last={all_k[-2:]}")

    # ── N: report identities ──
    print("\n── N report identities ──")
    p = pnl()
    rev = (p["revenue_known_cost"] + p["revenue_mixed_cost"] + p["revenue_estimated_cost"] + p["revenue_cost_unknown"]
           - p["returns_unlinked"] - p["returns_prior_period"])
    rec(f"N7 revenue identity ({round(rev, 2)} == {round(p['net'], 2)})", round(rev, 2) == round(p["net"], 2))
    cg = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"] - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"])
    rec(f"N8 COGS identity ({round(cg, 2)} == {round(p['cogs'], 2)})", round(cg, 2) == round(p["cogs"], 2))
    rec("N9 gross_profit_known = revenue_known_cost - cogs_of_known_revenue",
        round(p["gross_profit_known"], 2) == round(p["revenue_known_cost"] - p["cogs_of_known_revenue"], 2))
    for ep in ("/reports/summary", "/reports/dashboard"):
        _s, _r = call("GET", ep, token=T)
        rec(f"N10 {ep} declares profit_basis", "profit_basis" in _r and "revenue_cost_unknown" in _r, str(list(_r)[:6]))
    _s, _ov = call("GET", "/reports/overview?period=month", token=T)
    rec("N11 overview.kpi declares profit_basis", "profit_basis" in (_ov.get("kpi") or {}), str((_ov.get("kpi") or {}).get("profit_basis")))

    # ── lot invariant on every tracked product ──
    for tp in (pj, pn, pmx):
        _s, _r = call("GET", f"/lots/products/{tp}", token=T)
        qty = float(_r.get("inventory_qty") or 0)
        ls = sum(float(x["remaining_qty"]) for x in _r.get("lots", []))
        debt = float(_r.get("unresolved_shortfall_qty") or 0)
        rec(f"N12 invariant qty == lots - open debt ({qty} == {ls} - {debt})", abs(qty - (ls - debt)) < 1e-6)

    rec("Z1 Fayzan copy untouched by all functional operations (tenant isolation)",
        fayzan_fingerprint() == fz_before, str(fz_before))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    os.makedirs(OUT, exist_ok=True)
    try:
        if mode == "prod-mode":
            prod_mode()
        elif mode == "functional":
            functional()
        else:
            raise SystemExit("mode: prod-mode | functional")
    except Exception as e:  # noqa: BLE001 — a crash is a FAILED proof, recorded explicitly
        import traceback
        traceback.print_exc()
        rec(f"CRASH {type(e).__name__}", False, str(e)[:200])
    with open(os.path.join(OUT, f"clone_{mode}.json"), "w", encoding="utf-8") as f:
        json.dump(STEPS, f, indent=1, ensure_ascii=False)
    bad = [s for s in STEPS if not s["ok"]]
    print(f"\nCLONE PROOF [{mode}]: {len(STEPS) - len(bad)}/{len(STEPS)} OK")
    for s in bad:
        print("  FAILED:", s["step"], "—", s["note"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
