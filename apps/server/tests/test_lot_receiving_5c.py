# -*- coding: utf-8 -*-
"""PHASE 5C (B2) — KIRIM UI PARTIYA YUBORA OLSIN: server tomonidagi darvozalar.

Kirim ekrani (Manager «Yangi kirim» va «Rasm orqali kirim») endi kuzatuvli
mahsulotga `lots` yuboradi. UI ishonchli bo'lishi uchun SERVER bir nechta
jimlikni yopishi kerak edi:

  1. MIQDOR ANIQLIGI. Qator miqdori `Inventory.qty` ga XOM qo'shiladi
     (Postgres NUMERIC(14,3) — YARIM-YUQORIGA yaxlitlaydi), partiya esa
     `lot_receiving._q` orqali o'tardi (ilgari YARIM-JUFTGA). 1.2345 da ikki yo'l
     ikki xil son berardi — SQLite buni YASHIRADI, Postgres esa kirimni yakuniy
     invariant darvozasida 409 bilan yiqitardi. Endi: uchtadan ortiq kasr xonasi
     ANIQ 400 bilan rad etiladi va `_q` ham YARIM-YUQORIGA yaxlitlaydi (FEFO,
     hisobdan chiqarish, qarzni yopish va frontend `lots.ts:q3` bilan AYNI).
  2. PARTIYALAR SONI. `lots` ro'yxati cheksiz edi.
  3. XARID TAHRIRIDA NARX. Miqdor o'zgarishi allaqachon 409 olardi, FAQAT narx
     o'zgarishi esa delta=0 bo'lgani uchun darvozagacha yetmasdi: hujjat narxi
     yangilanib, partiya tannarxi ESKI qolardi.
  4. `GET /purchases/{id}` qatorlarida partiya bayrog'i — UI qulflay olsin.
  5. TAKROR `client_uuid` — boshqa payload bilan ham TAHRIR EMAS (bugungi xulq
     ATAYLAB shunday; test uni MIXLAB qo'yadi, chunki UI shunga tayanadi).

Har yangi qoida uchun MANFIY NAZORAT bor: qoida olib tashlansa (yoki eski kodga
qaytarilsa) mos test QIZIL bo'ladi.
"""
import uuid
from decimal import Decimal

import pytest

from app.models.inventory import StockBatch, StockMovement
from app.models.purchasing import Purchase, PurchaseItem
from app.models.receiving import Receiving
from app.services import lot_receiving as LR

from tests.test_lot_receiving import (  # noqa: F401
    _commit,
    _db,
    _enable,
    _inv_qty,
    _lots,
    _new_product,
    ctx,
)

KASR_QATOR = ("'{nom}': qator miqdori {q} da uchtadan ORTIQ kasr xonasi bor — miqdor "
              "0.001 aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi.")
KASR_PARTIYA = ("'{nom}': partiya miqdori {q} da uchtadan ORTIQ kasr xonasi bor — miqdor "
                "0.001 aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi.")
#  ⚠️  MASLAHAT BAJARILADIGAN BO'LSIN (Phase 5C review, C-2): «kirimni bekor qiling»
#      degan eski matn operatorni IKKINCHI rad javobiga olib borardi — kuzatuvli qatorni
#      o'chirish ham shu endpointda `stock_gate` bilan 409 oladi.
NARX_DARVOZA = ("'{nom}' partiya bo'yicha kuzatiladi — kirim narxini tahrirlab bo'lmaydi: "
                "partiya tannarxi qabul paytida yozilgan va hujjat bilan jimgina ajralib "
                "qolardi. Kuzatuvli hujjat hozircha bekor ham qilinmaydi — tuzatish uchun "
                "qo'llab-quvvatlashga murojaat qiling.")


def _nom(pid):
    from app.models.catalog import Product
    with _db() as db:
        return db.get(Product, uuid.UUID(str(pid))).name


