# -*- coding: utf-8 -*-
"""ADMIN-1.0 / P0-B..P0-G — vendor konsolining OPERATSION tayyorligi.

NEGA BU FAYL BOR
================
ADMIN-1.0-LAUNCH-GAP ko'rigi konsolni «backend bor, UI yo'q yoki buzuq»
holatida topdi. Quyidagi testlar AYNAN o'sha o'lchangan bo'shliqlarni
qulflaydi — har biri BIRINCHI NAVBATDA XULQNI (HTTP yoki DOM), faqat
zarurda manbani o'lchaydi.

⚠️  MANBA GARDLARI (`_portal`) NEGA KERAK. Konsol — bitta statik HTML
    fayl, unda brauzer E2E dan tashqari ijro yo'li YO'Q. Shu bois
    ba'zi da'volar (maydon ko'rinadimi, parol bannerda qoladimi) fayl
    MATNI bo'yicha o'lchanadi. Brauzer darajasidagi tekshiruv alohida:
    `e2e/vendor-portal.spec.ts`.

⚠️  PRODUKSIYA MA'LUMOTI YO'Q. Hamma do'kon shu testda yaratiladi;
    telefon, kod va parollar SINTETIK.
"""
from __future__ import annotations

import io
import pathlib
import re
import uuid
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTAL = ROOT / "app" / "static" / "vendor_portal.html"
ADMIN_PY = ROOT / "app" / "api" / "v1" / "admin.py"

VK = {"X-Vendor-Key": "test-vendor-key"}
VK_YOLGON = {"X-Vendor-Key": "butunlay-boshqa-kalit"}
PAROL = "Toshkent-Bahor-2026"          # 19 belgi — siyosatdan o'tadi
QISQA = "Parol-11xyz"                  # 11 belgi — siyosat RAD etadi


# ── yordamchilar ──────────────────────────────────────────────────────────
def _portal() -> str:
    return io.open(PORTAL, encoding="utf-8").read()


def _portal_izohsiz() -> str:
    """Konsol HTML’i IZOHLARSIZ.

    ⚠️  NEGA KERAK — BU REPODA O‘LCHANGAN TUZOQ: manba gardlari izohni ham
        sanaydi. Tuzatish izohida «ilgari kamida 6 yozilgan edi» deb
        TUSHUNTIRISH yozilishi tabiiy, va u «kamida 6 qolmasin» gardini
        JIM QIZIL qilardi (aynan shu test RED bosqichida shunday yiqildi).

    ⚠️  CHEKLOV, OCHIQ AYTILADI: regex FAQAT SATR BOSHIDAGI JS izohlarini
        oladi (`^\\s*//`), ya’ni satr OXIRIDAGI `// ...` izohlari QOLADI.
        Bu ataylab: `//` ni har joyda kesish URL larni (`https://`) ham
        buzardi. Xavf yo‘nalishi XAVFSIZ tomonga — qolgan izoh `not in`
        gardida YOLG‘ON QIZIL berishi mumkin, YOLG‘ON YASHIL emas.
    """
    h = _portal()
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)          # HTML izohlari
    h = re.sub(r"(?m)^\s*//.*$", " ", h)                   # JS qator izohlari
    return h


def _vendor_tozala():
    """Vendor urinishlari jadvalini tozalaydi.

    ⚠️  NEGA KERAK: `_VENDOR_IP_TIER` bir xil manbadan kelgan urinishlarni
        sanaydi va TestClient HAR SO‘ROVNI ayni manbadan yuboradi. Ketma-ket
        bir necha rad etilgan proba 401 o‘rniga 429 qaytarardi — ya’ni test
        darvozani emas, cheklovni o‘lchab qo‘yardi.
    """
    from app.models.vendor import VendorAuthAttempt
    db = _db()
    try:
        db.query(VendorAuthAttempt).delete()
        db.commit()
    finally:
        db.close()


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _tel() -> str:
    return "+99894%07d" % (uuid.uuid4().int % 10000000)


def _kod() -> str:
    return "p0" + uuid.uuid4().hex[:10]


def _ochish(client, **ustun):
    """`POST /admin/companies` — sintetik do'kon."""
    tana = {"company_name": "P0 QA", "company_code": _kod(),
            "owner_name": "P0 Ega", "owner_phone": _tel(),
            "owner_password": PAROL, "plan": "start"}
    tana.update(ustun)
    return client.post("/api/v1/admin/companies", headers=VK, json=tana), tana


def _kirish(client, tel, parol=PAROL):
    return client.post("/api/v1/auth/login/password",
                       json={"phone": tel, "password": parol})


