# -*- coding: utf-8 -*-
"""BOOT QULFLARI — `python -m app.initdb` jonli jadvalni cheksiz kutmasin (SQLite / birlik).

⚠️  NUQSON. Barqaror (hammasi joyida) Postgres boot'i ham har safar ~55 ta
    `CREATE [UNIQUE] INDEX IF NOT EXISTS` (jadvalga SHARE) va bitta
    `ALTER TABLE product_barcodes DROP CONSTRAINT IF EXISTS` (ACCESS EXCLUSIVE)
    yuborardi. PostgreSQL qulfni obyekt BOR-YO'QLIGINI tekshirishdan OLDIN oladi,
    `lock_timeout` esa hech qayerda yo'q edi: `sales` dagi ochiq bitta yozuvchi
    boot'ni cheksiz ushlab, uning ortida yangi sotuvlar navbatga tushardi.

Bu fayl (Postgres'siz) mixlaydi:
  · PGOPTIONS birlashtirish — mavjud opsiyalar saqlanadi, `lock_timeout` takrorlanmaydi,
    `SAVDOOS_BOOT_LOCK_TIMEOUT` ishlaydi, bo'sh/yaroqsiz qiymat -> standart;
  · `__main__` yo'li PGOPTIONS'ni libpq ko'radigan qilib qo'yadi, oddiy import esa TEGMAYDI;
  · `_index`: Postgres'da indeks BOR bo'lsa na DDL, na tranzaksiya; SQLite'da prechek YO'Q;
  · qulf band (55P03) -> cheklangan urinish; MAJBURIY indeks/ustun va `create_all` -> FATAL,
    qolgani -> o'tkaziladi; qulfdan BOSHQA xato qayta urinilmaydi;
  · statik qo'riqchi: har `CREATE INDEX` literali `_index` orqali, `DROP CONSTRAINT IF
    EXISTS` esa katalog prechegi ortida.

Haqiqiy qulf xulqi (PG'ning qulfni nomdan OLDIN olishi, pg_locks) —
`tests/test_boot_locks_pg.py`.
"""
import ast
import contextlib
import os
import pathlib
import re
import subprocess
import sys
import types

import psycopg.errors
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError, ProgrammingError

import app.initdb as I

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _lock_err(sql="CREATE INDEX IF NOT EXISTS ix ON t (a)"):
    """Haqiqiy psycopg `LockNotAvailable` (55P03), SQLAlchemy o'ramida — boot ko'radigan shakl."""
    orig = psycopg.errors.LockNotAvailable("canceling statement due to lock timeout")
    return OperationalError(sql, None, orig)


class _SoxtaCon:
    def __init__(self, eng):
        self.eng = eng

    def execute(self, stmt, params=None):
        self.eng.ddl.append(str(stmt))
        if self.eng.errors:
            raise self.eng.errors.pop(0)


class _SoxtaEngine:
    """Faqat `dialect.name` va `begin()` — yuborilgan HAR bayonot yoziladi."""

    def __init__(self, dialect="postgresql", errors=()):
        self.dialect = types.SimpleNamespace(name=dialect)
        self.ddl, self.errors = [], list(errors)

    @contextlib.contextmanager
    def begin(self):
        yield _SoxtaCon(self)

    def connect(self):
        raise AssertionError("soxta engine: kutilmagan connect()")


@pytest.fixture
def soxta(monkeypatch):
    """Postgres'ga o'xshagan soxta engine; urinishlar orasida uxlamaydi; blokerlar — tayyor matn."""
    def make(dialect="postgresql", errors=(), exists=()):
        eng = _SoxtaEngine(dialect, errors)
        seq = list(exists)
        eng.prechecks = []

        def rel_exists(name):
            eng.prechecks.append(name)
            return seq.pop(0) if seq else False

        def holders(tables):
            return ("lock_timeout=1s; to'sayotgan seanslar: "
                    f"{tables[0] if tables else '?'}: pid=4242 RowExclusiveLock")
        monkeypatch.setattr(I, "engine", eng)
        monkeypatch.setattr(I, "_LOCK_RETRY_SLEEP", 0)
        monkeypatch.setattr(I, "_pg_relation_exists", rel_exists, raising=False)
        monkeypatch.setattr(I, "_lock_holders", holders, raising=False)
        return eng
    return make


