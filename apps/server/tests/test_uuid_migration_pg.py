# -*- coding: utf-8 -*-
"""ANIQ UUID MIGRATSIYASI — HAQIQIY PostgreSQL (Phase 5C).

Boot endi tipni O'ZGARTIRMAYDI (`tests/test_uuid_migration.py` buni statik mixlaydi); tuzatish
operator yurgizadigan versiyalangan migratsiya: `app/db/migrations/m2026_09_17_uuid_client_columns.py`
+ CLI `app/tools/schema_migrate.py`.

Bu fayl HAQIQIY bazada isbotlaydi:
  (a) varchar (production holati) + kanonik kichik/KATTA harfli qiymatlar + NULL -> preflight READY,
      `apply --commit` -> uuid, qiymatlar KICHIK harfda saqlanadi, indeks noyob/yaroqli;
      ikkinchi apply ALREADY_APPLIED va NOL DDL (`ddl_command_start` zondi);
  (b) allaqachon uuid -> preflight ALREADY_APPLIED, apply NOL DDL va LOCK ham so'ramaydi
      (jadvalni ushlab turgan o'quvchi ostida ham darhol qaytadi);
  (c) nokanonik qiymat / bo'sh satr / qavsli shakl / registr dublikati -> preflight BLOCKED
      (aniq kod), apply RAD, sxema va digest O'ZGARMAYDI; SALBIY NAZORAT: PG cast'i qavsli va
      defissiz shaklni QABUL qiladi, registr dublikati esa ALTER'da 23505 beradi;
  (d) qulf band -> apply cheklangan `lock_timeout` bilan chiqadi (exit 2), HECH NARSA o'zgarmaydi;
  (e) preflight'dan KEYIN struktura o'zgargan bo'lsa (yangi indeks) -> apply REJECTED (exit 3);
  (f) `--rehearse` DOIM qaytaradi — tip varchar qoladi;
  (g) revert -> varchar, keyin qayta apply -> uuid (digest barqaror);
  (h) SALBIY NAZORAT: varchar ustunda ORM `== uuid` 42883, apply'dan keyin ishlaydi, revert'dan
      keyin yana 42883;
  (i) BOOT: og'ishgan bazada `python -m app.initdb` exit 0, NOL DDL, `TAYYOR EMAS` + o'zgarmas
      migratsiya maslahati, tayyorlik `column_types=false`; apply'dan keyin 200;
  (j) DARVOZALAR: noto'g'ri `--expect-system-identifier` RAD; production sysid ikki bayroqsiz RAD;
      read-only isboti (negativ zond 25006) va preflight sessiyasida DDL imkonsiz;
  (k) BOG'LIQLIK tekshiruvi: KUTILGAN indeks bog'liqlik sifatida BLOK QILMAYDI, lekin
      HAQIQIY bog'liqlik (ko'rinish) BLOK QILADI — SALBIY NAZORAT: PG o'sha holatda
      `ALTER .. TYPE` ni O'ZI rad etadi.

Maqsad-baza: `tests/test_check_defs_pg.py::pg_target` (CI'da `-k external`).
"""
import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from tests.test_boot_locks_pg import _DDL_PROBE, _boot, _built, _ddl_log, _fatal, _held, _holding
from tests.test_check_defs_pg import pg_target  # noqa: F401
from tests.test_runtime_columns_pg import (_UUID_COLS, _cash_row, _qr_row, _ready, _seed,
                                           _to_varchar, _types)

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIG = "2026-09-17.uuid-client-columns-v1"
IX = "ux_cashmov_client_uuid"


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _cli(url, *args, env_extra=None, timeout=300):
    """(kod, stdout, stderr). Sysid ruxsati ATAYLAB har chaqiruvda ANIQ beriladi."""
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test", PYTHONIOENCODING="utf-8")
    env.pop("RAILWAY_ENVIRONMENT_NAME", None)
    env.pop("PGOPTIONS", None)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-m", "app.tools.schema_migrate", *args], cwd=SRV,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def _sysid(eng) -> str:
    with eng.connect() as con:
        return str(con.execute(text("SELECT system_identifier::text FROM pg_control_system()")).scalar())


def _allow(eng) -> dict:
    return {"SAVDOOS_SCHEMA_MIGRATE_ALLOWED_SYSTEM_IDENTIFIERS": _sysid(eng)}


