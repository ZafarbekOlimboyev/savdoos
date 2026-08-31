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


def test_store_cannot_change_own_plan(client, admin_headers):
    """Do'kon admini tarifni O'ZI o'zgartira olmaydi (403); vendor esa oladi. Boshqa sozlama ishlaydi."""
    r = client.put("/api/v1/settings", headers=admin_headers, json={"key": "plan", "value": {"plan": "business"}})
    assert r.status_code == 403
    ok = client.put("/api/v1/settings", headers=admin_headers, json={"key": "features", "value": {"returns": True}})
    assert ok.status_code == 200


def test_returns_list_oversight(client, admin_headers):
    """Manager nazorati: sotuv -> qaytarish -> GET /returns ro'yxatда ko'rinsin."""
    # Naqд qaytarish endi OCHIQ SMENА talab qiladi (kassа yozувi bo'lsin) — avval smena ochamiz.
    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 100000})
    pid = client.get("/api/v1/products", headers=admin_headers).json()[0]["id"]
    sale = client.post("/api/v1/sales", headers=admin_headers, json={
        "items": [{"product_id": pid, "qty": 2}], "payment_method": "cash", "client_uuid": str(uuid.uuid4())})
    assert sale.status_code == 200, sale.text
    up = sale.json()["items"][0]["unit_price"]
    r = client.post("/api/v1/returns", headers=admin_headers, json={
        "original_sale_id": sale.json()["id"], "reason": "customer", "restock": True, "refund_method": "cash",
        "items": [{"product_id": pid, "qty": 1, "unit_price": up}], "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    lst = client.get("/api/v1/returns?period=all", headers=admin_headers)
    assert lst.status_code == 200, lst.text
    body = lst.json()
    assert body["kpi"]["count"] >= 1
    row = body["returns"][0]
    assert row["return_no"] and row["reason"] == "customer" and row["items"]


def test_shifts_overview_oversight(client, admin_headers):
    """Ega nazorati: /shifts/overview barcha smenalarni qaytaradi (ochiq smena ko'rinsin)."""
    client.post("/api/v1/shifts/open", headers=admin_headers, json={"opening_cash": 100000})
    r = client.get("/api/v1/shifts/overview", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "shifts" in body and "open_count" in body
    assert body["open_count"] >= 1
    opened = [s for s in body["shifts"] if s["status"] == "open"]
    assert opened, "ochiq smena ko'rinishi kerak"
    assert opened[0]["counted"] is None and opened[0]["difference"] is None
    assert opened[0]["expected"] >= 100000 and opened[0]["cashier"]


def test_reports_overview_ok(client, admin_headers):
    r = client.get("/api/v1/reports/overview?period=week", headers=admin_headers)
    assert r.status_code == 200
    assert "kpi" in r.json()


def test_receiving_new_weighted_product_with_plu(client, admin_headers):
    """Kirimda yangi KG mahsulot: PLU+min qoldiq saqlanadi; band PLU 409."""
    r = client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"new_name": "Olma Gala QA", "qty": 12, "unit_cost": 90, "new_sell_price": 130,
                   "unit": "kg", "new_is_weighted": True, "new_plu": "77001", "new_min_qty": 4}],
        "supplier_id": None, "payment": "cash", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r.status_code == 200, r.text
    prods = client.get("/api/v1/products?include_archived=1", headers=admin_headers).json()
    p = next(x for x in prods if x["name"] == "Olma Gala QA")
    assert p["is_weighted"] is True and p["plu_code"] == "77001"
    assert float(p["min_stock"]) == 4.0 and p["unit_code"] == "kg"
    # band PLU bilan ikkinchi mahsulot -> 409
    r2 = client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"new_name": "Nok QA", "qty": 5, "unit_cost": 80, "unit": "kg",
                   "new_is_weighted": True, "new_plu": "77001"}],
        "supplier_id": None, "payment": "cash", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert r2.status_code == 409


