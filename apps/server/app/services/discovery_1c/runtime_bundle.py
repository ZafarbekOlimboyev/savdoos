# -*- coding: utf-8 -*-
"""RUNTIME PAKETI — haqiqiy 1C mashinasidan chiqadigan PAPKA va uning OFFLINE validatori.

Bu modul 1C'ga ULANMAYDI, tarmoqqa CHIQMAYDI va AI provayderini TALAB QILMAYDI. U operator
olib kelgan papkani o'qiydi va «bu paket keyingi qadamga yaroqlimi?» degan savolga
STRUKTURALI javob beradi (`Report`). Hech narsa yozmaydi, hech narsa tuzatmaydi.

⚠️ BU NIMANI ISBOTLAYDI: papkadagi BAYTLAR shartnomaga mos, ichida sir yo'q, sanoqlar MATN,
   xesh mos va keyingi qatlamlar (to'plam ko'prigi, graf, AI yuki) shu paketdan QURILA OLADI.
⚠️ BU NIMANI ISBOTLAMAYDI: yig'uvchining 1C'da ISHLASHINI, `.epf` ning kompilyatsiya
   bo'lishini, topilgan nomzodning TO'G'RI ekanini. Yig'uvchi runtime holati —
   `RUNTIME-UNKNOWN` va u shu modul bilan o'zgarmaydi.

## PAKET SHARTNOMASI (yetti artefakt)

    export.json        `binos-1c-export-v1`     MAJBURIY   Phase 2 shakli, O'ZGARMAGAN
    metadata.json      `binos-1c-metadata-v1`   MAJBURIY   Phase 3 shakli, O'ZGARMAGAN
    run_status.json    `binos-1c-run-v1`        MAJBURIY   YANGI: rejim, vaqtlar, bo'limlar
    errors.json        `binos-1c-errors-v1`     MAJBURIY   YANGI: strukturali xatolar (bo'sh
                                                          bo'lishi MUMKIN, fayl esa SHART)
    run_summary.md     —                        MAJBURIY   operator uchun: nima bo'ldi
    manifest.json      `binos-1c-manifest-v1`   MAJBURIY   YANGI: har fayl uchun SHA-256
    probes/NN_<tur>.json `binos-1c-probe-v1`    IXTIYORIY  faqat `APPROVED_PROBES` rejimida

⚠️ NEGA `run_status.json` va `run_summary.md`, `status.json`/`summary.md` EMAS.
   `binos-1c-discovery-v1` TO'PLAMINING besh a'zosi AYNAN `status.json` va `summary.md` deb
   ataladi va ularni ADAPTER quradi (`export_adapter.to_bundle_members`) — ya'ni ular BU
   paketning fayllari emas, undan KEYIN tug'iladigan boshqa hujjatning fayllari. Bir xil nom
   ikki xil sxemani anglatsa, tuzoq ikki tomonlama bo'ladi: operator ikki papkadan birini
   boshqasi deb o'qiydi, kod esa noto'g'ri validatorni chaqirib «yashil» javob beradi. Shu
   bois runtime paketi BOSHQA nom oladi va nom farqi shartnomaning bir qismi.

⚠️ MANIFEST — PROVENANS DA'VOSI EMAS. U faqat YOZILGAN BAYTLARNING sha256'si, ya'ni
   «papkadagi fayl ko'chirishda buzilmadimi?» degan savolga javob beradi. `source_copy`,
   `snapshot_at`, `plan_sha256` kabi MANBA provenansi maydonlari QO'SHILMAYDI: ular metadata
   razvedkasidan KELIB CHIQMAYDI (yig'uvchi qaysi `.dt` faylidan tiklangan nusxada
   ishlayotganini bila olmaydi) va Phase 2 qoidasi ularni ATAYLAB taqiqlagan. Manifestda
   faqat uch maydon: fayl nomi, bayt hajmi, sha256 — va bu ro'yxat `FORBIDDEN_MANIFEST_KEYS`
   bilan qulflangan, ya'ni provenans maydoni «zararsiz qo'shimcha» sifatida kirib kelmaydi.

⚠️ MANIFEST O'ZINI XESHLAMAYDI, `run_status.artifacts` esa O'ZINI HAM SANAYDI. Asimmetriya
   ATAYLAB: manifest o'z xeshini o'z ichiga yozsa, yozish xeshni o'zgartirardi (aylanma),
   nomni SANASH esa mazmunga tegmaydi. Shu ikki qoidani birga bajaradigan YAGONA yozish
   navbati bor va yig'uvchi shunga amal qilishi kerak:
       1. `export.json`, `metadata.json`, `errors.json`, `run_summary.md`, `probes/*.json`
       2. `run_status.json` — `artifacts` da HAMMA fayl, `manifest.json` ham, o'zi ham
       3. `manifest.json` — 1 va 2 da yozilgan fayllarning xeshi (o'zidan TASHQARI)

## YAGONA HAQIQIY SHAKL (arxitektor qarori)

⚠️ ILGARI FAQAT ARTEFAKT JADVALI KELISHILGAN EDI, KALIT NOMLARI EMAS. Natijada yig'uvchi
   (`BinOSDiscovery.bsl`) va bu validator bir-biriga ZID shakl yozdi — masalan yurish
   jurnalini yig'uvchi `probes`, validator esa `probes_run` deb atardi — ya'ni HAR BIR
   real paket rad etilardi. Endi shakl QAT'IY va IKKI TOMON AYNAN shunga yozadi:

    run_status.json   run_version · collector · mode · mode_note · started_at · finished_at
                      overall · platform · sections · families · probes · artifacts
                      error_count · notes
    errors.json       errors_version · collected_at · errors · notes
    manifest.json     manifest_version · files · notes
    probes/NN.json    probe_version · probe_type · target_object · read_only · result
                      errors · mode

⚠️ `absent` va `unreadable` FAQAT `families[].state` da yashaydi. `sections[].status` da
   ular BO'LMAYDI — bo'lim lug'ati `bundle.SECTION_STATUSES` bilan bir xil qoladi
   (`ok|failed|skipped`). Oila o'qilmasa: `families` da `unreadable` VA tegishli bo'lim
   `failed`. Oila yo'q bo'lsa: `families` da `absent` VA bo'lim `ok`. Sabab: bir xil
   so'zning ikki lug'atda turishi ikki tomonni bir-biriga zid qilib qo'yardi.

## REJIMLAR (§5)

`METADATA_ONLY` — **DEFAULT**. Hech qanday aktiv zond YO'Q: `probes` jurnali BO'SH va
`probes/` papkasi BO'SH bo'lishi SHART.
`APPROVED_PROBES` — faqat operator bergan ANIQ allowlist. Har zondning TURI (katalog kaliti),
NISHONI, SABABI, FAYLI va bajarilish O'RNI `probes` jurnalida ko'rsatiladi; o'zboshimcha kod
YO'Q, chunki `probe.PROBE_CATALOG` dan tashqari nom RAD etiladi.

⚠️ Default HAR DOIM `METADATA_ONLY`: argument berilmasa YOKI noma'lum rejim kelsa, natija
   `METADATA_ONLY` bo'ladi (fail-safe) va bu `run_status.mode_note` da QAYD ETILADI. Noma'lum
   rejimni jimgina eng qat'iy rejimga tushirish — yig'uvchi tomonidagi imlo xatosi aktiv
   zondlarni ishga tushirib yubormasligi uchun. `resolve_mode()` ga qarang.

⚠️ `mode_note` HAR IKKI REJIMDA to'ldirilishi MUMKIN va bu shakl qarori: u «rejim QANDAY hal
   bo'ldi» degan savolga javob beradi, faqat fail-safe tushishiga emas. Ilgari bu yerda
   `APPROVED_PROBES` da `mode_note` `null` bo'lishi TALAB qilinardi — yig'uvchi esa izohni
   har yurishda yozadi, ya'ni talab operator tasdiqlagan har bir aktiv zond yurishini rad
   etardi.

## FAIL-CLOSED QOIDALARI

  1. Noma'lum kalit RAD, tushib qolgan kalit RAD, noma'lum enum qiymati RAD.
  2. JSON SONI TAQIQLANGAN — har qanday sanoq MATN. `true`/`false` ham TAQIQLANGAN: 1C
     uchulik mantiqi MATN bilan keladi (`"unknown"` = «qaralmadi», `"false"` = «qaradi va
     yo'q»), JSON booleani esa uchinchi holatni JIMGINA yo'q qiladi.
  3. Bajarilmagan tekshiruv `ok=True` BO'LMAYDI. Kirishi yo'q tekshiruv `ok=False` va detali
     «bajarilmadi». «Tekshirib ko'rmadim» — «muammo yo'q» EMAS.
  4. Sir topilsa DARHOL `ok=False`, va xato matnida qiymatning O'ZI KO'RSATILMAYDI.
  5. `absent` va `unreadable` ALOHIDA holatlar. «Bu konfiguratsiyada yo'q» — to'liq javob;
     «o'qiy olmadim» — javob yo'qligi. Ikkisini qo'shib yuborish razvedkaning ma'nosini buzadi.

Bu modulda birorta konfiguratsiyaga yoki ijarachiga oid nom YO'Q: oila nomlari, obyekt nomlari
va zond nishonlari paket ICHIDAN kelgan MA'LUMOT.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from . import MAX_MEMBER_BYTES
from . import redact as redaction
from . import ai
from .bundle import COUNT_TEXT_RE, SECTION_STATUSES, DiscoveryError, dumps, load_members
from .export_adapter import EXPORT_VERSION, to_bundle_members, validate_export
from .graph import build_graph
from .metadata import METADATA_VERSION, validate_metadata
from .probe import PROBE_CATALOG, PROBE_VERSION, ProbeError, assert_no_raw_code
from .schema import (CONFIDENCE_CANDIDATE, CONFIDENCE_UNKNOWN, STRONG_EVIDENCE_KINDS, TARGETS,
                     WEAK_EVIDENCE_KINDS)
from ..migrator_1c.bundle import BundleError, parse_ts, sha256_bytes, strict_json_loads

# ── Versiyalar ─────────────────────────────────────────────────────────────────────────────
RUN_VERSION = "binos-1c-run-v1"
ERRORS_VERSION = "binos-1c-errors-v1"
MANIFEST_VERSION = "binos-1c-manifest-v1"

#: Hisobotning O'Z versiyasi — `--json` chiqishini o'qiydigan operator skripti uchun.
#: ⚠️ Paketning versiyasi EMAS: bu VALIDATOR chiqishining shakli.
REPORT_VERSION = "binos-1c-runtime-report-v1"

# ── Fayl nomlari ───────────────────────────────────────────────────────────────────────────
EXPORT_FILE = "export.json"
METADATA_FILE = "metadata.json"
RUN_STATUS_FILE = "run_status.json"
ERRORS_FILE = "errors.json"
RUN_SUMMARY_FILE = "run_summary.md"
MANIFEST_FILE = "manifest.json"
PROBE_DIR = "probes"

#: Majburiy fayllar — birortasi yo'q bo'lsa paket RAD. Tartib SHARTNOMA (hisobot shu tartibda
#: nom sanaydi), shu bois ro'yxat tartiblangan holda yozilgan.
REQUIRED_FILES: tuple[str, ...] = (ERRORS_FILE, EXPORT_FILE, MANIFEST_FILE, METADATA_FILE,
                                   RUN_STATUS_FILE, RUN_SUMMARY_FILE)

#: Ixtiyoriy a'zolar — ODAM O'QIYDIGAN shakl ro'yxati (hisobotga va xato matniga chiqadi).
#: ⚠️ Bu ro'yxat MOSLASHTIRUVCHI EMAS: haqiqiy darvoza `PROBE_NAME_RE`. Ikkisi ataylab
#: ajratilgan, chunki regexni xato matniga ko'chirish operatorga hech narsa aytmaydi.
OPTIONAL_FILES: tuple[str, ...] = (f"{PROBE_DIR}/NN_<tur>.json",)

#: `probes/NN_<tur>.json`: NN — bajarilish TARTIBI (ikki raqam), `<tur>` — katalog kaliti.
#: ⚠️ `NN` ikki raqam bo'lgani uchun bitta paketda 100 tadan ko'p zond fayli bo'lishi mumkin
#: emas — bu chegara ataylab, shakldan kelib chiqadi.
PROBE_NAME_RE = re.compile(rf"{PROBE_DIR}/(?P<seq>[0-9]{{2}})_(?P<tur>[a-z][a-z0-9_]*)\.json")

#: Bitta fayl uchun yuqori chegara. ⚠️ To'plam bilan AYNI chegara, AYNI joydan:
#: ikki xil chegara bir kun bir-biridan ajralib ketardi.
MAX_FILE_BYTES = MAX_MEMBER_BYTES

# ── Rejimlar ───────────────────────────────────────────────────────────────────────────────
MODE_METADATA_ONLY = "METADATA_ONLY"
MODE_APPROVED_PROBES = "APPROVED_PROBES"
MODES: tuple[str, ...] = (MODE_APPROVED_PROBES, MODE_METADATA_ONLY)
DEFAULT_MODE = MODE_METADATA_ONLY

# ── Umumiy holat ───────────────────────────────────────────────────────────────────────────
OVERALL_SUCCESS = "SUCCESS"
OVERALL_PARTIAL = "PARTIAL"
OVERALL_FAILED = "FAILED"
OVERALLS: tuple[str, ...] = (OVERALL_FAILED, OVERALL_PARTIAL, OVERALL_SUCCESS)

#: Oila holati. ⚠️ `absent` va `unreadable` ALOHIDA: birinchisi JAVOB («bu konfiguratsiyada
#: bunday oila yo'q»), ikkinchisi javob YO'QLIGI («qaradim, o'qiy olmadim»). Ularni bitta
#: qiymatga qo'shib yuborish razvedkaning butun ma'nosini buzadi.
FAMILY_STATES: tuple[str, ...] = ("absent", "present", "unreadable")

#: Xatoning qaysi darajada yuz berganini aytadi.
#: ⚠️ `run` EMAS, `platform`/`write`/`mode`: «yurish darajasidagi xato» juda keng edi va
#: operatorga xato QAYERDAN kelganini aytmasdi. Uchta aniq qamrov uchovi ham oiladan
#: TASHQARIDA yuz beradi (platforma so'rovi, fayl yozish, rejim hal qilish), shu bois
#: ularda `family` `null` bo'lishi SHART — oila nomi `run_status.families` bilan
#: solishtiriladi va «platforma» degan oila mavjud emas.
ERROR_SCOPES: tuple[str, ...] = ("family", "mode", "object", "platform", "probe", "write")

#: Oiladan TASHQARIDAGI qamrovlar — `family` `null`, `object` esa IXTIYORIY (platforma
#: maydonining nomi, yozilmagan faylning nomi).
RUN_LEVEL_SCOPES: tuple[str, ...] = ("mode", "platform", "write")

# ── Kalit oq ro'yxatlari ───────────────────────────────────────────────────────────────────
#: ⚠️ YAGONA HAQIQIY SHAKL (modul docstringiga qarang). Bu ro'yxat `BinOSDiscovery.bsl` dagi
#: `СобратьСостояниеЗапуска` bilan AYNAN bir xil bo'lishi SHART — `test_discovery_1c_runbook`
#: ikkisini solishtiradi.
RUN_KEYS = {"run_version", "collector", "mode", "mode_note", "started_at", "finished_at",
            "overall", "platform", "sections", "families", "probes", "artifacts",
            "error_count", "notes"}
COLLECTOR_KEYS = {"name", "version"}
RUN_SECTION_KEYS = {"name", "status", "error"}
FAMILY_KEYS = {"name", "state", "detail"}

#: Bajarilgan zondning JURNAL qatori (`run_status.probes[]`). ⚠️ Zond NATIJASI boshqa hujjat
#: (`PROBE_RESULT_KEYS`): jurnal «nima bajarildi va qayerga yozildi» ni aytadi, natija esa
#: «nima chiqdi» ni.
PROBE_LOG_KEYS = {"no", "probe_type", "target_object", "reason", "file", "status"}

ERRORS_DOC_KEYS = {"errors_version", "collected_at", "errors", "notes"}
ERROR_KEYS = {"scope", "family", "object", "code", "detail"}

MANIFEST_DOC_KEYS = {"manifest_version", "files", "notes"}
MANIFEST_FILE_KEYS = {"name", "bytes", "sha256"}

#: `binos-1c-probe-v1` NATIJASINING kalitlari (`probe.PROBE_KEYS` — SO'ROVNING kalitlari,
#: ular boshqa hujjat va ularni aralashtirmaslik uchun shakl shu yerda alohida yoziladi).
#: ⚠️ `mode` natijaning O'ZIDA ham turadi: zond fayli paketdan ajratib olinib uzatilsa,
#: «bu qaysi rejimda bajarildi» degan savol javobsiz qolmasligi kerak.
PROBE_RESULT_KEYS = {"probe_version", "probe_type", "target_object", "read_only", "result",
                     "errors", "mode"}

#: `run_status.platform` KALITINING shakli (§11 ishga tushirish maydonlari).
#: ⚠️ KALIT RO'YXATI ATAYLAB QULFLANMAGAN va bu YAGONA joyda shunday. Sabab: §11 maydonlari
#: platformaning QOBILIYATIGA bog'liq (eski relizda funksiya umuman yo'q) va arxitektor
#: shaklda `platform: {…}` deb yozgan — ya'ni kalit to'plami shartnoma EMAS. Buning o'rniga
#: KALIT SHAKLI va QIYMAT TURI qulflanadi, sanoq/boolean darvozasi (`sanoqlar_matn`) va sir
#: skani esa bu bo'limga ham TO'LIQ qo'llanadi.
PLATFORM_KEY_RE = re.compile(r"[a-z][a-z0-9_]*")

#: ⚠️ MANIFESTDA BO'LISHI TAQIQLANGAN maydonlar — nom bo'yicha, ANIQ. Kalit oq ro'yxati
#: ularni allaqachon to'sadi, lekin «noma'lum kalit» degan xato SABABINI aytmaydi: bu maydonlar
#: MANBA provenansi da'volari va ular metadata razvedkasidan kelib chiqmaydi.
FORBIDDEN_MANIFEST_KEYS: tuple[str, ...] = ("plan_sha256", "snapshot_at", "source_copy")

#: SHA-256 ning shakli: AYNAN 64 ta KICHIK harfli hex.
SHA256_RE = re.compile(r"[0-9a-f]{64}")

#: Xato KODI: barqaror, mashina o'qiydigan belgi (`CATALOG_UNREADABLE`). ⚠️ Erkin matn kod
#: bo'lib ishlatilmasin — kod bo'yicha filtr yozadigan operator har gal boshqa jumlani
#: ko'rardi; sabab `detail` da yoziladi.
ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")

#: `VERIFIED` SO'ZI (bo'lak emas).
#: ⚠️ NEGA SO'Z CHEGARASI SHART: yig'uvchining versiyasi ataylab `0.1.0-UNVERIFIED` deb
#: yoziladi (u hech qachon haqiqiy konfiguratsiyada tasdiqlanmagan), ya'ni oddiy bo'lak
#: qidiruvi HAR BIR halol paketni rad etib, darvozani o'chirishga olib kelardi.
VERIFIED_WORD_RE = re.compile(r"(?<![0-9A-Za-z_])VERIFIED(?![0-9A-Za-z_])")

#: `confidence` NOMLI kalit — yig'uvchi ishonch darajasini BERMAYDI.
#: ⚠️ NAQSH ATAYLAB KENG (`search`, `fullmatch` EMAS): `confidence_score`, `field_confidence`
#: va shu kabi shakllar AYNI da'voni tashiydi, ya'ni faqat aynan `confidence` nomini to'sish
#: darvozani nom o'zgartirish bilan aylanib o'tish yo'lini qoldirardi. Yolg'on ijobiy xavfi
#: YO'Q: shu paketning HAMMA hujjati kalit OQ RO'YXATI bilan tekshiriladi va birorta qonuniy
#: kalitda bu bo'lak uchramaydi.
CONFIDENCE_KEY_RE = re.compile(r"(?i)confidence")


class RuntimeBundleError(DiscoveryError):
    """Runtime paketi shakli buzuq. `DiscoveryError` dan meros: paketni o'qiydigan kod bitta
    `except` bilan to'plam, inventarizatsiya va runtime paketini qamrab oladi."""