def _holat(pid, bid):
    """Qoldiq + partiyalar + hujjatlar soni — «hech narsa yozilmadi» ni o'lchash uchun."""
    with _db() as db:
        lots = sorted((str(b.batch_no), str(b.remaining_qty), str(b.unit_cost))
                      for b in db.query(StockBatch).filter(
                          StockBatch.product_id == uuid.UUID(str(pid))).all())
        return {
            "inv": str(_inv_qty(pid, bid)),
            "lots": lots,
            "harakat": db.query(StockMovement).filter(
                StockMovement.product_id == uuid.UUID(str(pid))).count(),
            "xarid": db.query(Purchase).count(),
            "qabul": db.query(Receiving).count(),
        }


# ══ 1. MIQDOR ANIQLIGI ═══════════════════════════════════════════════════════

def test_KUZATUVLI_qatorda_TORT_kasr_400_va_HECH_NARSA_yozilmaydi(client, admin_headers, ctx):
    """ESKI KODDA (HALF_EVEN, darvozasiz) bu kirim 200 qaytarardi va SQLite'da
    qoldiq/partiya bir xil ko'rinardi — Postgres'da esa 1.235 va 1.234."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    oldin = _holat(pid, bid)

    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 1.2345, "unit_cost": 700,
                                         "unit": "kg", "lots": [{"qty": 1.2345}]}])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == KASR_QATOR.format(nom=_nom(pid), q="1.2345"), r.text
    assert _holat(pid, bid) == oldin, "rad etilgan kirim IZ qoldirdi"

    # NAZORAT: AYNI kirim UCH kasr bilan o'tadi va qoldiq partiyaga TENG.
    r2 = _commit(client, admin_headers, [{"product_id": pid, "qty": 1.234, "unit_cost": 700,
                                          "unit": "kg", "lots": [{"qty": 1.234}]}])
    assert r2.status_code == 200, r2.text
    assert _inv_qty(pid, bid) == Decimal("1.234")
    assert sum(Decimal(str(b.remaining_qty)) for b in _lots(pid)) == Decimal("1.234")


def test_PARTIYA_miqdorida_TORT_kasr_400(client, admin_headers, ctx):
    """ESKI KODDA 0.5004 + 0.4996 yarim-juftga 0.500 + 0.500 bo'lib yig'indi 1.000 ga
    TENG chiqardi va kirim 200 bilan o'tardi — partiyalar esa 0.0004/0.0004 ga
    JIMGINA siljigan bo'lardi."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    oldin = _holat(pid, bid)

    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 1, "unit_cost": 700,
                                         "unit": "kg",
                                         "lots": [{"qty": 0.5004}, {"qty": 0.4996}]}])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == KASR_PARTIYA.format(nom=_nom(pid), q="0.5004"), r.text
    assert _holat(pid, bid) == oldin, "rad etilgan kirim IZ qoldirdi"

    # NAZORAT: uch xonali bo'linma o'tadi (0.1 + 0.9 emas — aynan kasr bo'linish).
    r2 = _commit(client, admin_headers, [{"product_id": pid, "qty": 1.235, "unit_cost": 700,
                                          "unit": "kg",
                                          "lots": [{"qty": 0.617}, {"qty": 0.618}]}])
    assert r2.status_code == 200, r2.text
    assert _inv_qty(pid, bid) == Decimal("1.235")


