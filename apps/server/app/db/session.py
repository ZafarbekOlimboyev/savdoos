import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _normalize(url: str) -> str:
    # Railway/Heroku "postgres://" yoki "postgresql://" beradi — psycopg v3 draйveri kerak.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _envint(name: str, default: int, minv: int) -> int:
    """Env'дан butun son — noto'g'ri/bo'sh/kichik qiymat boot'ni yiqitmasin (ValueError -> default)."""
    try:
        v = int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default
    return v if v >= minv else default


_url = _normalize(settings.database_url)
_engine_kw: dict = {"pool_pre_ping": True, "future": True}
# Postgres (prod): standart hovuz (5+10=15) ko'p kassa/parallel yukда tor bo'lardi (yuqori
# konkurentlikда QueuePool timeout -> 500). Hovuzni oshiramiz; env orqali sozlanadi. SQLite (dev/test)
# uchun tegmaymiz (u boshqa hovuz naqshini ishlatadi). Umumiy ulanish (pool_size+max_overflow) Postgres
# server max_connections'дан oshmasин — standart 50 xavfsiz (odatдаги limit 100).
if not _url.startswith("sqlite"):
    # Prod Postgres max_connections=100 (tekshirilgan). Bir instansiya 40 (15+25) — rolling-deploy'да
    # qisqa vaqt 2 instansiya ishlasa ham 2x40=80<100 xavfsiz. Env orqali oshirса bo'ladi (yagona
    # instansiya bo'lsa DB_MAX_OVERFLOW ni 45 gacha ko'tarish mumkin).
    _engine_kw.update(
        pool_size=_envint("DB_POOL_SIZE", 15, 1),       # <1 (yoki 0=cheksiz) xavfli -> default
        max_overflow=_envint("DB_MAX_OVERFLOW", 25, 0),
        pool_recycle=1800,   # uzoq idle ulanishni yangilaydi (stale TCP oldini oladi)
        pool_timeout=30,
    )
engine = create_engine(_url, **_engine_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
