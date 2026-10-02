# -*- coding: utf-8 -*-
"""Import DALILI: har qator uchun yozuv + rejaning yaxlitligi.

IKKI SAVOLGA JAVOB BERADI:

  «Import NIMANI o'zgartirdi?»  -> `import_rows` (mavjud jadval, yangi jadval yaratilmadi).
  «Qo'llangan reja ko'rib chiqilgani-mi?» -> reja (hisobot, mapping) dan QAYTA quriladi va
                                            ixtiyoriy `expect_plan_sha256` bilan solishtiriladi.

⚠️ NEGA JSON BLOB YETMAYDI. Reja `column_mapping["plan"]` da ham yotadi, lekin blob ichiga indeks
yetib bormaydi: «X ishi qaysi mahsulotlarni yaratdi?» degan savolga javob yo'q. Repo buni
allaqachon hal qilgan — `inventory.py` da partiya taqsimoti aynan shu sababdan alohida jadval.
"""
import uuid

import pytest

from app.models.imports import ImportJob, ImportRow
from app.services.migrator_1c import classify as C
from app.services.migrator_1c.apply import DriftError, apply_migration
from app.services.migrator_1c.catalog import load_snapshot
from app.services.migrator_1c.mapping import build_plan
from tests.migrator_1c_helpers import (actor_of, bundle_dict, g, load, mapping_for, prod,
                                       seed_company)


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _ready(db, products=None):
    comp, (br,) = seed_company(db)
    db.commit()
    b = load(bundle_dict(products or [prod(g(1), "Tovar", stock=("25",)),
                                       prod(g(2), "Ikkinchi", stock=("3",))]))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    return comp, br, b, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE")


def _rows(db, job_id):
    return db.query(ImportRow).filter(ImportRow.job_id == job_id).all()


# ── 1. HAR QATOR UCHUN DALIL ──────────────────────────────────────────────────────────────
def test_har_op_uchun_BITTA_qator_yoziladi(db):
    comp, br, b, rep, m = _ready(db)
    plan = build_plan(rep, m)
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.commit()

    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    rows = _rows(db, job.id)
    kutilgan = len(plan["ops"]) + len(plan["skipped"]) + len(plan["deactivate"])
    assert len(rows) == kutilgan, f"{len(rows)} != {kutilgan}"
    assert job.column_mapping["import_rows"] == str(kutilgan)   # sanoq MATN (qoida 1)


def test_qator_MANBA_va_NATIJANI_bogdaydi(db):
    """Har yozuv 1C qatorini (guid, row_no) BinOS mahsuloti bilan bog'laydi."""
    from app.models.catalog import Product
    comp, br, b, rep, m = _ready(db)
    plan = build_plan(rep, m)
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.commit()

    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    by_guid = {r.raw["guid"]: r for r in _rows(db, job.id) if r.raw.get("guid")}
    for o in plan["ops"]:
        r = by_guid[o["guid"]]
        assert r.job_id == job.id                       # ish identiteti
        assert r.row_no == o["row"]                     # manba qator identiteti
        assert r.parsed["action"] == o["action"]
        assert r.parsed["classification"] == o["classification"]
        assert r.product_id is not None
        p = db.get(Product, r.product_id)
        assert p is not None and p.company_id == comp.id


def test_yaratilgan_qatorlar_CREATED_statusi_bilan(db):
    comp, br, b, rep, m = _ready(db)
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.commit()
    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    st = {r.status for r in _rows(db, job.id)}
    assert st == {"CREATED"}, st


def test_qatorlar_SORALADIGAN_blob_emas(db):
    """Asosiy farq: statusga indeks orqali so'rov qilinadi, blobga esa yo'q."""
    comp, br, b, rep, m = _ready(db)
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.commit()
    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    n = (db.query(ImportRow)
         .filter(ImportRow.job_id == job.id, ImportRow.status == "CREATED").count())
    assert n == 2


