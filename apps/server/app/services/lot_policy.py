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


def confirm_tz(db: Session, company_id, branch_id) -> str:
    """Zonani tasdiqlaydi. Avval yaroqliligi tekshiriladi."""
    name = validate_for_expiry(db, branch_id)
    from app.services import catalog_import_v2 as civ2
    conf = dict(_catalog_settings(db, company_id).get(CONFIRM_FIELD) or {})
    conf[str(branch_id)] = name
    civ2.set_catalog_settings(db, company_id, **{CONFIRM_FIELD: conf})
    return name


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
