# -*- coding: utf-8 -*-
"""YIG'MA XAVFSIZLIGI (§10) — KODLASH tuzatishini va «yashirin xulq YO'Q» da'vosini QULFLAYDI.

⚠️⚠️ BU FAYL NEGA MAVJUD — ikki DARVOZA, ikkisi ham boshqa joyda O'LCHANMAYDI:

(A) KODLASH TUZATISHI (`__main__._utf8ga_otkaz` + `__main__._XavfsizOqim`).
    Topilgan HAQIQIY nuqson: operator matnlarida `cp1252` ga SIG'MAYDIGAN belgilar bor
    (`⚠` U+26A0, `═`, `─`, kirill). Windows'da chiqish quvurga/faylga yo'naltirilganda
    `sys.stdout.encoding` `cp1252` bo'ladi va chop etish `UnicodeEncodeError` berardi —
    natijada yurish CHOP ETISH paytida uzilib, NATIJA PAPKASI UMUMAN YOZILMASDI.
    ⚠️ Mavjud to'plam buni TUTMAGAN, chunki pytest chiqishni UTF-8 bilan ushlaydi.
    ⚠️⚠️ VA YIG'ILGAN `.exe` DA HAM O'LCHAB BO'LMAYDI: `.exe` ni `PYTHONIOENCODING=cp1252`
         bilan yurgizsangiz, QATLAM 1 (`reconfigure` -> UTF-8) DOIM muvaffaqiyat qozonadi,
         demak QATLAM 2 (`_XavfsizOqim`) umuman CHAQIRILMAYDI va u SINALMAGAN qolardi.
         Shu bois qatlam 2 AYNAN SHU YERDA — `reconfigure` ni BERMAYDIGAN yoki UNI
         YIQITADIGAN oqim bilan — o'lchanadi. Ikki qatlam IKKI xil test talab qiladi.

(B) «YASHIRIN XULQ YO'Q» STATIK DARVOZASI (§10.2–§10.7): avtoyuklanish, Windows xizmati,
    rejalashtirilgan vazifa, reestrga YOZISH, o'zboshimcha `powershell`/`cmd.exe` va
    `shell=True`. Bu da'volar `__main__.py`/`detector.py`/spec DOCSTRINGLARIDA yozilgan —
    docstring esa DARVOZA EMAS. Bu fayl ularni KOD ustida tekshiradi.

⚠️ BU FAYL HAQIQIY 1C ISBOTI EMAS: 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI, tarmoq
   ISHLATILMAYDI. Muhit skaneri SINTETIK (`agent_scenario_mock`), kuzatilgan papka BO'SH.

⚠️ BU FAYL REESTRGA YOZMAYDI va HAQIQIY `%APPDATA%` ga TEGMAYDI: hamma yozuv `tmp_path`
   ichida qoladi. Statik tekshiruvlar faqat MANBA MATNINI o'qiydi.

⚠️⚠️ BESHINCHI DARVOZA, AYNI TESHIK (2026-10-02 da tuzatildi): bu fayl ilgari (a) yig'ma
     papkasini QO'LDA `C:/Users/Developer/binos-agent-build/...` deb yozardi — ya'ni
     `BINOS_AGENT_BUILD_ROOT` ni UMUMAN o'qimasdi va qolgan darvozalar bilan jimgina
     BOSHQA yig'mani tekshirishi mumkin edi; (b) `.exe` yo'q bo'lsa SHARTSIZ `skip`
     berardi (`_yigma_yoq`) — platformaga bog'liq EMAS va YANGILIK tekshiruvi YO'Q;
     (c) o'sha uch skip `tests/ci_expected_skips.txt` da UMUMAN YO'Q edi, ya'ni HAQIQIY
     Linux CI'da 3 ta «KUTILMAGAN skip» backend job'ni QIZIL qilardi. Beshinchisining
     amaliy oqibati: bu modul tarqatiladigan `.exe` BAYTLARI ustida da'vo qiladi
     («qobiq/persistence izi YO'Q», «tarmoqqa qodir fayllar ro'yxati O'SMADI», «UPX
     YO'Q»), eskirgan artefaktda esa bu da'volar YOLG'ON — o'lchangan holat `22 passed`
     (yig'ma uch moduldan eskirgan, qarang `packaging/BUILD_GATE.md` §2).
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import os
import pathlib
import re
import sys
import textwrap

import pytest

from app.services.discovery_agent import __main__ as M
from app.services.discovery_agent import states as st
from tests import agent_scenario_mock as X

# ══════════════════════════════════════════════════════════════════════════════════════════
# YO'LLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `app/services/discovery_agent/` — agentning O'Z manbasi.
_AGENT_DIR = pathlib.Path(M.__file__).resolve().parent
#: `apps/server` — harness yo'lini hisoblash uchun ildiz.
_SERVER = pathlib.Path(__file__).resolve().parents[1]
#: Yig'ma REPO TASHQARISIDA quriladi (repo daraxti toza qolishi uchun).
#: ⚠️⚠️ ILDIZ QO'LDA YOZILMAYDI. U qolgan darvozalar bilan AYNI muhit o'zgaruvchisidan
#:      keladi; BESH modulning tengligi `tests/test_agent_build_inventory.py` dagi
#:      `test_BESH_modulda_yigma_ILDIZI_AYNI` bilan QULFLANGAN.
_YIGMA_ILDIZ = pathlib.Path(os.environ.get("BINOS_AGENT_BUILD_ROOT")
                            or pathlib.Path.home() / "binos-agent-build")
_DIST = _YIGMA_ILDIZ / "dist-onedir" / "BinOSDiscoveryAgent"
_EXE = _DIST / "BinOSDiscoveryAgent.exe"

#: Yurishning YAGONA tamg'asi — soat O'QILMAYDI (determinizm).
_TAMGA = "20261001T090000Z"


def _agent_manbalari() -> list[pathlib.Path]:
    """Agentning HAMMA `.py` fayli. ⚠️ Ro'yxat DISKDAN olinadi, testga YOZILMAYDI: yangi
    modul qo'shilsa u ham AVTOMATIK darvoza ostiga tushadi."""
    fayllar = sorted(p for p in _AGENT_DIR.glob("*.py"))
    assert fayllar, f"agent manbasi topilmadi: {_AGENT_DIR}"
    return fayllar


