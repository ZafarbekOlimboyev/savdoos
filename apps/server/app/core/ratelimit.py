# -*- coding: utf-8 -*-
"""Umumiy (bo'linadigan) brute-force cheklovi — PostgreSQL asosida.

⚠️  NEGA XOTIRA EMAS. Kassir cheklovlari jarayon xotirasida edi: har deploy'da
    nolga tushardi va instanslar o'rtasida bo'linmasdi. Vendor yo'lida bu naqsh
    allaqachon isbotlangan, shu bois o'sha naqsh takrorlanadi — yangi
    infratuzilma (Redis) qo'shilmaydi, chunki loyihada u YO'Q.

⚠️  DO'KON QATLAMI QATTIQ RAD ETMAYDI. Phase 1 da aynan shu narsa DoS bo'lgan
    edi: `company_code` ni bilgan istalgan kishi 25 ta soxta PIN yuborib butun
    do'konni kassadan uzardi. Shuning uchun do'kon qatlami faqat SEKINLASHTIRADI.

⚠️  SAQLASH ISHLAMASA — YO'L OCHILMAYDI. Cheklovni o'lchay olmagan holatda
    urinishga ruxsat berish "cheklov bor" degan da'voni yolg'onga aylantiradi.
    Kassir yo'lida bu 503 (xizmat vaqtincha yo'q), ya'ni fail-closed.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.models.security import AuthAttempt

# ── Qatlamlar: (max_fails, window_seconds, xabar) ───────────────────────────
IP_TIER = (10, 300, "Juda ko'p urinish — 5 daqiqadan keyin qayta urining")
ACCT_TIER = (12, 900, "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring")
CAND_TIER = (5, 900, "Juda ko'p urinish — birozdan keyin qayta urining")

# Do'kon qatlami — SEKINLASHTIRISH (rad etish EMAS)
STORE_SOFT = 25
STORE_WINDOW = 900
STORE_STEP = 0.25
STORE_DELAY_MAX = 3.0

_MAX_WINDOW = max(IP_TIER[1], ACCT_TIER[1], CAND_TIER[1], STORE_WINDOW)

# ⚠️  TAHDID TAHLILI VA NEGA TUZ `SECRET_KEY` DAN OLINADI.
#
#     4 raqamli PIN fazosi 10 000 ta, ya'ni PIN'ning oddiy `sha256` i rainbow-table
#     bilan bir soniyada qaytariladi. Shu bois nomzod kaliti HMAC bilan tuzlanadi.
#
#     Tuz JARAYONGA XOS BO'LMASLIGI kerak: `os.urandom` bilan har instans BOSHQA
#     kalit hisoblardi va (a) ikki replika bir-birining hisoblagichini KO'RMASDI,
#     (b) har deploy'dan keyin nomzod qatlami NOLGA tushardi — ya'ni "umumiy va
#     restart'dan omon qoladigan cheklov" degan maqsad aynan shu qatlamda
#     bajarilmasdi.
#
#     `SECRET_KEY` esa barcha replikalarda BIR XIL, bazada SAQLANMAYDI va
#     allaqachon kuch siyosatidan o'tadi. Bazani o'qigan tomon kalitlardan PIN'ni
#     tiklay olmaydi. Qolaversa, bu kalitlar faqat NOTO'G'RI urinishlar uchun
#     yoziladi — ya'ni ular hech qachon HAQIQIY PIN'ni oshkor qilmaydi.
def _pin_salt() -> bytes:
    from app.core.config import settings
    return hashlib.sha256(("pin-bucket|" + settings.secret_key).encode()).digest()

_last_prune = [0.0]


def candidate_bucket(company_id, pin: str) -> str:
    """(do'kon, PIN qiymati) uchun qaytarib bo'lmaydigan kalit."""
    mac = hmac.new(_pin_salt(), f"{company_id}|{pin}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


# ⚠️  TELEFON CHELAGI — NEGA XOM RAQAM SAQLANMAYDI (S1-F9A).
#
#     Ilgari parol-login yo'li `("acct", f"pw:{phone}", None)` yozardi, ya'ni
#     ijarachi EGASINING telefon raqami OCHIQ MATNDA (`norm_phone` dan keyin)
#     `auth_attempts.bucket` ga tushardi. Ikki mustaqil oqibati O'LCHANGAN:
#
#       1. Telefon — `app/static/privacy.html` SHAXSIY MA'LUMOT sifatida
#          aniq sanaydigan maydon (hujjat uni ikki joyda ochiq nomlaydi).
#          ⚠️  Ilgari bu yerda tirnoq ichida «Hisob ma'lumotlari» degan
#              BO'LIM NOMI keltirilgan edi — bunday sarlavha hujjatda YO'Q.
#              Mazmun to'g'ri, HAVOLА noto'g'ri edi; tuzatildi.
#       2. Qator `company_id=None` bilan yoziladi, shu bois `tools/tenant_purge`
#          predikati (`"company_id" = :cid`) UNKNOWN qaytaradi: do'kon
#          o'chirilganda ham qator QOLADI va «nol qoldiq» tekshiruvi ham uni
#          KO'RMAYDI (u AYNI predikatni qayta ishlatadi). `models/security.py`
#          docstringi esa `company_id IS NULL` qatorlarni FAQAT «IP qatlami»
#          deb ta'riflaydi — ya'ni purge siyosatining yozma asosi bu o'lchov
#          uchun YOLG'ON edi.
#
#     NEGA HMAC, NEGA TUZSIZ `sha256` EMAS: telefon fazosi SANOQLI — milliy
#     prefiks + 7..9 raqam, ya'ni 10^7..10^9 nomzod. Tuzsiz digest lug'at
#     hujumi bilan darhol qaytariladi, ya'ni u himoya BERMAYDI (ayni xulosani
#     bu modul PIN uchun yuqorida allaqachon yozgan).
#
#     NEGA TUZ `SECRET_KEY` DAN: `_pin_salt` bilan AYNI sabablar — barcha
#     replikalarda bir xil, bazada SAQLANMAYDI, restart'dan omon qoladi va
#     kuch siyosatidan o'tadi (`core/security_config`: production'da zaif
#     kalit bilan boot FAIL-CLOSED).
#
#     NEGA ALOHIDA DOMEN PREFIKSI: `"acct-bucket|"` != `"pin-bucket|"`, ya'ni
#     hisob chelagi hech qachon nomzod-PIN chelagi bilan TO'QNASHMAYDI —
#     aks holda bir o'lchovdagi urinish boshqasining hisoblagichini surardi.
def _acct_salt() -> bytes:
    from app.core.config import settings
    return hashlib.sha256(("acct-bucket|" + settings.secret_key).encode()).digest()


def account_bucket(phone: str) -> str:
    """Telefon raqami uchun BARQAROR, qaytarib bo'lmaydigan kalit.

    Barqarorlik SHART: kalit har chaqiruvda o'zgarsa hisoblagich nolga
    tushardi va hisob qatlami umuman ishlamasdi.
    """
    mac = hmac.new(_acct_salt(), (phone or "").encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


# ⚠️  IP CHELAGI — NEGA XOM MANZIL SAQLANMAYDI (S1-F9F, ADMIN-1.0/P0-A da
#     kengaytirildi).
#
#     Ilgari chaqiruv joylari XOM manzilni f-satrga qo'yardi — ya'ni MIJOZ IP
#     MANZILI OCHIQ MATNDA `auth_attempts.bucket` va
#     `vendor_auth_attempts.bucket` ga tushardi. Tuzatishdan OLDINGI BESH
#     yozuvchi (`origin/main` = `2457b98a` da o'lchangan):
#
#         api/v1/auth.py:292    f"pin:{ip}"    / f"pin:?:{employee_id}"
#         api/v1/auth.py:355    f"pw:{ip}"     / f"pw:?:{phone or '-'}"   ← TELEFON
#         api/v1/auth.py:568    f"del:{ip}"    / f"del:?:{emp.id}"
#         api/v1/auth.py:764    f"close:{ip}"  / f"close:?:{emp.id}"
#         api/v1/admin.py:172   f"ip:{ip}"
#
#     ⚠️  OXIRGI IKKITASI S1-F9F DAN KEYIN PAYDO BO'LGAN. S1-F9F `8d5c4bcd`
#         ustida yozilgan va faqat `pin`/`pw`/`ip` ni qamragan; hisob o'chirish
#         (CH-18A..D) va do'kon yopish yo'llari keyinroq qo'shilgan. Shuning
#         uchun `IP_PATHS` ADMIN-1.0 P0-A da `del`/`close` bilan kengaytirildi.
#         Testlar: `tests/test_auth_ip_privacy.py::test_F9F_19..23`.
#
#     Uch o'lchangan oqibat:
#
#       1. IP — `app/static/privacy.html` da ANIQ tan olingan shaxsiy ma'lumot
#          («kirish urinishlari yozuvlarida IP manzil bo'lishi mumkin»).
#       2. `auth_attempts` ning `ip` o'lchovi `company_id=None` bilan yoziladi,
#          shu bois `tools/tenant_purge` predikati (`"company_id" = :cid`)
#          UNKNOWN qaytaradi: do'kon o'chirilganda ham qator QOLADI va «nol
#          qoldiq» tekshiruvi ham uni KO'RMAYDI (u AYNI predikatni qayta
#          ishlatadi).
#       3. `vendor_auth_attempts` da TOZALASH KODI UMUMAN YO'Q (`_prune` ga teng
#          narsa yozilmagan), ya'ni u yerda qator MUDDATSIZ qoladi.
#
#     NEGA XULQ O'ZGARMAYDI (o'lchangan, taxmin emas): `bucket` HECH QAYERDA
#     qayta o'qilmaydi — faqat TENGLIK bilan solishtiriladi (`_count`,
#     `clear`, `admin.py` dagi vendor `count`). Chelak QIYMATINI almashtirish
#     ekvivalentlik SINFLARINI saqlaydi, ya'ni chegara, oyna va 429 bir xil
#     qoladi.
#
#     NEGA TUZSIZ `sha256` EMAS: IPv4 fazosi 2^32 — to'liq jadval arzon
#     (ayni xulosa bu modulda PIN va telefon uchun allaqachon yozilgan).
#     Tuz `SECRET_KEY` dan: `_pin_salt` bilan AYNI sabablar.
#
#     NEGA YO'L HMAC KIRISHIGA QO'SHILADI, faqat prefiks EMAS: namespace'lar
#     AJRATILGAN qolishi SHART. Aks holda `pin` yo'lidagi urinishlar `pw`,
#     `del`, `close` yoki vendor hisoblagichini surardi — ya'ni kassirga
#     qilingan hujum vendor portalini yoki hisob o'chirishni bloklardi.
#
#     NEGA YO'LLAR YOPIQ TO'PLAM: `"pwd"` kabi IMLO XATOSI jim yangi
#     namespace ochib, o'sha yo'ldagi cheklovni NOLGA tushirardi. Yopiq
#     to'plam buni ValueError bilan ko'rsatadi, test esa chaqiruv joylaridagi
#     literallarni STATIK tekshiradi (`test_F9F_18`).
#
#     NEGA O'QILADIGAN PREFIKS QOLDIRILADI: prefiks shaxsiy ma'lumot EMAS,
#     lekin `dimension='ip'` ichida yo'llarni ajratib turadi (operator uchun).
#
#     ⚠️  BU TUZATISH QAMRAMAYDIGAN NARSA, ochiq aytiladi: `acct` o'lchovi
#         HAMON XOM identifikator saqlaydi — `pin:{employee_id}`,
#         `chpw:{emp.id}`, `del:{emp.id}`, `close:{emp.id}`. Ular ICHKI UUID
#         lar (telefon yoki IP kabi tashqi shaxsiy ma'lumot EMAS).
#
#         ⚠️  PURGE XULQI ULAR UCHUN BIR XIL EMAS (mustaqil ko'rik tuzatdi;
#             ilgari bu yerda «ular HAM `company_id=None` bilan yoziladi»
#             deb yozilgan edi va bu `chpw` uchun NOTO'G'RI edi):
#               · `pin:{employee_id}`, `del:{emp.id}`, `close:{emp.id}`
#                 -> `company_id=None` (purge'dan OMON QOLADI);
#               · `chpw:{emp.id}` -> `RL.guard/record/clear(..., emp.company_id)`
#                 (`api/v1/auth.py` parol o'zgartirish yo'li), ya'ni u
#                 do'konga BOG'LANGAN va purge predikatiga TUSHADI.
#         Buni o'zgartirish ALOHIDA qaror (S1-F8 D4) va bu yerda BAJARILMAYDI;
#         `test_F9F_13` va `test_F9F_22` holatni ATAYLAB qadaydi.
#
#     ⚠️  TUZATILGAN DA'VO (mustaqil ko'rik topdi): vendor jadvalida `flow:`
#         qatorlari AMALDA YO'Q. `admin.py` `_rate_record` DOIM `bucket_ip`
#         bilan chaqiriladi, ya'ni `"flow:vendor"` chelagini HECH KIM YOZMAYDI
#         va `_rate_guard(db, "flow:vendor", ...)` DOIM 0 sanaydi — vendor
#         oqimining GLOBAL cheklovi (20 / 3600 s) HECH QACHON ishlamaydi. Bu
#         S1-F9F dan OLDIN ham shunday edi va bu tuzatish uni O'ZGARTIRMAYDI;
#         alohida topilma sifatida hisobotda qayd etilgan.
#
#     O'TISH DAVRI CHEKLOVI — ANIQ CHEGARALAR (mustaqil ko'rikdan keyin
#     TUZATILDI; ilgari «`acct` va `cand` TEGILMAGAN» deb yozilgan va bu
#     NOTO'G'RI edi):
#
#       · DEPLOY. `ip` o'lchovidagi eski formatli qatorlar yangi chelak bilan
#         teng emas -> IP hisoblagichi BIR MARTA nolga tushadi (IP uchun
#         300 s, vendor uchun 900 s). AYNI relizda S1-F9A parol yo'lining
#         `acct` chelagini ham `f"pw:{phone}"` dan `account_bucket(phone)` ga
#         o'tkazadi, ya'ni O'SHA qatlam ham bir marta (900 s) nolga tushadi.
#         Kalitga BOG'LANMAGAN chelaklar omon qoladi: `pin:{employee_id}`,
#         `chpw:{id}`, `del:{id}`, `close:{id}` va `store` qatlamidagi
#         `str(company_id)`.
#
#       · `SECRET_KEY` ALMASHTIRISH. Uchala tuz ham AYNI kalitdan olinadi
#         (`_pin_salt`, `_acct_salt`, `_ip_salt`), shu bois `ip`, parol
#         yo'lidagi `acct` VA `cand` qatlamlari BIRGALIKDA nolga tushadi.
#         Ya'ni kalit rotatsiyasi hujumchiga qisqa muddatli (eng ko'pi 900 s)
#         yangi byudjet beradi — bu rotatsiya qarorida hisobga OLINISHI kerak.
#
#       · ARALASH VERSIYALI replikalar bir vaqtda ishlagan oynada har versiya
#         FAQAT o'z qatorlarini sanaydi.
IP_PATHS = frozenset({
    "pin", "pin:?",          # POS PIN login       (auth.py `login_pin`)
    "pw", "pw:?",            # ega/admin parol     (auth.py `login_password`)
    "del", "del:?",          # o'z hisobini o'chirish (auth.py `delete_own_account`)
    "close", "close:?",      # do'konni yopish     (auth.py `close_own_store`)
    "ip",                    # vendor konsoli      (admin.py `_vendor_rate_check`)
})


def _ip_salt() -> bytes:
    from app.core.config import settings
    return hashlib.sha256(("ip-bucket|" + settings.secret_key).encode()).digest()


def ip_bucket(path: str, value: str) -> str:
    """(autentifikatsiya yo'li, manba) uchun BARQAROR, qaytarib bo'lmaydigan kalit.

    `path` — `IP_PATHS` dagi qiymat; `value` — mijoz IP'si yoki zaxira manba.
    Qaytadi: `"<path>:<32 hex>"`.
    """
    if path not in IP_PATHS:
        raise ValueError("ip_bucket: noma'lum yo'l %r (IP_PATHS ga qarang)" % (path,))
    mac = hmac.new(_ip_salt(), ("%s|%s" % (path, value or "")).encode("utf-8"),
                   hashlib.sha256)
    return "%s:%s" % (path, mac.hexdigest()[:32])


def _prune(db) -> None:
    """Eskirgan yozuvlarni tozalaydi — jadval cheksiz o'smasin."""
    now = time.time()
    if now - _last_prune[0] < 300:          # har 5 daqiqada bir marta (arzon)
        return
    _last_prune[0] = now
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_MAX_WINDOW)
    db.execute(delete(AuthAttempt).where(AuthAttempt.occurred_at < cutoff))
    db.commit()


def _count(db, dimension: str, bucket: str, window: int, company_id=None) -> int:
    since = datetime.now(timezone.utc) - timedelta(seconds=window)
    q = (select(func.count()).select_from(AuthAttempt)
         .where(AuthAttempt.dimension == dimension,
                AuthAttempt.bucket == bucket,
                AuthAttempt.occurred_at >= since))
    if company_id is not None:
        q = q.where(AuthAttempt.company_id == company_id)
    return db.execute(q).scalar() or 0


def guard(db, dimension: str, bucket: str, tier: tuple, company_id=None) -> None:
    """Chegara oshsa 429. Oyna bilan cheklangan — DOIMIY blok yo'q."""
    max_fails, window, msg = tier
    try:
        _prune(db)
        n = _count(db, dimension, bucket, window, company_id)
    except HTTPException:
        raise
    except Exception as e:                   # noqa: BLE001
        db.rollback()
        raise HTTPException(503, "Xavfsizlik cheklovini tekshirib bo'lmadi") from e
    if n >= max_fails:
        raise HTTPException(429, msg)


def over_limit(db, dimension: str, bucket: str, tier: tuple, company_id=None) -> bool:
    """Chegara oshganmi — 429 OTMAYDI, faqat javob qaytaradi.

    ⚠️  NEGA ALOHIDA. `guard` 429 otadi va o'sha 429 ba'zi yo'llarda OSHKOR
        QILUVCHI bo'lib qoladi: agar qatlam faqat MA'LUM shartda ishlasa,
        "429 keldi" degan javobning o'zi shu shart bajarilganini tasdiqlaydi.
        Bunday joylarda chaqiruvchi cheklovni qo'llaydi, lekin javobni
        boshqa xatolar bilan BIR XIL qiladi.

    ⚠️  Saqlash ishlamasa — YO'L OCHILMAYDI (fail-closed): `guard` bilan izchil
        ravishda 503 ko'tariladi."""
    max_fails, window, _ = tier
    try:
        _prune(db)
        n = _count(db, dimension, bucket, window, company_id)
    except HTTPException:
        raise
    except Exception as e:                   # noqa: BLE001
        db.rollback()
        raise HTTPException(503, "Xavfsizlik cheklovini tekshirib bo'lmadi") from e
    return n >= max_fails


def record(db, entries) -> None:
    """Muvaffaqiyatsiz urinishlarni qayd etadi: [(dimension, bucket, company_id), ...]."""
    now = datetime.now(timezone.utc)
    try:
        for dimension, bucket, company_id in entries:
            db.add(AuthAttempt(dimension=dimension, bucket=bucket,
                               company_id=company_id, occurred_at=now))
        db.commit()
    except Exception:                        # noqa: BLE001
        db.rollback()
        raise


def clear(db, entries) -> None:
    """Muvaffaqiyatli kirishda tanlangan o'lchovlarni tozalaydi.

    ⚠️  Do'kon qatlami ATAYLAB tozalanmaydi: aks holda insider "9 xato + o'z
        PIN'i bilan 1 kirish" sikli bilan hisoblagichni nolga tushirib,
        hamkasb PIN'ini cheksiz taxmin qilardi."""
    try:
        for dimension, bucket, company_id in entries:
            q = delete(AuthAttempt).where(AuthAttempt.dimension == dimension,
                                          AuthAttempt.bucket == bucket)
            if company_id is not None:
                q = q.where(AuthAttempt.company_id == company_id)
            db.execute(q)
        db.commit()
    except Exception:                        # noqa: BLE001
        db.rollback()


def store_backoff(db, company_id) -> float:
    """Do'kon bo'yicha xatolar ko'p bo'lsa KECHIKISH (rad etish EMAS)."""
    try:
        n = _count(db, "store", str(company_id), STORE_WINDOW, company_id)
    except Exception:                        # noqa: BLE001
        db.rollback()
        return 0.0
    over = n - STORE_SOFT
    if over <= 0:
        return 0.0
    return min(over * STORE_STEP, STORE_DELAY_MAX)
