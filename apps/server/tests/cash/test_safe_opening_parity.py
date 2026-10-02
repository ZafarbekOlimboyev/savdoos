# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ochilishining PARITY/HISOBOT oqibatlari (real PostgreSQL).

Shartnoma: `docs/PURCHASE_SETTLEMENT_PHASE1.md` §6, testlar T-13…T-16 va T-20.

⚠️  MARKAZIY SAVOL. Ochilish legi `provenance='NORMAL'` (B1), ya'ni u `compare_engine`
    ning `EXTRA_LEDGER` shoxiga TUSHADI. Uni faqat ANIQ MANBA SHARTNOMASI yopadi:
    `cash.cash_account_openings` da MOS `COUNTED` qator bo'lsa — kutilgan; bo'lmasa
    (soxta/manbasiz/takroriy leg) — HAMON nomuvofiqlik. Bu «ADJUSTMENT ni kechiramiz»
    EMAS.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashAccountOpening
from app.models.cash import CashLedgerEntry as CLE
from app.models.org import Branch, Company
from app.services.cash import compare_engine as ce
from app.services.cash import safe_opening as so
from app.services.cash import shadow_compare as sc
from app.services.cash import till_identity as _ti

REF = "SANOQ-AKT-01"


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _T0():
    return _now() - timedelta(days=1)


def _acct(db, co, br, typ):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type=typ, currency="UZS", status="ACTIVE",
                    label=(_ti.till_label("T-" + _hex(), None) if typ == "TILL"
                           else _ti.safe_label("S-" + _hex())), created_at=_now())
    db.add(a)
    db.flush()
    return a


def _tenant(db):
    """Yangi TENANT + filial + MENEJER + TILL + SAFE (toza reconcile uchun)."""
    co = Company(name="P1" + _hex(), code="p1" + _hex(), currency="UZS")
    db.add(co)
    db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(br)
    db.flush()
    role = db.query(Role).filter(Role.code == "menejer").first()
    if role is None:
        role = Role(code="menejer", name="Menejer")
        db.add(role)
        db.flush()
    emp = Employee(company_id=co.id, full_name="M", role_id=role.id)
    db.add(emp)
    db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = _acct(db, co, br, "TILL")
    safe = _acct(db, co, br, "SAFE")
    db.commit()
    emp.role
    return co, br, emp, till, safe


def _attest(db, emp, safe, amount="900000.00"):
    return so.attest_opening(db, emp, account=safe, kind="COUNTED", counted_amount=amount,
                             counted_at=_now(), attestation_ref=REF)


def _rec(db, co):
    return ce.reconcile_events(db, co.id, t0=_T0())


def _codes(r):
    return r["mismatch_counts"]


