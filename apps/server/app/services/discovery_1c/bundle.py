# -*- coding: utf-8 -*-
"""`binos-1c-discovery-v1` to'plami — yuklash, tekshirish, deterministik yozish, mazmun xeshi.

To'plam — bitta papka (yoki ZIP ichidagi papka):

    discovery.json        manba metadatasi + NISHONLAR bo'yicha bog'lanishlar (asosiy mazmun)
    metadata_sweep.json   xom metadata sanog'i: obyektlar, ularning bolalari, qator sanoqlari
    counts.json           rekonsiliatsiya sanoqlari
    status.json           yurish yozuvi: umumiy holat, bo'limlar, vaqtlar
    summary.md            odam o'qiydigan hisobot
    samples/*.json        namunalar (ixtiyoriy), har biri redaksiyadan o'tgan

KUCHGA KIRITILADIGAN INVARIANTLAR:
  1. JSON soni HECH QAYERDA yo'q — barcha sanoqlar MATN. (`binos-1c-v1` 1-qoidasi bilan bir xil.)
  2. HAR BIR nishon `mappings` da AYNAN BIR MARTA uchraydi. Aniqlanmagan nishon TUSHIRIB
     QOLDIRILMAYDI — u `UNKNOWN` darajasi va sababi bilan yoziladi. Jim tushib qolish —
     eng xavfli nosozlik: hisobot to'liq ko'rinadi, aslida esa savol berilmagan.
  3. `status` bo'limlardan HISOBLANADI va e'lon qilingani bilan mos kelishi SHART.
  4. `VERIFIED` faqat kuchli dalil bilan (`schema.confidence_error`).
  5. Sir topilsa — RAD (`redact.scan`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from . import (CONTENT_HASH_LABEL, MAX_MEMBER_BYTES, REQUIRED_MEMBERS, SCHEMA_VERSION,
               STATUS_BLOCKED, STATUS_COMPLETE, STATUS_PARTIAL, STATUSES)
from . import redact as redaction
from .schema import (CONFIDENCES, CONFIDENCE_UNKNOWN, EVIDENCE_KINDS, SOURCE_KINDS, TARGETS,
                     confidence_error)
from ..migrator_1c.bundle import BundleError, parse_ts, sha256_bytes, strict_json_loads

COUNT_TEXT_RE = re.compile(r"[0-9]{1,18}")
SECTION_STATUSES = ("ok", "failed", "skipped")
SOURCE_INSPECTED_KINDS = ("copy", "live")          # `live` — faqat ATAYLAB ruxsat berilganda
INFOBASE_MODES = ("file", "server", "ws")

DISCOVERY_KEYS = {"schema_version", "collector", "collected_at", "source", "mappings", "notes"}
COLLECTOR_KEYS = {"name", "version"}
SOURCE_KEYS = {"kind", "platform_version", "configuration_name", "configuration_version",
               "configuration_modified", "infobase_mode", "infobase_id"}
MAPPING_KEYS = {"target", "source_object", "source_field", "source_kind", "confidence",
                "evidence", "row_count", "non_null_count", "sample_count", "errors"}
EVIDENCE_KEYS = {"kind", "detail"}
STATUS_KEYS = {"schema_version", "status", "started_at", "finished_at", "sections", "blocked_reason"}
SECTION_KEYS = {"name", "status", "error"}
SWEEP_KEYS = {"schema_version", "objects"}
OBJECT_KEYS = {"full_name", "kind", "name", "synonym", "children", "row_count", "errors"}
CHILD_KEYS = {"name", "kind", "type", "synonym"}
COUNTS_KEYS = {"schema_version", "counts"}
COUNT_KEYS = {"name", "value", "scope", "errors"}
SAMPLE_KEYS = {"schema_version", "source_object", "fields", "rows", "row_count", "sample_count"}


class DiscoveryError(ValueError):
    """To'plam buzuq, to'liqsiz yoki ishonch darajasi dalilga mos emas — o'qilmaydi."""


