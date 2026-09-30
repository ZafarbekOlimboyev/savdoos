# -*- coding: utf-8 -*-
"""INDEKS GARDI — HAQIQIY Postgres va HAQIQIY qo'riqlangan yozuvchi (SAFE-02).

NEGA BU FAYL BOR
================
`tests/test_index_guarantee_guard.py` gard MANTIQINI qadab qo'yadi, lekin u butunlay
monkeypatch va soxta bind ustida ishlaydi: `_unique_index_states` almashtiriladi,
haqiqiy katalog hech qachon o'qilmaydi va birorta HAQIQIY yozuv bajarilmaydi. Shu
bois u ikki zond (noyoblik va SHAKL) haqiqiy bazada bir-biriga MOS KELMAYDIGAN
javob berishi mumkinligini ko'ra olmasdi.

Yozuvchi sifatida `doc_seq.allocate` tanlandi: u `doc_counters` ning YAGONA
yozuvchisi (`doc_seq.py` izohi), gard `ux_doc_counter` ni talab qiladi va yo'l pul
ko'chirmaydi — ya'ni eng kichik deterministik haqiqiy qo'riqlangan yozuv.

SAFE-02 TOPILMASI
=================
⚠️  «Majburiy indeks uchun ta'rif qatori yo'qolsa gard o'chadi» degan gumon AYTILGAN
    SHAKLIDA NOTO'G'RI: indeks jismonan o'chirilsa `index_definition_states` kalit
    qaytarmaydi, LEKIN noyoblik zondi ham uni ko'rmaydi va gard BAD beradi — yozuv
    409 bilan rad etiladi (`test_PG_indeks_YOQ_bolsa_yozuv_RAD`).
⚠️  Haqiqiy nuqson TORROQ va BOSHQA: ikki zond IKKI ALOHIDA ulanishda o'qiydi, shu
    bois oraliqda `DROP INDEX` bo'lsa noyoblik zondi «bor» deydi, shakl zondi esa
    hukm BERMAYDI. Ilgari shu holat pastga tushib `OK` KESHLAGAN edi: indeks bazada
    YO'Q bo'lsa ham yozuv o'tib ketardi va BITTA poyga keshni butun TTL davomida
    zaharlardi (`test_PG_POYGA_*`). Endi bu `UNVERIFIABLE` — keshlanmaydi, rad etadi.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core import index_guard as ig
from app.core import required_schema as rs
from app.models.org import Company
from app.services import doc_seq

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IX = "ux_doc_counter"
TBL = "doc_counters"
#  AYNAN `REQUIRED_INDEX_DEFINITIONS["ux_doc_counter"]` shakli: (company_id, kind), predikatsiz.
TOGRI_DDL = f"CREATE UNIQUE INDEX {IX} ON {TBL} (company_id, kind)"


@pytest.fixture(scope="module")
def pg():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp())
    u = srv.get_uri()
    url = ("postgresql+psycopg://" + u[len("postgresql://"):]
           if u.startswith("postgresql://") and "+psycopg" not in u else u)
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    env.pop("PYTHONIOENCODING", None)
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV,
                       capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    eng = create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def Sess(pg):
    return sessionmaker(bind=pg, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture(autouse=True)
def toza(pg):
    """Har testdan KEYIN indeksni to'g'ri shaklga qaytaradi va keshni bo'shatadi.

    ⚠️  Tiklash `finally` emas, fixture teardown'ida: test yiqilsa ham keyingi test
        toza bazadan boshlaydi (aks holda bitta yiqilish qolganini ham qizil qilardi).
    """
    ig.reset_cache()
    yield
    with pg.begin() as con:
        con.execute(text(f"DROP INDEX IF EXISTS {IX}"))
        con.execute(text(TOGRI_DDL))
    ig.reset_cache()


def _ddl(pg, *stmts):
    with pg.begin() as con:
        for s in stmts:
            con.execute(text(s))
    ig.reset_cache()


def _kompaniya(Sess) -> uuid.UUID:
    with Sess() as db:
        cid = uuid.uuid4()
        db.add(Company(id=cid, name=f"S02 {cid.hex[:8]}"))
        db.commit()
    return cid


def _yozuv(Sess, cid):
    """HAQIQIY qo'riqlangan yozuv. -> ("YOZILDI", raqam) yoki ("RAD", status)."""
    with Sess() as db:
        try:
            n = doc_seq.allocate(db, cid, doc_seq.SALE)
            db.commit()
            return ("YOZILDI", n)
        except HTTPException as e:
            db.rollback()
            return ("RAD", e.status_code)


def _bazada_bormi(pg) -> bool:
    with pg.connect() as con:
        return con.execute(text("SELECT 1 FROM pg_class WHERE relname = :n"),
                           {"n": IX}).first() is not None


