# -*- coding: utf-8 -*-
"""KUZATUVNI YOQISH × YOZUVCHI — ESKIRGAN BAYROQ POYGASI (Phase 5B, W). SQLite.

⚠️  POYGA. Yozuvchi (sotuv, offline qayta yuborish, hisobdan chiqarish, sanoq,
    qaytarish, xarid, ko'chirish) mahsulotning `track_lots` bayrog'ini `Inventory`
    qulfidan OLDIN o'qiydi. `/lots/enable` o'sha qatorni qulflab, bayroq va ochilish
    partiyasini commit qilguncha yozuvchi qulfda KUTADI — keyin esa qo'lidagi ESKI
    `False` bilan davom etardi: FEFO taqsimoti ham, yakuniy darvoza ham o'tkazib
    yuborilib, `Inventory != SUM(partiya)` JIMGINA commit bo'lardi.

Bu fayl isbotlaydi:
  · sotuv va offline qayta yuborish bayroqni QULFDAN KEYIN yangidan o'qiydi va FEFO
    bilan sotadi (ulush yoziladi, invariant butun);
  · hisobdan chiqarish va sanoq yangi bayroqni ko'radi — partiyasiz so'rov 400, hech
    narsa yozilmaydi;
  · qaytarish yozuvdan keyin bayroq o'zgarganini ko'radi, tranzaksiyani qaytarib
    QAYTA uradi va kuzatuvli yo'l qarorini beradi;
  · xarid va ko'chirish darvozasi qulfdan keyin QAYTA tekshiriladi (409, yozuvsiz);
  · kirim (receiving) allaqachon xavfsiz: yakuniy darvoza bayroqni o'zi o'qiydi (pin);
  · `/lots/enable` qoldiq qatori YO'Q filialda qatorni yaratib qulflaydi va bayroqni
    qulfdan keyin qayta o'qiydi (parallel ikkinchi yoqish 409);
  · MANFIY NAZORAT: kuzatuvsiz mahsulot bugungidek, qo'shimcha — BITTA SELECT;
    allaqachon kuzatuvli mahsulotda refresh yo'q, ulush soni o'zgarmagan.

⚠️  NEGA SUN'IY OYNA. SQLite'da `FOR UPDATE` yo'q, ikkinchi yozuvchi esa fayl
    qulfida turadi — haqiqiy interleaving `test_lot_enable_race_pg.py` da. Bu yerda
    yoqish yozuvchining bayroq o'qishi bilan qulfi ORASIGA qo'yiladi:
      · yozuvchi hali hech narsa YOZMAGAN bo'lsa (hisobdan chiqarish, sanoq,
        qaytarish, ko'chirish) — HAQIQIY `enable_tracking` ALOHIDA sessiyada
        commit qiladi (birinchi `stock_gate.tracked_ids` o'qishidan keyin);
      · yozuvchi allaqachon YOZGAN bo'lsa (chek sarlavhasi, xarid hujjati) — SQLite
        ikkinchi yozuvchini kutdirib yiqitardi, shu bois yoqish yozuvlari AYNI
        ulanishda Core SQL bilan bajariladi (ORM identity map'i ESKI qiymatni
        saqlab qoladi — aynan poyga holati).

⚠️  HAR SINOV O'Z DO'KONIDA — umumiy seed do'koni tarifi va keshlariga tegmaydi.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, insert, select, update
from sqlalchemy.orm import Query

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, Unit
from app.models.enums import EmployeeStatus
from app.models.inventory import (Inventory, SaleItemLotAllocation, StockBatch,
                                  StockMovement)
from app.models.org import Branch, Company
from app.models.purchasing import Purchase, Supplier
from app.models.sales import Return
from app.models.sync import AuditLog
from app.services import stock_gate as SG
from app.services import stock_invariant as SI

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"

# Kutilgan rad etish matnlari — server kodi bilan AYNAN (lug'at kaliti ham shu).
LOTS_KERAK = ("Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim qaysi "
              "jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.")
SANOQ_KERAK = ("Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim "
               "partiyalarga TAQSIMLAMAYDI.")
# B3 (Phase 5C): aktivatsiyadan OLDIN sotilgan chekni OMBORGA qaytarish rad etiladi.
OLDIN_SOTILGAN = ("Bu mahsulot partiya kuzatuvi yoqilishidan OLDIN sotilgan — tovar qaysi "
                  "partiyadan chiqqani NOMA'LUM va tizim uni taxmin qilmaydi. Omborga "
                  "qaytarmasdan (restock'siz) qaytaring.")


def _gate(path):
    return (f"«{path}» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin 1 ta "
            f"kuzatuvli mahsulot so'raldi. Partiya-darajasidagi amalni ishlating — "
            f"qoldiqni partiyalardan ayirmasdan o'zgartirish miqdor invariantini buzardi.")


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _dokon(qoldiq=(10,)):
    """Toza do'kon: filial(lar), ega, ta'minotchi, KUZATUVSIZ mahsulot.

    `qoldiq[i]` — i-filialdagi `Inventory.qty`; `None` — qator UMUMAN yo'q.
    Filiallar `created_at` bo'yicha ANIQ tartibda (birinchisi — xodim filiali).
    """
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="Poyga W", code="w" + uuid.uuid4().hex[:8],
                       currency="UZS")
        db.add(comp)
        db.flush()
        bids = []
        for i, _q in enumerate(qoldiq):
            br = Branch(id=uuid.uuid4(), company_id=comp.id, name=f"F0{i + 1}",
                        code=f"F0{i + 1}", timezone=TZ, is_active=True,
                        created_at=NOW - timedelta(days=10 - i))
            db.add(br)
            db.flush()
            bids.append(br.id)
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="W ega", phone=f"+9987{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        unit = db.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=comp.id, name="Poyga " + uuid.uuid4().hex[:6],
                    article_code="W-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
        db.add(p)
        db.flush()
        for bid, q in zip(bids, qoldiq):
            if q is not None:
                db.add(Inventory(product_id=p.id, branch_id=bid, qty=Decimal(str(q)),
                                 min_qty=0, updated_at=NOW))
        sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="W ta'minotchi")
        db.add(sup)
        db.commit()
        tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id),
                                                "sv": 0})
        return {"cid": comp.id, "bids": bids, "eid": emp.id, "pid": p.id, "sup": sup.id,
                "H": {"Authorization": f"Bearer {tok}"}}


def _holat(d):
    """Mahsulotning bazadagi TO'LIQ holati — invariant ALOHIDA sessiyada, yangi o'qish."""
    with _db() as db:
        p = db.get(Product, d["pid"])
        inv = {str(b): Decimal(str(q)) for b, q in db.query(Inventory.branch_id, Inventory.qty)
               .filter(Inventory.product_id == d["pid"]).all()}
        lots = sorted((s, Decimal(str(r))) for s, r in db.query(
            StockBatch.source_type, StockBatch.remaining_qty)
            .filter(StockBatch.product_id == d["pid"]).all())
        allocs = db.query(SaleItemLotAllocation).filter(
            SaleItemLotAllocation.product_id == d["pid"]).count()
        rep = SI.check(db, d["cid"], [d["pid"]])
        return {"tracked": bool(p.track_lots), "expiry": bool(p.track_expiry), "inv": inv,
                "lots": lots, "allocs": allocs, "buzilish": [str(m) for m in rep.mismatches]}


def _q(v):
    return Decimal(str(v)).quantize(Decimal("0.001"))


def _yoq_haqiqiy(d, branch_index=0, **kw):
    """HAQIQIY `/lots/enable` — ALOHIDA sessiyada, commit bilan (parallel operator)."""
    from app.api.v1.lots import EnableIn, enable_tracking
    with _db() as s:
        body = {"product_id": d["pid"], "branch_id": d["bids"][branch_index],
                "reason": "poyga: parallel yoqish", "legacy_unit_cost": 50, **kw}
        return enable_tracking(EnableIn(**body), emp=s.get(Employee, d["eid"]), db=s)


def _yoq_ayni_ulanishda(d, branch_index=0, expiry=False):
    """`/lots/enable` YOZUVLARI (legacy partiya + bayroqlar) yozuvchining O'Z ulanishida.

    Core SQL — ORM identity map'dagi `Product` obyekti ESKI qoladi, xuddi boshqa
    tranzaksiya commit qilgandek."""
    t_inv, t_sb, t_p = Inventory.__table__, StockBatch.__table__, Product.__table__
    bid = d["bids"][branch_index]

    def go(s):
        q = s.execute(select(t_inv.c.qty).where(t_inv.c.product_id == d["pid"],
                                                t_inv.c.branch_id == bid)).scalar()
        q = _q(q or 0)
        now = datetime.now(timezone.utc)
        if q > 0:
            s.execute(insert(t_sb).values(
                id=uuid.uuid4(), company_id=d["cid"], branch_id=bid, product_id=d["pid"],
                qty=q, received_qty=q, remaining_qty=q, unit_cost=Decimal("50.00"),
                status=SI.OPEN, source_type="legacy", client_uuid=uuid.uuid4(),
                received_at=now, created_at=now, updated_at=now, row_version=1))
        s.execute(update(t_p).where(t_p.c.id == d["pid"]).values(
            track_lots=True, track_expiry=expiry, lots_activated_at=now))
    return go


def _poyga_bayroqdan_keyin(monkeypatch, fn):
    """Yozuvchining BIRINCHI `stock_gate.tracked_ids` o'qishidan KEYIN (qulfdan oldin) `fn()`.

    Yozuvchi eski natijani oladi — ya'ni parallel yoqish aynan shu oynada commit qildi."""
    real = SG.tracked_ids
    holat = {"n": 0, "yoqildi": None}

    def wrap(db, ids):
        out = real(db, ids)
        holat["n"] += 1
        if holat["n"] == 1:
            holat["yoqildi"] = fn()
        return out

    monkeypatch.setattr(SG, "tracked_ids", wrap)
    return holat


