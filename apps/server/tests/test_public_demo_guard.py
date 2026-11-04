"""OMMAVIY DEMO HISOBI — server tomonidagi yozuv taqiqi va TOR DOIRA isboti.

Nima tekshiriladi:
  1. Demo hisobi O'QIYDI, lekin HAR QANDAY yozuv metodi 403 (deps darvozasi).
  2. `POST /auth/password`, `POST /auth/account-deletion` ham 403.
  3. `POST /auth/logout` — NO-OP: demo'ning BOSHQA sessiyalari uzilmaydi.
  4. ODDIY mijoz hisobi (ayni do'konda) login/logout/parol — AVVALGIDEK ishlaydi.
  5. Umumiy demo telefoni hisob-darajali tezlik cheklovidan OZOD, oddiy telefon — EMAS.
  6. Belgi (`Setting`) nomuvofiq bo'lsa imtiyoz BERILMAYDI (imtiyoz o'g'irlanmasin).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core import public_demo as PD

DEMO_PHONE = "+998900000777"
DEMO_PW = "demoPublic123"
ODDIY_PHONE = "+998900000778"
ODDIY_PW = "oddiyPublic123"
SEED_ADMIN = "+998901234567"


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _xodim(db, comp_id, phone, pw, rol="menejer", nom="Test"):
    from app.core.security import hash_password
    from app.models.auth import Employee, Role
    role = db.query(Role).filter(Role.code == rol).first()
    e = Employee(company_id=comp_id, full_name=nom, phone=phone, role_id=role.id,
                 password_hash=hash_password(pw))
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def demo(client):
    """Demo ko'ruvchisi + ODDIY xodim + belgi qatori; test oxirida TOZALANADI."""
    from app.models.auth import Employee, EmployeePermission, Permission
    from app.models.org import Company
    from app.models.settings import Setting
    db = _db()
    comp = db.query(Company).first()
    d = _xodim(db, comp.id, DEMO_PHONE, DEMO_PW, nom="BinOS Demo (faqat korish)")
    o = _xodim(db, comp.id, ODDIY_PHONE, ODDIY_PW, nom="Oddiy Menejer")
    for p in db.query(Permission).filter(Permission.code.in_(("kassa.ops", "mijozlar.edit"))).all():
        db.add(EmployeePermission(employee_id=d.id, permission_id=p.id, allowed=False))
    db.add(Setting(company_id=comp.id, key=PD.PUBLIC_DEMO_KEY,
                   value={"employee_id": str(d.id), "phone": DEMO_PHONE}))
    db.commit()
    did, oid = d.id, o.id
    PD.reset_phones_cache()
    try:
        yield {"id": did, "oddiy_id": oid, "company_id": comp.id}
    finally:
        db.query(EmployeePermission).filter(EmployeePermission.employee_id == did).delete()
        db.query(Setting).filter(Setting.key == PD.PUBLIC_DEMO_KEY).delete()
        db.commit()
        #  ⚠️  QATTIQ O'CHIRISH FK bilan to'xtashi mumkin (test yaratgan mijozda
        #      `created_by`). Bunda YUMSHOQ o'chiramiz va TELEFONNI bo'shatamiz —
        #      aks holda keyingi testlarda global telefon noyobligi buzilardi.
        for x in (did, oid):
            row = db.get(Employee, x)
            if row is None:
                continue
            try:
                db.delete(row)
                db.commit()
            except Exception:
                db.rollback()
                row = db.get(Employee, x)
                row.phone = None
                row.password_hash = None
                row.status = "terminated"
                row.deleted_at = datetime.now(timezone.utc)
                db.commit()
        db.close()
        PD.reset_phones_cache()


def _login(client, phone, pw, ip="91.200.10.7"):
    #  Python 203.0.113.0/24 (TEST-NET-3) ni `is_private` deb biladi va
    #  `core/net._is_infrastructure` uni RAD etadi -> IP noma'lum bo'lib
    #  hamma urinish BIR kalitga tushardi. Shu bois HAQIQIY global diapazon.
    return client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw},
                       headers={"X-Forwarded-For": ip})


def _tok(client, phone, pw):
    r = _login(client, phone, pw)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# -- 1. O'qish ishlaydi -------------------------------------------------------
def test_demo_oqish_ishlaydi(client, demo):
    h = _tok(client, DEMO_PHONE, DEMO_PW)
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    r = client.get("/api/v1/auth/context", headers=h)
    assert r.status_code == 200
    assert r.json()["employee"]["role_code"] == "menejer"


