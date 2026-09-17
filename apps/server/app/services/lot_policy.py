"""PARTIYA SIYOSATI — muddat HOSILA holat, biznes sanasi filial vaqtida.

⚠️  MUDDAT — HOLAT EMAS. `StockBatch.status` faqat miqdor hayot siklini bildiradi
    (open / depleted / void). «Muddati o'tgan» esa har safar HISOBLANADI:

        expired  ⇔  expiry_date < business_date(branch)

    Sabab: muddat o'tishi bilan tovar javondan YO'QOLMAYDI. 10 dona muddati kecha
    tugagan sut hamon 10 dona. Uni holat sifatida saqlash ikki xavf tug'diradi:
    (1) kim va qachon «muddati o'tgan» deb belgilashini hal qilish kerak bo'ladi —
    fon ishimi, so'rov paytimi, qaysi vaqt zonasida; (2) shu belgilash miqdor
    invariantidan partiyani chiqarib yuborsa, qoldiq JIMGINA yo'qolardi.

⚠️  VAQT ZONASI. `expiry_date` — `DATE`, ya'ni BIZNES sanasi. Uni UTC bilan
    solishtirish xato: Toshkent UTC+5, mahalliy 03:00 da UTC hali KECHAGI kun.
    Loyihada allaqachon `branches.timezone` bor (`app/models/org.py`) va
    hisobotlar undan foydalanadi — YANGI ustun QO'SHILMAYDI.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.org import Branch

# ⚠️  YAGONA MANBA. Ro'yxatni NUSXALASH xavfli: hisobotlar bir zonani biladi,
#     muddat esa bilmay qolsa, AYNI do'kon uchun ikki xil "bugun" chiqardi.
#     Shu bois ro'yxat hisobotlardan OLINADI, qayta yozilmaydi.
from app.api.v1.reports import _TZ_OFFSETS  # noqa: E402

_TZ_OFFSETS = dict(_TZ_OFFSETS)
DEFAULT_TZ = "Asia/Tashkent"


class TimezoneNotConfigured(ValueError):
    """Filial vaqt zonasi ishonchli emas — muddat kuzatuvini yoqib bo'lmaydi."""


def branch_tz(db: Session, branch_id) -> timezone:
    """Filialning BIZNES vaqt zonasi.

    Kompaniya darajasidagi vaqt zonasi modelда YO'Q — shu bois zanjir
    `branch.timezone` → standart. Standart JIMGINA to'g'ri deb qabul
    qilinmaydi: `validate_for_expiry()` uni aniq tekshiradi.
    """
    b = db.get(Branch, branch_id)
    name = (b.timezone if b and b.timezone else DEFAULT_TZ)
    return timezone(timedelta(hours=_TZ_OFFSETS.get(name, 5)))


def business_date(db: Session, branch_id, now: datetime | None = None) -> date:
    """Filialning MAHALLIY biznes sanasi."""
    tz = branch_tz(db, branch_id)
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(tz).date()


def validate_for_expiry(db: Session, branch_id) -> str:
    """Muddat kuzatuvini yoqishdan OLDIN vaqt zonasi ANIQ bo'lishi shart.

    ⚠️  `Asia/Tashkent` standarti boshqa mamlakatdagi do'kon uchun JIMGINA
        to'g'ri deb hisoblanmaydi: bir kunlik xato muddati o'tgan sutni
        «yaroqli» qilib ko'rsatishi mumkin. Shu bois filial vaqt zonasi ANIQ
        o'rnatilgan va TANILGAN bo'lishi kerak.
    """
    b = db.get(Branch, branch_id)
    if b is None:
        raise TimezoneNotConfigured("filial topilmadi")
    name = (b.timezone or "").strip()
    if not name:
        raise TimezoneNotConfigured(
            "filial vaqt zonasi o'rnatilmagan. Muddat kuzatuvi BIZNES sanasiga "
            "tayanadi; zonasiz bir kunlik xato muddati o'tgan tovarni yaroqli "
            "ko'rsatishi mumkin.")
    if name not in _TZ_OFFSETS:
        raise TimezoneNotConfigured(
            f"vaqt zonasi '{name}' tanilmagan. Muddat kuzatuvi yoqilishidan oldin "
            f"u qo'llab-quvvatlanadigan zonalar ro'yxatiga kiritilishi kerak.")
    return name


