# -*- coding: utf-8 -*-
"""MINIMAL OPERATOR OYNASI (tkinter) — bitta oyna, bitta tugma.

Ko'rinadigan narsalar brief bo'yicha AYNAN shular:
    · aniqlangan 1C          · nishon infobaza        · READ ONLY holati
    · «Start Discovery»      · progress (holat nomi)
    · «Open Report»          · «Open Result Folder»

⚠️⚠️ BUNGA USTIGA IKKI QATOR QO'SHILGAN va ikkisi ham HAQQONIYLIK uchun (bezak emas):
     · YO'L QATORI (`route_line`) + OPERATOR QADAMLARI (`operator_steps`) — brief §7.
       `watch_folder` yo'lida yig'uvchini OPERATOR ishga tushiradi, demak ekran «bitta
       bosishda avtomatik razvedka» taassurotini BERMASLIGI kerak. Qator buni AYNAN aytadi
       va matnlar ko'prikdan keladi (yurish yozuvidagi `notes` bilan AYNI).
     · KUTISH QATORI (`wait_line`) — brief §6C. Kuzatiladigan papka hali bo'sh bo'lsa agent
       KUTADI; qator yangilanib turmasa operator oynani «osilgan» deb o'qirdi. Kutish YANGI
       HOLAT YARATMAYDI — u `METADATA_DISCOVERY` ichida bo'ladi va progress holat nomi bo'lib
       qoladi (parallel semantik lug'at TAQIQ).

⚠️⚠️ UI MANTIQNI O'Z ICHIGA OLMAYDI — u faqat QADAMLAR TARTIBINI biladi. Hamma QAROR boshqa
     modullarda:
       muhit skaneri   -> `detector.scan_environment`     (1C bormi, qaysi bazalar)
       paket QAYERDAN  -> `collector_bridge.preflight` / `collect`  (ikki yo'l, bitta chiqish)
       quvur           -> `pipeline.run_pipeline`         (validatsiya, graf, analitik)
       hisobot         -> `report.build_report`
       natija paketi   -> `result_package` (qurish, manifest va TEKSHIRISH)
     Shu bois butun xulq UI SIZ ham sinaladi: `UiModel` tkinter'ga TEGMAYDI va testlar uni
     to'g'ridan-to'g'ri chaqiradi. Vidjetlar esa faqat `UiModel` ni ko'rsatadi.

⚠️ ULAGICH NIMA QILADI (va faqat shuni): (1) `START`..`METADATA_DISCOVERY` o'tishlarini
   qo'yadi — quvur ulardan OLDINGI qadamlarni ATAYLAB o'ylab chiqarmaydi (`run_pipeline`
   docstringi); (2) ko'prikning `state_hint` ini `collector_bridge.HINT_SOURCE_STATE` aytgan
   HOLATDAN yozadi, chunki `states.TRANSITIONS` har bir yiqilishni faqat o'z joyidan ruxsat
   etadi; (3) artefakt baytlarini bir joyga yig'ib, natija papkasini YAKUNLAYDI.

⚠️ `tkinter` IMPORTI HIMOYALANGAN: CI Linux'da yuradi va u yerda `tkinter` bo'lmasligi
   mumkin. Modul BARIBIR import qilinadi, `TK_MAVJUD` esa `False` bo'ladi — oyna ochishga
   urinishda ANIQ xato beriladi («jimgina ishlamaslik» YO'Q).

⚠️ VIZUAL JILVA YO'Q (brief: Reliability > appearance): stil, ikonka, animatsiya va
   moslashuvchan tartib ATAYLAB yozilmagan. Bu bo'shliq emas — tanlov.

⚠️ BITTA IP (thread YO'Q): «Start Discovery» quvurni AYNI ipda yuritadi va oyna shu vaqtda
   band bo'ladi. Sabab: tkinter vidjetlarini boshqa ipdan o'zgartirish — nodeterministik
   yiqilishlarning klassik manbai, ishonchlilik esa ko'rinishdan ustun. Operator uzun
   yurishda oynaning «band» bo'lishini ko'radi va bu OCHIQ yoziladi.

QAT'IY CHEGARALAR (buzilishi = nuqson):
  · FAQAT O'QISH: bu modul 1C ga ulanmaydi, hech narsa bajarmaydi, biznes qatorini
    o'zgartirmaydi. U faqat boshqa modullarni CHAQIRADI va natijani ko'rsatadi.
  · YASHIRIN SAQLASH YO'Q: avtoyuklanish yo'q, reestrga yozish yo'q, xizmat o'rnatish yo'q,
    yashirin vaqtinchalik fayl yo'q. Faqat OPERATOR BERGAN papkaga yoziladi.
  · TARMOQ YO'Q: `socket`/`requests`/`urllib`/`http.client` importi YO'Q.
  · TASHQI KUTUBXONA YO'Q: faqat stdlib + `tkinter`.
  · KREDENSIAL YO'Q: oynada parol maydoni YO'Q va bo'lmaydi. Baza parol so'rasa quvur
    `FAILED_AUTH_REQUIRED` ga o'tadi va `watch_folder` yo'lini taklif qiladi.
  · MAHALLIY YO'L EKRANGA chiqmaydi: infobaza faqat NOMI bilan ko'rsatiladi (fayl bazasining
    `locator` i — mahalliy yo'l, u sir deb hisoblanadi).

⚠️ `os.startfile` ATAYLAB ISHLATILADI va u «ixtiyoriy dastur ishga tushirish» EMAS:
   (1) faqat OPERATOR tugmani bosganda chaqiriladi, (2) faqat AGENTNING O'ZI yozgan natija
   papkasi ICHIDAGI yo'l uzatiladi (`_natija_ichida` darvozasi), (3) chaqiruvchi
   almashtirilishi mumkin (`opener`), shu bois testlar hech narsa ochmaydi.

⚠️ 1C bu mashinada YO'Q (`1cv8.exe` yo'q, COM klassi ro'yxatda yo'q), shu bois «Start
   Discovery» ning 1C bilan ishlaydigan qismi `RUNTIME-UNKNOWN`. UI ning O'ZI esa to'liq
   sinaladi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable

from . import (AGENT_NAME, AGENT_STATUS_FILE, AGENT_VERSION, AI_CANDIDATES_FILE,
               ENVIRONMENT_FILE, ERRORS_FILE, REPORT_FILE, ROUTE_BATCH_EXECUTE,
               ROUTE_WATCH_FOLDER)
from . import collector_bridge as bridge
from . import detector as det
from . import pipeline as pipe
from . import report as reporter
from . import result_package as rp
from . import states as st
from . import status as agent_status
from ..discovery_1c import redact as redaction
from ..discovery_1c.runtime_bundle import MODE_METADATA_ONLY

# ⚠️ HIMOYALANGAN IMPORT: `tkinter` yo'q muhitda ham bu modul IMPORT QILINADI.
#    `ImportError` dan kengroq tutiladi: ba'zi yig'malarda `tkinter` bor, lekin ichki
#    `_tkinter` kengaytmasi yo'q va import boshqa istisno beradi.
try:  # pragma: no cover - muhitga bog'liq shox
    import tkinter as tk
    from tkinter import filedialog, messagebox
    TK_MAVJUD = True
except Exception:  # pragma: no cover - tkinter yo'q muhit
    tk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    TK_MAVJUD = False

#: Oyna sarlavhasi.
WINDOW_TITLE = f"{AGENT_NAME} {AGENT_VERSION}"

#: `READ ONLY` yorlig'i — DOIM shu matn. ⚠️ Uni o'zgartiradigan yo'l YO'Q: yozadigan agent
#: mavjud emas va bo'lishi ham mumkin emas.
READ_ONLY_LABEL = "READ ONLY — agent faqat O'QIYDI (yozish yo'li YO'Q)"

#: Xato kodlari — BARQAROR, mashina o'qiydigan belgilar (`agent_status.errors[].code` shakli).
#: ⚠️ `scope` bu qatlamni ko'rsatadi: hisobotni o'qigan odam nuqson QAYSI qatlamda
#:    bo'lganini bilishi kerak (muhit skaneri, ko'prik, quvur yoki ULAGICH).
SCOPE_UI = "agent:ui"
SCOPE_ENVIRONMENT = "agent:environment"
#: ⚠️ KO'PRIKDAN OLINADI, qayta yozilmaydi: kuzatish yo'lining `scope` i va «papka yo'q»
#: kodi endi KO'PRIKNING shartnomasi (darvoza ham u yerda). Ikki nusxa bir kun ajralib
#: ketardi va `agent_status.json` da bir xil holat ikki xil kod bilan yozilib qolardi.
SCOPE_WATCH = bridge.SCOPE_WATCH
CODE_BUNDLE_DIR_MISSING = bridge.CODE_BUNDLE_DIR_MISSING
CODE_PAKET_RAD = "RESULT_PACKAGE_REJECTED"
CODE_PAKET_YOZILMADI = "RESULT_PACKAGE_WRITE_FAILED"
CODE_ICHKI_XATO = "AGENT_INTERNAL_ERROR"
#: ⚠️⚠️ CHIQISHDA SIR TOPILDI va BUTUN paket USHLAB QOLINDI. Kod yozuvga ham tushadi
#:    (`agent_status.errors` -> hosila `errors.json`), chunki sir ANIQLANGANI faktining
#:    O'ZI operatorga kerak: usiz u «nega paketda `bundle/` yo'q» degan savol bilan qoladi.
#:    ⚠️ QIYMAT HECH QAYERGA YOZILMAYDI — faqat QAYSI artefaktda topilgani.
CODE_SIR_USHLANDI = "SECRET_FOUND_PACKAGE_HELD"
#: ⚠️ To'liq hisobot O'Z darvozasidan (shakl + sir + yo'l haqqoniyligi) o'tmadi va hisobot
#:    YURISH YOZUVIDAN qayta qurildi. Bu JIM qisqartirish EMAS: sabab yozuvga tushadi.
CODE_HISOBOT_QISQARTIRILDI = "REPORT_REBUILT_FROM_RECORD"
#: ⚠️⚠️ ZAHIRA hisobot HAM darvozadan o'tmadi — oxirgi chora: MINIMAL matn yoziladi.
#:    NEGA ISTISNO TASHLAMAYMIZ: zahira hisobotning istisnosi `start()` ning umumiy `except`
#:    iga tushib yurishni `FAILED_INTERNAL` ga aylantirardi (va `_ichki_xato` ning O'ZI yana
#:    AYNI hisobotni qurishga urinardi) — ya'ni bitta matn butun yurishning hukmini
#:    almashtirardi. Degradatsiya esa JIM EMAS: kod yozuvga tushadi.
CODE_HISOBOT_DEGRADATSIYA = "REPORT_DEGRADED_TO_MINIMAL"

#: ⚠️ Sir ushlangan paketning yozuvidagi IZOH. Ekrandagi hukm (`FAILED_REPORT`) bilan
#: yozuvdagi holat (yurishning O'Z holati) FARQ QILISHI mumkin, va bu farq YASHIRILMAYDI:
#: yakunlangan yurish qayta tirilmaydi (`states` shartnomasi), shu bois UI o'z hukmini
#: yozuvning holatiga YOZMAYDI, balki shu izohda OCHIQ aytadi.
SIR_USHLANDI_IZOH = (
    "Chiqishda shubhali qiymat topildi, shu bois BUTUN natija paketi USHLAB QOLINDI va "
    "operatorga faqat MINIMAL, sirsiz paket qoldi: Phase 4 paketi (`bundle/`) ham, "
    "analitik nomzodlari ham YOZILMADI, hisobot esa shu yurish yozuvidan QAYTA QURILDI. "
    "UI bu yurishni `FAILED_REPORT` deb ko'rsatadi (chiqish yozilmadi), yozuvdagi holat esa "
    "yurishning O'Z holati bo'lib qoladi — yakunlangan yurish qayta tirilmaydi. Keyingi "
    "qadam: sir topilgan artefaktni ishlab chiquvchi bilan birga, PAKETSIZ ko'rib chiqing."
)


class UiError(RuntimeError):
    """Oynani ocha olmaslik yoki UI qatlamining shartnoma buzilishi."""


def utc_now() -> str:
    """Hozirgi UTC vaqt (ISO 8601, sekundlargacha).

    ⚠️ SOATNI FAQAT KIRISH NUQTASI O'QIYDI. Qolgan modullar (`status`, `result_package`)
       vaqtni KIRISHDAN oladi — shu tufayli ular deterministik va to'liq sinaladi. UI va
       `__main__` — kirish nuqtalari, demak soat shu yerda, BITTA joyda yashaydi.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def xavfsiz_matn(matn: str) -> str:
    """Tashqi matnni ekranga chiqarishdan oldin niqoblash.

    ⚠️ NEGA: quvurdan kelgan istisno matnida 1C ning xato tavsifi (fayl yo'li, server nomi,
       hatto ulanish satri) bo'lishi mumkin, va bu matn ekrandan jurnalga, jurnaldan esa
       xabar almashinuviga ko'chadi.
    """
    return redaction.redact(str(matn))


