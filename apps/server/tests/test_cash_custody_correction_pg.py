# -*- coding: utf-8 -*-
"""PHASE 5E — TUZATISH NAQD OYOG'INING LEDGER IDENTITY'SI (§A.5), HAQIQIY POSTGRES.

⚠️  NEGA ALOHIDA FAYL VA NEGA PG18. Bu yerdagi HAR bir tasdiq BAZANING O'ZIGA
    tegishli: `cle_uq_business` cheklovining USTUN TARKIBI, append-only
    ledgerdagi leg raqamlanishi va IKKI KONKURRENT tuzatishning qulf xulqi.
    SQLite'da `cash` sxemasi UMUMAN yo'q, `with_for_update()` esa bezarar
    no-op — ya'ni bu sinovlar u yerda «yashil» bo'lib hech narsani
    isbotlamasdi. CI ularni `postgres:18` servisida `-k external` bilan
    QAYTA yugurtiradi (ci.yml: pre-hardening PG18 job'i).

USHLANADIGAN NUQSONLAR SINFLARI
  1. KALIT SHAKLINING SURILISHI — `cle_uq_business` (tenant, source_type,
     source_id, leg_index) dan boshqa narsaga aylansa, BUTUN idempotentlik
     hikoyasi qulaydi va takror so'rov ikkinchi marta pul yozardi.
  2. O'ZGARMAS OYOQNING QAYTA YOZILISHI — tuzatish asl `PURCHASE·0` legiga
     tegishi (summasini «to'g'rilashi»). U TARIXIY fakt: qaytim ALOHIDA
     hodisa bo'lib, QARAMA-QARSHI oyoq bilan yoziladi.
  3. IKKI MARTA POST — takror (`client_uuid`) yoki konkurrent yuborish
     ikkinchi naqd oyoq yozishi. Qator SONI bilan o'lchanadi, mavjudligi
     bilan emas: «bor» degan tasdiq ikkitasini ham o'tkazib yuborardi.
  4. LEG TO'QNASHUVI — ikkinchi tuzatish birinchisining kalitiga urilib
     butun amalni yiqitishi (yoki teskarisi: birinchisini bosib o'tishi).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza;
CI'da `-k external`). Do'kon/kassa/qabul yordamchilari BITTA joyda turadi —
`tests/test_cash_custody_correction.py` (nusxa ko'paytirilmaydi).
"""
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text

from tests.test_cash_custody_correction import (KAM, QAYTIM, QTY, _amal, _dokon, _hisob,
                                                _ledger, _pul, _qabul, _t0)
from tests.test_check_defs_pg import pg_target  # noqa: F401
from tests.test_lot_tz_confirm_pg import _navbat
from tests.test_receiving_correction_pg import _baza, _ushla

OSHIRILGAN = Decimal("80")            # tuzatilgan qator narxi -> hujjat summasi OSHADI
QOSHIMCHA = Decimal("90.00")          # KAM × (OSHIRILGAN − COST)


def _savdo(S):
    """Post-T0 do'kon + to'ldirilgan kassa + NAQD qabul (hujjat jami 500.00)."""
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    return d, till


def _ish(S, go):
    """Chaqiruvni O'Z sessiyasida bajaradi (`get_db` bilan AYNI yopilish)."""
    s = S()
    try:
        return go(s)
    finally:
        s.close()


def _qaytarishlar(S, d):
    """Hujjatning `PurchaseReturn` hodisalari — ledger `source_id` ning manbai."""
    from app.models.purchasing import PurchaseReturn
    s = S()
    try:
        return sorted(((str(r.id), Decimal(str(r.amount)),
                        (str(r.cash_account_id) if r.cash_account_id else None))
                       for r in s.query(PurchaseReturn).filter(
                           PurchaseReturn.purchase_id == d["pur"]).all()),
                      key=lambda x: x[1])
    finally:
        s.close()


def _sanoq(S, d, source_type):
    """Berilgan `source_type` bo'yicha ledger qatorlari SONI (mavjudligi emas)."""
    return len([x for x in _ledger(S, d) if x[0] == source_type])


def _asl_leg(S, d):
    """Asl naqd xarid oyog'i — `PURCHASE·purchase_id·0`. U HECH QACHON o'zgarmaydi."""
    return [x for x in _ledger(S, d) if x[0] == "PURCHASE" and x[2] == 0]


# ══ 1. BIZNES KALITINING SHAKLI ══════════════════════════════════════════════

