# -*- coding: utf-8 -*-
"""P9 KRITIK TUZATISH 1 — KONTRAKT va ADVERSARIAL CHETLAB O'TISH URINISHLARI.

DOIRA (ega qarori, 2026-09-30):
  · P9-01 (offline idempotentlik kaliti) — TUZATILDI, quyida qulflanadi.
  · P9-02 — Phase 3A ning RATIFIKATSIYA QILINGAN yopiq-smena/LATE_SYNC kontrakti
    SAQLANADI. Ya'ni «yopilgan smenaga kech chek» O'Z-O'ZIDAN nuqson EMAS: u
    3A da ataylab qabul qilinadi va leg sotuvning O'Z smenasiga LATE_SYNC bo'lib
    tushadi (`tests/cash/test_sale_shift_ownership.py`). Bu fayl uni BUZMAYDI.
    Bu yerda faqat 3A ning O'Z niyatidan TASHQARIDAGI atribusiya sinaladi.

KONTRAKT 1 — OFFLINE IDEMPOTENTLIK (`/sync/push`)
  · Har offline chek BARDOSHLI `client_uuid` bilan kelishi SHART.
  · Kalitsiz / nol-UUID / buzuq kalit -> DOIMIY rad (`retry:false`), chek YOZILMAYDI.
  · Server YANGI kalit YARATMAYDI (aks holda retry'lar «boshqa chek» bo'lib ketardi).
  · Ayni kalit takroran kelsa -> BITTA sotuv, BITTA stok chiqimi.
  · Kalit doirasi — KOMPANIYA: boshqa tenantning kaliti bu do'kon savdosini bosmaydi.
  · ONLAYN `/sales` semantikasi O'ZGARMAYDI (kalit u yerda ixtiyoriy).

KONTRAKT 2 — KECH SINXRONLASH ATRIBUSIYASINING CHEGARASI
  · Qonuniy kech chek O'Z smenasiga bog'lanadi (3A) — BU SAQLANADI.
  · Lekin `sold_at` KLIENT qiymati: u smenani TANLAYDI. Tanlov kassir bilan
    chegaralangan (`Shift.cashier_id == emp.id`), FILIAL bilan esa YO'Q.
    Sotuvning filiali `actor_branch` dan (JORIY biriktirilgan filial) keladi,
    smena esa BOSHQA filialniki bo'lishi mumkin — natijada bitta chek ikki
    filialga bo'linadi: stok B dan chiqadi, naqd/custody A ning kassasiga
    yoziladi. 3A ning «leg sotuvning o'z smenasiga tushsin» niyati bu holatni
    NAZARDA TUTMAGAN (uning barcha sinovlari BITTA filialda).

⚠️  PARALLEL YETKAZIB BERISH SQLite'da modellab bo'lmaydi; kafolat baza
    darajasida (`ux_sales_company_client_uuid`). Quyida indeks MAJBURIY
    ro'yxatda ekani tekshiriladi; haqiqiy PG poyga sinovi — PENDING.
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_mobile_parity import _db, _product, _shop, _staff

PUSH = "/api/v1/sync/push"
SALES = "/api/v1/sales"
CODE_KEY = "SYNC_IDEMPOTENCY_KEY_REQUIRED"


def _open_shift(client, H):
    r = client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 0})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _close_shift(client, H, sid):
    r = client.post(f"/api/v1/shifts/{sid}/close", headers=H, json={"counted_cash": 0})
    assert r.status_code == 200, r.text
    return r.json()


def _rec(pid, *, cu="MISSING", qty=1, price=100, sold_at=None):
    r = {"payment_method": "cash", "given_amount": price * qty,
         "items": [{"product_id": str(pid), "qty": qty, "unit_price": price}]}
    if cu != "MISSING":
        r["client_uuid"] = cu
    if sold_at is not None:
        r["sold_at"] = sold_at.isoformat()
    return r


def _push(client, H, rec):
    r = client.post(PUSH, headers=H, json={"sales": [rec]})
    assert r.status_code == 200, r.text          # push HAR DOIM 200; holat results ichida
    return r.json()["results"][0]


def _sales_of(cid):
    from app.models.sales import Sale
    with _db() as db:
        return db.query(Sale).filter(Sale.company_id == cid).all()


def _inv(pid, bid):
    from app.models.inventory import Inventory
    with _db() as db:
        row = db.query(Inventory).filter(
            Inventory.product_id == pid, Inventory.branch_id == bid).first()
        return float(row.qty) if row else None


def _kassir(d, *, filiallar=None):
    return _staff(d, "kassir", filiallar=filiallar or (d["bids"][0],))


def _reassign(eid, bid):
    """Kassirni BOSHQA filialga biriktirish (oddiy administrator amali)."""
    from app.models.auth import EmployeeBranch
    with _db() as db:
        db.query(EmployeeBranch).filter(EmployeeBranch.employee_id == eid).delete()
        db.add(EmployeeBranch(employee_id=eid, branch_id=bid))
        db.commit()


# ══ KONTRAKT 1 — IDEMPOTENTLIK KALITI ════════════════════════════════════════

def test_c1_kalitsiz_chek_DOIMIY_rad_va_stok_TEGILMAYDI(client):
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    res = _push(client, H, _rec(p["id"]))
    assert res["ok"] is False
    assert res["retry"] is False, "kalitsiz chek retry'ga qo'yilsa nuqson ko'payadi"
    assert res["code"] == CODE_KEY
    assert _sales_of(d["cid"]) == []
    assert _inv(p["id"], d["bids"][0]) == 10.0


def test_c2_NOL_uuid_rad_etiladi_va_keyingi_cheklarni_YUTMAYDI(client):
    """Sentinel `00000000-…`: qabul qilinsa birinchi sotuvdan keyin HAMMA chek
    «takror» bo'lib o'sha sotuvni qaytarardi — butun smena savdosi jimgina yutilardi."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    res = _push(client, H, _rec(p["id"], cu=str(uuid.UUID(int=0))))
    assert res["ok"] is False and res["code"] == CODE_KEY
    assert _sales_of(d["cid"]) == []


