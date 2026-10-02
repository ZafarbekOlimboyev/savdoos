# -*- coding: utf-8 -*-
"""A..J — YIG'ILGAN `.exe` NI HAQIQATAN YURGIZIB o'tkazilgan uchiga-uch matritsa.

⚠️⚠️ BU FAYL NIMASI BILAN BOSHQALARDAN FARQ QILADI: `tests/test_agent_e2e_watch_folder.py`
     quvurni JARAYON ICHIDA (`UiModel.start()`) yuritadi va hamma bog'liqlikni
     ALMASHTIRADI — soat, `sleeper`, muhit skaneri, analitik. Bu fayl esa
     `BinOSDiscoveryAgent.exe` ni `subprocess` bilan ROSTDAN ishga tushiradi: PyInstaller
     yig'masi, HAQIQIY muhit skaneri (bu mashinada 1C YO'Q), HAQIQIY `time.sleep`, HAQIQIY
     konsol kodlashi. Shu bois bu fayl faqat jarayon ichida KO'RINMAYDIGAN nuqsonlarni
     ko'radi: yig'maga modul tushmay qolishi, chiqish kodlarining shartnomasi, `stdout`
     kodlashi va natija papkasining ROSTDAN yozilishi.

⚠️⚠️ BU REAL 1C ISBOTI EMAS. Kuzatilgan papkaga tushadigan paketlar — SINTETIK FIKSTURA
     (`tests.discovery_1c_runtime_mock`, Phase 4 generatorlari). Bu faylda 1C ga ULANISH
     YO'Q, `1cv8.exe` ISHGA TUSHMAYDI, `.epf` BAJARILMAYDI va TARMOQ ishlatilmaydi.
     Fiksturani «real 1C collection» DEB ATASH YOLG'ON bo'lardi: u operator yig'uvchini
     yurgizgandan KEYINGI papkaning SHAKLINI taqlid qiladi, yig'uvchining 1C da rostdan
     ishlashini esa ISBOTLAMAYDI (`RUNTIME-UNKNOWN` bo'lib qoladi).

NIMA QULFLANADI (har ssenariyda, `_umumiy_shartnoma` orqali):
    1. OPERATORGA PYTHON TRACEBACK CHIQMAYDI — `stdout` ham, `stderr` ham toza;
    2. CHIQISH KODI UCH QIYMATLI SHARTNOMAGA mos: `0` tugadi · `1` yurish yiqildi ·
       `2` yurish BOSHLANMADI;
    3. NATIJA PAPKASI YOZILADI — YIQILGAN yurishda HAM — va u `result_package` ning
       HAQIQIY validatoridan o'tadi (brief §2: failure package ham VALID package);
    4. ildizda BESHTA majburiy artefakt bor (ro'yxat koddan: `rp.ALWAYS_FILES`).

⚠️ YIG'MA REPO TASHQARISIDA turadi — ildiz `BINOS_AGENT_BUILD_ROOT` dan keladi (zaxira
   `~/binos-agent-build`), shu bois CI mashinasida u BO'LMAYDI va `.exe` ni YURGIZADIGAN
   testlar ANIQ SABAB bilan `skip` bo'ladi. Darvozaning O'Z o'lchovi (§0) yig'masiz ham
   ishlaydi — u faqat qaror jadvalini va shu modulning manbasini o'qiydi.

⚠️⚠️ TO'RTINCHI DARVOZA, AYNI TESHIK (2026-10-02 da tuzatildi): bu fayl ilgari (a) yig'ma
     ildizini QO'LDA `C:/Users/Developer/binos-agent-build/...` deb yozardi — ya'ni
     `BINOS_AGENT_BUILD_ROOT` ni UMUMAN o'qimasdi va qolgan darvozalar bilan jimgina
     BOSHQA yig'mani tekshirishi mumkin edi; (b) MODUL darajasidagi `pytest.mark.skipif`
     bilan `.exe` yo'q bo'lsa SHARTSIZ `skip` berardi — platformaga bog'liq EMAS va
     YANGILIK tekshiruvi YO'Q; (c) skip'lari `tests/ci_expected_skips.txt` da UMUMAN
     YO'Q edi, ya'ni HAQIQIY Linux CI'da 15 ta «KUTILMAGAN skip» backend job'ni QIZIL
     qilardi. To'rtinchisining amaliy oqibati ENG og'ir: bu modul `.exe` ni `subprocess`
     bilan ROSTDAN yurgizadi, demak ESKIRGAN artefakt «uchiga-uch ishlaydi» deb
     TASDIQLANARDI — o'lchangan holat `15 passed` (yig'ma uch moduldan eskirgan,
     qarang `packaging/BUILD_GATE.md` §2).

⚠️ `BINOS_AGENT_EXE` bu modulda BOSHQA ARTEFAKTGA yo'naltirish uchun O'QILMAYDI: ildiz
   BITTA manbadan kelishi kerak (pattern modullari ham shunday). Harness o'sha
   o'zgaruvchini o'qiganda darvoza bilan test BOSHQA fayl ustida ishlab qolmasligi
   `_darvoza_AYNI_EXE_ni_olchasin()` da BALAND tekshiriladi.

⚠️ HAQIQIY VAQT KUTILMAYDI: `--wait-seconds` KICHIK beriladi (so'rov oralig'i ko'prikda
   2 s), ya'ni kutish ssenariylari ~2 s da tugaydi. Cheksiz kutish agentda UMUMAN yo'q.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from app.services.discovery_1c import ai
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_agent import (AGENT_STATUS_FILE, AI_CANDIDATES_FILE,
                                          BUNDLE_SUBDIR, REPORT_FILE, RESULT_DIR_PREFIX,
                                          ROUTE_WATCH_FOLDER)
from app.services.discovery_agent import __main__ as agent_main
from app.services.discovery_agent import collector_bridge as bridge
from app.services.discovery_agent import pipeline as P
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from app.services.discovery_agent import ui as agent_ui
from tests import agent_scenario_mock as X
from tests import discovery_1c_metadata_synth as S
from tests import discovery_1c_runtime_mock as M

# ══════════════════════════════════════════════════════════════════════════════════════════
# YIG'MANI TOPISH
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Yig'ma ATAYLAB repo tashqarisida: repo daraxti toza qoladi va `.gitignore` ga tegilmaydi.
#: ⚠️⚠️ ILDIZ QO'LDA YOZILMAYDI. U qolgan darvozalar bilan AYNI muhit o'zgaruvchisidan
#:      keladi; BESH modulning tengligi `tests/test_agent_build_inventory.py` dagi
#:      `test_BESH_modulda_yigma_ILDIZI_AYNI` bilan QULFLANGAN.
_YIGMA_ILDIZ = pathlib.Path(os.environ.get("BINOS_AGENT_BUILD_ROOT")
                            or pathlib.Path.home() / "binos-agent-build")
_DIST = _YIGMA_ILDIZ / "dist-onedir" / "BinOSDiscoveryAgent"
EXE = _DIST / "BinOSDiscoveryAgent.exe"

#: `apps/server` — harness yo'lini hisoblash uchun ildiz.
_SERVER = pathlib.Path(__file__).resolve().parents[1]


# ══════════════════════════════════════════════════════════════════════════════════════════
# ESKIRGAN YIG'MA DARVOZASI — bu modul uchun ham MAJBURIY
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ O'LCHANGAN TESHIK (shu worktree'da): mahalliy `.exe` uch moduldan eskirgan edi
#      (`discovery_1c/redact.py`, `discovery_agent/detector.py`,
#      `discovery_agent/launcher.py`) — `test_agent_parity.py` BALAND yiqildi va uchtasini
#      NOMLADI, bu modul esa `15 passed` berdi. Ya'ni UCHIGA-UCH darvozasi ESKIRGAN
#      artefaktni «ishlaydi» deb TASDIQLADI.
#
# ⚠️ NEGA BU MODULGA HAM SHART: bu yerdagi HAR BIR da'vo JORIY manba haqidagi da'vo bo'lib
#    o'qiladi — «buzuq manifest tugallanish belgisi sifatida QABUL QILINMAYDI», «sir
#    birorta BAYTGA yozilmaydi», «`VERIFIED` da'vosi RAD etiladi», «chiqish kodlari
#    shartnomada». Eskirgan artefaktda bu da'volar YOLG'ON yashil bo'ladi: manbaga BUGUN
#    kiritilgan regressiya (masalan `redact.py` ning sirni oshkor qilishi) ESKI `.exe` da
#    umuman BAJARILMAYDI.
#
# ⚠️ Darvoza QAYTA YOZILMAYDI: hukm `packaging/parity_harness.yigma_tayyorligi()` dan
#    OLINADI (OWNER B) — AYNI harness, AYNI qaror jadvali.
_HARNESS_YOLI = _SERVER / "packaging" / "parity_harness.py"

#: ⚠️ parity · packaging · portability harnessni AYNI shu nom bilan `sys.modules` ga
#:    qo'yadi — mavjud nusxa QAYTA ISHLATILADI. Aks holda bir yurishda TO'RTINCHI modul
#:    nusxasi paydo bo'lardi va unga qo'yilgan o'lchov boshqalariga ta'sir qilmasdi.
_HARNESS_MODUL_NOMI = "binos_parity_harness"


def _harness():
    """OWNER B darvozasi — YO'L bilan va KECHIKTIRILGAN holda yuklanadi.

    ⚠️⚠️ `from packaging.parity_harness import ...` ISHLAMAYDI: `packaging` nomi PyPI
         paketi bilan to'qnashadi (oddiy paket nom bo'shliqli paketdan USTUN turadi).
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

