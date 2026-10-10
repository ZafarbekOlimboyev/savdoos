# -*- coding: utf-8 -*-
"""IMTIYOZLI DEMO-TARIX MARSHRUTLARI — provisioning va yakunlash (HTTP).

Tenant BU YERDA FAQAT yangi kanonik API orqali yaratiladi — to'g'ridan-to'g'ri
ORM bilan do'kon qurilmaydi (ega talabi). Bu fayl SQLite'da ishlaydi, shu bois
finalize'ning MUVAFFAQIYATLI yo'li bu yerda YO'Q (naqd ledgeri ataylab faqat
Postgres'da). Baxtli yo'l: `tests/cash/test_demo_history_finalize_pg.py`.

A  provisioning: 200, shakl, `cash` qatori UCHINCHI shaklda
B  NC1: 'test'/'demo' bo'lmagan kod -> 400 va do'kon YARATILMAYDI
C  NC2: kod band -> 409 (mavjud do'konni qurilishga tortib kiritish yo'li yo'q)
D  yangi tenant imtiyozli tarixiy yuzaga KIRADI (haqiqiy hodisa)
E  NC3: `collection` va server-egalik maydonlari -> 422 (parserda)
F  NC4/NC5: shu tenantning O'Z tokeni bilan live POS -> 409
G  finalize: noma'lum do'kon -> 404
H  finalize: 'demo' bo'lmagan kod -> 400
I  finalize: qurilish BO'LMAGAN (ledger-native) tenant -> 409
J  finalize: journal BO'SH -> 409
K  finalize: NOL HAJM -> 409 (vakuum MATCH qabul qilinmaydi)
L  finalize: paritet TASDIQLANMASA -> 409
M  NC6: qurilish tenantida QR/tashqi to'lov marshruti YOPIQ
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

VK = {"X-Vendor-Key": "test-vendor-key"}
NOW = datetime.now(timezone.utc)
#: Tarixiy kun: `/sync/push` ning 60 kunlik oynasidan ham NARIDA.
D0 = (NOW - timedelta(days=200)).replace(hour=8, minute=0, second=0, microsecond=0)


def _kod(prefix="demo"):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _tana(code=None, **kw):
    code = code or _kod()
    out = {"company_name": "Demo Tarix", "company_code": code,
           "owner_name": "Ega", "owner_phone": f"+9967{uuid.uuid4().int % 10**8:08d}",
           "owner_password": "Zt7#mvQ2pLx9", "currency": "KGS",
           "timezone": "Asia/Bishkek", "plan_id": "plan-" + uuid.uuid4().hex[:6]}
    out.update(kw)
    return out


def _provision(client, **kw):
    return client.post("/api/v1/admin/demo-history/companies", headers=VK, json=_tana(**kw))


def _cfg(company_id):
    from app.db.session import SessionLocal
    from app.services.cash import tenant as _t
    db = SessionLocal()
    try:
        return _t.cash_config(db, uuid.UUID(str(company_id)))
    finally:
        db.close()


def _token(company_id, employee_id):
    from app.core.security import create_access_token
    return {"Authorization": "Bearer " + create_access_token(
        str(employee_id), {"role": "ega", "company_id": str(company_id), "sv": 0})}


def _hev(p, *, event_type, payload, seq=None, at=None, plan_start=False):
    return {"company_id": p["company_id"], "branch_id": p["branch_id"],
            "actor_employee_id": p["owner_id"], "plan_id": "pl-" + uuid.uuid4().hex[:8],
            "plan_start": plan_start, "occurred_at": (at or D0).isoformat(),
            "event_seq": seq or [uuid.uuid4().hex[:8]],
            "event": {"event_type": event_type, "payload": payload}}


def _finalize(client, company_id, ref="OPERATOR-ATTEST-1"):
    return client.post(f"/api/v1/admin/demo-history/{company_id}/finalize",
                       headers=VK, json={"attestation_ref": ref})


# ═══ A) provisioning ══════════════════════════════════════
def test_A_provisioning_UCHINCHI_shaklni_yozadi(client):
    r = _provision(client)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["historical_build"] is True
    for k in ("company_id", "branch_id", "owner_id", "company_code", "plan"):
        assert j.get(k), f"{k} javobda yo'q"
    assert j["build_started_at"], "build_started_at yo'q"

    cfg = _cfg(j["company_id"])
    assert cfg.get("historical_build") is True
    #  ASOSIY INVARIANT: ikkisi ham YO'Q.
    assert "ledger_native" not in cfg, cfg
    assert "cutover_at" not in cfg, cfg
    assert cfg.get("build_plan_id"), "plan_id uzatilmadi"


def test_A2_provisioning_oddiy_marshrutga_TEGMAYDI(client):
    """`POST /admin/companies` AVVALGIDEK ledger-native tenant yaratadi."""
    code = _kod("live")
    r = client.post("/api/v1/admin/companies", headers=VK, json=_tana(code=code))
    assert r.status_code == 200, r.text
    j = r.json()
    assert "historical_build" not in j, "oddiy javobga yangi maydon oqib o'tdi"
    cfg = _cfg(j["company_id"])
    assert cfg["ledger_native"] is True
    assert cfg["cutover_at"] == cfg["onboarded_at"]
    assert "historical_build" not in cfg


# ═══ B/C) NC1 va NC2 ═════════════════════════════════════
@pytest.mark.parametrize("code", ["fayzan1", "magazin7", "testo", "demoshop"])
def test_B_NC1_demo_bolmagan_kod_RAD(client, code):
    """'test'/'demo' PREFIKSI shart. `testo`/`demoshop` prefiksli -> O'TADI,
    `fayzan1`/`magazin7` -> RAD. Ya'ni test ikki tomonlama."""
    from app.db.session import SessionLocal
    from app.models.org import Company
    r = _provision(client, code=code)
    kutilgan_ok = code.startswith("test") or code.startswith("demo")
    if kutilgan_ok:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 400, r.text
    assert "test" in r.json()["detail"] and "demo" in r.json()["detail"]
    db = SessionLocal()
    try:
        assert db.query(Company).filter(Company.code == code).first() is None, \
            "rad etilgan so'rov do'kon YARATDI"
    finally:
        db.close()


