"""R7.6 — refresh sessiyalari: moslik, rotation, replay, revoke.

ILDIZ SABAB (R7.6 auth P0): `auth_sessions` modeli va `refresh_token_days`
konfigi reponing boshidan bor, `ARCHITECTURE.md:219` esa `POST /auth/refresh`
ni hujjatlashtirgan — LEKIN kod hech qachon yozilmagan
(`account_deletion.py:28` buni ochiq qayd etadi). Natijada yagona kredensial
12 soatlik access token bo'lib qoldi va 12 soatdan uzoq tanaffus TO'LIQ parol
bilan kirishni majbur qilardi.

⚠️  TOKEN JURNALGA CHIQMAYDI. Testlar kredensialni faqat o'zgaruvchida
    uzatadi; `print`/assert xabarida uning QIYMATI emas, FAKTI ko'rsatiladi.

⚠️  Bu fayl O'Z xodimini yaratadi (umumiy fikstura qatorini olmaydi) va
    o'zidan keyin tozalaydi — `client` fiksturasi SEANS doirasida.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_token, hash_refresh
from app.models.auth import AuthSession, Employee

REFRESH_HEADER = {"X-BinOS-Session": "refresh"}
PW = "Samarqand-Qish-2026"


@pytest.fixture()
def owner(client, admin_headers):
    """Shu fayl uchun ALOHIDA ega-roli xodim (noyob telefon)."""
    phone = "+99890" + str(uuid.uuid4().int)[:7]
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": "R76 Sessiya", "phone": phone, "password": PW, "role_code": "menejer"})
    assert r.status_code == 200, r.text
    emp_id = r.json()["id"]
    yield {"phone": phone, "id": emp_id}
    client.delete(f"/api/v1/employees/{emp_id}", headers=admin_headers)


def _login(client, owner, *, refresh: bool):
    return client.post("/api/v1/auth/login/password",
                       json={"phone": owner["phone"], "password": PW},
                       headers=REFRESH_HEADER if refresh else {})


def _sessions(client, emp_id) -> list[AuthSession]:
    db = client.app.state.test_db() if hasattr(client.app.state, "test_db") else None
    if db is None:                      # conftest sessiyasini ishlatamiz
        from app.db.session import SessionLocal
        db = SessionLocal()
    try:
        return list(db.scalars(select(AuthSession).where(
            AuthSession.employee_id == uuid.UUID(emp_id))).all())
    finally:
        db.close()


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


# ── 1. MOSLIK: sarlavhasiz login AYNAN avvalgidek ishlaydi ──────────────────

def test_LEGACY_login_SARLAVHASIZ_avvalgidek(client, owner):
    """R7.6 audit 5-bandi: eski POS/desktop xulqi O'ZGARMASIN."""
    r = _login(client, owner, refresh=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("refresh_token") is None, "sarlavhasiz login refresh BERMASLIGI kerak"
    payload = decode_token(body["access_token"])
    assert "sid" not in payload, "legacy tokenda `sid` BO'LMASLIGI kerak"
    # TTL legacy qiymatda qoladi (720 daqiqa), 60 ga TUSHMAYDI.
    ttl = datetime.fromtimestamp(payload["exp"], timezone.utc) - \
        datetime.fromtimestamp(payload["iat"], timezone.utc)
    assert abs(ttl - timedelta(minutes=settings.access_token_minutes)) < timedelta(minutes=2)
    assert _sessions(client, owner["id"]) == [], "legacy login sessiya YARATMASLIGI kerak"


def test_OPT_IN_login_sessiya_ochadi(client, owner):
    r = _login(client, owner, refresh=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("refresh_token"), str) and body["refresh_token"]
    payload = decode_token(body["access_token"])
    assert payload.get("sid"), "opt-in tokenda `sid` BO'LISHI kerak"
    ttl = datetime.fromtimestamp(payload["exp"], timezone.utc) - \
        datetime.fromtimestamp(payload["iat"], timezone.utc)
    #  Rollback oynasini chegaralash uchun QISQA TTL.
    assert abs(ttl - timedelta(minutes=settings.session_access_token_minutes)) \
        < timedelta(minutes=2)
    rows = _sessions(client, owner["id"])
    assert len(rows) == 1 and rows[0].revoked_at is None
    assert rows[0].prev_refresh_hash is None


# ── 2. ROTATION ─────────────────────────────────────────────────────────────

def test_REFRESH_yangi_kredensial_va_ishlaydigan_token(client, owner):
    first = _login(client, owner, refresh=True).json()
    r = client.post("/api/v1/auth/refresh",
                    json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"], "kredensial ALMASHMADI"
    #  Yangi access token HAQIQATAN ishlaydi.
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {second['access_token']}"})
    assert me.status_code == 200, me.text
    #  `sid` O'ZGARMAYDI — bu AYNI sessiya, yangi kredensial.
    assert decode_token(second["access_token"])["sid"] == \
        decode_token(first["access_token"])["sid"]


def test_ROTATION_absolyut_muddatni_UZAYTIRMAYDI(client, owner):
    first = _login(client, owner, refresh=True).json()
    before = _sessions(client, owner["id"])[0].expires_at
    client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    after = _sessions(client, owner["id"])[0].expires_at
    assert before == after, "rotation sessiyaning absolyut umrini uzaytirmasligi kerak"


# ── 3. REPLAY va GRACE ──────────────────────────────────────────────────────

def test_GRACE_oynasida_parallel_takror_QABUL_qilinadi(client, owner):
    """Mijozda single-flight bor, lekin fon/oldinga o'tishda poyga mumkin."""
    first = _login(client, owner, refresh=True).json()
    ok1 = client.post("/api/v1/auth/refresh",
                      json={"refresh_token": first["refresh_token"]})
    assert ok1.status_code == 200
    #  AYNI (endi iste'mol qilingan) kredensial — grace oynasi ICHIDA.
    ok2 = client.post("/api/v1/auth/refresh",
                      json={"refresh_token": first["refresh_token"]})
    assert ok2.status_code == 200, "grace oynasidagi takror RAD etilmasligi kerak"
    #  Yangi kredensial beriladi — AYNISI qaytarilmaydi (plaintext saqlanmaydi).
    assert ok2.json()["refresh_token"] != ok1.json()["refresh_token"]
    assert _sessions(client, owner["id"])[0].revoked_at is None, "sessiya tirik qolishi kerak"


def test_REPLAY_oynadan_KEYIN_sessiyani_BEKOR_qiladi(client, owner, monkeypatch):
    first = _login(client, owner, refresh=True).json()
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": first["refresh_token"]}).status_code == 200
    #  Grace oynasini YOPAMIZ — iste'mol qilingan kredensial endi REPLAY.
    monkeypatch.setattr(settings, "refresh_grace_seconds", 0)
    bad = client.post("/api/v1/auth/refresh",
                      json={"refresh_token": first["refresh_token"]})
    assert bad.status_code == 401
    assert bad.headers.get("X-Error-Code") == "SESSION_INVALID"
    rows = _sessions(client, owner["id"])
    assert rows[0].revoked_at is not None, "replay sessiyani BEKOR qilishi kerak (fail-closed)"


def test_NOMAVJUD_sir_sessiyani_BEKOR_QILMAYDI(client, owner):
    """Anti-DoS: `sid` ni taxmin qilgan hujumchi begona sessiyani o'chira olmasin."""
    first = _login(client, owner, refresh=True).json()
    sid = decode_token(first["access_token"])["sid"]
    bad = client.post("/api/v1/auth/refresh",
                      json={"refresh_token": f"{sid}.butunlay-boshqa-sir-qiymati"})
    assert bad.status_code == 401
    rows = _sessions(client, owner["id"])
    assert rows[0].revoked_at is None, "noma'lum sir sessiyani o'chirMASLIGI kerak"
    #  Eski kredensial HAMON ishlaydi — sessiya buzilmagan.
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": first["refresh_token"]}).status_code == 200


def test_SHAKLI_BUZILGAN_kredensial_401(client, owner):
    _login(client, owner, refresh=True)
    for raw in ("sidsiz-sir", "a.b.c", "." , "x."):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": raw + "xxxxxxxx"})
        assert r.status_code in (401, 422), raw


# ── 4. MUDDAT ───────────────────────────────────────────────────────────────

def test_MUDDATI_OTGAN_sessiya_401(client, owner):
    first = _login(client, owner, refresh=True).json()
    db = _db()
    try:
        row = db.scalar(select(AuthSession).where(
            AuthSession.employee_id == uuid.UUID(owner["id"])))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    r = client.post("/api/v1/auth/refresh",
                    json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401


# ── 5. /auth/revoke — FAQAT o'z sessiyasi ───────────────────────────────────

def test_REVOKE_access_tokenni_DARHOL_oldiradi(client, owner):
    body = _login(client, owner, refresh=True).json()
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200
    r = client.post("/api/v1/auth/revoke", headers=auth,
                    json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200, r.text
    #  Muddati tugashini KUTMAYDI — `deps.py` har so'rovda sessiyani tekshiradi.
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401
    #  Refresh ham o'lgan.
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_REVOKE_SIRSIZ_ishlamaydi(client, owner):
    body = _login(client, owner, refresh=True).json()
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    sid = decode_token(body["access_token"])["sid"]
    r = client.post("/api/v1/auth/revoke", headers=auth,
                    json={"refresh_token": f"{sid}.notogri-sir-qiymati"})
    assert r.status_code == 401
    #  Sessiya TIRIK qoldi.
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 200


def test_REVOKE_BEGONA_sessiyaga_tegmaydi(client, owner, admin_headers):
    """Boshqa xodim `sid` + sirni bilsa ham — egalik tekshiriladi."""
    victim = _login(client, owner, refresh=True).json()
    me = client.post("/api/v1/auth/login/password",
                     json={"phone": "+998901234567", "password": "demo1234"},
                     headers=REFRESH_HEADER).json()
    r = client.post("/api/v1/auth/revoke",
                    headers={"Authorization": f"Bearer {me['access_token']}"},
                    json={"refresh_token": victim["refresh_token"]})
    assert r.status_code == 401
    assert client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {victim['access_token']}"}
                      ).status_code == 200
    #  O'zinikini tozalab ketamiz.
    client.post("/api/v1/auth/revoke",
                headers={"Authorization": f"Bearer {me['access_token']}"},
                json={"refresh_token": me["refresh_token"]})


# ── 6. GLOBAL leverlar: logout va parol ─────────────────────────────────────

def test_LOGOUT_refresh_bilan_CHETLAB_OTILMAYDI(client, owner):
    """⚠️  Bu bo'lmasa chiqish MAG'LUB bo'lardi: `sec_epoch` oshgach eski
    access tokenlar o'ladi, lekin TIRIK refresh sessiyasi yangi `sv` bilan
    YAROQLI token berib qo'yardi."""
    body = _login(client, owner, refresh=True).json()
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    r = client.post("/api/v1/auth/refresh",
                    json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 401, "logout'dan keyin refresh ISHLAMASLIGI kerak"
    assert _sessions(client, owner["id"])[0].revoked_at is not None


def test_LOGOUT_sessiyasiz_mijoz_uchun_ONGARMAYDI(client, owner):
    """POS/desktop (sessiyasiz) uchun logout AYNAN avvalgidek: 0 qator tegadi."""
    body = _login(client, owner, refresh=False).json()
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    assert _sessions(client, owner["id"]) == []
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    assert _sessions(client, owner["id"]) == []
    #  `sec_epoch` global lever HAMON ishlaydi.
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_GLOBAL_sec_epoch_sid_tokenni_ham_oldiradi(client, owner):
    body = _login(client, owner, refresh=True).json()
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    db = _db()
    try:
        emp = db.get(Employee, uuid.UUID(owner["id"]))
        emp.sec_epoch = int(emp.sec_epoch or 0) + 1
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401


def test_PAROL_ozgarishi_eski_sessiyalarni_BEKOR_qiladi(client, owner):
    old = _login(client, owner, refresh=True).json()
    auth = {"Authorization": f"Bearer {old['access_token']}"}
    new_pw = "Buxoro-Bahor-2027"
    r = client.post("/api/v1/auth/password", headers=auth | REFRESH_HEADER,
                    json={"old_password": PW, "new_password": new_pw})
    assert r.status_code == 200, r.text
    #  Eski refresh O'LGAN.
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": old["refresh_token"]}).status_code == 401
    #  Joriy qurilma esa chiqib qolMAYDI — yangi juftlik berildi.
    assert r.json().get("refresh_token")
    assert client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {r.json()['access_token']}"}
                      ).status_code == 200
    #  Parolni qaytaramiz (fikstura tozalashi uchun ahamiyatsiz, lekin izchil).
    client.post("/api/v1/auth/password",
                headers={"Authorization": f"Bearer {r.json()['access_token']}"},
                json={"old_password": new_pw, "new_password": PW})


# ── 7. AUDIT 4-BANDI: kechikkan revoke YANGI sessiyaga tegmaydi ─────────────

def test_KECHIKKAN_revoke_YANGI_sessiyani_oldirmaydi(client, owner):
    first = _login(client, owner, refresh=True).json()
    second = _login(client, owner, refresh=True).json()
    assert decode_token(first["access_token"])["sid"] != \
        decode_token(second["access_token"])["sid"], "har login YANGI sid olishi kerak"
    #  ESKI sessiyani KECHIKIB bekor qilamiz.
    r = client.post("/api/v1/auth/revoke",
                    headers={"Authorization": f"Bearer {first['access_token']}"},
                    json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200, r.text
    #  YANGI sessiya TIRIK.
    assert client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {second['access_token']}"}
                      ).status_code == 200
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": second["refresh_token"]}).status_code == 200


# ── 8. Kredensial bazada OCHIQ saqlanmaydi ──────────────────────────────────

def test_KREDENSIAL_bazada_OCHIQ_saqlanmaydi(client, owner):
    body = _login(client, owner, refresh=True).json()
    raw = body["refresh_token"]
    sid, secret = raw.split(".", 1)
    rows = _sessions(client, owner["id"])
    stored = {rows[0].refresh_hash, rows[0].prev_refresh_hash}
    assert secret not in stored, "xom sir bazada TURMASLIGI kerak"
    assert raw not in stored
    #  Saqlangani — keyed-hash.
    assert rows[0].refresh_hash == hash_refresh(secret)
    assert len(rows[0].refresh_hash) == 64      # sha256 hex