def _probe(eng):
    with eng.begin() as con:
        for stmt in _DDL_PROBE:
            con.execute(text(stmt))


def _clear_ddl(eng):
    with eng.begin() as con:
        con.execute(text("DELETE FROM boot_ddl_log"))


def _preflight(eng, url, out, *extra):
    return _cli(url, "preflight", "--migration", MIG, "--expect-system-identifier", _sysid(eng),
                "--out", out, *extra, env_extra=_allow(eng))


def _apply(eng, url, report, *extra, cmd="apply"):
    return _cli(url, cmd, "--migration", MIG, "--report", report,
                "--expect-system-identifier", _sysid(eng), *extra, env_extra=_allow(eng))


def _report(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _relfilenode(eng, table) -> int:
    with eng.connect() as con:
        return int(con.execute(text("SELECT relfilenode FROM pg_class WHERE oid = to_regclass(:t)"),
                               {"t": f"public.{table}"}).scalar())


def _index_state(eng, name=IX):
    with eng.connect() as con:
        r = con.execute(text(
            "SELECT i.indisunique, i.indisvalid, i.indisready, pg_get_indexdef(i.indexrelid) "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :n"),
            {"n": name}).first()
    return tuple(r) if r else None


def _digest(eng, table, col) -> tuple[int, str]:
    with eng.connect() as con:
        r = con.execute(text(
            f'SELECT count(*), md5(coalesce(string_agg("id"::text || \'=\' || '
            f'coalesce(lower("{col}"::text), \'-\'), \',\' ORDER BY "id"::text), \'\')) '
            f'FROM public."{table}"')).one()
    return int(r[0]), r[1]


def _values(eng, table, col) -> list:
    with eng.connect() as con:
        return [r[0] for r in con.execute(text(
            f'SELECT "{col}"::text FROM public."{table}" ORDER BY "id"::text'))]


def _seed_drifted(eng, *, with_values=True):
    """Production holati: uchala ustun varchar. Kanonik kichik + KATTA harfli + NULL."""
    ids = _seed(eng)
    _to_varchar(eng)
    vals = {}
    if with_values:
        cm_lower, cm_upper = str(uuid.uuid4()), str(uuid.uuid4()).upper()
        qr_sale, qr_client = str(uuid.uuid4()).upper(), str(uuid.uuid4())
        with eng.begin() as con:
            _cash_row(con, ids["shift"], cm_lower, 1)
            _cash_row(con, ids["shift"], cm_upper, 2)
            _cash_row(con, ids["shift"], None, 3)
            _qr_row(con, qr_sale, qr_client, 1)
            _qr_row(con, None, None, 2)
        vals = {"cm_lower": cm_lower, "cm_upper": cm_upper, "qr_sale": qr_sale,
                "qr_client": qr_client}
    return ids, vals


# ══ (a) VARCHAR -> UUID: preflight READY, apply, qiymatlar SAQLANADI ═════════

def test_PG_preflight_READY_apply_UUID_qiymatlar_KICHIK_harfda_SAQLANADI_ikkinchi_apply_NOL_DDL(
        pg_target, tmp_path):
    from app.core import required_schema as rs
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        _ids, vals = _seed_drifted(eng)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)
        before = {(t, c): _digest(eng, t, c) for t, c in _UUID_COLS}
        _probe(eng)

        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0, (out, err)
        rep = _report(rep_path)
        assert rep["verdict"] == "READY", rep["verdict"]
        cm = next(v for v in rep["values"]["columns"] if v["table"] == "cash_movements")
        assert (cm["canonical_lower"], cm["canonical_other_case"], cm["null"], cm["empty"],
                cm["noncanonical"]) == (1, 1, 1, 0, 0), cm
        assert rep["read_only_proof"]["before"]["probe"].startswith("rejected"), rep
        assert rep["plan_sha256"] and rep["report_sha256"], rep
        blob = json.dumps(rep) + out + err
        for v in vals.values():                       # QIYMAT hech qayerda chiqmaydi
            assert v not in blob and v.lower() not in blob, v
        assert _ddl_log(eng) == [], "preflight DDL yubordi"

        # Mashq: hech narsa o'zgarmaydi (f).
        code, out, err = _apply(eng, pg_target, rep_path, "--rehearse")
        assert code == 0, (out, err)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)

        rel_before = {t: _relfilenode(eng, t) for t in ("cash_movements", "qr_payments")}
        _clear_ddl(eng)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 0, (out, err)
        ddl = _ddl_log(eng)
        assert [tag for tag, _q in ddl] == ["ALTER TABLE"] * 2, ddl   # har jadvalga BITTA
        assert all("TYPE uuid" in q and "lower(" in q for _t, q in ddl), ddl
        assert set(_types(eng).values()) == {"uuid"}, _types(eng)
        assert {t: _relfilenode(eng, t) for t in rel_before} != rel_before, "jadval qayta yozilmadi"
        assert {(t, c): _digest(eng, t, c) for t, c in _UUID_COLS} == before, "qiymat o'zgardi"
        assert sorted(x for x in _values(eng, "cash_movements", "client_uuid") if x) == sorted(
            [vals["cm_lower"].lower(), vals["cm_upper"].lower()])
        assert None in _values(eng, "cash_movements", "client_uuid"), "NULL yo'qoldi"
        u, valid, ready, _def = _index_state(eng)
        assert (u, valid, ready) == (True, True, True), _index_state(eng)
        assert rs.column_type_problems(eng) == []

        code, out, err = _cli(pg_target, "verify", "--migration", MIG,
                              "--expect-system-identifier", _sysid(eng), env_extra=_allow(eng))
        assert code == 0, (out, err)

        # Ikkinchi apply — ALREADY_APPLIED, NOL DDL.
        _clear_ddl(eng)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 0, (out, err)
        assert "ALREADY_APPLIED" in out, out
        assert _ddl_log(eng) == [], _ddl_log(eng)
    finally:
        eng.dispose()


