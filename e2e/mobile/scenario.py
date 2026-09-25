# -*- coding: utf-8 -*-
"""Mobil E2E STSENARIYSI (Phase 5G, M6) — ALOHIDA do'kon (tenant) urug'lash.

Bu modul `start_backend.py` (mahalliy pgserver / CI postgres:18) va STAGING'dagi alohida
sinov do'koni uchun AYNI kod. Hamma narsa ilovaning O'Z yozuvchilari orqali yoziladi:

  * do'kon — vendor provizioningining O'Z funksiyasi (`admin.provision`): FRESH (ledger-native)
    tenant, T0 = yaratilish lahzasi, ya'ni smenasiz naqd amali `OPERATOR_MUST_CHOOSE`;
  * filial, xodimlar, mahsulotlar, partiya kuzatuvi, kassa/seyf, ta'minotchi, mijozlar,
    kirimlar, qarz to'lovlari — HAQIQIY HTTP marshrutlari (`TestClient`, jarayon ichida);
  * FAQAT ikki narsa to'g'ridan-to'g'ri ORM bilan (API'da yo'li yo'q): mijozning BOSHLANG'ICH
    qarzi (`CreditTransaction(adjustment)` — `app.seed` / 1C migratori bilan AYNI naqsh).
    Kassaga pul esa ataylab HAQIQIY yo'l bilan tushadi: qarz to'lovi (naqd, aniq hisob).

XAVFSIZLIK (fail-closed) — `refusal_reasons()`:
  * `APP_ENV` ANIQ `dev`/`test`/`staging` bo'lishi shart (yo'q/bo'sh/boshqa — RAD);
  * platforma (`RAILWAY_ENVIRONMENT_NAME`) production bo'lsa — RAD;
  * baza Postgres bo'lishi shart (kassa custody faqat Postgres'da);
  * `system_identifier` production ro'yxatida bo'lsa (7674898282858840119) — RAD, override YO'Q;
  * `APP_ENV=staging` da `--expect-system-identifier` MAJBURIY va ulangan bazaga teng;
  * do'kon kodi `e2e` bilan boshlanishi shart va bazada BO'LMASLIGI shart (mavjud do'konga
    hech qachon yozilmaydi — faqat YANGI, ataylab ajratilgan tenant).

CLI (staging uchun; mahalliy/CI yo'li `start_backend.py`):

    APP_ENV=staging DATABASE_URL=postgresql://... \
      python e2e/mobile/scenario.py --tenant-code e2emob0919 \
        --expect-system-identifier <staging sysid> --manifest e2e/mobile/.run/staging.json

Natija — MANIFEST (JSON): Dart E2E testlari aynan shu fayldan id/telefon/shtrix-kodlarni o'qiydi.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import secrets
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "apps" / "server"

# Production klasteri — `app/db/migrations/guard.py` bilan AYNI qiymat (import qilinadi; import
# bo'lmasa ham shu nusxa ishlaydi — himoya hech qachon "o'chib" qolmasin).
PRODUCTION_SYSTEM_IDENTIFIERS = frozenset({"7674898282858840119"})
ALLOWED_ENVS = frozenset({"dev", "test", "staging"})
PRODUCTION_NAMES = frozenset({"prod", "production"})
TENANT_PREFIX = "e2e"

# Hamma sinov xodimlarining paroli (parol siyosati: >= 12 belgi, arzon emas).
PASSWORD = "E2e-mobil-sinov-2026"

# (manifest kaliti, rol kodi, to'liq ism, filial kaliti yoki None)
USERS = (
    ("owner", "ega", "E2E Ega Sardor", None),
    ("omborchi", "omborchi", "E2E Omborchi Jamshid", "A"),
    ("kassir", "kassir", "E2E Kassir Dilnoza", "A"),
    ("menejer", "menejer", "E2E Menejer Nodira", "A"),
    ("omborchi_b", "omborchi", "E2E Omborchi Bobur", "B"),
)

# Mahsulotlar: kalit -> (nom, shtrix-kod, birlik, xarid, sotuv, kuzatuv)
#   kuzatuv: None | "lots" | "expiry"
PRODUCTS = {
    "plain": ("E2E Shakar 1kg", "4781200000017", "dona", 9000, 12000, None),
    "count_plain": ("E2E Tuz 1kg", "4781200000024", "dona", 3000, 4500, None),
    "lot": ("E2E Guruch partiyali", "4781200000031", "dona", 14000, 18000, "lots"),
    "expiry": ("E2E Qatiq muddatli", "4781200000048", "dona", 7000, 9500, "expiry"),
    "count_lot": ("E2E Yog' partiya sanoq", "4781200000055", "dona", 21000, 26000, "lots"),
    "wo_lot": ("E2E Kefir hisobdan chiqarish", "4781200000062", "dona", 8000, 11000, "expiry"),
    "corr": ("E2E Un tuzatish", "4781200000079", "dona", 5000, 7000, "lots"),
    "b_only": ("E2E Filial-B mahsuloti", "4781200000086", "dona", 4000, 6000, None),
    "scale": ("E2E Mol go'shti tarozi", None, "kg", 70000, 95000, None),
}
SCALE_PLU = 4121
SCALE_GRAMS = 1234


class Refused(RuntimeError):
    """Bu bazaga/muhitga sinov do'koni YOZILMAYDI."""


