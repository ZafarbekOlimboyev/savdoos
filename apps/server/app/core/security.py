from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

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


def create_access_token(subject: str, extra: dict | None = None,
                        minutes: int | None = None) -> str:
    """Access token. [minutes] berilmasa `access_token_minutes` (legacy, 720).

    Refresh sessiyasidagi token QISQA TTL oladi — qarang
    `config.session_access_token_minutes` izohi (rollback xavfi).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes or settings.access_token_minutes),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


#  Refresh kredensiali: `<sid>.<secret>`. `sid` qidirish uchun, `secret` esa
#  tekshirish uchun. Sir 32 bayt `secrets.token_urlsafe` — PAROL EMAS, shu bois
#  bcrypt kerak emas va mumkin ham emas (atomar rotation deterministik xesh
#  talab qiladi). Qarang `models/auth.AuthSession.refresh_hash` izohi.
REFRESH_SECRET_BYTES = 32


def new_refresh_secret() -> str:
    return secrets.token_urlsafe(REFRESH_SECRET_BYTES)


def hash_refresh(secret: str) -> str:
    """HMAC-SHA256(secret_key, secret) — deterministik, server kalitiga bog'langan.

    Kalitga bog'langani muhim: baza dump'i o'g'irlansa ham xeshlardan
    kredensial tiklanmaydi (kalit `SECRET_KEY` da, bazada emas).
    """
    return hmac.new(settings.secret_key.encode("utf-8"),
                    secret.encode("utf-8"), hashlib.sha256).hexdigest()


def refresh_matches(secret: str, stored: str | None) -> bool:
    """Doimiy vaqtli solishtirish — xesh taqqoslashda ham timing oqmasin."""
    if not stored:
        return False
    return hmac.compare_digest(hash_refresh(secret), stored)


def split_refresh(raw: str) -> tuple[str, str] | None:
    """`<sid>.<secret>` -> (sid, secret). Shakl buzilgan bo'lsa None."""
    if not raw or raw.count(".") != 1:
        return None
    sid, secret = raw.split(".", 1)
    if not sid or not secret:
        return None
    return sid, secret


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm],
            # python-jose kalitlari: muddatsiz/subject'siz token rad etiladi
            options={"require_exp": True, "require_sub": True, "verify_exp": True},
        )
    except JWTError as e:
        raise ValueError("invalid token") from e
    if payload.get("type") != "access":  # faqat access token — refresh/boshqa turlar rad
        raise ValueError("invalid token type")
    return payload
