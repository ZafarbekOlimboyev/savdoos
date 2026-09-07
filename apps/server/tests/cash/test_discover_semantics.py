# -*- coding: utf-8 -*-
"""DISCOVERY SEMANTIKASI — UNKNOWN hech qachon "RESOLVED" emas (real PostgreSQL).

Ishlab chiqarish dalili (Fayzan F01): historical_shift_count=0, terminal_records=[],
existing_active_tills=[], physical_checkout_count=UNKNOWN, detection_source=NO_ACTIVITY —
va shunga QARAMAY operator_input_required=false + VERDICT=RESOLVED chiqardi. Ziddiyat.

A  NO_ACTIVITY + terminal yo'q + TILL yo'q -> UNKNOWN, input kerak, RESOLVED EMAS
B  UNKNOWN hech qachon AVTOMATIK 0 ga aylanmaydi
C  mapping skeleton SAFE'ni AVTOMATIK yoqmaydi
D  deterministik dalil bo'lsa RESOLVED bo'la oladi (EXISTING/TERMINAL/OPERATOR)
E  tarixiy dalil yo'qligi BUGUNGI kassa sonini ISBOTLAMAYDI (matn + xulq)
F  AMBIGUOUS (tarix bor, terminal NULL) ham input talab qiladi — regressiya qo'riqchisi
G  mapping fingerprint kassa KODLARINI qamraydi (approved-hash butunligi)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.shifts import Shift
from app.services.cash import till_identity as _ti
from app.tools import cash_discover as CLI


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _sf(cashenv):
    return (lambda: Session(cashenv.engine)), cashenv.engine


def _co(db):
    c = Company(name="DS" + _hex(), code="ds" + _hex(), currency="UZS")
    db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _term(db, br):
    t = Terminal(branch_id=br.id, name="T" + _hex()); db.add(t); db.flush(); return t


def _shift(db, br, emp, terminal=None):
    s = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(days=3),
              closed_at=_now() - timedelta(days=3) + timedelta(hours=8),
              opening_cash=Decimal("0"), status=ShiftStatus.closed,
              terminal_id=(terminal.id if terminal else None))
    db.add(s); db.flush(); return s


def _till(db, co, br, code="TILL-01"):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS", status="ACTIVE",
                    label=_ti.till_label(code, None), created_at=_now())
    db.add(a); db.flush(); return a


def _run(cashenv, co, br, capsys, extra=()):
    sf, eng = _sf(cashenv)
    rc = CLI.main(["--company-id", str(co.id), "--branch-id", str(br.id), "--json", *extra],
                  session_factory=sf, engine=eng)
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):out.rindex("}") + 1])
    return rc, payload, payload["evidence"][0]


# ═══ A) NO_ACTIVITY -> UNKNOWN + input kerak + RESOLVED EMAS ═══════════════
def test_A_no_activity_is_not_resolved(db, cashenv, capsys):
    """Aynan Fayzan F01 holati: tarix yo'q, terminal yo'q, TILL yo'q."""
    co = _co(db); br = _br(db, co); db.commit()
    rc, rep, ev = _run(cashenv, co, br, capsys)

    assert ev["detection_source"] == _ti.SRC_NO_ACTIVITY
    assert ev["physical_checkout_count"] == "UNKNOWN"
    assert ev["operator_input_required"] is True, "UNKNOWN bo'lsa-da input talab qilinmadi"
    assert ev["count_state"] == "UNRESOLVED_CURRENT_CHECKOUT_COUNT"
    assert ev["confidence"] == "UNKNOWN"                  # "N/A" EMAS
    assert rep["verdict"] == "OPERATOR_INPUT_REQUIRED"
    assert rep["verdict"] != "RESOLVED"
    assert rep["operator_input_required"] is True
    assert br.code in rep["branches_needing_input"]
    assert rc == 2, "RESOLVED emas, lekin exit 0 qaytdi"