def test_c3_buzuq_va_bosh_kalit_rad_etiladi(client):
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    for bad in ("", "   ", "not-a-uuid", "123"):
        res = _push(client, H, _rec(p["id"], cu=bad))
        assert res["ok"] is False, f"buzuq kalit qabul qilindi: {bad!r}"
    assert _sales_of(d["cid"]) == []
    assert _inv(p["id"], d["bids"][0]) == 10.0


def test_c4_ayni_kalit_ikki_marta_BITTA_sotuv_BITTA_chiqim(client):
    """Javob yo'qolishi -> qayta yuborish. AYNAN shu kalit qaytadi."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    rec = _rec(p["id"], cu=str(uuid.uuid4()))
    r1 = _push(client, H, rec)
    r2 = _push(client, H, rec)                    # aynan o'sha payload
    assert r1["ok"] is True and r2["ok"] is True
    assert r1["id"] == r2["id"], "takror urinish YANGI sotuv yaratdi"
    assert len(_sales_of(d["cid"])) == 1
    assert _inv(p["id"], d["bids"][0]) == 9.0     # BIR marta


def test_c5_sold_at_ozgarsa_ham_ayni_kalit_YANGI_sotuv_yaratmaydi(client):
    """Chetlab o'tish urinishi: kalit o'sha, faqat `sold_at` boshqa."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    cu = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    r1 = _push(client, H, _rec(p["id"], cu=cu, sold_at=now - timedelta(minutes=5)))
    r2 = _push(client, H, _rec(p["id"], cu=cu, sold_at=now - timedelta(days=3)))
    assert r1["ok"] is True and r2["ok"] is True
    assert r1["id"] == r2["id"]
    assert len(_sales_of(d["cid"])) == 1
    assert _inv(p["id"], d["bids"][0]) == 9.0


