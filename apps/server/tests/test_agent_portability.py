# -*- coding: utf-8 -*-
"""PORTATIVLIK DARVOZASI — yig'ilgan `BinOSDiscoveryAgent.exe` ni HAQIQATAN yurgizadi (§8, §9).

⚠️⚠️ BU FAYL `test_agent_packaging.py` DAN NIMASI BILAN FARQ QILADI: u yerda yig'ma
     FAYLLARI o'qiladi (EXE ISHGA TUSHIRILMAYDI), bu yerda esa EXE `subprocess` bilan
     ROSTDAN yuritiladi va uning NATIJASI o'lchanadi. Ya'ni bu fayl «yig'ma ichida nima
     bor» emas, «yig'ma BOSHQA joyda, BOSHQA muhitda ham ishlaydimi» savoliga javob beradi.

⚠️⚠️ NIMA ISBOTLANMAYDI (eng muhim ogohlantirish):
     1. Bu yerda HAQIQIY 1C YO'Q. Agent 1C ni topmaydi (`presence_verdict == "absent"`) va
        `watch_folder` yo'lida yig'uvchi chiqishini kutib `FAILED_TIMEOUT` bilan to'xtaydi.
        O'lchanadigan narsa — AGENTNING O'ZI yurdimi va natija paketini yozdimi. 1C
        integratsiyasi HAMON `RUNTIME-UNKNOWN`.
     2. Bu TOZA MASHINA isboti EMAS. Ikkinchi Windows mashinasi (yoki VM) YO'Q. §9 testlari
        BIR XIL mashinada muhit o'zgaruvchilarini KESIB o'tkaziladi — bu YAQINLASHUV
        (`APPROXIMATED`), isbot emas. «Python o'rnatilmagan mashinada ishlaydi» degan
        xulosa bu fayldan CHIQMAYDI: registr, WinSxS, VC runtime va antivirus holati shu
        mashinaning O'ZIDA qanday bo'lsa shundayligida qoladi.

⚠️ Yig'ma REPO TASHQARISIDA turadi (ildiz `BINOS_AGENT_BUILD_ROOT` dan keladi, standart
   `~/binos-agent-build`), shu bois CI mashinasida u BO'LMAYDI va bu fayldagi yurish
   testlari ANIQ SABAB bilan `skip` bo'ladi. Hujjat testi (§C) va darvozaning O'Z o'lchovi
   (§0) yig'masiz ham ishlaydi — ular repo faylini va qaror jadvalini o'qiydi.

⚠️⚠️ UCHINCHI DARVOZA, AYNI TESHIK (2026-10-02 da tuzatildi): bu fayl ilgari (a) yig'ma
     ildizini QO'LDA `C:/Users/Developer/binos-agent-build` deb yozardi — ya'ni
     `BINOS_AGENT_BUILD_ROOT` ni UMUMAN o'qimasdi va boshqa ikki darvoza bilan jimgina
     BOSHQA yig'mani tekshirishi mumkin edi; (b) `.exe` yo'q bo'lsa SHARTSIZ `skip`
     berardi — platformaga bog'liq EMAS va YANGILIK tekshiruvi YO'Q; (c) skip'lari
     `tests/ci_expected_skips.txt` da UMUMAN YO'Q edi, ya'ni HAQIQIY Linux CI'da 18 ta
     «KUTILMAGAN skip» backend job'ni QIZIL qilardi. Uchinchisining amaliy oqibati:
     ESKIRGAN `.exe` shu yerda ham «portativ» deb tasdiqlanardi — o'lchangan holat
     `21 passed` (yig'ma uch moduldan eskirgan, qarang `packaging/BUILD_GATE.md` §2).
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pytest
import textwrap

# ── Yig'ma joylashuvi (`test_agent_packaging.py` va harness bilan AYNI manzil) ──────────
#: ⚠️⚠️ ILDIZ QO'LDA YOZILMAYDI. U AYNI muhit o'zgaruvchisidan keladi va UCH modulning
#:      (parity · packaging · portability) tengligi `test_agent_parity.py` dagi
#:      `test_A_yigma_ILDIZI_UCH_modulda_AYNI` bilan QULFLANGAN. Qotirilgan mutlaq yo'l
#:      spec faylining O'Z qoidasiga («hardcoded developer path bo'lmasin») zid edi.
_YIGMA_ILDIZ = pathlib.Path(os.environ.get("BINOS_AGENT_BUILD_ROOT")
                            or pathlib.Path.home() / "binos-agent-build")
_DIST = _YIGMA_ILDIZ / "dist-onedir" / "BinOSDiscoveryAgent"
_EXE = _DIST / "BinOSDiscoveryAgent.exe"

#: `apps/server` va worktree ildizi — «repoga yozilmadi» tekshiruvi uchun.
_SERVER = pathlib.Path(__file__).resolve().parents[1]
_WORKTREE = _SERVER.parents[1]
_DOC = _WORKTREE / "integrations" / "1c" / "AGENT_PORTABLE_BUILD.md"

#: Natija papkasining ILDIZ artefaktlari — `watch_folder` yo'li TIMEOUT bilan tugaganda
#: AYNAN beshtasi yoziladi (`bundle/` yo'q, chunki yig'uvchi chiqishi kelmagan).
_ILDIZ_ARTEFAKT = frozenset({
    "agent_manifest.json", "agent_status.json", "discovery_report.md",
    "environment.json", "errors.json",
})

#: Takrorlanadigan yurish uchun qotirilgan vaqt belgisi (soat o'qilmaydi).
_TS = "20261002T000000Z"


# ══════════════════════════════════════════════════════════════════════════════════════════
# ESKIRGAN YIG'MA DARVOZASI — bu modul uchun ham MAJBURIY
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ O'LCHANGAN TESHIK (shu worktree'da): mahalliy `.exe` uch moduldan eskirgan edi
#      (`discovery_1c/redact.py`, `discovery_agent/detector.py`,
#      `discovery_agent/launcher.py`) — `test_agent_parity.py` BALAND yiqildi va uchtasini
#      NOMLADI, bu modul esa `21 passed` berdi. Ya'ni PORTATIVLIK darvozasi ESKIRGAN
#      artefaktni «portativ» deb TASDIQLADI.
#
# ⚠️ NEGA BU MODULGA HAM SHART: bu yerdagi HAR BIR da'vo JORIY manba haqidagi da'vo bo'lib
#    o'qiladi — «yig'ma bo'sh papkadan yuradi», «joriy papkadagi soxta `app` paketini
#    IMPORT QILMAYDI», «yig'mada BU MASHINA yo'li YO'Q», «hujjatdagi xesh haqiqiy yig'maga
#    MOS». Eskirgan artefaktda bu da'volar YOLG'ON yashil bo'ladi: manbaga BUGUN kiritilgan
#    regressiya (masalan `launcher.py` ning joriy papkaga yozib qo'yishi) ESKI `.exe` da
#    umuman BAJARILMAYDI. Hujjat testi esa undan ham yomoni: xesh MOS kelsa, hujjat
#    ESKIRGAN yig'mani «tarqatiladigan» deb tasdiqlagan bo'lardi.
#
# ⚠️ Darvoza QAYTA YOZILMAYDI: hukm `packaging/parity_harness.yigma_tayyorligi()` dan
#    OLINADI (OWNER B) — AYNI harness, AYNI qaror jadvali. Ikkinchi nusxa bir kun ajralib
#    ketardi va uch darvoza jimgina BOSHQA javob berardi.
_HARNESS_YOLI = _SERVER / "packaging" / "parity_harness.py"

#: ⚠️ `test_agent_parity.py` va `test_agent_packaging.py` harnessni AYNI shu nom bilan
#:    `sys.modules` ga qo'yadi — mavjud nusxa QAYTA ISHLATILADI. Aks holda bir yurishda
#:    UCHINCHI modul nusxasi paydo bo'lardi va unga qo'yilgan o'lchov (masalan muhit
#:    taqlidi) boshqalarga ta'sir qilmasdi.
_HARNESS_MODUL_NOMI = "binos_parity_harness"


def _harness():
    """OWNER B darvozasi — YO'L bilan va KECHIKTIRILGAN holda yuklanadi.

    ⚠️⚠️ `from packaging.parity_harness import ...` ISHLAMAYDI: `packaging` nomi PyPI
         paketi bilan to'qnashadi (oddiy paket nom bo'shliqli paketdan USTUN turadi).
         `test_agent_parity.py` dagi `_harnessni_yukla()` bilan AYNI usul.
    ⚠️ KECHIKTIRILGAN (import paytida emas, darvoza chaqirilganda): shu paytgacha
       `sys.modules` dagi nusxa allaqachon paydo bo'lgan bo'ladi.
    """
    modul = sys.modules.get(_HARNESS_MODUL_NOMI)
    if modul is not None:
        return modul
    spec = importlib.util.spec_from_file_location(_HARNESS_MODUL_NOMI, _HARNESS_YOLI)
    assert spec is not None and spec.loader is not None, \
        f"parity harnessi yuklanmadi: {_HARNESS_YOLI}"
    modul = importlib.util.module_from_spec(spec)
    # ⚠️ `sys.modules` ga EXEC'DAN OLDIN: `@dataclass` sinfning modulini `sys.modules`
    #    dan izlaydi (yo'l bilan yuklashning ma'lum talabi, hiyla emas).
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


#: Darvoza qarorlari — `pytest` chaqiruvi QARORDAN AJRATILGAN, shunda qaror jadvalini
#: `.exe` bo'lmagan platformada ham (ya'ni Linux CI'da) test bilan o'lchash mumkin.
_QAROR_YIQIL, _QAROR_SKIP = "YIQIL", "SKIP"

#: ⚠️⚠️ SABAB MATNI BOSHQA IKKI DARVOZADAN ATAYLAB FARQ QILADI
#:      (`MUHIT: Windows EXE Linux CI'da QURILMAYDI` — parity, OWNER B;
#:       `MUHIT: Windows yig'masi Linux CI'da QURILMAYDI` — yig'ma tarkibi).
#:      `verify_pytest_run._matches` sababni `reason in msg` bilan tekshiradi, ya'ni
#:      matnlar bir-birining BO'LAGI bo'lsa, bir darvozaning yozuvi yo'qolganda uning
#:      skip'lari ikkinchisining qatoriga «yashirinib» o'tib ketardi va KUTILMAGAN skip
#:      QIZIL bermasdi. Shu bois uchinchisi O'Z matnini ishlatadi.
#: ⚠️ Matn SEMANTIK jihatdan ham boshqa: bu modul `.exe` ni ROSTDAN yurgizadi, demak
#:    Linux'dagi cheklov faqat «qurilmaydi» emas — yig'ma BO'LGANDA ham Linux uni
#:    YURGIZA OLMAYDI (PE ikkiligi, Wine ishlatilmaydi).
_MUHIT_SABABI = "MUHIT: Windows EXE'ni Linux CI YURGIZA OLMAYDI"


def _yoqlik_qarori(*, qurilishi_mumkin: bool) -> tuple[str, str]:
    """`.exe` UMUMAN YO'Q bo'lganda: `(qaror, matn)`.

    ⚠️⚠️ «EXE yo'q bo'lsa skip» SHARTSIZ EMAS va bu ataylab: yig'ma QURILISHI mumkin
         bo'lgan platformada (Windows) yo'qligi OPERATORNING ishi, muhit cheklovi EMAS —
         u yerda portativlik O'LCHANMAGANI SKIP bo'lib ko'rinmasligi kerak. Ilgari bu
         modulda shartsiz `skip` turardi, ya'ni Windows reliz darvozasida yig'ma
         topilmasa «hammasi o'tdi» ko'rinishi mumkin edi.
    ⚠️ Skip matni `_MUHIT_SABABI` bilan BOSHLANADI — `tests/ci_expected_skips.txt` dagi
       sabab bo'lagi AYNAN shu satr (o'zgartirilsa ro'yxat ham yangilanadi).
    """
    if qurilishi_mumkin:
        return _QAROR_YIQIL, (
            f"PORTATIVLIK O'LCHANMADI: {_EXE} topilmadi, LEKIN bu platformada "
            f"(`{sys.platform}`) yig'ma QURILADI va YURADI — ya'ni yo'qligi MUHIT "
            f"cheklovi EMAS va skip bo'lib o'tib ketishi TAQIQLANGAN. Reliz darvozasi "
            f"(`packaging/BUILD_GATE.md`) bo'yicha yig'ing, build papkasini SAQLAB "
            f"(`--workpath`), so'ng shu modulni qayta yurgizing.")
    return _QAROR_SKIP, (
        f"{_MUHIT_SABABI}. Yig'ma YO'Q: {_EXE} topilmadi. Yig'ma repo tashqarisida "
        f"quriladi (`pyinstaller packaging/BinOSDiscoveryAgent.spec`), PyInstaller "
        f"kross-kompilyatsiya QILMAYDI va Linux backend job'i Windows PE ikkiligini "
        f"BAJARA OLMAYDI (Wine ishlatilmaydi), shu bois bu MUHIT cheklovi. Portativlik "
        f"YURISH bilan shu yurishda tekshirilmadi; darvozaning QAROR JADVALI shu yurishda "
        f"o'lchandi (`::test_darvoza_ESKIRGAN_yigmani_PORTATIV_deb_tasdiqlamaydi`), "
        f"hujjat halolligi `::test_hujjat*` da, yurishning o'zi esa Windows reliz "
        f"darvozasida (`packaging/BUILD_GATE.md`).")


def _yangilik_qarori(holat: str, sabab: str, *, toza: str) -> str | None:
    """`None` — yig'ma JORIY manbadan qurilgani ISBOTLANDI; aks holda YIQILISH matni.

    ⚠️⚠️ FAIL-CLOSED va PLATFORMAGA BOG'LIQ EMAS: `toza` dan BOSHQA HAR holat
         (`ESKIRGAN`, `ISBOTSIZ`, va hatto `YO_Q` — harness BOSHQA `.exe` yo'liga
         qarasa, `BINOS_AGENT_EXE`) YIQILISH beradi. JIM SKIP YO'Q: eskirgan yig'ma
         «portativ» deb tasdiqlanishining yo'li aynan shu edi.
    ⚠️ `sabab` harnessdan KELGANIDEK uzatiladi — nomos modullar ro'yxati va tuzatish
       yo'li o'sha matnda.
    """
    if holat == toza:
        return None
    return (f"PORTATIVLIK DARVOZASI O'LCHANMADI (holat: {holat}) — yurgiziladigan yig'ma "
            f"JORIY manbadan qurilgani ISBOTLANMADI. Shu moduldagi «boshqa joydan ham "
            f"yuradi / repoga yozmaydi / soxta `app` ni import qilmaydi» da'volari ESKI "
            f"artefakt haqida bo'lardi va manbaga BUGUN kiritilgan regressiya umuman "
            f"BAJARILMASDI (yolg'on kafolat); hujjatdagi xesh esa ESKIRGAN yig'mani "
            f"«tarqatiladigan» deb tasdiqlardi. {sabab}")


def _dist_talab() -> None:
    """Yig'ma BOR va JORIY manbadan qurilgani ISBOTLANGAN bo'lsin.

    ⚠️ `_EXE.exists()` AVVAL o'lchanadi — shu modulning O'Z yo'li bilan: harness
       `BINOS_AGENT_EXE` bilan boshqa `.exe` ga yo'naltirilgan bo'lsa, darvozalar
       BOSHQA artefaktni tekshirardi. Bunday ziddiyat `_yangilik_qarori()` da `YO_Q`
       bo'lib YIQILADI (jimgina o'tmaydi).
    """
    PH = _harness()
    if not _EXE.exists():
        qaror, matn = _yoqlik_qarori(qurilishi_mumkin=PH.exe_qurish_mumkinmi())
        if qaror == _QAROR_YIQIL:
            pytest.fail(matn)
        pytest.skip(matn)
    holat, sabab = PH.yigma_tayyorligi()
    matn = _yangilik_qarori(holat, sabab, toza=PH.HOLAT_TOZA)
    if matn is not None:
        pytest.fail(matn)


# ── Muhitni KESISH (§9 yaqinlashuvi) ───────────────────────────────────────────────────
#: ⚠️ Bu ro'yxatda Python'ga aloqador BIRORTA o'zgaruvchi YO'Q va bu ATAYLAB: `PYTHONPATH`,
#   `PYTHONHOME`, `VIRTUAL_ENV`, `PYTHONSTARTUP` berilmaydi. Ya'ni yig'ma bo'lishilgan
#   `.venv` ga ham, manba daraxtiga ham TAYANMAYDI.
#: ⚠️ `PATH` da FAQAT `System32` qoladi: «`python` PATH da bo'lmasa ham ishlaydi» talabi
#   aynan shu bilan o'lchanadi. Windows yuklovchisi uchun `SystemRoot` SHART — usiz jarayon
#   umuman boshlanmaydi va test muhit haqida emas, o'zi haqida yiqilardi.
_PYTHON_OZGARUVCHILARI = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
                          "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONUSERBASE")


def _kesilgan_muhit() -> dict[str, str]:
    """`PATH` faqat `System32`, Python o'zgaruvchilari UMUMAN yo'q."""
    tizim = os.environ.get("SystemRoot", r"C:\Windows")
    muhit = {
        "SystemRoot": tizim,
        "windir": tizim,
        "PATH": str(pathlib.Path(tizim) / "System32"),
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "TEMP": tempfile.gettempdir(),
        "TMP": tempfile.gettempdir(),
        "NUMBER_OF_PROCESSORS": os.environ.get("NUMBER_OF_PROCESSORS", "1"),
        "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64"),
        # ⚠️ Quyidagi uchtasi 1C ni ANIQLASH uchun o'qiladi (fayl tizimi manbalari), shu
        #    bois ularni olib tashlash muhitni kesish emas, aniqlovchini KO'R qilish bo'lardi.
        "USERPROFILE": os.environ.get("USERPROFILE", r"C:\Users"),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", r"C:\Users"),
        "APPDATA": os.environ.get("APPDATA", r"C:\Users"),
        "PROGRAMFILES": os.environ.get("PROGRAMFILES", r"C:\Program Files"),
    }
    assert not set(muhit) & set(_PYTHON_OZGARUVCHILARI), \
        "kesilgan muhitga Python o'zgaruvchisi tushib qolgan — test o'z shartini buzadi"
    return muhit


# ── Yurgizgich ─────────────────────────────────────────────────────────────────────────
class _Yurish:
    """Bitta yurishning natijasi — testlar o'qiydigan yagona shakl."""

    def __init__(self, p: subprocess.CompletedProcess, natija: pathlib.Path) -> None:
        self.kod = p.returncode
        self.chiqish = p.stdout.decode("utf-8", "replace")
        self.xato = p.stderr.decode("utf-8", "replace")
        self.natija_ildizi = natija

    @property
    def hammasi(self) -> str:
        return self.chiqish + self.xato

    @property
    def paket(self) -> pathlib.Path:
        """Natija ildizidagi YAGONA `binos-discovery-*` papkasi."""
        papkalar = sorted(q for q in self.natija_ildizi.iterdir() if q.is_dir())
        assert len(papkalar) == 1, (
            f"natija ildizida AYNAN bitta paket papkasi bo'lishi kerak, topildi: "
            f"{[q.name for q in papkalar]}\nchiqish:\n{self.hammasi}")
        return papkalar[0]

    def status(self) -> dict:
        return json.loads((self.paket / "agent_status.json").read_text(encoding="utf-8"))

    def muhit(self) -> dict:
        return json.loads((self.paket / "environment.json").read_text(encoding="utf-8"))