def _izohsiz(matn: str) -> str:
    """Satr oxiridagi `#` izohlarini OLIB TASHLAYDI.

    ⚠️ NEGA KERAK: bu loyihada docstring va izohlar QASDAN `shell=True`, `powershell`,
       `schtasks` kabi so'zlarni ESLATADI («bu YO'Q» deb tushuntirish uchun). Darvoza
       IZOHNI emas, BAJARILADIGAN KODNI o'lchashi kerak — aks holda u o'z hujjatidan
       yiqilardi va odamlar uni o'chirib tashlashga majbur bo'lardi.
    ⚠️ Docstringlar ham olib tashlanadi (pastdagi `_KOD_FAQAT`).
    """
    return "\n".join(satr.split("#", 1)[0] for satr in matn.splitlines())


#: Uch qo'shtirnoqli bloklar (docstring) — ular ham IZOH, kod emas.
_DOCSTRING_RE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')


def _KOD_FAQAT(p: pathlib.Path) -> str:
    """Faylning BAJARILADIGAN qismi: docstring va `#` izohlari OLIB TASHLANGAN."""
    return _izohsiz(_DOCSTRING_RE.sub('""', p.read_text(encoding="utf-8")))


# ══════════════════════════════════════════════════════════════════════════════════════════
# SOXTA OQIMLAR — KODLASHNI MAJBURLAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
class QatiyOqim:
    """`encoding` ANIQ bo'lgan matn oqimi: sig'maydigan belgi `UnicodeEncodeError` beradi.

    ⚠️ `reconfigure` ATAYLAB YO'Q (`AttributeError`): shu tufayli QATLAM 1 jim o'tib ketadi
       va QATLAM 2 (`_XavfsizOqim`) SINALADI. Haqiqiy konsol oqimida `reconfigure` bor, shu
       bois `.exe` da qatlam 2 ga umuman yetib borilmaydi — bu sinf aynan shu bo'shliqni
       yopadi.
    ⚠️ `write` HECH NARSA YOZMAYDI, agar kodlash yiqilsa: haqiqiy `TextIOWrapper` ham
       butun satrni OLDIN kodlaydi, demak yarim yozuv bo'lmaydi.
    """

    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self._bolaklar: list[str] = []
        self.flush_soni = 0

    def write(self, s: str) -> int:
        s.encode(self.encoding)        # QAT'IY: sig'masa UnicodeEncodeError
        self._bolaklar.append(s)
        return len(s)

    def flush(self) -> None:
        self.flush_soni += 1

    @property
    def matn(self) -> str:
        return "".join(self._bolaklar)


class OtkazadiganOqim(QatiyOqim):
    """QATLAM 1 ISHLAYDIGAN oqim: `reconfigure` UTF-8 ga o'tkazadi va belgilar SAQLANADI."""

    def reconfigure(self, *, encoding: str | None = None, errors: str | None = None) -> None:
        if encoding:
            self.encoding = encoding


class OtkazmaydiganOqim(QatiyOqim):
    """QATLAM 1 YIQILADIGAN oqim: `reconfigure` istisno tashlaydi (qulflangan konsol)."""

    def reconfigure(self, *, encoding: str | None = None, errors: str | None = None) -> None:
        raise OSError("bu oqimni qayta sozlab bo'lmaydi")


class FlushYiqiladiganOqim(QatiyOqim):
    """`flush` YIQILADIGAN oqim — yopilgan quvur. Chop etish buni YUTISHI kerak."""

    def flush(self) -> None:
        raise ValueError("oqim yopilgan")


def _yurgiz(tmp_path, out, err, *, kutish: str = "6"):
    """`main()` ni BO'SH kuzatilgan papka bilan OXIRIGACHA yuritadi.

    ⚠️ Hamma tashqi bog'liqlik ALMASHTIRILGAN: muhit SINTETIK, soat va `sleeper` KIRISHDAN
       (`agent_scenario_mock`), demak HAQIQIY vaqt kutilmaydi va mashinaning holati
       natijaga ta'sir qilmaydi.
    ⚠️ Bo'sh papka -> `FAILED_TIMEOUT` -> chiqish kodi `1`. Bu «yurish yiqildi», lekin
       PAKET baribir QOLISHI kerak — aynan shu kafolat kodlash nuqsonida buzilgan edi.
    """
    kuzatilgan = tmp_path / "kuzatilgan"
    kuzatilgan.mkdir()
    ota = tmp_path / "natija"
    ota.mkdir()
    # ⚠️ `scan` — CHAQIRUV, tayyor natija EMAS: `UiModel.refresh_environment` uni
    #    `self.scan()` deb chaqiradi (muhitni qayta skanerlash imkoniyati shundan).
    kod = M.main(["--headless", str(kuzatilgan), "--result-dir", str(ota),
                  "--wait-seconds", kutish, "--timestamp", _TAMGA],
                 out=out, err=err,
                 scan=lambda: X.muhit_1c_yoq(), clock=X.oshuvchi_soat(),
                 sleeper=X.yozib_oluvchi_uyqu([]))
    papkalar = sorted(p for p in ota.iterdir() if p.is_dir())
    return kod, papkalar


