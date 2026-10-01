# -*- coding: utf-8 -*-
"""AGENTNING 16 SSENARIYSI — brief sanagan holatlar, har biri ALOHIDA test.

⚠️⚠️ BU TESTLAR REAL 1C ISHLASHINI ISBOTLAMAYDI. Bu mashinada 1C UMUMAN O'RNATILMAGAN
     (`C:\\Program Files\\1cv8` yo'q, `HKLM\\SOFTWARE\\1C\\1Cv8` yo'q, `1cv8.exe`/`ibcmd.exe`
     PATH da yo'q, `V83.COMConnector` ro'yxatda yo'q, `pywin32` yo'q). Kirish — SINTETIK
     reestr, SINTETIK `ibases.v8i` va SINTETIK Phase 4 runtime paketlari
     (`tests/agent_scenario_mock.py`, `tests/discovery_1c_runtime_mock.py`). Shu bois bu
     to'plam BinOS tomonidagi QAROR mantiqini o'lchaydi; integratsiya yo'llari
     (`batch_execute`, `watch_folder`) va COM yo'li `RUNTIME-UNKNOWN` bo'lib QOLADI.

ISBOTLANADIGAN ASOSIY INVARIANT (hammasining o'zagi):
    ⚠️ `UNKNOWN` HECH QACHON `NOT_FOUND` ga AYLANMAYDI.
    · «qaradim va 1C YO'Q» (`absent`) va «qaray OLMADIM» (`unknown`) — IKKI XIL natija;
    · «oila o'qildi va BO'SH» (`absent`) yurishni TUGATADI, «oilani o'qiy olmadim»
      (`unreadable`) yurishni TO'XTATADI — ikkisi bir xil yakun BERMAYDI;
    · tahlil hech qachon `VERIFIED` bermaydi, ikkilanishni esa YASHIRMAYDI.

USLUB QARORI: har ssenariy KUTILGAN XULQNI qulflaydi, MUAYYAN BALLNI emas. Heuristika
o'zgarishi nuqson EMAS; nuqson — invariantning buzilishi (tanlovning jimgina qilinishi,
qarshi dalilning yozilmasligi, `UNKNOWN` ning yo'qolishi).

⚠️ TARIX (bu izoh ESKIRMASIN): bu fayl yozilganda ikki nuqson `xfail(strict=True)` bilan
   BELGILANGAN edi — (1) 1C yo'q muhitda agent `FAILED_INTERNAL` berib natija papkasini
   UMUMAN yozmasdi, (2) `FAILED_NO_1C` ma'nosi aniqlovchining hukmi `unknown` bo'lsa ham
   «o'rnatilmagan» deb SHARTSIZ da'vo qilardi. IKKISI HAM TUZATILDI va markerlar OLIB
   TASHLANDI: testlarning O'ZI o'zgarmadi, ya'ni endi ular oddiy YASHIL test bo'lib
   nuqsonning qaytib kelishini qo'riqlaydi. `strict=True` naqshi kelajakda yangi nuqson
   topilganda yana ishlatilsin — u tuzatilgan zahoti testni QIZIL qiladi (XPASS) va belgi
   esdan chiqib ketmaydi.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re

import pytest

from app.services.discovery_1c import ai, probe
from app.services.discovery_1c import epf_audit
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c import schema
from app.services.discovery_1c.analyst.heuristics import HeuristicAnalyzer, NullAnalyzer
from app.services.discovery_1c.graph import build_graph
from app.services.discovery_agent import (AGENT_MANIFEST_FILE, AGENT_STATUS_FILE,
                                          AI_CANDIDATES_FILE, BUNDLE_SUBDIR, ENVIRONMENT_FILE,
                                          REPORT_FILE, RESULT_DIR_PREFIX,
                                          ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER)
from app.services.discovery_agent import collector_bridge as bridge
from app.services.discovery_agent import detector as D
from app.services.discovery_agent import pipeline as P
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as ss
from app.services.discovery_agent import ui as U
from tests import agent_scenario_mock as X
from tests import discovery_1c_metadata_synth as S
from tests import discovery_1c_runtime_mock as M

#: Yig'uvchi manbasi — `epf_audit` darvozasining HAQIQIY nishoni (13-ssenariy).
BSL_SOURCE = (pathlib.Path(__file__).resolve().parents[3]
              / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl")

#: Agent paketining modullari — statik qo'riqchilar uchun.
AGENT_PKG = pathlib.Path(U.__file__).resolve().parent

#: ⚠️ Nomdan kelib chiqadigan dalil turlari. 11-ssenariyda ular UMUMAN bo'lmasligi kerak:
#: nomlar ma'nosiz, demak nomzod FAQAT strukturadan chiqishi mumkin.
LEKSIK_DALILLAR = frozenset({"name_match", "synonym_match"})

#: ⚠️ Bu kanalda MUMKIN BO'LMAGAN dalil turlari: ular kuchli dalil va ular bilan
#: `VERIFIED`/`HUMAN_CONFIRMED` beriladi — metadata razvedkasida esa kuchli dalil YO'Q.
TAQIQLANGAN_DALILLAR = frozenset({"absence_proven", "human_confirmed"})


# ══════════════════════════════════════════════════════════════════════════════════════════
# YORDAMCHILAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def holatlar(papka) -> list[str]:
    """Yurish bosib o'tgan holatlar — `agent_status.json` dan O'QILADI, taxmin qilinmaydi."""
    return [t["to"] for t in json.loads(X.matn(papka, AGENT_STATUS_FILE))["transitions"]]


def yozuv(papka) -> dict:
    return json.loads(X.matn(papka, AGENT_STATUS_FILE))


def korik(papka) -> dict:
    return json.loads(X.matn(papka, AI_CANDIDATES_FILE))


def xato_kodlari(papka) -> list[str]:
    return [e["code"] for e in yozuv(papka)["errors"]]


#: ⚠️⚠️ HAR BIR `watch_folder` YURISHIDA ATAYLAB YOZILADIGAN XATO. Bu «yiqilish» EMAS: u
#: paketli yo'l (`batch_execute`) NEGA UMUMAN URINILMAGANINI qayd etadi (brief §4 — jimgina
#: yiqilish YO'Q). Shu bois quyidagi ssenariylar xato ro'yxatini TO'LIQ solishtirganda shu
#: kodni ham sanaydi: ro'yxatni qisqartirib solishtirish kutilmagan xatoni jimgina
#: o'tkazib yuborardi.
YOL_QAYDI = bridge.CODE_BATCH_NOT_ATTEMPTED


def dalil_turlari(review: dict) -> set[str]:
    """Ko'rik artefaktidagi HAMMA dalil va qarshi dalil turi."""
    turlar: set[str] = set()
    for c in review["candidates"]:
        for qator in list(c["evidence"]) + list(c["counter_evidence"]):
            turlar.add(qator["kind"])
    return turlar


def nomzodlar(review: dict, konsept: str) -> list[dict]:
    return [c for c in review["candidates"] if c["concept"] == konsept]


def agent_manbalari() -> list[tuple[str, str]]:
    """Agent paketining hamma `.py` fayli: `(nom, matn)`."""
    return [(p.name, p.read_text(encoding="utf-8"))
            for p in sorted(AGENT_PKG.glob("*.py"))]


