# -*- coding: utf-8 -*-
"""Xavfsizlik 3A — autentifikatsiya suiiste'moli va kredensial siyosati.

Qamrov:
  2  kassir cheklovi UMUMIY holatda (PostgreSQL), restart'dan omon qoladi
  3  `change_password` uchun STEP-UP (o'g'irlangan sessiya doimiy kredensialga
     aylanmasin)
  4  parol siyosati (uzunlik, arzon qiymatlar, bcrypt 72-bayt chegarasi)
  5  do'kon kodi enumeratsiyasi
  6  so'rov tanasi hajmi chegarasi
"""
import uuid

import pytest

_VK = {"X-Vendor-Key": "test-vendor-key"}


# ── yordamchilar ──────────────────────────────────────────────────────────
def _tenant(client, *, owner_password="Toshkent-Bahor-2026", plan="start"):
    phone = f"+99894{uuid.uuid4().int % 10000000:07d}"
    code = f"c3{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": "QA 3A", "company_code": code, "owner_name": "QA Ega",
        "owner_phone": phone, "owner_password": owner_password, "plan": plan})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password",
                     json={"phone": phone, "password": owner_password}).json()
    return {"company_id": uuid.UUID(r.json()["company_id"]), "code": code, "phone": phone,
            "password": owner_password, "owner_id": lg["employee"]["id"], "cashier_id": None,
            "headers": {"Authorization": f"Bearer {lg['access_token']}"}}


def _cashier(client, t, pin, role_code="kassir", phone=None):
    body = {"full_name": "QA Kassir", "role_code": role_code, "pin": pin}
    if phone:
        body["phone"] = phone
    r = client.post("/api/v1/employees", headers=t["headers"], json=body)
    assert r.status_code == 200, r.text
    t["cashier_id"] = r.json()["id"]        # standart PIN-nishon
    return r.json()


def _pin_login(client, t, pin, emp_id=None, code=None):
    """PIN login — endi NISHON xodim ham yuboriladi (bir so'rov = bitta bcrypt)."""
    return client.post("/api/v1/auth/login", json={
        "company_code": code if code is not None else t["code"],
        "employee_id": emp_id or t["cashier_id"] or t["owner_id"],
        "pin": pin})


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _clear(dimension=None):
    from app.models.security import AuthAttempt
    db = _db()
    try:
        q = db.query(AuthAttempt)
        if dimension:
            q = q.filter(AuthAttempt.dimension == dimension)
        q.delete()
        db.commit()
    finally:
        db.close()


# ═══ 2 · UMUMIY (BO'LINADIGAN) CHEKLOV ══════════════════════════════════════

def test_rate_limit_state_lives_in_the_database(client):
    """⚠️  Hisoblagich BAZADA. Ilgari u jarayon xotirasidagi lug'atda edi: har
    deploy'da nolga tushardi va instanslar o'rtasida bo'linmasdi, ya'ni "10
    xatodan keyin blok" degan kafolat amalda hech narsani kafolatlamasdi."""
    from app.models.security import AuthAttempt

    t = _tenant(client)
    _clear()
    for i in range(3):
        _pin_login(client, t, f"{8000 + i:04d}")
    db = _db()
    try:
        n = db.query(AuthAttempt).count()
    finally:
        db.close()
    assert n >= 3, f"urinishlar bazaga yozilmadi: {n}"


def test_rate_limit_survives_a_process_restart(client):
    """Yangi jarayon AYNI hisoblagichni ko'radi — modul qayta yuklansa ham.

    Nomzod kaliti `SECRET_KEY` dan olinadi, ya'ni u jarayonga XOS EMAS: aks holda
    har deploy'dan keyin nomzod qatlami nolga tushardi va replikalar bir-birining
    hisoblagichini ko'rmasdi."""
    import importlib

    from app.core import ratelimit as RL

    t = _tenant(client)
    _clear()
    before = RL.candidate_bucket(t["company_id"], "1234")
    importlib.reload(RL)                      # "qayta ishga tushish"
    after = RL.candidate_bucket(t["company_id"], "1234")
    assert before == after, "restart'dan keyin nomzod kaliti O'ZGARDI"


def test_two_sessions_observe_the_same_limit(client):
    """Ikki mustaqil DB sessiyasi (≈ ikki instans) AYNI holatni ko'radi."""
    from app.core import ratelimit as RL

    t = _tenant(client)
    _clear()
    d1, d2 = _db(), _db()
    try:
        RL.record(d1, [("cand", "shared-test-bucket", t["company_id"])] * 5)
        with pytest.raises(Exception) as ei:
            RL.guard(d2, "cand", "shared-test-bucket", RL.CAND_TIER, t["company_id"])
        assert getattr(ei.value, "status_code", None) == 429
    finally:
        d1.close(); d2.close()