# ══ (b) ALLAQACHON UUID — LOCK ham, DDL ham YO'Q ════════════════════════════

def test_PG_allaqachon_uuid_preflight_ALREADY_APPLIED_apply_LOCK_SORAMAYDI(pg_target, tmp_path):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        _seed(eng)
        assert set(_types(eng).values()) == {"uuid"}, _types(eng)
        _probe(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0, (out, err)
        assert _report(rep_path)["verdict"] == "ALREADY_APPLIED", _report(rep_path)

        # O'quvchi ACCESS SHARE ushlab turibdi: LOCK so'ralganda apply `lock_timeout` gacha
        # KUTARDI. Demak tez qaytishi — LOCK umuman so'ralmaganining isboti.
        with _holding(eng, "SELECT 1 FROM cash_movements") as (h,):
            assert _held(eng, h.pid, "cash_movements", "AccessShareLock")
            t0 = time.monotonic()
            code, out, err = _apply(eng, pg_target, rep_path, "--commit",
                                    "--lock-timeout-ms", "60000")
            took = time.monotonic() - t0
        assert code == 0, (out, err)
        assert "ALREADY_APPLIED" in out, out
        assert _ddl_log(eng) == [], _ddl_log(eng)
        assert took < 40, f"apply qulf kutdi ({took:.1f}s) — LOCK so'ralgan"
    finally:
        eng.dispose()


# ══ (c) QIYMAT SINFLARI — BLOCKED, apply RAD ════════════════════════════════

_MAXFIY = "not-a-uuid-MAXFIY-42"


@pytest.mark.parametrize("bad,code_want", [
    (_MAXFIY, "UUID_NONCANONICAL"),
    ("", "UUID_EMPTY_STRING"),
    ("{" + "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11" + "}", "UUID_NONCANONICAL"),
    ("a0eebc999c0b4ef8bb6d6bb9bd380a11", "UUID_NONCANONICAL"),
    ("a0eebc99-9c0b4ef8-bb6d-6bb9-bd380a11", "UUID_NONCANONICAL"),
    (" a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11", "UUID_NONCANONICAL"),
    ("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11\n", "UUID_NONCANONICAL"),
])
def test_PG_KANONIK_BOLMAGAN_qiymat_preflight_BLOCKED_apply_RAD_sxema_OZGARMAYDI(
        pg_target, tmp_path, bad, code_want):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        ids, _vals = _seed_drifted(eng, with_values=False)
        with eng.begin() as con:
            _cash_row(con, ids["shift"], bad, 1)
        before = _digest(eng, "cash_movements", "client_uuid")
        rel = _relfilenode(eng, "cash_movements")
        _probe(eng)

        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 3, (out, err)
        rep = _report(rep_path)
        assert rep["verdict"] == "BLOCKED", rep["verdict"]
        assert code_want in [f["code"] for f in rep["findings"]], rep["findings"]
        if len(bad.strip()) > 8:                       # bo'sh satr/qisqa shakl tekshirib bo'lmaydi
            assert bad.strip() not in (json.dumps(rep) + out + err), "qiymat chiqdi"

        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 3, (out, err)
        assert _ddl_log(eng) == [], _ddl_log(eng)
        assert _types(eng)[("cash_movements", "client_uuid")] == "varchar"
        assert _digest(eng, "cash_movements", "client_uuid") == before
        assert _relfilenode(eng, "cash_movements") == rel

        # MUSBAT NAZORAT: qiymat tuzatilgach AYNI yo'l o'tadi.
        with eng.begin() as con:
            con.execute(text("UPDATE cash_movements SET client_uuid = :g"), {"g": str(uuid.uuid4())})
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0 and _report(rep_path)["verdict"] == "READY", (out, err)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 0, (out, err)
        assert _types(eng)[("cash_movements", "client_uuid")] == "uuid"
    finally:
        eng.dispose()


def test_PG_NAZORAT_PG_casti_QAVSLI_va_DEFISSIZ_shaklni_QABUL_qiladi_siyosat_QATIYROQ(pg_target):
    """Eski boot `USING c::uuid` edi — ya'ni bu shakllar JIMGINA o'tib ketardi."""
    from sqlalchemy.exc import DBAPIError
    u = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
    forms = {"qavsli": "{" + u + "}", "defissiz": u.replace("-", ""), "bosh_boshliq": " " + u,
             "satr_oxiri": u + "\n", "bosh_satr": "", "matn": _MAXFIY}
    _built(pg_target)
    eng = create_engine(pg_target)
    accepted = {}
    try:
        with eng.connect() as con:
            for name, txt in forms.items():
                sp = con.begin_nested()
                try:
                    con.execute(text("SELECT CAST(:v AS uuid)"), {"v": txt})
                    accepted[name] = True
                except DBAPIError as e:
                    accepted[name] = False
                    assert getattr(e.orig, "sqlstate", None) == "22P02", e
                sp.rollback()
    finally:
        eng.dispose()
    print("PG uuid cast qabul qiladi:", accepted)      # hujjatlashtiriladi (runbook §5)
    # ASOSIY FAKT: cast bizning siyosatdan YUMSHOQ — eski `USING c::uuid` bu shakllarni
    # JIMGINA uuid qilardi, yangi siyosat esa ularni BLOCK qiladi (yuqoridagi parametrli test).
    assert accepted["qavsli"] and accepted["defissiz"], accepted
    assert accepted["bosh_satr"] is False and accepted["matn"] is False, accepted


def test_PG_REGISTR_DUBLIKATI_noyob_kalitda_BLOCKED_nazorat_ALTER_23505_beradi(pg_target, tmp_path):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        ids, _ = _seed_drifted(eng, with_values=False)
        dup = str(uuid.uuid4())
        with eng.begin() as con:
            _cash_row(con, ids["shift"], dup, 1)
            _cash_row(con, ids["shift"], dup.upper(), 2)
        _probe(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 3, (out, err)
        rep = _report(rep_path)
        assert "UUID_CASE_DUPLICATE_IN_UNIQUE_KEY" in [f["code"] for f in rep["findings"]], rep
        assert rep["values"]["case_duplicates"][0]["groups"] == 1, rep["values"]

        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 3, (out, err)
        assert _ddl_log(eng) == [], _ddl_log(eng)

        # SALBIY NAZORAT: tekshiruv bo'lmaganda indeks qayta qurilishida 23505.
        with pytest.raises(IntegrityError) as ei:
            with eng.begin() as con:
                con.execute(text('ALTER TABLE cash_movements ALTER COLUMN client_uuid '
                                 'TYPE uuid USING client_uuid::uuid'))
        assert getattr(ei.value.orig, "sqlstate", None) == "23505", ei.value

        # NAZORAT: AYNI juftlik BOSHQA smenalarda — READY (noyoblik buzilmaydi).
        with eng.begin() as con:
            con.execute(text("DELETE FROM cash_movements"))
        ids2 = _seed(eng)
        with eng.begin() as con:
            _cash_row(con, ids["shift"], dup, 1)
            _cash_row(con, ids2["shift"], dup.upper(), 2)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0 and _report(rep_path)["verdict"] == "READY", (out, err)
    finally:
        eng.dispose()


# ══ (k) BOG'LIQLIK: KUTILGAN INDEKS BLOK EMAS, KO'RINISH — BLOK ═════════════

def test_PG_KUTILGAN_INDEKS_boglilik_sifatida_BLOK_QILMAYDI_KORINISH_esa_BLOK_QILADI(
        pg_target, tmp_path):
    """NUQSON EDI: indeks `pg_class` da yashaydi, ya'ni uning `pg_depend` yozuvi
    `classid='pg_index'` EMAS, `classid='pg_class'`. Sinf NOMI bo'yicha istisno qilinganda
    `ux_cashmov_client_uuid` (qism indeks — kalit ustun + `WHERE` sharti uchun IKKI yozuv)
    «kutilmagan bog'liqlik» bo'lib, HAR BIR preflight BLOCKED chiqardi va migratsiya
    umuman ishlamasdi. Endi BOG'LIQ obyektning `relkind` iga qaraladi.

    Tekshiruv O'CHIRILMAGANINING isboti — pastdagi ko'rinish (`pg_rewrite`) nazorati.
    """
    from sqlalchemy.exc import DBAPIError
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        _seed_drifted(eng, with_values=False)
        # 1. FAKT: kutilgan indeks maqsad ustunga `classid='pg_class'` bilan bog'langan.
        with eng.connect() as con:
            n = int(con.execute(text(
                "SELECT count(*) FROM pg_depend d JOIN pg_class dc ON dc.oid = d.objid "
                "JOIN pg_class c ON c.oid = d.refobjid "
                "JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid "
                "WHERE d.refclassid = 'pg_class'::regclass AND d.classid = 'pg_class'::regclass "
                "AND c.relname = 'cash_movements' AND a.attname = 'client_uuid' "
                "AND dc.relname = :ix"), {"ix": IX}).scalar())
        assert n >= 1, "kutilgan indeks ustunga bog'lanmagan — test o'z mavzusini yo'qotdi"

        # 2. Shunga qaramay preflight TOZA: bog'liqlik ro'yxati bo'sh, indeks «kutilgan».
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0, (out, err)
        rep = _report(rep_path)
        assert rep["verdict"] == "READY", rep["verdict"]
        assert rep["structure"]["dependencies"] == [], rep["structure"]["dependencies"]
        assert "UUID_UNEXPECTED_DEPENDENCY" not in [f["code"] for f in rep["findings"]], rep
        ix = [i for i in rep["structure"]["indexes"] if i["name"] == IX]
        assert ix and ix[0]["expected"] is True, rep["structure"]["indexes"]

        # 3. SALBIY NAZORAT: HAQIQIY bog'liqlik (ko'rinish) — BLOK.
        with eng.begin() as con:
            con.execute(text("CREATE VIEW v_cashmov_uuid AS "
                             "SELECT id, client_uuid FROM cash_movements"))
        _probe(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 3, (out, err)
        rep = _report(rep_path)
        dep = [f for f in rep["findings"] if f["code"] == "UUID_UNEXPECTED_DEPENDENCY"]
        assert dep, rep["findings"]
        assert any(d["class"] == "pg_rewrite" and d["column"] == "client_uuid"
                   for d in rep["structure"]["dependencies"]), rep["structure"]["dependencies"]
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 3, (out, err)
        assert _ddl_log(eng) == [], _ddl_log(eng)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)

        # 4. NAZORAT: tekshiruv bo'lmasa PG O'ZI rad etadi — ya'ni bloker haqiqiy.
        with pytest.raises(DBAPIError) as ei:
            with eng.begin() as con:
                con.execute(text('ALTER TABLE cash_movements ALTER COLUMN client_uuid '
                                 'TYPE uuid USING client_uuid::uuid'))
        assert getattr(ei.value.orig, "sqlstate", None) == "0A000", ei.value

        # 5. Ko'rinish olib tashlangach — yana READY va apply o'tadi.
        with eng.begin() as con:
            con.execute(text("DROP VIEW v_cashmov_uuid"))
        _clear_ddl(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0 and _report(rep_path)["verdict"] == "READY", (out, err)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 0, (out, err)
        assert set(_types(eng).values()) == {"uuid"}, _types(eng)
    finally:
        eng.dispose()


# ══ (d) QULF BAND — CHEKLANGAN, HECH NARSA O'ZGARMAYDI ══════════════════════

def test_PG_qulf_BAND_apply_CHEKLANGAN_vaqtda_chiqadi_HECH_NARSA_ozgarmaydi(pg_target, tmp_path):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        _seed_drifted(eng)
        _probe(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0, (out, err)
        with _holding(eng, "SELECT 1 FROM cash_movements") as (h,):
            assert _held(eng, h.pid, "cash_movements", "AccessShareLock")
            t0 = time.monotonic()
            code, out, err = _apply(eng, pg_target, rep_path, "--commit", "--lock-timeout-ms", "1000")
            took = time.monotonic() - t0
            assert code == 2, (code, out, err)
            assert took < 120, took
            assert "QULF OLINMADI" in err, err
            assert f"pid={h.pid}" in err, err
            assert set(_types(eng).values()) == {"varchar"}, _types(eng)
            assert _ddl_log(eng) == [], _ddl_log(eng)
        # O'quvchi ketgach — o'tadi.
        code, out, err = _apply(eng, pg_target, rep_path, "--commit", "--lock-timeout-ms", "5000")
        assert code == 0, (out, err)
        assert set(_types(eng).values()) == {"uuid"}, _types(eng)
    finally:
        eng.dispose()


# ══ (e) ESKIRGAN HISOBOT — REJECTED ═════════════════════════════════════════

def test_PG_preflightdan_KEYIN_struktura_OZGARSA_apply_REJECTED(pg_target, tmp_path):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep_path = str(tmp_path / "report.json")
    try:
        _seed_drifted(eng)
        code, out, err = _preflight(eng, pg_target, rep_path)
        assert code == 0, (out, err)
        with eng.begin() as con:
            con.execute(text("CREATE INDEX ix_qr_client_uuid_tmp ON qr_payments (client_uuid)"))
        _probe(eng)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 3, (out, err)
        assert "REJECTED_STATE_CHANGED" in err, err
        assert [tag for tag, _q in _ddl_log(eng)] == [], _ddl_log(eng)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)

        # Buzilgan hisobot ham RAD etiladi (sha256 bog'lanishi).
        rep = _report(rep_path)
        rep["database"]["system_identifier"] = "1" * 19
        with open(rep_path, "w", encoding="utf-8") as f:
            json.dump(rep, f)
        code, out, err = _apply(eng, pg_target, rep_path, "--commit")
        assert code == 3 and "BUZILGAN" in err, (code, err)
    finally:
        eng.dispose()


# ══ (g) REVERT -> qayta APPLY ═══════════════════════════════════════════════

def test_PG_revert_varchar_ga_qaytaradi_keyin_qayta_apply_digest_BARQAROR(pg_target, tmp_path):
    _built(pg_target)
    eng = create_engine(pg_target)
    rep = str(tmp_path / "r1.json")
    rep2 = str(tmp_path / "r2.json")
    rep3 = str(tmp_path / "r3.json")
    try:
        _seed_drifted(eng)
        assert _preflight(eng, pg_target, rep)[0] == 0
        assert _apply(eng, pg_target, rep, "--commit")[0] == 0
        applied = {(t, c): _digest(eng, t, c) for t, c in _UUID_COLS}

        assert _preflight(eng, pg_target, rep2)[0] == 0
        code, out, err = _apply(eng, pg_target, rep2, "--commit", cmd="revert")
        assert code == 0, (out, err)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)
        assert {(t, c): _digest(eng, t, c) for t, c in _UUID_COLS} == applied, "revert qiymatni buzdi"
        assert _index_state(eng)[:3] == (True, True, True)

        assert _preflight(eng, pg_target, rep3)[0] == 0
        assert _apply(eng, pg_target, rep3, "--commit")[0] == 0
        assert set(_types(eng).values()) == {"uuid"}, _types(eng)
        assert {(t, c): _digest(eng, t, c) for t, c in _UUID_COLS} == applied

        # Allaqachon varchar bo'lgan bazada revert — NOL DDL; hisobotsiz/xato sysid bilan — 1.
        code, out, err = _cli(pg_target, "revert", "--migration", MIG, "--report", rep3,
                              "--expect-system-identifier", "9" * 19, "--commit",
                              env_extra=_allow(eng))
        assert code == 1, (out, err)
    finally:
        eng.dispose()


# ══ (h) SALBIY NAZORAT — 42883 oldin, apply'dan keyin ISHLAYDI ══════════════

def test_PG_NAZORAT_varchar_ORM_42883_apply_dan_keyin_ISHLAYDI_revert_dan_keyin_YANA_42883(
        pg_target, tmp_path):
    from app.models.payments import QrPayment
    from app.models.shifts import CashMovement
    _built(pg_target)
    eng = create_engine(pg_target)
    rep = str(tmp_path / "r.json")
    queries = (select(CashMovement.id).where(CashMovement.client_uuid == uuid.uuid4()),
               select(QrPayment.id).where(QrPayment.sale_id == uuid.uuid4()),
               select(QrPayment.id).where(QrPayment.client_uuid == uuid.uuid4()))
    try:
        _seed_drifted(eng, with_values=False)
        for q in queries:
            with Session(eng) as s:
                with pytest.raises(ProgrammingError) as ei:
                    s.execute(q).all()
                assert getattr(ei.value.orig, "sqlstate", None) == "42883", ei.value
        assert _preflight(eng, pg_target, rep)[0] == 0
        assert _apply(eng, pg_target, rep, "--commit")[0] == 0
        for q in queries:
            with Session(eng) as s:
                assert s.execute(q).all() == []
        rep2 = rep + ".2"
        assert _preflight(eng, pg_target, rep2)[0] == 0
        assert _apply(eng, pg_target, rep2, "--commit", cmd="revert")[0] == 0
        for q in queries:
            with Session(eng) as s:
                with pytest.raises(ProgrammingError):
                    s.execute(q).all()
    finally:
        eng.dispose()


# ══ (i) BOOT — NOL DDL, TAYYORLIK QIZIL, apply'dan keyin YASHIL ═════════════

def test_PG_BOOT_ogishgan_bazada_NOL_DDL_tayyorlik_QIZIL_apply_dan_keyin_YASHIL(
        pg_target, tmp_path):
    import app.initdb as I
    from app.core import required_schema as rs
    _built(pg_target)
    eng = create_engine(pg_target)
    rep = str(tmp_path / "r.json")
    try:
        ids, _ = _seed_drifted(eng, with_values=False)
        with eng.begin() as con:                       # kanonik qiymat: eski boot ALTER qilardi
            _cash_row(con, ids["shift"], str(uuid.uuid4()), 1)
        _probe(eng)

        code, out, _ = _boot(pg_target)
        assert code == 0, out[-2500:]
        assert not _fatal(out), out[-2500:]
        assert _ddl_log(eng) == [], f"boot DDL yubordi: {_ddl_log(eng)}"
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)
        assert "-> uuid" not in out, out[-2500:]
        for t, c in _UUID_COLS:
            assert f"[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: {t}.{c}" in out
        assert I._UUID_MIGRATION_HINT in out, out[-2500:]
        assert out.count(I._UUID_MIGRATION_HINT) == 1, "maslahat takrorlandi"

        # Jadvalni ochiq o'quvchi ushlab tursa ham boot KUTMAYDI va YIQILMAYDI.
        with _holding(eng, "SELECT 1 FROM cash_movements") as (h,):
            assert _held(eng, h.pid, "cash_movements", "AccessShareLock")
            code, out, _took = _boot(pg_target)
        assert code == 0 and not _fatal(out), out[-2500:]
        assert _ddl_log(eng) == [], _ddl_log(eng)

        res = _ready(pg_target)
        assert res["s"] == 503, res
        assert [k for k, v in res["b"]["checks"].items() if v is not True] == ["column_types"], res
        assert rs.missing(eng) == [], "tip muammosi partiya darvozasiga sizib kirdi"

        assert _preflight(eng, pg_target, rep)[0] == 0
        assert _apply(eng, pg_target, rep, "--commit")[0] == 0
        res = _ready(pg_target)
        assert res["s"] == 200 and res["b"]["checks"]["column_types"] is True, res
        _clear_ddl(eng)
        code, out, _ = _boot(pg_target)
        assert code == 0 and _ddl_log(eng) == [], (out[-2000:], _ddl_log(eng))
        assert I._UUID_MIGRATION_HINT not in out, out[-2000:]
    finally:
        eng.dispose()


# ══ (j) DARVOZALAR ══════════════════════════════════════════════════════════

def test_PG_DARVOZA_notogri_sysid_RAD_production_sysid_IKKI_BAYROQSIZ_RAD(pg_target, tmp_path,
                                                                         monkeypatch):
    from app.db.migrations import guard
    _built(pg_target)
    eng = create_engine(pg_target)
    rep = str(tmp_path / "r.json")
    try:
        _seed_drifted(eng, with_values=False)
        assert _preflight(eng, pg_target, rep)[0] == 0
        sysid = _sysid(eng)

        # 1. Noto'g'ri `--expect-system-identifier` (haqiqiy CLI).
        code, out, err = _cli(pg_target, "apply", "--migration", MIG, "--report", rep,
                              "--expect-system-identifier", "9" * 19, "--commit",
                              env_extra=_allow(eng))
        assert code == 1 and "RAD ETILDI" in err, (code, err)
        # 2. `--expect-system-identifier` umuman yo'q.
        code, out, err = _cli(pg_target, "apply", "--migration", MIG, "--report", rep, "--commit",
                              env_extra=_allow(eng))
        assert code == 1 and "MAJBURIY" in err, (code, err)
        # 3. Ruxsat ro'yxatisiz (env berilmagan) — production yo'liga tushadi.
        code, out, err = _cli(pg_target, "apply", "--migration", MIG, "--report", rep,
                              "--expect-system-identifier", sysid, "--commit")
        assert code == 1 and "PRODUCTION yo'li" in err, (code, err)
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)

        # 4. Sysid production ro'yxatiga TUSHSA (monkeypatch) — env kengaytmasi ham qutqara olmaydi.
        monkeypatch.setattr(guard, "PRODUCTION_SYSTEM_IDENTIFIERS", frozenset({sysid}))
        monkeypatch.setenv(guard.ALLOWED_SYSTEM_IDENTIFIERS_ENV, sysid)
        assert sysid not in guard.allowed_system_identifiers()
        with eng.connect() as con:
            ident = guard.database_identity(con)
        common = dict(expect_system_identifier=sysid, reviewed_identity=ident,
                      session_read_only=False)
        assert guard.write_refusals(ident, env="test", platform="unknown",
                                    allow_production=False,
                                    confirm_production_system_identifier=None, **common)
        assert guard.write_refusals(ident, env="production", platform="production",
                                    allow_production=True,
                                    confirm_production_system_identifier=None, **common)
        assert guard.write_refusals(ident, env="production", platform="production",
                                    allow_production=True,
                                    confirm_production_system_identifier="9" * 19, **common)
        assert guard.write_refusals(ident, env="dev", platform="unknown", allow_production=True,
                                    confirm_production_system_identifier=sysid, **common)
        # IKKALA bayroq + muhit o'zini production deb e'lon qilgan -> RUXSAT (imkoniyat BOR).
        assert guard.write_refusals(ident, env="production", platform="production",
                                    allow_production=True,
                                    confirm_production_system_identifier=sysid, **common) == []
    finally:
        eng.dispose()


