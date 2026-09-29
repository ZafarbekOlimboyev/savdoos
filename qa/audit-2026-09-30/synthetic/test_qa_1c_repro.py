# -*- coding: utf-8 -*-
"""MUSTAQIL QA REPRODUKSIYA — 1C snapshot 40150b54 (qa/binos-independent-security).

Sof funksiya darajasi (baza kerak emas). QIZIL = nuqson isboti.
"""
import pytest

from app.services.discovery_1c import bundle as B
from app.services.migrator_1c.normalize import check_unit_mapping


def _mk_bundle(sample_rows):
    """Minimal DiscoveryBundle — samples MAZMUNI parametr."""
    return B.DiscoveryBundle(
        discovery={"collector": {"name": "BinOSDiscovery", "version": "1"},
                   "source": {"kind": "copy", "path": "X:/copy.dt"},
                   "notes": [], "mappings": []},
        sweep={"objects": []},
        counts={"counts": []},
        status={"status": "OK", "blocked_reason": None, "sections": []},
        summary_md="",
        samples={"samples/nomenklatura.json": {"rows": sample_rows}},
    )


# ══ BINOS-QA-1C-01 · content_sha256 namuna QATORLARINI qamramaydi ═════════════════════
# Invariant: to'plamning DALIL MA'LUMOTI (samples/*.json qatorlari) o'zgarsa,
# content_sha256 ham o'zgarishi SHART — aks holda «ko'rib chiqilgan va tasdiqlangan»
# to'plam ostida boshqa dalil yotishi mumkin. Nuqson: canonical_projection'da
# `"samples": sorted(b.samples)` — dict ustidagi sorted() FAQAT KALITLARNI (fayl
# nomlarini) oladi, qatorlar xeshga kirmaydi.

def test_qa1c01_content_hash_ignores_sample_rows():
    a = _mk_bundle([{"kod": "000537", "nom": "Olma"}])
    b = _mk_bundle([{"kod": "999999", "nom": "SOXTA QATOR — boshqa dalil"}])
    ha, hb = B.content_hash(a), B.content_hash(b)
    assert ha != hb, (
        f"XESH KO'R: ikki to'plamning namuna QATORLARI butunlay boshqa, content_sha256 "
        f"esa AYNI ({ha[:16]}…) — dalil ma'lumoti o'zgarsa ham imzo o'zgarmaydi")


# ══ BINOS-QA-1C-02 · massa birligining keng tarqalgan imlosi deny-listda YO'Q ═════════
# Invariant: TANILGAN o'lchamdagi manba birligini boshqa o'lchamga (--unit-map
# 'тн'=dona) xaritalash RAD etilishi shart — migrator son aylantirmaydi, shuning
# uchun 12.5 tonna JIMGINA 12.5 dona bo'lib yoziladi. Nuqson: lug'atda 'т', 'тонна',
# 'тонн' bor, lekin 1C'da tez-tez uchraydigan 'тн' (va 'литров', 'грамма') YO'Q —
# ular «yangi nom» sifatida tekshiruvsiz o'tadi.

@pytest.mark.parametrize("src", ["тн", "литров", "грамма"])
def test_qa1c02_common_unit_spelling_bypasses_dimension_check(src):
    with pytest.raises(ValueError):
        check_unit_mapping(src, "dona")