def test_guess_category(client, admin_headers):
    """Nomga qarab kategoriya taxmini — mavjud o'xshash mahsulotdan."""
    r = client.get("/api/v1/products/guess-category?name=Coca-Cola 1.5L yangi", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["category_name"] == "Ichimliklar", body
    r2 = client.get("/api/v1/products/guess-category?name=qwzx nomalum", headers=admin_headers)
    assert r2.json()["category_id"] is None


def test_employee_branch_assign(client, admin_headers):
    """Xodim yaratишда filialga biriktirish; ro'yxat/detalда ko'rinishi; tahrirда olib tashlash."""
    branches = client.get("/api/v1/branches", headers=admin_headers).json()["branches"]
    assert branches, "seed'да kamida bitta filial bo'lishi kerak"
    bid, bname = branches[0]["id"], branches[0]["name"]
    phone = f"+99890{uuid.uuid4().int % 10000000:07d}"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": "Filial Xodim", "phone": phone, "role_code": "kassir", "branch_id": bid})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    row = next(e for e in client.get("/api/v1/employees", headers=admin_headers).json() if e["id"] == eid)
    assert row["branch"] == bname
    det = client.get(f"/api/v1/employees/{eid}", headers=admin_headers).json()
    assert det["branch_id"] == bid and det["branch"] == bname
    # tahrir: filialni olib tashlaymiz (branch_id="")
    assert client.patch(f"/api/v1/employees/{eid}", headers=admin_headers, json={"branch_id": ""}).status_code == 200
    row2 = next(e for e in client.get("/api/v1/employees", headers=admin_headers).json() if e["id"] == eid)
    assert row2["branch"] is None


def test_employee_stats_real_sales_chart(client, admin_headers):
    """Xodim statistikasi HAQIQIY 6 oylik savdoни qaytaradi (eski soxta 'hours' emas)."""
    eid = client.get("/api/v1/employees", headers=admin_headers).json()[0]["id"]
    r = client.get(f"/api/v1/employees/{eid}/stats", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "month_sales" in body and "tx" in body
    assert len(body["chart"]) == 6
    assert all("sales" in c and "hours" not in c for c in body["chart"])


def test_credit_refund_tender_cap(client, admin_headers):
    """Round 20 (HIGH): qaytarish usuli SHU chek uchun HAQIQATAN olingan pulga cheklanadi.
    (a) KARTA bilan yopilgan nasiya chekini NAQD qaytarib kassani bo'shatib bo'lmaydi (drain);
    (b) o'sha chekni KARTA bilan qaytarish esa ruxsat etiladi (karta bilan olingan);
    (c) begona nasiya qarzi bor mijozning TO'LIQ NAQD chekini naqd qaytarish BLOKLANMAYDI
        (eski global-balans nasiya guard xatosi)."""
    H = admin_headers
    client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 100000})  # ochiq bo'lsa 400 — ahamiyatsiz
    pid = client.get("/api/v1/products", headers=H).json()[0]["id"]

    # ── Mijoz A: nasiya chek, qarz KARTA bilan yopiladi → NAQD kassaga hech narsa tushmagan ──
    cA = client.post("/api/v1/customers", headers=H, json={"full_name": "R20 Karta Mijoz", "phone": ""})
    assert cA.status_code == 200, cA.text
    cA_id = cA.json()["id"]
    saleA = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1}], "payment_method": "credit",
        "customer_id": cA_id, "client_uuid": str(uuid.uuid4())})
    assert saleA.status_code == 200, saleA.text
    A_id, A_total = saleA.json()["id"], saleA.json()["total"]
    upA = saleA.json()["items"][0]["unit_price"]
    payA = client.post(f"/api/v1/customers/{cA_id}/payments", headers=H,
                       json={"method": "card", "amount": A_total, "client_uuid": str(uuid.uuid4())})
    assert payA.status_code == 200, payA.text
    # NAQD qaytarish — kassaga naqd tushmagani uchun BLOKLANISHI shart (drain himoyasi)
    bad = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": A_id, "reason": "customer", "restock": True, "refund_method": "cash",
        "items": [{"product_id": pid, "qty": 1, "unit_price": upA}], "client_uuid": str(uuid.uuid4())})
    assert bad.status_code == 400, f"Karta bilan yopilgan nasiyani NAQD qaytarish (drain) bloklanmadi: {bad.text}"
    # KARTA qaytarish — ruxsat (qarz karta bilan olingan)
    okc = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": A_id, "reason": "customer", "restock": True, "refund_method": "card",
        "items": [{"product_id": pid, "qty": 1, "unit_price": upA}], "client_uuid": str(uuid.uuid4())})
    assert okc.status_code == 200, f"Karta bilan olingan nasiyani KARTA qaytarish rad etildi: {okc.text}"

    # ── Mijoz B: begona nasiya qarzi bor, LEKIN yangi chek TO'LIQ NAQD ──
    cB = client.post("/api/v1/customers", headers=H, json={"full_name": "R20 Naqd Mijoz", "phone": ""})
    cB_id = cB.json()["id"]
    client.post("/api/v1/sales", headers=H, json={  # begona qarz (nasiya) qoldiradi
        "items": [{"product_id": pid, "qty": 1}], "payment_method": "credit",
        "customer_id": cB_id, "client_uuid": str(uuid.uuid4())})
    saleB = client.post("/api/v1/sales", headers=H, json={  # TO'LIQ NAQD chek shu mijozga
        "items": [{"product_id": pid, "qty": 1}], "payment_method": "cash",
        "customer_id": cB_id, "client_uuid": str(uuid.uuid4())})
    assert saleB.status_code == 200, saleB.text
    B_id = saleB.json()["id"]
    upB = saleB.json()["items"][0]["unit_price"]
    # NAQD qaytarish — begona qarzga QARAMASDAN ruxsat etilishi shart (naqd chek naqd qaytadi)
    okb = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": B_id, "reason": "customer", "restock": True, "refund_method": "cash",
        "items": [{"product_id": pid, "qty": 1, "unit_price": upB}], "client_uuid": str(uuid.uuid4())})
    assert okb.status_code == 200, f"Naqd chekni naqd qaytarish begona qarz tufayli xato bloklandi: {okb.text}"