def test_C_NC2_kod_band_409(client):
    code = _kod()
    assert _provision(client, code=code).status_code == 200
    r2 = _provision(client, code=code)
    assert r2.status_code == 409, r2.text


def test_C2_NC2_mavjud_LEDGER_NATIVE_tenantni_qurilishga_tortib_bolmaydi(client):
    """Oddiy yo'l bilan yaratilgan do'kon kodi bilan qurilish so'ralsa -> 409,
    va uning `cash` qatori O'ZGARMAYDI."""
    code = _kod("demo")
    r = client.post("/api/v1/admin/companies", headers=VK, json=_tana(code=code))
    assert r.status_code == 200, r.text
    oldin = _cfg(r.json()["company_id"])
    assert oldin["ledger_native"] is True

    r2 = _provision(client, code=code)
    assert r2.status_code == 409, r2.text
    assert _cfg(r.json()["company_id"]) == oldin, "haqiqiy tenant `cash` qatori o'zgardi"


# ═══ D) tarixiy yuza OCHIQ ════════════════════════════════
def test_D_yangi_tenant_tarixiy_yuzaga_KIRADI(client):
    """Blokerning yopilgani: API bilan yaratilgan demo tenant tarixiy
    backfill'ga KIRA OLADI (ilgari `cutover_at = now` sababli 409 edi)."""
    p = _provision(client).json()
    r = client.post("/api/v1/historical/events", headers=VK,
                    json=_hev(p, event_type="shift_open",
                              payload={"opening_cash": 1000},
                              seq=["d1", "open"], plan_start=True))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["event_type"] == "shift_open"
    assert j["result_type"] == "shift"

    #  Vaqt AYNAN tarixiy bo'lsin (hozirgi vaqt EMAS).
    from app.db.session import SessionLocal
    from app.models.shifts import Shift
    db = SessionLocal()
    try:
        sh = db.get(Shift, uuid.UUID(j["result_id"]))
        assert sh is not None
        opened = sh.opened_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        assert abs((opened - D0).total_seconds()) < 2, f"{opened} != {D0}"
    finally:
        db.close()


