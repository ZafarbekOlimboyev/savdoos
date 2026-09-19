# -*- coding: utf-8 -*-
"""Chek SHABLONI — mavjud `settings` jadvalidagi `receipt` kaliti (Phase 5F).

QATORLAR:
    kompaniya standarti  (company_id, branch_id IS NULL, key='receipt')
    filial ustamasi      (company_id, branch_id=<filial>, key='receipt')

MEROS: maydon FAQAT qatorda bo'lsa ustun keladi — `filial → kompaniya → BUILTIN`.
Qatorda yo'q (yoki `None`) maydon yuqori qatlamdan olinadi; `None` yuborish maydonni
O'CHIRADI, ya'ni merosga qaytaradi.

⚠️  YAGONA VALIDATOR. `validate_receipt_patch` ham yangi `PUT /receipt/settings`,
    ham eski `PUT /settings` (key=receipt) yo'lida ishlaydi: ikki yo'l ikki xil
    qoida bilan yozsa, eski Manager yangi qoida taqiqlagan qiymatni (masalan
    bidi-boshqaruv belgili sarlavha) orqa eshikdan yozib qo'yardi.
⚠️  BAZADAGI qiymatga ham ISHONILMAYDI (`clean_stored`): eski/qo'lda yozilgan
    noto'g'ri maydon rad etilmaydi, balki TASHLAB YUBORILADI (meros ishlaydi) —
    chek chiqishi buzuq sozlama tufayli to'xtab qolmasin.
"""
from __future__ import annotations

import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import visible_branches
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.services.receipt import errors as E

KEY = "receipt"
MAX_PAYLOAD_BYTES = 64_000
LANGS = ("uz", "uzc", "ru", "ky")
QR_MODES = ("none", "receipt_id", "store_url")
WIDTHS = (58, 80)
QR_URL_MAX = 300

BUILTIN: dict = {
    "header": None,
    "footer": None,
    "printer": None,                 # ESKI: qurilmaga xos, endi qurilmada saqlanadi
    "show_barcode": False,
    "store_display_name": None,
    "address": None,
    "phone": None,
    "width_mm": 80,
    "lang": None,
    "show_logo": True,
    "logo_id": None,
    "show_branch": True,
    "show_stir": True,
    "show_cashier": True,
    "show_till": False,
    "show_payment_breakdown": True,
    "show_discount": True,
    "show_customer": False,          # maxfiylik: mijoz ismi standartda chekka chiqmaydi
    "qr_mode": "none",
    "qr_url": None,
    "auto_cut": True,
    "copies": 1,
    "auto_print": False,
}
FIELDS = tuple(BUILTIN)
# DTO `template` iga KIRMAYDI: qurilma printeri, logo havolasi (bitlar alohida) va URL.
TEMPLATE_EXCLUDED = ("printer", "logo_id", "qr_url")

_MULTILINE = {"header": 2000, "footer": 2000}
_SINGLE = {"printer": 200, "store_display_name": 120, "address": 300, "phone": 40}
_BOOLS = frozenset({"show_barcode", "show_logo", "show_branch", "show_stir", "show_cashier",
                    "show_till", "show_payment_breakdown", "show_discount", "show_customer",
                    "auto_cut", "auto_print"})
_URL_RE = re.compile(r"^https?://[^\s<>\"']+$")

# ── MATN TOZALASH ────────────────────────────────────────────────────────────
# ⚠️  C0/C1 boshqaruv belgilari termal printerga XOM BAYT bo'lib ketishi mumkin
#     (ESC/POS buyrug'i — masalan pul qutisini ochish), bidi belgilari esa matnni
#     ko'rinishda teskari aylantirib summani/nomni soxtalashtiradi. Shu bois ular
#     SAQLASHDAN OLDIN olib tashlanadi; ko'p qatorli maydonlarda faqat `\n` qoladi.
_BIDI = tuple(range(0x202A, 0x202F)) + tuple(range(0x2066, 0x206A)) + (0x200E, 0x200F)
_DROP = {c: None for c in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0), *_BIDI)}
_T_MULTI = {**_DROP, 0x0A: "\n", 0x09: " "}
_T_SINGLE = {**_DROP, 0x0A: " ", 0x09: " "}


def _clean_text(s: str, multiline: bool) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.translate(_T_MULTI if multiline else _T_SINGLE)


