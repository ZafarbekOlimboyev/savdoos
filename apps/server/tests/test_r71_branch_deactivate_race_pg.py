# -*- coding: utf-8 -*-
"""R7.1 P1 — «FILIALNI NOFAOL QILISH» × «SMENA OCHISH» POYGASI, HAQIQIY POSTGRES.

R6.8 P0-2 xodim yo'lida yopilgan edi (`test_r68_branch_shift_race_pg.py`), lekin
yozuv filialining IKKINCHI, BARAVAR KUCHLI manbasi — `Branch.is_active` —
QULFSIZ qolgan edi. R7.0 auditi buni P1 sifatida qayd etdi; bu fayl uni
O'LCHAYDI.

POYGA. `PATCH /branches/{id}` da `is_active=false` ikki «ochiq smena bormi?»
tekshiruvini QULFSIZ `SELECT` bilan qiladi; `POST /shifts/open` esa
`deps.actor_branch` ni (filialni `is_active IS TRUE` bilan tanlaydi) ham
QULFSIZ o'qiydi. Ikkisi bir-birini ko'rmaydi:

    T1 (nofaol qilish): ochiq smena YO'Q  ->  Branch.is_active = false   commit
    T2 (smena ochish):  actor_branch = A  ->  Shift(branch=A, open)      commit

Natija: NOFAOL filial ichida OCHIQ smena. Keyin `actor_branch` 1-bosqichda A ni
`is_active IS TRUE` bilan filtrlab chiqarib tashlaydi va 2-bosqichga —
«do'konning BIRINCHI FAOL filiali» (B) ga tushadi. Ya'ni o'sha smenaning
keyingi cheklari, qaytarishlari va payout'lari B filialga yoziladi:
BITTA SMENA IKKI FILIALGA BO'LINADI va yozuvlar immutable.

INVARIANT (shu fayl tasdiqlaydi, har ikkala commit'dan KEYIN):
    ochiq smena bo'lsa -> shift.branch_id == actor_branch(emp)
                       va o'sha filial FAOL.

TUZATISH — UMUMIY SERIALIZATSIYA NUQTASI. Ikkala yo'l ham AYNI `branches`
qatori(lari)ni `FOR UPDATE` qiladi:
  · `api/v1/branches.py::_lock_company_branches` — nofaol qilish va o'chirish
    kompaniyaning filial qatorlarini `id` bo'yicha TARTIBLI qulflaydi;
  · `services/shifts.py::open_shift_svc` — `actor_branch` tanlagan filial
    qatorini qulflaydi va QULFDAN KEYIN uning hamon FAOL ekanini QAYTA
    tekshiradi (READ COMMITTED'da qulfni kutgan `SELECT` eng yangi qatorni
    o'qiydi, keyingi `SELECT` esa YANGI snapshot oladi).

QULF TARTIBI: `Employee` -> `Branch`. Faqat `open_shift_svc` ikkisini ham
oladi; filial yo'llari `Employee` ni qulflamaydi, xodim yo'li `Branch` ni
qulflamaydi — demak TSIKL YO'Q, deadlock imkonsiz. Filiallar o'zaro HAR DOIM
`id` bo'yicha o'sish tartibida qulflanadi.

⚠️  INTERLEAVING MAJBURIY, TASODIFIY EMAS: `_navbat` birinchi tranzaksiyani
    yozib commit QILMAY ushlab turadi va ikkinchisi uning qulfini kutayotganini
    `pg_blocking_pids` da KO'RGANDAN keyin commit qiladi. Kutish ko'rilmasa
    (`kutdi` False) — qulf OLINMAGAN, ya'ni tuzatish ishlamaydi va sinov QIZIL.

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza;
CI'da `-k external` bilan PostgreSQL 18 servisida).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_lot_tz_confirm_pg import _mk, _navbat

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _baza(url):
    _initdb(url)
    return _mk(url)


def _dokon(S, *, filiallar=2):
    """Kompaniya + N faol filial + BIRINCHI filialga biriktirilgan kassir + ega.

    `created_at` o'sish tartibida — `actor_branch` ning 2-bosqichi AYNAN shu
    tartibdan «birinchi faol filial» ni tanlaydi, ya'ni fallback nishoni
    DETERMINISTIK: B1 nofaol bo'lsa B2 ga tushadi.
    """
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.org import Branch, Company
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="R71 PG", code="r71" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        bids = []
        for i in range(filiallar):
            b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}",
                       name=f"B{i + 1}", timezone=TZ, is_active=True,
                       created_at=NOW - timedelta(days=10 - i))
            s.add(b)
            s.flush()
            bids.append(b.id)
        kassir_role = s.query(Role).filter(Role.code == "kassir").one()
        ega_role = s.query(Role).filter(Role.code == "ega").one()
        kassir = Employee(id=uuid.uuid4(), company_id=co.id, full_name="R71 kassir",
                          phone="+9989" + str(uuid.uuid4().int)[:8], role_id=kassir_role.id)
        ega = Employee(id=uuid.uuid4(), company_id=co.id, full_name="R71 ega",
                       phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega_role.id)
        s.add_all([kassir, ega])
        s.flush()
        s.add(EmployeeBranch(employee_id=kassir.id, branch_id=bids[0]))
        s.commit()
        return co.id, bids, kassir.id, ega.id
    finally:
        s.close()


def _holat(S, eid):
    """(ochiq_smena_filiali, yozuv_filiali, o'sha_filial_faolmi) — commit'lardan KEYIN."""
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    from app.models.enums import ShiftStatus
    from app.models.org import Branch
    from app.models.shifts import Shift
    s = S()
    try:
        sh = (s.query(Shift)
              .filter(Shift.cashier_id == eid, Shift.status == ShiftStatus.open).first())
        emp = s.get(Employee, eid)
        yozuv = actor_branch(emp, s)
        faol = None
        if sh is not None:
            b = s.get(Branch, sh.branch_id)
            faol = bool(b.is_active) and b.deleted_at is None
        return (sh.branch_id if sh else None), (yozuv.id if yozuv else None), faol
    finally:
        s.close()


def _filial_faolmi(S, bid):
    from app.models.org import Branch
    s = S()
    try:
        b = s.get(Branch, bid)
        return bool(b.is_active)
    finally:
        s.close()


def _audit_soni(S, bid):
    """Filial ustidagi `update` audit yozuvlari — RAD ETILGAN amal iz qoldirmasin."""
    from app.models.sync import AuditLog
    s = S()
    try:
        return (s.query(AuditLog)
                .filter(AuditLog.entity == "branch", AuditLog.entity_id == bid,
                        AuditLog.action == "update").count())
    finally:
        s.close()


def _nofaol_qilish(bid, ega_id, *, commit_kechiktir: bool = False):
    """`PATCH /branches/{id}` ning `is_active=false` yo'li — AYNAN production tanasi.

    `edit_branch` o'z ichida `db.commit()` qiladi; `_navbat` esa «yozib, commit
    QILMAY tur» talab qiladi. Shu bois SHU chaqiruv doirasida `commit`
    VAQTINCHA `flush` ga almashtiriladi va darhol tiklanadi — production kodi
    bayt-bayt AYNI, faqat YAKUNIY commit `_navbat` ga qoldiriladi.
    """
    def _ish(s):
        from app.api.v1.branches import BranchEdit, edit_branch
        from app.models.auth import Employee
        emp = s.get(Employee, ega_id)
        data = BranchEdit(is_active=False)
        if not commit_kechiktir:
            return edit_branch(bid, data, emp, s)
        asl = s.commit
        s.commit = s.flush          # type: ignore[method-assign]
        try:
            return edit_branch(bid, data, emp, s)
        finally:
            s.commit = asl          # type: ignore[method-assign]
    return _ish


def _smena_ochish(eid, *, commit_kechiktir: bool = False):
    """`POST /shifts/open` ning kanonik tanasi (R6.8 fayli bilan AYNI naqsh)."""
    def _ish(s):
        from app.models.auth import Employee
        from app.services.shifts import open_shift_svc
        emp = s.get(Employee, eid)
        data = type("OpenShift", (), {"opening_cash": Decimal("0"), "terminal_id": None,
                                      "till_id": None})()
        if not commit_kechiktir:
            return open_shift_svc(data, emp, s)
        asl = s.commit
        s.commit = s.flush          # type: ignore[method-assign]
        try:
            return open_shift_svc(data, emp, s)
        finally:
            s.commit = asl          # type: ignore[method-assign]
    return _ish


def _xato_kodi(x):
    return x.status_code if isinstance(x, HTTPException) else None


# ══ 1. NOFAOL QILISH BIRINCHI QULFLAYDI ═════════════════════════════════════

def test_NOFAOL_QILISH_birinchi_smena_FAOL_FILIALDA_ochiladi(pg_target):
    """T1 filialni nofaol qiladi; T2 kutadi va smenani FAOL filialda ochadi.

    Tuzatishdan OLDIN T2 kutmasdi va smenani NOFAOL B1 da ochardi — keyingi
    cheklar esa B2 ga tushardi."""
    eng, S = _baza(pg_target)
    _cid, bids, kassir, ega = _dokon(S)

    r = _navbat(eng, S,
                _nofaol_qilish(bids[0], ega, commit_kechiktir=True),
                _smena_ochish(kassir))

    assert r["kutdi"], ("ikkinchi tranzaksiya QULFNI KUTMADI — umumiy "
                        "serializatsiya nuqtasi YO'Q")
    assert not isinstance(r["a"], Exception), r["a"]
    assert not isinstance(r["b"], Exception), r["b"]

    smena_bid, yozuv_bid, faol = _holat(S, kassir)
    assert smena_bid is not None, "smena ochilmadi"
    assert faol is True, "smena NOFAOL filialda ochildi"
    assert smena_bid == yozuv_bid, (
        "ochiq smena filiali yozuv filialidan FARQ QILADI — smena ikki "
        f"filialga bo'lindi: smena={smena_bid}, yozuv={yozuv_bid}")
    assert smena_bid == bids[1], (smena_bid, bids)
    assert not _filial_faolmi(S, bids[0])


# ══ 2. SMENA OCHISH BIRINCHI QULFLAYDI ══════════════════════════════════════

def test_SMENA_birinchi_nofaol_qilish_RAD_etiladi(pg_target):
    """T1 smena ochadi (commit qilmay turadi); T2 nofaol qilmoqchi.

    T2 qulfni kutadi, keyin YANGI snapshot'da ochiq smenani KO'RADI va 400
    beradi. Tuzatishdan OLDIN T2 kutmasdi, smenani ko'rmasdi va filialni
    nofaol qilib yuborardi."""
    eng, S = _baza(pg_target)
    _cid, bids, kassir, ega = _dokon(S)

    r = _navbat(eng, S,
                _smena_ochish(kassir, commit_kechiktir=True),
                _nofaol_qilish(bids[0], ega))

    assert r["kutdi"], "nofaol qilish QULFNI KUTMADI"
    assert not isinstance(r["a"], Exception), r["a"]
    assert _xato_kodi(r["b"]) == 400, ("nofaol qilish RAD ETILMADI", r["b"])
    assert "ochiq smena" in str(getattr(r["b"], "detail", "")).lower()

    smena_bid, yozuv_bid, faol = _holat(S, kassir)
    assert smena_bid == bids[0] and yozuv_bid == bids[0], (smena_bid, yozuv_bid)
    assert faol is True
    assert _filial_faolmi(S, bids[0]), "RAD ETILGAN amal filialni nofaol qildi"
    #  RAD ETILGAN amal AUDITGA «muvaffaqiyat» yozmasin.
    assert _audit_soni(S, bids[0]) == 0, "rad etilgan nofaol qilish audit izi qoldirdi"


# ══ 3. OXIRGI FAOL FILIAL — IKKI PARALLEL NOFAOL QILISH ════════════════════

def test_IKKI_PARALLEL_nofaol_qilish_DOKONNI_FILIALSIZ_QOLDIRMAYDI(pg_target):
    """«Oxirgi faol filialni o'chirib bo'lmaydi» tekshiruvi ham QULFSIZ edi.

    Ikki filial, ikki parallel nofaol qilish: ikkisi ham «mendan boshqa 1 ta
    faol bor» deb o'qib o'tib ketsa, do'kon 0 faol filial bilan qolardi —
    `actor_branch` hech narsa topmaydi va KASSA UMUMAN ISHLAMAYDI."""
    eng, S = _baza(pg_target)
    _cid, bids, _kassir, ega = _dokon(S)

    r = _navbat(eng, S,
                _nofaol_qilish(bids[0], ega, commit_kechiktir=True),
                _nofaol_qilish(bids[1], ega))

    assert r["kutdi"], "ikkinchi nofaol qilish QULFNI KUTMADI"
    assert not isinstance(r["a"], Exception), r["a"]
    assert _xato_kodi(r["b"]) == 400, ("ikkinchisi RAD ETILMADI", r["b"])
    faollar = [b for b in bids if _filial_faolmi(S, b)]
    assert len(faollar) == 1, f"do'kon {len(faollar)} faol filial bilan qoldi"


# ══ 4. TENANT IZOLYATSIYASI — BOSHQA DO'KON BLOKLAMAYDI ════════════════════

def test_TENANT_boshqa_dokonning_SMENASI_BLOKLAMAYDI(pg_target):
    """A do'konining filialini nofaol qilish B do'konining ochiq smenasiga
    BOG'LIQ BO'LMASLIGI kerak — aks holda qulf kompaniyalar orasida oqardi."""
    eng, S = _baza(pg_target)
    _, a_bids, _a_kassir, a_ega = _dokon(S)
    _, b_bids, b_kassir, _b_ega = _dokon(S)

    r = _navbat(eng, S,
                _smena_ochish(b_kassir, commit_kechiktir=True),   # B do'koni
                _nofaol_qilish(a_bids[0], a_ega))                 # A do'koni

    assert not isinstance(r["a"], Exception), r["a"]
    assert not isinstance(r["b"], Exception), ("boshqa do'kon bloklab qo'ydi", r["b"])
    assert not _filial_faolmi(S, a_bids[0])
    #  B do'konining smenasi TEGILMAGAN va o'z filialida.
    b_smena, b_yozuv, b_faol = _holat(S, b_kassir)
    assert b_smena == b_bids[0] and b_yozuv == b_bids[0] and b_faol is True


# ══ 5. XODIMGA BIRIKTIRILGANLIK YO'LI ══════════════════════════════════════

def test_BIRIKTIRILGAN_XODIMNING_smenasi_BOSHQA_filialda_bolsa_ham_RAD(pg_target):
    """Smena B2 da ochilgan, kassir esa B1 ga biriktirilgan: B1 nofaol
    qilinsa kassirning YOZUV filiali siljirdi. Ikkinchi darvoza shuni to'sadi
    va u ham AYNI qulf ostida ishlaydi."""
    from app.models.auth import EmployeeBranch
    _eng, S = _baza(pg_target)
    _cid, bids, kassir, ega = _dokon(S, filiallar=3)

    #  Kassirni B2 ga ko'chiramiz, smenani B2 da ochamiz, keyin B1 ga qaytaramiz:
    #  natija — smena B2 da, biriktiruv B1 da.
    s = S()
    try:
        s.query(EmployeeBranch).filter(EmployeeBranch.employee_id == kassir).update(
            {"branch_id": bids[1]})
        s.commit()
    finally:
        s.close()
    s = S()
    try:
        _smena_ochish(kassir)(s)
        s.commit()
    finally:
        s.close()
    s = S()
    try:
        s.query(EmployeeBranch).filter(EmployeeBranch.employee_id == kassir).update(
            {"branch_id": bids[0]})
        s.commit()
    finally:
        s.close()

    s = S()
    try:
        with pytest.raises(HTTPException) as xato:
            _nofaol_qilish(bids[0], ega)(s)
        assert xato.value.status_code == 400, xato.value.detail
        assert "biriktirilgan" in str(xato.value.detail).lower()
    finally:
        s.rollback()
        s.close()
    assert _filial_faolmi(S, bids[0])


# ══ 6. FILIAL DARVOZASINI FAQAT O'ZI O'LCHAYDIGAN HOLAT ════════════════════

def test_BIRIKTIRILMAGAN_kassirning_smenasi_FILIAL_darvozasi_bilan_TUTILADI(pg_target):
    """⚠️  BU TEST MUTATSIYA NAZORATI TOPGAN KO'RLIKNI YOPADI.

    `PATCH /branches` da ikki darvoza bor: (1) filial bo'yicha ochiq smena,
    (2) filialga BIRIKTIRILGAN xodimda ochiq smena. Mavjud testlarning hammasi
    biriktirilgan kassir bilan ishlaydi, ya'ni (1) ni o'chirib qo'yilsa (2)
    uni TUTIB QOLARDI va test YASHIL qolardi — o'lchangan.

    Bu holat FAQAT (1) ni o'lchaydi: kassir HECH QAYSI filialga biriktirilmagan,
    smenasi esa `actor_branch` ning 2-bosqichi bilan BIRINCHI FAOL filialda
    ochiladi. (2) darvozasi `EmployeeBranch` ga tayanadi va bu yerda hech narsa
    topmaydi — demak filialni nofaol qilishni faqat (1) to'sadi.
    """
    from app.models.auth import EmployeeBranch
    _eng, S = _baza(pg_target)
    _cid, bids, kassir, ega = _dokon(S)

    s = S()
    try:
        #  Biriktiruvni OLIB TASHLAYMIZ -> `actor_branch` 2-bosqichga tushadi.
        s.query(EmployeeBranch).filter(EmployeeBranch.employee_id == kassir).delete()
        s.commit()
    finally:
        s.close()
    s = S()
    try:
        _smena_ochish(kassir)(s)
        s.commit()
    finally:
        s.close()

    smena_bid, yozuv_bid, _ = _holat(S, kassir)
    assert smena_bid == bids[0] == yozuv_bid, (smena_bid, yozuv_bid, bids)

    s = S()
    try:
        with pytest.raises(HTTPException) as xato:
            _nofaol_qilish(bids[0], ega)(s)
        assert xato.value.status_code == 400, xato.value.detail
        assert "filialda ochiq smena" in str(xato.value.detail).lower(), (
            "FILIAL bo'yicha darvoza ishlamadi — xato matni boshqa darvozadan "
            f"keldi: {xato.value.detail}")
    finally:
        s.rollback()
        s.close()
    assert _filial_faolmi(S, bids[0])
