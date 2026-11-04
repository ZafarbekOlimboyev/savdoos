# -*- coding: utf-8 -*-
"""R7.2 — KANONIK AI TALABI: SERVER ↔ FLUTTER ↔ DESKTOP UCH TOMONLAMA QULF.

Bu fayl R7.1 ning `test_r71_ai_consent_contract.py` sini ALMASHTIRADI.

NEGA ALMASHTIRILDI. R7.1 shu branch'da AI talabini KODDA e'lon qilingan statik
jadval (`REQUIREMENT_REVISIONS`) bilan amalga oshirgan edi, chunki
production'da kanonik mexanizm borligi O'SHA PAYTDA ma'lum emas edi.
Production (`ci-proof/public-demo-cutover`, 2026-11-04T16:31Z dan beri jonli)
esa ancha kuchli mexanizmni olib yuradi:

  · `ai_requirement` JADVALI — singleton qator, monoton reviziya (trigger
    o'chirishni ham, reviziyani orqaga qaytarishni ham taqiqlaydi);
  · UCH REJIMLI holat mashinasi: `paused` / `demo` / `active`;
  · AKTIVATSIYA PANJARASI (`locked()`): protokol/dispatch/oshkor etish
    versiyasi mos kelmasa 503 `AI_WORKER_FENCED`; `paused` -> 503
    `AI_REQUIREMENT_PAUSED`; `active` da provayder+model+KREDENTSIAL
    tekshiriladi (503 `AI_CREDENTIAL_UNAVAILABLE`);
  · QULF TARTIBI: siyosat -> kompaniya -> rozilik (`FOR SHARE`/`FOR UPDATE`,
    `lock_timeout = 5s`), qulflar provayder chaqiruvi davomida ushlab turiladi;
  · `activate()` FAQAT imtiyozli CLI'dan (`app/tools/ai_requirement.py`,
    `--commit` talab qiladi) chaqiriladi — startup'da AVTOMATIK
    aktivlashtirish YO'Q.

Shu bois R7.1 ning statik jadvali TASHLANDI va kanonik mexanizm SAQLANDI.
R7.1 dan KO'CHIRILGANI — shartnomani uch tomondan qulflash g'oyasi:

    HAQIQIY FastAPI server  ──(bu fayl)──>  contracts/ai_consent.samples.json
                                                     │
                      ┌──────────────────────────────┴───────────────────┐
                      v                                                  v
    HAQIQIY AiConsent.fromJson                        desktop `St` maydonlari
    (receiving_ai_backend_contract_test.dart)         (tests/ai-consent-contract.test.ts)

Etalonni qayta yozish (shartnoma ATAYLAB o'zgarganda):
    BINOS_WRITE_AI_CONTRACT=1 pytest tests/test_r72_ai_consent_contract.py -k ETALON
Yozilgan faylni DIFF bilan ko'rib chiqing: u ikki mijoz uchun majburiy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

#  Sintetik rasm yasovchilar — HAQIQIY fayl ham, PIL ham kerak emas.
from tests.test_ch16_ai_rozilik_va_rasm import _b64, _jpeg
from tests.test_mobile_parity import _shop

#  Repo ildizi: .../apps/server/tests/<bu fayl> -> uch pog'ona yuqori.
ETALON = Path(__file__).resolve().parents[3] / "contracts" / "ai_consent.samples.json"

#  ⚠️  VAQTGA BOG'LIQ MAYDON. `granted_at` har yurishda boshqa — etalonda
#      uning QIYMATI emas, MAVJUDLIGI va TURI qulflanadi.
UCHQUR = "<vaqt>"


# ══ KANONIK SIYOSATNI O'RNATISH ═════════════════════════════════════════════

def _policy(mode: str, provider: str | None = None, model: str | None = None) -> int:
    """Kanonik siyosatni ATAYLAB o'rnatadi va yangi reviziyani qaytaradi.

    ⚠️  Bu TEST bazasida ishlaydi. Production siyosatini faqat imtiyozli CLI
        (`app/tools/ai_requirement.py --commit`) o'zgartiradi; bu yerda
        `activate()` ning O'ZI chaqiriladi, ya'ni panjara mantig'i ham
        sinovdan o'tadi (noto'g'ri juftlik 422 beradi).
    """
    from app.db.session import SessionLocal
    from app.models.ai_requirement import AiRequirement
    from app.services import ai_requirement as AR

    with SessionLocal() as db:
        row = db.get(AiRequirement, 1)
        if row is None:
            row = AiRequirement(
                id=1, revision=1, mode="paused", provider=None, model=None,
                disclosure_version=1, disclosure_id=AR.DISCLOSURE_ID,
                protocol_version=AR.PROTOCOL_VERSION, dispatch_id=AR.DISPATCH_ID,
                activated_by="r72-test")
            db.add(row)
            db.flush()
        rev = AR.activate(db, expected_revision=row.revision, mode=mode,
                          provider=provider, model=model, actor="r72-test")
        db.commit()
        return rev


@pytest.fixture()
def ai(monkeypatch):
    """MOCK provayder + kredentsial izolyatsiyasi. HAQIQIY tarmoq chaqirig'i YO'Q.

    Har test `_policy(...)` bilan kerakli rejimni O'ZI tanlaydi — fikstura
    hech qanday rejimni «standart» deb o'rnatmaydi, chunki `paused` va
    `demo` orasidagi farq aynan o'lchanadigan narsa.
    """
    from app.core.config import settings
    from app.services import receiving_ai as RA

    yuborilgan: list[dict] = []

    def _mock(image_b64, media_type, prompt, target):
        yuborilgan.append({"b64": image_b64, "media_type": media_type,
                           "provider": target.provider, "model": target.model})
        return [{"name": "Shakar", "qty": 2, "unit": "kg", "price": 1000}]

    monkeypatch.setattr(RA, "_read_gemini", _mock)
    monkeypatch.setattr(RA, "_read_claude", _mock)
    monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)

    class _Boshqaruv:
        sent = yuborilgan

        @staticmethod
        def paused():
            return _policy("paused")

        @staticmethod
        def demo():
            return _policy("demo")

        @staticmethod
        def active(provider="gemini"):
            monkeypatch.setattr(settings, "gemini_api_key",
                                "sinov-kaliti" if provider == "gemini" else "",
                                raising=False)
            monkeypatch.setattr(settings, "anthropic_api_key",
                                "sinov-kaliti" if provider == "anthropic" else "",
                                raising=False)
            return _policy("active", provider, "synthetic-model")

        @staticmethod
        def active_without_credential(provider="gemini"):
            monkeypatch.setattr(settings, "gemini_api_key", "", raising=False)
            monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
            return _policy("active", provider, "synthetic-model")

    return _Boshqaruv()


def _normal(body: dict) -> dict:
    out = dict(body)
    if out.get("granted_at") is not None:
        out["granted_at"] = UCHQUR
    return out


def _revizionlarni_normallashtirish(namunalar: list[dict]) -> list[dict]:
    """`revision` — ISH VAQTI HOLATI, shartnoma qiymati EMAS.

    ⚠️  NEGA KERAK. Kanonik reviziya `ai_requirement` singleton qatorida
        yashaydi va `activate()` har chaqirilganda OSHADI. Bitta pytest
        seansida boshqa testlar ham siyosatni o'zgartiradi (`test_ch16` ning
        `ai` fiksturasi), ya'ni ABSOLUT qiymat TEST TARTIBIGA bog'liq bo'lib
        qoladi va etalon yakka yurishda yashil, to'liq to'plamda qizil
        bo'lardi — aynan shu kuzatildi va shu bois normallashtirish kiritildi.

    Nima SAQLANADI (shartnoma uchun muhim bo'lgani):
      · tur va diapazon — butun son, >= 1 (mijozlar shu talabni tekshiradi);
      · MUNOSABATLAR — ayni talab ayni raqamni oladi, BOSHQA talab BOSHQA
        raqamni (provayder o'zgarishi testi aynan shunga tayanadi).
    Nima tashlanadi: absolut qiymat, ya'ni «nechanchi marta aktivlashtirilgan».

    Usul: paydo bo'lish tartibida 1, 2, 3 … ga qayta raqamlash.
    """
    xarita: dict[int, int] = {}
    out: list[dict] = []
    for n in namunalar:
        yangi = dict(n)
        body = dict(n.get("body") or {})
        if isinstance(body.get("revision"), int):
            xarita.setdefault(body["revision"], len(xarita) + 1)
            body["revision"] = xarita[body["revision"]]
            yangi["body"] = body
        req = n.get("request")
        if isinstance(req, dict) and isinstance(req.get("revision"), int):
            r = dict(req)
            xarita.setdefault(r["revision"], len(xarita) + 1)
            r["revision"] = xarita[r["revision"]]
            yangi["request"] = r
        out.append(yangi)
    return out


def _grant_body(st: dict) -> dict:
    """Mijoz AYNAN KO'RSATILGAN talabni qaytaradi (`ConsentIn`)."""
    return {"revision": st["revision"], "provider": st["provider"],
            "disclosure_id": st["disclosure_id"],
            "disclosure_version": st["disclosure_version"]}


# ══ 1. ETALON — SERVER SILJISA QIZIL ════════════════════════════════════════

def _yig(client, ai) -> list[dict]:
    """HAQIQIY server javoblari — kanonik holat mashinasining har rejimi."""
    from app.services import ai_requirement as AR

    d = _shop()
    H = d["H"]
    ns: list[dict] = []

    def _rec(scenario, izoh, method, path, r, request=None):
        item = {"scenario": scenario, "izoh": izoh, "method": method, "path": path,
                "status": r.status_code, "body": _normal(r.json())}
        if request is not None:
            item["request"] = request
        ns.append(item)
        return r

    def _get(scenario, izoh):
        return _rec(scenario, izoh, "GET", "/receiving/ai-consent",
                    client.get("/api/v1/receiving/ai-consent", headers=H))

    # 1. PAUSED — AI ATAYLAB o'chirilgan (migratsiya shu holatda ekadi).
    ai.paused()
    _get("paused", "Siyosat paused: 503, tashqi uzatish YO'Q")

    # 2. DEMO — tashqi uzatish YO'Q, rozilik TALAB QILINMAYDI.
    ai.demo()
    _get("demo", "Siyosat demo: rozilik talab qilinmaydi, tashqariga hech narsa chiqmaydi")

    # 3. ACTIVE, rozilik YO'Q — dialog KERAK (fail-closed).
    ai.active("gemini")
    _get("active_rozilik_yoq", "Siyosat active, rozilik yo'q: dialog kerak, skan 403")

    # 4. Mijoz AYNAN ko'rsatilgan talabni qaytarib ROZILIK BERADI.
    holat = client.get("/api/v1/receiving/ai-consent", headers=H).json()
    _rec("active_grant_echo", "Mijoz ko'rsatilgan talabni AYNAN qaytaradi",
         "POST", "/receiving/ai-consent",
         client.post("/api/v1/receiving/ai-consent", headers=H, json=_grant_body(holat)),
         request=_grant_body(holat))

    # 5. Rozilik BERILGAN holat.
    _get("active_berilgan", "Rozilik yozilgan: uzatishga ruxsat")

    # 6. PROVAYDER O'ZGARDI — reviziya oshadi, eski rozilik KUCHINI YO'QOTADI.
    ai.active("anthropic")
    _get("provayder_ozgardi", "Reviziya oshdi: eski rozilik avtomatik o'tmaydi")

    # 7. ROZILIK QAYTARIB OLINDI (paused bo'lsa ham ishlashi kerak).
    ai.active("gemini")
    r = client.delete("/api/v1/receiving/ai-consent", headers=H)
    _rec("qaytarib_olindi", "DELETE: fail-closed holatga qaytdi",
         "DELETE", "/receiving/ai-consent", r)

    shartnoma = {
        "disclosure_id": AR.DISCLOSURE_ID,
        "disclosure_version": 1,
        "protocol_version": AR.PROTOCOL_VERSION,
        "dispatch_id": AR.DISPATCH_ID,
        "modes": ["active", "paused", "demo"],
        "providers": sorted(AR.PROVIDERS),
    }
    return [{"shartnoma": shartnoma}] + _revizionlarni_normallashtirish(ns)


def test_ETALON_haqiqiy_server_javobi_bilan_AYNAN_mos(client, ai):
    """`contracts/ai_consent.samples.json` — HAQIQIY kanonik server javobining
    qotirilgan nusxasi. Shartnoma o'zgarsa bu test QIZIL bo'ladi va IKKI
    mijozni ham yangilash kerakligini ko'rsatadi."""
    hozir = _yig(client, ai)

    if os.environ.get("BINOS_WRITE_AI_CONTRACT") == "1":
        ETALON.write_text(json.dumps(hozir, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        pytest.skip(f"etalon qayta yozildi: {ETALON} — diff bilan ko'rib chiqing")

    assert ETALON.exists(), f"etalon yo'q: {ETALON}"
    kutilgan = json.loads(ETALON.read_text(encoding="utf-8"))
    assert hozir == kutilgan, (
        "KANONIK SHARTNOMA SILJIDI. Ikki mijoz shu fayldan tekshiriladi — "
        "`apps/mobile/test/receiving_ai_backend_contract_test.dart` va "
        "`tests/ai-consent-contract.test.ts` ni ham yangilang.\n\nhozir:\n"
        + json.dumps(hozir, ensure_ascii=False, indent=2)[:3000])


# ══ 2. HOLAT MASHINASI — SPETSIFIKATSIYANING YETTI BANDI ═══════════════════

def test_PAUSED_503_va_TASHQI_CHAQIRUV_NOL(client, ai):
    """`paused` -> 503 va provayder UMUMAN chaqirilmaydi."""
    d = _shop()
    ai.paused()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"])
    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": 1, "image_b64": _b64(_jpeg()), "media_type": "image/jpeg"})

    assert st.status_code == 503, (st.status_code, st.text[:200])
    assert st.headers.get("X-Error-Code") == "AI_REQUIREMENT_PAUSED", dict(st.headers)
    assert sc.status_code == 503, (sc.status_code, sc.text[:200])
    assert ai.sent == [], "paused holatda provayder CHAQIRILDI"


def test_DEMO_tashqi_UZATILMAYDI_va_rozilik_TALAB_QILINMAYDI(client, ai):
    """`demo` -> namunaviy qatorlar, tashqariga HECH NARSA chiqmaydi."""
    d = _shop()
    ai.demo()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"})

    assert st["required"] is False and st["granted"] is False, st
    assert st["mode"] == "demo" and st["provider"] is None, st
    assert sc.status_code == 200, (sc.status_code, sc.text[:200])
    assert ai.sent == [], "demo rejimda TASHQARIGA uzatildi"


def test_ACTIVE_rozilik_YOQ_FAIL_CLOSED(client, ai):
    """`active`, rozilik yo'q -> 403 va rasm UMUMAN chiqmaydi."""
    d = _shop()
    ai.active("gemini")

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"})

    assert st["required"] is True and st["granted"] is False, st
    assert sc.status_code == 403, (sc.status_code, sc.text[:200])
    assert sc.headers.get("X-Error-Code") == "AI_CONSENT_REQUIRED", dict(sc.headers)
    assert ai.sent == [], "roziliksiz uzatildi"


def test_ACTIVE_rozilik_BOR_talabga_MOS_RUXSAT(client, ai):
    """`active` + rozilik -> uzatiladi va AYNAN e'lon qilingan provayderga."""
    d = _shop()
    ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    assert client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                       json=_grant_body(st)).status_code == 200

    st2 = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st2["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"})

    assert st2["granted"] is True, st2
    assert sc.status_code == 200, (sc.status_code, sc.text[:200])
    assert len(ai.sent) == 1, ai.sent
    assert ai.sent[0]["provider"] == "gemini", ai.sent[0]
    assert ai.sent[0]["model"] == "synthetic-model", ai.sent[0]


def test_REVIZIYA_OZGARSA_eski_rozilik_RAD_ETILADI(client, ai):
    """Reviziya oshsa (provayder/model/rejim o'zgarishi) eski rozilik o'tmaydi."""
    d = _shop()
    rev1 = ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    client.post("/api/v1/receiving/ai-consent", headers=d["H"], json=_grant_body(st))
    assert client.get("/api/v1/receiving/ai-consent",
                      headers=d["H"]).json()["granted"] is True
    oldin = len(ai.sent)

    rev2 = ai.active("anthropic")
    st2 = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st2["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"})

    assert rev2 > rev1, (rev1, rev2)
    assert st2["revision"] == rev2 and st2["granted"] is False, st2
    assert st2["previous_provider"] == "gemini", st2
    assert sc.status_code == 403, (sc.status_code, sc.text[:200])
    assert len(ai.sent) == oldin, "yangi provayderga ROZILIKSIZ uzatildi"


def test_ESKIRGAN_REVIZIYA_bilan_skan_409(client, ai):
    """Mijoz eskirgan reviziya yuborsa -> 409 va rasm UZATILMAYDI."""
    d = _shop()
    rev1 = ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    client.post("/api/v1/receiving/ai-consent", headers=d["H"], json=_grant_body(st))
    ai.active("gemini")                       # reviziya oshdi, rozilik eskirdi
    oldin = len(ai.sent)

    sc = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": rev1, "image_b64": _b64(_jpeg()), "media_type": "image/jpeg"})

    assert sc.status_code == 409, (sc.status_code, sc.text[:200])
    assert sc.headers.get("X-Error-Code") == "AI_REQUIREMENT_CHANGED", dict(sc.headers)
    assert len(ai.sent) == oldin, "eskirgan reviziya bilan rasm UZATILDI"


def test_TENANT_izolyatsiyasi_rozilik_UMUMLASHMAYDI(client, ai):
    """A do'konining roziligi B do'koniga O'TMAYDI."""
    A, B = _shop(), _shop()
    ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=A["H"]).json()
    client.post("/api/v1/receiving/ai-consent", headers=A["H"], json=_grant_body(st))
    oldin = len(ai.sent)

    stb = client.get("/api/v1/receiving/ai-consent", headers=B["H"]).json()
    rb = client.post("/api/v1/receiving/scan", headers=B["H"], json={
        "revision": stb["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"})

    assert stb["granted"] is False, stb
    assert rb.status_code == 403, rb.status_code
    assert len(ai.sent) == oldin, "B do'koni A ning roziligi bilan uzatdi"
    #  A hamon ishlaydi — izolyatsiya BIR TOMONLAMA emas.
    assert client.post("/api/v1/receiving/scan", headers=A["H"], json={
        "revision": st["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"}).status_code == 200


def test_KREDENTSIAL_YOQ_bolsa_FAIL_CLOSED(client, ai):
    """`active`, lekin kalit yo'q -> 503 va uzatish YO'Q.

    Kalitning MAVJUDLIGI AI ni aktivlashtirmaydi va YO'QLIGI jim demo rejimga
    tushirmaydi — ikkisi ham fail-closed."""
    d = _shop()
    ai.active_without_credential("gemini")

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"])

    assert st.status_code == 503, (st.status_code, st.text[:200])
    assert st.headers.get("X-Error-Code") == "AI_CREDENTIAL_UNAVAILABLE", dict(st.headers)
    assert ai.sent == []


# ══ 3. ESKI MIJOZLAR — KANONIK SHARTNOMA ULARDAN NIMA TALAB QILADI ═════════

def test_ESKI_DESKTOP_shaklidagi_sorov_422_RAD_ETILADI(client, ai):
    """⚠️  O'RNATILGAN DESKTOP KANONIK SHARTNOMAGA MOS KELMAYDI.

    `packages/shared/src/screens/Purchases.tsx` POST'ga FAQAT
    `{disclosure_version}` yuboradi, skanga esa reviziya umuman yubormaydi.
    Kanonik `ConsentIn`/`ScanIn` da bu maydonlar MAJBURIY, ya'ni javob 422.

    Bu test o'sha holatni QOTIRADI, chunki u SERVER nuqsoni EMAS — mijozni
    yangilash talabi. Server tomonini bo'shashtirish rozilikni «ko'rsatilgan
    talabga bog'lash» invariantini buzardi.
    """
    d = _shop()
    ai.active("gemini")

    grant = client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                        json={"disclosure_version": 1})
    scan = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "image_b64": _b64(_jpeg()), "media_type": "image/jpeg"})

    assert grant.status_code == 422, (grant.status_code, grant.text[:200])
    assert scan.status_code == 422, (scan.status_code, scan.text[:200])
    assert ai.sent == [], "shakl xatosiga qaramay rasm uzatildi"
    assert not client.get("/api/v1/receiving/ai-consent",
                          headers=d["H"]).json()["granted"]