# ═══ E) NC3 — parser allowlist ══════════════════════════════
def test_E_NC3_collection_va_server_egalik_maydoni_422(client):
    p = _provision(client).json()
    #  `collection` ATAYLAB allowlist'dan tashqarida.
    r1 = client.post("/api/v1/historical/events", headers=VK,
                     json=_hev(p, event_type="collection", payload={"amount": 100}))
    assert r1.status_code == 422, r1.text
    #  Server-egalik maydoni DTO darajasida rad etiladi.
    env = _hev(p, event_type="shift_open", payload={"opening_cash": 1})
    env["event"]["payload"]["client_uuid"] = str(uuid.uuid4())
    r2 = client.post("/api/v1/historical/events", headers=VK, json=env)
    assert r2.status_code == 422, r2.text


# ═══ F) NC4/NC5 — live oqim YOPIQ ═══════════════════════════
def test_F_NC4_NC5_qurilish_tenantida_live_POS_YOPIQ(client):
    """Tenant O'Z tokeni bilan ham normal savdo/smena YOZA OLMAYDI."""
    p = _provision(client).json()
    h = _token(p["company_id"], p["owner_id"])
    for yol in ("/api/v1/sales", "/api/v1/shifts/open", "/api/v1/cash/ops",
                "/api/v1/sync/push", "/api/v1/returns", "/api/v1/purchases",
                "/api/v1/inventory/writeoff"):
        r = client.post(yol, json={}, headers=h)
        assert r.status_code == 409, f"{yol}: {r.status_code} {r.text[:160]}"
        assert r.headers.get("X-Error-Code") == "HISTORICAL_BUILD_LOCKED", yol


def test_F2_sozlash_marshrutlari_OCHIQ(client):
    """Qurilish uchun kerak bo'lgan sozlash yuzasi bloklanmaydi — aks holda
    TILL yaratib bo'lmas va ledger legi yozilmasdi."""
    p = _provision(client).json()
    h = _token(p["company_id"], p["owner_id"])
    r = client.post("/api/v1/tills", json={}, headers=h)
    #  422/400 — tana validatsiyasi; MUHIMI: 409 qurilish bloki EMAS.
    assert r.status_code != 409, r.text
    assert r.headers.get("X-Error-Code") != "HISTORICAL_BUILD_LOCKED"


# ═══ M) NC6 — tashqi ta'sir ═══════════════════════════════
def test_M_NC6_tashqi_tolov_marshruti_YOPIQ(client):
    p = _provision(client).json()
    h = _token(p["company_id"], p["owner_id"])
    r = client.post("/api/v1/payments/qr", json={}, headers=h)
    assert r.status_code == 409, r.text
    assert r.headers.get("X-Error-Code") == "HISTORICAL_BUILD_LOCKED"
    r2 = client.get(f"/api/v1/payments/qr/{uuid.uuid4()}", headers=h)
    assert r2.status_code == 409, r2.text


