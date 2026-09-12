# -*- coding: utf-8 -*-
"""HUJJAT HISOBLAGICHLARINING IZOLYATSIYASI (Phase 3.5, 6-band).

⚠️  NEGA ALOHIDA FAYL. Phase 3 da bu nuqson JONLI KANONIK TO'PLAMDA otildi:

        INSERT INTO doc_counters ... next_value = 9637078514
        psycopg.errors.NumericValueOutOfRange: integer out of range

    Sabab: `_seed()` namunasi `(\\d+)\\s*$` edi va u HAR QANDAY qiymatning
    oxirgi raqamlarini olardi. Tasodifiy heksa identifikator (`R3f9637078513`)
    10+ raqam bilan tugasa — hisoblagich `INTEGER` chegarasidan oshib, butun
    sotuv yo'li YIQILARDI. Ehtimollik ~1%, ya'ni jonli bazada ham kutilmaganda
    otilishi mumkin edi.

    Xuddi shu yo'l bilan `/reports/history/seed` yozgan `H<1C raqami>` chek
    raqami jonli chek hisoblagichini ming marta oldinga surib yuborardi.

Bu fayl uch narsani ABADIY mahkamlaydi:
  1. Hisoblagich FAQAT o'z prefiksidagi hujjatlarni o'qiydi.
  2. Har tur (sotuv / qaytarish / kirim) BOSHQASINING raqamlariga ta'sir
     qilmaydi — ular bir jadvalda yashasa ham.
  3. Chegaradan oshgan qiymat xom `DataError` emas, TUSHUNARLI xato beradi.
"""
import re
import uuid
from datetime import datetime, timezone

import pytest

from app.services import doc_seq as DS


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def cid(client):
    from app.models.org import Company
    with _db() as db:
        return db.query(Company).first().id


def _pat(kind):
    return re.compile(re.escape(DS.SPEC[kind]["prefix"]) + r"(\d+)")


def _reset_counter(company_id, kind=None):
    from app.models.org import DocCounter
    with _db() as db:
        q = db.query(DocCounter).filter(DocCounter.company_id == company_id)
        if kind:
            q = q.filter(DocCounter.kind == kind)
        q.delete()
        db.commit()


# ══ 1. NAMUNA — FAQAT O'Z FORMATI ═══════════════════════════════════════════

@pytest.mark.parametrize("kind,good,bad", [
    (DS.SALE, ["#1288", "#1"],
     ["H1C00012345", "H000000999999", "R3f9637078513", "QAY-1001", "KIR-1042",
      "#1288x", "TMP-sale-" + "a" * 8, "1288", "", "#"]),
    (DS.RETURN, ["QAY-1001"],
     ["#1288", "KIR-1042", "H1C00012345", "QAY-", "QAY1001", "R9637078513"]),
    (DS.PURCHASE, ["KIR-1042"],
     ["#1288", "QAY-1001", "H1C00012345", "KIR-", "KIR1042", "R9637078513"]),
])
def test_SEED_namunasi_FAQAT_oz_prefiksini_oladi(kind, good, bad):
    pat = _pat(kind)
    for v in good:
        assert pat.fullmatch(v), (kind, v)
    for v in bad:
        assert not pat.fullmatch(v), (kind, v)


def test_TASODIFIY_identifikator_hisoblagichni_ZAHARLAMAYDI():
    """⚠️  AYNAN KANONIK TO'PLAMNI YIQITGAN QIYMAT."""
    assert not _pat(DS.SALE).fullmatch("R3f9637078513")
    # Eski namuna esa uni QABUL QILARDI — sinov bo'sh bo'lmasin.
    assert re.compile(r"(\d+)\s*$").search("R3f9637078513").group(1) == "9637078513"


# ══ 2. JONLI HISOBLAGICH — BEGONA CHEK TA'SIR QILMAYDI ══════════════════════

def _make_sale(cid, receipt_no):
    from app.models.sales import Sale
    with _db() as db:
        from app.models.auth import Employee
        from app.models.org import Branch
        emp = db.query(Employee).filter(Employee.company_id == cid).first()
        br = db.query(Branch).filter(Branch.company_id == cid).first()
        db.add(Sale(id=uuid.uuid4(), company_id=cid, branch_id=br.id,
                    cashier_id=emp.id, sold_at=_now(), subtotal=0, discount_total=0,
                    tax_total=0, total=0, cost_total=0, status="completed",
                    receipt_no=receipt_no, client_uuid=uuid.uuid4(), is_offline=False))
        db.commit()


