# -*- coding: utf-8 -*-
"""PHASE 3 — HAQIQIY POSTGRES: qaytarish / hisobdan chiqarish / sanoq / yopish.

⚠️  NEGA SQLite YETMAYDI. `with_for_update()` SQLite'da BEZARAR NO-OP, ya'ni
    mahalliy to'plam «ikki operator ayni partiyaga tegdi» holatini UMUMAN
    o'lchamaydi. Phase 2 da aynan shu bo'shliq bitta deadlock'ni staging'gacha
    olib chiqqan edi.

QULF TARTIBI — YAGONA VA GLOBAL:

        Inventory  ->  LotShortfall  ->  StockBatch (id bo'yicha tartiblangan)

    Har uch yozuvchi (sotuv, qaytarish, yopish, hisobdan chiqarish, sanoq)
    AYNAN shu tartibda oladi. Teskarisi AB/BA deadlock tug'dirardi.
"""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func

from tests.test_lot_fefo_concurrency import (  # noqa: F401
    D10,
    NOW,
    _concurrent,
    _mk,
    _seed,
    _sell_fn,
    _state,
    pg,
)


def _lots(s, pid):
    from app.models.inventory import StockBatch
    return (s.query(StockBatch).filter(StockBatch.product_id == pid)
            .order_by(StockBatch.id).all())


def _inv(s, pid, bid):
    from app.models.inventory import Inventory
    r = s.query(Inventory).filter(Inventory.product_id == pid,
                                  Inventory.branch_id == bid).first()
    return Decimal(str(r.qty)) if r else Decimal("0")


def _invariant(eng, cid, pid):
    from app.services import stock_invariant as SI
    s = _mk(eng)
    try:
        rep = SI.check(s, cid, [pid])
        assert rep.ok, rep.mismatches
    finally:
        s.close()


def _writeoff_fn(eid, pid, qty, batch_id):
    from app.api.v1.inventory import WriteoffIn, writeoff
    from app.models.auth import Employee

    def go(s):
        emp = s.get(Employee, eid)
        return writeoff(WriteoffIn(product_id=pid, qty=qty, reason="brak",
                                   client_uuid=uuid.uuid4(),
                                   lots=[{"stock_batch_id": batch_id, "qty": qty}]),
                        emp=emp, db=s)
    return go


def _count_fn(eid, pid, counted, batch_id, lot_counted):
    from app.api.v1.inventory import CountIn, stock_count
    from app.models.auth import Employee

    def go(s):
        emp = s.get(Employee, eid)
        return stock_count(CountIn(
            items=[{"product_id": pid, "counted": counted,
                    "lots": [{"stock_batch_id": batch_id, "counted": lot_counted}]}],
            client_uuid=uuid.uuid4()), emp=emp, db=s)
    return go


def test_HAQIQIY_postgres_ekanini_ISBOTLAYMIZ(pg):
    """⚠️  Bu fayl SQLite'da HECH NARSANI o'lchamaydi: `with_for_update()` u yerda
        bezarar no-op. Fixture jimgina SQLite'ga tushib qolsa, quyidagi 8 ta
        sinov YASHIL bo'lib qolardi va hech qanday qulfni isbotlamasdi.
    """
    assert pg.dialect.name == "postgresql", pg.dialect.name


# ══ 1. IKKI HISOBDAN CHIQARISH — BITTA PARTIYA ══════════════════════════════

def test_IKKI_hisobdan_chiqarish_partiyani_MANFIYGA_tushirmaydi(pg):
    """Partiya = 5. Ikkala operator 4 tadan chiqarmoqchi.

    ⚠️  BU AYNAN «YO'QOLGAN YANGILANISH» SINOVI. Qulfsiz ikkalasi ham
        `remaining_qty = 5` ni o'qib, ikkalasi ham «yetarli» deb topardi va
        partiya −3 ga tushardi.
    """
    cid, bid, eid, pid = _seed(pg, lot_qty=5)
    s = _mk(pg); b = _lots(s, pid)[0]; bid_lot = str(b.id); s.close()
    ra, rb = _concurrent(pg, _writeoff_fn(eid, pid, 4, bid_lot),
                         _writeoff_fn(eid, pid, 4, bid_lot))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    assert len(oks) == 1, f"ikkalasi ham o'tdi -> partiya manfiyga tushardi: {ra} {rb}"
    inv, rems, _ = _state(pg, pid, bid)
    assert all(r >= 0 for r in rems), f"partiya MANFIYGA tushdi: {rems}"
    assert inv == Decimal("1.000"), inv
    _invariant(pg, cid, pid)


