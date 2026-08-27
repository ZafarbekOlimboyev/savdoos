"""Xavfsizlik regressiya testlari — imtiyoz-oshirish himoyasi, brute-force lockout, vendor auth.

Bular 2026-avgust auditidan keyin qo'shildi; qayta regressiya qilinmasin.
"""
import uuid


def _mgr_with_edit(client, admin_headers):
    """xodimlar.edit ruxsatли non-admin menejer yaratadi va login token qaytaradi."""
    phone = f"+99890{uuid.uuid4().int % 10000000:07d}"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": "QA Menejer", "phone": phone, "role_code": "menejer", "password": "mgr12345"})
    assert r.status_code == 200, r.text
    mid = next(e["id"] for e in client.get("/api/v1/employees", headers=admin_headers).json()
               if e["phone"] == phone)
    client.patch(f"/api/v1/employees/{mid}/permissions", headers=admin_headers,
                 json={"overrides": {"xodimlar.edit": True}})
    tok = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": "mgr12345"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, phone


def test_admin_can_login(admin_headers):
    assert "Authorization" in admin_headers


def test_non_admin_cannot_create_administrator(client, admin_headers):
    mgr, _ = _mgr_with_edit(client, admin_headers)
    r = client.post("/api/v1/employees", headers=mgr, json={
        "full_name": "Yovuz", "phone": "+998900000091", "role_code": "administrator", "password": "hack12345"})
    assert r.status_code == 403


def test_non_admin_cannot_takeover_administrator(client, admin_headers):
    mgr, _ = _mgr_with_edit(client, admin_headers)
    admin_id = next(e["id"] for e in client.get("/api/v1/employees", headers=admin_headers).json()
                    if e["role"] == "administrator")
    # parolni almashtirish
    assert client.patch(f"/api/v1/employees/{admin_id}", headers=mgr, json={"password": "pwned12345"}).status_code == 403
    # o'chirish
    assert client.delete(f"/api/v1/employees/{admin_id}", headers=mgr).status_code == 403


def test_non_admin_can_create_cashier(client, admin_headers):
    """Oddiy xodim yaratish TAQIQLANMAGAN — himoya faqat administratorga tegishli."""
    mgr, _ = _mgr_with_edit(client, admin_headers)
    r = client.post("/api/v1/employees", headers=mgr, json={"full_name": "Oddiy Kassir", "role_code": "kassir"})
    assert r.status_code == 200


def test_login_lockout(client):
    """Ketma-ket noto'g'ri parol — belgilangan chegaradan keyin 429 (brute-force himoya)."""
    codes = [client.post("/api/v1/auth/login/password",
                         json={"phone": "+998900000001", "password": "wrong"}).status_code for _ in range(13)]
    assert 429 in codes, codes
    assert codes.index(429) <= 12


def test_vendor_key_required(client):
    assert client.get("/api/v1/admin/overview", headers={"X-Vendor-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/admin/overview", headers={"X-Vendor-Key": "test-vendor-key"}).status_code == 200


def test_vendor_portal_served(client):
    r = client.get("/api/v1/admin/portal")
    assert r.status_code == 200 and "SavdoOS Vendor" in r.text


_VK = {"X-Vendor-Key": "test-vendor-key"}


def _provision(client, pw="owner12345"):
    """Yangi (alohida) do'kon ochadi — seed demo do'koniga tegmasligi uchun."""
    phone = f"+99891{uuid.uuid4().int % 10000000:07d}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": "QA Do'kon", "company_code": f"co{uuid.uuid4().hex[:8]}",
        "owner_name": "QA Ega", "owner_phone": phone, "owner_password": pw, "plan": "start"})
    assert r.status_code == 200, r.text
    return r.json()["company_id"], phone, pw


def _pw_login(client, phone, pw):
    return client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw}).status_code


def test_suspend_blocks_then_restores_login(client):
    cid, phone, pw = _provision(client)
    assert _pw_login(client, phone, pw) == 200            # dastlab kiradi
    assert client.patch(f"/api/v1/admin/companies/{cid}/suspend", headers=_VK, json={"suspended": True}).status_code == 200
    assert _pw_login(client, phone, pw) == 403            # to'xtatilgan — bloklandi
    assert client.patch(f"/api/v1/admin/companies/{cid}/suspend", headers=_VK, json={"suspended": False}).status_code == 200
    assert _pw_login(client, phone, pw) == 200            # qayta yoqildi


def test_delete_company_blocks_login_and_hides(client):
    cid, phone, pw = _provision(client)
    assert _pw_login(client, phone, pw) == 200
    assert client.delete(f"/api/v1/admin/companies/{cid}", headers=_VK).status_code == 200
    assert _pw_login(client, phone, pw) == 401            # o'chirilgan — umumiy xato (oshkor qilinmaydi)
    comps = client.get("/api/v1/admin/companies", headers=_VK).json()["companies"]
    assert cid not in [c["id"] for c in comps]            # ro'yxatда ko'rinmaydi


def test_suspended_flag_in_listing(client):
    cid, _phone, _pw = _provision(client)
    client.patch(f"/api/v1/admin/companies/{cid}/suspend", headers=_VK, json={"suspended": True})
    row = next(c for c in client.get("/api/v1/admin/companies", headers=_VK).json()["companies"] if c["id"] == cid)
    assert row["suspended"] is True


def test_vendor_login_session_no_2fa(client):
    """2FA o'chiq: /admin/login sessiya tokeni beradi; token bilan endpointlarga kirish mumkin."""
    r = client.post("/api/v1/admin/login", headers=_VK, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totp"] is False and body["session"]
    sess = {"X-Vendor-Session": body["session"]}
    assert client.get("/api/v1/admin/overview", headers=sess).status_code == 200
    assert client.get("/api/v1/admin/overview", headers={"X-Vendor-Session": "bad.token"}).status_code == 401


def _totp_now(secret: str) -> str:
    import base64
    import hashlib
    import hmac as _h
    import struct
    import time
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = _h.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def test_vendor_2fa_totp_flow(client, monkeypatch):
    """2FA yoqilса: kalitning o'zi yetмaydi (401); to'g'ri OTP bilan /admin/login sessiya beradi."""
    from app.core.config import settings
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setattr(settings, "vendor_totp_secret", secret)
    # kalit bor, lekin 2FA yoqilgan — to'g'ridan-to'g'ri kirish taqiqlanadi
    assert client.get("/api/v1/admin/overview", headers=_VK).status_code == 401
    # OTP'siz login -> 401
    assert client.post("/api/v1/admin/login", headers=_VK, json={}).status_code == 401
    # noto'g'ri OTP -> 401
    assert client.post("/api/v1/admin/login", headers=_VK, json={"otp": "000000"}).status_code == 401
    # to'g'ri OTP -> 200 + sessiya
    r = client.post("/api/v1/admin/login", headers=_VK, json={"otp": _totp_now(secret)})
    assert r.status_code == 200, r.text
    sess = r.json()["session"]
    assert client.get("/api/v1/admin/overview", headers={"X-Vendor-Session": sess}).status_code == 200
