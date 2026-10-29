# -*- coding: utf-8 -*-
"""CH-18A — HISOBNI O'CHIRISH: shaxsiy ma'lumot QAYTARILMAS olib tashlanadi.

Apple Guideline 5.1.1(v): hisob yaratgan ilova foydalanuvchiga ILOVA ICHIDAN
hisobni o'chirishni boshlash imkonini berishi SHART.

UCHTA QOIDA (hammasi XULQNI o'lchaydi):

  1. O'Z hisobi: parol qayta kiritiladi + tasdiq so'zi -> PII QAYTA YOZILADI,
     sessiyalar bekor qilinadi (`sec_epoch`), biznes tarixi TEGILMAYDI.
  2. BOSHQA xodim: FAQAT `ega`. `administrator` boshqani o'chira OLMAYDI (403)
     va bu SERVERDA majburlanadi — soxta token roli bilan chetlab o'tilmaydi.
  3. OXIRGI rahbar: rad etilmaydi-yu, TANLOV beriladi (o'tkazish nomzodlari).

⚠️  MARKER SWEEP. «PII o'chdi» degan da'vo kalit nomini tekshirib emas,
    UNIKAL QIYMATNI butun `employees` qatori bo'ylab qidirib tasdiqlanadi
    (`_qator_matni`). Aks holda refaktoring maydonni ko'chirsa sinov jim
    qolib o'lardi — CH-15B da aynan shunday teshik topilgan.

⚠️  POZITIV NAZORAT MAJBURIY: o'chirishdan OLDIN marker TOPILISHI shart
    (`test_SWEEP_ozi_ishlaydi`), aks holda sweep hech narsa o'lchamagan bo'lardi.

⚠️  CROSS-TENANT. Parolli telefon GLOBAL noyob, PIN'li xodim esa AYNI telefon
    bilan boshqa do'konda ALOHIDA qator bo'lishi mumkin. O'chirish FAQAT shu
    do'kondagi a'zolikni oladi — `test_CROSS_TENANT_...` buni o'lchaydi.
"""
from __future__ import annotations

import json
import uuid

from tests.test_mobile_parity import _db, _shop, _staff

PAROL = "Toshkent-Bahor-2026"
TASDIQ = "O'CHIRISH"


def _marker(nima: str) -> str:
    return f"CH18A-{nima}-{uuid.uuid4().hex}"


def _qator_matni(eid) -> str:
    """`employees` qatorining BARCHA ustunlari — matn ko'rinishida (sweep uchun)."""
    from app.models.auth import Employee
    with _db() as db:
        e = db.get(Employee, uuid.UUID(str(eid)))
        assert e is not None, "xodim qatori YO'Q BO'LMASLIGI kerak (FK butunligi)"
        return json.dumps({c.name: getattr(e, c.name) for c in Employee.__table__.columns},
                          default=str, ensure_ascii=False)


def _xodim(d, role, *, nom=None, tel=None, parol=PAROL):
    """Parolli xodim — o'z hisobini o'chirish uchun parol SHART."""
    from app.core.security import hash_password, norm_phone
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    with _db() as db:
        r = db.query(Role).filter(Role.code == role).one()
        e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id,
                     full_name=nom or _marker("NOM"),
                     phone=norm_phone(tel or f"+9989{uuid.uuid4().int % 10**8:08d}"),
                     password_hash=hash_password(parol),
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.commit()
        return str(e.id), e.full_name, e.phone


def _token(eid, role, cid):
    from app.core.security import create_access_token
    with _db() as db:
        from app.models.auth import Employee
        e = db.get(Employee, uuid.UUID(str(eid)))
        sv = int(e.sec_epoch or 0)
    t = create_access_token(str(eid), {"role": role, "company_id": str(cid), "sv": sv})
    return {"Authorization": f"Bearer {t}"}


def _delete_self(client, h, *, password=PAROL, confirm=TASDIQ):
    return client.post("/api/v1/auth/account-deletion", headers=h,
                       json={"password": password, "confirm": confirm})