def _yurgiz(exe: pathlib.Path, *, cwd: pathlib.Path, kuzat: pathlib.Path,
            natija: pathlib.Path | None, muhit: dict[str, str] | None = None,
            qoshimcha: tuple[str, ...] = ()) -> _Yurish:
    """EXE ni `--headless` rejimida yurgizadi.

    ⚠️ `natija=None` — `--result-dir` UMUMAN berilmaydi: standart xulq (joriy papka)
       tekshiriladi.
    """
    buyruq = [str(exe), "--headless", str(kuzat), "--wait-seconds", "1", "--timestamp", _TS]
    if natija is not None:
        buyruq += ["--result-dir", str(natija)]
    buyruq += list(qoshimcha)
    p = subprocess.run(buyruq, cwd=str(cwd), env=muhit, capture_output=True, timeout=300)
    return _Yurish(p, natija if natija is not None else cwd)


def _joy(tmp: pathlib.Path, nom: str) -> tuple[pathlib.Path, pathlib.Path]:
    """Kuzatiladigan (BO'SH) papka va natija papkasi — har yurish uchun yangi."""
    kuzat = tmp / nom / "kuzat"
    natija = tmp / nom / "natija"
    kuzat.mkdir(parents=True)
    natija.mkdir(parents=True)
    return kuzat, natija


