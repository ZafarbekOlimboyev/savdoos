# -*- coding: utf-8 -*-
"""PHASE 3.5 (5-band) — 1C TARIX IMPORTI VA TANNARX ASOSI.

⚠️  O'LCHANGAN NUQSON. `/reports/history/seed` `Sale.cost_total` ga
    `tushum × 0.77` ni yozardi. Phase 2.5 dan beri o'sha ustun ANIQ,
    partiyadan olingan tannarx degan ma'noni oldi — ya'ni TO'QIB CHIQARILGAN
    taxmin hisobotlarda ANIQ tannarx bo'lib ko'rinardi va uni ajratishning
    HECH QANDAY yo'li yo'q edi.

⚠️  ENDPOINTNI HECH KIM CHAQIRMAYDI. Butun repo bo'yicha tekshirildi: na
    `apps/pos`, na `apps/manager`, na `packages/shared`, na skriptlar. U bir
    martalik qo'lda import uchun qolgan. Shu bois to'g'ri yechim uni
    o'chirish emas, TAXMIN QILISHDAN TO'XTATISH:

        ratio berilmasa  -> `cost_basis="unknown"` (tannarx TAXMIN QILINMAYDI)
        ratio berilsa    -> `cost_basis="estimated"` ANIQ e'lon qilinishi SHART

    Hisobot esa taxminiy ulushni ALOHIDA ko'rsatadi — yig'indini o'zgartirmay.
"""
import uuid

import pytest

from app.models.sales import (COST_BASIS_ESTIMATED, COST_BASIS_UNKNOWN, Sale)


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _seed(client, headers, rows, **kw):
    return client.post("/api/v1/reports/history/seed", headers=headers,
                       json={"rows": rows, **kw})


def _row(no, rev="500000"):
    return {"date": "12.01.2026 15:24:07", "revenue": float(rev), "no": no}


def _sale(no):
    with _db() as db:
        return db.query(Sale).filter(Sale.receipt_no == f"H{no}").first()


# ══ 1. SERVER O'ZI TAXMIN QILMAYDI ══════════════════════════════════════════

def test_RATIOSIZ_import_tannarxni_UMUMAN_yozmaydi(client, admin_headers):
    """⚠️  Ilgari `cost_ratio` standarti 0.77 edi — chaqiruvchi hech narsa
        demasa ham server tannarx TO'QIB chiqarardi."""
    no = "NOCOST" + uuid.uuid4().hex[:6].upper()
    r = _seed(client, admin_headers, [_row(no)])
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1, r.json()
    s = _sale(no)
    assert s is not None
    assert s.cost_basis == COST_BASIS_UNKNOWN, "tannarx asosi belgilanmadi"
    # ⚠️  `cost_total` 0 bo'lib qoladi (ustunda `default=0`), lekin u endi
    #     «nol tannarx» EMAS — `cost_basis` uni NOMA'LUM deb e'lon qiladi.
    assert float(s.cost_total or 0) == 0.0


def test_RATIO_berilsa_ASOS_e_LON_qilinishi_SHART(client, admin_headers):
    no = "NEEDBASIS" + uuid.uuid4().hex[:6].upper()
    r = _seed(client, admin_headers, [_row(no)], cost_ratio=0.77)
    assert r.status_code == 400, r.text
    assert "estimated" in r.json()["detail"]
    assert _sale(no) is None, "rad etilgan import qator yozdi"


def test_ASOS_ratiosiz_berilsa_RAD(client, admin_headers):
    no = "BASISONLY" + uuid.uuid4().hex[:6].upper()
    r = _seed(client, admin_headers, [_row(no)], cost_basis=COST_BASIS_ESTIMATED)
    assert r.status_code == 400, r.text
    assert _sale(no) is None


def test_OSHKORA_taxmin_QABUL_qilinadi_va_BELGILANADI(client, admin_headers):
    no = "MARKED" + uuid.uuid4().hex[:6].upper()
    r = _seed(client, admin_headers, [_row(no, "1000000")],
              cost_ratio=0.77, cost_basis=COST_BASIS_ESTIMATED)
    assert r.status_code == 200, r.text
    s = _sale(no)
    assert float(s.cost_total) == 770000.0, s.cost_total
    assert s.cost_basis == COST_BASIS_ESTIMATED, "taxmin BELGILANMADI"


