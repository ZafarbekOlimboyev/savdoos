# -*- coding: utf-8 -*-
"""CH-16 — TASHQI AI GA UZATISH: ROZILIK DARVOZASI VA RASM TOZALASH.

IKKI QOIDA (ikkisi ham XULQNI o'lchaydi):

  1. ROZILIKSIZ TASHQI SO'ROV YO'Q. Provayder sozlangan bo'lsa-yu, do'kon AYNAN
     shu provayderga rozilik bermagan bo'lsa — `POST /receiving/scan` 403 beradi
     va provayder funksiyasi UMUMAN chaqirilmaydi. Buni «403 qaytdi» deb emas,
     MOCK provayder chaqiruvlarini SANAB tekshiramiz: oraliq kodda xato bo'lsa
     rasm chiqib ketgan, lekin javob baribir 403 bo'lishi mumkin edi.

  2. TOZALANMAGAN RASM UZATILMAYDI. Mock provayder olgan baytlarda EXIF/GPS
     markeri BO'LMASLIGI shart va `media_type` BAYTLARDAN aniqlangan bo'lishi
     kerak — mijoz e'lon qilgan qiymatdan emas.

⚠️  MIJOZ BAYROG'I ROZILIK EMAS. `test_MIJOZ_BAYROGI_rozilik_BERMAYDI` so'rovga
    `consent: true` qo'shadi va baribir 403 kutadi: rozilik dalili SERVERDAGI
    `Setting(key="ai_consent")` yozuvi, mijoz yuborgan maydon emas.

⚠️  DEMO REJIM ROZILIK TALAB QILMAYDI. Canonical demo yoqilganda `read_invoice` namunaviy
    qatorlarni qaytaradi va TASHQARIGA HECH NARSA CHIQMAYDI — darvoza o'sha yerda
    hech qanday maxfiylik foydasi bermasdan oqimni to'sardi.

HECH QANDAY HAQIQIY TARMOQ CHAQIRUVI YO'Q: `_read_gemini`/`_read_claude`
monkeypatch bilan almashtiriladi, rasmlar esa qo'lda yasalgan sintetik baytlar
(PIL ham, tashqi fayl ham kerak emas).
"""
from __future__ import annotations

import base64
import struct
import uuid
import zlib

import pytest

from tests.test_mobile_parity import _product, _shop

GPS = b"CH16-GPS-41.2995N-69.2401E"
QURILMA = b"CH16-QURILMA-SERIYA-ABC123"


def _jpeg(w=800, h=600, *, exif=True):
    o = bytearray(b"\xff\xd8")
    o += b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    if exif:
        p = b"Exif\x00\x00" + GPS + b"|" + QURILMA
        o += b"\xff\xe1" + struct.pack(">H", len(p) + 2) + p
    o += b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes(64)
    sof = b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00"
    o += b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof
    sos = b"\x01\x01\x00\x00\x3f\x00"
    o += b"\xff\xda" + struct.pack(">H", len(sos) + 2) + sos + b"\x12\x34" + b"\xff\xd9"
    return bytes(o)


