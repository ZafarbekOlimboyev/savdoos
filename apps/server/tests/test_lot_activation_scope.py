# -*- coding: utf-8 -*-
"""PARTIYA KUZATUVINI YOQISH — DO'KON × FILIAL DARVOZASI (Phase 5B.1, G).

⚠️  NEGA. Muhit darvozasi JARAYON bo'yicha edi: production'da ochilsa, HAR
    do'konning `ombor.edit` egasi o'z mahsulotini QAYTARIB BO'LMAYDIGAN qilib
    kuzatuvli qila olardi, `/lots/availability` esa hamma do'konga bo'limni
    ochardi. Faollashtirish — vendor qarori: bitta do'kon, aniq filial.

        SAVDOOS_LOT_ACTIVATION_SCOPES="<company_uuid>:<branch_uuid>[,...]"

Bu fayl isbotlaydi (SQLite):
  · `lot_policy` haqiqat jadvali — ro'yxatsiz production YOPIQ, aniq juftlik OCHIQ,
    bitta buzuq yozuv HAMMASINI yopadi, qarama-qarshi muhit signallari yopadi,
    staging ro'yxatsiz muhit bo'yicha, ro'yxat bilan production kabi;
  · API: ro'yxatdagi juftlik tasdiq + enable(track_expiry) 200; filialsiz so'rov,
    begona/tasodifiy filial, qisman qoplangan ko'p filialli do'kon — 403 (404 emas)
    va HECH NARSA yozilmaydi (settings, mahsulot bayroqlari, partiyalar, audit);
  · filialga biriktirilgan omborchi ko'rinmaydigan filialda 404, yozuvsiz;
  · availability: filial bayroqlari, begona do'kon yopiq, ro'yxat/rejim OSHKOR EMAS;
  · darvoza yopilgach yoqish/tasdiq 403, kuzatuvli mahsulot esa SOTILADI va KIRIM qilinadi;
  · ruxsat tekshiruvi darvozadan OLDIN;
  · ochilish partiyalari validatsiyasi (buzuq sana 400, muddatsiz/o'tgan muddat 400);
  · `config_audit` va boot jurnali qiymatni CHOP ETMAYDI.

Haqiqiy Postgres'da AYNI yo'l — `test_lot_activation_scope_pg.py`.

⚠️  HAR SINOV O'Z DO'KONIDA. Umumiy seed do'konining tarifi 10 foydalanuvchi va
    filiallar to'plami qo'riqlanadi (`conftest._seed_filiallari_ozgarmaydi`).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Text, cast

from app.core.security import create_access_token
from app.models.auth import Employee, EmployeeBranch, EmployeePermission, Permission, Role
from app.models.catalog import Product, Unit
from app.models.enums import EmployeeStatus
from app.models.inventory import Inventory, StockBatch
from app.models.org import Branch, Company
from app.models.settings import Setting
from app.models.sync import AuditLog
from app.services import lot_policy as LP

SCOPES = "SAVDOOS_LOT_ACTIVATION_SCOPES"
CONFIRM = "/api/v1/lots/timezone/confirm"
ENABLE = "/api/v1/lots/enable"
AVAIL = "/api/v1/lots/availability"
TZ = "Asia/Tashkent"
NOW = datetime.now(timezone.utc)
AUDIT_ENTITIES = ("product_lot_tracking", "expiry_timezone")

C1, B1 = str(uuid.uuid4()), str(uuid.uuid4())
C2, B2 = str(uuid.uuid4()), str(uuid.uuid4())


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _muhit(monkeypatch, app_env, platform=None, scopes=None):
    for k, v in (("APP_ENV", app_env), ("RAILWAY_ENVIRONMENT_NAME", platform), (SCOPES, scopes)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _juft(*pairs):
    return ",".join(f"{c}:{b}" for c, b in pairs)


def _prod(monkeypatch, *pairs, raw=None):
    """JONLI production shakli: `APP_ENV=production`, platforma `production`."""
    _muhit(monkeypatch, "production", "production",
           raw if raw is not None else (_juft(*pairs) if pairs else None))


def _ochiq(monkeypatch):
    _muhit(monkeypatch, "dev")


def _darvoza_matni():
    """Joriy muhitda darvoza AYNAN qaysi matn bilan rad etadi (yangi matn yo'q)."""
    with pytest.raises(LP.LotActivationNotAllowed) as ei:
        LP.assert_activation_allowed()
    return str(ei.value)


def _xodim(db, cid, role, allow=(), filial=None):
    r = db.query(Role).filter(Role.code == role).one()
    e = Employee(id=uuid.uuid4(), company_id=cid, role_id=r.id, full_name=f"G {role}",
                 phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                 status=EmployeeStatus.active, sec_epoch=0)
    db.add(e)
    db.flush()
    for code in allow:
        p = db.query(Permission).filter(Permission.code == code).one()
        db.add(EmployeePermission(employee_id=e.id, permission_id=p.id, allowed=True))
    if filial is not None:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=filial))
    tok = create_access_token(str(e.id), {"role": role, "company_id": str(cid), "sv": 0})
    return {"Authorization": f"Bearer {tok}"}