class VerifiedBermoqchi:
    """`VERIFIED` bermoqchi bo'lgan analitik (15-ssenariy).

    ⚠️ DETERMINISTIK EVRISTIKANING JAVOBI OLINADI va FAQAT BITTA maydon — birinchi
       gipotezaning `status` i — o'zgartiriladi. Sabab: agar gipotezani qo'lda yozsam,
       `validate_analysis` uni BOSHQA sabab bilan (kalit nomi, dalil shakli) rad etishi
       mumkin edi va test o'zi o'lchamoqchi bo'lgan darvozani UMUMAN o'lchamay qolardi.
       Shu usulda rad etishning sababi ISBOTLANGAN holda `VERIFIED` bo'ladi.
    """

    name = "SintetikVerifiedBermoqchi"
    version = "0.0.1-SINTETIK"

    def analyze(self, payload):
        doc = dict(HeuristicAnalyzer().analyze(payload))
        gipotezalar = [dict(h) for h in doc["hypotheses"]]
        assert gipotezalar, ("fikstura birorta gipoteza bermadi — bunda ssenariy "
                            "o'lchanmay qolardi")
        gipotezalar[0]["status"] = ai.FORBIDDEN_STATUS
        doc["hypotheses"] = gipotezalar
        return doc


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · 1C UMUMAN O'RNATILMAGAN -> `FAILED_NO_1C`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_1_1c_yoqligi_ISBOTLANGAN_deb_belgilanadi_va_oqilmadi_bilan_aralashmaydi():
    """Hamma manba o'qildi va bo'sh chiqdi -> `absent` (JAVOB), `unknown` EMAS.

    ⚠️ BU ENG MUHIM AJRIM: `absent` da `FAILED_NO_1C` HAQLI, `unknown` da HAQLI EMAS. Ikkisi
       bitta xulosaga qo'shilsa, huquqi cheklangan hisobda 1C BOR bo'lsa ham agent «yo'q»
       deb to'xtardi — ya'ni `UNKNOWN` jimgina `NOT_FOUND` ga aylanardi.
    """
    yoq = X.muhit_1c_yoq()
    oqilmadi = X.muhit_huquq_yoq()

    assert yoq.installs == () and oqilmadi.installs == (), "ikkisida ham ro'yxat BO'SH"
    assert yoq.presence_verdict == D.PRESENCE_ABSENT
    assert yoq.is_absent_proven is True
    assert oqilmadi.presence_verdict == D.PRESENCE_UNKNOWN
    assert oqilmadi.is_absent_proven is False, "o'qilmagan manba «yo'q» ni ISBOTLAMAYDI"

    # ⚠️ Farq IZOHDA ham ko'rinadi: hisobotni o'qigan odam ikkisini adashtirmasligi kerak.
    assert "o'rnatilmagan (absent)" in yoq.notes[-1]
    assert "HAQLI EMAS" in oqilmadi.notes[-1]
    assert yoq.errors() == [], "o'qilgan va bo'sh manba XATO emas"
    assert [e["code"] for e in oqilmadi.errors()] == [D.CODE_REGISTRY_UNREADABLE]