def _yurish_sogdir(y: _Yurish) -> None:
    """HAR BIR joydan yurishda bir xil bo'lishi SHART bo'lgan tekshiruvlar.

    ⚠️ Kutilgan chiqish kodi `1`, `0` EMAS: 1C bu mashinada yo'q, shu bois yurish
       `FAILED_TIMEOUT` bilan tugaydi. `1` — «yurish yiqildi, lekin bu ham JAVOB va natija
       papkasi SAQLANDI». `2` bo'lsa — yurgizib bo'lmagan, ya'ni portativlik BUZILGAN.
    """
    assert y.kod == 1, (
        f"kutilgan chiqish kodi 1 (FAILED_TIMEOUT), olingan {y.kod}.\n"
        f"⚠️ 2 = YURGIZIB BO'LMADI — portativlik buzilgan.\n{y.hammasi}")
    assert "Traceback" not in y.hammasi, \
        f"operatorga PYTHON TRACEBACK chiqdi:\n{y.hammasi}"
    assert "ModuleNotFoundError" not in y.hammasi, \
        f"yig'mada modul topilmadi — yig'ma to'liq emas:\n{y.hammasi}"
    assert "UnicodeEncodeError" not in y.hammasi, \
        f"chop etish kodlashi yiqildi (regressiya):\n{y.hammasi}"
    assert set(q.name for q in y.paket.iterdir()) == set(_ILDIZ_ARTEFAKT), (
        f"ildiz artefaktlari kutilganidan farq qiladi: "
        f"{sorted(q.name for q in y.paket.iterdir())}")
    st = y.status()
    assert st["state"] == "FAILED_TIMEOUT", st["state"]
    # ⚠️ `terminal` va `read_only` sxemada MATN (`"true"`), mantiqiy qiymat EMAS — bu
    #    `status.py` dagi ataylab qilingan tanlov (`READ_ONLY` konstantasi), shu bois test
    #    ham MATN bilan solishtiradi.
    assert st["terminal"] == "true", st["terminal"]
    assert st["read_only"] == "true", "agent FAQAT-O'QISH da'vosini yo'qotdi"
    assert y.muhit()["presence_verdict"] == "absent", y.muhit()["presence_verdict"]