def _dokon(filiallar=1, role="ega", allow=(), tz=TZ):
    """Toza do'kon + N filial (yaratilish tartibi aniq) + xodim."""
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="G darvoza", code="g" + uuid.uuid4().hex[:9],
                       currency="UZS")
        db.add(comp)
        db.flush()
        bids = []
        for i in range(filiallar):
            b = Branch(id=uuid.uuid4(), company_id=comp.id, name=f"F0{i + 1}", code=f"F0{i + 1}",
                       timezone=tz, created_at=NOW + timedelta(seconds=i))
            db.add(b)
            db.flush()
            bids.append(b.id)
        H = _xodim(db, comp.id, role, allow)
        db.commit()
        return {"cid": comp.id, "bids": bids, "bid": bids[0], "H": H}


def _xodim_qosh(t, role, allow=(), filial=None):
    with _db() as db:
        H = _xodim(db, t["cid"], role, allow, filial)
        db.commit()
        return H


def _mahsulot(t, qty=0, bid=None):
    """Mahsulot + (ixtiyoriy) qoldiq — to'g'ridan-to'g'ri bazaga (rol ruxsatiga bog'liq emas)."""
    with _db() as db:
        unit = db.query(Unit).filter(Unit.code == "dona").one()
        p = Product(id=uuid.uuid4(), company_id=t["cid"], article_code=f"G-{uuid.uuid4().hex[:8]}",
                    name=f"G mahsulot {uuid.uuid4().hex[:6]}", unit_id=unit.id,
                    base_buy_price=Decimal("70"), base_sell_price=Decimal("100"), tax_rate=0,
                    is_active=True)
        db.add(p)
        db.flush()
        if qty:
            db.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=bid or t["bid"],
                             qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        db.commit()
        return str(p.id)


def _iz(cid):
    """Yoqish va tasdiq yozishi mumkin bo'lgan HAMMA narsa.

    `settings` — qiymat MATNI va `row_version` bilan; mahsulot bayroqlari; partiyalar;
    qoldiq; audit — `product_lot_tracking`/`expiry_timezone` qatorlari do'kondan qat'i
    nazar (begona filial yoki mahsulot id'si bilan yozilgan qator ham ko'rinsin).
    """
    with _db() as db:
        return {
            "settings": sorted(
                (k, str(b), v, int(rv or 0)) for k, b, v, rv in
                db.query(Setting.key, Setting.branch_id, cast(Setting.value, Text),
                         Setting.row_version).filter(Setting.company_id == cid).all()),
            "products": sorted(
                (str(i), bool(tl), bool(te), str(la)) for i, tl, te, la in
                db.query(Product.id, Product.track_lots, Product.track_expiry,
                         Product.lots_activated_at).filter(Product.company_id == cid).all()),
            "batches": sorted(str(i) for (i,) in
                              db.query(StockBatch.id).filter(StockBatch.company_id == cid).all()),
            "inventory": sorted(
                (str(p), str(b), str(q)) for p, b, q in
                db.query(Inventory.product_id, Inventory.branch_id, Inventory.qty)
                .join(Product, Product.id == Inventory.product_id)
                .filter(Product.company_id == cid).all()),
            "audit": [(a.id, a.entity, str(a.entity_id)) for a in
                      db.query(AuditLog).filter(AuditLog.entity.in_(AUDIT_ENTITIES))
                      .order_by(AuditLog.id).all()],
        }


def _mahsulot_holati(pid):
    with _db() as db:
        p = db.get(Product, uuid.UUID(pid))
        n = db.query(StockBatch).filter(StockBatch.product_id == p.id).count()
        return bool(p.track_lots), bool(p.track_expiry), p.lots_activated_at, n


def _catalog_qatori(cid):
    with _db() as db:
        return db.query(Setting).filter(Setting.company_id == cid, Setting.branch_id.is_(None),
                                        Setting.key == "catalog").one_or_none()


def _tasdiq(client, H, bid=None):
    return client.post(CONFIRM, headers=H, json={} if bid is None else {"branch_id": str(bid)})


def _enable(client, H, pid, bid=None, **kw):
    body = {"product_id": pid, "reason": "sinov: do'kon×filial darvozasi", **kw}
    if bid is not None:
        body["branch_id"] = str(bid)
    return client.post(ENABLE, headers=H, json=body)


def _av(client, H):
    r = client.get(AVAIL, headers=H)
    assert r.status_code == 200, r.text
    return r


def _biz(bid):
    with _db() as db:
        return LP.business_date(db, bid)


# ══ 1. `lot_policy` HAQIQAT JADVALI (BAZASIZ) ═══════════════════════════════

@pytest.mark.parametrize("app_env", ["production", "prod"])
@pytest.mark.parametrize("platform", ["production", "prod", None])
def test_PRODUCTION_royxatsiz_YOPIQ(monkeypatch, app_env, platform):
    """Jonli production: o'zgaruvchi YO'Q — hech kimga, argument bilan ham, argumentsiz ham."""
    _muhit(monkeypatch, app_env, platform, None)
    assert LP.activation_mode() == "closed"
    assert LP.activation_scopes() is None
    assert LP.activation_allowed() is False
    assert LP.activation_allowed(C1, B1) is False
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed(C1, B1)