#: ⚠️⚠️ SABAB MATNI BOSHQA UCH DARVOZADAN ATAYLAB FARQ QILADI:
#:      `MUHIT: Windows EXE Linux CI'da QURILMAYDI`      — parity (OWNER B);
#:      `MUHIT: Windows yig'masi Linux CI'da QURILMAYDI` — yig'ma tarkibi;
#:      `MUHIT: Windows EXE'ni Linux CI YURGIZA OLMAYDI` — portativlik.
#:      `verify_pytest_run._matches` sababni `reason in msg` bilan tekshiradi, ya'ni
#:      matnlar bir-birining BO'LAGI bo'lsa, bir darvozaning yozuvi yo'qolganda uning
#:      skip'lari ikkinchisining qatoriga «yashirinib» o'tib ketardi va KUTILMAGAN skip
#:      QIZIL bermasdi. Shu bois to'rtinchisi O'Z matnini ishlatadi va u BOSHQA SO'Z
#:      BILAN boshlanadi (`Linux CI'da ...`), demak uchtasining BO'LAGI bo'lishi
#:      MUMKIN EMAS. Ajralganlik `::test_darvoza_ESKIRGAN_yigmani_ISHLAYDI_demaydi` da
#:      test bilan qulflangan.
#: ⚠️ Matn SEMANTIK jihatdan ham boshqa: bu modul `.exe` ni UCHIGA-UCH ssenariy
#:    matritsasi bilan yurgizadi (natija paketi, chiqish kodlari, konsol kodlashi).
_MUHIT_SABABI = "MUHIT: Linux CI'da Windows yig'masi UCHIGA-UCH yurmaydi"


def _yoqlik_qarori(*, qurilishi_mumkin: bool) -> tuple[str, str]:
    """`.exe` UMUMAN YO'Q bo'lganda: `(qaror, matn)`.

    ⚠️⚠️ «EXE yo'q bo'lsa skip» SHARTSIZ EMAS va bu ataylab: yig'ma QURILISHI mumkin
         bo'lgan platformada (Windows) yo'qligi OPERATORNING ishi, muhit cheklovi EMAS —
         u yerda uchiga-uch matritsa O'LCHANMAGANI SKIP bo'lib ko'rinmasligi kerak.
         Ilgari bu modulda MODUL darajasidagi SHARTSIZ `skipif` turardi, ya'ni Windows
         reliz darvozasida yig'ma topilmasa «hammasi o'tdi» ko'rinishi mumkin edi.
    ⚠️ Skip matni `_MUHIT_SABABI` bilan BOSHLANADI — `tests/ci_expected_skips.txt` dagi
       sabab bo'lagi AYNAN shu satr (o'zgartirilsa ro'yxat ham yangilanadi).
    """
    if qurilishi_mumkin:
        return _QAROR_YIQIL, (
            f"UCHIGA-UCH MATRITSA O'LCHANMADI: {EXE} topilmadi, LEKIN bu platformada "
            f"(`{sys.platform}`) yig'ma QURILADI va YURADI — ya'ni yo'qligi MUHIT "
            f"cheklovi EMAS va skip bo'lib o'tib ketishi TAQIQLANGAN. Reliz darvozasi "
            f"(`packaging/BUILD_GATE.md`) bo'yicha yig'ing, build papkasini SAQLAB "
            f"(`--workpath`), so'ng shu modulni qayta yurgizing.")
    return _QAROR_SKIP, (
        f"{_MUHIT_SABABI}. Yig'ma YO'Q: {EXE} topilmadi. Yig'ma repo tashqarisida "
        f"quriladi (`pyinstaller packaging/BinOSDiscoveryAgent.spec`), PyInstaller "
        f"kross-kompilyatsiya QILMAYDI va Linux backend job'i Windows PE ikkiligini "
        f"BAJARA OLMAYDI (Wine ishlatilmaydi), shu bois bu MUHIT cheklovi. Uchiga-uch "
        f"ssenariylar JARAYON ICHIDA `tests/test_agent_e2e_watch_folder.py` da shu "
        f"yurishda o'lchanadi; darvozaning QAROR JADVALI ham shu yurishda o'lchandi "
        f"(`::test_darvoza_ESKIRGAN_yigmani_ISHLAYDI_demaydi`), yig'ma bilan yurish esa "
        f"Windows reliz darvozasida (`packaging/BUILD_GATE.md`).")


def _yangilik_qarori(holat: str, sabab: str, *, toza: str) -> str | None:
    """`None` — yig'ma JORIY manbadan qurilgani ISBOTLANDI; aks holda YIQILISH matni.

    ⚠️⚠️ FAIL-CLOSED va PLATFORMAGA BOG'LIQ EMAS: `toza` dan BOSHQA HAR holat
         (`ESKIRGAN`, `ISBOTSIZ`, va hatto `YO_Q` — harness BOSHQA `.exe` yo'liga
         qarasa, `BINOS_AGENT_EXE`) YIQILISH beradi. JIM SKIP YO'Q: eskirgan yig'ma
         «uchiga-uch ishlaydi» deb tasdiqlanishining yo'li aynan shu edi.
    ⚠️ `sabab` harnessdan KELGANIDEK uzatiladi — nomos modullar ro'yxati va tuzatish
       yo'li o'sha matnda.
    """
    if holat == toza:
        return None
    return (f"UCHIGA-UCH DARVOZASI O'LCHANMADI (holat: {holat}) — yurgiziladigan yig'ma "
            f"JORIY manbadan qurilgani ISBOTLANMADI. Shu moduldagi «buzuq manifest QABUL "
            f"QILINMAYDI / sir BIRORTA BAYTGA chiqmaydi / `VERIFIED` RAD etiladi / "
            f"chiqish kodlari shartnomada» da'volari ESKI artefakt haqida bo'lardi va "
            f"manbaga BUGUN kiritilgan regressiya umuman BAJARILMASDI (yolg'on "
            f"kafolat). {sabab}")


def _darvoza_AYNI_EXE_ni_olchasin(PH) -> None:
    """Darvoza va testlar AYNI faylni ko'rsin — aks holda BALAND yiqilish.

    ⚠️⚠️ NEGA ALOHIDA TEKSHIRUV: harness `BINOS_AGENT_EXE` ni o'qiydi, bu modul esa
         ildizdan hisoblangan yo'lni YURGIZADI. Ikkisi BOSHQA fayl bo'lsa darvoza BIR
         artefaktni «toza» deb tasdiqlab, testlar BOSHQASINI yurgizardi — ya'ni
         tuzatilgan teshikning AYNI ko'rinishi qaytib kelardi.
    ⚠️⚠️ FAQAT `EXE` MAVJUD bo'lganda chaqiriladi (`_dist_talab()` dagi tartibga qarang)
         va bu ATAYLAB: artefakt yo'q bo'lsa hech narsa YURGIZILMAYDI, demak «ikki
         artefakt chalkashdi» zarari ham YO'Q — u holat `_yoqlik_qarori()` (Windows'da
         YIQILISH, aks holda MUHIT skip'i) va harnessning `YO_Q` holati bilan
         yopilgan. Shartsiz solishtirish esa `BINOS_AGENT_EXE` ni MAVJUD BO'LMAGAN
         yo'lga qo'yib Linux CI'ni taqlid qilish usulini YOLG'ON qizil qilardi.
    ⚠️ Solishtirish `normcase`+`abspath` bilan: Windows'da harf registri va `/`↔`\\`
       farqi YOLG'ON qizil bermasligi kerak.
    """
    def norm(p) -> str:
        return os.path.normcase(os.path.abspath(str(p)))

    if norm(PH.YIGMA_EXE) != norm(EXE):
        pytest.fail(
            f"DARVOZA VA TEST BOSHQA ARTEFAKTNI ko'rsatadi: harness `{PH.YIGMA_EXE}` ni "
            f"tekshiradi, bu modul esa `{EXE}` ni YURGIZADI. Ildiz BITTA manbadan "
            f"kelishi SHART: `{PH.YIGMA_ILDIZ_ENV_KALITI}` ni qo'ying va "
            f"`{PH.YIGMA_ENV_KALITI}` ni OLIB TASHLANG.")


