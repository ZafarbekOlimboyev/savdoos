# -*- coding: utf-8 -*-
"""MANBA ↔ YIG'MA PARITY HARNESSI — AYNI fikstura, IKKI yurish, SEMANTIK solishtirish.

Bu modul bitta savolga javob beradi: **yig'ilgan `.exe` manba Python bilan AYNI QARORNI
chiqaradimi?** Ya'ni PyInstaller o'rami (import mexanizmi, `__file__` yo'qligi, resurs
yo'llari, kodlash sozlamasi) agentning BIZNES semantikasini o'zgartirmaganini isbotlaydi.

IKKI YURISH, AYNI KIRISH:
    MANBA:  `<venv>/python.exe -m app.services.discovery_agent --headless ... --result-dir ...`
    YIG'MA: `BinOSDiscoveryAgent.exe --headless ... --result-dir ...`

⚠️⚠️ IKKISIGA HAM AYNI `--timestamp` BERILADI. Usiz natija papkasining NOMI ham, yurish
     yozuvidagi `started_at`/`finished_at` ham tabiiy ravishda boshqa bo'lardi va solishtirish
     MA'NOSIZ bo'lib qolardi: har qanday farq «vaqt» deb yozib qo'yilardi. Tamg'a berilganda
     esa `ui.utc_now` UMUMAN o'qilmaydi (`__main__.main` shuni kafolatlaydi) va yurishning
     butun vaqt o'qi KIRISHDAN keladi.

⚠️⚠️ SINTETIK FIKSTURA — REAL 1C EMAS. Kuzatiladigan papkani Phase 4 ning O'Z generatorlari
     yozadi (`tests.discovery_1c_runtime_mock`), ya'ni paket SHAKLI Phase 4 shartnomasi bilan
     bir xil bo'lib qoladi. Bu modul 1C ga ULANMAYDI, `1cv8.exe` ni ISHGA TUSHIRMAYDI,
     `.epf` BAJARMAYDI va TARMOQDAN foydalanmaydi. Shu bois bu yerdagi hech narsa «real 1C
     kolleksiyasi» DEB ATALMAYDI: isbotlanadigan narsa — IKKI YIG'MANING bir xil kirishdagi
     QARORI, 1C bilan ishlash emas.

⚠️ GENERATORLAR NUSXA KO'CHIRILMAYDI: `tests/discovery_1c_runtime_mock.py` dan IMPORT
   qilinadi. Ikki nusxa bir kun bir-biridan ajralib ketardi va qaysi biri haqiqat ekani
   aniqlanmay qolardi (`tests/agent_scenario_mock.py` dagi AYNI qoida).

⚠️⚠️ BU FAYL `packaging.parity_harness` DEB IMPORT QILINMAYDI va QILINMASLIGI kerak:
     `packaging` nomi PyPI paketi bilan TO'QNASHADI (u `.venv/Lib/site-packages/packaging/`
     da ODDIY paket, ya'ni `__init__.py` bilan). Odatiy paket nom bo'shliqli paketdan
     USTUN turadi, shu bois `import packaging` DOIM site-packages'dagi kutubxonani beradi va
     `packaging.parity_harness` HECH QACHON topilmaydi (tekshirildi). Shuning uchun test
     modul bu faylni YO'L bilan yuklaydi (`importlib.util.spec_from_file_location`) —
     bu chetlab o'tish emas, nomlar to'qnashuvining YAGONA to'g'ri yechimi.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import marshal
import os
import pathlib
import struct
import subprocess
import sys
import types
import zlib
from dataclasses import dataclass, field

from app.services.discovery_agent import (AGENT_MANIFEST_FILE, AGENT_STATUS_FILE,
                                          AI_CANDIDATES_FILE, BUNDLE_SUBDIR, ENVIRONMENT_FILE,
                                          ERRORS_FILE, REPORT_FILE)
from app.services.discovery_agent import result_package as rp

# ══════════════════════════════════════════════════════════════════════════════════════════
# QAYERDAN YURGIZILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `apps/server` — MANBA yurishining ishchi papkasi (`-m app.services.discovery_agent` shu
#: yerdan ko'rinadi). ⚠️ `__file__` dan hisoblanadi, QO'LDA yozilmaydi: harness ko'chirilsa
#: ham yo'l o'zidan-o'zi to'g'ri qoladi.
SERVER_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

#: MANBA tarafning interpretatori. ⚠️ `sys.executable` — ya'ni testni YURGIZAYOTGAN AYNI
#: Python. Qo'lda yozilgan yo'l boshqa mashinada yoki boshqa venv'da jimgina BOSHQA
#: interpretatorni solishtirardi.
MANBA_PYTHON = sys.executable

#: ⚠️ YIG'MA REPO TASHQARISIDA (repo daraxti toza qolishi uchun). Yo'l muhit o'zgaruvchisi
#: bilan ALMASHTIRILADI — CI yoki boshqa mashinada yig'ma boshqa joyda bo'lishi mumkin.
#: ⚠️⚠️ ILDIZ BITTA MUHIT O'ZGARUVCHISIDAN: `dist-onedir` ham, `build-onedir` ham SHU
#:      ildizdan hisoblanadi va `tests/test_agent_packaging.py` AYNI ildizni o'qiydi.
#:      Ilgari u faylda ildiz QO'LDA `C:/Users/Developer/...` deb yozilgan edi — ya'ni
#:      ishlab chiquvchining mutlaq yo'li (spec'ning O'Z qoidasiga zid) va ikki fayl
#:      jimgina BOSHQA yig'mani tekshirishi mumkin edi. Ikkisining tengligi
#:      `test_agent_parity.py` dagi drift qo'riqchisi bilan QULFLANGAN.
YIGMA_ILDIZ_ENV_KALITI = "BINOS_AGENT_BUILD_ROOT"
YIGMA_ILDIZ = pathlib.Path(os.environ.get(YIGMA_ILDIZ_ENV_KALITI)
                           or pathlib.Path.home() / "binos-agent-build")
YIGMA_ENV_KALITI = "BINOS_AGENT_EXE"
_STANDART_EXE = YIGMA_ILDIZ / "dist-onedir" / "BinOSDiscoveryAgent" / "BinOSDiscoveryAgent.exe"
YIGMA_EXE = os.environ.get(YIGMA_ENV_KALITI) or str(_STANDART_EXE)

#: PyInstaller ning BUILD papkasi — yig'ma ichidagi bytecode AYNAN shu yerda ALOHIDA fayl
#: bo'lib ham qoladi (`PYZ-00.pyz`). Eskirgan-EXE darvozasi shuni o'qiydi (pastga qarang).
YIGMA_BUILD_ENV_KALITI = "BINOS_AGENT_BUILD"
YIGMA_BUILD = os.environ.get(YIGMA_BUILD_ENV_KALITI) or str(
    YIGMA_ILDIZ / "build-onedir" / "BinOSDiscoveryAgent")

#: Ikki yurish uchun AYNI tamg'a. ⚠️ Doimiy bo'lishi SHART (yuqoridagi izohga qarang).
TAMGA = "20261001T090000Z"

#: Kutish chegarasi — KICHIK. ⚠️ Chegara KIRISHDAN keladi, demak uni kichraytirish XULQNI
#: o'zgartirmaydi, faqat to'plamni tez qiladi. `collector_bridge` tayyorlik uchun IKKI
#: o'lchov talab qiladi, ya'ni sog'lom paketda ham bitta `poll` uyqusi bo'ladi.
SOG_LOM_KUTISH = "6"
#: Bo'sh papka ssenariysi uchun — eng kichik qiymat, vaqt tugashi TEZ urishi kerak.
TIMEOUT_KUTISH = "1"


def yigma_bor() -> bool:
    """Yig'ilgan `.exe` joyidami?"""
    return os.path.isfile(YIGMA_EXE)


