# -*- coding: utf-8 -*-
"""R6.8 P0-2 — XODIM FILIALI × OCHIQ SMENA INVARIANTI.

NUQSON (R6.7 auditida topilgan, `employees.py` da o'lchangan):
`PATCH /employees/{id}` ayni handlerda

  · STATUS o'zgarishini  `_has_open_shift` bilan to'sadi,
  · O'CHIRISHNI          `_has_open_shift` bilan to'sadi,
  · FILIAL o'zgarishini  HECH NARSA bilan to'smaydi.

Oqibat MOLIYAVIY. Yozuv filiali `EmployeeBranch` dan olinadi
(`core/deps.py::actor_branch`) va o'n ikkidan ortiq yozuvchi shu funksiyaga
tayanadi: sotuv (`services/sales.py`), qaytarish, xarid, hisobdan chiqarish,
sanoq, inkassa, custody. Ochiq smena O'RTASIDA filial A->B qilinsa, o'sha
smenaning KEYINGI chekи B filialga yoziladi: bitta smena ikki filialga
bo'linadi va yozuvlar immutable — tuzatib bo'lmaydi.

Bu fayl INVARIANTNI qadaydi:
  1. ochiq smena + HAQIQIY filial o'zgarishi -> 400, `EmployeeBranch` TEGILMAYDI;
  2. ochiq smena + AYNI filial               -> 200 (idempotent, buzilmaydi);
  3. smena YOPILGAN + filial o'zgarishi      -> 200;
  4. smena YO'Q + filial o'zgarishi          -> 200;
  5. rad etish TO'LIQ rollback: `full_name` ham o'zgarmaydi;
  6. rad etish AUDIT qatori qoldirmaydi (noto'g'ri «o'zgardi» izi yo'q);
  7. boshqa xodimning ochiq smenasi bu xodimni to'smaydi (izolyatsiya);
  8. yangi xodim yaratish (`POST /employees`) buzilmaydi;
  9. ruxsat: `xodimlar.edit` siz 403 — darvoza RUXSATDAN KEYIN;
 10. filial biriktiruvini OLIB TASHLASH (`branch_id=""`) ham o'zgarish — to'siladi;
 11. keyingi sotuv AYNI filialga yoziladi (atributsiya isboti).

⚠️  REAL POSTGRES POYGASI ALOHIDA FAYLDA: `test_r68_branch_shift_race_pg.py`.
    Bu yerdagi SQLite to'plami KETMA-KET mantiqni qadaydi; qulf xulqi
    SQLite'da o'lchanmaydi.
"""
import uuid as _uuid
from decimal import Decimal

import pytest

API = "/api/v1"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _demo_company_id():
    from app.models.org import Company
    s = _db()
    try:
        return s.query(Company).filter(Company.code == "demo").one().id
    finally:
        s.close()


def _branch(code: str, name: str):
    """Demo do'konida yangi FAOL filial — yoki mavjudini qaytaradi.

    ⚠️  DO'KON ANIQ KO'RSATILADI. Ilgari bu yerda `s.query(Branch).first()`
        orqali kompaniya olinardi — TARTIBSIZ `.first()`, ya'ni to'liq
        to'plamda boshqa testlar yaratgan BEGONA do'kon filiali qaytishi
        mumkin edi. Keyin `_set_branch` `br.company_id != company_id` ni
        ko'rib «Filial topilmadi» (400) berardi va nuqsonga aloqasi yo'q
        BESH test qizil bo'lardi (o'lchangan: to'liq to'plamda qizil,
        yolg'iz yurishda yashil — ya'ni nuqson TARTIBGA tayanish edi).
    """
    from app.models.org import Branch
    s = _db()
    try:
        cid = _demo_company_id()
        b = s.query(Branch).filter(Branch.company_id == cid, Branch.code == code).first()
        if b is None:
            b = Branch(id=_uuid.uuid4(), company_id=cid, code=code, name=name,
                       timezone="Asia/Tashkent", is_active=True)
            s.add(b)
            s.commit()
        return str(b.id)
    finally:
        s.close()


def _first_branch_id():
    """Demo do'konining `actor_branch` tanlaydigan FILIALI.

    ⚠️  `deps.actor_branch` bilan AYNI qoida: o'z kompaniyasi + faol +
        `order_by(created_at)`. Kompaniya filtri SHART (yuqoridagi izoh).
    """
    from app.models.org import Branch
    s = _db()
    try:
        b = (s.query(Branch)
             .filter(Branch.company_id == _demo_company_id(),
                     Branch.deleted_at.is_(None), Branch.is_active.is_(True))
             .order_by(Branch.created_at, Branch.id).first())
        return str(b.id)
    finally:
        s.close()


