# -*- coding: utf-8 -*-
"""DO'KON × FILIAL DARVOZASI — HAQIQIY POSTGRES (Phase 5B.1, G).

SQLite nimani o'lchay olmaydi: `settings.value` — JSONB, `inventory` FOR UPDATE haqiqiy
qulf, `required_schema` sxema darvozasi haqiqiy introspeksiya bilan. Rad etilgan
yoqish qulfni olgan va 400 bilan qaytgan bo'lishi mumkin (buzuq sana) — tranzaksiya
qaytgach bazada HECH NARSA qolmasligi shu yerda isbotlanadi.

Bu fayl isbotlaydi (production shaklidagi muhit: `APP_ENV=production`, platforma
`production`, jarayon ichida monkeypatch):
  1. ro'yxatsiz, buzuq ro'yxat, filialsiz so'rov, begona/tasodifiy filial, ro'yxatda
     yo'q do'kon -> 403; `settings`, `products`, `stock_batches`, `audit_log` qator
     soni va DIGEST'i o'zgarmagan;
  2. buzuq ochilish sanasi -> 400, yozuvsiz;
  3. ro'yxatdagi juftlik: tasdiq 200 -> enable(track_expiry, ochilish partiyasi) 200,
     yozuvlar AYNAN kutilgan joyda, begona do'kon digest'i o'zgarmagan;
  4. ikki filialli do'kon: bitta filial ro'yxatda -> 403 yozuvsiz; ikkalasi -> 200;
     filialga biriktirilgan omborchi ko'rinmaydigan filialda -> 404 yozuvsiz.

Endpoint funksiyasi sessiya bilan TO'G'RIDAN chaqiriladi — PG testlaridagi odatiy naqsh
(`test_products_tracked_pg`), TestClient ilova engine'iga (SQLite) bog'langan.
Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401

SCOPES = "SAVDOOS_LOT_ACTIVATION_SCOPES"
TZ = "Asia/Tashkent"
NOW = datetime.now(timezone.utc)


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _baza(url):
    _initdb(url)
    eng = create_engine(url, connect_args={
        "options": "-c lock_timeout=15000 -c statement_timeout=60000"})
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def _prod(monkeypatch, *pairs, raw=None):
    """`_initdb` DAN KEYIN chaqiriladi — boot subprocess'i ro'yxatni meros olmasin."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    val = raw if raw is not None else ",".join(f"{c}:{b}" for c, b in pairs)
    if val:
        monkeypatch.setenv(SCOPES, val)
    else:
        monkeypatch.delenv(SCOPES, raising=False)


def _dokon(S, filiallar=1, qty=5):
    """Do'kon + N filial + ega + birinchi filialda qoldiqli mahsulot."""
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="G PG", code="gp" + uuid.uuid4().hex[:8], currency="UZS")
        s.add(co)
        s.flush()
        bids = []
        for i in range(filiallar):
            b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}", name=f"B{i + 1}",
                       timezone=TZ, is_active=True, created_at=NOW + timedelta(seconds=i))
            s.add(b)
            s.flush()
            bids.append(b.id)
        role = s.query(Role).filter(Role.code == "ega").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, role_id=role.id, full_name="G PG ega",
                     phone="+99895" + str(uuid.uuid4().int % 10_000_000).zfill(7),
                     status=EmployeeStatus.active, sec_epoch=0)
        s.add(e)
        unit = s.query(Unit).filter(Unit.code == "dona").one()
        p = Product(id=uuid.uuid4(), company_id=co.id, article_code="G-PG-" + uuid.uuid4().hex[:6],
                    name="G PG mahsulot", unit_id=unit.id, base_buy_price=Decimal("70"),
                    base_sell_price=Decimal("100"), tax_rate=0, is_active=True)
        s.add(p)
        s.flush()
        if qty:
            s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=bids[0],
                            qty=Decimal(str(qty)), min_qty=0, updated_at=NOW))
        s.commit()
        return {"cid": co.id, "bids": bids, "bid": bids[0], "emp": e.id, "pid": p.id}
    finally:
        s.close()


