# -*- coding: utf-8 -*-
"""CURRENT TILL PROVISION PLAN CLI testlari (real PostgreSQL).

A  bo'sh filial + bitta kod        -> CREATE, exit 0, SAFE rejalashtirilmaydi
B  ACTIVE bir xil kod              -> EXISTS_NOOP (idempotent), exit 2
C  ARCHIVED bir xil kod            -> CONFLICT (dublikat identity xavfi), exit 3
D  valyuta nomuvofiqligi           -> CONFLICT
E  BOSHQA filialdagi bir xil kod   -> QONUNIY (nizo EMAS), lekin OCHIQ ko'rsatiladi
F  terminal boshqa filialniki      -> CONFLICT; band terminal -> CONFLICT
G  faqat SO'RALGAN filial ko'riladi (qo'shni filial rejaga TA'SIR QILMAYDI)
H  ko'p kassa + terminalsiz        -> OGOHLANTIRISH
I  usage: kod yo'q / noto'g'ri UUID / noma'lum kompaniya
J  STRICTLY READ-ONLY: yozuv yo'q + manba skani (apply yo'q, gardlar bor)
K  TARIXIY ajratish matni hisobotda BOR (bugungi kassa tarixni hal qilmaydi)
L  --json stdout AYNAN JSON (operator `| jq` qila olsin)
"""
from __future__ import annotations

import ast
import json
import pathlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.cash import CashAccount
from app.models.org import Branch, Company, Terminal
from app.services.cash import till_identity as _ti
from app.tools import cash_till_plan as CLI

CLI_PATH = pathlib.Path(__file__).resolve().parents[2] / "app" / "tools" / "cash_till_plan.py"


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _sf(cashenv):
    return (lambda: Session(cashenv.engine)), cashenv.engine


def _co(db, currency="UZS"):
    c = Company(name="TP" + _hex(), code="tp" + _hex(), currency=currency)
    db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _till(db, co, br, code, *, status="ACTIVE", currency="UZS", terminal_id=None):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency=currency,
                    status=status, label=_ti.till_label(code, terminal_id), created_at=_now())
    db.add(a); db.flush(); return a


def _term(db, br, name="Kassa-1"):
    t = Terminal(branch_id=br.id, name=name + _hex())
    db.add(t); db.flush(); return t


def _json(out: str) -> dict:
    return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]


def _run(cashenv, argv, capsys):
    sf, eng = _sf(cashenv)
    rc = CLI.main(argv, session_factory=sf, engine=eng)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _args(co, br, *codes, extra=()):
    a = ["--company-id", str(co.id), "--branch-id", str(br.id)]
    for c in codes:
        a += ["--code", c]
    return a + list(extra)


