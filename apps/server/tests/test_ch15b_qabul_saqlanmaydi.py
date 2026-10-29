# -*- coding: utf-8 -*-
"""CH-15B FAZA A — NAKLADNOY SURATI VA XOM AI MATNI SAQLANMAYDI.

QOIDA (xulqni o'lchaydi, maydon NOMINI emas): `POST /receiving/commit` dan keyin
yangi `receivings` qatorida mijoz yuborgan xom qiymatlarning HECH BIRI qolmaydi:
  · `image_b64`  — nakladnoy surati (AI o'qishi uchun ishlatiladi, saqlanmaydi)
  · `ai_raw`     — AI ning xom javobi
  · `ai_name`    — AI ning qatorni SO'ZMA-SO'Z o'qishi (`final_items` ichida edi)
  · `unit`       — AI/mijoz yuborgan XOM birlik yorlig'i (D5-b, CH-15B Faza A.1)

⚠️  `unit` KANALI FAZA A DA O'TKAZIB YUBORILGAN — va aynan shu fayl aybdor. Yuqoridagi
    «marker» usuli e'lon qilingan, lekin markerlar FAQAT `img`/`ai_raw`/`ai_name`
    orqali yuborilgan; `unit` orqali HECH QACHON. Natijada `receiving.py` xom
    `i.unit` ni `final_items[].unit` ga yozishda davom etdi va bu testlar «toza»
    deb ko'rsatdi. Shuning uchun quyidagi bo'lim markerni AYNAN shu kanal orqali
    yuboradi (D5-b bo'limi, fayl oxirida).

USUL: har test o'z UNIKAL markerini yuboradi va qator BARCHA ustunlari bo'ylab
qidiradi. `assert "image_b64" not in body` kabi NOM bo'yicha tekshiruv refaktoringda
jim qolib o'ladi; marker esa qiymat qayerga tushsa ham topiladi.

MAJBURIY POZITIV NAZORAT: marker sweep'ning O'ZI ishlashi isbotlanadi — operator
tasdiqlagan `name` markeri qatorda TOPILISHI kerak (`test_SWEEP_ozi_ishlaydi`).
Aks holda sweep hamma narsani «toza» deb ko'rsatib, hech narsa o'lchamagan bo'lardi.

ESKI MIJOZLAR: `CommitIn.image_b64`/`ai_raw` va `CommitItem.ai_name` E'LON QILINGAN
holda QOLADI — server ularni QABUL qiladi (200) va TASHLAB YUBORADI. Shuning uchun
o'rnatilgan Flutter/Desktop mijozlari buzilmaydi va muzlatilgan DTO ro'yxati
(`test_historical_dto_freeze.py:54/:56`) o'zgarmaydi.

DOIRA: mavjud qatorlar TEGILMAYDI (legacy tozalash — alohida, ega tasdiqlaydigan
amal). `GET /receiving/{id}` javobi ham TEGILMAGAN (ega qarori kutilmoqda) — ya'ni
TARIXIY qatorlardagi `image_b64`/`ai_raw` hamon qaytadi (D5-a, alohida ruxsat kutadi).
"""
from __future__ import annotations

import json
import uuid

from tests.test_mobile_parity import _db, _product, _shop

UNIT = "dona"


def _marker(nima: str) -> str:
    """Har chaqiruvda unikal — testlar bir-birining markerini topmasin."""
    return f"CH15B-{nima}-{uuid.uuid4().hex}"


def _xom_commit(client, h, pid, *, qty=3, cost=1500, cu=None,
                img=None, ai_raw=None, ai_name=None, source="ai"):
    """Eski mijoz kabi XOM maydonlar bilan commit (server ularni tashlashi kerak)."""
    item = {"product_id": str(pid), "qty": qty, "unit_cost": cost, "unit": UNIT}
    if ai_name is not None:
        item["ai_name"] = ai_name
    tana = {"items": [item], "payment": "cash", "source": source,
            "client_uuid": str(cu or uuid.uuid4())}
    if img is not None:
        tana["image_b64"] = img
    if ai_raw is not None:
        tana["ai_raw"] = ai_raw
    return client.post("/api/v1/receiving/commit", headers=h, json=tana)


def _qator(rid):
    """`receivings` qatorining BARCHA ustunlari — matn ko'rinishida (sweep uchun)."""
    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(str(rid)))
        assert r is not None, "qabul qatori topilmadi"
        xom = {c.name: getattr(r, c.name) for c in Receiving.__table__.columns}
        return xom, json.dumps(xom, default=str, ensure_ascii=False)


