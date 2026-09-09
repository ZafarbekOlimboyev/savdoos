# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · LEDGER BUTUNLIGI PROBE (STRICTLY READ-ONLY).

SAVOL: **ledger-native** do'konda fizik naqd manba qatori COMMIT bo'lib, unga TEGISHLI ledger
legi YOZILMAY qolgan holat bormi?

Tranzaksiya yo'llari buni allaqachon BALAND xato bilan to'xtatadi (manba + leg BIR
tranzaksiyada). Bu probe esa FAKTDAN KEYIN tekshiradi — chunki "hech qachon bo'lmaydi" degan
invariantni HECH KIM tekshirmasa, u buzilganini ham hech kim bilmaydi. Deploy nosozligi,
qo'lda SQL, yoki kelajakdagi regressiya aynan shu jimgina holatni yaratishi mumkin.

`cash_reconcile_probe` DAN FARQI (takrorlash EMAS):
    cash_reconcile_probe — MIGRATSIYA savoli: legacy qator backfill qilinishga layoqatlimi,
                           tarixiy TILL dalili bormi. Manbalar: CustomerPayment / SupplierPayment
                           / Return. LEGACY tenantlar uchun.
    BU PROBE          — LEDGER-NATIVE invariant: manba bor, leg YO'Q. Manbalar: naqd SAVDO,
                           naqd XARID, qarz to'lovi, naqd QAYTARISH, kassa harakatlari.
                           Tarix yoki backfill bilan UMUMAN ishi yo'q.

Operator:
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_integrity_probe --json
    # faqat bitta do'kon:  --company-id <uuid>
    # oyna:                --days 7   (standart: 7 kun; 0 = cutover_at dan beri)

XAVFSIZLIK: HECH NARSA yozmaydi (faqat SELECT); oxirida ROLLBACK+close. Shaxsiy maydon
CHIQMAYDI — faqat texnik id/summa/vaqt.

Exit: 0 = butunlik SAQLANGAN, 2 = KAMIDA BITTA yetishmayotgan leg (TEKSHIRISH SHART), 1 = usage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.models.cash import CashLedgerEntry as CLE
from app.models.customers import Customer, CustomerPayment
from app.models.enums import SaleStatus
from app.models.org import Branch, Company
from app.models.purchasing import Purchase, PurchaseStatus
from app.models.sales import Return, Sale, SalePayment
from app.models.shifts import CashMovement, Shift
from app.services.cash import cutover as _cut
from app.services.cash import tenant as _tn
from app.tools import _common as C


def _ledger_source_ids(db, tenant_id, source_type: str, since) -> set:
    """Shu tenant/tur uchun ledgerda MAVJUD manba id'lari."""
    rows = db.execute(
        select(CLE.source_id).where(
            CLE.tenant_id == tenant_id,
            CLE.source_type == source_type,
            CLE.recorded_at >= since,
        ).distinct()
    ).all()
    return {r[0] for r in rows}


def _check_company(db, company, since) -> dict:
    """Bitta do'kon uchun barcha naqd manbalarini tekshiradi."""
    cid = company.id
    findings: list[dict] = []
    scanned = {}

    def _add(kind, sid, when, amount, extra=None):
        findings.append({
            "kind": kind, "source_id": str(sid),
            "occurred_at": when.isoformat() if when is not None else None,
            "amount": str(amount) if amount is not None else None,
            **(extra or {}),
        })

    # ── 1) NAQD SAVDO -> SALE ───────────────────────────────────────────────
    have = _ledger_source_ids(db, cid, "SALE", since)
    rows = db.execute(
        select(Sale.id, Sale.sold_at, func.sum(SalePayment.amount))
        .join(SalePayment, SalePayment.sale_id == Sale.id)
        .where(Sale.company_id == cid, Sale.sold_at >= since,
               Sale.status != SaleStatus.voided,
               SalePayment.method_code == "cash")
        .group_by(Sale.id, Sale.sold_at)
    ).all()
    scanned["cash_sale"] = len(rows)
    for sid, when, amt in rows:
        if sid not in have:
            _add("cash_sale", sid, when, amt)

    # ── 2) NAQD XARID -> PURCHASE ───────────────────────────────────────────
    have = _ledger_source_ids(db, cid, "PURCHASE", since)
    rows = db.execute(
        select(Purchase.id, Purchase.created_at, Purchase.total)
        .join(Branch, Branch.id == Purchase.branch_id)
        .where(Branch.company_id == cid, Purchase.created_at >= since,
               Purchase.status == PurchaseStatus.received)
    ).all()
    scanned["cash_purchase"] = len(rows)
    for sid, when, amt in rows:
        if sid not in have:
            _add("cash_purchase", sid, when, amt)

    # ── 3) QARZ TO'LOVI (naqd) -> CUSTOMER_PAYMENT ──────────────────────────
    have = _ledger_source_ids(db, cid, "CUSTOMER_PAYMENT", since)
    rows = db.execute(
        select(CustomerPayment.id, CustomerPayment.paid_at, CustomerPayment.amount)
        .join(Customer, Customer.id == CustomerPayment.customer_id)
        .where(Customer.company_id == cid, CustomerPayment.paid_at >= since,
               CustomerPayment.method == "cash")
    ).all()
    scanned["debt_payment"] = len(rows)
    for sid, when, amt in rows:
        if sid not in have:
            _add("debt_payment", sid, when, amt)

    # ── 4) NAQD QAYTARISH -> RETURN ─────────────────────────────────────────
    have = _ledger_source_ids(db, cid, "RETURN", since)
    rows = db.execute(
        select(Return.id, Return.created_at, Return.total)
        .where(Return.company_id == cid, Return.created_at >= since,
               Return.refund_method == "cash")
    ).all()
    scanned["cash_refund"] = len(rows)
    for sid, when, amt in rows:
        if sid not in have:
            _add("cash_refund", sid, when, amt)

    # ── 5) KASSA HARAKATLARI -> CASH_OP / TRANSFER ──────────────────────────
    # Inkassa (collection) juft o'tkazma bo'lib TRANSFER sifatida yoziladi, qolganlari CASH_OP.
    have = _ledger_source_ids(db, cid, "CASH_OP", since) | _ledger_source_ids(db, cid, "TRANSFER", since)
    rows = db.execute(
        select(CashMovement.id, CashMovement.created_at, CashMovement.amount, CashMovement.type)
        .join(Shift, Shift.id == CashMovement.shift_id)
        .join(Branch, Branch.id == Shift.branch_id)
        .where(Branch.company_id == cid, CashMovement.created_at >= since)
    ).all()
    scanned["cash_movement"] = len(rows)
    for sid, when, amt, mtype in rows:
        if sid not in have:
            _add("cash_movement", sid, when, amt, {"movement_type": str(getattr(mtype, "value", mtype))})

    return {
        "company_id": str(cid),
        "code": company.code,
        "name": company.name,
        "ledger_native": True,
        "window_since": since.isoformat(),
        "scanned": scanned,
        "missing_legs": findings,
        "verdict": "INTEGRITY_OK" if not findings else "MISSING_LEDGER_LEGS",
    }


