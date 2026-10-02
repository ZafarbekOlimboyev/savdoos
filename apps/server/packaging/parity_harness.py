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

import hashlib
import json
import os
import pathlib
import subprocess
import sys
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
YIGMA_ENV_KALITI = "BINOS_AGENT_EXE"
_STANDART_EXE = pathlib.Path.home() / "binos-agent-build" / "dist-onedir" \
    / "BinOSDiscoveryAgent" / "BinOSDiscoveryAgent.exe"
YIGMA_EXE = os.environ.get(YIGMA_ENV_KALITI) or str(_STANDART_EXE)

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
