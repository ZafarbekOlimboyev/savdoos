# -*- coding: utf-8 -*-
"""Production operatsion tayyorlik — REGRESSIYA testlari.

Bu yerda tekshiriladigan xatti-harakatlar do'kon ochilishidan OLDIN to'g'ri bo'lishi shart.
Har biri HAQIQIY nosozlikni qoplaydi:

A  readiness baza yiqilganda 503 beradi (tiriklik 200 bilan chalg'itmaydi)
B  /health tiriklik: bazaga TEGMAYDI (restart signali xizmat signalidan ajratilgan)
C  demo seed production'da AVTOMATIK ishlamaydi
D  cashflow: naqd xarid chiqimda KO'RINADI (ledger-native) — "kassada" yolg'on ko'p emas
E  cashflow legacy tenant uchun O'ZGARMAYDI
F  fleet heartbeat qurilma versiyasini saqlaydi
G  fleet heartbeat company'ni SO'ROVDAN emas, TOKENDAN oladi (tenant soxtalashtirilmaydi)
H  navbat holati NOMA'LUM qurilma "tayyor" deb hisoblanmaydi (queue=0 O'YLAB TOPILMAYDI)
I  versiya taqqoslash SONLI (satr emas): 0.7.10 > 0.7.9
J  barmoq izi solishtiruvi farqni USHLAYDI (RESTORE_REHEARSAL_FAILED)
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from datetime import datetime, timezone

from app.api.v1.fleet import MINIMUM_POS_VERSION, version_ok


def _dt_now():
    return datetime.now(timezone.utc)
from app.models.org import Branch
from app.models.sync import SyncDevice

from tests.cash.test_fresh_tenant_launch import (  # noqa: F401  (fixture'lar bir xil)
    _fresh_company, _hex, _open, _product, _till,
)
from app.schemas.sales import SaleCreate, SaleItemIn
from app.services.sales import create_sale


# ═══ A/B) tiriklik vs tayyorlik ═════════════════════════════════════════════
def test_A_readiness_fails_when_db_is_down(monkeypatch):
    """Baza yiqilsa /health/ready 503 berishi SHART. Ilgari faqat /health bor edi va u
    bazaga tegmagani uchun Postgres o'lgan paytda ham 'ok' qaytarardi — monitoring yashil
    turib, kassalar savdo qila olmasdi."""
    from app.api.v1 import health as H

    monkeypatch.setattr(H, "_check_db", lambda: (False, False))

    class _R:
        status_code = 200
    r = _R()
    body = H.ready(r)
    assert r.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] is False


def test_B_liveness_never_touches_db(monkeypatch):
    """Tiriklik ATAYLAB bazaga tegmaydi — u 'jarayonni qayta ishga tushiraymi?' degan
    savolga javob beradi. Agar u ham bazaga tegsa, baza sekinlaganда konteyner cheksiz
    restart bo'lib, nosozlikni KUCHAYTIRARDI."""
    from app.api.v1 import health as H

    def _boom():
        raise AssertionError("liveness bazaga TEGMASLIGI kerak")
    monkeypatch.setattr(H, "_check_db", _boom)
    assert H.health()["status"] == "ok"


# ═══ C) demo seed production'da o'chiq ══════════════════════════════════════
def test_C_demo_seed_skipped_in_production(monkeypatch, capsys):
    """Production bazasiga soxta 'demo' tenant TUSHMASLIGI kerak. Bu SEED_DEMO=1 aniq
    berilmaguncha ishlamaydi — testda MIXLAB qo'yamiz (kelajakda kimdir gardni olib
    tashlasa shu yerda yiqiladi)."""
    import app.seed as S
    from app.core.config import Settings

    monkeypatch.delenv("SEED_DEMO", raising=False)
    # `settings` seed.run() ichida import qilinadi — sinf xossasini almashtiramiz.
    monkeypatch.setattr(Settings, "is_production", property(lambda self: True))
    S.run()
    out = capsys.readouterr().out
    assert "Production" in out and "o'tkazib yuborildi" in out


