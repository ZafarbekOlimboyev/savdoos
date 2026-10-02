# -*- coding: utf-8 -*-
"""YIG'MA TARKIBI DARVOZASI — `BinOSDiscoveryAgent` (brief §4).

⚠️⚠️ BU FAYL NIMAGA JAVOB BERADI: «yig'ilgan `.exe` ichida AYNAN nima bor?». Bu REAL 1C
     isboti EMAS: bu yerda 1C ga ulanish yo'q, `.epf` bajarilmaydi, tarmoq ishlatilmaydi va
     EXE ham ISHGA TUSHIRILMAYDI. O'lchanadigan narsa — yig'ma FAYLLARI va yig'uvchi
     (PyInstaller) qoldirgan modul manifesti.

⚠️ NEGA SHART: `packaging/BinOSDiscoveryAgent.spec` dagi `excludes` ro'yxati o'zi hech
   NARSANI isbotlamaydi — u faqat NIYAT. Spec'da modul taqiqlangan bo'lib, yig'mada MAVJUD
   bo'lsa, spec YOLG'ON KAFOLAT bergan bo'ladi (va «agent offline, faqat-o'qish» da'vosi
   buziladi). Shu bois darvoza spec'ni YIG'MA bilan solishtiradi.

═══ USUL (aniq yozilgan, brief talabi) ═══════════════════════════════════════════════════
PyInstaller modullarni `_internal/base_library.zip` ichiga va `.exe` ichidagi `PYZ` arxiviga
JOYLASHTIRADI — ya'ni papkada `foo.py` ko'rinishida YOTMAYDI va oddiy `ls` bilan topilmaydi.
Shu sababli IKKI MUSTAQIL manba o'qiladi:

  (A) YIG'UVCHI MANIFESTI — `build-onedir/BinOSDiscoveryAgent/Analysis-00.toc`. Bu build
      vaqtida yoziladigan, `ast.literal_eval` bilan o'qiladigan Python literali. Undan
      olinadi: `excludes` (build AYNI spec bilan qilinganini isbotlaydi), `PYMODULE`
      yozuvlari (PYZ + `base_library.zip` ga ketgan modullar), `BINARY`/`EXTENSION`
      (`.pyd`/`.dll`) va `PYSOURCE` (boshlang'ich skriptlar).
      ⚠️ MANIFEST ESKIRGAN BO'LISHI MUMKIN: `build-onedir` papkasi oldingi yurishdan
         qolgan bo'lsa, u TARQATILADIGAN `.exe` ni tasvirlamaydi. Shu bois (A) ga tayangan
         har bir test OLDIN `_manifest_talab()` darvozasidan o'tadi: build papkasidagi
         `.exe` va dist papkasidagi `.exe` BAYT-BA-BAYT bir xil bo'lishi kerak.
      ⚠️⚠️ LEKIN BU TENGLIK YETMAYDI va bu O'LCHANGAN TESHIK edi: ikkisi ham AYNI, ESKI
           yig'madan bo'lsa tenglik SAQLANADI. Shu bois (A) va (B) ning IKKISI ham
           `_dist_talab()` orqali ESKIRGAN YIG'MA darvozasidan o'tadi — yig'ma ichidagi
           bytecode JORIY manba bilan solishtiriladi
           (`packaging/parity_harness.yigma_tayyorligi()`).

  (B) TARQATILADIGAN ARTEFAKT O'ZI — `dist-onedir/BinOSDiscoveryAgent/`: fayllar ro'yxati,
      `base_library.zip` ichidagi nomlar va `.exe` ning XOM BAYTLARI. `PYZ` arxivining TOC
      qismi modul NOMLARINI siqilmagan ASCII matn sifatida saqlaydi (faqat modul MAZMUNI
      siqiladi), shu bois `b"sqlalchemy" in exe_baytlari` — yig'uvchi manifestiga BOG'LIQ
      BO'LMAGAN mustaqil tekshiruv.
      ⚠️ (B) HAR DOIM ishlaydi — manifest eskirgan yoki o'chirilgan bo'lsa ham. Ya'ni
         taqiqlangan modul darvozasi manifestsiz ham qulflangan qoladi.

═══ NIMA QULFLANMAYDI ════════════════════════════════════════════════════════════════════
⚠️ O'LCHAM va SHA-256 bu yerda TEKSHIRILMAYDI. Ular yig'uvchi versiyasi, Python patch
   versiyasi va Tcl/Tk tarkibiga qarab o'zgaradi; testga yozilsa darvoza har build'da
   YOLG'ON qizil bo'lardi. O'lchamlar operator hisobotida qaytariladi.
⚠️ Yig'ma MAVJUD BO'LMASA — qaror PLATFORMAGA bog'liq: yig'ma QURILISHI mumkin bo'lgan
   platformada (Windows) YIQILISH, boshqasida ANIQ SABAB bilan `skip`
   (`tests/ci_expected_skips.txt` da ratifikatsiya qilingan). Yig'ma BOR, lekin JORIY
   manbadan qurilgani isbotlanmagan bo'lsa — HAR PLATFORMADA YIQILISH, jim skip EMAS.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import importlib.util
import inspect
import os
import pathlib
import sys
import zipfile

import pytest
import textwrap

# ── Yig'ma va manba joylashuvi ──────────────────────────────────────────────────────────
#: ⚠️ Yig'ma ATAYLAB repo TASHQARISIDA: repo daraxti toza qoladi, `.gitignore` o'zgarmaydi.
#: ⚠️⚠️ ILDIZ QO'LDA YOZILMAYDI. Ilgari bu yerda `C:/Users/Developer/binos-agent-build`
#:      turardi — ya'ni (a) ishlab chiquvchining MUTLAQ yo'li, bu esa spec faylining O'Z
#:      qoidasiga («hardcoded developer path bo'lmasin») zid, va (b) `parity_harness`
#:      boshqa ildizni ko'rsatganda ikki darvoza jimgina BOSHQA yig'mani tekshirardi:
#:      biri eskisini «toza» deb, ikkinchisi yangisini o'lchab. Endi ikkisi AYNI muhit
#:      o'zgaruvchisidan keladi va tengligi `test_agent_parity.py` dagi
#:      `test_A_yigma_ILDIZI_UCH_modulda_AYNI` bilan QULFLANGAN.
_YIGMA_ILDIZ = pathlib.Path(os.environ.get("BINOS_AGENT_BUILD_ROOT")
                            or pathlib.Path.home() / "binos-agent-build")
_DIST = _YIGMA_ILDIZ / "dist-onedir" / "BinOSDiscoveryAgent"
_BUILD = _YIGMA_ILDIZ / "build-onedir" / "BinOSDiscoveryAgent"
_EXE = _DIST / "BinOSDiscoveryAgent.exe"

#: `apps/server` — modul nomlarini fayl yo'liga aylantirish uchun ildiz.
_SERVER = pathlib.Path(__file__).resolve().parents[1]
_AGENT_DIR = _SERVER / "app" / "services" / "discovery_agent"
_SPEC = _SERVER / "packaging" / "BinOSDiscoveryAgent.spec"
_ENTRY = _SERVER / "packaging" / "binos_agent_entry.py"


# ── Skip sabablari (ANIQ matn: «nega o'tkazib yuborildi» savoli ochiq qolmasin) ──────────
#: ⚠️ `tests/ci_expected_skips.txt` dagi sabab bo'lagi AYNAN shu satr (shu moduldagi
#:    HAMMA yig'ma skip'i uchun). ⚠️ `parity_harness.MUHIT_SABABI` dan ATAYLAB BOSHQA:
#:    ikki darvozaning skip'lari ro'yxatda ARALASHMASLIGI kerak — biri yo'qolsa ikkinchisi
#:    uning yozuviga «yashirinib» o'tib ketardi.
_MUHIT_SABABI = "MUHIT: Windows yig'masi Linux CI'da QURILMAYDI"


# ══════════════════════════════════════════════════════════════════════════════════════════
# ESKIRGAN YIG'MA DARVOZASI — bu modul uchun ham MAJBURIY
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ O'LCHANGAN TESHIK (shu worktree'da): mahalliy `.exe` uch moduldan eskirgan edi
#      (`discovery_1c/redact.py`, `discovery_agent/detector.py`,
#      `discovery_agent/launcher.py`) — `test_agent_parity.py` BALAND yiqildi va uchtasini
#      NOMLADI, bu modul esa `25 passed, 0 skipped` berdi. Ya'ni yig'ma TARKIBI darvozasi
#      ESKIRGAN artefaktni «toza» deb TASDIQLADI.
#
# ⚠️ NEGA (A) MANIFEST TENGLIGI YETMAYDI: oldingi `_manifest_talab()` faqat build-dagi
#    `.exe` ↔ dist-dagi `.exe` BAYT tengligini o'lchardi. Ikkisi ham AYNI, ESKI yig'madan
#    bo'lsa tenglik SAQLANADI — ya'ni o'lchov «manifest shu artefaktni tasvirlaydimi»
#    degan savolga javob beradi, «artefakt JORIY manbadan qurilganmi» degan savolga EMAS.
#
# ⚠️ NEGA (B) ARTEFAKT TEKSHIRUVLARI HAM SHU DARVOZADAN O'TADI: bu moduldagi HAR bir
#    da'vo JORIY manba haqidagi da'vo bo'lib o'qiladi — «biz tarqatadigan `.exe` da test
#    kodi YO'Q», «ishlab chiquvchi yo'li YO'Q», «mijoz ulanish satri YO'Q», «taqiqlangan
#    migrator moduli YO'Q». Eskirgan artefaktda bu da'volar YOLG'ON yashil bo'ladi:
#    manbaga BUGUN kiritilgan sir yoki taqiqlangan import ESKI `.exe` da ko'rinmaydi.
#    Shu bois darvoza `_dist_talab()` da — ya'ni (A) va (B) ning UMUMIY ildizida.
#
# ⚠️ Darvoza QAYTA YOZILMAYDI: hukm `packaging/parity_harness.yigma_tayyorligi()` dan
#    OLINADI (OWNER B). Ikkinchi nusxa bir kun ajralib ketardi va ikki darvoza jimgina
#    BOSHQA javob berardi.
_HARNESS_YOLI = _SERVER / "packaging" / "parity_harness.py"

#: ⚠️ `test_agent_parity.py` harnessni AYNI shu nom bilan `sys.modules` ga qo'yadi —
#:    mavjud nusxa QAYTA ISHLATILADI. Aks holda bir yurishda IKKI modul nusxasi paydo
#:    bo'lardi va ularning biriga qo'yilgan o'lchov (masalan muhit taqlidi) ikkinchisiga
#:    ta'sir qilmasdi.
_HARNESS_MODUL_NOMI = "binos_parity_harness"


def _harness():
    """OWNER B darvozasi — YO'L bilan va KECHIKTIRILGAN holda yuklanadi.

    ⚠️⚠️ `from packaging.parity_harness import ...` ISHLAMAYDI: `packaging` nomi PyPI
         paketi bilan to'qnashadi (oddiy paket nom bo'shliqli paketdan USTUN turadi).
         `test_agent_parity.py` dagi `_harnessni_yukla()` bilan AYNI usul.
    ⚠️ KECHIKTIRILGAN (import paytida emas, darvoza chaqirilganda): bu modulni
       `test_agent_parity.py` IMPORT qiladi, ya'ni import paytidagi har qanday ishni
       ikki modul BIRGA to'laydi; bundan tashqari `sys.modules` dagi nusxa shu
       paytgacha allaqachon paydo bo'lgan bo'ladi.
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