def _has_control(s: str) -> bool:
    return any(ord(ch) in _DROP for ch in s)


def clean_line(s: str, maxlen: int) -> str | None:
    """Bir qatorli erkin matn (printer xatosi, printer nomi) — boshqaruv/bidi belgisiz,
    qisqartirilgan; bo'sh bo'lsa None."""
    out = _clean_text(s, False).strip()[:maxlen].strip()
    return out or None


def _coerce(f: str, v):
    """Bitta maydon (None EMAS) — tozalangan qiymat yoki 400."""
    if f in _MULTILINE or f in _SINGLE:
        if not isinstance(v, str):
            raise E.invalid_field(f)
        if f in _MULTILINE:
            # Uzun matn QISQARTIRILADI (rad etilmaydi) — eski `_as_str` semantikasi, moslik.
            return _clean_text(v, True)[:_MULTILINE[f]]
        return clean_line(v, _SINGLE[f])   # bo'sh bir qatorli maydon = meros (filial/do'kon)
    if f in _BOOLS:
        if isinstance(v, bool):
            return v
        raise E.invalid_field(f)
    if f == "width_mm":
        if type(v) is int and v in WIDTHS:
            return v
        raise E.invalid_field(f)
    if f == "copies":
        if type(v) is int and 1 <= v <= 3:
            return v
        raise E.invalid_field(f)
    if f == "lang":
        if isinstance(v, str) and v in LANGS:
            return v
        raise E.invalid_field(f)
    if f == "qr_mode":
        if isinstance(v, str) and v in QR_MODES:
            return v
        raise E.invalid_field(f)
    if f == "logo_id":
        if not isinstance(v, str):
            raise E.invalid_field(f)
        try:
            return str(uuid.UUID(v))
        except ValueError:
            raise E.invalid_field(f) from None
    if f == "qr_url":
        # ⚠️  URL QISQARTIRILMAYDI — kesilgan havola BOSHQA manzilga olib borardi.
        #     `javascript:`/`data:` sxema, bo'shliq, qo'shtirnoq va boshqaruv belgisi rad.
        if (not isinstance(v, str) or len(v) > QR_URL_MAX or _has_control(v)
                or not _URL_RE.match(v)):
            raise E.invalid_field(f)
        return v
    raise E.unknown_field(f)          # `BUILTIN` bilan izchil — bu yerga yetib kelmaydi


def validate_receipt_patch(value) -> dict:
    """PATCH (faqat o'zgargan maydonlar) → tozalangan lug'at. `None` = maydonni o'chirish.

    Noma'lum maydon — `receipt: noma'lum maydon '<f>'` (eski matn), noto'g'ri tip /
    oraliq / naqsh — `Chek sozlamasi noto'g'ri: <maydon>`."""
    if not isinstance(value, dict):
        raise E.invalid_field("value")
    try:
        size = len(json.dumps(value))
    except (TypeError, ValueError):
        raise E.invalid_field("value") from None
    if size > MAX_PAYLOAD_BYTES:
        raise E.invalid_field("value")
    out: dict = {}
    for f, v in value.items():
        if f not in BUILTIN:
            raise E.unknown_field(f)
        out[f] = None if v is None else _coerce(f, v)
    return out


def clean_stored(value) -> dict:
    """Bazadagi qatorni ISHONCHSIZ deb o'qiydi: noma'lum yoki noto'g'ri maydon tashlanadi."""
    if not isinstance(value, dict):
        return {}
    out: dict = {}
    for f, v in value.items():
        if f not in BUILTIN or v is None:
            continue
        try:
            c = _coerce(f, v)
        except HTTPException:
            continue
        if c is not None:
            out[f] = c
    return out


def effective(company_value, branch_value=None) -> dict:
    """`filial → kompaniya → BUILTIN` — har maydon alohida."""
    eff = dict(BUILTIN)
    eff.update(clean_stored(company_value))
    eff.update(clean_stored(branch_value))
    return eff


def template_of(eff: dict) -> dict:
    return {k: v for k, v in eff.items() if k not in TEMPLATE_EXCLUDED}


