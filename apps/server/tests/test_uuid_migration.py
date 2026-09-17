# -*- coding: utf-8 -*-
"""ANIQ SXEMA MIGRATSIYASI (Phase 5C) — SQLite / birlik.

⚠️  NUQSON (eski xulq). Boot (`initdb._repair_uuid_type_drift`) `varchar` qolgan uuid ustunlarini
    O'ZI `ALTER .. TYPE uuid USING c::uuid` bilan tuzatardi: production sxemasi deploy paytida
    JIMGINA o'zgarardi, qulf band bo'lsa `[FATAL]` + Railway qayta urinishi = crash-loop, skaner
    bilan ALTER orasidagi oynada yozilgan nokanonik qiymat («{uuid}», defissiz 32 hex) esa cast
    tomonidan JIMGINA qabul qilinardi. Endi boot HECH NARSA O'ZGARTIRMAYDI.

Bu fayl (Postgres'siz) mixlaydi:
  · STATIK: `initdb` da `ALTER .. TYPE` / `TYPE uuid` literali YO'Q va u migratsiya modulini
    na import qiladi, na `apply/revert` chaqiradi (salbiy nazorat — eski funksiya bo'lagi);
  · boot og'ishda o'zgarmas MASLAHAT satrini chiqaradi (migratsiya id + CLI), og'ish yo'qolsa —
    chiqarmaydi;
  · REYESTR: `MIGRATION_ID` sanali va noyob, `TARGETS` muzlatilgan va `required_schema.
    UUID_TYPED_COLUMNS` ni QOPLAYDI, kutilgan indeks ta'rifi `initdb` DDL'i bilan AYNI;
  · DARVOZALAR (toza funksiya): kutilgan sysid MAJBURIY, hisobot identiteti bog'lanadi, production
    sysid env kengaytmasi bilan ham RUXSAT ETILMAYDI, production yo'li IKKI bayroq + muhitning
    O'Z e'lonini talab qiladi (`APP_ENV` yo'qligi HECH QACHON ruxsat bermaydi);
  · SHARTNOMA: `plan_sha256` faqat STRUKTURA ustidan (qator sonlari uni o'zgartirmaydi), chiqish
    kodlari xaritasi;
  · CLI: SQLite'da HAR buyruq NOT_APPLICABLE + 0 va HECH NARSA yozmaydi (baza fayli ham
    yaratilmaydi), argument xatolari AYNAN 1 (argparse'ning standart 2 si «REVIEW» bilan
    chalkashmasin).

Haqiqiy Postgres (preflight/apply/verify/revert, qulf, qiymat sinflari, boot NOL DDL) —
`tests/test_uuid_migration_pg.py`.
"""
import ast
import json
import pathlib
import re

import pytest

import app.initdb as I
from app.core import required_schema as rs
from app.db.migrations import MIGRATIONS, get, ids
from app.db.migrations import contract as C
from app.db.migrations import guard as G
from app.db.migrations import m2026_09_17_uuid_client_columns as M
from app.tools import _common as CM
from app.tools import schema_migrate as SM
from tests.test_boot_locks import _func, _literals

MIG = "2026-09-17.uuid-client-columns-v1"


@pytest.fixture(autouse=True)
def _reset_stdout_mode():
    yield
    CM.set_stdout_json_only(False)


# ══ REYESTR VA MUZLATILGAN QAMROV ═══════════════════════════════════════════

def test_reyestr_MIGRATION_ID_sanali_TARGETS_MUZLATILGAN():
    assert M.MIGRATION_ID == MIG
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.[a-z0-9-]+-v\d+", M.MIGRATION_ID), M.MIGRATION_ID
    assert M.TARGETS == (("cash_movements", "client_uuid"), ("qr_payments", "sale_id"),
                         ("qr_payments", "client_uuid"))
    assert ids() == sorted(MIGRATIONS) and get(MIG) is M
    assert len(MIGRATIONS) == len({m.MIGRATION_ID for m in MIGRATIONS.values()}), "id takrorlangan"
    with pytest.raises(KeyError):
        get("yoq-migratsiya")