class SeedError(RuntimeError):
    """Urug'lash qadami server tomonidan rad etildi (matn — serverniki)."""


# ══ XAVFSIZLIK ═══════════════════════════════════════════════════════════════

def _env(name: str) -> str:
    raw = (os.getenv(name) or "").strip().lower()
    return raw or "unknown"


def normalize_url(url: str) -> str:
    for p in ("postgres://", "postgresql://"):
        if url.startswith(p):
            return "postgresql+psycopg://" + url[len(p):]
    return url


def database_identity(url: str) -> dict:
    """(dialect, system_identifier, database) — faqat katalog funksiyalari, YOZUV YO'Q."""
    from sqlalchemy import create_engine, text
    eng = create_engine(normalize_url(url), future=True)
    try:
        with eng.connect() as con:
            out = {"dialect": eng.dialect.name, "system_identifier": None, "database": None}
            if eng.dialect.name == "postgresql":
                out["system_identifier"] = str(con.execute(
                    text("SELECT system_identifier::text FROM pg_control_system()")).scalar())
                out["database"] = str(con.execute(text("SELECT current_database()")).scalar())
            return out
    finally:
        eng.dispose()


def refusal_reasons(url: str, *, tenant_code: str | None = None,
                    expect_system_identifier: str | None = None,
                    identity: dict | None = None) -> list[str]:
    """RAD sabablari (bo'sh ro'yxat = ruxsat). Hech narsa YOZMAYDI."""
    out: list[str] = []
    env, platform = _env("APP_ENV"), _env("RAILWAY_ENVIRONMENT_NAME")
    if env not in ALLOWED_ENVS:
        out.append(f"APP_ENV='{env}' ruxsat ro'yxatida emas {sorted(ALLOWED_ENVS)} "
                   "(yo'qligi 'production emas' degani EMAS)")
    if platform in PRODUCTION_NAMES:
        out.append(f"platforma muhiti '{platform}' — production")
    prod_ids = set(PRODUCTION_SYSTEM_IDENTIFIERS)
    try:
        sys.path.insert(0, str(SERVER_DIR))
        from app.db.migrations.guard import PRODUCTION_SYSTEM_IDENTIFIERS as _P  # noqa: N811
        prod_ids |= set(_P)
    except Exception:  # noqa: BLE001 — nusxa baribir ishlaydi
        pass
    ident = identity or database_identity(url)
    if ident.get("dialect") != "postgresql":
        out.append(f"baza Postgres emas ({ident.get('dialect')}) — kassa custody stsenariysi "
                   "faqat Postgres'da tug'iladi")
    sysid = ident.get("system_identifier")
    if sysid in prod_ids:
        out.append(f"system_identifier {sysid} — PRODUCTION klasteri (override yo'q)")
    if env == "staging":
        if not expect_system_identifier:
            out.append("staging'da --expect-system-identifier MAJBURIY (maqsad baza aniq aytilsin)")
        elif str(expect_system_identifier).strip() != sysid:
            out.append(f"kutilgan baza {expect_system_identifier}, ulangan {sysid}")
    if tenant_code is not None:
        if not tenant_code.startswith(TENANT_PREFIX) or not tenant_code.isalnum():
            out.append(f"do'kon kodi '{tenant_code}' '{TENANT_PREFIX}' bilan boshlanadigan "
                       "harf-raqam bo'lishi shart (sinov do'koni aniq ajralib tursin)")
    return out


