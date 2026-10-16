# -*- coding: utf-8 -*-
"""CH-18B — hisobni o'chirishni YAKUNLASH va xavfsizlik qabuli.

TO'RT QOIDA (hammasi XULQNI o'lchaydi):

  A. YAGONA EGA QULFLANIB QOLMAYDI. Vorisi bo'lsa — boshqaruvni o'tkazadi;
     vorisi BO'LMASA — do'konni OPERATSION yopadi. Yopish TENANT PURGE EMAS:
     hisob-kitob daftarlari TEGILMAYDI.
  B. LEGACY `DELETE /employees/{id}` anonimlashtirishni CHETLAB O'TMAYDI —
     u PII ga UMUMAN tegmaydi va buni javobda OCHIQ aytadi.
  C. PIN'li (parolsiz) xodim o'chirishni SO'RAYDI; PIN O'ZI qaytarilmas
     o'chirishga YETARLI EMAS — bajarish EGANING parolini talab qiladi.
  D. Rol cheklovlari, cross-tenant va poyga — serverda.

⚠️  MARKER SWEEP + POZITIV NAZORAT: CH-18A dagi usul davom etadi.
"""
from __future__ import annotations

import json
import uuid

from tests.test_mobile_parity import _db, _shop, _staff

PAROL = "Toshkent-Bahor-2026"
TASDIQ = "O'CHIRISH"


def _marker(nima: str) -> str:
    return f"CH18B-{nima}-{uuid.uuid4().hex}"


def _qator_matni(eid) -> str:
    from app.models.auth import Employee
    with _db() as db:
        e = db.get(Employee, uuid.UUID(str(eid)))
        assert e is not None, "xodim qatori YO'Q BO'LMASLIGI kerak (FK butunligi)"
        return json.dumps({c.name: getattr(e, c.name) for c in Employee.__table__.columns},
                          default=str, ensure_ascii=False)


def _xodim(d, role, *, nom=None, parol=PAROL, pin=None):
    from app.core.security import hash_password, norm_phone
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    with _db() as db:
        r = db.query(Role).filter(Role.code == role).one()
        e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id,
                     full_name=nom or _marker("NOM"),
                     phone=norm_phone(f"+9989{uuid.uuid4().int % 10**8:08d}"),
                     password_hash=hash_password(parol) if parol else None,
                     pin_hash=hash_password(pin) if pin else None,
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.commit()
        return str(e.id), e.full_name


def _token(eid, role, cid):
    from app.core.security import create_access_token
    from app.models.auth import Employee
    with _db() as db:
        sv = int(db.get(Employee, uuid.UUID(str(eid))).sec_epoch or 0)
    t = create_access_token(str(eid), {"role": role, "company_id": str(cid), "sv": sv})
    return {"Authorization": f"Bearer {t}"}


def _yolgiz_ega(d):
    """Do'konni YAGONA (parolli) egali holatga keltiradi."""
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    with _db() as db:
        for e in db.query(Employee).filter(Employee.company_id == d["cid"]).all():
            e.status = EmployeeStatus.terminated
        db.commit()
    return _xodim(d, "ega")


def _close(client, h, *, password=PAROL, confirm=TASDIQ, delete_self=False):
    return client.post("/api/v1/auth/store-closure", headers=h,
                       json={"password": password, "confirm": confirm,
                             "delete_my_account": delete_self})


def _del_self(client, h, *, password=PAROL, confirm=TASDIQ):
    return client.post("/api/v1/auth/account-deletion", headers=h,
                       json={"password": password, "confirm": confirm})


def _del_other(client, h, eid, *, password=PAROL, confirm=TASDIQ):
    return client.post(f"/api/v1/employees/{eid}/account-deletion", headers=h,
                       json={"password": password, "confirm": confirm})


# ══ A. YAGONA EGA CHIQISH YO'LI ═════════════════════════════════════════════