def _hisob_matni(rid):
    """Qabulga bog'langan XARID va OMBOR HARAKATLARI — ular ham tekshiriladi."""
    from app.models.inventory import StockMovement
    from app.models.purchasing import Purchase
    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(str(rid)))
        chunks = []
        if r.purchase_id:
            pur = db.get(Purchase, r.purchase_id)
            chunks.append(json.dumps({c.name: getattr(pur, c.name)
                                      for c in Purchase.__table__.columns},
                                     default=str, ensure_ascii=False))
            for m in db.query(StockMovement).filter(StockMovement.ref_id == r.purchase_id).all():
                chunks.append(json.dumps({c.name: getattr(m, c.name)
                                          for c in StockMovement.__table__.columns},
                                         default=str, ensure_ascii=False))
        return "\n".join(chunks)


# ══ QOIDA — uchta xom qiymat ham SAQLANMAYDI ════════════════════════════════

def test_SURAT_AI_XOM_va_AI_NOMI_QATORDA_YOQ(client):
    d = _shop()
    p = _product(d, name="CH15B mahsulot", qty=0)
    m_img, m_ai, m_name = _marker("IMG"), _marker("AIRAW"), _marker("AINAME")

    r = _xom_commit(client, d["H"], p["id"], img=m_img,
                    ai_raw=[{"name": m_ai, "qty": 3}], ai_name=m_name)
    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]

    xom, matn = _qator(rid)
    for nom, m in (("image_b64", m_img), ("ai_raw", m_ai), ("ai_name", m_name)):
        assert m not in matn, f"{nom} markeri QATORDA QOLDI: {matn[:400]}"
    # Ustun darajasida ham aniq:
    assert xom["image_b64"] is None, f"image_b64 = {xom['image_b64']!r}"
    assert xom["ai_raw"] == [], f"ai_raw = {xom['ai_raw']!r}"
    assert all("ai_name" not in it for it in xom["final_items"]), xom["final_items"]

    # Bog'langan xarid va ombor harakatlarida ham yo'q:
    hm = _hisob_matni(rid)
    for m in (m_img, m_ai, m_name):
        assert m not in hm, f"marker XARID/HARAKATda qoldi: {hm[:400]}"


def test_SWEEP_ozi_ishlaydi_POZITIV_NAZORAT(client):
    """Marker sweep haqiqatan qidiradimi: operator TASDIQLAGAN nom qatorda BO'LISHI kerak.
    Bu test yiqilsa — yuqoridagi «toza» natijalar hech narsa o'lchamagan bo'ladi."""
    d = _shop()
    nom = _marker("TASDIQLANGAN-NOM")
    p = _product(d, name=nom, qty=0)
    r = _xom_commit(client, d["H"], p["id"])
    assert r.status_code == 200, r.text
    _, matn = _qator(r.json()["receiving_id"])
    assert nom in matn, f"sweep tasdiqlangan nomni TOPMADI — sweep buzuq: {matn[:400]}"


# ══ TASDIQLANGAN BIZNES YOZUVI TO'G'RI QOLADI ═══════════════════════════════

def test_TASDIQLANGAN_maydonlar_va_HISOB_TOGRI(client):
    d = _shop()
    nom = _marker("NOM")
    p = _product(d, name=nom, qty=0)
    r = _xom_commit(client, d["H"], p["id"], qty=4, cost=2500,
                    img=_marker("IMG"), ai_raw=[{"name": _marker("AIRAW")}],
                    ai_name=_marker("AINAME"))
    assert r.status_code == 200, r.text
    xom, _ = _qator(r.json()["receiving_id"])

    assert len(xom["final_items"]) == 1, xom["final_items"]
    it = xom["final_items"][0]
    assert set(it) == {"product_id", "name", "qty", "unit_cost", "unit"}, it
    assert it["product_id"] == str(p["id"])
    assert it["name"] == nom, "tasdiqlangan katalog nomi saqlanishi kerak"
    assert float(it["qty"]) == 4.0 and float(it["unit_cost"]) == 2500.0
    assert it["unit"] == UNIT
    assert xom["total_types"] == 1 and float(xom["total_qty"]) == 4.0

    # Ombor qoldig'i va IMMUTABLE fakt-ledger
    from app.models.inventory import Inventory, StockMovement
    with _db() as db:
        inv = db.query(Inventory).filter(Inventory.product_id == p["id"]).first()
        assert float(inv.qty) == 4.0, float(inv.qty)
        mv = db.query(StockMovement).filter(StockMovement.product_id == p["id"]).all()
        assert len(mv) >= 1, "StockMovement yozilmadi"
        assert any(float(m.qty) == 4.0 and float(m.unit_cost) == 2500.0 for m in mv), \
            [(float(m.qty), float(m.unit_cost)) for m in mv]