# ═══ D/E) cashflow — naqd xarid chiqimda ════════════════════════════════════
def _cashflow(db, emp):
    from app.api.v1.reports import cashflow
    return cashflow(period="day", emp=emp, db=db)


def test_D_cashflow_includes_cash_purchase_outflow(db, cashenv):
    """NAQD XARID ledgerga OUT·PURCHASE_OUT yozadi, LEKIN CashMovement YOZMAYDI. Shu bois u
    hisobotning chiqimida UMUMAN yo'q edi va "kassada" xarid summasicha KO'P chiqardi —
    kassirning Z-hisoboti (ledgerdan) bilan menejer hisoboti BIR kun uchun ZID edi."""
    from app.api.v1.purchases import create_purchase
    from app.models.purchasing import Supplier
    from app.schemas.purchase import PurchaseCreate, PurchaseItemIn

    co, br, emp = _fresh_company(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br, "TILL-01")
    _open(db, emp, till["id"], opening="0")
    db.commit()

    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()

    sup = Supplier(company_id=co.id, name="Ta'minotchi " + _hex())
    db.add(sup); db.flush(); db.commit()

    before = _cashflow(db, emp)
    assert before["ledger_native"] is True

    create_purchase(PurchaseCreate(
        supplier_id=sup.id, status="received",
        items=[PurchaseItemIn(product_id=prod.id, qty=3, unit_cost=10000)],
    ), emp=emp, db=db)
    db.commit()

    after = _cashflow(db, emp)
    # ASOSIY: 30 000 chiqim KO'RINDI va "kassada" AYNAN shuncha kamaydi
    assert after["out"]["naqd_xarid"] == pytest.approx(30000.0)
    assert after["out"]["jami"] - before["out"]["jami"] == pytest.approx(30000.0)
    assert before["kassada"] - after["kassada"] == pytest.approx(30000.0)
    assert after["kassada"] == pytest.approx(70000.0)      # 100 000 savdo − 30 000 xarid


def test_E_cashflow_unchanged_for_legacy_tenant(db, cashenv):
    """Legacy (migratsiya) tenantда javob shakli O'ZGARMAYDI — eski mijozlar buzilmasin."""
    from app.models.settings import Setting
    from app.services.cash.tenant import CASH_SETTING_KEY

    co, br, emp = _fresh_company(db)
    row = (db.query(Setting).filter(Setting.company_id == co.id,
                                    Setting.key == CASH_SETTING_KEY).first())
    row.value = {**(row.value or {}), "ledger_native": False}     # legacy qilib belgilaymiz
    db.commit()

    res = _cashflow(db, emp)
    assert res["ledger_native"] is False
    assert "naqd_xarid" not in res["out"]                 # yangi qator legacy'da CHIQMAYDI
    assert set(res["out"]) == {"xarajat", "inkassatsiya", "qaytarish", "beruvchiga", "jami"}


# ═══ F/G/H) qurilma telemetriyasi ═══════════════════════════════════════════
def test_F_heartbeat_records_version(db, cashenv):
    from app.api.v1.fleet import HeartbeatIn, heartbeat

    co, br, emp = _fresh_company(db)
    du = "dev-" + _hex()
    out = heartbeat(HeartbeatIn(device_uuid=du, app_version="0.7.0", app_name="pos",
                                platform="win32", pending_ops=0, failed_ops=0),
                    emp=emp, db=db)
    assert out["version_ok"] is True
    dev = db.query(SyncDevice).filter(SyncDevice.device_uuid == du).first()
    assert dev.app_version == "0.7.0" and dev.company_id == co.id
    assert dev.last_seen_at is not None