# ═══ A) bo'sh filial -> CREATE, SAFE yo'q ══════════════════════════════════
def test_A_empty_branch_plans_create(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 0, out
    assert rep["kind"] == "CASH_TILL_PROVISION_PLAN"
    assert rep["apply_mode"] == "NONE" and rep["read_only"] is True
    assert rep["verdict"] == "READY_TO_APPLY" and rep["to_create"] == 1
    p = rep["plan"][0]
    assert p["action"] == "CREATE" and p["code"] == "TILL-01"
    assert "TILL code=TILL-01 terminal=NONE" in p["detail"]
    # SAFE HECH QACHON rejalashtirilmaydi
    assert rep["safe_policy"]["planned"] == 0 and rep["safe_policy"]["auto_create"] is False
    assert rep["existing_active_safes"] == 0
    assert rep["scope"]["companies"] == 1 and rep["scope"]["branches"] == 1
    assert rep["currency_resolution"]["effective"] == "UZS"


# ═══ B) ACTIVE bir xil kod -> idempotent NO-OP ═════════════════════════════
def test_B_existing_active_is_noop(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); a = _till(db, co, br, "TILL-01"); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 2
    assert rep["verdict"] == "NOTHING_TO_DO"
    p = rep["plan"][0]
    assert p["action"] == "EXISTS_NOOP" and p["existing_id"] == str(a.id)
    assert "IDEMPOTENT" in p["detail"]


# ═══ C) ARCHIVED bir xil kod -> CONFLICT (dublikat identity) ═══════════════
def test_C_archived_same_code_is_conflict(db, cashenv, capsys):
    """POST /tills idempotentligi FAQAT ACTIVE bo'yicha (list_tills status='ACTIVE'), va
    (tenant, filial, kod) uchun BAZA unique constraint YO'Q -> jimgina ikkilanish xavfi."""
    co = _co(db); br = _br(db, co)
    arch = _till(db, co, br, "TILL-01", status="ARCHIVED"); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 3
    assert rep["verdict"] == "CONFLICT"
    p = rep["plan"][0]
    assert p["action"] == "CONFLICT" and p["reason"] == "ARCHIVED_SAME_CODE"
    assert str(arch.id) in p["archived_ids"]
    assert "QAYTA FAOLLASHTIRING" in p["detail"]


# ═══ D) valyuta nomuvofiqligi -> CONFLICT ══════════════════════════════════
def test_D_currency_mismatch_is_conflict(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); _till(db, co, br, "TILL-01", currency="USD"); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--currency", "UZS", "--json"]), capsys)
    rep = _json(out)
    assert rc == 3 and rep["plan"][0]["reason"] == "CURRENCY_MISMATCH"


# ═══ E) boshqa filialdagi bir xil kod QONUNIY, lekin ko'rsatiladi ══════════
def test_E_same_code_other_branch_is_legal_but_reported(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); other = _br(db, co)
    _till(db, co, other, "TILL-01"); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 0, out                                   # nizo EMAS — kod filial doirasida
    p = rep["plan"][0]
    assert p["action"] == "CREATE"
    assert len(p["same_code_other_branches"]) == 1
    assert any("QONUNIY" in n for n in p["notes"])


# ═══ F) terminal validatsiyasi ═════════════════════════════════════════════
def test_F_terminal_validation(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); other = _br(db, co)
    foreign = _term(db, other)                            # boshqa filial terminali
    db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, f"TILL-01={foreign.id}", extra=["--json"]), capsys)
    assert rc == 3 and _json(out)["plan"][0]["reason"] == "TERMINAL_WRONG_BRANCH"

    rc2, out2, _ = _run(cashenv, _args(co, br, f"TILL-01={uuid.uuid4()}", extra=["--json"]), capsys)
    assert rc2 == 3 and _json(out2)["plan"][0]["reason"] == "TERMINAL_NOT_FOUND"

    t = _term(db, br); _till(db, co, br, "TILL-09", terminal_id=t.id); db.commit()
    rc3, out3, _ = _run(cashenv, _args(co, br, f"TILL-01={t.id}", extra=["--json"]), capsys)
    assert rc3 == 3 and _json(out3)["plan"][0]["reason"] == "TERMINAL_ALREADY_BOUND"

    t2 = _term(db, br); db.commit()
    rc4, out4, _ = _run(cashenv, _args(co, br, f"TILL-02={t2.id}", extra=["--json"]), capsys)
    assert rc4 == 0 and _json(out4)["plan"][0]["action"] == "CREATE"


# ═══ G) faqat so'ralgan filial ko'riladi ═══════════════════════════════════
def test_G_only_requested_branch_is_considered(db, cashenv, capsys):
    """Qo'shni filialdagi hisoblar rejaga KIRMAYDI — scope AYNAN bitta filial."""
    co = _co(db); br = _br(db, co); neighbour = _br(db, co)
    _till(db, co, neighbour, "TILL-77")
    a = CashAccount(tenant_id=co.id, branch_id=neighbour.id, type="SAFE", currency="UZS",
                    status="ACTIVE", label=_ti.safe_label(), created_at=_now())
    db.add(a); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 0
    assert rep["existing_accounts"] == []                  # qo'shni filial hisoblari YO'Q
    assert rep["scope"]["branch_id"] == str(br.id)
    assert rep["existing_active_safes"] == 0               # qo'shni SAFE sanalmadi


