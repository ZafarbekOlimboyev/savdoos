# -*- coding: utf-8 -*-
"""Cash Ledger · PRE-T0 CURRENT RUNTIME READINESS (STRICTLY READ-ONLY, PER-COMPANY).

Bu modul "T0'ga (cutover) o'tishga TAYYORMI?" savoliga KOMPANIYA-BO'YICHA javob beradi.
HECH NARSA yozmaydi: cutover_at O'RNATMAYDI, TILL yaratmaydi, smena yopmaydi, mode o'zgartirmaydi.

═══ UCHTA TUSHUNCHA QAT'IY AJRATILADI ═══════════════════════════════════════

  1. HISTORICAL_TILL_UNKNOWN      — o'tmishdagi drawer identity'sini ISBOTLAB bo'lmaydi.
                                    -> REVIEW, ledger'dan tashqarida, **HECH QACHON BLOKER EMAS**.
  2. CURRENT_BRANCH_NO_ACTIVE_TILL — filialda BUGUN drawer sozlanmagan.
                                    -> runtime TAYYORLIGI: T0'dan keyin naqd smena ocholmaydi.
  3. POST_T0_NO_ACTIVE_TILL        — T0'dan KEYIN TILL'siz naqd amal -> runtime RAD etadi.

ASOSIY QOIDA (§7): TARIXIY noaniqlik YOLG'IZ O'ZI cutover'ni TO'XTATMAYDI.
    tarixiy noaniq + joriy TILL bor + osilgan legacy smena yo'q  -> CUTOVER_READY
    tarixiy noaniq + joriy ACTIVE TILL yo'q                      -> CURRENT_RUNTIME_NOT_READY
    tarixiy noaniq + till_id=NULL ochiq legacy smena             -> CURRENT_RUNTIME_NOT_READY

Shu bois `status` FAQAT joriy runtime holatidan kelib chiqadi; tarixiy o'lchov alohida
`historical_identity_status` (CLEAN | HISTORICAL_REVIEW) sifatida HAR DOIM ko'rsatiladi va
bloklamaydi. Uchala nom ham konstanta sifatida mavjud (quyida).

cutover_at PER-COMPANY (Setting(company_id, branch_id=None, key='cash')), shu bois 7 tenant
BIR VAQTDA cutover qilishi SHART EMAS — har kompaniya alohida tayyor bo'ladi.
"""
from __future__ import annotations

from sqlalchemy import func

from app.db.cash.migration import historical_till as _hist
from app.db.cash.migration import phase1
from app.models.cash import CashAccount, CashLedgerEntry as CLE
from app.models.enums import ShiftStatus
from app.models.org import Branch, Company
from app.models.shifts import Shift
from app.services.cash import cutover as _cut

# Yakuniy status qiymatlari (§7)
CUTOVER_READY = "CUTOVER_READY"
CURRENT_RUNTIME_NOT_READY = "CURRENT_RUNTIME_NOT_READY"
# Tarixiy o'lchov (ALOHIDA, hech qachon bloklamaydi)
HISTORICAL_REVIEW = "HISTORICAL_REVIEW"
HISTORICAL_CLEAN = "CLEAN"

# Runtime tayyorligi sabab kodlari
R_NO_ACTIVE_TILL = "CURRENT_BRANCH_NO_ACTIVE_TILL"
R_OPEN_SHIFT_NO_TILL = "LEGACY_OPEN_SHIFT_WITHOUT_TILL"


def _guard_available() -> bool:
    """§16: markaziy post-T0 darvozasi mavjudmi (require_post_t0_till + cutover_open_shift_gate)."""
    try:
        from app.services.cash import cutover_guard as _cg
        return (callable(getattr(_cg, "require_post_t0_till", None))
                and callable(getattr(_cg, "cutover_open_shift_gate", None)))
    except Exception:
        return False


def _companies(db, company_id=None):
    q = db.query(Company).filter(Company.deleted_at.is_(None))
    if company_id is not None:
        q = q.filter(Company.id == company_id)
    return q.order_by(Company.code).all()


def _dt(x):
    return x.isoformat() if x is not None else None


