# -*- coding: utf-8 -*-
"""PHASE 5B.1 ADVERSARIAL REVIEW — tasdiqlangan uchta kamchilik.

  (G-2) Muddat KUZATILMAYDIGAN (FIFO) mahsulotda sanali partiya. FEFO nomzodlari
        muddati o'tgan partiyani HAR kuzatuvli mahsulotda chiqarib tashlaydi:
        yoqishdagi ochilish partiyasi yoki kirim partiyasiga yozilgan o'tgan sana
        tovarni birinchi kundanoq sotuvdan tushirardi. Sanoq bu sanani allaqachon
        rad etardi — endi yoqish va kirim ham AYNI qoida va AYNI matn bilan.

  (X-1) `/lots/enable` mahsulotning HAR filialdagi qatorini qulflaydi/yaratadi;
        ko'chirish bilan deadlock (40P01) bo'lsa yoqish tranzaksiyasi to'liq
        qaytadi — qayta urinish xavfsiz, 500 emas.

  (T1)  Yoqishdagi IntegrityError qayta urinishini HECH BIR sinov qamramasdi:
        uni o'chirib tashlash hamma sinovni yashil qoldirardi.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.inventory import Inventory, StockBatch
from app.models.sync import AuditLog
from app.services import lot_policy as LP

from tests.test_lot_fefo_sale import (  # noqa: F401
    _db,
    _enable,
    _product,
    _recv,
    _sell,
    _set_stock,
    ctx,
    sup,
)

FIFO_SANA = ("'{nom}' muddat bo'yicha KUZATILMAYDI — yangi partiyaga `expiry_date` yozib "
             "bo'lmaydi. Avval mahsulotda muddat kuzatuvini yoqing.")


def _nom(pid):
    from app.models.catalog import Product
    with _db() as db:
        return db.get(Product, uuid.UUID(pid)).name


def _holat(pid):
    from app.models.catalog import Product
    with _db() as db:
        p = db.get(Product, uuid.UUID(pid))
        lots = sorted((str(b.expiry_date), str(b.remaining_qty)) for b in
                      db.query(StockBatch).filter(StockBatch.product_id == p.id).all())
        inv = sorted((str(i.branch_id), str(i.qty)) for i in
                     db.query(Inventory).filter(Inventory.product_id == p.id).all())
        audit = db.query(AuditLog).filter(AuditLog.entity == "product_lot_tracking",
                                          AuditLog.entity_id == p.id).count()
        return {"track": (bool(p.track_lots), bool(p.track_expiry)), "lots": lots,
                "inv": inv, "audit": audit}


def _biz(bid):
    with _db() as db:
        return LP.business_date(db, bid)


# ══ G-2. FIFO mahsulotda sanali partiya ═══════════════════════════════════════

def test_FIFO_ochilish_partiyasida_SANA_400_yozuvsiz_sanasiz_200_va_SOTILADI(
        client, admin_headers, ctx):
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 2)
    biz = _biz(bid)
    oldin = _holat(pid)
    for sana in ((biz - timedelta(days=30)).isoformat(), (biz + timedelta(days=30)).isoformat()):
        r = _enable(client, admin_headers, pid, expiry=False,
                    opening_lots=[{"qty": 2, "unit_cost": 55, "expiry_date": sana}])
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == FIFO_SANA.format(nom=_nom(pid)), r.text
        assert _holat(pid) == oldin
    # NAZORAT: AYNI partiya SANASIZ — o'tadi va tovar darhol SOTILADI (FEFO nomzodi).
    r = _enable(client, admin_headers, pid, expiry=False,
                opening_lots=[{"qty": 2, "unit_cost": 55}])
    assert r.status_code == 200, r.text
    assert _sell(client, admin_headers, pid, 1).status_code == 200


def test_FIFO_kirim_partiyasida_SANA_400_yozuvsiz_sanasiz_200(
        client, admin_headers, ctx, sup):
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=False).status_code == 200
    oldin = _holat(pid)
    r = _recv(client, admin_headers, sup, pid, 3, 55, expiry=_biz(bid) - timedelta(days=5))
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == FIFO_SANA.format(nom=_nom(pid)), r.text
    assert _holat(pid) == oldin
    # NAZORAT: sanasiz kirim o'tadi, qoldiq va partiya birga o'sadi.
    assert _recv(client, admin_headers, sup, pid, 3, 55).status_code == 200
    h = _holat(pid)
    assert h["lots"] == [("None", "3.000")], h
    assert _sell(client, admin_headers, pid, 1).status_code == 200


def test_MUDDATLI_mahsulotda_sanali_partiya_AVVALGIDEK_200(client, admin_headers, ctx, sup):
    """NAZORAT: yangi qoida faqat muddat KUZATILMAYDIGAN mahsulotga tegadi."""
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    assert _enable(client, admin_headers, pid, expiry=True).status_code == 200
    r = _recv(client, admin_headers, sup, pid, 2, 55, expiry=_biz(bid) + timedelta(days=20))
    assert r.status_code == 200, r.text


# ══ X-1 / T1. Yoqishning qayta urinishi ══════════════════════════════════════

class _Deadlock(Exception):
    sqlstate = "40P01"


class _LockTimeout(Exception):
    sqlstate = "55P03"


def _bir_marta(monkeypatch, exc, n=1):
    from app.api.v1 import lots as L
    asl = L._inventory_rows_for_update
    qoldi = {"n": n}

    def _yiqil(*a, **k):
        if qoldi["n"] > 0:
            qoldi["n"] -= 1
            raise exc
        return asl(*a, **k)

    monkeypatch.setattr(L, "_inventory_rows_for_update", _yiqil)
    return qoldi


@pytest.mark.parametrize("xato", [
    IntegrityError("INSERT INTO inventory ...", {}, Exception("duplicate key")),
    OperationalError("SELECT ... FOR UPDATE", {}, _Deadlock("deadlock detected")),
], ids=["integrity", "deadlock_40P01"])
def test_YOQISH_bir_marta_TOQNASHUV_qayta_urinib_200_audit_va_partiya_BITTA(
        client, admin_headers, ctx, monkeypatch, xato):
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 4)
    qoldi = _bir_marta(monkeypatch, xato)
    r = _enable(client, admin_headers, pid, expiry=False, legacy_unit_cost=55)
    assert r.status_code == 200, r.text
    assert qoldi["n"] == 0, "to'qnashuv simulyatsiyasi ishlamadi — sinov o'lchamaydi"
    h = _holat(pid)
    assert h["track"] == (True, False) and h["audit"] == 1 and h["lots"] == [("None", "4.000")], h


def test_YOQISH_uch_marta_TOQNASHUV_409_va_HECH_NARSA_yozilmaydi(
        client, admin_headers, ctx, monkeypatch):
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 4)
    oldin = _holat(pid)
    _bir_marta(monkeypatch, IntegrityError("INSERT", {}, Exception("dup")), n=3)
    r = _enable(client, admin_headers, pid, expiry=False, legacy_unit_cost=55)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Ombor band — qayta urining"
    assert _holat(pid) == oldin


def test_YOQISH_boshqa_baza_xatosi_JIMGINA_qayta_urinilmaydi(client, admin_headers, ctx, monkeypatch):
    """NAZORAT: faqat 40P01 qayta uriniladi — lock timeout (55P03) kabi xato yashirilmaydi."""
    _cid, bid = ctx
    pid = _product(client, admin_headers)
    _set_stock(pid, bid, 4)
    oldin = _holat(pid)
    qoldi = _bir_marta(monkeypatch, OperationalError("SELECT", {}, _LockTimeout("lock timeout")), n=3)
    with pytest.raises(OperationalError):
        _enable(client, admin_headers, pid, expiry=False, legacy_unit_cost=55)
    assert qoldi["n"] == 2, "55P03 qayta urinildi — faqat 40P01 urinilishi kerak edi"
    assert _holat(pid) == oldin
    assert Decimal(_holat(pid)["inv"][0][1]) == Decimal("4")