def _png(w=800, h=600, *, meta=True):
    def ch(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    o = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if meta:
        o += ch(b"eXIf", GPS) + ch(b"tEXt", b"Comment\x00" + QURILMA)
    return o + ch(b"IDAT", zlib.compress(b"\x00" * 16)) + ch(b"IEND", b"")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _target(key="synthetic"):
    from app.services.ai_requirement import Requirement, DISCLOSURE_ID, DISPATCH_ID
    return Requirement(1, 'active', 'gemini', 'synthetic-model', 1,
                       DISCLOSURE_ID, 2, DISPATCH_ID, key)


@pytest.fixture()
def ai(monkeypatch, client):
    """MOCK provayder + sozlamalarni IZOLYATSIYA qilish.

    `monkeypatch` test oxirida `settings` ni o'z holiga qaytaradi — aks holda
    bitta test boshqa testlarga AI kalitini «yuqtirardi»."""
    from app.core.config import settings
    from app.services import receiving_ai as RA

    yuborilgan: list[dict] = []

    def _mock(image_b64, media_type, prompt, target):
        yuborilgan.append({"b64": image_b64, "media_type": media_type, "prompt": prompt})
        return [{"name": "Shakar", "qty": 2, "unit": "kg", "price": 1000}]

    monkeypatch.setattr(RA, "_read_gemini", _mock)
    monkeypatch.setattr(RA, "_read_claude", _mock)
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)

    # Explicit canonical test policy. Credentials never implicitly activate AI.
    from app.db.session import SessionLocal
    from app.models.ai_requirement import AiRequirement
    from app.services import ai_requirement as AR

    def policy(provider=None):
        with SessionLocal() as db:
            row = db.get(AiRequirement, 1)
            if row is None:
                row = AiRequirement(id=1, revision=1, mode='paused', provider=None, model=None,
                    disclosure_version=1, disclosure_id=AR.DISCLOSURE_ID, protocol_version=2,
                    dispatch_id=AR.DISPATCH_ID, activated_by='synthetic-test')
                db.add(row); db.flush()
            AR.activate(db, expected_revision=row.revision,
                mode='active' if provider else 'demo', provider=provider,
                model='synthetic-model' if provider else None, actor='synthetic-test')
            db.commit()

    policy()

    class _Boshqaruv:
        sent = yuborilgan

        @staticmethod
        def gemini():
            monkeypatch.setattr(settings, "gemini_api_key", "sinov-kaliti", raising=False)
            monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
            policy("gemini")

        @staticmethod
        def anthropic():
            monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
            monkeypatch.setattr(settings, "anthropic_api_key", "sinov-kaliti", raising=False)
            policy("anthropic")

    return _Boshqaruv()


def _scan(client, h, raw=None, *, media="image/jpeg", b64=None):
    st = client.get("/api/v1/receiving/ai-consent", headers=h).json()
    return client.post("/api/v1/receiving/scan", headers=h, json={
        "revision": st.get("revision", 1),
        "image_b64": b64 if b64 is not None else _b64(raw if raw is not None else _jpeg()),
        "media_type": media})


def _grant(client, h, version=1):
    st = client.get("/api/v1/receiving/ai-consent", headers=h).json()
    return client.post("/api/v1/receiving/ai-consent", headers=h,
                       json={**st, "disclosure_version": version})


# ══ QOIDA 1 — ROZILIKSIZ TASHQI SO'ROV YO'Q ═════════════════════════════════

def test_ROZILIK_YOQ_tashqi_SOROV_YUBORILMAYDI(client, ai):
    d = _shop()
    ai.gemini()

    r = _scan(client, d["H"])

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert r.headers.get("X-Error-Code") == "AI_CONSENT_REQUIRED", dict(r.headers)
    assert ai.sent == [], f"rozilik yo'q, lekin provayder CHAQIRILDI: {len(ai.sent)}"


def test_MIJOZ_BAYROGI_rozilik_BERMAYDI(client, ai):
    """⚠️  Mijoz yuborgan `consent: true` — rozilik DALILI EMAS."""
    d = _shop()
    ai.gemini()

    r = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()["revision"],
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg",
        "consent": True, "ai_consent": True, "granted": True})

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert ai.sent == []


def test_DEMO_rejimda_rozilik_TALAB_QILINMAYDI(client, ai):
    """Kalit sozlanmagan -> tashqaridan hech narsa so'ralmaydi -> darvoza o'tkazadi."""
    d = _shop()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    r = _scan(client, d["H"])

    assert st["required"] is False and st["provider"] is None, st
    assert r.status_code == 200, r.text[:200]
    assert r.json()["source"] == "demo", r.json()["source"]
    assert ai.sent == [], "demo rejimda provayder chaqirildi"


def test_ROZILIK_BERILGACH_skan_ISHLAYDI(client, ai):
    d = _shop()
    ai.gemini()
    assert _grant(client, d["H"]).status_code == 200

    r = _scan(client, d["H"])

    assert r.status_code == 200, r.text[:200]
    assert len(ai.sent) == 1, ai.sent
    assert r.json()["source"] == "ai"