def _branch_tills(db, co):
    """Har FAOL filial uchun BUGUNGI ACTIVE TILL soni. 0 — qonuniy holat (branch 0..N TILL),
    lekin T0'dan keyin naqd ishlash uchun kamida 1 ta kerak."""
    out = {}
    for b in db.query(Branch).filter(Branch.company_id == co.id, Branch.deleted_at.is_(None),
                                     Branch.is_active.is_(True)).all():
        n = db.query(func.count(CashAccount.id)).filter(
            CashAccount.tenant_id == co.id, CashAccount.branch_id == b.id,
            CashAccount.type == "TILL", CashAccount.status == "ACTIVE").scalar() or 0
        out[str(b.id)] = {"branch_id": str(b.id), "code": b.code, "active_tills": int(n)}
    return out


def _open_legacy_shifts(db, co):
    """OCHIQ legacy smenalar. till_id=NULL bo'lganlari T0'ni KESIB O'TSA, ular T0'dan keyin ham
    TILL'siz naqd qabul qilishda davom etadi -> cutover'dan OLDIN yopilishi yoki aniq TILL'ga
    biriktirilishi SHART. Kassir/filial/terminaldan TAXMIN QILINMAYDI."""
    rows = []
    for sh in (db.query(Shift).join(Branch, Branch.id == Shift.branch_id)
               .filter(Branch.company_id == co.id, Shift.status == ShiftStatus.open,
                       Shift.deleted_at.is_(None)).all()):
        rows.append({"shift_id": str(sh.id), "branch_id": str(sh.branch_id),
                     "opened_at": _dt(sh.opened_at),
                     "till_id": (str(sh.till_id) if sh.till_id else None),
                     "has_till": sh.till_id is not None})
    return rows


def _historical_identity(db, co):
    """Tarixiy identity o'lchovi — dalilsiz (HISTORICAL_TILL_UNKNOWN) legalar soni.
    Manba: plan_backfill + resolve (READ-ONLY). Bu o'lchov HECH QACHON bloklamaydi."""
    from app.db.cash.migration import backfill as _bf
    plan = phase1.plan_backfill(db, company_id=co.id)
    ctx = _bf._build_context(db, co.id)
    unknown = resolvable = 0
    for leg in plan["legs"]:
        acc, info = _bf.resolve_account(db, leg, ctx)
        if acc is not None:
            resolvable += 1
        elif isinstance(info, tuple) and len(info) > 2 and info[2] == _hist.HISTORICAL_TILL_UNKNOWN:
            unknown += 1
    return {"candidate_legs": len(plan["legs"]), "resolvable_legs": resolvable,
            "historical_till_unknown": unknown,
            "status": HISTORICAL_REVIEW if unknown else HISTORICAL_CLEAN,
            "blocking": False,      # ATAYLAB: tarixiy noaniqlik cutover'ni TO'XTATMAYDI
            "note": ("dalilsiz tarixiy qatorlar ledger'dan TASHQARIDA qoladi; manba jadvallari "
                     "avtoritet tarixiy dalil bo'lib qoladi. Dalil/attestatsiya paydo bo'lsa "
                     "keyinroq idempotent yoziladi. T0 uchun attestatsiya SHART EMAS.")}


def _ledger_state(db, co):
    base = db.query(CLE).filter(CLE.tenant_id == co.id)
    return {"total_rows": base.count(),
            "reconstruction_rows": base.filter(CLE.provenance == "RECONSTRUCTION").count(),
            "normal_rows": base.filter(CLE.provenance == "NORMAL").count()}


