# -*- coding: utf-8 -*-
"""MANBA KESIMI (`snapshot_at`) semantikasi va eskirganlik chegaralari.

KANONIK MA'NO (egasining qarori):

    snapshot_at  = jonli 1C holati MUZLATILGAN / NUSXA OLINGAN lahza.
                   Bu yig'uvchi ishlagan vaqt EMAS, tiklash vaqti EMAS, fayl yozilgan vaqt EMAS.
    exported_at  = shu FAYL yaratilgan lahza.

Eskirganlik darvozasi AYNAN `snapshot_at` ni baholaydi (`apply.py`), `exported_at` ni esa hech kim
solishtirmaydi. Copy-first arxitekturasida bu maydon do'konda kimdir ko'rgan lahzadan tashqarida
e'lon qilinadigan DA'VOga aylanadi — shuning uchun uning chegaralari aniq qulflanadi.

Bu fayl ikki qatlamni qoplaydi:
  1. FAYL darajasi (DB kerak emas) — `snapshot_at <= exported_at` va kalendar ishonarliligi;
  2. QO'LLASH darajasi (SQLite) — teng / bir mikrosekund eski / bir mikrosekund yangi, ofset
     farqi, va o'zgarmagan katalogning qayta chiqarilishi.

⚠️ Bu invariantlar TARTIBNI isbotlaydi, ROSTLIKNI emas. Ikkala vaqt belgisini birga surib qo'ygan
ekstraktor hamma tekshiruvdan o'tadi — buni kod tuta olmaydi va shu holat hujjatda ham shunday
yozilgan. Yagona haqiqiy himoya — nusxaning yozma qaydi (`SANDBOX_RESTORE_RUNBOOK.md`).
"""
import json

import pytest

from app.services.migrator_1c import bundle as B
from app.services.migrator_1c import classify as C
from app.services.migrator_1c.apply import AlreadyApplied, StaleSnapshotError, apply_migration
from app.services.migrator_1c.catalog import load_snapshot
from tests.migrator_1c_helpers import bundle_dict, g, load, mapping_for, prod, seed_company

S0 = "2026-09-20T09:00:00+06:00"


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _with_times(snapshot_at: str, exported_at: str) -> dict:
    d = bundle_dict([prod(g(1), "Tovar")], snapshot_at=snapshot_at)
    d["exported_at"] = exported_at
    return d


def _counts(db, comp):
    from app.models.imports import ImportJob
    return db.query(ImportJob).filter(ImportJob.company_id == comp.id).count()


# ── 1. FAYL darajasi ───────────────────────────────────────────────────────────────────────
def test_kesim_eksportdan_KEYIN_bolsa_rad():
    """Holatni qo'lga olishdan oldin eksport qilib bo'lmaydi.

    Bu aynan maydonlar almashib ketgan yoki `snapshot_at` ni qo'lda oldinga surib, eskirganlik
    darvozasini chetlab o'tmoqchi bo'lgan holatni tutadi."""
    with pytest.raises(B.BundleError, match="manba kesimi eksportdan keyin bo'lolmaydi"):
        load(_with_times("2026-09-20T09:00:06+06:00", "2026-09-20T09:00:05+06:00"))


def test_kesim_eksportga_TENG_bolsa_qabul():
    """Chegara `<=`, `<` emas: 1C `Дата` si soniya aniqligida — muzlatish va eksport bir soniyaga
    tushishi mumkin va bu qonuniy."""
    b = load(_with_times(S0, S0))
    assert b.data["snapshot_at"] == b.data["exported_at"] == S0


def test_kesim_eksportdan_oldin_bolsa_qabul():
    assert load(_with_times(S0, "2026-09-20T09:00:05+06:00")) is not None


def test_TENGLIK_boshqa_ofsetda_ham_qabul():
    """Bir xil LAHZA, boshqa ofset — solishtirish satr bo'yicha emas, lahza bo'yicha."""
    assert load(_with_times(S0, "2026-09-20T03:00:00+00:00")) is not None


@pytest.mark.parametrize("bad", ["0001-01-01T00:00:00+06:00", "1970-01-01T00:00:00+00:00",
                                 "9026-09-20T09:00:00+06:00"])
def test_ishonarsiz_kalendar_sanasi_rad(bad):
    """To'ldirilmagan 1C `Дата` si `0001-01-01` beradi, epoch esa 1970 — ikkalasi ham ISO 8601
    sifatida to'g'ri va ikkalasi ham eskirganlik darvozasini jimgina ochib yuborardi."""
    with pytest.raises(B.BundleError, match="ishonarli oraliqda emas"):
        load(bundle_dict([prod(g(1), "A")], snapshot_at=bad))