# ══ 1. PGOPTIONS — FAQAT BOOT JARAYONI UCHUN ════════════════════════════════

@pytest.mark.parametrize("existing,value,want", [
    (None, None, "-c lock_timeout=2s"),                          # hech narsa yo'q -> standart
    ("", "", "-c lock_timeout=2s"),                              # bo'sh -> standart
    ("   ", "   ", "-c lock_timeout=2s"),                        # faqat probel -> standart
    (None, "750ms", "-c lock_timeout=750ms"),                    # env ustun
    (None, " 5 s ", "-c lock_timeout=5s"),                       # probellar olib tashlanadi
    (None, "abc", "-c lock_timeout=2s"),                         # yaroqsiz -> standart
    (None, "1s -c statement_timeout=1", "-c lock_timeout=2s"),   # opsiya in'eksiyasi YO'Q
    ("-c default_transaction_read_only=on", None,
     "-c default_transaction_read_only=on -c lock_timeout=2s"),  # mavjud SAQLANADI
    ("-c default_transaction_read_only=on", "1s",
     "-c default_transaction_read_only=on -c lock_timeout=1s"),
    ("-c deadlock_timeout=1s", None,
     "-c deadlock_timeout=1s -c lock_timeout=2s"),               # deadlock_timeout boshqa GUC
    # Postgres RAD etadigan qiymat HAR ulanishni FATAL qilardi -> standart.
    (None, "25d", "-c lock_timeout=2s"),                         # > 2147483647 ms
    (None, "597h", "-c lock_timeout=2s"),
    (None, "35792min", "-c lock_timeout=2s"),
    (None, "2147484s", "-c lock_timeout=2s"),
    (None, "3000000000", "-c lock_timeout=2s"),
    (None, "08s", "-c lock_timeout=2s"),                         # bosh nol: strtol sakkizlik
    (None, "010", "-c lock_timeout=2s"),
    # Chegaradagi YAROQLI qiymatlar o'zgarmasdan o'tadi.
    (None, "24d", "-c lock_timeout=24d"),
    (None, "596h", "-c lock_timeout=596h"),
    (None, "2147483647", "-c lock_timeout=2147483647"),
    (None, "0", "-c lock_timeout=0"),                            # operatorning ochiq qarori
])
def test_PGOPTIONS_birlashtirish(existing, value, want):
    assert I._boot_pgoptions(existing, value) == want


@pytest.mark.parametrize("existing", [
    "-c lock_timeout=3000",
    "-clock_timeout=3000",
    "--lock_timeout=3000",
    "--lock-timeout=3000",
    "-c default_transaction_read_only=on -c lock_timeout=0",
    "-c LOCK_TIMEOUT=0",                                         # GUC nomi registrga sezgir emas
    "--Lock-Timeout=3000",
])
def test_PGOPTIONS_da_lock_timeout_BOR_bolsa_TAKRORLANMAYDI_operator_qiymati_USTUN(existing):
    assert I._boot_pgoptions(existing, "9s") == existing


def _run_main_path(tmp_path, env_extra, code):
    db = str(tmp_path / "boot.db").replace("\\", "/")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db}", APP_ENV="test")
    for k in ("PGOPTIONS", "SAVDOOS_BOOT_LOCK_TIMEOUT"):
        env.pop(k, None)
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", code], cwd=SRV, capture_output=True,
                       text=True, env=env, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    return r.stdout


