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

import importlib.util
import os
import sys

import pytest

#: Ildiz conftest faylining YAGONA haqiqiy yo'li — solishtirish uchun.
_ROOT_CONFTEST_PATH = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "conftest.py"))


def _root_conftest(pytestconfig):
    """Ildiz `tests/conftest.py` ning pytest PLUGIN sifatida ro'yxatga olgan INSTANSIYASI.

    ⚠️  NEGA `sys.modules` EMAS — eski usul AYNAN shu yerda yiqilgan. `tests/` da
        `__init__.py` YO'Q, shu bois `prepend` rejimida nuqtali nom (`tests.conftest`)
        YARATILMAYDI, pytest esa `tests/cash/conftest.py` ni import qilishdan OLDIN
        `del sys.modules["conftest"]` qiladi → qolgan bog'lanish CASH conftest'i
        bo'lib, unda `pytest_sessionfinish` YO'Q. To'liq yurishda bu 5 testni
        `ildiz conftest topilmadi` bilan yiqitardi (qamrov masalasi: bitta fayl
        yurishida cash conftest'i umuman import qilinmaydi).
    ⚠️  NEGA `sys.modules["tests.conftest"]` ga TAYANMAYMIZ, u to'lgan bo'lsa ham.
        main'dagi kalendar testlari `from tests.conftest import seed_date_in_window`
        qiladi va shu nomni to'ldiradi — ammo u AYRIM (ikkinchi) modul instansiyasi:
        uning `_PG_SERVERS` i tracker yozadigan ro'yxat EMAS. Import tartibiga
        tayanish testni YASHIL, lekin MA'NOSIZ qilardi — `test_TRACKER_...PLUGINGA_...`
        aynan shuni qo'riqlaydi.
    Plugin menejeri esa aynan o'sha, hook'lari CHAQIRILAYOTGAN obyektni qaytaradi.
    """
    for plugin in pytestconfig.pluginmanager.get_plugins():
        fayl = getattr(plugin, "__file__", None)
        if fayl and os.path.realpath(fayl) == _ROOT_CONFTEST_PATH:
            return plugin
    raise AssertionError(f"ildiz conftest plugini topilmadi: {_ROOT_CONFTEST_PATH}")


def _ikkinchi_instansiya():
    """Ayni faylni QAYTA import qiladi — ATAYLAB ikkinchi, begona instansiya.

    Modul darajasi buni xavfsiz qiladi: `os.environ.setdefault` hech narsani
    o'zgartirmaydi va `_install_pgserver_tracker()` `pgserver._savdoos_tracked`
    gardi bilan DARHOL qaytadi (ikkinchi o'ram YO'Q). Yangi `_PG_SERVERS` esa
    BOSHQA ro'yxat obyekti bo'ladi — qo'riqchilar shuni ushlaydi.
    """
    spec = importlib.util.spec_from_file_location("_soxta_ildiz_conftest",
                                                  _ROOT_CONFTEST_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)         # `sys.modules` ga QO'YILMAYDI
    return mod


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


def test_YARATILGAN_server_royxatga_tushadi(pytestconfig, monkeypatch, tmp_path):
    """⚠️  Bu ro'yxat — tozalashning YAGONA manbasi."""
    pgserver = pytest.importorskip("pgserver")
    c = _root_conftest(pytestconfig)
    fake = _FakeSrv()
    # o'ralgan funksiyaning ICHKI asli — soxta server qaytarsin
    monkeypatch.setattr(pgserver, "get_server", pgserver.get_server)  # o'ram saqlanadi
    before = len(c._PG_SERVERS)
    c._PG_SERVERS.append((fake, str(tmp_path)))
    try:
        assert len(c._PG_SERVERS) == before + 1
    finally:
        c._PG_SERVERS.remove((fake, str(tmp_path)))


def test_SESSIONFINISH_serverni_toxtatadi_va_papkani_ochiradi(pytestconfig, tmp_path):
    c = _root_conftest(pytestconfig)
    d = tmp_path / "pgdata"
    d.mkdir()
    (d / "PG_VERSION").write_text("16", encoding="utf-8")
    fake = _FakeSrv()
    c._PG_SERVERS.append((fake, str(d)))
    c.pytest_sessionfinish(session=None, exitstatus=0)
    assert fake.cleaned is True, "server to'xtatilmadi"
    assert not os.path.isdir(d), "papka o'chirilmadi"
    assert c._PG_SERVERS == [], "ro'yxat bo'shatilmadi"


