# -*- coding: utf-8 -*-
"""A..K — UCHIGA-UCH SINTETIK ISBOT: OPERATOR OQIMI darajasidagi o'n bir ssenariy.

⚠️⚠️ BU REAL 1C ISBOTI EMAS. Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI,
     `.epf` BAJARILMAYDI, HAQIQIY Windows reestri O'QILMAYDI va TARMOQ ishlatilmaydi. Bu
     mashinada 1C:Enterprise UMUMAN O'RNATILMAGAN (`C:\\Program Files\\1cv8` yo'q,
     `HKLM\\SOFTWARE\\1C\\1Cv8` yo'q, `1cv8.exe`/`ibcmd.exe` PATH da yo'q,
     `V83.COMConnector` ro'yxatda yo'q, `pywin32` yo'q). Kirish — SINTETIK reestr, SINTETIK
     `ibases.v8i` va SINTETIK Phase 4 runtime paketlari. Shu bois bu fayl javob beradigan
     YAGONA savol: «muhit va kuzatilgan papka shunday ko'rinsa, AGENT TO'G'RI hukm
     chiqaradimi va OPERATOR qo'lida YAROQLI paket qoladimi?». Integratsiya yo'llarining
     (`batch_execute`, `watch_folder`) 1C bilan ishlaydigan qismi `RUNTIME-UNKNOWN` bo'lib
     QOLADI.

NEGA BU FAYL `test_agent_scenarios.py` DAN ALOHIDA (va nega u fayl TAKRORLANMAYDI):
    `test_agent_scenarios.py` — brief sanagan 16 holatning QAROR mantiqi (ko'pi qatlam
    darajasida: muhit skaneri, ko'prik, darvozalar). Bu fayl esa AYNI quvurni OPERATOR
    OQIMI darajasida o'lchaydi (`integrations/1c/AGENT_OPERATOR_FLOW.md`): har ssenariy
    `UiModel.start()` ni OXIRIGACHA yuritadi va keyin operator qo'lida NIMA QOLGANINI
    tekshiradi — natija papkasi `result_package.validate_result_package` dan O'TADIMI,
    ildizda BESHTA artefakt bormi, ekrandagi qatorlar (yo'l, kutish) yurish yozuvi bilan
    ZID emasmi, va hisobotda da'vo qilinmasligi kerak bo'lgan narsa YO'Qmi.

ISBOTLANADIGAN O'ZAK INVARIANTLAR:
    1. `UNKNOWN` HECH QACHON `NOT_FOUND` ga AYLANMAYDI (B, G, K).
    2. YIQILGAN YURISH HAM YAROQLI PAKET QOLDIRADI — beshta ildiz artefakti va validatordan
       o'tgan papka (A, B, C, E, F, G, I, J, K). ⚠️ ISTISNO YO'Q: SIR topilgan yurishda ham
       (G) paket qoladi, lekin u MINIMAL va SIRSIZ — `bundle/` va nomzodlar fayli UNGA
       QO'SHILMAYDI, sir topilgani fakti esa `errors.json` da ANIQ kod bilan turadi.
    3. JIMGINA DAVOM ETISH YO'Q: validator kodi `2` (yurish to'liq emas) `1` (paketga
       ishonib bo'lmaydi) dan AJRALADI va IKKISI ham quvurni TO'XTATADI (E, F).
    4. `VERIFIED` hech qachon chiqmaydi, `HUMAN_CONFIRMED` esa AI kanalidan kelmaydi (I, J).
    5. CHEKSIZ KUTISH YO'Q (C).

USLUB QARORI: har ssenariy KUTILGAN XULQNI qulflaydi, MUAYYAN MATNNI emas. Matn tekshirilsa
— faqat MANBASI bilan solishtirilib (`states.failure_meaning`, `report.NO_AUTOMATION_LINE`,
`collector_bridge.WATCH_FOLDER_OPERATOR_STEPS`), ya'ni test ikkinchi haqiqat yozmaydi.

⚠️ HAQIQIY VAQT KUTILMAYDI: soat va `sleeper` KIRISHDAN keladi
   (`agent_scenario_mock.kutuvchi_agent`), demak to'plam mashinaning tezligiga bog'liq emas.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

import pytest

from app.services.discovery_1c import ai, epf_audit
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.analyst.heuristics import HeuristicAnalyzer
from app.services.discovery_agent import (AGENT_MANIFEST_FILE, AGENT_STATUS_FILE,
                                          AI_CANDIDATES_FILE, BUNDLE_SUBDIR, ENVIRONMENT_FILE,
                                          ERRORS_FILE, ERRORS_VERSION, REPORT_FILE,
                                          RESULT_DIR_PREFIX, ROUTE_BATCH_EXECUTE,
                                          ROUTE_WATCH_FOLDER)
from app.services.discovery_agent import collector_bridge as bridge
from app.services.discovery_agent import detector as D
from app.services.discovery_agent import pipeline as P
from app.services.discovery_agent import report as reporter
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as stat
from app.services.discovery_agent import ui as agent_ui
from tests import agent_scenario_mock as X
from tests import discovery_1c_metadata_synth as S
from tests import discovery_1c_runtime_mock as M
# ⚠️ ZOND PAKETINI QURADIGAN FIKSTURA QAYTA ISHLATILADI, nusxa KO'CHIRILMAYDI: zond bor
#    paketning shakli Phase 4 shartnomasi (`run_status.probes` jurnali + `probes/NN_<tur>.json`
#    + manifest + `artifacts` da sanash) va uni bu yerda qaytadan yozish IKKI HAQIQAT yasardi
#    — K ssenariysi esa aynan shartnomaning O'ZINI o'lchaydi. Loyihada bu naqsh allaqachon
#    bor (`agent_scenario_mock` `test_agent_detector` dan fikstura oladi).
from tests import test_discovery_1c_runtime_bundle as RB

#: Yig'uvchi manbasi — K ssenariysidagi MAVJUD darvozaning haqiqiy nishoni.
BSL_SOURCE = (pathlib.Path(__file__).resolve().parents[3]
              / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl")

#: ⚠️ `watch_folder` yurishida ATAYLAB yoziladigan xato — «yiqilish» EMAS: u paketli yo'l
#: NEGA UMUMAN urinilmaganini qayd etadi (brief §4). Ro'yxatlarni TO'LIQ solishtirgan
#: ssenariylar shu kodni ham sanaydi.
YOL_QAYDI = bridge.CODE_BATCH_NOT_ATTEMPTED

#: Operator oqimi hujjati (`AGENT_OPERATOR_FLOW.md` §3.5) sanab o'tgan progress zanjiri —
#: TO'LIQ muvaffaqiyatli yurish uchun. ⚠️ Zond YO'Q: `METADATA_ONLY` — DEFAULT rejim.
TOLIQ_PROGRESS: tuple[str, ...] = (
    st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY,
    st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS, st.REPORT, st.COMPLETE,
)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YORDAMCHILAR — HAMMASI DISKDAN O'QIYDI, HECH NARSA TAXMIN QILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def yozuv(papka) -> dict:
    return json.loads(X.matn(papka, AGENT_STATUS_FILE))


def holatlar(papka) -> list[str]:
    return [t["to"] for t in yozuv(papka)["transitions"]]


def xato_kodlari(papka) -> list[str]:
    return [e["code"] for e in yozuv(papka)["errors"]]


def ildiz_fayllar(papka) -> set[str]:
    """Natija papkasining ILDIZIDAGI fayl nomlari (`bundle/` ichi SANALMAYDI)."""
    return {n for n in X.papka_baytlari(papka) if "/" not in n}


def paket_fayllar(papka) -> set[str]:
    """`bundle/` ichidagi fayllar — `bundle/` prefiksi OLIB TASHLANGAN holda."""
    pref = f"{BUNDLE_SUBDIR}/"
    return {n[len(pref):] for n in X.papka_baytlari(papka) if n.startswith(pref)}


def yaroqli_paket(papka) -> None:
    """⚠️ BU ENG MUHIM YORDAMCHI: natija papkasi DISKDAN tekshiriladi.

    `validate_result_package` nuqson bo'lsa ISTISNO beradi, demak bu chaqiruv «papka bor»
    dan KO'RA KO'PROQ narsani qulflaydi: manifest xeshlari mazmunga mos, ildizdagi
    `errors.json` AGENT sxemasida va `agent_status.errors` ga TENG, `bundle/` Phase 4
    tekshiruvlaridan o'tgan (yoki yiqilgan yurishda sir darvozalari ochilmagan), sanoqlar
    MATN, holat bilan fayl ro'yxati ZID emas.
    ⚠️ Ikki qatlam ataylab: `UiModel._paket` ning O'ZI ham `check_result_package` ni
       chaqiradi, lekin u tekshiruvni O'TKAZIB YUBORADIGAN qilib tahrirlansa, bu chaqiruv
       baribir tutadi.
    """
    rp.validate_result_package(papka)


def besh_ildiz_artefakti(papka, *, tahlil_bor: bool = False) -> None:
    """Brief §2: yiqilish paketida BESHTA ildiz artefakti BO'LISHI SHART.

    ⚠️ RO'YXAT KODDAN OLINADI (`result_package.ALWAYS_FILES`), qo'lda sanalmaydi: ikkinchi
       ro'yxat bir kun birinchisidan ajralib ketardi.
    ⚠️ `errors.json` SHU BESHTANING ICHIDA va u ildizda turadi — `bundle/errors.json` BOSHQA
       hujjat (pastda `test_A2_...` buni alohida qulflaydi).
    """
    bor = ildiz_fayllar(papka)
    assert set(rp.ALWAYS_FILES) <= bor, f"ildizda majburiy artefakt yetishmaydi: {bor}"
    assert len(rp.ALWAYS_FILES) == 5, "brief BESH ildiz artefaktini talab qiladi"
    assert ERRORS_FILE in rp.ALWAYS_FILES, "`errors.json` ildizda MAJBURIY"
    if tahlil_bor:
        assert AI_CANDIDATES_FILE in bor, "tahlil bo'lgan yurishda nomzodlar fayli SHART"
    else:
        # ⚠️ BO'SH ARTEFAKT YOZISH TAQIQ: bo'sh nomzodlar fayli «tahlil bo'ldi, nomzod
        #    chiqmadi» degan BOSHQA ma'noni berardi.
        assert AI_CANDIDATES_FILE not in bor, \
            "tahlilga yetmagan yurish nomzodlar faylini YOZMAYDI"


def ildiz_errors(papka) -> dict:
    return json.loads(X.matn(papka, ERRORS_FILE))


def hisobot(papka) -> str:
    return X.matn(papka, REPORT_FILE)


def papka_ichidagi_hamma_bayt(papka) -> bytes:
    """Papka ostidagi HAMMA faylning baytlari bitta bloda — sir qidirish uchun."""
    return b"\n".join(X.papka_baytlari(papka).values())


def faqat_RAD_sababida(papka, daraja: str) -> None:
    """`daraja` nomi paketda FAQAT IKKI RUXSAT ETILGAN joyda uchraydi, boshqa joyda YO'Q.

    Ruxsat etilgan joylar: (1) RAD ETISH SABABI, (2) hisobotning boshidagi MAJBURIY
    ogohlantirishlar (`report.HEADER_WARNINGS` — ular darajaning MAVJUD EMASLIGINI aytadi).

    ⚠️⚠️ NEGA «UMUMAN YO'Q» TALABI XATO BO'LARDI: rad etilgan darajani ATAMASDAN rad etishni
         tushuntirib bo'lmaydi («nimadir rad etildi» degan xato hech narsa aytmasdi), va
         hisobot ham «bu daraja bu kanalda YO'Q» deb AYNAN uni atab ogohlantiradi. Ya'ni
         so'zning bu ikki joyda bo'lishi TO'G'RI. TAQIQLANADIGAN narsa — uning QABUL
         QILINGAN HUKM (status) bo'lib chiqishi.
    ⚠️ USUL: ruxsat etilgan matnlar OLIB TASHLANADI va qolganida nom QIDIRILADI. Shunda
       «ruxsat etilgan joyda bor» bilan «boshqa joyda bor» ARALASHIB ketmaydi. Ruxsat
       etilgan matnlar KODDAN olinadi, qo'lda ko'chirilmaydi — ya'ni matn tahrirlansa test
       o'z invariantini o'lchashda DAVOM ETADI.
    ⚠️⚠️ SO'Z CHEGARASI SHART, oddiy `in` EMAS: `AGENT_VERSION` = `0.1.0-UNVERIFIED` va u
         HALOL versiya satri — ichida `VERIFIED` bo'lgani uchun uni «tasdiq da'vosi» deb
         o'qish yolg'on nuqson bergan bo'lardi. Naqsh yadroning qoidasi bilan AYNI
         (`runtime_bundle.VERIFIED_WORD_RE` ham aynan shu chegarani ishlatadi).
    """
    naqsh = re.compile(rf"(?<![0-9A-Za-z_]){re.escape(daraja)}(?![0-9A-Za-z_])")
    sabablar = [e["detail"] for e in yozuv(papka)["errors"] if naqsh.search(e["detail"])]
    assert sabablar, f"rad etish sababi rad etilgan darajani ({daraja}) NOMLASHI SHART"
    for s in sabablar:
        assert "RAD" in s, f"nom sababda bo'lsa, sabab RAD ETISHNI aytishi kerak: {s!r}"
    ruxsat = list(sabablar) + list(reporter.HEADER_WARNINGS)
    for nom, raw in X.papka_baytlari(papka).items():
        qoldiq = raw.decode("utf-8", "replace")
        for matn in ruxsat:
            qoldiq = qoldiq.replace(matn, "")
        assert not naqsh.search(qoldiq), \
            f"`{nom}`: rad etilgan daraja ({daraja}) RUXSAT ETILGAN JOYLARDAN TASHQARIDA qoldi"


def natija_papkalari(parent) -> list[str]:
    if not os.path.isdir(parent):
        return []
    return sorted(d for d in os.listdir(parent) if d.startswith(RESULT_DIR_PREFIX))


class StatusAlmashtiruvchi:
    """Deterministik evristikaning javobini olib, FAQAT `status` ni almashtiradigan analitik.

    ⚠️ NEGA SHU USUL: gipotezani qo'lda yozsam, `ai.validate_analysis` uni BOSHQA sabab
       bilan (kalit nomi, dalil shakli, ball) rad etishi mumkin edi va test o'zi o'lchamoqchi
       bo'lgan darvozani UMUMAN o'lchamay qolardi. Shu usulda rad etishning sababi FAQAT
       `status` bo'ladi.
    """

    version = "0.0.1-SINTETIK"

    def __init__(self, status: str, nom: str) -> None:
        self._status = status
        self.name = nom

    def analyze(self, payload):
        doc = dict(HeuristicAnalyzer().analyze(payload))
        gipotezalar = [dict(h) for h in doc["hypotheses"]]
        assert gipotezalar, ("fikstura birorta gipoteza bermadi — bunda ssenariy "
                            "o'lchanmay qolardi")
        gipotezalar[0]["status"] = self._status
        doc["hypotheses"] = gipotezalar
        return doc


def zond_paketi(papka, *, read_only: str) -> str:
    """Zond natijasi BOR Phase 4 paketi — `read_only` qiymati KIRISHDAN.

    ⚠️ `read_only="true"` — shartnoma talab qiladigan YAGONA qiymat (`"false"` ham,
       `true` booleani ham RAD: `runtime_bundle.validate_probe_result`). Shu bois bu
       generator K ssenariysida IKKI MARTA, FAQAT shu bitta qiymat bilan farqlanib
       chaqiriladi — yiqilish AYNAN mutatsiya signaliga tegishli bo'lsin.
    """
    nom = "01_row_count"
    a_lar = sorted(set(rb.REQUIRED_FILES) | {f"{rb.PROBE_DIR}/{nom}.json"})
    return M.yoz(papka, RB.paket(
        mode=rb.MODE_APPROVED_PROBES,
        probes={nom: RB.probe_doc(read_only=read_only)},
        run=RB.run_status(mode=rb.MODE_APPROVED_PROBES,
                          mode_note="operator ANIQ allowlist tasdiqladi (SINTETIK)",
                          probes_log=[RB.zond_qaydi("row_count")],
                          artifacts=a_lar)))


# ══════════════════════════════════════════════════════════════════════════════════════════
# A · 1C YO'Q -> YAROQLI YIQILISH PAKETI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_A_1c_yoq_YAROQLI_yiqilish_paketi_qoladi(tmp_path):
    """1C o'rnatilmagan mashinada operator qo'lida UZATISHGA YAROQLI paket qoladi.

    ⚠️ NEGA BU ENG MUHIM YIQILISH: `states.failure_meaning` operatorga «natija papkasini
       butunlay (hisoboti bilan) saqlab, ishlab chiquvchiga uzating» deydi. Papka yozilmasa
       yoki validatordan o'tmasa, bu ko'rsatma BAJARILMAS bo'lib qolardi va nuqsonning
       yagona izi ekrandagi bir qatorlik xabar bo'lardi.
    ⚠️ `epf_path` ATAYLAB BERILADI: paketli yo'lning darvozasi AYNAN muhit hukmini o'qiydi,
       demak `FAILED_NO_1C` ni shu yo'l chiqaradi. `watch_folder` yo'li 1C mavjudligi haqida
       HECH NARSA demaydi (buni C ssenariysi ko'rsatadi).
    """
    ota = tmp_path / "natija"
    natija = X.agent(ota, scan=X.muhit_1c_yoq(), epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_NO_1C, "muhit hukmi MUHIT holati bo'lib chiqadi"
    assert natija.result_dir is not None, "yiqilgan yurish ham PAPKA qoldiradi"
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)
    assert paket_fayllar(natija.result_dir) == set(), \
        "paket OLINMAGAN yurishda `bundle/` BO'SH qoladi — bo'sh papka «paket bor» demaydi"

    # ── Mashina o'qiydigan ajrim: hukm YURISH YOZUVIDA ──────────────────────────────────
    d = yozuv(natija.result_dir)
    assert d["presence_verdict"] == D.PRESENCE_ABSENT
    assert bridge.CODE_EXE_MISSING in xato_kodlari(natija.result_dir)

    # ⚠️⚠️ CHEGARA YOPILDI (oldingi yozuv: «kalit `environment.json` da YO'Q»): hukm ENDI
    #      muhit hujjatining O'ZIDA ham turadi, ya'ni uni YOLG'IZ o'qiydigan dastur
    #      «qaradim va yo'q» bilan «qaray olmadim» ni o'zbek nasrini tahlil qilmasdan
    #      ajratadi. Shu bois chegara emas, MOSLIK qulflanadi: bitta paketdagi ikki hujjat
    #      AYNI hukmni yozishi SHART (ZID hukm — yangi nuqson).
    muhit_doc = json.loads(X.matn(natija.result_dir, ENVIRONMENT_FILE))
    assert muhit_doc["presence_verdict"] == d["presence_verdict"] == D.PRESENCE_ABSENT, \
        "`environment.json` va `agent_status.json` hukmi ZID bo'lishi MUMKIN EMAS"
    assert any(D.PRESENCE_ABSENT in n for n in muhit_doc["notes"]), \
        "hukm muhit hujjatida izoh bo'lib ham qoladi (odam o'qiydigan ajrim)"

    # ── Odam o'qiydigan ajrim: hisobot `absent` MA'NOSINI beradi ─────────────────────────
    assert st.failure_meaning(st.FAILED_NO_1C, presence_verdict=D.PRESENCE_ABSENT) \
        in hisobot(natija.result_dir), "hisobot ma'noni O'ZI yozmaydi — `states` dan oladi"


def test_A2_ildizdagi_errors_json_PHASE4_hujjati_BILAN_aralashmaydi(tmp_path):
    """Ildizdagi `errors.json` AGENT hujjati, `bundle/errors.json` esa PHASE 4 ning hujjati.

    ⚠️⚠️ NEGA ALOHIDA TEST: ikki fayl BIR XIL nomda va IKKI XIL sxemada. «Bir xil nom, ikki
         xil sxema» Phase 4 da butun paketni rad etgan nuqsonning aynan o'zi edi, shu bois
         ARALASHTIRISH IKKI TOMONGA ham rad etilishi kerak — va aralashtirishni TUTADIGAN
         test SHART.
    ⚠️ Sxemalar VERSIYA SATRI bilan ajraladi va bu testda ikkisi ham KODDAN olinadi.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()
    assert natija.state == st.COMPLETE
    yaroqli_paket(natija.result_dir)

    ildiz = ildiz_errors(natija.result_dir)
    paketdagi = json.loads(X.matn(natija.result_dir, f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}"))
    assert ildiz["errors_version"] == ERRORS_VERSION
    assert paketdagi["errors_version"] == rb.ERRORS_VERSION
    assert ERRORS_VERSION != rb.ERRORS_VERSION, "ikki sxema BIR XIL versiya satriga ega emas"
    # ⚠️ Agent manifesti `manifest.json` deb ATALMAYDI (brief §5) — Phase 4 ning manifesti
    #    `bundle/` ichida shu nomda turadi va ikkisi bir papkada uchrashmasligi kerak.
    assert AGENT_MANIFEST_FILE in ildiz_fayllar(natija.result_dir)
    assert rb.MANIFEST_FILE not in ildiz_fayllar(natija.result_dir)
    assert rb.MANIFEST_FILE in paket_fayllar(natija.result_dir)

    # ── ARALASHTIRISH IKKI TOMONGA ham RAD etiladi ───────────────────────────────────────
    with pytest.raises(rp.ResultPackageError):
        rp.validate_agent_errors(paketdagi)      # Phase 4 hujjati ILDIZDA — RAD
    with pytest.raises(rb.RuntimeBundleError):
        rb.validate_errors(ildiz)                # agent hujjati `bundle/` da — RAD
    # ⚠️ Har biri O'Z sxemasi bilan esa O'TADI: darvoza «hammasini rad etish» EMAS.
    rp.validate_agent_errors(ildiz)
    rb.validate_errors(paketdagi)


# ══════════════════════════════════════════════════════════════════════════════════════════
# B · DETEKTOR `unknown` -> YOLG'ON `absent` DA'VOSI YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_B_unknown_hukmida_agent_absent_DAVO_QILMAYDI(tmp_path):
    """Reestr O'QILMADI -> hukm `unknown`, va «o'rnatilmagan» xulosasi HECH QAYERDA YO'Q.

    ⚠️⚠️ BU `UNKNOWN -> NOT_FOUND` SIQILISHINING UCHIGA-UCH ISBOTI. Hukm IKKI joyda
         ko'rinadi va IKKISI ham MAVJUD lug'atdan: mashina uchun
         `agent_status.presence_verdict`, odam uchun `states.failure_meaning(...)`. Yangi
         holat (`FAILED_1C_UNKNOWN` kabi) QO'SHILMAGANI ham shu testda qulflanadi: yakun
         AYNI `FAILED_NO_1C` bo'lib qoladi.
    ⚠️ ENG QATTIQ ASSERT — oxirgisi: `absent` matni papkaning BIRORTA baytida uchramaydi.
       Hisobotda bitta joy to'g'ri yozilib, boshqa joyda (izoh, xato tafsiloti) qolib ketsa
       ham operator ZID ikki gapni o'qirdi.
    """
    ota = tmp_path / "natija"
    natija = X.agent(ota, scan=X.muhit_huquq_yoq(), epf_path=X.epf_yoz(tmp_path),
                     output_dir=X.bosh_papka(tmp_path, "chiqish")).start()

    assert natija.state == st.FAILED_NO_1C, "YANGI holat yaratilmaydi — yakun AYNI"
    assert natija.result_dir is not None
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)

    # ── (1) MASHINA O'QIYDIGAN AJRIM ─────────────────────────────────────────────────────
    d = yozuv(natija.result_dir)
    assert d["presence_verdict"] == D.PRESENCE_UNKNOWN
    assert d["presence_verdict"] in (D.PRESENCE_FOUND, D.PRESENCE_ABSENT,
                                     D.PRESENCE_UNKNOWN), "lug'at YOPIQ, yangi qiymat YO'Q"
    assert D.CODE_REGISTRY_UNREADABLE.upper() in xato_kodlari(natija.result_dir), \
        "qaysi manba o'qilmagani ANIQ kod bilan qoladi"
    # ⚠️ CHEGARA YOPILDI (A ssenariysidagi bilan AYNI): hukm ENDI muhit hujjatida ham bor,
    #    shu bois IKKI HUJJATNING MOSLIGI tekshiriladi — izoh ham «yo'q» deb DA'VO QILMAYDI.
    muhit = json.loads(X.matn(natija.result_dir, ENVIRONMENT_FILE))
    assert muhit["presence_verdict"] == d["presence_verdict"] == D.PRESENCE_UNKNOWN, \
        "bitta paketdagi ikki hujjat AYNI hukmni yozadi — ZID bo'lishi MUMKIN EMAS"
    assert any("HAQLI EMAS" in n for n in muhit["notes"]), \
        "o'qilmagan manba ustidan xulosa chiqarilmasligi muhit hujjatida ham AYTILADI"
    assert not any(f"({D.PRESENCE_ABSENT})" in n for n in muhit["notes"]), \
        "muhit hujjati `absent` hukmini DA'VO QILMAYDI"

    # ── (2) ODAM O'QIYDIGAN AJRIM ────────────────────────────────────────────────────────
    matn = hisobot(natija.result_dir)
    unknown_ma_no = st.failure_meaning(st.FAILED_NO_1C,
                                       presence_verdict=D.PRESENCE_UNKNOWN)
    absent_ma_no = st.failure_meaning(st.FAILED_NO_1C,
                                      presence_verdict=D.PRESENCE_ABSENT)
    assert unknown_ma_no != absent_ma_no, "ikki hukm uchun matn BOSHQA bo'lishi SHART"
    assert unknown_ma_no in matn
    assert absent_ma_no not in matn

    # ⚠️ SHARTSIZ matn ham chiqmaydi: u «hukm berilmagan» holat uchun va bu yerda hukm BOR.
    assert st.FAILURE_MEANING[st.FAILED_NO_1C] not in matn, \
        "hukm berilgan bo'lsa SHARTSIZ matn ko'rsatilmaydi"

    # ── (3) PAPKANING BIRORTA BAYTIDA «ISBOTLANGAN YO'QLIK» DA'VOSI YO'Q ────────────────
    hamma = papka_ichidagi_hamma_bayt(natija.result_dir).decode("utf-8", "replace")
    assert absent_ma_no not in hamma
    for parcha in ("Bu JAVOB, taxmin emas", "O'RNATILMAGAN"):
        assert parcha not in hamma, \
            f"o'qilmagan manba ustidan da'vo qolib ketdi: {parcha!r}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# C · KUZATILGAN PAPKA BO'SH -> KUTADI, SO'NG `FAILED_TIMEOUT` (CHEKSIZ KUTISH YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_C_bosh_papkada_kutadi_va_CHEKLI_vaqtda_FAILED_TIMEOUT(tmp_path):
    """Operator yig'uvchini hali yurgizmagan -> agent KUTADI va CHEKLI vaqtda to'xtaydi.

    ⚠️ BO'SH PAPKA YIQILISH EMAS: u kutishning BOSHLANG'ICH holati (brief §6C). Shu bois
       yakun `FAILED_COLLECTOR_UNAVAILABLE` («javob bermadi» degan HUKM) emas,
       `FAILED_TIMEOUT` — yig'uvchi hali ishlab turgan bo'lishi MUMKIN.
    ⚠️ KUTISH KO'RINADI: `waiting_ticks` va `wait_line()` operator ekranida «osilgan» emas,
       «kutilmoqda» deb o'qilishini ta'minlaydi. Bu BEZAK emas — ko'rinmasa operator
       agentni o'ldirib, sababsiz qolardi.
    ⚠️ HAQIQIY SONIYA KUTILMAYDI: `sleeper` faqat so'rovni YOZIB OLADI. «Cheksiz kutish
       YO'Q» da'vosi shu jurnal bilan O'LCHANADI — chaqiruvlar soni CHEKLI.
    """
    ota = tmp_path / "natija"
    bosh = X.bosh_papka(tmp_path, "kuzatilgan-bosh")
    uyqu: list[float] = []
    model = X.kutuvchi_agent(ota, bundle_dir=bosh, timeout_seconds=6.0, poll_seconds=2.0,
                             uyqu_jurnali=uyqu, qadam=1.0)
    natija = model.start()

    assert natija.state == st.FAILED_TIMEOUT
    assert natija.result_dir is not None
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)

    # ── KUTDI (jim turmadi) ──────────────────────────────────────────────────────────────
    assert model.waiting_ticks >= 1, "bo'sh papkada agent KUTISHI kerak, darhol yiqilmasligi"
    assert "kutilmoqda" in model.wait_line(), "kutish OPERATOR EKRANIDA ko'rinadi"
    assert uyqu, "kutish `sleeper` orqali bo'ladi (haqiqiy `time.sleep` EMAS)"
    assert all(s == 2.0 for s in uyqu), "so'rov oralig'i KIRISHDAN keladi"

    # ── CHEKSIZ EMAS ─────────────────────────────────────────────────────────────────────
    assert len(uyqu) <= 10, f"kutish CHEKLI bo'lishi SHART, o'lchov soni: {len(uyqu)}"
    assert model.waiting_ticks == len(uyqu), \
        "har «hali tayyor emas» o'lchovi BIR MARTA ko'rsatiladi va BIR MARTA uxlaydi"

    # ── SABAB va YO'L HAQQONIYLIGI ───────────────────────────────────────────────────────
    d = yozuv(natija.result_dir)
    assert d["route"] == ROUTE_WATCH_FOLDER
    assert bridge.CODE_WAIT_TIMEOUT in xato_kodlari(natija.result_dir)
    assert YOL_QAYDI in xato_kodlari(natija.result_dir), \
        "paketli yo'l NEGA urinilmagani JIMGINA tashlanmaydi"
    # ⚠️ Operatorning TO'RT qadami yozuvga AYNI holda tushadi — ekran va hisobot bir manbadan.
    assert set(bridge.WATCH_FOLDER_OPERATOR_STEPS) <= set(d["notes"])
    assert model.operator_steps() == bridge.WATCH_FOLDER_OPERATOR_STEPS


