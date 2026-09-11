"""Sog'liq endpointlari — TIRIKLIK va TAYYORLIK ATAYLAB ajratilgan.

NEGA IKKITA: `/health` faqat "jarayon javob beryapti"ni bildiradi. U bazaga TEGMAYDI — demak
Postgres butunlay yiqilsa ham 200 qaytaradi. Uptime monitori faqat shuni tekshirsa, kassalar
savdo qila olmayotgan paytda ham "hammasi joyida" ko'rsatardi (jim nosozlik).

`/health/ready` esa ilova HAQIQATDA xizmat ko'rsata oladimi — shuni tekshiradi:
baza javob beryaptimi, kerakli sxemalar bormi, kritik konfiguratsiya yuklanganmi.

SIR CHIQMAYDI: javobda sir, ulanish satri, host/IP/port, baza nomi yoki baza
foydalanuvchisi HECH QACHON bo'lmaydi — bu endpointlar OCHIQ. Chiqadigan narsa qat'iy
cheklangan: holat boolean'lari, deploy identifikatori (commit SHA + muhit nomi) va
dev/test/staging'da yetishmayotgan MAJBURIY sxema obyektlarining nomlari (production'da
faqat SONI). Xato matnlari (`str(e)`) javobga TUSHMAYDI — ular jurnalga yoziladi, chunki
drayver xatolari ichida host va ulanish tafsilotlari bo'ladi.
"""
import os

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


def build_info() -> dict:
    """Qaysi kod ishlayapti — XAVFSIZ metadata (sir YO'Q).

    NEGA KERAK: ilgari ishlayotgan konteynerdan «qaysi versiyasan?» deb so'rab
    bo'lmasdi. Deploy qilingan commit faqat Railway boshqaruv panelidan bilinardi,
    ya'ni «tuzatish chindan ham chiqdimi?» degan savolga ilovaning O'ZI javob
    bera olmasdi.

    ⚠️  SHA O'YLAB TOPILMAYDI. Platforma bermasa — `None`. Yolg'on commit
        ko'rsatgandan ko'ra «bilmayman» degan afzal.
    """
    import os
    sha = None
    for key in ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT", "SOURCE_COMMIT",
                "GIT_COMMIT", "APP_COMMIT_SHA"):
        val = (os.getenv(key) or "").strip()
        if val:
            sha = val
            break
    env = (os.getenv("APP_ENV") or "").strip().lower() or None
    return {"commit": sha, "environment": env,
            "platform_environment": (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "").strip().lower()
            or None}


@router.get("/health")
def health():
    """TIRIKLIK (liveness): jarayon ko'tarilgan. Bazaga ATAYLAB tegmaydi —
    bu endpoint restart qilish kerakmi degan savolga javob beradi, xizmat tayyormi degan savolga emas."""
    return {"status": "ok", "service": "savdoos-server", "build": build_info()}


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

    # Kritik xavfsizlik konfiguratsiyasi — KANONIK manbadan (`app/core/security_config`).
    #
    # ⚠️  Ilgari bu yerda faqat `insecure_secret` (aynan standart kalit) tekshirilardi,
    #     ya'ni zaif SECRET_KEY, production'da yoqilgan demo seed, 2FA'siz yoki IP
    #     cheklovisiz vendor portali — hammasi "tayyor" deb ko'rinardi. Endi boot,
    #     readiness va `config_audit` AYNAN bir xil shartlarni baholaydi.
    #     Javobda faqat KALIT NOMI va mos/mos emasligi bo'ladi — sir qiymatlari ham,
    #     ortiqcha konfiguratsiya tafsiloti ham CHIQMAYDI.
    try:
        from app.core.security_config import security_config_ok
        config_ok, _sec_detail = security_config_ok()
    except Exception:      # noqa: BLE001
        config_ok = False  # baholay olmasak — TAYYOR EMAS (fail-closed)

    # Ko'p-tenantlik sxemasi: `customer_groups`/`brands` do'konga BOG'LANGAN bo'lishi shart.
    # `initdb` bunday bo'lmasa ishga tushishni to'xtatadi, LEKIN kimdir uvicorn'ni
    # to'g'ridan-to'g'ri ko'tarsa o'sha gard chetlab o'tilardi. Shu bois IKKINCHI qatlam:
    # xavfsiz bo'lmagan sxemada backend HECH QACHON "tayyor" deb ko'rinmaydi.
    try:
        from app.initdb import tenancy_schema_ok
        tenancy_ok, _detail = tenancy_schema_ok()
    except Exception:      # noqa: BLE001
        tenancy_ok = False

    # MAJBURIY 1C Cutover V2 obyektlari. `initdb` ularsiz ishga tushmaydi, LEKIN
    # migratsiya boshqa yo'l bilan (qo'lda, eski konteyner, qaytarilgan deploy)
    # chetlab o'tilishi mumkin. Bu ikkinchi qatlam: yetishsa — TAYYOR EMAS.
    # ⚠️  FAQAT INTROSPEKSIYA — sog'liq tekshiruvi sxemani O'ZGARTIRMAYDI.
    #
    # ⚠️  FAQAT baza YETIB BORILGANDA so'raladi. Ikki sabab:
    #     1) baza yiqilgan bo'lsa sxema holatini BILIB BO'LMAYDI — «yo'q» deb
    #        aytish yolg'on bo'lardi, «bor» deb aytish esa xavfli;
    #     2) muhimi — introspeksiya ULANISH OCHADI, va SQLite'da bu baza faylini
    #        YARATIB YUBORADI. Sog'liq tekshiruvi yon ta'sir sifatida baza
    #        yaratmasligi kerak (sinov to'plamida aynan shu bo'ldi: `ready()`
    #        chaqirilgach `_pytest.db` paydo bo'lib BAND qolardi va keyingi
    #        sessiya fixture'i uni o'chira olmasdi).
    missing: list[str] = []
    if not db_ok:
        v2_ok = False
        missing = ["baza yetib bo'lmadi — sxema tekshirilmadi"]
    else:
        try:
            from app.core import required_schema as rs
            from app.db.session import engine
            v2_ok, missing = rs.ok(engine)
        except Exception:      # noqa: BLE001
            v2_ok = False      # baholay olmasak — TAYYOR EMAS (fail-closed)

    checks = {"database": db_ok, "cash_schema": cash_ok, "config": config_ok,
              "tenancy_schema": tenancy_ok, "catalog_v2_schema": v2_ok}
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    out = {"status": "ready" if ok else "not_ready", "checks": checks,
           "build": build_info()}
    if missing:
        # ⚠️  Bu endpoint AVTORIZATSIYASIZ. Obyekt nomlari sir emas, lekin kod
        #     repo'si YOPIQ (CLAUDE.md) — ya'ni jadval/ustun/indeks nomlari
        #     ommaviy ma'lum EMAS va ularni ochiq e'lon qilish nishonli
        #     probing uchun yordam bo'lardi. Shu bois production'da faqat SON
        #     chiqadi; aniq nomlar JURNALGA yoziladi (Railway loglari).
        #     Dev/test/staging'da nomlar javobda qoladi — operator ayni shu
        #     yerda tuzatadi.
        print("[schema] yetishmayotgan majburiy obyektlar: " + "; ".join(missing))
        env = (os.getenv("APP_ENV") or "").strip().lower()
        if env in {"prod", "production"} or                 (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "").strip().lower() in {"prod", "production"}:
            out["missing_schema_count"] = len(missing)
        else:
            out["missing_schema"] = missing
    return out
