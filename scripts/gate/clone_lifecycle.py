# -*- coding: utf-8 -*-
"""PRODUCTION DEPLOY GATE 89f647a — Phase 4A FUNCTIONAL LIFECYCLE on a COPY of the migrated clone.

Runs ONLY against a local database whose name starts with `lifecycle_` (a CREATE DATABASE ...
TEMPLATE copy of the migrated production clone), with APP_ENV=staging and the platform name
staging for THIS process only — lot activation is denied in production env, and the copy is
the isolated place where the real engine can be exercised on the production schema shape.

Creates ONE synthetic tenant, drives the real API in-process (TestClient + a dependency override
for the synthetic owner — no token is minted):

   1 tracked product            2 offline shortfall        3 partial resolution
   4 second partial other cost  5 variance check           6 P&L identities + report parity
   7 return interaction         8 idempotent replay        9 real-PG concurrency
  10 invariant                 11 cleanup (tenant purge, zero residue)

and proves that every Fayzan row on the copy is byte-identical before and after (row digests of
every Fayzan-scoped table) and that Fayzan's P&L is unchanged. Output: LIFECYCLE_JSON=...
"""
import os
import sys
from urllib.parse import urlsplit

for cand in (os.getcwd(), os.path.join(os.getcwd(), "apps", "server")):
    if os.path.isdir(os.path.join(cand, "app")):
        os.chdir(cand)
        sys.path.insert(0, cand)
        break

DB_URL = os.environ.get("DATABASE_URL", "")
_u = urlsplit(DB_URL.replace("+psycopg", ""))
APP_ENV = (os.getenv("APP_ENV") or "").strip().lower()
PLATFORM = (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "").strip().lower()
DBNAME = (_u.path or "/").lstrip("/")
if _u.hostname not in ("localhost", "127.0.0.1") or not DBNAME.startswith("lifecycle_") \
        or os.environ.get("GATE_LIFECYCLE_DB") != DBNAME or APP_ENV != "staging" or PLATFORM != "staging":
    print(f"REFUSED: host={_u.hostname!r} db={DBNAME!r} APP_ENV={APP_ENV!r} platform={PLATFORM!r}")
    sys.exit(3)

import json  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
import uuid  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core import deps  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import Employee, Role  # noqa: E402
from app.models.inventory import (LotShortfall, LotShortfallResolution,  # noqa: E402
                                  ReturnItemResolutionAllocation, StockBatch)
from app.models.org import Branch, Company  # noqa: E402
from app.models.purchasing import Supplier  # noqa: E402
from app.models.sales import Sale, SaleItem  # noqa: E402
from app.services import lot_resolution as LRes  # noqa: E402
from app.services import stock_invariant as SI  # noqa: E402

PG_URL = DB_URL.replace("postgresql+psycopg://", "postgresql://")
R = {"env": {"APP_ENV": APP_ENV, "platform": PLATFORM, "database": DBNAME}, "steps": []}
MK = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
CODE = "gate4a" + uuid.uuid4().hex[:8]
FAILED = []


def rec(step, ok, **detail):
    R["steps"].append({"step": step, "ok": bool(ok), **{k: (v if isinstance(v, (int, float, str, bool, type(None), list, dict)) else str(v)) for k, v in detail.items()}})
    if not ok:
        FAILED.append(step)
    print(f"[{'OK  ' if ok else 'FAIL'}] {step} {json.dumps(detail, default=str)[:400]}", flush=True)


def pnl(c, **p):
    return c.get("/api/v1/reports/pnl", params={"period": "month", **p}).json()


def identity(p):
    cogs = (p["cogs_known"] + p["cogs_estimated"] + p["cogs_unknown"]
            - p["cogs_returns_unlinked"] - p["cogs_returns_prior_period"] + p["cogs_variance"])
    return round(cogs, 2) == round(p["cogs"], 2) and round(p["net"] - p["cogs"], 2) == round(p["gross_profit"], 2)


