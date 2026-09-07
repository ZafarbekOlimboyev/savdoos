# -*- coding: utf-8 -*-
"""PER-COMPANY RUNTIME READINESS CLI testlari (real PostgreSQL).

A  tayyor kompaniya            -> exit 0 + VERDICT CUTOVER_READY
B  --json                      -> yaroqli JSON + §2 majburiy maydonlar
C  --company-id                -> FAQAT o'sha tenant baholanadi
D  per-company mustaqillik     -> A tayyor, B tayyor emas (bir-biriga ta'sir qilmaydi)
E  noto'g'ri UUID              -> EXIT_USAGE
F  mavjud bo'lmagan company    -> EXIT_USAGE + COMPANY_NOT_FOUND
G  naqd filial TILL'siz        -> NO_ACTIVE_TILL + exit 2
H  naqd faoliyati YO'Q filial  -> BLOKER EMAS (advisory)
I  TILL'siz ochiq legacy smena -> OPEN_LEGACY_SHIFT_WITHOUT_TILL + exit 2
J  SAFE HAR filial uchun TALAB QILINMAYDI
K  tarixiy unknown bloklamaydi + "tarix uchun kassa yarating" TAVSIYA QILINMAYDI
L  offline sync baryeri HAR DOIM OPERATOR_CONFIRMATION_REQUIRED (navbat "bo'sh" DEYILMAYDI)
M  STRICTLY READ-ONLY: yozuv yo'q + manba skani (apply/mutatsiya yo'q, gardlar bor)
N  mijoz shaxsiy ma'lumoti CHIQMAYDI (smena ro'yxati faqat texnik id'lar)
Q  --json stdout AYNAN JSON (operator `| jq` qila olsin)
O  NAQD XARID qiladigan "ombor" filiali IDLE emas -> NO_ACTIVE_TILL (yolg'on-tayyorlik regressiyasi)
P  ARCHIVED/boshqa-filial TILL'ga bog'langan ochiq smena TAYYOR deb sanalmaydi (till_state)
"""
from __future__ import annotations

import ast
import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.cash.migration import runtime_readiness as RR
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.customers import Customer, CustomerPayment
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.shifts import Shift
from app.services.cash import till_identity as _ti
from app.tools import cash_runtime_readiness as CLI

CLI_PATH = pathlib.Path(__file__).resolve().parents[2] / "app" / "tools" / "cash_runtime_readiness.py"


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _sf(cashenv):
    return (lambda: Session(cashenv.engine)), cashenv.engine


def _co(db):
    c = Company(name="RC" + _hex(), code="rc" + _hex(), currency="UZS"); db.add(c); db.flush(); return c


def _br(db, co):
    b = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True)
    db.add(b); db.flush(); return b


def _emp(db, co, br):
    e = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(e); db.flush(); db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id)); db.flush(); return e


def _acct(db, co, br, kind):
    a = CashAccount(tenant_id=co.id, branch_id=br.id, type=kind, currency="UZS", status="ACTIVE",
                    label=(_ti.till_label("T-" + _hex(), None) if kind == "TILL" else "SEYF"),
                    created_at=_now())
    db.add(a); db.flush(); return a


def _cash_activity(db, co, br, emp):
    """Filialning naqd bilan ishlashiga DALIL (ayni paytda dalilsiz tarixiy qator ham)."""
    cu = Customer(company_id=co.id, code="M" + _hex(), full_name="Mijoz Ismi Sirli",
                  phone="+998900000000", credit_balance=Decimal("0"))
    db.add(cu); db.flush()
    t = _now() - timedelta(days=200)
    p = CustomerPayment(customer_id=cu.id, amount=Decimal("3000"), method="cash", paid_at=t,
                        created_at=t, employee_id=emp.id, branch_id=br.id)
    db.add(p); db.flush(); return cu, p


def _ready_tenant(db):
    """Naqd bilan ishlaydigan, ACTIVE TILL'li, osilgan smenasiz kompaniya."""
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _acct(db, co, br, "TILL")
    _cash_activity(db, co, br, emp)
    db.commit()
    return co, br, emp


def _json(out: str) -> dict:
    """JSON blokini sarlavha/VERDICT matnidan ajratib oladi (raw_decode -> keyingi matn e'tiborsiz)."""
    return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]


def _run(cashenv, argv, capsys):
    sf, eng = _sf(cashenv)
    rc = CLI.main(argv, session_factory=sf, engine=eng)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ═══ A) tayyor kompaniya -> exit 0 ═════════════════════════════════════════