# ═══ 0. DARVOZANING O'ZI: eskirgan yig'ma JIMGINA «portativ» bo'lolmaydi ════════════════
def _chaqirilgan_nomlar(fn) -> set[str]:
    """`fn` TANASIDA ROSTDAN chaqirilgan nomlar (docstring va izoh HISOBGA OLINMAYDI).

    ⚠️⚠️ NEGA MATN QIDIRUVI YETMAYDI — O'LCHANGAN MUTATSIYA: darvoza simini
         olib tashlab turib `inspect.getsource(...)` ichida nomni IZLASH tekshiruvi YASHIL
         qolardi, chunki `getsource()` DOCSTRINGNI ham qaytaradi va docstring o'sha nomni
         ESLATADI. Ya'ni simlash qo'riqchisining O'ZI o'lik edi. AST esa faqat HAQIQIY
         `Call` tugunlarini ko'radi: izoh ham, docstring ham uni chalg'itmaydi.
    ⚠️ `PH.yigma_tayyorligi()` kabi atribut chaqiruvlari ham qamraladi (`Attribute.attr`).
    """
    daraxt = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    nomlar: set[str] = set()
    for n in ast.walk(daraxt):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name):
            nomlar.add(f.id)
        elif isinstance(f, ast.Attribute):
            nomlar.add(f.attr)
    return nomlar


def test_darvoza_ESKIRGAN_yigmani_PORTATIV_deb_tasdiqlamaydi():
    """⚠️⚠️ UCHINCHI DARVOZADAGI AYNI TESHIK shu testda qadalgan: «eskirgan yig'ma reliz
         validatsiyasidan JIMGINA o'tib ketolmasligi ISBOTLANSIN». Qaror jadvali `.exe`
         DAN MUSTAQIL o'lchanadi, ya'ni bu test Linux CI'da ham BAJARILADI va shu bois
         `ci_expected_skips.txt` da YO'Q.

    O'lchanadigan uch narsa:
      1. `TOZA` — yagona DAVOM etiladigan holat;
      2. `ESKIRGAN` / `ISBOTSIZ` / `YO_Q` — HAMMASI yiqilish matni beradi (`None` EMAS),
         ya'ni jim skip YO'Q va harness sababi (nomos modullar ro'yxati) SAQLANADI;
      3. `.exe` yo'qligi — Windows'da YIQILISH, boshqa platformada RATIFIKATSIYA qilingan
         skip, va skip matni `ci_expected_skips.txt` dagi sabab bo'lagini O'Z ICHIGA
         OLADI.
    ⚠️ To'rtinchisi — SIMLASH: qaror jadvali mavjud bo'lib, `_dist_talab()` uni
       CHAQIRMASA, darvoza qog'ozda qolardi (o'lik gard). Shu bois chaqiruv manbadan
       tekshiriladi.
    ⚠️ Beshinchisi — SABAB MATNINING AJRALGANLIGI: uchinchi darvozaning skip sababi
       boshqa ikkisining BO'LAGI bo'lsa (yoki teskarisi), ro'yxatdan bitta yozuv
       yo'qolganda skip ikkinchisining qatoriga yashirinib o'tib ketardi.
    """
    PH = _harness()
    assert _yangilik_qarori(PH.HOLAT_TOZA, "", toza=PH.HOLAT_TOZA) is None, \
        "`TOZA` holat DAVOM etmadi — darvoza yolg'on qizil beradi"
    for holat in (PH.HOLAT_ESKIRGAN, PH.HOLAT_ISBOTSIZ, PH.HOLAT_YOQ):
        matn = _yangilik_qarori(holat, f"<SABAB:{holat}>", toza=PH.HOLAT_TOZA)
        assert matn is not None, \
            f"`{holat}` holati JIMGINA o'tib ketdi — PORTATIVLIK darvozasi TESHIK"
        assert f"<SABAB:{holat}>" in matn, \
            f"`{holat}` yiqilish matnida harness sababi YO'Q: {matn}"

    assert _yoqlik_qarori(qurilishi_mumkin=True)[0] == _QAROR_YIQIL, \
        "yig'ma QURILADIGAN platformada `.exe` yo'qligi SKIP bo'lib qoldi"
    qaror, matn = _yoqlik_qarori(qurilishi_mumkin=False)
    assert qaror == _QAROR_SKIP, "yig'ma QURILMAYDIGAN platformada MUHIT skip'i yo'qoldi"
    assert _MUHIT_SABABI in matn, \
        f"skip matni `ci_expected_skips.txt` dagi sabab bo'lagini olmaydi: {matn}"

    # ⚠️ SIMLASH AST BILAN o'lchanadi, MATN qidiruvi bilan EMAS: matn qidiruvi
    #    docstringdagi eslatmani «chaqiruv» deb hisoblab, O'LIK qo'riqchiga aylangan edi.
    chaqirilgan = _chaqirilgan_nomlar(_dist_talab)
    for chaqiruv in ("yigma_tayyorligi", "_yangilik_qarori", "_yoqlik_qarori"):
        assert chaqiruv in chaqirilgan, \
            f"`_dist_talab()` `{chaqiruv}` ni CHAQIRMAYDI — darvoza SIMLANMAGAN"

    # ⚠️ Sabab matnlari ARALASHMAYDI: hech biri boshqasining BO'LAGI emas, va bu
    #    moduldagi skip matni boshqa darvozalarning sababini O'Z ICHIGA OLMAYDI.
    from tests import test_agent_packaging as PKG
    begonalar = (PH.MUHIT_SABABI, PKG._MUHIT_SABABI)
    for begona in begonalar:
        assert begona != _MUHIT_SABABI, "uchinchi darvoza sababi BOSHQASI bilan AYNI"
        assert begona not in _MUHIT_SABABI and _MUHIT_SABABI not in begona, \
            (f"skip sabablari bir-birining BO'LAGI: `{_MUHIT_SABABI}` ↔ `{begona}` — "
             f"ro'yxatdan bitta yozuv yo'qolsa skip ikkinchisiga YASHIRINIB o'tardi")
        assert begona not in matn, \
            f"bu modulning skip matni BOSHQA darvozaning sababini o'z ichiga oldi: {begona}"