def test_KUZATUVSIZ_qatorda_TORT_kasr_AVVALGIDEK_OTADI(client, admin_headers, ctx):
    """MANFIY NAZORAT: darvoza FAQAT kuzatuvli qatorga tegadi — kuzatuvsiz kirim
    (bugungi do'konning 100% i) bir zarracha ham o'zgarmaydi."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 1.2345, "unit_cost": 700,
                                         "unit": "kg"}])
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["added"] == 1.2345
    assert len(_lots(pid)) == 0, "kuzatuvsiz mahsulotda partiya paydo bo'ldi"


def test_q_YARIM_YUQORIGA_yaxlitlaydi_boshqa_yollar_bilan_AYNI():
    """`lot_receiving._q` butun tizimdagi YAGONA yarim-juft joyi edi.

    ESKI KODDA: _q('1.2345') == 1.234 (yarim-juft) — bu yerda QIZIL.
    """
    from app.services import lot_fefo as LF
    from app.services import lot_resolution as LRes
    from app.services import lot_writeoff as LW
    for v in ("1.2345", "0.0005", "0.5005", "1.2355", "2.5005", "0.1235"):
        assert LR._q(v) == LF._q(v) == LW._d(v) == LRes.q3(v), v
    assert LR._q("1.2345") == Decimal("1.235")
    assert LR._q("0.0005") == Decimal("0.001")
    # `_uch_xona` — darvozaning o'zi: chegara 3 xona (trailing nol xona EMAS).
    assert LR._uch_xona("1.234") and LR._uch_xona("1.2340") and LR._uch_xona(5)
    assert not LR._uch_xona("1.2345") and not LR._uch_xona("0.0005")


# ══ 2. PARTIYALAR SONI ═══════════════════════════════════════════════════════

def test_bir_qatorda_51_partiya_RAD_50_tasi_OTADI(client, admin_headers, ctx):
    """ESKI KODDA chegara YO'Q edi — 51 ta ham (mingtasi ham) o'tardi."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200

    r = _commit(client, admin_headers, [{"product_id": pid, "qty": 51, "unit_cost": 700,
                                         "unit": "dona", "lots": [{"qty": 1}] * 51}])
    assert r.status_code == 422, r.text
    assert "at most 50" in r.text
    assert len(_lots(pid)) == 0

    r2 = _commit(client, admin_headers, [{"product_id": pid, "qty": 50, "unit_cost": 700,
                                          "unit": "dona", "lots": [{"qty": 1}] * 50}])
    assert r2.status_code == 200, r2.text
    assert len(_lots(pid)) == 50
    assert _inv_qty(pid, bid) == Decimal("50.000")


# ══ 3. XARID TAHRIRI — KUZATUVLI QATORDA NARX ════════════════════════════════

def _kirim_xaridi(client, admin_headers, pid, qty=5, cost=700, lots=None):
    r = _commit(client, admin_headers, [{"product_id": pid, "qty": qty, "unit_cost": cost,
                                         "unit": "dona",
                                         **({"lots": lots} if lots is not None else {})}])
    assert r.status_code == 200, r.text
    return r.json()["purchase_id"]