def _xodim(S, t, rol, allow=(), filial=None):
    from app.models.auth import Employee, EmployeeBranch, EmployeePermission, Permission, Role
    from app.models.enums import EmployeeStatus
    s = S()
    try:
        role = s.query(Role).filter(Role.code == rol).one()
        e = Employee(id=uuid.uuid4(), company_id=t["cid"], role_id=role.id, full_name=f"G PG {rol}",
                     phone="+99895" + str(uuid.uuid4().int % 10_000_000).zfill(7),
                     status=EmployeeStatus.active, sec_epoch=0)
        s.add(e)
        s.flush()
        for code in allow:
            perm = s.query(Permission).filter(Permission.code == code).one()
            s.add(EmployeePermission(employee_id=e.id, permission_id=perm.id, allowed=True))
        if filial is not None:
            s.add(EmployeeBranch(employee_id=e.id, branch_id=filial))
        s.commit()
        return e.id
    finally:
        s.close()


def _cagir(S, fn, data, emp_id):
    """Endpoint funksiyasi — (status, javob yoki detail). Rad etilsa sessiya QAYTARILADI
    (`get_db` yopilishi bilan AYNI natija)."""
    from app.models.auth import Employee
    s = S()
    try:
        emp = s.get(Employee, emp_id)
        try:
            return 200, fn(data=data, emp=emp, db=s)
        except HTTPException as e:
            s.rollback()
            return e.status_code, e.detail
    finally:
        s.close()


def _tasdiq(S, t, bid=None, emp=None):
    from app.api.v1.lots import ConfirmTzIn, confirm_timezone
    return _cagir(S, confirm_timezone, ConfirmTzIn(branch_id=bid), emp or t["emp"])


def _enable(S, t, bid=None, emp=None, pid=None, **kw):
    from app.api.v1.lots import EnableIn, enable_tracking
    body = EnableIn(product_id=pid or t["pid"], branch_id=bid, reason="PG: do'kon×filial", **kw)
    return _cagir(S, enable_tracking, body, emp or t["emp"])


_DIGEST = {
    "settings": ("SELECT count(*), md5(coalesce(string_agg(key || '|' || coalesce(branch_id::text, '-') "
                 "|| '|' || value::text || '|' || row_version::text, ';' ORDER BY key, branch_id), '')) "
                 "FROM settings WHERE company_id = :c"),
    "products": ("SELECT count(*), md5(coalesce(string_agg(id::text || '|' || track_lots::text || '|' "
                 "|| track_expiry::text || '|' || coalesce(lots_activated_at::text, '-'), ';' "
                 "ORDER BY id), '')) FROM products WHERE company_id = :c"),
    "stock_batches": ("SELECT count(*), md5(coalesce(string_agg(id::text || '|' || remaining_qty::text, "
                      "';' ORDER BY id), '')) FROM stock_batches WHERE company_id = :c"),
    "inventory": ("SELECT count(*), md5(coalesce(string_agg(i.product_id::text || '|' || "
                  "i.branch_id::text || '|' || i.qty::text, ';' ORDER BY i.product_id, i.branch_id), '')) "
                  "FROM inventory i JOIN products p ON p.id = i.product_id WHERE p.company_id = :c"),
}


def _iz(eng, *cids):
    """Har do'kon uchun qator soni + digest; audit — BUTUN jadval (begona id bilan yozilgan
    qator ham ko'rinsin); stock_batches — butun jadval soni ham."""
    with eng.connect() as con:
        out = {str(c): {k: tuple(con.execute(text(q), {"c": c}).one()) for k, q in _DIGEST.items()}
               for c in cids}
        out["audit_log"] = tuple(con.execute(text(
            "SELECT count(*), coalesce(max(id), 0) FROM audit_log")).one())
        out["stock_batches_jami"] = con.execute(text("SELECT count(*) FROM stock_batches")).scalar()
        out["settings_jami"] = tuple(con.execute(text(
            "SELECT count(*), coalesce(sum(row_version), 0) FROM settings")).one())
    return out