def test_YANGI_MIJOZ_shaklidagi_sorov_OTADI(client, ai):
    """Build 67 / yangi desktop AYNAN shu tanani yuboradi va o'tadi."""
    d = _shop()
    ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()

    grant = client.post("/api/v1/receiving/ai-consent", headers=d["H"],
                        json=_grant_body(st))

    assert grant.status_code == 200, (grant.status_code, grant.text[:200])
    assert grant.json()["granted"] is True, grant.json()
    assert client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg"}).status_code == 200


@pytest.mark.parametrize("tana, izoh", [
    ({"revision": 0, "provider": "gemini", "disclosure_id": "binos.receiving.ai.v1",
      "disclosure_version": 1}, "revision < 1"),
    ({"revision": "2", "provider": "gemini", "disclosure_id": "binos.receiving.ai.v1",
      "disclosure_version": 1}, "revision satr (strict)"),
    ({"revision": 2, "provider": "openai", "disclosure_id": "binos.receiving.ai.v1",
      "disclosure_version": 1}, "provider ro'yxatda yo'q"),
    ({"revision": 2, "provider": "gemini", "disclosure_id": "",
      "disclosure_version": 1}, "disclosure_id bo'sh"),
    ({"revision": 2, "provider": "gemini", "disclosure_id": "x" * 101,
      "disclosure_version": 1}, "disclosure_id > 100"),
    ({"revision": 2, "provider": "gemini", "disclosure_id": "binos.receiving.ai.v1"},
     "disclosure_version yo'q"),
])
def test_NOTOGRI_DTO_422_va_ROZILIK_YOZILMAYDI(client, ai, tana, izoh):
    """Shakl xatosi 422 bo'lsin va rozilik YOZILMASIN."""
    d = _shop()
    ai.active("gemini")

    r = client.post("/api/v1/receiving/ai-consent", headers=d["H"], json=tana)

    assert r.status_code == 422, (izoh, r.status_code, r.text[:200])
    assert not client.get("/api/v1/receiving/ai-consent",
                          headers=d["H"]).json()["granted"], izoh