@dataclass(frozen=True)
class DiscoveryBundle:
    discovery: dict
    sweep: dict
    counts: dict
    status: dict
    summary_md: str
    samples: dict = field(default_factory=dict)
    content_sha256: str = ""

    @property
    def mappings(self) -> list[dict]:
        return self.discovery["mappings"]

    @property
    def overall_status(self) -> str:
        return self.status["status"]

    def mapping(self, target: str) -> dict:
        for m in self.mappings:
            if m["target"] == target:
                return m
        raise KeyError(target)                       # invariant 2 buni imkonsiz qiladi


# ── Kichik yordamchilar (migrator'dagi bilan bir xil shakl, boshqa xato turi) ───────────────
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise DiscoveryError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = set(obj) - allowed
    _need(not extra, f"{where}: noma'lum kalit(lar) {sorted(extra)} — {SCHEMA_VERSION} da yo'q")
    missing = allowed - set(obj)
    _need(not missing, f"{where}: kalit(lar) yetishmayapti {sorted(missing)}")


def _str_or_none(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(v is None or isinstance(v, str), f"{where}.{key} matn yoki null bo'lishi kerak")


def _nonempty_str(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(isinstance(v, str) and v.strip(), f"{where}.{key} bo'sh bo'lmagan matn bo'lishi kerak")


def _count_or_none(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(v is None or (isinstance(v, str) and COUNT_TEXT_RE.fullmatch(v)),
          f"{where}.{key} ASCII raqamli MATN yoki null bo'lishi kerak (JSON soni TAQIQLANGAN)")


def _str_list(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    _need(isinstance(v, list) and all(isinstance(x, str) for x in v),
          f"{where}.{key} matnlar ro'yxati bo'lishi kerak")


def _ts(obj: dict, key: str, where: str):
    try:
        return parse_ts(obj.get(key), f"{where}.{key}")
    except BundleError as e:
        raise DiscoveryError(str(e)) from e


def _loads(text: str, where: str):
    try:
        return strict_json_loads(text)
    except BundleError as e:
        raise DiscoveryError(f"{where}: {e}") from e


# ── Bo'lim holati -> umumiy holat ──────────────────────────────────────────────────────────
def derive_status(sections: list[dict]) -> str:
    """Bo'limlardan umumiy holat. Bo'lim JIMGINA tushib qolmaydi — u shu yerda sanaladi.

    BLOCKED — birorta bo'lim muvaffaqiyatli tugamagan (ya'ni to'plamdan foyda yo'q).
    PARTIAL — hech bo'lmasa bittasi `ok`, lekin `failed`/`skipped` ham bor.
    COMPLETE — hammasi `ok`.
    """
    _need(sections, "status.sections bo'sh bo'lmasligi kerak")
    ok = sum(1 for s in sections if s["status"] == "ok")
    if ok == 0:
        return STATUS_BLOCKED
    return STATUS_COMPLETE if ok == len(sections) else STATUS_PARTIAL


# ── Tekshiruvlar ───────────────────────────────────────────────────────────────────────────
def _validate_mapping(m, where: str) -> None:
    _keys(m, MAPPING_KEYS, where)
    _need(m["target"] in TARGETS, f"{where}.target noma'lum: {m['target']!r}")
    _need(m["confidence"] in CONFIDENCES, f"{where}.confidence noma'lum: {m['confidence']!r}")
    _need(m["source_kind"] in SOURCE_KINDS or m["source_kind"] is None,
          f"{where}.source_kind noma'lum: {m['source_kind']!r}")
    _str_or_none(m, "source_object", where)
    _str_or_none(m, "source_field", where)
    for key in ("row_count", "non_null_count", "sample_count"):
        _count_or_none(m, key, where)
    _str_list(m, "errors", where)

    ev = m["evidence"]
    _need(isinstance(ev, list), f"{where}.evidence ro'yxat bo'lishi kerak")
    kinds = []
    for i, e in enumerate(ev):
        w = f"{where}.evidence[{i}]"
        _keys(e, EVIDENCE_KEYS, w)
        _need(e["kind"] in EVIDENCE_KINDS, f"{w}.kind noma'lum: {e['kind']!r}")
        _nonempty_str(e, "detail", w)
        kinds.append(e["kind"])

    err = confidence_error(m["confidence"], kinds, m["source_kind"])
    _need(err is None, f"{where}: {err}")

    if m["confidence"] == CONFIDENCE_UNKNOWN:
        _need(m["errors"] or m["source_kind"] is None or m["source_kind"] == "absent",
              f"{where}: UNKNOWN darajasi sabab talab qiladi — `errors` ga yozing")
    # Sanoq mantig'i: to'ldirilgan qatorlar umumiy qatordan ko'p bo'lolmaydi.
    rc, nn = m["row_count"], m["non_null_count"]
    if rc is not None and nn is not None:
        _need(int(nn) <= int(rc), f"{where}: non_null_count ({nn}) row_count ({rc}) dan katta")


def _validate_discovery(d) -> None:
    _keys(d, DISCOVERY_KEYS, "discovery")
    _need(d["schema_version"] == SCHEMA_VERSION,
          f"discovery.schema_version {SCHEMA_VERSION!r} bo'lishi kerak, kelgani {d['schema_version']!r}")
    _keys(d["collector"], COLLECTOR_KEYS, "discovery.collector")
    _nonempty_str(d["collector"], "name", "discovery.collector")
    _nonempty_str(d["collector"], "version", "discovery.collector")
    _ts(d, "collected_at", "discovery")

    src = d["source"]
    _keys(src, SOURCE_KEYS, "discovery.source")
    _need(src["kind"] in SOURCE_INSPECTED_KINDS, f"discovery.source.kind noma'lum: {src['kind']!r}")
    for k in ("platform_version", "configuration_name", "configuration_version", "infobase_id"):
        _str_or_none(src, k, "discovery.source")
    _need(src["configuration_modified"] is None or isinstance(src["configuration_modified"], bool),
          "discovery.source.configuration_modified bool yoki null bo'lishi kerak")
    _need(src["infobase_mode"] is None or src["infobase_mode"] in INFOBASE_MODES,
          f"discovery.source.infobase_mode noma'lum: {src['infobase_mode']!r}")

    ms = d["mappings"]
    _need(isinstance(ms, list), "discovery.mappings ro'yxat bo'lishi kerak")
    for i, m in enumerate(ms):
        _validate_mapping(m, f"discovery.mappings[{i}]")

    seen = [m["target"] for m in ms]
    dupes = sorted({t for t in seen if seen.count(t) > 1})
    _need(not dupes, f"discovery.mappings: nishon takrorlangan {dupes}")
    missing = sorted(set(TARGETS) - set(seen))
    _need(not missing, f"discovery.mappings: nishon(lar) tushib qolgan {missing} — "
                       "aniqlanmagan nishon UNKNOWN darajasi bilan YOZILADI, tashlab ketilmaydi")
    _str_list(d, "notes", "discovery")


def _validate_status(s) -> None:
    _keys(s, STATUS_KEYS, "status")
    _need(s["schema_version"] == SCHEMA_VERSION, "status.schema_version mos emas")
    _need(s["status"] in STATUSES, f"status.status noma'lum: {s['status']!r}")
    started = _ts(s, "started_at", "status")
    finished = _ts(s, "finished_at", "status")
    _need(finished >= started, "status.finished_at `started_at` dan oldin bo'lolmaydi")
    _str_or_none(s, "blocked_reason", "status")

    secs = s["sections"]
    _need(isinstance(secs, list) and secs, "status.sections bo'sh bo'lmagan ro'yxat bo'lishi kerak")
    names = []
    for i, sec in enumerate(secs):
        w = f"status.sections[{i}]"
        _keys(sec, SECTION_KEYS, w)
        _nonempty_str(sec, "name", w)
        _need(sec["status"] in SECTION_STATUSES, f"{w}.status noma'lum: {sec['status']!r}")
        _str_or_none(sec, "error", w)
        _need(sec["status"] == "ok" or (sec["error"] or "").strip(),
              f"{w}: `{sec['status']}` bo'lgan bo'lim sababsiz qolmaydi — `error` ni to'ldiring")
        _need(sec["status"] != "ok" or not sec["error"],
              f"{w}: `ok` bo'limda `error` bo'lmasligi kerak")
        names.append(sec["name"])
    dupes = sorted({n for n in names if names.count(n) > 1})
    _need(not dupes, f"status.sections: bo'lim nomi takrorlangan {dupes}")

    derived = derive_status(secs)
    _need(derived == s["status"],
          f"status.status bo'limlarga mos emas: e'lon qilingani {s['status']!r}, hisoblangani {derived!r}")
    _need(s["status"] != STATUS_BLOCKED or (s["blocked_reason"] or "").strip(),
          "status BLOCKED bo'lsa `blocked_reason` SHART")


def _validate_cross_refs(discovery, sweep) -> None:
    """Xaritalar SWEEP'da HAQIQATAN ko'rilgan obyektlarga ishora qilishi SHART.

    NEGA. Ilgari to'rt fayl bir-biridan MUSTAQIL tekshirilardi, ya'ni to'plam hech qachon
    ko'rilmagan obyektga ishora qilib ham validatsiyadan o'tib ketardi. Bu discovery'ning
    butun ma'nosini buzadi: «bu maydon shu yerda» degan da'vo uni KO'RGANLIK dalili bilan
    bog'lanmasa, u shunchaki taxmin bo'ladi.

    ⚠️ `source_kind == "absent"` ISTISNO: yo'qlik da'vosi ta'rifi bo'yicha sweep'da obyekt
    bo'lmasligini bildiradi. `source_object` berilmagan xarita ham (None) tekshirilmaydi —
    u hali hech narsaga ishora qilmayapti."""
    ko_rilgan = {o["full_name"] for o in sweep["objects"]}
    for i, m in enumerate(discovery["mappings"]):
        src = m["source_object"]
        if src is None or m["source_kind"] == "absent":
            continue
        _need(src in ko_rilgan,
              f"discovery.mappings[{i}] ('{m['target']}') KO'RILMAGAN obyektga ishora qiladi: "
              f"{src!r} metadata_sweep.objects ichida yo'q. Yig'uvchi ko'rmagan narsaga xarita "
              f"qura olmaydi — bu dalil emas, taxmin.")


def _validate_sweep(d) -> None:
    _keys(d, SWEEP_KEYS, "metadata_sweep")
    _need(d["schema_version"] == SCHEMA_VERSION, "metadata_sweep.schema_version mos emas")
    objs = d["objects"]
    _need(isinstance(objs, list), "metadata_sweep.objects ro'yxat bo'lishi kerak")
    seen = []
    for i, o in enumerate(objs):
        w = f"metadata_sweep.objects[{i}]"
        _keys(o, OBJECT_KEYS, w)
        _nonempty_str(o, "full_name", w)
        _nonempty_str(o, "name", w)
        _str_or_none(o, "synonym", w)
        _need(o["kind"] in SOURCE_KINDS, f"{w}.kind noma'lum: {o['kind']!r}")
        _count_or_none(o, "row_count", w)
        _str_list(o, "errors", w)
        ch = o["children"]
        _need(isinstance(ch, list), f"{w}.children ro'yxat bo'lishi kerak")
        cnames = []
        for j, c in enumerate(ch):
            cw = f"{w}.children[{j}]"
            _keys(c, CHILD_KEYS, cw)
            _nonempty_str(c, "name", cw)
            _need(c["kind"] in SOURCE_KINDS, f"{cw}.kind noma'lum: {c['kind']!r}")
            _str_or_none(c, "type", cw)
            _str_or_none(c, "synonym", cw)
            cnames.append(c["name"])
        cdupes = sorted({n for n in cnames if cnames.count(n) > 1})
        _need(not cdupes, f"{w}.children: nom takrorlangan {cdupes}")
        seen.append(o["full_name"])
    dupes = sorted({n for n in seen if seen.count(n) > 1})
    _need(not dupes, f"metadata_sweep.objects: full_name takrorlangan {dupes}")


def _validate_counts(d) -> None:
    _keys(d, COUNTS_KEYS, "counts")
    _need(d["schema_version"] == SCHEMA_VERSION, "counts.schema_version mos emas")
    cs = d["counts"]
    _need(isinstance(cs, list), "counts.counts ro'yxat bo'lishi kerak")
    names = []
    for i, c in enumerate(cs):
        w = f"counts.counts[{i}]"
        _keys(c, COUNT_KEYS, w)
        _nonempty_str(c, "name", w)
        _nonempty_str(c, "scope", w)
        _count_or_none(c, "value", w)
        _str_list(c, "errors", w)
        _need(c["value"] is not None or c["errors"],
              f"{w}: sanoq olinmagan bo'lsa sababi `errors` da bo'lishi SHART")
        names.append(c["name"])
    dupes = sorted({n for n in names if names.count(n) > 1})
    _need(not dupes, f"counts.counts: nom takrorlangan {dupes}")


def _validate_sample(d, where: str) -> None:
    _keys(d, SAMPLE_KEYS, where)
    _need(d["schema_version"] == SCHEMA_VERSION, f"{where}.schema_version mos emas")
    _nonempty_str(d, "source_object", where)
    _str_list(d, "fields", where)
    # Ustun NOMI sirga o'xshasa — qatorlar ham sir. Bu `redact.scan` dan o'tib ketardi, chunki
    # u yerda «password» kalit emas, QIYMAT bo'lib turadi.
    secret_fields = [f for f in d["fields"] if redaction.SECRET_KEY_RE.search(f)]
    _need(not secret_fields,
          f"{where}.fields: sirga o'xshash ustun nomi {secret_fields} — bunday namuna olinmaydi")
    _count_or_none(d, "row_count", where)
    _count_or_none(d, "sample_count", where)
    rows = d["rows"]
    _need(isinstance(rows, list), f"{where}.rows ro'yxat bo'lishi kerak")
    width = len(d["fields"])
    for i, r in enumerate(rows):
        _need(isinstance(r, list) and len(r) == width,
              f"{where}.rows[{i}]: {width} ta ustunli ro'yxat bo'lishi kerak")
        _need(all(x is None or isinstance(x, str) for x in r),
              f"{where}.rows[{i}]: qiymatlar MATN yoki null (JSON soni TAQIQLANGAN)")
    if d["sample_count"] is not None:
        _need(int(d["sample_count"]) == len(rows),
              f"{where}.sample_count qatorlar soniga teng bo'lishi kerak")


# ── Deterministik yozish va mazmun xeshi ───────────────────────────────────────────────────
def dumps(obj) -> str:
    """Deterministik JSON: kalitlar tartiblangan, ortiqcha probel yo'q, oxirida bitta `\\n`.

    Bir xil mazmun — AYNAN bir xil baytlar. Shu tufayli to'plamni qayta yig'ib, xeshini
    solishtirib ko'rish mumkin."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def _canon_mapping(m: dict) -> dict:
    return {
        "target": m["target"],
        "source_object": m["source_object"],
        "source_field": m["source_field"],
        "source_kind": m["source_kind"],
        "confidence": m["confidence"],
        "evidence": sorted([e["kind"], e["detail"]] for e in m["evidence"]),
        "row_count": m["row_count"],
        "non_null_count": m["non_null_count"],
        "sample_count": m["sample_count"],
        "errors": sorted(m["errors"]),
    }


def canonical_projection(b: "DiscoveryBundle") -> dict:
    """Xesh hisoblanadigan kanonik proyeksiya.

    KIRMAYDI: vaqt belgilari (`collected_at`, `started_at`, `finished_at`), `summary.md` va
    fayl formatlanishi. Ya'ni bitta nusxani ikki marta skanerlash — bir xil xesh, agar
    javoblar o'zgarmagan bo'lsa. KIRADI: mazmunning O'ZI, jumladan xatolar va bo'lim holatlari,
    chunki «xato bor» ham javobning bir qismi."""
    return {
        "schema_version": SCHEMA_VERSION,
        "collector": b.discovery["collector"],
        "source": b.discovery["source"],
        "status": b.status["status"],
        "blocked_reason": b.status["blocked_reason"],
        "sections": sorted([s["name"], s["status"], s["error"] or ""] for s in b.status["sections"]),
        "mappings": sorted(dumps(_canon_mapping(m)).rstrip("\n") for m in b.mappings),
        "notes": sorted(b.discovery["notes"]),
        "objects": sorted(
            dumps({"full_name": o["full_name"], "kind": o["kind"], "name": o["name"],
                   "synonym": o["synonym"], "row_count": o["row_count"],
                   "errors": sorted(o["errors"]),
                   "children": sorted([c["name"], c["kind"], c["type"] or "", c["synonym"] or ""]
                                      for c in o["children"])}).rstrip("\n")
            for o in b.sweep["objects"]),
        "counts": sorted([c["name"], c["scope"], c["value"] or "", "|".join(sorted(c["errors"]))]
                         for c in b.counts["counts"]),
        "samples": sorted(b.samples),
    }


def content_hash(b: "DiscoveryBundle") -> str:
    proj = canonical_projection(b)
    h = hashlib.sha256()
    h.update(CONTENT_HASH_LABEL + b"\x00")
    h.update(dumps(proj).encode("utf-8"))
    return h.hexdigest()


# ── Yuklash ────────────────────────────────────────────────────────────────────────────────
def load_members(members: dict[str, bytes], allow_live_source: bool = False) -> DiscoveryBundle:
    """Nom -> baytlar xaritasidan to'plam. Fayl tizimiga bog'liq emas (ZIP uchun ham shu)."""
    for name in REQUIRED_MEMBERS:
        _need(name in members, f"to'plamda majburiy fayl yo'q: {name}")
    for name, raw in members.items():
        _need(len(raw) <= MAX_MEMBER_BYTES, f"{name}: fayl juda katta ({len(raw)} bayt)")

    def text(name: str) -> str:
        raw = members[name]
        raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DiscoveryError(f"{name} UTF-8 emas: {e}") from e

    discovery = _loads(text("discovery.json"), "discovery.json")
    sweep = _loads(text("metadata_sweep.json"), "metadata_sweep.json")
    counts = _loads(text("counts.json"), "counts.json")
    status = _loads(text("status.json"), "status.json")
    summary = text("summary.md")

    _validate_discovery(discovery)
    _validate_sweep(sweep)
    _validate_counts(counts)
    _validate_status(status)
    _validate_cross_refs(discovery, sweep)
    _need(summary.strip(), "summary.md bo'sh bo'lmasligi kerak")

    _need(allow_live_source or discovery["source"]["kind"] == "copy",
          "discovery.source.kind='live' — jonli bazadan yig'ilgan to'plam ATAYLAB ruxsat talab qiladi "
          "(`allow_live_source=True`)")

    samples: dict[str, dict] = {}
    for name in sorted(members):
        if not name.startswith("samples/"):
            continue
        _need(name.endswith(".json"), f"{name}: namunalar faqat .json bo'ladi")
        s = _loads(text(name), name)
        _validate_sample(s, name)
        samples[name] = s

    # Sirlar — ENG OXIRIDA, butun to'plam bo'ylab, jumladan summary.md matni.
    findings = redaction.scan({"discovery": discovery, "metadata_sweep": sweep, "counts": counts,
                               "status": status, "summary_md": summary, "samples": samples})
    _need(not findings, "to'plamda sir topildi — RAD: " + "; ".join(str(f) for f in findings[:10]))

    b = DiscoveryBundle(discovery=discovery, sweep=sweep, counts=counts, status=status,
                        summary_md=summary, samples=samples)
    return DiscoveryBundle(discovery=b.discovery, sweep=b.sweep, counts=b.counts, status=b.status,
                           summary_md=b.summary_md, samples=b.samples, content_sha256=content_hash(b))


def load_dir(path: str, allow_live_source: bool = False) -> DiscoveryBundle:
    members: dict[str, bytes] = {}
    for root, _dirs, files in os.walk(path):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            with open(full, "rb") as f:
                members[rel] = f.read()
    return load_members(members, allow_live_source=allow_live_source)


def write_dir(path: str, members: dict[str, bytes]) -> dict[str, str]:
    """To'plamni deterministik yozadi va har fayl uchun SHA256 qaytaradi."""
    out: dict[str, str] = {}
    for name in sorted(members):
        full = os.path.join(path, *name.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(members[name])
        out[name] = sha256_bytes(members[name])
    return out