def _poyga_qulfdan_oldin(monkeypatch, fn, nth=1):
    """`Inventory` ga n-chi `with_for_update()` chaqiruvida — QULF SELECT'IDAN OLDIN — `fn(sessiya)`."""
    real = Query.with_for_update
    holat = {"n": 0}

    def wrap(self, *a, **kw):
        if any(c.get("entity") is Inventory for c in self.column_descriptions):
            holat["n"] += 1
            if holat["n"] == nth:
                fn(self.session)
        return real(self, *a, **kw)

    monkeypatch.setattr(Query, "with_for_update", wrap)
    return holat


def _sotuv_json(d, qty=2, **kw):
    return {"items": [{"product_id": str(d["pid"]), "qty": qty, "unit_price": 100}],
            "payment_method": "card", "client_uuid": str(uuid.uuid4()), **kw}


def _sql_yozuvi():
    """Engine'dagi HAR bajarilgan SQL (ro'yxat) + tozalash funksiyasi."""
    from app.db.session import engine
    got = []

    def _ol(conn, cursor, statement, params, context, executemany):
        got.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _ol)
    return got, lambda: event.remove(engine, "before_cursor_execute", _ol)


# Qulfdan keyingi bayroq o'qishi (`stock_gate.tracked_ids`) va mahsulotni qayta yuklash shakli.
_QAYTA_OQISH = "SELECT products.id FROM products WHERE products.id IN (?) AND products.track_lots IS 1"
_REFRESH = "FROM products WHERE products.id = ?"


