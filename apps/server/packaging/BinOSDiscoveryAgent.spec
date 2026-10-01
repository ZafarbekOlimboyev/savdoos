# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spetsifikatsiyasi — `BinOSDiscoveryAgent`.

⚠️ YIG'MA ICHIGA NIMA KIRADI (brief §4): faqat agentga KERAK bo'lgan narsa —
   `app.services.discovery_agent`, `app.services.discovery_1c` (Phase 3/4 yadrosi),
   `app.services.migrator_1c.bundle` (TO'RT yordamchi: `BundleError`, `parse_ts`,
   `sha256_bytes`, `strict_json_loads`) va `tkinter`.

⚠️ MIGRATOR APPLY YIG'MAGA KIRMAYDI va bu TASODIF EMAS: `migrator_1c/__init__.py` da
   BIRORTA import yo'q (37 satr, 0 import), shu bois `apply.py` tranzitiv tortilmaydi.
   Qo'shimcha to'siq sifatida u `excludes` ga ANIQ yozilgan — ya'ni kelajakda
   `__init__.py` ga import qo'shilsa ham yig'ma uni olib kirmaydi.

⚠️ `excludes` RO'YXATI HIMOYA, OPTIMIZATSIYA EMAS: testlar, pytest, server freymvorki,
   ma'lumotlar bazasi haydovchilari va PYTHON tarmoq kutubxonalari yig'maga TUSHMASLIGI
   kerak. Agent offline va faqat-o'qish; bu modullar unga kerak emas va ularning mavjudligi
   xavfsizlik yuzasini kengaytirardi.
   ⚠️⚠️ ANIQLASHTIRISH (ko'rik topdi, da'vo HADDAN OSHGAN edi): «tarmoq kutubxonasi yo'q»
        FAQAT Python tomoniga tegishli. Tarqatiladigan papkada Tcl ning IXTIYORIY `http`
        paketi BOR — `_internal/_tcl_data/http1.0/http.tcl` (GET/POST/HEAD) — va u Tk
        bilan BIRGA keladi, uni `excludes` olib tashlamaydi. Nega bu baribir xavf emas:
        agent Tcl kodini BAJARMAYDI (`tk.eval`/`package require` chaqiruvi YO'Q) va
        `tkinter` faqat oyna uchun ishlatiladi. ⚠️ Lekin FAYL YIG'MADA BOR, va buni
        yozmaslik — da'voni yolg'on qilish bo'lardi. Inertligi test bilan qulflangan
        (`tests/test_agent_packaging.py`).
   ⚠️ Bu ro'yxat «kirmasligi kerak» degan NIYAT emas, DARVOZA: yig'ilgandan keyin
      `tests/test_agent_packaging.py` yig'ma ichidagi modul ro'yxatini TEKSHIRADI.

⚠️ `console=True` ATAYLAB: `--headless` rejimi operator skriptlari uchun chiqish kodi va
   matnli xabar beradi; oynasiz yig'mada `stderr` yo'qolib ketardi va `2` kodining sababi
   ko'rinmasdi. Oyna rejimi (`tkinter`) konsol bilan ham ishlaydi.

⚠️ YASHIRIN XULQ YO'Q: avtoyuklanish yo'q, xizmat yo'q, yangilovchi yo'q, rejalashtirilgan
   vazifa yo'q. Yig'ma faqat operator ishga tushirganda ishlaydi va chiqadi.
   ⚠️ ANIQLASHTIRISH: `runtime_hooks=[]` — BIZ hook qo'shmaymiz. Lekin PyInstaller O'ZI
      ikki standart hook qo'shadi (`pyi_rth__tkinter`, `pyi_rth_inspect`) — ular
      kutubxonani ishga tayyorlaydi, bizning xulqimiz emas. «Hook umuman yo'q» deyish
      yig'ma tarkibiga zid bo'lardi.
"""

import pathlib

# ⚠️ `SPECPATH` — PyInstaller beradigan o'zgaruvchi (spec faylining papkasi). Ishlab
#    chiquvchining MUTLAQ yo'li bu yerda YOZILMAYDI: aks holda yig'ma faqat bitta
#    mashinada qurilardi (brief §8: hardcoded developer path bo'lmasin).
SERVER_DIR = str(pathlib.Path(SPECPATH).parent)      # noqa: F821 - PyInstaller beradi
ENTRY = str(pathlib.Path(SPECPATH) / "binos_agent_entry.py")   # noqa: F821

HIDDEN = [
    # tkinter himoyalangan `import` ichida (muhit tkinter'siz bo'lsa modul import
    # qilinishi kerak), shu bois statik tahlil uni O'TKAZIB YUBORISHI mumkin.
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
]

EXCLUDES = [
    # ── Migrator APPLY va uning qo'shnilari (bundle.py DAN BOSHQA hammasi) ──────────
    "app.services.migrator_1c.apply",
    "app.services.migrator_1c.actor",
    "app.services.migrator_1c.catalog",
    "app.services.migrator_1c.classify",
    "app.services.migrator_1c.freshness",
    "app.services.migrator_1c.guard",
    "app.services.migrator_1c.mapping",
    "app.services.migrator_1c.normalize",
    # ── Testlar va sinov vositalari ────────────────────────────────────────────────
    "pytest", "_pytest", "pluggy", "py", "hypothesis", "coverage",
    # ── Server freymvorki va DB (agent ularni ishlatmaydi) ─────────────────────────
    "fastapi", "starlette", "uvicorn", "pydantic", "sqlalchemy", "alembic",
    "psycopg", "psycopg2", "asyncpg", "sqlite3",
    # ── Tarmoq / mijoz kutubxonalari: agent OFFLINE ────────────────────────────────
    "requests", "httpx", "urllib3", "aiohttp", "smtplib", "ftplib",
    # ── Og'ir ilmiy to'plam (tasodifan tortilmasin) ────────────────────────────────
    "numpy", "pandas", "scipy", "matplotlib", "PIL", "lxml",
    # ── Ishlab chiquvchi vositalari ────────────────────────────────────────────────
    "IPython", "setuptools", "pip", "wheel", "pkg_resources",
]

a = Analysis(                      # noqa: F821
    [ENTRY],
    pathex=[SERVER_DIR],
    binaries=[],
    datas=[],                      # ⚠️ runtime'da fayl o'qilmaydi: hujjat/shablon YO'Q
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],              # ⚠️ BO'SH: yashirin boshlang'ich xulq yo'q
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)                  # noqa: F821

exe = EXE(                         # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,         # ⚠️ ONE-DIR: binarlar papkada qoladi
    name="BinOSDiscoveryAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # ⚠️ UPX YO'Q: antivirus uchun qo'shimcha shubha manbai
    console=True,
    disable_windowed_traceback=True,   # ⚠️ operatorga traceback oynasi CHIQMAYDI
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(                    # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BinOSDiscoveryAgent",
)
