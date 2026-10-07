# -*- coding: utf-8 -*-
"""H2 — TARIXIY SMENANING LEDGER EGIZAGI (FAQAT Postgres).

NEGA ALOHIDA, POSTGRES'DA
=========================
H2 smena servisi tarixiy `at` ni IKKI joyga uzatadi:
  1. legacy `public.shifts.opened_at` / `closed_at`;
  2. ledger egizagi `cash.shifts.opened_at` / `closed_at` + reconciliation
     yozuvi — `services/cash/retrofit.on_shift_open` / `on_shift_close` orqali.

Ikkinchisi SQLite'da UMUMAN BAJARILMAYDI: `retrofit.dual_write_enabled(db)`
`cash_enabled(db)` ni talab qiladi va u SQLite'da `False` (o'lchangan). Ya'ni
asosiy to'plam (`tests/test_h2_historical_shift_sale.py`) ledger egizagiga
uzatilgan `at` ni KO'RMAYDI — u yerda hook GUARDED NO-OP.

⚠️  SHU BOIS BU FAYL BOR. Aks holda H2 tekshirilMAGAN kod yo'li bilan ketardi:
    `at` hook'ga uzatilmay qolsa ham mahalliy to'plam YASHIL bo'lardi, ledger
    egizagi esa BUGUNGI sana bilan ochilib, `posting._in_window` (smena oynasi)
    tarixiy legilarni YO'QOTARDI. Bu loyihaning ma'lum tuzoq sinfi: SQLite
    ko'rmaydigan narsa Postgres'da sinalishi SHART.

⚠️  TO'G'RIDAN ORM BILAN `CashShift` YOZILMAYDI — faqat kanonik yo'l
    (`open_shift_svc` / `close_shift_svc` -> `retrofit` hook'lari).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import historical as H

TZ = "Asia/Tashkent"
DEPTH = 130
PLAN = "h2-ledger-pg"


def _aw(dt):
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture()
def demo(db, cashenv):
    """DEMO tenant (kod `demo-...`, T0 YO'Q) + filial + kassir + ACTIVE TILL.

    `cashenv` ning umumiy kompaniyasi ISHLATILMAYDI: H1 darvozasi `test`/`demo`
    kodli do'konni TALAB qiladi va umumiy fixture'ni qayta nomlash ayni
    sessiyadagi boshqa cash testlarini o'zgartirib yuborardi.
    """
    from app.models.auth import Employee, Role
    from app.models.cash import CashAccount
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    now = datetime.now(timezone.utc)
    comp = Company(id=uuid.uuid4(), name="H2 ledger demo",
                   code=f"demo-h2pg-{uuid.uuid4().hex[:6]}", currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                timezone=TZ, is_active=True, created_at=now - timedelta(days=400))
    db.add(br)
    db.flush()
    role = db.query(Role).first()
    if role is None:
        role = Role(id=uuid.uuid4(), code="ega", name="Ega")
        db.add(role)
        db.flush()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                   full_name="H2 kassir", phone=f"+9988{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    #  Maydonlar AYNAN modeldagidek: `type`/`label` (`code`/`name`/`account_type` YO'Q).
    #  Yorliq `till_identity.till_label` bilan — mavjud cash testlari naqshi.
    from app.services.cash import till_identity as _ti
    till = CashAccount(id=uuid.uuid4(), tenant_id=comp.id, branch_id=br.id,
                       type="TILL", currency="KGS", status="ACTIVE",
                       label=_ti.till_label(f"TILL-{uuid.uuid4().hex[:4]}", None),
                       created_at=now)
    db.add(till)
    db.commit()
    return {"comp": comp, "emp": emp, "br": br, "till": till}


class _Open:
    opening_cash = 0.0
    terminal_id = None
    till_id = None


class _Close:
    counted_cash = 0.0


def test_ledger_egizagi_TARIXIY_vaqtni_oladi(db, demo):
    """`cash.shifts.opened_at`/`closed_at` AYNAN tarixiy paytda bo'lishi SHART.

    Agar `at` hook'ga uzatilmasa, bu test QIZIL bo'ladi: egizak BUGUN ochilgan
    bo'lib ko'rinadi va legacy jadval bilan AJRALIB ketadi.
    """
    from app.models.cash import CashShift
    from app.services.cash import retrofit as _cr
    from app.services.shifts import close_shift_svc, open_shift_svc

    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq (cash sxemasi yo'q) — ledger egizagi o'lchanmaydi")

    _Open.till_id = demo["till"].id
    day = (datetime.now(timezone.utc) - timedelta(days=DEPTH)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    t_open, t_close = day + timedelta(hours=9), day + timedelta(hours=18)

    with H.enter(db, demo["comp"], plan_id=PLAN, instant=t_open) as ctx:
        sh = open_shift_svc(_Open(), demo["emp"], db, at=t_open,
                            client_uuid=ctx.key("d", "shift", "open"))
    sid = uuid.UUID(sh["id"])

    twin = db.get(CashShift, sid)
    assert twin is not None, "ledger egizagi UMUMAN yaratilmadi"
    assert _aw(twin.opened_at).date() == t_open.date(), \
        f"egizak opened_at TARIXIY emas: {twin.opened_at}"
    assert abs((_aw(twin.opened_at) - t_open).total_seconds()) < 2, \
        f"egizak opened_at legacy bilan AJRALDI: {twin.opened_at} != {t_open}"

    with H.enter(db, demo["comp"], plan_id=PLAN, instant=t_close):
        close_shift_svc(sid, _Close(), demo["emp"], db, at=t_close)

    db.expire_all()
    twin = db.get(CashShift, sid)
    assert twin.status == "CLOSED", f"egizak yopilmadi: {twin.status}"
    assert abs((_aw(twin.closed_at) - t_close).total_seconds()) < 2, \
        f"egizak closed_at TARIXIY emas: {twin.closed_at} != {t_close}"

    # Legacy va egizak AYNI paytda — ikkisi ajralsa smena oynasi buzilardi.
    from app.models.shifts import Shift
    leg = db.get(Shift, sid)
    assert abs((_aw(leg.opened_at) - _aw(twin.opened_at)).total_seconds()) < 2
    assert abs((_aw(leg.closed_at) - _aw(twin.closed_at)).total_seconds()) < 2


def test_reconciliation_yozuvi_ham_TARIXIY(db, demo):
    """Yopishda yoziladigan reconciliation surati ham tarixiy paytni oladi."""
    from app.services.cash import retrofit as _cr
    from app.services.shifts import close_shift_svc, open_shift_svc

    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq — reconciliation o'lchanmaydi")

    _Open.till_id = demo["till"].id
    day = (datetime.now(timezone.utc) - timedelta(days=DEPTH + 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    t_open, t_close = day + timedelta(hours=9), day + timedelta(hours=17)
    with H.enter(db, demo["comp"], plan_id=PLAN + "-rec", instant=t_open) as ctx:
        sh = open_shift_svc(_Open(), demo["emp"], db, at=t_open,
                            client_uuid=ctx.key("d2", "shift", "open"))
    sid = uuid.UUID(sh["id"])
    with H.enter(db, demo["comp"], plan_id=PLAN + "-rec", instant=t_close):
        close_shift_svc(sid, _Close(), demo["emp"], db, at=t_close)

    rows = db.execute(
        __import__("sqlalchemy").text(
            "SELECT created_at FROM cash.reconciliation_records WHERE shift_id = :s"),
        {"s": str(sid)}).all()
    assert rows, "reconciliation yozuvi YO'Q"
    for (created,) in rows:
        assert abs((_aw(created) - t_close).total_seconds()) < 5, \
            f"reconciliation BUGUNGI sana bilan yozildi: {created} != {t_close}"
