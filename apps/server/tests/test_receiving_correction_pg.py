# -*- coding: utf-8 -*-
"""QABUL TUZATISH POYGALARI — HAQIQIY POSTGRES (Phase 5D).

⚠️  NEGA SQLite YETMAYDI. Tuzatish butun kuchini QULFLARDAN oladi: hujjat
    `FOR UPDATE`, ta'minotchi `FOR UPDATE`, qoldiq va partiyalar `FOR UPDATE`.
    SQLite'da `with_for_update()` BEZARAR NO-OP va fayl qulfi yozuvchilarni
    baribir ketma-ket qo'yadi — ya'ni mahalliy to'plam «ikki operator ayni
    hujjatga tegdi» holatini UMUMAN o'lchamaydi. Aynan shu bo'shliqda ikki
    marta bekor qilish (ikki naqd qaytarish, ikki ta'minotchi tuzatishi) yoki
    tuzatish bilan sotuv o'rtasida YO'QOLGAN YANGILANISH jimgina o'tib ketardi.

⚠️  INTERLEAVING MAJBURIY, TASODIFIY EMAS (`test_lot_tz_confirm_pg._navbat`).
    Birinchi tranzaksiya yozib, commit QILMAY turadi; ikkinchisi shundan KEYIN
    boshlanadi va u birinchisining qulfini KUTAYOTGANI `pg_blocking_pids` da
    ko'rilgach birinchisi commit qiladi. Kutish ko'rilmasa sinov QIZIL
    (`kutdi`) — aks holda biz qulfni emas, taymingni o'lchagan bo'lardik.

Bu fayl isbotlaydi:
  1. to'liq bekor qilingan hujjatni IKKINCHI marta bekor qilib bo'lmaydi (404),
     AYNI `client_uuid` bilan takror esa BIRINCHI javobni qaytaradi;
  2. ikki parallel bekor qilish — BITTASI o'tadi, ikkinchisi hujjat qulfida
     kutib, o'chirilgan hujjatni ko'radi va 404 oladi (ikkinchi ta'minotchi
     tuzatishi YOZILMAYDI);
  3. bekor qilish × sotuv / hisobdan chiqarish / sanoq, IKKALA tartibda:
       tuzatish avval -> yozuvchi qulfda KUTADI va BEKOR QILINGAN holatni ko'radi,
       yozuvchi avval -> tuzatish qulfda KUTADI va kamaygan qoldiqni ko'rib,
                         to'liq teskari qilishdan BOSH TORTADI (409, barqaror kod);
  4. qisman tuzatish × sotuv — IKKALASI ham o'tadi va qoldiq AYNAN 5 bo'ladi
     (rad etish bilan tugagan poyga dreyfni o'lchamaydi — bu o'lchaydi);
  5. AYNI `client_uuid` bilan ikki konkurrent tuzatish — qoldiq BIR MARTA
     siljiydi (konkurrent takror ham `duplicate: true` oladi — to'liq bekor
     qilishda ham, chunki takror qidiruvi `deleted_at` tekshiruvidan OLDIN,
     o'z sinovida hujjatlangan);
  6. rad etilgan tuzatish BAZADA IZ QOLDIRMAYDI — sarlavha ham, harakat ham,
     ta'minotchi tuzatishi ham; `client_uuid` KUYMAYDI (ayni kalit bilan qayta
     yuborish o'tadi) va hujjat `PATCH` uchun JIMGINA qulflanib qolmaydi.

HAR POYGADAN KEYIN — MIQDOR DREYFI YO'Q (`_dreyf_yoq`):
    Inventory.qty == Σ remaining (void'siz) − Σ ochiq qarz   VA
    Σ received_qty O'ZGARMAYDI (tuzatish kogorta identifikatsiyasini HECH QACHON
    qayta yozmaydi — u faqat teskari yozuv qo'shadi).

⚠️  OSILMAYDI: har ulanishda `lock_timeout`/`statement_timeout`, iplar
    `join(timeout)` bilan (`test_lot_tz_confirm_pg._mk` / `_navbat`).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
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
QTY = Decimal("10")          # qabul qilingan miqdor
COST = Decimal("50")         # partiya tannarxi -> hujjat jami 500.00
SABAB = "PG poyga: nakladnoyda miqdor xato"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _baza(url):
    _initdb(url)
    eng, S = _mk(url)
    # ⚠️  Bu fayl SQLite'da HECH NARSANI o'lchamaydi: `with_for_update()` u yerda
    #     bezarar no-op. Fixture jimgina SQLite'ga tushib qolsa, quyidagi poygalar
    #     YASHIL bo'lib qolardi va hech qanday qulfni isbotlamasdi.
    assert eng.dialect.name == "postgresql", eng.dialect.name
    return eng, S


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.001"))


def _dokon(S):
    """Kompaniya + filial + ega + ta'minotchi + KUZATUVLI mahsulot, qoldiq 0."""
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="5D PG", code="c5d" + uuid.uuid4().hex[:8],
                     currency="UZS")
        s.add(co)
        s.flush()
        b = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="B1", timezone=TZ,
                   is_active=True, created_at=NOW - timedelta(days=10))
        s.add(b)
        s.flush()
        ega = s.query(Role).filter(Role.code == "ega").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name="5D ega",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
        s.add(e)
        s.flush()
        unit = s.query(Unit).filter(Unit.code == "dona").first() or s.query(Unit).first()
        nom = "5D " + uuid.uuid4().hex[:6]
        p = Product(id=uuid.uuid4(), company_id=co.id, name=nom,
                    article_code="5D-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=COST, base_sell_price=100, tax_rate=0,
                    track_lots=True)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b.id, qty=Decimal("0"),
                        min_qty=0, updated_at=NOW))
        sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="5D ta'minotchi")
        s.add(sup)
        s.commit()
        return {"cid": co.id, "bid": b.id, "emp": e.id, "pid": p.id, "sup": sup.id, "nom": nom}
    finally:
        s.close()