# ══ ESKI MIJOZLAR BUZILMAYDI ════════════════════════════════════════════════

def test_ESKI_MIJOZ_xom_maydonlar_bilan_200_oladi(client):
    """Maydonlar E'LON QILINGAN holda qolgani uchun 422 EMAS, 200 kelishi kerak."""
    d = _shop()
    p = _product(d, name="CH15B eski mijoz", qty=0)
    r = _xom_commit(client, d["H"], p["id"], img="QUJD",
                    ai_raw=[{"name": "x", "qty": 1}], ai_name="AI matni")
    assert r.status_code == 200, f"eski mijoz buzildi: {r.status_code} {r.text[:300]}"


# ══ IDEMPOTENTLIK ═══════════════════════════════════════════════════════════

def test_IDEMPOTENT_ikki_marta_bitta_qator_va_TOZA(client):
    d = _shop()
    p = _product(d, name="CH15B idempotent", qty=0)
    cu, m_img = uuid.uuid4(), _marker("IMG")

    r1 = _xom_commit(client, d["H"], p["id"], cu=cu, img=m_img, ai_name=_marker("AINAME"))
    assert r1.status_code == 200, r1.text
    r2 = _xom_commit(client, d["H"], p["id"], cu=cu, img=m_img, ai_name=_marker("AINAME"))
    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is True, r2.text
    assert r1.json()["receiving_id"] == r2.json()["receiving_id"], (r1.text, r2.text)

    from app.models.receiving import Receiving
    with _db() as db:
        assert db.query(Receiving).filter(Receiving.client_uuid == cu).count() == 1
    _, matn = _qator(r1.json()["receiving_id"])
    assert m_img not in matn, matn[:300]


# ══ TENANT IZOLYATSIYASI ════════════════════════════════════════════════════

def test_TENANT_izolyatsiyasi_va_ikki_dokonda_ham_TOZA(client):
    A, B = _shop(), _shop()
    pa, pb = _product(A, name="CH15B A", qty=0), _product(B, name="CH15B B", qty=0)
    ma, mb = _marker("IMG-A"), _marker("IMG-B")

    ra = _xom_commit(client, A["H"], pa["id"], img=ma, ai_name=_marker("AINAME-A"))
    rb = _xom_commit(client, B["H"], pb["id"], img=mb, ai_name=_marker("AINAME-B"))
    assert ra.status_code == 200 and rb.status_code == 200, (ra.text, rb.text)

    xa, ta = _qator(ra.json()["receiving_id"])
    xb, tb = _qator(rb.json()["receiving_id"])
    assert ma not in ta and mb not in tb, "o'z markeri qoldi"
    assert mb not in ta and ma not in tb, "BEGONA tenant markeri qatorda!"
    assert str(xa["company_id"]) == str(A["cid"]) and str(xb["company_id"]) == str(B["cid"])
    assert xa["image_b64"] is None and xb["image_b64"] is None
    assert xa["ai_raw"] == [] and xb["ai_raw"] == []


# ══ QO'LDA KIRIM (AI'siz yo'l) O'ZGARMAGAN ══════════════════════════════════

def test_QOLDA_KIRIM_ishlaydi_va_TOZA(client):
    d = _shop()
    nom = _marker("QOLDA")
    p = _product(d, name=nom, qty=0)
    r = _xom_commit(client, d["H"], p["id"], qty=2, cost=700, source="manual")
    assert r.status_code == 200, r.text
    xom, matn = _qator(r.json()["receiving_id"])
    assert xom["source"] == "manual", xom["source"]
    assert xom["image_b64"] is None and xom["ai_raw"] == []
    assert nom in matn, "qo'lda kirimda ham tasdiqlangan nom saqlanishi kerak"
    assert float(xom["total_qty"]) == 2.0


# ══ HISTORICAL EXECUTOR MUVOFIQLIGI ═════════════════════════════════════════