# ⚠️ TUZATILDI (xfail OLIB TASHLANDI): `ui.UiModel._manzilgacha` manzil INDEKSIGACHA yuradi,
#    shu bois `HINT_SOURCE_STATE[FAILED_NO_1C]` joriy holatning O'ZI bo'lsa HECH QAYERGA
#    yurilmaydi. Avval kesim joriy holatni chiqarib tashlardi, zanjir `METADATA_DISCOVERY`
#    gacha borardi va RUXSAT ETILMAGAN o'tishda `FAILED_INTERNAL` chiqardi — natija papkasi
#    esa umuman yozilmasdi.
def test_1_1c_ornatilmagan_mashinada_agent_FAILED_NO_1C_beradi(tmp_path):
    """1C yo'q -> `FAILED_NO_1C` + natija papkasi (`FAILED_INTERNAL` EMAS).

    ⚠️ `FAILED_NO_1C` va `FAILED_INTERNAL` ni ARALASHTIRISH mumkin emas: birinchisi MUHIT
       haqidagi hukm («1C o'rnating»), ikkinchisi AGENTNING O'ZIDA nuqson («ishlab
       chiquvchiga uzating»). Operatorning keyingi qadami butunlay boshqa.
    """
    natija = X.agent(tmp_path, scan=X.muhit_1c_yoq(),
                     epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_NO_1C
    assert natija.result_dir is not None, "yiqilgan yurish ham HISOBOT bilan qoladi"
    assert st.FAILED_NO_1C in holatlar(natija.result_dir)
    assert bridge.CODE_EXE_MISSING in xato_kodlari(natija.result_dir)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · BIR NECHTA 1C O'RNATMASI -> HAMMASI RO'YXATDA, OPERATOR TANLAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_2_bir_nechta_ornatma_va_baza_hammasi_royxatda_tanlov_OPERATORDA(tmp_path):
    """Ikki o'rnatma + ikki baza: hech biri JIMGINA tashlanmaydi, tanlov operatorda.

    ⚠️ AGENT O'ZI TANLAMAYDI: birinchi baza faqat TAKLIF bo'lib belgilanadi va operator uni
       o'zgartira oladi. ⚠️ QAYTA SKANERLASH operator tanlovini USTIDAN YOZMAYDI — aks holda
       oynani yangilash jimgina boshqa bazaga razvedka yurgizardi.
    ⚠️ `locator` EKRANGA ham, hujjatga ham XOM holda chiqmaydi: fayl bazasining `locator` i
       mahalliy yo'l va u SIR deb hisoblanadi.
    """
    env = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path, "Birinchi baza"),
                         X.baza_parolli(tmp_path, "Ikkinchi baza"),
                         versiyalar=(X.ESKI_VERSIYA, X.YANGI_VERSIYA))
    model = X.agent(tmp_path, scan=env)
    model.refresh_environment()

    # ── Hamma o'rnatma ro'yxatda, eng yangisi ANIQ ────────────────────────────────────────
    assert [i.version for i in env.installs] == [X.ESKI_VERSIYA, X.YANGI_VERSIYA]
    assert env.newest_install().version == X.YANGI_VERSIYA
    hujjat = env.to_document()
    assert [i["version"] for i in hujjat["installs"]] == [X.ESKI_VERSIYA, X.YANGI_VERSIYA]
    assert {i["path"] for i in hujjat["installs"]} == {"[REDACTED]"}, "yo'l NIQOBLANADI"
    assert "2 o'rnatma" in model.install_line()

    # ── Hamma baza ro'yxatda, tanlov OPERATORDA ───────────────────────────────────────────
    yorliqlar = model.target_labels()
    assert len(yorliqlar) == 2
    assert "Birinchi baza" in yorliqlar[0] and "Ikkinchi baza" in yorliqlar[1]
    assert "parol kerakmi: unknown" in yorliqlar[0]
    assert "parol kerakmi: true" in yorliqlar[1]
    assert model.selected_index == 0, "birinchi baza faqat TAKLIF"

    model.select_target(1)
    model.refresh_environment()
    assert model.selected_index == 1, "qayta skanerlash OPERATOR tanlovini buzmaydi"
    assert model.selected_infobase().name == "Ikkinchi baza"

    # ⚠️ Oraliqdan tashqari tanlov JIMGINA 0 ga aylanmaydi — ISTISNO bo'ladi.
    with pytest.raises(U.UiError):
        model.select_target(5)

    # ⚠️ `locator` ekranda ham, hujjatda ham XOM emas.
    for yorliq in yorliqlar:
        assert str(tmp_path) not in yorliq
    assert {b["locator"] for b in hujjat["infobases"]} == {"[REDACTED]"}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · NISHON INFOBAZA YO'Q -> `FAILED_NO_TARGET`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_3_nishon_infobaza_yoq_FAILED_NO_TARGET(tmp_path):
    """1C BOR, baza YO'Q -> `FAILED_NO_TARGET` (`FAILED_NO_1C` EMAS).

    ⚠️ Ikkisini aralashtirish operatorni butunlay boshqa yo'lga yuborardi: birinchisida 1C
       o'rnatiladi, bu yerda esa mavjud 1C ga bazani ro'yxatga qo'shish kerak.
    """
    natija = X.agent(tmp_path, scan=X.muhit_bazasiz(tmp_path),
                     epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_NO_TARGET
    assert natija.result_dir is not None
    assert holatlar(natija.result_dir) == [st.ENVIRONMENT_SCAN, st.TARGET_SELECTION,
                                           st.FAILED_NO_TARGET], \
        "yiqilish O'Z holatidan yoziladi, «qulay» umumiy holatdan emas"
    assert xato_kodlari(natija.result_dir) == [bridge.CODE_NO_TARGET]
    assert yozuv(natija.result_dir)["route"] == ROUTE_BATCH_EXECUTE
    # ⚠️ Keyingi qadam AYTILADI: faqat «yiqildi» deydigan xabar qo'ng'iroqqa majbur qiladi.
    assert "ro'yxatga qo'shing" in X.matn(natija.result_dir, REPORT_FILE)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · AUTENTIFIKATSIYA TALAB QILINADI -> `FAILED_AUTH_REQUIRED`, PAROL BUYRUQ SATRIDA YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_4_parol_kerak_bolsa_FAILED_AUTH_REQUIRED_va_sir_CHIQISHDA_YOQ(tmp_path):
    """Parol kerak -> paketli yo'l BOSHLANMAYDI, `watch_folder` TAKLIF qilinadi.

    ⚠️ Agent parolni buyruq satriga QO'YMAYDI, chunki u jarayon ro'yxatida KO'RINADI. Shu
       bois yo'l umuman boshlanmaydi va operator `.epf` ni O'Z 1C sessiyasida ochadi —
       kirish oynasini 1C ning O'ZI ko'rsatadi, agent sirni KO'RMAYDI.
    ⚠️ Fiksturadagi `Usr=`/`Pwd=` qiymatlari TO'QIMA va test ularning CHIQISHDA
       uchramasligini isbotlaydi: `detector` faqat KALIT borligini o'qiydi, QIYMATNI emas.
    """
    env = X.muhit_bazali(tmp_path, X.baza_parolli(tmp_path))
    assert [b.requires_auth for b in env.infobases] == [D.TRI_TRUE]

    natija = X.agent(tmp_path, scan=env, epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_AUTH_REQUIRED
    assert xato_kodlari(natija.result_dir) == [bridge.CODE_AUTH_REQUIRED]
    izohlar = yozuv(natija.result_dir)["notes"]
    assert any(ROUTE_WATCH_FOLDER in n for n in izohlar), "zaxira yo'l TAKLIF qilinadi"

    # ⚠️ SIR HECH BIR ARTEFAKTDA YO'Q — `bundle/` ham, hisobot ham, muhit hujjati ham.
    for nom, raw in X.papka_baytlari(natija.result_dir).items():
        matn = raw.decode("utf-8", errors="replace")
        topilgan = [s for s in X.SIR_IZLARI if s in matn]
        assert not topilgan, f"{nom} ichida sir qoldi: {topilgan}"

    # ⚠️ EKRANDA ham faqat TALAB bor, QIYMAT yo'q: `requires_auth` uchlik matn, kredensial
    #    maydoni esa `detector.Infobase` da ATAYLAB mavjud emas.
    model = X.agent(tmp_path, scan=env)
    model.refresh_environment()
    yorliq = model.target_labels()[0]
    assert "parol kerakmi: true" in yorliq
    assert not [s for s in X.SIR_IZLARI if s in yorliq]
    assert not [f for f in D.Infobase.__dataclass_fields__
                if re.search(r"pwd|passw|parol|secret|user|login", f, re.I)]


def test_4b_statik_darvoza_parol_kaliti_buyruq_satriga_TUSHMAYDI(tmp_path):
    """STATIK tekshiruv: kredensial uchun MAYDON ham, KALIT ham, YO'L ham yo'q.

    ⚠️ Bu test «hozir kerak emas»: hech bir joy parol uzatmaydi. U KELAJAK uchun — kimdir
       «parolni ham berib yuboraylik-da» deb qo'shsa, darvoza shu yerda yiqiladi.
    """
    # ── (a) Rejada kredensial MAYDONI yo'q ───────────────────────────────────────────────
    maydonlar = set(bridge.CollectPlan.__dataclass_fields__)
    taqiq = re.compile(r"pwd|passw|parol|secret|credential|token|connect_string", re.I)
    assert not [m for m in maydonlar if taqiq.search(m)], \
        "«maydon bor, lekin bo'sh qoldiramiz» yo'li yaramaydi — bir kun kimdir to'ldiradi"

    # ── (b) Qurilgan buyruqda `/P`/`/N` YO'Q ─────────────────────────────────────────────
    reja = bridge.CollectPlan(
        epf_path=X.epf_yoz(tmp_path), output_dir=X.bosh_papka(tmp_path, "chiqish"),
        exe_path=X.exe_yoz(tmp_path), infobase_kind=D.KIND_FILE,
        infobase_locator=str(tmp_path / "sintetik-baza"), requires_auth=D.TRI_FALSE)
    buyruq = bridge.build_command(reja)
    assert buyruq[1] == bridge.VERB_ENTERPRISE
    for token in buyruq:
        for kalit in bridge.FORBIDDEN_SWITCHES:
            assert not token.upper().startswith(kalit.upper()), \
                f"taqiqlangan kalit buyruqqa tushdi: {kalit}"

    # ── (c) Darvoza ROSTDAN ishlaydi (kelajakdagi tahrir uchun) ──────────────────────────
    with pytest.raises(bridge.BridgeError, match="TAQIQLANGAN"):
        bridge._assert_no_credentials(buyruq + ("/Psintetikparol00",))

    # ── (d) Manbada `/P...` shaklidagi literal YO'Q ──────────────────────────────────────
    for nom, kod in agent_manbalari():
        for tugun in ast.walk(ast.parse(kod)):
            if isinstance(tugun, ast.Constant) and isinstance(tugun.value, str):
                if tugun.value[:2].upper() in ("/P", "/N"):
                    assert tugun.value in bridge.FORBIDDEN_SWITCHES, (
                        f"{nom}: `{tugun.value}` — kredensial kaliti QIYMAT bilan "
                        f"yozilgan ko'rinadi")
            if isinstance(tugun, ast.JoinedStr) and tugun.values:
                bosh = tugun.values[0]
                if isinstance(bosh, ast.Constant) and isinstance(bosh.value, str):
                    assert bosh.value[:2].upper() not in ("/P", "/N"), (
                        f"{nom}: f-satr `{bosh.value}...` kredensial kalitini QIYMAT bilan "
                        f"yig'ayotgan ko'rinadi")

    # ── (e) Funksiya PARAMETRI ham kredensial nomini ko'tarmaydi ─────────────────────────
    for nom, kod in agent_manbalari():
        for tugun in ast.walk(ast.parse(kod)):
            if isinstance(tugun, (ast.FunctionDef, ast.AsyncFunctionDef)):
                argnomlar = [a.arg for a in tugun.args.args + tugun.args.kwonlyargs]
                assert not [a for a in argnomlar if taqiq.search(a)], \
                    f"{nom}:{tugun.name} kredensial parametrini oladi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · YIG'UVCHI (`.epf`) MAVJUD EMAS -> `FAILED_COLLECTOR_UNAVAILABLE`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_5_yiguvchi_epf_yoq_FAILED_COLLECTOR_UNAVAILABLE(tmp_path):
    """`.epf` topilmadi -> javob YO'Q. ⚠️ `FAILED_NO_1C` EMAS: 1C BOR va topilgan.

    ⚠️ «Yig'uvchi yo'q» 1C bor-yo'qligi haqida HECH NARSA demaydi. Ikkisini bitta holatga
       qo'shib yuborish `UNKNOWN` ni `NOT_FOUND` ga aylantirishning aynan o'zi bo'lardi.
    """
    env = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))
    assert env.presence_verdict == D.PRESENCE_FOUND, "fikstura 1C NI TOPGAN bo'lishi kerak"

    natija = X.agent(tmp_path, scan=env,
                     epf_path=str(tmp_path / "umuman-yoq.epf"),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.state != st.FAILED_NO_1C
    assert xato_kodlari(natija.result_dir) == [bridge.CODE_EPF_MISSING]
    hisobot = X.matn(natija.result_dir, REPORT_FILE)
    assert "1C bor-yo'qligi haqida bu hech narsa demaydi" in hisobot
    # ⚠️ Paket umuman olinmagan, demak `bundle/` ham YO'Q — bo'sh papka «paket» deb
    #    uzatilmaydi.
    assert not X.fayl_bor(natija.result_dir, f"{BUNDLE_SUBDIR}/{rb.MANIFEST_FILE}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · BUZUQ CHIQISH (YARIM JSON) -> `FAILED_VALIDATION`, JIMGINA O'TISH YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_6_yarim_yozilgan_json_FAILED_VALIDATION_va_tahlil_BAJARILMAYDI(tmp_path):
    """`metadata.json` yarim yozilgan -> paketga ISHONIB BO'LMAYDI (chiqish kodi 1).

    ⚠️ ENG MUHIM QISMI: quvur DAVOM ETMAYDI. Grafga ham, tahlilga ham yetib bormaydi va
       ko'rik artefakti UMUMAN yozilmaydi — noto'g'ri paketdan chiqarilgan xulosa to'g'ri
       xulosaga O'XSHAB ketardi.
    ⚠️ Manifest YARIM baytlarni xeshlaydi, ya'ni xesh MOS keladi: nuqsonni faqat qat'iy JSON
       o'qish tuta oladi (fikstura izohiga qarang). Shu bois bu test ROSTDAN serializatsiya
       darvozasini o'lchaydi, xesh darvozasini emas.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_serializatsiya_yarim)
    natija = X.agent(tmp_path, scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)),
                     bundle_dir=paket).start()

    assert natija.state == st.FAILED_VALIDATION
    assert xato_kodlari(natija.result_dir) == [YOL_QAYDI, "BUNDLE_INVALID"]
    zanjir = holatlar(natija.result_dir)
    assert st.VALIDATION in zanjir
    assert st.GRAPH_BUILD not in zanjir and st.ANALYSIS not in zanjir
    assert not X.fayl_bor(natija.result_dir, AI_CANDIDATES_FILE), \
        "tahlil qilinmadi — ko'rik artefakti ham bo'lmasligi SHART"
    hisobot = X.matn(natija.result_dir, REPORT_FILE)
    assert "Tahlil QILINMADI" in hisobot
    # ⚠️ Yiqilgan yurish ham FAQAT-O'QISH ekanini e'lon qiladi: hech narsa o'zgartirilmadi.
    assert "`read_only`" in hisobot and f"`{ss.READ_ONLY}`" in hisobot


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · QISMLI METADATA: `UNKNOWN` SAQLANADI va `absent` DEB TALQIN QILINMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_7_oila_oqilmadi_va_oila_yoq_BIR_XIL_YAKUN_BERMAYDI(tmp_path):
    """`unreadable` (javob YO'Q) va `absent` (JAVOB) — IKKI XIL yakun.

    ⚠️ BU SSENARIYNING O'ZAGI: `ПланыСчетов` «o'qildi va BO'SH» bo'lsa yurish TUGAYDI
       (`COMPLETE`), «o'qiy olmadim» bo'lsa TO'XTAYDI va sababi OCHIQ yoziladi. Agar ikkisi
       bir xil yakun bergan bo'lsa, «qaralmadi» jimgina «yo'q» ga aylangan bo'lardi.
    ⚠️ CHEGARA OCHIQ AYTILADI: brief 7-ssenariy uchun «yurish DAVOM etadi» deb kutadi,
       amalda esa `overall=PARTIAL` validator chiqish kodi `2` ni beradi va quvur
       `FAILED_VALIDATION` da TO'XTAYDI (`pipeline` shartnomasi: yarim yurishdan chiqarilgan
       xulosa to'liq xulosaga o'xshab ketardi). Ya'ni `UNKNOWN` SAQLANADI — lekin qolgan 12
       oiladan chiqadigan foyda ham yo'qoladi. Bu ARXITEKTURA QARORI, testda XULQ sifatida
       qulflanadi va hisobotda nuqson sifatida qayd etiladi.
    """
    env = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))

    oqilmadi = X.agent(tmp_path / "a", scan=env, bundle_dir=X.paket_yoz(
        tmp_path / "b-oqilmadi", M.paket_oila_oqilmadi)).start()
    (tmp_path / "b").mkdir()
    yoq = X.agent(tmp_path / "b", scan=env, bundle_dir=X.paket_yoz(
        tmp_path / "b-yoq", M.paket_oila_yoq)).start()

    # ── Ikki yakun AJRALADI ──────────────────────────────────────────────────────────────
    assert yoq.state == st.COMPLETE, "«o'qildi va BO'SH» — TO'LIQ javob, yurish tugaydi"
    assert oqilmadi.state == st.FAILED_VALIDATION
    assert oqilmadi.state != yoq.state

    # ── Sabab ANIQ: paket BUTUN, yurish TO'LIQ EMAS (kod 2, kod 1 EMAS) ──────────────────
    assert xato_kodlari(oqilmadi.result_dir) == [YOL_QAYDI, "BUNDLE_RUN_INCOMPLETE"]
    izohlar = " ".join(yozuv(oqilmadi.result_dir)["notes"])
    assert "TO'LIQ EMAS" in izohlar and "chiqish kodi 2" in izohlar

    # ── `UNKNOWN` PAKETDA SAQLANADI va `absent` ga AYLANMAYDI ────────────────────────────
    oilalar = {o["name"]: o["state"] for o in json.loads(
        X.matn(oqilmadi.result_dir, f"{BUNDLE_SUBDIR}/{rb.RUN_STATUS_FILE}"))["families"]}
    assert oilalar["ПланыСчетов"] == "unreadable"
    assert oilalar["ПланыСчетов"] != "absent"
    oilalar_yoq = {o["name"]: o["state"] for o in json.loads(
        X.matn(yoq.result_dir, f"{BUNDLE_SUBDIR}/{rb.RUN_STATUS_FILE}"))["families"]}
    assert oilalar_yoq["ПланыСчетов"] == "absent"

    # ── `absent` yurishida QARALMAGAN konseptlar hisobotda QOLADI ────────────────────────
    assert korik(yoq.result_dir)["unknown_concepts"], \
        "«qaralmadi» ro'yxati jimgina tashlanmaydi"
    hisobot = X.matn(yoq.result_dir, REPORT_FILE)
    assert "`UNKNOWN` konseptlar (QARALMAGAN)" in hisobot
    assert "«Qaralmadi» va «yo'q» BIR XIL NARSA EMAS" in hisobot


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · HUQUQ YETMADI -> ANIQ XATO, `installs == []` BILAN ARALASHMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_8_huquq_yetmadi_bosh_royxat_bilan_ARALASHMAYDI(tmp_path):
    """Reestr o'qilmadi -> `unknown` + ANIQ xato yozuvi; `absent` dan AJRALADI.

    ⚠️ Xato kodi va yorlig'i MA'LUM: operator qaysi manbaga huquqi yo'qligini biladi. Va
       `scope` da XOM fayl yo'li BO'LMAYDI (u hisobotga chiqadi va redaksiya uni
       `[REDACTED]` qilib izohni ma'nosiz qilardi).
    """
    oqilmadi = X.muhit_huquq_yoq()
    yoq = X.muhit_1c_yoq()

    assert oqilmadi.presence_verdict == D.PRESENCE_UNKNOWN
    assert yoq.presence_verdict == D.PRESENCE_ABSENT
    assert oqilmadi.to_document() != yoq.to_document(), \
        "ikki holat BIR XIL hujjat bermasligi SHART"

    xatolar = oqilmadi.errors()
    assert [e["code"] for e in xatolar] == [D.CODE_REGISTRY_UNREADABLE]
    assert "huquq yetmadi" in xatolar[0]["detail"]
    assert "[REDACTED]" not in xatolar[0]["scope"], "yorliq niqoblanmasligi kerak"
    # ⚠️ Kod `agent_status.errors` shakliga (`[A-Z][A-Z0-9_]+`) KELTIRILADI — aks holda butun
    #    yurish yozuvi validatordan o'tmasdi (`ui._error_code` izohiga qarang).
    assert ss.ERROR_CODE_RE.fullmatch(U._error_code(xatolar[0]["code"]))


# ⚠️ TUZATILDI (xfail OLIB TASHLANDI): (1) `_manzilgacha` tuzatishi natija papkasini
#    qaytardi; (2) ma'no matni endi `states.failure_meaning(state, presence_verdict=...)` dan
#    olinadi va `unknown` hukmida «o'rnatilmagan» degan xulosa CHIQARILMAYDI — hisobot
#    `environment.json` bilan zid bo'lishi mumkin emas.
def test_8_huquq_yetmaganda_agent_ISBOTLANGAN_YOQLIK_deb_DAVO_QILMAYDI(tmp_path):
    """Huquq yetmasa hisobot «1C o'rnatilmagan, bu JAVOB» deb YOZMASLIGI kerak."""
    natija = X.agent(tmp_path, scan=X.muhit_huquq_yoq(), epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.result_dir is not None, "yurish yozuvi va muhit hujjati QOLISHI kerak"
    hisobot = X.matn(natija.result_dir, REPORT_FILE)
    assert "Bu JAVOB, taxmin emas" not in hisobot, \
        "o'qilmagan manba ustidan «isbotlangan yo'qlik» DA'VO qilinmaydi"
    assert D.CODE_REGISTRY_UNREADABLE.upper() in xato_kodlari(natija.result_dir)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · SIR OQISHI -> RAD, va HISOBOTDA SIR KO'RINMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_9_paketda_ulanish_satri_bolsa_natija_RAD_etiladi_va_sir_KORINMAYDI(tmp_path):
    """`errors.json` ichida 1C ulanish satri -> SIRLI paket RAD, MINIMAL sirsiz paket qoladi.

    ⚠️ HAQIQIY OQIM SHUNDAY: yig'uvchi 1C ning xato tavsifini `errors.json` ga qo'yadi, SUBD
       xatosi esa ulanish satrini (server nomi, foydalanuvchi, parol) O'Z ICHIGA OLADI. Ya'ni
       bu operator xatosi emas, quvurning TABIIY natijasi — darvoza shu bois shu yerda.
    ⚠️ ENG MUHIMI: sir birorta YOZILGAN faylga tushmaydi. `bundle/` (sirning tashuvchisi)
       natija paketiga UMUMAN qo'shilmaydi, hisobot esa yurish yozuvidan qayta quriladi.
    ⚠️⚠️ TUZATILGAN NUQSON (brief §2): avval bu yerda `result_dir is None` kutilardi, ya'ni
         sir topilsa operator «hech narsa qolmadi» holatida qolardi — sir ANIQLANGANI
         faktining ham hujjatli izi yo'q edi. Endi MINIMAL, SIRSIZ paket yoziladi va u
         validatordan o'tadi. ⚠️ TO'LIQ ISBOT — `test_agent_e2e_watch_folder.py` ning G
         ssenariysida (beshta ildiz artefakti, yozuvdagi kod, `errors.json` bilan tenglik);
         bu yerda faqat SHU qatlamning da'vosi qulflanadi, ikkinchi nusxa yozilmaydi.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sir_oqqan)
    natija = X.agent(tmp_path, scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)),
                     bundle_dir=paket).start()

    assert natija.is_failure, "jimgina muvaffaqiyat YO'Q"
    assert natija.state == st.FAILED_REPORT
    assert natija.code == U.CODE_SIR_USHLANDI
    assert natija.result_dir is not None, "operator «hech narsa qolmadi» holatida QOLMAYDI"
    # ⚠️ AYNAN BITTA natija papkasi: yarim yozilgan ikkinchi papka QOLMAYDI.
    assert [d for d in os.listdir(tmp_path)
            if d.startswith(RESULT_DIR_PREFIX)] == [pathlib.Path(natija.result_dir).name]
    # ⚠️ SIRNING O'ZI YOZILMAYDI: `bundle/` yo'q va birorta baytda sir qoldiq qolmaydi.
    yozilganlar = X.papka_baytlari(natija.result_dir)
    assert not any(n.startswith(f"{BUNDLE_SUBDIR}/") for n in yozilganlar), \
        "sirning tashuvchisi (Phase 4 paketi) natija paketiga QO'SHILMAYDI"
    for qiymat in M.SIR_QIYMATLAR:
        assert all(qiymat.encode("utf-8") not in b for b in yozilganlar.values()), \
            f"sir YOZILGAN baytlarda qoldi: {qiymat}"

    # ── Sir EKRANGA ham, muammolar ro'yxatiga ham chiqmaydi ──────────────────────────────
    hamma_matn = natija.detail + " " + " ".join(natija.problems)
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat not in hamma_matn, f"sir chiqishda qoldi: {qiymat}"
    assert "[REDACTED]" in hamma_matn, "qiymat YASHIRILMADI, ALMASHTIRILDI"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · JUDA KATTA METADATA (2000+ OBYEKT) -> ISHLAYDI, DETERMINIZM SAQLANADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_10_ulkan_metadata_ishlaydi_va_determinizm_SAQLANADI(tmp_path):
    """2000 obyektli paket -> `COMPLETE`, va IKKI yurish AYNAN bir xil bayt beradi.

    ⚠️ DETERMINIZM NEGA MUHIM: natija paketi `sha256` manifestiga ega va operator ikki
       yurishni solishtirib «nima o'zgardi» degan savolga javob olishi kerak. Soat, papka
       yo'li yoki lug'at tartibi natijaga sizib kirsa, solishtirish MA'NOSIZ bo'lardi.
    ⚠️ IKKI natija papkasi BOSHQA joyda: yo'l artefaktlarga TUSHMASLIGI shu bilan
       isbotlanadi.
    ⚠️ BU TEST QIMMAT (~30 s har yurish): 2000 obyekt graf va evristikadan o'tadi. Hajm
       briefda talab qilingan, shu bois qisqartirilmaydi.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_ulkan)
    inventar = json.loads(pathlib.Path(paket, rb.METADATA_FILE).read_text(encoding="utf-8"))
    assert len(inventar["objects"]) >= 2000

    env = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))
    birinchi_papka = tmp_path / "natija-1"
    birinchi_papka.mkdir()
    ikkinchi_papka = tmp_path / "natija-2"
    ikkinchi_papka.mkdir()

    birinchi = X.agent(birinchi_papka, scan=env, bundle_dir=paket).start()
    ikkinchi = X.agent(ikkinchi_papka, scan=env, bundle_dir=paket).start()

    assert birinchi.state == st.COMPLETE and ikkinchi.state == st.COMPLETE
    a = X.papka_baytlari(birinchi.result_dir)
    b = X.papka_baytlari(ikkinchi.result_dir)
    assert sorted(a) == sorted(b)
    farq = [n for n in a if a[n] != b.get(n)]
    assert farq == [], f"bir xil kirish bir xil bayt bermadi: {farq}"
    assert AGENT_MANIFEST_FILE in a and ENVIRONMENT_FILE in a


# ══════════════════════════════════════════════════════════════════════════════════════════
# 11 · TUSHUNARSIZ OBYEKT NOMLARI -> STRUKTURA BO'YICHA NOMZOD TOPILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_11_tushunarsiz_nomlarda_nomzod_FAQAT_STRUKTURADAN_chiqadi(tmp_path):
    """`X17`/`X23`/`ABCD`/`R41` — nomdan hech narsa bilinmaydi, struktura QOLADI.

    ⚠️ Tushunarsiz nom «yig'uvchi qaramadi» degani EMAS: sinonim ROSTDAN bo'sh va hamma
       bo'lim `ok`. Shu bois obyektni jimgina tashlab ketish — MA'LUMOT YO'QOTISH.
    ⚠️ ISBOTLANMAYDI: topilgan nomzodning TO'G'RILIGI. `String(13)` shtrix-kod BO'LISHI SHART
       emas; shu bois test BALLNI emas, DALIL TURINI qulflaydi.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan",
                        lambda p: M.yoz(p, M.baytlar(metadata=S.config("G"))))
    natija = X.agent(tmp_path, scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)),
                     bundle_dir=paket).start()

    assert natija.state == st.COMPLETE, "g'alati nom paketni RAD ETTIRMAYDI"
    review = korik(natija.result_dir)
    assert review["candidates"], "strukturadan KAMIDA bitta nomzod chiqishi kerak"

    turlar = dalil_turlari(review)
    assert turlar, "dalilsiz nomzod bo'lmaydi"
    assert not (turlar & LEKSIK_DALILLAR), \
        f"nomlar ma'nosiz — leksik dalil CHIQMASLIGI kerak: {sorted(turlar & LEKSIK_DALILLAR)}"
    assert not (turlar & TAQIQLANGAN_DALILLAR)
    assert turlar <= set(schema.WEAK_EVIDENCE_KINDS), \
        "bu kanalda KUCHLI dalil yo'q — hammasi kuchsiz bo'lishi SHART"

    # ⚠️ Nomzodlar GRAFDAGI obyektlarga tushadi, o'ylab chiqarilmaydi.
    obyektlar = {c["candidate_object"] for c in review["candidates"]}
    assert obyektlar <= {o["full_name"] for o in S.config("G")["objects"]}
    assert "Catalog.X17" in obyektlar

    # ⚠️ Eng yuqori avtomat daraja — `CANDIDATE`; `VERIFIED` so'zi hisobotda UMUMAN yo'q.
    assert {c["status"] for c in review["candidates"]} <= {ai.STATUS_CANDIDATE,
                                                          ai.STATUS_AMBIGUOUS,
                                                          ai.STATUS_REJECTED}
    assert not rb.VERIFIED_WORD_RE.findall(X.matn(natija.result_dir, REPORT_FILE))


# ══════════════════════════════════════════════════════════════════════════════════════════
# 12 · NOANIQ XARITALAR -> `AMBIGUOUS` va IKKALA NOMZOD KO'RSATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_12_ikki_teng_nomzod_AMBIGUOUS_va_IKKALASI_KORSATILADI(tmp_path):
    """Ikki teng kuchli mahsulot katalogi -> tanlash EMAS, IKKILANISHNI AYTISH.

    ⚠️ JIMGINA BITTASINI TANLASH — eng qimmat xato: operator xaritani tasdiqlangan deb
       o'qiydi va ko'chirish noto'g'ri katalogdan ketadi. Shu bois IKKALA nomzod ham
       ko'rinishi, ikkisi ham `AMBIGUOUS` bo'lishi va ikkilanish SABABI yozilishi SHART.
    ⚠️ ISBOTLANMAYDI: qaysi biri «haqiqiy» ekani. Javob zonddan yoki operatordan keladi —
       hujjatdagi ma'lumot bilan bu savolga javob BERILMAYDI.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan",
                        lambda p: M.yoz(p, M.baytlar(metadata=S.config("J"))))
    natija = X.agent(tmp_path, scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)),
                     bundle_dir=paket).start()

    assert natija.state == st.COMPLETE
    review = korik(natija.result_dir)
    mahsulot = nomzodlar(review, "product")
    assert len(mahsulot) >= 2, "ikki teng nomzod IKKI qator bo'lib ko'rinishi kerak"
    assert {c["status"] for c in mahsulot} == {ai.STATUS_AMBIGUOUS}, \
        "teng ballda bittasi tanlab olinmaydi"

    OSN = "Справочник.ТоварыОсновные"
    DOP = "Справочник.ТоварыДополнительные"
    assert {c["candidate_object"] for c in mahsulot} == {OSN, DOP}
    for qator in mahsulot:
        sabab = " ".join(qator["ambiguity"])
        assert OSN in sabab and DOP in sabab, "ikkilanish IKKALA nomzodni NOMLAYDI"
        assert "avtomat tanlov QILINMADI" in sabab
        assert qator["required_confirmation"], "tasdiq TALAB qilinadi"

    hisobot = X.matn(natija.result_dir, REPORT_FILE)
    assert OSN in hisobot and DOP in hisobot, "operator ikkalasini ham KO'RISHI kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 13 · TAQIQLANGAN MUTATSIYA URINISHI -> RAD (`epf_audit` DARVOZASI)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_13_yiguvchi_manbasida_mutatsiya_urinishi_RAD_etiladi(tmp_path):
    """`Записать`/`Провести`/`Удалить` -> `epf_audit` darvozasi QIZIL bo'ladi.

    ⚠️ BU NIMANI ISBOTLAYDI: manba matnida taqiqlangan chaqiruv YO'Q.
    ⚠️ BU NIMANI ISBOTLAMAYDI: modulning kompilyatsiya bo'lishini yoki 1C da to'g'ri
       ishlashini — bu mashinada 1C platformasi YO'Q.
    ⚠️ Ikki tomon tekshiriladi: (a) mutatsiya qo'shilgan SINTETIK manba RAD etiladi,
       (b) REPODAGI HAQIQIY yig'uvchi manbasi darvozadan O'TADI. Faqat (a) bo'lsa, darvoza
       ishlayotganini bilardik, lekin haqiqiy manba holati noma'lum qolardi; faqat (b)
       bo'lsa, darvoza butunlay ko'r bo'lib qolgan bo'lsa ham test yashil bo'lardi.
    """
    mutatsiya = "\n".join([
        "// SINTETIK manba — mutatsiya urinishi (bu REAL yig'uvchi EMAS)",
        "Процедура SintetikYozish()",
        "    Объект.Записать();",
        "    Документ.Провести();",
        "    Элемент.Удалить();",
        "    УстановитьПривилегированныйРежим(Истина);",
        "КонецПроцедуры",
    ])
    topilmalar = {f.code for f in epf_audit.audit_source(mutatsiya)}
    assert {"WRITE_OBJECT", "POST_DOCUMENT", "DELETE", "PRIVILEGED_MODE"} <= topilmalar

    # ⚠️ Har topilma SATR RAQAMI va SABABI bilan keladi: «qizil» yetmaydi, operator/ishlab
    #    chiquvchi qayerda va nega ekanini bilishi kerak.
    for f in epf_audit.audit_source(mutatsiya):
        if f.code in ("WRITE_OBJECT", "POST_DOCUMENT", "DELETE", "PRIVILEGED_MODE"):
            assert f.line_no > 0 and f.line.strip() and f.why.strip()

    assert BSL_SOURCE.is_file(), f"yig'uvchi manbasi topilmadi: {BSL_SOURCE.name}"
    haqiqiy = epf_audit.audit_file(BSL_SOURCE)
    assert haqiqiy == [], f"repodagi yig'uvchi manbasi darvozadan o'tmadi: {haqiqiy}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 14 · O'ZBOSHIMCHA ZOND URINISHI -> RAD (`probe.validate_probe`)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_14_ozboshimcha_zond_RAD_etiladi_va_tasdiqsiz_bajarilmaydi(tmp_path):
    """Allowlistdan tashqari zond ham, tasdiqsiz zond ham BAJARILMAYDI.

    ⚠️ UCH DARVOZA ALOHIDA tekshiriladi:
       (a) KATALOG — `probe_type` ro'yxatda bo'lmasa RAD (o'zboshimcha so'rov yo'q);
       (b) GRAF — nishon O'YLAB CHIQARILGAN bo'lsa RAD (mavjud bo'lmagan obyekt so'ralmaydi);
       (c) TASDIQ — operator tasdig'i paketning rejimiga MOS kelmasa `FAILED_SAFETY`.
    ⚠️ Katalogdagi BIRORTA zond yozuvchi EMAS: yozuvchi zond bu qatlamning butun ma'nosini
       yo'qotardi.
    """
    graf = build_graph(S.config("A"))
    nishon = "Справочник.Товары"

    # ── (a) Katalogdan tashqari tur ──────────────────────────────────────────────────────
    with pytest.raises(probe.ProbeError, match="noma'lum zond turi"):
        probe.validate_probe(probe.ProbeRequest(
            probe_type="execute_query", target_object=nishon,
            reason="o'zboshimcha so'rov bajarish urinishi",
            expected_evidence=("cardinality",)), graph=graf)

    # ── (b) O'ylab chiqarilgan nishon ────────────────────────────────────────────────────
    with pytest.raises(probe.ProbeError, match="grafda yo'q"):
        probe.validate_probe(probe.ProbeRequest(
            probe_type="row_count", target_object="Справочник.UmumanYoqObyekt",
            reason="mavjud bo'lmagan obyektni so'rash urinishi",
            expected_evidence=("cardinality",)), graph=graf)

    # ── Katalog o'zi: FAQAT O'QISH ───────────────────────────────────────────────────────
    assert len(probe.PROBE_CATALOG) == 11, "zond allowlisti 11 ta — kengaytirish KO'RIKDAN"
    assert all(y["read_only"] for y in probe.PROBE_CATALOG.values())
    assert "execute_query" not in probe.PROBE_CATALOG

    # ── (c) Tasdiq paketga MOS kelmasa — xavfsizlik ziddiyati ────────────────────────────
    paket = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    kirish = ss.new_run("run-ssenariy-14", now=X.NOW_ISO)
    for holat in (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                  st.METADATA_DISCOVERY):
        kirish = kirish.advance(holat, now=X.NOW_ISO)
    kirish = kirish.with_mode(rb.MODE_APPROVED_PROBES).with_probe(ss.ProbeRecord(
        no="1", probe_type="object_attributes", target_object=nishon,
        reason="paketda natijasi YO'Q zond",
        file=f"{BUNDLE_SUBDIR}/probes/01_object_attributes.json", status="APPROVED"))

    natija = P.run_pipeline(paket, status=kirish, now=X.NOW_ISO)
    assert natija.state == st.FAILED_SAFETY
    assert [e.code for e in natija.status.errors] == ["PROBE_MODE_MISMATCH"]
    assert st.REVALIDATE not in [t.to_state for t in natija.status.transitions]
    assert natija.report_text is None, "xavfsizlik to'xtatgan yurish hisobot YOZMAYDI"

    # ⚠️ TAKLIF TASDIQ EMAS: analitik tavsiyasi o'zi zondni bajarmaydi.
    assert "PROPOSED" not in P.APPROVED_PROBE_STATUSES


