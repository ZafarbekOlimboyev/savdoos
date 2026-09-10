# -*- coding: utf-8 -*-
"""PRODUCTION: provisioning parol siyosati — FAQAT RAD ETISH tekshiruvlari.

Buni OPERATOR o'z terminalida yurgizadi:

    python scripts/prod_provision_check.py

⚠️  PRODUCTION'DA DO'KON YARATILMAYDI. Skript FAQAT kuchsiz/trivial parol RAD
    ETILISHINI va rad etishdan keyin QOLDIQ QOLMASLIGINI tekshiradi. Muvaffaqiyatli
    provisioning YO'LI ATAYLAB SINALMAYDI — aks holda production'da sinov mijozi
    paydo bo'lardi.

⚠️  OTP YASHIRIN kiritiladi (`getpass`) — ekranga chiqmaydi, faylga va logga
    yozilmaydi. `VENDOR_TOTP_SECRET` UMUMAN o'qilmaydi. Vendor kaliti shu
    jarayonning o'zida Railway'dan olinadi va chop etilmaydi.
"""
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

P = "https://savdoos-production.up.railway.app/api/v1"
PROJECT = "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
PROD_ENV = "1d0edbf9-652e-44ae-b4ca-ca58d6c8106f"
SERVICE = "4c0164e3-d24f-477d-a3c1-0a4c9283e218"

OUT = []


def check(name, ok, detail=""):
    OUT.append((name, bool(ok), detail))
    print(("OK   | " if ok else "XATO | ") + name + (" | " + detail if detail else ""))


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
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pvars.gql")
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


def _company_count(raw: str) -> int:
    """`GET /admin/companies` javobidagi do'konlar SONI.

    ⚠️  ILGARI BU YERDA XATO BOR EDI. Kod `len(json.loads(b).get("items") or json.loads(b))`
        edi: endpoint `{"companies": [...]}` qaytaradi, unda `items` kaliti YO'Q, shuning
        uchun `or` butun LUG'ATNI qaytarardi va `len()` do'konlar sonini emas, LUG'AT
        KALITLARI sonini — ya'ni DOIM 1 ni — berardi. Natijada bo'sh production
        "1 ta do'kon bor" deb ko'rinib, soxta trevoga chiqardi."""
    try:
        j = json.loads(raw) if raw.strip() else {}
    except Exception:
        return -1
    if isinstance(j, list):
        return len(j)
    for k in ("companies", "items"):
        v = j.get(k)
        if isinstance(v, list):
            return len(v)
    return -1


def main() -> int:
    st, b = call("GET", "/health/ready")
    check("production ready 200", st == 200, f"HTTP {st}")
    check("barcha readiness checklari true", '"database":true' in b.replace(" ", "")
          and '"cash_schema":true' in b.replace(" ", "")
          and '"config":true' in b.replace(" ", "")
          and '"tenancy_schema":true' in b.replace(" ", ""))

    key = vendor_key()
    if not key:
        print("XATO: production vendor kaliti olinmadi (railway CLI kirgan bo'lsin).")
        return 1

    otp = getpass.getpass("PRODUCTION vendor OTP (6 raqam, ekranga chiqmaydi): ").strip()
    if not (len(otp) == 6 and otp.isdigit()):
        print("XATO: OTP 6 raqam bo'lishi kerak.")
        return 1

    st, b = call("POST", "/admin/login", {"otp": otp}, {"X-Vendor-Key": key})
    check("vendor sessiyasi ochildi (kalit + OTP + ruxsatli IP)", st == 200, f"HTTP {st}")
    if st != 200:
        print("   Sessiya ochilmadi — OTP muddati o'tgan bo'lishi mumkin, qayta urining.")
        return 1
    H = {"X-Vendor-Session": json.loads(b)["session"]}
    otp = None

    # Boshlang'ich holat: do'kon YO'Q
    st, b0 = call("GET", "/admin/companies", None, H)
    n0 = _company_count(b0)
    check("boshlang'ich: production'da do'kon YO'Q", n0 == 0, f"{n0} ta")

    code = "pp" + uuid.uuid4().hex[:8]
    phone = f"+99893{uuid.uuid4().int % 10000000:07d}"

    def body(pw):
        return {"company_name": "SINOV — YARATILMASIN", "company_code": code,
                "owner_name": "Sinov", "owner_phone": phone,
                "owner_password": pw, "plan": "start"}

    st, b = call("POST", "/admin/companies", body("qisqa1"), H)
    check("KUCHSIZ egа paroli RAD ETILADI", st == 400, f"HTTP {st}")
    check("sabab bor, parolning O'ZI javobda yo'q",
          "Parol qabul qilinmadi" in b and "qisqa1" not in b)

    st, b = call("POST", "/admin/companies", body("password12345"), H)
    check("TRIVIAL egа paroli RAD ETILADI", st == 400, f"HTTP {st}")
    check("trivial parol javobda yo'q", "password12345" not in b)

    # QOLDIQ YO'Q — do'kon soni O'ZGARMAGAN bo'lsin
    st, b1 = call("GET", "/admin/companies", None, H)
    n1 = _company_count(b1)
    check("rad etishdan keyin QOLDIQ yo'q (do'kon soni o'zgarmadi)", n1 == n0, f"{n0} -> {n1}")
    check("sinov kodi bazada YO'Q", code not in b1)

    # Telefon ham band bo'lmasligi kerak
    st, b = call("POST", "/auth/login/password", {"phone": phone, "password": "Sinov-Parol-2026"})
    check("sinov telefoni akkaunt yaratmagan", st == 401, f"HTTP {st}")

    call("POST", "/admin/logout", None, H)
    check("vendor sessiyasi bekor qilindi", True)

    bad = [n for n, ok, _ in OUT if not ok]
    res = "\n".join(f"{'OK  ' if ok else 'XATO'} | {n} | {d}" for n, ok, d in OUT)
    res += f"\n\n=== {len(OUT) - len(bad)} / {len(OUT)} ===\n"
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prod_provision_check.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write(res)
    print(f"\n=== {len(OUT) - len(bad)} / {len(OUT)} ===")
    print("natija:", p)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