def _chaqirilgan_nomlar(fn) -> set[str]:
    """`fn` TANASIDA ROSTDAN chaqirilgan nomlar (docstring va izoh HISOBGA OLINMAYDI).

    ⚠️⚠️ NEGA MATN QIDIRUVI YETMAYDI — BU O'LCHANGAN MUTATSIYA (M2): darvoza simini
         (`_darvoza_AYNI_EXE_ni_olchasin(PH)` chaqiruvini) OLIB TASHLAB turib,
         `inspect.getsource(...)` ichida nomni IZLASH tekshiruvi YASHIL qoldi — chunki
         `getsource()` DOCSTRINGNI ham qaytaradi va docstring o'sha nomni ESLATADI. Ya'ni
         simlash qo'riqchisining O'ZI o'lik edi. AST esa faqat HAQIQIY `Call` tugunlarini
         ko'radi: izoh ham, docstring ham uni chalg'itmaydi.
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


def _dist_talab() -> None:
    """Yig'ma BOR va JORIY manbadan qurilgani ISBOTLANGAN bo'lsin.

    ⚠️ TARTIB MUHIM: `EXE.exists()` AVVAL o'lchanadi — shu modulning O'Z yo'li bilan.
       Artefakt BOR bo'lsa, darvoza AYNI o'sha faylni ko'rishi
       (`_darvoza_AYNI_EXE_ni_olchasin()`) va u JORIY manbadan qurilgani
       (`yigma_tayyorligi()`) talab qilinadi.
    """
    PH = _harness()
    if not EXE.exists():
        qaror, matn = _yoqlik_qarori(qurilishi_mumkin=PH.exe_qurish_mumkinmi())
        if qaror == _QAROR_YIQIL:
            pytest.fail(matn)
        pytest.skip(matn)
    _darvoza_AYNI_EXE_ni_olchasin(PH)
    holat, sabab = PH.yigma_tayyorligi()
    matn = _yangilik_qarori(holat, sabab, toza=PH.HOLAT_TOZA)
    if matn is not None:
        pytest.fail(matn)

#: Takrorlanadigan natija papkasi nomi uchun qisqa tamg'a (soat O'QILMAYDI).
TAMGA = "20261002T120000Z"
NATIJA_NOMI = f"{RESULT_DIR_PREFIX}{TAMGA}"

#: ⚠️ Kutish KICHIK: chegara KIRISHDAN keladi, demak uni kichraytirish XULQNI o'zgartirmaydi,
#: faqat to'plamni tez qiladi (ko'prikning so'rov oralig'i `DEFAULT_POLL_SECONDS`).
QISQA_KUTISH = "1"

#: Jarayonni hech qachon cheksiz kutmaslik uchun qattiq chegara (sekin diskda ham yetadi).
JARAYON_CHEGARASI = 300.0

#: Operator matnidagi `cp1252` ga SIG'MAYDIGAN belgi — kodlash testining nishoni.
OGOHLIK_BELGISI = "\u26a0"


# ══════════════════════════════════════════════════════════════════════════════════════════
# YURGIZISH
# ══════════════════════════════════════════════════════════════════════════════════════════
class Yurish:
    """Bitta `.exe` yurishining natijasi — jarayondan VA diskdan o'qilgan holda."""

    __slots__ = ("kod", "chiqish", "xato", "ota", "natija_dir", "papkalar", "stdout_baytlari",
                 "kuzatilgan")

    def __init__(self, *, kod, chiqish, xato, ota, papkalar, stdout_baytlari, kuzatilgan):
        self.kod = kod
        self.chiqish = chiqish
        self.xato = xato
        self.ota = ota
        self.papkalar = papkalar
        self.natija_dir = papkalar[0] if len(papkalar) == 1 else None
        self.stdout_baytlari = stdout_baytlari
        self.kuzatilgan = kuzatilgan

    @property
    def ekran(self) -> str:
        """`stdout` + `stderr` — operator KO'RGAN hamma matn."""
        return self.chiqish + "\n" + self.xato

    def _papka(self) -> str:
        assert self.natija_dir is not None, \
            f"AYNAN bitta natija papkasi kutilgan edi, topilgani: {self.papkalar}"
        return str(self.natija_dir)

    def yozuv(self) -> dict:
        return json.loads(X.matn(self._papka(), AGENT_STATUS_FILE))

    def kodlar(self) -> list[str]:
        return [e["code"] for e in self.yozuv()["errors"]]

    def holatlar(self) -> list[str]:
        return [t["to"] for t in self.yozuv()["transitions"]]

    def sabab(self, kod: str) -> str:
        """Berilgan xato kodining tafsiloti (hammasi bitta satrga qo'shilgan holda)."""
        return " ".join(e["detail"] for e in self.yozuv()["errors"] if e["code"] == kod)

    def ildiz_fayllar(self) -> set[str]:
        return {n for n in X.papka_baytlari(self._papka()) if "/" not in n}

    def paket_fayllar(self) -> dict[str, bytes]:
        """`bundle/` ichidagi fayllar — prefiks OLIB TASHLANGAN holda, baytlari bilan."""
        pref = f"{BUNDLE_SUBDIR}/"
        return {n[len(pref):]: b for n, b in X.papka_baytlari(self._papka()).items()
                if n.startswith(pref)}

    def hisobot(self) -> str:
        return X.matn(self._papka(), REPORT_FILE)

    def hamma_bayt(self) -> bytes:
        """Natija OTA papkasidagi HAMMA baytlar (ikkilik fayllar ham) — bitta bo'lak.

        ⚠️ SIR TEKSHIRUVI UCHUN: `papka_baytlari` nomlarga emas, BAYTLARGA qaraydi, shu bois
           sir JSON ichida, Markdown ichida yoki kutilmagan faylda bo'lsa ham topiladi.
        """
        return b"\n".join(X.papka_baytlari(str(self.ota)).values())

    def manba_baytlari(self) -> dict[str, bytes]:
        """KUZATILGAN (operator) papkasining baytlari — agent unga tegmasligi kerak."""
        return X.papka_baytlari(str(self.kuzatilgan))


def _muhit() -> dict[str, str]:
    """`.exe` uchun muhit — `PYTHONIOENCODING`/`PYTHONUTF8` OLIB TASHLANGAN.

    ⚠️⚠️ NEGA OLIB TASHLANADI: aynan shu ikki o'zgaruvchi HAQIQIY nuqsonni YASHIRADI.
         Windows'da chiqish quvurga yo'naltirilganda `sys.stdout.encoding` `cp1252` bo'ladi
         va operator matnidagi `⚠`, `═`, kirill harflar unga SIG'MAYDI. Agar test
         `PYTHONIOENCODING=utf-8` bilan yurgizsa, u o'zi tuzoqni olib tashlagan bo'lardi va
         `test_cp1252_...` hech narsa o'lchamasdi. Mahalliy to'plamda bu o'zgaruvchi ROSTDAN
         qo'yilgan bo'lishi mumkin (loyihada bunday tuzoq allaqachon uchragan), shu bois
         tozalash SHART, ixtiyoriy EMAS.
    """
    return {k: v for k, v in os.environ.items()
            if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}


def yurgiz(tmp_path, nom: str, qurish=None, *, kutish: str = QISQA_KUTISH,
           tamga: str | None = TAMGA, argv_quruvchi=None,
           kuzatilgan_yaratilsin: bool = True) -> Yurish:
    """Yig'ilgan `.exe` ni ROSTDAN ishga tushiradi va natijani diskdan o'qiydi.

    `qurish` — kuzatilgan papkaga SINTETIK paket yozadigan chaqiruv (`None`: bo'sh papka).
    `argv_quruvchi(kuzatilgan, ota)` — bayroqlarni O'ZI quradigan chaqiruv (buyruq
    shartnomasi testlari uchun); berilmasa standart `--headless/--result-dir/--wait-seconds`.
    `kuzatilgan_yaratilsin=False` — papka DISKDA YARATILMAYDI («papka yo'q» ssenariysi).

    ⚠️ `cwd` ATAYLAB alohida papka: agent standart holda natijani JORIY papkaga yozadi, demak
       sinov repo daraxtiga yozib qo'ymasligi kerak. `--result-dir` baribir ANIQ beriladi.
    """
    ish = pathlib.Path(tmp_path) / nom
    kuzatilgan = ish / "kuzatilgan"
    ota = ish / "natija"
    ota.mkdir(parents=True)
    if kuzatilgan_yaratilsin:
        kuzatilgan.mkdir(parents=True)
        if qurish is not None:
            qurish(str(kuzatilgan))

    if argv_quruvchi is None:
        argv = ["--headless", str(kuzatilgan), "--result-dir", str(ota),
                "--wait-seconds", kutish]
        if tamga is not None:
            argv += ["--timestamp", tamga]
    else:
        argv = list(argv_quruvchi(kuzatilgan, ota))

    try:
        p = subprocess.run([str(EXE)] + argv, capture_output=True, cwd=str(ish),
                           env=_muhit(), timeout=JARAYON_CHEGARASI)
    except subprocess.TimeoutExpired as e:          # pragma: no cover - nuqson belgisi
        pytest.fail(f"yig'ilgan agent {JARAYON_CHEGARASI} s da tugamadi — CHEKSIZ KUTISH "
                    f"belgisi: {e}")

    # ⚠️ `errors="replace"` TESTNING o'qishi uchun: agent chiqishi buzuq bo'lsa ham test uni
    #    KO'RSATISHI kerak. Kodlash DA'VOSI alohida testda, QAT'IY dekodlash bilan o'lchanadi.
    return Yurish(kod=p.returncode,
                  chiqish=p.stdout.decode("utf-8", "replace"),
                  xato=p.stderr.decode("utf-8", "replace"),
                  ota=ota,
                  papkalar=sorted(ota.iterdir()) if ota.is_dir() else [],
                  stdout_baytlari=p.stdout,
                  kuzatilgan=kuzatilgan)