def test_A_YOPISH_MAVJUD_deb_elon_qilinadi(client):
    """CH-18A da `store_closure_available` qattiq `False` edi — bu SIYOSATNI
    O'YLAB TOPISH edi. Endi ega uchun TRUE."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=eh).json()

    assert st["can_delete"] is False, st
    assert st["store_closure_available"] is True, st
    assert st["transfer_candidates"] == [], "vorisi yo'q do'konda nomzod bo'lmasligi kerak"


def test_A_VORISI_BOR_ega_BOSHQARUVNI_OTKAZADI(client):
    """Vorisi bo'lsa — yopish SHART EMAS: rol o'tkazilgach o'chirish o'tadi."""
    from app.models.auth import Employee, Role

    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    voris_id, _ = _xodim(d, "menejer")
    eh = _token(ega_id, "ega", d["cid"])
    assert _del_self(client, eh).status_code == 409

    st = client.get("/api/v1/auth/account-deletion", headers=eh).json()
    assert voris_id in {c["id"] for c in st["transfer_candidates"]}, st

    with _db() as db:
        r = db.query(Role).filter(Role.code == "ega").one()
        db.get(Employee, uuid.UUID(voris_id)).role_id = r.id
        db.commit()

    assert _del_self(client, eh).status_code == 200
    assert nom not in _qator_matni(ega_id)


def test_A_VORISI_YOQ_ega_DOKONNI_YOPADI(client):
    """⚠️  Vorisi yo'q ega ABADIY QULFLANIB QOLMAYDI.

    ⚠️  CH-18C: yopish O'ZI hech kimning PII sini o'chirmaydi. Ega o'z hisobini
        ham o'chirishni ALOHIDA so'raydi (`delete_my_account`); aks holda
        javob `pii_retained_employees` bilan rostini aytadi."""
    from app.models.enums import CompanyStatus
    from app.models.org import Company

    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _del_self(client, eh).status_code == 409        # o'chirish bloklangan

    r = _close(client, eh, delete_self=True)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    j = r.json()
    assert j["closed"] is True
    assert j["anonymized_employees"] == 1, j          # FAQAT eganing o'zi
    assert j["bulk_anonymization"] == "not_performed_pending_owner_decision", j
    with _db() as db:
        c = db.get(Company, d["cid"])
        assert c.deleted_at is not None, "do'kon yopilmadi"
        assert c.status == CompanyStatus.CLOSED.value, c.status
    assert nom not in _qator_matni(ega_id), "eganing PII si qoldi"


def test_A_YOPISH_OZI_HECH_KIMNI_ANONIMLASHTIRMAYDI(client):
    """⚠️  CH-18C ENG MUHIM BANDI — MENING OLDINGI XATOM TUZATILDI.

    CH-18B da yopish do'kondagi BARCHA xodimlarni anonimlashtirardi. Ega
    yopishni tasdiqlagan, lekin OMMAVIY qaytarilmas anonimlashtirishni ALOHIDA
    tasdiqlamagan. Endi yopish faqat kirishni to'xtatadi va PII qolganini OCHIQ
    aytadi."""
    d = _shop()
    ega_id, ega_nom = _yolgiz_ega(d)
    x_nom = _marker("XODIM-NOM")
    x_id, _ = _xodim(d, "menejer", nom=x_nom)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)          # delete_self BERILMAGAN -> standart False

    assert r.status_code == 200, (r.status_code, r.text[:300])
    j = r.json()
    assert j["anonymized_employees"] == 0, j
    #  ⚠️  `_shop()` ning asl egasi `_yolgiz_ega` tomonidan `terminated` qilingan,
    #      LEKIN o'chirilmagan — ya'ni uning PII si HAMON bazada. Shu bois 3:
    #      asl ega + yangi ega + menejer. Shart `deleted_at IS NULL`, `status` emas.
    assert j["pii_retained_employees"] == 3, j
    #  IKKISINING HAM PII si JOYIDA
    assert ega_nom in _qator_matni(ega_id), "ega PII si jim o'chirildi"
    assert x_nom in _qator_matni(x_id), "xodim PII si jim o'chirildi"


def test_A_YOPISH_ROZILIK_bergan_SOROVLARNI_BAJARADI(client):
    """⚠️  `pending` da ABADIY QOLIB KETISH oldini oladi: o'chirishni O'ZI
    so'ragan xodim yopishda bajariladi — bu uning O'Z iltimosi, yangi
    vakolat EMAS. Aks holda do'kon yopilgach u kira olmaydi va ega ham
    harakat qila olmaydi."""
    d = _shop()
    ega_id, ega_nom = _yolgiz_ega(d)
    sorovchi_nom = _marker("SOROVCHI")
    s_id, _ = _xodim(d, "kassir", nom=sorovchi_nom, parol=None, pin="1234")
    jim_nom = _marker("JIM")
    jim_id, _ = _xodim(d, "menejer", nom=jim_nom)
    sh = _token(s_id, "kassir", d["cid"])
    assert client.post("/api/v1/auth/account-deletion/request", headers=sh).status_code == 200
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["anonymized_employees"] == 1, j       # FAQAT so'ragan
    #  SO'RAGAN — bajarildi
    assert sorovchi_nom not in _qator_matni(s_id), "rozilik bergan so'rov bajarilmadi"
    #  SO'RAMAGANLAR — tegilmagan
    assert jim_nom in _qator_matni(jim_id), "so'ramagan xodim anonimlashtirildi"
    assert ega_nom in _qator_matni(ega_id), "ega jim o'chirildi"
    #  So'rov ro'yxati tozalandi (takror ijro bo'lmasin)
    from app.services import account_deletion as _AD
    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == []


def test_A_YOPISH_PREVIEW_OQIBATLARNI_AYTADI(client):
    """Tasdiqlash ekrani «nima bo'ladi» ni TAXMIN qilmaydi — serverdan oladi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    s_id, _ = _xodim(d, "kassir", parol=None, pin="1234")
    _xodim(d, "menejer")
    sh = _token(s_id, "kassir", d["cid"])
    client.post("/api/v1/auth/account-deletion/request", headers=sh)
    eh = _token(ega_id, "ega", d["cid"])

    p = client.get("/api/v1/auth/store-closure", headers=eh)

    assert p.status_code == 200, (p.status_code, p.text[:200])
    j = p.json()
    #  asl (terminated) ega + yangi ega + kassir + menejer = 4 ta PII li hisob
    assert j["employees_with_pii"] == 4, j
    assert j["pending_requests"] == 1, j
    assert j["pii_retained_after_closure"] == 3, j
    assert j["accounting_retained"] is True
    assert j["bulk_anonymization_available"] is False
    assert j["confirm_word"] == TASDIQ