# ═══ H) ko'p kassa + terminalsiz -> ogohlantirish ══════════════════════════
def test_H_multi_unbound_till_warning(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", "TILL-02", extra=["--json"]), capsys)
    rep = _json(out)
    assert rc == 0 and rep["to_create"] == 2
    mw = rep["multi_till_warning"]
    assert mw["active_tills_after"] == 2 and mw["unbound"] == 2
    assert "NOANIQ" in mw["note"]
    _, human, _ = _run(cashenv, _args(co, br, "TILL-01", "TILL-02"), capsys)
    assert "OGOHLANTIRISH:" in human


# ═══ I) usage xatolari ═════════════════════════════════════════════════════
def test_I_usage_errors(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    rc, _out, err = _run(cashenv, ["--company-id", str(co.id), "--branch-id", str(br.id)], capsys)
    assert rc == 1 and "kamida bitta --code" in err
    assert "TARIXDAN taxmin QILINMAYDI" in err            # §1 qoidasi operatorga eslatiladi

    rc2, _o2, err2 = _run(cashenv, ["--company-id", "nope", "--branch-id", str(br.id),
                                    "--code", "TILL-01"], capsys)
    assert rc2 == 1 and "UUID" in err2

    rc3, _o3, err3 = _run(cashenv, ["--company-id", str(uuid.uuid4()), "--branch-id", str(br.id),
                                    "--code", "TILL-01"], capsys)
    assert rc3 == 1 and "COMPANY_NOT_FOUND" in err3

    other_co = _co(db); db.commit()                        # filial boshqa kompaniyaniki
    rc4, _o4, err4 = _run(cashenv, ["--company-id", str(other_co.id), "--branch-id", str(br.id),
                                    "--code", "TILL-01"], capsys)
    assert rc4 == 1 and "BRANCH_WRONG_COMPANY" in err4


# ═══ J) STRICTLY READ-ONLY ═════════════════════════════════════════════════
def test_J_strictly_read_only(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    n = db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count()
    _run(cashenv, _args(co, br, "TILL-01", "TILL-02", extra=["--json"]), capsys)
    db.expire_all()
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count() == n == 0

    src = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for a in node.args:
                assert not (isinstance(a, ast.Constant) and str(a.value).startswith("--apply")), \
                    "CLI'da --apply bayrog'i mavjud"
    # Mutatsiya chaqiruvlari — RESEPTOR bo'yicha (db/session). `set.add()` kabi sof-python
    # chaqiruvlar DB mutatsiyasi EMAS, shu bois nom bo'yicha ko'r-ko'rona taqiqlanmaydi.
    banned = {"commit", "add", "add_all", "flush", "merge", "bulk_save_objects", "execute", "delete"}
    def _recv(node):
        v = node.func.value
        while isinstance(v, (ast.Attribute, ast.Subscript)):
            v = v.value
        return v.id if isinstance(v, ast.Name) else (v.func.id if isinstance(v, ast.Call)
                                                     and isinstance(v.func, ast.Name) else "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in banned:
                assert _recv(node) not in ("db", "session", "sess"),                     f"DB mutatsiya chaqiruvi: {_recv(node)}.{node.func.attr}() (satr {node.lineno})"
    for need in ("guard_never_primary", "require_postgres_cash", "db.rollback()", "db.close()",
                 "finally:"):
        assert need in src, f"{need} yo'q"
    for forbidden in ("CashAccount(", "set_cutover", "cutover_at\"] =", "cash_mode ="):
        assert forbidden not in src, f"taqiqlangan amal: {forbidden}"
    # DDL/DML — FAQAT satr-literallar ichida SQL SHAKLIDA qidiriladi. Xom matn skani yaramaydi:
    # `A_CREATE = "CREATE"` kabi identifikator "CREATE " ga soxta mos keladi.
    import re
    sql = re.compile(r"(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+(TABLE|INDEX|"
                     r"SCHEMA)|DROP\s+\w+|ALTER\s+\w+|TRUNCATE\s+\w+)", re.I)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = sql.search(node.value)
            assert m is None, f"DDL/DML satr-literali (satr {node.lineno}): {m.group(0)!r}"


# ═══ K) tarixiy ajratish OCHIQ aytiladi ════════════════════════════════════
def test_K_historical_separation_is_stated(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    rc, out, _ = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    rep = _json(out)
    assert "HAL QILMAYDI" in rep["historical_separation"]
    assert "backfill qilinmaydi" in rep["historical_separation"]
    assert "T0 o'rnatilmaydi" in rep["historical_separation"]
    _, human, _ = _run(cashenv, _args(co, br, "TILL-01"), capsys)
    assert "TARIX:" in human


# ═══ L) --json stdout AYNAN JSON ═══════════════════════════════════════════
def test_L_json_stdout_is_pure_json(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); db.commit()
    rc, out, err = _run(cashenv, _args(co, br, "TILL-01", extra=["--json"]), capsys)
    assert rc == 0
    rep = json.loads(out)                       # to'liq stdout yaroqli JSON
    assert rep["kind"] == "CASH_TILL_PROVISION_PLAN"
    assert "MODE:        READ-ONLY" in err
    assert "VERDICT:" in err and "VERDICT:" not in out