def _totp(sir: str, siljish: int = 0) -> str:
    """Joriy TOTP kodi — `admin._totp_ok` bilan AYNI algoritm."""
    import base64
    import hashlib
    import hmac
    import struct
    import time
    key = base64.b32decode(sir + "=" * (-len(sir) % 8))
    c = int(time.time() // 30) + siljish
    h = hmac.new(key, struct.pack(">Q", c), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000)


# ══════════════════════════════════════════════════════════════════════════
#  P0-B — PRODUCTION ADMIN LOGIN (2FA maydoni, anti-oracle, sessiya)
# ══════════════════════════════════════════════════════════════════════════

def test_P0B_1_2FA_maydoni_SHAKLDA_KORINADI():
    """OTP maydoni `display:none` ORTIDA bo'lmasin.

    O'LCHANGAN NUQSON: `#otpRow` da `display:none` turardi va maydon FAQAT
    server 401 matnida "otp"/"2fa" so'zi uchrasa ochilardi. Production'da
    2FA MAJBURIY (`admin.py`: 2FA sozlanmagan bo'lsa 503), ya'ni operator
    kira olmasligi uchun yetarli edi.
    """
    h = _portal()
    m = re.search(r'<div class="field" id="otpRow"[^>]*>', h)
    assert m, "`#otpRow` topilmadi — shakl o'zgargan"
    assert "display:none" not in m.group(0), (
        "2FA maydoni HAMON yashirin: %s" % m.group(0))
    assert 'id="otp"' in h, "OTP input yo'q"
    #  Yorliq `for=` bilan bog'langan (skrinriderda ham ko'rinadi).
    assert 'for="otp"' in h, "OTP yorligi inputga bog'lanmagan"


def test_P0B_2_XATO_MATNI_PARSE_QILINMAYDI_anti_oracle():
    """Mijoz 401 matnini tasniflamasin — bu serverning yagona 401 ini buzardi."""
    h = _portal()
    assert "/otp|2fa/i" not in _portal_izohsiz(), (
        "mijoz HAMON xato matnini parse qiladi — bu mijoz tomonda ORACLE "
        "yasaydi (kalit to'g'ri, faqat OTP xato)")
    #  Vakuumga qarshi: `doLogin` haqiqatan shu faylda.
    assert "async function doLogin()" in h


def test_P0B_3_TOGRI_OTP_kiradi_XATO_OTP_va_XATO_KALIT_AYNI_401(client, monkeypatch):
    """2FA yoqilganda: to'g'ri kod -> sessiya; xato kod va xato kalit -> AYNI 401."""
    from app.api.v1 import admin as A
    from app.core.config import settings

    sir = "JBSWY3DPEHPK3PXP"
    monkeypatch.setattr(settings, "vendor_totp_secret", sir)
    assert settings.vendor_2fa_on is True

    #  (a) TO'G'RI kod -> sessiya.
    r = client.post("/api/v1/admin/login", headers=VK, json={"otp": _totp(sir)})
    assert r.status_code == 200, r.text
    sess = r.json()["session"]
    assert sess and r.json()["totp"] is True

    #  (b) XATO kod -> 401, va matn XATO KALIT bilan AYNI (oracle yo'q).
    r_otp = client.post("/api/v1/admin/login", headers=VK, json={"otp": "000000"})
    r_key = client.post("/api/v1/admin/login", headers=VK_YOLGON,
                        json={"otp": _totp(sir)})
    r_none = client.post("/api/v1/admin/login", json={"otp": _totp(sir)})
    assert r_otp.status_code == r_key.status_code == r_none.status_code == 401, (
        r_otp.status_code, r_key.status_code, r_none.status_code)
    assert r_otp.json() == r_key.json() == r_none.json(), (
        "javoblar FARQ qiladi — oracle: otp=%r key=%r kalitsiz=%r"
        % (r_otp.text, r_key.text, r_none.text))
    assert A._VENDOR_401 in r_otp.text

    #  (c) Sessiya bilan konsol ishlaydi; 2FA yoqilganda XOM KALIT ishlamaydi.
    ok = client.get("/api/v1/admin/overview", headers={"X-Vendor-Session": sess})
    assert ok.status_code == 200, ok.text
    xom = client.get("/api/v1/admin/overview", headers=VK)
    assert xom.status_code == 401, (
        "2FA yoqilganda xom master kalit avtorizatsiya sifatida QABUL QILINDI")


def test_P0B_4_LOGOUT_tokenni_DARHOL_kuchsiz_qiladi(client):
    """Chiqish -> sessiya bekor; o'sha token bilan hech narsa ochilmaydi."""
    r = client.post("/api/v1/admin/login", headers=VK, json={"otp": None})
    assert r.status_code == 200, r.text
    sess = r.json()["session"]
    H = {"X-Vendor-Session": sess}
    assert client.get("/api/v1/admin/overview", headers=H).status_code == 200
    assert client.post("/api/v1/admin/logout", headers=H).status_code == 200
    assert client.get("/api/v1/admin/overview", headers=H).status_code == 401, (
        "bekor qilingan sessiya HAMON ishlaydi")


def test_P0B_4b_SHAKLDAGI_CHIQISH_serverga_LOGOUT_yuboradi():
    """«Chiqish» mijoz holatini tozalash bilan CHEKLANMASIN.

    O'LCHANGAN NUQSON (haqiqiy brauzerda, ADMIN-1.0/P0-H tekshiruvida):
    `logout()` FAQAT `sessionStorage` va sahifa holatini tozalardi, server
    tomondagi `vendor_sessions` qatori TEGILMASDI. Natija o'lchandi:

        logout(); GET /admin/overview  (X-Vendor-Session: eski)  ->  200

    ya'ni operator «chiqdim» deb o'ylardi, token esa to'liq muddati
    (standart 2 soat) davomida tirik qolardi. Backend `POST /admin/logout`
    ALLAQACHON bor edi (`test_P0B_4` isbotlaydi) — konsol uni chaqirmasdi.

    Tuzatishdan keyin AYNI o'lchov 401 beradi (brauzerda tasdiqlangan).
    """
    h = _portal()
    i = h.index("async function logout()")
    blok = h[i:h.index("function showApp()", i)]
    assert "/api/v1/admin/logout" in blok, (
        "`logout()` serverga chiqish so'rovini YUBORMAYDI — sessiya "
        "bekor qilinmaydi va token tirik qoladi")
    assert "method:'POST'" in blok, blok[-300:]
    assert "X-Vendor-Session" in blok, blok[-300:]
    #  `api()` orqali EMAS: u 401 da yana `logout()` ni chaqiradi (rekursiya).
    assert "api('/logout'" not in blok and "api(\"/logout\"" not in blok, (
        "chiqish `api()` orqali yuborilgan — 401 da rekursiya bo'ladi")


def test_P0B_5_MUDDATI_OTGAN_sessiya_RAD_etiladi(client):
    """`expires_at` o'tgan qator — imzo to'g'ri bo'lsa ham RAD etiladi."""
    from app.models.vendor import VendorSession

    r = client.post("/api/v1/admin/login", headers=VK, json={"otp": None})
    sess = r.json()["session"]
    H = {"X-Vendor-Session": sess}
    assert client.get("/api/v1/admin/overview", headers=H).status_code == 200

    db = _db()
    try:
        qator = db.query(VendorSession).order_by(
            VendorSession.issued_at.desc()).first()
        assert qator is not None
        qator.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/admin/overview", headers=H).status_code == 401, (
        "muddati o'tgan sessiya qabul qilindi")


def test_P0B_6_AVTORIZATSIYASIZ_kirish_YOPIQ(client):
    """Sessiyasiz/kalitsiz va YOLG'ON kalit bilan konsol sirti yopiq."""
    uchlar = ["/api/v1/admin/overview", "/api/v1/admin/companies",
              "/api/v1/admin/deleted-companies", "/api/v1/admin/audit"]
    for u in uchlar:
        _vendor_tozala()
        assert client.get(u).status_code in (401, 403, 503), u
        _vendor_tozala()
        assert client.get(u, headers=VK_YOLGON).status_code in (401, 403), u
    _vendor_tozala()


