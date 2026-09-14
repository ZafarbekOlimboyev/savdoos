# -*- coding: utf-8 -*-
"""`scripts/ci/verify_pytest_run.py` — CI «test HAQIQATAN bajarildimi» darvozasi (Phase 4A.1).

⚠️  NEGA. pytest exit kodi bajarilishni isbotlamaydi: test tanasidagi
    `pytest.exit(returncode=0)`, modul/katalog darajasidagi skip, `collect_ignore`,
    `pytest_collection_modifyitems` yoki `if dependency: def test_...` bilan to'plamning bir
    qismi yo'qolib, pytest YASHIL tugaydi. Bu fayl darvozaning har qoidasini sintetik junit
    bilan, eng muhimi — HAQIQIY ichki pytest sessiyasi bilan sinaydi: pytest 0 qaytaradi,
    darvoza esa QIZIL bo'lishi shart.

⚠️  SON EMAS, IDENTIFIKATSIYA (ikki review). Umumiy son (~190 parametr ortiqchasi) va modul
    bo'yicha son ham (parametr/import nusxalari) yo'qolgan funksiyani yashirardi. Sinovlar
    shu bois parametrlangan modul bilan va ANIQ yo'qolgan funksiya id'sini tekshirib yoziladi.
"""
import importlib.util
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "verify_pytest_run", ROOT / "scripts" / "ci" / "verify_pytest_run.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


def _suite(tmp_path, files: dict[str, str]) -> pathlib.Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    for name, body in files.items():
        p = tests / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return tests


def _junit(tmp_path, cases) -> pathlib.Path:
    """cases: (classname, name, kind[, message[, text]]) — kind: passed|failure|error|skipped."""
    parts = []
    for c in cases:
        cls, name, kind = c[0], c[1], c[2]
        msg = c[3] if len(c) > 3 else ""
        body = c[4] if len(c) > 4 else ""
        inner = "" if kind == "passed" else f'<{kind} message="{msg}">{body}</{kind}>'
        parts.append(f'<testcase classname="{cls}" name="{name}">{inner}</testcase>')
    p = tmp_path / "junit.xml"
    p.write_text(f'<testsuites><testsuite>{"".join(parts)}</testsuite></testsuites>',
                 encoding="utf-8")
    return p


_TWO = {"test_a.py": "def test_1():\n    pass\n\ndef test_2():\n    pass\n",
        "test_b.py": "class TestX:\n    def test_3(self):\n        pass\n"}
_TWO_OK = [("tests.test_a", "test_1", "passed"), ("tests.test_a", "test_2", "passed"),
           ("tests.test_b.TestX", "test_3", "passed")]


def test_STATIK_son_modul_sinf_va_shartli_bloklarni_sanaydi_fixture_va_initli_sinfni_EMAS(tmp_path):
    tests = _suite(tmp_path, {
        **_TWO,
        "test_c.py": """
            import pytest
            @pytest.fixture
            def test_not_a_test():
                return 1
            class TestHelper:
                def __init__(self):
                    pass
                def test_hidden(self):
                    pass
            async def test_async():
                pass
            try:
                import yoq_paket
            except ImportError:
                yoq_paket = None
            if yoq_paket is not None:
                def test_shartli():
                    pass
            def helper():
                def test_ichki():
                    pass
        """,
        "helper.py": "def test_ignored():\n    pass\n",
    })
    total, per = V.static_test_count(tests)
    assert total == 5, per
    assert per["tests/test_c.py"] == 2
    assert ("tests/test_c.py" in V.static_test_functions(tests)
            and (None, "test_shartli") in V.static_test_functions(tests)["tests/test_c.py"])


def test_HAMMASI_otgan_toliq_sessiya_ISBOTLANADI(tmp_path):
    problems, _ = V.verify(_junit(tmp_path, _TWO_OK), _suite(tmp_path, _TWO), None)
    assert problems == []