# ── VAQT ZONASINI TASDIQLASH ─────────────────────────────────────────────────
# Sintaktik yaroqli zona YETARLI EMAS. `Asia/Tashkent` standarti Qozog'istondagi
# do'kon uchun ham "yaroqli" ko'rinadi — lekin bir soatlik farq muddat sanasini
# bir kunga surib yuborishi mumkin. Shu bois muddat kuzatuvini yoqishdan oldin
# operator zonani ANIQ tasdiqlashi kerak.
#
# ⚠️  IKKINCHI USTUN QO'SHILMAYDI. Tasdiq mavjud `settings` mexanizmida yashaydi:
#     kalit `catalog`, ichida `expiry_tz_confirmed: {branch_id: "Asia/Tashkent"}`.
#     Tasdiq ZONA NOMI bilan birga saqlanadi — keyin zona o'zgartirilsa tasdiq
#     avtomatik KUCHINI YO'QOTADI va qayta so'raladi.
SETTINGS_KEY = "catalog"
CONFIRM_FIELD = "expiry_tz_confirmed"


def _catalog_settings(db: Session, company_id) -> dict:
    from app.services import catalog_import_v2 as civ2
    return civ2.get_catalog_settings(db, company_id) or {}


def tz_confirmed(db: Session, company_id, branch_id) -> bool:
    """Shu filial uchun zona ANIQ tasdiqlanganmi (va o'shandan beri o'zgarmaganmi)."""
    b = db.get(Branch, branch_id)
    if b is None or not (b.timezone or "").strip():
        return False
    conf = (_catalog_settings(db, company_id).get(CONFIRM_FIELD) or {})
    return conf.get(str(branch_id)) == b.timezone


def confirm_tz(db: Session, company_id, branch_id) -> tuple[str, str | None, bool]:
    """Zonani tasdiqlaydi. Avval yaroqliligi tekshiriladi.

    Qaytaradi: (zona nomi, AVVALGI tasdiq yoki None, qiymat o'zgardimi).

    ⚠️  FAQAT `expiry_tz_confirmed[branch_id]` YOZILADI — qulf ostida. Ilgari
        butun `settings.catalog` (standartlari bilan) qaytarib yozilardi: bu
        katalog cutover holatini (mode/cutover_at/source_system/last_*) eskirgan
        qiymat bilan bosib ketishi va migrator izini o'zgartirishi mumkin edi.
    """
    name = validate_for_expiry(db, branch_id)
    from app.services import catalog_import_v2 as civ2
    prev: dict = {}

    def _mark(val: dict) -> None:
        conf = dict(val.get(CONFIRM_FIELD) or {})
        prev["tz"] = conf.get(str(branch_id))      # QULF ostida o'qilgan qiymat
        conf[str(branch_id)] = name
        val[CONFIRM_FIELD] = conf

    changed = civ2.update_catalog_settings(db, company_id, _mark)
    return name, prev.get("tz"), changed


def assert_tz_confirmed(db: Session, company_id, branch_id) -> None:
    """Tasdiqlanmagan bo'lsa — muddat kuzatuvi YOQILMAYDI."""
    validate_for_expiry(db, branch_id)          # avval sintaktik yaroqlilik
    if not tz_confirmed(db, company_id, branch_id):
        b = db.get(Branch, branch_id)
        raise TimezoneNotConfigured(
            f"filial vaqt zonasi ('{b.timezone}') TASDIQLANMAGAN. Muddat biznes "
            f"sanasiga tayanadi va bir soatlik xato muddatni bir kunga suradi — "
            f"shu bois zona operator tomonidan ANIQ tasdiqlanishi kerak.")


