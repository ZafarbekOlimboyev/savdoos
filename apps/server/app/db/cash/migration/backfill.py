# -*- coding: utf-8 -*-
"""Cash Ledger · Migration Phase 1 — HISTORICAL BACKFILL EXECUTOR (migration-owner append).

EXECUTION_DESIGN.md ni bajaradi. QAT'IY:
  * MIGRATION-ONLY: bu modul runtime kod yo'lidan CHAQIRILMAYDI (faqat aniq migration operatsiyasi).
    CashPostingService runtime YAGONA yozувчиligicha qoladi. Bu — sanctioned migration-time writer
    (direct-write audit whitelistда). Faqat migration-owner ishga tushiradi.
  * APPEND-ONLY: FAQAT INSERT (UPDATE/DELETE yo'q). Biznes-kaliti (tenant, source_type, source_id,
    leg_index) + deterministik uuid5 id. Idempotentlik DB darajасида: ON CONFLICT DO NOTHING.
  * FAITHFUL: tarixiy summalar/vaqtlar O'ZGARTIRILMAYDI. Manfiy running-balance -> REVIEW, lekin leg
    baribir yoziladi (clamp yo'q, soxta opening yo'q, jimgina NegativeCashApproval yo'q).
  * TAXMIN YO'Q: hal qilinmagan account/shift -> BLOCK/REVIEW, hech qachon actor_branch "first active".
  * dry-run == execution: manifest-hash bilan tasdiqlanadi (bir xil rejadan yoziladi).
"""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.cash.migration import phase0, phase1
from app.models.auth import EmployeeBranch
from app.models.cash import CashAccount, CashLedgerEntry, CashShift
from app.models.customers import CustomerPayment
from app.models.enums import CashMovementType
from app.models.org import Branch
from app.models.purchasing import SupplierPayment
from app.models.shifts import CashMovement, Shift

_D0 = Decimal("0")
# Deterministik tartib uchun source_type rank: OPENING (SHIFT_OPEN) doim BIRINCHI (§4).
_SRC_RANK = {"SHIFT_OPEN": 0, "SALE": 1, "CASH_OP": 2, "DEBT_IN": 3, "PURCHASE_RETURN": 4,
             "REFUND": 5, "PURCHASE": 6, "SUPPLIER_PAYMENT": 7, "CUSTOMER_PAYMENT": 3}
_TOL = timedelta(minutes=int(__import__("os").getenv("CASH_TS_TOLERANCE_MIN", "60")))
_MAXH = int(__import__("os").getenv("CASH_MAX_SHIFT_HOURS", "24"))


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _ts(iso):
    return phase1._parse_ts(iso)


# ═══ Kontekst (bir marta yuklanadi) ══════════════════════════════════════════
def _build_context(db: Session, company_id) -> dict:
    tills: dict[str, CashAccount] = {}
    aq = db.query(CashAccount).filter(CashAccount.type == "TILL", CashAccount.status == "ACTIVE")
    if company_id is not None:
        aq = aq.filter(CashAccount.tenant_id == company_id)
    for a in aq.all():
        tills[str(a.branch_id)] = a
    active_branches: dict[str, list] = {}
    bq = db.query(Branch.id, Branch.company_id).filter(Branch.deleted_at.is_(None), Branch.is_active.is_(True))
    if company_id is not None:
        bq = bq.filter(Branch.company_id == company_id)
    for bid, cid in bq.all():
        active_branches.setdefault(str(cid), []).append(str(bid))
    emp_br: dict[str, list] = {}
    for eid, bid in db.query(EmployeeBranch.employee_id, EmployeeBranch.branch_id).all():
        emp_br.setdefault(str(eid), []).append(str(bid))
    return {"tills": tills, "active_branches": active_branches, "emp_br": emp_br}