def _delete_other(client, h, eid, *, password=PAROL, confirm=TASDIQ):
    return client.post(f"/api/v1/employees/{eid}/account-deletion", headers=h,
                       json={"password": password, "confirm": confirm})


# ══ 1. O'Z HISOBINI O'CHIRISH ═══════════════════════════════════════════════

def test_SWEEP_ozi_ishlaydi_POZITIV_NAZORAT(client):
    """⚠️  MAJBURIY: o'chirishdan OLDIN marker TOPILISHI shart."""
    d = _shop()
    nom = _marker("NOM")
    eid, _, tel = _xodim(d, "menejer", nom=nom)
    matn = _qator_matni(eid)
    assert nom in matn, f"POZITIV NAZORAT YIQILDI — sweep ism ko'rmaydi: {matn[:300]}"
    assert tel in matn, "sweep telefonni ko'rmaydi"


def test_OZ_hisobini_ochiradi_PII_QAYTA_YOZILADI(client):
    d = _shop()
    nom = _marker("NOM")
    eid, _, tel = _xodim(d, "menejer", nom=nom)
    h = _token(eid, "menejer", d["cid"])
    assert nom in _qator_matni(eid)          # oldin BOR

    r = _delete_self(client, h)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["deleted"] is True and r.json()["repeated"] is False
    matn = _qator_matni(eid)
    assert nom not in matn, f"ISM qoldi: {matn[:300]}"
    assert tel not in matn, f"TELEFON qoldi: {matn[:300]}"
    from app.models.auth import Employee
    with _db() as db:
        e = db.get(Employee, uuid.UUID(eid))
        assert e.password_hash is None and e.pin_hash is None, "kredensial qoldi"
        assert e.phone is None
        assert e.deleted_at is not None
        assert e.full_name.startswith("O'chirilgan xodim #"), e.full_name
        assert int(e.sec_epoch) == 1, f"sessiya bekor qilinmadi: {e.sec_epoch}"


def test_OCHIRILGACH_TOKEN_DARHOL_KUCHSIZ(client):
    """`sec_epoch` oshgani uchun eski token 401 oladi — sessiya bekor qilindi."""
    d = _shop()
    eid, _, _ = _xodim(d, "menejer")
    h = _token(eid, "menejer", d["cid"])
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200   # oldin ishlaydi

    assert _delete_self(client, h).status_code == 200

    assert client.get("/api/v1/auth/me", headers=h).status_code == 401, "eski token hamon ishlaydi"


def test_PAROL_NOTOGRI_bolsa_HISOB_TEGILMAYDI(client):
    d = _shop()
    nom = _marker("NOM")
    eid, _, _ = _xodim(d, "menejer", nom=nom)
    h = _token(eid, "menejer", d["cid"])

    r = _delete_self(client, h, password="butunlay-boshqa-parol")

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert nom in _qator_matni(eid), "noto'g'ri parolda ham PII o'chdi"
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200, "sessiya buzildi"


def test_TASDIQ_SOZI_bolmasa_HISOB_TEGILMAYDI(client):
    d = _shop()
    nom = _marker("NOM")
    eid, _, _ = _xodim(d, "menejer", nom=nom)
    h = _token(eid, "menejer", d["cid"])

    for yomon in ("", "ha", "DELETE", "o'chirish"):
        r = _delete_self(client, h, confirm=yomon) if yomon else client.post(
            "/api/v1/auth/account-deletion", headers=h, json={"password": PAROL, "confirm": " "})
        assert r.status_code in (400, 422), (yomon, r.status_code)
    assert nom in _qator_matni(eid), "tasdiqsiz o'chirildi"


