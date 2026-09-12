# -*- coding: utf-8 -*-
"""PHASE 1 — QABUL -> PARTIYA -> QOLDIQ -> AUDIT -> IDEMPOTENTLIK.

Har darvoza uchun MANFIY nazorat ham bor: darvoza olib tashlansa test QIZIL
bo'lishi shart. Aks holda test darvozani emas, o'z kutilmasini isbotlardi.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.catalog import Product, Unit
from app.models.inventory import Inventory, StockBatch
from app.services import lot_policy as LP
from app.services import lot_receiving as LR
from app.services import stock_invariant as SI

NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=90)).date()
YESTERDAY = (NOW - timedelta(days=1)).date()


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture()
def ctx(client):
    """(company_id, branch_id) — AYNAN xodim yozadigan filial.

    ⚠️  `Branch...first()` ISHLATILMAYDI: u ORDER BY siz nodeterministik va
        to'plamdagi boshqa fayl ikkinchi filial yaratsa (test_lot_receiving.py
        aynan shunday qiladi) bu fixture SOTUV YOZMAYDIGAN filialni qaytarardi —
        natijada sinovlar mahsulotni emas, fayllar tartibini o'lchardi.
        `actor_branch()` — API ning O'ZI ishlatadigan yechim.
    """
    from app.core.deps import actor_branch
    from app.models.auth import Employee
    from app.models.org import Company
    with _db() as db:
        c = db.query(Company).first()
        emp = (db.query(Employee)
               .filter(Employee.company_id == c.id, Employee.deleted_at.is_(None))
               .order_by(Employee.created_at).first())
        b = actor_branch(emp, db)
        yield c.id, b.id


def _new_product(client, admin_headers, name=None):
    """Toza mahsulot — API orqali (haqiqiy yo'l)."""
    nm = name or f"Partiya sinov {uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/products/bulk", headers=admin_headers, json={
        "items": [{"name": nm, "sell_price": 1000, "buy_price": 700,
                   "unit_code": "dona", "stock": 0}]})
    assert r.status_code in (200, 201), r.text
    return r.json()[0]["id"]


def _enable(client, admin_headers, pid, **kw):
    body = {"product_id": pid, "reason": "sinov: partiya kuzatuvi", **kw}
    return client.post("/api/v1/lots/enable", headers=admin_headers, json=body)


def _commit(client, admin_headers, items, cu=None):
    return client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": items, "supplier_id": None, "payment": "cash",
        "client_uuid": str(cu or uuid.uuid4()), "source": "manual"})


def _inv_qty(pid, bid):
    with _db() as db:
        r = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(str(pid)),
                                       Inventory.branch_id == bid).first()
        return Decimal(str(r.qty)) if r else Decimal("0")


def _lots(pid):
    with _db() as db:
        return db.query(StockBatch).filter(
            StockBatch.product_id == uuid.UUID(str(pid))).all()


# == 1. QABUL PARTIYA TUG'DIRADI VA QOLDIQNI OSHIRADI ========================

def test_QABUL_partiya_tugdiradi_va_qoldiq_oshadi(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200

    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 30, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 10, "batch_number": "A-1"},
                                                  {"qty": 20, "batch_number": "A-2"}]}])
    assert r.status_code == 200, r.text
    lots = _lots(pid)
    assert len(lots) == 2, [str(b.id) for b in lots]
    assert sum(Decimal(str(b.remaining_qty)) for b in lots) == Decimal("30.000")
    assert _inv_qty(pid, bid) == Decimal("30.000")
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_bir_qatorda_KOP_partiya_agregat_harakat_bitta(client, admin_headers, ctx):
    """`ux_stockmov_client_prod_type` bitta (mahsulot, tur) ga BITTA harakat beradi."""
    from app.models.inventory import StockMovement
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 7, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 3}, {"qty": 4}]}])
    assert r.status_code == 200, r.text
    with _db() as db:
        mv = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(pid)).all()
        assert len(mv) == 1, f"{len(mv)} ta harakat — agregat buzilgan"
        assert Decimal(str(mv[0].qty)) == Decimal("7.000")
        # ⚠️  ESKIRGAN `batch_id` HECH QACHON yozilmaydi — ko'p partiyali qatorda
        #     bitta id yolg'on bo'lardi, bitta partiyalida esa yarim to'ldirilgan
        #     havola «NULL = partiyasi yo'q» degan yolg'on o'qish tug'dirardi.
        assert mv[0].batch_id is None


