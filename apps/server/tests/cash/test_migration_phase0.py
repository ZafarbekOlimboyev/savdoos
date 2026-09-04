# -*- coding: utf-8 -*-
"""Migration Phase 0 — Prepare & Production Readiness — validatsiya testlari (real PostgreSQL).

§16 dagi 15 ta test. Read-only tahlil + report-only dry-run + idempotent provisioning + readiness.
Har test O'Z kompaniyasini quradi (flush, commit EMAS -> db fixture rollback bilan izolyatsiya) va
dry_run/mapping'ni SHU tenant'ga scope qiladi (shared pgserver bazasида boshqa test ma'lumoti aralashmasin).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.cash.migration import phase0
from app.models.auth import Employee, Role
from app.models.cash import CashAccount, CashLedgerEntry
from app.models.enums import PurchaseStatus, ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.enums import CashMovementType, CreditTxnType
from app.models.purchasing import Purchase, Supplier, SupplierLedger
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift
from app.services.cash import repositories as repo


def _hex():
    return uuid.uuid4().hex[:8]


def _co(db, cashenv, cur="UZS"):
    c = Company(name="Co" + _hex(), code="c" + _hex(), currency=cur)
    db.add(c); db.flush()
    return c


def _br(db, co, active=True):
    b = Branch(company_id=co.id, code="B" + _hex(), name="Br", is_active=active)
    db.add(b); db.flush()
    return b


def _term(db, br):
    t = Terminal(branch_id=br.id, name="T" + _hex())
    db.add(t); db.flush()
    return t


def _emp(db, co):
    role = db.query(Role).first()
    e = Employee(company_id=co.id, full_name="Kassir", role_id=role.id)
    db.add(e); db.flush()
    return e


def _shift(db, cashenv, br, emp, terminal=None, status=ShiftStatus.open, opening=0):
    s = Shift(branch_id=br.id, cashier_id=emp.id,
              terminal_id=(terminal.id if terminal else None),
              opened_at=cashenv.now, opening_cash=Decimal(str(opening)), status=status)
    db.add(s); db.flush()
    return s


def _sale_cash(db, cashenv, co, br, emp, amount):
    s = Sale(receipt_no="R" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
             subtotal=Decimal(str(amount)), total=Decimal(str(amount)), sold_at=cashenv.now)
    db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal(str(amount)), paid_at=cashenv.now))
    db.flush()
    return s


def _received_purchase(db, cashenv, co, br, total):
    sup = Supplier(company_id=co.id, name="Sup" + _hex())
    db.add(sup); db.flush()
    p = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                 purchase_date=cashenv.now.date(), status=PurchaseStatus.received,
                 subtotal=Decimal(str(total)), total=Decimal(str(total)), paid_amount=Decimal(str(total)))
    db.add(p); db.flush()
    return p


# ── §16.1 mapping idempotency ────────────────────────────────────────────────
def test_mapping_idempotency(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    m, _ = phase0.propose_till_mapping(db, company_id=co.id)
    phase0.provision_accounts(db, m, apply=True)
    phase0.provision_accounts(db, m, apply=True)   # ikkinchi marta — dublikat yaratmasligi kerak
    n = db.query(CashAccount).filter(CashAccount.branch_id == br.id, CashAccount.type == "TILL").count()
    assert n == 1


# ── §16.2 duplicate mapping detection ────────────────────────────────────────
def test_duplicate_mapping_detection(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    m, _ = phase0.propose_till_mapping(db, company_id=co.id)
    p1 = phase0.provision_accounts(db, m, apply=True)
    assert p1["to_create"] == 1 and p1["existing"] == 0
    p2 = phase0.provision_accounts(db, m, apply=False)   # endi mavjud
    assert p2["to_create"] == 0 and p2["existing"] == 1  # DUBLIKAT aniqlanди (create emas)


# ── §16.3 missing till identity (legacy'да fizik-till entity yo'q -> branch = identity) ──
def test_missing_till_identity(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, terminal=None, opening=1000)   # terminal YO'Q
    m, findings = phase0.propose_till_mapping(db, company_id=co.id)
    assert len(m) == 1 and m[0].confidence == "HIGH"           # branch bitta TILL (identity = branch)
    assert not any(f.code == "TILL_AMBIGUOUS" for f in findings)


# ── §16.4 multiple tills (ambiguous) ─────────────────────────────────────────
def test_multiple_tills_ambiguous(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    t1, t2 = _term(db, br), _term(db, br)
    _shift(db, cashenv, br, emp, terminal=t1)
    _shift(db, cashenv, br, emp, terminal=t2)                   # ikki alohida terminal
    m, findings = phase0.propose_till_mapping(db, company_id=co.id)
    assert m[0].confidence == "AMBIGUOUS" and m[0].distinct_terminals == 2
    assert any(f.code == "TILL_AMBIGUOUS" and f.severity == phase0.BLOCK for f in findings)


# ── §16.5 shared drawer (ambiguous -> provision skip; operator 1 TILL bilan hal qiladi) ──
def test_shared_drawer_resolution(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, terminal=_term(db, br))
    _shift(db, cashenv, br, emp, terminal=_term(db, br))
    m, _ = phase0.propose_till_mapping(db, company_id=co.id)
    plan = phase0.provision_accounts(db, m, apply=True)
    assert plan["skipped_ambiguous"] == 1 and plan["to_create"] == 0   # taxmin qilmaydi, o'tkazади
    # Operator "umumiy yashik" deb hal qiladi -> BITTA TILL qo'lда yaratadi
    db.add(CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                       status="ACTIVE", label="SHARED", created_at=cashenv.now)); db.flush()
    assert repo.find_account(db, co.id, br.id, "TILL") is not None


# ── §16.6 open shift mapping ─────────────────────────────────────────────────
def test_open_shift_mapping(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, status=ShiftStatus.open, opening=5000)
    rows, findings = phase0.map_open_shifts(db, company_id=co.id)
    assert len(rows) == 1 and rows[0]["blocked"] is False
    assert rows[0]["proposed_cash_account"] and rows[0]["legacy_shift_id"] == str(sh.id)
    assert not any(f.severity == phase0.BLOCK for f in findings)


# ── §16.7 ambiguous shift mapping (blocked) ──────────────────────────────────
def test_ambiguous_shift_mapping_blocked(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, terminal=_term(db, br), status=ShiftStatus.closed)
    _shift(db, cashenv, br, emp, terminal=_term(db, br), status=ShiftStatus.closed)  # -> AMBIGUOUS branch
    sh_open = _shift(db, cashenv, br, emp, status=ShiftStatus.open, opening=5000)
    rows, findings = phase0.map_open_shifts(db, company_id=co.id)
    row = next(r for r in rows if r["legacy_shift_id"] == str(sh_open.id))
    assert row["blocked"] is True and row["proposed_cash_account"] is None
    assert any(f.code == "OPEN_SHIFT_UNMAPPABLE" and f.severity == phase0.BLOCK for f in findings)


# ── §16.8 currency mismatch ──────────────────────────────────────────────────
def test_currency_mismatch_blocks(db, cashenv):
    co = _co(db, cashenv, cur="")   # bo'sh valyuta
    _br(db, co)
    findings = phase0.currency_audit(db, company_id=co.id)
    assert any(f.code == "CURRENCY_INVALID" and f.severity == phase0.BLOCK for f in findings)
    # §13: mapping valyutani TAXMIN QILMAYDI ("UZS" emas) -> AMBIGUOUS -> provisionlanmaydi
    m, mfind = phase0.propose_till_mapping(db, company_id=co.id)
    assert m[0].confidence == "AMBIGUOUS" and m[0].currency == ""
    assert any(f.code == "TILL_CURRENCY_UNKNOWN" and f.severity == phase0.BLOCK for f in mfind)
    plan = phase0.provision_accounts(db, m, apply=True)
    assert plan["to_create"] == 0 and plan["skipped_ambiguous"] >= 1   # yomon-valyutali TILL yaratilmaydi


# ── §16.9 tenant mismatch (cross-tenant leak yo'q) ───────────────────────────
def test_tenant_isolation_no_leak(db, cashenv):
    coA = _co(db, cashenv); brA = _br(db, coA); empA = _emp(db, coA)
    _sale_cash(db, cashenv, coA, brA, empA, 10000)
    coB = _co(db, cashenv); brB = _br(db, coB); empB = _emp(db, coB)
    _sale_cash(db, cashenv, coB, brB, empB, 99999)
    # provisioning tenant_id ni HAR DOIM filial kompaniyasига tenglaydi (cross-tenant emas)
    mA, _ = phase0.propose_till_mapping(db, company_id=coA.id)
    phase0.provision_accounts(db, mA, apply=True)
    accA = repo.find_account(db, coA.id, brA.id, "TILL")
    assert accA is not None and accA.tenant_id == coA.id
    # coA scoped dry-run coB ma'lumotини KO'RMAYDI
    repA = phase0.dry_run(db, company_id=coA.id)
    assert repA["projection"]["IN"].get("SALE") == 10000.0   # faqat coA (99999 emas)


# ── §16.10 reconstruction candidate detection ───────────────────────────────
def test_reconstruction_candidate_detection(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    pur = _received_purchase(db, cashenv, co, br, 30000)
    cands, findings = phase0.reconstruction_candidates(db, company_id=co.id)
    assert len(cands) == 1
    c = cands[0]
    assert c["classification"] == "RECONSTRUCTION" and c["source"] == f"purchases:{pur.id}"
    assert c["expected_entry"]["category"] == "PURCHASE_OUT" and c["expected_entry"]["amount"] == 30000.0
    assert any(f.code == "RECON_CASH_PURCHASES" for f in findings)


# ── §16.11 backup verification ───────────────────────────────────────────────
def test_backup_verification(db, cashenv):
    assert phase0.verify_backup(None)["ok"] is False
    assert phase0.verify_backup({})["ok"] is False
    partial = {"snapshot_ref": "s", "taken_at": "t", "operator": "op", "checksum": "c",
               "restore_rehearsed": False, "verified": True}
    assert phase0.verify_backup(partial)["ok"] is False        # restore_rehearsed False -> BLOCK
    full = {**partial, "restore_rehearsed": True}
    assert phase0.verify_backup(full)["ok"] is True


# ── §16.12 PostgreSQL compatibility ──────────────────────────────────────────
def test_postgresql_compatibility(db, cashenv):
    r = phase0.readiness_check(cashenv.engine)
    assert r["ok"] is True
    c = r["checks"]
    assert c["pg_version_ok"] and c["cash_schema"] and c["roles_ok"]
    assert c["posting_cannot_mutate_ledger"] is True          # §17 immutable ledger


# ── §16.13 search_path reset ─────────────────────────────────────────────────
def test_search_path_reset(db, cashenv):
    from sqlalchemy import text
    r = phase0.readiness_check(cashenv.engine)
    assert r["checks"]["search_path_not_cash_first"] is True
    # Qualify qilinmagan `shifts` public.shifts'ga resolve bo'lishi kerak (cash.shifts EMAS): legacy
    # public.shifts'да `opening_cash` ustuni bor, cash.shifts'да YO'Q. Agar search_path cash'ni oldinга
    # qo'yган bo'lса, quyidagi so'rov cash.shifts'ga tushib "opening_cash yo'q" bilan yiqilardi.
    with cashenv.engine.connect() as con:
        con.execute(text("SELECT count(opening_cash) FROM shifts")).scalar()   # public.shifts resolve
        sp = con.execute(text("SHOW search_path")).scalar()
    assert not str(sp).strip().startswith("cash")


# ── §16.14 dry-run produces no ledger writes ─────────────────────────────────
def test_dry_run_writes_no_ledger(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, opening=5000)
    _sale_cash(db, cashenv, co, br, emp, 12000)
    before = db.query(CashLedgerEntry).count()
    rep = phase0.dry_run(db, company_id=co.id)
    after = db.query(CashLedgerEntry).count()
    assert rep["wrote_ledger"] is False
    assert before == after                                     # ledger'ga BITTA qator yozilmagan
    assert rep["expected_ledger_rows"] >= 2                     # OPENING + SALE proyeksiyasi


# ── §16.15 dry-run deterministic on repeat ───────────────────────────────────
def test_dry_run_deterministic(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    _shift(db, cashenv, br, emp, opening=7000)
    _sale_cash(db, cashenv, co, br, emp, 8000)
    _received_purchase(db, cashenv, co, br, 5000)
    r1 = phase0.dry_run(db, company_id=co.id)
    r2 = phase0.dry_run(db, company_id=co.id)
    assert r1["projection"] == r2["projection"]
    assert r1["expected_ledger_rows"] == r2["expected_ledger_rows"]
    assert r1["go_no_go"]["decision"] == r2["go_no_go"]["decision"]
    assert r1["expected_in_total"] == r2["expected_in_total"]


# ── §13 regressiya: PURCHASE_OUT faqat NAQD (charge yo'q) xarid; debt->received phantom emas ──
def test_purchase_out_excludes_charged_debt(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co)
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.flush()
    # debt xarid to'liq to'lanib `received`ga o'girilган (SupplierLedger charge BOR)
    pur = Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=br.id, supplier_id=sup.id,
                   purchase_date=cashenv.now.date(), status=PurchaseStatus.received,
                   subtotal=Decimal("30000"), total=Decimal("30000"), paid_amount=Decimal("30000"))
    db.add(pur); db.flush()
    db.add(SupplierLedger(supplier_id=sup.id, type=CreditTxnType.charge, amount=Decimal("30000"),
                          balance_after=Decimal("30000"), ref_type="purchase", ref_id=pur.id,
                          created_at=cashenv.now)); db.flush()
    cands, _ = phase0.reconstruction_candidates(db, company_id=co.id)
    assert len(cands) == 0                                   # charge bor -> reconstruction YO'Q (phantom emas)
    rep = phase0.dry_run(db, company_id=co.id)
    assert "PURCHASE_OUT" not in rep["projection"]["OUT"]    # phantom PURCHASE_OUT yo'q


# ── §13 regressiya: payin/payout soyalari HEADLINE'га qo'shilmaydi (ikki hisob emas) ──
def test_ambiguous_movements_excluded_from_headline(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, opening=5000)
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payout, amount=Decimal("2000"),
                        reason="Qaytarish", created_at=cashenv.now))   # refund soyasi
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.payin, amount=Decimal("3000"),
                        reason="Qarz to'lovi", created_at=cashenv.now))  # debt-payment soyasi
    db.add(CashMovement(shift_id=sh.id, type=CashMovementType.expense, amount=Decimal("500"),
                        reason="x", created_at=cashenv.now))             # NOYOB manual
    db.flush()
    rep = phase0.dry_run(db, company_id=co.id)
    assert "CASH_IN" not in rep["projection"]["IN"]           # payin HEADLINE'да YO'Q
    assert rep["projection"]["OUT"].get("CASH_OUT") is None   # payout HEADLINE'да YO'Q (collection yo'q)
    assert rep["projection"]["OUT"].get("EXPENSE") == 500.0   # expense NOYOB -> bor
    amv = rep["ambiguous_movements"]
    assert amv["payin"]["sum"] == 3000.0 and amv["payout"]["sum"] == 2000.0
    assert any(f["code"] == "AMBIGUOUS_CASH_MOVEMENTS" for f in rep["review"])


# ── §13 regressiya: soft-deleted filial ochiq smenasi BLOKLANADI (phantom TILL emas) ──
def test_open_shift_soft_deleted_branch_blocked(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    sh = _shift(db, cashenv, br, emp, status=ShiftStatus.open, opening=5000)
    br.deleted_at = cashenv.now; db.add(br); db.flush()       # filial soft-delete (smena hali ochiq)
    rows, findings = phase0.map_open_shifts(db)               # UNSCOPED (soft-deleted filial scope'дан tushmasin)
    row = next((r for r in rows if r["legacy_shift_id"] == str(sh.id)), None)
    assert row is not None and row["blocked"] is True and row["proposed_cash_account"] is None
    assert any(f.code == "OPEN_SHIFT_UNMAPPABLE" and f.ref == f"shifts:{sh.id}" for f in findings)


# ── §13 regressiya: bir xil terminalли soft-deleted smena AMBIGUOUS qilmaydi ──
def test_soft_deleted_shift_not_ambiguous(db, cashenv):
    co = _co(db, cashenv); br = _br(db, co); emp = _emp(db, co)
    t1 = _term(db, br)
    _shift(db, cashenv, br, emp, terminal=t1)                 # tirik: 1 terminal
    dead = _shift(db, cashenv, br, emp, terminal=_term(db, br))   # o'chirilган: boshqa terminal
    dead.deleted_at = cashenv.now; db.add(dead); db.flush()
    m, _ = phase0.propose_till_mapping(db, company_id=co.id)
    assert m[0].confidence == "HIGH"                          # o'chirilган smena sanalmaydi -> AMBIGUOUS emas