def test_SOTUV_va_hisobdan_chiqarish_AYNI_partiyaga(pg):
    """Sotuv ham, chiqarish ham AYNI partiyani yeydi — jami sotilgan+chiqarilgan
    miqdor mavjud miqdordan OSHMASIN.

    ⚠️  MIQDORNI emas, SARFNI tekshiramiz. Yo'qolgan yangilanishda oxirgi holat
        «to'g'ri ko'rinishi» mumkin — chunki ikkinchi yozuvchi birinchisining
        natijasini bosib o'tadi va kitob o'zini butun ko'rsatadi.
    """
    cid, bid, eid, pid = _seed(pg, lot_qty=6)
    s = _mk(pg); b = _lots(s, pid)[0]; bid_lot = str(b.id); s.close()
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 4), _writeoff_fn(eid, pid, 4, bid_lot))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    inv, rems, _ = _state(pg, pid, bid)
    assert all(r >= 0 for r in rems), f"partiya MANFIYGA tushdi: {rems}"
    assert inv >= 0, inv
    # Har o'tgan amal AYNAN 4 ta yedi; qolgani 6 − 4*len(oks).
    assert inv == Decimal("6") - Decimal("4") * len(oks), (inv, len(oks))
    _invariant(pg, cid, pid)


# ══ 2. SANOQ — MUTLAQ YOZUV, QULF OSTIDA ════════════════════════════════════

def test_IKKI_sanoq_bir_vaqtda_INVARIANTNI_buzmaydi(pg):
    cid, bid, eid, pid = _seed(pg, lot_qty=10)
    s = _mk(pg); b = _lots(s, pid)[0]; bid_lot = str(b.id); s.close()
    ra, rb = _concurrent(pg, _count_fn(eid, pid, 7, bid_lot, 7),
                         _count_fn(eid, pid, 4, bid_lot, 4))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    assert oks, f"ikkalasi ham yiqildi: {ra} {rb}"
    inv, rems, _ = _state(pg, pid, bid)
    assert inv in (Decimal("7.000"), Decimal("4.000")), inv
    assert sum(rems) == inv, f"qoldiq {inv} partiyalar {rems} bilan mos emas"
    _invariant(pg, cid, pid)


def test_SANOQ_va_SOTUV_bir_vaqtda(pg):
    """Sanoq qoldiqni MUTLAQ qilib yozadi — qulfsiz o'rtadagi sotuv YO'QOLARDI."""
    cid, bid, eid, pid = _seed(pg, lot_qty=10)
    s = _mk(pg); b = _lots(s, pid)[0]; bid_lot = str(b.id); s.close()
    ra, rb = _concurrent(pg, _sell_fn(eid, pid, 3), _count_fn(eid, pid, 8, bid_lot, 8))
    inv, rems, _ = _state(pg, pid, bid)
    assert all(r >= 0 for r in rems)
    assert sum(rems) == inv, f"qoldiq {inv} partiyalar {rems} bilan mos emas"
    _invariant(pg, cid, pid)


# ══ 3. QARZNI YOPISH — QULFSIZ EDI (Phase 2.5 kamchiligi) ═══════════════════

def _shortfall_seed(eng, *, lot_qty, debt):
    """Partiya + OCHIQ qarz — offline sotuvdan keyingi holat."""
    from app.models.inventory import Inventory, LotShortfall
    cid, bid, eid, pid = _seed(eng, lot_qty=lot_qty)
    s = _mk(eng)
    inv = s.query(Inventory).filter(Inventory.product_id == pid).first()
    inv.qty = Decimal(str(lot_qty)) - Decimal(str(debt))
    sf = LotShortfall(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=pid,
                      sale_item_id=None, qty=Decimal(str(debt)), resolved_qty=0,
                      returned_qty=0, resolved_cost=0, unit_cost=Decimal("70"),
                      reason="offline", created_at=NOW)
    s.add(sf); s.commit()
    out = (cid, bid, eid, pid, sf.id)
    s.close()
    return out