# ── Kichik yordamchilar (qolgan modullardagi bilan bir xil shakl, boshqa xato turi) ────────
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeBundleError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = set(obj) - allowed
    _need(not extra, f"{where}: noma'lum kalit(lar) {sorted(extra)} — shartnomada yo'q")
    missing = allowed - set(obj)
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {sorted(missing)}")


def _text_or_none(v, where: str):
    _need(v is None or isinstance(v, str), f"{where} matn yoki null bo'lishi kerak")
    if isinstance(v, str):
        _need(v.strip(), f"{where} bo'sh matn bo'lmasligi kerak — javob yo'q bo'lsa `null` yozing")
    return v


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _count_text(v, where: str) -> str:
    """Sanoq — ASCII raqamli MATN. JSON soni ATAYLAB RAD etiladi."""
    if isinstance(v, (bool, int, float)):
        _need(False, f"{where} JSON SONI bo'lmasligi kerak — MATN yozing "
                     f"(0000123 soni 123 bo'lib qoladi, boshidagi nollar yo'qoladi): {v!r}")
    _need(isinstance(v, str) and COUNT_TEXT_RE.fullmatch(v),
          f"{where} ASCII raqamli MATN bo'lishi kerak (JSON soni TAQIQLANGAN) — kelgani {v!r}")
    return v


def _str_list(v, where: str) -> list[str]:
    _need(isinstance(v, list) and all(isinstance(x, str) for x in v),
          f"{where} matnlar ro'yxati bo'lishi kerak")
    return v


def _dupes(items) -> list[str]:
    seen: dict = {}
    for x in items:
        seen[x] = seen.get(x, 0) + 1
    return sorted(k for k, n in seen.items() if n > 1)


def _ts(v, where: str):
    try:
        return parse_ts(v, where)
    except BundleError as e:
        raise RuntimeBundleError(str(e)) from e


#: Nom ichidagi ajratuvchilar — `_xavfsiz` ularni probelga almashtirib QAYTA skanerlaydi.
#: ⚠️ Nuqta ham bor: `pwd=hunter2.json` da kengaytma sirga yelimlangan.
#: ⚠️ IKKI VARIANT ATAYLAB: birinchisi NUQTANI SAQLAYDI, ikkinchisi uni ham almashtiradi.
#:    Nuqtani almashtirish IP ni BO'LIB TASHLAYDI (`10.8.0.5:1541` -> `10 8 0 5:1541`)
#:    va `ip_with_port` naqshi ishlamay qoladi; nuqtani saqlash esa kengaytmaga
#:    yelimlangan sirni (`pwd=hunter2.json`) ba'zi naqshlardan yashiradi. Shu bois
#:    IKKISI ham sinaladi va BIRORTASIDA sir topilsa qiymat niqoblanadi.
_AJRATUVCHILAR = (re.compile(r"[_/\\-]+"), re.compile(r"[_/\\.\-]+"))


def _xavfsiz(qiymat) -> str:
    """Nuqson matniga QO'SHILADIGAN TASHQI qiymatni sirdan tozalab beradi.

    ⚠️ NEGA HAR JOYDA KERAK: hisobot matni operator ekranidan jurnalga, jurnaldan esa xabar
       almashinuviga ko'chadi. Paketdagi HAR QANDAY matn maydoni 1C ning xato tavsifidan
       kelishi mumkin, SUBD xatosi esa ulanish satrini, server nomini va PAROLNI o'z ichiga
       oladi. Ilgari faqat SKANERLAR qiymatni yashirardi (`redact.Finding.__str__`), qolgan
       tekshiruvlar esa oila nomini, fayl nomini, obyekt manzilini va rejim izohini XOM holda
       nuqson matniga qo'shardi — ya'ni `cli.py` boshidagi «SIR EKRANGA CHIQMAYDI» da'vosi
       YOLG'ON edi.
    ⚠️ QIYMAT TUSHIB QOLMAYDI, NIQOBLANADI: `[REDACTED]` operatorga «bu yerda shubhali
       qiymat bor» deb aytadi, qiymatning o'zini esa aytmaydi. Butunlay olib tashlash
       nuqsonni tushunarsiz qilardi.
    ⚠️ `str()` ATAYLAB: kelgan qiymat matn bo'lmasligi ham mumkin (son, `None`, ro'yxat) va
       `redact` faqat matnni tozalaydi.
    ⚠️ AJRATUVCHI NORMALIZATSIYASI SHART: `redact` naqshlari `\b` anker'iga tayanadi va
       `_` so'z belgisi bo'lgani uchun sir NOM ICHIGA yelimlanganda ko'rinmaydi —
       `redact("10.8.0.5:1541")` niqoblaydi, `redact("99_10.8.0.5:1541")` esa YO'Q.
       Fayl nomlari aynan shunday (`probes/99_pwd=hunter2.json`). Shu bois ajratuvchilar
       probel bilan almashtirilgan NUSXA ham tekshiriladi va sir topilsa BUTUN qiymat
       niqoblanadi: qiymat chegarasi qayerda tugashini bilmaymiz.
       ⚠️ `redact.py` — Phase 2 fayli va bu yerda O'ZGARTIRILMAYDI; tuzatish shu yerda."""
    matn = str(qiymat)
    tozalangan = redaction.redact(matn)
    if tozalangan != matn:
        return tozalangan
    for ajratuvchi in _AJRATUVCHILAR:
        yoyilgan = ajratuvchi.sub(" ", matn)
        if yoyilgan == matn:
            continue
        if redaction.scan({"x": yoyilgan}) or redaction.redact(yoyilgan) != yoyilgan:
            return redaction.MASK
    return matn