# ── QATORLAR ─────────────────────────────────────────────────────────────────
def _row_query(db: Session, company_id, branch_id):
    q = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == KEY)
    if branch_id is None:
        # Eski bazada `ux_settings_company_key` bo'lmasligi mumkin (ixtiyoriy indeks) —
        # dublikatda eng YANGI qator (GET /settings ham shuni ko'rsatadi).
        return q.filter(Setting.branch_id.is_(None)).order_by(Setting.row_version.desc())
    return q.filter(Setting.branch_id == branch_id)


def load_values(db: Session, company_id, branch_id) -> tuple[dict | None, dict | None]:
    """(kompaniya qatori qiymati, filial qatori qiymati) — XOM, yo'q bo'lsa None."""
    crow = _row_query(db, company_id, None).first()
    brow = _row_query(db, company_id, branch_id).first() if branch_id is not None else None
    cval = dict(crow.value or {}) if crow is not None else None
    bval = dict(brow.value or {}) if brow is not None else None
    return cval, bval


def store_info(db: Session, company_id) -> dict:
    row = (db.query(Setting)
           .filter(Setting.company_id == company_id, Setting.branch_id.is_(None),
                   Setting.key == "store_info")
           .order_by(Setting.row_version.desc()).first())
    val = row.value if row is not None else None
    return dict(val) if isinstance(val, dict) else {}


def _nz(v) -> str | None:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def resolve_store(db: Session, company: Company, branch: Branch | None, eff: dict, *,
                  branch_name: str | None = None) -> dict:
    """Chek sarlavhasidagi do'kon ma'lumoti.

    nom:     shablon → `store_info.name` → Company.name
    manzil:  shablon → Branch.address → `store_info.address`
    telefon: shablon → Branch.phone → `store_info.phone`
    STIR:    FAQAT `store_info.stir` (boshqa soliq identifikatori TO'QILMAYDI)."""
    si = store_info(db, company.id)
    return {
        "name": _nz(eff.get("store_display_name")) or _nz(si.get("name")) or company.name,
        "branch_name": _nz(branch_name) or (_nz(branch.name) if branch is not None else None),
        "address": (_nz(eff.get("address")) or (_nz(branch.address) if branch is not None else None)
                    or _nz(si.get("address"))),
        "phone": (_nz(eff.get("phone")) or (_nz(branch.phone) if branch is not None else None)
                  or _nz(si.get("phone"))),
        "stir": _nz(si.get("stir")),
    }


def resolve_for_branch(db: Session, company_id,
                       branch: Branch | None) -> tuple[dict, dict | None, dict | None]:
    """(effective, kompaniya qiymati, filial qiymati) — bitta joyda (DTO, profil, ko'rinish)."""
    cval, bval = load_values(db, company_id, branch.id if branch is not None else None)
    return effective(cval, bval), cval, bval


# ── DOIRA (filial izolyatsiyasi) ─────────────────────────────────────────────
def parse_uuid(raw) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def visible_branch(db: Session, emp, raw) -> Branch:
    """Xodim KO'RADIGAN, o'chirilmagan, o'z kompaniyasidagi filial — aks holda 404.

    ⚠️  Begona do'kon, begona filial, o'chirilgan va buzuq id — BIR XIL javob:
        filial mavjudligi haqida oracle yo'q."""
    bid = parse_uuid(raw)
    if bid is None:
        raise E.branch_not_found()
    b = db.get(Branch, bid)
    if b is None or b.company_id != emp.company_id or b.deleted_at is not None:
        raise E.branch_not_found()
    vis = visible_branches(emp, db)
    if vis is not None and b.id not in vis:
        raise E.branch_not_found()
    return b


def write_scope(db: Session, emp, raw_branch_id) -> Branch | None:
    """Yozish doirasi: None = kompaniya standarti.

    ⚠️  Kompaniya standarti BARCHA filial chekiga ta'sir qiladi — uni faqat
        filial cheklovisiz xodim (Ega yoki hech bir filialga biriktirilmagan)
        o'zgartiradi. Aks holda bitta filial administratori boshqa filiallarning
        chekini orqa eshikdan o'zgartira olardi."""
    if raw_branch_id is None:
        if visible_branches(emp, db) is not None:
            raise E.scope_company_forbidden()
        return None
    return visible_branch(db, emp, raw_branch_id)