def test_MIJOZ_BAYROGI_rozilik_BERMAYDI(client, ai):
    """⚠️  Mijoz yuborgan `consent: true` — rozilik DALILI EMAS."""
    d = _shop()
    ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()

    r = client.post("/api/v1/receiving/scan", headers=d["H"], json={
        "revision": st["revision"], "image_b64": _b64(_jpeg()),
        "media_type": "image/jpeg",
        "consent": True, "ai_consent": True, "granted": True})

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert ai.sent == []


# ══ 4. AKTIVATSIYA PANJARASI VA MONOTON REVIZIYA ═══════════════════════════

def test_REVIZIYA_MONOTON_va_ORQAGA_QAYTMAYDI(client, ai):
    """`activate()` reviziyani AYNAN bir qadam oshiradi; eski kutilgan
    reviziya bilan chaqirilsa 409 beradi (CAS)."""
    from app.db.session import SessionLocal
    from app.models.ai_requirement import AiRequirement
    from app.services import ai_requirement as AR
    from fastapi import HTTPException

    r1 = ai.demo()
    r2 = ai.active("gemini")
    assert r2 == r1 + 1, (r1, r2)

    with SessionLocal() as db:
        with pytest.raises(HTTPException) as xato:
            AR.activate(db, expected_revision=r1, mode="demo", provider=None,
                        model=None, actor="r72-test")
        assert xato.value.status_code == 409
        db.rollback()
        assert db.get(AiRequirement, 1).revision == r2, "reviziya o'zgardi"