@pytest.mark.parametrize("bosh", ["", "   ", " , "])
def test_BOSH_ozgaruvchi_ROYXAT_YOQ_deb_oqiladi_bosh_vergul_esa_BUZUQ(monkeypatch, bosh):
    _muhit(monkeypatch, "production", "production", bosh)
    if bosh.strip():
        assert LP.activation_scopes() == frozenset() and LP.activation_mode() == "scoped"
    else:
        assert LP.activation_scopes() is None and LP.activation_mode() == "closed"
    assert LP.activation_allowed(C1, B1) is False


@pytest.mark.parametrize("app_env", ["production", "prod", "PRODUCTION"])
def test_PRODUCTION_ANIQ_juftlik_OCHIQ_qolgani_YOPIQ(monkeypatch, app_env):
    _muhit(monkeypatch, app_env, "production", _juft((C1, B1), (C2, B2)))
    assert LP.activation_mode() == "scoped"
    assert LP.activation_allowed(C1, B1) is True
    assert LP.activation_allowed(uuid.UUID(C2), uuid.UUID(B2)) is True     # UUID obyekt ham
    # Juftlik AYNAN — kesishgan juftlik, yo'q filial yoki yo'q do'kon ochmaydi.
    for c, b in ((C1, B2), (C2, B1), (C1, None), (None, B1), (None, None),
                 (C1, str(uuid.uuid4())), (str(uuid.uuid4()), B1), (C1, "buzuq")):
        assert LP.activation_allowed(c, b) is False, (c, b)
    assert LP.activation_allowed() is False, "argumentsiz chaqiruv scoped rejimda OCHIQ qoldi"
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed(C1, None)


@pytest.mark.parametrize("buzuq", [
    pytest.param(f"{C1}:{B1},garbage", id="ikki_nuqtasiz"),
    pytest.param(f"{C1}:{B1},", id="oxirgi_vergul"),
    pytest.param(f",{C1}:{B1}", id="birinchi_vergul"),
    pytest.param(f"{C1}:{B1},,{C2}:{B2}", id="bosh_yozuv"),
    pytest.param(f"{C1}:{B1}:{B2}", id="uch_qism"),
    pytest.param(f"{C1}:{B1},{C2}:", id="filialsiz"),
    pytest.param(f"{C1}:{B1},:{B2}", id="dokonsiz"),
    pytest.param(f"{C1}:{B1},not-a-uuid:{B2}", id="uuid_emas"),
    pytest.param(f"{C1};{B1}", id="nuqtali_vergul"),
])
def test_BITTA_buzuq_yozuv_HAMMASINI_yopadi(monkeypatch, buzuq):
    """«Qolganlari to'g'ri-ku» deb qisman o'qish operator xatosini JIMGINA ruxsatga
    aylantirardi."""
    _muhit(monkeypatch, "production", "production", buzuq)
    assert LP.activation_scopes() == frozenset()
    assert LP.activation_allowed(C1, B1) is False
    assert LP.activation_allowed(C2, B2) is False
    s = LP.scope_summary()
    assert s["malformed"] is True and s["valid_pairs"] == 0 and s["set"] is True


def test_KATTA_harf_va_BOSH_JOY_kanonik_holga_keltiriladi(monkeypatch):
    raw = f"  {C1.upper()} : {B1.upper()} ,\t{{{C2}}}:{B2.replace('-', '')}  "
    _muhit(monkeypatch, "production", "production", raw)
    assert LP.activation_scopes() == frozenset({(C1, B1), (C2, B2)})
    assert LP.activation_allowed(C1, B1) is True
    assert LP.activation_allowed(C1.upper(), f" {B1} ") is True
    assert LP.activation_allowed(C2, B2) is True


@pytest.mark.parametrize("app_env", [None, "", "boshqa", "PROD-X"])
@pytest.mark.parametrize("platform", [None, "production"])
def test_APP_ENV_yoq_yoki_NOMALUM_royxat_bilan_ham_YOPIQ(monkeypatch, app_env, platform):
    _muhit(monkeypatch, app_env, platform, _juft((C1, B1)))
    assert LP.activation_mode() == "closed"
    assert LP.activation_allowed(C1, B1) is False
    assert LP.activation_allowed() is False


@pytest.mark.parametrize("app_env", ["dev", "test", "staging"])
@pytest.mark.parametrize("platform", ["production", "prod"])
@pytest.mark.parametrize("scopes", [None, _juft((C1, B1))])
def test_DEV_production_platformasida_royxat_bilan_ham_YOPIQ(monkeypatch, app_env, platform,
                                                           scopes):
    """Platforma belgisi `APP_ENV` dan USTUN — ro'yxat uni aylanib o'tmaydi."""
    _muhit(monkeypatch, app_env, platform, scopes)
    assert LP.activation_mode() == "closed"
    assert LP.activation_allowed(C1, B1) is False
    assert LP.activation_allowed() is False


@pytest.mark.parametrize("platform", ["staging", "dev", "test", "boshqa"])
def test_PRODUCTION_ilova_BOSHQA_platformada_royxat_bilan_ham_YOPIQ(monkeypatch, platform):
    _muhit(monkeypatch, "production", platform, _juft((C1, B1)))
    assert LP.activation_mode() == "closed"
    assert LP.activation_allowed(C1, B1) is False


