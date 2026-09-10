# -*- coding: utf-8 -*-
"""BIRINCHI REAL MIJOZ — production onboarding (single-branch).

Buni OPERATOR o'z terminalida yurgizadi:

    python scripts/onboard_merchant.py

⚠️  BARCHA SIRLAR YASHIRIN. Egа paroli, kassir PIN'i va vendor OTP `getpass`
    orqali olinadi: ekranga chiqmaydi, natija fayliga ham, logga ham yozilmaydi.
    `VENDOR_TOTP_SECRET` UMUMAN o'qilmaydi.

⚠️  BIRINCHI XATODA TO'XTAYDI. Har invariant tekshiriladi; biror tekshiruv
    yiqilsa skript DARHOL to'xtaydi va dalilni `onboard_merchant.out` ga yozadi.
    Zaxira nusxa allaqachon olingan — tiklash mumkin.

⚠️  `owner_pin` BERILMAYDI: egа PIN bilan kira olmaydi (imtiyozli identifikator
    PIN yo'lidan to'siladi), ya'ni o'rnatilgan PIN o'lik kredensial bo'lardi.

⚠️  HECH QANDAY MOLIYAVIY AMAL QILINMAYDI. Sinov mahsuloti, sinov savdosi,
    smena ochish/yopish, naqd harakati va rekonsiliatsiya ATAYLAB YO'Q.
    CashLedger O'ZGARMAS: onboarding paytida yozilgan sun'iy yozuv mijozning
    DOIMIY moliyaviy tarixiga kirib qolardi va uni keyin tozalab bo'lmasdi.
    Birinchi moliyaviy hodisa do'kon HAQIQATAN ishlay boshlaganda yoziladi.

    Skript yaratadigan YAGONA narsalar: bitta do'kon (+ birinchi filial), bitta
    fizik TILL (kassa ta'rifi — ledger yozuvi EMAS) va bitta kassir. Qolgani
    faqat o'qish va sessiya ochish/yopish.
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

OUT = []
FACTS = {}


class Stop(Exception):
    pass


def check(name, ok, detail=""):
    OUT.append((name, bool(ok), str(detail)))
    print(("OK   | " if ok else "XATO | ") + name + (" | " + str(detail) if detail else ""))
    if not ok:
        raise Stop(name)


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(P + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def vendor_key() -> str:
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ovars.gql")
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


def policy_problem(pw: str):
    """Kanonik siyosat — TARMOQQA CHIQMASDAN, mahalliy tekshiruv."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apps", "server")
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("DATABASE_URL", "sqlite:///./_policy_check.db")
    os.environ.setdefault("SECRET_KEY", "x" * 64)
    from app.core.password_policy import password_policy_problem
    return password_policy_problem(pw)


def _list_len(st: int, raw: str, *keys) -> int:
    """HTTP javobidagi RO'YXAT uzunligi. Xato bo'lsa -1 (hech qachon "1" emas).

    ⚠️  IKKI MARTA TISHLAGAN XATO. Ilgari kod to'g'ridan-to'g'ri
        `len(json.loads(b))` qilardi. Agar javob RO'YXAT bo'lmasa — masalan
        `{"companies": [...]}` o'ramasi yoki `{"detail": "..."}` XATOSI — `len()`
        LUG'AT KALITLARINI sanardi va DOIM 1 chiqardi. Natijada:
          • bo'sh production "1 ta do'kon bor" deb ko'rindi;
          • 401 javobi "1 ta xodim bor" deb ko'rindi.
        Endi status ham tekshiriladi va o'ram kalitlari aniq ko'rsatiladi."""
    if st != 200:
        return -1
    try:
        j = json.loads(raw) if raw.strip() else []
    except Exception:
        return -1
    if isinstance(j, list):
        return len(j)
    for k in keys:
        if isinstance(j.get(k), list):
            return len(j[k])
    return -1


def _company_count(raw: str) -> int:
    try:
        j = json.loads(raw) if raw.strip() else {}
    except Exception:
        return -1
    if isinstance(j, list):
        return len(j)
    for k in ("companies", "items"):
        if isinstance(j.get(k), list):
            return len(j[k])
    return -1


