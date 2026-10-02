# -*- coding: utf-8 -*-
"""R-DDL — KOMPOZIT FK OTA-KALITLARI (haqiqiy PostgreSQL + haqiqiy SQLite).

Ikki nomzod kalit, FAQAT tasdiqlangan kelgusi kompozit FK talab qilgani uchun:

    uq_purchases_company_id  UNIQUE (company_id, id) ON purchases
        <- purchase_settlements (company_id, purchase_id)   [Phase 3]
    uq_employees_company_id  UNIQUE (company_id, id) ON employees
        <- creditors (company_id, employee_id)              [Phase 6a, A qarori]

Boshqa ota-kalit QO'SHILMAYDI (taxminiy emas). Bola jadvallar BU YERDA YARATILMAYDI.

⚠️  Postgres FK ota tomonida NOYOB va QISMAN BO'LMAGAN indeks talab qiladi. Mavjud
    `UNIQUE (company_id, doc_no)` boshqa ustunlar, `ux_purchases_client_uuid` /
    `ux_employees_client_uuid` / `ux_employees_phone_pw` esa QISMAN — hech biri yaramaydi.
⚠️  Ma'lumotga xavfsiz: `id` PK bo'lgani uchun `(company_id, id)` TA'RIF BO'YICHA noyob.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from app.core import required_schema as rs
from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401

_PARENTS = {
    "uq_purchases_company_id": ("purchases", ("company_id", "id")),
    "uq_employees_company_id": ("employees", ("company_id", "id")),
}

# Mavjud (TEGILMASLIGI kerak) indekslar — R-DDL ularni almashtirmaydi
_UNTOUCHED = ("ux_purchases_client_uuid", "ux_employees_client_uuid", "ux_employees_phone_pw")

_SHAPE_SQL = text(
    "SELECT c.relname, t.relname, i.indisunique, i.indisvalid AND i.indisready, "
    "       i.indpred IS NULL, pg_get_indexdef(i.indexrelid), c.oid, "
    "       (SELECT array_agg(a.attname ORDER BY k.ord) "
    "          FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
    "          JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum) "
    "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_class t ON t.oid = i.indrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname = :n")


def _shape(eng, name):
    """(jadval, noyob, yaroqli, qisman_emas, ta'rif, oid, ustunlar) yoki None."""
    with eng.connect() as con:
        r = con.execute(_SHAPE_SQL, {"n": name}).first()
    if r is None:
        return None
    return (r[0], r[1], bool(r[2]), bool(r[3]), bool(r[4]), r[5], r[6], tuple(r[7] or ()))


def _eng(url):
    return create_engine(url, future=True)


def _boot_raw(url):
    """`CompletedProcess` qaytaradi — boot YIQILISHI kutilgan holat uchun.

    (`test_check_defs_pg._initdb` returncode'ni O'ZI tasdiqlaydi va stdout qaytaradi.)"""
    import subprocess
    import sys

    from tests.test_check_defs_pg import SRV
    return subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                          text=True, timeout=900,
                          env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))


# ═══ 1+2+3) FRESH PG: nom + ustunlar + noyoblik + predikat ═══════════════════
def test_1_2_3_fresh_PG_ota_kalit_SHAKLI_ANIQ(pg_target):
    _initdb(pg_target)                 # `_initdb` returncode'ni O'ZI tasdiqlaydi
    eng = _eng(pg_target)
    try:
        for name, (table, cols) in _PARENTS.items():
            got = _shape(eng, name)
            assert got is not None, f"{name} YO'Q"
            _iname, gtable, uniq, valid, whole, ddef, _oid, gcols = got
            assert gtable == table, (name, gtable)
            assert uniq, f"{name} NOYOB EMAS"
            assert valid, f"{name} YAROQSIZ"
            assert whole, f"{name} QISMAN (FK ota-kaliti bo'la olmaydi)"
            assert gcols == cols, (name, gcols)
            assert "UNIQUE INDEX" in ddef and " WHERE " not in ddef, ddef
        # mavjud indekslar TEGILMAGAN (R-DDL almashtirmaydi)
        for name in _UNTOUCHED:
            assert _shape(eng, name) is not None, f"{name} yo'qoldi"
        # registr shakl muammosini KO'RMAYDI
        assert rs.parent_key_problems(eng) == []
    finally:
        eng.dispose()