# ═══ A. §8 — FAYL TIZIMI PORTATIVLIGI (UCH JOYDAN YURISH) ═══════════════════════════════
def test_bosh_temp_papkadan_yuradi(tmp_path: pathlib.Path):
    """1-JOY: BUTUNLAY BO'SH temp papkasi joriy papka bo'lganda.

    ⚠️ Nega muhim: operator `.exe` ni Downloads yoki Desktop'dan yurgizadi — u papkada
       na repo, na `app/` paketi, na konfiguratsiya bo'ladi.
    """
    _dist_talab()
    kuzat, natija = _joy(tmp_path, "bosh")
    ishchi = tmp_path / "butunlay-bosh"
    ishchi.mkdir()
    assert not any(ishchi.iterdir()), "joriy papka BO'SH bo'lishi kerak"

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija)
    _yurish_sogdir(y)
    # ⚠️ Natija AYNAN berilgan papkaga tushdi, joriy papkaga EMAS.
    assert y.paket.parent == natija
    assert not any(ishchi.iterdir()), \
        f"joriy papkaga nimadir yozildi: {[q.name for q in ishchi.iterdir()]}"


def test_repo_tashqarisidagi_papkadan_yuradi(tmp_path: pathlib.Path):
    """2-JOY: joriy papka REPO TASHQARISIDA (`binos-agent-build` ostida).

    ⚠️ Nega muhim: repo daraxti yonida turmagan holatni isbotlaydi — manba fayllari
       `..` orqali ham topilmaydi.
    """
    _dist_talab()
    ishchi = _YIGMA_ILDIZ
    assert _WORKTREE not in ishchi.parents and ishchi != _WORKTREE, \
        "2-JOY repo TASHQARISIDA bo'lishi kerak"
    kuzat, natija = _joy(tmp_path, "tashqari")

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija)
    _yurish_sogdir(y)
    assert y.paket.parent == natija


def test_uchinchi_ishchi_papkadan_yuradi(tmp_path: pathlib.Path):
    """3-JOY: joriy papka `System32` — repo bilan HECH QANDAY aloqasi yo'q va YOZISH
    huquqi ham kutilmaydi.

    ⚠️ Nega muhim: agar agent jim turib joriy papkaga vaqtinchalik fayl yozsa, bu yerda
       yiqilardi. Ya'ni test «joriy papka yoziladigan bo'lishi SHART emas» ni qulflaydi.
    """
    _dist_talab()
    ishchi = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    kuzat, natija = _joy(tmp_path, "system32")

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija)
    _yurish_sogdir(y)
    assert y.paket.parent == natija


def test_natija_UCH_joyda_bir_xil_chiqadi(tmp_path: pathlib.Path):
    """⚠️ Uch joydan «ishladi» yetarli emas: natija MAZMUNI ham bir xil bo'lishi kerak,
    aks holda joriy papka natijaga jimgina ta'sir qilgan bo'lardi.

    ⚠️ `agent_status.json` BAYT-BA-BAYT solishtirilmaydi: unda `started_at`/`finished_at`
       bor va ular har yurishda boshqa. Shu bois QARORGA ta'sir qiladigan maydonlar
       solishtiriladi.
    """
    _dist_talab()
    joylar = {
        "bosh-temp": tmp_path,
        "repo-tashqarisi": _YIGMA_ILDIZ,
        "system32": pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32",
    }
    barmoq: dict[str, tuple] = {}
    for nom, ishchi in joylar.items():
        kuzat, natija = _joy(tmp_path, f"solish-{nom}")
        y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija)
        _yurish_sogdir(y)
        st, mh = y.status(), y.muhit()
        barmoq[nom] = (
            y.paket.name, tuple(sorted(st["artifacts"])), st["state"], st["route"],
            st["mode"], tuple(e["code"] for e in st["errors"]),
            mh["presence_verdict"], mh["com_registered"], tuple(mh["notes"]),
            # ⚠️ Hisobotning O'LCHAMI emas, XESHI: matn ichida yo'l bo'lsa farq chiqardi.
            hashlib.sha256((y.paket / "discovery_report.md").read_bytes()).hexdigest(),
        )
    birinchi = next(iter(barmoq))
    for nom, qiymat in barmoq.items():
        assert qiymat == barmoq[birinchi], (
            f"natija joriy papkaga BOG'LIQ bo'lib chiqdi: `{nom}` `{birinchi}` dan farq "
            f"qiladi.\n  {nom}: {qiymat}\n  {birinchi}: {barmoq[birinchi]}")


def test_result_dir_berilmasa_JORIY_papkaga_yoziladi(tmp_path: pathlib.Path):
    """⚠️ Standart xulq: `--result-dir` berilmasa natija JORIY papkaga tushadi — yig'ma
    papkasiga ham, `%TEMP%` ga ham, `AppData` ga ham EMAS.

    ⚠️ Nega shu muhim: yig'ma papkasiga yozish operatorda «Program Files» da bo'lsa
       administrator huquqini talab qilardi.
    """
    _dist_talab()
    kuzat = tmp_path / "kuzat-std"
    kuzat.mkdir()
    ishchi = tmp_path / "joriy-papka"
    ishchi.mkdir()

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=None)
    _yurish_sogdir(y)
    assert y.paket.parent == ishchi, \
        f"standart natija papkasi joriy papkada emas: {y.paket}"


