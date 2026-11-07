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

from app.core import api_capabilities, build_identity
from app.core.config import settings
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])


def build_info() -> dict:
    """Qaysi kod ishlayapti — XAVFSIZ metadata (sir YO'Q).

    NEGA KERAK: ilgari ishlayotgan konteynerdan «qaysi versiyasan?» deb so'rab
    bo'lmasdi. Deploy qilingan commit faqat Railway boshqaruv panelidan bilinardi,
    ya'ni «tuzatish chindan ham chiqdimi?» degan savolga ilovaning O'ZI javob
    bera olmasdi.

    ⚠️  SHA O'YLAB TOPILMAYDI. Manba bo'lmasa — `None`. Yolg'on commit
        ko'rsatgandan ko'ra «bilmayman» degan afzal.

    ⚠️  IDENTITET MANBASI ENDI ARTEFAKT ICHIDA (2026-11-07, Phase 9).
        Ilgari commit FAQAT muhit o'zgaruvchisidan olinardi va bu jonli
        insidentga olib keldi: Railway git o'zgaruvchilarini `rollback`
        deploymentida BERMAYDI, shu bois production AYNAN kutilgan
        relizga qaytarilgan bo'lsa ham `commit` `null` keldi, demo
        worker'ning darvozasi yolg'on yiqildi va do'kon 22,8 soat
        muzladi. Batafsil: `app/core/build_identity.py`.

        Endi tartib: MUHR (`app/_build_info.py`, artefakt ichida, o'zini
        tekshiradi) > muhit o'zgaruvchisi (orqaga moslik, `ENV_ONLY`).
        Muhr kod bilan mos kelmasa `commit` E'LON QILINMAYDI.

    ⚠️  JAVOB MAYDONLARI QO'SHILDI, OLIB TASHLANMADI: eski mijozlar
        `build.commit` ni o'qishda davom etadi. `source_digest` va
        `trust` — YANGI maydonlar; ularni o'qimaydigan mijoz uchun
        xulq o'zgarmaydi.
    """
    import os
    ident = build_identity.build_identity()
    env = (os.getenv("APP_ENV") or "").strip().lower() or None
    out = {"commit": ident["commit"], "environment": env,
           "platform_environment": (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "")
           .strip().lower() or None,
           #  ── RELIZ IDENTITETI (to'rt manba ATAYLAB ajratilgan) ──────
           "commit_source": ident["commit_source"],
           "trust": ident["trust"],
           "source_digest": ident["source_digest"],
           "stamp_matches_source": ident["stamp_matches_source"],
           "sealed_at": ident["sealed_at"],
           "deployment_id": ident["deployment_id"]}
    #  ⚠️  Xato SABABI faqat SINF nomi sifatida chiqadi — bu endpoint
    #      OCHIQ, fayl yo'llari oshkor bo'lmasin.
    if ident.get("source_digest_error"):
        out["source_digest_error"] = ident["source_digest_error"]
    return out


@router.get("/health")
def health():
    """TIRIKLIK (liveness): jarayon ko'tarilgan. Bazaga ATAYLAB tegmaydi —
    bu endpoint restart qilish kerakmi degan savolga javob beradi, xizmat tayyormi degan savolga emas.

    `api` — SHARTNOMA DARAJASI (`app/core/api_capabilities.py`). Mobil/PWA mijoz
    ESKI serverni shu blok BO'LMAGANIDAN taniydi (`level 0`) va tayangan
    marshruti yo'q oqimni «server eski» deb TO'SADI — 422/404 ko'rsatib
    operatorni aybdor qilib qo'ymaydi. Statik ma'lumot: baza ham, hisob-kitob
    ham yo'q, javob kichkina qoladi."""
    return {"status": "ok", "service": "savdoos-server", "build": build_info(),
            "api": api_capabilities.declaration()}


def _check_db() -> tuple[bool, bool]:
    """(baza_javob_berdi, cash_sxemasi_bor). Hech qanday metadata QAYTARMAYDI.

    ⚠️  SHARTNOMA O'ZGARMAYDI — AYNAN IKKI qiymat. Bu yordamchi bir nechta testda mock
        qilinadi (`test_hardening`, `test_runtime_columns`, `test_production_ops`), shu
        bois uning arligini yangi imkoniyat uchun o'zgartirish Phase 1 ga UMUMAN aloqasi
        bo'lmagan tayyorlik tekshiruvlarini buzardi. Phase 1 tekshiruvi ALOHIDA:
        `_check_cash_opening()`."""
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