# ═══ G–L) finalize rad etishlari ════════════════════════════
# ═══ O) NC8 — darvoza TUR-MUSTAQIL (strukturaviy isbot) ════════════════════
def test_O_NC8_darvoza_TUR_MUSTAQIL_strukturaviy():
    """Darvoza 12 turdan HECH BIRIGA bog'liq emas — bu STRUKTURADAN kelib chiqadi.

    ⚠️  NEGA STRUKTURAVIY ISBOT KERAK. "12 turni birma-bir sinash" o'zi
        yetarli emas: yaroqsiz tana DTO qurilishida yiqilib darvozaga UMUMAN
        yetmasligi mumkin, va test "hammasi rad etildi" deb yolg'on
        ko'rsatardi. Bu yerda esa darvozaning POZITSIYASI o'lchanadi:
        `assert_demo_tenant` `historical_event` tanasida AYNAN BIR MARTA,
        SHARTSIZ va jurnal rezervatsiyasidan ham, dispatch'dan ham OLDIN
        chaqiriladi — demak hodisa turi QANDAY bo'lsa ham o'zgarmaydi.

    Xulq tomoni: `tests/cash/test_demo_history_finalize_pg.py::test_C_NC8_...`
    (12/12, hammasi DTO'dan o'tadigan namuna bilan).
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "api" / "v1" / "historical_exec.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "historical_event")

    def _qatorlar(nom):
        out = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                atalgan = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if atalgan == nom:
                    out.append(n.lineno)
        return out

    gard = _qatorlar("assert_demo_tenant")
    jurnal = _qatorlar("claim")
    dispatch = _qatorlar("_bajar")
    mavjud = _qatorlar("_mavjud_kalit")

    assert len(gard) == 1, f"darvoza {len(gard)} marta chaqirilgan: {gard}"
    assert jurnal and dispatch and mavjud, (jurnal, dispatch, mavjud)
    #  Darvoza REZERVATSIYADAN OLDIN: aks holda allaqachon `done` kalit
    #  saqlangan javobni qaytarib, finalize'dan keyin ham "muvaffaqiyat"
    #  ko'rsatardi.
    assert gard[0] < min(jurnal), (gard, jurnal)
    assert gard[0] < min(mavjud), (gard, mavjud)
    #  Darvoza YOZUVCHIDAN OLDIN.
    assert gard[0] < min(dispatch), (gard, dispatch)

    #  SHARTSIZ: chaqiruv funksiya tanasining TO'G'RIDAN-TO'G'RI bayonoti,
    #  `if`/`for`/`try` ichida EMAS.
    tanada = False
    for st in fn.body:
        for n in ast.walk(st):
            if isinstance(n, ast.Call):
                f = n.func
                if (f.attr if isinstance(f, ast.Attribute) else None) == "assert_demo_tenant":
                    tanada = isinstance(st, (ast.Expr, ast.Assign, ast.AnnAssign))
    assert tanada, "darvoza shartli blok ichida — tur/holatga bog'liq bo'lib qolardi"


# ═══ N) MUHIT DARVOZASI — production'ga TEGILMAYDI ═════════════════════════
@pytest.mark.parametrize("yol,tana", [
    ("/api/v1/admin/demo-history/companies", None),
    (f"/api/v1/admin/demo-history/{uuid.uuid4()}/finalize", {"attestation_ref": "x"}),
])
def test_N_muhit_RAD_etsa_403(client, monkeypatch, yol, tana):
    """`environment_allows_apply` tuple qaytaradi va FAIL-CLOSED: `APP_ENV`
    yo'q bo'lsa `"unknown"` o'qiladi va ruxsat berilmaydi. Shu bois ikki
    marshrut ham production muhitida 403 beradi."""
    monkeypatch.setattr("app.services.migrator_1c.guard.environment_allows_apply",
                        lambda: (False, "production"))
    r = client.post(yol, headers=VK, json=(tana if tana is not None else _tana()))
    assert r.status_code == 403, r.text
    assert "production" in r.json()["detail"]


def test_N2_muhit_darvozasi_TUPLE_sifatida_ochiladi(client, monkeypatch):
    """⚠️  `if not environment_allows_apply()` HECH QACHON ishlamasdi — bo'sh
    bo'lmagan tuple doim truthy. Bu test o'sha nuqson sinfini qulflaydi:
    darvoza `(False, ...)` ni haqiqatan RAD etsin."""
    chaqirildi = {"n": 0}

    def _fake():
        chaqirildi["n"] += 1
        return (False, "test-sabab")

    monkeypatch.setattr("app.services.migrator_1c.guard.environment_allows_apply", _fake)
    r = _provision(client)
    assert r.status_code == 403, r.text
    assert chaqirildi["n"] == 1, "darvoza chaqirilmadi"
    assert "test-sabab" in r.json()["detail"]


def test_N3_finalize_attestatsiya_SHART(client):
    """Operator tasdig'i QAYD etiladi; yo'q bo'lsa so'rov qabul qilinmaydi."""
    p = _provision(client).json()
    r = client.post(f"/api/v1/admin/demo-history/{p['company_id']}/finalize",
                    headers=VK, json={})
    assert r.status_code == 422, r.text
    r2 = client.post(f"/api/v1/admin/demo-history/{p['company_id']}/finalize",
                     headers=VK, json={"attestation_ref": ""})
    assert r2.status_code == 422, r2.text


def test_G_finalize_nomalum_dokon_404(client):
    r = _finalize(client, uuid.uuid4())
    assert r.status_code == 404, r.text


def test_G2_finalize_yaroqsiz_uuid_400(client):
    r = _finalize(client, "not-a-uuid")
    assert r.status_code == 400, r.text


def test_H_finalize_demo_bolmagan_kod_400(client):
    """Qurilish o'rtasida kodi o'zgartirilgan tenant JIM yakunlanmaydi."""
    from app.db.session import SessionLocal
    from app.models.org import Company
    p = _provision(client).json()
    db = SessionLocal()
    try:
        co = db.get(Company, uuid.UUID(p["company_id"]))
        co.code = "fayzan" + uuid.uuid4().hex[:6]
        db.commit()
    finally:
        db.close()
    r = _finalize(client, p["company_id"])
    assert r.status_code == 400, r.text
    assert "demo" in r.json()["detail"]


def test_I_finalize_qurilish_BOLMAGAN_tenant_409(client):
    code = _kod("demo")
    p = client.post("/api/v1/admin/companies", headers=VK, json=_tana(code=code)).json()
    r = _finalize(client, p["company_id"])
    assert r.status_code == 409, r.text
    assert "HISTORICAL_BUILD holatida emas" in r.json()["detail"]


def test_J_finalize_journal_BOSH_409(client):
    p = _provision(client).json()
    r = _finalize(client, p["company_id"])
    assert r.status_code == 409, r.text
    assert "Tarixiy hodisa YO'Q" in r.json()["detail"]
    #  Holat O'ZGARMADI.
    assert _cfg(p["company_id"]).get("historical_build") is True


def _jurnal_qatori(company_id, branch_id, actor_id, *, status, at, plan="pl-x"):
    """Jurnal qatorini TO'G'RIDAN-TO'G'RI yozadi — darvozani sinash uchun.

    `POST /historical/events` orqali `started`/`failed` holatini ATAYLAB
    yasash mumkin emas (yozuvchi yiqilishini talab qilardi), shu bois
    darvozaning bu yarmi faqat shunday o'lchanadi."""
    import uuid as _u

    from app.db.session import SessionLocal
    from app.models.historical import HistoricalPlanEvent
    db = SessionLocal()
    try:
        row = HistoricalPlanEvent(
            company_id=uuid.UUID(str(company_id)), branch_id=uuid.UUID(str(branch_id)),
            actor_employee_id=uuid.UUID(str(actor_id)), plan_id=plan,
            event_type="cash_payin", event_key=_u.uuid4(), occurred_at=at,
            status=status, payload_hash="0" * 64, hash_version=1, payload={})
        db.add(row)
        db.commit()
        return row.event_key
    finally:
        db.close()