_MAIN_CODE = (
    "import os, runpy" + chr(10) +
    "runpy.run_module('app.initdb', run_name='__main__')" + chr(10) +
    "from psycopg import pq" + chr(10) +
    "d = {x.keyword: x.val for x in pq.Conninfo.get_defaults()}" + chr(10) +
    "print('PGOPTIONS=' + os.environ.get('PGOPTIONS', '<yoq>'))" + chr(10) +
    "print('LIBPQ=' + (d[b'options'] or b'').decode())" + chr(10)
)


def test_MAIN_yoli_lock_timeout_QOSHADI_va_libpq_uni_KORADI(tmp_path):
    """`python -m app.initdb` — mavjud opsiya saqlanadi, libpq birlashgan qiymatni o'qiydi.

    libpq PGOPTIONS'ni ULANISH paytida o'qiydi; bu yerda uning standartlar jadvali
    (`PQconndefaults`) bilan tekshiriladi — ya'ni jarayon ichidagi o'zgarish haqiqatan
    drayverga yetadi (bazasiz)."""
    out = _run_main_path(tmp_path, {"PGOPTIONS": "-c default_transaction_read_only=on"},
                         _MAIN_CODE)
    assert "[OK] Jadvallar yaratildi" in out, out[-1500:]
    want = "-c default_transaction_read_only=on -c lock_timeout=2s"
    assert f"PGOPTIONS={want}" in out, out[-600:]
    assert f"LIBPQ={want}" in out, out[-600:]


def test_MAIN_yoli_SAVDOOS_BOOT_LOCK_TIMEOUT_ni_oladi(tmp_path):
    out = _run_main_path(tmp_path, {"SAVDOOS_BOOT_LOCK_TIMEOUT": "750ms"}, _MAIN_CODE)
    assert "PGOPTIONS=-c lock_timeout=750ms" in out, out[-600:]
    assert "LIBPQ=-c lock_timeout=750ms" in out, out[-600:]


def test_ODDIY_import_PGOPTIONS_ga_TEGMAYDI_uvicorn_va_testlar_tashqarida(tmp_path):
    """Salbiy nazorat: faqat `__main__` yo'li. Ilova (uvicorn) va jarayon ichidagi
    `initdb.main()` (conftest) sessiyasiga boot chegarasi o'tmasligi kerak."""
    code = ("import os, app.initdb, app.main" + chr(10) +
            "print('PGOPTIONS=' + os.environ.get('PGOPTIONS', '<yoq>'))" + chr(10))
    assert "PGOPTIONS=<yoq>" in _run_main_path(tmp_path, {}, code)


# ══ 2. `_index` — QULFSIZ PRECHEK ═══════════════════════════════════════════

def test_POSTGRES_da_indeks_BOR_bolsa_DDL_ham_tranzaksiya_ham_YOQ(soxta):
    eng = soxta(exists=[True])
    I._index("CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)", "ix_sales_shift")
    assert eng.ddl == [], f"indeks BOR, lekin DDL yuborildi (jadvalga SHARE qulf): {eng.ddl}"
    assert eng.prechecks == ["ix_sales_shift"]


def test_POSTGRES_da_indeks_YOQ_bolsa_DDL_bir_marta(soxta):
    """Musbat nazorat: prechek hamma narsani «bor» deb yutib yubormaydi."""
    eng = soxta(exists=[False])
    I._index("CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)", "ix_sales_shift")
    assert eng.ddl == ["CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)"]