def is_expired(expiry_date: date | None, biz_date: date) -> bool:
    """Muddat O'TGANMI. `None` — muddat NOMA'LUM, o'tgan DEYILMAYDI.

    Chegara ATAYLAB saxiy: `expiry_date == biz_date` — o'sha kun oxirigacha
    YAROQLI. Bu SIYOSAT chegarasi, umumiy huquqiy qoida emas; tenant uni
    keyinchalik («muddat kunида sotilmasin») qattiqroq qilishi mumkin.
    """
    if expiry_date is None:
        return False
    return expiry_date < biz_date


# ── PHASE 2 XUSUSIYAT DARVOZASI — PRODUCTION'DA KUZATUV YOQILMAYDI ───────────
# Partiya kuzatuvi hali production'da ko'rib chiqilmagan. «Hech kim bosmaydi»
# ga tayanish YETARLI EMAS: bitta tasodifiy chaqiruv jonli do'konning mahsulotini
# kuzatuvli qilib qo'yadi va uni ortga qaytarib bo'lmaydi (tarix yo'qoladi).
#
# ⚠️  FAIL-CLOSED. Muhit nomi ANIQ ruxsat ro'yxatida bo'lmasa — RAD ETILADI.
#     «Signal yo'q» «production emas» degani EMAS: production'da `APP_ENV`
#     umuman o'rnatilmagan va aynan shu bo'shliq ilgari katalog resetini
#     production'da ochiq qoldirgan edi (`catalog_reset` izohiga qarang).
#     Shu bois qaror MANBAI bitta — allaqachon ko'rib chiqilgan o'sha modul.
LOT_ACTIVATION_ALLOWED_ENVS = frozenset({"dev", "test", "staging"})


class LotActivationNotAllowed(RuntimeError):
    """Bu muhitda partiya kuzatuvini yoqib bo'lmaydi."""


# ── DO'KON × FILIAL DARVOZASI (Phase 5B.1) ──────────────────────────────────
# Muhit darvozasi JARAYON bo'yicha: u production'da ochilsa, HAR do'konning
# `ombor.edit` egasi o'z mahsulotini QAYTARIB BO'LMAYDIGAN qilib kuzatuvli qila
# olardi. Faollashtirish esa VENDOR qarori — bitta do'kon, bitta filial.
#
#     SAVDOOS_LOT_ACTIVATION_SCOPES="<company_uuid>:<branch_uuid>[,<...>:<...>]"
#
# ⚠️  FAIL-CLOSED. O'zgaruvchi yo'q/bo'sh -> ro'yxat YO'Q (production'da yopiq).
#     BITTA buzuq yozuv -> ro'yxat BO'SH: hammasi yopiq. «Qolganlari to'g'ri-ku»
#     deb qisman o'qish operator xatosini JIMGINA ruxsatga aylantirardi.
# ⚠️  HAR CHAQIRUVDA o'qiladi (`environment_name()` kabi) — keshlanmaydi.
# ⚠️  QIYMAT HECH QAYERDA CHIQMAYDI: na javobda, na xato matnida, na jurnalda.
LOT_ACTIVATION_SCOPES_ENV = "SAVDOOS_LOT_ACTIVATION_SCOPES"
_PROD_ENVS = frozenset({"prod", "production"})

MODE_ENV = "env"          # dev/test/staging, ro'yxat YO'Q — muhit bo'yicha (bugungi xulq)
MODE_SCOPED = "scoped"    # ro'yxat BOR — faqat aniq (do'kon, filial) juftligi
MODE_CLOSED = "closed"    # hech kimga


