# -*- coding: utf-8 -*-
"""MIJOZ #1 HOLATINI TEKSHIRISH — FAQAT O'QISH.

    python scripts/verify_merchant.py

⚠️  HECH NARSA YARATILMAYDI, O'ZGARTIRILMAYDI, O'CHIRILMAYDI. Faqat `GET`
    so'rovlari (yagona `POST` — vendor sessiyasini ochish va oxirida yopish).

⚠️  ATAYLAB MUVAFFAQIYATSIZ LOGIN QILINMAYDI — haqiqiy mijoz muhitida
    `auth_attempts` / audit qoldig'i qolmasin.

⚠️  OTP `getpass` bilan yashirin olinadi; `VENDOR_TOTP_SECRET` o'qilmaydi.
    Parol hash, PIN hash, token va sirlar CHOP ETILMAYDI.
"""
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

P = "https://savdoos-production.up.railway.app/api/v1"
PROJECT = "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
PROD_ENV = "1d0edbf9-652e-44ae-b4ca-ca58d6c8106f"
SERVICE = "4c0164e3-d24f-477d-a3c1-0a4c9283e218"

COMPANY_ID = "8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5"
CASHIER_ID = "64a2cb0d-85a9-45ca-9587-129dab9a0fab"

LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(P + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def vendor_key() -> str:
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vvars.gql")
    with open(q, "w", encoding="utf-8") as f:
        f.write("query($pid: String!, $eid: String!, $sid: String!) "
                "{ variables(projectId: $pid, environmentId: $eid, serviceId: $sid) }")
    try:
        raw = subprocess.run(["railway", "api", "-f", q,
                              "--var", f"pid={PROJECT}", "--var", f"eid={PROD_ENV}",
                              "--var", f"sid={SERVICE}"],
                             capture_output=True, text=True, timeout=120, shell=True).stdout
        return json.loads(raw)["data"]["variables"].get("VENDOR_ADMIN_KEY") or ""
    finally:
        try:
            os.remove(q)
        except OSError:
            pass


def main() -> int:
    key = vendor_key()
    if not key:
        print("XATO: vendor kaliti olinmadi (railway CLI kirgan bo'lsin).")
        return 1
    otp = getpass.getpass("PRODUCTION vendor OTP (yashirin): ").strip()
    if not (len(otp) == 6 and otp.isdigit()):
        print("XATO: OTP 6 raqam bo'lishi kerak.")
        return 1
    st, b = call("POST", "/admin/login", {"otp": otp}, {"X-Vendor-Key": key})
    if st != 200:
        print(f"XATO: vendor sessiyasi ochilmadi (HTTP {st}). OTP muddati o'tgan bo'lishi mumkin.")
        return 1
    H = {"X-Vendor-Session": json.loads(b)["session"]}
    otp = None

    # ── Do'konlar ro'yxati: har biri bo'yicha sanoqlar ──────────────────
    st, b = call("GET", "/admin/companies", None, H)
    comps = json.loads(b).get("companies", []) if st == 200 else []
    say(f"HTTP {st} | do'konlar: {len(comps)}")
    for c in comps:
        say(f"  id={c['id']}")
        say(f"  kod={c['code']} | nom={c['name']} | valyuta={c['currency']} | tarif={c['plan']}")
        say(f"  yaratildi={c['created_at']} | to'xtatilgan={c['suspended']}")
        say(f"  SANOQLAR -> filiallar={c['branches']} xodimlar={c['employees']} "
            f"mahsulotlar={c['products']} savdolar(tx)={c['tx']}")
        o = c.get("owner") or {}
        say(f"  egа: {o.get('name')}")

    # ── Do'kon tafsiloti: xodimlar ro'yxati ────────────────────────────
    st, b = call("GET", f"/admin/companies/{COMPANY_ID}", None, H)
    say()
    say(f"HTTP {st} | do'kon tafsiloti {COMPANY_ID}")
    if st == 200:
        d = json.loads(b)
        emps = d.get("employees", [])
        say(f"  XODIMLAR: {len(emps)} ta")
        for e in emps:
            say(f"    - {e.get('name')} | rol={e.get('role')} | holat={e.get('status')}")
        say(f"  filiallar={d.get('branches')} | so'nggi savdolar={len(d.get('recent_sales') or [])}")

    # ── Kassir aynan shu ID bilan bormi ────────────────────────────────
    say()
    say(f"kutilgan cashier_id = {CASHIER_ID}")
    say("(vendor ko'rinishida xodim ID'lari qaytarilmaydi — rol va holat bo'yicha solishtiring)")

    call("POST", "/admin/logout", None, H)
    say()
    say("vendor sessiyasi yopildi")

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_merchant.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nnatija:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