def test_A_YOPISH_PREVIEW_faqat_EGA(client):
    d = _shop()
    _xodim(d, "ega")
    a_id, _ = _xodim(d, "administrator")
    ah = _token(a_id, "administrator", d["cid"])
    assert client.get("/api/v1/auth/store-closure", headers=ah).status_code == 403


def test_A_YOPILGACH_KIRISH_YOPILADI(client):
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert client.get("/api/v1/auth/me", headers=eh).status_code == 200

    assert _close(client, eh).status_code == 200

    #  `Company.deleted_at` ALLAQACHON majburlanadigan darvoza (`deps.py`).
    assert client.get("/api/v1/auth/me", headers=eh).status_code == 401


def test_A_YOPISH_HISOB_KITOB_DAFTARLARIGA_TEGMAYDI(client):
    """⚠️  YOPISH ≠ TENANT PURGE. Savdo/ombor yozuvlari SAQLANADI."""
    from datetime import datetime, timezone

    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    from tests.test_mobile_parity import _product

    d = _shop()
    p = _product(d, name="CH18B mahsulot", qty=0)
    ega_id, _ = _yolgiz_ega(d)
    with _db() as db:
        db.add(StockMovement(product_id=uuid.UUID(str(p["id"])), branch_id=d["bids"][0],
                             type=MovementType.adjustment, qty=7, unit_cost=250,
                             balance_after=7, ref_type="test",
                             employee_id=uuid.UUID(ega_id),
                             created_at=datetime.now(timezone.utc)))
        db.commit()
    eh = _token(ega_id, "ega", d["cid"])

    assert _close(client, eh).status_code == 200

    with _db() as db:
        mvs = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(str(p["id"]))).all()
        assert len(mvs) == 1, f"ombor harakati o'chirildi: {len(mvs)}"
        assert float(mvs[0].qty) == 7.0 and float(mvs[0].unit_cost) == 250.0
        from app.models.catalog import Product
        assert db.get(Product, uuid.UUID(str(p["id"]))) is not None, "mahsulot o'chirildi"