def test_credit_refund_multisale_drain(client, admin_headers):
    """Round 21 (HIGH): CustomerPayment sale'ga bog'lanmagan — bir mijozning naqd-to'lov pooli
    HAR nasiya chekida qayta ishlatilib kassa drain bo'lmasin. Mijoz 2 to'liq-nasiya chek oladi,
    faqat BITTA chek qiymatini naqd to'laydi; A'ni naqd qaytarish ruxsat, B'ni naqd qaytarish esa
    (pool tugagani uchun) BLOKLANISHI shart. Global netting to'g'ri ishlashini isbotlaydi."""
    H = admin_headers
    client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 100000})
    pid = client.get("/api/v1/products", headers=H).json()[0]["id"]
    c = client.post("/api/v1/customers", headers=H, json={"full_name": "R21 Ko'p-chek Mijoz", "phone": ""})
    assert c.status_code == 200, c.text
    c_id = c.json()["id"]
    # Ikki to'liq-nasiya chek (A, B) — har biri qty=1
    A = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1}], "payment_method": "credit",
        "customer_id": c_id, "client_uuid": str(uuid.uuid4())})
    B = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1}], "payment_method": "credit",
        "customer_id": c_id, "client_uuid": str(uuid.uuid4())})
    assert A.status_code == 200 and B.status_code == 200, (A.text, B.text)
    A_id, upA = A.json()["id"], A.json()["items"][0]["unit_price"]
    B_id, upB = B.json()["id"], B.json()["items"][0]["unit_price"]
    T = A.json()["total"]  # bitta chek qiymati
    # Mijoz FAQAT bitta chek qiymatini (T) naqd to'laydi — hali qarzdor
    pay = client.post(f"/api/v1/customers/{c_id}/payments", headers=H,
                      json={"method": "cash", "amount": T, "client_uuid": str(uuid.uuid4())})
    assert pay.status_code == 200, pay.text
    # A'ni naqd qaytarish — RUXSAT (T naqd olingan)
    rA = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": A_id, "reason": "customer", "restock": True, "refund_method": "cash",
        "items": [{"product_id": pid, "qty": 1, "unit_price": upA}], "client_uuid": str(uuid.uuid4())})
    assert rA.status_code == 200, f"To'langan chekni naqd qaytarish rad etildi: {rA.text}"
    # B'ni naqd qaytarish — BLOKLANISHI shart (pool A'ga ishlatildi; mijoz jami faqat T naqd to'lagan)
    rB = client.post("/api/v1/returns", headers=H, json={
        "original_sale_id": B_id, "reason": "customer", "restock": True, "refund_method": "cash",
        "items": [{"product_id": pid, "qty": 1, "unit_price": upB}], "client_uuid": str(uuid.uuid4())})
    assert rB.status_code == 400, f"Ko'p-chek naqd DRAIN bloklanmadi (pool qayta ishlatildi): {rB.text}"