def main(argv=None, session_factory=None) -> int:
    p = argparse.ArgumentParser(
        description="Ledger-native do'konlarda 'manba bor, leg yo'q' holatini topadi (read-only).")
    p.add_argument("--json", action="store_true", help="stdout FAQAT JSON")
    p.add_argument("--company-id", default=None, help="faqat shu do'kon (standart: barchasi)")
    p.add_argument("--days", type=int, default=7,
                   help="necha kunlik oyna (standart 7). 0 = cutover_at dan beri.")
    args = p.parse_args(argv)

    C.set_stdout_json_only(bool(args.json))
    try:
        try:
            only = C.parse_company_id(args.company_id)
        except ValueError:
            C.err("--company-id noto'g'ri UUID"); return 1

        _engine, db = C.get_engine_and_session(session_factory)
        try:
            if not C.is_postgres(db):
                C.err("REFUSED: cash quyi tizimi faqat Postgres'da. To'xtatildi.")
                return 1
            if not args.json:
                C.print_header("CASH INTEGRITY PROBE", mode_label="READ-ONLY",
                               company_id=only, db=db)

            comps = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.code).all()
            if only is not None:
                comps = [c for c in comps if c.id == only]

            results, skipped = [], []
            now = datetime.now(timezone.utc)
            for c in comps:
                # FAQAT ledger-native do'konlar. Legacy tenantda "leg yo'q" NORMAL holat
                # (ular migratsiya qilinmagan) — ularni bu yerda xato deb ko'rsatish
                # YOLG'ON signal bo'lardi.
                if not _tn.is_ledger_native(db, c.id):
                    skipped.append({"company_id": str(c.id), "code": c.code, "reason": "legacy_tenant"})
                    continue
                if args.days and args.days > 0:
                    since = now - timedelta(days=args.days)
                else:
                    since = _cut.cutover_at(db, c.id) or (now - timedelta(days=3650))
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                results.append(_check_company(db, c, since))

            bad = [r for r in results if r["missing_legs"]]
            payload = {
                "verdict": "INTEGRITY_OK" if not bad else "MISSING_LEDGER_LEGS",
                "ledger_native_companies": len(results),
                "skipped_legacy": skipped,
                "companies_with_missing_legs": len(bad),
                "results": results,
            }
            if args.json:
                C.emit_json(payload)
            else:
                for r in results:
                    C.out(f"\n[{r['code']}] {r['verdict']}  (oyna: {r['window_since']})")
                    C.out(f"   ko'rildi: {r['scanned']}")
                    for f in r["missing_legs"][:20]:
                        C.out(f"   !! LEG YO'Q  {f['kind']:14s} {f['source_id']}  {f['amount']}  {f['occurred_at']}")
                    if len(r["missing_legs"]) > 20:
                        C.out(f"   ... yana {len(r['missing_legs']) - 20} ta")
                if skipped:
                    C.out(f"\n(legacy tenantlar o'tkazib yuborildi: {len(skipped)})")
                C.out("\n" + payload["verdict"])
            return 0 if not bad else 2
        finally:
            db.rollback()
            db.close()
    finally:
        C.set_stdout_json_only(False)


if __name__ == "__main__":
    raise SystemExit(main())