def evaluate_company(db, co) -> dict:
    """Bitta kompaniya uchun PRE-T0 tayyorlik (read-only)."""
    tills = _branch_tills(db, co)
    open_shifts = _open_legacy_shifts(db, co)
    hist = _historical_identity(db, co)
    recon = [f.as_dict() for f in phase1.reconcile_shadows(db, co.id)]
    t0 = _cut.cutover_at(db, co.id)

    blockers = []
    branches_without_till = [b for b in tills.values() if b["active_tills"] == 0]
    if branches_without_till:
        blockers.append({"code": R_NO_ACTIVE_TILL, "count": len(branches_without_till),
                         "branches": [b["code"] for b in branches_without_till],
                         "fix": ("Admin: Filial sozlamalari -> Kassalar -> + Yangi kassa. FAQAT hozir "
                                 "REAL mavjud fizik kassa(lar)ni yarating; kelajakdagi umumiy sonni "
                                 "bilish SHART EMAS, keyin migratsiyasiz qo'shsa bo'ladi.")})
    untilled_open = [s for s in open_shifts if not s["has_till"]]
    if untilled_open:
        blockers.append({"code": R_OPEN_SHIFT_NO_TILL, "count": len(untilled_open),
                         "shift_ids": [s["shift_id"] for s in untilled_open],
                         "fix": ("T0'dan OLDIN: (A) legacy smenani YOPING (afzal), so'ng T0'dan keyin "
                                 "aniq TILL bilan yangi smena oching; yoki (B) operator FIZIK drawer'ni "
                                 "ANIQ bilsa, o'sha smenani real TILL'ga biriktiring. "
                                 "Kassir/filial/terminaldan TAXMIN QILINMAYDI.")})

    # §16: post-T0 guard INFRASTRUKTURASI mavjudligi ham tayyorlik sharti — aks holda "READY" desak,
    # cutover'dan keyin TILL'siz naqd amallar jimgina o'tib ketardi.
    guard_ok = _guard_available()
    if not guard_ok:
        blockers.append({"code": "POST_T0_GUARD_UNAVAILABLE", "count": 1,
                         "fix": "app/services/cash/cutover_guard.py mavjud va import qilinadigan bo'lsin."})
    status = CURRENT_RUNTIME_NOT_READY if blockers else CUTOVER_READY
    return {
        "company": co.code, "company_id": str(co.id), "name": co.name,
        "status": status,
        # TARIXIY o'lchov — ALOHIDA va HECH QACHON bloklamaydi (§7)
        "historical_identity_status": hist["status"],
        "historical_identity": hist,
        "active_current_tills": sorted(tills.values(), key=lambda b: b["code"]),
        "branches_without_active_till": len(branches_without_till),
        "legacy_open_shifts": open_shifts,
        "legacy_open_shifts_without_till": len(untilled_open),
        "reconciliation_anomalies": [f for f in recon if f["severity"] != "INFO"],
        "reconciliation_informational": [f for f in recon if f["severity"] == "INFO"],
        "ledger_state": _ledger_state(db, co),
        "cutover_at": _dt(t0),
        "cutover_enforcement": ("ACTIVE" if _cut.cutover_reached(db, co.id) else "inactive"),
        "post_t0_guard_available": guard_ok,
        "runtime_blockers": blockers,
        "rule": ("TARIXIY noaniqlik YOLG'IZ O'ZI cutover'ni TO'XTATMAYDI. status FAQAT joriy runtime "
                 "holatidan; historical_identity_status alohida va bloklamaydi."),
    }


def evaluate(db, company_id=None) -> dict:
    """Barcha (yoki bitta) kompaniya uchun PRE-T0 tayyorlik. STRICTLY READ-ONLY.

    Har kompaniya MUSTAQIL baholanadi — cutover_at per-company bo'lgani uchun tenantlar
    BIR VAQTDA cutover qilishi SHART EMAS."""
    per = [evaluate_company(db, c) for c in _companies(db, company_id)]
    return {
        "kind": "CASH_PRE_T0_RUNTIME_READINESS",
        "per_company": per,
        "totals": {
            "companies": len(per),
            "cutover_ready": sum(1 for p in per if p["status"] == CUTOVER_READY),
            "runtime_not_ready": sum(1 for p in per if p["status"] == CURRENT_RUNTIME_NOT_READY),
            "with_historical_review": sum(1 for p in per
                                          if p["historical_identity_status"] == HISTORICAL_REVIEW),
            "historical_till_unknown_rows": sum(p["historical_identity"]["historical_till_unknown"]
                                                for p in per),
        },
        "t0_note": ("T0 BU YERDA O'RNATILMAYDI. Toza cutover shartlari: kompaniya tanlangan; joriy "
                    "fizik TILL(lar) sozlangan; legacy ochiq smenalar yopilgan/aniq hal qilingan; "
                    "offline POS yozuvlari sinxronlangan; cutover lahzasida naqd amallar pauza; "
                    "backup tekshirilgan; preflight'da HAQIQIY BLOCK yo'q; vaqt ONGLI tanlangan."),
    }
