# -*- coding: utf-8 -*-
"""Darvozalar — FAIL-CLOSED.

APPLY (yozuv) faqat quyidagilarning HAMMASI bajarilganda:
  1. muhit o'zini ATAYLAB `dev`/`test`/`staging` deb e'lon qilgan (APP_ENV allowlist);
  2. platforma (RAILWAY_ENVIRONMENT_NAME) production EMAS;
  3. Postgres bo'lsa: `system_identifier` production ro'yxatida EMAS (Phase 5A: qat'iy, override YO'Q);
  4. Postgres bo'lsa: `system_identifier` production BO'LMAGAN klasterlarning ANIQ RUXSAT ro'yxatida
     (kodda: staging; qo'shimcha — faqat `MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS` orqali, vaqtinchalik
     mahalliy/CI klonlari uchun). Production qayta yaratilsa (dump/restore -> yangi sysid) u ro'yxatda
     bo'lmaydi va apply RAD etiladi — denylist yolg'iz to'siq emas;
  5. Postgres bo'lsa: operator KUTILGAN `system_identifier`ni ANIQ bergan va u ulangan bazaga teng;
  6. operator ko'rib chiqqan hisobot AYNAN shu bazada (sysid + baza nomi) tayyorlangan.
  5–6-shartlar operatorning izchilligini isbotlaydi (xato bazaga ulanish), production EMASligini emas —
  buni 3–4-shartlar beradi.

QURUQ YURISH (o'qish) har qanday muhitda ruxsat, lekin sessiya DB darajasida read-only bo'lishi
SHART: ijobiy dalil (PG `transaction_read_only=on` + izolyatsiya; SQLite `query_only=1`) VA negativ
nazorat (hech narsaga tegmaydigan UPDATE AYNAN read-only xatosi bilan rad etilishi). Boshqa har
qanday xato (qulf, jadval yo'q, huquq yo'q, vaqt tugashi) — ISBOT EMAS, quruq yurish to'xtaydi.
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import os

from . import NON_PRODUCTION_SYSTEM_IDENTIFIERS, PRODUCTION_SYSTEM_IDENTIFIERS

APPLY_ALLOWED_ENVS = frozenset({"dev", "test", "staging"})
PG_READ_ONLY_SQLSTATE = "25006"                 # read_only_sql_transaction


class ApplyForbidden(PermissionError):
    """Bu muhitda / bu bazada apply taqiqlangan."""


def allowed_system_identifiers() -> frozenset[str]:
    extra = {x.strip() for x in (os.getenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS") or "").split(",") if x.strip()}
    return frozenset(NON_PRODUCTION_SYSTEM_IDENTIFIERS | extra) - PRODUCTION_SYSTEM_IDENTIFIERS


def environment_allows_apply() -> tuple[bool, str]:
    from app.services.catalog_reset import environment_name, platform_environment_name
    env, plat = environment_name(), platform_environment_name()
    if env not in APPLY_ALLOWED_ENVS:
        return False, f"APP_ENV='{env}' ruxsat ro'yxatida emas {sorted(APPLY_ALLOWED_ENVS)}"
    if plat in {"prod", "production"}:
        return False, f"platforma muhiti '{plat}'"
    return True, f"APP_ENV={env}, platforma={plat}"


def database_identity(db: Session) -> dict:
    dialect = db.get_bind().dialect.name
    out = {"dialect": dialect, "system_identifier": None, "database": None}
    if dialect == "postgresql":
        out["system_identifier"] = str(db.execute(text("SELECT system_identifier::text FROM pg_control_system()")).scalar())
        out["database"] = str(db.execute(text("SELECT current_database()")).scalar())
    return out


def assert_apply_allowed(db: Session, expect_system_identifier: str | None = None,
                         reviewed_database: dict | None = None) -> dict:
    ok, why = environment_allows_apply()
    if not ok:
        raise ApplyForbidden(f"APPLY taqiqlangan: {why}")
    ident = database_identity(db)
    sysid = ident["system_identifier"]
    if ident["dialect"] == "postgresql":
        if sysid in PRODUCTION_SYSTEM_IDENTIFIERS:
            raise ApplyForbidden(f"APPLY taqiqlangan: production bazasi (system_identifier {sysid}) — Phase 5A")
        if sysid not in allowed_system_identifiers():
            raise ApplyForbidden(f"APPLY taqiqlangan: system_identifier {sysid} production bo'lmagan klasterlar "
                                 "ruxsat ro'yxatida yo'q")
        if not expect_system_identifier:
            raise ApplyForbidden("APPLY: --expect-system-identifier MAJBURIY (Postgres) — maqsad baza ANIQ aytilishi kerak")
        if sysid != str(expect_system_identifier).strip():
            raise ApplyForbidden(f"APPLY taqiqlangan: kutilgan baza {expect_system_identifier}, ulangan {sysid}")
        rd = reviewed_database if isinstance(reviewed_database, dict) else {}
        if rd.get("system_identifier") != sysid or rd.get("database") != ident["database"]:
            raise ApplyForbidden("APPLY taqiqlangan: ko'rib chiqilgan hisobot BOSHQA bazada tayyorlangan "
                                 f"(hisobot {rd.get('system_identifier')}/{rd.get('database')}, "
                                 f"ulangan {sysid}/{ident['database']})")
        if db.execute(text("SHOW transaction_read_only")).scalar() == "on":
            raise ApplyForbidden("APPLY: sessiya read-only — yozib bo'lmaydi")
    else:
        if expect_system_identifier:
            raise ApplyForbidden(f"APPLY: {ident['dialect']} bazasida system_identifier yo'q — kutilgan qiymat mos emas")
        if isinstance(reviewed_database, dict) and reviewed_database.get("dialect") not in (None, ident["dialect"]):
            raise ApplyForbidden("APPLY taqiqlangan: ko'rib chiqilgan hisobot boshqa turdagi bazada tayyorlangan")
    return {"environment": why, **ident}


def _is_read_only_error(dialect: str, e: DBAPIError) -> bool:
    orig = getattr(e, "orig", None)
    if dialect == "postgresql":
        return getattr(orig, "sqlstate", None) == PG_READ_ONLY_SQLSTATE
    if dialect == "sqlite":
        code = getattr(orig, "sqlite_errorcode", None)
        if code is not None:
            return code == sqlite3.SQLITE_READONLY
        return isinstance(orig, sqlite3.OperationalError) and "readonly database" in str(orig)
    return False


def prove_read_only(db: Session) -> dict:
    """Ijobiy dalil + negativ nazorat. Isbot bo'lmasa PermissionError — quruq yurish TO'XTAYDI."""
    dialect = db.get_bind().dialect.name
    evidence: dict = {"dialect": dialect}
    if dialect == "postgresql":
        evidence["transaction_read_only"] = db.execute(text("SHOW transaction_read_only")).scalar()
        evidence["transaction_isolation"] = db.execute(text("SHOW transaction_isolation")).scalar()
        if evidence["transaction_read_only"] != "on":
            raise PermissionError(f"READ-ONLY isbotlanmadi: transaction_read_only={evidence['transaction_read_only']}")
    elif dialect == "sqlite":
        evidence["query_only"] = int(db.execute(text("PRAGMA query_only")).scalar() or 0)
        if evidence["query_only"] != 1:
            raise PermissionError("READ-ONLY isbotlanmadi: PRAGMA query_only o'chiq")
    else:
        raise PermissionError(f"READ-ONLY isboti {dialect} uchun yo'q")
    db.execute(text("SAVEPOINT m1c_ro_probe"))            # yiqilsa — istisno (yashirilmaydi)
    try:
        db.execute(text("UPDATE companies SET code = code WHERE 1 = 0"))
    except DBAPIError as e:
        db.execute(text("ROLLBACK TO SAVEPOINT m1c_ro_probe"))
        if not _is_read_only_error(dialect, e):
            raise PermissionError(f"READ-ONLY isboti NOANIQ: yozuv boshqa sabab bilan yiqildi "
                                  f"({type(getattr(e, 'orig', e)).__name__}: {getattr(e, 'orig', e)})") from e
        evidence["probe"] = f"rejected: {type(e.orig).__name__}" + (
            f" (SQLSTATE {PG_READ_ONLY_SQLSTATE})" if dialect == "postgresql" else "")
        evidence["enforced"] = True
        return evidence
    raise PermissionError("READ-ONLY isbotlanmadi: yozuv so'rovi rad etilmadi — quruq yurish TO'XTATILDI")
