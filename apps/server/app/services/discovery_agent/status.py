# -*- coding: utf-8 -*-
"""`agent_status.json` — `binos-agent-run-v1`: yurish yozuvi, qat'iy validator, deterministik yozish.

Bu fayl — agent yurishining YAGONA rasmiy yozuvi: qaysi holatda, qaysi yo'l bilan, qanday
artefakt chiqargani va NEGA to'xtagani. Shu bois u hisobotdan ham muhim: hisobotni odam
o'qiydi, bu faylni esa boshqa kod ham o'qiydi.

SHAKL ARXITEKTOR TOMONIDAN QOTIRILGAN va o'z-o'zidan «yaxshilanmaydi».
⚠️⚠️ NEGA SHUNCHA QAT'IY: Phase 4 da artefakt JADVALI berilgan, lekin KALIT NOMLARI
     berilmagan edi — ikki agent bo'shliqni har xil to'ldirdi va 1764 test yashil bo'lsa ham
     har bir real paket rad etilardi. Shu bois bu yerda noma'lum kalit ham, TUSHIB QOLGAN
     kalit ham RAD etiladi: «kalit yo'q» degan shakl keyinroq jimgina boshqa ma'no oladi.
⚠️ `schema_version` nomli kalit ATAYLAB YO'Q: shartnomada yetgizilgan kalit ro'yxati AYNAN
   o'n yettita va unga «aniqroq bo'lsin» deb maydon qo'shish — Phase 4 ni yiqitgan aynan shu
   bir tomonlama «yaxshilash». Sxema o'zligi FAYL NOMI va `agent_version` bilan beriladi,
   nomi esa `RUN_VERSION` konstantasida (xato matnlarida ko'rinadi).

KUCHGA KIRITILADIGAN INVARIANTLAR:
  1. JSON SONI va JSON BOOLEANI HECH QAYERDA yo'q. Har qanday sanoq — MATN ("3"), uchulik
     mantiq — MATN ("true"/"false"/"unknown"). Sabab yadrodagi bilan AYNI: `0000123` soni
     `123` bo'lib qoladi, boolean esa uchinchi holatni JIMGINA yo'q qiladi.
  2. `read_only` DOIM `"true"`. Uni o'zgartiradigan YO'L YO'Q: maydon ham emas, `replace`
     ham tegmaydi (`AgentStatus` — frozen dataclass, `read_only` esa XOSSA).
  3. O'tishlar ZANJIR: birinchisi `START` dan, har biri oldingisining davomidan, oxirgisining
     nishoni — joriy holat. Har bir o'tish `states.assert_transition` dan o'tadi.
  4. `terminal` e'lon qilinmaydi — HOLATDAN hisoblanadi va mos kelishi SHART.
  5. Vaqt tamg'alari KIRISHDAN keladi (`now` parametri). Modul «hozir»ni O'ZI o'ylab
     chiqarmaydi: aks holda na determinizm, na test bo'ladi. Vaqt ORQAGA ketmaydi.
  6. Zond yozuvi faqat `APPROVED_PROBES` rejimida bo'ladi (`METADATA_ONLY` + zond — o'z-o'ziga
     zid hujjat, yadrodagi `validate_probe_result` ham AYNI qoidani qo'yadi).
  7. Sir topilsa — RAD (`discovery_1c.redact.scan`), fail-closed. Yo'llar NISBIY: natija
     papkasidan tashqariga ishora qiladigan yoki absolyut yo'l RAD etiladi.

⚠️ BU MODUL FAYL YOZMAYDI va vaqt olmaydi: u faqat MATN qaytaradi (`to_json()`). Yozish —
   chaqiruvchining ishi. Sabab: yozmaydigan modulni to'liq sinash mumkin, va «chiqishga
   yozishdan oldin tekshir» qoidasi shu bilan buzilmas bo'ladi.
⚠️ 1C bu yerda ham YO'Q: `route` qiymati faqat QAYD, da'vo emas — ikki integratsiya yo'li
   ham `RUNTIME-UNKNOWN`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from . import AGENT_NAME, AGENT_VERSION, ROUTES, RUN_VERSION
from . import states as st
from ..discovery_1c import redact as redaction
from ..discovery_1c.bundle import dumps
from ..discovery_1c.probe import PROBE_CATALOG
from ..discovery_1c.runtime_bundle import MODES, MODE_APPROVED_PROBES, MODE_METADATA_ONLY
from ..migrator_1c.bundle import BundleError, parse_ts

#: `read_only` ning YAGONA qiymati. ⚠️ Konstanta sifatida bitta joyda: ikki joyda yozilgan
#: «true» bir kun bittasi `True` bo'lib ketadi.
READ_ONLY = "true"

#: Hujjatning kalitlari — AYNAN shular (noma'lum RAD, tushib qolgan RAD).
AGENT_STATUS_KEYS: frozenset[str] = frozenset({
    "agent_version", "run_id", "started_at", "finished_at", "state", "terminal", "route",
    "mode", "read_only", "transitions", "environment_file", "bundle_dir", "artifacts",
    "probes", "errors", "notes",
})
AGENT_VERSION_KEYS: frozenset[str] = frozenset({"name", "version"})
TRANSITION_KEYS: frozenset[str] = frozenset({"from", "to", "at", "note"})
PROBE_KEYS: frozenset[str] = frozenset({"no", "probe_type", "target_object", "reason", "file",
                                        "status"})
ERROR_KEYS: frozenset[str] = frozenset({"scope", "code", "detail"})

#: Zond yozuvining holatlari. ⚠️ Arxitektor bu LUG'ATNI bermagan, shu bois u SHU YERDA
#: e'lon qilinadi va keyin O'ZGARMAYDI — noma'lum qiymat RAD (fail-closed). Ajrim muhim:
#: `PROPOSED` — analitik taklif qildi, `APPROVED` — operator tasdiqladi lekin bajarilmadi,
#: `EXECUTED` — bajarildi, `SKIPPED` — tasdiqlanmagani uchun o'tkazib yuborildi,
#: `DENIED` — operator RAD etdi, `FAILED` — bajarilib xato berdi. «Tasdiqlandi» va
#: «bajarildi» ni bitta qiymatga qo'shish operator tasdig'ining izini yo'q qiladi.
PROBE_STATUSES: tuple[str, ...] = ("APPROVED", "DENIED", "EXECUTED", "FAILED", "PROPOSED",
                                  "SKIPPED")

#: `run_id` — fayl nomiga ham tushadigan qiymat, shu bois ASCII va yo'l belgilarisiz.
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,63}")
#: Sanoq — ASCII raqamli MATN (yadrodagi `COUNT_TEXT_RE` bilan AYNI qoida).
COUNT_TEXT_RE = re.compile(r"[0-9]{1,18}")
#: Xato kodi — BARQAROR, MOSHINA O'QIYDIGAN belgi (tarjima qilinadigan matn emas).
ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,47}")


class AgentStatusError(ValueError):
    """`binos-agent-run-v1` shakli yoki invarianti buzilgan."""


# ══════════════════════════════════════════════════════════════════════════════════════════
# KICHIK YORDAMCHILAR (yadrodagi shakl bilan bir xil, boshqa xato turi)
# ══════════════════════════════════════════════════════════════════════════════════════════
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise AgentStatusError(msg)


def _keys(obj, allowed: frozenset[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = set(obj) - allowed
    _need(not extra, f"{where}: noma'lum kalit(lar) {sorted(extra)} — {RUN_VERSION} da yo'q")
    missing = allowed - set(obj)
    _need(not missing, f"{where}: kalit(lar) yetishmayapti {sorted(missing)}")


def _nonempty(obj: dict, key: str, where: str) -> str:
    v = obj.get(key)
    _need(isinstance(v, str) and v.strip() != "",
          f"{where}.{key} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _str_or_none(obj: dict, key: str, where: str):
    v = obj.get(key)
    _need(v is None or isinstance(v, str), f"{where}.{key} matn yoki null bo'lishi kerak")
    return v


def _str_list(v, where: str) -> None:
    _need(isinstance(v, list) and all(isinstance(x, str) for x in v),
          f"{where} matnlar ro'yxati bo'lishi kerak")


def _ts(obj: dict, key: str, where: str):
    """ISO 8601 (offset bilan) matnni vaqtga aylantiradi."""
    try:
        return parse_ts(obj.get(key), f"{where}.{key}")
    except BundleError as e:
        raise AgentStatusError(str(e)) from e


def _rel_path(v, where: str) -> None:
    """Natija papkasi ICHIDAGI nisbiy yo'l.

    ⚠️ NEGA QAT'IY: (1) absolyut yo'l do'kon mashinasining tuzilmasini oshkor qiladi va
    `redact` uni sir deb RAD etadi — ya'ni absolyut yo'l yozgan kod chiqishni butunlay
    bloklaydi; (2) `..` papkadan tashqariga chiqadi, manifest esa faqat papka ichini
    xeshlaydi — tashqaridagi fayl hisobga olinmay qoladi; (3) teskari slesh platformaga
    bog'liq, demak determinizmni buzadi.
    """
    _need(isinstance(v, str) and v.strip() != "", f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    _need("\\" not in v, f"{where}: teskari slesh YO'Q, yo'l `/` bilan yoziladi: {v!r}")
    _need(not v.startswith("/"), f"{where}: nisbiy yo'l bo'lishi kerak: {v!r}")
    _need(not re.match(r"^[A-Za-z]:", v), f"{where}: absolyut yo'l YO'Q: {v!r}")
    _need(".." not in v.split("/"), f"{where}: `..` bo'lagi YO'Q: {v!r}")


def _scalar_paths(node, path: str) -> list[str]:
    """JSON SONI yoki `true`/`false` turgan yo'llar (tartiblangan, takrorsiz).

    ⚠️ Yadroda (`runtime_bundle`) AYNI qoida bor, lekin u YOPIQ yordamchi. Qoida bitta:
    hujjatda son ham, boolean ham bo'lmaydi — faqat matn va `null`.
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