# ═══ §3 ACCOUNT RESOLUTION (ranked; REVIEW/BLOCK, hech qachon guess) ══════════
def resolve_account(db: Session, leg: dict, ctx: dict):
    """(CashAccount, method) yoki (None, (severity, reason)). Ranking EXECUTION_DESIGN §3."""
    tills = ctx["tills"]
    tenant = leg["tenant_id"]
    acc = method = None
    if leg["branch_id"]:                                  # a. explicit branch_id
        acc = tills.get(leg["branch_id"])
        if acc is None:
            return None, ("BLOCK", f"branch {leg['branch_id']} uchun ACTIVE TILL yo'q (ambiguous/xaritalanmagan)")
        method = "explicit_branch"
    else:
        brs = ctx["active_branches"].get(tenant, [])
        if len(brs) == 1 and tills.get(brs[0]) is not None:   # b. single active branch
            acc, method = tills[brs[0]], "single_branch"
        else:
            br = _resolve_via_shadow(db, leg)                 # c. unique shadow -> shift.branch (tenant-scoped)
            if br and tills.get(br) is not None:
                acc, method = tills[br], "shadow"
            else:
                br = _resolve_via_employee(db, leg, ctx)      # d. employee sole EmployeeBranch
                if br and tills.get(br) is not None:
                    acc, method = tills[br], "employee_branch"
    if acc is None:                                      # e. REVIEW — TAXMIN YO'Q
        return None, ("REVIEW", "account aniqlanmadi (multi-branch; explicit/shadow/employee yo'q) — operator")
    # §16 topilma: CROSS-TENANT guard — resolved TILL leg tenant'iga tegishli bo'lishi SHART.
    if str(acc.tenant_id) != tenant:
        return None, ("BLOCK", f"resolved TILL tenant {acc.tenant_id} != leg tenant {tenant} (cross-tenant)")
    return acc, method


def _source_row(db, leg):
    st = leg["source_type"]
    sid = uuid.UUID(leg["source_id"])
    if st == "SUPPLIER_PAYMENT":
        return db.get(SupplierPayment, sid)
    if st == "CUSTOMER_PAYMENT":
        return db.get(CustomerPayment, sid)
    return None


def _resolve_via_shadow(db, leg):
    """Manba to'lovining SOYA CashMovement'ini (payin/payout, reason-prefiks, client_uuid NULL) topib
    uning smenasi filialini oladi. FAQAT NOYOB moslik (employee+amount+prefiks) qabul qilinadi."""
    row = _source_row(db, leg)
    if row is None:
        return None
    if leg["source_type"] == "SUPPLIER_PAYMENT":
        mtype, prefix = CashMovementType.payout, "Ta'minotchi · "
    elif leg["source_type"] == "CUSTOMER_PAYMENT":
        mtype, prefix = CashMovementType.payin, "Qarz to'lovi · "
    else:
        return None
    # §16 topilma: soya so'rovi leg TENANTига scope qilinadi (Branch.company_id) — aks holда boshqa
    # tenant'ning bir xil summa/employee soyasiga tushib cross-tenant TILL berardi.
    q = (db.query(Shift.branch_id).join(CashMovement, CashMovement.shift_id == Shift.id)
         .join(Branch, Branch.id == Shift.branch_id).filter(
            Branch.company_id == uuid.UUID(leg["tenant_id"]),
            CashMovement.type == mtype, CashMovement.client_uuid.is_(None),
            CashMovement.reason.like(prefix + "%"),
            CashMovement.amount == _D(leg["amount"]),
            CashMovement.employee_id == getattr(row, "employee_id", None)))
    rows = q.distinct().all()
    return str(rows[0][0]) if len(rows) == 1 else None


def _resolve_via_employee(db, leg, ctx):
    row = _source_row(db, leg)
    eid = getattr(row, "employee_id", None) if row is not None else None
    if eid is None:
        return None
    brs = ctx["emp_br"].get(str(eid), [])
    return brs[0] if len(brs) == 1 else None