def yigma_yoqligi_sababi() -> str:
    """⚠️ EXE yo'q bo'lsa test JIMGINA o'tib ketmaydi: sabab AYNAN shu matn bilan ko'rinadi.

    Matn ikki narsani aytadi: QAYERGA qaradik va uni QANDAY qurish/ko'rsatish kerak. «Skip»
    ning o'zi hisobotda «parity tekshirilmadi» degan MA'NONI yo'qotmasligi kerak.
    """
    # ⚠️ Yo'l `!r` BILAN EMAS: Windows yo'lidagi teskari chiziqlar ikkilanib ketardi va
    #    operator matndan yo'lni KO'CHIRIB OLA olmasdi.
    return (f"PARITY TEKSHIRILMADI: yig'ilgan agent topilmadi — {YIGMA_EXE} . "
            f"Bu test MANBA Python bilan YIG'ILGAN `.exe` ni solishtiradi, demak yig'ma "
            f"bo'lmasa u HECH NARSA isbotlamaydi. Yig'ma repo TASHQARISIDA quriladi "
            f"(`packaging/BinOSDiscoveryAgent.spec`, ONE-DIR); boshqa joyda bo'lsa "
            f"`{YIGMA_ENV_KALITI}` muhit o'zgaruvchisida yo'lini ko'rsating.")


# ══════════════════════════════════════════════════════════════════════════════════════════
# BITTA YURISH
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Yurish:
    """Bitta yurishning XOM natijasi — hali solishtirilmagan, hali normallashtirilmagan."""

    nom: str
    kod: int
    stdout: str
    stderr: str
    #: Kuzatilgan papka (`--headless`) va natija papkasining OTASI (`--result-dir`).
    kuzatilgan: str
    natija_otasi: str
    #: `binos-discovery-<tamga>` — yozilgan bo'lsa.
    natija_papkasi: str | None
    #: Nisbiy nom -> baytlar (`bundle/...` ham). Papka yozilmasa BO'SH.
    fayllar: dict[str, bytes] = field(default_factory=dict)


def manba_buyruq() -> list[str]:
    """MANBA yurishining buyrug'i."""
    return [MANBA_PYTHON, "-m", "app.services.discovery_agent"]


def yigma_buyruq() -> list[str]:
    """YIG'MA yurishining buyrug'i."""
    return [YIGMA_EXE]


def toza_muhit(qoshimcha: dict[str, str] | None = None) -> dict[str, str]:
    """⚠️ IKKI YURISH AYNI MUHITDA: kodlashga ta'sir qiladigan o'zgaruvchilar OLIB TASHLANADI.

    `PYTHONIOENCODING`/`PYTHONUTF8` ni pytest yoki ishlab chiquvchining qobig'i qo'yib
    yuborgan bo'lishi mumkin. U faqat MANBA tarafga ta'sir qilardi (interpretator o'sha) va
    solishtirish jimgina NOTENG sharoitda ketardi. `PYTHONPATH` ham olib tashlanadi: MANBA
    yurishi faqat `cwd` dan topilsin.
    """
    muhit = dict(os.environ)
    for kalit in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONPATH", "PYTHONHOME",
                  "PYTHONSTARTUP", "PYTHONWARNINGS"):
        muhit.pop(kalit, None)
    if qoshimcha:
        muhit.update(qoshimcha)
    return muhit


def yurgiz(buyruq: list[str], *, nom: str, kuzatilgan: str, natija_otasi: str,
           tamga: str = TAMGA, kutish: str = SOG_LOM_KUTISH,
           muhit_qoshimcha: dict[str, str] | None = None, timeout: float = 300.0) -> Yurish:
    """Bitta yurish: jarayonni ochadi, chiqishni va natija papkasini O'QIYDI.

    ⚠️ Chiqish BAYT bo'lib olinadi va UTF-8 `replace` bilan dekodlanadi: bola jarayonning
       kodlashi haqida HECH QANDAY taxmin qilinmaydi — aynan shu narsa sinalayotgan
       xususiyatlarning biri.
    ⚠️ `cwd` DOIM `SERVER_ROOT`: MANBA tarafga `-m` shu yerdan ko'rinadi, YIG'MA tarafga esa
       farqi yo'q — lekin IKKISI AYNI joydan yurishi kerak (nisbiy yo'l qoldiq ta'siri
       bo'lmasin).
    """
    os.makedirs(natija_otasi, exist_ok=True)
    jarayon = subprocess.run(
        buyruq + ["--headless", kuzatilgan, "--result-dir", natija_otasi,
                  "--timestamp", tamga, "--wait-seconds", kutish],
        cwd=SERVER_ROOT, capture_output=True, env=toza_muhit(muhit_qoshimcha),
        timeout=timeout, check=False)
    papka = os.path.join(natija_otasi, rp.result_dir_name(tamga))
    bor = os.path.isdir(papka)
    return Yurish(
        nom=nom, kod=jarayon.returncode,
        stdout=jarayon.stdout.decode("utf-8", "replace"),
        stderr=jarayon.stderr.decode("utf-8", "replace"),
        kuzatilgan=kuzatilgan, natija_otasi=natija_otasi,
        natija_papkasi=papka if bor else None,
        fayllar=papka_baytlari(papka) if bor else {},
    )


def papka_baytlari(papka: str) -> dict[str, bytes]:
    """Papkadagi HAMMA fayl (`bundle/` ichi ham): nisbiy POSIX nom -> baytlar."""
    kok = pathlib.Path(papka)
    out: dict[str, bytes] = {}
    for yo_l in sorted(kok.rglob("*")):
        if yo_l.is_file():
            out[yo_l.relative_to(kok).as_posix()] = yo_l.read_bytes()
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════
# IKKI YURISH — AYNI FIKSTURA
# ══════════════════════════════════════════════════════════════════════════════════════════
def fikstura_yoz(ildiz: str, nom: str, generator) -> str:
    """Kuzatiladigan papkani quradi va (generator berilgan bo'lsa) Phase 4 paketini yozadi.

    `generator is None` — papka BO'SH qoladi (vaqt tugashi ssenariysi).
    ⚠️ Generator `tests.discovery_1c_runtime_mock` dan keladi va BU YERDA QAYTA YOZILMAYDI.
    """
    papka = pathlib.Path(ildiz) / nom
    papka.mkdir(parents=True, exist_ok=True)
    if generator is not None:
        generator(str(papka))
    return str(papka)


