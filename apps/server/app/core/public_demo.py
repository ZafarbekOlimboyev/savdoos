"""OMMAVIY DEMO HISOBI — server tomonidan majburlanadigan FAQAT-O'QISH identifikatori.

Belgi (marker):
    Setting(company_id=<demo do'kon>, branch_id=NULL, key='public_demo_viewer')
    value = {"employee_id": "<uuid>", "phone": "+998...", "note": "..."}

⚠️  NEGA SOZLAMA QATORI, NEGA YANGI USTUN EMAS:
    bu kalitni `PUT /settings` YOZA OLMAYDI — `api/v1/settings.py:_validate_value`
    noma'lum kalitni 400 qiladi; `api/v1/admin.py` ham faqat `plan`, `store_info`,
    `suspended` yozadi. Ya'ni belgini FAQAT DB darajasidagi migratsiya qo'yadi —
    tenant egasi ham, vendor admin ham API orqali yarata olmaydi. Shu bois sxema
    migratsiyasi (yangi ustun) KERAK EMAS va production DDL'ga tegilmaydi.

⚠️  DARVOZA QAYERDA: `core/deps.get_current_employee` — AVTORIZATSIYA TALAB QILGAN
    HAR BIR marshrut shu yerdan o'tadi. Shu bois ruxsat ro'yxatiga (`require(...)`)
    tayanmaydi: kelajakda ruxsatsiz qo'shilgan yozuv marshruti ham YOPIQ bo'ladi
    (fail-closed). `POST /auth/password`, `POST /auth/account-deletion`,
    `POST /cash/ops`, smena marshrutlari — hammasi 403.

⚠️  `POST /auth/logout` ISTISNO: u 403 QILINMAYDI, balki NO-OP bo'ladi
    (`api/v1/auth.logout`). Sababi — demo hisobi UMUMIY: `sec_epoch` oshishi
    shu paytda demo ko'rayotgan BOSHQA hamma odamning sessiyasini uzardi.

Oddiy mijoz tenantlariga ta'siri YO'Q: belgi qatori bo'lmasa funksiya darhol qaytadi.
"""
from __future__ import annotations

import time
import uuid as _uuid

from fastapi import HTTPException, status

PUBLIC_DEMO_KEY = "public_demo_viewer"

#: O'qish metodlari — demo hisobiga ruxsat etiladi.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: NO-OP qilinadigan yagona yozuv marshruti (umumiy sessiyalarni uzmaslik uchun).
LOGOUT_SUFFIX = "/auth/logout"

DEMO_DENY_MSG = "Ommaviy demo hisobi — faqat ko'rish uchun. Yozuv amallari o'chirilgan."


def is_viewer(emp, setting) -> bool:
    """`emp` AYNAN shu do'konning ommaviy demo ko'ruvchisimi."""
    if setting is None or emp is None:
        return False
    vid = (setting.value or {}).get("employee_id")
    if not vid:
        return False
    return str(vid) == str(emp.id)


def demo_phone(setting) -> str | None:
    if setting is None:
        return None
    ph = (setting.value or {}).get("phone")
    return str(ph) if ph else None


def mark_and_guard(request, emp, setting) -> bool:
    """Demo bo'lsa `request.state.public_demo = True` qo'yadi; yozuv bo'lsa 403.

    Qaytaradi: shu xodim demo ko'ruvchisi ekanligi (chaqiruvchiga ma'lumot uchun).
    """
    if not is_viewer(emp, setting):
        return False
    if request is not None:
        request.state.public_demo = True
    method = (getattr(request, "method", None) or "POST").upper()
    if method in SAFE_METHODS:
        return True
    path = str(getattr(getattr(request, "url", None), "path", "") or "")
    if path.rstrip("/").endswith(LOGOUT_SUFFIX):
        return True          # NO-OP marshruti — `auth.logout` o'zi hal qiladi
    raise HTTPException(status.HTTP_403_FORBIDDEN, DEMO_DENY_MSG)


# --------------------------------------------------------------------------
# TEZLIK CHEKLOVI (rate limit) — UMUMIY HISOB MUAMMOSI
# --------------------------------------------------------------------------
#  Muammo: `login_password` hisob qatlamini `pw:{telefon}` kaliti bilan ushlaydi
#  (ACCT_TIER = 12 urinish / 900 s). Bu kalit BITTA ODAMGA tegishli hisob uchun
#  to'g'ri. Ommaviy demo esa UMUMIY: butun internet bitta telefonga kiradi, va
#  har xil odamlarning tasodifiy xato yozishi UMUMIY hisoblagichni to'ldiradi —
#  natijada demo 15 daqiqaga HAMMA uchun yopilib qolardi (o'z-o'ziga DoS).
#
#  Yechim (TOR DOIRADA): FAQAT demo telefoni uchun hisob qatlami o'tkaziladi.
#    · IP qatlami (IP_TIER = 10/300 s) JOYIDA QOLADI — bitta manbadan kelgan
#      taxmin hujumi avvalgidek bloklanadi.
#    · Demo parolining siri YO'Q (u ommaviy e'lon qilinadi) va hisob HECH NARSA
#      yoza olmaydi — ya'ni bu yerda himoyalanadigan maxfiylik yo'q.
#    · Oddiy mijoz hisoblarida HECH NARSA o'zgarmaydi.
#
#  ⚠️  IMTIYOZNI O'G'IRLASHGA QARSHI: telefon shunchaki sozlamada yozilgani
#      uchun yetarli EMAS — u AYNAN shu do'kon ichidagi, parolli, o'chirilmagan
#      xodimga tegishli bo'lishi SHART. Belgi kaliti `PUT /settings` orqali
#      yozilmaydi (yuqoridagi izoh), demak tenant egasi birovning telefonini
#      cheklovdan chiqarib qo'ya olmaydi.
_PHONES_TTL = 60.0
_phones_cache: tuple[float, frozenset] | None = None


def demo_login_phones(db) -> frozenset:
    """Cheklovdan ozod qilinadigan demo telefonlari (60 s keshlanadi)."""
    global _phones_cache
    now = time.monotonic()
    if _phones_cache is not None and (now - _phones_cache[0]) < _PHONES_TTL:
        return _phones_cache[1]
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    from app.models.settings import Setting
    out: set[str] = set()
    for r in db.query(Setting).filter(Setting.key == PUBLIC_DEMO_KEY).all():
        v = r.value or {}
        ph, eid = v.get("phone"), v.get("employee_id")
        if not ph or not eid:
            continue
        #  ⚠️  ID JSON'da SATR — UUID'ga AYNAN keltiriladi. Satr holida
        #      `db.get()` xodimni TOPMAYDI (va PG'da tip xatosi beradi), ya'ni
        #      imtiyoz JIM ishlamasdi (testda o'lchandi: 13-urinishda 429).
        try:
            emp = db.get(Employee, _uuid.UUID(str(eid)))
        except (ValueError, TypeError, AttributeError):
            continue
        if (emp is not None and emp.company_id == r.company_id and emp.phone == ph
                and emp.password_hash and emp.deleted_at is None
                and emp.status == EmployeeStatus.active):
            out.add(str(ph))
    _phones_cache = (now, frozenset(out))
    return _phones_cache[1]


def reset_phones_cache() -> None:
    """Testlar uchun: keshni tozalash."""
    global _phones_cache
    _phones_cache = None