def test_tenant_a_flood_does_not_limit_tenant_b(client):
    """Bir do'kondagi nomzod xatolari BOSHQA do'konga ta'sir qilmaydi."""
    from app.core import ratelimit as RL

    a, b = _tenant(client), _tenant(client)
    _clear()
    d = _db()
    try:
        bucket = RL.candidate_bucket(a["company_id"], "0000")
        RL.record(d, [("cand", bucket, a["company_id"])] * 6)
        # B uchun AYNI PIN qiymati — kalit boshqa, chunki company_id kiradi
        RL.guard(d, "cand", RL.candidate_bucket(b["company_id"], "0000"),
                 RL.CAND_TIER, b["company_id"])      # xato KO'TARMASLIGI kerak
    finally:
        d.close()


def test_attempts_are_pruned_and_do_not_grow_forever(client):
    """Eskirgan yozuvlar tozalanadi — jadval cheksiz o'smaydi."""
    from datetime import datetime, timedelta, timezone

    from app.core import ratelimit as RL
    from app.models.security import AuthAttempt

    _clear()
    d = _db()
    try:
        old = datetime.now(timezone.utc) - timedelta(seconds=RL._MAX_WINDOW + 60)
        d.add(AuthAttempt(dimension="ip", bucket="eski", occurred_at=old))
        d.commit()
        RL._last_prune[0] = 0.0               # prune'ni majburlaymiz
        RL._prune(d)
        assert d.query(AuthAttempt).filter(AuthAttempt.bucket == "eski").count() == 0
    finally:
        d.close()


# ═══ 3 · PAROL O'ZGARTIRISH — STEP-UP ═══════════════════════════════════════

def test_stolen_session_cannot_create_a_password_without_the_current_credential(client):
    """⚠️  ASOSIY REGRESSIYA. Paroli YO'Q akkaunt `old_password` SIZ parol
    o'rnata olardi: o'g'irlangan 12 soatlik token — masalan umumiy kassa
    terminalidan qolgan sessiya — DOIMIY kredensialga aylantirilardi."""
    t = _tenant(client)
    _cashier(client, t, "9090")
    tok = _pin_login(client, t, "9090").json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}

    r = client.post("/api/v1/auth/password", headers=H,
                    json={"new_password": "Yangi-Parol-2026-Kassa"})
    assert r.status_code == 401, r.text


def test_pin_account_can_set_a_password_by_proving_the_pin(client):
    """Joriy PIN — qonuniy step-up: u shu akkauntga kirish uchun ishlatilgan kredensial."""
    t = _tenant(client)
    # Parol o'rnatish uchun telefon SHART (mavjud qoida: parolli akkaunt telefoni
    # global noyob bo'lishi kerak) — bu test PIN step-up'ini tekshiradi, o'sha
    # qoidani emas.
    _cashier(client, t, "9191", phone=f"+99895{uuid.uuid4().int % 10000000:07d}")
    tok = _pin_login(client, t, "9191").json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}

    r = client.post("/api/v1/auth/password", headers=H,
                    json={"old_password": "9191", "new_password": "Yangi-Parol-2026-Kassa"})
    assert r.status_code == 200, r.text


def test_password_account_still_needs_the_current_password(client):
    t = _tenant(client)
    bad = client.post("/api/v1/auth/password", headers=t["headers"],
                      json={"old_password": "notogri-parol", "new_password": "Boshqa-Parol-2026"})
    assert bad.status_code == 401, bad.text
    ok = client.post("/api/v1/auth/password", headers=t["headers"],
                     json={"old_password": t["password"], "new_password": "Boshqa-Parol-2026"})
    assert ok.status_code == 200, ok.text


# ═══ 4 · PAROL SIYOSATI ═════════════════════════════════════════════════════