def test_HISTORICAL_executor_AYNI__commit_once_ni_ishlatadi(client):
    """`historical_exec` xom maydonlarni RAD etadi va AYNI `_commit_once` ni chaqiradi —
    ya'ni bizning o'zgarish u yerda ham izchil. Import va SERVER_OWNED tarkibi qadaladi."""
    from app.api.v1 import historical_exec as HX
    from app.api.v1.receiving import _commit_once
    assert HX._commit_once is _commit_once, "historical boshqa funksiyani ishlatadi"
    for maydon in ("image_b64", "ai_raw"):
        assert maydon in HX.SERVER_OWNED, (maydon, HX.SERVER_OWNED)


# ══════════════════════════════════════════════════════════════════════════════
#  D5-b — XOM BIRLIK YORLIG'I (`final_items[].unit`)                CH-15B A.1
# ══════════════════════════════════════════════════════════════════════════════
#
#  INVARIANT (bitta jumla): saqlangan `final_items[].unit` HAR DOIM mahsulotning
#  o'z birligi — `Product.unit_id -> Unit.code` — va hech qachon mijoz yuborgan satr.
#
#  NEGA BU TO'G'RI MANBA. `products.unit_id` — NOT NULL (`db/schema.sql:212`), ya'ni
#  har mahsulotning birligi BOR. Qabul qatori esa mahsulotga tegishli: uning birligi
#  katalogdan keladi, nakladnoyni o'qigan AI dan emas. Shu bois MAVJUD mahsulot uchun
#  mijozning `unit` yorlig'i KERAK EMAS, YANGI mahsulot uchun esa u allaqachon
#  `unit_id` ga YECHILADI (`receiving.py:375`) — ikki holatda ham javob `unit_id` da.
#
#  ⚠️  BU MODULNING O'Z QOIDASI, YANGI QOIDA EMAS. `services/unit_gate.py:110-118`
#      ilgari MAVJUD bo'lgan `code_fraction_map` ni ATAYLAB OLIB TASHLAGAN: u
#      `unit.code` ni KLIENT yuborgan satr bo'yicha yechardi va ikki fail-open
#      teshigi ochardi (katta-kichik harf, noma'lum kod). O'sha modulning xulosasi
#      — «Mijozga ishonilmaydi». `receiving.py:472` ham AYNI shunday qiladi:
#      javobdagi `results[].unit` ALLAQACHON yechilgan `_uc`. Faqat `:485`
#      (`final_items`) xom satrni afzal ko'rardi.
#
#  O'LCHANGAN HOLAT (tuzatishdan oldin, 8 ta holatda, manfiy nazorat):
#      MAVJUD dona + xom marker  -> marker SAQLANDI
#      MAVJUD kg   + xom marker  -> marker SAQLANDI
#      MAVJUD kg   + "dona"      -> "dona" SAQLANDI   <- kg qatori «dona» deb yozildi
#      MAVJUD dona + "KG"        -> "KG" SAQLANDI
#      MAVJUD dona + "ящик"      -> "ящик" SAQLANDI
#      YANGI  + "KG"/"ящик"/marker -> hujjat mahsulotning o'z birligiga ZID
#      (null va "" allaqachon kanonik edi — `i.unit or _uc` zaxiraga tushardi)
#  Hech bir holat 4xx bermagan, ya'ni muammo jim edi.

import pytest

# AI chiqishi va eski mijozlar REAL yuborishi mumkin bo'lgan qiymatlar.
# `receiving_ai.py:17` prompt FAQAT "dona|kg|litr" so'raydi, `:156` javobni
# TEKSHIRMAYDI; `Purchases.tsx:1190` esa `unit` ni MAVJUD mahsulot uchun ham
# SHARTSIZ yuboradi (mobil `receiving_api.dart:929` to'g'ri qiladi).
XOM_BIRLIKLAR = [
    ("DONA", "KATTA HARF — kod topilmaydi, xom satr saqlanardi"),
    ("Dona", "aralash harf — AYNI mexanizm"),
    ("ящик", "NOMA'LUM kod (AI ruscha yozdi)"),
    ("шт", "1C/ruscha qisqartma"),
    ("kg ", "orqa bo'shliq — normalizatsiyasiz boshqa satr"),
    ("<script>x</script>", "HTML/JS — JSONB ichida muddatsiz qolardi"),
]


def _birlik_kodi(pid) -> str:
    """Mahsulotning HAQIQIY birligi: `Product.unit_id -> Unit.code`. YAGONA to'g'ri manba."""
    from app.models.catalog import Product, Unit
    with _db() as db:
        p = db.get(Product, uuid.UUID(str(pid)))
        assert p is not None, "mahsulot topilmadi"
        u = db.get(Unit, p.unit_id)
        assert u is not None, "mahsulot birligi yechilmadi"
        return u.code


