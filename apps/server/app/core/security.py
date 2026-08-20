from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(raw: str) -> str:
    # bcrypt 72 baytdan uzun parolni qabul qilmaydi — qo'lda qisqartiramiz (PIN uchun ahamiyatsiz)
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def norm_phone(raw: str | None) -> str:
    """Telefonni login uchun bitta kanonik shaklga keltiradi: '+' + faqat raqamlar.
    "+996 700 111 222" == "996700111222" == "+996700111222" -> "+996700111222".
    Bo'sh bo'lsa bo'sh qaytadi. Saqlash va login bir xil shakldan foydalanadi."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return "+" + digits if digits else ""


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as e:
        raise ValueError("invalid token") from e