# ═══ §2 SHIFT RECONSTRUCTION + ATTRIBUTION ═══════════════════════════════════
def reconstruct_shifts(db: Session, exec_legs: list, t0dt, *, apply: bool):
    """ON_SHIFT legalarning legacy smenalarини cash.shifts'ga reconstruct qiladi (legacy id, CLOSED).
    T0'ни kesib o'tган smena (open yoki closed_at>=t0) -> REVIEW (uning legalari INSERT qilinmaydi).
    Qaytaradi: (window_by_shift, straddle_shift_ids). Idempotent (mavjud cash.shift o'tkazиб yuboriladi)."""
    window: dict[str, tuple] = {}
    straddle: set = set()
    shift_account: dict[str, str] = {}
    shift_ids = {l["shift_id"] for l in exec_legs if l["posting_kind_proposed"] == "ON_SHIFT" and l["shift_id"]}
    for sid in shift_ids:
        sh = db.get(Shift, uuid.UUID(sid))
        if sh is None:
            straddle.add(sid); continue
        is_open = (sh.status.value if hasattr(sh.status, "value") else str(sh.status)) == "open"
        closed = sh.closed_at
        # §16 topilma: OCHIQ yoki yopilmagan legacy smena HECH QACHON CLOSED cash.shift'ga SODIQ
        # reconstruct qilinmaydi (soxta closed_at) -> DOIM straddle/REVIEW (t0'дан qat'i nazar).
        # Yopiq lekin >=t0 -> t0 berilса straddle (live hudud).
        if is_open or closed is None or (t0dt is not None and _ts(closed.isoformat()) >= t0dt):
            straddle.add(sid); continue
        acc_id = next((l["cash_account_id"] for l in exec_legs if l["shift_id"] == sid and l["cash_account_id"]), None)
        if acc_id is None:
            straddle.add(sid); continue
        window[sid] = (sh.opened_at, closed)
        shift_account[sid] = acc_id     # smena BITTA TILL'ga qadaladi (leg account farq qilса -> OFF_SHIFT+REVIEW)
        if apply and db.get(CashShift, uuid.UUID(sid)) is None:
            acc = db.get(CashAccount, uuid.UUID(acc_id))
            # closed_at > opened_at SHART (sh_window). closed yaroqsiz bo'lса max-oyna chegarasi
            # (opened + MAXH) — EVENT vaqtini clamp EMAS, smena yopilish chegarasini tiklaydi.
            close_val = closed if closed > sh.opened_at else (sh.opened_at + timedelta(hours=_MAXH))
            db.add(CashShift(id=uuid.UUID(sid), tenant_id=acc.tenant_id, cash_account_id=acc.id,
                             branch_id=acc.branch_id, account_type="TILL", status="CLOSED",
                             opened_at=sh.opened_at, closed_at=close_val, version=1,
                             opened_by=sh.cashier_id))
    if apply:
        db.flush()
    return window, straddle, shift_account


def _attribute_shift(leg, window, straddle, shift_account):
    """Yakuniy (posting_kind, shift_id) — §2. straddle/ochiq -> REVIEW; account-mos emas -> OFF_SHIFT+REVIEW;
    out-of-window -> OFF_SHIFT."""
    sid = leg["shift_id"]
    if leg["posting_kind_proposed"] != "ON_SHIFT" or not sid:
        return "OFF_SHIFT", None, None
    if sid in straddle:
        return None, None, ("REVIEW", f"smena {sid} T0'ни kesadi / ochiq — operator T0'да yopsin")
    # §16 topilma: leg account'i smena account'iga MOS bo'lishi SHART (cle_shift_fk). Farq (sale.branch !=
    # shift.branch) -> ON_SHIFT bo'lmaydi -> OFF_SHIFT + REVIEW (jimgina FK-fail/batch-yo'qotish YO'Q).
    if shift_account.get(sid) != leg["cash_account_id"]:
        return "OFF_SHIFT", None, ("REVIEW", f"leg account leg {leg['cash_account_id']} != smena {sid} account "
                                             f"{shift_account.get(sid)} (branch nomuvofiq) -> OFF_SHIFT")
    opened, closed = window.get(sid, (None, None))
    dt = _ts(leg["device_occurred_at"])
    if opened is not None and dt is not None:
        lo = _ts(opened.isoformat()) - _TOL
        hi = (_ts(closed.isoformat()) if closed else _ts(opened.isoformat()) + timedelta(hours=_MAXH)) + _TOL
        if not (lo <= dt <= hi):
            return "OFF_SHIFT", None, ("REVIEW_TS", f"{leg['device_occurred_at']} smena {sid} oynasidan tashqarida")
    return "ON_SHIFT", sid, None


