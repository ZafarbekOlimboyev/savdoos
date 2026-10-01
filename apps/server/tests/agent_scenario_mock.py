# -*- coding: utf-8 -*-
"""SSENARIY FIKSTURALARI — agentning 16 ssenariysi uchun SINTETIK muhit va paketlar.

⚠️⚠️ BU REAL 1C ISBOTI EMAS. Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI,
     `.epf` BAJARILMAYDI va HAQIQIY Windows reestri O'QILMAYDI. Hamma «o'rnatma», «infobaza»
     va «yig'uvchi fayli» — xotiradagi yoki `tmp_path` dagi TO'QIMA narsalar. Shu bois bu
     fiksturalar javob beradigan YAGONA savol: «muhit shunday ko'rinsa, AGENT TO'G'RI hukm
     chiqaradimi?». Yig'uvchining va integratsiya yo'llarining runtime holati bundan keyin
     ham `RUNTIME-UNKNOWN` bo'lib qoladi.

⚠️⚠️ BU MASHINADA 1C UMUMAN O'RNATILMAGAN (`C:\\Program Files\\1cv8` yo'q,
     `HKLM\\SOFTWARE\\1C\\1Cv8` yo'q, `1cv8.exe`/`ibcmd.exe` PATH da yo'q, COM klasslari
     ro'yxatda yo'q, `pywin32` yo'q). Shu bois COM yo'li ham, paketli yo'lning 1C bilan
     ishlaydigan qismi ham BU YERDA SINAB BO'LMAYDI — «ishlamaydi» emas, «tekshirib
     bo'lmaydi». Fiksturalar faqat BinOS tomonidagi QAROR mantiqini o'lchaydi.

NUSXA KO'CHIRILMAGAN NARSALAR (ataylab):
  · runtime paketlari — `tests.discovery_1c_runtime_mock` (Phase 4 generatorlari);
  · metadata konfiguratsiyalari — `tests.discovery_1c_metadata_synth` (A..O);
  · sintetik reestr/fayl tizimi o'quvchilari — `tests.test_agent_detector` dagi
    `FakeRegistry`/`FakeFiles`. ⚠️ Ular test modulidan IMPORT qilinadi, qayta yozilmaydi:
    ikki nusxa bir kun bir-biridan ajralib ketardi va qaysi biri haqiqat ekani aniqlanmay
    qolardi. Loyihada bu naqsh allaqachon bor (`tests/cash/` modullari bir-biridan fikstura
    oladi, `pyproject.toml` dagi `pythonpath` izohiga qarang).
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

from app.services.discovery_agent import detector as D
from app.services.discovery_agent import ui as U
from tests.test_agent_detector import INSTALL_KEY, ONE_HIVE, FakeFiles, FakeRegistry

# ══════════════════════════════════════════════════════════════════════════════════════════
# VAQT — KIRISHDAN, hisoblanmaydi
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Yurishning YAGONA tamg'asi. Soat O'QILMAYDI: bir xil kirish bir xil bayt berishi kerak
#: (determinizm ssenariysi 10 shunga tayanadi).
NOW_ISO = "2026-10-01T09:00:00+06:00"
#: Muhit skanerining tamg'asi — ATAYLAB boshqa (UTC): hujjatlar bir-birining vaqtini
#: taxmin qilmasligi kerak.
SCANNED_AT = "2026-10-01T09:00:00+00:00"
OS_VERSION = "Windows-11-10.0.26200-SP0"

#: Sintetik 1C versiyalari — eski va yangi. ⚠️ Ikki o'rnatma ssenariysi (2) uchun TARTIB
#: muhim: `newest_install()` kattasini tanlashi kerak.
ESKI_VERSIYA = "8.3.20.1789"
YANGI_VERSIYA = "8.3.24.1548"

# ══════════════════════════════════════════════════════════════════════════════════════════
# SINTETIK SIR — ⚠️ TO'QIMA, hech kimning haqiqiy kredensiali EMAS
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Bu qiymatlar `ibases.v8i` fiksturasiga ATAYLAB qo'yiladi: test ularning agentning
#: BIRORTA chiqishida (hisobot, yurish yozuvi, muhit hujjati, buyruq satri) KO'RINMASLIGINI
#: isbotlaydi. Shu bois ular nom bilan izlanadi va alohida doimiy bo'lib turadi.
SIR_LOGIN = "sintetikfoydalanuvchi"
SIR_PAROL = "sintetikparol00"
#: Chiqishda UMUMAN uchramasligi kerak bo'lgan bo'laklar.
SIR_IZLARI: tuple[str, ...] = (SIR_LOGIN, SIR_PAROL, "Pwd=", "Usr=")


# ══════════════════════════════════════════════════════════════════════════════════════════
# DISKDAGI SOXTA FAYLLAR (mavjudlik tekshiruvlari uchun)
# ══════════════════════════════════════════════════════════════════════════════════════════
def exe_yoz(root, versiya: str = YANGI_VERSIYA) -> str:
    """Soxta `1cv8.exe` ni `<root>/1cv8/<versiya>/bin/` ga yozadi va yo'lini qaytaradi.

    ⚠️ NEGA HAQIQIY FAYL KERAK: `collector_bridge._batch_preflight` ijro faylining BORLIGINI
       `os.path.isfile` bilan tekshiradi. Yo'q bo'lsa yo'l `FAILED_NO_1C` da to'xtaydi, ya'ni
       undan KEYINGI darvozalar (nishon, parol) UMUMAN o'lchanmay qolardi.
    ⚠️ BU FAYL 1C EMAS va ISHGA TUSHIRILMAYDI: ichida bir nechta bayt matn turadi. Agent
       jarayon ochmaydi — `runner` testda almashtiriladi yoki quvur unga yetib ham bormaydi.
    ⚠️ Har versiya O'Z yo'lini oladi: `detector._dedupe` AYNI exe yo'lini bitta o'rnatma deb
       birlashtiradi, ya'ni ikki versiyani bir faylga qaratsak «ikki o'rnatma» ssenariysi
       jimgina «bitta o'rnatma» ga aylanib qolardi.
    """
    p = pathlib.Path(root) / "1cv8" / versiya / "bin" / "1cv8.exe"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"SINTETIK: bu 1C EMAS, faqat mavjudlik tekshiruvi uchun")
    return str(p)


def epf_yoz(root, nom: str = "BinOSDiscovery.epf") -> str:
    """Soxta yig'uvchi `.epf` — faqat MAVJUDLIK uchun.

    ⚠️ Bu haqiqiy `.epf` konteyneri EMAS va kompilyatsiya qilinmagan: repoda `.epf` HOZIR
       umuman yo'q (`AGENT_INTEGRATION_MATRIX.md`, «BSL BO'SHLIG'I»). Agent bu faylni
       O'QIMAYDI ham — u faqat `os.path.isfile` darvozasidan o'tadi.
    """
    p = pathlib.Path(root) / nom
    p.write_bytes(b"SINTETIK .epf: konteyner EMAS, kompilyatsiya QILINMAGAN")
    return str(p)


def bosh_papka(root, nom: str) -> str:
    """BO'SH papka — ko'prik talabi (`output_dir` bo'sh bo'lmasa `FAILED_SAFETY`)."""
    p = pathlib.Path(root) / nom
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


# ══════════════════════════════════════════════════════════════════════════════════════════
# SINTETIK REESTR
# ══════════════════════════════════════════════════════════════════════════════════════════
def reestr(root, *versiyalar: str) -> FakeRegistry:
    """`HKLM\\SOFTWARE\\1C\\1Cv8` ostida berilgan versiyalar, har biri O'Z exe yo'li bilan."""
    tree = {FakeRegistry.key(D.HKLM, INSTALL_KEY): {"subkeys": list(versiyalar)}}
    for v in versiyalar:
        tree[FakeRegistry.key(D.HKLM, f"{INSTALL_KEY}\\{v}")] = {
            "values": {"Path": exe_yoz(root, v)}}
    return FakeRegistry(tree)


def reestr_bosh() -> FakeRegistry:
    """Reestr O'QILDI va BO'SH chiqdi — «1C o'rnatilmagan» JAVOBI."""
    return FakeRegistry()