# ═══ T-14) MOS manba bor -> NOMUVOFIQLIK YO'Q ══════════════════════════════
def test_14_ochilish_legi_mos_manba_bilan_toza(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    row, _ = _attest(db, emp, safe)
    r = _rec(db, co)
    assert _codes(r) == {}, r["mismatches"][:3]
    assert r["matched"] >= 1


# ═══ T-15a) MANBASIZ (soxta) leg -> EXTRA_LEDGER ═══════════════════════════
def test_15a_manbasiz_ochilish_legi_extra_ledger(db, cashenv):
    """⚠️  SEZGIRLIK: aynan shu leg manba shartnomasisiz "kechirilib" ketmasligi kerak."""
    co, br, emp, till, safe = _tenant(db)
    db.add(CLE(tenant_id=co.id, cash_account_id=safe.id, branch_id=br.id, account_type="SAFE",
               shift_id=None, posting_kind="OFF_SHIFT", source_type="ACCOUNT_OPENING",
               source_id=uuid.uuid4(), leg_index=0, direction="IN", category="ADJUSTMENT",
               amount=Decimal("5000000.00"), currency="UZS", device_occurred_at=_now(),
               server_received_at=_now(), recorded_at=_now(), actor_id=emp.id,
               idempotency_key=str(uuid.uuid4()), provenance="NORMAL"))
    db.commit()
    assert _codes(_rec(db, co)).get(ce.EXTRA_LEDGER) == 1


# ═══ T-15b) SUMMA manbadan boshqa -> WRONG_AMOUNT ══════════════════════════
def test_15b_summa_manbaga_mos_emas(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    row, _ = _attest(db, emp, safe, amount="900000.00")
    db.commit()
    # Ledger o'zgarmas, shu bois SOXTA leg BOSHQA manba qatori nomi ostida yoziladi:
    # ayni `source_id`, lekin summa boshqa — buning uchun ikkinchi hisob va ikkinchi
    # ochilish yaratamiz, keyin uning legini ataylab NOTO'G'RI summada yozamiz.
    safe2 = _acct(db, co, br, "SAFE")
    db.commit()
    oid = uuid.uuid4()
    db.add(CashAccountOpening(
        id=oid, tenant_id=co.id, cash_account_id=safe2.id, account_type="SAFE",
        kind="COUNTED", counted_amount=Decimal("100000.00"), currency="UZS",
        counted_at=_now(), attested_by=emp.id, attestation_ref=REF,
        ledger_entry_id=None, created_at=_now()))
    # ⚠️  `ck_cao_kind_ledger` COUNTED uchun leg majburiy — shu bois avval legni yozamiz
    db.rollback()
    e = CLE(tenant_id=co.id, cash_account_id=safe2.id, branch_id=br.id, account_type="SAFE",
            shift_id=None, posting_kind="OFF_SHIFT", source_type="ACCOUNT_OPENING",
            source_id=oid, leg_index=0, direction="IN", category="ADJUSTMENT",
            amount=Decimal("999999.00"),            # manbadagi 100000 EMAS
            currency="UZS", device_occurred_at=_now(), server_received_at=_now(),
            recorded_at=_now(), actor_id=emp.id, idempotency_key=str(uuid.uuid4()),
            provenance="NORMAL")
    db.add(e)
    db.flush()
    db.add(CashAccountOpening(
        id=oid, tenant_id=co.id, cash_account_id=safe2.id, account_type="SAFE",
        kind="COUNTED", counted_amount=Decimal("100000.00"), currency="UZS",
        counted_at=_now(), attested_by=emp.id, attestation_ref=REF,
        ledger_entry_id=e.id, created_at=_now()))
    db.commit()
    codes = _codes(_rec(db, co))
    assert codes.get(ce.WRONG_AMOUNT) == 1, codes


# ═══ T-15c) TAKRORIY leg (leg_index=1) -> EXTRA_LEDGER ═════════════════════
def test_15c_takroriy_ochilish_legi(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    row, _ = _attest(db, emp, safe)
    db.commit()
    db.add(CLE(tenant_id=co.id, cash_account_id=safe.id, branch_id=br.id, account_type="SAFE",
               shift_id=None, posting_kind="OFF_SHIFT", source_type="ACCOUNT_OPENING",
               source_id=row.id, leg_index=1,        # AYNI manba, IKKINCHI oyoq
               direction="IN", category="ADJUSTMENT", amount=Decimal("1.00"), currency="UZS",
               device_occurred_at=_now(), server_received_at=_now(), recorded_at=_now(),
               actor_id=emp.id, idempotency_key=str(uuid.uuid4()), provenance="NORMAL"))
    db.commit()
    assert _codes(_rec(db, co)).get(ce.EXTRA_LEDGER) == 1


# ═══ T-16) shadow_compare: ochilish DELTA bermaydi, boshqa ADJUSTMENT BERADI ══
def test_16_shadow_compare_ochilish_delta_bermaydi(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    base = sc.compare_branch(db, co.id, br.id, t0=_T0())
    _attest(db, emp, safe, amount="750000.00")
    db.commit()
    after = sc.compare_branch(db, co.id, br.id, t0=_T0())
    assert after["delta"] == base["delta"], "ochilish legi SOXTA delta berdi"

    # ⚠️  MANFIY NAZORAT: BOSHQA NORMAL ADJUSTMENT (CASH_OP) HAMON ko'rinadi —
    #     ya'ni biz «ADJUSTMENT toifasini» yoki «NORMAL qatorlarni» chiqarib
    #     tashlamadik, faqat AYNAN `ACCOUNT_OPENING` manba turini.
    db.add(CLE(tenant_id=co.id, cash_account_id=safe.id, branch_id=br.id, account_type="SAFE",
               shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP",
               source_id=uuid.uuid4(), leg_index=0, direction="IN", category="ADJUSTMENT",
               amount=Decimal("60000.00"), currency="UZS", device_occurred_at=_now(),
               server_received_at=_now(), recorded_at=_now(), actor_id=emp.id,
               idempotency_key=str(uuid.uuid4()), provenance="NORMAL"))
    db.commit()
    noisy = sc.compare_branch(db, co.id, br.id, t0=_T0())
    assert noisy["delta"] != base["delta"], "boshqa ADJUSTMENT ham yashirilib qoldi"


# ═══ T-13) SEYF ochilishi TILL jamlariga KIRMAYDI ══════════════════════════
def test_13_till_jamlariga_kirmaydi(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    from app.services.cash import repositories as repo
    before = repo.account_balance(db, co.id, till.id)
    _attest(db, emp, safe, amount="1000000.00")
    db.commit()
    assert repo.account_balance(db, co.id, till.id) == before, "SEYF ochilishi TILLga tegdi"
    assert repo.account_balance(db, co.id, safe.id) == Decimal("1000000.00")


# ═══ T-13b) HISOBOT: `kassada` SEYF ochilishidan O'ZGARMAYDI ══════════════
def test_13b_cashflow_kassada_ozgarmaydi(db, cashenv):
    """⚠️  `/reports/cashflow` ledger-avtoritet tenantda `category_totals` ni O'QIYDI —
        ochilish legi esa `ADJUSTMENT` toifasida. Hisobot faqat `PURCHASE_OUT` va
        `PURCHASE_RETURN` ni oladi, shu bois `kassada` TEGILMASLIGI kerak. Bu test
        o'sha da'voni KOD ustida emas, JAVOB ustida isbotlaydi."""
    from datetime import timedelta as _td

    from app.api.v1 import reports as reports_api
    from app.models.settings import Setting

    co, br, emp, till, safe = _tenant(db)
    iso = (_now() - _td(hours=2)).isoformat()
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"ledger_native": True, "onboarded_at": iso, "cutover_at": iso}))
    db.commit()
    before = reports_api.cashflow(period="day", emp=emp, db=db)
    assert before["ledger_native"] is True

    _attest(db, emp, safe, amount="2500000.00")
    db.commit()
    after = reports_api.cashflow(period="day", emp=emp, db=db)
    assert after["kassada"] == before["kassada"], "SEYF ochilishi `kassada` ni o'zgartirdi"
    assert after["in"] == before["in"] and after["out"] == before["out"]


# ═══ T-20) BACKFILL VERIFIKATSIYASI O'ZGARMAYDI ════════════════════════════
def test_20_backfill_verifikatsiyasi_tegilmagan(db, cashenv):
    """(a) ochilishdan keyin RECONSTRUCTION to'plami BO'SH qoladi;
       (b) qo'lda qo'shilgan RECONSTRUCTION qatori HAMON yiqitadi.

    ⚠️  Ochilish legi NORMAL, ya'ni u `verify_backfill` ning ko'rish maydoniga UMUMAN
        kirmaydi — darvoza kuchsizlantirilmagan."""
    from app.db.cash.migration import backfill

    co, br, emp, till, safe = _tenant(db)
    _attest(db, emp, safe, amount="400000.00")
    db.commit()
    manifest = {"inserted_rows": 0, "already_existing_rows": 0, "in_total": 0.0,
                "out_total": 0.0, "review": []}
    v = backfill.verify_backfill(db, manifest, company_id=co.id)
    assert v["all_ok"] is True, v

    db.add(CLE(tenant_id=co.id, cash_account_id=safe.id, branch_id=br.id, account_type="SAFE",
               shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP",
               source_id=uuid.uuid4(), leg_index=0, direction="IN", category="ADJUSTMENT",
               amount=Decimal("10.00"), currency="UZS", device_occurred_at=_now(),
               server_received_at=_now(), recorded_at=_now(), actor_id=emp.id,
               idempotency_key=str(uuid.uuid4()), provenance="RECONSTRUCTION",
               reconstruction_reason="test", reconstruction_source_ref="test"))
    db.commit()
    v2 = backfill.verify_backfill(db, manifest, company_id=co.id)
    assert v2["all_ok"] is False, "kutilmagan RECONSTRUCTION endi TUTILMAYAPTI"
    assert v2["row_count_matches"] is False


# ═══ compare_engine FAQAT O'QIYDI (mavjud qo'riqchi bilan izchil) ══════════
def test_compare_engine_ochilishni_yozmaydi(db, cashenv):
    co, br, emp, till, safe = _tenant(db)
    _attest(db, emp, safe)
    db.commit()
    n_open = db.query(CashAccountOpening).count()
    n_leg = db.query(CLE).count()
    _rec(db, co)
    assert db.query(CashAccountOpening).count() == n_open
    assert db.query(CLE).count() == n_leg
