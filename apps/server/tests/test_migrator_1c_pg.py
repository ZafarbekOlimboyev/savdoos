# -*- coding: utf-8 -*-
"""Migrator V1 — HAQIQIY POSTGRES (mahalliy pgserver + CI'da PostgreSQL 18).

SQLite nimani o'lchay olmaydi va bu fayl nimani isbotlaydi:
  · quruq yurish sessiyasi DB darajasida read-only (ReadOnlySqlTransaction) va XID OLMAYDI;
  · Numeric(14,2)/(14,3) ga Decimal AYNAN yoziladi va AYNAN o'qiladi;
  · 10 000 mahsulotli sintetik eksport: quruq yurish deterministik, apply bitta tranzaksiyada,
    kutilgan jami bilan mos, takroriy apply rad etiladi, so'rovlar soni katalog hajmiga bog'liq emas;
  · ikki PARALLEL apply — faqat bittasi yozadi (do'kon qatori FOR NO KEY UPDATE + ux_import_jobs_snapshot),
    ikkinchisi eski 10 s lock_timeout'dan UZOQ kutsa ham LockNotAvailable emas, AlreadyApplied oladi;
  · production system_identifier, kutilgan sysid'siz yoki boshqa bazada ko'rilgan hisobot bilan apply — yozuvsiz rad;
  · yozuvchi sessiyada read-only isboti PermissionError beradi (har qanday xato "isbot" emas).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
"""
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.orm import sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401


def _mk(url, read_only=False):
    opts = "-c default_transaction_read_only=on" if read_only else ""
    eng = create_engine(url, connect_args={"options": opts} if opts else {})
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def _allow(monkeypatch, url):
    """Vaqtinchalik test klasterini apply ruxsat ro'yxatiga qo'shadi (production sysid hech qachon qo'shilmaydi)."""
    eng = create_engine(url)
    try:
        with eng.connect() as con:
            sysid = con.execute(text("SELECT system_identifier::text FROM pg_control_system()")).scalar()
    finally:
        eng.dispose()
    monkeypatch.setenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", sysid)
    return sysid


UNIT_OF = {"шт": "dona", "кг": "kg", "л": "litr", "упак": "upak"}


def _seed(Session, legacy_from=None, n_legacy=0):
    from tests.migrator_1c_helpers import add_product, seed_company
    s = Session()
    comp, (br,) = seed_company(s, code="pg" + uuid.uuid4().hex[:8])
    legacy = []
    for i, p in enumerate((legacy_from or [])[:n_legacy]):
        legacy.append(add_product(s, comp, br, f"LEGACY {i}", barcodes=[p["barcodes"][0]["value"]],
                                  unit_code=UNIT_OF[p["unit"]["name"]],
                                  qty=str(i % 7), sell="10.00"))
    s.commit()
    out = (comp.code, br.id, [x.id for x in legacy])
    s.close()
    return out


def _dry(url, code, bundle):
    """CLI dry-run bilan AYNI: read-only sessiya, isbot, hisobotga baza identiteti."""
    from app.services.migrator_1c import classify as C
    from app.services.migrator_1c.catalog import load_snapshot
    from app.services.migrator_1c.guard import database_identity, prove_read_only
    from tests.migrator_1c_helpers import with_database
    eng, S = _mk(url, read_only=True)
    s = S()
    try:
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        ro = prove_read_only(s)
        rep = with_database(C.classify(bundle, load_snapshot(s, code)), database_identity(s))
        return rep, ro
    finally:
        s.rollback()
        s.close()
        eng.dispose()


def _xmax(url):
    eng, S = _mk(url)
    s = S()
    try:
        return s.execute(text("SELECT pg_snapshot_xmax(pg_current_snapshot())::text")).scalar()
    finally:
        s.close()
        eng.dispose()


def test_pg_quruq_yurish_read_only_XIDsiz_va_Numeric_aniq(pg_target, monkeypatch):
    from app.models.catalog import Product
    from app.models.inventory import Inventory
    from tests.migrator_1c_helpers import bundle_dict, g, load, prod
    _initdb(pg_target)
    _allow(monkeypatch, pg_target)
    eng, S = _mk(pg_target)
    code, bid, _ = _seed(S)
    b = load(bundle_dict([prod(g(1), "Aniq", stock=("12345678901.234",), retail="999999999999.99", purchase="0.01"),
                          prod(g(2), "Kichik", stock=("0.001",), retail="0.01")]))
    x0 = _xmax(pg_target)
    rep, ro = _dry(pg_target, code, b)
    rep2, _ = _dry(pg_target, code, b)
    assert ro["enforced"] and ro["transaction_read_only"] == "on" and ro["transaction_isolation"] == "repeatable read"
    assert "ReadOnlySqlTransaction" in ro["probe"] and "25006" in ro["probe"]
    assert rep["report_sha256"] == rep2["report_sha256"]
    assert _xmax(pg_target) == x0                                  # quruq yurish tranzaksiya raqami OLMAGAN

    from app.services.migrator_1c.apply import apply_migration
    from tests.migrator_1c_helpers import mapping_for
    s = S()
    out = apply_migration(s, b, rep, mapping_for(rep, bid, mode="INITIAL_CREATE"),
                          expect_system_identifier=rep["database"]["system_identifier"])
    s.commit()
    assert out["post_verify"]["ok"]
    s.close()
    s = S()
    p = s.query(Product).filter(Product.external_id == g(1)).one()
    assert p.base_sell_price == Decimal("999999999999.99") and p.base_buy_price == Decimal("0.01")
    q = s.query(Inventory.qty).filter(Inventory.product_id == p.id).scalar()
    assert q == Decimal("12345678901.234")
    q2 = s.query(Inventory.qty).join(Product, Product.id == Inventory.product_id).filter(Product.external_id == g(2)).scalar()
    assert q2 == Decimal("0.001")
    s.close()
    eng.dispose()