def test_ROZILIK_QAYTARIB_OLINSA_yana_FAIL_CLOSED(client, ai):
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])
    assert _scan(client, d["H"]).status_code == 200
    oldin = len(ai.sent)

    assert client.delete("/api/v1/receiving/ai-consent", headers=d["H"]).status_code == 200
    r = _scan(client, d["H"])

    assert r.status_code == 403, r.text[:200]
    assert len(ai.sent) == oldin, "rozilik qaytarilgandan keyin ham uzatildi"


# ══ PROVAYDER ALMASHUVI ═════════════════════════════════════════════════════

def test_PROVAYDER_ALMASHSA_QAYTA_rozilik_SHART(client, ai):
    """⚠️  `read_invoice` da RUNTIME zaxira YO'Q — provayder KONFIGURATSIYA bilan
    almashadi. Rozilik ayni tanlovga bog'langani uchun almashuv uzatishni TO'XTATADI."""
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])
    assert _scan(client, d["H"]).status_code == 200
    oldin = len(ai.sent)

    ai.anthropic()                      # KONFIGURATSIYA o'zgardi
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    r = _scan(client, d["H"])

    assert st["granted"] is False, st
    assert st["provider"] == "anthropic" and st["previous_provider"] == "gemini", st
    assert "Anthropic" in (st["provider_name"] or ""), st
    assert r.status_code == 403, r.text[:200]
    assert len(ai.sent) == oldin, "yangi provayderga ROZILIKSIZ uzatildi"

    assert _grant(client, d["H"]).status_code == 200
    assert _scan(client, d["H"]).status_code == 200
    assert len(ai.sent) == oldin + 1


def test_OSHKOR_ETISH_VERSIYASI_mos_kelmasa_RAD(client, ai):
    """Eski mijoz eski matnni ko'rsatgan bo'lsa, u yangi matnga rozilik bermagan."""
    d = _shop()
    ai.gemini()

    r = _grant(client, d["H"], version=99)

    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert not client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()["granted"]


# ══ QOIDA 2 — FAQAT TOZALANGAN RASM UZATILADI ═══════════════════════════════

@pytest.mark.parametrize("nom, yasa", [("JPEG", _jpeg), ("PNG", _png)])
def test_EXIF_GPS_markeri_UZATILGAN_YUKDA_YOQ(client, ai, nom, yasa):
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])
    asl = yasa()

    r = _scan(client, d["H"], asl)

    assert r.status_code == 200, r.text[:200]
    assert len(ai.sent) == 1
    uzatilgan = base64.b64decode(ai.sent[0]["b64"])
    assert GPS not in uzatilgan, f"{nom}: GPS markeri provayderga KETDI"
    assert QURILMA not in uzatilgan, f"{nom}: qurilma markeri provayderga KETDI"
    assert uzatilgan != asl, f"{nom}: asl baytlar o'zgarmasdan uzatildi"


def test_MEDIA_TYPE_mijozdan_EMAS_BAYTLARDAN(client, ai):
    """Mobil `image_capture.dart:35` picker'ning `mimeType` ini o'zgartirmasdan
    uzatadi, desktop esa brauzerning `f.type` ini — ikkisi ham YOLG'ON bo'lishi mumkin."""
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])

    r = _scan(client, d["H"], _jpeg(), media="image/heic")   # E'LON: HEIC, BAYT: JPEG

    assert r.status_code == 200, r.text[:200]
    assert ai.sent[0]["media_type"] == "image/jpeg", ai.sent[0]["media_type"]


def test_METAMALUMOTSIZ_rasm_BUZILMAYDI(client, ai):
    """Jim buzilish bo'lmasin: tozalashga hojat yo'q rasm BAYT-AYNI qoladi."""
    from app.services import image_guard as IG

    toza = _jpeg(exif=False)
    natija, tur = IG.sanitize(toza)
    assert natija == toza, "metama'lumotsiz JPEG o'zgartirildi"
    assert tur == "image/jpeg"
    pn = _png(meta=False)
    assert IG.sanitize(pn)[0] == pn, "metama'lumotsiz PNG o'zgartirildi"


