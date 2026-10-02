# -*- coding: utf-8 -*-
"""Agent YADROSI: holat mashinasi (`states.py`) va yurish yozuvi (`status.py`).

⚠️⚠️ BU TESTLAR 1C GA TEGMAYDI va tegishi ham mumkin emas: bu mashinada 1C UMUMAN
     O'RNATILMAGAN (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q, `pywin32` yo'q). Shu
     bois ular MANTIQNI isbotlaydi va integratsiya yo'llari (`batch_execute`,
     `watch_folder`) haqida HECH QANDAY da'vo qilmaydi — ular `RUNTIME-UNKNOWN`.

ISBOTLANADIGAN INVARIANTLAR:
  · 12 normal + 11 yiqilish holati AYNAN shu nomlar bilan; `TRANSITIONS` to'liq;
  · FAIL-CLOSED: ro'yxatda yo'q o'tish ISTISNO, «o'xshash holat» zaxirasi YO'Q;
  · yakuniy holatdan o'tish YO'Q va yakunlangan yurish qayta boshlanmaydi;
  · `UNKNOWN` ≠ `NOT_FOUND`: `FAILED_NO_1C` («1C yo'q» — JAVOB) va
    `FAILED_COLLECTOR_UNAVAILABLE` («1C bor, javob yo'q») ARALASHMAYDI — ma'nolari ham,
    ularga olib boradigan yo'llar ham FARQLI;
  · `read_only` ni `"false"` qilishning YO'LI YO'Q (frozen + xossa + validator);
  · hujjat shakli: noma'lum kalit RAD, tushib qolgan kalit RAD, JSON soni/booleani RAD;
  · sir FAIL-CLOSED to'siladi (parol, ulanish satri, lotin `parol`, fayl yo'li) va nuqson
    matnida qiymatning O'ZI ko'rsatilmaydi;
  · determinizm: bir xil o'tishlar — AYNAN bir xil baytlar.

ATAYLAB SINALMAYDI:
  · 1C ning haqiqiy xulqi va yig'uvchining ishlashi — fikstura ham yo'q, da'vo ham yo'q;
  · muhit skaneri va hisobot matni — ular ALOHIDA modullar.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import json
import pathlib

import pytest

from app.services.discovery_1c import redact as redaction
from app.services.discovery_1c.runtime_bundle import MODE_APPROVED_PROBES, MODE_METADATA_ONLY
from app.services.discovery_agent import ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER, RUN_VERSION
from app.services.discovery_agent import detector as D
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as ss

T0 = "2026-10-01T09:00:00+06:00"
T1 = "2026-10-01T09:00:10+06:00"
T2 = "2026-10-01T09:00:20+06:00"
T3 = "2026-10-01T09:00:30+06:00"

#: Zondsiz, eng qisqa muvaffaqiyatli yo'l.
HAPPY_PATH: tuple[str, ...] = (
    st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY,
    st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS, st.REPORT, st.COMPLETE,
)
#: Zondli (operator tasdiqlagan) yo'l.
PROBE_PATH: tuple[str, ...] = (
    st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK, st.METADATA_DISCOVERY,
    st.VALIDATION, st.GRAPH_BUILD, st.ANALYSIS, st.OPTIONAL_APPROVED_PROBES, st.REVALIDATE,
    st.REPORT, st.COMPLETE,
)


def _walk(path, *, run_id="run-0001", start=T0):
    """Berilgan yo'l bo'ylab yurgan `AgentStatus` (vaqt har qadamda bir soniya o'sadi)."""
    s = ss.new_run(run_id, now=start)
    for i, holat in enumerate(path, start=1):
        s = s.advance(holat, now=f"2026-10-01T09:00:{i:02d}+06:00", note=f"{i}-qadam")
    return s


def _doc(path=HAPPY_PATH):
    """Tekshiruvdan O'TADIGAN hujjat (mutatsiya testlari uchun asos)."""
    return _walk(path).to_doc()


# ══════════════════════════════════════════════════════════════════════════════════════════
# HOLATLAR RO'YXATI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_normal_holatlar_aynan_oniki_va_nomlari_shartnoma_bilan_bir_xil():
    assert st.NORMAL_STATES == (
        "START", "ENVIRONMENT_SCAN", "TARGET_SELECTION", "SAFETY_CHECK", "METADATA_DISCOVERY",
        "VALIDATION", "GRAPH_BUILD", "ANALYSIS", "OPTIONAL_APPROVED_PROBES", "REVALIDATE",
        "REPORT", "COMPLETE",
    )
    assert len(st.NORMAL_STATES) == 12


def test_yiqilish_holatlari_aynan_onbir_va_nomlari_shartnoma_bilan_bir_xil():
    assert set(st.FAILURE_STATES) == {
        "FAILED_NO_1C", "FAILED_NO_TARGET", "FAILED_AUTH_REQUIRED",
        "FAILED_COLLECTOR_UNAVAILABLE", "FAILED_SAFETY", "FAILED_VALIDATION",
        "FAILED_ANALYSIS", "FAILED_REPORT", "FAILED_TIMEOUT", "FAILED_INTERNAL",
        "ABORTED_BY_OPERATOR",
    }
    assert len(st.FAILURE_STATES) == 11


def test_holat_nomi_takrorlanmaydi_va_jami_yigirma_uchta():
    assert len(st.STATES) == 23
    assert len(set(st.STATES)) == 23


def test_terminal_complete_va_hamma_yiqilishdan_iborat():
    assert st.TERMINAL == frozenset(st.FAILURE_STATES) | {st.COMPLETE}
    # ⚠️ Normal oraliq holat yakuniy BO'LMASLIGI kerak: aks holda quvur o'rtada «tugagan»
    #    deb hisoblanib, hisobot yarim yo'ldan yoziladi.
    for holat in st.NORMAL_STATES:
        if holat != st.COMPLETE:
            assert not st.is_terminal(holat)


def test_umumiy_failed_holati_yoq():
    """⚠️ Bitta umumiy `FAILED` operatorga NIMA QILISHNI aytmaydi — shu bois u YO'Q."""
    assert "FAILED" not in st.STATES


# ══════════════════════════════════════════════════════════════════════════════════════════
# O'TISHLAR JADVALI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_transitions_hamma_holatni_qamraydi_va_nishonlari_malum():
    assert set(st.TRANSITIONS) == set(st.STATES)
    for manba, nishonlar in st.TRANSITIONS.items():
        for nishon in nishonlar:
            assert nishon in st.TRANSITIONS, f"{manba} -> {nishon}: noma'lum nishon"
        assert len(set(nishonlar)) == len(nishonlar), f"{manba}: nishon takrorlangan"


def test_yakuniy_holatdan_chiqish_yoq():
    for holat in st.TERMINAL:
        assert st.TRANSITIONS[holat] == ()


def test_har_bir_yakunlanmagan_holatda_uch_umumiy_chiqish_bor():
    """⚠️ Vaqt chegarasi, ichki xato va OPERATOR TO'XTATISHI — har qadamda bo'lishi mumkin."""
    for holat in st.STATES:
        if holat in st.TERMINAL:
            continue
        for chiqish in (st.FAILED_TIMEOUT, st.FAILED_INTERNAL, st.ABORTED_BY_OPERATOR):
            assert st.can_transition(holat, chiqish), f"{holat} -> {chiqish} yo'q"


def test_har_bir_yiqilish_holatiga_kamida_bitta_yol_boradi():
    """⚠️ Yetib bo'lmaydigan yiqilish holati — o'lik kod: u hech qachon ko'rinmaydi."""
    kiradi = {n for nishonlar in st.TRANSITIONS.values() for n in nishonlar}
    for holat in st.FAILURE_STATES:
        assert holat in kiradi, f"{holat} ga olib boradigan o'tish yo'q"


def test_happy_path_toliq_otiladi():
    oldingi = st.START
    for holat in HAPPY_PATH:
        assert st.can_transition(oldingi, holat), f"{oldingi} -> {holat}"
        oldingi = holat
    assert oldingi == st.COMPLETE


def test_zondli_yol_ham_toliq_otiladi():
    oldingi = st.START
    for holat in PROBE_PATH:
        assert st.can_transition(oldingi, holat), f"{oldingi} -> {holat}"
        oldingi = holat
    assert oldingi == st.COMPLETE


def test_zonddan_keyin_qayta_tekshirmasdan_hisobotga_otilmaydi():
    """⚠️ Zond paketni O'ZGARTIRADI, demak qayta tekshiruv MAJBURIY."""
    assert st.can_transition(st.OPTIONAL_APPROVED_PROBES, st.REVALIDATE)
    assert not st.can_transition(st.OPTIONAL_APPROVED_PROBES, st.REPORT)
    assert not st.can_transition(st.OPTIONAL_APPROVED_PROBES, st.COMPLETE)


def test_xavfsizlik_darvozasini_aylanib_otish_yoli_yoq():
    """⚠️ `SAFETY_CHECK` dan O'TMASDAN metadata yig'ishning yo'li BO'LMASLIGI kerak."""
    for manba, nishonlar in st.TRANSITIONS.items():
        if st.METADATA_DISCOVERY in nishonlar:
            assert manba == st.SAFETY_CHECK, f"{manba} xavfsizlik darvozasini aylanib o'tadi"


#: Ruxsat ETILMAGAN juftliklar (sakkiztadan ko'p). Har biri — haqiqiy xato shakli.
NOTO_GRI_JUFTLIKLAR = (
    (st.START, st.METADATA_DISCOVERY),          # skanersiz to'g'ridan yig'ish
    (st.START, st.COMPLETE),                    # hech narsa qilmasdan «tugadi»
    (st.ENVIRONMENT_SCAN, st.REPORT),           # tahlilsiz hisobot
    (st.TARGET_SELECTION, st.METADATA_DISCOVERY),   # xavfsizlik darvozasini aylanib o'tish
    (st.SAFETY_CHECK, st.VALIDATION),           # yig'masdan tekshirish
    (st.VALIDATION, st.REPORT),                 # grafsiz/tahlilsiz hisobot
    (st.GRAPH_BUILD, st.OPTIONAL_APPROVED_PROBES),  # tahlilsiz zond
    (st.ANALYSIS, st.COMPLETE),                 # hisobotsiz yakun
    (st.REPORT, st.ANALYSIS),                   # orqaga qaytish
    (st.REVALIDATE, st.OPTIONAL_APPROVED_PROBES),   # qayta tekshiruvdan keyin yana zond
    (st.ENVIRONMENT_SCAN, st.FAILED_COLLECTOR_UNAVAILABLE),  # UNKNOWN ≠ NOT_FOUND
    (st.METADATA_DISCOVERY, st.FAILED_NO_1C),   # UNKNOWN ≠ NOT_FOUND (teskari tomoni)
)


@pytest.mark.parametrize("manba,nishon", NOTO_GRI_JUFTLIKLAR)
def test_ruxsat_etilmagan_otish_istisno(manba, nishon):
    assert not st.can_transition(manba, nishon)
    with pytest.raises(st.TransitionError):
        st.assert_transition(manba, nishon)


@pytest.mark.parametrize("holat", sorted(st.TERMINAL))
def test_yakuniy_holatdan_hech_qayerga_otilmaydi(holat):
    for nishon in st.STATES:
        assert not st.can_transition(holat, nishon)
        with pytest.raises(st.TransitionError, match="YAKUNIY"):
            st.assert_transition(holat, nishon)


@pytest.mark.parametrize("nom", ["", "FAILED", "failed_no_1c", "DONE", "START ", "UNKNOWN",
                                "NOT_FOUND", None, 7])
def test_nomalum_holat_nomi_istisno(nom):
    """⚠️ Noma'lum nom `False` BERMAYDI: «bilmadim» ni «yo'q» deb aytish eng qimmat xato."""
    assert not st.is_known(nom)
    with pytest.raises(st.TransitionError):
        st.is_failure(nom)
    with pytest.raises(st.TransitionError):
        st.can_transition(st.START, nom)
    with pytest.raises(st.TransitionError):
        st.can_transition(nom, st.START)


def test_is_failure_va_is_operator_abort():
    assert st.is_failure(st.FAILED_NO_1C)
    assert st.is_failure(st.ABORTED_BY_OPERATOR)
    assert not st.is_failure(st.COMPLETE)
    assert not st.is_failure(st.ANALYSIS)
    # ⚠️ Operator to'xtatishi muvaffaqiyat EMAS, lekin AYB ham emas — ajrim saqlanadi.
    assert st.is_operator_abort(st.ABORTED_BY_OPERATOR)
    assert not st.is_operator_abort(st.FAILED_INTERNAL)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YIQILISH MA'NOLARI — `UNKNOWN` ≠ `NOT_FOUND`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_har_bir_yiqilish_holati_uchun_mano_bor_va_takrorlanmaydi():
    assert set(st.FAILURE_MEANING) == set(st.FAILURE_STATES)
    matnlar = list(st.FAILURE_MEANING.values())
    assert len(set(matnlar)) == len(matnlar), "ikki yiqilish bir xil matn bilan izohlangan"
    for holat, matn in st.FAILURE_MEANING.items():
        assert len(matn) > 80, f"{holat}: ma'no juda qisqa"
        # ⚠️ Matnda KEYINGI QADAM bo'lishi SHART: faqat «nima bo'ldi» yozilgan xabar
        #    operatorni qo'ng'iroq qilishga majbur qiladi.
        assert "Keyingi qadam" in matn, f"{holat}: keyingi qadam yozilmagan"


def test_no_1c_va_collector_unavailable_manolari_farqli():
    """⚠️ «1C topilmadi» (JAVOB) va «1C bor, lekin o'qiy olmadim» (javob YO'Q) — ALOHIDA."""
    yoq = st.failure_meaning(st.FAILED_NO_1C)
    yigolmadi = st.failure_meaning(st.FAILED_COLLECTOR_UNAVAILABLE)
    assert yoq != yigolmadi
    assert "O'RNATILMAGAN" in yoq
    assert "O'RNATILMAGAN" not in yigolmadi
    assert "1C BOR" in yigolmadi
    assert "javob YO'Q" in yigolmadi
    # Holatlar ham, ularga olib boradigan yo'llar ham qo'shilib ketmagan.
    assert st.FAILED_NO_1C != st.FAILED_COLLECTOR_UNAVAILABLE
    assert st.can_transition(st.ENVIRONMENT_SCAN, st.FAILED_NO_1C)
    assert not st.can_transition(st.ENVIRONMENT_SCAN, st.FAILED_COLLECTOR_UNAVAILABLE)
    assert st.can_transition(st.METADATA_DISCOVERY, st.FAILED_COLLECTOR_UNAVAILABLE)
    assert not st.can_transition(st.METADATA_DISCOVERY, st.FAILED_NO_1C)


def test_auth_required_manosi_watch_folder_yolini_taklif_qiladi():
    """⚠️ Parol buyruq satriga QO'YILMAYDI — operatorga ZAXIRA yo'l ko'rsatilishi SHART."""
    matn = st.failure_meaning(st.FAILED_AUTH_REQUIRED)
    assert ROUTE_WATCH_FOLDER in matn


def test_presence_verdict_FAILED_NO_1C_manosini_UCHGA_ajratadi():
    """⚠️⚠️ `absent` va `unknown` BOSHQA matn: «qaradim va yo'q» (JAVOB) bilan «qaray
    olmadim» (javob YO'Q) ni bitta matnga qo'shish `UNKNOWN` ni `NOT_FOUND` ga aylantiradi.

    ⚠️ `unknown` matnida «o'rnatilmagan» degan XULOSA bo'lmasligi SHART, va «Bu JAVOB,
       taxmin emas» iborasi ham FAQAT `absent` da haqli.
    """
    yoq = st.failure_meaning(st.FAILED_NO_1C, presence_verdict=D.PRESENCE_ABSENT)
    bilmadim = st.failure_meaning(st.FAILED_NO_1C, presence_verdict=D.PRESENCE_UNKNOWN)
    topildi = st.failure_meaning(st.FAILED_NO_1C, presence_verdict=D.PRESENCE_FOUND)
    assert len({yoq, bilmadim, topildi}) == 3, "uch hukm UCH XIL matn beradi"

    assert "O'RNATILMAGAN" in yoq and "Bu JAVOB, taxmin emas" in yoq
    assert "ANIQLAB BO'LMADI" in bilmadim
    assert "Bu JAVOB, taxmin emas" not in bilmadim
    assert "XULOSA" in bilmadim and "CHIQARILMAYDI" in bilmadim
    # ⚠️ «topildi», lekin `FAILED_NO_1C` — bu ZIDDIYAT va u OCHIQ aytiladi, jimgina
    #    «qulay» matnga aylanmaydi.
    assert "ZIDDIYAT" in topildi
    for matn in (yoq, bilmadim, topildi):
        assert "Keyingi qadam" in matn and len(matn) > 80
        assert redaction.scan({"note": matn}) == [], "ma'no matnida shubhali qiymat"


def test_presence_verdict_berilmasa_ISBOTLANGAN_yoqlik_DAVO_QILINMAYDI():
    """⚠️ Hukm BERILMAGANDA matn «1C o'rnatilmagan, bu JAVOB» deb DA'VO QILMAYDI."""
    matn = st.failure_meaning(st.FAILED_NO_1C)
    assert "Bu JAVOB, taxmin emas" not in matn
    assert "presence_verdict" in matn, "operator hukmni QAYERDAN o'qishini bilishi kerak"


@pytest.mark.parametrize("qiymat", ["", "FOUND", "yoq", "not_found", "true", "none", 7])
def test_nomalum_presence_verdict_ISTISNO(qiymat):
    """⚠️ FAIL-CLOSED: noma'lum verdikt jimgina «absent» ga aylanmaydi."""
    with pytest.raises(st.TransitionError):
        st.failure_meaning(st.FAILED_NO_1C, presence_verdict=qiymat)


def test_boshqa_yiqilishlarda_verdikt_matnni_OZGARTIRMAYDI():
    """⚠️ Verdikt faqat 1C MAVJUDLIGI hukmiga tegishli — boshqa sabablar unga bog'liq emas."""
    for holat in (st.FAILED_VALIDATION, st.FAILED_SAFETY, st.ABORTED_BY_OPERATOR):
        asos = st.failure_meaning(holat)
        for verdikt in (D.PRESENCE_ABSENT, D.PRESENCE_FOUND, D.PRESENCE_UNKNOWN):
            assert st.failure_meaning(holat, presence_verdict=verdikt) == asos


def test_yozuvda_presence_verdict_YOPIQ_lugat():
    """`agent_status.json` ning 17-kaliti: qiymatlar `detector.PRESENCE_*` dan, boshqasi RAD."""
    assert "presence_verdict" in ss.AGENT_STATUS_KEYS
    assert set(ss.PRESENCE_VERDICTS) == {D.PRESENCE_ABSENT, D.PRESENCE_FOUND,
                                         D.PRESENCE_UNKNOWN}
    # ⚠️ DEFAULT — `unknown`: skanerdan OLDIN «yo'q» deb aytish mumkin emas.
    s = ss.new_run("run-0001", now=T0)
    assert s.presence_verdict == D.PRESENCE_UNKNOWN
    assert json.loads(s.to_json())["presence_verdict"] == D.PRESENCE_UNKNOWN

    yangi = s.with_presence_verdict(D.PRESENCE_ABSENT)
    assert yangi.presence_verdict == D.PRESENCE_ABSENT
    assert s.presence_verdict == D.PRESENCE_UNKNOWN, "yozuv O'ZGARMAS (frozen)"
    with pytest.raises(ss.AgentStatusError):
        s.with_presence_verdict("not_found")


@pytest.mark.parametrize("qiymat", [None, "", "FOUND", "not_found", "yoq", True, 1])
def test_hujjatda_nomalum_presence_verdict_RAD(qiymat):
    doc = _doc()
    doc["presence_verdict"] = qiymat
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


def test_yiqilish_bolmagan_holat_uchun_mano_sorash_istisno():
    for holat in (st.START, st.ANALYSIS, st.COMPLETE):
        with pytest.raises(st.TransitionError):
            st.failure_meaning(holat)


def test_yiqilish_manolarida_sir_yoq():
    """⚠️ Bu matnlar `notes` ga tushishi mumkin — o'zida sir bo'lsa chiqish BLOKLANARDI."""
    for holat, matn in st.FAILURE_MEANING.items():
        assert redaction.scan({"note": matn}) == [], f"{holat}: ma'no matnida shubhali qiymat"


# ══════════════════════════════════════════════════════════════════════════════════════════
# `ABORTED_BY_OPERATOR` — LUG'ATDA BOR va SHIPPED KODDA ENDI ISHLATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ BU BO'LIM AKSIGA AYLANTIRILDI (O'CHIRILMADI, YUMSHATILMADI). Ilgari u «holat
#      e'lon qilingan, lekin uni YOZADIGAN kod YO'Q» da'vosini qulflardi va bu HAQIQAT
#      edi. ENDI `launcher.py` + `one_click.py` bekor qilishni ROSTDAN amalga oshiradi
#      (`launcher.CancelToken` + `launcher.wait_for_collector`, `one_click.run_one_click`
#      ga `cancel=...`), ya'ni holat SHIPPED yo'lda YOZILADI.
# ⚠️⚠️ QO'RIQCHINING MA'NOSI SAQLANDI, FAQAT YO'NALISHI TESKARI. U hamon AYNAN BIR
#      nuqsonni tutadi: «E'LON QILINGAN, LEKIN YETIB BO'LMAYDIGAN QOBILIYAT». Oldin
#      nuqson «hujjat ishlatiladi deydi, kod ishlatmaydi» ko'rinishida edi; endi u
#      «kod ishlatadi, hujjat esa ISHLATILMAYDI deb yozib turadi» ko'rinishida — ikkisi
#      ham paketni O'ZI HAQIDA YOLG'ON yozishga olib keladi va ikkisi ham operatorni
#      boshqa yo'lga yuboradi.
# ⚠️ BU TEST YANGI QOBILIYAT TALAB QILMAYDI va YANGI HOLAT QO'SHMAYDI: `FAILURE_STATES`
#    11 ta, `NORMAL_STATES` 12 ta bo'lib qoladi (pastdagi `..._orni_OZGARMAYDI` testi).
#: Agentning SHIPPED modullari — `states.py` ning O'ZIDAN tashqari: holat AYNAN shu faylda
#: e'lon qilinadi va `_ANY_EXIT`, `TRANSITIONS`, `FAILURE_MEANING` ham shu yerda, ya'ni u
#: «ishlatuvchi» emas, E'LON QILUVCHI.
SHIPPED_MODULLAR: tuple[pathlib.Path, ...] = tuple(sorted(
    f for f in pathlib.Path(st.__file__).parent.glob("*.py") if f.name != "states.py"))

#: Holatning O'ZI — shipped kodda ISHLATILISHI SHART bo'lgan nom.
ABORT_HOLATI = "ABORTED_BY_OPERATOR"

#: ⚠️ `is_operator_abort()` ALOHIDA o'lchanadi va u HAMON CHAQIRILMAYDI. Holat yozilsa ham
#: uni SO'RAYDIGAN yo'l qurilmagan — ya'ni qo'riqchining ASL ma'nosi (e'lon qilingan,
#: yetib bo'lmaydigan qobiliyat) shu NOM uchun kuchda QOLADI.
ABORT_SOROVI = "is_operator_abort"

#: Eski nom — mavjud chaqiruvchilar (fikstura) uchun saqlanadi va ikki nomning yig'indisi.
ABORT_NOMLARI: tuple[str, ...] = (ABORT_HOLATI, ABORT_SOROVI)


def _kod_nomlari(fayl: pathlib.Path) -> set[str]:
    """Fayl KODIDAGI identifikatorlar va MATN konstantalari (`X`, `obj.X`, `"X"`).

    ⚠️ IZOH va DOCSTRING hisobga OLINMAYDI va bu ataylab: `__main__.py` holat nomini
       docstringda eslatadi (chiqish kodlarini tushuntirib), lekin matnda ESLATISH holatni
       ISHLATISH degani emas. Oddiy matn qidiruvi (`grep`) bu ajrimni qila olmasdi.
    ⚠️ MATN konstantasi esa HISOBGA OLINADI: `advance("ABORTED_BY_OPERATOR")` nomni
       import qilmasdan ham holatni YOZISHI mumkin — docstring ichidagi matn esa
       `ast.Expr` bo'lib qolgani uchun pastda ALOHIDA tashlab yuboriladi.
    """
    daraxt = ast.parse(fayl.read_text("utf-8"), filename=str(fayl))
    # ⚠️ Docstring tugunlari (modul/klass/funksiya) OLIB TASHLANADI: ular MATN, kod emas.
    docstringlar = set()
    for tugun in ast.walk(daraxt):
        if isinstance(tugun, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            birinchi = tugun.body[0] if tugun.body else None
            if (isinstance(birinchi, ast.Expr) and isinstance(birinchi.value, ast.Constant)
                    and isinstance(birinchi.value.value, str)):
                docstringlar.add(id(birinchi.value))
    nomlar: set[str] = set()
    for tugun in ast.walk(daraxt):
        if isinstance(tugun, ast.Name):
            nomlar.add(tugun.id)
        elif isinstance(tugun, ast.Attribute):
            nomlar.add(tugun.attr)
        elif (isinstance(tugun, ast.Constant) and isinstance(tugun.value, str)
                and id(tugun) not in docstringlar):
            nomlar.add(tugun.value)
    return nomlar


def test_ABORTED_BY_OPERATOR_shipped_kodda_ISHLATILADI_va_hujjat_shuni_AYTADI():
    """⚠️⚠️ DA'VO QULFI (AKSIGA AYLANTIRILGAN): holat e'lon qilingan VA uni YOZADIGAN kod
         ENDI BOR — hujjat ham AYNAN shuni aytishi SHART.

    `launcher.py` bekor qilishni ROSTDAN amalga oshiradi: `CancelToken` qo'yiladi,
    `wait_for_collector` kutishni to'xtatadi va natija `OPERATOR_CANCELLED` kodi bilan
    `ABORTED_BY_OPERATOR` holatiga tushadi; `one_click.run_one_click(cancel=...)` uni
    oqimga uzatadi. Ya'ni «holatni yozadigan kod YO'Q» da'vosi ENDI ESKIRGAN.

    ⚠️⚠️ BEKOR QILISH KOOPERATIV: agent KUTISHNI to'xtatadi, 1C oynasini esa operator O'ZI
         yopadi. Jarayonni KENG O'LDIRISH (`taskkill`, jarayon daraxtini tugatish) YO'Q va
         bu test bunday qobiliyatni TALAB QILMAYDI.

    ⚠️ QO'RIQCHINING MA'NOSI O'ZGARMADI, YO'NALISHI TESKARI. U hamon «E'LON QILINGAN,
       LEKIN YETIB BO'LMAYDIGAN QOBILIYAT» nuqsonini tutadi va IKKI TOMONGA ishlaydi:
         · kimdir bekor qilish yo'lini OLIB TASHLASA — test QIZIL bo'ladi, chunki holat
           yana «yozilmaydigan» bo'lib qoladi va hujjat buni aytishi kerak bo'ladi;
         · hujjat kodga ZID qolsa (hali «ISHLATILMAYDI» deb yozilgan bo'lsa) — test
           QIZIL, chunki paket O'ZI HAQIDA YOLG'ON yozadi.
    """
    assert SHIPPED_MODULLAR, "fikstura: shipped modullar topilmadi"
    ishlatganlar = sorted(f.name for f in SHIPPED_MODULLAR
                          if ABORT_HOLATI in _kod_nomlari(f))
    assert ishlatganlar, (
        f"`{ABORT_HOLATI}` shipped kodda UMUMAN ishlatilmayapti — bekor qilish yo'li "
        f"(`launcher.CancelToken` + `launcher.wait_for_collector`, "
        f"`one_click.run_one_click(cancel=...)`) OLIB TASHLANGANMI? Agar ATAYLAB bo'lsa, "
        f"holat yana FAQAT E'LON bo'lib qoladi va `states.py` hujjati buni OCHIQ aytishi "
        f"SHART — aks holda paket yetib bo'lmaydigan qobiliyatni e'lon qiladi")

    #: ⚠️ ASL QO'RIQCHI SHU NOM UCHUN KUCHDA QOLADI: holat yozilsa ham, uni SO'RAYDIGAN
    #:    yo'l (`is_operator_abort()`) hamon QURILMAGAN. Chaqiruv paydo bo'lsa — bu
    #:    YAXSHI, lekin u holda hujjat ham, bu pin ham yangilanishi SHART.
    sorovni_chaqirganlar = sorted(f.name for f in SHIPPED_MODULLAR
                                  if ABORT_SOROVI in _kod_nomlari(f))
    assert sorovni_chaqirganlar == [], (
        f"`{ABORT_SOROVI}()` ENDI chaqirilyapti: {sorovni_chaqirganlar}. Bu YAXSHI "
        f"o'zgarish, lekin u BIR O'ZI o'tmaydi: `states.py` dagi «hech qaerdan "
        f"CHAQIRILMAYDI» qaydi va shu pin BIR VAQTDA tuzatilsin")

    # ── HUJJAT KOD BILAN MOS BO'LISHI SHART ───────────────────────────────────────────────
    # ⚠️⚠️ BU YERDA TEST HOZIR QIZIL BO'LADI va bu ATAYLAB: `states.py` hali ESKI da'voni
    #      yozib turadi, lekin u BU AGENTGA BERILMAGAN fayl. Xato matni aynan nimani
    #      o'zgartirish kerakligini AYTADI — yumshatish TAQIQLANGAN.
    hujjat = st.__doc__ or ""
    assert ABORT_HOLATI in hujjat, \
        "modul docstringi holatni OCHIQ eslatishi SHART"
    assert "ISHLATILMAYDI" not in hujjat, (
        f"`states.py` MODUL DOCSTRINGI hamon «{ABORT_HOLATI} — LUG'ATDA BOR, SHIPPED "
        f"KODDA ISHLATILMAYDI» deb yozib turadi, lekin holat {ishlatganlar} da ROSTDAN "
        f"yozilyapti.\n"
        f"⚠️ SO'ROV (`states.py` EGASIGA — bu fayl shu agentga berilmagan):\n"
        f"   1. MODUL DOCSTRINGI: «LUG'ATDA BOR, SHIPPED KODDA ISHLATILMAYDI» bandini "
        f"«LUG'ATDA BOR va SHIPPED KODDA ISHLATILADI» ga aylantirib, bekor qilish "
        f"yo'lini nomlab bering: `launcher.CancelToken` + `launcher.wait_for_collector` "
        f"+ `one_click.run_one_click(cancel=...)`, holat `OPERATOR_CANCELLED` kodi bilan "
        f"yoziladi. «`ui.py`/`pipeline.py`/`collector_bridge.py`/`status.py` bu nomni "
        f"UMUMAN ishlatmaydi» gapi HAMON to'g'ri — uni saqlab qolish mumkin.\n"
        f"   2. `is_operator_abort()` haqidagi «hech qaerdan CHAQIRILMAYDI» qaydi HAMON "
        f"HAQIQAT — uni O'ZGARTIRMANG.\n"
        f"   3. Bekor qilish KOOPERATIV ekanini yozib qo'ying: agent KUTISHNI to'xtatadi, "
        f"1C oynasini operator O'ZI yopadi; jarayon MAJBURAN tugatilmaydi.\n"
        f"   4. `FAILURE_STATES` (11) va `NORMAL_STATES` (12) izohlariga TEGMANG — yangi "
        f"holat QO'SHILMAYDI.")

    matn = st.FAILURE_MEANING[st.ABORTED_BY_OPERATOR]
    assert "QURILMAGAN" not in matn and "KO'RSATILMAYDI" not in matn, (
        f"`FAILURE_MEANING[{ABORT_HOLATI}]` matni hamon «to'xtatish tugmasi QURILMAGAN» / "
        f"«BU MATN KO'RSATILMAYDI» deb yozadi, lekin holat {ishlatganlar} da yoziladi va "
        f"matn ENDI ROSTDAN operatorga chiqadi.\n"
        f"⚠️ SO'ROV (`states.py` EGASIGA): oxiridagi «SHU RELIZDA BU MATN KO'RSATILMAYDI: "
        f"to'xtatish tugmasi QURILMAGAN va holatni yozadigan kod YO'Q, ya'ni lug'atdagi "
        f"bu yozuv KELAJAK uchun saqlanadi va hozir hech narsani DA'VO QILMAYDI» gapini "
        f"OLIB TASHLANG. Matnning BIRINCHI yarmi («Yurishni OPERATOR to'xtatdi — bu "
        f"nuqson emas... har yurish o'z papkasini oladi») TO'G'RI va u QOLSIN. Uning "
        f"o'rniga bekor qilishning KOOPERATIVLIGINI qo'shish mumkin: 1C oynasini "
        f"operator O'ZI yopadi.\n"
        f"⚠️ `FAILURE_MEANING` dan YOZUVNI O'CHIRMANG va yangi holat QO'SHMANG.")


def test_ABORTED_BY_OPERATOR_SHARTNOMADAGI_orni_OZGARMAYDI():
    """⚠️ Da'voni haqiqatga moslash holatni O'CHIRISH degani EMAS: 11 ta yiqilish, jadvaldagi
       o'rin va ma'no lug'ati AVVALGIDEK qoladi (yangi holat ham QO'SHILMAYDI).
    """
    assert st.ABORTED_BY_OPERATOR in st.FAILURE_STATES and len(st.FAILURE_STATES) == 11
    assert st.ABORTED_BY_OPERATOR in st.TERMINAL
    assert st.TRANSITIONS[st.ABORTED_BY_OPERATOR] == ()
    assert st.ABORTED_BY_OPERATOR in st.FAILURE_MEANING
    for manba, nishonlar in st.TRANSITIONS.items():
        if manba not in st.TERMINAL:
            assert st.ABORTED_BY_OPERATOR in nishonlar, manba


# ══════════════════════════════════════════════════════════════════════════════════════════
# `AgentStatus` — o'tishlarni QAYD ETADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_yangi_yurish_start_holatida_va_otishi_yoq():
    s = ss.new_run("run-0001", now=T0)
    assert s.state == st.START
    assert s.transitions == ()
    assert s.terminal == "false"
    assert s.finished_at is None
    ss.validate_agent_status(s.to_doc())


def test_otish_qayd_etiladi_va_zanjir_uziladi_emas():
    s = _walk(HAPPY_PATH)
    assert s.state == st.COMPLETE
    assert len(s.transitions) == len(HAPPY_PATH)
    assert s.transitions[0].from_state == st.START
    for oldingi, keyingi in zip(s.transitions, s.transitions[1:]):
        assert oldingi.to_state == keyingi.from_state
    assert s.transitions[-1].to_state == st.COMPLETE
    assert s.terminal == "true"
    # ⚠️ Yakunda tugash vaqti BOR.
    assert s.finished_at == s.transitions[-1].at
    ss.validate_agent_status(s.to_doc())


def test_ruxsat_etilmagan_otish_statusda_ham_rad():
    s = ss.new_run("run-0001", now=T0)
    with pytest.raises(ss.AgentStatusError):
        s.advance(st.COMPLETE, now=T1)
    # ⚠️ Nusxa O'ZGARMADI: muvaffaqiyatsiz urinish yozuvni buzmaydi.
    assert s.state == st.START and s.transitions == ()


def test_yakuniy_holatdan_keyin_davom_etish_rad():
    s = _walk((st.ENVIRONMENT_SCAN, st.FAILED_NO_1C))
    with pytest.raises(ss.AgentStatusError, match="YAKUNIY"):
        s.advance(st.TARGET_SELECTION, now=T3)


def test_vaqt_kirishdan_keladi_va_orqaga_ketmaydi():
    s = ss.new_run("run-0001", now=T2)
    s = s.advance(st.ENVIRONMENT_SCAN, now=T3)
    doc = s.advance(st.TARGET_SELECTION, now=T3).to_doc()
    ss.validate_agent_status(doc)                 # teng vaqt — mumkin
    doc["transitions"][1]["at"] = T0              # orqaga ketdi — RAD
    with pytest.raises(ss.AgentStatusError, match="ORQAGA"):
        ss.validate_agent_status(doc)


def test_notogri_vaqt_tamgasi_rad():
    with pytest.raises(ss.AgentStatusError):
        ss.new_run("run-0001", now="2026-10-01 09:00:00")       # offsetsiz
    s = ss.new_run("run-0001", now=T0)
    with pytest.raises(ss.AgentStatusError):
        s.advance(st.ENVIRONMENT_SCAN, now="hozir")


# ══════════════════════════════════════════════════════════════════════════════════════════
# `read_only` — O'ZGARTIRISHNING YO'LI YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_read_only_doim_true_va_hamma_holatda_shunday():
    for holat in (st.START,) + HAPPY_PATH:
        s = _walk(HAPPY_PATH[:HAPPY_PATH.index(holat) + 1] if holat in HAPPY_PATH else ())
        assert s.read_only == "true"
        assert s.to_doc()["read_only"] == "true"


def test_read_only_ni_ozgartirish_imkonsiz():
    s = ss.new_run("run-0001", now=T0)
    # (1) frozen dataclass — `setattr` YO'Q.
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.read_only = "false"
    # (2) `read_only` MAYDON emas, XOSSA — `replace()` uni bilmaydi.
    assert "read_only" not in {f.name for f in dataclasses.fields(s)}
    with pytest.raises(TypeError):
        dataclasses.replace(s, read_only="false")
    # (3) qurilmada ham yo'q.
    with pytest.raises(TypeError):
        ss.AgentStatus(run_id="run-0001", started_at=T0, read_only="false")


@pytest.mark.parametrize("qiymat", ["false", "FALSE", True, False, "unknown", "", None])
def test_hujjatda_read_only_true_dan_boshqa_qiymat_rad(qiymat):
    doc = _doc()
    doc["read_only"] = qiymat
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


# ══════════════════════════════════════════════════════════════════════════════════════════
# HUJJAT SHAKLI — `binos-agent-run-v1`
# ══════════════════════════════════════════════════════════════════════════════════════════
#: `status.py` docstringi kalitlar sonini SO'Z bilan aytadi; bu lug'at uni SONGA aylantiradi.
#: ⚠️⚠️ NEGA KERAK: docstring allaqachon «AYNAN o'n yettita» deb yozgan edi, `AGENT_STATUS_KEYS`
#:    da esa 16 kalit turardi — ya'ni DA'VO XATO edi va uni hech narsa tekshirmasdi.
#:    `presence_verdict` qo'shilishi bilan da'vo TO'G'RI bo'ldi, lekin «to'g'ri bo'lib qoldi»
#:    yetarli emas: sanoq KOD bilan qulflanadi, aks holda keyingi kalit yana jimgina
#:    ajralib ketardi.
SANOQ_SOZLARI: dict[str, int] = {
    "o'n beshta": 15, "o'n oltita": 16, "o'n yettita": 17, "o'n sakkizta": 18,
    "o'n to'qqizta": 19, "yigirmata": 20,
}


def test_hujjat_kalitlari_aynan_shartnomadagidek():
    assert set(_doc()) == set(ss.AGENT_STATUS_KEYS)
    assert len(ss.AGENT_STATUS_KEYS) == 17


def test_docstringdagi_kalit_sanogi_KOD_bilan_mos():
    """⚠️ Hujjatdagi SANOQ da'vosi lug'atning haqiqiy uzunligiga teng bo'lishi SHART."""
    topilgan = sorted({son for soz, son in SANOQ_SOZLARI.items() if soz in ss.__doc__})
    assert len(topilgan) == 1, f"docstring sanoq da'vosi aniq emas: {topilgan}"
    assert topilgan[0] == len(ss.AGENT_STATUS_KEYS),         "docstring kalitlar sonini XATO aytadi — da'vo kod bilan mos emas"


def test_nomalum_kalit_rad():
    doc = _doc()
    doc["schema_version"] = RUN_VERSION          # «aniqroq bo'lsin» deb qo'shilgan maydon
    with pytest.raises(ss.AgentStatusError, match="noma'lum kalit"):
        ss.validate_agent_status(doc)


@pytest.mark.parametrize("kalit", sorted(ss.AGENT_STATUS_KEYS))
def test_tushib_qolgan_kalit_rad(kalit):
    doc = _doc()
    del doc[kalit]
    with pytest.raises(ss.AgentStatusError, match="yetishmayapti"):
        ss.validate_agent_status(doc)


@pytest.mark.parametrize("yol,qiymat", [
    (("probes",), [{"no": 1, "probe_type": "object_attributes", "target_object": "Spr.A",
                    "reason": "sabab", "file": "bundle/probes/01_object_attributes.json",
                    "status": "EXECUTED"}]),
    (("terminal",), True),
    (("notes",), ["izoh", 7]),
    (("run_id",), 1),
])
def test_json_soni_va_booleani_rad(yol, qiymat):
    """⚠️ Sanoq MATN: `0000123` soni `123` bo'lib qoladi. Boolean uchinchi holatni yo'q qiladi.

    ⚠️ Xato matni ham qulflanadi: son/boolean UMUMIY darvozada, maydon tekshiruvidan OLDIN
       tutilishi kerak. Faqat maydon tekshiruvi ishlasa, kelajakda qo'shilgan YANGI maydon
       (hali o'z tekshiruvi yo'q) son bilan jimgina o'tib ketardi.
    """
    doc = _doc()
    doc[yol[0]] = qiymat
    with pytest.raises(ss.AgentStatusError, match="JSON soni"):
        ss.validate_agent_status(doc)


def test_terminal_holatdan_hisoblanadi_elon_qilinmaydi():
    doc = _doc()
    doc["terminal"] = "false"                    # holat `COMPLETE`, ya'ni zid
    with pytest.raises(ss.AgentStatusError, match="terminal"):
        ss.validate_agent_status(doc)


def test_yakunlanmagan_yurishda_tugash_vaqti_yoq_yakunlanganida_bor():
    yarim = _walk(HAPPY_PATH[:3]).to_doc()
    ss.validate_agent_status(yarim)
    yarim["finished_at"] = T3
    with pytest.raises(ss.AgentStatusError, match="finished_at"):
        ss.validate_agent_status(yarim)
    tugagan = _doc()
    tugagan["finished_at"] = None
    with pytest.raises(ss.AgentStatusError, match="finished_at"):
        ss.validate_agent_status(tugagan)


def test_otish_zanjiri_uzilsa_rad():
    doc = _doc()
    doc["transitions"] = doc["transitions"][1:]   # birinchi qadam yo'q qilindi
    with pytest.raises(ss.AgentStatusError, match="zanjirni uzdi"):
        ss.validate_agent_status(doc)


def test_hujjatdagi_ruxsat_etilmagan_otish_rad():
    doc = _doc()
    doc["transitions"][1]["to"] = st.REPORT      # TARGET_SELECTION -> REPORT
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


def test_state_oxirgi_otishga_mos_bolmasa_rad():
    doc = _doc()
    doc["state"] = st.REPORT
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


def test_otishsiz_hujjat_faqat_start_holatida_mumkin():
    doc = ss.new_run("run-0001", now=T0).to_doc()
    ss.validate_agent_status(doc)
    doc["state"] = st.ENVIRONMENT_SCAN
    with pytest.raises(ss.AgentStatusError, match="IZSIZ"):
        ss.validate_agent_status(doc)


@pytest.mark.parametrize("qiymat", ["", "run id", "../run", "C:/run", "x" * 65, None])
def test_notogri_run_id_rad(qiymat):
    doc = _doc()
    doc["run_id"] = qiymat
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


@pytest.mark.parametrize("qiymat", ["COM_CONNECT", "unknown_route", "", "batch execute"])
def test_nomalum_route_rad(qiymat):
    doc = _doc()
    doc["route"] = qiymat
    with pytest.raises(ss.AgentStatusError, match="route"):
        ss.validate_agent_status(doc)


def test_ikki_yol_ham_qabul_qilinadi_lekin_dalil_emas():
    """⚠️ `route` — QAYD, DA'VO EMAS: bu mashinada 1C yo'q, ikki yo'l ham RUNTIME-UNKNOWN."""
    for yol in (ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER):
        doc = _walk(HAPPY_PATH).with_route(yol).to_doc()
        ss.validate_agent_status(doc)
        assert doc["route"] == yol


@pytest.mark.parametrize("qiymat", ["C:/binos/agent_status.json", "..\\tashqari.json",
                                    "/etc/passwd", "../bundle/export.json", "",
                                    "bundle\\export.json"])
def test_absolyut_yoki_tashqariga_chiqadigan_yol_rad(qiymat):
    """⚠️ Yo'l NISBIY: absolyut yo'l do'kon mashinasining tuzilmasini oshkor qiladi."""
    doc = _doc()
    doc["bundle_dir"] = qiymat
    with pytest.raises(ss.AgentStatusError):
        ss.validate_agent_status(doc)


def test_artefakt_royxati_tartiblangan_va_takrorsiz():
    s = _walk(HAPPY_PATH).with_artifacts(["discovery_report.md", "environment.json",
                                          "bundle/export.json", "environment.json"])
    doc = s.to_doc()
    assert doc["artifacts"] == ["bundle/export.json", "discovery_report.md", "environment.json"]
    ss.validate_agent_status(doc)
    doc["artifacts"] = ["environment.json", "bundle/export.json"]
    with pytest.raises(ss.AgentStatusError, match="tartiblangan"):
        ss.validate_agent_status(doc)


def test_xato_yozuvi_shakli():
    s = _walk(HAPPY_PATH).with_error("environment", "COM_NOT_REGISTERED",
                                    "COM klassi reestrda yo'q — tekshirib bo'lmadi")
    ss.validate_agent_status(s.to_doc())
    doc = s.to_doc()
    doc["errors"][0]["code"] = "com not registered"
    with pytest.raises(ss.AgentStatusError, match="code"):
        ss.validate_agent_status(doc)


# ══════════════════════════════════════════════════════════════════════════════════════════
# ZONDLAR — faqat `APPROVED_PROBES`
# ══════════════════════════════════════════════════════════════════════════════════════════
def _zond(no="1", turi="object_attributes", status="EXECUTED"):
    return ss.ProbeRecord(no=no, probe_type=turi, target_object="Spravochnik.Nomenklatura",
                          reason="maydon tarkibi bilinmasa gipoteza tekshirilmaydi",
                          file=f"bundle/probes/{no.zfill(2)}_{turi}.json", status=status)


def test_zond_approved_probes_rejimida_qabul_qilinadi():
    s = _walk(PROBE_PATH).with_mode(MODE_APPROVED_PROBES).with_probe(_zond())
    ss.validate_agent_status(s.to_doc())


def test_metadata_only_rejimida_zond_rad():
    """⚠️ `METADATA_ONLY` + zond — o'z-o'ziga ZID hujjat (yadro ham shunday deydi)."""
    s = _walk(PROBE_PATH).with_probe(_zond())
    assert s.mode == MODE_METADATA_ONLY
    with pytest.raises(ss.AgentStatusError, match=MODE_METADATA_ONLY):
        ss.validate_agent_status(s.to_doc())


def test_royxatda_yoq_zond_turi_rad():
    s = _walk(PROBE_PATH).with_mode(MODE_APPROVED_PROBES).with_probe(
        _zond(turi="execute_arbitrary_bsl"))
    with pytest.raises(ss.AgentStatusError, match="allowlist"):
        ss.validate_agent_status(s.to_doc())


def test_zond_raqami_takrorlansa_rad():
    s = (_walk(PROBE_PATH).with_mode(MODE_APPROVED_PROBES)
         .with_probe(_zond(no="1")).with_probe(_zond(no="1", turi="tabular_sections")))
    with pytest.raises(ss.AgentStatusError, match="takrorlangan"):
        ss.validate_agent_status(s.to_doc())


@pytest.mark.parametrize("status", ["ok", "DONE", "", "executed"])
def test_nomalum_zond_statusi_rad(status):
    s = _walk(PROBE_PATH).with_mode(MODE_APPROVED_PROBES).with_probe(_zond(status=status))
    with pytest.raises(ss.AgentStatusError, match="status"):
        ss.validate_agent_status(s.to_doc())


def test_zond_sababsiz_bolmaydi():
    """⚠️ Sababsiz zond — tasdiqlab bo'lmaydigan zond."""
    doc = _walk(PROBE_PATH).with_mode(MODE_APPROVED_PROBES).with_probe(_zond()).to_doc()
    doc["probes"][0]["reason"] = ""
    with pytest.raises(ss.AgentStatusError, match="reason"):
        ss.validate_agent_status(doc)


def test_nomalum_rejim_rad():
    doc = _doc()
    doc["mode"] = "FULL_ACCESS"
    with pytest.raises(ss.AgentStatusError, match="mode"):
        ss.validate_agent_status(doc)
    with pytest.raises(ss.AgentStatusError):
        ss.new_run("run-0001", now=T0).with_mode("WRITE")


# ══════════════════════════════════════════════════════════════════════════════════════════
# SIR — FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════
SIRLAR = (
    ("notes", ["Пароль базы 12345"]),                                  # kirill parol
    ("notes", ["parol: hunter2"]),                                     # lotin `parol`
    ("notes", ["Srvr=srv1;Ref=buh;Usr=admin;Pwd=hunter2"]),            # ulanish satri
    ("notes", ["token: abc123def"]),                                   # token qiymati bilan
    ("notes", [r"C:\Users\kassir\1Cv8.1CD o'qilmadi"]),               # fayl yo'li
    ("notes", ["AnyDesk: 123 456 789"]),                               # masofaviy kirish
)


@pytest.mark.parametrize("kalit,qiymat", SIRLAR)
def test_sir_topilsa_yozish_rad(kalit, qiymat):
    doc = _doc()
    doc[kalit] = qiymat
    with pytest.raises(ss.AgentStatusError, match="shubhali qiymat"):
        ss.validate_agent_status(doc)


def test_sir_xato_detalida_ham_tutiladi():
    s = _walk(HAPPY_PATH).with_error("collector", "SQL_ERROR",
                                     "baza fayli ochilmadi: C:\\baza\\1Cv8.1CD")
    with pytest.raises(ss.AgentStatusError, match="shubhali qiymat"):
        s.to_json()


def test_sir_nuqson_matnida_qiymatning_ozi_korsatilmaydi():
    """⚠️ Bu xabar jurnalga tushadi, jurnal esa qo'ldan-qo'lga o'tadi."""
    doc = _doc()
    doc["notes"] = ["parol: hunter2"]
    with pytest.raises(ss.AgentStatusError) as e:
        ss.validate_agent_status(doc)
    assert "hunter2" not in str(e.value)
    assert "notes[0]" in str(e.value)


def test_sir_kalit_nomida_ham_tutiladi():
    """⚠️ Sir nomli kalit ostidagi HAMMA narsa shubhali (yadrodagi `redact` qoidasi)."""
    doc = _doc()
    doc["notes"] = ["toza izoh"]
    with pytest.raises(ss.AgentStatusError):
        ss.assert_no_secrets({"password": {"value": "x"}})
    ss.assert_no_secrets(doc)


# ══════════════════════════════════════════════════════════════════════════════════════════
# DETERMINIZM
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_bir_xil_otishlar_bir_xil_bayt():
    a = _walk(HAPPY_PATH).to_json()
    b = _walk(HAPPY_PATH).to_json()
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_otish_tartibi_baytlarda_saqlanadi():
    a = _walk(HAPPY_PATH).to_json()
    b = _walk(PROBE_PATH).to_json()
    assert a != b


def test_json_kalitlari_tartiblangan_va_oxirida_bitta_yangi_satr():
    matn = _walk(HAPPY_PATH).to_json()
    assert matn.endswith("}\n") and not matn.endswith("\n\n")
    yuklandi = json.loads(matn)
    assert list(yuklandi) == sorted(yuklandi)
    # ⚠️ Yurish YOZUVI — vaqt bo'yicha tartib, alfavit EMAS: o'tishlar ro'yxati
    #    tartiblanmaydi, aks holda zanjir ma'nosini yo'qotadi.
    assert [t["to"] for t in yuklandi["transitions"]] == list(HAPPY_PATH)


def test_to_json_tekshirilmagan_hujjat_qaytarmaydi():
    """⚠️ Chiqish YO'LI BITTA: validator va sir skaneridan o'tmagan matn qaytmaydi."""
    s = _walk(HAPPY_PATH)
    buzuq = dataclasses.replace(s, mode="WRITE_EVERYTHING")
    with pytest.raises(ss.AgentStatusError):
        buzuq.to_json()


def test_asl_nusxa_ozgarmaydi():
    """⚠️ Immutability: `advance()` YANGI nusxa beradi, oldingisi JOYIDA qoladi."""
    a = ss.new_run("run-0001", now=T0)
    b = a.advance(st.ENVIRONMENT_SCAN, now=T1)
    assert a.state == st.START and a.transitions == ()
    assert b.state == st.ENVIRONMENT_SCAN and len(b.transitions) == 1
    assert a is not b


def test_hujjat_chuqur_nusxasi_validatordan_otadi():
    """Mutatsiya testlari asosga tegib ketmaganini qulflaydi."""
    doc = _doc()
    ss.validate_agent_status(copy.deepcopy(doc))
    ss.validate_agent_status(doc)
