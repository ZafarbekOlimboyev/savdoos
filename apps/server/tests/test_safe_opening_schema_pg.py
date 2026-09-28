# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ochilishi: SXEMA va TAYYORLIK (haqiqiy PostgreSQL, haqiqiy boot).

Shartnoma: `docs/PURCHASE_SETTLEMENT_PHASE1.md` §2 (jadval), §5 (additiv migratsiya
va tayyorlik). Testlar T-18 va T-19.

⚠️  NEGA ADDITIV QADAM KERAK. `deploy_cash_schema` HAMMASI-YOKI-HECH NARSA: `cash`
    sxemasi mavjud bo'lsa `'exists'` qaytaradi va DDL faylini BUTUNLAY o'tkazib
    yuboradi. Ya'ni mavjud (production-like) baza `cash_ddl_v1.sql` ga qo'shilgan
    yangi obyektni HECH QACHON olmasdi. Shu bois Phase 1 obyektlari `cash_ddl_v1.sql`
    ga TEGMASDAN, alohida idempotent boot qadamida tug'iladi — va fresh baza ham
    AYNI qadamdan oladi (ikki manba bo'lsa ular ajralib ketardi).

⚠️  `CREATE TABLE IF NOT EXISTS` O'ZI ISBOT EMAS: nomi to'g'ri, shakli noto'g'ri
    jadval uni JIM o'tkazib yuboradi. Shu bois tayyorlik ustun/CHECK/FK/indeks/
    triggerni ANIQ tekshiradi (T-19).
"""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.test_check_defs_pg import SRV, _initdb, pg_target  # noqa: F401

TBL = "cash_account_openings"

# §2 — ustun shartnomasi: (tip, nullable)
_COLS = {
    "id": ("uuid", False),
    "tenant_id": ("uuid", False),
    "cash_account_id": ("uuid", False),
    "account_type": ("USER-DEFINED", False),      # cash.cash_account_type
    "kind": ("text", False),
    "counted_amount": ("numeric", False),
    "currency": ("character", False),
    "counted_at": ("timestamp with time zone", False),
    "attested_by": ("uuid", False),
    "attestation_ref": ("text", False),
    "ledger_entry_id": ("uuid", True),            # KNOWN_ZERO uchun NULL
    "created_at": ("timestamp with time zone", False),
}

# §2 — CHECK shartnomasi (MATN emas, MA'NO bo'yicha solishtiriladi)
_CHECKS = {
    "ck_cao_kind": "kind IN ('KNOWN_ZERO','COUNTED')",
    "ck_cao_amount_nonneg": "counted_amount >= 0",
    "ck_cao_kind_amount": "(kind = 'COUNTED') = (counted_amount > 0)",
    "ck_cao_kind_ledger": "(kind = 'COUNTED') = (ledger_entry_id IS NOT NULL)",
    "ck_cao_ref_nb": "attestation_ref <> ''",
    "ck_cao_type_safe": "account_type = 'SAFE'::cash.cash_account_type",
}

_FKS = {"cao_acct_type_fk", "cao_acct_cur_fk", "cao_entry_fk"}
_UNIQUES = {"cao_uq_account": ("tenant_id", "cash_account_id"),
            "cao_uq_tenant_id": ("tenant_id", "id")}
_TRIGGERS = {"trg_cao_immutable": "fn_block_mutation",
             "trg_cao_no_truncate": "fn_block_truncate"}


# ── yordamchilar ────────────────────────────────────────────────────────────
def _eng(url):
    return create_engine(url, future=True)


def _boot_raw(url):
    """Boot YIQILISHI/DAVOM ETISHI kutilgan holat uchun — `CompletedProcess`."""
    return subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                          text=True, timeout=900,
                          env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))


def _enum_labels(eng, typ="cash_source_type"):
    with eng.connect() as con:
        return {r[0] for r in con.execute(text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = 'cash' AND t.typname = :t"), {"t": typ})}


def _cols(eng):
    with eng.connect() as con:
        return {r[0]: (r[1], r[2] == "YES") for r in con.execute(text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'cash' AND table_name = :t"), {"t": TBL})}


def _checks(eng):
    with eng.connect() as con:
        return {r[0]: r[1] for r in con.execute(text(
            "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'cash' AND t.relname = :t AND c.contype = 'c'"), {"t": TBL})}


def _cons(eng, contype):
    with eng.connect() as con:
        return {r[0]: r[1] for r in con.execute(text(
            "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'cash' AND t.relname = :t AND c.contype = :k"),
            {"t": TBL, "k": contype})}


def _indexes(eng):
    with eng.connect() as con:
        return {r[0]: (bool(r[1]), bool(r[2]), r[3], r[4]) for r in con.execute(text(
            "SELECT c.relname, i.indisunique, i.indpred IS NULL, pg_get_indexdef(i.indexrelid), c.oid "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_class t ON t.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cash' AND t.relname = :t"), {"t": TBL})}


def _triggers(eng):
    with eng.connect() as con:
        return {r[0]: r[1] for r in con.execute(text(
            "SELECT tg.tgname, p.proname FROM pg_trigger tg "
            "JOIN pg_class t ON t.oid = tg.tgrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_proc p ON p.oid = tg.tgfoid "
            "WHERE n.nspname = 'cash' AND t.relname = :t AND NOT tg.tgisinternal"), {"t": TBL})}


def _tbl_oid(eng):
    with eng.connect() as con:
        r = con.execute(text("SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                             "WHERE n.nspname = 'cash' AND c.relname = :t"), {"t": TBL}).first()
    return r[0] if r else None


def _assert_shape(eng):
    """§2 ning TO'LIQ shakli — har bir tekshiruv alohida sabab bilan."""
    from app.core import check_canon as cc

    assert "ACCOUNT_OPENING" in _enum_labels(eng), "cash_source_type da ACCOUNT_OPENING YO'Q"

    cols = _cols(eng)
    assert cols, f"cash.{TBL} jadvali YO'Q"
    for name, (typ, nullable) in _COLS.items():
        assert name in cols, f"ustun YO'Q: {name}"
        got_t, got_n = cols[name]
        assert got_t == typ, (name, got_t, typ)
        assert got_n == nullable, (name, "nullable", got_n, nullable)
    assert set(cols) == set(_COLS), ("kutilmagan ustun(lar)", set(cols) ^ set(_COLS))

    txt_cols = tuple(n for n, (t, _) in _COLS.items() if t in ("text", "character"))
    got_ck = _checks(eng)
    for name, src in _CHECKS.items():
        assert name in got_ck, f"CHECK YO'Q: {name}"
        defn = got_ck[name]
        body = defn[defn.index("(") + 1:defn.rindex(")")]
        assert cc.same_check(src, body, text_columns=txt_cols), (name, body, src)

    got_fk = _cons(eng, "f")
    assert _FKS <= set(got_fk), ("FK YO'Q", _FKS - set(got_fk))
    # SEYF-only kompozit FK aynan `cash_accounts (tenant_id, id, type)` ga borishi SHART
    assert "cash_accounts(tenant_id, id, type)" in got_fk["cao_acct_type_fk"].replace(" ", "").replace(
        "cash_accounts(tenant_id,id,type)", "cash_accounts(tenant_id, id, type)") or \
        "tenant_id, id, \"type\"" in got_fk["cao_acct_type_fk"] or \
        "(tenant_id, id, type)" in got_fk["cao_acct_type_fk"], got_fk["cao_acct_type_fk"]

    got_u = _cons(eng, "u")
    for name, cols_ in _UNIQUES.items():
        assert name in got_u, f"UNIQUE YO'Q: {name}"
        for c in cols_:
            assert c in got_u[name], (name, got_u[name])

    idx = _indexes(eng)
    assert "cao_uq_entry" in idx, "cao_uq_entry qisman indeksi YO'Q"
    uniq, whole, ddef, _oid = idx["cao_uq_entry"]
    assert uniq, "cao_uq_entry NOYOB EMAS"
    assert not whole, "cao_uq_entry QISMAN bo'lishi kerak (WHERE ledger_entry_id IS NOT NULL)"
    assert "ledger_entry_id IS NOT NULL" in ddef, ddef

    got_tg = _triggers(eng)
    for _n, _fn in _TRIGGERS.items():
        assert _n in got_tg, f"trigger YO'Q: {_n}"
        assert got_tg[_n] == _fn, (_n, got_tg[_n], _fn)


# ═══ T-18a) FRESH PostgreSQL ════════════════════════════════════════════════
def test_18a_fresh_pg_phase1_obyektlari(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        _assert_shape(eng)
        from app.services.cash import schema_readiness as sr
        assert sr.opening_schema_problems(eng) == []
    finally:
        eng.dispose()


# ═══ T-18b) MAVJUD (production-like) PG — additiv qadam qo'shadi ════════════
def test_18b_mavjud_cash_sxemasiga_qoshiladi(pg_target):
    """`deploy_cash_schema` 'exists' qaytarganda ham Phase 1 obyektlari kelishi SHART."""
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        # Phase 1 dan OLDINGI holatni qayta tiklaymiz (cash sxemasi QOLADI)
        with eng.begin() as con:
            con.exec_driver_sql(f"DROP TABLE IF EXISTS cash.{TBL} CASCADE")
        assert _cols(eng) == {}, "tozalanmadi"
        from app.db.cash.deploy import cash_schema_exists, deploy_cash_schema
        assert cash_schema_exists(eng) is True
        assert deploy_cash_schema(eng) == "exists"      # ⚠️ eski yo'l HECH NARSA qilmaydi
        r = _boot_raw(pg_target)
        assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        _assert_shape(eng)                               # additiv qadam TIKLADI
    finally:
        eng.dispose()


# ═══ T-18c) IKKINCHI BOOT — no-op (qayta yaratish YO'Q) ════════════════════
def test_18c_ikkinchi_boot_no_op(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        oid1 = _tbl_oid(eng)
        labels1 = _enum_labels(eng)
        idx1 = {k: v[3] for k, v in _indexes(eng).items()}
        r = _boot_raw(pg_target)
        assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        assert _tbl_oid(eng) == oid1, "jadval QAYTA YARATILDI (DROP/CREATE)"
        assert _enum_labels(eng) == labels1, "enum o'zgardi"
        assert {k: v[3] for k, v in _indexes(eng).items()} == idx1, "indeks qayta qurildi"
        _assert_shape(eng)
    finally:
        eng.dispose()


# ═══ T-19a) BUZUQ/QISMAN obyekt → tayyorlik QIZIL, JIM ALMASHTIRISH YO'Q ═══
# ⚠️  Buzish qadamlari RO'YXAT: SQL ni "; " bo'yicha BO'LISH mumkin emas — dollar-quoted
#     ($x$ … $x$) funksiya tanasi ichida ham nuqtali vergul bor.
@pytest.mark.parametrize("nom,buzish,kutilgan", [
    ("ustun_yoq", [f"ALTER TABLE cash.{TBL} DROP COLUMN attestation_ref CASCADE"],
     "attestation_ref"),
    ("check_boshqa", [f"ALTER TABLE cash.{TBL} DROP CONSTRAINT ck_cao_amount_nonneg",
                      f"ALTER TABLE cash.{TBL} ADD CONSTRAINT ck_cao_amount_nonneg "
                      f"CHECK (counted_amount >= -1)"], "ck_cao_amount_nonneg"),
    ("indeks_qisman_emas", ["DROP INDEX cash.cao_uq_entry",
                            f"CREATE UNIQUE INDEX cao_uq_entry ON cash.{TBL} (ledger_entry_id)"],
     "cao_uq_entry"),
    # ⚠️  NOM YETMAYDI: to'g'ri nomli, lekin BOSHQA (bo'sh) funksiyani chaqiradigan trigger
    #     jadvalni himoya QILMAYDI. Boot uni ALMASHTIRMASLIGI kerak (audit qilingan tuzatish
    #     protsedurasi shunday triggerni VAQTINCHA qo'yishi mumkin — `cash_ddl_v1.sql` CF-D6).
    ("trigger_boshqa_funksiya",
     [f"DROP TRIGGER trg_cao_immutable ON cash.{TBL}",
      "CREATE OR REPLACE FUNCTION cash.fn_cao_test_noop() RETURNS trigger LANGUAGE plpgsql "
      "AS $x$ BEGIN RETURN NEW; END $x$",
      f"CREATE TRIGGER trg_cao_immutable BEFORE UPDATE OR DELETE ON cash.{TBL} "
      "FOR EACH ROW EXECUTE FUNCTION cash.fn_cao_test_noop()"],
     "trg_cao_immutable"),
])
def test_19a_buzuq_obyekt_tayyorlik_qizil(pg_target, nom, buzish, kutilgan):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        from app.services.cash import schema_readiness as sr
        assert sr.opening_schema_problems(eng) == []
        with eng.begin() as con:
            for stmt in buzish:
                con.exec_driver_sql(stmt)
        probs = sr.opening_schema_problems(eng)
        assert any(kutilgan in p for p in probs), (nom, probs)
        # boot TO'XTAMAYDI va obyektni JIMGINA almashtirmaydi
        r = _boot_raw(pg_target)
        assert r.returncode == 0, f"{nom}: boot to'xtadi\n" + (r.stdout + r.stderr)[-1500:]
        assert any(kutilgan in p for p in sr.opening_schema_problems(eng)), \
            f"{nom}: boot obyektni JIMGINA almashtirdi"
    finally:
        eng.dispose()


# ═══ T-19b) /health/ready — yangi kalit va 503 ══════════════════════════════
def test_19b_health_ready_cash_opening_schema(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        from app.services.cash import schema_readiness as sr
        assert sr.opening_schema_ok(eng) is True
        with eng.begin() as con:
            con.exec_driver_sql(f"DROP TABLE cash.{TBL} CASCADE")
        assert sr.opening_schema_ok(eng) is False
        probs = sr.opening_schema_problems(eng)
        assert any(TBL in p for p in probs), probs
    finally:
        eng.dispose()
    # kalit `/health/ready` javobida BOR (checks lug'ati)
    import inspect

    from app.api.v1 import health as H
    assert "cash_opening_schema" in inspect.getsource(H), "/health/ready da kalit YO'Q"


# ═══ T-19c) cash sxemasi YO'Q → Phase 1 kutilmaydi (yolg'on qizil emas) ════
def test_19c_cash_sxemasisiz_muammo_yoq(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        from app.services.cash import schema_readiness as sr
        with eng.begin() as con:
            con.exec_driver_sql("DROP SCHEMA cash CASCADE")
        assert sr.opening_schema_problems(eng) == [], "cash yo'q bo'lsa Phase 1 KUTILMAYDI"
    finally:
        eng.dispose()


# ═══ T-18d) enum labeli MODEL bilan izchil ═════════════════════════════════
def test_18d_model_enum_izchil(pg_target):
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        from app.models.cash import CashSourceType
        assert CashSourceType.ACCOUNT_OPENING.value == "ACCOUNT_OPENING"
        assert {e.value for e in CashSourceType} <= _enum_labels(eng), \
            "model enumida bazada YO'Q label bor"
    finally:
        eng.dispose()


# ═══ T-18e) DDL fayli TEGILMAGAN (versiyalangan, qayta qo'llanmaydi) ═══════
def test_18e_cash_ddl_v1_tegilmagan():
    ddl = open(os.path.join(SRV, "app", "db", "cash", "cash_ddl_v1.sql"),
               encoding="utf-8").read()
    assert TBL not in ddl, "Phase 1 obyekti cash_ddl_v1.sql ga qo'shilgan — u VERSIYALANGAN"
    assert "ACCOUNT_OPENING" not in ddl, "enum labeli cash_ddl_v1.sql ga qo'shilgan"


# ═══ T-19d) YO'Q trigger — tayyorlik QIZIL, boot esa TIKLAYDI ══════════════
def test_19d_yoq_trigger_tiklanadi(pg_target):
    """⚠️  BU «jimgina almashtirish» EMAS, HIMOYANI QAYTA O'RNATISH.

    R-DDL dagi ayni naqsh: YO'Q obyekt yaratiladi, BOR-u NOTO'G'RI obyekt esa
    TEGILMAYDI (yuqoridagi `trigger_boshqa_funksiya` holati). O'zgarmaslik triggeri
    yo'qolsa append-only kafolati yo'qoladi — uni tiklash hech narsa yo'qotmaydi."""
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        from app.services.cash import schema_readiness as sr
        with eng.begin() as con:
            con.exec_driver_sql(f"DROP TRIGGER trg_cao_immutable ON cash.{TBL}")
        assert any("trg_cao_immutable" in p for p in sr.opening_schema_problems(eng))
        r = _boot_raw(pg_target)
        assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
        assert sr.opening_schema_problems(eng) == [], "boot himoyani TIKLAMADI"
        assert _triggers(eng)["trg_cao_immutable"] == "fn_block_mutation"
    finally:
        eng.dispose()


# ═══ C) BARQAROR BOOT — probe NOL o'zgarish deydi, qadam NOL DDL yuboradi ══
def test_C_barqaror_bootda_nol_ddl(pg_target):
    """⚠️  `CREATE … IF NOT EXISTS` bu tekshiruvning O'RNINI BOSMAYDI: `ddl_command_start`
        jadval qulfidan OLDIN ishlaydi, ya'ni u ham DDL bo'lib jonli jadvalga ShareLock
        so'raydi. Shu bois qadam AVVAL katalogni FAQAT O'QIB, hech narsa yetishmasa
        BIRORTA bayonot yubormasligi kerak (`tests/test_boot_locks_pg.py` bilan bir xil
        shartnoma, lekin bu yerda Phase 1 qadami TO'G'RIDAN-TO'G'RI sinaladi)."""
    from app.db.cash.deploy import ensure_phase1_objects, phase1_missing
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        with eng.connect() as con:
            miss = phase1_missing(con)
        assert miss == {"enum": False, "table": False, "index": False,
                        "triggers": False, "grants": False}, miss
        assert ensure_phase1_objects(eng) == "noop", "barqaror bootda DDL yuborildi"
        # ikkinchi chaqiruv ham no-op (idempotent)
        assert ensure_phase1_objects(eng) == "noop"
    finally:
        eng.dispose()


# ═══ C2) YETISHMAGAN obyekt -> FAQAT O'SHA bo'lim qo'llanadi ══════════════
@pytest.mark.parametrize("yoqot,kutilgan", [
    ("index", "index"),
    ("triggers", "triggers"),
])
def test_C2_faqat_yetishmagan_bolim_qollanadi(pg_target, yoqot, kutilgan):
    from app.db.cash.deploy import ensure_phase1_objects, phase1_missing
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        with eng.begin() as con:
            if yoqot == "index":
                con.exec_driver_sql("DROP INDEX cash.cao_uq_entry")
            else:
                con.exec_driver_sql(f"DROP TRIGGER trg_cao_immutable ON cash.{TBL}")
        with eng.connect() as con:
            assert phase1_missing(con)[kutilgan] is True
        res = ensure_phase1_objects(eng)
        assert res.startswith("applied:") and kutilgan in res, res
        # jadval QAYTA YARATILMAGAN (bo'lim tanlab qo'llandi)
        assert "table" not in res, res
        with eng.connect() as con:
            assert phase1_missing(con)[kutilgan] is False
        assert ensure_phase1_objects(eng) == "noop"       # tiklangach yana no-op
    finally:
        eng.dispose()


# ═══ G) PARALLEL BOOT — dublikat/buzuq DDL YO'Q ═══════════════════════════
def test_G_parallel_boot_dublikat_bermaydi(pg_target):
    """Ikki jarayon bir vaqtda ko'tarilsa: xato yo'q, obyektlar BITTA nusxada."""
    import threading

    from app.db.cash.deploy import ensure_phase1_objects
    _initdb(pg_target)
    eng = _eng(pg_target)
    try:
        with eng.begin() as con:            # Phase 1 obyektlarini olib tashlaymiz
            con.exec_driver_sql(f"DROP TABLE cash.{TBL} CASCADE")
        res, errs = [], []
        barrier = threading.Barrier(2)

        def worker():
            e2 = create_engine(pg_target, future=True)
            try:
                barrier.wait(timeout=30)
                res.append(ensure_phase1_objects(e2))
            except Exception as ex:          # noqa: BLE001
                errs.append(ex)
            finally:
                e2.dispose()

        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=120)
        # ⚠️  `CREATE TABLE IF NOT EXISTS` POYGAGA QARSHI HIMOYA EMAS (PG'da tekshiruv va
        #     yaratish atomar emas -> `pg_type_typname_nsp_index` unique violation). Shu bois
        #     qo'llash yo'li MASLAHAT QULFI bilan seriyalanadi: biri qo'llaydi, ikkinchisi
        #     qulf ostida qayta tekshirib `noop-raced` qaytaradi. XATO bo'lmasligi SHART.
        assert not errs, [str(e) for e in errs]
        assert len(res) == 2, res
        assert sorted(r.split(":")[0] for r in res) == ["applied", "noop-raced"], res
        _assert_shape(eng)
        with eng.connect() as con:
            n = con.execute(text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='cash' AND c.relname='cao_uq_entry'")).scalar()
        assert n == 1, f"indeks {n} nusxada"
        from app.services.cash import schema_readiness as sr
        assert sr.opening_schema_problems(eng) == []
    finally:
        eng.dispose()