def test_TAKRORIY_sorov_IDEMPOTENT(client):
    d = _shop()
    eid, _, _ = _xodim(d, "menejer")
    h = _token(eid, "menejer", d["cid"])
    assert _delete_self(client, h).status_code == 200
    nom1 = _qator_matni(eid)

    #  Eski token endi kuchsiz — ikkinchi so'rov 401 bo'ladi, bu TO'G'RI xulq:
    #  o'chirilgan hisobdan yana o'chirish so'rovi kelmaydi.
    r2 = _delete_self(client, h)
    assert r2.status_code == 401, r2.status_code
    assert _qator_matni(eid) == nom1, "ikkinchi so'rov qatorni o'zgartirdi"


def test_PAROLSIZ_xodim_ANIQ_javob_oladi(client):
    """PIN'li (parolsiz) xodim parol bilan tasdiqlay olmaydi — jim 401 emas, ANIQ matn."""
    d = _shop()
    _, kid = _staff(d, "kassir")           # parolsiz yaratiladi
    h = _token(kid, "kassir", d["cid"])

    r = _delete_self(client, h)

    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert "parol yo'q" in r.json()["detail"], r.json()["detail"]


# ══ 2. RBAC — BOSHQA XODIMNI FAQAT EGA O'CHIRADI ════════════════════════════

def test_ADMINISTRATOR_boshqani_OCHIRA_OLMAYDI_403(client):
    """⚠️  ENG MUHIM RBAC BANDI (ega qarori). `administrator` roli «ALL»
    ruxsatga ega, shu bois `xodimlar.edit` ham bor — lekin SERVER rolni
    BAZADAN o'qib rad etadi."""
    d = _shop()
    admin_id, _, _ = _xodim(d, "administrator")
    nom = _marker("NISHON")
    target_id, _, _ = _xodim(d, "menejer", nom=nom)
    ah = _token(admin_id, "administrator", d["cid"])

    r1 = _delete_other(client, ah, target_id)
    r2 = client.delete(f"/api/v1/employees/{target_id}", headers=ah)

    assert r1.status_code == 403, (r1.status_code, r1.text[:200])
    assert r2.status_code == 403, (r2.status_code, r2.text[:200])
    assert nom in _qator_matni(target_id), "admin boshqa xodim PII sini o'chirdi"


def test_ADMINISTRATOR_OZ_hisobini_OCHIRA_OLADI(client):
    """Admin o'z hisobini o'chiradi — bu yo'l unga OCHIQ qoladi."""
    d = _shop()
    _xodim(d, "administrator")              # ikkinchi rahbar — oxirgi qolmasin
    admin_id, nom, _ = _xodim(d, "administrator")
    ah = _token(admin_id, "administrator", d["cid"])

    r = _delete_self(client, ah)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert nom not in _qator_matni(admin_id)


def test_EGA_boshqa_xodim_hisobini_OCHIRADI(client):
    d = _shop()
    nom = _marker("NISHON")
    target_id, _, tel = _xodim(d, "menejer", nom=nom)
    # `_shop()` egasi parolsiz — ega uchun parolli hisob yasaymiz
    ega_id, _, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])

    r = _delete_other(client, eh, target_id)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    matn = _qator_matni(target_id)
    assert nom not in matn and tel not in matn, f"PII qoldi: {matn[:300]}"


def test_EGA_parolsiz_yoki_tasdiqsiz_OCHIRA_OLMAYDI(client):
    """Ega ham QAYTA AUTENTIFIKATSIYA qiladi — token o'g'irlansa ham o'chmaydi."""
    d = _shop()
    nom = _marker("NISHON")
    target_id, _, _ = _xodim(d, "menejer", nom=nom)
    ega_id, _, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])

    assert _delete_other(client, eh, target_id, password="xato").status_code == 403
    assert _delete_other(client, eh, target_id, confirm="ha").status_code == 400
    assert nom in _qator_matni(target_id)


def test_NISHON_PAROLI_hech_qachon_SORALMAYDI(client):
    """⚠️  Ega nishonning parolini BILMASLIGI kerak: DTO'da bunday maydon YO'Q."""
    from app.api.v1.employees import OwnerAccountDeletionIn

    maydonlar = set(OwnerAccountDeletionIn.model_fields)
    assert maydonlar == {"password", "confirm"}, maydonlar
    # Nishon id'si ham tanada emas — URL'da (soxta tanadan o'chirishni oldini oladi)
    assert "employee_id" not in maydonlar and "target" not in maydonlar


