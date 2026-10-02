# -*- coding: utf-8 -*-
"""Agent QUVURI — Phase 3/4 yadrosini TARTIB bilan CHAQIRADI, mantiqni QAYTA YOZMAYDI.

Qadamlar (har biri holat mashinasidagi O'Z holatida bajariladi):

    METADATA_DISCOVERY  (kirish holati — yig'uvchi ishini TUGATGAN deb hisoblanadi)
      -> VALIDATION      `runtime_bundle.validate_runtime_bundle` + `metadata.validate_metadata`
      -> GRAPH_BUILD     `graph.build_graph`
      -> ANALYSIS        `ai.analyst_payload` -> analitik -> `ai.validate_analysis`
                         -> `review.build_review`
      -> OPTIONAL_APPROVED_PROBES   (FAQAT operator tasdiqlagan zond bo'lsa)
      -> REVALIDATE      (zond paketni O'ZGARTIRGANI uchun QAYTA validatsiya)
      -> REPORT          `report.build_report`
      -> COMPLETE

⚠️⚠️ BU MODUL YADRONING MANTIQINI TAKRORLAMAYDI. Validator, graf, analitik, zond allowlisti,
     ko'rik artefakti va redaksiya — hammasi `..discovery_1c` da yashaydi va SHU YERDAN
     CHAQIRILADI. Qayta yozish regressiya bo'lardi: ikki nusxa bir kun bir-biridan ajralib
     ketadi va qaysi biri haqiqat ekani aniqlanmay qoladi.

QAT'IY QOIDALAR:
  · ⚠️ OFFLINE-FIRST MAJBURIY: `analyzer=None` bo'lsa DETERMINISTIK `HeuristicAnalyzer`
    ishlatiladi. Tarmoq chaqiruvi YO'Q, cloud AI YO'Q — analitik «mavjud bo'lmasa» ham quvur
    ISHLAYDI va bu REJIM, zaxira yo'l emas.
  · ⚠️ VALIDATOR CHIQISH KODI SHARTNOMASI (`discovery_1c.cli`: `0`/`1`/`2`) HURMAT QILINADI:
      `0` — paket to'g'ri VA yurish to'liq: quvur davom etadi;
      `1` — paketga ISHONIB BO'LMAYDI: `FAILED_VALIDATION`, tahlil QILINMAYDI;
      `2` — paket to'g'ri, LEKIN yurishning O'ZI to'liq emas: quvur TO'XTAYDI va buni
            `notes` da OCHIQ yozadi. ⚠️ JIMGINA DAVOM ETMAYDI: yarim yurishdan chiqarilgan
            xulosa to'liq xulosaga o'xshab ketardi va aynan shu narsa `UNKNOWN` ni
            `NOT_FOUND` ga aylantirardi.
    Kod `validator_exit_code()` da `cli` ning O'Z konstantalaridan quriladi, raqamlar bu
    yerda qaytadan yozilmaydi; test uni `cli.main` ning haqiqiy kodi bilan solishtirib
    qulflaydi.
  · ⚠️ ZOND FAQAT IKKI SHART BIR VAQTDA bajarilganda: (1) OPERATOR tasdiqlagan
    (`status.probes` da `APPROVED`/`EXECUTED` yozuvi bor) VA (2) `probe.validate_probe` dan
    o'tgan. MVP DA DEFAULT — ZOND YO'Q (`METADATA_ONLY`), ya'ni quvur `ANALYSIS` dan
    TO'G'RIDAN `REPORT` ga o'tadi.
  · ⚠️ QUVUR ZONDNI O'ZI BAJARMAYDI: u jarayon ochmaydi, 1C ga ulanmaydi va BSL bajarmaydi.
    Zond natijasi paket ICHIDA keladi (yig'uvchi bajargan). Natija yo'q bo'lsa —
    `FAILED_COLLECTOR_UNAVAILABLE` («1C bor, javob YO'Q»), «zond yo'q» EMAS.
  · ⚠️ AI `VERIFIED` BERMAYDI (`ai.FORBIDDEN_STATUS` darvozasi yadroda) va bu quvur
    `allow_human_confirmed=True` ni HECH QACHON uzatmaydi: `HUMAN_CONFIRMED` faqat
    `discovery_1c.confirmations` kanalidan keladi.
  · ⚠️ BU MODUL FAYL YOZMAYDI: `run_pipeline` artefakt BAYTLARINI qaytaradi
    (`PipelineResult.outputs`), yozish esa ALOHIDA `write_outputs()` bilan va ATAYLAB
    bajariladi (`status.py` dagi bilan AYNI sabab: yozmaydigan qadamni to'liq sinash mumkin).
  · ⚠️ VAQT KIRISHDAN: `now` — MAJBURIY parametr. Modul «hozir»ni O'ZI olmaydi, aks holda
    bir xil kirish bir xil bayt bermasdi. BITTA tamg'a butun yurishga qo'yiladi: quvur bir
    sinxron yurishda tugaydi, qadam-ba-qadam soat o'qish esa determinizmni buzardi.
  · ⚠️ TASHQI MATN `redact.redact` DAN O'TADI: validator nuqsoni ichida papka yo'li,
    analitik istisnosi ichida esa har qanday narsa bo'lishi mumkin. Absolyut yo'l yozilsa
    `status.to_json()` butun yozuvni RAD etardi — ya'ni yiqilishning sababi ham yo'qolardi.
  · TARMOQ YO'Q, TASHQI KUTUBXONA YO'Q (faqat stdlib), git YO'Q, 1C GA ULANISH YO'Q.

⚠️⚠️ RUNTIME HOLATI: bu mashinada 1C UMUMAN O'RNATILMAGAN, shu bois quvur HAQIQIY paketga
     qarshi sinalmagan — faqat SINTETIK runtime fiksturalariga qarshi
     (`tests/discovery_1c_runtime_mock.py`). «Ishlaydi» DEYILMAYDI: integratsiya yo'llari
     `RUNTIME-UNKNOWN`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import AGENT_STATUS_FILE, AI_CANDIDATES_FILE, BUNDLE_SUBDIR, REPORT_FILE
from . import states as st
from .report import ReportError, build_report
from .status import AgentStatus, AgentStatusError
from ..discovery_1c import ai
from ..discovery_1c import cli as core_cli
from ..discovery_1c import redact as redaction
from ..discovery_1c import review as core_review
from ..discovery_1c import runtime_bundle as rb
from ..discovery_1c.analyst.heuristics import HeuristicAnalyzer
from ..discovery_1c.graph import DiscoveryGraph, build_graph
from ..discovery_1c.metadata import validate_metadata
from ..discovery_1c.probe import ProbeError, validate_probe

#: Validator chiqish kodlari — MATN, `discovery_1c.cli` ning O'Z konstantalaridan.
#: ⚠️ Raqamlar bu yerda QAYTA YOZILMAYDI: ikki joyda yozilgan shartnoma bir kun ajralib
#: ketadi. `test_agent_pipeline` kodni `cli.main` ning haqiqiy natijasi bilan solishtiradi.
EXIT_OK = str(core_cli.EXIT_OK)
EXIT_INVALID = str(core_cli.EXIT_PROBLEM)
EXIT_INCOMPLETE = str(core_cli.EXIT_INCOMPLETE)

#: Xato `scope` qiymatlari — QAYSI qadam yiqilgani.
SCOPE_PIPELINE = "pipeline"
SCOPE_VALIDATION = "validation"
SCOPE_METADATA = "metadata"
SCOPE_GRAPH = "graph"
SCOPE_ANALYSIS = "analysis"
SCOPE_PROBES = "probes"
SCOPE_REVALIDATE = "revalidate"
SCOPE_REPORT = "report"

#: Zond yozuvining OPERATOR TASDIG'INI bildiradigan holatlari.
#: ⚠️ `PROPOSED` bu ro'yxatda YO'Q: taklif tasdiq EMAS. `DENIED`/`SKIPPED` ham yo'q —
#: operator RAD etgan yoki o'tkazib yuborilgan zond bajarilmaydi.
APPROVED_PROBE_STATUSES: frozenset[str] = frozenset({"APPROVED", "EXECUTED"})

#: Analitik o'z versiyasini E'LON QILMAGANDA yoziladigan qiymat.
#: ⚠️ RAQAM O'YLAB CHIQARILMAYDI: to'qima versiya ko'rikni aniq bir analitik yig'masiga
#: qarshi qayta tiklanadigan qilib KO'RSATARDI, holbuki u emas.
ANALYZER_VERSION_UNDECLARED = "UNDECLARED"

#: ⚠️ Yadroning hisobot turi SHU NOM bilan ishlatiladi: o'quvchi annotatsiyada «qanday
#: hisobot» degan savolga javobni AYNI JOYDA ko'rishi kerak, va bu nom yadrodan keladi —
#: bu yerda yangi tur E'LON QILINMAYDI.
Report = rb.Report


class PipelineError(ValueError):
    """Quvurni umuman boshlab bo'lmadi yoki yurish yozuvini yozib bo'lmadi.

    ⚠️ Bu ISTISNO quvurning NORMAL yiqilishi EMAS: normal yiqilish `FAILED_*` holatiga
       tushadi va `PipelineResult` bo'lib QAYTADI (operator uni o'qiy oladi). Istisno faqat
       yozuvning O'ZI mumkin bo'lmaganda chiqadi — bu nuqson, muhit muammosi emas."""


class _Stop(Exception):
    """ICHKI signal: quvur shu holatda TO'XTADI. Tashqariga CHIQMAYDI."""

    def __init__(self, state: str, *, scope: str, code: str, detail: str, note: str = ""):
        super().__init__(code)
        self.state = state
        self.scope = scope
        self.code = code
        self.detail = detail
        self.note = note