def _qulfdan_keyingi_mahsulot_sorovlari(sqls):
    """Birinchi `inventory` SELECT'idan KEYINGI `FROM products` so'rovlari."""
    i = next(n for n, s in enumerate(sqls) if s.startswith("SELECT") and "FROM inventory" in s)
    return [s for s in sqls[i:] if s.startswith("SELECT") and "FROM products" in s]


# ══ 1. SOTUV — BAYROQ QULFDAN KEYIN YANGIDAN ═════════════════════════════════

def test_SOTUV_qulf_oldidan_yoqilgan_kuzatuv_FEFO_bilan_sotiladi(client, monkeypatch):
    d = _dokon()
    q = _poyga_qulfdan_oldin(monkeypatch, _yoq_ayni_ulanishda(d))
    r = client.post("/api/v1/sales", headers=d["H"], json=_sotuv_json(d))
    assert q["n"] >= 1, "poyga oynasi ochilmadi — sinov hech narsani o'lchamadi"
    assert r.status_code == 200, r.text
    h = _holat(d)
    assert h["buzilish"] == [], f"qoldiq partiyalardan AJRALDI (eskirgan bayroq): {h}"
    assert h["tracked"] is True
    assert h["allocs"] == 1, f"FEFO taqsimoti o'tkazib yuborildi: {h}"
    assert h["inv"] == {str(d["bids"][0]): _q(8)}
    assert h["lots"] == [("legacy", _q(8))]