def test_PG_cle_uq_business_KALIT_SHAKLI_AYNAN_TORT_USTUN(pg_target):
    """`cle_uq_business` = UNIQUE (tenant_id, source_type, source_id, leg_index).

    ⚠️  BUTUN IDEMPOTENTLIK SHU KALITGA TAYANADI. `leg_index` tushib qolsa —
        summasi oshirilgan naqd xaridning ikkinchi oyog'i UMUMAN yozilmasdi;
        `tenant_id` tushib qolsa — bir do'konning hodisasi boshqasinikini
        bloklardi. Nom bo'yicha tekshirish bularning BIRORTASINI ko'rmasdi,
        shu bois ustunlar TARTIBI bilan birga o'qiladi.
    """
    eng, _S = _baza(pg_target)
    try:
        with eng.connect() as con:
            row = con.execute(text(
                "SELECT array_agg(a.attname ORDER BY k.ord) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                "WHERE n.nspname = 'cash' AND t.relname = 'cash_ledger_entries' "
                "AND c.conname = 'cle_uq_business' AND c.contype = 'u' "
                "GROUP BY c.oid")).first()
        assert row is not None, "cle_uq_business cheklovi YO'Q — dedup umuman yo'q"
        assert list(row[0]) == ["tenant_id", "source_type", "source_id", "leg_index"], row[0]
    finally:
        eng.dispose()


# ══ 2. KAMAYTIRISH — IN·PURCHASE_RETURN ══════════════════════════════════════

def test_PG_KAMAYTIRISH_AYNAN_BITTA_PURCHASE_RETURN_oyogi(pg_target):
    """Hujjat kamaysa: AYNAN bitta IN oyoq, `source_id` = YANGI `PurchaseReturn`.

    ⚠️  `source_id` XARID ID'SI EMAS. Bo'lganida u asl `PURCHASE·0` legi bilan
        AYNI kalitga urilardi (yoki uni dedup qilib, qaytim UMUMAN
        yozilmasdi) — va bir xariddan IKKI marta qaytarish imkonsiz bo'lardi.
    ⚠️  ASL OYOQ TEGILMAYDI: u o'sha kunning fakti (`PURCHASE·0` = 500.00).
    """
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        r = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till))
        assert r["ok"] is True and r["delta_total"] == -150.0, r
        qaytim = _qaytarishlar(S, d)
        assert [(a, acc) for _i, a, acc in qaytim] == [(QAYTIM, str(till["id"]))], qaytim
        ret = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
        assert len(ret) == 1, ret
        (_st, src, leg, yon, kat, hisob, summa) = ret[0]
        assert src == qaytim[0][0], (src, qaytim)
        assert (leg, yon, kat) == (0, "IN", "PURCHASE_RETURN"), ret
        assert (hisob, summa) == (str(till["id"]), QAYTIM), ret
        assert _asl_leg(S, d) == [("PURCHASE", str(d["pur"]), 0, "OUT", "PURCHASE_OUT",
                                   str(till["id"]), Decimal("500.00"))], _ledger(S, d)
    finally:
        eng.dispose()


# ══ 3. OSHIRISH — OUT·PURCHASE, leg >= 1 ═════════════════════════════════════

def test_PG_OSHIRISH_PURCHASE_leg_1_OUT_asl_leg_TEGILMAYDI(pg_target):
    """Hujjat summasi oshsa: FAQAT DELTA yangi `PURCHASE` legi bo'lib chiqadi.

    ⚠️  ASL LEG QAYTA YOZILMAYDI va XARID IKKI MARTA HISOBLANMAYDI: leg-0
        o'z summasida (500.00) qoladi, leg-1 esa faqat farqni (90.00) tutadi.
        Ledger append-only — «to'g'rilash» UPDATE bilan emas, YANGI oyoq bilan.
    """
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        r = _ish(S, _amal(d, reverse=[(d["batch"], KAM)],
                          replace=[{"qty": float(KAM), "batch_number": "B-1"}],
                          narx=OSHIRILGAN, account=till))
        assert r["ok"] is True and r["delta_total"] == 90.0, r
        pur_legs = sorted(x for x in _ledger(S, d) if x[0] == "PURCHASE")
        assert [(x[2], x[3], x[6]) for x in pur_legs] == [
            (0, "OUT", Decimal("500.00")), (1, "OUT", QOSHIMCHA)], pur_legs
        assert {x[5] for x in pur_legs} == {str(till["id"])}, pur_legs
        assert _sanoq(S, d, "PURCHASE_RETURN") == 0, _ledger(S, d)
    finally:
        eng.dispose()