def test_TARGETS_required_schema_UUID_TYPED_COLUMNS_ni_QOPLAYDI():
    """Tayyorlik uuid TALAB qiladigan har ustun uchun TUZATADIGAN migratsiya bo'lishi SHART.

    ⚠️  `TARGETS` `UUID_TYPED_COLUMNS` dan IMPORT QILINMAYDI (ko'rib chiqilgan hisobot ma'nosi
        keyinchalik o'zgarmasin) — izchillik shu test bilan tekshiriladi.
    """
    covered = {p for m in MIGRATIONS.values() for p in m.TARGETS}
    assert set(rs.UUID_TYPED_COLUMNS) <= covered, sorted(set(rs.UUID_TYPED_COLUMNS) - covered)
    assert covered <= set(rs.UUID_TYPED_COLUMNS), sorted(covered - set(rs.UUID_TYPED_COLUMNS))
    for t, c in M.TARGETS:
        assert (t, c) in set(rs.REQUIRED_COLUMNS), f"{t}.{c} MAJBURIY ustunlar ro'yxatida emas"


def test_KUTILGAN_INDEKS_tarifi_initdb_DDL_i_bilan_AYNI():
    """Indeks `initdb` tomonidan quriladi — kutilgan ta'rif o'sha DDL'dan chetlashmasin."""
    src = pathlib.Path(I.__file__).read_text(encoding="utf-8")
    spec = M.EXPECTED_INDEXES["ux_cashmov_client_uuid"]
    assert spec == {"table": "cash_movements", "unique": True,
                    "columns": ("shift_id", "client_uuid"),
                    "predicate": "(client_uuid IS NOT NULL)"}
    assert ("CREATE UNIQUE INDEX IF NOT EXISTS ux_cashmov_client_uuid " in src)
    assert ("ON cash_movements (shift_id, client_uuid) WHERE client_uuid IS NOT NULL" in src)
    assert ("ux_cashmov_client_uuid", "cash_movements") in rs.IDEMPOTENCY_INDEXES


# ══ STATIK: BOOT TIPNI O'ZGARTIRMAYDI ═══════════════════════════════════════

_TYPE_CHANGE = re.compile(r"ALTER\s+COLUMN\s+\S+\s+TYPE\b", re.IGNORECASE)
_TYPE_UUID = re.compile(r"\bTYPE\s+uuid\b", re.IGNORECASE)


def _type_change_violations(src: str) -> tuple[list[str], int]:
    """(buzilishlar, tekshirilgan literal soni) — manbadagi HAR satr literali bo'yicha."""
    tree = ast.parse(src)
    bad, n = [], 0
    for lit, chain in _literals(tree):
        n += 1
        if _TYPE_CHANGE.search(lit.value) or _TYPE_UUID.search(lit.value):
            fn = _func(chain)
            bad.append(f"{lit.lineno}: `{fn.name if fn else '<modul>'}` da tip o'zgartirish: "
                       f"{lit.value[:70]!r}")
    return bad, n


def _migration_use_violations(src: str) -> list[str]:
    """Boot migratsiya modulini import qilmaydi va `apply/revert` chaqirmaydi."""
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") and (
                "db.migrations" in node.module or "schema_migrate" in node.module):
            bad.append(f"{node.lineno}: `from {node.module} import ...`")
        if isinstance(node, ast.Import):
            for al in node.names:
                if "db.migrations" in al.name or "schema_migrate" in al.name:
                    bad.append(f"{node.lineno}: `import {al.name}`")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in {"apply", "revert"}:
                bad.append(f"{node.lineno}: `{name}(...)` chaqirig'i")
    return bad


def test_STATIK_initdb_da_TIP_OZGARTIRISH_YOQ_va_migratsiya_CHAQIRILMAYDI():
    src = pathlib.Path(I.__file__).read_text(encoding="utf-8")
    bad, n = _type_change_violations(src)
    assert not bad, ("boot mavjud ustun TIPINI o'zgartiradi (jadval qayta yoziladi, ACCESS "
                     "EXCLUSIVE, qulfda crash-loop):\n  " + "\n  ".join(bad))
    assert n > 50, f"literallar juda kam ({n}) — tahlil buzilgan"
    assert "_repair_uuid_type_drift" not in src, "eski boot ta'miri qaytib kelgan"
    assert not _migration_use_violations(src), _migration_use_violations(src)
    # `main()` ketma-ketligida ham u yo'q.
    body = next(x for x in ast.parse(src).body
                if isinstance(x, ast.FunctionDef) and x.name == "main")
    steps = [c.value.func.id for c in body.body
             if isinstance(c, ast.Expr) and isinstance(c.value, ast.Call)
             and isinstance(c.value.func, ast.Name)]
    assert "_repair_uuid_type_drift" not in steps, steps
    assert steps.index("_ensure_columns") < steps.index("_ensure_indexes") < steps.index(
        "_verify_required_schema"), steps