# ══════════════════════════════════════════════════════════════════════════
#  P0-C — MIJOZ OCHISH (parol 12, filial, tz, valyuta, dublikat)
# ══════════════════════════════════════════════════════════════════════════

def test_P0C_1_PAROL_CHEGARASI_12_shaklda_ham_SERVERDA_ham(client):
    """Yorliq va mijoz tekshiruvi SERVER qoidasi (`MIN_LEN=12`) bilan BIR XIL."""
    from app.core.password_policy import MIN_LEN
    assert MIN_LEN == 12, "siyosat o'zgardi — shakl yorlig'ini ham yangilang"

    h = _portal_izohsiz()
    assert "kamida 6" not in h, "shaklda HAMON «kamida 6» yozilgan"
    assert "Parol (kamida 12 belgi)" in h, "parol yorlig'i 12 ni ko'rsatmaydi"
    assert "pw.length<12" in h, "mijoz tomonda 12 chegarasi yo'q"
    #  Parolni tiklash dialogida ham.
    assert "kamida 12 belgi" in h

    #  SERVER: 11 belgi RAD etiladi va do'kon YARATILMAYDI.
    r, tana = _ochish(client, owner_password=QISQA)
    assert r.status_code == 400, r.text
    from app.models.org import Company
    db = _db()
    try:
        assert db.query(Company).filter(
            Company.code == tana["company_code"]).first() is None, (
            "rad etilgan parol bilan YARIM do'kon qoldi")
    finally:
        db.close()


def test_P0C_2_FILIAL_NOMI_va_TZ_SHAKLDAN_YUBORILADI_va_SAQLANADI(client):
    """Qirg'iziston do'koni: `Asia/Bishkek` + o'z filial nomi."""
    h = _portal()
    #  Shakl maydonlari bor va `submitProvision` ularni YUBORADI.
    for nav in ('id="p_branch"', 'id="p_tz"', "branch_name:", "timezone:"):
        assert nav in h, "shakl `%s` ni yubormaydi" % nav
    assert 'value="Asia/Bishkek"' in h, "Asia/Bishkek tanlovi yo'q"

    #  SERVER: qiymatlar SAQLANADI.
    r, tana = _ochish(client, branch_name="Bishkek markaz",
                      timezone="Asia/Bishkek", currency="KGS")
    assert r.status_code == 200, r.text
    from app.models.org import Branch, Company
    db = _db()
    try:
        c = db.query(Company).filter(Company.code == tana["company_code"]).one()
        b = db.query(Branch).filter(Branch.company_id == c.id).one()
        assert b.name == "Bishkek markaz", b.name
        assert b.timezone == "Asia/Bishkek", b.timezone
        assert c.currency == "KGS", c.currency
    finally:
        db.close()


def test_P0C_3_SHAKLDAGI_TZ_ROYXATI_SERVER_royxatining_QISMI(client):
    """Shakldagi har bir tanlov SERVER qabul qiladigan to'plamda bo'lsin."""
    from app.api.v1.reports import _TZ_OFFSETS

    h = _portal()
    blok = h[h.index('id="p_tz"'):h.index("</select>", h.index('id="p_tz"'))]
    tanlovlar = re.findall(r'<option value="([^"]+)"', blok)
    assert len(tanlovlar) >= 2, tanlovlar
    noma = sorted(set(tanlovlar) - set(_TZ_OFFSETS))
    assert noma == [], (
        "shakl SERVER qabul qilmaydigan mintaqa taklif qiladi: %s" % noma)
    assert "Asia/Bishkek" in tanlovlar and "Asia/Tashkent" in tanlovlar

    #  Teskari yo'nalish: yaroqsiz mintaqa 400 (jim `Asia/Tashkent` EMAS).
    r, _ = _ochish(client, timezone="Asia/Bishkeck")
    assert r.status_code == 400, r.text


def test_P0C_4_VALYUTA_erkin_matn_EMAS_va_SERVER_qollaydigan_qiymatlar():
    """Valyuta `<select>` va FAQAT yorliq jadvalida bor kodlar."""
    h = _portal()
    assert '<select id="p_cur">' in h, "valyuta HAMON erkin matn maydoni"
    blok = h[h.index('id="p_cur"'):h.index("</select>", h.index('id="p_cur"'))]
    kodlar = set(re.findall(r'<option value="([^"]+)"', blok))
    assert kodlar == {"UZS", "KGS"}, (
        "valyuta tanlovlari mijoz yorliq jadvali (`receipt/format.ts` "
        "`BY_CURRENCY`) bilan mos emas: %s" % sorted(kodlar))


def test_P0C_5_DUBLIKAT_kod_va_telefon_409(client):
    """Ikkala dublikat ham 409 (shakl `e.message` ni ko'rsatadi)."""
    r1, t1 = _ochish(client)
    assert r1.status_code == 200, r1.text

    r2, _ = _ochish(client, company_code=t1["company_code"])
    assert r2.status_code == 409, r2.text
    assert "kodi band" in r2.text

    r3, _ = _ochish(client, owner_phone=t1["owner_phone"])
    assert r3.status_code == 409, r3.text


def test_P0C_6_QIRGIZISTON_MIJOZI_TOLIQ_sintetik_onboarding(client):
    """Konsol -> do'kon -> tarif -> ega kirishi -> POS PIN — bir yo'lda."""
    r, tana = _ochish(client, company_name="Bishkek Market",
                      branch_name="Chuy filiali", timezone="Asia/Bishkek",
                      currency="KGS", plan="business", owner_pin="4321")
    assert r.status_code == 200, r.text
    cid = r.json()["company_id"]

    #  (1) EGA kiradi va valyutani KO'RADI (klient yorlig'i shundan keladi).
    lr = _kirish(client, tana["owner_phone"])
    assert lr.status_code == 200, lr.text
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}
    me = client.get("/api/v1/auth/me", headers=H)
    assert me.status_code == 200, me.text
    assert me.json().get("company_currency") == "KGS", me.json()

    #  (2) EGA PIN BILAN KIRMAYDI — va bu ATAYLAB (`_pin_login_allowed`:
    #      `ega`/`administrator` PIN yo'lidan o'tmaydi, `FULL_ACCESS_ROLES`).
    #      Shu bois provisioning shaklidagi «PIN» maydoni OLIB TASHLANDI:
    #      server uni `employees.pin_hash` ga YOZARDI, lekin u HECH QACHON
    #      ishlamasdi — operator egaga «kassa PIN'i» berdi deb o'ylardi.
    rp = client.post("/api/v1/auth/login",
                     json={"employee_id": me.json()["id"], "pin": "4321"})
    assert rp.status_code == 401, (
        "ega PIN bilan KIRDI — `_pin_login_allowed` to'siqi buzilgan: %s"
        % rp.text[:160])
    #      Shakl endi bu maydonni TAKLIF QILMAYDI va sababni aytadi.
    h = _portal_izohsiz()
    assert 'id="p_pin"' not in h, (
        "shakl HAMON ega PIN'ini so'raydi — u amalda ishlamaydi")
    assert "Kassir PIN" in h, "shakl kassir PIN'i qayerda berilishini aytmaydi"

    #  (3) Konsol detali tarif va filialni ko'rsatadi.
    d = client.get("/api/v1/admin/companies/%s" % cid, headers=VK)
    assert d.status_code == 200, d.text
    assert d.json()["plan"] == "business", d.json()["plan"]
    assert d.json()["currency"] == "KGS"