# ══════════════════════════════════════════════════════════════════════════════════════════
# NATIJA
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class PipelineResult:
    """Quvurning natijasi — O'ZGARMAS (frozen) yozuv.

    `status`   — YURISHNING yakuniy yozuvi (`COMPLETE` yoki aniq `FAILED_*`).
    `outputs`  — `(nisbiy nom, baytlar)` juftliklari, TARTIBLANGAN. ⚠️ Lug'at emas, TUPLE:
                 tartib chiqishning bir qismi va «bir xil kirish — bir xil bayt» kafolati
                 ro'yxatning navbatiga ham tegishli.
    `validation` / `validator_exit_code` — Phase 4 validatorining hisoboti va `0`/`1`/`2`.
    `revalidation` / `revalidation_exit_code` — zonddan keyingi QAYTA validatsiya (bo'lsa).
    `graph` / `hypotheses` / `review` — qadamlarning natijalari; yiqilgan qadamdan keyingisi
                 `None` yoki bo'sh bo'lib qoladi (JIM to'ldirish YO'Q).

    ⚠️ `ok` E'LON QILINMAYDI, HOLATDAN hisoblanadi: ikki joyda turgan haqiqat bir kun
       bir-biriga zid bo'ladi."""

    status: AgentStatus
    outputs: tuple[tuple[str, bytes], ...] = ()
    validation: Report | None = None
    validator_exit_code: str | None = None
    revalidation: Report | None = None
    revalidation_exit_code: str | None = None
    graph: DiscoveryGraph | None = None
    hypotheses: tuple = ()
    review: dict | None = None
    unresolved_references: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Quvur TO'LIQ tugadimi (`COMPLETE`). ⚠️ Boshqa har qanday holat — yiqilish."""
        return self.status.state == st.COMPLETE

    @property
    def state(self) -> str:
        return self.status.state

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(nom for nom, _ in self.outputs)

    def output(self, name: str) -> bytes | None:
        """Artefakt baytlari, yo'q bo'lsa `None` (jim bo'sh baytlar QAYTMAYDI)."""
        for nom, raw in self.outputs:
            if nom == name:
                return raw
        return None

    @property
    def report_text(self) -> str | None:
        """Hisobot matni, yozilmagan bo'lsa `None`."""
        raw = self.output(REPORT_FILE)
        return None if raw is None else raw.decode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════════════════
