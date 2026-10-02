# -*- coding: utf-8 -*-
"""`binos-1c-export-v1` -> `binos-1c-discovery-v1` KO'PRIGI.

⚠️⚠️ HAMMA FIKSTURA SINTETIK. Bu fayl ADAPTER mantig'ini isbotlaydi; u haqiqiy 1C runtime
     ishlashini ISBOTLAMAYDI va bunday da'vo qilmaydi. `.epf` hech qachon ishlatilmagan.

ISBOTLANADIGAN INVARIANTLAR:
  · adapter ishonch darajasini HECH QACHON ko'tarmaydi (VERIFIED chiqmaydi);
  · har nishon AYNAN bir marta chiqadi — qidirilmagani UNKNOWN bo'lib YOZILADI, tashlanmaydi;
  · adapter `source_copy` / `snapshot_at` / `plan_sha256` ni O'YLAB CHIQARMAYDI;
  · `source.kind` OPERATOR e'loni, eksportdan olinmaydi;
  · chiqish DETERMINISTIK — bir xil eksport, aynan bir xil baytlar.
"""
from __future__ import annotations

import pytest

from app.services.discovery_1c import bundle as B
from app.services.discovery_1c import export_adapter as A
from app.services.discovery_1c.schema import TARGETS
from tests.discovery_1c_export_synth import (CATALOG, REGISTER, candidate, count, ev,
                                             export_dict, obj, section)


def build(export=None, *, source_kind="copy", allow_live=False):
    members = A.to_bundle_members(export or export_dict(), source_kind=source_kind)
    return B.load_members(members, allow_live_source=allow_live)


# ── 1. HAQIQIY METADATA HISOBOTI ──────────────────────────────────────────────────────────
def test_HAQIQIY_eksport_toplamga_aylanadi_va_YUKLANADI():
    b = build()
    assert b.discovery["schema_version"] == B.SCHEMA_VERSION
    assert b.discovery["source"]["platform_version"] == "8.3.24.1548"
    assert len(b.sweep["objects"]) == 2


def test_HAR_nishon_AYNAN_bir_marta_chiqadi():
    """Qidirilmagan nishon TASHLANMAYDI — «qaralmadi» va «yo'q» bir xil narsa emas."""
    b = build()
    nishonlar = [m["target"] for m in b.discovery["mappings"]]
    assert sorted(nishonlar) == sorted(TARGETS)
    assert len(nishonlar) == len(set(nishonlar))


def test_QIDIRILMAGAN_nishon_UNKNOWN_va_sababi_yoziladi():
    b = build()
    m = b.mapping("products.plu")               # fiksturada umuman yo'q
    assert m["confidence"] == "UNKNOWN"
    assert m["evidence"] == []
    assert "qidirmadi" in " ".join(m["errors"])


# ── 2. FAQAT NOMZOD: adapter darajani KO'TARMAYDI ─────────────────────────────────────────
def test_dalilli_nomzod_CANDIDATE_boladi():
    b = build()
    m = b.mapping("products.code")
    assert m["confidence"] == "CANDIDATE"
    assert m["source_object"] == CATALOG and m["source_field"] == "Код"


@pytest.mark.parametrize("kuchli", ["human_confirmed", "arithmetic_proof", "contract_match",
                                    "cross_source_agreement", "absence_proven"])
def test_KUCHLI_dalil_ham_VERIFIED_bermaydi(kuchli):
    """HAL QILUVCHI: yig'uvchi kuchli dalil TURINI yozsa ham, adapter darajani ko'tarmaydi.

    Sabab: yig'uvchi o'zini o'zi tasdiqlay olmaydi va u hali hech qachon haqiqiy 1C'da
    ishlamagan. Darajani ko'tarish — odam ko'rigi, alohida qadam."""
    src = None if kuchli == "absence_proven" else CATALOG
    kind = "absent" if kuchli == "absence_proven" else "attribute"
    e = export_dict(candidates=[candidate("products.code", source_object=src,
                                          source_field=None, source_kind=kind,
                                          evidence=[ev(kuchli, "yig'uvchi shunday dedi")])])
    b = build(e)
    assert b.mapping("products.code")["confidence"] == "CANDIDATE"


def test_HECH_BIR_xarita_VERIFIED_emas():
    b = build()
    assert all(m["confidence"] != "VERIFIED" for m in b.discovery["mappings"])