# ══════════════════════════════════════════════════════════════════════════
#  P0-D — KREDENSIAL BILAN XAVFSIZ ISHLASH
# ══════════════════════════════════════════════════════════════════════════

def test_P0D_1_PAROL_BANNERGA_va_ALERTGA_yozilmaydi():
    """Parol DOM da turmaydi va `alert()` ga tushmaydi."""
    h = _portal_izohsiz()
    #  (a) Provisioning banneri parolni CHOP ETMAYDI.
    assert "esc(body.owner_password)" not in h, (
        "parol HAMON bannerga yoziladi (DOM da modal yopilguncha qoladi)")
    #  (b) Tiklash `alert` ida ham yo'q.
    assert "Yangi parol: '+np" not in h, (
        "`alert()` HAMON yangi parolni ko'rsatadi")
    #  (c) O'rniga BIR MARTALIK topshirish paneli bor.
    for nav in ("function credSet(", "function credClear(", "function credPanel(",
                "function credReveal(", "async function credCopy("):
        assert nav in h, "bir martalik topshirish paneli to'liq emas: %s" % nav
    #  (d) Doimiy mijoz holatiga YOZILMAYDI.
    assert "sessionStorage.setItem('cred" not in h
    assert "localStorage" not in h, (
        "konsol `localStorage` ishlatadi — kredensial sirpanib tushishi mumkin")
    #  (e) `logout` kredensialni tozalaydi.
    assert re.search(r"function logout\(\)\{[^}]*credClear\(\)", h, re.S), (
        "`logout()` kredensialni tozalamaydi")


def test_P0D_2_JAVOB_va_AUDIT_parol_SAQLAMAYDI(client):
    """`POST /companies` javobida va audit qatorida parol YO'Q."""
    r, tana = _ochish(client)
    assert r.status_code == 200, r.text
    assert PAROL not in r.text, "javobda parol qaytdi: %s" % r.text[:200]

    from app.models.sync import AuditLog
    db = _db()
    try:
        qatorlar = db.query(AuditLog).filter(AuditLog.actor_id.is_(None)).all()
        assert qatorlar, "audit qatori yozilmadi — proba kuchsiz"
        for q in qatorlar:
            matn = "%r %r" % (q.before, q.after)
            assert PAROL not in matn, "AUDITDA parol: %s" % matn[:200]
            assert "password" not in matn or "password_reset" in matn, matn[:200]
    finally:
        db.close()

    #  Tiklash yo'li ham: javobda yangi parol YO'Q.
    yangi = "Boshqa-Parol-2026-xyz"
    rr = client.post("/api/v1/admin/reset-password", headers=VK,
                     json={"company_code": tana["company_code"], "new_password": yangi})
    assert rr.status_code == 200, rr.text
    assert yangi not in rr.text, rr.text[:200]

    #  ⚠️  AUDIT SKANI TIKLASHDAN KEYIN ham TAKRORLANADI (mustaqil ko‘rik
    #      topdi): ilgari skan `reset-password` dan OLDIN bajarilardi, ya’ni
    #      `audit_log(..., after={"password_reset": True})` qatori UMUMAN
    #      tekshirilmasdi va u yerga parol qo‘shilsa test JIM yashil qolardi.
    db = _db()
    try:
        qatorlar = db.query(AuditLog).filter(AuditLog.actor_id.is_(None)).all()
        assert qatorlar
        for q in qatorlar:
            matn = "%r %r" % (q.before, q.after)
            assert yangi not in matn, "TIKLASH auditida YANGI parol: %s" % matn[:200]
            assert PAROL not in matn, "TIKLASH auditida ESKI parol: %s" % matn[:200]
    finally:
        db.close()


def test_P0D_3_TIKLASH_eski_tokenni_BEKOR_qiladi(client):
    """Parol tiklangach eski sessiya ishlamaydi (`sec_epoch`)."""
    r, tana = _ochish(client)
    assert r.status_code == 200
    lr = _kirish(client, tana["owner_phone"])
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}
    assert client.get("/api/v1/auth/me", headers=H).status_code == 200

    yangi = "Yangi-Parol-2026-abc"
    assert client.post("/api/v1/admin/reset-password", headers=VK, json={
        "company_code": tana["company_code"], "new_password": yangi}
    ).status_code == 200
    assert client.get("/api/v1/auth/me", headers=H).status_code == 401, (
        "parol tiklangach eski token HAMON ishlaydi")
    assert _kirish(client, tana["owner_phone"], yangi).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
#  P0-E — OPERATOR AUDITI (vendor sirti, ijarachi izolyatsiyasi)
# ══════════════════════════════════════════════════════════════════════════

def test_P0E_1_KONSOL_AUDITI_amallarni_KORSATADI(client):
    """Yaratish, tarif, to'xtatish, o'chirish — hammasi jurnalda."""
    r, tana = _ochish(client)
    cid = r.json()["company_id"]
    assert client.patch("/api/v1/admin/companies/%s/plan" % cid, headers=VK,
                        json={"plan": "business"}).status_code == 200
    assert client.patch("/api/v1/admin/companies/%s/suspend" % cid, headers=VK,
                        json={"suspended": True}).status_code == 200

    a = client.get("/api/v1/admin/audit?company_id=%s" % cid, headers=VK)
    assert a.status_code == 200, a.text
    d = a.json()
    assert d["attribution"] == "shared-key", d["attribution"]
    amallar = {(e["action"], e["entity"]) for e in d["entries"]}
    assert ("create", "company") in amallar, amallar
    assert ("update", "company") in amallar, amallar
    #  Do'kon kodi operator uchun O'QILADIGAN qiymatga aylantirilgan.
    assert any(e["company_code"] == tana["company_code"] for e in d["entries"]), d
    #  ATRIBUTSIYA DA'VOSI: ism EMAS, konsol.
    assert {e["actor"] for e in d["entries"]} == {"vendor-console"}


