# -*- coding: utf-8 -*-
"""PostgreSQL mijoz versiyasi GARDI — regressiya.

NEGA BU TEST BOR: birinchi HAQIQIY production backup'i shu sababdan yiqildi —

    pg_dump: error: aborting because of server version mismatch
    server version: 18.6 ... pg_dump version: 16.15

Holbuki workflow `postgresql-client-17` ni MUVAFFAQIYATLI o'rnatgan edi (17.11).
Sabab: Debian/Ubuntu'da `/usr/bin/pg_dump` haqiqiy binar EMAS — u `pg_wrapper` ga symlink
va qaysi versiyani ishga tushirishni O'ZI hal qiladi. GitHub runner obrazida PostgreSQL 16
oldindan o'rnatilgani uchun wrapper DOIM 16 ni tanlardi.

Test HAQIQIY Postgres talab qilmaydi: `pg_dump`/`psql` o'rniga versiya chop etadigan
soxta binarlar qo'yiladi va gard mantig'i to'g'ridan-to'g'ri sinaladi. Shu bois u tez
va har mashinada ishlaydi.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
LIB = ROOT / "scripts" / "lib" / "pg_client.sh"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash kerak")


def _stub(dirpath: pathlib.Path, name: str, version_line: str) -> None:
    """Versiya chop etadigan soxta binar."""
    p = dirpath / name
    p.write_text(f'#!/usr/bin/env bash\necho "{version_line}"\n', encoding="utf-8")
    p.chmod(0o755)


def _make_client(tmp_path: pathlib.Path, client_major: str, server_version: str) -> pathlib.Path:
    """PG_BIN katalogi: berilgan versiyali pg_dump + serverni shu deb ko'rsatadigan psql."""
    d = tmp_path / f"bin{client_major}"
    d.mkdir()
    _stub(d, "pg_dump", f"pg_dump (PostgreSQL) {client_major}.1 (Ubuntu {client_major}.1-1)")
    _stub(d, "pg_restore", f"pg_restore (PostgreSQL) {client_major}.1")
    # `psql -tAc 'SHOW server_version'` -> server versiyasi. Argumentlar e'tiborga olinmaydi.
    _stub(d, "psql", server_version)
    return d


def _run_guard(bin_dir: pathlib.Path) -> subprocess.CompletedProcess:
    script = textwrap.dedent(f"""
        set -Eeuo pipefail
        fail() {{ echo "::error::$*" >&2; exit 1; }}
        . "{LIB.as_posix()}"
        PG_BIN="{bin_dir.as_posix()}"
        pg_client_resolve
        pg_client_require_ge "postgresql://ignored/db"
        echo "GUARD_PASSED"
    """)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)


def test_client_older_than_server_is_refused_before_dump(tmp_path):
    """server major 18 + mijoz major 16 -> DUMPDAN OLDIN yiqilishi SHART.

    Bu aynan production'da bo'lgan holat. Gard bo'lmasa pg_dump o'zi yiqilardi, lekin
    sabab operator uchun tushunarsiz qolardi va workflow "nega artefakt yo'q?" degan
    savolni qoldirardi."""
    d = _make_client(tmp_path, "16", "18.6 (Debian 18.6-1.pgdg13+2)")
    r = _run_guard(d)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"eski mijoz O'TKAZIB YUBORILDI:\n{out}"
    assert "GUARD_PASSED" not in out
    assert "MIJOZ ESKI" in out, out
    # Xabar operatorga ANIQ yo'l ko'rsatsin
    assert "server_major=18" in out and "pg_dump_major=16" in out, out
    assert "postgresql-client-18" in out, out


def test_client_matching_server_is_allowed(tmp_path):
    """server major 18 + mijoz major 18 -> RUXSAT."""
    d = _make_client(tmp_path, "18", "18.6 (Debian 18.6-1.pgdg13+2)")
    r = _run_guard(d)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "GUARD_PASSED" in out
    assert "server_major=18" in out and "pg_dump_major=18" in out, out


def test_newer_client_is_allowed(tmp_path):
    """Mijoz YANGI bo'lsa ruxsat (shart `>=`, `==` EMAS).

    Aks holda Railway serverni yangilagan kunning ertasiga backup to'xtardi — ya'ni
    qattiq tenglik talabi o'zi nosozlik manbai bo'lardi."""
    d = _make_client(tmp_path, "19", "18.6 (Debian 18.6-1.pgdg13+2)")
    r = _run_guard(d)
    assert r.returncode == 0, (r.stdout + r.stderr)
    assert "GUARD_PASSED" in (r.stdout + r.stderr)


def test_unreadable_server_version_fails_closed(tmp_path):
    """Server versiyasini o'qib bo'lmasa DAVOM ETMAYMIZ (fail-closed).

    "Bilmayman" ni "mos" deb hisoblash aynan jim nosozlikka olib borardi."""
    d = tmp_path / "broken"
    d.mkdir()
    _stub(d, "pg_dump", "pg_dump (PostgreSQL) 18.1")
    _stub(d, "pg_restore", "pg_restore (PostgreSQL) 18.1")
    (d / "psql").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (d / "psql").chmod(0o755)
    r = _run_guard(d)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "server versiyasini aniqlab bo'lmadi" in out, out


def test_resolver_prefers_explicit_pg_bin_over_path(tmp_path):
    """PG_BIN berilgan bo'lsa PATH'dagi (pg_wrapper bo'lishi mumkin) binar YUTMAYDI.

    Production nosozligining ILDIZI shu edi: yangi mijoz o'rnatilgan, lekin PATH eskisini
    tanlagan. Shu bois aniq ko'rsatma har doim ustun bo'lishi kerak."""
    good = _make_client(tmp_path, "18", "18.6 (Debian 18.6)")
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _stub(decoy, "pg_dump", "pg_dump (PostgreSQL) 16.15 (Ubuntu 16.15-1)")

    script = textwrap.dedent(f"""
        set -Eeuo pipefail
        fail() {{ echo "::error::$*" >&2; exit 1; }}
        export PATH="{decoy.as_posix()}:$PATH"
        . "{LIB.as_posix()}"
        PG_BIN="{good.as_posix()}"
        pg_client_resolve
        echo "CHOSEN=$PG_DUMP"
        pg_client_require_ge "postgresql://ignored/db"
    """)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "CHOSEN=" in out and "bin18" in out, out
    assert "pg_dump_major=18" in out, out