def test_c6_kalit_doirasi_KOMPANIYA_begona_tenant_bosmaydi(client):
    """A do'konining kaliti B do'konining HAQIQIY savdosini yutmasligi SHART."""
    dA, dB = _shop(), _shop()
    HA, _ = _kassir(dA)
    HB, _ = _kassir(dB)
    pA = _product(dA, qty=10)
    pB = _product(dB, qty=10)
    cu = str(uuid.uuid4())
    rA = _push(client, HA, _rec(pA["id"], cu=cu))
    rB = _push(client, HB, _rec(pB["id"], cu=cu, qty=3, price=200))
    assert rA["ok"] is True and rB["ok"] is True
    assert rA["id"] != rB["id"], "begona tenant kaliti savdoni bosdi"
    assert _inv(pB["id"], dB["bids"][0]) == 7.0


def test_c7_ONLAYN_sales_semantikasi_OZGARMAYDI(client):
    """Tuzatish FAQAT `/sync/push` ga tegadi: onlayn savdo kalitsiz ham ishlaydi."""
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    r = client.post(SALES, headers=H, json={
        "payment_method": "cash", "given_amount": 100,
        "items": [{"product_id": str(p["id"]), "qty": 1, "unit_price": 100}]})
    assert r.status_code == 200, r.text
    assert _inv(p["id"], d["bids"][0]) == 9.0


def test_c8_baza_darajasidagi_noyoblik_TALAB_royxatida(client):
    """Parallel yetkazishning yakuniy to'sig'i — qisman noyob indeks. U MAJBURIY
    ro'yxatda turishi shart (boot darvozasi uni tekshiradi)."""
    from app.core import required_schema as rs
    names = set()
    for grp in (getattr(rs, "REQUIRED_INDEXES", ()), getattr(rs, "IDEMPOTENCY_INDEXES", ())):
        for item in grp:
            names.add(item[0] if isinstance(item, (tuple, list)) else str(item))
    assert "ux_sales_company_client_uuid" in names, names


# ══ KONTRAKT 2 — 3A SAQLANADI, ATRIBUSIYA CHEGARASI QO'YILADI ════════════════

def test_c9_3A_SAQLANADI_ochiq_smenaga_tarixiy_sold_at_biriktiriladi(client):
    """Regressiya qo'riqchisi: 3A ning tarixiy bog'lash niyati buzilmasin."""
    from app.models.sales import Sale
    from app.models.shifts import Shift
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    sid = _open_shift(client, H)
    with _db() as db:
        after_open = db.get(Shift, uuid.UUID(sid)).opened_at + timedelta(seconds=30)
    cu = uuid.uuid4()
    assert _push(client, H, _rec(p["id"], cu=str(cu), sold_at=after_open))["ok"] is True
    with _db() as db:
        assert str(db.query(Sale).filter(Sale.client_uuid == cu).one().shift_id) == sid


def test_c10_3A_SAQLANADI_yopilgan_OZ_smenasiga_kech_chek_QABUL(client):
    """3A RATIFIKATSIYASI: smena yopilgach kelgan kech chek RAD ETILMAYDI va
    O'Z (yopilgan) smenasiga bog'lanadi. Bu sinov ega qarori bo'yicha shu
    xulqni QULFLAYDI — kelajakdagi «qattiqlashtirish» uni bilmasdan buzmasin."""
    from app.models.sales import Sale
    from app.models.shifts import Shift
    d = _shop()
    H, _ = _kassir(d)
    p = _product(d, qty=10)
    sid = _open_shift(client, H)
    sotilgan = datetime.now(timezone.utc)
    _close_shift(client, H, sid)
    with _db() as db:
        sh = db.get(Shift, uuid.UUID(sid))
        muzlagan = (sh.expected_cash, sh.counted_cash, sh.difference, sh.closed_at)
    cu = uuid.uuid4()
    res = _push(client, H, _rec(p["id"], cu=str(cu), sold_at=sotilgan))
    assert res["ok"] is True, res
    with _db() as db:
        assert str(db.query(Sale).filter(Sale.client_uuid == cu).one().shift_id) == sid
        sh2 = db.get(Shift, uuid.UUID(sid))
        # MUZLATILGAN YARASHTIRISH TEGILMAYDI (3A kafolati).
        assert (sh2.expected_cash, sh2.counted_cash, sh2.difference,
                sh2.closed_at) == muzlagan