def _xavfsiz_royxat(items) -> list[str]:
    """Ro'yxatning HAR a'zosi tozalangan nusxasi — nuqson matnida ro'yxat ko'rsatilganda."""
    return [_xavfsiz(x) for x in items]


# ── Rejim: fail-safe hal qilish ────────────────────────────────────────────────────────────
def resolve_mode(raw) -> tuple[str, str | None]:
    """Berilgan rejim nomidan `(mode, mode_note)`. Noma'lum yoki yo'q rejim — `METADATA_ONLY`.

    ⚠️ FAIL-SAFE VA U ATAYLAB ASIMMETRIK: shubha bo'lganda natija ENG QAT'IY rejim bo'ladi,
       ya'ni aktiv zond ISHLAMAYDI. Teskarisi (noma'lum rejimni `APPROVED_PROBES` deb olish)
       yig'uvchi tomonidagi bitta imlo xatosini mijoz bazasida bajariladigan amalga
       aylantirardi.
    ⚠️ TUSHISH JIMGINA BO'LMAYDI: `mode_note` nima bo'lganini yozib qoladi va u
       `run_status.json` ga tushadi. Jimgina tushish «operator so'ragan rejim ishladi» degan
       yolg'on xotirjamlik bo'lardi.
    ⚠️ Nom AYNAN taqqoslanadi: `"metadata_only"` ham, `" METADATA_ONLY"` ham noma'lum deb
       hisoblanadi va tushiriladi. «Tuzatib qabul qilish» operator yozganini jimgina
       o'zgartirish bo'lardi."""
    if raw in MODES:
        return (raw, None)
    if raw is None:
        return (DEFAULT_MODE, f"rejim berilmadi — fail-safe {DEFAULT_MODE} qo'llanildi")
    return (DEFAULT_MODE,
            f"noma'lum rejim {raw!r} — fail-safe {DEFAULT_MODE} qo'llanildi "
            f"(ruxsat etilgani: {', '.join(MODES)})")


def derive_overall(sections: list[dict], *, families, artifacts) -> str:
    """Umumiy holatning YAGONA TA'RIFI — yig'uvchi ham AYNAN shu qoida bilan hisoblaydi.

    `SUCCESS` ⇔ HAMMA majburiy artefakt yozilgan **VA** birorta bo'lim `failed` emas **VA**
    birorta oila `unreadable` emas.
    Yozish yiqilsa (majburiy artefakt yo'q) -> `FAILED`. Aks holda -> `PARTIAL`.

    ⚠️ `skipped` BO'LIM VA `absent` OILA `SUCCESS` NI BUZMAYDI va bu tuzatishning O'ZAGI.
       Ilgari bu funksiya `SUCCESS` uchun HAMMA bo'lim `ok` bo'lishini talab qilardi,
       yig'uvchi esa `METADATA_ONLY` da HAR DOIM `probes` bo'limini `skipped` deb yozadi —
       ya'ni HAR BIR halol default yurishda ikki tomon ZID javob berardi: yig'uvchi
       `SUCCESS` yozardi, validator `PARTIAL` hisoblardi va paketni rad etardi. `skipped`
       — «bu ish ATAYLAB qilinmadi» degan JAVOB, yiqilish emas; `absent` ham JAVOB
       («bu konfiguratsiyada bunday oila yo'q»).
    ⚠️ `FAILED` FAQAT YOZISH yiqilganda: paketning O'ZI to'liq bo'lmasa, uning ichidagi
       hukmlarni o'qishdan foyda yo'q. Yiqilgan bo'limlar soni esa — har biri sababi bilan
       qayd etilgan bo'lsa — paketni yaroqsiz qilmaydi, TO'LIQSIZ qiladi (`PARTIAL`).
    ⚠️ MAJBURIY ARTEFAKTLAR OLTOVI (`REQUIRED_FILES`), `errors.json` HAM. Uning yozilishini
       hisobga olmaslik yolg'on `SUCCESS` berardi: xatolar ro'yxati yozilmagan yurish
       «hech qanday xato bo'lmadi» bilan bir xil ko'rinardi.

    ⚠️ NEGA HISOBLANADI, NEGA ISHONILMAYDI: e'lon qilingan holat paketga mos kelmasa, bu
       yoki yig'uvchining nuqsoni, yoki paketni keyin qo'lda «tuzatish» — ikkisi ham paketni
       ishonchsiz qiladi. Shu bois `run_status.overall` HAR DOIM hisoblangani bilan
       solishtiriladi (`overall_ziddiyatsiz` tekshiruvi)."""
    _need(bool(sections), "run_status.sections bo'sh bo'lmasligi kerak")
    yozilgan = set(artifacts)
    if [n for n in REQUIRED_FILES if n not in yozilgan]:
        return OVERALL_FAILED
    yiqilgan = any(s.get("status") == "failed" for s in sections)
    oqilmagan = any(f.get("state") == "unreadable" for f in families)
    return OVERALL_PARTIAL if (yiqilgan or oqilmagan) else OVERALL_SUCCESS


# ── `run_status.json` validatori ───────────────────────────────────────────────────────────
def validate_run_status(doc) -> None:
    """`binos-1c-run-v1` ni QAT'IY tekshiradi. Xato — `RuntimeBundleError`."""
    _keys(doc, RUN_KEYS, "run_status")
    _need(doc["run_version"] == RUN_VERSION,
          f"run_status.run_version {RUN_VERSION!r} bo'lishi kerak, kelgani {doc['run_version']!r}")

    _need(doc["mode"] in MODES,
          f"run_status.mode {list(MODES)} dan biri bo'lishi kerak, kelgani {doc['mode']!r}")
    # ⚠️ `mode_note` HAR IKKI REJIMDA to'ldirilishi MUMKIN: u «rejim QANDAY hal bo'ldi»
    #    degan savolga javob beradi (fail-safe tushish, operator tasdig'i, argument manbasi).
    #    Ilgari bu yerda `APPROVED_PROBES` uchun `null` TALAB qilinardi — yig'uvchi esa
    #    izohni har yurishda yozadi, ya'ni talab har bir halol aktiv zond yurishini rad
    #    etardi. Izohning MAZMUNI tekshirilmaydi (u erkin matn), lekin sir skani undan ham
    #    o'tadi va hisobotga chiqqanda `redact` dan o'tadi.
    _text_or_none(doc["mode_note"], "run_status.mode_note")

    _keys(doc["collector"], COLLECTOR_KEYS, "run_status.collector")
    for k in sorted(COLLECTOR_KEYS):
        _nonempty(doc["collector"][k], f"run_status.collector.{k}")

    boshlandi = _ts(doc["started_at"], "run_status.started_at")
    tugadi = _ts(doc["finished_at"], "run_status.finished_at")
    _need(tugadi >= boshlandi,
          "run_status.finished_at `started_at` dan oldin bo'lolmaydi")

    _need(doc["overall"] in OVERALLS,
          f"run_status.overall {list(OVERALLS)} dan biri bo'lishi kerak, "
          f"kelgani {doc['overall']!r}")
    # ⚠️ E'LON QILINGAN `overall` SHU YERDA HISOBLANGANI BILAN SOLISHTIRILMAYDI, va bu
    #    ATAYLAB: yagona ta'rif bo'limlardan TASHQARI oilalarga va yozilgan artefaktlarga ham
    #    tayanadi, ya'ni bu hukm CROSS-DOCUMENT. U bitta joyda — `overall_ziddiyatsiz`
    #    tekshiruvida — chiqariladi, shunda operator BIR sabab ko'radi, ikki xil so'z bilan
    #    aytilgan bir xil nuqsonni emas.

    # ── Platforma (§11) ───────────────────────────────────────────────────────────────────
    plat = doc["platform"]
    _need(isinstance(plat, dict) and plat,
          "run_status.platform bo'sh bo'lmagan obyekt bo'lishi kerak — §11 maydonlari "
          "topilmasa ham kalit `null` qiymat bilan TURADI («qaramadim» va «yo'q» bir xil emas)")
    for k in sorted(plat):
        _need(isinstance(k, str) and PLATFORM_KEY_RE.fullmatch(k),
              f"run_status.platform: kalit kichik harfli identifikator bo'lishi kerak, "
              f"kelgani {k!r}")
        # ⚠️ TEKIS shakl: qiymat MATN yoki `null`. Ichma-ich obyekt qo'shilsa u JIMGINA
        #    o'tib ketmasligi kerak — §11 maydonlari xom qiymatlar, tuzilma emas.
        _text_or_none(plat[k], f"run_status.platform.{k}")

    # ── Bo'limlar: yiqilgani JIMGINA tushib qolmaydi ───────────────────────────────────────
    secs = doc["sections"]
    _need(isinstance(secs, list) and secs,
          "run_status.sections bo'sh bo'lmagan ro'yxat bo'lishi kerak — yig'uvchi NIMANI "
          "urinib ko'rganini aytishi SHART (bo'sh ro'yxat «hech narsa qaralmadi» degani)")
    for i, sec in enumerate(secs):
        w = f"run_status.sections[{i}]"
        _keys(sec, RUN_SECTION_KEYS, w)
        _nonempty(sec["name"], f"{w}.name")
        # ⚠️ BO'LIM LUG'ATI `bundle.SECTION_STATUSES` bilan AYNI: `ok|failed|skipped`.
        #    `absent` va `unreadable` bu yerda BO'LMAYDI — ular FAQAT `families[].state` da
        #    yashaydi. Bir so'zning ikki lug'atda turishi ikki tomonni zid qilib qo'yardi va
        #    «o'qilmadi» bo'lim jurnalidan oila jurnaliga ko'chib, ajrim yo'qolardi.
        _need(sec["status"] in SECTION_STATUSES,
              f"{w}.status noma'lum: {sec['status']!r} — {list(SECTION_STATUSES)} dan biri. "
              f"⚠️ `absent`/`unreadable` bo'lim holati EMAS, ular FAQAT `families[].state` da")
        _text_or_none(sec["error"], f"{w}.error")
        _need(sec["status"] == "ok" or sec["error"] is not None,
              f"{w}: `{sec['status']}` bo'lgan bo'lim sababsiz qolmaydi — `error` ni to'ldiring")
        _need(sec["status"] != "ok" or sec["error"] is None,
              f"{w}: `ok` bo'limda `error` bo'lmasligi kerak")
    dupes = _dupes(s["name"] for s in secs)
    _need(not dupes, f"run_status.sections: bo'lim nomi takrorlangan {dupes}")

    # ── Oilalar ───────────────────────────────────────────────────────────────────────────
    fams = doc["families"]
    _need(isinstance(fams, list) and fams,
          "run_status.families bo'sh bo'lmagan ro'yxat bo'lishi kerak — qaysi oilalarga "
          "qaralgani aytilmasa, `absent` javobining ma'nosi yo'q")
    for i, fam in enumerate(fams):
        w = f"run_status.families[{i}]"
        _keys(fam, FAMILY_KEYS, w)
        _nonempty(fam["name"], f"{w}.name")
        _need(fam["state"] in FAMILY_STATES,
              f"{w}.state {list(FAMILY_STATES)} dan biri bo'lishi kerak, kelgani "
              f"{fam['state']!r}. ⚠️ `absent` = «bu konfiguratsiyada yo'q» (JAVOB), "
              f"`unreadable` = «o'qiy olmadim» (javob YO'Q) — ikkisi bir xil emas")
        _text_or_none(fam["detail"], f"{w}.detail")
        _need(fam["state"] != "unreadable" or fam["detail"] is not None,
              f"{w}: `unreadable` oila sababsiz qolmaydi — `detail` ni to'ldiring "
              f"(sababsiz «o'qiy olmadim» tekshirib bo'lmaydigan da'vo)")
    dupes = _dupes(f["name"] for f in fams)
    _need(not dupes, f"run_status.families: oila nomi takrorlangan {dupes}")

    # ── Bajarilgan zondlar jurnali ────────────────────────────────────────────────────────
    probes = doc["probes"]
    _need(isinstance(probes, list), "run_status.probes ro'yxat bo'lishi kerak")
    for i, pr in enumerate(probes):
        w = f"run_status.probes[{i}]"
        _keys(pr, PROBE_LOG_KEYS, w)
        _count_text(pr["no"], f"{w}.no")
        # ⚠️ IKKI RAQAM: `no` — bajarilish O'RNI va u zond FAYLINING nomida ham turadi
        #    (`probes/NN_<tur>.json`), ya'ni ikkisi bir-biriga bog'langan.
        _need(len(pr["no"]) == 2,
              f"{w}.no AYNAN ikki raqamli MATN bo'lishi kerak (`01`), kelgani {pr['no']!r}")
        _need(pr["probe_type"] in PROBE_CATALOG,
              f"{w}.probe_type katalogda yo'q: {pr['probe_type']!r}. Bajariladigan amallar "
              f"ro'yxati QO'LDA yozilgan ({', '.join(sorted(PROBE_CATALOG))}) — "
              f"o'zboshimcha kod YO'Q")
        _nonempty(pr["target_object"], f"{w}.target_object")
        try:
            assert_no_raw_code(pr["target_object"], where=f"{w}.target_object", address=True)
        except ProbeError as e:
            raise RuntimeBundleError(str(e)) from e
        _nonempty(pr["reason"], f"{w}.reason")
        _nonempty(pr["file"], f"{w}.file")
        m = PROBE_NAME_RE.fullmatch(pr["file"])
        _need(m is not None,
              f"{w}.file shartnomaga mos emas: {pr['file']!r} — "
              f"{', '.join(OPTIONAL_FILES)} shaklida bo'lishi kerak")
        # ⚠️ JURNAL VA FAYL NOMI BIR-BIRINI TASDIQLAYDI: `ls` qiladigan operator va JSON
        #    o'qiydigan kod bir xil narsani ko'rishi SHART.
        _need(m.group("seq") == pr["no"] and m.group("tur") == pr["probe_type"],
              f"{w}: jurnal fayl nomiga mos emas — jurnalda "
              f"no={pr['no']!r}/probe_type={pr['probe_type']!r}, fayl nomida "
              f"no={m.group('seq')!r}/tur={m.group('tur')!r}")
        # ⚠️ AYNI LUG'AT (`bundle.SECTION_STATUSES`): zond bajarildi (`ok`), yiqildi
        #    (`failed`) yoki ataylab bajarilmadi (`skipped`). Ikkinchi lug'at yasash ikki
        #    tomonni yana bir marta ajratardi.
        _need(pr["status"] in SECTION_STATUSES,
              f"{w}.status noma'lum: {pr['status']!r} — {list(SECTION_STATUSES)} dan biri")
    dupes = _dupes(p["no"] for p in probes)
    _need(not dupes, f"run_status.probes: bajarilish o'rni takrorlangan {dupes} — `no` "
                     f"bajarilish O'RNI va ikki zond bir o'rinda tura olmaydi")
    dupes = _dupes(p["file"] for p in probes)
    _need(not dupes, f"run_status.probes: zond fayli takrorlangan {dupes}")

    # ⚠️ REJIM DARVOZASI HUJJAT ICHIDA HAM: `METADATA_ONLY` da aktiv zond BO'LMAYDI.
    _need(doc["mode"] != MODE_METADATA_ONLY or not probes,
          f"run_status: {MODE_METADATA_ONLY} rejimida `probes` jurnali BO'SH bo'lishi SHART — "
          f"qayd etilgan zond(lar): {sorted(p['file'] for p in probes)}")
    _need(doc["mode"] != MODE_APPROVED_PROBES or probes,
          f"run_status: {MODE_APPROVED_PROBES} rejimida `probes` jurnali bo'sh bo'lolmaydi — "
          f"hech qanday zond bajarilmagan bo'lsa rejim {MODE_METADATA_ONLY} deb yozilishi kerak")

    # ── Artefakt da'vosi ──────────────────────────────────────────────────────────────────
    arts = _str_list(doc["artifacts"], "run_status.artifacts")
    _need(arts, "run_status.artifacts bo'sh bo'lmasligi kerak")
    for i, name in enumerate(arts):
        w = f"run_status.artifacts[{i}]"
        _nonempty(name, w)
        _need(name in REQUIRED_FILES or PROBE_NAME_RE.fullmatch(name),
              f"{w}: shartnomada bunday artefakt yo'q: {name!r}. Ruxsat etilgani: "
              f"{', '.join(REQUIRED_FILES)} va {', '.join(OPTIONAL_FILES)}")
    dupes = _dupes(arts)
    _need(not dupes, f"run_status.artifacts: fayl nomi takrorlangan {dupes}")

    # ── Xato sanog'i va izohlar ───────────────────────────────────────────────────────────
    # ⚠️ SANOQ MATN (`_count_text`): `0000` soni `0` bo'lib qolardi.
    # ⚠️ `errors.json` DAGI QATORLAR SONI BILAN TENGLIK TALAB QILINMAYDI va sababi ochiq:
    #    `errors.json` yozish navbatida BIRINCHI bo'lib muhrlanadi, keyingi yozish xatosi
    #    (`WRITE_FAILED`) esa undan KEYIN qayd etiladi — ya'ni qat'iy tenglik halol paketni
    #    rad etardi. Sanoq shu bois «e'lon», tekshiruv esa `errors.json` ning O'ZIDA.
    _count_text(doc["error_count"], "run_status.error_count")
    for i, note in enumerate(_str_list(doc["notes"], "run_status.notes")):
        _nonempty(note, f"run_status.notes[{i}]")