@pytest.mark.parametrize("app_env,platform", [("staging", "staging"), ("staging", None),
                                              ("dev", None), ("test", "test")])
def test_STAGING_royxatsiz_MUHIT_boyicha_royxat_bilan_PRODUCTION_kabi(monkeypatch, app_env,
                                                                     platform):
    _muhit(monkeypatch, app_env, platform, None)
    assert LP.activation_mode() == "env"
    assert LP.activation_allowed() is True                  # bugungi xulq (e2e, pytest)
    assert LP.activation_allowed(C1, B1) is True
    assert LP.activation_allowed(str(uuid.uuid4()), None) is True
    LP.assert_activation_allowed()

    # Ro'yxat berilsa — staging production konfiguratsiyasini AYNAN takrorlaydi.
    _muhit(monkeypatch, app_env, platform, _juft((C1, B1)))
    assert LP.activation_mode() == "scoped"
    assert LP.activation_allowed() is False
    assert LP.activation_allowed(C1, B1) is True
    assert LP.activation_allowed(C1, B2) is False


def test_ENV_rejimida_qoplash_BAZAGA_TEGMAYDI_boshqa_rejimda_bazasiz_RAD(monkeypatch):
    """`test_check_defs_pg._enable_status` soxta `db` bilan chaqiradi — `env` rejimida
    darvoza unga umuman tegmasligi shart."""
    class Portlovchi:
        def __getattr__(self, name):
            raise AssertionError(f"env rejimida baza o'qildi: {name}")

    _ochiq(monkeypatch)
    assert LP.scope_covers_company(Portlovchi(), None) is True
    LP.assert_activation_allowed(None, None, db=Portlovchi())

    _prod(monkeypatch, (C1, B1))
    # Qoplashni isbotlab bo'lmaydi — FAIL-CLOSED.
    assert LP.scope_covers_company(None, C1) is False
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed(C1, B1, db=None)
    # Juftlik rad etilsa qoplash (baza) SO'RALMAYDI.
    with pytest.raises(LP.LotActivationNotAllowed):
        LP.assert_activation_allowed(C2, B2, db=Portlovchi())


def test_rad_MATNI_barcha_sabablarda_AYNI(monkeypatch):
    """Sabab farqi (ro'yxatda yo'q, filialsiz, qoplanmagan) javobda ko'rinmasin."""
    _prod(monkeypatch, (C1, B1))
    matnlar = set()
    for args in ((), (C1, None), (C2, B2), (C1, B2)):
        with pytest.raises(LP.LotActivationNotAllowed) as ei:
            LP.assert_activation_allowed(*args)
        matnlar.add(str(ei.value))
    assert len(matnlar) == 1, matnlar
    assert C1 not in matnlar.pop()


def test_MUHIT_royxati_OZGARMAGAN():
    assert LP.LOT_ACTIVATION_ALLOWED_ENVS == frozenset({"dev", "test", "staging"})
    assert LP.LOT_ACTIVATION_SCOPES_ENV == SCOPES


# ══ 2. API — RO'YXATDAGI JUFTLIK ═════════════════════════════════════════════

def test_ROYXATDAGI_juftlik_TASDIQ_200_va_ENABLE_track_expiry_200(client, monkeypatch):
    t = _dokon()
    pid = _mahsulot(t, qty=5)
    _prod(monkeypatch)
    # MANFIY NAZORAT: ro'yxatsiz AYNI so'rovlar 403 — 200 ro'yxatdan kelmoqda.
    assert _tasdiq(client, t["H"], t["bid"]).status_code == 403
    _prod(monkeypatch, (t["cid"], t["bid"]))
    c = _tasdiq(client, t["H"], t["bid"])
    assert c.status_code == 200, c.text
    assert c.json()["changed"] is True
    muddat = (_biz(t["bid"]) + timedelta(days=30)).isoformat()
    e = _enable(client, t["H"], pid, t["bid"], track_expiry=True,
                opening_lots=[{"qty": 5, "unit_cost": 70, "expiry_date": muddat,
                               "batch_number": "G-1"}])
    assert e.status_code == 200, e.text
    assert (e.json()["track_expiry"], e.json()["lots_created"]) == (True, 1)
    tl, te, la, n = _mahsulot_holati(pid)
    assert (tl, te, n) == (True, True, 1) and la is not None
    with _db() as db:
        lot = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).one()
        assert (lot.branch_id, lot.expiry_date.isoformat()) == (t["bid"], muddat)
        assert db.query(AuditLog).filter(AuditLog.entity == "product_lot_tracking",
                                         AuditLog.entity_id == uuid.UUID(pid)).count() == 1
        assert db.query(AuditLog).filter(AuditLog.entity == "expiry_timezone",
                                         AuditLog.entity_id == t["bid"]).count() == 1