def test_KUZATUVLI_qatorda_FAQAT_NARX_tahriri_409_va_TANNARX_QIMIRLAMAYDI(
        client, admin_headers, ctx):
    """ESKI KODDA bu 200 qaytarardi: `PurchaseItem.unit_cost` 250 bo'lib,
    `StockBatch.unit_cost` 700 qolardi — bir hujjat, ikki xil tannarx."""
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    pur_id = _kirim_xaridi(client, admin_headers, pid, lots=[{"qty": 5}])
    det = client.get(f"/api/v1/purchases/{pur_id}", headers=admin_headers).json()
    it = det["items"][0]

    r = client.patch(f"/api/v1/purchases/{pur_id}", headers=admin_headers, json={
        "items": [{"id": it["id"], "qty": it["qty"], "unit_cost": 250}]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == NARX_DARVOZA.format(nom=_nom(pid)), r.text
    with _db() as db:
        assert Decimal(str(db.query(PurchaseItem).filter(
            PurchaseItem.id == uuid.UUID(it["id"])).one().unit_cost)) == Decimal("700.00")
    assert Decimal(str(_lots(pid)[0].unit_cost)) == Decimal("700.00")

    # NAZORAT 1: narx TEGILMASA (faqat sotish narxi) tahrir o'tadi.
    ok = client.patch(f"/api/v1/purchases/{pur_id}", headers=admin_headers, json={
        "items": [{"id": it["id"], "qty": it["qty"], "unit_cost": it["unit_cost"],
                   "sell_price": 1500}]})
    assert ok.status_code == 200, ok.text


def test_KUZATUVSIZ_qatorda_NARX_tahriri_AVVALGIDEK_OTADI(client, admin_headers, ctx):
    """MANFIY NAZORAT: darvoza kuzatuvsiz xaridga TEGMAYDI."""
    pid = _new_product(client, admin_headers)
    pur_id = _kirim_xaridi(client, admin_headers, pid)
    det = client.get(f"/api/v1/purchases/{pur_id}", headers=admin_headers).json()
    it = det["items"][0]
    r = client.patch(f"/api/v1/purchases/{pur_id}", headers=admin_headers, json={
        "items": [{"id": it["id"], "qty": it["qty"], "unit_cost": 250}]})
    assert r.status_code == 200, r.text
    with _db() as db:
        assert Decimal(str(db.query(PurchaseItem).filter(
            PurchaseItem.id == uuid.UUID(it["id"])).one().unit_cost)) == Decimal("250.00")


def test_XARID_TAFSILOTIDA_partiya_bayroqlari_BOR(client, admin_headers, ctx):
    """UI kuzatuvli qatorni QULFLASHI uchun bayroq javobda bo'lishi shart."""
    client.post("/api/v1/lots/timezone/confirm", headers=admin_headers, json={})
    tracked = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, tracked, track_expiry=True).status_code == 200
    plain = _new_product(client, admin_headers)
    from datetime import date, timedelta
    muddat = (date.today() + timedelta(days=120)).isoformat()
    r = _commit(client, admin_headers, [
        {"product_id": tracked, "qty": 3, "unit_cost": 700, "unit": "dona",
         "lots": [{"qty": 3, "expiry_date": muddat}]},
        {"product_id": plain, "qty": 2, "unit_cost": 500, "unit": "dona"},
    ])
    assert r.status_code == 200, r.text
    det = client.get(f"/api/v1/purchases/{r.json()['purchase_id']}", headers=admin_headers).json()
    bayroq = {i["product_id"]: (i["track_lots"], i["track_expiry"]) for i in det["items"]}
    assert bayroq[tracked] == (True, True)
    assert bayroq[plain] == (False, False)


def test_NARX_darvozasi_matni_LUGATDA_BOR():
    """Xato matni `serverErrorsLots.ts` da bo'lmasa, kirillcha do'kon egasi
    lotin-o'zbekcha texnik matn ko'rardi (`purchases.py` drift ro'yxatida emas)."""
    from tests.test_lot_error_texts import _covered, _dicts
    static, dyn = _dicts()
    assert _covered(NARX_DARVOZA.format(nom="7"), static, dyn), NARX_DARVOZA


# ══ 4. RUXSAT ════════════════════════════════════════════════════════════════

_XODIM: dict = {}


def _staff(client, admin_headers, role):
    """ROL BO'YICHA BITTA xodim, fayl bo'yi (demo tarifi — 10 foydalanuvchi)."""
    if role in _XODIM:
        return {"Authorization": _XODIM[role]["h"]}
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    pw = "Toshkent-Kuz-2026"
    r = client.post("/api/v1/employees", headers=admin_headers, json={
        "full_name": f"5C {role}", "phone": phone, "password": pw, "role_code": role})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": pw})
    assert lg.status_code == 200, lg.text
    _XODIM[role] = {"h": f"Bearer {lg.json()['access_token']}", "id": r.json()["id"]}
    return {"Authorization": _XODIM[role]["h"]}


@pytest.fixture(scope="module", autouse=True)
def _xodimlarni_tozalash(client):
    yield
    import contextlib
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": "+998901234567", "password": "demo1234"})
    if r.status_code != 200:
        return
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for v in _XODIM.values():
        with contextlib.suppress(Exception):
            client.delete(f"/api/v1/employees/{v['id']}", headers=h)
    _XODIM.clear()


@pytest.mark.parametrize("role", ["kassir", "menejer"])
def test_XARIDLAR_EDIT_siz_kirim_403_va_OMBOR_tegilmaydi(client, admin_headers, ctx, role):
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    oldin = _holat(pid, bid)
    r = _commit(client, _staff(client, admin_headers, role),
                [{"product_id": pid, "qty": 4, "unit_cost": 700, "unit": "dona",
                  "lots": [{"qty": 4}]}])
    assert r.status_code == 403, r.text
    assert _holat(pid, bid) == oldin, f"{role} ruxsatsiz kirim yozdi"


def test_OMBORCHI_partiyali_kirimni_BAJARADI(client, admin_headers, ctx):
    """NAZORAT: 403 ruxsatdan keladi, kirim yo'lining o'zi yopiq emas."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    r = _commit(client, _staff(client, admin_headers, "omborchi"),
                [{"product_id": pid, "qty": 4, "unit_cost": 700, "unit": "dona",
                  "lots": [{"qty": 4}]}])
    assert r.status_code == 200, r.text
    assert _inv_qty(pid, bid) == Decimal("4.000")
    assert len(_lots(pid)) == 1


# ══ 5. ARALASH HUJJAT VA TAKROR ══════════════════════════════════════════════

def test_ARALASH_hujjatda_BITTA_yomon_qator_BUTUN_hujjatni_qaytaradi(client, admin_headers, ctx):
    """UI shu bois hujjatni yuborishdan OLDIN har kuzatuvli qatorni tekshiradi:
    bitta xato butun hujjatni (kuzatuvsiz qatorlari bilan birga) rad etadi."""
    _cid, bid = ctx
    plain = _new_product(client, admin_headers)
    tracked = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, tracked).status_code == 200
    _commit(client, admin_headers, [{"product_id": plain, "qty": 6, "unit_cost": 500,
                                     "unit": "dona"}])          # boshlang'ich qoldiq
    oldin_plain = _holat(plain, bid)
    oldin_tracked = _holat(tracked, bid)

    r = _commit(client, admin_headers, [
        {"product_id": plain, "qty": 3, "unit_cost": 500, "unit": "dona"},
        {"product_id": tracked, "qty": 10, "unit_cost": 700, "unit": "dona",
         "lots": [{"qty": 4}, {"qty": 5}]},                      # yig'indi 9 ≠ 10
    ])
    assert r.status_code == 400, r.text
    assert "TENG EMAS" in r.json()["detail"]
    assert _holat(plain, bid) == oldin_plain, "yomon qator KUZATUVSIZ qatorni yozib yubordi"
    assert _holat(tracked, bid) == oldin_tracked


def test_TAKROR_client_uuid_BOSHQA_payload_bilan_ham_TAHRIR_EMAS(client, admin_headers, ctx):
    """BUGUNGI XULQ MIXLANADI (UI shunga tayanadi): takror yuborish birinchi
    hujjatni qaytaradi va o'zgarishlarni QO'LLAMAYDI."""
    _cid, bid = ctx
    pid = _new_product(client, admin_headers)
    assert _enable(client, admin_headers, pid).status_code == 200
    cu = uuid.uuid4()
    r1 = _commit(client, admin_headers, [{"product_id": pid, "qty": 5, "unit_cost": 700,
                                          "unit": "dona",
                                          "lots": [{"qty": 5, "batch_number": "BIRINCHI"}]}], cu=cu)
    assert r1.status_code == 200, r1.text
    r2 = _commit(client, admin_headers, [{"product_id": pid, "qty": 9, "unit_cost": 999,
                                          "unit": "dona",
                                          "lots": [{"qty": 9, "batch_number": "IKKINCHI"}]}], cu=cu)
    assert r2.status_code == 200, r2.text
    assert r2.json()["duplicate"] is True
    assert r2.json()["receiving_id"] == r1.json()["receiving_id"]
    assert "doc_no" not in r2.json(), "takror javobi hujjat yaratgandek ko'rinadi"
    lots = _lots(pid)
    assert len(lots) == 1 and lots[0].batch_no == "BIRINCHI"
    assert _inv_qty(pid, bid) == Decimal("5.000")