def _check_cash_opening() -> bool:
    """Phase 1 (SEYF ochilishi) obyektlari SOG'MI — MAVJUDLIGI emas, SHAKLI.

    `cash_schema` faqat «`cash` sxemasi bormi» deydi. Phase 1 obyektlari esa MAVJUD
    bazaga additiv boot qadamida qo'shiladi va nomi to'g'ri, shakli noto'g'ri obyekt
    jim o'tib ketishi mumkin — shu bois ustun/CHECK/FK/indeks/trigger (va trigger
    FUNKSIYASI) ANIQ tekshiriladi (`services/cash/schema_readiness`).

    ⚠️  FAQAT `bool`: muammo MATNLARI (jadval/ustun/cheklov nomlari) javobga UMUMAN
        chiqmaydi — production'da obyekt nomlarini oshkor qilmaslik qoidasi.
    ⚠️  «Tekshirib bo'lmadi» ≠ «sog'»: istisnoda False (fail-closed)."""
    db = SessionLocal()
    try:
        from app.services.cash import schema_readiness as _sr
        return bool(_sr.opening_schema_ok(db.get_bind()))
    except Exception:
        return False
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
    cash_opening_ok = _check_cash_opening()

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
    # ⚠️  IDEMPOTENTLIK INDEKSLARI va USTUN TIPI (Phase 5B.1) — ALOHIDA kalitlar. Boot ular
    #     uchun YIQILMAYDI (tuzatish dublikat qatorlar / UUID bo'lmagan qiymatlar ustida
    #     operator qarori), demak monitoring signali — shu yerda QIZIL bo'lish. `missing()`
    #     ga ATAYLAB qo'shilmaydi: `catalog_v2_schema`/`lot_schema_integrity` tasnifi
    #     siljimasin. Nomlar ham AYNI redaksiyadan o'tadi (pastda).
    # ⚠️  PHASE 5C: bu ikki kalit endi partiya kuzatuvini YOQISHNI ham to'sadi — lekin
    #     `missing()` orqali EMAS, `/lots/enable` dagi alohida keshsiz darvoza orqali
    #     (`lot_policy.activation_readiness`). Ya'ni tasnif shu yerda o'zgarmagan,
    #     qaytarib bo'lmaydigan amal esa ikkalasi yashil bo'lishini talab qiladi.
    other: list[str] = []
    if not db_ok:
        v2_ok = False
        lot_ok = False
        idem_ok = False
        types_ok = False
        missing = ["baza yetib bo'lmadi — sxema tekshirilmadi"]
    else:
        try:
            from app.core import required_schema as rs
            from app.db.session import engine
            _all_ok, missing = rs.ok(engine)
            # ⚠️  PARTIYA SXEMASI YAXLITLIGI (Phase 4A) — FK va tasdiqlanmagan CHECK.
            #     Boot bular uchun YIQILMAYDI (crash-loop'ga qarshi), shuning uchun
            #     yagona to'siq — shu yerda QIZIL bo'lish. Alohida kalitda: operator
            #     «ustun yo'q» bilan «FK tasdiqlanmagan» ni darhol ajratsin.
            #     Manba BITTA (`rs.ok`) — sinf satr turidan aniqlanadi.
            v2_ok = not [m for m in missing if not rs.is_soft(m)]
            lot_ok = (not [m for m in missing if rs.is_soft(m)]
                      and missing != ["introspeksiya yiqildi"])
        except Exception:      # noqa: BLE001
            v2_ok = False      # baholay olmasak — TAYYOR EMAS (fail-closed)
            lot_ok = False
        try:
            from app.core import required_schema as rs
            from app.db.session import engine
            idem = rs.idempotency_missing(engine)
            idem_ok = not idem
            other += idem
        except Exception:      # noqa: BLE001
            idem_ok = False    # fail-closed; sabab matni javobga TUSHMAYDI
            other.append("idempotentlik indekslarini o'qib bo'lmadi")
        try:
            from app.core import required_schema as rs
            from app.db.session import engine
            bad_types = rs.column_type_problems(engine)
            types_ok = not bad_types
            other += bad_types
        except Exception:      # noqa: BLE001
            types_ok = False
            other.append("ustun tiplarini o'qib bo'lmadi")

    checks = {"database": db_ok, "cash_schema": cash_ok,
              "cash_opening_schema": cash_opening_ok, "config": config_ok,
              "tenancy_schema": tenancy_ok, "catalog_v2_schema": v2_ok,
              "lot_schema_integrity": lot_ok, "idempotency_schema": idem_ok,
              "column_types": types_ok}
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    out = {"status": "ready" if ok else "not_ready", "checks": checks,
           "build": build_info()}
    missing = missing + other
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
