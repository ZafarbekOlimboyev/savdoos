# -*- coding: utf-8 -*-
"""QAT'IY FINALIZE KOMPARATORI — SOF qatlam (bazasiz).

Bu fayl komponent arifmetikasini va hukm funksiyasini o'lchaydi. Naqd ledgeri
ATAYLAB faqat Postgres'da bor, shu bois haqiqiy leg talab qiladigan holatlar
`tests/cash/test_strict_parity_pg.py` da.

A  komponent moslik jadvali va ISHORA konvensiyasi
B  8-HOLAT: ayni filialda qarama-qarshi ikki nuqson BEKOR BO'LMAYDI
C  13-HOLAT: qoplanmagan NORMAL toifa -> UNDETERMINED (mavjudlik bo'yicha, summa EMAS)
D  hukm funksiyasi: har muammo sinfi RAD etiladi
E  vakuum himoyasi
F  eski skalyar hukmi TEGILMAGAN (operator tooling kontrakti)
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.cash import shadow_compare as SC

_Z = Decimal("0")


def _cat(**kw):
    """{toifa: (imzoli_summa, leg_soni)} — `_strict_ledger_by_category` shakli."""
    return {k: (Decimal(str(v)), 1) for k, v in kw.items()}


def _legacy(**kw):
    base = {"cash_sales": _Z, "payin": _Z, "payout": _Z, "expense": _Z,
            "collection": _Z, "net_cash_purchases": _Z, "opening": _Z}
    base.update({k: Decimal(str(v)) for k, v in kw.items()})
    return base


def _rep(**kw):
    """TOZA strict hisobot; `kw` bilan muammo kiritiladi."""
    pr = {"components": [], "uncovered_categories": [], "openings": [],
          "structural": [], "orphan_openings": []}
    pr.update({k: v for k, v in kw.items() if k in pr})
    return {"level": "tenant_strict", "tenant_id": "t", "status": "MATCH",
            "components": [], "uncovered_categories": pr["uncovered_categories"],
            "openings": pr["openings"], "structural": pr["structural"],
            "orphan_openings": pr["orphan_openings"],
            "counts": {"shifts": kw.get("shifts", 1), "accounts": kw.get("accounts", 1),
                       "problems": sum(len(v) for v in pr.values())},
            "problems": pr}


# ═══ A) moslik jadvali va ishoralar ════════════════════════════════════════
def test_A_moslik_jadvali_AYNAN_egani_bergani():
    assert set(SC.STRICT_COMPONENTS) == {
        "cash_sales", "payin", "expense", "payout", "net_cash_purchases"}
    assert SC.STRICT_COMPONENTS["cash_sales"] == (+1, ("SALE",))
    assert SC.STRICT_COMPONENTS["payin"] == (+1, ("CASH_IN", "DEBT_IN"))
    assert SC.STRICT_COMPONENTS["expense"] == (-1, ("EXPENSE",))
    assert SC.STRICT_COMPONENTS["payout"] == (-1, ("CASH_OUT", "REFUND", "SUPPLIER_OUT"))
    assert SC.STRICT_COMPONENTS["net_cash_purchases"] == (
        -1, ("PURCHASE_OUT", "PURCHASE_RETURN"))


def test_A2_qoplangan_toifalar_AYNAN_on_ta():
    """`OPENING` + 9 biznes toifasi. `TRANSFER`/`BANK_DEPOSIT`/`ADJUSTMENT` QOPLANMAGAN."""
    assert SC.STRICT_COVERED_CATEGORIES == frozenset({
        "OPENING", "SALE", "CASH_IN", "DEBT_IN", "EXPENSE", "CASH_OUT", "REFUND",
        "SUPPLIER_OUT", "PURCHASE_OUT", "PURCHASE_RETURN"})
    for t in ("TRANSFER", "BANK_DEPOSIT", "ADJUSTMENT"):
        assert t not in SC.STRICT_COVERED_CATEGORIES


@pytest.mark.parametrize("nom,legacy_kw,cat_kw", [
    ("cash_sales", {"cash_sales": 5000}, {"SALE": 5000}),            # KIRIM: +
    ("payin", {"payin": 300}, {"CASH_IN": 300}),                      # KIRIM: +
    ("payin", {"payin": 300}, {"DEBT_IN": 300}),                      # guruhlangan
    ("expense", {"expense": 700}, {"EXPENSE": -700}),                 # CHIQIM: -
    ("payout", {"payout": 400}, {"CASH_OUT": -400}),
    ("payout", {"payout": 400}, {"REFUND": -400}),
    ("payout", {"payout": 400}, {"SUPPLIER_OUT": -400}),
    ("net_cash_purchases", {"net_cash_purchases": 900}, {"PURCHASE_OUT": -900}),
])
def test_A3_ISHORA_konvensiyasi_sogʻlom_holatda_nol_delta(nom, legacy_kw, cat_kw):
    rows = SC._strict_component_rows(_legacy(**legacy_kw), _cat(**cat_kw))
    r = next(x for x in rows if x["component"] == nom)
    assert r["delta"] == 0.0, r
    assert r["status"] == "MATCH"


def test_A4_net_xarid_qaytarishni_AYIRADI():
    """`Purchase.total` allaqachon net; ledgerda OUT va RETURN BIRGA olinadi."""
    rows = SC._strict_component_rows(
        _legacy(net_cash_purchases=600), _cat(PURCHASE_OUT=-1000, PURCHASE_RETURN=400))
    r = next(x for x in rows if x["component"] == "net_cash_purchases")
    assert r["delta"] == 0.0, r


# ═══ B) 8-HOLAT — bekor qilinmaslik ════════════════════════════════════════
def test_B_8HOLAT_ayni_filialda_qarama_qarshi_nuqsonlar_BEKOR_BOLMAYDI():
    """⚠️  ASOSIY. Eski skalyar bu holatda `MATCH` beradi (o'lchangan), chunki
    `compare_branch` filialni bitta skalyarga keltiradi. Komponentli model
    IKKISINI ham ko'rishi SHART.

    Stsenariy: legacy'da 21000 lik naqd savdo bor, ledgerda SALE legi YO'Q
    (delta -21000); va legacy'da 21000 lik payout bor, ledgerda CASH_OUT legi
    YO'Q (delta +21000). Umumiy skalyar: legacy 21000-21000=0, ledger 0 -> 0.
    """
    rows = SC._strict_component_rows(
        _legacy(cash_sales=21000, payout=21000), _cat())
    d = {r["component"]: r for r in rows}
    assert d["cash_sales"]["delta"] == -21000.0
    assert d["payout"]["delta"] == +21000.0
    #  Ikkisi ham REVIEW — va yig'indisi nolga bekor bo'lsa ham AHAMIYATSIZ.
    assert d["cash_sales"]["status"] == "REVIEW"
    assert d["payout"]["status"] == "REVIEW"
    assert sum(r["delta"] for r in rows) == 0.0, "stsenariy bekor-qiluvchi bo'lishi SHART"

    ok, sabab = SC.strict_finalize_verdict(
        _rep(components=[d["cash_sales"], d["payout"]]))
    assert ok is False
    assert "KOMPONENT" in sabab and "cash_sales" in sabab and "payout" in sabab


def test_B2_bitta_komponent_tolerantlik_ichida_MATCH():
    rows = SC._strict_component_rows(_legacy(cash_sales=100), _cat(SALE=100.004))
    assert rows[0]["status"] == "MATCH", rows[0]
    rows2 = SC._strict_component_rows(_legacy(cash_sales=100), _cat(SALE=100.006))
    assert next(r for r in rows2 if r["component"] == "cash_sales")["status"] == "REVIEW"


# ═══ C) 13-HOLAT — qoplanmagan toifa ═══════════════════════════════════════
@pytest.mark.parametrize("toifa", ["TRANSFER", "BANK_DEPOSIT", "ADJUSTMENT",
                                   "KELAJAKDA_QOSHILGAN"])
def test_C_13HOLAT_qoplanmagan_toifa_RAD(toifa):
    ok, sabab = SC.strict_finalize_verdict(
        _rep(uncovered_categories=[{"category": toifa, "signed": 0.0, "legs": 2}]))
    assert ok is False
    assert "QOPLANMAGAN" in sabab and toifa in sabab


def test_C2_qoplanmagan_toifa_MAVJUDLIK_boyicha_IMZOLI_SUMMA_boyicha_EMAS():
    """⚠️  Inkassa (TRANSFER) juftligi tenant darajasida NOLGA bekor bo'ladi.
    Faqat summaga qarasak u JIM o'tib ketardi — shu bois leg SONI ishlatiladi."""
    ok, sabab = SC.strict_finalize_verdict(
        _rep(uncovered_categories=[{"category": "TRANSFER", "signed": 0.0, "legs": 2}]))
    assert ok is False, "net-nol TRANSFER jim o'tib ketdi"
    assert "TRANSFER" in sabab


# ═══ D) hukm funksiyasi — har muammo sinfi ═════════════════════════════════
def test_D_TOZA_hisobot_PASS():
    ok, sabab = SC.strict_finalize_verdict(_rep())
    assert ok is True and sabab == "STRICT MATCH"


@pytest.mark.parametrize("kw,belgi", [
    ({"openings": [{"shift_id": "s1", "status": "UNDETERMINED",
                    "reason": "ORDERING_AMBIGUOUS"}]}, "NOANIQ"),
    ({"openings": [{"shift_id": "s1", "status": "FAIL",
                    "reason": "MISSING_OPENING_LEG", "expected": 3000.0,
                    "actual": None}]}, "OCHILISH"),
    ({"structural": [{"shift_id": "s1", "status": "NO_TWIN"}]}, "STRUKTURAVIY"),
    ({"structural": [{"shift_id": "s1", "status": "ANCHOR_MISMATCH"}]}, "STRUKTURAVIY"),
    ({"structural": [{"shift_id": "s1", "status": "NO_TILL"}]}, "STRUKTURAVIY"),
    ({"orphan_openings": [{"id": "e1", "reason": "OPENING_UNLINKED"}]}, "BOG'LANMAGAN"),
])
def test_D2_har_muammo_sinfi_RAD(kw, belgi):
    ok, sabab = SC.strict_finalize_verdict(_rep(**kw))
    assert ok is False, kw
    assert belgi in sabab, sabab


def test_D3_NOANIQLIK_boshqa_muammolardan_OLDIN_xabar_qilinadi():
    """Fail-closed tartibi: noaniqlik «taxmin bilan MATCH» xavfini ko'taradi,
    shu bois u birinchi aytiladi."""
    ok, sabab = SC.strict_finalize_verdict(_rep(
        openings=[{"shift_id": "s1", "status": "UNDETERMINED", "reason": "BOUNDARY_TIE"},
                  {"shift_id": "s2", "status": "FAIL", "reason": "OPENING_AMOUNT"}]))
    assert ok is False
    assert "NOANIQ" in sabab


def test_D4_yaroqsiz_kirish_500_BERMAYDI():
    for yomon in (None, [], "", 0, {"problems": "x"}):
        ok, sabab = SC.strict_finalize_verdict(yomon)
        assert ok is False and isinstance(sabab, str) and sabab


# ═══ E) vakuum himoyasi ════════════════════════════════════════════════════
def test_E_nol_hisob_yoki_nol_smena_RAD():
    ok, s1 = SC.strict_finalize_verdict(_rep(accounts=0))
    assert ok is False and "hisob" in s1
    ok2, s2 = SC.strict_finalize_verdict(_rep(shifts=0))
    assert ok2 is False and "smena" in s2


# ═══ F) eski yuza TEGILMAGAN ═══════════════════════════════════════════════
def test_F_eski_olti_simvol_MAVJUD_va_eski_hukm_TEGILMAGAN():
    """Operator/Phase-1/Phase-2 tooling kontrakti: olti simvol o'z joyida va
    eski `finalize_parity_verdict` xulqi O'ZGARMAGAN."""
    for nom in ("compare_shift", "compare_till", "compare_branch", "compare_tenant",
                "_rollup", "_status", "finalize_parity_verdict"):
        assert callable(getattr(SC, nom)), nom
    #  Eski hukm HALI HAM `status != MATCH` ni rad etadi (operator semantikasi).
    eski = {"status": "REVIEW", "divergent_part_count": 0, "abs_delta": 21000.0,
            "legacy_in": 1.0, "legacy_out": 0.0, "ledger_in": 1.0, "ledger_out": 0.0,
            "parts": [{"account_count": 1, "status": "REVIEW", "delta": -21000.0}]}
    ok, _ = SC.finalize_parity_verdict(eski)
    assert ok is False
    #  Va `_rollup` ning abs_delta semantikasi ham o'zgarmagan.
    r = SC._rollup("tenant", {"tenant_id": "t"}, [
        {"legacy_in": 100.0, "legacy_out": 0.0, "ledger_in": 0.0, "ledger_out": 0.0,
         "delta": -100.0, "status": "REVIEW", "account_count": 1},
        {"legacy_in": 0.0, "legacy_out": 0.0, "ledger_in": 100.0, "ledger_out": 0.0,
         "delta": 100.0, "status": "REVIEW", "account_count": 1}])
    assert r["delta"] == 0.0 and r["abs_delta"] == 200.0 and r["status"] == "REVIEW"