def test_C2_kuzatiladigan_papka_YOQ_bolsa_KUTISH_umuman_boshlanmaydi(tmp_path):
    """Papka KO'RSATILMAGAN -> darhol `FAILED_COLLECTOR_UNAVAILABLE`, kutish YO'Q.

    ⚠️ NEGA `FAILED_TIMEOUT` EMAS: kutish papkani YARATMAYDI, demak u bu holatni HECH
       QACHON tuzatmaydi va soniyalarni sarflash operatorni chalg'itardi (fail-closed).
    ⚠️ Bu C ning JUFTI: ikkisi birgalikda «bo'sh papka» (kutiladi) va «papka yo'q»
       (kutilmaydi) ni AJRATADI. Bittasi bo'lsa, ikkisi bitta kodga qo'shilib ketgani
       sezilmay qolardi.
    """
    ota = tmp_path / "natija"
    uyqu: list[float] = []
    model = X.kutuvchi_agent(ota, bundle_dir=None, uyqu_jurnali=uyqu)
    natija = model.start()

    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE
    assert model.waiting_ticks == 0 and uyqu == [], "yo'q papkani KUTISH ma'nosiz"
    assert natija.result_dir is not None
    yaroqli_paket(natija.result_dir)
    assert bridge.CODE_BUNDLE_DIR_MISSING in xato_kodlari(natija.result_dir)
    # ⚠️ Bu kod 1C bor-yo'qligi haqida HECH NARSA demaydi: hukm `muhit_1c_yoq()` dan
    #    kelgani holda ham yakun `FAILED_NO_1C` EMAS — sabab BOSHQA qatlamda.
    assert st.FAILED_NO_1C not in holatlar(natija.result_dir)