# CHIQISH KODI — `cli` SHARTNOMASIDAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def validator_exit_code(report: Report) -> str:
    """Validator hisobotining `0`/`1`/`2` kodi — MATN.

    ⚠️ TARTIB MUHIM va u `cli.main` dagi bilan AYNI: paket noto'g'ri bo'lsa uning E'LON
       QILGAN holati haqida gapirishdan foyda yo'q, chunki `overall` ning O'ZI ham shu
       paketdan keladi.
    ⚠️ `!= SUCCESS` deb yozilgan, `in (PARTIAL, FAILED)` deb EMAS: holat NOMA'LUM (`None`)
       bo'lsa ham javob `0` bo'lmasligi kerak (fail-closed)."""
    if not isinstance(report, rb.Report):
        raise PipelineError(
            f"validator_exit_code `runtime_bundle.Report` kutadi, kelgani "
            f"{type(report).__name__}")
    if not report.ok:
        return EXIT_INVALID
    if report.overall != rb.OVERALL_SUCCESS:
        return EXIT_INCOMPLETE
    return EXIT_OK


def _safe(text) -> str:
    """Tashqi matnni yozishga TAYYOR holga keltiradi (niqoblangan, bo'sh emas).

    ⚠️ NEGA NIQOBLASH SHU YERDA: xato tafsiloti tashqi manbadan keladi (validator nuqsoni,
       istisno matni) va uning ichida papka yo'li bo'lishi MUMKIN. `status.to_json()` esa
       absolyut yo'lni sir deb bilib BUTUN yozuvni rad etadi — ya'ni niqoblamasdan yozsak,
       yiqilishning SABABI ham yo'qolardi. Niqob qiymatni YASHIRMAYDI, ALMASHTIRADI: operator
       qiymat borligini ko'radi."""
    s = redaction.redact(str(text)).strip()
    return s if s else "tafsilot yo'q"


def _analyzer_identity(analyzer) -> tuple[str, str]:
    """Analitikning nomi va versiyasi — E'LON QILGANINI oladi, o'ylab CHIQARMAYDI."""
    nom = getattr(analyzer, "name", None) or type(analyzer).__name__
    versiya = getattr(analyzer, "version", None) or ANALYZER_VERSION_UNDECLARED
    return str(nom), str(versiya)


