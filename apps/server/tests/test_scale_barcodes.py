# -*- coding: utf-8 -*-
"""TAROZI ETIKETKASI — POS BILAN UMUMIY VEKTORLAR (Phase 5G).

⚠️  BITTA FAYL, IKKI TIL. `tests/fixtures/scale_barcodes.json` (repo ildizida) ni vitest
    (`tests/scale-barcode.test.ts` -> `packages/shared/src/lib/scaleBarcode.ts`, POS kassasi) va
    shu fayl (`app/services/scale_barcode.py`, `GET /products/scan`) BIRGA tekshiradi. POS va
    server bir etiketkani har xil o'qisa, bu ikkisidan biri QIZARADI.

KONTRAKT: `27` + PLU(5) + GRAMM(5) + EAN-13 nazorat(1) — Fayzan do'konidan olingan REAL
etiketkalar bilan tasdiqlangan (pastdagi `REAL` ro'yxati).
"""
import json
import pathlib

import pytest

from app.services import scale_barcode as SB

_FIX = pathlib.Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scale_barcodes.json"
V = json.loads(_FIX.read_text(encoding="utf-8"))

# Fayzan do'konidan olingan HAQIQIY etiketkalar: (barkod, PLU, gramm, kg satri)
REAL = [
    ("2700345032787", "00345", 3278, "3.278"),
    ("2700565020205", "00565", 2020, "2.020"),
    ("2700537004264", "00537", 426, "0.426"),
    ("2700349000560", "00349", 56, "0.056"),
]


def test_vektor_fayli_BOR_va_BOSH_EMAS():
    assert len(V["labels"]) >= 10 and len(V["plu_match"]) >= 8


@pytest.mark.parametrize("v", V["labels"], ids=[repr(v["code"]) for v in V["labels"]])
def test_etiketka_vektori(v):
    assert SB.digits_only(v["code"]) == v["digits"]
    got = SB.parse(v["code"])
    if v["scale"] is None:
        assert got is None, got
    else:
        assert got is not None
        # HAR BESHTA maydon — aks holda POS bilan parity da'vosi yolg'on bo'ladi.
        assert (got.prefix, got.plu, got.grams, got.qty, got.checksum) == (
            v["scale"]["prefix"], v["scale"]["plu"], v["scale"]["grams"],
            v["scale"]["qty"], v["scale"]["checksum"])
        assert got.prefix == SB.SCALE_PREFIX
        assert len(got.plu) == SB.PLU_DIGITS
        assert SB.ean13_checksum(v["digits"][:12]) == v["scale"]["checksum"]


@pytest.mark.parametrize("c", V["plu_match"],
                         ids=[f"{c['plu_code']!r}~{c['plu']}" for c in V["plu_match"]])
def test_plu_mosligi_vektori(c):
    assert SB.plu_matches(c["plu_code"], c["plu"]) is c["match"]


@pytest.mark.parametrize("code,plu,grams,qty", REAL)
def test_fayzan_real_etiketkasi(code, plu, grams, qty):
    got = SB.parse(code)
    assert got is not None
    assert got.prefix == "27"
    assert got.plu == plu           # 5 xonali SATR, yetakchi nollar bilan
    assert got.grams == grams
    assert got.qty == qty
    assert got.checksum == int(code[12])


@pytest.mark.parametrize("code,plu,grams,qty", REAL)
def test_eski_6_xonali_layout_qaytmasin(code, plu, grams, qty):
    """REGRESSIYA: `2 + PLU(6) + gramm(5)` PLU ni 700000 ga surardi (700345, 700537...)."""
    got = SB.parse(code)
    assert got.plu != code[1:7]
    assert got.plu == plu
    assert int(got.plu) <= 99999    # BinOS `plu_code` 1-5 xona (products.py `_valid_plu`)


@pytest.mark.parametrize("code,per_kg,total", [("2700537004264", 350, 149.10),
                                               ("2700349000560", 580, 32.48)])
def test_payload_GRAMM_narx_emas(code, per_kg, total):
    """Etiketkadagi summa = narx x (gramm / 1000) — 8-12-raqamlar VAZN ekanining dalili."""
    got = SB.parse(code)
    assert round(per_kg * got.grams / 1000, 2) == total


@pytest.mark.parametrize("code,plu,grams,qty", REAL)
def test_nazorat_raqami_buzilsa_rad(code, plu, grams, qty):
    bad = code[:12] + str((int(code[12]) + 1) % 10)
    assert SB.parse(bad) is None


def test_plu_kanonik_yetakchi_nollar():
    assert SB.normalize_plu("537") == "00537"
    assert SB.normalize_plu("00537") == "00537"
    assert SB.normalize_plu(537) == "00537"
    assert SB.normalize_plu("0") == "00000"
    # Etiketkada BOSILGAN 6 xonali KOD — barkod PLU maydoni EMAS.
    assert SB.normalize_plu("000537") is None
    assert SB.plu_matches("000537", "00537") is False


def test_mapping_zanjiri_hujjat_bilan_MOS():
    """KOD 000537 -> barkod PLU 00537 -> BinOS `plu_code` 537 — uchalasi bitta tovar."""
    m = V["mapping"]
    got = SB.parse("2700537004264")
    assert m["barkod_plu_maydoni"] == got.plu == "00537"
    assert SB.plu_matches(m["binos_plu_code"], got.plu) is True
    assert SB.plu_matches("537", got.plu) is True
    assert SB.normalize_plu(m["etiketkada_bosilgan_kod"]) is None
