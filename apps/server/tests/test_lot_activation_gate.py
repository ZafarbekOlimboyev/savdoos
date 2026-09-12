# -*- coding: utf-8 -*-
"""PARTIYA KUZATUVINI YOQISH DARVOZASI — PRODUCTION'DA RAD.

⚠️  NEGA ALOHIDA FAYL. Bu qoida Phase 2 dan beri KODDA bor edi, lekin uni
    o'lchaydigan test YO'Q edi — ya'ni «production'da DENY» degan da'vo har
    bosqichda KOD O'QISH bilan tasdiqlanardi. Kuzatuvni yoqish QAYTARIB
    BO'LMAYDIGAN amal (tarix paydo bo'lgach uni o'chirish yo'li yo'q), shu
    bois darvoza sinov bilan mahkamlanadi.

⚠️  FAIL-CLOSED. «Signal yo'q» «production emas» degani EMAS. Loyihada aynan
    shu xato bir marta bo'lgan: `APP_ENV` yo'qligi «dev» deb talqin qilinib,
    katalog reseti production'da OCHIQ qolgan edi (`catalog_reset` izohi).
"""
import pytest

from app.services import lot_policy as LP


@pytest.mark.parametrize("app_env", ["production", "prod", "", "PRODUCTION", "boshqa"])
def test_PRODUCTION_va_NOMALUM_muhitda_yoqib_bolmaydi(monkeypatch, app_env):
    """Ruxsat ro'yxatida bo'lmagan HAR QANDAY muhit — RAD."""
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    assert LP.activation_allowed() is False, app_env
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed()


def test_APP_ENV_UMUMAN_yoq_bolsa_ham_RAD(monkeypatch):
    """⚠️  JONLI PRODUCTION KONFIGURATSIYASI. `APP_ENV` o'rnatilmagan muhit
        «dev» deb o'qilsa, darvoza JIMGINA ochilardi."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    assert LP.activation_allowed() is False
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed()


@pytest.mark.parametrize("platform", ["production", "prod"])
def test_PLATFORMA_belgisi_APP_ENV_dan_USTUN(monkeypatch, platform):
    """`APP_ENV=dev` berib production darvozasini OCHIB bo'lmaydi.

    ⚠️  Bu ikkinchi, MUSTAQIL to'siq: birinchisi (`APP_ENV`) so'rov bilan
        o'zgartirilishi mumkin bo'lgan konfiguratsiya, ikkinchisi esa
        platformaning O'Z belgisi.
    """
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", platform)
    assert LP.activation_allowed() is False, platform
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed()


@pytest.mark.parametrize("app_env", ["dev", "test", "staging"])
def test_RUXSAT_ETILGAN_muhitlarda_yoqiladi(monkeypatch, app_env):
    """Nazorat: darvoza hamma joyda yopiq bo'lsa, yuqoridagi sinovlar BO'SH bo'lardi."""
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", app_env)
    assert LP.activation_allowed() is True, app_env
    LP.assert_activation_allowed()          # otilmasin


def test_RUXSAT_royxati_production_ni_OZ_ICHIGA_OLMAYDI():
    """Ro'yxat kelajakda kengaytirilsa, bu sinov darhol QIZIL bo'ladi."""
    assert "production" not in LP.LOT_ACTIVATION_ALLOWED_ENVS
    assert "prod" not in LP.LOT_ACTIVATION_ALLOWED_ENVS
    assert LP.LOT_ACTIVATION_ALLOWED_ENVS == frozenset({"dev", "test", "staging"})


def test_API_darvozasi_403_qaytaradi(client, admin_headers, monkeypatch):
    """Uchidan-uchiga: HTTP qatlami ham 403 bersin (500 emas)."""
    from app.api.v1 import lots as lots_api
    monkeypatch.setattr(lots_api.LP, "assert_activation_allowed",
                        lots_api.LP.assert_activation_allowed)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    r = client.post("/api/v1/products/bulk", headers=admin_headers, json={"items": [
        {"name": f"Darvoza sinov {id(client)}", "sell_price": 100, "buy_price": 50,
         "unit_code": "dona", "stock": 0}]})
    assert r.status_code == 200, r.text
    pid = r.json()[0]["id"]
    rr = client.post("/api/v1/lots/enable", headers=admin_headers, json={
        "product_id": pid, "reason": "production darvozasi sinovi"})
    assert rr.status_code == 403, rr.text
    # Mahsulot KUZATUVSIZ qolsin — rad etish hech narsa yozmagan bo'lsin.
    from app.db.session import SessionLocal
    from app.models.catalog import Product
    import uuid as _u
    with SessionLocal() as db:
        p = db.get(Product, _u.UUID(pid))
        assert p.track_lots is False
        assert p.lots_activated_at is None