# ══════════════════════════════════════════════════════════════════════════════════════════
# QUVUR
# ══════════════════════════════════════════════════════════════════════════════════════════
class _Run:
    """Bitta yurishning ICHKI ish daftari — O'ZGARUVCHI (mutable) iskala.

    ⚠️ NEGA MUTABLE: qadamlar ketma-ket bajariladi va har biri yozuvni YANGILAYDI; holatni
       o'n marta qo'ldan-qo'lga uzatish kodni o'qishga xalaqit berardi. CHIQISH esa
       O'ZGARMAS: `AgentStatus` ham, `PipelineResult` ham frozen. Bu sinf moduldan
       TASHQARIGA chiqmaydi."""

    def __init__(self, bundle_dir: str, status: AgentStatus, analyzer, now: str):
        self.bundle_dir = bundle_dir
        self.status = status
        self.analyzer = HeuristicAnalyzer() if analyzer is None else analyzer
        self.analyzer_given = analyzer is not None
        self.now = now
        self.validation: Report | None = None
        self.exit_code: str | None = None
        self.revalidation: Report | None = None
        self.revalidation_exit_code: str | None = None
        self.metadata_doc: dict | None = None
        self.unresolved: tuple[str, ...] = ()
        self.graph: DiscoveryGraph | None = None
        self.hypotheses: tuple = ()
        self.review: dict | None = None
        self.bundle_mode: str | None = None
        self.bundle_probe_files: tuple[str, ...] = ()
        self.outputs: dict[str, bytes] = {}

    # ── Kichik yordamchilar ───────────────────────────────────────────────────────────────
    def advance(self, to: str, note: str = "") -> None:
        self.status = self.status.advance(to, now=self.now, note=note)

    def note(self, text: str) -> None:
        self.status = self.status.with_note(text)

    def stop(self, state: str, *, scope: str, code: str, detail: str, note: str = ""):
        raise _Stop(state, scope=scope, code=code, detail=detail, note=note)

    def _read_json(self, member: str, *, scope: str, state: str):
        """Paket ichidagi JSON faylni o'qiydi. Xato — ANIQ to'xtash (jim `None` YO'Q)."""
        yo_l = os.path.join(self.bundle_dir, *member.split("/"))
        try:
            with open(yo_l, "rb") as fh:
                xom = fh.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.stop(state, scope=scope, code="BUNDLE_MEMBER_UNREADABLE",
                      detail=f"`{member}` o'qilmadi: {_safe(e)}")
        try:
            return json.loads(xom)
        except ValueError as e:
            self.stop(state, scope=scope, code="BUNDLE_MEMBER_NOT_JSON",
                      detail=f"`{member}` JSON bo'lib o'qilmadi: {_safe(e)}")

    # ── 1 · VALIDATSIYA ───────────────────────────────────────────────────────────────────
    def step_validation(self) -> None:
        """Phase 4 validatori + inventarizatsiya sxemasi. ⚠️ `1` va `2` ni AJRATADI."""
        self.advance(st.VALIDATION,
                     note="Phase 4 validatori (`runtime_bundle`) ishga tushadi")
        self.validation = rb.validate_runtime_bundle(self.bundle_dir)
        self.exit_code = validator_exit_code(self.validation)

        if self.exit_code == EXIT_INVALID:
            self.stop(st.FAILED_VALIDATION, scope=SCOPE_VALIDATION, code="BUNDLE_INVALID",
                      detail="validator chiqish kodi 1: paketga ISHONIB BO'LMAYDI — "
                             + _safe("; ".join(self.validation.problems[:5])),
                      note="Tahlil BAJARILMADI: noto'g'ri paketdan chiqarilgan xulosa "
                           "noto'g'ri bo'ladi (chiqish kodi 1).")
        if self.exit_code == EXIT_INCOMPLETE:
            # ⚠️ PAKET TO'G'RI, YURISH TO'LIQ EMAS. Quvur SHU YERDA TO'XTAYDI va sababini
            #    OCHIQ yozadi. Davom etish yarim yurishdan to'liq ko'rinadigan hisobot
            #    yasardi — aynan shu narsa «qaralmadi» ni «yo'q» ga aylantiradi.
            self.stop(st.FAILED_VALIDATION, scope=SCOPE_VALIDATION,
                      code="BUNDLE_RUN_INCOMPLETE",
                      detail=f"validator chiqish kodi 2: paketning BAYTLARI to'g'ri, lekin "
                             f"yurish holati `overall`="
                             f"{self.validation.overall or 'NOMA`LUM'} — `SUCCESS` EMAS",
                      note="QUVUR TO'XTADI (chiqish kodi 2: paket to'g'ri, yurish TO'LIQ "
                           "EMAS). Bu `FAILED` dan FARQ QILADI: fayllar butun, lekin "
                           "yig'uvchi hamma bo'limni tugatmagan. Davom etilmadi — yarim "
                           "yurishdan chiqarilgan xulosa to'liq xulosaga o'xshab ketardi. "
                           "Sababni paketning `errors.json` idan o'qing.")

        # ⚠️ Paket to'g'ri, demak uning ichidagi JSON ham o'qiladi: rejim va zond fayllari
        #    keyingi qadamlarning darvozalari uchun KERAK.
        run_status = self._read_json(rb.RUN_STATUS_FILE, scope=SCOPE_VALIDATION,
                                    state=st.FAILED_VALIDATION)
        self.bundle_mode = run_status.get("mode")
        self.bundle_probe_files = self._probe_members()

        # ⚠️ IKKINCHI DARVOZA: `runtime_bundle` inventarizatsiyani allaqachon tekshirgan, shu
        #    bois bu chaqiruv sog'lom paketda YIQILMAYDI. U baribir bor, chunki quvurning
        #    O'ZI grafni shu hujjatdan quradi — «validator tekshirgan bo'lsa kerak» degan
        #    taxmin bilan emas.
        self.metadata_doc = self._read_json(rb.METADATA_FILE, scope=SCOPE_METADATA,
                                           state=st.FAILED_VALIDATION)
        try:
            self.unresolved = tuple(validate_metadata(self.metadata_doc))
        except Exception as e:                     # noqa: BLE001 — yadro xatosi ham, kutilmagani ham
            self.stop(st.FAILED_VALIDATION, scope=SCOPE_METADATA, code="METADATA_INVALID",
                      detail=f"`{rb.METADATA_FILE}` sxemasi: {_safe(e)}")
        if self.unresolved:
            self.note(f"Inventarizatsiyada {len(self.unresolved)} ta ANIQLANMAGAN havola "
                      f"bor. Bu NUQSON EMAS (konfiguratsiya bo'lak-bo'lak olingan bo'lishi "
                      f"mumkin), lekin JIMGINA tashlanmaydi — hisobotda sanab o'tiladi.")

    def _probe_members(self) -> tuple[str, ...]:
        """Paketdagi zond natijalarining nomlari (`probes/NN_<tur>.json`), TARTIBLANGAN."""
        papka = os.path.join(self.bundle_dir, rb.PROBE_DIR)
        if not os.path.isdir(papka):
            return ()
        return tuple(sorted(f"{rb.PROBE_DIR}/{n}" for n in os.listdir(papka)
                            if rb.PROBE_NAME_RE.fullmatch(f"{rb.PROBE_DIR}/{n}")))

    # ── 2 · GRAF ──────────────────────────────────────────────────────────────────────────
    def step_graph(self) -> None:
        """⚠️ Graf xatosi `FAILED_ANALYSIS` ga tushadi (holat jadvali shunday), chunki bu
        yerda PAKET emas, TALQIN yiqiladi: paketning o'zi joyida qoladi va tahlilni
        keyinroq, 1C siz ham qayta yurgizish mumkin."""
        self.advance(st.GRAPH_BUILD, note="`graph.build_graph` grafni quradi")
        try:
            self.graph = build_graph(self.metadata_doc)
        except Exception as e:                     # noqa: BLE001
            self.stop(st.FAILED_ANALYSIS, scope=SCOPE_GRAPH, code="GRAPH_BUILD_FAILED",
                      detail=f"graf qurilmadi: {_safe(e)}")

    # ── 3 · TAHLIL ────────────────────────────────────────────────────────────────────────
    def step_analysis(self) -> None:
        """Yuk -> analitik -> validator -> ko'rik artefakti.

        ⚠️ ANALITIK TASHQI KOD: u har qanday istisno tashlashi mumkin va u JIM YUTILMAYDI —
           `FAILED_ANALYSIS` ga tushadi, sababi esa xato yozuvida qoladi. «Bo'sh hisobot»
           bilan davom etish eng qimmat xato bo'lardi: operator tahlil bo'lmaganini
           BILMASDI.
        ⚠️ `validate_analysis` `allow_human_confirmed` ni OLMAYDI (ya'ni `False`):
           `HUMAN_CONFIRMED` AI kanalidan kelmaydi, u faqat operatorning ALOHIDA tasdiq
           hujjatidan tug'iladi. `VERIFIED` esa har qanday rejimda RAD."""
        self.advance(st.ANALYSIS, note="deterministik lokal analitik ishga tushadi "
                                       "(tarmoq YO'Q, cloud AI YO'Q)")
        if not self.analyzer_given:
            self.note("Analitik berilmadi, shu bois DETERMINISTIK `HeuristicAnalyzer` "
                      "ishlatildi: offline-first rejim MAJBURIY va u zaxira yo'l emas.")
        nom, versiya = _analyzer_identity(self.analyzer)
        try:
            yuk = ai.analyst_payload(self.graph)
            xom = self.analyzer.analyze(yuk)
            natija = ai.validate_analysis(xom, graph=self.graph)
            self.hypotheses = tuple(natija)
            self.review = core_review.build_review(
                natija, graph=self.graph, analyzer_name=nom, analyzer_version=versiya,
                analyzer_notes=ai.analysis_notes(natija),
                # ⚠️ `coverage=None` ATAYLAB («o'lchanmadi», «bo'sh» EMAS):
                #    `analyst.heuristics.coverage()` analitikni QAYTA yurgizadi, quvur esa
                #    uni AYNAN BIR MARTA chaqiradi — aks holda ko'rik bitta javobdan,
                #    qamrov esa boshqasidan qurilishi mumkin bo'lardi. Qamralmagan
                #    konseptlar baribir artefaktning `unknown_concepts` ida turadi.
                coverage=None)
            self.outputs[AI_CANDIDATES_FILE] = core_review.dumps_review(self.review)
        except Exception as e:                     # noqa: BLE001
            self.stop(st.FAILED_ANALYSIS, scope=SCOPE_ANALYSIS, code="ANALYSIS_FAILED",
                      detail=f"analitik qadami yakunlanmadi ({nom} {versiya}): {_safe(e)}",
                      note="Hisobot YOZILMADI: tahlilsiz hisobot bo'sh xaritaga o'xshab "
                           "ketardi. Paketning O'ZI joyida qoldi — tahlilni 1C siz, "
                           "keyinroq ham qayta yurgizish mumkin.")
        noma_lum = list(self.review.get("unknown_concepts") or [])
        self.note(f"Tahlil tugadi: {len(self.hypotheses)} ta gipoteza, "
                  f"{len(noma_lum)} ta konsept QARALMAGAN (`UNKNOWN`). «Qaralmadi» «yo'q» "
                  f"degani EMAS va ro'yxat hisobotda QOLADI.")

    # ── 4 · ZONDLAR (IXTIYORIY, FAQAT TASDIQLANGAN) ───────────────────────────────────────
    def step_probes(self) -> bool:
        """Tasdiqlangan zondlar bo'lsa `True`. ⚠️ MVP DA DEFAULT — `False` (zond YO'Q)."""
        tasdiqlangan = tuple(p for p in self.status.probes
                             if p.status in APPROVED_PROBE_STATUSES)
        paket_zondli = bool(self.bundle_probe_files) or \
            self.bundle_mode == rb.MODE_APPROVED_PROBES

        if not tasdiqlangan and not paket_zondli:
            self.note("Zond BAJARILMADI va rejalashtirilmadi: rejim "
                      f"`{rb.MODE_METADATA_ONLY}` — bu quvurning DEFAULT holati. Tahlil "
                      "tavsiya qilgan zondlar FAQAT ko'rik artefaktida TAKLIF bo'lib "
                      "qoladi va operator tasdig'isiz bajarilmaydi.")
            return False

        self.advance(st.OPTIONAL_APPROVED_PROBES,
                     note="tasdiqlangan zondlar darvozasi (katalog + graf + tasdiq)")
        if not tasdiqlangan:
            self.stop(st.FAILED_SAFETY, scope=SCOPE_PROBES, code="PROBE_NOT_APPROVED",
                      detail=f"paketda {len(self.bundle_probe_files)} ta zond natijasi bor "
                             f"(yoki rejim `{rb.MODE_APPROVED_PROBES}`), yurish yozuvida esa "
                             f"OPERATOR TASDIG'I YO'Q — tasdiqsiz bajarilgan zond xavfsizlik "
                             f"buzilishi",
                      note="Hech narsa o'zgartirilmadi. Zond kerak bo'lsa, uni operator "
                           "sifatida ALOHIDA tasdiqlab, yurishni qaytadan boshlang.")
        if not paket_zondli:
            self.stop(st.FAILED_SAFETY, scope=SCOPE_PROBES, code="PROBE_MODE_MISMATCH",
                      detail=f"operator {len(tasdiqlangan)} ta zondni tasdiqlagan, paket esa "
                             f"`{self.bundle_mode}` rejimida yozilgan va zond natijasi "
                             f"YO'Q — tasdiq boshqa yurishga tegishli bo'lishi mumkin")

        tavsiya = {(p.probe_type, p.target_object): p
                   for h in self.hypotheses for p in h.recommended_next_probe}
        for rec in tasdiqlangan:
            kalit = (rec.probe_type, rec.target_object)
            so_rov = tavsiya.get(kalit)
            if so_rov is None:
                # ⚠️ ALLOWLIST TASHQARISI: tahlil tavsiya qilmagan zond — kim so'raganini
                #    isbotlab bo'lmaydigan so'rov. Katalogda turgani YETMAYDI.
                self.stop(st.FAILED_SAFETY, scope=SCOPE_PROBES, code="PROBE_NOT_RECOMMENDED",
                          detail=f"tasdiqlangan zond `{rec.probe_type}` -> "
                                 f"`{rec.target_object}` tahlilning tavsiyalari ichida YO'Q")
            try:
                validate_probe(so_rov, graph=self.graph)
            except ProbeError as e:
                self.stop(st.FAILED_SAFETY, scope=SCOPE_PROBES, code="PROBE_REJECTED",
                          detail=f"`{rec.probe_type}` darvozadan o'tmadi: {_safe(e)}")
            kutilgan = f"{rb.PROBE_DIR}/" + rec.file.rsplit("/", 1)[-1]
            if kutilgan not in self.bundle_probe_files:
                # ⚠️ «1C BOR, JAVOB YO'Q» — bu `FAILED_COLLECTOR_UNAVAILABLE`, «zond yo'q»
                #    EMAS. Quvur zondni O'ZI bajarmaydi: u jarayon ochmaydi va 1C ga
                #    ulanmaydi, natija paket ichida kelishi kerak.
                self.stop(st.FAILED_COLLECTOR_UNAVAILABLE, scope=SCOPE_PROBES,
                          code="PROBE_RESULT_MISSING",
                          detail=f"tasdiqlangan zond `{rec.probe_type}` natijasi paketda "
                                 f"YO'Q: `{kutilgan}` topilmadi")
        self.note(f"{len(tasdiqlangan)} ta TASDIQLANGAN zondning natijasi paketda topildi va "
                  f"darvozadan o'tdi. Zondni quvur bajarmagan — u yig'uvchining ishi.")
        return True

    # ── 5 · QAYTA VALIDATSIYA ─────────────────────────────────────────────────────────────
    def step_revalidate(self) -> None:
        """⚠️ Zond paketni O'ZGARTIRGAN, demak paket QAYTA tekshiriladi: zonddan oldin
        tekshirilgan baytlar endi boshqa baytlar."""
        self.advance(st.REVALIDATE, note="zonddan keyin paket QAYTA tekshiriladi")
        self.revalidation = rb.validate_runtime_bundle(self.bundle_dir)
        self.revalidation_exit_code = validator_exit_code(self.revalidation)
        if self.revalidation_exit_code != EXIT_OK:
            self.stop(st.FAILED_VALIDATION, scope=SCOPE_REVALIDATE,
                      code="REVALIDATION_FAILED",
                      detail=f"qayta validatsiya chiqish kodi "
                             f"{self.revalidation_exit_code}: "
                             + _safe("; ".join(self.revalidation.problems[:5])
                                     or f"overall={self.revalidation.overall}"))

    # ── 6 · HISOBOT ───────────────────────────────────────────────────────────────────────
    def step_report(self) -> None:
        """Hisobot matni. ⚠️ Artefakt ro'yxati hisobotdan OLDIN to'ldiriladi: hisobot o'z
        yonidagi fayllarni sanab o'tishi kerak."""
        self.advance(st.REPORT, note="hisobot quriladi va sir darvozasidan o'tadi")
        self.status = self.status.with_artifacts(self._artifact_names())
        try:
            matn = build_report(status=self.status, review=self.review,
                                validation=self.validation, exit_code=self.exit_code,
                                revalidation=self.revalidation,
                                revalidation_exit_code=self.revalidation_exit_code,
                                unresolved_references=self.unresolved)
        except ReportError as e:
            # ⚠️ FAQAT `ReportError`: u hisobotning O'Z darvozalari (shakl + sir skani).
            #    Kutilmagan har qanday boshqa istisno `run_pipeline` ning umumiy
            #    qo'riqchisida `FAILED_INTERNAL` ga tushadi — chunki u NUQSON, «hisobot
            #    yozilmadi» degan muhit muammosi emas, va ikkisini bitta holatga qo'shib
            #    yuborish nuqsonni oddiy nosozlik qilib ko'rsatardi.
            self.stop(st.FAILED_REPORT, scope=SCOPE_REPORT, code="REPORT_FAILED",
                      detail=f"hisobot yozilmadi: {_safe(e)}")
        self.outputs[REPORT_FILE] = matn.encode("utf-8")

    def _artifact_names(self) -> tuple[str, ...]:
        """Quvur CHIQARGAN artefaktlar (nisbiy nom). ⚠️ `environment.json` va
        `agent_manifest.json` bu yerda YO'Q: ular muhit skaneri va manifest qatlamining
        ishi, manifest esa TO'LIQ papka ustidan ENG OXIRIDA quriladi."""
        nomlar = {AGENT_STATUS_FILE} | set(self.outputs)
        if self.status.state == st.REPORT:
            # ⚠️ Hisobot AYNI SHU qadamda yoziladi, ya'ni ro'yxatda turishi haqiqat.
            nomlar.add(REPORT_FILE)
        return tuple(sorted(nomlar))

    # ── Yakunlash ─────────────────────────────────────────────────────────────────────────
    def finish(self) -> PipelineResult:
        """Yakuniy yozuvni muhrlaydi va `agent_status.json` baytlarini chiqaradi."""
        self.status = self.status.with_artifacts(self._artifact_names())
        try:
            self.outputs[AGENT_STATUS_FILE] = self.status.to_json().encode("utf-8")
        except AgentStatusError as e:
            # ⚠️ Bu NUQSON: quvur yozadigan har bir matn `redact.redact` dan o'tgan, demak
            #    yozuv rad etilsa sabab kodda. Jimgina natija qaytarish yiqilishni
            #    yashirardi, shu bois ISTISNO.
            raise PipelineError(
                f"yurish yozuvi ({AGENT_STATUS_FILE}) yozib bo'lmadi — bu NUQSON: {e}") from e
        return PipelineResult(
            status=self.status,
            outputs=tuple(sorted(self.outputs.items())),
            validation=self.validation,
            validator_exit_code=self.exit_code,
            revalidation=self.revalidation,
            revalidation_exit_code=self.revalidation_exit_code,
            graph=self.graph,
            hypotheses=self.hypotheses,
            review=self.review,
            unresolved_references=self.unresolved,
        )


