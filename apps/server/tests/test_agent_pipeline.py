# -*- coding: utf-8 -*-
"""Agent QUVURI va HISOBOTI: `pipeline.py` + `report.py`.

⚠️⚠️ BU TESTLAR 1C GA TEGMAYDI va tegishi ham mumkin emas: bu mashinada 1C UMUMAN
     O'RNATILMAGAN (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q, `pywin32` yo'q). Kirish —
     SINTETIK runtime paketlari (`tests/discovery_1c_runtime_mock.py`), ya'ni ular BinOS
     tomonidagi quvur mantiqini isbotlaydi va yig'uvchining 1C da ISHLASHI haqida HECH
     QANDAY da'vo qilmaydi: integratsiya yo'llari `RUNTIME-UNKNOWN`.

ISBOTLANADIGAN INVARIANTLAR:
  · sog'lom paket -> `COMPLETE`, hisobot va ko'rik artefakti CHIQADI;
  · validator chiqish kodi `1` -> `FAILED_VALIDATION`, quvur DAVOM ETMAYDI (grafga ham
    yetib bormaydi);
  · ⚠️ chiqish kodi `2` (paket to'g'ri, yurish TO'LIQ EMAS) -> quvur TO'XTAYDI va sababi
    `notes` da OCHIQ yoziladi — JIMGINA davom etish YO'Q;
  · chiqish kodi yadroning `cli.main` i bergan AYNI kod bilan mos (shartnoma QULFLANGAN);
  · buzuq inventarizatsiya -> `FAILED_VALIDATION`;
  · analitik ISTISNO tashlasa -> `FAILED_ANALYSIS` va hisobot UMUMAN yozilmaydi (jim bo'sh
    hisobot YO'Q);
  · ⚠️ `analyzer=None` -> deterministik `HeuristicAnalyzer` (offline-first MAJBURIY);
  · birorta nomzodda `VERIFIED` ham, `HUMAN_CONFIRMED` ham YO'Q;
  · `UNKNOWN` konseptlar hisobotda QOLADI («qaralmadi» ≠ «yo'q»);
  · determinizm: bir xil kirish -> AYNAN bir xil bayt;
  · sir topilsa -> ISTISNO va hisobotda ham, yurish yozuvida ham sir YO'Q;
  · zond TASDIQSIZ bajarilmaydi va `METADATA_ONLY` da umuman rejalashtirilmaydi;
  · tarmoq importi (`socket`/`requests`/`urllib`/`http.client`) ikki modulda ham YO'Q.

ATAYLAB SINALMAYDI:
  · 1C ning haqiqiy xulqi, `.epf` ning bajarilishi, COM yo'li — fikstura ham yo'q, da'vo ham
    yo'q;
  · yadroning O'Z mantiqi (validator, graf, analitik, zond allowlisti, redaksiya) — ular
    ALOHIDA testlarda qulflangan va bu quvur ularni QAYTA YOZMAYDI, faqat chaqiradi.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from app.services.discovery_1c import cli as core_cli
from app.services.discovery_1c.ai import FORBIDDEN_STATUS, STATUS_HUMAN_CONFIRMED
from app.services.discovery_1c.analyst.heuristics import NullAnalyzer
from app.services.discovery_1c.review import REVIEW_VERSION
from app.services.discovery_1c.runtime_bundle import (MODE_APPROVED_PROBES, MODE_METADATA_ONLY,
                                                      VERIFIED_WORD_RE,
                                                      validate_runtime_bundle)
from app.services.discovery_agent import (AGENT_STATUS_FILE, AI_CANDIDATES_FILE, BUNDLE_SUBDIR,
                                          REPORT_FILE, ROUTE_BATCH_EXECUTE,
                                          ROUTE_WATCH_FOLDER)
from app.services.discovery_agent import collector_bridge as bridge
from app.services.discovery_agent import pipeline as P
from app.services.discovery_agent import report as R
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as ss
from tests import discovery_1c_runtime_mock as M

T0 = "2026-10-01T09:00:00+06:00"
T1 = "2026-10-01T09:05:00+06:00"

#: Quvurgacha bo'lgan qadamlar — ular BOSHQA qatlamning ishi, bu yerda faqat YO'L.
OLDINGI: tuple[str, ...] = (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                            st.METADATA_DISCOVERY)


def kirish(*, run_id: str = "run-0001", mode: str = MODE_METADATA_ONLY, route=None,
           probes=()) -> ss.AgentStatus:
    """`METADATA_DISCOVERY` holatidagi yurish yozuvi — quvurning kirishi."""
    s = ss.new_run(run_id, now=T0)
    for to in OLDINGI:
        s = s.advance(to, now=T0)
    s = s.with_mode(mode)
    if route is not None:
        s = s.with_route(route)
    for p in probes:
        s = s.with_probe(p)
    return s


def yurish(papka, *, analyzer=None, status=None, now: str = T1) -> P.PipelineResult:
    return P.run_pipeline(str(papka), status=kirish() if status is None else status,
                          analyzer=analyzer, now=now)


def sog_lom(tmp_path, nom: str = "bundle") -> pathlib.Path:
    """Sog'lom SINTETIK runtime paketi (`bundle/` ostki papkasida — shartnoma shunday)."""
    d = tmp_path / nom
    d.mkdir()
    M.paket_sog_lom(str(d))
    return d


def holatlar(result: P.PipelineResult) -> list[str]:
    """Yurish bosib o'tgan holatlar (o'tishlar zanjirining nishonlari)."""
    return [t.to_state for t in result.status.transitions]


class Yiqiladigan:
    """ISTISNO tashlaydigan analitik. ⚠️ U «buzuq javob» bermaydi, UMUMAN yiqiladi —
    quvur tashqi kodning istisnosini JIM YUTMASLIGI kerak."""

    def analyze(self, payload):
        raise RuntimeError("analitik yiqildi: sintetik nuqson")


@pytest.fixture(scope="module")
def sog_lom_papka(tmp_path_factory) -> pathlib.Path:
    """Sog'lom SINTETIK paket — MODUL doirasida bir marta yoziladi (faqat O'QILADI)."""
    d = tmp_path_factory.mktemp("sog-lom") / BUNDLE_SUBDIR
    d.mkdir()
    M.paket_sog_lom(str(d))
    return d