def _besh_artefakt(papkalar) -> set[str]:
    """Natija papkasining ILDIZ fayllari. ⚠️ AYNAN bitta papka kutiladi."""
    assert len(papkalar) == 1, f"AYNAN bitta natija papkasi kutilgan edi: {papkalar}"
    return {p.name for p in papkalar[0].iterdir() if p.is_file()}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. KODLASH TUZATISHI — QATLAM 2 (`_XavfsizOqim`)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Uch kodlash ATAYLAB: `cp1252` (Windows-G'arb, nuqson TOPILGAN joy), `cp866`
#: (Windows konsolining eski kirill kodlashi) va `ascii` (eng yomon holat — deyarli
#: HAMMA operator belgisi sig'maydi). Agent uchtasida ham YURISHNI TUGATISHI kerak.
_KODLASHLAR = ("cp1252", "cp866", "ascii")


@pytest.mark.parametrize("kodlash", _KODLASHLAR)
def test_sigmaydigan_kodlashda_yurish_YIQILMAYDI_va_paket_YOZILADI(tmp_path, kodlash):
    """⚠️⚠️ TOPILGAN NUQSON QULFI: chiqish oqimi `⚠` ni ko'tarmasa ham yurish OXIRIGACHA
    boradi va operator qo'lida BESH artefaktli paket QOLADI.

    Nuqson bor edi: `print` `UnicodeEncodeError` berib yurishni UZIB tashlardi va natija
    papkasi UMUMAN yozilmasdi — ya'ni «operator hech qachon hech narsasiz qolmasin»
    kafolati HAQIQIY konsolda buzilardi.
    """
    out = QatiyOqim(kodlash)
    err = QatiyOqim(kodlash)
    kod, papkalar = _yurgiz(tmp_path, out, err)
    assert kod == M.EXIT_FAILED_RUN, (
        f"bo'sh papka `{st.FAILED_TIMEOUT}` -> chiqish kodi 1 bo'lishi kerak, kelgani {kod}")
    fayllar = _besh_artefakt(papkalar)
    assert len(fayllar) == 5, (
        f"`{kodlash}` oqimida natija paketi TO'LIQ yozilmadi: {sorted(fayllar)}")
    assert out.matn, "operator ekraniga HECH NARSA chiqmadi"


@pytest.mark.parametrize("kodlash", _KODLASHLAR)
def test_sigmaydigan_belgi_JIMGINA_tashlanmaydi_balki_ALMASHTIRILADI(tmp_path, kodlash):
    """⚠️ BELGI YO'QOLSA — bu ham NUQSON: operator matnning bir qismini KO'RMAY qolardi va
    nimadir yo'qolganini ham BILMASDI. `_XavfsizOqim` `replace` ishlatadi, ya'ni belgi
    o'rniga ALMASHTIRISH BELGISI chiqadi va operator «bu yerda nimadir bor edi» deb ko'radi.

    ⚠️ Shu bilan birga SATRNING QOLGANI BUTUN qolishi kerak: tekshiruv faqat `?` ni emas,
       YONIDAGI MA'NOLI MATNNI ham talab qiladi.
    """
    out = QatiyOqim(kodlash)
    kod, _ = _yurgiz(tmp_path, out, QatiyOqim(kodlash))
    assert kod == M.EXIT_FAILED_RUN
    matn = out.matn
    # `⚠` (U+26A0) uchta kodlashning BIRORTASIDA ham yo'q -> u ALMASHTIRILGAN bo'lishi kerak.
    assert "\u26a0" not in matn, (
        f"`{kodlash}` ga sig'maydigan `⚠` oqimga O'TIB ketdi — oqim qat'iy emas, "
        f"test hech narsa o'lchamayapti")
    assert "?" in matn, (
        f"`{kodlash}`: sig'maydigan belgi ALMASHTIRILMAGAN (jimgina tashlangan) — "
        f"operator matnning yo'qolganini bilmay qoladi")
    # ⚠️ MA'NOLI MATN ham bor: `?` lar o'rnida bo'sh satr qolmagan.
    assert "READ ONLY" in matn or "FAQAT O'QISH" in matn.upper(), (
        f"`{kodlash}`: almashtirish satrning MA'NOLI qismini ham yeb yuborgan: {matn[:200]!r}")
    assert st.FAILED_TIMEOUT in matn or st.FAILED_TIMEOUT in out.matn, (
        "yurish xulosasi ekranga chiqmadi")


def test_QATLAM_1_ishlasa_belgilar_UMUMAN_yoqolmaydi(tmp_path):
    """⚠️ ENG YAXSHI HOLAT: oqimni UTF-8 ga o'tkazish MUMKIN bo'lsa belgi ALMASHTIRILMAYDI,
    `⚠` AYNAN o'zi chiqadi. Yig'ilgan `.exe` da HAQIQATDA shu qatlam ishlaydi.

    ⚠️ Bu test qatlam 1 ni qatlam 2 dan AJRATADI: ikkisi bitta testda o'lchansa, qatlam 1
       buzilib qolsa ham qatlam 2 uni YASHIRARDI va nuqson sezilmasdi.
    """
    out = OtkazadiganOqim("cp1252")
    kod, papkalar = _yurgiz(tmp_path, out, OtkazadiganOqim("cp1252"))
    assert kod == M.EXIT_FAILED_RUN
    assert len(_besh_artefakt(papkalar)) == 5
    assert out.encoding == "utf-8", "`_utf8ga_otkaz` oqimni UTF-8 ga O'TKAZMADI"
    assert "\u26a0" in out.matn, (
        "qatlam 1 ishlagan bo'lsa `⚠` AYNAN saqlanishi kerak edi (almashtirish KERAK EMAS)")


def test_QATLAM_1_yiqilsa_ham_yurish_OXIRIGACHA_boradi(tmp_path):
    """⚠️ `reconfigure` ISTISNO tashlasa (qulflangan yoki almashtirilgan oqim) `_utf8ga_otkaz`
    JIM o'tadi va qatlam 2 ishni oladi. Chop etish HECH QACHON yurishni to'xtatmaydi."""
    out = OtkazmaydiganOqim("cp1252")
    kod, papkalar = _yurgiz(tmp_path, out, OtkazmaydiganOqim("cp1252"))
    assert kod == M.EXIT_FAILED_RUN
    assert len(_besh_artefakt(papkalar)) == 5
    assert out.encoding == "cp1252", "oqim o'tkazilmagan bo'lishi kerak edi"
    assert "?" in out.matn, "qatlam 2 ishlamadi"


def test_flush_YIQILSA_ham_yurish_toxtamaydi(tmp_path):
    """⚠️ Yopilgan quvur (`flush` -> istisno) chop etishni to'xtatmasin: operator skripti
    chiqishni yarim o'qib tashlab ketishi NORMAL, agent esa paketni YOZIB tugatishi kerak."""
    kod, papkalar = _yurgiz(tmp_path, FlushYiqiladiganOqim("utf-8"),
                            FlushYiqiladiganOqim("utf-8"))
    assert kod == M.EXIT_FAILED_RUN
    assert len(_besh_artefakt(papkalar)) == 5


def test_utf8ga_otkaz_reconfigure_SIZ_oqimda_istisno_TASHLAMAYDI():
    """⚠️ `_utf8ga_otkaz` har qanday obyektni qabul qilishi kerak: to'plam oqimni
    `io.StringIO` bilan almashtiradi va unda `reconfigure` YO'Q."""
    class Yalangoch:
        pass

    M._utf8ga_otkaz(Yalangoch())          # istisno BO'LMASLIGI kerak
    M._utf8ga_otkaz(QatiyOqim("ascii"))   # `reconfigure` yo'q — jim o'tadi


def test_XavfsizOqim_notanish_atributni_ICHKI_oqimga_uzatadi():
    """⚠️ O'ram SHAFFOF bo'lishi kerak: `print(file=...)` oqimdan boshqa atributlarni ham
    so'rashi mumkin (`errors`, `encoding`, `isatty`). O'ram ularni YO'QOTMASLIGI kerak."""
    ichki = QatiyOqim("cp1252")
    oram = M._XavfsizOqim(ichki)
    assert oram.encoding == "cp1252"
    assert oram.write("oddiy ascii") == len("oddiy ascii")
    assert ichki.matn == "oddiy ascii"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. §10.6–§10.7 — O'ZBOSHIMCHA QOBIQ YO'Q (MANBA ustida)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_shell_True_agent_manbasida_YOQ():
    """⚠️ `shell=True` bo'lsa qobiq METABELGILARI talqin qilinardi va 1C bazasining yo'li
    (probel, `&`, `;`) buyruqqa aylanib ketishi mumkin edi."""
    topildi = [p.name for p in _agent_manbalari()
               if re.search(r"shell\s*=\s*True", _KOD_FAQAT(p))]
    assert not topildi, f"`shell=True` topildi: {topildi}"


def test_qobiq_va_interpretator_chaqiruvlari_manbada_YOQ():
    """⚠️ Agent 1C ni TO'G'RIDAN-TO'G'RI ishga tushiradi; oraliqda `cmd.exe`/`powershell`
    BO'LMASLIGI kerak — ular buyruqni QAYTA talqin qiladi va antivirus uchun ham aynan shu
    zanjir shubhali."""
    # ⚠️ `cmd\.exe` SO'Z CHEGARASI bilan izlanadi: 1C ning qonuniy ijro fayli `ibcmd.exe`
    #    ichida `cmd.exe` BO'LAGI bor va oddiy «substring» tekshiruv uni YOLG'ON ushlardi.
    #    Darvoza yolg'on yiqilsa — uni o'chirib tashlashga majbur bo'lardilar.
    taqiq = (r"powershell", r"pwsh\.exe", r"(?<![A-Za-z])cmd\.exe", r"COMSPEC",
             r"WScript\.Shell", r"os\.system", r"os\.popen", r"rundll32", r"mshta",
             r"certutil", r"bitsadmin")
    topildi: dict[str, list[str]] = {}
    for p in _agent_manbalari():
        kod = _KOD_FAQAT(p)
        for t in taqiq:
            if re.search(t, kod):
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"manbada qobiq/interpretator izi bor: {topildi}"


def test_subprocess_FAQAT_koprikda_va_shell_ANIQ_False():
    """⚠️ `subprocess` YAGONA joyda bo'lishi kerak (`collector_bridge`) — tarqalib ketgan
    jarayon ishga tushirish auditni IMKONSIZ qiladi. Va u joyda `shell` ANIQ `False`."""
    ishlatganlar = [p.name for p in _agent_manbalari()
                    if re.search(r"^\s*import subprocess", _KOD_FAQAT(p), re.M)]
    assert ishlatganlar == ["collector_bridge.py"], (
        f"`subprocess` faqat `collector_bridge.py` da bo'lishi kerak, topilgani: "
        f"{ishlatganlar}")
    kod = _KOD_FAQAT(_AGENT_DIR / "collector_bridge.py")
    assert re.search(r"shell\s*=\s*False", kod), (
        "`subprocess.run` chaqiruvida `shell=False` ANIQ yozilishi kerak (standart qiymatga "
        "tayanmaslik: standart kelajakda o'zgarsa darvoza sezmaydi)")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. §10.2–§10.5 — AVTOYUKLANISH / XIZMAT / VAZIFA / REESTRGA YOZISH YO'Q (MANBA ustida)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_reestrga_YOZISH_apilari_manbada_YOQ():
    """⚠️ Detector reestrni O'QIYDI (bu RUXSAT ETILGAN va kerak). YOZISH esa YO'Q: yozuv
    api'si manbada BO'LMASLIGI kerak, `KEY_READ` dan boshqa ruxsat ham olinmasin."""
    yozuv_api = ("SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey",
                 "DeleteKeyEx", "DeleteValue", "SaveKey", "KEY_WRITE", "KEY_SET_VALUE",
                 "KEY_CREATE_SUB_KEY", "KEY_ALL_ACCESS")
    topildi: dict[str, list[str]] = {}
    for p in _agent_manbalari():
        kod = _KOD_FAQAT(p)
        for t in yozuv_api:
            if t in kod:
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"reestrga YOZISH api'si topildi: {topildi}"
    # ⚠️ VA o'qish ANIQ `KEY_READ` bilan: standart ruxsatga tayanmaslik kerak.
    det = _KOD_FAQAT(_AGENT_DIR / "detector.py")
    assert "KEY_READ" in det, "reestr `KEY_READ` bilan ANIQ ochilishi kerak"


def test_avtoyuklanish_xizmat_va_rejalashtirilgan_vazifa_izlari_manbada_YOQ():
    """⚠️⚠️ ENG MUHIM DARVOZA: agent FAQAT operator yurgizganda ishlaydi va ishini tugatib
    CHIQADI. Avtoyuklanish, Windows xizmati, rejalashtirilgan vazifa va `Startup` papkasiga
    yozish — hech biri BO'LMAYDI. Bu da'vo `__main__.py` docstringida yozilgan; docstring
    esa darvoza EMAS, shu bois u KOD ustida tekshiriladi."""
    taqiq = ("schtasks", "TaskScheduler", "Schedule.Service", "sc create", "CreateService",
             "OpenSCManager", "StartService", "CurrentVersion\\Run", "CurrentVersion/Run",
             "RunOnce", "Winlogon", "Userinit", "Startup\\", "Start Menu",
             "win32serviceutil", "pythonservice", "atexit.register")
    topildi: dict[str, list[str]] = {}
    for p in _agent_manbalari():
        kod = _KOD_FAQAT(p)
        for t in taqiq:
            if t in kod:
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"avtoyuklanish/xizmat/vazifa izi topildi: {topildi}"


def test_tarmoq_chaqiruvlari_agent_manbasida_YOQ():
    """⚠️ Agent OFFLINE: manbada tarmoq mijozi IMPORTI ham, ulanish chaqiruvi ham yo'q.

    ⚠️ `platform` moduli `socket` ni TRANZITIV olib keladi (`platform.node()` uchun) va u
       yig'maga TUSHADI — bu AUDIT HISOBOTIDA ayrim band. Bu test boshqa narsani o'lchaydi:
       AGENTNING O'ZI tarmoqqa MUROJAAT QILMAYDI.
    """
    taqiq = (r"^\s*import\s+socket", r"^\s*from\s+socket\s+import",
             r"^\s*import\s+(requests|httpx|urllib3|aiohttp|smtplib|ftplib|telnetlib)\b",
             r"\.connect\s*\(", r"urlopen", r"urlretrieve", r"http\.client",
             r"socketserver", r"\.sendall\s*\(", r"\.recv\s*\(")
    topildi: dict[str, list[str]] = {}
    for p in _agent_manbalari():
        kod = _KOD_FAQAT(p)
        for t in taqiq:
            if re.search(t, kod, re.M):
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"agent manbasida tarmoq chaqiruvi bor: {topildi}"


def test_kredensial_bayrogi_buyruq_satrida_YOQ():
    """⚠️ Buyruq satri jarayon ro'yxatida HAMMAGA ko'rinadi, shu bois parol uchun bayroq
    ATAYLAB mavjud EMAS. Bayroq qo'shilsa bu test yiqilib ESLATADI."""
    bayroqlar = {a.option_strings[0] for a in M.build_parser()._actions if a.option_strings}
    taqiq = {"--password", "--parol", "--pwd", "--pass", "--user", "--usr", "--login",
             "--token", "--secret"}
    assert not (bayroqlar & taqiq), (
        f"buyruq satrida kredensial bayrog'i paydo bo'ldi: {sorted(bayroqlar & taqiq)}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. §10.8 — KREDENSIAL CHIQISHGA YOZILMAYDI (uchiga-uch, SINTETIK sir bilan)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ibases_parolli_bolsa_sir_natija_paketiga_BIRORTA_BAYT_bolib_tushmaydi(tmp_path):
    """⚠️⚠️ `ibases.v8i` da `Usr=`/`Pwd=` BO'LISHI MUMKIN va detector faylni O'QIYDI. Sir
    esa natija paketining BIRORTA BAYTIGA tushmasligi kerak: paket qo'ldan qo'lga o'tadi.

    ⚠️ Tekshiruv NOMLARGA emas, BAYTLARGA qaraydi — sir JSON ichida, Markdown ichida yoki
       kutilmagan faylda bo'lsa ham topiladi.
    """
    kuzatilgan = tmp_path / "kuzatilgan"
    kuzatilgan.mkdir()
    ota = tmp_path / "natija"
    ota.mkdir()
    kod = M.main(["--headless", str(kuzatilgan), "--result-dir", str(ota),
                  "--wait-seconds", "6", "--timestamp", _TAMGA],
                 out=QatiyOqim("utf-8"), err=QatiyOqim("utf-8"),
                 scan=lambda: X.muhit_bazali(tmp_path, X.baza_parolli(tmp_path)),
                 clock=X.oshuvchi_soat(), sleeper=X.yozib_oluvchi_uyqu([]))
    assert kod in (M.EXIT_FAILED_RUN, M.EXIT_CANNOT_RUN), (
        f"parolli baza bilan yurish YIQILISHI kutilgan edi, kelgani {kod}")
    baytlar = b"\n".join(X.papka_baytlari(str(ota)).values())
    assert baytlar, "natija papkasi BO'SH — paket umuman yozilmagan"
    for iz in X.SIR_IZLARI:
        for enc in ("utf-8", "utf-16-le", "cp1251"):
            assert iz.encode(enc) not in baytlar, (
                f"natija paketida SIR OSHKOR bo'ldi: {iz!r} [{enc}]")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. YIG'MA USTIDA — faqat yig'ma BOR bo'lsa
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ O'LCHANGAN TESHIK (shu worktree'da): mahalliy `.exe` uch moduldan eskirgan edi
#      (`discovery_1c/redact.py`, `discovery_agent/detector.py`,
#      `discovery_agent/launcher.py`) — `test_agent_parity.py` BALAND yiqildi va uchtasini
#      NOMLADI, bu modul esa `22 passed` berdi. Ya'ni TARQATILADIGAN BAYTLAR darvozasi
#      ESKIRGAN artefaktni «xavfsiz» deb TASDIQLADI.
#
# ⚠️ NEGA BU MODULGA HAM SHART: bu yerdagi uch da'vo TARQATILADIGAN papka ustida — manbada
#    yo'q narsa yig'mada paydo bo'lishi mumkin (tranzitiv import, hook, ma'lumot fayli),
#    shu bois darvoza yig'ilgan artefakt ustida turadi. Lekin artefakt ESKI bo'lsa da'vo
#    JORIY manba haqida EMAS: manbaga BUGUN kiritilgan `powershell` chaqiruvi yoki yangi
#    tarmoq komponenti ESKI `.exe` da KO'RINMAYDI va darvoza YOLG'ON yashil bo'ladi.
#
# ⚠️ Darvoza QAYTA YOZILMAYDI: hukm `packaging/parity_harness.yigma_tayyorligi()` dan
#    OLINADI (OWNER B) — AYNI harness, AYNI qaror jadvali.
_HARNESS_YOLI = _SERVER / "packaging" / "parity_harness.py"

#: ⚠️ Qolgan darvozalar harnessni AYNI shu nom bilan `sys.modules` ga qo'yadi — mavjud
#:    nusxa QAYTA ISHLATILADI. Aks holda bir yurishda BESHINCHI modul nusxasi paydo
#:    bo'lardi va unga qo'yilgan o'lchov boshqalariga ta'sir qilmasdi.
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

#: ⚠️⚠️ SABAB MATNI BOSHQA TO'RT DARVOZADAN ATAYLAB FARQ QILADI:
#:      `MUHIT: Windows EXE Linux CI'da QURILMAYDI`             — parity (OWNER B);
#:      `MUHIT: Windows yig'masi Linux CI'da QURILMAYDI`        — yig'ma tarkibi;
#:      `MUHIT: Windows EXE'ni Linux CI YURGIZA OLMAYDI`        — portativlik;
#:      `MUHIT: Linux CI'da Windows yig'masi UCHIGA-UCH yurmaydi` — uchiga-uch matritsa.
#:      `verify_pytest_run._matches` sababni `reason in msg` bilan tekshiradi, ya'ni
#:      matnlar bir-birining BO'LAGI bo'lsa, bir darvozaning yozuvi yo'qolganda uning
#:      skip'lari boshqasining qatoriga «yashirinib» o'tib ketardi va KUTILMAGAN skip
#:      QIZIL bermasdi. Ajralganlik `::test_darvoza_ESKIRGAN_yigmani_XAVFSIZ_demaydi`
#:      da test bilan qulflangan.
#: ⚠️ Matn SEMANTIK jihatdan ham boshqa: bu modul `.exe` ni NA quradi, NA yurgizadi — u
#:    TARQATILADIGAN papkaning BAYTLARINI o'qiydi, va Linux CI'da o'sha baytlar YO'Q.
_MUHIT_SABABI = "MUHIT: tarqatiladigan Windows BAYTLARI Linux CI'da YO'Q"


def _yoqlik_qarori(*, qurilishi_mumkin: bool) -> tuple[str, str]:
    """`.exe` UMUMAN YO'Q bo'lganda: `(qaror, matn)`.

    ⚠️⚠️ «EXE yo'q bo'lsa skip» SHARTSIZ EMAS va bu ataylab: yig'ma QURILISHI mumkin
         bo'lgan platformada (Windows) yo'qligi OPERATORNING ishi, muhit cheklovi EMAS —
         u yerda tarqatiladigan baytlar O'LCHANMAGANI SKIP bo'lib ko'rinmasligi kerak.
         Ilgari bu modulda SHARTSIZ `skipif` (`_yigma_yoq`) turardi, ya'ni Windows reliz
         darvozasida yig'ma topilmasa «hammasi o'tdi» ko'rinishi mumkin edi.
    ⚠️ Skip matni `_MUHIT_SABABI` bilan BOSHLANADI — `tests/ci_expected_skips.txt` dagi
       sabab bo'lagi AYNAN shu satr (o'zgartirilsa ro'yxat ham yangilanadi).
    """
    if qurilishi_mumkin:
        return _QAROR_YIQIL, (
            f"TARQATILADIGAN BAYTLAR O'LCHANMADI: {_EXE} topilmadi, LEKIN bu platformada "
            f"(`{sys.platform}`) yig'ma QURILADI — ya'ni yo'qligi MUHIT cheklovi EMAS va "
            f"skip bo'lib o'tib ketishi TAQIQLANGAN. Reliz darvozasi "
            f"(`packaging/BUILD_GATE.md`) bo'yicha yig'ing, build papkasini SAQLAB "
            f"(`--workpath`), so'ng shu modulni qayta yurgizing.")
    return _QAROR_SKIP, (
        f"{_MUHIT_SABABI}. Yig'ma YO'Q: {_EXE} topilmadi. Yig'ma repo tashqarisida "
        f"quriladi (`pyinstaller packaging/BinOSDiscoveryAgent.spec`) va PyInstaller "
        f"kross-kompilyatsiya QILMAYDI, shu bois Linux backend job'ida o'qiladigan BAYT "
        f"MAVJUD EMAS — bu MUHIT cheklovi. Shu moduldagi MANBA darvozalari (`shell=True` "
        f"yo'q, qobiq/reestr/avtoyuklanish chaqiruvlari yo'q, kodlash qatlamlari) BU "
        f"YURISHDA bajarildi va ro'yxatda YO'Q; darvozaning QAROR JADVALI ham shu "
        f"yurishda o'lchandi (`::test_darvoza_ESKIRGAN_yigmani_XAVFSIZ_demaydi`); "
        f"baytlar ustidagi o'lchov esa Windows reliz darvozasida "
        f"(`packaging/BUILD_GATE.md`).")


def _yangilik_qarori(holat: str, sabab: str, *, toza: str) -> str | None:
    """`None` — yig'ma JORIY manbadan qurilgani ISBOTLANDI; aks holda YIQILISH matni.

    ⚠️⚠️ FAIL-CLOSED va PLATFORMAGA BOG'LIQ EMAS: `toza` dan BOSHQA HAR holat
         (`ESKIRGAN`, `ISBOTSIZ`, va hatto `YO_Q` — harness BOSHQA `.exe` yo'liga
         qarasa, `BINOS_AGENT_EXE`) YIQILISH beradi. JIM SKIP YO'Q: eskirgan yig'ma
         «xavfsiz» deb tasdiqlanishining yo'li aynan shu edi.
    ⚠️ `sabab` harnessdan KELGANIDEK uzatiladi — nomos modullar ro'yxati va tuzatish
       yo'li o'sha matnda.
    """
    if holat == toza:
        return None
    return (f"YIG'MA XAVFSIZLIGI O'LCHANMADI (holat: {holat}) — o'qilgan baytlar JORIY "
            f"manbadan qurilgani ISBOTLANMADI. «Qobiq/persistence izi YO'Q», «tarmoqqa "
            f"qodir fayllar ro'yxati O'SMADI» va «UPX YO'Q» da'volari ESKI artefakt "
            f"haqida bo'lardi: manbaga BUGUN kiritilgan chaqiruv yoki yangi komponent "
            f"eski papkada KO'RINMAYDI (yolg'on kafolat). {sabab}")


def _darvoza_AYNI_EXE_ni_olchasin(PH) -> None:
    """Darvoza va testlar AYNI faylni ko'rsin — aks holda BALAND yiqilish.

    ⚠️⚠️ NEGA ALOHIDA TEKSHIRUV: harness `BINOS_AGENT_EXE` ni o'qiydi, bu modul esa
         ildizdan hisoblangan papkaning BAYTLARINI o'qiydi. Ikkisi BOSHQA fayl bo'lsa
         darvoza BIR artefaktni «toza» deb tasdiqlab, testlar BOSHQASINI tekshirardi —
         tuzatilgan teshikning AYNI ko'rinishi.
    ⚠️⚠️ FAQAT `_EXE` MAVJUD bo'lganda chaqiriladi (`_dist_talab()` dagi tartibga
         qarang): artefakt yo'q bo'lsa birorta BAYT o'qilmaydi, demak chalkashish
         zarari ham YO'Q — u holat `_yoqlik_qarori()` va harnessning `YO_Q` holati
         bilan yopilgan. Shartsiz solishtirish esa `BINOS_AGENT_EXE` ni MAVJUD
         BO'LMAGAN yo'lga qo'yib Linux CI'ni taqlid qilishni YOLG'ON qizil qilardi.
    ⚠️ Solishtirish `normcase`+`abspath` bilan: Windows'da harf registri va `/`↔`\\`
       farqi YOLG'ON qizil bermasligi kerak.
    """
    def norm(p) -> str:
        return os.path.normcase(os.path.abspath(str(p)))

    if norm(PH.YIGMA_EXE) != norm(_EXE):
        pytest.fail(
            f"DARVOZA VA TEST BOSHQA ARTEFAKTNI ko'rsatadi: harness `{PH.YIGMA_EXE}` ni "
            f"tekshiradi, bu modul esa `{_DIST}` BAYTLARINI o'qiydi. Ildiz BITTA manbadan "
            f"kelishi SHART: `{PH.YIGMA_ILDIZ_ENV_KALITI}` ni qo'ying va "
            f"`{PH.YIGMA_ENV_KALITI}` ni OLIB TASHLANG.")


def _chaqirilgan_nomlar(fn) -> set[str]:
    """`fn` TANASIDA ROSTDAN chaqirilgan nomlar (docstring va izoh HISOBGA OLINMAYDI).

    ⚠️⚠️ NEGA MATN QIDIRUVI YETMAYDI — BU O'LCHANGAN MUTATSIYA (M2): darvoza simini
         OLIB TASHLAB turib, `inspect.getsource(...)` ichida nomni IZLASH tekshiruvi
         YASHIL qoldi, chunki `getsource()` DOCSTRINGNI ham qaytaradi va docstring o'sha
         nomni ESLATADI. AST esa faqat HAQIQIY `Call` tugunlarini ko'radi.
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

    ⚠️ TARTIB MUHIM: `_EXE.exists()` AVVAL o'lchanadi (shu modulning O'Z yo'li bilan),
       so'ng darvoza AYNI faylni ko'rishi va u JORIY manbadan qurilgani talab qilinadi.
    """
    PH = _harness()
    if not _EXE.exists():
        qaror, matn = _yoqlik_qarori(qurilishi_mumkin=PH.exe_qurish_mumkinmi())
        if qaror == _QAROR_YIQIL:
            pytest.fail(matn)
        pytest.skip(matn)
    _darvoza_AYNI_EXE_ni_olchasin(PH)
    holat, sabab = PH.yigma_tayyorligi()
    matn = _yangilik_qarori(holat, sabab, toza=PH.HOLAT_TOZA)
    if matn is not None:
        pytest.fail(matn)


def _dist_fayllari() -> list[pathlib.Path]:
    return sorted(p for p in _DIST.rglob("*") if p.is_file())


# ═══ 0. DARVOZANING O'ZI: eskirgan yig'ma JIMGINA «xavfsiz» bo'lolmaydi ═════════════════
def test_darvoza_ESKIRGAN_yigmani_XAVFSIZ_demaydi():
    """⚠️⚠️ BESHINCHI DARVOZADAGI AYNI TESHIK shu testda qadalgan: «eskirgan yig'ma
         xavfsizlik validatsiyasidan JIMGINA o'tib ketolmasligi ISBOTLANSIN». Qaror
         jadvali `.exe` DAN MUSTAQIL o'lchanadi, ya'ni bu test Linux CI'da ham
         BAJARILADI va shu bois `ci_expected_skips.txt` da YO'Q.

    O'lchanadigan olti narsa — `test_agent_packaged_e2e.py` dagi §0 bilan AYNI jadval:
      1. `TOZA` yagona DAVOM etiladigan holat;
      2. `ESKIRGAN`/`ISBOTSIZ`/`YO_Q` — HAMMASI yiqilish matni (jim skip YO'Q);
      3. `.exe` yo'qligi — Windows'da YIQILISH, boshqa platformada ratifikatsiya
         qilingan skip, matn `ci_expected_skips.txt` dagi bo'lakni O'Z ICHIGA oladi;
      4. SIMLASH: `_dist_talab()` qaror jadvalini ROSTDAN chaqiradi;
      5. SABAB MATNINING AJRALGANLIGI (qolgan to'rtta bilan);
      6. QAMROV: tarqatiladigan BAYTLARNI o'qiydigan HAR test darvozani chaqiradi
         (AST) — yangi bayt-testi qo'shilib darvoza chaqirilmasa, eskirgan artefakt
         yana jimgina «xavfsiz» bo'lardi.
    """
    PH = _harness()
    assert _yangilik_qarori(PH.HOLAT_TOZA, "", toza=PH.HOLAT_TOZA) is None, \
        "`TOZA` holat DAVOM etmadi — darvoza yolg'on qizil beradi"
    for holat in (PH.HOLAT_ESKIRGAN, PH.HOLAT_ISBOTSIZ, PH.HOLAT_YOQ):
        matn = _yangilik_qarori(holat, f"<SABAB:{holat}>", toza=PH.HOLAT_TOZA)
        assert matn is not None, \
            f"`{holat}` holati JIMGINA o'tib ketdi — XAVFSIZLIK darvozasi TESHIK"
        assert f"<SABAB:{holat}>" in matn, \
            f"`{holat}` yiqilish matnida harness sababi YO'Q: {matn}"

    assert _yoqlik_qarori(qurilishi_mumkin=True)[0] == _QAROR_YIQIL, \
        "yig'ma QURILADIGAN platformada `.exe` yo'qligi SKIP bo'lib qoldi"
    qaror, matn = _yoqlik_qarori(qurilishi_mumkin=False)
    assert qaror == _QAROR_SKIP, "yig'ma QURILMAYDIGAN platformada MUHIT skip'i yo'qoldi"
    assert _MUHIT_SABABI in matn, \
        f"skip matni `ci_expected_skips.txt` dagi sabab bo'lagini olmaydi: {matn}"

    # ⚠️ SIMLASH AST BILAN o'lchanadi, MATN qidiruvi bilan EMAS (mutatsiya M2).
    chaqirilgan = _chaqirilgan_nomlar(_dist_talab)
    for chaqiruv in ("yigma_tayyorligi", "exe_qurish_mumkinmi", "_yangilik_qarori",
                     "_yoqlik_qarori", "_darvoza_AYNI_EXE_ni_olchasin"):
        assert chaqiruv in chaqirilgan, \
            f"`_dist_talab()` `{chaqiruv}` ni CHAQIRMAYDI — darvoza SIMLANMAGAN"

    # ⚠️ Sabab matnlari ARALASHMAYDI: hech biri boshqasining BO'LAGI emas, va bu
    #    moduldagi skip matni boshqa darvozalarning sababini O'Z ICHIGA OLMAYDI.
    from tests import test_agent_packaged_e2e as E2E
    from tests import test_agent_packaging as PKG
    from tests import test_agent_portability as PORT
    for begona in (PH.MUHIT_SABABI, PKG._MUHIT_SABABI, PORT._MUHIT_SABABI,
                   E2E._MUHIT_SABABI):
        assert begona != _MUHIT_SABABI, "beshinchi darvoza sababi BOSHQASI bilan AYNI"
        assert begona not in _MUHIT_SABABI and _MUHIT_SABABI not in begona, \
            (f"skip sabablari bir-birining BO'LAGI: `{_MUHIT_SABABI}` ↔ `{begona}` — "
             f"ro'yxatdan bitta yozuv yo'qolsa skip ikkinchisiga YASHIRINIB o'tardi")
        assert begona not in matn, \
            f"bu modulning skip matni BOSHQA darvozaning sababini o'z ichiga oldi: {begona}"

    # ⚠️ QAMROV (AST): tarqatiladigan papkani o'qigan HAR test darvozani chaqirsin.
    daraxt = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    qamrovsiz = []
    for n in daraxt.body:
        if not (isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
            continue
        nomlar = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
        if nomlar & {"_DIST", "_EXE", "_dist_fayllari"} and "_dist_talab" not in nomlar:
            qamrovsiz.append(n.name)
    assert not qamrovsiz, (
        f"tarqatiladigan BAYTLARNI o'qiydigan test darvozani CHAQIRMAYDI: {qamrovsiz} — "
        f"eskirgan artefakt shu testlar orqali jimgina «xavfsiz» bo'lardi. "
        f"`_dist_talab()` ni test tanasining BIRINCHI qatoriga qo'ying va skip'ini "
        f"`tests/ci_expected_skips.txt` ga yozing.")


def test_yigmada_qobiq_persistence_va_yuklab_olish_vositalari_YOQ():
    """⚠️⚠️ TARQATILADIGAN HAMMA BAYT ustida: avtoyuklanish, xizmat, rejalashtirilgan vazifa,
    reestrga yozish va «yuklab olib bajarish» vositalarining NOMI ham bo'lmasin.

    ⚠️ NEGA BAYT DARAJASIDA: operator qo'liga manba emas, SHU PAPKA boradi. Manbada yo'q
       narsa yig'mada paydo bo'lishi mumkin (tranzitiv import, hook, ma'lumot fayli), shu
       bois darvoza yig'ilgan artefakt ustida ham turishi kerak.
    ⚠️ Bu ro'yxatga `cmd.exe`/`COMSPEC` ATAYLAB KIRMAYDI: ular Tcl/Tk ning O'Z
       fayllarida bor (`init.tcl`, `tcl86t.dll`) va ular `tkinter` bilan birga keladi.
       Shu bois ular ALOHIDA, ro'yxatga olingan test bilan kuzatiladi (pastda).
    """
    _dist_talab()
    taqiq = ("powershell", "pwsh.exe", "schtasks", "sc create", "CreateServiceW",
             "OpenSCManagerW", "reg add", "regsvr32", "RunOnce", "rundll32", "mshta",
             "certutil", "bitsadmin", "Invoke-Expression", "DownloadString",
             "WScript.Shell", "shell=True", "CurrentVersion\\Run")
    topildi: dict[str, list[str]] = {}
    for p in _dist_fayllari():
        xom = p.read_bytes().lower()
        for t in taqiq:
            for enc in ("utf-8", "utf-16-le"):
                if t.lower().encode(enc) in xom:
                    topildi.setdefault(t, []).append(str(p.relative_to(_DIST)))
                    break
    assert not topildi, f"yig'mada qobiq/persistence/yuklab olish izi bor: {topildi}"


#: ⚠️⚠️ BU RO'YXAT TASDIQ EMAS, REGISTR. Yig'maga `tkinter` (va u bilan Tcl/Tk) kirgani
#: uchun papkada TARMOQQA QODIR fayllar BOR: Tcl ning `http` paketi, `_socket.pyd`,
#: `select.pyd` va OpenSSL. Agent ularni CHAQIRMAYDI (yuqoridagi manba testlari shuni
#: o'lchaydi), lekin ular OPERATOR PAPKASIDA YOTADI va auditda shunday YOZILGAN.
#: ⚠️ Bu test ro'yxat O'SIB ketmasligini kuzatadi: yangi tarmoq komponenti paydo bo'lsa
#: test yiqiladi va ODAM uni ko'rib chiqadi. «Hammasi joyida» degan da'vo EMAS.
_TARMOQQA_QODIR_FAYLLAR = {
    "_internal/_socket.pyd",
    "_internal/select.pyd",
    "_internal/_hashlib.pyd",
    "_internal/libcrypto-3.dll",
    "_internal/_tcl_data/http1.0/http.tcl",
    "_internal/_tcl_data/http1.0/pkgIndex.tcl",
    "_internal/tcl8/8.6/http-2.9.8.tm",
}


def test_yigmadagi_tarmoqqa_QODIR_fayllar_royxati_OSMAYDI():
    """⚠️ Spec docstringi «tarmoq kutubxonalari yig'maga tushmasligi kerak» deydi; bu
    HAQIQATDA faqat MIJOZ kutubxonalariga (`requests`, `httpx`, ...) tegishli. Tcl/Tk va
    CPython kengaytmalari tranzitiv tarmoq QUVVATINI olib keladi. Bu test shu quvvatni
    RO'YXATGA oladi va uning O'SMASLIGINI kuzatadi."""
    _dist_talab()
    nomzod = re.compile(r"(socket|select\.pyd|http|ssl|crypto|ftp|smtp)", re.I)
    haqiqiy = {str(p.relative_to(_DIST)).replace("\\", "/")
               for p in _dist_fayllari() if nomzod.search(p.name)}
    qoshilgan = haqiqiy - _TARMOQQA_QODIR_FAYLLAR
    assert not qoshilgan, (
        f"yig'maga YANGI tarmoqqa qodir fayl kirdi — ODAM ko'rib chiqishi kerak: "
        f"{sorted(qoshilgan)}")


def test_yigma_ONE_DIR_va_UPX_SIQILMAGAN():
    """⚠️ ONE-DIR ATAYLAB: one-file yig'ma har yurishda `%TEMP%\\_MEI*` ga o'zini ochadi va
    operator papkasidan TASHQARIDA fayl paydo bo'ladi — bu §10.9 («faqat natija papkasiga
    yoziladi») ni o'lchashni qiyinlashtiradi. UPX esa antivirus uchun qo'shimcha shubha."""
    _dist_talab()
    assert (_DIST / "_internal").is_dir(), "ONE-DIR yig'masida `_internal/` bo'lishi kerak"
    assert (_DIST / "_internal" / "python312.dll").is_file(), (
        "interpretator DLL `_internal/` da bo'lishi kerak (one-file emas)")
    xom = (_DIST / "BinOSDiscoveryAgent.exe").read_bytes()
    assert b"UPX!" not in xom, "EXE UPX bilan siqilgan — spec `upx=False` deydi"