def test_SQLITE_da_PRECHEK_YOQ_CREATE_bajariladi(tmp_path, monkeypatch):
    """Salbiy nazorat: SQLite xulqi O'ZGARMAGAN — haqiqiy SQLite, `to_regclass` so'ralmaydi."""
    eng = create_engine("sqlite:///" + str(tmp_path / "ix.db").replace("\\", "/"))
    with eng.begin() as con:
        con.execute(text("CREATE TABLE t (a INTEGER)"))
    seen = []
    event.listen(eng, "before_cursor_execute", lambda *a: seen.append(a[2]))
    monkeypatch.setattr(I, "engine", eng)
    monkeypatch.setattr(I, "_pg_relation_exists",
                        lambda n: pytest.fail("SQLite'da prechek chaqirildi"), raising=False)
    try:
        for _ in range(2):          # ikkinchisi — IF NOT EXISTS no-op, xato yo'q
            I._index("CREATE INDEX IF NOT EXISTS ix_t_a ON t (a)", "ix_t_a")
        with eng.connect() as con:
            names = [r[0] for r in con.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'index'"))]
    finally:
        eng.dispose()
    assert "ix_t_a" in names
    assert sum("CREATE INDEX IF NOT EXISTS ix_t_a" in q for q in seen) == 2, seen
    assert not any("to_regclass" in q for q in seen), seen


# ══ 3. QULF BAND — CHEKLANGAN URINISH va TASNIF ═════════════════════════════

def test_ixtiyoriy_indeks_QULF_BAND_cheklangan_urinish_keyin_OTKAZILADI(soxta, capsys):
    eng = soxta(errors=[_lock_err()] * 20)
    I._index("CREATE INDEX IF NOT EXISTS ix_sales_shift ON sales (shift_id)", "ix_sales_shift")
    out = capsys.readouterr().out
    assert len(eng.ddl) == 5, f"qulf band: {len(eng.ddl)} urinish (5 kutilgan): {eng.ddl}"
    assert I._DDL_LOCK_ATTEMPTS == 5
    assert len(eng.prechecks) == 5, "prechek har urinishda qayta so'ralmadi"
    assert "ix_sales_shift: qulf band — 4/5" in out, out
    assert "5/5" not in out, "oxirgi urinishdan keyin ham kutildi"
    assert "[migrate] ix_sales_shift — o'tkazib yuborildi" in out and "lock timeout" in out, out
    assert "[FATAL]" not in out


def test_MAJBURIY_indeks_QULF_BAND_FATAL_blokerlar_bilan(soxta, capsys):
    eng = soxta(errors=[_lock_err()] * 20)
    with pytest.raises(OperationalError):
        I._index("CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_counter "
                 "ON doc_counters (company_id, kind)", "ux_doc_counter")
    out = capsys.readouterr().out
    assert len(eng.ddl) == 5, eng.ddl
    fatal = [ln for ln in out.splitlines() if ln.startswith("[FATAL]")]
    assert len(fatal) == 1, out
    for part in ("MAJBURIY indeks yaratilmadi: ux_doc_counter", "doc_counters qulfi 5 urinishda",
                 "lock_timeout=1s", "pid=4242 RowExclusiveLock", "lock timeout"):
        assert part in fatal[0], fatal[0]


def test_qulf_kutilganda_INDEKS_PAYDO_bolsa_DDL_TAKRORLANMAYDI(soxta, capsys):
    """Boshqa instansiya qurib bo'ldi: 2-urinishning prechegi «bor» -> FATAL ham, DDL ham yo'q."""
    eng = soxta(errors=[_lock_err()], exists=[False, True])
    I._index("CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_counter "
             "ON doc_counters (company_id, kind)", "ux_doc_counter")
    assert len(eng.ddl) == 1 and eng.prechecks == ["ux_doc_counter"] * 2, (eng.ddl, eng.prechecks)
    assert "[FATAL]" not in capsys.readouterr().out


def test_qulfdan_BOSHQA_xato_QAYTA_URINILMAYDI_MAJBURIY_FATAL_avvalgidek(soxta, capsys):
    """Salbiy nazorat: faqat 55P03 qayta urinadi. `test_hardening` 1-qatlami xulqi saqlanadi."""
    eng = soxta(errors=[RuntimeError("SINOV: DDL yiqildi")])
    with pytest.raises(RuntimeError):
        I._index("CREATE UNIQUE INDEX IF NOT EXISTS ux_import_jobs_snapshot ON import_jobs "
                 "(company_id, source, snapshot_id)", "ux_import_jobs_snapshot")
    out = capsys.readouterr().out
    assert len(eng.ddl) == 1, eng.ddl
    assert "[FATAL] MAJBURIY indeks yaratilmadi: ux_import_jobs_snapshot — SINOV: DDL yiqildi" \
        in out, out
    assert "qulf band" not in out


class _SoxtaInsp:
    def __init__(self, table, missing):
        self.table = table
        self.cols = [{"name": c} for t, c, _ in I._ADDED_COLUMNS if t == table and c != missing]

    def get_table_names(self):
        return [self.table]

    def get_columns(self, table):
        return self.cols


@pytest.mark.parametrize("col,required", [("till_id", False), ("cost_basis", True)])
def test_ustun_QULF_BAND_cheklangan_urinish_MAJBURIY_FATAL_qolgani_OTKAZILADI(
        soxta, monkeypatch, capsys, col, required):
    from app.core import required_schema as rs
    assert (("sales", col) in rs.REQUIRED_COLUMNS) is required, "sinov farazi eskirgan"
    eng = soxta(errors=[_lock_err()] * 20)
    monkeypatch.setattr(I, "inspect", lambda bind: _SoxtaInsp("sales", col))
    if required:
        with pytest.raises(OperationalError):
            I._ensure_columns()
    else:
        I._ensure_columns()
    out = capsys.readouterr().out
    sqltype = {"till_id": "UUID", "cost_basis": "VARCHAR"}[col]
    assert eng.ddl == [f"ALTER TABLE sales ADD COLUMN {col} {sqltype}"] * 5, eng.ddl
    assert f"sales.{col}: qulf band — 4/5" in out, out
    if required:
        fatal = [ln for ln in out.splitlines() if ln.startswith("[FATAL]")]
        assert len(fatal) == 1, out
        for part in (f"MAJBURIY ustun qo'shilmadi: sales.{col}", "sales qulfi 5 urinishda",
                     "lock_timeout=1s", "pid=4242"):
            assert part in fatal[0], fatal[0]
    else:
        assert f"[migrate] sales.{col} — o'tkazib yuborildi" in out and "[FATAL]" not in out, out


_CREATE_RIRA = ("CREATE TABLE return_item_resolution_allocations (id UUID NOT NULL, "
                "FOREIGN KEY(company_id) REFERENCES companies (id), "
                "FOREIGN KEY(return_id) REFERENCES returns (id))")


def _main_faqat_create_all(monkeypatch, soxta, create_all):
    """`main()` ni HAQIQIY tartibda yurgizadi, lekin `create_all` dan keyingi qadamlar no-op."""
    soxta()
    tree = ast.parse(pathlib.Path(I.__file__).read_text(encoding="utf-8"))
    body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    steps = {c.func.id for c in ast.walk(body) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Name) and c.func.id.startswith("_")
             and c.func.id != "_create_all"}
    assert len(steps) >= 15, steps
    for name in steps:
        monkeypatch.setattr(I, name, lambda *a, **k: None)
    monkeypatch.setattr(I, "Base", types.SimpleNamespace(
        metadata=types.SimpleNamespace(create_all=create_all)))


