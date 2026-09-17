# -*- coding: utf-8 -*-
"""B3 — AKTIVATSIYADAN OLDINGI CHEKNI QAYTARISH: HAQIQIY POSTGRES (Phase 5C).

SQLite nimani o'lchay olmaydi: `FOR UPDATE` u yerda no-op. Bu yerda qaytarish
`/lots/enable` bilan HAQIQATAN interleaving qilinadi — yoqish yozib, commit
QILMAY turadi; qaytarish uning qulfini kutayotgani `pg_blocking_pids` da
ko'rilgach yoqish commit qiladi (`test_lot_tz_confirm_pg._navbat`).

Isbotlanadi:
  1. aktivatsiyadan oldingi chek, `restock=False` -> OK: partiya, qarz va
     taqsimot TEGILMAYDI, qoldiq +1 keyin −1 (NOL), invariant butun;
  2. AYNI chek, `restock=True` -> 409 + `X-Error-Code: LOT_RETURN_PRE_ACTIVATION`,
     bazaga HECH NARSA yozilmaydi;
  3. qaytarish o'rtasida `/lots/enable` commit qilsa (poyga): ichki
     `_KuzatuvOzgardi` qayta urinishi yangi bayroq bilan qaror beradi —
     invariant butun, qaytarish BITTA (pul ikki marta qaytmaydi);
  4. AYNI chekni IKKI kassa bir vaqtda restock'siz qaytarsa — ikkinchisi asl chek
     qulfida kutadi va «sotilganidan oshiq» bilan 400 oladi.

⚠️  4-band NEGA SHU YERDA. Aktivatsiyadan oldingi yo'lda partiya HAM, qarz HAM
    tegilmaydi va `assert_caps` CHAQIRILMAYDI (tegilmagan narsa tekshirilmaydi),
    qoldiq esa +k keyin −k bo'lib NOL qoladi — ya'ni yakuniy invariant darvozasi
    ham, partiya cheklari ham bu yerda HECH NIMANI ushlamaydi. Pulni ikki marta
    berishdan saqlaydigan YAGONA narsa — asl chek qatori qulfi (`Sale ... FOR
    UPDATE`) va undan KEYIN o'qiladigan «sotilganidan oshmasin» hisobi. SQLite buni
    o'lchay olmaydi (`FOR UPDATE` u yerda no-op), shu bois isbot AYNAN PG'da.

MANFIY NAZORAT — bu fayl eski kodda (537d20b, yoqishdan oldingi chekka BARIBIR
409) QIZIL bo'lgani PG'da o'lchandi: 1, 2 va 3-band yiqildi (1/3: `409 == 'ok'`,
umumiy «bog'lab bo'lmadi» matni bilan; 2: matn va `X-Error-Code` YO'Q).
`test_lot_enable_race_pg.py::...[pgserver-qaytarish_restocksiz]` ham qizil edi.

⚠️  KARTA QAYTARISH. Bo'sh sinov bazasida naqd ledger'i (`cash` sxemasi TILL'lari)
    sozlanmagan; naqd yo'li SQLite to'plamida va `tests/cash` da qoplangan. Bu
    yerda o'lchanadigan narsa — partiya qarori va poyga, pul yo'li emas. «Ikki
    marta qaytmadi» = qaytarish HUJJATI bitta (karta refund'ining pul legi shu).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
"""
import uuid
from decimal import Decimal

from fastapi import HTTPException

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_lot_enable_race_pg import _baza, _dokon, _emp, _holat, _natija, _q, _sotuv
from tests.test_lot_tz_confirm_pg import _navbat

OLDIN_SOTILGAN = ("Bu mahsulot partiya kuzatuvi yoqilishidan OLDIN sotilgan — tovar qaysi "
                  "partiyadan chiqqani NOMA'LUM va tizim uni taxmin qilmaydi. Omborga "
                  "qaytarmasdan (restock'siz) qaytaring.")
