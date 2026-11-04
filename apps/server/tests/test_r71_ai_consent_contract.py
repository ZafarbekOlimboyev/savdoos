# -*- coding: utf-8 -*-
"""R7.1 — AI ROZILIK SHARTNOMASI: SERVER ↔ FLUTTER IKKI TOMONLAMA QULF.

NEGA BU FAYL BOR. R7.0 auditi aniqladi: mobil klient (`AiConsent.fromJson`)
`revision` va `disclosure_id` ni MAJBURIY talab qiladi, server esa ularni
QAYTARMAYDI — ya'ni Build 67 da AI-skan har do'konda 100% ishlamaydi.
Uch qatlam test YASHIL edi va buni USHLAMADI:

  · server testlari ESKI shartnomani tasdiqlaydi (faqat `disclosure_version`);
  · mobil testlar YANGI shartnomani tasdiqlaydi, lekin javobni O'ZI yasaydi
    (`test/support/ai_contract.dart`) va BOSHQA branch serverini nomlaydi:
    `26332b0` -> `ci-proof/public-demo-cutover`, u 2026-11-04T16:31Z da
    PRODUCTION'ga chiqqan. Shartnoma xayoliy emas — SHU BRANCHDA yo'q;
  · haqiqiy-backend E2E bu yo'lga UMUMAN tegmaydi.

Har qatlam o'z ichida izchil, bir-biriga mos kelmaydi, hech biri CHEGARANI
kesmaydi. Shu bois bu fayl chegarani KESADI:

  1. HAQIQIY FastAPI serverdan (TestClient) oltita holat javobini OLADI;
  2. ularni `contracts/ai_consent.samples.json` ga yozilgan ETALON bilan
     solishtiradi -> SERVER siljisa QIZIL;
  3. AYNI faylni `apps/mobile/test/receiving_ai_backend_contract_test.dart`
     HAQIQIY `AiConsent.fromJson` ga beradi -> MIJOZ siljisa QIZIL.

Etalonni qayta yozish (server shartnomasi ATAYLAB o'zgarganda):
    BINOS_WRITE_AI_CONTRACT=1 python -m pytest tests/test_r71_ai_consent_contract.py -k ETALON
Yozilgan faylni DIFF bilan ko'rib chiqing: u mijoz uchun majburiy shartnoma.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

#  `ai` — MOCK provayder fikstura (test_ch16): hech qanday haqiqiy tarmoq
#  chaqiruvi yo'q, konfiguratsiya esa test oxirida tiklanadi.
from tests.test_ch16_ai_rozilik_va_rasm import ai  # noqa: F401
from tests.test_ch16_ai_rozilik_va_rasm import _b64, _jpeg
from tests.test_mobile_parity import _shop

#  Repo ildizi: .../apps/server/tests/<bu fayl> -> uch pog'ona yuqori.
ETALON = Path(__file__).resolve().parents[3] / "contracts" / "ai_consent.samples.json"

#  ⚠️  VAQTGA BOG'LIQ MAYDON. `granted_at` har yurishda boshqa — etalonda uning
#      QIYMATI emas, MAVJUDLIGI va TURI qulflanadi.
UCHQUR = "<vaqt>"


def _normal(body: dict) -> dict:
    """Etalonga yoziladigan shakl: uchqur qiymatlar niqoblanadi, qolgani AYNAN."""
    out = dict(body)
    if out.get("granted_at") is not None:
        out["granted_at"] = UCHQUR
    return out


def _yig(client, ai) -> list[dict]:
    """HAQIQIY server javoblari — oltita holat, AYNI tartibda."""
    from app.services import ai_consent as _AC

    d = _shop()
    H = d["H"]
    namunalar: list[dict] = []

    def _get(scenario: str, izoh: str):
        r = client.get("/api/v1/receiving/ai-consent", headers=H)
        namunalar.append({"scenario": scenario, "izoh": izoh, "method": "GET",
                          "path": "/api/v1/receiving/ai-consent",
                          "status": r.status_code, "body": _normal(r.json())})
        return r

    def _post(scenario: str, izoh: str, body: dict):
        r = client.post("/api/v1/receiving/ai-consent", headers=H, json=body)
        namunalar.append({"scenario": scenario, "izoh": izoh, "method": "POST",
                          "path": "/api/v1/receiving/ai-consent", "request": body,
                          "status": r.status_code, "body": _normal(r.json())})
        return r

    # 1. DEMO REJIM — provayder sozlanmagan, tashqi uzatish YO'Q.
    _get("demo", "Provayder sozlanmagan: rozilik talab qilinmaydi")

    # 2. GEMINI sozlangan, rozilik YO'Q — dialog KERAK.
    ai.gemini()
    _get("gemini_rozilik_yoq", "Provayder bor, rozilik yo'q: dialog kerak")

    # 3. Mobil Build 67 AYNAN yuboradigan tana bilan ROZILIK BERISH.
    holat = client.get("/api/v1/receiving/ai-consent", headers=H).json()
    _post("gemini_grant_echo", "Build 67 tanasi: kutilgan talab qaytariladi", {
        "revision": holat.get("revision"), "provider": holat.get("provider"),
        "disclosure_id": holat.get("disclosure_id"),
        "disclosure_version": holat.get("disclosure_version"),
    })

    # 4. Rozilik BERILGAN holat.
    _get("gemini_berilgan", "Rozilik yozilgan: uzatishga ruxsat")

    # 5. PROVAYDER O'ZGARDI — eski rozilik AVTOMATIK o'tmaydi.
    ai.anthropic()
    _get("provayder_ozgardi", "Konfiguratsiya o'zgardi: eski rozilik kuchsiz")

    # 6. ROZILIK QAYTARIB OLINDI.
    ai.gemini()
    r = client.delete("/api/v1/receiving/ai-consent", headers=H)
    namunalar.append({"scenario": "qaytarib_olindi", "izoh": "DELETE: fail-closed holatga qaytdi",
                      "method": "DELETE", "path": "/api/v1/receiving/ai-consent",
                      "status": r.status_code, "body": _normal(r.json())})

    #  Etalon serverning e'lon qilgan shartnomasini ham olib yuradi, shunda
    #  mijoz testi reviziyalarni TAXMIN QILMAYDI.
    return [{"shartnoma": {"disclosure_id": _AC.DISCLOSURE_ID,
                           "disclosure_version": _AC.DISCLOSURE_VERSION,
                           "revisions": {f"{p}|{v}": rev
                                         for (p, v), rev in sorted(
                                             _AC.REQUIREMENT_REVISIONS.items(),
                                             key=lambda kv: kv[1])}}}] + namunalar


# ══ 1. ETALON — SERVER SILJISA QIZIL ════════════════════════════════════════

def test_ETALON_haqiqiy_server_javobi_bilan_AYNAN_mos(client, ai):
    """`contracts/ai_consent.samples.json` — HAQIQIY server javobining qotirilgan
    nusxasi. Server shartnomasi o'zgarsa bu test QIZIL bo'ladi va mobil
    klientni ham yangilash KERAKLIGINI ko'rsatadi."""
    hozir = _yig(client, ai)

    if os.environ.get("BINOS_WRITE_AI_CONTRACT") == "1":
        ETALON.write_text(json.dumps(hozir, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        pytest.skip(f"etalon qayta yozildi: {ETALON} — diff bilan ko'rib chiqing")

    assert ETALON.exists(), (
        f"etalon yo'q: {ETALON}. BINOS_WRITE_AI_CONTRACT=1 bilan yozing.")
    kutilgan = json.loads(ETALON.read_text(encoding="utf-8"))
    assert hozir == kutilgan, (
        "SERVER SHARTNOMASI SILJIDI. Mobil klient shu fayldan parse qiladi — "
        "`apps/mobile/test/receiving_ai_backend_contract_test.dart` ni ham "
        "tekshiring.\n\nhozir:\n"
        + json.dumps(hozir, ensure_ascii=False, indent=2)[:3000])


# ══ 2. E'LON DARVOZASI — `api_capabilities` naqshi ══════════════════════════

def test_HAR_PROVAYDER_uchun_reviziya_ELON_QILINGAN():
    """Yangi provayder qo'shilib reviziyasi e'lon qilinmasa — bu test QIZIL.

    Aks holda nuqson RUNTIME'da (503) chiqardi: operator «AI ishlamaydi» deb
    ko'rardi, sabab esa kodda e'lon qilinmagan juftlik bo'lardi."""
    from app.services import ai_consent as _AC

    yoq = [p for p in list(_AC.PROVIDERS) + [None]
           if _AC.requirement_revision(p) is None]
    assert yoq == [], (
        f"reviziyasi e'lon qilinmagan provayder(lar): {yoq}. "
        f"`REQUIREMENT_REVISIONS` ga qo'shing (QO'SHIMCHA-ONLY).")


def test_REVIZIYALAR_QAYTA_ISHLATILMAYDI():
    """Ikki XIL talab AYNI reviziyani ulashsa, mijozning `sameRequirement`
    tekshiruvi provayder o'zgarishini SEZMAY qolardi — eski rozilik yangi talab
    deb qabul qilinardi. Shu bois reviziyalar NOYOB."""
    from app.services import ai_consent as _AC

    qiymatlar = list(_AC.REQUIREMENT_REVISIONS.values())
    assert len(set(qiymatlar)) == len(qiymatlar), _AC.REQUIREMENT_REVISIONS
    assert all(isinstance(v, int) and v >= 1 for v in qiymatlar), _AC.REQUIREMENT_REVISIONS


def test_DEMO_REJIM_reviziyasi_PROVAYDERLARDAN_FARQ_QILADI():
    """Demo (tashqi uzatish YO'Q) va haqiqiy provayder — BOSHQA-BOSHQA talab."""
    from app.services import ai_consent as _AC

    demo = _AC.requirement_revision(None)
    assert demo is not None
    assert all(_AC.requirement_revision(p) != demo for p in _AC.PROVIDERS)


# ══ 3. XULQ — REVIZIYA HAQIQATAN MAJBURLANADI ══════════════════════════════

def test_PROVAYDER_OZGARSA_reviziya_ham_rozilik_ham_OZGARADI(client, ai):
    """Invariant: provayder o'zgarsa oldingi rozilik AVTOMATIK yangi rozilik
    DEB HISOBLANMAYDI — va mijoz buni reviziyadan KO'RADI."""
    d = _shop()
    ai.gemini()
    a = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                json={"disclosure_version": 1})
    berilgan = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    assert berilgan["granted"] is True, berilgan

    ai.anthropic()
    b = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()

    assert b["revision"] != a["revision"], (a, b)
    assert b["granted"] is False, b
    assert b["previous_provider"] == "gemini", b


def test_ESKI_ROZILIK_YOZUVI_reviziyasiz_ham_OQILADI(client, ai):
    """O'rnatilgan production'da rozilik yozuvlari `revision`SIZ saqlangan.

    Ularni «noto'g'ri» deb hisoblash har do'konni qaytadan rozilik so'rashga
    majburlardi. Reviziya saqlangan (provayder, versiya) juftligidan AYNI
    deterministik funksiya bilan hisoblanadi — taxmin yo'q, qayta rozilik yo'q."""
    from app.models.settings import Setting
    from app.services import ai_consent as _AC

    from app.db.session import SessionLocal

    d = _shop()
    ai.gemini()
    db = SessionLocal()
    try:
        #  AYNAN eski shakl: `revision` ham, `disclosure_id` ham YO'Q.
        db.add(Setting(company_id=d["cid"], key=_AC.CONSENT_KEY,
                       value={"provider": "gemini", "model": "gemini-2.5-flash",
                              "disclosure_version": 1,
                              "granted_at": "2026-10-01T00:00:00+00:00",
                              "employee_id": str(d["eid"])}))
        db.commit()
    finally:
        db.close()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()

    assert st["granted"] is True, (
        ("eski yozuv RAD etildi — har do'kon qaytadan rozilik so'rashga "
         "majbur bo'lardi"), st)
    assert st["revision"] == _AC.requirement_revision("gemini")


def test_KUTILGAN_TALAB_mos_kelmasa_ROZILIK_YOZILMAYDI(client, ai):
    """Mijoz A talabini ko'rsatgan, server esa B da — rozilik YOZILMAYDI (409).

    Aks holda foydalanuvchi Gemini uchun «roziman» desa, yozuv Anthropic uchun
    tushardi va keyingi rasm u ko'rmagan kompaniyaga ketardi."""
    d = _shop()
    ai.gemini()
    gemini_rev = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()["revision"]

    ai.anthropic()                                  # konfiguratsiya SILJIDI
    r = client.post("/api/v1/receiving/ai-consent", headers=d["H"], json={
        "disclosure_version": 1, "revision": gemini_rev, "provider": "gemini",
        "disclosure_id": "binos.receiving.ai.v1"})

    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert r.headers.get("X-Error-Code") == "AI_REQUIREMENT_CHANGED", dict(r.headers)
    assert not client.get("/api/v1/receiving/ai-consent",
                          headers=d["H"]).json()["granted"]
    assert ai.sent == []


def test_ESKI_MIJOZ_kutilgan_talab_YUBORMAYDI_va_ISHLAYDI(client, ai):
    """O'rnatilgan desktop faqat `disclosure_version` yuboradi (`Purchases.tsx:1248`).

    Yangi maydonlar MAJBURIY bo'lsa, o'sha mijozlarda rozilik butunlay ishlamay
    qolardi — shu bois ular ixtiyoriy va bu test shuni qulflaydi."""
    d = _shop()
    ai.gemini()

    r = client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                    json={"disclosure_version": 1})

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["granted"] is True, r.json()
    #  Eski mijoz skanda ham reviziya yubormaydi — yo'l O'ZGARMAYDI.
    assert client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg"}).status_code == 200


