# -*- coding: utf-8 -*-
"""CH-19B/A — MIJOZ shaxsiy ma'lumotiga KIRISH ruxsati (P0).

⚠️  TOPILGAN ZAIFLIK. `GET /customers`, `GET /customers/{id}` va
    `GET /customers/{id}/detail` faqat `get_current_employee` bilan
    yopilgandi — ya'ni do'konning HAR BIR faol xodimi, roli va ruxsat
    to'plamidan QAT'I NAZAR, barcha mijozning ismi, telefoni va QARZ
    balansini o'qiy olardi. Yozish yo'llari esa ruxsat talab qilardi
    (`mijozlar.edit`) — ya'ni o'qish yozishdan KO'RA ochiq edi.

⚠️  YANGI SIYOSAT O'YLAB TOPILMADI. `mijozlar.view` ruxsati urug'da
    ALLAQACHON mavjud va rollarga ALLAQACHON taqsimlangan
    (`app/seed.py:ROLES`):

        ega            -> ALL (bor)
        administrator  -> ALL (bor)
        menejer        -> BOR
        kassir         -> BOR        (nasiya savdosida mijozni topishi kerak)
        omborchi       -> YO'Q

    Ya'ni eganing o'z rol dizayni omborchiga mijoz ma'lumotini BERMAYDI —
    kod shuni e'tiborsiz qoldirgan. Tuzatish MAVJUD ruxsatni majburlaydi,
    xolos. Hech qanday yangi rol qoidasi kiritilmadi.

⚠️  `mijozlar.view` ILGARI HECH QAYERDA MAJBURLANMAGAN (o'lik ruxsat edi):
    `grep -rn "mijozlar.view" app/` faqat `seed.py` ni topardi.

Bu fayl POZITIV va MANFIY tomonni, cross-tenant izolyatsiyasini, soxta
token bilan hujumni va override semantikasini qadaydi.
"""
from __future__ import annotations

import uuid

import pytest

PREFIX = "/api/v1"
ROLLAR = ("ega", "administrator", "menejer", "omborchi", "kassir")

#: `mijozlar.view` ga EGA bo'lgan rollar (urug'dan, qattiq yozilmaydi).
RUXSATLI = ("ega", "administrator", "menejer", "kassir")
#: Ruxsati YO'Q rollar.
RUXSATSIZ = ("omborchi",)


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _dokon(nom="CH19B"):
    """Yangi do'kon + har roldan bitta xodim + bitta qarzli mijoz."""
    from app.core.security import create_access_token
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.customers import Customer
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name=f"{nom} {uuid.uuid4().hex[:6]}",
                       code=nom.lower() + uuid.uuid4().hex[:8], currency="UZS")
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                    timezone="Asia/Tashkent", is_active=True)
        db.add(br)
        db.flush()
        hdr = {}
        for code in ROLLAR:
            role = db.query(Role).filter(Role.code == code).one()
            e = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                         full_name=f"{nom} {code}",
                         phone="+9989" + str(uuid.uuid4().int)[:8],
                         status=EmployeeStatus.active, sec_epoch=0)
            db.add(e)
            db.flush()
            if code != "ega":
                db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id))
            tok = create_access_token(str(e.id), {"role": code, "company_id": str(comp.id), "sv": 0})
            hdr[code] = ({"Authorization": f"Bearer {tok}"}, str(e.id))
        ism = f"{nom}-MIJOZ-{uuid.uuid4().hex[:8]}"
        tel = "+9989" + str(uuid.uuid4().int)[:8]
        cust = Customer(id=uuid.uuid4(), company_id=comp.id,
                        code="C" + uuid.uuid4().hex[:8], full_name=ism,
                        phone=tel, credit_balance=125000)
        db.add(cust)
        db.commit()
        return {"cid": comp.id, "bid": br.id, "hdr": hdr,
                "mijoz": str(cust.id), "ism": ism, "tel": tel}


def _h(d, rol):
    return d["hdr"][rol][0]


def _uchta_yol(d):
    """Mijoz PII sini qaytaradigan UCHTA o'qish yo'li."""
    return (
        ("list",   f"{PREFIX}/customers"),
        ("single", f"{PREFIX}/customers/{d['mijoz']}"),
        ("detail", f"{PREFIX}/customers/{d['mijoz']}/detail"),
    )


# ══ POZITIV — ruxsati BOR rollar ishlayotgan jarayonni YO'QOTMAYDI ══════════