def _resolve_fn(eid, sf_id, batch_id, qty):
    from app.api.v1.lots import ResolveShortfallIn, resolve_shortfall
    from app.models.auth import Employee

    def go(s):
        emp = s.get(Employee, eid)
        return resolve_shortfall(sf_id, ResolveShortfallIn(
            stock_batch_id=batch_id, qty=qty, reason="topildi",
            client_uuid=uuid.uuid4()), emp=emp, db=s)
    return go


def test_IKKI_yopish_QARZDAN_ORTIQ_yopolmaydi(pg):
    """Qarz = 4. Ikkala operator 4 tadan yopmoqchi.

    ⚠️  ILGARI QARZ QATORI QULFLANMAS EDI (`db.get(...)`). Ikkalasi ham
        `open_qty = 4` ni o'qib, ikkalasi ham o'tardi: partiya 8 ga kamayib,
        qarz esa bir marta yopilardi — ya'ni qoldiq JIMGINA 4 ta yo'qotardi.
    """
    cid, bid, eid, pid, sf_id = _shortfall_seed(pg, lot_qty=10, debt=4)
    s = _mk(pg); b = _lots(s, pid)[0]; blot = b.id; s.close()
    ra, rb = _concurrent(pg, _resolve_fn(eid, sf_id, blot, 4),
                         _resolve_fn(eid, sf_id, blot, 4))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    assert len(oks) == 1, f"ikkalasi ham yopdi -> qoldiq yo'qolardi: {ra} {rb}"
    inv, rems, _ = _state(pg, pid, bid)
    assert inv == Decimal("6.000"), inv          # 10 − 4 (qarz) o'zgarmaydi
    assert sum(rems) == Decimal("6.000"), rems   # 10 − 4 (yopildi)
    _invariant(pg, cid, pid)


def test_YOPISH_QOLDIQNI_umuman_ozgartirmaydi(pg):
    """Yopish — ATRIBUTSIYA amali. Qoldiq bir tiyin ham qimirlamasin."""
    cid, bid, eid, pid, sf_id = _shortfall_seed(pg, lot_qty=10, debt=4)
    s = _mk(pg); blot = _lots(s, pid)[0].id; oldin = _inv(s, pid, bid); s.close()
    r = _resolve_fn(eid, sf_id, blot, 3)(_mk(pg))
    assert r["ok"] is True, r
    s = _mk(pg)
    assert _inv(s, pid, bid) == oldin, "yopish qoldiqni o'zgartirdi"
    s.close()
    _invariant(pg, cid, pid)


# ══ 4. QULF TARTIBI — AB/BA DEADLOCK YO'Q ═══════════════════════════════════

def test_TESKARI_yonalishdagi_amallar_DEADLOCK_bermaydi(pg):
    """Chiqarish va yopish AYNI partiya + AYNI mahsulotga teginadi.

    Ikkisi har xil tartibda qulflasa Postgres birini `deadlock detected` bilan
    o'ldirardi (40P01). Yagona tartib — Inventory -> qarz -> partiya.
    """
    cid, bid, eid, pid, sf_id = _shortfall_seed(pg, lot_qty=10, debt=4)
    s = _mk(pg); blot = _lots(s, pid)[0]; blot_id = blot.id; s.close()
    ra, rb = _concurrent(pg, _resolve_fn(eid, sf_id, blot_id, 2),
                         _writeoff_fn(eid, pid, 2, str(blot_id)))
    for r in (ra, rb):
        if isinstance(r, Exception):
            assert "deadlock" not in str(r).lower(), f"DEADLOCK: {r}"
    inv, rems, _ = _state(pg, pid, bid)
    assert all(x >= 0 for x in rems), rems
    _invariant(pg, cid, pid)


# ══ 5. TRANZAKSIYA ATOMIKLIGI — RAD ETISH IZ QOLDIRMAYDI ════════════════════

