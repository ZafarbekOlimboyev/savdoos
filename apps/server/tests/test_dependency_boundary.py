# -*- coding: utf-8 -*-
"""TOOLING va PRODUCTION RUNTIME dependency chegarasi (Phase 4A.1).

⚠️  NEGA. CI backend job 2026-09-11 dan beri BIRORTA test ishlatmagan edi:
    `tests/test_import_1c.py` `tools/import_1c.py` ni yuklaydi, u esa pandas yo'q
    bo'lsa import paytida `sys.exit` qiladi. Tuzatish pandas'ni CI'ga o'rnatadi —
    lekin FAQAT alohida `import1c` extra orqali. Bu fayl pandas va boshqa tooling
    paketlari production runtime'ga (`[project].dependencies`, Dockerfile, Railway,
    infra) HECH QACHON o'tib ketmasligini matn darajasida mahkamlaydi.

⚠️  MATN TEKSHIRUVI YETARLI EMAS (review): `pip --no-cache-dir install`, `pip3.12` yoki
    tranzitiv dependency ham paket olib kirishi mumkin. Shu bois CI'da alohida
    `prod-install-boundary` job'i Dockerfile'dagidek toza venv'ga `pip install .` qiladi
    va O'RNATILGAN paketlar ro'yxatini tekshiradi. Bu fayl — tez, mahalliy birinchi qatlam.

Production yo'li: Railway `builder=DOCKERFILE` -> `pip install -e .` (extras'siz) ->
`sh start.sh`. `requirements.txt` bu yo'lda ISHLATILMAYDI, lekin builder almashtirilsa
u o'rnatish ro'yxatiga aylanadi — shuning uchun u ham tekshiriladi.

Bazaga ulanmaydi (`client` fixture'i yo'q): umumiy sessiya bazasiga tegmaydi.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

SERVER = pathlib.Path(__file__).resolve().parents[1]
ROOT = SERVER.parents[1]

# Production image'ga TUSHMASLIGI shart bo'lgan paketlar (PEP 503 nomi).
_TOOLING = frozenset({"pandas", "numpy", "xlrd", "openpyxl", "lxml", "beautifulsoup4",
                      "html5lib", "pgserver", "pytest", "ruff"})
# Ilova import qilganda xotiraga YUKLANMASLIGI shart bo'lgan modullar.
_TOOLING_MODULES = ("pandas", "numpy", "xlrd", "openpyxl", "lxml", "bs4", "html5lib",
                    "pgserver", "pytest")
# `pip`, `pip3`, `pip3.12`, `python -m pip`, `uv pip` — opsiyalar `install` dan oldin ham bo'lishi mumkin.
_PIP_INSTALL = re.compile(r"\bpip[\d.]*\b[^\n&;|]*?\binstall\b([^\n&;|]*)")
_OTHER_INSTALLERS = re.compile(r"\b(?:poetry\s+add|conda\s+install|mamba\s+install|pipx\s+install|"
                               r"apt(?:-get)?\s+install[^\n]*python3-(?:pandas|numpy|openpyxl|xlrd))\b")


def _name(req: str) -> str:
    """Talab satridan normallashtirilgan paket nomi (extras/marker/versiya tashlanadi)."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    assert m, f"talab satri tanilmadi: {req!r}"
    return re.sub(r"[-_.]+", "-", m.group(1)).lower()