def reestr_huquq_yoq() -> FakeRegistry:
    """Reestr O'QILMADI (huquq yetmadi) — javobning O'ZI YO'Q.

    ⚠️ `reestr_bosh()` dan ANIQ ajratilgan: birinchisi `absent` (xulosa HAQLI), bu esa
       `unknown` (xulosa HAQLI EMAS). Ikkisini bitta fiksturaga qo'shib yuborish ssenariy
       1 va 8 ni farqlanmas qilib qo'yardi.
    """
    return FakeRegistry(unreadable_prefixes=(FakeRegistry.key(D.HKLM, INSTALL_KEY),))


# ══════════════════════════════════════════════════════════════════════════════════════════
# SINTETIK `ibases.v8i`
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Baza:
    """`ibases.v8i` ga yoziladigan bitta infobaza e'loni.

    `parol_kerak=True` bo'lsa satrga `Usr=`/`Pwd=` qo'yiladi — `detector._parse_connect`
    AYNAN shu kalitlarning BORLIGIDAN `requires_auth="true"` chiqaradi va QIYMATNI hech
    qaerga yozmaydi.
    """

    nom: str
    yol: str
    parol_kerak: bool = False


def v8i_matn(*bazalar: Baza) -> str:
    """`.v8i` (INI ko'rinishidagi) fayl matni."""
    bloklar = []
    for b in bazalar:
        connect = f'File="{b.yol}";'
        if b.parol_kerak:
            connect += f"Usr={SIR_LOGIN};Pwd={SIR_PAROL};"
        bloklar.append(f"[{b.nom}]\nConnect={connect}\n")
    return "\n".join(bloklar)