# ═══ Manifest hash (dry-run == execution parity) ═════════════════════════════
def _manifest_hash(exec_legs: list, t0, scope) -> str:
    """Fingerprint HAR yoziladigan avtoritativ ustunni qamraydi (§16 topilma): device_occurred_at
    (DDL "authoritative accounting time"), currency, branch_id ham — aks holда faqat vaqti farq
    qiladigan reja bir xil hashга tushib, approved_hash noto'g'ri vaqtli qatorni ruxsat berardi."""
    payload = [f"{l['tenant_id']}|{l['source_type']}|{l['source_id']}|{l['leg_index']}|{l['amount']}|"
               f"{l['direction']}|{l['category']}|{l['cash_account_id']}|{l['account_branch_id']}|"
               f"{l['currency']}|{l['posting_kind']}|{l['shift_id']}|{l['device_occurred_at']}"
               for l in exec_legs]
    payload.sort()
    h = hashlib.sha256(("||".join(payload) + f"##t0={t0}##scope={scope}").encode()).hexdigest()
    return h


def _order_key(l):
    return (_ts(l["device_occurred_at"]) or datetime.min.replace(tzinfo=timezone.utc),
            _SRC_RANK.get(l["source_type"], 99), l["source_id"], l["leg_index"])


# ═══ execute / verify / reconcile ════════════════════════════════════════════
def _insert_batch(db: Session, batch: list):
    """Bitta batch INSERT ... ON CONFLICT DO NOTHING RETURNING id. Muvaffaq -> yozilganlar SONI;
    xato -> None (rollback qilingan) — per-row fallback (poison-qator izolyatsiyasi) uchun."""
    try:
        stmt = (pg_insert(CashLedgerEntry.__table__).values(batch)
                .on_conflict_do_nothing().returning(CashLedgerEntry.__table__.c.id))
        n = len(db.execute(stmt).fetchall())
        db.commit()
        return n
    except Exception:
        db.rollback()
        return None


