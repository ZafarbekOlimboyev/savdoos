# -*- coding: utf-8 -*-
"""Cash Ledger · Migration Phase 0 — Prepare & Production Readiness (toolkit).

MUHIM QOIDALAR (bu modul ularга RIOYA qiladi):
  * cash.cash_ledger_entries'ga HECH NARSA yozilmaydi — dry-run FAQAT hisobot.
  * Legacy biznes ma'lumoti Phase 0'да o'zgartirilmaydi/tuzatilmaydi (audit — tasnif, remont emas).
  * Tarixiy backfill / cutover BU YERDA emas (keyingi fazalar).
  * Mapping "taxmin qilmaydi": ishonchsiz fizik-drawer identity -> AMBIGUOUS + operator-review istisnosi.

REAL FIZIK MODEL (revision): BIR FILIAL != BIR TILL. Har fizik checkout/kassa (alohida cash drawer) =
alohida TILL; kassir TILL emas (kassir almashadi, drawer o'zgarmaydi); har branch (odatda) 1 SAFE
(shiftless). Fizik checkout aniqlash (till_identity.detect_physical_checkouts) ustuvorligi:
OPERATOR_MAPPING > EXISTING (allaqачон provisionланган TILL) > TERMINAL (distinct Shift.terminal_id) >
AMBIGUOUS. "Ko'p kassir = ko'p TILL" HECH QACHON taxmin qilinmaydi — terminal dalili yoki explicit
operator mapping bo'lmasa AMBIGUOUS (BLOCK; provision + backfill to'xtaydi). Fizik identity ratifikatsiya
qilинган JADVALni o'zgartirmasдан `cash_accounts.label`да saqlanadi (till_identity konvensiyasi).

Read-only tahlil DIALEKT-NEYTRAL (SQLite dev + Postgres prod). Provisioning/readiness — Postgres.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.enums import CreditTxnType, PurchaseStatus, ShiftStatus
from app.models.org import Branch, Company, Terminal
from app.models.purchasing import Purchase, SupplierLedger, SupplierPayment
from app.models.sales import Sale, SalePayment, Return
from app.models.shifts import CashMovement, Shift
from app.services.cash import till_identity as _ti


def _cash_at_creation_filter():
    """NAQD (create'da kassadan chiqqan) xarid = status=received VA SupplierLedger charge YO'Q.
    `received` O'ZI naqd belgisi EMAS: pay_supplier to'liq to'langan `debt` xaridni `received`ga
    o'giradi (usuldan qat'i nazar). Runtime `not _charged` gate'i (on_cash_purchase) bilan izchil —
    charge'li (debt) xarid PURCHASE_OUT olmaydi (uning naqdи SUPPLIER_OUT orqali)."""
    charge_exists = (
        select(SupplierLedger.id)
        .where(SupplierLedger.ref_id == Purchase.id,
               SupplierLedger.ref_type.in_(("purchase", "receiving")),
               SupplierLedger.type == CreditTxnType.charge)
        .exists()
    )
    return (Purchase.status == PurchaseStatus.received) & (~charge_exists)

_D0 = Decimal("0")


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _companies(db: Session, company_id: uuid.UUID | None):
    """Ishlov beriladigan kompaniyalar — company_id berilса FAQAT o'sha (per-tenant run), aks holда
    hammasi. Per-tenant scoping test izolyatsiyasi VA operatorning tenant-ba-tenant ishga tushirishi uchun."""
    q = db.query(Company).filter(Company.deleted_at.is_(None))
    if company_id is not None:
        q = q.filter(Company.id == company_id)
    return q.all()


def _branch_ids(db: Session, company_id: uuid.UUID | None) -> list:
    q = db.query(Branch.id).filter(Branch.deleted_at.is_(None))
    if company_id is not None:
        q = q.filter(Branch.company_id == company_id)
    return [r[0] for r in q.all()]


# ── §13 GO/NO-GO tasnifi ─────────────────────────────────────────────────────
BLOCK = "BLOCK"       # migratsiyani (yoki shu filialни) TO'XTATADI
REVIEW = "REVIEW"     # operator ko'rib chiqadi, lekin bloklamaydi (reconstruction shu yerда)
INFO = "INFO"         # ma'lumot


@dataclass
class Finding:
    code: str
    severity: str          # BLOCK | REVIEW | INFO
    scope: str             # "company:<id>" | "branch:<id>" | "shift:<id>" | "global"
    detail: str
    ref: str | None = None  # legacy manba (table:id) — taxmin emas, haqiqiy qator

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "scope": self.scope,
                "detail": self.detail, "ref": self.ref}


