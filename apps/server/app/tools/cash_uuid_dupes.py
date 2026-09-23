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
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_uuid_dupes \\
        --apply --yes --expect-system-identifier <sarlavhadagi qiymat>

DEFAULT — FAQAT O'QISH. `--apply --yes` bo'lmasa hech narsa yozilmaydi.

TUZATISH QOIDASI (pulga TEGMAYDI):
  · Hech qanday `cash_movements` qatori O'CHIRILMAYDI va summasi o'zgartirilmaydi —
    ikkala qator ham HAQIQIY pul harakati.
  · Guruhdagi ENG ESKI qator (created_at, id) kalitni SAQLAYDI — takror so'rov
    aynan birinchi amalni nazarda tutadi.
  · Qolganlarining `client_uuid` i YANGI, DETERMINISTIK qiymatga almashtiriladi:
    `uuid5(RELEASE_NS, <qator id>)`. Qator, summasi, smenasi va ledger legi
    JOYIDA qoladi; kalit esa endi HECH QACHON to'qnashmaydi (qiymat qator id'sidan
    kelib chiqadi, mijoz uni hech qachon yubormaydi) va takror urinish idempotent.

    ⚠️  KALIT NULL QILINMAYDI. `client_uuid IS NULL` — Cash Ledger migratsiyasida
        «SOYA qator» belgisining YAGONA ajratuvchisi (`app/db/cash/migration/phase1.
        _is_shadow`: soya yozuvchilar kalit qo'ymaydi). Kalitni NULL qilish kassirning
        HAQIQIY qo'lbola amalini soyaga aylantirardi va backfill o'sha pulni ledgerga
        UMUMAN yozmasdi — izohi tasodifan `Qaytarish`/`Qarz to'lovi · ` bilan
        boshlangan har bir qator uchun (kassir izohi — ERKIN matn).
  · Tuzatishdan keyin indeks `initdb` (boot) da o'z-o'zidan quriladi; bu CLI DDL
    YUBORMAYDI (qulf olmaydi). Apply YAKUNIDA takrorlar QAYTA sanaladi: yozuvlar
    davom etayotgani uchun yangi juftlik paydo bo'lgan bo'lsa exit 2 (REVIEW).

MAQSAD BAZA DARVOZASI (Postgres'da): `--apply` uchun `--expect-system-identifier`
MAJBURIY va ulangan klasterga teng bo'lishi shart; production ko'rinishidagi maqsad
esa qo'shimcha `--allow-production` + `--confirm-production-system-identifier`
talab qiladi. Yozuv QAYTARIB BO'LMAYDI (eski kalit hech qayerda saqlanmaydi), shu
bois «qaysi klaster» savoliga taxmin bilan javob berilmaydi.

Exit: 0 = takror yo'q (yoki apply toza yakunlandi), 2 = takrorlar bor (dry-run)
yoki apply'dan keyin qolib ketdi, 1 = usage/rad etilgan apply.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import text

from app.tools import _common as C

KIND = "CASH_UUID_DUPES"
INDEX_NAME = "ux_cashmov_client_uuid_all"

# Bo'shatilgan kalitlar uchun BARQAROR ad-hoc namespace. O'ZGARMAYDI: qayta yurgizish
# AYNI qiymatni berishi (idempotentlik) shunga bog'liq.
RELEASE_NS = uuid.UUID("3f9d2b7c-5a41-4e08-9c6e-1b2f7a4d8e55")

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


def _as_uuid(v):
    """`str`/`UUID` -> `UUID` (SQLite defissiz saqlaydi, PG defis bilan)."""
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def released_key(row_id) -> uuid.UUID:
    """Yutqazgan qator uchun YANGI kalit — qator id'sidan deterministik.

    Mijoz (POS/mobil) v4 uuid yuboradi; bu qiymat esa `RELEASE_NS` + qator id'dan
    hosil bo'lgan v5, ya'ni yangi so'rov bilan to'qnashuvi amalda mumkin emas.
    Deterministikligi tufayli tool qayta yurgizilsa AYNI qiymat yoziladi."""
    return uuid.uuid5(RELEASE_NS, str(_as_uuid(row_id)))


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
    """Yutqazgan qatorlarga YANGI (deterministik) kalit beradi. Qatorlar O'CHIRILMAYDI.

    ⚠️  ORM ustuni orqali yoziladi (xom SQL emas): `client_uuid` tipi dialektga qarab
        turlicha saqlanadi (PG native uuid, SQLite CHAR(32) defissiz) va xom matn
        yozilsa keyingi solishtirishlar jimgina mos kelmay qolardi."""
    from app.models.shifts import CashMovement
    n = 0
    for g in groups:
        for rid in g["losers"]:
            db.query(CashMovement).filter(CashMovement.id == _as_uuid(rid)).update(
                {CashMovement.client_uuid: released_key(rid)}, synchronize_session=False)
            n += 1
    db.commit()
    return n


# ── MAQSAD BAZA DARVOZASI ────────────────────────────────────────────────────

def target_identity(db) -> dict:
    """Ulangan bazaning identiteti (SIRLARSIZ): dialekt, klaster, baza nomi."""
    out = {"dialect": db.get_bind().dialect.name, "system_identifier": None, "database": None}
    if C.is_postgres(db):
        out["system_identifier"] = str(db.execute(text(
            "SELECT system_identifier::text FROM pg_control_system()")).scalar())
        out["database"] = C.db_display_name(db)
    return out


def apply_refusals(ident: dict, *, env: str, platform: str, expect: str | None,
                   allow_production: bool, confirm: str | None) -> list[str]:
    """TOZA funksiya: `--apply` ni RAD etish sabablari (bo'sh ro'yxat = ruxsat).

    Naqsh `app/db/migrations/guard.write_refusals` dan olingan, IKKI ATAYLAB farq bilan:
      · ko'rib chiqilgan hisobot hash'i TALAB QILINMAYDI — bu tool bitta jadvaldagi
        kalitni aylantiradi, reja fayli yo'q (dry-run bevosita shu bazada yuritiladi);
      · muhitning O'ZINI production deb E'LON QILISHI shart emas: tuzatish AYNAN
        shu indeks yo'q bo'lgan klasterda ishlashi kerak va platforma nomiga
        tayanib operatorni boshi berk ko'chaga kiritish tayyorlikni QIZIL qoldirardi.
    SQLite (dev/demo/test) — darvoza YO'Q: production hech qachon SQLite emas."""
    from app.db.migrations import guard as _g
    out: list[str] = []
    if ident.get("dialect") != "postgresql":
        return out
    sysid = ident.get("system_identifier")
    if not expect:
        out.append("--expect-system-identifier MAJBURIY — maqsad klaster ANIQ aytilishi kerak "
                   "(qiymat sarlavhadagi TARGET CLUSTER da)")
    elif str(expect).strip() != sysid:
        out.append(f"kutilgan klaster {str(expect).strip()}, ulangani {sysid}")
    signals: list[str] = []
    if sysid in _g.PRODUCTION_SYSTEM_IDENTIFIERS:
        signals.append(f"system_identifier {sysid} production ro'yxatida")
    elif sysid not in _g.allowed_system_identifiers():
        signals.append(f"system_identifier {sysid} production BO'LMAGAN klasterlar "
                       "ruxsat ro'yxatida yo'q")
    if env not in _g.APPLY_ALLOWED_ENVS:
        signals.append(f"APP_ENV='{env}' ruxsat ro'yxatida emas {sorted(_g.APPLY_ALLOWED_ENVS)}")
    if platform in _g.PRODUCTION_ENV_NAMES:
        signals.append(f"platforma muhiti '{platform}'")
    if not signals:
        return out
    missing: list[str] = []
    if not allow_production:
        missing.append("--allow-production berilmagan")
    if not confirm:
        missing.append("--confirm-production-system-identifier MAJBURIY")
    elif str(confirm).strip() != sysid:
        missing.append(f"tasdiq mos emas ({str(confirm).strip()} ≠ {sysid})")
    if missing:
        out.append(f"PRODUCTION yo'li [{'; '.join(signals)}]: " + "; ".join(missing))
    return out


def _apply_warning() -> None:
    """`_common.print_apply_warning` NING O'RNIGA — o'sha matn «hech qanday yangilash
    amali yo'q» deydi, bu tool esa AYNAN UPDATE qiladi (operatorga yolg'on aytilmaydi)."""
    C.out("")
    C.out("!" * 74)
    C.out("  THIS WILL UPDATE cash_movements.client_uuid ON THE TARGET DATABASE.")
    C.out("  (Faqat TAKROR kalitli qatorlarning KEYINGILARIGA yangi kalit beriladi: pul, "
          "smena, ledger legi va qatorning o'zi TEGILMAYDI. Eski kalit qiymati hech "
          "qayerda saqlanmaydi — QAYTARIB BO'LMAYDI. LEDGER_PRIMARY O'RNATILMAYDI.)")
    C.out("!" * 74)
    C.out("")


def run(db, *, as_json: bool, apply: bool, yes: bool, expect=None,
        allow_production: bool = False, confirm=None) -> int:
    C.set_stdout_json_only(as_json)
    C.guard_never_primary()
    ident = target_identity(db)
    C.print_header("CASH UUID DUPES", mode_label=("APPLY" if apply else "DRY-RUN (read-only)"),
                   company_id=None, db=db,
                   extra={"TARGET CLUSTER": ident.get("system_identifier") or "—"})
    groups = scan(db)
    total_losers = sum(len(g["losers"]) for g in groups)
    report = {"kind": KIND, "index": INDEX_NAME, "duplicate_keys": len(groups),
              "rows_to_free": total_losers, "groups": groups, "applied": False,
              "target": ident}

    if not groups:
        if as_json:
            C.emit_json(report)
        C.out("Takror `client_uuid` YO'Q — indeks qurilishiga to'siq yo'q.")
        return C.EXIT_OK

    if apply:
        from app.db.migrations.guard import environment_names
        env, platform = environment_names()
        refusals = ([] if yes else ["--apply uchun --yes ham kerak (yozuvni tasdiqlaysiz)"])
        refusals += apply_refusals(ident, env=env, platform=platform, expect=expect,
                                   allow_production=allow_production, confirm=confirm)
        if refusals:
            report["refusals"] = refusals
            if as_json:
                C.emit_json(report)
            for r in refusals:
                C.err(f"REFUSED: {r}")
            return C.EXIT_USAGE
        _apply_warning()
        freed = repair(db, groups)
        # ⚠️  TEKSHIRUV APPLY'DAN KEYIN. `scan()` qulfsiz o'qiydi va indeks hali yo'q —
        #     ya'ni scan bilan repair orasida kelgan POS/mobil yozuvi YANGI takror
        #     qoldirishi mumkin. «Tuzatildi, servisni qayta ishga tushiring» deb exit 0
        #     berish operatorni indeks baribir qurilmaydigan holatga olib borardi.
        qolgan = scan(db)
        db.rollback()                       # tekshiruv — FAQAT o'qish
        report["applied"] = True
        report["rows_freed"] = freed
        report["remaining_duplicate_keys"] = len(qolgan)
        report["remaining_groups"] = qolgan
        if as_json:
            C.emit_json(report)
        C.out(f"TUZATILDI: {freed} qatorning kaliti yangilandi ({len(groups)} guruh). "
              f"Pul, smena va ledger legi TEGILMADI.")
        if qolgan:
            C.err(f"DIQQAT: {len(qolgan)} takror guruh QOLDI (tuzatish paytida yangi "
                  f"yozuvlar kelgan bo'lishi mumkin) — `{INDEX_NAME}` HALI qurilmaydi. "
                  "Yozuvlarni to'xtatib, toolni QAYTA yurgizing.")
            return C.EXIT_REVIEW
        C.out(f"Takror qolmadi. Endi servisni qayta ishga tushiring — `{INDEX_NAME}` "
              "boot'da quriladi.")
        return C.EXIT_OK

    if as_json:
        C.emit_json(report)
    C.out(f"TAKROR KALITLAR: {len(groups)} guruh, {total_losers} qator kalitni bo'shatishi kerak.")
    for g in groups[:20]:
        C.out(f"  {g['client_uuid']}  qatorlar={g['rows']}  saqlanadi={g['keeper']}")
    if len(groups) > 20:
        C.out(f"  … yana {len(groups) - 20} guruh (--json to'liq ro'yxatni beradi)")
    C.out("")
    C.out("TUZATISH (pulga tegmaydi, faqat kalitni aylantiradi):")
    C.out("  python -m app.tools.cash_uuid_dupes --apply --yes" + (
        f" --expect-system-identifier {ident['system_identifier']}"
        if ident.get("system_identifier") else ""))
    return C.EXIT_REVIEW


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m app.tools.cash_uuid_dupes",
        description=f"`{INDEX_NAME}` qurilishiga to'sqinlik qiladigan takror kalitlar.")
    p.add_argument("--json", action="store_true", help="Hisobotni JSON sifatida chiqarish.")
    p.add_argument("--apply", action="store_true",
                   help="Yutqazgan qatorlarga YANGI kalit berish (--yes bilan).")
    p.add_argument("--yes", action="store_true", help="--apply ni tasdiqlash.")
    p.add_argument("--expect-system-identifier", default=None,
                   help="Maqsad klaster (Postgres'da --apply uchun MAJBURIY).")
    p.add_argument("--allow-production", action="store_true",
                   help="Production ko'rinishidagi maqsadga yozishga ruxsat.")
    p.add_argument("--confirm-production-system-identifier", default=None,
                   help="Production maqsadni AYNAN tasdiqlash (klaster id).")
    args = p.parse_args(argv)
    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, as_json=args.json, apply=args.apply, yes=args.yes,
                   expect=args.expect_system_identifier,
                   allow_production=args.allow_production,
                   confirm=args.confirm_production_system_identifier)
    finally:
        if not args.apply:
            db.rollback()
        db.close()
        C.set_stdout_json_only(False)


if __name__ == "__main__":
    sys.exit(main())
