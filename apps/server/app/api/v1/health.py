"""Sog'liq endpointlari — TIRIKLIK va TAYYORLIK ATAYLAB ajratilgan.

NEGA IKKITA: `/health` faqat "jarayon javob beryapti"ni bildiradi. U bazaga TEGMAYDI — demak
Postgres butunlay yiqilsa ham 200 qaytaradi. Uptime monitori faqat shuni tekshirsa, kassalar
savdo qila olmayotgan paytda ham "hammasi joyida" ko'rsatardi (jim nosozlik).

`/health/ready` esa ilova HAQIQATDA xizmat ko'rsata oladimi — shuni tekshiradi:
baza javob beryaptimi, kerakli sxemalar bormi, kritik konfiguratsiya yuklanganmi.

SIR CHIQMAYDI: javobda faqat BOOLEAN/holat so'zlari. Baza nomi, host, versiya, ulanish satri,
sxema ro'yxati — hech biri chiqmaydi (bu endpointlar ochiq).
"""
from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """TIRIKLIK (liveness): jarayon ko'tarilgan. Bazaga ATAYLAB tegmaydi —
    bu endpoint restart qilish kerakmi degan savolga javob beradi, xizmat tayyormi degan savolga emas."""
    return {"status": "ok", "service": "savdoos-server"}


def _check_db() -> tuple[bool, bool]:
    """(baza_javob_berdi, cash_sxemasi_bor). Hech qanday metadata QAYTARMAYDI."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        reachable = True
        if db.get_bind().dialect.name == "postgresql":
            cash_ok = db.execute(text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'"
            )).first() is not None
        else:
            # SQLite (dev/e2e): cash quyi tizimi ATAYLAB yo'q — bu yerda uni talab qilish
            # noto'g'ri bo'lardi. Faqat Postgres'da (production) kutiladi.
            cash_ok = True
        return reachable, cash_ok
    except Exception:
        return False, False
    finally:
        try:
            db.rollback()
            db.close()
        except Exception:
            pass


@router.get("/health/ready")
def ready(response: Response):
    """TAYYORLIK (readiness): ilova haqiqatan xizmat ko'rsata oladimi.

    503 qaytsa — trafik yubormang / ogohlantiring. Monitoring AYNAN shuni kuzatishi kerak."""
    db_ok, cash_ok = _check_db()

    # Kritik konfiguratsiya: production'da standart JWT siri bilan ishlash mumkin emas.
    # (main.py buni ishga tushishda ham bloklaydi — bu yerda ikkinchi, kuzatiladigan signal.)
    config_ok = not (settings.is_production and settings.insecure_secret)

    checks = {"database": db_ok, "cash_schema": cash_ok, "config": config_ok}
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not_ready", "checks": checks}