def test_junit_YOQ_bolsa_QIZIL(tmp_path):
    problems, _ = V.verify(tmp_path / "yoq.xml", _suite(tmp_path, _TWO), None)
    assert problems and "junit XML yo'q" in problems[0]


def test_error_yoki_failure_QIZIL(tmp_path):
    j = _junit(tmp_path, [("tests.test_a", "test_1", "passed"), ("tests.test_a", "test_2", "error", "x"),
                          ("tests.test_b.TestX", "test_3", "failure", "y")])
    problems, _ = V.verify(j, _suite(tmp_path, _TWO), None)
    assert any("1 failure / 1 error" in p for p in problems), problems


def test_BITTA_funksiya_yoqolsa_SON_yetsa_ham_QIZIL(tmp_path):
    """review: parametr nusxalari umumiy (va modul) sonni to'ldiradi — qoida FUNKSIYA bo'yicha."""
    tests = _suite(tmp_path, _TWO)
    j = _junit(tmp_path, [("tests.test_a", f"test_1[{i}]", "passed") for i in range(10)]
               + [("tests.test_a", "test_2", "passed")])
    problems, _ = V.verify(j, tests, None)
    assert any("1 ta test funksiyasi junit'da YO'Q" in p and "tests/test_b.py::TestX::test_3" in p
               for p in problems), problems


def test_KUTILMAGAN_skip_QIZIL_royxatdagisi_OTADI(tmp_path):
    tests = _suite(tmp_path, _TWO)
    j = _junit(tmp_path, [("tests.test_a", "test_1", "passed"),
                          ("tests.test_a", "test_2", "skipped", "pgserver yo'q"),
                          ("tests.test_b.TestX", "test_3", "skipped", "CHECK faqat Postgres'da")])
    allow = tmp_path / "allow.txt"
    allow.write_text("# izoh\ntests.test_b.TestX::test_3 | CHECK faqat Postgres\n", encoding="utf-8")
    problems, report = V.verify(j, tests, allow)
    assert problems == ["KUTILMAGAN skip: tests.test_a::test_2 — pgserver yo'q"], problems
    assert any("kutilgan skip: tests.test_b.TestX::test_3" in r for r in report)


def test_ANIQ_id_qavsli_parametr_bilan_ISHLAYDI_glob_faqat_ochiq_belgilanganda(tmp_path):
    """review: fnmatch `[..]` ni belgi sinfi deb o'qirdi — parametrlangan id o'ziga mos kelmasdi."""
    tests = _suite(tmp_path, {"test_a.py": "def test_1():\n    pass\n\ndef test_2():\n    pass\n"})
    j = _junit(tmp_path, [("tests.test_a", "test_1[pgserver]", "skipped", "faqat PG18"),
                          ("tests.test_a", "test_1[external]", "skipped", "faqat PG18"),
                          ("tests.test_a", "test_2", "passed")])
    exact = tmp_path / "exact.txt"
    exact.write_text("tests.test_a::test_1[pgserver] | faqat PG18\n", encoding="utf-8")
    problems, _ = V.verify(j, tests, exact)
    assert problems == ["KUTILMAGAN skip: tests.test_a::test_1[external] — faqat PG18"], problems
    glob = tmp_path / "glob.txt"
    glob.write_text("glob:tests.test_a::test_1* | faqat PG18\n", encoding="utf-8")
    problems, _ = V.verify(j, tests, glob)
    assert problems == [], problems


def test_sabab_MOS_KELMASA_royxatdagi_id_ham_QIZIL(tmp_path):
    tests = _suite(tmp_path, {"test_a.py": "def test_1():\n    pass\n\ndef test_2():\n    pass\n"})
    j = _junit(tmp_path, [("tests.test_a", "test_1", "passed"),
                          ("tests.test_a", "test_2", "skipped", "boshqa sabab")])
    allow = tmp_path / "allow.txt"
    allow.write_text("tests.test_a::test_2 | CHECK faqat Postgres\n", encoding="utf-8")
    problems, _ = V.verify(j, tests, allow)
    assert any("KUTILMAGAN skip" in p for p in problems)


