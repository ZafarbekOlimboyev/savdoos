# -*- coding: utf-8 -*-
"""VAQT ZONASI TASDIG'I × `settings.catalog` — HAQIQIY POSTGRES (Phase 5B, A).

SQLite nimani o'lchay olmaydi: `FOR UPDATE` u yerda no-op, yozuvchilar esa fayl
qulfi bilan baribir ketma-ket. Ilgari tasdiq ham, catalog V2 / migrator ham
qatorni QULFSIZ o'qib, BUTUN lug'atni qaytarib yozardi.

Bu fayl isbotlaydi:
  1. ikki filial tasdig'i parallel, qator bor       -> IKKALA yozuv ham saqlanadi;
  2. tasdiq × cutover yopilishi (ikkala tartibda)   -> `LIVE` + `cutover_at` VA tasdiq;
  3. qator yo'q, ikki BIRINCHI INSERT parallel       -> istisno chiqmaydi, BITTA qator, ikkala yozuv;
     migrator uslubidagi uzun tranzaksiya bilan      -> faqat SAVEPOINT qaytadi, undan OLDINGI
                                                        yozuvlar (import ishi) SAQLANADI;
  4. MANFIY NAZORAT: AYNI interleaving eski qulfsiz algoritm bilan yangilanishni YO'QOTADI
     (va birinchi INSERT poygasida istisno chiqaradi) — ya'ni sinov poygani haqiqatan KO'RADI;
  5. `_initdb` dan keyin `ux_settings_company_key` bor (3-band shunga tayanadi).

⚠️  INTERLEAVING MAJBURIY, TASODIFIY EMAS. Barrier bilan bir lahzada boshlangan ikki
    tranzaksiya ketma-ket bajarilib qolishi mumkin — u holda qulfsiz kod ham «to'g'ri»
    natija berardi. Shu bois birinchisi yozib, commit QILMAY turadi; ikkinchisi boshlanadi
    va u birinchisining qulfini KUTAYOTGANI `pg_blocking_pids` da ko'rilgach, birinchisi
    commit qiladi. Kutish ko'rilmasa sinov QIZIL (`kutdi`).
⚠️  OSILMAYDI: har ulanishda `lock_timeout`/`statement_timeout`, kuzatuv muddati
    cheklangan, iplar `join(timeout)` bilan.

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
"""
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401

TZ = "Asia/Tashkent"
CUT = "2026-09-17T10:00:00+00:00"
LOCK_MS = 15_000
KUTISH = 20.0


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _mk(url):
    """Ilova bilan AYNI sessiya sozlamasi (`autoflush=False`) + qulf/so'rov muddati."""
    eng = create_engine(url, connect_args={
        "options": f"-c lock_timeout={LOCK_MS} -c statement_timeout=60000"})
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, class_=Session)


def _seed(S, *, branches=2, catalog=None):
    from app.models.org import Branch, Company
    from app.models.settings import Setting
    s = S()
    co = Company(id=uuid.uuid4(), name="TZ PG", code="tz" + uuid.uuid4().hex[:8], currency="UZS")
    s.add(co)
    s.flush()
    bids = []
    for i in range(branches):
        b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i + 1}", name=f"B{i + 1}",
                   timezone=TZ, is_active=True)
        s.add(b)
        s.flush()
        bids.append(b.id)
    if catalog is not None:
        s.add(Setting(company_id=co.id, branch_id=None, key="catalog", value=catalog))
    s.commit()
    out = (co.id, bids)
    s.close()
    return out


def _catalog_rows(S, cid):
    from app.models.settings import Setting
    s = S()
    try:
        return [(r.value, r.row_version) for r in s.query(Setting).filter(
            Setting.company_id == cid, Setting.branch_id.is_(None),
            Setting.key == "catalog").all()]
    finally:
        s.close()


def _bloklangan(eng, b_pid, a_pid) -> bool:
    # Har so'rov YANGI tranzaksiyada: `pg_stat_*` tranzaksiya ichida keshlanadi.
    with eng.connect() as con:
        return bool(con.execute(
            text("SELECT CAST(:a AS integer) = ANY(pg_blocking_pids(CAST(:b AS integer)))"),
            {"a": a_pid, "b": b_pid}).scalar())