def test_BITTA_partiyali_qatorda_ham_batch_id_YOZILMAYDI(client, admin_headers, ctx):
    """Kanonik yo'nalish BITTA: partiya -> hujjat (`receiving_id`/`purchase_item_id`).

    ⚠️  Bu test ilgari TESKARISINI talab qilardi (`batch_id is not None`) va
        XATO edi: `StockMovement.batch_id` ni hech kim o'qimaydi, u faqat bitta
        partiyali qatorda to'lardi va shu bilan uchinchi, ishonchsiz qirra
        yaratardi. Harakat -> partiya bog'lanishi Phase 2 da
        `sale_item_lot_allocations` orqali ANIQ modellanadi.
    """
    from app.models.inventory import StockBatch, StockMovement
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 5}]}])
    with _db() as db:
        mv = db.query(StockMovement).filter(
            StockMovement.product_id == uuid.UUID(pid)).first()
        assert mv.batch_id is None
        # Bog'lanish partiya TOMONIDA va u TO'LIQ.
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        assert b.receiving_id is not None, "partiya qabul hujjatiga bog'lanmagan"


# == 2. IDEMPOTENTLIK =======================================================

def test_AYNI_client_uuid_ikki_marta_BIR_MARTA_qoldiq(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    cu = uuid.uuid4()
    body = [{"product_id": pid, "qty": 12, "unit_cost": 700, "unit": "dona",
             "lots": [{"qty": 12, "batch_number": "IDEM"}]}]
    r1 = _commit(client, admin_headers, body, cu=cu)
    r2 = _commit(client, admin_headers, body, cu=cu)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json().get("duplicate") is True, r2.text
    assert len(_lots(pid)) == 1, "takror qabul YANGI partiya tug'dirdi"
    assert _inv_qty(pid, bid) == Decimal("12.000")


def test_partiya_kaliti_DETERMINISTIK():
    """Kalit tasodifiy bo'lsa retry ikkinchi partiya tug'dirardi."""
    cid = uuid.uuid4()
    doc = uuid.uuid4()
    a = LR.lot_key(cid, doc, 0, 0)
    b = LR.lot_key(cid, doc, 0, 0)
    assert a == b
    assert LR.lot_key(cid, doc, 0, 1) != a           # partiya indeksi ajratadi
    assert LR.lot_key(cid, doc, 1, 0) != a           # qator indeksi ajratadi
    assert LR.lot_key(uuid.uuid4(), doc, 0, 0) != a  # kompaniya ajratadi


def test_ATRIBUT_boyicha_BIRLASHTIRISH_YOQ(client, admin_headers, ctx):
    """AYNI raqam/muddat/narx bilan kelgan keyingi yetkazish — BOSHQA kogorta."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    line = {"product_id": pid, "qty": 5, "unit_cost": 700, "unit": "dona",
            "lots": [{"qty": 5, "batch_number": "BIR-XIL"}]}
    _commit(client, admin_headers, [line])
    _commit(client, admin_headers, [line])       # boshqa client_uuid
    assert len(_lots(pid)) == 2, "atribut bo'yicha jimgina birlashtirildi"
    assert _inv_qty(pid, bid) == Decimal("10.000")


# == 3. MA'LUMOT TEKSHIRUVI =================================================

def test_KUZATUVLI_mahsulotga_lots_MAJBURIY(client, admin_headers):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 5,
                                         "unit_cost": 700, "unit": "dona"}])
    assert r.status_code == 400, r.text
    assert "lots" in r.text or "MAJBUR" in r.text


def test_KUZATUVSIZ_mahsulotga_lots_RAD_etiladi(client, admin_headers):
    pid = _new_product(client, admin_headers)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                         "unit": "dona", "lots": [{"qty": 5}]}])
    assert r.status_code == 400, r.text


def test_partiyalar_YIGINDISI_qatorga_TENG_bolishi_shart(client, admin_headers):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 4}, {"qty": 5}]}])
    assert r.status_code == 400, r.text
    assert "TENG EMAS" in r.text


def test_yigindi_KASR_aniqlikda_solishtiriladi(client, admin_headers, ctx):
    """0.1+0.2 float'da 0.30000000000000004 — Decimal'da ANIQ 0.3."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 0.3, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 0.1}, {"qty": 0.2}]}])
    assert r.status_code == 200, r.text
    assert _inv_qty(pid, bid) == Decimal("0.300")


def test_TANNARX_jimgina_base_buy_price_dan_OLINMAYDI(client, admin_headers, ctx):
    """Narx provenansi: partiya narxi -> qator narxi -> XATO. Taxmin YO'Q."""
    cid, bid = ctx
    with _db() as db:
        p = Product(id=uuid.uuid4(), company_id=cid, name=f"Narx {uuid.uuid4().hex[:6]}",
                    article_code="N-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=db.query(Unit).first().id, base_buy_price=999,
                    base_sell_price=1200, tax_rate=0, track_lots=True)
        db.add(p)
        db.commit()
        pid = p.id
    with _db() as db:
        prod = db.get(Product, pid)
        with pytest.raises(LR.LotPayloadError):
            LR.create_lots(db, company_id=cid, branch_id=bid, product=prod,
                           lots=[LR.LotIn(qty=Decimal("5"))], doc_key="X", line_index=0,
                           source_type=LR.SOURCE_RECEIVING, default_cost=None, now=NOW)


def test_qator_narxi_partiyaga_TUSHADI(client, admin_headers, ctx):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 4, "unit_cost": 123.45,
                                     "unit": "dona", "lots": [{"qty": 4}]}])
    assert Decimal(str(_lots(pid)[0].unit_cost)) == Decimal("123.45")


