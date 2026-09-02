from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import FULL_ACCESS_ROLES, effective_permissions, get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.settings import Setting

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: dict


# ── Kalit OQ-RO'YXATI + har kalit uchun maydon sxemasi (QA SB-005/SB-015/SB-022) ──
# Ilgari: istalgan kalit, istalgan qiymat qabul qilinardi — tax.rate="matn" pnl'ni 500 qilardi,
# junk kalitlar cheksiz to'planardi. Endi faqat ma'lum kalitlar, maydonlar tip-tekshiruvli.
# 'plan'/'suspended' — faqat-vendor (quyida alohida 403).
def _as_bool(v, fld):
    if isinstance(v, bool):
        return v
    raise HTTPException(400, f"'{fld}' true/false bo'lishi kerak")


def _as_num(v, fld, lo, hi):
    # Eski mijoz "12" (satr) yuborishi mumkin — muloyim koersiya, lekin 'matn' rad etiladi.
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"'{fld}' raqam bo'lishi kerak")
    if not (lo <= f <= hi):
        raise HTTPException(400, f"'{fld}' {lo}..{hi} oralig'ida bo'lishi kerak")
    return f


def _as_str(v, fld, maxlen):
    if v is None:
        return None
    if not isinstance(v, str):
        raise HTTPException(400, f"'{fld}' matn bo'lishi kerak")
    return v[:maxlen]


def _validate_value(key: str, value: dict) -> dict:
    """Ma'lum maydonlarni tekshiradi/koersiya qiladi; NOMA'LUM maydon rad (sxema qat'iy)."""
    out: dict = {}
    if key == "tax":
        allowed = {"vat_on", "rate", "max_disc"}
        for f, v in value.items():
            if f not in allowed:
                raise HTTPException(400, f"tax: noma'lum maydon '{f}'")
            if f == "vat_on":
                out[f] = _as_bool(v, f)
            else:
                out[f] = _as_num(v, f, 0, 100)
        return out
    if key == "payments":
        bools = {"karta", "qr", "qarz", "offline_card", "offline_qr"}
        for f, v in value.items():
            if f in bools:
                out[f] = _as_bool(v, f)
            elif f == "qr_mode":
                if v not in ("manual", "xpay"):
                    raise HTTPException(400, "qr_mode: manual | xpay")
                out[f] = v
            else:
                raise HTTPException(400, f"payments: noma'lum maydon '{f}'")
        return out
    if key in ("security", "features"):
        for f, v in value.items():
            if not isinstance(f, str) or len(f) > 60:
                raise HTTPException(400, f"{key}: maydon nomi noto'g'ri")
            if key == "security" and f == "auto_logout":   # daqiqa (0=o'chiq) — UI raqam yuboradi
                out[f] = int(_as_num(v, f, 0, 1440))
            else:
                out[f] = _as_bool(v, f)
        return out
    if key == "store_info":
        allowed = {"name": 200, "branch": 200, "phone": 30, "address": 300, "stir": 40}
        for f, v in value.items():
            if f not in allowed:
                raise HTTPException(400, f"store_info: noma'lum maydon '{f}'")
            out[f] = _as_str(v, f, allowed[f])
        return out
    if key == "receipt":
        allowed = {"header": 2000, "footer": 2000, "printer": 200}
        for f, v in value.items():
            if f in allowed:
                out[f] = _as_str(v, f, allowed[f])
            elif f == "show_barcode":  # eski mijozlar yuborishi mumkin — qabul, lekin o'lik (UI'dan olib tashlandi)
                out[f] = _as_bool(v, f)
            else:
                raise HTTPException(400, f"receipt: noma'lum maydon '{f}'")
        return out
    raise HTTPException(400, f"Noma'lum sozlama kaliti: {key}")


# POS/kassir UI'ga kerak bo'ladigan kalitlar — qolganlari (masalan 'security') faqat
# sozlamalar.view/to'liq-huquqlilarga (QA SB-011: kassir hamma sozlamani o'qiy olardi).
_UI_KEYS = {"store_info", "payments", "features", "receipt", "tax", "plan"}


