# -*- coding: utf-8 -*-
"""`binos-1c-export-v1` -> `binos-1c-discovery-v1` KO'PRIGI (MINIMAL adapter).

NEGA IKKI SHAKL BOR. To'plam shakli (`binos-1c-discovery-v1`) qat'iy: besh a'zo fayl, kalit
oq ro'yxatlari, har nishon AYNAN bir marta, ishonch darajasi dalil turi bilan chegaralangan,
holat bo'limlardan HISOBLANADI. Buni 1C ichida, men sinay olmaydigan tilda qurish — xatoni
aynan tekshirib bo'lmaydigan joyga qo'yish bo'lardi.

Shu bois vazifa BO'LINDI:
  · `.epf` **oddiy va tekis** eksport yozadi (`binos-1c-export-v1`) — bitta fayl, hamma sanoq
    MATN, hech qanday hisoblangan maydon yo'q;
  · shu modul uni to'plam shakliga aylantiradi — Python'da, to'liq sinaladigan joyda.

⚠️ ADAPTER HECH QACHON ISHONCHNI KO'TARMAYDI. U `VERIFIED` ni UMUMAN chiqarmaydi, hatto
eksportda kuchli dalil turi bo'lsa ham. Sabab: yig'uvchi o'zini o'zi tasdiqlay olmaydi, va u
hali hech qachon haqiqiy 1C'da ishlamagan. Dalil bor -> `CANDIDATE`, yo'q -> `UNKNOWN`.
Darajani ko'tarish — odam ko'rigi, BinOS tomonida, alohida qadam.

⚠️ ADAPTER QUYIDAGILARNI O'YLAB CHIQARMAYDI: `source_copy`, `snapshot_at`, `plan_sha256`.
Ular metadata разведкаsidan KELIB CHIQMAYDI va migrator darvozalari uchun MUSTAQIL
tasdiqlanishi shart. Discovery sxemasida bunday maydon umuman yo'q — bu ataylab.

⚠️ `source.kind` (nusxami yoki jonlimi) EKSPORTDAN OLINMAYDI. Yig'uvchi o'zi qayerda
ishlayotganini bila olmaydi; buni OPERATOR e'lon qiladi va u majburiy argument.
"""
from __future__ import annotations

import re

from . import SCHEMA_VERSION, STATUS_BLOCKED
from .bundle import DiscoveryError, derive_status, dumps
from .schema import (CONFIDENCE_CANDIDATE, CONFIDENCE_UNKNOWN, EVIDENCE_KINDS, SOURCE_KINDS,
                     TARGETS)

EXPORT_VERSION = "binos-1c-export-v1"

EXPORT_KEYS = {"export_version", "collector", "collected_at", "started_at", "finished_at",
               "platform", "objects", "counts", "candidates", "sections", "notes"}
PLATFORM_KEYS = {"platform_version", "configuration_name", "configuration_version",
                 "configuration_modified", "infobase_mode", "infobase_id"}
CANDIDATE_KEYS = {"target", "source_object", "source_field", "source_kind", "evidence",
                  "row_count", "non_null_count", "errors"}

#: 1C tomoni uchulik mantiq MATN bilan beradi — `Булево` JSON'da `true` bo'lib ketmasin.
TRISTATE = {"true": True, "false": False, "unknown": None}
INFOBASE_MODES_EXPORT = {"file": "file", "server": "server", "ws": "ws", "unknown": None}

_COUNT_RE = re.compile(r"[0-9]{1,18}")


def _need(cond, msg: str) -> None:
    if not cond:
        raise DiscoveryError(msg)


def _keys(d, allowed: set, where: str) -> None:
    _need(isinstance(d, dict), f"{where}: obyekt kutilgan")
    unknown = sorted(set(d) - allowed)
    _need(not unknown, f"{where}: noma'lum kalit(lar) {unknown}")
    missing = sorted(allowed - set(d))
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {missing}")


def _text_or_none(v, where: str):
    _need(v is None or isinstance(v, str), f"{where}: matn yoki null bo'lishi kerak")
    return v


def _count_or_none(v, where: str):
    if v is None:
        return None
    _need(isinstance(v, str) and _COUNT_RE.fullmatch(v),
          f"{where}: sanoq MATN bo'lishi kerak (JSON soni TAQIQLANGAN) — kelgani {v!r}")
    return v