# ══════════════════════════════════════════════════════════════════════════════════════════
# D · YAROQLI SUCCESS PAKETI -> `COMPLETE`, HISOBOT va NOMZODLAR YOZILGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_D_yaroqli_paket_paydo_bolsa_COMPLETE_va_hamma_artefakt_yoziladi(tmp_path):
    """Operator yig'uvchini yurgizdi, paket to'liq -> `COMPLETE` + OLTI ildiz artefakti.

    ⚠️ BU TESTNING QAMROVI: paket yaroqli bo'lsa quvur OXIRIGACHA boradi va natija
       UZATISHGA tayyor bo'ladi. BU TEST ISBOTLAMAYDI: yig'uvchining 1C da rostdan
       ishlashini — paket SINTETIK.
    ⚠️ `bundle/` BAYT-BA-BAYT solishtiriladi: agent manba paketni O'ZGARTIRMASLIGI kerak
       (u DALIL va uning xeshlari Phase 4 manifestida yozilgan).
    ⚠️ PROGRESS ZANJIRI operator hujjati (§3.5) bilan solishtiriladi: ekranda ko'rinadigan
       qadamlar yurish yozuvidagi o'tishlardan AJRALIB ketmasligi kerak.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    manba_baytlari = X.papka_baytlari(manba)

    progress: list[str] = []
    model = X.kutuvchi_agent(ota, bundle_dir=manba,
                             scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)))
    model.on_progress = progress.append
    natija = model.start()

    assert natija.state == st.COMPLETE, "yaroqli paket OXIRIGACHA boradi"
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir, tahlil_bor=True)

    # ── Hisobot va nomzodlar ROSTDAN yozilgan (bo'sh emas) ───────────────────────────────
    assert hisobot(natija.result_dir).strip(), "hisobot BO'SH bo'lmaydi"
    korik = json.loads(X.matn(natija.result_dir, AI_CANDIDATES_FILE))
    assert korik["candidates"], "tahlil KAMIDA bitta nomzod bermasligi — nuqson belgisi"

    # ── Phase 4 paketi O'ZGARMAGAN ───────────────────────────────────────────────────────
    assert X.papka_baytlari(manba) == manba_baytlari, "MANBA papkaga TEGILMAYDI"
    kochirilgan = {n[len(BUNDLE_SUBDIR) + 1:]: b
                   for n, b in X.papka_baytlari(natija.result_dir).items()
                   if n.startswith(f"{BUNDLE_SUBDIR}/")}
    assert kochirilgan == manba_baytlari, "`bundle/` BAYT-BA-BAYT ko'chiriladi"

    # ── PROGRESS zanjiri = yurish yozuvi = operator hujjati ─────────────────────────────
    assert tuple(progress) == TOLIQ_PROGRESS, f"progress zanjiri o'zgardi: {progress}"
    assert holatlar(natija.result_dir) == list(TOLIQ_PROGRESS), \
        "ekran va yurish yozuvi BIR XIL zanjirni ko'rsatishi SHART"

    # ── YO'L HAQQONIYLIGI: muvaffaqiyatda ham «avtomatik» da'vosi YO'Q ──────────────────
    d = yozuv(natija.result_dir)
    assert d["route"] == ROUTE_WATCH_FOLDER
    matn = hisobot(natija.result_dir)
    assert reporter.NO_AUTOMATION_LINE in matn, \
        "yig'uvchini OPERATOR yurgizgani MUVAFFAQIYATLI yurishda ham aytiladi"
    assert reporter.INTERVENTION_BY_ROUTE[ROUTE_WATCH_FOLDER] in matn
    assert ROUTE_BATCH_EXECUTE in matn, "urinilmagan yo'l ham NOMI bilan tilga olinadi"
    assert model.route_line().count(ROUTE_WATCH_FOLDER) >= 1
    assert "ishga tushirMAYDI" in model.route_line(), \
        "ekrandagi qator «avtomatik razvedka» taassurotini BERMAYDI"


def hisobot_artefaktlari(matn: str) -> list[str]:
    """Hisobotning «### Artefaktlar» bo'limida SANALGAN nomlar.

    ⚠️ Nomlar hisobotdan O'QILADI, qo'lda yozilmaydi: test ikkita hujjatni SOLISHTIRADI va
       o'zi uchinchi haqiqat yozmaydi.
    """
    bolim = matn.split("### Artefaktlar", 1)[1].split("###", 1)[0]
    return [s.strip()[3:-1] for s in bolim.splitlines() if s.strip().startswith("- `")]


def test_D2_hisobot_sanagan_artefaktlar_YURISH_YOZUVI_bilan_MOS(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON: muvaffaqiyatli yurishda hisobot UCHTA nom sanardi,
         `agent_status.json` esa O'N IKKITA — ya'ni bitta papka ichidagi ikki hujjat
         ZID edi va operator «qaysi biri haqiqat» savoli bilan qolardi.

    Sabab: `COMPLETE` yo'lida hisobotni QUVUR quradi va u faqat O'ZI chiqargan nomlarni
    biladi; papkaning yakuniy ro'yxati esa `ui` qatlamida tug'iladi (`environment.json`,
    `agent_manifest.json`, `errors.json` va butun `bundle/`).
    ⚠️ TEST IKKI TOMONNI SOLISHTIRADI va MUAYYAN SONNI qulflamaydi: paket fiksturasi
       o'zgarsa ham invariant (ikki hujjat MOS) o'lchanishda davom etadi.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()
    assert natija.state == st.COMPLETE
    yaroqli_paket(natija.result_dir)

    d = yozuv(natija.result_dir)
    sanalgan = hisobot_artefaktlari(hisobot(natija.result_dir))
    assert sanalgan == d["artifacts"], \
        "hisobot va yurish yozuvi AYNI artefakt ro'yxatini sanashi SHART"
    # ⚠️ Ro'yxat ROSTDAN to'liq: `bundle/` ham, ildizdagi hosila fayllar ham ichida.
    assert ERRORS_FILE in sanalgan and AGENT_MANIFEST_FILE in sanalgan
    assert any(n.startswith(f"{BUNDLE_SUBDIR}/") for n in sanalgan)
    assert set(sanalgan) == set(X.papka_baytlari(natija.result_dir)), \
        "hisobot papkada ROSTDAN turgan fayllarni sanaydi (yo'q narsa ham, kam ham emas)"


# ══════════════════════════════════════════════════════════════════════════════════════════
# E · `PARTIAL` PAKET -> VALIDATOR KODI `2` HURMAT QILINADI (JIMGINA DAVOM YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_E_partial_paket_kod_2_bilan_TOXTAYDI_va_tahlil_BAJARILMAYDI(tmp_path):
    """Paketning BAYTLARI to'g'ri, YURISHI to'liq emas (`overall=PARTIAL`) -> quvur TO'XTAYDI.

    ⚠️⚠️ ENG NOZIK NUQTA: `2` «yiqildi» EMAS, lekin «davom et» ham EMAS. Yarim yurishdan
         chiqarilgan xulosa TO'LIQ xulosaga O'XSHAB ketardi — ya'ni «qaralmadi» jimgina
         «yo'q» ga aylanardi. Shu bois tahlil BAJARILMAYDI va nomzodlar fayli YOZILMAYDI.
    ⚠️ `2` va `1` AJRATILADI: ikkisi bir kodga qo'shilsa, operator «paketga ishonib
       bo'lmaydi» (qayta yig'ish kerak) bilan «yig'uvchi hamma bo'limni tugatmagan» (qayta
       YURGIZISH kerak) ni farqlamasdi.
    ⚠️ BUZUQ EMAS, LEKIN TO'LIQ EMAS paket `bundle/` da DALIL bo'lib SAQLANADI.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_oila_oqilmadi)
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.state == st.FAILED_VALIDATION
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)      # ⚠️ nomzodlar fayli YO'Q — tekshiriladi

    # ── Validator kodi AYNAN `2` (hujjatda MATN) ─────────────────────────────────────────
    hisobot_matni = hisobot(natija.result_dir)
    assert P.EXIT_INCOMPLETE == "2" and P.EXIT_INVALID == "1", \
        "kodlar yadrodan keladi; ikkisi ARALASHMAYDI"
    assert "BUNDLE_RUN_INCOMPLETE" in xato_kodlari(natija.result_dir)
    assert "BUNDLE_INVALID" not in xato_kodlari(natija.result_dir), \
        "to'liq bo'lmagan yurish «paketga ishonib bo'lmaydi» deb NOMLANMAYDI"

    # ── Paketning O'Z hukmi `PARTIAL` va u yo'qolmaydi ──────────────────────────────────
    paket_run = json.loads(X.matn(natija.result_dir,
                                  f"{BUNDLE_SUBDIR}/{rb.RUN_STATUS_FILE}"))
    assert paket_run["overall"] == rb.OVERALL_PARTIAL
    assert M.CODE_FAMILY_UNREADABLE in X.matn(natija.result_dir,
                                              f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}"), \
        "o'qilmagan oila DALIL bo'lib `bundle/` da qoladi"

    # ── TAHLIL BAJARILMADI va bu OCHIQ aytiladi ─────────────────────────────────────────
    assert st.ANALYSIS not in holatlar(natija.result_dir), \
        "kod 2 dan keyin tahlilga O'TILMAYDI"
    assert st.failure_meaning(st.FAILED_VALIDATION) in hisobot_matni