def test_create_all_QULF_BAND_cheklangan_urinish_keyin_FATAL(soxta, monkeypatch, capsys):
    calls = []

    def create_all(bind):
        calls.append(bind)
        raise _lock_err(_CREATE_RIRA)
    _main_faqat_create_all(monkeypatch, soxta, create_all)
    with pytest.raises(OperationalError):
        I.main()
    out = capsys.readouterr().out
    assert len(calls) == 5, f"create_all {len(calls)} marta chaqirildi"
    fatal = [ln for ln in out.splitlines() if ln.startswith("[FATAL]")]
    assert len(fatal) == 1, out
    for part in ("yangi jadval yaratilmadi (create_all): return_item_resolution_allocations",
                 "companies, returns qulfi 5 urinishda", "pid=4242"):
        assert part in fatal[0], fatal[0]
    assert "[OK]" not in out


def test_create_all_qulf_BOSHLIQ_ikkinchi_urinishda_OTADI(soxta, monkeypatch, capsys):
    calls = []

    def create_all(bind):
        calls.append(bind)
        if len(calls) == 1:
            raise _lock_err(_CREATE_RIRA)
    _main_faqat_create_all(monkeypatch, soxta, create_all)
    I.main()
    out = capsys.readouterr().out
    assert len(calls) == 2 and "[OK] Jadvallar yaratildi" in out and "[FATAL]" not in out, out