@pytest.fixture(scope="module")
def sog_lom_yurish(sog_lom_papka) -> P.PipelineResult:
    """Sog'lom paketdagi ODATIY yurish — MODUL doirasida BIR MARTA.

    ⚠️ QAYTA ISHLATISH XAVFSIZ, chunki natija O'ZGARMAS (frozen `PipelineResult` va
       `AgentStatus`) va quvur DETERMINISTIK — bu `test_determinizm_...` da alohida
       isbotlanadi. Har testda qaytadan yurgizish esa to'plamni bir necha baravar
       sekinlashtirardi va HECH QANDAY yangi invariantni o'lchamasdi."""
    return yurish(sog_lom_papka)


@pytest.fixture(scope="module")
def yiqilgan_tahlil(sog_lom_papka) -> P.PipelineResult:
    """Analitik ISTISNO tashlagan yurish — MODUL doirasida bir marta (natija o'zgarmas)."""
    return yurish(sog_lom_papka, analyzer=Yiqiladigan())


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · SOG'LOM YO'L
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_sog_lom_paket_complete_va_hisobot_bilan_tugaydi(sog_lom_yurish):
    r = sog_lom_yurish
    assert r.state == st.COMPLETE and r.ok
    assert r.validator_exit_code == P.EXIT_OK
    assert r.status.errors == ()
    # ⚠️ Uch artefakt: yurish yozuvi, ko'rik artefakti va hisobot. `environment.json` va
    #    `agent_manifest.json` BOSHQA qatlamlarning ishi, shu bois bu yerda YO'Q.
    assert r.names == (AGENT_STATUS_FILE, AI_CANDIDATES_FILE, REPORT_FILE)
    assert r.status.artifacts == (AGENT_STATUS_FILE, AI_CANDIDATES_FILE, REPORT_FILE)


def test_korik_artefakti_yadroning_sxemasida_chiqadi(sog_lom_yurish):
    doc = json.loads(sog_lom_yurish.output(AI_CANDIDATES_FILE).decode("utf-8"))
    assert doc["review_version"] == REVIEW_VERSION
    assert doc["candidates"], "sintetik konfiguratsiyada nomzod chiqishi kutiladi"
    # ⚠️ Qamrov ATAYLAB `None` («o'lchanmadi»): `heuristics.coverage()` analitikni QAYTA
    #    yurgizadi, quvur esa uni AYNAN BIR MARTA chaqiradi.
    assert doc["coverage"] is None


def test_quvur_qadamlari_shartnoma_tartibida_boradi(sog_lom_yurish):
    assert holatlar(sog_lom_yurish) == list(OLDINGI) + [st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS,
                                           st.REPORT, st.COMPLETE]


def test_paket_papkasi_nisbiy_nom_bilan_yoziladi(sog_lom_yurish, sog_lom_papka):
    """⚠️ Absolyut yo'l SIR: `redact` uni Windows fayl yo'li deb biladi va yozuvni RAD
    etardi. Shu bois yozuvda shartnomaviy `bundle` nomi turadi, berilgan yo'l EMAS."""
    r = sog_lom_yurish
    assert r.status.bundle_dir == BUNDLE_SUBDIR
    for xom in (r.output(AGENT_STATUS_FILE).decode("utf-8"), r.report_text):
        assert str(sog_lom_papka) not in xom and str(sog_lom_papka.parent) not in xom


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · VALIDATOR SHARTNOMASI (0 / 1 / 2)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_validator_kodi_1_quvur_davom_etmaydi(tmp_path):
    d = tmp_path / "bundle"
    d.mkdir()
    M.paket_manifest_mos_emas(str(d))
    r = yurish(d)
    assert r.validator_exit_code == P.EXIT_INVALID
    assert r.state == st.FAILED_VALIDATION and not r.ok
    assert [e.code for e in r.status.errors] == ["BUNDLE_INVALID"]
    # ⚠️ Grafga ham, tahlilga ham YETIB BORMAYDI: noto'g'ri paketdan chiqarilgan xulosa
    #    noto'g'ri bo'ladi.
    assert st.GRAPH_BUILD not in holatlar(r) and st.ANALYSIS not in holatlar(r)
    assert r.graph is None and r.review is None and r.hypotheses == ()
    # ⚠️ Hisobot ham, ko'rik artefakti ham YOZILMAYDI — faqat yurish yozuvi qoladi.
    assert r.names == (AGENT_STATUS_FILE,)
    assert r.report_text is None


def test_validator_kodi_2_quvur_toxtaydi_va_sabab_yoziladi(tmp_path):
    """⚠️ PAKET TO'G'RI, YURISH TO'LIQ EMAS. Bu `1` dan FARQ QILADI va quvur JIMGINA davom
    etmaydi: yarim yurishdan chiqarilgan xulosa to'liq xulosaga o'xshab ketardi."""
    d = tmp_path / "bundle"
    d.mkdir()
    M.paket_qismli_inspeksiya(str(d))
    r = yurish(d)
    assert r.validator_exit_code == P.EXIT_INCOMPLETE
    assert r.validation.ok is True, "paketning BAYTLARI to'g'ri — nuqson paketda emas"
    assert r.validation.overall != "SUCCESS"
    assert r.state == st.FAILED_VALIDATION
    assert [e.code for e in r.status.errors] == ["BUNDLE_RUN_INCOMPLETE"]
    sabab = " ".join(r.status.notes)
    assert "TO'XTADI" in sabab and "2" in sabab
    assert st.GRAPH_BUILD not in holatlar(r)
    assert r.report_text is None


def test_kod_1_va_kod_2_bir_xil_holatda_ham_AYRIM_kod_bilan_yoziladi(tmp_path):
    """⚠️ Ikkisi ham `FAILED_VALIDATION` ga tushadi (holat alifbosi arxitektor tomonidan
    QOTIRILGAN va kengaytirilmaydi), lekin XATO KODI ularni ajratadi: operatorning
    harakati boshqa — birinchisida paket qayta yig'iladi, ikkinchisida yiqilgan bo'limning
    sababi `errors.json` dan o'qiladi."""
    bir = tmp_path / "bir"
    bir.mkdir()
    M.paket_manifest_mos_emas(str(bir))
    ikki = tmp_path / "ikki"
    ikki.mkdir()
    M.paket_qismli_inspeksiya(str(ikki))
    a, b = yurish(bir), yurish(ikki)
    assert a.state == b.state == st.FAILED_VALIDATION
    assert {e.code for e in a.status.errors} != {e.code for e in b.status.errors}