# ══════════════════════════════════════════════════════════════════════════════════════════
# 15 · AI `VERIFIED` BERMOQCHI BO'LSA -> RAD (`ai.validate_analysis`)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_15_analitik_VERIFIED_bermoqchi_bolsa_yurish_RAD_etiladi(tmp_path):
    """`VERIFIED` -> `FAILED_ANALYSIS`. Ko'rik artefakti UMUMAN yozilmaydi.

    ⚠️ Yarim qabul qilish YO'Q: taqiqlangan darajani «`CANDIDATE` ga tushirib» qabul qilish
       modelning da'vosini JIMGINA yumshatardi va operator nima bo'lganini BILMASDI.
    ⚠️ `HUMAN_CONFIRMED` ham bu kanaldan kelmaydi: u faqat OPERATORNING alohida tasdiq
       hujjatidan tug'iladi.
    """
    paket = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    natija = X.agent(tmp_path, scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)),
                     bundle_dir=paket, analyzer=VerifiedBermoqchi()).start()

    assert natija.state == st.FAILED_ANALYSIS
    kodlar = xato_kodlari(natija.result_dir)
    assert kodlar == [YOL_QAYDI, "ANALYSIS_FAILED"]
    # ⚠️ TAHLIL xatosi — ro'yxatdagi SO'NGGISI: birinchisi yo'l qaydi (`YOL_QAYDI`), u
    #    yurishning BOSHIDA yoziladi. Indeksni `0` deb qotirib qo'yish testni yozuvlar
    #    TARTIBIGA bog'lab, mazmunni o'lchamay qo'yardi.
    tafsilot = yozuv(natija.result_dir)["errors"][-1]["detail"]
    assert ai.FORBIDDEN_STATUS in tafsilot, "rad etish SABABI aynan `VERIFIED` bo'lishi kerak"
    assert "VerifiedBermoqchi" in tafsilot, "qaysi analitik ekani YOZILADI"

    assert not X.fayl_bor(natija.result_dir, AI_CANDIDATES_FILE), \
        "rad etilgan tahlilning artefakti YOZILMAYDI"
    zanjir = holatlar(natija.result_dir)
    assert st.ANALYSIS in zanjir and st.REPORT not in zanjir

    # ⚠️ Taqiqlangan SO'Z hisobot matnida UMUMAN uchramaydi (`UNVERIFIED` — boshqa so'z,
    #    shu bois so'z chegarasi bilan izlanadi).
    hisobot = X.matn(natija.result_dir, REPORT_FILE)
    assert not rb.VERIFIED_WORD_RE.findall(hisobot)
    assert "UNVERIFIED" in hisobot, "versiya belgisi esa JOYIDA qoladi"
    assert ai.STATUS_HUMAN_CONFIRMED in hisobot and "OPERATORNING" in hisobot