def _mk_employee(full_name: str, pin: str, role_code: str = "kassir", branch_id=None):
    """Xodimni TO'G'RIDAN bazaga yozadi (API yo'li ruxsat/noyoblik tekshiradi —
    bu yerda sinaladigan narsa u emas). Qaytaradi: (employee_id, pin)."""
    from app.core.security import hash_password
    from app.models.auth import Employee, EmployeeBranch, Role
    s = _db()
    try:
        cid = _demo_company_id()
        role = s.query(Role).filter(Role.code == role_code).one()
        e = Employee(id=_uuid.uuid4(), company_id=cid, full_name=full_name,
                     phone=None, role_id=role.id, pin_hash=hash_password(pin))
        s.add(e)
        s.flush()
        if branch_id:
            s.add(EmployeeBranch(employee_id=e.id, branch_id=_uuid.UUID(branch_id)))
        s.commit()
        return str(e.id)
    finally:
        s.close()


def _branch_of(employee_id: str):
    """Xodimning biriktirilgan filiali (`EmployeeBranch`) — yoki `None`."""
    from app.models.auth import EmployeeBranch
    s = _db()
    try:
        row = (s.query(EmployeeBranch.branch_id)
               .filter(EmployeeBranch.employee_id == _uuid.UUID(employee_id)).first())
        return str(row[0]) if row else None
    finally:
        s.close()


def _name_of(employee_id: str):
    from app.models.auth import Employee
    s = _db()
    try:
        return s.get(Employee, _uuid.UUID(employee_id)).full_name
    finally:
        s.close()


def _audit_count(employee_id: str) -> int:
    """Shu xodim ustidagi `employee/update` audit qatorlari soni."""
    from app.models.sync import AuditLog
    s = _db()
    try:
        return (s.query(AuditLog)
                .filter(AuditLog.entity == "employee",
                        AuditLog.entity_id == _uuid.UUID(employee_id),
                        AuditLog.action == "update")
                .count())
    finally:
        s.close()


def _open_shift_direct(employee_id: str, branch_id: str):
    """Ochiq smenani TO'G'RIDAN yozadi — `/shifts/open` kassirning O'Z tokenini
    talab qiladi, bu testlarda esa smena FAKTI kerak, uni ochish yo'li emas."""
    from datetime import datetime, timezone
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = _db()
    try:
        sh = Shift(id=_uuid.uuid4(), branch_id=_uuid.UUID(branch_id),
                   cashier_id=_uuid.UUID(employee_id), opened_at=datetime.now(timezone.utc),
                   opening_cash=Decimal("0"), status=ShiftStatus.open)
        s.add(sh)
        s.commit()
        return str(sh.id)
    finally:
        s.close()


def _close_shift_direct(shift_id: str):
    from datetime import datetime, timezone
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = _db()
    try:
        sh = s.get(Shift, _uuid.UUID(shift_id))
        sh.status = ShiftStatus.closed
        sh.closed_at = datetime.now(timezone.utc)
        s.commit()
    finally:
        s.close()


@pytest.fixture
def two_branches(client):
    """(A, B) — demo do'konidagi ikki FAOL filial id'si."""
    a = _first_branch_id()
    b = _branch("F0R68", "R6.8 ikkinchi filial")
    assert a != b
    return a, b


@pytest.fixture(autouse=True)
def _r68_tozalash(client):
    """Bu modul yaratgan xodimlarni HAR testdan oldin olib tashlaydi.

    ⚠️  NEGA KERAK (o'lchangan). `client` SEANS doirasida — ya'ni bitta SQLite
        bazasi butun modulga. Har test o'z xodimini yaratadi, demo seed esa
        4 ta bilan boshlanadi; `start` tarifida chegara 10 ta, shu bois 7-chi
        testdan keyin `POST /employees` 403 `tarif_limit` bera boshlaydi va
        nuqsonga aloqasi yo'q test QIZIL bo'lardi.
    ⚠️  FAQAT SHU MODUL YOZGANLARI: `full_name` AYNAN `R68 ` bilan boshlanadi.
        Demo seed xodimlariga (`Sardor`, `Dilnoza`, ...) TEGILMAYDI.
    """
    from app.models.auth import Employee, EmployeeBranch
    from app.models.shifts import Shift
    s = _db()
    try:
        ids = [r[0] for r in s.query(Employee.id)
               .filter(Employee.full_name.like("R68 %")).all()]
        if ids:
            s.query(Shift).filter(Shift.cashier_id.in_(ids)).delete(synchronize_session=False)
            s.query(EmployeeBranch).filter(
                EmployeeBranch.employee_id.in_(ids)).delete(synchronize_session=False)
            s.query(Employee).filter(Employee.id.in_(ids)).delete(synchronize_session=False)
            s.commit()
    finally:
        s.close()
    yield
    #  ⚠️  TESTDAN KEYIN HAM TOZALANADI. Faqat oldin tozalash yetmaydi: OXIRGI
    #      testning xodimlari butun to'plam davomida qolib ketardi va demo
    #      do'konini `start` tarifining 10 ta chegarasiga yetkazardi — natijada
    #      BOSHQA fayldagi test 403 `tarif_limit` olardi (o'lchangan:
    #      `test_security::test_non_admin_can_create_cashier`).
    s = _db()
    try:
        ids = [r[0] for r in s.query(Employee.id)
               .filter(Employee.full_name.like("R68 %")).all()]
        if ids:
            s.query(Shift).filter(Shift.cashier_id.in_(ids)).delete(synchronize_session=False)
            s.query(EmployeeBranch).filter(
                EmployeeBranch.employee_id.in_(ids)).delete(synchronize_session=False)
            s.query(Employee).filter(Employee.id.in_(ids)).delete(synchronize_session=False)
            s.commit()
    finally:
        s.close()


