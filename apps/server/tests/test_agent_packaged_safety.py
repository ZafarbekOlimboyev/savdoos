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
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.services.discovery_agent import __main__ as M
from app.services.discovery_agent import states as st
from tests import agent_scenario_mock as X

# ══════════════════════════════════════════════════════════════════════════════════════════
# YO'LLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `app/services/discovery_agent/` — agentning O'Z manbasi.
_AGENT_DIR = pathlib.Path(M.__file__).resolve().parent
#: Yig'ma REPO TASHQARISIDA quriladi (repo daraxti toza qolishi uchun). Yo'q bo'lsa — SKIP,
#: yashirish emas: yig'ma bo'lmasa bu tekshiruvlar PRINTSIPIAL ravishda ma'nosiz.
_DIST = pathlib.Path(r"C:\Users\Developer\binos-agent-build\dist-onedir\BinOSDiscoveryAgent")

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
_yigma_yoq = pytest.mark.skipif(
    not (_DIST / "BinOSDiscoveryAgent.exe").is_file(),
    reason=(f"yig'ma topilmadi: {_DIST} — yig'ma REPO TASHQARISIDA quriladi, shu bois bu "
            f"tekshiruvlar yig'masiz PRINTSIPIAL ravishda ma'nosiz (SKIP yashirish emas)"))


def _dist_fayllari() -> list[pathlib.Path]:
    return sorted(p for p in _DIST.rglob("*") if p.is_file())


@_yigma_yoq
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


@_yigma_yoq
def test_yigmadagi_tarmoqqa_QODIR_fayllar_royxati_OSMAYDI():
    """⚠️ Spec docstringi «tarmoq kutubxonalari yig'maga tushmasligi kerak» deydi; bu
    HAQIQATDA faqat MIJOZ kutubxonalariga (`requests`, `httpx`, ...) tegishli. Tcl/Tk va
    CPython kengaytmalari tranzitiv tarmoq QUVVATINI olib keladi. Bu test shu quvvatni
    RO'YXATGA oladi va uning O'SMASLIGINI kuzatadi."""
    nomzod = re.compile(r"(socket|select\.pyd|http|ssl|crypto|ftp|smtp)", re.I)
    haqiqiy = {str(p.relative_to(_DIST)).replace("\\", "/")
               for p in _dist_fayllari() if nomzod.search(p.name)}
    qoshilgan = haqiqiy - _TARMOQQA_QODIR_FAYLLAR
    assert not qoshilgan, (
        f"yig'maga YANGI tarmoqqa qodir fayl kirdi — ODAM ko'rib chiqishi kerak: "
        f"{sorted(qoshilgan)}")


@_yigma_yoq
def test_yigma_ONE_DIR_va_UPX_SIQILMAGAN():
    """⚠️ ONE-DIR ATAYLAB: one-file yig'ma har yurishda `%TEMP%\\_MEI*` ga o'zini ochadi va
    operator papkasidan TASHQARIDA fayl paydo bo'ladi — bu §10.9 («faqat natija papkasiga
    yoziladi») ni o'lchashni qiyinlashtiradi. UPX esa antivirus uchun qo'shimcha shubha."""
    assert (_DIST / "_internal").is_dir(), "ONE-DIR yig'masida `_internal/` bo'lishi kerak"
    assert (_DIST / "_internal" / "python312.dll").is_file(), (
        "interpretator DLL `_internal/` da bo'lishi kerak (one-file emas)")
    xom = (_DIST / "BinOSDiscoveryAgent.exe").read_bytes()
    assert b"UPX!" not in xom, "EXE UPX bilan siqilgan — spec `upx=False` deydi"