def validate_export(d: dict) -> None:
    """Eksportni to'plamga aylantirishdan OLDIN tekshiradi. Xato — `DiscoveryError`."""
    _keys(d, EXPORT_KEYS, "export")
    _need(d["export_version"] == EXPORT_VERSION,
          f"export.export_version {EXPORT_VERSION!r} bo'lishi kerak, kelgani {d['export_version']!r}")
    _keys(d["collector"], {"name", "version"}, "export.collector")
    for k in ("name", "version"):
        _need(isinstance(d["collector"][k], str) and d["collector"][k].strip(),
              f"export.collector.{k} bo'sh bo'lmagan matn bo'lishi kerak")

    _keys(d["platform"], PLATFORM_KEYS, "export.platform")
    p = d["platform"]
    for k in ("platform_version", "configuration_name", "configuration_version", "infobase_id"):
        _text_or_none(p[k], f"export.platform.{k}")
    _need(p["configuration_modified"] in TRISTATE,
          f"export.platform.configuration_modified {sorted(TRISTATE)} dan biri bo'lishi kerak")
    _need(p["infobase_mode"] in INFOBASE_MODES_EXPORT,
          f"export.platform.infobase_mode {sorted(INFOBASE_MODES_EXPORT)} dan biri bo'lishi kerak")

    _need(isinstance(d["objects"], list), "export.objects ro'yxat bo'lishi kerak")
    _need(isinstance(d["counts"], list), "export.counts ro'yxat bo'lishi kerak")
    _need(isinstance(d["candidates"], list), "export.candidates ro'yxat bo'lishi kerak")
    _need(isinstance(d["sections"], list) and d["sections"],
          "export.sections bo'sh bo'lmagan ro'yxat bo'lishi kerak")
    _need(isinstance(d["notes"], list), "export.notes ro'yxat bo'lishi kerak")

    for i, c in enumerate(d["candidates"]):
        w = f"export.candidates[{i}]"
        _keys(c, CANDIDATE_KEYS, w)
        _need(c["target"] in TARGETS, f"{w}.target noma'lum: {c['target']!r}")
        _text_or_none(c["source_object"], f"{w}.source_object")
        _text_or_none(c["source_field"], f"{w}.source_field")
        _need(c["source_kind"] is None or c["source_kind"] in SOURCE_KINDS,
              f"{w}.source_kind noma'lum: {c['source_kind']!r}")
        _count_or_none(c["row_count"], f"{w}.row_count")
        _count_or_none(c["non_null_count"], f"{w}.non_null_count")
        _need(isinstance(c["errors"], list), f"{w}.errors ro'yxat bo'lishi kerak")
        _need(isinstance(c["evidence"], list), f"{w}.evidence ro'yxat bo'lishi kerak")
        for j, e in enumerate(c["evidence"]):
            ew = f"{w}.evidence[{j}]"
            _keys(e, {"kind", "detail"}, ew)
            _need(e["kind"] in EVIDENCE_KINDS, f"{ew}.kind noma'lum: {e['kind']!r}")
            _need(isinstance(e["detail"], str) and e["detail"].strip(),
                  f"{ew}.detail bo'sh bo'lmasligi kerak")

    seen = [c["target"] for c in d["candidates"]]
    dupes = sorted({t for t in seen if seen.count(t) > 1})
    _need(not dupes, f"export.candidates: nishon takrorlangan {dupes}")


def to_bundle_members(export: dict, *, source_kind: str) -> dict[str, bytes]:
    """Eksportdan to'plam a'zolarini quradi (nom -> baytlar).

    `source_kind` — OPERATOR e'loni (`copy` yoki `live`). Eksportdan olinmaydi: yig'uvchi
    o'zi nusxada ishlayotganini bila olmaydi."""
    _need(source_kind in ("copy", "live"),
          f"source_kind 'copy' yoki 'live' bo'lishi kerak, kelgani {source_kind!r}")
    validate_export(export)

    p = export["platform"]
    discovery = {
        "schema_version": SCHEMA_VERSION,
        "collector": dict(export["collector"]),
        "collected_at": export["collected_at"],
        "source": {
            "kind": source_kind,                       # ← OPERATOR aytdi, yig'uvchi emas
            "platform_version": p["platform_version"],
            "configuration_name": p["configuration_name"],
            "configuration_version": p["configuration_version"],
            "configuration_modified": TRISTATE[p["configuration_modified"]],
            "infobase_mode": INFOBASE_MODES_EXPORT[p["infobase_mode"]],
            "infobase_id": p["infobase_id"],
        },
        "mappings": _mappings(export["candidates"]),
        "notes": list(export["notes"]) + [
            "Bu to'plam `binos-1c-export-v1` dan adapter orqali qurilgan. Adapter ishonch "
            "darajasini KO'TARMAYDI: eng yuqorisi CANDIDATE.",
        ],
    }

    sweep = {"schema_version": SCHEMA_VERSION, "objects": list(export["objects"])}
    counts = {"schema_version": SCHEMA_VERSION, "counts": list(export["counts"])}
    status = {
        "schema_version": SCHEMA_VERSION,
        "status": derive_status(export["sections"]),
        "started_at": export["started_at"],
        "finished_at": export["finished_at"],
        "sections": list(export["sections"]),
        "blocked_reason": None,
    }
    if status["status"] == STATUS_BLOCKED:
        yiqilgan = [s["name"] for s in export["sections"] if s["status"] != "ok"]
        status["blocked_reason"] = ("birorta bo'lim muvaffaqiyatli tugamadi: "
                                    + ", ".join(sorted(yiqilgan)))

    members = {
        "discovery.json": dumps(discovery).encode("utf-8"),
        "metadata_sweep.json": dumps(sweep).encode("utf-8"),
        "counts.json": dumps(counts).encode("utf-8"),
        "status.json": dumps(status).encode("utf-8"),
        "summary.md": _summary(discovery, sweep, counts, status).encode("utf-8"),
    }
    return members