def test_G_heartbeat_branch_is_tenant_scoped(db, cashenv):
    """Qurilma BOSHQA do'konning filialini ko'rsatsa — qabul QILINMAYDI. Aks holda bir do'kon
    qurilmasi boshqa do'kon hisobotida paydo bo'lardi."""
    from app.api.v1.fleet import HeartbeatIn, heartbeat

    co, br, emp = _fresh_company(db)
    other_co, other_br, _other_emp = _fresh_company(db)      # BOSHQA do'kon
    du = "dev-" + _hex()
    heartbeat(HeartbeatIn(device_uuid=du, app_version="0.7.0", branch_id=other_br.id),
              emp=emp, db=db)
    dev = db.query(SyncDevice).filter(SyncDevice.device_uuid == du).first()
    assert dev.company_id == co.id
    assert dev.branch_id != other_br.id                      # begona filial QABUL QILINMADI


def test_H_unknown_queue_is_not_treated_as_empty(db, cashenv):
    """Server hech qachon 'navbat bo'sh' deb O'YLAB TOPMAYDI. Xabar bermagan qurilma
    `queue_state_unknown` da turadi va reliz TAYYOR EMAS deb belgilanadi — aks holda
    operator sinxronlanmagan chek turgan kassa ustidan buzuvchi reliz chiqarardi."""
    from app.api.v1.fleet import HeartbeatIn, heartbeat, list_devices

    co, br, emp = _fresh_company(db)
    du = "dev-" + _hex()
    # Versiya yuboriladi, LEKIN navbat sonlari YUBORILMAYDI
    heartbeat(HeartbeatIn(device_uuid=du, app_version="0.7.0", app_name="pos"), emp=emp, db=db)

    view = list_devices(active_only=True, emp=emp, db=db)
    row = next(r for r in view["devices"] if r["device_uuid"] == du)
    assert row["pending_ops"] is None and row["queue_known"] is False
    assert du in view["readiness"]["queue_state_unknown"]
    assert view["readiness"]["release_ready"] is False

    # Endi navbat xabar qilinadi -> tayyor
    heartbeat(HeartbeatIn(device_uuid=du, pending_ops=0, failed_ops=0), emp=emp, db=db)
    view2 = list_devices(active_only=True, emp=emp, db=db)
    assert view2["readiness"]["release_ready"] is True


def test_I_version_compare_is_numeric_not_lexicographic():
    """SATR taqqoslashda '0.7.9' > '0.7.10' bo'lardi va operator ESKI build'ni yangi deb
    o'ylardi. Taqqoslash SONLI bo'lishi SHART."""
    assert version_ok("0.7.10", "0.7.9") is True
    assert version_ok("0.7.9", "0.7.10") is False
    assert version_ok("0.7.0", MINIMUM_POS_VERSION) is True
    assert version_ok("0.6.9", MINIMUM_POS_VERSION) is False
    assert version_ok(None) is False          # NOMA'LUM versiya YETARLI EMAS (fail-closed)
    assert version_ok("v1.0.0", "0.7.0") is True


# ═══ J) barmoq izi solishtiruvi ═════════════════════════════════════════════
def test_J_fingerprint_compare_detects_loss():
    """Tiklashdan keyin bitta qator yo'qolsa ham MISMATCH bo'lishi shart — aks holda
    'tiklandi' deb yolg'on ishonch berardi."""
    from app.tools.db_fingerprint import compare

    before = {"counts": {"sales": 360, "companies": 1}, "ledger_sums": {"IN": "100.00"}}
    ok, diffs = compare(before, before)
    assert ok and not diffs

    after = {"counts": {"sales": 359, "companies": 1}, "ledger_sums": {"IN": "100.00"}}
    ok, diffs = compare(before, after)
    assert ok is False
    assert any(d["key"] == "counts.sales" and d["severity"] == "MISMATCH" for d in diffs)

    # Sanoq bir xil, LEKIN pul summasi farq qiladi — bu ham ushlanishi kerak
    after2 = {"counts": {"sales": 360, "companies": 1}, "ledger_sums": {"IN": "99.00"}}
    ok2, diffs2 = compare(before, after2)
    assert ok2 is False
    assert any(d["key"] == "ledger_sums.IN" for d in diffs2)


