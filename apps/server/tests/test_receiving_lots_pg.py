# -*- coding: utf-8 -*-
"""PARTIYALI KIRIM — HAQIQIY POSTGRES (Phase 5C, B2).

⚠️  NEGA SQLite YETMAYDI. Kirim qatori miqdorini `Inventory.qty` ga XOM qo'shadi,
    partiya esa `lot_receiving._q` bilan kvantlanadi. Postgres NUMERIC(14,3)
    ustunga YOZAYOTGANDA yaxlitlaydi (yarim-nolddan uzoqqa), SQLite esa qiymatni
    o'z holicha saqlab, o'qishda ham shunday qaytaradi — ya'ni ikki yo'lning
    farqi mahalliy to'plamda UMUMAN ko'rinmaydi. Aynan shu sabab 1.2345 kabi
    miqdor SQLite'da «yashil», Postgres'da esa `Inventory 1.235 ≠ partiya 1.234`
    bo'lib yakuniy invariant darvozasidan 409 olardi.

Bu fayl isbotlaydi (har holatda commit'dan KEYIN `stock_invariant.check` BUTUN):
  1. UCH kasrli kirim (1.235 = 0.617 + 0.618) o'tadi va qoldiq partiyalar
     yig'indisiga AYNAN teng — 409 YO'Q;
  2. TO'RT kasrli miqdor 400 bilan rad etiladi va bazada IZ qoldirmaydi
     (ESKI kodda bu yerda 409 «qo'llab-quvvatlashga murojaat qiling» bo'lardi);
  3. AYNI `client_uuid` bilan ikki KONKURRENT yuborish — BITTA qabul, BITTA
     partiya to'plami, qoldiq bir marta oshadi (ikkinchisi `duplicate: true`).

⚠️  OSILMAYDI: ulanishlarda `lock_timeout`/`statement_timeout`, iplar
    `join(timeout)` bilan (`test_lot_tz_confirm_pg._mk` / `_navbat`).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza).
Endpoint funksiyalari sessiya bilan TO'G'RIDAN chaqiriladi.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_lot_tz_confirm_pg import _mk, _navbat

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
KASR_QATOR = ("qator miqdori 1.2345 da uchtadan ORTIQ kasr xonasi bor — miqdor "
              "0.001 aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi.")


def _baza(url):
    _initdb(url)
    return _mk(url)


def _dokon(S):
    """Kompaniya + filial + ega + ta'minotchi + KUZATUVLI (FIFO) kg mahsulot, qoldiq 0."""
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="B2 PG", code="b2" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        b = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B1", timezone=TZ,
                   is_active=True, created_at=NOW - timedelta(days=10))
        s.add(b)
        s.flush()
        ega = s.query(Role).filter(Role.code == "ega").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name="B2 ega",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
        s.add(e)
        s.flush()
        unit = s.query(Unit).filter(Unit.code == "kg").first() or s.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=co.id, name="B2 " + uuid.uuid4().hex[:6],
                    article_code="B2-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0,
                    track_lots=True)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b.id, qty=Decimal("0"),
                        min_qty=0, updated_at=NOW))
        sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="B2 ta'minotchi")
        s.add(sup)
        s.commit()
        return {"cid": co.id, "bid": b.id, "emp": e.id, "pid": p.id, "sup": sup.id}
    finally:
        s.close()


def _emp(s, d):
    from app.models.auth import Employee
    return s.get(Employee, d["emp"])


def _kirim(d, qty, lots, cu=None, *, ushlab_tur=False):
    """HAQIQIY `POST /receiving/commit` funksiyasi. `ushlab_tur` — commit o'rniga
    flush: tranzaksiyani `_navbat` commit qiladi (ikkinchisi qulfda kutayotgani ko'rilgach)."""
    from app.api.v1.receiving import CommitIn, commit
    body = CommitIn(
        items=[{"product_id": str(d["pid"]), "qty": qty, "unit_cost": 50, "unit": "kg",
                "lots": [{"qty": q} for q in lots]}],
        supplier_id=d["sup"], payment="credit", source="manual",
        client_uuid=(cu or uuid.uuid4()))

    def go(s):
        if not ushlab_tur:
            return commit(body, emp=_emp(s, d), db=s)
        s.commit = s.flush
        try:
            return commit(body, emp=_emp(s, d), db=s)
        finally:
            del s.commit
    return go


