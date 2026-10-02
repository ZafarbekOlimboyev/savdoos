# -*- coding: utf-8 -*-
"""YURISHGA BOG'LANGAN KO'PRIK PROTOKOLI — `request.json` / `response.json` / `bridge_done.json`.

Agent va 1C ichidagi yig'uvchi BIR papka orqali gaplashadi. Shartnoma ATAYLAB uchta
hujjatga bo'lingan:

    request.json        AGENT yozadi      `binos-bridge-request-v1`
    response.json       YIG'UVCHI yozadi  `binos-bridge-response-v1`
    bridge_done.json    YIG'UVCHI yozadi  `binos-bridge-done-v1`  — ENG OXIRIDA

⚠️⚠️ NEGA UCHINCHI HUJJAT: `response.json` ning O'ZI yozilib bo'lgani bilinmaydi — fayl
     yarim yozilgan holatda ham diskda turadi va agent uni to'liq deb o'qib ketardi. Shu
     bois tugallanish belgisi ENG OXIRIDA, alohida fayl bo'lib yoziladi: belgi yo'q bo'lsa
     javob QABUL QILINMAYDI (`DONE_MARKER_MISSING`).
⚠️⚠️ PHASE 4 PAKETINING `manifest.json` I O'ZGARMAYDI. U `bundle/` ichida yashaydi va o'z
     navbatida oxirgi yoziladi; ko'prik belgisi esa QO'SHIMCHA qatlam, undan TASHQARIDA.
     Ikki hujjat bir-birini ALMASHTIRMAYDI va bir-birining nomini OLMAYDI — Phase 4 da
     «bir xil nom, ikki xil sxema» butun paketni rad etgan edi.

⚠️⚠️ YURISHGA BOG'LANGAN (run-bound) degani: har javob AYNAN bitta so'rovga tegishli.
     Buning uchun ikki qiymat solishtiriladi — `run_id` (yurish o'zligi) va `nonce` (shu
     yurish uchun bir martalik qiymat). Ikkisi `secrets.token_hex` bilan tug'iladi, demak
     taxmin qilib bo'lmaydi va «papkada qolgan eski natijani qayta ishlatish» YO'LI YOPIQ.

⚠️⚠️ KREDENSIAL: parol `argv` ga, jurnalga, natija fayliga, doimiy konfiguratsiyaga va
     buyruq tarixiga HECH QACHON tushmaydi. Ishga tushirishda FAQAT `/F<yo'l>` yoki
     `/S<server>`; parol/foydalanuvchi kalitlari TAQIQLANGAN va darvoza ikkinchi nusxada
     YOZILMAYDI — mavjud `collector_bridge` tekshiruvi QAYTA ISHLATILADI.
     Parolni 1C NING O'Z oynasi oladi, agent uni KO'RMAYDI.

⚠️⚠️ NISHON O'ZLIGI KREDENSIALSIZ: protokolga nishonning XOM `locator` i (fayl yo'li yoki
     server ulanish satri) YOZILMAYDI — faqat `kind` + `name` + `locator` ning sha256
     xeshi (`target_fingerprint`). Sabab: `locator` sir bo'lishi mumkin (`Usr`/`Pwd`
     bo'laklari, UNC yo'li, server nomi), xesh esa solishtirish uchun YETARLI.

⚠️ COM YO'Q. O'ylab chiqarilgan buyruq satri parametri YO'Q. Avtomatik ishga tushirish yo'li
   DEKLARATSIYA bo'lib qoladi va `bridge_phase.AUTOMATIC_LAUNCH_VERIFICATION` bilan
   belgilanadi: agent 1C ni o'zi ochishga URINMAYDI, operator tasdig'isiz esa bu yo'l
   umuman boshlanmaydi (`COLLECTOR_EXECUTION_NOT_ALLOWED`).
⚠️ TARMOQ YO'Q: bu modulda tarmoq importi ham, ulanish chaqiruvi ham yo'q.
⚠️ O'CHIRISH YO'Q: bu modulda birorta fayl/papka o'chirish naqshi YO'Q — na wildcard
   bo'yicha, na yolg'iz fayl bo'yicha. Agent FAQAT O'Z yurish papkasini yaratadi, papka
   bo'sh bo'lmasa esa TO'XTAYDI (`RUN_DIR_NOT_EMPTY`) va begona fayllarga TEGMAYDI.
   Umumiy global natija fayli ham YO'Q: har yurish o'z papkasida yashaydi.
⚠️ Vaqt KIRISHDAN keladi (`now` parametri): bu modul soatni O'ZI o'qimaydi, aks holda na
   determinizm, na test bo'ladi.
⚠️ Hamma JSON UTF-8 va DETERMINISTIK (`discovery_1c.bundle.dumps`): bir xil mazmun — AYNAN
   bir xil bayt. Sanoqlar MATN, boolean YO'Q (yadrodagi qoida bilan AYNI).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
from dataclasses import dataclass

from . import bridge_phase as bp
from .collector_bridge import _assert_no_credentials
from .detector import KIND_FILE, KIND_SERVER
from .status import RUN_ID_RE
from ..discovery_1c import redact as redaction
from ..discovery_1c.bundle import dumps
from ..discovery_1c.probe import PROBE_CATALOG
from ..discovery_1c.runtime_bundle import (MODE_METADATA_ONLY, MODES, OVERALL_FAILED,
                                           OVERALL_PARTIAL, OVERALL_SUCCESS,
                                           REQUIRED_FILES)
from ..migrator_1c.bundle import BundleError, parse_ts

# ══════════════════════════════════════════════════════════════════════════════════════════
# SXEMA NOMLARI va FAYL NOMLARI — SHARTNOMA
# ══════════════════════════════════════════════════════════════════════════════════════════
REQUEST_VERSION = "binos-bridge-request-v1"
RESPONSE_VERSION = "binos-bridge-response-v1"
DONE_VERSION = "binos-bridge-done-v1"

REQUEST_FILE = "request.json"
RESPONSE_FILE = "response.json"
DONE_FILE = "bridge_done.json"

#: ⚠️ BEKOR QILISH KOOPERATIV: agent shu nomdagi belgini qo'yadi, yig'uvchi esa uni ko'rib
#: O'ZI to'xtaydi. Jarayonni KENG O'LDIRISH (jarayon daraxtini tugatish) YO'Q.
#: ⚠️⚠️ HALOL QAYD (ANIQLASHTIRILDI): bu FAYLNI yozadigan kod shu relizda ham YO'Q — nom
#:    SHARTNOMA sifatida qotirilgan va «1C ichidagi yig'uvchi ham to'xtaydi» degan da'vo
#:    BERILMAYDI. Lekin AGENT TOMONIDAGI bekor qilish ENDI ROSTDAN BOR va u SHIPPED
#:    yo'lda ishlatiladi: `launcher.CancelToken` + `launcher.wait_for_collector`, va
#:    `one_click.run_one_click(cancel=...)` uni oqimga uzatadi. Ya'ni agent KUTISHNI
#:    to'xtatadi (holat `states.ABORTED_BY_OPERATOR`), 1C oynasini esa operator O'ZI
#:    yopadi — jarayon HECH QACHON majburan tugatilmaydi.
CANCEL_FILE = "cancel_requested.json"

#: ⚠️ Yurish papkasini almashtiradigan kalit NOMI.
#: ⚠️⚠️ HALOL QAYD YANGILANDI (ESKIRGAN DA'VO OLIB TASHLANDI): ilgari bu izoh «uni buyruq
#:    satriga qo'shadigan kod YO'Q (`__main__.py` tegilmagan)» deydi — bu ENDI HAQIQAT
#:    EMAS. `__main__.py` da `--runs-dir PAPKA` bayrog'i BOR va u
#:    `one_click.run_one_click(runs_root=...)` ga uzatiladi; bayroq faqat `--one-click`
#:    oqimida ma'noga ega va boshqa rejimda JIM TASHLAB YUBORILMAYDI (aniq xato beradi).
#:    Ya'ni qobiliyat MAVJUD va u shu nom bilan ataladi.
RUNS_DIR_OPTION = "--runs-dir"

#: Standart yurish ildizi: `%LOCALAPPDATA%\BinOS\Discovery\runs`.
#: ⚠️ NEGA SHU JOY: (1) manba daraxtidan TASHQARIDA — repo toza qoladi va natija tasodifan
#:    commit qilinmaydi; (2) administrator huquqi KERAK EMAS; (3) foydalanuvchiga tegishli,
#:    ya'ni boshqa hisobning natijasi bilan aralashmaydi.
LOCALAPPDATA_ENV = "LOCALAPPDATA"
RUNS_SUBPATH: tuple[str, ...] = ("BinOS", "Discovery", "runs")

# ══════════════════════════════════════════════════════════════════════════════════════════
# KALIT OQ RO'YXATLARI — noma'lum kalit RAD, TUSHIB QOLGAN kalit ham RAD
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ NEGA SHUNCHA QAT'IY: Phase 4 da artefakt jadvali berilgan, lekin KALIT NOMLARI
#:    berilmagan edi — ikki tomon bo'shliqni har xil to'ldirdi va to'plam yashil bo'lsa ham
#:    HAR BIR real paket rad etilardi. Shu bois bu yerda «kalit yo'q» shakli ham RAD
#:    etiladi: tushib qolgan kalit keyinroq JIMGINA boshqa ma'no oladi.
REQUEST_KEYS: frozenset[str] = frozenset({
    "request_version", "run_id", "nonce", "requested_at", "output_dir",
    "expected_collector", "target_fingerprint", "mode", "allowed_probes", "notes",
})
COLLECTOR_KEYS: frozenset[str] = frozenset({"name", "version"})
RESPONSE_KEYS: frozenset[str] = frozenset({
    "response_version", "run_id", "nonce", "collector", "target_fingerprint", "status",
    "started_at", "finished_at", "notes",
})
#: ⚠️ `done_version` QO'SHILGAN: sxema o'zligi FAYL ICHIDA bo'lishi kerak, aks holda
#: `bridge_done.json` nomli boshqa sxemali fayl jimgina qabul qilinardi (`RUN_VERSION`
#: naqshi bilan AYNI).
DONE_KEYS: frozenset[str] = frozenset({"done_version", "run_id", "nonce", "written_at"})

#: Javobning YOPIQ holat lug'ati. Noma'lum qiymat RAD (fail-closed).
#:
#: ⚠️⚠️ TUZATILGAN P0 — LUG'AT IKKI XIL EDI. Ilgari bu yerda `OK` turardi, yig'uvchi
#:      (`integrations/1c/collector/BinOSDiscoveryCollector.bsl`) esa `run_status.json` ning
#:      `overall` qiymatini — `SUCCESS`/`PARTIAL`/`FAILED` — qaytaradi. Natijada
#:      MUVAFFAQIYATLI yurish `BRIDGE_SHAPE_INVALID` bilan rad etilardi: to'plam yashil,
#:      haqiqiy 1C da esa HECH QACHON ishlamaydigan ko'prik. Shu bois:
#:        · `OK` OLIB TASHLANDI — u `SUCCESS` ning dublikati edi;
#:        · uchta qiymat yadroning MAVJUD doimiylaridan IMPORT qilinadi
#:          (`runtime_bundle.OVERALL_*`) va BU YERDA QAYTA E'LON QILINMAYDI — ikkinchi
#:          nusxa bir kun birinchisidan ajralib ketardi (aynan shu nuqsonning o'zi).
#: ⚠️ `CANCELLED` — ko'prikka XOS va u ustiga qo'shiladigan YAGONA qiymat: Phase 4 da
#:    «bekor qilish» tushunchasi yo'q (yadro paketni yozadi yoki yozmaydi).
#: ⚠️ `PARTIAL` JIMGINA MUVAFFAQIYAT EMAS: u `COLLECTOR_COMPLETE` fazasiga o'tadi (javob
#:    bor, paket to'liq), lekin hukmni QUVUR beradi — Phase 4 validatori kodi `2` ni
#:    hurmat qilib TO'XTAYDI. Ko'prik yarim natijani «tugadi» deb ATAMAYDI va uni
#:    «yiqildi» deb ham atamaydi: ikkisi ham operatorni boshqa yo'lga yuborardi.
STATUS_SUCCESS = OVERALL_SUCCESS
STATUS_PARTIAL = OVERALL_PARTIAL
STATUS_FAILED = OVERALL_FAILED
STATUS_CANCELLED = "CANCELLED"
#: ⚠️⚠️ `BRIDGE_REJECTED` — yig'uvchining KO'PRIK qatlami `request.json` ni O'QIB RAD
#:      ETGANI (bir martalik belgi yoki yig'uvchi versiyasi mos emas, yoki so'rov fayli
#:      yo'q). Bu HAQIQIY JAVOB va u `FAILED` dan AJRATILADI: `FAILED` — razvedka YURDI
#:      va yiqildi; `BRIDGE_REJECTED` — razvedka UMUMAN BOSHLANMADI va 1C da hech narsa
#:      o'zgartirilmadi.
#: ⚠️⚠️ ILGARI BU QIYMAT LUG'ATDA YO'Q EDI va `.bsl` uni yozardi — shu bois noma'lum
#:      status `BRIDGE_SHAPE_INVALID` («hujjat buzuq») bo'lib ko'rinardi, ya'ni operator
#:      HAQIQIY sababni UMUMAN olmasdi. Uch tomonli konformans darvozasi shu driftni
#:      TUTDI (`test_agent_bridge_conformance`).
STATUS_BRIDGE_REJECTED = "BRIDGE_REJECTED"
RESPONSE_STATUSES: tuple[str, ...] = (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED,
                                      STATUS_CANCELLED, STATUS_BRIDGE_REJECTED)

#: ⚠️⚠️ ESKIRGAN NOM, YANGI QIYMAT: `STATUS_OK` ning QIYMATI endi `SUCCESS`. Nom faqat
#:      mavjud chaqiruvchilar (test harnessi) kompilyatsiyadan o'tishi uchun turadi va u
#:      `STATUS_SUCCESS` ning AYNAN O'ZI (import paytida tekshiriladi) — ya'ni «ikki
#:      haqiqat» qaytmaydi, chunki QIYMAT bitta. Yangi kodda `STATUS_SUCCESS` ishlatiladi
#:      va bu nom harness yangilangach OLIB TASHLANADI.
STATUS_OK = STATUS_SUCCESS

# ══════════════════════════════════════════════════════════════════════════════════════════
# SHAKL DARVOZALARI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `nonce` — kamida 32 hex belgi (16 bayt): taxmin qilinmaydigan uzunlik.
NONCE_RE = re.compile(r"[0-9a-f]{32,128}")
#: sha256 — AYNAN 64 kichik hex belgi.
FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

#: `secrets.token_hex` uchun BAYT soni. ⚠️ `run_id` qisqaroq (u ekranda va papka nomida
#: ko'rinadi), `nonce` esa 16 bayt = 32 hex belgi.
RUN_ID_BYTES = 8
NONCE_BYTES = 16

#: KO'PRIKNING `run_id` SHAKLI — AYNAN `RUN_ID_BYTES * 2` kichik hex belgi.
#: ⚠️⚠️ NEGA ALOHIDA SHART (TUZATILGAN NUQSON): `status.RUN_ID_RE` umumiy yurish o'zligi
#:      uchun yozilgan va u `[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}` — ya'ni `0000000` ham,
#:      `run-2026-10-02` ham o'tadi. Ko'prikda esa `run_id` `secrets.token_hex(8)` dan
#:      keladi va u SIR YO'LIDAGI qiymat: qisqaroq (entropiyasi kamroq) qiymatni qabul
#:      qilish «papkada qolgan eski natijani qayta ishlatish» yo'lini KENGAYTIRARDI.
#:      ⚠️ `status.RUN_ID_RE` BUZILMAYDI — u boshqa joyda (`agent_status.json`) ishlatiladi
#:         va bu yerda faqat QO'SHIMCHA, QAT'IYROQ shart qo'yiladi. Ikki shart bir-biriga
#:         zid bo'lmasligi import paytida tekshiriladi (`BRIDGE_RUN_ID_RE` ⊂ `RUN_ID_RE`).
BRIDGE_RUN_ID_RE = re.compile(r"[0-9a-f]{%d}" % (RUN_ID_BYTES * 2))

#: Nishon turlari — `detector` dan (ikkinchi lug'at YOZILMAYDI).
TARGET_KINDS: tuple[str, ...] = (KIND_FILE, KIND_SERVER)

#: Ishga tushirishda RUXSAT ETILGAN nishon kalitlari (QAROR 5). ⚠️ Boshqa hech qanday
#: kalit qo'shilmaydi va `/C` dan keyin o'ylab chiqarilgan parametr ham YO'Q.
ALLOWED_TARGET_SWITCHES: tuple[str, ...] = ("/F", "/S")


class BridgeProtocolError(ValueError):
    """Ko'prik hujjati RAD etildi. `.code` — `bridge_phase.BRIDGE_CODES` dan BITTA kod.

    ⚠️ Istisnoda AYNAN bitta kod bo'lishi SHART: «umumiy xato» operatorga nima qilishni
    aytmaydi va har qo'ng'iroq qo'lda tekshiruvga aylanadi.
    ⚠️ Xato matnida QIYMATNING O'ZI ko'rsatilmaydi (yo'l ham, `locator` ham): bu xabar
    jurnalga tushadi, jurnal esa qo'ldan-qo'lga o'tadi.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = bp.failure_triple(code).code
        super().__init__(f"[{self.code}] {message}")


@dataclass(frozen=True)
class RunIdentity:
    """Yurishning o'zligi: `run_id`, `nonce` va so'rov vaqti."""

    run_id: str
    nonce: str
    requested_at: str


@dataclass(frozen=True)
class Acceptance:
    """Yig'uvchi javobining QABUL QILINGAN natijasi.

    ⚠️⚠️ NEGA ISTISNO EMAS: shakli to'g'ri va shu yurishga tegishli javob — JAVOB, hatto
    `FAILED` bo'lsa ham. Protokol RAD ETISHLARI istisno bilan qaytadi (`.code`), mazmunan
    nosoz javob esa FAZA bilan: ikkisini aralashtirish «javob yo'q» va «javob bor, lekin
    yig'uvchi yiqildi» ni bitta narsaga aylantirardi.
    """

    status: str
    phase: str
    code: str | None


# ══════════════════════════════════════════════════════════════════════════════════════════
# KICHIK YORDAMCHILAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def _reject(code: str, msg: str) -> "BridgeProtocolError":
    return BridgeProtocolError(code, msg)


def _need(cond: bool, code: str, msg: str) -> None:
    if not cond:
        raise _reject(code, msg)


def _keys(obj, allowed: frozenset[str], where: str) -> None:
    _need(isinstance(obj, dict), bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}: noma'lum kalit(lar) {extra} — shartnomada yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}: kalit(lar) yetishmayapti {missing}")


def _text(obj: dict, key: str, where: str) -> str:
    v = obj.get(key)
    _need(isinstance(v, str) and v.strip() != "", bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}.{key} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _matched(obj: dict, key: str, pattern: re.Pattern, where: str, nima: str) -> str:
    v = _text(obj, key, where)
    _need(pattern.fullmatch(v) is not None, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}.{key} {nima} shaklida emas (qiymat ataylab ko'rsatilmayapti)")
    return v


def _ts(obj: dict, key: str, where: str):
    """ISO 8601 (offset bilan) matnni vaqtga aylantiradi (shakl buzuq bo'lsa — RAD)."""
    try:
        return parse_ts(obj.get(key), f"{where}.{key}")
    except BundleError as e:
        raise _reject(bp.CODE_BRIDGE_SHAPE_INVALID, str(e)) from e


def _scalar_paths(node, path: str) -> list[str]:
    """JSON SONI yoki `true`/`false` turgan yo'llar (tartiblangan, takrorsiz).

    ⚠️ AYNI qoida yadroda (`runtime_bundle`) va `status.py` da ham bor, lekin ikkisida ham
    u YOPIQ yordamchi. Qoida bitta va u YOZILGAN joyida takrorlanadi: hujjatda son ham,
    boolean ham bo'lmaydi — faqat matn, ro'yxat, obyekt va `null`. Sabab yadrodagi bilan
    AYNI: `0000123` soni `123` bo'lib qoladi, boolean esa uchinchi holatni JIMGINA yo'q
    qiladi.
    """
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += _scalar_paths(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _scalar_paths(v, f"{path}[{i}]")
    elif isinstance(node, (bool, int, float)):
        out.append(f"{path} ({node!r})")
    return sorted(set(out))


def _assert_no_json_numbers(doc, where: str) -> None:
    topilgan = _scalar_paths(doc, "")
    _need(not topilgan, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}: JSON soni/booleani TAQIQLANGAN (qiymatni MATN qilib yozing) — "
          f"{topilgan}")


def _notes(obj: dict, where: str) -> list[str]:
    """`notes` — matnlar ro'yxati va u SIR DARVOZASIDAN o'tadi.

    ⚠️⚠️ NEGA FAQAT `notes`: bu YAGONA erkin matn maydoni, ya'ni sir aynan shu yerdan
         sizib chiqadi (operator izohi, 1C xato matni). `output_dir` esa ATAYLAB
         tekshirilmaydi — u YO'L bo'lishi SHART (yig'uvchi qayerga yozishni bilishi kerak),
         va `redact` har qanday mahalliy yo'lni shubhali deb belgilaydi. Ya'ni butun
         hujjatni skanerlash darvozani HAR SAFAR yolg'on qizil qilardi va uni o'chirishga
         majbur qilardi.
    ⚠️ Shu bois `request.json` va `response.json` NATIJA PAKETINING bir qismi EMAS: ular
       yurish papkasida qoladi va hisobotga ko'chirilmaydi.
    """
    v = obj.get("notes")
    _need(isinstance(v, list) and all(isinstance(x, str) for x in v),
          bp.CODE_BRIDGE_SHAPE_INVALID, f"{where}.notes matnlar ro'yxati bo'lishi kerak")
    topilgan = redaction.scan(v)
    _need(not topilgan, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{where}.notes da shubhali qiymat topildi, hujjat RAD etildi — "
          f"{[str(f) for f in topilgan]}")
    return list(v)


def _collector(obj: dict, where: str) -> tuple[str, str]:
    c = obj.get("collector") if where == "response" else obj.get("expected_collector")
    kalit = "collector" if where == "response" else "expected_collector"
    _keys(c, COLLECTOR_KEYS, f"{where}.{kalit}")
    return _text(c, "name", f"{where}.{kalit}"), _text(c, "version", f"{where}.{kalit}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# NISHON O'ZLIGI — KREDENSIALSIZ XESH
# ══════════════════════════════════════════════════════════════════════════════════════════
def target_fingerprint(kind: str, name: str, locator: str) -> str:
    """Nishon KIMLIGINING sha256 xeshi: `kind` + `name` + `locator`.

    ⚠️⚠️ XOM `locator` NATIJAGA TUSHMAYDI va protokolga YOZILMAYDI. Sabab: `locator` sir
         bo'lishi mumkin — fayl bazasining to'liq yo'li, UNC yo'li yoki server ulanish
         satri (`Usr`/`Pwd` bo'laklari bilan). Solishtirish uchun esa XESH YETARLI: agent
         «javob SHU bazadan kelganmi?» degan savolga javob beradi, bazaning manzilini
         saqlashi SHART EMAS.
    ⚠️ `locator` xeshga KIRADI (undan voz kechilsa, bir xil nomli ikki baza bitta xesh
       olardi), lekin FAQAT xesh ichida: chiqishga 64 hex belgi yoziladi, XOM `locator`
       esa HECH QAYERGA yozilmaydi.
    ⚠️⚠️ DA'VO ANIQ CHEGARALANGAN (TUZATILGAN DA'VO): bu xesh `locator` ni OSHKOR
         QILMAYDI, lekin «qaytarib bo'lmaydi» degan KRIPTOGRAFIK kafolat BERILMAYDI.
         Sabab halol aytiladi: kirish past entropiyali (`kind` lug'ati ikki qiymatli,
         `name` va `locator` esa tipik qiymatlar) va tuzlanmagan sha256 — ya'ni tipik
         fayl yo'llarini LUG'AT bilan qidirib topish mumkin. Shu bois xesh «sirni
         yashirdim» deb emas, «solishtirish uchun YETARLI va xom qiymatni OLIB
         YURMAYDI» deb ishlatiladi: agent «javob SHU nishondanmi?» degan savolga javob
         beradi, nishonning manzilini SAQLAMAYDI.
    ⚠️ Kanonizatsiya `bundle.dumps` bilan: bir xil kirish — AYNAN bir xil xesh (determinizm).
    ⚠️ Noma'lum `kind` — ISTISNO (fail-closed): lug'at `detector` da, yangi tur O'YLAB
       CHIQARILMAYDI.
    """
    _need(kind in TARGET_KINDS, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"noma'lum nishon turi: {kind!r}; ruxsat etilganlari {sorted(TARGET_KINDS)}")
    for nom, qiymat in (("name", name), ("locator", locator)):
        _need(isinstance(qiymat, str) and qiymat.strip() != "",
              bp.CODE_BRIDGE_SHAPE_INVALID,
              f"target_fingerprint: {nom} bo'sh bo'lmagan matn bo'lishi kerak "
              f"(qiymat ataylab ko'rsatilmayapti)")
    xom = dumps({"kind": kind, "locator": locator, "name": name})
    return hashlib.sha256(xom.encode("utf-8")).hexdigest()


def assert_unique_target(fingerprints) -> str:
    """Nishon BIR MA'NOLI bo'lishi SHART: ikkitasi mos kelsa — `TARGET_AMBIGUOUS`.

    ⚠️ NEGA AGENT O'ZI TANLAMAYDI: noto'g'ri baza tanlansa BUTUN hisobot noto'g'ri bo'ladi,
       va bu xato jimgina — hisobot o'zini to'liq deb ko'rsatadi. Shu bois qaror OPERATORDA.
    """
    noyob = sorted({f for f in fingerprints})
    _need(noyob, bp.CODE_BRIDGE_SHAPE_INVALID, "nishon ro'yxati BO'SH")
    _need(len(noyob) == 1, bp.CODE_TARGET_AMBIGUOUS,
          f"{len(noyob)} ta nishon bir xil darajada mos keldi — tanlash OPERATORDA")
    return noyob[0]


# ══════════════════════════════════════════════════════════════════════════════════════════
# YURISH O'ZLIGI va SO'ROV
# ══════════════════════════════════════════════════════════════════════════════════════════
def new_run(*, now: str) -> RunIdentity:
    """Yangi yurish o'zligi: `run_id` va `nonce` — `secrets.token_hex` bilan.

    ⚠️ `secrets` (va NA `random`): `random` oldindan aytiladigan ketma-ketlik beradi, ya'ni
       «papkada qolgan eski natijani shu yurishning javobi deb o'tkazish» yo'li ochilardi.
    ⚠️ Vaqt KIRISHDAN (`now`): modul soatni o'zi o'qimaydi — aks holda na determinizm, na
       test bo'ladi.
    """
    _need(isinstance(now, str), bp.CODE_BRIDGE_SHAPE_INVALID,
          "now ISO 8601 matn bo'lishi kerak")
    _ts({"now": now}, "now", "new_run")
    return RunIdentity(
        run_id=secrets.token_hex(RUN_ID_BYTES),
        nonce=secrets.token_hex(NONCE_BYTES),
        requested_at=now,
    )


def build_request(
    identity: RunIdentity,
    *,
    output_dir: str,
    collector_name: str,
    collector_version: str,
    target_fingerprint: str,
    mode: str,
    allowed_probes=(),
    notes=(),
) -> dict:
    """`binos-bridge-request-v1` hujjatini quradi va DARROV tekshiradi.

    ⚠️ Yozishdan OLDIN tekshiriladi: nosoz so'rov diskka umuman chiqmaydi.
    ⚠️ `allowed_probes` TARTIBLANGAN va TAKRORSIZ qilinadi (determinizm): bir xil ruxsat —
       AYNAN bir xil bayt.
    """
    _need(isinstance(identity, RunIdentity), bp.CODE_BRIDGE_SHAPE_INVALID,
          "identity `RunIdentity` bo'lishi kerak (`new_run` dan olinadi)")
    doc = {
        "request_version": REQUEST_VERSION,
        "run_id": identity.run_id,
        "nonce": identity.nonce,
        "requested_at": identity.requested_at,
        "output_dir": output_dir,
        "expected_collector": {"name": collector_name, "version": collector_version},
        "target_fingerprint": target_fingerprint,
        "mode": mode,
        "allowed_probes": sorted(set(allowed_probes)),
        "notes": list(notes),
    }
    validate_request(doc)
    return doc


def validate_request(req) -> dict:
    """So'rovni TO'LIQ tekshiradi (shakl + invariantlar). Nosoz bo'lsa — RAD."""
    _keys(req, REQUEST_KEYS, "request")
    _assert_no_json_numbers(req, "request")
    _need(req.get("request_version") == REQUEST_VERSION, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"request.request_version AYNAN {REQUEST_VERSION!r} bo'lishi kerak")
    _matched(req, "run_id", BRIDGE_RUN_ID_RE, "request", "yurish o'zligi")
    _matched(req, "nonce", NONCE_RE, "request", "kamida 32 hex belgi")
    _ts(req, "requested_at", "request")
    # ⚠️ `output_dir` — YO'L va u tekshirilmaydigan YAGONA maydon (`_notes` izohiga qarang):
    #    yig'uvchi qayerga yozishni bilishi kerak.
    _text(req, "output_dir", "request")
    _collector(req, "request")
    _matched(req, "target_fingerprint", FINGERPRINT_RE, "request", "sha256 (64 hex belgi)")
    mode = _text(req, "mode", "request")
    _need(mode in MODES, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"request.mode noma'lum: {mode!r}; ruxsat etilganlari {sorted(MODES)}")
    zondlar = req.get("allowed_probes")
    _need(isinstance(zondlar, list) and all(isinstance(x, str) for x in zondlar),
          bp.CODE_BRIDGE_SHAPE_INVALID, "request.allowed_probes matnlar ro'yxati bo'lsin")
    notanish = sorted(set(zondlar) - set(PROBE_CATALOG))
    _need(not notanish, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"request.allowed_probes da katalogda YO'Q zond(lar) {notanish} — ro'yxat "
          f"`discovery_1c.probe.PROBE_CATALOG` da, yangisi O'YLAB CHIQARILMAYDI")
    _need(list(zondlar) == sorted(set(zondlar)), bp.CODE_BRIDGE_SHAPE_INVALID,
          "request.allowed_probes TARTIBLANGAN va TAKRORSIZ bo'lishi kerak (determinizm)")
    # ⚠️ `METADATA_ONLY` + zond — O'Z-O'ZIGA ZID hujjat; yadrodagi `validate_probe_result`
    #    ham AYNI qoidani qo'yadi.
    _need(not (mode == MODE_METADATA_ONLY and zondlar), bp.CODE_BRIDGE_SHAPE_INVALID,
          f"request: {MODE_METADATA_ONLY} rejimida zond RUXSAT ETILMAYDI")
    _notes(req, "request")
    return req


# ══════════════════════════════════════════════════════════════════════════════════════════
# JAVOB va TUGALLANISH BELGISI
# ══════════════════════════════════════════════════════════════════════════════════════════
def validate_response(resp, *, request) -> dict:
    """Javobni so'rovga NISBATAN tekshiradi. HAR rad etish sababi — O'Z kodi bilan.

    Tekshiruv TARTIBI ataylab shunday:
      1. so'rovning O'ZI yaroqli (aks holda solishtirish ma'nosiz);
      2. javobning SHAKLI (`BRIDGE_SHAPE_INVALID`) — yo'q kalitni solishtirib bo'lmaydi;
      3. `run_id` (`STALE_OUTPUT`) — boshqa yurishning javobi versiya haqida hech nima
         aytmaydi, shu bois o'zlik AVVAL;
      4. `nonce` (`NONCE_MISMATCH`);
      5. yig'uvchi versiyasi (`WRONG_COLLECTOR_VERSION`);
      6. nishon xeshi (`TARGET_FINGERPRINT_MISMATCH`).
    """
    validate_request(request)
    _keys(resp, RESPONSE_KEYS, "response")
    _assert_no_json_numbers(resp, "response")
    _need(resp.get("response_version") == RESPONSE_VERSION, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"response.response_version AYNAN {RESPONSE_VERSION!r} bo'lishi kerak")
    _matched(resp, "run_id", BRIDGE_RUN_ID_RE, "response", "yurish o'zligi")
    _matched(resp, "nonce", NONCE_RE, "response", "kamida 32 hex belgi")
    _matched(resp, "target_fingerprint", FINGERPRINT_RE, "response", "sha256 (64 hex belgi)")
    holat = _text(resp, "status", "response")
    _need(holat in RESPONSE_STATUSES, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"response.status noma'lum: {holat!r}; ruxsat etilganlari "
          f"{sorted(RESPONSE_STATUSES)}")
    boshlandi = _ts(resp, "started_at", "response")
    tugadi = _ts(resp, "finished_at", "response")
    _need(tugadi >= boshlandi, bp.CODE_BRIDGE_SHAPE_INVALID,
          "response: tugash vaqti boshlanish vaqtidan OLDIN bo'lishi mumkin emas")
    name, version = _collector(resp, "response")
    _notes(resp, "response")

    _need(resp["run_id"] == request["run_id"], bp.CODE_STALE_OUTPUT,
          "response boshqa yurishga tegishli (yurish o'zligi mos emas) — eski javob "
          "bo'yicha xulosa chiqarilmaydi")
    _need(resp["nonce"] == request["nonce"], bp.CODE_NONCE_MISMATCH,
          "response shu yurishning bir martalik belgisiga mos emas")
    kutilgan_name, kutilgan_version = _collector(request, "request")
    _need((name, version) == (kutilgan_name, kutilgan_version),
          bp.CODE_WRONG_COLLECTOR_VERSION,
          "response: yig'uvchining nomi/versiyasi kutilganidan farq qiladi")
    _need(resp["target_fingerprint"] == request["target_fingerprint"],
          bp.CODE_TARGET_FINGERPRINT_MISMATCH,
          "response BOSHQA nishondan yig'ilgan (nishon xeshi mos emas)")
    return resp


def validate_done_marker(done, *, request) -> dict:
    """Tugallanish belgisini tekshiradi. Belgi YO'Q bo'lsa — `DONE_MARKER_MISSING`.

    ⚠️⚠️ `written_at < requested_at` — `OUTPUT_PREDATES_REQUEST`: chiqish so'rovdan OLDIN
         yozilgan bo'lsa, u shu yurishda yig'ilmagan. Bu darvoza AYNAN eski natijani qayta
         ishlatishni to'sadi va u `STALE_OUTPUT` dan AJRATILGAN: o'zlik mos kelsa ham
         (masalan papka qo'lda ko'chirilgan bo'lsa) VAQT mos kelmasligi mumkin.
    """
    validate_request(request)
    _need(done is not None, bp.CODE_DONE_MARKER_MISSING,
          f"{DONE_FILE} YO'Q — yig'uvchi ishini tugatganini bildirmadi, javob QABUL "
          f"QILINMAYDI")
    _keys(done, DONE_KEYS, "done")
    _assert_no_json_numbers(done, "done")
    _need(done.get("done_version") == DONE_VERSION, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"done.done_version AYNAN {DONE_VERSION!r} bo'lishi kerak")
    _matched(done, "run_id", BRIDGE_RUN_ID_RE, "done", "yurish o'zligi")
    _matched(done, "nonce", NONCE_RE, "done", "kamida 32 hex belgi")
    yozilgan = _ts(done, "written_at", "done")
    _need(done["run_id"] == request["run_id"], bp.CODE_STALE_OUTPUT,
          f"{DONE_FILE} boshqa yurishga tegishli (yurish o'zligi mos emas)")
    _need(done["nonce"] == request["nonce"], bp.CODE_NONCE_MISMATCH,
          f"{DONE_FILE} shu yurishning bir martalik belgisiga mos emas")
    sorovda = _ts(request, "requested_at", "request")
    _need(yozilgan >= sorovda, bp.CODE_OUTPUT_PREDATES_REQUEST,
          "chiqish so'rovdan OLDIN yozilgan — bu natija shu yurishda yig'ilmagan")
    return done


def validate_package_complete(present_files) -> tuple[str, ...]:
    """Paket TO'LIQMI: `runtime_bundle.REQUIRED_FILES` ning hammasi bormi.

    ⚠️ Majburiy fayl nomlari SHARTNOMADAN olinadi va bu yerda QAYTA YOZILMAYDI: ikkinchi
       ro'yxat bir kun birinchisidan ajralib ketardi.
    ⚠️ Xato matnida nomlar KO'RSATILADI — ular shartnoma, sir EMAS.
    """
    bor = {str(n) for n in present_files}
    yoq = tuple(n for n in REQUIRED_FILES if n not in bor)
    _need(not yoq, bp.CODE_PARTIAL_PACKAGE,
          f"paket TO'LIQ EMAS, yetishmaydigan fayl(lar): {', '.join(yoq)}")
    return REQUIRED_FILES


def accept_collector_output(*, request, response, done, bundle_files=()) -> Acceptance:
    """Yig'uvchi chiqishining YAGONA darvozasi: javob + belgi + paket to'liqligi.

    Rad etish sabablari va KODLARI (har biri ALOHIDA):
      · javob YO'Q                      -> `RESPONSE_MISSING`
      · shakl buzuq                     -> `BRIDGE_SHAPE_INVALID`
      · `run_id` mos emas               -> `STALE_OUTPUT`
      · `nonce` mos emas                -> `NONCE_MISMATCH`
      · yig'uvchi versiyasi mos emas    -> `WRONG_COLLECTOR_VERSION`
      · nishon mos emas                 -> `TARGET_FINGERPRINT_MISMATCH`
      · tugallanish belgisi YO'Q        -> `DONE_MARKER_MISSING`
      · chiqish so'rovdan OLDIN         -> `OUTPUT_PREDATES_REQUEST`
      · paket to'liq emas               -> `PARTIAL_PACKAGE`

    ⚠️ Paket to'liqligi FAQAT QUVURGA BORADIGAN javobda (`SUCCESS`, `PARTIAL`)
       tekshiriladi: yig'uvchi «yiqildim» deb aytgan bo'lsa, to'liq bo'lmagan paket SABAB
       emas, NATIJA — va operatorga ko'rsatiladigan kod ham boshqa bo'lishi kerak.
    ⚠️⚠️ `PARTIAL` ham `COLLECTOR_COMPLETE` fazasiga o'tadi, LEKIN u JIMGINA
         MUVAFFAQIYAT EMAS: `Acceptance.status` da AYNAN `PARTIAL` qoladi (chaqiruvchi uni
         operatorga ko'rsatadi) va hukmni QUVUR beradi — Phase 4 validatori kodi `2` ni
         hurmat qilib TO'XTAYDI. Ko'prik yarim natijani «tugadi» deb ATAMAYDI. Paket
         to'liqligi esa `PARTIAL` da ham TALAB QILINADI: yarim yozilgan paketni ingest
         qilish aynan Phase 4 da yolg'on SUCCESS bergan yo'l edi.
    ⚠️ `CANCELLED` — AYB EMAS, lekin COMPLETE ham emas: u `COLLECTOR_FAILED` fazasi bilan
       va `OPERATOR_CANCELLED` kodi bilan qaytadi. Ko'prik faza lug'atida «bekor qilindi»
       fazasi YO'Q, operator to'xtatishining HOLATI esa shu relizda e'lon qilingan-u,
       YOZILMAYDI — shu bois yangi faza ham, yangi holat ham QO'SHILMAYDI.
    """
    _need(response is not None, bp.CODE_RESPONSE_MISSING,
          f"{RESPONSE_FILE} YO'Q — yig'uvchi javob qoldirmadi")
    resp = validate_response(response, request=request)
    validate_done_marker(done, request=request)
    holat = resp["status"]
    if holat in (STATUS_SUCCESS, STATUS_PARTIAL):
        validate_package_complete(bundle_files)
        return Acceptance(status=holat, phase=bp.COLLECTOR_COMPLETE, code=None)
    if holat == STATUS_BRIDGE_REJECTED:
        # ⚠️ Razvedka BOSHLANMADI — sabab yig'uvchining `notes` ida. ALOHIDA kod, chunki
        #    «yiqildi» va «boshlanmadi» operator uchun ikki XIL vaziyat: birinchisida
        #    paketni ko'rish kerak, ikkinchisida yurishni qaytadan boshlash kerak.
        return Acceptance(status=STATUS_BRIDGE_REJECTED, phase=bp.COLLECTOR_FAILED,
                          code=bp.CODE_COLLECTOR_REJECTED_REQUEST)
    if holat == STATUS_CANCELLED:
        return Acceptance(status=STATUS_CANCELLED, phase=bp.COLLECTOR_FAILED,
                          code=bp.CODE_OPERATOR_CANCELLED)
    return Acceptance(status=STATUS_FAILED, phase=bp.COLLECTOR_FAILED, code=None)


# ══════════════════════════════════════════════════════════════════════════════════════════
# ISHGA TUSHIRISH DARVOZALARI (QAROR 5, 6)
# ══════════════════════════════════════════════════════════════════════════════════════════
def assert_launch_allowed(*, operator_confirmed: bool) -> None:
    """Agent 1C ni O'ZI ishga tushirishi — FAQAT operator aniq tasdig'i bilan.

    ⚠️⚠️ FAIL-CLOSED: tasdiq YO'Qligi ruxsat BERMAYDI
         (`COLLECTOR_EXECUTION_NOT_ALLOWED`). Sabab: bu yo'l haqiqiy 1C da HECH QACHON
         sinalmagan (`bridge_phase.AUTOMATIC_LAUNCH_VERIFICATION`), va sinalmagan yo'lni
         standart qilib qo'yish — operator so'ramagan xatarni uning nomidan qabul qilish.
    ⚠️ COM avtomatizatsiyasi QO'SHILMAYDI va o'ylab chiqarilgan buyruq satri parametri
       ham QO'SHILMAYDI: zaxira yo'l — operator yig'uvchini O'Z sessiyasida bajarishi.
    """
    _need(operator_confirmed is True, bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED,
          "avtomatik ishga tushirish operator tasdig'isiz BOSHLANMAYDI (bu yo'l haqiqiy "
          "1C da sinalmagan)")


def assert_launch_command(command) -> tuple[str, ...]:
    """Ishga tushirish buyrug'ining KREDENSIAL darvozasi (QAROR 5).

    ⚠️⚠️ PAROL DARVOZASI IKKINCHI NUSXADA YOZILMAYDI: mavjud
         `collector_bridge._assert_no_credentials` QAYTA ISHLATILADI. Ikki nusxa bir kun
         bir-biridan ajralib ketardi va «qaysi darvoza haqiqiy» degan savol tug'ilardi.
    ⚠️ Bu yerda QO'SHIMCHA, IJOBIY darvoza bor: nishon kaliti FAQAT `/F` yoki `/S`
       bo'lishi SHART va AYNAN bittasi bo'lishi kerak. Taqiqni sanash yetarli emas —
       ruxsat etilganni sanash kerak, aks holda ertaga paydo bo'lgan yangi kalit jimgina
       o'tib ketardi.
    ⚠️⚠️ HALOL QAYD: kredensial darvozasi `collector_bridge.BridgeError` tashlaydi, ya'ni
         uning istisnosida ko'prik KODI YO'Q — va bu ATAYLAB. Bu darvoza OPERATOR yo'li
         emas: hozir hech bir joy parol kalitini qo'shmaydi, u ishlab chiquvchi uchun
         tripwire («kimdir bir kun qo'shsa, KOD o'zi yiqiladi»). Istisnoni o'z kodimizga
         o'rash uni operator xatosiga aylantirardi va NUQSONNI yashirib qo'yardi.
    """
    _need(isinstance(command, (tuple, list)) and all(isinstance(t, str) for t in command),
          bp.CODE_BRIDGE_SHAPE_INVALID, "buyruq matnlar ketma-ketligi bo'lishi kerak")
    buyruq = tuple(command)
    _assert_no_credentials(buyruq)
    nishon = [t for t in buyruq
              if t.upper().startswith(ALLOWED_TARGET_SWITCHES[0])
              or t.upper().startswith(ALLOWED_TARGET_SWITCHES[1])]
    _need(len(nishon) == 1, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"buyruqda nishon kaliti AYNAN bitta bo'lishi kerak "
          f"({' yoki '.join(ALLOWED_TARGET_SWITCHES)}), topilgani: {len(nishon)} ta")
    return buyruq


# ══════════════════════════════════════════════════════════════════════════════════════════
# YURISH PAPKASI (QAROR 4)
# ══════════════════════════════════════════════════════════════════════════════════════════
def resolve_runs_root(*, runs_root=None) -> pathlib.Path:
    """Yurishlar ildizi: berilgan yo'l yoki `%LOCALAPPDATA%\\BinOS\\Discovery\\runs`.

    ⚠️⚠️ FAIL-CLOSED: muhit o'zgaruvchisi YO'Q bo'lsa — ISTISNO
         (`RUNS_ROOT_UNKNOWN`), joriy papkaga yoki manba daraxtiga ZAXIRA YO'Q.
         Sabab: o'zgaruvchi yo'qligi HECH QACHON ruxsat bermasin — aks holda agent
         repo ichiga yoza boshlardi va natija tasodifan commit qilinardi.
    """
    if runs_root is not None:
        return pathlib.Path(runs_root)
    baza = os.environ.get(LOCALAPPDATA_ENV)
    _need(isinstance(baza, str) and baza.strip() != "", bp.CODE_RUNS_ROOT_UNKNOWN,
          f"{LOCALAPPDATA_ENV} muhit o'zgaruvchisi yo'q yoki bo'sh — yurish papkasini "
          f"operator {RUNS_DIR_OPTION} bilan ko'rsatishi kerak (taxmin QILINMAYDI)")
    return pathlib.Path(baza).joinpath(*RUNS_SUBPATH)


def run_dir_for(run_id: str, *, runs_root=None) -> pathlib.Path:
    """Shu yurishning papkasi: `<ildiz>/<run_id>` (hech narsa yaratilmaydi).

    ⚠️ `run_id` shakli papka nomiga tushishdan OLDIN tekshiriladi: yo'l belgisi yoki
       `..` bo'lgan qiymat papkadan CHIQIB ketardi.
    """
    _matched({"run_id": run_id}, "run_id", BRIDGE_RUN_ID_RE, "run_dir", "yurish o'zligi")
    return resolve_runs_root(runs_root=runs_root) / run_id


def prepare_run_dir(run_id: str, *, runs_root=None) -> pathlib.Path:
    """FAQAT O'Z yurish papkasini yaratadi va uning BO'SH ekanini talab qiladi.

    ⚠️⚠️ HECH NARSA O'CHIRILMAYDI. Papka mavjud va bo'sh BO'LMASA — `RUN_DIR_NOT_EMPTY` va
         TO'XTASH. Avtomatik tozalash («avval papkani bo'shataman») — eng xavfli naqsh:
         bir kun noto'g'ri papka berilsa, u operatorning fayllarini olib ketardi. Shu bois
         bu modulda wildcard bo'yicha ham, yolg'iz fayl bo'yicha ham o'chirish YO'Q (statik
         test bilan qulflangan).
    ⚠️ Ota papkalar yaratiladi (ildiz hali bo'lmasligi mumkin), lekin BEGONA faylga
       tegilmaydi va umumiy global natija fayli YARATILMAYDI: har yurish o'z papkasida.
    """
    d = run_dir_for(run_id, runs_root=runs_root)
    d.mkdir(parents=True, exist_ok=True)
    band = sorted(p.name for p in d.iterdir())
    _need(not band, bp.CODE_RUN_DIR_NOT_EMPTY,
          f"yurish papkasi BO'SH EMAS ({len(band)} ta a'zo) — agent unga yozmaydi va "
          f"ichidagini O'CHIRMAYDI")
    return d


def request_path(run_dir) -> pathlib.Path:
    """`request.json` ning yo'li."""
    return pathlib.Path(run_dir) / REQUEST_FILE


def response_path(run_dir) -> pathlib.Path:
    """`response.json` ning yo'li."""
    return pathlib.Path(run_dir) / RESPONSE_FILE


def done_marker_path(run_dir) -> pathlib.Path:
    """`bridge_done.json` ning yo'li."""
    return pathlib.Path(run_dir) / DONE_FILE


def cancel_marker_path(run_dir) -> pathlib.Path:
    """Kooperativ bekor qilish belgisining yo'li.

    ⚠️ HALOL QAYD: bu FAYLNI yozadigan kod shu relizda YO'Q — nom shartnoma sifatida
       qotirilgan (`CANCEL_FILE` izohiga qarang). Agent tomonidagi bekor qilish esa
       `launcher.CancelToken` bilan ishlaydi va u faylga EMAS, xotiraga yoziladi — shu
       bois yurish papkasida TO'RTINCHI hujjat paydo bo'lmaydi.
    ⚠️ Jarayonni majburan tugatish HECH QACHON qo'shilmaydi.
    """
    return pathlib.Path(run_dir) / CANCEL_FILE


# ══════════════════════════════════════════════════════════════════════════════════════════
# O'QISH / YOZISH — UTF-8 va DETERMINISTIK
# ══════════════════════════════════════════════════════════════════════════════════════════
def dump_request(req) -> str:
    """So'rovning DETERMINISTIK matni (tekshiruvdan o'tmasa — RAD).

    ⚠️ `bundle.dumps` QAYTA ISHLATILADI: ikkinchi serializator bir kun boshqa bayt
       berardi va xesh solishtirish ma'nosini yo'qotardi.
    """
    validate_request(req)
    return dumps(req)


def write_request(run_dir, req) -> pathlib.Path:
    """So'rovni yurish papkasiga UTF-8 (BOM'SIZ) bo'lib yozadi.

    ⚠️ Tekshiruv YOZISHDAN OLDIN (`dump_request`): nosoz hujjat diskka chiqmaydi.
    ⚠️ Mavjud fayl ALMASHTIRILMAYDI: papka bo'sh bo'lishi SHART (`prepare_run_dir`), shu
       bois bu yerda `x` rejimi — tasodifan boshqa yurishning so'rovi ustiga yozilmaydi.
    ⚠️ `newline="\\n"`: Windows'da `\\r\\n` ga aylanib ketsa baytlar o'zgarib, determinizm
       buzilardi.
    """
    matn = dump_request(req)
    p = request_path(run_dir)
    with open(p, "x", encoding="utf-8", newline="\n") as f:
        f.write(matn)
    return p


def _read_json(path):
    """Yo'q bo'lsa `None`, buzuq bo'lsa — `BRIDGE_SHAPE_INVALID`.

    ⚠️⚠️ `utf-8-sig` ATAYLAB: 1C ning o'zi JSON ni ko'pincha BOM bilan yozadi, BOM esa
         `utf-8` o'qishda birinchi kalitni buzadi va hujjat «noma'lum kalit» bilan rad
         etilardi — ya'ni yig'uvchi to'g'ri ishlasa ham natija yo'qolardi. YOZISHDA esa
         BOM QO'YILMAYDI (`write_request`): BOM determinizmni buzadi.
    ⚠️ Xato matnida FAYL NOMI bor, YO'L esa YO'Q: yo'l sir bo'lishi mumkin.
    """
    p = pathlib.Path(path)
    try:
        xom = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as e:
        # ⚠️ Istisno MATNI ko'chirilmaydi — unda yo'l bo'ladi. Faqat TURI yoziladi.
        raise _reject(bp.CODE_BRIDGE_SHAPE_INVALID,
                      f"{p.name} o'qilmadi: {type(e).__name__}") from e
    try:
        return json.loads(xom)
    except ValueError as e:
        raise _reject(bp.CODE_BRIDGE_SHAPE_INVALID,
                      f"{p.name} yaroqli JSON emas") from e


def read_response(run_dir):
    """`response.json` (yo'q bo'lsa `None` — rad etish kodi CHAQIRUVCHIDA)."""
    return _read_json(response_path(run_dir))


def read_done_marker(run_dir):
    """`bridge_done.json` (yo'q bo'lsa `None`).

    ⚠️ «Yo'q» va «buzuq» AJRATILGAN: yo'qligi `DONE_MARKER_MISSING` (yig'uvchi tugatmagan),
       buzuqligi `BRIDGE_SHAPE_INVALID` (fayl bor, lekin o'qilmaydi) — operatorning qadami
       ikkisida boshqa.
    """
    return _read_json(done_marker_path(run_dir))


# ══════════════════════════════════════════════════════════════════════════════════════════
# IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI
# ══════════════════════════════════════════════════════════════════════════════════════════
assert REQUEST_VERSION == "binos-bridge-request-v1", "so'rov sxemasining nomi SHARTNOMA"
assert RESPONSE_VERSION == "binos-bridge-response-v1", "javob sxemasining nomi SHARTNOMA"
assert DONE_VERSION == "binos-bridge-done-v1", "tugallanish sxemasining nomi SHARTNOMA"
assert len(REQUEST_KEYS) == 10 and len(RESPONSE_KEYS) == 9 and len(DONE_KEYS) == 4, \
    "ko'prik hujjatlarining kalit soni SHARTNOMA — yangi maydon faqat versiya oshganda"
assert len({REQUEST_FILE, RESPONSE_FILE, DONE_FILE, CANCEL_FILE}) == 4, \
    "ko'prik fayllari BOSHQA-BOSHQA nomda: bir xil nom + ikki xil sxema Phase 4 ni yiqitgan"
assert DONE_FILE not in REQUIRED_FILES, \
    "ko'prik belgisi Phase 4 paketining majburiy fayllari bilan ARALASHMAYDI"
assert set(RESPONSE_STATUSES) == {STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED,
                                 STATUS_CANCELLED, STATUS_BRIDGE_REJECTED} \
    and len(RESPONSE_STATUSES) == 5, \
    "javob holatlari lug'ati YOPIQ va TAKRORSIZ"
assert (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED) == (OVERALL_SUCCESS, OVERALL_PARTIAL,
                                                           OVERALL_FAILED), \
    "javob holatlari YADRONING `runtime_bundle.OVERALL_*` qiymatlaridan OLINADI — ikkinchi " \
    "lug'at yozilsa yig'uvchining `SUCCESS` i yana rad etilardi (P0 nuqsonning o'zi)"
assert STATUS_OK == STATUS_SUCCESS, \
    "`STATUS_OK` — ESKIRGAN NOM va u `STATUS_SUCCESS` ning AYNAN O'ZI: qiymat IKKI xil " \
    "bo'lsa `OK`/`SUCCESS` nomuvofiqligi qaytardi"
assert "OK" not in RESPONSE_STATUSES, \
    "`OK` QIYMATI lug'atdan OLIB TASHLANGAN: u `SUCCESS` ning dublikati edi"
assert STATUS_CANCELLED not in (OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED), \
    "`CANCELLED` — ko'prikka XOS qiymat: Phase 4 da bekor qilish tushunchasi YO'Q"
assert BRIDGE_RUN_ID_RE.fullmatch("0" * (RUN_ID_BYTES * 2)) is not None, \
    "`BRIDGE_RUN_ID_RE` `token_hex(RUN_ID_BYTES)` chiqishini qabul qilishi SHART"
assert BRIDGE_RUN_ID_RE.fullmatch("0" * (RUN_ID_BYTES * 2 - 1)) is None, \
    "ko'prik `run_id` i AYNAN uzunlikda bo'lishi SHART — qisqa qiymat RAD etiladi"
assert RUN_ID_RE.fullmatch("0" * (RUN_ID_BYTES * 2)) is not None, \
    "ko'prik shakli umumiy `status.RUN_ID_RE` ga ZID bo'lmasligi SHART (u papka nomiga tushadi)"
assert NONCE_BYTES * 2 >= 32, "nonce kamida 32 hex belgi bo'lishi SHART"
assert NONCE_RE.fullmatch("0" * (NONCE_BYTES * 2)) is not None, \
    "NONCE_RE `token_hex(NONCE_BYTES)` chiqishini qabul qilmayapti"
assert ALLOWED_TARGET_SWITCHES == ("/F", "/S"), \
    "ishga tushirishda FAQAT fayl (/F) yoki server (/S) nishoni — boshqa kalit YO'Q"
