"""Umumiy kiritma validatsiyasi — telefon formati, nom tozalash. Barcha modullar shu yerdan.
Telefon qoidasi employees.py bilan bir xil: +996/+998 -> aynan 12 raqam, boshqa kod 10-15."""
from decimal import Decimal

from fastapi import HTTPException

# Numeric(14,2) DB ustunlarining sig'imi (pul/summa maydonlari). Yig'indi yoki qator summasi bundan
# oshsa Postgres "numeric field overflow" (DataError) bilan xom 500 berardi — buni oldindan tekshirib
# do'stona 400 qaytaramiz. Per-field Pydantic bound (le=1e9) yig'indini/ko'paytmani qoplamaydi.
NUMERIC_14_2_MAX = Decimal("999999999999.99")


def guard_amount(value, label: str = "Summa"):
    """value Numeric(14,2) sig'imidan oshsa 400 (500 emas). Har pul yig'indisi/ko'paytmasiga qo'llang."""
    try:
        v = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        raise HTTPException(400, f"{label} noto'g'ri")
    if v > NUMERIC_14_2_MAX or v < -NUMERIC_14_2_MAX:
        raise HTTPException(400, f"{label} juda katta — miqdor yoki narxni tekshiring")
    return v


def like_escape(s: str) -> str:
    """LIKE/ILIKE naqshi uchun maxsus belgilarni qochiradi (% _ \\) — foydalanuvchi '%' yozganda
    HAMMA yozuv mos kelib qolmasin (yoki '_' bilan bittalik joker). Query'да escape='\\' bilan:
    `Col.ilike(f"%{like_escape(q)}%", escape="\\")`."""
    return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def valid_phone(phone: str) -> bool:
    """norm_phone'дан keyin '+' + raqamlar keladi. Bo'sh emas deb faraz qilinadi."""
    digits = phone[1:] if phone.startswith("+") else phone
    if not digits.isdigit():
        return False
    # Faqat HAQIQIY +996/+998 davlat kodi bilan kelганда 12-raqam qoidasi (tasodifan 996/998
    # bilan boshlangan boshqa raqam noto'g'ri rad etilmasin).
    if phone.startswith(("+996", "+998")):
        return len(digits) == 12
    return 10 <= len(digits) <= 15


def require_phone(phone: str):
    """Bo'sh telefon — ixtiyoriy (o'tkazadi); noto'g'ri format -> 400."""
    if phone and not valid_phone(phone):
        raise HTTPException(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")


def clean_name(raw: str | None, field: str = "Nomi", maxlen: int = 200) -> str:
    """Nomni strip qiladi; bo'sh/faqat-bo'shliq -> 400; juda uzunни kesadi."""
    s = (raw or "").strip()
    if not s:
        raise HTTPException(400, f"{field} kiritilishi kerak")
    return s[:maxlen]