# ══════════════════════════════════════════════════════════════════════════════════════════
# 16 · ANALITIK MAVJUD EMAS -> DETERMINISTIK REJIM ISHLAYDI (OFFLINE-FIRST)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_16_analitik_berilmasa_deterministik_rejim_ISHLAYDI(tmp_path):
    """`analyzer=None` -> lokal evristika; BO'SH analitik -> hammasi `UNKNOWN`, lekin ISHLAYDI.

    ⚠️ OFFLINE-FIRST REJIM, ZAXIRA YO'L EMAS: tarmoq chaqiruvi yo'q, cloud AI yo'q va
       do'konning ma'lumoti hech qayerga yuborilmaydi. «Analitik mavjud emas» holati
       quvurni TO'XTATMAYDI.
    ⚠️ BO'SH TAHLIL ham `COMPLETE` beradi — lekin hamma konsept `unknown_concepts` da
       QOLADI. «Qaralmadi» ni jimgina «yo'q» deb o'qitmaslik aynan shu ro'yxat bilan
       ta'minlanadi.
    """
    env = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))
    (tmp_path / "n1").mkdir()
    (tmp_path / "n2").mkdir()

    standart = X.agent(tmp_path / "n1", scan=env, bundle_dir=X.paket_yoz(
        tmp_path / "b1", M.paket_sog_lom), analyzer=None).start()
    bosh = X.agent(tmp_path / "n2", scan=env, bundle_dir=X.paket_yoz(
        tmp_path / "b2", M.paket_sog_lom), analyzer=NullAnalyzer()).start()

    assert standart.state == st.COMPLETE and bosh.state == st.COMPLETE

    rev = korik(standart.result_dir)
    assert rev["analyzer"]["name"] == "HeuristicAnalyzer"
    assert rev["analyzer"]["version"] == P.ANALYZER_VERSION_UNDECLARED, \
        "e'lon qilinmagan versiya O'YLAB CHIQARILMAYDI"
    assert int(rev["counts"]["candidates"]) > 0
    izohlar = " ".join(yozuv(standart.result_dir)["notes"])
    assert "DETERMINISTIK" in izohlar and "zaxira yo'l emas" in izohlar

    rev_bosh = korik(bosh.result_dir)
    assert rev_bosh["candidates"] == [], "bo'sh analitik nomzod BERMAYDI"
    assert int(rev_bosh["counts"]["unknown_concepts"]) > 0, \
        "qaralmagan konseptlar JIMGINA tashlanmaydi"
    assert not rb.VERIFIED_WORD_RE.findall(X.matn(bosh.result_dir, REPORT_FILE))