def _pyproject() -> dict:
    with open(SERVER / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _deploy_files() -> list[pathlib.Path]:
    files = [SERVER / f for f in ("start.sh", "Procfile", "railway.json")]
    files += sorted((ROOT / "infra").glob("*.yml")) + sorted((ROOT / "infra").glob("*.yaml"))
    return [f for f in files if f.exists()]


def test_RUNTIME_dependencies_da_TOOLING_paketi_YOQ():
    deps = {_name(d) for d in _pyproject()["project"]["dependencies"]}
    bad = sorted(deps & _TOOLING)
    assert not bad, (f"production runtime'ga tooling paketi tushdi: {bad} — "
                     "[project.optional-dependencies] ga ko'chiring")


def test_import1c_extra_ALOHIDA_va_dev_ga_ARALASHMAGAN():
    opt = _pyproject()["project"]["optional-dependencies"]
    assert {"pandas", "xlrd", "openpyxl"} <= {_name(d) for d in opt["import1c"]}
    leaked = {_name(d) for d in opt["dev"]} & {"pandas", "numpy", "xlrd", "openpyxl"}
    assert not leaked, (f"`dev` extra'ga Excel tooling qo'shildi: {sorted(leaked)} — bitta "
                        "noto'g'ri `pip install -e .[dev]` uni production'ga olib kirardi")


def test_requirements_txt_da_TOOLING_paketi_va_extras_YOQ():
    for p in sorted(SERVER.glob("requirements*.txt")):
        names = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.split("#", 1)[0].strip()
            if not s:
                continue
            assert not s.startswith(("-r", "--requirement", "-c", "--constraint", "-e")), (p.name, s)
            assert ".[" not in s, (p.name, s)
            names.add(_name(s))
        assert not names & _TOOLING, (p.name, sorted(names & _TOOLING))


def test_Dockerfile_FAQAT_asosiy_paketni_ORNATADI():
    txt = (SERVER / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    installs = _PIP_INSTALL.findall(txt)
    assert installs, "Dockerfile'da `pip install` topilmadi — sinov hech narsani o'lchamaydi"
    seen_base = False
    for chunk in installs:
        toks = chunk.split()
        assert not any(t in ("-r", "--requirement", "-c", "--constraint")
                       or t.startswith(("--requirement=", "--constraint=")) for t in toks), chunk
        assert not any("[" in t for t in toks), f"Dockerfile extras o'rnatmoqda: {chunk}"
        for t in toks:
            if t.startswith("-"):
                continue
            assert t in (".", "pip"), f"Dockerfile kutilmagan paket o'rnatmoqda: {t!r} ({chunk})"
            seen_base |= t == "."
    assert seen_base, "Dockerfile ilova paketini (`.`) o'rnatmayapti"
    assert not _OTHER_INSTALLERS.search(txt), "Dockerfile boshqa paket menejeri bilan o'rnatmoqda"


def test_PIP_regexi_opsiyali_va_versiyali_shakllarni_USHLAYDI():
    """review: `pip3?\\s+install` `pip --no-cache-dir install` va `pip3.12 install` ni o'tkazib yuborardi."""
    for cmd in ("pip --no-cache-dir install pandas", "pip3.12 install pandas",
                "python -m pip -q install pandas", "uv pip install pandas", "pip install pandas"):
        found = _PIP_INSTALL.findall(cmd)
        assert found and "pandas" in found[0], cmd


def test_ishga_tushirish_va_infra_fayllarida_PAKET_ORNATISH_YOQ():
    checked = _deploy_files()
    assert len(checked) >= 3, [f.name for f in checked]
    for f in checked:
        body = f.read_text(encoding="utf-8")
        assert not _PIP_INSTALL.search(body), f"{f.name} ishga tushishda paket o'rnatmoqda"
        assert not _OTHER_INSTALLERS.search(body), f"{f.name} paket menejeri chaqirmoqda"


def test_Railway_DOCKERFILE_bilan_quradi():
    """Builder Nixpacks/Railpack'ga almashsa `requirements.txt` va Procfile jonli o'rnatish
    yo'liga aylanadi va yuqoridagi Dockerfile sinovi chetlab o'tiladi."""
    cfg = json.loads((SERVER / "railway.json").read_text(encoding="utf-8"))
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert cfg["build"]["dockerfilePath"] == "Dockerfile"
    assert cfg["deploy"]["startCommand"] == "sh start.sh"


def test_tooling_extra_lari_DEPLOY_fayllarida_TILGA_OLINMAYDI():
    extras = _pyproject()["project"]["optional-dependencies"]
    files = [SERVER / "Dockerfile"] + _deploy_files()
    for f in files:
        body = f.read_text(encoding="utf-8")
        for extra in extras:
            assert not re.search(r"\[\s*(?:[\w-]+\s*,\s*)*" + re.escape(extra) + r"\s*[\],]", body), \
                f"deploy fayli `{f.name}` `{extra}` extra'sini o'rnatmoqda"


_BOUNDARY_PROBE = r'''
import importlib, pkgutil, sys
BLOCK = set(sys.argv[1].split(","))
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ModuleNotFoundError("tooling paketi bloklandi: " + name)
        return None
sys.meta_path.insert(0, _Block())
import app, app.main, app.initdb, app.seed
n = 0
for mi in pkgutil.walk_packages(app.__path__, "app."):
    importlib.import_module(mi.name)
    n += 1
leaked = sorted(k for k in sys.modules if k.split(".")[0] in BLOCK)
assert not leaked, leaked
print("BOUNDARY-OK", n)
'''


def test_ilova_TOOLING_paketlarisiz_TOLIQ_import_qilinadi(tmp_path):
    """Statik sinovlar ko'rmaydigan narsa: funksiya ichidagi import. Alohida jarayon —
    pytest jarayonida pytest (va ehtimol pandas) allaqachon yuklangan."""
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path / 'b.db'}", APP_ENV="dev",
               VENDOR_ADMIN_KEY="x", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-c", _BOUNDARY_PROBE, ",".join(_TOOLING_MODULES)],
                       cwd=SERVER, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "BOUNDARY-OK" in r.stdout, (r.stdout + r.stderr)[-3000:]
    assert int(r.stdout.split("BOUNDARY-OK", 1)[1].split()[0]) > 50, r.stdout