def test_OFFLINE_qayta_yuborish_qulf_oldidan_yoqilgan_kuzatuvni_KORADI(client, monkeypatch):
    d = _dokon()
    q = _poyga_qulfdan_oldin(monkeypatch, _yoq_ayni_ulanishda(d))
    r = client.post("/api/v1/sync/push", headers=d["H"], json={"sales": [
        _sotuv_json(d, sold_at=datetime.now(timezone.utc).isoformat())]})
    assert q["n"] >= 1
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"] is True, res
    h = _holat(d)
    assert h["buzilish"] == [], f"offline chek partiyasiz yozildi: {h}"
    assert h["allocs"] == 1 and h["lots"] == [("legacy", _q(8))], h


# ══ 2. HISOBDAN CHIQARISH VA SANOQ — PARTIYASIZ SO'ROV ENDI 400 ══════════════

def test_HISOBDAN_chiqarish_bayroq_ozgarsa_400_va_HECH_NARSA_yozmaydi(client, monkeypatch):
    d = _dokon()
    q = _poyga_bayroqdan_keyin(monkeypatch, lambda: _yoq_haqiqiy(d))
    r = client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
        "product_id": str(d["pid"]), "qty": 2, "reason": "brak",
        "client_uuid": str(uuid.uuid4())})
    assert q["yoqildi"] and q["yoqildi"]["ok"] is True, q
    h = _holat(d)
    assert h["buzilish"] == [], f"hisobdan chiqarish partiyaga tegmay qoldiqni kamaytirdi: {h}"
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == LOTS_KERAK
    assert h["inv"] == {str(d["bids"][0]): _q(10)} and h["lots"] == [("legacy", _q(10))], h
    with _db() as db:
        assert db.query(StockMovement).filter(StockMovement.product_id == d["pid"]).count() == 0


def test_SANOQ_bayroq_ozgarsa_400_va_HECH_NARSA_yozmaydi(client, monkeypatch):
    d = _dokon()
    q = _poyga_bayroqdan_keyin(monkeypatch, lambda: _yoq_haqiqiy(d))
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(d["pid"]), "counted": 7}],
        "client_uuid": str(uuid.uuid4())})
    assert q["yoqildi"] and q["yoqildi"]["ok"] is True, q
    h = _holat(d)
    assert h["buzilish"] == [], f"sanoq qoldiqni partiyalarsiz MUTLAQ yozdi: {h}"
    assert r.status_code == 400, r.text
    assert SANOQ_KERAK in r.json()["detail"], r.text
    assert h["inv"] == {str(d["bids"][0]): _q(10)} and h["lots"] == [("legacy", _q(10))], h