def fayzan_snapshot():
    """Row digests of EVERY Fayzan-scoped table (company_id / tenant_id, and product-scoped tables)."""
    out = {}
    with psycopg.connect(PG_URL) as c:
        fid = c.execute("SELECT id FROM companies WHERE code IN ('fayzan1','fayzan') ORDER BY code DESC LIMIT 1").fetchone()
        if not fid:
            return None, {}
        fid = fid[0]
        base = {(s, t) for s, t in c.execute("SELECT table_schema, table_name FROM information_schema.tables "
                                             "WHERE table_schema IN ('public','cash') AND table_type = 'BASE TABLE'")}
        cols = {}
        for s, t, col in c.execute("SELECT table_schema, table_name, column_name FROM information_schema.columns "
                                   "WHERE table_schema IN ('public','cash') ORDER BY table_schema, table_name, ordinal_position"):
            if (s, t) in base:
                cols.setdefault((s, t), []).append(col)

        def digest(s, t, where, params):
            row_expr = sql.SQL("concat_ws(E'\\x1f', {})").format(sql.SQL(", ").join(
                sql.SQL("quote_nullable({}::text)").format(sql.Identifier(n)) for n in cols[(s, t)]))
            q = sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                        "FROM (SELECT md5({}) AS h FROM {}.{} WHERE " + where + ") x").format(
                            row_expr, sql.Identifier(s), sql.Identifier(t))
            r = c.execute(q, params).fetchone()
            return [r[0], r[1]]

        for (s, t), names in sorted(cols.items()):
            if t == "companies":
                out[f"{s}.{t}"] = digest(s, t, "id = %s", (fid,))
            elif "company_id" in names:
                out[f"{s}.{t}"] = digest(s, t, "company_id = %s", (fid,))
            elif "tenant_id" in names:
                out[f"{s}.{t}"] = digest(s, t, "tenant_id = %s", (fid,))
            elif "product_id" in names:
                out[f"{s}.{t}"] = digest(s, t, "product_id IN (SELECT id FROM public.products WHERE company_id = %s)", (fid,))
            elif "sale_id" in names:
                out[f"{s}.{t}"] = digest(s, t, "sale_id IN (SELECT id FROM public.sales WHERE company_id = %s)", (fid,))
            elif "branch_id" in names:
                out[f"{s}.{t}"] = digest(s, t, "branch_id IN (SELECT id FROM public.branches WHERE company_id = %s)", (fid,))
        c.rollback()
    return fid, out


def fayzan_pnl(fid):
    with MK() as x:
        emps = (x.query(Employee).join(Role, Role.id == Employee.role_id)
                .filter(Employee.company_id == fid, Employee.deleted_at.is_(None)).all())
        owner = next((e for e in emps if e.role.code == "ega"), emps[0] if emps else None)
        if owner is None:
            return None
        _ = owner.role.permissions
    app.dependency_overrides[deps.get_current_employee] = lambda: owner
    try:
        c = TestClient(app)
        return {"all": c.get("/api/v1/reports/pnl", params={"period": "all"}).json(),
                "summary_keys": sorted(c.get("/api/v1/reports/summary").json().keys())}
    finally:
        app.dependency_overrides.pop(deps.get_current_employee, None)


fid, fz_before = fayzan_snapshot()
fz_pnl_before = fayzan_pnl(fid) if fid else None
rec("0 Fayzan found on the copy; row digests of every Fayzan-scoped table captured",
    fid is not None and len(fz_before) > 10, tables=len(fz_before),
    products=(fz_before.get("public.products") or [None])[0])