def test_A_ready_company_exit_zero(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    rc, out, err = _run(cashenv, ["--company-id", str(co.id)], capsys)
    assert rc == 0, out + err
    assert f"VERDICT: {RR.CUTOVER_READY}" in out
    assert "MODE:        READ-ONLY" in out
    assert "APPLY MODE: NONE" in out


# ═══ B) --json -> yaroqli JSON + §2 majburiy maydonlar ═════════════════════
def test_B_json_shape(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    _acct(db, co, br, "SAFE"); db.commit()
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    assert rc == 0, out
    rep = _json(out)
    assert rep["kind"] == "CASH_PER_COMPANY_RUNTIME_READINESS"
    assert rep["apply_mode"] == "NONE" and rep["read_only"] is True
    p = rep["per_company"][0]
    # §2: talab qilingan maydonlar
    for k in ("status", "branches", "safe_configuration", "cash_transacting_branches",
              "open_shifts_total", "open_shifts_with_till", "legacy_open_shifts",
              "legacy_open_shifts_without_till", "historical_identity",
              "offline_sync_barrier", "post_t0_guard_available", "schema_ready",
              "runtime_blockers", "cutover_at"):
        assert k in p, f"JSON'da {k} yo'q"
    assert p["status"] in (RR.CUTOVER_READY, RR.CURRENT_RUNTIME_NOT_READY)   # FAQAT ikki qiymat
    assert p["safe_configuration"][0]["active_safes"] == 1
    assert p["historical_identity"]["historical_till_unknown"] >= 1
    assert p["offline_sync_barrier"] == RR.OPERATOR_CONFIRMATION_REQUIRED


# ═══ C) --company-id FAQAT o'sha tenantni baholaydi ════════════════════════
def test_C_company_scope(db, cashenv, capsys):
    coA, *_ = _ready_tenant(db)
    coB, *_ = _ready_tenant(db)
    rc, out, _ = _run(cashenv, ["--company-id", str(coA.id), "--json"], capsys)
    rep = _json(out)
    assert rc == 0
    assert rep["scope"] == "SINGLE_COMPANY"
    assert [p["company_id"] for p in rep["per_company"]] == [str(coA.id)]
    assert rep["totals"]["companies"] == 1


# ═══ D) per-company mustaqillik ═══════════════════════════════════════════
def test_D_per_company_independence(db, cashenv, capsys):
    coA, *_ = _ready_tenant(db)
    coB = _co(db); brB = _br(db, coB); empB = _emp(db, coB, brB)
    _cash_activity(db, coB, brB, empB); db.commit()        # B naqd ishlaydi, TILL YO'Q
    rcA, outA, _ = _run(cashenv, ["--company-id", str(coA.id)], capsys)
    rcB, outB, _ = _run(cashenv, ["--company-id", str(coB.id)], capsys)
    assert rcA == 0 and f"VERDICT: {RR.CUTOVER_READY}" in outA
    assert rcB == 2 and f"VERDICT: {RR.CURRENT_RUNTIME_NOT_READY}" in outB
    assert RR.R_NO_ACTIVE_TILL in outB


# ═══ E) noto'g'ri UUID -> usage ═══════════════════════════════════════════
def test_E_bad_uuid_is_usage_error(db, cashenv, capsys):
    rc, out, err = _run(cashenv, ["--company-id", "not-a-uuid"], capsys)
    assert rc == 1
    assert "USAGE" in err


# ═══ F) mavjud bo'lmagan kompaniya -> COMPANY_NOT_FOUND ═══════════════════
def test_F_unknown_company_not_found(db, cashenv, capsys):
    rc, out, err = _run(cashenv, ["--company-id", str(uuid.uuid4())], capsys)
    assert rc == 1
    assert "COMPANY_NOT_FOUND" in err


# ═══ G) naqd filial TILL'siz -> NO_ACTIVE_TILL ════════════════════════════
def test_G_cash_branch_without_till_blocks(db, cashenv, capsys):
    co = _co(db); br = _br(db, co); emp = _emp(db, co, br)
    _cash_activity(db, co, br, emp); db.commit()
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(out)
    p = rep["per_company"][0]
    assert rc == 2
    assert p["status"] == RR.CURRENT_RUNTIME_NOT_READY
    assert RR.R_NO_ACTIVE_TILL in [b["code"] for b in p["runtime_blockers"]]
    assert p["cash_transacting_branches"] == [br.code]
    # §3: sabab ANIQ — mavhum "REVIEW" emas
    assert RR.R_NO_ACTIVE_TILL in rep["reason_catalog"]
    # §7: tool "tekshirdim" deb YOLG'ON aytmaydi — muvaffaqiyatsiz shart FAIL deb ko'rsatiladi
    tv = {x["code"]: x for x in rep["cutover_decision"]["tool_verified"]}
    assert tv[RR.R_NO_ACTIVE_TILL]["state"] == "FAIL"
    assert tv[RR.R_NO_ACTIVE_TILL]["failing_companies"] == [co.code]
    assert tv[RR.R_GUARD_NOT_READY]["state"] == "PASS"
    assert tv[RR.R_SCHEMA_NOT_READY]["state"] == "PASS"


# ═══ H) naqd faoliyati YO'Q filial BLOKLAMAYDI ════════════════════════════
def test_H_idle_branch_without_till_is_not_a_blocker(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    idle = _br(db, co); db.commit()                    # ombor/ofis: naqd faoliyat YO'Q, TILL YO'Q
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(out)
    p = rep["per_company"][0]
    assert rc == 0, out
    assert p["status"] == RR.CUTOVER_READY
    assert idle.code in p["idle_branches_without_till"]
    assert idle.code not in p["cash_transacting_branches"]
    assert p["branches_without_active_till"] == 0


# ═══ I) TILL'siz ochiq legacy smena -> bloker ═════════════════════════════
def test_I_untilled_open_shift_blocks(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=3),
               opening_cash=Decimal("0"), status=ShiftStatus.open, till_id=None)
    db.add(sh); db.commit()
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    assert rc == 2
    assert RR.R_OPEN_SHIFT_NO_TILL in out
    assert str(sh.id) in out                      # §6: smena RO'YXATLANADI
    assert "till=NULL" in out


# ═══ J) SAFE HAR filial uchun TALAB QILINMAYDI ════════════════════════════
def test_J_safe_not_required_per_branch(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)                # TILL bor, SAFE YO'Q
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(out)
    p = rep["per_company"][0]
    assert rc == 0, out
    assert p["status"] == RR.CUTOVER_READY                      # SAFE yo'qligi BLOKLAMADI
    assert p["safe_configuration"] == [{"branch": br.code, "active_safes": 0}]
    codes = [b["code"] for b in p["runtime_blockers"]]
    assert not any("SAFE" in c for c in codes)
    rc2, human, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    assert "SAFE: majburiy EMAS" in human


# ═══ K) tarixiy unknown bloklamaydi + tarix uchun TILL TAVSIYA QILINMAYDI ══
def test_K_historical_unknown_never_blocks_and_no_till_advice(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(out)
    p = rep["per_company"][0]
    assert rc == 0
    assert p["historical_identity_status"] == RR.HISTORICAL_REVIEW
    assert p["historical_identity"]["blocking"] is False
    assert p["status"] == RR.CUTOVER_READY
    assert rep["historical_identity_policy"]["blocking"] is False
    # §5: tarixiy blok "kassa yarating" tavsiyasi bilan ARALASHTIRILMAYDI
    assert "HAL QILMAYDI" in rep["historical_identity_policy"]["do_not"]
    _, human, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    hist_line = [l for l in human.splitlines() if "TARIXIY IDENTITY" in l][0]
    idx = human.splitlines().index(hist_line)
    advice = "\n".join(human.splitlines()[idx:idx + 2])
    assert "HAL QILMAYDI" in advice
    # NO_ACTIVE_TILL yechimi tarixiy bo'limda TAKRORLANMAYDI
    assert "Yangi kassa" not in advice


# ═══ L) offline sync baryeri — navbat "bo'sh" deb E'LON QILINMAYDI ════════
def test_L_offline_sync_barrier_always_operator_confirmed(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(out)
    p = rep["per_company"][0]
    assert rc == 0                                             # TAYYOR bo'lsa ham baryer qoladi
    assert p["offline_sync_barrier"] == RR.OPERATOR_CONFIRMATION_REQUIRED
    assert p["operator_confirmations"][0]["code"] == RR.R_OFFLINE_SYNC
    dq = rep["cutover_decision"]["device_queue"]
    assert dq["state"] == RR.OPERATOR_CONFIRMATION_REQUIRED
    assert dq["claim"] == "NOT_VERIFIABLE_BY_TOOL"
    assert rep["cutover_decision"]["t0_set_by_this_tool"] is False
    _, human, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    assert f"OFFLINE SYNC BARRIER: {RR.OPERATOR_CONFIRMATION_REQUIRED}" in human
    # Tool navbatni BO'SH deb TASDIQLAMAYDI: "navbat bo'sh" uchraydigan HAR bir satr INKOR bo'lishi shart.
    for line in human.splitlines():
        low = line.lower()
        if "navbat bo'sh" in low or "queue empty" in low or "queue is empty" in low:
            assert any(neg in low for neg in ("olmaydi", "qilmaydi", "emas", "tasdiq")),                 f"tool navbatni BO'SH deb e'lon qildi: {line.strip()}"


# ═══ M) STRICTLY READ-ONLY (runtime + manba skani) ════════════════════════
def test_M_strictly_read_only(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    n_acc = db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count()
    n_set = db.query(Setting).filter(Setting.company_id == co.id).count()
    n_sh = db.query(Shift).join(Branch, Branch.id == Shift.branch_id).filter(
        Branch.company_id == co.id).count()
    _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    db.expire_all()
    assert db.query(CashAccount).filter(CashAccount.tenant_id == co.id).count() == n_acc
    assert db.query(Setting).filter(Setting.company_id == co.id).count() == n_set
    assert db.query(Shift).join(Branch, Branch.id == Shift.branch_id).filter(
        Branch.company_id == co.id).count() == n_sh

    src = CLI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # apply rejimi UMUMAN yo'q: argparse'da --apply bayrog'i ham, apply shoxobchasi ham yo'q
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for a in node.args:
                assert not (isinstance(a, ast.Constant) and str(a.value).startswith("--apply")),                     "CLI'da --apply bayrog'i mavjud"
    assert "args.apply" not in src and "apply=True" not in src
    # mutatsiya chaqiruvlari yo'q
    banned = {"commit", "add", "add_all", "flush", "merge", "bulk_save_objects", "execute"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in banned, f"mutatsiya chaqiruvi: .{node.func.attr}()"
    # DDL/DML matni yo'q
    for kw in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP ", "ALTER ", "TRUNCATE "):
        assert kw not in src.upper().replace("NO GIT", ""), f"DDL/DML topildi: {kw}"
    # gardlar + rollback/close bor
    for need in ("guard_never_primary", "require_postgres_cash", "db.rollback()", "db.close()"):
        assert need in src, f"{need} yo'q"
    # T0/TILL/smena mutatsiyasi yo'q
    for forbidden in ("cutover_at\"] =", "set_cutover", "CashAccount(", "ShiftStatus.closed",
                      "cash_mode ="):
        assert forbidden not in src, f"taqiqlangan amal: {forbidden}"


# ═══ N) mijoz shaxsiy ma'lumoti CHIQMAYDI ═════════════════════════════════
def test_N_no_sensitive_customer_data(db, cashenv, capsys):
    co, br, emp = _ready_tenant(db)
    cu, _p = _cash_activity(db, co, br, emp)
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=1),
               opening_cash=Decimal("0"), status=ShiftStatus.open, till_id=None)
    db.add(sh); db.commit()
    rc_h, human, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    rc_j, js, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    rep = _json(js)
    for blob in (human, js):
        assert cu.full_name not in blob
        assert cu.phone not in blob
        assert cu.code not in blob
    # smena ro'yxati FAQAT texnik identifikatorlar
    assert set(rep["per_company"][0]["legacy_open_shifts"][0]) == {
        "shift_id", "branch_id", "opened_at", "till_id", "till_state", "has_till"}
    # sirlar chiqmaydi
    assert "DATABASE_URL present:" in human and "postgresql://" not in human


# ═══ O) naqd XARID qiladigan ombor IDLE emas (yolg'on-tayyorlik REGRESSIYASI) ═══
def test_O_cash_purchase_branch_is_not_idle(db, cashenv, capsys):
    """Mol qabul qilib NAQD to'laydigan ombor T0'dan keyin explicit custody TALAB qiladi
    (resolve_cash_custody -> require_custody_account FILIAL mosligini tekshiradi).
    Uni "bo'sh filial" deb sanash aynan shu tool oldini olishi kerak bo'lgan YOLG'ON-TAYYORLIK."""
    from app.models.purchasing import Purchase, Supplier
    from app.models.enums import PurchaseStatus
    co, br, emp = _ready_tenant(db)                       # savdo filiali TILL bilan -> tayyor
    wh = _br(db, co)                                      # OMBOR: sotuv/smena/qaytarish YO'Q
    sup = Supplier(company_id=co.id, name="T" + _hex()); db.add(sup); db.flush()
    db.add(Purchase(doc_no="D" + _hex(), company_id=co.id, branch_id=wh.id, supplier_id=sup.id,
                    purchase_date=_now().date(), status=PurchaseStatus.received,
                    subtotal=Decimal("50000"), total=Decimal("50000"),
                    paid_amount=Decimal("50000"),
                    created_at=_now() - timedelta(days=5)))   # NAQD (SupplierLedger charge YO'Q)
    db.commit()

    rc, out, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    p = _json(out)["per_company"][0]
    assert wh.code in p["cash_transacting_branches"], "naqd xarid qiluvchi ombor IDLE deb sanaldi"
    assert wh.code not in p["idle_branches_without_till"]
    assert p["status"] == RR.CURRENT_RUNTIME_NOT_READY
    assert RR.R_NO_ACTIVE_TILL in [b["code"] for b in p["runtime_blockers"]]
    assert rc == 2

    _acct(db, co, wh, "TILL"); db.commit()                # ombor kassasi sozlandi -> tayyor
    rc2, out2, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    assert rc2 == 0 and _json(out2)["per_company"][0]["status"] == RR.CUTOVER_READY


# ═══ P) ochiq smena YAROQSIZ TILL'ga bog'langan -> TAYYOR EMAS ═════════════
def test_P_open_shift_with_invalid_till_is_not_ready(db, cashenv, capsys):
    """`till_id IS NOT NULL` YETARLI EMAS. cutover_guard.require_post_t0_till kassani
    ACTIVE + shu tenant + shu filial deb TEKSHIRADI; readiness ham xuddi shunday tekshirishi kerak,
    aks holda T0 o'rnatilgach kassir smena o'rtasida TILL_INVALID bilan to'xtab qolardi."""
    co, br, emp = _ready_tenant(db)
    till = _acct(db, co, br, "TILL")
    sh = Shift(branch_id=br.id, cashier_id=emp.id, opened_at=_now() - timedelta(hours=2),
               opening_cash=Decimal("0"), status=ShiftStatus.open, till_id=till.id)
    db.add(sh); db.commit()
    rc0, out0, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    p0 = _json(out0)["per_company"][0]
    assert rc0 == 0 and p0["status"] == RR.CUTOVER_READY          # yaroqli TILL -> bloker YO'Q
    assert p0["legacy_open_shifts"][0]["till_state"] == "VALID"
    assert p0["open_shifts_with_till"] == 1

    # Admin kassani deaktivatsiya qildi (PATCH /tills active=false) — ochiq smena tekshirilmaydi
    till.status = "ARCHIVED"; db.add(till); db.commit()
    rc1, out1, _ = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    p1 = _json(out1)["per_company"][0]
    assert rc1 == 2, "ARCHIVED kassali ochiq smena YOLG'ON tayyor deb ko'rsatildi"
    assert p1["status"] == RR.CURRENT_RUNTIME_NOT_READY
    assert p1["legacy_open_shifts"][0]["till_state"] == "ARCHIVED"
    assert p1["open_shifts_with_till"] == 0
    blk = next(b for b in p1["runtime_blockers"] if b["code"] == RR.R_OPEN_SHIFT_NO_TILL)
    assert blk["till_states"][str(sh.id)] == "ARCHIVED"
    _, human, _ = _run(cashenv, ["--company-id", str(co.id)], capsys)
    assert "till_state=ARCHIVED" in human

    # boshqa filialning kassasiga bog'langan smena ham YAROQSIZ
    other = _br(db, co); other_till = _acct(db, co, other, "TILL")
    sh.till_id = other_till.id; db.add(sh); db.commit()
    p2 = _json(_run(cashenv, ["--company-id", str(co.id), "--json"], capsys)[1])["per_company"][0]
    assert p2["legacy_open_shifts"][0]["till_state"] == "WRONG_BRANCH"
    assert p2["status"] == RR.CURRENT_RUNTIME_NOT_READY


# ═══ Q) --json stdout AYNAN JSON (sarlavha/VERDICT stderr'ga) ══════════════
def test_Q_json_stdout_is_pure_json(db, cashenv, capsys):
    """§10 tekshirish buyrug'i `--json` bilan ishlatiladi; operator uni `| jq` yoki faylga
    yo'naltirsa, stdout'da FAQAT JSON bo'lishi SHART."""
    co, br, emp = _ready_tenant(db)
    rc, out, err = _run(cashenv, ["--company-id", str(co.id), "--json"], capsys)
    assert rc == 0
    rep = json.loads(out)                       # raw_decode EMAS — to'liq stdout yaroqli JSON
    assert rep["kind"] == "CASH_PER_COMPANY_RUNTIME_READINESS"
    assert "MODE:        READ-ONLY" in err      # odam-o'qiydigan matn stderr'da
    assert "VERDICT:" in err and "VERDICT:" not in out