# -- 2. Yozuv metodlari 403 ---------------------------------------------------
@pytest.mark.parametrize("metod,yol,tana", [
    ("POST", "/api/v1/sales", {"items": [], "payments": []}),
    ("POST", "/api/v1/cash/ops", {"type": "collection", "amount": 1, "reason": "t",
                                  "client_uuid": "11111111-1111-1111-1111-111111111111"}),
    ("POST", "/api/v1/shifts/open", {"opening_cash": 0}),
    ("POST", "/api/v1/customers", {"full_name": "t"}),
    ("PUT", "/api/v1/settings", {"key": "store_info", "value": {"name": "t"}}),
    ("POST", "/api/v1/auth/password", {"old_password": DEMO_PW, "new_password": "yangiParol123"}),
    ("POST", "/api/v1/auth/account-deletion", {"confirm": "O'CHIRISH", "password": DEMO_PW}),
])
def test_demo_yozuv_403(client, demo, metod, yol, tana):
    h = _tok(client, DEMO_PHONE, DEMO_PW)
    r = client.request(metod, yol, json=tana, headers=h)
    assert r.status_code == 403, f"{metod} {yol} -> {r.status_code} {r.text[:120]}"
    assert "demo" in r.text.lower()


def test_demo_paroli_ozgarmaydi(client, demo):
    """403 dan keyin ham ESKI parol ishlashi SHART (yozuv amalga oshmagan)."""
    h = _tok(client, DEMO_PHONE, DEMO_PW)
    client.post("/api/v1/auth/password", headers=h,
                json={"old_password": DEMO_PW, "new_password": "yangiParol123"})
    assert _login(client, DEMO_PHONE, "yangiParol123").status_code == 401
    assert _login(client, DEMO_PHONE, DEMO_PW).status_code == 200


# -- 3. logout NO-OP: boshqa sessiyalar uzilmaydi -----------------------------
def test_demo_logout_boshqa_sessiyani_uzmaydi(client, demo):
    a = _tok(client, DEMO_PHONE, DEMO_PW)
    b = _tok(client, DEMO_PHONE, DEMO_PW)
    r = client.post("/api/v1/auth/logout", headers=a)
    assert r.status_code == 200 and r.json().get("demo") is True
    # ikkinchi odamning sessiyasi TIRIK qolishi SHART (umumiy hisob!)
    assert client.get("/api/v1/auth/me", headers=b).status_code == 200
    assert client.get("/api/v1/auth/me", headers=a).status_code == 200


# -- 4. Oddiy mijoz yo'li buzilmaydi ------------------------------------------
def test_oddiy_xodim_logout_sessiyani_bekor_qiladi(client, demo):
    h = _tok(client, ODDIY_PHONE, ODDIY_PW)
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_oddiy_xodim_parolni_ozgartiradi(client, demo):
    h = _tok(client, ODDIY_PHONE, ODDIY_PW)
    r = client.post("/api/v1/auth/password", headers=h,
                    json={"old_password": ODDIY_PW, "new_password": "YangiOddiy456"})
    assert r.status_code == 200, r.text
    assert _login(client, ODDIY_PHONE, "YangiOddiy456").status_code == 200
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post("/api/v1/auth/password", headers=h2,
                       json={"old_password": "YangiOddiy456", "new_password": ODDIY_PW}
                       ).status_code == 200


# -- 5. Tezlik cheklovi: umumiy hisob o'z-o'ziga DoS qilmasin -----------------
def _xato_urinishlar(client, phone, n=14):
    """Har urinish BOSHQA IP'dan — IP qatlami (10/300) ataylab ishga tushmaydi."""
    kodlar = []
    for i in range(n):
        kodlar.append(_login(client, phone, "butunlayXato!", ip=f"91.200.10.{10 + i}").status_code)
    return kodlar


def test_demo_telefoni_hisob_cheklovidan_ozod(client, demo):
    kodlar = _xato_urinishlar(client, DEMO_PHONE)
    assert 429 not in kodlar, f"demo telefoni bloklandi: {kodlar}"
    # va to'g'ri parol HALI HAM ishlaydi (demo hamma uchun ochiq qoladi)
    assert _login(client, DEMO_PHONE, DEMO_PW, ip="91.200.10.99").status_code == 200


def test_oddiy_telefon_hisob_cheklovida_qoladi(client, demo):
    kodlar = _xato_urinishlar(client, SEED_ADMIN)
    assert 429 in kodlar, f"oddiy telefon bloklanmadi: {kodlar}"


# -- 6. Imtiyoz o'g'irlanmasin ------------------------------------------------
def test_belgi_nomuvofiq_telefonga_imtiyoz_bermaydi(client, demo):
    """Belgidagi telefon xodimning HAQIQIY telefoni bo'lmasa — imtiyoz YO'Q."""
    from app.models.settings import Setting
    db = _db()
    try:
        row = db.query(Setting).filter(Setting.key == PD.PUBLIC_DEMO_KEY).first()
        row.value = {"employee_id": str(demo["id"]), "phone": SEED_ADMIN}
        db.commit()
        PD.reset_phones_cache()
        assert SEED_ADMIN not in PD.demo_login_phones(db)
        assert DEMO_PHONE not in PD.demo_login_phones(db)
    finally:
        db.close()
        PD.reset_phones_cache()


def test_belgi_faqat_ozi_nomidagi_xodimni_bloklaydi(client, demo):
    """Belgi BOR, lekin oddiy xodim yozuv amallarini AVVALGIDEK bajaradi."""
    h = _tok(client, ODDIY_PHONE, ODDIY_PW)
    r = client.post("/api/v1/customers", json={"full_name": "Demo darvoza testi"}, headers=h)
    assert r.status_code in (200, 201), r.text