def test_TENANT_izolyatsiyasi_begona_dokon_404(client):
    A, B = _shop(), _shop()
    nom = _marker("NISHON-B")
    b_target, _, _ = _xodim(B, "menejer", nom=nom)
    a_ega, _, _ = _xodim(A, "ega")
    ah = _token(a_ega, "ega", A["cid"])

    r = _delete_other(client, ah, b_target)

    assert r.status_code == 404, (r.status_code, r.text[:200])
    assert nom in _qator_matni(b_target), "begona do'kon xodimi o'chirildi"


def test_CROSS_TENANT_ayni_telefon_boshqa_dokonda_TEGILMAYDI(client):
    """⚠️  O'chirilayotgani — ODAMNING BITTA DO'KONDAGI A'ZOLIGI.

    Parolsiz (PIN'li) xodim AYNI telefon bilan ikki do'konda ALOHIDA qator
    bo'lishi mumkin (`ux_employees_phone_pw` faqat PAROLLI telefonni global
    noyob qiladi). Bir do'kondagi o'chirish ikkinchisiga TEGMASLIGI shart."""
    from app.core.security import hash_password, norm_phone
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus

    A, B = _shop(), _shop()
    tel = norm_phone(f"+9989{uuid.uuid4().int % 10**8:08d}")
    nom_a, nom_b = _marker("A-NOM"), _marker("B-NOM")
    ids = {}
    for tag, d, nom, parol in (("a", A, nom_a, PAROL), ("b", B, nom_b, None)):
        with _db() as db:
            r = db.query(Role).filter(Role.code == "menejer").one()
            e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id, full_name=nom,
                         phone=tel, password_hash=hash_password(parol) if parol else None,
                         pin_hash=None if parol else hash_password("1234"),
                         status=EmployeeStatus.active, sec_epoch=0)
            db.add(e); db.commit(); ids[tag] = str(e.id)

    h = _token(ids["a"], "menejer", A["cid"])
    assert _delete_self(client, h).status_code == 200

    # A do'konidagi a'zolik o'chdi
    assert nom_a not in _qator_matni(ids["a"])
    # B do'konidagi AYNI TELEFONLI qator TEGILMAGAN
    matn_b = _qator_matni(ids["b"])
    assert nom_b in matn_b, f"boshqa do'kondagi qator o'chirildi: {matn_b[:300]}"
    assert tel in matn_b, "boshqa do'kondagi telefon o'chirildi"


# ══ 3. OXIRGI RAHBAR — RAD ETILMAYDI, TANLOV BERILADI ═══════════════════════

def test_OXIRGI_RAHBAR_bloklanadi_va_TANLOV_beriladi(client):
    d = _shop()
    #  `_shop()` egasi parolsiz; parolli YAGONA ega yasaymiz va boshqa
    #  rahbarlarni qoldirmaymiz — shunda u «oxirgi rahbar» bo'ladi.
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    with _db() as db:
        for e in db.query(Employee).filter(Employee.company_id == d["cid"]).all():
            e.status = EmployeeStatus.terminated
        db.commit()
    ega_id, nom, _ = _xodim(d, "ega")
    _, kassir_id = _staff(d, "kassir")
    eh = _token(ega_id, "ega", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=eh)
    r = _delete_self(client, eh)

    assert st.status_code == 200, st.text[:200]
    j = st.json()
    assert j["can_delete"] is False, j
    assert "sole_manager" in j["blockers"] or "sole_owner" in j["blockers"], j
    assert j["confirm_word"] == TASDIQ
    #  ⚠️  TANLOV: o'tkazish nomzodlari ro'yxati BO'SH BO'LMASLIGI kerak —
    #      aks holda operator qulflanib qolardi.
    nomzod_ids = {c["id"] for c in j["transfer_candidates"]}
    assert str(kassir_id) in nomzod_ids, j["transfer_candidates"]
    #  Nomzod ro'yxati PII BERMAYDI
    for c in j["transfer_candidates"]:
        assert set(c) == {"id", "role"}, c
    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert nom in _qator_matni(ega_id), "oxirgi rahbar hisobi o'chirildi"