def _emp(s, d):
    from app.models.auth import Employee
    return s.get(Employee, d["emp"])


def _qabul(S, d, lots=(QTY,)):
    """HAQIQIY `/receiving/commit` — QARZ (credit) hujjati + partiyalar.

    ⚠️  ATAYLAB QARZ HUJJATI. Naqd hujjatda tuzatish `resolve_cash_custody` ni
        chaqiradi (smena/kassa hisobi) — bu poygalarga BEGONA o'zgaruvchi
        qo'shardi. Qarz hujjatida esa pul yo'li AYNAN ta'minotchi defteri
        bo'ladi va uni bir qatorga qadar tekshirib bo'ladi.
    """
    from app.api.v1.receiving import CommitIn, commit
    from app.models.inventory import StockBatch
    from app.models.purchasing import PurchaseItem
    from app.models.receiving import Receiving
    jami = sum((Decimal(str(q)) for q in lots), Decimal("0"))
    s = S()
    try:
        r = commit(CommitIn(
            items=[{"product_id": str(d["pid"]), "qty": float(jami), "unit_cost": float(COST),
                    "unit": "dona", "lots": [{"qty": float(q)} for q in lots]}],
            supplier_id=d["sup"], payment="credit", source="manual",
            client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)
        assert r["ok"] is True, r
    finally:
        s.close()
    s = S()
    try:
        rec = s.get(Receiving, uuid.UUID(r["receiving_id"]))
        item = s.query(PurchaseItem).filter(PurchaseItem.purchase_id == rec.purchase_id).one()
        bs = (s.query(StockBatch).filter(StockBatch.receiving_id == rec.id)
              .order_by(StockBatch.received_qty.desc(), StockBatch.id).all())
        d.update({"rec": rec.id, "pur": rec.purchase_id, "item": item.id,
                  "batch": [b.id for b in bs]})
        return d
    finally:
        s.close()


def _tuzat(d, reverse, *, cu=None, reason=SABAB):
    """HAQIQIY `POST /receiving/{id}/corrections` (tarjima qatlami bilan birga)."""
    from app.api.v1.receiving import (CorrectionIn, CorrectionLine, CorrectionReverse,
                                      correct_receiving)
    body = CorrectionIn(
        client_uuid=(cu or uuid.uuid4()), reason=reason,
        lines=[CorrectionLine(purchase_item_id=d["item"],
                              reverse=[CorrectionReverse(stock_batch_id=b, qty=float(q))
                                       for b, q in reverse])])
    return lambda s: correct_receiving(d["rec"], body, emp=_emp(s, d), db=s)


def _bekor(d, **kw):
    """To'liq bekor qilish — hujjatning HAMMA partiyasini to'liq teskari qiladi."""
    return _tuzat(d, [(b, QTY / len(d["batch"])) for b in d["batch"]], **kw)


def _ushla(go):
    """Tranzaksiyani USHLAB turadi: `commit` o'rniga `flush` — uni `_navbat` commit qiladi."""
    def wrap(s):
        s.commit = s.flush
        try:
            return go(s)
        finally:
            del s.commit
    return wrap


def _sotuv(d, qty=2):
    from app.schemas.sales import SaleCreate
    from app.services.sales import create_sale
    return lambda s: str(create_sale(s, _emp(s, d), SaleCreate(
        items=[{"product_id": str(d["pid"]), "qty": qty, "unit_price": 100}],
        payment_method="card", client_uuid=uuid.uuid4())).id)


def _hisobdan(d, qty=3):
    from app.api.v1.inventory import WriteoffIn, writeoff
    return lambda s: writeoff(WriteoffIn(
        product_id=d["pid"], qty=qty, reason="brak", client_uuid=uuid.uuid4(),
        lots=[{"stock_batch_id": str(d["batch"][0]), "qty": qty}]), emp=_emp(s, d), db=s)


def _sanoq(d, counted=8):
    from app.api.v1.inventory import CountIn, stock_count
    return lambda s: stock_count(CountIn(
        items=[{"product_id": str(d["pid"]), "counted": counted,
                "lots": [{"stock_batch_id": str(d["batch"][0]), "counted": counted}]}],
        client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)


YOZUVCHILAR = {"sotuv": _sotuv, "hisobdan": _hisobdan, "sanoq": _sanoq}
# Yozuvchi o'tgandan KEYINGI partiya qoldig'i (10 dan): sotuv −2, chiqarish −3, sanoq 8 ga.
QOLDIQ_KEYIN = {"sotuv": Decimal("8"), "hisobdan": Decimal("7"), "sanoq": Decimal("8")}


def _holat(S, d):
    """Tuzatishning BUTUN izi: qoldiq, partiyalar, hodisalar, hujjat va ta'minotchi."""
    from app.models.inventory import (Inventory, LotShortfall, SaleItemLotAllocation,
                                      StockBatch, StockMovement, StockMovementLotAllocation)
    from app.models.purchasing import Purchase, Supplier, SupplierLedger
    from app.models.receiving import ReceivingCorrection
    from app.services import stock_invariant as SI
    s = S()
    try:
        inv = s.query(Inventory.qty).filter(Inventory.product_id == d["pid"],
                                            Inventory.branch_id == d["bid"]).scalar()
        lots = sorted((str(b), st, _q(r), _q(rq)) for b, st, r, rq in s.query(
            StockBatch.id, StockBatch.status, StockBatch.remaining_qty,
            StockBatch.received_qty).filter(StockBatch.product_id == d["pid"]).all())
        # Invariantning O'Z ta'rifi: faqat MUSBAT ochiq qoldiq qarz hisoblanadi.
        qarz = sum((max(_q(q) - _q(rq), Decimal("0")) for q, rq in s.query(
            LotShortfall.qty, LotShortfall.resolved_qty)
            .filter(LotShortfall.product_id == d["pid"]).all()), Decimal("0"))
        pur = s.get(Purchase, d["pur"])
        sup = s.get(Supplier, d["sup"])
        mv = sorted((rt, str(t.value if hasattr(t, "value") else t), _q(q))
                    for rt, t, q in s.query(StockMovement.ref_type, StockMovement.type,
                                            StockMovement.qty)
                    .filter(StockMovement.product_id == d["pid"]).all())
        rep = SI.check(s, d["cid"], [d["pid"]])
        return {
            "inv": _q(inv or 0),
            "lots": lots,
            "qoldiq": sum((r for _b, st, r, _rq in lots if st != SI.VOID), Decimal("0")),
            "kelgan": sum((rq for _b, _st, _r, rq in lots), Decimal("0")),
            "qarz": qarz,
            "harakat": mv,
            "ulush": s.query(StockMovementLotAllocation).filter(
                StockMovementLotAllocation.product_id == d["pid"]).count(),
            "sotuv_ulush": s.query(SaleItemLotAllocation).filter(
                SaleItemLotAllocation.product_id == d["pid"]).count(),
            "tuzatish": s.query(ReceivingCorrection).filter(
                ReceivingCorrection.company_id == d["cid"]).count(),
            "hujjat": (pur.status.value, Decimal(str(pur.total)),
                       Decimal(str(pur.paid_amount or 0)), pur.deleted_at is not None),
            "balans": Decimal(str(sup.balance or 0)),
            "defter": sorted((t.value if hasattr(t, "value") else str(t), rt, Decimal(str(a)))
                             for t, rt, a in s.query(SupplierLedger.type, SupplierLedger.ref_type,
                                                     SupplierLedger.amount)
                             .filter(SupplierLedger.supplier_id == d["sup"]).all()),
            "buzilish": [str(m) for m in rep.mismatches],
        }
    finally:
        s.close()


def _dreyf_yoq(h, *, kelgan=QTY):
    """MIQDOR DREYFI YO'Q — har poygadan keyingi majburiy tekshiruv.

    ⚠️  UCHALA SHART HAM KERAK. Faqat invariantni o'qish YETMAYDI: u qoldiq bilan
        partiyani solishtiradi, ya'ni IKKALASI birga surilsa ham «butun» deydi.
        `kelgan` (Σ received_qty) esa kogorta identifikatsiyasini ushlab turadi —
        tuzatish uni HECH QACHON qayta yozmaydi (faqat teskari yozuv qo'shadi).
    """
    assert h["buzilish"] == [], f"qoldiq partiyalardan AJRALDI: {h}"
    assert h["inv"] == h["qoldiq"] - h["qarz"], f"miqdor DREYF qildi: {h}"
    assert h["kelgan"] == _q(kelgan), f"kelgan miqdor QAYTA YOZILDI: {h}"
    # `void` — qabul bekor qilingan kogorta: u MIQDOR TASHIMAYDI (stock_invariant).
    assert all(r == 0 for _b, st, r, _rq in h["lots"] if st == "void"), h


def _natija(r):
    """("ok", qiymat) yoki (HTTP holati, matn); boshqa istisno — sinov QIZIL."""
    if isinstance(r, HTTPException):
        return r.status_code, r.detail
    assert not isinstance(r, Exception), f"kutilmagan istisno: {r!r}"
    return "ok", r


def _ortiq_matn(d, qoldiq, teskari=QTY):
    """`LOT_CORRECTION_EXCEEDS_REMAINING` matni — server bilan AYNAN."""
    return (f"'{d['nom']}': partiyada {_q(qoldiq)} qoldi, {_q(teskari)} teskari "
            f"qilinmoqda — jismoniy partiya MANFIYGA tushmaydi.")


# ══ 1. IKKI MARTA BEKOR QILISH — KETMA-KET ═══════════════════════════════════

def test_PG_toliq_bekor_TAKROR_duplicate_IKKINCHI_bekor_404(pg_target):
    """Bekor qilingan hujjat TERMINAL. Ikkinchi bekor qilish 404 (ikkinchi
    ta'minotchi tuzatishi va ikkinchi naqd qaytarish YOZILMASIN), AYNI
    `client_uuid` bilan takror esa BIRINCHI javobni qaytaradi — tarmoq uzilib
    qayta yuborilgan bekor qilish operatorga «topilmadi» bo'lib qaytmaydi."""
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        cu = uuid.uuid4()
        s = S()
        try:
            r1 = _bekor(d, cu=cu)(s)
        finally:
            s.close()
        assert r1["ok"] is True and r1["cancelled"] is True, r1
        assert r1["duplicate"] is False and r1["purchase_status"] == "cancelled", r1
        assert r1["reversed_total"] == 500.0 and r1["delta_total"] == -500.0, r1

        h = _holat(S, d)
        _dreyf_yoq(h)
        assert h["inv"] == _q(0) and h["qoldiq"] == 0, h
        assert [(st, r) for _b, st, r, _rq in h["lots"]] == [("void", _q(0))], h
        assert h["tuzatish"] == 1 and h["hujjat"][0] == "cancelled" and h["hujjat"][3] is True, h
        assert h["hujjat"][1] == Decimal("0.00"), h
        assert h["balans"] == Decimal("0.00"), h
        assert h["defter"] == [("adjustment", "receiving_correction", Decimal("-500.00")),
                               ("charge", "receiving", Decimal("500.00"))], h
        assert h["harakat"] == [("receiving", "purchase_in", _q(10)),
                                ("receiving_correction", "adjustment", _q(-10))], h

        # TAKROR — AYNI `client_uuid`, AYNI mazmun: BIRINCHI javob (404 EMAS).
        s = S()
        try:
            r2 = _bekor(d, cu=cu)(s)
        finally:
            s.close()
        assert r2["duplicate"] is True and r2["correction_id"] == r1["correction_id"], r2
        assert r2["cancelled"] is True and r2["delta_total"] == r1["delta_total"], r2

        # IKKINCHI (yangi `client_uuid`) bekor qilish — hujjat o'chirilgan: 404.
        s = S()
        try:
            with pytest.raises(HTTPException) as ei:
                _bekor(d)(s)
        finally:
            s.close()
        assert ei.value.status_code == 404 and ei.value.detail == "Kirim topilmadi", ei.value.detail

        keyin = _holat(S, d)
        assert keyin == h, f"takror/ikkinchi bekor IZ qoldirdi: {h} -> {keyin}"
        _dreyf_yoq(keyin)
    finally:
        eng.dispose()


# ══ 2. IKKI PARALLEL BEKOR QILISH ════════════════════════════════════════════

def test_PG_IKKI_konkurrent_bekor_BITTASI_otadi_boshqasi_404(pg_target):
    """Ikki operator (yoki ikki oyna) ayni hujjatni bir vaqtda bekor qiladi.

    ⚠️  HUJJAT QULFIDAN KEYINGI `deleted_at` QAYTA TEKSHIRUVINING ISBOTI. Qulfsiz
        (yoki qulf ostida qayta o'qimasdan) ikkinchi oqim ESKI suratga tayanib
        ikkinchi teskari yozuvni va IKKINCHI ta'minotchi tuzatishini yozardi:
        balans −500 emas, −1000 bo'lardi, partiya esa MANFIYGA tushardi.
    """
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        r = _navbat(eng, S, _ushla(_bekor(d)), _bekor(d))
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert r["kutdi"] is True, f"ikkinchi bekor qilish hujjat qulfini KUTMADI: {r}"
        kod_a, qiymat_a = _natija(r["a"])
        assert kod_a == "ok" and qiymat_a["cancelled"] is True, r
        kod_b, qiymat_b = _natija(r["b"])
        assert kod_b == 404 and qiymat_b == "Kirim topilmadi", r
        assert h["tuzatish"] == 1, f"ikkinchi tuzatish sarlavhasi YOZILDI: {h}"
        assert h["inv"] == _q(0) and [st for _b, st, _r, _rq in h["lots"]] == ["void"], h
        assert h["balans"] == Decimal("0.00"), f"ta'minotchi balansi IKKI marta siljidi: {h}"
        assert h["defter"] == [("adjustment", "receiving_correction", Decimal("-500.00")),
                               ("charge", "receiving", Decimal("500.00"))], h
        assert h["ulush"] == 1, f"ikkinchi allokatsiya yozildi: {h}"
    finally:
        eng.dispose()


# ══ 3. BEKOR QILISH × OMBOR YOZUVCHILARI — IKKALA TARTIBDA ═══════════════════

@pytest.mark.parametrize("yozuvchi", ["sotuv", "hisobdan", "sanoq"])
@pytest.mark.parametrize("tartib", ["tuzatish_avval", "yozuvchi_avval"])
def test_PG_bekor_x_yozuvchi_poygasi(pg_target, yozuvchi, tartib):
    """Bekor qilish va ombor yozuvchisi AYNI partiyaga tegadi.

    `tuzatish_avval`: yozuvchi tuzatish qulfida KUTADI va BEKOR QILINGAN holatni
        ko'radi — bo'sh qoldiqdan sotib/chiqarib bo'lmaydi, `void` kogortani
        sanab ham bo'lmaydi. Qulfsiz u ESKI (10 dona) suratga tayanib yozardi va
        qoldiq partiyalardan AJRALARDI.
    `yozuvchi_avval`: tuzatish KUTADI va kamaygan qoldiqni ko'radi — to'liq
        teskari qilish endi jismoniy partiyani MANFIYGA tushirardi, shu bois
        barqaror kod bilan RAD etiladi. Qulfsiz u `remaining = 10` ni o'qib
        o'tib ketardi va partiya −2 bo'lardi (YO'QOLGAN YANGILANISH).
    """
    from app.core import error_codes as EC
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        yoz = YOZUVCHILAR[yozuvchi](d)
        if tartib == "tuzatish_avval":
            r = _navbat(eng, S, _ushla(_bekor(d)), yoz)
        else:
            r = _navbat(eng, S, _ushla(yoz), _bekor(d))
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert r["kutdi"] is True, f"{yozuvchi}/{tartib}: ikkinchi oqim KUTMADI: {r}"
        kod_a, _ = _natija(r["a"])
        assert kod_a == "ok", r
        kod_b, qiymat_b = _natija(r["b"])

        if tartib == "tuzatish_avval":
            # Hujjat bekor qilindi; yozuvchi bo'sh/`void` kogortaga tegolmaydi.
            assert r["a"]["cancelled"] is True, r
            assert h["tuzatish"] == 1 and h["hujjat"][0] == "cancelled", h
            assert h["inv"] == _q(0), h
            assert [(st, rem) for _b, st, rem, _rq in h["lots"]] == [("void", _q(0))], h
            if yozuvchi == "sanoq":
                # Sanoq qoldiq yetarliligini tekshirmaydi — u `void` kogorta
                # darvozasiga boradi (`lot_writeoff.plan_count`).
                assert kod_b == 400 and "'void'" in qiymat_b, r
            else:
                assert kod_b == 400 and "Yetarli qoldiq yo'q" in qiymat_b, r
            assert h["ulush"] == 1, f"yozuvchi allokatsiya yozdi: {h}"
        else:
            # Yozuvchi o'tdi; to'liq teskari qilish endi partiyani manfiyga tushirardi.
            qoldiq = QOLDIQ_KEYIN[yozuvchi]
            assert kod_b == 409, r
            assert qiymat_b == _ortiq_matn(d, qoldiq), r
            assert (r["b"].headers or {}).get("X-Error-Code") == \
                EC.LOT_CORRECTION_EXCEEDS_REMAINING, r
            assert h["tuzatish"] == 0, f"RAD ETILGAN tuzatish sarlavha qoldirdi: {h}"
            assert h["inv"] == _q(qoldiq), h
            assert [(st, rem) for _b, st, rem, _rq in h["lots"]] == [("open", _q(qoldiq))], h
            assert h["hujjat"] == ("debt", Decimal("500.00"), Decimal("0.00"), False), h
            assert h["balans"] == Decimal("500.00"), h
            assert not any(rt == "receiving_correction" for rt, _t, _q2 in h["harakat"]), h
    finally:
        eng.dispose()


@pytest.mark.parametrize("tartib", ["tuzatish_avval", "sotuv_avval"])
def test_PG_QISMAN_tuzatish_x_SOTUV_IKKALASI_otadi_dreyf_YOQ(pg_target, tartib):
    """IKKALA yozuvchi ham O'TADIGAN yagona poyga — dreyf tekshiruvi shu yerda ISHLAYDI.

    ⚠️  RAD ETISH BILAN TUGAGAN POYGA DREYFNI O'LCHAMAYDI: bir tomon hech narsa
        yozmasa, «qoldiq = partiyalar» tengligi arzon saqlanadi. Bu yerda esa
        ikkala tomon ham AYNI kogortani kamaytiradi (sotuv 2, tuzatish 3) va
        yakuniy qoldiq AYNAN 5 bo'lishi shart. Qulfsiz ikkalasi ham
        `remaining = 10` ni o'qib, oxirgi yozuvchi birinchisini BOSIB o'tardi:
        partiya 8 yoki 7 bo'lib qolar, qoldiq esa 5 — ya'ni tovar JIMGINA
        «paydo bo'lardi» (YO'QOLGAN YANGILANISH).
    """
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        tuz = _tuzat(d, [(d["batch"][0], Decimal("3"))])
        sot = _sotuv(d, qty=2)
        r = (_navbat(eng, S, _ushla(tuz), sot) if tartib == "tuzatish_avval"
             else _navbat(eng, S, _ushla(sot), tuz))
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert r["kutdi"] is True, f"{tartib}: ikkinchi oqim KUTMADI: {r}"
        assert _natija(r["a"])[0] == "ok" and _natija(r["b"])[0] == "ok", r
        assert h["inv"] == _q(5), f"sotuv va tuzatish BIRGA 5 qoldirishi shart: {h}"
        assert [(st, rem, rq) for _b, st, rem, rq in h["lots"]] == \
            [("open", _q(5), _q(10))], h
        assert h["ulush"] == 1 and h["sotuv_ulush"] == 1, h
        assert h["tuzatish"] == 1, h
        # Sotuv HUJJAT summasiga tegmaydi; tuzatish faqat 3×50 ni oladi.
        assert h["hujjat"] == ("debt", Decimal("350.00"), Decimal("0.00"), False), h
        assert h["balans"] == Decimal("350.00"), h
    finally:
        eng.dispose()


# ══ 4. AYNI `client_uuid` BILAN IKKI KONKURRENT TUZATISH ═════════════════════

def test_PG_AYNI_client_uuid_IKKI_konkurrent_tuzatish_BIR_MARTA(pg_target):
    """Tarmoq uzilib, UI AYNI tuzatishni qayta yuboradi — ikkinchisi birinchi
    tranzaksiya OCHIQ turganda keladi.

    ⚠️  BIRINCHI QADAMDAGI (QULFSIZ) TAKROR QIDIRUVI BU YERDA KO'R. Ikkinchi
        oqim sarlavhani KO'RMAYDI (u hali commit bo'lmagan) va hujjat qulfida
        navbatga turadi. Qulfni olganida BIRINCHISI allaqachon commit qilgan:
        qulf OSTIDAGI takror qidiruvi bo'lmaganda chegaralar («partiyada 7
        qoldi, 3 teskari qilinmoqda» emas, balki ikkinchi kamaytirish) ni
        qo'llab, qoldiqni IKKI marta siljitardi.
    """
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        cu = uuid.uuid4()
        rev = [(d["batch"][0], Decimal("3"))]
        r = _navbat(eng, S, _ushla(_tuzat(d, rev, cu=cu)), _tuzat(d, rev, cu=cu))
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert r["kutdi"] is True, f"ikkinchi yuborish qulfni KUTMADI: {r}"
        kod_a, qiymat_a = _natija(r["a"])
        kod_b, qiymat_b = _natija(r["b"])
        assert kod_a == "ok" and qiymat_a["duplicate"] is False, r
        assert kod_b == "ok" and qiymat_b["duplicate"] is True, r
        assert qiymat_b["correction_id"] == qiymat_a["correction_id"], r
        assert qiymat_b["reversed_total"] == qiymat_a["reversed_total"] == 150.0, r

        assert h["tuzatish"] == 1, f"takror IKKINCHI sarlavha yozdi: {h}"
        assert h["inv"] == _q(7) and [(st, rem) for _b, st, rem, _rq in h["lots"]] == \
            [("open", _q(7))], h
        assert h["ulush"] == 1, f"qoldiq IKKI marta siljidi: {h}"
        assert h["hujjat"] == ("debt", Decimal("350.00"), Decimal("0.00"), False), h
        assert h["balans"] == Decimal("350.00"), h
        assert h["defter"] == [("adjustment", "receiving_correction", Decimal("-150.00")),
                               ("charge", "receiving", Decimal("500.00"))], h
    finally:
        eng.dispose()


def test_PG_konkurrent_TAKROR_BEKOR_qilish_DUPLICATE_oladi_BIR_MARTA_qollanadi(pg_target):
    """Konkurrent takror ham BIRINCHI javobni oladi — 404 EMAS.

    ⚠️  ILGARI 404 EDI (shu sinov o'lchagan). Hujjat qulfi ostida `deleted_at`
        qayta tekshiruvi takror qidiruvidan OLDIN turardi: to'liq bekor qilish
        `deleted_at` ni o'rnatgani uchun, ayni `client_uuid` bilan kelgan
        ikkinchi so'rov «Kirim topilmadi» olardi — ya'ni operatorga BAJARILGAN
        amali uchun «hujjat yo'q» deyilardi va u qayta urinishga tushardi.
        Endi takror qidiruvi `deleted_at` dan OLDIN: takror HAR DOIM birinchi
        javobni qaytaradi, natija hujjatga nima qilganidan qat'i nazar.

    Pul va qoldiq tomoni o'zgarmadi: ikkinchi teskari yozuv, ikkinchi ta'minotchi
    tuzatishi va ikkinchi sarlavha YOZILMAYDI.
    """
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        cu = uuid.uuid4()
        r = _navbat(eng, S, _ushla(_bekor(d, cu=cu)), _bekor(d, cu=cu))
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert r["kutdi"] is True, r
        kod_a, qiymat_a = _natija(r["a"])
        assert kod_a == "ok" and qiymat_a["cancelled"] is True, r
        kod_b, qiymat_b = _natija(r["b"])
        assert kod_b == "ok" and qiymat_b["duplicate"] is True, r
        assert qiymat_b["correction_id"] == qiymat_a["correction_id"], r
        assert qiymat_b["cancelled"] is True, r
        assert h["tuzatish"] == 1, h
        assert h["ulush"] == 1 and h["inv"] == _q(0), h
        assert h["balans"] == Decimal("0.00"), h
        assert h["defter"] == [("adjustment", "receiving_correction", Decimal("-500.00")),
                               ("charge", "receiving", Decimal("500.00"))], h
    finally:
        eng.dispose()


# ══ 5. RAD ETISH — TRANZAKSIYA ROSTDAN QAYTADI ═══════════════════════════════

def test_PG_RAD_etilgan_tuzatish_IZ_qoldirmaydi_client_uuid_KUYMAYDI(pg_target):
    """Yakuniy darvoza commit'dan OLDIN — `rollback()` ROSTDAN qaytarsin.

    ⚠️  SARLAVHA HODISALARDAN OLDIN YOZILADI (`ux_recv_corr_client` ni AYNI
        tranzaksiyada band qilish uchun). Agar rad etish uni qoldirsa, ikki
        zarar bo'lardi: (1) `client_uuid` KUYARDI — operatorning qayta urinishi
        «boshqa so'rov / yakunlanmagan» 409 iga urilardi; (2) hujjat abadiy
        `LOT_CORRECTION_DOC_LOCKED` bo'lib, `PATCH /purchases/{id}` ham
        yopilardi — ya'ni BAJARILMAGAN amal hujjatni qulflab qo'yardi.

    Invariant ATAYLAB oldindan buziladi (qoldiq 11, partiya 10): darvoza
    HAQIQIY, `assert_ok` almashtirilmaydi.
    """
    from app.core import error_codes as EC
    from app.models.inventory import Inventory
    from app.services import lot_correction as LC
    eng, S = _baza(pg_target)
    try:
        d = _qabul(S, _dokon(S))
        s = S()
        try:
            s.query(Inventory).filter(Inventory.product_id == d["pid"],
                                      Inventory.branch_id == d["bid"]).update(
                {"qty": Decimal("11")})
            s.commit()
        finally:
            s.close()
        oldin = _holat(S, d)
        assert oldin["buzilish"] != [], "invariant buzilmadi — sinov o'lchamaydi"

        cu = uuid.uuid4()
        rev = [(d["batch"][0], Decimal("3"))]
        s = S()
        try:
            with pytest.raises(HTTPException) as ei:
                _tuzat(d, rev, cu=cu)(s)
        finally:
            s.close()
        assert ei.value.status_code == 409, ei.value.detail
        assert ei.value.detail == ("Tuzatishni yozib bo'lmadi — partiya va qoldiq mos "
                                   "kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga "
                                   "murojaat qiling."), ei.value.detail
        assert (ei.value.headers or {}).get("X-Error-Code") == EC.LOT_INVARIANT_BROKEN
        # Xom UUID va ichki nomlar operatorga SIZMAYDI (Phase 4B.1 shartnomasi).
        for sir in (str(d["pid"]), str(d["bid"]), str(d["rec"]), str(d["batch"][0]),
                    "≠", "stock_invariant", "InvariantBroken"):
            assert sir not in ei.value.detail, f"{sir!r} operatorga sizib chiqdi"

        keyin = _holat(S, d)
        assert keyin == oldin, f"rad etilgan tuzatish IZ qoldirdi: {oldin} -> {keyin}"
        assert keyin["tuzatish"] == 0 and keyin["ulush"] == 0, keyin
        s = S()
        try:
            assert LC.doc_has_correction(s, d["cid"], d["pur"]) is False, \
                "bajarilmagan tuzatish hujjatni PATCH uchun QULFLAB qo'ydi"
        finally:
            s.close()

        # MANFIY NAZORAT: qoldiq tiklansa AYNI so'rov AYNI `client_uuid` bilan
        # o'tadi — ya'ni 409 kiritma emas, aynan buzilgan invariant bergan va
        # idempotentlik kaliti KUYMAGAN.
        s = S()
        try:
            s.query(Inventory).filter(Inventory.product_id == d["pid"],
                                      Inventory.branch_id == d["bid"]).update(
                {"qty": Decimal("10")})
            s.commit()
        finally:
            s.close()
        s = S()
        try:
            r = _tuzat(d, rev, cu=cu)(s)
        finally:
            s.close()
        assert r["ok"] is True and r["duplicate"] is False, r
        assert r["reversed_total"] == 150.0 and r["cancelled"] is False, r
        h = _holat(S, d)
        _dreyf_yoq(h)
        assert h["inv"] == _q(7) and h["tuzatish"] == 1 and h["ulush"] == 1, h
        assert h["hujjat"] == ("debt", Decimal("350.00"), Decimal("0.00"), False), h
        assert h["balans"] == Decimal("350.00"), h
    finally:
        eng.dispose()


# ══ 6. «TO'LIQ TESKARI QILINDIMI» QARORI — FAQAT QULFLANGAN QATORLARDAN ══════

def _ikki_qatorli(S, d):
    """Ikkinchi mahsulot + IKKI qatorli qabul (2-qator BEPUL, tannarx 0).

    ⚠️  BEPUL QATOR ATAYLAB. «Hujjat to'liq teskari qilindimi» qarorini PULDAN
        ajratish uchun: 1-qatorni to'liq teskari qilish hujjat jamini nolga
        tushiradi, 2-qatorning kogortasi esa hamon MIQDOR tashiydi. Aynan shu
        holatda qaror tuzatish TEGMAGAN va QULFLAMAGAN qatorga tayanardi.
    """
    from app.api.v1.receiving import CommitIn, commit
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory, StockBatch
    from app.models.purchasing import PurchaseItem
    from app.models.receiving import Receiving
    s = S()
    try:
        unit = s.query(Unit).filter(Unit.code == "dona").first() or s.query(Unit).first()
        nom2 = "5D-2 " + uuid.uuid4().hex[:6]
        p2 = Product(id=uuid.uuid4(), company_id=d["cid"], name=nom2,
                     article_code="5D2-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                     unit_id=unit.id, base_buy_price=0, base_sell_price=10, tax_rate=0,
                     track_lots=True)
        s.add(p2)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p2.id, branch_id=d["bid"],
                        qty=Decimal("0"), min_qty=0, updated_at=NOW))
        s.commit()
        pid2 = p2.id
    finally:
        s.close()
    s = S()
    try:
        r = commit(CommitIn(items=[
            {"product_id": str(d["pid"]), "qty": float(QTY), "unit_cost": float(COST),
             "unit": "dona", "lots": [{"qty": float(QTY)}]},
            {"product_id": str(pid2), "qty": float(QTY), "unit_cost": 0,
             "unit": "dona", "lots": [{"qty": float(QTY)}]}],
            supplier_id=d["sup"], payment="credit", source="manual",
            client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)
        assert r["ok"] is True, r
    finally:
        s.close()
    s = S()
    try:
        rec = s.get(Receiving, uuid.UUID(r["receiving_id"]))
        items = {it.product_id: it.id for it in s.query(PurchaseItem).filter(
            PurchaseItem.purchase_id == rec.purchase_id).all()}
        b1 = (s.query(StockBatch).filter(StockBatch.receiving_id == rec.id,
                                         StockBatch.product_id == d["pid"]).one())
        b2 = (s.query(StockBatch).filter(StockBatch.receiving_id == rec.id,
                                         StockBatch.product_id == pid2).one())
        d.update({"rec": rec.id, "pur": rec.purchase_id, "item": items[d["pid"]],
                  "batch": [b1.id], "pid2": pid2, "item2": items[pid2], "batch2": b2.id})
        return d
    finally:
        s.close()


def test_PG_bekor_qarori_QULFLANMAGAN_kogortaga_TAYANMAYDI(pg_target):
    """⚠️  QARORNI PARALLEL YOZUVCHI HAL QILMASIN.

    Tuzatish 1-qatorni TO'LIQ teskari qiladi (hujjat jami 0 ga tushadi), lekin
    hujjatni bekor qilish uchun BUTUN qabulda qoldiq qolmagani ham shart.
    2-qatorning kogortasi bu tuzatishda UMUMAN qatnashmaydi — ilgari uni
    qulfsiz SELECT o'qirdi va parallel hisobdan chiqarish (kogortani nolga
    tushirayotgan, hali COMMIT qilmagan) qarorga UMUMAN kirmasdi: hujjat
    «hali tovar bor» deb tirik qolardi, holbuki tranzaksiyalar tugaganda
    qabulda birorta dona qolmagan.

    Endi tuzatish o'sha kogortani (va uning qoldiq qatorini) ham QULFLAYDI:
    ikkinchi oqim KUTADI va YAKUNIY holatni ko'radi.
    """
    from app.api.v1.inventory import WriteoffIn, writeoff
    from app.models.purchasing import Purchase
    eng, S = _baza(pg_target)
    try:
        d = _ikki_qatorli(S, _dokon(S))

        def _chiqar(s):
            return writeoff(WriteoffIn(
                product_id=d["pid2"], qty=float(QTY), reason="brak",
                client_uuid=uuid.uuid4(),
                lots=[{"stock_batch_id": str(d["batch2"]), "qty": float(QTY)}]),
                emp=_emp(s, d), db=s)

        r = _navbat(eng, S, _ushla(_chiqar), _tuzat(d, [(d["batch"][0], QTY)]))
        assert _natija(r["a"])[0] == "ok", r
        assert r["kutdi"] is True, f"tuzatish hujjatning BOSHQA kogortasini qulflamadi: {r}"
        kod, qiymat = _natija(r["b"])
        assert kod == "ok", r
        assert qiymat["cancelled"] is True, (
            "butun qabulda tovar qolmadi, hujjat esa tirik qoldi", qiymat)
        s = S()
        try:
            pur = s.get(Purchase, d["pur"])
            assert pur.status.value == "cancelled" and pur.deleted_at is not None, (
                pur.status, pur.deleted_at)
            assert Decimal(str(pur.total)) == Decimal("0.00"), pur.total
        finally:
            s.close()
        _dreyf_yoq(_holat(S, d))
    finally:
        eng.dispose()
