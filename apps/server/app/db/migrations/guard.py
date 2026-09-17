# -*- coding: utf-8 -*-
"""SXEMA MIGRATSIYASI DARVOZALARI — FAIL-CLOSED.

Naqsh `app/services/migrator_1c/guard.py` dan olingan (o'sha fayl O'ZGARMAYDI): muhit
ruxsat ro'yxati, production `system_identifier` taqiq ro'yxati, production BO'LMAGAN
klasterlarning aniq ruxsat ro'yxati (+ efemer klonlar uchun env kengaytmasi), MAJBURIY
`--expect-system-identifier`, ko'rib chiqilgan hisobotning baza identiteti bilan bog'lanishi
va READ-ONLY isboti (ijobiy dalil + negativ nazorat).

YOZISH (apply/revert) ikki yo'ldan BIRI bilan:

  A) PRODUCTION BO'LMAGAN YO'L — quyidagilarning HAMMASI:
     1. `APP_ENV` ANIQ `dev`/`test`/`staging` (yo'q/bo'sh/noma'lum — RAD);
     2. platforma (`RAILWAY_ENVIRONMENT_NAME`) production EMAS;
     3. `system_identifier` production taqiq ro'yxatida EMAS (kodda qat'iy, override YO'Q);
     4. `system_identifier` ruxsat ro'yxatida (kodda: staging; efemer klon/CI uchun
        `SAVDOOS_SCHEMA_MIGRATE_ALLOWED_SYSTEM_IDENTIFIERS`).

  B) PRODUCTION YO'LI — yuqoridagilardan birortasi bajarilmasa, apply RAD etiladi, agar
     operator AYNI vaqtda quyidagilarni BERMAGAN bo'lsa:
     1. `--allow-production`;
     2. `--confirm-production-system-identifier` == ULANGAN bazaning sysid'i;
     3. muhit O'ZI production deb e'lon qilingan: `APP_ENV` VA platforma ikkalasi ham
        `prod`/`production`. «Production signali yo'qligi» production emasligini ANGLATMAYDI,
        teskarisi ham: production bazasiga «dev» niqobi ostida yozib bo'lmaydi.

HAR IKKI yo'lda ham (Postgres): `--expect-system-identifier` MAJBURIY va ulangan bazaga teng;
ko'rib chiqilgan hisobot AYNAN shu bazada (sysid + baza nomi) tayyorlangan; sessiya read-only EMAS.
"""
from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .contract import MigrationError

# Bu klasterlarga migratsiya APPLY hech qachon «production bo'lmagan yo'l» bilan o'tmaydi.
PRODUCTION_SYSTEM_IDENTIFIERS = frozenset({"7674898282858840119"})
# Production BO'LMAGAN, ANIQ ruxsat etilgan klasterlar — staging demo bazasi.
NON_PRODUCTION_SYSTEM_IDENTIFIERS = frozenset({"7683497876193431618"})
# Efemer klon (restore mashqi, CI, mahalliy) uchun vaqtinchalik kengaytma.
ALLOWED_SYSTEM_IDENTIFIERS_ENV = "SAVDOOS_SCHEMA_MIGRATE_ALLOWED_SYSTEM_IDENTIFIERS"

APPLY_ALLOWED_ENVS = frozenset({"dev", "test", "staging"})
PRODUCTION_ENV_NAMES = frozenset({"prod", "production"})
PG_READ_ONLY_SQLSTATE = "25006"                 # read_only_sql_transaction
APPLICATION_NAME = "savdoos_schema_migrate"


class MigrationForbidden(MigrationError):
    """Bu muhitda / bu bazada migratsiya yozuvi TAQIQLANGAN."""


def allowed_system_identifiers() -> frozenset[str]:
    """Ruxsat ro'yxati + env kengaytmasi − production taqiq ro'yxati (kengaytma production'ni
    HECH QACHON qaytara olmaydi)."""
    raw = os.getenv(ALLOWED_SYSTEM_IDENTIFIERS_ENV) or ""
    extra = {x.strip() for x in raw.split(",") if x.strip()}
    return frozenset(NON_PRODUCTION_SYSTEM_IDENTIFIERS | extra) - PRODUCTION_SYSTEM_IDENTIFIERS