# ══ 1. IJOBIY: ta'rif bor + indeks TO'G'RI -> HAQIQIY yozuv o'tadi ═════════

def test_PG_indeks_TOGRI_bolsa_HAQIQIY_yozuv_otadi(pg, Sess):
    cid = _kompaniya(Sess)
    assert ig.index_state(pg, IX, TBL) == ig.OK
    assert rs.index_definition_states(pg).get(IX) == rs.IX_DEF_OK
    natija, raqam = _yozuv(Sess, cid)
    assert natija == "YOZILDI", natija
    assert isinstance(raqam, int)


# ══ 2. SALBIY: haqiqiy katalog holatlari -> yozuv RAD ══════════════════════

def test_PG_indeks_YOQ_bolsa_yozuv_RAD(pg, Sess):
    """«Ta'rif qatori yo'q» ning TABIIY shakli — gard O'CHMAYDI, BAD beradi.

    ⚠️  Bu AYNAN SAFE-02 gumonini rad etadigan test: shakl zondi kalit qaytarmaydi
        (`(KALIT YO'Q)`), lekin noyoblik zondi ham indeksni ko'rmaydi, ya'ni holat
        BAD va yozuv 409. Gumon aytilgan shaklida NOTO'G'RI.
    """
    cid = _kompaniya(Sess)
    _ddl(pg, f"DROP INDEX {IX}")
    assert IX not in rs.index_definition_states(pg), "shakl zondi kalit qaytardi"
    assert ig.index_state(pg, IX, TBL) == ig.BAD
    assert _yozuv(Sess, cid) == ("RAD", 409)


def test_PG_indeks_NOYOB_EMAS_bolsa_yozuv_RAD(pg, Sess):
    cid = _kompaniya(Sess)
    _ddl(pg, f"DROP INDEX {IX}", f"CREATE INDEX {IX} ON {TBL} (company_id, kind)")
    assert ig.index_state(pg, IX, TBL) == ig.BAD
    assert _yozuv(Sess, cid) == ("RAD", 409)


@pytest.mark.parametrize("ddl,label", [
    (f"CREATE UNIQUE INDEX {IX} ON {TBL} (company_id)", "ustunlar KAM"),
    (f"CREATE UNIQUE INDEX {IX} ON {TBL} (kind, company_id)", "ustunlar TARTIBI teskari"),
    (f"CREATE UNIQUE INDEX {IX} ON {TBL} (company_id, kind) WHERE next_value > 0",
     "ORTIQCHA predikat"),
])
def test_PG_SHAKLI_notogri_bolsa_yozuv_RAD(pg, Sess, ddl, label):
    """Noyob, lekin shakli boshqa indeks kafolat BERMAYDI — shakl ko'rligi yo'q."""
    cid = _kompaniya(Sess)
    _ddl(pg, f"DROP INDEX {IX}", ddl)
    assert rs.index_definition_states(pg).get(IX) == rs.IX_DEF_WRONG, label
    assert ig.index_state(pg, IX, TBL) == ig.BAD, label
    assert _yozuv(Sess, cid) == ("RAD", 409), label


def test_PG_katalog_oqilmasa_yozuv_RAD(pg, Sess, monkeypatch):
    """Ikki zondning HAR BIRI yiqilsa ham fail-closed (UNVERIFIABLE)."""
    cid = _kompaniya(Sess)

    def _boom(*a, **k):
        raise RuntimeError("katalog o'qilmadi (simulyatsiya)")

    for nom in ("_unique_index_states", "index_definition_states"):
        ig.reset_cache()
        monkeypatch.setattr(rs, nom, _boom)
        assert ig.index_state(pg, IX, TBL) == ig.UNVERIFIABLE, nom
        assert _yozuv(Sess, cid) == ("RAD", 409), nom
        monkeypatch.undo()


# ══ 3. SAFE-02 REGRESSIYASI: HUKM YO'Q = TEKSHIRILMADI, «TO'G'RI» EMAS ═════

def test_PG_POYGA_zondlar_orasida_DROP_INDEX_yozuvni_TOSADI(pg, Sess, monkeypatch):
    """Ikki zond IKKI ALOHIDA ulanishda o'qiydi — oraliqda indeks yo'qolsa RAD.

    ⚠️  TUZATISHDAN OLDIN: noyoblik zondi «bor» deydi, shakl zondi hukm bermaydi,
        `d is None` pastga tushib `OK` KESHLANARDI va HAQIQIY yozuv o'tib ketardi —
        indeks bazada YO'Q bo'lsa ham. O'lchangan: `indeks_bazada=False`, `holat=ok`,
        `yozuv=YOZILDI`.
    """
    cid = _kompaniya(Sess)
    asl = rs.index_definition_states

    def _oradan_ochir(bind):
        #  Noyoblik zondi ALLAQACHON o'qib bo'ldi; endi indeks yo'qoladi.
        with pg.begin() as con:
            con.execute(text(f"DROP INDEX IF EXISTS {IX}"))
        return asl(bind)

    monkeypatch.setattr(rs, "index_definition_states", _oradan_ochir)
    holat = ig.index_state(pg, IX, TBL)
    natija = _yozuv(Sess, cid)
    monkeypatch.undo()

    assert holat == ig.UNVERIFIABLE, "poyga OK bo'lib o'tdi — fail-open"
    assert natija == ("RAD", 409), natija
    assert not _bazada_bormi(pg), "test o'z shartini qurmadi: indeks hali ham bor"


