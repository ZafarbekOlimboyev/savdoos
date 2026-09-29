# -*- coding: utf-8 -*-
"""`binos-1c-discovery-v1` yadrosi — 1C RUNTIME'SIZ to'liq sinaladi.

Bu fayl yadroning shartnomasini qulflaydi: sxema, validator, ishonch qoidasi, redaksiya,
deterministik yozish, qisman-xato semantikasi va «yadroda konfiguratsiyaga oid bilim yo'q»
invarianti.
"""
from __future__ import annotations

import pytest

from app.services.discovery_1c import (SCHEMA_VERSION, STATUS_BLOCKED, STATUS_COMPLETE,
                                       STATUS_PARTIAL)
from app.services.discovery_1c import bundle as D
from app.services.discovery_1c import redact as R
from app.services.discovery_1c.schema import (STRONG_EVIDENCE_KINDS, TARGETS, WEAK_EVIDENCE_KINDS,
                                              confidence_error)
from tests.discovery_1c_synth import (SECTIONS_OK, all_unknown_mappings, counts_dict,
                                      count as mk_count, discovery_dict, ev, mapping, members,
                                      obj, sample_dict, status_dict, sweep_dict, with_mapping)


def load(**kw):
    return D.load_members(members(**kw))


# ── Asosiy oqim ────────────────────────────────────────────────────────────────────────────
def test_sintetik_toplam_yuklanadi():
    b = load()
    assert b.overall_status == STATUS_COMPLETE
    assert len(b.content_sha256) == 64
    assert len(b.mappings) == len(TARGETS)


def test_sxema_versiyasi_qulflangan():
    d = discovery_dict()
    d["schema_version"] = "binos-1c-discovery-v2"
    with pytest.raises(D.DiscoveryError, match="schema_version"):
        load(discovery=d)


def test_notanish_kalit_rad_etiladi():
    d = discovery_dict()
    d["yangi_maydon"] = "x"
    with pytest.raises(D.DiscoveryError, match="noma'lum kalit"):
        load(discovery=d)


def test_kalit_yetishmasa_rad_etiladi():
    d = discovery_dict()
    del d["notes"]
    with pytest.raises(D.DiscoveryError, match="yetishmayapti"):
        load(discovery=d)


def test_majburiy_fayl_yoq():
    with pytest.raises(D.DiscoveryError, match="majburiy fayl yo'q: counts.json"):
        D.load_members(members(drop=("counts.json",)))


# ── Invariant: nishon TUSHIB QOLMAYDI ──────────────────────────────────────────────────────
def test_nishon_tushib_qolsa_rad():
    ms = [m for m in all_unknown_mappings() if m["target"] != "products.plu"]
    with pytest.raises(D.DiscoveryError, match=r"tushib qolgan \['products\.plu'\]"):
        load(discovery=discovery_dict(mappings=ms))


def test_nishon_takrorlansa_rad():
    ms = all_unknown_mappings()
    ms.append(mapping("products.guid", errors=["ikkinchi marta"]))
    with pytest.raises(D.DiscoveryError, match="takrorlangan"):
        load(discovery=discovery_dict(mappings=ms))


def test_notanish_nishon_rad():
    ms = all_unknown_mappings()
    ms[0] = mapping("products.guid", errors=["x"])
    ms.append(mapping("products.guid", errors=["x"]))
    ms[-1]["target"] = "products.oydirma"
    with pytest.raises(D.DiscoveryError, match="target noma'lum"):
        load(discovery=discovery_dict(mappings=ms))


def test_barcha_nishonlar_unknown_bolsa_ham_toplam_haqiqiy():
    """«Hech narsa topilmadi» — bu ham to'liq javob, jim sukut emas."""
    b = load()
    assert {m["confidence"] for m in b.mappings} == {"UNKNOWN"}
    assert all(m["errors"] for m in b.mappings)


# ── Ishonch qoidasi: NOM MOSLIGI hech qachon VERIFIED bermaydi ──────────────────────────────
@pytest.mark.parametrize("kind", WEAK_EVIDENCE_KINDS)
def test_kuchsiz_dalil_verified_bermaydi(kind):
    assert confidence_error("VERIFIED", [kind], "attribute") is not None
    assert confidence_error("CANDIDATE", [kind], "attribute") is None


@pytest.mark.parametrize("kind", STRONG_EVIDENCE_KINDS)
def test_kuchli_dalil_verified_beradi(kind):
    src = "absent" if kind == "absence_proven" else "attribute"
    assert confidence_error("VERIFIED", [kind], src) is None


def test_yuzta_nom_mosligi_ham_verified_bermaydi():
    err = confidence_error("VERIFIED", ["name_match"] * 100, "attribute")
    assert err and "kuchli dalil" in err


