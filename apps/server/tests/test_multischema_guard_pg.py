# -*- coding: utf-8 -*-
"""SXEMA-XABARDOR INDEKS GARDI — HAQIQIY Postgres, `public` + `cash` yonma-yon.

NEGA BU FAYL BOR
================
`index_guard` ning katalog so'rovlari `nspname = 'public'` bo'yicha QATTIQ
filtrlardi, kesh kaliti esa `(id(bind), indeks, jadval)` edi. O'lchangan
(tuzatishdan OLDIN, shu harness bilan):
  · `cash.sh_one_open_per_account` MAVJUD bo'lsa ham hukm `bad`;
  · uni DROP qilsa — AYNI `bad`; noto'g'ri shaklga almashtirsa — AYNI `bad`.
    Ya'ni gard cash uchun «bor / yo'q / buzuq» ni AJRATMASDI;
  · `shifts` jadvali IKKI sxemada ham bor, shu bois ayni nomli indeks
    so'ralganda javob public nusxasidan kelardi — cash savoliga YOLG'ON `ok`.

⚠️  BITTA KLASTER (modul doirasi). Mashina 85 % commit ostida, 322 begona
    postgres bor — ko'p-klaster bo'roni TAQIQ.
⚠️  Har DDL dan keyin `ig.reset_cache()` — AKS HOLDA o'lchov TTL ni, mahsulotni
    emas o'lchagan bo'lardi. Kesh TO'QNASHUVI testida esa kesh ATAYLAB
    bo'shatilMAYDI: aynan shu yerda sxemasiz kalit ko'rinadi.
"""
from __future__ import annotations

import tempfile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.core import index_guard as ig
from app.core import required_schema as rs

#: `cash.shifts` BO'SH — shu bois quyidagi «noto'g'ri» shakllar haqiqiy bazada ham
#: qurilaveradi (qismiy indeks hech bir qatorni qamramaydi -> noyoblik trivial).
CASH_IX = "sh_one_open_per_account"
CASH_TBL = "shifts"
CASH_TIKLASH = ("CREATE UNIQUE INDEX sh_one_open_per_account "
                "ON cash.shifts (cash_account_id) WHERE status = 'OPEN'")


def _norm(u: str) -> str:
    return ("postgresql+psycopg://" + u[len("postgresql://"):]
            if u.startswith("postgresql://") and "+psycopg" not in u else u)


@pytest.fixture(scope="module")
def eng():
    pgserver = pytest.importorskip("pgserver")
    from app.db.base import Base
    from app.db.cash.deploy import deploy_cash_schema, ensure_phase1_objects
    import app.models  # noqa: F401

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="msguard_"))
    e = create_engine(_norm(srv.get_uri()), future=True)
    Base.metadata.create_all(e)
    assert deploy_cash_schema(e) == "deployed"
    assert ensure_phase1_objects(e).startswith("applied:")
    #  public tomonidagi xom qismiy indeks — `create_all` uni YARATMAYDI.
    with e.begin() as con:
        con.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_cashier_open "
            "ON shifts (cashier_id) WHERE status = 'open' AND deleted_at IS NULL"))
    try:
        yield e
    finally:
        e.dispose()


@pytest.fixture(autouse=True)
def _kesh():
    ig.reset_cache()
    yield
    ig.reset_cache()


def _ddl(e, *sqls):
    with e.begin() as con:
        for q in sqls:
            con.execute(text(q))
    ig.reset_cache()


# ══ 1. CASH INDEKSI KO'RINADI — bor / yo'q / buzuq AJRATILADI ═══════════════