def _yoqlik_qarori(*, qurilishi_mumkin: bool) -> tuple[str, str]:
    """`.exe` UMUMAN YO'Q bo'lganda: `(qaror, matn)`.

    ⚠️⚠️ «EXE yo'q bo'lsa skip» SHARTSIZ EMAS va bu ataylab: yig'ma QURILISHI mumkin
         bo'lgan platformada (Windows) yo'qligi OPERATORNING ishi, muhit cheklovi EMAS —
         u yerda yig'ma TARKIBI o'lchanmagani SKIP bo'lib ko'rinmasligi kerak. Ilgari bu
         himoya faqat `packaging/BUILD_GATE.md` cheklistining `0 skipped` shartida, ya'ni
         HUJJATDA edi; endi KODDA.
    ⚠️ Skip matni `_MUHIT_SABABI` bilan BOSHLANADI — `tests/ci_expected_skips.txt` dagi
       sabab bo'lagi AYNAN shu satr (o'zgartirilsa ro'yxat ham yangilanadi).
    """
    if qurilishi_mumkin:
        return _QAROR_YIQIL, (
            f"YIG'MA TARKIBI O'LCHANMADI: {_EXE} topilmadi, LEKIN bu platformada "
            f"(`{sys.platform}`) yig'ma QURILADI — ya'ni yo'qligi MUHIT cheklovi EMAS va "
            f"skip bo'lib o'tib ketishi TAQIQLANGAN. Reliz darvozasi "
            f"(`packaging/BUILD_GATE.md`) bo'yicha yig'ing, build papkasini SAQLAB "
            f"(`--workpath`), so'ng shu modulni qayta yurgizing.")
    return _QAROR_SKIP, (
        f"{_MUHIT_SABABI}. Yig'ma YO'Q: {_EXE} topilmadi. Yig'ma repo tashqarisida "
        f"quriladi (`pyinstaller packaging/BinOSDiscoveryAgent.spec`) va PyInstaller "
        f"kross-kompilyatsiya QILMAYDI, shu bois Linux backend job'ida u bo'lmasligi "
        f"MUHIT cheklovi. Yig'ma TARKIBI shu yurishda tekshirilmadi; yig'ma "
        f"SHARTNOMASI manbadan tekshirildi (`tests/test_agent_parity.py::test_A_*`), "
        f"tarkibning o'zi esa Windows reliz darvozasida (`packaging/BUILD_GATE.md`).")