# ══════════════════════════════════════════════════════════════════════════════════════════
# HAR SSENARIYDA QULFLANADIGAN UMUMIY SHARTNOMA
# ══════════════════════════════════════════════════════════════════════════════════════════
def _umumiy_shartnoma(y: Yurish, *, kutilgan_kod: int) -> None:
    """Traceback YO'Q · chiqish kodi shartnomada · natija papkasi YAROQLI · 5 ildiz artefakti.

    ⚠️ Bu yordamchi HAR ssenariyda chaqiriladi, chunki brief §2 ning kafolati ssenariyga
       BOG'LIQ EMAS: operator hech qachon «hech narsa qolmadi» holatida qolmasligi kerak.
    """
    assert "Traceback (most recent call last)" not in y.ekran, \
        f"operatorga PYTHON TRACEBACK chiqdi:\n{y.ekran[-3000:]}"
    assert "UnicodeEncodeError" not in y.ekran, \
        "chop etish yurishni buzdi — konsol kodlashi darvozasi ochiq qoldi"
    assert y.kod in (0, 1, 2), f"chiqish kodi shartnomada YO'Q: {y.kod}"
    assert y.kod == kutilgan_kod, (f"chiqish kodi {kutilgan_kod} kutilgan edi, kelgani "
                                  f"{y.kod}:\n{y.ekran[-2000:]}")
    assert len(y.papkalar) == 1, \
        (f"AYNAN bitta natija papkasi bo'lishi SHART (yarim yozilgan ikkinchi papka "
         f"QOLMAYDI), topilgani: {y.papkalar}\n{y.ekran[-2000:]}")
    assert y.natija_dir is not None and y.natija_dir.name.startswith(RESULT_DIR_PREFIX), \
        f"natija papkasining nomi shartnomada emas: {y.papkalar}"
    # ⚠️ HAQIQIY VALIDATOR, «papka bor» tekshiruvi EMAS: manifest xeshlari, ildizdagi
    #    `errors.json` ning sxemasi va yurish yozuvi bilan MOSLIGI — hammasi shu chaqiruvda.
    rp.validate_result_package(str(y.natija_dir))
    bor = y.ildiz_fayllar()
    assert set(rp.ALWAYS_FILES) <= bor, f"ildizda majburiy artefakt yetishmaydi: {bor}"
    assert len(rp.ALWAYS_FILES) == 5, "brief BESH ildiz artefaktini talab qiladi"
    assert "xulosa:" in y.chiqish, "operator ekranida YAKUN qatori bo'lishi SHART"


def _yol_haqqoniyligi(y: Yurish) -> None:
    """`watch_folder` yo'li va «paketli yo'l urinilMADI» qaydi — ikkisi ham YOZUVDA.

    ⚠️ Bu qayd «yiqilish» EMAS: u paketli yo'l NEGA umuman urinilmaganini aytadi. Jimgina
       tashlab ketish operatorga «agent 1C ni o'zi yurgizdi» degan yolg'on taassurot berardi.
    """
    assert y.yozuv()["route"] == ROUTE_WATCH_FOLDER
    assert bridge.CODE_BATCH_NOT_ATTEMPTED in y.kodlar(), \
        "paketli yo'l NEGA urinilmagani JIMGINA tashlanmaydi"


# ═══ 0. DARVOZANING O'ZI: eskirgan yig'ma JIMGINA «ishlaydi» bo'lolmaydi ════════════════
def test_darvoza_ESKIRGAN_yigmani_ISHLAYDI_demaydi():
    """⚠️⚠️ TO'RTINCHI DARVOZADAGI AYNI TESHIK shu testda qadalgan: «eskirgan yig'ma
         uchiga-uch matritsadan JIMGINA o'tib ketolmasligi ISBOTLANSIN». Qaror jadvali
         `.exe` DAN MUSTAQIL o'lchanadi, ya'ni bu test Linux CI'da ham BAJARILADI va shu
         bois `ci_expected_skips.txt` da YO'Q.

    O'lchanadigan olti narsa:
      1. `TOZA` — yagona DAVOM etiladigan holat;
      2. `ESKIRGAN` / `ISBOTSIZ` / `YO_Q` — HAMMASI yiqilish matni beradi (`None` EMAS),
         ya'ni jim skip YO'Q va harness sababi (nomos modullar ro'yxati) SAQLANADI;
      3. `.exe` yo'qligi — Windows'da YIQILISH, boshqa platformada RATIFIKATSIYA qilingan
         skip, va skip matni `ci_expected_skips.txt` dagi sabab bo'lagini O'Z ICHIGA
         OLADI;
      4. SIMLASH: qaror jadvali mavjud bo'lib, `_dist_talab()` uni CHAQIRMASA, darvoza
         qog'ozda qolardi (o'lik gard);
      5. SABAB MATNINING AJRALGANLIGI: bu darvozaning skip sababi qolgan uchtasining
         BO'LAGI bo'lsa (yoki teskarisi), ro'yxatdan bitta yozuv yo'qolganda skip
         boshqasining qatoriga yashirinib o'tib ketardi;
      6. QAMROV: `.exe` ni YURGIZADIGAN HAR test darvozani chaqiradi. ⚠️ Bu AST
         tekshiruvi — yangi ssenariy qo'shilib darvoza chaqirilmasa, eskirgan artefakt
         SHU BITTA test orqali yana jimgina tasdiqlanardi.
    """
    PH = _harness()
    assert _yangilik_qarori(PH.HOLAT_TOZA, "", toza=PH.HOLAT_TOZA) is None, \
        "`TOZA` holat DAVOM etmadi — darvoza yolg'on qizil beradi"
    for holat in (PH.HOLAT_ESKIRGAN, PH.HOLAT_ISBOTSIZ, PH.HOLAT_YOQ):
        matn = _yangilik_qarori(holat, f"<SABAB:{holat}>", toza=PH.HOLAT_TOZA)
        assert matn is not None, \
            f"`{holat}` holati JIMGINA o'tib ketdi — UCHIGA-UCH darvozasi TESHIK"
        assert f"<SABAB:{holat}>" in matn, \
            f"`{holat}` yiqilish matnida harness sababi YO'Q: {matn}"

    assert _yoqlik_qarori(qurilishi_mumkin=True)[0] == _QAROR_YIQIL, \
        "yig'ma QURILADIGAN platformada `.exe` yo'qligi SKIP bo'lib qoldi"
    qaror, matn = _yoqlik_qarori(qurilishi_mumkin=False)
    assert qaror == _QAROR_SKIP, "yig'ma QURILMAYDIGAN platformada MUHIT skip'i yo'qoldi"
    assert _MUHIT_SABABI in matn, \
        f"skip matni `ci_expected_skips.txt` dagi sabab bo'lagini olmaydi: {matn}"

    # ⚠️ SIMLASH AST BILAN o'lchanadi, MATN qidiruvi bilan EMAS: `_chaqirilgan_nomlar()`
    #    docstringdagi eslatmani chaqiruv deb HISOBLAMAYDI (o'lchangan mutatsiya M2).
    chaqirilgan = _chaqirilgan_nomlar(_dist_talab)
    for chaqiruv in ("yigma_tayyorligi", "exe_qurish_mumkinmi", "_yangilik_qarori",
                     "_yoqlik_qarori", "_darvoza_AYNI_EXE_ni_olchasin"):
        assert chaqiruv in chaqirilgan, \
            f"`_dist_talab()` `{chaqiruv}` ni CHAQIRMAYDI — darvoza SIMLANMAGAN"

    # ⚠️ Sabab matnlari ARALASHMAYDI: hech biri boshqasining BO'LAGI emas, va bu
    #    moduldagi skip matni boshqa darvozalarning sababini O'Z ICHIGA OLMAYDI.
    from tests import test_agent_packaging as PKG
    from tests import test_agent_portability as PORT
    for begona in (PH.MUHIT_SABABI, PKG._MUHIT_SABABI, PORT._MUHIT_SABABI):
        assert begona != _MUHIT_SABABI, "to'rtinchi darvoza sababi BOSHQASI bilan AYNI"
        assert begona not in _MUHIT_SABABI and _MUHIT_SABABI not in begona, \
            (f"skip sabablari bir-birining BO'LAGI: `{_MUHIT_SABABI}` ↔ `{begona}` — "
             f"ro'yxatdan bitta yozuv yo'qolsa skip ikkinchisiga YASHIRINIB o'tardi")
        assert begona not in matn, \
            f"bu modulning skip matni BOSHQA darvozaning sababini o'z ichiga oldi: {begona}"

    # ⚠️ QAMROV (AST): `yurgiz()` ni ishlatgan HAR test `_dist_talab()` ni ham chaqirsin.
    daraxt = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    qamrovsiz = []
    for n in daraxt.body:
        if not (isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
            continue
        nomlar = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
        if "yurgiz" in nomlar and "_dist_talab" not in nomlar:
            qamrovsiz.append(n.name)
    assert not qamrovsiz, (
        f"`.exe` ni YURGIZADIGAN test darvozani CHAQIRMAYDI: {qamrovsiz} — eskirgan "
        f"artefakt shu testlar orqali jimgina tasdiqlanardi. `_dist_talab()` ni test "
        f"tanasining BIRINCHI qatoriga qo'ying va skip'ini `tests/ci_expected_skips.txt` "
        f"ga yozing.")


# ══════════════════════════════════════════════════════════════════════════════════════════
# A · KUZATILGAN PAPKA BO'SH -> ANIQ `FAILED_TIMEOUT` (CHEKSIZ KUTISH YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_A_bosh_papkada_yigma_ANIQ_timeout_paketini_qoldiradi(tmp_path):
    """Operator yig'uvchini hali yurgizmagan -> `.exe` KUTADI va CHEKLI vaqtda to'xtaydi.

    ⚠️ BO'SH PAPKA YIQILISH EMAS, u kutishning BOSHLANG'ICH holati — shu bois yakun
       «yig'uvchi javob bermadi» degan HUKM emas, `FAILED_TIMEOUT`.
    ⚠️ ENG MUHIM QISM: hech narsa topilmagan yurishda ham operator qo'lida UZATISHGA
       YAROQLI paket qoladi (`_umumiy_shartnoma` ichida HAQIQIY validator chaqiriladi).
    """
    _dist_talab()
    y = yurgiz(tmp_path, "A_bosh")
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)
    _yol_haqqoniyligi(y)

    assert y.yozuv()["state"] == st.FAILED_TIMEOUT
    assert bridge.CODE_WAIT_TIMEOUT in y.kodlar()
    assert y.paket_fayllar() == {}, \
        "paket OLINMAGAN yurishda `bundle/` BO'SH qoladi — bo'sh papka «paket bor» demaydi"
    # ── KUTISH KO'RINDI: jim turgan agent «osilgan» deb o'qiladi ─────────────────────────
    assert "kutilmoqda" in y.chiqish, "kutish OPERATOR EKRANIDA ko'rinishi SHART"
    # ── Bu mashinada 1C YO'Q, lekin kuzatish yo'li bu haqda HUKM CHIQARMAYDI ─────────────
    assert st.FAILED_NO_1C not in y.holatlar(), \
        "kuzatish yo'li 1C mavjudligi haqida hukm chiqarMAYDI — sabab BOSHQA qatlamda"


