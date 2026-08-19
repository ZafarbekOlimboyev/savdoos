"""XPAY (xpay.kg) QR to'lov integratsiyasi — server tomonda (kalitlar hech qachon ilovada emas).

DIQQAT: quyidagi endpoint path'lari va maydon nomlari xpay.kg ochiq hujjati asosida
taxminan yozilgan. Merchant sandbox olingach shu 3 konstantani va JSON maydonlarini
haqiqiy hujjatga solishtirib tasdiqlash kerak (o'zgarsa faqat shu fayl tuziladi).
"""
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal

from fastapi import HTTPException

from app.core.config import settings

# ── xpay.kg API path'lari (sandbox olingach tekshiriladi) ──
TOKEN_PATH = "/api/v1/oauth/token"
QR_PATH = "/api/v1/qr"
STATUS_PATH = "/api/v1/qr/{txn}"

_token_cache = {"token": "", "exp": 0.0}


def _req(method: str, url: str, body: dict | None = None, token: str | None = None, timeout: int = 20) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300] if e.fp else str(e)
        raise HTTPException(502, f"XPAY xatosi ({e.code}): {detail}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"XPAY bilan aloqa yo'q: {e}")


def _token() -> str:
    if not settings.xpay_enabled:
        raise HTTPException(503, "XPAY sozlanmagan (kalitlar yo'q)")
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] > now + 30:
        return _token_cache["token"]
    res = _req("POST", settings.xpay_base_url + TOKEN_PATH, {
        "client_id": settings.xpay_client_id,
        "client_secret": settings.xpay_client_secret,
        "grant_type": "client_credentials",
    })
    tok = res.get("access_token") or res.get("token") or ""
    if not tok:
        raise HTTPException(502, "XPAY token olinmadi")
    _token_cache["token"] = tok
    _token_cache["exp"] = now + int(res.get("expires_in", 3000))
    return tok


def create_qr(amount: Decimal, comment: str = "", callback_url: str | None = None) -> dict:
    """Dinamik QR yaratadi. Qaytaradi: {qr_url, txn_id}."""
    body = {
        "uuid": settings.xpay_merchant_uuid,
        "amount": float(amount),
        "type": "dynamic",
        "comments": comment or "SavdoOS savdo",
        "amount_change": False,
    }
    if callback_url:
        body["callback_url"] = callback_url
    res = _req("POST", settings.xpay_base_url + QR_PATH, body, token=_token())
    qr_url = res.get("qr_code") or res.get("qr_url") or ""
    txn = res.get("qr_transaction_id") or res.get("transaction_id") or res.get("id") or ""
    if not txn:
        raise HTTPException(502, "XPAY QR yaratilmadi")
    return {"qr_url": qr_url, "txn_id": str(txn)}


def check_status(txn_id: str) -> str:
    """Qaytaradi: WAITING|PROCESSING|COMPLETED|CANCELED|ERROR."""
    res = _req("GET", settings.xpay_base_url + STATUS_PATH.format(txn=txn_id), token=_token())
    st = (res.get("pay_status") or res.get("status") or "WAITING").upper()
    return st