# ══ 3. QAYTARISH — YOZUVDAN KEYIN TEKSHIRUV, QAYTA URINISH ═══════════════════

def test_QAYTARISH_restock_bayroq_ozgarsa_QAYTA_urinib_kuzatuvli_qaror_beradi(client, monkeypatch):
    d = _dokon()
    s = client.post("/api/v1/sales", headers=d["H"], json=_sotuv_json(d))
    assert s.status_code == 200, s.text           # yoqishdan OLDINGI (kuzatuvsiz) chek
    q = _poyga_bayroqdan_keyin(monkeypatch, lambda: _yoq_haqiqiy(d))
    r = client.post("/api/v1/returns", headers=d["H"], json={
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(d["pid"]), "qty": 1}]})
    assert q["yoqildi"] and q["yoqildi"]["ok"] is True, q
    h = _holat(d)
    assert h["buzilish"] == [], f"qaytarish qoldiqni partiyasiz oshirdi: {h}"
    # Kuzatuvli mahsulotning chekda ulushi YO'Q (yoqishdan oldin sotilgan) — tizim TAXMIN
    # QILMAYDI: bu poygasiz holatdagi AYNI javob.
    #
    # ⚠️  MATN B3 SIYOSATIDA ATAYLAB ALMASHDI (Phase 5C). Ilgari bu yerda umumiy
    #     «bog'lab bo'lmadi» matni turardi; endi sabab ANIQ aytiladi va barqaror
    #     `X-Error-Code` bilan keladi. Xulq o'zgarmadi: omborga qaytarish RAD.
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == OLDIN_SOTILGAN, r.text
    assert r.headers.get("X-Error-Code") == "LOT_RETURN_PRE_ACTIVATION", dict(r.headers)
    assert q["n"] >= 3, f"qayta urinish bo'lmadi (tracked_ids chaqiruvlari: {q['n']})"
    assert h["inv"] == {str(d["bids"][0]): _q(8)} and h["lots"] == [("legacy", _q(8))], h
    with _db() as db:
        assert db.query(Return).filter(Return.company_id == d["cid"]).count() == 0


def test_QAYTARISH_RESTOCKSIZ_bayroq_ozgarsa_QAYTA_urinib_OTADI(client, monkeypatch):
    """B3: aynan shu poygada `restock=False` esa O'TADI — partiyaga tegilmaydi.

    Qayta urinishdan keyingi kuzatuvli qaror «aktivatsiyadan oldingi chek»
    bo'ladi: qoldiq +1 keyin −1 (NOL), partiyalar qimirlamaydi, invariant butun.
    """
    d = _dokon()
    s = client.post("/api/v1/sales", headers=d["H"], json=_sotuv_json(d))
    assert s.status_code == 200, s.text           # yoqishdan OLDINGI (kuzatuvsiz) chek
    q = _poyga_bayroqdan_keyin(monkeypatch, lambda: _yoq_haqiqiy(d))
    r = client.post("/api/v1/returns", headers=d["H"], json={
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": False,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(d["pid"]), "qty": 1}]})
    assert q["yoqildi"] and q["yoqildi"]["ok"] is True, q
    h = _holat(d)
    assert r.status_code == 200, r.text
    assert h["buzilish"] == [], f"qaytarish qoldiqni partiyalardan ajratdi: {h}"
    assert q["n"] >= 3, f"qayta urinish bo'lmadi (tracked_ids chaqiruvlari: {q['n']})"
    assert h["inv"] == {str(d["bids"][0]): _q(8)} and h["lots"] == [("legacy", _q(8))], h
    with _db() as db:
        assert db.query(Return).filter(Return.company_id == d["cid"]).count() == 1
        assert db.query(AuditLog).filter(
            AuditLog.entity == "return_pre_activation",
            AuditLog.actor_id == d["eid"]).count() == 1


# ══ 4. XARID VA KO'CHIRISH — DARVOZA QULFDAN KEYIN QAYTA ═════════════════════

def test_XARID_darvozasi_qulfdan_keyin_QAYTA_409_yozuvsiz(client, monkeypatch):
    d = _dokon()
    q = _poyga_qulfdan_oldin(monkeypatch, _yoq_ayni_ulanishda(d))
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "debt", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(d["pid"]), "qty": 5, "unit_cost": 50}]})
    assert q["n"] >= 1
    h = _holat(d)
    assert h["buzilish"] == [], f"xarid partiyasiz qoldiq kiritdi: {h}"
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _gate("xarid (partiyasiz kirim)")
    # Ayni ulanishdagi yoqish ham QAYTARILDI — hech narsa yozilmagan.
    assert h["inv"] == {str(d["bids"][0]): _q(10)} and h["lots"] == [], h
    with _db() as db:
        assert db.query(Purchase).filter(Purchase.company_id == d["cid"]).count() == 0