# ══════════════════════════════════════════════════════════════════════════════════════════
# QATLAMLARNI ULASH (mantiq EMAS — TARTIB)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Muhit skanidan keyin yuriladigan QADAMLAR, shu tartibda. ⚠️ Tartib `states.TRANSITIONS`
#: bilan AYNI bo'lishi SHART — import paytida tekshiriladi (fayl oxiriga qarang).
PRE_PIPELINE_CHAIN: tuple[str, ...] = (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION,
                                      st.SAFETY_CHECK, st.METADATA_DISCOVERY)


def _error_code(code: str) -> str:
    """Boshqa modulning xato kodini `agent_status` shakliga keltiradi.

    ⚠️⚠️ TOPILGAN MOSLIKSIZLIK (bu yerda yopiladi, lekin YASHIRILMAYDI):
         `status.ERROR_CODE_RE` xato kodini `[A-Z][A-Z0-9_]+` deb talab qiladi va
         `collector_bridge` AYNI shunday yozadi (`EPF_MISSING`), `detector` esa KICHIK
         harflarda yozadi (`registry_unreadable`) — holbuki uning `Unreadable.as_error()`
         docstringi aynan `agent_status.errors` ga ko'chishni ko'rsatadi. Ya'ni muhit
         skanerining xatosi yurish yozuviga XOM holda tushsa, yozuv validatordan O'TMAYDI
         va BUTUN natija paketi rad etilardi.
         Bu qatlam kodni KATTA harfga keltiradi (`upper()`), chunki `detector.py` ham,
         `status.py` ham bu qatlamning fayli EMAS va ularning shartnomasini bir tomonlama
         o'zgartirish Phase 4 ni yiqitgan xatoning aynan o'zi bo'lardi. Mosliksizlikning
         O'ZI ishlab chiquvchiga ochiq xabar qilinadi; `upper()` esa allaqachon KATTA
         harfli kodni O'ZGARTIRMAYDI, shu bois `detector` tuzatilganda bu yerda hech narsa
         buzilmaydi.
    """
    return str(code).upper()


# ══════════════════════════════════════════════════════════════════════════════════════════
# NATIJA
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class RunOutcome:
    """Bitta yurishning UI uchun qisqa natijasi.

    ⚠️ `state` HAQIQIY manbadan: yurish tugagach u `agent_status.json` dan O'QILADI, UI
       o'zidan «COMPLETE» deb YOZMAYDI. Aks holda UI quvurdan ko'proq narsa da'vo qilardi.
    """

    state: str
    result_dir: str | None
    detail: str
    code: str | None = None
    problems: tuple[str, ...] = ()

    @property
    def is_failure(self) -> bool:
        return st.is_failure(self.state) if st.is_known(self.state) else True