def test_P_finalize_journal_TUGALLANMAGAN_qator_bilan_409(client):
    """Darvozaning IKKINCHI yarmi: `status != done` qator bo'lsa yakunlash RAD.

    ⚠️  Ilgari faqat BO'SH journal yarmi sinalgan edi (adversarial ko'rik topdi).
    """
    p = _provision(client).json()
    for st in ("started", "failed"):
        _jurnal_qatori(p["company_id"], p["branch_id"], p["owner_id"],
                       status=st, at=D0 + timedelta(hours=2))
        r = _finalize(client, p["company_id"])
        assert r.status_code == 409, f"{st}: {r.status_code} {r.text[:200]}"
        assert "tugallanmagan" in r.json()["detail"], r.json()["detail"]
    #  Holat O'ZGARMADI.
    cfg = _cfg(p["company_id"])
    assert cfg.get("historical_build") is True
    assert "cutover_at" not in cfg


def test_Q_YAKUNLANGAN_tenantda_takror_SOF_OQISH_va_ABADIY_409_YO_Q(client):
    """⚠️  REGRESSIYA: yakunlangandan keyin journalga qator qo'shilsa ham takror
        chaqiruv 200 `duplicate` bo'lishi SHART.

    Ilgari takror yo'l T0 ni QAYTA HISOBLARDI. Yakunlangandan keyin journal
    o'sib ketsa (poyga yoki qo'lda tuzatish), qayta hisoblangan T0 saqlangandan
    FARQ qilardi va `finalize_historical_build` «boshqa T0» deb 409 berardi —
    ya'ni muvaffaqiyatli yakunlangan tenant ABADIY 409 holatiga tushardi.
    Endi takror yo'l SOF O'QISH: saqlangan holat qaytariladi.
    """
    from app.db.session import SessionLocal
    from app.services.cash import tenant as _t

    p = _provision(client).json()
    r = client.post("/api/v1/historical/events", headers=VK,
                    json=_hev(p, event_type="shift_open", payload={"opening_cash": 0},
                              seq=["d1", "open"], plan_start=True))
    assert r.status_code == 200, r.text

    #  Yakunlashni SERVIS orqali qilamiz: marshrut yo'li SQLite'da paritetni
    #  isbotlay olmasdi (503), lekin TAKROR yo'li paritetdan OLDIN turadi.
    t0 = D0 + timedelta(hours=1)
    db = SessionLocal()
    try:
        _t.finalize_historical_build(db, uuid.UUID(p["company_id"]), t0=t0)
        db.commit()
    finally:
        db.close()

    r1 = _finalize(client, p["company_id"])
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["duplicate"] is True and j1["finalized"] is True
    assert j1["cutover_at"] == t0.isoformat(), j1

    #  JOURNAL O'SDI — AYNAN tuzoqni yasaymiz (yangi max(occurred_at)).
    _jurnal_qatori(p["company_id"], p["branch_id"], p["owner_id"],
                   status="done", at=t0 + timedelta(days=1))
    r2 = _finalize(client, p["company_id"])
    assert r2.status_code == 200, f"ABADIY 409 tuzog'i qaytdi: {r2.status_code} {r2.text[:200]}"
    assert r2.json()["duplicate"] is True
    assert r2.json()["cutover_at"] == t0.isoformat(), "saqlangan T0 o'zgardi"