def environment_names() -> tuple[str, str]:
    """(APP_ENV, platforma) — aniqlanmasa `"unknown"` (fail-closed, `catalog_reset` bilan ayni)."""
    from app.services.catalog_reset import environment_name, platform_environment_name
    return environment_name(), platform_environment_name()


def database_identity(con) -> dict:
    """Ulangan bazaning identiteti — QULFSIZ, faqat katalog funksiyalari."""
    dialect = con.engine.dialect.name if hasattr(con, "engine") else con.get_bind().dialect.name
    out = {"dialect": dialect, "system_identifier": None, "database": None,
           "server_version_num": None, "current_user": None}
    if dialect == "postgresql":
        out["system_identifier"] = str(con.execute(
            text("SELECT system_identifier::text FROM pg_control_system()")).scalar())
        out["database"] = str(con.execute(text("SELECT current_database()")).scalar())
        out["server_version_num"] = int(con.execute(text("SHOW server_version_num")).scalar())
        out["current_user"] = str(con.execute(text("SELECT current_user")).scalar())
    return out


def write_refusals(ident: dict, *, env: str, platform: str, expect_system_identifier: str | None,
                   reviewed_identity: dict | None, allow_production: bool,
                   confirm_production_system_identifier: str | None,
                   session_read_only: bool) -> list[str]:
    """TOZA funksiya: yozuvni RAD etish sabablari (bo'sh ro'yxat = ruxsat).

    Faqat shu yerda qaror qabul qilinadi — shuning uchun uni bazasiz sinash mumkin.
    """
    out: list[str] = []
    sysid = ident.get("system_identifier")
    if ident.get("dialect") != "postgresql":
        return [f"migratsiya yozuvi faqat PostgreSQL'da ma'noli (joriy: {ident.get('dialect')})"]
    if session_read_only:
        out.append("sessiya read-only — yozib bo'lmaydi")
    if not expect_system_identifier:
        out.append("--expect-system-identifier MAJBURIY — maqsad baza ANIQ aytilishi kerak")
    elif str(expect_system_identifier).strip() != sysid:
        out.append(f"kutilgan baza {str(expect_system_identifier).strip()}, ulangan {sysid}")
    rd = reviewed_identity if isinstance(reviewed_identity, dict) else {}
    if rd.get("system_identifier") != sysid or rd.get("database") != ident.get("database"):
        out.append("ko'rib chiqilgan hisobot BOSHQA bazada tayyorlangan "
                   f"(hisobot {rd.get('system_identifier')}/{rd.get('database')}, "
                   f"ulangan {sysid}/{ident.get('database')})")

    # Production YO'LIGA olib keladigan har bir signal (bittasi ham yetarli).
    signals: list[str] = []
    if env not in APPLY_ALLOWED_ENVS:
        signals.append(f"APP_ENV='{env}' ruxsat ro'yxatida emas {sorted(APPLY_ALLOWED_ENVS)}")
    if platform in PRODUCTION_ENV_NAMES:
        signals.append(f"platforma muhiti '{platform}'")
    if sysid in PRODUCTION_SYSTEM_IDENTIFIERS:
        signals.append(f"system_identifier {sysid} production taqiq ro'yxatida")
    elif sysid not in allowed_system_identifiers():
        signals.append(f"system_identifier {sysid} production bo'lmagan klasterlar "
                       "ruxsat ro'yxatida yo'q")
    if not signals:
        return out

    # ⚠️  Sabab (qaysi signal) HAR refusal satrida qoladi — operator nima uchun production
    #     yo'liga tushganini ko'rmasa, bayroqlarni «shunchaki» qo'shib qo'yardi.
    missing: list[str] = []
    if not allow_production:
        missing.append("--allow-production berilmagan")
    if not confirm_production_system_identifier:
        missing.append("--confirm-production-system-identifier MAJBURIY")
    elif str(confirm_production_system_identifier).strip() != sysid:
        missing.append("tasdiq mos emas "
                       f"({str(confirm_production_system_identifier).strip()} ≠ {sysid})")
    if env not in PRODUCTION_ENV_NAMES or platform not in PRODUCTION_ENV_NAMES:
        missing.append(f"muhit o'zini production deb E'LON QILMAGAN (APP_ENV='{env}', "
                       f"platforma='{platform}') — niqob ostida yozilmaydi")
    if missing:
        out.append(f"PRODUCTION yo'li [{'; '.join(signals)}]: " + "; ".join(missing))
    return out