KOD = "LOT_RETURN_PRE_ACTIVATION"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _yoq70(d, *, ushlab_tur=True):
    """`/lots/enable`, ochilish partiyasi narxi 70 — sotuv tannarxidan (50) FARQLI.

    Farq ataylab: qaytarish tannarxi ochilish partiyasidan olinsa KO'RINADI.
    `ushlab_tur` — commit o'rniga flush (tranzaksiyani `_navbat` commit qiladi).
    """
    from app.api.v1.lots import EnableIn, enable_tracking

    def go(s):
        body = EnableIn(product_id=d["pid"], branch_id=d["bids"][0],
                        reason="B3 PG: kuzatuvni yoqish", legacy_unit_cost=70)
        if not ushlab_tur:
            return enable_tracking(body, emp=_emp(s, d), db=s)
        s.commit = s.flush
        try:
            return enable_tracking(body, emp=_emp(s, d), db=s)
        finally:
            del s.commit
    return go


def _qaytarish(d, sale_id, qty=1, *, restock):
    from app.api.v1.sales import create_return
    from app.schemas.sales import ReturnCreate, ReturnItemIn
    return lambda s: create_return(ReturnCreate(
        original_sale_id=sale_id, reason="customer", restock=restock, refund_method="card",
        client_uuid=uuid.uuid4(), items=[ReturnItemIn(product_id=d["pid"], qty=qty)]),
        emp=_emp(s, d), db=s)


def _ushlab(fn):
    """Tranzaksiyani USHLAB turadi: `commit` o'rniga `flush` — uni `_navbat` commit qiladi.

    Shu bilan birinchi qaytarish asl chek qatorining qulfini ushlab turadi va
    ikkinchisi HAQIQATAN navbatga tushadi (`_yoq70` dagi ayni hiyla).
    """
    def go(s):
        s.commit = s.flush
        try:
            return fn(s)
        finally:
            del s.commit
    return go


def _ish(S, fn):
    """Bitta sessiyada bajaradi; `HTTPException` — natija sifatida qaytadi."""
    s = S()
    try:
        return fn(s)
    except HTTPException as e:
        s.rollback()
        return e
    finally:
        s.close()


def _hujjat(S, d):
    """Qaytarish hujjatlari, qatorlari, taqsimot qatorlari va audit izlari."""
    from app.models.inventory import (ReturnItemLotAllocation, ReturnItemResolutionAllocation,
                                      ReturnItemShortfallAllocation)
    from app.models.sales import Return, ReturnItem
    from app.models.sync import AuditLog
    s = S()
    try:
        rets = s.query(Return).filter(Return.company_id == d["cid"]).all()
        items = s.query(ReturnItem).filter(ReturnItem.product_id == d["pid"]).all()
        return {
            "rets": len(rets),
            "jami": sum((Decimal(str(r.total)) for r in rets), Decimal("0")),
            "items": [(Decimal(str(i.qty)), Decimal(str(i.cost_total)),
                       Decimal(str(i.cost_unresolved or 0))) for i in items],
            "rila": s.query(ReturnItemLotAllocation).filter(
                ReturnItemLotAllocation.product_id == d["pid"]).count(),
            "risa": s.query(ReturnItemShortfallAllocation).filter(
                ReturnItemShortfallAllocation.product_id == d["pid"]).count(),
            "rira": s.query(ReturnItemResolutionAllocation).filter(
                ReturnItemResolutionAllocation.product_id == d["pid"]).count(),
            "audit": s.query(AuditLog).filter(
                AuditLog.entity == "return_pre_activation").count(),
        }
    finally:
        s.close()


def _oldin_sotilgan(S, d):
    """Kuzatuvsiz chek (2 dona) -> keyin kuzatuvni yoqish. Qaytaradi: chek id."""
    s = S()
    try:
        sale_id = _sotuv(d)(s)
    finally:
        s.close()
    assert _ish(S, _yoq70(d, ushlab_tur=False))["ok"] is True
    return sale_id