@pytest.mark.parametrize("generator", ["paket_sog_lom", "paket_qismli_inspeksiya",
                                       "paket_serializatsiya_yarim", "paket_manifest_mos_emas",
                                       "paket_sir_oqqan", "paket_oila_oqilmadi",
                                       "paket_yolgon_success", "paket_oila_yoq"])
def test_chiqish_kodi_yadroning_cli_kodi_bilan_AYNI(tmp_path, generator):
    """⚠️ SHARTNOMA QULFLANDI: quvur kodni O'ZI hisoblaydi, lekin javob yadroning
    `cli.main` i bergan kod bilan AYNAN bir xil bo'lishi SHART. Ikki joyda yozilgan
    shartnoma bir kun ajralib ketadi — shu test aynan o'sha kunni ushlaydi."""
    import io

    d = tmp_path / "bundle"
    d.mkdir()
    getattr(M, generator)(str(d))
    kutilgan = core_cli.main([core_cli.VALIDATE_CMD, str(d), "--json"],
                            out=io.StringIO(), err=io.StringIO())
    assert P.validator_exit_code(validate_runtime_bundle(str(d))) == str(kutilgan)


def test_papka_yoq_failed_validation_va_absolyut_yol_yozuvga_tushmaydi(tmp_path):
    """⚠️ Validator nuqsoni ichida PAPKA YO'LI bo'ladi; `status.to_json()` esa absolyut
    Windows yo'lini sir deb bilib BUTUN yozuvni rad etardi — ya'ni niqoblamasa, yiqilishning
    SABABI ham yo'qolardi."""
    r = yurish(tmp_path / "umuman-yoq")
    assert r.state == st.FAILED_VALIDATION
    xom = r.output(AGENT_STATUS_FILE).decode("utf-8")
    assert "umuman-yoq" not in xom and str(tmp_path) not in xom
    assert "[REDACTED]" in xom, "yo'l NIQOBLANGAN bo'lishi kerak, jim o'chirilgan emas"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · INVENTARIZATSIYA (METADATA)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_buzuq_metadata_failed_validation(tmp_path):
    """`metadata.json` YARIM yozilgan — buzuq JSON. ⚠️ Manifest xeshi yarim baytlarga MOS
    keladi, ya'ni nuqsonni faqat qat'iy JSON o'qish tuta oladi."""
    d = tmp_path / "bundle"
    d.mkdir()
    M.paket_serializatsiya_yarim(str(d))
    r = yurish(d)
    assert r.state == st.FAILED_VALIDATION
    assert r.validator_exit_code == P.EXIT_INVALID
    assert r.graph is None and r.report_text is None


