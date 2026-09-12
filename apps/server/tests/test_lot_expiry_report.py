# -*- coding: utf-8 -*-
"""PHASE 3 — MUDDAT HISOBOTI (`GET /lots/expiring`).

Hisobot uch narsani ISBOTLASHI kerak:

  1. Guruhlar KESISHMAYDI va chegaralar filialning BIZNES sanasidan olinadi
     (UTC'dan emas) — bir kunlik xato muddati o'tgan tovarni «yaroqli»
     ko'rsatardi.
  2. Muddati o'tgan partiya QOLDIQDAN YO'QOLMAYDI. «Muddati o'tgan» — holat
     emas, HISOB. Hisobot uni ko'rsatadi, lekin invariantga tegmaydi.
  3. So'rov `ix_lot_expiry` qisman indeksining shartiga AYNAN mos bo'lsin —
     aks holda jonli bazada to'liq jadval skanerlanardi.
"""
import uuid
from datetime import timedelta

from app.services import stock_invariant as SI

from tests.test_lot_fefo_sale import (  # noqa: F401
    NOW,
    _db,
    _enable,
    _lots,
    _product,
    _recv,
    ctx,
    sup,
)

TODAY = NOW.date()
KECHA = TODAY - timedelta(days=1)
ERTAGA = TODAY + timedelta(days=1)
KUN7 = TODAY + timedelta(days=7)
KUN8 = TODAY + timedelta(days=8)
KUN30 = TODAY + timedelta(days=30)
KUN31 = TODAY + timedelta(days=31)


def _exp(client, headers, **kw):
    r = client.get("/api/v1/lots/expiring", headers=headers, params=kw)
    assert r.status_code == 200, r.text
    return r.json()


def _eskirt(pid, eski):
    """Partiyani VAQT O'TISHI bilan eskirtiradi.

    ⚠️  NEGA API ORQALI EMAS. Kirim muddati O'TGAN tovarni QABUL QILMAYDI
        (400) — va bu to'g'ri. Jonli do'konda muddati o'tgan partiya faqat
        BITTA yo'l bilan paydo bo'ladi: yaroqli tovar javonda TURIB qoladi.
        Shu bois sana bevosita orqaga suriladi — bu API'ni chetlab o'tish
        emas, VAQTNI simulyatsiya qilish.
    """
    from app.models.inventory import StockBatch
    with _db() as db:
        n = 0
        for b in (db.query(StockBatch)
                  .filter(StockBatch.product_id == uuid.UUID(pid)).all()):
            b.expiry_date = eski
            n += 1
        db.commit()
        assert n, "eskirtiriladigan partiya topilmadi"


def _mine(body, pid):
    return [l for l in body["lots"] if l["product_id"] == pid]


# ══ 1. GURUHLASH ════════════════════════════════════════════════════════════