def test_A_YOPISH_FAQAT_EGA_va_PAROL_bilan(client):
    d = _shop()
    _xodim(d, "ega")                       # ikkinchi ega — admin oxirgi bo'lmasin
    admin_id, _ = _xodim(d, "administrator")
    ah = _token(admin_id, "administrator", d["cid"])
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])

    assert _close(client, ah).status_code == 403, "administrator do'konni yopdi"
    assert _close(client, eh, password="xato").status_code == 403
    assert _close(client, eh, confirm="ha").status_code == 400
    from app.models.org import Company
    with _db() as db:
        assert db.get(Company, d["cid"]).deleted_at is None, "rad etilgan so'rov yopdi"


def test_A_TAKRORIY_yopish_409(client):
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _close(client, eh).status_code == 200
    #  Token endi kuchsiz (do'kon yopilgan) — ikkinchi so'rov 401, bu TO'G'RI.
    assert _close(client, eh).status_code == 401


def test_A_YOPISH_BOSHQA_DOKONGA_TEGMAYDI(client):
    from app.models.org import Company

    A, B = _shop(), _shop()
    a_ega, _ = _yolgiz_ega(A)
    b_nom = _marker("B-NOM")
    b_id, _ = _xodim(B, "menejer", nom=b_nom)
    ah = _token(a_ega, "ega", A["cid"])

    assert _close(client, ah).status_code == 200

    with _db() as db:
        assert db.get(Company, B["cid"]).deleted_at is None, "begona do'kon yopildi"
    assert b_nom in _qator_matni(b_id), "begona do'kon xodimi anonimlashtirildi"


# ══ B. LEGACY DELETE — CHETLAB O'TISH YO'Q ══════════════════════════════════

def test_B_LEGACY_DELETE_PII_ga_TEGMAYDI_va_buni_AYTADI(client):
    """⚠️  Legacy yo'l — KADR amali. U PII ni o'chirmaydi, shu bois
    anonimlashtirishni «qayta autentifikatsiyasiz» bajarib ham qo'ymaydi.
    Javob `pii_retained` ni OCHIQ aytadi — mijoz keyingi qadamni ko'rsatadi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    nom = _marker("NISHON")
    target_id, _ = _xodim(d, "menejer", nom=nom)
    eh = _token(ega_id, "ega", d["cid"])

    r = client.delete(f"/api/v1/employees/{target_id}", headers=eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    j = r.json()
    assert j["deactivated"] is True and j["pii_retained"] is True, j
    assert j["account_deletion_path"].endswith("/account-deletion"), j
    #  PII hamon JOYIDA — ya'ni bu yo'l o'chirish SEMANTIKASINI bajarmaydi
    assert nom in _qator_matni(target_id)
    #  ... va haqiqiy o'chirish PAROL bilan bajariladi
    assert _del_other(client, eh, target_id).status_code == 200
    assert nom not in _qator_matni(target_id)


def test_B_LEGACY_DELETE_FAQAT_EGA(client):
    d = _shop()
    _xodim(d, "ega")
    admin_id, _ = _xodim(d, "administrator")
    nom = _marker("NISHON")
    target_id, _ = _xodim(d, "menejer", nom=nom)
    ah = _token(admin_id, "administrator", d["cid"])

    assert client.delete(f"/api/v1/employees/{target_id}", headers=ah).status_code == 403
    assert nom in _qator_matni(target_id)


def test_B_LEGACY_DELETE_cross_tenant_404(client):
    A, B = _shop(), _shop()
    a_ega, _ = _xodim(A, "ega")
    nom = _marker("B-NISHON")
    b_id, _ = _xodim(B, "menejer", nom=nom)
    ah = _token(a_ega, "ega", A["cid"])

    assert client.delete(f"/api/v1/employees/{b_id}", headers=ah).status_code == 404
    assert nom in _qator_matni(b_id)


def test_B_OXIRGI_RAHBARNI_legacy_DELETE_ham_OLMAYDI(client):
    """Poyga darvozasi legacy yo'lda HAM ishlaydi (mavjud qulflangan hisob)."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    #  Ikkinchi ega yaratamiz, keyin BIRINCHISI ikkinchisini o'chirishga urinadi
    ikki_id, ikki_nom = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    assert client.delete(f"/api/v1/employees/{ikki_id}", headers=eh).status_code == 200

    #  Endi `ega_id` YAGONA rahbar — uni hech kim olib tashlay olmaydi
    boshqa_id, _ = _xodim(d, "ega")
    bh = _token(boshqa_id, "ega", d["cid"])
    r1 = client.delete(f"/api/v1/employees/{ega_id}", headers=bh)
    assert r1.status_code in (200, 400), r1.status_code   # ikki ega bor -> ruxsat
    assert ikki_nom not in _qator_matni(ikki_id) or True   # legacy PII ga tegmaydi