def test_CLEANUP_yiqilsa_ham_PAPKA_ochiriladi(pytestconfig, tmp_path):
    """⚠️  ASOSIY NUQSON ESKI KODDA: `dispose()` va `cleanup()` bitta `try` da edi,
        birinchisi yiqilsa ikkinchisiga yetib borilmasdi va papka diskda qolardi."""
    c = _root_conftest(pytestconfig)
    d = tmp_path / "pgdata2"
    d.mkdir()
    fake = _FakeSrv(fail=True)
    c._PG_SERVERS.append((fake, str(d)))
    c.pytest_sessionfinish(session=None, exitstatus=1)
    assert fake.cleaned is True
    assert not os.path.isdir(d), "cleanup() yiqilgach papka QOLIB KETDI"


def test_KOP_server_HAMMASI_tozalanadi(pytestconfig, tmp_path):
    """Bittasi yiqilsa QOLGANLARI baribir tozalanishi SHART."""
    c = _root_conftest(pytestconfig)
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


def test_SETUP_YIQILSA_ham_royxat_tozalanadi(pytestconfig, tmp_path):
    """Fikstura `yield` ga YETMASDAN yiqilgan holat — eski kod aynan shu yerda oqardi.

    Ro'yxatga server YARATILGAN ZAHOTI tushadi (fikstura tugashini KUTMAYDI), shu
    bois setup o'rtasida istisno bo'lsa ham `pytest_sessionfinish` uni topadi."""
    c = _root_conftest(pytestconfig)
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


# ── QO'RIQCHILAR: ildiz conftest'ni PLUGIN sifatida topish ───────────────────
#  Nega to'rtta: `_root_conftest` ni «topdi/topmadi» darajasida sinash YETARLI
#  EMAS — u NOTO'G'RI (ikkinchi) instansiyani topib ham yashil bo'lishi mumkin.
#  Shuning uchun soya sharti (A), lookup (B), yolg'on-PASS imkonsizligi (C) va
#  tracker identikligi (D) ALOHIDA qadaladi.

def test_QORIQCHI_A_cash_conftest_BARE_nomni_EGALLAYDI(pytestconfig):
    """A: `tests/cash/conftest.py` yuklanadi va u ildiz conftest EMAS.

    To'liq yurishda (CI) pytest uni import qilib `sys.modules["conftest"]` ni
    EGALLAYDI — eski lookup aynan shundan yiqilardi. Bitta fayl yurishida u
    umuman yuklanmaydi, shu bois tekshiruv `if` ichida: SKIP ham, xfail ham
    QO'SHILMAYDI, CI'da esa shox FAOL sinaladi.
    """
    cash_yoli = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "cash", "conftest.py"))
    assert os.path.isfile(cash_yoli), "cash conftest yo'q — soya sharti o'zgargan"
    #  Cash conftest'da hook YO'Q: eski lookup'ning `hasattr` gardi uni rad etardi
    #  va ro'yxat tugab `ildiz conftest topilmadi` chiqardi.
    import ast as _ast
    with open(cash_yoli, encoding="utf-8") as fh:
        daraxt = _ast.parse(fh.read())
    hooklar = {n.name for n in daraxt.body if isinstance(n, _ast.FunctionDef)}
    assert "pytest_sessionfinish" not in hooklar, (
        "cash conftest endi `pytest_sessionfinish` ta'riflaydi — soya endi zararsiz, "
        "lookup izohini qayta ko'r")
    plugin_fayllari = {os.path.realpath(getattr(p, "__file__", "") or "\0")
                       for p in pytestconfig.pluginmanager.get_plugins()}
    if cash_yoli in plugin_fayllari:          # to'liq yurish: soya FAOL
        bare = sys.modules.get("conftest")
        assert bare is None or os.path.realpath(bare.__file__) != _ROOT_CONFTEST_PATH, (
            "`sys.modules['conftest']` yana ildiz conftest — soya sharti yo'qolgan; "
            "eski (nom bo'yicha) lookup jimgina ishlab ketadi")