def test_PG_POYGA_keshni_ZAHARLAMAYDI(pg, Sess, monkeypatch):
    """`UNVERIFIABLE` keshlanmaydi — keyingi so'rov qaytadan tekshiradi va BAD ko'radi.

    ⚠️  Ilgari bitta poyga `OK` ni keshlardi, ya'ni TTL tugaguncha HAR qo'riqlangan
        yozuv qo'riqsiz o'tardi. Bu bitta yozuv emas, TTL uzunligidagi OYNA edi.
    """
    cid = _kompaniya(Sess)
    asl = rs.index_definition_states

    def _oradan_ochir(bind):
        with pg.begin() as con:
            con.execute(text(f"DROP INDEX IF EXISTS {IX}"))
        return asl(bind)

    monkeypatch.setattr(rs, "index_definition_states", _oradan_ochir)
    ig.index_state(pg, IX, TBL)              # poyga
    monkeypatch.undo()

    #  Kesh BO'SHATILMAYDI: aynan keshning o'zi tekshiriladi.
    assert not _bazada_bormi(pg)
    assert ig.index_state(pg, IX, TBL) == ig.BAD, "poyga OK ni keshlab qo'ydi"
    assert _yozuv(Sess, cid) == ("RAD", 409)


def test_PG_SHAKL_zondi_BOSH_qaytarsa_yozuv_RAD(pg, Sess, monkeypatch):
    """Zondlar ZID javob bersa (noyoblik OK, shakl bo'sh) -> UNVERIFIABLE.

    ⚠️  Bu holatni ATAYLAB soxtalashtiramiz: `index_definition_states` haqiqiy bazada
        topilgan indeks uchun ALBATTA kalit qaytaradi, ya'ni tabiiy yo'li faqat
        yuqoridagi POYGA. Lekin shox baribir qadab qo'yiladi — kelajakda ikki zond
        o'rtasida yangi asimmetriya paydo bo'lsa (masalan chaqiruvchi `table` ni
        `REQUIRED_INDEX_DEFINITIONS` dagidan boshqa bersa) shu yerga tushadi.
    """
    cid = _kompaniya(Sess)
    monkeypatch.setattr(rs, "index_definition_states", lambda bind: {})
    assert ig.index_state(pg, IX, TBL) == ig.UNVERIFIABLE
    assert _yozuv(Sess, cid) == ("RAD", 409)
    monkeypatch.undo()
    ig.reset_cache()
    #  Soxtalashtirish olingach yozuv QAYTA ishlaydi — rad etish yopishib qolmaydi.
    assert _yozuv(Sess, cid)[0] == "YOZILDI"


# ══ 4. TIKLANISH: operator tuzatgach yozuv QAYTA ishlaydi ══════════════════

def test_PG_TIKLANISH_indeks_tuzatilgach_yozuv_QAYTA_otadi(pg, Sess):
    cid = _kompaniya(Sess)
    _ddl(pg, f"DROP INDEX {IX}")
    assert _yozuv(Sess, cid) == ("RAD", 409)
    _ddl(pg, TOGRI_DDL)                       # operator tuzatdi (+ kesh bo'shatildi)
    assert ig.index_state(pg, IX, TBL) == ig.OK
    assert _yozuv(Sess, cid)[0] == "YOZILDI"


def test_PG_kesh_BIND_boyicha_ajratilgan(pg, Sess):
    """Kesh kaliti bind'ni o'z ichiga oladi — SAFE-02 tuzatishi buni buzmadi."""
    cid = _kompaniya(Sess)
    assert ig.index_state(pg, IX, TBL) == ig.OK          # bind=pg uchun OK keshlandi
    _ddl(pg, f"DROP INDEX {IX}")                         # (kesh bo'shatildi)
    boshqa = create_engine(str(pg.url))
    try:
        assert ig.index_state(boshqa, IX, TBL) == ig.BAD
        assert ig.index_state(pg, IX, TBL) == ig.BAD, "kesh bindlar orasida oqidi"
    finally:
        boshqa.dispose()
    assert _yozuv(Sess, cid) == ("RAD", 409)