# ══════════════════════════════════════════════════════════════════════════════════════════
# B · BUZUQ `manifest.json` -> FAIL-CLOSED (tugallanish belgisi QABUL QILINMAYDI)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_B_buzuq_manifest_tugallanish_belgisi_sifatida_QABUL_QILINMAYDI(tmp_path):
    """Paketning qolgani TO'LIQ, `manifest.json` esa JSON EMAS -> «tayyor» DEYILMAYDI.

    ⚠️⚠️ NEGA BU ENG QIMMAT NUQSON BO'LARDI: `manifest.json` — YAGONA tugallanish belgisi
         (Phase 4 uni ENG OXIRIDA yozadi). Yarim yozilgan faylni «tayyor» deb hisoblash
         yig'uvchi HALI YOZIB TURGAN paketni o'qib, undan xulosa chiqarishga olib kelardi —
         ya'ni «qaralmadi» jimgina «yo'q» ga aylanardi.
    ⚠️ FAIL-CLOSED YO'NALISHI: belgi QABUL QILINMAYDI, demak yurish KUTADI va vaqt tugaydi.
       Validatorga UMUMAN yetib kelinmaydi — `VALIDATION` holati RO'YXATDA YO'Q.
    """
    _dist_talab()
    def qurish(p):
        M.paket_sog_lom(p)
        pathlib.Path(p, rb.MANIFEST_FILE).write_bytes(b"{ bu JSON emas")

    y = yurgiz(tmp_path, "B_buzuq", qurish)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)
    _yol_haqqoniyligi(y)

    assert y.yozuv()["state"] == st.FAILED_TIMEOUT
    assert bridge.CODE_WAIT_TIMEOUT in y.kodlar()
    assert st.VALIDATION not in y.holatlar(), \
        "buzuq belgi bilan VALIDATSIYAGA o'tilmaydi — paket «olindi» deb hisoblanmaydi"
    assert y.paket_fayllar() == {}, \
        "tayyor DEB HISOBLANMAGAN papka ko'chirilmaydi: yarim paket dalil sifatida ham olinmaydi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# C · `{}` MANIFEST -> TAYYOR EMAS (parse BO'LADI, lekin SHAKL yetmaydi)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_C_bosh_manifest_obyekti_TAYYOR_deb_hisoblanmaydi(tmp_path):
    """`manifest.json` IKKI BAYT `{}` -> JSON bo'lib o'qiladi, lekin «tayyor» DEMAYDI.

    ⚠️⚠️ B DAN ALOHIDA SSENARIY BO'LISHI SHART: B da fayl UMUMAN parse bo'lmaydi (ya'ni
         darvoza JSON o'quvchisining o'zi bo'lishi ham mumkin), bu yerda esa parse
         MUVAFFAQIYATLI va ildizi OBYEKT — demak rad etish qarorini FAQAT SHAKL tekshiruvi
         (`_manifest_minimal_shape`: `manifest_version` + bo'sh bo'lmagan `files`) chiqara
         oladi. Aynan shu shox bir vaqtlar YO'Q edi va ikki baytlik `{}` «tayyor» bo'lib
         o'tib ketardi.
    ⚠️ Fikstura HALOL va buni test O'ZI tekshiradi: aks holda ssenariy jimgina B ning
       nusxasiga aylanib qolardi va «shakl darvozasi» hech qachon o'lchanmasdi.
    """
    _dist_talab()
    def qurish(p):
        M.paket_sog_lom(p)
        pathlib.Path(p, rb.MANIFEST_FILE).write_bytes(b"{}")

    y = yurgiz(tmp_path, "C_bosh_manifest", qurish)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)

    xom = y.manba_baytlari()[rb.MANIFEST_FILE]
    assert isinstance(json.loads(xom.decode("utf-8")), dict), \
        "fikstura yaroqli JSON OBYEKT bo'lishi SHART (aks holda bu B ssenariysi bo'lardi)"

    assert y.yozuv()["state"] == st.FAILED_TIMEOUT
    assert bridge.CODE_WAIT_TIMEOUT in y.kodlar()
    assert st.VALIDATION not in y.holatlar(), "shakl yetmasa paket OLINMAYDI"
    assert y.paket_fayllar() == {}