def test_partiya_OZ_narxi_qator_narxini_YENGADI(client, admin_headers, ctx):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 4, "unit_cost": 100,
                                     "unit": "dona",
                                     "lots": [{"qty": 4, "unit_cost": 250}]}])
    assert Decimal(str(_lots(pid)[0].unit_cost)) == Decimal("250.00")


# == 4. MUDDAT ==============================================================

def _confirm_tz(client, admin_headers):
    return client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})


def test_MUDDAT_kuzatuvi_TASDIQLANMAGAN_zonada_YOQILMAYDI(client, admin_headers, ctx):
    cid, bid = ctx
    from app.services import catalog_import_v2 as civ2
    with _db() as db:                      # tasdiqni OLIB TASHLAYMIZ
        civ2.set_catalog_settings(db, cid, **{LP.CONFIRM_FIELD: {}})
        db.commit()
    pid = _new_product(client, admin_headers)
    r = _enable(client, admin_headers, pid, track_expiry=True)
    assert r.status_code == 409, r.text
    assert "TASDIQLANMAGAN" in r.text


def test_zona_tasdiqlangach_muddat_kuzatuvi_YOQILADI(client, admin_headers, ctx):
    assert _confirm_tz(client, admin_headers).status_code == 200
    pid = _new_product(client, admin_headers)
    r = _enable(client, admin_headers, pid, track_expiry=True)
    assert r.status_code == 200, r.text
    assert r.json()["track_expiry"] is True


def test_MUDDAT_kuzatuvida_expiry_date_MAJBURIY(client, admin_headers, ctx):
    _confirm_tz(client, admin_headers)
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid, track_expiry=True)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                         "unit": "dona", "lots": [{"qty": 5}]}])
    assert r.status_code == 400, r.text
    assert "expiry_date" in r.text


def test_MUDDATI_OTGAN_tovar_QABUL_QILINMAYDI(client, admin_headers, ctx):
    _confirm_tz(client, admin_headers)
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid, track_expiry=True)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 5,
                                                   "expiry_date": YESTERDAY.isoformat()}]}])
    assert r.status_code == 400, r.text
    assert "muddat" in r.text.lower()


def test_muddat_BUGUN_hali_QABUL_qilinadi(client, admin_headers, ctx):
    """Chegara saxiy: `expiry == biznes sanasi` o'sha kun oxirigacha yaroqli."""
    cid, bid = ctx
    _confirm_tz(client, admin_headers)
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid, track_expiry=True)
    with _db() as db:
        biz = LP.business_date(db, bid)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                         "unit": "dona",
                                         "lots": [{"qty": 5, "expiry_date": biz.isoformat()}]}])
    assert r.status_code == 200, r.text


def test_MUDDAT_hosila_holat_saqlanmaydi(client, admin_headers, ctx):
    """`GET /lots/products/{id}` da `expired` HISOBLANADI, `status` o'zgarmaydi."""
    cid, bid = ctx
    _confirm_tz(client, admin_headers)
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid, track_expiry=True)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                     "unit": "dona",
                                     "lots": [{"qty": 5, "expiry_date": FUTURE.isoformat()}]}])
    # Muddatni ORQAGA suramiz — miqdor QIMIRLAMASIN, faqat `expired` yonsin.
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.expiry_date = YESTERDAY
        db.commit()
    r = client.get(f"/api/v1/lots/products/{pid}", headers=admin_headers)
    assert r.status_code == 200, r.text
    lot = r.json()["lots"][0]
    assert lot["expired"] is True
    assert lot["status"] == SI.OPEN, "muddat holatni o'zgartirdi"
    assert lot["remaining_qty"] == 5.0, "muddati o'tgan tovar qoldiqdan YO'QOLDI"
    assert r.json()["inventory_qty"] == 5.0