def test_PG_READ_ONLY_isboti_preflight_sessiyasida_YOZUV_IMKONSIZ(pg_target, tmp_path):
    from sqlalchemy.exc import DBAPIError

    from app.db.migrations import guard
    from app.tools import schema_migrate as SM
    _built(pg_target)
    eng = create_engine(pg_target)
    rep = str(tmp_path / "r.json")
    try:
        _seed_drifted(eng, with_values=False)
        code, out, err = _preflight(eng, pg_target, rep)
        assert code == 0, (out, err)
        proof = _report(rep)["read_only_proof"]
        assert proof["before"]["transaction_read_only"] == "on", proof
        assert proof["before"]["transaction_isolation"] == "repeatable read", proof
        assert "25006" in proof["before"]["probe"] and proof["after"]["enforced"] is True, proof

        # AYNI sessiyada DDL — 25006 (ya'ni preflight yozuvni FIZIK qila olmaydi).
        ro_eng, con, _p = SM._read_only_session(pg_target, 30_000)
        try:
            sp = con.begin_nested()
            with pytest.raises(DBAPIError) as ei:
                con.execute(text("ALTER TABLE cash_movements ALTER COLUMN client_uuid "
                                 "TYPE uuid USING client_uuid::uuid"))
            assert getattr(ei.value.orig, "sqlstate", None) == guard.PG_READ_ONLY_SQLSTATE, ei.value
            sp.rollback()
        finally:
            con.rollback()
            con.close()
            ro_eng.dispose()
        assert set(_types(eng).values()) == {"varchar"}, _types(eng)
    finally:
        eng.dispose()