# ── `errors.json` validatori ───────────────────────────────────────────────────────────────
def validate_errors(doc) -> None:
    """`binos-1c-errors-v1` ni QAT'IY tekshiradi. BO'SH `errors[]` — QONUNIY javob."""
    _keys(doc, ERRORS_DOC_KEYS, "errors")
    _need(doc["errors_version"] == ERRORS_VERSION,
          f"errors.errors_version {ERRORS_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['errors_version']!r}")
    # ⚠️ `collected_at` `null` bo'lishi MUMKIN: eski platformada vaqt olish yiqilsa, YOLG'ON
    #    vaqt yozilmasligi kerak. Vaqt bor bo'lsa — shakli QAT'IY tekshiriladi.
    if _text_or_none(doc["collected_at"], "errors.collected_at") is not None:
        _ts(doc["collected_at"], "errors.collected_at")
    for i, note in enumerate(_str_list(doc["notes"], "errors.notes")):
        _nonempty(note, f"errors.notes[{i}]")
    rows = doc["errors"]
    _need(isinstance(rows, list), "errors.errors ro'yxat bo'lishi kerak")

    for i, e in enumerate(rows):
        w = f"errors.errors[{i}]"
        _keys(e, ERROR_KEYS, w)
        _need(e["scope"] in ERROR_SCOPES,
              f"{w}.scope {list(ERROR_SCOPES)} dan biri bo'lishi kerak, kelgani {e['scope']!r}")
        _text_or_none(e["family"], f"{w}.family")
        _text_or_none(e["object"], f"{w}.object")
        _nonempty(e["code"], f"{w}.code")
        _need(ERROR_CODE_RE.fullmatch(e["code"]),
              f"{w}.code BARQAROR kod bo'lishi kerak (bosh harf bilan boshlanadigan "
              f"`A-Z`, `0-9`, `_`), kelgani {e['code']!r}. Sabab: operator kod bo'yicha "
              f"filtr yozadi, erkin jumla esa har gal boshqacha keladi — sabab `detail` da")
        _nonempty(e["detail"], f"{w}.detail")

        # ⚠️ QAMROV SHARTNOMASI: xato QAYERDA yuz berganini `scope` aytadi, va shu bilan
        #    `family`/`object` maydonlari MAJBURIY yoki TAQIQLANGAN bo'lib qoladi. Ixtiyoriy
        #    qoldirilsa, «oila darajasidagi xato» bilan «o'sha oiladagi bitta obyektning
        #    xatosi» hisobotda farqlanmay qolardi.
        if e["scope"] in RUN_LEVEL_SCOPES:
            # ⚠️ `platform`/`write`/`mode` xatosi metadata OILASIGA tegishli EMAS: `family`
            #    `null` bo'lishi SHART, chunki oila nomi `run_status.families` bilan
            #    solishtiriladi va «platforma» degan oila mavjud emas. `object` esa
            #    IXTIYORIY: platforma maydonining nomi yoki yozilmagan faylning nomi shu
            #    yerda qoladi — uni tashlab yuborish xatoni MANZILSIZ qoldirardi.
            _need(e["family"] is None,
                  f"{w}: `{e['scope']}` darajasidagi xato metadata oilasiga tegishli EMAS — "
                  f"`family` `null` bo'lishi kerak")
        elif e["scope"] == "family":
            _need(e["family"] is not None,
                  f"{w}: `family` darajasidagi xatoda `family` ko'rsatilishi SHART")
            _need(e["object"] is None,
                  f"{w}: `family` darajasidagi xatoda `object` `null` bo'lishi kerak — "
                  f"obyekt ko'rsatilsa scope `object` bo'ladi")
        elif e["scope"] == "object":
            _need(e["family"] is not None and e["object"] is not None,
                  f"{w}: `object` darajasidagi xatoda `family` ham, `object` ham SHART")
        else:  # probe
            _need(e["object"] is not None,
                  f"{w}: `probe` darajasidagi xatoda zond NISHONI `object` da ko'rsatiladi")


# ── `manifest.json` validatori ─────────────────────────────────────────────────────────────
def validate_manifest(doc) -> None:
    """`binos-1c-manifest-v1` ni QAT'IY tekshiradi.

    ⚠️ MANIFEST PROVENANS DA'VOSI EMAS — modul docstringiga qarang. Uchta maydondan boshqasi
       yo'q va `FORBIDDEN_MANIFEST_KEYS` buni SABABI bilan aytadi."""
    _need(isinstance(doc, dict), "manifest obyekt bo'lishi kerak")
    taqiq = sorted(k for k in FORBIDDEN_MANIFEST_KEYS if k in doc)
    _need(not taqiq,
          f"manifest: MANBA provenansi maydon(lar)i {taqiq} — manifest faqat YOZILGAN "
          f"BAYTLARNI tasdiqlaydi. Bu da'volar metadata razvedkasidan kelib chiqmaydi va "
          f"mustaqil tasdiqlanishi shart (Phase 2 qoidasi ularni ATAYLAB taqiqlagan)")
    _keys(doc, MANIFEST_DOC_KEYS, "manifest")
    _need(doc["manifest_version"] == MANIFEST_VERSION,
          f"manifest.manifest_version {MANIFEST_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['manifest_version']!r}")
    for i, note in enumerate(_str_list(doc["notes"], "manifest.notes")):
        _nonempty(note, f"manifest.notes[{i}]")

    rows = doc["files"]
    _need(isinstance(rows, list) and rows,
          "manifest.files bo'sh bo'lmagan ro'yxat bo'lishi kerak")
    for i, f in enumerate(rows):
        w = f"manifest.files[{i}]"
        taqiq = sorted(k for k in FORBIDDEN_MANIFEST_KEYS if k in (f if isinstance(f, dict) else {}))
        _need(not taqiq, f"{w}: MANBA provenansi maydon(lar)i {taqiq} — manifestda faqat "
                         f"fayl nomi, bayt hajmi va sha256 bo'ladi")
        _keys(f, MANIFEST_FILE_KEYS, w)
        _nonempty(f["name"], f"{w}.name")
        _need(f["name"] in REQUIRED_FILES or PROBE_NAME_RE.fullmatch(f["name"]),
              f"{w}.name shartnomada yo'q: {f['name']!r}")
        # ⚠️ MANIFEST O'ZINI XESHLAMAYDI: o'z xeshini o'z ichiga yozish aylanma bo'lardi
        #    (yozish xeshni o'zgartiradi). Shu bois o'z nomi ro'yxatda TURMASLIGI kerak.
        _need(f["name"] != MANIFEST_FILE,
              f"{w}.name: manifest O'ZINI xeshlay olmaydi (xeshni yozish xeshni "
              f"o'zgartiradi) — {MANIFEST_FILE!r} ro'yxatda turmaydi")
        _count_text(f["bytes"], f"{w}.bytes")
        if f["sha256"] is not None:
            _need(isinstance(f["sha256"], str) and SHA256_RE.fullmatch(f["sha256"]),
                  f"{w}.sha256 AYNAN 64 ta KICHIK harfli hex yoki `null` bo'lishi kerak, "
                  f"kelgani {f['sha256']!r}")
    dupes = _dupes(f["name"] for f in rows)
    _need(not dupes, f"manifest.files: fayl nomi takrorlangan {dupes}")


# ── Zond natijasi validatori ───────────────────────────────────────────────────────────────
def validate_probe_result(doc, *, where: str, expected_type: str) -> None:
    """`binos-1c-probe-v1` natijasini tekshiradi.

    ⚠️ `result` SHAKLI TEKSHIRILMAYDI va bu OCHIQ aytiladi: BSL tomonidagi izoh ham
       «natija shakli hali SHARTNOMA EMAS» deb turadi. Shakl tekshirilmagani uchun uning
       ichidagi HAMMA narsa qolgan darvozalardan o'tadi: JSON soni yo'qligi, sir yo'qligi,
       `VERIFIED` yo'qligi. Ya'ni shakl erkin, mazmun esa erkin EMAS.
    ⚠️ `read_only` — AYNAN `"true"` MATNI. `true` booleani ham, `"false"` ham RAD: yozuvchi
       zond bu qatlamning butun ma'nosini yo'qotardi, `Булево` esa JSON'da uchinchi holatni
       (`"unknown"`) yo'q qilib qo'yardi."""
    _keys(doc, PROBE_RESULT_KEYS, where)
    _need(doc["probe_version"] == PROBE_VERSION,
          f"{where}.probe_version {PROBE_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['probe_version']!r}")
    _need(doc["probe_type"] in PROBE_CATALOG,
          f"{where}.probe_type katalogda yo'q: {doc['probe_type']!r}")
    _need(doc["probe_type"] == expected_type,
          f"{where}.probe_type fayl nomiga mos emas: faylda {expected_type!r}, "
          f"ichida {doc['probe_type']!r} — `ls` qiladigan operator va JSON o'qiydigan kod "
          f"bir xil narsani ko'rishi SHART")
    _nonempty(doc["target_object"], f"{where}.target_object")
    try:
        assert_no_raw_code(doc["target_object"], where=f"{where}.target_object", address=True)
    except ProbeError as e:
        raise RuntimeBundleError(str(e)) from e
    _need(doc["read_only"] == "true",
          f"{where}.read_only AYNAN `\"true\"` MATNI bo'lishi kerak, kelgani "
          f"{doc['read_only']!r} — yozuvchi zond mavjud emas va bo'lishi ham mumkin emas")
    # ⚠️ ZOND FAQAT `APPROVED_PROBES` DA BAJARILADI, shu bois natijadagi `mode` ham AYNAN
    #    shu bo'ladi. Natija paketdan ajratib olinib uzatilsa, «bu qaysi rejimda bajarildi»
    #    degan savol javobsiz qolmasligi kerak — `METADATA_ONLY` deb yozilgan zond natijasi
    #    esa o'z-o'ziga zid hujjat.
    _need(doc["mode"] == MODE_APPROVED_PROBES,
          f"{where}.mode AYNAN {MODE_APPROVED_PROBES!r} bo'lishi kerak, kelgani "
          f"{doc['mode']!r} — aktiv zond boshqa rejimda bajarilmaydi")
    _str_list(doc["errors"], f"{where}.errors")