@pytest.mark.parametrize("value,must_fail,nega", [
    ("", True, "bo'sh"),
    ("qisqa1", True, "juda qisqa"),
    ("password1234", True, "arzon qiymatdan boshlanadi"),
    ("aaaaaaaaaaaaaa", True, "past entropiya"),
    ("x" * 80, True, "bcrypt 72 bayt chegarasi"),
    ("Toshkent-Bahor-2026-Kassa", False, "uzun ibora — QABUL"),
    ("men-bugun-bozorga-bordim", False, "oddiy ibora — QABUL"),
])
def test_password_policy(value, must_fail, nega):
    """⚠️  Ilgari yagona shart `len < 6` edi — `123456` do'konning butun
    boshqaruvini himoya qilardi.

    Maxsus belgi retsepti ATAYLAB yo'q: u odamlarni `Parol1!` kabi taxmin
    qilinadigan naqshlarga majburlaydi va entropiyaga deyarli qo'shmaydi."""
    from app.core.password_policy import password_policy_problem
    assert (password_policy_problem(value) is not None) is must_fail, nega


def test_password_longer_than_bcrypt_limit_is_rejected_not_truncated():
    """⚠️  JIM QISQARTIRISH YO'Q. bcrypt faqat 72 baytni hisobga oladi; uzunini
    qabul qilish foydalanuvchiga YOLG'ON xavfsizlik hissi berardi."""
    from app.core.password_policy import MAX_BYTES, password_policy_problem
    p = password_policy_problem("A" * (MAX_BYTES + 1))
    assert p and "uzun" in p, p


def test_policy_reason_never_contains_the_password():
    from app.core.password_policy import password_policy_problem
    secret = "maxfiy-parol-qiymati"
    p = password_policy_problem(secret)
    assert p is None or secret not in p


# ═══ 5 · DO'KON KODI ENUMERATSIYASI ═════════════════════════════════════════

def test_unknown_company_code_is_indistinguishable_from_a_wrong_pin(client):
    """⚠️  Ilgari "Do'kon kodi topilmadi" va "PIN noto'g'ri" ALOHIDA matnlar edi —
    bu autentifikatsiyasiz hujumchiga do'kon kodi MAVJUDLIGINI tasdiqlaydigan
    oracle berardi va hujum aynan o'sha do'konga qaratilardi."""
    t = _tenant(client)
    _cashier(client, t, "3131")
    _clear()

    mavjud = _pin_login(client, t, "0001")          # kod BOR, PIN noto'g'ri
    _clear("ip")
    yoq = _pin_login(client, t, "0001", code=f"yoq{uuid.uuid4().hex[:8]}")   # kod YO'Q

    assert mavjud.status_code == yoq.status_code == 401
    assert mavjud.json() == yoq.json(), (mavjud.json(), yoq.json())


def test_unknown_phone_is_indistinguishable_from_a_wrong_password(client):
    t = _tenant(client)
    _clear()
    bad_pw = client.post("/api/v1/auth/login/password",
                         json={"phone": t["phone"], "password": "butunlay-boshqa"})
    _clear()
    no_phone = client.post("/api/v1/auth/login/password",
                           json={"phone": "+998900000000", "password": "butunlay-boshqa"})
    assert bad_pw.status_code == no_phone.status_code == 401
    assert bad_pw.json() == no_phone.json()


# ═══ 6 · SO'ROV TANASI HAJMI ════════════════════════════════════════════════

def test_oversized_auth_payload_is_rejected(client):
    """⚠️  Chegara ILOVA KODIGA yetib bormasdan ishlaydi — ya'ni bcrypt umuman
    ishga tushmaydi. Ilgari chegara yo'q edi: autentifikatsiyasiz mijoz istalgan
    hajmdagi tanani serverga to'liq o'qitib, xotira va CPU yeyishi mumkin edi."""
    from app.core.bodylimit import AUTH_MAX_BYTES

    big = "9" * (AUTH_MAX_BYTES + 5_000)
    r = client.post("/api/v1/auth/login", json={"company_code": "x", "pin": big})
    assert r.status_code == 413, r.status_code


def test_normal_auth_payload_is_unaffected(client):
    t = _tenant(client)
    _cashier(client, t, "2424")
    _clear()
    assert _pin_login(client, t, "2424").status_code == 200


def test_non_auth_paths_keep_a_larger_limit():
    """Kirim rasmi `image_b64` sifatida JSON ichida keladi (~15 MB) — u buzilmasin."""
    from app.core.bodylimit import AUTH_MAX_BYTES, DEFAULT_MAX_BYTES, _limit_for
    assert _limit_for("/api/v1/auth/login") == AUTH_MAX_BYTES
    assert _limit_for("/api/v1/admin/login") == AUTH_MAX_BYTES
    assert _limit_for("/api/v1/receiving/scan") == DEFAULT_MAX_BYTES
    assert DEFAULT_MAX_BYTES > 15_000_000, "kirim rasmi uchun joy qolmadi"


