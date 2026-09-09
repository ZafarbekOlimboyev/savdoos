# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · DB FINGERPRINT (STRICTLY READ-ONLY).

MAQSAD: bazaning "barmoq izi" — jadval sanoqlari, naqd ledger yig'indilari va eng katta vaqt
belgilari. Ikki nuqtada olinadi va SOLISHTIRILADI:

    1) backup OLINISHIDAN oldin  (manba baza)
    2) restore QILINGANDAN keyin (bir martalik tiklash bazasi)

Farq bo'lsa — tiklash ISHONCHSIZ: `restore_rehearsal` RESTORE_REHEARSAL_FAILED bilan yiqiladi.
"Backup fayli bor" DEGANI "tiklanadi" DEGANI EMAS; buni faqat solishtirish isbotlaydi.

Operator:
    python -m app.tools.db_fingerprint --json > before.json
    # ... restore ...
    python -m app.tools.db_fingerprint --json > after.json
    python -m app.tools.db_fingerprint --compare before.json after.json

XAVFSIZLIK: HECH NARSA yozmaydi (faqat SELECT); oxirida ROLLBACK+close. Sir/URL/host CHIQMAYDI.
SHAXSIY MAYDON YO'Q: mijoz/xodim ismi, telefoni, PIN, token — hech biri o'qilmaydi. Faqat
texnik sanoq/summa/vaqt.

Exit: 0 = OK (yoki --compare mos), 2 = --compare MOS EMAS, 1 = usage/xato.
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import func, inspect

from app.tools import _common as C

# ── Sanaladigan jadvallar: (etiket, model yo'li) ─────────────────────────────
# Faqat MA'NOLI biznes jadvallari. Kesh/log jadvallari ataylab yo'q (ular tiklashdan keyin
# farq qilishi TABIIY va yolg'on signal berardi).
_PUBLIC = [
    ("companies",           "app.models.org:Company"),
    ("branches",            "app.models.org:Branch"),
    ("terminals",           "app.models.org:Terminal"),
    ("employees",           "app.models.auth:Employee"),
    ("products",            "app.models.catalog:Product"),
    ("product_barcodes",    "app.models.catalog:ProductBarcode"),
    ("categories",          "app.models.catalog:Category"),
    ("customers",           "app.models.customers:Customer"),
    ("customer_payments",   "app.models.customers:CustomerPayment"),
    ("credit_transactions", "app.models.customers:CreditTransaction"),
    ("sales",               "app.models.sales:Sale"),
    ("sale_items",          "app.models.sales:SaleItem"),
    ("sale_payments",       "app.models.sales:SalePayment"),
    ("returns",             "app.models.sales:Return"),
    ("shifts",              "app.models.shifts:Shift"),
    ("cash_movements",      "app.models.shifts:CashMovement"),
    ("purchases",           "app.models.purchasing:Purchase"),
    ("purchase_items",      "app.models.purchasing:PurchaseItem"),
    ("purchase_returns",    "app.models.purchasing:PurchaseReturn"),
    ("suppliers",           "app.models.purchasing:Supplier"),
    ("supplier_payments",   "app.models.purchasing:SupplierPayment"),
    ("inventory",           "app.models.inventory:Inventory"),
    ("stock_movements",     "app.models.inventory:StockMovement"),
    ("receivings",          "app.models.receiving:Receiving"),
    ("settings",            "app.models.settings:Setting"),
]

_CASH = [
    ("cash_accounts",        "app.models.cash:CashAccount"),
    ("cash_ledger_entries",  "app.models.cash:CashLedgerEntry"),
    ("cash_shifts",          "app.models.cash:CashShift"),
    ("cash_transfers",       "app.models.cash:CashTransfer"),
    ("reconciliation_records", "app.models.cash:ReconciliationRecord"),
    ("cash_ledger_exceptions", "app.models.cash:CashLedgerException"),
]


def _model(path: str):
    mod, cls = path.split(":")
    return getattr(__import__(mod, fromlist=[cls]), cls)


def _count(db, path: str):
    """Jadval sanog'i. Jadval umuman yo'q bo'lsa None (xato EMAS) — SQLite dev'da cash yo'q."""
    try:
        return int(db.query(func.count()).select_from(_model(path)).scalar())
    except Exception:
        db.rollback()
        return None


def _max_ts(db, path: str, col: str):
    try:
        v = db.query(func.max(getattr(_model(path), col))).scalar()
        return v.isoformat() if v is not None else None
    except Exception:
        db.rollback()
        return None


def _ledger_sums(db) -> dict:
    """Ledger yig'indilari yo'nalish bo'yicha — pul MIQDORI tiklanganini isbotlaydi.
    Sanoq bir xil bo'lib summa farq qilsa (buzilgan restore) — shu yerda ushlanadi."""
    try:
        CLE = _model("app.models.cash:CashLedgerEntry")
    except Exception:
        return {}
    out = {}
    try:
        for direction, in db.query(CLE.direction).distinct().all():
            total = db.query(func.coalesce(func.sum(CLE.amount), 0)).filter(
                CLE.direction == direction).scalar()
            out[str(direction)] = str(total)
        out["_rows"] = str(db.query(func.count()).select_from(CLE).scalar())
    except Exception:
        db.rollback()
        return {}
    return out