def test_ROYXATDAGI_dokon_FILIALSIZ_sorov_403_va_HECH_NARSA_yozilmaydi(client, monkeypatch):
    """Qaytarib bo'lmaydigan yozuvni jimgina tanlangan «standart filial» hal qilmasin."""
    t = _dokon()
    pid = _mahsulot(t, qty=3)
    _prod(monkeypatch, (t["cid"], t["bid"]))
    matn = _darvoza_matni()
    oldin = _iz(t["cid"])
    c = _tasdiq(client, t["H"])
    e = _enable(client, t["H"], pid, legacy_unit_cost=70)
    e2 = _enable(client, t["H"], pid, track_expiry=True,
                 opening_lots=[{"qty": 3, "unit_cost": 70, "expiry_date": "2099-01-01"}])
    for r in (c, e, e2):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == matn
    assert _iz(t["cid"]) == oldin
    assert _catalog_qatori(t["cid"]) is None
    assert _mahsulot_holati(pid) == (False, False, None, 0)
    # NAZORAT: ayni do'kon filial bilan o'tadi — 403 boshqa sababdan emas.
    assert _enable(client, t["H"], pid, t["bid"], legacy_unit_cost=70).status_code == 200


@pytest.mark.parametrize("raw", [pytest.param(None, id="ozgaruvchi_yoq"),
                                 pytest.param("buzuq", id="buzuq")])
def test_PRODUCTION_royxatsiz_yoki_BUZUQ_royxat_AVVALGIDEK_403(client, monkeypatch, raw):
    t = _dokon()
    pid = _mahsulot(t)
    if raw is None:
        _prod(monkeypatch)
    else:
        _prod(monkeypatch, raw=f"{t['cid']}:{t['bid']},{raw}")
    matn = _darvoza_matni()
    oldin = _iz(t["cid"])
    for r in (_tasdiq(client, t["H"], t["bid"]), _enable(client, t["H"], pid, t["bid"])):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == matn
    assert _iz(t["cid"]) == oldin


def test_ROYXATDA_YOQ_dokon_BEGONA_yoki_TASODIFIY_filial_bilan_403_404_EMAS(client, monkeypatch):
    """Darvoza filial qidiruvidan OLDIN: 404 begona filial MAVJUDLIGINI oshkor qilardi."""
    a, b = _dokon(), _dokon()
    pa, pb = _mahsulot(a), _mahsulot(b)
    _prod(monkeypatch, (a["cid"], a["bid"]))
    matn = _darvoza_matni()
    oldin = (_iz(a["cid"]), _iz(b["cid"]))
    # Ro'yxatda YO'Q do'kon: ro'yxatdagi do'konning filiali, tasodifiy UUID, o'z filiali.
    for bid in (a["bid"], uuid.uuid4(), b["bid"]):
        for r in (_tasdiq(client, b["H"], bid), _enable(client, b["H"], pb, bid),
                  _enable(client, b["H"], pa, bid)):
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == matn
    # Ro'yxatdagi do'kon — begona yoki tasodifiy filial bilan.
    for bid in (b["bid"], uuid.uuid4()):
        for r in (_tasdiq(client, a["H"], bid), _enable(client, a["H"], pa, bid)):
            assert r.status_code == 403, r.text
            assert r.json()["detail"] == matn
    assert (_iz(a["cid"]), _iz(b["cid"])) == oldin


def test_IKKI_filialli_dokon_BITTASI_royxatda_403_IKKALASI_royxatda_200(client, monkeypatch):
    """`track_lots` — MAHSULOT bayrog'i: bitta filialli pilot ikkinchi filialda kirim va
    sotuvni jimgina partiyaga bog'lab qo'yardi."""
    t = _dokon(filiallar=2)
    b1, b2 = t["bids"]
    pid = _mahsulot(t)
    _prod(monkeypatch, (t["cid"], b1))
    matn = _darvoza_matni()
    oldin = _iz(t["cid"])
    for r in (_tasdiq(client, t["H"], b1), _enable(client, t["H"], pid, b1),
              _tasdiq(client, t["H"], b2), _enable(client, t["H"], pid, b2)):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == matn
    assert _iz(t["cid"]) == oldin
    j = _av(client, t["H"]).json()
    assert j["activation_allowed"] is False and j["can_enable"] is False
    assert [x["activation_allowed"] for x in j["branches"]] == [False, False]

    # O'chirilgan filial qoplashni talab qilmaydi.
    with _db() as db:
        db.add(Branch(id=uuid.uuid4(), company_id=t["cid"], name="F09", code="F09", timezone=TZ,
                      deleted_at=NOW))
        db.commit()
    # NAZORAT: ikkala tirik filial ro'yxatda — AYNI so'rovlar o'tadi.
    _prod(monkeypatch, (t["cid"], b1), (t["cid"], b2))
    assert _tasdiq(client, t["H"], b1).status_code == 200
    assert _enable(client, t["H"], pid, b1).status_code == 200
    j = _av(client, t["H"]).json()
    assert j["activation_allowed"] is True
    assert [x["activation_allowed"] for x in j["branches"]] == [True, True]