def test_RAD_etilgan_chiqarish_HECH_NARSA_yozmaydi(pg):
    """Yig'indi mos kelmasa: na qoldiq, na partiya, na tafsilot o'zgarsin."""
    from app.models.inventory import StockMovement, StockMovementLotAllocation
    from fastapi import HTTPException

    from app.api.v1.inventory import WriteoffIn, writeoff
    from app.models.auth import Employee
    cid, bid, eid, pid = _seed(pg, lot_qty=8)
    s = _mk(pg); blot = _lots(s, pid)[0]; blot_id = str(blot.id); s.close()

    s = _mk(pg)
    emp = s.get(Employee, eid)
    with pytest.raises(HTTPException) as ei:
        writeoff(WriteoffIn(product_id=pid, qty=5, reason="brak",
                            client_uuid=uuid.uuid4(),
                            lots=[{"stock_batch_id": blot_id, "qty": 3}]),
                 emp=emp, db=s)
    assert ei.value.status_code == 400
    s.rollback(); s.close()

    inv, rems, _ = _state(pg, pid, bid)
    assert inv == Decimal("8.000"), inv
    assert rems == [Decimal("8.000")], rems
    s = _mk(pg)
    assert s.query(func.count(StockMovementLotAllocation.id)).filter(
        StockMovementLotAllocation.product_id == pid).scalar() == 0
    assert s.query(func.count(StockMovement.id)).filter(
        StockMovement.product_id == pid).scalar() == 0
    s.close()
    _invariant(pg, cid, pid)


def test_INVARIANT_buzilса_amal_QAYTARILADI(pg):
    """Yakuniy darvoza commit'dan OLDIN — `rollback()` ROSTDAN qaytarsin.

    ⚠️  PHASE 1 DARSI. Darvoza commit'dan KEYIN turganda `db.rollback()` hech
        narsani qaytarmasdi va «rad etildi» degan javob YOLG'ON bo'lardi.
    """
    from fastapi import HTTPException

    from app.api.v1.inventory import WriteoffIn, writeoff
    from app.models.auth import Employee
    from app.models.inventory import Inventory
    cid, bid, eid, pid = _seed(pg, lot_qty=8)
    s = _mk(pg); blot_id = str(_lots(s, pid)[0].id); s.close()

    # Qoldiqni ATAYLAB partiyalardan AJRATAMIZ — invariant OLDINDAN buzilgan.
    s = _mk(pg)
    inv = s.query(Inventory).filter(Inventory.product_id == pid).first()
    inv.qty = Decimal("9")            # partiyalar esa 8
    s.commit(); s.close()

    s = _mk(pg)
    emp = s.get(Employee, eid)
    with pytest.raises(HTTPException) as ei:
        writeoff(WriteoffIn(product_id=pid, qty=2, reason="brak",
                            client_uuid=uuid.uuid4(),
                            lots=[{"stock_batch_id": blot_id, "qty": 2}]),
                 emp=emp, db=s)
    assert ei.value.status_code == 409
    assert "invariant" in ei.value.detail.lower()
    s.rollback(); s.close()

    inv2, rems, _ = _state(pg, pid, bid)
    assert inv2 == Decimal("9.000"), f"rad etilgan amal qoldiqni o'zgartirdi: {inv2}"
    assert rems == [Decimal("8.000")], f"rad etilgan amal partiyani o'zgartirdi: {rems}"


def test_IKKI_yopish_HAR_XIL_partiyaga_ham_ORTIQ_yopolmaydi(pg):
    """Qarz = 4. Ikkala operator 4 tadan, lekin HAR XIL partiyaga yopmoqchi.

    ⚠️  NEGA AYNAN HAR XIL PARTIYA. Bir xil partiyada `StockBatch` qulfi
        ikkovini SERIALIZATSIYA qilib qo'yadi — ya'ni qarz qatorining O'Z
        qulfi ORTIQCHA ko'rinadi va uni olib tashlash sinovni QIZIL
        qilmaydi. Har xil partiyada bu yordam YO'Q: yagona himoya —
        qarz qatorining (va mahsulot `Inventory` qatorining) qulfi.

        Ularsiz ikkala tranzaksiya ham `open_qty = 4` ni o'qib, ikkalasi ham
        o'tardi: jami 8 ta yopilib, partiyalar 8 ga kamayardi, qarz esa bir
        marta yopilardi — qoldiq JIMGINA 4 ta yo'qotardi.
    """
    from app.models.inventory import StockBatch
    cid, bid, eid, pid, sf_id = _shortfall_seed(pg, lot_qty=10, debt=4)
    # Ikkinchi partiya — jismonan boshqa kogorta.
    s = _mk(pg)
    b2 = StockBatch(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=pid,
                    qty=Decimal("10"), received_qty=Decimal("10"),
                    remaining_qty=Decimal("10"), unit_cost=Decimal("60"),
                    expiry_date=D10, status="open", source_type="receiving",
                    client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                    updated_at=NOW, row_version=1)
    s.add(b2)
    inv = _inv(s, pid, bid)
    from app.models.inventory import Inventory
    s.query(Inventory).filter(Inventory.product_id == pid,
                              Inventory.branch_id == bid).update(
        {"qty": inv + Decimal("10")})
    s.commit()
    b1_id = [b.id for b in _lots(s, pid) if b.id != b2.id][0]
    b2_id = b2.id
    s.close()
    _invariant(pg, cid, pid)

    ra, rb = _concurrent(pg, _resolve_fn(eid, sf_id, b1_id, 4),
                         _resolve_fn(eid, sf_id, b2_id, 4))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    assert len(oks) == 1, f"ikkalasi ham yopdi -> qoldiq yo'qolardi: {ra} {rb}"
    _invariant(pg, cid, pid)