# ══ 4. IKKI TUZATISH — YONMA-YON YASHAYDI ════════════════════════════════════

def test_PG_IKKI_KETMA_KET_tuzatish_IKKI_MUSTAQIL_oyoq(pg_target):
    """Ikki kamaytirish — ikki MUSTAQIL `PURCHASE_RETURN` hodisasi.

    ⚠️  IKKALASI HAM `leg_index = 0`. Kalit `source_id` bo'yicha ajraladi
        (`PurchaseReturn` id'si), ya'ni ikkinchi qaytim birinchisining
        kalitiga UMUMAN urilmaydi. `source_id` xarid id'si bo'lganida ikkinchi
        tuzatish `cle_uq_business` ga urilib, BUTUN amalni yiqitardi.
    """
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        r1 = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till))
        r2 = _ish(S, _amal(d, reverse=[(d["batch"], Decimal("2"))], account=till))
        assert (r1["delta_total"], r2["delta_total"]) == (-150.0, -100.0), (r1, r2)
        qaytim = _qaytarishlar(S, d)
        assert [a for _i, a, _acc in qaytim] == [Decimal("100.00"), QAYTIM], qaytim
        ret = sorted(x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN")
        assert len(ret) == 2, ret
        assert {x[2] for x in ret} == {0}, ret
        assert sorted(x[1] for x in ret) == sorted(i for i, _a, _acc in qaytim), ret
        assert sorted(x[6] for x in ret) == [Decimal("100.00"), QAYTIM], ret
        assert _asl_leg(S, d)[0][6] == Decimal("500.00"), _ledger(S, d)
    finally:
        eng.dispose()


# ══ 5. TAKROR — IKKINCHI OYOQ YO'Q (QATOR SONI) ══════════════════════════════

def test_PG_TAKROR_ayni_client_uuid_IKKINCHI_oyoq_YOZMAYDI(pg_target):
    """Tarmoq uzilib qayta yuborilgan AYNI tuzatish ikkinchi marta pul yozmaydi.

    ⚠️  «OYOQ BOR» DEGAN TASDIQ YETMAYDI — QATOR SONI o'lchanadi. Ikkinchi
        oyoq yozilganda ham «bor» tasdig'i o'tardi va kassa jimgina 150.00 ga
        ko'p ko'rsatardi.
    """
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        cu = uuid.uuid4()
        r1 = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till, cu=cu))
        oldin = _ledger(S, d)
        r2 = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till, cu=cu))
        assert r1["duplicate"] is False and r2["duplicate"] is True, (r1, r2)
        assert r2["correction_id"] == r1["correction_id"], (r1, r2)
        assert _sanoq(S, d, "PURCHASE_RETURN") == 1, _ledger(S, d)
        assert _ledger(S, d) == oldin, "takror ledgerni QIMIRLATDI"
        assert len(_qaytarishlar(S, d)) == 1, _qaytarishlar(S, d)
    finally:
        eng.dispose()


def test_PG_YANGI_client_uuid_YANGI_HODISA_pul_ROSTDAN_ikki_marta_qaytadi(pg_target):
    """AYNI MAZMUN + YANGI `client_uuid` = IKKINCHI, MUSTAQIL tuzatish.

    ⚠️  BU DUBLIKAT EMAS — SHARTNOMA. Ikkinchi so'rov yana 3 dona teskari
        qiladi: partiya 10 -> 7 -> 4, hujjat 500 -> 350 -> 200, ya'ni pul
        ROSTDAN ikki marta qaytadi va ikkita oyoq TO'G'RI. Ledger darajasida
        ikkinchi yuborishni to'sadigan kalit YO'Q (`source_id` har safar yangi
        `PurchaseReturn`), dedup esa `ReceivingCorrection.client_uuid` da —
        ya'ni takrorlanishning YAGONA qo'riqchisi mijoz bergan kalit.
        Sinov shu shartnomani MUZLATADI: agar kelajakda ayni semantik
        tuzatish uchun ikkinchi oyoq FANTOM bo'lib qolsa (qoldiq
        qimirlamasdan pul qaytsa), quyidagi tasdiqlar buzilib, buni ushlaydi.
    """
    from app.models.inventory import StockBatch
    from app.models.purchasing import Purchase
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        r1 = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till))
        r2 = _ish(S, _amal(d, reverse=[(d["batch"], KAM)], account=till))
        assert r1["correction_id"] != r2["correction_id"], (r1, r2)
        assert r1["duplicate"] is False and r2["duplicate"] is False, (r1, r2)
        ret = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
        assert len(ret) == 2 and sorted(x[6] for x in ret) == [QAYTIM, QAYTIM], ret
        assert len({x[1] for x in ret}) == 2, ret       # ikki HAR XIL `source_id`
        s = S()
        try:
            b = s.get(StockBatch, d["batch"])
            pur = s.get(Purchase, d["pur"])
            assert Decimal(str(b.remaining_qty)) == QTY - 2 * KAM, b.remaining_qty
            assert Decimal(str(pur.total)) == Decimal("200.00"), pur.total
            assert Decimal(str(pur.paid_amount)) == Decimal("200.00"), pur.paid_amount
        finally:
            s.close()
    finally:
        eng.dispose()