@pytest.mark.parametrize("rejim", ["scoped", "env"])
def test_FILIALGA_biriktirilgan_OMBORCHI_korinmaydigan_filialda_404_va_yozuvsiz(
        client, monkeypatch, rejim):
    """IDOR: bitta filialga biriktirilgan omborchi ilgari do'konning ISTALGAN filialida
    kuzatuvni yoqa olardi. Qoida HAR rejimda (muhit bo'yicha ochiq dev'da ham)."""
    t = _dokon(filiallar=2)
    b1, b2 = t["bids"]
    H = _xodim_qosh(t, "omborchi", allow=("sozlamalar.edit",), filial=b1)
    pid = _mahsulot(t)
    if rejim == "scoped":
        _prod(monkeypatch, (t["cid"], b1), (t["cid"], b2))
    else:
        _ochiq(monkeypatch)
    oldin = _iz(t["cid"])
    for r in (_tasdiq(client, H, b2), _enable(client, H, pid, b2)):
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "Filial topilmadi"
    assert _iz(t["cid"]) == oldin
    # NAZORAT: o'z filiali o'tadi; ega esa ikkinchi filialni ko'radi.
    assert _tasdiq(client, H, b1).status_code == 200
    assert _enable(client, H, pid, b1).status_code == 200
    assert _tasdiq(client, t["H"], b2).status_code == 200


# ══ 3. AVAILABILITY ══════════════════════════════════════════════════════════

def test_AVAILABILITY_filial_bayroqlari_begona_dokon_YOPIQ_royxat_OSHKOR_EMAS(client, monkeypatch):
    t, u, v = _dokon(filiallar=2), _dokon(), _dokon()
    b1, b2 = t["bids"]
    Hb1 = _xodim_qosh(t, "omborchi", filial=b1)
    _prod(monkeypatch, (t["cid"], b1), (t["cid"], b2), (v["cid"], v["bid"]))

    r = _av(client, t["H"])
    j = r.json()
    assert j["activation_allowed"] is True
    assert {x["id"]: x["activation_allowed"] for x in j["branches"]} == {str(b1): True,
                                                                          str(b2): True}
    assert j["can_enable"] == (j["activation_allowed"] and j["can_write"]) is True
    assert j["section_visible"] is True
    # Ro'yxat, rejim va o'zgaruvchi nomi javobda YO'Q; boshqa ro'yxatdagi do'kon ham.
    for sir in (SCOPES, "scoped", str(v["cid"]), str(v["bid"]), str(u["cid"])):
        assert sir not in r.text, sir

    # Biriktirilgan omborchi faqat o'z filialini ko'radi — u ham ochiq (do'kon qoplangan).
    jb = _av(client, Hb1).json()
    assert [(x["id"], x["activation_allowed"]) for x in jb["branches"]] == [(str(b1), True)]
    assert jb["activation_allowed"] is True and jb["can_enable"] is True

    # Ro'yxatda YO'Q do'kon — hammasi yopiq, bo'lim ko'rinmaydi.
    ru = _av(client, u["H"])
    ju = ru.json()
    assert (ju["activation_allowed"], ju["can_enable"], ju["section_visible"]) == (
        False, False, False)
    assert [x["activation_allowed"] for x in ju["branches"]] == [False]
    for sir in (SCOPES, "scoped", str(t["cid"]), str(v["cid"]), str(b1)):
        assert sir not in ru.text, sir


def test_AVAILABILITY_production_royxatsiz_HAMMASI_YOPIQ_env_rejimida_OCHIQ(client, monkeypatch):
    t = _dokon(filiallar=2)
    _prod(monkeypatch)
    j = _av(client, t["H"]).json()
    assert j["activation_allowed"] is False and j["can_enable"] is False
    assert [x["activation_allowed"] for x in j["branches"]] == [False, False]
    _ochiq(monkeypatch)
    j = _av(client, t["H"]).json()
    assert j["activation_allowed"] is True and j["can_enable"] is True
    assert [x["activation_allowed"] for x in j["branches"]] == [True, True]


# ══ 4. DARVOZANI YOPISH — MAVJUD KUZATUV ISHLAYVERADI ═══════════════════════

def test_DARVOZA_yopilgach_YOQISH_va_TASDIQ_403_kuzatuvli_mahsulot_SOTILADI_va_KIRIM_qilinadi(
        client, monkeypatch):
    t = _dokon()
    pid = _mahsulot(t, qty=4)
    boshqa = _mahsulot(t)
    _prod(monkeypatch, (t["cid"], t["bid"]))
    assert _tasdiq(client, t["H"], t["bid"]).status_code == 200
    muddat = _biz(t["bid"]) + timedelta(days=20)
    e = _enable(client, t["H"], pid, t["bid"], track_expiry=True,
                opening_lots=[{"qty": 4, "unit_cost": 70, "expiry_date": muddat.isoformat()}])
    assert e.status_code == 200, e.text

    # ── Yopish: o'zgaruvchi olib tashlandi ──
    _prod(monkeypatch)
    oldin = _iz(t["cid"])
    for r in (_tasdiq(client, t["H"], t["bid"]), _enable(client, t["H"], boshqa, t["bid"])):
        assert r.status_code == 403, r.text
    assert _iz(t["cid"]) == oldin

    # ── Runtime darvozalanmagan: sotuv FEFO bilan, kirim partiya bilan ──
    s = client.post("/api/v1/sales", headers=t["H"], json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 1000, "client_uuid": str(uuid.uuid4())})
    assert s.status_code == 200, s.text
    sup = client.post("/api/v1/suppliers", headers=t["H"], json={"name": "G ta'minotchi"})
    assert sup.status_code in (200, 201), sup.text
    k = client.post("/api/v1/receiving/commit", headers=t["H"], json={
        "items": [{"product_id": pid, "qty": 2, "unit_cost": 70, "unit": "dona",
                   "lots": [{"qty": 2, "unit_cost": 70,
                             "expiry_date": (muddat + timedelta(days=5)).isoformat()}]}],
        "supplier_id": sup.json()["id"], "payment": "credit",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert k.status_code == 200, k.text
    with _db() as db:
        lots = (db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid))
                .order_by(StockBatch.expiry_date).all())
        assert [float(x.remaining_qty) for x in lots] == [3.0, 2.0]
        inv = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid)).one()
        assert float(inv.qty) == 5.0
    assert _mahsulot_holati(boshqa) == (False, False, None, 0)


