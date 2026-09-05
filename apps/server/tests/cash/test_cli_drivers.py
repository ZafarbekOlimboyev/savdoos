# -*- coding: utf-8 -*-
"""Cash Migration OPERATOR CLI driver'lari testlari (real PostgreSQL, pgserver).

`app/tools/cash_*` yupqa CLI qobiqlarини tekshiradi — default read-only/dry-run, --apply xatti-harakati,
approved-hash gate, verify pass/fail exit kodlari, va XAVFSIZLIK invariantlari (sir chiqmaydi,
LEDGER_PRIMARY hech qачон o'rnatilmaydi, destruktiv SQL yo'q). Har test FRESH tenant ishlatadi
(shared-DB kontaminatsiyasidан toza natija) va har CLI --company-id bilan skoplanadi.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import app.tools as tools_pkg
from app.db.cash.migration import backfill
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount, CashLedgerEntry
from app.models.enums import SaleStatus
from app.models.org import Branch, Company
from app.models.sales import Sale, SalePayment
from app.services.cash import mode
from app.tools import cash_backfill, cash_compare, cash_preflight, cash_provision, cash_verify


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


# ── seed helpers ─────────────────────────────────────────────────────────────
def _hex():
    return uuid.uuid4().hex[:8]


def _tenant(db, cashenv, *, with_till: bool):
    co = Company(name="CLI" + _hex(), code="cli" + _hex(), currency="UZS"); db.add(co); db.flush()
    role = db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="K", role_id=role.id); db.add(emp); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="Br"); db.add(br); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = None
    if with_till:
        till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                           status="ACTIVE", created_at=cashenv.now); db.add(till)
    db.commit()
    return co, br, emp, till


def _hist_cash_sale(db, co, br, emp, cashenv, amount="10000"):
    """Historical (< T0) naqd sotuv -> backfill uchun bitta IN·SALE (RECONSTRUCTION) leg."""
    hist = cashenv.now - timedelta(days=5)   # T0 = now - 1 kun; bu undan oldin
    s = Sale(receipt_no="R" + _hex(), company_id=co.id, branch_id=br.id, cashier_id=emp.id,
             shift_id=None, status=SaleStatus.completed, currency="UZS",
             subtotal=Decimal(amount), total=Decimal(amount), sold_at=hist)
    db.add(s); db.flush()
    db.add(SalePayment(sale_id=s.id, method_code="cash", amount=Decimal(amount), paid_at=hist))
    db.commit()
    return s


def _T0(cashenv):
    return (cashenv.now - timedelta(days=1)).isoformat()


def _sf(cashenv):
    """(session_factory, engine) — CLI'ga inyeksiya (app'ning global engine'iga tegmasдан)."""
    return (lambda: Session(cashenv.engine)), cashenv.engine


def _recon_count(db, co):
    return (db.query(CashLedgerEntry)
            .filter(CashLedgerEntry.tenant_id == co.id,
                    CashLedgerEntry.provenance == "RECONSTRUCTION").count())


def _till_count(db, co):
    return db.query(CashAccount).filter(CashAccount.tenant_id == co.id,
                                        CashAccount.type == "TILL").count()


