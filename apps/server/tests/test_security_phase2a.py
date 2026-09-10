# -*- coding: utf-8 -*-
"""Xavfsizlik 2A — vendor auth, sir siyosati, konfiguratsiya gate'i, deploy konteksti.

Qamrov:
  P1-3  vendor autentifikatsiyasi/sessiyasi (rate limit, bir xil 401, bekor qilish)
  P1-5  `.vendor_key.txt` deploy kontekstiga tushmasligi
  P1-6  zaif `SECRET_KEY` production'da qabul qilinmasligi
  P1-8  `config_audit` boot/readiness/CI ni haqiqatan gate qilishi
"""
import base64
import hashlib
import hmac
import pathlib
import struct
import time

import pytest

_VK = {"X-Vendor-Key": "test-vendor-key"}
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _totp_now(secret: str) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


# ═══ P1-3 · VENDOR AUTENTIFIKATSIYASI ═══════════════════════════════════════

def test_vendor_auth_is_rate_limited(client):
    """⚠️  Vendor auth CHEKLANGAN. Ilgari umuman cheklov yo'q edi: 6 raqamli TOTP
    (±1 oyna = 1 000 000 dan 3 ta jonli kod) soatlar ichida topilardi va hech qanday
    ogohlantirish chiqmasdi."""
    codes = [client.get("/api/v1/admin/overview",
                        headers={"X-Vendor-Key": f"wrong-{i}"}).status_code
             for i in range(8)]
    assert 429 in codes, codes
    assert codes.index(429) <= 6, codes


def test_vendor_rate_limit_state_survives_process_restart(client):
    """Hisoblagich BAZADA — deploy yoki qayta ishga tushish uni nolga tushirmaydi.

    Xotiradagi hisoblagich har deploy'da tozalanardi va instanslar o'rtasida
    bo'linmasdi, ya'ni hujumchi deploy kutib chetlab o'tardi. Redis loyihada yo'q,
    shu bois mavjud Postgres/SQLite ishlatiladi."""
    from app.db.session import SessionLocal
    from app.models.vendor import VendorAuthAttempt

    for i in range(3):
        client.get("/api/v1/admin/overview", headers={"X-Vendor-Key": f"nope-{i}"})
    db = SessionLocal()
    try:
        n = db.query(VendorAuthAttempt).count()
    finally:
        db.close()
    assert n >= 3, f"urinishlar bazada saqlanmadi: {n}"


