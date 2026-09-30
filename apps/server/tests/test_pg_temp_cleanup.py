# -*- coding: utf-8 -*-
"""VAQTINCHALIK PostgreSQL klasterlari KAFOLATLANGAN tozalanadimi.

⚠️  NEGA BU TEST BOR. 2026-09-30 da to'liq regressiya
    `OSError: [Errno 28] No space left on device` bilan yiqildi: 59 ta
    `cashpg_test_*` papka (2.57 GB), `pytest-of-Developer` da 15.4 GB va 391 ta
    yetim `postgres.exe`. Sabab — `pgserver.get_server(...)` 15 faylda 20 marta
    chaqiriladi, 11 tasida `cleanup()` YO'Q, 4 tasi `tempfile.mkdtemp()` ishlatadi
    (pytest uni tozalamaydi), va `tests/cash/conftest.py` tozalashni `yield` dan
    KEYIN qilardi — setup yiqilsa umuman ishlamasdi.

Bu yerda HAQIQIY PostgreSQL ko'tarilmaydi: tekshiriladigan narsa — MEXANIZM
(ro'yxatga olish + `pytest_sessionfinish` da har qadamning ALOHIDA bajarilishi),
va uni soxta server bilan sinash aniqroq hamda arzonroq.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

CONFTEST = sys.modules.get("conftest") or sys.modules.get("tests.conftest")


def _root_conftest():
    """Ildiz `tests/conftest.py` moduli (pytest uni allaqachon yuklagan)."""
    for name in ("tests.conftest", "conftest"):
        m = sys.modules.get(name)
        if m is not None and hasattr(m, "pytest_sessionfinish"):
            return m
    raise AssertionError("ildiz conftest topilmadi")


class _FakeSrv:
    def __init__(self, fail: bool = False):
        self.cleaned = False
        self._fail = fail

    def cleanup(self):
        self.cleaned = True
        if self._fail:
            raise RuntimeError("cleanup ataylab yiqildi")


def test_TRACKER_ornatilgan():
    """`get_server` o'ralganmi — usiz hech narsa ro'yxatga tushmaydi."""
    pgserver = pytest.importorskip("pgserver")
    assert getattr(pgserver, "_savdoos_tracked", False) is True
    assert pgserver.get_server.__name__ == "_tracked"


def test_YARATILGAN_server_royxatga_tushadi(monkeypatch, tmp_path):
    """⚠️  Bu ro'yxat — tozalashning YAGONA manbasi."""
    pgserver = pytest.importorskip("pgserver")
    c = _root_conftest()
    fake = _FakeSrv()
    # o'ralgan funksiyaning ICHKI asli — soxta server qaytarsin
    monkeypatch.setattr(pgserver, "get_server", pgserver.get_server)  # o'ram saqlanadi
    before = len(c._PG_SERVERS)
    c._PG_SERVERS.append((fake, str(tmp_path)))
    try:
        assert len(c._PG_SERVERS) == before + 1
    finally:
        c._PG_SERVERS.remove((fake, str(tmp_path)))


def test_SESSIONFINISH_serverni_toxtatadi_va_papkani_ochiradi(tmp_path):
    c = _root_conftest()
    d = tmp_path / "pgdata"
    d.mkdir()
    (d / "PG_VERSION").write_text("16", encoding="utf-8")
    fake = _FakeSrv()
    c._PG_SERVERS.append((fake, str(d)))
    c.pytest_sessionfinish(session=None, exitstatus=0)
    assert fake.cleaned is True, "server to'xtatilmadi"
    assert not os.path.isdir(d), "papka o'chirilmadi"
    assert c._PG_SERVERS == [], "ro'yxat bo'shatilmadi"


def test_CLEANUP_yiqilsa_ham_PAPKA_ochiriladi(tmp_path):
    """⚠️  ASOSIY NUQSON ESKI KODDA: `dispose()` va `cleanup()` bitta `try` da edi,
        birinchisi yiqilsa ikkinchisiga yetib borilmasdi va papka diskda qolardi."""
    c = _root_conftest()
    d = tmp_path / "pgdata2"
    d.mkdir()
    fake = _FakeSrv(fail=True)
    c._PG_SERVERS.append((fake, str(d)))
    c.pytest_sessionfinish(session=None, exitstatus=1)
    assert fake.cleaned is True
    assert not os.path.isdir(d), "cleanup() yiqilgach papka QOLIB KETDI"


def test_KOP_server_HAMMASI_tozalanadi(tmp_path):
    """Bittasi yiqilsa QOLGANLARI baribir tozalanishi SHART."""
    c = _root_conftest()
    dirs, srvs = [], []
    for i, fail in enumerate((False, True, False)):
        d = tmp_path / f"pg{i}"
        d.mkdir()
        dirs.append(d)
        s = _FakeSrv(fail=fail)
        srvs.append(s)
        c._PG_SERVERS.append((s, str(d)))
    c.pytest_sessionfinish(session=None, exitstatus=0)
    assert all(s.cleaned for s in srvs), "ba'zi serverlar to'xtatilmadi"
    assert not any(os.path.isdir(d) for d in dirs), "ba'zi papkalar qoldi"


def test_SETUP_YIQILSA_ham_royxat_tozalanadi(tmp_path):
    """Fikstura `yield` ga YETMASDAN yiqilgan holat — eski kod aynan shu yerda oqardi.

    Ro'yxatga server YARATILGAN ZAHOTI tushadi (fikstura tugashini KUTMAYDI), shu
    bois setup o'rtasida istisno bo'lsa ham `pytest_sessionfinish` uni topadi."""
    c = _root_conftest()
    d = tmp_path / "pg_setup_fail"
    d.mkdir()
    fake = _FakeSrv()
    c._PG_SERVERS.append((fake, str(d)))        # «yaratildi», keyin setup yiqildi
    c.pytest_sessionfinish(session=None, exitstatus=2)
    assert fake.cleaned and not os.path.isdir(d)


def test_CASH_conftest_yield_dan_keyin_TOZALAMAYDI():
    """Eski (oqadigan) naqsh QAYTIB KELMASIN — qo'riqchi."""
    import pathlib
    src = pathlib.Path(__file__).parent.joinpath("cash", "conftest.py").read_text(encoding="utf-8")
    body = src.split("yield env", 1)[1]
    assert "srv.cleanup()" not in body, "tozalash yana `yield` dan keyinga qaytdi"
    assert "engine.dispose()" not in body