def ikki_yurish(ildiz: str, generator, *, kutish: str = SOG_LOM_KUTISH,
                tamga: str = TAMGA) -> tuple[Yurish, Yurish]:
    """AYNI generator bilan MANBA va YIG'MA yurishlari.

    ⚠️⚠️ HAR YURISH O'Z kuzatilgan papkasini oladi (nusxasini EMAS, AYNI generatordan QAYTA
         yozilgan holini). Bitta papkani ikkisiga berish mumkin EMAS: birinchi yurish uni
         O'QIYDI, lekin ikkinchi yurish uchun papka holati (yozilish vaqti, bufer) boshqa
         bo'ladi va tayyorlik o'lchovi ikki xil yo'ldan ketishi mumkin edi. Generator
         DETERMINISTIK, demak ikki papka BAYT-BA-BAYT bir xil bo'ladi — bu testda
         tekshiriladi.
    ⚠️ Natija papkalari ham ALOHIDA bo'lishi SHART: nomlari AYNI (`--timestamp` bir xil),
       demak bitta otada ikkinchisi birinchisining ustiga yozardi.
    """
    manba_kuzatilgan = fikstura_yoz(ildiz, "manba-kuzatilgan", generator)
    yigma_kuzatilgan = fikstura_yoz(ildiz, "yigma-kuzatilgan", generator)
    manba = yurgiz(manba_buyruq(), nom="MANBA", kuzatilgan=manba_kuzatilgan,
                   natija_otasi=os.path.join(ildiz, "manba-natija"),
                   kutish=kutish, tamga=tamga)
    yigma = yurgiz(yigma_buyruq(), nom="YIG'MA", kuzatilgan=yigma_kuzatilgan,
                   natija_otasi=os.path.join(ildiz, "yigma-natija"),
                   kutish=kutish, tamga=tamga)
    return manba, yigma