def test_SKAN_reviziyasi_ESKIRGAN_bolsa_RASM_CHIQMAYDI(client, ai):
    """TOCTOU: operator Gemini ekranida turib yuboradi, konfiguratsiya esa
    Anthropic'ga o'tgan va unga ham rozilik bor. Rasm JIM ketmasligi kerak."""
    d = _shop()
    ai.gemini()
    eski_rev = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()["revision"]
    client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                json={"disclosure_version": 1})

    ai.anthropic()
    client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                json={"disclosure_version": 1})          # YANGI provayderga rozilik BOR
    oldin = len(ai.sent)

    r = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg", "revision": eski_rev})

    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert r.headers.get("X-Error-Code") == "AI_REQUIREMENT_CHANGED", dict(r.headers)
    assert len(ai.sent) == oldin, "ESKIRGAN talab bilan rasm UZATILDI"


def test_ELON_QILINMAGAN_provayder_FAIL_CLOSED(client, ai, monkeypatch):
    """Reviziyasi e'lon qilinmagan provayder sozlansa — hech narsa uzatilmaydi.

    `1` ni taxmin qilib qaytarish mijozga «eski rozilik amal qiladi» deb
    ko'rsatardi; shu bois fail-closed va qo'lda kirim yo'li ochiq qoladi."""
    from app.services import ai_consent as _AC

    d = _shop()
    ai.gemini()
    monkeypatch.setitem(_AC.PROVIDERS, "yangi-provayder", "Yangi (Sinov)")
    monkeypatch.setattr(_AC, "active_provider",
                        lambda: ("yangi-provayder", "yangi-model"))

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"])
    r = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg"})

    assert st.status_code == 503, (st.status_code, st.text[:200])
    assert r.status_code == 503, (r.status_code, r.text[:200])
    assert ai.sent == [], "e'lon qilinmagan provayderga rasm UZATILDI"


