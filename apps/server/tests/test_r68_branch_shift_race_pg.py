# -*- coding: utf-8 -*-
"""R6.8 P0-2 — «SMENA OCHISH» × «FILIAL ALMASHTIRISH» POYGASI, HAQIQIY POSTGRES.

POYGA (tuzatishdan OLDIN mavjud edi, bu faylning manfiy nazorati bilan
o'lchangan): `PATCH /employees/{id}` filial o'zgarishidan oldin «ochiq smena
bormi?» ni QULFSIZ o'qiydi, `POST /shifts/open` esa yozuv filialini
(`deps.actor_branch`) ham QULFSIZ o'qiydi. Ikki tranzaksiya bir-birini
ko'rmasdan commit qiladi:

    T1 (filial A->B):  ochiq smena YO'Q  ->  EmployeeBranch = B   commit
    T2 (smena ochish): actor_branch = A  ->  Shift(branch=A)      commit

Natija ZID: ochiq smena A filialда, xodim esa B da. O'sha smenaning KEYINGI
cheklari (`services/sales.py:212 _ab(emp, db)`) B ga tushadi — bitta smena ikki
filialga bo'linadi va yozuvlar immutable.

TUZATISH ikki tomonlama va AYNI qatorga tayanadi:
  · `api/v1/employees.py::_assert_branch_change_allowed` — tekshirishdan OLDIN
    `employees` qatorini `FOR UPDATE` qiladi;
  · `services/shifts.py::open_shift_svc` — `actor_branch` o'qilishidan OLDIN
    AYNI qatorni `FOR UPDATE` qiladi.

Bu fayl isbotlaydi (har holatda IKKALA commit'dan keyin INVARIANT BUTUN:
`shift.branch_id == EmployeeBranch.branch_id`):
  1. filial almashtirish BIRINCHI qulflaydi -> smena ochish KUTADI va YANGI
     filialda ochiladi;
  2. smena ochish BIRINCHI qulflaydi -> filial almashtirish KUTADI va keyin
     RAD etiladi (400), biriktiruv TEGILMAYDI;
  3. AYNI filialni qayta yuborish ochiq smenada ham o'tadi (idempotentlik
     poyga ostida ham buzilmaydi).

⚠️  INTERLEAVING MAJBURIY, TASODIFIY EMAS (`test_lot_tz_confirm_pg._navbat`):
    birinchi tranzaksiya yozib commit QILMAY turadi; ikkinchisi uning qulfini
    kutayotgani `pg_blocking_pids` da KO'RILGACH birinchisi commit qiladi.
    Kutish ko'rilmasa sinov QIZIL (`kutdi`) — ya'ni qulf olinmagani JIM
    o'tib ketmaydi.

⚠️  OSILMAYDI: `_mk` har ulanishga `lock_timeout`/`statement_timeout` qo'yadi,
    `_navbat` iplarni `join(90)` bilan kutadi.

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


def _dokon(S):
    """Kompaniya + IKKI faol filial + A ga biriktirilgan kassir.

    Qaytaradi: (company_id, branch_a, branch_b, employee_id).
    """
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.org import Branch, Company
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="R68 PG", code="r68" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        bids = []
        for i in range(2):
            b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}", name=f"B{i + 1}",
                       timezone=TZ, is_active=True, created_at=NOW - timedelta(days=10 - i))
            s.add(b)
            s.flush()
            bids.append(b.id)
        role = s.query(Role).filter(Role.code == "kassir").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name="R68 kassir",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=role.id)
        s.add(e)
        s.flush()
        s.add(EmployeeBranch(employee_id=e.id, branch_id=bids[0]))
        s.commit()
        return co.id, bids[0], bids[1], e.id
    finally:
        s.close()


def _holat(S, eid):
    """(biriktirilgan_filial, ochiq_smena_filiali) — ikkala commit'dan KEYIN."""
    from app.models.auth import EmployeeBranch
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        row = (s.query(EmployeeBranch.branch_id)
               .filter(EmployeeBranch.employee_id == eid).first())
        sh = (s.query(Shift)
              .filter(Shift.cashier_id == eid, Shift.status == ShiftStatus.open).first())
        return (row[0] if row else None), (sh.branch_id if sh else None)
    finally:
        s.close()


def _filial_almashtirish(eid, yangi_bid, cid):
    """`PATCH /employees/{id}` ning FILIAL yo'li — darvoza + yozuv, AYNAN."""
    def _ish(s):
        from app.api.v1.employees import _assert_branch_change_allowed, _set_branch
        _assert_branch_change_allowed(s, eid, str(yangi_bid))
        _set_branch(s, eid, str(yangi_bid), cid)
        return "almashtirildi"
    return _ish


def _smena_ochish(eid, *, commit_kechiktir: bool = False):
    """`POST /shifts/open` ning kanonik tanasi, xodim tokeni bilan AYNI yo'l.

    `commit_kechiktir=True` — `open_shift_svc` O'Z ICHIDA `db.commit()` qiladi
    (`services/shifts.py:179`), ya'ni `_navbat` ning «yozib, commit QILMAY tur»
    shartini BUZADI: tranzaksiya yopilib qulf bo'shaydi va ikkinchi tranzaksiya
    kutishga ULGURMAYDI (o'lchangan: `kutdi` False). Shu bois shu chaqiruv
    doirasida `commit` VAQTINCHA `flush` ga almashtiriladi.

    ⚠️  PRODUCTION TANASI O'ZGARMAYDI — bayt-bayt AYNI kod ishlaydi; faqat
        YAKUNIY commit `_navbat` ga qoldiriladi (u poyga oynasini ko'rgach
        o'zi commit qiladi). Asl `commit` darhol tiklanadi.
    """
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