def execute_backfill(db: Session, *, company_id, t0: str | None = None, apply: bool = False,
                     approved_hash: str | None = None, batch_size: int = 500,
                     run_id: str | None = None) -> dict:
    """Tarixiy backfill'ни BAJARADI (apply=True) yoki REJALASHTIRADI (apply=False). apply=False -> yozuv yo'q.
    approved_hash berilса va manifest-hash mos kelмаса -> RAD (manifest mismatch). Faqat Postgres."""
    started = time.monotonic()
    run_id = run_id or str(uuid.uuid4())
    dialect = db.get_bind().dialect.name
    t0dt = _ts(t0) if t0 else None
    plan = phase1.plan_backfill(db, company_id=company_id, t0=t0)
    ctx = _build_context(db, company_id)

    approved, blocked, review = [], [], []
    # 1) account resolution + T0 (plan allaqачон <t0; after_t0 alohida)
    for leg in plan["legs"]:
        acc, method = resolve_account(db, leg, ctx)
        if acc is None:
            sev, reason = method
            (blocked if sev == "BLOCK" else review).append({**leg, "reason": reason, "severity": sev})
            continue
        approved.append({**leg, "cash_account_id": str(acc.id), "currency": acc.currency,
                         "account_branch_id": str(acc.branch_id), "posting_kind_proposed": leg["posting_kind"]})

    # 2) shift WINDOW/straddle/account COMPUTE (YOZUV YO'Q — gate'dан oldin; §16 topilma)
    window, straddle, shift_account = reconstruct_shifts(db, approved, t0dt, apply=False)

    # 3) final shift attribution (account-mos, straddle, out-of-window)
    final = []
    for leg in approved:
        pk, sid, note = _attribute_shift(leg, window, straddle, shift_account)
        if pk is None:                      # straddle/ochiq -> REVIEW (INSERT qilinmaydi)
            review.append({**leg, "reason": note[1], "severity": "REVIEW"}); continue
        if note is not None:                # out-of-window / account-mos emas -> OFF_SHIFT + REVIEW iz
            review.append({"source": leg["reconstruction"]["source_ref"], "reason": note[1], "severity": "REVIEW"})
        final.append({**leg, "posting_kind": pk, "shift_id": sid})

    # 4) deterministik tartib + running-balance (manfiy -> REVIEW, lekin post)
    final.sort(key=_order_key)
    review += _negative_review(final)

    manifest_hash = _manifest_hash(final, t0, str(company_id))
    now = datetime.now(timezone.utc)
    # ── GATE'lar HAR QANDAY YOZUVDAN OLDIN (§16 topilma: REJECTED/NO-GO cash.shifts ham yozmasин).
    # Bu nuqtaga qadar reconstruct_shifts(apply=False) va resolve_account FAQAT O'QIYDI — hech qanday
    # pending yozuv yo'q, shu bois REJECTED rollback QILMAYDI (chaqiruvchining committed holatiga tegmaydi).
    if approved_hash is not None and approved_hash != manifest_hash:
        return {"run_id": run_id, "status": "REJECTED_MANIFEST_MISMATCH",
                "expected_hash": approved_hash, "actual_hash": manifest_hash, "wrote_ledger": False}
    go = (len(blocked) == 0 and len(plan["block_rows"]) == 0 and len(plan["duplicate_conflicts"]) == 0)

    inserted = existing = failed = 0
    if apply and go:
        # Gate'lar o'tdi -> ENDI cash.shifts yoziladi (idempotent), so'ng legalar.
        reconstruct_shifts(db, final, t0dt, apply=True); db.commit()
        rows = [_entry_values(l, now, run_id) for l in final]
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            ins = _insert_batch(db, batch)
            if ins is None:                             # batch xato -> HAR QATORNI ALOHIDA (poison-izolyatsiya)
                for row in batch:
                    r1 = _insert_batch(db, [row])
                    if r1 is None:
                        failed += 1                     # yagona yaroqsiz qator -> failed; qolganlar yoziladi
                    else:
                        inserted += r1; existing += 1 - r1
            else:
                inserted += ins
                existing += len(batch) - ins            # allaqачон mavjud (idempotent rerun)

    manifest = {
        "kind": "PHASE1_BACKFILL_MANIFEST", "run_id": run_id, "wrote_ledger": bool(apply and go),
        "dialect": dialect, "t0": t0, "tenant_scope": str(company_id),
        "candidate_rows": plan["total_candidate_rows"],
        "approved_rows": len(final),
        "blocked_rows": len(blocked) + len(plan["block_rows"]),
        "review_rows": len(review) + len(plan["review_rows"]),
        "in_total": round(sum(_D(l["amount"]) for l in final if l["direction"] == "IN"), 2).__float__(),
        "out_total": round(sum(_D(l["amount"]) for l in final if l["direction"] == "OUT"), 2).__float__(),
        "reconstructed_rows": sum(1 for l in final if l["provenance"] == "RECONSTRUCTION"),
        "skipped_shadow_rows": plan["skipped_shadow_rows"],
        "account_ids": sorted({l["cash_account_id"] for l in final}),
        "manifest_hash": manifest_hash,
        "started_at": now.isoformat(),
        "inserted_rows": inserted, "already_existing_rows": existing, "failed_rows": failed,
        "go_no_go": "GO" if go else "NO-GO",
        "duration_ms": int((time.monotonic() - started) * 1000),
        "blocked": blocked, "review": review,
    }
    return manifest


