# -*- coding: utf-8 -*-
"""Sintetik `binos-1c-discovery-v1` to'plami — DETERMINISTIK, 1C SIZ.

Bu yerdagi 1C nomlari — TO'QIMA. Ular hech qanday konfiguratsiyani ifodalamaydi va yadro
ularni bilmaydi: yadro uchun bu shunchaki matn. Shuning uchun testlar ataylab uydirma
(«Справочник.Вымышленная») va standart ko'rinishdagi nomlarni ARALASH ishlatadi — agar bir kun
yadroga konfiguratsiyaga xos bilim sizib kirsa, uydirma nomli testlar yiqiladi.
"""
from __future__ import annotations

from app.services.discovery_1c import SCHEMA_VERSION
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_1c.schema import TARGETS

TS_START = "2026-09-28T09:00:00+06:00"
TS_END = "2026-09-28T09:21:40+06:00"
TS_COLLECTED = "2026-09-28T09:21:40+06:00"

SECTIONS_OK = [
    {"name": "platform", "status": "ok", "error": None},
    {"name": "metadata_sweep", "status": "ok", "error": None},
    {"name": "counts", "status": "ok", "error": None},
    {"name": "samples", "status": "ok", "error": None},
]


def ev(kind: str, detail: str) -> dict:
    return {"kind": kind, "detail": detail}


def mapping(target: str, *, source_object=None, source_field=None, source_kind=None,
            confidence="UNKNOWN", evidence=(), row_count=None, non_null_count=None,
            sample_count=None, errors=()) -> dict:
    return {
        "target": target,
        "source_object": source_object,
        "source_field": source_field,
        "source_kind": source_kind,
        "confidence": confidence,
        "evidence": list(evidence),
        "row_count": row_count,
        "non_null_count": non_null_count,
        "sample_count": sample_count,
        "errors": list(errors),
    }


def all_unknown_mappings() -> list[dict]:
    """Har bir nishon bor, lekin hech biri aniqlanmagan — eng kamtar TO'G'RI to'plam.

    Aynan shu narsa invariantni ko'rsatadi: nishon tushib qolmaydi, u «bilmadim» deb yoziladi."""
    return [mapping(t, errors=["yig'uvchi hali bu nishonni qidirmaydi"]) for t in TARGETS]


def with_mapping(mappings: list[dict], m: dict) -> list[dict]:
    """Ro'yxatdagi shu nishonni almashtiradi (nusxasini qaytaradi)."""
    return [m if x["target"] == m["target"] else x for x in mappings]


def discovery_dict(*, mappings=None, source_kind="copy", platform_version="8.3.99.9999",
                   configuration_name="Вымышленная конфигурация", configuration_version="9.9.9.9",
                   configuration_modified=False, infobase_mode="file", infobase_id=None,
                   notes=("sintetik to'plam — real do'kon ma'lumoti emas",),
                   collector_name="BinOS 1C Discovery Collector", collector_version="0.1.0",
                   collected_at=TS_COLLECTED) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "collector": {"name": collector_name, "version": collector_version},
        "collected_at": collected_at,
        "source": {
            "kind": source_kind,
            "platform_version": platform_version,
            "configuration_name": configuration_name,
            "configuration_version": configuration_version,
            "configuration_modified": configuration_modified,
            "infobase_mode": infobase_mode,
            "infobase_id": infobase_id,
        },
        "mappings": all_unknown_mappings() if mappings is None else mappings,
        "notes": list(notes),
    }


def status_dict(*, sections=None, status=None, blocked_reason=None,
                started_at=TS_START, finished_at=TS_END) -> dict:
    from app.services.discovery_1c.bundle import derive_status
    secs = [dict(s) for s in (SECTIONS_OK if sections is None else sections)]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": derive_status(secs) if status is None else status,
        "started_at": started_at,
        "finished_at": finished_at,
        "sections": secs,
        "blocked_reason": blocked_reason,
    }


