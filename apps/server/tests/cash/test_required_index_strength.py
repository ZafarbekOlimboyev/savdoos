# -*- coding: utf-8 -*-
"""MAJBURIY INDEKS «bor» EMAS, «NOYOB va YAROQLI» bo'lishi kerak.

`REQUIRED_INDEXES` dagi 16 indeksning hammasi pul yoki idempotentlik kafolati:
ularsiz takror so'rov partiyani ikki marta ko'paytiradi, chek raqamini takrorlaydi,
naqd amalini ikki marta yozadi. Boot ularni `CREATE UNIQUE INDEX IF NOT EXISTS` bilan
quradi — LEKIN `IF NOT EXISTS` AYNI NOMLI, noyob BO'LMAGAN indeksni jimgina qabul qiladi
va tekshiruv ilgari FAQAT NOMNI ko'rardi: kafolat yo'q, tayyorlik YASHIL.

Bu sinov shu yolg'on yashilni to'sadi.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core import required_schema as rs


def _hex():
    return uuid.uuid4().hex[:8]


def test_noyob_bolmagan_indeks_tutiladi(db, cashenv, monkeypatch):
    """Nomi to'g'ri, lekin NOYOB EMAS -> «indeks noyob EMAS» (ilgari jimgina o'tardi)."""
    tb, ix = "rfix_ix_" + _hex(), "ux_rfix_" + _hex()
    bind = db.get_bind()
    db.execute(text(f"CREATE TABLE {tb} (a int)"))
    db.execute(text(f"CREATE INDEX {ix} ON {tb} (a)"))      # ATAYLAB noyob EMAS
    db.commit()
    try:
        monkeypatch.setattr(rs, "REQUIRED_INDEXES", [(ix, tb)])
        monkeypatch.setattr(rs, "REQUIRED_COLUMNS", [])
        monkeypatch.setattr(rs, "REQUIRED_PG_CONSTRAINTS", [])
        gaps = rs._fatal(bind)
        assert any("noyob EMAS" in g and ix in g for g in gaps), gaps
        # MANFIY NAZORAT: nom-bo'yicha eski mantiq bu holatni TOPMASDI
        from sqlalchemy import inspect as _insp
        assert ix in {i["name"] for i in _insp(bind).get_indexes(tb)}
    finally:
        db.rollback()
        db.execute(text(f"DROP TABLE IF EXISTS {tb}"))
        db.commit()


def test_noyob_indeks_otadi(db, cashenv, monkeypatch):
    tb, ix = "rfix_ix_" + _hex(), "ux_rfix_" + _hex()
    bind = db.get_bind()
    db.execute(text(f"CREATE TABLE {tb} (a int)"))
    db.execute(text(f"CREATE UNIQUE INDEX {ix} ON {tb} (a)"))
    db.commit()
    try:
        monkeypatch.setattr(rs, "REQUIRED_INDEXES", [(ix, tb)])
        monkeypatch.setattr(rs, "REQUIRED_COLUMNS", [])
        monkeypatch.setattr(rs, "REQUIRED_PG_CONSTRAINTS", [])
        assert rs._fatal(bind) == []
    finally:
        db.rollback()
        db.execute(text(f"DROP TABLE IF EXISTS {tb}"))
        db.commit()


def test_yoq_indeks_hamon_tutiladi(db, cashenv, monkeypatch):
    tb = "rfix_ix_" + _hex()
    bind = db.get_bind()
    db.execute(text(f"CREATE TABLE {tb} (a int)"))
    db.commit()
    try:
        monkeypatch.setattr(rs, "REQUIRED_INDEXES", [("ux_rfix_yoq_" + _hex(), tb)])
        monkeypatch.setattr(rs, "REQUIRED_COLUMNS", [])
        monkeypatch.setattr(rs, "REQUIRED_PG_CONSTRAINTS", [])
        assert any("indeks yo'q" in g for g in rs._fatal(bind))
    finally:
        db.rollback()
        db.execute(text(f"DROP TABLE IF EXISTS {tb}"))
        db.commit()


def test_barcha_majburiy_indeks_nomi_ux_prefiksli():
    """Registr SINFI aralashmasin: `REQUIRED_INDEXES` — NOYOB indekslar ro'yxati."""
    bad = [n for n, _ in rs.REQUIRED_INDEXES if not n.startswith("ux_")]
    assert not bad, ("noyob bo'lmagan indeks majburiy ro'yxatda: " + str(bad)
                     + " — tezlik indeksi `PERFORMANCE_INDEXES` ga boradi")


def test_check_registrida_noyoblik_yoq():
    """UNIQUE nomi CHECK registriga TUSHMASIN: ikki so'rov ham `contype='c'` bilan filtrlaydi,
    ya'ni u yerdagi noyoblik nomi ABADIY «yo'q» bo'lib tayyorlikni qizil qilardi."""
    bad = [n for n, _ in rs.REQUIRED_PG_CONSTRAINTS if n.startswith(("ux_", "uq_"))]
    assert not bad, "noyoblik nomi CHECK registrida: " + str(bad)
    # har majburiy CHECK uchun ta'rif bor (mavjud invariantni R-fix ham qotiradi)
    assert set(rs.CHECK_DEFINITIONS) == {n for n, _ in rs.REQUIRED_PG_CONSTRAINTS}


def test_sinflar_kesishmaydi():
    """Bir indeks AYNAN bitta sinfda (T4 qo'riqchisi bilan izchil)."""
    groups = {"REQUIRED_INDEXES": rs.REQUIRED_INDEXES,
              "PERFORMANCE_INDEXES": rs.PERFORMANCE_INDEXES,
              "IDEMPOTENCY_INDEXES": rs.IDEMPOTENCY_INDEXES,
              "OPTIONAL_UNIQUE_INDEXES": rs.OPTIONAL_UNIQUE_INDEXES}
    seen: dict = {}
    dup = []
    for gname, pairs in groups.items():
        for name, _tb in pairs:
            if name in seen:
                dup.append(f"{name}: {seen[name]} + {gname}")
            seen[name] = gname
    assert not dup, "indeks ikki sinfda: " + str(dup)
