# -*- coding: utf-8 -*-
"""VAQT ZONASI TASDIG'I — PARTIYA DARVOZASI ORTIDA (Phase 5B, A).

⚠️  NEGA. `/lots/enable` production'da 403 edi, `/lots/timezone/confirm` esa
    darvozasiz qolgan edi: ega yoki administrator production'da
    `settings.catalog` qatorini (1C cutover holati) yaratar yoki butun
    lug'atni qaytarib yozardi — partiya kuzatuvi uxlab turgan paytda. Tasdiqni
    u yerda o'qiydigan hech kim yo'q, lekin migrator izi, production dalili
    («settings.catalog yo'q») va GET /settings o'zgarardi, API orqali esa uni
    qaytarib bo'lmasdi.

Bu fayl isbotlaydi (SQLite):
  · production shaklidagi HAR muhitda tasdiq 403, `settings` va audit BAYT-BAYT o'zgarmagan;
  · darvoza filial qidiruvidan OLDIN — begona yoki yo'q filial ham 403 (404 emas);
  · `/lots/enable` va tasdiq AYNI darvozaga tayanadi;
  · darvoza ochiq: tasdiq -> enable(track_expiry) 200, tasdiqsiz 409 (MANFIY NAZORAT);
  · takroriy tasdiq no-op; katalog cutover kalitlariga TEGMAYDI, eskirgan nusxa ham qaytarmaydi;
  · yaroqsiz zona 400, o'chirilgan yoki begona filial 404 — yozuvsiz;
  · ruxsat matritsasi — darvoza ochiq va yopiq;
  · rad etilgan tasdiq migrator izini o'zgartirmaydi.

Parallel yozuvlar (FOR UPDATE, birinchi INSERT poygasi) — `test_lot_tz_confirm_pg.py`:
SQLite qulfni umuman bilmaydi.

⚠️  HAR SINOV O'Z DO'KONIDA. Umumiy seed do'konining tarifi 10 foydalanuvchi va
    `_staff` keshi boshqa fayllar bilan umumiy — rol va override sinovlari
    xodimni shu yerda, alohida do'konda yaratadi.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Text, cast

from app.core.security import create_access_token
from app.models.auth import Employee, EmployeePermission, Permission, Role
from app.models.enums import EmployeeStatus
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.sync import AuditLog
from app.services import catalog_import_v2 as civ2
from app.services import lot_policy as LP

CONFIRM = "/api/v1/lots/timezone/confirm"
ENABLE = "/api/v1/lots/enable"
AVAIL = "/api/v1/lots/availability"
TZ = "Asia/Tashkent"

# ⚠️  JONLI PRODUCTION'NING O'ZI HAM SHU RO'YXATDA: `APP_ENV` umuman YO'Q muhit.
#     Platforma belgisi esa `APP_ENV=dev` dan USTUN.
PROD_SHAPED = [
    pytest.param({"APP_ENV": "production"}, id="production"),
    pytest.param({"APP_ENV": "prod"}, id="prod"),
    pytest.param({"APP_ENV": "PRODUCTION"}, id="PRODUCTION"),
    pytest.param({"APP_ENV": ""}, id="bosh"),
    pytest.param({"APP_ENV": None}, id="APP_ENV_yoq"),
    pytest.param({"APP_ENV": "boshqa"}, id="boshqa"),
    pytest.param({"APP_ENV": "dev", "RAILWAY_ENVIRONMENT_NAME": "production"},
                 id="dev_railway_production"),
    pytest.param({"APP_ENV": "dev", "RAILWAY_ENVIRONMENT_NAME": "prod"}, id="dev_railway_prod"),
]


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _muhit(monkeypatch, env):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    # Do'kon×filial ro'yxati bu faylda YO'Q — u `test_lot_activation_scope.py` da.
    monkeypatch.delenv(LP.LOT_ACTIVATION_SCOPES_ENV, raising=False)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _ochiq(monkeypatch):
    _muhit(monkeypatch, {"APP_ENV": "dev"})


def _darvoza_matni():
    """Joriy muhitda darvoza AYNAN qaysi matn bilan rad etadi (yangi matn yo'q)."""
    with pytest.raises(LP.LotActivationNotAllowed) as ei:
        LP.assert_activation_allowed()
    return str(ei.value)


def _xodim(db, cid, role, allow=()):
    r = db.query(Role).filter(Role.code == role).one()
    e = Employee(id=uuid.uuid4(), company_id=cid, role_id=r.id, full_name=f"TZ {role}",
                 phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                 status=EmployeeStatus.active, sec_epoch=0)
    db.add(e)
    db.flush()
    for code in allow:
        p = db.query(Permission).filter(Permission.code == code).one()
        db.add(EmployeePermission(employee_id=e.id, permission_id=p.id, allowed=True))
    tok = create_access_token(str(e.id), {"role": role, "company_id": str(cid), "sv": 0})
    return {"Authorization": f"Bearer {tok}"}


def _dokon(tz=TZ, catalog=None, role="ega", allow=()):
    """Toza do'kon + filial + xodim. `settings.catalog` qatori YO'Q (yoki aynan `catalog`)."""
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="TZ tasdiq", code="tz" + uuid.uuid4().hex[:8],
                       currency="UZS")
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01", timezone=tz)
        db.add(br)
        db.flush()
        H = _xodim(db, comp.id, role, allow)
        if catalog is not None:
            db.add(Setting(company_id=comp.id, branch_id=None, key="catalog", value=catalog))
        db.commit()
        return {"cid": comp.id, "code": comp.code, "bid": br.id, "H": H}


