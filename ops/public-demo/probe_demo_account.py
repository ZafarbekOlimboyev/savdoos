"""OMMAVIY DEMO HISOBI — server tomonidagi YOZUV TAQIQI va tenant izolyatsiyasi isboti.

python probe_demo_account.py --base http://127.0.0.1:8767 --phone +998000000000 --password ...
                             [--neighbour-phone ... --neighbour-password ...]

Har bir mutatsiya marshrutiga demo token bilan so'rov yuboriladi va **403** kutiladi
(401/404 ham o'tmaydi — darvoza ruxsat bo'yicha yopilishi SHART). O'qish marshrutlari
200 bo'lishi kerak. Qo'shni tenant resurslariga murojaat 403/404 bo'lishi kerak
(ma'lumot QAYTMASLIGI shart).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

import httpx

MUTATIONS = [
    ("POST", "/sales", {"items": [], "payments": []}, "kassa.sell"),
    ("POST", "/returns", {"sale_id": str(uuid.uuid4()), "items": []}, "qaytarishlar.create"),
    ("POST", "/cash/ops", {"type": "collection", "amount": 1, "reason": "probe",
                            "client_uuid": str(uuid.uuid4())}, "kassa.ops"),
    ("POST", "/shifts/open", {"opening_cash": 0}, "kassa.sell"),
    ("POST", "/inventory/writeoff", {"items": []}, "ombor.edit"),
    ("POST", "/inventory/count", {"items": []}, "ombor.edit"),
    ("POST", "/inventory/transfer", {"items": []}, "ombor.edit"),
    ("POST", "/purchases", {"supplier_id": str(uuid.uuid4()), "items": []}, "xaridlar.edit"),
    ("POST", "/products/bulk", [{"name": "probe", "sell_price": 1}], "mahsulotlar.edit"),
    ("POST", "/customers", {"full_name": "probe"}, "mijozlar.edit"),
    ("POST", "/suppliers", {"name": "probe"}, "xaridlar.edit"),
    ("POST", "/employees", {"full_name": "probe", "phone": "+998111111111"}, "xodimlar.edit"),
    ("PUT", "/settings", {"store_name": "probe"}, "sozlamalar.edit"),
    ("POST", "/shifts/{SID}/cash", {"type": "payin", "amount": 1}, "kassa.sell"),
    ("POST", "/shifts/{SID}/close", {"counted_cash": 0}, "kassa.sell"),
]
READS = ["/auth/context", "/sales/summary?period=today", "/reports/overview?period=week",
         "/reports/dashboard", "/products?limit=5", "/customers?limit=5", "/shifts/overview"]


def login(c: httpx.Client, phone: str, pw: str) -> str | None:
    r = c.post("/auth/login/password", json={"phone": phone, "password": pw})
    return r.json()["access_token"] if r.status_code == 200 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--phone", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--neighbour-phone"); ap.add_argument("--neighbour-password")
    a = ap.parse_args()
    base = a.base.rstrip("/") + "/api/v1"
    c = httpx.Client(base_url=base, timeout=60)
    out = {"mutations": [], "reads": [], "isolation": []}

    tok = login(c, a.phone, a.password)
    if not tok:
        print("FAIL: demo login ishlamadi"); return 1
    c.headers["Authorization"] = f"Bearer {tok}"
    ctx = c.get("/auth/context").json()
    print(f"DEMO login OK — do'kon={ctx['company']['code']} rol={ctx['employee']['role_code']} "
          f"full_access={ctx.get('full_access')}")
    print(f"ruxsatlar={sorted(ctx.get('permissions') or [])}")

    ok = True
    print("\n== MUTATSIYA MARSHRUTLARI (403 kutiladi)")
    sid = (c.get("/shifts/overview").json().get("shifts") or [{}])[0].get("id", str(uuid.uuid4()))
    for m, path, body, need in MUTATIONS:
        r = c.request(m, path.replace("{SID}", sid), json=body)
        good = r.status_code == 403
        ok &= good
        out["mutations"].append({"m": m, "path": path, "need": need, "code": r.status_code, "pass": good})
        print(f"  {'PASS' if good else 'FAIL'}  {m:5s} {path:24s} -> {r.status_code}  ({need})")

    print("\n== O'QISH MARSHRUTLARI (200 kutiladi)")
    for path in READS:
        r = c.get(path)
        good = r.status_code == 200
        ok &= good
        out["reads"].append({"path": path, "code": r.status_code, "pass": good})
        n = ""
        if good:
            try:
                j = r.json()
                n = f" n={len(j)}" if isinstance(j, list) else ""
            except Exception:
                pass
        print(f"  {'PASS' if good else 'FAIL'}  {path:34s} -> {r.status_code}{n}")

    if a.neighbour_phone:
        print("\n== TENANT IZOLYATSIYASI (qo'shni tenant resurslari)")
        n = httpx.Client(base_url=base, timeout=60)
        ntok = login(n, a.neighbour_phone, a.neighbour_password)
        if not ntok:
            print("  FAIL: qo'shni login ishlamadi"); return 1
        n.headers["Authorization"] = f"Bearer {ntok}"
        nctx = n.get("/auth/context").json()
        print(f"  qo'shni do'kon={nctx['company']['code']}")
        # qo'shni tenantning xodim ID'si bilan demo token orqali murojaat
        nid = nctx["employee"]["id"]
        for path in (f"/employees/{nid}", f"/customers/{nid}", f"/products/{nid}",
                     f"/sales/{nid}", f"/shifts/{nid}/summary"):
            r = c.get(path)
            good = r.status_code in (403, 404)
            ok &= good
            out["isolation"].append({"path": path, "code": r.status_code, "pass": good})
            print(f"  {'PASS' if good else 'FAIL'}  demo -> {path:30s} {r.status_code}")
        # qo'shni tenant o'z kontekstida demo do'konini ko'rmasligi
        r = n.get("/sales/summary?period=all")
        cnt = (r.json() or {}).get("count") if r.status_code == 200 else None
        good = cnt == 0
        ok &= good
        out["isolation"].append({"path": "neighbour /sales/summary?period=all", "count": cnt, "pass": good})
        print(f"  {'PASS' if good else 'FAIL'}  qo'shni ko'rgan chek soni = {cnt} (0 kutiladi)")

    print(f"\nNATIJA: {'PASS' if ok else 'FAIL'}")
    print(json.dumps({k: sum(1 for x in v if x['pass']) for k, v in out.items()}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