def test_manba_korsatilgan_lekin_DALILSIZ_UNKNOWN_boladi():
    e = export_dict(candidates=[candidate("products.code", source_object=CATALOG,
                                          source_field="Код", source_kind="attribute")])
    m = build(e).mapping("products.code")
    assert m["confidence"] == "UNKNOWN"
    assert "dalil yo'q" in " ".join(m["errors"])


# ── 3. PROVENANS: adapter migrator kafolatlarini O'YLAB CHIQARMAYDI ───────────────────────
def test_adapter_source_copy_snapshot_plan_hash_YARATMAYDI():
    """Bular metadata разведкаsidan KELIB CHIQMAYDI va mustaqil tasdiqlanishi shart."""
    members = A.to_bundle_members(export_dict(), source_kind="copy")
    hammasi = b"".join(members.values()).decode("utf-8")
    for taqiqlangan in ("source_copy", "snapshot_at", "plan_sha256", "copy_sha256"):
        assert taqiqlangan not in hammasi, f"adapter {taqiqlangan!r} ni o'ylab chiqardi"


def test_source_kind_OPERATOR_eloni_eksportdan_OLINMAYDI():
    assert build(source_kind="copy").discovery["source"]["kind"] == "copy"
    with pytest.raises(B.DiscoveryError, match="ATAYLAB ruxsat"):
        build(source_kind="live")                       # jonli manba ruxsatsiz RAD
    assert build(source_kind="live", allow_live=True).discovery["source"]["kind"] == "live"


@pytest.mark.parametrize("yomon", ["", "COPY", "nusxa", None])
def test_notogri_source_kind_RAD(yomon):
    with pytest.raises(B.DiscoveryError, match="source_kind"):
        A.to_bundle_members(export_dict(), source_kind=yomon)


# ── 4. DETERMINIZM ────────────────────────────────────────────────────────────────────────
def test_bir_xil_eksport_AYNAN_bir_xil_baytlar():
    a = A.to_bundle_members(export_dict(), source_kind="copy")
    c = A.to_bundle_members(export_dict(), source_kind="copy")
    assert a == c
    assert B.content_hash(build()) == B.content_hash(build())


def test_kalit_TARTIBI_chiqishga_tasir_qilmaydi():
    """Eksportdagi kalit tartibi boshqa bo'lsa ham natija AYNAN bir xil."""
    e1 = export_dict()
    e2 = {k: e1[k] for k in reversed(list(e1))}
    assert A.to_bundle_members(e1, source_kind="copy") == A.to_bundle_members(e2, source_kind="copy")


# ── 5. SXEMA MOSLIGI VA NOTO'G'RI IDENTIFIKATORLAR ────────────────────────────────────────
def test_notanish_eksport_versiyasi_RAD():
    with pytest.raises(B.DiscoveryError, match="export_version"):
        A.to_bundle_members(export_dict(export_version="binos-1c-export-v2"), source_kind="copy")


def test_notanish_kalit_RAD():
    e = export_dict()
    e["qoshimcha_kalit"] = "x"
    with pytest.raises(B.DiscoveryError, match="noma'lum kalit"):
        A.to_bundle_members(e, source_kind="copy")


def test_tushib_qolgan_kalit_RAD():
    e = export_dict()
    del e["counts"]
    with pytest.raises(B.DiscoveryError, match="tushib qolgan"):
        A.to_bundle_members(e, source_kind="copy")


def test_notanish_NISHON_RAD():
    with pytest.raises(B.DiscoveryError, match="target noma'lum"):
        A.to_bundle_members(export_dict(candidates=[candidate("products.yoq_nishon")]),
                            source_kind="copy")


def test_notanish_DALIL_turi_RAD():
    e = export_dict(candidates=[candidate("products.code", source_object=CATALOG,
                                          source_kind="attribute",
                                          evidence=[ev("men_shunday_oylayman", "x")])])
    with pytest.raises(B.DiscoveryError, match="kind noma'lum"):
        A.to_bundle_members(e, source_kind="copy")


def test_notanish_MANBA_turi_RAD():
    e = export_dict(candidates=[candidate("products.code", source_object=CATALOG,
                                          source_kind="qandaydir_registr",
                                          evidence=[ev("name_match", "x")])])
    with pytest.raises(B.DiscoveryError, match="source_kind noma'lum"):
        A.to_bundle_members(e, source_kind="copy")