def test_BOSHQARUV_OTKAZILGACH_ochirish_ISHLAYDI(client):
    """Tanlovning AMALDA ishlashi: boshqa xodim ega qilingach, o'chirish o'tadi."""
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus

    d = _shop()
    with _db() as db:
        for e in db.query(Employee).filter(Employee.company_id == d["cid"]).all():
            e.status = EmployeeStatus.terminated
        db.commit()
    ega_id, nom, _ = _xodim(d, "ega")
    yangi_id, _, _ = _xodim(d, "menejer")
    eh = _token(ega_id, "ega", d["cid"])
    assert _delete_self(client, eh).status_code == 409      # hali oxirgi rahbar

    #  BOSHQARUVNI O'TKAZAMIZ (mavjud rol o'zgartirish yo'li bilan AYNI natija)
    with _db() as db:
        r = db.query(Role).filter(Role.code == "ega").one()
        db.get(Employee, uuid.UUID(yangi_id)).role_id = r.id
        db.commit()

    st = client.get("/api/v1/auth/account-deletion", headers=eh).json()
    r2 = _delete_self(client, eh)

    assert st["can_delete"] is True, st
    assert r2.status_code == 200, (r2.status_code, r2.text[:300])
    assert nom not in _qator_matni(ega_id)


def test_OCHIQ_SMENA_BLOKLAMAYDI_va_smena_QATORI_TEGILMAYDI(client):
    """Ega qarori (2026-10-17): xodim O'Z hisobini smena ochiq yoki yopiq
    bo'lishidan QAT'I NAZAR o'chira oladi.

    ⚠️  Ilgari bu test teskari edi (`open_shift` bloki + 409). Qoida o'zgardi,
        chunki ochiq smena yagona egani butunlay qulflab qo'yardi: smenani
        yopish kassirning O'ZINI talab qiladi, u yo'q bo'lsa chiqib ketishning
        yo'li qolmasdi.
    ⚠️  SMENA AVTOMATIK YOPILMAYDI: qator `open` holatida, o'chirilmagan
        holda QOLADI — moliyaviy tarix va naqd qoldiq hisobi saqlanadi.
    """
    from datetime import datetime, timezone

    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift

    d = _shop()
    _xodim(d, "ega")                        # boshqa rahbar bor
    eid, nom, _ = _xodim(d, "menejer")
    sid = uuid.uuid4()
    with _db() as db:
        db.add(Shift(id=sid, branch_id=d["bids"][0], cashier_id=uuid.UUID(eid),
                     status=ShiftStatus.open, opened_at=datetime.now(timezone.utc),
                     opening_cash=0))
        db.commit()
    h = _token(eid, "menejer", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=h).json()
    r = _delete_self(client, h)

    assert "open_shift" not in st["blockers"], st
    assert st["can_delete"] is True, st
    assert r.status_code == 200, (r.status_code, r.text[:200])
    #  Smena TEGILMAGAN: yopilmadi ham, o'chirilmadi ham.
    with _db() as db:
        sh = db.get(Shift, sid)
        assert sh is not None, "smena qatori o'chirilgan"
        assert sh.status == ShiftStatus.open, sh.status
        assert sh.deleted_at is None
    #  PII tozalandi — bu yo'lning o'z kontrakti, smena bilan aloqasi yo'q.
    assert nom not in _qator_matni(eid)


# ══ 4. BIZNES TARIXI VA HISOB-KITOB TEGILMAYDI ══════════════════════════════

