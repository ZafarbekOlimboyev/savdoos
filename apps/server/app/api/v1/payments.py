import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.payments import QrPayment
from app.services import xpay

router = APIRouter(tags=["payments"])


class QrRequest(BaseModel):
    amount: float
    comment: str | None = None


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
    # Webhook kechiksa — jonli tekshiramiz
    if rec.status == "WAITING" and settings.xpay_enabled:
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
    # XPAY to'lov bo'lishi bilan chaqiradi (ochiq endpoint). Turli maydon nomlarini qo'llab-quvvatlaymiz.
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):  # [] yoki skalyar kelsa ham 500 bermaymiz
        body = {}
    txn = str(body.get("qr_transaction_id") or body.get("transaction_id") or body.get("id") or "")
    status = str(body.get("pay_status") or body.get("status") or "").upper()
    if txn:
        rec = db.query(QrPayment).filter(QrPayment.txn_id == txn).first()
        if rec and status:
            rec.status = status
            rec.updated_at = datetime.now(timezone.utc)
            db.commit()
    return {"ok": True}