def test_R_products_bulk_ATALGAN_istisno_va_uning_CHEGARASI():
    """`/products/bulk` qurilish davomida OCHIQ — mahsulot yaratishning yagona
    yo'li. LEKIN `stock > 0` berilsa u HOZIRGI vaqt bilan `StockMovement`
    yozadi, ya'ni qoidaning («zaxira harakati hujjati yozilmaydi») chegarasida
    turadi. Bu test istisnoni ATAYLAB ekanini va reja sharti hujjatlanganini
    qulflaydi (adversarial ko'rik topilmasi).
    """
    import inspect
    import pathlib

    from app.core import subscription_routes as SR

    anahtar = ("POST", "/products/bulk")
    assert anahtar in SR.HISTORICAL_BUILD_SETUP_OPEN, "istisno olib tashlangan"
    sinf = SR.SUBSCRIPTION_ROUTE_ACTIONS[anahtar]
    assert SR.blocked_during_historical_build(sinf, anahtar) is False

    #  Chegara MANBADA hujjatlangan bo'lsin — izohsiz istisno keyingi o'quvchi
    #  uchun nuqsonga aylanadi.
    src = pathlib.Path(inspect.getfile(SR)).read_text(encoding="utf-8")
    assert "stock > 0" in src and "stock = 0" in src, \
        "istisnoning chegarasi manbada yozilmagan"
    assert "product_create" in src

    #  Va yozuvchi haqiqatan shunday ishlasin: `stock` shartli.
    psrc = (pathlib.Path(inspect.getfile(SR)).parents[1]
            / "api" / "v1" / "products.py").read_text(encoding="utf-8")
    assert "if row.stock and row.stock > 0:" in psrc, \
        "products.py o'zgardi — istisnoning chegarasi qayta o'lchanishi kerak"


def test_K_naqd_quyi_tizimi_YOQ_bolsa_finalize_FAIL_CLOSED_503(client):
    """SQLite'da `cash` sxemasi YO'Q — paritetni ISBOTLAB BO'LMAYDI.

    ⚠️  To'g'ri javob 503, 409 ham, 200 ham EMAS: isbotsiz yakunlash T0'ni
        ABADIY qo'yib yuborardi (qaytish yo'li yo'q). Bu `services/sales.py`
        va `reports.py` bilan AYNI kontrakt: `CASH_LEDGER_UNAVAILABLE`.
    """
    p = _provision(client).json()
    r = client.post("/api/v1/historical/events", headers=VK,
                    json=_hev(p, event_type="shift_open", payload={"opening_cash": 5000},
                              seq=["d1", "open"], plan_start=True))
    assert r.status_code == 200, r.text

    rf = _finalize(client, p["company_id"])
    assert rf.status_code == 503, rf.text
    assert rf.headers.get("X-Error-Code") == "CASH_LEDGER_UNAVAILABLE"
    #  HOLAT O'ZGARMADI — yarim o'tish YO'Q.
    cfg = _cfg(p["company_id"])
    assert cfg.get("historical_build") is True
    assert "cutover_at" not in cfg and "ledger_native" not in cfg