def tenant_exists(url: str, tenant_code: str) -> bool:
    """Shu kodli do'kon bazada bormi — HECH NARSA yozmaydi (jadval yo'q bo'lsa False)."""
    from sqlalchemy import create_engine, inspect, text
    eng = create_engine(normalize_url(url), future=True)
    try:
        with eng.connect() as con:
            if not inspect(con).has_table("companies"):
                return False
            return con.execute(text("SELECT 1 FROM companies WHERE code = :c"),
                               {"c": tenant_code}).first() is not None
    finally:
        eng.dispose()


def assert_allowed(url: str, **kw) -> dict:
    ident = database_identity(url)
    bad = refusal_reasons(url, identity=ident, **kw)
    if bad:
        raise Refused("Sinov do'koni YOZILMAYDI:\n  - " + "\n  - ".join(bad))
    return ident


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def phone_for(tenant_code: str, idx: int) -> str:
    """Do'kon kodidan DETERMINISTIK telefon (+998 99 NNNNN II) — global noyob bo'lishi kerak."""
    h = int(hashlib.sha1(tenant_code.encode()).hexdigest()[:8], 16) % 90000 + 10000
    return f"+99899{h:05d}{idx:02d}"


def ean13(body12: str) -> str:
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


def scale_code(plu: int = SCALE_PLU, grams: int = SCALE_GRAMS) -> str:
    """POS tarozi yorlig'i: '27' + PLU(5) + gramm(5) + EAN-13 nazorat raqami.

    Kontrakt Fayzan do'konidan olingan REAL etiketkalar bilan tasdiqlangan
    (`tests/fixtures/scale_barcodes.json`)."""
    assert 0 <= plu <= 99999, f"PLU 5 xonaga sig'maydi: {plu}"
    return ean13(f"27{plu:05d}{grams:05d}")


class _Api:
    """Ilovaning O'Z marshrutlari — jarayon ichida (`TestClient`, lifespan'siz)."""

    def __init__(self, log):
        from fastapi.testclient import TestClient

        from app.main import app
        self.c = TestClient(app, raise_server_exceptions=True)
        self.log = log

    def call(self, method: str, path: str, token: str | None = None, body=None,
             expect=(200,), query: dict | None = None):
        h = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.c.request(method, "/api/v1" + path, json=body, headers=h, params=query)
        if r.status_code not in expect:
            raise SeedError(f"{method} {path} -> {r.status_code}: {r.text[:600]}")
        return r.json() if r.content else None

    def login(self, phone: str) -> str:
        return self.call("POST", "/auth/login/password",
                         body={"phone": phone, "password": PASSWORD})["access_token"]


def _provision(tenant_code: str, name: str, owner_phone: str) -> dict:
    """Vendor provizioningining O'Z funksiyasi (vendor autentifikatsiyasisiz — u HTTP qatlami).

    FRESH tenant: `ledger_native` + `cutover_at` = hozir (post-T0 gardlari darhol faol)."""
    from app.api.v1.admin import ProvisionIn, provision
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        return provision(ProvisionIn(
            company_name=name, company_code=tenant_code, owner_name=USERS[0][2],
            owner_phone=owner_phone, owner_password=PASSWORD, plan="business",
            branch_name="Markaz filiali", timezone="Asia/Tashkent"), True, db)
    finally:
        db.close()


