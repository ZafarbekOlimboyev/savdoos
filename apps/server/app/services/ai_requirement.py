"""Canonical policy and activation fence. Lock order: policy -> company -> consent.
Locks live through the provider call. No DB/HTTP distributed atomicity is claimed.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai_requirement import AiRequirement

PROTOCOL_VERSION = 2
DISCLOSURE_ID = "binos.receiving.ai.v1"
DISPATCH_ID = "binos.receiving.dispatch.v2"
PROVIDERS = {"gemini": "Google Gemini (Google LLC)",
             "anthropic": "Anthropic Claude (Anthropic PBC)"}


def reject(status: int, code: str):
    messages = {
        "AI_CONSENT_REQUIRED": "AI orqali o‘qish uchun do‘kon egasi yoki administratorining roziligi kerak. Qatorlarni qo‘lda kiriting.",
        "AI_REQUIREMENT_CHANGED": "AI xizmati yoki rozilik shartlari o‘zgardi. Yangilangan shartlarni tekshiring va qayta rozilik bering.",
    }
    raise HTTPException(status, messages.get(code,
        "AI xizmati hozir mavjud emas. Qatorlarni qo‘lda kiriting."),
        headers={"X-Error-Code": code})


@dataclass(frozen=True)
class Requirement:
    revision: int
    mode: str
    provider: str | None
    model: str | None
    disclosure_version: int
    disclosure_id: str
    protocol_version: int
    dispatch_id: str
    credential: str = field(default="", repr=False, compare=False)

    def public(self) -> dict:
        return {"revision": self.revision, "mode": self.mode,
                "provider": self.provider, "provider_name": PROVIDERS.get(self.provider),
                "model": self.model, "disclosure_version": self.disclosure_version,
                "disclosure_id": self.disclosure_id, "protocol_version": self.protocol_version}

    def matches(self, value: dict) -> bool:
        return all(type(value.get(k)) is type(v) and value[k] == v
                   for k, v in self.public().items()
                   if k in ("revision", "provider", "disclosure_version", "disclosure_id"))


def _load(db: Session, *, exclusive=False):
    try:
        if getattr(db, 'bind', None) is not None and db.bind.dialect.name == 'postgresql':
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
        row = db.scalar(select(AiRequirement).where(AiRequirement.id == 1)
                        .with_for_update(read=not exclusive)
                        .execution_options(populate_existing=True))
    except SQLAlchemyError:
        reject(503, "AI_REQUIREMENT_UNAVAILABLE")
    if row is None:
        reject(503, "AI_REQUIREMENT_UNAVAILABLE")
    return row


def locked(db: Session) -> Requirement:
    row = _load(db)
    if (row.protocol_version != PROTOCOL_VERSION or row.dispatch_id != DISPATCH_ID
            or row.disclosure_version != 1 or row.disclosure_id != DISCLOSURE_ID):
        reject(503, "AI_WORKER_FENCED")
    if row.mode == "paused":
        reject(503, "AI_REQUIREMENT_PAUSED")
    key = ""
    if row.mode == "active":
        if row.provider not in PROVIDERS or not row.model or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", row.model):
            reject(503, "AI_WORKER_FENCED")
        key = settings.gemini_api_key if row.provider == "gemini" else settings.anthropic_api_key
        if not key.strip():
            reject(503, "AI_CREDENTIAL_UNAVAILABLE")
    elif row.mode != "demo" or row.provider is not None or row.model is not None:
        reject(503, "AI_WORKER_FENCED")
    return Requirement(row.revision, row.mode, row.provider, row.model,
                       row.disclosure_version, row.disclosure_id,
                       row.protocol_version, row.dispatch_id, key)


GUARD_NAME = "ai_requirement_revision_guard"

# Same body as app/db/migrations/m2026_10_17_ai_requirement.sql. Pinned by
# tests/test_r74_ai_provision_pg.py::test_PROVISION_SQL_MIGRATSIYA_bilan_AYNI.
_GUARD_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {GUARD_NAME}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'ai requirement cannot be deleted';
 END IF;
 IF NEW.revision <> OLD.revision + 1 THEN
   RAISE EXCEPTION 'ai requirement revision must advance by one';
 END IF;
 RETURN NEW;
END;
$$
"""

_SEED_SQL = text(
    "INSERT INTO ai_requirement (id, revision, mode, provider, model, disclosure_version,"
    " disclosure_id, protocol_version, dispatch_id, activated_by)"
    " VALUES (1, 1, 'paused', NULL, NULL, 1, :disclosure_id, :protocol_version,"
    " :dispatch_id, :actor) ON CONFLICT (id) DO NOTHING")


def _guard_installed(con) -> tuple[bool, bool]:
    """(funksiya bormi, trigger bormi) — QULFSIZ katalog o'qishi."""
    fn = con.execute(text("SELECT count(*) FROM pg_proc WHERE proname = :n"),
                     {"n": GUARD_NAME}).scalar()
    tg = con.execute(text(
        "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'public.ai_requirement'::regclass"
        " AND NOT tgisinternal AND tgname = :n"), {"n": GUARD_NAME}).scalar()
    return bool(fn), bool(tg)