# ══════════════════════════════════════════════════════════════════════════════════════════
# HISOBOT
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Check:
    """Bitta tekshiruv: nomi, natijasi va SABABI.

    ⚠️ `detail` muvaffaqiyatda ham to'ldiriladi: «OK» so'zining o'zi operatorga NIMA
       tekshirilganini aytmaydi, va keyingi safar nimani solishtirishni ham."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Report:
    """Validatorning STRUKTURALI javobi. Deterministik: `checks` tartibi `CHECK_NAMES` bilan
    QULFLANGAN, `problems` esa AYNI tartibda yiqilgan tekshiruvlarni takrorlaydi.

    ⚠️ `problems` TARTIBLANMAYDI, TEKSHIRUV TARTIBIDA qoladi. Alfavit bo'yicha tartiblash
       nuqsonni uni topgan tekshiruvdan ajratardi: birinchi yiqilgan tekshiruv odatda
       qolganlarining SABABI (masalan fayl yo'q bo'lsa parse ham bo'lmaydi), va operator
       ro'yxatning boshidan o'qishi kerak.
    ⚠️ `ok` har doim `checks` dan HISOBLANADI (`_build`), alohida e'lon qilinmaydi.
    ⚠️ `ok` VA `overall` IKKI XIL SAVOL: `ok` — «paketga ishonib bo'ladimi?» (fayllar butun,
       sxema mos, sir yo'q), `overall` — «yurishning O'ZI to'liq tugadimi?». Ikkisini bitta
       bayroqqa qo'shib yuborish `PARTIAL` yurishni «hammasi joyida» deb ko'rsatardi, chiqish
       kodi esa `0` bo'lib, runbook bo'yicha paket keyingi bosqichga (AI analitik) o'tib
       ketardi. `overall` paketning O'Z e'loni, ammo u `overall_ziddiyatsiz` tekshiruvidan
       o'tgan: `ok=True` bo'lganda u HISOBLANGAN holatga mos."""

    ok: bool
    checks: tuple[Check, ...]
    problems: tuple[str, ...]
    #: Paket e'lon qilgan yurish holati; yurish yozuvi o'qilmasa `None` («NOMA'LUM»).
    overall: str | None = None

    def to_json(self) -> dict:
        """Mashina o'qiydigan shakl.

        ⚠️ PAPKA YO'LI ATAYLAB YO'Q: yo'l qo'shilsa AYNI paketning ikki nusxasi ikki xil
           bayt berardi va `--json` chiqishi deterministik bo'lmay qolardi. Operator qaysi
           papkani berganini o'zi biladi; odam o'qiydigan hisobotda yo'l ko'rsatiladi."""
        return {
            "report_version": REPORT_VERSION,
            "ok": self.ok,
            "overall": self.overall,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "problems": list(self.problems),
        }


#: TEKSHIRUVLAR — nomi va TARTIBI SHARTNOMA. Tartib bajarilish tartibi ham: keyingi tekshiruv
#: oldingisining natijasiga tayanadi, shu bois yiqilganda «bajarilmadi» deb belgilanadi.
#: ⚠️ Ro'yxatga qo'shish — shartnoma o'zgarishi: operator skripti nom bo'yicha filtr yozadi.
CHECK_NAMES: tuple[str, ...] = (
    "majburiy_fayllar",
    "json_parse",
    "sanoqlar_matn",
    "sxema_va_versiya",
    "obyekt_noyobligi",
    "havola_butunligi",
    "yiguvchidan_verified_yoq",
    "bsl_dan_confidence_yoq",
    "maxfiylik_skani",
    "taqiqlangan_sir_naqshlari",
    "xesh_manifest_mosligi",
    "artefakt_dalvosi",
    "unknown_toliqligi",
    "graf_qurilishi",
    "ai_kirishiga_tayyor",
    "rejim_darvozasi",
    "overall_ziddiyatsiz",
)

#: Bajarilmagan tekshiruvning detali. ⚠️ FAIL-CLOSED: u `ok=False` bo'lib qoladi.
NOT_RUN = ("bajarilmadi — kirishi yo'q (oldingi tekshiruv yiqildi). FAIL-CLOSED: "
           "«tekshirib ko'rmadim» «muammo yo'q» EMAS")


class _Checks:
    """Tekshiruv natijalarini yig'adi. Yozilmagan tekshiruv — `NOT_RUN` va `ok=False`."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[bool, str]] = {}

    def ok(self, name: str, detail: str) -> None:
        self._set(name, True, detail)

    def bad(self, name: str, detail: str) -> None:
        self._set(name, False, detail)

    def _set(self, name: str, ok: bool, detail: str) -> None:
        assert name in CHECK_NAMES, name          # ichki invariant, kirishga bog'liq emas
        # ⚠️ BIRINCHI YOZUV QOLADI: bir tekshiruv ikki sababdan yiqilsa, birinchisi
        #    ko'rsatiladi. Keyingi «ok» eskisini YUVIB TASHLAMASLIGI kerak.
        self._rows.setdefault(name, (ok, detail))

    def done(self, name: str) -> bool:
        return name in self._rows

    def build(self, *, overall: str | None = None) -> Report:
        """⚠️ `overall` BERILMASA `None`: paketning yurish holatini O'QIB BO'LMAGANI
        «muvaffaqiyatli» degani emas (fail-closed — `cli.main` uni `SUCCESS` deb qabul
        qilmaydi)."""
        checks = tuple(
            Check(name, *self._rows.get(name, (False, NOT_RUN))) for name in CHECK_NAMES)
        problems = tuple(f"{c.name}: {c.detail}" for c in checks if not c.ok)
        return Report(ok=not problems, checks=checks, problems=problems, overall=overall)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YORDAMCHI SKANERLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def _walk(node, path: str):
    """`(yo'l, barg)` juftliklari — `redact._walk` bilan AYNI shakl."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def _walk_keys(node, path: str):
    """`(yo'l, kalit)` juftliklari — faqat lug'at KALITLARI."""
    if isinstance(node, dict):
        for k, v in node.items():
            yo_l = f"{path}.{k}" if path else str(k)
            yield yo_l, k
            yield from _walk_keys(v, yo_l)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_keys(v, f"{path}[{i}]")


def _number_paths(node, path: str) -> list[str]:
    """JSON SONI yoki `true`/`false` turgan yo'llar (tartiblangan, takrorsiz).

    ⚠️ BOOLEAN HAM TAQIQLANGAN: 1C uchulik mantiqi MATN bilan keladi
    (`"true"`/`"false"`/`"unknown"`). JSON booleani uchinchi holatni JIMGINA yo'q qiladi,
    ya'ni «qaralmadi» «yo'q» bo'lib qoladi — bu razvedkada eng qimmat yo'qotish."""
    out: list[str] = []
    for yo_l, qiymat in _walk(node, path):
        if isinstance(qiymat, (bool, int, float)):
            out.append(f"{yo_l} ({qiymat!r})")
    return sorted(set(out))


def _raw_secret_findings(name: str, text: str) -> list[str]:
    """Fayl MATNIDAGI sir naqshlari — `<fayl>:<satr>: <detal> (<naqsh>)`.

    ⚠️ QIYMATNING O'ZI CHIQMAYDI: faqat fayl nomi, satr raqami, naqsh nomi va tavsifi.
       `redact.Finding.__str__` aynan shu qoidaga amal qiladi va shu yer ham undan
       chetlashmaydi — nuqson matni jurnalga tushadi, jurnal esa qo'ldan-qo'lga o'tadi.
    ⚠️ NEGA `redact.scan` USTIGA QO'SHIMCHA PASS. `scan()` PARSE QILINGAN hujjatni kezadi,
       ya'ni (a) JSON buzuq bo'lsa u UMUMAN ishlamaydi va sir hech kim ko'rmasdan o'tib
       ketardi, (b) u qiymatlarni kezadi — sir JSON KALIT NOMIDA yoki qo'shtirnoqdan
       tashqaridagi shovqinda tursa, strukturali kezish uni ko'rmaydi.
    ⚠️ NEGA FAQAT QIYMAT NAQSHLARI (`VALUE_PATTERNS`), `SECRET_KEY_RE` EMAS. Kalit NOMI
       naqshini XOM matnga qo'llash qonuniy metadata nomlarini (`token` so'zi bor registr
       nomi) rad etardi — `redact.py` bunday nomni ATAYLAB o'tkazadi, chunki qiymatsiz nom
       hech kimga kirish bermaydi. Kalit nomlari `maxfiylik_skani` da, strukturali
       ko'rinishda tekshiriladi.
    ⚠️ FAYL NOMI HAM TASHQI QIYMAT: papkadagi nomni operator emas, yig'uvchi (yoki paketni
       qo'lda «tuzatgan» kishi) qo'yadi va uning ichida ulanish satri bo'lishi mumkin. Shu
       bois nom ham `_xavfsiz` dan o'tadi."""
    out: list[str] = []
    xavfsiz_nom = _xavfsiz(name)
    for i, line in enumerate(text.splitlines(), start=1):
        for naqsh, rx, detail in redaction.VALUE_PATTERNS:
            if rx.search(line):
                out.append(f"{xavfsiz_nom}:{i}: {detail} ({naqsh})")
    return sorted(set(out))


def _probe_seq_and_type(name: str) -> tuple[str, str]:
    m = PROBE_NAME_RE.fullmatch(name)
    _need(m is not None, f"{_xavfsiz(name)}: zond fayli nomi shartnomaga mos emas "
                         f"({', '.join(OPTIONAL_FILES)})")
    return (m.group("seq"), m.group("tur"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# ASOSIY VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════════════════
def validate_runtime_bundle(folder: str) -> Report:
    """Runtime paketi papkasini tekshiradi va STRUKTURALI hisobot qaytaradi.

    ⚠️ ISTISNO TASHLAMAYDI: har qanday nuqson `Report.problems` ga tushadi, chunki chaqiruvchi
       (CLI va operator skripti) HAMMA nuqsonni bir yurishda ko'rishi kerak — birinchi
       istisnoda to'xtash qolgan o'nta nuqsonni keyingi yurishga qoldirardi.
    ⚠️ TARMOQ YO'Q, AI PROVAYDERI KERAK EMAS. `ai.analyst_payload` faqat YUKNI quradi va uni
       hech qayerga yubormaydi."""
    try:
        members = _read_folder(folder)
    except RuntimeBundleError as e:
        ck = _Checks()
        ck.bad("majburiy_fayllar", str(e))
        return ck.build()
    return validate_runtime_members(members)


def _read_folder(folder: str) -> dict[str, bytes]:
    """Papkani `nom -> baytlar` ga o'qiydi. Nom har doim `/` bilan (Windows ham)."""
    _need(isinstance(folder, str) and folder.strip(), "papka yo'li bo'sh bo'lmasligi kerak")
    _need(os.path.isdir(folder), f"papka topilmadi yoki papka emas: {folder!r}")
    members: dict[str, bytes] = {}
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            with open(full, "rb") as fh:
                members[rel] = fh.read()
    return members


def validate_runtime_members(members: dict[str, bytes]) -> Report:
    """Fayl tizimiga BOG'LIQ EMAS shakl: `nom -> baytlar`. Testlar va ZIP uchun ham shu."""
    ck = _Checks()

    # ── 1 · MAJBURIY FAYLLAR ──────────────────────────────────────────────────────────────
    texts: dict[str, str] = {}
    muammo: list[str] = []
    nomlar = sorted(members)
    yoq = [n for n in REQUIRED_FILES if n not in members]
    if yoq:
        # ⚠️ Bu nomlar SHARTNOMADAN (`REQUIRED_FILES`), paketdan EMAS — tozalash kerak emas.
        muammo.append(f"majburiy fayl(lar) yo'q: {yoq}")
    # ⚠️ NOTANISH FAYL HAM RAD: shartnomada ta'riflanmagan fayl nima ekani, kim yozgani va
    #    ichida nima borligi MA'LUM EMAS, lekin u paket bilan birga qo'ldan-qo'lga o'tadi.
    notanish = [n for n in nomlar
                if n not in REQUIRED_FILES and not PROBE_NAME_RE.fullmatch(n)]
    if notanish:
        muammo.append(f"shartnomada yo'q fayl(lar): {_xavfsiz_royxat(notanish)} — ruxsat "
                      f"etilgani {list(REQUIRED_FILES)} va {list(OPTIONAL_FILES)}")
    katta = [n for n in nomlar if len(members[n]) > MAX_FILE_BYTES]
    if katta:
        muammo.append(f"fayl juda katta (chegara {MAX_FILE_BYTES} bayt): "
                      f"{_xavfsiz_royxat(katta)}")
    for n in nomlar:
        raw = members[n]
        raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw   # 1C/PowerShell BOM
        try:
            texts[n] = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            muammo.append(f"{_xavfsiz(n)} UTF-8 emas: {_xavfsiz(e)}")
    if RUN_SUMMARY_FILE in texts and not texts[RUN_SUMMARY_FILE].strip():
        muammo.append(f"{RUN_SUMMARY_FILE} bo'sh — operator uchun hisobot SHART")
    if muammo:
        ck.bad("majburiy_fayllar", "; ".join(muammo))
    else:
        ck.ok("majburiy_fayllar",
              f"{len(REQUIRED_FILES)} majburiy fayl bor, "
              f"{len(nomlar) - len(REQUIRED_FILES)} ixtiyoriy fayl, hammasi UTF-8")

    # ── 2 · STRICT JSON PARSE ─────────────────────────────────────────────────────────────
    json_nomlar = [n for n in nomlar if n.endswith(".json")]
    docs: dict[str, object] = {}
    muammo = []
    for n in json_nomlar:
        if n not in texts:
            continue
        try:
            docs[n] = strict_json_loads(texts[n])
        except BundleError as e:
            # ⚠️ XATO MATNI HAM TOZALANADI: qat'iy o'qish xatosi hujjatdagi QIYMATNI
            #    ko'rsatishi mumkin (`takror kalit`, `JSON son`), qiymat esa sir bo'lishi
            #    mumkin. Xato MANBASI (fayl nomi, sabab) saqlanadi.
            muammo.append(f"{_xavfsiz(n)}: {_xavfsiz(e)}")
    if muammo:
        ck.bad("json_parse", "; ".join(sorted(muammo)))
    elif not json_nomlar:
        ck.bad("json_parse", NOT_RUN)
    else:
        ck.ok("json_parse",
              f"{len(docs)} JSON fayl qat'iy o'qildi (takror kalit, JSON soni va "
              f"NaN/Infinity RAD)")

    # ── 3 · SANOQLAR MATN ─────────────────────────────────────────────────────────────────
    # ⚠️ NEGA ALOHIDA TEKSHIRUV: `strict_json_loads` sonni RAD etadi, lekin xato matni faqat
    #    qiymatni aytadi («JSON son taqiqlangan: 12») — QAYSI maydonda ekanini AYTMAYDI.
    #    Shu bois bu yerda fayl YUMSHOQ o'qiladi va sonning YO'LI ko'rsatiladi. Boolean ham
    #    shu yerda tutiladi: `strict_json_loads` uni o'tkazib yuboradi.
    muammo = []
    tekshirilgan = 0
    for n in json_nomlar:
        if n not in texts:
            continue
        try:
            yumshoq = json.loads(texts[n])
        except ValueError:
            continue                          # buzuq JSON — `json_parse` allaqachon aytdi
        tekshirilgan += 1
        yo_llar = _number_paths(yumshoq, "")
        if yo_llar:
            # ⚠️ YO'LDA HUJJATNING KALITLARI TURADI, ya'ni yo'l ham tashqi matn: sir nomli
            #    kalit (`Pwd=...`) yo'lga tushib, nuqson matniga chiqib ketishi mumkin.
            muammo.append(f"{_xavfsiz(n)}: JSON soni yoki `true`/`false`: "
                          f"{_xavfsiz_royxat(yo_llar)}")
    if muammo:
        ck.bad("sanoqlar_matn",
               "; ".join(sorted(muammo))
               + ". Har qanday sanoq MATN bo'ladi (0000123 soni 123 bo'lib qoladi), "
                 "uchulik mantiq ham MATN (`true`/`false`/`unknown`)")
    elif not tekshirilgan:
        ck.bad("sanoqlar_matn", NOT_RUN)
    else:
        ck.ok("sanoqlar_matn",
              f"{tekshirilgan} faylda JSON soni ham, booleani ham yo'q")

    # ── 4 · SXEMA VA VERSIYA ──────────────────────────────────────────────────────────────
    run_doc = docs.get(RUN_STATUS_FILE)
    export_doc = docs.get(EXPORT_FILE)
    metadata_doc = docs.get(METADATA_FILE)
    errors_doc = docs.get(ERRORS_FILE)
    manifest_doc = docs.get(MANIFEST_FILE)
    probe_nomlar = [n for n in nomlar if PROBE_NAME_RE.fullmatch(n)]

    muammo = []
    tasdiqlangan: list[str] = []

    def _sxema(nom: str, doc, fn) -> None:
        """⚠️ SXEMA XATOSINING MATNI TOZALANADI. Sxema validatorlari (shu modul, `metadata.py`,
        `export_adapter.py`) noto'g'ri qiymatni `repr` bilan ko'rsatadi — bu ATAYLAB, aks
        holda operator nimani tuzatishni bilmasdi. Lekin o'sha qiymat 1C xatosidan kelgan
        ulanish satri bo'lishi mumkin, ya'ni nuqson matni sirni ekranga chiqarardi. Tozalash
        SHU YERDA, bitta joyda: Phase 2/3 validatorlari BOSHQA shartnoma va ularga
        tegilmaydi."""
        if doc is None:
            muammo.append(f"{nom}: o'qilmadi (yo'q yoki buzuq JSON)")
            return
        try:
            fn(doc)
        except (RuntimeBundleError, DiscoveryError) as e:
            muammo.append(f"{_xavfsiz(nom)}: {_xavfsiz(e)}")
        else:
            tasdiqlangan.append(nom)

    _sxema(RUN_STATUS_FILE, run_doc, validate_run_status)
    _sxema(ERRORS_FILE, errors_doc, validate_errors)
    _sxema(MANIFEST_FILE, manifest_doc, validate_manifest)
    # ⚠️ Phase 2 / Phase 3 SHAKLLARI O'ZGARMAYDI: bu yerda AYNI validatorlar chaqiriladi,
    #    ularning nusxasi yoki «yumshoq varianti» YO'Q.
    _sxema(EXPORT_FILE, export_doc, validate_export)
    _sxema(METADATA_FILE, metadata_doc, validate_metadata)
    for n in sorted(probe_nomlar):
        doc = docs.get(n)
        if doc is None:
            muammo.append(f"{_xavfsiz(n)}: o'qilmadi (buzuq JSON)")
            continue
        try:
            _seq, tur = _probe_seq_and_type(n)
            validate_probe_result(doc, where=n, expected_type=tur)
        except (RuntimeBundleError, DiscoveryError) as e:
            muammo.append(f"{_xavfsiz(n)}: {_xavfsiz(e)}")
        else:
            tasdiqlangan.append(n)
    seqlar = [_probe_seq_and_type(n)[0] for n in probe_nomlar if PROBE_NAME_RE.fullmatch(n)]
    dupes = _dupes(seqlar)
    if dupes:
        # ⚠️ `NN` — bajarilish TARTIBI, ya'ni ikki zond bir o'rinda tura olmaydi.
        muammo.append(f"zond fayllarida takror tartib raqami {dupes} — `NN` bajarilish "
                      f"o'rni va u noyob bo'lishi SHART")
    if muammo:
        ck.bad("sxema_va_versiya", "; ".join(sorted(muammo)))
    else:
        ck.ok("sxema_va_versiya",
              f"sxema va versiya mos ({EXPORT_VERSION} va {METADATA_VERSION} shakllari "
              f"O'ZGARMAGAN holda tekshirildi): "
              + ", ".join(_xavfsiz_royxat(sorted(tasdiqlangan))))

    # ── 5 · OBYEKT NOYOBLIGI ──────────────────────────────────────────────────────────────
    # ⚠️ `validate_export` `objects` ni FAQAT ro'yxat deb tekshiradi (shakl to'plam ko'prigida
    #    tekshiriladi), shu bois takror `full_name` shu yerda ALOHIDA tutiladi: takror
    #    obyekt — ikki xil javobning bitta manzilda turishi.
    muammo = []
    sanoq = []
    for nom, doc in ((EXPORT_FILE, export_doc), (METADATA_FILE, metadata_doc)):
        if not isinstance(doc, dict) or not isinstance(doc.get("objects"), list):
            muammo.append(f"{nom}: `objects` ro'yxati o'qilmadi")
            continue
        to_liq = [o["full_name"] for o in doc["objects"]
                  if isinstance(o, dict) and isinstance(o.get("full_name"), str)]
        shakli_buzuq = [i for i, o in enumerate(doc["objects"])
                        if not isinstance(o, dict) or not isinstance(o.get("full_name"), str)]
        if shakli_buzuq:
            muammo.append(f"{nom}.objects: `full_name` matn emas, indeks(lar) {shakli_buzuq}")
        dupes = _dupes(to_liq)
        if dupes:
            # ⚠️ OBYEKT MANZILI TASHQI MATN: u 1C dan keladi va sir bo'lishi mumkin.
            muammo.append(f"{nom}.objects: `full_name` takrorlangan "
                          f"{_xavfsiz_royxat(dupes)}")
        sanoq.append(f"{nom}: {len(to_liq)} obyekt")
    if muammo:
        ck.bad("obyekt_noyobligi", "; ".join(sorted(muammo)))
    else:
        ck.ok("obyekt_noyobligi", "; ".join(sanoq) + " — `full_name` takrorlanmaydi")

    # ── 6 · HAVOLA BUTUNLIGI (IMKON BO'LGANDA) ────────────────────────────────────────────
    muammo = []
    eslatma = []
    if isinstance(export_doc, dict) and isinstance(export_doc.get("objects"), list) \
            and isinstance(export_doc.get("candidates"), list):
        ko_rilgan = {o["full_name"] for o in export_doc["objects"]
                     if isinstance(o, dict) and isinstance(o.get("full_name"), str)}
        for i, c in enumerate(export_doc["candidates"]):
            if not isinstance(c, dict):
                continue
            src = c.get("source_object")
            # ⚠️ `absent` ISTISNO: yo'qlik da'vosi ta'rifi bo'yicha obyekt ro'yxatda
            #    bo'lmasligini bildiradi (`bundle._validate_cross_refs` bilan AYNI qoida).
            if src is None or c.get("source_kind") == "absent":
                continue
            if src not in ko_rilgan:
                # ⚠️ NISHON HAM, MANBA HAM TASHQI QIYMAT.
                muammo.append(f"{EXPORT_FILE}.candidates[{i}] ({_xavfsiz(c.get('target'))}) "
                              f"KO'RILMAGAN obyektga ishora qiladi: {_xavfsiz(src)}")
    else:
        muammo.append(f"{EXPORT_FILE}: `objects`/`candidates` o'qilmadi")

    if isinstance(metadata_doc, dict):
        try:
            aniqlanmagan = validate_metadata(metadata_doc)
        except DiscoveryError as e:
            muammo.append(f"{METADATA_FILE}: {_xavfsiz(e)}")
        else:
            # ⚠️ ANIQLANMAGAN HAVOLA NUQSON EMAS: konfiguratsiya bo'lak-bo'lak olinishi
            #    mumkin, shu bois bunday havola «tashqi/aniqlanmagan» deb SAQLANADI. Jimgina
            #    o'chirish ma'lumot yo'qotish bo'lardi — shuning uchun u SANALADI, rad
            #    ETILMAYDI (`metadata.unresolved_references`).
            eslatma.append(f"aniqlanmagan havola: {len(aniqlanmagan)} ta (NUQSON EMAS — "
                           f"konfiguratsiya bo'lak-bo'lak olinishi mumkin)")
    else:
        muammo.append(f"{METADATA_FILE}: o'qilmadi")

    # `errors.family` -> `run_status.families` KESISHMASI tekshiriladi.
    # ⚠️ `errors.object` TEKSHIRILMAYDI va bu OCHIQ aytiladi: o'qilmagan obyekt ta'rifi
    #    bo'yicha hech qaysi ro'yxatda turmaydi, ya'ni uni «mavjud bo'lishi shart» deb
    #    talab qilish o'qish xatosini hujjatlashning O'ZINI taqiqlab qo'yardi.
    if isinstance(errors_doc, dict) and isinstance(errors_doc.get("errors"), list) \
            and isinstance(run_doc, dict) and isinstance(run_doc.get("families"), list):
        oilalar = {f["name"] for f in run_doc["families"]
                   if isinstance(f, dict) and isinstance(f.get("name"), str)}
        notanish = sorted({e["family"] for e in errors_doc["errors"]
                           if isinstance(e, dict) and isinstance(e.get("family"), str)
                           and e["family"] not in oilalar})
        if notanish:
            # ⚠️⚠️ AYNAN SHU YER SIRNI EKRANGA CHIQARARDI: `family` qiymati `errors.json` dan
            #    keladi, `errors.json` esa 1C ning xato tavsifini tashiydi — SUBD xatosi
            #    ulanish satrini, server nomini va PAROLNI o'z ichiga oladi. Nom XOM holda
            #    nuqson matniga qo'shilardi, matn esa CLI ekraniga va `--json` chiqishiga
            #    tushardi. Endi `_xavfsiz` dan o'tadi: operator «notanish oila bor» degan
            #    xabarni ko'radi, qiymatning o'zini esa KO'RMAYDI.
            muammo.append(f"{ERRORS_FILE}: `family` {_xavfsiz_royxat(notanish)} "
                          f"`run_status.families` da yo'q — qaralmagan oilaning xatosi "
                          f"bo'lishi mumkin emas")
    if muammo:
        ck.bad("havola_butunligi", "; ".join(sorted(muammo)))
    else:
        ck.ok("havola_butunligi",
              "nomzodlar KO'RILGAN obyektlarga ishora qiladi, `errors.family` qaralgan "
              "oilalarga tegishli"
              + ("; " + "; ".join(eslatma) if eslatma else ""))

    # ── 7 · YIG'UVCHIDAN `VERIFIED` YO'Q ──────────────────────────────────────────────────
    # ⚠️ Yig'uvchi o'zini o'zi tasdiqlay olmaydi: u hali BIRORTA haqiqiy konfiguratsiyada
    #    ishlamagan. `VERIFIED` faqat odam ko'rigidan keladi, KUCHLI dalil esa zonddan ham,
    #    metadata razvedkasidan ham CHIQMAYDI (`schema.confidence_error`).
    muammo = []
    for n in sorted(texts):
        if VERIFIED_WORD_RE.search(texts[n]):
            muammo.append(f"{_xavfsiz(n)}: `VERIFIED` so'zi turadi")
    kuchli_taqiq = []
    for n in sorted(texts):
        topilgan = sorted({k for k in STRONG_EVIDENCE_KINDS if k in texts[n]})
        if topilgan:
            kuchli_taqiq.append(f"{_xavfsiz(n)}: {topilgan}")
    if kuchli_taqiq:
        muammo.append("KUCHLI dalil turi yig'uvchidan kelmaydi — " + "; ".join(kuchli_taqiq))
    if not texts:
        ck.bad("yiguvchidan_verified_yoq", NOT_RUN)
    elif muammo:
        ck.bad("yiguvchidan_verified_yoq",
               "; ".join(muammo)
               + f". Yig'uvchi o'zini tasdiqlay olmaydi: eng yuqorisi "
                 f"{CONFIDENCE_CANDIDATE}, {CONFIDENCE_UNKNOWN} esa sababi bilan. Ruxsat "
                 f"etilgan dalil turlari: {', '.join(sorted(WEAK_EVIDENCE_KINDS))}")
    else:
        ck.ok("yiguvchidan_verified_yoq",
              f"{len(texts)} faylda `VERIFIED` so'zi ham, kuchli dalil turi ham yo'q "
              f"(`UNVERIFIED` so'z chegarasi bilan AJRATILGAN va u QONUNIY)")

    # ── 8 · BSL DAN `confidence` YO'Q ─────────────────────────────────────────────────────
    # ⚠️ Ishonch darajasi 1C tomonida HISOBLANMAYDI. `validate_export` kalit oq ro'yxati
    #    nomzod darajasida buni to'sadi, ammo `export.objects`/`counts` ni FAQAT ro'yxat deb
    #    ko'radi — ya'ni ichma-ich yashiringan `confidence` o'tib ketardi. Shu bois kalitlar
    #    butun paket bo'ylab kezib chiqiladi.
    muammo = []
    for n in sorted(docs):
        topilgan = sorted({yo_l for yo_l, kalit in _walk_keys(docs[n], "")
                           if CONFIDENCE_KEY_RE.search(kalit)})
        if topilgan:
            # ⚠️ Yo'lda hujjatning KALITLARI turadi — ular ham tashqi matn.
            muammo.append(f"{_xavfsiz(n)}: {_xavfsiz_royxat(topilgan)}")
    if not docs:
        ck.bad("bsl_dan_confidence_yoq", NOT_RUN)
    elif muammo:
        ck.bad("bsl_dan_confidence_yoq",
               "`confidence` nomli kalit(lar): " + "; ".join(muammo)
               + ". Yig'uvchi daraja BERMAYDI — u faqat KO'RGANINI yozadi, darajani BinOS "
                 "tomoni hisoblaydi (`export_adapter`)")
    else:
        ck.ok("bsl_dan_confidence_yoq",
              f"{len(docs)} hujjatda `confidence` nomli kalit yo'q")

    # ── 9 · MAXFIYLIK SKANI (strukturali) ─────────────────────────────────────────────────
    if not docs and not texts:
        ck.bad("maxfiylik_skani", NOT_RUN)
    else:
        yuk = {"documents": docs, "run_summary_md": texts.get(RUN_SUMMARY_FILE)}
        findings = redaction.scan(yuk)
        if findings:
            # ⚠️ `Finding.__str__` QIYMATNI ko'rsatmaydi, lekin YO'LNI ko'rsatadi — yo'lda esa
            #    hujjatning kalitlari va FAYL NOMLARI turadi (`documents.<fayl>....`). Sir
            #    kalit NOMIDA yoki fayl nomida bo'lsa, u yo'l orqali chiqib ketardi.
            ck.bad("maxfiylik_skani",
                   "sir shubhasi: " + "; ".join(_xavfsiz(f) for f in findings[:10])
                   + (f" (+{len(findings) - 10} ta)" if len(findings) > 10 else "")
                   + ". FAIL-CLOSED: yolg'on ijobiy — bir marta qo'lda ko'rish, yolg'on "
                     "salbiy — mijozning paroli paket bilan tarqaladi")
        else:
            ck.ok("maxfiylik_skani",
                  "strukturali skan toza: sir nomli kalit ham, sir shaklidagi qiymat ham yo'q")

    # ── 10 · TAQIQLANGAN SIR NAQSHLARI (xom matn) ─────────────────────────────────────────
    if not texts:
        ck.bad("taqiqlangan_sir_naqshlari", NOT_RUN)
    else:
        xom: list[str] = []
        for n in sorted(texts):
            xom += _raw_secret_findings(n, texts[n])
        if xom:
            ck.bad("taqiqlangan_sir_naqshlari",
                   "xom matnda taqiqlangan naqsh: " + "; ".join(xom[:10])
                   + (f" (+{len(xom) - 10} ta)" if len(xom) > 10 else "")
                   + ". Qiymatning O'ZI ataylab ko'rsatilmaydi")
        else:
            ck.ok("taqiqlangan_sir_naqshlari",
                  f"{len(texts)} faylning XOM matnida ulanish satri, parol, token, e-mail, "
                  f"telefon, PEM bloki, masofaviy kirish ID si, Windows/UNC yo'li va "
                  f"`IP:port` naqshlari topilmadi")

    # ── 11 · XESH / MANIFEST MOSLIGI ──────────────────────────────────────────────────────
    if not isinstance(manifest_doc, dict) or not isinstance(manifest_doc.get("files"), list):
        ck.bad("xesh_manifest_mosligi", NOT_RUN)
    else:
        muammo = []
        qatorlar = [f for f in manifest_doc["files"] if isinstance(f, dict)]
        manifestda = {f.get("name") for f in qatorlar}
        # Manifest O'ZIDAN tashqari HAMMA faylni qamrashi SHART.
        kutilgan = {n for n in nomlar if n != MANIFEST_FILE}
        yetmayotgan = sorted(kutilgan - manifestda)
        if yetmayotgan:
            muammo.append(f"manifestda fayl yo'q: {_xavfsiz_royxat(yetmayotgan)}")
        ortiqcha = sorted(n for n in manifestda - kutilgan if isinstance(n, str))
        if ortiqcha:
            muammo.append(f"manifestda papkada YO'Q fayl(lar): {_xavfsiz_royxat(ortiqcha)}")
        for f in sorted(qatorlar, key=lambda r: str(r.get("name"))):
            nom = f.get("name")
            if not isinstance(nom, str) or nom not in members:
                continue
            raw = members[nom]
            if isinstance(f.get("bytes"), str) and f["bytes"].isdigit() \
                    and int(f["bytes"]) != len(raw):
                muammo.append(f"{_xavfsiz(nom)}: bayt hajmi mos emas (manifest {f['bytes']}, "
                              f"haqiqiy {len(raw)})")
            xesh = f.get("sha256")
            if xesh is None:
                # ⚠️ `null` — yig'uvchi xeshlay olmagani. Bu JAVOB, lekin xeshsiz fayl
                #    ko'chirishda buzilganini isbotlab bo'lmaydi, shu bois NUQSON deb
                #    belgilanadi: fail-closed.
                muammo.append(f"{_xavfsiz(nom)}: `sha256` `null` — xeshsiz fayl ko'chirishda "
                              f"buzilganini isbotlab bo'lmaydi")
            elif isinstance(xesh, str) and xesh != sha256_bytes(raw):
                muammo.append(f"{_xavfsiz(nom)}: sha256 MOS KELMADI — fayl manifest "
                              f"yozilgandan keyin o'zgargan yoki ko'chirishda buzilgan")
        if muammo:
            ck.bad("xesh_manifest_mosligi", "; ".join(sorted(muammo)))
        else:
            ck.ok("xesh_manifest_mosligi",
                  f"{len(qatorlar)} fayl xeshi va bayt hajmi mos ({MANIFEST_FILE} O'ZINI "
                  f"xeshlamaydi — bu shartnoma)")

    # ── 12 · ARTEFAKT DA'VOSI ─────────────────────────────────────────────────────────────
    if not isinstance(run_doc, dict) or not isinstance(run_doc.get("artifacts"), list):
        ck.bad("artefakt_dalvosi", NOT_RUN)
    else:
        dalvo = {a for a in run_doc["artifacts"] if isinstance(a, str)}
        haqiqiy = set(nomlar)
        yoq = sorted(dalvo - haqiqiy)
        sanalmagan = sorted(haqiqiy - dalvo)
        muammo = []
        if yoq:
            muammo.append(f"da'vo qilingan, lekin papkada YO'Q: {_xavfsiz_royxat(yoq)}")
        if sanalmagan:
            muammo.append(f"papkada bor, lekin `artifacts` da SANALMAGAN: "
                          f"{_xavfsiz_royxat(sanalmagan)} — "
                          f"`artifacts` O'ZINI ham, {MANIFEST_FILE!r} ni ham sanaydi "
                          f"(nomni sanash mazmunga tegmaydi, shu bois aylanma YO'Q)")
        if muammo:
            ck.bad("artefakt_dalvosi", "; ".join(muammo))
        else:
            ck.ok("artefakt_dalvosi",
                  f"`artifacts` papka bilan AYNAN mos: {len(dalvo)} fayl")

    # ── 13 · `UNKNOWN` TO'LIQLIGI ─────────────────────────────────────────────────────────
    # ⚠️ ANIQLANMAGAN NISHON TASHLAB KETILMAYDI. «Qaralmadi» va «yo'q» bir xil emas: jim
    #    tushib qolgan nishon hisobotni TO'LIQ ko'rsatadi, aslida esa savol berilmagan.
    # ⚠️ QURUQ YURISH: nishon to'liqligini isbotlashning yagona halol yo'li — to'plam
    #    ko'prigini AYNAN o'sha kod bilan o'tkazib ko'rish. `source_kind="copy"` bu yerda
    #    OPERATOR E'LONI EMAS, balki ko'prikning majburiy argumenti uchun SENTINEL: natija
    #    XOTIRADA qoladi, hech qayerga YOZILMAYDI va to'plam sifatida ishlatilMAYDI. Haqiqiy
    #    aylantirishda `source_kind` ni OPERATOR e'lon qiladi (`export_adapter` docstringi).
    if not isinstance(export_doc, dict):
        ck.bad("unknown_toliqligi", NOT_RUN)
    else:
        try:
            quruq = to_bundle_members(export_doc, source_kind="copy")
            topam = load_members(quruq)
        except DiscoveryError as e:
            ck.bad("unknown_toliqligi",
                   f"to'plam ko'prigi qurilmadi (quruq yurish): {_xavfsiz(e)}")
        else:
            darajalar: dict[str, int] = {}
            sababsiz: list[str] = []
            for m in topam.mappings:
                darajalar[m["confidence"]] = darajalar.get(m["confidence"], 0) + 1
                if m["confidence"] == CONFIDENCE_UNKNOWN and not m["errors"] \
                        and m["source_kind"] not in (None, "absent"):
                    sababsiz.append(m["target"])
            nishonlar = sorted(m["target"] for m in topam.mappings)
            muammo = []
            if nishonlar != sorted(TARGETS):
                # ⚠️ «Ortiqcha» nishon paketdan keladi, ya'ni TASHQI qiymat — tozalanadi.
                muammo.append(
                    f"nishonlar TARGETS bilan mos emas: "
                    f"yo'q {sorted(set(TARGETS) - set(nishonlar))}, "
                    f"ortiqcha {_xavfsiz_royxat(sorted(set(nishonlar) - set(TARGETS)))}")
            if sababsiz:
                muammo.append(f"{CONFIDENCE_UNKNOWN} nishon(lar) sababsiz: "
                              f"{_xavfsiz_royxat(sorted(sababsiz))}")
            if muammo:
                ck.bad("unknown_toliqligi", "; ".join(muammo))
            else:
                ck.ok("unknown_toliqligi",
                      f"{len(nishonlar)} nishonning HAMMASI qayd etilgan, darajalar: "
                      + ", ".join(f"{k}={darajalar[k]}" for k in sorted(darajalar))
                      + " (quruq yurish: to'plam XOTIRADA qurildi, yozilMADI)")

    # ── 14 · GRAF QURILISHI ───────────────────────────────────────────────────────────────
    graf = None
    if not isinstance(metadata_doc, dict):
        ck.bad("graf_qurilishi", NOT_RUN)
    else:
        try:
            graf = build_graph(metadata_doc)
        except DiscoveryError as e:
            ck.bad("graf_qurilishi", f"graf qurilmadi: {_xavfsiz(e)}")
        else:
            # ⚠️ GRAF QURILISHI TASDIQ EMAS: obyekt grafda turgani uning mazmuni
            #    ko'chirishga yaroqli ekanini ISBOTLAMAYDI (`graph.py` docstringi).
            ck.ok("graf_qurilishi",
                  f"graf qurildi: {len(graf.objects)} obyekt, "
                  f"{len(graf.relationships)} qirra, "
                  f"{len(graf.unresolved_references)} aniqlanmagan havola "
                  f"(graf qurilishi TASDIQ EMAS)")

    # ── 15 · AI ANALITIK KIRISHIGA TAYYORLIK ──────────────────────────────────────────────
    # ⚠️ YUK QURILADI, HECH QAYERGA YUBORILMAYDI. Bu tekshiruv provayderni TALAB QILMAYDI va
    #    tarmoqqa chiqmaydi: `analyst_payload` faqat lug'at yasaydi va uni O'ZI sir uchun
    #    qayta skanerlaydi (fail-closed).
    if graf is None:
        ck.bad("ai_kirishiga_tayyor", NOT_RUN)
    else:
        try:
            yuk = ai.analyst_payload(graf)
        except DiscoveryError as e:
            ck.bad("ai_kirishiga_tayyor", f"analitik yuki qurilmadi: {_xavfsiz(e)}")
        else:
            ck.ok("ai_kirishiga_tayyor",
                  f"analitik yuki qurildi ({yuk['payload_version']}), "
                  f"{len(yuk['graph']['objects'])} obyekt — YUBORILMADI, tarmoq YO'Q")

    # ── 16 · REJIM DARVOZASI ──────────────────────────────────────────────────────────────
    if not isinstance(run_doc, dict) or run_doc.get("mode") not in MODES \
            or not isinstance(run_doc.get("probes"), list):
        ck.bad("rejim_darvozasi", NOT_RUN)
    else:
        rejim = run_doc["mode"]
        # ⚠️ SOLISHTIRISH FAYL NOMI BO'YICHA, TUR BO'YICHA EMAS: bitta turdagi zond ikki
        #    BOSHQA nishonga bajarilishi mumkin, ya'ni tur bo'yicha taqqoslash ikkinchi
        #    zondni jimgina «takror» deb yo'qotardi. Fayl nomi esa noyob va u jurnalda ham,
        #    papkada ham AYNI ko'rinadi.
        qayd = sorted({p["file"] for p in run_doc["probes"]
                       if isinstance(p, dict) and isinstance(p.get("file"), str)})
        fayllar = sorted(probe_nomlar)
        muammo = []
        if rejim == MODE_METADATA_ONLY:
            if fayllar:
                muammo.append(f"{MODE_METADATA_ONLY} rejimida zond fayli BO'LMAYDI: "
                              f"{_xavfsiz_royxat(fayllar)}")
            if qayd:
                muammo.append(f"{MODE_METADATA_ONLY} rejimida `probes` jurnali BO'SH "
                              f"bo'ladi: {_xavfsiz_royxat(qayd)}")
        elif qayd != fayllar:
            muammo.append(
                f"{MODE_APPROVED_PROBES}: zond fayllari va `probes` jurnali mos emas — "
                f"faqat papkada {_xavfsiz_royxat(sorted(set(fayllar) - set(qayd)))}, "
                f"faqat jurnalda {_xavfsiz_royxat(sorted(set(qayd) - set(fayllar)))}. "
                f"Operator tasdiqlagan ALLOWLIST bilan bajarilgan ish AYNAN mos bo'lishi SHART")
        if muammo:
            ck.bad("rejim_darvozasi", "; ".join(muammo))
        else:
            # ⚠️ REJIM IZOHI TASHQI MATN: u yig'uvchidan keladi va ichida 1C xatosi (ya'ni
            #    ulanish satri) bo'lishi mumkin — shu bois ekranga `_xavfsiz` dan o'tib
            #    chiqadi.
            ck.ok("rejim_darvozasi",
                  f"rejim {rejim}, zond: {len(qayd)} fayl"
                  + (f" ({', '.join(_xavfsiz_royxat(qayd))})" if qayd
                     else " — aktiv zond YO'Q")
                  + (f"; izoh: {_xavfsiz(run_doc.get('mode_note'))}"
                     if run_doc.get("mode_note") else ""))

    # ── 17 · `overall` ZIDDIYATSIZ ────────────────────────────────────────────────────────
    # ⚠️ §6 ning oxirgi bandi: `SUCCESS` deb e'lon qilingan yurishda majburiy artefakt yo'q
    #    bo'lsa — bu ZIDDIYAT va u ANIQ nuqson deb belgilanadi. Ziddiyat oddiy nuqsondan
    #    QO'RQINCHLIROQ: u paketning O'Z hisobotiga ishonib bo'lmasligini ko'rsatadi.
    # ⚠️ BU TEKSHIRUV IKKI TOMONLI BO'LDI. Ilgari u FAQAT `SUCCESS` shoxini ko'rardi, ya'ni
    #    `overall=FAILED` (yoki `PARTIAL`) bo'lib `errors.json` BO'SH bo'lgan paket 17/17
    #    tekshiruvdan o'tib ketardi: `ok=True`, CLI «HAMMASI O'TDI» yozardi, chiqish kodi 0
    #    bo'lardi — runbook esa 0 ni «AI analitikka topshir» deb ta'riflaydi. Ya'ni YIQILGAN
    #    yurish keyingi bosqichga jimgina o'tib ketardi. Endi SABABSIZ yiqilish ham ZIDDIYAT.
    #: ⚠️ FAIL-CLOSED DEFAULT: yurish yozuvi o'qilmasa holat NOMA'LUM (`None`) bo'lib qoladi
    #: va chaqiruvchi (`cli.main`) uni HECH QACHON `SUCCESS` deb qabul qilmaydi.
    e_lon_qilingan_overall: str | None = None
    if not isinstance(run_doc, dict) or run_doc.get("overall") not in OVERALLS:
        ck.bad("overall_ziddiyatsiz", NOT_RUN)
    else:
        overall = run_doc["overall"]
        e_lon_qilingan_overall = overall
        muammo = []
        # ⚠️ E'LON QILINGAN HOLAT HISOBLANGANI BILAN SOLISHTIRILADI, SHU YERDA: yagona ta'rif
        #    bo'limlarga, OILALARGA va yozilgan artefaktlarga tayanadi (`derive_overall`), ya'ni
        #    hukm bir nechta hujjat maydonidan quriladi va bitta joyda aytiladi.
        secs_x = [s for s in (run_doc.get("sections") or [])
                  if isinstance(s, dict) and isinstance(s.get("status"), str)]
        fams_x = [f for f in (run_doc.get("families") or []) if isinstance(f, dict)]
        arts_x = [a for a in (run_doc.get("artifacts") or []) if isinstance(a, str)]
        if not secs_x:
            muammo.append("bo'limlar o'qilmadi — holat HISOBLAB bo'lmadi. FAIL-CLOSED: "
                          "«tekshirib ko'rmadim» «muammo yo'q» EMAS")
        else:
            hisoblangan = derive_overall(secs_x, families=fams_x, artifacts=arts_x)
            if hisoblangan != overall:
                muammo.append(
                    f"ZIDDIYAT: e'lon qilingan `overall={overall}`, hisoblangani "
                    f"{hisoblangan!r} — holat YAGONA ta'rifdan HISOBLANADI (majburiy "
                    f"artefaktlar yozilgan + `failed` bo'lim yo'q + `unreadable` oila yo'q)")
        if overall == OVERALL_SUCCESS:
            if yoq_fayllar := [n for n in REQUIRED_FILES if n not in members]:
                muammo.append(f"ZIDDIYAT: `overall=SUCCESS`, lekin majburiy artefakt YO'Q: "
                              f"{yoq_fayllar}")
            if isinstance(errors_doc, dict) and isinstance(errors_doc.get("errors"), list) \
                    and errors_doc["errors"]:
                muammo.append(
                    f"ZIDDIYAT: `overall=SUCCESS`, lekin `{ERRORS_FILE}` da "
                    f"{len(errors_doc['errors'])} xato bor — birorta bo'limni yiqitmagan "
                    f"xato JIMGINA tushib qolgan nosozlik, holat esa PARTIAL bo'lishi kerak")
            if isinstance(run_doc.get("families"), list):
                oqilmagan = sorted(f["name"] for f in run_doc["families"]
                                   if isinstance(f, dict) and f.get("state") == "unreadable"
                                   and isinstance(f.get("name"), str))
                if oqilmagan:
                    # ⚠️ OILA NOMI TASHQI QIYMAT — `_xavfsiz` dan o'tadi.
                    muammo.append(
                        f"ZIDDIYAT: `overall=SUCCESS`, lekin o'qilmagan oila(lar) bor: "
                        f"{_xavfsiz_royxat(oqilmagan)}. `unreadable` — javob YO'QLIGI, "
                        f"`absent` esa JAVOB; birinchisi bilan yurish muvaffaqiyatli deb "
                        f"e'lon qilinmaydi")
        else:
            # ── YIQILGAN YURISH SABABINI KO'RSATISHI SHART (fail-closed) ──────────────────
            # ⚠️ NEGA BU ZIDDIYAT: `PARTIAL`/`FAILED` «nimadir bo'ldi» degani, `errors.json`
            #    ning bo'shligi esa «hech narsa bo'lmadi» degani. Ikkisi birga turolmaydi:
            #    yo holat yolg'on, yo xato ro'yxati to'ldirilmagan — har ikki holda paketning
            #    O'Z hisobotiga ishonib bo'lmaydi va operator tuzatadigan narsa ham yo'q
            #    («nimani tuzatay?»).
            xato_royxati = errors_doc.get("errors") if isinstance(errors_doc, dict) else None
            if not isinstance(xato_royxati, list):
                muammo.append(
                    f"ZIDDIYAT: `overall={overall}`, lekin `{ERRORS_FILE}` o'qilmadi — "
                    f"yiqilishning SABABI tekshirilmadi. FAIL-CLOSED: «tekshirib ko'rmadim» "
                    f"«muammo yo'q» EMAS")
            elif not xato_royxati:
                muammo.append(
                    f"ZIDDIYAT: `overall={overall}`, lekin `{ERRORS_FILE}` BO'SH — sababi "
                    f"ko'rsatilmagan yiqilish. Yurish «to'liq tugamadim» deydi, xato ro'yxati "
                    f"esa «hech narsa bo'lmadi» deydi; ikkisidan biri YOLG'ON")
        if muammo:
            ck.bad("overall_ziddiyatsiz", "; ".join(muammo))
        else:
            ck.ok("overall_ziddiyatsiz",
                  f"`overall={overall}` YAGONA ta'rifdan hisoblangan holatga mos va majburiy "
                  f"artefakt, xato ro'yxati, oila holatlari bilan ZIDDIYATSIZ"
                  + ("" if overall == OVERALL_SUCCESS
                     else " — lekin yurishning O'ZI to'liq emas (sabablari "
                          f"`{ERRORS_FILE}` da)"))

    return ck.build(overall=e_lon_qilingan_overall)


def report_to_json_text(report: Report) -> str:
    """Hisobotning DETERMINISTIK JSON matni: bir xil paket — AYNAN bir xil baytlar."""
    return dumps(report.to_json())