def test_kesim_mazmun_xeshida_eksport_vaqti_esa_YOQ():
    """Kesim — HOLATNING bir qismi, fayl yozilgan vaqt esa emas.

    Shu polyarlik tufayli o'zgarmagan holatni qayta serializatsiya qilish bir xil mazmun xeshini
    beradi, kesim o'zgarsa esa xesh o'zgaradi."""
    a = load(_with_times(S0, "2026-09-20T09:00:05+06:00"))
    b_same_snap = load(_with_times(S0, "2026-09-20T23:59:59+06:00"))
    b_new_snap = load(_with_times("2026-09-20T10:00:00+06:00", "2026-09-20T10:00:05+06:00"))
    assert a.content_sha256 == b_same_snap.content_sha256
    assert a.content_sha256 != b_new_snap.content_sha256


# ── 2. QO'LLASH darajasi: eskirganlik chegaralari ──────────────────────────────────────────
def _apply(db, comp, br, stock, snapshot_at, mode="CUTOVER_REFRESH"):
    b = load(bundle_dict([prod(g(1), "Tovar", stock=(stock,))], snapshot_at=snapshot_at))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    apply_migration(db, b, rep, mapping_for(rep, br.id, mode=mode))
    db.commit()
    return b


def _try_apply(db, comp, br, stock, snapshot_at, export_id="x"):
    b = load(bundle_dict([prod(g(1), "Tovar", stock=(stock,))], snapshot_at=snapshot_at,
                         export_id=export_id))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    return b, rep, mapping_for(rep, br.id)


def test_AYNI_kesim_vaqti_qayta_qollanmaydi(db):
    """Chegara: `>=`. Teng kesim ham eskirgan hisoblanadi — bir lahza ikki marta qo'llanmaydi."""
    comp, (br,) = seed_company(db)
    db.commit()
    _apply(db, comp, br, "25", S0, mode="INITIAL_CREATE")
    b, rep, m = _try_apply(db, comp, br, "40", S0, export_id="ikkinchi")
    assert rep["summary"]["stale_snapshot"] and rep["binos"]["newer_or_equal_snapshot_jobs"]
    before = _counts(db, comp)
    with pytest.raises(StaleSnapshotError):
        apply_migration(db, b, rep, m)
    db.rollback()
    assert _counts(db, comp) == before


def test_bir_MIKROSEKUND_eski_kesim_rad_etiladi(db):
    """Solishtirish satr emas, LAHZA bo'yicha — bir mikrosekund ham yetarli."""
    comp, (br,) = seed_company(db)
    db.commit()
    _apply(db, comp, br, "25", "2026-09-20T09:00:00.000001+06:00", mode="INITIAL_CREATE")
    b, rep, m = _try_apply(db, comp, br, "40", "2026-09-20T09:00:00.000000+06:00")
    assert rep["summary"]["stale_snapshot"]
    with pytest.raises(StaleSnapshotError):
        apply_migration(db, b, rep, m)
    db.rollback()


def test_bir_MIKROSEKUND_yangi_kesim_qollanadi(db):
    """Teskari chegara: darvoza qonuniy yangi eksportni TO'SMASLIGI kerak."""
    comp, (br,) = seed_company(db)
    db.commit()
    _apply(db, comp, br, "25", "2026-09-20T09:00:00.000000+06:00", mode="INITIAL_CREATE")
    b, rep, m = _try_apply(db, comp, br, "40", "2026-09-20T09:00:00.000001+06:00")
    assert not rep["summary"]["stale_snapshot"]
    apply_migration(db, b, rep, m)
    db.commit()
    assert _counts(db, comp) == 2


def test_AYNI_LAHZA_boshqa_ofsetda_ham_eskirgan(db):
    """`+06:00` va `+00:00` da yozilgan BIR XIL lahza bir xil xulosa berishi kerak —
    aks holda ofsetni almashtirib darvozani chetlab o'tish mumkin bo'lardi."""
    comp, (br,) = seed_company(db)
    db.commit()
    _apply(db, comp, br, "25", S0, mode="INITIAL_CREATE")
    b, rep, m = _try_apply(db, comp, br, "40", "2026-09-20T03:00:00+00:00", export_id="ofset")
    assert rep["summary"]["stale_snapshot"]
    with pytest.raises(StaleSnapshotError):
        apply_migration(db, b, rep, m)
    db.rollback()