def _opening_debt(customer_id: str, amount: int) -> None:
    """Mijozning BOSHLANG'ICH qarzi — `app.seed` bilan AYNI naqsh (invariant: balans == SUM(txn))."""
    from decimal import Decimal

    from app.db.session import SessionLocal
    from app.models.customers import CreditTransaction, Customer
    from app.models.enums import CreditTxnType
    db = SessionLocal()
    try:
        c = db.get(Customer, uuid.UUID(customer_id))
        c.credit_balance = Decimal(amount)
        db.add(CreditTransaction(customer_id=c.id, type=CreditTxnType.adjustment,
                                 amount=Decimal(amount), balance_after=Decimal(amount),
                                 note="Boshlang'ich qoldiq (E2E stsenariy)",
                                 created_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()


# ══ URUG'LASH ════════════════════════════════════════════════════════════════

def seed(url: str, tenant_code: str, *, expect_system_identifier: str | None = None,
         log=print) -> dict:
    """Stsenariy do'konini yaratadi va MANIFEST qaytaradi. `DATABASE_URL` allaqachon `url` bo'lishi
    va `app` hali import qilinmagan (yoki shu url bilan import qilingan) bo'lishi kerak."""
    t_start = time.monotonic()
    ident = assert_allowed(url, tenant_code=tenant_code,
                           expect_system_identifier=expect_system_identifier)
    if normalize_url(os.environ.get("DATABASE_URL", "")) != normalize_url(url):
        raise Refused("DATABASE_URL jarayonda boshqa bazaga qaragan — app import'idan OLDIN o'rnating")
    sys.path.insert(0, str(SERVER_DIR))

    from app.db.session import SessionLocal
    from app.models.org import Company
    with SessionLocal() as db:
        if db.query(Company).filter(Company.code == tenant_code).first() is not None:
            raise Refused(f"do'kon '{tenant_code}' ALLAQACHON bor — mavjud do'konga yozilmaydi "
                          "(yangi kod bering)")

    api = _Api(log)
    phones = {k: phone_for(tenant_code, i + 1) for i, (k, *_r) in enumerate(USERS)}
    shop = f"E2E Mobil Do'kon ({tenant_code})"

    # 1) Do'kon + A filial + ega (vendor provizioningi)
    prov = _provision(tenant_code, shop, phones["owner"])
    company_id, branch_a = prov["company_id"], prov["branch_id"]
    owner = api.login(phones["owner"])
    log(f"[scenario] do'kon {tenant_code} ({company_id}) yaratildi")

    # 2) B filial (A dan keyin yaratiladi -> egа'ning aktor filiali A)
    branch_b = api.call("POST", "/branches", owner,
                        {"name": "Chilonzor filiali", "timezone": "Asia/Tashkent"})["id"]
    branches = {"A": {"id": branch_a, "name": "Markaz filiali"},
                "B": {"id": branch_b, "name": "Chilonzor filiali"}}

    # 3) Xodimlar (parol bilan; filialga biriktirilgan)
    users = {"owner": {"id": prov["owner_id"], "phone": phones["owner"], "role": "ega",
                       "name": USERS[0][2], "branch": None}}
    for key, role, full, br in USERS[1:]:
        r = api.call("POST", "/employees", owner, {
            "full_name": full, "phone": phones[key], "role_code": role, "password": PASSWORD,
            "branch_id": branches[br]["id"] if br else None, "client_uuid": str(uuid.uuid4())})
        users[key] = {"id": r["id"], "phone": phones[key], "role": role, "name": full,
                      "branch": br}
    tok = {k: api.login(v["phone"]) for k, v in users.items()}

    # 4) Filial vaqt zonasi tasdig'i (muddatli partiya va sanoq shunga tayanadi)
    for b in branches.values():
        api.call("POST", "/lots/timezone/confirm", owner, {"branch_id": b["id"]})

    # 5) Mahsulotlar (qoldiqsiz — qoldiq HAQIQIY kirim bilan keladi)
    items = []
    for key, (nm, bc, unit, buy, sell, _t) in PRODUCTS.items():
        it = {"name": nm, "barcode": bc, "unit_code": unit, "buy_price": buy,
              "sell_price": sell, "stock": 0, "min_qty": 2, "client_uuid": str(uuid.uuid4())}
        if key == "scale":
            it.update(is_weighted=True, plu_code=str(SCALE_PLU), barcode=None)
        items.append(it)
    made = api.call("POST", "/products/bulk", owner, {"items": items})
    by_name = {p["name"]: p for p in made}
    products: dict = {}
    for key, (nm, bc, unit, buy, sell, track) in PRODUCTS.items():
        p = by_name[nm]
        products[key] = {"id": p["id"], "name": nm, "barcode": bc, "unit": unit,
                         "buy": buy, "sell": sell, "track_lots": track is not None,
                         "track_expiry": track == "expiry"}

    # 6) Partiya kuzatuvi (qoldiq 0 — ochilish partiyasi kerak emas)
    for key, (_n, _b, _u, _bu, _s, track) in PRODUCTS.items():
        if track:
            api.call("POST", "/lots/enable", owner, {
                "product_id": products[key]["id"], "branch_id": branch_a,
                "track_expiry": track == "expiry", "reason": "E2E mobil stsenariysi"})

    # 7) Kassa va seyflar (+ A filialda ARXIVLANGAN kassa: tanlovda chiqmasligi kerak)
    def _acc(path, br, code):
        a = api.call("POST", path, owner, {"branch_id": branches[br]["id"], "code": code})
        return {"id": a["id"], "code": code, "type": a["type"], "branch": br}
    accounts = {"till_a": _acc("/tills", "A", "E2E-K1"), "safe_a": _acc("/safes", "A", "E2E-S1"),
                "till_b": _acc("/tills", "B", "E2E-KB1"), "safe_b": _acc("/safes", "B", "E2E-SB1"),
                "till_a_archived": _acc("/tills", "A", "E2E-K9")}
    api.call("PATCH", f"/tills/{accounts['till_a_archived']['id']}", owner, {"active": False})

    # 8) Ta'minotchi va mijozlar
    supplier = api.call("POST", "/suppliers", owner, {"name": "E2E Ta'minotchi MChJ"})
    debtor = api.call("POST", "/customers", owner,
                      {"full_name": "E2E Qarzdor Akbar", "client_uuid": str(uuid.uuid4())})
    funder = api.call("POST", "/customers", owner,
                      {"full_name": "E2E Kassa manbai", "client_uuid": str(uuid.uuid4())})
    _opening_debt(debtor["id"], 150_000)
    _opening_debt(funder["id"], 30_000_000)

    # 9) Kassaga HAQIQIY pul: naqd qarz to'lovi, aniq hisob bilan (post-T0, smenasiz). Faqat
    #    A filial: B hisoblari stsenariyda chiqim qilmaydi (ular faqat "begona filial" belgisi).
    for acc_key, amount in (("till_a", 5_000_000), ("safe_a", 5_000_000)):
        api.call("POST", f"/customers/{funder['id']}/payments", owner, {
            "amount": amount, "method": "cash", "client_uuid": str(uuid.uuid4()),
            "cash_account_id": accounts[acc_key]["id"]})

    # 10) Qoldiq: A filial — omborchi kirimi (qarzga), partiyali qatorlar partiyalar bilan
    today = date.today()
    exp1, exp2 = (today + timedelta(days=20)).isoformat(), (today + timedelta(days=60)).isoformat()
    lines_a = [
        (products["plain"], 50, None),
        (products["count_plain"], 10, None),
        (products["lot"], 10, [{"qty": 6, "batch_number": "E2E-G-A1"},
                               {"qty": 4, "batch_number": "E2E-G-A2"}]),
        (products["count_lot"], 8, [{"qty": 5, "batch_number": "E2E-Y-1"},
                                    {"qty": 3, "batch_number": "E2E-Y-2"}]),
        (products["wo_lot"], 9, [{"qty": 4, "batch_number": "E2E-K-1", "expiry_date": exp1},
                                 {"qty": 5, "batch_number": "E2E-K-2", "expiry_date": exp2}]),
        (products["scale"], 5.5, None),
    ]
    rec_a = api.call("POST", "/receiving/commit", tok["omborchi"], {
        "items": [{"product_id": p["id"], "qty": q, "unit_cost": p["buy"], "unit": p["unit"],
                   **({"lots": lots} if lots else {})} for p, q, lots in lines_a],
        "supplier_id": supplier["id"], "payment": "credit", "source": "manual",
        "client_uuid": str(uuid.uuid4())})

    # 11) TUZATISH uchun hujjat: NAQD kirim (post-T0, smenasiz -> aniq kassa), partiyali
    corr = products["corr"]
    rec_c = api.call("POST", "/receiving/commit", owner, {
        "items": [{"product_id": corr["id"], "qty": 10, "unit_cost": corr["buy"], "unit": "dona",
                   "lots": [{"qty": 10, "batch_number": "E2E-U-1"}]}],
        "supplier_id": supplier["id"], "payment": "cash", "source": "manual",
        "cash_account_id": accounts["till_a"]["id"], "client_uuid": str(uuid.uuid4())})
    pur_c = api.call("GET", f"/purchases/{rec_c['purchase_id']}", owner)
    corr_lot = next(lt for it in pur_c["items"] for lt in (it.get("lots") or []))

    # 12) B filial — o'z qoldig'i (B ga biriktirilgan omborchi yozadi)
    rec_b = api.call("POST", "/receiving/commit", tok["omborchi_b"], {
        "items": [
            {"product_id": products["b_only"]["id"], "qty": 7, "unit_cost": 4000, "unit": "dona"},
            {"product_id": products["lot"]["id"], "qty": 3, "unit_cost": 14000, "unit": "dona",
             "lots": [{"qty": 3, "batch_number": "E2E-G-B1"}]},
        ],
        "supplier_id": supplier["id"], "payment": "credit", "source": "manual",
        "client_uuid": str(uuid.uuid4())})

    # 13) Tekshiruv: server ko'rgan holat stsenariy aytgan holat bilan AYNI
    def _stock(pid, br):
        rows = api.call("GET", "/products", owner,
                        query={"q": by_id[pid], "branch_id": branches[br]["id"],
                               "limit": 10})
        return next(float(r["stock"]) for r in rows if r["id"] == pid)
    by_id = {v["id"]: v["name"] for v in products.values()}
    expect = {("plain", "A"): 50, ("lot", "A"): 10, ("lot", "B"): 3, ("b_only", "B"): 7,
              ("b_only", "A"): 0, ("corr", "A"): 10, ("scale", "A"): 5.5}
    for (k, br), want in expect.items():
        got = _stock(products[k]["id"], br)
        if abs(got - want) > 1e-9:
            raise SeedError(f"qoldiq {k}@{br}: kutilgan {want}, server {got}")
    for k in ("plain", "lot"):
        sc = api.call("GET", "/products/scan", owner, query={"code": products[k]["barcode"]})
        if sc["kind"] != "barcode" or sc["product"]["id"] != products[k]["id"]:
            raise SeedError(f"skaner {k}: {sc}")
    sc = api.call("GET", "/products/scan", owner, query={"code": scale_code()})
    if sc["kind"] != "scale" or sc["product"]["id"] != products["scale"]["id"]:
        raise SeedError(f"tarozi yorlig'i: {sc}")
    prev = api.call("GET", "/cash/custody-preview", owner,
                    query={"operation": "receiving_payment"})
    if prev["mode"] != "OPERATOR_MUST_CHOOSE" or sorted(o["id"] for o in prev["options"]) != \
            sorted([accounts["till_a"]["id"], accounts["safe_a"]["id"]]):
        raise SeedError(f"custody-preview kutilgandek emas: {prev}")

    manifest = {
        "version": 1,
        "seeded_at": datetime.now(timezone.utc).isoformat(),
        "seconds": round(time.monotonic() - t_start, 2),
        "database": {"system_identifier": ident.get("system_identifier"),
                     "database": ident.get("database")},
        "app_env": _env("APP_ENV"),
        "tenant": {"id": company_id, "code": tenant_code, "name": shop},
        "password": PASSWORD,
        "users": users,
        "branches": branches,
        "products": products,
        "scale": {"code": scale_code(), "plu": SCALE_PLU, "grams": SCALE_GRAMS,
                  "qty": f"{SCALE_GRAMS / 1000:.3f}", "product": products["scale"]["id"]},
        "unknown_barcode": ean13("478129999999"),
        "accounts": accounts,
        "supplier": {"id": supplier["id"], "name": supplier["name"]},
        "customers": {"debtor": {"id": debtor["id"], "name": debtor["full_name"],
                                 "balance": 150_000}},
        "correction": {"receiving_id": rec_c["receiving_id"], "purchase_id": rec_c["purchase_id"],
                       "doc_no": pur_c["doc_no"], "lot_id": corr_lot["id"], "qty": 10,
                       "unit_cost": corr["buy"], "batch": "E2E-U-1"},
        "receivings": {"a": rec_a["receiving_id"], "b": rec_b["receiving_id"]},
        "lots": {"wo_expiry": [exp1, exp2]},
    }
    log(f"[scenario] tayyor: {len(products)} mahsulot, {len(users)} xodim, "
        f"{len(accounts)} hisob ({manifest['seconds']} s)")
    return manifest


def write_manifest(manifest: dict, path: str | os.PathLike) -> pathlib.Path:
    p = pathlib.Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--tenant-code", required=True, help="yangi do'kon kodi, 'e2e' bilan boshlanadi")
    ap.add_argument("--manifest", default=str(REPO / "e2e" / "mobile" / ".run" / "manifest.json"))
    ap.add_argument("--expect-system-identifier", default=None)
    ap.add_argument("--check-only", action="store_true", help="faqat xavfsizlik darvozasi, yozuvsiz")
    a = ap.parse_args(argv)
    if not a.database_url:
        print("DATABASE_URL (yoki --database-url) kerak", file=sys.stderr)
        return 2
    url = normalize_url(a.database_url)
    os.environ["DATABASE_URL"] = url
    # Jarayon ichidagi ilova nusxasi uchun: kuchli JWT kaliti (tokenlar shu jarayondan chiqmaydi),
    # vendor kaliti YO'Q (vendor marshruti ishlatilmaydi), demo seed YO'Q.
    os.environ["SECRET_KEY"] = secrets.token_hex(32)
    for k in ("VENDOR_ADMIN_KEY", "SEED_DEMO"):
        os.environ.pop(k, None)
    os.chdir(SERVER_DIR)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        if a.check_only:
            ident = assert_allowed(url, tenant_code=a.tenant_code,
                                   expect_system_identifier=a.expect_system_identifier)
            print(f"[scenario] ruxsat: {ident}")
            return 0
        m = seed(url, a.tenant_code, expect_system_identifier=a.expect_system_identifier)
    except Refused as e:
        print(f"[scenario] RAD: {e}", file=sys.stderr)
        return 3
    p = write_manifest(m, a.manifest)
    print(f"[scenario] manifest: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
