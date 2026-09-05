# -*- coding: utf-8 -*-
"""Cash Migration CLI — umumiy yordamchilar (I/O, DB session, xavfsizlik gardlari).

Bu modul hech qanday migration mantig'iни BAJARMAYDI — u faqat CLI plumbing'ini markazlashtiradi,
shunda har bir `cash_*` driver bir xil xavfsizlik invariantlariga (sir chiqarmaslik, LEDGER_PRIMARY
yoqmaslik, default read-only) rioya qiladi.
"""
from __future__ import annotations

import json
import os
import sys
import uuid


# ── I/O ──────────────────────────────────────────────────────────────────────
def out(msg: str = "") -> None:
    print(msg)


def err(msg: str) -> None:
    print(msg, file=sys.stderr)


def emit_json(obj) -> None:
    """Struktura'ni barqaror JSON sifatida chiqaradi (default=str -> UUID/Decimal/datetime xavfsiz)."""
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str, sort_keys=True))


def parse_company_id(raw: str | None) -> uuid.UUID | None:
    """--company-id ni UUID'ga (yoki None = barcha tenant) aylantiradi. Noto'g'ri -> ValueError."""
    if raw is None or str(raw).strip() == "":
        return None
    return uuid.UUID(str(raw).strip())


# ── Sirlarsiz TARGET ma'lumoti ───────────────────────────────────────────────
def database_url_present() -> bool:
    """DATABASE_URL o'rnatilganmi — faqat mavjudlik (QIYMAT hech qachon o'qilmaydi/chop etilmaydi)."""
    return bool((os.getenv("DATABASE_URL") or "").strip())


def db_display_name(db) -> str:
    """XAVFSIZ target etiketkasi: FAQAT logik baza nomi — host/user/password/URL EMAS."""
    try:
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            return str(db.execute(text("SELECT current_database()")).scalar())
        return f"<{db.get_bind().dialect.name}>"
    except Exception:
        return "<unknown>"


def is_postgres(db) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def has_cash_schema(db) -> bool:
    if not is_postgres(db):
        return False
    from sqlalchemy import text
    return db.execute(text(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'")).first() is not None


# ── Xavfsizlik gardlari ──────────────────────────────────────────────────────
def current_cash_mode() -> str:
    """Joriy feature-gate rejimi (o'qish). LEDGER_PRIMARY guard xatosi -> '?' (fail-safe, chiqmaydi)."""
    try:
        from app.services.cash import mode
        return mode.cash_mode().value
    except Exception:
        return "?"


def guard_never_primary() -> None:
    """LEDGER_PRIMARY (cutover) muhitiga qarshi ishlashдан BOSH TORTADI. Bu CLI'lар hech qachon
    cutover qilmaydi — read-only/backfill toolingi. Mode'ни O'ZGARTIRMAYDI (faqat o'qiydi)."""
    from app.services.cash import mode
    try:
        mode.cash_mode()   # LEDGER_PRIMARY+allow bo'lса ledger_is_authority() True bo'ladi
    except Exception:
        return   # cash_mode() guard xatosi = LEDGER_PRIMARY allow-flag'siz -> primary FAOL emas
    if mode.ledger_is_authority():
        raise SystemExit(
            "REFUSED: muhit LEDGER_PRIMARY (cutover) — cash migration CLI'lари cutover muhitida "
            "ishlamaydi (faqat read-only/backfill). To'xtatildi.")


def require_postgres_cash(db) -> None:
    """Yozuv/ledger amallari uchun Postgres + cash schema SHART (aks holда fail loud)."""
    if not is_postgres(db):
        raise SystemExit(f"REFUSED: bu amal Postgres talab qiladi (joriy: {db.get_bind().dialect.name}). "
                         "Cash subsystem faqat Postgres.")
    if not has_cash_schema(db):
        raise SystemExit("REFUSED: 'cash' schema topilmadi — avval cash schema deploy qilinishi kerak.")


# ── Session hal qilish (prod = app engine; test = inyeksiya qilingan factory) ─
def get_engine_and_session(session_factory=None, engine=None):
    """(engine, Session) qaytaradi. session_factory berilса (testlar) — o'shani ishlatadi; aks holда
    app'ning global engine/SessionLocal (prod: DATABASE_URL'дан). App engine LAZY import — session_factory
    bilan chaqirilса app engine UMUMAN yaratilmaydi (test izolyatsiyasi)."""
    if session_factory is not None:
        db = session_factory()
        return (engine if engine is not None else db.get_bind()), db
    from app.db.session import SessionLocal, engine as app_engine
    return app_engine, SessionLocal()


# ── Sarlavha (sirlarsiz) ─────────────────────────────────────────────────────
_LINE = "=" * 74


def print_header(tool: str, *, mode_label: str, company_id, db, t0=None, extra: dict | None = None) -> None:
    """CLI sarlavhasi: MODE + TARGET (db nomi, tenant, T0) — SIRLARSIZ. Har run boshida chop etiladi."""
    out(_LINE)
    out(f" SavdoOS Cash Migration CLI · {tool}")
    out(f"   MODE:        {mode_label}")
    out(f"   CASH_MODE:   {current_cash_mode()}   (LEDGER_PRIMARY bu tool tomonidan HECH QACHON yoqilmaydi)")
    out(f"   TARGET DB:   {db_display_name(db)}   (host/user/parol/URL HECH QACHON chop etilmaydi)")
    out(f"   DATABASE_URL present: {str(database_url_present()).lower()}")
    out(f"   COMPANY:     {company_id if company_id is not None else 'ALL tenants'}")
    if t0 is not None:
        out(f"   T0:          {t0}")
    if extra:
        for k, v in extra.items():
            out(f"   {k}: {v}")
    out(_LINE)


def print_apply_warning(target_desc: str) -> None:
    out("")
    out("!" * 74)
    out(f"  THIS WILL WRITE TO {target_desc}.")
    out("  (Idempotent + append-only; hech qanday o'chirish/yangilash/bo'shatish amali yo'q. "
        "LEDGER_PRIMARY O'RNATILMAYDI.)")
    out("!" * 74)
    out("")


# ── Findings yordamchi ───────────────────────────────────────────────────────
def findings_to_dicts(findings) -> list[dict]:
    """Finding obyektlari (yoki allaqачон dict'lar) ro'yxatини dict ro'yxatiga aylantiradi."""
    res = []
    for f in findings:
        res.append(f.as_dict() if hasattr(f, "as_dict") else f)
    return res


def split_severity(finding_dicts: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    block = [f for f in finding_dicts if f.get("severity") == "BLOCK"]
    review = [f for f in finding_dicts if f.get("severity") == "REVIEW"]
    info = [f for f in finding_dicts if f.get("severity") not in ("BLOCK", "REVIEW")]
    return block, review, info


# Exit kodlari (barcha CLI'lар uchun umumiy shartnoma)
EXIT_OK = 0        # READY / clean / MATCH
EXIT_USAGE = 1     # noto'g'ri argument / usage xatosi
EXIT_REVIEW = 2    # REVIEW bandlari bor (bloklamaydi, lekin operator ko'radi)
EXIT_BLOCK = 3     # BLOCK / REJECTED / FAIL — davom etib bo'lmaydi