@router.get("/settings")
def get_settings(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    rows = db.query(Setting).filter(Setting.company_id == emp.company_id).order_by(Setting.row_version).all()
    full = emp.role.code in FULL_ACCESS_ROLES or "sozlamalar.view" in effective_permissions(emp, db)
    out: dict = {}
    for r in rows:  # order_by tufayli legacy-dublikat bo'lsa eng "yangi"si g'olib (deterministik)
        if full or r.key in _UI_KEYS:
            out[r.key] = r.value
    return out


def _sync_payment_methods(db: Session, company_id, value: dict):
    """QA SB-001: to'lov toggle Setting'ga yozilardi, server enforcement esa payment_methods
    JADVALIDAN o'qiydi (services/sales.py) — sinxron yo'q edi, o'chirish ISHLAMASdi.
    Endi Setting bilan birga jadval ham yangilanadi (karta→card, qarz→credit; naqd doim yoniq).
    Maydon berilmagan bo'lsa prefs semantikasi: !==false => yoniq."""
    from app.models.settings import PaymentMethod
    mapping = {"card": value.get("karta") is not False,
               "qr": value.get("qr") is not False,
               "credit": value.get("qarz") is not False}
    existing = {p.code: p for p in db.query(PaymentMethod).filter(
        PaymentMethod.company_id == company_id).all()}
    names = {"card": "Karta", "qr": "QR to'lov", "credit": "Nasiya"}
    for code, enabled in mapping.items():
        row = existing.get(code)
        if row:
            row.is_enabled = enabled
        else:  # eski tenant'da qator bo'lmasligi mumkin — yaratamiz
            db.add(PaymentMethod(company_id=company_id, code=code, name=names[code],
                                 is_enabled=enabled, sort_order=len(existing)))
    cash = existing.get("cash")
    if cash and not cash.is_enabled:
        cash.is_enabled = True  # naqd hech qachon o'chmaydi (kassa asosi)


@router.put("/settings")
def put_setting(
    data: SettingsIn,
    emp: Employee = Depends(require("sozlamalar.edit")),
    db: Session = Depends(get_db),
):
    # FAQAT-VENDOR kalitlар — do'kon O'ZI o'zgartira olmaydi:
    #  - 'plan': tarif (mijoz o'zini "business"ga ko'tarmasin);
    #  - 'suspended': do'konни to'xtatish/tiklash — vendor nazoratида.
    if data.key in ("plan", "suspended"):
        raise HTTPException(403, "Bu sozlamani o'zgartirib bo'lmaydi — provayder bilan bog'laning")
    value = _validate_value(data.key, data.value)
    import json as _json
    if len(_json.dumps(value)) > 64_000:  # ulkan sozlama payload'ini to'saymiz
        raise HTTPException(400, "Sozlama qiymati juda katta")
    row = (
        db.query(Setting)
        .filter(Setting.company_id == emp.company_id, Setting.branch_id.is_(None), Setting.key == data.key)
        .order_by(Setting.row_version.desc())  # legacy-dublikat bo'lsa eng yangi qatorga yozamiz
        .with_for_update()  # parallel ikki admin bir kalitga yozsa — ketma-ket merge (lost-update yo'q)
        .first()
    )
    _old = dict(row.value or {}) if row else None
    # MERGE semantikasi (QA SB-008): mijoz faqat O'ZGARGAN maydonlarni yuboradi, server mavjud
    # qiymatga qo'shadi (None = maydonni o'chirish). Ikki admin bir vaqtda HAR XIL maydonni
    # o'zgartirsa — ikkalasi ham saqlanadi (ilgari butun obyekt almashib, biri jim yo'qolardi).
    merged = dict(_old or {})
    for f, v in value.items():
        if v is None:
            merged.pop(f, None)
        else:
            merged[f] = v
    if row:
        row.value = merged
        row.row_version += 1
    else:
        row = Setting(company_id=emp.company_id, key=data.key, value=merged)
        db.add(row)
    if data.key == "payments":
        _sync_payment_methods(db, emp.company_id, merged)
    # AUDIT: xavfsizlik sozlamasi (allow_oversell/force_shift/to'lov-usullari) o'zgarishi iz qoldirsin.
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "update", "setting", None,
              before={"key": data.key, "value": _old}, after={"key": data.key, "value": merged})
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Parallel birinchi-yozish poygasi (ux_settings_company_key) — qayta o'qib merge qilamiz.
        db.rollback()
        row = (db.query(Setting)
               .filter(Setting.company_id == emp.company_id, Setting.branch_id.is_(None), Setting.key == data.key)
               .with_for_update()
               .first())
        if not row:
            raise HTTPException(409, "Sozlama saqlanmadi — qayta urining")
        merged = dict(row.value or {})
        for f, v in value.items():
            if v is None:
                merged.pop(f, None)
            else:
                merged[f] = v
        row.value = merged
        row.row_version += 1
        if data.key == "payments":
            _sync_payment_methods(db, emp.company_id, merged)
        db.commit()
    return {data.key: merged}