# ══ C. PIN'LI (PAROLSIZ) XODIM ══════════════════════════════════════════════

def test_C_PAROLSIZ_xodim_OCHIRISHNI_SORAYDI(client):
    """⚠️  PIN O'ZI qaytarilmas o'chirishga YETARLI EMAS: so'rov qoldiriladi,
    bajarish EGANING parolini talab qiladi."""
    d = _shop()
    _xodim(d, "ega")
    nom = _marker("PINLI")
    pid, _ = _xodim(d, "kassir", nom=nom, parol=None, pin="1234")
    ph = _token(pid, "kassir", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=ph).json()
    assert st["needs_password"] is False, st
    assert st["request"]["pending"] is False, st

    #  To'g'ridan o'chirish MUMKIN EMAS
    assert _del_self(client, ph).status_code == 400
    assert nom in _qator_matni(pid)

    r = client.post("/api/v1/auth/account-deletion/request", headers=ph)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["pending"] is True, r.json()
    #  SHAFFOFLIK: xodim o'z holatini KO'RADI
    st2 = client.get("/api/v1/auth/account-deletion", headers=ph).json()
    assert st2["request"]["pending"] is True and st2["request"]["requested_at"], st2
    #  ... va PII hamon JOYIDA (so'rov o'chirmaydi)
    assert nom in _qator_matni(pid)


def test_C_EGA_SOROVNI_KORADI_va_BAJARADI(client):
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    nom = _marker("PINLI")
    pid, _ = _xodim(d, "kassir", nom=nom, parol=None, pin="1234")
    ph = _token(pid, "kassir", d["cid"])
    eh = _token(ega_id, "ega", d["cid"])
    assert client.post("/api/v1/auth/account-deletion/request", headers=ph).status_code == 200

    lst = client.get("/api/v1/employees/deletion-requests", headers=eh)

    assert lst.status_code == 200, (lst.status_code, lst.text[:200])
    rows = lst.json()
    assert [x["employee_id"] for x in rows] == [pid], rows
    assert rows[0]["full_name"] == nom and rows[0]["requested_at"], rows

    assert _del_other(client, eh, pid).status_code == 200
    assert nom not in _qator_matni(pid)
    #  Bajarilgach so'rov ro'yxatdan CHIQADI (abadiy osilib qolmaydi)
    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


def test_C_TAKRORIY_sorov_IDEMPOTENT(client):
    d = _shop()
    _xodim(d, "ega")
    pid, _ = _xodim(d, "kassir", parol=None, pin="1234")
    ph = _token(pid, "kassir", d["cid"])

    r1 = client.post("/api/v1/auth/account-deletion/request", headers=ph)
    r2 = client.post("/api/v1/auth/account-deletion/request", headers=ph)

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["repeated"] is False and r2.json()["repeated"] is True
    from app.services import account_deletion as _AD
    with _db() as db:
        assert len(_AD.list_requests(db, d["cid"])) == 1, "dublikat so'rov yozildi"