def test_pg_10k_sintetik_quruq_yurish_apply_idempotent(pg_target, monkeypatch):
    from app.models.inventory import StockMovement
    from app.services.migrator_1c.apply import AlreadyApplied, apply_migration, verify_state
    from app.services.migrator_1c.catalog import load_snapshot
    from tests.migrator_1c_helpers import load, mapping_for
    from tests.migrator_1c_synth import make_bundle
    _initdb(pg_target)
    _allow(monkeypatch, pg_target)
    eng, S = _mk(pg_target)
    d = make_bundle(10_000, seed=20260920)
    with_bc = [p for p in d["products"][40:] if p["barcodes"]]
    code, bid, legacy_ids = _seed(S, legacy_from=with_bc, n_legacy=250)
    b = load(d)

    statements = []
    def _count(*_a, **_k):
        statements.append(1)

    t0 = time.time()
    event.listen(eng, "before_cursor_execute", _count)
    s = S()
    s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    load_snapshot(s, code)
    s.rollback()
    s.close()
    event.remove(eng, "before_cursor_execute", _count)
    snap_queries = len(statements)
    assert snap_queries <= 15, snap_queries                        # katalog hajmiga bog'liq emas (N+1 yo'q)

    rep, ro = _dry(pg_target, code, b)
    t_dry = time.time() - t0
    rep_again, _ = _dry(pg_target, code, b)
    assert rep["report_sha256"] == rep_again["report_sha256"]      # deterministik
    s_ = rep["summary"]
    assert s_["total_1c_products"] == 10_000 and s_["candidate"] == 250 and rep["reconciliation"]["ok"]
    assert s_["blocked"] >= 6 and s_["excluded"] == 3

    decisions = {r["guid"]: {"action": "LINK", "product_id": r["target_product_id"]}
                 for r in rep["rows"] if r["classification"] == "CANDIDATE"}
    m = mapping_for(rep, bid, decisions=decisions)
    s = S()
    t1 = time.time()
    out = apply_migration(s, b, rep, m, expect_system_identifier=rep["database"]["system_identifier"])
    s.commit()
    t_apply = time.time() - t1
    s.close()
    assert out["post_verify"]["ok"], out["post_verify"]
    exp = out["expected"]
    assert exp["link"] == 250 and exp["create"] + exp["link"] + exp["reactivate"] == exp["ops"]
    assert out["post_verify"]["movements"] == exp["movements_total"]

    s = S()
    s.execute(text("SET TRANSACTION READ ONLY"))
    from app.models.imports import ImportJob
    job = s.query(ImportJob).filter(ImportJob.snapshot_id == f"1c-bundle:{b.file_sha256}").one()
    again = verify_state(s, job.company_id, job.id, job.column_mapping["plan"])
    assert again["ok"], again["failures"]
    from decimal import Decimal as D
    assert {b: D(v) for b, v in again["stock_by_mapped_branch"].items() if D(v)} ==         {b: D(v) for b, v in exp["stock_after_by_mapped_branch"].items() if D(v)}     # BAZADAN o'qilgan jami
    n_mov = s.query(func.count(StockMovement.id)).filter(StockMovement.ref_id == job.id).scalar()
    job_id = job.id
    s.rollback()
    s.close()

    s = S()
    with pytest.raises(AlreadyApplied):
        apply_migration(s, b, rep, m, expect_system_identifier=rep["database"]["system_identifier"])
    s.rollback()
    s.close()
    s = S()
    assert s.query(func.count(StockMovement.id)).filter(StockMovement.ref_id == job_id).scalar() == n_mov
    assert s.query(func.count(ImportJob.id)).filter(ImportJob.source == "1c").scalar() == 1
    s.close()
    eng.dispose()
    assert t_dry < 300 and t_apply < 600, (t_dry, t_apply)
    print(f"\n10k: dry-run {t_dry:.1f}s, apply {t_apply:.1f}s, snapshot so'rovlari {snap_queries}, harakatlar {n_mov}")