def _ochiq_smena_yozib(S, eid, bid):
    """Ochiq smenani TO'G'RIDAN yozadi (2-holatning boshlang'ich sharti)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        sh = Shift(id=uuid.uuid4(), branch_id=bid, cashier_id=eid, opened_at=NOW,
                   opening_cash=Decimal("0"), status=ShiftStatus.open)
        s.add(sh)
        s.commit()
        return sh.id
    finally:
        s.close()


def _kutdi(r):
    assert r["kutdi"] is True, \
        f"ikkinchi tranzaksiya qulfni KUTMADI — poyga oynasi ochilmadi: {r}"


# ══ 1. FILIAL ALMASHTIRISH BIRINCHI QULFLAYDI ════════════════════════════════

def test_filial_almashtirish_birinchi_smena_YANGI_filialda_ochiladi(pg_target):
    """T1 xodim qatorini qulflab filialni B ga o'zgartiradi; T2 (smena ochish)
    KUTADI va T1 commit'idan keyin YANGI (B) filialni o'qiydi.

    MANFIY NAZORAT (qulflardan oldin): T2 KUTMAYDI (`kutdi` False) va smena
    ESKI (A) filialda ochiladi — `_holat` ikki xil filial qaytarardi.
    """
    eng, S = _baza(pg_target)
    cid, a, b, eid = _dokon(S)

    r = _navbat(eng, S, _filial_almashtirish(eid, b, cid), _smena_ochish(eid))

    _kutdi(r)
    assert not isinstance(r["a"], Exception), r["a"]
    assert not isinstance(r["b"], Exception), r["b"]
    bir_filial, smena_filial = _holat(S, eid)
    assert bir_filial == b, "filial almashtirish commit bo'lmadi"
    assert smena_filial == b, \
        f"smena ESKI filialda ochildi: smena={smena_filial} biriktiruv={bir_filial}"
    assert smena_filial == bir_filial, "INVARIANT BUZILDI: smena va biriktiruv boshqa filialda"
    eng.dispose()


# ══ 2. SMENA OCHISH BIRINCHI QULFLAYDI ═══════════════════════════════════════

def test_smena_ochish_birinchi_filial_almashtirish_RAD_etiladi(pg_target):
    """T1 smena ochib qatorni qulflaydi; T2 (filial almashtirish) KUTADI va
    T1 commit'idan keyin ochiq smenani KO'RADI -> 400, biriktiruv TEGILMAYDI.

    MANFIY NAZORAT (qulflardan oldin): T2 KUTMAYDI va `EmployeeBranch` B ga
    o'tib ketardi — ochiq smena esa A da qolardi.
    """
    eng, S = _baza(pg_target)
    cid, a, b, eid = _dokon(S)

    r = _navbat(eng, S, _smena_ochish(eid, commit_kechiktir=True),
                _filial_almashtirish(eid, b, cid))

    _kutdi(r)
    assert not isinstance(r["a"], Exception), r["a"]
    assert isinstance(r["b"], HTTPException), f"filial almashtirish RAD ETILMADI: {r['b']}"
    assert r["b"].status_code == 400, r["b"]
    assert "smena" in r["b"].detail.lower(), r["b"].detail
    bir_filial, smena_filial = _holat(S, eid)
    assert bir_filial == a, "rad etilgan o'zgarish biriktiruvni SURDI"
    assert smena_filial == a
    assert smena_filial == bir_filial, "INVARIANT BUZILDI: smena va biriktiruv boshqa filialda"
    eng.dispose()


# ══ 3. IDEMPOTENTLIK POYGA OSTIDA ════════════════════════════════════════════

def test_AYNI_filial_poyga_ostida_ham_otadi(pg_target):
    """Ochiq smena BOR, lekin so'rov AYNI filialni qayta yuboradi — bu
    O'ZGARISH emas, demak darvoza o'tkazishi SHART (aks holda takroriy PATCH
    va boshqa maydonlarni tahrirlash ochiq smenada butunlay to'silardi)."""
    eng, S = _baza(pg_target)
    cid, a, _b, eid = _dokon(S)
    _ochiq_smena_yozib(S, eid, a)

    s = S()
    try:
        from app.api.v1.employees import _assert_branch_change_allowed, _set_branch
        _assert_branch_change_allowed(s, eid, str(a))      # istisno OTMASLIGI shart
        _set_branch(s, eid, str(a), cid)
        s.commit()
    finally:
        s.close()

    bir_filial, smena_filial = _holat(S, eid)
    assert bir_filial == a
    assert smena_filial == a
    eng.dispose()


def test_bosh_branch_id_ochiq_smenada_RAD_etiladi(pg_target):
    """Biriktiruvni OLIB TASHLASH ham o'zgarish: `actor_branch` zaxira
    «birinchi faol filial» ga tushib ketardi, ya'ni atributsiya SURILARDI."""
    eng, S = _baza(pg_target)
    cid, a, _b, eid = _dokon(S)
    _ochiq_smena_yozib(S, eid, a)

    s = S()
    try:
        from app.api.v1.employees import _assert_branch_change_allowed
        with pytest.raises(HTTPException) as ei:
            _assert_branch_change_allowed(s, eid, "")
        assert ei.value.status_code == 400
        s.rollback()
    finally:
        s.close()

    bir_filial, _ = _holat(S, eid)
    assert bir_filial == a
    eng.dispose()