def test_create_all_qulfdan_BOSHQA_xato_bir_marta_va_avvalgidek_yuqoriga(
        soxta, monkeypatch, capsys):
    """Salbiy nazorat: huquq xatosi qayta urinilmaydi va qulf FATAL satri chiqmaydi."""
    calls = []

    def create_all(bind):
        calls.append(bind)
        raise ProgrammingError(_CREATE_RIRA, None, psycopg.errors.InsufficientPrivilege(
            "permission denied for schema public"))
    _main_faqat_create_all(monkeypatch, soxta, create_all)
    with pytest.raises(ProgrammingError):
        I.main()
    assert len(calls) == 1
    assert "[FATAL] yangi jadval" not in capsys.readouterr().out


# ══ 4. STATIK QO'RIQCHI — yangi kod eski yo'lga qaytmasin ═══════════════════

_CREATE_INDEX = re.compile(r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE)
_DROP_CONSTRAINT = re.compile(r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+\"?(\w+)", re.IGNORECASE)
_CIC_HELPER = "_ensure_sale_items_sale_id_index"
#  Tenancy qulfli yo'li: faqat QULFSIZ `_precheck_states` LEGACY topganda chaqiriladi
#  (`tests/cash/test_tenancy_scoping.py` AA/JJ mixlaydi).
_TENANCY_LOCKED = "_migrate_one"


def _literals(tree):
    """(literal, uning ota-zanjiri) — docstring/yolg'iz satr ifodalari tashlanadi."""
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and not isinstance(parents.get(node), ast.Expr):
            chain, cur = [], node
            while cur in parents:
                cur = parents[cur]
                chain.append(cur)
            yield node, chain


def _is_index_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_index")


def _via_index(lit, chain):
    cur = lit
    for par in chain:
        if _is_index_call(par) and any(a is cur for a in par.args):
            return True
        if isinstance(par, ast.For) and par.iter is cur:
            targets = {n.id for n in ast.walk(par.target) if isinstance(n, ast.Name)}
            return any(_is_index_call(c) and c.args and isinstance(c.args[0], ast.Name)
                       and c.args[0].id in targets
                       for stmt in par.body for c in ast.walk(stmt))
        if isinstance(par, (ast.FunctionDef, ast.Module)):
            return False
        cur = par
    return False


def _func(chain):
    return next((p for p in chain if isinstance(p, ast.FunctionDef)), None)