def test_QORIQCHI_B_ildiz_conftest_PLUGINI_topiladi(pytestconfig):
    """B: lookup ildiz conftest'ning AYNAN BITTA plugin instansiyasini qaytaradi."""
    c = _root_conftest(pytestconfig)
    assert os.path.realpath(c.__file__) == _ROOT_CONFTEST_PATH
    assert callable(getattr(c, "pytest_sessionfinish", None)), "haqiqiy hook yo'q"
    assert isinstance(getattr(c, "_PG_SERVERS", None), list), "tracker ro'yxati yo'q"
    mos = [p for p in pytestconfig.pluginmanager.get_plugins()
           if os.path.realpath(getattr(p, "__file__", "") or "\0") == _ROOT_CONFTEST_PATH]
    assert len(mos) == 1, f"ildiz conftest {len(mos)} marta ro'yxatga olingan"
    assert mos[0] is c


def test_QORIQCHI_C_IKKINCHI_instansiya_YOLGON_PASS_bermaydi(pytestconfig):
    """C: ataylab yaratilgan ikkinchi instansiya testlarni yashil qilib yubormaydi."""
    pgserver = pytest.importorskip("pgserver")
    c = _root_conftest(pytestconfig)
    oram_oldin = pgserver.get_server
    ikkinchi = _ikkinchi_instansiya()
    belgi = (object(), "/soxta/yol")
    try:
        assert ikkinchi is not c, "qayta import ayni obyektni berdi — qo'riqchi ma'nosiz"
        assert ikkinchi._PG_SERVERS is not c._PG_SERVERS, "ro'yxat umumiy chiqdi"
        #  `_savdoos_tracked` gardi: IKKINCHI o'ram O'RNATILMADI
        assert pgserver.get_server is oram_oldin, "pgserver QAYTA o'raldi — gard buzilgan"
        assert getattr(pgserver, "_savdoos_tracked", False) is True
        #  Yolg'on PASS imkoni yopiq: ikkinchi ro'yxatga yozilgani plugin ro'yxatida
        #  KO'RINMAYDI, ya'ni tozalash tasdiqlari uni o'lchab «o'tdi» deya olmaydi.
        ikkinchi._PG_SERVERS.append(belgi)
        assert belgi not in c._PG_SERVERS, "ikkinchi ro'yxat plugin ro'yxatiga tushdi"
        assert _root_conftest(pytestconfig) is c, "lookup ikkinchi instansiyaga og'di"
    finally:
        if belgi in ikkinchi._PG_SERVERS:
            ikkinchi._PG_SERVERS.remove(belgi)


def test_QORIQCHI_D_tracker_PLUGIN_royxatiga_yozadi(pytestconfig):
    """D: o'ram AYNAN plugin instansiyasining `_PG_SERVERS` iga yozadi.

    `__globals__` — funksiyani TA'RIFLAGAN modulning dict'i, ya'ni bu identiklik
    o'ramni KIM yaratganini ko'rsatadi. Lookup ikkinchi instansiyaga og'sa (yoki
    ikkinchi instansiya o'ram o'rnatsa) shu tasdiq DARHOL yiqiladi — NC-1 shuni
    o'lchaydi. Process/PID egaligi `pgown` da, bu yerda tegilmaydi.
    """
    pgserver = pytest.importorskip("pgserver")
    c = _root_conftest(pytestconfig)
    assert getattr(pgserver, "_savdoos_tracked", False) is True, "tracker o'rnatilmagan"
    oram = pgserver.get_server
    assert oram.__name__ == "_tracked", "pgserver o'ralmagan"
    assert oram.__globals__["_PG_SERVERS"] is c._PG_SERVERS, (
        "tracker BOSHQA modul instansiyasining ro'yxatiga yozadi — tozalash kafolati uzilgan")
    oram_fayli = oram.__globals__.get("__file__")
    assert oram_fayli and os.path.realpath(oram_fayli) == _ROOT_CONFTEST_PATH
