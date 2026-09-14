# -*- coding: utf-8 -*-
"""PRODUCTION DEPLOY GATE 89f647a — REPORT PARITY: da47aa8 vs 89f647a on the SAME data.

Runs ONLY against a local database whose name starts with `acct_copy` — a TEMPLATE copy of the
restored production clone taken BEFORE the migration. The working directory decides which code
runs (the da47aa8 tree or the 89f647a tree).

  seed <state.json>             (da47aa8 tree) a synthetic UNTRACKED tenant: products with and
                                without a buy price, a purchase receipt, card and QR sales with
                                price overrides, and a restocked card return
  capture <state.json> <out>    GET every /api/v1/reports endpoint (period variants) as the
                                synthetic owner AND as the Fayzan owner, keeping the bodies
  compare <before> <after>      every numeric / string leaf present BEFORE must be identical AFTER at
                                the same path (lists of rows are matched by their id / name);
                                fields added by the new code are listed, never excused if changed
"""
import os
import sys
from urllib.parse import urlsplit

MODE = sys.argv[1] if len(sys.argv) > 1 else ""

if MODE in ("seed", "capture"):
    for cand in (os.getcwd(),):
        if os.path.isdir(os.path.join(cand, "app")):
            sys.path.insert(0, cand)
    _u = urlsplit(os.environ.get("DATABASE_URL", "").replace("+psycopg", ""))
    if _u.hostname not in ("localhost", "127.0.0.1") or not (_u.path or "/").lstrip("/").startswith("acct_copy"):
        print(f"REFUSED: host={_u.hostname!r} db={(_u.path or '').lstrip('/')!r}")
        sys.exit(3)

import json  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402

IGNORE = re.compile(r"(generated|timestamp|_at$|(^|\.)now$|server_time)", re.I)
ROW_KEYS = ("product_id", "id", "category_id", "category", "supplier_id", "customer_id", "name", "key", "bucket",
            "label", "date", "day", "hour", "month", "week", "method", "type", "code")


def _app():
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from app.core import deps
    from app.db.session import engine
    from app.main import app
    return TestClient, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session), deps, app


def _as(deps, app, MK, eid):
    from app.models.auth import Employee
    s = MK()
    e = s.get(Employee, uuid.UUID(str(eid)))
    _ = e.role.permissions
    s.close()
    app.dependency_overrides[deps.get_current_employee] = lambda: e