# ══ 1. OCHIQ SMENA + HAQIQIY FILIAL O'ZGARISHI -> RAD ════════════════════════

def test_ochiq_smena_filial_ozgarishini_RAD_etadi(client, admin_headers, two_branches):
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-1", "7101", branch_id=a)
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 400, r.text
    assert "smena" in r.text.lower(), r.text
    # EN MUHIM TASDIQ: biriktiruv TEGILMAGAN.
    assert _branch_of(eid) == a, "rad etilgan so'rov EmployeeBranch'ni o'zgartirdi"


def test_rad_etish_boshqa_maydonlarni_HAM_rollback_qiladi(client, admin_headers, two_branches):
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-2", "7102", branch_id=a)
    _open_shift_direct(eid, a)
    oldin = _name_of(eid)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers,
                     json={"full_name": "YANGI ISM", "branch_id": b})

    assert r.status_code == 400, r.text
    assert _name_of(eid) == oldin, "ism rad etilgan tranzaksiyada saqlanib qoldi"
    assert _branch_of(eid) == a


def test_rad_etish_AUDIT_qatori_qoldirmaydi(client, admin_headers, two_branches):
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-3", "7103", branch_id=a)
    _open_shift_direct(eid, a)
    oldin = _audit_count(eid)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 400, r.text
    assert _audit_count(eid) == oldin, "rad etilgan o'zgarish audit izini qoldirdi"


def test_biriktiruvni_OLIB_TASHLASH_ham_ozgarish_va_rad_etiladi(client, admin_headers, two_branches):
    """`branch_id=""` -> `_set_branch` biriktiruvni O'CHIRADI. Ochiq smenada bu ham
    atributsiyani buzadi (`actor_branch` zaxira «birinchi faol filial» ga tushadi)."""
    a, _b = two_branches
    eid = _mk_employee("R68 Kassir-4", "7104", branch_id=a)
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": ""})

    assert r.status_code == 400, r.text
    assert _branch_of(eid) == a


# ══ 2. AYNI FILIAL -> IDEMPOTENT, BUZILMAYDI ═════════════════════════════════

def test_ochiq_smena_AYNI_filial_qayta_yuborilsa_OTADI(client, admin_headers, two_branches):
    a, _b = two_branches
    eid = _mk_employee("R68 Kassir-5", "7105", branch_id=a)
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": a})

    assert r.status_code == 200, r.text
    assert _branch_of(eid) == a


def test_ochiq_smena_AYNI_filial_bilan_boshqa_maydon_ham_yoziladi(client, admin_headers, two_branches):
    a, _b = two_branches
    eid = _mk_employee("R68 Kassir-6", "7106", branch_id=a)
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers,
                     json={"full_name": "R68 Kassir-6b", "branch_id": a})

    assert r.status_code == 200, r.text
    assert _name_of(eid) == "R68 Kassir-6b"
    assert _branch_of(eid) == a


def test_biriktiruvsiz_xodimga_bosh_branch_id_ham_idempotent(client, admin_headers, two_branches):
    """Filiali YO'Q xodimga `branch_id=""` — o'zgarish EMAS, ochiq smenada ham o'tadi."""
    a, _b = two_branches
    eid = _mk_employee("R68 Kassir-7", "7107", branch_id=None)
    _open_shift_direct(eid, a)
    assert _branch_of(eid) is None

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": ""})

    assert r.status_code == 200, r.text
    assert _branch_of(eid) is None


# ══ 3-4. SMENA YOPILGAN / YO'Q -> RUXSAT ═════════════════════════════════════

def test_smena_YOPILGAN_bolsa_filial_ozgaradi(client, admin_headers, two_branches):
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-8", "7108", branch_id=a)
    sid = _open_shift_direct(eid, a)
    _close_shift_direct(sid)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 200, r.text
    assert _branch_of(eid) == b


def test_smena_YOQ_bolsa_filial_ozgaradi(client, admin_headers, two_branches):
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-9", "7109", branch_id=a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 200, r.text
    assert _branch_of(eid) == b