# ═══ K) production'ni ANIQLASH — DATABASE_URL'ga YOLG'IZ tayanmaydi ═════════
def test_K_managed_platform_counts_as_production(monkeypatch):
    """Railway'da DATABASE_URL yo'qolsa ilova JIMGINA dev rejimga tushmasligi kerak.

    Ilgari `is_production` FAQAT database_url satridan chiqarilardi. Ya'ni Postgres servisi
    uzilsa konteyner YIQILMASDAN ko'tarilib: (a) vaqtinchalik SQLite'ga yozardi — savdolar
    keyingi deploy'da yo'qolardi, (b) JWT standart OCHIQ kalit bilan imzolanardi,
    (c) /docs ochilardi, (d) demo do'kon (PIN 1234) seed qilinardi.
    Bitta yo'qolgan o'zgaruvchi ochiq internetda demo do'kon ochib qo'yardi."""
    from app.core.config import Settings

    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
              "RAILWAY_SERVICE_ID", "RAILWAY_SERVICE_NAME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")

    local = Settings()
    assert local.is_production is False          # lokal dev buzilmaydi
    assert local.production_on_sqlite is False

    # Railway konteyneri — DATABASE_URL hamon SQLite (ya'ni Postgres UZILGAN)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p-123")
    rail = Settings()
    assert rail.is_production is True            # platforma signali YETARLI
    assert rail.production_on_sqlite is True     # ...va bu HOLAT BELGILANADI


def test_L_production_on_sqlite_refuses_to_boot():
    """Bu holat JIM o'tkazilmaydi — ishga tushish TO'XTAYDI. Yiqilgan servis jimgina
    yolg'on ishlayotgan servisdan afzal (savdo yo'qolgandan ko'ra ochilmagani yaxshi).

    ALOHIDA JARAYONDA sinaladi: `app.main` import qilinishi global nojo'ya ta'sirga ega
    (settings yagona nusxa, routerlar ro'yxati), shu bois uni shu jarayonda qayta yuklash
    keyingi testlarni buzardi."""
    import subprocess
    import sys

    env = dict(os.environ)
    env.update({
        "APP_ENV": "prod",                       # aniq production
        "DATABASE_URL": "sqlite:///./_guard.db",  # ...lekin baza SQLite (DATABASE_URL buzilgan)
        # JWT gardi chalg'itmasin — kalit xavfsizlik SIYOSATIGA mos bo'lishi kerak
        # (>=32 belgi, >=8 xil belgi), aks holda test SQLite gardini emas, SECRET_KEY
        # gardini sinagan bo'lardi.
        "SECRET_KEY": "Rk7-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0cW",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    r = subprocess.run([sys.executable, "-c", "import app.main"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode != 0, "production+SQLite holatida ilova ishga TUSHMASLIGI kerak edi"
    assert "DATABASE_URL" in (r.stderr or ""), r.stderr[-500:]


# ═══ M) bir vaqtdagi heartbeat 500 bermaydi (device_uuid UNIQUE poygasi) ════
def test_M_concurrent_heartbeat_does_not_500(db, cashenv):
    """Ikki heartbeat bir vaqtda kelsa (ikki oyna / qayta urinish) ikkalasi ham "qator yo'q"
    deb INSERT qilardi va ikkinchisi UNIQUE cheklovini buzib 500 berardi. Telemetriya
    HECH QACHON kassani bezovta qilmasligi kerak."""
    from app.api.v1.fleet import HeartbeatIn, heartbeat
    from app.models.sync import SyncDevice as SD

    co, br, emp = _fresh_company(db)
    du = "dev-" + _hex()

    # Boshqa seans allaqachon qatorni yaratib qo'ygan holatni taqlid qilamiz
    db.add(SD(device_uuid=du, created_at=_dt_now()))
    db.commit()

    out = heartbeat(HeartbeatIn(device_uuid=du, app_version="0.7.0", pending_ops=3),
                    emp=emp, db=db)
    assert out["ok"] is True
    rows = db.query(SD).filter(SD.device_uuid == du).all()
    assert len(rows) == 1                      # DUBLIKAT qator YARATILMADI
    assert rows[0].pending_ops == 3