# ═══ B) UNKNOWN hech qachon AVTOMATIK 0 emas ═══════════════════════════════
def test_B_unknown_never_becomes_zero(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    _rc, rep, ev = _run(cashenv, co, br, capsys)
    assert ev["physical_checkout_count"] == "UNKNOWN"
    assert ev["physical_checkout_count"] != 0 and ev["physical_checkout_count"] is not None
    # skeleton ham 0 ta kassa DEB E'LON QILMAYDI — u BO'SH ro'yxat (operator to'ldiradi)
    sk = rep["mapping_skeleton"]["branches"][str(br.id)]
    assert sk["tills"] == []                             # "0 ta kassa bor" EMAS, "javob yo'q"
    assert ev["count_state"] == "UNRESOLVED_CURRENT_CHECKOUT_COUNT"


# ═══ C) skeleton SAFE'ni AVTOMATIK yoqmaydi ════════════════════════════════
def test_C_skeleton_does_not_auto_enable_safe(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    _rc, rep, _ev = _run(cashenv, co, br, capsys)
    sk = rep["mapping_skeleton"]["branches"][str(br.id)]
    assert sk["safe"] is not True                        # ASOSIY: `safe: true` EMAS
    assert sk["safe"] is None and sk["safe_decision"] == "OPERATOR_DECISION"
    assert rep["safe_policy"]["auto_enabled"] is False

    # Va skeleton parser bilan MOS: `safe: null` -> SAFE YARATILMAYDI, `safe_decision` xato bermaydi
    m = _ti.parse_operator_mapping({"branches": {str(br.id): dict(sk, tills=[{"code": "TILL-01"}])}})
    bm = m.for_branch(br.id)
    assert bm.safe is False and bm.safe_explicit is True

    # MOSLIK: `safe` kaliti YO'Q eski mapping xulqi O'ZGARMAGAN (fingerprint siljimasin)
    old = _ti.parse_operator_mapping({"branches": {str(br.id): {"tills": [{"code": "TILL-01"}]}}})
    assert old.for_branch(br.id).safe is True and old.for_branch(br.id).safe_explicit is False


# ═══ D) deterministik dalil -> RESOLVED bo'la oladi ════════════════════════
def test_D_deterministic_evidence_can_resolve(db, cashenv, capsys):
    """RESOLVED hamon MUMKIN — lekin FAQAT deterministik dalil bilan."""
    # (i) EXISTING: allaqachon provisionlangan ACTIVE TILL
    co = _co(db); br = _br(db, co); _till(db, co, br); db.commit()
    rc, rep, ev = _run(cashenv, co, br, capsys)
    assert ev["detection_source"] == _ti.SRC_EXISTING
    assert ev["physical_checkout_count"] == 1 and ev["confidence"] == "HIGH"
    assert ev["operator_input_required"] is False
    assert rep["verdict"] == "RESOLVED" and rc == 0

    # (ii) TERMINAL: smena tarixida terminal dalili bor
    co2 = _co(db); br2 = _br(db, co2); e2 = _emp(db, co2, br2)
    t = _term(db, br2); _shift(db, br2, e2, terminal=t); db.commit()
    rc2, rep2, ev2 = _run(cashenv, co2, br2, capsys)
    assert ev2["detection_source"] == _ti.SRC_TERMINAL
    assert ev2["physical_checkout_count"] == 1
    assert ev2["operator_input_required"] is False and rep2["verdict"] == "RESOLVED" and rc2 == 0


# ═══ E) tarix yo'qligi BUGUNGI sonni ISBOTLAMAYDI ══════════════════════════
def test_E_absent_history_does_not_prove_current_count(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    _rc, _rep, ev = _run(cashenv, co, br, capsys)
    assert ev["historical_shift_count"] == 0 and ev["terminal_records"] == []
    assert ev["existing_active_tills"] == []
    # tarix bo'sh — LEKIN xulosa "0 ta kassa" EMAS, "aniqlab bo'lmadi"
    assert ev["physical_checkout_count"] == "UNKNOWN"
    note = ev["count_note"]
    assert "EMAS" in note and "operator" in note.lower()
    assert "KELTIRIB" in note                            # "0 ni tarixdan keltirib chiqarmang"

    sf, eng = _sf(cashenv)
    CLI.main(["--company-id", str(co.id), "--branch-id", str(br.id)], session_factory=sf, engine=eng)
    human = capsys.readouterr().out
    assert "BUGUN NECHTA fizik" in human                 # operatorga ANIQ savol beriladi
    assert "OPERATOR_INPUT_REQUIRED" in human


# ═══ F) AMBIGUOUS ham input talab qiladi (regressiya qo'riqchisi) ══════════
def test_F_ambiguous_still_requires_input(db, cashenv, capsys):
    """Tarix BOR, lekin terminal_id NULL -> fizik drawer aniqlanmaydi."""
    co = _co(db); br = _br(db, co); e = _emp(db, co, br)
    _shift(db, br, e, terminal=None); db.commit()
    rc, rep, ev = _run(cashenv, co, br, capsys)
    assert ev["detection_source"] == _ti.SRC_AMBIGUOUS
    assert ev["physical_checkout_count"] == "UNKNOWN"
    assert ev["operator_input_required"] is True
    assert rep["verdict"] == "OPERATOR_INPUT_REQUIRED" and rc == 2


# ═══ G) fingerprint kassa KODLARINI qamraydi ══════════════════════════════
def test_G_fingerprint_covers_till_codes(db, cashenv):
    """RC13 topilma: mapping_fingerprint `getattr(t, "code", "")` o'qirdi, lekin OperatorTill
    maydoni `checkout_code`. Natijada kod HAR DOIM '' bo'lib fingerprint'ga KIRMASDI — kodi
    boshqa, terminali bir xil ikki mapping BIR XIL hash berardi va tasdiqlangan (approved)
    reja jimgina almashtirilishi mumkin edi."""
    from app.db.cash.migration import backfill as bf
    b = str(uuid.uuid4())

    def fp(code):
        m = _ti.parse_operator_mapping({"branches": {b: {"safe": False,
                                                         "tills": [{"code": code}]}}})
        return bf.mapping_fingerprint(m)

    assert "TILL-01" in fp("TILL-01"), "kassa kodi fingerprint'ga kirmadi"
    assert fp("TILL-01") != fp("TILL-99"), "turli kodlar BIR XIL hash berdi"

    # terminal bir xil, kod boshqa -> hash ham BOSHQA bo'lishi SHART
    t = str(uuid.uuid4())
    m1 = _ti.parse_operator_mapping({"branches": {b: {"safe": False, "tills": [
        {"code": "TILL-01", "terminal_id": t}]}}})
    m2 = _ti.parse_operator_mapping({"branches": {b: {"safe": False, "tills": [
        {"code": "TILL-02", "terminal_id": t}]}}})
    assert bf.mapping_fingerprint(m1) != bf.mapping_fingerprint(m2)