def test_P0E_2_MIJOZ_AUDITI_vendor_qatorlarini_KORSATMAYDI(client):
    """`GET /api/v1/audit` INNER JOIN’i TEGILMADI — aktorsiz qator chiqmaydi.

    ⚠️  BU TEST QAYTA YOZILDI (mustaqil ko‘rik topdi). Oldingi varianti
        nuqsonni UMUMAN ushlamasdi: unda `for ... pass` bo‘sh sikli bor edi,
        asosiy tasdiq esa `tana_matn` da `"vendor-console"` satrini qidirardi
        — ammo bu satrni FAQAT vendor endpointi yozadi, mijoz endpointi esa
        uni hech qachon chiqarmaydi. Ya’ni INNER JOIN LEFT JOIN ga
        aylantirilsa ham test YASHIL qolardi (mutatsiya bilan o‘lchandi).

        Endi o‘lchov TO‘G‘RIDAN-TO‘G‘RI: bazadagi AKTORSIZ qatorlarning
        `id` lari olinadi va mijoz javobida ULARDAN BIRORTASI ham
        chiqmasligi tekshiriladi, ustiga POZITIV NAZORAT — mijozning O‘Z
        (aktorli) qatori javobda BOR.
    """
    from app.models.sync import AuditLog

    r, tana = _ochish(client)
    cid = uuid.UUID(r.json()["company_id"])
    lr = _kirish(client, tana["owner_phone"])
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}

    #  (1) Mijozning O‘Z (AKTORLI) audit qatori bo‘lsin — POZITIV NAZORAT.
    #      `PUT /settings` `audit_log(db, emp.id, "update", "setting", ...)` yozadi
    #      (`api/v1/settings.py:199`), ya’ni aktor AYNAN shu xodim.
    pr = client.put("/api/v1/settings", headers=H,
                    json={"key": "features", "value": {"p0e2_sinov": True}})
    assert pr.status_code in (200, 201), pr.text

    #  (2) BAZADAN: shu do‘kon bilan bog‘liq AKTORSIZ (vendor) qator id’lari.
    db = _db()
    try:
        aktorsiz = [q.id for q in db.query(AuditLog).filter(
            AuditLog.actor_id.is_(None), AuditLog.entity_id == cid).all()]
        aktorli = [q.id for q in db.query(AuditLog).filter(
            AuditLog.actor_id.isnot(None), AuditLog.entity == "setting").all()]
    finally:
        db.close()
    assert aktorsiz, "vendor qatori yozilmadi — proba kuchsiz"
    assert aktorli, "mijoz qatori yozilmadi — pozitiv nazorat kuchsiz"

    #  (3) MIJOZ javobi.
    m = client.get("/api/v1/audit?limit=300", headers=H)
    assert m.status_code == 200, m.text
    javob = m.json()
    qatorlar = javob["items"] if isinstance(javob, dict) and "items" in javob else javob
    assert isinstance(qatorlar, list), javob

    #  POZITIV NAZORAT: mijozning o‘z qatori KO‘RINADI (aks holda quyidagi
    #  salbiy tasdiq vakuumda ham yashil bo‘lardi).
    assert qatorlar, "mijoz jurnali BO‘SH — salbiy tasdiq hech narsa o‘lchamaydi"

    #  ASOSIY DARVOZA: aktorsiz qatorlarning `id` lari javobda BO‘LMASIN.
    #  `id` ishlatiladi, chunki u javobda bo‘lsa ham, bo‘lmasa ham
    #  quyidagi matn qidiruvi uni butun javob bo‘ylab ko‘radi.
    import json as _j
    matn = _j.dumps(javob, ensure_ascii=False, default=str)
    for aid in aktorsiz:
        assert ('"id": %d' % aid) not in matn and ('"id":%d' % aid) not in matn, (
            "mijoz jurnali AKTORSIZ (vendor) qatorni ko‘rsatdi: id=%s — "
            "ijarachilar aro sizish" % aid)
    #  Vendor amallarining ENTITY nomlari ham chiqmasin.
    assert "vendor_session" not in matn, matn[:300]
    assert "vendor-console" not in matn, matn[:300]
    #  Vendor «do‘kon yaratildi» qatorining imzosi (`company_code`) ham yo‘q.
    assert tana["company_code"] not in matn or "create" not in matn, matn[:300]


def test_P0E_3_MIJOZ_KATALOG_reseti_VENDOR_jurnaliga_tushmaydi(client):
    """`actor_id IS NULL` YOLG'IZ yetarli emasligi O'LCHANADI."""
    from app.api.v1 import admin as A
    from app.models.sync import AuditLog
    from app.services.audit import log as audit_log

    r, _ = _ochish(client)
    cid = uuid.UUID(r.json()["company_id"])
    #  `api/v1/catalog_v2.py` AYNI shakl bilan yozadi (aktorsiz, `catalog`).
    db = _db()
    try:
        audit_log(db, None, "reset", "catalog", cid, after={"deleted": 7})
        db.commit()
        assert db.query(AuditLog).filter(
            AuditLog.entity == "catalog", AuditLog.entity_id == cid).first()
    finally:
        db.close()

    a = client.get("/api/v1/admin/audit?company_id=%s" % cid, headers=VK)
    assert a.status_code == 200
    turlar = {e["entity"] for e in a.json()["entries"]}
    assert "catalog" not in turlar, (
        "mijozning katalog reseti VENDOR amali deb ko'rsatildi: %s" % turlar)
    assert "catalog" not in set(A._VENDOR_AUDIT_ENTITIES)


def test_P0E_4_ATRIBUTSIYA_CHEKLOVI_HUJJATLASHTIRILGAN():
    """«Bitta umumiy kalit» cheklovi KODDA aniq yozilgan bo'lsin."""
    src = io.open(ADMIN_PY, encoding="utf-8").read()
    i = src.index('@router.get("/audit")')
    blok = src[i:i + 2500]
    for nav in ("umumiy", "PlatformAdmin", "SIMLANMAGAN"):
        assert nav in blok, (
            "audit endpointi atributsiya cheklovini aytmaydi (`%s` yo'q)" % nav)