# ══ 1. RESTOCK'SIZ — O'TADI, PARTIYAGA TEGMASDAN ════════════════════════════

def test_PG_OLDIN_sotilgan_chek_RESTOCKSIZ_qaytadi_PARTIYAGA_TEGMASDAN(pg_target):
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10,))
        b0 = str(d["bids"][0])
        sale_id = _oldin_sotilgan(S, d)
        oldin = _holat(S, d)
        assert oldin["lots"] == [(b0, "legacy", _q(8))], oldin

        r = _ish(S, _qaytarish(d, sale_id, restock=False))
        assert _natija(r)[0] == "ok", r

        h = _holat(S, d)
        assert h["buzilish"] == [], f"qoldiq partiyalardan AJRALDI: {h}"
        assert h["inv"] == oldin["inv"] == {b0: _q(8)}, h
        assert h["lots"] == oldin["lots"] and h["qarz"] == {}, h
        doc = _hujjat(S, d)
        assert doc["rets"] == 1 and (doc["rila"], doc["risa"], doc["rira"]) == (0, 0, 0), doc
        # Tannarx ASL CHEKDAN (50), ochilish partiyasidan (70) EMAS.
        assert doc["items"] == [(_q(1), Decimal("50.00"), Decimal("0.00"))], doc
        assert doc["audit"] == 1, "audit izi yo'q"
    finally:
        eng.dispose()


# ══ 2. RESTOCK — RAD, YOZUVSIZ ══════════════════════════════════════════════

def test_PG_OLDIN_sotilgan_chekni_OMBORGA_qaytarib_BOLMAYDI(pg_target):
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10,))
        sale_id = _oldin_sotilgan(S, d)
        oldin = _holat(S, d)

        r = _ish(S, _qaytarish(d, sale_id, restock=True))
        kod, qiymat = _natija(r)
        assert kod == 409 and qiymat == OLDIN_SOTILGAN, r
        assert (r.headers or {}).get("X-Error-Code") == KOD, r.headers

        h = _holat(S, d)
        assert h == oldin, f"rad etilgan qaytarish holatni o'zgartirdi: {h}"
        assert h["buzilish"] == [], h
        doc = _hujjat(S, d)
        assert (doc["rets"], doc["items"], doc["audit"]) == (0, [], 0), doc
    finally:
        eng.dispose()


# ══ 2b. AYNI CHEK, IKKI KASSA BIR VAQTDA (TOCTOU) ═══════════════════════════

def test_PG_AYNI_chekni_IKKI_kassa_RESTOCKSIZ_bir_marta_qaytaradi(pg_target):
    """Ikki kassa AYNI aktivatsiyadan oldingi chekni bir vaqtda restock'siz qaytaradi.

    Bu yo'lda partiyaga tegilmaydi va `assert_caps` chaqirilmaydi, qoldiq esa
    +2 keyin −2 bo'lib NOL qoladi: yakuniy invariant darvozasi ikki marta pul
    berishni KO'RMAYDI. Ushlab turuvchi yagona narsa — `Sale ... FOR UPDATE` va
    undan KEYIN o'qiladigan «sotilganidan oshmasin» hisobi. Kutish ko'rilmasa
    (`kutdi`) sinov QIZIL: u holda poyga oynasi umuman ochilmagan bo'lardi.
    """
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10,))
        b0 = str(d["bids"][0])
        sale_id = _oldin_sotilgan(S, d)          # 2 dona sotilgan, keyin yoqilgan
        oldin = _holat(S, d)

        r = _navbat(eng, S, _ushlab(_qaytarish(d, sale_id, qty=2, restock=False)),
                    _qaytarish(d, sale_id, qty=2, restock=False))

        assert r["kutdi"] is True, f"ikkinchi qaytarish asl chek qulfini KUTMADI: {r}"
        assert _natija(r["a"])[0] == "ok", r
        kod, qiymat = _natija(r["b"])
        assert kod == 400 and "sotilganidan oshiq" in qiymat, f"IKKINCHI qaytarish o'tdi: {r}"

        h = _holat(S, d)
        assert h["buzilish"] == [], h
        assert h["inv"] == oldin["inv"] == {b0: _q(8)}, h
        assert h["lots"] == oldin["lots"] == [(b0, "legacy", _q(8))] and h["qarz"] == {}, h
        doc = _hujjat(S, d)
        assert doc["rets"] == 1, f"AYNI chek IKKI marta qaytdi: {doc}"
        assert doc["items"] == [(_q(2), Decimal("100.00"), Decimal("0.00"))], doc
        assert doc["audit"] == 1 and (doc["rila"], doc["risa"], doc["rira"]) == (0, 0, 0), doc
    finally:
        eng.dispose()