@pytest.mark.parametrize("nom, raw", [
    ("PDF", b"%PDF-1.7\n" + b"x" * 80),
    ("GIF", b"GIF89a" + b"x" * 80),
    ("WebP", b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 80),
    ("HEIC", b"\x00\x00\x00\x18ftypheic" + b"x" * 80),
    ("axlat", b"\x01\x02\x03\x04" + b"x" * 80),
    ("juda kichik", _jpeg(8, 8)),
    ("juda katta", _jpeg(9000, 9000)),
])
def test_YAROQSIZ_rasm_RAD_etiladi_va_UZATILMAYDI(client, ai, nom, raw):
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])

    r = _scan(client, d["H"], raw)

    assert r.status_code == 400, f"{nom}: {r.status_code} {r.text[:150]}"
    assert r.headers.get("X-Error-Code") == "AI_IMAGE_REJECTED", dict(r.headers)
    assert ai.sent == [], f"{nom}: rad etilgan rasm provayderga ketdi"


def test_BUZUQ_base64_RAD_etiladi(client, ai):
    d = _shop()
    ai.gemini()
    _grant(client, d["H"])

    r = _scan(client, d["H"], b64="!!! bu base64 emas !!!")

    assert r.status_code == 400, (r.status_code, r.text[:150])
    assert ai.sent == []


# ══ QO'LDA KIRIM ROZILIKSIZ HAM ISHLAYDI ════════════════════════════════════

def test_ROZILIK_RAD_ETILSA_QOLDA_KIRIM_ISHLAYDI(client, ai):
    """⚠️  ENG MUHIM BAND: maxfiylik darvozasi biznesni TO'XTATMAYDI."""
    d = _shop()
    p = _product(d, name="CH16 mahsulot", qty=0)
    ai.gemini()
    assert _scan(client, d["H"]).status_code == 403          # rozilik YO'Q

    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(p["id"]), "qty": 5, "unit_cost": 900, "unit": "dona"}],
        "payment": "cash", "source": "manual", "client_uuid": str(uuid.uuid4())})

    assert r.status_code == 200, r.text[:200]
    assert ai.sent == [], "qo'lda kirim tashqi AI ni chaqirdi"
    from app.models.inventory import Inventory
    from tests.test_mobile_parity import _db
    with _db() as db:
        inv = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(str(p["id"]))).first()
        assert float(inv.qty) == 5.0, inv.qty


# ══ XOM MA'LUMOT SAQLANMAYDI ════════════════════════════════════════════════

def test_SKAN_hech_narsa_SAQLAMAYDI(client, ai):
    """Skan — sof o'qish: `receivings` jadvaliga qator qo'shilmaydi."""
    from app.models.receiving import Receiving
    from tests.test_mobile_parity import _db

    d = _shop()
    ai.gemini()
    _grant(client, d["H"])
    with _db() as db:
        oldin = db.query(Receiving).filter(Receiving.company_id == d["cid"]).count()

    assert _scan(client, d["H"]).status_code == 200

    with _db() as db:
        assert db.query(Receiving).filter(
            Receiving.company_id == d["cid"]).count() == oldin, "skan qator yaratdi"


# ══ TENANT IZOLYATSIYASI VA AVTENTIFIKATSIYA ════════════════════════════════

def test_TENANT_izolyatsiyasi_rozilik_UMUMLASHMAYDI(client, ai):
    A, B = _shop(), _shop()
    ai.gemini()
    _grant(client, A["H"])

    stb = client.get("/api/v1/receiving/ai-consent", headers=B["H"]).json()
    rb = _scan(client, B["H"])

    assert stb["granted"] is False, stb
    assert rb.status_code == 403, rb.status_code
    assert ai.sent == [], "B do'koni A ning roziligi bilan uzatdi"
    assert _scan(client, A["H"]).status_code == 200          # A hamon ishlaydi


def test_AVTENTIFIKATSIYA_talab_qilinadi(client, ai):
    ai.gemini()
    assert _scan(client, {}).status_code in (401, 403)
    assert client.get("/api/v1/receiving/ai-consent").status_code in (401, 403)
    assert client.post("/api/v1/receiving/ai-consent",
                       json={"disclosure_version": 1}).status_code in (401, 403)
    assert client.delete("/api/v1/receiving/ai-consent").status_code in (401, 403)