def test_MODUL_darajasidagi_skip_royxatda_bolsa_ham_QIZIL_haqiqiy_sabab_bilan(tmp_path):
    """review: junit bunday skip'da message='collection skipped' yozadi, haqiqiy sabab faqat
    MATNDA. Butun modul/katalogning CI'da yo'qolishi hech qachon kechirilmaydi."""
    tests = _suite(tmp_path, _TWO)
    j = _junit(tmp_path, _TWO_OK[:2] + [
        ("", "tests.test_b", "skipped", "collection skipped",
         "('tests/test_b.py', 1, 'Skipped: pgserver yo''q')")])
    allow = tmp_path / "allow.txt"
    allow.write_text("glob:* | collection skipped\nglob:* | pgserver\n", encoding="utf-8")
    problems, _ = V.verify(j, tests, allow)
    assert any("MODUL/KATALOG butunlay o'tkazib yuborildi: tests.test_b" in p and "pgserver" in p
               for p in problems), problems


def test_birorta_ham_OTMAGAN_bolsa_QIZIL(tmp_path):
    tests = _suite(tmp_path, {"test_a.py": "def test_1():\n    pass\n"})
    j = _junit(tmp_path, [("tests.test_a", "test_1", "skipped", "CHECK faqat Postgres")])
    allow = tmp_path / "allow.txt"
    allow.write_text("tests.test_a::test_1 | CHECK faqat Postgres\n", encoding="utf-8")
    problems, _ = V.verify(j, tests, allow)
    assert any("birorta ham test O'TMADI" in p for p in problems)


def test_notogri_allowlist_qatori_XATO(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("tests.test_a::test_1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        V.load_allowlist(allow)


@pytest.mark.parametrize("log,expected", [
    ("... !!!!! _pytest.outcomes.Exit: negctl !!!!!\n5 passed", "pytest.exit chaqirilgan"),
    ("!!!!!!! Interrupted: 1 error during collection !!!!!!!", "sessiya uzilgan"),
    ("INTERNALERROR> Traceback", "pytest ichki xatosi"),
    ("12 passed, 3 deselected in 1.0s", "3 ta test DESELECT"),
])
def test_pytest_LOGIDAGI_belgilar_QIZIL(tmp_path, log, expected):
    lp = tmp_path / "pytest.log"
    lp.write_text(log, encoding="utf-8")
    problems, _ = V.verify(_junit(tmp_path, _TWO_OK), _suite(tmp_path, _TWO), None, lp)
    assert any(expected in p for p in problems), problems


def test_pytest_LOGI_berilib_YOQ_bolsa_QIZIL(tmp_path):
    problems, _ = V.verify(_junit(tmp_path, _TWO_OK), _suite(tmp_path, _TWO), None,
                           tmp_path / "yoq.log")
    assert any("pytest logi yo'q" in p for p in problems)


def _real_pytest(tmp_path, files):
    tests = _suite(tmp_path, files)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    junit = tmp_path / "junit.xml"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-c", str(tmp_path / "pytest.ini"), "--rootdir", str(tmp_path),
                        f"--junitxml={junit}", "-o", "junit_family=xunit2", str(tests)],
                       cwd=tmp_path, capture_output=True, text=True, timeout=180)
    log = tmp_path / "pytest.log"
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    return r, tests, junit, log


# Parametrlangan modul: 1 statik funksiya -> 25 testcase. SON qoidasi quyidagi har holatda
# YASHIL bo'lardi — faqat FUNKSIYA identifikatsiyasi (va skip siyosati) qizartiradi.
_PARAM = {"test_a_param.py": "import pytest\n@pytest.mark.parametrize('x', range(25))\n"
                             "def test_p(x):\n    pass\n"}
_Z = {"test_z.py": "def test_3():\n    pass\n\ndef test_4():\n    pass\n\ndef test_5():\n    pass\n"}


