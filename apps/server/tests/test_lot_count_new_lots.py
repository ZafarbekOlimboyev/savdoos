# -*- coding: utf-8 -*-
"""PHASE 4B — SANOQDA TOPILGAN, TIZIMDA YO'Q PARTIYA.

Phase 3 da ortiqcha miqdor faqat SANALGAN partiyadan nusxa olib yaratilardi:
muddat va tannarx o'sha kogortadan ko'chirilardi. Javonda BOSHQA muddatli qadoq
topilsa, bu muddat hisobotini yolg'on qilardi.

Shu bois operator endi partiyani ANIQ e'lon qiladi — o'z raqami, o'z muddati,
o'zi aytgan tannarx bilan. U hech qachon hujjat narxi sifatida ko'rinmasin
uchun `source_type='adjustment'` bo'lib tug'iladi.
"""
import uuid
from decimal import Decimal

from app.services import stock_invariant as SI

from tests.test_lot_count import _by_expiry, _count, _ok, _q
from tests.test_lot_fefo_sale import (  # noqa: F401
    D10,
    D20,
    D30,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    _recv_plain,
    ctx,
    sup,
)


def _new(qty, cost=0, batch=None, expiry=None, reason=None):
    d = {"qty": qty, "unit_cost": cost}
    if batch:
        d["batch_no"] = batch
    if expiry:
        d["expiry_date"] = expiry.isoformat()
    if reason:
        d["reason"] = reason
    return d


def test_EʼLON_qilingan_partiya_OZ_muddati_va_OZ_narxi_bilan_tugʻiladi(client, admin_headers, ctx, sup):
    """Javonda boshqa muddatli qadoq topildi — u D10 kogortasiga QO'SHILMAYDI."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    manba = _lots(pid)[0]

    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 10,
        "lots": [{"stock_batch_id": str(manba.id), "counted": 4}],
        "new_lots": [_new(6, 70, batch="TOPILDI", expiry=D30, reason="javondan chiqdi")]}])
    assert r.status_code == 200, r.text

    lots = _lots(pid)
    assert len(lots) == 2, [l.batch_no for l in lots]
    eski = [x for x in lots if x.id == manba.id][0]
    yangi = [x for x in lots if x.id != manba.id][0]
    assert Decimal(str(eski.remaining_qty)) == 4, "sanalgan kogorta o'zgardi"
    assert Decimal(str(eski.unit_cost)) == 50 and eski.expiry_date == D10
    # Yangi partiya — NUSXA EMAS: o'z muddati, o'z raqami, operator narxi.
    assert yangi.batch_no == "TOPILDI" and yangi.expiry_date == D30
    assert Decimal(str(yangi.unit_cost)) == 70
    assert Decimal(str(yangi.remaining_qty)) == 6 and Decimal(str(yangi.received_qty)) == 6
    assert yangi.source_type == "adjustment", "operator narxi hujjat narxidek ko'rinmasin"
    assert _q(pid) == 10.0
    _ok(cid, pid)

    # Javob UI uchun partiya darajasida — operator nima yaratganini KO'RADI.
    row = [x for x in r.json()["results"] if x["product_id"] == pid][0]
    assert row["lots"]["created"] and row["lots"]["created"][0]["batch_no"] == "TOPILDI"
    assert row["lots"]["created"][0]["qty"] == 6.0
    assert row["lots"]["surpluses"] == [], "nusxa yo'li ishlatildi"


def test_SANALMAGAN_partiyalar_TEGILMAY_yangi_partiya_qoʻshiladi(client, admin_headers, ctx, sup):
    """`lots` BO'SH bo'lsa ham yangi partiya e'lon qilish mumkin.

    Bu «javonda boshqa hech narsani sanamadim, faqat yangi qadoq topdim»
    holati — mavjud kogortalar KO'RILMAGAN, demak tegilmaydi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 5, 30, D10)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 8,
        "new_lots": [_new(3, 12, batch="YANGI-1", expiry=D20)]}])
    assert r.status_code == 200, r.text
    erta, kech = _by_expiry(pid)
    assert Decimal(str(erta.remaining_qty)) == 5, "sanalmagan partiya o'zgardi"
    assert kech.batch_no == "YANGI-1" and Decimal(str(kech.remaining_qty)) == 3
    assert _q(pid) == 8.0
    _ok(cid, pid)