def test_PANJARA_notogri_protokol_FENCED(client, ai):
    """Protokol/dispatch mos kelmasa -> 503 `AI_WORKER_FENCED`, uzatish YO'Q."""
    from app.db.session import SessionLocal
    from app.models.ai_requirement import AiRequirement

    d = _shop()
    ai.active("gemini")
    with SessionLocal() as db:
        row = db.get(AiRequirement, 1)
        row.protocol_version = 99                 # ESKIRGAN ishchi simulyatsiyasi
        db.commit()

    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"])

    assert st.status_code == 503, (st.status_code, st.text[:200])
    assert st.headers.get("X-Error-Code") == "AI_WORKER_FENCED", dict(st.headers)
    assert ai.sent == []


def test_BEKOR_QILISH_paused_holatda_HAM_ishlaydi(client, ai):
    """Rozilikni qaytarib olish siyosat `paused` bo'lsa ham mumkin bo'lishi
    kerak — aks holda do'kon o'z roziligini qaytarib olmay qolardi."""
    d = _shop()
    ai.active("gemini")
    st = client.get("/api/v1/receiving/ai-consent", headers=d["H"]).json()
    client.post("/api/v1/receiving/ai-consent", headers=d["H"], json=_grant_body(st))

    ai.paused()
    r = client.delete("/api/v1/receiving/ai-consent", headers=d["H"])

    assert r.status_code == 200, (r.status_code, r.text[:200])
    ai.active("gemini")
    assert not client.get("/api/v1/receiving/ai-consent",
                          headers=d["H"]).json()["granted"]