# ═══ 7 · N x bcrypt DoS — BIR SO'ROV = BITTA bcrypt ═════════════════════════
#
# ⚠️  O'LCHANGAN MUAMMO. Ilgari `/auth/login` PIN'ni do'kondagi HAR BIR xodim
#     hash'i bilan qiyoslardi. bcrypt (cost 12) ≈ 220 ms:
#         N=1 → 214 ms · N=10 → 2 213 ms · N=25 → 5 619 ms
#         N=50 → 10 882 ms · N=100 → 21 861 ms
#     Ya'ni bitta AUTENTIFIKATSIYASIZ so'rov 100 xodimli do'konda ~22 CPU-soniya
#     yeyardi. Endi POS avval kassirni tanlaydi va server AYNAN BITTA hash'ni
#     tekshiradi.


class _Spy:
    def __init__(self):
        self.n = 0


def _count_bcrypt(monkeypatch) -> _Spy:
    """`/auth/login` yo'lidagi HAQIQIY bcrypt chaqiruvlarini sanaydi."""
    from app.api.v1 import auth as A
    from app.core.security import verify_password as real
    spy = _Spy()

    def _wrapped(raw, hashed):
        spy.n += 1
        return real(raw, hashed)

    monkeypatch.setattr(A, "verify_password", _wrapped)
    return spy


@pytest.fixture(scope="session")
def big(client):
    """1 / 10 / 25 / 50 / 100 xodimli do'konlar.

    ⚠️  To'ldiruvchi xodimlar TO'G'RIDAN-TO'G'RI bazaga yoziladi va BITTA tayyor
        hash'ni baham ko'radi — aks holda tayyorgarlikning O'ZI ~186 ta bcrypt
        (~40 s) bo'lardi. Yangi modelda bu ahamiyatsiz: server baribir faqat
        bitta, ANIQ ko'rsatilgan xodimni tekshiradi. Eski (N x bcrypt) yo'lda esa
        bu to'ldiruvchilar aynan yukni hosil qiladi — negativ nazorat shunga tayanadi.
    """
    from app.core.security import hash_password
    from app.models.auth import Employee, Role

    filler_hash = hash_password("0000")     # BITTA marta hisoblanadi
    out = {}
    for n in (1, 10, 25, 50, 100):
        t = _tenant(client)
        target = _cashier(client, t, f"{7000 + n:04d}")
        db = _db()
        try:
            rid = db.query(Role.id).filter(Role.code == "kassir").scalar()
            for i in range(n - 1):          # nishon xodim ham N ga kiradi
                db.add(Employee(company_id=t["company_id"], full_name=f"Toldiruvchi {i}",
                                role_id=rid, pin_hash=filler_hash))
            db.commit()
        finally:
            db.close()
        out[n] = {"t": t, "id": target["id"], "pin": f"{7000 + n:04d}"}
    return out


def _emp_count(company_id) -> int:
    from app.models.auth import Employee
    db = _db()
    try:
        return db.query(Employee).filter(Employee.company_id == company_id).count()
    finally:
        db.close()


# ── 1/2/3 · N qancha bo'lsa ham AYNAN bitta bcrypt ──────────────────────────
@pytest.mark.parametrize("n", [1, 10, 100])
def test_login_costs_exactly_one_bcrypt_regardless_of_headcount(client, big, monkeypatch, n):
    """1 / 10 / 100 xodim — baribir AYNAN 1 ta bcrypt."""
    d = big[n]
    assert _emp_count(d["t"]["company_id"]) >= n, "tayyorgarlik yetarli emas"
    _clear()
    spy = _count_bcrypt(monkeypatch)
    r = _pin_login(client, d["t"], "0001", d["id"])       # noto'g'ri PIN — eng qimmat yo'l
    assert r.status_code == 401, r.text
    assert spy.n == 1, f"N={n} uchun {spy.n} ta bcrypt bajarildi"


# ── 4 · Nomavjud xodim → ko'pi bilan bitta SOXTA bcrypt ────────────────────
def test_unknown_employee_costs_exactly_one_dummy_bcrypt(client, monkeypatch):
    """Nomavjud `employee_id` ham AYNAN bitta bcrypt sarflaydi.

    Ikki sabab: (a) javob vaqti "bunday xodim bormi" degan oracle bermasin,
    (b) nol bcrypt bo'lsa, nomavjud ID bilan arzon so'rov yuborish orqali boshqa
    o'lchovlarni chalg'itish oson bo'lardi."""
    t = _tenant(client)
    _clear()
    spy = _count_bcrypt(monkeypatch)
    r = _pin_login(client, t, "0001", str(uuid.uuid4()))
    assert r.status_code == 401, r.text
    assert spy.n == 1, spy.n