def _saqlangan_birliklar(rid) -> list:
    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(str(rid)))
        assert r is not None, "qabul qatori topilmadi"
        return [(it.get("product_id"), it.get("unit")) for it in (r.final_items or [])]


def _invariant(rid):
    """HAR qator uchun: saqlangan birlik == mahsulotning katalogdagi birligi."""
    buzilgan = [(pid, saqlangan, _birlik_kodi(pid))
                for pid, saqlangan in _saqlangan_birliklar(rid)
                if saqlangan != _birlik_kodi(pid)]
    assert not buzilgan, (
        "saqlangan birlik mahsulot birligiga MOS KELMAYDI "
        f"(product_id, saqlangan, katalog): {buzilgan!r}")


def _commit_birlik(client, h, *, pid=None, new_name=None, unit="__YOQ__",
                   qty=2, cost=100, cu=None, source="ai"):
    """Birlikni ANIQ boshqaradigan commit. `unit="__YOQ__"` -> kalit YUBORILMAYDI."""
    it = {"qty": qty, "unit_cost": cost}
    if pid is not None:
        it["product_id"] = str(pid)
    if new_name is not None:
        it["new_name"], it["new_sell_price"] = new_name, cost * 2
    if unit != "__YOQ__":
        it["unit"] = unit
    return client.post("/api/v1/receiving/commit", headers=h, json={
        "items": [it], "payment": "cash", "source": source,
        "client_uuid": str(cu or uuid.uuid4())})


# ── 1. XOM AI BIRLIGI SAQLANMAYDI ───────────────────────────────────────────

def test_XOM_AI_BIRLIGI_marker_QATORDA_YOQ(client):
    """Marker AYNAN `unit` kanali orqali yuboriladi — Faza A sweep'i qoldirgan teshik."""
    d = _shop()
    p = _product(d, name="Birlik sinovi", qty=0)
    m = _marker("XOM-UNIT")

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=m)

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    _, matn = _qator(rid)
    assert m not in matn, f"XOM birlik qatorda SAQLANDI: {matn[:400]!r}"
    assert m not in _hisob_matni(rid), "XOM birlik xarid/harakatlarga tushdi"
    _invariant(rid)


@pytest.mark.parametrize("xom, nima", XOM_BIRLIKLAR)
def test_MAVJUD_mahsulot_YAROQSIZ_birlik_bilan_KANONIK_saqlanadi(client, xom, nima):
    """Har bir realistik yaroqsiz qiymat uchun: 200 QAYTADI va KATALOG birligi saqlanadi."""
    d = _shop()
    p = _product(d, name="Dona mahsulot", qty=0)

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=xom)

    assert r.status_code == 200, f"{nima}: {r.status_code} {r.text[:200]}"
    rid = r.json()["receiving_id"]
    assert [u for _, u in _saqlangan_birliklar(rid)] == ["dona"], \
        f"{nima}: saqlangan birlik {_saqlangan_birliklar(rid)!r}"
    _invariant(rid)


# ── 2. POZITIV NAZORAT — bu bo'lim HAQIQATAN o'lchayotganini isbotlaydi ─────

def test_BIRLIK_SWEEP_ozi_ishlaydi_POZITIV_NAZORAT(client):
    """⚠️  MAJBURIY. Yuqoridagi testlar «marker yo'q» deyishi faqat sweep QIYMATNI
    ko'ra olsa ma'noli. Bu yerda birlik `kg` — u qatorda TOPILISHI SHART.
    Agar bu test yiqilsa, qolgan hammasi hech narsa o'lchamagan."""
    d = _shop()
    p = _product(d, name="Kg mahsulot", qty=0, weighted=True)   # unit_id -> kg

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=_marker("XOM-UNIT"))

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    _, matn = _qator(rid)
    assert '"unit": "kg"' in matn or "'unit': 'kg'" in matn, \
        f"POZITIV NAZORAT YIQILDI — sweep saqlangan birlikni KO'RMAYDI: {matn[:400]!r}"
    assert [u for _, u in _saqlangan_birliklar(rid)] == ["kg"]


# ── 3. QONUNIY BIRLIK `dona` GA TUSHIRILMAYDI (ega talabi) ──────────────────