def _navbat(eng, S, birinchi, ikkinchi):
    """`birinchi` yozib commit QILMAY turadi; `ikkinchi` uning qulfini kutayotgani
    ko'rilgach `birinchi` commit qiladi.

    Qaytaradi: {"a": natija yoki istisno, "b": natija yoki istisno, "kutdi": bool}.
    """
    yozdi = threading.Event()
    pids: dict = {}
    out: dict = {"kutdi": False}

    def run_a():
        s = S()
        try:
            pids["a"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
            res = birinchi(s)
            s.flush()
            yozdi.set()
            oxiri = time.monotonic() + KUTISH
            while time.monotonic() < oxiri and "b" not in out:
                if "b" in pids and _bloklangan(eng, pids["b"], pids["a"]):
                    out["kutdi"] = True
                    break
                time.sleep(0.02)
            s.commit()
            out["a"] = res
        except Exception as e:      # noqa: BLE001
            s.rollback()
            out["a"] = e
        finally:
            yozdi.set()
            s.close()

    def run_b():
        s = S()
        try:
            if not yozdi.wait(KUTISH):
                raise TimeoutError("birinchi tranzaksiya yozib ulgurmadi")
            pids["b"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
            res = ikkinchi(s)
            s.commit()
            out["b"] = res
        except Exception as e:      # noqa: BLE001
            s.rollback()
            out["b"] = e
        finally:
            s.close()

    ta = threading.Thread(target=run_a, daemon=True)
    tb = threading.Thread(target=run_b, daemon=True)
    ta.start()
    tb.start()
    ta.join(90)
    tb.join(90)
    assert not ta.is_alive() and not tb.is_alive(), "tranzaksiya OSILDI"
    return out


def _xatosiz(r):
    assert not isinstance(r.get("a"), Exception) and not isinstance(r.get("b"), Exception), r
    assert r["kutdi"] is True, f"ikkinchi tranzaksiya qulfni KUTMADI — poyga oynasi ochilmadi: {r}"


def _confirm(cid, bid):
    from app.services import lot_policy as LP
    return lambda s: LP.confirm_tz(s, cid, bid)


def _cutover(cid):
    from app.services import catalog_import_v2 as civ2
    return lambda s: civ2.set_catalog_settings(s, cid, mode="LIVE", cutover_at=CUT,
                                               last_import_job_id="job-1")


# ── ESKI ALGORITM — AYNAN NUSXA (e1eb019), FAQAT MANFIY NAZORAT UCHUN ─────────
def _eski_get(s, cid):
    from app.models.settings import Setting
    row = s.query(Setting).filter(Setting.company_id == cid, Setting.branch_id.is_(None),
                                  Setting.key == "catalog").first()
    val = dict(row.value or {}) if row else {}
    for k, v in (("mode", "PRE_LIVE"), ("cutover_at", None), ("source_system", None),
                 ("last_import_job_id", None), ("last_snapshot_id", None),
                 ("last_content_sha256", None)):
        val.setdefault(k, v)
    return val


def _eski_set(s, cid, **patch):
    from app.models.settings import Setting
    row = s.query(Setting).filter(Setting.company_id == cid, Setting.branch_id.is_(None),
                                  Setting.key == "catalog").first()
    cur = _eski_get(s, cid)
    cur.update({k: v for k, v in patch.items() if v is not None})
    if row is None:
        s.add(Setting(company_id=cid, branch_id=None, key="catalog", value=cur))
    else:
        row.value = cur
        row.row_version = (row.row_version or 1) + 1
    s.flush()
    return cur


def _eski_confirm(cid, bid):
    def go(s):
        conf = dict(_eski_get(s, cid).get("expiry_tz_confirmed") or {})
        conf[str(bid)] = TZ
        _eski_set(s, cid, expiry_tz_confirmed=conf)
        return TZ
    return go


def _eski_cutover(cid):
    return lambda s: _eski_set(s, cid, mode="LIVE", cutover_at=CUT, last_import_job_id="job-1")


# ══ 1–3. QULF OSTIDA YOZUV ═══════════════════════════════════════════════════

def test_PG_ikki_filial_tasdigi_PARALLEL_IKKALASI_saqlanadi(pg_target):
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        base = {"mode": "PRE_LIVE", "source_system": "1c", "expiry_tz_confirmed": {}}
        cid, (b1, b2) = _seed(S, catalog=base)
        r = _navbat(eng, S, _confirm(cid, b1), _confirm(cid, b2))
        _xatosiz(r)
        assert r["a"] == (TZ, None, True) and r["b"] == (TZ, None, True), r
        rows = _catalog_rows(S, cid)
        assert len(rows) == 1, rows
        val, rv = rows[0]
        assert val == {**base, "expiry_tz_confirmed": {str(b1): TZ, str(b2): TZ}}
        assert rv == 3
    finally:
        eng.dispose()


@pytest.mark.parametrize("tartib", ["cutover_avval", "tasdiq_avval"])
def test_PG_tasdiq_x_CUTOVER_yopilishi_LIVE_va_tasdiq_SAQLANADI(pg_target, tartib):
    """Eski kodda tasdiq cutover'dan keyin eskirgan PRE_LIVE ni qaytarib yozib, yopilgan
    cutover'ni qayta OCHARDI; teskari tartibda esa cutover tasdiqni o'chirardi."""
    from app.services import catalog_import_v2 as civ2
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        cid, (b1,) = _seed(S, branches=1, catalog={"mode": "PRE_LIVE"})
        juft = ((_cutover(cid), _confirm(cid, b1)) if tartib == "cutover_avval"
                else (_confirm(cid, b1), _cutover(cid)))
        r = _navbat(eng, S, *juft)
        _xatosiz(r)
        rows = _catalog_rows(S, cid)
        assert len(rows) == 1, rows
        val = rows[0][0]
        assert val["mode"] == "LIVE" and val["cutover_at"] == CUT, val
        assert val["last_import_job_id"] == "job-1"
        assert val["expiry_tz_confirmed"] == {str(b1): TZ}, val
        s = S()
        try:
            assert civ2.is_live(s, cid) is True
        finally:
            s.close()
    finally:
        eng.dispose()


def test_PG_qatorsiz_ikki_BIRINCHI_insert_PARALLEL_istisnosiz_BITTA_qator(pg_target):
    """Ikkinchisi `ux_settings_company_key` da kutadi, SAVEPOINT qaytadi, qatorni QULF bilan
    qayta o'qib o'z yozuvini qo'shadi. Tashqi tranzaksiya qaytarilmaydi."""
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        cid, (b1, b2) = _seed(S)
        assert _catalog_rows(S, cid) == []
        r = _navbat(eng, S, _confirm(cid, b1), _confirm(cid, b2))
        _xatosiz(r)
        assert r["a"] == (TZ, None, True) and r["b"] == (TZ, None, True), r
        rows = _catalog_rows(S, cid)
        assert len(rows) == 1, rows
        assert rows[0][0] == {"expiry_tz_confirmed": {str(b1): TZ, str(b2): TZ}}
    finally:
        eng.dispose()


def test_PG_qatorsiz_BIRINCHI_insert_poygasi_MIGRATOR_tranzaksiyasini_QAYTARMAYDI(pg_target):
    """Migrator apply `set_catalog_settings` ni uzun tranzaksiya OXIRIDA chaqiradi (import ishi,
    mahsulotlar allaqachon yozilgan). Birinchi INSERT poygasida FAQAT savepoint qaytishi shart:
    tashqi tranzaksiya qaytsa import ishi jimgina yo'qolardi. Eski kodda esa IntegrityError
    butun tranzaksiyani yiqitardi.

    Qayta urinish yo'li HAQIQATAN o'tildi: `kutdi` — ikkinchisi faqat katalog INSERT'ida
    to'xtashi mumkin (import ishi va boshqa kalit birinchisi bilan to'qnashmaydi), qulf
    bo'shagach esa bu INSERT `ux_settings_company_key` da yiqiladi."""
    from datetime import datetime, timezone

    from app.models.imports import ImportJob, ImportStatus
    from app.services import catalog_import_v2 as civ2
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        cid, (b1,) = _seed(S, branches=1)
        assert _catalog_rows(S, cid) == []
        job_id = uuid.uuid4()

        def migrator(s):
            s.add(ImportJob(id=job_id, company_id=cid, source="1c", file_name="export-1",
                            status=ImportStatus.committed, created_at=datetime.now(timezone.utc)))
            s.flush()
            return civ2.set_catalog_settings(s, cid, source_system="1c",
                                             last_import_job_id=str(job_id))

        r = _navbat(eng, S, _confirm(cid, b1), migrator)
        _xatosiz(r)
        kutilgan = {"mode": "PRE_LIVE", "cutover_at": None, "source_system": "1c",
                    "last_import_job_id": str(job_id), "last_snapshot_id": None,
                    "last_content_sha256": None, "expiry_tz_confirmed": {str(b1): TZ}}
        assert r["a"] == (TZ, None, True), r
        assert r["b"] == kutilgan, r          # qulf ostida qayta o'qilgan tasdiq ham bor
        rows = _catalog_rows(S, cid)
        assert rows == [(kutilgan, 2)], rows
        s = S()
        try:
            assert s.get(ImportJob, job_id) is not None, "tashqi tranzaksiya QAYTARILDI"
        finally:
            s.close()
    finally:
        eng.dispose()


# ══ 4. MANFIY NAZORAT — SINOV POYGANI KO'RADI ═══════════════════════════════

def test_PG_MANFIY_NAZORAT_eski_QULFSIZ_algoritm_yangilanishni_YOQOTADI(pg_target):
    """AYNI `_navbat` interleaving'i eski o'qi-o'zgartir-yoz bilan: yangilanish yo'qoladi
    va birinchi INSERT poygasi istisno chiqaradi. Bu yashil bo'lmasa, 1–3 sinovlari
    qulfni emas, tasodifiy ketma-ketlikni o'lchagan bo'lardi."""
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        # (a) tasdiq × tasdiq — birinchi filial yozuvi YO'QOLADI
        cid, (b1, b2) = _seed(S, catalog={"mode": "PRE_LIVE", "expiry_tz_confirmed": {}})
        r = _navbat(eng, S, _eski_confirm(cid, b1), _eski_confirm(cid, b2))
        _xatosiz(r)
        val = _catalog_rows(S, cid)[0][0]
        assert val["expiry_tz_confirmed"] == {str(b2): TZ}, val

        # (b) cutover × tasdiq — yopilgan cutover QAYTA OCHILADI
        cid, (b1,) = _seed(S, branches=1, catalog={"mode": "PRE_LIVE"})
        r = _navbat(eng, S, _eski_cutover(cid), _eski_confirm(cid, b1))
        _xatosiz(r)
        val = _catalog_rows(S, cid)[0][0]
        assert val["mode"] == "PRE_LIVE" and val["cutover_at"] is None, val

        # (c) qatorsiz birinchi INSERT — ikkinchisi istisno bilan yiqiladi (API'da 500)
        cid, (b1, b2) = _seed(S)
        r = _navbat(eng, S, _eski_confirm(cid, b1), _eski_confirm(cid, b2))
        assert r["kutdi"] is True, r
        assert not isinstance(r["a"], Exception), r
        assert isinstance(r["b"], IntegrityError), r
        assert [v for v, _ in _catalog_rows(S, cid)][0]["expiry_tz_confirmed"] == {str(b1): TZ}
    finally:
        eng.dispose()


# ══ 5. SXEMA ═════════════════════════════════════════════════════════════════

def test_PG_initdb_dan_keyin_ux_settings_company_key_BOR(pg_target):
    """Birinchi INSERT poygasini faqat shu indeks ushlaydi: `UniqueConstraint(company_id,
    branch_id, key)` Postgres'da NULL `branch_id` ni takror deb hisoblamaydi."""
    from app.models.settings import Setting
    _initdb(pg_target)
    eng, S = _mk(pg_target)
    try:
        with eng.connect() as con:
            ddl = con.execute(text("SELECT indexdef FROM pg_indexes "
                                   "WHERE indexname = 'ux_settings_company_key'")).scalar()
        assert ddl is not None
        assert "UNIQUE" in ddl and "branch_id IS NULL" in ddl, ddl
        cid, _ = _seed(S, branches=1, catalog={"mode": "PRE_LIVE"})
        s = S()
        try:
            s.add(Setting(company_id=cid, branch_id=None, key="catalog", value={}))
            with pytest.raises(IntegrityError):
                s.flush()
        finally:
            s.rollback()
            s.close()
        assert len(_catalog_rows(S, cid)) == 1
    finally:
        eng.dispose()