# ══════════════════════════════════════════════════════════════════════════════════════════
# D · YAROQLI `PARTIAL` PAKET -> VALIDATOR KODI `2` HURMAT QILINADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_D_partial_paket_QISMLI_semantika_bilan_toxtaydi(tmp_path):
    """Baytlar to'g'ri, YURISH to'liq emas (`overall=PARTIAL`) -> quvur TO'XTAYDI.

    ⚠️⚠️ ENG NOZIK NUQTA: validatorning `2` kodi «yiqildi» EMAS, lekin «davom et» ham EMAS.
         Yarim yurishdan chiqarilgan xulosa TO'LIQ xulosaga O'XSHAB ketardi.
    ⚠️ `2` va `1` AJRALADI va bu YOZUVDA ko'rinadi: `BUNDLE_RUN_INCOMPLETE` («qayta
       YURGIZISH kerak») bilan `BUNDLE_INVALID` («qayta YIG'ISH kerak») BIR XIL NARSA EMAS.
    ⚠️ JARAYONNING chiqish kodi baribir `1` («yurish yiqildi»): validatorning ICHKI `2` kodi
       operator skriptiga YOZUV orqali yetadi. Uchta jarayon kodi (`0/1/2`) BOSHQA savolga
       javob beradi — ularni validator kodlari bilan tenglashtirish xato bo'lardi.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "D_partial", M.paket_oila_oqilmadi)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)
    _yol_haqqoniyligi(y)

    assert y.yozuv()["state"] == st.FAILED_VALIDATION
    assert "BUNDLE_RUN_INCOMPLETE" in y.kodlar()
    assert "BUNDLE_INVALID" not in y.kodlar(), \
        "to'liq bo'lmagan yurish «paketga ishonib bo'lmaydi» deb NOMLANMAYDI"
    assert P.EXIT_INCOMPLETE == "2" and P.EXIT_INVALID == "1", \
        "validator kodlari YADRODAN keladi va ikkisi ARALASHMAYDI"
    # ── Tahlil BAJARILMADI va bo'sh artefakt YOZILMADI ───────────────────────────────────
    assert st.ANALYSIS not in y.holatlar(), "kod 2 dan keyin tahlilga O'TILMAYDI"
    assert AI_CANDIDATES_FILE not in y.ildiz_fayllar(), \
        "tahlilsiz yurishda nomzodlar fayli YOZILMAYDI (bo'sh artefakt — yolg'on da'vo)"
    # ── TO'LIQ EMAS, lekin BUZUQ EMAS paket DALIL bo'lib saqlanadi ───────────────────────
    paket_run = json.loads(X.matn(str(y.natija_dir),
                                  f"{BUNDLE_SUBDIR}/{rb.RUN_STATUS_FILE}"))
    assert paket_run["overall"] == rb.OVERALL_PARTIAL, \
        "paketning O'Z hukmi `PARTIAL` bo'lib qoladi — agent uni «tuzatmaydi»"


# ══════════════════════════════════════════════════════════════════════════════════════════
# E · YAROQLI `SUCCESS` PAKET -> QUVUR OXIRIGACHA YURADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_E_success_paketida_quvur_OXIRIGACHA_yuradi(tmp_path):
    """Tugallanish belgisi to'liq va paket yaroqli -> HAMMA qadam bajariladi.

    ⚠️ BU TEST ISBOTLAYDI: yig'ilgan `.exe` ichida grafni quradigan, tahlil qiladigan va
       hisobot yozadigan modullar ROSTDAN bor. Yig'maga tushmay qolgan modul AYNAN shu yerda
       ko'rinardi — jarayon ichidagi testda esa u hech qachon ko'rinmaydi.
    ⚠️ BU TEST ISBOTLAMAYDI: yig'uvchining 1C da ishlashini — paket SINTETIK FIKSTURA.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "E_success", M.paket_sog_lom)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_OK)
    _yol_haqqoniyligi(y)

    assert y.yozuv()["state"] == st.COMPLETE
    for qadam in (st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS, st.REPORT, st.COMPLETE):
        assert qadam in y.holatlar(), f"`{qadam}` qadami bajarilmagan"
    assert AI_CANDIDATES_FILE in y.ildiz_fayllar(), "tahlil bo'lgan yurishda nomzodlar SHART"

    # ── PAKET BAYT-BA-BAYT KO'CHIRILGAN: agent uni «tahrirlamaydi» ───────────────────────
    assert y.paket_fayllar() == y.manba_baytlari(), \
        "paket AYNAN shu baytlar bilan ko'chiriladi (tahrir YO'Q)"
    # ── Yurish yozuvi papkada ROSTDAN turgan fayllarni sanaydi ──────────────────────────
    assert set(y.yozuv()["artifacts"]) == set(X.papka_baytlari(str(y.natija_dir))), \
        "yozuv yo'q narsani ham, kam ham sanamaydi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# F · SIRLI PAKET -> XAVFSIZ (MINIMAL, SIRSIZ) YIQILISH PAKETI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_F_sirli_paketda_sir_birorta_BAYTGA_yozilmaydi(tmp_path):
    """Yig'uvchi `errors.json` iga 1C ulanish satrini qo'ydi -> paket USHLAB QOLINADI.

    ⚠️⚠️ ENG QATTIQ ASSERT: sir qiymati natija OTA PAPKASINING birorta BAYTIDA ham yo'q —
         JSON, Markdown va kutilmagan fayl ham shu tekshiruvga tushadi.
    ⚠️ ASIMMETRIYA ATAYLAB: buzuq/to'liqsiz paket DALIL bo'lib saqlanadi (D), SIRLI paket esa
       SAQLANMAYDI — «dalilni saqlash» mijozning parolini tashqariga chiqarishni OQLAMAYDI.
    ⚠️ Sir SINTETIK (`M.SIR_ULANISH`) — hech kimning haqiqiy kredensiali EMAS.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "F_sir", M.paket_sir_oqqan)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)

    # ── EKRANDAGI HUKM va YOZUVDAGI HOLAT ATAYLAB BOSHQA — va bu IZOHDA aytiladi ────────
    # ⚠️⚠️ NOZIK JOY: ekranda yakun `FAILED_REPORT` («chiqish yozilmadi» — UI ning hukmi),
    #      yozuvda esa QUVURNING o'z terminal holati qoladi (`FAILED_VALIDATION`: sirli paket
    #      Phase 4 validatoridan ham o'tmaydi). Ikkisini tenglashtirish YOLG'ON bo'lardi —
    #      yozuv quvur BORGAN joyni, ekran esa PAKET YOZILMAGANINI aytadi. Farqning
    #      JIMGINA qolmasligi `SIR_USHLANDI_IZOH` bilan qulflanadi.
    assert f"xulosa: {st.FAILED_REPORT}" in y.chiqish, \
        "ekranda UI ning hukmi (`chiqish yozilmadi`) turadi"
    d = y.yozuv()
    assert d["state"] == st.FAILED_VALIDATION, \
        "yozuvda QUVURNING o'z terminal holati qoladi (sirli paket validatordan ham o'tmaydi)"
    assert agent_ui.SIR_USHLANDI_IZOH in d["notes"], \
        "ekran bilan yozuvning farqi IZOHDA OCHIQ aytiladi (jimgina qolmaydi)"
    assert agent_ui.CODE_SIR_USHLANDI in y.kodlar(), "sir topilgani NUQSON va yashirilmaydi"
    # ── MINIMAL PAKET: `bundle/` ham, nomzodlar ham QO'SHILMAYDI ─────────────────────────
    assert y.paket_fayllar() == {}, "sirning eng ehtimolli tashuvchisi paketga QO'SHILMAYDI"
    assert y.ildiz_fayllar() == set(rp.ALWAYS_FILES), \
        "minimal paketda AYNAN beshta ildiz artefakti bo'ladi"

    # ── SIR HECH QAYERDA: natija OTA papkasining HAMMA bayti tekshiriladi ───────────────
    yozilgan = y.hamma_bayt()
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat.encode("utf-8") not in yozilgan, \
            f"sir YOZILGAN baytlarda qoldi: {qiymat}"
        assert qiymat not in y.ekran, f"sir OPERATOR EKRANIDA qoldi: {qiymat}"
    assert "[REDACTED]" in y.ekran, "qiymat YASHIRILMADI, ALMASHTIRILDI"

    # ── Operator QAYSI faylni ko'rishini biladi (qiymatni esa KO'RMAYDI) ───────────────
    sabab = y.sabab(agent_ui.CODE_SIR_USHLANDI)
    assert f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}" in sabab, \
        "HAQIQIY topilgan joy NOMLANADI — operator shu faylni ko'radi"
    assert "USHLAB QOLINDI" in sabab, "butun paket ushlab qolingani ham AYTILADI"
    # ⚠️⚠️ YIG'MA BILAN TOPILGAN NOZIKLIK (yashirilmaydi, lekin DA'VO ham qilinmaydi):
    #      HAQIQIY mashinada bu ro'yxatga `environment.json` ham tushadi. Sabab: 1C YO'Q
    #      mashinada muhit hujjati `registry:HKLM\SOFTWARE\1C\1Cv8: kalit yo'q` izohlarini
    #      yozadi va ularning JSON-qochirilgan shakli (`HKLM\\SOFTWARE\\...`) sir skanerining
    #      `unc_path` naqshiga MOS keladi — ya'ni bu YOLG'ON IJOBIY. Loyiha bu yo'nalishni
    #      ATAYLAB tanlagan («yolg'on ijobiy — bir marta qo'lda ko'rish; yolg'on salbiy —
    #      mijozning paroli tarqaladi»), shu bois test ro'yxatning TO'LIQ TENGLIGINI talab
    #      QILMAYDI — faqat HAQIQIY joy nomlanishini va sir yozilmasligini qulflaydi.
    #      ⚠️ Jarayon ichidagi `test_agent_e2e_watch_folder.py::test_G2_...` esa «toza
    #         artefakt ro'yxatda YO'Q» deb qulflangan va u O'TADI, chunki uning fiksturasi
    #         1C ni TOPILGAN deb ko'rsatadi — bunda registr izohlari UMUMAN yozilmaydi.
    #         Ikki da'vo ZID emas, lekin ularning SHARTI boshqa va buni yozib qo'yish kerak.

    # ── MANBA papka O'ZGARMAGAN: agent faqat-o'qish chegarasidan chiqmaydi ──────────────
    assert any(M.SIR_QIYMATLAR[0].encode("utf-8") in b
               for b in y.manba_baytlari().values()), \
        "agent OPERATOR papkasini TOZALAMAYDI — «sir yo'q» da'vosi AGENT YOZGAN baytlar haqida"


# ══════════════════════════════════════════════════════════════════════════════════════════
# G · NOANIQ NOMZOD -> `AMBIGUOUS`, IKKALA NOMZOD KO'RSATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_G_noaniq_nomzodda_IKKALASI_ham_korsatiladi(tmp_path):
    """Ikki teng kuchli nomzod -> tanlash EMAS, IKKILANISHNI AYTISH.

    ⚠️ JIMGINA BITTASINI TANLASH — eng qimmat xato: operator xaritani tasdiqlangan deb
       o'qiydi va ko'chirish noto'g'ri katalogdan ketadi.
    ⚠️ BALL QULFLANMAYDI (evristika o'zgarishi nuqson emas). Qulflanadigani: status
       `AMBIGUOUS`, ikkala nomzod DISKDAGI artefaktda ham, HISOBOTDA ham ko'rinadi, tasdiq
       TALAB qilinadi va `VERIFIED` so'zi hisobotda UMUMAN yo'q.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "G_noaniq",
               lambda p: M.yoz(p, M.baytlar(metadata=S.config("J"))))
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_OK)
    assert y.yozuv()["state"] == st.COMPLETE

    korik = json.loads(X.matn(str(y.natija_dir), AI_CANDIDATES_FILE))
    mahsulot = [c for c in korik["candidates"] if c["concept"] == "product"]
    assert len(mahsulot) >= 2, "ikki teng nomzod IKKI qator bo'lib ko'rinadi"
    assert {c["status"] for c in mahsulot} == {ai.STATUS_AMBIGUOUS}, \
        "teng ballda bittasi tanlab OLINMAYDI"

    osn = "Справочник.ТоварыОсновные"
    dop = "Справочник.ТоварыДополнительные"
    assert {c["candidate_object"] for c in mahsulot} == {osn, dop}
    for qator in mahsulot:
        sabab = " ".join(qator["ambiguity"])
        assert osn in sabab and dop in sabab, "ikkilanish IKKALA nomzodni NOMLAYDI"
        assert qator["required_confirmation"], "tasdiq TALAB qilinadi"

    matn = y.hisobot()
    assert osn in matn and dop in matn, "operator IKKALASINI ham ko'rishi kerak"
    assert not rb.VERIFIED_WORD_RE.findall(matn), "`VERIFIED` so'zi hisobotda UMUMAN YO'Q"
    assert {c["status"] for c in korik["candidates"]} <= set(ai.AI_STATUSES), \
        "hamma daraja AI lug'atidan — `HUMAN_CONFIRMED` ham, `VERIFIED` ham yo'q"