def _boot_lock_violations(src: str) -> tuple[list[str], int, int]:
    """(buzilishlar, CREATE INDEX literallari soni, tekshirilgan DROP CONSTRAINT soni)."""
    tree = ast.parse(src)
    bad, n_ix, n_drop = [], 0, 0
    lits = list(_literals(tree))
    for lit, chain in lits:
        fn = _func(chain)
        fname = fn.name if fn else "<modul>"
        if "CONCURRENTLY" in lit.value.upper() and fname != _CIC_HELPER:
            bad.append(f"{lit.lineno}: CONCURRENTLY `{_CIC_HELPER}` dan tashqarida")
        if _CREATE_INDEX.match(lit.value):
            n_ix += 1
            if fname == _CIC_HELPER and "CONCURRENTLY" in lit.value.upper():
                continue
            if not _via_index(lit, chain):
                bad.append(f"{lit.lineno}: `_index` dan o'tmagan indeks DDL: {lit.value[:60]!r}")
        m = _DROP_CONSTRAINT.search(lit.value)
        if m and fname != _TENANCY_LOCKED:
            n_drop += 1
            #  Ma'lumotga bog'liq `if` (dialekt tekshiruvi EMAS) + undan oldin pg_constraint so'rovi.
            guarded = fn is not None and any(
                isinstance(p, ast.If) and "dialect" not in ast.unparse(p.test)
                for p in chain[:chain.index(fn)])
            probe = fn is not None and any(
                "pg_constraint" in o.value and m.group(1) in o.value and o.lineno < lit.lineno
                for o, och in lits if _func(och) is fn)
            if not (guarded and probe):
                bad.append(f"{lit.lineno}: `DROP CONSTRAINT IF EXISTS {m.group(1)}` katalog "
                           "prechegi (pg_constraint + if) ortida EMAS — ACCESS EXCLUSIVE har boot")
    return bad, n_ix, n_drop


def test_QORIQCHI_har_CREATE_INDEX_index_orqali_DROP_CONSTRAINT_prechek_ortida():
    src = pathlib.Path(I.__file__).read_text(encoding="utf-8")
    bad, n_ix, n_drop = _boot_lock_violations(src)
    assert not bad, "boot har safar jonli jadvalga qulf so'raydi:\n  " + "\n  ".join(bad)
    # Bo'sh ro'yxat «o'tdi» degani bo'lmasin: qo'riqchi haqiqatan literallarni ko'rdi.
    assert n_ix >= 45, f"CREATE INDEX literallari juda kam topildi ({n_ix}) — tahlil buzilgan"
    assert n_drop >= 1, "product_barcodes DROP CONSTRAINT topilmadi — tahlil buzilgan"


def test_QORIQCHI_salbiy_nazorat_ESKI_naqshni_USHLAYDI():
    """Qo'riqchining o'zi yolg'on yashil bo'lmasin: eski naqsh AYNAN ushlanadi."""
    eski = (
        "def _ensure_indexes():\n"
        "    try:\n"
        "        with engine.begin() as con:\n"
        "            con.execute(text(\"CREATE UNIQUE INDEX IF NOT EXISTS ux_a ON a (x)\"))\n"
        "    except Exception as e:\n"
        "        print(e)\n"
        "    for name, ddl in [(\"ix_b\", \"CREATE INDEX IF NOT EXISTS ix_b ON b (y)\")]:\n"
        "        with engine.begin() as con:\n"
        "            con.execute(text(ddl))\n"
        "def _migrate_barcodes_per_company():\n"
        "    if engine.dialect.name == \"postgresql\":\n"
        "        with engine.begin() as con:\n"
        "            con.execute(text(\"ALTER TABLE product_barcodes DROP CONSTRAINT IF EXISTS "
        "product_barcodes_barcode_key\"))\n"
    )
    bad, n_ix, n_drop = _boot_lock_violations(eski)
    assert n_ix == 2 and n_drop == 1, (n_ix, n_drop)
    assert len(bad) == 3, bad
    yangi = eski.replace(
        "            con.execute(text(\"CREATE UNIQUE INDEX IF NOT EXISTS ux_a ON a (x)\"))\n",
        "            _index(\"CREATE UNIQUE INDEX IF NOT EXISTS ux_a ON a (x)\", \"ux_a\")\n").replace(
        "            con.execute(text(ddl))\n", "            _index(ddl, name)\n")
    assert len(_boot_lock_violations(yangi)[0]) == 1, "musbat nazorat: faqat DROP qolishi kerak"