def test_BIZNES_TARIXI_va_FK_BUTUNLIGI_SAQLANADI(client):
    """⚠️  Savdo/ombor yozuvlari O'CHIRILMAYDI va `employee_id` FK BUTUN qoladi —
    shu bois xodim QATORI o'chirilmaydi, faqat PII ustunlari tozalanadi."""
    from app.models.auth import Employee
    from app.models.inventory import StockMovement
    from tests.test_mobile_parity import _product

    d = _shop()
    _xodim(d, "ega")
    eid, nom, _ = _xodim(d, "menejer")
    p = _product(d, name="CH18A mahsulot", qty=0)
    # Xodim nomidan ombor harakati yozamiz
    from datetime import datetime, timezone
    from app.models.enums import MovementType
    with _db() as db:
        db.add(StockMovement(product_id=uuid.UUID(str(p["id"])), branch_id=d["bids"][0],
                             type=MovementType.adjustment, qty=5, unit_cost=100,
                             balance_after=5, ref_type="test", employee_id=uuid.UUID(eid),
                             created_at=datetime.now(timezone.utc)))
        db.commit()
    h = _token(eid, "menejer", d["cid"])

    assert _delete_self(client, h).status_code == 200

    with _db() as db:
        # Qator O'CHIRILMAGAN -> FK butun
        assert db.get(Employee, uuid.UUID(eid)) is not None, "xodim qatori o'chirildi — FK buzilardi"
        mvs = db.query(StockMovement).filter(
            StockMovement.employee_id == uuid.UUID(eid)).all()
        assert len(mvs) == 1, f"ombor harakati o'chirildi: {len(mvs)}"
        assert float(mvs[0].qty) == 5.0 and float(mvs[0].unit_cost) == 100.0
        assert nom not in json.dumps(
            {c.name: getattr(mvs[0], c.name) for c in StockMovement.__table__.columns},
            default=str, ensure_ascii=False), "harakatda PII bor"


def test_KIRISH_GRANTLARI_olib_tashlanadi(client):
    """Filial va ruxsat grantlari — biznes tarixi EMAS, shu bois o'chiriladi."""
    from app.models.auth import EmployeeBranch

    d = _shop()
    _xodim(d, "ega")
    eid, _, _ = _xodim(d, "menejer")
    with _db() as db:
        db.add(EmployeeBranch(employee_id=uuid.UUID(eid), branch_id=d["bids"][0]))
        db.commit()
        assert db.query(EmployeeBranch).filter(
            EmployeeBranch.employee_id == uuid.UUID(eid)).count() == 1
    h = _token(eid, "menejer", d["cid"])

    assert _delete_self(client, h).status_code == 200

    with _db() as db:
        assert db.query(EmployeeBranch).filter(
            EmployeeBranch.employee_id == uuid.UUID(eid)).count() == 0, "filial granti qoldi"


def test_AUDIT_izi_QOLADI_lekin_PII_SIZ(client):
    from app.models.sync import AuditLog

    d = _shop()
    _xodim(d, "ega")
    eid, nom, tel = _xodim(d, "menejer")
    h = _token(eid, "menejer", d["cid"])

    assert _delete_self(client, h).status_code == 200

    with _db() as db:
        rows = db.query(AuditLog).filter(AuditLog.entity == "employee_account").all()
        assert rows, "audit izi yozilmadi"
        matn = json.dumps([{c.name: getattr(r, c.name) for c in AuditLog.__table__.columns}
                           for r in rows], default=str, ensure_ascii=False)
        assert nom not in matn and tel not in matn, f"audit izida PII bor: {matn[:300]}"


# ══ 5. AVTENTIFIKATSIYA ═════════════════════════════════════════════════════

def test_AVTENTIFIKATSIYA_talab_qilinadi(client):
    assert client.get("/api/v1/auth/account-deletion").status_code in (401, 403)
    assert client.post("/api/v1/auth/account-deletion",
                       json={"password": PAROL, "confirm": TASDIQ}).status_code in (401, 403)
    assert client.post(f"/api/v1/employees/{uuid.uuid4()}/account-deletion",
                       json={"password": PAROL, "confirm": TASDIQ}).status_code in (401, 403)
