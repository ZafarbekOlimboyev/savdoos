# -*- coding: utf-8 -*-
"""Cash Ledger · PRE-T0 CURRENT RUNTIME READINESS (STRICTLY READ-ONLY, PER-COMPANY).

Bu modul "T0'ga (cutover) o'tishga TAYYORMI?" savoliga KOMPANIYA-BO'YICHA javob beradi.
HECH NARSA yozmaydi: cutover_at O'RNATMAYDI, TILL yaratmaydi, smena yopmaydi, mode o'zgartirmaydi.

═══ UCHTA TUSHUNCHA QAT'IY AJRATILADI ═══════════════════════════════════════

  1. HISTORICAL_TILL_UNKNOWN — o'tmishdagi drawer identity'sini ISBOTLAB bo'lmaydi.
       -> REVIEW, ledger'dan tashqarida, **HECH QACHON BLOKER EMAS** (historical_till.py konstantasi).
  2. NO_ACTIVE_TILL — naqd bilan ishlaydigan filialda BUGUN drawer sozlanmagan.
       -> runtime TAYYORLIGI: T0'dan keyin naqd smena ocholmaydi. Shu modul EMIT qiladigan kod
       (R_NO_ACTIVE_TILL). DIQQAT: phase0 dagi bir xil ma'noli `CURRENT_BRANCH_NO_ACTIVE_TILL`
       BOSHQA topilma — u preflight'da REVIEW (bloklamaydi); ikkisi ARALASHTIRILMASIN.
  3. T0'DAN KEYINGI RAD ETISH — TILL'siz naqd amal runtime tomonidan rad etiladi. Kodlar shu modulda
       EMAS, `cutover_guard.py` da (TILL_REQUIRED_AFTER_CUTOVER, LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER).

ASOSIY QOIDA (§7): TARIXIY noaniqlik YOLG'IZ O'ZI cutover'ni TO'XTATMAYDI.
    tarixiy noaniq + joriy TILL bor + osilgan legacy smena yo'q  -> CUTOVER_READY
    tarixiy noaniq + joriy ACTIVE TILL yo'q                      -> CURRENT_RUNTIME_NOT_READY
    tarixiy noaniq + till_id=NULL ochiq legacy smena             -> CURRENT_RUNTIME_NOT_READY

Shu bois `status` FAQAT joriy runtime holatidan kelib chiqadi; tarixiy o'lchov alohida
`historical_identity_status` (CLEAN | HISTORICAL_REVIEW) sifatida HAR DOIM ko'rsatiladi va
bloklamaydi. Shu modul EMIT qiladigan bloker kodlari quyida R_* konstantalar sifatida.

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

# §3 ANIQ sabab kodlari (mavhum "REVIEW" EMAS — operator nima qilishni biladi)
R_NO_ACTIVE_TILL = "NO_ACTIVE_TILL"
R_OPEN_SHIFT_NO_TILL = "OPEN_LEGACY_SHIFT_WITHOUT_TILL"
R_RECON_ANOMALY = "REAL_RECONCILIATION_ANOMALY"
R_SCHEMA_NOT_READY = "SCHEMA_NOT_READY"
R_GUARD_NOT_READY = "GUARD_NOT_READY"
# Operator TASDIQI (tizim ISBOTLAY OLMAYDI — avtomatik "bo'sh" deb e'lon QILINMAYDI)
R_OFFLINE_SYNC = "OFFLINE_SYNC_CONFIRMATION_REQUIRED"
OPERATOR_CONFIRMATION_REQUIRED = "OPERATOR_CONFIRMATION_REQUIRED"


def _guard_available() -> bool:
    """§16: markaziy post-T0 darvozasi mavjudmi (require_post_t0_till + cutover_open_shift_gate)."""
    try:
        from app.services.cash import cutover_guard as _cg
        return (callable(getattr(_cg, "require_post_t0_till", None))
                and callable(getattr(_cg, "cutover_open_shift_gate", None)))
    except Exception:
        return False


def _schema_ready(db) -> bool:
    """cash sxemasi deploy qilinganmi (Postgres). Bo'lmasa hech qanday runtime custody ishlamaydi."""
    try:
        from sqlalchemy import text
        if db.get_bind().dialect.name != "postgresql":
            return False
        return db.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'")).first() is not None
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
        def _cnt(kind):
            return int(db.query(func.count(CashAccount.id)).filter(
                CashAccount.tenant_id == co.id, CashAccount.branch_id == b.id,
                CashAccount.type == kind, CashAccount.status == "ACTIVE").scalar() or 0)
        out[str(b.id)] = {"branch_id": str(b.id), "code": b.code,
                          "active_tills": _cnt("TILL"), "active_safes": _cnt("SAFE"),
                          # §2/§7: FAQAT naqd bilan ishlaydigan filial TILL TALAB qiladi.
                          # Dalil: smena / sotuv / qaytarish / filialga bog'langan naqd qarz to'lovi.
                          "cash_transacting": _cash_transacting(db, co, b)}
    return out