def _ibases_sozlama(yol: str) -> D.DetectorConfig:
    """⚠️ `filesystem_roots` BO'SH qoladi: haqiqiy `C:\\Program Files` ga qaramaslik SHART —
    aks holda to'plam mashinaning holatiga bog'liq bo'lib qolardi."""
    return D.DetectorConfig(registry_install_keys=ONE_HIVE,
                            ibases_files=((D.SOURCE_IBASES_USER, yol),))


# ══════════════════════════════════════════════════════════════════════════════════════════
# MUHIT SKANERI — FAQAT SINTETIK MANBALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def muhit(*, registry=None, files=None, config=None) -> D.EnvironmentScan:
    """`detector.scan_environment` ni SINTETIK manbalar bilan yurgizadi.

    ⚠️ `which` DOIM `None` qaytaradi: haqiqiy `PATH` tekshirilsa, 1C o'rnatilgan mashinada
       to'plam boshqacha natija berardi. Soat va OS versiyasi ham KIRISHDAN.
    """
    return D.scan_environment(
        config=config if config is not None else D.DetectorConfig(
            registry_install_keys=ONE_HIVE),
        registry=registry if registry is not None else FakeRegistry(),
        files=files if files is not None else FakeFiles(),
        which=lambda _nom: None,
        now=lambda: SCANNED_AT,
        os_version=lambda: OS_VERSION,
    )


def muhit_1c_yoq() -> D.EnvironmentScan:
    """SSENARIY 1: hamma manba O'QILDI va BO'SH chiqdi -> `presence_verdict == "absent"`."""
    return muhit(registry=reestr_bosh())


def muhit_huquq_yoq() -> D.EnvironmentScan:
    """SSENARIY 8: reestr O'QILMADI -> `presence_verdict == "unknown"`.

    ⚠️ `installs` bu yerda ham BO'SH, lekin BO'SHLIGINING MA'NOSI boshqa: «qaradim va yo'q»
       emas, «qaray olmadim». Agent ikkisini ARALASHTIRMASLIGI kerak.
    """
    return muhit(registry=reestr_huquq_yoq())


