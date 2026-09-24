# -*- coding: utf-8 -*-
"""PHASE 5G.1 / C3 — SERVER QOBILIYAT DARAJASI (`GET /health` dagi `api` bloki).

NEGA: mijoz (Android / PWA) ESKI serverga urilganda buni OLDINDAN bilishi kerak.
Production `99b1da7` da `/auth/context`, `/products/scan`, `/cash/custody-preview`,
sahifalangan `/products` (`X-Total-Count`), `/sales/{id}/receipt`,
`/receiving/{id}/corrections` va `X-Error-Code` YO'Q — bundan tashqari u
`access-control-expose-headers` YUBORMAYDI, ya'ni brauzer mijoz bu sarlavhalarni
o'qiy olmaydi. Mijoz shu holatni SHA bo'yicha emas, serverning O'ZI e'lon qilgan
DARAJA bo'yicha bilishi kerak: eski server `api` blokini umuman yubormaydi va bu
mijozda `level 0` deb o'qiladi — hech qanday alohida holat kerak emas.

BU SINOV NIMANI USHLAYDI:
  1. `/health` da `api.level` (butun son) va `api.features` (NOMLAR, marshrutlar emas) bor;
  2. daraja MONOTON — yangi daraja eskisining ustiga qo'shiladi, qobiliyat O'CHIRILMAYDI
     (1-darajaning ro'yxati shu faylda NUSXA sifatida muzlatilgan — koddan import EMAS,
     shuning uchun ro'yxatdan nom olib tashlansa sinov yiqiladi);
  3. e'lon qilingan har bir qobiliyat AYNAN shu SHA da mavjud marshrutga mos keladi
     (o'ylab topilgan qobiliyat bo'lmasin);
  4. `/health` AVTORIZATSIYASIZ, ARZON va BAZAGA TEGMAYDI (SessionLocal yiqilsa ham 200).

⚠️  KUTILGAN RO'YXAT NUSXA (koddan import EMAS) — `test_mobile_parity.py` dagi qoida.
"""
from __future__ import annotations

import pytest

# 1-daraja qobiliyatlari — MUZLATILGAN NUSXA. Bu ro'yxatdan nom olib tashlash
# mijozlar uchun buzuvchi o'zgarish: shu sinov uni ushlaydi.
LEVEL_1 = {
    "auth_context",
    "cash_custody_preview",
    "error_codes",
    "products_paging",
    "products_scan",
    "receiving_corrections",
    "sale_receipt",
}

# Qaysi qobiliyat qaysi marshrutni anglatadi. `None` — marshrut emas (sarlavha).
FEATURE_ROUTES = {
    "auth_context": ("GET", "/api/v1/auth/context"),
    "cash_custody_preview": ("GET", "/api/v1/cash/custody-preview"),
    "error_codes": None,
    "products_paging": ("GET", "/api/v1/products"),
    "products_scan": ("GET", "/api/v1/products/scan"),
    "receiving_corrections": ("POST", "/api/v1/receiving/{receiving_id}/corrections"),
    "sale_receipt": ("GET", "/api/v1/sales/{sale_id}/receipt"),
}