def test_verified_kuchsiz_dalil_bilan_toplamda_rad():
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.barcodes", source_object="РегистрСведений.ВымышленныеКоды", source_field="Значение",
        source_kind="information_register", confidence="VERIFIED",
        evidence=[ev("name_match", "nomi «Штрихкод» ga o'xshaydi")]))
    with pytest.raises(D.DiscoveryError, match="VERIFIED faqat kuchli dalil"):
        load(discovery=discovery_dict(mappings=ms))


def test_verified_odam_tasdigi_bilan_otadi():
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.barcodes", source_object="РегистрСведений.ВымышленныеКоды", source_field="Значение",
        source_kind="information_register", confidence="VERIFIED",
        evidence=[ev("name_match", "nomi mos"),
                  ev("human_confirmed", "operator ekranda tasdiqladi, 2026-09-28")],
        row_count="59211", non_null_count="58888"))
    b = load(discovery=discovery_dict(mappings=ms))
    assert b.mapping("products.barcodes")["confidence"] == "VERIFIED"


# ── XARITA ↔ SWEEP IZCHILLIGI ─────────────────────────────────────────────────────────────
def test_KORILMAGAN_obyektga_xarita_RAD():
    """Ilgari to'rt fayl bir-biridan MUSTAQIL tekshirilardi: to'plam hech qachon ko'rilmagan
    obyektga ishora qilib ham o'tib ketardi. Bu discovery'ning ma'nosini buzadi — ko'rganlik
    dalili bilan bog'lanmagan da'vo taxmindan farq qilmaydi."""
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.code", source_object="Справочник.HechQachonKorilmagan", source_field="Код",
        source_kind="attribute", confidence="CANDIDATE",
        evidence=[ev("name_match", "nomi mos")]))
    with pytest.raises(D.DiscoveryError, match="KO'RILMAGAN obyektga"):
        load(discovery=discovery_dict(mappings=ms))


def test_KORILGAN_obyektga_xarita_OTADI():
    """Nazorat: sweep'da bor obyektga ishora qilgan AYNI xarita o'tadi."""
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.code", source_object="Справочник.Вымышленная", source_field="Код",
        source_kind="attribute", confidence="CANDIDATE",
        evidence=[ev("name_match", "nomi mos")]))
    assert load(discovery=discovery_dict(mappings=ms)).mapping("products.code")["source_object"]         == "Справочник.Вымышленная"


def test_ABSENT_xarita_sweepda_bolmasligi_KUTILGAN():
    """`absent` — yo'qlik DA'VOSI. U ta'rifi bo'yicha sweep'da obyekt yo'qligini bildiradi,
    shuning uchun izchillik tekshiruvidan ATAYLAB chetda qoladi."""
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.plu", source_object=None, source_kind="absent", confidence="VERIFIED",
        evidence=[ev("absence_proven", "butun konfiguratsiya bo'ylab qidirildi — yo'q")]))
    assert load(discovery=discovery_dict(mappings=ms)).mapping("products.plu")["source_kind"] == "absent"


def test_absent_verified_uchun_absence_proven_shart():
    base = dict(target="products.plu", source_kind="absent", confidence="VERIFIED")
    ms = with_mapping(all_unknown_mappings(), mapping(
        **base, evidence=[ev("cross_source_agreement", "ikki manba bir xil dedi")]))
    with pytest.raises(D.DiscoveryError, match="absence_proven"):
        load(discovery=discovery_dict(mappings=ms))

    ms = with_mapping(all_unknown_mappings(), mapping(
        **base, evidence=[ev("absence_proven", "butun metadata sanab chiqildi, mos maydon yo'q")]))
    assert D.load_members(members(discovery=discovery_dict(mappings=ms))) is not None


def test_unknown_darajasida_dalil_bolmaydi():
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.plu", confidence="UNKNOWN", evidence=[ev("name_match", "x")]))
    with pytest.raises(D.DiscoveryError, match="UNKNOWN darajasida dalil bo'lmasligi"):
        load(discovery=discovery_dict(mappings=ms))


def test_candidate_dalilsiz_bolmaydi():
    ms = with_mapping(all_unknown_mappings(), mapping("products.code", confidence="CANDIDATE"))
    with pytest.raises(D.DiscoveryError, match="kamida bitta dalil"):
        load(discovery=discovery_dict(mappings=ms))


# ── JSON soni TAQIQLANGAN ──────────────────────────────────────────────────────────────────
def test_sanoq_json_soni_bolsa_rad():
    m = mapping("products.code", errors=["x"])
    m["row_count"] = 7137                                   # MATN emas, son
    with pytest.raises(D.DiscoveryError, match="JSON son"):
        load(discovery=discovery_dict(mappings=with_mapping(all_unknown_mappings(), m)))