# ══════════════════════════════════════════════════════════════════════════
#  P0-F — O'CHIRISH XAVFSIZLIGI (ajratish, tasdiq, TIKLASH)
# ══════════════════════════════════════════════════════════════════════════

def test_P0F_1_SHAKLDA_amallar_AJRATILGAN_va_TERIB_tasdiqlanadi():
    """Suspend / Restore / Soft-delete vizual AJRATILGAN."""
    h = _portal_izohsiz()
    #  (a) O'chirish ALOHIDA «xavf zonasi»da.
    assert "Xavf zonasi" in h, "o'chirish tugmasi hamon kundalik amallar yonida"
    #  (b) Tugma AYNIQ «yumshoq» deyadi.
    assert "Yumshoq o" in h and "btnDelete" in h
    #  (c) TERIB tasdiqlash: ikki `confirm()` naqshi olib tashlangan.
    assert "Aniqmisiz?" not in h, "ikki ketma-ket confirm() naqshi qoldi"
    assert "deleteCompany(id,code)" in h, "o'chirish kodni tekshirmaydi"
    assert "KODINI kiriting" in h
    #  (d) To'xtatish/qayta yoqish matni AMALNI aytadi.
    assert "kirishni yopish" in h and "kirishni ochish" in h
    #  (e) Tiklash sirti bor.
    assert "function restoreCompany(" in h and "loadDeleted(" in h
    #  (f) EGA O‘ZI YOPGAN do‘konga TIKLASH tugmasi BERILMAYDI (P1 darvozasi).
    #      ⚠️  CHEKLOV, OCHIQ AYTILADI VA MUTATSIYA BILAN O‘LCHANGAN: bu
    #          MATN gardi bayroq ISHLATILGANINI isbotlaydi, SHOX XULQINI
    #          ISBOTLAY OLMAYDI. `${c.closed_by_owner` → `${false && c.closed_by_owner`
    #          mutatsiyasi shu tasdiqdan O‘TIB KETADI (o‘lchandi: M11 yashil),
    #          chunki satr baribir faylda qoladi. Xulqning HAQIQIY darvozasi —
    #          brauzer E2E si: `e2e/vendor-portal.spec.ts` da yopilgan do‘kon
    #          qatorida TUGMA YO‘Qligi DOM dan o‘lchanadi.
    #  ⚠️  Qatorlarni QURADIGAN JS bo‘lagi olinadi, qobiqdagi
    #      `<tbody id="delRows">` markupi EMAS (birinchi urinish aynan
    #      shunga tushib, bo‘sh bo‘lakni tekshirgan edi).
    i = h.index("$('delRows').innerHTML=")
    blok = h[i:h.index("</tr>`).join", i)]
    assert "c.closed_by_owner" in blok, (
        "o‘chirilganlar ro‘yxati `closed_by_owner` ni TEKSHIRMAYDI — egasi "
        "yopgan do‘konga TIKLASH tugmasi beriladi va u 409 bilan qaytadi")
    assert "egasi yopgan" in blok, "operator sababni KO‘RMAYDI"
    #      Tugma AYNAN `closed_by_owner` FALSE shoxida bo‘lsin.
    assert blok.index("c.closed_by_owner") < blok.index("restoreCompany("), blok[:300]


def test_P0F_2_OCHIRISH_TIKLASH_TOLIQ_sikli_va_BIZNES_TARIXI(client):
    """O'chirish -> ro'yxatdan chiqadi -> tiklash -> kirish qaytadi."""
    from app.models.org import Company

    r, tana = _ochish(client)
    cid = r.json()["company_id"]
    assert _kirish(client, tana["owner_phone"]).status_code == 200

    #  (1) O'CHIRISH.
    assert client.delete("/api/v1/admin/companies/%s" % cid,
                         headers=VK).status_code == 200
    tirik = client.get("/api/v1/admin/companies", headers=VK).json()["companies"]
    assert all(c["id"] != cid for c in tirik), "o'chirilgan do'kon ro'yxatda qoldi"
    #  Kirish YOPILDI.
    assert _kirish(client, tana["owner_phone"]).status_code == 401

    #  (2) «O'CHIRILGANLAR» ro'yxatida KO'RINADI (yagona tiklash sirti).
    och = client.get("/api/v1/admin/deleted-companies", headers=VK)
    assert och.status_code == 200, och.text
    qator = next((c for c in och.json()["companies"] if c["id"] == cid), None)
    assert qator is not None, "o'chirilgan do'kon hech qayerda ko'rinmaydi"
    assert qator["code_taken"] is False
    assert qator["deleted_at"]

    #  (3) TIKLASH.
    t = client.post("/api/v1/admin/companies/%s/restore" % cid, headers=VK)
    assert t.status_code == 200, t.text
    assert t.json()["restored"] is True
    assert _kirish(client, tana["owner_phone"]).status_code == 200, (
        "tiklangach kirish ochilmadi")

    #  (4) BIZNES MA'LUMOTI TEGILMAGAN — qator o'chirilmagan edi.
    db = _db()
    try:
        c = db.get(Company, uuid.UUID(cid))
        assert c is not None and c.deleted_at is None
        assert c.code == tana["company_code"]
    finally:
        db.close()

    #  (5) Audit ikki amalni ham yozdi.
    a = client.get("/api/v1/admin/audit?company_id=%s" % cid, headers=VK).json()
    assert any(e["action"] == "delete" for e in a["entries"]), a
    assert any((e["after"] or {}).get("restored") for e in a["entries"]), a


def test_P0F_3_TIKLASH_DARVOZALARI_409(client):
    """O'chirilmagan do'kon va KOD TO'QNASHUVI — ikkisi ham 409."""
    #  (a) Tirik do'konni «tiklash» — 409 (jim «ok» EMAS).
    r, tana = _ochish(client)
    cid = r.json()["company_id"]
    t = client.post("/api/v1/admin/companies/%s/restore" % cid, headers=VK)
    assert t.status_code == 409, t.text

    #  (b) KOD TO'QNASHUVI: o'chir -> ayni kod bilan yangi -> tiklash RAD.
    assert client.delete("/api/v1/admin/companies/%s" % cid,
                         headers=VK).status_code == 200
    r2, _ = _ochish(client, company_code=tana["company_code"])
    assert r2.status_code == 200, r2.text
    och = client.get("/api/v1/admin/deleted-companies", headers=VK).json()
    qator = next(c for c in och["companies"] if c["id"] == cid)
    assert qator["code_taken"] is True, (
        "shakl operatorni OLDINDAN ogohlantirmaydi")
    t2 = client.post("/api/v1/admin/companies/%s/restore" % cid, headers=VK)
    assert t2.status_code == 409, t2.text
    assert "kodi band" in t2.text