# ═══ PREFLIGHT ═══════════════════════════════════════════════════════════════
def test_preflight_ready_and_readonly(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    before = _recon_count(db, co)
    sf, eng = _sf(cashenv)

    rc = cash_preflight.main(["--company-id", str(co.id)], session_factory=sf, engine=eng)

    out = capsys.readouterr().out
    assert rc == 0, out
    assert "VERDICT: READY" in out
    assert "MODE:        READ-ONLY" in out
    # read-only: hech narsa yozilmadi
    assert _recon_count(db, co) == before == 0


def test_preflight_json(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    sf, eng = _sf(cashenv)
    rc = cash_preflight.main(["--company-id", str(co.id), "--json"], session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 0
    assert '"kind": "CASH_PREFLIGHT"' in out


# ═══ PROVISION ═══════════════════════════════════════════════════════════════
def test_provision_dry_run_writes_nothing(db, cashenv, capsys):
    co, br, emp, _ = _tenant(db, cashenv, with_till=False)
    sf, eng = _sf(cashenv)
    rc = cash_provision.main(["--company-id", str(co.id)], session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DRY-RUN" in out
    assert _till_count(db, co) == 0   # dry-run -> yozuv yo'q


def test_provision_apply_then_idempotent(db, cashenv, capsys):
    co, br, emp, _ = _tenant(db, cashenv, with_till=False)
    sf, eng = _sf(cashenv)

    rc1 = cash_provision.main(["--company-id", str(co.id), "--apply"], session_factory=sf, engine=eng)
    out1 = capsys.readouterr().out
    assert rc1 == 0, out1
    assert "THIS WILL WRITE" in out1
    assert _till_count(db, co) == 1

    # idempotent rerun: yangi yozuv yo'q, existing=1
    rc2 = cash_provision.main(["--company-id", str(co.id), "--apply"], session_factory=sf, engine=eng)
    out2 = capsys.readouterr().out
    assert rc2 == 0, out2
    assert _till_count(db, co) == 1
    assert "existing=1" in out2 or "already_existing=1" in out2


# ═══ BACKFILL ════════════════════════════════════════════════════════════════
def test_backfill_dry_run_writes_nothing(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    sf, eng = _sf(cashenv)
    rc = cash_backfill.main(["--company-id", str(co.id), "--t0", _T0(cashenv)],
                            session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 0, out               # toza dry-run -> GO
    assert "DRY-RUN" in out and "MANIFEST HASH" in out
    assert _recon_count(db, co) == 0  # dry-run yozmaydi


def test_backfill_apply_without_hash_rejected(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    sf, eng = _sf(cashenv)
    rc = cash_backfill.main(["--company-id", str(co.id), "--t0", _T0(cashenv), "--apply"],
                            session_factory=sf, engine=eng)
    err = capsys.readouterr().err
    assert rc == 1                    # usage xato
    assert "approved-hash" in err
    assert _recon_count(db, co) == 0  # yozilmadi


def test_backfill_missing_t0_rejected(db, cashenv):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    sf, eng = _sf(cashenv)
    with pytest.raises(SystemExit):   # argparse required=True
        cash_backfill.main(["--company-id", str(co.id)], session_factory=sf, engine=eng)
    assert _recon_count(db, co) == 0


def test_backfill_wrong_hash_rejected_writes_nothing(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    sf, eng = _sf(cashenv)
    rc = cash_backfill.main(["--company-id", str(co.id), "--t0", _T0(cashenv),
                             "--apply", "--approved-hash", "deadbeef-not-a-real-hash"],
                            session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "REJECTED" in out and "MISMATCH" in out
    assert _recon_count(db, co) == 0  # RAD -> hech narsa yozilmadi


def test_backfill_correct_hash_applies_then_idempotent(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    t0 = _T0(cashenv)
    # to'g'ri approved-hash'ni read-only dry-run'дан olamiz
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    sf, eng = _sf(cashenv)

    rc1 = cash_backfill.main(["--company-id", str(co.id), "--t0", t0,
                              "--apply", "--approved-hash", approved], session_factory=sf, engine=eng)
    out1 = capsys.readouterr().out
    assert rc1 == 0, out1
    assert "THIS WILL WRITE TO THE CASH MIGRATION TABLES" in out1
    assert _recon_count(db, co) == 1

    # idempotent rerun (bir xil deterministik hash): inserted=0
    rc2 = cash_backfill.main(["--company-id", str(co.id), "--t0", t0,
                              "--apply", "--approved-hash", approved], session_factory=sf, engine=eng)
    out2 = capsys.readouterr().out
    assert rc2 == 0, out2
    assert _recon_count(db, co) == 1
    assert "inserted_rows:         0" in out2


# ═══ VERIFY ══════════════════════════════════════════════════════════════════
def test_verify_fails_before_backfill(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)   # candidate bor, lekin backfill BAJARILMAGAN
    sf, eng = _sf(cashenv)
    rc = cash_verify.main(["--company-id", str(co.id), "--t0", _T0(cashenv)],
                          session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 3, out               # row_count mos emas -> FAIL
    assert "VERDICT: FAIL" in out
    assert _recon_count(db, co) == 0  # read-only


def test_verify_passes_after_backfill(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    sf, eng = _sf(cashenv)
    cash_backfill.main(["--company-id", str(co.id), "--t0", t0, "--apply", "--approved-hash", approved],
                       session_factory=sf, engine=eng)
    capsys.readouterr()
    before = _recon_count(db, co)

    rc = cash_verify.main(["--company-id", str(co.id), "--t0", t0], session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "VERDICT: PASS" in out
    assert _recon_count(db, co) == before == 1   # read-only (yozmadi)


# ═══ COMPARE ═════════════════════════════════════════════════════════════════
def test_compare_match_and_readonly(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    t0 = _T0(cashenv)
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    sf, eng = _sf(cashenv)
    cash_backfill.main(["--company-id", str(co.id), "--t0", t0, "--apply", "--approved-hash", approved],
                       session_factory=sf, engine=eng)
    capsys.readouterr()
    before = _recon_count(db, co)

    rc = cash_compare.main(["--company-id", str(co.id), "--t0", t0, "--report"],
                           session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 0, out                            # >= T0 hodisa yo'q -> MATCH
    assert "VERDICT: MATCH" in out
    assert "CUTOVER READINESS" in out
    assert _recon_count(db, co) == before          # read-only


def test_compare_detects_extra_ledger(db, cashenv, capsys):
    from datetime import timezone
    from sqlalchemy.dialects.postgresql import insert as _pg
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    # >= T0 NORMAL leg, legacy manbasiz -> EXTRA_LEDGER mismatch (REVIEW)
    now = cashenv.now
    db.execute(_pg(CashLedgerEntry.__table__).values(
        id=uuid.uuid4(), tenant_id=co.id, cash_account_id=till.id, branch_id=br.id, account_type="TILL",
        shift_id=None, posting_kind="OFF_SHIFT", source_type="CASH_OP", source_id=uuid.uuid4(), leg_index=0,
        direction="IN", category="CASH_IN", amount=Decimal("500"), currency="UZS",
        device_occurred_at=now, server_received_at=now, recorded_at=now,
        idempotency_key="cli-extra-" + _hex(), provenance="NORMAL").on_conflict_do_nothing())
    db.commit()
    sf, eng = _sf(cashenv)
    rc = cash_compare.main(["--company-id", str(co.id), "--t0", _T0(cashenv)],
                           session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    assert rc == 2, out                            # REVIEW (unexplained mismatch)
    assert "VERDICT: REVIEW" in out


# ═══ XAVFSIZLIK INVARIANTLARI ═══════════════════════════════════════════════
def test_no_secrets_in_output(db, cashenv, capsys):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    sf, eng = _sf(cashenv)
    cash_preflight.main(["--company-id", str(co.id)], session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    # to'liq DB URL / socket-host / DATABASE_URL qiymati HECH QACHON chiqmaydi
    assert str(cashenv.engine.url) not in out
    assert "sqlite:///./_pytest.db" not in out     # DATABASE_URL QIYMATI (faqat true/false bo'lishi kerak)
    assert "DATABASE_URL present:" in out
    # TARGET faqat logik baza nomini ko'rsatadi (host/parol emas)
    assert "host/user/parol/URL HECH QACHON chop etilmaydi" in out


def test_ledger_primary_never_set_and_mode_unchanged(db, cashenv):
    co, br, emp, till = _tenant(db, cashenv, with_till=True)
    _hist_cash_sale(db, co, br, emp, cashenv)
    t0 = _T0(cashenv)
    before_mode = mode.cash_mode()
    approved = backfill.execute_backfill(db, company_id=co.id, t0=t0, apply=False)["manifest_hash"]
    sf, eng = _sf(cashenv)
    cash_preflight.main(["--company-id", str(co.id)], session_factory=sf, engine=eng)
    cash_backfill.main(["--company-id", str(co.id), "--t0", t0, "--apply", "--approved-hash", approved],
                       session_factory=sf, engine=eng)
    cash_compare.main(["--company-id", str(co.id), "--t0", t0], session_factory=sf, engine=eng)
    # CLI'lар mode'ni O'ZGARTIRMAYDI va LEDGER_PRIMARY'ni YOQMAYDI
    assert mode.cash_mode() == before_mode
    assert not mode.ledger_is_authority()


def _code_without_docstrings(src: str) -> str:
    """AST orqali DOCSTRING'lar (proza) + izohlarни olib tashlab, faqat BAJARILADIGAN kodни qaytaradi.
    Shunda scan tool prozasidagi 'DELETE/TRUNCATE/DROP YO'Q' izohига yolg'on tushmaydi — faqat haqiqiy
    kod (masalan text('DELETE FROM ...') string-literali) qolса ushlaydi."""
    import ast
    tree = ast.parse(src)
    targets = [n for n in ast.walk(tree)
               if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in targets:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_source_has_no_destructive_sql_or_mode_mutation():
    tools_dir = Path(tools_pkg.__file__).parent
    forbidden = ("set_mode(", "reset_mode(", "SAVDOOS_CASH_ALLOW_PRIMARY",
                 "TRUNCATE", "DROP TABLE", "DROP SCHEMA", "DELETE FROM", "os.environ[")
    for f in sorted(tools_dir.glob("*.py")):
        code = _code_without_docstrings(f.read_text(encoding="utf-8"))
        for bad in forbidden:
            assert bad not in code, f"{f.name} destruktiv/mode-mutatsiya token'ini kodda o'z ichiga oladi: {bad!r}"
    # ijobiy: primary-guard mavjud
    assert "ledger_is_authority" in (tools_dir / "_common.py").read_text(encoding="utf-8")