# ══════════════════════════════════════════════════════════════════════════════════════════
# YO'LLARNI NIQOBLASH — farqni YO'QOTMAYDI, uni YURISHGA NISBIY qiladi
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ NEGA NIQOB, NEGA TASHLAB KETISH EMAS: ikki yurishning papkalari TURLI (nomlari bir xil
#: bo'lsa biri ikkinchisini bosib yozardi). Agar yo'l satrini solishtirishdan butunlay
#: chiqarib tashlasak, «yo'l hisobotga chiqib ketdi» kabi HAQIQIY nuqson ko'rinmay qolardi.
#: Niqoblashda esa yo'l MATNI solishtiriladi — faqat har yurishning O'Z ildizi bir xil
#: belgiga aylantiriladi.
NIQOBLAR: tuple[tuple[str, str], ...] = (
    ("natija_papkasi", "<NATIJA-PAPKASI>"),
    ("natija_otasi", "<NATIJA-OTASI>"),
    ("kuzatilgan", "<KUZATILGAN-PAPKA>"),
)


def niqobla(matn: str, yurish: Yurish) -> str:
    """Yurishning O'Z mutlaq yo'llarini barqaror belgilarga almashtiradi.

    ⚠️ UZUNDAN QISQAGA: natija papkasi natija otasining ICHIDA, demak otani birinchi
       almashtirsak papkaning yo'li yarmi niqoblangan holda qolib ketardi.
    ⚠️ Teskari va to'g'ri chiziqli shakl ham, `os.path.normcase` farqi ham qaraladi: chiqish
       Windows shaklida, JSON va hisobotda esa boshqacha bo'lishi mumkin.
    """
    natija = matn
    juftlar = []
    for maydon, belgi in NIQOBLAR:
        qiymat = getattr(yurish, maydon)
        if qiymat:
            juftlar.append((str(qiymat), belgi))
    for qiymat, belgi in sorted(juftlar, key=lambda j: len(j[0]), reverse=True):
        for shakl in (qiymat, qiymat.replace("\\", "/"), qiymat.replace("\\", "\\\\")):
            natija = natija.replace(shakl, belgi)
    return natija


# ══════════════════════════════════════════════════════════════════════════════════════════
# SEMANTIK KO'RINISH — SOLISHTIRILADIGAN NARSANING O'ZI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Fayl yo'q bo'lsa qo'yiladigan belgi. ⚠️ `None` EMAS: `null` qiymatli maydon bilan
#: ARALASHIB ketmasligi kerak — «fayl yo'q» va «maydon bo'sh» ikki xil fakt.
YOQ = "<FAYL YO'Q>"

#: Ildizdagi JSON artefaktlari — HAMMASI chuqur solishtiriladi.
JSON_ARTEFAKTLAR: tuple[str, ...] = (AGENT_STATUS_FILE, ENVIRONMENT_FILE, ERRORS_FILE,
                                     AGENT_MANIFEST_FILE, AI_CANDIDATES_FILE)


def _json_yoki_yoq(yurish: Yurish, nom: str):
    xom = yurish.fayllar.get(nom)
    if xom is None:
        return YOQ
    try:
        return json.loads(xom.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        # ⚠️ BUZUQ JSON JIM YUTILMAYDI: u ham SOLISHTIRILADIGAN fakt. Ikki yurishdan biri
        #    buzuq hujjat yozsa — farq ko'rinishi SHART.
        return f"<JSON BUZUQ: {type(e).__name__}>"


def _manifest_ko_rinishi(doc):
    """`agent_manifest.json` — `files` ro'yxati NOM bo'yicha kalitlanadi, TARTIB esa alohida.

    ⚠️ NEGA: ro'yxat indeksi bo'yicha solishtirilsa, ikki yurish fayllarni boshqa TARTIBDA
       yozsa HAMMA satr «farq» bo'lib chiqardi va haqiqiy farq ko'rinmay qolardi. Tartibning
       o'zi ham shartnoma (determinizm), shu bois u ALOHIDA maydon bo'lib solishtiriladi —
       ya'ni tekshiruv yo'qolmaydi, ikkiga bo'linadi.
    """
    if not isinstance(doc, dict):
        return doc
    fayllar = doc.get("files")
    if not isinstance(fayllar, list):
        return doc
    nomlar = [f.get("name") if isinstance(f, dict) else f for f in fayllar]
    kalitlangan = {}
    for f in fayllar:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            kalitlangan[f["name"]] = {k: v for k, v in f.items() if k != "name"}
        else:
            kalitlangan[f"<SHAKLSIZ:{len(kalitlangan)}>"] = f
    chiqish = {k: v for k, v in doc.items() if k != "files"}
    chiqish["files"] = kalitlangan
    chiqish["files_tartibi"] = nomlar
    return chiqish


def semantik(yurish: Yurish) -> dict:
    """Yurishning SOLISHTIRILADIGAN ko'rinishi — brief §5 sanagan maydonlar.

    Ichida: terminal holat · yo'l · `presence_verdict` · `agent_status.json` ·
    `environment.json` · `errors.json` · hisobot · `agent_manifest.json` · paket
    validatsiyasining natijasi · nomzodlar · `bundle/` ning xeshlari · chiqish kodi va
    operator ekrani.

    ⚠️ «Ikkisi ham bo'sh emas» DEGAN TEKSHIRUV EMAS: hujjatlar JSON DARAXTI bo'ylab
       bargma-barg solishtiriladi (`farqlar`), hisobot esa to'liq MATN bo'lib.
    ⚠️ `bundle/` baytlari XESH bilan solishtiriladi: u Phase 4 paketining O'ZGARMAGAN nusxasi,
       demak farq bo'lsa xesh darhol ko'rsatadi va xato matni megabaytlab bo'lib ketmaydi.
    """
    ko_rinish: dict = {
        "chiqish_kodi": yurish.kod,
        "natija_papkasi_yozildi": yurish.natija_papkasi is not None,
        "fayl_nomlari": sorted(yurish.fayllar),
    }
    for nom in JSON_ARTEFAKTLAR:
        doc = _json_yoki_yoq(yurish, nom)
        if nom == AGENT_MANIFEST_FILE:
            doc = _manifest_ko_rinishi(doc)
        ko_rinish[f"hujjat:{nom}"] = doc

    holat = ko_rinish[f"hujjat:{AGENT_STATUS_FILE}"]
    muhit = ko_rinish[f"hujjat:{ENVIRONMENT_FILE}"]
    # ⚠️ ENG MUHIM UCH MAYDON ALOHIDA CHIQARILADI: ular hujjat ichida ham solishtiriladi,
    #    lekin yiqilish xabarida «qaysi QAROR boshqa» darhol ko'rinishi kerak.
    ko_rinish["terminal_holat"] = holat.get("state") if isinstance(holat, dict) else holat
    ko_rinish["route"] = holat.get("route") if isinstance(holat, dict) else holat
    ko_rinish["presence_verdict"] = (muhit.get("presence_verdict")
                                     if isinstance(muhit, dict) else muhit)

    xom_hisobot = yurish.fayllar.get(REPORT_FILE)
    ko_rinish["hisobot"] = (YOQ if xom_hisobot is None
                            else niqobla(xom_hisobot.decode("utf-8", "replace"), yurish))

    ko_rinish["bundle_xeshlari"] = {
        nom: hashlib.sha256(xom).hexdigest()
        for nom, xom in sorted(yurish.fayllar.items())
        if nom.startswith(f"{BUNDLE_SUBDIR}/")
    }

    # ⚠️ PAKET VALIDATSIYASINING NATIJASI ham solishtiriladi: ikki paket bir xil
    #    MAZMUNGA ega bo'lib ham validatordan boshqa natija bilan o'tishi mumkin emas —
    #    aks holda paketda biz solishtirmagan narsa bor degani.
    ko_rinish["paket_nuqsonlari"] = (
        YOQ if yurish.natija_papkasi is None
        else [niqobla(p, yurish) for p in rp.check_result_package(yurish.natija_papkasi)])

    # ⚠️ OPERATOR EKRANI ham shartnoma (yo'l haqqoniyligi, kutish qatori, yiqilish ma'nosi):
    #    yig'mada u jimgina qisqarib qolmasligi kerak.
    ko_rinish["stdout"] = niqobla(yurish.stdout, yurish).replace("\r\n", "\n")
    ko_rinish["stderr"] = niqobla(yurish.stderr, yurish).replace("\r\n", "\n")
    return ko_rinish


# ══════════════════════════════════════════════════════════════════════════════════════════
# TABIIY FARQLAR — ANIQ, QISQA va KENGAYTIRILMAYDIGAN RO'YXAT
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ BU RO'YXAT KENGAYTIRILMAYDI. Har bir satr — IKKI JARAYON bir xil kirishda ham
#:      boshqa qiymat berishi FIZIK ravishda muqarrar bo'lgan joy. BIZNES yoki QAROR
#:      semantikasi (holat, yo'l, hukm, xatolar, hisobot, paket mazmuni) bu ro'yxatga
#:      HECH QACHON tushmaydi: u AYNAN bir xil bo'lishi SHART.
#: ⚠️ Moslashtirish AYNAN TENGLIK bo'yicha (naqsh, yulduzcha, prefiks YO'Q): «`files` ning
#:    hamma xeshi» kabi jimgina kengayib ketadigan qoida bu yerda yozib bo'lmaydi.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    (
        f"hujjat:{ENVIRONMENT_FILE}/scanned_at",
        "Muhit skanerining O'Z soati. `--timestamp` faqat AGENTNING soatini "
        "(`ui.utc_now`) chetlab o'tadi; `detector` skanerlangan vaqtni mustaqil oladi "
        "(`detector._now`, mikrosekundsiz UTC). Ikki jarayon bir SEKUNDDA boshlanishi "
        "kafolatlanmaydi, demak bu farq muqarrar. "
        "⚠️ Faqat QIYMAT ruxsat etiladi: maydonning BORLIGI, shakli va uzunligi baribir "
        "solishtiriladi (manifestdagi `bytes` orqali ham).",
    ),
    (
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/sha256",
        "Yuqoridagi birinchi satrning BEVOSITA OQIBATI: manifest `environment.json` ni "
        "xeshlaydi, uning esa yagona farqi `scanned_at` qiymati. "
        "⚠️ FAQAT SHU BITTA FAYLNING xeshi: qolgan HAMMA artefaktning `sha256` i va SHU "
        "faylning `bytes` i ham AYNAN teng bo'lishi SHART (ISO tamg'a qat'iy kenglikda, "
        "demak hajm o'zgarmaydi).",
    ),
)

#: ⚠️ MUTLAQ YO'LLAR ro'yxatda YO'Q va bu ATAYLAB: ular tashlab ketilmaydi, `niqobla` bilan
#: yurishga NISBIY qilinadi va SHUNDAN KEYIN solishtiriladi (yuqoridagi `NIQOBLAR`). Ya'ni
#: «hisobotga mutlaq yo'l chiqib ketdi» kabi nuqson baribir ko'rinadi.
#: ⚠️ BUILD METADATASI ham ro'yxatda YO'Q: tajribada ikki yurish bitta ham build maydonida
#: farq qilmadi (agent versiyasi kodda doimiy, `os_version` ikkisida ham `platform.platform()`
#: dan keladi). Ehtimollik uchun oldindan ruxsat berib qo'yish — himoyani bo'shatish.
ALLOWLIST_YO_LLARI: frozenset[str] = frozenset(yo_l for yo_l, _ in ALLOWLIST)


def allowlist_sababi(yo_l: str) -> str | None:
    for nomzod, sabab in ALLOWLIST:
        if nomzod == yo_l:
            return sabab
    return None


