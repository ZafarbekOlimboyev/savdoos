# -*- coding: utf-8 -*-
"""Kassa parki (fleet) — QURILMA TELEMETRIYASI va RELIZ TAYYORLIGI.

MUAMMO: buzuvchi naqd relizidan oldin operator quyidagi savolga javob bera olishi kerak:
    "Barcha FAOL naqd kassalari kerakli versiyadami?"
Ilgari yagona yo'l — har kassirdan "Sozlamalar" ekranidagi versiyani og'zaki so'rash edi.
Bu miqyoslashmaydi va xato beradi.

IKKI ENDPOINT:
    POST /fleet/heartbeat   — mijoz O'ZI haqida xabar beradi (versiya, navbat sonlari)
    GET  /fleet/devices     — operator ko'rinishi + reliz tayyorligi hisoboti

XOLISLIK QOIDASI (eng muhimi): server navbat holatini O'YLAB TOPMAYDI.
`pending_ops`/`failed_ops` — FAQAT qurilma xabar qilgan son. Hech qachon xabar bermagan
qurilma uchun ular NULL bo'lib qoladi va hisobotda `unknown` sifatida sanaladi —
NOL sifatida EMAS. "Navbat bo'sh" va "bilmayman" ARALASHTIRILMAYDI: aks holda operator
sinxronlanmagan chek turgan kassani "toza" deb o'ylab reliz chiqarardi.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.org import Branch
from app.models.sync import SyncDevice

router = APIRouter(tags=["fleet"])

# ── Naqd uchun TALAB QILINADIGAN eng past POS versiyasi ──────────────────────
# v0.7.0 — AYNAN till_id yuboradigan birinchi build. Undan eskisi kassa (TILL) identity'sini
# yubormaydi, ya'ni T0'dan keyin naqd smena OCHA OLMAYDI. Buzuvchi naqd relizi chiqarilganda
# shu qiymat oshiriladi va tayyorlik hisoboti avtomatik yangilanadi.
MINIMUM_POS_VERSION = "0.7.0"

# Shu muddatdan keyin xabar bermagan qurilma "faol" hisoblanmaydi (o'chirilgan/omborda).
ACTIVE_WINDOW_DAYS = 14


def _vtuple(v: str | None) -> tuple[int, ...]:
    """'0.7.10' -> (0,7,10). Taqqoslash SATR bo'yicha EMAS: satrda '0.7.9' > '0.7.10' bo'lib
    ketardi va operator eski build'ni yangi deb o'ylardi."""
    if not v:
        return ()
    parts = []
    for chunk in str(v).strip().lstrip("vV").split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def version_ok(v: str | None, minimum: str = MINIMUM_POS_VERSION) -> bool:
    """Versiya yetarlimi. NOMA'LUM versiya YETARLI EMAS (fail-closed) — bilmaslik
    "joyida" deb hisoblanmaydi."""
    if not v:
        return False
    return _vtuple(v) >= _vtuple(minimum)


class HeartbeatIn(BaseModel):
    device_uuid: str = Field(min_length=8, max_length=100)
    app_version: str | None = Field(default=None, max_length=32)
    app_name: str | None = Field(default=None, max_length=32)      # pos | manager
    platform: str | None = Field(default=None, max_length=32)
    branch_id: uuid.UUID | None = None
    # Offline navbat — QURILMA sanagan. Ixtiyoriy: yubormasa oldingi qiymat SAQLANADI
    # (jimgina 0 ga TUSHIRILMAYDI).
    pending_ops: int | None = Field(default=None, ge=0, le=1_000_000)
    failed_ops: int | None = Field(default=None, ge=0, le=1_000_000)
    last_sync_ok_at: datetime | None = None


def _own_device(db: Session, emp: Employee, device_uuid: str):
    """Qurilmani FAQAT chaqiruvchining do'koni ichidan (yoki EGASIZ qatorlardan) qidiradi.

    `device_uuid` global UNIQUE, shuning uchun uni yolg'iz predikat sifatida ishlatish
    do'konlar orasidagi devorni buzadi: BOSHQA do'kon qurilmasi MAVJUD EMASdek
    ko'rinishi kerak.

    EGASIZ (`company_id IS NULL`) qatorlar ATAYLAB qabul qilinadi va bu XAVFSIZ:
    ular hech qaysi do'konga tegishli emas, ya'ni ularni o'zlashtirish hech kimdan
    hech narsa olmaydi. Bunday qatorlar eski koddan qolgan — u `SyncDevice` ni
    `company_id` SIZ yaratib, egasini keyin yozardi, shuning uchun so'rov o'rtasida
    uzilgan yozuvlar egasiz qolishi mumkin edi. Yangi kod egani INSERT paytida
    yozadi, ya'ni bundan buyon egasiz qator paydo bo'lmaydi."""
    return (
        db.query(SyncDevice)
        .filter(SyncDevice.device_uuid == device_uuid,
                or_(SyncDevice.company_id == emp.company_id,
                    SyncDevice.company_id.is_(None)))
        .first()
    )


@router.post("/fleet/heartbeat")
def heartbeat(data: HeartbeatIn, emp: Employee = Depends(get_current_employee),
              db: Session = Depends(get_db)):
    """Qurilma o'zi haqida xabar beradi. FAQAT HISOBOT — hech narsani boshqarmaydi.

    Tenant doirasi: `company_id` DOIM autentifikatsiyalangan xodimdan olinadi, so'rovdan EMAS —
    aks holda qurilma o'zini boshqa do'konnikiman deb e'lon qila olardi."""
    now = datetime.now(timezone.utc)
    du = (data.device_uuid or "").strip()

    # `device_uuid` UNIQUE. Ikki heartbeat bir vaqtda kelsa (ikki oyna, qayta urinish,
    # ilova qayta ishga tushishi) ikkalasi ham "qator yo'q" deb topib INSERT qilardi va
    # ikkinchisi IntegrityError bilan 500 berardi. Telemetriya kassani hech qachon
    # bezovta qilmasligi kerak — poygani ushlab, mavjud qatorni qayta o'qiymiz.
    # ⚠️  QIDIRUV TENANT DOIRASIDA. Ilgari qator FAQAT `device_uuid` bo'yicha
    #     topilar, so'ng quyida `dev.company_id = emp.company_id` bilan CHAQIRUVCHINING
    #     do'koniga YOZIB QO'YILARDI. Ya'ni boshqa do'kon qurilmasining UUID'ini bilgan
    #     kishi o'sha qurilmani O'ZIGA o'tkazib olardi: jabrlanuvchining fleet ro'yxatidan
    #     yo'qolardi, telemetriyasi esa hujumchiga oqardi. Docstring tenant doirasini
    #     da'vo qilardi — lekin kafolat `company_id` YOZUVIGA tegishli edi, QIDIRUVGA emas.
    dev = _own_device(db, emp, du)
    if dev is None:
        dev = SyncDevice(device_uuid=du, company_id=emp.company_id, created_at=now)
        db.add(dev)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            # `emp` rollback'dan keyin session'dan chiqib ketishi mumkin — qayta bog'laymiz.
            emp = db.merge(emp)
            # Qayta o'qish ham TENANT DOIRASIDA: bu haqiqiy poyga (o'z do'konimizdagi
            # ikkinchi heartbeat) bo'lsa qator topiladi. Topilmasa — UUID BOSHQA
            # do'konga tegishli; egalik O'TKAZILMAYDI va hech narsa oshkor qilinmaydi.
            dev = _own_device(db, emp, du)
            if dev is None:
                raise HTTPException(404, "Qurilma topilmadi")

    # Filial: so'rovda kelgani SHU do'konga tegishli bo'lsagina qabul qilinadi.
    br_id = None
    if data.branch_id is not None:
        br = db.get(Branch, data.branch_id)
        if br is not None and br.company_id == emp.company_id:
            br_id = br.id
    if br_id is None:
        br_id = getattr(emp, "branch_id", None)

    dev.company_id = emp.company_id
    if br_id is not None:
        dev.branch_id = br_id
    if data.app_version:
        dev.app_version = data.app_version.strip()[:32]
    if data.app_name:
        dev.app_name = data.app_name.strip()[:32]
    if data.platform:
        dev.platform = data.platform.strip()[:32]
    # Yubormagan maydonni O'ZGARTIRMAYMIZ (None = "bu safar xabar bermadim", "nol" EMAS).
    if data.pending_ops is not None:
        dev.pending_ops = int(data.pending_ops)
    if data.failed_ops is not None:
        dev.failed_ops = int(data.failed_ops)
    if data.last_sync_ok_at is not None:
        dev.last_sync_ok_at = data.last_sync_ok_at
    dev.last_seen_at = now

    db.commit()
    return {"ok": True, "minimum_pos_version": MINIMUM_POS_VERSION,
            "version_ok": version_ok(dev.app_version)}