def test_yigma_KOCHIRILGANDA_ham_yuradi(tmp_path: pathlib.Path):
    """⚠️ ENG KUCHLI §8 isboti: yig'ma papkasi BOSHQA yo'lga KO'CHIRILADI va shu nusxadan
    yuritiladi. Yo'lda ATAYLAB bo'sh joy va LOTIN BO'LMAGAN (kirill) belgilar bor —
    do'kon kompyuterida papka nomi `Разведка 1С` bo'lishi mumkin.

    ⚠️ Agar yig'ma qurilgan joyiga (`dist-onedir`) bog'langan bo'lsa — bu test yiqiladi.
    """
    _dist_talab()
    nusxa_ildizi = tmp_path / "Разведка 1С (ko'chirilgan)"
    nusxa = nusxa_ildizi / "BinOSDiscoveryAgent"
    shutil.copytree(_DIST, nusxa)
    nusxa_exe = nusxa / "BinOSDiscoveryAgent.exe"
    assert nusxa_exe.exists()

    kuzat, natija = _joy(tmp_path, "kochirilgan")
    y = _yurgiz(nusxa_exe, cwd=nusxa_ildizi, kuzat=kuzat, natija=natija)
    _yurish_sogdir(y)
    assert y.paket.parent == natija


def test_yigma_ILDIZ_papkasi_ozgarmaydi(tmp_path: pathlib.Path):
    """⚠️ Yurish o'z yig'ma papkasiga HECH NARSA yozmasin: operator papkasi O'ZGARMAS
    qolsa, uning `sha256` ro'yxati keyin ham to'g'ri bo'ladi.

    ⚠️ Yig'uvchi (PyInstaller) ONE-DIR tanlanganining amaliy sababi ham shu: `--onefile`
       har yurishda `%TEMP%` ga o'zini ochardi.
    """
    _dist_talab()

    def suratga_ol() -> dict[str, int]:
        return {str(p.relative_to(_DIST)): p.stat().st_size
                for p in _DIST.rglob("*") if p.is_file()}

    oldin = suratga_ol()
    kuzat, natija = _joy(tmp_path, "ozgarmas")
    _yurish_sogdir(_yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija))
    keyin = suratga_ol()

    assert keyin == oldin, (
        f"yig'ma papkasi yurishdan keyin O'ZGARDI.\n"
        f"  yangi/o'zgargan: {sorted(set(keyin.items()) - set(oldin.items()))[:10]}\n"
        f"  yo'qolgan:       {sorted(set(oldin) - set(keyin))[:10]}")


def test_repo_daraxtiga_HECH_NARSA_yozilmaydi(tmp_path: pathlib.Path):
    """⚠️ Yig'ma repo bilan BOG'LIQ EMAS: yurishdan keyin repo ildizida va `apps/server` da
    natija papkasi PAYDO BO'LMASIN. Aks holda «cwd repo bo'lishiga tayanmaydi» da'vosi
    yolg'on bo'lardi.
    """
    _dist_talab()
    kuzat, natija = _joy(tmp_path, "repo-toza")
    _yurish_sogdir(_yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija))

    sochilgan = [str(q) for tekshir in (_WORKTREE, _SERVER, _SERVER / "tests")
                 for q in tekshir.glob("binos-discovery-*")]
    assert not sochilgan, f"repo daraxtida natija papkasi paydo bo'ldi: {sochilgan}"


# ═══ A2. §8 — ISHLAB CHIQUVCHI YO'LI YIG'MADA YO'Q (ikkilik qidiruv) ════════════════════
#: ⚠️ Naqshlar SHU mashinaning izlari: repo yo'li, build muhiti, worktree nomi.
#: ⚠️ `pyinstaller` va `site-packages` ATAYLAB bu ro'yxatda YO'Q va bu MUHIM farq:
#   `pyinstaller` — EXE ichidagi yuklovchining O'Z nomi (`PYINSTALLER_RESET_ENVIRONMENT`
#   kabi o'zgaruvchilar), `site-packages` — CPython ning `site` moduli YORDAM MATNI
#   (`python312.dll` ichida). Ikkisi ham YO'L emas, ya'ni ishlab chiquvchi haqida hech
#   narsa oshkor qilmaydi. Ularni naqsh qilish test'ni YOLG'ON qizil qilardi.
_BU_MASHINA_NAQSHI = (
    r"c:\users\developer", "c:/users/developer", r"users\developer",
    "binos-agent-build", "buildenv", "dist-onedir", "build-onedir",
    "worktrees", "1c-autonomous-agent", "savdoos",
    ".venv", r"apps\server", "apps/server",
)


def test_yigmada_BU_MASHINA_yoli_YOQ():
    """⚠️ Yig'mada ishlab chiquvchi mashinasining yo'li QOLMASIN: operator papkasi qo'ldan
    qo'lga o'tadi va u yerdagi har bayt tarqaydi.

    ⚠️ Har naqsh UCH kodlashda qidiriladi: UTF-8 (Python matni va PYZ TOC), UTF-16-LE
       (Windows resurslari, versiya bloki) va CP1251 (kirill matn).
    """
    _dist_talab()
    ignalar: list[tuple[str, bytes]] = []
    for s in _BU_MASHINA_NAQSHI:
        for enc in ("utf-8", "utf-16-le", "cp1251"):
            try:
                ignalar.append((f"{s} [{enc}]", s.encode(enc).lower()))
            except UnicodeEncodeError:
                pass
    topildi: dict[str, list[str]] = {}
    for p in sorted(_DIST.rglob("*")):
        if not p.is_file():
            continue
        baytlar = p.read_bytes().lower()
        for nom, igna in ignalar:
            if igna in baytlar:
                topildi.setdefault(nom, []).append(str(p.relative_to(_DIST)))
    assert not topildi, (
        f"Yig'ma baytlarida SHU mashinaning yo'li qoldi: {topildi}\n"
        f"⚠️ Bu nuqson: operator papkasi ishlab chiquvchi joylashuvini oshkor qiladi.")