def test_STATIK_salbiy_nazorat_ESKI_boot_tamirini_USHLAYDI():
    eski = (
        "def _repair_uuid_type_drift():\n"
        "    def _alter(table=table, col=col):\n"
        "        with engine.begin() as con:\n"
        "            con.execute(text('ALTER TABLE t ALTER COLUMN c TYPE uuid USING c::uuid'))\n"
        "    con.execute(text('ALTER TABLE t ALTER COLUMN row_version DROP DEFAULT'))\n"
    )
    bad, n = _type_change_violations(eski)
    assert n == 2 and len(bad) == 1 and "_alter" in bad[0], (n, bad)   # DROP DEFAULT — buzilish EMAS
    yomon = ("from app.db.migrations import get\n"
             "def main():\n"
             "    get('x').apply(con, reviewed_report=None)\n")
    assert len(_migration_use_violations(yomon)) == 2, _migration_use_violations(yomon)


# ══ BOOT MASLAHATI (o'zgarmas satr) ═════════════════════════════════════════

def test_MASLAHAT_satri_migratsiya_ID_si_va_CLI_ni_nomlaydi():
    assert MIG in I._UUID_MIGRATION_HINT
    assert "python -m app.tools.schema_migrate preflight" in I._UUID_MIGRATION_HINT
    assert I._UUID_MIGRATION_HINT.startswith("[schema] ")
    assert "\n" not in I._UUID_MIGRATION_HINT


def _verify_with(monkeypatch, *, types_bad):
    monkeypatch.setattr(rs, "fatal_missing", lambda b: [])
    monkeypatch.setattr(rs, "soft_missing", lambda b: [])
    monkeypatch.setattr(rs, "idempotency_missing", lambda b: [])
    monkeypatch.setattr(rs, "optional_unique_missing", lambda b: [])
    monkeypatch.setattr(rs, "performance_missing", lambda b: [])
    monkeypatch.setattr(rs, "column_type_problems", lambda b: list(types_bad))
    I._verify_required_schema()


def test_BOOT_ogish_bolsa_MASLAHAT_chiqadi_ogish_yoq_bolsa_CHIQMAYDI(monkeypatch, capsys):
    _verify_with(monkeypatch, types_bad=["ustun tipi uuid emas: cash_movements.client_uuid"])
    out = capsys.readouterr().out
    assert ("[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: "
            "cash_movements.client_uuid") in out, out
    assert I._UUID_MIGRATION_HINT in out, out
    assert out.count(I._UUID_MIGRATION_HINT) == 1, out
    assert "[FATAL]" not in out and "-> uuid" not in out, out

    _verify_with(monkeypatch, types_bad=[])
    out = capsys.readouterr().out
    assert I._UUID_MIGRATION_HINT not in out, out


# ══ DARVOZALAR (toza funksiya — bazasiz) ════════════════════════════════════

_IDENT = {"dialect": "postgresql", "system_identifier": "111", "database": "savdoos",
          "server_version_num": 180000, "current_user": "app"}


def _refuse(**kw):
    base = dict(ident=_IDENT, env="test", platform="unknown",
                expect_system_identifier="111", reviewed_identity=_IDENT,
                allow_production=False, confirm_production_system_identifier=None,
                session_read_only=False)
    base.update(kw)
    ident = base.pop("ident")
    return G.write_refusals(ident, **base)


def test_DARVOZA_ruxsat_etilgan_klasterda_YOZISH_MUMKIN(monkeypatch):
    monkeypatch.setenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, "111")
    assert _refuse() == []                                    # nazorat: yo'l ochiq