def _canon(v) -> str | None:
    """UUID ning kanonik ko'rinishi (kichik harf, chiziqchali); yaroqsiz -> None."""
    if v is None:
        return None
    try:
        return str(v if isinstance(v, uuid.UUID) else uuid.UUID(str(v).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def activation_scopes() -> frozenset[tuple[str, str]] | None:
    """Ruxsat berilgan (do'kon, filial) juftliklari.

    `None` — o'zgaruvchi berilmagan yoki bo'sh; `frozenset()` — kamida BITTA yozuv
    buzuq (bo'sh yozuv, ikki qismdan boshqa, UUID emas) — hammasi YOPIQ.
    """
    raw = os.getenv(LOT_ACTIVATION_SCOPES_ENV)
    if raw is None or not raw.strip():
        return None
    out: set[tuple[str, str]] = set()
    for entry in raw.split(","):
        parts = entry.split(":")
        if len(parts) != 2:
            return frozenset()
        cid, bid = _canon(parts[0]), _canon(parts[1])
        if cid is None or bid is None:
            return frozenset()
        out.add((cid, bid))
    return frozenset(out)


def _state() -> tuple[str, frozenset[tuple[str, str]] | None]:
    """(rejim, ro'yxat) — ikkalasi AYNI o'qishdan."""
    from app.services.catalog_reset import environment_name, platform_environment_name
    env, platform = environment_name(), platform_environment_name()
    scopes = activation_scopes()
    # Platformaning O'Z belgisi `APP_ENV` dan USTUN — `APP_ENV=dev` berib
    # production darvozasini ochib bo'lmasin (ro'yxat bo'lsa ham).
    if platform in _PROD_ENVS and env not in _PROD_ENVS:
        return MODE_CLOSED, scopes
    if env in LOT_ACTIVATION_ALLOWED_ENVS:
        # Ro'yxat berilgan bo'lsa staging ham AYNAN production kabi ishlaydi —
        # production konfiguratsiyasini oldindan sinab ko'rish mumkin bo'lsin.
        return (MODE_SCOPED if scopes is not None else MODE_ENV), scopes
    # ⚠️  Production'da FAQAT ro'yxat ochadi. Qarama-qarshi signal (production
    #     ilova staging platformasida) — ochmaydi.
    if env in _PROD_ENVS and platform in (_PROD_ENVS | {"unknown"}):
        return (MODE_SCOPED if scopes is not None else MODE_CLOSED), scopes
    return MODE_CLOSED, scopes


def activation_mode() -> str:
    """`env` | `scoped` | `closed`. Tashqariga (API javobiga) CHIQARILMAYDI."""
    return _state()[0]


def scope_summary() -> dict:
    """Operator uchun (boot jurnali, `config_audit`) — QIYMATSIZ: rejim va sonlar.

    `entries` — vergul bilan ajratilgan yozuvlar soni (o'zgaruvchi yo'q bo'lsa 0);
    `malformed` — kamida bitta yozuv buzuq, ya'ni ro'yxat HAMMA uchun yopiq.
    """
    mode, scopes = _state()
    raw = os.getenv(LOT_ACTIVATION_SCOPES_ENV) or ""
    entries = len(raw.split(",")) if raw.strip() else 0
    return {"mode": mode, "set": scopes is not None, "entries": entries,
            "valid_pairs": len(scopes or ()),
            "malformed": scopes is not None and not scopes}


def activation_allowed(company_id=None, branch_id=None) -> bool:
    """Kuzatuvni yoqish MUMKINMI — BAZAGA TEGMAYDI.

    `env` (dev/test/staging, ro'yxatsiz) — ha, argumentlarsiz ham (bugungi xulq);
    `scoped` — faqat ro'yxatdagi AYNAN (do'kon, filial) juftligi; `closed` — yo'q.
    Filial ko'rsatilmasa `scoped` da RAD: qaytarib bo'lmaydigan yozuvni jimgina
    tanlangan «standart filial» hal qilmasin.
    """
    mode, scopes = _state()
    if mode == MODE_ENV:
        return True
    if mode != MODE_SCOPED:
        return False
    pair = (_canon(company_id), _canon(branch_id))
    if None in pair:
        return False
    return pair in (scopes or frozenset())


def scope_covers_company(db: Session | None, company_id) -> bool:
    """Do'konning HAR tirik filiali ro'yxatdami.

    ⚠️  NEGA BUTUN DO'KON. `track_lots` — MAHSULOT bayrog'i: invariant, FEFO, kirim
        va sanoq do'konning HAMMA filialida ishlaydi. Ikki filialli do'konda bitta
        filial ro'yxatda bo'lsa, ikkinchisida o'sha mahsulotning kirimi va sotuvi
        jimgina partiyaga bog'lanib qolardi. Keyin qo'shilgan filial ham darvozani
        avtomatik YOPADI.

    `env` rejimida bazaga TEGMAYDI. Faqat chaqiruvchining O'Z do'koni o'qiladi va
    faqat juftlik tekshiruvidan KEYIN — begona filial mavjudligi oshkor bo'lmaydi.
    Baza berilmasa (`scoped`/`closed`) — isbotlab bo'lmaydi, demak RAD.
    """
    mode, scopes = _state()
    if mode == MODE_ENV:
        return True
    cid = _canon(company_id)
    if mode != MODE_SCOPED or cid is None or db is None:
        return False
    ids = [r[0] for r in db.query(Branch.id)
           .filter(Branch.company_id == uuid.UUID(cid), Branch.deleted_at.is_(None)).all()]
    if not ids:
        return False
    return all((cid, _canon(b)) in (scopes or frozenset()) for b in ids)


def assert_activation_allowed(company_id=None, branch_id=None, db: Session | None = None) -> None:
    """Rad etilsa — `LotActivationNotAllowed` AYNI matn bilan.

    ⚠️  MATN ATAYLAB BITTA. «Ro'yxatda yo'q», «filial ko'rsatilmagan», «begona
        filial», «do'kon to'liq qoplanmagan» — hammasi bir xil javob: sabab farqi
        begona filial yoki ro'yxat haqida hech narsa oshkor qilmasin (va yangi
        tarjima kerak bo'lmasin).
    """
    if not (activation_allowed(company_id, branch_id) and scope_covers_company(db, company_id)):
        from app.services.catalog_reset import environment_name
        raise LotActivationNotAllowed(
            f"partiya kuzatuvi bu muhitda ('{environment_name()}') YOQILMAYDI. "
            f"Phase 2 hali production uchun ko'rib chiqilmagan; kuzatuv yoqilgan "
            f"mahsulotni ortga qaytarib bo'lmaydi.")


# ── SXEMA DARVOZASI — QISQA KESHLANGAN ──────────────────────────────────────
_SCHEMA_CACHE: dict[int, tuple[float, list[str]]] = {}
SCHEMA_TTL = 60.0


def schema_problems(bind, ttl: float = SCHEMA_TTL) -> list[str]:
    """Majburiy sxema obyektlaridan yetishmayotganlari.

    (`required_schema.missing`: HALOKATLI + FK/CHECK holati.)

    ⚠️  NEGA KESHLANADI. To'liq introspeksiya o'nlab katalog so'rovi. Uni har
        partiya yozuvida bajarish inventarizatsiyani sezilarli sekinlashtirardi va
        foyda bermasdi: sxema faqat deploy/migratsiyada o'zgaradi.

    ⚠️  KESH JARAYON ICHIDA. Deploydan keyin yangi konteyner boshidan o'qiydi;
        eski konteyner esa ko'pi bilan {ttl} soniya eskirgan javob beradi.
    """
    import time

    from app.core import required_schema as _rs

    key = id(bind)
    hit = _SCHEMA_CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    out = _rs.missing(bind)
    # ⚠️  INTROSPEKSIYA YIQILISHI KESHLANMAYDI. Bir lahzalik ulanish uzilishi
    #     «sxema tayyor emas» deb 60 soniya eslab qolinsa, baza tiklangandan
    #     keyin ham kuzatuvli yozuvlar asossiz 409 olardi.
    if out != ["introspeksiya yiqildi"]:
        _SCHEMA_CACHE[key] = (now, out)
    return out


# ── AKTIVATSIYA TAYYORLIGI — BAZA (KESHSIZ) ─────────────────────────────────
#
# ⚠️  NEGA ALOHIDA VA KESHSIZ. Kuzatuvni yoqish QAYTARIB BO'LMAYDI: bayroq
#     yoqilgach mahsulotning har yozuvi partiya/qarz qatorlarini tug'diradi va
#     ularni o'chiradigan yo'l YO'Q. Shu bois qaror 60 soniyalik keshga emas,
#     AYNI LAHZADAGI bazaga tayanadi (`schema_problems` keshi esa ekranlar
#     uchun qoladi — u yozuv qarori emas).
# ⚠️  NOM QAYTARILMAYDI. Faqat uchta boolean: javob `/health/ready` da allaqachon
#     ochiq bo'lgan MA'LUMOTDAN oshmaydi, indeks/jadval/ustun nomlari esa (kod
#     repo'si yopiq) faqat JURNALGA tushadi.
# ⚠️  FAIL-CLOSED: tekshiruv yiqilsa — TAYYOR EMAS. «Bilmadim» ni «mumkin» deb
#     o'qish aynan qaytarib bo'lmaydigan amalda eng qimmat xato bo'lardi.
READINESS_KEYS = ("schema_integrity", "idempotency", "column_types")


def _clean(fn, bind, fail: str) -> list[str]:
    """`fn(bind)` natijasi; istisno yoki kutilmagan tur -> [fail] (ya'ni TAYYOR EMAS).

    Sabab matni (`str(e)`: host, port, foydalanuvchi, reflection SQL) FAQAT JURNALGA —
    `required_schema.missing` izohidagi qoida bilan AYNI.
    """
    try:
        out = fn(bind)
    except Exception as e:      # noqa: BLE001 — matn javobga TUSHMAYDI
        print(f"[schema] partiya tayyorligi tekshirilmadi ({fail}): {e}")
        return [fail]
    return list(out) if isinstance(out, (list, tuple)) else [fail]


def activation_readiness(bind, integrity_problems: list[str] | None = None) -> dict[str, bool]:
    """Qaytarib bo'lmaydigan yoqish uchun BAZA tayyorligi (UI/jarayon EMAS). Keshsiz.

    · `schema_integrity` — `required_schema.missing` (halokatli + FK/CHECK holati).
      Chaqiruvchi uni allaqachon o'qigan bo'lsa `integrity_problems` bilan uzatadi
      (ikki marta introspeksiya qilinmasin).
    · `idempotency`      — pul/qoldiq/auth takror yozuvini to'sadigan noyob indekslar.
    · `column_types`     — uuid bo'lishi shart ustun haqiqatan uuid (Postgres).

    ⚠️  JARAYON tayyorligi BU YERDA EMAS (1C cutover, o'rnatilgan Manager/POS
        yig'malari, backup mashqi, sokin savdo oynasi) — ularni server tekshira
        olmaydi, ular runbook'ning STOP shartlari bo'lib qoladi.
    """
    from app.core import required_schema as _rs

    if integrity_problems is None:
        integrity_problems = _clean(_rs.missing, bind, "introspeksiya yiqildi")
    return {
        "schema_integrity": not integrity_problems,
        "idempotency": not _clean(_rs.idempotency_missing, bind, "idempotentlik o'qilmadi"),
        "column_types": not _clean(_rs.column_type_problems, bind, "ustun tipi o'qilmadi"),
    }