def test_PG_CASH_indeksi_KORINADI_va_holatlar_AJRATILADI(eng):
    """⚠️  BU TESTNING MOHIYATI: uch holat UCH XIL javob berishi SHART.

    Tuzatishdan oldin uchalasi ham `bad` edi — ya'ni gard cash sxemasi uchun
    butunlay ko'r edi va «kafolat bor» ni «kafolat yo'q» dan ajratmasdi.
    """
    #  (a) HAQIQIY cash indeksi -> OK
    assert ig.index_state(eng, CASH_IX, CASH_TBL, schema="cash") == ig.OK
    #  (b) DROP -> BAD
    _ddl(eng, f"DROP INDEX IF EXISTS cash.{CASH_IX}")
    try:
        assert ig.index_state(eng, CASH_IX, CASH_TBL, schema="cash") == ig.BAD
        #  (c) NOYOB EMAS, ayni nom -> BAD (shakl emas, NOYOBLIK darvozasi)
        _ddl(eng, f"CREATE INDEX {CASH_IX} ON cash.shifts (cash_account_id) "
                  f"WHERE status = 'OPEN'")
        assert ig.index_state(eng, CASH_IX, CASH_TBL, schema="cash") == ig.BAD
        _ddl(eng, f"DROP INDEX IF EXISTS cash.{CASH_IX}")
    finally:
        _ddl(eng, CASH_TIKLASH)
    assert ig.index_state(eng, CASH_IX, CASH_TBL, schema="cash") == ig.OK


# ══ 2. PUBLIC xulqi O'ZGARMADI ══════════════════════════════════════════════

def test_PG_PUBLIC_xulqi_AYNI_qoladi(eng):
    """Standart `schema="public"` — eski chaqiruvchilar uchun hukm AYNI.

    ⚠️  12 ta mavjud `require_index` chaqiruvi SXEMA UZATMAYDI. Agar standart
        qiymat yoki public yo'li o'zgargan bo'lsa, sotuv/qaytarish/qabul/xarid va
        kassa amali HAR so'rovda 409 olardi — shu bois bu test shakl registridagi
        HAR public yozuvni ham tekshiradi.
    """
    assert ig.index_state(eng, "ux_shifts_cashier_open", "shifts") == ig.OK
    #  ANIQ ko'rsatilgan `public` — standart bilan AYNI javob.
    assert ig.index_state(eng, "ux_shifts_cashier_open", "shifts",
                          schema="public") == ig.OK
    #  Shakl registri public tomonda ishlashda davom etadi.
    defs = rs.index_definition_states(eng)
    assert defs.get("ux_shifts_cashier_open") == rs.IX_DEF_OK, defs
    #  Tayyorlik PUBLIC-ONLY qoladi: cash shakllari `/health/ready` ga CHIQMAYDI.
    muammolar = rs.index_definition_problems(eng)
    assert not [m for m in muammolar if "sh_one_open" in m or "cle_uq" in m
                or "cao_uq" in m or "rr_" in m], muammolar


# ══ 3. KESH KALITI SXEMA-XABARDOR — ayni nom ikki sxemada ═══════════════════

def test_PG_KESH_ayni_nomni_SXEMA_boyicha_AJRATADI(eng):
    """⚠️  KESHNI ATAYLAB BO'SHATMAYMIZ — mutatsiya A aynan shu yerda ko'rinadi.

    `shifts` jadvali public'da HAM, cash'da HAM bor (`app/models/cash.py`:
    `__tablename__ = "shifts"`, `{"schema": "cash"}`). Shu bois `(indeks, jadval)`
    juftligi IKKI sxemada AYNI bo'lishi mumkin. Kesh kalitida sxema bo'lmasa
    birinchi javob TTL davomida ikkinchisiga ham qo'llanardi: public nusxasi
    sog'lom bo'lsa, cash'dagi YO'Q kafolat «bor» bo'lib ko'rinardi.
    """
    _ddl(eng,
         "DROP INDEX IF EXISTS zz_both",
         "DROP INDEX IF EXISTS cash.zz_both",
         "CREATE UNIQUE INDEX zz_both ON shifts (id)",        # public: KAFOLAT BOR
         "CREATE INDEX zz_both ON cash.shifts (id)")          # cash: KAFOLAT YO'Q
    try:
        assert ig._TTL_SECONDS > 0, "TTL 0 bo'lsa bu test hech narsa o'lchamaydi"
        assert ig.index_state(eng, "zz_both", "shifts", schema="public") == ig.OK
        #  KESH BO'SHATILMAYDI: ikkinchi savol BOSHQA sxema haqida.
        assert ig.index_state(eng, "zz_both", "shifts", schema="cash") == ig.BAD, (
            "cash javobi public keshidan keldi — kesh kalitida SXEMA YO'Q")
        #  Teskari tartib ham: cash avval so'ralsa public javobi buzilmasin.
        ig.reset_cache()
        assert ig.index_state(eng, "zz_both", "shifts", schema="cash") == ig.BAD
        assert ig.index_state(eng, "zz_both", "shifts", schema="public") == ig.OK
    finally:
        _ddl(eng, "DROP INDEX zz_both", "DROP INDEX cash.zz_both")