# ── LOGO HAVOLASI ────────────────────────────────────────────────────────────
def logo_allowed(logo_company_id, logo_branch_id, company_id, scope_branch_id) -> bool:
    """Kompaniya qatori — faqat kompaniya logosi (branch_id NULL); filial qatori —
    kompaniya logosi YOKI aynan o'sha filial logosi."""
    if logo_company_id != company_id:
        return False
    return logo_branch_id is None or (scope_branch_id is not None
                                      and logo_branch_id == scope_branch_id)


def check_logo_ref(db: Session, company_id, scope_branch_id, logo_id: str) -> None:
    from app.models.receipt import ReceiptLogo
    row = (db.query(ReceiptLogo.company_id, ReceiptLogo.branch_id)
           .filter(ReceiptLogo.id == uuid.UUID(logo_id)).first())
    if row is None or not logo_allowed(row[0], row[1], company_id, scope_branch_id):
        raise HTTPException(400, E.LOGO_NOT_FOUND)


# ── YOZISH ───────────────────────────────────────────────────────────────────
def _merge(old: dict | None, patch: dict) -> dict:
    out = dict(old or {})
    for f, v in patch.items():
        if v is None:
            out.pop(f, None)
        else:
            out[f] = v
    return out


def _check_consistency(db: Session, company_id, branch_id, new_value: dict, patch: dict) -> None:
    """`qr_mode=store_url` URL'siz bo'lmasin — FAQAT patch QR maydoniga tegsa.

    ⚠️  Aloqasiz yozuv (masalan footer) boshqa qatlamdagi eski nomuvofiqlik tufayli
        rad etilmaydi: DTO bunday holatda QR'ni shunchaki chiqarmaydi."""
    if "qr_mode" not in patch and "qr_url" not in patch:
        return
    if branch_id is None:
        eff = effective(new_value)
    else:
        cval, _ = load_values(db, company_id, None)
        eff = effective(cval, new_value)
    if eff["qr_mode"] == "store_url" and not eff["qr_url"]:
        raise E.invalid_field("qr_url")


def _row_for_update(db: Session, company_id, branch_id):
    # `populate_existing` — sessiyadagi ESKI nusxa ustida qaror qabul qilinmasin.
    return _row_query(db, company_id, branch_id).with_for_update().populate_existing().first()


def write_receipt_settings(db: Session, emp, branch: Branch | None, patch: dict, *,
                           audit_entity: str = "receipt_settings") -> dict:
    """Validatsiyadan o'tgan PATCH ni qator QULFI ostida maydonma-maydon qo'shadi.

    COMMIT QILMAYDI (chaqiruvchi qiladi) — PG poyga sinovlari uni tranzaksiya
    o'rtasida to'xtatib turadi. Qaytaradi: qatorning yangi qiymati.

    ⚠️  BIRINCHI YOZUV POYGASI: qator yo'q, ikki admin bir vaqtda yozadi. Noyoblik
        (`ux_settings_company_key` / UNIQUE(company_id, branch_id, key)) ikkinchisini
        to'xtatadi — FAQAT uning SAVEPOINT'i qaytadi va u g'olib qatorni qulf bilan
        qayta o'qib, o'z maydonlarini USTIGA qo'shadi (yo'qolgan yangilanish yo'q)."""
    from app.services.audit import log as audit_log
    company_id = emp.company_id
    bid = branch.id if branch is not None else None
    if patch.get("logo_id"):
        check_logo_ref(db, company_id, bid, patch["logo_id"])
    db.flush()
    row = _row_for_update(db, company_id, bid)
    before = None
    if row is None:
        new = _merge(None, patch)
        _check_consistency(db, company_id, bid, new, patch)
        sp = db.begin_nested()
        try:
            db.add(Setting(company_id=company_id, branch_id=bid, key=KEY, value=new, row_version=1))
            db.flush()
            sp.commit()
        except IntegrityError:
            sp.rollback()
            row = _row_for_update(db, company_id, bid)
            if row is None:          # boshqa sabab (FK va sh.k.) — yashirilmaydi
                raise
    if row is not None:
        before = dict(row.value or {})
        new = _merge(before, patch)
        _check_consistency(db, company_id, bid, new, patch)
        row.value = new
        row.row_version = (row.row_version or 1) + 1
    audit_log(db, emp.id, "update", audit_entity, None,
              before={"key": KEY, "branch_id": str(bid) if bid else None, "value": before},
              after={"key": KEY, "branch_id": str(bid) if bid else None, "value": new})
    db.flush()
    return new
