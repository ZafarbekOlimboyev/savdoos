# -*- coding: utf-8 -*-
"""`--unit-map` XAVFSIZLIGI — o'lcham va miqyos darvozasi (ilgari ORQA ESHIK edi).

NIMA BUZUQ EDI. Egasining qarori: massa birligini dona'ga aylantirish TAQIQLANGAN va
`policies.unit_differs` doim `block`. Lekin operator jadvali shu qarorni CHETLAB O'TARDI:

    --unit-map {"кг": "dona"}

`build_unit_table` faqat kalit/qiymat bo'sh emasligini va kalitlar to'qnashmasligini tekshirardi.
Natijada BITTA jadval yozuvi IKKITA darvozani birdan ochardi, hech qanday xato bermay:
  1. mahsulot `unit_code = "dona"` bo'lardi — `UNIT_DIFFERS` UMUMAN chiqmaydi, ya'ni `block`
     siyosati ishga tushmaydi;
  2. `is_weighted` esa `unit_code == "kg"` dan kelib chiqadi, demak `False` — tarozi tovari
     donali bo'lib qolardi va POS etiketkani hech qachon o'qimasdi.
Uchinchi va eng jimi: 12.5 KG qoldiq bazaga 12.5 DONA bo'lib yozilardi (RED test bilan
bazagacha isbotlangan).

QOIDA (`normalize.check_unit_mapping`). Manba nomi BIZGA TANISH bo'lsa — maqsad haqiqiy BinOS
birlik kodi, AYNI o'lchamda va AYNI miqyosda bo'lishi SHART. Manba nomi tanish bo'lmasa — bu
`--unit-map` ning asl vazifasi (yangi nom o'rgatish), o'lcham da'vosi yo'q, tekshirilmaydi.

⚠️ MIQYOS ATAYLAB QO'LLAB-QUVVATLANMAYDI. Migrator sonni aylantirmaydi, faqat birlikni qayta
nomlaydi, shuning uchun «г» -> `kg` ham RAD etiladi: aks holda 1000 г jimgina 1000 kg bo'lardi.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest

from app.services.migrator_1c import classify as C
from app.services.migrator_1c.apply import apply_migration
from app.services.migrator_1c.catalog import load_snapshot
from app.services.migrator_1c.normalize import (BINOS_UNIT_DIMENSION, DEFAULT_UNIT_NAMES,
                                                build_unit_table, check_unit_mapping,
                                                norm_unit_key, normalize_product)
from tests.migrator_1c_helpers import (actor_of, bundle_dict, g, load, mapping_for, prod,
                                       seed_company)
from tests.migrator_1c_synth import PT_RETAIL, WH_MAIN

SELECTION = {"warehouse_guids": [WH_MAIN], "retail_price_type_guid": PT_RETAIL,
             "purchase_price_type_guid": None}


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _kg_product():
    """Tarozi tovari: 1C birligi «кг», `is_weighted` kaliti berilmagan (shartnoma bo'yicha mumkin)."""
    return prod(g(1), "Сыр кг", unit="кг", okei="166", is_weighted=None)


# ── A–C. O'LCHAMI MOS KELMAYDIGAN XARITALAR RAD ETILADI ───────────────────────────────────
@pytest.mark.parametrize("src,tgt", [
    ("кг", "dona"),          # A — massa -> sanoq
    ("килограмм", "dona"),
    ("kg", "pcs"),           # B — massa -> sanoq (lotincha taxallus; `pcs` BinOS kodi ham emas)
    ("г", "dona"),           # C — gramm -> sanoq
    ("л", "kg"),             # hajm -> massa
    ("шт", "kg"),            # sanoq -> massa (teskari yo'nalish ham xuddi shunday xavfli)
    ("метр", "kg"),          # uzunlik -> massa
])
def test_OLCHAMI_mos_kelmaydigan_xarita_RAD(src, tgt):
    with pytest.raises(ValueError) as e:
        build_unit_table({src: tgt})
    msg = str(e.value)
    assert "RAD ETILDI" in msg
    assert src in msg and tgt in msg          # manba ham, maqsad ham xatoda AYTILADI


def test_massa_donaga_RAD_xabari_MASSA_deb_ataydi():
    """xfail edi: `build_unit_table` massa birligini massa bo'lmagan kodga xaritalashni rad etmasdi."""
    with pytest.raises(ValueError, match="massa"):
        build_unit_table({"кг": "dona"})


def test_TANILGAN_manba_notanish_BinOS_kodiga_RAD():
    """xfail edi: qiymat ma'lum BinOS birlik kodi ekani tekshirilmasdi.

    «шт» allaqachon ishlaydigan nom; uni BinOS kodi bo'lmagan qiymatga burish faqat barcha
    donali tovarni karantinga tushirardi — buning qonuniy sababi yo'q."""
    with pytest.raises(ValueError, match="birlik kodi"):
        build_unit_table({"шт": "qanaqadir_yoq_birlik"})


# ── MIQYOS: bir xil o'lcham, boshqa kattalik — AYLANTIRISH SHARTNOMADA YO'Q ────────────────
@pytest.mark.parametrize("src,tgt", [("г", "kg"), ("грамм", "kg"), ("т", "kg"), ("мл", "litr")])
def test_MIQYOSI_boshqa_xarita_RAD(src, tgt):
    """1000 г -> 1 kg aylantirish YO'Q. Birlikni qayta nomlash miqdorni 1000 marta buzardi."""
    with pytest.raises(ValueError, match="MIQYOS"):
        build_unit_table({src: tgt})


# ── LOTIN YOZUVI: darvoza NOM IMLOSIGA bog'liq, shuning uchun lotincha taxalluslar ham SHART ──
# ⚠️ Bu bo'shliq adversarial ko'rikda topildi: `kilogramm` jadvalda bor edi, `gramm` esa YO'Q.
# BinOS birlik kodlarining O'ZI lotincha (dona/kg/litr/upak) va bozor o'zbek/qirg'iz, ya'ni
# lotin yozuvli 1C — kutilgan holat, chekka holat emas. `{"gramm": "kg"}` 1200 grammni
# 1200 KILOGRAMM qilib yozardi: aynan shu commit to'sishi kerak bo'lgan buzilish turi.
@pytest.mark.parametrize("src", ["gramm", "gr", "gramma", "g", "tonna", "t", "mg", "millilitr"])
def test_LOTIN_yozuvidagi_miqyos_taxalluslari_ham_RAD(src):
    tgt = "litr" if src in ("millilitr",) else "kg"
    with pytest.raises(ValueError, match="RAD ETILDI"):
        build_unit_table({src: tgt})


@pytest.mark.parametrize("src", ["gramm", "kg", "tonna", "metr", "kv.m", "m2"])
def test_LOTIN_yozuvidagi_nomlar_DONAga_ham_tushmaydi(src):
    with pytest.raises(ValueError, match="RAD ETILDI"):
        build_unit_table({src: "dona"})


def test_MIQYOS_xabari_BinOS_birligini_TOGRI_ataydi():
    """Xabar nuqsoni edi: «BinOS'da bu o'lcham uchun birlik yo'q» deb yozardi.

    Bu shoxga yetilganda o'lcham ALLAQACHON mos kelgan, ya'ni BinOS birligi BOR — har o'lchamga
    aynan bitta kod. Ya'ni eski matn bu yerda hech qachon to'g'ri emas edi va operatorni
    «birlik yo'q, qo'limdan kelmaydi» degan noto'g'ri xulosaga olib borardi."""
    with pytest.raises(ValueError) as e:
        build_unit_table({"г": "kg"})
    msg = str(e.value)
    assert "birlik yo'q" not in msg
    assert "'kg' da bering" in msg          # nima qilish kerakligi AYTILADI


# ── D–E. HAQIQIY TAXALLUSLAR QABUL QILINADI ───────────────────────────────────────────────
@pytest.mark.parametrize("src", ["кг", "килограмм", "kg", "KG", " Кг. "])
def test_D_kg_taxalluslari_QABUL(src):
    assert build_unit_table({src: "kg"})[norm_unit_key(src)] == "kg"


@pytest.mark.parametrize("src", ["шт", "штука", "штук", "pcs", "dona"])
def test_E_dona_taxalluslari_QABUL(src):
    assert build_unit_table({src: "dona"})[norm_unit_key(src)] == "dona"


def test_D_E_registr_va_probel_maqsadda_ham_kechiriladi():
    """Maqsad « KG » bo'lsa ham kanonik `kg` ga tushadi — keyin UNKNOWN_UNIT bo'lib qolmaydi."""
    assert build_unit_table({"кг": " KG "})["кг"] == "kg"


def test_kg_xaritasi_bilan_tarozi_tovari_VAZNLI_boladi():
    """Nazorat: to'g'ri xarita oqimni buzmaydi."""
    np = normalize_product(0, _kg_product(), SELECTION, build_unit_table({"кг": "kg"}))
    assert np.unit_code == "kg" and np.is_weighted is True


def test_standart_jadvalda_kg_vaznli_boladi():
    np = normalize_product(0, _kg_product(), SELECTION, build_unit_table(None))
    assert np.unit_code == "kg" and np.is_weighted is True


# ── F. NOMA'LUM BIRLIK — MAVJUD SIYOSAT: KARANTIN (rad etish EMAS) ────────────────────────
def test_F_NOTANISH_manba_notanish_maqsadga_QABUL_va_karantinga_tushadi():
    """MAVJUD HUJJATLASHGAN SIYOSAT (Review #15/#46, `test_migrator_1c_dryrun.py`): BinOS'da
    bo'lmagan kodni ko'rsatgan xarita apply'ni buzmaydi — qator `UNKNOWN_UNIT` ga tushadi va
    operator siyosati (`unknown_unit`) hal qiladi.

    Bu YO'L ATAYLAB ochiq qoldirilgan, chunki `--unit-map` ning asl vazifasi — BinOS bilmagan
    1C nomini o'rgatish. «бухта» bizga tanish emas, demak hech qanday o'lcham da'vosi yo'q va
    biz uni rad eta olmaymiz: rad etsak, xususiyatning o'zi yo'qoladi."""
    table = build_unit_table({"Бухта": "metr"})
    assert table["бухта"] == "metr"
    np = normalize_product(0, prod(g(5), "Sim", unit="бухта", okei="999"), SELECTION, table)
    assert np.unit_code == "metr"            # BinOS kodi emas -> tasnifda UNKNOWN_UNIT


def test_F_notanish_manba_HAQIQIY_kodga_ham_QABUL():
    assert build_unit_table({"бухта": "upak"})["бухта"] == "upak"


# ── G. REGISTR/PROBEL NORMALLASHTIRISH DARVOZANI CHETLAB O'TA OLMAYDI ─────────────────────
@pytest.mark.parametrize("src", ["КГ", " кг ", "Кг.", "кг .", "  КИЛОГРАММ  "])
def test_G_registr_va_probel_bilan_CHETLAB_otib_bolmaydi(src):
    with pytest.raises(ValueError, match="RAD ETILDI"):
        build_unit_table({src: "dona"})


def test_G_maqsaddagi_registr_ham_chetlab_otkazmaydi():
    with pytest.raises(ValueError, match="RAD ETILDI"):
        build_unit_table({"кг": " DONA "})


# ── SIYOSAT JADVALINING O'ZI IZCHILMI ─────────────────────────────────────────────────────
def test_STANDART_jadval_oz_qoidasidan_OTADI():
    """Agar standart jadval o'z darvozasidan o'tmasa, darvoza noto'g'ri."""
    for k, v in DEFAULT_UNIT_NAMES.items():
        check_unit_mapping(k, v)


def test_BinOS_birlik_olchamlari_SEED_bilan_MOS(db):
    """Siyosat jadvali bazadagi haqiqiy birliklar bilan sinxron turishi SHART.

    Beshinchi birlik seed qilinsa bu test yiqiladi — shunda o'lcham ongli tanlanadi, aks holda
    migrator uni jimgina rad etib yurardi."""
    from app.models.catalog import Unit
    units = db.query(Unit).all()
    seeded = {u.code for u in units}
    assert seeded == set(BINOS_UNIT_DIMENSION), (
        f"seed {sorted(seeded)} != siyosat {sorted(BINOS_UNIT_DIMENSION)}")

    # MUSTAQIL TASDIQ: `allow_fraction` bizning o'lcham bo'linishimiz bilan AYNAN mos tushadi —
    # massa/hajm kasrli, sanoq/o'ram butun (`seed.py` UNITS). Ya'ni «кг -> dona» xaritasi 12.5
    # kabi kasr qiymatni kasrga RUXSAT BERMAYDIGAN birlikka tiqardi. Bu bizning jadvalimizni
    # bazadagi boshqa, bog'liq bo'lmagan maydon bilan tekshiradi.
    kutilgan_kasr = {"mass": True, "volume": True, "count": False, "pack": False}
    for u in units:
        assert bool(u.allow_fraction) is kutilgan_kasr[BINOS_UNIT_DIMENSION[u.code]], (
            f"{u.code}: allow_fraction={u.allow_fraction}, o'lcham={BINOS_UNIT_DIMENSION[u.code]}")


# ── H + I. APPLY DA HAM AYNI TEKSHIRUV; RAD ETILGAN XARITA HECH NARSA YOZMAYDI ────────────
def _counts(db, comp):
    from app.models.catalog import Product
    from app.models.imports import ImportJob
    from app.models.inventory import Inventory, StockMovement
    pids = [p.id for p in db.query(Product).filter(Product.company_id == comp.id).all()]
    return (len(pids),
            db.query(Inventory).filter(Inventory.product_id.in_(pids)).count() if pids else 0,
            db.query(StockMovement).filter(StockMovement.product_id.in_(pids)).count() if pids else 0,
            db.query(ImportJob).filter(ImportJob.company_id == comp.id).count())


def test_I_APPLY_zaharlangan_hisobotni_RAD_va_HECH_NARSA_yozmaydi(db):
    """Darvoza faqat preview'da emas, APPLY'da ham.

    Hujum: dry-run TOZA xarita bilan o'tadi, keyin operator `report.json` dagi
    `unit_names_extra` ni QO'LDA tahrirlaydi. Apply hisobotni QAYTA tasniflaydi, ya'ni
    jadval AYNI darvozadan o'tadi."""
    comp, (br,) = seed_company(db)
    db.commit()
    before = _counts(db, comp)
    b = load(bundle_dict([prod(g(1), "Сыр", unit="кг", okei="166", stock=("12.5",))]))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    m = mapping_for(rep, br.id, mode="INITIAL_CREATE")
    rep["unit_names_extra"] = {"кг": "dona"}          # ← zaharlangan hisobot
    with pytest.raises(ValueError, match="RAD ETILDI"):
        apply_migration(db, b, rep, m, actor_id=actor_of(db, comp))
    db.rollback()
    assert _counts(db, comp) == before == (0, 0, 0, 0)   # qisman yozuv YO'Q


def test_H_REHEARSE_va_COMMIT_AYNI_tekshiruvni_qollaydi(db, tmp_path, monkeypatch, capsys):
    """`--rehearse` va `--commit` farqi apply'dan KEYIN (rollback/commit), shuning uchun
    darvoza ikkalasida ham AYNI nuqtada ishlaydi. CLI orqali isbotlanadi."""
    from app.tools import migrate_1c
    from tests.migrator_1c_synth import write
    comp, (br,) = seed_company(db)
    db.commit()
    path = str(tmp_path / "e.json")
    write(bundle_dict([prod(g(1), "Сыр", unit="кг", okei="166", stock=("12.5",))]), path)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./_pytest.db"))
    rpath, mpath = str(tmp_path / "r.json"), str(tmp_path / "m.json")
    assert migrate_1c.main(["dry-run", "--bundle", path, "--company-code", comp.code,
                            "--out", rpath]) == 0
    rep = json.loads(open(rpath, encoding="utf-8").read())
    open(mpath, "w", encoding="utf-8").write(
        json.dumps(mapping_for(rep, br.id, mode="INITIAL_CREATE")))
    rep["unit_names_extra"] = {"кг": "dona"}                       # qo'lda zaharlash
    open(rpath, "w", encoding="utf-8").write(json.dumps(rep, ensure_ascii=False))
    aid = str(actor_of(db, comp))
    db.commit()
    before = _counts(db, comp)

    args = ["apply", "--bundle", path, "--report", rpath, "--mapping", mpath,
            "--actor-employee-id", aid]
    for extra in (["--rehearse"], ["--expect-plan-sha256", "0" * 64, "--commit"]):
        capsys.readouterr()
        with pytest.raises(ValueError, match="RAD ETILDI"):
            migrate_1c.main(args + extra)
        db.rollback()
        assert _counts(db, comp) == before


def test_CLI_dry_run_XATO_xaritani_TOZA_xabar_bilan_rad_etadi(tmp_path, monkeypatch):
    """`cmd_dry_run` preflight'i ValueError'ni SystemExit'ga aylantiradi — traceback emas."""
    from app.tools import migrate_1c
    from tests.migrator_1c_synth import write
    path, upath = str(tmp_path / "e.json"), str(tmp_path / "u.json")
    write(bundle_dict([prod(g(1), "Сыр", unit="кг", okei="166")]), path)
    open(upath, "w", encoding="utf-8").write(json.dumps({"кг": "dona"}, ensure_ascii=False))
    monkeypatch.setenv("DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./_pytest.db"))
    with pytest.raises(SystemExit) as e:
        migrate_1c.main(["dry-run", "--bundle", path, "--company-code", "yoq-dokon",
                         "--unit-map", upath, "--out", str(tmp_path / "r.json")])
    assert "RAD ETILDI" in str(e.value) and "massa" in str(e.value)


# ── J. TO'G'RI XARITADA O'NLIK ANIQLIK SAQLANADI ──────────────────────────────────────────
def test_J_togri_xaritada_ONLIK_aniqlik_SAQLANADI(db):
    """Vaznli qoldiq yaxlitlanmaydi: 12.345 kg AYNAN shunday yoziladi (Numeric(14,3))."""
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    comp, (br,) = seed_company(db)
    db.commit()
    b = load(bundle_dict([prod(g(1), "Сыр", unit="кг", okei="166", stock=("12.345",))]))
    rep = C.classify(b, load_snapshot(db, comp.code), {"кг": "kg"})
    db.rollback()
    apply_migration(db, b, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE"),
                    actor_id=actor_of(db, comp))
    db.commit()
    p = db.query(Product).filter(Product.company_id == comp.id).one()
    assert db.get(Unit, p.unit_id).code == "kg" and p.is_weighted is True
    assert db.query(Inventory.qty).filter(Inventory.product_id == p.id).scalar() == Decimal("12.345")