def test_DARVOZA_kutilgan_sysid_MAJBURIY_va_HISOBOT_bazaga_BOGLANADI(monkeypatch):
    monkeypatch.setenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, "111")
    assert "MAJBURIY" in " ".join(_refuse(expect_system_identifier=None))
    assert "kutilgan baza" in " ".join(_refuse(expect_system_identifier="222"))
    assert "BOSHQA bazada" in " ".join(_refuse(reviewed_identity={**_IDENT, "database": "boshqa"}))
    assert "BOSHQA bazada" in " ".join(_refuse(reviewed_identity=None))
    assert "read-only" in " ".join(_refuse(session_read_only=True))
    assert "faqat PostgreSQL" in " ".join(_refuse(ident={**_IDENT, "dialect": "sqlite"}))


def test_DARVOZA_APP_ENV_YOQ_bolsa_RAD_production_ikki_BAYROQ_talab_qiladi(monkeypatch):
    monkeypatch.setenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, "111")
    # `APP_ENV` yo'q/noma'lum -> production yo'li (fail-open DARS: yo'qlik ruxsat EMAS).
    assert "PRODUCTION yo'li" in " ".join(_refuse(env="unknown"))
    assert "PRODUCTION yo'li" in " ".join(_refuse(env="production", platform="production"))
    assert "PRODUCTION yo'li" in " ".join(_refuse(platform="production"))
    # Faqat bitta bayroq — RAD.
    assert "MAJBURIY" in " ".join(_refuse(env="production", platform="production",
                                          allow_production=True))
    assert "tasdiq mos emas" in " ".join(
        _refuse(env="production", platform="production", allow_production=True,
                confirm_production_system_identifier="222"))
    # Ikkala bayroq + muhit production — RUXSAT (imkoniyat BOR, lekin ATAYLAB).
    assert _refuse(env="production", platform="production", allow_production=True,
                   confirm_production_system_identifier="111") == []
    # Ruxsat ro'yxatidan TASHQARI klaster (efemer klon) — production yo'li. Bayroqlar bor,
    # lekin muhit o'zini `dev` deb aytmoqda: NIQOB ostida yozilmaydi.
    monkeypatch.delenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, raising=False)
    said = " ".join(_refuse(env="dev", platform="unknown", allow_production=True,
                            confirm_production_system_identifier="111"))
    assert "ruxsat ro'yxatida yo'q" in said and "E'LON QILMAGAN" in said, said
    # ⚠️  To'g'ri yo'l — efemer klonni ANIQ ruxsat ro'yxatiga qo'shish (bayroqlar emas).
    monkeypatch.setenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, "111")
    assert _refuse(env="dev", platform="unknown") == []


def test_DARVOZA_production_sysid_env_KENGAYTMASI_bilan_ham_ruxsat_royxatiga_TUSHMAYDI(monkeypatch):
    prod = sorted(G.PRODUCTION_SYSTEM_IDENTIFIERS)[0]
    assert prod == "7674898282858840119"
    monkeypatch.setenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, f"{prod},111")
    assert prod not in G.allowed_system_identifiers()
    assert "111" in G.allowed_system_identifiers()
    ident = {**_IDENT, "system_identifier": prod}
    said = " ".join(_refuse(ident=ident, expect_system_identifier=prod, reviewed_identity=ident))
    assert "production taqiq ro'yxatida" in said and "PRODUCTION yo'li" in said
    # Staging kodda ruxsat ro'yxatida (env'siz ham).
    monkeypatch.delenv(G.ALLOWED_SYSTEM_IDENTIFIERS_ENV, raising=False)
    assert G.allowed_system_identifiers() == G.NON_PRODUCTION_SYSTEM_IDENTIFIERS
    assert "7683497876193431618" in G.allowed_system_identifiers()