# ══════════════════════════════════════════════════════════════════════════════════════════
# CHUQUR SOLISHTIRISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def barglar(obyekt, prefiks: str = "") -> dict[str, object]:
    """JSON daraxtini BARGLARGA yoyadi: `yo'l -> qiymat`.

    ⚠️ Lug'at KALITLARI ham, ro'yxat INDEKSLARI ham yo'lga kiradi, ya'ni «bu kalit faqat
       bittasida bor» holati ham FARQ bo'lib ko'rinadi (yo'qolgan barg `<YO'Q>` bo'ladi).
    """
    if isinstance(obyekt, dict):
        if not obyekt:
            return {prefiks: "<BO'SH LUG'AT>"}
        out: dict[str, object] = {}
        for kalit, qiymat in obyekt.items():
            out.update(barglar(qiymat, f"{prefiks}/{kalit}" if prefiks else str(kalit)))
        return out
    if isinstance(obyekt, list):
        if not obyekt:
            return {prefiks: "<BO'SH RO'YXAT>"}
        out = {}
        for i, qiymat in enumerate(obyekt):
            out.update(barglar(qiymat, f"{prefiks}[{i}]"))
        return out
    return {prefiks: obyekt}


def _allowlistda(yo_l: str) -> bool:
    """⚠️ AYNIQ TENGLIK, prefiks yoki naqsh EMAS: `files/<boshqa fayl>/sha256` kabi qo'shni
    barg jimgina ruxsat olib qolmasligi kerak."""
    return yo_l in ALLOWLIST_YO_LLARI


@dataclass(frozen=True)
class Farq:
    yo_l: str
    manba: object
    yigma: object
    ruxsat: str | None

    def human(self) -> str:
        belgi = "RUXSAT" if self.ruxsat else "FARQ"
        return (f"[{belgi}] {self.yo_l}\n"
                f"    MANBA:  {self.manba!r}\n"
                f"    YIG'MA: {self.yigma!r}"
                + (f"\n    sabab: {self.ruxsat}" if self.ruxsat else ""))


def farqlar(manba: Yurish, yigma: Yurish) -> tuple[list[Farq], list[Farq]]:
    """`(taqiqlangan, ruxsat etilgan)` — ikki semantik ko'rinishning HAMMA bargi bo'ylab.

    ⚠️ Ikki ro'yxat QAYTARILADI, chunki ikkisi ham hisobot uchun kerak: birinchisi testni
       yiqitadi, ikkinchisi esa «allowlist ROSTDAN ishlatilganmi» degan savolga javob beradi.
       Ruxsat etilgan satr KUTILGAN joyda KUTILGANDEK paydo bo'lishi ham tekshiriladi —
       aks holda allowlist jimgina o'lik qoidaga aylanib, keyin kerak bo'lganda yo'q bo'lardi.
    """
    a = barglar(semantik(manba))
    b = barglar(semantik(yigma))
    taqiq: list[Farq] = []
    ruxsat: list[Farq] = []
    for yo_l in sorted(set(a) | set(b)):
        qa, qb = a.get(yo_l, "<YO'Q>"), b.get(yo_l, "<YO'Q>")
        if qa == qb:
            continue
        sabab = allowlist_sababi(yo_l) if _allowlistda(yo_l) else None
        (ruxsat if sabab else taqiq).append(Farq(yo_l, qa, qb, sabab))
    return taqiq, ruxsat


def hisobot(manba: Yurish, yigma: Yurish, taqiq: list[Farq]) -> str:
    """Yiqilish xabari — QAYSI maydon, QAYSI qiymat, va yurishlarning xulosasi."""
    sa, sb = semantik(manba), semantik(yigma)
    satrlar = [
        "MANBA ↔ YIG'MA PARITY BUZILDI.",
        f"  MANBA:  kod={sa['chiqish_kodi']} holat={sa['terminal_holat']} "
        f"yo'l={sa['route']} hukm={sa['presence_verdict']}",
        f"  YIG'MA: kod={sb['chiqish_kodi']} holat={sb['terminal_holat']} "
        f"yo'l={sb['route']} hukm={sb['presence_verdict']}",
        f"  TAQIQLANGAN FARQ: {len(taqiq)}",
    ]
    satrlar += [f.human() for f in taqiq[:25]]
    if len(taqiq) > 25:
        satrlar.append(f"  ... va yana {len(taqiq) - 25} farq")
    return "\n".join(satrlar)