def _iz(cid):
    """Tasdiq yozishi mumkin bo'lgan HAMMA narsa.

    `settings` — qiymat bazadagi MATNI va `row_version` bilan (mavjud qatorni
    qayta yozish ham yozuv); audit — `expiry_timezone` qatorlari, filialdan qat'i
    nazar (begona filial id'si bilan yozilgan qator ham ko'rinsin).
    """
    with _db() as db:
        sozlama = sorted(
            (k, str(b), v, int(rv or 0)) for k, b, v, rv in
            db.query(Setting.key, Setting.branch_id, cast(Setting.value, Text),
                     Setting.row_version).filter(Setting.company_id == cid).all())
        audit = [(str(a.entity_id), a.before, a.after) for a in
                 db.query(AuditLog).filter(AuditLog.entity == "expiry_timezone")
                 .order_by(AuditLog.id).all()]
    return {"settings": sozlama, "audit": audit}


def _catalog_qatori(cid):
    with _db() as db:
        return db.query(Setting).filter(Setting.company_id == cid, Setting.branch_id.is_(None),
                                        Setting.key == "catalog").one_or_none()


def _audit(bid):
    with _db() as db:
        return db.query(AuditLog).filter(AuditLog.entity == "expiry_timezone",
                                         AuditLog.entity_id == bid).order_by(AuditLog.id).all()


def _mahsulot(client, H):
    r = client.post("/api/v1/products/bulk", headers=H, json={"items": [
        {"name": f"TZ sinov {uuid.uuid4().hex[:8]}", "sell_price": 1000, "buy_price": 700,
         "unit_code": "dona", "stock": 0}]})
    assert r.status_code in (200, 201), r.text
    return r.json()[0]["id"]


def _enable(client, H, pid, bid, **kw):
    return client.post(ENABLE, headers=H, json={
        "product_id": pid, "branch_id": str(bid), "reason": "sinov: zona tasdig'i", **kw})


def _filial_holati(client, H, bid):
    av = client.get(AVAIL, headers=H)
    assert av.status_code == 200, av.text
    j = av.json()
    return j, next(b for b in j["branches"] if b["id"] == str(bid))


# ══ 1. PRODUCTION SHAKLIDAGI MUHIT — RAD, YOZUVSIZ ═══════════════════════════

@pytest.mark.parametrize("env", PROD_SHAPED)
def test_PRODUCTION_shaklidagi_muhitda_TASDIQ_403_va_HECH_NARSA_yozilmaydi(client, monkeypatch, env):
    """REGRESSIYA: ilgari 200 qaytib, `settings.catalog` qatorini YARATARDI.

    Do'konda katalog qatori ATAYLAB yo'q — «qiymat o'zgarmadi» emas, «qator
    umuman PAYDO BO'LMADI» isbotlanadi (production dalili aynan shu).
    """
    t = _dokon()
    _muhit(monkeypatch, env)
    matn = _darvoza_matni()
    oldin = _iz(t["cid"])
    for body in ({}, {"branch_id": str(t["bid"])}):
        r = client.post(CONFIRM, headers=t["H"], json=body)
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == matn
    assert _iz(t["cid"]) == oldin
    assert _catalog_qatori(t["cid"]) is None
    assert _audit(t["bid"]) == []