# ══ 3. POYGA — QAYTARISH O'RTASIDA KUZATUV YOQILADI ════════════════════════

def test_PG_YOQISH_qaytarish_bilan_POYGA_RESTOCKSIZ_bir_marta_qaytadi(pg_target):
    """Qaytarish bayroqni qulfdan OLDIN o'qigan; yoqish qulfni ushlab turibdi.

    Ichki `_KuzatuvOzgardi` qayta urinishi butun tranzaksiyani QAYTARIB, yangi
    bayroq bilan boshidan uradi. Natija: BITTA qaytarish hujjati (pul ikki marta
    qaytmaydi), partiyaga tegilmagan, invariant butun.
    """
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10,))
        b0 = str(d["bids"][0])
        s = S()
        try:
            sale_id = _sotuv(d)(s)         # yoqishdan OLDINGI (kuzatuvsiz) chek
        finally:
            s.close()
        oldin = _holat(S, d)["inv"]

        r = _navbat(eng, S, _yoq70(d), _qaytarish(d, sale_id, restock=False))

        h = _holat(S, d)
        assert h["buzilish"] == [], f"poyga qoldiqni partiyalardan ajratdi: {h} {r}"
        assert r["kutdi"] is True, f"qaytarish yoqish qulfini KUTMADI: {r}"
        assert _natija(r["a"])[0] == "ok" and r["a"]["ok"] is True, r
        assert _natija(r["b"])[0] == "ok", r
        assert h["tracked"] is True and h["inv"] == oldin == {b0: _q(8)}, h
        assert h["lots"] == [(b0, "legacy", _q(8))] and h["qarz"] == {}, h
        doc = _hujjat(S, d)
        assert doc["rets"] == 1, f"qaytarish IKKI MARTA yozildi: {doc}"
        assert len(doc["items"]) == 1 and doc["audit"] == 1, doc
        assert (doc["rila"], doc["risa"], doc["rira"]) == (0, 0, 0), doc
    finally:
        eng.dispose()


def test_PG_YOQISH_qaytarish_bilan_POYGA_RESTOCKLI_RAD_yozuvsiz(pg_target):
    """AYNI poyga, `restock=True`: qayta urinishdan keyin ham B3 rad etadi."""
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S, qoldiq=(10,))
        b0 = str(d["bids"][0])
        s = S()
        try:
            sale_id = _sotuv(d)(s)
        finally:
            s.close()
        oldin = _holat(S, d)["inv"]

        r = _navbat(eng, S, _yoq70(d), _qaytarish(d, sale_id, restock=True))

        h = _holat(S, d)
        assert h["buzilish"] == [], f"{h} {r}"
        assert r["kutdi"] is True, r
        kod, qiymat = _natija(r["b"])
        assert kod == 409 and qiymat == OLDIN_SOTILGAN, r
        assert (r["b"].headers or {}).get("X-Error-Code") == KOD, r
        assert h["inv"] == oldin == {b0: _q(8)} and h["lots"] == [(b0, "legacy", _q(8))], h
        doc = _hujjat(S, d)
        assert (doc["rets"], doc["items"], doc["audit"]) == (0, [], 0), doc
    finally:
        eng.dispose()