# ══════════════════════════════════════════════════════════════════════════════════════════
# H · `VERIFIED` -> RAD
# ⚠️⚠️ ANALITIK KANALIGA YIG'MA ORQALI YETIB BO'LMAYDI va bu JIMGINA o'tkazilmaydi: H1 —
#      yig'ma orqali YETILADIGAN darvoza, H2 — yetib bo'lmasligining ISBOTI va manba
#      darajasidagi isbotga HAVOLA.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_H1_paketdagi_VERIFIED_davosi_yigma_orqali_RAD_etiladi(tmp_path):
    """Yig'uvchi o'z hujjatida `VERIFIED` yozdi -> paket RAD, quvur TO'XTAYDI.

    ⚠️ BU AI KANALI EMAS, YIG'UVCHI KANALI — lekin TAQIQ AYNI: `VERIFIED` darajasini na
       model, na yig'uvchi, na quvurning o'zi chiqara oladi (`ai.FORBIDDEN_STATUS`). Yig'ma
       orqali YETIB BORILADIGAN darvoza shu, shu bois u YIG'MA bilan qulflanadi
       (`runtime_bundle` ning `yiguvchidan_verified_yoq` tekshiruvi).
    ⚠️⚠️ FIKSTURA ATAYLAB XESH-BUTUN: so'z manifest QURILISHIDAN OLDIN qo'yiladi, ya'ni xesh
         MOS keladi va rad etishning SABABI AYNAN provenans darvozasi bo'ladi. Aks holda test
         o'zi buzgan xeshni o'lchab, «darvoza ishladi» degan XATO xulosa chiqarardi — shu
         bois xesh/hajm nuqsonining YO'QLIGI ham ANIQ tekshiriladi.
    """
    _dist_talab()
    xulosa = M.SUMMARY_MD + "\nYig'uvchining o'z xulosasi: VERIFIED\n"
    y = yurgiz(tmp_path, "H1_verified", lambda p: M.yoz(p, M.baytlar(summary=xulosa)))
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)

    assert y.yozuv()["state"] == st.FAILED_VALIDATION
    assert "BUNDLE_INVALID" in y.kodlar(), "provenans da'vosi paketni ISHONCHSIZ qiladi"
    sabab = y.sabab("BUNDLE_INVALID")
    assert "yiguvchidan_verified_yoq" in sabab, \
        "rad etish SABABI aynan provenans darvozasi bo'lishi SHART (xesh/shakl EMAS)"
    assert "sha256" not in sabab and "bayt hajmi" not in sabab, \
        "fikstura xesh-butun: rad etish BOSHQA darvozaga tegmaydi"
    assert st.ANALYSIS not in y.holatlar(), "rad etilgan paketdan XULOSA chiqarilmaydi"
    assert AI_CANDIDATES_FILE not in y.ildiz_fayllar()
    # ── Hisobotning O'ZIDA so'z YO'Q: agent hech narsani tasdiqlamaydi ──────────────────
    assert not rb.VERIFIED_WORD_RE.findall(y.hisobot()), \
        "agent hisobotida `VERIFIED` so'zi HECH QACHON bo'lmaydi"


