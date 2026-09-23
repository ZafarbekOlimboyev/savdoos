# -*- coding: utf-8 -*-
"""Kassa idempotentlik kalitlari · TAKRORLARNI KO'RISH va (ixtiyoriy) TUZATISH.

Nima uchun: `ux_cashmov_client_uuid_all` — `cash_movements (client_uuid)` bo'yicha
JADVAL BO'YLAB noyob qisman indeks. U `/cash/ops` va `POST /shifts/{id}/cash`
takrorlarining YAGONA tranzaksion to'sig'i (kod darajasidagi SELECT-dedup parallel
ikki takrorga chidamli emas). ESKI bazada bu indeks BO'LMAGAN — o'shanda noyoblik
`(shift_id, client_uuid)` edi, ya'ni AYNI kalit IKKI smenada yonma-yon yashashi
MUMKIN edi. Shunday qator juftligi bo'lsa yangi indeks QURILMAYDI (`_index()`
uni jimgina o'tkazib yuboradi) va `/health/ready` «idempotentlik indeksi yo'q»
deb QIZIL qoladi.

Operator (Railway'da):
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_uuid_dupes
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_uuid_dupes --json
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_uuid_dupes --apply --yes

DEFAULT — FAQAT O'QISH. `--apply --yes` bo'lmasa hech narsa yozilmaydi.

TUZATISH QOIDASI (pulga TEGMAYDI):
  · Hech qanday `cash_movements` qatori O'CHIRILMAYDI va summasi o'zgartirilmaydi —
    ikkala qator ham HAQIQIY pul harakati.
  · Guruhdagi ENG ESKI qator (created_at, id) kalitni SAQLAYDI — takror so'rov
    aynan birinchi amalni nazarda tutadi.
  · Qolganlarining `client_uuid` i NULL ga o'tkaziladi: qator, summasi, smenasi va
    ledger legi JOYIDA qoladi, faqat idempotentlik kaliti bo'shaydi. Bu tarixiy
    (allaqachon yozilgan) amal uchun takror himoyasini yo'qotadi — yangi so'rovlar
    baribir yangi kalit bilan keladi.
  · Tuzatishdan keyin indeks `initdb` (boot) da o'z-o'zidan quriladi; bu CLI DDL
    YUBORMAYDI (qulf olmaydi).

Exit: 0 = takror yo'q (yoki apply muvaffaqiyatli), 2 = takrorlar bor (dry-run),
1 = usage/rad etilgan apply.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.tools import _common as C

KIND = "CASH_UUID_DUPES"
INDEX_NAME = "ux_cashmov_client_uuid_all"

_GROUPS_SQL = """
SELECT client_uuid, COUNT(*) AS n
  FROM cash_movements
 WHERE client_uuid IS NOT NULL
 GROUP BY client_uuid
HAVING COUNT(*) > 1
 ORDER BY n DESC, client_uuid
"""

# Guruh ichidagi qatorlar — eng eskisi BIRINCHI (u kalitni saqlaydi).
_ROWS_SQL = """
SELECT id, shift_id, type, amount, created_at
  FROM cash_movements
 WHERE client_uuid = :u
 ORDER BY created_at, id
"""


def scan(db) -> list[dict]:
    """Takror kalit guruhlari — FAQAT SELECT. Sir yoki shaxsiy ma'lumot chiqarmaydi."""
    out = []
    for key, n in db.execute(text(_GROUPS_SQL)).fetchall():
        rows = db.execute(text(_ROWS_SQL), {"u": str(key)}).fetchall()
        out.append({
            "client_uuid": str(key),
            "rows": int(n),
            "keeper": str(rows[0][0]) if rows else None,
            "losers": [str(r[0]) for r in rows[1:]],
            "movements": [{"id": str(r[0]), "shift_id": str(r[1]),
                           "type": str(getattr(r[2], "value", r[2])), "amount": str(r[3]),
                           "created_at": str(r[4])} for r in rows],
        })
    return out


def repair(db, groups: list[dict]) -> int:
    """Yutqazgan qatorlarning `client_uuid` ini NULL qiladi. Qatorlar O'CHIRILMAYDI."""
    n = 0
    for g in groups:
        for rid in g["losers"]:
            db.execute(text("UPDATE cash_movements SET client_uuid = NULL WHERE id = :i"),
                       {"i": rid})
            n += 1
    db.commit()
    return n


def run(db, *, as_json: bool, apply: bool, yes: bool) -> int:
    C.set_stdout_json_only(as_json)
    C.print_header("CASH UUID DUPES", mode_label=("APPLY" if apply else "DRY-RUN (read-only)"),
                   company_id=None, db=db)
    groups = scan(db)
    total_losers = sum(len(g["losers"]) for g in groups)
    report = {"kind": KIND, "index": INDEX_NAME, "duplicate_keys": len(groups),
              "rows_to_free": total_losers, "groups": groups, "applied": False}

    if not groups:
        if as_json:
            C.emit_json(report)
        C.out("Takror `client_uuid` YO'Q — indeks qurilishiga to'siq yo'q.")
        return C.EXIT_OK

    if apply and not yes:
        if as_json:
            C.emit_json(report)
        C.err("REFUSED: --apply uchun --yes ham kerak (yozuvni tasdiqlaysiz).")
        return C.EXIT_USAGE

    if apply:
        freed = repair(db, groups)
        report["applied"] = True
        report["rows_freed"] = freed
        if as_json:
            C.emit_json(report)
        C.out(f"TUZATILDI: {freed} qatorning kaliti bo'shatildi ({len(groups)} guruh). "
              f"Pul, smena va ledger legi TEGILMADI. Endi servisni qayta ishga tushiring — "
              f"`{INDEX_NAME}` boot'da quriladi.")
        return C.EXIT_OK

    if as_json:
        C.emit_json(report)
    C.out(f"TAKROR KALITLAR: {len(groups)} guruh, {total_losers} qator kalitni bo'shatishi kerak.")
    for g in groups[:20]:
        C.out(f"  {g['client_uuid']}  qatorlar={g['rows']}  saqlanadi={g['keeper']}")
    if len(groups) > 20:
        C.out(f"  … yana {len(groups) - 20} guruh (--json to'liq ro'yxatni beradi)")
    C.out("")
    C.out("TUZATISH (pulga tegmaydi, faqat kalitni bo'shatadi):")
    C.out("  python -m app.tools.cash_uuid_dupes --apply --yes")
    return C.EXIT_REVIEW


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m app.tools.cash_uuid_dupes",
        description=f"`{INDEX_NAME}` qurilishiga to'sqinlik qiladigan takror kalitlar.")
    p.add_argument("--json", action="store_true", help="Hisobotni JSON sifatida chiqarish.")
    p.add_argument("--apply", action="store_true",
                   help="Yutqazgan qatorlarning client_uuid ini NULL qilish (--yes bilan).")
    p.add_argument("--yes", action="store_true", help="--apply ni tasdiqlash.")
    args = p.parse_args(argv)
    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, as_json=args.json, apply=args.apply, yes=args.yes)
    finally:
        if not args.apply:
            db.rollback()
        db.close()
        C.set_stdout_json_only(False)


if __name__ == "__main__":
    sys.exit(main())