def test_KOCHIRISH_darvozasi_qulfdan_keyin_QAYTA_409_yozuvsiz(client, monkeypatch):
    d = _dokon(qoldiq=(10, None))
    q = _poyga_bayroqdan_keyin(monkeypatch, lambda: _yoq_haqiqiy(d))
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(d["pid"]), "qty": 3}], "client_uuid": str(uuid.uuid4())})
    assert q["yoqildi"] and q["yoqildi"]["ok"] is True, q
    h = _holat(d)
    assert h["buzilish"] == [], f"ko'chirish partiyasiz qoldiq siljitdi: {h}"
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == _gate("filiallararo ko'chirish")
    assert h["inv"].get(str(d["bids"][0])) == _q(10), h
    assert h["inv"].get(str(d["bids"][1]), _q(0)) == _q(0), h


# ══ 5. KIRIM — ALLAQACHON XAVFSIZ (PIN) ══════════════════════════════════════

def test_KIRIM_mahsulot_yuklangach_yoqilsa_YAKUNIY_darvoza_409(client, monkeypatch):
    """Kirim mahsulotni qulf halqasidan KEYIN yuklaydi va yakuniy darvoza bayroqni O'ZI
    o'qiydi — mahsulot yuklangan, lekin qator hali qulflanmagan oynada yoqilsa ham
    commit bo'lmaydi. (Qator YO'Q filialdagi haqiqiy poyga — PG faylida.)"""
    d = _dokon()
    q = _poyga_qulfdan_oldin(monkeypatch, _yoq_ayni_ulanishda(d), nth=2)
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(d["pid"]), "qty": 5, "unit_cost": 50, "unit": "dona"}],
        "supplier_id": str(d["sup"]), "payment": "credit",
        "client_uuid": str(uuid.uuid4()), "source": "manual"})
    assert q["n"] >= 2
    assert r.status_code == 409, r.text
    assert r.headers.get("X-Error-Code") == "LOT_INVARIANT_BROKEN", dict(r.headers)
    h = _holat(d)
    assert h["buzilish"] == [] and h["inv"] == {str(d["bids"][0]): _q(10)}, h
    with _db() as db:
        assert db.query(Purchase).filter(Purchase.company_id == d["cid"]).count() == 0


# ══ 6. /lots/enable O'ZI ═════════════════════════════════════════════════════

def test_YOQISH_qator_YOQ_filiallarda_qatorni_YARATIB_qulflaydi(client):
    """Qator yo'q bo'lsa qulflanadigan narsa yo'q edi: birinchi kirim/sotuv qatorni
    yaratib, eskirgan bayroq bilan commit qilardi. Endi yoqish HAR tirik filialda
    qatorni o'zi yaratadi — parallel yozuvchining INSERT'i unga to'qnashadi (PG)."""
    d = _dokon(qoldiq=(None, None))
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(d["pid"]), "branch_id": str(d["bids"][0]),
        "reason": "qatorsiz yoqish", "track_expiry": False})
    assert r.status_code == 200, r.text
    assert r.json()["opening_qty"] == 0 and r.json()["lots_created"] == 0
    h = _holat(d)
    assert h["inv"] == {str(b): _q(0) for b in d["bids"]}, h
    assert h["tracked"] is True and h["buzilish"] == [], h