def _entry_values(l: dict, now, run_id) -> dict:
    """cash_ledger_entries qatori — deterministik id (uuid5 biznes-kaliti), RECONSTRUCTION provenance."""
    ent_id = uuid.uuid5(phase1._NS, f"cle:{l['tenant_id']}:{l['source_type']}:{l['source_id']}:{l['leg_index']}")
    return {
        "id": ent_id, "tenant_id": uuid.UUID(l["tenant_id"]),
        "cash_account_id": uuid.UUID(l["cash_account_id"]), "branch_id": uuid.UUID(l["account_branch_id"]),
        "account_type": "TILL", "shift_id": (uuid.UUID(l["shift_id"]) if l["shift_id"] else None),
        "posting_kind": l["posting_kind"], "source_type": l["source_type"],
        "source_id": uuid.UUID(l["source_id"]), "leg_index": l["leg_index"],
        "direction": l["direction"], "category": l["category"], "amount": _D(l["amount"]),
        "currency": l["currency"], "device_occurred_at": _ts(l["device_occurred_at"]),
        "server_received_at": now, "recorded_at": now, "actor_id": None,
        "idempotency_key": f"backfill:{run_id}:{l['plan_id']}",
        "provenance": "RECONSTRUCTION",
        "reconstruction_reason": l["reconstruction"]["reason"],
        "reconstruction_source_ref": l["reconstruction"]["source_ref"],
    }


def _negative_review(ordered_legs: list) -> list:
    """Per-account running-balance; <0 bo'lган NUQTA -> REVIEW (leg baribir yoziladi, clamp yo'q)."""
    bal: dict[str, Decimal] = {}
    out = []
    for l in ordered_legs:
        acc = l["cash_account_id"]
        cur = bal.get(acc, _D0) + (_D(l["amount"]) if l["direction"] == "IN" else -_D(l["amount"]))
        bal[acc] = cur
        if cur < 0:
            out.append({"source": l["reconstruction"]["source_ref"], "severity": "REVIEW",
                        "reason": f"historical running balance MANFIY ({cur:g}) account {acc} @ {l['device_occurred_at']} "
                                  f"— leg SODIQ yoziladi, clamp yo'q; operator ko'radi"})
    return out


def verify_backfill(db: Session, manifest: dict, *, company_id) -> dict:
    """§12 post-execution tekshiruvlari. Har bir ledger qatori manifest-legга mos bo'lishi kerak."""
    checks = {}
    q = db.query(CashLedgerEntry).filter(CashLedgerEntry.provenance == "RECONSTRUCTION")
    if company_id is not None:
        q = q.filter(CashLedgerEntry.tenant_id == company_id)
    rows = q.all()
    # no duplicate business keys
    keys = [(r.tenant_id, r.source_type, r.source_id, r.leg_index) for r in rows]
    checks["no_duplicate_business_keys"] = len(keys) == len(set(keys))
    # deterministic ids match
    checks["deterministic_ids"] = all(
        r.id == uuid.uuid5(phase1._NS, f"cle:{r.tenant_id}:{r.source_type}:{r.source_id}:{r.leg_index}") for r in rows)
    # tenant isolation
    checks["tenant_isolation"] = (company_id is None) or all(r.tenant_id == company_id for r in rows)
    # counts + totals match manifest
    checks["row_count_matches"] = len(rows) == manifest["inserted_rows"] + manifest["already_existing_rows"]
    ins = sum(_D(r.amount) for r in rows if r.direction == "IN")
    outs = sum(_D(r.amount) for r in rows if r.direction == "OUT")
    checks["in_total_matches"] = abs(float(ins) - manifest["in_total"]) < 0.005
    checks["out_total_matches"] = abs(float(outs) - manifest["out_total"]) < 0.005
    # §16 topilma: HAQIQIY soya-tekshiruv — yozilган CASH_OP leg'ining source_id'si SOYA CashMovement
    # bo'lmasligi kerak (soya = reason-prefiks + client_uuid NULL). Aks holда double-count.
    # §16-review topilma: soya (TYPE, prefiks) juftligiga scope qilinishi SHART — planner
    # (_is_shadow/_mv_count) faqat payout+{Qaytarish,Ta'minotchi·} va payin+{Qarz to'lovi·}'ni soya
    # deydi. TYPE'siz faqat prefiks bo'lsa, prefiksga tasodifan mos genuine expense/collection/
    # non-Qarz-payin (masalan reason "Qaytarish tovar buzuq" li EXPENSE) yolg'on "sizib chiqqan soya"
    # deb belgilanib, toza run'da all_ok=False bo'lardi. Planner konstantalarini QAYTA ISHLATAMIZ (drift yo'q).
    from sqlalchemy import and_ as _and, or_ as _or
    _pairs = ((CashMovementType.payout, phase1._SHADOW_PAYOUT_PREFIX),
              (CashMovementType.payin, phase1._SHADOW_PAYIN_PREFIX))
    shadow_ids = {str(r[0]) for r in db.query(CashMovement.id).filter(
        CashMovement.client_uuid.is_(None),
        _or(*[_and(CashMovement.type == mt, _or(*[CashMovement.reason.like(p + "%") for p in prefixes]))
              for mt, prefixes in _pairs])).all()}
    cashop_src = {str(r.source_id) for r in rows if r.source_type == "CASH_OP"}
    checks["no_shadow_leg_leaked"] = len(cashop_src & shadow_ids) == 0
    # all rows RECONSTRUCTION + reason/source_ref present (cle_recon_prov)
    checks["all_reconstruction_metadata"] = all(
        r.provenance == "RECONSTRUCTION" and r.reconstruction_reason and r.reconstruction_source_ref for r in rows)
    checks["all_ok"] = all(v for v in checks.values())
    return checks