def test_P0F_4_JISMONIY_PURGE_konsoldan_YETIB_BOLMAYDI(client):
    """To'liq o'chirish (purge) HOLD'da — HTTP sirti YO'Q."""
    from app.main import app

    yollar = {getattr(r, "path", "") for r in app.routes}
    #  Mount qilingan sub-app ichidagi yo'llarni ham yig'amiz.
    for r in app.routes:
        ich = getattr(getattr(r, "app", None), "routes", None)
        if ich:
            yollar |= {getattr(x, "path", "") for x in ich}
    shubha = [y for y in yollar if "purge" in y.lower()]
    assert shubha == [], "purge HTTP sirti paydo bo'lgan: %s" % shubha
    for u in ("/api/v1/admin/purge", "/api/v1/admin/companies/x/purge"):
        assert client.post(u, headers=VK).status_code in (404, 405), u


# ══════════════════════════════════════════════════════════════════════════
#  P0-G — OBUNA VA TIJORAT CHEGARALARI (holatni QULFLASH, yoqish EMAS)
# ══════════════════════════════════════════════════════════════════════════

def test_P0G_1_PROVISIONING_OBUNA_QATORI_yaratmaydi(client):
    """Konsol do'koni GRANDFATHERED qoladi — billing dvigateli YOQILMAYDI."""
    from app.models.subscription import Subscription
    from app.services.subscription.state import evaluate_subscription_access

    r, _ = _ochish(client)
    cid = uuid.UUID(r.json()["company_id"])
    db = _db()
    try:
        assert db.query(Subscription).filter(
            Subscription.company_id == cid).first() is None, (
            "provisioning OBUNA qatori yaratdi — bu tijorat qarori va "
            "ega tasdiqlamagan")
    finally:
        db.close()
    #  Yozuv yo'q -> boshqarilmaydi, yozuvga RUXSAT bor.
    acc = evaluate_subscription_access(None, datetime.now(timezone.utc))
    assert acc.managed is False and acc.writes_allowed is True
    assert acc.reason == "GRANDFATHERED", acc.reason


def test_P0G_2_TARIF_ENTITLEMENT_amalda_ISHLAYDI(client):
    """`Setting("plan")` — TIRIK nazorat: `start` 2-filialni 403 bilan to'sadi."""
    from app.api.v1.branches import PLAN_LIMITS, USER_LIMITS
    assert PLAN_LIMITS["start"] == 1 and PLAN_LIMITS["business"] == 999
    assert USER_LIMITS["start"] == 10

    r, tana = _ochish(client, plan="start")
    cid = r.json()["company_id"]
    lr = _kirish(client, tana["owner_phone"])
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}

    #  `start` -> 1 filial. Ikkinchisi 403 `tarif_limit`.
    r2 = client.post("/api/v1/branches", headers=H,
                     json={"name": "Ikkinchi", "code": "F02"})
    assert r2.status_code == 403, r2.text
    assert "tarif_limit" in r2.text, r2.text

    #  Konsol tarifni ko'taradi -> AYNI so'rov o'tadi (entitlement TIRIK).
    assert client.patch("/api/v1/admin/companies/%s/plan" % cid, headers=VK,
                        json={"plan": "business"}).status_code == 200
    r3 = client.post("/api/v1/branches", headers=H,
                     json={"name": "Ikkinchi", "code": "F02"})
    assert r3.status_code in (200, 201), r3.text


def test_P0G_3_SAVDOGAR_TARIFNI_OZI_KOTARA_OLMAYDI(client):
    """`plan` va `suspended` — FAQAT konsol yozadi.

    ⚠️  MARSHRUT TUZATILDI (mustaqil ko‘rik topdi). Oldingi varianti
        `PUT /api/v1/settings/{kalit}` ga so‘rov yuborardi — bunday marshrut
        YO‘Q, ya’ni 404/405 har doim kelardi va darvoza
        (`settings.py` dagi `plan`/`suspended` taqiqi) HECH QACHON
        ijro etilmasdi. Haqiqiy marshrut: `PUT /api/v1/settings`, tanada
        `{"key": ..., "value": ...}`.
    """
    r, tana = _ochish(client, plan="start")
    lr = _kirish(client, tana["owner_phone"])
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}

    #  POZITIV NAZORAT: marshrut HAQIQATAN mavjud va RUXSAT ETILGAN kalitni
    #  qabul qiladi (`_validate_value` yopiq ro‘yxat: tax/payments/security/
    #  features/store_info/receipt — noma’lum kalit 400 beradi).
    ok = client.put("/api/v1/settings", headers=H,
                    json={"key": "features", "value": {"p0g3_sinov": True}})
    assert ok.status_code in (200, 201), (
        "`PUT /api/v1/settings` ishlamadi — proba kuchsiz: %s %s"
        % (ok.status_code, ok.text[:160]))

    #  ASOSIY DARVOZA: `plan` va `suspended` RAD etiladi.
    for kalit, qiymat in (("plan", {"plan": "business"}), ("suspended", {"on": True})):
        rr = client.put("/api/v1/settings", headers=H,
                        json={"key": kalit, "value": qiymat})
        assert rr.status_code == 403, (
            "savdogar `%s` ni O‘ZI o‘zgartira oldi: %s %s"
            % (kalit, rr.status_code, rr.text[:160]))

    #  VA tarif HAQIQATAN o‘zgarmadi.
    d = client.get("/api/v1/admin/companies/%s" % r.json()["company_id"], headers=VK)
    assert d.status_code == 200 and d.json()["plan"] == "start", d.text[:200]