def _cash_transacting(db, co, b) -> bool:
    """Filial HAQIQATAN naqd bilan ishlaydimi (dalil asosida, TAXMIN emas).
    Naqd faoliyati bo'lmagan filial (masalan sof tranzit ombor) cutover'ni BLOKLAMASLIGI kerak.

    QAMROV: T0'dan keyin FILIALGA BOG'LANGAN custody talab qiladigan HAR BIR fizik naqd manbasi.
    phase1.plan_backfill 8 ta manba turini biladi; ular shu yerda quyidagicha qoplanadi:
      SHIFT_OPEN/SALE/RETURN/CUSTOMER_PAYMENT — to'g'ridan-to'g'ri so'rov;
      CASH_OP                                 — CashMovement.shift_id NOT NULL -> Shift orqali;
      PURCHASE / PURCHASE_RETURN              — to'g'ridan-to'g'ri so'rov (quyida);
      SUPPLIER_PAYMENT                        — filialga bog'lanmagan (purchases.py smenasiz holatда
                                                branch_id=None uzatadi) -> filial dalili EMAS.
    DIQQAT (ombor!): mol qabul qilib NAQD to'laydigan ombor T0'dan keyin explicit TILL/SAFE custody
    TALAB qiladi (resolve_cash_custody -> require_custody_account filial mosligini tekshiradi), shu
    bois u "bo'sh filial" EMAS. Buni o'tkazib yuborish aynan shu tool oldini olishi kerak bo'lgan
    YOLG'ON-TAYYORLIK bo'lardi.

    ATAYLAB soft-delete bo'yicha filtr YO'Q: o'chirilgan yozuv ham fizik naqd SODIR bo'lganini
    ko'rsatadi — bu yerda EHTIYOTKOR (ko'proq bloker) tomonga og'ish TO'G'RI."""
    from app.models.customers import CustomerPayment
    from app.models.purchasing import Purchase, PurchaseReturn
    from app.models.sales import Return, Sale
    if db.query(Shift.id).filter(Shift.branch_id == b.id).first():
        return True
    if db.query(Sale.id).filter(Sale.branch_id == b.id).first():
        return True
    if db.query(Return.id).filter(Return.branch_id == b.id).first():
        return True
    if db.query(CustomerPayment.id).filter(CustomerPayment.branch_id == b.id,
                                           CustomerPayment.method == "cash").first():
        return True
    # NAQD xarid = yaratilishда chiqim (SupplierLedger charge YO'Q). AYNAN backfill planeridagi
    # predikat ishlatiladi (_no_charge_exists) — readiness va ledger tushunchasi AJRALIB KETMASIN.
    if db.query(Purchase.id).filter(Purchase.branch_id == b.id,
                                    phase1._no_charge_exists()).first():
        return True
    if (db.query(PurchaseReturn.id).join(Purchase, Purchase.id == PurchaseReturn.purchase_id)
            .filter(PurchaseReturn.branch_id == b.id, phase1._no_charge_exists()).first()):
        return True
    return False