def test_yigmadagi_mutlaq_yollar_BU_foydalanuvchiga_tegishli_EMAS():
    """⚠️ Oldingi test NAQSH ro'yxatiga tayanadi — ro'yxat esa to'liq bo'lmasligi mumkin.
    Bu test teskari tomondan yuradi: yig'madagi HAR QANDAY disk harfi bilan boshlanadigan
    yo'lni TOPADI va ularning birortasi ham SHU foydalanuvchining profiliga yoki repo
    ildiziga ishora qilmasligini tekshiradi.

    ⚠️ Topiladigan yo'llar YUQORI OQIM yig'uvchilaridan keladi va bu NORMAL: CPython ni
       python.org `D:\\a\\1\\...` da, OpenSSL ni `C:\\A\\_work\\...` da quradi. Ular
       begona mashinaning yo'li va bizning mashinamiz haqida hech narsa aytmaydi, shu bois
       ularni TAQIQLASH mumkin emas — tekshiriladigan narsa faqat BIZGA tegishliligi.

    ⚠️ IKKI YOLG'ON IGNA ATAYLAB OLIB TASHLANGAN (ikkisi ham HAQIQIY yurishda chiqdi):
       1. Qidiruv naqshi `://` dan KEYIN boshlanmaydi: `https://...` dagi `s:` disk harfiga
          o'xshaydi va `Tcl` ning `http-2.9.8.tm` moduli ichidagi hujjat HAVOLASI
          «mutlaq yo'l» bo'lib tutilardi.
       2. Foydalanuvchi nomi YAKKA holda qidirilmaydi, faqat YO'L BO'LAGI sifatida
          (`users\\<nom>`): `USERNAME` bu mashinada `Developer` va u `developer.mozilla.org`
          ichida uchraydi — bu yo'l emas, havola.
    """
    _dist_talab()
    naqsh = re.compile(rb"[A-Za-z]:[\\/](?![\\/])[A-Za-z0-9_\\/. ~+-]{6,120}")
    nom = os.environ.get("USERNAME") or ""
    bizning = {s.lower() for s in filter(None, (
        os.environ.get("USERPROFILE"),
        rf"users\{nom}" if nom else "", f"users/{nom}" if nom else "",
        str(_WORKTREE), str(_YIGMA_ILDIZ),
    ))}
    yomon: dict[str, list[str]] = {}
    jami = 0
    for p in sorted(_DIST.rglob("*")):
        if not p.is_file():
            continue
        for m in set(naqsh.findall(p.read_bytes())):
            jami += 1
            matn = m.decode("latin-1").lower()
            for b in bizning:
                if b and b in matn:
                    yomon.setdefault(matn, []).append(str(p.relative_to(_DIST)))
    assert jami, "yig'mada birorta yo'lga o'xshash satr topilmadi — qidiruv usuli buzilgan"
    assert not yomon, (
        f"Yig'mada BIZGA tegishli mutlaq yo'l topildi: {yomon}\n"
        f"⚠️ Bu nuqson: qaysi faylda ekani yuqorida ko'rsatilgan.")


# ═══ B. §9 — TOZA MASHINA YAQINLASHUVI (APPROXIMATED, isbot EMAS) ══════════════════════
def test_PATH_kesilganda_ham_yuradi(tmp_path: pathlib.Path):
    """`python` PATH da BO'LMAGANDA ham yig'ma ishlaydi.

    ⚠️⚠️ Bu TOZA MASHINA isboti EMAS: mashinada Python va `.venv` baribir DISKDA turadi —
         faqat ularga olib boradigan muhit o'zgaruvchilari KESILGAN. Haqiqiy isbot uchun
         Python umuman o'rnatilmagan IKKINCHI Windows mashinasi kerak, u YO'Q.
    """
    _dist_talab()
    muhit = _kesilgan_muhit()
    assert shutil.which("python", path=muhit["PATH"]) is None, \
        f"kesilgan PATH da hamon `python` topilmoqda: {muhit['PATH']}"
    kuzat, natija = _joy(tmp_path, "path-kesilgan")

    y = _yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija, muhit=muhit)
    _yurish_sogdir(y)


def test_VIRTUAL_ENV_va_PYTHONPATH_BERILMASA_ham_yuradi(tmp_path: pathlib.Path):
    """Bo'lishilgan `.venv` ga olib boradigan o'zgaruvchilar UMUMAN berilmasa ham ishlaydi.

    ⚠️ `.venv` ning O'ZIGA TEGILMAYDI (u boshqa sessiyalar bilan bo'lishilgan) — o'lchash
       usuli: unga ishora qiladigan `VIRTUAL_ENV`, `PYTHONHOME`, `PYTHONPATH`
       o'zgaruvchilarini BERMASLIK.
    """
    _dist_talab()
    muhit = _kesilgan_muhit()
    for nom in _PYTHON_OZGARUVCHILARI:
        assert nom not in muhit, f"{nom} muhitda qolib ketdi"
    kuzat, natija = _joy(tmp_path, "venvsiz")

    y = _yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija, muhit=muhit)
    _yurish_sogdir(y)
    # ⚠️ Yig'ma O'Z interpretatorini ishlatdi: natija paketi yozildi va hukm chiqdi.
    assert y.muhit()["presence_verdict"] == "absent"


def test_MANBA_daraxti_topilmasa_ham_yuradi(tmp_path: pathlib.Path):
    """Repo manba daraxti ko'rinmaydigan joyda (`PYTHONPATH` BO'SH, cwd repo tashqarisida)
    ham yig'ma ishlaydi."""
    _dist_talab()
    muhit = _kesilgan_muhit()
    muhit["PYTHONPATH"] = ""          # ⚠️ ATAYLAB bo'sh satr: «yo'l yo'q» holati
    ishchi = _YIGMA_ILDIZ
    kuzat, natija = _joy(tmp_path, "manbasiz")

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija, muhit=muhit)
    _yurish_sogdir(y)


def _soxta_app_paketi(ildiz: pathlib.Path) -> None:
    """Import qilinsa DARHOL yiqiladigan soxta `app.services.discovery_agent` paketi."""
    zahar = "raise SystemExit(77)   # soxta manba daraxti: import qilinmasligi SHART\n"
    d = ildiz / "app" / "services" / "discovery_agent"
    d.mkdir(parents=True)
    for q in (ildiz / "app", ildiz / "app" / "services", d):
        (q / "__init__.py").write_text(zahar, encoding="utf-8")
    (d / "__main__.py").write_text(zahar, encoding="utf-8")


def test_JORIY_papkadagi_soxta_app_paketi_IMPORT_QILINMAYDI(tmp_path: pathlib.Path):
    """⚠️ Yig'ma O'Z modullarini ishlatadi: joriy papkada `app/services/discovery_agent/`
    bo'lsa ham undan O'QIMAYDI.

    ⚠️ Nega bu portativlik savoli: agar yig'ma joriy papkadan import qilsa, operator
       tasodifan `app` nomli papka yonida turgan joydan yurgizganda xulq O'ZGARARDI —
       va bu yo'l orqali TASHQI kod bajarilishi mumkin bo'lardi (xavfsizlik).
    """
    _dist_talab()
    ishchi = tmp_path / "soxta-cwd"
    ishchi.mkdir()
    _soxta_app_paketi(ishchi)
    kuzat, natija = _joy(tmp_path, "soxta-cwd-nat")

    y = _yurgiz(_EXE, cwd=ishchi, kuzat=kuzat, natija=natija)
    assert y.kod != 77, "joriy papkadagi soxta `app` paketi IMPORT QILINDI — jiddiy nuqson"
    _yurish_sogdir(y)


def test_ZAHARLANGAN_PYTHONPATH_yigmaga_tasir_qilmaydi(tmp_path: pathlib.Path):
    """⚠️ `PYTHONPATH` soxta `app` paketiga ko'rsatilsa ham yig'ma O'Z modulini ishlatadi.

    ⚠️ Birgalikda oldingi test bilan bu `source ↔ packaged` chegarasini qulflaydi:
       yig'ilgan ilova manba daraxtiga NA tayanadi, NA undan ta'sirlanadi.
    """
    _dist_talab()
    soxta = tmp_path / "soxta-pythonpath"
    soxta.mkdir()
    _soxta_app_paketi(soxta)
    muhit = _kesilgan_muhit()
    muhit["PYTHONPATH"] = str(soxta)
    kuzat, natija = _joy(tmp_path, "zahar-pp")

    y = _yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija, muhit=muhit)
    assert y.kod != 77, "`PYTHONPATH` dagi soxta paket IMPORT QILINDI — jiddiy nuqson"
    _yurish_sogdir(y)