def muhit_bazasiz(root) -> D.EnvironmentScan:
    """SSENARIY 3: 1C BOR, lekin birorta infobaza e'lon qilinmagan."""
    return muhit(registry=reestr(root, YANGI_VERSIYA))


def muhit_bazali(root, *bazalar: Baza,
                 versiyalar: tuple[str, ...] = (YANGI_VERSIYA,)) -> D.EnvironmentScan:
    """1C BOR + berilgan infobazalar e'lon qilingan.

    ⚠️ `versiyalar` — ikki o'rnatma ssenariysi (2) uchun; standart holda bitta.
    """
    yol = str(pathlib.Path(root) / "ibases.v8i")
    vers = tuple(versiyalar)
    return muhit(registry=reestr(root, *vers),
                 files=FakeFiles(texts={yol: v8i_matn(*bazalar)}),
                 config=_ibases_sozlama(yol))


def baza_oddiy(root, nom: str = "Sintetik fayl bazasi") -> Baza:
    """Parol kaliti YO'Q baza. ⚠️ `requires_auth` baribir `"unknown"` bo'ladi: parolsiz
    kirishni ULANMASDAN isbotlab bo'lmaydi va `detector` fail-closed tomonda turadi."""
    return Baza(nom=nom, yol=str(pathlib.Path(root) / "sintetik-baza"))


def baza_parolli(root, nom: str = "Sintetik parolli baza") -> Baza:
    """SSENARIY 4: `Usr=`/`Pwd=` kalitlari bor baza -> `requires_auth == "true"`."""
    return Baza(nom=nom, yol=str(pathlib.Path(root) / "sintetik-parolli-baza"),
                parol_kerak=True)