def test_guruhlar_CHEGARASI_aniq_va_KESISHMAYDI(client, admin_headers, ctx, sup):
    """Har chegara sanasi AYNAN bitta guruhga tegishli."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    kutilgan = {
        TODAY: "expires_today",
        ERTAGA: "within_7_days",
        KUN7: "within_7_days",
        KUN8: "within_30_days",
        KUN30: "within_30_days",
    }
    for d in kutilgan:
        assert _recv(client, admin_headers, sup, pid, 1, 10, d).status_code == 200
    # Muddati O'TGAN partiya alohida mahsulotda (eskirtirish butun mahsulotga
    # ta'sir qiladi — aralashtirilса yuqoridagi guruhlar buzilardi).
    eski_pid = _product(client, admin_headers)
    _enable(client, admin_headers, eski_pid)
    assert _recv(client, admin_headers, sup, eski_pid, 1, 10, KUN7).status_code == 200
    _eskirt(eski_pid, KECHA)

    body = _exp(client, admin_headers)
    assert _mine(body, eski_pid)[0]["bucket"] == "expired"
    assert body["business_date"] == TODAY.isoformat()
    olindi = {l["expiry_date"]: l["bucket"] for l in _mine(body, pid)}
    for d, g in kutilgan.items():
        assert olindi.get(d.isoformat()) == g, (d, olindi.get(d.isoformat()), g)


def test_GORIZONTDAN_narigi_partiya_KIRMAYDI(client, admin_headers, ctx, sup):
    """31-kun — 30 kunlik gorizontdan tashqarida, hisobotda YO'Q.

    Bu tasodifiy cheklov emas: diapazonsiz so'rov butun jadvalni skanerlardi.
    """
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 1, 10, KUN31).status_code == 200
    assert _mine(_exp(client, admin_headers), pid) == []


def test_MUDDATSIZ_partiya_hisobotda_YOQ(client, admin_headers, ctx, sup):
    """`expiry_date IS NULL` — indeks shartidan ham, hisobotdan ham tashqarida."""
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid, expiry=False)
    assert _recv(client, admin_headers, sup, pid, 5, 10).status_code == 200
    assert _mine(_exp(client, admin_headers), pid) == []


# ══ 2. XAVF OSTIDAGI SUMMA ══════════════════════════════════════════════════

def test_XAVF_summasi_qoldiq_karra_tannarx(client, admin_headers, ctx, sup):
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 3, 25, KUN7).status_code == 200
    _eskirt(pid, KECHA)
    row = _mine(_exp(client, admin_headers), pid)[0]
    assert row["remaining_qty"] == 3.0
    assert row["unit_cost"] == 25.0
    assert row["value_at_risk"] == 75.0
    assert row["days_left"] == -1


def test_YIGINDI_faqat_TANLANGAN_guruhni_emas_HAMMASINI_sanaydi(
        client, admin_headers, ctx, sup):
    """`bucket=` filtri RO'YXATNI qisqartiradi, YIG'INDINI emas.

    Aks holda operator «muddati o'tgan» ni tanlagach, boshqa guruhlar NOL
    ko'rinib, «hammasi joyida» degan noto'g'ri xulosa chiqarardi.
    """
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 2, 10, KUN7).status_code == 200
    _eskirt(pid, KECHA)                       # birinchi partiya eskirdi
    assert _recv(client, admin_headers, sup, pid, 4, 10, KUN8).status_code == 200

    hammasi = _exp(client, admin_headers)
    faqat = _exp(client, admin_headers, bucket="expired")
    assert len(_mine(faqat, pid)) == 1
    assert faqat["summary"]["expired"]["qty"] >= 2.0
    assert faqat["summary"]["within_30_days"]["qty"] >= 4.0
    assert faqat["summary"] == hammasi["summary"]


def test_NOMALUM_guruh_400(client, admin_headers, ctx):
    r = client.get("/api/v1/lots/expiring", headers=admin_headers,
                   params={"bucket": "keyinroq"})
    assert r.status_code == 400, r.text


# ══ 3. MUDDAT — HOLAT EMAS ══════════════════════════════════════════════════

def test_muddati_OTGAN_partiya_QOLDIQDAN_yoqolmaydi(client, admin_headers, ctx, sup):
    """Hisobot ko'rsatadi — lekin tovar javonda TURIBDI va invariant BUTUN.

    ⚠️  Agar «muddati o'tgan» holatga aylantirilса va u invariant yig'indisidan
        chiqib ketsa, qoldiq JIMGINA yo'qolardi. Shu bois partiya `open`
        bo'lib qoladi va hisobot uni FAQAT ko'rsatadi.
    """
    cid, bid = ctx
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 6, 10, KUN7).status_code == 200
    _eskirt(pid, KECHA)

    row = _mine(_exp(client, admin_headers), pid)[0]
    assert row["bucket"] == "expired"

    with _db() as db:
        lots = _lots(pid)
        assert [l.status for l in lots] == ["open"], "muddat holatni O'ZGARTIRDI"
        rep = SI.check(db, cid, [uuid.UUID(pid)])
        assert rep.ok, rep.mismatches


def test_SOTILGAN_partiya_hisobotdan_CHIQADI(client, admin_headers, ctx, sup):
    """`remaining_qty > 0` — indeks shartining bir qismi, hisobot ham shunga amal qiladi."""
    from tests.test_lot_fefo_sale import _replay
    pid = _product(client, admin_headers)
    _enable(client, admin_headers, pid)
    assert _recv(client, admin_headers, sup, pid, 2, 10, KUN8).status_code == 200
    assert len(_mine(_exp(client, admin_headers), pid)) == 1
    assert _replay(client, admin_headers, pid, 2).json()["results"][0]["ok"] is True
    assert _mine(_exp(client, admin_headers), pid) == [], "bo'shagan partiya qoldi"


# ══ 4. INDEKS BILAN IZCHILLIK ═══════════════════════════════════════════════

def test_SOROV_indeks_sharti_bilan_AYNAN_mos(client, admin_headers):
    """`ix_lot_expiry` ning qisman sharti so'rovda TO'LIQ takrorlanishi shart.

    Bittasi tushib qolsa Postgres qisman indeksdan foydalana olmaydi va
    jonli bazada to'liq jadval skanerlanardi. Buni matn darajasida
    bog'laymiz — indeks o'zgarsa test QIZIL bo'ladi.
    """
    import inspect

    from app import initdb
    from app.api.v1 import lots as L

    idx = inspect.getsource(initdb._ensure_indexes)
    ix = idx[idx.index("ix_lot_expiry"):]
    ix = ix[:ix.index('"ix_lot_expiry")')]
    for shart in ("remaining_qty > 0", "status = 'open'", "expiry_date IS NOT NULL"):
        assert shart in ix, f"indeks sharti o'zgardi: {shart}"

    src = inspect.getsource(L.expiring_lots)
    assert "StockBatch.remaining_qty > 0" in src
    assert "StockBatch.status == SI.OPEN" in src
    assert "StockBatch.expiry_date.isnot(None)" in src
    assert "StockBatch.expiry_date <= horizon" in src