def solishtirilgan_maydonlar() -> tuple[str, ...]:
    """Brief §5 ning maydonlari — hisobot uchun NOM bilan.

    ⚠️ Bu ro'yxat `semantik()` ning kalitlaridan HISOBLANMAYDI, qo'lda yozilgan: test uni
       `semantik()` chiqishi bilan solishtiradi, ya'ni kodda maydon yo'qolsa darhol ko'rinadi
       (o'z-o'zini tasdiqlaydigan ro'yxat hech narsa isbotlamasdi).
    """
    return (
        "chiqish_kodi", "natija_papkasi_yozildi", "fayl_nomlari", "terminal_holat", "route",
        "presence_verdict", f"hujjat:{AGENT_STATUS_FILE}", f"hujjat:{ENVIRONMENT_FILE}",
        f"hujjat:{ERRORS_FILE}", f"hujjat:{AGENT_MANIFEST_FILE}",
        f"hujjat:{AI_CANDIDATES_FILE}", "hisobot", "bundle_xeshlari", "paket_nuqsonlari",
        "stdout", "stderr",
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# OWNER A — MANBA SHARTNOMASI (EXE KERAK EMAS, har platformada DETERMINISTIK)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ NEGA IKKI EGA. Haqiqiy `.exe` parity'si Windows yig'masini TALAB qiladi, Linux backend
#      CI esa uni QURA OLMAYDI (Windows runner yo'q). Kafolat shu bois IKKIGA bo'linadi:
#        (A) YIG'MA SHARTNOMASI — yig'maga NIMA kirishi kerak, NIMA taqiqlangan, kirish
#            nuqtasi va chiqish kodlari. Hammasi MANBADAN hisoblanadi, demak Linux'da ham
#            AYNI javobni beradi. Bu `.exe` ni emas, YIG'MANING SHARTNOMASINI qulflaydi.
#        (B) HAQIQIY EXE PARITY'SI — manba va `.exe` ni AYNI fikstura bilan yurgizib
#            semantik solishtirish. Windows reliz darvozasi (`packaging/BUILD_GATE.md`).
#      ⚠️ (A) (B) ning O'RNINI BOSMAYDI va bosa olmaydi: PyInstaller o'rami QARORNI
#         o'zgartirdimi — buni faqat (B) o'lchaydi. (A) esa (B) o'lchamaydigan narsani
#         o'lchaydi: yig'ma TARKIBINING shartnomasi. Ikkisi KESISHMAYDI.

#: Yig'maga kiradigan MANBA daraxtlari (spec'dagi `ENTRY` dan yetib boriladigan hammasi
#: shu ikki paketda yashaydi) — ildizga NISBIY, POSIX shaklida.
YIGMA_MANBA_PAPKALARI: tuple[str, ...] = (
    "app/services/discovery_agent",
    "app/services/discovery_1c",
)

#: Yig'maga kiradigan ALOHIDA manba fayllari + yig'maning O'Z sozlamasi.
#: ⚠️ `migrator_1c` dan FAQAT `__init__.py` va `bundle.py`: qolgani `excludes` da
#:    (`apply.py` va qo'shnilari yig'maga KIRMAYDI).
#: ⚠️ Spec va kirish skripti ham KIRISH: ular o'zgarsa yig'ma boshqa narsa bo'ladi, demak
#:    ular ham «yig'ma eskirdimi» savoliga kiradi.
YIGMA_MANBA_FAYLLARI: tuple[str, ...] = (
    "app/__init__.py",
    "app/services/__init__.py",
    "app/services/migrator_1c/__init__.py",
    "app/services/migrator_1c/bundle.py",
    "packaging/BinOSDiscoveryAgent.spec",
    "packaging/binos_agent_entry.py",
)

SPEC_YOLI = str(pathlib.Path(SERVER_ROOT) / "packaging" / "BinOSDiscoveryAgent.spec")
ENTRY_YOLI = str(pathlib.Path(SERVER_ROOT) / "packaging" / "binos_agent_entry.py")


def manba_kirishlari() -> dict[str, str]:
    """Yig'maning MANBA KIRISHLARI: nisbiy POSIX nom -> sha256.

    ⚠️ Papkalar REKURSIV o'qiladi va `__pycache__` tashlab ketiladi: `.pyc` fayli manba
       emas, u Python versiyasiga bog'liq va xeshni jimgina «o'zgargan» qilardi.
    ⚠️ Ro'yxat QO'LDA yozilmaydi — papkadan o'qiladi, demak YANGI modul qo'shilsa u
       o'zidan-o'zi kirish bo'lib qoladi (qo'lda yozilgan ro'yxat eskirar edi).
    """
    kok = pathlib.Path(SERVER_ROOT)
    chiqish: dict[str, str] = {}
    for papka in YIGMA_MANBA_PAPKALARI:
        for yo_l in sorted((kok / papka).rglob("*.py")):
            if "__pycache__" in yo_l.parts:
                continue
            chiqish[yo_l.relative_to(kok).as_posix()] = hashlib.sha256(
                yo_l.read_bytes()).hexdigest()
    for nisbiy in YIGMA_MANBA_FAYLLARI:
        chiqish[nisbiy] = hashlib.sha256((kok / nisbiy).read_bytes()).hexdigest()
    return dict(sorted(chiqish.items()))


def xesh_jamlash(kirishlar: dict[str, str]) -> str:
    """`{nom: xesh}` -> YAGONA xesh.

    ⚠️ NOM ham jamlanmaga kiradi (faqat mazmun emas): fayl QAYTA NOMLANSA ham imzo
       o'zgarishi kerak, aks holda ko'chirilgan modul sezilmay qolardi.
    ⚠️ ALOHIDA funksiya bo'lib turishi ataylab: jamlashning TISHI (bitta fayl o'zgarsa
       imzo o'zgaradimi) diskka tegmasdan, sintetik kirish bilan sinaladi.
    """
    satrlar = [f"{nom} {kirishlar[nom]}" for nom in sorted(kirishlar)]
    return hashlib.sha256("\n".join(satrlar).encode("utf-8")).hexdigest()


def manba_xeshi() -> str:
    """Yig'ma kirishlarining YAGONA xeshi — reliz hisobotiga yoziladigan manba imzosi."""
    return xesh_jamlash(manba_kirishlari())


def spec_royxati(nom: str) -> list[str]:
    """Spec faylidan modul darajasidagi ro'yxatni O'QIYDI (`EXCLUDES`, `HIDDEN`).

    ⚠️ Spec IMPORT QILINMAYDI, AST bilan o'qiladi: uning ichida `SPECPATH` kabi faqat
       PyInstaller beradigan nomlar bor, ya'ni import `NameError` berardi.
    """
    daraxt = ast.parse(pathlib.Path(SPEC_YOLI).read_text(encoding="utf-8"))
    for n in daraxt.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == nom for t in n.targets):
            return list(ast.literal_eval(n.value))
    raise AssertionError(f"spec ichida `{nom}` ro'yxati topilmadi: {SPEC_YOLI}")


def taqiq_qamraydi(modul: str, taqiq: str) -> bool:
    """`taqiq` ning O'ZI yoki uning OSTIDAGI modulmi.

    ⚠️ Oddiy `startswith(taqiq)` EMAS: `psycopg` taqig'i `psycopg_begona` ni ham qamrardi.
    """
    return modul == taqiq or modul.startswith(taqiq + ".")


# ══════════════════════════════════════════════════════════════════════════════════════════
# OWNER B — ESKIRGAN YIG'MA DARVOZASI (yig'ma ICHIDAGI bytecode ↔ JORIY manba)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ MUAMMO: «`.exe` bor» degani «`.exe` SHU manbadan qurilgan» degani EMAS. Eskirgan
#      yig'ma parity'dan JIMGINA o'tib ketishi mumkin — o'zgargan modul tanlangan
#      fiksturada kuzatiladigan farq bermasa, solishtirish YASHIL bo'ladi va «yig'ma
#      manbaga teng» degan YOLG'ON xulosa chiqadi. Bu nazariy xavf emas: shu darvoza
#      yozilgan kunda mahalliy yig'ma AYNAN shunday holatda edi (`redact.py` va
#      `detector.py` manbada o'zgargan, parity esa YASHIL edi) — pastdagi solishtiruvchi
#      aynan shu ikki modulni, faqat shu ikkisini, topdi.
#
# ⚠️ NEGA SHTAMP FAYLI EMAS. «Build paytida manba xeshini yozib qo'yish» ham yechim, lekin
#    u ikki tomondan bo'sh: (1) shtamp YANGI va MAJBURIY build qadamini talab qiladi —
#    esdan chiqsa darvoza yo DOIM qizil, yo TESHIK bo'ladi; (2) shtamp artefaktning
#    O'ZIDAN emas, uning YONIDAN keladi — ko'chirilgan yoki qo'lda yozilgan shtamp
#    eskirgan `.exe` ni «toza» deb ko'rsatardi. Shu bois darvoza artefaktning ICHIDAGI
#    bytecode'ni o'qiydi: u YOLG'ON BO'LA OLMAYDI. `manba_xeshi()` baribir saqlanadi —
#    u reliz hisobotiga yoziladigan, inson o'qiy oladigan imzo (BUILD_GATE.md).
#
# ⚠️ PyInstaller `build-onedir/<nom>/PYZ-00.pyz` ni ALOHIDA fayl bo'lib qoldiradi: sarlavha
#    `PYZ\0` + Python magic + TOC siljishi, TOC esa `marshal` bilan o'qiladigan
#    `{nom: (tur, siljish, uzunlik)}`. Yozuvlar `zlib` bilan siqilgan `marshal` kod
#    obyektlari. Hammasi STANDART kutubxona bilan o'qiladi — PyInstaller O'RNATILMAYDI
#    (umumiy `.venv` ga paket qo'shish TAQIQLANGAN).

#: PYZ yozuvining turlari (PyInstaller `pyimod01_archive`): 0 — modul, 1 — paket,
#: 3 — nom bo'shliqli paket (fayli YO'Q).
PYZ_TUR_MODUL, PYZ_TUR_PAKET, PYZ_TUR_NSPAKET = 0, 1, 3

PYZ_FAYL_NOMI = "PYZ-00.pyz"
BUILD_EXE_NOMI = "BinOSDiscoveryAgent.exe"