@pytest.mark.parametrize("kind,extra,must", [
    ("test tanasida pytest.exit(returncode=0) — sessiya yarmida to'xtaydi",
     {"test_m_middle.py": "import pytest\ndef test_stop():\n"
                          "    pytest.exit('negctl: sessiya yarmida', returncode=0)\n"},
     "tests/test_z.py::test_3"),
    ("modul darajasidagi skip",
     {"test_m_middle.py": "import pytest\npytest.skip('modul butunlay', allow_module_level=True)\n"
                          "def test_never_1():\n    pass\n\ndef test_never_2():\n    pass\n"},
     "MODUL/KATALOG butunlay o'tkazib yuborildi"),
    ("katalog conftest'idagi skip (tests/cash/conftest.py naqshi)",
     {"sub/conftest.py": "import pytest\npytest.skip('katalog butunlay', allow_module_level=True)\n",
      "sub/test_s.py": "def test_s1():\n    pass\n\ndef test_s2():\n    pass\n"},
     "MODUL/KATALOG butunlay o'tkazib yuborildi"),
    # re-review: shartli ta'riflar — modul HECH NARSA yig'maydi, skip ham yozilmaydi
    ("if/try ichidagi test ta'riflari yig'ilmadi",
     {"test_cond.py": "try:\n    import yoq_paket_xyz as pgs\nexcept ImportError:\n    pgs = None\n"
                      "if pgs is not None:\n    def test_c1():\n        pass\n\n"
                      "    def test_c2():\n        pass\n"},
     "tests/test_cond.py::test_c1"),
    # re-review: conftest hook funksiyani jimgina olib tashlaydi ('deselected' YOZILMAYDI),
    # modul soni esa parametr nusxalari bilan to'ladi
    ("modifyitems funksiyani deselect'siz olib tashladi",
     {"conftest.py": "def pytest_collection_modifyitems(items):\n"
                     "    items[:] = [i for i in items if 'test_q' not in i.nodeid]\n",
      "test_p.py": "import pytest\n@pytest.mark.parametrize('x', range(5))\n"
                   "def test_p(x):\n    pass\n\ndef test_q():\n    pass\n"},
     "tests/test_p.py::test_q"),
    # re-review: ayni nomli katalog o'chirilgan modulning sonini to'ldirmasin
    ("collect_ignore modulni o'chirdi, ayni nomli katalog bor",
     {"conftest.py": "collect_ignore = ['test_a.py']\n",
      "test_a/test_b.py": "def test_b1():\n    pass\n\ndef test_b2():\n    pass\n\n"
                          "def test_b3():\n    pass\n"},
     "tests/test_a.py::test_1"),
])
def test_HAQIQIY_pytest_YASHIL_tugaydi_lekin_darvoza_QIZIL(tmp_path, kind, extra, must):
    """Salbiy nazorat (Phase 4A.1 #2): pytest'ning o'zi 0 qaytaradi — exit kodiga tayangan
    CI YASHIL bo'lardi. Darvoza esa sessiya to'liq bajarilmaganini ANIQ id bilan ko'rsatishi
    SHART (parametr ortiqchasi umumiy sonni to'ldirgan holda ham)."""
    files = {**_PARAM, "test_a.py": "def test_1():\n    pass\n\ndef test_2():\n    pass\n",
             **extra, **_Z}
    r, tests, junit, _log = _real_pytest(tmp_path, files)
    assert r.returncode == 0, f"{kind}: pytest yashil tugamadi — nazorat ma'nosiz\n{r.stdout[-800:]}"
    problems, report = V.verify(junit, tests, None)
    assert any(must in p for p in problems), f"{kind}: {problems} {report}"


def test_HAQIQIY_toliq_pytest_sessiyasi_ISBOTLANADI(tmp_path):
    r, tests, junit, log = _real_pytest(tmp_path, {
        **_PARAM, "test_z.py": "class TestZ:\n    def test_2(self):\n        pass\n",
        "sub/test_s.py": "def test_s1():\n    pass\n"})
    assert r.returncode == 0, r.stdout[-800:]
    problems, report = V.verify(junit, tests, None, log)
    assert problems == [], (problems, report)