def test_admin_password_reset_revokes_old_token(client, admin_headers):
    """Round 22 (MEDIUM): admin xodim parolini tiklaganda sec_epoch oshadi -> eski token darhol bekor."""
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": "R22 Token Xodim", "phone": phone, "password": "parol123", "role_code": "kassir"})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": "parol123"})
    assert lg.status_code == 200, lg.text
    tok = {"Authorization": f"Bearer {lg.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 200  # token ishlayapti
    up = client.patch(f"/api/v1/employees/{eid}", headers=admin_headers, json={"password": "yangi123"})
    assert up.status_code == 200, up.text
    # Eski token endi bekor bo'lishi shart (sec_epoch oshdi)
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401, "Parol tiklangach eski token hali ishlayapti"


def test_writeoff_idempotent(client, admin_headers):
    """Round 22 (HIGH): bir xil client_uuid bilan takror writeoff qoldiqni IKKI marta kamaytirmasin."""
    client.post("/api/v1/receiving/commit", headers=admin_headers, json={
        "items": [{"product_id": client.get("/api/v1/products", headers=admin_headers).json()[0]["id"],
                   "qty": 20, "unit_cost": 100, "unit": "dona"}],
        "supplier_id": None, "payment": "cash", "client_uuid": str(uuid.uuid4()), "source": "manual"})
    pid = client.get("/api/v1/products", headers=admin_headers).json()[0]["id"]
    cu = str(uuid.uuid4())
    w1 = client.post("/api/v1/inventory/writeoff", headers=admin_headers,
                     json={"product_id": pid, "qty": 3, "reason": "brak", "client_uuid": cu})
    assert w1.status_code == 200, w1.text
    q_after = w1.json()["new_qty"]
    w2 = client.post("/api/v1/inventory/writeoff", headers=admin_headers,
                     json={"product_id": pid, "qty": 3, "reason": "brak", "client_uuid": cu})
    assert w2.status_code == 200 and w2.json().get("duplicate") is True, f"Takror writeoff dedup ishlamadi: {w2.text}"
    # Qoldiq faqat BIR marta kamaygan bo'lishi kerak
    ov = client.get("/api/v1/inventory/overview", headers=admin_headers).json()
    row = next((x for x in ov.get("items", ov if isinstance(ov, list) else []) if str(x.get("product_id")) == pid), None)
    if row is not None:
        assert abs(float(row.get("qty", q_after)) - q_after) < 0.001, "Takror writeoff qoldiqni 2x kamaytirdi"