@pytest.mark.parametrize("env", [pytest.param({"APP_ENV": "production"}, id="production"),
                                 pytest.param({"APP_ENV": None}, id="APP_ENV_yoq")])
def test_DARVOZA_filial_qidiruvidan_OLDIN_begona_va_yoq_filial_ham_403(client, monkeypatch, env):
    """404 bo'lganda javob filial MAVJUDLIGINI oshkor qilardi va darvoza qidiruvdan
    keyin turgan bo'lardi."""
    t, begona = _dokon(), _dokon()
    _muhit(monkeypatch, env)
    oldin = (_iz(t["cid"]), _iz(begona["cid"]))
    for bid in (uuid.uuid4(), begona["bid"]):
        r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(bid)})
        assert r.status_code == 403, r.text
        assert "YOQILMAYDI" in r.json()["detail"]
    assert (_iz(t["cid"]), _iz(begona["cid"])) == oldin


def test_enable_va_tasdiq_AYNI_darvozaga_tayanadi(client, monkeypatch):
    """Kelajakda darvoza (masalan, tenant bo'yicha) faqat bittasiga qo'shilsa — QIZIL."""
    t = _dokon()
    _ochiq(monkeypatch)
    pid = _mahsulot(client, t["H"])
    # Darvoza endi (do'kon, filial) oladi — soxta ham istalgan argumentni qabul qiladi.
    monkeypatch.setattr(LP, "activation_allowed", lambda *a, **k: False)
    oldin = _iz(t["cid"])
    e = _enable(client, t["H"], pid, t["bid"])
    c = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert (e.status_code, c.status_code) == (403, 403), (e.text, c.text)
    assert e.json()["detail"] == c.json()["detail"]
    assert _iz(t["cid"]) == oldin
    # NAZORAT: darvoza qaytgach ikkalasi ham o'tadi — 403 boshqa sababdan emas.
    monkeypatch.undo()
    _ochiq(monkeypatch)
    assert client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])}).status_code == 200
    assert _enable(client, t["H"], pid, t["bid"]).status_code == 200


def test_rad_etilgan_tasdiqdan_keyin_AVAILABILITY_ozgarmaydi(client, monkeypatch):
    """Ilgari rad etilmagan tasdiq `timezone_confirmed` ni jimgina TRUE qilardi."""
    t = _dokon()
    _muhit(monkeypatch, {"APP_ENV": None})
    j0, b0 = _filial_holati(client, t["H"], t["bid"])
    assert j0["activation_allowed"] is False and b0["timezone_confirmed"] is False
    assert client.post(CONFIRM, headers=t["H"], json={}).status_code == 403
    j1, b1 = _filial_holati(client, t["H"], t["bid"])
    assert j1["activation_allowed"] is False
    assert b1 == b0
    assert j1["section_visible"] is False and j1["section_visible"] == j0["section_visible"]


# ══ 2. DARVOZA OCHIQ — MANFIY NAZORAT ════════════════════════════════════════

def test_OCHIQ_darvozada_tasdiq_200_va_muddat_kuzatuvi_yoqiladi_TASDIQSIZ_409(client, monkeypatch):
    """Usiz yuqoridagi 403 sinovlari tasdiq HAMMA JOYDA buzilganda ham yashil bo'lardi."""
    t = _dokon()
    _ochiq(monkeypatch)
    pid = _mahsulot(client, t["H"])
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True)
    assert r.status_code == 409, r.text
    assert "TASDIQLANMAGAN" in r.text

    c = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert c.status_code == 200, c.text
    assert c.json() == {"ok": True, "branch_id": str(t["bid"]), "timezone": TZ,
                        "confirmed": True, "changed": True}
    assert _catalog_qatori(t["cid"]).value[LP.CONFIRM_FIELD] == {str(t["bid"]): TZ}
    assert _filial_holati(client, t["H"], t["bid"])[1]["timezone_confirmed"] is True

    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True)
    assert r.status_code == 200, r.text
    assert r.json()["track_expiry"] is True