@pytest.mark.parametrize("kod, weighted", [("kg", True), ("dona", False)])
def test_QONUNIY_birlik_DONA_ga_TUSHIRILMAYDI(client, kod, weighted):
    """Ega talabi: «Do not silently replace legitimate supported custom units with dona».
    Mijoz BOSHQA birlik aytsa ham, mahsulotning O'Z birligi saqlanadi."""
    d = _shop()
    p = _product(d, name=f"{kod} mahsulot", qty=0, weighted=weighted)
    assert _birlik_kodi(p["id"]) == kod, "sinov sharti: mahsulot birligi kutilganidek"

    # Mijoz ATAYLAB boshqa birlik aytadi — qarama-qarshi tomondan ham tekshiramiz.
    r = _commit_birlik(client, d["H"], pid=p["id"], unit=("dona" if kod == "kg" else "kg"))

    assert r.status_code == 200, r.text
    assert [u for _, u in _saqlangan_birliklar(r.json()["receiving_id"])] == [kod], \
        f"mahsulot birligi {kod} edi — hujjat boshqa qiymat yozdi"


@pytest.mark.parametrize("kod", ["kg", "litr", "upak"])
def test_YANGI_mahsulot_QOLLANADIGAN_birlik_SAQLANADI(client, kod):
    """YANGI mahsulot yo'li: qo'llanadigan birlik (`units` jadvalidagi qator) buzilmaydi —
    mahsulot ham, hujjat ham AYNI birlikni oladi."""
    d = _shop()
    nom = "Yangi " + uuid.uuid4().hex[:8]

    r = _commit_birlik(client, d["H"], new_name=nom, unit=kod, qty=2)

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    assert [u for _, u in _saqlangan_birliklar(rid)] == [kod], _saqlangan_birliklar(rid)
    _invariant(rid)   # mahsulotning `unit_id` si bilan ham MOS


@pytest.mark.parametrize("xom", ["KG", "Litr"])
def test_YANGI_mahsulot_birlik_HARFI_normallashadi_hujjatda_ham(client, xom):
    """`receiving.py:375` `.lower()` bilan yechadi — mahsulot `kg`/`litr` bo'ladi.
    Hujjat ham AYNI kanonik kodni yozishi kerak, mijozning `KG` satrini emas."""
    d = _shop()
    r = _commit_birlik(client, d["H"], new_name="Yangi " + uuid.uuid4().hex[:8], unit=xom)

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    assert [u for _, u in _saqlangan_birliklar(rid)] == [xom.lower()]
    _invariant(rid)


def test_DEDUP_mavjud_nomga_tushganda_ham_KANONIK(client):
    """⚠️  UCHINCHI YO'L — `new_name` berilgan, lekin AYNI nomli mahsulot ALLAQACHON bor:
    `receiving.py:360-368` yangisini yaratmaydi, mavjudiga kirim qiladi (`prod = existing`).
    Bu shoxda mijozning `unit` yorlig'i mahsulotga UMUMAN ta'sir qilmaydi — ya'ni xom
    satrni saqlash ayni shu yerda eng yolg'on bo'lardi. Hujjat mavjud mahsulotning
    birligini (`kg`) yozishi SHART."""
    d = _shop()
    nom = "Dedup " + uuid.uuid4().hex[:8]
    p = _product(d, name=nom, qty=0, weighted=True)        # MAVJUD, birligi kg

    r = _commit_birlik(client, d["H"], new_name=nom, unit="litr")   # mijoz "litr" deydi

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    qatorlar = _saqlangan_birliklar(rid)
    assert [pid for pid, _ in qatorlar] == [str(p["id"])], \
        f"dedup ishlamadi — yangi mahsulot yaratildi: {qatorlar!r}"
    assert [u for _, u in qatorlar] == ["kg"], f"dedup shoxida xom birlik saqlandi: {qatorlar!r}"
    _invariant(rid)


def test_YANGI_mahsulot_NOMALUM_birlik_hujjat_mahsulot_bilan_MOS(client):
    """Noma'lum kod (`units` da YO'Q) — mahsulot zaxira birlik bilan yaratiladi
    (mavjud xulq, O'ZGARMAGAN). Muhimi: HUJJAT xom satrni emas, mahsulotning
    HAQIQIY birligini yozadi — ya'ni ikkisi ZIDDIYATDA qolmaydi."""
    d = _shop()
    r = _commit_birlik(client, d["H"], new_name="Yangi " + uuid.uuid4().hex[:8], unit="ящик")

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    _, matn = _qator(rid)
    assert "ящик" not in matn, f"noma'lum XOM kod saqlandi: {matn[:300]!r}"
    _invariant(rid)