def test_P0G_4_TOLOV_HTTP_SIRTI_YOQ_qolda_hisob_kitob(client):
    """To'lov yozuvchisi SERVISDA bor, lekin MARSHRUT yo'q — ataylab.

    ⚠️  Bu test «billing ishlaydi» demaydi. Aksincha: birinchi kohort uchun
        hisob-kitob QO'LDA bo'ladi degan TAKLIFNI qulflaydi va dvigatel
        jim yoqilib qolmasin deb turadi. Narx, davr, trial va grace —
        EGA QARORI, bu yerda o'ylab TOPILMAYDI.
    """
    from app.services.subscription import payments
    assert hasattr(payments, "record_payment"), (
        "to'lov yozuvchisi yo'qoldi — hisobot shu faktga tayanadi")

    for u in ("/api/v1/subscription", "/api/v1/subscriptions",
              "/api/v1/admin/subscription", "/api/v1/admin/payments",
              "/api/v1/subscription/payments"):
        r = client.get(u, headers=VK)
        assert r.status_code in (401, 403, 404, 405), (u, r.status_code)
        assert r.status_code != 200, "to'lov/obuna sirti JIM yoqilgan: %s" % u


def test_P0F_5_EGA_OZI_YOPGAN_dokon_KONSOLDAN_TIKLANMAYDI(client):
    """P1 (mustaqil ko‘rik topdi): yopish TERMINAL — tiklash uni qaytarmasin.

    `Company.deleted_at` ni IKKI yo‘l yozadi:
      1. VENDOR yumshoq o‘chirishi — FAQAT `deleted_at`, xodimlarga tegmaydi;
      2. EGA O‘ZI yopishi (`POST /auth/store-closure`) — `deleted_at` VA
         `status = CLOSED`, ustiga rozilik bergan xodimlar
         ANONIMLASHTIRILADI va ega o‘z hisobini ham o‘chirgan bo‘lishi mumkin.

    `origin/main` ikkinchisini ATAYLAB terminal qilgan: `peers_present`
    darvozasining yozma asosi aynan «qaytarilmaydi» (`account_deletion.py`).
    Tiklash uni qaytarsa, KIRA OLADIGAN HECH KIM QOLMAGAN tirik ijarachi
    paydo bo‘lardi.
    """
    from app.models.enums import CompanyStatus
    from app.models.org import Company

    r, tana = _ochish(client)
    cid = r.json()["company_id"]
    lr = _kirish(client, tana["owner_phone"])
    H = {"Authorization": "Bearer %s" % lr.json()["access_token"]}

    #  EGA O‘ZI yopadi (haqiqiy HTTP yo‘l, soxta ustun yozish EMAS).
    from app.services.account_deletion import CONFIRM_WORD
    rc = client.post("/api/v1/auth/store-closure", headers=H,
                     json={"password": PAROL, "confirm": CONFIRM_WORD,
                           "delete_my_account": True})
    assert rc.status_code == 200, rc.text

    #  Bazada IKKI ustun ham yozilgan — ajratish mezonining asosi.
    db = _db()
    try:
        c = db.get(Company, uuid.UUID(cid))
        assert c.deleted_at is not None
        assert (c.status or "") == CompanyStatus.CLOSED.value, c.status
    finally:
        db.close()

    #  RO‘YXAT operatorni OLDINDAN ogohlantiradi.
    och = client.get("/api/v1/admin/deleted-companies", headers=VK)
    assert och.status_code == 200, och.text
    qator = next(x for x in och.json()["companies"] if x["id"] == cid)
    assert qator["closed_by_owner"] is True, qator

    #  TIKLASH RAD ETILADI.
    t = client.post("/api/v1/admin/companies/%s/restore" % cid, headers=VK)
    assert t.status_code == 409, t.text
    assert "EGASI" in t.text, t.text[:240]

    #  VA do‘kon HAMON yopiq — jim tiriltirilmadi.
    db = _db()
    try:
        c = db.get(Company, uuid.UUID(cid))
        assert c.deleted_at is not None, "yopilgan do‘kon TIRILTIRILDI"
    finally:
        db.close()


def test_P0F_6_VENDOR_ochirgan_dokon_HAMON_TIKLANADI_ajratish_ISHLAYDI(client):
    """Ajratish mezoni YOLG‘ON POZITIV bermasin (pozitiv nazorat).

    Vendor yumshoq o‘chirishi `status` ga TEGMAYDI, ya’ni u tiklanadi.
    Bu testsiz `closed_by_owner` darvozasi HAMMASINI to‘sib qo‘ysa ham
    sezilmasdi.
    """
    from app.models.org import Company

    r, tana = _ochish(client)
    cid = r.json()["company_id"]
    assert client.delete("/api/v1/admin/companies/%s" % cid,
                         headers=VK).status_code == 200

    och = client.get("/api/v1/admin/deleted-companies", headers=VK).json()
    qator = next(x for x in och["companies"] if x["id"] == cid)
    assert qator["closed_by_owner"] is False, qator

    t = client.post("/api/v1/admin/companies/%s/restore" % cid, headers=VK)
    assert t.status_code == 200, t.text
    assert _kirish(client, tana["owner_phone"]).status_code == 200

    #  `status` TEGILMAGAN qoladi (vendor yo‘li uni hech qachon yozmagan).
    db = _db()
    try:
        c = db.get(Company, uuid.UUID(cid))
        assert c.deleted_at is None
        assert (c.status or "") != "CLOSED", c.status
    finally:
        db.close()


def test_P0E_5_AUDIT_javobi_QAYTGAN_sonini_va_AMALDAGI_chegarani_AYIRADI(client):
    """`returned` ≠ `limit_applied` — «natija kesildimi?» savoliga javob bor.

    ⚠️  Ilgari javobda `"limit": len(rows)` bor edi: nomi «so‘ralgan
        chegara» deb o‘qilardi, qiymati esa DOIM qaytgan qatorlar soni edi.
    """
    r, _ = _ochish(client)
    cid = r.json()["company_id"]
    a = client.get("/api/v1/admin/audit?limit=1&company_id=%s" % cid, headers=VK)
    assert a.status_code == 200, a.text
    d = a.json()
    assert "limit" not in d, "chalg‘ituvchi `limit` maydoni qoldi: %s" % d
    assert d["returned"] == len(d["entries"]) == 1, d
    assert d["limit_applied"] == 1, d
    #  Chegara YUQORIDAN qisiladi (DoS gardi).
    b = client.get("/api/v1/admin/audit?limit=99999", headers=VK)
    assert b.status_code == 200, b.text
    assert b.json()["limit_applied"] == 200, b.json()["limit_applied"]
    #  Yaroqsiz `company_id` — 500 EMAS.
    c = client.get("/api/v1/admin/audit?company_id=bu-uuid-emas", headers=VK)
    assert c.status_code == 400, (c.status_code, c.text[:160])