def _yangilik_qarori(holat: str, sabab: str, *, toza: str) -> str | None:
    """`None` — yig'ma JORIY manbadan qurilgani ISBOTLANDI; aks holda YIQILISH matni.

    ⚠️⚠️ FAIL-CLOSED va PLATFORMAGA BOG'LIQ EMAS: `toza` dan BOSHQA HAR holat
         (`ESKIRGAN`, `ISBOTSIZ`, va hatto `YO_Q` — harness BOSHQA `.exe` yo'liga
         qarasa, `BINOS_AGENT_EXE`) YIQILISH beradi. JIM SKIP YO'Q: eskirgan yig'ma
         «toza» deb tasdiqlanishining yo'li aynan shu edi.
    ⚠️ `sabab` harnessdan KELGANIDEK uzatiladi — nomos modullar ro'yxati va tuzatish
       yo'li o'sha matnda.
    """
    if holat == toza:
        return None
    return (f"YIG'MA TARKIBI DARVOZASI O'LCHANMADI (holat: {holat}) — tarqatiladigan "
            f"yig'ma JORIY manbadan qurilgani ISBOTLANMADI. Shu moduldagi «yig'mada X "
            f"YO'Q / Y BOR» da'volari ESKI artefakt haqida bo'lardi va manbaga BUGUN "
            f"kiritilgan taqiqlangan import yoki sir ko'rinmay qolardi (yolg'on "
            f"kafolat). {sabab}")