# ── 4. ESKI MIJOZ MOSLIGI — 422 YO'Q ────────────────────────────────────────

@pytest.mark.parametrize("uzunlik", [11, 64, 500, 5000])
def test_ESKI_MIJOZ_UZUN_birlik_qiymati_200_OLADI(client, uzunlik):
    """⚠️  `CommitItem.unit` ga `max_length` QO'YILMADI (ega qarori): o'rnatilgan
    mijozlar uzun qiymat yuborsa, normalizatsiyadan OLDIN 422 olishlari mumkin edi.
    Shuning uchun uzunlik CHEKLANMAYDI — qiymat shunchaki SAQLANMAYDI."""
    d = _shop()
    p = _product(d, name="Dona mahsulot", qty=0)
    uzun = "ящик-" + "x" * (uzunlik - 5)

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=uzun)

    assert r.status_code == 200, f"uzun birlik 4xx berdi ({uzunlik}): {r.text[:200]}"
    rid = r.json()["receiving_id"]
    _, matn = _qator(rid)
    assert uzun not in matn, "uzun XOM qiymat saqlandi"
    assert [u for _, u in _saqlangan_birliklar(rid)] == ["dona"]


@pytest.mark.parametrize("qiymat", [None, "", "   "])
def test_ESKI_MIJOZ_birlik_BERMASA_ham_KANONIK(client, qiymat):
    """`unit` kalitsiz (mobil `receiving_api.dart:929` mavjud mahsulot uchun `null` yuboradi),
    bo'sh satr va faqat bo'shliq — hammasi mahsulotning birligini beradi."""
    d = _shop()
    p = _product(d, name="Kg mahsulot", qty=0, weighted=True)

    r = (_commit_birlik(client, d["H"], pid=p["id"])
         if qiymat is None else
         _commit_birlik(client, d["H"], pid=p["id"], unit=qiymat))

    assert r.status_code == 200, r.text
    assert [u for _, u in _saqlangan_birliklar(r.json()["receiving_id"])] == ["kg"]


def test_MUZLATILGAN_DTO_unit_maydoni_JOYIDA(client):
    """Tuzatish DTO ni O'ZGARTIRMAYDI: `unit` e'lon qilingan holda qoladi, ya'ni
    `test_historical_dto_freeze.py:56` muzlatilgan ro'yxati buzilmaydi."""
    from app.api.v1.receiving import CommitItem
    assert "unit" in CommitItem.model_fields, sorted(CommitItem.model_fields)
    # Cheklov QO'SHILMAGANINI qadaymiz — aks holda eski mijoz 422 olardi.
    mf = CommitItem.model_fields["unit"]
    uzunlik_cheklovi = [m for m in getattr(mf, "metadata", []) or []
                        if type(m).__name__ in ("MaxLen", "MinLen")]
    assert not uzunlik_cheklovi, f"`unit` ga uzunlik cheklovi qo'shilgan: {uzunlik_cheklovi!r}"


# ── 5. QO'LDA KIRIM / IDEMPOTENTLIK / TENANT ────────────────────────────────

def test_QOLDA_KIRIM_birligi_ham_KANONIK(client):
    """AI'siz yo'l (`source="manual"`) ham AYNI `_commit_once` — birlik shu yerda ham kanonik."""
    d = _shop()
    p = _product(d, name="Kg mahsulot", qty=0, weighted=True)
    m = _marker("XOM-UNIT-QOLDA")

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=m, source="manual")

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    xom, matn = _qator(rid)
    assert xom["source"] == "manual", xom["source"]
    assert m not in matn
    assert [u for _, u in _saqlangan_birliklar(rid)] == ["kg"]


