# -*- coding: utf-8 -*-
"""R-DDL — OTA-KALIT PREREQUISITE, SQLite tomoni (haqiqiy boot, haqiqiy PRAGMA).

Postgres tomoni: `tests/test_parent_key_prereq_pg.py`. Bu fayl SQLite uchun:
  · fresh boot ota-kalit indekslarini QURADI (noyob, QISMAN EMAS, aynan `(company_id, id)`);
  · ikkinchi boot — no-op;
  · ilova ulanishida `PRAGMA foreign_keys=ON` (mahalliy to'plam FK buzilishini KO'RADI);
  · kompozit FK SQLite'da ham MAJBURLANADI (ota-kalitga tayanadi).

⚠️  Mahalliy SQLite'da FK majburlanmasligi haqidagi eski taxmin XATO: `app/db/session.py`
    har ulanishda pragmani YOQADI va izoh uni o'chirishni TAQIQLAYDI.
"""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core import required_schema as rs

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # apps/server

_PARENTS = {
    "uq_purchases_company_id": ("purchases", ("company_id", "id")),
    "uq_employees_company_id": ("employees", ("company_id", "id")),
}


def _boot(db_path):
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, timeout=900,
                       env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))
    return url, r


def _shape(eng, name, table):
    """(noyob, qisman_emas, ustunlar) yoki None — `PRAGMA index_list`/`index_info`."""
    with eng.connect() as con:
        for row in con.exec_driver_sql(f'PRAGMA index_list("{table}")').fetchall():
            if row[1] != name:
                continue
            cols = tuple(r[2] for r in con.exec_driver_sql(
                f'PRAGMA index_info("{name}")').fetchall())
            return bool(row[2]), not bool(row[4]), cols
    return None


# ═══ 7) FRESH SQLite — shakl ANIQ ═══════════════════════════════════════════
def test_7_fresh_sqlite_ota_kalit_shakli(tmp_path):
    url, r = _boot(tmp_path / "t7.db")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    eng = create_engine(url, future=True)
    try:
        for name, (table, cols) in _PARENTS.items():
            got = _shape(eng, name, table)
            assert got is not None, f"{name} YO'Q"
            uniq, whole, gcols = got
            assert uniq, f"{name} NOYOB EMAS"
            assert whole, f"{name} QISMAN"
            assert gcols == cols, (name, gcols)
        assert rs.parent_key_problems(eng) == []
    finally:
        eng.dispose()


def test_7b_ikkinchi_boot_sqlite_no_op(tmp_path):
    url, r1 = _boot(tmp_path / "t7b.db")
    assert r1.returncode == 0
    _, r2 = _boot(tmp_path / "t7b.db")
    assert r2.returncode == 0, (r2.stdout + r2.stderr)[-1200:]
    eng = create_engine(url, future=True)
    try:
        for name, (table, cols) in _PARENTS.items():
            assert _shape(eng, name, table) == (True, True, cols)
    finally:
        eng.dispose()


# ═══ 8) ILOVA ULANISHIDA `foreign_keys=ON` ══════════════════════════════════
def test_8_ilova_ulanishida_foreign_keys_ON():
    """Bu ILOVANING O'Z dvigateli (`app/db/session.py`) — test dvigateli emas."""
    from app.db.session import engine as app_engine
    if app_engine.dialect.name != "sqlite":
        pytest.skip("bu sinov SQLite dvigateli uchun")
    with app_engine.connect() as con:
        assert con.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# ═══ 9) KOMPOZIT FK SQLite'da MAJBURLANADI (ota-kalitga tayanadi) ═══════════
def test_9_sqlite_kompozit_FK_majburlanadi(tmp_path):
    url, r = _boot(tmp_path / "t9.db")
    assert r.returncode == 0
    eng = create_engine(url, future=True)
    ch = "rddl_child_" + uuid.uuid4().hex[:8]
    try:
        with eng.begin() as con:
            con.exec_driver_sql("PRAGMA foreign_keys=ON")
            con.exec_driver_sql(
                f'CREATE TABLE {ch} (id TEXT PRIMARY KEY, company_id TEXT, purchase_id TEXT, '
                f'FOREIGN KEY (company_id, purchase_id) REFERENCES purchases (company_id, id))')
        # ota qator YO'Q -> RAD etiladi (pragma ON bo'lgani uchun)
        with pytest.raises(IntegrityError) as ei:
            with eng.begin() as con:
                con.exec_driver_sql("PRAGMA foreign_keys=ON")
                con.execute(text(f"INSERT INTO {ch} (id, company_id, purchase_id) "
                                 "VALUES (:i, :c, :p)"),
                            {"i": str(uuid.uuid4()), "c": str(uuid.uuid4()),
                             "p": str(uuid.uuid4())})
        msg = str(ei.value).lower()
        # ⚠️  SEZGIRLIK: ota-kalit indeksi BO'LMASA SQLite butunlay boshqa xato beradi —
        #     `OperationalError: foreign key mismatch` (ya'ni FK UMUMAN ishlamaydi). Shu bois
        #     aynan «constraint failed» talab qilinadi: u FK HAQIQATAN majburlanganini
        #     isbotlaydi, «mismatch» esa ota-kalit yo'qligini bildiradi.
        assert "foreign key constraint failed" in msg, msg
        assert "mismatch" not in msg, "ota-kalit indeksi YO'Q — FK majburlanmadi: " + msg
    finally:
        with eng.begin() as con:
            con.exec_driver_sql(f"DROP TABLE IF EXISTS {ch}")
        eng.dispose()


# ═══ IFLOS SXEMA (SQLite): almashtirilmaydi, tayyorlik QIZIL ════════════════
def test_sqlite_iflos_indeks_almashtirilmaydi(tmp_path):
    url, r = _boot(tmp_path / "td.db")
    assert r.returncode == 0
    eng = create_engine(url, future=True)
    try:
        with eng.begin() as con:
            con.exec_driver_sql("DROP INDEX uq_purchases_company_id")
            con.exec_driver_sql("CREATE UNIQUE INDEX uq_purchases_company_id "
                                "ON purchases (id, company_id)")      # ustunlar TESKARI
        probs = rs.parent_key_problems(eng)
        assert any("ustunlari mos emas" in p for p in probs), probs
    finally:
        eng.dispose()
    _, r2 = _boot(tmp_path / "td.db")
    assert r2.returncode == 0, "SQLite'da boot TO'XTAMAYDI"
    eng = create_engine(url, future=True)
    try:
        assert _shape(eng, "uq_purchases_company_id", "purchases")[2] == ("id", "company_id"), \
            "boot indeksni JIMGINA almashtirdi"
        assert any("uq_purchases_company_id" in m for m in rs.missing(eng)), rs.missing(eng)
    finally:
        eng.dispose()