@dataclass
class UiModel:
    """UI ning MANTIQSIZ qobig'i: boshqa modullarni chaqiradi va natijani SAQLAYDI.

    ⚠️ Bu sinf tkinter'ga TEGMAYDI va shu bois tkinter'siz muhitda ham to'liq sinaladi.
    ⚠️ Hamma tashqi bog'liqlik ALMASHTIRILADI (`scan`, `runner`, `opener`, `now`): testlar
       haqiqiy reestrni o'qimaydi, hech narsa ochmaydi va soatga qaramaydi.
    ⚠️ FROZEN EMAS va bu ATAYLAB: bu obyekt oynaning JORIY holati (tanlangan nishon,
       progress, oxirgi natija), ya'ni uning vazifasi — o'zgarish. Loyihaning frozen
       qoidasi YOZUVLARGA tegishli va u saqlanadi: yurish yozuvi (`status.AgentStatus`) va
       yurish natijasi (`RunOutcome`) — O'ZGARMAS.
    """

    #: Natija papkasi QAYERGA quriladi. ⚠️ Faqat OPERATOR bergan papka.
    parent_dir: str
    #: TAYYOR Phase 4 paketining papkasi — operator yig'uvchini O'ZI yurgizgan holat
    #: (`watch_folder` natijasi). ⚠️ `epf_path` berilmasa YAGONA yo'l shu.
    bundle_dir: str | None = None
    #: Yig'uvchi `.epf` fayli. ⚠️ Berilsa ko'prik (`collector_bridge`) chaqiriladi va u
    #: `batch_execute` dan boshlaydi. Repoda `.epf` konteyneri HOZIR YO'Q — shu bois amalda
    #: bu yo'l `EPF_MISSING` bilan to'xtaydi (`AGENT_INTEGRATION_MATRIX.md`, «BSL BO'SHLIG'I»).
    epf_path: str | None = None
    #: Yig'uvchi yozadigan BO'SH papka (ko'prik talabi: bo'sh bo'lmasa `FAILED_SAFETY`).
    output_dir: str | None = None
    mode: str = MODE_METADATA_ONLY
    scan: Callable[[], det.EnvironmentScan] = det.scan_environment
    #: 1C ni ishga tushiruvchi (`collector_bridge.Runner`). ⚠️ Testda almashtiriladi —
    #: HAQIQIY `1cv8.exe` hech qachon ishga tushmaydi (u bu mashinada yo'q ham).
    runner: Callable | None = None
    #: Monoton soat — ko'prikning kutish mantiqi uchun (`collector_bridge` o'zi olmaydi).
    clock: Callable[[], float] = bridge.DEFAULT_CLOCK
    sleeper: Callable[[float], None] = bridge.DEFAULT_SLEEPER
    #: ⚠️ KUTISH CHEGARASI — KIRISHDAN va CHEKLI. Papka bo'sh bo'lsa agent shu vaqt ichida
    #: yig'uvchining chiqishini kutadi, so'ng `FAILED_TIMEOUT` bilan to'xtaydi. Cheksiz
    #: kutish YO'Q (brief §6C): osilgan 1C sessiyasi agentni butun kechaga qoldirardi.
    watch_timeout_seconds: float = bridge.DEFAULT_TIMEOUT_SECONDS
    watch_poll_seconds: float = bridge.DEFAULT_POLL_SECONDS
    #: Analitik. ⚠️ `None` — DETERMINISTIK lokal evristika: offline-first MAJBURIY.
    analyzer: object | None = None
    opener: Callable[[str], None] | None = None
    now: Callable[[], str] = utc_now
    on_progress: Callable[[str], None] | None = None
    #: ⚠️ KUTISH KO'RINADI: ko'prik har «hali tayyor emas» o'lchovida shu chaqiruvni yuboradi
    #: (`collector_bridge.WaitTick`). Progress HOLAT NOMI bo'lib qoladi — kutish yangi HOLAT
    #: yaratmaydi (yangi parallel lug'at TAQIQ), u `METADATA_DISCOVERY` ichida bo'ladi.
    on_wait: Callable[[bridge.WaitTick], None] | None = None

    environment: det.EnvironmentScan | None = None
    #: Necha marta «hali tayyor emas» deb o'lchandi (0 — kutilmadi).
    waiting_ticks: int = 0
    _oxirgi_kutish: object | None = None
    #: ⚠️ ENG OXIRGI HAQIQIY yurish yozuvi — kutilmagan istisnodan keyin ham natija papkasi
    #: yozilishi uchun saqlanadi (`_ichki_xato`). U YOZUVNI o'ylab chiqarmaydi, faqat
    #: oxirgi muvaffaqiyatli o'tishni eslab qoladi.
    _oxirgi_yozuv: object | None = None
    #: ⚠️⚠️ KO'PRIK BERGAN Phase 4 PAKETINING papkasi — kutilmagan istisnodan keyin ham
    #: paket ICHIGA ko'chirilishi uchun eslab qolinadi (`_ichki_xato`). U TAXMIN EMAS:
    #: qiymat faqat `_collect` MUVAFFAQIYATLI tugagach yoziladi, ya'ni papka ko'prikning
    #: tayyorlik isbotidan ALLAQACHON o'tgan. Usiz ichki xato yo'li o'qilgan paketni
    #: JIMGINA tashlardi va yozuvdagi `bundle_dir` da'vosi ham yo'qolardi.
    _oxirgi_paket_papkasi: str | None = None
    selected_index: int | None = None
    last: RunOutcome | None = None
    progress: str = st.START
    notes: list[str] = field(default_factory=list)

    # ── Muhit ─────────────────────────────────────────────────────────────────────────────
    def refresh_environment(self) -> det.EnvironmentScan:
        """Muhitni qayta skanerlaydi (FAQAT O'QISH) va natijani saqlaydi.

        ⚠️ Bu KO'RSATISH uchun ham chaqiriladi (oyna ochilganda), shu bois u progress
           hodisasini YUBORMAYDI: progress — YURISHNING holati, oynaning yangilanishi emas.
        """
        self.environment = self.scan()
        # ⚠️ Nishon O'ZI tanlanmaydi: birinchi baza faqat TAKLIF sifatida belgilanadi va
        #    operator uni o'zgartira oladi. Baza bo'lmasa — hech narsa tanlanmaydi.
        #    ⚠️ OPERATOR TANLOVI USTIDAN YOZILMAYDI: agar u allaqachon yaroqli bazani
        #       tanlagan bo'lsa, qayta skanerlash tanlovni birinchi bazaga qaytarmaydi.
        soni = len(self.environment.infobases)
        if self.selected_index is None or not (0 <= self.selected_index < soni):
            self.selected_index = 0 if soni else None
        return self.environment

    def install_line(self) -> str:
        """«Aniqlangan 1C» qatori. ⚠️ Mahalliy YO'L ko'rsatilmaydi (u sir)."""
        env = self.environment
        if env is None:
            return "1C: hali skanerlanmadi"
        if env.presence_verdict == det.PRESENCE_UNKNOWN:
            return ("1C: NOMA'LUM — manbalardan biri O'QILMADI, «1C yo'q» xulosasi HAQLI "
                    "EMAS (huquqni tekshiring)")
        if env.presence_verdict == det.PRESENCE_ABSENT:
            return "1C: O'RNATILMAGAN (hamma manba o'qildi va bo'sh chiqdi)"
        eng = env.newest_install()
        versiya = (eng.version if eng and eng.version else "versiyasi noma'lum")
        return (f"1C: topildi — {len(env.installs)} o'rnatma, eng yangisi {versiya} "
                f"(COM ro'yxati: {env.com_registered})")

    def target_labels(self) -> list[str]:
        """Nishon ro'yxati — faqat NOM, TUR va autentifikatsiya talabi.

        ⚠️ `locator` EKRANGA CHIQMAYDI: fayl bazasining `locator` i mahalliy yo'l va u sir
           deb hisoblanadi (`detector` modul docstringi).
        """
        env = self.environment
        if env is None:
            return []
        out = []
        for ib in env.infobases:
            nom = ib.name or "(nomsiz baza)"
            out.append(f"{nom} · {ib.kind} · parol kerakmi: {ib.requires_auth}")
        return out

    def target_line(self) -> str:
        """«Nishon infobaza» qatori."""
        yorliqlar = self.target_labels()
        if not yorliqlar:
            return "Nishon: baza topilmadi (1C ni bir marta qo'lda ochib ro'yxatga qo'shing)"
        if self.selected_index is None or not (0 <= self.selected_index < len(yorliqlar)):
            return "Nishon: tanlanmadi"
        return f"Nishon: {yorliqlar[self.selected_index]}"

    def select_target(self, index: int) -> None:
        yorliqlar = self.target_labels()
        if not (isinstance(index, int) and 0 <= index < len(yorliqlar)):
            raise UiError(f"nishon raqami oraliqdan tashqarida: {index!r}")
        self.selected_index = index

    def read_only_line(self) -> str:
        return READ_ONLY_LABEL

    # ── Yurish ────────────────────────────────────────────────────────────────────────────
    def start(self) -> RunOutcome:
        """«Start Discovery» — QADAMLAR TARTIBI. Har bir QAROR boshqa modulda.

        Tartib: `detector` (muhit) -> `collector_bridge` (paket QAYERDAN) ->
        `pipeline` (validatsiya, graf, analitik, hisobot) -> `result_package` (papka).

        ⚠️⚠️ YO'L TANLASH AVTOMATIK, lekin JIM EMAS (brief §4). Yig'uvchi `.epf` berilgan
             bo'lsa ko'prik `batch_execute` dan boshlaydi; berilmagan bo'lsa (bugungi NORMAL
             holat) yurish `watch_folder` bilan ketadi va `batch_execute` NEGA urinilmagani
             `errors` ga ANIQ kod bilan, operator qadamlari esa `notes` ga AYNAN yoziladi.
             Ekranda ham shu ko'rinadi (`route_line`, `operator_steps`). Operator uchun bu
             BITTA workflow: bitta tugma — lekin «avtomatik razvedka bo'ldi» degan da'vo YO'Q.
        ⚠️ HOLATNI UI E'LON QILMAYDI: yakuniy holat `pipeline` (yoki ko'prikning `state_hint`
           i) qaytargan `AgentStatus` dan keladi. UI faqat natija PAPKASINI tekshiradi.
        ⚠️ JIMGINA MUVAFFAQIYAT YO'Q: paket rad etilsa yoki yozilmasa — `FAILED_REPORT`.
        """
        # ⚠️ KUTISH HISOBI HAR YURISHDA NOLDAN: oldingi yurishning kutishini yangi yurishga
        #    qo'shib yuborish «bu yurish kutdi» degan yolg'on ko'rsatma bo'lardi.
        self.waiting_ticks = 0
        self._oxirgi_kutish = None
        # ⚠️ Oldingi yurishning paket papkasi YANGI yurishga O'TMAYDI: u «bu yurish paket
        #    oldi» degan yolg'on da'vo bo'lardi (kutish hisobi bilan AYNI qoida).
        self._oxirgi_paket_papkasi = None
        t = self.now()
        try:
            timestamp = rp.compact_timestamp(t)
        except rp.ResultPackageError as e:
            # ⚠️ Soat noto'g'ri qiymat berdi — bu NUQSON, muhit muammosi emas.
            return self._finish(RunOutcome(state=st.FAILED_INTERNAL, result_dir=None,
                                           code=CODE_ICHKI_XATO, detail=xavfsiz_matn(e)))
        try:
            run = agent_status.new_run(f"run-{timestamp}", now=t)
            self._oxirgi_yozuv = run
            run, bundle_dir = self._collect(run, t)
            self._oxirgi_paket_papkasi = bundle_dir
            natija = None
            if bundle_dir is not None:
                qadam = len(run.transitions)
                # ⚠️ Quvur ISTISNO TASHLAMAYDI: har qanday yiqilish ANIQ `FAILED_*` bo'lib
                #    yozuvga tushadi va natija bo'lib qaytadi (uning shartnomasi).
                natija = pipe.run_pipeline(bundle_dir, status=run, analyzer=self.analyzer,
                                           now=t)
                run = natija.status
                self._oxirgi_yozuv = run
                # ⚠️ PROGRESS KEYIN KO'RSATILADI: `run_pipeline` progress chaqiruvini QABUL
                #    QILMAYDI, lekin o'tishlarni YOZUVGA yozadi. Shu bois UI zanjirni
                #    yurishdan KEYIN takrorlaydi — operator hamma holatni ko'radi, faqat
                #    ularning hammasi oxirida paydo bo'ladi. Bu CHEGARA, yashirilmaydi.
                for o_tish in run.transitions[qadam:]:
                    self._progress(o_tish.to_state)
            return self._paket(run, natija, timestamp, bundle_dir)
        except Exception as e:  # noqa: BLE001
            # ⚠️ Traceback OPERATOR EKRANIGA chiqmaydi, lekin JIM ham yutilmaydi: holat
            #    `FAILED_INTERNAL` (ya'ni NUQSON, muhit muammosi EMAS), matn esa
            #    `redact` dan o'tadi — u ekrandan jurnalga ko'chadi.
            return self._ichki_xato(e, timestamp, t)

    def _ichki_xato(self, e: Exception, timestamp: str, t: str) -> RunOutcome:
        """Kutilmagan istisno: holat `FAILED_INTERNAL`, LEKIN natija papkasi BARIBIR yoziladi.

        ⚠️⚠️ NEGA PAPKA KERAK: `states.failure_meaning(FAILED_INTERNAL)` operatorga «natija
             papkasini butunlay (hisoboti bilan) saqlab, ishlab chiquvchiga uzating» deydi.
             Papka yozilmasa bu ko'rsatma BAJARILMAS bo'lib qolardi va nuqsonning yagona izi
             ekrandagi bir qatorlik xabar bo'lardi — ya'ni eng muhim yiqilishda operator
             «hech narsa qolmadi» holatida qolardi.
        ⚠️ YOZUV SOXTALASHTIRILMAYDI: eng oxirgi HAQIQIY yozuv olinadi (u `_advance` da
           saqlanadi) va unga FAQAT bitta o'tish — `FAILED_INTERNAL` — qo'shiladi. Yozuv
           yo'q yoki allaqachon YAKUNLANGAN bo'lsa, minimal yangi yozuv quriladi va bu izohda
           OCHIQ aytiladi (yakunlangan yurish qayta tirilmaydi — `states` shartnomasi).
        ⚠️ IKKINCHI YIQILISH JIM YUTILMAYDI: paketni qurishning O'ZI yiqilsa (masalan
           istisno matni `redact` darvozasiga tushsa), eski xulq qaytadi — papkasiz
           `FAILED_INTERNAL`. Yarim yozilgan papka esa `result_package` tufayli qolmaydi.
        ⚠️⚠️ MA'LUMOT YO'QOTILMAYDI (TUZATILGAN NUQSON): minimal yozuv qurilganda ISBOTLANGAN
             faktlar — `route`, olingan Phase 4 paketi, artefakt ro'yxati va OLDINGI XATOLAR
             bilan izohlar — YOZUVGA QAYTARILADI (`_yozuvni_tiklash`). Oldin ular TASHLANARDI:
             operatorga `route=None` bo'lgan yozuv va «Ishlatilgan yo'l: qayd etilmagan — bu
             NUQSON» deydigan hisobot qolardi, holbuki yo'l ANIQ ma'lum edi va olingan paket
             ham qo'lda turardi. Bu SOXTALASHTIRISH EMAS: har bir qiymat oldingi HAQIQIY
             yozuvdan ko'chiriladi, o'ylab chiqarilmaydi.
        ⚠️ PAKET DA'VOSI PAPKAGA MOS QILINADI: `bundle_dir` yozuvdan EMAS, ROSTDAN olingan
           papkadan (`_oxirgi_paket_papkasi`) chiqariladi — paket yozilsa da'vo bor, yozilmasa
           da'vo ham yo'q. Aks holda yozuv papkada YO'Q narsani da'vo qilib, paketni
           `check_result_package` da rad etardi.
        ⚠️⚠️ ANIQ CHEGARA: istisno MUHIT SKANERINING O'ZIDA bo'lsa (`self.environment is
             None`), papka YOZILMAYDI — chunki `environment.json` ni YOZISH uchun hech qanday
             halol mazmun yo'q, soxta «bo'sh muhit» hujjati esa «qaradim va 1C yo'q» degan
             YOLG'ON hukm bo'lib o'qilardi. Bu bo'shliq emas, TANLOV: paketda to'qima hujjat
             bo'lgandan ko'ra papka bo'lmagani yaxshi. ⚠️ Chegara ENDI ANIQ TEKSHIRILADI,
             `det.dump_document(None)` ning tasodifiy istisnosiga TAYANMAYDI.
        ⚠️⚠️ TUZATILGAN NUQSON (paket O'Z-O'ZIGA ZID edi): minimal yozuv muhit haqida HECH
             NARSA da'vo qilmasdi (`environment_file=null`, `presence_verdict` — standart
             `unknown`), AYNI papkadagi `environment.json` esa TO'LIQ skaner natijasini
             yozardi. Ya'ni bitta paket ichida ikki hujjat ZID bo'lardi va «qaysi biri
             haqiqat» savoli javobsiz qolardi. Tuzatish: muhit hujjati YOZILADIGAN bo'lsa
             (ya'ni skaner BAJARILGAN bo'lsa), minimal yozuv ham AYNI SHU faktni yozadi —
             `environment_file`, `presence_verdict` va `ENVIRONMENT_SCAN` o'tishi. Bu
             SOXTALASHTIRISH EMAS: skaner rostdan bajarilgan va uning natijasi qo'lda
             (`self.environment`), o'tish esa shu faktning yozuvdagi izi.
        """
        matn = f"{type(e).__name__}: {xavfsiz_matn(e)}"
        papkasiz = RunOutcome(state=st.FAILED_INTERNAL, result_dir=None,
                              code=CODE_ICHKI_XATO, detail=matn)
        if self.environment is None:
            return self._finish(papkasiz)
        try:
            yozuv = self._oxirgi_yozuv
            oldingi = yozuv
            izoh = ("Kutilmagan ichki xato: yurish yozuvi to'xtagan joyidan OLINDI va unga "
                    "yakuniy o'tish qo'shildi.")
            if yozuv is None or st.is_terminal(yozuv.state):
                # ⚠️ `self._advance` EMAS, YOZUVNING O'Z `advance` i: progress chaqiruvi
                #    istisnoning MANBASI bo'lishi mumkin (operator kuzatuvchisi) va uni bu
                #    yerda qayta chaqirish ikkinchi yiqilishga olib kelardi.
                yozuv = (agent_status.new_run(f"run-{timestamp}", now=t)
                         .advance(st.ENVIRONMENT_SCAN, now=t,
                                  note="muhit skaneri BAJARILDI — hujjati paketda"))
                yozuv = self._yozuvni_tiklash(yozuv, oldingi)
                izoh = ("Kutilmagan ichki xato: yurishning oraliq yozuvi MAVJUD EMAS yoki "
                        "allaqachon YAKUNLANGAN (yakunlangan yurish qayta tirilmaydi), shu "
                        "bois bu yozuv MINIMAL — O'TISHLAR ZANJIRI to'liq emas. Lekin "
                        "ISBOTLANGAN faktlar TASHLANMADI: muhit skaneri bajarilgani va uning "
                        "hujjati shu paketda turgani, hamda oldingi yozuvdan ko'chirilgan "
                        "yo'l, artefakt ro'yxati, xatolar va izohlar — hammasi QOLDI.")
            # ⚠️⚠️ MUHIT DA'VOSI HAR IKKI SHOXDA hujjat bilan MOS QILINADI: `_paket`
            #      `environment.json` ni DOIM `self.environment` dan yozadi, demak yozuv ham
            #      AYNI SHU manbani da'vo qilishi SHART. Ikkinchi shox ham ochiq edi: istisno
            #      `refresh_environment` ning ICHIDA bo'lsa (oyna ochilganda skanerlangan
            #      natija esa qo'lda qolgan bo'lsa) yozuv `environment_file=null` bilan
            #      qolardi va «papkada hujjat bor, yozuv uni DA'VO QILMAYDI» degan nuqson
            #      butun paketni rad etardi — ya'ni ENG MUHIM yiqilishda yana «hech narsa
            #      qolmadi» holati. ⚠️ Hukm ham AYNI manbadan olinadi: ikki hujjat ZID
            #      hukm yoza OLMAYDI.
            yozuv = (yozuv.with_environment_file(ENVIRONMENT_FILE)
                     .with_presence_verdict(self.environment.presence_verdict))
            yozuv = (yozuv.with_error(SCOPE_UI, CODE_ICHKI_XATO, matn)
                     .with_note(izoh))
            # ⚠️ DA'VO PAPKAGA MOS: paket ROSTDAN olingan bo'lsa u paketga ko'chadi va
            #    yozuv uni DA'VO qiladi; olinmagan bo'lsa da'vo ham OLIB TASHLANADI
            #    (`replace` — `_sirsiz_paket` dagi AYNI sabab: da'voni qaytarib oladigan
            #    metod ATAYLAB yo'q, yozuv o'chirgich emas).
            paket_papkasi = self._oxirgi_paket_papkasi
            if paket_papkasi is not None:
                yozuv = yozuv.with_bundle_dir(rp.BUNDLE_SUBDIR)
            elif yozuv.bundle_dir is not None:
                yozuv = replace(yozuv, bundle_dir=None)
            yozuv = self._advance(yozuv, st.FAILED_INTERNAL, t,
                                  note="kutilmagan ichki xato — quvur to'xtadi")
            natija = self._paket(yozuv, None, timestamp, paket_papkasi)
            if natija.result_dir is None:
                return natija
            # ⚠️ HOLAT `_paket` dan EMAS, shu yerdan: paket to'g'ri yozilgani NUQSONNI
            #    tuzatmaydi va yurish BARIBIR `FAILED_INTERNAL` bo'lib qoladi.
            return self._finish(RunOutcome(state=st.FAILED_INTERNAL,
                                           result_dir=natija.result_dir,
                                           code=CODE_ICHKI_XATO, detail=matn))
        except Exception:  # noqa: BLE001
            return self._finish(papkasiz)

    def _yozuvni_tiklash(self, yangi, oldingi):
        """MINIMAL yozuvga oldingi HAQIQIY yozuvning ISBOTLANGAN faktlarini qaytaradi.

        Ko'chiriladigan narsalar: `route` · artefakt ro'yxati · XATOLAR · IZOHLAR.

        ⚠️⚠️ NEGA KERAK (TUZATILGAN NUQSON): kutilmagan ichki xato oxirgi yozuv YAKUNLANGAN
             bo'lsa MINIMAL yozuv quradi — va u avval HECH NARSANI ko'chirmasdi. Natijada
             yo'li ANIQ ma'lum bo'lgan yurish `route=None` bilan yetib borar, hisobot esa
             «Ishlatilgan yo'l: qayd etilmagan — bu NUQSON» deb yozardi; paketli yo'l NEGA
             urinilmaganini aytadigan xato va operator qadamlari ham YO'QOLARDI. Ya'ni
             brief §7 talab qilgan «operator aralashuvi yozilgan» da'vosi AYNAN eng muhim
             yiqilishda BAJARILMASDI.
        ⚠️ SOXTALASHTIRISH YO'Q: har bir qiymat oldingi yozuvdan AYNAN ko'chiriladi va yangi
           qiymat O'YLAB CHIQARILMAYDI. O'TISHLAR ZANJIRI esa ATAYLAB ko'chirilmaydi —
           yakunlangan yurish qayta tirilmaydi (`states` shartnomasi) va zanjirning
           to'liqsizligi yozuvdagi izohda OCHIQ aytiladi.
        ⚠️ `bundle_dir` BU YERDA TEGILMAYDI: paket da'vosi yozuvdan emas, ROSTDAN olingan
           papkadan chiqariladi (`_ichki_xato`), aks holda yozuv papkada YO'Q narsani da'vo
           qilardi.
        ⚠️ ARTEFAKT RO'YXATI keyin `_yakunla` da YAKUNLANADI (papkaning haqiqiy mazmuni
           bilan). Bu yerda ko'chirish SHUNDA ham kerak: oraliq yozuv «hech narsa yozilmagan»
           deb turmasligi uchun, va ro'yxatni YAKUNLAMAYDIGAN yo'l qo'shilsa ham da'vo
           yo'qolmasligi uchun.
        """
        if oldingi is None:
            return yangi
        if oldingi.route:
            yangi = yangi.with_route(oldingi.route)
        if oldingi.artifacts:
            yangi = yangi.with_artifacts(oldingi.artifacts)
        for xato in oldingi.errors:
            yangi = yangi.with_error(xato.scope, xato.code, xato.detail)
        for izoh in oldingi.notes:
            yangi = yangi.with_note(izoh)
        return yangi

    # ── Qadamlar ──────────────────────────────────────────────────────────────────────────
    def _collect(self, run, t: str):
        """`START` dan `METADATA_DISCOVERY` gacha. Qaytaradi: `(yozuv, bundle_dir|None)`.

        ⚠️ Ko'prikning `state_hint` i QAYSI holatdan yozilishi kerakligini `collector_bridge.
           HINT_SOURCE_STATE` aytadi: `states.TRANSITIONS` har bir yiqilishni FAQAT o'z
           joyidan ruxsat etadi (`FAILED_NO_1C` — `ENVIRONMENT_SCAN` dan, `FAILED_NO_TARGET`
           — `TARGET_SELECTION` dan). Shu bois darvozalar (`preflight`) ERTA chaqiriladi va
           «qulay» umumiy holatga siltab yuborilmaydi.
        """
        run = self._advance(run, st.ENVIRONMENT_SCAN, t,
                            note="muhit skaneri — FAQAT O'QISH, 1C ga ulanmaydi")
        env = self.refresh_environment()
        run = run.with_environment_file(ENVIRONMENT_FILE)
        # ⚠️⚠️ 1C MAVJUDLIGI HUKMI YOZUVGA KO'CHADI (`detector` da tug'iladi, bu yerda faqat
        #    ko'chiriladi): `FAILED_NO_1C` holatining O'ZI «qaradim va yo'q» (`absent`) bilan
        #    «qaray olmadim» (`unknown`) ni ajratmaydi, va shu ajrimsiz hisobot
        #    `environment.json` ga ZID xulosa yozardi. Mashina o'qiydigan ajrim — SHU kalit,
        #    odam o'qiydigani — `states.failure_meaning(..., presence_verdict=...)`.
        run = run.with_presence_verdict(env.presence_verdict)
        for xato in env.errors():
            # ⚠️ `_error_code` izohiga qarang: `detector` kodlari kichik harfda, yurish
            #    yozuvi esa KATTA harf talab qiladi.
            run = run.with_error(xato["scope"], _error_code(xato["code"]), xato["detail"])

        plan = self._plan(env)
        if plan is None:
            # ── NORMAL `watch_folder` OQIMI: yig'uvchini OPERATOR yurgizadi ───────────────
            # ⚠️⚠️ TUZATILGAN NUQSON: avval bu shox `bridge.collect` ni UMUMAN chaqirmasdi va
            #      faqat «papkada yozuv bormi» deb qarardi (`_bundle_bor`), lekin `route` ni
            #      `watch_folder` deb YOZARDI. Natijada ko'prikning TAYYORLIK ISBOTI (yarim
            #      yozilgan `manifest.json` ni RAD etish, hajm barqarorligi, JSON parse)
            #      shipped yo'lda ISHLATILMASDI — ya'ni Phase 4 da yolg'on SUCCESS bergan
            #      aynan shu nuqson qaytib kelardi. Endi normal oqim ham ko'prikning
            #      kuzatish/tayyorlik mantig'idan O'TADI (`bridge.watch`).
            # ⚠️ JIMGINA YIQILISH YO'Q (brief §4): paketli yo'l NEGA urinilmagani `errors` ga
            #    ANIQ kod bilan, operator qadamlari esa `notes` ga AYNAN yoziladi. Ikkisi ham
            #    ko'prikdan keladi — hisobot va yurish yozuvi BIR MANBADAN o'qiydi.
            run = run.with_route(ROUTE_WATCH_FOLDER)
            run = run.with_error(bridge.SCOPE_BATCH, bridge.CODE_BATCH_NOT_ATTEMPTED,
                                 bridge.BATCH_NOT_ATTEMPTED_REASON)
            for izoh in bridge.WATCH_FOLDER_OPERATOR_STEPS:
                run = run.with_note(izoh)
            for holat in (st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY):
                run = self._advance(run, holat, t)
            # ⚠️ Kuzatish yiqilishlari (`WATCH_STATE_HINTS`) HAMMASI `METADATA_DISCOVERY` dan
            #    yoziladi — bu ko'prikda import paytida tekshiriladi, shu bois zanjirni
            #    `_manzilgacha` bilan qayta hisoblash KERAK EMAS.
            natija = bridge.watch(self._watch_plan(), clock=self.clock, sleeper=self.sleeper,
                                  on_wait=self._kutish_hodisasi)
            run = self._bridge_yozuvi(run, natija)
            if not natija.ok:
                return self._advance(run, natija.state_hint, t,
                                     note="kuzatilgan papka TO'LIQ paket bermadi"), None
            return run, natija.bundle_dir

        # ── Ko'prik yo'li ────────────────────────────────────────────────────────────────
        yiqildi = bridge.preflight(plan)
        if yiqildi is not None:
            run = self._manzilgacha(run, bridge.HINT_SOURCE_STATE[yiqildi.state_hint], t)
            run = self._bridge_yozuvi(run, yiqildi)
            return self._advance(run, yiqildi.state_hint, t,
                                 note="ko'prik darvozasi — hech narsa bajarilmadi"), None

        for holat in (st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY):
            run = self._advance(run, holat, t)
        natija = bridge.collect(plan, clock=self.clock, sleeper=self.sleeper,
                                runner=self.runner)
        run = self._bridge_yozuvi(run, natija)
        if not natija.ok:
            return self._advance(run, natija.state_hint, t,
                                 note="yig'uvchi ko'prigi natija bermadi"), None
        return run, natija.bundle_dir

    def _manzilgacha(self, run, manzil: str, t: str):
        """Zanjir bo'ylab AYNAN `manzil` holatigacha yuradi (undan OSHMAYDI).

        ⚠️⚠️ BU TUZATILGAN NUQSON (eski kesim: `PRE_PIPELINE_CHAIN[index(run.state) + 1:]`
             + `break`): kesim JORIY holatni chiqarib tashlardi, `HINT_SOURCE_STATE
             [FAILED_NO_1C]` esa AYNAN joriy holat (`ENVIRONMENT_SCAN`) — ya'ni `manzil`
             kesimda UCHRAMAY, halqa `METADATA_DISCOVERY` gacha borardi va
             `METADATA_DISCOVERY -> FAILED_NO_1C` RUXSAT ETILMAGAN o'tishida istisno
             berardi. Natijada 1C o'rnatilmagan mashinada (ya'ni ENG EHTIMOLLI holatda)
             agent `FAILED_INTERNAL` berib, natija papkasini UMUMAN yozmasdi.
             Tuzatish SHAKLI: manzil INDEKSI hisoblanadi va faqat unga QADAR yuriladi —
             `manzil == run.state` bo'lsa kesim BO'SH, ya'ni hech qayerga yurilmaydi.
        ⚠️ FAIL-CLOSED: manzil zanjirda bo'lmasa yoki joriy holatdan ORQADA bo'lsa — ANIQ
           istisno. «Qulay» holatga jimgina siljish YO'Q: u yiqilish sababini almashtirib,
           operatorni butunlay boshqa yo'lga yuborardi.
        """
        if run.state not in PRE_PIPELINE_CHAIN:
            raise UiError(f"joriy holat ({run.state}) quvurgacha bo'lgan zanjirda yo'q — "
                          f"ko'prik darvozasi faqat shu zanjirdan yoziladi")
        if manzil not in PRE_PIPELINE_CHAIN:
            raise UiError(f"ko'prik ishorasining manbasi ({manzil}) zanjirda yo'q — "
                          f"`collector_bridge.HINT_SOURCE_STATE` o'zgargan")
        joriy_idx = PRE_PIPELINE_CHAIN.index(run.state)
        manzil_idx = PRE_PIPELINE_CHAIN.index(manzil)
        if manzil_idx < joriy_idx:
            raise UiError(f"ko'prik ishorasining manbasi ({manzil}) joriy holatdan "
                          f"({run.state}) ORQADA — yurish ORQAGA qaytmaydi")
        for holat in PRE_PIPELINE_CHAIN[joriy_idx + 1:manzil_idx + 1]:
            run = self._advance(run, holat, t)
        return run

    def _plan(self, env: det.EnvironmentScan):
        """`collector_bridge.CollectPlan` (yoki `None` — paket allaqachon bor).

        ⚠️ `exe_path` va `locator` XOM `EnvironmentScan` dan olinadi, hujjatdan EMAS:
           hujjatda ular niqoblangan (`[REDACTED]`) va ko'prikka yaroqsiz. Rejada
           KREDENSIAL maydoni YO'Q va bo'lmaydi.
        """
        if self.epf_path is None:
            return None
        eng = env.newest_install()
        nishon = self.selected_infobase()
        return bridge.CollectPlan(
            epf_path=self.epf_path,
            output_dir=self.output_dir or "",
            exe_path=eng.path if eng is not None else None,
            # ⚠️ HUKM KO'PRIKKA UZATILADI: `exe_path` ning yo'qligi O'ZICHA «1C yo'q» ni
            #    isbotlamaydi — ko'prik sababni shu hukmga qarab yozadi.
            presence_verdict=env.presence_verdict,
            infobase_kind=nishon.kind if nishon is not None else None,
            infobase_locator=nishon.locator if nishon is not None else None,
            requires_auth=nishon.requires_auth if nishon is not None else det.TRI_UNKNOWN,
            mode=self.mode,
        )

    def _watch_plan(self) -> bridge.WatchPlan:
        """`collector_bridge.WatchPlan` — kuzatiladigan papka va CHEKLI kutish.

        ⚠️ `bundle_dir` `None` bo'lsa ham reja QURILADI (bo'sh matn bilan): darvoza
           KO'PRIKDA turadi va u sababni O'Z shartnomasi bilan yozadi
           (`BUNDLE_DIR_MISSING`). UI yiqilish sababini O'ZI o'ylab chiqarmaydi — aks holda
           bitta vaziyat ikki xil kod bilan yozilib qolardi.
        """
        return bridge.WatchPlan(
            bundle_dir=self.bundle_dir if isinstance(self.bundle_dir, str) else "",
            mode=self.mode,
            timeout_seconds=self.watch_timeout_seconds,
            poll_seconds=self.watch_poll_seconds,
        )

    def _kutish_hodisasi(self, tick) -> None:
        """Ko'prikning «hali tayyor emas» o'lchovi — QAROR QABUL QILMAYDI, faqat ko'rsatadi."""
        self.waiting_ticks += 1
        self._oxirgi_kutish = tick
        if self.on_wait is not None:
            self.on_wait(tick)

    def wait_line(self) -> str:
        """Ekrandagi KUTISH qatori. ⚠️ Yo'l yozilmaydi (`WaitTick.human()` qoidasi)."""
        if self._oxirgi_kutish is None:
            return "Kutish: yo'q"
        return self._oxirgi_kutish.human()

    def route_line(self) -> str:
        """«Qaysi yo'l» qatori — OPERATOR EKRANIDA, yurish tugashini kutmasdan.

        ⚠️⚠️ YO'L HAQQONIYLIGI (brief §7): bu qator `watch_folder` bo'lganda «avtomatik
             razvedka» ma'nosini BERMAYDI va bermasligi testda qulflangan. Operator
             ekranda ko'rishi kerak bo'lgan narsa — YIG'UVCHINI U O'ZI ISHGA TUSHIRISHI.
        ⚠️ Yo'l `epf_path` BERILGANMI degan YAGONA faktdan hisoblanadi — aynan shu fakt
           `_plan()` ning qarorini ham belgilaydi, demak ekrandagi qator quvurning haqiqiy
           yo'lidan ajralib ketmaydi.
        """
        if self.epf_path is None:
            return (f"Yo'l: `{ROUTE_WATCH_FOLDER}` — yig'uvchini OPERATOR o'z 1C sessiyasida "
                    f"ishga tushiradi, agent esa chiqish papkasini KUZATADI. Agent 1C ni "
                    f"ishga tushirMAYDI.")
        return (f"Yo'l: `{ROUTE_BATCH_EXECUTE}` urinib ko'riladi — darvozasi yopiq "
                f"bo'lsa sabab yozuvga tushadi va yurish `{ROUTE_WATCH_FOLDER}` bo'lib "
                f"qoladi.")

    def operator_steps(self) -> tuple[str, ...]:
        """Operator BAJARADIGAN qadamlar (`watch_folder` yo'lida) — ko'prikdan AYNI holda.

        ⚠️ Matnlar UI da QAYTA YOZILMAYDI: yurish yozuviga (`notes`) tushadigan matn bilan
           AYNAN bir xil bo'lishi kerak, aks holda ekranda bir narsa, hisobotda boshqa narsa
           turardi.
        """
        if self.epf_path is not None:
            return ()
        return bridge.WATCH_FOLDER_OPERATOR_STEPS

    def selected_infobase(self):
        """Tanlangan nishon (`detector.Infobase`) yoki `None`."""
        env = self.environment
        if env is None or self.selected_index is None:
            return None
        if not (0 <= self.selected_index < len(env.infobases)):
            return None
        return env.infobases[self.selected_index]

    def _bridge_yozuvi(self, run, natija):
        """Ko'prikning yo'li, xatolari va izohlarini yurish yozuviga KO'CHIRADI."""
        run = run.with_route(natija.route)
        for xato in natija.errors:
            run = run.with_error(xato.scope, _error_code(xato.code), xato.detail)
        for izoh in natija.notes:
            run = run.with_note(izoh)
        return run

    def _paket(self, run, natija, timestamp: str, bundle_dir: str | None) -> RunOutcome:
        """Natija papkasini quradi, yozadi va TEKSHIRADI.

        ⚠️ `pipeline.write_outputs` ATAYLAB ISHLATILMAYDI: u faqat quvurning O'Z artefaktlarini
           yozadi va papkani YAKUNLAMAYDI (o'z docstringi shuni aytadi). `result_package` esa
           papkani BUTUN holda, manifest bilan birga va FAIL-CLOSED yozadi — artefaktlar
           baytlari esa `PipelineResult.outputs` dan xotirada olinadi. Ikki yozuvchi
           bo'lmasligi shu bilan ta'minlanadi.
        ⚠️ ARTEFAKT RO'YXATI SHU YERDA YAKUNLANADI: quvur faqat O'ZI chiqargan nomlarni
           biladi, `environment.json` va `agent_manifest.json` esa boshqa qatlamlardan keladi.
        ⚠️⚠️ HISOBOT HAM SHU YERDA QURILADI (`_yakunla`), quvurning hisobot matni ESA
             ISHLATILMAYDI — sabab `_yakunla` docstringida: quvur hisobotni O'Z artefakt
             ro'yxati bilan quradi, u esa YAKUNIY ro'yxat EMAS.
        """
        # ⚠️ Phase 4 paketi ko'prik bergan (yoki operator ko'rsatgan) papkadan BAYT-BA-BAYT
        #    ko'chiriladi va O'ZGARTIRILMAYDI. Manba papkaga TEGILMAYDI — faqat o'qiladi.
        bundle = {} if bundle_dir is None else rp.read_folder_bytes(bundle_dir)
        ai = None if natija is None else natija.output(AI_CANDIDATES_FILE)
        run, hisobot = self._yakunla(run, natija, bundle, ai is not None)

        paket = rp.ResultPackage.from_parts(
            timestamp=timestamp,
            status_json=run.to_json(),
            environment_json=det.dump_document(self.environment),
            report_md=hisobot,
            ai_candidates_json=None if ai is None else ai.decode("utf-8"),
            bundle=bundle,
        )
        try:
            root = paket.write(self.parent_dir)
        except (rp.ResultPackageError, OSError) as e:
            # ⚠️⚠️ SIR TOPILGAN HOLAT ALOHIDA: paket RAD etiladi, LEKIN operator «hech narsa
            #      qolmadi» holatida QOLMAYDI — `_sirsiz_paket` minimal, sirsiz paketni
            #      yozadi (brief §2). Sirning O'ZI u paketga TUSHMAYDI.
            sirli = self._sirli_artefaktlar(paket)
            if sirli:
                return self._sirsiz_paket(run, timestamp, sirli, e)
            # ⚠️ Papka YOZILMADI, demak yurishning YAGONA izi — shu ekran. Holatni
            #    `FAILED_REPORT` ga «o'tkazib» yozib bo'lmaydi: yakunlangan yurish qayta
            #    tirilmaydi (`states` shartnomasi), shu bois bu faqat UI ning hukmi va u
            #    `agent_status.json` da emas, ekranda qoladi. Bu NUQSON — yashirilmaydi.
            return self._finish(RunOutcome(
                state=st.FAILED_REPORT, result_dir=None, code=CODE_PAKET_YOZILMADI,
                detail=f"natija papkasi yozilmadi: {type(e).__name__}",
                problems=(xavfsiz_matn(e),)))
        problems = rp.check_result_package(root)
        if problems:
            return self._finish(RunOutcome(
                state=st.FAILED_REPORT, result_dir=root, code=CODE_PAKET_RAD,
                problems=tuple(xavfsiz_matn(p) for p in problems),
                detail="natija paketi tekshiruvdan O'TMADI — paket UZATILMAYDI"))
        # ⚠️⚠️ TAFSILOT HOLATGA QARAB YOZILADI: «natija paketi tekshiruvdan o'tdi» PAKET
        #      haqidagi gap, YURISH haqidagi emas. Yiqilgan yurishda shu matnni yolg'iz
        #      ko'rsatish ekranda «FAILED_TIMEOUT — tekshiruvdan o'tdi» degan O'Z-O'ZIGA ZID
        #      qator berardi va operator qaysi biri haqiqat ekanini bilmasdi.
        yiqildi = st.is_known(run.state) and st.is_failure(run.state)
        tafsilot = ("natija paketi tekshiruvdan o'tdi va SAQLANDI, lekin YURISHNING O'ZI "
                    "yiqildi — sababini hisobotdan o'qing" if yiqildi
                    else "natija paketi tekshiruvdan o'tdi")
        return self._finish(RunOutcome(state=run.state, result_dir=root, detail=tafsilot))

    def _yakunla(self, run, natija, bundle, ai_bor: bool):
        """Artefakt ro'yxatini YAKUNLAYDI va AYNI SHU ro'yxat bilan hisobotni quradi.

        Qaytaradi: `(yurish yozuvi, hisobot matni)`.

        ⚠️⚠️ TUZATILGAN NUQSON (hisobot yozuvga ZID artefakt ro'yxatini sanardi):
             `pipeline.step_report` hisobotni O'Z artefakt ro'yxati bilan quradi, u esa quvur
             KO'RADIGAN nomlar (hisobot, nomzodlar, yurish yozuvi) — ya'ni UCHTA. Papkaning
             YAKUNIY ro'yxati esa shu qatlamda tug'iladi (`environment.json`,
             `agent_manifest.json`, `errors.json` va butun `bundle/` — o'n ikkita). Natijada
             MUVAFFAQIYATLI yurishda bitta papka ichida `discovery_report.md` uchta nom,
             `agent_status.json` esa o'n ikkita nom sanardi, va operator «qaysi biri
             haqiqat» savoli bilan qolardi. Tuzatish: hisobotni QUVUR EMAS, SHU qatlam
             quradi — ro'yxat YAKUNLANGANDAN KEYIN. Shu bois `PipelineResult.report_text`
             bu yerda ATAYLAB ishlatilmaydi (quvurning o'z chiqishi tegishsiz qoladi: u
             `pipeline` ning shartnomasi va u yerda sinaladi).
        ⚠️ MAZMUN QUVURDAN KELADI: ko'rik, validatsiya hisobotlari va aniqlanmagan havolalar
           `PipelineResult` dan AYNAN uzatiladi — ya'ni hisobot «qayta qurilgani» uchun
           hech narsa yo'qolmaydi, faqat artefakt ro'yxati to'g'ri bo'ladi.
        ⚠️ QUVUR YETIB BORMAGAN YURISHDA (`natija is None`) hisobot BARIBIR quriladi:
           `states.FAILURE_MEANING` operatorga aynan hisobotni uzatishni aytadi.
        """
        nomlar = [AGENT_STATUS_FILE, rp.AGENT_MANIFEST_FILE, ENVIRONMENT_FILE, ERRORS_FILE,
                  REPORT_FILE]
        if ai_bor:
            nomlar.append(AI_CANDIDATES_FILE)
        nomlar += [f"{rp.BUNDLE_SUBDIR}/{n}" for n in bundle]
        run = run.with_artifacts(nomlar)
        if natija is not None:
            try:
                return run, reporter.build_report(
                    status=run, review=natija.review, validation=natija.validation,
                    exit_code=natija.validator_exit_code, revalidation=natija.revalidation,
                    revalidation_exit_code=natija.revalidation_exit_code,
                    unresolved_references=natija.unresolved_references)
            except reporter.ReportError as e:
                # ⚠️ JIM QISQARTIRISH YO'Q: hisobotning darvozasi (shakl, sir, yo'l
                #    haqqoniyligi) tashqi matnni rad etdi — SABAB yozuvga tushadi va u
                #    hosila `errors.json` ga ham ko'chadi. Hisobot esa yurish yozuvidan
                #    qayta quriladi: hisobotsiz paket uzatilmaydi.
                run = run.with_error(
                    SCOPE_UI, CODE_HISOBOT_QISQARTIRILDI,
                    f"to'liq hisobot darvozadan O'TMADI va hisobot FAQAT yurish yozuvidan "
                    f"qayta qurildi (tahlil va validator matni paketga tushmadi): "
                    f"{xavfsiz_matn(e)}")
        # ⚠️⚠️ ZAHIRA HISOBOT QURILISHI HAM `try` ICHIDA va bu TUZATILGAN NUQSON: oldin bu
        #      chaqiruv himoyasiz edi, ya'ni uning istisnosi `_paket` dan chiqib `start()`
        #      ning umumiy `except` iga tushardi — SOG'LOM yurish `FAILED_INTERNAL` bo'lar,
        #      `route` yo'qolar va MINIMAL yozuv qolardi. Ikkinchi yiqilish esa EHTIMOLLI:
        #      birinchi yiqilishning SABABI yozuvga tushadi, zahira hisobot esa sabab matnini
        #      `### Xatolar` bo'limida QAYTA chiqaradi — ya'ni darvoza O'Z xato matniga qarshi
        #      ishlashi mumkin edi. Darvozalarning O'ZI endi iborani ko'chirmaydi
        #      (`report._assert_no_automatic_claim`), lekin bu qatlam BARIBIR fail-closed
        #      bo'lishi kerak: tashqi matn (tahlilchi izohi, 1C xato tavsifi) oldindan
        #      bilinmaydi.
        try:
            return run, reporter.build_report(status=run)
        except reporter.ReportError as e:
            # ⚠️ JIM DEGRADATSIYA YO'Q: kod ham, sabab ham yozuvga tushadi va `errors.json`
            #    ga ko'chadi. Xato AVVAL yoziladi, hisobot KEYIN quriladi — shunda minimal
            #    hisobot sanagan xatolar soni yozuvdagi ro'yxat bilan ZID bo'lmaydi.
            run = run.with_error(
                SCOPE_UI, CODE_HISOBOT_DEGRADATSIYA,
                f"yurish yozuvidan qurilgan ZAHIRA hisobot ham O'Z darvozasidan O'TMADI, shu "
                f"bois hisobot MINIMAL matnga degradatsiya qildi (papka BARIBIR yoziladi — "
                f"hisobotsiz paket uzatilmaydi): {xavfsiz_matn(e)}")
            return run, self._minimal_hisobot(run)

    def _minimal_hisobot(self, run) -> str:
        """ENG OXIRGI ZAHIRA: hisobotning IKKI qurilishi ham yiqilganda yoziladigan matn.

        ⚠️⚠️ NEGA UMUMAN MATN: `result_package` bo'sh hisobotni RAD etadi va
             `states.failure_meaning` operatorga papkani «hisoboti bilan» uzatishni aytadi —
             ya'ni hisobotsiz paket operatorni «hech narsa qolmadi» holatida qoldirardi.
        ⚠️⚠️ XATO MATNLARI BU YERGA KO'CHIRILMAYDI (faqat SANOQ): aynan xato matni
             hisobotning darvozasini bloklagan bo'lishi mumkin, demak uni qayta yozish
             UCHINCHI yiqilish bo'lardi. To'liq ro'yxat `agent_status.json` va `errors.json`
             da turadi — ikkisi ham shu paketda.
        ⚠️ MATN ATAYLAB QISQA va TAQIQLANGAN IBORASIZ: u avtomatlashtirish da'vosini
           bermaydi, tasdiq so'zini ishlatmaydi va tashqi matn OLMAYDI. Shu bois u na
           `redact`, na yo'l haqqoniyligi darvozasiga tushadi — va buni test qulflaydi.
        ⚠️ DETERMINISTIK: hamma qiymat yurish yozuvidan keladi, VAQT o'ylab chiqarilmaydi.
        """
        return "\n".join([
            f"# {reporter.REPORT_TITLE}",
            "",
            "## ⚠️⚠️ BU HISOBOT MINIMAL — TO'LIQ HISOBOT QURILMADI",
            "",
            "To'liq hisobot ham, yurish yozuvidan qurilgan ZAHIRA hisobot ham O'Z "
            "darvozasidan o'tmadi. Shu bois bu fayl faqat yurishni TANITADI: unda TAHLIL "
            "YO'Q, nomzodlar YO'Q va birorta TAXMIN ham yozilmagan.",
            "",
            f"- **Yurish (`run_id`):** `{run.run_id}`",
            f"- **Holat:** `{run.state}`",
            f"- **Yo'l:** " + (f"`{run.route}`" if run.route else reporter.NOT_RECORDED),
            f"- **Paket papkasi:** " + (f"`{run.bundle_dir}`" if run.bundle_dir
                                        else reporter.NOT_RECORDED),
            f"- **Xatolar soni:** {len(run.errors)} ta — ro'yxati `{AGENT_STATUS_FILE}` va "
            f"`{ERRORS_FILE}` da TO'LIQ turadi va bu yerda ATAYLAB TAKRORLANMAYDI (aynan "
            f"xato matni hisobot darvozasini bloklagan bo'lishi mumkin).",
            f"- **Izohlar soni:** {len(run.notes)} ta — AYNI ikki faylda.",
            "",
            f"> ⚠️ Keyingi qadam: butun natija papkasini (shu fayl bilan birga) saqlab, "
            f"ishlab chiquvchiga uzating. Sabab `{AGENT_STATUS_FILE}` da turadi.",
            "",
        ])

    def _sirli_artefaktlar(self, paket) -> tuple[str, ...]:
        """Paketning QAYSI a'zolarida sir shubhasi bor — NOMLAR ro'yxati (tartiblangan).

        ⚠️⚠️ QIYMAT QAYTARILMAYDI va hech qayerga yozilmaydi: operatorga «qaysi faylni
             ko'rish kerak» degan javob yetarli, qiymatning o'zi esa ekrandan jurnalga,
             jurnaldan xabar almashinuviga ko'chardi (`redact.Finding.__str__` AYNI qoida).
        ⚠️ DARVOZA BU EMAS: rad etish qarorini `result_package` ning O'ZI qiladi (fail-closed,
           yozishdan OLDIN). Bu yerda faqat rad etilgan paketning SABABI nomlanadi, shu bois
           skaner YADRONING skaneri bilan AYNI (`redact.scan`) — ikkinchi «sir aniqlovchi»
           yozilsa, u bir kun birinchisidan ajralib ketardi.
        ⚠️ `errors.json` ATAYLAB SKANERLANMAYDI: u `agent_status.json` DAN HOSILA
           (`ResultPackage.errors_json`), ya'ni undagi sir yozuvning O'ZIDA ham bor va
           yozuv allaqachon skanerlanadi. Ikki marta sanash operatorga ikki xil «joy»
           ko'rsatib, yolg'on ikkinchi manba yasardi.
        """
        nomzodlar: list[tuple[str, str]] = [
            (AGENT_STATUS_FILE, paket.status_json),
            (ENVIRONMENT_FILE, paket.environment_json),
            (REPORT_FILE, paket.report_md),
        ]
        if paket.ai_candidates_json is not None:
            nomzodlar.append((AI_CANDIDATES_FILE, paket.ai_candidates_json))
        for nom, raw in paket.bundle:
            # ⚠️ `errors="replace"` — buzuq baytli paket ham SKANERLANADI: dekodlash xatosi
            #    tufayli skanerni o'tkazib yuborish aynan «sir bor, lekin ko'rmadim» bo'lardi.
            nomzodlar.append((f"{rp.BUNDLE_SUBDIR}/{nom}", raw.decode("utf-8", "replace")))
        return tuple(sorted(nom for nom, matn in nomzodlar if redaction.scan(matn)))

    def _sirsiz_paket(self, run, timestamp: str, sirli, e) -> RunOutcome:
        """SIR topilganda yoziladigan MINIMAL, SIRSIZ paket (brief §2).

        ⚠️⚠️ NEGA UMUMAN PAKET: brief §2 ANIQ — «operator hech qachon ``hech narsa qolmadi``
             holatida qolmasin, failure package ham VALID package bo'lsin». Eski xulqda sir
             topilsa `result_dir=None` bo'lardi, ya'ni na yurish yozuvi, na xatolar, na muhit
             hujjati yozilmasdi: SIR ANIQLANGANI faktining ham HUJJATLI izi qolmasdi va
             yurishning yagona izi ekrandagi bir qatorlik xabar bo'lardi.
        ⚠️⚠️ SIRNING O'ZI BU PAKETDA YO'Q va bu TANLOV, bo'shliq emas:
             · `bundle/` QO'SHILMAYDI — Phase 4 paketi sirning eng ehtimolli tashuvchisi va
               uni «tozalab» yozish uning baytlarini (demak dalilini) buzardi;
             · `discovery_ai_candidates.json` QO'SHILMAYDI — u metadata matnidan quriladi;
             · hisobot TASHQI MATNSIZ, FAQAT yurish yozuvidan qayta quriladi (validator
               nuqsonlari va tahlil matni paketga tushmaydi).
             Qolgan BESH ildiz artefakti (`ALWAYS_FILES`) o'z darvozalaridan O'TADI — ya'ni
             bu paket ham `validate_result_package` dan o'tadigan HAQIQIY paket.
        ⚠️ YOZUVDAGI DA'VO PAPKAGA MOS BO'LADI: `bundle_dir` `null` ga qaytariladi va
           artefakt ro'yxati AYNAN beshta nomdan iborat bo'ladi. Aks holda yozuv papkada
           YO'Q narsani da'vo qilib, paketning O'ZI validatordan o'tmasdi. «Paket OLINGAN,
           lekin USHLAB QOLINGAN» fakti esa xato yozuvi va izohda OCHIQ turadi.
        ⚠️ HOLAT SOXTALASHTIRILMAYDI: yurishning O'Z holati o'zgarmaydi (yakunlangan yurish
           qayta tirilmaydi), ekranda esa `FAILED_REPORT` — chiqish YOZILMADI. Farq
           `SIR_USHLANDI_IZOH` da ochiq aytiladi.
        ⚠️⚠️ MINIMAL PAKETNING O'ZI ham yozilmasligi MUMKIN va bu YASHIRILMAYDI: sir
             `environment.json` ning ICHIDA bo'lsa (yoki yurish `COMPLETE` bo'lsa — paketsiz
             `COMPLETE` shartnomada MUMKIN EMAS) halol minimal paket QURILMAYDI va
             `result_dir=None` bo'lib qoladi. To'qima muhit hujjati yozib paketni «yaroqli»
             qilish TAQIQ: u «qaradim va 1C yo'q» degan YOLG'ON hukm bo'lib o'qilardi.
        """
        # ⚠️ ZOND YOZUVLARI HAM OLIB TASHLANADI (va bu OCHIQ aytiladi): har zond yozuvi O'Z
        #    natija faylini DA'VO qiladi, fayl esa ushlab qolingan `bundle/` ichida — ya'ni
        #    da'vo papkada YO'Q faylga ishora qilardi va paket shu sababdan rad etilardi
        #    (`result_package._check_status_cross_refs`). Zond BO'LGANI fakti tafsilotda
        #    SANOQ bilan qoladi: «yo'q edi» va «olib tashlandi» ARALASHTIRILMAYDI.
        zond_qaydi = ""
        if run.probes:
            zond_qaydi = (
                f" Zond yozuvlari ham olib tashlandi (soni: {len(run.probes)}) — ularning "
                f"natija fayllari AYNI ushlab qolingan `{rp.BUNDLE_SUBDIR}/` ichida edi."
            )
        tafsilot = (
            "Chiqishda shubhali qiymat TOPILDI va BUTUN natija paketi USHLAB QOLINDI "
            f"(qiymatning O'ZI hech qayerga yozilmadi). Topilgan joy(lar): {', '.join(sirli)}"
            f". Shu bois `{rp.BUNDLE_SUBDIR}/` ham, `{AI_CANDIDATES_FILE}` ham paketga "
            f"QO'SHILMADI, hisobot esa FAQAT yurish yozuvidan qayta qurildi.{zond_qaydi}"
        )
        papkasiz = RunOutcome(state=st.FAILED_REPORT, result_dir=None,
                              code=CODE_SIR_USHLANDI, detail=tafsilot,
                              problems=(xavfsiz_matn(e),))
        if self.environment is None:
            # ⚠️ Muhit hujjati uchun HALOL mazmun yo'q — `_ichki_xato` dagi AYNI chegara.
            return self._finish(papkasiz)
        try:
            # ⚠️ `replace` ATAYLAB: `status.with_bundle_dir` nisbiy NOM talab qiladi va
            #    da'voni QAYTARIB OLADIGAN metod yo'q (to'g'ri qaror — yozuv o'chirgich
            #    emas). Bu yerda esa da'vo papkaga MOS bo'lishi SHART, aks holda paket
            #    «yetim paket» sifatida rad etilardi. Yozuv keyin O'Z validatoridan o'tadi
            #    (`to_json`), ya'ni bu yo'l darvozani CHETLAB o'tmaydi.
            yozuv = replace(run, bundle_dir=None, artifacts=(), probes=())
            yozuv = (yozuv.with_artifacts(rp.ALWAYS_FILES)
                     .with_error(SCOPE_UI, CODE_SIR_USHLANDI, tafsilot)
                     .with_note(SIR_USHLANDI_IZOH))
            paket = rp.ResultPackage.from_parts(
                timestamp=timestamp,
                status_json=yozuv.to_json(),
                environment_json=det.dump_document(self.environment),
                report_md=reporter.build_report(status=yozuv),
            )
            root = paket.write(self.parent_dir)
        except Exception:  # noqa: BLE001
            # ⚠️ IKKINCHI YIQILISH JIM YUTILMAYDI: ekranda sababi (`problems`) va kodi
            #    qoladi. Yarim yozilgan papka esa `result_package` tufayli qolmaydi.
            return self._finish(papkasiz)
        problems = rp.check_result_package(root)
        if problems:
            return self._finish(RunOutcome(
                state=st.FAILED_REPORT, result_dir=root, code=CODE_PAKET_RAD,
                problems=tuple(xavfsiz_matn(p) for p in problems),
                detail="minimal sirsiz paket ham tekshiruvdan O'TMADI — paket UZATILMAYDI"))
        return self._finish(RunOutcome(state=st.FAILED_REPORT, result_dir=root,
                                       code=CODE_SIR_USHLANDI, detail=tafsilot,
                                       problems=(xavfsiz_matn(e),)))

    def _advance(self, run, holat: str, t: str, note: str = ""):
        """Bitta o'tish + progress. ⚠️ Ruxsat etilmagan o'tish — ISTISNO (`status` darvozasi)."""
        run = run.advance(holat, now=t, note=note)
        self._oxirgi_yozuv = run
        self._progress(holat)
        return run

    def _finish(self, outcome: RunOutcome) -> RunOutcome:
        self.last = outcome
        self._progress(outcome.state)
        return outcome

    def _progress(self, holat: str) -> None:
        """Progress — HOLAT NOMI (erkin matn emas: operator uni hisobotda ham ko'radi).

        ⚠️ AYNI holat ikki marta e'lon qilinmaydi: quvur zanjiri takrorlangandan keyin
           yakuniy holat yana bir marta kelishi mumkin, ekranda esa ikki bir xil qator
           «ikki marta bo'ldi» degan yolg'on taassurot berardi.
        """
        if holat == self.progress:
            return
        self.progress = holat
        if self.on_progress is not None:
            self.on_progress(holat)

    # ── Ochish ────────────────────────────────────────────────────────────────────────────
    def report_path(self) -> str | None:
        """Hisobot faylining yo'li (yurish bo'lmasa — `None`)."""
        if self.last is None or self.last.result_dir is None:
            return None
        return os.path.join(self.last.result_dir, REPORT_FILE)

    def open_report(self) -> str:
        yo_l = self.report_path()
        if yo_l is None:
            raise UiError("hisobot yo'q: avval «Start Discovery» ni bosing")
        return self._open(yo_l)

    def open_result_folder(self) -> str:
        if self.last is None or self.last.result_dir is None:
            raise UiError("natija papkasi yo'q: avval «Start Discovery» ni bosing")
        return self._open(self.last.result_dir)

    def _open(self, yo_l: str) -> str:
        """⚠️ FAQAT natija papkasi ICHIDAGI yo'l ochiladi.

        Sabab: «ochish» qobiliyati ixtiyoriy dastur ishga tushirish yo'liga aylanmasligi
        kerak. Darvoza yo'lni normallashtirib, natija papkasining ichida ekanini tekshiradi
        (`..` bilan chiqib ketishni ham to'sadi).
        """
        ildiz = self.last.result_dir if self.last else None
        if ildiz is None:
            raise UiError("natija papkasi yo'q")
        ildiz_abs = os.path.abspath(ildiz)
        nishon = os.path.abspath(yo_l)
        try:
            ichkarida = os.path.commonpath([ildiz_abs, nishon]) == ildiz_abs
        except ValueError:
            # ⚠️ Boshqa diskdagi yo'l: `commonpath` istisno beradi. FAIL-CLOSED — «noma'lum»
            #    ruxsatga aylanmaydi.
            ichkarida = False
        if not ichkarida:
            raise UiError("natija papkasidan TASHQARIDAGI yo'l ochilmaydi")
        if not os.path.exists(nishon):
            raise UiError("ochiladigan fayl yoki papka topilmadi")
        ochuvchi = self.opener if self.opener is not None else _default_opener
        ochuvchi(nishon)
        return nishon