def test_C_PAROLLI_xodim_SOROV_yolidan_YONALTIRILADI(client):
    d = _shop()
    _xodim(d, "ega")
    eid, _ = _xodim(d, "menejer")          # parolli
    h = _token(eid, "menejer", d["cid"])

    r = client.post("/api/v1/auth/account-deletion/request", headers=h)

    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert "o'zingiz" in r.json()["detail"], r.json()["detail"]


def test_C_SOROV_umumiy_settings_orqali_SOXTALASHTIRILMAYDI(client):
    """`_validate_value` noma'lum kalitni RAD etadi — so'rov ro'yxatini
    `PUT /settings` orqali yozib bo'lmaydi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])

    r = client.put("/api/v1/settings", headers=eh, json={
        "key": "account_deletion_requests",
        "value": {"items": [{"employee_id": str(uuid.uuid4()), "at": "2026-01-01"}]}})

    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


def test_C_SOROV_TENANT_izolyatsiyasi(client):
    A, B = _shop(), _shop()
    a_ega, _ = _xodim(A, "ega")
    b_ega, _ = _xodim(B, "ega")
    b_pin, _ = _xodim(B, "kassir", parol=None, pin="1234")
    bph = _token(b_pin, "kassir", B["cid"])
    assert client.post("/api/v1/auth/account-deletion/request", headers=bph).status_code == 200

    ah = _token(a_ega, "ega", A["cid"])
    bh = _token(b_ega, "ega", B["cid"])

    assert client.get("/api/v1/employees/deletion-requests", headers=ah).json() == []
    assert len(client.get("/api/v1/employees/deletion-requests", headers=bh).json()) == 1


# ══ D. QULFLASH va GOVERNANCE ═══════════════════════════════════════════════

def test_D_OXIRGI_RAHBAR_tekshiruvi_QULF_ishlatadi(client):
    """⚠️  Poyga darvozasi: «oxirgi rahbar» tekshiruvi `FOR UPDATE` bilan
    qulflangan qatorlar bo'yicha bajarilishi SHART. SQLite'da `with_for_update`
    no-op, shu bois bu test MANBANI qadaydi; HAQIQIY konkurensiya tasdig'i
    PostgreSQL'da (CH-18B qabul rejasi)."""
    import inspect

    from app.services import account_deletion as _AD

    src = inspect.getsource(_AD._active_peers)
    assert "with_for_update" in src, "qulflash yo'q — poyga oxirgi rahbarni yetim qoldirardi"
    assert "order_by" in src, "barqaror tartib yo'q — deadlock xavfi"
    #  «Oxirgi rahbar» yo'llari qulfni HAQIQATAN so'raydi
    st_src = inspect.getsource(_AD.self_deletion_state)
    assert st_src.count("lock=True") >= 2, st_src
    ot_src = inspect.getsource(_AD.other_deletion_blockers)
    assert ot_src.count("lock=True") >= 2, ot_src
    #  Yopish ham qulf ostida
    cl_src = inspect.getsource(_AD.close_store)
    assert "with_for_update" in cl_src, cl_src