def assert_no_secrets(doc) -> None:
    """Chiqishda sir bo'lmasligi — FAIL-CLOSED darvoza.

    ⚠️ Xato matnida QIYMATNING O'ZI ko'rsatilmaydi (`redact.Finding.__str__` qoidasi):
    bu xabar jurnalga tushadi, jurnal esa qo'ldan-qo'lga o'tadi.
    ⚠️ «Avval niqobla, keyin yoz» YO'LI emas, «topilsa RAD» yo'li tanlangan: niqoblash
    yozuvni jimgina o'zgartiradi va operator qaysi qiymat yo'qolganini bilmaydi. Chaqiruvchi
    `redact.redact` ni O'ZI, ATAYLAB qo'llashi kerak (masalan `locator` uchun).
    """
    topilgan = redaction.scan(doc)
    _need(not topilgan,
          f"{RUN_VERSION}: chiqishda shubhali qiymat(lar) topildi, yozish RAD etildi — "
          f"{[str(f) for f in topilgan]}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════════════════
def validate_agent_status(doc) -> None:
    """`binos-agent-run-v1` hujjatini to'liq tekshiradi (shakl + invariantlar + sir)."""
    _keys(doc, AGENT_STATUS_KEYS, "agent_status")

    yo_llar = _scalar_paths(doc, "")
    _need(not yo_llar,
          f"agent_status: JSON soni/booleani TAQIQLANGAN (qiymatni MATN qilib yozing) — "
          f"{yo_llar}")

    _keys(doc["agent_version"], AGENT_VERSION_KEYS, "agent_status.agent_version")
    _nonempty(doc["agent_version"], "name", "agent_status.agent_version")
    _nonempty(doc["agent_version"], "version", "agent_status.agent_version")

    run_id = _nonempty(doc, "run_id", "agent_status")
    _need(RUN_ID_RE.fullmatch(run_id) is not None,
          f"agent_status.run_id ASCII harf/raqam/`.`/`_`/`-` dan iborat bo'lishi kerak "
          f"(fayl nomiga ham tushadi): {run_id!r}")

    boshlandi = _ts(doc, "started_at", "agent_status")
    tugadi = None
    if doc["finished_at"] is not None:
        tugadi = _ts(doc, "finished_at", "agent_status")
        _need(tugadi >= boshlandi, "agent_status.finished_at `started_at` dan oldin bo'lmaydi")

    holat = doc["state"]
    _need(isinstance(holat, str) and st.is_known(holat),
          f"agent_status.state noma'lum holat: {holat!r}")
    yakuniy = st.is_terminal(holat)
    _need(doc["terminal"] in ("true", "false"),
          f"agent_status.terminal AYNAN `\"true\"` yoki `\"false\"` MATNI bo'lishi kerak "
          f"(JSON booleani EMAS), kelgani {doc['terminal']!r}")
    # ⚠️ `terminal` E'LON EMAS, HOSILA: holat bilan mos kelmasa — hujjat o'z-o'ziga zid.
    _need(doc["terminal"] == ("true" if yakuniy else "false"),
          f"agent_status.terminal holatga mos emas: {holat} uchun "
          f"{'true' if yakuniy else 'false'!r} bo'lishi kerak, kelgani {doc['terminal']!r}")
    # ⚠️ Yakunlangan yurishning tugash vaqti BOR, yakunlanmaganining YO'Q. «Tugadi, lekin
    #    qachon — bilmayman» degan yozuv keyin hech qachon tiklanmaydi.
    kutilgan_tugash = "vaqt" if yakuniy else "null"
    _need((doc["finished_at"] is not None) == yakuniy,
          f"agent_status.finished_at: {holat} holati uchun {kutilgan_tugash} bo'lishi kerak")

    _need(doc["read_only"] == READ_ONLY,
          f"agent_status.read_only AYNAN {READ_ONLY!r} MATNI bo'lishi kerak, kelgani "
          f"{doc['read_only']!r} — yozadigan agent mavjud emas va bo'lishi ham mumkin emas")

    _need(doc["route"] is None or doc["route"] in ROUTES,
          f"agent_status.route {sorted(ROUTES)} dan biri yoki null bo'lishi kerak, kelgani "
          f"{doc['route']!r}")
    _need(doc["mode"] in MODES,
          f"agent_status.mode {sorted(MODES)} dan biri bo'lishi kerak, kelgani {doc['mode']!r}")

    _validate_transitions(doc, boshlandi, holat)

    for kalit in ("environment_file", "bundle_dir"):
        agar = _str_or_none(doc, kalit, "agent_status")
        if agar is not None:
            _rel_path(agar, f"agent_status.{kalit}")

    _str_list(doc["artifacts"], "agent_status.artifacts")
    for i, nom in enumerate(doc["artifacts"]):
        _rel_path(nom, f"agent_status.artifacts[{i}]")
    _need(len(set(doc["artifacts"])) == len(doc["artifacts"]),
          "agent_status.artifacts: nom takrorlangan")
    # ⚠️ TARTIB MAJBURIY TARTIBLANGAN: papka ro'yxatining tabiiy tartibi OS va fayl
    #    tizimiga bog'liq, ya'ni aynan shu joy «bir xil kirish — bir xil bayt» ni buzadi.
    _need(list(doc["artifacts"]) == sorted(doc["artifacts"]),
          "agent_status.artifacts tartiblangan bo'lishi kerak (determinizm)")

    _validate_probes(doc)

    _need(isinstance(doc["errors"], list), "agent_status.errors ro'yxat bo'lishi kerak")
    for i, xato in enumerate(doc["errors"]):
        w = f"agent_status.errors[{i}]"
        _keys(xato, ERROR_KEYS, w)
        _nonempty(xato, "scope", w)
        kod = _nonempty(xato, "code", w)
        _need(ERROR_CODE_RE.fullmatch(kod) is not None,
              f"{w}.code BARQAROR belgi bo'lishi kerak (`[A-Z][A-Z0-9_]+`): {kod!r}")
        _nonempty(xato, "detail", w)

    _str_list(doc["notes"], "agent_status.notes")

    # ⚠️ ENG OXIRIDA: shakl to'g'ri bo'lsa ham sir bo'lsa — yozish RAD.
    assert_no_secrets(doc)


def _validate_transitions(doc, boshlandi, holat: str) -> None:
    """O'tishlar ZANJIRI: `START` dan joriy holatgacha, uzilishsiz va ruxsat etilgan."""
    rows = doc["transitions"]
    _need(isinstance(rows, list), "agent_status.transitions ro'yxat bo'lishi kerak")
    if not rows:
        # ⚠️ Bo'sh zanjir FAQAT hali qadam qo'yilmagan yurishda bo'ladi.
        _need(holat == st.START,
              f"agent_status.transitions bo'sh, lekin holat {holat} — {st.START} dan boshqa "
              f"holatga o'tish IZSIZ bo'lmaydi")
        return

    oldingi_vaqt = boshlandi
    for i, row in enumerate(rows):
        w = f"agent_status.transitions[{i}]"
        _keys(row, TRANSITION_KEYS, w)
        manba, nishon = row["from"], row["to"]
        for kalit, qiymat in (("from", manba), ("to", nishon)):
            _need(isinstance(qiymat, str) and st.is_known(qiymat),
                  f"{w}.{kalit} noma'lum holat: {qiymat!r}")
        try:
            st.assert_transition(manba, nishon)
        except st.TransitionError as e:
            raise AgentStatusError(f"{w}: {e}") from e
        vaqt = _ts(row, "at", w)
        _need(vaqt >= oldingi_vaqt,
              f"{w}.at vaqt ORQAGA ketdi — yurish yozuvi vaqt bo'yicha o'sib borishi kerak")
        oldingi_vaqt = vaqt
        _need(isinstance(row["note"], str), f"{w}.note matn bo'lishi kerak (bo'sh bo'lsa ham)")
        kutilgan = st.START if i == 0 else rows[i - 1]["to"]
        _need(manba == kutilgan,
              f"{w}.from zanjirni uzdi: {kutilgan!r} kutilgan edi, {manba!r} keldi")

    _need(rows[-1]["to"] == holat,
          f"agent_status.state oxirgi o'tishga mos emas: zanjir {rows[-1]['to']!r} da "
          f"tugaydi, `state` esa {holat!r}")
    if doc["finished_at"] is not None:
        _need(_ts(doc, "finished_at", "agent_status") >= oldingi_vaqt,
              "agent_status.finished_at oxirgi o'tishdan oldin bo'lmaydi")


def _validate_probes(doc) -> None:
    """Zond yozuvlari. ⚠️ Zond — FAQAT `APPROVED_PROBES` rejimida."""
    rows = doc["probes"]
    _need(isinstance(rows, list), "agent_status.probes ro'yxat bo'lishi kerak")
    if rows:
        _need(doc["mode"] == MODE_APPROVED_PROBES,
              f"agent_status: zond yozuvi bor, lekin rejim {doc['mode']!r} — "
              f"{MODE_METADATA_ONLY} da zond BAJARILMAYDI va rejalashtirilmaydi ham")
    raqamlar = []
    for i, row in enumerate(rows):
        w = f"agent_status.probes[{i}]"
        _keys(row, PROBE_KEYS, w)
        no = _nonempty(row, "no", w)
        _need(COUNT_TEXT_RE.fullmatch(no) is not None,
              f"{w}.no ASCII raqamli MATN bo'lishi kerak (JSON soni TAQIQLANGAN): {no!r}")
        raqamlar.append(no)
        _need(row["probe_type"] in PROBE_CATALOG,
              f"{w}.probe_type ruxsat etilgan zondlar ro'yxatida yo'q: {row['probe_type']!r} "
              f"— ro'yxat `discovery_1c.probe.PROBE_CATALOG` da, u YOPIQ allowlist")
        _nonempty(row, "target_object", w)
        # ⚠️ `reason` MAJBURIY: sababsiz zond — tasdiqlab bo'lmaydigan zond. Operator
        #    «nega bu so'ralyapti» degan savolga javobni AYNI JOYDA ko'rishi kerak.
        _nonempty(row, "reason", w)
        _rel_path(row["file"], f"{w}.file")
        _need(row["status"] in PROBE_STATUSES,
              f"{w}.status {list(PROBE_STATUSES)} dan biri bo'lishi kerak, kelgani "
              f"{row['status']!r}")
    _need(len(set(raqamlar)) == len(raqamlar), "agent_status.probes: `no` takrorlangan")


# ══════════════════════════════════════════════════════════════════════════════════════════
# YURISH YOZUVI (immutable)
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Transition:
    """Bitta o'tish. ⚠️ `from` Python kaliti, shu bois maydon `from_state` deb ATALADI va
    JSON'ga `from` bo'lib chiqadi — JSON SHARTNOMASI o'zgarmaydi."""

    from_state: str
    to_state: str
    at: str
    note: str = ""

    def to_doc(self) -> dict:
        return {"from": self.from_state, "to": self.to_state, "at": self.at, "note": self.note}


@dataclass(frozen=True)
class ProbeRecord:
    """Rejalashtirilgan yoki bajarilgan zond. `no` — MATN sanoq."""

    no: str
    probe_type: str
    target_object: str
    reason: str
    file: str
    status: str

    def to_doc(self) -> dict:
        return {"no": self.no, "probe_type": self.probe_type,
                "target_object": self.target_object, "reason": self.reason,
                "file": self.file, "status": self.status}


@dataclass(frozen=True)
class AgentError:
    """Xato yozuvi: QAYERDA (`scope`), NIMA (`code`), BATAFSIL (`detail`)."""

    scope: str
    code: str
    detail: str

    def to_doc(self) -> dict:
        return {"scope": self.scope, "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class AgentStatus:
    """Agent yurishi — O'ZGARMAS (frozen) yozuv.

    ⚠️ NEGA IMMUTABLE: har qadam YANGI nusxa qaytaradi, ya'ni oldingi holat o'zgarmaydi va
       «kim qachon nimani o'zgartirdi» degan savol tug'ilmaydi. Shuning yonida bu
       `read_only` ni ham himoya qiladi: u maydon EMAS, XOSSA — unga qiymat berishning
       yo'li yo'q (`replace()` ham, `setattr` ham ishlamaydi).
    ⚠️ VAQT KIRISHDAN: har bir o'zgartiruvchi metod `now` TALAB QILADI. Modul «hozir»ni o'zi
       olmaydi — bo'lmasa bir xil kirish bir xil bayt bermaydi.
    """

    run_id: str
    started_at: str
    state: str = st.START
    finished_at: str | None = None
    route: str | None = None
    mode: str = MODE_METADATA_ONLY
    agent_name: str = AGENT_NAME
    agent_version: str = AGENT_VERSION
    transitions: tuple[Transition, ...] = ()
    environment_file: str | None = None
    bundle_dir: str | None = None
    artifacts: tuple[str, ...] = ()
    probes: tuple[ProbeRecord, ...] = ()
    errors: tuple[AgentError, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    # ── Hosila qiymatlar ──────────────────────────────────────────────────────────────────
    @property
    def read_only(self) -> str:
        """DOIM `"true"`. ⚠️ Maydon emas, XOSSA: o'zgartirish yo'li YO'Q."""
        return READ_ONLY

    @property
    def terminal(self) -> str:
        """`"true"`/`"false"` MATNI — HOLATDAN hisoblanadi, e'lon qilinmaydi."""
        return "true" if st.is_terminal(self.state) else "false"

    @property
    def is_failure(self) -> bool:
        return st.is_failure(self.state) if st.is_terminal(self.state) else False

    # ── O'tish ────────────────────────────────────────────────────────────────────────────
    def advance(self, to: str, *, now: str, note: str = "") -> "AgentStatus":
        """Yangi holatga o'tgan NUSXA. Ruxsat etilmagan o'tish — ISTISNO (fail-closed).

        ⚠️ Yakuniy holatga o'tishda `finished_at` AYNI `now` bilan to'ldiriladi: «tugadi,
           lekin qachon — bilmayman» degan yozuv keyin tiklanmaydi.
        """
        try:
            st.assert_transition(self.state, to)
        except st.TransitionError as e:
            raise AgentStatusError(str(e)) from e
        self._assert_ts(now, "now")
        _need(isinstance(note, str), "note matn bo'lishi kerak")
        row = Transition(from_state=self.state, to_state=to, at=now, note=note)
        return replace(self, state=to, transitions=self.transitions + (row,),
                       finished_at=now if st.is_terminal(to) else self.finished_at)

    # ── Maydonlarni to'ldirish (har biri YANGI nusxa) ──────────────────────────────────────
    def with_route(self, route: str) -> "AgentStatus":
        _need(route in ROUTES,
              f"route {sorted(ROUTES)} dan biri bo'lishi kerak, kelgani {route!r}")
        return replace(self, route=route)

    def with_mode(self, mode: str) -> "AgentStatus":
        """⚠️ `APPROVED_PROBES` — FAQAT operator tasdig'idan keyin. Bu metod tasdiqni
        ALMASHTIRMAYDI: tasdiq `discovery_1c.confirmations` qatlamida qayd etiladi, bu yerda
        esa faqat NATIJA yoziladi."""
        _need(mode in MODES, f"mode {sorted(MODES)} dan biri bo'lishi kerak, kelgani {mode!r}")
        return replace(self, mode=mode)

    def with_environment_file(self, name: str) -> "AgentStatus":
        _rel_path(name, "environment_file")
        return replace(self, environment_file=name)

    def with_bundle_dir(self, name: str) -> "AgentStatus":
        _rel_path(name, "bundle_dir")
        return replace(self, bundle_dir=name)

    def with_artifacts(self, names) -> "AgentStatus":
        """Artefakt ro'yxati — TAKRORSIZ va TARTIBLANGAN (determinizm)."""
        rows = tuple(names)
        for i, nom in enumerate(rows):
            _rel_path(nom, f"artifacts[{i}]")
        return replace(self, artifacts=tuple(sorted(set(rows))))

    def with_probe(self, probe: ProbeRecord) -> "AgentStatus":
        _need(isinstance(probe, ProbeRecord), "probe `ProbeRecord` bo'lishi kerak")
        return replace(self, probes=self.probes + (probe,))

    def with_error(self, scope: str, code: str, detail: str) -> "AgentStatus":
        return replace(self, errors=self.errors + (AgentError(scope, code, detail),))

    def with_note(self, note: str) -> "AgentStatus":
        _need(isinstance(note, str) and note.strip() != "",
              "note bo'sh bo'lmagan matn bo'lishi kerak")
        return replace(self, notes=self.notes + (note,))

    # ── Chiqish ───────────────────────────────────────────────────────────────────────────
    def to_doc(self) -> dict:
        """`binos-agent-run-v1` hujjati (tekshirilmagan XOM shakl)."""
        return {
            "agent_version": {"name": self.agent_name, "version": self.agent_version},
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "state": self.state,
            "terminal": self.terminal,
            "route": self.route,
            "mode": self.mode,
            "read_only": self.read_only,
            "transitions": [t.to_doc() for t in self.transitions],
            "environment_file": self.environment_file,
            "bundle_dir": self.bundle_dir,
            "artifacts": list(self.artifacts),
            "probes": [p.to_doc() for p in self.probes],
            "errors": [e.to_doc() for e in self.errors],
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        """Tekshirilgan, sirdan tozaligi isbotlangan, DETERMINISTIK JSON matni.

        ⚠️ Yozishdan OLDIN validator va `redact.scan` ishlaydi: shubhali qiymat topilsa
           ISTISNO va HECH NARSA qaytmaydi (fail-closed).
        ⚠️ Baytlar yadroning `bundle.dumps` i bilan yoziladi — ikkinchi «deterministik
           yozuvchi» yozib, bir kun ajralib ketmasligi uchun.
        """
        doc = self.to_doc()
        validate_agent_status(doc)
        return dumps(doc)

    @staticmethod
    def _assert_ts(value, where: str):
        try:
            return parse_ts(value, where)
        except BundleError as e:
            raise AgentStatusError(str(e)) from e


def new_run(run_id: str, *, now: str) -> AgentStatus:
    """`START` holatidagi yangi yurish. ⚠️ Vaqt KIRISHDAN keladi."""
    _need(isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id) is not None,
          f"run_id ASCII harf/raqam/`.`/`_`/`-` dan iborat bo'lishi kerak: {run_id!r}")
    AgentStatus._assert_ts(now, "started_at")
    return AgentStatus(run_id=run_id, started_at=now)