# ══ 5. RUXSAT — DARVOZADAN OLDIN ═════════════════════════════════════════════

MATRITSA = [
    # rol, override, tasdiq, enable
    pytest.param("ega", (), 200, 200, id="ega"),
    pytest.param("administrator", (), 200, 200, id="administrator"),
    pytest.param("menejer", (), 403, 403, id="menejer"),
    pytest.param("omborchi", (), 403, 200, id="omborchi"),
    pytest.param("kassir", (), 403, 403, id="kassir"),
    pytest.param("kassir", ("sozlamalar.edit", "ombor.edit"), 200, 200, id="kassir_override"),
]


@pytest.mark.parametrize("role,allow,tasdiq,yoqish", MATRITSA)
def test_RUXSAT_matritsasi_SCOPED_rejimda_ruxsat_DARVOZADAN_OLDIN(client, monkeypatch, role,
                                                                allow, tasdiq, yoqish):
    """Ruxsatsiz xodim «Ruxsat yo'q» ni oladi — ro'yxatdan tashqari filial yoki filialsiz
    so'rovda ham. Ruxsati bor xodim filialsiz so'rovda darvoza matnini oladi."""
    t = _dokon(role=role, allow=allow)
    pid = _mahsulot(t)
    _prod(monkeypatch, (t["cid"], t["bid"]))
    matn = _darvoza_matni()
    oldin = _iz(t["cid"])
    for kutilgan, so_rov in ((tasdiq, lambda bid: _tasdiq(client, t["H"], bid)),
                             (yoqish, lambda bid: _enable(client, t["H"], pid, bid))):
        for bid in (None, uuid.uuid4()):
            r = so_rov(bid)
            assert r.status_code == 403, r.text
            if kutilgan == 200:
                assert r.json()["detail"] == matn
            else:
                assert "Ruxsat yo'q" in r.json()["detail"], r.text
    assert _iz(t["cid"]) == oldin
    c = _tasdiq(client, t["H"], t["bid"])
    e = _enable(client, t["H"], pid, t["bid"])
    assert (c.status_code, e.status_code) == (tasdiq, yoqish), (c.text, e.text)
    if tasdiq != 200 and yoqish != 200:
        assert _iz(t["cid"]) == oldin


def test_TOKENSIZ_401_scoped_rejimda(client, monkeypatch):
    t = _dokon()
    pid = _mahsulot(t)
    _prod(monkeypatch, (t["cid"], t["bid"]))
    oldin = _iz(t["cid"])
    assert client.post(CONFIRM, json={"branch_id": str(t["bid"])}).status_code == 401
    assert client.post(ENABLE, json={"product_id": pid, "branch_id": str(t["bid"]),
                                      "reason": "tokensiz"}).status_code == 401
    assert _iz(t["cid"]) == oldin


# ══ 6. OCHILISH PARTIYALARI VALIDATSIYASI ════════════════════════════════════

@pytest.fixture(params=["env", "scoped"])
def yoqiladigan(request, client, monkeypatch):
    """Muddat kuzatuviga tayyor do'kon (zona tasdiqlangan) — ikkala ochiq rejimda."""
    t = _dokon()
    if request.param == "env":
        _ochiq(monkeypatch)
    else:
        _prod(monkeypatch, (t["cid"], t["bid"]))
    assert _tasdiq(client, t["H"], t["bid"]).status_code == 200
    return t


@pytest.mark.parametrize("sana", ["2026-13-01", "ertaga", "17.09.2026", "2026-02-30", " "])
@pytest.mark.parametrize("muddat_kuzatuvi", [True, False])
def test_ENABLE_BUZUQ_sana_400_500_EMAS_va_yozuvsiz(client, yoqiladigan, sana, muddat_kuzatuvi):
    """REGRESSIYA: `date.fromisoformat` tutilmagan `ValueError` edi — 500."""
    t = yoqiladigan
    pid = _mahsulot(t, qty=2)
    oldin = _iz(t["cid"])
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=muddat_kuzatuvi,
                opening_lots=[{"qty": 1, "unit_cost": 70, "expiry_date": "2099-01-01"},
                              {"qty": 1, "unit_cost": 70, "expiry_date": sana}])
    assert r.status_code == 400, r.text
    with _db() as db:
        nom = db.get(Product, uuid.UUID(pid)).name
    assert r.json()["detail"] == (f"'{nom}': ochilish partiyasi muddati sana EMAS — "
                                  f"YYYY-MM-DD ko'rinishida bering. Muddat taxmin qilinmaydi.")
    assert sana not in r.json()["detail"] or not sana.strip()
    assert _iz(t["cid"]) == oldin
    assert _mahsulot_holati(pid) == (False, False, None, 0)


