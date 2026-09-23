# -*- coding: utf-8 -*-
"""TAROZI ETIKETKASI — POS BILAN UMUMIY VEKTORLAR (Phase 5G).

⚠️  BITTA FAYL, IKKI TIL. `tests/fixtures/scale_barcodes.json` (repo ildizida) ni vitest
    (`tests/scale-barcode.test.ts` -> `packages/shared/src/lib/scaleBarcode.ts`, POS kassasi) va
    shu fayl (`app/services/scale_barcode.py`, `GET /products/scan`) BIRGA tekshiradi. POS va
    server bir etiketkani har xil o'qisa, bu ikkisidan biri QIZARADI.
"""
import json
import pathlib

import pytest

from app.services import scale_barcode as SB

_FIX = pathlib.Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scale_barcodes.json"
V = json.loads(_FIX.read_text(encoding="utf-8"))


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
        assert (got.plu, got.grams, got.qty) == (v["scale"]["plu"], v["scale"]["grams"],
                                                 v["scale"]["qty"])


@pytest.mark.parametrize("c", V["plu_match"],
                         ids=[f"{c['plu_code']!r}~{c['plu']}" for c in V["plu_match"]])
def test_plu_mosligi_vektori(c):
    assert SB.plu_matches(c["plu_code"], c["plu"]) is c["match"]