# ── 3. O'zgarmagan katalog qayta chiqarilganda ─────────────────────────────────────────────
def test_ozgarmagan_katalog_AYNI_kesim_bilan_AlreadyApplied(db):
    """Mazmun xeshi `snapshot_at` ni O'Z ICHIGA OLADI, `exported_at` ni esa YO'Q.

    Shuning uchun o'sha holatni o'sha kesim bilan qayta chiqarish — boshqa fayl, boshqa eksport
    vaqti bo'lsa ham — AYNI eksport deb tanib olinadi."""
    comp, (br,) = seed_company(db)
    db.commit()
    first = _apply(db, comp, br, "25", S0, mode="INITIAL_CREATE")
    again = _with_times(S0, "2026-09-20T23:59:59+06:00")
    again["export_id"] = "qayta-chiqarildi"
    again["products"] = json.loads(json.dumps(first.data["products"]))
    b2 = load(again, indent=2)
    assert b2.file_sha256 != first.file_sha256 and b2.content_sha256 == first.content_sha256
    rep = C.classify(b2, load_snapshot(db, comp.code))
    db.rollback()
    before = _counts(db, comp)
    with pytest.raises(AlreadyApplied):
        apply_migration(db, b2, rep, mapping_for(rep, br.id))
    db.rollback()
    assert _counts(db, comp) == before


def test_ozgarmagan_katalog_YANGI_kesim_bilan_AlreadyApplied_EMAS(db):
    """Qo'shimchasi: yangi muzlatish — yangi kesim, ya'ni bu BOSHQA eksport.

    ⚠️ Shu bilan birga bu aynan egasining taqiqlagan holatining shakli: eski nusxaga yangi yorliq.
    Kod uni TUTA OLMAYDI — u faqat da'vo qilingan tartibni ko'radi. Shuning uchun nusxaning
    `source_snapshot_at` qaydi yozma tartib bilan himoyalanadi."""
    comp, (br,) = seed_company(db)
    db.commit()
    _apply(db, comp, br, "25", S0, mode="INITIAL_CREATE")
    b, rep, m = _try_apply(db, comp, br, "25", "2026-09-20T10:00:00+06:00", export_id="yangi-kesim")
    assert not rep["summary"]["stale_snapshot"]
    apply_migration(db, b, rep, m)
    db.commit()
    assert _counts(db, comp) == 2


# ── 4. Egasi so'ragan to'liq ketma-ketlik ──────────────────────────────────────────────────
def test_TOLIQ_KETMA_KETLIK_isbotlanadi(db):
    """muzlatish -> nusxa -> source_snapshot_at -> tiklash -> yig'uvchi -> bundle -> quruq yurish -> APPLY.

    Tartib bitta zanjirda tasdiqlanadi va APPLY dan keyin qo'llangan kesim aynan biz e'lon qilgan
    lahza bo'lib saqlanadi — keyingi yurish uchun yagona xotira shu."""
    from app.models.imports import ImportJob
    comp, (br,) = seed_company(db)
    db.commit()

    freeze = "2026-09-20T09:00:00+06:00"          # savdo to'xtadi, nusxa shu lahzada olindi
    generated = "2026-09-20T11:30:00+06:00"       # tiklandi, yig'uvchi ishladi, bundle yozildi
    d = bundle_dict([prod(g(1), "Tovar", stock=("25",))], snapshot_at=freeze)
    d["exported_at"] = generated
    b = load(d)

    assert B.parse_ts(b.data["snapshot_at"], "s") <= B.parse_ts(b.data["exported_at"], "e")

    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    assert not rep["summary"]["stale_snapshot"]
    apply_migration(db, b, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE"))
    db.commit()

    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    stored = B.parse_ts(job.column_mapping["snapshot_at"], "job")
    assert stored == B.parse_ts(freeze, "freeze")         # yig'uvchi ishlagan vaqt EMAS
    assert stored != B.parse_ts(generated, "generated")

    # Endi o'sha muzlatish lahzasi qayta ishlatilmaydi — zanjir yopildi.
    b2, rep2, m2 = _try_apply(db, comp, br, "40", freeze, export_id="qayta")
    assert rep2["summary"]["stale_snapshot"]
    with pytest.raises(StaleSnapshotError):
        apply_migration(db, b2, rep2, m2)
    db.rollback()