# ═══ §02 INVENTORY ═══════════════════════════════════════════════════════════
def inventory(db: Session, company_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Tenant/filial bo'yicha HAQIQIY inventarizatsiya (mavjud ma'lumotdan; taxmin yo'q).
    Prod raqamlari uchun operator shu funksiyani PROD ulanishда ishlatади (fabrikatsiya emas).
    company_id berilса FAQAT o'sha tenant (per-tenant run)."""
    out: dict[str, Any] = {"companies": [], "totals": {}}
    companies = _companies(db, company_id)
    tot = dict(branches=0, active_branches=0, terminals=0, cashiers=0, shifts=0, open_shifts=0,
               cash_movements=0, sales=0, cash_sale_payments=0, purchases=0, cash_purchases=0,
               supplier_payments=0, customer_payments=0, returns=0)
    for co in companies:
        brs = db.query(Branch).filter(Branch.company_id == co.id, Branch.deleted_at.is_(None)).all()
        br_ids = [b.id for b in brs]
        active = [b for b in brs if b.is_active]
        cashiers = db.query(func.count(func.distinct(Shift.cashier_id))).filter(
            Shift.branch_id.in_(br_ids)).scalar() if br_ids else 0
        shifts = db.query(func.count(Shift.id)).filter(Shift.branch_id.in_(br_ids)).scalar() if br_ids else 0
        open_sh = db.query(func.count(Shift.id)).filter(
            Shift.branch_id.in_(br_ids), Shift.status == ShiftStatus.open,
            Shift.deleted_at.is_(None)).scalar() if br_ids else 0
        terminals = db.query(func.count(Terminal.id)).filter(
            Terminal.branch_id.in_(br_ids)).scalar() if br_ids else 0
        mv = db.query(func.count(CashMovement.id)).join(Shift, Shift.id == CashMovement.shift_id).filter(
            Shift.branch_id.in_(br_ids)).scalar() if br_ids else 0
        sales = db.query(func.count(Sale.id)).filter(Sale.company_id == co.id).scalar()
        cash_pay = db.query(func.count(SalePayment.id)).join(Sale, Sale.id == SalePayment.sale_id).filter(
            Sale.company_id == co.id, SalePayment.method_code == "cash").scalar()
        purchases = db.query(func.count(Purchase.id)).filter(Purchase.company_id == co.id).scalar()
        cash_pur = db.query(func.count(Purchase.id)).filter(
            Purchase.company_id == co.id, Purchase.status == PurchaseStatus.received).scalar()
        sup_pay = db.query(func.count(SupplierPayment.id)).filter(
            SupplierPayment.method == "cash").scalar() if brs else 0
        from app.models.customers import Customer, CustomerPayment
        cust_pay = db.query(func.count(CustomerPayment.id)).join(
            Customer, Customer.id == CustomerPayment.customer_id).filter(
            Customer.company_id == co.id).scalar()
        returns = db.query(func.count(Return.id)).filter(Return.company_id == co.id).scalar()
        rec = {
            "company_id": str(co.id), "code": co.code, "name": co.name, "currency": co.currency,
            "branches": len(brs), "active_branches": len(active), "terminals": int(terminals or 0),
            "cashiers": int(cashiers or 0), "shifts": int(shifts or 0), "open_shifts": int(open_sh or 0),
            "cash_movements": int(mv or 0), "sales": int(sales or 0),
            "cash_sale_payments": int(cash_pay or 0), "purchases": int(purchases or 0),
            "cash_purchases": int(cash_pur or 0), "supplier_payments": int(sup_pay or 0),
            "customer_payments": int(cust_pay or 0), "returns": int(returns or 0),
            "branch_ids": [str(b) for b in br_ids],
        }
        out["companies"].append(rec)
        for k in tot:
            tot[k] += rec.get(k, 0)
    out["totals"] = tot
    out["company_count"] = len(companies)
    return out


# ═══ §03 CASHACCOUNT (TILL/SAFE) MAPPING ═════════════════════════════════════
@dataclass
class TillMapping:
    """Provisionlanadigan BITTA hisob (fizik TILL yoki branch SAFE) — REAL fizik-drawer modeli.
    TILL identity = tenant + branch + FIZIK CHECKOUT (checkout_code/terminal), branch-only EMAS."""
    company_id: uuid.UUID
    branch_id: uuid.UUID
    branch_code: str
    currency: str
    proposed_type: str = "TILL"                 # TILL | SAFE
    checkout_code: str | None = None            # (tenant, branch) doirasida BARQAROR fizik identity
    terminal_id: uuid.UUID | None = None        # ixtiyoriy legacy binding (TILL)
    label: str = ""                             # cash_accounts.label (till_identity orqali quriladi)
    label_human: str = ""                       # inson o'qiydigan nom (Kassa 1 / terminal nomi)
    confidence: str = "HIGH"                    # HIGH | AMBIGUOUS
    source: str = "TERMINAL"                     # OPERATOR_MAPPING | TERMINAL | BRANCH_DEFAULT | AMBIGUOUS
    reason: str = ""

    def as_dict(self) -> dict:
        return {"company_id": str(self.company_id), "branch_id": str(self.branch_id),
                "branch_code": self.branch_code, "currency": self.currency,
                "proposed_type": self.proposed_type, "checkout_code": self.checkout_code,
                "terminal_id": (str(self.terminal_id) if self.terminal_id else None),
                "label": self.label, "label_human": self.label_human,
                "confidence": self.confidence, "source": self.source, "reason": self.reason}


def _safe_mapping(company_id, br, cur: str) -> TillMapping:
    return TillMapping(company_id=company_id, branch_id=br.id, branch_code=br.code, currency=cur,
                       proposed_type="SAFE", checkout_code="SAFE", label=_ti.safe_label(),
                       label_human="Branch SAFE", confidence="HIGH", source="BRANCH_DEFAULT",
                       reason="branch-level umumiy seyf (odatda 1/branch; shiftless).")


def propose_till_mapping(db: Session, company_id: uuid.UUID | None = None, *,
                         mapping: "_ti.OperatorMapping | None" = None) -> tuple[list[TillMapping], list[Finding]]:
    """Legacy fizik drawer -> cash.cash_accounts (TILL/SAFE) mapping TAKLIFI (yozmaydi).

    REAL model: BIR FILIAL != BIR TILL. Har fizik checkout/kassa = alohida TILL. Fizik checkout aniqlash
    ustuvorligi (till_identity.detect_physical_checkouts): OPERATOR_MAPPING > TERMINAL > AMBIGUOUS.
    "Ko'p kassir = ko'p TILL" HECH QACHON taxmin qilinmaydi. Terminal dalili yoki explicit operator
    mapping bo'lmasa -> AMBIGUOUS (BLOCK). Har branch (odatda) 1 SAFE. Ratifikatsiya qilinган runtime
    sxema O'ZGARTIRILMAYDI — fizik identity `label`da (till_identity konvensiyasi)."""
    mappings: list[TillMapping] = []
    findings: list[Finding] = []
    for co in _companies(db, company_id):
        cur = (co.currency or "").strip().upper()
        for br in db.query(Branch).filter(
                Branch.company_id == co.id, Branch.deleted_at.is_(None)).all():
            if not cur or len(cur) != 3:
                # Valyuta noaniq/bo'sh -> TILL/SAFE valyutasi taxmin qilinmaydi -> provisionlanmaydi.
                reason = (f"kompaniya {co.code} valyutasi noaniq/bo'sh ({co.currency!r}) — TILL/SAFE "
                          f"valyutasi taxmin qilinmaydi; operator tasdiqlaydi.")
                findings.append(Finding("TILL_CURRENCY_UNKNOWN", BLOCK, f"branch:{br.id}", reason,
                                        ref=f"companies:{co.id}"))
                mappings.append(TillMapping(company_id=co.id, branch_id=br.id, branch_code=br.code,
                                            currency="", proposed_type="TILL", confidence="AMBIGUOUS",
                                            source="AMBIGUOUS", reason=reason))
                continue
            checkouts, source, _conf, detail = _ti.detect_physical_checkouts(db, co.id, br, mapping=mapping)
            if source in (_ti.SRC_OPERATOR, _ti.SRC_EXISTING, _ti.SRC_TERMINAL):
                for ck in checkouts:
                    mappings.append(TillMapping(
                        company_id=co.id, branch_id=br.id, branch_code=br.code, currency=cur,
                        proposed_type="TILL", checkout_code=ck.checkout_code, terminal_id=ck.terminal_id,
                        label=_ti.till_label(ck.checkout_code, ck.terminal_id), label_human=ck.label_human,
                        confidence="HIGH", source=source,
                        reason=f"{source}: fizik checkout '{ck.label_human}' -> alohida TILL."))
                bm = mapping.for_branch(br.id) if mapping is not None else None
                if bm is None or bm.safe:
                    sm = _safe_mapping(co.id, br, cur)
                    # §2: SAFE'ni operator ATAYLAB so'radimi, yoki u AVTOMATIK qo'shilyaptimi?
                    # (bm is None = branch mapping'da umuman yo'q -> AVTOMATIK). Xulq o'zgarmaydi;
                    # provision dry-run buni BALAND ko'rsatadi, operator ko'r-ko'rona SAFE olmaydi.
                    sm.source = ("OPERATOR_MAPPING" if (bm is not None and bm.safe_explicit)
                                 else "AUTO_SAFE_NOT_REQUESTED")
                    mappings.append(sm)
            elif source == _ti.SRC_AMBIGUOUS:
                # DYNAMIC TILL LIFECYCLE: TILL soni FIXED EMAS (branch 0..N TILL, keyinchalik qo'shiladi).
                # Fizik checkout sonini MIGRATION vaqtida bilmaslik architecture invariant EMAS -> GLOBAL
                # BLOCK EMAS. Bu branch'да hozircha provisionланган TILL yo'q -> REVIEW (runtime: operator
                # T0'дан oldin kamida bitta ACTIVE TILL yaratsin). "Ko'p kassir = ko'p TILL" HECH QACHON
                # taxmin qilinmaydi; provision uni o'tkazиб yuboradi (soxta TILL emas).
                reason = (detail + " — hozircha bu branch'да provisionланган TILL yo'q. TILL lifecycle "
                          "DINAMIK: admin kerak bo'lганда kassa qo'shadi. Migration BLOKLANMAYDI; T0'dan "
                          "keyin bu branch'да naqd smena ochilса, kamida bitta ACTIVE TILL kerak.")
                findings.append(Finding("CURRENT_BRANCH_NO_ACTIVE_TILL", REVIEW, f"branch:{br.id}",
                                        reason, ref=f"branches:{br.id}"))
                mappings.append(TillMapping(company_id=co.id, branch_id=br.id, branch_code=br.code,
                                            currency=cur, proposed_type="TILL", confidence="AMBIGUOUS",
                                            source="AMBIGUOUS", reason=reason))
            else:  # NO_ACTIVITY — cash tarixi yo'q -> migration blocker EMAS (backfill legasi yo'q).
                findings.append(Finding("BRANCH_NO_ACTIVITY", INFO, f"branch:{br.id}", detail,
                                        ref=f"branches:{br.id}"))
    findings.append(Finding("SAFE_MODEL", INFO, "global",
                            "SAFE = branch-level umumiy seyf (odatda 1/branch), shiftless. Legacy'да "
                            "SAFE tarixi yo'q -> historical SAFE backfill yo'q (SAFE provisioning-only)."))
    return mappings, findings


# ═══ §04 OCHIQ SMENALAR MAPPING ══════════════════════════════════════════════
def map_open_shifts(db: Session, mappings: list[TillMapping] | None = None,
                    company_id: uuid.UUID | None = None, *,
                    mapping: "_ti.OperatorMapping | None" = None) -> tuple[list[dict], list[Finding]]:
    """Har OCHIQ legacy smenani FIZIK TILL'ga resolve qiladi (terminal_id / single-checkout orqali).

    !!! FAQAT RUNTIME-READINESS HISOBOTI — TARIXIY ATRIBUTSIYA UCHUN ISHLATILMAYDI !!!
    Bu yerdagi "single-checkout" (branch'da bugun bitta ACTIVE TILL) JORIY holat haqida; u
    O'TMISHDAGI qator qaysi drawer'da bo'lganini ISBOTLAMAYDI. Tarixiy resolution YAGONA joyda:
    `historical_till.resolve` (dalil ierarxiyasi). Qaytarilgan qatorlarni (open_rows) HECH QACHON
    ledger leg'iga account tanlash uchun ulamang — bu retroaktiv taxminni qayta ochadi.
    Kassir identity'дан permanent TILL YARATILMAYDI (kassir almashadi, drawer o'zgarmaydi). Faqat
    cashier bor / fizik drawer noma'lum -> BLOCK/REVIEW (soxta drawer yaratilmaydi)."""
    if mappings is None:
        mappings, _ = propose_till_mapping(db, company_id, mapping=mapping)
    # Branch -> uning NON-ambiguous TILL checkout'lari; + ambiguous branch to'plami.
    till_by_branch: dict = {}
    ambiguous_branches: set = set()
    for m in mappings:
        if m.proposed_type != "TILL":
            continue
        if m.confidence == "AMBIGUOUS":
            ambiguous_branches.add(m.branch_id)
        else:
            till_by_branch.setdefault(m.branch_id, []).append(m)
    rows: list[dict] = []
    findings: list[Finding] = []
    oq = db.query(Shift).filter(Shift.status == ShiftStatus.open, Shift.deleted_at.is_(None))
    if company_id is not None:
        oq = oq.filter(Shift.branch_id.in_(_branch_ids(db, company_id)))
    for sh in oq.all():
        br = db.get(Branch, sh.branch_id)
        co_id = br.company_id if br else None
        tills = till_by_branch.get(sh.branch_id, [])
        resolved = None
        if sh.branch_id in ambiguous_branches or not tills:
            how = "unresolved-no-physical-drawer"
        elif len(tills) == 1:
            resolved, how = tills[0], "single-checkout"     # yagona fizik drawer
        elif sh.terminal_id is not None:
            match = [t for t in tills if t.terminal_id == sh.terminal_id]
            resolved, how = (match[0], "terminal") if len(match) == 1 else (None, "terminal-no-match")
        else:
            how = "multi-checkout-no-terminal"               # ko'p drawer, smena terminal_id siz
        blocked = resolved is None
        rows.append({
            "legacy_shift_id": str(sh.id), "company_id": str(co_id) if co_id else None,
            "branch_id": str(sh.branch_id), "cashier_id": str(sh.cashier_id),
            "terminal_id": str(sh.terminal_id) if sh.terminal_id else None,
            "resolved_checkout": (resolved.checkout_code if resolved else None),
            "resolution": how,
            "opened_at": sh.opened_at.isoformat() if sh.opened_at else None,
            "opening_cash": float(_D(sh.opening_cash)), "status": sh.status.value, "blocked": blocked,
        })
        if blocked:
            # DYNAMIC model: eski OCHIQ smena FIZIK TILL'siz -> GLOBAL migration blocker EMAS (REVIEW).
            # Bu CUTOVER-vaqti masalasi: T0'да bunday smena yangi authoritative runtime'ga O'TA OLMAYDI ->
            # operator uni T0'дан OLDIN yopadi yoki aniq TILL biriktiradi. Buni cutover_open_shift_gate
            # BLOKLAydi (discovery emas). Kassir identity'дан permanent TILL YARATILMAYDI.
            findings.append(Finding(
                "OPEN_SHIFT_WITHOUT_TILL", REVIEW, f"shift:{sh.id}",
                f"ochiq smena {sh.id} FIZIK TILL'ga resolve bo'lmadi ({how}) — T0 CUTOVER'да operator "
                f"uni yopsin yoki ACTIVE TILL biriktirsin (dinamik TILL; taxmin YO'Q).",
                ref=f"shifts:{sh.id}"))
    return rows, findings


# ═══ §09 CURRENCY AUDIT ══════════════════════════════════════════════════════
def currency_audit(db: Session, company_id: uuid.UUID | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for co in _companies(db, company_id):
        cur = (co.currency or "").strip().upper()
        if not cur or len(cur) != 3:
            findings.append(Finding("CURRENCY_INVALID", BLOCK, f"company:{co.id}",
                                    f"kompaniya {co.code} valyutasi noto'g'ri/bo'sh: {co.currency!r} — "
                                    f"TILL valyutasi aniqlanmaydi.", ref=f"companies:{co.id}"))
    # Legacy naqd summalarда valyuta ustuni YO'Q (bitta-valyutali model). Ko'p-valyuta anomaliyasi:
    # bir kompaniyада turli xil valyuta bo'lса aniqlанмайди (yagona companies.currency) — INFO.
    findings.append(Finding("CURRENCY_SINGLE_MODEL", INFO, "global",
                            "Legacy naqd summalар valyuta ustunисиз (kompaniya-yagona valyuta). "
                            "Ko'p-valyuta tarixi bo'lса CashAccount.currency ni operator tasdiqlaydi."))
    return findings


# ═══ §10 DATA-QUALITY AUDIT (tasnif — REMONT EMAS) ═══════════════════════════
def data_quality_audit(db: Session, company_id: uuid.UUID | None = None) -> list[Finding]:
    f: list[Finding] = []
    br_ids = _branch_ids(db, company_id) if company_id is not None else None

    def _sh(q):
        return q.filter(Shift.branch_id.in_(br_ids)) if br_ids is not None else q
    # Manfiy/imkonsiz naqd (FAQAT kerakli ustunlar — sxema-drift'ga chidamli)
    for sid, oc in _sh(db.query(Shift.id, Shift.opening_cash).filter(Shift.opening_cash < 0)).all():
        f.append(Finding("NEG_OPENING_CASH", BLOCK, f"shift:{sid}",
                         f"smena {sid} opening_cash manfiy: {oc}", ref=f"shifts:{sid}"))
    for sid, cc in _sh(db.query(Shift.id, Shift.counted_cash).filter(Shift.counted_cash < 0)).all():
        f.append(Finding("NEG_COUNTED_CASH", REVIEW, f"shift:{sid}",
                         f"smena {sid} counted_cash manfiy: {cc}", ref=f"shifts:{sid}"))
    # Orphan cash movement (shift yo'q) — LEFT JOIN yo'qlik.
    orphan_q = db.query(CashMovement.id, CashMovement.shift_id).outerjoin(
        Shift, Shift.id == CashMovement.shift_id).filter(Shift.id.is_(None))
    for mv_id, mv_shift in orphan_q.all():
        f.append(Finding("ORPHAN_CASH_MOVEMENT", BLOCK, "global",
                         f"cash_movement {mv_id} yaroqsiz shift_id: {mv_shift}",
                         ref=f"cash_movements:{mv_id}"))
    # Cashier/branch yo'q smena
    for (sid,) in db.query(Shift.id).filter(Shift.branch_id.is_(None)).all():
        f.append(Finding("SHIFT_NO_BRANCH", BLOCK, f"shift:{sid}",
                         f"smena {sid} branch_id yo'q", ref=f"shifts:{sid}"))
    # Yopilган smena counted_cash siz (SAFE/expected tekshiruvsiz) — REVIEW
    closed_uncounted = _sh(db.query(func.count(Shift.id)).filter(
        Shift.status == ShiftStatus.closed, Shift.counted_cash.is_(None))).scalar() or 0
    if closed_uncounted:
        f.append(Finding("CLOSED_SHIFT_UNCOUNTED", REVIEW, "global",
                         f"{closed_uncounted} ta yopilган smena counted_cash siz — expected tekshiruvi yo'q."))
    # Noma'lum filialли sotuv (company bor, branch link yo'q — sotuvда branch_id bormi?)
    return f


# ═══ §11 RECONSTRUCTION CANDIDATES (provenance=RECONSTRUCTION) ════════════════
def reconstruction_candidates(db: Session, company_id: uuid.UUID | None = None) -> tuple[list[dict], list[Finding]]:
    """Backfill'да RECONSTRUCTION talab qiladigan tarixiy yozuvlar. QIYMAT O'YLAB TOPMAYDI —
    manba qatorдан oladi. Asosiy sinf: tarixiy NAQD (received) xaridlar — kassadan naqd chiqған,
    lekin ledger OUT yo'q edi (§07 teshigi). Ular backfill'да OUT·PURCHASE_OUT (RECONSTRUCTION)."""
    cands: list[dict] = []
    findings: list[Finding] = []
    br_ids = _branch_ids(db, company_id) if company_id is not None else None
    # Tarixiy NAQD xaridlar (create'da kassadan chiqqan) — SupplierLedger charge YO'Q (debt emas).
    # `received` o'zi yetarli emas: pay_supplier to'langan debt'ni received qiladi -> phantom OUT +
    # SUPPLIER_OUT bilan ikki hisob bo'lardi. _cash_at_creation_filter() runtime `not _charged` bilan izchil.
    pq = db.query(Purchase.id, Purchase.total).filter(_cash_at_creation_filter())
    if company_id is not None:
        pq = pq.filter(Purchase.company_id == company_id)
    n_cash_pur = 0
    for pid, ptotal in pq.all():
        cands.append({
            "source": f"purchases:{pid}", "reason": "historical cash purchase (no ledger OUT)",
            "confidence": "HIGH", "classification": "RECONSTRUCTION",
            "expected_entry": {"direction": "OUT", "category": "PURCHASE_OUT",
                               "source_type": "PURCHASE", "source_id": str(pid),
                               "amount": float(_D(ptotal))},
        })
        n_cash_pur += 1
    if n_cash_pur:
        findings.append(Finding("RECON_CASH_PURCHASES", REVIEW, "global",
                                f"{n_cash_pur} ta tarixiy naqd xarid RECONSTRUCTION (OUT·PURCHASE_OUT)."))
    # Ochiq smenalar opening float — reconstruct qilinадi (ledger'да OPENING yo'q edi)
    osq = db.query(func.count(Shift.id)).filter(
        Shift.status == ShiftStatus.open, Shift.deleted_at.is_(None), Shift.opening_cash > 0)
    if br_ids is not None:
        osq = osq.filter(Shift.branch_id.in_(br_ids))
    n_open = osq.scalar() or 0
    if n_open:
        findings.append(Finding("RECON_OPEN_FLOATS", REVIEW, "global",
                                f"{n_open} ta ochiq smena opening float RECONSTRUCTION (IN·OPENING) — "
                                f"T0'да reconstruct qilinadi."))
    return cands, findings


# ═══ §12 BACKFILL DRY-RUN (FAQAT HISOBOT — YOZUV YO'Q) ════════════════════════
def dry_run(db: Session, company_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Backfill NIMA yozishini HISOBLAYDI — lekin HECH NARSA yozmaydi (§12). Kutilган ledger
    qatorlari/IN/OUT/reconstruction/ambiguous/invalid/duplicate + per-account/per-shift/branch/company
    yakunlari. Ledger'ga yozmaslik `test_dry_run_writes_no_ledger` bilan isbotlangan."""
    t0 = time.monotonic()
    from app.models.customers import Customer, CustomerPayment
    from app.models.purchasing import Supplier
    inv = inventory(db, company_id)
    mappings, map_find = propose_till_mapping(db, company_id)
    open_rows, open_find = map_open_shifts(db, mappings, company_id)
    cur_find = currency_audit(db, company_id)
    dq_find = data_quality_audit(db, company_id)
    recon, recon_find = reconstruction_candidates(db, company_id)
    br_ids = _branch_ids(db, company_id) if company_id is not None else None

    def _co(q, col):  # company filter (col = company_id ustunли jadval)
        return q.filter(col == company_id) if company_id is not None else q

    # Kutilган ledger proyeksiyasi (legacy'дан; yozuv YO'Q)
    proj = {"IN": {}, "OUT": {}, "counts": {}}

    def _add(direction, category, amount, n=1):
        proj[direction][category] = float(_D(proj[direction].get(category, 0)) + _D(amount))
        proj["counts"][f"{direction}.{category}"] = proj["counts"].get(f"{direction}.{category}", 0) + n

    # IN·OPENING (har opening_cash>0 smena)
    opq = db.query(func.coalesce(func.sum(Shift.opening_cash), 0), func.count(Shift.id)).filter(
        Shift.opening_cash > 0)
    if br_ids is not None:
        opq = opq.filter(Shift.branch_id.in_(br_ids))
    op_sum, op_n = opq.one()
    if op_n:
        _add("IN", "OPENING", op_sum, int(op_n))
    # IN·SALE (naqd sale_payment)
    cash_sales = _co(db.query(func.coalesce(func.sum(SalePayment.amount), 0), func.count(SalePayment.id))
                     .join(Sale, Sale.id == SalePayment.sale_id).filter(SalePayment.method_code == "cash"),
                     Sale.company_id).one()
    if cash_sales[1]:
        _add("IN", "SALE", cash_sales[0], int(cash_sales[1]))
    # OUT·REFUND (naqd qaytarish)
    cash_ref = _co(db.query(func.coalesce(func.sum(Return.total), 0), func.count(Return.id)).filter(
        Return.refund_method == "cash"), Return.company_id).one()
    if cash_ref[1]:
        _add("OUT", "REFUND", cash_ref[0], int(cash_ref[1]))
    # OUT·PURCHASE_OUT (NAQD create'da chiqqan xarid — charge YO'Q; RECONSTRUCTION). `received` o'zi
    # emas — debt->received flip phantom OUT + SUPPLIER_OUT ikki hisob berardi (§13 topilma).
    cash_pur = _co(db.query(func.coalesce(func.sum(Purchase.total), 0), func.count(Purchase.id)).filter(
        _cash_at_creation_filter()), Purchase.company_id).one()
    if cash_pur[1]:
        _add("OUT", "PURCHASE_OUT", cash_pur[0], int(cash_pur[1]))
    # OUT·SUPPLIER_OUT (naqd ta'minotchi to'lovi)
    sup = _co(db.query(func.coalesce(func.sum(SupplierPayment.amount), 0), func.count(SupplierPayment.id))
              .join(Supplier, Supplier.id == SupplierPayment.supplier_id).filter(
                  SupplierPayment.method == "cash"), Supplier.company_id).one()
    if sup[1]:
        _add("OUT", "SUPPLIER_OUT", sup[0], int(sup[1]))
    # IN·DEBT_IN (naqd mijoz qarz to'lovi)
    cust = _co(db.query(func.coalesce(func.sum(CustomerPayment.amount), 0), func.count(CustomerPayment.id))
               .join(Customer, Customer.id == CustomerPayment.customer_id).filter(
                   CustomerPayment.method == "cash"), Customer.company_id).one()
    if cust[1]:
        _add("IN", "DEBT_IN", cust[0], int(cust[1]))
    # CashMovement — DIQQAT (§13 topilma): naqd refund/ta'minotchi to'lov/qarz to'lovi HAR BIRI o'z
    # manba qatoriга QO'SHIMCHA `payout`/`payin` CashMovement (soya) yozadi. Runtime `_CASHOP_MAP`
    # `payout`ни UMUMAN post qilmaydi, `payin`ни esa FAQAT manual cashops endpoint'idан (soya
    # payin'lar debt-payment orqali, cashops'siz -> post qilinmaydi). Shu bois:
    #   - expense -> EXPENSE, collection -> CASH_OUT  (NOYOB manual — soya yo'q)
    #   - payin / payout -> AMBIGUOUS: soya (DEBT_IN/REFUND/SUPPLIER_OUT bilan ikki hisob) yoki manual.
    #     Aggregat so'rovда ajratib bo'lmaydi -> HEADLINE'ga QO'SHILMAYDI, alohida hisobot + REVIEW.
    #     Phase-1 backfill row-darajасида (client_uuid/reason) manba-trace qilib ajratadi.
    mvq = db.query(CashMovement.type, func.coalesce(func.sum(CashMovement.amount), 0),
                   func.count(CashMovement.id))
    if br_ids is not None:
        mvq = mvq.join(Shift, Shift.id == CashMovement.shift_id).filter(Shift.branch_id.in_(br_ids))
    mv_rows = mvq.group_by(CashMovement.type).all()
    ambiguous_mv = {"payin": {"sum": 0.0, "count": 0}, "payout": {"sum": 0.0, "count": 0}}
    for mtype, amt, n in mv_rows:
        mt = mtype.value if hasattr(mtype, "value") else str(mtype)
        if mt == "expense":
            _add("OUT", "EXPENSE", amt, int(n))
        elif mt == "collection":
            _add("OUT", "CASH_OUT", amt, int(n))
        elif mt in ("payin", "payout"):
            ambiguous_mv[mt] = {"sum": float(_D(amt)), "count": int(n)}

    total_in = sum((_D(v) for v in proj["IN"].values()), _D0)
    total_out = sum((_D(v) for v in proj["OUT"].values()), _D0)
    expected_rows = sum(proj["counts"].values())

    amv_find = []
    if ambiguous_mv["payin"]["count"] or ambiguous_mv["payout"]["count"]:
        amv_find.append(Finding(
            "AMBIGUOUS_CASH_MOVEMENTS", REVIEW, "global",
            f"payin={ambiguous_mv['payin']['count']} (sum {ambiguous_mv['payin']['sum']:g}), "
            f"payout={ambiguous_mv['payout']['count']} (sum {ambiguous_mv['payout']['sum']:g}) — "
            f"soya (DEBT_IN/REFUND/SUPPLIER_OUT) yoki manual cashops. HEADLINE'ga QO'SHILMADI (ikki "
            f"hisob bo'lmasin); Phase-1 backfill manba-trace bilan ajratadi."))

    findings = [f.as_dict() for f in (map_find + open_find + cur_find + dq_find + recon_find + amv_find)]
    blocking = [f for f in findings if f["severity"] == BLOCK]
    review = [f for f in findings if f["severity"] == REVIEW]
    report = {
        "kind": "PHASE0_DRY_RUN", "wrote_ledger": False,
        "dialect": db.get_bind().dialect.name,
        "inventory": inv,
        "till_mappings": [m.as_dict() for m in mappings],
        "ambiguous_mappings": [m.as_dict() for m in mappings if m.confidence == "AMBIGUOUS"],
        "open_shift_mappings": open_rows,
        "open_shift_blocked": [r for r in open_rows if r["blocked"]],
        "reconstruction_candidates": recon,
        "projection": proj,
        "ambiguous_movements": ambiguous_mv,   # payin/payout — headline'дан tashqarida (§13)
        "expected_ledger_rows": expected_rows,
        "expected_in_total": float(total_in),
        "expected_out_total": float(total_out),
        "expected_net": float(total_in - total_out),
        "reconstruction_count": len(recon),
        "invalid_rows": [f for f in findings if f["code"] in
                         ("ORPHAN_CASH_MOVEMENT", "SHIFT_NO_BRANCH", "NEG_OPENING_CASH")],
        "findings": findings,
        "blocking": blocking,
        "review": review,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }
    report["metrics"] = observability_metrics(report)
    report["go_no_go"] = evaluate_go_no_go(report)
    return report


# ═══ §13 GO / NO-GO ══════════════════════════════════════════════════════════
def evaluate_go_no_go(report: dict) -> dict:
    """BLOCK topilma bo'lса NO-GO. REVIEW (reconstruction dahil) bloklamaydi — operator ko'radi.
    Reconstruction TASDIQLANGAN mexanizm: nol reconstruction TALAB QILINMAYDI."""
    blocking = report.get("blocking", [])
    decision = "NO-GO" if blocking else "GO"
    return {
        "decision": decision,
        "blocking_count": len(blocking),
        "review_count": len(report.get("review", [])),
        "blocking_codes": sorted({b["code"] for b in blocking}),
        "note": ("Barcha BLOCK sabablari tozalangач GO. Reconstruction/REVIEW bloklamaydi."
                 if blocking else "Blocklovchi anomaliya yo'q. REVIEW bandlarини operator ko'radi."),
    }


# ═══ §18 OBSERVABILITY ═══════════════════════════════════════════════════════
def observability_metrics(report: dict) -> dict:
    maps = report.get("till_mappings", [])
    return {
        "mapped_accounts": sum(1 for m in maps if m["confidence"] in ("HIGH", "MEDIUM")),
        "unmapped_accounts": sum(1 for m in maps if m["confidence"] == "AMBIGUOUS"),
        "ambiguous_mappings": len(report.get("ambiguous_mappings", [])),
        "open_shift_mapping_failures": len(report.get("open_shift_blocked", [])),
        "reconstruction_candidates": report.get("reconstruction_count", 0),
        "blocking_anomalies": len(report.get("blocking", [])),
        "dry_run_duration_ms": report.get("duration_ms", 0),
        "dry_run_failures": 0,
    }


def ensure_provisioning_unique_index(db: Session) -> str:
    """§13 topilma (robustlik): read-then-write idempotentlik KONKURRENT/retry provisioning'да bir xil
    fizik checkout uchun ikki ACTIVE TILL berishi mumkin (cash_accounts UNIQUE'lari id'ni o'z ichiga
    oladi -> biznes-dublikatni ushlamaydi).

    REAL fizik model (revision): bir branch KO'P TILL'ga ega bo'la oladi -> uniqueness (tenant, branch,
    type) EMAS, balki FIZIK IDENTITY bo'yicha: (tenant, branch, type, label). label fizik checkout
    identity'ни (till_identity konvensiyasi: "TILL code=... terminal=...") va SAFE identity'ни
    ("SAFE code=SAFE") tashiydi -> bir xil LABELLI checkout/SAFE dublikat (mas. konkurrent provision race)
    bloklanadi, LEKIN turli fizik checkout'lar (turli label) birga yashaydi. Postgres NULL'ni NOYOB deb
    biladi -> label-siz (legacy/test) hisoblар CHEKLANMAYDI (provision DOIM label qo'yadi, shu bois bu
    guard provisionланган hisoblarни himoya qiladi). Ratifikatsiya qilинган JADVAL ta'rifi O'ZGARМАЙДИ —
    QO'SHIMCHA partial-unique indeks (provision --apply avto-yaratadi). Faqat Postgres."""
    if db.get_bind().dialect.name != "postgresql":
        return "skipped-sqlite"
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_cash_accounts_active_identity "
                    "ON cash.cash_accounts (tenant_id, branch_id, type, label) "
                    "WHERE status = 'ACTIVE'"))
    return "ensured"


# ═══ §08 CASHACCOUNT PROVISIONING (idempotent; Phase 0 = REJA, yozuv yo'q) ═════
def provision_accounts(db: Session, mappings: list[TillMapping] | None = None, *,
                       apply: bool = False, mapping: "_ti.OperatorMapping | None" = None) -> dict:
    """Mapping'дан FIZIK TILL(lar) + branch SAFE CashAccount yaratadi — IDEMPOTENT (fizik identity
    bo'yicha dedup: checkout_code / terminal binding). apply=False -> FAQAT reja, yozuv yo'q. AMBIGUOUS
    branch o'tkazib yuboriladi (operator mapping/terminal hал qilгунча). Faqat Postgres (cash schema).
    Ledger'ga HECH NARSA yozmaydi (faqat cash_accounts)."""
    from app.models.cash import CashAccount
    if db.get_bind().dialect.name != "postgresql":
        return {"applied": False, "reason": "skipped-sqlite", "plan": []}
    if apply:
        # §review topilma: himoya partial-unique indeksини YOZUVDAN OLDIN kafolatlaymiz — read-then-write
        # idempotentlik KONKURRENT/retry apply'да bir xil fizik checkout uchun IKKI ACTIVE TILL bermasин
        # (aks holда resolve None -> dual-write o'chib qoladi). Idempotent DDL; runbook qadamiga tayanmaydi.
        ensure_provisioning_unique_index(db)
    if mappings is None:
        mappings, _ = propose_till_mapping(db, mapping=mapping)
    plan: list[dict] = []
    for m in mappings:
        base = {"branch_id": str(m.branch_id), "type": m.proposed_type,
                "checkout_code": m.checkout_code, "source": m.source}
        if m.confidence == "AMBIGUOUS":
            plan.append({**base, "action": "skip-ambiguous"})
            continue
        if m.proposed_type == "SAFE":
            existing = _ti.find_safe(db, m.company_id, m.branch_id)
        else:  # TILL — fizik identity bo'yicha (checkout_code, keyin terminal binding)
            existing = (_ti.find_till_by_checkout(db, m.company_id, m.branch_id, m.checkout_code)
                        or _ti.find_till_by_terminal(db, m.company_id, m.branch_id, m.terminal_id))
        if existing is not None:
            plan.append({**base, "action": "exists", "cash_account_id": str(existing.id)})
        else:
            plan.append({**base, "action": "create", "currency": m.currency, "label": m.label,
                         "terminal_id": (str(m.terminal_id) if m.terminal_id else None)})
            if apply:
                db.add(CashAccount(tenant_id=m.company_id, branch_id=m.branch_id, type=m.proposed_type,
                                   currency=m.currency, status="ACTIVE", label=m.label,
                                   created_at=datetime.now(timezone.utc)))
    if apply:
        db.flush()
    def _n(action, typ=None):
        return sum(1 for p in plan if p["action"] == action and (typ is None or p["type"] == typ))
    return {"applied": bool(apply), "plan": plan,
            "to_create": _n("create"),
            "existing": _n("exists"),
            "skipped_ambiguous": _n("skip-ambiguous"),
            "tills_created": _n("create", "TILL"),
            "safes_created": _n("create", "SAFE")}


# ═══ §07/§17 ENVIRONMENT READINESS ═══════════════════════════════════════════
def readiness_check(engine: Engine) -> dict:
    """Postgres muhitини tekshiradi: versiya, cash schema, rollar, imtiyozlar, search_path RESET
    regressiyasi. Faqat Postgres (SQLite -> skipped)."""
    if engine.dialect.name != "postgresql":
        return {"ok": None, "reason": "skipped-sqlite", "checks": {}}
    checks: dict[str, Any] = {}
    ok = True
    with engine.connect() as con:
        ver = con.execute(text("SHOW server_version_num")).scalar()
        checks["pg_version_num"] = int(ver)
        checks["pg_version_ok"] = int(ver) >= 130000   # gen_random_uuid() core (§07)
        ok &= checks["pg_version_ok"]
        checks["cash_schema"] = con.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'")).first() is not None
        ok &= checks["cash_schema"]
        roles = {r[0] for r in con.execute(text(
            "SELECT rolname FROM pg_roles WHERE rolname LIKE 'cash_%'")).all()}
        checks["roles"] = sorted(roles)
        checks["roles_ok"] = {"cash_posting", "cash_app", "cash_readonly", "cash_admin"} <= roles
        ok &= checks["roles_ok"]
        # Imtiyoz: cash_posting immutable ledger'ni UPDATE/DELETE QILA OLMASLIGI kerak (§17)
        has_upd = con.execute(text(
            "SELECT has_table_privilege('cash_posting','cash.cash_ledger_entries','UPDATE')")).scalar()
        has_del = con.execute(text(
            "SELECT has_table_privilege('cash_posting','cash.cash_ledger_entries','DELETE')")).scalar()
        checks["posting_cannot_mutate_ledger"] = (not has_upd) and (not has_del)
        ok &= checks["posting_cannot_mutate_ledger"]
        # search_path RESET regressiyasi (§07): deploy hovuzga cash,public oqizmasin
        checks["search_path"] = con.execute(text("SHOW search_path")).scalar()
        checks["search_path_not_cash_first"] = not str(checks["search_path"]).strip().startswith("cash")
        ok &= checks["search_path_not_cash_first"]
    checks["all_ok"] = bool(ok)
    return {"ok": bool(ok), "checks": checks}


# ═══ §05 PRODUCTION BACKUP VERIFICATION ══════════════════════════════════════
_BACKUP_REQUIRED = ("snapshot_ref", "taken_at", "operator", "checksum", "restore_rehearsed", "verified")


def verify_backup(manifest: dict | None) -> dict:
    """Migratsiya BOSHLANISHIDAN oldin majburiy backup manifestini tekshiradi (§05). Barcha majburiy
    maydon bo'lishi + verified=True + restore_rehearsed=True SHART — aks holда ROLLBACK NUQTASI YO'Q ->
    migratsiya boshlanмайди (BLOCK). Hech qanday backup OLMAYDI — faqat operator bergan manifestни tekshiradi."""
    missing = [k for k in _BACKUP_REQUIRED if not manifest or manifest.get(k) in (None, "", False)]
    ok = (not missing and manifest is not None
          and manifest.get("verified") is True and manifest.get("restore_rehearsed") is True)
    return {"ok": bool(ok), "missing": missing,
            "reason": ("verified rollback nuqtasi mavjud" if ok
                       else f"backup yetarli emas / tekshirilmagan: {missing or 'verified/restore_rehearsed=False'}")}