# ═══ 4) UPGRADE PG: ota-kalitsiz MAVJUD baza -> boot qo'shadi ════════════════
def test_4_upgrade_PG_mavjud_bazaga_qoshiladi(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        # MAVJUD (eski) bazaga o'xshatamiz: ota-kalitlarni olib tashlaymiz + qator qo'shamiz
        with eng.begin() as con:
            for name in _PARENTS:
                con.execute(text(f"DROP INDEX {name}"))
        for name in _PARENTS:
            assert _shape(eng, name) is None
        problems = rs.parent_key_problems(eng)
        assert problems == [], "yo'q indeks SHAKL muammosi emas (u REQUIRED_INDEXES yo'lida)"
        assert any("uq_purchases_company_id" in m for m in rs.missing(eng)), rs.missing(eng)

        _initdb(pg_target)    # ikkinchi boot -> qo'shadi
        for name, (table, cols) in _PARENTS.items():
            got = _shape(eng, name)
            assert got is not None and got[2] and got[4] and got[7] == cols, (name, got)
        assert rs.missing(eng) == [] or not any(
            n in m for n in _PARENTS for m in rs.missing(eng)), rs.missing(eng)
    finally:
        eng.dispose()


# ═══ 5) IKKINCHI BOOT — no-op (indeks QAYTA QURILMAYDI) ═════════════════════
def test_5_ikkinchi_boot_indeksni_qayta_qurmaydi(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        before = {n: _shape(eng, n)[6] for n in _PARENTS}       # oid
        _initdb(pg_target)
        after = {n: _shape(eng, n)[6] for n in _PARENTS}
        assert before == after, "indeks DROP/CREATE qilingan (oid o'zgardi)"
    finally:
        eng.dispose()


# ═══ 6) PG FK OTA-KALIT ISBOTI: FK quriladi; indekssiz 42830 ════════════════
def test_6_PG_kompozit_FK_ota_kalitga_tayanadi(pg_target):
    """Bola jadval FAQAT shu sinov ichida (vaqtinchalik) — Phase 3/6a jadvallari YARATILMAYDI."""
    _initdb(pg_target)
    eng = _eng(pg_target)
    ch = "rddl_child_" + uuid.uuid4().hex[:8]
    try:
        with eng.begin() as con:
            con.execute(text(f"CREATE TABLE {ch} (id uuid PRIMARY KEY, company_id uuid, "
                             "purchase_id uuid)"))
            con.execute(text(f"ALTER TABLE {ch} ADD CONSTRAINT fk_{ch} "
                             "FOREIGN KEY (company_id, purchase_id) "
                             "REFERENCES purchases (company_id, id)"))
        # ota-kalitsiz AYNI FK 42830 beradi
        with eng.begin() as con:
            con.execute(text(f"ALTER TABLE {ch} DROP CONSTRAINT fk_{ch}"))
            con.execute(text("DROP INDEX uq_purchases_company_id"))
        with pytest.raises(ProgrammingError) as ei:
            with eng.begin() as con:
                con.execute(text(f"ALTER TABLE {ch} ADD CONSTRAINT fk_{ch} "
                                 "FOREIGN KEY (company_id, purchase_id) "
                                 "REFERENCES purchases (company_id, id)"))
        assert getattr(ei.value.orig, "sqlstate", None) == "42830", ei.value
    finally:
        with eng.begin() as con:
            con.execute(text(f"DROP TABLE IF EXISTS {ch}"))
        eng.dispose()


# ═══ 10) IFLOS SXEMA: ALMASHTIRILMAYDI, TAYYORLIK QIZIL ════════════════════
@pytest.mark.parametrize("kind", ["qisman", "boshqa_ustun"])
def test_10_iflos_indeks_almashtirilmaydi_tayyorlik_qizil(pg_target, kind):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("DROP INDEX uq_purchases_company_id"))
            if kind == "qisman":
                con.execute(text("CREATE UNIQUE INDEX uq_purchases_company_id ON purchases "
                                 "(company_id, id) WHERE deleted_at IS NULL"))
            else:
                con.execute(text("CREATE UNIQUE INDEX uq_purchases_company_id ON purchases "
                                 "(id, company_id)"))
        oid0 = _shape(eng, "uq_purchases_company_id")[6]
        _initdb(pg_target)    # boot TO'XTAMAYDI (shakl muammosi soft)
        got = _shape(eng, "uq_purchases_company_id")
        assert got[6] == oid0, "boot indeksni JIMGINA almashtirdi"
        probs = rs.parent_key_problems(eng)
        assert probs, "iflos shakl tayyorlikda KO'RINMADI"
        assert any(("QISMAN" if kind == "qisman" else "ustunlari mos emas") in p for p in probs), probs
        assert any("uq_purchases_company_id" in m for m in rs.missing(eng)), rs.missing(eng)
    finally:
        eng.dispose()


def test_10b_noyob_bolmagan_indeks_TAYYORLIKDA_tutiladi(pg_target):
    """Noyoblikning O'ZI yo'qolsa — TUTILADI, lekin boot TO'XTAMAYDI.

    ⚠️  SEVERITY QAYTA BAZALANDI (ega qarori 2026-09-29). Ilgari bu test `fatal_missing`
        ni va boot'ning YIQILISHINI talab qilardi. Yangi shartnoma: nomi bor-u noyob
        bo'lmagan majburiy indeks ishlab turgan do'konni O'CHIRMAYDI — u tayyorlikni
        QIZIL qiladi. Testning maqsadi O'ZGARMADI («jimgina sog'lom bo'lmasin»),
        o'zgargani — qaysi sinfda ko'rinishi.

    ⚠️  Va pul tomonini tayyorlikning O'ZI emas, `index_guard` fail-closed qiladi
        (`tests/test_index_guarantee_guard.py`, `PHASE1.md` §11.2 qamrovi)."""
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        with eng.begin() as con:
            con.execute(text("DROP INDEX uq_employees_company_id"))
            con.execute(text("CREATE INDEX uq_employees_company_id ON employees "
                             "(company_id, id)"))              # NOYOB EMAS
        probs = rs.unique_index_problems(eng)
        assert any("noyob EMAS" in m and "uq_employees_company_id" in m for m in probs), probs
        assert all(rs.is_soft(m) for m in probs), probs
        assert rs.ok(eng)[0] is False, "tayyorlik QIZIL bo'lishi SHART"
        #  BOOT esa O'TADI — ishlab turgan do'kon shakl muammosi uchun o'chmaydi.
        r = _boot_raw(pg_target)
        assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
        #  ⚠️  Va indeks JIMGINA almashtirilmaydi (fail-closed).
        assert any("noyob EMAS" in m for m in rs.unique_index_problems(eng)), \
            "boot indeksni jimgina tuzatdi"
    finally:
        eng.dispose()


# ═══ 11) REGISTR — INDEKS mexanizmi, CHECK registri EMAS ═══════════════════
def test_11_registr_indeks_mexanizmi():
    names = set(_PARENTS)
    assert names <= {n for n, _ in rs.REQUIRED_INDEXES}
    assert names == set(rs.PARENT_KEY_COLUMNS)
    assert not (names & {n for n, _ in rs.REQUIRED_PG_CONSTRAINTS}), "CHECK registrida"
    assert not (names & set(rs.CHECK_DEFINITIONS)), "CHECK ta'rifida"
    for cls in ("IDEMPOTENCY_INDEXES", "OPTIONAL_UNIQUE_INDEXES", "PERFORMANCE_INDEXES"):
        assert not (names & {n for n, _ in getattr(rs, cls)}), cls + " da ham bor"
    for name, (table, cols) in rs.PARENT_KEY_COLUMNS.items():
        assert (name, table) in rs.REQUIRED_INDEXES
        assert cols == ("company_id", "id")


# ═══ 12) BOOT TARTIBI — ota-kalit `_create_all` dan OLDIN ═══════════════════
def test_12_boot_tartibi_ota_kalit_create_all_dan_oldin():
    import inspect

    from app import initdb as I
    src = inspect.getsource(I.main)
    i_par, i_all = src.index("_ensure_parent_uniques()"), src.index("_create_all()")
    assert i_par < i_all, "ota-kalit qadami `_create_all` dan KEYIN — kompozit FK 42830 berardi"
    body = inspect.getsource(I._ensure_parent_uniques)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS {_nm} {_ddl}" in body
    for name, (table, _cols) in _PARENTS.items():
        assert f'("{name}", "ON {table} (company_id, id)")' in body, name
    for bad in ("DROP INDEX", "REINDEX", "ALTER INDEX"):
        assert bad not in body, "ota-kalit qadami mavjud indeksni o'zgartirmasin: " + bad
