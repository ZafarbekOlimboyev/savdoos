# -*- coding: utf-8 -*-
"""STAGING: provisioning parol siyosatini JONLI tekshirish.

Buni OPERATOR o'z terminalida yurgizadi:

    python scripts/staging_provision_check.py

⚠️  OTP kodi YASHIRIN kiritiladi (`getpass`) — u ekranga chiqmaydi, faylga ham,
    logga ham yozilmaydi. `VENDOR_TOTP_SECRET` bu skript tomonidan UMUMAN
    o'qilmaydi. Vendor kaliti Railway'dan shu jarayonning O'ZIDA olinadi va
    hech qayerga chop etilmaydi.

⚠️  Sinov uchun yaratilgan do'kon OXIRIDA O'CHIRILADI va o'chirilgani
    tekshiriladi. Natija `staging_provision_check.out` fayliga yoziladi —
    unda FAQAT tekshiruv nomlari va HTTP kodlari bo'ladi.
"""
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

S = "https://savdoos-staging.up.railway.app/api/v1"
PROJECT = "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
STAGING_ENV = "7eb2e84f-3c17-4dbb-b343-2b7a6df783fe"
SERVICE = "4c0164e3-d24f-477d-a3c1-0a4c9283e218"

OUT = []


def check(name, ok, detail=""):
    OUT.append((name, bool(ok), detail))
    print(("OK   | " if ok else "XATO | ") + name + (" | " + detail if detail else ""))


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(S + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def vendor_key() -> str:
    """Staging vendor kaliti — Railway'dan, CHOP ETILMAYDI."""
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vars.gql")
    with open(q, "w", encoding="utf-8") as f:
        f.write("query($pid: String!, $eid: String!, $sid: String!) "
                "{ variables(projectId: $pid, environmentId: $eid, serviceId: $sid) }")
    try:
        raw = subprocess.run(["railway", "api", "-f", q,
                              "--var", f"pid={PROJECT}", "--var", f"eid={STAGING_ENV}",
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
    check("staging ready 200", st == 200, f"HTTP {st}")

    key = vendor_key()
    if not key:
        print("XATO: staging vendor kaliti olinmadi (railway CLI kirgan bo'lsin).")
        return 1

    otp = getpass.getpass("Staging vendor OTP (6 raqam, ekranga chiqmaydi): ").strip()
    if not (len(otp) == 6 and otp.isdigit()):
        print("XATO: OTP 6 raqam bo'lishi kerak.")
        return 1

    st, b = call("POST", "/admin/login", {"otp": otp}, {"X-Vendor-Key": key})
    check("vendor sessiyasi ochildi (kalit + OTP + ruxsatli IP)", st == 200, f"HTTP {st}")
    if st != 200:
        print("   Sessiya ochilmadi — OTP muddati o'tgan bo'lishi mumkin, qayta urinib ko'ring.")
        return 1
    H = {"X-Vendor-Session": json.loads(b)["session"]}
    otp = None  # xotiradan chiqaramiz

    code = "pl" + uuid.uuid4().hex[:8]
    phone = f"+99893{uuid.uuid4().int % 10000000:07d}"

    def body(pw):
        return {"company_name": "Siyosat sinovi", "company_code": code,
                "owner_name": "Sinov Ega", "owner_phone": phone,
                "owner_password": pw, "plan": "start"}

    # ── A. Kuchsiz parol RAD ETILADI ────────────────────────────────────
    st, b = call("POST", "/admin/companies", body("qisqa1"), H)
    check("KUCHSIZ egа paroli rad etiladi", st == 400, f"HTTP {st}")
    check("rad etish sababi bor, parolning O'ZI yo'q",
          "Parol qabul qilinmadi" in b and "qisqa1" not in b)

    # ── B. Trivial parol RAD ETILADI ────────────────────────────────────
    st, b = call("POST", "/admin/companies", body("password12345"), H)
    check("TRIVIAL egа paroli rad etiladi", st == 400, f"HTTP {st}")

    # ── C. Rad etilgan so'rov QOLDIQ qoldirmaydi ────────────────────────
    st, b = call("GET", f"/admin/companies?q={code}", None, H)
    check("rad etilgan so'rovdan tenant QOLDIG'I yo'q", code not in b, f"HTTP {st}")

    # ── D. Kuchli parol ISHLAYDI ────────────────────────────────────────
    STRONG = "Staging-Kuchli-Parol-2026"
    st, b = call("POST", "/admin/companies", body(STRONG), H)
    check("KUCHLI parol bilan do'kon yaratildi", st == 200, f"HTTP {st}")
    cid = json.loads(b)["company_id"] if st == 200 else None

    if cid:
        st, _ = call("POST", "/auth/login/password", {"phone": phone, "password": STRONG})
        check("yangi egа kira oladi", st == 200, f"HTTP {st}")

        # ── E. TOZALASH ─────────────────────────────────────────────────
        st, b = call("DELETE", f"/admin/companies/{cid}", None, H)
        check("sinov do'koni o'chirildi", st in (200, 204), f"HTTP {st}")
        st, _ = call("POST", "/auth/login/password", {"phone": phone, "password": STRONG})
        check("o'chirilgandan keyin login YOPIQ", st != 200, f"HTTP {st}")

    call("POST", "/admin/logout", None, H)   # sessiyani bekor qilamiz

    bad = [n for n, ok, _ in OUT if not ok]
    res = "\n".join(f"{'OK  ' if ok else 'XATO'} | {n} | {d}" for n, ok, d in OUT)
    res += f"\n\n=== {len(OUT) - len(bad)} / {len(OUT)} ===\n"
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "staging_provision_check.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write(res)
    print(f"\n=== {len(OUT) - len(bad)} / {len(OUT)} ===")
    print("natija:", p)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