def main() -> int:
    print("=" * 62)
    print("  BIRINCHI REAL MIJOZ — PRODUCTION ONBOARDING (single-branch)")
    print("=" * 62)

    # ── 1. Tayyorlik ────────────────────────────────────────────────────
    st, b = call("GET", "/health/ready")
    check("production ready 200", st == 200, f"HTTP {st}")
    flat = b.replace(" ", "")
    check("barcha readiness checklari true",
          all(f'"{k}":true' in flat for k in ("database", "cash_schema", "config", "tenancy_schema")))

    # ── 2. Mijoz ma'lumotlari ───────────────────────────────────────────
    print("\n--- Mijoz ma'lumotlari ---")
    company_name = input("  Do'kon nomi                : ").strip()
    company_code = input("  Do'kon kodi (harf+raqam)   : ").strip().lower()
    owner_name = input("  Egа to'liq ismi            : ").strip()
    owner_phone = input("  Egа telefoni (+996...)     : ").strip()
    branch_name = input("  Filial nomi                : ").strip()
    plan = (input("  Tarif [start]              : ").strip() or "start").lower()
    currency = (input("  Valyuta [KGS]              : ").strip() or "KGS").upper()
    tz = (input("  Vaqt mintaqasi [Asia/Bishkek]: ").strip() or "Asia/Bishkek")

    check("do'kon kodi faqat harf va raqam", company_code.isalnum() and 2 <= len(company_code) <= 40,
          company_code)
    check("majburiy maydonlar to'ldirilgan",
          all([company_name, owner_name, owner_phone, branch_name]))

    # ── 3. Egа paroli — YASHIRIN + kanonik siyosat ─────────────────────
    print("\n--- Egа paroli (ekranga chiqmaydi) ---")
    pw = getpass.getpass("  Parol                      : ")
    pw2 = getpass.getpass("  Parolni takrorlang         : ")
    check("parollar mos keldi", pw == pw2)
    problem = policy_problem(pw)
    check("parol kanonik siyosatdan o'tdi (TARMOQQA CHIQMASDAN)", problem is None, problem or "")

    print(f"\n  -> {company_name} / {company_code} / {plan} / {currency} / {tz}")
    print(f"  -> filial: {branch_name} | egа: {owner_name} {owner_phone}")
    if input("\n  Production'da YARATILSINMI? (ha/yo'q): ").strip().lower() not in ("ha", "yes", "y"):
        print("  Bekor qilindi — hech narsa yaratilmadi.")
        return 1

    # ── 4. Vendor sessiyasi ─────────────────────────────────────────────
    key = vendor_key()
    check("vendor kaliti olindi", bool(key))
    otp = getpass.getpass("\n  PRODUCTION vendor OTP (yashirin): ").strip()
    check("OTP 6 raqam", len(otp) == 6 and otp.isdigit())
    st, b = call("POST", "/admin/login", {"otp": otp}, {"X-Vendor-Key": key})
    check("vendor sessiyasi ochildi", st == 200, f"HTTP {st}")
    VH = {"X-Vendor-Session": json.loads(b)["session"]}
    otp = None

    st, b0 = call("GET", "/admin/companies", None, VH)
    n0 = _company_count(b0)
    check("onboardingdan OLDIN do'kon soni 0", n0 == 0, f"{n0} ta")
    check("bu kod hali band emas", company_code not in b0)

    # ── 5. PROVISIONING — bitta do'kon, bitta filial ───────────────────
    print("\n--- Provisioning ---")
    st, b = call("POST", "/admin/companies", {
        "company_name": company_name, "company_code": company_code,
        "owner_name": owner_name, "owner_phone": owner_phone,
        "owner_password": pw, "plan": plan, "currency": currency,
        "branch_name": branch_name, "timezone": tz,
    }, VH)
    check("do'kon yaratildi", st == 200, f"HTTP {st} {b[:160]}")
    cid = json.loads(b)["company_id"]
    FACTS["company_id"] = cid
    FACTS["company_code"] = company_code
    print(f"  company_id = {cid}")

    st, b1 = call("GET", "/admin/companies", None, VH)
    check("endi AYNAN 1 ta do'kon", _company_count(b1) == 1, f"{_company_count(b1)} ta")

    # ── 6. Egа kirishi + tenant invariantlari ──────────────────────────
    st, b = call("POST", "/auth/login/password", {"phone": owner_phone, "password": pw})
    check("egа parol bilan kira oldi", st == 200, f"HTTP {st}")
    lg = json.loads(b)
    OH = {"Authorization": f"Bearer {lg['access_token']}"}
    pw = pw2 = None
    check("egа roli 'ega'", lg["employee"]["role_code"] == "ega", lg["employee"]["role_code"])
    check("login javobida do'kon kodi qaytdi", lg["employee"].get("company_code") == company_code)
    FACTS["owner_id"] = lg["employee"]["id"]

    st, b = call("GET", "/branches", None, OH)
    brs = json.loads(b).get("branches", [])
    check("AYNAN 1 ta faol filial", len(brs) == 1, f"{len(brs)} ta")
    FACTS["branch_id"] = brs[0]["id"]
    FACTS["branch_name"] = brs[0]["name"]

    st, b = call("GET", "/settings", None, OH)
    S = json.loads(b)
    cash = S.get("cash") or {}
    check("ledger_native = true", cash.get("ledger_native") is True, cash.get("ledger_native"))
    check("onboarded_at mavjud", bool(cash.get("onboarded_at")), cash.get("onboarded_at"))
    check("cutover_at mavjud", bool(cash.get("cutover_at")), cash.get("cutover_at"))
    FACTS["onboarded_at"] = cash.get("onboarded_at")
    FACTS["cutover_at"] = cash.get("cutover_at")
    check("tarif to'g'ri", (S.get("plan") or {}).get("plan") == plan, (S.get("plan") or {}).get("plan"))

    # ⚠️  `payments` SETTING'i FRESH tenantda ATAYLAB YO'Q: provisioning to'lov
    #     usullarini `payment_methods` JADVALIGA yozadi (cash/card/qr/credit, hammasi
    #     yoqilgan) va server ham AYNAN o'sha jadvaldan o'qiydi. Setting faqat UI
    #     toggle'i yozganda paydo bo'ladi. Shu bois bu yerda "bo'sh bo'lsa ham mayli"
    #     deb o'tkazib yubormaymiz — aynan YO'QLIGINI talab qilamiz, aks holda
    #     tekshiruv hech narsani tekshirmagan bo'lardi.
    check("`payments` Setting'i fresh tenantda YO'Q (kutilgan holat)",
          S.get("payments") is None, str(S.get("payments"))[:60])

    st, b = call("GET", "/employees", None, OH)
    emps = json.loads(b)
    check("AYNAN 1 ta xodim (egа)", len(emps) == 1, f"{len(emps)} ta")

    # ── 7. Birinchi TILL ────────────────────────────────────────────────
    print("\n--- Birinchi kassa (TILL) ---")
    till_code = (input("  TILL kodi [K1]             : ").strip() or "K1")
    till_label = (input("  TILL nomi [Kassa 1]        : ").strip() or "Kassa 1")
    st, b = call("POST", "/tills", {"branch_id": FACTS["branch_id"],
                                    "code": till_code, "label": till_label}, OH)
    check("TILL yaratildi", st == 200, f"HTTP {st} {b[:140]}")
    till = json.loads(b)
    FACTS["till_id"] = till["id"]
    FACTS["till_code"] = till["code"]
    check("TILL faol va shu filialda",
          till.get("active") is True and till["branch_id"] == FACTS["branch_id"])

    # ── 8-9. Birinchi kassir ────────────────────────────────────────────
    print("\n--- Birinchi kassir ---")
    cashier_name = input("  Kassir ismi                : ").strip()
    cashier_pin = getpass.getpass("  Kassir PIN (4 raqam, yashirin): ").strip()
    check("PIN 4 raqam", len(cashier_pin) >= 4 and cashier_pin.isdigit())
    st, b = call("POST", "/employees", {"full_name": cashier_name, "role_code": "kassir",
                                        "pin": cashier_pin, "branch_id": FACTS["branch_id"]}, OH)
    check("kassir yaratildi", st == 200, f"HTTP {st} {b[:140]}")
    FACTS["cashier_id"] = json.loads(b)["id"]

    # ── 10. Ro'yxat bootstrap: egа chiqadi -> kassir PIN bilan kiradi ──
    st, b = call("GET", "/auth/pin-roster", None, OH)
    check("kassirlar ro'yxati olindi", st == 200, f"HTTP {st}")
    roster = json.loads(b)
    check("kassir ro'yxatda", any(r["id"] == FACTS["cashier_id"] for r in roster), f"{len(roster)} ta")
    check("egа ro'yxatda YO'Q (PIN yo'li imtiyozliga yopiq)",
          all(r["id"] != FACTS["owner_id"] for r in roster))

    # ⚠️  EGА CHIQISHI ENDI SHU YERDA EMAS. `/auth/logout` `sec_epoch` ni oshiradi
    #     va egа ning BARCHA tokenlarini bekor qiladi. Ilgari chiqish shu yerda edi,
    #     keyingi `GET /employees` esa O'SHA yaroqsiz token bilan ketib 401 olardi —
    #     va `len({"detail": ...})` uni "1 ta xodim" deb ko'rsatardi. Chiqish endi
    #     BARCHA egа-tekshiruvlari tugagach, oxirida bajariladi.
    st, b = call("POST", "/auth/login", {"employee_id": FACTS["cashier_id"],
                                         "pin": cashier_pin, "company_code": company_code})
    check("kassir PIN bilan kirdi", st == 200, f"HTTP {st}")
    CH = {"Authorization": f"Bearer {json.loads(b)['access_token']}"}
    cashier_pin = None

    # ── 11. MOLIYAVIY AMAL QILINMAYDI ──────────────────────────
    #
    # ⚠️  BU YERDA SINOV SAVDOSI, SMENA, MAHSULOT VA HISOB-KITOB ATAYLAB YO'Q.
    #     CashLedger O'ZGARMAS (immutable): onboarding paytida yozilgan har qanday
    #     sun'iy yozuv mijozning DOIMIY moliyaviy tarixiga kirib qolardi va uni
    #     keyin "tozalab" bo'lmasdi. Birinchi moliyaviy hodisa do'kon HAQIQATAN
    #     ishlay boshlaganda, HAQIQIY savdo bilan yozilishi kerak.
    #
    #     Shu bois quyida faqat O'QISH tekshiruvlari: hech qanday mahsulot, smena,
    #     savdo, to'lov, qaytarish, naqd harakati yoki rekonsiliatsiya yaratilmaydi.

    # Kassir sessiyasi HAQIQATAN ishlayotganini o'qish bilan tasdiqlaymiz
    st, b = call("GET", "/auth/pin-roster", None, CH)
    check("kassir sessiyasi ishlaydi (o'qish)", st == 200, f"HTTP {st}")

    # ⚠️  ATAYLAB MUVAFFAQIYATSIZ LOGIN URINISHI QILINMAYDI. Egа ning PIN yo'lidan
    #     rad etilishi allaqachon avtomatik testlarda va staging'da qoplangan; uni
    #     HAQIQIY mijoz muhitida takrorlash `auth_attempts` / cheklov / xavfsizlik
    #     auditida keraksiz qoldiq qoldirardi. Bu yerda egа ning PIN yo'liga
    #     haqli EMASLIGI QOLDIQSIZ tarzda — ro'yxatda yo'qligi bilan — tasdiqlanadi.

    # ── 12. Biznes qatorlari kutilganidek ────────────────────────
    #
    # ⚠️  BU TEKSHIRUV BIZNES ma'lumotiga tegishli. Muvaffaqiyatli autentifikatsiya
    #     va chiqish hosil qiladigan XAVFSIZLIK/SESSIYA yozuvlari (`auth_attempts`
    #     tozalanishi, vendor sessiyasi, audit satrlari) NORMAL va bu yerda
    #     sanalmaydi — ular tenantning biznes holati emas.
    st, b = call("GET", "/employees", None, OH)
    check("xodimlar ro'yxati o'qildi (token amal qiladi)", st == 200, f"HTTP {st}")
    emps2 = json.loads(b)
    check("AYNAN 2 ta xodim (egа + kassir)", _list_len(st, b) == 2, f"{_list_len(st, b)} ta")
    roles = sorted(e["role"] for e in emps2)
    check("rollar: ega + kassir", roles == ["ega", "kassir"], str(roles))

    st, b = call("GET", "/branches", None, OH)
    n_br = _list_len(st, b, "branches")
    check("hamon AYNAN 1 ta filial", n_br == 1, f"{n_br} ta")

    st, b = call("GET", "/tills", None, OH)
    tl = json.loads(b) if st == 200 else []
    check("AYNAN 1 ta TILL", _list_len(st, b) == 1, f"{_list_len(st, b)} ta")
    check("SAFE yaratilmagan (ixtiyoriy)", all(t.get("type") == "TILL" for t in tl))

    st, b = call("GET", "/sales?limit=5", None, OH)
    check("SAVDO YO'Q (moliyaviy tarix toza)", _list_len(st, b, "items", "sales") == 0,
          f"{_list_len(st, b, 'items', 'sales')} ta")

    st, b = call("GET", "/shifts/current", None, CH)
    check("OCHIQ SMENA YO'Q", st == 200 and b.strip() in ("null", ""), f"HTTP {st} {b[:60]}")

    st, b = call("GET", "/cash/ops", None, OH)
    check("NAQD HARAKATI YO'Q", _list_len(st, b, "items", "ops") == 0,
          f"{_list_len(st, b, 'items', 'ops')} ta")
    # ⚠️  `CashLedgerEntry` va `reconciliation_records` uchun o'qish endpointi YO'Q.
    #     Ular onboardingdan KEYINGI zaxira nusxa barmoq izidan (`fingerprint.json`
    #     -> cash_counts) TO'G'RIDAN-TO'G'RI SELECT COUNT(*) bilan tekshiriladi.

    st, b = call("GET", "/products", None, OH)
    check("MAHSULOT YO'Q (import hali qilinmagan)", _list_len(st, b, "items") == 0,
          f"{_list_len(st, b, 'items')} ta")

    # ── 13. Yakuniy holat ────────────────────────────────
    st, b = call("GET", "/health/ready")
    check("yakuniy ready 200", st == 200, f"HTTP {st}")
    flat = b.replace(" ", "")
    check("yakuniy checklar true",
          all(f'"{k}":true' in flat for k in ("database", "cash_schema", "config", "tenancy_schema")))

    call("POST", "/auth/logout", None, OH)     # egа sessiyasi yopiladi (endi OXIRIDA)
    call("POST", "/auth/logout", None, CH)     # kassir sessiyasi yopiladi
    call("POST", "/admin/logout", None, VH)    # vendor sessiyasi bekor qilinadi
    print("\n  Moliyaviy amal QILINMADI — birinchi savdo mijozning HAQIQIY ishi bo'ladi.")
    return 0


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except Stop as e:
        print(f"\n!!! TO'XTATILDI: {e}")
        rc = 2
    except Exception as e:                                   # noqa: BLE001
        print(f"\n!!! KUTILMAGAN XATO: {type(e).__name__}: {str(e)[:200]}")
        rc = 3
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onboard_merchant.out")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(f"{'OK  ' if ok else 'XATO'} | {n} | {d}" for n, ok, d in OUT))
        f.write("\n\n--- FAKTLAR (sirlarsiz) ---\n")
        f.write(json.dumps(FACTS, ensure_ascii=False, indent=1))
        bad = [n for n, ok, _ in OUT if not ok]
        f.write(f"\n\n=== {len(OUT) - len(bad)} / {len(OUT)} | exit={rc} ===\n")
    print("\nnatija:", p)
    sys.exit(rc)