def test_H2_analitik_kanalini_yigma_orqali_ALMASHTIRIB_bolmaydi(tmp_path):
    """⚠️⚠️ YETIB BO'LMAGAN SSENARIY — OCHIQ YOZILADI, jimgina o'tkazilmaydi.

    `VERIFIED` ni ANALITIK KANALIDAN sinash analitikni almashtirishni talab qiladi. Yig'ilgan
    `.exe` da bunga YO'L YO'Q va bu test AYNAN SHUNI isbotlaydi:
      1. buyruq satrida analitikni almashtiradigan BAYROQ yo'q (`--help` ning O'ZIDAN
         o'qiladi, hujjatdan emas);
      2. yagona almashtirish nuqtasi — `__main__.main` ning kalit-so'zli `analyzer`
         parametri, ya'ni FAQAT jarayon ichida chaqiriladigan Python API;
      3. demak bu darvozani YIG'MA orqali o'lchash MUMKIN EMAS.

    MANBA DARAJASIDAGI ISBOT (bu yerda TAKRORLANMAYDI — ikki haqiqat bo'lardi):
      · `tests/test_agent_e2e_watch_folder.py::test_I_analitik_VERIFIED_bermoqchi_bolsa_
        yurish_RAD_etiladi` — analitik `VERIFIED` qaytarsa yurish `FAILED_ANALYSIS`;
      · `app/services/discovery_1c/ai.py::validate_analysis` — `FORBIDDEN_STATUS` darvozasi;
      · `app/services/discovery_1c/analyst/heuristics.py::_assert_allowed_status` — lokal
        analitik bu darajani KODDA chiqara olmaydi.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "H2_help", argv_quruvchi=lambda k, o: ["--help"])
    assert y.kod == agent_main.EXIT_OK, "`--help` operator so'ragan narsa — kod 0"
    assert "Traceback (most recent call last)" not in y.ekran
    assert y.papkalar == [], "`--help` natija papkasi QURMAYDI"

    past = y.chiqish.lower()
    for taqiq in ("analyzer", "analitik", "ai", "status", "confidence"):
        assert f"--{taqiq}" not in past, \
            f"yig'mada analitik/daraja kanalini ochadigan bayroq PAYDO BO'LDI: --{taqiq}"
    # ── Yagona almashtirish nuqtasi — jarayon ICHIDAGI API ──────────────────────────────
    param = inspect.signature(agent_main.main).parameters
    assert "analyzer" in param and param["analyzer"].kind is inspect.Parameter.KEYWORD_ONLY, \
        "analitik faqat Python chaqiruvi bilan almashtiriladi (buyruq satri bilan EMAS)"
    assert ai.FORBIDDEN_STATUS == "VERIFIED", "taqiqlangan daraja nomi YADRODAN keladi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# I · `HUMAN_CONFIRMED` -> RAD
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_I1_paketdagi_ODAM_TASDIGI_dalili_yigma_orqali_RAD_etiladi(tmp_path):
    """Yig'uvchi `human_confirmed` dalilini DA'VO qildi -> paket RAD.

    ⚠️⚠️ NEGA H1 DAN ALOHIDA: `HUMAN_CONFIRMED` — QONUNIY daraja, lekin FAQAT BOSHQA
         KANALDAN (operatorning alohida tasdiq hujjati). Yig'uvchidan kelgan `human_confirmed`
         esa YOLG'ON PROVENANS bo'lardi: mashina chiqargan taxmin odamning qaroriga aylanib
         qolardi. `VERIFIED` esa HECH QAYSI kanalda bo'lmaydi — ikki taqiq bir xil EMAS.
    ⚠️ Darvoza darajaning NOMINI emas, DALIL TURINI to'sadi (`STRONG_EVIDENCE_KINDS`): yuzta
       `name_match` ham bitta `human_confirmed` o'rnini bosmaydi.
    """
    _dist_talab()
    tur = "human_confirmed"
    assert tur in rb.STRONG_EVIDENCE_KINDS, "dalil turi YADRODAN olinadi, qo'lda yozilmaydi"
    xulosa = M.SUMMARY_MD + f"\nYig'uvchining dalil turi: {tur}\n"
    y = yurgiz(tmp_path, "I1_human", lambda p: M.yoz(p, M.baytlar(summary=xulosa)))
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)

    assert y.yozuv()["state"] == st.FAILED_VALIDATION
    assert "BUNDLE_INVALID" in y.kodlar()
    sabab = y.sabab("BUNDLE_INVALID")
    assert tur in sabab and "KUCHLI dalil" in sabab, \
        "rad etish sababi AYNAN kuchli dalil taqiqi bo'lishi SHART"
    assert "sha256" not in sabab and "bayt hajmi" not in sabab, \
        "fikstura xesh-butun: rad etish BOSHQA darvozaga tegmaydi"
    assert st.ANALYSIS not in y.holatlar()
    assert AI_CANDIDATES_FILE not in y.ildiz_fayllar(), \
        "rad etilgan paketdan «odam tasdiqlagan» artefakt QOLMAYDI"


def test_I2_odam_tasdigi_AI_lugatida_UMUMAN_yoq():
    """⚠️⚠️ YETIB BO'LMAGAN SSENARIY — OCHIQ YOZILADI (H2 bilan AYNI sabab).

    `HUMAN_CONFIRMED` ni AI KANALIDAN sinash analitikni almashtirishni talab qiladi, yig'ma
    esa bunga yo'l bermaydi (isboti — `test_H2_...`). Bu yerda qulflanadigan narsa AJRIMNING
    O'ZI: daraja QONUNIY lug'atda BOR, AI lug'atida esa YO'Q, va quvur `allow_human_confirmed`
    bayrog'ini UZATMAYDI — ya'ni qaror KODDA turadi, nasrda emas.

    MANBA DARAJASIDAGI ISBOT (takrorlanmaydi):
      · `tests/test_agent_e2e_watch_folder.py::test_J_AI_kanalidan_HUMAN_CONFIRMED_RAD_etiladi`;
      · `app/services/discovery_agent/pipeline.py::_Run.step_analysis`.
    """
    assert ai.STATUS_HUMAN_CONFIRMED in ai.STATUSES, "daraja QONUNIY lug'atda bor"
    assert ai.STATUS_HUMAN_CONFIRMED not in ai.AI_STATUSES, "AI lug'atida esa YO'Q"
    manba = inspect.getsource(P._Run.step_analysis)
    assert "validate_analysis" in manba, "tahlil qadami yadroning validatorini chaqiradi"
    assert "allow_human_confirmed=True" not in manba, \
        "`step_analysis` bu bayroqni UZATMASLIGI SHART (AI kanali odam tasdig'ini bermaydi)"


# ══════════════════════════════════════════════════════════════════════════════════════════
# J · YAROQLI NORMAL OQIM -> `COMPLETE` va CHIQISH KODI `0`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_J_normal_oqimda_COMPLETE_va_chiqish_kodi_NOL(tmp_path):
    """OPERATORNING ODDIY YURISHI: bayroq eng kam, vaqt tamg'asi HAQIQIY SOATDAN.

    ⚠️ E DAN FARQI: bu yerda `--timestamp` BERILMAYDI, ya'ni natija papkasining nomini agent
       O'ZI (haqiqiy UTC soatdan) quradi. Shu bois bu test `0` kodini TAKRORLAMAYDI — u
       operator ROSTDAN yozadigan buyruqni o'lchaydi va soat qatlami (`ui.utc_now`) yig'mada
       ishlashini, papka nomi/ichki vaqtlar quvurni buzmasligini qulflaydi.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "J_normal", M.paket_sog_lom, tamga=None)
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_OK)

    assert y.natija_dir is not None
    assert y.natija_dir.name != NATIJA_NOMI, \
        "tamg'a BERILMAGANDA nom haqiqiy soatdan keladi (qotib qolgan nom EMAS)"
    d = y.yozuv()
    assert d["state"] == st.COMPLETE and d["terminal"] == "true"
    assert d["read_only"] == "true", "agent FAQAT-O'QISH bo'lib qoladi"
    assert AI_CANDIDATES_FILE in y.ildiz_fayllar()
    assert st.COMPLETE in y.chiqish, "operator YAKUNNI ekranda ko'radi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# CHIQISH KODI `2` — «YURISH BOSHLANMADI» (`1` DAN AJRATILGAN)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_kuzatiladigan_papka_YOQ_bolsa_kod_2_va_papka_YOZILMAYDI(tmp_path):
    """`--headless` papkasi yo'q -> kod `2`, natija papkasi QURILMAYDI.

    ⚠️⚠️ BU `1` DAN ATAYLAB AJRALGAN va «yiqilishda ham paket qoladi» qoidasiga ZID EMAS:
         `1` — YURISH yiqildi (demak aytishga gap bor va paket qoladi), `2` — yurish
         BOSHLANMADI (buyruq xatosi: hali hech narsa o'lchanmagan, demak hisobot qilish uchun
         ham narsa yo'q). Ikkisini bitta kodga qo'shish operator skriptini chalg'itardi.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "K_papka_yoq", kuzatilgan_yaratilsin=False)

    assert y.kod == agent_main.EXIT_CANNOT_RUN, "«yurish boshlanmadi» kodi AYNAN 2"
    assert "Traceback (most recent call last)" not in y.ekran
    assert y.papkalar == [], \
        "yurish BOSHLANMAGANDA natija papkasi qurilmaydi (bo'sh hisobot — yolg'on da'vo)"
    assert y.xato.strip(), "sabab `stderr` da ANIQ aytiladi"


def test_wait_seconds_nol_bolsa_CHEKSIZ_kutish_EMAS_kod_2(tmp_path):
    """`--wait-seconds 0` -> yurish BOSHLANMAYDI (`2`), «cheksiz kut» DEGANI EMAS.

    ⚠️ FAIL-OPEN BO'LARDI: nol yoki manfiy chegarani «cheksiz» deb o'qish agentni mijoz
       mashinasida abadiy qoldirardi. Agentda cheksiz kutish UMUMAN mavjud emas.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "L_nol", kutish="0")

    assert y.kod == agent_main.EXIT_CANNOT_RUN
    assert "Traceback (most recent call last)" not in y.ekran
    assert y.papkalar == []
    assert y.xato.strip(), "sabab `stderr` da ANIQ aytiladi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# KONSOL KODLASHI — HAQIQIY (YIG'MA BILAN TOPILGAN) NUQSONNING QULFI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_cp1252_quvurda_chiqish_yurishni_BUZMAYDI_va_belgilar_YOQOLMAYDI(tmp_path):
    """⚠️⚠️ BU TEST HAQIQIY, YIG'MANI YURGIZIB TOPILGAN NUQSONNI QULFLAYDI.

    NUQSON SHUNDAY EDI: operator matnlarida `cp1252` ga SIG'MAYDIGAN belgilar bor (`⚠`
    U+26A0, variatsiya selektori, `═`, `─`, kirill harflar). Windows'da chiqish QUVURGA
    yo'naltirilganda `sys.stdout.encoding` `cp1252` bo'ladi va chop etish
    `UnicodeEncodeError` berardi — yurish AYNAN CHOP ETISH paytida uzilib, NATIJA PAKETI
    UMUMAN YOZILMASDI. Ya'ni brief §2 ning kafolati («operator hech qachon hech narsasiz
    qolmasin») HAQIQIY konsolda buzilardi.

    ⚠️ TO'PLAM BUNI KO'RMAGAN: `pytest` chiqishni UTF-8 bilan ushlaydi. Shu bois bu test
       chiqishni QUVURGA oladi va muhitdan `PYTHONIOENCODING` ni OLIB TASHLAYDI (`_muhit`).

    UCH DA'VO BIRGALIKDA IKKI QATLAMNI ham o'lchaydi:
      1. yurish TUGADI va chiqish kodi shartnomada (`1`) — chop etish uzilmadi;
      2. natija papkasi YOZILDI va HAQIQIY validatordan o'tdi;
      3. `stdout` QAT'IY UTF-8 bo'lib dekodlanadi va belgilar ROSTDAN joyida — ya'ni
         birinchi qatlam (`_utf8ga_otkaz`) ishladi va belgilar YO'QOLMADI.
         ⚠️ Faqat ikkinchi qatlam (`_XavfsizOqim`) qolsa, belgi `?` ga almashardi va 3-da'vo
            tutadi; IKKISI ham yo'qolsa, 1-da'vo tutadi.
    """
    _dist_talab()
    y = yurgiz(tmp_path, "M_kodlash")
    _umumiy_shartnoma(y, kutilgan_kod=agent_main.EXIT_FAILED_RUN)

    qatiy = y.stdout_baytlari.decode("utf-8")      # ⚠️ `errors=` YO'Q: QAT'IY dekodlash
    assert OGOHLIK_BELGISI in qatiy, \
        "`⚠` belgisi YO'QOLDI — chiqish `cp1252` ga tushirilgan (belgilar almashtirilgan)"
    assert "kutilmoqda" in qatiy, "kutish qatori ham chop etildi"
    assert "xulosa:" in qatiy, "chop etish OXIRIGACHA bordi (yarim yo'lda uzilmadi)"
    # ⚠️ Kirill ham tekshiriladi: operator qadamlarida 1C funksiyasining nomi turadi.
    assert "Разведку" in qatiy, "kirill matn ham yo'qolmasligi SHART"