def test_YIGʻINDI_yangi_partiya_bilan_ham_MOS_kelishi_shart(client, admin_headers, ctx, sup):
    """`counted` = sanalgan + tegilmagan + YANGI. Mos kelmasa — RAD."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    manba = _lots(pid)[0]
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 12,   # 4 + 6 = 10 ≠ 12
        "lots": [{"stock_batch_id": str(manba.id), "counted": 4}],
        "new_lots": [_new(6, 70, expiry=D30)]}])
    assert r.status_code == 400, r.text
    assert len(_lots(pid)) == 1, "rad etilgan sanoq partiya yaratdi"
    assert _q(pid) == 4.0


def test_MUDDAT_kuzatuvida_yangi_partiya_MUDDATSIZ_boʻlmaydi(client, admin_headers, ctx, sup):
    """Qabul yo'lidagi qoida bilan AYNI — jim qabul qilinsa hisobot ko'rmasdi."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=True)
    _recv(client, admin_headers, sup, pid, 4, 50, D10)
    manba = _lots(pid)[0]
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 6,
        "lots": [{"stock_batch_id": str(manba.id), "counted": 4}],
        "new_lots": [_new(2, 10)]}])
    assert r.status_code == 400, r.text
    assert "MAJBURIY" in r.json()["detail"], r.text
    assert len(_lots(pid)) == 1

    # Muddat kuzatuvi YO'Q mahsulotda muddatsiz partiya — QONUNIY.
    pid2 = _product(client, admin_headers)
    _enable(client, admin_headers, pid2, expiry=False)
    _recv(client, admin_headers, sup, pid2, 4, 50)
    m2 = _lots(pid2)[0]
    r2 = _count(client, admin_headers, [{
        "product_id": pid2, "counted": 6,
        "lots": [{"stock_batch_id": str(m2.id), "counted": 4}],
        "new_lots": [_new(2, 10, batch="MUDDATSIZ")]}])
    assert r2.status_code == 200, r2.text
    assert [l.batch_no for l in _lots(pid2) if l.batch_no] == ["MUDDATSIZ"]


def test_KUZATUVSIZ_mahsulotga_yangi_partiya_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _recv_plain(client, admin_headers, sup, pid, 5, 20)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 7, "new_lots": [_new(2, 10)]}])
    assert r.status_code == 400, r.text
    assert "kuzatuvi yoqilmagan" in r.json()["detail"], r.text


def test_NOTOʻGʻRI_yangi_partiya_qiymatlari_RAD(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    for bad in ({"qty": 0, "unit_cost": 5}, {"qty": -2, "unit_cost": 5},
                {"qty": 2, "unit_cost": -1}):
        r = _count(client, admin_headers, [{"product_id": pid, "counted": 2, "new_lots": [bad]}])
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert _lots(pid) == []


def test_QAYTA_yuborilgan_sanoq_partiyani_IKKI_marta_yaratmaydi(client, admin_headers, ctx, sup):
    """Ikki marta bosish yoki offline qayta yuborish — bitta partiya."""
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    _recv(client, admin_headers, sup, pid, 4, 50)
    manba = _lots(pid)[0]
    body = {"items": [{"product_id": pid, "counted": 9,
                       "lots": [{"stock_batch_id": str(manba.id), "counted": 4}],
                       "new_lots": [_new(5, 11, batch="IDEMP")]}],
            "client_uuid": str(uuid.uuid4())}
    r1 = client.post("/api/v1/inventory/count", headers=admin_headers, json=body)
    r2 = client.post("/api/v1/inventory/count", headers=admin_headers, json=body)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert len(_lots(pid)) == 2, [l.batch_no for l in _lots(pid)]
    assert _q(pid) == 9.0
    _ok(cid, pid)


def test_EʼLON_qilingan_partiya_TUZATISH_deb_koʻrinadi(client, admin_headers, ctx, sup):
    """Manager ro'yxatida u qabuldan kelgan partiyadek KO'RINMASLIGI shart."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 3,
        "new_lots": [_new(3, 25, batch="KO-RINISH", reason="javondan topildi")]}])
    assert r.status_code == 200, r.text

    d = client.get("/api/v1/lots/batches", headers=admin_headers,
                   params={"product_id": pid}).json()
    assert d["total"] == 1, d
    row = d["lots"][0]
    assert row["source_type"] == "adjustment" and row["supplier_id"] is None
    assert row["cost_basis"] == "known" and row["value"] == 75.0
    det = client.get(f"/api/v1/lots/batches/{row['id']}", headers=admin_headers).json()
    assert det["source"]["type"] == "adjustment"
    assert det["source"]["receiving_id"] is None and det["source"]["purchase_item_id"] is None
    # Sanoq harakati tarixda KO'RINADI — partiya qayerdan paydo bo'lgani izlanadi.
    assert det["movements"] and det["movements"][0]["type"] == "adjustment", det["movements"]


def test_OPERATOR_SABABI_audit_jurnalida_qoladi(client, admin_headers, ctx, sup):
    """Yangi partiyada HUJJAT yo'q — sabab yagona tushuntirish, u yo'qolmasin."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    r = _count(client, admin_headers, [{
        "product_id": pid, "counted": 2,
        "new_lots": [_new(2, 10, batch="SABAB-1", reason="javon ortidan chiqdi")]}])
    assert r.status_code == 200, r.text

    from app.models.sync import AuditLog
    with _db() as db:
        rows = [a for a in db.query(AuditLog)
                .filter(AuditLog.entity == "stock_count").all()
                if (a.after or {}).get("product_id") == pid]
        assert rows, "sanoq audit yozuvi yo'q"
        yangi = rows[-1].after["yangi_partiyalar"]
        assert len(yangi) == 1, yangi
        assert yangi[0]["reason"] == "javon ortidan chiqdi", yangi[0]
        assert yangi[0]["batch_no"] == "SABAB-1" and yangi[0]["qty"] == 2.0