def test_YOQISH_ochirilgan_filialda_qator_YARATMAYDI(client):
    d = _dokon(qoldiq=(None, None))
    with _db() as db:
        db.get(Branch, d["bids"][1]).deleted_at = NOW
        db.commit()
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(d["pid"]), "branch_id": str(d["bids"][0]),
        "reason": "o'chirilgan filial", "track_expiry": False})
    assert r.status_code == 200, r.text
    assert _holat(d)["inv"] == {str(d["bids"][0]): _q(0)}


def test_YOQISH_qulf_kutayotganda_boshqasi_yoqsa_409_bayroq_QAYTA_yozilmaydi(client, monkeypatch):
    """Ikkinchi yoqish mahsulotni qulfdan OLDIN (kuzatuvsiz) o'qigan. Eskirgan bayroq bilan
    u `track_expiry` ni jimgina QAYTA yozib, ikkinchi audit qatorini qo'shardi."""
    d = _dokon(qoldiq=(0,))
    q = _poyga_qulfdan_oldin(monkeypatch, _yoq_ayni_ulanishda(d, expiry=True))
    r = client.post("/api/v1/lots/enable", headers=d["H"], json={
        "product_id": str(d["pid"]), "branch_id": str(d["bids"][0]),
        "reason": "ikkinchi yoqish", "track_expiry": False})
    assert q["n"] >= 1
    assert r.status_code == 409, r.text
    assert r.json()["detail"].endswith("allaqachon partiya bo'yicha kuzatiladi"), r.text
    with _db() as db:
        assert db.query(AuditLog).filter(AuditLog.entity == "product_lot_tracking",
                                         AuditLog.entity_id == d["pid"]).count() == 0


# ══ 7. MANFIY NAZORAT — KUZATUVSIZ VA ALLAQACHON KUZATUVLI ═══════════════════

def test_NAZORAT_kuzatuvsiz_sotuv_BUGUNGIDEK_qoshimcha_BITTA_select(client):
    """Production'dagi HAMMA mahsulot kuzatuvsiz. Yo'l o'zgarmagan: ulush yo'q, qoldiq
    kamaydi; qulfdan keyin mahsulotga BITTA so'rov (bayroq o'qishi, natijasi bo'sh),
    `refresh` yo'q."""
    d = _dokon()
    got, stop = _sql_yozuvi()
    try:
        r = client.post("/api/v1/sales", headers=d["H"], json=_sotuv_json(d))
    finally:
        stop()
    assert r.status_code == 200, r.text
    h = _holat(d)
    assert h == {"tracked": False, "expiry": False, "inv": {str(d["bids"][0]): _q(8)},
                 "lots": [], "allocs": 0, "buzilish": []}, h
    keyin = _qulfdan_keyingi_mahsulot_sorovlari(got)
    assert len(keyin) == 1, keyin
    assert _QAYTA_OQISH in keyin[0], keyin
    assert not [s for s in keyin if _REFRESH in s], keyin


def test_NAZORAT_allaqachon_kuzatuvli_sotuv_REFRESHSIZ_bitta_ulush(client):
    d = _dokon()
    with _db() as s:
        _yoq_ayni_ulanishda(d)(s)
        s.commit()
    got, stop = _sql_yozuvi()
    try:
        r = client.post("/api/v1/sales", headers=d["H"], json=_sotuv_json(d))
    finally:
        stop()
    assert r.status_code == 200, r.text
    h = _holat(d)
    assert h["allocs"] == 1 and h["lots"] == [("legacy", _q(8))] and h["buzilish"] == [], h
    keyin = _qulfdan_keyingi_mahsulot_sorovlari(got)
    # Qayta o'qish (1) + yakuniy darvozaning o'z bayroq so'rovi (1); mahsulot QAYTA YUKLANMAYDI.
    assert len([s for s in keyin if _QAYTA_OQISH in s]) == 1, keyin
    assert not [s for s in keyin if _REFRESH in s], keyin


