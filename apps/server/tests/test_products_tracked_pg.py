# -*- coding: utf-8 -*-
"""PHASE 5B — `/products?tracked=` agregat toraytirishi HAQIQIY POSTGRES'da.

SQLite nimani o'lchay olmaydi va bu fayl nimani isbotlaydi:
  · `IN (SELECT ...)` ichidagi ILIKE ... ESCAPE, UUID bind'lar va `IS true`/`IS false` PG'da ham
    mustaqil oracle bilan AYNI qiymat beradi; '%' va '_' qidiruvda JOKER EMAS;
  · `tracked`'siz yo'lning agregat SQL'i tuzatishdan oldingisi bilan AYNAN (psycopg dialekti);
  · bo'sh natija -> `inventory`/`sale_items` ga BITTA ham so'rov yo'q, `branch_id`
    tekshiruvi (400/403) esa baribir OLDIN ishlaydi;
  · EXPLAIN: agregat rejasida mahsulot cheklovi (semi-join / SubPlan) BOR.

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
Endpoint funksiyasi sessiya bilan TO'G'RIDAN chaqiriladi — PG testlaridagi odatiy naqsh
(`test_lot_phase4a_pg._return_fn`), TestClient ilova engine'iga (SQLite) bog'langan.
"""
import contextlib
import re
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_products_tracked_scope import (
    _AGG,
    ICHIDA,
    KATALOG,
    _dokon,
    _eski_agregatlar,
    _kutilgan,
    _m,
    _niqob,
    _solishtir,
)

# '%' va '_' — ESCAPE'siz ILIKE'da joker. Har biri uchun JOKER bo'lsa topiladigan aldamchi qator.
KATALOG_PG = KATALOG + (
    _m("Yogurt 100% kuzatuvli", tl=True, inv={"A": ("4", "1"), "B": ("6", "2")},
       sotuv=[("A", "2", ICHIDA)]),
    _m("Yogurt 1000 kuzatuvli", tl=True, inv={"A": ("40", "3")}, sotuv=[("B", "5", ICHIDA)]),
    _m("Kefir_2 kuzatuvli", tl=True, te=True, inv={"B": ("3", "1")}),
    _m("Kefir12 kuzatuvli", tl=True, inv={"A": ("30", "2")}),
    _m("Ayron 50% oddiy", inv={"A": ("7", "1")}, sotuv=[("A", "1", ICHIDA)]),
)
AKTYORLAR = {"ega@-": None, "omborchi@A": {"A"}, "menejer@-": None}


def _baza(url):
    _initdb(url)
    eng = create_engine(url)
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def _seed(S, **dokonlar):
    s = S()
    try:
        out = {k: _dokon(s, k, kat, **kw) for k, (kat, kw) in dokonlar.items()}
        s.commit()
        return out
    finally:
        s.close()


@contextlib.contextmanager
def _sql(eng):
    got = []

    def _ol(conn, cursor, statement, params, context, executemany):
        got.append((statement, params))

    event.listen(eng, "before_cursor_execute", _ol)
    try:
        yield got
    finally:
        event.remove(eng, "before_cursor_execute", _ol)


def _royxat(eng, S, d, kalit, **kw):
    """`list_products` — endpoint bilan AYNI funksiya; (javob JSON'i, bajarilgan so'rovlar)."""
    from app.api.v1.products import list_products
    from app.models.auth import Employee
    args = {"q": None, "category_id": None, "branch_id": None, "archived": False,
            "include_archived": False, "tracked": None}
    args.update(kw)
    s = S()
    try:
        emp = s.get(Employee, d["x"][kalit]["id"])
        with _sql(eng) as got:
            body = [x.model_dump(mode="json") for x in list_products(**args, emp=emp, db=s)]
        return body, got
    finally:
        s.rollback()
        s.close()


def _explain(eng, statement, params):
    """Ushlangan agregat so'rovning rejasi. Mijoz tomonida bog'lash (ClientCursor) —
    utility buyrug'ida server tomoni parametrlariga tayanmaslik uchun."""
    import psycopg
    raw = eng.raw_connection()
    try:
        cur = psycopg.ClientCursor(raw.driver_connection)
        cur.execute("EXPLAIN (COSTS OFF) " + statement, params)
        return "\n".join(r[0] for r in cur.fetchall())
    finally:
        raw.close()