@pytest.mark.parametrize("rol", RUXSATLI)
def test_A_RUXSATLI_rollar_mijozni_KORADI(client, rol):
    """⚠️  Kassir ALOHIDA muhim: nasiya savdosida mijozni topishi SHART.
    Tuzatish uning ishini buzmasligi kerak."""
    d = _dokon()

    for nom, yol in _uchta_yol(d):
        r = client.get(yol, headers=_h(d, rol))
        assert r.status_code == 200, (rol, nom, r.status_code, r.text[:200])

    #  Ro'yxatda mijoz chindan ko'rinadi
    lst = client.get(f"{PREFIX}/customers", headers=_h(d, rol)).json()
    assert any(x["full_name"] == d["ism"] for x in lst), (rol, lst[:2])


# ══ MANFIY — ruxsati YO'Q rol HECH BIR yo'ldan PII olmaydi ══════════════════

@pytest.mark.parametrize("rol", RUXSATSIZ)
def test_A_RUXSATSIZ_rol_UCHTA_yoldan_ham_403(client, rol):
    d = _dokon()

    for nom, yol in _uchta_yol(d):
        r = client.get(yol, headers=_h(d, rol))

        assert r.status_code == 403, (nom, r.status_code, r.text[:200])
        assert r.headers.get("X-Error-Code") == "PERMISSION_DENIED", (nom, dict(r.headers))


@pytest.mark.parametrize("rol", RUXSATSIZ)
def test_A_RUXSATSIZ_rol_ISM_TELEFON_QARZ_ni_KORMAYDI(client, rol):
    """Javob tanasida PII SIZIB CHIQMASLIGI — status koddan tashqari, MATN
    bo'yicha ham qadalgan (403 bo'lsa ham tana PII bermasligi kerak)."""
    d = _dokon()

    for nom, yol in _uchta_yol(d):
        r = client.get(yol, headers=_h(d, rol))
        matn = r.text

        assert d["ism"] not in matn, f"{nom}: ism sizdi"
        assert d["tel"] not in matn, f"{nom}: telefon sizdi"
        assert "125000" not in matn, f"{nom}: qarz balansi sizdi"


def test_A_RUXSATSIZ_rol_QIDIRUV_parametri_bilan_ham_OLMAYDI(client):
    """⚠️  SOXTA SO'ROV: `?q=` bilan substring qidiruvi — darvoza marshrutda
    bo'lgani uchun parametr yordam bermaydi."""
    d = _dokon()
    h = _h(d, "omborchi")

    for q in (d["ism"][:10], d["tel"][-6:], "", "%", "_", "a"):
        r = client.get(f"{PREFIX}/customers", headers=h, params={"q": q})

        assert r.status_code == 403, (q, r.status_code)
        assert d["ism"] not in r.text and d["tel"] not in r.text


def test_A_RUXSATSIZ_rol_YOZISH_yollaridan_ham_OLMAYDI(client):
    """Nazorat: yozish yo'llari ILGARI ham yopiq edi va shunday qoladi."""
    d = _dokon()
    h = _h(d, "omborchi")

    assert client.post(f"{PREFIX}/customers", headers=h,
                       json={"full_name": "X"}).status_code == 403
    assert client.patch(f"{PREFIX}/customers/{d['mijoz']}", headers=h,
                        json={"full_name": "Y"}).status_code == 403
    assert client.delete(f"{PREFIX}/customers/{d['mijoz']}", headers=h).status_code == 403


# ══ CROSS-TENANT ════════════════════════════════════════════════════════════

def test_A_CROSS_TENANT_begona_dokon_mijozini_KORMAYDI(client):
    """Ruxsati BOR ega ham BEGONA do'kon mijozini ko'rmaydi."""
    a = _dokon("CH19BA")
    b = _dokon("CH19BB")
    ah = _h(a, "ega")

    #  Ro'yxatda begona mijoz YO'Q
    lst = client.get(f"{PREFIX}/customers", headers=ah).json()
    assert all(x["full_name"] != b["ism"] for x in lst), lst[:3]
    #  To'g'ridan murojaat — 404 (mavjudligi ham oshkor bo'lmaydi)
    for yol in (f"{PREFIX}/customers/{b['mijoz']}",
                f"{PREFIX}/customers/{b['mijoz']}/detail"):
        r = client.get(yol, headers=ah)
        assert r.status_code == 404, (yol, r.status_code, r.text[:150])
        assert b["ism"] not in r.text and b["tel"] not in r.text


def test_A_CROSS_TENANT_qidiruv_bilan_ham_CHIQMAYDI(client):
    """Begona mijoz ismini AYNAN bilib qidirish ham natija bermaydi."""
    a = _dokon("CH19BC")
    b = _dokon("CH19BD")

    r = client.get(f"{PREFIX}/customers", headers=_h(a, "ega"),
                   params={"q": b["ism"]})

    assert r.status_code == 200, r.text[:200]
    assert r.json() == [], r.json()


# ══ SOXTA TOKEN — rol BAZADAN olinadi ══════════════════════════════════════

