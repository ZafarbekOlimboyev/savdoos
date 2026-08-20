"""FCM push yuborish (kam-qoldiq bildirishnomasi).

FCM_CREDENTIALS_JSON (Firebase xizmat kaliti JSON) bo'lmasa — barcha yuborishlar inert (no-op).
Har chaqiruv xavfsiz (best-effort): xato bo'lsa yutiladi, hech qachon asosiy oqimni buzmaydi.
"""
import json
import threading

from app.core.config import settings

_app = None
_lock = threading.Lock()


def _ensure_app():
    global _app
    if _app is not None:
        return _app
    with _lock:
        if _app is None:
            import firebase_admin
            from firebase_admin import credentials
            info = json.loads(settings.fcm_credentials_json)
            _app = firebase_admin.initialize_app(credentials.Certificate(info), name="savdoos-fcm")
    return _app


def send(tokens, title: str, body: str, data: dict | None = None) -> int:
    """Ro'yxatdagi tokenlarga bildirishnoma. Yuborilganlar sonini qaytaradi (0 = o'chiq/xato)."""
    tokens = [t for t in (tokens or []) if t]
    if not settings.fcm_enabled or not tokens:
        return 0
    try:
        from firebase_admin import messaging
        _ensure_app()
        msg = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
        )
        resp = messaging.send_each_for_multicast(msg, app=_app)
        return resp.success_count
    except Exception:  # noqa: BLE001
        return 0


def notify_low_stock(db, company_id, products) -> None:
    """products: [(name, qty), ...] — do'kon qurilmalariga kam-qoldiq bildirishnomasi."""
    if not settings.fcm_enabled or not products:
        return
    try:
        from app.models.devices import DeviceToken
        tokens = [
            t.token for t in db.query(DeviceToken).filter(DeviceToken.company_id == company_id).all()
        ]
        if not tokens:
            return
        if len(products) == 1:
            name, qty = products[0]
            title = "Kam qoldi"
            body = f"{name} — qoldiq {qty:g}"
        else:
            title = "Ombor ogohlantirishi"
            body = f"{len(products)} ta mahsulot kam qoldi"
        send(tokens, title, body, {"type": "low_stock"})
    except Exception:  # noqa: BLE001
        return