def test_metadata_sxemasi_quvurda_IKKINCHI_darvoza(sog_lom_papka, monkeypatch):
    """⚠️ `runtime_bundle` inventarizatsiyani allaqachon tekshiradi, shu bois sog'lom
    paketda bu darvoza YIQILMAYDI. U baribir bor, chunki quvur grafni SHU hujjatdan quradi
    — «validator tekshirgan bo'lsa kerak» degan taxmin bilan emas. Shu bois darvoza
    chaqirilishi ISBOTLANADI."""
    def yiqil(doc):
        raise ValueError("sintetik: inventarizatsiya sxemasi mos emas")

    monkeypatch.setattr(P, "validate_metadata", yiqil)
    r = yurish(sog_lom_papka)
    assert r.state == st.FAILED_VALIDATION
    assert [e.code for e in r.status.errors] == ["METADATA_INVALID"]
    assert st.GRAPH_BUILD not in holatlar(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · TAHLIL
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_analitik_istisno_tashlasa_failed_analysis_va_hisobot_UMUMAN_yozilmaydi(
        yiqilgan_tahlil):
    r = yiqilgan_tahlil
    assert r.state == st.FAILED_ANALYSIS and not r.ok
    assert [e.code for e in r.status.errors] == ["ANALYSIS_FAILED"]
    # ⚠️ JIM BO'SH HISOBOT YO'Q: hisobot ham, ko'rik artefakti ham yozilmaydi.
    assert r.names == (AGENT_STATUS_FILE,)
    assert r.report_text is None
    assert r.review is None and r.hypotheses == ()
    # ⚠️ Graf QURILGAN va u joyida qoladi: tahlilni 1C siz, keyinroq ham qayta yurgizish
    #    mumkin.
    assert r.graph is not None


def test_analitik_istisnosining_sababi_YUTILMAYDI(yiqilgan_tahlil):
    detal = yiqilgan_tahlil.status.errors[0].detail
    assert "sintetik nuqson" in detal and "Yiqiladigan" in detal


def test_analyzer_none_deterministik_rejim_ISHLAYDI(sog_lom_yurish):
    """⚠️ OFFLINE-FIRST MAJBURIY: analitik berilmasa ham quvur ISHLAYDI — tarmoq ham,
    cloud AI ham kerak emas. Bu REJIM, zaxira yo'l emas."""
    r = sog_lom_yurish
    assert r.state == st.COMPLETE
    assert r.review["analyzer"]["name"] == "HeuristicAnalyzer"
    assert any("HeuristicAnalyzer" in n and "offline-first" in n for n in r.status.notes)


def test_versiyasini_elon_qilmagan_analitik_uchun_raqam_OYLAB_CHIQARILMAYDI(sog_lom_yurish):
    assert sog_lom_yurish.review["analyzer"]["version"] == P.ANALYZER_VERSION_UNDECLARED


def test_bosh_tahlil_ham_COMPLETE_beradi_lekin_hammasi_UNKNOWN(sog_lom_papka):
    """⚠️ `NullAnalyzer` buzuq EMAS: u shartnomaga mos BO'SH javob beradi. Bo'sh tahlil
    «hech narsa yo'q» degani emas — hamma konsept `UNKNOWN` bo'lib QOLADI."""
    r = yurish(sog_lom_papka, analyzer=NullAnalyzer())
    assert r.state == st.COMPLETE
    assert r.review["candidates"] == []
    assert len(r.review["unknown_concepts"]) == 23
    assert "Birorta nomzod chiqmadi" in r.report_text


def test_birorta_nomzodda_VERIFIED_ham_HUMAN_CONFIRMED_ham_YOQ(sog_lom_yurish):
    """⚠️ `VERIFIED` bu kanalda UMUMAN yo'q, `HUMAN_CONFIRMED` esa faqat OPERATORNING
    alohida tasdiq hujjatidan keladi — quvur `allow_human_confirmed=True` ni HECH QACHON
    uzatmaydi."""
    r = sog_lom_yurish
    holatlar_ = {c["status"] for c in r.review["candidates"]}
    assert FORBIDDEN_STATUS not in holatlar_
    assert STATUS_HUMAN_CONFIRMED not in holatlar_
    assert all(h.status not in (FORBIDDEN_STATUS, STATUS_HUMAN_CONFIRMED)
               for h in r.hypotheses)
    assert f"- **Holat:** `{FORBIDDEN_STATUS}`" not in r.report_text
    assert f"- **Holat:** `{STATUS_HUMAN_CONFIRMED}`" not in r.report_text


def test_hisobotda_taqiqlangan_tasdiq_SOZI_umuman_YOQ(sog_lom_yurish):
    """⚠️ YADRONING DARVOZASI QAYTA ISHLATILADI (`runtime_bundle.VERIFIED_WORD_RE`): tasdiq
    so'zi agent chiqaradigan HAR QANDAY matnda taqiqlangan — so'z artefaktda turmasa, hech
    bir artefakt tasdiq DA'VOSINI olib yura olmaydi.
    ⚠️ So'z hisobotga TASHQI matndan ham tushadi: tahlilchining izohi AYNAN shu so'z bilan
    «bu daraja yo'q» deb aytadi. Shu bois u O'RNI bilan almashtiriladi va almashtirish
    hisobotning BOSHIDA ochiq aytiladi — jim tahrir EMAS.
    ⚠️ `0.1.0-UNVERIFIED` halol versiya va u RAD ETILMAYDI (so'z chegarasi)."""
    matn = sog_lom_yurish.report_text
    assert VERIFIED_WORD_RE.search(matn) is None
    assert R.FORBIDDEN_WORD_LABEL in matn
    assert "ALMASHTIRILDI" in matn, "almashtirish OCHIQ aytilishi kerak"
    # Tahlilchining izohi hisobotda QOLADI — faqat taqiqlangan so'z o'rni bilan almashgan.
    assert "Eng yuqori holat CANDIDATE" in matn
    # Halol versiya o'tadi: agent va yig'uvchi versiyalari `UNVERIFIED` bilan tugaydi.
    assert "UNVERIFIED" in matn


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · HISOBOT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_hisobot_boshida_HAMMA_ogohlantirish_turadi(sog_lom_yurish):
    matn = sog_lom_yurish.report_text
    bosh = matn.split("## Yurish xulosasi")[0]
    for ogoh in R.HEADER_WARNINGS:
        assert ogoh in bosh, "ogohlantirish hisobotning BOSHIDA turishi kerak"


def test_watch_folder_yoli_BIRINCHI_HAQIQIY_SINOV_deb_aytiladi(sog_lom_papka,
                                                               sog_lom_yurish):
    """⚠️ Bu yo'lda `.epf` ni operator O'Z 1C sessiyasida QO'LDA ochgan, ya'ni AYNI SHU
    YURISH yig'uvchining birinchi haqiqiy sinovi. Buni aytmaslik «sinalgan» degan JIM
    da'vo bo'lardi."""
    r = yurish(sog_lom_papka, status=kirish(route=ROUTE_WATCH_FOLDER))
    assert R.WATCH_FOLDER_WARNING in r.report_text
    assert "BIRINCHI HAQIQIY sinovi" in r.report_text
    # Yo'l ko'rsatilmagan yurishda bu ogohlantirish BO'LMAYDI (yolg'on da'vo ham xato).
    assert R.WATCH_FOLDER_WARNING not in sog_lom_yurish.report_text


def test_hisobotda_har_nomzod_uchun_DALIL_va_QARSHI_DALIL_bor(sog_lom_yurish):
    matn = sog_lom_yurish.report_text
    soni = len(sog_lom_yurish.review["candidates"])
    for sarlavha in ("- **Dalil:**", "- **Qarshi dalil:**", "- **Noaniqlik:**",
                     "- **Talab qilinadigan tasdiq:**",
                     "- **Keyingi tavsiya etilgan zond:**",
                     "- **Ball (`confidence_score`):**"):
        assert matn.count(sarlavha) == soni, sarlavha


def test_UNKNOWN_konseptlar_hisobotda_QOLADI(sog_lom_yurish):
    """⚠️ «Qaralmadi» va «yo'q» BIR XIL NARSA EMAS: tushirib qoldirilgan konsept keyinchalik
    «tekshirilgan va topilmagan» deb o'qilardi."""
    r = sog_lom_yurish
    noma_lum = r.review["unknown_concepts"]
    assert noma_lum, "sintetik konfiguratsiyada qaralmagan konsept bo'lishi kutiladi"
    bo_lim = r.report_text.split("## `UNKNOWN` konseptlar")[1]
    for konsept in noma_lum:
        assert f"`{konsept}`" in bo_lim
    assert "«Qaralmadi» va «yo'q» BIR XIL NARSA EMAS" in bo_lim


def test_hisobotda_yurish_xulosasi_toliq(sog_lom_yurish):
    matn = sog_lom_yurish.report_text
    for kerak in ("**Rejim:**", "**Yo'l:**", "**Holat:**", "### Artefaktlar", "### Xatolar",
                  "### Zondlar", "### Izohlar", "chiqish kodi"):
        assert kerak in matn
    assert MODE_METADATA_ONLY in matn


def test_hisobot_YIQILGAN_yurish_uchun_ham_quriladi(yiqilgan_tahlil):
    """⚠️ Quvur hisobotni faqat `REPORT` holatida yozadi, lekin UI qatlami yiqilishni ham
    SHU modul bilan ko'rsatishi kerak — ikkinchi «hisobot yozuvchi» paydo bo'lmasligi
    uchun."""
    r = yiqilgan_tahlil
    matn = R.build_report(status=r.status, review=None, validation=r.validation,
                          exit_code=r.validator_exit_code)
    assert st.FAILED_ANALYSIS in matn
    assert st.failure_meaning(st.FAILED_ANALYSIS) in matn
    assert "Tahlil BAJARILMADI yoki yakunlanmadi" in matn
    assert "Bu «nomzod yo'q» degani EMAS" in matn


def test_hisobot_darvozasi_yiqilsa_FAILED_REPORT(sog_lom_papka, monkeypatch):
    """⚠️ `ReportError` — hisobotning O'Z darvozalari (shakl + sir skani). Bu MUHIT yoki
    CHIQISH muammosi, nuqson emas, shu bois `FAILED_REPORT`."""
    def yiqil(**kw):
        raise R.ReportError("sintetik: chiqishda shubhali qiymat")

    monkeypatch.setattr(P, "build_report", yiqil)
    r = yurish(sog_lom_papka)
    assert r.state == st.FAILED_REPORT
    assert [e.code for e in r.status.errors] == ["REPORT_FAILED"]
    # ⚠️ Tahlil TUGAGAN, shu bois ko'rik artefakti QOLADI — hisobot esa yozilmaydi.
    assert r.names == (AGENT_STATUS_FILE, AI_CANDIDATES_FILE)
    assert r.report_text is None


def test_kutilmagan_istisno_FAILED_INTERNAL_bolib_YOZUVGA_tushadi(sog_lom_papka, monkeypatch):
    """⚠️ Kutilmagan istisno JIM YUTILMAYDI, lekin tashqariga ham CHIQMAYDI: u
    `FAILED_INTERNAL` bo'lib yozuvga tushadi. `FAILED_INTERNAL` «agentning O'ZIDA nuqson»
    degani — qolgan `FAILED_*` esa muhit yoki paket haqidagi HUKM, va ikkisini aralashtirish
    nuqsonni oddiy nosozlik qilib ko'rsatardi."""
    def yiqil(**kw):
        raise TypeError("sintetik: quvurning o'zida nuqson")

    monkeypatch.setattr(P, "build_report", yiqil)
    r = yurish(sog_lom_papka)
    assert r.state == st.FAILED_INTERNAL
    assert [e.code for e in r.status.errors] == ["PIPELINE_INTERNAL_ERROR"]
    assert "TypeError" in r.status.errors[0].detail
    assert r.output(AGENT_STATUS_FILE) is not None, "nuqson ham YOZUV bilan qaytadi"


def test_validatsiya_bajarilmagani_muammo_yoq_deb_yozilmaydi():
    """⚠️ FAIL-CLOSED: «bajarilmadi» «muammo yo'q» EMAS."""
    matn = R.build_report(status=kirish(), review=None, validation=None, exit_code=None)
    assert "BAJARILMADI" in matn and "«muammo yo'q» EMAS" in matn




# ══════════════════════════════════════════════════════════════════════════════════════════
# 5b · YO'L HAQQONIYLIGI (brief §7) — HISOBOT «AVTOMATIK BAJARILDI» DEMAYDI
#
# ⚠️⚠️ NEGA BU BO'LIM BOR: `watch_folder` yo'lida 1C ni OPERATOR ishga tushiradi. Hisobot
#      «avtomatik razvedka bajarildi» degan ma'noni bersa, u ODAMNING ishini agentga yozib
#      qo'yardi — ya'ni keyingi o'qiydigan odam «agent buni o'zi qila oladi» deb ishonib,
#      1C bo'lmagan mashinada ham shunday bo'lishini kutardi.
# ══════════════════════════════════════════════════════════════════════════════════════════
def _yol_bolimi(matn: str) -> str:
    """Hisobotning «Yo'l va operator aralashuvi» bo'limi."""
    i = matn.index("## Yo'l va operator aralashuvi")
    keyingi = matn.find("\n## ", i + 10)
    return matn[i:] if keyingi < 0 else matn[i:keyingi]


def test_yol_bolimi_UCHTA_savolga_javob_beradi(sog_lom_papka):
    """⚠️ Brief §7 ning uchta savoli: qaysi yo'l · operator aralashuvi · `batch_execute` nega
    ishlatilmadi. Uchovi bitta bo'limda turadi — tarqalib ketgan javobni odam yig'ib
    o'qimaydi."""
    s = kirish(route=ROUTE_WATCH_FOLDER)
    s = s.with_error(bridge.SCOPE_BATCH, bridge.CODE_BATCH_NOT_ATTEMPTED,
                     bridge.BATCH_NOT_ATTEMPTED_REASON)
    bolim = _yol_bolimi(yurish(sog_lom_papka, status=s).report_text)
    assert "Ishlatilgan yo'l:" in bolim and f"`{ROUTE_WATCH_FOLDER}`" in bolim
    assert "Operator aralashuvi:" in bolim and "BO'LDI" in bolim
    assert f"`{ROUTE_BATCH_EXECUTE}` nega ishlatilmadi" in bolim
    assert bridge.CODE_BATCH_NOT_ATTEMPTED in bolim


def test_yol_bolimi_sababni_YURISH_YOZUVIDAN_oladi_oylab_chiqarmaydi(sog_lom_papka):
    """⚠️ Sabab `agent_status.errors` dan AYNI holda ko'chiriladi: hisobot ikkinchi «sabab
    manbasi» bo'lsa, ikki hujjat bir kun zid javob berardi."""
    s = kirish(route=ROUTE_WATCH_FOLDER).with_error(
        bridge.SCOPE_BATCH, bridge.CODE_BATCH_NOT_ATTEMPTED, bridge.BATCH_NOT_ATTEMPTED_REASON)
    bolim = _yol_bolimi(yurish(sog_lom_papka, status=s).report_text)
    assert bridge.BATCH_NOT_ATTEMPTED_REASON in bolim


def test_sabab_QAYD_ETILMAGAN_bolsa_hisobot_buni_NUQSON_deb_aytadi(sog_lom_papka):
    """⚠️⚠️ JIMGINA YIQILISH YO'Q (brief §4): yo'l `watch_folder` bo'lib sabab yozilmagan
         bo'lsa, hisobot bo'sh bo'limni JIM qoldirmaydi — «sabab QAYD ETILMAGAN, bu NUQSON»
         deb AYTADI. Aks holda yo'l tanlovi izsiz bo'lib qolardi."""
    bolim = _yol_bolimi(
        yurish(sog_lom_papka, status=kirish(route=ROUTE_WATCH_FOLDER)).report_text)
    assert "QAYD ETILMAGAN" in bolim and "NUQSON" in bolim


def test_watch_folder_yolida_AVTOMATIK_RAZVEDKA_DAVOSI_hisobotda_YOQ(sog_lom_papka):
    """⚠️⚠️ STATIK QULF: `route == watch_folder` bo'lgan hisobotda avtomatlashtirish
         iborasining BIRORTASI chiqmaydi."""
    matn = yurish(sog_lom_papka, status=kirish(route=ROUTE_WATCH_FOLDER)).report_text
    for nom, rx in R.AUTOMATIC_CLAIM_PATTERNS:
        uchraydi = rx.search(matn)
        assert uchraydi is None, f"{nom}: {uchraydi.group(0)!r}"


def test_watch_folder_yolida_INKOR_satri_OCHIQ_yoziladi(sog_lom_papka):
    """⚠️ Jim qolish yetarli emas: «agent 1C ni ishga TUSHIRMADI» ochiq aytilishi SHART,
    aks holda o'quvchi bo'shliqni o'zi to'ldiradi."""
    matn = yurish(sog_lom_papka, status=kirish(route=ROUTE_WATCH_FOLDER)).report_text
    assert R.NO_AUTOMATION_LINE in matn
    assert "ISHGA TUSHIRMADI" in matn
    assert "AVTOMATIK razvedka EMAS" in matn


def test_AVTOMATIK_DAVO_hisobotni_YOZILMAS_qiladi_fail_closed(sog_lom_papka):
    """⚠️⚠️ BU DARVOZA TESTDAN KUCHLI: ibora `notes` ga tashqi manbadan tushib qolsa ham
         hisobot UMUMAN yozilmaydi (`ReportError`), ya'ni yolg'on da'vo bilan paket chiqmaydi.
    ⚠️ `pipeline` bu holatda `FAILED_REPORT` beradi — jimgina bo'sh hisobot YO'Q."""
    s = kirish(route=ROUTE_WATCH_FOLDER).with_note(
        "paket paketli yo'l bilan olindi")       # ⚠️ YOLG'ON izoh: shu yo'lda bo'lishi mumkin emas
    with pytest.raises(R.ReportError) as xato:
        R.build_report(status=s)
    assert ROUTE_WATCH_FOLDER in str(xato.value)
    r = yurish(sog_lom_papka, status=s)
    assert r.status.state == st.FAILED_REPORT
    assert r.report_text is None, "yolg'on da'vo bilan hisobot YOZILMAYDI"


def test_batch_execute_yolida_darvoza_ISHLAMAYDI_va_bu_ATAYLAB(sog_lom_papka):
    """⚠️ Darvoza FAQAT `watch_folder` uchun: paketli yo'lda agent ROSTDAN o'zi ishga
    tushiradi, demak u yerda «paketli yo'l bilan olindi» degan izoh HALOL."""
    s = kirish(route=ROUTE_BATCH_EXECUTE).with_note("paket paketli yo'l bilan olindi")
    matn = R.build_report(status=s)
    assert "paketli yo'l bilan olindi" in matn
    bolim = _yol_bolimi(matn)
    assert f"`{ROUTE_BATCH_EXECUTE}`" in bolim
    assert "URINDI" in bolim and "DEGANI EMAS" in bolim


def test_yol_yozilmagan_yurishda_hisobot_BUNI_NUQSON_deb_aytadi(sog_lom_yurish):
    """⚠️ `route` `null` bo'lsa, hisobot «avtomatik bo'ldi» ham, «operator qildi» ham
    DEMAYDI: u yo'l yozilmaganini NUQSON deb qayd etadi."""
    bolim = _yol_bolimi(sog_lom_yurish.report_text)
    assert R.NOT_RECORDED in bolim and "NUQSON" in bolim
    assert R.NO_AUTOMATION_LINE not in bolim, "yo'l noma'lum bo'lsa INKOR ham DA'VO bo'lardi"


def test_yol_bolimi_XULOSADAN_OLDIN_turadi(sog_lom_papka):
    """⚠️ Operator eng avval «bu avtomatik bo'ldimi» degan savolga javob olishi kerak:
    qolgan hamma satr shu javob ostida o'qiladi."""
    matn = yurish(sog_lom_papka, status=kirish(route=ROUTE_WATCH_FOLDER)).report_text
    assert matn.index("## Yo'l va operator aralashuvi") < matn.index("## Yurish xulosasi")


def test_avtomatik_davo_naqshlari_INKORNI_tutmaydi():
    """⚠️⚠️ YOLG'ON IJOBIY DARVOZASI: naqshlar TASDIQ shaklida yozilgan, ya'ni hisobotning
         O'Z inkor satrlari (va operator qadamlari) darvozani bloklamaydi. Bu test shuni
         qulflaydi — aks holda darvoza bir kun HAR BIR hisobotni rad etib, kimdir uni
         butunlay o'chirib tashlardi."""
    halol = (R.NO_AUTOMATION_LINE, R.WATCH_FOLDER_WARNING,
             R.INTERVENTION_BY_ROUTE[ROUTE_WATCH_FOLDER],
             bridge.OPERATOR_RAN_COLLECTOR_NOTE, bridge.BATCH_NOT_ATTEMPTED_REASON,
             bridge.WATCH_FOLDER_PROVENANCE_NOTE) + bridge.WATCH_FOLDER_OPERATOR_STEPS
    for matn in halol:
        for nom, rx in R.AUTOMATIC_CLAIM_PATTERNS:
            uchraydi = rx.search(matn)
            assert uchraydi is None, f"yolg'on ijobiy — {nom}: {uchraydi.group(0)!r}"


@pytest.mark.parametrize("yolgon", [
    "avtomatik razvedka bajarildi",
    "avtomatik 1C razvedkasi bajarildi",
    "hammasi avtomatik bajarildi",
    "agent 1C ni o'zi ishga tushirdi",
    "paket paketli yo'l bilan olindi",
    "batch_execute bajarildi",
    "bitta bosishda avtomatik razvedka",
])
def test_naqshlar_HAQIQIY_davo_iboralarini_TUTADI(yolgon):
    """⚠️ TESKARI TOMON: darvoza ROSTDAN tutishi kerak. Naqsh bo'lib hech narsa tutmaydigan
    darvoza «bizda darvoza bor» degan yolg'on xotirjamlik bo'lardi."""
    assert any(rx.search(yolgon) for _nom, rx in R.AUTOMATIC_CLAIM_PATTERNS), yolgon


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · SIR (FAIL-CLOSED)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_hisobotda_sir_topilsa_ISTISNO_va_qiymat_korsatilmaydi(sog_lom_yurish):
    """⚠️ Sir ko'rik artefaktiga uch yo'l bilan tushishi mumkin (metadata izohi, operator
    matni, tahlilchi nomi). Bu yerda u ATAYLAB QO'LDA qo'yiladi: `build_review` o'z
    darvozasini allaqachon qo'yadi, lekin hisobot YOZUVCHISI ham o'z darvozasini
    qo'yishi SHART — yozishdan oldingi holat muhim."""
    r = sog_lom_yurish
    buzuq = json.loads(r.output(AI_CANDIDATES_FILE).decode("utf-8"))
    buzuq["analyzer_notes"] = [f"baza bilan ishlash xatosi: {M.SIR_ULANISH}"]

    with pytest.raises(R.ReportError) as xato:
        R.build_report(status=r.status, review=buzuq, validation=r.validation,
                       exit_code=r.validator_exit_code)
    matn = str(xato.value)
    assert "RAD etildi" in matn and "satr " in matn
    # ⚠️ Nuqson matnida QIYMATNING O'ZI ko'rsatilmaydi (`redact.Finding.__str__` qoidasi).
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat not in matn


def test_sir_oqqan_paket_validatsiyada_toxtaydi_va_sir_yozuvga_tushmaydi(tmp_path):
    """⚠️ HAQIQIY OQIM: yig'uvchi 1C xatosini `errors.json` ga qo'yadi, SUBD xatosi esa
    ulanish satrini O'Z ICHIGA OLADI. Darvoza shu bois aynan shu yerda turadi."""
    d = tmp_path / "bundle"
    d.mkdir()
    M.paket_sir_oqqan(str(d))
    r = yurish(d)
    assert r.state == st.FAILED_VALIDATION
    xom = r.output(AGENT_STATUS_FILE).decode("utf-8")
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat not in xom
    assert r.report_text is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · DETERMINIZM
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_determinizm_ikki_yurish_AYNAN_bir_xil_bayt(tmp_path):
    """⚠️ Bir xil kirish — AYNAN bir xil bayt. Papka yo'li ikki xil, natija bir xil: yo'l
    chiqishga umuman tushmaydi."""
    bir = yurish(sog_lom(tmp_path, "bir"))
    ikki = yurish(sog_lom(tmp_path, "ikki"))
    assert bir.outputs == ikki.outputs
    assert bir.output(REPORT_FILE) == ikki.output(REPORT_FILE)
    assert bir.output(AI_CANDIDATES_FILE) == ikki.output(AI_CANDIDATES_FILE)


def test_artefakt_royxati_TARTIBLANGAN(sog_lom_yurish):
    r = sog_lom_yurish
    assert list(r.names) == sorted(r.names)
    assert list(r.status.artifacts) == sorted(r.status.artifacts)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · ZONDLAR — TASDIQSIZ BAJARILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_metadata_only_rejimda_zond_rejalashtirilmaydi_ham(sog_lom_yurish):
    """⚠️ MVP DEFAULT: zond YO'Q. Tavsiya etilgan zondlar FAQAT ko'rik artefaktida TAKLIF
    bo'lib qoladi — yurish yozuvida zond yozuvi PAYDO BO'LMAYDI."""
    r = sog_lom_yurish
    assert r.status.probes == ()
    assert st.OPTIONAL_APPROVED_PROBES not in holatlar(r)
    assert st.REVALIDATE not in holatlar(r)
    assert r.revalidation is None and r.revalidation_exit_code is None
    assert any(c["recommended_next_probe"] for c in r.review["candidates"]), \
        "tavsiya BO'LISHI kerak — lekin u BAJARILGAN amal emas"


def test_tasdiqlangan_zond_paketda_natijasiz_bolsa_FAILED_SAFETY(sog_lom_papka):
    """⚠️ Operator zondni tasdiqlagan, paket esa `METADATA_ONLY` rejimida yozilgan va zond
    natijasi YO'Q: tasdiq BOSHQA yurishga tegishli bo'lishi mumkin. Bu xavfsizlik
    ziddiyati, «zond yo'q» EMAS."""
    yozuv = ss.ProbeRecord(no="1", probe_type="row_count",
                           target_object="Справочник.Товары",
                           reason="qator sanog'i gipotezani tasdiqlaydi yoki rad etadi",
                           file=f"{BUNDLE_SUBDIR}/probes/01_row_count.json",
                           status="APPROVED")
    r = yurish(sog_lom_papka,
               status=kirish(mode=MODE_APPROVED_PROBES, probes=(yozuv,)))
    assert r.state == st.FAILED_SAFETY
    assert [e.code for e in r.status.errors] == ["PROBE_MODE_MISMATCH"]
    assert st.OPTIONAL_APPROVED_PROBES in holatlar(r)
    assert st.REVALIDATE not in holatlar(r)
    assert r.report_text is None


def test_taklif_tasdiq_EMAS(tmp_path):
    """⚠️ `PROPOSED` holati tasdiq hisoblanmaydi: taklif analitikdan, tasdiq esa
    OPERATORDAN keladi."""
    assert "PROPOSED" not in P.APPROVED_PROBE_STATUSES
    assert "DENIED" not in P.APPROVED_PROBE_STATUSES
    assert "SKIPPED" not in P.APPROVED_PROBE_STATUSES
    assert P.APPROVED_PROBE_STATUSES <= set(ss.PROBE_STATUSES)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · KIRISH HOLATI VA YOZISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_notogri_kirish_holati_FAILED_INTERNAL_bilan_yoziladi(sog_lom_papka):
    """⚠️ Quvur undan oldingi qadamlarni (muhit skaneri, nishon tanlash, xavfsizlik
    darvozasi) O'YLAB CHIQARMAYDI: ular BOSHQA qatlamning ishi."""
    r = P.run_pipeline(str(sog_lom_papka), status=ss.new_run("run-0002", now=T0), now=T1)
    assert r.state == st.FAILED_INTERNAL
    assert [e.code for e in r.status.errors] == ["PIPELINE_STATE_INVALID"]
    assert r.output(AGENT_STATUS_FILE) is not None, "yiqilish ham YOZUV bilan qaytadi"


def test_yakunlangan_yurish_qayta_yurgizilmaydi(sog_lom_yurish, sog_lom_papka):
    """⚠️ Yakunlangan yurish QAYTA boshlanmaydi — yangi yurish YANGI `run_id` oladi."""
    with pytest.raises(P.PipelineError, match="YANGI"):
        P.run_pipeline(str(sog_lom_papka), status=sog_lom_yurish.status, now=T1)


def test_write_outputs_paket_fayllariga_TEGMAYDI(tmp_path):
    """⚠️ Phase 4 paketi `bundle/` da O'ZGARMAGAN holda qoladi va agent ILDIZDA
    `manifest.json` YOZMAYDI: bir xil nom, ikki xil sxema Phase 4 da butun paketni rad
    etgan nuqson edi."""
    natija = tmp_path / "binos-discovery-2026"
    natija.mkdir()
    paket = natija / BUNDLE_SUBDIR
    paket.mkdir()
    M.paket_sog_lom(str(paket))
    oldin = {p.name: p.read_bytes() for p in paket.iterdir()}

    r = P.run_pipeline(str(paket), status=kirish(), now=T1)
    yozilgan = P.write_outputs(r, out_dir=str(natija))

    assert yozilgan == r.names
    assert {p.name for p in natija.iterdir()} == {BUNDLE_SUBDIR, AGENT_STATUS_FILE,
                                                 AI_CANDIDATES_FILE, REPORT_FILE}
    assert not (natija / "manifest.json").exists()
    assert {p.name: p.read_bytes() for p in paket.iterdir()} == oldin
    assert (natija / REPORT_FILE).read_bytes() == r.output(REPORT_FILE)


def test_run_pipeline_OZI_hech_narsa_yozmaydi(tmp_path):
    """⚠️ Yozmaydigan qadamni to'liq sinash mumkin, va «chiqishga yozishdan oldin tekshir»
    qoidasi shu bilan buzilmas bo'ladi (`status.py` dagi bilan AYNI sabab)."""
    natija = tmp_path / "natija"
    natija.mkdir()
    paket = natija / BUNDLE_SUBDIR
    paket.mkdir()
    M.paket_sog_lom(str(paket))
    r = P.run_pipeline(str(paket), status=kirish(), now=T1)
    assert r.state == st.COMPLETE
    assert {p.name for p in natija.iterdir()} == {BUNDLE_SUBDIR}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · STATIK QO'RIQCHILAR
# ══════════════════════════════════════════════════════════════════════════════════════════
MODULLAR = ("pipeline.py", "report.py")

#: ⚠️ TARMOQ YO'Q: offline-first talab, da'vo emas. Import BO'LMASLIGI kerak — «ishlatmaymiz»
#: degan izoh keyingi o'zgarishda jimgina yo'qoladi.
TAQIQLANGAN_IMPORT = frozenset({"socket", "requests", "urllib", "urllib.request", "urllib3",
                                "http", "http.client", "httpx", "ftplib", "smtplib",
                                "telnetlib", "xmlrpc", "asyncio", "subprocess"})


def _modul_ast(nom: str) -> ast.Module:
    yo_l = (pathlib.Path(P.__file__).parent / nom)
    return ast.parse(yo_l.read_text(encoding="utf-8"))


@pytest.mark.parametrize("nom", MODULLAR)
def test_tarmoq_va_jarayon_importi_YOQ(nom):
    """⚠️ `subprocess` ham ro'yxatda: quvur zondni O'ZI BAJARMAYDI va 1C ni ishga
    tushirmaydi — jarayon ochish yo'li bu modullarda umuman bo'lmasligi kerak."""
    topilgan = set()
    for node in ast.walk(_modul_ast(nom)):
        if isinstance(node, ast.Import):
            topilgan |= {a.name.split(".")[0] for a in node.names}
            topilgan |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            topilgan.add(node.module)
            topilgan.add(node.module.split(".")[0])
    assert not (topilgan & TAQIQLANGAN_IMPORT), f"{nom}: taqiqlangan import"


@pytest.mark.parametrize("nom", MODULLAR)
def test_tashqi_kutubxona_YOQ(nom):
    """⚠️ Faqat stdlib + yadro: do'kon kompyuterida Python o'rnatish talab qilinmasligi
    kerak va `pywin32` bu mashinada umuman o'rnatilmagan."""
    ruxsat = {"ast", "dataclasses", "json", "os", "pathlib", "re", "__future__", "typing"}
    for node in ast.walk(_modul_ast(nom)):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in ruxsat, f"{nom}: {a.name}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert node.module.split(".")[0] in ruxsat, f"{nom}: {node.module}"


def test_quvur_yadro_funksiyalarini_CHAQIRADI_qayta_yozmaydi():
    """⚠️ Phase 3/4 moduli MAVJUD va ISHLAYDI. Mantiqni qayta yozish REGRESSIYA bo'lardi:
    ikki nusxa bir kun bir-biridan ajralib ketadi va qaysi biri haqiqat ekani aniqlanmay
    qoladi. Shu bois chaqiriladigan nomlar SHU YERDA qulflangan."""
    matn = pathlib.Path(P.__file__).read_text(encoding="utf-8")
    for chaqiruv in ("rb.validate_runtime_bundle(", "validate_metadata(", "build_graph(",
                     "ai.analyst_payload(", "ai.validate_analysis(",
                     "core_review.build_review(", "core_review.dumps_review(",
                     "validate_probe(", "build_report("):
        assert chaqiruv in matn, chaqiruv
    # ⚠️ Chiqish kodi raqamlari yadroning `cli` konstantalaridan quriladi, bu yerda qayta
    #    yozilmaydi.
    assert "core_cli.EXIT_PROBLEM" in matn and "core_cli.EXIT_INCOMPLETE" in matn


def test_read_only_quvurda_ozgarmaydi(sog_lom_yurish):
    """⚠️ `read_only` MAYDON EMAS, XOSSA: unga qiymat berishning yo'li yo'q — quvur ham
    uni o'zgartira olmaydi."""
    r = sog_lom_yurish
    assert r.status.read_only == "true"
    assert json.loads(r.output(AGENT_STATUS_FILE).decode("utf-8"))["read_only"] == "true"