def test_takror_nishon_RAD():
    e = export_dict(candidates=[candidate("products.code", source_object=CATALOG,
                                          source_kind="attribute",
                                          evidence=[ev("name_match", "a")]),
                                candidate("products.code", source_object=CATALOG,
                                          source_kind="attribute",
                                          evidence=[ev("name_match", "b")])])
    with pytest.raises(B.DiscoveryError, match="takrorlangan"):
        A.to_bundle_members(e, source_kind="copy")


@pytest.mark.parametrize("yomon", [7137, 7137.0, "7 137", "-1", "", "1e5"])
def test_sanoq_JSON_SONI_bolsa_RAD(yomon):
    """JSON soni TAQIQLANGAN: `000537` soni bo'lganda `537` bo'lib qolardi."""
    e = export_dict(candidates=[candidate("products.code", source_object=CATALOG,
                                          source_kind="attribute", row_count=yomon,
                                          evidence=[ev("name_match", "x")])])
    with pytest.raises(B.DiscoveryError, match="sanoq MATN"):
        A.to_bundle_members(e, source_kind="copy")


def test_ONLIK_nol_sanoqda_SAQLANADI():
    e = export_dict(counts=[count(CATALOG, "000537")])
    assert build(e).counts["counts"][0]["value"] == "000537"


# ── 6. QO'LLAB-QUVVATLANMAYDIGAN KONFIGURATSIYA ───────────────────────────────────────────
def test_KORILMAGAN_obyektga_nomzod_RAD():
    """Xarita sweep'da ko'rilgan obyektga ishora qilishi SHART (izchillik darvozasi)."""
    e = export_dict(candidates=[candidate("products.code", source_object="Справочник.YoqObyekt",
                                          source_field="Код", source_kind="attribute",
                                          evidence=[ev("name_match", "x")])])
    with pytest.raises(B.DiscoveryError, match="KO'RILMAGAN obyektga"):
        build(e)


def test_yiqilgan_bolim_PARTIAL_qiladi():
    e = export_dict(sections=[section("platform"), section("counts", "failed", "so'rov yiqildi")])
    b = build(e)
    assert b.status["status"] == "PARTIAL"


def test_HAMMA_bolim_yiqilsa_BLOCKED_va_SABABI_yoziladi():
    e = export_dict(sections=[section("platform", "failed", "x"),
                              section("counts", "skipped", "o'tkazib yuborildi")])
    b = build(e)
    assert b.status["status"] == "BLOCKED"
    assert "counts" in b.status["blocked_reason"] and "platform" in b.status["blocked_reason"]


def test_XARAKTERISTIKA_va_BIRLIK_aniqlanmasa_UNKNOWN_bolib_qoladi():
    """Bu ikkisi ochiq STOP — adapter ularni «bor» deb ko'rsatib qo'ymasligi kerak."""
    b = build()
    for nishon in ("products.has_characteristics", "products.unit", "products.is_weighted"):
        assert b.mapping(nishon)["confidence"] == "UNKNOWN"


# ── 7. MAXFIYLIK / REDAKSIYA ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sir", [
    "Srvr=10.0.0.5;Ref=buxgalteriya;Usr=Admin;Pwd=Qwerty123;",
    "parol: Qwerty12345",
    "https://admin:sirparol@1c.example.com/base",
])
def test_SIR_topilsa_toplam_RAD(sir):
    """Redaksiya fail-closed: sir ko'rinsa to'plam umuman o'qilmaydi."""
    e = export_dict(notes=["sintetik fikstura", sir])
    with pytest.raises(B.DiscoveryError):
        build(e)


def test_metadata_only_eksportda_NAMUNA_yoq():
    """Metadata-only разведкаda qiymat namunalari UMUMAN bo'lmaydi."""
    members = A.to_bundle_members(export_dict(), source_kind="copy")
    assert not [k for k in members if k.startswith("samples/")]
    assert all(m["sample_count"] is None for m in build().discovery["mappings"])


# ── 8. XULOSA FAYLI ───────────────────────────────────────────────────────────────────────
def test_xulosa_DETERMINISTIK_va_ogohlantirishni_saqlaydi():
    a = A.to_bundle_members(export_dict(), source_kind="copy")["summary.md"].decode("utf-8")
    c = A.to_bundle_members(export_dict(), source_kind="copy")["summary.md"].decode("utf-8")
    assert a == c
    assert "YAROQLI ekanini ISBOTLAMAYDI" in a       # nishon topilgani yetarli emas
    assert "CANDIDATE" in a
