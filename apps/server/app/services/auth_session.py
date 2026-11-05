"""Refresh sessiyalari — `auth_sessions` jadvali ustidagi YAGONA mantiq.

NEGA BU MODUL BOR. `auth_sessions` modeli reponing birinchi kunlaridan bor
(`db/schema.sql:149` — «refresh tokenlar / qurilmalar») va `ARCHITECTURE.md:219`
`POST /auth/refresh` ni hujjatlashtirgan, lekin kod HECH QACHON yozilmagan:
`account_deletion.py:28` buni ochiq qayd etadi. Natijada yagona kredensial
12 soatlik access token bo'lib qoldi va 12 soatdan uzoq tanaffus to'liq parol
bilan kirishni MAJBUR qilardi (R7.6 auth P0).

ARXITEKTURA (R7.6 audit darvozalari):

  · Har login — ALOHIDA `sid` (`auth_sessions.id`) va alohida kredensial.
  · Kredensial shakli `<sid>.<secret>`; bazada FAQAT keyed-hash
    (`core/security.hash_refresh`). PLAINTEXT HECH QACHON saqlanmaydi.
  · Rotation ATOMAR: bitta `UPDATE … WHERE refresh_hash = :old`.
  · `expires_at` ABSOLYUT — rotation uni UZAYTIRMAYDI. Sessiyaning umri
    chegaralangan (`refresh_token_days`), ya'ni oylik qayta autentifikatsiya.
  · `/auth/logout` TEGILMAYDI: u hamon global `sec_epoch` ni oshiradi, chunki
    POS/Manager AutoLogout va operatsion skriptlar shunga tayanadi. Bitta
    sessiyani bekor qilish — ALOHIDA `/auth/revoke`.
  · `sec_epoch` global bekor qilish leveri sifatida SAQLANADI.
"""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (hash_refresh, new_refresh_secret, refresh_matches,
                               split_refresh)
from app.models.auth import AuthSession