def test_NAZORAT_kuzatuvsiz_yozuvchilar_poygasiz_BUGUNGIDEK(client):
    """Poyga YO'Q: har yozuvchi kuzatuvsiz mahsulotda avvalgidek 200 va qoldiqni siljitadi.
    O'lchov: birinchi `inventory` so'rovidan keyin bayroq o'qishi — AYNAN BITTA (qo'shilgani)."""
    d = _dokon(qoldiq=(10, None))
    H, pid = d["H"], str(d["pid"])
    b0, b1 = (str(b) for b in d["bids"])

    def post(path, body):
        got, stop = _sql_yozuvi()
        try:
            r = client.post(path, headers=H, json=body)
        finally:
            stop()
        oqish = [s for s in _qulfdan_keyingi_mahsulot_sorovlari(got) if _QAYTA_OQISH in s]
        assert len(oqish) == 1, (path, oqish)
        return r

    r = post("/api/v1/inventory/writeoff", {
        "product_id": pid, "qty": 1, "reason": "brak", "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["new_qty"] == 9, r.text
    r = post("/api/v1/inventory/count", {
        "items": [{"product_id": pid, "counted": 12}], "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["changed"] == 1, r.text
    s = post("/api/v1/sales", _sotuv_json(d))
    assert s.status_code == 200, s.text                                   # 10
    r = post("/api/v1/returns", {
        "original_sale_id": s.json()["id"], "reason": "customer", "restock": True,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 1}]})
    assert r.status_code == 200, r.text                                   # 11
    r = post("/api/v1/purchases", {
        "supplier_id": str(d["sup"]), "status": "debt", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 5, "unit_cost": 50}]})
    assert r.status_code == 200, r.text                                   # 16
    r = post("/api/v1/inventory/transfer", {
        "from_branch_id": b0, "to_branch_id": b1, "items": [{"product_id": pid, "qty": 3}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text                                   # 13 / 3
    h = _holat(d)
    assert h == {"tracked": False, "expiry": False, "inv": {b0: _q(13), b1: _q(3)},
                 "lots": [], "allocs": 0, "buzilish": []}, h


@pytest.mark.parametrize("yol", ["hisobdan", "sanoq"])
def test_NAZORAT_allaqachon_kuzatuvli_partiya_bilan_OTADI(client, yol):
    """Allaqachon kuzatuvli mahsulotda qulfdan keyingi qayta o'qish hech narsani
    o'zgartirmaydi — partiya ko'rsatilgan so'rov avvalgidek o'tadi."""
    d = _dokon()
    assert _yoq_haqiqiy(d)["ok"] is True
    lot = _holat(d)
    with _db() as db:
        lot_id = str(db.query(StockBatch.id).filter(StockBatch.product_id == d["pid"]).scalar())
    if yol == "hisobdan":
        r = client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
            "product_id": str(d["pid"]), "qty": 2, "reason": "brak",
            "client_uuid": str(uuid.uuid4()), "lots": [{"stock_batch_id": lot_id, "qty": 2}]})
    else:
        r = client.post("/api/v1/inventory/count", headers=d["H"], json={
            "items": [{"product_id": str(d["pid"]), "counted": 8,
                       "lots": [{"stock_batch_id": lot_id, "counted": 8}]}],
            "client_uuid": str(uuid.uuid4())})
    assert lot["lots"] == [("legacy", _q(10))]
    assert r.status_code == 200, r.text
    h = _holat(d)
    assert h["inv"] == {str(d["bids"][0]): _q(8)} and h["lots"] == [("legacy", _q(8))], h
    assert h["buzilish"] == [], h