def _mappings(candidates: list[dict]) -> list[dict]:
    """Har nishon uchun AYNAN bitta xarita. Aniqlanmagani TASHLAB KETILMAYDI — u `UNKNOWN`
    darajasi bilan yoziladi, chunki «qaralmadi» va «yo'q» bir xil narsa emas."""
    by_target = {c["target"]: c for c in candidates}
    out = []
    for target in TARGETS:
        c = by_target.get(target)
        if c is None:
            out.append({
                "target": target, "source_object": None, "source_field": None,
                "source_kind": None, "confidence": CONFIDENCE_UNKNOWN, "evidence": [],
                "row_count": None, "non_null_count": None, "sample_count": None,
                "errors": ["yig'uvchi bu nishonni qidirmadi"],
            })
            continue

        evidence = [dict(e) for e in c["evidence"]]
        # ⚠️ Daraja SHU YERDA hisoblanadi, eksportdan OLINMAYDI. VERIFIED chiqmaydi.
        confidence = CONFIDENCE_CANDIDATE if evidence else CONFIDENCE_UNKNOWN
        errors = list(c["errors"])
        if not evidence and (c["source_object"] or c["source_field"]):
            errors.append("manba ko'rsatilgan, lekin dalil yo'q — daraja UNKNOWN bo'lib qoldi")
        out.append({
            "target": target,
            "source_object": c["source_object"],
            "source_field": c["source_field"],
            "source_kind": c["source_kind"],
            "confidence": confidence,
            "evidence": evidence,
            "row_count": c["row_count"],
            "non_null_count": c["non_null_count"],
            "sample_count": None,            # metadata-only eksportda namuna YO'Q
            "errors": errors,
        })
    return out


def _summary(discovery, sweep, counts, status) -> str:
    """Odam o'qiydigan xulosa — DETERMINISTIK (sanalgan qiymatlar tartiblangan)."""
    ms = discovery["mappings"]
    daraja = {}
    for m in ms:
        daraja[m["confidence"]] = daraja.get(m["confidence"], 0) + 1
    src = discovery["source"]
    satrlar = [
        "# 1C discovery — xulosa",
        "",
        f"- Yig'uvchi: {discovery['collector']['name']} {discovery['collector']['version']}",
        f"- Yig'ilgan: {discovery['collected_at']}",
        f"- Manba: {src['kind']} · platforma {src['platform_version'] or '?'} · "
        f"konfiguratsiya {src['configuration_name'] or '?'} {src['configuration_version'] or ''}".rstrip(),
        f"- Holat: {status['status']}",
        f"- Ko'rilgan obyektlar: {len(sweep['objects'])} · sanoqlar: {len(counts['counts'])}",
        "",
        "## Nishonlar",
        "",
    ]
    for k in sorted(daraja):
        satrlar.append(f"- {k}: {daraja[k]}")
    satrlar += [
        "",
        "⚠️ Bu to'plam METADATA разведкаsi. Nishon topilgani uning mazmuni ko'chirishga "
        "YAROQLI ekanini ISBOTLAMAYDI.",
        "⚠️ Adapter ishonch darajasini ko'tarmaydi — eng yuqorisi CANDIDATE. VERIFIED faqat "
        "odam ko'rigi bilan beriladi.",
        "",
    ]
    return "\n".join(satrlar)
