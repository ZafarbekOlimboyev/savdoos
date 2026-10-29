# -*- coding: utf-8 -*-
"""TASHQI AI GA RASM YUBORISHGA ROZILIK — SERVER TOMONDA MAJBURLANADI (CH-16).

QOIDA. Nakladnoy surati tashqi AI provayderiga (Google Gemini yoki Anthropic
Claude) YUBORILADI, ya'ni u do'kon nazoratidan chiqadi. Bu uzatish do'kon AYNAN
shu provayderga rozilik bergandan KEYIN va faqat shundan keyin bajariladi.

⚠️  MIJOZ YUBORGAN BAYROQ ROZILIK DALILI EMAS. `POST /receiving/scan` so'rovida
    `consent: true` kabi maydon UMUMAN YO'Q va bo'lmaydi: uni istalgan mijoz
    (yoki qo'lda yozilgan so'rov) qo'yib yuborardi. Dalil — SERVERDA saqlangan
    yozuv: `Setting(company_id, branch_id=NULL, key="ai_consent")`.

⚠️  SXEMA O'ZGARMAYDI. `Setting` — mavjud umumiy kalit->JSONB do'koni
    (`models/settings.py:42`, `UNIQUE(company_id, branch_id, key)`), repoda
    allaqachon `payments`/`features`/`store_info`/`cash`/`suspended` uchun
    ishlatiladi. Rozilik — YANGI QATOR, yangi ustun emas: migratsiya ham,
    buzuvchi API o'zgarishi ham kerak emas.

⚠️  NEGA ALOHIDA KALIT VA ALOHIDA ENDPOINT. `PUT /settings` ning `features` va
    `security` kalitlari IXTIYORIY maydon nomlarini qabul qiladi va ularni
    `bool` ga keltiradi (`api/v1/settings.py:75-82`) — ya'ni rozilikni o'sha
    kalitlar ichida saqlash `sozlamalar.edit` huquqi bo'lgan mijozga uni
    SOXTALASHTIRISH yo'lini ochardi. `_validate_value` esa NOMA'LUM kalitni
    RAD etadi (`:95`), shu bois `"ai_consent"` ni umumiy endpoint orqali
    yozib bo'lmaydi va yagona yozuvchi — shu moduldagi `grant`.

⚠️  SERVER EGALIK QILADIGAN MAYDONLAR. `provider`, `model`, `granted_at` va
    `employee_id` ni MIJOZ YUBORMAYDI — ular serverda aniqlanadi. Mijoz faqat
    O'ZI KO'RSATGAN oshkor etish versiyasini (`disclosure_version`) bildiradi,
    shuning uchun eski mijoz yangi matnga rozilik bergan bo'lib ko'rinmaydi.
    (`api/v1/historical_exec.py:117` `SERVER_OWNED` bilan AYNI naqsh.)

FAIL-CLOSED. Rozilik yo'q / boshqa provayder uchun / eski versiya uchun bo'lsa —
rasm UZATILMAYDI va operator QO'LDA KIRIM yo'lida ishlashda davom etadi.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.core.config import settings
from app.models.settings import Setting

#  `_validate_value` (api/v1/settings.py) bu kalitni BILMAYDI -> umumiy
#  `PUT /settings` orqali yozib bo'lmaydi. Bu ataylab.
CONSENT_KEY = "ai_consent"

#  Oshkor etish matni O'ZGARSA bu raqam oshadi va eski rozilik KUCHINI YO'QOTADI.
#  Matnning o'zi mijozda (tarjima qilinadi), bu yerda esa faqat versiya.
DISCLOSURE_VERSION = 1

#  Provayder identifikatori — operatorga KO'RSATILADIGAN nom bilan birga.
#  «Tashqi AI» kabi umumiy ibora YETARLI EMAS: ega qaysi kompaniyaga ma'lumot
#  ketayotganini bilishi kerak.
PROVIDERS = {
    "gemini": "Google Gemini (Google LLC)",
    "anthropic": "Anthropic Claude (Anthropic PBC)",
}


def active_provider() -> tuple[str | None, str | None]:
    """HOZIR ishlatiladigan provayder — `receiving_ai.read_invoice` bilan AYNI tartib.

    ⚠️  `read_invoice` da ZAXIRA (fallback) YO'Q: `if settings.gemini_enabled`
        bo'lsa FAQAT Gemini ishlatiladi va u yiqilsa `error:` qaytadi — Claude'ga
        o'tmaydi. Ya'ni provayder RUNTIME'da emas, KONFIGURATSIYA bilan
        almashadi. Shu bois rozilik ayni shu tanlovga bog'lanadi: konfiguratsiya
        o'zgarsa, saqlangan `provider` mos kelmaydi va uzatish TO'XTAYDI.
    """
    if settings.gemini_enabled:
        return "gemini", settings.gemini_model
    if settings.ai_enabled:
        return "anthropic", settings.ai_model
    return None, None            # kalit yo'q -> demo rejim, TASHQI UZATISH YO'Q


def _row(db: Session, company_id):
    return (db.query(Setting)
            .filter(Setting.company_id == company_id,
                    Setting.branch_id.is_(None),
                    Setting.key == CONSENT_KEY)
            .order_by(Setting.row_version.desc())
            .first())


def read(db: Session, company_id) -> dict:
    row = _row(db, company_id)
    return dict(row.value or {}) if row is not None else {}


def status(db: Session, company_id) -> dict:
    """Mijoz uchun holat: dialog kerakmi va QAYSI provayder nomlanadi."""
    provider, model = active_provider()
    saqlangan = read(db, company_id)
    talab = provider is not None          # demo rejimda rozilik KERAK EMAS
    berilgan = bool(
        provider is not None
        and saqlangan.get("provider") == provider
        and int(saqlangan.get("disclosure_version") or 0) >= DISCLOSURE_VERSION
    )
    return {
        "required": talab,
        "granted": berilgan,
        "provider": provider,
        "provider_name": PROVIDERS.get(provider or "", None),
        "model": model,
        "disclosure_version": DISCLOSURE_VERSION,
        "granted_at": saqlangan.get("granted_at") if berilgan else None,
        # Ilgari BOSHQA provayderga rozilik berilgan bo'lsa — mijoz nega qayta
        # so'rayotganini tushuntirishi uchun.
        "previous_provider": (saqlangan.get("provider")
                              if saqlangan.get("provider") not in (None, provider) else None),
    }


def grant(db: Session, emp, disclosure_version: int) -> dict:
    """Rozilikni YOZADI. Provayder/model/vaqt/xodim — SERVERDAN."""
    provider, model = active_provider()
    if provider is None:
        # Uzatish bo'lmaydigan holatda rozilik yozish — ma'nosiz va chalg'ituvchi.
        raise HTTPException(400, "Tashqi AI sozlanmagan — rozilik talab qilinmaydi")
    if int(disclosure_version) != DISCLOSURE_VERSION:
        raise HTTPException(
            409, "Ilova eskirgan — rozilik matni yangilangan, ilovani yangilang",
            headers=EC.headers(EC.AI_CONSENT_REQUIRED))
    qiymat = {
        "provider": provider,
        "model": model,
        "disclosure_version": DISCLOSURE_VERSION,
        "granted_at": datetime.now(timezone.utc).isoformat(),
        "employee_id": str(emp.id),
    }
    row = _row(db, emp.company_id)
    if row is not None:
        row.value = qiymat
        row.row_version += 1
    else:
        db.add(Setting(company_id=emp.company_id, key=CONSENT_KEY, value=qiymat))
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "setting", None,
              before={"key": CONSENT_KEY, "value": read(db, emp.company_id) or None},
              after={"key": CONSENT_KEY, "value": qiymat})
    return qiymat


def revoke(db: Session, emp) -> None:
    """Rozilikni OLIB TASHLAYDI — qator o'chirilmaydi, qiymati bo'shatiladi
    (audit izi va `row_version` ketma-ketligi saqlanadi)."""
    row = _row(db, emp.company_id)
    oldin = dict(row.value or {}) if row is not None else {}
    if row is not None:
        row.value = {"revoked_at": datetime.now(timezone.utc).isoformat(),
                     "employee_id": str(emp.id)}
        row.row_version += 1
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "setting", None,
              before={"key": CONSENT_KEY, "value": oldin or None},
              after={"key": CONSENT_KEY, "value": None})


def require_consent(db: Session, company_id) -> None:
    """TASHQI UZATISHDAN OLDINGI DARVOZA. Rozilik yo'q bo'lsa — 403, fail-closed.

    Demo rejimda (provayder sozlanmagan) HECH NARSA uzatilmaydi, shu bois
    darvoza o'tkazib yuboriladi — aks holda rozilik hech qanday maxfiylik
    foydasi bermasdan demo oqimini ham to'sardi.
    """
    st = status(db, company_id)
    if not st["required"] or st["granted"]:
        return
    nom = st["provider_name"] or "tashqi AI xizmati"
    if st["previous_provider"]:
        matn = (f"AI xizmati o'zgardi — rasm endi {nom} ga yuboriladi. "
                f"Davom etish uchun yangi rozilik bering yoki qatorlarni qo'lda kiriting.")
    else:
        matn = (f"Nakladnoy rasmi {nom} ga yuboriladi. Davom etish uchun "
                f"rozilik bering yoki qatorlarni qo'lda kiriting.")
    raise HTTPException(403, matn, headers=EC.headers(EC.AI_CONSENT_REQUIRED))