# ── 5/6/7 · Tashqi xulq: yagona xato ────────────────────────────────────────
def test_valid_cashier_with_valid_pin_succeeds(client):
    t = _tenant(client)
    e = _cashier(client, t, "5511")
    _clear()
    r = _pin_login(client, t, "5511", e["id"])
    assert r.status_code == 200, r.text
    assert r.json()["employee"]["id"] == e["id"]


def test_wrong_pin_and_unknown_employee_are_the_same_failure(client):
    """⚠️  Nomavjud xodim va noto'g'ri PIN TASHQARIDAN farqlanmasligi kerak —
    aks holda `employee_id` ni tekshirish uchun oracle paydo bo'lardi."""
    t = _tenant(client)
    e = _cashier(client, t, "5512")
    _clear()
    xato_pin = _pin_login(client, t, "9999", e["id"])
    _clear()
    yoq_xodim = _pin_login(client, t, "9999", str(uuid.uuid4()))
    assert xato_pin.status_code == yoq_xodim.status_code == 401
    assert xato_pin.json() == yoq_xodim.json(), (xato_pin.json(), yoq_xodim.json())


# ── 8 · Tenant izolyatsiyasi ────────────────────────────────────────────────
def test_tenant_b_cannot_authenticate_a_tenant_a_employee(client):
    """A do'konining xodim UUID'si B do'koni konteksti bilan ISHLAMAYDI."""
    a, b = _tenant(client), _tenant(client)
    ea = _cashier(client, a, "6611")
    _clear()
    assert _pin_login(client, a, "6611", ea["id"]).status_code == 200
    _clear()
    r = _pin_login(client, b, "6611", ea["id"])     # A ning ID'si, B ning kodi
    assert r.status_code == 401, r.text