def _fk_integrity(db) -> dict:
    """Postgres'da FK cheklovlari SONI. pg_restore FK'larni tushirib qoldirsa shu yerda ko'rinadi
    (jadval to'la, lekin bog'lanishlar yo'q — jim buzilish)."""
    if not C.is_postgres(db):
        return {"dialect": "non-postgres", "fk_constraints": None}
    from sqlalchemy import text
    try:
        n = db.execute(text(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE constraint_type='FOREIGN KEY' AND constraint_schema IN ('public','cash')")).scalar()
        return {"dialect": "postgresql", "fk_constraints": int(n)}
    except Exception:
        db.rollback()
        return {"dialect": "postgresql", "fk_constraints": None}


def build(db) -> dict:
    """Barmoq izini yig'adi. Barqaror (sort_keys) — ikki chiqishni to'g'ridan-to'g'ri solishtirsa bo'ladi."""
    insp = inspect(db.get_bind())
    fp = {
        "schema": {
            "cash_schema_present": C.has_cash_schema(db),
            "public_tables": len(insp.get_table_names()),
        },
        "integrity": _fk_integrity(db),
        "counts": {label: _count(db, path) for label, path in _PUBLIC},
        "cash_counts": {label: _count(db, path) for label, path in _CASH},
        "ledger_sums": _ledger_sums(db),
        "max_timestamps": {
            "sale_sold_at":     _max_ts(db, "app.models.sales:Sale", "sold_at"),
            "shift_opened_at":  _max_ts(db, "app.models.shifts:Shift", "opened_at"),
            "payment_paid_at":  _max_ts(db, "app.models.customers:CustomerPayment", "paid_at"),
            "ledger_created_at": _max_ts(db, "app.models.cash:CashLedgerEntry", "created_at"),
        },
    }
    return fp


# ── Solishtirish ─────────────────────────────────────────────────────────────
def _flatten(d, prefix=""):
    flat = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            flat.update(_flatten(v, key + "."))
        else:
            flat[key] = v
    return flat


def compare(before: dict, after: dict) -> tuple[bool, list[dict]]:
    """Ikki barmoq izini solishtiradi. Har FARQ qaytariladi — jimgina o'tkazib yuborilmaydi."""
    b, a = _flatten(before), _flatten(after)
    diffs = []
    for key in sorted(set(b) | set(a)):
        bv, av = b.get(key, "<MISSING>"), a.get(key, "<MISSING>")
        # `public_tables` tiklashdan keyin farq qilishi mumkin (masalan alembic_version) — LEKIN
        # jimgina o'tkazmaymiz: INFO sifatida ko'rsatamiz, xato deb sanamaymiz.
        soft = key in {"schema.public_tables"}
        if bv != av:
            diffs.append({"key": key, "before": bv, "after": av, "severity": "INFO" if soft else "MISMATCH"})
    ok = not [d for d in diffs if d["severity"] == "MISMATCH"]
    return ok, diffs


def main(argv=None, session_factory=None) -> int:
    p = argparse.ArgumentParser(
        description="SavdoOS DB barmoq izi (read-only) — backup/restore qabul testi uchun.")
    p.add_argument("--json", action="store_true", help="stdout FAQAT JSON (operator | jq qila olsin)")
    p.add_argument("--compare", nargs=2, metavar=("BEFORE.json", "AFTER.json"),
                   help="ikki barmoq izi faylini solishtiradi (bazaga ULANMAYDI)")
    args = p.parse_args(argv)

    # ── Solishtirish rejimi: bazaga umuman ulanmaydi ────────────────────────
    if args.compare:
        try:
            with open(args.compare[0], encoding="utf-8") as f:
                before = json.load(f)
            with open(args.compare[1], encoding="utf-8") as f:
                after = json.load(f)
        except OSError as e:
            print(f"XATO: barmoq izi faylini o'qib bo'lmadi: {e}", file=sys.stderr)
            return 1
        ok, diffs = compare(before.get("fingerprint", before), after.get("fingerprint", after))
        if args.json:
            C.emit_json({"ok": ok, "verdict": "RESTORE_REHEARSAL_OK" if ok else "RESTORE_REHEARSAL_FAILED",
                         "diffs": diffs})
        else:
            for d in diffs:
                print(f"  [{d['severity']}] {d['key']}: {d['before']} -> {d['after']}")
            print("MOS" if ok else "MOS EMAS — RESTORE_REHEARSAL_FAILED")
        return 0 if ok else 2

    C.set_stdout_json_only(bool(args.json))
    try:
        _engine, db = C.get_engine_and_session(session_factory)
        try:
            if not args.json:
                C.print_header("DB FINGERPRINT", mode_label="READ-ONLY", company_id=None, db=db)
            fp = build(db)
            payload = {"target_db": C.db_display_name(db), "fingerprint": fp}
            if args.json:
                C.emit_json(payload)
            else:
                for section in ("counts", "cash_counts"):
                    C.out(f"\n[{section}]")
                    for k, v in sorted(fp[section].items()):
                        C.out(f"  {k:24s} {'-' if v is None else v}")
                C.out(f"\n[ledger_sums] {fp['ledger_sums']}")
                C.out(f"[integrity]   {fp['integrity']}")
            return 0
        finally:
            db.rollback()
            db.close()
    finally:
        C.set_stdout_json_only(False)   # global bayroqni OQIZMAYMIZ (testlar aralashmasin)


if __name__ == "__main__":
    raise SystemExit(main())
