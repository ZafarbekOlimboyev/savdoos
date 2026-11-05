# -*- coding: utf-8 -*-
"""§7AC — SANOQ MANBASI PROVENANSINING LEDGER EGIZAGI (FAQAT Postgres).

NEGA ALOHIDA FAYL, NEGA `tests/cash/`
=====================================
`close_shift_svc` sanoq manbasini IKKI joyga yozadi:
  1. legacy `public.shifts.note` — asosiy to'plamda (SQLite) sinaladi
     (`tests/test_7ac_simulated_cash_count.py`);
  2. ledger egizagi `cash.reconciliation_records.exception_reason` —
     `services/cash/retrofit.on_shift_close` -> `lifecycle._new_recon`
     orqali.

Ikkinchisi SQLite'da UMUMAN BAJARILMAYDI: `retrofit.dual_write_enabled(db)`
`cash_enabled(db)` ni talab qiladi va u SQLite'da `False`, ya'ni hook
GUARDED NO-OP. `cash` sxemasining o'zi ham SQLite'da yo'q.

⚠️  NEGA ASOSIY TESTDAN KO'CHIRILDI. Ilgari bu tasdiq
    `test_08_farq_YASHIRILMAYDI_va_tuzatuvchi_yozuv_YOQ` ichida edi va
    `cash` sxemasi yo'qligida `pytest.skip` qilardi. CI ning
    «Verify tests actually EXECUTED» darvozasi (Phase 4A.1) ro'yxatga
    olinmagan HAR skip'da backend job'ni QIZIL qiladi — va haqli:
    skip'li tasdiq HECH QAYERDA bajarilmay qolardi. Endi u shu yerda,
    HAQIQIY Postgres ustida bajariladi.

⚠️  CI'DA MAJBURIY, SKIP EMAS. `tests/cash/conftest.py` `pgserver`
    yo'qligida CI'da `RuntimeError` otadi (faqat mahalliy yurishda
    modul darajasida skip). `pgserver` `[project.optional-dependencies]
    dev` da e'lon qilingan va CI `pip install -e ".[dev]"` bilan
    o'rnatadi. Ya'ni bu fayl CI'da HAQIQATAN yuradi.

⚠️  TO'G'RIDAN ORM BILAN `ReconciliationRecord` YOZILMAYDI — faqat
    kanonik yo'l (`open_shift_svc` / `close_shift_svc` -> `retrofit`
    hook'lari), aks holda test o'z yozganini o'zi o'qigan bo'lardi.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

TZ = "Asia/Tashkent"


@pytest.fixture()
def demo(db, cashenv):
    """DEMO tenant (kod `demo-...`) + filial + kassir + ACTIVE TILL.

    ⚠️  Kod `demo-` prefiksli bo'lishi SHART: `close_shift_svc` ning
        `SIMULATED` darvozasi `services.historical.is_demo_code` ni
        ishlatadi va haqiqiy do'konda `SIMULATED` ni RAD etadi.
        `cashenv` ning umumiy kompaniyasi demo kodli EMAS, shu bois
        (va boshqa cash testlariga ta'sir qilmaslik uchun) alohida
        tenant qurilади — `test_h2_historical_shift_ledger_pg.py`
        naqshi.
    """
    from app.models.auth import Employee, Role
    from app.models.cash import CashAccount
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    from app.services.cash import till_identity as _ti
    now = datetime.now(timezone.utc)
    comp = Company(id=uuid.uuid4(), name="7AC provenans demo",
                   code=f"demo-7acpg-{uuid.uuid4().hex[:6]}", currency="KGS")
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
                   full_name="7AC kassir",
                   phone=f"+9988{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    till = CashAccount(id=uuid.uuid4(), tenant_id=comp.id, branch_id=br.id,
                       type="TILL", currency="KGS", status="ACTIVE",
                       label=_ti.till_label(f"TILL-{uuid.uuid4().hex[:4]}", None),
                       created_at=now)
    db.add(till)
    db.commit()
    return {"comp": comp, "emp": emp, "br": br, "till": till}


class _Open:
    opening_cash = 1000.0
    terminal_id = None
    till_id = None


class _Close:
    """`CloseShift` o'rniga oddiy tashuvchi (servis qatlami uchun)."""

    def __init__(self, counted_cash, count_source=None, attestation_ref=None):
        self.counted_cash = counted_cash
        self.count_source = count_source
        self.attestation_ref = attestation_ref


def _recons(db, sid):
    from app.models.cash import ReconciliationRecord
    return (db.query(ReconciliationRecord)
            .filter(ReconciliationRecord.shift_id == sid)
            .order_by(ReconciliationRecord.seq)
            .all())


def _yopib_kor(db, demo, body):
    """Smena ochadi, berilgan tana bilan yopadi va recon yozuvlarini qaytaradi."""
    from app.services.shifts import close_shift_svc, open_shift_svc
    _Open.till_id = demo["till"].id
    sh = open_shift_svc(_Open(), demo["emp"], db)
    sid = uuid.UUID(sh["id"])
    out = close_shift_svc(sid, body, demo["emp"], db)
    db.expire_all()
    return sid, out, _recons(db, sid)


def test_SIMULATED_provenansi_LEDGERGA_ham_yoziladi(db, demo):
    """⭐ `exception_reason` da manba va attestatsiya havolasi bo'lishi SHART."""
    from app.services.cash import retrofit as _cr
    assert _cr.dual_write_enabled(db), \
        "dual-write O'CHIQ — bu fayl Postgres'da MAJBURIY yuradi"

    ref = f"synthetic-lab/7acpg/{uuid.uuid4().hex[:8]}"
    sid, out, recs = _yopib_kor(
        db, demo, _Close(1000.00, "SIMULATED", ref))

    assert out["count_source"] == "SIMULATED"
    assert out["attestation_ref"] == ref
    assert recs, "ledger rekonsiliatsiya yozuvi UMUMAN yaratilmadi"
    cur = [r for r in recs if r.is_current]
    assert len(cur) == 1, f"joriy yozuv aynan bitta bo'lishi SHART: {len(cur)}"
    prov = cur[0].exception_reason or ""
    assert "count_source=SIMULATED" in prov, \
        f"ledger qatlamida manba YO'Q: {prov!r}"
    assert f"attestation_ref={ref}" in prov, \
        f"ledger qatlamida havola YO'Q: {prov!r}"


def test_PHYSICAL_ham_AYNIQ_belgilanadi(db, demo):
    """Manbasiz yopish ledgerda `PHYSICAL` deb ko'rinadi, SIMULATED EMAS."""
    sid, out, recs = _yopib_kor(db, demo, _Close(1000.00))
    assert out["count_source"] == "PHYSICAL"
    prov = ([r for r in recs if r.is_current][0].exception_reason) or ""
    assert "count_source=PHYSICAL" in prov, prov
    assert "SIMULATED" not in prov, \
        "manbasiz yopish ledgerda SIMULATED deb YOZILDI — qayta tasnif"
    assert "attestation_ref=-" in prov, prov


def test_farq_AVTOMATIK_kitobga_OLINMAYDI(db, demo):
    """⭐ §18 — farq `PENDING` qoladi, `ADJUSTMENT` legi YOZILMAYDI.

    Bu AYNAN SQLite'da o'lchab bo'lmaydigan tasdiq: `state` ustuni
    `cash.reconciliation_records` da, u esa faqat Postgres'da bor.
    """
    from app.models.cash import CashLedgerEntry as CLE
    ref = f"synthetic-lab/7acpg/{uuid.uuid4().hex[:8]}"
    oldin = db.query(CLE).count()
    sid, out, recs = _yopib_kor(
        db, demo, _Close(950.00, "SIMULATED", ref))

    #  Farq SAQLANADI va yaxlitlanmaydi.
    assert Decimal(str(out["expected_cash"])) == Decimal("1000.00")
    assert Decimal(str(out["counted_cash"])) == Decimal("950.00")
    assert Decimal(str(out["difference"])) == Decimal("-50.00")

    cur = [r for r in recs if r.is_current]
    assert len(cur) == 1
    rec = cur[0]
    assert rec.state == "PENDING", \
        f"farq AVTOMATIK kitobga olindi — taqiq: state={rec.state}"
    assert Decimal(str(rec.counted_cash)) == Decimal("950.00")
    assert Decimal(str(rec.difference)) == Decimal("-50.00")

    #  Farqni «tekislaydigan» ADJUSTMENT legi paydo bo'lmasligi SHART.
    #  ⚠️  `ADJUSTMENT` — `CashCategory` qiymati (`category` ustuni);
    #      `CashLedgerEntry` da `reason` ustuni YO'Q (model o'qildi).
    adj = (db.query(CLE)
           .filter(CLE.shift_id == sid, CLE.category == "ADJUSTMENT")
           .count())
    assert adj == 0, "farq uchun ADJUSTMENT legi YOZILDI — §18 buzildi"
    assert db.query(CLE).count() >= oldin, "ledger legilari YO'QOLDI"