def _default_opener(yo_l: str) -> None:  # pragma: no cover - OS qobig'iga bog'liq
    """Windows'da OS ning O'Z ochuvchisi. ⚠️ Faqat shu funksiya, boshqa buyruq YO'Q."""
    ochish = getattr(os, "startfile", None)
    if ochish is None:
        raise UiError("bu operatsion tizimda fayl ochish qo'llab-quvvatlanmaydi")
    ochish(yo_l)


# ══════════════════════════════════════════════════════════════════════════════════════════
# OYNA (faqat ko'rsatish)
# ══════════════════════════════════════════════════════════════════════════════════════════
class AgentWindow:
    """Bitta oyna. ⚠️ Hech qanday qaror qabul qilmaydi — `UiModel` ni ko'rsatadi."""

    def __init__(self, model: UiModel, *, root=None):  # pragma: no cover - vidjetlar
        if not TK_MAVJUD:
            raise UiError("tkinter bu muhitda yo'q — oyna ochilmaydi (CLI: "
                          "`python -m app.services.discovery_agent --headless <papka>`)")
        self.model = model
        self.root = root if root is not None else tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.var_install = tk.StringVar(value=model.install_line())
        self.var_target = tk.StringVar(value=model.target_line())
        self.var_progress = tk.StringVar(value=f"progress: {model.progress}")
        self.var_parent = tk.StringVar(value=model.parent_dir)
        # ⚠️ YO'L va KUTISH ekranda TURADI (brief §7 va §6C): operator «avtomatik bo'ldi»
        #    deb o'ylab qolmasligi va bo'sh papkada oynani «osilgan» deb o'qimasligi uchun.
        self.var_route = tk.StringVar(value=model.route_line())
        self.var_wait = tk.StringVar(value=model.wait_line())
        model.on_progress = self._on_progress
        model.on_wait = self._on_wait

        tk.Label(self.root, text=READ_ONLY_LABEL).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.root, textvariable=self.var_install).pack(anchor="w", padx=8)
        tk.Label(self.root, textvariable=self.var_target).pack(anchor="w", padx=8)
        tk.Label(self.root, textvariable=self.var_route, wraplength=520,
                 justify="left").pack(anchor="w", padx=8)
        for qadam in model.operator_steps():
            tk.Label(self.root, text=qadam, wraplength=520,
                     justify="left").pack(anchor="w", padx=8)
        self.listbox = tk.Listbox(self.root, height=5, width=70)
        self.listbox.pack(anchor="w", padx=8, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        qator = tk.Frame(self.root)
        qator.pack(anchor="w", padx=8, pady=4)
        tk.Label(qator, text="Natija papkasi:").pack(side="left")
        tk.Label(qator, textvariable=self.var_parent).pack(side="left")
        tk.Button(qator, text="Tanlash", command=self._on_pick_parent).pack(side="left", padx=4)

        tk.Button(self.root, text="Start Discovery",
                  command=self._on_start).pack(anchor="w", padx=8, pady=4)
        tk.Label(self.root, textvariable=self.var_progress).pack(anchor="w", padx=8)
        tk.Label(self.root, textvariable=self.var_wait, wraplength=520,
                 justify="left").pack(anchor="w", padx=8)
        tugmalar = tk.Frame(self.root)
        tugmalar.pack(anchor="w", padx=8, pady=(4, 8))
        tk.Button(tugmalar, text="Open Report",
                  command=self._on_open_report).pack(side="left")
        tk.Button(tugmalar, text="Open Result Folder",
                  command=self._on_open_folder).pack(side="left", padx=4)
        self._refresh()

    # ── Ichki ─────────────────────────────────────────────────────────────────────────────
    def _refresh(self) -> None:  # pragma: no cover - vidjetlar
        self.model.refresh_environment()
        self.var_install.set(self.model.install_line())
        self.var_target.set(self.model.target_line())
        self.listbox.delete(0, "end")
        for yorliq in self.model.target_labels():
            self.listbox.insert("end", yorliq)
        if self.model.selected_index is not None:
            self.listbox.selection_set(self.model.selected_index)

    def _on_progress(self, holat: str) -> None:  # pragma: no cover - vidjetlar
        self.var_progress.set(f"progress: {holat}")
        self.root.update_idletasks()

    def _on_wait(self, _tick) -> None:  # pragma: no cover - vidjetlar
        """⚠️ Kutish qatori YANGILANADI, lekin progress HOLATI o'zgarmaydi: kutish
        `METADATA_DISCOVERY` ICHIDA bo'ladi va yangi holat yaratmaydi."""
        self.var_wait.set(self.model.wait_line())
        self.root.update_idletasks()

    def _on_select(self, _event=None) -> None:  # pragma: no cover - vidjetlar
        tanlov = self.listbox.curselection()
        if tanlov:
            self.model.select_target(int(tanlov[0]))
            self.var_target.set(self.model.target_line())

    def _on_pick_parent(self) -> None:  # pragma: no cover - vidjetlar
        papka = filedialog.askdirectory(title="Natija papkasi qayerga qurilsin?")
        if papka:
            self.model.parent_dir = papka
            self.var_parent.set(papka)

    def _on_start(self) -> None:  # pragma: no cover - vidjetlar
        natija = self.model.start()
        if natija.is_failure:
            matn = natija.detail
            if natija.problems:
                matn += "\n\n" + "\n".join(f"- {p}" for p in natija.problems[:10])
            messagebox.showerror(natija.state, matn)
        else:
            messagebox.showinfo(natija.state, natija.detail)

    def _on_open_report(self) -> None:  # pragma: no cover - vidjetlar
        self._try(self.model.open_report)

    def _on_open_folder(self) -> None:  # pragma: no cover - vidjetlar
        self._try(self.model.open_result_folder)

    def _try(self, fn) -> None:  # pragma: no cover - vidjetlar
        try:
            fn()
        except UiError as e:
            messagebox.showwarning("Ochilmadi", xavfsiz_matn(e))

    def mainloop(self) -> None:  # pragma: no cover - vidjetlar
        self.root.mainloop()


def launch(*, parent_dir: str, bundle_dir: str | None = None,
           model: UiModel | None = None) -> int:  # pragma: no cover - vidjetlar
    """Oynani ochadi va operator yopguncha kutadi. Chiqish kodi: `0`.

    ⚠️ `tkinter` yo'q bo'lsa — `UiError`, jimgina «hech narsa bo'lmadi» EMAS.
    """
    if not TK_MAVJUD:
        raise UiError("tkinter bu muhitda yo'q — oyna ochilmaydi")
    window = AgentWindow(model if model is not None
                         else UiModel(parent_dir=parent_dir, bundle_dir=bundle_dir))
    window.mainloop()
    return 0


# ⚠️ IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI: quvurgacha bo'lgan zanjir holat mashinasidan
#    ajralib ketmasin. Testlar ham shuni qulflaydi, lekin import paytidagi darvoza eng
#    arzoni — testi yurgizilmagan yo'l ham shu yerdan o'tadi.
assert PRE_PIPELINE_CHAIN[0] == st.START or st.can_transition(st.START, PRE_PIPELINE_CHAIN[0]), \
    "PRE_PIPELINE_CHAIN `START` dan boshlanmaydi"
assert all(st.can_transition(a, b) for a, b in zip(PRE_PIPELINE_CHAIN,
                                                   PRE_PIPELINE_CHAIN[1:])), \
    "PRE_PIPELINE_CHAIN `states.TRANSITIONS` ga mos emas"
assert set(bridge.HINT_SOURCE_STATE.values()) <= set(PRE_PIPELINE_CHAIN), \
    "ko'prikning yiqilish manbalari zanjirda yo'q — `HINT_SOURCE_STATE` o'zgargan"