def test_pg_parallel_apply_faqat_bittasi_yozadi(pg_target, monkeypatch):
    import threading

    from app.models.imports import ImportJob
    from app.models.inventory import StockMovement
    from app.services.migrator_1c.apply import AlreadyApplied, apply_migration
    from tests.migrator_1c_helpers import bundle_dict, g, load, mapping_for, prod
    _initdb(pg_target)
    _allow(monkeypatch, pg_target)
    eng, S = _mk(pg_target)
    code, bid, _ = _seed(S)
    b = load(bundle_dict([prod(g(i), f"P{i}", stock=(str(i),)) for i in range(1, 30)]))
    rep, _ = _dry(pg_target, code, b)
    m = mapping_for(rep, bid, mode="INITIAL_CREATE")
    barrier = threading.Barrier(2)
    res = {}

    def run(key):
        s = S()
        try:
            barrier.wait(timeout=20)
            out = apply_migration(s, b, rep, m, expect_system_identifier=rep["database"]["system_identifier"])
            time.sleep(12)                                          # eski 10 s lock_timeout'dan UZOQ ushlaymiz
            s.commit()
            res[key] = out
        except Exception as e:      # noqa: BLE001
            s.rollback()
            res[key] = e
        finally:
            s.close()

    ts = [threading.Thread(target=run, args=(k,)) for k in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ok = [v for v in res.values() if isinstance(v, dict)]
    err = [v for v in res.values() if not isinstance(v, dict)]
    assert len(ok) == 1 and len(err) == 1 and isinstance(err[0], AlreadyApplied), res
    s = S()
    assert s.query(func.count(ImportJob.id)).filter(ImportJob.source == "1c").scalar() == 1
    job = s.query(ImportJob).filter(ImportJob.source == "1c").one()
    assert s.query(func.count(StockMovement.id)).filter(StockMovement.ref_id == job.id).scalar() == 29
    s.close()
    eng.dispose()


def test_pg_production_sysid_va_read_only_sessiyada_apply_rad(pg_target, monkeypatch):
    from app.services.migrator_1c import guard
    from app.services.migrator_1c.apply import apply_migration
    from tests.migrator_1c_helpers import bundle_dict, g, load, mapping_for, prod
    _initdb(pg_target)
    _allow(monkeypatch, pg_target)
    eng, S = _mk(pg_target)
    code, bid, _ = _seed(S)
    b = load(bundle_dict([prod(g(1), "X")]))
    rep, _ = _dry(pg_target, code, b)
    m = mapping_for(rep, bid, mode="INITIAL_CREATE")
    s = S()
    sysid = s.execute(text("SELECT system_identifier::text FROM pg_control_system()")).scalar()
    s.rollback()
    monkeypatch.setattr(guard, "PRODUCTION_SYSTEM_IDENTIFIERS", frozenset({sysid}))
    with pytest.raises(guard.ApplyForbidden, match="production bazasi"):          # allowlist'da bo'lsa ham
        apply_migration(s, b, rep, m, expect_system_identifier=sysid)
    s.rollback()
    monkeypatch.setattr(guard, "PRODUCTION_SYSTEM_IDENTIFIERS", frozenset())
    monkeypatch.delenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS")
    with pytest.raises(guard.ApplyForbidden, match="ruxsat ro'yxatida yo'q"):    # "yangi production" klasteri
        apply_migration(s, b, rep, m, expect_system_identifier=sysid)
    s.rollback()
    monkeypatch.setenv("MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS", sysid)
    s.close()
    monkeypatch.setattr(guard, "PRODUCTION_SYSTEM_IDENTIFIERS", frozenset())
    reng, RS = _mk(pg_target, read_only=True)
    rs = RS()
    with pytest.raises(guard.ApplyForbidden, match="read-only"):
        apply_migration(rs, b, rep, m, expect_system_identifier=sysid)
    rs.rollback()
    with pytest.raises(PermissionError, match="transaction_read_only"):
        rs.execute(text("SET TRANSACTION READ WRITE"))
        guard.prove_read_only(rs)                                     # yozuvchi tranzaksiya — isbot YO'Q
    rs.rollback()
    rs.close()
    reng.dispose()
    s = S()
    with pytest.raises(guard.ApplyForbidden, match="MAJBURIY"):
        apply_migration(s, b, rep, m)
    s.rollback()
    with pytest.raises(guard.ApplyForbidden, match="kutilgan baza"):
        apply_migration(s, b, rep, m, expect_system_identifier="1")
    s.rollback()
    other = dict(rep, database=dict(rep["database"], database="boshqa_baza"))
    with pytest.raises(guard.ApplyForbidden, match="BOSHQA bazada"):
        apply_migration(s, b, other, m, expect_system_identifier=sysid)
    s.rollback()
    s.close()
    s = S()
    assert s.execute(text("SELECT count(*) FROM import_jobs")).scalar() == 0
    s.close()
    eng.dispose()