#: Darvoza holatlari.
HOLAT_TOZA = "TOZA"            # yig'ma JORIY manbadan qurilgani ISBOTLANDI
HOLAT_YOQ = "YO_Q"             # yig'ma umuman YO'Q (Linux CI)
HOLAT_ISBOTSIZ = "ISBOTSIZ"    # yig'ma BOR, lekin yangiligini isbotlab BO'LMAYDI
HOLAT_ESKIRGAN = "ESKIRGAN"    # yig'ma BOR va JORIY manbadan EMAS

#: ⚠️ `tests/ci_expected_skips.txt` dagi sabab bo'lagi AYNAN shu satr. O'zgartirilsa
#:    kutilgan-skip yozuvi mos kelmay qoladi va backend job QIZIL bo'ladi — ataylab
#:    shunday: skip sababi va uning ratifikatsiyasi BIRGA o'zgarishi kerak.
MUHIT_SABABI = "MUHIT: Windows EXE Linux CI'da QURILMAYDI"


class YigmaOqilmadi(RuntimeError):
    """Yig'ma ichidagi bytecode O'QILMADI — «toza» deb hisoblash TAQIQLANGAN."""


def exe_qurish_mumkinmi() -> bool:
    """Shu platformada Windows `.exe` qurish MUMKINMI.

    ⚠️⚠️ BU DARVOZANING O'ZAGI: `.exe` yo'qligi Windows'da YIQILISH, Linux'da esa MUHIT
         skip'i bo'ladi. Ya'ni «EXE yo'q bo'lsa yiqil» xulqi SHARTSIZ skip'ga
         AYLANTIRILMADI — u yig'ma qurilishi MUMKIN bo'lgan platformada BALAND qoladi.
    """
    return sys.platform == "win32"


def _sha256_fayl(yo_l: str) -> str:
    return hashlib.sha256(pathlib.Path(yo_l).read_bytes()).hexdigest()


def pyz_yoli() -> str:
    return os.path.join(YIGMA_BUILD, PYZ_FAYL_NOMI)


def build_exe_yoli() -> str:
    return os.path.join(YIGMA_BUILD, BUILD_EXE_NOMI)


def _konst_imzosi(k):
    """`co_consts` elementining TARTIBGA va JARAYONGA bog'liq bo'lmagan ko'rinishi.

    ⚠️⚠️ `repr()` ISHLATILMAYDI va bu haqiqiy tuzoq: `co_consts` ichida `in {...}` dan
         kelgan `frozenset` bo'ladi, uning `repr` TARTIBI esa satr xeshiga (ya'ni
         JARAYONGA) bog'liq. `repr` bilan solishtirilganda SOG'LOM yig'ma ham
         «eskirgan» bo'lib chiqardi — bu aynan shu kodni yozishda uchradi
         (`redact.py` va `result_package.py` yolg'on FARQ berdi, keyin usul tuzatildi).
    ⚠️ `float`/`complex` BAYT ko'rinishida olinadi: `nan != nan`, ya'ni tenglik bilan
       solishtirilsa sog'lom yig'ma yana «eskirgan» bo'lardi.
    ⚠️ TUR ham imzoga kiradi: `1` va `True` bytecode'da BOSHQA konstanta, lekin `==`
       bo'yicha teng.
    """
    if isinstance(k, types.CodeType):
        return ("code", kod_imzosi(k))
    if isinstance(k, (frozenset, set)):
        return ("set", tuple(sorted(repr(_konst_imzosi(x)) for x in k)))
    if isinstance(k, tuple):
        return ("tuple", tuple(_konst_imzosi(x) for x in k))
    if isinstance(k, bool):
        return ("bool", k)
    if isinstance(k, float):
        return ("float", struct.pack("<d", k))
    if isinstance(k, complex):
        return ("complex", struct.pack("<dd", k.real, k.imag))
    return (type(k).__name__, k)


#: Kod obyektining solishtiriladigan maydonlari.
#: ⚠️ `co_filename` va qator jadvali (`co_linetable`) QO'SHILMAYDI: ular yig'uvchining
#:    ishchi papkasiga va izoh/bo'sh qatorlarga bog'liq, ya'ni MANTIQ o'zgarmasa ham farq
#:    qilishi mumkin. Bu darvoza «yig'madagi KOD joriy manbaning kodimi» degan savolga
#:    javob beradi; izoh yoki yo'l farqi uchun relizni to'xtatish YOLG'ON qizil bo'lardi.
IMZO_MAYDONLARI: tuple[str, ...] = (
    "co_name", "co_qualname", "co_code", "co_names", "co_varnames", "co_flags",
    "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_freevars", "co_cellvars",
)


def kod_imzosi(kod: types.CodeType) -> tuple:
    """Kod obyektining REKURSIV, deterministik imzosi (ichki funksiyalar ham)."""
    asos = tuple(getattr(kod, maydon) for maydon in IMZO_MAYDONLARI)
    return asos + (tuple(_konst_imzosi(k) for k in kod.co_consts),)


def pyz_toc() -> tuple[bytes, dict[str, tuple[int, int, int]]]:
    """`(xom baytlar, TOC)` — yig'ma ichidagi modullar jadvali.

    ⚠️ PYTHON MAGIC TEKSHIRILADI: yig'ma BOSHQA Python bilan qurilgan bo'lsa bytecode
       baribir boshqa bo'ladi va solishtirish MA'NOSIZ. Bunda darvoza «toza» DEMAYDI —
       `YigmaOqilmadi` beradi, ya'ni natija ISBOTSIZ bo'lib yiqiladi.
    """
    yo_l = pyz_yoli()
    try:
        xom = pathlib.Path(yo_l).read_bytes()
    except OSError as e:
        raise YigmaOqilmadi(f"PYZ arxivi o'qilmadi ({yo_l}): {e}") from e
    if xom[:4] != b"PYZ\0":
        raise YigmaOqilmadi(f"PYZ sarlavhasi kutilganidan boshqa: {xom[:4]!r} ({yo_l})")
    if xom[4:8] != importlib.util.MAGIC_NUMBER:
        raise YigmaOqilmadi(
            f"Yig'ma BOSHQA Python bilan qurilgan: PYZ magic {xom[4:8]!r}, joriy "
            f"interpretator {importlib.util.MAGIC_NUMBER!r} ({sys.version.split()[0]}). "
            f"Bytecode solishtirib bo'lmaydi — yig'maning yangiligi ISBOTSIZ.")
    try:
        (siljish,) = struct.unpack("!i", xom[8:12])
        toc = dict(marshal.loads(xom[siljish:]))
    except Exception as e:                   # noqa: BLE001 - shakl buzuq bo'lsa ham ISBOTSIZ
        raise YigmaOqilmadi(f"PYZ TOC o'qilmadi ({type(e).__name__}: {e})") from e
    if not toc:
        raise YigmaOqilmadi("PYZ TOC bo'sh — o'qish usuli buzilgan")
    return xom, toc


def pyz_kodi(xom: bytes, yozuv: tuple[int, int, int]) -> types.CodeType:
    """PYZ yozuvidan kod obyektini chiqaradi."""
    _tur, siljish, uzunlik = yozuv
    return marshal.loads(zlib.decompress(xom[siljish:siljish + uzunlik]))