def test_vendor_401_is_uniform_for_key_and_session(client):
    """⚠️  ORACLE YO'Q. Kalit noto'g'ri, sessiya yaroqsiz — javob AYNAN bir xil.

    Ilgari 401 matni farq qilardi ("kalit noto'g'ri" va "2FA yoqilgan, OTP kiriting"),
    ya'ni hujumchi OTP'ni bilmasdan kalitni taxmin qilishni avtomatlashtirib,
    to'g'ri topganini darhol bilardi."""
    a = client.get("/api/v1/admin/overview", headers={"X-Vendor-Key": "butunlay-boshqa"})
    b = client.get("/api/v1/admin/overview", headers={"X-Vendor-Session": "yaroqsiz.token"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json(), (a.json(), b.json())


def test_vendor_401_is_uniform_for_wrong_key_and_wrong_otp(client, monkeypatch):
    """Kalit noto'g'ri va OTP noto'g'ri — ikkalasi ham bir xil javob."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "vendor_totp_secret", "JBSWY3DPEHPK3PXP")

    wrong_key = client.post("/api/v1/admin/login",
                            headers={"X-Vendor-Key": "notmykey"}, json={"otp": "000000"})
    wrong_otp = client.post("/api/v1/admin/login", headers=_VK, json={"otp": "000000"})
    assert wrong_key.status_code == wrong_otp.status_code == 401
    assert wrong_key.json() == wrong_otp.json(), (wrong_key.json(), wrong_otp.json())


def test_vendor_non_ascii_key_is_rejected_not_crashed():
    """ASCII bo'lmagan kalit `compare_digest` da TypeError berib 500 ga aylanardi.

    HTTP sarlavhalari latin-1 kodlanadi va test klienti bunday qiymatni umuman
    yubormaydi, shuning uchun funksiya BEVOSITA sinaladi — himoya aynan shu yerda."""
    from app.api.v1.admin import _key_ok
    assert _key_ok("kalit-ø") is False        # xato KO'TARMASLIGI kerak
    assert _key_ok("安全") is False


def test_vendor_session_can_be_revoked(client):
    """⚠️  Sessiya BEKOR QILINADI. Ilgari token faqat `exp` dan iborat edi va uni
    to'xtatishning yagona yo'li master kalitni almashtirish edi."""
    r = client.post("/api/v1/admin/login", headers=_VK, json={})
    assert r.status_code == 200, r.text
    sess = {"X-Vendor-Session": r.json()["session"]}

    assert client.get("/api/v1/admin/overview", headers=sess).status_code == 200
    assert client.post("/api/v1/admin/logout", headers=sess).status_code == 200
    assert client.get("/api/v1/admin/overview", headers=sess).status_code == 401


def test_vendor_session_has_jti_recorded_in_the_database(client):
    """Sessiya server tomonda QAYD ETILADI — imzoning o'zi yetarli emas."""
    from app.db.session import SessionLocal
    from app.models.vendor import VendorSession

    r = client.post("/api/v1/admin/login", headers=_VK, json={})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        rows = db.query(VendorSession).all()
        assert rows, "sessiya bazada qayd etilmadi"
        assert all(x.jti and x.issued_at and x.expires_at for x in rows)
    finally:
        db.close()


def test_vendor_session_signature_alone_is_not_enough(client):
    """Imzo to'g'ri, LEKIN qator bekor qilingan bo'lsa — rad etiladi.

    Bu server tomondagi holat haqiqatan tekshirilayotganini isbotlaydi (faqat HMAC emas)."""
    from app.db.session import SessionLocal
    from app.models.vendor import VendorSession
    from datetime import datetime, timezone

    r = client.post("/api/v1/admin/login", headers=_VK, json={})
    sess = {"X-Vendor-Session": r.json()["session"]}
    assert client.get("/api/v1/admin/overview", headers=sess).status_code == 200

    db = SessionLocal()
    try:
        for row in db.query(VendorSession).filter(VendorSession.revoked_at.is_(None)).all():
            row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/admin/overview", headers=sess).status_code == 401


def test_vendor_auth_events_are_audited_without_secrets(client):
    """Sessiya yaratilishi auditga tushadi va u yerda SIR bo'lmaydi."""
    from app.db.session import SessionLocal
    from app.models.sync import AuditLog

    r = client.post("/api/v1/admin/login", headers=_VK, json={})
    assert r.status_code == 200
    sess_token = r.json()["session"]

    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.entity == "vendor_session").all()
        assert rows, "vendor sessiya auditga tushmadi"
        blob = " ".join(str(x.after) + str(x.before) for x in rows)
    finally:
        db.close()
    assert "test-vendor-key" not in blob, "MASTER KALIT auditga yozildi"
    assert sess_token not in blob, "SESSIYA TOKENI auditga yozildi"


# ═══ P1-6 · SECRET_KEY SIYOSATI ═════════════════════════════════════════════

@pytest.mark.parametrize("value,must_fail", [
    ("", True),                                  # yo'q
    ("dev-secret-change-me", True),              # standart
    ("x", True),                                 # juda qisqa
    ("secret", True),                            # shablon
    ("changeme-changeme", True),                 # shablondan boshlanadi
    ("x" * 64, True),                            # takrorlanuvchi naqsh
    ("abababababababababababababababab", True),  # past entropiya
    ("K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c", False),  # yaroqli
])
def test_secret_key_policy(value, must_fail):
    """⚠️  Ilgari tekshiruv `secret_key == DEFAULT_SECRET` edi — AYNAN o'sha satr.
    `SECRET_KEY=x` bergan production yashil ko'tarilib, tokenlarni bir belgili kalit
    bilan imzolardi."""
    from app.core.security_config import secret_key_problem
    problem = secret_key_problem(value)
    assert (problem is not None) is must_fail, (value[:12], problem)


def test_secret_key_value_is_never_returned_in_the_reason():
    """Sabab matnida kalitning O'ZI bo'lmasligi kerak."""
    from app.core.security_config import secret_key_problem
    secret = "zaif-kalit-qiymati"
    problem = secret_key_problem(secret)
    assert problem and secret not in problem, problem


# ═══ P1-8 · KONFIGURATSIYA GATE'I ═══════════════════════════════════════════

def _prod(monkeypatch, **over):
    """Production sozlamalarini taqlid qiladi."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "database_url", "postgresql://x/y")
    monkeypatch.setattr(settings, "app_env", "prod", raising=False)
    for k, v in over.items():
        monkeypatch.setattr(settings, k, v, raising=False)


def test_production_refuses_weak_secret(monkeypatch):
    """Zaif SECRET_KEY bilan production ISHGA TUSHMAYDI."""
    from app.core import security_config
    _prod(monkeypatch, secret_key="x")
    with pytest.raises(security_config.UnsafeConfigError) as ei:
        security_config.enforce_at_boot()
    assert "SECRET_KEY" in str(ei.value)
    assert "x" * 8 not in str(ei.value)          # qiymat chiqmaydi


def test_production_refuses_sqlite(monkeypatch):
    from app.core import security_config
    from app.core.config import settings
    _prod(monkeypatch, secret_key="K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c")
    monkeypatch.setattr(settings, "database_url", "sqlite:///./x.db")
    monkeypatch.setattr(settings, "app_env", "prod", raising=False)
    bad = [r["key"] for r in security_config.critical_failures()]
    assert "DATABASE_URL" in bad, bad


def test_production_refuses_vendor_without_mfa(monkeypatch):
    """⚠️  Production'da vendor 2FA MAJBURIY — kalit yolg'iz cross-tenant kirishga yetmaydi."""
    from app.core import security_config
    _prod(monkeypatch, secret_key="K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c",
          vendor_admin_key="k" * 40, vendor_totp_secret="",
          vendor_allowed_ips="10.0.0.1")
    bad = [r["key"] for r in security_config.critical_failures()]
    assert "VENDOR_TOTP_SECRET" in bad, bad


def test_production_refuses_vendor_without_ip_allowlist(monkeypatch):
    from app.core import security_config
    _prod(monkeypatch, secret_key="K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c",
          vendor_admin_key="k" * 40, vendor_totp_secret="JBSWY3DPEHPK3PXP",
          vendor_allowed_ips="")
    bad = [r["key"] for r in security_config.critical_failures()]
    assert "VENDOR_ALLOWED_IPS" in bad, bad


def test_production_refuses_seed_demo(monkeypatch):
    """Production + SEED_DEMO=1 — MA'LUM kredensialli soxta tenant tushardi."""
    from app.core import security_config
    _prod(monkeypatch, secret_key="K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c")
    monkeypatch.setenv("SEED_DEMO", "1")
    bad = [r["key"] for r in security_config.critical_failures()]
    assert "SEED_DEMO" in bad, bad


def test_safe_production_config_passes(monkeypatch):
    """To'g'ri sozlangan production ISHGA TUSHADI — gate ortiqcha qattiq emas."""
    from app.core import security_config
    _prod(monkeypatch, secret_key="K7f-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0c",
          vendor_admin_key="k" * 40, vendor_totp_secret="JBSWY3DPEHPK3PXP",
          vendor_allowed_ips="10.0.0.1,10.0.0.2")
    monkeypatch.delenv("SEED_DEMO", raising=False)
    assert security_config.critical_failures() == []
    security_config.enforce_at_boot()            # xato KO'TARMASLIGI kerak


def test_config_audit_uses_the_canonical_evaluation(monkeypatch):
    """⚠️  BITTA manba. Ilgari shartlar `main.py`, `/health/ready` va `config_audit` da
    ALOHIDA yozilgan edi va vaqt o'tib bir-biridan uzoqlashdi — `config_audit` vendor
    2FA yo'qligini "REVIEW" deb belgilar, boot esa umuman tekshirmasdi."""
    from app.core import security_config
    from app.tools.config_audit import audit
    _prod(monkeypatch, secret_key="x", vendor_admin_key="k" * 40,
          vendor_totp_secret="", vendor_allowed_ips="")
    rows = {r["key"]: r for r in audit()}
    for key in [r["key"] for r in security_config.critical_failures()]:
        assert key in rows, f"{key} hisobotda yo'q"
        assert rows[key]["critical"] is True, f"{key} kritik deb belgilanmagan"


def test_readiness_reports_security_config(client):
    """Readiness javobida `config` bor va SIR qiymatlari YO'Q."""
    r = client.get("/api/v1/health/ready")
    body = r.json()
    assert "config" in body["checks"], body
    assert "test-vendor-key" not in r.text
    assert "dev-secret-change-me" not in r.text


# ═══ P1-5 · DEPLOY KONTEKSTI ════════════════════════════════════════════════

_SECRET_FILE_PATTERNS = (".env", ".env.*", ".vendor_key.txt", "*.pem", "*.key")


@pytest.mark.parametrize("pattern", _SECRET_FILE_PATTERNS)
def test_secret_files_are_excluded_from_every_deploy_context(pattern):
    """⚠️  Sir fayllari HECH QANDAY deploy kontekstiga tushmasligi kerak.

    `.vendor_key.txt` (vendor MASTER kaliti) `.dockerignore` da bor edi, LEKIN
    `.railwayignore` da YO'Q. Loyihaning o'z runbook'i `railway up` ni tavsiya
    qiladi — ya'ni master kalit deploy qilingan obraz ichiga tushishi mumkin edi.
    Ikkala ro'yxat ham tekshiriladi, aks holda ular yana uzoqlashadi."""
    for name in (".dockerignore", ".railwayignore"):
        path = ROOT / name
        assert path.exists(), f"{name} yo'q"
        lines = {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()}
        assert pattern in lines, f"{name}: '{pattern}' istisno qilinmagan"


def test_vendor_key_file_is_not_tracked_by_git():
    """Fayl git'da BO'LMASLIGI kerak (tarkibi O'QILMAYDI)."""
    import subprocess
    out = subprocess.run(["git", "ls-files"], cwd=ROOT.parents[0],
                         capture_output=True, text=True, check=True).stdout
    assert ".vendor_key.txt" not in out, "vendor kaliti git'da KUZATILMOQDA"


# ═══ ISHONCHLI PROXY MODELI ═════════════════════════════════════════════════

@pytest.mark.parametrize("chain,expected,nega", [
    # Edge STRIP qilgan holat: mijoz + ichki hop
    ("93.184.216.34, 100.64.0.7", "93.184.216.34", "ichki hop tashlanadi"),
    # Edge QO'SHGAN holat: hujumchi CHAPGA soxta qiymat qo'ydi
    ("8.8.8.8, 93.184.216.34, 100.64.0.7", "93.184.216.34", "soxta qiymatga YETIB BORILMAYDI"),
    # Bir NECHTA ichki hop (topologiya chuqurlashdi) — hop soni AHAMIYATSIZ
    ("93.184.216.34, 100.64.0.7, 10.0.0.3, 192.168.1.1", "93.184.216.34", "chuqurlik siljishi"),
    # IPv6 mijoz + IPv6 ULA ichki hop
    ("2606:4700:4700::1111, fd12:2c84::1", "2606:4700:4700::1111", "IPv6"),
    # Port bilan kelgan shakllar
    ("93.184.216.34:51234, 100.64.0.7", "93.184.216.34", "IPv4:port"),
    ("[2606:4700:4700::1111]:443, 100.64.0.7", "2606:4700:4700::1111", "IPv6 qavs+port"),
    # Faqat ichki manzillar -> OMMAVIY yo'q -> fail-closed
    ("100.64.0.7, 10.0.0.3", "", "ommaviy manzil yo'q"),
    # Buzuq qiymatlar tashlanadi
    ("not-an-ip, 93.184.216.34, 100.64.0.7", "93.184.216.34", "buzuq qiymat"),
    ("not-an-ip, 100.64.0.7", "", "faqat buzuq va ichki"),
])
def test_client_ip_scans_from_the_right_skipping_infrastructure(chain, expected, nega):
    """⚠️  Ilgari IKKALA joyda ham XFF ning ENG O'NG qismi QAT'IY olinardi.

    Railway'ning O'Z xodimlari bu savolga zid javob berishgan (biri "eng chap",
    boshqasi "eng o'ng"), va mijoz yuborgan `X-Forwarded-For: 8.8.8.8` filtrlanmasdan
    qaytgani KO'RSATILGAN — ya'ni edge zanjirga qo'shadi. Ustiga, CDN (Fastly) yo'li
    bosqichma-bosqich yoqilmoqda, ya'ni ZANJIR CHUQURLIGI KAFOLATLANMAGAN.

    Shuning uchun na eng chap qiymat (spoofing), na qat'iy hop sanog'i (topologiya
    siljishi) yaroqli. Diapazon bo'yicha skanerlash ikkala o'qishda ham to'g'ri
    ishlaydi va hop soniga bog'liq emas."""
    from app.core import net

    class _Req:
        headers = {"x-forwarded-for": chain}
        client = None

    assert net.client_ip(_Req()) == expected, nega


def test_client_ip_falls_back_to_peer_without_a_proxy():
    """Proxy yo'q (lokal dev) — peer manzilining o'zi."""
    from app.core import net

    class _Client:
        host = "127.0.0.1"

    class _Req:
        headers = {}
        client = _Client()

    assert net.client_ip(_Req()) == "127.0.0.1"


def test_attacker_cannot_choose_the_rate_limit_key():
    """⚠️  Hujumchi rate-limit KALITINI TANLAY OLMAYDI.

    Bu rate-limit'ning butun ma'nosi: kalitni hujumchi boshqarsa, u har so'rovda
    yangi kalit yuborib cheklovni butunlay chetlab o'tardi."""
    from app.core import net

    real = "93.184.216.34"
    infra = "100.64.0.7"
    spoofs = ["8.8.8.8", "1.1.1.1", "9.9.9.9", "127.0.0.1", "10.0.0.9",
              "not-an-ip", "2606:4700:4700::1001"]

    keys = set()
    for spoof in spoofs:
        class _Req:
            headers = {"x-forwarded-for": f"{spoof}, {real}, {infra}"}
            client = None
        keys.add(net.client_ip(_Req()))
    assert keys == {real}, f"kalit hujumchi ta'sirida O'ZGARDI: {keys}"