def _api(client) -> dict:
    r = client.get("/api/v1/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "api" in body, "eski javob: `api` bloki yo'q — mijoz darajani bila olmaydi"
    return body["api"]


# ══ 1. E'LON ════════════════════════════════════════════════════════════════

def test_health_api_darajasi_va_qobiliyatlari(client):
    api = _api(client)
    assert isinstance(api["level"], int) and not isinstance(api["level"], bool)
    assert api["level"] >= 1, "e'lon qilingan daraja 1 dan boshlanadi (0 = eski server)"
    feats = api["features"]
    assert isinstance(feats, list) and all(isinstance(f, str) for f in feats)
    assert len(feats) == len(set(feats)), "takroriy qobiliyat nomi"
    assert feats == sorted(feats), "ro'yxat barqaror tartibda bo'lsin"
    # NOMLAR, marshrutlar emas: `/` bo'lgan nom marshrutni oshkor qilardi.
    assert all("/" not in f for f in feats), f"qobiliyat nomi marshrut emas: {feats}"
    assert LEVEL_1 <= set(feats), f"yetishmayotgan: {sorted(LEVEL_1 - set(feats))}"


def test_health_javobida_ortiqcha_maydon_yoq(client):
    body = client.get("/api/v1/health").json()
    assert set(body) == {"status", "service", "build", "api"}, body.keys()
    assert set(body["api"]) == {"level", "features"}, body["api"].keys()


# ══ 2. MONOTONLIK ═══════════════════════════════════════════════════════════

def test_daraja_monoton_va_qobiliyat_ochirilmaydi():
    from app.core import api_capabilities as cap

    levels = sorted(cap.LEVEL_FEATURES)
    assert levels == list(range(1, len(levels) + 1)), f"darajalar ketma-ket 1..N bo'lsin: {levels}"
    assert cap.API_LEVEL == levels[-1]

    seen: set[str] = set()
    prev: set[str] = set()
    for lv in levels:
        added = cap.LEVEL_FEATURES[lv]
        assert len(added) == len(set(added)), f"daraja {lv}: takroriy nom"
        assert not (set(added) & seen), f"daraja {lv}: qobiliyat ikki darajada e'lon qilingan"
        seen |= set(added)
        now = set(cap.features(lv))
        assert prev <= now, f"daraja {lv} oldingisidan qobiliyat OLIB TASHLAGAN: {sorted(prev - now)}"
        prev = now

    assert set(cap.features()) == seen
    assert set(cap.LEVEL_FEATURES[1]) == LEVEL_1, (
        "1-darajaning muzlatilgan ro'yxati o'zgargan — bu mijozlar uchun buzuvchi"
    )


def test_eski_server_darajasi_nol_deb_oqiladi():
    """Eski server `api` blokini yubormaydi. Mijoz uni 0 deb o'qiydi — bu yerda
    faqat "0 hech qanday qobiliyatni anglatmaydi" invarianti tasdiqlanadi."""
    from app.core import api_capabilities as cap

    assert cap.features(0) == []


# ══ 3. O'YLAB TOPILGAN QOBILIYAT YO'Q ═══════════════════════════════════════

def test_har_bir_qobiliyat_haqiqiy_marshrutga_mos(client):
    # ⚠️  Marshrutlar OpenAPI sxemasidan olinadi, `app.routes` dan emas: FastAPI
    #     `include_router` natijasini ichma-ich saqlaydi (`_IncludedRouter`) va
    #     tekis ro'yxatda v1 marshrutlari KO'RINMAYDI — sinov jimgina bo'sh
    #     to'plamni tekshirib «yashil» bo'lib qolardi.
    schema = client.get("/openapi.json")
    assert schema.status_code == 200, schema.text
    paths = schema.json()["paths"]
    real = {(m.upper(), p) for p, ops in paths.items() for m in ops}
    assert ("GET", "/api/v1/health") in real, "sxema bo'sh yoki boshqa shaklda"
    feats = _api(client)["features"]
    assert set(feats) == set(FEATURE_ROUTES), (
        "e'lon qilingan ro'yxat va sinovdagi marshrut xaritasi mos emas: "
        f"{sorted(set(feats) ^ set(FEATURE_ROUTES))}"
    )
    for name, route in FEATURE_ROUTES.items():
        if route is None:
            continue
        assert route in real, f"qobiliyat '{name}' mavjud bo'lmagan marshrutni e'lon qiladi: {route}"


def test_error_codes_qobiliyati_haqiqatan_sarlavha_chiqaradi(client):
    """`error_codes` — marshrut emas: (a) server `X-Error-Code` yuboradi va
    (b) uni CORS `expose_headers` da e'lon qiladi (brauzer mijoz o'qiy olsin).
    Production `99b1da7` da ikkalasi ham yo'q."""
    from starlette.middleware.cors import CORSMiddleware

    from app.core import error_codes
    from app.main import app

    exposed: list[str] = []
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            exposed = list(mw.kwargs.get("expose_headers") or [])
    assert error_codes.HEADER in exposed, f"CORS expose_headers: {exposed}"
    assert "X-Total-Count" in exposed, f"CORS expose_headers: {exposed}"


# ══ 4. ARZON, OCHIQ, BAZASIZ ════════════════════════════════════════════════

def test_health_avtorizatsiyasiz(client):
    r = client.get("/api/v1/health")          # Authorization sarlavhasi YO'Q
    assert r.status_code == 200, r.text
    assert r.json()["api"]["level"] >= 1


def test_health_bazaga_tegmaydi(client, monkeypatch):
    """Baza butunlay yiqilsa ham `/health` (tiriklik) 200 va daraja qaytaradi.

    Isbot: `health` moduli ko'rayotgan `SessionLocal` ATAYLAB yiqiladi va HAR
    chaqiruv sanaladi. `/health` 200 qaytaradi va sanoq NOL bo'lib qoladi —
    ya'ni seans umuman OCHILMAGAN. Keyin `/health/ready` AYNAN shu patch'ga
    uriladi: sanoq o'sadi — demak patch haqiqatan ta'sir qilgan (sinov bo'sh
    joyga urmagan)."""
    calls: list[int] = []

    def _boom(*a, **k):
        calls.append(1)
        raise RuntimeError("baza yiqildi (sinov)")

    monkeypatch.setattr("app.api.v1.health.SessionLocal", _boom)

    r = client.get("/api/v1/health")
    assert r.status_code == 200, r.text
    assert r.json()["api"]["level"] >= 1
    assert calls == [], "/health baza seansini OCHDI — tiriklik tekshiruvi bazasiz bo'lishi shart"

    # ⚠️  `_check_db` da `SessionLocal()` `try` dan TASHQARIDA — drayver
    #     konstruktori yiqilsa istisno ko'tariladi (503 emas). Bu yerda muhimi
    #     patch'ning KO'RINISHI: `/health/ready` unga uriladi, `/health` esa yo'q.
    with pytest.raises(RuntimeError):
        client.get("/api/v1/health/ready")
    assert calls, "patch ta'sir qilmadi — bazasizlik isboti bekor"


def test_api_capabilities_moduli_bazani_import_qilmaydi():
    """Qobiliyat e'loni — MA'LUMOT, bog'lanish emas: modul na bazani, na ilovani
    import qiladi (aks holda `/health` arzon bo'lib qolmasdi)."""
    import pathlib

    src = pathlib.Path("app/core/api_capabilities.py").read_text(encoding="utf-8")
    for bad in ("app.db", "sqlalchemy", "from app.main", "fastapi"):
        assert bad not in src, f"api_capabilities.py `{bad}` ni import qilyapti"


@pytest.mark.parametrize("path", ["/api/v1/health"])
def test_health_javobi_kichik(client, path):
    """Arzon: javob tanasi kichkina (har ishga tushishda va har 4 soatda so'raladi)."""
    r = client.get(path)
    assert len(r.content) < 2048, len(r.content)