def _gate_text():
    from app.services import lot_policy as LP
    with pytest.raises(LP.LotActivationNotAllowed) as ei:
        LP.assert_activation_allowed()
    return str(ei.value)


# ══ 1–3. RAD YOZUVSIZ, RO'YXATDAGI JUFTLIK O'TADI ════════════════════════════

def test_PG_royxatsiz_BUZUQ_filialsiz_BEGONA_rad_YOZUVSIZ_royxatdagi_juftlik_OTADI(
        pg_target, monkeypatch):
    from app.services import lot_policy as LP
    eng, S = _baza(pg_target)
    try:
        a, b = _dokon(S), _dokon(S)
        oldin = _iz(eng, a["cid"], b["cid"])

        # ── ro'yxat yo'q ──
        _prod(monkeypatch)
        matn = _gate_text()
        for r in (_tasdiq(S, a, a["bid"]), _enable(S, a, a["bid"], legacy_unit_cost=70)):
            assert r == (403, matn), r
        assert _iz(eng, a["cid"], b["cid"]) == oldin

        # ── buzuq ro'yxat — hammasi yopiq ──
        _prod(monkeypatch, raw=f"{a['cid']}:{a['bid']},buzuq")
        for r in (_tasdiq(S, a, a["bid"]), _enable(S, a, a["bid"], legacy_unit_cost=70)):
            assert r == (403, matn), r
        assert _iz(eng, a["cid"], b["cid"]) == oldin

        # ── A ro'yxatda: filialsiz, begona, tasodifiy; B umuman ro'yxatda yo'q ──
        _prod(monkeypatch, (a["cid"], a["bid"]))
        rad = [_tasdiq(S, a), _enable(S, a, legacy_unit_cost=70),
               _tasdiq(S, a, b["bid"]), _enable(S, a, b["bid"], legacy_unit_cost=70),
               _tasdiq(S, a, uuid.uuid4()), _enable(S, a, uuid.uuid4(), legacy_unit_cost=70),
               _tasdiq(S, b, a["bid"]), _enable(S, b, a["bid"], legacy_unit_cost=70),
               _enable(S, b, a["bid"], pid=a["pid"], legacy_unit_cost=70),
               _tasdiq(S, b, b["bid"]), _enable(S, b, b["bid"], legacy_unit_cost=70),
               _tasdiq(S, b, uuid.uuid4())]
        assert rad == [(403, matn)] * len(rad), rad
        assert _iz(eng, a["cid"], b["cid"]) == oldin

        # ── tasdiq 200 ──
        st, body = _tasdiq(S, a, a["bid"])
        # `and` — rad etilsa `body` matn: qizil holatda TypeError emas, AYNI javob ko'rinsin.
        assert st == 200 and body["changed"] is True, (st, body)
        tasdiqdan_keyin = _iz(eng, a["cid"], b["cid"])
        assert tasdiqdan_keyin[str(b["cid"])] == oldin[str(b["cid"])]
        assert tasdiqdan_keyin["audit_log"][0] == oldin["audit_log"][0] + 1

        # ── buzuq ochilish sanasi: qulf olindi, 400, tranzaksiya qaytdi — yozuvsiz ──
        st, detail = _enable(S, a, a["bid"], track_expiry=True, opening_lots=[
            {"qty": 5, "unit_cost": 70, "expiry_date": "2026-02-30"}])
        assert st == 400 and "sana EMAS" in detail, (st, detail)
        s = S()
        try:
            biz = LP.business_date(s, a["bid"])
        finally:
            s.close()
        st, detail = _enable(S, a, a["bid"], track_expiry=True, opening_lots=[
            {"qty": 5, "unit_cost": 70, "expiry_date": (biz - timedelta(days=1)).isoformat()}])
        assert st == 400 and "muddati o'tgan" in detail, (st, detail)
        assert _iz(eng, a["cid"], b["cid"]) == tasdiqdan_keyin

        # ── enable(track_expiry) 200 ──
        muddat = biz + timedelta(days=30)
        st, body = _enable(S, a, a["bid"], track_expiry=True, opening_lots=[
            {"qty": 5, "unit_cost": 70, "expiry_date": muddat.isoformat(), "batch_number": "PG-1"}])
        assert st == 200, body
        assert (body["track_expiry"], body["lots_created"]) == (True, 1)
        keyin = _iz(eng, a["cid"], b["cid"])
        assert keyin[str(b["cid"])] == oldin[str(b["cid"])], "begona do'kon o'zgardi"
        assert keyin[str(a["cid"])]["stock_batches"][0] == 1
        assert keyin["audit_log"][0] == oldin["audit_log"][0] + 2
        with eng.connect() as con:
            row = con.execute(text(
                "SELECT track_lots, track_expiry, lots_activated_at IS NOT NULL FROM products "
                "WHERE id = :p"), {"p": a["pid"]}).one()
            assert tuple(row) == (True, True, True)
            lot = con.execute(text(
                "SELECT branch_id, expiry_date, remaining_qty, source_type FROM stock_batches "
                "WHERE product_id = :p"), {"p": a["pid"]}).one()
            assert (lot[0], lot[1], float(lot[2]), lot[3]) == (a["bid"], muddat, 5.0, "opening")
            conf = con.execute(text(
                "SELECT value -> 'expiry_tz_confirmed' ->> :b FROM settings "
                "WHERE company_id = :c AND branch_id IS NULL AND key = 'catalog'"),
                {"b": str(a["bid"]), "c": a["cid"]}).scalar()
            assert conf == TZ
            ent = sorted(r[0] for r in con.execute(text(
                "SELECT entity FROM audit_log WHERE id > :m"), {"m": oldin["audit_log"][1]}))
            assert ent == ["expiry_timezone", "product_lot_tracking"], ent
    finally:
        eng.dispose()


