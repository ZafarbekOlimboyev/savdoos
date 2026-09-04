# -*- coding: utf-8 -*-
"""Cash Ledger · Migration Phase 0 — Prepare & Production Readiness (toolkit).

MUHIM QOIDALAR (bu modul ularга RIOYA qiladi):
  * cash.cash_ledger_entries'ga HECH NARSA yozilmaydi — dry-run FAQAT hisobot.
  * Legacy biznes ma'lumoti Phase 0'да o'zgartirilmaydi/tuzatilmaydi (audit — tasnif, remont emas).
  * Tarixiy backfill / cutover BU YERDA emas (keyingi fazalar).
  * Mapping "taxmin qilmaydi": ishonchsiz till-identity -> AMBIGUOUS + operator-review istisnosi.

Legacy'да ALOHIDA fizik-till entity YO'Q — naqd smena bo'yicha kuzatiladi (Shift.opening_cash +
CashMovement), smena esa branch + (nullable) terminal + cashier'ga bog'langan. Runtime (Phase 2b)
FILIALGA BITTA TILL'ni resolve qiladi (retrofit.resolve_till(tenant, branch_id, "TILL")). Shu bois
kanonik mapping: HAR FAOL FILIAL = BITTA TILL. Bir filialда bir nechta terminal (mumkin bo'lган
alohida yashiklar) bo'lса -> AMBIGUOUS (umumiy yashik vs terminal-boshiga) -> operator hal qiladi.

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
    company_id: uuid.UUID
    branch_id: uuid.UUID
    branch_code: str
    currency: str
    proposed_type: str = "TILL"
    label: str = ""                 # fizik-identity ref (cash_accounts.label — runtime sxema o'zgармайди)
    confidence: str = "HIGH"        # HIGH | MEDIUM | AMBIGUOUS
    distinct_terminals: int = 0
    reason: str = ""

    def as_dict(self) -> dict:
        return {"company_id": str(self.company_id), "branch_id": str(self.branch_id),
                "branch_code": self.branch_code, "currency": self.currency,
                "proposed_type": self.proposed_type, "label": self.label,
                "confidence": self.confidence, "distinct_terminals": self.distinct_terminals,
                "reason": self.reason}


def propose_till_mapping(db: Session, company_id: uuid.UUID | None = None) -> tuple[list[TillMapping], list[Finding]]:
    """Legacy fizik naqd-joy -> cash.cash_accounts (TILL) mapping TAKLIFI (yozmaydi).

    Qoida: har faol filial = 1 TILL. Filialда shift'lar >1 alohida terminal ishlatса -> AMBIGUOUS
    (umumiy yashik vs terminal-boshiga alohida — legacy ayta olmaydi) -> operator-review istisnosi.
    Mapping ARTEFAKTI: qaytarilган ro'yxat (JSON'га yoziladi) + provisioning cash_accounts.branch_id +
    label (fizik ref). Ratifikatsiya qilинган runtime sxema O'ZGARTIRILMAYDI (yangi ustun/jadval yo'q)."""
    mappings: list[TillMapping] = []
    findings: list[Finding] = []
    for co in _companies(db, company_id):
        cur = (co.currency or "").strip().upper()
        for br in db.query(Branch).filter(
                Branch.company_id == co.id, Branch.deleted_at.is_(None)).all():
            # DIQQAT (§13): faqat TIRIK smena tarixi (deleted_at IS NULL) — soft-deleted smena
            # o'chirilган terminalни sanab HIGH filialни AMBIGUOUS qilib qo'ymasin.
            distinct_terms = db.query(func.count(func.distinct(Shift.terminal_id))).filter(
                Shift.branch_id == br.id, Shift.terminal_id.isnot(None),
                Shift.deleted_at.is_(None)).scalar() or 0
            m = TillMapping(company_id=co.id, branch_id=br.id, branch_code=br.code,
                            currency=cur, label=f"BRANCH:{br.code}")   # valyuta TAXMIN QILINMAYDI (UZS emas)
            if not cur or len(cur) != 3:
                # Valyuta noaniq/bo'sh -> TILL valyutasi taxmin qilinmaydi -> provisionlanmaydi (§13).
                m.confidence = "AMBIGUOUS"
                m.reason = (f"kompaniya {co.code} valyutasi noaniq/bo'sh ({co.currency!r}) — TILL "
                            f"valyutasi taxmin qilinmaydi; operator tasdiqlaydi.")
                findings.append(Finding("TILL_CURRENCY_UNKNOWN", BLOCK, f"branch:{br.id}", m.reason,
                                        ref=f"companies:{co.id}"))
            elif distinct_terms > 1:
                m.confidence = "AMBIGUOUS"
                m.distinct_terminals = int(distinct_terms)
                m.reason = (f"filial {br.code} {distinct_terms} ta terminal ishlatgan — umumiy yashik "
                            f"yoki terminal-boshiga alohida TILL? Legacy ayta olmaydi.")
                findings.append(Finding("TILL_AMBIGUOUS", BLOCK, f"branch:{br.id}", m.reason,
                                        ref=f"branches:{br.id}"))
            elif not br.is_active and db.query(func.count(Shift.id)).filter(
                    Shift.branch_id == br.id, Shift.deleted_at.is_(None)).scalar():
                m.confidence = "MEDIUM"
                m.reason = "faol emas filial, lekin smena tarixi bor — TILL kerak (arxiv)."
            else:
                m.confidence = "HIGH"
                m.reason = "bitta yashik (0/1 terminal) — filialга bitta TILL."
            mappings.append(m)
    # SAFE: legacy'да umuman yo'q — ixtiyoriy, operator so'rovi bilan (tarixiy SAFE ma'lumoti yo'q).
    findings.append(Finding("SAFE_NOT_IN_LEGACY", INFO, "global",
                            "Legacy'да SAFE (seyf) tushunchasi yo'q — SAFE ixtiyoriy, operator so'rovi "
                            "bilan filial/kompaniya darajасида yaratiladi; tarixiy SAFE backfill yo'q."))
    return mappings, findings


# ═══ §04 OCHIQ SMENALAR MAPPING ══════════════════════════════════════════════
def map_open_shifts(db: Session, mappings: list[TillMapping] | None = None,
                    company_id: uuid.UUID | None = None) -> tuple[list[dict], list[Finding]]:
    """Barcha OCHIQ legacy smenalarni proposed TILL'ga bog'laydi. Filial TILL mapping'i AMBIGUOUS
    bo'lса — o'sha filialни BLOKLAYDI (aniq TILL'ga xavfsiz bog'lab bo'lmaydi; SOXTA smena yaratmaymiz)."""
    if mappings is None:
        mappings, _ = propose_till_mapping(db, company_id)
    # PROVISIONABLE = mapping'да bor VA ambiguous emas. Ambiguous / soft-deleted filial / mappingда
    # umuman yo'q filial -> BLOK (propose_till_mapping faqat deleted_at IS NULL filiallarни oladi, shu
    # bois soft-deleted filial provisionable'да bo'lmaydi -> phantom TILL taklif qilinmaydi — §13 topilma).
    provisionable = {m.branch_id for m in mappings if m.confidence != "AMBIGUOUS"}
    rows: list[dict] = []
    findings: list[Finding] = []
    oq = db.query(Shift).filter(Shift.status == ShiftStatus.open, Shift.deleted_at.is_(None))
    if company_id is not None:
        oq = oq.filter(Shift.branch_id.in_(_branch_ids(db, company_id)))
    open_shifts = oq.all()
    for sh in open_shifts:
        br = db.get(Branch, sh.branch_id)
        co_id = br.company_id if br else None
        blocked = sh.branch_id not in provisionable
        rows.append({
            "legacy_shift_id": str(sh.id), "company_id": str(co_id) if co_id else None,
            "branch_id": str(sh.branch_id), "cashier_id": str(sh.cashier_id),
            "terminal_id": str(sh.terminal_id) if sh.terminal_id else None,
            "inferred_till": f"BRANCH:{br.code}" if br else None,
            "proposed_cash_account": ("TILL@" + br.code) if (br and not blocked) else None,
            "opened_at": sh.opened_at.isoformat() if sh.opened_at else None,
            "opening_cash": float(_D(sh.opening_cash)), "status": sh.status.value, "blocked": blocked,
        })
        if blocked:
            findings.append(Finding(
                "OPEN_SHIFT_UNMAPPABLE", BLOCK, f"shift:{sh.id}",
                f"ochiq smena {sh.id} filiali TILL-identity aniq emas (ambiguous/branch yo'q) — "
                f"o'sha filial migratsiyasi bloklanadi; soxta smena yaratilmaydi.",
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
    """§13 topilma (robustlik): read-then-write idempotentlik KONKURRENT/retry provisioning'да ikki
    ACTIVE TILL berishi mumkin (cash_accounts UNIQUE'lari id'ni o'z ichiga oladi -> biznes-dublikatni
    ushlamaydi). DB-darajасидаги kafolat: har (tenant, branch, type) uchun BITTA ACTIVE hisob.
    Ratifikatsiya qilинган JADVAL ta'rifi O'ZGARМАЙДИ — bu QO'SHIMCHA partial-unique indeks, migration
    owner Phase-1 provisioning'дан OLDIN TOZA prod bazада bir marta yaratadi (runbook §14). Faqat Postgres."""
    if db.get_bind().dialect.name != "postgresql":
        return "skipped-sqlite"
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_cash_accounts_active_type "
                    "ON cash.cash_accounts (tenant_id, branch_id, type) WHERE status = 'ACTIVE'"))
    return "ensured"


# ═══ §08 CASHACCOUNT PROVISIONING (idempotent; Phase 0 = REJA, yozuv yo'q) ═════
def provision_accounts(db: Session, mappings: list[TillMapping] | None = None, *,
                       apply: bool = False, include_safe: bool = False) -> dict:
    """Mapping'дан TILL (+ ixtiyoriy SAFE) CashAccount yaratadi — IDEMPOTENT (mavjud bo'lса o'tkazadi,
    DUBLIKAT yaratmaydi). apply=False (Phase 0 STANDARTI) -> FAQAT reja, yozuv yo'q. AMBIGUOUS mapping
    o'tkazib yuboriladi (operator hal qilгунча). Faqat Postgres (cash schema)."""
    from app.services.cash import repositories as repo
    from app.models.cash import CashAccount
    if db.get_bind().dialect.name != "postgresql":
        return {"applied": False, "reason": "skipped-sqlite", "plan": []}
    if mappings is None:
        mappings, _ = propose_till_mapping(db)
    plan: list[dict] = []
    for m in mappings:
        if m.confidence == "AMBIGUOUS":
            plan.append({"branch_id": str(m.branch_id), "type": "TILL", "action": "skip-ambiguous"})
            continue
        existing = repo.find_account(db, m.company_id, m.branch_id, "TILL")
        if existing is not None:
            plan.append({"branch_id": str(m.branch_id), "type": "TILL", "action": "exists",
                         "cash_account_id": str(existing.id)})
        else:
            plan.append({"branch_id": str(m.branch_id), "type": "TILL", "action": "create",
                         "currency": m.currency, "label": m.label})
            if apply:
                acc = CashAccount(tenant_id=m.company_id, branch_id=m.branch_id, type="TILL",
                                  currency=m.currency, status="ACTIVE", label=m.label,
                                  created_at=datetime.now(timezone.utc))
                db.add(acc)
        if include_safe:
            ex_safe = repo.find_account(db, m.company_id, m.branch_id, "SAFE")
            if ex_safe is None:
                plan.append({"branch_id": str(m.branch_id), "type": "SAFE", "action": "create",
                             "currency": m.currency, "label": m.label + ":SAFE"})
                if apply:
                    db.add(CashAccount(tenant_id=m.company_id, branch_id=m.branch_id, type="SAFE",
                                       currency=m.currency, status="ACTIVE", label=m.label + ":SAFE",
                                       created_at=datetime.now(timezone.utc)))
            else:
                plan.append({"branch_id": str(m.branch_id), "type": "SAFE", "action": "exists",
                             "cash_account_id": str(ex_safe.id)})
    if apply:
        db.flush()
    return {"applied": bool(apply), "plan": plan,
            "to_create": sum(1 for p in plan if p["action"] == "create"),
            "existing": sum(1 for p in plan if p["action"] == "exists"),
            "skipped_ambiguous": sum(1 for p in plan if p["action"] == "skip-ambiguous")}


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