def test_ENABLE_muddat_kuzatuvida_MUDDATSIZ_ochilish_partiyasi_400(client, yoqiladigan):
    t = yoqiladigan
    pid = _mahsulot(t, qty=3)
    oldin = _iz(t["cid"])
    for lots in ([{"qty": 3, "unit_cost": 70}],
                 [{"qty": 2, "unit_cost": 70, "expiry_date": "2099-01-01"},
                  {"qty": 1, "unit_cost": 70, "expiry_date": None}],
                 [{"qty": 3, "unit_cost": 70, "expiry_date": ""}]):
        r = _enable(client, t["H"], pid, t["bid"], track_expiry=True, opening_lots=lots)
        assert r.status_code == 400, r.text
        assert "`expiry_date` MAJBURIY" in r.json()["detail"], r.text
    assert _iz(t["cid"]) == oldin
    # NAZORAT: muddat kuzatuvisiz AYNI muddatsiz partiya o'tadi (qoida faqat track_expiry'da).
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=False,
                opening_lots=[{"qty": 3, "unit_cost": 70}])
    assert r.status_code == 200, r.text


def test_ENABLE_muddat_kuzatuvida_OTGAN_muddat_400_BUGUNGI_sana_200(client, yoqiladigan):
    t = yoqiladigan
    pid = _mahsulot(t, qty=2)
    biz = _biz(t["bid"])
    oldin = _iz(t["cid"])
    kecha = (biz - timedelta(days=1)).isoformat()
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True,
                opening_lots=[{"qty": 1, "unit_cost": 70, "expiry_date": biz.isoformat()},
                              {"qty": 1, "unit_cost": 70, "expiry_date": kecha}])
    assert r.status_code == 400, r.text
    with _db() as db:
        nom = db.get(Product, uuid.UUID(pid)).name
    assert r.json()["detail"] == (f"'{nom}': {kecha} muddati bugungi biznes sanasi ({biz}) dan "
                                  f"OLDIN — muddati o'tgan tovar qabul qilinmaydi.")
    assert _iz(t["cid"]) == oldin
    # NAZORAT: chegara saxiy — BUGUNGI sana yaroqli.
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True,
                opening_lots=[{"qty": 2, "unit_cost": 70, "expiry_date": biz.isoformat()}])
    assert r.status_code == 200, r.text
    assert _mahsulot_holati(pid)[:2] == (True, True)
    assert _mahsulot_holati(pid)[3] == 1


def test_ENABLE_YAROQLI_ochilish_partiyalari_200(client, yoqiladigan):
    t = yoqiladigan
    pid = _mahsulot(t, qty=5)
    biz = _biz(t["bid"])
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True, opening_lots=[
        {"qty": 2, "unit_cost": 70, "expiry_date": (biz + timedelta(days=3)).isoformat(),
         "batch_number": "V-1"},
        {"qty": 3, "unit_cost": 72, "expiry_date": (biz + timedelta(days=40)).isoformat()}])
    assert r.status_code == 200, r.text
    assert r.json()["lots_created"] == 2
    assert _mahsulot_holati(pid)[:2] == (True, True)


# ══ 7. OPERATOR ASBOBLARI — QIYMATSIZ ═══════════════════════════════════════

def test_CONFIG_AUDIT_royxat_holati_QIYMATSIZ(monkeypatch):
    from app.tools.config_audit import audit

    def qator():
        rows = [r for r in audit() if r["key"] == SCOPES]
        assert len(rows) == 1, rows
        return rows[0]

    _prod(monkeypatch)
    r = qator()
    assert (r["status"], r["critical"]) == ("OFF", False), r

    _prod(monkeypatch, (C1, B1), (C2, B2))
    r = qator()
    assert (r["status"], r["critical"]) == ("REVIEW", False), r
    assert "2 ta yozuv" in r["note"] and "malformed" in r["note"] and "closed" in r["note"]
    assert "rejim=scoped" in r["note"]

    _prod(monkeypatch, raw=f"{C1}:{B1},buzuq")
    r = qator()
    assert r["status"] == "REVIEW" and "BUZUQ" in r["note"], r
    assert "buzuq" not in r["note"], r          # buzuq yozuvning O'ZI ham chiqmaydi
    butun = str(audit())
    for sir in (C1, B1, C2, B2, C1.upper()):
        assert sir not in butun, sir


def test_BOOT_jurnali_rejim_va_SON_QIYMATSIZ(monkeypatch, capsys):
    from app import initdb
    _prod(monkeypatch, (C1, B1), (C2, B2))
    initdb._log_lot_activation_scope()
    out = capsys.readouterr().out
    assert "rejim=scoped" in out and "yozuvlari=2" in out, out
    for sir in (C1, B1, C2, B2):
        assert sir not in out
    _prod(monkeypatch, raw=f"{C1}:{B1},x")
    initdb._log_lot_activation_scope()
    out = capsys.readouterr().out
    assert "BUZUQ" in out and C1 not in out, out