cid = bid = eid = None
try:
    # ── 1. SYNTHETIC TENANT + TRACKED PRODUCT ────────────────────────────────
    s = MK()
    ega = s.query(Role).filter(Role.code == "ega").one()
    co = Company(id=uuid.uuid4(), name="Phase4A synthetic (clone gate)", code=CODE, currency="UZS")
    s.add(co)
    s.flush()
    br = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="G4A", timezone="Asia/Tashkent",
                is_active=True)
    s.add(br)
    s.flush()
    em = Employee(id=uuid.uuid4(), company_id=co.id, full_name="G4A owner",
                  phone="+99890" + str(uuid.uuid4().int)[:7], role_id=ega.id)
    s.add(em)
    sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="G4A supplier")
    s.add(sup)
    s.commit()
    cid, bid, eid, sup_id = co.id, br.id, em.id, sup.id
    emp = s.get(Employee, eid)
    _ = emp.role.permissions
    app.dependency_overrides[deps.get_current_employee] = lambda: emp
    c = TestClient(app)

    r = c.post("/api/v1/products/bulk", json={"items": [{"name": "G4A tovar", "sell_price": 100,
                                                          "buy_price": 50, "unit_code": "dona", "stock": 0}]})
    pid = r.json()[0]["id"]
    ready = c.get("/api/v1/health/ready").json()
    en = c.post("/api/v1/lots/enable", json={"product_id": pid, "reason": "phase4a clone gate",
                                             "track_expiry": False})
    rec("1 tracked product (enable passes the FK/CHECK integrity gate on the migrated production shape)",
        en.status_code == 200 and en.json()["track_lots"], enable_status=en.status_code,
        ready_checks=ready.get("checks"), company_code=CODE)

    # ── 2. OFFLINE SHORTFALL ─────────────────────────────────────────────────
    cu_sale = str(uuid.uuid4())
    body = {"sales": [{"client_uuid": cu_sale, "payment_method": "card", "given_amount": 1000,
                       "items": [{"product_id": pid, "qty": 10, "unit_price": 100}]}]}
    r = c.post("/api/v1/sync/push", json=body)
    with MK() as x:
        sale = x.query(Sale).filter(Sale.company_id == cid, Sale.client_uuid == uuid.UUID(cu_sale)).one()
        si = x.query(SaleItem).filter(SaleItem.sale_id == sale.id).one()
        sf = x.query(LotShortfall).filter(LotShortfall.company_id == cid).one()
        snap = (str(si.cost_total), str(si.cost_unresolved), str(si.provisional_qty), str(si.unit_cost))
    rec("2 offline shortfall 10 @50", r.json()["results"][0]["ok"] and D(str(sf.qty)) == 10
        and D(str(sf.unit_cost)) == 50 and snap[:3] == ("500.00", "500.00", "10.000"),
        sale_item=snap, shortfall_qty=str(sf.qty))
    sale_id, sf_id = sale.id, sf.id

    def receive(qty, cost, product=None):
        prod = product or pid
        rr = c.post("/api/v1/receiving/commit", json={
            "items": [{"product_id": prod, "qty": qty, "unit_cost": cost, "unit": "dona",
                       "lots": [{"qty": qty, "unit_cost": cost}]}],
            "supplier_id": str(sup_id), "payment": "credit", "client_uuid": str(uuid.uuid4()),
            "source": "manual"})
        assert rr.status_code == 200, rr.text
        with MK() as x:
            return x.query(StockBatch).filter(StockBatch.company_id == cid,
                                              StockBatch.product_id == uuid.UUID(prod),
                                              StockBatch.unit_cost == cost,
                                              StockBatch.remaining_qty > 0).order_by(StockBatch.created_at.desc()).first().id

    def resolve(batch, qty, cu):
        return c.post(f"/api/v1/lots/shortfalls/{sf_id}/resolve", json={
            "stock_batch_id": str(batch), "qty": qty, "reason": "phase4a clone gate", "client_uuid": cu})

    # ── 3. PARTIAL RESOLUTION ────────────────────────────────────────────────
    x_id = receive(5, 55)
    cu1 = str(uuid.uuid4())
    r1 = resolve(x_id, 5, cu1)
    j1 = r1.json()
    rec("3 partial resolution 5 @55 -> variance +25, open 5", r1.status_code == 200 and j1["variance_now"] == 25.0
        and j1["open_qty"] == 5.0 and j1["kinds"] == ["real"], status=r1.status_code,
        body={k: j1.get(k) for k in ("variance_now", "open_qty", "kinds")})

    # ── 4. SECOND PARTIAL AT A DIFFERENT COST ────────────────────────────────
    y_id = receive(3, 48)
    cu2 = str(uuid.uuid4())
    r2 = resolve(y_id, 3, cu2)
    j2 = r2.json()
    rec("4 second partial 3 @48 -> variance -6, open 2", r2.status_code == 200 and j2["variance_now"] == -6.0
        and j2["open_qty"] == 2.0 and j2["cogs_variance_net"] == 19.0,
        body={k: j2.get(k) for k in ("variance_now", "open_qty", "cogs_variance_net", "closed")})

    # ── 5. VARIANCE CHECK ────────────────────────────────────────────────────
    with MK() as x:
        ev = (x.query(LotShortfallResolution).filter(LotShortfallResolution.shortfall_id == sf_id)
              .order_by(LotShortfallResolution.resolved_at, LotShortfallResolution.line_no).all())
        evs = [(e.kind, str(e.qty), str(e.provisional_cost), str(e.actual_cost), str(e.variance)) for e in ev]
        si2 = x.get(SaleItem, si.id)
        snap2 = (str(si2.cost_total), str(si2.cost_unresolved), str(si2.provisional_qty), str(si2.unit_cost))
    lst = [z for z in c.get("/api/v1/lots/shortfalls").json()["shortfalls"] if z["id"] == str(sf_id)][0]
    rec("5 variance: events exact, open 2, exposure 100, SaleItem snapshot UNCHANGED",
        evs == [("real", "5.000", "250.00", "275.00", "25.00"), ("real", "3.000", "150.00", "144.00", "-6.00")]
        and lst["open_qty"] == 2.0 and lst["cogs_variance"] == 19.0 and lst["provisional_exposure"] == 100.0
        and snap2 == snap, events=evs, listed={k: lst[k] for k in ("open_qty", "cogs_variance", "provisional_exposure")},
        snapshot_before=snap, snapshot_after=snap2)

    # ── 6. P&L CHECK ─────────────────────────────────────────────────────────
    p6 = pnl(c)
    summ = c.get("/api/v1/reports/summary").json()
    dash = c.get("/api/v1/reports/dashboard").json()
    ov = c.get("/api/v1/reports/overview", params={"period": "month"}).json()
    rec("6 P&L: estimated 500 kept, variance 19 separate, cogs 519, identities hold; parity across reports",
        p6["cogs_estimated"] == 500.0 and p6["cogs_variance"] == 19.0 and p6["cogs"] == 519.0
        and identity(p6) and p6["profit_includes_cost_adjustment"] is True
        and summ["cogs_variance"] == 19.0 and dash["cogs_variance"] == 19.0 and ov["kpi"]["cogs_variance"] == 19.0
        and round(sum(b["cost"] for b in ov["series"]), 2) == 519.0,
        pnl={k: p6[k] for k in ("net", "cogs", "cogs_estimated", "cogs_known", "cogs_variance", "gross_profit", "gross_profit_basis")},
        summary_variance=summ["cogs_variance"], dashboard_variance=dash["cogs_variance"],
        overview_variance=ov["kpi"]["cogs_variance"])

    # ── 7. RETURN INTERACTION ────────────────────────────────────────────────
    cu_ret = str(uuid.uuid4())
    rr = c.post("/api/v1/returns", json={"original_sale_id": str(sale_id), "reason": "customer",
                                          "restock": True, "refund_method": "card", "client_uuid": cu_ret,
                                          "items": [{"product_id": pid, "qty": 4, "unit_price": 0}]})
    with MK() as x:
        rira = x.query(ReturnItemResolutionAllocation).filter(ReturnItemResolutionAllocation.company_id == cid).all()
        rira_v = [(str(z.qty), str(z.provisional_cost_credit), str(z.variance_reversed)) for z in rira]
        x_rem = str(x.get(StockBatch, x_id).remaining_qty)
    p7 = pnl(c)
    rec("7 return 4 after partial resolution: via event to X, credit 200 est, variance reversed 20",
        rr.status_code == 200 and rira_v == [("4.000", "200.00", "20.00")] and x_rem == "4.000"
        and p7["cogs_variance"] == -1.0 and p7["cogs_estimated"] == 300.0 and identity(p7),
        status=rr.status_code, rira=rira_v, x_remaining=x_rem,
        pnl={k: p7[k] for k in ("cogs", "cogs_estimated", "cogs_variance", "cogs_variance_resolutions",
                                "cogs_variance_return_reversals")})

    # ── 8. REPLAY ────────────────────────────────────────────────────────────
    d2 = resolve(y_id, 3, cu2).json()
    rep_sale = c.post("/api/v1/sync/push", json=body)
    rep_ret = c.post("/api/v1/returns", json={"original_sale_id": str(sale_id), "reason": "customer",
                                               "restock": True, "refund_method": "card", "client_uuid": cu_ret,
                                               "items": [{"product_id": pid, "qty": 4, "unit_price": 0}]})
    with MK() as x:
        n_ev = x.query(LotShortfallResolution).filter(LotShortfallResolution.company_id == cid).count()
        n_sale = x.query(Sale).filter(Sale.company_id == cid).count()
        n_rira = x.query(ReturnItemResolutionAllocation).filter(ReturnItemResolutionAllocation.company_id == cid).count()
    p8 = pnl(c)
    rec("8 replay: resolve duplicate, sale and return idempotent, P&L unchanged",
        d2.get("duplicate") is True and n_ev == 2 and n_sale == 1 and n_rira == 1
        and rep_ret.status_code == 200 and p8["cogs_variance"] == p7["cogs_variance"] and p8["cogs"] == p7["cogs"],
        duplicate=d2.get("duplicate"), events=n_ev, sales=n_sale, rira=n_rira,
        push_status=rep_sale.status_code)

    # ── 9. REAL POSTGRES CONCURRENCY ─────────────────────────────────────────
    z_id = receive(4, 60)

    def run_pair(fa, fb):
        barrier = threading.Barrier(2)
        out = {}

        def wrap(k, fn):
            sess = MK()
            try:
                barrier.wait(timeout=20)
                out[k] = fn(sess)
            except Exception as e:  # noqa: BLE001
                out[k] = e
            finally:
                sess.close()
        ts = [threading.Thread(target=wrap, args=("a", fa)), threading.Thread(target=wrap, args=("b", fb))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        return out["a"], out["b"]

    def rfn(lines, cu):
        return lambda sess: LRes.resolve(sess, sess.get(Employee, eid), sf_id, lines, reason="pg race", client_uuid=cu)

    a, b = run_pair(rfn([(z_id, 2)], uuid.uuid4()), rfn([(z_id, 2)], uuid.uuid4()))
    kinds = sorted(["ok" if isinstance(v, dict) else f"rad{getattr(v, 'status', type(v).__name__)}" for v in (a, b)])
    with MK() as x:
        resolved_after = str(x.get(LotShortfall, sf_id).resolved_qty)
    rec("9a concurrent resolve x resolve SAME shortfall (open 2, each asks 2): one ok, one 400, no over-resolution",
        kinds == ["ok", "rad400"] and resolved_after == "10.000", outcomes=kinds, resolved_qty=resolved_after)
    r = c.post("/api/v1/products/bulk", json={"items": [{"name": "G4A tovar 2", "sell_price": 100,
                                                          "buy_price": 50, "unit_code": "dona", "stock": 0}]})
    pid2 = r.json()[0]["id"]
    en2 = c.post("/api/v1/lots/enable", json={"product_id": pid2, "reason": "phase4a clone gate 2",
                                              "track_expiry": False})
    assert en2.status_code == 200, en2.text
    cu_sale2 = str(uuid.uuid4())
    c.post("/api/v1/sync/push", json={"sales": [{"client_uuid": cu_sale2, "payment_method": "card", "given_amount": 300,
                                                  "items": [{"product_id": pid2, "qty": 3, "unit_price": 100}]}]})
    with MK() as x:
        sf2_id = x.query(LotShortfall).filter(LotShortfall.product_id == uuid.UUID(pid2)).one().id
    w_id = receive(3, 52, pid2)
    same = uuid.uuid4()

    def rfn2(cu):
        return lambda sess: LRes.resolve(sess, sess.get(Employee, eid), sf2_id, [(w_id, 3)], reason="pg dup", client_uuid=cu)
    a, b = run_pair(rfn2(same), rfn2(same))
    dups = sorted([v.get("duplicate") if isinstance(v, dict) else repr(v) for v in (a, b)], key=str)
    with MK() as x:
        n2 = x.query(LotShortfallResolution).filter(LotShortfallResolution.shortfall_id == sf2_id).count()
    rec("9b concurrent SAME client_uuid: exactly one applied, one duplicate", dups == [False, True] and n2 == 1,
        outcomes=dups, events=n2)

    # ── 10. INVARIANT ────────────────────────────────────────────────────────
    with MK() as x:
        rep = SI.check(x, cid, [uuid.UUID(pid), uuid.UUID(pid2)])
        neg = x.execute(text("SELECT count(*) FROM stock_batches WHERE company_id=:c AND remaining_qty < 0"), {"c": cid}).scalar()
        over = x.execute(text("SELECT count(*) FROM lot_shortfalls WHERE company_id=:c AND resolved_qty > qty"), {"c": cid}).scalar()
        rev_over = x.execute(text(
            "SELECT count(*) FROM lot_shortfall_resolutions e WHERE e.company_id=:c AND e.qty < "
            "(SELECT coalesce(sum(r.qty),0) FROM return_item_resolution_allocations r WHERE r.resolution_id=e.id)"),
            {"c": cid}).scalar()
        var_id = x.execute(text("SELECT count(*) FROM lot_shortfall_resolutions WHERE company_id=:c AND "
                                "variance <> actual_cost - provisional_cost"), {"c": cid}).scalar()
    rec("10 invariant + no negative lot + no over-resolution + reversal caps + variance identity",
        rep.ok and neg == 0 and over == 0 and rev_over == 0 and var_id == 0,
        mismatches=[str(m) for m in rep.mismatches], negative=neg, over=over, reversal_over=rev_over)
    c.close()
    s.close()
except Exception as e:  # noqa: BLE001
    rec("LIFECYCLE aborted", False, error=repr(e), tb=traceback.format_exc()[-1500:])
finally:
    app.dependency_overrides.pop(deps.get_current_employee, None)
    # ── 11. CLEANUP ──────────────────────────────────────────────────────────
    if cid is not None:
        try:
            engine.dispose()
            from app.tools import tenant_purge as TP
            rc = TP.main(["--company-code", CODE, "--execute", "--confirm-company-code", CODE,
                          "--i-know-this-is-not-a-real-merchant", "--json"])
            with MK() as x:
                left = {"companies": x.execute(text("SELECT count(*) FROM companies WHERE id=:c"), {"c": cid}).scalar()}
                for t in ("products", "sales", "returns", "stock_batches", "lot_shortfalls",
                          "lot_shortfall_resolution_requests", "lot_shortfall_resolutions",
                          "return_item_shortfall_allocations", "return_item_resolution_allocations"):
                    left[t] = x.execute(text(f"SELECT count(*) FROM {t} WHERE company_id=:c"), {"c": cid}).scalar()
            rec("11 cleanup: tenant purge exit 0, zero residue", rc == 0 and not any(left.values()),
                purge_rc=rc, residue=left)
        except BaseException as e:  # noqa: BLE001 — SystemExit from the CLI included
            rec("11 cleanup", False, error=repr(e))

try:
    fid2, fz_after = fayzan_snapshot()
    diff = sorted(k for k in set(fz_before) | set(fz_after) if fz_before.get(k) != fz_after.get(k))
    rec("12 Fayzan untouched by the whole lifecycle: every Fayzan-scoped table digest identical",
        fid2 == fid and not diff and len(fz_after) == len(fz_before), changed=diff, tables=len(fz_after))
    fz_pnl_after = fayzan_pnl(fid)
    rec("12 Fayzan P&L (period=all) identical before and after", fz_pnl_before is not None
        and fz_pnl_before == fz_pnl_after, before=fz_pnl_before and fz_pnl_before.get("all"),
        after=fz_pnl_after and fz_pnl_after.get("all"))
except Exception as e:  # noqa: BLE001
    rec("12 Fayzan invariance", False, error=repr(e), tb=traceback.format_exc()[-1200:])

R["verdict"] = "PASS" if not FAILED else "FAIL"
R["failed"] = FAILED
print("LIFECYCLE_JSON=" + json.dumps(R, default=str))
sys.exit(0 if not FAILED else 1)