def test_PG_PARITET_tracked_true_false_none_ILIKE_escape_bilan(pg_target):
    eng, S = _baza(pg_target)
    try:
        dk = _seed(S, T=(KATALOG_PG, {}),
                   U=(KATALOG_PG, {"koef": 100, "xodimlar": (("ega", None),)}))
        t, u = dk["T"], dk["U"]

        # Escape haqiqatan muhim: joker bo'lsa aldamchi qatorlar ham kelardi.
        assert [r["nom"] for r in _kutilgan(t, q="0%", tracked=True)] == ["Yogurt 100% kuzatuvli"]
        assert [r["nom"] for r in _kutilgan(t, q="r_2", tracked=True)] == ["Kefir_2 kuzatuvli"]

        cheklov = re.compile(r"product_id IN \(SELECT products\.id\s+FROM products\b")
        begona = {str(r["id"]) for r in u["p"].values()}
        holatlar = [(k, tr, q) for k in AKTYORLAR for tr in (None, True, False)
                    for q in (None, "0%", "r_2", "qatiq")]
        for kalit, tracked, q in holatlar:
            kutilgan = _kutilgan(t, q=q, tracked=tracked)
            if not kutilgan:
                continue
            doira = AKTYORLAR[kalit] and {t["fil"][f] for f in AKTYORLAR[kalit]}
            body, got = _royxat(eng, S, t, kalit, q=q, tracked=tracked)
            assert not ({x["id"] for x in body} & begona)
            s = S()
            try:
                _solishtir(s, t, body, kutilgan, doira, tartib=False)
                with _sql(eng) as eski:
                    if tracked is None:
                        _eski_agregatlar(s, t["cid"], doira)
            finally:
                s.close()
            agg = [(st, p) for st, p in got if _AGG.search(st)]
            assert len(agg) == 3, [st for st, _ in agg]
            if tracked is None:
                # `tracked`'siz yo'l: psycopg dialektida ham tuzatishdan oldingi SQL bilan AYNAN.
                eski = [(st, p) for st, p in eski if _AGG.search(st)]
                assert _niqob(agg) == _niqob(eski), (kalit, q)
                continue
            # Subquery AYNI filtrdan: tracked=false -> `IS false` (qat'iy `IS true` emas).
            belgi = f"track_lots IS {'true' if tracked else 'false'}"
            for st, p in agg:
                assert cheklov.search(st) and belgi in st, st
                matn = st + repr(p)
                for r in t["p"].values():
                    assert str(r["id"]) not in matn and r["id"].hex not in matn, st

        # Aniq filial: faqat o'sha filial qoldig'i, sotilgan — kompaniya bo'yicha.
        body, _ = _royxat(eng, S, t, "ega@-", tracked=True, branch_id=t["fil"]["B"])
        s = S()
        try:
            _solishtir(s, t, body, _kutilgan(t, tracked=True), {t["fil"]["B"]}, tartib=False)
        finally:
            s.close()
        yog = next(x for x in body if x["name"] == "Yogurt 100% kuzatuvli")
        assert (yog["stock"], yog["min_stock"], yog["sold_qty"]) == (6.0, 2.0, 2.0)
    finally:
        eng.dispose()


def test_PG_BOSH_natija_AGREGAT_sorovsiz_va_branch_id_TEKSHIRUVI_OLDIN(pg_target):
    eng, S = _baza(pg_target)
    try:
        dk = _seed(S, T=(KATALOG_PG, {}),
                   V=([r for r in KATALOG_PG if not r["track_lots"]], {"xodimlar": (("ega", None),)}))
        t, v = dk["T"], dk["V"]

        body, got = _royxat(eng, S, v, "ega@-", tracked=True)
        assert body == [] and got
        assert not [st for st, _ in got if _AGG.search(st)], got
        body, got = _royxat(eng, S, t, "omborchi@A", tracked=True, q="hech-qanday-mos-yoq")
        assert body == [] and not [st for st, _ in got if _AGG.search(st)]
        # NAZORAT: natija bo'lsa agregatlar ishlaydi.
        body, got = _royxat(eng, S, v, "ega@-", tracked=False)
        assert body and len([st for st, _ in got if _AGG.search(st)]) == 3

        for q in (None, "hech-qanday-mos-yoq"):
            for kalit, bid, kod in (("omborchi@A", t["fil"]["B"], 403),
                                    ("ega@-", v["fil"]["A"], 400),
                                    ("ega@-", t["fil"]["D"], 400),
                                    ("menejer@-", uuid.uuid4(), 400)):
                with pytest.raises(HTTPException) as e:
                    _royxat(eng, S, t, kalit, tracked=True, q=q, branch_id=bid)
                assert e.value.status_code == kod, (kalit, q, e.value.detail)
        body, _ = _royxat(eng, S, t, "omborchi@A", tracked=True, branch_id=t["fil"]["A"])
        assert body                                                           # nazorat: o'z filiali
    finally:
        eng.dispose()


def test_PG_EXPLAIN_agregat_rejasida_MAHSULOT_cheklovi(pg_target):
    eng, S = _baza(pg_target)
    try:
        t = _seed(S, T=(KATALOG_PG, {}))["T"]
        with eng.begin() as con:
            con.exec_driver_sql("ANALYZE")

        _, got = _royxat(eng, S, t, "omborchi@A", tracked=True, q="0%")
        agg = [(st, p) for st, p in got if _AGG.search(st)]
        assert len(agg) == 3
        for st, p in agg:
            plan = _explain(eng, st, p)
            assert "track_lots" in plan, plan
            assert re.search(r"Semi Join|SubPlan|Join|Nested Loop", plan), plan

        # NAZORAT: `tracked`'siz agregat rejasida kuzatuv cheklovi YO'Q.
        _, got = _royxat(eng, S, t, "omborchi@A")
        agg = [(st, p) for st, p in got if _AGG.search(st)]
        assert len(agg) == 3
        for st, p in agg:
            assert "track_lots" not in _explain(eng, st, p)
    finally:
        eng.dispose()