def _shift_till_state(db, co, sh) -> tuple:
    """Smenaning kassasi T0'dan KEYIN runtime QABUL QILADIGAN holatdami — AYNAN
    `cutover_guard.require_post_t0_till` tekshiradigan shartlar bo'yicha (mavjud, type=TILL, ACTIVE,
    shu tenant, shu filial). `till_id IS NOT NULL` YETARLI EMAS: ARCHIVED yoki boshqa filial kassasiga
    bog'langan ochiq smena T0'dan keyin TILL_INVALID bilan RAD etiladi, ya'ni u TAYYOR emas.
    Qaytaradi (state, ok). Kassa TAXMIN QILINMAYDI — faqat smenadagi AYNAN id tekshiriladi."""
    if sh.till_id is None:
        return "MISSING", False
    acc = db.get(CashAccount, sh.till_id)
    if acc is None:
        return "NOT_FOUND", False
    if str(acc.tenant_id) != str(co.id):
        return "WRONG_TENANT", False
    if acc.type != "TILL":
        return "NOT_A_TILL", False
    if acc.status != "ACTIVE":
        return "ARCHIVED", False
    if str(acc.branch_id) != str(sh.branch_id):
        return "WRONG_BRANCH", False
    return "VALID", True


def _open_legacy_shifts(db, co):
    """OCHIQ legacy smenalar. Kassasi YO'Q yoki YAROQSIZ bo'lganlari T0'ni KESIB O'TSA, ular T0'dan
    keyin naqd qabul qilolmaydi (runtime rad etadi) -> cutover'dan OLDIN yopilishi yoki AYNAN yaroqli
    joriy TILL'ga biriktirilishi SHART. Kassir/filial/terminaldan TAXMIN QILINMAYDI."""
    rows = []
    for sh in (db.query(Shift).join(Branch, Branch.id == Shift.branch_id)
               .filter(Branch.company_id == co.id, Shift.status == ShiftStatus.open,
                       Shift.deleted_at.is_(None)).all()):
        state, ok = _shift_till_state(db, co, sh)
        rows.append({"shift_id": str(sh.id), "branch_id": str(sh.branch_id),
                     "opened_at": _dt(sh.opened_at),
                     "till_id": (str(sh.till_id) if sh.till_id else None),
                     "till_state": state,          # MISSING|NOT_FOUND|WRONG_TENANT|NOT_A_TILL|ARCHIVED|WRONG_BRANCH|VALID
                     "has_till": ok})              # AYNAN yaroqli joriy TILL (validatsiyalangan)
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
    # §7: FAQAT naqd bilan ishlaydigan filial ACTIVE TILL talab qiladi. Naqd faoliyati bo'lmagan
    # filial (ombor/ofis) cutover'ni BLOKLAMAYDI — u alohida advisory sifatida ko'rsatiladi.
    branches_without_till = [b for b in tills.values()
                             if b["active_tills"] == 0 and b["cash_transacting"]]
    idle_without_till = [b for b in tills.values()
                         if b["active_tills"] == 0 and not b["cash_transacting"]]
    if branches_without_till:
        blockers.append({"code": R_NO_ACTIVE_TILL, "count": len(branches_without_till),
                         "branches": [b["code"] for b in branches_without_till],
                         "fix": ("POST /api/v1/tills (permission: sozlamalar.edit) — hozircha DESKTOP "
                                 "EKRANI YO'Q, chaqiruv API orqali qilinadi. FAQAT hozir REAL mavjud "
                                 "fizik kassa(lar)ni yarating; kelajakdagi umumiy sonni bilish SHART "
                                 "EMAS, keyin migratsiyasiz qo'shsa bo'ladi. Avval read-only reja: "
                                 "python -m app.tools.cash_till_plan --company-id <co> --branch-id <br> "
                                 "--code TILL-01")})
    untilled_open = [s for s in open_shifts if not s["has_till"]]
    if untilled_open:
        blockers.append({"code": R_OPEN_SHIFT_NO_TILL, "count": len(untilled_open),
                         "shift_ids": [s["shift_id"] for s in untilled_open],
                         # ANIQ sabab: kassa umuman yo'qmi, yoki ARCHIVED/boshqa filialnikimi
                         "till_states": {s["shift_id"]: s["till_state"] for s in untilled_open},
                         "fix": ("T0'dan OLDIN: (A) legacy smenani YOPING (afzal), so'ng T0'dan keyin "
                                 "aniq TILL bilan yangi smena oching; yoki (B) operator FIZIK drawer'ni "
                                 "ANIQ bilsa, o'sha smenani YAROQLI (ACTIVE, shu filial) TILL'ga "
                                 "biriktiring. till_state=ARCHIVED bo'lsa kassani qayta faollashtiring "
                                 "yoki smenani yoping. Kassir/filial/terminaldan TAXMIN QILINMAYDI.")})

    # §16: post-T0 guard INFRASTRUKTURASI mavjudligi ham tayyorlik sharti — aks holda "READY" desak,
    # cutover'dan keyin TILL'siz naqd amallar jimgina o'tib ketardi.
    anomalies = [f for f in recon if f["severity"] != "INFO"]
    if anomalies:
        blockers.append({"code": R_RECON_ANOMALY, "count": len(anomalies),
                         "codes": [f["code"] for f in anomalies],
                         "fix": ("Rostakam nomuvofiqlik (masalan ORTIQCHA/orphan soya) — "
                                 "cash_reconcile_probe bilan ROW-DARAJADA tekshiring.")})
    guard_ok = _guard_available()
    if not guard_ok:
        blockers.append({"code": R_GUARD_NOT_READY, "count": 1,
                         "fix": "app/services/cash/cutover_guard.py mavjud va import qilinadigan bo'lsin."})
    schema_ok = _schema_ready(db)
    if not schema_ok:
        blockers.append({"code": R_SCHEMA_NOT_READY, "count": 1,
                         "fix": "cash sxemasi deploy qilinsin (Postgres) — usiz runtime custody ishlamaydi."})
    status = CURRENT_RUNTIME_NOT_READY if blockers else CUTOVER_READY

    # §7: OFFLINE SINXRONIZATSIYA BARYERI — tizim POS navbati bo'sh ekanini ISBOTLAY OLMAYDI.
    # Shu bois u HAR DOIM operator tasdig'ini talab qiladi va AVTOMATIK "bo'sh" deb e'lon qilinmaydi.
    # Bu texnik bloker EMAS (status'ga kirmaydi), lekin T0 O'RNATISHDAN OLDIN BAJARILISHI SHART.
    confirmations = [{"code": R_OFFLINE_SYNC, "state": OPERATOR_CONFIRMATION_REQUIRED,
                      "fix": ("T0'dan OLDIN: naqd yozuvlarni qisqa pauza qiling, HAR BIR POS "
                              "qurilmasi kutilayotgan offline navbatini yuborsin, navbat = 0 "
                              "ekanini tasdiqlang. Tizim buni o'zi TEKSHIRA OLMAYDI.")}]
    return {
        "company": co.code, "company_id": str(co.id), "name": co.name,
        "status": status,
        # TARIXIY o'lchov — ALOHIDA va HECH QACHON bloklamaydi (§7)
        "historical_identity_status": hist["status"],
        "historical_identity": hist,
        "branches": sorted(tills.values(), key=lambda b: b["code"]),
        "active_current_tills": sorted(tills.values(), key=lambda b: b["code"]),   # nom mosligi
        "cash_transacting_branches": [b["code"] for b in tills.values() if b["cash_transacting"]],
        "branches_without_active_till": len(branches_without_till),
        "idle_branches_without_till": [b["code"] for b in idle_without_till],   # advisory, BLOKER EMAS
        # §4: SAFE sozlamasi ALOHIDA ko'rsatiladi — HAR filial uchun AVTOMATIK TALAB QILINMAYDI.
        "safe_configuration": [{"branch": b["code"], "active_safes": b["active_safes"]}
                               for b in sorted(tills.values(), key=lambda b: b["code"])],
        "open_shifts_total": len(open_shifts),
        "open_shifts_with_till": sum(1 for s_ in open_shifts if s_["has_till"]),
        "legacy_open_shifts": open_shifts,
        "legacy_open_shifts_without_till": len(untilled_open),
        "schema_ready": schema_ok,
        "offline_sync_barrier": OPERATOR_CONFIRMATION_REQUIRED,
        "operator_confirmations": confirmations,
        "reconciliation_anomalies": anomalies,
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
