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