def test_xom_json_dagi_son_qabul_qilinmaydi():
    raw = members()
    raw["counts.json"] = raw["counts.json"].replace(b'"7137"', b"7137")
    with pytest.raises(D.DiscoveryError, match="JSON son"):
        D.load_members(raw)


def test_oldingi_nollar_saqlanadi():
    b = load()
    row = b.samples["samples/catalog.json"]["rows"][0]
    assert row[0] == "000537"                                # son bo'lganda 537 bo'lib qolardi


def test_non_null_row_countdan_katta_bolmaydi():
    m = mapping("products.code", source_object="X", source_field="Y", source_kind="attribute",
                confidence="CANDIDATE", evidence=[ev("fill_ratio", "to'ldirilgan")],
                row_count="10", non_null_count="11")
    with pytest.raises(D.DiscoveryError, match="katta"):
        load(discovery=discovery_dict(mappings=with_mapping(all_unknown_mappings(), m)))


# ── Qisman xato semantikasi ────────────────────────────────────────────────────────────────
def test_qisman_xato_partial_beradi():
    secs = [dict(s) for s in SECTIONS_OK]
    secs[1] = {"name": "metadata_sweep", "status": "failed",
               "error": "Запрос ruxsat rad etdi: недостаточно прав"}
    b = load(status=status_dict(sections=secs))
    assert b.overall_status == STATUS_PARTIAL


def test_hammasi_yiqilsa_blocked():
    secs = [{"name": s["name"], "status": "failed", "error": "xato"} for s in SECTIONS_OK]
    b = load(status=status_dict(sections=secs, blocked_reason="bazaga ulanib bo'lmadi"))
    assert b.overall_status == STATUS_BLOCKED


def test_blocked_sababsiz_bolmaydi():
    secs = [{"name": s["name"], "status": "failed", "error": "xato"} for s in SECTIONS_OK]
    with pytest.raises(D.DiscoveryError, match="blocked_reason"):
        load(status=status_dict(sections=secs))


def test_yiqilgan_bolim_sababsiz_qolmaydi():
    secs = [dict(s) for s in SECTIONS_OK]
    secs[0] = {"name": "platform", "status": "failed", "error": None}
    with pytest.raises(D.DiscoveryError, match="sababsiz qolmaydi"):
        load(status=status_dict(sections=secs))


def test_elon_qilingan_holat_bolimlarga_mos_kelishi_shart():
    """Yig'uvchi «COMPLETE» deb yozib, ichida yiqilgan bo'lim qoldira olmaydi."""
    secs = [dict(s) for s in SECTIONS_OK]
    secs[2] = {"name": "counts", "status": "skipped", "error": "vaqt yetmadi"}
    with pytest.raises(D.DiscoveryError, match="bo'limlarga mos emas"):
        load(status=status_dict(sections=secs, status=STATUS_COMPLETE))


def test_sanoq_olinmasa_sabab_shart():
    c = counts_dict([mk_count("catalog_rows", None, "Справочник.Вымышленная")])
    with pytest.raises(D.DiscoveryError, match="sababi `errors` da"):
        load(counts=c)
    c = counts_dict([mk_count("catalog_rows", None, "Справочник.Вымышленная",
                              errors=["ruxsat yo'q"])])
    assert D.load_members(members(counts=c)).counts["counts"][0]["value"] is None


# ── Sirlar ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("payload", [
    'File="C:\\bazalar\\fayzan"',
    "Srvr=10.0.0.5;Ref=trade;",
    "admin@example.com",
    "+996 555 123 456",
    "postgres://user:hunter2@host/db",
    "-----BEGIN RSA PRIVATE KEY-----",
    "пароль: 1234",
])
def test_sir_topilsa_toplam_rad(payload):
    d = discovery_dict(notes=[payload])
    with pytest.raises(D.DiscoveryError, match="sir topildi"):
        load(discovery=d)


def test_sirga_oxshash_ustun_nomi_rad():
    """Ustun NOMI «password» bo'lsa — qatorlar ham sir; namuna olinmaydi."""
    s = sample_dict(fields=("Код", "password"), rows=(("1", "x"),))
    with pytest.raises(D.DiscoveryError, match="sirga o‘xshash ustun nomi|sirga o'xshash ustun nomi"):
        load(samples={"samples/x.json": s})


def test_summary_md_ham_tekshiriladi():
    with pytest.raises(D.DiscoveryError, match="sir topildi"):
        load(summary="# Hisobot\n\nAnyDesk: 123 456 789\nпароль — qwerty\n")


def test_redaksiya_niqoblaydi_va_asl_obyekt_ozgarmaydi():
    src = {"notes": ["yozing: admin@example.com"], "password": "qwerty", "ok": "matn"}
    out = R.redact(src)
    assert out["password"] == R.MASK
    assert "admin@example.com" not in out["notes"][0]
    assert out["ok"] == "matn"
    assert src["password"] == "qwerty"                       # asl nusxa tegilmagan


