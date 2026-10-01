# -*- coding: utf-8 -*-
"""MINIMAL OPERATOR OYNASI (tkinter) — bitta oyna, bitta tugma.

Ko'rinadigan narsalar brief bo'yicha AYNAN shular:
    · aniqlangan 1C          · nishon infobaza        · READ ONLY holati
    · «Start Discovery»      · progress (holat nomi)
    · «Open Report»          · «Open Result Folder»

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import (AGENT_NAME, AGENT_STATUS_FILE, AGENT_VERSION, AI_CANDIDATES_FILE,
               ENVIRONMENT_FILE, REPORT_FILE, ROUTE_WATCH_FOLDER)
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
SCOPE_WATCH = "collector:watch_folder"
CODE_BUNDLE_DIR_MISSING = "BUNDLE_DIR_MISSING"
CODE_PAKET_RAD = "RESULT_PACKAGE_REJECTED"
CODE_PAKET_YOZILMADI = "RESULT_PACKAGE_WRITE_FAILED"
CODE_ICHKI_XATO = "AGENT_INTERNAL_ERROR"


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
    #: Analitik. ⚠️ `None` — DETERMINISTIK lokal evristika: offline-first MAJBURIY.
    analyzer: object | None = None
    opener: Callable[[str], None] | None = None
    now: Callable[[], str] = utc_now
    on_progress: Callable[[str], None] | None = None

    environment: det.EnvironmentScan | None = None
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

        ⚠️ YO'L TANLASH OPERATORDAN YASHIRILGAN, lekin YOZUVDA ochiq: ko'prik `batch_execute`
           dan boshlaydi, darvozasi yiqilsa `watch_folder` TAKLIF qiladi va bu
           `agent_status.json` ning `route`, `errors`, `notes` maydonlariga tushadi. Operator
           uchun bu BITTA workflow: bitta tugma.
        ⚠️ HOLATNI UI E'LON QILMAYDI: yakuniy holat `pipeline` (yoki ko'prikning `state_hint`
           i) qaytargan `AgentStatus` dan keladi. UI faqat natija PAPKASINI tekshiradi.
        ⚠️ JIMGINA MUVAFFAQIYAT YO'Q: paket rad etilsa yoki yozilmasa — `FAILED_REPORT`.
        """
        t = self.now()
        try:
            timestamp = rp.compact_timestamp(t)
        except rp.ResultPackageError as e:
            # ⚠️ Soat noto'g'ri qiymat berdi — bu NUQSON, muhit muammosi emas.
            return self._finish(RunOutcome(state=st.FAILED_INTERNAL, result_dir=None,
                                           code=CODE_ICHKI_XATO, detail=xavfsiz_matn(e)))
        try:
            run, bundle_dir = self._collect(agent_status.new_run(f"run-{timestamp}", now=t), t)
            natija = None
            if bundle_dir is not None:
                qadam = len(run.transitions)
                # ⚠️ Quvur ISTISNO TASHLAMAYDI: har qanday yiqilish ANIQ `FAILED_*` bo'lib
                #    yozuvga tushadi va natija bo'lib qaytadi (uning shartnomasi).
                natija = pipe.run_pipeline(bundle_dir, status=run, analyzer=self.analyzer,
                                           now=t)
                run = natija.status
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
            return self._finish(RunOutcome(
                state=st.FAILED_INTERNAL, result_dir=None, code=CODE_ICHKI_XATO,
                detail=f"{type(e).__name__}: {xavfsiz_matn(e)}"))

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
        for xato in env.errors():
            # ⚠️ `_error_code` izohiga qarang: `detector` kodlari kichik harfda, yurish
            #    yozuvi esa KATTA harf talab qiladi.
            run = run.with_error(xato["scope"], _error_code(xato["code"]), xato["detail"])

        plan = self._plan(env)
        if plan is None:
            # ── Paket ALLAQACHON yozilgan: operator yig'uvchini O'ZI yurgizgan ────────────
            run = run.with_route(ROUTE_WATCH_FOLDER)
            for holat in (st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY):
                run = self._advance(run, holat, t)
            if not self._bundle_bor():
                # ⚠️ «Paket yo'q» — `FAILED_COLLECTOR_UNAVAILABLE`: javob YO'Q. Bu
                #    `FAILED_NO_1C` EMAS — 1C bor-yo'qligi haqida hech narsa demaydi.
                # ⚠️ BO'SH papka ham «paket yo'q»: aks holda quvur bo'sh paket ustida
                #    yurib `FAILED_VALIDATION` berardi, yurish yozuvi esa mavjud bo'lmagan
                #    paketni DA'VO qilib qolardi (`bundle_dir` to'ladi, ichida hech narsa
                #    yo'q) — ya'ni yozuv o'z-o'ziga zid bo'lardi.
                run = run.with_error(SCOPE_WATCH, CODE_BUNDLE_DIR_MISSING,
                                     "kuzatilgan papka ko'rsatilmadi, topilmadi yoki BO'SH — "
                                     "yig'uvchi natija bermadi (javob YO'Q). Keyingi qadam: "
                                     "yig'uvchini 1C sessiyangizda bajarib, chiqish "
                                     "papkasini ko'rsating")
                return self._advance(run, st.FAILED_COLLECTOR_UNAVAILABLE, t), None
            return run, self.bundle_dir

        # ── Ko'prik yo'li ────────────────────────────────────────────────────────────────
        yiqildi = bridge.preflight(plan)
        if yiqildi is not None:
            manzil = bridge.HINT_SOURCE_STATE[yiqildi.state_hint]
            for holat in PRE_PIPELINE_CHAIN[PRE_PIPELINE_CHAIN.index(run.state) + 1:]:
                run = self._advance(run, holat, t)
                if holat == manzil:
                    break
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
            infobase_kind=nishon.kind if nishon is not None else None,
            infobase_locator=nishon.locator if nishon is not None else None,
            requires_auth=nishon.requires_auth if nishon is not None else det.TRI_UNKNOWN,
            mode=self.mode,
        )

    def _bundle_bor(self) -> bool:
        """Operator ko'rsatgan papkada ROSTDAN fayl bormi (bo'sh papka — paket EMAS)."""
        if not (isinstance(self.bundle_dir, str) and os.path.isdir(self.bundle_dir)):
            return False
        try:
            return any(True for _ in os.scandir(self.bundle_dir))
        except OSError:
            # ⚠️ O'qilmadi — FAIL-CLOSED: «noma'lum» «bor» ga aylanmaydi.
            return False

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
        """
        # ⚠️ Phase 4 paketi ko'prik bergan (yoki operator ko'rsatgan) papkadan BAYT-BA-BAYT
        #    ko'chiriladi va O'ZGARTIRILMAYDI. Manba papkaga TEGILMAYDI — faqat o'qiladi.
        bundle = {} if bundle_dir is None else rp.read_folder_bytes(bundle_dir)
        ai = None if natija is None else natija.output(AI_CANDIDATES_FILE)

        nomlar = [AGENT_STATUS_FILE, rp.AGENT_MANIFEST_FILE, ENVIRONMENT_FILE, REPORT_FILE]
        if ai is not None:
            nomlar.append(AI_CANDIDATES_FILE)
        nomlar += [f"{rp.BUNDLE_SUBDIR}/{n}" for n in bundle]
        run = run.with_artifacts(nomlar)

        hisobot = None if natija is None else natija.report_text
        if hisobot is None:
            # ⚠️ Quvur hisobotga YETMAGAN bo'lsa (yoki umuman chaqirilmagan bo'lsa) hisobot
            #    SHU YERDA quriladi: yiqilgan yurish ham hisobotsiz qolmaydi
            #    (`states.FAILURE_MEANING` operatorga aynan hisobotni uzatishni aytadi).
            # ⚠️ ARTEFAKT RO'YXATI YAKUNLANGANDAN KEYIN: hisobot o'z yonidagi fayllarni
            #    to'liq sanab o'tishi kerak (`pipeline.step_report` dagi AYNI tartib).
            hisobot = reporter.build_report(
                status=run,
                validation=None if natija is None else natija.validation,
                exit_code=None if natija is None else natija.validator_exit_code)

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
        return self._finish(RunOutcome(state=run.state, result_dir=root,
                                       detail="natija paketi tekshiruvdan o'tdi"))

    def _advance(self, run, holat: str, t: str, note: str = ""):
        """Bitta o'tish + progress. ⚠️ Ruxsat etilmagan o'tish — ISTISNO (`status` darvozasi)."""
        run = run.advance(holat, now=t, note=note)
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
        model.on_progress = self._on_progress

        tk.Label(self.root, text=READ_ONLY_LABEL).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(self.root, textvariable=self.var_install).pack(anchor="w", padx=8)
        tk.Label(self.root, textvariable=self.var_target).pack(anchor="w", padx=8)
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