def provision(db: Session, *, actor: str) -> dict:
    """Baza darajasidagi gardni o'rnatadi va `paused` siyosat qatorini ekadi.

    NEGA KERAK (R7.3 topilmasi): jadvalni va uning CHECK cheklovlarini boot yo'li
    yaratadi (`initdb` -> `Base.metadata.create_all`, model `models/__init__.py` da
    ro'yxatdan o'tgan), lekin TRIGGER va ekilgan QATOR faqat
    `app/db/migrations/m2026_10_17_ai_requirement.sql` da yashaydi — va o'sha faylni
    deploy yo'lida HECH NARSA bajarmaydi. Qator bo'lmasa `activate()` ning
    `_load(exclusive=True)` i 503 beradi, ya'ni AI ni YOQIB BO'LMAYDI.

    ⚠️  AI NI YOQMAYDI. Ekiladigan qator `mode='paused'` — `locked()` undan keyin
        ham 503 beradi, faqat xato kodi `AI_REQUIREMENT_UNAVAILABLE` dan
        `AI_REQUIREMENT_PAUSED` ga aniqlashadi. Yoqish — alohida, CAS bilan
        himoyalangan `activate()` amali.

    ⚠️  MAVJUD QATORGA TEGMAYDI: `ON CONFLICT (id) DO NOTHING`. Nokanonik qator
        topilsa u TUZATILMAYDI (bu CAS'siz siyosat o'zgarishi bo'lardi) —
        `canonical: False` deb XABAR qilinadi, operator `activate()` bilan tuzatadi.

    Idempotent. Chaqiruvchi commit qiladi. Imtiyozli amal: faqat
    `app/tools/ai_requirement.py` dan chaqiriladi, ommaviy API'da yo'q.
    """
    if not actor.strip():
        reject(422, "AI_REQUIREMENT_INVALID")
    if getattr(db, "bind", None) is None or db.bind.dialect.name != "postgresql":
        raise RuntimeError("provision requires an explicit PostgreSQL connection")
    con = db.connection()
    con.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    con.exec_driver_sql("SET LOCAL statement_timeout = '10s'")

    # 1) Gard. Maqsad holat joyida bo'lsa — DDL ham, qulf ham YO'Q.
    have_fn, have_tg = _guard_installed(con)
    if have_fn and have_tg:
        guard = "ALREADY_PRESENT"
    else:
        guard = "INSTALLED"
        con.exec_driver_sql(_GUARD_FUNCTION_SQL)
        con.exec_driver_sql(f"DROP TRIGGER IF EXISTS {GUARD_NAME} ON ai_requirement")
        con.exec_driver_sql(
            f"CREATE TRIGGER {GUARD_NAME} BEFORE UPDATE OR DELETE ON ai_requirement"
            f" FOR EACH ROW EXECUTE FUNCTION {GUARD_NAME}()")

    # 2) Qator — FAQAT yo'q bo'lsa. Trigger `BEFORE UPDATE OR DELETE`, INSERT'ga tegmaydi.
    seeded = con.execute(_SEED_SQL, {"disclosure_id": DISCLOSURE_ID,
                                     "protocol_version": PROTOCOL_VERSION,
                                     "dispatch_id": DISPATCH_ID,
                                     "actor": actor.strip()}).rowcount

    row = db.scalar(select(AiRequirement).where(AiRequirement.id == 1)
                    .execution_options(populate_existing=True))
    if row is None:                      # tutib bo'lmaydigan holat — fail-closed
        raise RuntimeError("provision could not establish the policy row")
    canonical = (row.protocol_version == PROTOCOL_VERSION and row.dispatch_id == DISPATCH_ID
                 and row.disclosure_version == 1 and row.disclosure_id == DISCLOSURE_ID)
    return {"guard": guard, "row": "SEEDED" if seeded == 1 else "ALREADY_PRESENT",
            "canonical": canonical, "revision": row.revision, "mode": row.mode}


def activate(db: Session, *, expected_revision: int, mode: str,
             provider: str | None, model: str | None, actor: str,
             disclosure_version=1, disclosure_id=DISCLOSURE_ID,
             protocol_version=PROTOCOL_VERSION, dispatch_id=DISPATCH_ID) -> int:
    """Privileged operation; caller commits. Never called on worker startup.

    Pre-fence binaries MUST be drained before first activation. They cannot
    obey code they do not run. Rollback also advances the revision.
    """
    row = _load(db, exclusive=True)
    if row.revision != expected_revision:
        reject(409, "AI_REQUIREMENT_CHANGED")
    if (mode not in ("active", "paused", "demo") or not actor.strip()
            or not disclosure_id.strip() or not dispatch_id.strip()
            or disclosure_version < 1 or protocol_version < 1
            or (mode == "active" and (provider not in PROVIDERS or not model
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", model)))
            or (mode != "active" and (provider is not None or model is not None))):
        reject(422, "AI_REQUIREMENT_INVALID")
    row.revision += 1
    row.mode, row.provider, row.model = mode, provider, model
    row.disclosure_version, row.disclosure_id = disclosure_version, disclosure_id
    row.protocol_version, row.dispatch_id = protocol_version, dispatch_id
    row.activated_by, row.activated_at = actor, datetime.now(timezone.utc)
    db.flush()
    return row.revision