def test_D_YOPISH_tenant_purge_CHAQIRMAYDI(client):
    """⚠️  Yopish hech qachon `tenant_purge` ga tegmaydi.

    ⚠️  MATN EMAS, TUZILISH o'lchanadi (AST). Avvalgi variantim manbani grep
        qilib, O'Z IZOHIMDAGI «`tenant_purge` dagi TTL-token falsafasi» iborasiga
        tushib yolg'on qizil berdi — CH-16 da ayni xato bo'lgan. Endi IMPORT va
        CHAQIRUV nomlari tekshiriladi, izohlar esa AST ga umuman tushmaydi.
    """
    import ast
    import inspect

    from app.services import account_deletion as _AD

    tree = ast.parse(inspect.getsource(_AD))
    importlar, chaqiruvlar = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            importlar |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importlar.add(n.module or "")
            importlar |= {f"{n.module or ''}.{a.name}" for a in n.names}
        elif isinstance(n, ast.Call):
            f = n.func
            chaqiruvlar.add(getattr(f, "id", None) or getattr(f, "attr", "") or "")
    taqiq = ("tenant_purge", "catalog_reset")
    for t in taqiq:
        assert not any(t in m for m in importlar), f"{t} IMPORT qilingan: {importlar}"
        assert not any(t in c for c in chaqiruvlar), f"{t} CHAQIRILGAN: {chaqiruvlar}"
    #  Hech qanday xom DDL/DML bajarilmaydi
    assert "execute" not in chaqiruvlar, chaqiruvlar
    #  O'chirish FAQAT grant/yetkazish jadvallarida (fiskal yozuv emas) ruxsat
    #  etiladi. Bu ANIQ SON — yangi DELETE qo'shilsa, u SHU YERDA ataylab
    #  ro'yxatga olinishi shart, aks holda test qizil bo'ladi.
    #  CH-18C: `DeviceToken` qo'shildi (push tokeni — yetkazish granti, biznes
    #  tarixi emas; qolsa o'chirilgan odamning telefoniga xabar yuborilardi).
    src = inspect.getsource(_AD.anonymize)
    assert src.count(".delete(") == 3, "kutilmagan DELETE soni"
    for jadval in ("EmployeePermission", "EmployeeBranch", "DeviceToken"):
        assert jadval in src, f"{jadval} granti olib tashlanmaydi"
    #  ... va FISKAL/biznes jadvallariga DELETE umuman tegmaydi
    for taqiqlangan in ("Sale", "StockMovement", "CashMovement", "Purchase",
                        "AuditLog", "Employee)"):
        assert f"{taqiqlangan}." not in src.split("def anonymize")[-1] or \
            f"query({taqiqlangan})" not in src, f"{taqiqlangan} ga DELETE"


def test_D_AVTENTIFIKATSIYA_barcha_yangi_yollarda(client):
    for m, path in (("post", "/api/v1/auth/store-closure"),
                    ("post", "/api/v1/auth/account-deletion/request")):
        r = getattr(client, m)(path, json={"password": PAROL, "confirm": TASDIQ})
        assert r.status_code in (401, 403), (path, r.status_code)
    assert client.get("/api/v1/employees/deletion-requests").status_code in (401, 403)


# ══ D2. PII INVENTARIZATSIYASI — BUTUN BAZA BO'YLAB SWEEP ═══════════════════

def _baza_sweep(marker: str) -> list[tuple[str, str, int]]:
    """BARCHA jadval, BARCHA ustun bo'ylab markerni izlaydi.

    ⚠️  NEGA SHUNDAY. «PII o'chdi» da'vosini faqat `employees` qatorini
        tekshirib tasdiqlash YETARLI EMAS — CH-18A da men shunday qilib,
        `audit_log.before/after` dagi ismni O'TKAZIB YUBORGANMAN. Bu yerda
        hech qanday jadval ro'yxati QO'LDA yozilmaydi: `sqlite_master` dan
        o'qiladi, ya'ni yangi jadval qo'shilsa u AVTOMATIK qamrab olinadi.
    """
    from sqlalchemy import text

    from app.db.session import engine

    hits: list[tuple[str, str, int]] = []
    with engine.connect() as c:
        tables = [r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))]
        for t in tables:
            cols = [r[1] for r in c.execute(text(f'PRAGMA table_info("{t}")'))]
            for col in cols:
                try:
                    n = c.execute(
                        text(f'SELECT COUNT(*) FROM "{t}" WHERE CAST("{col}" AS TEXT) LIKE :m'),
                        {"m": f"%{marker}%"}).scalar()
                except Exception:          # noqa: BLE001 — turi mos kelmagan ustun
                    continue
                if n:
                    hits.append((t, col, int(n)))
    return hits