def test_c11_kech_chek_BOSHQA_FILIALNING_smenasiga_bogLANMAYDI(client):
    """P9-02 NING TOR YADROSI.

    `sold_at` KLIENT qiymati va u smenani TANLAYDI. Tanlov `cashier_id` bilan
    chegaralangan, FILIAL bilan esa YO'Q. Kassir A filialida smena ochib-yopgan,
    keyin B filialiga o'tkazilgan bo'lsa (yoki ikkala filialga biriktirilgan
    bo'lsa), B da yuborilgan chek `sold_at` orqali A ning smenasiga bog'lanadi:

        sale.branch_id = B  (stok B dan chiqadi)
        sale.shift_id  = A ning smenasi;  sale.till_id = A ning kassasi

    Ya'ni bitta chek IKKI filialga bo'linadi: tovar B dan, pul A ning kassa
    hisobiga. 3A ning «leg sotuvning O'Z smenasiga tushsin» niyati bu holatni
    nazarda tutmagan — uning barcha sinovlari bitta filialda.

    INVARIANT: chekning smenasi chekning FILIALIGA tegishli bo'lishi shart."""
    from app.models.sales import Sale
    from app.models.shifts import Shift
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    H, eid = _kassir(d, filiallar=(A,))
    sid = _open_shift(client, H)                       # smena A filialida
    sotilgan = datetime.now(timezone.utc)
    _close_shift(client, H, sid)
    with _db() as db:
        assert db.get(Shift, uuid.UUID(sid)).branch_id == A

    _reassign(eid, B)                                  # kassir endi B filialida
    p = _product(d, qty=10, bid=B)                     # tovar B filialida
    cu = uuid.uuid4()
    res = _push(client, H, _rec(p["id"], cu=str(cu), sold_at=sotilgan))

    if res["ok"]:
        with _db() as db:
            sale = db.query(Sale).filter(Sale.client_uuid == cu).one()
            sh = db.get(Shift, sale.shift_id) if sale.shift_id else None
        assert sh is None or sh.branch_id == sale.branch_id, (
            f"FILIALLARARO ATRIBUSIYA: sale.branch_id={sale.branch_id} (stok shu "
            f"yerdan chiqdi), sale.shift_id={sale.shift_id} -> smena filiali "
            f"{sh.branch_id}, sale.till_id={sale.till_id} — chek ikki filialga bo'lindi")


def test_c12_filiallararo_rad_etilsa_QISMAN_holat_qolmaydi(client):
    """Agar yuqoridagi holat rad etilsa — izsiz bo'lsin (stok tegilmaydi)."""
    from app.models.shifts import Shift
    d = _shop(filiallar=2)
    A, B = d["bids"][0], d["bids"][1]
    H, eid = _kassir(d, filiallar=(A,))
    sid = _open_shift(client, H)
    sotilgan = datetime.now(timezone.utc)
    _close_shift(client, H, sid)
    _reassign(eid, B)
    p = _product(d, qty=10, bid=B)
    res = _push(client, H, _rec(p["id"], cu=str(uuid.uuid4()), sold_at=sotilgan))
    if not res["ok"]:
        assert _inv(p["id"], B) == 10.0, "rad etilgan chek stokni o'zgartirdi"
        assert _sales_of(d["cid"]) == []
    with _db() as db:                                   # A ning smenasi har holda tegilmagan
        assert db.get(Shift, uuid.UUID(sid)).status.value == "closed"