def reconcile_backfill(db: Session, *, company_id, t0: str | None = None) -> dict:
    """§13 reconciliation: legacy-derived expected (< t0, backfill'га mos) vs ledger, per account + overall.
    t0 backfill bilan BIR XIL bo'lishi kerak — aks holда T0'дан keyingi (deferred) hodisalar SOXTA delta
    berardi. Delta + unexplained (approved==inserted bo'lса 0)."""
    plan = phase1.plan_backfill(db, company_id=company_id, t0=t0)   # legacy-derived expected (< t0)
    exp_in = _D(plan["in_total"]); exp_out = _D(plan["out_total"])
    q = db.query(CashLedgerEntry.direction, func.coalesce(func.sum(CashLedgerEntry.amount), 0)).filter(
        CashLedgerEntry.provenance == "RECONSTRUCTION")
    if company_id is not None:
        q = q.filter(CashLedgerEntry.tenant_id == company_id)
    led = {d: _D(a) for d, a in q.group_by(CashLedgerEntry.direction).all()}
    led_in = led.get("IN", _D0); led_out = led.get("OUT", _D0)
    # per-account
    per = {}
    aq = db.query(CashLedgerEntry.cash_account_id, CashLedgerEntry.direction,
                  func.coalesce(func.sum(CashLedgerEntry.amount), 0)).filter(
        CashLedgerEntry.provenance == "RECONSTRUCTION")
    if company_id is not None:
        aq = aq.filter(CashLedgerEntry.tenant_id == company_id)
    for acc, d, a in aq.group_by(CashLedgerEntry.cash_account_id, CashLedgerEntry.direction).all():
        per.setdefault(str(acc), {"IN": 0.0, "OUT": 0.0})[d] = float(_D(a))
    return {
        "expected_in": float(exp_in), "expected_out": float(exp_out),
        "ledger_in": float(led_in), "ledger_out": float(led_out),
        "delta_in": float(led_in - exp_in), "delta_out": float(led_out - exp_out),
        "per_account": per,
        "unexplained_delta": float((led_in - exp_in) - (led_out - exp_out)),
        "note": "delta_in/out = ledger - legacy-expected. Approved==inserted bo'lса 0 (skipped=already-existing).",
    }