# ══════════════════════════════════════════════════════════════════════════════════════════
# F · BUZUQ PAKET -> `FAILED_VALIDATION` (kod `1`)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_F_buzuq_paket_FAILED_VALIDATION_va_buzuq_baytlar_DALIL_bolib_qoladi(tmp_path):
    """`metadata.json` YARIM yozilgan -> paketga ISHONIB BO'LMAYDI (kod `1`).

    ⚠️ FIKSTURA ATAYLAB SHUNDAY: manifest AYNI yarim baytlarni xeshlaydi, ya'ni xesh MOS
       keladi va nuqsonni FAQAT qat'iy JSON o'qish tuta oladi. Aks holda test o'zini
       «yarim yozilishni ushladim» deb hisoblab, aslida xesh darvozasini o'lchagan bo'lardi.
    ⚠️ BUZUQ PAKET SAQLANADI: rad etilgan paketni tashlab yuborish YAGONA dalilni yo'q
       qilardi. Lekin sir darvozalari BU HOLATDA HAM ochilmaydi (G ssenariysiga qarang).
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_serializatsiya_yarim)
    buzuq_baytlar = pathlib.Path(manba, rb.METADATA_FILE).read_bytes()
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.state == st.FAILED_VALIDATION
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)
    assert "BUNDLE_INVALID" in xato_kodlari(natija.result_dir)
    assert "BUNDLE_RUN_INCOMPLETE" not in xato_kodlari(natija.result_dir), \
        "ishonib bo'lmaydigan paket «to'liq emas» deb yumshatilmaydi"
    assert st.GRAPH_BUILD not in holatlar(natija.result_dir), "grafga O'TILMAYDI"

    # ── Dalil AYNI buzuq baytlar bilan saqlangan ─────────────────────────────────────────
    saqlangan = pathlib.Path(natija.result_dir, BUNDLE_SUBDIR, rb.METADATA_FILE)
    assert saqlangan.read_bytes() == buzuq_baytlar, \
        "buzuq paket «tuzatilmaydi» va «tashlanmaydi» — AYNAN shu baytlar qoladi"
    with pytest.raises(ValueError):
        json.loads(buzuq_baytlar.decode("utf-8", "replace"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# G · SIRLI ARTEFAKT -> PAKET USHLAB QOLINADI, LEKIN MINIMAL PAKET QOLADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_G_paketda_sir_bolsa_MINIMAL_SIRSIZ_paket_qoladi(tmp_path):
    """Yig'uvchi `errors.json` iga 1C ulanish satrini qo'ydi -> SIR yozilmaydi, PAKET qoladi.

    ⚠️ HAQIQIY OQIM SHUNDAY: SUBD xatosi ulanish satrini (server nomi, foydalanuvchi,
       parol) O'Z ICHIGA OLADI, ya'ni bu operator xatosi emas, quvurning TABIIY natijasi.
    ⚠️⚠️ TUZATILGAN NUQSON (brief §2 ni buzardi): avval bu YAGONA ssenariy edi, unda
         `result_dir is None` bo'lardi — ya'ni na yurish yozuvi, na `errors.json`, na muhit
         hujjati yozilmasdi va SIR ANIQLANGANI faktining ham hujjatli izi QOLMASDI. Brief §2
         esa ANIQ: «operator hech qachon ``hech narsa qolmadi`` holatida qolmasin, failure
         package ham VALID package bo'lsin». Endi MINIMAL, SIRSIZ paket yoziladi.
    ⚠️⚠️ ASIMMETRIYA ATAYLAB SAQLANADI: buzuq paket DALIL bo'lib `bundle/` da saqlanadi (F),
         SIRLI paket esa SAQLANMAYDI — «dalilni saqlash» mijozning parolini tashqariga
         chiqarishni OQLAMAYDI. Shu bois bu ssenariyda `bundle/` ham, nomzodlar fayli ham
         YOZILMAYDI, beshta ildiz artefakti esa YOZILADI.
    ⚠️ ENG QATTIQ ASSERT O'Z JOYIDA QOLADI: natija OTA PAPKASINING birorta baytida sir YO'Q.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sir_oqqan)
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.is_failure, "jimgina muvaffaqiyat YO'Q"
    assert natija.state == st.FAILED_REPORT, "chiqish YOZILMADI — bu UI ning hukmi"
    assert natija.code == agent_ui.CODE_SIR_USHLANDI
    assert natija.result_dir is not None, \
        "sir topilsa ham operator «hech narsa qolmadi» holatida QOLMAYDI (brief §2)"
    assert natija_papkalari(ota) == [pathlib.Path(natija.result_dir).name], \
        "AYNAN bitta natija papkasi: yarim yozilgan ikkinchi papka QOLMAYDI"

    # ── Paket HAQIQIY paket: validatordan O'TADI va beshta ildiz artefakti BOR ───────────
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)

    # ── SIRNING O'ZI YOZILMAYDI: `bundle/` ham, nomzodlar ham paketga TUSHMAYDI ──────────
    assert paket_fayllar(natija.result_dir) == set(), \
        "sirning eng ehtimolli tashuvchisi — Phase 4 paketi; u paketga QO'SHILMAYDI"
    assert ildiz_fayllar(natija.result_dir) == set(rp.ALWAYS_FILES), \
        "minimal paketda AYNAN beshta ildiz artefakti bo'ladi"

    # ── SIR ANIQLANGANI FAKTI ikki hujjatda ham YOZILGAN (va ular ZID emas) ─────────────
    d = yozuv(natija.result_dir)
    assert agent_ui.CODE_SIR_USHLANDI in xato_kodlari(natija.result_dir), \
        "sir topilgani NUQSON va u yashirilmaydi — yozuvda ANIQ kod turadi"
    assert ildiz_errors(natija.result_dir)["errors"] == d["errors"], \
        "`errors.json` yozuvdan HOSILA, demak ikkisi ZID bo'lolmaydi"
    sabab = [e["detail"] for e in d["errors"] if e["code"] == agent_ui.CODE_SIR_USHLANDI]
    assert len(sabab) == 1
    assert f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}" in sabab[0], \
        "yozuv QAYSI artefaktda sir topilganini AYTADI (operator shu faylni ko'radi)"
    assert "USHLAB QOLINDI" in sabab[0], "butun paket ushlab qolingani ham AYTILADI"
    # ⚠️ Yozuvdagi da'vo papkaga MOS: `bundle/` yo'q, demak `bundle_dir` ham `null`.
    assert d["bundle_dir"] is None, "yo'q paketni DA'VO qiladigan yozuv paket EMAS"
    assert d["artifacts"] == sorted(rp.ALWAYS_FILES)
    assert agent_ui.SIR_USHLANDI_IZOH in d["notes"], \
        "ekrandagi hukm bilan yozuvdagi holat farqi IZOHDA ochiq aytiladi"

    # ── Sir EKRANDA ham YO'Q, ALMASHTIRILGAN ─────────────────────────────────────────────
    ekran = natija.detail + " " + " ".join(natija.problems)
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat not in ekran, f"sir ekranda qoldi: {qiymat}"
    assert "[REDACTED]" in ekran, "qiymat YASHIRILMADI, ALMASHTIRILDI"

    # ── Sir YOZILGAN BIRORTA BAYTDA YO'Q (eng qattiq assert) ────────────────────────────
    yozilgan = papka_ichidagi_hamma_bayt(ota)
    for qiymat in M.SIR_QIYMATLAR:
        assert qiymat.encode("utf-8") not in yozilgan, \
            f"sir YOZILGAN baytlarda qoldi: {qiymat}"

    # ⚠️ MANBA PAPKADA sir JOYIDA qoladi: agent operator papkasini TOZALAMAYDI (faqat-o'qish
    #    chegarasi). Ya'ni «sir yo'q» da'vosi AGENT YOZGAN baytlar haqida, boshqa haqida emas.
    assert M.SIR_QIYMATLAR[0].encode("utf-8") in papka_ichidagi_hamma_bayt(manba), \
        "agent OPERATOR papkasini o'zgartirmaydi — fikstura shuni ko'rsatadi"


def test_G2_sir_ekranda_HAM_qiymatsiz_FAQAT_JOYI_bilan_aytiladi(tmp_path):
    """⚠️ Operator ekranda «qaysi faylni ko'rish kerak» ni ko'radi, QIYMATNI esa KO'RMAYDI.

    ⚠️ NEGA ALOHIDA TEST: `_sirli_artefaktlar` ro'yxati ekranga ham, yozuvga ham tushadi va
       u YADRONING skaneri bilan (`redact.scan`) hisoblanadi. Ro'yxat bo'sh bo'lib qolsa
       (masalan skaner almashtirilsa) minimal paket UMUMAN yozilmasdi — shu bois ro'yxatning
       mazmuni ham qulflanadi.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sir_oqqan)
    model = X.kutuvchi_agent(ota, bundle_dir=manba,
                             scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)))
    natija = model.start()
    assert f"{BUNDLE_SUBDIR}/{rb.ERRORS_FILE}" in natija.detail
    # ⚠️ Toza artefaktlar ro'yxatda YO'Q: «hammasi shubhali» degan ro'yxat hech narsa aytmasdi.
    assert REPORT_FILE not in natija.detail and ENVIRONMENT_FILE not in natija.detail


# ══════════════════════════════════════════════════════════════════════════════════════════
# H · NOANIQ METADATA -> `CANDIDATE`/`AMBIGUOUS`, IKKALA NOMZOD KO'RSATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_H_noaniq_metadata_AMBIGUOUS_va_IKKALA_nomzod_operatorga_KORSATILADI(tmp_path):
    """Ikki teng kuchli nomzod -> tanlash EMAS, IKKILANISHNI AYTISH.

    ⚠️ JIMGINA BITTASINI TANLASH — eng qimmat xato: operator xaritani tasdiqlangan deb
       o'qiydi va ko'chirish noto'g'ri katalogdan ketadi.
    ⚠️ BU TEST BALLNI QULFLAMAYDI: evristika o'zgarishi nuqson emas. Qulflanadigan narsa —
       (a) ikkala nomzod ham KO'RINADI, (b) status `AMBIGUOUS`, (c) ikkilanish SABABI
       ikkalasini NOMLAYDI, (d) tasdiq TALAB qilinadi, (e) `VERIFIED` so'zi hisobotda YO'Q.
    ⚠️ OPERATOR OQIMI DARAJASI: nomzodlar DISKDAGI `discovery_ai_candidates.json` dan
       o'qiladi va hisobotda ham ko'rinadi — ya'ni operator ularni ROSTDAN ko'radi.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan",
                        lambda p: M.yoz(p, M.baytlar(metadata=S.config("J"))))
    natija = X.kutuvchi_agent(ota, bundle_dir=manba,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.state == st.COMPLETE
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir, tahlil_bor=True)

    korik = json.loads(X.matn(natija.result_dir, AI_CANDIDATES_FILE))
    mahsulot = [c for c in korik["candidates"] if c["concept"] == "product"]
    assert len(mahsulot) >= 2, "ikki teng nomzod IKKI qator bo'lib ko'rinadi"
    assert {c["status"] for c in mahsulot} == {ai.STATUS_AMBIGUOUS}, \
        "teng ballda bittasi tanlab OLINMAYDI"

    OSN = "Справочник.ТоварыОсновные"
    DOP = "Справочник.ТоварыДополнительные"
    assert {c["candidate_object"] for c in mahsulot} == {OSN, DOP}
    for qator in mahsulot:
        sabab = " ".join(qator["ambiguity"])
        assert OSN in sabab and DOP in sabab, "ikkilanish IKKALA nomzodni NOMLAYDI"
        assert qator["required_confirmation"], "tasdiq TALAB qilinadi"

    # ── Hamma status AVTOMAT lug'atdan: `VERIFIED` ham, `HUMAN_CONFIRMED` ham YO'Q ──────
    assert {c["status"] for c in korik["candidates"]} <= set(ai.AI_STATUSES)
    assert ai.STATUS_HUMAN_CONFIRMED not in {c["status"] for c in korik["candidates"]}, \
        "odam tasdig'i AI kanalidan CHIQMAYDI"
    matn = hisobot(natija.result_dir)
    assert OSN in matn and DOP in matn, "operator IKKALASINI ham ko'rishi kerak"
    assert not rb.VERIFIED_WORD_RE.findall(matn), "`VERIFIED` so'zi hisobotda UMUMAN YO'Q"


