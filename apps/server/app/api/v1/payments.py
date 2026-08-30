import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.payments import QrPayment
from app.services import xpay

router = APIRouter(tags=["payments"])


class QrRequest(BaseModel):
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)  # QrPayment.amount Numeric(14,2)ga sig'sin (1e12 overflow)
    comment: str | None = Field(default=None, max_length=200)


@router.get("/payments/config")
def payment_config(emp: Employee = Depends(require("kassa.sell"))):
    # POS shu bo'yicha "XPAY" rejimini ko'rsatishi yoki yashirishini biladi
    return {"xpay_enabled": settings.xpay_enabled}


@router.post("/payments/qr")
def create_qr(
    data: QrRequest,
    emp: Employee = Depends(require("kassa.sell")),
    db: Session = Depends(get_db),
):
    callback = (settings.public_base_url.rstrip("/") + "/api/v1/payments/xpay/webhook") if settings.public_base_url else None
    res = xpay.create_qr(Decimal(str(data.amount)), comment=data.comment or "", callback_url=callback)
    now = datetime.now(timezone.utc)
    rec = QrPayment(
        company_id=emp.company_id, txn_id=res["txn_id"], amount=Decimal(str(data.amount)),
        qr_url=res["qr_url"], status="WAITING", created_at=now, updated_at=now,
    )
    db.add(rec)
    db.commit()
    return {"txn_id": res["txn_id"], "qr_url": res["qr_url"], "status": "WAITING"}


@router.get("/payments/qr/{txn_id}")
def qr_status(
    txn_id: str,
    emp: Employee = Depends(require("kassa.sell")),
    db: Session = Depends(get_db),
):
    # TENANT: faqat o'z kompaniyasining to'lovi ko'rinadi (boshqa tenant statusi sizmasin)
    rec = db.query(QrPayment).filter(
        QrPayment.txn_id == txn_id, QrPayment.company_id == emp.company_id).first()
    if not rec:
        return {"status": "ERROR"}
    # Webhook kechiksa — jonli tekshiramiz. NOTERMINAL har qanday holatда (WAITING/PROCESSING/...)
    # qayta so'raymiz — aks holда XPAY 'PROCESSING' qaytarса status shunga qotib qolиб, jonli
    # tekshiruv boshqa ishlaмас, to'langan QR savdo abadiy "kutishда" osilib qolарди.
    _TERMINAL = {"COMPLETED", "CANCELED", "ERROR", "EXPIRED", "FAILED"}
    if rec.status not in _TERMINAL and settings.xpay_enabled:
        try:
            live = xpay.check_status(txn_id)
            if live != rec.status:
                rec.status = live
                rec.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    return {"status": rec.status}


@router.post("/payments/xpay/webhook")
async def xpay_webhook(request: Request, db: Session = Depends(get_db)):
    """XPAY callback (ochiq endpoint — internetdan istalgan kishi chaqirishi mumkin).

    XAVFSIZLIK: so'rov tanasidagi 'status'ga ISHONMAYMIZ (aks holda txn_id'ni bilgan
    har kim to'lovni 'to'langan' qilib soxtalashtirardi). Faqat txn_id'ni olamiz va
    statusni XPAY'dan SERVER tomonda (OAuth kaliti bilan) MUSTAQIL qayta so'raymiz —
    bu forge qilib bo'lmaydi. Qo'shimcha: XPAY_WEBHOOK_SECRET o'rnatilgan bo'lsa,
    tananing HMAC-SHA256 imzosi ham tekshiriladi (mos kelmasa 401)."""
    raw = await request.body()

    # 1) Ixtiyoriy HMAC imzo tekshiruvi (sir o'rnatilgan bo'lsa — majburiy)
    secret = settings.xpay_webhook_secret
    if secret:
        sig = (request.headers.get("x-signature") or request.headers.get("x-sign")
               or request.headers.get("signature") or "").strip().lower()
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "Webhook imzosi noto'g'ri")

    try:
        body = json.loads(raw.decode() or "{}")
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    txn = str(body.get("qr_transaction_id") or body.get("transaction_id") or body.get("id") or "")
    if not txn:
        return {"ok": True}
    rec = db.query(QrPayment).filter(QrPayment.txn_id == txn).first()
    if not rec:
        return {"ok": True}

    # 2) Statusni XPAY'dan mustaqil tasdiqlaymiz — tanadagi status e'tiborsiz qoldiriladi
    if settings.xpay_enabled:
        try:
            live = xpay.check_status(txn)
            if live and live != rec.status:
                rec.status = live
                rec.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:  # noqa: BLE001
            pass  # XPAY vaqtincha javob bermasa — POS baribir qr_status orqali so'raydi
    return {"ok": True}