class RefreshError(Exception):
    """Refresh bajarilmadi. [revoked] — sessiya fail-closed bekor qilindi."""

    def __init__(self, reason: str, *, revoked: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.revoked = revoked


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value) -> datetime | None:
    """SQLite `DateTime(timezone=True)` ni naive qaytaradi — UTC deb o'qiymiz.

    ⚠️  Bu TAXMIN emas: `create()` va `rotate()` har doim UTC yozadi, boshqa
        yo'l yo'q. Naive qiymatni mahalliy vaqt deb o'qish muddat tekshiruvini
        mintaqaga bog'lab qo'yardi.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def create(db: Session, employee_id: uuid.UUID, *, terminal_id=None) -> tuple[str, str]:
    """Yangi sessiya. Qaytaradi: (`sid`, xom refresh kredensiali).

    Chaqiruvchi commit qiladi. Xom kredensial FAQAT shu yerda mavjud —
    hech qayerga yozilmaydi va hech qachon jurnalga chiqmaydi.
    """
    secret = new_refresh_secret()
    now = _now()
    row = AuthSession(
        employee_id=employee_id,
        terminal_id=terminal_id,
        refresh_hash=hash_refresh(secret),
        prev_refresh_hash=None,
        rotated_at=None,
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_days),
        revoked_at=None,
    )
    db.add(row)
    db.flush()
    return str(row.id), f"{row.id}.{secret}"


def _load(db: Session, sid: str) -> AuthSession | None:
    try:
        key = uuid.UUID(sid)
    except (ValueError, AttributeError, TypeError):
        return None
    return db.scalar(select(AuthSession).where(AuthSession.id == key)
                     .execution_options(populate_existing=True))


def active(db: Session, sid: str) -> AuthSession | None:
    """Har so'rovdagi tekshiruv uchun: tirik sessiya yoki None.

    `deps.py` shuni ishlatadi — `/auth/revoke` dan keyin o'sha sessiyaning
    access token'i DARHOL ishlamay qoladi (muddati tugashini kutmaydi).
    """
    row = _load(db, sid)
    if row is None or row.revoked_at is not None:
        return None
    exp = _aware(row.expires_at)
    if exp is None or exp <= _now():
        return None
    return row


def revoke(db: Session, sid: str, *, employee_id: uuid.UUID) -> bool:
    """FAQAT shu `sid` ni bekor qiladi. Chaqiruvchi commit qiladi.

    ⚠️  [employee_id] MAJBURIY: bir xodim boshqasining sessiyasini `sid` ni
        taxmin qilib o'chira olmasin.

    ⚠️  KECHIKKAN REVOKE YANGI LOGIN'GA TEGMAYDI (R7.6 audit, 4-band): har
        login YANGI `sid` yaratadi, bu amal esa AYNAN BITTA qatorga yozadi.
        Eski `sid` ning kechikkan revoke'i yangi sessiyani ko'rmaydi ham.
    """
    res = db.execute(
        update(AuthSession)
        .where(AuthSession.id == _uuid_or_none(sid),
               AuthSession.employee_id == employee_id,
               AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now()))
    return (res.rowcount or 0) == 1


def revoke_all(db: Session, employee_id: uuid.UUID) -> int:
    """Xodimning hamma tirik sessiyasi. Parol o'zgarishi / hodisa uchun.

    `sec_epoch` ni OSHIRMAYDI — buni chaqiruvchi hal qiladi (global lever
    o'z joyida qoladi).
    """
    res = db.execute(
        update(AuthSession)
        .where(AuthSession.employee_id == employee_id,
               AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now()))
    return res.rowcount or 0


def _uuid_or_none(sid: str):
    try:
        return uuid.UUID(sid)
    except (ValueError, AttributeError, TypeError):
        return uuid.UUID(int=0)       # hech qachon mos kelmaydi


def rotate(db: Session, raw: str) -> tuple[AuthSession, str]:
    """Kredensialni ALMASHTIRADI va (sessiya, yangi xom kredensial) qaytaradi.

    Chaqiruvchi commit qiladi. To'rt yo'l — ATAYLAB farqlangan:

      1. Sir JORIY xeshga mos  -> atomar rotation, OK.
      2. Sir OLDINGI xeshga mos VA `rotated_at` grace oynasida
         -> parallel so'rovning benign takrori: QAYTA rotation, OK.
         (Ayni yangi kredensialni qaytarish uchun uni plaintext saqlash kerak
          bo'lardi — bu TAQIQLANGAN, shu bois yangisi beriladi.)
      3. Sir OLDINGI xeshga mos, oyna O'TGAN
         -> iste'mol qilingan kredensialning QAYTA ishlatilishi: sessiya
            REVOKE qilinadi (fail-closed).
      4. Hech biriga mos emas
         -> 401, lekin REVOKE QILINMAYDI. Aks holda `sid` ni taxmin qilgan
            hujumchi begona sessiyalarni o'chira olardi (DoS).
    """
    parts = split_refresh(raw)
    if parts is None:
        raise RefreshError("malformed")
    sid, secret = parts
    row = _load(db, sid)
    if row is None:
        raise RefreshError("unknown")
    if row.revoked_at is not None:
        raise RefreshError("revoked")
    exp = _aware(row.expires_at)
    if exp is None or exp <= _now():
        raise RefreshError("expired")

    now = _now()
    if refresh_matches(secret, row.refresh_hash):
        return row, _swap(db, row, row.refresh_hash, now, reason="current")

    if refresh_matches(secret, row.prev_refresh_hash):
        rotated = _aware(row.rotated_at)
        within = (rotated is not None
                  and (now - rotated).total_seconds() <= settings.refresh_grace_seconds)
        if within:
            #  Benign poyga. JORIY xeshdan rotation qilamiz — biz uni o'qiy
            #  olamiz, chaqiruvchi esa o'qiy olmaydi, ya'ni CAS haqiqiy qoladi.
            return row, _swap(db, row, row.refresh_hash, now, reason="grace")
        #  REPLAY. Iste'mol qilingan kredensial oynadan keyin keldi.
        db.execute(update(AuthSession)
                   .where(AuthSession.id == row.id, AuthSession.revoked_at.is_(None))
                   .values(revoked_at=now))
        raise RefreshError("replay", revoked=True)

    raise RefreshError("mismatch")


def _swap(db: Session, row: AuthSession, expect_hash: str, now: datetime,
          *, reason: str) -> str:
    """Atomar CAS: FAQAT [expect_hash] hamon joyida bo'lsa almashtiradi.

    Parallel ikki so'rovdan BITTASI g'alaba qiladi; ikkinchisining `rowcount`
    i 0 bo'ladi va u grace yo'liga tushadi (yoki replay deb baholanadi).
    `expires_at` TEGILMAYDI — sessiyaning absolyut umri uzaymaydi.
    """
    secret = new_refresh_secret()
    res = db.execute(
        update(AuthSession)
        .where(AuthSession.id == row.id,
               AuthSession.refresh_hash == expect_hash,
               AuthSession.revoked_at.is_(None))
        .values(refresh_hash=hash_refresh(secret),
                prev_refresh_hash=expect_hash,
                rotated_at=now))
    if (res.rowcount or 0) != 1:
        #  Poygada yutqazdik: boshqa so'rov AYNI paytda rotation qildi.
        #  Qayta urinmaymiz — mijoz single-flight bilan bitta so'rov yuboradi
        #  va takror urinish cheksiz tsikl yasashi mumkin.
        raise RefreshError("raced")
    db.expire(row)
    return f"{row.id}.{secret}"