# ══════════════════════════════════════════════════════════════════════════════════════════
# AGENT — HAMMA TASHQI BOG'LIQLIK ALMASHTIRILGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def agent(parent_dir, *, scan: D.EnvironmentScan, bundle_dir=None, epf_path=None,
          output_dir=None, analyzer=None, now: str = NOW_ISO, runner=None,
          mode=None) -> U.UiModel:
    """Sinovga tayyor `UiModel`: oyna OCHMAYDI, soatga QARAMAYDI, 1C ga ULANMAYDI.

    ⚠️ `clock` nol qaytaradi va `sleeper` hech narsa qilmaydi: ko'prikning kutish mantiqi
       HAQIQIY soniyalarni kutmasligi kerak (to'plam tez qolishi uchun).
    ⚠️ `opener` BERILMAYDI: agent hech narsa ochmaydi. Test uni chaqirmaydi ham.
    """
    kw = {}
    if mode is not None:
        kw["mode"] = mode
    return U.UiModel(
        parent_dir=str(parent_dir),
        bundle_dir=None if bundle_dir is None else str(bundle_dir),
        epf_path=None if epf_path is None else str(epf_path),
        output_dir=None if output_dir is None else str(output_dir),
        scan=lambda: scan,
        now=lambda: now,
        clock=lambda: 0.0,
        sleeper=lambda _s: None,
        runner=runner,
        analyzer=analyzer,
        **kw,
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# NATIJA PAPKASINI O'QISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def paket_yoz(papka, generator, **kw) -> str:
    """Phase 4 runtime paketini `papka` ga yozadi (generator `discovery_1c_runtime_mock` dan).

    ⚠️ GENERATOR QAYTA ISHLATILADI, nusxa ko'chirilmaydi: paket SHAKLI Phase 4 shartnomasi
       va uni bu yerda qaytadan yozish ikki haqiqat yasardi.
    """
    p = pathlib.Path(papka)
    p.mkdir(parents=True, exist_ok=True)
    generator(str(p), **kw)
    return str(p)


def papka_baytlari(papka) -> dict[str, bytes]:
    """Natija papkasidagi HAMMA fayl (`bundle/` ichi ham), nisbiy nom -> baytlar."""
    kok = pathlib.Path(papka)
    out: dict[str, bytes] = {}
    for yo_l in sorted(kok.rglob("*")):
        if yo_l.is_file():
            out[yo_l.relative_to(kok).as_posix()] = yo_l.read_bytes()
    return out


def matn(papka, nom: str) -> str:
    """Natija papkasidagi faylning UTF-8 matni."""
    return pathlib.Path(papka, *nom.split("/")).read_text(encoding="utf-8")


def fayl_bor(papka, nom: str) -> bool:
    return os.path.isfile(os.path.join(papka, *nom.split("/")))


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAQT SOXTALARI — UCHIGA-UCH ISBOT (A..K) UCHUN QO'SHILDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def oshuvchi_soat(qadam: float = 1.0):
    """MONOTON soxta soat: har chaqiruvda `qadam` soniya oshadi, HAQIQIY vaqt o'qilmaydi.

    ⚠️ NEGA KERAK: yuqoridagi `agent()` soati QOTIB QOLGAN (`lambda: 0.0`) va u bilan
       ko'prikning VAQT chegarasi hech qachon urmaydi — kutish faqat O'LCHOV SONI chegarasi
       bilan tugaydi (`collector_bridge._wait_until_ready` ikki mustaqil chegara). Kutish
       ssenariysi (C) esa AYNAN vaqt chegarasining urishini ham o'lchashi kerak, shu bois
       soat oshib turishi SHART.
    ⚠️ HAQIQIY `time.monotonic` ISHLATILMAYDI: to'plam mashinaning tezligiga bog'liq
       bo'lib qolardi va kutish ssenariysi sekin mashinada boshqa yo'ldan ketardi.
    """
    holat = {"t": 0.0}

    def soat() -> float:
        joriy = holat["t"]
        holat["t"] = joriy + qadam
        return joriy

    return soat


def yozib_oluvchi_uyqu(jurnal: list) -> object:
    """HAQIQIY KUTMAYDIGAN `sleeper`: so'ralgan soniyalarni `jurnal` ga YOZIB OLADI.

    ⚠️ NEGA JURNAL: «cheksiz kutish YO'Q» da'vosini o'lchash uchun agentning NECHA MARTA va
       QANCHA kutishni so'raganini bilish kerak. `time.sleep` chaqirilmaydi — aks holda bu
       bitta test to'plamni daqiqalarga uzaytirardi.
    """
    def uxla(soniya: float) -> None:
        jurnal.append(soniya)

    return uxla


def kutuvchi_agent(parent_dir, *, bundle_dir, scan=None, analyzer=None,
                   timeout_seconds: float = 6.0, poll_seconds: float = 2.0,
                   uyqu_jurnali=None, qadam: float = 1.0):
    """`watch_folder` yo'lidagi agent — CHEKLI va QISQA kutish bilan.

    ⚠️ `epf_path` ATAYLAB BERILMAYDI: bu MVP ning YAGONA shipped marshruti (operator
       yig'uvchini O'ZI yurgizadi, agent papkani kuzatadi — `AGENT_OPERATOR_FLOW.md` §1).
    ⚠️ Kutish chegarasi KICHIK (standart 900 s emas): chegara KIRISHDAN keladi, demak uni
       kichraytirish XULQNI o'zgartirmaydi, faqat testni tez qiladi.
    ⚠️ `UiModel` frozen EMAS, shu bois kutish parametrlari obyekt qurilgandan KEYIN
       qo'yiladi — `agent()` ning imzosini kengaytirish mavjud 16 ssenariyga tegishi
       mumkin edi va u fikstura HOZIR ishlayapti.
    """
    model = agent(parent_dir, scan=scan if scan is not None else muhit_1c_yoq(),
                  bundle_dir=bundle_dir, analyzer=analyzer)
    model.clock = oshuvchi_soat(qadam)
    model.sleeper = yozib_oluvchi_uyqu([] if uyqu_jurnali is None else uyqu_jurnali)
    model.watch_timeout_seconds = timeout_seconds
    model.watch_poll_seconds = poll_seconds
    return model