def run_pipeline(bundle_dir: str, *, status: AgentStatus, analyzer=None,
                 now: str) -> PipelineResult:
    """Quvurni ishga tushiradi: validatsiya -> graf -> analitik -> zond -> hisobot.

    `bundle_dir` — Phase 4 runtime PAKETINING papkasi (natija papkasidagi `bundle/`).
    `status`     — yurish yozuvi, `METADATA_DISCOVERY` holatida: yig'uvchi ishini tugatgan,
                   endi BinOS tomoni o'qiydi. ⚠️ Undan oldingi qadamlar (muhit skaneri,
                   nishon tanlash, xavfsizlik darvozasi) BOSHQA qatlamning ishi va bu modul
                   ularni O'YLAB CHIQARMAYDI.
    `analyzer`   — `ai.DiscoveryAIAnalyzer` protokoli. ⚠️ `None` bo'lsa DETERMINISTIK
                   `HeuristicAnalyzer`: offline-first rejim MAJBURIY, tarmoq ham, cloud AI
                   ham YO'Q.
    `now`        — ISO 8601 vaqt tamg'asi (offset bilan). ⚠️ KIRISHDAN: modul «hozir»ni o'zi
                   olmaydi, aks holda bir xil kirish bir xil bayt bermasdi.

    Qaytaradi: `PipelineResult`. ⚠️ ISTISNO TASHLAMAYDI (`PipelineError` dan boshqa): har
    qanday yiqilish ANIQ `FAILED_*` holatiga tushadi va natija bo'lib qaytadi — operator
    uni o'qiy olishi kerak, chaqiruvchi esa `except` yozishga majbur bo'lmasligi kerak.
    ⚠️ KUTILMAGAN istisno ham chiqmaydi: u `FAILED_INTERNAL` bo'lib YOZUVGA tushadi. Bu
    holat ANIQ ajratilgan — `FAILED_INTERNAL` «agentning O'ZIDA nuqson», qolgan `FAILED_*`
    esa muhit yoki paket haqidagi HUKM.
    ⚠️ HECH NARSA DISKKA YOZILMAYDI: artefakt baytlari `PipelineResult.outputs` da,
    yozish esa `write_outputs()` bilan ATAYLAB bajariladi."""
    if not isinstance(status, AgentStatus):
        raise PipelineError(
            f"run_pipeline `AgentStatus` kutadi, kelgani {type(status).__name__}")
    if not isinstance(bundle_dir, str) or not bundle_dir.strip():
        raise PipelineError("bundle_dir bo'sh bo'lmagan matn bo'lishi kerak")

    if status.state != st.METADATA_DISCOVERY:
        # ⚠️ Yakunlangan yurish QAYTA boshlanmaydi (`states` shartnomasi), shu bois undan
        #    hatto xato yozuvi ham chiqarib bo'lmaydi — chaqiruvchi yangi `run_id` olishi
        #    kerak.
        if st.is_terminal(status.state):
            raise PipelineError(
                f"yurish allaqachon {status.state} holatida yakunlangan — quvurni qaytadan "
                f"yurgizish uchun YANGI `run_id` bilan yangi yurish boshlanadi")
        qism = _Run(bundle_dir, status.with_bundle_dir(BUNDLE_SUBDIR), analyzer, now)
        qism.status = qism.status.with_error(
            SCOPE_PIPELINE, "PIPELINE_STATE_INVALID",
            f"quvur {st.METADATA_DISCOVERY} holatidan boshlanadi, kelgani {status.state} — "
            f"undan oldingi qadamlar BOSHQA qatlamning ishi va o'ylab chiqarilmaydi")
        qism.advance(st.FAILED_INTERNAL, note="quvur kirish holatini TEKSHIRDI va to'xtadi")
        return qism.finish()

    run = _Run(bundle_dir, status.with_bundle_dir(BUNDLE_SUBDIR), analyzer, now)
    try:
        run.step_validation()
        run.step_graph()
        run.step_analysis()
        if run.step_probes():
            run.step_revalidate()
        run.step_report()
        run.advance(st.COMPLETE, note="quvur TO'LIQ tugadi — natija TAXMIN, tasdiq EMAS")
    except _Stop as stop:
        run.status = run.status.with_error(stop.scope, stop.code, stop.detail)
        if stop.note:
            run.note(stop.note)
        run.advance(stop.state, note=f"{stop.scope}: {stop.code}")
    except Exception as e:                         # noqa: BLE001
        # ⚠️ KUTILMAGAN ISTISNO JIM YUTILMAYDI, lekin TASHQARIGA ham chiqmaydi: u
        #    `FAILED_INTERNAL` bo'lib YOZUVGA tushadi va operator natija papkasini
        #    ishlab chiquvchiga uzatа oladi. Bu holat ANIQ ajratilgan: `FAILED_INTERNAL`
        #    «agentning O'ZIDA nuqson» degani, qolgan `FAILED_*` esa muhit yoki paket
        #    haqidagi HUKM. Ikkisini aralashtirish nuqsonni nosozlik qilib ko'rsatardi.
        run.status = run.status.with_error(
            SCOPE_PIPELINE, "PIPELINE_INTERNAL_ERROR",
            f"kutilmagan istisno ({type(e).__name__}): {_safe(e)}")
        run.advance(st.FAILED_INTERNAL, note="quvurda KUTILMAGAN istisno — bu NUQSON, "
                                             "muhit muammosi emas; natija papkasini "
                                             "saqlab, ishlab chiquvchiga uzating")
    return run.finish()