# ── 9/16 · Filial va tenant doirasi — kassir tanlash MANBASIDA ─────────────
def _branch(client, t, name):
    r = client.post("/api/v1/branches", headers=t["headers"], json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"] if isinstance(r.json(), dict) else r.json()


def _roster(client, headers):
    return client.get("/api/v1/auth/pin-roster", headers=headers)


def test_cashier_selector_is_tenant_and_branch_scoped(client):
    """⚠️  Kassir tanlash ro'yxati AYNAN shu do'kon va shu filial bilan chegaralangan.

    Filial cheklovi login so'rovida emas, ro'yxat MANBASIDA qo'llanadi — chunki
    so'rovdagi `branch_id` mijozdan keladi va uni mijozning O'ZI tanlaydi, ya'ni u
    xavfsizlik nazorati bo'la olmaydi. Kanonik model — `visible_branches`."""
    t = _tenant(client, plan="business")   # ko'p filial uchun
    bx, by = _branch(client, t, "Filial X"), _branch(client, t, "Filial Y")
    ax = client.post("/api/v1/employees", headers=t["headers"], json={
        "full_name": "Kassir X", "role_code": "kassir", "pin": "7711", "branch_id": bx}).json()
    by_emp = client.post("/api/v1/employees", headers=t["headers"], json={
        "full_name": "Kassir Y", "role_code": "kassir", "pin": "7722", "branch_id": by}).json()
    _clear()

    tok = _pin_login(client, t, "7711", ax["id"]).json()["access_token"]
    r = _roster(client, {"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    ids = {x["id"] for x in r.json()}
    assert ax["id"] in ids, "o'z filiali ko'rinmadi"
    assert by_emp["id"] not in ids, "BOSHQA filial xodimi ro'yxatga tushdi"

    # Boshqa do'kon esa umuman ko'rinmaydi.
    b = _tenant(client)
    eb = _cashier(client, b, "7733")
    assert eb["id"] not in ids


def test_owner_never_appears_in_the_cashier_selector(client):
    """Egа ro'yxatda KO'RINMAYDI — u PIN yo'lidan kira olmaydi."""
    t = _tenant(client)
    e = _cashier(client, t, "7744")
    _clear()
    tok = _pin_login(client, t, "7744", e["id"]).json()["access_token"]
    ids = {x["id"] for x in _roster(client, {"Authorization": f"Bearer {tok}"}).json()}
    assert t["owner_id"] not in ids


# ── 10 · Imtiyozli identifikator PIN yo'lidan kirmaydi ──────────────────────
def test_privileged_employee_id_is_rejected(client):
    """Egа va administrator `employee_id` si bilan ham PIN yo'li YOPIQ."""
    t = _tenant(client)
    adm = _cashier(client, t, "8811", role_code="administrator")
    _clear()
    assert _pin_login(client, t, "8811", adm["id"]).status_code == 401
    _clear()
    # Egа: unga PIN o'rnatib ko'ramiz — baribir rad etiladi.
    from app.core.security import hash_password
    from app.models.auth import Employee
    db = _db()
    try:
        o = db.get(Employee, uuid.UUID(t["owner_id"]))
        o.pin_hash = hash_password("8812")
        db.commit()
    finally:
        db.close()
    assert _pin_login(client, t, "8812", t["owner_id"]).status_code == 401


# ── 11 · Faol bo'lmagan xodim ──────────────────────────────────────────────
def test_disabled_employee_is_rejected(client):
    t = _tenant(client)
    e = _cashier(client, t, "8822")
    _clear()
    assert _pin_login(client, t, "8822", e["id"]).status_code == 200

    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    db = _db()
    try:
        row = db.get(Employee, uuid.UUID(e["id"]))
        row.status = EmployeeStatus.suspended
        db.commit()
    finally:
        db.close()
    _clear()
    assert _pin_login(client, t, "8822", e["id"]).status_code == 401


# ── 14 · Bir kassirga qarshi toshqin do'konni bloklamaydi ──────────────────
def test_flood_against_one_cashier_does_not_lock_another(client):
    """⚠️  ASOSIY REGRESSIYA (P0-1 ning yangi modeldagi shakli). Bir kassirga
        qaratilgan toshqin YONIDAGI kassirni ham, butun do'konni ham kassadan
        uzmasligi kerak. Do'kon qatlami ATAYLAB faqat sekinlashtiradi."""
    t = _tenant(client)
    a = _cashier(client, t, "9911")
    b = _cashier(client, t, "9922")
    _clear()
    for i in range(30):
        _clear("ip")                                  # tarqoq hujum taqlidi
        _pin_login(client, t, f"{1000 + i:04d}", a["id"])
    _clear("ip")
    r = _pin_login(client, t, "9922", b["id"])
    assert r.status_code == 200, f"yonidagi kassir bloklandi: {r.status_code} {r.text}"


# ── 15 · Anonim enumeratsiya YO'Q ──────────────────────────────────────────
def test_anonymous_caller_cannot_enumerate_employees(client):
    """⚠️  QAT'IY SHART. `company_code` ni bilgan anonim foydalanuvchi xodimlar
        ro'yxatini HECH QANDAY yo'l bilan ola olmasligi kerak."""
    t = _tenant(client)
    _cashier(client, t, "3311")
    _clear()
    for path in ("/api/v1/auth/pin-roster", "/api/v1/employees"):
        r = client.get(path)
        assert r.status_code in (401, 403), (path, r.status_code, r.text)
        assert "3311" not in r.text and "QA Kassir" not in r.text, (path, r.text)
    # Do'kon kodi bilan ham — qo'shimcha parametr yo'li ochiq qolmasin.
    r = client.get(f"/api/v1/auth/pin-roster?company_code={t['code']}")
    assert r.status_code in (401, 403), r.status_code


# ── 17 · Eski (N x bcrypt) yo'l UMUMAN yo'q ────────────────────────────────
def test_legacy_pin_login_payload_is_rejected(client):
    """`employee_id` siz so'rov — 422. Legacy fallback ATAYLAB qoldirilmagan:
    u qolsa, DoS yo'li ham qolardi."""
    t = _tenant(client)
    _cashier(client, t, "3322")
    r = client.post("/api/v1/auth/login", json={"company_code": t["code"], "pin": "3322"})
    assert r.status_code == 422, r.text
    assert "employee_id" in r.text


def test_login_source_contains_no_bcrypt_loop():
    """Manba darajasidagi qo'riqchi: `login_pin` ichida bitta bcrypt yo'li bo'lsin.

    HTTP testi kelajakda qayta tiklangan siklni ushlamasligi mumkin (masalan
    fallback boshqa nom ostida qaytsa), shu bois yo'lning O'ZI tekshiriladi."""
    import inspect
    from app.api.v1 import auth as A
    src = inspect.getsource(A.login_pin)
    assert src.count("verify_password(") == 1, src
    assert " for " not in src.replace("\n", " "), "login_pin ichida sikl paydo bo'ldi"


# ── PERFORMANCE · kechikish xodimlar soniga BOG'LIQ EMAS ──────────────────
def test_latency_does_not_scale_with_headcount(client, big, monkeypatch):
    """⚠️  ASOSIY O'LCHOV. Eski yo'lda N=100 → ~22 s edi. Endi har N uchun
        AYNAN 1 bcrypt va kechikish deyarli o'zgarmas bo'lishi kerak."""
    import time as _t
    olchov = {}
    for n in (1, 10, 25, 50, 100):
        d = big[n]
        _clear()
        spy = _count_bcrypt(monkeypatch)
        t0 = _t.perf_counter()
        r = _pin_login(client, d["t"], "0001", d["id"])
        olchov[n] = (_t.perf_counter() - t0, spy.n)
        assert r.status_code == 401, r.text

    for n, (_, calls) in olchov.items():
        assert calls == 1, f"N={n}: {calls} ta bcrypt"

    kichik = olchov[1][0]
    katta = olchov[100][0]
    # Chiziqli o'sish 100x bo'lardi. 4x chegara sekin CI mashinasidagi shovqinni
    # ko'taradi, lekin regressiyani (10x+) baribir ushlaydi.
    assert katta < kichik * 4 + 0.5, f"kechikish xodimlar soniga bog'liq: {olchov}"


# ═══ 8 · SOVUQ START AUDITIDAN KEYINGI TUZATISHLAR ═══════════════════════
#
# Quyidagilar adversarial auditda O'LCHANGAN kamchiliklar uchun regressiya
# to'siqlari. Har biri "ilgari nima noto'g'ri edi" bilan birga yozilgan.


def test_candidate_throttle_is_not_an_existence_oracle(client, monkeypatch):
    """⚠️  ASOSIY REGRESSIYA. Nomzod qatlami ilgari 429 otardi va u FAQAT haqiqiy,
        faol, PIN-haqli xodim uchun ishlardi — ya'ni "429 keldi" degan javobning
        o'zi employee_id haqiqiyligini TASDIQLARDI. Endi chegara oshganda javob
        noto'g'ri PIN bilan bayt-ma-bayt bir xil."""
    t = _tenant(client)
    e = _cashier(client, t, "4747")
    _clear()

    # Nomzod chegarasini oshiramiz (CAND_TIER = 5).
    for _ in range(6):
        _pin_login(client, t, "0000", e["id"])
        _clear("ip")

    bor = _pin_login(client, t, "0000", e["id"])            # HAQIQIY xodim
    _clear("ip")
    yoq = _pin_login(client, t, "0000", str(uuid.uuid4()))  # NOMAVJUD xodim

    assert bor.status_code == yoq.status_code == 401, (bor.status_code, yoq.status_code)
    assert bor.text == yoq.text, (bor.text, yoq.text)


def test_candidate_throttle_still_blocks(client):
    """To'siq HAQIQIY: chegaradan keyin AYNI qiymat to'g'ri PIN bo'lsa ham o'tmaydi."""
    t = _tenant(client)
    a = _cashier(client, t, "4848")
    b = _cashier(client, t, "5252")
    _clear()
    for _ in range(6):
        _pin_login(client, t, "5252", a["id"])   # b ning PIN qiymatini bolg'alaymiz
        _clear("ip")
    assert _pin_login(client, t, "5252", b["id"]).status_code == 401


def test_throttled_request_still_costs_exactly_one_bcrypt(client, monkeypatch):
    """Cheklangan so'rov ham AYNAN bitta bcrypt sarflaydi — "tez 401" oracle bo'lmasin."""
    t = _tenant(client)
    e = _cashier(client, t, "4949")
    _clear()
    for _ in range(6):
        _pin_login(client, t, "0000", e["id"])
        _clear("ip")
    spy = _count_bcrypt(monkeypatch)
    r = _pin_login(client, t, "0000", e["id"])
    assert r.status_code == 401
    assert spy.n == 1, spy.n


def test_locked_out_cashier_can_be_unlocked_by_a_manager(client):
    """⚠️  Xodim qatlami QATTIQ bloklaydi (4 raqamli PIN uchun yagona haqiqiy to'siq),
        lekin blokni ochish YO'LI bo'lishi SHART. Aks holda `employee_id` ni bilgan
        tomon kassirni uzluksiz 429 da ushlab, do'konni ishsiz qoldirardi."""
    t = _tenant(client)
    e = _cashier(client, t, "5353")
    _clear()

    codes = []
    for i in range(13):                       # ACCT_TIER = 12
        codes.append(_pin_login(client, t, f"{6000 + i:04d}", e["id"]).status_code)
        _clear("ip")
    assert 429 in codes, codes
    assert _pin_login(client, t, "5353", e["id"]).status_code == 429   # to'g'ri PIN ham to'silgan

    r = client.post(f"/api/v1/employees/{e['id']}/unlock", headers=t["headers"])
    assert r.status_code == 200, r.text
    _clear("ip")
    assert _pin_login(client, t, "5353", e["id"]).status_code == 200


def test_unlock_is_tenant_scoped_and_permissioned(client):
    a, b = _tenant(client), _tenant(client)
    ea = _cashier(client, a, "5454")
    # Boshqa do'kon rahbari — 404 (mavjudligi oshkor qilinmaydi)
    assert client.post(f"/api/v1/employees/{ea['id']}/unlock",
                       headers=b["headers"]).status_code == 404
    # Kassir o'zi — ruxsat yo'q
    _clear()
    tok = _pin_login(client, a, "5454", ea["id"]).json()["access_token"]
    r = client.post(f"/api/v1/employees/{ea['id']}/unlock",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.status_code


def test_pin_roster_does_not_query_per_employee(client):
    """⚠️  N+1 REGRESSIYASI. Ilgari ro'yxat har xodim uchun alohida
        `employee_permissions` so'rovi berardi: 108 xodimda 108 ta ortiqcha
        so'rov (o'lchangan). 'business' tarifida shift 999 xodim."""
    from sqlalchemy import event
    from app.db.session import engine

    t = _tenant(client, plan="business")
    for i in range(12):
        _cashier(client, t, f"{3400 + i:04d}")
    _clear()

    n = [0]

    def _count(conn, cursor, statement, params, context, executemany):
        n[0] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        r = client.get("/api/v1/auth/pin-roster", headers=t["headers"])
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert r.status_code == 200, r.text
    assert len(r.json()) >= 12, len(r.json())
    # Xodim soniga BOG'LIQ BO'LMAGAN, kichik doimiy chegara.
    assert n[0] <= 15, f"{n[0]} ta so'rov — xodim soniga bog'liq bo'lib qoldi"


def test_unknown_client_ip_does_not_create_one_global_bucket(client, monkeypatch):
    """⚠️  Ilgari IP aniqlanmasa kalit "?" bo'lardi — BITTA GLOBAL hisoblagich.
        10 ta xato BARCHA do'konlarni 5 daqiqaga kassadan uzardi (P0-1 ning
        tizim miqyosidagi shakli)."""
    from app.api.v1 import auth as A
    monkeypatch.setattr(A, "_client_ip", lambda request: "")

    a, b = _tenant(client), _tenant(client)
    ea, eb = _cashier(client, a, "5757"), _cashier(client, b, "5858")
    _clear()

    codes = [_pin_login(client, a, f"{7700 + i:04d}", ea["id"]).status_code for i in range(12)]
    assert 429 in codes, codes                       # o'z xodimi uchun cheklov ISHLAYDI
    # Boshqa do'konning kassiri BEMALOL kiradi — kalit global emas.
    assert _pin_login(client, b, "5858", eb["id"]).status_code == 200


def test_password_login_with_no_digits_is_the_same_failure(client):
    """⚠️  Raqamsiz telefon ilgari BOSHQA matn qaytarardi (kichik, lekin haqiqiy farq)."""
    t = _tenant(client)
    _clear()
    yoq = client.post("/api/v1/auth/login/password",
                      json={"phone": t["phone"], "password": "butunlay-boshqa"})
    _clear()
    raqamsiz = client.post("/api/v1/auth/login/password",
                           json={"phone": "+-+-", "password": "butunlay-boshqa"})   # 4 belgi, raqamsiz
    assert yoq.status_code == raqamsiz.status_code == 401
    assert yoq.json() == raqamsiz.json(), (yoq.json(), raqamsiz.json())


def test_login_returns_the_company_code_for_device_self_repair(client):
    """⚠️  Qurilmaga xato do'kon kodi terilsa, parol logini baribir o'tardi va
        keyin HAR BIR PIN login o'sha xato kod bilan ketib doim 401 berardi.
        Endi POS kodni autentifikatsiyalangan javobdan oladi."""
    t = _tenant(client)
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": t["phone"], "password": t["password"]})
    assert r.status_code == 200, r.text
    assert r.json()["employee"]["company_code"] == t["code"]