# == 5. KUZATUVNI YOQISH — MAVJUD QOLDIQ ====================================

def _set_stock(client, admin_headers, cid, bid, qty):
    pid = _new_product(client, admin_headers)
    with _db() as db:
        inv = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(pid), Inventory.branch_id == bid).first()
        if inv is None:
            inv = Inventory(product_id=uuid.UUID(pid), branch_id=bid, qty=0,
                            min_qty=0, updated_at=NOW)
            db.add(inv)
        inv.qty = qty
        db.commit()
    return pid


def test_MAVJUD_qoldiq_bilan_yoqishda_partiya_MAJBURIY(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _set_stock(client, admin_headers, cid, bid, 40)
    r = _enable(client, admin_headers, pid)      # na opening_lots, na legacy narx
    assert r.status_code == 400, r.text
    assert "legacy_unit_cost" in r.text


def test_ochilish_partiyalari_qoldiqqa_TENG_bolishi_shart(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _set_stock(client, admin_headers, cid, bid, 40)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 10, "unit_cost": 700},
                              {"qty": 20, "unit_cost": 700}])
    assert r.status_code == 400, r.text
    assert "TENG EMAS" in r.text


def test_ochilish_partiyalari_bilan_YOQILADI(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _set_stock(client, admin_headers, cid, bid, 40)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 15, "unit_cost": 700},
                              {"qty": 25, "unit_cost": 800}])
    assert r.status_code == 200, r.text
    assert len(_lots(pid)) == 2
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_LEGACY_partiya_miqdori_AYNAN_joriy_qoldiq(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _set_stock(client, admin_headers, cid, bid, 37)
    r = _enable(client, admin_headers, pid, legacy_unit_cost=650)
    assert r.status_code == 200, r.text
    lots = _lots(pid)
    assert len(lots) == 1
    assert Decimal(str(lots[0].remaining_qty)) == Decimal("37.000")
    assert lots[0].expiry_date is None, "noma'lum muddat TAXMIN qilindi"
    assert lots[0].batch_no is None, "noma'lum partiya raqami TAXMIN qilindi"
    assert lots[0].source_type == LR.SOURCE_LEGACY
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok


def test_NOL_qoldiqda_partiya_KERAK_EMAS(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    r = _enable(client, admin_headers, pid)
    assert r.status_code == 200, r.text
    assert r.json()["lots_created"] == 0


def test_IKKI_marta_yoqib_bolmaydi(client, admin_headers):
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    assert _enable(client, admin_headers, pid).status_code == 409


def test_yoqish_SABABSIZ_qabul_qilinmaydi(client, admin_headers):
    pid = _new_product(client, admin_headers)
    r = client.post("/api/v1/lots/enable", headers=admin_headers,
                    json={"product_id": pid})
    assert r.status_code == 422, r.text


def test_yoqish_AUDIT_izini_qoldiradi(client, admin_headers, ctx):
    from app.models.sync import AuditLog
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    with _db() as db:
        a = (db.query(AuditLog)
             .filter(AuditLog.entity == "product_lot_tracking",
                     AuditLog.entity_id == uuid.UUID(pid)).first())
        assert a is not None, "kuzatuvni yoqish AUDITSIZ o'tdi"
        assert a.after["track_lots"] is True
        assert a.after["reason"]


# == 6. INVARIANT — ATAYIN BUZISH (MANFIY NAZORAT) ==========================

def test_FAQAT_qoldiq_buzilsa_invariant_TUTADI(client, admin_headers, ctx):
    """Qoldiq siljidi, partiyalar joyida — nomuvofiqlik KO'RINISHI shart."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    with _db() as db:
        assert SI.check(db, cid, [uuid.UUID(pid)]).ok         # avval TOZA
        inv = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(pid), Inventory.branch_id == bid).first()
        inv.qty = Decimal("99")                               # ATAYIN buzamiz
        db.flush()
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert not rep.ok, "qoldiq buzildi, invariant JIM qoldi"
        m = rep.mismatches[0]
        assert m.inventory_qty == Decimal("99") and m.lot_sum == Decimal("10.000")
        with pytest.raises(SI.InvariantBroken):
            SI.assert_ok(db, cid, [uuid.UUID(pid)])
        db.rollback()


def test_FAQAT_partiya_buzilsa_invariant_TUTADI(client, admin_headers, ctx):
    """Partiya siljidi, qoldiq joyida — bu ham nomuvofiqlik."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.remaining_qty = Decimal("3")                        # ATAYIN buzamiz
        db.flush()
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert not rep.ok, "partiya buzildi, invariant JIM qoldi"
        assert rep.mismatches[0].lot_sum == Decimal("3.000")
        db.rollback()


def test_partiya_OCHIRILSA_invariant_TUTADI(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    with _db() as db:
        db.query(StockBatch).filter(
            StockBatch.product_id == uuid.UUID(pid)).delete(synchronize_session=False)
        db.flush()
        assert not SI.check(db, cid, [uuid.UUID(pid)]).ok
        db.rollback()


def test_NOTANISH_holat_FAIL_CLOSED(client, admin_headers, ctx):
    """Yangi `status` qiymati jimgina yig'indidan tushib qolmasin."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    with _db() as db:
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.status = "quarantined"                     # kelajakdagi holat
        db.flush()
        with pytest.raises(SI.UnknownLotStatus):
            SI.check(db, cid, [uuid.UUID(pid)])
        db.rollback()


def test_QABUL_invariant_buzilsa_TRANZAKSIYA_QAYTADI(client, admin_headers, ctx, monkeypatch):
    """Darvoza COMMIT'dan OLDIN — rad etilgan kirim bazada IZ QOLDIRMASIN.

    ⚠️  Bu aynan topilgan xato: tekshiruv `db.commit()` dan KEYIN turganda
        `db.rollback()` hech narsani qaytarmasdi — operator 409 ko'rardi, buzilgan
        qoldiq esa bazada QOLARDI.
    """
    from app.api.v1 import receiving as RCV
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    before_inv = _inv_qty(pid, bid)
    before_lots = len(_lots(pid))

    def _boom(db, company_id, product_ids):
        raise SI.InvariantBroken("sun'iy buzilish (sinov)")
    monkeypatch.setattr(RCV._LR, "assert_invariant", _boom)

    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 9, "unit_cost": 700,
                                         "unit": "dona", "lots": [{"qty": 9}]}])
    assert r.status_code == 409, r.text
    assert _inv_qty(pid, bid) == before_inv, "rad etilgan kirim qoldiqni O'ZGARTIRDI"
    assert len(_lots(pid)) == before_lots, "rad etilgan kirim PARTIYA qoldirdi"


# == 7. ESKI YOZUVCHILAR — KUZATUVLIDA FAIL-CLOSED ==========================

def test_SOTUV_kuzatuvli_mahsulotni_ENDI_SOTADI(client, admin_headers, ctx):
    """Phase 2: kuzatuvli mahsulot SOTILADI — darvoza o'rniga FEFO taqsimoti.

    ⚠️  Bu test Phase 1 da TESKARISINI talab qilardi (400 bilan rad etish) va
        O'SHANDA to'g'ri edi: FEFO yo'q edi, ya'ni sotuv qoldiqni partiyalardan
        ayirmasdan kamaytirardi. Phase 2 taqsimotni olib keldi — qoida o'zgardi,
        chunki IMKONIYAT o'zgardi. Batafsil sinovlar: test_lot_fefo_sale.py.
    """
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    r = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 4, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 5000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _inv_qty(pid, bid) == Decimal("6.000")
    with _db() as db:
        from app.models.inventory import SaleItemLotAllocation
        a = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == uuid.UUID(pid)).all()
        assert len(a) == 1 and Decimal(str(a[0].qty)) == Decimal("4.000")


def test_QAYTARISH_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = client.post("/api/v1/returns", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": 1000}],
        "reason": "other", "refund_method": "cash", "restock": True,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 409, r.text


def test_HISOBDAN_CHIQARISH_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10}]}])
    r = client.post("/api/v1/inventory/writeoff", headers=admin_headers, json={
        "product_id": pid, "qty": 2, "reason": "brak"})
    assert r.status_code == 409, r.text
    assert _inv_qty(pid, bid) == Decimal("10.000")


def test_INVENTARIZATSIYA_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": pid, "counted": 3}], "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 409, r.text


def test_XARID_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    """`POST /purchases` — bu ham kirim, lekin `lots` ni BILMAYDI."""
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    sup = client.get("/api/v1/suppliers", headers=admin_headers).json()[0]["id"]
    r = client.post("/api/v1/purchases", headers=admin_headers, json={
        "supplier_id": sup, "payment": "cash",
        "items": [{"product_id": pid, "qty": 5, "unit_cost": 700}]})
    assert r.status_code == 409, r.text


def test_XARID_TAHRIRI_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    """Kuzatuv YOQILGANDAN keyin eski xaridni tahrirlash — delta partiyani bilmaydi."""
    pid = _new_product(client, admin_headers)
    sup = client.get("/api/v1/suppliers", headers=admin_headers).json()[0]["id"]
    r = client.post("/api/v1/purchases", headers=admin_headers, json={
        "supplier_id": sup, "payment": "cash",
        "items": [{"product_id": pid, "qty": 5, "unit_cost": 700}]})
    assert r.status_code == 200, r.text
    pur_id = r.json()["id"]
    det = client.get(f"/api/v1/purchases/{pur_id}", headers=admin_headers).json()
    it = det["items"][0]
    assert _enable(client, admin_headers, pid,
                   legacy_unit_cost=700).status_code == 200
    r2 = client.patch(f"/api/v1/purchases/{pur_id}", headers=admin_headers, json={
        "items": [{"id": it["id"], "qty": 2, "unit_cost": 700}]})
    assert r2.status_code == 409, r2.text


def test_TRANSFER_kuzatuvli_mahsulotni_RAD_etadi(client, admin_headers, ctx):
    """Ko'chirish partiyani IKKI filialda ko'chirishi kerak edi — bu Phase 4."""
    from app.models.org import Branch
    cid, bid = ctx
    with _db() as db:
        others = db.query(Branch).filter(Branch.company_id == cid,
                                         Branch.id != bid,
                                         Branch.deleted_at.is_(None)).all()
        dst = str(others[0].id) if others else None
    if dst is None:
        # ⚠️  SKIP QILMAYMIZ: o'tkazib yuborilgan test darvozani ISBOTLAMAYDI.
        #     Urug'dagi tarif "start" (max_branches=1) — API orqali ikkinchi filial
        #     ochilmaydi, shuning uchun uni TO'G'RIDAN-TO'G'RI yozamiz. Sinov mavzusi
        #     tarif limiti emas, ko'chirish darvozasi.
        with _db() as db:
            nb = Branch(id=uuid.uuid4(), company_id=cid,
                        name=f"Partiya filial {uuid.uuid4().hex[:6]}",
                        code=f"F-{uuid.uuid4().hex[:3]}", timezone="Asia/Tashkent",
                        is_active=True, created_at=NOW)
            db.add(nb)
            db.commit()
            dst = str(nb.id)
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    r = client.post("/api/v1/inventory/transfer", headers=admin_headers, json={
        "from_branch_id": str(bid), "to_branch_id": dst,
        "items": [{"product_id": pid, "qty": 1}], "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 409, r.text


def test_KUZATUVSIZ_mahsulot_bugungidek_ISHLAYDI(client, admin_headers, ctx):
    """Darvozalar kuzatuvsiz oqimni QIMIRLATMASLIGI shart (regressiya)."""
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _commit(client, admin_headers,
                   [{"product_id": pid, "qty": 10, "unit_cost": 700,
                     "unit": "dona"}]).status_code == 200
    assert client.post("/api/v1/inventory/writeoff", headers=admin_headers, json={
        "product_id": pid, "qty": 1, "reason": "brak"}).status_code == 200
    assert client.post("/api/v1/inventory/count", headers=admin_headers, json={
        "items": [{"product_id": pid, "counted": 9}],
        "client_uuid": str(uuid.uuid4())}).status_code == 200


# == 8. QAMROV REGRESSIYASI — YANGI YOZUVCHI DARVOZASIZ QOLMASIN ============

def test_BARCHA_qoldiq_yozuvchilari_DARVOZALANGAN():
    """`Inventory.qty` ni yozadigan MODUL yo himoyalangan, yo ANIQ oqlangan.

    ⚠️  Bu sinov kelajak uchun: yangi yozuvchi qo'shilsa va darvoza unutilsa,
        kuzatuvli mahsulot JIMGINA partiyasiz siljib ketardi. Ro'yxatga yangi
        nom qo'shish — ONGLI qaror, tasodif emas.
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    # ANIQ OQLANGAN: bu modullar YANGI mahsulot yaratayotganda qator ochadi
    # (`track_lots` qurilish bo'yicha False), yoki dev-urug'i.
    EXEMPT = {
        "api/v1/products.py",              # faqat yangi mahsulot + min_qty (qty=0)
        "services/catalog_import_v2.py",   # INITIAL_CREATE — yangi mahsulot
        "seed.py", "services/demo_seed.py",        # dev urug'i
        "api/v1/receiving.py",             # PARTIYANI BILADI (Phase 1)
        "services/sales.py",               # FEFO ni BILADI (Phase 2) — darvoza
                                           # o'rniga haqiqiy taqsimot qiladi
    }
    # ⚠️  IMPORT YETARLI EMAS — CHAQIRUV talab qilinadi. Ilgari ro'yxatda
    #     `"stock_gate"` bor edi va u IMPORT satriga ham mos kelardi: darvoza
    #     chaqiruvi olib tashlanib, import qolib ketsa qorovul YASHIL qolardi.
    #     Buni manfiy nazorat aynan shunday tutdi.
    #     Namuna BITTA va ANIQ: `_gate(` kabi qisqa bo'lak begona funksiyaga
    #     (`cutover_open_shift_gate(`) ham mos kelib, qorovulni YOLG'ON yashil
    #     qilardi — buni ham manfiy nazorat tutdi.
    GATED = ("assert_untracked(",)
    writer = re.compile(r"\.qty\s*=\s|\.qty\s*\+=|Inventory\(")
    bad = []
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith("models/") or rel in EXEMPT:
            continue
        src = f.read_text(encoding="utf-8")
        if not writer.search(src):
            continue
        if not any(g in src for g in GATED):
            bad.append(rel)
    assert not bad, f"darvozasiz qoldiq yozuvchilari: {bad}"


# == 9. KATALOG RESET — PARTIYALAR GRAFDA VA IZDA ===========================

def test_RESET_grafi_partiya_jadvallarini_BILADI():
    from app.services import catalog_reset as CR
    delete_tables = [n for n, _ in CR.DELETE_PLAN]
    assert "stock_batches" in delete_tables
    assert "sale_item_lot_allocations" in delete_tables
    # Taqsimotlar partiyalardan OLDIN o'chishi shart (FK).
    assert (delete_tables.index("sale_item_lot_allocations")
            < delete_tables.index("stock_batches"))
    assert "stock_batches" in CR.KNOWN_PRODUCT_REFERRERS
    assert "sale_item_lot_allocations" in CR.KNOWN_PRODUCT_REFERRERS


def test_RESET_izi_partiya_MAZMUNINI_hisobga_oladi(client, admin_headers, ctx):
    """Qoldiqni QIMIRLATMAYDIGAN partiya o'zgarishi ham izni o'zgartirsin."""
    from app.services import catalog_reset as CR
    cid, bid = ctx
    pid = _new_product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _commit(client, admin_headers, [{"product_id": pid, "qty": 10, "unit_cost": 700,
                                     "unit": "dona", "lots": [{"qty": 10,
                                                               "batch_number": "IZ-1"}]}])
    names = [n for n, _ in CR.DIGEST_PLAN]
    assert "stock_batches" in names, "partiya mazmuni izga kirmaydi"
    with _db() as db:
        sql = dict(CR.DIGEST_PLAN)["stock_batches"]
        before = CR._digest(db, sql, cid)
        b = db.query(StockBatch).filter(StockBatch.product_id == uuid.UUID(pid)).first()
        b.batch_no = "IZ-2"                 # qoldiq QIMIRLAMAYDI
        db.flush()
        after = CR._digest(db, sql, cid)
        assert before != after, "partiya tahriri izda ko'rinmadi"
        db.rollback()


# == 10. MAJBURIY SXEMA — PHASE 1 OBYEKTLARI ================================

def test_PHASE1_qabul_ustunlari_MAJBURIY():
    from app.core import required_schema as rs
    names = {f"{t}.{c}" for t, c in rs.REQUIRED_COLUMNS}
    for col in ("company_id", "received_qty", "remaining_qty", "status",
                "source_type", "client_uuid", "updated_at", "row_version",
                "purchase_item_id", "receiving_id", "external_lot_id", "supplier_id"):
        assert f"stock_batches.{col}" in names, f"stock_batches.{col} majburiy emas"


def test_MAJBURIY_ustunlar_MIGRATSIYA_qola_oladigan_bolsin():
    """Ikki tomonlama qoida: majburiy ustunni `_ADDED_COLUMNS` QO'SHA OLISHI shart.

    ⚠️  Aks holda yetishmovchilikni TUZATADIGAN qadam yo'q va tayyorlik abadiy
        qizil qolardi — ya'ni ishga tushish boot-loop'ga tushardi. Aynan shu
        sabab butun `sale_item_lot_allocations` jadvali ro'yxatga KIRITILMADI:
        uni `create_all` yaratadi, migratsiya emas.
    """
    from app.core import required_schema as rs
    from app.initdb import _ADDED_COLUMNS
    added = {(t, c) for t, c, _ in _ADDED_COLUMNS}
    yoq = [p for p in rs.REQUIRED_COLUMNS if p not in added]
    assert not yoq, f"migratsiya qo'sha olmaydigan majburiy ustunlar: {yoq}"


def test_QABUL_idempotentlik_indeksi_MAJBURIY():
    from app.core import required_schema as rs
    assert ("ux_lot_intake_key", "stock_batches") in rs.REQUIRED_INDEXES


# == 11. POSTGRES — MAVJUD BAZADA MIGRATSIYA (dialekt tuzog'i) ===============
#  ⚠️  YANGI bazada `create_all` ustunlarni O'ZI yaratadi va `ALTER` UMUMAN
#      ishga tushmaydi. Ya'ni toza baza sinovi ustun migratsiyasini O'LCHAMAYDI.
#      Staging esa MAVJUD baza edi — aynan shu bo'shliqda `BOOLEAN DEFAULT 0`
#      Postgres'da jimgina yiqilgan edi. Shu bois quyidagi sinov avval bazani
#      quradi, Phase 1 ustunlarini OLIB TASHLAYDI va migratsiyani MAVJUD baza
#      ustida yurgizadi.

PHASE1_COLS = ("company_id", "received_qty", "remaining_qty", "status",
               "source_type", "purchase_item_id", "receiving_id",
               "external_lot_id", "supplier_id", "client_uuid",
               "updated_at", "row_version")


@pytest.fixture()
def pg_url(tmp_path):
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(str(tmp_path / "pgdata"))
    try:
        u = srv.get_uri()
        yield ("postgresql+psycopg://" + u[len("postgresql://"):]
               if u.startswith("postgresql://") and "+psycopg" not in u else u)
    finally:
        try:
            srv.cleanup()
        except Exception:      # noqa: BLE001
            pass


def _initdb(url):
    import os
    import subprocess
    import sys as _sys
    srv = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.run([_sys.executable, "-m", "app.initdb"], cwd=srv,
                          capture_output=True, text=True, timeout=900,
                          env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"))


def _drop_phase1(url):
    from sqlalchemy import create_engine, text
    eng = create_engine(url)
    with eng.begin() as con:
        con.execute(text("DROP INDEX IF EXISTS ux_lot_intake_key"))
        con.execute(text("DROP INDEX IF EXISTS ix_lot_fefo"))
        con.execute(text("DROP INDEX IF EXISTS ix_lot_expiry"))
        for c in PHASE1_COLS:
            con.execute(text(f"ALTER TABLE stock_batches DROP COLUMN IF EXISTS {c}"))
    eng.dispose()


def test_PG_MAVJUD_bazada_partiya_ustunlari_QOSHILADI(pg_url):
    from sqlalchemy import create_engine, inspect

    from app.core import required_schema as rs
    r = _initdb(pg_url)
    assert r.returncode == 0, (r.stdout + r.stderr)[-900:]
    _drop_phase1(pg_url)

    # ── Nazorat: fixture HAQIQATAN eski sxemani beradi ──────────────────────
    eng = create_engine(pg_url)
    cols = {c["name"] for c in inspect(eng).get_columns("stock_batches")}
    assert not (set(PHASE1_COLS) & cols), "ustunlar tushmadi — sinov bo'sh bo'lardi"
    # ── Tayyorlik shu holatда QIZIL bo'lishi shart ──────────────────────────
    ok, missing = rs.ok(eng)
    assert ok is False, "Phase 1 ustunlarisiz tayyorlik YASHIL qoldi"
    assert any("remaining_qty" in m for m in missing), missing
    assert any("ux_lot_intake_key" in m for m in missing), missing
    eng.dispose()

    # ── MAVJUD baza ustida migratsiya — ALTER yo'li HAQIQATAN o'lchanadi ────
    r2 = _initdb(pg_url)
    out = r2.stdout + r2.stderr
    assert r2.returncode == 0, out[-1500:]

    eng2 = create_engine(pg_url)
    insp = inspect(eng2)
    got = {c["name"] for c in insp.get_columns("stock_batches")}
    yoq = [c for c in PHASE1_COLS if c not in got]
    assert not yoq, f"Postgres'da qo'shilmagan ustunlar: {yoq}\n{out[-900:]}"
    ix = {i["name"] for i in insp.get_indexes("stock_batches")}
    assert "ux_lot_intake_key" in ix, sorted(ix)
    ok2, missing2 = rs.ok(eng2)
    assert ok2, missing2
    eng2.dispose()


def test_PG_migratsiya_IDEMPOTENT(pg_url):
    """Har deploy qayta yuradi — ikkinchi yurish xatosiz o'tsin."""
    from sqlalchemy import create_engine

    from app.core import required_schema as rs
    assert _initdb(pg_url).returncode == 0
    _drop_phase1(pg_url)
    assert _initdb(pg_url).returncode == 0
    r = _initdb(pg_url)
    assert r.returncode == 0, (r.stdout + r.stderr)[-900:]
    eng = create_engine(pg_url)
    ok, missing = rs.ok(eng)
    assert ok, missing
    eng.dispose()
