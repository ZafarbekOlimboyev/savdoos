"""Asosiy biznes-oqim regressiya testlari — kirim (receiving) commit + tahrir.

test_receiving_commit_with_barcode: 2026-avgustда 'ProductBarcode importi yo'q' bug'i
kirimни butunlay buzган (500). Bu test shu regressiyани qaytadan ushlaydi.
"""
import uuid


def _first_products(client, admin_headers, n=2):
    return [p["id"] for p in client.get("/api/v1/products", headers=admin_headers).json()[:n]]


def test_receiving_commit_with_barcode(client, admin_headers):
    """new_barcode berilgan kirim — ProductBarcode import regressiyasi (500 bermasin)."""
    pid = _first_products(client, admin_headers, 1)[0]
    r = client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"product_id": pid, "new_barcode": "9990001112223", "qty": 5,
                   "unit_cost": 100, "new_sell_price": 150, "unit": "dona"}],
        "supplier_id": None, "payment": "cash", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True


def test_receiving_edit_reconciles(client, admin_headers):
    """Kirim tahriri: qty kamaytirilса — jami va ombor mos ravishда to'g'rilanadi."""
    p1, p2 = _first_products(client, admin_headers, 2)
    sup = client.get("/api/v1/suppliers", headers=admin_headers).json()[0]["id"]
    client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"product_id": p1, "qty": 10, "unit_cost": 100, "unit": "dona"},
                  {"product_id": p2, "qty": 5, "unit_cost": 200, "unit": "dona"}],
        "supplier_id": sup, "payment": "credit", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    purchases = client.get("/api/v1/purchases", headers=admin_headers).json()
    pid = purchases[0]["id"]
    det = client.get(f"/api/v1/purchases/{pid}", headers=admin_headers).json()
    assert det["total"] == 2000.0
    it1 = next(i for i in det["items"] if i["product_id"] == p1)
    # qty 10 -> 4, ikkinchi qatorни o'chiramiz
    it2 = next(i for i in det["items"] if i["product_id"] == p2)
    r = client.patch(f"/api/v1/purchases/{pid}", headers=admin_headers, json={
        "items": [{"id": it1["id"], "qty": 4, "unit_cost": 100}], "removed": [it2["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 400.0


def test_reports_overview_ok(client, admin_headers):
    r = client.get("/api/v1/reports/overview?period=week", headers=admin_headers)
    assert r.status_code == 200
    assert "kpi" in r.json()