def _dist_talab() -> None:
    """Tarqatiladigan yig'ma BOR va JORIY manbadan qurilgani ISBOTLANGAN bo'lsin.

    ⚠️ `_EXE.exists()` AVVAL o'lchanadi — shu modulning O'Z yo'li bilan: harness
       `BINOS_AGENT_EXE` bilan boshqa `.exe` ga yo'naltirilgan bo'lsa, ikki darvoza
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


def _sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest_talab() -> dict:
    """(A) manbani qaytaradi — OLDIN `_dist_talab()` darvozasidan o'tib.

    ⚠️⚠️ BU YERDA SKIP YO'Q. Ilgari uchta holat (manifest fayli YO'Q · build `.exe` YO'Q ·
         build `.exe` ↔ dist `.exe` FARQ qiladi) JIM SKIP berardi va aynan shu skip'lar
         «artefakt darajasidagi testlar baribir ishlaydi» degan izoh bilan oqlangan edi.
         Endi `_dist_talab()` yig'maning JORIY manbadan qurilganini ISBOTLAYDI, ya'ni
         pastdagi ikki holat (build `.exe` YO'Q yoki FARQ qiladi) umuman YETIB
         BORILMAYDI — ular `ISBOTSIZ` bo'lib yuqorida yiqiladi. Qolgani (faqat
         `Analysis-00.toc` o'chirilgan) — reliz validatsiyasi paytidagi ZIDDIYAT, muhit
         cheklovi EMAS: yig'ma yangi, lekin TARKIBI o'lchanmaydi. Shu bois YIQILISH.
    ⚠️ Ikki holat SAQLANDI (o'chirilmadi): ular darvozaning ikkinchi qatlami — harness
       semantikasi bir kun yumshasa, bu yerda JIM SKIP paydo bo'lmasin.
    """
    _dist_talab()
    analysis = _BUILD / "Analysis-00.toc"
    build_exe = _BUILD / "BinOSDiscoveryAgent.exe"
    if not analysis.exists():
        pytest.fail(
            f"Yig'uvchi manifesti YO'Q: {analysis} topilmadi (build papkasi tozalangan), "
            f"lekin yig'ma JORIY manbadan qurilgani ISBOTLANGAN — ya'ni bu MUHIT cheklovi "
            f"emas, o'lchov yo'qolgan. Spec'ni `--workpath` bilan QAYTA yig'ib build "
            f"papkasini SAQLANG (`packaging/BUILD_GATE.md`).")
    if not build_exe.exists():
        pytest.fail(f"Manifest yangiligini isbotlab bo'lmadi: {build_exe} YO'Q.")
    if _sha256(build_exe) != _sha256(_EXE):
        pytest.fail(
            "Yig'uvchi manifesti ESKIRGAN: build papkasidagi `.exe` dist papkasidagi "
            "`.exe` dan FARQ qiladi, demak `Analysis-00.toc` tarqatiladigan yig'mani "
            "TASVIRLAMAYDI. Tuzatish: spec'ni QAYTA yig'ib, build va dist papkalarini "
            "birga yangilang.")
    return _manifest_oqi(analysis)


# ── (A) yig'uvchi manifestini o'qish ────────────────────────────────────────────────────
def _manifest_oqi(analysis: pathlib.Path) -> dict:
    """`Analysis-00.toc` ni Python literali sifatida o'qiydi.

    ⚠️ POZITSIYAGA TAYANMAYDI: PyInstaller bo'laklarning tartibini o'zgartirsa test
       YOLG'ON yashil bo'lmasligi kerak, shu bois har bo'lak SHAKLI bo'yicha (uchlik
       yozuvlar + `PYMODULE`/`PYSOURCE`/`BINARY` belgisi) tanlanadi.
    """
    t = ast.literal_eval(analysis.read_text(encoding="utf-8"))
    excludes = next(
        (x for x in t if isinstance(x, list) and x
         and all(isinstance(e, str) for e in x) and "pytest" in x), None)
    assert excludes is not None, "Analysis-00.toc ichida `excludes` ro'yxati topilmadi"

    boleklar = [x for x in t if isinstance(x, list) and x
                and all(isinstance(e, tuple) and len(e) == 3 for e in x)]
    assert boleklar, "Analysis-00.toc ichida TOC bo'laklari topilmadi"

    def tur_bilan(*belgilar: str) -> set[str]:
        return {nom for b in boleklar for nom, _yol, tur in b if tur in belgilar}

    manifest = {
        "excludes": list(excludes),
        # PYMODULE = PYZ (`pure`) VA `base_library.zip` (`zipped_data`) — ikkisi ham modul.
        "modullar": tur_bilan("PYMODULE"),
        "scriptlar": tur_bilan("PYSOURCE"),
        "binarlar": tur_bilan("BINARY", "EXTENSION"),
    }
    # ⚠️ Shakl darvozasi: bo'sh ro'yxat hamma «yo'q» testini YOLG'ON yashil qilardi.
    assert len(manifest["modullar"]) > 50, \
        f"manifestda modul juda kam ({len(manifest['modullar'])}) — o'qish usuli buzilgan"
    assert manifest["scriptlar"], "manifestda PYSOURCE yozuvi yo'q — o'qish usuli buzilgan"
    assert manifest["binarlar"], "manifestda BINARY yozuvi yo'q — o'qish usuli buzilgan"
    return manifest


# ── (B) tarqatiladigan artefaktni o'qish ────────────────────────────────────────────────
def _exe_baytlari() -> bytes:
    _dist_talab()
    return _EXE.read_bytes()


def _dist_fayllari() -> list[pathlib.Path]:
    _dist_talab()
    return sorted(p for p in _DIST.rglob("*") if p.is_file())


def _nom_exe_da(nom: str, baytlar: bytes) -> bool:
    """Modul nomi `.exe` ichidagi PYZ TOC da ASCII matn sifatida uchraydimi."""
    return nom.encode("ascii") in baytlar


# ── Manbadagi import grafi («nega shu modul kerak» savoliga javob) ──────────────────────
def _modul_fayli(mod: str) -> pathlib.Path | None:
    p = _SERVER.joinpath(*mod.split("."))
    if (p / "__init__.py").exists():
        return p / "__init__.py"
    if p.with_suffix(".py").exists():
        return p.with_suffix(".py")
    return None


def _app_importlari(path: pathlib.Path, paket: str) -> set[str]:
    """Fayldagi `app.*` importlari. Nisbiy importlar (`from ..x import y`) ham yechiladi."""
    daraxt = ast.parse(path.read_text(encoding="utf-8"))
    chiqdi: set[str] = set()
    for n in ast.walk(daraxt):
        if isinstance(n, ast.Import):
            chiqdi.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                bolaklar = paket.split(".")
                if n.level > 1:
                    bolaklar = bolaklar[:len(bolaklar) - (n.level - 1)]
                ildiz = ".".join(bolaklar)
                mod = f"{ildiz}.{n.module}" if n.module else ildiz
            else:
                mod = n.module or ""
            chiqdi.add(mod)
            # ⚠️ `from paket import a` da `a` ning O'ZI modul bo'lishi mumkin.
            chiqdi.update(f"{mod}.{a.name}" for a in n.names)
    return {m for m in chiqdi if m == "app" or m.startswith("app.")}


def _manbadan_yetib_boriladigan() -> set[str]:
    """Kirish skriptidan BOSHLAB import bo'yicha yetib boriladigan `app.*` modullar.

    ⚠️ Ota-paketlar QO'SHILADI: `...analyst.heuristics` kerak bo'lsa `...analyst` paketi
       ham yig'maga kiradi — paketsiz modulni import qilib bo'lmaydi.
    """
    korilgan: set[str] = set()
    navbat = collections.deque(_app_importlari(_ENTRY, "app"))
    while navbat:
        m = navbat.popleft()
        if m in korilgan:
            continue
        f = _modul_fayli(m)
        if f is None:                 # modul emas (funksiya/klass nomi) — tashlab ketiladi
            continue
        korilgan.add(m)
        paket = m if f.name == "__init__.py" else m.rsplit(".", 1)[0]
        navbat.extend(c for c in _app_importlari(f, paket) if c not in korilgan)
    otalar = {".".join(m.split(".")[:i])
              for m in korilgan for i in range(1, len(m.split(".")))}
    return korilgan | {o for o in otalar if _modul_fayli(o) is not None}


def _spec_excludes() -> list[str]:
    """Spec faylidan `EXCLUDES` ro'yxatini O'QIYDI (testda KO'CHIRMA saqlanmaydi).

    ⚠️ Nega o'qiladi, nega ko'chirilmaydi: ro'yxat ikki joyda yozilsa, spec'dan modul
       olib tashlangani testda SEZILMAY qolardi va darvoza eskirgan ro'yxatni qo'riqlardi.
    """
    daraxt = ast.parse(_SPEC.read_text(encoding="utf-8"))
    for n in daraxt.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EXCLUDES" for t in n.targets):
            return list(ast.literal_eval(n.value))
    raise AssertionError("spec ichida `EXCLUDES` topilmadi")


def _app_modullari(manifest: dict) -> set[str]:
    return {m for m in manifest["modullar"] if m == "app" or m.startswith("app.")}


def _qamralgan(modullar: set[str], taqiq: str) -> set[str]:
    """`taqiq` ning O'ZI yoki uning OSTIDAGI modullar yig'mada bormi."""
    return {m for m in modullar if m == taqiq or m.startswith(taqiq + ".")}


def _agent_manba_modullari() -> set[str]:
    """Agent paketidagi HAMMA manba moduli (ro'yxat testga YOZILMAYDI)."""
    nomlar = {
        "app.services.discovery_agent" if f.name == "__init__.py"
        else f"app.services.discovery_agent.{f.stem}"
        for f in _AGENT_DIR.glob("*.py")
    }
    assert len(nomlar) >= 8, f"agent manba papkasi kutilganidan kichik: {sorted(nomlar)}"
    return nomlar


# ═══ 0. DARVOZANING O'ZI: eskirgan yig'ma JIMGINA o'tib ketolmaydi ═════════════════════
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


def test_darvoza_ESKIRGAN_yigmani_JIM_otkazib_yubormaydi():
    """⚠️⚠️ BRIF TALABI shu testda qadalgan: «eskirgan yig'ma reliz validatsiyasidan
         JIMGINA o'tib ketolmasligi ISBOTLANSIN». Qaror jadvali `.exe` DAN MUSTAQIL
         o'lchanadi, ya'ni bu test Linux CI'da ham BAJARILADI va shu bois
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
    """
    PH = _harness()
    assert _yangilik_qarori(PH.HOLAT_TOZA, "", toza=PH.HOLAT_TOZA) is None, \
        "`TOZA` holat DAVOM etmadi — darvoza yolg'on qizil beradi"
    for holat in (PH.HOLAT_ESKIRGAN, PH.HOLAT_ISBOTSIZ, PH.HOLAT_YOQ):
        matn = _yangilik_qarori(holat, f"<SABAB:{holat}>", toza=PH.HOLAT_TOZA)
        assert matn is not None, \
            f"`{holat}` holati JIMGINA o'tib ketdi — yig'ma TARKIBI darvozasi TESHIK"
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


# ═══ 0b. Manifest TARQATILAYOTGAN yig'mani tasvirlaydi ═════════════════════════════════
def test_yiguvchi_manifesti_shu_exe_ni_tasvirlaydi():
    """⚠️ Manifestga tayangan HAMMA test shu isbotga suyanadi, shu bois u ALOHIDA test
    bo'lib turadi: bu skip bo'lsa, qolganlari ham skip bo'lgani KO'RINADI."""
    _manifest_talab()
    assert _sha256(_BUILD / "BinOSDiscoveryAgent.exe") == _sha256(_EXE)


# ═══ 1. MIGRATOR APPLY yig'mada YO'Q ═══════════════════════════════════════════════════
_MIGRATOR_TAQIQ = (
    "app.services.migrator_1c.apply",
    "app.services.migrator_1c.actor",
    "app.services.migrator_1c.catalog",
    "app.services.migrator_1c.classify",
    "app.services.migrator_1c.freshness",
    "app.services.migrator_1c.guard",
    "app.services.migrator_1c.mapping",
    "app.services.migrator_1c.normalize",
)


def test_migrator_apply_manifestda_yoq():
    """⚠️ YOZUVCHI migrator yig'maga TUSHMAYDI: agent faqat-O'QISH vositasi va u bazaga
    yozadigan kodni OLIB YURMASLIGI kerak (Phase 4 shartnomasi)."""
    modullar = _app_modullari(_manifest_talab())
    buzilgan = {t: sorted(_qamralgan(modullar, t)) for t in _MIGRATOR_TAQIQ}
    buzilgan = {k: v for k, v in buzilgan.items() if v}
    assert not buzilgan, f"Yig'maga migrator APPLY modullari kirgan: {buzilgan}"


def test_migrator_dan_faqat_bundle_kirgan():
    """`migrator_1c` dan yig'mada AYNAN IKKI nom: paketning o'zi va `bundle`."""
    migrator = _qamralgan(_app_modullari(_manifest_talab()), "app.services.migrator_1c")
    assert migrator == {"app.services.migrator_1c", "app.services.migrator_1c.bundle"}, \
        f"`migrator_1c` dan kutilmagan modullar: {sorted(migrator)}"


def test_migrator_apply_tarqatilgan_exe_baytlarida_ham_yoq():
    """(B) MUSTAQIL tekshiruv: PYZ TOC modul nomlarini SIQILMAGAN saqlaydi, shu bois
    taqiqlangan modul `.exe` baytlarida ko'rinib qolardi."""
    baytlar = _exe_baytlari()
    topildi = [t for t in _MIGRATOR_TAQIQ if _nom_exe_da(t, baytlar)]
    assert not topildi, f"`.exe` baytlarida taqiqlangan migrator moduli bor: {topildi}"
    # Usul ishlayotganining isboti: KIRISHI KERAK bo'lgan nom baytlarda BOR.
    assert _nom_exe_da("app.services.migrator_1c.bundle", baytlar), \
        "`migrator_1c.bundle` `.exe` baytlarida topilmadi — qidiruv usuli ishlamayapti"


#: ⚠️ `migrator_1c.bundle` dan OLINISHI RUXSAT ETILGAN nomlar. Ro'yxat qisqa va ATAYLAB:
#   har biri `normalize` ga TEGMAYDIGAN yo'l.
_BUNDLE_RUXSAT = {"BundleError", "parse_ts", "sha256_bytes", "strict_json_loads"}


def _yigmaga_kiradigan_manba_fayllari() -> list[pathlib.Path]:
    """Yig'maga KIRADIGAN har bir `app.*` modulining manba fayli (+ kirish skripti).

    ⚠️ NEGA FAQAT `discovery_agent/` NI SKANER QILISH YETMAYDI: `migrator_1c.bundle` dan
       nom oladigan modullar `discovery_1c/` ichida HAM bor (`bundle`, `metadata`, `ai`,
       `confirmations`, `runtime_bundle`), va ular YIG'MAGA KIRADI. Faqat agent papkasi
       tekshirilsa, darvoza YOLG'ON yashil bo'lardi.
    """
    fayllar = [_ENTRY]
    for m in sorted(_manbadan_yetib_boriladigan()):
        if m == "app.services.migrator_1c.bundle":
            continue               # ⚠️ `bundle` o'zi: kechiktirilgan import AYNAN unda
        f = _modul_fayli(m)
        if f is not None:
            fayllar.append(f)
    assert len(fayllar) > 20, f"skaner qilinadigan manba juda kam: {len(fayllar)}"
    return fayllar


def test_bundle_dan_faqat_tort_yordamchi_olinadi():
    """⚠️ NEGA BU DARVOZA BOR: `migrator_1c/bundle.py` ichidagi `_canon_guid_text`
    `from .normalize import canon_guid` qiladi, `normalize` esa yig'madan CHIQARILGAN
    (PyInstaller buni `warn-*.txt` da «excluded module named ...normalize» deb yozadi).
    Ya'ni yig'madagi kod shu yo'lga TUSHSA, MANBADA ishlaydigan chaqiruv YIG'MADA
    `ModuleNotFoundError` berardi — manba va yig'ma AJRALADI. Hozir xavf YO'Q, chunki
    yig'madagi HAMMA modul `bundle` dan faqat `normalize` ga tegmaydigan TO'RT nomni
    oladi. AYNI shu holat qulflanadi.
    """
    olinganlar: dict[str, set[str]] = {}
    for f in _yigmaga_kiradigan_manba_fayllari():
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(
                    "migrator_1c.bundle"):
                olinganlar.setdefault(f.name, set()).update(a.name for a in n.names)
    assert olinganlar, "yig'madagi hech bir modul `migrator_1c.bundle` dan nom olmaydi — " \
                       "skaner buzilgan yoki bog'liqlik yo'qolgan"
    buzilgan = {k: sorted(v - _BUNDLE_RUXSAT) for k, v in olinganlar.items()}
    buzilgan = {k: v for k, v in buzilgan.items() if v}
    assert not buzilgan, (
        f"Yig'madagi modul `migrator_1c.bundle` dan RUXSATSIZ nom oladi: {buzilgan}. "
        f"`normalize` yig'madan chiqarilgan — avval spec'ni QAYTA ko'rib chiqing.")

    # `normalize` ga olib boradigan YAGONA yo'l yig'madagi hech bir modulda ishlatilmaydi.
    for f in _yigmaga_kiradigan_manba_fayllari():
        matn = f.read_text(encoding="utf-8")
        assert "_canon_guid_text" not in matn, \
            f"{f}: migrator kanonik yo'li ishlatilgan — u yig'mada YIQILADI"


# ═══ 2. TESTLAR va sinov vositalari yig'mada YO'Q ═══════════════════════════════════════
_TEST_TAQIQ = ("pytest", "_pytest", "pluggy", "hypothesis", "coverage", "tests", "conftest")


def test_testlar_manifestda_yoq():
    """⚠️ To'plam kodi yig'maga tushmasin: u operator mashinasida BAJARILADIGAN, lekin
    hech kim kutmaydigan kod bo'lardi."""
    modullar = _manifest_talab()["modullar"]
    topildi = sorted({m for t in _TEST_TAQIQ for m in _qamralgan(modullar, t)})
    topildi += sorted(m for m in modullar if m.rsplit(".", 1)[-1].startswith("test_"))
    assert not topildi, f"Yig'maga test kodi kirgan: {topildi}"


def test_testlar_tarqatilgan_artefaktda_yoq():
    """(B): `.exe` baytlari + `base_library.zip` nomlari + papkadagi fayl nomlari."""
    baytlar = _exe_baytlari()
    exe_da = [t for t in ("pytest", "_pytest", "pluggy", "hypothesis", "conftest")
              if _nom_exe_da(t, baytlar)]
    assert not exe_da, f"`.exe` baytlarida test vositasi nomi bor: {exe_da}"

    zp = _DIST / "_internal" / "base_library.zip"
    assert zp.exists(), f"{zp} yo'q — yig'ma to'liq emas"
    with zipfile.ZipFile(zp) as z:
        nomlar = z.namelist()
    yomon = [n for n in nomlar
             if any(x in n.lower() for x in ("pytest", "conftest", "test_", "tests/"))]
    assert not yomon, f"`base_library.zip` ichida test fayllari: {yomon}"

    yomon = [p.name for p in _dist_fayllari()
             if p.name.lower().startswith("test_") or p.name.lower() == "conftest.py"]
    assert not yomon, f"Yig'ma papkasida test fayllari: {yomon}"


# ═══ 3. TARMOQ kutubxonalari yig'mada YO'Q ══════════════════════════════════════════════
#: ⚠️ `socket`/`_socket` bu ro'yxatda ATAYLAB YO'Q: ular stdlib bo'lagi va
#   `base_library.zip` ga Python o'zi tortadi (`urllib.parse` → `socket`). Agent ularni
#   ISHLATMAYDI; darvoza esa MIJOZ kutubxonalarini — ya'ni «tashqariga murojaat qilish
#   qulayligini» — to'sadi.
_TARMOQ_TAQIQ = ("requests", "httpx", "urllib3", "aiohttp", "smtplib", "ftplib",
                 "websockets", "paramiko", "telnetlib", "xmlrpc")


def test_tarmoq_kutubxonalari_manifestda_yoq():
    """⚠️ Agent OFFLINE: yig'mada HTTP/SMTP/FTP mijozi bo'lmasligi kerak."""
    topildi = sorted({m for t in _TARMOQ_TAQIQ
                      for m in _qamralgan(_manifest_talab()["modullar"], t)})
    assert not topildi, f"Yig'maga tarmoq kutubxonasi kirgan: {topildi}"


def test_tarmoq_kutubxonalari_tarqatilgan_exe_da_yoq():
    baytlar = _exe_baytlari()
    topildi = [t for t in _TARMOQ_TAQIQ if _nom_exe_da(t, baytlar)]
    assert not topildi, f"`.exe` baytlarida tarmoq kutubxonasi nomi bor: {topildi}"


# ═══ 4. SERVER va DB yig'mada YO'Q ══════════════════════════════════════════════════════
_SERVER_DB_TAQIQ = ("fastapi", "starlette", "uvicorn", "sqlalchemy", "alembic",
                    "psycopg", "psycopg2", "asyncpg", "pydantic", "pydantic_core",
                    "pydantic_settings", "sqlite3", "jose", "bcrypt", "firebase_admin",
                    "anthropic", "app.main", "app.models", "app.db", "app.routers",
                    "app.core")


def test_server_va_db_manifestda_yoq():
    """⚠️ Agent serverga ULANMAYDI va bazaga YOZMAYDI — bu kodni OLIB YURISHI ham kerak
    emas. Server freymvorki yig'maga tushsa, bu shunchaki HAJM emas: yig'ma ichida
    tashqi aloqa va DB drayveri paydo bo'lardi."""
    topildi = sorted({m for t in _SERVER_DB_TAQIQ
                      for m in _qamralgan(_manifest_talab()["modullar"], t)})
    assert not topildi, f"Yig'maga server/DB kodi kirgan: {topildi}"


def test_server_va_db_tarqatilgan_exe_da_yoq():
    baytlar = _exe_baytlari()
    topildi = [t for t in _SERVER_DB_TAQIQ if _nom_exe_da(t, baytlar)]
    assert not topildi, f"`.exe` baytlarida server/DB moduli nomi bor: {topildi}"


# ═══ 5. KERAKLISI yig'mada BOR ══════════════════════════════════════════════════════════
def test_agentning_hamma_moduli_yigmada_bor():
    """⚠️ Kutilgan ro'yxat MANBADAN (fayllar ro'yxatidan) olinadi, testga YOZILMAYDI:
    agentga yangi modul qo'shilib yig'maga tushmasa, bu test DARROV yiqiladi."""
    yetmaydi = sorted(_agent_manba_modullari() - _manifest_talab()["modullar"])
    assert not yetmaydi, f"Agent modullari yig'maga KIRMAGAN: {yetmaydi}"


def test_discovery_1c_yadrosi_yigmada_bor():
    """Agent Phase 3/4 yadrosiga TAYANADI — u yig'mada bo'lishi SHART."""
    modullar = _manifest_talab()["modullar"]
    kerak = {
        "app.services.discovery_1c",
        "app.services.discovery_1c.bundle",
        "app.services.discovery_1c.probe",
        "app.services.discovery_1c.metadata",
        "app.services.discovery_1c.graph",
        "app.services.discovery_1c.redact",
        "app.services.discovery_1c.runtime_bundle",
        "app.services.discovery_1c.export_adapter",
        "app.services.discovery_1c.confirmations",
        "app.services.discovery_1c.ai",
        "app.services.discovery_1c.analyst",
        "app.services.discovery_1c.analyst.heuristics",
        "app.services.discovery_1c.analyst.lexicon",
    }
    yetmaydi = sorted(kerak - modullar)
    assert not yetmaydi, f"`discovery_1c` yadrosi yig'maga kirmagan: {yetmaydi}"


def test_tkinter_va_oyna_kutubxonasi_yigmada_bor():
    """⚠️ `tkinter` himoyalangan `import` ichida — statik tahlil uni O'TKAZIB YUBORISHI
    mumkin, shu bois spec'da `hiddenimports`. Oyna rejimi yig'mada ISHLASHI kerak, va
    modul o'zi yetarli emas: mahalliy kutubxona ham kerak."""
    manifest = _manifest_talab()
    kerak = {"tkinter", "tkinter.ttk", "tkinter.filedialog",
             "tkinter.messagebox", "tkinter.scrolledtext"}
    yetmaydi = sorted(kerak - manifest["modullar"])
    assert not yetmaydi, f"tkinter modullari yig'maga kirmagan: {yetmaydi}"
    binarlar = {b.lower() for b in manifest["binarlar"]}
    assert "_tkinter.pyd" in binarlar, f"`_tkinter.pyd` yig'mada yo'q: {sorted(binarlar)}"
    assert (_DIST / "_internal" / "_tkinter.pyd").exists(), \
        "`_tkinter.pyd` tarqatiladigan papkada YO'Q — oyna rejimi ishlamaydi"


def test_yigmadagi_app_modullari_manbadagi_zaruratga_AYNAN_mos():
    """⚠️ IKKI TOMONLAMA darvoza: yig'mada KERAKSIZ `app.*` moduli BO'LMASIN va KERAKLISI
    YETMASIN. Kutilgan to'plam manbadagi IMPORT GRAFIDAN hisoblanadi (kirish skriptidan
    boshlab), ya'ni test ikkinchi haqiqat yozmaydi.

    ⚠️ YAGONA ATAYLAB FARQ — `migrator_1c.normalize`: import grafi uni KO'RADI (`bundle.py`
       dagi kechiktirilgan import), lekin spec uni CHIQARIB tashlagan. Bu farqning
       XAVFSIZLIGI `test_bundle_dan_faqat_tort_yordamchi_olinadi` da isbotlanadi.
    """
    yigmada = _app_modullari(_manifest_talab())
    kutilgan = _manbadan_yetib_boriladigan() - {"app.services.migrator_1c.normalize"}
    assert yigmada == kutilgan, (
        f"Yig'madagi `app.*` to'plami manbadagi zaruratdan FARQ qiladi.\n"
        f"  ORTIQCHA (manba talab qilmaydi): {sorted(yigmada - kutilgan)}\n"
        f"  YETMAYDI (manba talab qiladi):   {sorted(kutilgan - yigmada)}")


# ═══ 6. SIR va MA'LUMOT fayllari yig'mada YO'Q ══════════════════════════════════════════
#: Yig'ma papkasida UCHRASHI MUMKIN bo'lgan kengaytmalar. ⚠️ Ro'yxat YOPIQ: yangi
#  kengaytma paydo bo'lsa test yiqiladi va odam uni KO'RIB tasdiqlaydi.
_RUXSAT_KENGAYTMA = {
    ".exe", ".dll", ".pyd", ".zip",     # yig'ma yadrosi
    ".tcl", ".tm", ".msg", ".enc",      # Tcl/Tk (tkinter oynasi uchun)
    ".gif", ".eps",                     # Tk kursor/demo resurslari
    ".terms",                           # `license.terms` (Tcl/Tk litsenziyasi)
    "",                                 # kengaytmasiz: tzdata, tclIndex, README
}
#: ⚠️ Sir/ma'lumot IZLARI: BITTASI ham bo'lmasligi kerak.
_SIR_NAQSHI = (".env", "*.env", ".env.*", "*.db", "*.sqlite", "*.sqlite3", "*.dump",
               "*.sql", "*.pem", "*.key", "*.pfx", "*.p12", "*.crt", "*.jks",
               "*credential*", "*secret*", "*password*", "*.log", "*.bak",
               "id_rsa*", "*.ppk", "*.epf", "*.cf", "*.dt", "*.1cd", "*.json")


def test_sir_va_malumot_fayllari_yigmada_yoq():
    """⚠️ Operatorga beriladigan papkada SIR ham, MA'LUMOT BAZASI ham, kalit ham
    BO'LMASIN: papka qo'ldan qo'lga o'tadi va u yerdagi HAR FAYL tarqaydi."""
    fayllar = _dist_fayllari()
    assert fayllar, "yig'ma papkasi bo'sh"
    topildi = sorted({str(p.relative_to(_DIST)) for p in fayllar
                      for n in _SIR_NAQSHI if p.match(n)})
    assert not topildi, f"Yig'mada sir/ma'lumot fayli bor: {topildi}"
    kataloglar = {q.name for q in _DIST.rglob("*") if q.is_dir()}
    begona = {".git", ".venv", "venv", "__pycache__", "node_modules"} & kataloglar
    assert not begona, f"Yig'mada repo/muhit papkasi bor: {sorted(begona)}"


def test_yigmadagi_kengaytmalar_hammasi_kutilgan():
    """Papkadagi HAMMA faylning kengaytmasi sanaladi; kutilmagani XABAR qilinadi."""
    kengaytmalar = {p.suffix.lower() for p in _dist_fayllari()}
    kutilmagan = sorted(kengaytmalar - _RUXSAT_KENGAYTMA)
    assert not kutilmagan, (
        f"Yig'mada KUTILMAGAN kengaytma bor: {kutilmagan}. Har birini KO'RIB chiqing — "
        f"yig'maga faqat yig'uvchi yadrosi va Tcl/Tk resurslari kirishi kerak.")


# ═══ 7. MIJOZ MA'LUMOTI yig'mada YO'Q (ikkilik qidiruv) ═════════════════════════════════
#: ⚠️ Har naqsh UCH kodlashda qidiriladi: UTF-8 (Python matni), UTF-16-LE (Windows
#   resurslari) va CP1251 (kirill matn).
_MIJOZ_NAQSHI = ("fayzan", "fayzan1", "Файзан", "файзан",
                 "postgresql://", "postgres://", "mysql://", "mssql://",
                 "DATABASE_URL", "SECRET_KEY", "ANTHROPIC_API_KEY",
                 "savdoos-production", "up.railway.app", "railway.app",
                 "sk-ant-", "Srvr=", "Ref=")


def test_mijoz_malumoti_va_ulanish_satri_yigmada_yoq():
    """⚠️ Yig'ma HECH QANDAY tenant nomi, ulanish satri yoki kalit OLIB YURMAYDI: u
    operator mashinasida ishlaydigan OFFLINE vosita, server mijozi EMAS."""
    ignalar: list[tuple[str, bytes]] = []
    for s in _MIJOZ_NAQSHI:
        for enc in ("utf-8", "utf-16-le", "cp1251"):
            try:
                ignalar.append((f"{s} [{enc}]", s.encode(enc).lower()))
            except UnicodeEncodeError:
                pass                     # bu naqsh bu kodlashda ifodalanmaydi — normal
    topildi: dict[str, list[str]] = {}
    for p in _dist_fayllari():
        baytlar = p.read_bytes().lower()
        for nom, igna in ignalar:
            if igna in baytlar:
                topildi.setdefault(nom, []).append(str(p.relative_to(_DIST)))
    assert not topildi, f"Yig'ma baytlarida mijoz ma'lumoti/sir izi topildi: {topildi}"


def test_ishlab_chiquvchi_yoli_yigmada_yoq():
    """⚠️ Spec MUTLAQ yo'l yozmaydi (`SPECPATH` ishlatiladi). Yig'mada ishlab chiquvchi
    mashinasining yo'li qolsa — papka operatorga ichki joylashuvni ko'rsatardi."""
    naqsh = (rb"c:\users\developer", b"binos-agent-build", b"worktrees", b"savdoos")
    topildi: dict[str, list[str]] = {}
    for p in _dist_fayllari():
        baytlar = p.read_bytes().lower()
        for n in naqsh:
            if n in baytlar:
                topildi.setdefault(n.decode("latin-1"), []).append(
                    str(p.relative_to(_DIST)))
    assert not topildi, f"Yig'mada ishlab chiquvchi yo'li/repo nomi qoldi: {topildi}"


# ═══ 9. SPEC va HAQIQIY yig'ma MOS ══════════════════════════════════════════════════════
def test_spec_excludes_yigma_bilan_AYNAN_mos():
    """⚠️ SPEC YOLG'ON KAFOLAT BERMASIN: spec'da taqiqlangan HAR BIR modul haqiqiy
    yig'mada BO'LMASLIGI kerak. Ro'yxat spec FAYLIDAN o'qiladi (ko'chirma emas)."""
    modullar = _manifest_talab()["modullar"]
    buzilgan = {t: sorted(_qamralgan(modullar, t)) for t in _spec_excludes()}
    buzilgan = {k: v for k, v in buzilgan.items() if v}
    assert not buzilgan, (
        f"Spec'da TAQIQLANGAN modul yig'mada BOR — spec yolg'on kafolat bergan: {buzilgan}")


def test_yigma_AYNI_spec_bilan_qurilgan():
    """⚠️ Oldingi test faqat spec ro'yxatini o'qisa YETMAYDI: yig'ma BOSHQA (eski) spec
    bilan qurilgan bo'lishi mumkin. Yig'uvchi manifesti O'ZIDA ishlatilgan `excludes` ni
    yozib qoldiradi — AYNI shu bilan solishtiriladi."""
    manifest = _manifest_talab()
    # ⚠️ `__main__` ni PyInstaller O'ZI qo'shadi (skript `__main__` bo'lib yuritiladi).
    manifestda = [e for e in manifest["excludes"] if e != "__main__"]
    spec = _spec_excludes()
    assert manifestda == spec, (
        f"Yig'ma BOSHQA spec bilan qurilgan.\n"
        f"  faqat manifestda: {sorted(set(manifestda) - set(spec))}\n"
        f"  faqat spec'da:    {sorted(set(spec) - set(manifestda))}")


def test_yashirin_boshlangich_xulq_yoq():
    """⚠️ `runtime_hooks` BO'SH bo'lishi kerak: avtoyuklanish, xizmat, yangilovchi YO'Q.
    Yig'mada bajariladigan boshlang'ich skript faqat PyInstaller'ning O'Z hook'lari va
    bizning kirish skriptimiz bo'lsin."""
    manifest = _manifest_talab()
    begona = sorted(s for s in manifest["scriptlar"]
                    if not s.startswith("pyi_rth_") and s != "binos_agent_entry")
    assert not begona, f"Yig'mada KUTILMAGAN boshlang'ich skript bor: {begona}"
    assert "binos_agent_entry" in manifest["scriptlar"], \
        "kirish skripti manifestda yo'q — o'qish usuli buzilgan"
    daraxt = ast.parse(_SPEC.read_text(encoding="utf-8"))
    hooklar = [n for n in ast.walk(daraxt)
               if isinstance(n, ast.keyword) and n.arg == "runtime_hooks"]
    assert hooklar and all(isinstance(h.value, ast.List) and not h.value.elts
                           for h in hooklar), "spec'da `runtime_hooks` BO'SH bo'lishi kerak"


# ═══ Yig'ma ichidagi CHOP ETISH KODLASHI (HAQIQIY nuqson qulflanadi) ════════════════════
class _Cp1252Oqim:
    """`cp1252` konsolni taqlid qiladi: sig'maydigan belgi `UnicodeEncodeError` beradi.

    ⚠️ NEGA KERAK: pytest chiqishni UTF-8 bilan ushlaydi, shu bois TO'PLAM haqiqiy Windows
       konsolini KO'RMAYDI. Yig'ilgan `.exe` chiqishi faylga/quvurga yo'naltirilganda
       `sys.stdout.encoding` AYNAN `cp1252` bo'ladi — nuqson AYNI shu yerda chiqqan edi
       (chop etish uzilib, NATIJA PAPKASI umuman yozilmagan).
    """

    encoding = "cp1252"

    def __init__(self) -> None:
        self.yozilgan: list[str] = []

    def write(self, s: str) -> int:
        s.encode(self.encoding)          # ⚠️ sig'masa — UnicodeEncodeError
        self.yozilgan.append(s)
        return len(s)

    def flush(self) -> None:
        return None


def test_cp1252_konsolda_chop_etish_yurishni_toxtatmaydi():
    """⚠️ `_XavfsizOqim` cp1252 oqimga yozishda YIQILMASLIGI kerak, lekin matnni JIMGINA
    tashlab yubormasligi ham kerak."""
    from app.services.discovery_agent.__main__ import _XavfsizOqim

    xom = _Cp1252Oqim()
    with pytest.raises(UnicodeEncodeError):
        xom.write("⚠")                   # ⚠️ taqlid ISHONCHLI: oqim rostdan yiqiladi

    oqim = _XavfsizOqim(_Cp1252Oqim())
    oqim.write("⚠️ Natija: ═══ Файл — tayyor ─ 100% ✓\n")   # yiqilmasligi KERAK
    oqim.flush()
    chiqdi = "".join(oqim._o.yozilgan)
    assert "Natija" in chiqdi and "100%" in chiqdi, \
        f"sig'adigan matn ham yo'qolib ketdi: {chiqdi!r}"


def test_operator_matnlarida_cp1252_ga_sigmaydigan_belgi_bor_demak_himoya_shart():
    """⚠️ Nuqsonning SABABI qulflanadi: agent manbasida cp1252 ga sig'maydigan belgi BOR,
    demak IKKI QATLAM himoya SHART. Kimdir himoyani olib tashlasa — bu test eslatadi."""
    import app.services.discovery_agent.__main__ as m

    sigmaydigan: set[str] = set()
    for f in sorted(_AGENT_DIR.glob("*.py")):
        for ch in set(f.read_text(encoding="utf-8")):
            try:
                ch.encode("cp1252")
            except UnicodeEncodeError:
                sigmaydigan.add(ch)
    assert sigmaydigan, "cp1252 ga sig'maydigan belgi qolmadi — himoya hali ham keraklimi?"
    assert callable(m._utf8ga_otkaz) and hasattr(m._XavfsizOqim, "write"), \
        "cp1252 himoyasining ikki qatlamidan biri YO'Q"


def test_utf8ga_otkaz_imkon_bolsa_oqimni_ozgartiradi():
    """Birinchi qatlam: oqim UTF-8 ga o'tkaziladi, ya'ni belgi YO'QOLMAYDI (eng yaxshi
    holat). O'tkazib bo'lmasa — JIM o'tadi va ikkinchi qatlam ishlaydi."""
    from app.services.discovery_agent.__main__ import _utf8ga_otkaz

    class _Otkazuvchi:
        def __init__(self) -> None:
            self.chaqirildi: dict | None = None

        def reconfigure(self, **kw):
            self.chaqirildi = kw

    o = _Otkazuvchi()
    _utf8ga_otkaz(o)
    assert o.chaqirildi == {"encoding": "utf-8", "errors": "replace"}

    class _Otkazmaydigan:
        def reconfigure(self, **kw):
            raise OSError("oqim almashtirilgan")

    _utf8ga_otkaz(_Otkazmaydigan())      # YIQILMASLIGI kerak
