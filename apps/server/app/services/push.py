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


def send_ex(tokens, title: str, body: str, data: dict | None = None):
    """Yuborish + O'LIK tokenlar ro'yxati (QA WH-022: UNREGISTERED javoblar o'qilmasdi —
    o'chirilgan qurilma tokenlari abadiy to'planardi). Qaytaradi: (success_count, invalid_tokens)."""
    tokens = [t for t in (tokens or []) if t]
    if not settings.fcm_enabled or not tokens:
        return 0, []
    try:
        from firebase_admin import messaging
        _ensure_app()
        msg = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
        )
        resp = messaging.send_each_for_multicast(msg, app=_app)
        invalid = []
        for t, r in zip(tokens, resp.responses):
            if not r.success and r.exception is not None:
                _s = str(r.exception)
                if "UNREGISTERED" in _s.upper() or "registration-token-not-registered" in _s:
                    invalid.append(t)
        return resp.success_count, invalid
    except Exception:  # noqa: BLE001
        return 0, []


def send(tokens, title: str, body: str, data: dict | None = None) -> int:
    """Ro'yxatdagi tokenlarga bildirishnoma. Yuborilganlar sonini qaytaradi (0 = o'chiq/xato)."""
    n, _ = send_ex(tokens, title, body, data)
    return n


def notify_low_stock(db, company_id, products, branch_name: str | None = None) -> None:
    """products: [(name, qty), ...] — do'kon qurilmalariga kam-qoldiq bildirishnomasi.
    QA WH-022: branch_name — ko'p-filialda QAYSI filialda kamayganini aytadi."""
    if not settings.fcm_enabled or not products:
        return
    try:
        from app.models.devices import DeviceToken
        tokens = [
            t.token for t in db.query(DeviceToken).filter(DeviceToken.company_id == company_id).all()
        ]
        if not tokens:
            return
        _suf = f" · {branch_name}" if branch_name else ""
        if len(products) == 1:
            name, qty = products[0]
            title = "Kam qoldi"
            body = f"{name} — qoldiq {qty:g}{_suf}"
        else:
            title = "Ombor ogohlantirishi"
            body = f"{len(products)} ta mahsulot kam qoldi{_suf}"
        _n, _invalid = send_ex(tokens, title, body, {"type": "low_stock"})
        if _invalid:
            # O'lik tokenlarni tozalaymiz — keyingi yuborishlar yengil, xato yig'ilmaydi.
            db.query(DeviceToken).filter(DeviceToken.company_id == company_id,
                                         DeviceToken.token.in_(_invalid)).delete(synchronize_session=False)
            db.commit()
    except Exception:  # noqa: BLE001
        return
