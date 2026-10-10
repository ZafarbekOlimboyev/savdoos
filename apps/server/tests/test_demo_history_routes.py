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
            "legacy_in": 100.0, "ledger_in": 100.0,
            "parts": [{"account_count": 1, "status": "MATCH", "delta": 0.0}]}
    base.update(kw)
    return base


def test_L_paritet_hukmi_YAXSHI_holat():
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    ok, sabab = v(_rep())
    assert ok is True, sabab


def test_L2_VAKUUM_MATCH_rad_etiladi():
    """⚠️  ASOSIY: `_rollup` nol filial/hisob/leg uchun ham MATCH qaytaradi."""
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    #  Nol filial — `_rollup("tenant", ..., [])` AYNAN shuni beradi.
    ok, sabab = v(_rep(parts=[]))
    assert ok is False and "filial" in sabab, sabab
    #  Nol hajm, status hali ham MATCH.
    ok2, s2 = v(_rep(legacy_in=0.0, ledger_in=0.0))
    assert ok2 is False and "NOL HAJM" in s2, s2
    #  Hisob yo'q: legacy harakatlangan, ledger tomoni MAVJUD EMAS.
    ok3, s3 = v(_rep(parts=[{"account_count": 0, "status": "MATCH", "delta": 0.0}]))
    assert ok3 is False, s3


def test_L3_BIR_TOMONLAMA_hajm_rad_etiladi():
    """TILL aniqlanmasa `on_cash_sale` JIM `None` qaytaradi: legacy>0, ledger=0."""
    from app.services.cash.shadow_compare import finalize_parity_verdict as v
    ok, sabab = v(_rep(legacy_in=5000.0, ledger_in=0.0))
    assert ok is False and "NOL HAJM" in sabab, sabab
    ok2, s2 = v(_rep(legacy_in=0.0, ledger_in=5000.0))
    assert ok2 is False, s2


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