# ══ 2. HAQIQIY SOTUV BELGILANMAYDI ══════════════════════════════════════════

def test_HAQIQIY_sotuv_cost_basis_i_BOSH_qoladi(client, admin_headers):
    """⚠️  Ustun «ANIQ» deb DA'VO QILMAYDI. Kuzatuvsiz mahsulotning tannarxi
        ham partiyadan kelmaydi — uni 'exact' deb belgilash YANGI yolg'on
        bo'lardi. Ustun FAQAT «bu qator taxmin» degan faktni tashiydi.
    """
    pid = client.post("/api/v1/products/bulk", headers=admin_headers, json={"items": [
        {"name": "Asos sinov " + uuid.uuid4().hex[:6], "sell_price": 100,
         "buy_price": 50, "unit_code": "dona", "stock": 10}]}).json()[0]["id"]
    r = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 1000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    with _db() as db:
        s = db.get(Sale, uuid.UUID(r.json()["id"]))
        assert s.cost_basis is None
        assert s.cost_total is not None


# ══ 3. HISOBOT ANIQ VA TAXMINIYNI AJRATADI ══════════════════════════════════

def test_PNL_taxminiy_ulushni_ALOHIDA_koersatadi(client, admin_headers):
    """Yig'indi o'zgarmaydi — lekin o'quvchi qaysi qismga ishonishni biladi."""
    no = "PNL" + uuid.uuid4().hex[:6].upper()
    before = client.get("/api/v1/reports/pnl?period=month",
                        headers=admin_headers).json()
    assert "cogs_estimated" in before, before
    assert "revenue_cost_unknown" in before
    r = _seed(client, admin_headers,
              [{"date": "12.09.2026 10:00:00", "revenue": 1000000.0, "no": no}],
              cost_ratio=0.5, cost_basis=COST_BASIS_ESTIMATED)
    assert r.status_code == 200, r.text
    after = client.get("/api/v1/reports/pnl?period=month",
                       headers=admin_headers).json()
    assert after["cogs_estimated"] - before["cogs_estimated"] == 500000.0, (
        before["cogs_estimated"], after["cogs_estimated"])
    # Taxminiy ulush umumiy COGS ICHIDA — ikki marta sanalmaydi.
    assert after["cogs"] - before["cogs"] == 500000.0


def test_PNL_tannarxi_NOMALUM_tushumni_KOERSATADI(client, admin_headers):
    """Tannarxsiz tushum «nol tannarxli savdo» bo'lib ko'rinmasin."""
    no = "UNK" + uuid.uuid4().hex[:6].upper()
    before = client.get("/api/v1/reports/pnl?period=month",
                        headers=admin_headers).json()
    r = _seed(client, admin_headers,
              [{"date": "12.09.2026 11:00:00", "revenue": 400000.0, "no": no}])
    assert r.status_code == 200, r.text
    after = client.get("/api/v1/reports/pnl?period=month",
                       headers=admin_headers).json()
    assert after["revenue_cost_unknown"] - before["revenue_cost_unknown"] == 400000.0
    assert after["cogs"] == before["cogs"], "NOMA'LUM tannarx COGS'ga qo'shildi"


# ══ 4. IDEMPOTENTLIK VA SXEMA ═══════════════════════════════════════════════

def test_IMPORT_IDEMPOTENT(client, admin_headers):
    no = "IDEM" + uuid.uuid4().hex[:6].upper()
    body = {"rows": [_row(no)], }
    r1 = client.post("/api/v1/reports/history/seed", headers=admin_headers, json=body)
    r2 = client.post("/api/v1/reports/history/seed", headers=admin_headers, json=body)
    assert r1.json()["added"] == 1 and r2.json()["added"] == 0, (r1.json(), r2.json())
    with _db() as db:
        assert db.query(Sale).filter(Sale.receipt_no == f"H{no}").count() == 1


def test_COST_BASIS_majburiy_sxemada_va_MIGRATSIYA_tuzata_oladi():
    from app.core import required_schema as rs
    from app.initdb import _ADDED_COLUMNS
    assert ("sales", "cost_basis") in rs.REQUIRED_COLUMNS
    assert ("sales", "cost_basis") in {(t, c) for t, c, _ in _ADDED_COLUMNS}