def test_ROZILIK_UMUMIY_settings_orqali_SOXTALASHTIRILMAYDI(client, ai):
    """⚠️  `PUT /settings` ning `features`/`security` kalitlari IXTIYORIY maydon
    nomini qabul qiladi — shu bois rozilik ALOHIDA kalitda va `_validate_value`
    uni RAD etadi. Aks holda `sozlamalar.edit` huquqi rozilikni soxtalashtirardi."""
    d = _shop()
    ai.gemini()

    r = client.put("/api/v1/settings", headers=d["H"],
                   json={"key": "ai_consent",
                         "value": {"provider": "gemini", "disclosure_version": 1}})

    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert not client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()["granted"]
    assert _scan(client, d["H"]).status_code == 403
    assert ai.sent == []


def test_422_da_RASM_javobga_TUSHMAYDI(client, ai):
    """CH-15A redaksiyasi skan yo'lida HAM ishlaydi: `media_type` tur xatosi
    bersa, pydantic `input` ga BUTUN tanani qo'yardi — surat bilan birga."""
    d = _shop()
    ai.gemini()
    belgi = "CH16-RASM-BELGISI-" + uuid.uuid4().hex

    r = client.post("/api/v1/receiving/scan", headers=d["H"],
                    json={"image_b64": belgi, "media_type": ["ro'yxat", "satr emas"]})

    assert r.status_code == 422, (r.status_code, r.text[:200])
    assert belgi not in r.text, f"surat 422 javobida qaytdi: {r.text[:300]!r}"
    assert ai.sent == []


def test_GEMINI_kaliti_URL_da_EMAS_SARLAVHADA(monkeypatch):
    """⚠️  Kalit ilgari `params={"key": ...}` edi — so'rov URL'i httpx istisnosiga,
    proxy jurnaliga va xato-kuzatuvga TO'LIQ kalit bilan tushardi.

    MATN emas, XULQ o'lchanadi: `httpx.Client` ushlab olinadi va HAQIQIY so'rovning
    URL'i, query'si va sarlavhalari tekshiriladi. Manba matnini grep qilish
    o'z izohimizga ham tushib, sinovni yolg'on qizil qilardi."""
    import httpx

    from app.core.config import settings
    from app.services import receiving_ai as RA

    KALIT = "maxfiy-kalit-" + uuid.uuid4().hex
    tutilgan: dict = {}

    class _Javob:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @staticmethod
        def post(url, **kw):
            tutilgan["url"] = url
            tutilgan["params"] = kw.get("params")
            tutilgan["headers"] = kw.get("headers") or {}
            return _Javob()

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(settings, "gemini_api_key", KALIT, raising=False)

    RA._read_gemini("AAAA", "image/jpeg", "prompt", _target(KALIT))

    assert KALIT not in tutilgan["url"], "kalit URL'da"
    assert KALIT not in str(tutilgan["params"]), f"kalit query'da: {tutilgan['params']!r}"
    assert tutilgan["headers"].get("x-goog-api-key") == KALIT, tutilgan["headers"]


def test_PROVAYDER_XOM_JAVOBI_xato_matniga_TUSHMAYDI(client):
    """`source` qiymati `log.warning` bilan jurnalga yoziladi — unda provayderning
    javob TANASI (model chiqishi) bo'lmasligi SHART."""
    from app.services import receiving_ai as RA

    xom = "MODEL-XOM-JAVOBI-" + uuid.uuid4().hex

    def _yiqiladi(image_b64, media_type, prompt, target):
        raise RuntimeError(f"upstream dedi: {xom}")

    asl = RA._read_gemini
    try:
        RA._read_gemini = _yiqiladi
        from app.core.config import settings
        asl_kalit = settings.gemini_api_key
        settings.gemini_api_key = "sinov"
        try:
            rows, source = RA.read_invoice("AAAA", "image/jpeg", [], _target())
        finally:
            settings.gemini_api_key = asl_kalit
    finally:
        RA._read_gemini = asl

    assert rows == []
    assert source.startswith("error:"), source
    assert xom not in source, f"provayder xom javobi `source` ga tushdi: {source!r}"
    assert source == "error:RuntimeError", source