def test_TARIXIY_H_cheki_jonli_chek_raqamini_SURMAYDI(client, cid):
    """`/reports/history/seed` yozadigan shakl — hisoblagichga TEGMASIN.

    ⚠️  Ilgari `H1C00012345` seed'ni 12 346 ga ko'tarardi va keyingi HAQIQIY
        chek `#1288` o'rniga `#12346` bo'lib chiqardi.
    """
    _make_sale(cid, "H1C00012345")
    _make_sale(cid, "R" + uuid.uuid4().hex[:6] + "9637078513")
    _reset_counter(cid, DS.SALE)
    with _db() as db:
        n = DS.allocate(db, cid, DS.SALE)
        db.commit()
    assert n < 100000, f"begona chek hisoblagichni surdi: {n}"


def test_TURLAR_BIR_BIRIGA_tasir_qilmaydi(client, cid):
    """Sotuv / qaytarish / kirim hisoblagichlari MUSTAQIL."""
    _make_sale(cid, "#5000")
    _reset_counter(cid)
    with _db() as db:
        s = DS.allocate(db, cid, DS.SALE)
        r = DS.allocate(db, cid, DS.RETURN)
        p = DS.allocate(db, cid, DS.PURCHASE)
        db.commit()
    # ⚠️  ABSOLYUT QIYMAT TEKSHIRILMAYDI. Baza to'plam bo'yicha ulashiladi va
    #     oldingi sinovlar allaqachon qaytarish/kirim hujjatlari yaratgan
    #     bo'lishi mumkin — «aynan base+1» degan tasdiq mahsulotni emas,
    #     TO'PLAM TARTIBINI o'lchardi. MUHIM qoida: sotuvning katta raqami
    #     BOSHQA hisoblagichlarga SIZIB O'TMAYDI.
    assert s == 5001, s                              # '#5000' dan davom etadi
    assert r < 5000, f"sotuv raqami qaytarishga sizdi: {r}"
    assert p < 5000, f"sotuv raqami kirimga sizdi: {p}"
    assert r >= DS.SPEC[DS.RETURN]["base"], r        # o'z bazasidan pastga tushmaydi
    assert p >= DS.SPEC[DS.PURCHASE]["base"], p


def test_KIRIM_va_XARID_AYNI_hisoblagichni_ULASHADI(client, admin_headers, cid):
    """Ikkalasi ham `KIR-` — bu ONGLI: bitta hujjat oqimi, bitta raqam qatori."""
    import inspect

    from app.api.v1 import purchases, receiving
    for mod in (purchases, receiving):
        src = inspect.getsource(mod)
        assert "_DS.next_no(db, emp.company_id, _DS.PURCHASE)" in src, mod.__name__


# ══ 3. CHEGARA — TUSHUNARLI XATO ════════════════════════════════════════════

def test_INTEGER_chegarasidan_oshsa_TUSHUNARLI_xato(client, cid):
    """Xom `NumericValueOutOfRange` emas — nima qilish kerakligi aytiladi.

    ⚠️  O'ZIDAN KEYIN TOZALAYDI. Baza butun to'plam bo'yicha ULASHILADI;
        `#2500000000` cheki qolib ketsa, KEYINGI har bir sotuv `_seed()` ga
        tushib shu xato bilan yiqilardi — ya'ni bitta sinov 79 tasini
        o'ldirardi (kanonik to'plamda aynan shunday bo'ldi).
    """
    from app.models.sales import Sale as _S
    _make_sale(cid, "#2500000000")
    try:
        _reset_counter(cid, DS.SALE)
        with _db() as db:
            with pytest.raises(ValueError, match="juda katta"):
                DS.allocate(db, cid, DS.SALE)
    finally:
        with _db() as db:
            db.query(_S).filter(_S.company_id == cid,
                                _S.receipt_no == "#2500000000").delete()
            db.commit()
        _reset_counter(cid, DS.SALE)


def test_HISOBLAGICH_ustuni_INTEGER_ekani_PIN_qilinadi():
    """Chegara tekshiruvi shu tipga bog'liq — tip o'zgarsa test eslatadi."""
    from sqlalchemy import Integer

    from app.models.org import DocCounter
    assert isinstance(DocCounter.__table__.c.next_value.type, Integer)