@router.get("/fleet/devices")
def list_devices(active_only: bool = True,
                 emp: Employee = Depends(require("hisobot.view")),
                 db: Session = Depends(get_db)):
    """Operator ko'rinishi: qurilma · filial · oxirgi ko'rilgan · versiya · navbat holati.

    Shuningdek RELIZ TAYYORLIGI: eski yoki NOMA'LUM versiyali faol qurilma bo'lsa
    `release_ready=false` — ya'ni buzuvchi naqd relizini chiqarish XAVFLI."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ACTIVE_WINDOW_DAYS)

    q = db.query(SyncDevice).filter(SyncDevice.company_id == emp.company_id)
    rows = q.order_by(SyncDevice.last_seen_at.desc().nullslast()).all()

    names = {b.id: b.name for b in db.query(Branch).filter(Branch.company_id == emp.company_id).all()}

    out = []
    for d in rows:
        seen = d.last_seen_at
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        active = seen is not None and seen >= cutoff
        if active_only and not active:
            continue
        out.append({
            "device_uuid": d.device_uuid,
            "app_name": d.app_name,
            "platform": d.platform,
            "branch_id": str(d.branch_id) if d.branch_id else None,
            "branch_name": names.get(d.branch_id),
            "app_version": d.app_version,
            "version_ok": version_ok(d.app_version),
            "last_seen_at": seen.isoformat() if seen else None,
            "active": active,
            # NULL = qurilma HECH QACHON xabar bermagan. Nol deb ko'rsatilmaydi.
            "pending_ops": d.pending_ops,
            "failed_ops": d.failed_ops,
            "queue_known": d.pending_ops is not None,
            "last_sync_ok_at": d.last_sync_ok_at.isoformat() if d.last_sync_ok_at else None,
        })

    cash_devices = [r for r in out if r["active"] and (r["app_name"] or "pos") == "pos"]
    stale = [r["device_uuid"] for r in cash_devices if not r["version_ok"]]
    unknown_queue = [r["device_uuid"] for r in cash_devices if not r["queue_known"]]
    dirty_queue = [r["device_uuid"] for r in cash_devices
                   if r["queue_known"] and ((r["pending_ops"] or 0) > 0 or (r["failed_ops"] or 0) > 0)]

    return {
        "minimum_pos_version": MINIMUM_POS_VERSION,
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "devices": out,
        "readiness": {
            # Faqat versiya yetarli VA navbat holati MA'LUM bo'lganda tayyor deymiz.
            "release_ready": not stale and not unknown_queue and not dirty_queue,
            "active_cash_devices": len(cash_devices),
            "below_minimum_version": stale,
            "queue_state_unknown": unknown_queue,
            "queue_not_empty": dirty_queue,
            "note": ("Navbat holati NOMA'LUM qurilma 'bo'sh' deb hisoblanmaydi — "
                     "server hech qachon queue=0 deb O'YLAB TOPMAYDI."),
        },
    }