def test_DARVOZA_muhit_nomlari_YOQ_bolsa_UNKNOWN(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    assert G.environment_names() == ("unknown", "unknown")
    monkeypatch.setenv("APP_ENV", "  Staging ")
    assert G.environment_names()[0] == "staging"


# ══ SHARTNOMA: plan_sha256 / chiqish kodlari ════════════════════════════════

def _fake_report(verdict=C.VERDICT_READY, findings=(), rows=0, structure=None):
    rep = {"schema_version": C.REPORT_SCHEMA_VERSION, "migration_id": MIG,
           "database": {"dialect": "postgresql", "system_identifier": "111",
                        "database": "savdoos", "server_version_num": 180000},
           "structure": structure or {"columns": [{"table": "t", "column": "c", "type": "varchar"}]},
           "values": {"columns": [{"table": "t", "column": "c", "rows": rows}]},
           "findings": list(findings), "verdict": verdict}
    return C.seal(rep)


def test_SHARTNOMA_plan_sha256_SONLARGA_bogliq_EMAS_STRUKTURAGA_bogliq():
    a, b = _fake_report(rows=0), _fake_report(rows=17)
    assert a["plan_sha256"] == b["plan_sha256"], "qator soni rejani o'zgartirdi"
    assert a["report_sha256"] != b["report_sha256"], "hisobot xeshi sonlarni ko'rmadi"
    c = _fake_report(structure={"columns": [{"table": "t", "column": "c", "type": "uuid"}]})
    assert c["plan_sha256"] != a["plan_sha256"], "struktura o'zgarishi rejaga ta'sir qilmadi"
    d = _fake_report(findings=[C.finding(C.SEVERITY_BLOCK, "X", "y")])
    assert d["plan_sha256"] != a["plan_sha256"], "bloker rejaga kirmadi"
    assert C.report_sha256(a) == a["report_sha256"], "muhrlash barqaror emas"


def test_SHARTNOMA_chiqish_kodlari():
    assert C.exit_code_for(_fake_report()) == C.EXIT_OK == 0
    assert C.exit_code_for(_fake_report(verdict=C.VERDICT_ALREADY_APPLIED)) == 0
    assert C.exit_code_for(_fake_report(verdict=C.VERDICT_NOT_APPLICABLE)) == 0
    assert C.exit_code_for(_fake_report(
        findings=[C.finding(C.SEVERITY_REVIEW, "R", "k")])) == C.EXIT_REVIEW == 2
    assert C.exit_code_for(_fake_report(
        findings=[C.finding(C.SEVERITY_INFO, "I", "k")])) == 0
    assert C.exit_code_for(_fake_report(verdict=C.VERDICT_BLOCKED)) == C.EXIT_BLOCK == 3
    assert C.exit_code_for(_fake_report(
        findings=[C.finding(C.SEVERITY_BLOCK, "B", "k"),
                  C.finding(C.SEVERITY_REVIEW, "R", "k")])) == 3
    assert (C.EXIT_OK, C.EXIT_USAGE, C.EXIT_REVIEW, C.EXIT_BLOCK) == (0, 1, 2, 3)


# ══ CLI — SQLITE'DA NOT_APPLICABLE, ARGUMENT SEMANTIKASI ════════════════════

@pytest.fixture
def sqlite_url(tmp_path, monkeypatch):
    db = tmp_path / "yoq.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(db).replace("\\", "/"))
    monkeypatch.setenv("APP_ENV", "test")
    return db


def test_CLI_SQLite_da_HAR_buyruq_NOT_APPLICABLE_va_BAZA_YARATILMAYDI(sqlite_url, capsys):
    rep = str(sqlite_url.parent / "report.json")
    for argv in (["preflight", "--migration", MIG],
                 ["verify", "--migration", MIG],
                 ["apply", "--migration", MIG, "--report", rep, "--commit"],
                 ["revert", "--migration", MIG, "--report", rep, "--rehearse"]):
        assert SM.main(argv) == 0, argv
        out = capsys.readouterr().out
        assert "NOT_APPLICABLE" in out and "sqlite" in out, (argv, out)
    assert not sqlite_url.exists(), "CLI SQLite bazasini YARATDI (yon ta'sir)"
    assert not pathlib.Path(rep).exists(), "hisobot fayli yozildi"


def test_CLI_list_va_json_rejimi(sqlite_url, capsys):
    assert SM.main(["list"]) == 0
    assert MIG in capsys.readouterr().out
    assert SM.main(["list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [m["migration_id"] for m in data["migrations"]] == [MIG]
    assert data["migrations"][0]["targets"] == ["cash_movements.client_uuid",
                                                "qr_payments.sale_id", "qr_payments.client_uuid"]


def test_CLI_argument_xatolari_AYNAN_1_beradi(sqlite_url, capsys):
    rep = str(sqlite_url.parent / "report.json")
    cases = [
        ["apply", "--migration", MIG, "--commit"],                       # --report yo'q
        ["apply", "--migration", "yoq", "--report", rep, "--commit"],    # noma'lum migratsiya
        ["preflight"],                                                   # --migration yo'q
        ["yoq-buyruq"],
        ["apply", "--migration", MIG, "--report", rep],                  # rejim yo'q
        ["apply", "--migration", MIG, "--report", rep, "--rehearse", "--commit"],
        ["apply", "--migration", MIG, "--report", rep, "--commit", "--lock-timeout-ms", "0"],
        ["apply", "--migration", MIG, "--report", rep, "--commit", "--statement-timeout-ms", "-5"],
    ]
    for argv in cases:
        assert SM.main(argv) == C.EXIT_USAGE == 1, argv
        capsys.readouterr()


def test_CLI_DATABASE_URL_YOQ_bolsa_1(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert SM.main(["preflight", "--migration", MIG]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_CLI_buzilgan_hisobot_RAD_etiladi_3(tmp_path, monkeypatch, capsys):
    """Hisobot Postgres bo'lmaganda o'qilmaydi — shuning uchun tekshiruv toza funksiyada."""
    rep = tmp_path / "r.json"
    good = _fake_report()
    rep.write_text(json.dumps(good), encoding="utf-8")
    assert SM._load_reviewed(str(rep), MIG)["plan_sha256"] == good["plan_sha256"]
    bad = dict(good, report_sha256="0" * 64)
    rep.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SM._Blocked):
        SM._load_reviewed(str(rep), MIG)
    tampered = dict(good)
    tampered["verdict"] = C.VERDICT_READY
    tampered["structure"] = {"columns": []}
    tampered["report_sha256"] = C.report_sha256(tampered)
    rep.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(SM._Blocked):          # report_sha256 to'g'ri, plan_sha256 eski
        SM._load_reviewed(str(rep), MIG)
    rep.write_text(json.dumps(dict(good, migration_id="boshqa")), encoding="utf-8")
    with pytest.raises(SM._Blocked):
        SM._load_reviewed(str(rep), MIG)
    rep.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(SystemExit):
        SM._load_reviewed(str(rep), MIG)


# ══ MIGRATSIYA MODULI — SQLITE'DA NO-OP ═════════════════════════════════════

def test_migratsiya_SQLite_da_NOT_APPLICABLE_va_HECH_NARSA_bajarmaydi(tmp_path):
    from sqlalchemy import create_engine
    eng = create_engine("sqlite:///" + str(tmp_path / "x.db").replace("\\", "/"))
    try:
        with eng.connect() as con:
            assert M.is_applicable(con) is False
            rep = M.preflight(con)
            assert rep["verdict"] == C.VERDICT_NOT_APPLICABLE and rep["plan_sha256"]
            assert M.apply(con, reviewed_report=rep)["result"] == C.RESULT_NOT_APPLICABLE
            assert M.revert(con, reviewed_report=rep)["result"] == C.RESULT_NOT_APPLICABLE
            assert M.verify(con)["ok"] is True
    finally:
        eng.dispose()


def test_migratsiya_KANONIK_shakl_SQL_da_BIR_MARTA_tariflanadi():
    """Python nusxasi YO'Q: eski `re.match` satr oxiridagi `\\n` ni QABUL qilardi (PG esa yo'q)."""
    src = pathlib.Path(M.__file__).read_text(encoding="utf-8")
    assert "re.match" not in src and "re.compile" not in src, "Python regex nusxasi paydo bo'ldi"
    assert "octet_length" in src, "36 baytlik uzunlik sharti yo'q"
    for pat in (M._RE_LOWER, M._RE_ANY_CASE):
        assert pat.startswith("^[0123456789abcdef") and pat.endswith("{12}$"), pat
    assert "ABCDEF" in M._RE_ANY_CASE and "ABCDEF" not in M._RE_LOWER
    assert "USING lower(" in src, "qiymat kanonik KICHIK harfga o'tkazilmayapti"