def _holat(S, d):
    from app.models.inventory import Inventory, StockBatch
    from app.models.receiving import Receiving
    from app.services import stock_invariant as SI
    s = S()
    try:
        inv = s.query(Inventory.qty).filter(Inventory.product_id == d["pid"],
                                            Inventory.branch_id == d["bid"]).scalar()
        lots = sorted(Decimal(str(q)) for (q,) in s.query(StockBatch.remaining_qty)
                      .filter(StockBatch.product_id == d["pid"]).all())
        rep = SI.check(s, d["cid"], [d["pid"]])
        return {
            "inv": Decimal(str(inv or 0)),
            "lots": lots,
            "qabul": s.query(Receiving).filter(Receiving.company_id == d["cid"]).count(),
            "buzilish": [str(m) for m in rep.mismatches],
        }
    finally:
        s.close()


# ══ 1. UCH KASRLI KIRIM — QOLDIQ VA PARTIYA AYNAN TENG ═══════════════════════

def test_PG_uch_kasrli_kirim_qoldiq_partiyaga_TENG(pg_target):
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        s = S()
        try:
            r = _kirim(d, 1.235, [0.617, 0.618])(s)
        finally:
            s.close()
        assert r["ok"] is True, r
        h = _holat(S, d)
        assert h["inv"] == Decimal("1.235"), h
        assert h["lots"] == [Decimal("0.617"), Decimal("0.618")], h
        assert sum(h["lots"]) == h["inv"], h
        assert h["buzilish"] == [], h
    finally:
        eng.dispose()


# ══ 2. TO'RT KASR — 400, YOZUVSIZ ════════════════════════════════════════════

def test_PG_tort_kasrli_miqdor_400_va_IZ_qoldirmaydi(pg_target):
    """ESKI KODDA: qator 1.2345 -> `Inventory` 1.235 (Postgres yozuvda yaxlitlaydi),
    partiya 1.234 (`_q` yarim-juft) -> yakuniy darvoza 409 LOT_INVARIANT_BROKEN.
    Endi sabab ANIQ aytiladi (400) va kirim umuman boshlanmaydi."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        oldin = _holat(S, d)
        s = S()
        try:
            with pytest.raises(HTTPException) as ei:
                _kirim(d, 1.2345, [1.2345])(s)
            s.rollback()
        finally:
            s.close()
        assert ei.value.status_code == 400, ei.value.detail
        assert KASR_QATOR in ei.value.detail, ei.value.detail
        assert _holat(S, d) == oldin
    finally:
        eng.dispose()


# ══ 3. KONKURRENT TAKROR — BITTA QABUL, BITTA PARTIYA TO'PLAMI ═══════════════

def test_PG_AYNI_client_uuid_bilan_IKKI_konkurrent_yuborish_BITTA_qabul(pg_target):
    """Tarmoq uzilib, UI AYNI hujjatni qayta yuboradi — ikkinchisi birinchi
    tranzaksiya ochiq turganda keladi. Qoldiq IKKI marta oshmasligi shart."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        cu = uuid.uuid4()
        r = _navbat(eng, S,
                    _kirim(d, 3, [1, 2], cu=cu, ushlab_tur=True),
                    _kirim(d, 3, [1, 2], cu=cu))
        assert not isinstance(r.get("a"), Exception), r
        assert not isinstance(r.get("b"), Exception), r
        assert r["kutdi"] is True, f"ikkinchi yuborish qulfni KUTMADI: {r}"
        assert r["a"].get("duplicate") is not True, r["a"]
        assert r["b"].get("duplicate") is True, r["b"]
        assert r["a"]["receiving_id"] == r["b"]["receiving_id"], r

        h = _holat(S, d)
        assert h["qabul"] == 1, h
        assert h["lots"] == [Decimal("1.000"), Decimal("2.000")], h
        assert h["inv"] == Decimal("3.000"), h
        assert h["buzilish"] == [], h
    finally:
        eng.dispose()