def test_16b_agent_paketida_TARMOQ_importi_YOQ():
    """STATIK darvoza: offline-first — TALAB, da'vo emas.

    ⚠️ «Ishlatmaymiz» degan izoh keyingi o'zgarishda jimgina yo'qoladi; IMPORTNING O'ZI
       bo'lmasligi esa darvoza.
    ⚠️ `subprocess` ro'yxatda YO'Q va bu ATAYLAB: `collector_bridge` 1C ni paketli rejimda
       ishga tushirishi KERAK (`run_1c_batch` — modulning YAGONA `subprocess` joyi). Lekin
       u faqat SHU modulda bo'lishi shart, boshqa joyda emas.
    """
    taqiq = frozenset({"socket", "requests", "urllib", "urllib3", "http", "httpx",
                       "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio"})
    for nom, kod in agent_manbalari():
        for tugun in ast.walk(ast.parse(kod)):
            if isinstance(tugun, ast.Import):
                nomlar = {a.name.split(".")[0] for a in tugun.names}
            elif isinstance(tugun, ast.ImportFrom):
                nomlar = {(tugun.module or "").split(".")[0]}
            else:
                continue
            assert not (nomlar & taqiq), f"{nom}: tarmoq importi {sorted(nomlar & taqiq)}"

    subprocessli = [nom for nom, kod in agent_manbalari()
                    if re.search(r"^import subprocess", kod, re.M)]
    assert subprocessli == ["collector_bridge.py"], \
        "jarayon ishga tushirish YAGONA modulda qoladi"