def test_YOPISH_kritik_oynada_QARZ_qatorini_USHLAB_turadi(pg, monkeypatch):
    """Qarz qatori qulfi HAQIQATAN ushlab turishini ISBOTLAYDI.

    ⚠️  NEGA SUN'IY KECHIKISH KERAK. Yopish tranzaksiyasi shunchalik qisqaki,
        ikki ip tabiiy holda deyarli hech qachon KESISHMAYDI — ikkinchisi
        birinchisi commit qilgandan KEYIN o'qiydi va «ortiqcha» deb to'g'ri
        rad etadi. Ya'ni sinov YASHIL bo'lardi, lekin qulfni EMAS, taymingni
        o'lchagan bo'lardi. Manfiy nazorat aynan shuni ko'rsatdi: uchala
        himoyani olib tashlaganda ham sinov yashil qolardi.

        Kechikish MAHSULOT kodiga emas, AUDIT chaqiruviga qo'yiladi (test
        dublyori) — ya'ni kritik bo'lim o'z holicha qoladi, faqat oyna
        kengayadi.

    ⚠️  HAR XIL PARTIYA tanlanadi: bir xil partiyada `StockBatch` qulfi
        ikkovini serializatsiya qilib, qarz qulfini ORTIQCHA qilib qo'yardi.
    """
    import time

    from app.api.v1 import lots as lots_api
    from app.models.inventory import Inventory, StockBatch

    cid, bid, eid, pid, sf_id = _shortfall_seed(pg, lot_qty=10, debt=4)
    s = _mk(pg)
    b2 = StockBatch(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=pid,
                    qty=Decimal("10"), received_qty=Decimal("10"),
                    remaining_qty=Decimal("10"), unit_cost=Decimal("60"),
                    expiry_date=D10, status="open", source_type="receiving",
                    client_uuid=uuid.uuid4(), received_at=NOW, created_at=NOW,
                    updated_at=NOW, row_version=1)
    s.add(b2)
    s.query(Inventory).filter(Inventory.product_id == pid,
                              Inventory.branch_id == bid).update(
        {"qty": _inv(s, pid, bid) + Decimal("10")})
    s.commit()
    b1_id = [b.id for b in _lots(s, pid) if b.id != b2.id][0]
    b2_id = b2.id
    s.close()
    _invariant(pg, cid, pid)

    _real = lots_api.audit_log
    _first = {"done": False}

    def _slow(*a, **kw):
        # FAQAT birinchi yopish sekinlashadi — ikkinchisi shu oynada keladi.
        if not _first["done"]:
            _first["done"] = True
            time.sleep(1.5)
        return _real(*a, **kw)

    monkeypatch.setattr(lots_api, "audit_log", _slow)

    ra, rb = _concurrent(pg, _resolve_fn(eid, sf_id, b1_id, 4),
                         _resolve_fn(eid, sf_id, b2_id, 4))
    oks = [r for r in (ra, rb) if not isinstance(r, Exception)]
    assert len(oks) == 1, f"ikkalasi ham yopdi -> qoldiq yo'qolardi: {ra} {rb}"
    _invariant(pg, cid, pid)