def test_IDEMPOTENT_takror_ham_BITTA_qator_va_KANONIK(client):
    """AYNI `client_uuid` bilan ikki marta: bitta qabul, birlik kanonik, marker YO'Q."""
    d = _shop()
    p = _product(d, name="Dona mahsulot", qty=0)
    cu, m = uuid.uuid4(), _marker("XOM-UNIT-TAKROR")

    r1 = _commit_birlik(client, d["H"], pid=p["id"], unit=m, cu=cu)
    r2 = _commit_birlik(client, d["H"], pid=p["id"], unit=m, cu=cu)

    assert r1.status_code == 200 and r2.status_code == 200, (r1.text[:200], r2.text[:200])
    assert r1.json()["receiving_id"] == r2.json()["receiving_id"], "takror YANGI qabul yaratdi"
    rid = r1.json()["receiving_id"]
    _, matn = _qator(rid)
    assert m not in matn, "takrorda XOM birlik saqlandi"
    assert [u for _, u in _saqlangan_birliklar(rid)] == ["dona"]
    # Qoldiq BIR MARTA oshgan (takror hisobni ikkilantirmagan).
    from app.models.inventory import Inventory
    with _db() as db:
        inv = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(str(p["id"]))).first()
        assert float(inv.qty) == 2.0, f"takror qoldiqni ikkilantirdi: {inv.qty}"


def test_TENANT_izolyatsiyasi_birlik_ikki_dokonda_ham_KANONIK(client):
    """Ikki mustaqil do'kon: har biri O'Z mahsulotining birligini oladi, markerlar YO'Q."""
    A, B = _shop(), _shop()
    pa = _product(A, name="A dona", qty=0)
    pb = _product(B, name="B kg", qty=0, weighted=True)
    ma, mb = _marker("XOM-UNIT-A"), _marker("XOM-UNIT-B")

    ra = _commit_birlik(client, A["H"], pid=pa["id"], unit=ma)
    rb = _commit_birlik(client, B["H"], pid=pb["id"], unit=mb)

    assert ra.status_code == 200 and rb.status_code == 200
    rida, ridb = ra.json()["receiving_id"], rb.json()["receiving_id"]
    _, mata = _qator(rida)
    _, matb = _qator(ridb)
    for m in (ma, mb):
        assert m not in mata and m not in matb, "marker do'konlar orasida oqdi"
    assert [u for _, u in _saqlangan_birliklar(rida)] == ["dona"]
    assert [u for _, u in _saqlangan_birliklar(ridb)] == ["kg"]
    # Begona do'kon hujjatni O'QIY OLMAYDI (mavjud izolyatsiya — regressiya nazorati).
    assert client.get(f"/api/v1/receiving/{ridb}", headers=A["H"]).status_code == 404


# ── 6. HISOB-KITOB VA TASDIQLANGAN MAYDONLAR O'ZGARMAYDI ────────────────────

def test_TASDIQLANGAN_maydonlar_va_HISOB_birlik_tuzatishidan_KEYIN_ham_TOGRI(client):
    """Tuzatish FAQAT `unit` qiymatiga tegadi: nom, miqdor, tannarx, qoldiq va
    ombor harakati AYNAN o'z joyida qoladi (hisob regressiyasi YO'Q)."""
    d = _shop()
    nom = _marker("TASDIQLANGAN-NOM")
    p = _product(d, name=nom, qty=5)

    r = _commit_birlik(client, d["H"], pid=p["id"], unit=_marker("XOM-UNIT"),
                       qty=3, cost=1500)

    assert r.status_code == 200, r.text
    rid = r.json()["receiving_id"]
    xom, matn = _qator(rid)
    # Operator tasdiqlagan maydonlar — JOYIDA.
    assert nom in matn, "tasdiqlangan NOM saqlanmadi"
    assert float(xom["total_qty"]) == 3.0, xom["total_qty"]
    assert xom["total_types"] == 1, xom["total_types"]
    qatorlar = (xom["final_items"] if isinstance(xom["final_items"], list)
                else json.loads(xom["final_items"]))
    assert len(qatorlar) == 1
    assert qatorlar[0]["name"] == nom
    assert float(qatorlar[0]["qty"]) == 3.0
    assert float(qatorlar[0]["unit_cost"]) == 1500.0
    assert qatorlar[0]["unit"] == "dona"
    # Hisob-kitob: qoldiq 5 -> 8, harakat qatori AYNI miqdor va tannarx bilan.
    from app.models.inventory import Inventory, StockMovement
    with _db() as db:
        inv = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(str(p["id"]))).first()
        assert float(inv.qty) == 8.0, f"qoldiq noto'g'ri: {inv.qty}"
        mvs = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(str(p["id"]))).all()
        kirim = [m for m in mvs if float(m.qty) == 3.0]
        assert len(kirim) == 1, f"kirim harakati bitta bo'lishi kerak: {len(kirim)}"
        assert float(kirim[0].unit_cost) == 1500.0, kirim[0].unit_cost
        assert float(kirim[0].balance_after) == 8.0, kirim[0].balance_after