def test_TAKROR_tasdiq_NO_OP_row_version_ozgarmaydi_audit_BITTA(client, monkeypatch):
    """Ilgari har chaqiruv `row_version` ni oshirib, yana bitta audit qatori yozardi."""
    t = _dokon()
    _ochiq(monkeypatch)
    body = {"branch_id": str(t["bid"])}
    a = client.post(CONFIRM, headers=t["H"], json=body)
    assert a.status_code == 200 and a.json()["changed"] is True, a.text
    oldin = _iz(t["cid"])
    b = client.post(CONFIRM, headers=t["H"], json=body)
    assert b.status_code == 200 and b.json()["changed"] is False, b.text
    assert b.json()["confirmed"] is True
    assert _iz(t["cid"]) == oldin
    au = _audit(t["bid"])
    assert len(au) == 1
    assert (au[0].action, au[0].before, au[0].after) == (
        "update", {"confirmed_tz": None}, {"timezone": TZ})

    # Zona o'zgarsa — qayta tasdiq HAQIQIY o'zgarish: audit AVVALGI tasdiqni ko'rsatadi.
    with _db() as db:
        db.get(Branch, t["bid"]).timezone = "Asia/Bishkek"
        db.commit()
    c = client.post(CONFIRM, headers=t["H"], json=body)
    assert c.status_code == 200 and c.json()["changed"] is True, c.text
    au = _audit(t["bid"])
    assert len(au) == 2
    assert (au[1].before, au[1].after) == ({"confirmed_tz": TZ}, {"timezone": "Asia/Bishkek"})


# ══ 3. KATALOG CUTOVER HOLATIGA TEGMAYDI ═════════════════════════════════════

def _live_katalog(boshqa_filial):
    return {"mode": "LIVE", "cutover_at": "2026-09-01T10:00:00+00:00", "source_system": "1c",
            "last_import_job_id": str(uuid.uuid4()), "last_snapshot_id": "snap-2026-09-01",
            "last_content_sha256": "ab" * 32,
            LP.CONFIRM_FIELD: {boshqa_filial: "Asia/Tashkent"}}


def test_tasdiq_KATALOG_cutover_kalitlariga_TEGMAYDI(client, monkeypatch):
    boshqa = str(uuid.uuid4())
    kat = _live_katalog(boshqa)
    t = _dokon(catalog=kat)
    _ochiq(monkeypatch)
    rv = _catalog_qatori(t["cid"]).row_version
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert r.status_code == 200, r.text
    row = _catalog_qatori(t["cid"])
    assert row.value == {**kat, LP.CONFIRM_FIELD: {boshqa: "Asia/Tashkent", str(t["bid"]): TZ}}
    assert row.row_version == (rv or 1) + 1
    with _db() as db:
        assert civ2.is_live(db, t["cid"]) is True


def test_ESKIRGAN_sessiya_nusxasi_cutover_holatini_QAYTARMAYDI(client, monkeypatch):
    """REGRESSIYA (SQLite'da ham ko'rinadi): sessiya `settings.catalog` qatorini cutover
    yopilishidan OLDIN yuklab, obyektni identity map'da ushlab turgan bo'lsa, eski kod o'sha
    nusxani qaytarib yozib `mode='LIVE'` ni PRE_LIVE ga tushirardi. Postgres'dagi parallel
    poyga — `test_lot_tz_confirm_pg.py`."""
    t = _dokon(catalog={"mode": "PRE_LIVE"})
    _ochiq(monkeypatch)
    s1 = _db()
    try:
        ushlangan = (s1.query(Setting).filter(Setting.company_id == t["cid"],
                                              Setting.branch_id.is_(None),
                                              Setting.key == "catalog").one())
        assert ushlangan.value["mode"] == "PRE_LIVE"      # identity map'da ESKI nusxa
        with _db() as s2:
            civ2.set_catalog_settings(s2, t["cid"], mode="LIVE",
                                      cutover_at="2026-09-01T10:00:00+00:00")
            s2.commit()
        natija = LP.confirm_tz(s1, t["cid"], t["bid"])
        s1.commit()
    finally:
        s1.close()
    v = _catalog_qatori(t["cid"]).value
    assert v["mode"] == "LIVE" and v["cutover_at"] == "2026-09-01T10:00:00+00:00"
    assert v[LP.CONFIRM_FIELD] == {str(t["bid"]): TZ}
    assert natija == (TZ, None, True)