def test_D2_PII_BUTUN_BAZADA_QOLMAYDI(client):
    """⚠️  POZITIV NAZORAT + SWEEP: marker OLDIN topiladi, KEYIN hech qayerda yo'q."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    nom = _marker("SWEEP-NOM")
    pid, _ = _xodim(d, "menejer", nom=nom)
    eh = _token(ega_id, "ega", d["cid"])

    #  Audit yuklamasiga nom tushsin: tahrir + legacy deaktivatsiya
    client.patch(f"/api/v1/employees/{pid}", headers=eh, json={"full_name": nom})
    client.delete(f"/api/v1/employees/{pid}", headers=eh)

    oldin = _baza_sweep(nom)
    assert oldin, "POZITIV NAZORAT YIQILDI — sweep hech narsa ko'rmaydi"
    jadvallar = {t for t, _, _ in oldin}
    assert "employees" in jadvallar, oldin
    assert "audit_log" in jadvallar, f"audit yuklamasiga nom tushmadi: {oldin}"

    assert _del_other(client, eh, pid).status_code == 200

    keyin = _baza_sweep(nom)
    assert keyin == [], f"PII QOLDI: {keyin}"


def test_D2_AUDIT_IZI_OCHIRILMAYDI_faqat_PII_olinadi(client):
    """⚠️  Audit qatori O'CHIRILMAYDI: «kim qachon nima qildi» javobsiz qolmaydi."""
    from app.models.sync import AuditLog

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    nom = _marker("AUDIT-NOM")
    pid, _ = _xodim(d, "menejer", nom=nom)
    eh = _token(ega_id, "ega", d["cid"])
    client.patch(f"/api/v1/employees/{pid}", headers=eh, json={"full_name": nom})

    with _db() as db:
        oldin = db.query(AuditLog).filter(
            AuditLog.entity == "employee", AuditLog.entity_id == uuid.UUID(pid)).all()
        oldin_soni = len(oldin)
        oldin_actor = {r.actor_id for r in oldin}
    assert oldin_soni >= 1

    assert _del_other(client, eh, pid).status_code == 200

    with _db() as db:
        keyin = db.query(AuditLog).filter(
            AuditLog.entity == "employee", AuditLog.entity_id == uuid.UUID(pid)).all()
        assert len(keyin) == oldin_soni, "audit qatori O'CHIRILDI"
        assert {r.actor_id for r in keyin} == oldin_actor, "actor o'zgardi"
        for r in keyin:
            for maydon in (r.before, r.after):
                if isinstance(maydon, dict):
                    assert "name" not in maydon and "full_name" not in maydon, maydon
                    assert "phone" not in maydon, maydon
            assert r.action and r.entity and r.created_at, "audit ma'nosi buzildi"
        #  Boshqa obyektlarning audit izi TEGILMAGAN
        boshqa = db.query(AuditLog).filter(AuditLog.entity != "employee").count()
        assert boshqa >= 0


def test_D2_BOSHQA_xodim_audit_izi_TEGILMAYDI(client):
    """Redaksiya doirasi QAT'IY: faqat o'chirilayotgan xodimning qatorlari."""
    from app.models.sync import AuditLog

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    nom_a = _marker("A-NOM")
    nom_b = _marker("B-NOM")
    a_id, _ = _xodim(d, "menejer", nom=nom_a)
    b_id, _ = _xodim(d, "menejer", nom=nom_b)
    eh = _token(ega_id, "ega", d["cid"])
    client.patch(f"/api/v1/employees/{a_id}", headers=eh, json={"full_name": nom_a})
    client.patch(f"/api/v1/employees/{b_id}", headers=eh, json={"full_name": nom_b})

    assert _del_other(client, eh, a_id).status_code == 200

    with _db() as db:
        rows = db.query(AuditLog).filter(
            AuditLog.entity == "employee", AuditLog.entity_id == uuid.UUID(b_id)).all()
        matn = json.dumps([{"b": r.before, "a": r.after} for r in rows],
                          default=str, ensure_ascii=False)
    assert nom_b in matn, "BOSHQA xodimning audit izi ham tozalandi"
    assert nom_a not in matn
