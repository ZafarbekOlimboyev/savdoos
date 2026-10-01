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

⚠️ Yig'ma REPO TASHQARISIDA turadi (`C:/Users/Developer/binos-agent-build`), shu bois CI
   mashinasida u BO'LMAYDI va bu fayldagi yurish testlari ANIQ SABAB bilan `skip` bo'ladi.
   Hujjat testi (§C) yig'masiz ham ishlaydi — u repo faylini o'qiydi.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

# ── Yig'ma joylashuvi (`test_agent_packaging.py` dagi bilan AYNI manzil) ────────────────
_YIGMA_ILDIZ = pathlib.Path("C:/Users/Developer/binos-agent-build")
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


def _dist_talab() -> None:
    if not _EXE.exists():
        pytest.skip(
            f"Yig'ma YO'Q: {_EXE} topilmadi. Yig'ma repo TASHQARISIDA quriladi "
            f"(`pyinstaller packaging/BinOSDiscoveryAgent.spec`), shu bois CI mashinasida "
            f"u bo'lmasligi NORMAL. Portativlik YURISH bilan TEKSHIRILMADI.")


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