def test_A_SOXTA_token_roli_YORDAM_BERMAYDI(client):
    """⚠️  Tokendagi `role` claim'ini `ega` deb yasasak ham, ruxsat BAZADAGI
    rol bo'yicha hisoblanadi (`effective_permissions`)."""
    from app.core.security import create_access_token

    d = _dokon()
    _hdr, omborchi_id = d["hdr"]["omborchi"]
    soxta = create_access_token(str(omborchi_id),
                                {"role": "ega", "company_id": str(d["cid"]), "sv": 0})
    h = {"Authorization": f"Bearer {soxta}"}

    for nom, yol in _uchta_yol(d):
        r = client.get(yol, headers=h)

        assert r.status_code == 403, (nom, r.status_code, r.text[:200])
        assert d["ism"] not in r.text


def test_A_SOXTA_company_id_boshqa_dokonga_KIRITMAYDI(client):
    """Tokenda boshqa do'kon `company_id` si bo'lsa ham, ijarachi xodim
    qatoridan olinadi."""
    from app.core.security import create_access_token

    a = _dokon("CH19BE")
    b = _dokon("CH19BF")
    _hdr, a_ega_id = a["hdr"]["ega"]
    soxta = create_access_token(str(a_ega_id),
                                {"role": "ega", "company_id": str(b["cid"]), "sv": 0})
    h = {"Authorization": f"Bearer {soxta}"}

    lst = client.get(f"{PREFIX}/customers", headers=h)

    assert lst.status_code == 200, lst.text[:200]
    assert all(x["full_name"] != b["ism"] for x in lst.json()), lst.json()[:3]


def test_A_AUTENTIFIKATSIYASIZ_401(client):
    d = _dokon()
    for _nom, yol in _uchta_yol(d):
        assert client.get(yol).status_code in (401, 403)


# ══ OVERRIDE — mavjud arxitektura semantikasi saqlanadi ════════════════════

def test_A_OVERRIDE_bilan_omborchi_RUXSAT_OLADI(client):
    """Ega omborchiga `mijozlar.view` ni ALOHIDA bersa — ishlaydi.
    Ya'ni tuzatish rolni qattiq yozmaydi, RUXSATNI tekshiradi."""
    from app.models.auth import Employee, EmployeePermission, Permission

    d = _dokon()
    hdr, omborchi_id = d["hdr"]["omborchi"]
    assert client.get(f"{PREFIX}/customers", headers=hdr).status_code == 403

    with _db() as db:
        pid = {p.code: p.id for p in db.query(Permission).all()}["mijozlar.view"]
        db.add(EmployeePermission(employee_id=uuid.UUID(omborchi_id),
                                 permission_id=pid, allowed=True))
        db.commit()

    r = client.get(f"{PREFIX}/customers", headers=hdr)

    assert r.status_code == 200, r.text[:200]
    assert any(x["full_name"] == d["ism"] for x in r.json())
    assert Employee is not None


def test_A_OVERRIDE_bilan_kassirdan_OLINADI(client):
    """Teskari tomoni: ega kassirdan `mijozlar.view` ni olib qo'ysa — 403."""
    from app.models.auth import EmployeePermission, Permission

    d = _dokon()
    hdr, kassir_id = d["hdr"]["kassir"]
    assert client.get(f"{PREFIX}/customers", headers=hdr).status_code == 200

    with _db() as db:
        pid = {p.code: p.id for p in db.query(Permission).all()}["mijozlar.view"]
        db.add(EmployeePermission(employee_id=uuid.UUID(kassir_id),
                                 permission_id=pid, allowed=False))
        db.commit()

    r = client.get(f"{PREFIX}/customers", headers=hdr)

    assert r.status_code == 403, r.text[:200]
    assert d["ism"] not in r.text


# ══ MATRITSA bilan MOSLIK ══════════════════════════════════════════════════

def test_A_MATRITSA_uchta_yolni_HAM_elon_qiladi(client):
    """Mobil matritsa serverning darvozasi bilan mos bo'lishi SHART
    (`test_mobile_permission_matrix` buni majburlaydi). Bu test uchinchi
    yo'l (`GET /customers/{id}`) matritsada BORLIGINI ham qadaydi — u
    ilgari umuman e'lon qilinmagandi."""
    import json

    from tests.test_mobile_permission_matrix import MATRIX

    acts = json.loads(MATRIX.read_text(encoding="utf-8"))["actions"]
    mijoz_oqish = {k: v for k, v in acts.items()
                   if v["method"] == "GET" and v["path"].startswith("/customers")}

    assert len(mijoz_oqish) == 3, sorted(mijoz_oqish)
    for k, v in mijoz_oqish.items():
        assert v["any_of"] == ["mijozlar.view"], (k, v)
