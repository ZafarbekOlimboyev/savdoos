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
import shlex
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
    # AYNAN production shakli — paket qismi bilan ("...pgdg24.04+2"). Ochko'z naqsh
    # aynan shu qismdan `2` ni major deb o'qigan edi, shu bois gard testlari ham
    # HAQIQIY satr ustida ishlaydi (soddalashtirilgan versiya buni o'tkazib yuborardi).
    _stub(d, "pg_dump",
          f"pg_dump (PostgreSQL) {client_major}.6 (Ubuntu {client_major}.6-1.pgdg24.04+2)")
    _stub(d, "pg_restore",
          f"pg_restore (PostgreSQL) {client_major}.6 (Ubuntu {client_major}.6-1.pgdg24.04+2)")
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


def _parse(version_text: str) -> subprocess.CompletedProcess:
    """KANONIK parserni to'g'ridan-to'g'ri chaqiradi (repoda YAGONA nusxa)."""
    script = textwrap.dedent(f"""
        set -Eeuo pipefail
        fail() {{ echo "::error::$*" >&2; exit 1; }}
        . "{LIB.as_posix()}"
        pg_parse_major {shlex.quote(version_text)}
    """)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)


# ═══ KANONIK PARSER — AYNIQSA production'da uchragan satrlar ════════════════
#
# Production backup'i AYNAN shu satrda yiqilgan edi. `action.yml` dagi ALOHIDA
# (ochko'z) naqsh paket raqamini major deb o'qigan:
#     "pg_dump (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)"  ->  2   (kutilgani 18)
# Endi parser repoda BITTA va u "PostgreSQL)" tokeniga BOG'LANGAN.
@pytest.mark.parametrize("text,expected", [
    # ── production'da haqiqatan ko'ringan shakl (paket qismi bilan) ──────────
    ("pg_dump (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)", "18"),
    ("pg_dump (PostgreSQL) 17.11 (Ubuntu 17.11-1.pgdg24.04+2)", "17"),
    ("pg_dump (PostgreSQL) 16.15 (Ubuntu 16.15-1.pgdg24.04+2)", "16"),
    # ── boshqa binarlar ─────────────────────────────────────────────────────
    ("psql (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)", "18"),
    ("pg_restore (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)", "18"),
    # ── paket qismisiz ──────────────────────────────────────────────────────
    ("pg_dump (PostgreSQL) 18.6", "18"),
    ("pg_dump (PostgreSQL) 18", "18"),
    # ── `SHOW server_version` chiqishi ("PostgreSQL" so'zi YO'Q) ────────────
    ("18.6 (Debian 18.6-1.pgdg13+2)", "18"),
    ("18.6", "18"),
    # ── ikki xonali major kelajakda ─────────────────────────────────────────
    ("pg_dump (PostgreSQL) 100.1 (Ubuntu 100.1-1)", "100"),
])
def test_canonical_parser_extracts_major(text, expected):
    r = _parse(text)
    assert r.returncode == 0, r.stderr
    got = r.stdout.strip()
    assert got == expected, f"{text!r} -> {got!r}, kutilgani {expected!r}"


def test_parser_is_not_greedy_on_package_suffix():
    """Ochko'z naqsh AYNAN shu yerda yiqilgan: '...pgdg24.04+2)' dan 2 ni olardi.

    Bu test o'sha regressiyani MIXLAB qo'yadi — kelajakda kimdir naqshni
    'satrdagi oxirgi son' ko'rinishiga qaytarsa shu yerda yiqiladi."""
    r = _parse("pg_dump (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)")
    got = r.stdout.strip()
    assert got != "2", "ochko'z naqsh QAYTIB KELDI — paket raqami major deb o'qildi"
    assert got == "18"


def test_parser_returns_empty_on_garbage():
    """Tushunarsiz matnda parser BO'SH qaytaradi (qarorni strict variant beradi)."""
    r = _parse("some unrelated output")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_strict_parser_fails_closed_on_garbage():
    """`pg_parse_major_strict` aniqlab bo'lmasa TO'XTAYDI — jimgina davom ETMAYDI."""
    script = textwrap.dedent(f"""
        set -Eeuo pipefail
        fail() {{ echo "::error::$*" >&2; exit 1; }}
        . "{LIB.as_posix()}"
        pg_parse_major_strict "some unrelated output" "sinov"
        echo "DAVOM_ETDI"
    """)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "DAVOM_ETDI" not in out
    assert "Versiyani aniqlab bo'lmadi" in out, out


def test_composite_action_has_no_own_regex():
    """Composite action O'Z naqshini SAQLAMASLIGI shart.

    Production nosozligining ildizi aynan IKKI NUSXA edi: `pg_client.sh` tuzatilgan,
    `action.yml` esa tuzatilmagan. Bu test drift qaytib kelishini bloklaydi."""
    action = (ROOT / ".github" / "actions" / "pg-client" / "action.yml").read_text(encoding="utf-8")
    assert "pg_parse_major_strict" in action, "action kanonik parserni chaqirmayapti"
    assert "scripts/lib/pg_client.sh" in action, "action umumiy kutubxonani source qilmayapti"
    for banned in ("sed -nE 's/.*[^0-9]", "grep -oE '[0-9]+'"):
        assert banned not in action, f"action.yml da ALOHIDA versiya naqshi paydo bo'ldi: {banned}"


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