# ══ 4. KO'P FILIAL VA FILIAL KO'RINISHI ══════════════════════════════════════

def test_PG_IKKI_filial_QISMAN_royxat_rad_TOLIQ_royxat_otadi_KORINMAYDIGAN_filial_404(
        pg_target, monkeypatch):
    eng, S = _baza(pg_target)
    try:
        t = _dokon(S, filiallar=2, qty=0)
        b1, b2 = t["bids"]
        omb = _xodim(S, t, "omborchi", allow=("sozlamalar.edit",), filial=b1)
        oldin = _iz(eng, t["cid"])

        _prod(monkeypatch, (t["cid"], b1))
        matn = _gate_text()
        rad = [_tasdiq(S, t, b1), _enable(S, t, b1), _tasdiq(S, t, b2), _enable(S, t, b2)]
        assert rad == [(403, matn)] * 4, rad
        assert _iz(eng, t["cid"]) == oldin

        _prod(monkeypatch, (t["cid"], b1), (t["cid"], b2))
        # Biriktirilgan omborchi — ko'rinmaydigan filial: 404, yozuvsiz.
        assert _tasdiq(S, t, b2, emp=omb) == (404, "Filial topilmadi")
        assert _enable(S, t, b2, emp=omb) == (404, "Filial topilmadi")
        assert _iz(eng, t["cid"]) == oldin

        # NAZORAT: to'liq ro'yxat — ega ikkala filialda, omborchi o'z filialida o'tadi.
        assert _tasdiq(S, t, b2)[0] == 200
        assert _tasdiq(S, t, b1, emp=omb)[0] == 200
        st, body = _enable(S, t, b1, emp=omb)
        assert st == 200, body
        with eng.connect() as con:
            assert con.execute(text("SELECT track_lots FROM products WHERE id = :p"),
                               {"p": t["pid"]}).scalar() is True
    finally:
        eng.dispose()