# ═══ L) PARITET HUKMI — SOF FUNKSIYA (bazasiz) ═════════════════════════════
#  `compare_tenant` naqd sxemasini talab qiladi (Postgres), lekin HUKM sof —
#  shu bois vakuum MATCH va qo'shni holatlar SHU YERDA o'lchanadi.
def _rep(**kw):
    base = {"status": "MATCH", "divergent_part_count": 0, "abs_delta": 0.0,
            "legacy_in": 100.0, "legacy_out": 0.0,
            "ledger_in": 100.0, "ledger_out": 0.0,
            "parts": [{"account_count": 1, "status": "MATCH", "delta": 0.0}]}
    base.update(kw)
    return base


def test_L_paritet_hukmi_YAXSHI_holat():
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    ok, sabab = v(_rep())
    assert ok is True, sabab


def test_L2_VAKUUM_struktura_bilan_rad_etiladi():
    """⚠️  ASOSIY: `_rollup` BO'SH `parts` uchun ham MATCH qaytaradi.

    Vakuum STRUKTURA bilan yopiladi (filial + naqd hisob mavjudligi), HAJM
    bilan emas — chunki nol hajm qonuniy ham bo'lishi mumkin (L4 ga qarang).
    """
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    #  Nol filial — `_rollup("tenant", ..., [])` AYNAN shuni beradi.
    ok, sabab = v(_rep(parts=[]))
    assert ok is False and "filial" in sabab, sabab
    #  Filial bor, lekin naqd hisob YO'Q -> ledger tomoni umuman mavjud emas.
    ok2, s2 = v(_rep(parts=[{"account_count": 0, "status": "MATCH", "delta": 0.0}]))
    assert ok2 is False and "naqd hisob" in s2, s2


def test_L3_BIR_TOMONLAMA_hajm_rad_etiladi():
    """TILL aniqlanmasa `on_cash_sale` JIM `None` qaytaradi: legacy>0, ledger=0.

    Bu holat `status` bilan ham ushlanishi KERAK (delta != 0), lekin filial
    ICHIDAGI qarama-qarshi xatolar `delta` ni nolga bekor qilishi mumkin
    (`compare_branch` filialni BITTA skalyarga keltiradi). Shu bois bir
    tomonlama hajm ALOHIDA tekshiriladi.
    """
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    for kw in ({"legacy_in": 5000.0, "ledger_in": 0.0},
               {"legacy_in": 0.0, "ledger_in": 5000.0},
               {"legacy_in": 0.0, "ledger_in": 0.0, "legacy_out": 500.0},
               {"legacy_in": 0.0, "ledger_in": 0.0, "ledger_out": 500.0}):
        ok, sabab = v(_rep(**kw))
        assert ok is False and "BIR TOMONLAMA" in sabab, (kw, sabab)


def test_L6_NAQDSIZ_karta_only_reja_QONUNIY_otadi():
    """⚠️  Bu men qo'ygan haddan tashqari qattiq shartning TUZATISHI.

    Faqat karta bilan savdo qilgan demo reja qonuniy: ikki tomon ham
    HAQIQATAN nol va bu TO'G'RI javob. Ilgari "ikki tomonda ham hajm > 0"
    talab qilingan edi — bunday rejani ABADIY yakunlanmaydigan holatda
    qoldirardi. Vakuum endi struktura bilan yopiladi.
    """
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    ok, sabab = v(_rep(legacy_in=0.0, legacy_out=0.0, ledger_in=0.0, ledger_out=0.0))
    assert ok is True, sabab
    assert "naqd harakati YO'Q" in sabab, sabab


@pytest.mark.parametrize("kw", [{"status": "REVIEW"}, {"status": "BLOCK"},
                                {"divergent_part_count": 1},
                                {"status": None}])
def test_L4_nomuvofiq_status_rad_etiladi(kw):
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    ok, _ = v(_rep(**kw))
    assert ok is False


def test_L5_hukm_SOF_bazasiz_ishlaydi():
    """Hukm I/O qilmaydi — shu bois sintetik dict bilan o'lchanadi (bu testning
    o'zi isbot) va yaroqsiz kirish ham 500 bermaydi."""
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    for yomon in (None, [], "", 0, {"parts": [{}]}):
        ok, sabab = v(yomon)
        assert ok is False and isinstance(sabab, str) and sabab