# ══════════════════════════════════════════════════════════════════════════════════════════
# YOZISH (ATAYLAB ALOHIDA)
# ══════════════════════════════════════════════════════════════════════════════════════════
def write_outputs(result: PipelineResult, *, out_dir: str) -> tuple[str, ...]:
    """Quvur chiqargan artefaktlarni `out_dir` ga yozadi va yozilgan nomlarni qaytaradi.

    ⚠️ FAQAT QUVURNING O'Z ARTEFAKTLARI yoziladi: `agent_status.json`,
       `discovery_ai_candidates.json`, `discovery_report.md`. `environment.json` muhit
       skaneridan, `agent_manifest.json` esa manifest qatlamidan keladi va manifest TO'LIQ
       papka ustidan ENG OXIRIDA quriladi — shu bois bu funksiya papkani YAKUNLAMAYDI va
       bunday da'vo ham qilmaydi.
    ⚠️ Phase 4 paketiga TEGILMAYDI: u `bundle/` ostki papkasida O'ZGARMAGAN holda qoladi.
       Agent ildizda `manifest.json` YOZMAYDI — bir xil nom, ikki xil sxema Phase 4 da butun
       paketni rad etgan nuqson edi.
    ⚠️ Nomlar `PipelineResult.outputs` dan keladi va ular NISBIY (validator ham shuni
       talab qiladi), shu bois `out_dir` dan tashqariga yozish yo'li yo'q."""
    if not isinstance(result, PipelineResult):
        raise PipelineError(
            f"write_outputs `PipelineResult` kutadi, kelgani {type(result).__name__}")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise PipelineError("out_dir bo'sh bo'lmagan matn bo'lishi kerak")
    yozilgan: list[str] = []
    for nom, raw in result.outputs:
        if "\\" in nom or nom.startswith("/") or ".." in nom.split("/"):
            raise PipelineError(f"artefakt nomi nisbiy bo'lishi kerak: {nom!r}")
        yo_l = os.path.join(out_dir, *nom.split("/"))
        os.makedirs(os.path.dirname(yo_l) or out_dir, exist_ok=True)
        with open(yo_l, "wb") as fh:
            fh.write(raw)
        yozilgan.append(nom)
    return tuple(yozilgan)
