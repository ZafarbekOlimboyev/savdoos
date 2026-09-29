# -*- coding: utf-8 -*-
"""SINTETIK `binos-1c-export-v1` fiksturasi.

⚠️⚠️ BU YERDAGI 1C NOMLARI — TO'QIMA. «Вымышленная», «ВымышленныеКоды» kabi nomlar ATAYLAB
     hech qanday haqiqiy konfiguratsiyaga tegishli emas. Agar fikstura haqiqiy nomlarni
     ishlatganda, testlar o'sha konfiguratsiya haqidagi TAXMINNI qulflab qo'yardi.

⚠️⚠️ HECH BIR SINTETIK FIKSTURA HAQIQIY 1C RUNTIME ISHLASHINI ISBOTLAMAYDI. Bu fayl faqat
     ADAPTER mantig'ini sinaydi — eksportdan to'plamga aylantirish qoidalarini.
"""
from __future__ import annotations

import copy

CATALOG = "Справочник.Вымышленная"
REGISTER = "РегистрСведений.ВымышленныеКоды"


def child(name, kind, type_, synonym=None) -> dict:
    return {"name": name, "kind": kind, "type": type_, "synonym": synonym}


def obj(full_name, kind, name, *, synonym=None, row_count=None, children=(), errors=()) -> dict:
    return {"full_name": full_name, "kind": kind, "name": name, "synonym": synonym,
            "row_count": row_count, "children": list(children), "errors": list(errors)}


def count(name, value, scope="table", errors=()) -> dict:
    return {"name": name, "value": value, "scope": scope, "errors": list(errors)}


def ev(kind, detail) -> dict:
    return {"kind": kind, "detail": detail}


def candidate(target, *, source_object=None, source_field=None, source_kind=None,
              evidence=(), row_count=None, non_null_count=None, errors=()) -> dict:
    return {"target": target, "source_object": source_object, "source_field": source_field,
            "source_kind": source_kind, "evidence": list(evidence), "row_count": row_count,
            "non_null_count": non_null_count, "errors": list(errors)}


def section(name, status="ok", error=None) -> dict:
    return {"name": name, "status": status, "error": error}


def export_dict(**over) -> dict:
    """To'liq, HAQIQIY eksport shakli — adapter uni to'plamga aylantira olishi kerak."""
    d = {
        "export_version": "binos-1c-export-v1",
        "collector": {"name": "BinOSDiscovery", "version": "0.1.0-UNVERIFIED"},
        "collected_at": "2026-09-30T10:15:00+06:00",
        "started_at": "2026-09-30T10:14:30+06:00",
        "finished_at": "2026-09-30T10:15:00+06:00",
        "platform": {
            "platform_version": "8.3.24.1548",
            "configuration_name": "ВымышленнаяКонфигурация",
            "configuration_version": "1.0.0.1",
            "configuration_modified": "unknown",
            "infobase_mode": "file",
            "infobase_id": None,
        },
        "objects": [
            obj(CATALOG, "catalog", "Вымышленная", synonym="Выдуманный список", row_count="7137",
                children=[child("Код", "attribute", "Строка(11)"),
                          child("ВыдуманныйРеквизит", "attribute", "Строка(5)")]),
            obj(REGISTER, "information_register", "ВымышленныеКоды", row_count="452",
                children=[child("Значение", "resource", "Строка(14)")]),
        ],
        "counts": [count(CATALOG, "7137"), count(REGISTER, "452")],
        "candidates": [
            candidate("products.code", source_object=CATALOG, source_field="Код",
                      source_kind="attribute", row_count="7137", non_null_count="7137",
                      evidence=[ev("name_match", "nomi «Код» ga mos")]),
            candidate("products.barcodes", source_object=REGISTER, source_field="Значение",
                      source_kind="information_register", row_count="452",
                      evidence=[ev("name_match", "registr nomi mos")]),
        ],
        "sections": [section("platform"), section("metadata_sweep"), section("counts"),
                     section("candidates")],
        "notes": ["sintetik fikstura"],
    }
    d.update(over)
    return copy.deepcopy(d)