# ══ 5. KANONIK XATO MATNLARI TARJIMALI BO'LISHI SHART ══════════════════════

def test_KANONIK_XATO_MATNLARI_TARJIMALI():
    """`ai_requirement.reject()` chiqaradigan HAR BIR matn desktop lug'atida
    ru va uzc tarjimasiga EGA bo'lishi shart.

    ⚠️  NEGA BU TEST ALOHIDA. Desktop xatoni KOD bo'yicha emas, MATN bo'yicha
        tarjima qiladi (`packages/shared/src/lib/api.ts` -> `translateLotError(detail)`).
        Ya'ni lug'atda yo'q matn rus/kirill tilidagi do'kon egasiga XOM
        lotin-o'zbekcha bo'lib ko'rinadi va hech qayerda xato chiqmaydi.
        R7.2 integratsiyasida aynan shu holat topildi: kanonik siyosatning
        uchala matni lug'atdan TUSHIB QOLGAN edi.

    ⚠️  NEGA `test_lot_error_texts.py` ushlamaydi. U `HTTPException(...)` ning
        LITERAL matn argumentlarini AST bilan yig'adi; `reject()` esa matnni
        kod->matn lug'atidan DINAMIK oladi. Shu bois bu yerda matnlar
        `reject()` ni HAQIQATAN chaqirib olinadi.
    """
    import pathlib
    import re

    from fastapi import HTTPException

    from app.services import ai_requirement as AR

    #  Modulda ishlatiladigan BARCHA kodlar (AST emas — oddiy qidiruv yetarli,
    #  chunki kodlar literal satr sifatida yoziladi).
    manba = pathlib.Path(AR.__file__).read_text(encoding="utf-8")
    kodlar = sorted(set(re.findall(r'reject\(\s*\d+\s*,\s*"([A-Z_]+)"', manba)))
    assert kodlar, "modulda `reject(...)` chaqiruvi topilmadi"

    matnlar = set()
    for kod in kodlar:
        try:
            AR.reject(503, kod)
        except HTTPException as e:
            matnlar.add(str(e.detail))
    assert matnlar, "matn yig'ilmadi"

    lugat = (pathlib.Path(__file__).resolve().parents[3]
             / "packages" / "shared" / "src" / "lib" / "serverErrorsLots.ts")
    assert lugat.exists(), lugat
    src = lugat.read_text(encoding="utf-8")

    yoq = []
    for m in sorted(matnlar):
        #  Kalit — AYNI matn; qiymatida `ru:` va `uzc:` bo'lishi shart.
        i = src.find(f'"{m}"')
        if i < 0:
            yoq.append((m, "lug'atda KALIT YO'Q"))
            continue
        blok = src[i:i + 900]
        if "ru:" not in blok or "uzc:" not in blok:
            yoq.append((m, "ru yoki uzc tarjimasi yo'q"))
    assert not yoq, (
        "KANONIK XATO MATNLARI TARJIMASIZ — rus/kirill egasi xom lotin matn "
        f"ko'radi:\n" + "\n".join(f"  · [{s}] {m[:70]}" for m, s in yoq))