def seed(state_path):
    TestClient, MK, deps, app = _app()
    from app.models.auth import Employee, Role
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    from app.models.sales import Sale

    s = MK()
    ega = s.query(Role).filter(Role.code == "ega").one()
    code = "parity" + uuid.uuid4().hex[:8]
    co = Company(id=uuid.uuid4(), name="Report parity synthetic (deploy gate)", code=code, currency="UZS")
    s.add(co)
    s.flush()
    br = Branch(id=uuid.uuid4(), company_id=co.id, code="P01", name="PARITY", timezone="Asia/Tashkent", is_active=True)
    s.add(br)
    s.flush()
    em = Employee(id=uuid.uuid4(), company_id=co.id, full_name="Parity owner",
                  phone="+99891" + str(uuid.uuid4().int)[:7], role_id=ega.id)
    s.add(em)
    sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="Parity supplier")
    s.add(sup)
    s.commit()
    fz = s.query(Employee).join(Company, Company.id == Employee.company_id).join(Role, Role.id == Employee.role_id) \
        .filter(Company.code.in_(["fayzan1", "fayzan"]), Employee.deleted_at.is_(None)) \
        .order_by((Role.code == "ega").desc(), Employee.created_at).first()
    st = {"company_id": str(co.id), "code": code, "owner_id": str(em.id), "supplier_id": str(sup.id),
          "fayzan_owner_id": str(fz.id) if fz else None}
    s.close()

    _as(deps, app, MK, st["owner_id"])
    c = TestClient(app)
    r = c.post("/api/v1/products/bulk", json={"items": [
        {"name": "PARITY A", "sell_price": 100, "buy_price": 60, "unit_code": "dona", "stock": 50},
        {"name": "PARITY B", "sell_price": 250, "buy_price": 0, "unit_code": "dona", "stock": 20},
        {"name": "PARITY C", "sell_price": 40, "buy_price": 25, "unit_code": "dona", "stock": 0}]})
    assert r.status_code == 200, r.text
    pa, pb, pc = [x["id"] for x in r.json()]
    rr = c.post("/api/v1/receiving/commit", json={
        "items": [{"product_id": pc, "qty": 30, "unit_cost": 22, "unit": "dona"}],
        "supplier_id": st["supplier_id"], "payment": "credit", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert rr.status_code == 200, rr.text
    sales = [("card", [(pa, 3, 100), (pb, 1, 240)]), ("qr", [(pa, 2, 95), (pc, 5, 40)]),
             ("card", [(pb, 2, 250), (pc, 1, 40)])]
    cus = []
    for pm, lines in sales:
        cu = str(uuid.uuid4())
        total = sum(q * p for _, q, p in lines)
        body = {"sales": [{"client_uuid": cu, "payment_method": pm, "given_amount": total,
                           "items": [{"product_id": p, "qty": q, "unit_price": pr} for p, q, pr in lines]}]}
        r = c.post("/api/v1/sync/push", json=body)
        assert r.status_code == 200 and r.json()["results"][0]["ok"], r.text
        cus.append(cu)
    with MK() as x:
        sale1 = x.query(Sale).filter(Sale.company_id == co.id, Sale.client_uuid == uuid.UUID(cus[0])).one().id
    rt = c.post("/api/v1/returns", json={"original_sale_id": str(sale1), "reason": "customer", "restock": True,
                                         "refund_method": "card", "client_uuid": str(uuid.uuid4()),
                                         "items": [{"product_id": pa, "qty": 1, "unit_price": 100}]})
    assert rt.status_code == 200, rt.text
    st.update(sales=len(cus), products=[pa, pb, pc])
    json.dump(st, open(state_path, "w", encoding="utf-8"), indent=1)
    print("SEEDED", json.dumps({k: st[k] for k in ("code", "sales")}), "fayzan_owner:", bool(st["fayzan_owner_id"]))
    return 0


def capture(state_path, out_path):
    TestClient, MK, deps, app = _app()
    st = json.load(open(state_path, encoding="utf-8"))
    paths = sorted(p for p, ops in app.openapi().get("paths", {}).items()
                   if "get" in ops and p.startswith("/api/v1/reports") and "{" not in p)
    res = {"paths": paths, "tenants": {}}
    for label, eid in (("synthetic", st["owner_id"]), ("fayzan", st.get("fayzan_owner_id"))):
        if not eid:
            continue
        _as(deps, app, MK, eid)
        c = TestClient(app, raise_server_exceptions=False)
        bodies = {}
        for p in paths:
            for v in [p] + [f"{p}?period={x}" for x in ("day", "week", "month", "year", "all")]:
                r = c.get(v)
                try:
                    body = r.json()
                except Exception:  # noqa: BLE001
                    body = None
                bodies[v] = {"status": r.status_code, "body": body}
        res["tenants"][label] = bodies
    json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print("CAPTURED", len(paths), "report paths;", {k: len(v) for k, v in res["tenants"].items()}, "calls")
    return 0


def flatten(o, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            key = str(i)
            if isinstance(v, dict):
                rk = next((k for k in ROW_KEYS if k in v and isinstance(v[k], (str, int))), None)
                if rk is not None:
                    key = f"{rk}={v[rk]}"
            flatten(v, f"{prefix}[{key}]", out)
    else:
        out[prefix] = o
    return out


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 0.005
    return a == b


def compare(before_path, after_path):
    b = json.load(open(before_path, encoding="utf-8"))
    a = json.load(open(after_path, encoding="utf-8"))
    fails, added, compared, nonzero = [], {}, 0, 0
    for tenant, bodies in b["tenants"].items():
        ab = a["tenants"].get(tenant)
        if ab is None:
            fails.append({"tenant": tenant, "problem": "tenant missing after"})
            continue
        for url, rb in bodies.items():
            ra = ab.get(url)
            if ra is None:
                fails.append({"tenant": tenant, "url": url, "problem": "endpoint missing after"})
                continue
            if rb["status"] != ra["status"]:
                fails.append({"tenant": tenant, "url": url, "problem": "status", "before": rb["status"], "after": ra["status"]})
                continue
            lb, la = flatten(rb["body"]), flatten(ra["body"])
            for k, v in lb.items():
                if IGNORE.search(k):
                    continue
                if k not in la:
                    fails.append({"tenant": tenant, "url": url, "problem": "field removed", "field": k, "before": v})
                    continue
                compared += 1
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) > 0.005:
                    nonzero += 1
                if not same(v, la[k]):
                    fails.append({"tenant": tenant, "url": url, "field": k, "before": v, "after": la[k]})
            extra = sorted({re.sub(r"\[[^\]]*\]", "[]", k) for k in la if k not in lb})
            if extra:
                added.setdefault(tenant, {})[url] = extra[:30]
    syn = (b["tenants"].get("synthetic") or {}).get("/api/v1/reports/pnl?period=month", {}).get("body") or {}
    verdict = "PARITY" if not fails and compared > 0 and (syn.get("net") or 0) > 0 else "MISMATCH"
    new_fields = sorted({f for per in added.values() for fs in per.values() for f in fs})
    print(json.dumps({"verdict": verdict, "leaves_compared": compared, "nonzero_numbers_compared": nonzero,
                      "synthetic_pnl_month_before": {k: syn.get(k) for k in ("net", "cogs", "gross_profit")},
                      "tenants": sorted(b["tenants"]), "endpoints": len(b.get("paths") or []),
                      "failures": fails[:60], "failure_count": len(fails),
                      "fields_added_by_new_code": new_fields[:80]}, indent=1, ensure_ascii=False, default=str))
    return 0 if verdict == "PARITY" else 1


if __name__ == "__main__":
    if MODE == "seed":
        sys.exit(seed(sys.argv[2]))
    if MODE == "capture":
        sys.exit(capture(sys.argv[2], sys.argv[3]))
    if MODE == "compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    sys.exit(__doc__)