# ══ CH-17A — SKAN QILUVCHI va ROZILIK BERUVCHI BOSHQA HUQUQLAR ══════════════

def test_OMBORCHI_skan_qiladi_lekin_ROZILIK_BERA_OLMAYDI(client, ai):
    """⚠️  O'LCHANGAN HUQUQ FARQI. `omborchi` roli `xaridlar.edit` ga EGA (skan
    qiladi), lekin `sozlamalar.edit` ga EGA EMAS (`seed.py` ROLES) — ya'ni u
    rozilikni O'ZI yoza olmaydi.

    Bu ATAYLAB: kompaniya ma'lumotini tashqi qayta ishlovchiga berish do'kon
    darajasidagi qaror. Lekin UX shuni BILISHI kerak — mobil dialog
    `Perm.allows('sozlamalar.edit')` ni tekshiradi va ruxsati yo'q xodimga
    «ega/administrator ruxsat berishi kerak» deb aytadi, 403 beradigan tugma
    ko'rsatmaydi (`receiving_home_screen.dart`)."""
    from tests.test_mobile_parity import _staff

    d = _shop()
    ai.gemini()
    omborchi_h, _ = _staff(d, "omborchi")

    # HOLATNI o'qiy oladi (dialogni ko'rsatish uchun SHART)
    st = client.get("/api/v1/receiving/ai-consent", headers=omborchi_h)
    assert st.status_code == 200, (st.status_code, st.text[:200])
    assert st.json()["required"] is True and st.json()["granted"] is False

    # Lekin YOZA OLMAYDI
    g = client.post("/api/v1/receiving/ai-consent", headers=omborchi_h,
                    json={"disclosure_version": 1})
    assert g.status_code == 403, (g.status_code, g.text[:200])

    # Va roziliksiz skan — tashqi so'rov YO'Q
    r = _scan(client, omborchi_h)
    assert r.status_code == 403, r.status_code
    assert ai.sent == []

    # EGA rozilik bergach, OMBORCHI skan qila oladi (rozilik KOMPANIYA darajasida)
    assert _grant(client, d["H"]).status_code == 200
    r2 = _scan(client, omborchi_h)
    assert r2.status_code == 200, r2.text[:200]
    assert len(ai.sent) == 1


def test_RAD_ETISH_matnlari_TARJIMA_uchun_QAT_IY(client, ai):
    """⚠️  Mijoz tarjimoni (`errors.dart:_translateKnown`) REGEX BILMAYDI: u aynan
    mos kelishni va `"PREFIKS: qolgan"` bo'linishini biladi. Shu bois rad etish
    matnlari o'rin-belgisiz bo'lishi SHART — aks holda ru/ky foydalanuvchi
    o'zbekcha matn ko'rib qolardi."""
    from app.services import image_guard as IG

    d = _shop()
    ai.gemini()
    _grant(client, d["H"])

    # HEIC: format nomi PREFIKS, jumla QAT'IY
    r = _scan(client, d["H"], b"\x00\x00\x00\x18ftypheic" + b"x" * 80)
    matn = r.json()["detail"]
    assert r.status_code == 400, r.status_code
    assert ": " in matn, f"prefiks bo'linishi yo'q: {matn!r}"
    qolgan = matn.split(": ", 1)[1]
    assert qolgan == "bu rasm turi qo'llab-quvvatlanmaydi — JPEG yoki PNG rasm tanlang", qolgan

    # O'lcham matnlarida RAQAM YO'Q (tarjima mos kelishi uchun)
    for raw in (_jpeg(8, 8), _jpeg(9000, 9000)):
        rr = _scan(client, d["H"], raw)
        assert rr.status_code == 400
        assert not any(ch.isdigit() for ch in rr.json()["detail"]), rr.json()["detail"]

    # Barcha matnlar modulda QAT'IY satr sifatida topilishi kerak
    import inspect
    src = inspect.getsource(IG)
    assert 'f"{nom}: bu rasm turi' in src, "format prefiksi yo'q"