def test_redaksiyadan_keyin_toplam_otadi():
    d = R.redact(discovery_dict(notes=["bog'laning: admin@example.com"]))
    assert D.load_members(members(discovery=d)) is not None


def test_oddiy_tovar_nomi_sir_deb_belgilanmaydi():
    """Yolg'on ijobiy narx: tarkibida raqam bo'lgan oddiy nom RAD ETILMASLIGI kerak."""
    s = sample_dict(fields=("Наименование",),
                    rows=(("Чай «Акбар» 100г",), ("Сок 1л 996",), ("Кефир 2,5% 0,5л",)))
    assert D.load_members(members(samples={"samples/x.json": s})) is not None


# ── Deterministik yozish va mazmun xeshi ───────────────────────────────────────────────────
def test_dumps_deterministik():
    a = D.dumps({"b": "1", "a": ["x", "y"]})
    b = D.dumps({"a": ["x", "y"], "b": "1"})
    assert a == b and a.endswith("\n")


def test_xesh_qator_tartibidan_mustaqil():
    ms = all_unknown_mappings()
    one = D.load_members(members(discovery=discovery_dict(mappings=ms)))
    two = D.load_members(members(discovery=discovery_dict(mappings=list(reversed(ms)))))
    assert one.content_sha256 == two.content_sha256


def test_xesh_vaqt_belgisidan_mustaqil():
    one = load()
    two = load(discovery=discovery_dict(collected_at="2027-01-01T00:00:00+06:00"),
               status=status_dict(started_at="2027-01-01T00:00:00+06:00",
                                  finished_at="2027-01-01T00:10:00+06:00"))
    assert one.content_sha256 == two.content_sha256


def test_xesh_mazmun_ozgarsa_ozgaradi():
    one = load()
    ms = with_mapping(all_unknown_mappings(), mapping(
        "products.code", source_object="Справочник.Вымышленная", source_field="Код",
        source_kind="standard_attribute", confidence="CANDIDATE",
        evidence=[ev("value_domain", "1–5 xonali raqam satri")]))
    two = load(discovery=discovery_dict(mappings=ms))
    assert one.content_sha256 != two.content_sha256


def test_xesh_xatolarni_ham_qamraydi():
    """«Xato bor» — javobning bir qismi; u xeshdan tushib qolmaydi."""
    one = load()
    secs = [dict(s) for s in SECTIONS_OK]
    secs[1] = {"name": "metadata_sweep", "status": "failed", "error": "ruxsat yo'q"}
    two = load(status=status_dict(sections=secs))
    assert one.content_sha256 != two.content_sha256


def test_toplam_yozib_qayta_oqilsa_xesh_teng(tmp_path):
    raw = members()
    D.write_dir(str(tmp_path), raw)
    assert D.load_dir(str(tmp_path)).content_sha256 == D.load_members(raw).content_sha256


# ── Manba: jonli baza ATAYLAB ruxsat talab qiladi ──────────────────────────────────────────
def test_jonli_manba_standart_holda_rad():
    d = discovery_dict(source_kind="live")
    with pytest.raises(D.DiscoveryError, match="ATAYLAB ruxsat"):
        load(discovery=d)


def test_jonli_manba_ataylab_ruxsat_bilan_otadi():
    d = discovery_dict(source_kind="live")
    assert D.load_members(members(discovery=d), allow_live_source=True).discovery["source"]["kind"] == "live"


# ── Vaqt va tuzilma ────────────────────────────────────────────────────────────────────────
def test_vaqt_zonasiz_sana_rad():
    with pytest.raises(D.DiscoveryError, match="vaqt zonasi"):
        load(discovery=discovery_dict(collected_at="2026-09-28T09:00:00"))


def test_tugash_boshlanishdan_oldin_bolmaydi():
    with pytest.raises(D.DiscoveryError, match="oldin bo'lolmaydi"):
        load(status=status_dict(started_at="2026-09-28T10:00:00+06:00",
                                finished_at="2026-09-28T09:00:00+06:00"))


def test_sweep_takror_obyekt_rad():
    o = obj("Справочник.Вымышленная", "catalog", "Вымышленная")
    with pytest.raises(D.DiscoveryError, match="full_name takrorlangan"):
        load(sweep=sweep_dict([o, dict(o)]))


def test_namuna_ustun_soni_mos_kelishi_shart():
    s = sample_dict(fields=("A", "B"), rows=(("1",),))
    with pytest.raises(D.DiscoveryError, match="ustunli ro'yxat"):
        load(samples={"samples/x.json": s})


def test_bosh_summary_rad():
    with pytest.raises(D.DiscoveryError, match="summary.md bo'sh"):
        load(summary="   \n")