def test_ijarachi_ajratilishi_FAQAT_job_orqali(db):
    """⚠️ `import_rows` da `company_id` YO'Q. Join'siz so'rov boshqa do'kon qatorlarini beradi —
    bu shartnomaning bir qismi va test uni qulflaydi."""
    comp_a, br_a, b_a, rep_a, m_a = _ready(db)
    apply_migration(db, b_a, rep_a, m_a, actor_id=actor_of(db, comp_a))
    db.commit()
    comp_b, br_b, b_b, rep_b, m_b = _ready(db)
    apply_migration(db, b_b, rep_b, m_b, actor_id=actor_of(db, comp_b))
    db.commit()

    assert not hasattr(ImportRow, "company_id")
    joined = (db.query(ImportRow).join(ImportJob, ImportJob.id == ImportRow.job_id)
              .filter(ImportJob.company_id == comp_a.id).count())
    hammasi = db.query(ImportRow).count()
    assert joined < hammasi and joined > 0


def test_qatorlar_ish_ochirilganda_birga_ochadi(db):
    """`ON DELETE CASCADE` — katalog tozalanganda yetim qator qolmaydi."""
    comp, br, b, rep, m = _ready(db)
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.commit()
    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    assert _rows(db, job.id)
    db.delete(job)
    db.commit()
    assert _rows(db, job.id) == []


# ── 2. REJA YAXLITLIGI ────────────────────────────────────────────────────────────────────
def test_reja_DETERMINISTIK_qayta_quriladi(db):
    """Reja fayldan o'qilmaydi — u (hisobot, mapping) dan qayta quriladi. Ikkalasi ham xesh
    bilan bog'langan, demak natija ham bir xil bo'lishi kerak."""
    comp, br, b, rep, m = _ready(db)
    assert build_plan(rep, m)["plan_sha256"] == build_plan(rep, m)["plan_sha256"]


def test_TOGRI_reja_xeshi_bilan_APPLY_otadi(db):
    comp, br, b, rep, m = _ready(db)
    sha = build_plan(rep, m)["plan_sha256"]
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp), expect_plan_sha256=sha)
    db.commit()
    assert db.query(ImportJob).filter(ImportJob.company_id == comp.id).count() == 1


def test_NOTOGRI_reja_xeshi_APPLYni_TOXTATADI(db):
    """Hisobot va mapping xeshlari mos, lekin qurilgan reja boshqa — ya'ni `build_plan`
    mantig'i ko'rikdan keyin o'zgargan. Bu JIM qolmasligi kerak."""
    comp, br, b, rep, m = _ready(db)
    with pytest.raises(DriftError, match="REJA ko'rib chiqilganidan FARQ"):
        apply_migration(db, b, rep, m, actor_id=actor_of(db, comp),
                        expect_plan_sha256="0" * 64)
    db.rollback()
    assert db.query(ImportJob).filter(ImportJob.company_id == comp.id).count() == 0
    # Qatorlar ham yozilmagan — sanoq SHU do'kon bo'yicha (join'siz boshqa do'kon aralashadi).
    assert (db.query(ImportRow).join(ImportJob, ImportJob.id == ImportRow.job_id)
            .filter(ImportJob.company_id == comp.id).count()) == 0


def test_reja_xeshi_KATTA_harfda_berilsa_ham_ishlaydi(db):
    comp, br, b, rep, m = _ready(db)
    sha = build_plan(rep, m)["plan_sha256"]
    apply_migration(db, b, rep, m, actor_id=actor_of(db, comp),
                    expect_plan_sha256=sha.upper())
    db.commit()
    assert db.query(ImportJob).filter(ImportJob.company_id == comp.id).count() == 1


def test_mapping_ozgarsa_reja_xeshi_ham_ozgaradi(db):
    """Xesh rejaning BUTUN mazmuniga bog'liq — jumladan hujjat metadatasiga.

    ⚠️ ANIQLANGAN XULQ: `build_plan` `prepared_by` / `prepared_at` ni rejaga ko'chiradi
    (`mapping.py`), shuning uchun operator qaydini o'zgartirish ham `plan_sha256` ni o'zgartiradi.
    Bu shuni anglatadiki, `--expect-plan-sha256` AYNAN ko'rib chiqilgan mapping bilan ishlaydi:
    keyin qaydni tahrirlab qo'yish ham farq sifatida ko'rinadi. Bu qat'iyroq, lekin kutilmagan
    bo'lishi mumkin — shuning uchun test uni ochiq qulflaydi."""
    comp, br, b, rep, m = _ready(db)
    a = build_plan(rep, m)["plan_sha256"]
    assert build_plan(rep, dict(m, prepared_by="boshqa operator"))["plan_sha256"] != a
    assert build_plan(rep, dict(m, mode="CUTOVER_REFRESH"))["plan_sha256"] != a