# ══ 7. IZOLYATSIYA ═══════════════════════════════════════════════════════════

def test_BOSHQA_xodimning_ochiq_smenasi_bu_xodimni_TOSMAYDI(client, admin_headers, two_branches):
    a, b = two_branches
    boshqa = _mk_employee("R68 Begona", "7110", branch_id=a)
    _open_shift_direct(boshqa, a)
    eid = _mk_employee("R68 Kassir-10", "7111", branch_id=a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 200, r.text
    assert _branch_of(eid) == b
    assert _branch_of(boshqa) == a


def test_BOSHQA_kompaniya_xodimi_404(client, admin_headers, two_branches):
    """Tenant izolyatsiyasi: begona do'kon xodimiga PATCH — 404, darvozadan OLDIN."""
    from app.core.security import hash_password
    from app.models.auth import Employee, Role
    from app.models.org import Company
    a, b = two_branches
    s = _db()
    try:
        co = Company(id=_uuid.uuid4(), name="R68 begona", code="r68x" + _uuid.uuid4().hex[:6],
                     currency="UZS")
        s.add(co)
        s.flush()
        role = s.query(Role).filter(Role.code == "kassir").one()
        e = Employee(id=_uuid.uuid4(), company_id=co.id, full_name="R68 begona kassir",
                     role_id=role.id, pin_hash=hash_password("7112"))
        s.add(e)
        s.commit()
        begona = str(e.id)
    finally:
        s.close()

    r = client.patch(f"{API}/employees/{begona}", headers=admin_headers, json={"branch_id": b})

    assert r.status_code == 404, r.text


# ══ 8-9. QO'SHNI YO'LLAR BUZILMAYDI ══════════════════════════════════════════

def test_YANGI_xodim_yaratish_filial_bilan_buzilmaydi(client, admin_headers, two_branches):
    """`POST /employees` da ochiq smena bo'lishi MUMKIN EMAS — darvoza u yerga
    qo'yilmasligi kerak."""
    a, _b = two_branches
    r = client.post(f"{API}/employees", headers=admin_headers,
                    json={"full_name": "R68 Yangi", "role_code": "kassir",
                          "pin": "7113", "branch_id": a})
    assert r.status_code == 200, r.text
    eid = r.json().get("id")
    assert eid, r.text
    assert _branch_of(eid) == a


def test_ruxsatsiz_PATCH_403_darvozadan_OLDIN(client, two_branches):
    """`xodimlar.edit` yo'q kassir — 403. Ochiq smena darvozasi ruxsatdan KEYIN
    bo'lishi kerak (aks holda ruxsatsiz so'rov smena holatini aniqlab olardi)."""
    a, b = two_branches
    kassir_pin = "7114"
    eid = _mk_employee("R68 Ruxsatsiz", kassir_pin, branch_id=a)
    r = client.post(f"{API}/auth/login", json={"employee_id": eid, "pin": kassir_pin})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=H, json={"branch_id": b})

    assert r.status_code == 403, r.text
    assert _branch_of(eid) == a


# ══ 11. ATRIBUTSIYA ISBOTI ═══════════════════════════════════════════════════

def test_ruxsat_etilgan_ozgarishdan_keyin_actor_branch_YANGI_filial(client, admin_headers,
                                                                    two_branches):
    """Smena yo'q -> filial o'zgaradi -> `actor_branch` YANGI filialni qaytaradi.
    Bu zanjir aynan moliyaviy atributsiyaning o'zi (`sales.py:212 _ab(emp, db)`)."""
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-11", "7115", branch_id=a)

    s = _db()
    try:
        assert str(actor_branch(s.get(Employee, _uuid.UUID(eid)), s).id) == a
    finally:
        s.close()

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})
    assert r.status_code == 200, r.text

    s = _db()
    try:
        assert str(actor_branch(s.get(Employee, _uuid.UUID(eid)), s).id) == b
    finally:
        s.close()


def test_RAD_etilgan_ozgarishdan_keyin_actor_branch_ESKI_filial(client, admin_headers,
                                                                two_branches):
    """Rad etilgandan keyin atributsiya O'ZGARMAGANINI isbotlaydi — ya'ni
    smenaning keyingi cheklari AYNI filialga yoziladi."""
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    a, b = two_branches
    eid = _mk_employee("R68 Kassir-12", "7116", branch_id=a)
    _open_shift_direct(eid, a)

    r = client.patch(f"{API}/employees/{eid}", headers=admin_headers, json={"branch_id": b})
    assert r.status_code == 400, r.text

    s = _db()
    try:
        assert str(actor_branch(s.get(Employee, _uuid.UUID(eid)), s).id) == a, \
            "rad etilgan o'zgarishdan keyin yozuv filiali SURILDI"
    finally:
        s.close()