# ══ 4. PRODUCTION SHAKLIDAGI ROZILIK YOZUVI BILAN MOSLIK ═══════════════════

def test_PRODUCTION_shaklidagi_rozilik_yozuvi_QABUL_QILINADI(client, ai):
    """⚠️  PRODUCTION (2026-11-04T16:31Z dan beri `ci-proof/public-demo-cutover`,
        `build.commit=6ef666b…`) rozilikni BOSHQA shaklda saqlaydi:
        `{**requirement.public(), granted_at, employee_id}` — ya'ni ichida
        `revision`, `mode`, `provider_name`, `protocol_version` ham bor va
        `revision` BAZADAN keladigan monoton son (migratsiya `1` dan boshlaydi).

        Shu branch deploy qilinsa, o'sha yozuvlar SHU kod bilan o'qilishi
        kerak — aks holda rozilik bergan har do'kon qaytadan so'rashga majbur
        bo'lardi. Kalit: ikkala tomon ham AYNI `disclosure_id` ni
        (`binos.receiving.ai.v1`) va AYNI `provider`/`disclosure_version`
        juftligini saqlaydi.

        ⚠️  AMALDA production'da rozilik yozuvi BO'LMASLIGI kerak: migratsiya
            `mode='paused'` bilan ekiladi va `grant` 503 beradi. Bu test ayni
            shu taxminga TAYANMAYDI — yozuv bo'lsa ham ishlashini tekshiradi.
    """
    from app.db.session import SessionLocal
    from app.models.settings import Setting
    from app.services import ai_consent as _AC

    d = _shop()
    ai.gemini()
    db = SessionLocal()
    try:
        db.add(Setting(company_id=d["cid"], key=_AC.CONSENT_KEY, value={
            #  AYNAN `ai_requirement.Requirement.public()` chiqishi + ikki maydon.
            "revision": 1,                       # BAZADAN kelgan, shu branchdagi 2 EMAS
            "mode": "active",
            "provider": "gemini",
            "provider_name": "Google Gemini (Google LLC)",
            "model": "gemini-2.5-flash",
            "disclosure_version": 1,
            "disclosure_id": "binos.receiving.ai.v1",
            "protocol_version": 2,
            "granted_at": "2026-11-04T17:00:00+00:00",
            "employee_id": str(d["eid"]),
        }))
        db.commit()
    finally:
        db.close()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()

    assert st["granted"] is True, (
        ("production shaklidagi rozilik RAD etildi — deploydan keyin har "
         "do'kon qaytadan rozilik so'rashga majbur bo'lardi"), st)
    assert st["disclosure_id"] == "binos.receiving.ai.v1", st
    #  Reviziya SON jihatidan farq qiladi (bazadagi 1 -> shu branchda 2) va bu
    #  NORMAL: mijoz har safar holatni qayta o'qiydi, skanda esa AYNI
    #  o'qilgan reviziyani yuboradi.
    assert st["revision"] == _AC.requirement_revision("gemini"), st
    assert client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg",
        "revision": st["revision"]}).status_code == 200