def test_AYNI_tranzaksiyadagi_YUBORILMAGAN_ozgarish_yoqolmaydi(client, monkeypatch):
    """`populate_existing` flush'siz ishlatilsa, `autoflush=False` sessiyada hali
    yuborilmagan yozuv bazadagi qiymat bilan USTIDAN yozilardi."""
    t = _dokon(catalog={"mode": "PRE_LIVE"})
    _ochiq(monkeypatch)
    with _db() as db:
        civ2.set_catalog_settings(db, t["cid"], source_system="1c")
        LP.confirm_tz(db, t["cid"], t["bid"])
        civ2.set_catalog_settings(db, t["cid"], last_import_job_id="job-1")
        db.commit()
    v = _catalog_qatori(t["cid"]).value
    assert v["source_system"] == "1c" and v["last_import_job_id"] == "job-1"
    assert v[LP.CONFIRM_FIELD] == {str(t["bid"]): TZ}


def test_set_catalog_settings_NATIJASI_avvalgidek(client):
    """Umumiy yordamchi almashdi — catalog V2 va migrator chaqiruvchilari AYNI natijani ko'rsin:
    standartlar to'ldiriladi, `None` patch e'tiborsiz, begona kalit saqlanadi, mavjud qatorda
    `row_version` HAR chaqiruvda oshadi (qiymat o'zgarmasa ham).

    ⚠️  Bu sinov ESKI kodda ham YASHIL — u tuzatish emas, xulq o'zgarmaganining isboti."""
    t = _dokon()
    with _db() as db:
        v = civ2.set_catalog_settings(db, t["cid"], source_system="1c", cutover_at=None)
        db.commit()
    assert v == {"mode": "PRE_LIVE", "cutover_at": None, "source_system": "1c",
                 "last_import_job_id": None, "last_snapshot_id": None,
                 "last_content_sha256": None}
    row = _catalog_qatori(t["cid"])
    assert row.value == v and row.row_version == 1
    with _db() as db:
        assert civ2.set_catalog_settings(db, t["cid"], source_system="1c") == v
        db.commit()
    assert _catalog_qatori(t["cid"]).row_version == 2

    t2 = _dokon(catalog={LP.CONFIRM_FIELD: {"f": TZ}, "mode": "PRE_LIVE"})
    with _db() as db:
        v2 = civ2.set_catalog_settings(db, t2["cid"], mode="LIVE", last_snapshot_id="s-1",
                                       source_system=None)
        db.commit()
    assert v2 == {LP.CONFIRM_FIELD: {"f": TZ}, "mode": "LIVE", "cutover_at": None,
                  "source_system": None, "last_import_job_id": None,
                  "last_snapshot_id": "s-1", "last_content_sha256": None}
    row2 = _catalog_qatori(t2["cid"])
    assert row2.value == v2 and row2.row_version == 2


def test_update_catalog_settings_OZGARISHSIZ_yozmaydi_qatorsiz_YARATMAYDI(client):
    t = _dokon(catalog={"mode": "LIVE"})
    with _db() as db:
        assert civ2.update_catalog_settings(db, t["cid"], lambda val: None) is False
        db.commit()
    row = _catalog_qatori(t["cid"])
    assert row.value == {"mode": "LIVE"} and row.row_version == 1
    bosh = _dokon()
    with _db() as db:
        assert civ2.update_catalog_settings(db, bosh["cid"], lambda val: None) is False
        db.commit()
    assert _catalog_qatori(bosh["cid"]) is None


# ══ 4. VALIDATSIYA ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("tz", ["", "Mars/Olympus"])
def test_YAROQSIZ_zona_400_va_HECH_NARSA_yozilmaydi(client, monkeypatch, tz):
    t = _dokon(tz=tz)
    _ochiq(monkeypatch)
    oldin = _iz(t["cid"])
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert r.status_code == 400, r.text
    assert _iz(t["cid"]) == oldin
    assert _catalog_qatori(t["cid"]) is None


def test_OCHIRILGAN_filial_404_va_yozuvsiz(client, monkeypatch):
    """REGRESSIYA: o'chirilgan filial (yaroqli zonasi bilan) ilgari TASDIQLANARDI."""
    t = _dokon()
    _ochiq(monkeypatch)
    with _db() as db:
        eski = Branch(id=uuid.uuid4(), company_id=t["cid"], name="F02", code="F02", timezone=TZ,
                      deleted_at=datetime.now(timezone.utc))
        db.add(eski)
        db.commit()
        eski_id = eski.id
    oldin = _iz(t["cid"])
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(eski_id)})
    assert r.status_code == 404, r.text
    assert _iz(t["cid"]) == oldin
    # NAZORAT: tirik filial o'tadi.
    assert client.post(CONFIRM, headers=t["H"],
                       json={"branch_id": str(t["bid"])}).status_code == 200