def child(name: str, kind: str, type_: str | None = None, synonym: str | None = None) -> dict:
    return {"name": name, "kind": kind, "type": type_, "synonym": synonym}


def obj(full_name: str, kind: str, name: str, *, synonym=None, children=(), row_count=None,
        errors=()) -> dict:
    return {"full_name": full_name, "kind": kind, "name": name, "synonym": synonym,
            "children": list(children), "row_count": row_count, "errors": list(errors)}


def sweep_dict(objects=None) -> dict:
    if objects is None:
        objects = [
            obj("Справочник.Вымышленная", "catalog", "Вымышленная", synonym="Выдуманный список",
                row_count="7137",
                children=[child("Ссылка", "standard_attribute", "СправочникСсылка.Вымышленная"),
                          child("Код", "standard_attribute", "Строка(11)"),
                          child("Наименование", "standard_attribute", "Строка(150)"),
                          child("ПометкаУдаления", "standard_attribute", "Булево"),
                          child("ЭтоГруппа", "standard_attribute", "Булево"),
                          child("ВыдуманныйРеквизит", "attribute", "Строка(5)",
                                synonym="Выдуманный код")]),
            obj("РегистрСведений.ВымышленныеКоды", "information_register", "ВымышленныеКоды",
                row_count="452",
                children=[child("Объект", "dimension", "СправочникСсылка.Вымышленная"),
                          child("Значение", "resource", "Строка(5)")]),
            obj("РегистрНакопления.ВымышленныеОстатки", "accumulation_register", "ВымышленныеОстатки",
                row_count="6159",
                children=[child("Объект", "dimension", "СправочникСсылка.Вымышленная"),
                          child("Место", "dimension", "СправочникСсылка.Места"),
                          child("Количество", "resource", "Число(15,3)")]),
        ]
    return {"schema_version": SCHEMA_VERSION, "objects": list(objects)}


def count(name: str, value: str | None, scope: str, errors=()) -> dict:
    return {"name": name, "value": value, "scope": scope, "errors": list(errors)}


def counts_dict(counts=None) -> dict:
    if counts is None:
        counts = [
            count("catalog_rows", "7137", "Справочник.Вымышленная, barcha qatorlar"),
            count("catalog_rows_not_deleted", "6744", "Справочник.Вымышленная, ПометкаУдаления=Ложь"),
            count("catalog_folders", "4", "Справочник.Вымышленная, ЭтоГруппа=Истина"),
            count("register_rows", "452", "РегистрСведений.ВымышленныеКоды"),
        ]
    return {"schema_version": SCHEMA_VERSION, "counts": list(counts)}


def sample_dict(source_object="Справочник.Вымышленная", fields=("Код", "Наименование"),
                rows=(("000537", "Выдуманный товар"), ("00538", "Ещё один")),
                row_count="7137") -> dict:
    return {"schema_version": SCHEMA_VERSION, "source_object": source_object,
            "fields": list(fields), "rows": [list(r) for r in rows],
            "row_count": row_count, "sample_count": str(len(rows))}


SUMMARY_MD = """# Discovery — sintetik to'plam

Bu fayl testlar uchun. Real do'kon ma'lumoti yo'q.
"""


def members(*, discovery=None, sweep=None, counts=None, status=None, summary=SUMMARY_MD,
            samples=None, drop=()) -> dict[str, bytes]:
    out = {
        "discovery.json": dumps(discovery_dict() if discovery is None else discovery),
        "metadata_sweep.json": dumps(sweep_dict() if sweep is None else sweep),
        "counts.json": dumps(counts_dict() if counts is None else counts),
        "status.json": dumps(status_dict() if status is None else status),
        "summary.md": summary,
    }
    for name, s in (samples or {"samples/catalog.json": sample_dict()}).items():
        out[name] = dumps(s)
    raw = {k: v.encode("utf-8") for k, v in out.items() if k not in drop}
    return raw