# ══════════════════════════════════════════════════════════════════════════════════════════
# I · `VERIFIED` CHIQARISHGA URINISH -> RAD
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_I_analitik_VERIFIED_bermoqchi_bolsa_yurish_RAD_etiladi(tmp_path):
    """Analitik `VERIFIED` qaytardi -> `FAILED_ANALYSIS`, hisobot YOZILMAYDI.

    ⚠️ `VERIFIED` ni AI ham, yig'uvchi ham, quvurning O'ZI ham chiqara olmaydi
       (`ai.FORBIDDEN_STATUS`): bu daraja FAQAT odam tasdig'idan tug'iladi va u BOSHQA kanal.
    ⚠️ «BO'SH HISOBOT BILAN DAVOM ETISH» ENG QIMMAT XATO bo'lardi: operator tahlil
       bo'lmaganini BILMASDI. Shu bois nomzodlar fayli YOZILMAYDI va holat ANIQ.
    ⚠️ PAKET BARIBIR YAROQLI: yiqilish tahlil qatlamida bo'ldi, demak paketning O'ZI
       joyida qoladi va tahlilni 1C siz, keyinroq qayta yurgizish mumkin.
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    analitik = StatusAlmashtiruvchi(ai.FORBIDDEN_STATUS, "SintetikVerifiedBermoqchi")
    natija = X.kutuvchi_agent(ota, bundle_dir=manba, analyzer=analitik,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.state == st.FAILED_ANALYSIS
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)      # ⚠️ nomzodlar fayli YO'Q
    assert "ANALYSIS_FAILED" in xato_kodlari(natija.result_dir)
    assert st.REPORT not in holatlar(natija.result_dir), "hisobot qadamiga O'TILMAYDI"

    # ── TOPILGAN NOZIKLIK (yashirilmaydi): so'z paketda BOR, lekin FAQAT RAD SABABIDA ──
    #    ⚠️ «Umuman yo'q» talabi XATO bo'lardi: rad etilgan darajani ATAMASDAN rad etishni
    #       tushuntirib bo'lmaydi. Shu bois qulflanadigan invariant — so'z HUKM bo'lib
    #       chiqmasligi, ya'ni sabab matnidan TASHQARIDA uchramasligi.
    faqat_RAD_sababida(natija.result_dir, ai.FORBIDDEN_STATUS)
    # ⚠️ Yordamchi so'zni MATN bo'lib qidiradi; bu assert esa hisobotda so'z HUKM bo'lib
    #    chiqmaganini yadroning O'Z naqshi bilan (`VERIFIED_WORD_RE`) ikkinchi marta tekshiradi.
    assert rb.VERIFIED_WORD_RE.search(ai.FORBIDDEN_STATUS), \
        "yordamchi va yadro naqshi BIR XIL so'zni ko'rsatishi SHART"
    # ⚠️ Paket esa O'ZGARMAGAN holda saqlangan: tahlilni qayta yurgizish mumkin.
    assert paket_fayllar(natija.result_dir) == set(X.papka_baytlari(manba))


# ══════════════════════════════════════════════════════════════════════════════════════════
# J · AI KANALIDAN `HUMAN_CONFIRMED` -> RAD
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_J_AI_kanalidan_HUMAN_CONFIRMED_RAD_etiladi(tmp_path):
    """Analitik `HUMAN_CONFIRMED` qaytardi -> `FAILED_ANALYSIS`.

    ⚠️⚠️ NEGA BU `VERIFIED` DAN ALOHIDA SSENARIY: `HUMAN_CONFIRMED` — QONUNIY daraja,
         lekin FAQAT BOSHQA KANALDAN (operatorning alohida tasdiq hujjati). AI kanalida u
         «odam tasdiqladi» degan YOLG'ON provenans bo'lardi — ya'ni modelning taxmini
         odamning qaroriga aylanib qolardi va hisobotni o'qigan operator uni O'ZI
         tasdiqlagan deb o'qirdi. `VERIFIED` esa HECH QAYSI kanalda bo'lmaydi.
    ⚠️ Darvoza quvurning O'Z chaqiruvida: `pipeline.step_analysis` `validate_analysis` ni
       `allow_human_confirmed` BERMASDAN chaqiradi (ya'ni `False`).
    """
    ota = tmp_path / "natija"
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    analitik = StatusAlmashtiruvchi(ai.STATUS_HUMAN_CONFIRMED, "SintetikOdamDavogari")
    natija = X.kutuvchi_agent(ota, bundle_dir=manba, analyzer=analitik,
                              scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))).start()

    assert natija.state == st.FAILED_ANALYSIS, \
        "AI kanalidan kelgan odam tasdig'i JIMGINA qabul qilinmaydi"
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir)
    assert "ANALYSIS_FAILED" in xato_kodlari(natija.result_dir)

    # ── Daraja QONUNIY lug'atda BOR, lekin AI lug'atida YO'Q — ajrim KODDA turadi ───────
    assert ai.STATUS_HUMAN_CONFIRMED in ai.STATUSES
    assert ai.STATUS_HUMAN_CONFIRMED not in ai.AI_STATUSES
    # ── Natijada «odam tasdiqladi» degan DA'VO qolmaydi ────────────────────────────────
    assert AI_CANDIDATES_FILE not in ildiz_fayllar(natija.result_dir), \
        "rad etilgan tahlil artefakt QOLDIRMAYDI — «odam tasdiqlagan» hujjat UMUMAN YO'Q"
    # ⚠️ I ssenariysidagi AYNI usul: daraja FAQAT rad etish sababida uchraydi, qabul qilingan
    #    hukm bo'lib EMAS. Ikki ssenariy BIR XIL yordamchidan o'tadi, demak ularning
    #    invarianti ham bir xil qattiqlikda qulflangan.
    faqat_RAD_sababida(natija.result_dir, ai.STATUS_HUMAN_CONFIRMED)


# ══════════════════════════════════════════════════════════════════════════════════════════
# K · PAKETDA TAQIQLANGAN MUTATSIYA SIGNALI -> SHARTNOMA KO'RGAN JOYDA FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_K_paketdagi_YOZUVCHI_zond_signali_FAIL_CLOSED_rad_etiladi(tmp_path):
    """Zond natijasi `read_only="false"` deb keldi -> paket RAD, quvur TO'XTAYDI.

    ⚠️⚠️ SHARTNOMA BU SIGNALNI KO'RADI va bu testning qamrovi AYNAN SHU: Phase 4
         `runtime_bundle.validate_probe_result` `read_only` ni AYNAN `"true"` MATNI deb
         talab qiladi. `"false"` — «yig'uvchi YOZDI» degan e'lon, va yozuvchi zond bu
         qatlamning BUTUN ma'nosini yo'qotardi. Shu bois paket kod `1` bilan rad etiladi
         (`FAILED_VALIDATION`), buzuq baytlar esa DALIL bo'lib `bundle/` da qoladi.
    ⚠️ NAZORAT (`read_only="true"`) ATAYLAB: aynan BITTA maydon farq qiladi. Nazorat
       paketi validatordan O'TADI va boshqa — KEYINGI — darvozada to'xtaydi
       (`FAILED_SAFETY`: operator tasdig'i yo'q). Nazorat bo'lmasa, test «har qanday zond
       paketi rad etiladi» degan XULOSANI mutatsiya darvozasining ishi deb o'qirdi.
    """
    ota1, ota2 = tmp_path / "natija-yozuvchi", tmp_path / "natija-nazorat"
    yozuvchi = zond_paketi(tmp_path / "kuzatilgan-yozuvchi", read_only="false")
    nazorat = zond_paketi(tmp_path / "kuzatilgan-nazorat", read_only="true")
    muhit = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))

    # ── (1) MUTATSIYA SIGNALI: Phase 4 validatori RAD etadi ─────────────────────────────
    hisobot_4 = rb.validate_runtime_bundle(yozuvchi)
    assert not hisobot_4.ok, "yozuvchi zond signali paketni RAD ettirishi SHART"
    assert P.validator_exit_code(hisobot_4) == P.EXIT_INVALID, "kod `1`: ishonib bo'lmaydi"
    assert "read_only" in " ".join(hisobot_4.problems), \
        "sabab ANIQ maydonni NOMLASHI kerak — «rad etildi» yetmaydi"

    n1 = X.kutuvchi_agent(ota1, bundle_dir=yozuvchi, scan=muhit).start()
    assert n1.state == st.FAILED_VALIDATION
    yaroqli_paket(n1.result_dir)
    besh_ildiz_artefakti(n1.result_dir)
    assert "BUNDLE_INVALID" in xato_kodlari(n1.result_dir)
    assert st.ANALYSIS not in holatlar(n1.result_dir), "rad etilgan paket TAHLIL QILINMAYDI"
    assert paket_fayllar(n1.result_dir) == set(X.papka_baytlari(yozuvchi)), \
        "rad etilgan paket DALIL bo'lib saqlanadi"

    # ── (2) NAZORAT: AYNI paket `read_only="true"` bilan validatordan O'TADI ────────────
    hisobot_t = rb.validate_runtime_bundle(nazorat)
    assert hisobot_t.ok, f"nazorat paketi yaroqli bo'lishi kerak: {hisobot_t.problems}"
    n2 = X.kutuvchi_agent(ota2, bundle_dir=nazorat, scan=muhit).start()
    assert n2.state != st.FAILED_VALIDATION, \
        "farq FAQAT `read_only` da — nazorat validatorda to'xtamasligi kerak"
    assert n2.state == st.FAILED_SAFETY, \
        "tasdiqsiz zond BOSHQA (keyingi) darvozada to'xtaydi — sabablar ARALASHMAYDI"
    assert "PROBE_NOT_APPROVED" in xato_kodlari(n2.result_dir)
    yaroqli_paket(n2.result_dir)


def test_K2_paket_sxemasi_YIGUVCHI_YOZDI_degan_umumiy_signalni_KORMAYDI():
    """⚠️⚠️ OCHIQ BO'SHLIQ: `run_status.json` da «yig'uvchi hech narsa yozmadi» maydoni YO'Q.

    BU HOLAT EMAS va NUQSON ham EMAS — bu QAMROVNING ANIQ CHEGARASI, va u yashirilmaydi:

      · SHARTNOMA KO'RADIGAN YAGONA mutatsiya signali — ZOND natijasining `read_only`
        maydoni (yuqoridagi test). U FAQAT `APPROVED_PROBES` rejimidagi zond fayllarida
        bo'ladi.
      · `METADATA_ONLY` rejimida (ya'ni MVP ning DEFAULT va YAGONA yo'lida) paketda
        «yig'uvchi infobazaga yozdimi» degan savolga javob beradigan MAYDON UMUMAN YO'Q.
        Demak mutatsiya qilgan, lekin buni e'lon QILMAGAN yig'uvchi paket darajasida
        KO'RINMAYDI — paket shunchaki sog'lom ko'rinadi.
      · NIMA KERAK BO'LARDI (kelajak ishi, bu yerda QURILMAYDI): `run_status` ga yig'uvchining
        O'Z e'lonini (masalan `read_only` maydoni) kiritish SHARTNOMA O'ZGARISHI bo'ladi va
        u Phase 4 ni buzadi; bundan tashqari e'lonning O'ZI ISBOT EMAS — yolg'on e'lon ham
        xuddi shunday yoziladi. HAQIQIY isbot faqat 1C tomonidagi texnologik jurnal yoki
        faqat-o'qish huquqi bilan beriladi va ikkisi ham BU MASHINADA tekshirilmaydi.
      · BUGUN TURGAN DARVOZA — STATIK: `epf_audit` yig'uvchi MANBASINI tekshiradi. Pastda
        aynan shu darvoza SINALADI.

    ⚠️ BU TEST SKIP QILINMAYDI: bo'shliq KODDAN o'qib ISBOTLANADI (maydon ro'yxati) va
       mavjud darvoza ROSTDAN yurgiziladi. «Qamrov yo'q» degan gap testsiz qolsa, u bir kun
       «qamrov bor» ga aylanib ketardi.
    """
    # ── (1) BO'SHLIQ KODDAN ISBOTLANADI: `run_status` kalitlarida bunday maydon YO'Q ────
    kalitlar = set(RB.run_status())
    assert "read_only" not in kalitlar
    assert not any("read_only" in k or "mutat" in k.lower() for k in kalitlar), \
        f"shartnomaga mutatsiya e'loni qo'shilgan bo'lsa, bu izoh YANGILANISHI kerak: {kalitlar}"
    # ⚠️ Zond natijasida esa maydon BOR — ya'ni signal FAQAT shu yo'lda ko'rinadi.
    assert "read_only" in rb.PROBE_RESULT_KEYS

    # ── (2) MAVJUD DARVOZA SINALADI: `epf_audit` MANBADAGI mutatsiyani TUTADI ──────────
    mutatsiya = "\n".join([
        "// SINTETIK manba — mutatsiya urinishi (bu REAL yig'uvchi EMAS)",
        "Процедура SintetikYozish()",
        "    Объект.Записать();",
        "    Документ.Провести();",
        "    Элемент.Удалить();",
        "    УстановитьПривилегированныйРежим(Истина);",
        "КонецПроцедуры",
    ])
    MUTATSIYA_KODLARI = {"WRITE_OBJECT", "POST_DOCUMENT", "DELETE", "PRIVILEGED_MODE"}
    topilmalar = epf_audit.audit_source(mutatsiya)
    kodlar = {f.code for f in topilmalar}
    assert MUTATSIYA_KODLARI <= kodlar
    # ⚠️ «Qizil» YETMAYDI: har MUTATSIYA topilmasi SATR RAQAMI va SABABI bilan keladi, aks
    #    holda tuzatish imkonsiz bo'lardi.
    # ⚠️ FAQAT MUTATSIYA KODLARI: audit faylning O'ZI haqida ham topilma beradi (masalan
    #    `MISSING_MARKER` — «runtime'da sinalmagani ochiq yozilsin») va u butun faylga
    #    tegishli, ya'ni `line_no == 0`. Uni ham satr raqamiga majburlash fayl darajasidagi
    #    topilmani yo'q qilishni talab qilardi.
    for f in topilmalar:
        if f.code in MUTATSIYA_KODLARI:
            assert f.line_no > 0 and f.line.strip() and f.why.strip()
        else:
            assert f.why.strip(), "fayl darajasidagi topilma ham SABABSIZ bo'lmaydi"

    # ── (3) IKKINCHI TOMON: REPODAGI HAQIQIY manba darvozadan O'TADI ───────────────────
    #    ⚠️ Faqat (2) bo'lsa, darvoza ishlayotganini bilardik, lekin haqiqiy manba holati
    #       noma'lum qolardi; faqat (3) bo'lsa, darvoza butunlay ko'r bo'lgan taqdirda ham
    #       test yashil bo'lardi.
    assert BSL_SOURCE.is_file(), f"yig'uvchi manbasi topilmadi: {BSL_SOURCE.name}"
    assert epf_audit.audit_file(BSL_SOURCE) == [], \
        "repodagi yig'uvchi manbasi mutatsiya darvozasidan o'tmadi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# L · O'Z-O'ZINI YIQITADIGAN DARVOZA — HAQQONIYLIK QAYTA ISHGA TUSHMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ NEGA BUTUN BIR BO'LIM: yo'l haqqoniyligi darvozasi O'Z xato matnini QAYTA tutardi.
#:    Zanjir shunday edi: darvoza taqiqlangan iborani O'Z `ReportError` matniga kiritar ->
#:    `ui._yakunla` shu matnni `status.errors` ga yozar -> ZAHIRA hisobot uni `### Xatolar`
#:    bo'limida QAYTA chiqarar -> darvoza IKKINCHI marta urar -> istisno `start()` ning
#:    umumiy `except` iga tushib yurishni `FAILED_INTERNAL` qilar -> MINIMAL yozuv `route`,
#:    `bundle_dir`, artefaktlar va OLDINGI XATOLARNI tashlar edi. Natijada analitik BITTA
#:    izoh qo'shgani uchun yetkazilgan hisobot «Ishlatilgan yo'l: qayd etilmagan — bu
#:    NUQSON» deb yozardi, ya'ni brief §7 talab qilgan «operator aralashuvi YOZILGAN»
#:    da'vosi aynan shu yo'lda BAJARILMASDI.
class AvtomatikIzohliAnalitik:
    """Izohida AVTOMATLASHTIRISH da'vosi bor analitik — darvozaning HAQIQIY nishoni.

    ⚠️ NEGA `notes`, boshqa maydon emas: tahlilchining izohi hisobotga TASHQI matn bo'lib
       tushadigan ENG qisqa yo'l (`ai.analysis_notes` -> `review.analyzer_notes` ->
       `report._analyzer_section`), ya'ni test sun'iy teshik ochmaydi — u SHIPPED quvurdan
       o'tadi.
    ⚠️ Qolgan hamma narsa DETERMINISTIK evristikadan AYNAN olinadi: farq FAQAT bitta izoh
       bo'lsin, aks holda yiqilish sababini signalga bog'lab bo'lmasdi.
    """

    version = "0.0.1-SINTETIK"
    name = "sintetik-avtomatik-izoh"
    IZOH = "bu yurishda razvedka avtomatik bajarildi deb o'qilmasin"

    def analyze(self, payload):
        doc = dict(HeuristicAnalyzer().analyze(payload))
        doc["notes"] = list(doc.get("notes") or []) + [self.IZOH]
        return doc


def yol_bolimi(matn: str) -> str:
    """Hisobotning «Yo'l va operator aralashuvi» bo'limi (`report._route_section` chiqishi)."""
    return matn.split("## Yo'l va operator aralashuvi", 1)[1].split("\n## ", 1)[0]


def avtomatlashtirish_davosi(matn: str) -> list[str]:
    """Matnda `report.AUTOMATIC_CLAIM_PATTERNS` dan BIRORTASI tutgan joylar.

    ⚠️ NAQSHLAR KODDAN olinadi, qo'lda ko'chirilmaydi: test ikkinchi haqiqat yozmaydi va
       naqsh qo'shilsa u ham AVTOMATIK o'lchanadi.
    """
    topilgan = []
    for i, satr in enumerate(matn.splitlines(), start=1):
        for nom, rx in reporter.AUTOMATIC_CLAIM_PATTERNS:
            uchraydi = rx.search(satr)
            if uchraydi is not None:
                topilgan.append(f"satr {i}: {nom} ({uchraydi.group(0)!r})")
    return topilgan


def test_L_analitik_AVTOMATIK_izohi_yurishni_FAILED_INTERNAL_qilMAYDI(tmp_path):
    """⚠️⚠️ ASOSIY ISBOT: darvoza O'Z xato matni bilan QAYTA ishga TUSHMAYDI.

    Analitik izohiga bitta taqiqlangan ibora qo'shadi. KUTILADIGAN xulq: hisobot darvozada
    RAD etiladi (bu TO'G'RI — yolg'on da'vo chiqmaydi), LEKIN yurish `FAILED_INTERNAL` ga
    AYLANMAYDI va yozuvdagi `route`, `bundle_dir`, OLDINGI XATOLAR hamda operator qadamlari
    JOYIDA QOLADI.

    ⚠️ NAZORAT YURISHI SHU TESTDA: AYNI fikstura FAQAT izohsiz ham yurgiziladi va u
       `COMPLETE` bo'ladi. Shunday bo'lmasa, bu test «quvur umuman ishlamayapti» ni
       `FAILED_INTERNAL` yo'qligi deb o'qib, nuqsonni O'LCHAMAY qolardi.
    ⚠️ TEST MUAYYAN YIQILISH NOMINI QULFLAMAYDI: o'lchanadigan invariant — nuqson holati
       (`FAILED_INTERNAL`) va MA'LUMOT YO'QOLISHI YO'Q. Hisobotning O'ZI rad etilgani
       `pipeline` ning shartnomasi va u yerda sinaladi.
    """
    muhit = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))

    # ── NAZORAT: AYNI fikstura, izohSIZ — to'liq tugaydi ────────────────────────────────
    nazorat = X.kutuvchi_agent(tmp_path / "nazorat",
                               bundle_dir=X.paket_yoz(tmp_path / "n-paket",
                                                      M.paket_sog_lom),
                               scan=muhit).start()
    assert nazorat.state == st.COMPLETE, \
        "nazorat yurishi tugamadi — signal izohga bog'lanmay qoladi"

    # ── SIGNAL: FAQAT bitta izoh qo'shildi ─────────────────────────────────────────────
    natija = X.kutuvchi_agent(tmp_path / "natija",
                              bundle_dir=X.paket_yoz(tmp_path / "s-paket",
                                                     M.paket_sog_lom),
                              analyzer=AvtomatikIzohliAnalitik(), scan=muhit).start()

    assert natija.result_dir is not None, "operator qo'lida paket QOLISHI shart"
    assert natija.state != st.FAILED_INTERNAL, \
        "darvozaning O'Z xato matni yurishni NUQSON holatiga ag'darmasligi SHART"
    assert agent_ui.CODE_ICHKI_XATO not in xato_kodlari(natija.result_dir)
    yaroqli_paket(natija.result_dir)
    besh_ildiz_artefakti(natija.result_dir, tahlil_bor=True)

    # ── MA'LUMOT YO'QOLMADI: yo'l, paket va OLDINGI xatolar JOYIDA ─────────────────────
    d = yozuv(natija.result_dir)
    assert d["route"] == ROUTE_WATCH_FOLDER, "yo'l ANIQ ma'lum edi — u yo'qolmaydi"
    assert d["bundle_dir"] == BUNDLE_SUBDIR, "olingan paket da'vosi ham qolishi kerak"
    assert YOL_QAYDI in xato_kodlari(natija.result_dir), \
        "paketli yo'l NEGA urinilmagani yozuvdan TUSHIB QOLMAYDI"
    assert set(bridge.WATCH_FOLDER_OPERATOR_STEPS) <= set(d["notes"]), \
        "operator qadamlari yozuvda QOLADI (brief §7)"
    assert agent_ui.CODE_HISOBOT_QISQARTIRILDI in xato_kodlari(natija.result_dir), \
        "hisobotning qayta qurilgani JIM bo'lmaydi — sabab yozuvda turadi"

    # ── HISOBOT: da'vo YO'Q, lekin YO'L va ARALASHUV BOR ──────────────────────────────
    matn = hisobot(natija.result_dir)
    assert avtomatlashtirish_davosi(matn) == [], \
        "yetkazilgan hisobotda AVTOMATLASHTIRISH da'vosi QOLMAYDI"
    bolim = yol_bolimi(matn)
    assert f"`{ROUTE_WATCH_FOLDER}`" in bolim and reporter.NOT_RECORDED not in bolim, \
        "«Ishlatilgan yo'l: qayd etilmagan — bu NUQSON» AYNAN shu nuqson edi"
    assert reporter.INTERVENTION_BY_ROUTE[ROUTE_WATCH_FOLDER] in bolim
    assert reporter.NO_AUTOMATION_LINE in matn, "inkor satri OCHIQ turadi"


def test_L2_YOL_YOZILMAGAN_hisobotda_ham_taqiqlangan_ibora_CHIQMAYDI(tmp_path):
    """⚠️⚠️ IKKINCHI OQIBAT: darvoza `route is None` da ERTA qaytardi.

    Shu bois `route` yo'qolgan OXIRGI hisobotda taqiqlangan ibora BARIBIR yozilib ketar va
    paket `check_result_package` dan TOZA o'tar edi — ya'ni ma'lumot yo'qolishi haqqoniylik
    darvozasini ham O'CHIRARDI. ENDI darvoza FAIL-CLOSED: «yo'lni bilmayman» RUXSATGA
    aylanmaydi.

    ⚠️ IKKI TOMON O'LCHANADI: (1) yo'lsiz yozuvda darvoza URADI, (2) ANIQ `batch_execute`
       da esa O'TKAZADI — u yo'lda paketli chaqiruvni agentning O'ZI qurib yurgizishga
       urinadi, demak «avtomatik» so'zi odamning ishini agentga yozib qo'ymaydi.
    """
    yolsiz = stat.new_run("run-20261001T030000Z", now=X.NOW_ISO).with_note(
        "paket paketli yo'l bilan olindi")       # ⚠️ YOLG'ON izoh (tashqi matn naqshi)
    assert yolsiz.route is None, "fikstura yo'lsiz yozuv bermadi — test o'lchamay qoladi"
    with pytest.raises(reporter.ReportError) as xato:
        reporter.build_report(status=yolsiz)

    # ── DARVOZA O'Z XATO MATNINI QAYTA TUTMAYDI (o'z-o'zini yiqitish YO'Q) ────────────
    assert avtomatlashtirish_davosi(str(xato.value)) == [], \
        "xato matni darvozaning O'ZIGA tushsa, darvoza o'ziga qarshi ishlardi"
    assert "satr " in str(xato.value), "tuzatish uchun SATR RAQAMI qolishi kerak"
    assert "paketli_yol_bilan_olindi" in str(xato.value), "NAQSH NOMI ham qoladi"

    # ── ANIQ `batch_execute` da esa izoh HALOL va hisobot QURILADI ────────────────────
    paketli = yolsiz.with_route(ROUTE_BATCH_EXECUTE)
    assert "paketli yo'l bilan olindi" in reporter.build_report(status=paketli), \
        "paketli yo'lda agent ROSTDAN o'zi yurgizadi — darvoza u yerda YOPILMAYDI"


class YakundaBirMartaYiqiladi:
    """`COMPLETE` ko'rsatilganda BIR MARTA istisno tashlaydigan progress kuzatuvchisi.

    ⚠️ NEGA SHU USUL: kutilmagan ichki xatoni quvur TUGAGANDAN keyin yuzaga keltiradi, ya'ni
       oxirgi HAQIQIY yozuv YAKUNLANGAN bo'ladi — `_ichki_xato` ning AYNAN minimal yozuv
       quradigan shoxi. Ikkinchi marta yiqilmaydi, aks holda test cheksiz yiqilishni
       o'lchardi.
    """

    def __init__(self) -> None:
        self.yiqildi = False

    def __call__(self, holat: str) -> None:
        if holat == st.COMPLETE and not self.yiqildi:
            self.yiqildi = True
            raise RuntimeError("sintetik kutilmagan xato: yakunda")


def test_L3_ICHKI_XATO_paketida_YOL_PAKET_va_OLDINGI_xatolar_SAQLANADI(tmp_path):
    """⚠️⚠️ UCHINCHI TOMON: `_ichki_xato` MINIMAL yozuv qurganda MA'LUMOT YO'QOTMAYDI.

    Avval bu shox `route`, `bundle_dir`, artefakt ro'yxati va OLDINGI XATOLARNI TASHLARDI —
    ya'ni ENG MUHIM yiqilishda operatorga yo'li noma'lum, paketi yo'q va sababi yarim yozuv
    qolardi. ENDI ISBOTLANGAN faktlar ko'chiriladi (soxtalashtirish YO'Q: hammasi oldingi
    HAQIQIY yozuvdan keladi), olingan Phase 4 paketi esa paketga ROSTDAN ko'chadi.

    ⚠️ O'TISHLAR ZANJIRI ATAYLAB ko'chirilmaydi (yakunlangan yurish qayta tirilmaydi) va
       yozuvning MINIMALLIGI izohda OCHIQ aytiladi — bu bo'shliq emas, TANLOV.
    """
    kuzatuvchi = YakundaBirMartaYiqiladi()
    manba = X.paket_yoz(tmp_path / "kuzatilgan", M.paket_sog_lom)
    model = X.kutuvchi_agent(tmp_path / "natija", bundle_dir=manba,
                             scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)))
    model.on_progress = kuzatuvchi
    natija = model.start()

    assert kuzatuvchi.yiqildi, "sintetik xato UMUMAN yuzaga kelmadi — test o'lchamay qoldi"
    assert natija.state == st.FAILED_INTERNAL, "nuqson holati YASHIRILMAYDI"
    assert natija.result_dir is not None, "nuqsonda ham UZATILADIGAN papka qoladi"
    yaroqli_paket(natija.result_dir)

    d = yozuv(natija.result_dir)
    assert d["state"] == st.FAILED_INTERNAL
    assert d["route"] == ROUTE_WATCH_FOLDER, "yo'l ISBOTLANGAN fakt — u tashlanmaydi"
    assert d["bundle_dir"] == BUNDLE_SUBDIR, "olingan paket da'vosi QOLADI"
    assert paket_fayllar(natija.result_dir) == set(X.papka_baytlari(manba)), \
        "o'qilgan Phase 4 paketi JIMGINA tashlanmaydi — u paketga ko'chadi"
    assert YOL_QAYDI in xato_kodlari(natija.result_dir) \
        and agent_ui.CODE_ICHKI_XATO in xato_kodlari(natija.result_dir), \
        "OLDINGI xatolar ham, yangi nuqson ham YOZUVDA"
    assert set(bridge.WATCH_FOLDER_OPERATOR_STEPS) <= set(d["notes"])
    assert any("MINIMAL" in n for n in d["notes"]), "yozuvning minimalligi OCHIQ aytiladi"
    assert [t["to"] for t in d["transitions"]] == [st.ENVIRONMENT_SCAN, st.FAILED_INTERNAL], \
        "o'tishlar zanjiri ATAYLAB ko'chirilmaydi (yakunlangan yurish tirilmaydi)"
    # ⚠️ Artefakt ro'yxati `bundle/` ni ham sanaydi — ya'ni da'vo papkaga MOS.
    assert any(n.startswith(f"{BUNDLE_SUBDIR}/") for n in d["artifacts"])
    assert set(d["artifacts"]) == set(X.papka_baytlari(natija.result_dir))

    bolim = yol_bolimi(hisobot(natija.result_dir))
    assert f"`{ROUTE_WATCH_FOLDER}`" in bolim and reporter.NOT_RECORDED not in bolim


def test_L4_ZAHIRA_hisobot_ham_yiqilsa_MINIMAL_matn_bilan_DEGRADATSIYA(tmp_path):
    """⚠️⚠️ ZAHIRA hisobot qurilishi `try` ICHIDA: uning istisnosi butun yurishni AG'DARMAYDI.

    Avval `ui._yakunla` ning oxirgi `build_report` chaqiruvi HIMOYASIZ edi: istisno `_paket`
    dan chiqib `start()` ning umumiy `except` iga tushar va SOG'LOM yurish `FAILED_INTERNAL`
    bo'lardi. Endi u ANIQ, QISQA va TAQIQLANGAN IBORASIZ matn bilan degradatsiya qiladi —
    papka esa BARIBIR yoziladi (hisobotsiz paket uzatilmaydi).

    ⚠️ FIKSTURA: yozuvning O'ZIGA yolg'on izoh qo'yiladi, ya'ni IKKI qurilish ham (to'liq va
       zahira) AYNI darvozada yiqiladi. Shunga quvur orqali erishib bo'lmaydi — ko'prikning
       izohlari ATAYLAB inkor shaklida — lekin darvoza shunga ham tayyor bo'lishi kerak
       (fail-closed qoidasi, `_sirsiz_paket` testidagi AYNI naqsh).
    """
    model = X.kutuvchi_agent(tmp_path / "natija",
                             bundle_dir=X.bosh_papka(tmp_path, "kuzatilgan-bosh"),
                             scan=X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path)))
    # ⚠️ KUTISH BILAN TO'XTAGAN yurish ATAYLAB tanlangan: uning yozuvi paket OLINMAGANINI
    #    da'vo qiladi (`bundle_dir=null`), ya'ni `bundle/` siz paket O'ZI bilan MOS — test
    #    degradatsiyani o'lchaydi, paket shaklining boshqa qoidasini emas.
    assert model.start().state == st.FAILED_TIMEOUT, "fikstura kutish yurishini bermadi"
    yolgonchi = model._oxirgi_yozuv.with_note("paket paketli yo'l bilan olindi")
    with pytest.raises(reporter.ReportError):
        reporter.build_report(status=yolgonchi)     # ⚠️ IKKI qurilish ham yiqilishi ISBOTI

    # ⚠️ IKKINCHI paket BOSHQA ota papkaga yoziladi: vaqt tamg'asi KIRISHDAN va O'ZGARMAS,
    #    ya'ni bir ota papkada ikkinchi yurish nomi BIRINCHISI bilan to'qnashardi.
    model.parent_dir = str(tmp_path / "natija-degradatsiya")
    natija = model._paket(yolgonchi, None, rp.compact_timestamp(X.NOW_ISO), None)

    assert natija.result_dir is not None, "degradatsiya papkani YO'Q QILMAYDI"
    yaroqli_paket(natija.result_dir)
    assert agent_ui.CODE_HISOBOT_DEGRADATSIYA in xato_kodlari(natija.result_dir), \
        "degradatsiya JIM bo'lmaydi — kod yozuvga tushadi"
    matn = hisobot(natija.result_dir)
    assert matn.strip(), "bo'sh hisobot bilan paket uzatilmaydi"
    assert avtomatlashtirish_davosi(matn) == [], "minimal matnda ham DA'VO yo'q"
    assert f"`{ROUTE_WATCH_FOLDER}`" in matn, "minimal matn ham YO'LNI aytadi"
    assert f"{len(yolgonchi.errors) + 1} ta" in matn, \
        "xato matnlari ko'chirilmaydi, lekin SANOQ qoladi («yo'q edi» bilan aralashmaydi)"
    for nom, _raw in reporter.AUTOMATIC_CLAIM_PATTERNS:
        assert nom not in matn, "minimal matn naqsh nomlarini ham ko'chirmaydi"


def test_L5_AVTOMATIK_izohli_yurish_DETERMINISTIK_bayt_beradi(tmp_path):
    """⚠️ Bir xil kirish — AYNAN bir xil bayt, degradatsiya yo'lida HAM.

    ⚠️ NEGA SHU YO'L: zahira hisobot yurish YOZUVIDAN quriladi, ya'ni unga xato matnlari
       tushadi — va aynan shu matnlar bir kun vaqt tamg'asi yoki yo'l bilan «boyitilsa»
       ikki yurish baytda farq qilib ketardi. Taqqoslash IKKI AYRIM papkada bo'ladi: papka
       nomi yo'lga bog'liq EMAS (absolyut yo'l hisobotga yozilmaydi).
    """
    muhit = X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))
    chiqish = []
    for n in ("bir", "ikki"):
        natija = X.kutuvchi_agent(tmp_path / f"natija-{n}",
                                  bundle_dir=X.paket_yoz(tmp_path / f"paket-{n}",
                                                         M.paket_sog_lom),
                                  analyzer=AvtomatikIzohliAnalitik(), scan=muhit).start()
        assert natija.result_dir is not None
        chiqish.append(X.papka_baytlari(natija.result_dir))
    assert chiqish[0] == chiqish[1], "bir xil kirish ikki xil bayt berdi — determinizm buzuq"