# ══ 4. XATO SXEMA MATRITSASI — YOLG'ON `OK` BO'LMASIN ══════════════════════

#: (izoh, indeks, jadval, sxema, DDL ro'yxati yoki None, KUTILGAN holat)
#
#  ⚠️  SXEMA VA INDEKS JUFTLIGI ATAYLAB ALOHIDA. «To'g'ri public» qatori PUBLIC
#      indeksini, «xato sxema» qatori esa AYNI CASH indeksini PUBLIC sxemada
#      so'raydi — ikkinchisi fail-closed bo'lishi shart, chunki u yerda obyekt YO'Q.
MATRITSA = [
    ("to'g'ri public", "ux_shifts_cashier_open", "shifts", "public", None, "OK"),
    ("to'g'ri cash", CASH_IX, CASH_TBL, "cash", None, "OK"),
    ("XATO sxema (indeks cash'da, PUBLIC so'raldi)",
     CASH_IX, CASH_TBL, "public", None, "BAD"),
    ("XATO sxema teskari (public indeksi CASH'da so'raldi)",
     "ux_shifts_cashier_open", "shifts", "cash", None, "BAD"),
    ("MAVJUD BO'LMAGAN sxema", CASH_IX, CASH_TBL, "zz_yoq_sxema", None, "BAD"),
    ("bo'sh sxema nomi", CASH_IX, CASH_TBL, "", None, "BAD"),
    ("indeks YO'Q", CASH_IX, CASH_TBL, "cash",
     [f"DROP INDEX IF EXISTS cash.{CASH_IX}"], "BAD"),
    ("NOTO'G'RI USTUN (ayni nom, cash)", CASH_IX, CASH_TBL, "cash",
     [f"DROP INDEX IF EXISTS cash.{CASH_IX}",
      f"CREATE UNIQUE INDEX {CASH_IX} ON cash.shifts (branch_id) "
      f"WHERE status = 'OPEN'"], "BAD"),
    ("NOTO'G'RI PREDIKAT (boshqa enum qiymati)", CASH_IX, CASH_TBL, "cash",
     [f"DROP INDEX IF EXISTS cash.{CASH_IX}",
      f"CREATE UNIQUE INDEX {CASH_IX} ON cash.shifts (cash_account_id) "
      f"WHERE status = 'CLOSING'"], "BAD"),
    ("KANONIZATSIYA BO'LMAYDI (funksiya chaqiruvi)", CASH_IX, CASH_TBL, "cash",
     [f"DROP INDEX IF EXISTS cash.{CASH_IX}",
      f"CREATE UNIQUE INDEX {CASH_IX} ON cash.shifts (cash_account_id) "
      f"WHERE status = 'OPEN' AND lower(id::text) IS NULL"], "UNVERIFIABLE"),
]