def test_YOLGON_PYTHONHOME_bilan_ham_yuradi(tmp_path: pathlib.Path):
    """⚠️ `PYTHONHOME` mavjud BO'LMAGAN papkaga ko'rsatilsa ham yig'ma ishlaydi: operator
    mashinasida eski Python o'rnatmasidan qolgan noto'g'ri o'zgaruvchi bo'lishi mumkin.
    """
    _dist_talab()
    muhit = _kesilgan_muhit()
    yoq = tmp_path / "bunday-papka-yoq"
    assert not yoq.exists()
    muhit["PYTHONHOME"] = str(yoq)
    kuzat, natija = _joy(tmp_path, "yolgon-home")

    y = _yurgiz(_EXE, cwd=tmp_path, kuzat=kuzat, natija=natija, muhit=muhit)
    _yurish_sogdir(y)


def test_version_kesilgan_muhitda_ham_chiqadi(tmp_path: pathlib.Path):
    """⚠️ Eng arzon tekshiruv: `--version` kesilgan muhitda ham `0` kod bilan chiqsin.
    Operator nosozlikni aynan shu buyruq bilan birinchi marta tekshiradi.
    """
    _dist_talab()
    p = subprocess.run([str(_EXE), "--version"], cwd=str(tmp_path),
                       env=_kesilgan_muhit(), capture_output=True, timeout=120)
    chiqish = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, f"kod {p.returncode}: {p.stderr.decode('utf-8', 'replace')}"
    assert "BinOSDiscoveryAgent" in chiqish
    # ⚠️ Versiya matnining O'ZI 1C haqidagi da'voni USTIDA saqlaydi.
    assert "RUNTIME-UNKNOWN" in chiqish, \
        "versiya matni 1C integratsiyasi haqidagi ogohlantirishni yo'qotdi"


# ═══ C. HUJJAT — `AGENT_PORTABLE_BUILD.md` HOLATI va HALOLLIGI ═════════════════════════
#: ⚠️ Bu testlar yig'masiz ham ishlaydi: ular repo faylini o'qiydi. Ya'ni hujjatning
#   halolligi CI mashinasida ham QULFLANGAN.


def _doc() -> str:
    assert _DOC.exists(), f"hujjat yo'q: {_DOC}"
    return _DOC.read_text(encoding="utf-8")


def test_hujjat_BUILD_tafsilotlarini_yozadi():
    """⚠️ Hujjat «qanday qurilgan» savoliga ANIQ javob bersin: vosita, ANIQ versiya,
    strategiya va AYNAN qaysi buyruq. Taxminiy tavsif keyingi qurishni takrorlanmas
    qilardi.
    """
    matn = _doc()
    for kerak in ("PyInstaller 6.22.3", "3.12.10", "ONE-DIR",
                  "BinOSDiscoveryAgent.spec", "binos-agent-build"):
        assert kerak in matn, f"hujjatda `{kerak}` yo'q"


def test_hujjat_IMZOLANMAGANINI_va_APPROXIMATED_ni_OCHIQ_yozadi():
    """⚠️ §11 va §9 ning halollik talabi: imzo YO'Q va toza-mashina natijasi
    YAQINLASHUV ekani hujjatda OCHIQ turishi kerak.
    """
    matn = _doc()
    assert "APPROXIMATED" in matn, \
        "hujjat toza-mashina natijasini YAQINLASHUV deb belgilamagan"
    assert "IMZOLANMAGAN" in matn and "unsigned" in matn, \
        "hujjat imzo yo'qligini OCHIQ yozmagan"
    assert "RUNTIME-UNKNOWN" in matn, \
        "hujjat 1C integratsiyasining holatini yo'qotgan"


#: ⚠️ TAQIQLANGAN IBORALAR — har biri hujjatda BO'LSA, hujjat isbotlanmagan narsani
#   da'vo qilgan bo'ladi. Iboralar ATAYLAB TO'LIQ: bitta so'z (`sinalgan`) taqiqlansa
#   `SINALMAGAN` ham tutilib, test yolg'on qizil bo'lardi.
_TAQIQ = (
    "toza mashinada ishlaydi",
    "toza mashinada sinaldi",
    "toza mashinada tekshirildi",
    "imzolangan",
    "code signing bajarildi",
    "1c bilan ishlaydi",
    "1c bilan sinaldi",
    "production uchun tayyor",
    "ishlab chiqarishga tayyor",
    "do'konga tarqatishga tayyor",
)


def test_hujjatda_ISBOTLANMAGAN_DAVO_yoq():
    """⚠️ Hujjat o'lchangan narsani yozadi, kutilgan narsani YOZMAYDI."""
    past = _doc().lower()
    topildi = [s for s in _TAQIQ if s in past]
    assert not topildi, f"hujjatda isbotlanmagan da'vo bor: {topildi}"
    # ⚠️ `signed` so'zi faqat `unsigned` ichida uchrashi mumkin: alohida `signed` —
    #    imzolangan degan da'vo bo'lardi.
    yolgon_imzo = [m.start() for m in re.finditer(r"(?<!un)signed", past)]
    assert not yolgon_imzo, \
        f"hujjatda `signed` (imzolangan) da'vosi bor, o'rinlar: {yolgon_imzo}"


def test_hujjatdagi_EXE_XESHI_haqiqiy_yigmaga_MOS():
    """⚠️ Hujjatda yozilgan SHA-256 HAQIQIY yig'maning xeshi bo'lsin.

    ⚠️ Nega gate: xesh hujjatning «qaysi yig'ma haqida gapirayotgani» ni belgilaydi. Qayta
       qurilgandan keyin xesh o'zgaradi — demak hujjat ham YANGILANISHI kerak, aks holda u
       mavjud bo'lmagan yig'ma haqida gapiradi. Yig'ma bo'lmasa (CI) — bu test `skip`.
    """
    _dist_talab()
    haqiqiy = hashlib.sha256(_EXE.read_bytes()).hexdigest()
    matn = _doc()
    xeshlar = set(re.findall(r"\b[0-9a-f]{64}\b", matn.lower()))
    assert xeshlar, "hujjatda birorta SHA-256 yozilmagan"
    assert haqiqiy in xeshlar, (
        f"hujjatdagi xesh haqiqiy yig'maga MOS EMAS.\n"
        f"  haqiqiy: {haqiqiy}\n  hujjatda: {sorted(xeshlar)}\n"
        f"⚠️ Yig'ma qayta qurilgan bo'lsa — hujjatdagi xesh, o'lcham va sanani YANGILANG.")