def test_BEGONA_dokon_filiali_404_va_yozuvsiz(client, monkeypatch):
    t, begona = _dokon(), _dokon()
    _ochiq(monkeypatch)
    oldin = (_iz(t["cid"]), _iz(begona["cid"]))
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(begona["bid"])})
    assert r.status_code == 404, r.text
    assert (_iz(t["cid"]), _iz(begona["cid"])) == oldin


# ══ 5. RUXSAT MATRITSASI ═════════════════════════════════════════════════════

MATRITSA = [
    pytest.param("ega", (), 200, id="ega"),
    pytest.param("administrator", (), 200, id="administrator"),
    pytest.param("menejer", (), 403, id="menejer"),
    pytest.param("omborchi", (), 403, id="omborchi"),
    pytest.param("kassir", (), 403, id="kassir"),
    pytest.param("kassir", ("sozlamalar.edit",), 200, id="kassir_override_sozlamalar_edit"),
]


@pytest.mark.parametrize("role,allow,kutiladi", MATRITSA)
def test_RUXSAT_matritsasi_darvoza_OCHIQ(client, monkeypatch, role, allow, kutiladi):
    t = _dokon(role=role, allow=allow)
    _ochiq(monkeypatch)
    oldin = _iz(t["cid"])
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert r.status_code == kutiladi, r.text
    if kutiladi == 200:
        assert _catalog_qatori(t["cid"]).value[LP.CONFIRM_FIELD] == {str(t["bid"]): TZ}
        assert len(_audit(t["bid"])) == 1
    else:
        assert "Ruxsat yo'q" in r.json()["detail"]
        assert _iz(t["cid"]) == oldin


@pytest.mark.parametrize("role,allow,ochiqda", MATRITSA)
def test_RUXSAT_matritsasi_darvoza_YOPIQ_hech_kim_yoza_olmaydi(client, monkeypatch, role, allow,
                                                               ochiqda):
    """Yopiq darvozada matritsada BIRORTA 200 yo'q. Ruxsati bor xodim darvoza matnini,
    ruxsatsiz xodim «Ruxsat yo'q» ni oladi — ruxsat tekshiruvi baribir birinchi."""
    t = _dokon(role=role, allow=allow)
    _muhit(monkeypatch, {"APP_ENV": None})
    oldin = _iz(t["cid"])
    r = client.post(CONFIRM, headers=t["H"], json={"branch_id": str(t["bid"])})
    assert r.status_code == 403, r.text
    if ochiqda == 200:
        assert r.json()["detail"] == _darvoza_matni()
    assert _iz(t["cid"]) == oldin
    assert _catalog_qatori(t["cid"]) is None


@pytest.mark.parametrize("env", [pytest.param({"APP_ENV": "dev"}, id="ochiq"),
                                 pytest.param({"APP_ENV": None}, id="yopiq")])
def test_TOKENSIZ_401(client, monkeypatch, env):
    t = _dokon()
    _muhit(monkeypatch, env)
    oldin = _iz(t["cid"])
    assert client.post(CONFIRM, json={"branch_id": str(t["bid"])}).status_code == 401
    assert _iz(t["cid"]) == oldin


# ══ 6. MIGRATOR IZI ══════════════════════════════════════════════════════════

def test_rad_etilgan_tasdiq_MIGRATOR_izini_ozgartirmaydi(client, monkeypatch):
    """Ko'rib chiqilgan 1C hisobotining izi `settings.catalog` ni ham o'z ichiga oladi —
    rad etilgan tasdiq uni o'zgartirsa, apply DriftError bilan qaytadan ko'rib chiqishni talab
    qilardi."""
    from app.services.migrator_1c.catalog import load_snapshot
    t = _dokon()
    _muhit(monkeypatch, {"APP_ENV": "production"})
    with _db() as db:
        s0 = load_snapshot(db, t["code"])
    assert client.post(CONFIRM, headers=t["H"], json={}).status_code == 403
    with _db() as db:
        s1 = load_snapshot(db, t["code"])
    assert s1.fingerprint == s0.fingerprint
    assert s1.catalog_setting == {} == s0.catalog_setting

    # NAZORAT: iz tasdiqni SEZADI — aks holda yuqoridagi tenglik hech narsani o'lchamasdi.
    _ochiq(monkeypatch)
    assert client.post(CONFIRM, headers=t["H"], json={}).status_code == 200
    with _db() as db:
        assert load_snapshot(db, t["code"]).fingerprint != s0.fingerprint
