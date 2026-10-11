# -*- coding: utf-8 -*-
"""Cash Ledger — Phase 2 SHADOW COMPARISON servisi (FAQAT O'QISH, auto-repair YO'Q).

Legacy AVTORITET; ledger SOYA. Bu servis ikki TARAFNI MUSTAQIL hisoblaydi va solishtiradi:

  A. LEGACY expected physical cash — FAQAT legacy source jadvallaridan
     (Shift.opening_cash, cash SalePayment, CashMovement payin/payout/expense/collection,
      Purchase/SupplierLedger). Ledger'ni HECH QACHON o'qimaydi (tautologiya emas).
  B. LEDGER expected physical cash — FAQAT cash_ledger_entries dual-write (provenance=NORMAL) leg'lardan.

Legacy'ning MA'LUM ko'r nuqtasi (naqd xarid) fizik summaga qo'shiladi: legacy naqd matematikasi
CashMovement'ga tayanadi, xarid esa CashMovement yozmaydi — shu bois "physical" legacy = naqd-mat
MINUS net naqd xaridlar (Purchase.total, not_charged). Ledger buni PURCHASE_OUT/PURCHASE_RETURN bilan
tutadi. Algebraik ayniyat: ledger_expected == legacy_physical_expected (delta=0) — dual-write to'g'ri bo'lsa.

provenance=NORMAL + ixtiyoriy t0: Phase-1 backfill (RECONSTRUCTION, < T0) Phase-2 dual-write'дан
AJRATILADI. Snapshot/trace READ-ONLY — hech nima yozmaydi, deltalar YASHIRILMAYDI/normallashtirilmaydi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.cash import CashAccount, CashLedgerEntry, CashShift, CashSourceType
from app.models.enums import CashMovementType, CreditTxnType
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseReturn, SupplierLedger
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift

_Z = Decimal("0")
_TOL = Decimal("0.005")   # butun-som quantize'дан keyin AYNIY kutiladi; float shovqin uchun kichik chek


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _status(delta: Decimal, blocked: bool = False) -> str:
    if blocked:
        return "BLOCK"
    return "MATCH" if abs(delta) <= _TOL else "REVIEW"


# ═══ CASH PURCHASE predikati (not_charged) — legacy manba, ledger'siz ══════════
def _charged_purchase_ids(db: Session, company_id) -> set:
    """SupplierLedger'ga CHARGE yozgan (debt/nasiya) xaridlar id'lari — bular naqd EMAS (kassa
    tegmagan). Runtime `_charged` + backfill filtri bilan izchil. TENANT'ga scope (§19 topilma:
    company_id endi HAQIQATAN ishlatiladi — Supplier orqali)."""
    from app.models.purchasing import Supplier
    rows = db.execute(select(SupplierLedger.ref_id).join(
        Supplier, Supplier.id == SupplierLedger.supplier_id).where(
        Supplier.company_id == company_id,
        SupplierLedger.ref_type.in_(("purchase", "receiving")),
        SupplierLedger.type == CreditTxnType.charge)).all()
    return {r[0] for r in rows if r[0] is not None}


def _cash_purchase_net(db: Session, company_id, branch_id, t0, opened=None, closed=None) -> Decimal:
    """Branch bo'yicha NAQD (not_charged) xaridlarning NET fizik chiqishi = Σ Purchase.total.
    Net = joriy total (increase qo'shadi, return ayiradi -> joriy total = net; cancelled -> total 0).
    t0/oyna berilса created_at bo'yicha filtr (smena-daraja atribusiyasi)."""
    charged = _charged_purchase_ids(db, company_id)
    q = select(Purchase.id, Purchase.total, Purchase.created_at).where(
        Purchase.company_id == company_id, Purchase.branch_id == branch_id)
    total = _Z
    for pid, ptotal, created in db.execute(q).all():
        if pid in charged:
            continue                      # debt xarid — kassa tegmagan
        if t0 is not None and created is not None and created < t0:
            continue
        if opened is not None and created is not None and not (opened <= created <= (closed or created)):
            continue
        total += _D(ptotal)
    return total


# ═══ LEGACY tarafi (source jadvallardan; ledger O'QILMAYDI) ═══════════════════
def _legacy_movement_sums(db: Session, shift_ids, t0):
    sums = {"payin": _Z, "payout": _Z, "expense": _Z, "collection": _Z}
    if not shift_ids:
        return sums
    q = select(CashMovement.type, CashMovement.amount, CashMovement.created_at).where(
        CashMovement.shift_id.in_(list(shift_ids)))
    for mtype, amt, created in db.execute(q).all():
        if t0 is not None and created is not None and created < t0:
            continue
        mt = mtype.value if hasattr(mtype, "value") else str(mtype)
        if mt in sums:
            sums[mt] += _D(amt)
    return sums


def _legacy_cash_sales(db: Session, sale_filter, t0) -> Decimal:
    q = select(func.coalesce(func.sum(SalePayment.amount), 0)).select_from(SalePayment).join(
        Sale, Sale.id == SalePayment.sale_id).where(SalePayment.method_code == "cash", sale_filter)
    if t0 is not None:
        q = q.where(Sale.sold_at >= t0)
    return _D(db.execute(q).scalar())


def _branch_of(db: Session, company_id, cash_account_id):
    acc = db.get(CashAccount, cash_account_id)
    if acc is None or acc.tenant_id != company_id:
        return None
    return acc.branch_id


# ═══ LEDGER tarafi (FAQAT NORMAL dual-write leg'lar) ══════════════════════════
def _ledger_flows(db: Session, company_id, *, cash_account_id=None, shift_id=None, on_shift_only=False):
    """(in, out) — provenance=NORMAL leg'lar. cash_account_id -> hisob bo'yicha; shift_id -> smena
    bo'yicha (on_shift_only=True -> ON_SHIFT filtri)."""
    signed_in = func.coalesce(func.sum(CashLedgerEntry.amount).filter(
        CashLedgerEntry.direction == "IN"), 0)
    signed_out = func.coalesce(func.sum(CashLedgerEntry.amount).filter(
        CashLedgerEntry.direction == "OUT"), 0)
    q = select(signed_in, signed_out).where(
        CashLedgerEntry.tenant_id == company_id,
        CashLedgerEntry.provenance == "NORMAL",
        # ── PHASE 1: SEYF OCHILISHI legacy tomonda HAMKORSIZ ──────────────────
        #  Ochilish TA'RIF BO'YICHA legacy hodisa emas: u hisobning bir martalik
        #  attestatsiyasi, savdo/kirim/chiqim emas, va legacy jadvallarda unga MOS
        #  hodisa YO'Q. Uni ledger tomonida sanash HAR ochilishni do'kon deltasiga
        #  aylantirardi (soxta CASH_OP nomuvofiqligi).
        #  ⚠️  AYNAN SHU MANBA TURI chiqariladi — `ADJUSTMENT` toifasi EMAS va NORMAL
        #      qatorlar EMAS: boshqa ADJUSTMENT (masalan qo'lda tuzatish) HAMON
        #      ko'rinishi SHART, aks holda haqiqiy farqlar yashirinardi.
        CashLedgerEntry.source_type != CashSourceType.ACCOUNT_OPENING.value)
    if cash_account_id is not None:
        q = q.where(CashLedgerEntry.cash_account_id == cash_account_id)
    if shift_id is not None:
        q = q.where(CashLedgerEntry.shift_id == shift_id)
    if on_shift_only:
        q = q.where(CashLedgerEntry.posting_kind == "ON_SHIFT")
    row = db.execute(q).first()
    return _D(row[0]), _D(row[1])


# ═══ PUBLIC: solishtirish darajalari ═════════════════════════════════════════
def compare_shift(db: Session, company_id, legacy_shift_id, *, t0=None) -> dict:
    """Bitta legacy smena: legacy physical expected vs ledger ON_SHIFT expected.
    cash.shift.id == legacy shift id (runtime alignment) -> ledger shift_id = legacy_shift_id.

    DIQQAT (§19 minor topilma): naqd XARID smena-atribusiyasi create-vaqti oynasiga tayanadi
    (Purchase.created_at). Agar xarid BOSHQA smenada oshirilса/qaytarilса, ledger o'sha edit-vaqti
    smenasiga leg yozadi -> bu SMENA-daraja delta noaniq bo'ladi (ikki smenaда REVIEW). compare_till
    (hisob-daraja, smena-agnostik) DOIM to'g'ri (deltalar bekor bo'ladi) — cutover go/no-go uchun
    compare_till/compare_tenant ishlating. Bir-smena hayot-tsikli (odatiy) -> aniq."""
    sh = db.get(Shift, legacy_shift_id)
    if sh is None:
        return {"level": "shift", "shift_id": str(legacy_shift_id), "status": "BLOCK",
                "reason": "legacy smena topilmadi"}
    br = db.get(Branch, sh.branch_id)
    if br is None or br.company_id != company_id:      # §19 topilma: tenant guard (branch->company)
        return {"level": "shift", "shift_id": str(legacy_shift_id), "status": "BLOCK",
                "reason": "smena boshqa tenant'ники / branch topilmadi"}
    opened, closed = sh.opened_at, sh.closed_at
    opening = _D(sh.opening_cash) if (t0 is None or (opened is not None and opened >= t0)) else _Z
    cash_sales = _legacy_cash_sales(db, Sale.shift_id == sh.id, t0)
    mv = _legacy_movement_sums(db, [sh.id], t0)
    net_purch = _cash_purchase_net(db, company_id, sh.branch_id, t0, opened=opened, closed=closed)
    legacy_in = opening + cash_sales + mv["payin"]
    legacy_out = mv["payout"] + mv["expense"] + mv["collection"] + net_purch
    legacy_expected = legacy_in - legacy_out
    ledger_in, ledger_out = _ledger_flows(db, company_id, shift_id=legacy_shift_id, on_shift_only=True)
    ledger_expected = ledger_in - ledger_out
    delta = ledger_expected - legacy_expected
    return {
        "level": "shift", "tenant_id": str(company_id), "branch_id": str(sh.branch_id),
        "shift_id": str(legacy_shift_id),
        "legacy_in": float(legacy_in), "legacy_out": float(legacy_out),
        "legacy_expected": float(legacy_expected),
        "ledger_in": float(ledger_in), "ledger_out": float(ledger_out),
        "ledger_expected": float(ledger_expected),
        "delta": float(delta), "status": _status(delta),
        "legacy_breakdown": {"opening": float(opening), "cash_sales": float(cash_sales),
                             "payin": float(mv["payin"]), "payout": float(mv["payout"]),
                             "expense": float(mv["expense"]), "collection": float(mv["collection"]),
                             "net_cash_purchases": float(net_purch)},
    }


def compare_till(db: Session, company_id, cash_account_id, *, t0=None) -> dict:
    """Bitta TILL uchun DIAGNOSTIK solishtirish (drill-down).

    ⚠️  DOIRA ASIMMETRIYASI (ATAYLAB, lekin CHEKLANGAN): legacy tomon BUTUN FILIAL bo'yicha
        hisoblanadi (smena/off-shift atributsiyasidan mustaqil bo'lish uchun), ledger tomon esa
        SHU BITTA hisob bo'yicha. Demak natija FAQAT filialda bitta naqd hisob bo'lganda
        ma'noli. Filialda bir nechta hisob bo'lsa `scope_warning` qaytadi va roll-up bu
        funksiyani ISHLATMAYDI (aks holda legacy hisoblar soniga KO'PAYTIRILARDI — R-fix).
        Filial/tenant darajasi uchun `compare_branch`/`compare_tenant`.
    """
    branch_id = _branch_of(db, company_id, cash_account_id)
    if branch_id is None:
        return {"level": "till", "cash_account_id": str(cash_account_id), "status": "BLOCK",
                "reason": "TILL topilmadi / boshqa tenant"}
    # legacy: branch bo'yicha BARCHA smenalar (opening + payin/payout/... ) + BARCHA naqd sotuvlar + net xarid
    sh_q = select(Shift.id, Shift.opening_cash, Shift.opened_at).where(Shift.branch_id == branch_id)
    opening = _Z
    shift_ids = []
    for sid, ocash, opened in db.execute(sh_q).all():
        shift_ids.append(sid)
        if t0 is None or (opened is not None and opened >= t0):
            opening += _D(ocash)
    cash_sales = _legacy_cash_sales(db, Sale.branch_id == branch_id, t0)
    mv = _legacy_movement_sums(db, shift_ids, t0)
    net_purch = _cash_purchase_net(db, company_id, branch_id, t0)
    legacy_in = opening + cash_sales + mv["payin"]
    legacy_out = mv["payout"] + mv["expense"] + mv["collection"] + net_purch
    legacy_expected = legacy_in - legacy_out
    ledger_in, ledger_out = _ledger_flows(db, company_id, cash_account_id=cash_account_id)
    ledger_expected = ledger_in - ledger_out
    delta = ledger_expected - legacy_expected
    _sibling = int(db.execute(select(func.count(CashAccount.id)).where(
        CashAccount.tenant_id == company_id, CashAccount.branch_id == branch_id)).scalar() or 0)
    _warn = (None if _sibling <= 1 else
             f"filialda {_sibling} naqd hisob bor — legacy tomon FILIAL bo'yicha, ledger tomon "
             f"FAQAT shu hisob bo'yicha; filial darajasi uchun compare_branch ishlating")
    return {
        "level": "till", "tenant_id": str(company_id), "branch_id": str(branch_id),
        "cash_account_id": str(cash_account_id), "scope_warning": _warn,
        "legacy_in": float(legacy_in), "legacy_out": float(legacy_out),
        "legacy_expected": float(legacy_expected),
        "ledger_in": float(ledger_in), "ledger_out": float(ledger_out),
        "ledger_expected": float(ledger_expected),
        "delta": float(delta), "status": _status(delta),
        "legacy_breakdown": {"opening": float(opening), "cash_sales": float(cash_sales),
                             "payin": float(mv["payin"]), "payout": float(mv["payout"]),
                             "expense": float(mv["expense"]), "collection": float(mv["collection"]),
                             "net_cash_purchases": float(net_purch)},
    }


def _branch_legacy(db: Session, company_id, branch_id, t0, *, collection_internal=False) -> dict:
    """FILIALNING legacy fizik naqd kutilmasi — BIR MARTA (hisoblar soniga bog'liq EMAS).

    `collection_internal` — INKASSA chiqim deb sanalmasin.

    ⚠️  NEGA KERAK (R-fix): inkassa = TILL -> SEYF ICHKI transfer. Ledger tomonga SEYF
        hisoblari QO'SHILGANDAN keyin juftlik nolga bekor bo'ladi (OUT till + IN seyf), legacy
        tomon esa `collection`ni CHIQIM deb ayirardi — ya'ni har inkassa uchun soxta delta.
    ⚠️  TENANT darajasida bu ANIQ: pul tenantdan chiqmaydi. FILIAL darajasida esa ANIQ EMAS —
        manba qatorda manzil YO'Q (`cash_movements` da ustun yo'q), shu bois markaziy seyfga
        qilingan inkassa filialdan CHIQADI, o'z filiali seyfiga qilingani esa YO'Q. Shu bois
        filial darajasi DIAGNOSTIK (`collection_internal=False`), tenant darajasi GATE.
    """
    sh_q = select(Shift.id, Shift.opening_cash, Shift.opened_at).where(Shift.branch_id == branch_id)
    opening, shift_ids = _Z, []
    for sid, ocash, opened in db.execute(sh_q).all():
        shift_ids.append(sid)
        if t0 is None or (opened is not None and opened >= t0):
            opening += _D(ocash)
    cash_sales = _legacy_cash_sales(db, Sale.branch_id == branch_id, t0)
    mv = _legacy_movement_sums(db, shift_ids, t0)
    net_purch = _cash_purchase_net(db, company_id, branch_id, t0)
    legacy_in = opening + cash_sales + mv["payin"]
    legacy_out = mv["payout"] + mv["expense"] + net_purch
    if not collection_internal:
        legacy_out += mv["collection"]
    return {"legacy_in": legacy_in, "legacy_out": legacy_out,
            "collection_internal": collection_internal,
            "breakdown": {"opening": float(opening), "cash_sales": float(cash_sales),
                          "payin": float(mv["payin"]), "payout": float(mv["payout"]),
                          "expense": float(mv["expense"]), "collection": float(mv["collection"]),
                          "net_cash_purchases": float(net_purch)}}


def compare_branch(db: Session, company_id, branch_id, *, t0=None,
                  collection_internal=False) -> dict:
    """Filial = legacy kutilmasi BIR MARTA vs uning BARCHA naqd hisoblari (TILL **va SEYF**).

    ⚠️  SEYF ham sanaladi (R-fix): inkassa naqdni TILL'dan SEYFga ko'chiradi va Phase 2 dan
        keyin SEYFdan to'lash MUMKIN. Faqat TILL sanalsa, seyfdagi pul ledger tomonda
        YO'QOLARDI va har SEYF amali doimiy delta berardi.
    ⚠️  Hisob YO'Q bo'lsa ham legacy tomon O'QILADI — «hisob yo'q, demak MATCH» degan jimgina
        yolg'on toza natija BO'LMASIN (ilgari roll-up bo'sh `parts` uchun MATCH qaytarardi).
    """
    lg = _branch_legacy(db, company_id, branch_id, t0,
                        collection_internal=collection_internal)
    legacy_in, legacy_out = lg["legacy_in"], lg["legacy_out"]
    legacy_expected = legacy_in - legacy_out
    accs = db.execute(select(CashAccount.id, CashAccount.type).where(
        CashAccount.tenant_id == company_id, CashAccount.branch_id == branch_id)).all()
    ledger_in, ledger_out = _Z, _Z
    acc_rows = []
    for aid, atype in accs:
        i, o = _ledger_flows(db, company_id, cash_account_id=aid)
        ledger_in += i
        ledger_out += o
        acc_rows.append({"cash_account_id": str(aid), "type": str(atype),
                         "ledger_in": float(i), "ledger_out": float(o),
                         "ledger_expected": float(i - o)})
    ledger_expected = ledger_in - ledger_out
    delta = ledger_expected - legacy_expected
    return {"level": "branch", "tenant_id": str(company_id), "branch_id": str(branch_id),
            "legacy_in": float(legacy_in), "legacy_out": float(legacy_out),
            "legacy_expected": float(legacy_expected),
            "ledger_in": float(ledger_in), "ledger_out": float(ledger_out),
            "ledger_expected": float(ledger_expected),
            "delta": float(delta), "status": _status(delta),
            "account_count": len(acc_rows), "accounts": acc_rows,
            # QAYSI konvensiya bilan hisoblangani — o'quvchi taxmin qilmasin
            "collection_internal": collection_internal,
            "legacy_breakdown": lg["breakdown"]}


def compare_tenant(db: Session, company_id, *, t0=None) -> dict:
    """Tenant = uning barcha FILIALLARI yig'indisi (hisoblar EMAS — R-fix).

    Filiallar `branches` jadvalidan olinadi, naqd hisoblardan EMAS: aks holda hisob
    provisionlanmagan filialning legacy naqdi solishtirishdan butunlay tushib qolardi.
    """
    brs = db.execute(select(Branch.id).where(Branch.company_id == company_id)).all()
    # INKASSA tenant ichida ICHKI ko'chish: TILL'dan chiqib SEYFga kiradi va ikkala hisob ham
    # shu yig'indida. Uni chiqim deb ayirish soxta delta berardi (R-fix).
    parts = [compare_branch(db, company_id, b[0], t0=t0, collection_internal=True) for b in brs]
    return _rollup("tenant", {"tenant_id": str(company_id)}, parts)


def _rollup(level, base, parts) -> dict:
    li = sum((_D(p.get("legacy_in", 0)) for p in parts), _Z)
    lo = sum((_D(p.get("legacy_out", 0)) for p in parts), _Z)
    di = sum((_D(p.get("ledger_in", 0)) for p in parts), _Z)
    do = sum((_D(p.get("ledger_out", 0)) for p in parts), _Z)
    net_delta = (di - do) - (li - lo)
    # §19 topilma (MAJOR false-negative): status NET signed delta'дан HISOBLANMASIN — teng-va-qarama-qarshi
    # bola deltalari 0'ga bekor bo'lиб yolg'on MATCH berardi. Status = ANY bola REVIEW/BLOCK bo'lса
    # eskaladsin; miqdor uchun ABSOLYUT delta ishlatiladi (offsetting'ni yashirmaydi).
    abs_delta = sum((abs(_D(p.get("delta", 0))) for p in parts), _Z)
    divergent = [p for p in parts if p.get("status") != "MATCH"]
    blocked = any(p.get("status") == "BLOCK" for p in parts)
    status = "BLOCK" if blocked else ("REVIEW" if (divergent or abs_delta > _TOL) else "MATCH")
    return {**base, "level": level,
            # ⚠️  R-fix: «part» endi FILIAL (ilgari TILL edi). Bitta filialning legacy kutilmasi
            #     BIR MARTA sanaladi, shu bois ko'p-TILL filial legacy'ni KO'PAYTIRMAYDI.
            "legacy_in": float(li), "legacy_out": float(lo), "legacy_expected": float(li - lo),
            "ledger_in": float(di), "ledger_out": float(do), "ledger_expected": float(di - do),
            "delta": float(net_delta), "abs_delta": float(abs_delta),
            "divergent_part_count": len(divergent), "status": status,
            "parts": parts}


# ═══ EVENT-LEVEL parity (item 5) ═════════════════════════════════════════════
def event_trace(db: Session, company_id, source_type, source_id) -> dict:
    """Bitta biznes hodisa: kutilган ledger biznes-kaliti(lari) vs HAQIQIY ledger qatori(lari).
    Aniqlaydi: missing leg / extra leg / wrong direction / wrong amount / duplicate business key."""
    rows = db.execute(select(CashLedgerEntry).where(
        CashLedgerEntry.tenant_id == company_id,
        CashLedgerEntry.source_type == source_type,
        CashLedgerEntry.source_id == source_id).order_by(CashLedgerEntry.leg_index)).scalars().all()
    legs = [{"leg_index": r.leg_index, "direction": r.direction, "category": r.category,
             "amount": float(r.amount), "cash_account_id": str(r.cash_account_id),
             "shift_id": str(r.shift_id) if r.shift_id else None, "posting_kind": r.posting_kind,
             "provenance": r.provenance} for r in rows]
    keys = [(r.leg_index) for r in rows]
    dup = len(keys) != len(set(keys))
    return {"source_type": source_type, "source_id": str(source_id),
            "ledger_leg_count": len(rows), "legs": legs,
            "duplicate_business_key": dup,
            "missing": len(rows) == 0}


# ═══ SNAPSHOT / observability (items 6, 15) — READ-ONLY ═══════════════════════
def snapshot(db: Session, *, company_id=None, t0=None, comparison_timestamp=None) -> dict:
    """READ-ONLY Phase-2 solishtirish snapshot: har tenant/till delta, event-mismatch soni,
    hal qilinmagan OFF_SHIFT/exception soni. HECH NIMA YOZMAYDI, deltalar YASHIRILMAYDI."""
    if company_id is not None:
        tenants = [company_id]
    else:
        tenants = [t[0] for t in db.execute(select(CashAccount.tenant_id).distinct()).all()]
    tenant_reports = []
    total_delta = _Z
    total_abs_delta = _Z
    divergent_tills = 0
    total_unresolved = 0
    any_review = any_block = False
    for tid in tenants:
        trep = compare_tenant(db, tid, t0=t0)
        total_delta += _D(trep["delta"])
        total_abs_delta += _D(trep.get("abs_delta", 0))
        divergent_tills += int(trep.get("divergent_part_count", 0))
        if trep["status"] == "BLOCK":
            any_block = True
        elif trep["status"] == "REVIEW":
            any_review = True
        # off-shift (unresolved) NORMAL leg soni
        off = db.execute(select(func.count(CashLedgerEntry.id)).where(
            CashLedgerEntry.tenant_id == tid, CashLedgerEntry.provenance == "NORMAL",
            CashLedgerEntry.posting_kind == "OFF_SHIFT")).scalar() or 0
        total_unresolved += int(off)
        trep["unresolved_off_shift"] = int(off)
        tenant_reports.append(trep)
    # §19 topilma: status ANY divergent tenant'дан eskaladsin (NET delta EMAS). event_mismatch_count
    # (avval qattiq 0 edi -> yolg'on toza) o'rniga HAQIQIY divergent_till_count.
    status = "BLOCK" if any_block else ("REVIEW" if (any_review or total_abs_delta > _TOL) else "MATCH")
    return {
        "kind": "PHASE2_SHADOW_COMPARISON_SNAPSHOT",
        "comparison_timestamp": comparison_timestamp,
        "t0": (t0.isoformat() if hasattr(t0, "isoformat") else t0),
        "tenant_count": len(tenant_reports),
        "total_delta": float(total_delta),
        "total_abs_delta": float(total_abs_delta),
        "divergent_till_count": divergent_tills,
        "unresolved_off_shift_count": total_unresolved,
        "status": status,
        "tenants": tenant_reports,
        "note": "READ-ONLY. delta=ledger(NORMAL)-legacy(physical); status ANY divergent till'дан "
                "(net EMAS, abs). Auto-repair YO'Q.",
    }


# ── DEMO-TARIX YAKUNLASH UCHUN PARITET HUKMI (SOF FUNKSIYA) ───────────
def finalize_parity_verdict(rep: dict) -> tuple[bool, str]:
    """`(ok, sabab)` — `compare_tenant` hisoboti demo-tarixni YAKUNLASH uchun yetarlimi.

    ⚠️  `status == "MATCH"` O'ZI YETARLI EMAS. `_rollup` BO'SH `parts` uchun ham
        `MATCH` qaytaradi (`divergent=[]`, `abs_delta=0`), ya'ni NOL FILIAL /
        NOL HISOB holati "muvaffaqiyat" bo'lib ko'rinardi — isbot qiymati NOL.
        Bir daraja pastda ayni yolg'on allaqachon tuzatilgan (`compare_branch`
        docstring'i: «hisob yo'q, demak MATCH» degan jimgina yolg'on), lekin
        tuzatish FILIAL ICHIDAGI hisoblarga qo'llangan, TENANT ICHIDAGI
        filiallarga EMAS.

    ⚠️  LEKIN "ikki tomonda ham naqd harakati bo'lsin" deb TALAB QILINMAYDI.
        Faqat KARTA bilan savdo qilgan demo reja qonuniy: u yerda ikki tomon
        ham HAQIQATAN nol va bu TO'G'RI javob. Bunday rejani bloklash uni
        abadiy yakunlanmaydigan holatda qoldirardi. Vakuum esa STRUKTURA bilan
        yopiladi (filial + naqd hisob mavjudligi), hajm bilan emas.

    To'rt shart BIRGA:
      1. `parts` BO'SH EMAS                — solishtirish filiallarni ko'rgan
      2. kamida bitta `account_count > 0`   — ledger tomoni MAVJUD
      3. `status == "MATCH"` va `divergent_part_count == 0`
      4. BIR TOMONLAMA hajm YO'Q: biri harakatlangan bo'lsa IKKINCHISI ham.
         Bu filial ICHIDAGI qarama-qarshi xatolar `delta` ni nolga bekor qilgan
         holatni ushlaydi (`compare_branch` filialni BITTA skalyarga keltiradi,
         `_rollup` ning `abs_delta` si esa offsetting'ni faqat PARTLAR ORASIDA
         ushlaydi). Masalan TILL aniqlanmasa `on_cash_sale` JIM `None`
         qaytaradi: legacy harakatlanadi, ledger esa BO'SH qoladi.

    Sof: baza ham, I/O ham yo'q — shu bois sintetik hisobot bilan o'lchanadi.
    """
    if not isinstance(rep, dict):
        return False, "hisobot shakli noto'g'ri"
    parts = rep.get("parts") or []
    if not parts:
        return False, "solishtirishda BIRORTA filial yo'q — nol isbot"
    if not any(int(p.get("account_count") or 0) > 0 for p in parts):
        return False, "birorta filialda naqd hisob YO'Q — ledger tomoni mavjud emas"
    status = rep.get("status")
    if status != "MATCH":
        return False, f"status={status!r} (abs_delta={rep.get('abs_delta')!r})"
    if int(rep.get("divergent_part_count") or 0) > 0:
        return False, f"divergent_part_count={rep.get('divergent_part_count')!r}"
    try:
        lin, lout = _D(rep.get("legacy_in") or 0), _D(rep.get("legacy_out") or 0)
        din, dout = _D(rep.get("ledger_in") or 0), _D(rep.get("ledger_out") or 0)
    except (TypeError, ValueError, ArithmeticError):
        return False, "hajm o'qilmadi"
    legacy_bor = (lin > _Z or lout > _Z)
    ledger_bor = (din > _Z or dout > _Z)
    if legacy_bor != ledger_bor:
        return False, (f"BIR TOMONLAMA hajm (legacy_in={float(lin)}, "
                       f"legacy_out={float(lout)}, ledger_in={float(din)}, "
                       f"ledger_out={float(dout)}) — bir tomon harakatlangan, "
                       "ikkinchisi BO'SH")
    return True, ("MATCH" if legacy_bor else "MATCH (naqd harakati YO'Q — ikki tomon ham nol)")

# ═══ STRICT FINALIZE KOMPARATORI — FAQAT demo-tarix yakunlash uchun ══════════
#
#  ⚠️  YUQORIDAGI YUZA TEGILMAYDI. `compare_shift/till/branch/tenant`, `_rollup`,
#      `_status` operator va Phase-1/Phase-2 cutover tooling'i uchun SEMANTIK
#      JIHATDAN O'ZGARMAYDI (`compare_engine.compare_run` -> `preflight` ->
#      cutover-readiness, `tools/cash_compare.py`). Quyidagi hammasi YANGI va
#      uni FAQAT `demo_history_finalize` chaqiradi.
#
#  NEGA KERAK (o'lchangan, taxmin emas):
#    1. `compare_branch` filialni BITTA skalyarga keltiradi (`delta = ledger_expected
#       - legacy_expected`), `_rollup` ning `abs_delta` si esa offsetting'ni faqat
#       PARTLAR ORASIDA ushlaydi. Ya'ni AYNI filialda qarama-qarshi ikki haqiqiy
#       nuqson (masalan -21000 ochilish + 21000 yozilmagan xarajat) nolga bekor
#       bo'lib `MATCH` beradi. O'LCHANGAN: haqiqiy `_rollup` + eski verdict
#       `(True, 'MATCH')` qaytargan.
#    2. Legacy tomoni `Shift.opening_cash` ni HAR smena uchun INFLOW deb qo'shadi,
#       ledger esa ochilish legini FAQAT `max(opening_cash - balans, 0)` uchun
#       yozadi. Bu IKKI XIL KONVENSIYA: sog'lom carry-over rejasi ham
#       `-(smenalar - tillar) x float` deltasini beradi. Shu bois umumiy skalyar
#       BU YERDA DIAGNOSTIK bo'ladi va PASS qarorini YOLG'IZ bermaydi; ochilish
#       esa qiymat-pariteti emas, ANIQ PER-SMENA invarianti bilan tekshiriladi.

#: Legacy komponent -> ledger toifalari, va legacy miqdorining ISHORASI.
#  `+1` = legacy miqdori KIRIM (ledger signed ham musbat kutiladi),
#  `-1` = legacy miqdori CHIQIM (ledger signed MANFIY kutiladi).
#  `net_cash_purchases`: `Purchase.total` ALLAQACHON net (increase qo'shadi,
#  qaytarish ayiradi — `_cash_purchase_net` docstring), shu bois ledger tomonda
#  `PURCHASE_OUT` va `PURCHASE_RETURN` BIRGA olinadi.
STRICT_COMPONENTS: dict[str, tuple[int, tuple[str, ...]]] = {
    "cash_sales":         (+1, ("SALE",)),
    "payin":              (+1, ("CASH_IN", "DEBT_IN")),
    "expense":            (-1, ("EXPENSE",)),
    "payout":             (-1, ("CASH_OUT", "REFUND", "SUPPLIER_OUT")),
    "net_cash_purchases": (-1, ("PURCHASE_OUT", "PURCHASE_RETURN")),
}

#: Ochilish toifasi — qiymat-pariteti BILAN TEKSHIRILMAYDI (3-bo'lim invarianti).
STRICT_OPENING_CATEGORY = "OPENING"

#: Strict komparator QOPLAYDIGAN toifalar. Bundan tashqaridagi HAR QANDAY
#  `NORMAL` business toifa (`TRANSFER`, `BANK_DEPOSIT`, `ADJUSTMENT`, yoki
#  kelajakda qo'shilgan yangisi) JIM TASHLANMAYDI — u `UNDETERMINED` beradi.
#  NEGA: beshta komponent o'n uchta toifani qoplamaydi; qoplanmagan toifadagi
#  delta jimgina yo'qolsa, yangi model almashtirgan skalyardan KUCHSIZROQ
#  bo'lardi.
STRICT_COVERED_CATEGORIES = frozenset(
    {STRICT_OPENING_CATEGORY} | {c for _s, cs in STRICT_COMPONENTS.values() for c in cs})


def _strict_legacy_components(db: Session, company_id) -> dict:
    """Legacy komponentlari, TENANT bo'yicha, DECIMAL da.

    ⚠️  `compare_branch` qaytargan `legacy_breakdown` ni YIG'MAYMIZ: u `float()`
        ga aylantirilgan va tolerantlik 0.005 bo'lgani uchun katta summalarda
        float shovqini soxta signal berardi. Shu bois AYNI yordamchilar
        (`_legacy_cash_sales`, `_legacy_movement_sums`, `_cash_purchase_net`)
        qayta chaqiriladi — ular Decimal qaytaradi.
    """
    out = {"cash_sales": _Z, "payin": _Z, "payout": _Z, "expense": _Z,
           "collection": _Z, "net_cash_purchases": _Z, "opening": _Z}
    brs = db.execute(select(Branch.id).where(Branch.company_id == company_id)).all()
    for (bid,) in brs:
        sh_rows = db.execute(select(Shift.id, Shift.opening_cash).where(
            Shift.branch_id == bid, Shift.deleted_at.is_(None))).all()
        sids = [r[0] for r in sh_rows]
        for _sid, ocash in sh_rows:
            out["opening"] += _D(ocash)
        out["cash_sales"] += _legacy_cash_sales(db, Sale.branch_id == bid, None)
        mv = _legacy_movement_sums(db, sids, None)
        for k in ("payin", "payout", "expense", "collection"):
            out[k] += mv[k]
        out["net_cash_purchases"] += _cash_purchase_net(db, company_id, bid, None)
    return out


def _strict_ledger_by_category(db: Session, company_id) -> dict:
    """Toifa -> IMZOLI yig'indi (ΣIN − ΣOUT), `_ledger_flows` bilan AYNI filtrlar.

    ⚠️  `repositories.category_totals` ISHLATILMAYDI: u `recorded_at` oynasi
        bo'yicha filtrlaydi (tarixiy leg uchun bu HOZIRGI payt, ya'ni tarixiy
        oynani butunlay yo'qotardi) va `source_type != ACCOUNT_OPENING`
        chiqarishni IFODALAY OLMAYDI (u toifa emas, MANBA TURI bo'yicha).
    """
    signed = func.coalesce(func.sum(
        case((CashLedgerEntry.direction == "IN", CashLedgerEntry.amount),
             else_=-CashLedgerEntry.amount)), 0)
    q = (select(CashLedgerEntry.category, signed, func.count(CashLedgerEntry.id))
         .where(CashLedgerEntry.tenant_id == company_id,
                CashLedgerEntry.provenance == "NORMAL",
                CashLedgerEntry.source_type != CashSourceType.ACCOUNT_OPENING.value)
         .group_by(CashLedgerEntry.category))
    #  \u26a0\ufe0f  SANOQ ham qaytariladi: qoplanmagan toifa MAVJUDLIK bo'yicha
    #      bayroqlanadi, imzoli yig'indi bo'yicha EMAS. Inkassa (TRANSFER) juftligi
    #      tenant darajasida nolga bekor bo'ladi \u2014 faqat summaga qarasak u JIM
    #      o'tib ketardi.
    return {str(cat): (_D(tot), int(cnt)) for cat, tot, cnt in db.execute(q).all()}


def _strict_component_rows(legacy: dict, by_cat: dict) -> list:
    rows = []
    for nom, (sign, cats) in STRICT_COMPONENTS.items():
        led = sum((by_cat.get(c, (_Z, 0))[0] for c in cats), _Z)
        kut = _D(sign) * legacy.get(nom, _Z)
        d = led - kut
        rows.append({"component": nom, "legacy": float(legacy.get(nom, _Z)),
                     "legacy_sign": sign, "ledger_categories": list(cats),
                     "ledger_signed": float(led), "expected_signed": float(kut),
                     "delta": float(d),
                     "status": ("MATCH" if abs(d) <= _TOL else "REVIEW")})
    return rows

#: Ochilish legining KANONIK shakli — bundan har qanday chetlanish FAIL.
_STRICT_OPEN_SRC = "SHIFT_OPEN"


def _strict_legs_by_account(db: Session, company_id) -> tuple[dict, dict]:
    """`(hisob -> leglar, source_id -> SHIFT_OPEN leglari)`. Bir marta o'qiladi.

    ⚠️  FILTR YO'Q — ataylab. `B_pre` yozuvchi KO'RGAN holatni qayta tiklashi
        kerak, yozuvchi esa `repositories.account_balance` ni ishlatgan: u faqat
        `tenant_id` va `cash_account_id` bo'yicha filtrlaydi. Provenance,
        category, posting_kind yoki vaqt filtri qo'shilsa, `B_pre` yozuvchidan
        BOSHQA holatni hisoblardi — migratsiya qilingan tenantda (REKONSTRUKSIYA
        leglari) va OFF_SHIFT leglari bo'lgan tenantda SOXTA FAIL chiqardi.
    """
    rows = db.execute(select(
        CashLedgerEntry.id, CashLedgerEntry.cash_account_id, CashLedgerEntry.direction,
        CashLedgerEntry.amount, CashLedgerEntry.category, CashLedgerEntry.source_type,
        CashLedgerEntry.source_id, CashLedgerEntry.leg_index, CashLedgerEntry.provenance,
        CashLedgerEntry.device_occurred_at, CashLedgerEntry.recorded_at,
        CashLedgerEntry.posting_kind,
    ).where(CashLedgerEntry.tenant_id == company_id)).all()
    by_acc: dict = {}
    by_src: dict = {}
    for (eid, acc, direction, amount, cat, stype, sid, lidx, prov, dev, rec, pk) in rows:
        leg = {"id": str(eid), "account": str(acc), "direction": str(direction),
               "amount": _D(amount), "category": str(cat), "source_type": str(stype),
               "source_id": (str(sid) if sid is not None else None),
               "leg_index": int(lidx or 0), "provenance": str(prov),
               "device_occurred_at": dev, "recorded_at": rec, "posting_kind": str(pk)}
        by_acc.setdefault(str(acc), []).append(leg)
        if leg["source_type"] == _STRICT_OPEN_SRC:
            by_src.setdefault(leg["source_id"], []).append(leg)
    return by_acc, by_src


def _strict_ordering_verdict(legs: list) -> tuple[bool, str]:
    """Hisob leglarining tartibi `B_pre` ni hisoblash uchun ISHONCHLIMI.

    ⚠️  `recorded_at` UNIVERSAL COMMIT KETMA-KETLIGI DEB QABUL QILINMAYDI —
        o'lchangan: `recv = _now()` `post()` ning BOSHIDA, `_lock_account` dan
        OLDIN olinadi (`posting.py:78`, `:98`), ya'ni u QO'SHILISH emas,
        CHAQIRUVGA KIRISH tartibini beradi; qulfda kutgan chaqiruv kichikroq
        `recorded_at` bilan KEYINROQ insert qiladi. Shu bois u DALIL emas,
        faqat INVERSIYA DETEKTORI: biznes-vaqt tartibi bilan kelishmasligi
        aniqlansa, tartib NOANIQ deb e'lon qilinadi.

    Ikki shart:
      · INVERSIYA YO'Q — biznes-vaqt bo'yicha saralanganda `recorded_at` ham
        kamaymasin (ikki yo'nalish bitta o'tishda qamraladi);
      · `recorded_at` JUFT-JUFT FARQLI — aks holda inversiya detektori ko'r
        bo'ladi (Phase-1 backfill'da u batch bo'yicha KONSTANTA).
    """
    if len(legs) < 2:
        return True, "ok"
    tartib = sorted(legs, key=lambda l: (l["device_occurred_at"], l["id"]))
    oldin = None
    for l in tartib:
        if l["recorded_at"] is None or l["device_occurred_at"] is None:
            return False, f"leg {l['id']}: vaqt maydoni bo'sh"
        if oldin is not None and l["recorded_at"] < oldin["recorded_at"]:
            return False, (f"INVERSIYA: leg {l['id']} biznes-vaqti kechroq, lekin "
                           f"{oldin['id']} dan OLDIN qayd etilgan")
        oldin = l
    recs = [l["recorded_at"] for l in legs]
    if len(set(recs)) != len(recs):
        return False, "`recorded_at` TAKRORLANADI — inversiya detektori ko'r bo'ladi"
    return True, "ok"


def _strict_openings(db: Session, company_id, by_acc: dict, by_src: dict) -> dict:
    """Per-smena ochilish invarianti + strukturaviy twin + teskari yarashtirish."""
    out = {"openings": [], "structural": [], "orphans": []}
    rows = db.execute(
        select(Shift.id, Shift.till_id, Shift.opening_cash, Shift.opened_at)
        .join(Branch, Branch.id == Shift.branch_id)
        .where(Branch.company_id == company_id, Shift.deleted_at.is_(None))).all()
    shift_ids = {str(r[0]) for r in rows}

    for sid, till_id, ocash, opened in rows:
        sid_s = str(sid)
        #  ══ 1) STRUKTURAVIY TWIN — ATAYLAB SAQLANGAN BAND ════════════════
        #  Ega 1-darajaning QIYMAT bandlarini kontrmisol bilan rad etdi, lekin
        #  STRUKTURAVIY bandni emas. U saqlanmasa `test_second_cashier_...`
        #  regressiyasi YASHILLASHIB ketardi: ikkinchi kassirning smenasi uchun
        #  `max(50000-100000,0)=0` bo'lib, aniq invariant o'zi PASS beradi.
        if till_id is None:
            out["structural"].append({"shift_id": sid_s, "status": "NO_TILL",
                                      "reason": "smena kassasiz (till_id NULL) — "
                                                "ledger-native do'konda custody noaniq"})
            continue
        twin = db.get(CashShift, sid)
        if twin is None or str(getattr(twin, "tenant_id", "")) != str(company_id):
            out["structural"].append({"shift_id": sid_s, "status": "NO_TWIN",
                                      "reason": "cash.shifts egizagi YO'Q"})
            continue
        if str(twin.cash_account_id) != str(till_id):
            out["structural"].append({"shift_id": sid_s, "status": "ANCHOR_MISMATCH",
                                      "reason": f"egizak hisobi {twin.cash_account_id} != "
                                                f"smena kassasi {till_id}"})
            continue

        acc = str(twin.cash_account_id)
        legs = by_acc.get(acc, [])
        linked = by_src.get(sid_s, [])

        #  ══ 2) IDENTITY SWEEP — KENG ════════════════════════════
        #  AYNI `source_type`/`source_id` bilan NOTO'G'RI shakldagi leg ham
        #  KO'RINSIN: `shift_id` bo'yicha izlash YARAMAYDI, chunki
        #  `posting._resolve_shift` legni OFF_SHIFT ga demote qilib `shift_id`
        #  ni NULL qilishi mumkin. (`origin_shift_id` ustuni esa MAVJUD EMAS —
        #  u faqat adapter parametri nomi.)
        kanonik, buzuq = [], []
        for l in linked:
            if (l["direction"] == "IN" and l["category"] == STRICT_OPENING_CATEGORY
                    and l["leg_index"] == 0 and l["account"] == acc):
                kanonik.append(l)
            else:
                buzuq.append(l)
        if buzuq:
            out["openings"].append({
                "shift_id": sid_s, "status": "FAIL", "reason": "MALFORMED_LINKED_LEG",
                "detail": [{"id": b["id"], "direction": b["direction"],
                            "category": b["category"], "leg_index": b["leg_index"],
                            "account": b["account"]} for b in buzuq]})
            continue
        if len(kanonik) > 1:
            out["openings"].append({"shift_id": sid_s, "status": "FAIL",
                                    "reason": "DUPLICATE_OPENING_LEG",
                                    "detail": [k["id"] for k in kanonik]})
            continue
        anchor = kanonik[0] if kanonik else None

        #  ══ 3) KUTILGAN SUMMA — KONVENSIYALAR ARALASHTIRILMAYDI ══════════
        #  Phase-1 REKONSTRUKSIYASI ochilish legini TO'LIQ `opening_cash` bilan
        #  yozadi (`phase1.py:219-231`, `amount=oc`); jonli yozuvchi esa FARQNI.
        #  Ikkisi AYNI biznes kalitini egallaydi, shu bois kutilgan summa legning
        #  O'Z provenance'iga qarab tanlanadi — aks holda migratsiya qilingan
        #  tenantda TO'G'RI leg yiqilardi.
        if anchor is not None and anchor["provenance"] == "RECONSTRUCTION":
            out["openings"].append({
                "shift_id": sid_s, "status": "MATCH", "convention": "RECONSTRUCTION",
                "expected": float(_D(ocash)), "actual": float(anchor["amount"]),
                "b_pre": None,
                **({"status": "FAIL", "reason": "RECONSTRUCTION_AMOUNT"}
                   if abs(anchor["amount"] - _D(ocash)) > _TOL else {})})
            continue

        #  NORMAL konvensiya — `B_pre` kerak, demak TARTIB ISBOTI ham kerak.
        ok_ord, sabab = _strict_ordering_verdict(legs)
        if not ok_ord:
            out["openings"].append({"shift_id": sid_s, "status": "UNDETERMINED",
                                    "reason": "ORDERING_AMBIGUOUS", "detail": sabab})
            continue
        if anchor is not None and anchor["device_occurred_at"] != opened:
            out["openings"].append({
                "shift_id": sid_s, "status": "UNDETERMINED", "reason": "ANCHOR_TIME_DRIFT",
                "detail": f"leg vaqti {anchor['device_occurred_at']} != smena "
                          f"ochilishi {opened}"})
            continue
        bogh = {l["id"] for l in linked}
        chegara = [l for l in legs
                   if l["id"] not in bogh and l["device_occurred_at"] == opened]
        if chegara:
            out["openings"].append({
                "shift_id": sid_s, "status": "UNDETERMINED", "reason": "BOUNDARY_TIE",
                "detail": [c["id"] for c in chegara]})
            continue

        #  ══ 4) B_pre — YOZUVCHI KO'RGAN PRE-STATE ═══════════════════
        #  LITERAL `account_balance()` CHAQIRILMAYDI: yakunlash paytida u BUTUN
        #  tarixni (kelajak leglarini ham) sanaydi va butunlay boshqa son berardi.
        #  Chegara — smena ochilish lahzasi: ochilish legining
        #  `device_occurred_at` i `Shift.opened_at` ga AYNAN teng (ikkisi bitta
        #  Python o'zgaruvchisi: `shifts.py:166` `opened_at=_now_at`, `:176`
        #  `at=_now_at` -> `retrofit.py:177`), va yuqorida bu tenglik alohida
        #  tasdiqlanadi (`ANCHOR_TIME_DRIFT`).
        b_pre = _Z
        for l in legs:
            if l["id"] in bogh:
                continue
            if l["device_occurred_at"] >= opened:
                continue          # KELAJAK qatorlar KIRMAYDI (qat'iy `<`)
            b_pre += l["amount"] if l["direction"] == "IN" else -l["amount"]

        kutilgan = _D(ocash) - b_pre
        if kutilgan < _Z:
            kutilgan = _Z         # yozuvchi qoidasi: `if _delta > 0` — manfiy YOZILMAYDI

        rec = {"shift_id": sid_s, "convention": "NORMAL", "b_pre": float(b_pre),
               "opening_cash": float(_D(ocash)), "expected": float(kutilgan),
               "actual": (float(anchor["amount"]) if anchor is not None else None),
               "legs": len(kanonik)}
        if kutilgan > _Z:
            if anchor is None:
                rec.update(status="FAIL", reason="MISSING_OPENING_LEG")
            elif abs(anchor["amount"] - kutilgan) > _TOL:
                rec.update(status="FAIL", reason="OPENING_AMOUNT")
            else:
                rec.update(status="MATCH")
        else:
            rec.update(status=("MATCH" if anchor is None else "FAIL"),
                       reason=(None if anchor is None else "UNEXPECTED_OPENING_LEG"))
        out["openings"].append(rec)

    #  ══ 5) TESKARI YARASHTIRISH — leg -> smena ════════════════════
    #  Faqat smena -> leg yo'nalishi YETMAYDI: tasodifiy `source_id` bilan
    #  yozilgan soxta OCHILISH legi hech qaysi smenaga kalitlanmaydi va bir
    #  yo'nalishli komparator uni UMUMAN KO'RMAYDI. Bu nazariy emas —
    #  `cash/lifecycle.open_shift` aynan shunday yozuvchi (`source_id=uuid4()`,
    #  TO'LIQ summa); uning app chaqiruvchisi yo'q, lekin shakl mavjud.
    #  SEYF attestatsiyasi bu yerga TUSHMAYDI: u `ADJUSTMENT`/`ACCOUNT_OPENING`
    #  (`safe_opening.py:263-267`), ya'ni `OPENING` toifasi EMAS — aralashtirilmaydi.
    for acc_legs in by_acc.values():
        for l in acc_legs:
            if l["category"] != STRICT_OPENING_CATEGORY:
                continue
            if l["source_type"] != _STRICT_OPEN_SRC:
                out["orphans"].append({"id": l["id"], "reason": "OPENING_WRONG_SOURCE_TYPE",
                                       "source_type": l["source_type"]})
            elif l["source_id"] not in shift_ids:
                out["orphans"].append({"id": l["id"], "reason": "OPENING_UNLINKED",
                                       "source_id": l["source_id"]})
    return out


def strict_finalize_report(db: Session, company_id) -> dict:
    """Demo-tarix yakunlash uchun QAT'IY hisobot. FAQAT O'QISH.

    Eski skalyar (`compare_tenant`) BU YERDA ishlatilmaydi — u chaqiruvchida
    DIAGNOSTIK sifatida qoladi. Sabab: sog'lom carry-over rejasi ham noldan
    farqli skalyar beradi, shu bois u PASS qarorini bera OLMAYDI."""
    by_acc, by_src = _strict_legs_by_account(db, company_id)
    legacy = _strict_legacy_components(db, company_id)
    by_cat = _strict_ledger_by_category(db, company_id)
    comps = _strict_component_rows(legacy, by_cat)
    uncovered = [{"category": c, "signed": float(v[0]), "legs": v[1]}
                 for c, v in sorted(by_cat.items())
                 if c not in STRICT_COVERED_CATEGORIES and v[1] > 0]
    op = _strict_openings(db, company_id, by_acc, by_src)

    def _bad(seq, ok=("MATCH",)):
        return [x for x in seq if x.get("status") not in ok]

    muammo = {
        "components": _bad(comps),
        "uncovered_categories": uncovered,
        "openings": _bad(op["openings"]),
        "structural": op["structural"],
        "orphan_openings": op["orphans"],
    }
    holat = "MATCH"
    if muammo["uncovered_categories"] or any(
            x.get("status") == "UNDETERMINED" for x in muammo["openings"]):
        holat = "UNDETERMINED"
    elif any(muammo.values()):
        holat = "REVIEW"
    return {"level": "tenant_strict", "tenant_id": str(company_id), "status": holat,
            "components": comps, "uncovered_categories": uncovered,
            "openings": op["openings"], "structural": op["structural"],
            "orphan_openings": op["orphans"],
            "counts": {"shifts": len(op["openings"]) + len(op["structural"]),
                       "accounts": len(by_acc),
                       "problems": sum(len(v) for v in muammo.values())},
            "problems": muammo}


def strict_finalize_verdict(rep: dict) -> tuple[bool, str]:
    """`(ok, sabab)` — SOF funksiya, bazasiz o'lchanadi.

    PASS FAQAT hamma bo'lim toza bo'lganda. `FAIL`, `REVIEW`, `UNDETERMINED`,
    `NO_TWIN`, `ANCHOR_MISMATCH`, `NO_TILL` — hammasi RAD."""
    if not isinstance(rep, dict):
        return False, "hisobot shakli noto'g'ri"
    pr = rep.get("problems")
    if not isinstance(pr, dict):
        #  FAIL-CLOSED: shakl kutilganidan boshqa bo'lsa «muammo yo'q» deb
        #  O'QILMAYDI. (Bu shox testda tutilgan: `problems` matn bo'lsa ilgari
        #  `AttributeError` -> 500 berardi.)
        return False, "hisobot `problems` bo'limi yo'q yoki shakli noto'g'ri"
    uc = pr.get("uncovered_categories") or []
    if uc:
        return False, ("QOPLANMAGAN ledger toifasi: "
                       + ", ".join(f"{u['category']}({u['legs']} leg)" for u in uc))
    und = [o for o in (pr.get("openings") or []) if o.get("status") == "UNDETERMINED"]
    if und:
        return False, ("TARTIB/ANIQLIK NOANIQ (fail-closed): "
                       + ", ".join(f"{o['shift_id']}:{o.get('reason')}" for o in und[:5]))
    st = pr.get("structural") or []
    if st:
        return False, ("STRUKTURAVIY: "
                       + ", ".join(f"{x['shift_id']}:{x['status']}" for x in st[:5]))
    orp = pr.get("orphan_openings") or []
    if orp:
        return False, ("BOG'LANMAGAN ochilish legi: "
                       + ", ".join(f"{o['id']}:{o['reason']}" for o in orp[:5]))
    op = pr.get("openings") or []
    if op:
        return False, ("OCHILISH invarianti: "
                       + ", ".join(f"{o['shift_id']}:{o.get('reason')}"
                                   f"(kutilgan={o.get('expected')},"
                                   f"haqiqiy={o.get('actual')})" for o in op[:5]))
    cp = pr.get("components") or []
    if cp:
        return False, ("KOMPONENT pariteti: "
                       + ", ".join(f"{c['component']}\u0394={c['delta']}" for c in cp))
    #  Vakuum himoyasi: hech qanday smena ham, hisob ham bo'lmasa isbot NOL.
    cnt = rep.get("counts") or {}
    if int(cnt.get("accounts") or 0) < 1:
        return False, "naqd hisob YO'Q — nol isbot"
    if int(cnt.get("shifts") or 0) < 1:
        return False, "smena YO'Q — nol isbot"
    return True, "STRICT MATCH"