# ══ 6. KONKURRENTLIK ═════════════════════════════════════════════════════════

def test_PG_KONKURRENT_ayni_client_uuid_AYNAN_BITTA_naqd_oyoq(pg_target):
    """Ikki konkurrent yuborish (AYNI `client_uuid`) — naqd BIR MARTA qaytadi.

    ⚠️  QULFSIZ TAKROR QIDIRUVI BU YERDA KO'R: ikkinchi oqim hali commit
        bo'lmagan sarlavhani ko'rmaydi va hujjat qulfida navbatga turadi.
        Qulf ostidagi takror qidiruvi bo'lmaganda u O'Z `PurchaseReturn`
        hodisasini yaratib, IKKINCHI IN oyog'ini yozardi — `cle_uq_business`
        buni TO'SMASDI (source_id har safar yangi), ya'ni baza darajasida
        himoya YO'Q va yagona qo'riqchi aynan shu qidiruv.
    """
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        cu = uuid.uuid4()
        rev = [(d["batch"], KAM)]
        r = _navbat(eng, S, _ushla(_amal(d, reverse=rev, account=till, cu=cu)),
                    _amal(d, reverse=rev, account=till, cu=cu))
        assert r["kutdi"] is True, f"ikkinchi yuborish qulfni KUTMADI: {r}"
        for yon in ("a", "b"):
            assert not isinstance(r[yon], (Exception, HTTPException)), r
        assert r["a"]["duplicate"] is False and r["b"]["duplicate"] is True, r
        assert r["b"]["correction_id"] == r["a"]["correction_id"], r
        assert _sanoq(S, d, "PURCHASE_RETURN") == 1, _ledger(S, d)
        assert len(_qaytarishlar(S, d)) == 1, _qaytarishlar(S, d)
        assert _asl_leg(S, d)[0][6] == Decimal("500.00"), _ledger(S, d)
    finally:
        eng.dispose()


def test_PG_KONKURRENT_custody_RAD_etsa_LEDGER_TEGILMAYDI(pg_target):
    """Custody rad etgan tuzatish ledgerda IZ QOLDIRMAYDI — parallel o'tayotgan
    haqiqiy tuzatishning oyog'i esa JOYIDA qoladi.

    ⚠️  CUSTODY §13 DA — TESKARI YOZUVDAN KEYIN. Rad etish tranzaksiyani
        ROSTDAN qaytarishi shart: aks holda bajarilmagan amal sarlavha,
        harakat va hujjat summasini qoldirib ketardi (`get_db` yopilishi
        bilan AYNI yo'l).
    """
    from app.models.receiving import ReceivingCorrection
    eng, S = _baza(pg_target)
    try:
        d, till = _savdo(S)
        arxiv = _hisob(S, d, status="ARCHIVED")
        r = _navbat(eng, S, _ushla(_amal(d, reverse=[(d["batch"], KAM)], account=till)),
                    _amal(d, reverse=[(d["batch"], Decimal("2"))], account=arxiv))
        assert r["kutdi"] is True, f"ikkinchi oqim hujjat qulfini KUTMADI: {r}"
        assert r["a"]["ok"] is True, r
        assert isinstance(r["b"], HTTPException) and r["b"].status_code == 400, r
        assert str(r["b"].detail).startswith("CASH_CUSTODY_ACCOUNT_INVALID:"), r
        assert _sanoq(S, d, "PURCHASE_RETURN") == 1, _ledger(S, d)
        s = S()
        try:
            assert s.query(ReceivingCorrection).filter(
                ReceivingCorrection.company_id == d["cid"]).count() == 1
        finally:
            s.close()
    finally:
        eng.dispose()