def _modul_manba_yoli(nom: str, tur: int) -> pathlib.Path:
    kok = pathlib.Path(SERVER_ROOT).joinpath(*nom.split("."))
    return (kok / "__init__.py") if tur in (PYZ_TUR_PAKET, PYZ_TUR_NSPAKET) \
        else kok.with_suffix(".py")


def eskirgan_modullar() -> list[str]:
    """Yig'ma ICHIDAGI `app.*` modullaridan JORIY manbaga mos KELMAYDIGANLARI.

    Har modul uchun: yig'madagi kod obyektining imzosi ↔ joriy manbani SHU yerda qayta
    kompilyatsiya qilib olingan imzo. Mos kelmasa — yig'ma eskirgan.

    ⚠️ `app.*` dan BOSHQA modul (standart kutubxona, `tkinter`) TEKSHIRILMAYDI: u bizning
       manbamiz emas va yig'uvchi Python'i bilan keladi.
    ⚠️ Manba fayli YO'Q bo'lsa ham ESKIRGAN deb hisoblanadi: yig'mada biz endi
       tarqatmaydigan modul qolib ketgan.
    """
    xom, toc = pyz_toc()
    nomos: list[str] = []
    app_modullari = sorted(n for n in toc if n == "app" or n.startswith("app."))
    if not any(n.startswith("app.services.discovery_agent") for n in app_modullari):
        # ⚠️ SHAKL DARVOZASI: agent modullari topilmasa «hammasi mos» degan xulosa BO'SH
        #    bo'lardi — o'qish usuli buzilgani darvozani JIMGINA yashil qilmasin.
        raise YigmaOqilmadi(
            f"PYZ ichida agent modullari topilmadi ({len(toc)} yozuv) — o'qish usuli buzilgan")
    for nom in app_modullari:
        tur, _s, _u = toc[nom]
        yo_l = _modul_manba_yoli(nom, tur)
        if not yo_l.is_file():
            nomos.append(f"{nom} (manba fayli YO'Q: {yo_l})")
            continue
        try:
            yigmadagi = pyz_kodi(xom, toc[nom])
        except Exception as e:               # noqa: BLE001 - buzuq yozuv ham ISBOTSIZ
            raise YigmaOqilmadi(
                f"{nom}: PYZ yozuvi o'qilmadi ({type(e).__name__}: {e})") from e
        manbadagi = compile(yo_l.read_bytes(), yigmadagi.co_filename, "exec",
                            dont_inherit=True, optimize=0)
        if kod_imzosi(yigmadagi) != kod_imzosi(manbadagi):
            nomos.append(yo_l.relative_to(pathlib.Path(SERVER_ROOT)).as_posix())
    return nomos


def yigma_yoqligi_sababi_muhit() -> str:
    """Yig'ma YO'Q bo'lganda MUHIT sababi — Linux CI'dagi skip AYNAN shu matn bilan.

    ⚠️ «Dependency o'rnatilmagan» EMAS: Linux Windows `.exe` ni QURA OLMAYDI (PyInstaller
       kross-kompilyatsiya qilmaydi, Windows runner esa backend job'da yo'q). Bu MUHIT
       cheklovi, va shu bois yig'ma shartnomasining Linux'da isbotlanadigan qismi
       ALOHIDA egaga (OWNER A) berilgan — ro'yxatdagi skip BO'SH joy qoldirmaydi.
    """
    return (f"{MUHIT_SABABI}. {yigma_yoqligi_sababi()} "
            f"Yig'ma SHARTNOMASI (tarkib, taqiqlar, kirish nuqtasi, chiqish kodlari) shu "
            f"yurishda MANBADAN tekshirildi (`test_A_*`); haqiqiy `.exe` parity'si "
            f"Windows reliz darvozasiga tegishli (`packaging/BUILD_GATE.md`).")


def yigma_tayyorligi() -> tuple[str, str]:
    """`(holat, sabab)` — haqiqiy parity'ni YURGIZISH mumkinmi va NEGA.

    ⚠️⚠️ FAIL-CLOSED: faqat `HOLAT_TOZA` da haqiqiy parity yurgiziladi. «Isbotlab
         bo'lmadi» holati «toza» ga AYLANTIRILMAYDI — eskirgan yig'ma jimgina o'tib
         ketishining yo'li aynan shu edi.
    """
    if not yigma_bor():
        return HOLAT_YOQ, yigma_yoqligi_sababi_muhit()
    build_exe = build_exe_yoli()
    if not os.path.isfile(pyz_yoli()):
        return HOLAT_ISBOTSIZ, (
            f"YIG'MA ESKIRGANMI — ISBOTSIZ: {pyz_yoli()} YO'Q. Yig'ma ({YIGMA_EXE}) BOR, "
            f"lekin uning bytecode'ini joriy manba bilan solishtirib bo'lmaydi, demak "
            f"«yig'ma manbaga teng» da'vosini TEKSHIRILMAGAN holda qabul qilish kerak "
            f"bo'lardi — bu TAQIQLANGAN. Build papkasini saqlang yoki qayta yig'ing "
            f"(`packaging/BUILD_GATE.md`); boshqa joyda bo'lsa `{YIGMA_BUILD_ENV_KALITI}`.")
    if not os.path.isfile(build_exe):
        return HOLAT_ISBOTSIZ, (
            f"YIG'MA ESKIRGANMI — ISBOTSIZ: {build_exe} YO'Q, demak build papkasidagi PYZ "
            f"TARQATILADIGAN `.exe` ni tasvirlashini isbotlab bo'lmaydi.")
    if _sha256_fayl(build_exe) != _sha256_fayl(YIGMA_EXE):
        return HOLAT_ISBOTSIZ, (
            f"YIG'MA ESKIRGANMI — ISBOTSIZ: build papkasidagi `.exe` tarqatiladigan `.exe` "
            f"dan FARQ qiladi ({build_exe} != {YIGMA_EXE}), demak `{PYZ_FAYL_NOMI}` boshqa "
            f"yig'mani tasvirlaydi. Spec'ni QAYTA yig'ib build va dist papkalarini birga "
            f"yangilang.")
    try:
        nomos = eskirgan_modullar()
    except YigmaOqilmadi as e:
        return HOLAT_ISBOTSIZ, f"YIG'MA ESKIRGANMI — ISBOTSIZ: {e}"
    if nomos:
        return HOLAT_ESKIRGAN, (
            f"YIG'MA ESKIRGAN: {len(nomos)} modul yig'ma ichida JORIY manbadan BOSHQA — "
            f"{', '.join(nomos)}. Haqiqiy parity YURGIZILMADI, chunki u eskirgan `.exe` ni "
            f"joriy manba bilan solishtirardi va o'zgargan modul tanlangan fiksturada farq "
            f"bermasa YASHIL bo'lib qolardi (yolg'on kafolat). Tuzatish: yig'mani QAYTA "
            f"qurish (`packaging/BUILD_GATE.md`). Joriy manba imzosi: {manba_xeshi()[:16]}.")
    return HOLAT_TOZA, ""