def assert_write_allowed(con, *, expect_system_identifier: str | None,
                         reviewed_identity: dict | None, allow_production: bool = False,
                         confirm_production_system_identifier: str | None = None) -> dict:
    """Bazadan identitet va muhitni o'qib, `write_refusals` qaroriga amal qiladi."""
    ident = database_identity(con)
    env, platform = environment_names()
    read_only = False
    if ident["dialect"] == "postgresql":
        read_only = con.execute(text("SHOW transaction_read_only")).scalar() == "on"
    bad = write_refusals(ident, env=env, platform=platform,
                         expect_system_identifier=expect_system_identifier,
                         reviewed_identity=reviewed_identity, allow_production=allow_production,
                         confirm_production_system_identifier=confirm_production_system_identifier,
                         session_read_only=read_only)
    if bad:
        raise MigrationForbidden("YOZISH TAQIQLANGAN: " + "; ".join(bad))
    return {"environment": f"APP_ENV={env}, platforma={platform}", **ident}


# ── READ-ONLY ISBOTI ─────────────────────────────────────────────────────────
# ⚠️  Negativ nazorat JADVALGA BOG'LIQ EMAS: `CREATE TEMP TABLE` read-only tranzaksiyada
#     `ProcessUtility` ning ENG BOSHIDA 25006 bilan rad etiladi (jadval qidirilmaydi, huquq
#     tekshirilmaydi, event trigger ishlamaydi). Sessiya read-only BO'LMASA — vaqtinchalik
#     jadval yaratiladi va SAVEPOINT qaytarilishi bilan yo'q bo'ladi, ya'ni izsiz.
_RO_PROBE_SQL = "CREATE TEMP TABLE savdoos_schema_migrate_ro_probe (x int)"


def prove_read_only(con) -> dict:
    """Ijobiy dalil + negativ nazorat. Isbot bo'lmasa — PermissionError (o'qish TO'XTAYDI)."""
    dialect = con.engine.dialect.name if hasattr(con, "engine") else con.get_bind().dialect.name
    if dialect != "postgresql":
        raise PermissionError(f"READ-ONLY isboti {dialect} uchun yo'q")
    evidence = {
        "dialect": dialect,
        "transaction_read_only": con.execute(text("SHOW transaction_read_only")).scalar(),
        "transaction_isolation": con.execute(text("SHOW transaction_isolation")).scalar(),
    }
    if evidence["transaction_read_only"] != "on":
        raise PermissionError("READ-ONLY isbotlanmadi: transaction_read_only="
                              f"{evidence['transaction_read_only']}")
    # ⚠️  SAVEPOINT (`begin_nested`) — xato tranzaksiyani BUZMASIN: zonddan keyin o'qish
    #     davom etadi (aks holda 25P02 bilan butun preflight yiqilardi).
    sp = con.begin_nested()
    try:
        con.execute(text(_RO_PROBE_SQL))
    except DBAPIError as e:
        sp.rollback()
        if getattr(getattr(e, "orig", None), "sqlstate", None) != PG_READ_ONLY_SQLSTATE:
            raise PermissionError(
                "READ-ONLY isboti NOANIQ: yozuv boshqa sabab bilan rad etildi "
                f"(SQLSTATE {getattr(getattr(e, 'orig', None), 'sqlstate', None)})") from e
        evidence["probe"] = f"rejected: SQLSTATE {PG_READ_ONLY_SQLSTATE}"
        evidence["enforced"] = True
        return evidence
    sp.rollback()
    raise PermissionError("READ-ONLY isbotlanmadi: yozuv so'rovi RAD ETILMADI — to'xtatildi")