def test_PG_XATO_SXEMA_matritsasi(eng):
    """⚠️  HAMMASI FAIL-CLOSED. Yolg'on `OK` — jim nuqson: kafolat yo'q bo'lsa ham
        gard indamay o'tkazib yuborardi, ya'ni «qo'riqlangan» yozuv aslida
        qo'riqlanmagan bo'lardi. Shu bois har bir qator ALOHIDA qadab qo'yilgan.
    ⚠️  «Tekshirib bo'lmadi» `UNVERIFIABLE` bo'lishi SHART, `BAD` EMAS: u
        KESHLANMAYDI, ya'ni o'tkinchi nosozlik abadiy uzilishga aylanmaydi.
    """
    for izoh, ix, tbl, sxema, ddl, kutilgan in MATRITSA:
        if ddl:
            _ddl(eng, *ddl)
        try:
            ig.reset_cache()
            holat = ig.index_state(eng, ix, tbl, schema=sxema)
            assert holat == getattr(ig, kutilgan), (izoh, sxema, holat, kutilgan)
            if kutilgan != "OK":
                #  Yozuvchi darajasida ham RAD etilsin (409 + barqaror kod).
                with pytest.raises(HTTPException) as ei:
                    ig.require_index(eng, ix, tbl,
                                     operation="cash_probe", schema=sxema)
                assert ei.value.status_code == 409, izoh
                assert (ei.value.headers or {}).get("X-Error-Code") == \
                    ig.SCHEMA_GUARANTEE_MISSING, izoh
        finally:
            #  ⚠️  TIKLASH HAR QATORDAN KEYIN va `IF EXISTS` bilan: modul doirasida
            #      BITTA klaster ishlatiladi, ya'ni o'chirilgan indeks keyingi
            #      TESTLARGA oqib o'tadi. Bitta yiqilish qolgan testlarni ham
            #      buzardi va mutatsiya isboti YOLG'ON signal berardi (bu tuzoqqa
            #      oldingi fazada tushilgan).
            if ddl:
                _ddl(eng, f"DROP INDEX IF EXISTS cash.{CASH_IX}", CASH_TIKLASH)
    #  Oxirida sog'lom holat — keyingi testlarga iz qoldirmaydi.
    ig.reset_cache()
    assert ig.index_state(eng, CASH_IX, CASH_TBL, schema="cash") == ig.OK


# ══ 5. CASH SHAKL REGISTRI haqiqiy bazaga MOS ══════════════════════════════

def test_PG_CASH_registri_HAQIQIY_bazaga_MOS(eng):
    """⚠️  BU TEST UZILISHDAN SAQLAYDI. Registr yozuvi haqiqiy `cash` sxemasidan
        farq qilsa, kelajakda cash gardini simlagan HAR yozuv 409 olardi. Shu
        bois ustun/predikatlarning MOSLIGI o'lchanadi, qo'lda tekshirilmaydi.
    ⚠️  IKKI yozuv (`sh_one_open_per_account`, `cx_one_open_per_kind`) SXEMA
        BILAN KVALIFIKATSIYALANGAN enum keltirishiga tayanadi
        (`'OPEN'::cash.cash_shift_status`) — `check_canon` enum normalizatsiyasi
        olib tashlansa aynan bu ikkisi `IX_DEF_WRONG` berardi.
    """
    assert rs.CASH_INDEX_DEFINITIONS, "cash registri bo'sh"
    #  ⚠️  O'Z HOLATINI O'ZI TA'MINLAYDI: modul klasteri umumiy, shu bois boshqa
    #      testning yiqilishi bu yerda YOLG'ON qizil bermasin.
    _ddl(eng, f"DROP INDEX IF EXISTS cash.{CASH_IX}", CASH_TIKLASH)
    st = rs.index_definition_states(eng, schema="cash")
    for nm in rs.CASH_INDEX_DEFINITIONS:
        assert st.get(nm) == rs.IX_DEF_OK, (nm, st.get(nm))
        tbl = rs.CASH_INDEX_DEFINITIONS[nm][0]
        assert ig.index_state(eng, nm, tbl, schema="cash") == ig.OK, nm
    #  Registrdagi hamma obyekt QISMIY INDEKS (constraint EMAS) — DROP mumkin,
    #  ya'ni gard haqiqatan kerak bo'ladigan sinf.
    with eng.connect() as con:
        rows = dict(con.execute(text(
            "SELECT c.relname, (con.oid IS NOT NULL) "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_constraint con ON con.conindid = i.indexrelid "
            "WHERE n.nspname = 'cash' AND c.relname = ANY(:n)"),
            {"n": sorted(rs.CASH_INDEX_DEFINITIONS)}).fetchall())
    for nm in rs.CASH_INDEX_DEFINITIONS:
        assert rows.get(nm) is False, (
            f"{nm} CONSTRAINT bilan qo'llangan — registr izohi QISMIY INDEKS deydi")
