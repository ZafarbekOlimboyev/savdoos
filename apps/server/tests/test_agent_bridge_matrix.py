# -*- coding: utf-8 -*-
"""A–N SOXTA HARNESS MATRITSASI — ko'prikning 14 ssenariysi.

⚠️⚠️⚠️ BU SOXTA HARNESS. HAQIQIY 1C MUVAFFAQIYATINI ISBOTLAMAYDI.
        Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI, `.epf` BAJARILMAYDI,
        COM ishlatilmaydi, tarmoqqa chiqilmaydi va haqiqiy Windows reestri o'qilmaydi.
        Bu mashinada 1C:Enterprise umuman o'rnatilmagan. «Ishga tushiruvchi» buyruqni
        YOZIB OLADIGAN obyekt, «yig'uvchi» esa papkaga hujjat YOZADIGAN funksiya
        (`tests.agent_bridge_mock`). Yashil to'plam «1C da ishladi» DEGANI EMAS: yig'uvchi
        va avtomatik ishga tushirish yo'lining haqiqiy holati `UNVERIFIED_ON_REAL_1C`
        bo'lib QOLADI.

⚠️⚠️ `.epf` IKKILIK FAYLI QURILGAN DEB AYTILMAYDI: manba matni tayyor
     (`bridge_phase.EPF_SOURCE_READY`), ikkilikni 1C konfiguratorida OPERATOR yig'adi.

BU FAYL MAVJUD TESTLARNI NEGA TAKRORLAMAYDI:
    `test_agent_one_click.py` — bir bosishli oqimning O'ZINI (uchiga-uch) o'lchaydi;
    `test_agent_launcher.py` — ishga tushirish shartnomasining birliklarini;
    bu fayl esa SOXTA ISHGA TUSHIRUVCHI va SOXTA YIG'UVCHI juftligini 14 ssenariyda
    MATRITSA bo'lib o'lchaydi: har ssenariyda (1) faza va holat ANIQ, (2) kod + operator
    matni + keyingi qadam BOR, (3) natija arxitektura ruxsat bergan joyga YOZILADI.

MATRITSA:
    A  1C yo'q               -> `NO_1C`, yaroqli yiqilish paketi
    B  bitta o'rnatma/baza   -> normal oqim, `COMPLETE`
    C  ko'p platforma vers.  -> DETERMINISTIK tanlov, tasodif YO'Q
    D  ko'p baza             -> ANIQ tanlov talab qilinadi (`TARGET_AMBIGUOUS`)
    E  yig'uvchi muvaffaqiy. -> `COLLECTOR_COMPLETE` -> `COMPLETE`
    F  yig'uvchi nosozligi   -> `COLLECTOR_FAILED` + sabab
    G  vaqt tugadi           -> `FAILED_TIMEOUT` + yaroqli paket
    H  ESKI natija           -> `STALE_OUTPUT` / `OUTPUT_PREDATES_REQUEST`
    I  noto'g'ri `nonce`     -> `NONCE_MISMATCH`
    J  to'liq bo'lmagan paket -> `PARTIAL_PACKAGE`
    K  xavfsizlik raddi      -> `COLLECTOR_EXECUTION_NOT_ALLOWED`
    L  operator bekor qildi  -> `OPERATOR_CANCELLED` + `ABORTED_BY_OPERATOR`, jarayon TIRIK
    M  agent qayta ishga t.  -> eski natija JIMGINA ishlatilmaydi
    N  ikki bir vaqtda yurish -> har biri O'Z papkasida, bir-birini KO'RMAYDI
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from app.services.discovery_1c import redact
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_agent import BUNDLE_SUBDIR
from app.services.discovery_agent import bridge_phase as bp
from app.services.discovery_agent import bridge_protocol as bpr
from app.services.discovery_agent import collector_bridge as cb
from app.services.discovery_agent import detector as det
from app.services.discovery_agent import launcher as lch
from app.services.discovery_agent import one_click as oc
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from tests import agent_bridge_mock as H
from tests import agent_scenario_mock as X

#: Statik taqiqlar uchun manbalar. ⚠️ Bekor qilish KOOPERATIV bo'lgani SHU fayllarda
#: isbotlanadi: jarayonni tugatish naqshi ularning birortasida ham bo'lmasligi SHART.
KUTISH_MANBALARI: tuple[pathlib.Path, ...] = (
    pathlib.Path(lch.__file__), pathlib.Path(oc.__file__), pathlib.Path(bpr.__file__),
    pathlib.Path(bp.__file__),
)

#: Xavfsizlikni ZAIFLASHTIRISHGA chaqiradigan maslahat naqshlari (K ssenariysi).
#: ⚠️ Ro'yxat ATAYLAB o'zbekcha fe'l shakllarida: operator matnlari o'zbek lotinida va
#: taqiq AYNAN operatorga ko'rinadigan matnga qo'yiladi.
ZAIFLASHTIRISH_NAQSHLARI: tuple[str, ...] = (
    "xavfsiz rejimni o'chir", "profilni o'chir", "profilni tahrirl", "rolga huquq qo'sh",
    "huquq qo'shib qo'y", "chetlab o'ting", "chetlab o'tamiz", "o'chirib qo'ying",
)


# ══════════════════════════════════════════════════════════════════════════════════════════
# UMUMIY DARVOZALAR — har ssenariy SHU UCHTASIDAN o'tadi
# ══════════════════════════════════════════════════════════════════════════════════════════
def uchlik_bor(code: str) -> None:
    """Kod uchun UCHTA narsa bor: kodning o'zi, operator matni, keyingi qadam.

    ⚠️⚠️ NEGA HAR SSENARIYDA: keyingi qadamsiz xato xabari har safar qo'ng'iroqqa
         aylanadi. Shu bois matritsaning har bir qatori uchlikni TALAB qiladi va bu
         talab bitta joyda yozilgan (ikkinchi nusxa bir kun yumshatilardi).
    """
    assert bp.BRIDGE_CODE_RE.fullmatch(code), f"kod shakli buzuq: {code!r}"
    uchlik = bp.failure_triple(code)
    assert uchlik.code == code
    assert uchlik.operator.strip(), f"{code}: operator matni BO'SH"
    assert uchlik.next_action.strip(), f"{code}: keyingi qadam BO'SH"


def faza_holat_aniq(phase: str, state: str) -> None:
    """Faza MA'LUM, holat MA'LUM va ikkisi ZID EMAS (fail-closed darvoza)."""
    assert bp.is_phase(phase), f"noma'lum faza: {phase!r}"
    assert st.is_known(state), f"noma'lum holat: {state!r}"
    oc.assert_outcome_consistent(phase, state)


def matnlar_sirsiz(*matnlar: str) -> None:
    """Operator matnlarida SIR va YO'L yo'q (`redact.scan` darvozasi).

    ⚠️ Bu matnlar `notes` ga va ekranga tushadi, ekran esa skrinshot bo'lib qo'ldan-qo'lga
       o'tadi.
    """
    topilgan = redact.scan([m for m in matnlar if m])
    assert not topilgan, f"operator matnida shubhali qiymat: {[str(f) for f in topilgan]}"
    for m in matnlar:
        for iz in X.SIR_IZLARI:
            assert iz not in (m or ""), f"matnda sintetik sir qoldi: {iz}"


def yakun_darvozasi(natija) -> None:
    """`OneClickOutcome` ning umumiy darvozasi: faza/holat + uchlik + sirsiz matn."""
    faza_holat_aniq(natija.phase, natija.state)
    if natija.code is not None:
        uchlik_bor(natija.code)
    assert natija.operator_text().strip(), "operator matni BO'SH bo'lmaydi"
    assert natija.next_action().strip(), "keyingi qadam BO'SH bo'lmaydi"
    matnlar_sirsiz(natija.operator_text(), natija.next_action(), natija.detail)
    for hodisa in natija.events:
        assert hodisa.text.strip(), f"«spinner-only» faza: {hodisa.phase}"
        faza_holat_aniq(hodisa.phase, hodisa.state)


def yozuv(papka) -> dict:
    """Natija papkasidagi `agent_status.json`."""
    return json.loads(X.matn(papka, "agent_status.json"))


def xato_kodlari(papka) -> list[str]:
    return [e["code"] for e in yozuv(papka)["errors"]]


def yaroqli_paket(papka) -> None:
    """Natija papkasi DISKDAN tekshiriladi (`validate_result_package` istisno beradi).

    ⚠️ Ikki qatlam ataylab: `UiModel._paket` ning O'ZI ham tekshiradi, lekin u tekshiruvni
       o'tkazib yuboradigan qilib tahrirlansa, bu chaqiruv baribir tutadi.
    """
    rp.validate_result_package(papka)
    bor = {n for n in X.papka_baytlari(papka) if "/" not in n}
    assert set(rp.ALWAYS_FILES) <= bor, f"ildizda majburiy artefakt yetishmaydi: {bor}"


def kod_matni(yol) -> str:
    """Manba matni IZOH va DOCSTRING larsiz.

    ⚠️⚠️ NEGA SHUNDAY: taqiqlar KODDA tekshirilishi kerak, IZOHDA emas. Oddiy matn
         qidiruvi «jarayon o'ldirish naqshi YO'Q» degan izohning O'ZINI topib, taqiqni
         isbot o'rniga NIQOB qilib qo'yardi.
    """
    daraxt = ast.parse(pathlib.Path(yol).read_text(encoding="utf-8"))
    for tugun in ast.walk(daraxt):
        tana = getattr(tugun, "body", None)
        if not isinstance(tana, list) or not tana:
            continue
        birinchi = tana[0]
        if (isinstance(birinchi, ast.Expr) and isinstance(birinchi.value, ast.Constant)
                and isinstance(birinchi.value.value, str)):
            tana[0] = ast.Pass()
    return ast.unparse(ast.fix_missing_locations(daraxt))


# ══════════════════════════════════════════════════════════════════════════════════════════
# A — 1C YO'Q -> `NO_1C`, YAROQLI YIQILISH PAKETI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_A_1c_yoq_NO_1C_fazasi_va_yaroqli_yiqilish_paketi(tmp_path):
    """1C o'rnatilmagan mashinada yurish BOSHLANMAYDI, lekin operator qo'li BO'SH QOLMAYDI.

    ⚠️⚠️ IKKI YO'L ATAYLAB o'lchanadi, chunki ular IKKI xil narsani isbotlaydi:
         (1) BIR BOSISHLI oqim — operator EKRANDA `NO_1C` fazasi, ma'no va keyingi qadamni
             oladi, yurish papkasi esa UMUMAN yaratilmaydi (yozishga hech narsa yo'q);
         (2) PAKETLI yo'l — operator qo'lida UZATISHGA YAROQLI yiqilish paketi qoladi va
             mashina o'qiydigan KOD aynan shu paketning `errors.json` ida turadi.
    ⚠️ `one_click` yiqilish paketini ATAYLAB yozmaydi (moduldagi HALOL QAYDga qarang):
       paketni mavjud quvur yozadi va u bu holatda sababni ALMASHTIRIB qo'yardi. Shu bois
       «yaroqli paket» talabi PAKETLI yo'lda o'lchanadi — ikki haqiqat yozilmaydi.
    ⚠️ Soxta ishga tushiruvchi UMUMAN chaqirilmaydi: 1C yo'q bo'lsa ochadigan narsa ham yo'q.
    """
    ochuvchi = H.SoxtaIshgaTushiruvchi()
    runs = H.runs_ildizi(tmp_path)
    model = H.agent(tmp_path, scan=X.muhit_1c_yoq())
    natija, hodisalar = H.bir_bosish(model, runs_root=runs)

    # ── (1) EKRAN: faza va holat ANIQ ───────────────────────────────────────────────────
    assert natija.phase == bp.NO_1C
    assert natija.state == st.FAILED_NO_1C
    assert bp.phase_state(bp.NO_1C) == st.FAILED_NO_1C, "faza xaritasi SHARTNOMA"
    assert [h.phase for h in hodisalar] == [bp.DETECTING_1C, bp.NO_1C], \
        "1C qidirildi va JAVOB berildi — oradagi faza O'YLAB QO'SHILMAYDI"
    yakun_darvozasi(natija)
    # ⚠️⚠️ MA'NO HUKMDAN KELADI: «qaradim va YO'Q» (`absent`) va «qaray olmadim»
    #      (`unknown`) BIR XIL matn bermasligi SHART — aks holda operator ikkisini
    #      ajratmasdi va «1C o'rnatmadim» degan noto'g'ri xulosaga kelardi.
    assert natija.operator_text() == st.failure_meaning(
        st.FAILED_NO_1C, presence_verdict=det.PRESENCE_ABSENT), \
        "matn MANBADAN (`states.failure_meaning`) olinadi, bu yerda yozilmaydi"
    assert natija.operator_text() != st.failure_meaning(
        st.FAILED_NO_1C, presence_verdict=det.PRESENCE_UNKNOWN), \
        "«qaradim va yo'q» bilan «qaray olmadim» BIR XIL matn bermaydi"

    # ── YURISH PAPKASI YARATILMAYDI va HECH NARSA O'CHIRILMAYDI ─────────────────────────
    assert H.yurish_papkalari(runs) == (), \
        "1C yo'q bo'lsa yurish papkasi UMUMAN yaratilmaydi (yozishga natija yo'q)"
    assert natija.run_id is None and natija.run_dir is None
    assert ochuvchi.chaqiruvlar == 0, "1C yo'q bo'lsa ishga tushiruvchi chaqirilmaydi"

    # ── (2) PAKETLI YO'L: YAROQLI yiqilish paketi + MASHINA O'QIYDIGAN KOD ──────────────
    paketli = H.agent(tmp_path, scan=X.muhit_1c_yoq(), nom="paketli",
                      epf_path=X.epf_yoz(tmp_path),
                      output_dir=X.bosh_papka(tmp_path, "chiqish")).start()
    assert paketli.state == st.FAILED_NO_1C
    assert paketli.result_dir is not None, "yiqilgan yurish ham PAPKA qoldiradi"
    yaroqli_paket(paketli.result_dir)
    assert cb.CODE_EXE_MISSING in xato_kodlari(paketli.result_dir), \
        "yiqilishning MASHINA O'QIYDIGAN kodi paketda bo'lishi SHART"
    assert yozuv(paketli.result_dir)["presence_verdict"] == det.PRESENCE_ABSENT, \
        "«qaradim va yo'q» hukmi paketda AYNAN shu nom bilan turadi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# B — BITTA O'RNATMA / BITTA BAZA -> NORMAL OQIM
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_B_bitta_ornatma_bitta_baza_normal_oqim(tmp_path):
    """Bitta o'rnatma va bitta baza: oqim OPERATOR QARORISIZ oxirigacha boradi.

    ⚠️ BITTA baza bo'lsa tanlov NOANIQ EMAS: `assert_unique_target` bitta nishon ko'radi va
       agent uni tanlaydi. «Har holda so'rash» operatorni sababsiz to'xtatardi.
    ⚠️ Soxta yig'uvchi `sleeper` ICHIDA yozadi, ya'ni fayllar KUTISH BOSHLANGANDAN KEYIN
       paydo bo'ladi — aks holda test kutish yo'lini umuman o'lchamagan bo'lardi.
    """
    runs = H.runs_ildizi(tmp_path)
    yiguvchi = H.SoxtaYiguvchi()
    model = H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path),
                    sleeper=yiguvchi.sleeper_sifatida(runs))
    kutish_jurnali: list[str] = []
    natija, hodisalar = H.bir_bosish(model, runs_root=runs,
                                     kutish_jurnali=kutish_jurnali)

    assert natija.state == st.COMPLETE and natija.phase == bp.COMPLETE
    assert natija.is_complete and not natija.is_failure
    assert natija.code is None, "muvaffaqiyatli yurishda nosozlik kodi BO'LMAYDI"
    yakun_darvozasi(natija)

    # ── FAZALAR: TO'LIQ, TARTIBDA va FAQAT OLDINGA ──────────────────────────────────────
    assert [h.phase for h in hodisalar] == [
        bp.DETECTING_1C, bp.DISCOVERING_INFOBASES, bp.SELECT_TARGET,
        bp.PREPARING_COLLECTOR, bp.LAUNCHING_1C, bp.WAITING_FOR_COLLECTOR,
        bp.COLLECTOR_COMPLETE, bp.INGESTING, bp.ANALYZING, bp.COMPLETE,
    ], "operator ko'radigan qadamlar ketma-ketligi SHARTNOMA"

    # ── YIG'UVCHI SHARTNOMA TARTIBIDA yozdi: BELGI ENG OXIRIDA ──────────────────────────
    assert yiguvchi.yozish_tartibi[-1] == bpr.DONE_FILE, \
        "tugallanish belgisi ENG OXIRIDA yozilishi SHART (yarim javob qabul qilinmasin)"
    assert yiguvchi.yozish_tartibi.index(bpr.RESPONSE_FILE) < \
        yiguvchi.yozish_tartibi.index(bpr.DONE_FILE)

    # ── NATIJA ARXITEKTURA RUXSAT BERGAN JOYDA ──────────────────────────────────────────
    run_dir = H.yagona_yurish_papkasi(runs)
    assert natija.run_dir == str(run_dir) and natija.run_id == run_dir.name
    assert natija.nonce_len >= 32, "`nonce` ning O'ZI emas, UZUNLIGI qaytadi"
    assert set(H.papka_nomlari(run_dir)) == {
        BUNDLE_SUBDIR, bpr.REQUEST_FILE, bpr.RESPONSE_FILE, bpr.DONE_FILE}, \
        "yurish papkasida UCHTA ko'prik hujjati va paket papkasi turadi"
    assert natija.result_dir is not None
    yaroqli_paket(natija.result_dir)

    # ── KUTISH KO'RINDI (operator «osilgan» deb o'ylamasin) ─────────────────────────────
    assert kutish_jurnali, "kutish operatorga KO'RSATILADI"
    assert all(s.strip() for s in kutish_jurnali)
    matnlar_sirsiz(*kutish_jurnali)

    # ── SO'ROV KREDENSIALSIZ va XOM LOKATORSIZ ──────────────────────────────────────────
    sorov = H.sorov_hujjati(run_dir)
    assert bpr.FINGERPRINT_RE.fullmatch(sorov["target_fingerprint"])
    xom = json.dumps(sorov, ensure_ascii=False)
    for iz in X.SIR_IZLARI:
        assert iz not in xom, f"so'rovga kredensial izi tushdi: {iz}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# C — BIR NECHTA PLATFORMA VERSIYASI -> DETERMINISTIK TARTIB
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_C_kop_platforma_versiyasi_deterministik_tanlov(tmp_path):
    """Ikki platforma versiyasi bo'lsa tanlov DETERMINISTIK: tasodifiy tanlov YO'Q.

    ⚠️⚠️ NEGA BU MUHIM: «qaysi 1C ochildi?» degan savolga javob bo'lmasa, bir mashinada
         ishlagan yurish ikkinchisida boshqa yo'ldan ketardi va nuqsonni takrorlab
         bo'lmasdi. Shu bois tanlov (1) HAR SAFAR bir xil, (2) KIRISH TARTIBIGA
         bog'liq EMAS, (3) SABABI bilan qaytadi.
    ⚠️ `random` moduli ishga tushirish manbasida UMUMAN bo'lmasligi ham tekshiriladi:
       «deterministik» da'vosi faqat o'lchov bilan emas, manba bilan ham qulflanadi.
    """
    env = H.muhit_ikki_versiya(tmp_path)
    assert len(env.installs) == 2, "fikstura IKKI o'rnatma bermasa ssenariy o'lchanmaydi"

    # ── (1) TAKRORLANADIGAN: besh chaqiruv — AYNAN bir natija ───────────────────────────
    tanlovlar = [lch.choose_exe(env.installs) for _ in range(5)]
    assert len({(t.path, t.version, t.client_type) for t in tanlovlar}) == 1, \
        "bir xil kirish AYNAN bir xil tanlov berishi SHART"
    tanlov = tanlovlar[0]
    assert tanlov.version == X.YANGI_VERSIYA, "ENG YANGI o'rnatma tanlanadi"
    assert tanlov.client_type == det.CLIENT_THICK, "standart tur — SEMIZ klient"

    # ── (2) KIRISH TARTIBIGA BOG'LIQ EMAS ───────────────────────────────────────────────
    teskari = H.muhit(tmp_path, H.baza("Sintetik yagona baza", tmp_path, "sintetik-baza"),
                      versiyalar=(X.YANGI_VERSIYA, X.ESKI_VERSIYA))
    assert lch.choose_exe(teskari.installs).path == tanlov.path, \
        "reestrdagi TARTIB tanlovni o'zgartirmasligi SHART"

    # ── (3) SABAB BILAN: jim tanlov YO'Q ────────────────────────────────────────────────
    assert tanlov.notes, "tanlov SABABI bilan qaytadi"
    assert any(X.YANGI_VERSIYA in n for n in tanlov.notes), \
        "izohda QAYSI versiya tanlangani turadi"
    matnlar_sirsiz(*tanlov.notes)

    # ── BUYRUQ ham DETERMINISTIK va faqat `/F` yoki `/S` bilan ──────────────────────────
    nishon = lch.LaunchTarget.from_infobase(env.infobases[0])
    buyruqlar = {lch.build_open_command(exe_path=tanlov.path, target=nishon)
                 for _ in range(3)}
    assert len(buyruqlar) == 1, "buyruq satri DETERMINISTIK"
    buyruq = buyruqlar.pop()
    assert buyruq[1] == cb.VERB_ENTERPRISE
    kalitlar = [t for t in buyruq if t.startswith(bpr.ALLOWED_TARGET_SWITCHES)]
    assert len(kalitlar) == 1, "nishon kaliti AYNAN bitta"
    for taqiq in ("/N", "/P", "/C"):
        assert not any(t.upper().startswith(taqiq) for t in buyruq), \
            f"buyruqda {taqiq} bo'lmasligi SHART (kredensial va o'ylab chiqarilgan kalit)"

    # ── SOXTA ISHGA TUSHIRUVCHI AYNI buyruqni oladi (va jarayon O'LDIRILMAYDI) ──────────
    ochuvchi = H.SoxtaIshgaTushiruvchi()
    natija = lch.open_infobase(exe_path=tanlov.path, target=nishon,
                               operator_confirmed=True, opener=ochuvchi)
    assert natija.launched == det.TRI_TRUE and natija.mode == lch.LAUNCH_MODE_AGENT
    assert ochuvchi.buyruqlar == [buyruq], "ishga tushiruvchiga AYNI buyruq boradi"
    assert ochuvchi.hammasi_tirik and ochuvchi.tugatish_chaqirildi == 0
    assert natija.verification == bp.AUTOMATIC_LAUNCH_VERIFICATION == \
        "UNVERIFIED_ON_REAL_1C", "avtomatik yo'l SINALMAGAN deb belgilanib qoladi"

    # ── MANBADA TASODIF YO'Q ────────────────────────────────────────────────────────────
    matn = kod_matni(pathlib.Path(lch.__file__))
    for taqiq in ("random", "shuffle", "sample("):
        assert taqiq not in matn, f"tanlovda tasodif naqshi topildi: {taqiq}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# D — BIR NECHTA BAZA -> ANIQ TANLOV TALAB QILINADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_D_kop_baza_aniq_tanlov_talab_qiladi(tmp_path):
    """Ikki baza bir xil darajada mos kelsa, agent O'ZI TANLAMAYDI — qaror OPERATORDA.

    ⚠️⚠️ BU QAROR ATAYLAB va u SHU TEST bilan QULFLANGAN: «jimgina birinchisini tanlash»
         noto'g'ri bazadan chiqqan hisobotni O'ZINI TO'LIQ deb ko'rsatardi, ya'ni xato
         JIMGINA bo'lardi. Shu bois:
           · tanlovsiz chaqiruv YIQILISH EMAS (`TARGET_SELECTION`, yakuniy holat emas);
           · yurish papkasi UMUMAN yaratilmaydi (yozadigan natija yo'q);
           · operatorning qadami ANIQ: «ro'yxatdan kerakli bazani O'ZINGIZ tanlang».
    ⚠️ Operator tanlasa oqim oxirigacha boradi va AYNAN TANLANGAN bazaning xeshi so'rovga
       tushadi — ya'ni tanlov jimgina boshqa bazaga surilib ketmaydi.
    """
    runs = H.runs_ildizi(tmp_path)
    env = H.muhit_ikki_baza(tmp_path)
    assert len(env.infobases) == 2, "fikstura IKKI baza bermasa ssenariy o'lchanmaydi"

    # ── TANLOVSIZ: agent TO'XTAYDI va o'zi tanlamaydi ───────────────────────────────────
    natija, hodisalar = H.bir_bosish(H.agent(tmp_path, scan=env), runs_root=runs)
    assert natija.phase == bp.SELECT_TARGET
    assert natija.state == st.TARGET_SELECTION
    assert natija.code == bp.CODE_TARGET_AMBIGUOUS
    assert natija.waiting_for_operator is True, "qaror OPERATORDA — yurish YIQILMADI"
    assert not natija.is_failure, "«agent urinib ko'rdi va bo'lmadi» YOLG'ON bo'lardi"
    yakun_darvozasi(natija)
    assert H.yurish_papkalari(runs) == (), \
        "tanlov qilinmagan yurish papkasi YARATILMAYDI"
    assert hodisalar[-1].phase == bp.SELECT_TARGET

    # ── OPERATOR TANLASA: oqim oxirigacha va AYNAN tanlangan baza ───────────────────────
    runs2 = H.runs_ildizi(tmp_path, "runs2")
    yiguvchi = H.SoxtaYiguvchi()
    model = H.agent(tmp_path, scan=env, nom="natija2",
                    sleeper=yiguvchi.sleeper_sifatida(runs2))
    tanlangan, _ = H.bir_bosish(model, runs_root=runs2, select_index=1)
    assert tanlangan.state == st.COMPLETE
    yakun_darvozasi(tanlangan)
    sorov = H.sorov_hujjati(H.yagona_yurish_papkasi(runs2))
    assert sorov["target_fingerprint"] == oc.target_fingerprint_of(env.infobases[1]), \
        "so'rovdagi nishon AYNAN operator tanlagan baza bo'lishi SHART"
    assert sorov["target_fingerprint"] != oc.target_fingerprint_of(env.infobases[0])


# ══════════════════════════════════════════════════════════════════════════════════════════
# E — YIG'UVCHI MUVAFFAQIYATI -> `COMPLETE`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_E_yiguvchi_muvaffaqiyati_qabul_qilinadi_va_COMPLETE(tmp_path):
    """Shartnomaga mos javob QABUL qilinadi va u mavjud quvurga BORADI.

    ⚠️⚠️ IKKI DA'VO ALOHIDA o'lchanadi:
         (1) KO'PRIK QATLAMI javobni qabul qiladi (`COLLECTOR_COMPLETE`, kod YO'Q);
         (2) QABUL QILINGAN PAKET natija papkasiga TUSHADI, ya'ni agent yig'uvchi yozgan
             papkani ROSTDAN o'qiydi — operator fayllarni QO'LDA KO'CHIRMAYDI.
    ⚠️ (2) ning isboti: so'rovdagi `output_dir` AYNAN yig'uvchi yozgan papka va natija
       paketining `bundle/` ichida AYNI majburiy fayllar turadi.
    """
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    yiguvchi = H.SoxtaYiguvchi()
    yiguvchi.yoz(yurish.run_dir)

    natija = H.kutish(yurish)
    assert natija.ok is True
    assert natija.phase == bp.COLLECTOR_COMPLETE
    assert natija.code is None and natija.state_hint is None
    assert natija.acceptance is not None
    assert natija.acceptance.status == bpr.STATUS_OK
    assert bp.phase_state(bp.COLLECTOR_COMPLETE) == st.METADATA_DISCOVERY, \
        "«javob keldi» — hali TEKSHIRILMAGAN bosqich (tekshiruv `INGESTING` da)"
    assert natija.diagnostics, "qabul qilish ham DIAGNOSTIKA qoldiradi"
    matnlar_sirsiz(*natija.diagnostics)

    # ── BIR BOSISHLI OQIM: AYNI javob bilan `COMPLETE` va paket KO'CHADI ────────────────
    runs2 = H.runs_ildizi(tmp_path, "runs2")
    yiguvchi2 = H.SoxtaYiguvchi()
    model = H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), nom="natija2",
                    sleeper=yiguvchi2.sleeper_sifatida(runs2))
    yakun, _ = H.bir_bosish(model, runs_root=runs2)
    assert yakun.state == st.COMPLETE and yakun.phase == bp.COMPLETE
    yakun_darvozasi(yakun)

    run_dir = H.yagona_yurish_papkasi(runs2)
    assert H.sorov_hujjati(run_dir)["output_dir"] == str(run_dir / BUNDLE_SUBDIR), \
        "yig'uvchi yozadigan papka AYNAN yurishning O'Z papkasi ichida"
    paketdagi = {n[len(BUNDLE_SUBDIR) + 1:]
                 for n in X.papka_baytlari(yakun.result_dir)
                 if n.startswith(f"{BUNDLE_SUBDIR}/")}
    assert set(rb.REQUIRED_FILES) <= paketdagi, \
        "yig'uvchi yozgan paket natija papkasiga KO'CHADI (qo'lda ko'chirish KERAK EMAS)"


# ══════════════════════════════════════════════════════════════════════════════════════════
# F — YIG'UVCHINING ANIQ NOSOZLIGI -> `COLLECTOR_FAILED` + SABAB
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_F_yiguvchi_aniq_nosozligi_COLLECTOR_FAILED_va_sabab(tmp_path):
    """Yig'uvchi «yiqildim» deb O'ZI aytsa — bu JAVOB, lekin `COMPLETE` emas.

    ⚠️⚠️ «JAVOB YO'Q» va «JAVOB BOR, LEKIN YIG'UVCHI YIQILDI» AJRATILADI: birinchisida
         operator yig'uvchini umuman bajarmagan bo'lishi mumkin, bu yerda esa u bajarilgan
         va 1C xatosi bilan to'xtagan. Keyingi qadam ikkisida BOSHQA.
    ⚠️ Sabab operatorga KO'RSATILADI (diagnostikada javob holati), lekin 1C ning xom xato
       matni sir darvozasidan o'tadi: `response.notes` `redact.scan` bilan tekshiriladi.
    """
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(status=bpr.STATUS_FAILED,
                    izohlar=("yig'uvchi 1C xatosi bilan to'xtadi",)).yoz(yurish.run_dir)

    natija = H.kutish(yurish)
    assert natija.ok is False
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.code == cb.CODE_EXIT_CODE_NONZERO, \
        "yig'uvchi O'ZI aytgan nosozlik uchun ko'prik kodi YO'Q — kod kutish qatlamidan"
    assert natija.operator.strip() and natija.next_action.strip(), "uchlik TO'LIQ"
    matnlar_sirsiz(natija.operator, natija.next_action, *natija.diagnostics)
    assert any(bpr.STATUS_FAILED in d for d in natija.diagnostics), \
        "SABAB diagnostikada: yig'uvchining o'z javobi atalib ko'rsatiladi"
    assert bp.phase_state(bp.COLLECTOR_FAILED) == st.FAILED_COLLECTOR_UNAVAILABLE

    # ── BIR BOSISHLI OQIMDA ham AYNI faza va holat ──────────────────────────────────────
    runs2 = H.runs_ildizi(tmp_path, "runs2")
    model = H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), nom="natija2",
                    sleeper=H.SoxtaYiguvchi(
                        status=bpr.STATUS_FAILED).sleeper_sifatida(runs2))
    yakun, hodisalar = H.bir_bosish(model, runs_root=runs2)
    assert yakun.phase == bp.COLLECTOR_FAILED
    assert yakun.state == st.FAILED_COLLECTOR_UNAVAILABLE
    yakun_darvozasi(yakun)
    assert hodisalar[-1].phase == bp.COLLECTOR_FAILED
    # ⚠️ Natija papkasi SAQLANADI: yarim natija O'CHIRILMAYDI (operator uni uzatishi mumkin).
    assert set(H.papka_nomlari(H.yagona_yurish_papkasi(runs2))) >= {
        bpr.REQUEST_FILE, bpr.RESPONSE_FILE, bpr.DONE_FILE}


# ══════════════════════════════════════════════════════════════════════════════════════════
# G — VAQT TUGADI -> `FAILED_TIMEOUT` + YAROQLI PAKET
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_G_vaqt_tugasa_FAILED_TIMEOUT_va_yaroqli_paket(tmp_path):
    """Yig'uvchi hech narsa yozmasa kutish CHEKLI tugaydi va paket YAROQLI qoladi.

    ⚠️⚠️ BO'SH PAPKA YIQILISH EMAS, u kutishning BOSHLANG'ICH holati. Shu bois hukm
         `FAILED_COLLECTOR_UNAVAILABLE` («javob bermadi») EMAS, `FAILED_TIMEOUT`: chekli
         vaqt ichida hech narsa chiqmasligi yig'uvchining O'LGANINI ISBOTLAMAYDI.
    ⚠️ HAQIQIY SONIYA KUTILMAYDI: soat va `sleeper` KIRISHDAN keladi va «cheksiz kutish
       YO'Q» da'vosi o'lchov SONI bilan isbotlanadi.
    """
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    uyqu: list[float] = []
    natija = H.kutish(yurish, uyqu_jurnali=uyqu)

    assert natija.phase == bp.WAITING_FOR_COLLECTOR
    assert natija.state_hint == st.FAILED_TIMEOUT
    assert natija.code == cb.CODE_WAIT_TIMEOUT
    assert natija.operator.strip() and natija.next_action.strip()
    assert int(natija.ticks) >= 1, "bo'sh papkada agent KUTADI, darhol yiqilmaydi"
    assert uyqu and len(uyqu) <= 10, f"kutish CHEKLI bo'lishi SHART: {len(uyqu)}"
    assert all(s <= H.KUTISH_QADAMI for s in uyqu), "uxlash chegaradan OSHMAYDI"
    assert any(bpr.RESPONSE_FILE in d and bpr.DONE_FILE in d
               for d in natija.diagnostics), \
        "NIMA kutilgani va NIMA topilmagani diagnostikada qoladi"
    matnlar_sirsiz(natija.operator, natija.next_action, *natija.diagnostics)

    # ── PAKETLI YO'L: `FAILED_TIMEOUT` + YAROQLI yiqilish paketi ────────────────────────
    uyqu2: list[float] = []
    model = X.kutuvchi_agent(tmp_path / "natija-kutish",
                             bundle_dir=X.bosh_papka(tmp_path, "kuzatilgan-bosh"),
                             timeout_seconds=6.0, poll_seconds=2.0, uyqu_jurnali=uyqu2,
                             qadam=1.0)
    paketli = model.start()
    assert paketli.state == st.FAILED_TIMEOUT
    yaroqli_paket(paketli.result_dir)
    assert cb.CODE_WAIT_TIMEOUT in xato_kodlari(paketli.result_dir)
    assert uyqu2 and len(uyqu2) <= 10

    # ── BIR BOSISHLI OQIM: yig'uvchi UMUMAN yozmadi -> `RESPONSE_MISSING` ───────────────
    runs2 = H.runs_ildizi(tmp_path, "runs2")
    yakun, _ = H.bir_bosish(
        H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), nom="natija2", chegara=6.0),
        runs_root=runs2)
    assert yakun.state == st.FAILED_TIMEOUT
    assert yakun.phase == bp.WAITING_FOR_COLLECTOR
    assert yakun.code == bp.CODE_RESPONSE_MISSING, \
        "papka BO'SH bo'lsa sabab «yig'uvchi umuman boshlanmagan» bo'ladi"
    assert yakun.waited_ticks >= 1, "yiqilishda ham o'lchov SONI qaytadi"
    yakun_darvozasi(yakun)


# ══════════════════════════════════════════════════════════════════════════════════════════
# H — ESKI NATIJA -> `STALE_OUTPUT` / `OUTPUT_PREDATES_REQUEST`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_H_eski_natija_rad_etiladi_va_ochirilmaydi(tmp_path):
    """Oldingi yurishdan qolgan natija bo'yicha XULOSA CHIQARILMAYDI.

    ⚠️⚠️ IKKI SABAB ATAYLAB AJRATILGAN:
         · `STALE_OUTPUT` — javob BOSHQA yurishga tegishli (`run_id` mos emas);
         · `OUTPUT_PREDATES_REQUEST` — o'zlik mos kelsa ham chiqish so'rovdan OLDIN
           yozilgan (masalan papka qo'lda ko'chirilgan).
         Operatorning qadami ikkisida boshqa, shu bois bitta kodga qo'shib yuborilmaydi.
    ⚠️ RAD ETISHDAN KEYIN HECH NARSA O'CHIRILMAYDI: eski fayllarni operator o'zi chetga
       suradi («agent hech narsani o'chirmaydi» da'vosi shu bilan o'lchanadi).
    """
    runs = H.runs_ildizi(tmp_path)

    # ── (1) BOSHQA YURISHNING natijasi ──────────────────────────────────────────────────
    birinchi = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(run_id=H.BEGONA_RUN_ID).yoz(birinchi.run_dir)
    natija = H.kutish(birinchi)
    assert natija.code == bp.CODE_STALE_OUTPUT
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    uchlik_bor(natija.code)
    assert natija.acceptance is None, "RAD etilgan javob QABUL QILINGAN deb yozilmaydi"
    oldin = set(H.papka_nomlari(birinchi.run_dir))
    assert {bpr.RESPONSE_FILE, bpr.DONE_FILE} <= oldin, "RAD etilgan fayl O'CHIRILMAYDI"

    # ── (2) CHIQISH SO'ROVDAN OLDIN yozilgan ────────────────────────────────────────────
    ikkinchi = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(belgi_vaqti=H.OLDINGI_KUN_ISO).yoz(ikkinchi.run_dir)
    natija2 = H.kutish(ikkinchi)
    assert natija2.code == bp.CODE_OUTPUT_PREDATES_REQUEST
    uchlik_bor(natija2.code)
    assert natija2.code != natija.code, "ikki sabab ALOHIDA kod bilan qaytadi"
    assert bp.failure_triple(natija2.code).next_action != \
        bp.failure_triple(natija.code).next_action, \
        "operatorning keyingi qadami ikkisida BOSHQA bo'lishi SHART"
    assert set(H.papka_nomlari(ikkinchi.run_dir)) >= {bpr.RESPONSE_FILE, bpr.DONE_FILE}

    # ── RAD ETISH MATNLARIDA YO'L YO'Q ──────────────────────────────────────────────────
    matnlar_sirsiz(natija.operator, natija.next_action, natija2.operator,
                   natija2.next_action)


# ══════════════════════════════════════════════════════════════════════════════════════════
# I — NOTO'G'RI `nonce` -> `NONCE_MISMATCH`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_I_notogri_nonce_NONCE_MISMATCH_bilan_rad_etiladi(tmp_path):
    """`nonce` mos kelmasa javob RAD etiladi — bu «eski javob» dan ALOHIDA sabab.

    ⚠️⚠️ NEGA ALOHIDA KOD: `run_id` mos kelib `nonce` mos kelmasligi — AYNI yurishga
         O'XSHATILGAN, lekin BOSHQA so'rovga yozilgan javob (masalan papkada oldingi
         so'rov qolgan). «Eski javob» deb atash operatorni yangi yurish boshlashga
         yuborardi, holbuki muammo so'rov hujjatining O'ZIDA.
    ⚠️⚠️ `nonce` NING QIYMATI RAD ETISH MATNIGA TUSHMAYDI: u soxta javobni aniqlashning
         yagona vositasi, xato xabari esa jurnalga tushadi va qo'ldan-qo'lga o'tadi.
    """
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(nonce=H.BEGONA_NONCE).yoz(yurish.run_dir)

    natija = H.kutish(yurish)
    assert natija.code == bp.CODE_NONCE_MISMATCH
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    uchlik_bor(natija.code)
    assert natija.acceptance is None

    haqiqiy_nonce = yurish.request["nonce"]
    for matn in (natija.operator, natija.next_action, *natija.diagnostics):
        assert haqiqiy_nonce not in matn, "`nonce` qiymati operator matniga TUSHMAYDI"
        assert H.BEGONA_NONCE not in matn, "begona qiymat ham ko'rsatilmaydi"
    matnlar_sirsiz(natija.operator, natija.next_action, *natija.diagnostics)

    # ── PROTOKOL DARVOZASI ham AYNI kodni beradi (ikkinchi talqin YO'Q) ────────────────
    with pytest.raises(bpr.BridgeProtocolError) as xato:
        bpr.accept_collector_output(
            request=yurish.request,
            response=H.javob_hujjati(yurish.request, nonce=H.BEGONA_NONCE),
            done=H.belgi_hujjati(yurish.request),
            bundle_files=rb.REQUIRED_FILES)
    assert xato.value.code == bp.CODE_NONCE_MISMATCH
    assert haqiqiy_nonce not in str(xato.value)


# ══════════════════════════════════════════════════════════════════════════════════════════
# J — TO'LIQ BO'LMAGAN PAKET -> `PARTIAL_PACKAGE`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_J_toliq_bolmagan_paket_PARTIAL_PACKAGE_bilan_rad_etiladi(tmp_path):
    """Yarim paket bo'yicha TAHLIL QILINMAYDI, lekin u O'CHIRILMAYDI ham.

    ⚠️⚠️ NEGA RAD: yarim paket ustida chiqarilgan xulosa O'ZINI TO'LIQ deb ko'rsatardi —
         bu jimgina xato, ya'ni eng yomoni.
    ⚠️ KEYINGI QADAM aynan «yarim natijani o'chirmasdan saqlab qo'ying» deydi, shu bois
       harness ham hech narsa o'chirmaydi va test buni O'LCHAYDI.
    ⚠️ Majburiy fayl nomi SHARTNOMADAN olinadi: ikkinchi ro'yxat bir kun birinchisidan
       ajralib ketardi.
    """
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(paket=H.paket_yarim).yoz(yurish.run_dir)

    natija = H.kutish(yurish)
    assert natija.code == bp.CODE_PARTIAL_PACKAGE
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    uchlik_bor(natija.code)
    assert natija.acceptance is None, "yarim paket QABUL QILINGAN deb yozilmaydi"

    # ── YARIM PAKET SAQLANADI (o'chirish YO'Q) ──────────────────────────────────────────
    bor = set(H.papka_nomlari(yurish.bundle_dir))
    assert rb.RUN_SUMMARY_FILE not in bor, "fikstura aynan shu faylni olib tashlagan"
    assert bor, "qolgan fayllar O'CHIRILMAYDI — operator ularni uzatishi mumkin"
    assert len(bor) == len(rb.REQUIRED_FILES) - 1, \
        "FAQAT bitta fayl yetishmaydi (wildcard o'chirish YO'Q)"
    matnlar_sirsiz(natija.operator, natija.next_action)

    # ── `OK` BO'LMAGAN javobda paket to'liqligi SABAB EMAS, NATIJA ──────────────────────
    ikkinchi = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(paket=H.paket_yarim, status=bpr.STATUS_FAILED).yoz(ikkinchi.run_dir)
    natija2 = H.kutish(ikkinchi)
    assert natija2.code == cb.CODE_EXIT_CODE_NONZERO, \
        "yig'uvchi «yiqildim» desa kod yarim paket EMAS, uning O'Z javobi bo'ladi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# K — XAVFSIZLIK RADDI -> `COLLECTOR_EXECUTION_NOT_ALLOWED`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_K_xavfsizlik_raddi_COLLECTOR_EXECUTION_NOT_ALLOWED(tmp_path):
    """1C tashqi qayta ishlashni rad etsa — bu NORMAL natija, nuqson emas.

    ⚠️⚠️ XAVFSIZLIK ZAIFLASHTIRILMAYDI: keyingi qadam matnlari xavfsiz rejimni o'chirish,
         xavfsizlik profilini tahrirlash yoki rolga huquq qo'shishni TAVSIYA QILMAYDI.
         Bu test shu taqiqni MATN bo'yicha o'lchaydi, chunki aynan shu matn operatorning
         1C administratoriga ko'rsatadigan matni bo'ladi.
    ⚠️⚠️ AGENT 1C NI O'ZI ISHGA TUSHIRMAYDI: bir bosishli oqimda darvoza FAIL-CLOSED va
         soxta ishga tushiruvchi UMUMAN chaqirilmaydi. Avtomatik yo'l DEKLARATSIYA bo'lib
         qoladi (`UNVERIFIED_ON_REAL_1C`) va u buyruq ham qurmaydi.
    """
    nishon = lch.LaunchTarget(kind=det.KIND_FILE, locator="SOXTA-LOKATOR",
                              name="Sintetik soxta baza")
    ochuvchi = H.SoxtaIshgaTushiruvchi()

    for sabab in lch.SECURITY_REFUSALS:
        natija = lch.security_refusal(sabab, target=nishon,
                                      collector_file="BinOSDiscovery.epf")
        assert natija.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
        assert natija.phase == bp.COLLECTOR_FAILED
        assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
        assert natija.launched == det.TRI_FALSE
        assert natija.mode == lch.LAUNCH_MODE_OPERATOR
        uchlik_bor(natija.code)
        assert natija.operator.strip() and natija.next_action.strip()
        matnlar = (natija.operator, natija.next_action, *natija.instructions,
                   *natija.notes)
        matnlar_sirsiz(*matnlar)
        past = " ".join(matnlar).casefold()
        for naqsh in ZAIFLASHTIRISH_NAQSHLARI:
            assert naqsh not in past, \
                f"{sabab}: xavfsizlikni zaiflashtirishga chaqiruv topildi: {naqsh!r}"
        assert any("administrator" in m.casefold() for m in matnlar), \
            "qaror DO'KONNING 1C administratoriga qoldiriladi"

    # ── TASDIQSIZ ISHGA TUSHIRISH: darvoza FAIL-CLOSED, ochuvchi CHAQIRILMAYDI ─────────
    tasdiqsiz = lch.open_infobase(exe_path=str(tmp_path / "1cv8.exe"), target=nishon,
                                  opener=ochuvchi)
    assert tasdiqsiz.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
    assert tasdiqsiz.launched == det.TRI_FALSE
    assert ochuvchi.chaqiruvlar == 0, "tasdiq yo'q bo'lsa ishga tushiruvchi CHAQIRILMAYDI"
    with pytest.raises(bpr.BridgeProtocolError) as xato:
        bpr.assert_launch_allowed(operator_confirmed=False)
    assert xato.value.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED

    # ── AVTOMATIK YO'L — DEKLARATSIYA, buyruq ham qurilmaydi ───────────────────────────
    dekl = lch.auto_run_processor()
    assert dekl.status == "UNVERIFIED_ON_REAL_1C"
    assert dekl.implemented == det.TRI_FALSE
    assert dekl.command is None, "qurilmagan yo'l uchun buyruq ham QURILMAYDI"
    assert dekl.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED

    # ── BIR BOSISHLI OQIM 1C NI O'ZI OCHMAYDI ──────────────────────────────────────────
    runs = H.runs_ildizi(tmp_path)
    model = H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path),
                    sleeper=H.SoxtaYiguvchi().sleeper_sifatida(runs))
    yakun, hodisalar = H.bir_bosish(model, runs_root=runs)
    assert yakun.state == st.COMPLETE
    assert ochuvchi.chaqiruvlar == 0, "bir bosishli oqim 1C ni O'ZI ochmaydi"
    launching = [h for h in hodisalar if h.phase == bp.LAUNCHING_1C]
    assert len(launching) == 1
    assert launching[0].detail == \
        bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED).next_action, \
        "operator AYNAN «o'zingiz bajaring» ko'rsatmasini oladi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# L — OPERATOR BEKOR QILDI -> `OPERATOR_CANCELLED` + `ABORTED_BY_OPERATOR`
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_L_operator_bekor_qilsa_jarayon_oldirilmaydi(tmp_path):
    """Bekor qilish KOOPERATIV: agent KUTISHNI to'xtatadi, 1C ni YOPMAYDI.

    ⚠️⚠️ ENG MUHIM DA'VO SHU TESTDA: jarayon O'LDIRILMAGANI IZOH bilan emas, HOLAT bilan
         isbotlanadi — soxta ishga tushiruvchi ochgan «jarayon» bekor qilishdan KEYIN ham
         TIRIK va tugatish sanog'i NOL.
    ⚠️⚠️ BEKOR QILISH TEKSHIRUVI BIRINCHI: papkada TO'LIQ va YAROQLI javob turgan bo'lsa
         ham bekor qilingan yurish MUVAFFAQIYAT bilan tugamaydi. Aks holda operator
         tugmani bosgandan keyin agent «tasodifan» muvaffaqiyat deb qaytardi.
    ⚠️ Yig'uvchi O'ZI «bekor qilindi» deb aytgan holat ham AYNI kodga va AYNI holatga
       tushadi: bitta vaziyat ikki xil nom OLMAYDI.
    """
    env = H.muhit_bir_baza(tmp_path)
    tanlov = lch.choose_exe(env.installs)
    nishon = lch.LaunchTarget.from_infobase(env.infobases[0])
    ochuvchi = H.SoxtaIshgaTushiruvchi()
    ochildi = lch.open_infobase(exe_path=tanlov.path, target=nishon,
                                operator_confirmed=True, opener=ochuvchi)
    assert ochildi.launched == det.TRI_TRUE
    assert len(ochuvchi.jarayonlar) == 1 and ochuvchi.hammasi_tirik

    # ── PAPKADA TO'LIQ JAVOB BOR, LEKIN OPERATOR BEKOR QILDI ───────────────────────────
    runs = H.runs_ildizi(tmp_path)
    yurish = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi().yoz(yurish.run_dir)
    belgi = lch.CancelToken()
    belgi.cancel()
    natija = H.kutish(yurish, cancel=belgi)

    assert natija.code == bp.CODE_OPERATOR_CANCELLED
    assert natija.state_hint == st.ABORTED_BY_OPERATOR
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.ok is False, "bekor qilingan yurish MUVAFFAQIYAT bilan tugamaydi"
    assert natija.acceptance is None, "bekor qilingach javob UMUMAN o'qilmaydi"
    uchlik_bor(natija.code)
    assert any(belgi.reason in d for d in natija.diagnostics), \
        "«nega to'xtadi» savoli javobsiz qolmaydi"
    matnlar_sirsiz(natija.operator, natija.next_action, *natija.diagnostics)

    # ── JARAYON O'LDIRILMADI ────────────────────────────────────────────────────────────
    assert ochuvchi.hammasi_tirik, "bekor qilish 1C jarayonini YOPMAYDI"
    assert all(j.tirik for j in ochuvchi.jarayonlar)
    assert ochuvchi.tugatish_chaqirildi == 0, "jarayonni tugatish CHAQIRILMAYDI"
    assert "o'zingiz yoping" in bp.failure_triple(bp.CODE_OPERATOR_CANCELLED).next_action, \
        "keyingi qadam 1C ni OPERATOR yopishini aytadi"

    # ── IDEMPOTENT: ikkinchi bosish SABABNI o'zgartirmaydi ─────────────────────────────
    belgi.cancel("boshqa sabab")
    assert belgi.reason == lch.CANCEL_REASON_OPERATOR, "BIRINCHI sabab qoladi"

    # ── YIG'UVCHI O'ZI «bekor qilindi» desa — AYNI kod va AYNI holat ───────────────────
    ikkinchi = H.yurish_tayyorla(runs)
    H.SoxtaYiguvchi(status=bpr.STATUS_CANCELLED).yoz(ikkinchi.run_dir)
    natija2 = H.kutish(ikkinchi)
    assert natija2.code == bp.CODE_OPERATOR_CANCELLED
    assert natija2.state_hint == st.ABORTED_BY_OPERATOR
    assert natija2.phase == bp.COLLECTOR_FAILED

    # ── STATIK TAQIQ: manbada jarayon O'LDIRISH va wildcard O'CHIRISH naqshi YO'Q ──────
    for manba in KUTISH_MANBALARI:
        matn = kod_matni(manba)
        for taqiq in ("taskkill", "rmtree", "terminate(", "kill(", "Popen",
                      "subprocess", "win32com", "CreateObject", "glob"):
            assert taqiq not in matn, f"{manba.name}: taqiqlangan naqsh topildi: {taqiq}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# M — AGENT QAYTA ISHGA TUSHDI -> ESKI NATIJA JIMGINA ISHLATILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_M_agent_qayta_ishga_tushsa_eski_natija_jimgina_ishlatilmaydi(tmp_path):
    """Kutish paytida agent qayta ishga tushsa, oldingi yurishning natijasi QABUL QILINMAYDI.

    ⚠️⚠️ BU ENG XAVFLI JIM XATO: qayta ishga tushgan agent papkada qolgan javobni «mening
         javobim» deb o'qib ketsa, operator butunlay BOSHQA bazadan (yoki boshqa vaqtdan)
         olingan hisobotni to'liq deb qabul qilardi. Darvoza ikki qiymat bilan yopiladi:
         `run_id` (`STALE_OUTPUT`) va `nonce` (`NONCE_MISMATCH`) — ikkisi ham
         `secrets.token_hex` bilan tug'iladi, ya'ni TAXMIN QILIB BO'LMAYDI.
    ⚠️ «Qayta ishga tushish» MODELI: birinchi yurish papkasini oladi va kutishda qoladi;
       agent qayta ishga tushganda YANGI yurish (yangi `run_id`, yangi `nonce`, YANGI
       papka) tug'iladi. Operator esa yig'uvchini ESKI so'rov bilan bajargan bo'lishi
       mumkin — aynan shu holat o'lchanadi.
    ⚠️ Yangi yurish ESKI papkaga UMUMAN QARAMAYDI: u faqat O'Z papkasini o'qiydi.
    """
    runs = H.runs_ildizi(tmp_path)
    eski = H.yurish_tayyorla(runs)
    yangi = H.yurish_tayyorla(runs)

    assert eski.run_dir != yangi.run_dir
    assert eski.request["run_id"] != yangi.request["run_id"]
    assert eski.request["nonce"] != yangi.request["nonce"], \
        "`nonce` har yurishda YANGI bo'lishi SHART"

    # ── (1) ESKI so'rov bilan yozilgan TO'LIQ javob YANGI papkada ──────────────────────
    # ⚠️ Yig'uvchi operatorning eski so'rovi bilan ishlagan, lekin natija yangi papkaga
    #    tushgan (papka qo'lda ko'chirilgan yoki yig'uvchi eski hujjatni o'qigan).
    H.yoz_json(yangi.run_dir / bpr.RESPONSE_FILE, H.javob_hujjati(eski.request))
    H.yoz_json(yangi.run_dir / bpr.DONE_FILE, H.belgi_hujjati(eski.request))
    H.SoxtaYiguvchi(javob=False, belgi=False).yoz(yangi.run_dir)

    natija = H.kutish(yangi)
    assert natija.ok is False, "eski natija JIMGINA muvaffaqiyat bo'lmaydi"
    assert natija.code == bp.CODE_STALE_OUTPUT
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.acceptance is None
    uchlik_bor(natija.code)

    # ── (2) FAQAT `nonce` farq qilsa — AYNI yurishga O'XSHATILGAN javob ham RAD ────────
    uchinchi = H.yurish_tayyorla(runs)
    H.yoz_json(uchinchi.run_dir / bpr.RESPONSE_FILE,
               H.javob_hujjati(uchinchi.request, nonce=eski.request["nonce"]))
    H.yoz_json(uchinchi.run_dir / bpr.DONE_FILE, H.belgi_hujjati(uchinchi.request))
    H.SoxtaYiguvchi(javob=False, belgi=False).yoz(uchinchi.run_dir)
    natija2 = H.kutish(uchinchi)
    assert natija2.code == bp.CODE_NONCE_MISMATCH, \
        "`run_id` to'g'ri bo'lsa ham BOSHQA so'rovning javobi o'tmaydi"

    # ── (3) YANGI YURISH ESKI PAPKAGA QARAMAYDI ────────────────────────────────────────
    H.SoxtaYiguvchi().yoz(eski.run_dir)      # eski papkada TO'LIQ va YAROQLI javob
    tortinchi = H.yurish_tayyorla(runs)
    natija3 = H.kutish(tortinchi)
    assert natija3.code == cb.CODE_WAIT_TIMEOUT, \
        "boshqa papkadagi yaroqli javob SHU yurishga tegishli emas — u KUTISHDA qoladi"
    assert natija3.state_hint == st.FAILED_TIMEOUT
    assert H.papka_nomlari(tortinchi.run_dir) == (BUNDLE_SUBDIR, bpr.REQUEST_FILE), \
        "yangi yurishning papkasiga BEGONA fayl ko'chirilmaydi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# N — IKKI BIR VAQTDA YURISH -> HAR BIRI O'Z PAPKASIDA
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_N_ikki_bir_vaqtda_yurish_bir_birini_kormaydi(tmp_path):
    """Ikki yurish BIR ildizda bo'lsa ham bir-birining natijasini KO'RMAYDI.

    ⚠️⚠️ ARALASHTIRILGAN TARTIB ATAYLAB: ikkisi ham AVVAL papka oladi, KEYIN ikkisiga ham
         yoziladi — ya'ni «bittasi tugagach ikkinchisi boshlandi» degan yengil holat
         o'lchanmaydi. Jarayon (thread) ISHLATILMAYDI: determinizm o'zaro ta'sirning
         TARTIBI bilan isbotlanadi, tasodifiy rejalashtirish bilan emas.
    ⚠️ UMUMIY GLOBAL NATIJA FAYLI YO'Q: ildizda FAQAT ikki papka turadi, ularning
       tashqarisida birorta fayl yo'q (aks holda ikki yurish bitta faylni ustma-ust
       yozardi).
    ⚠️ Papkalar KESISHMAYDI va biri ikkinchisining ichida EMAS.
    """
    runs = H.runs_ildizi(tmp_path)
    birinchi = H.yurish_tayyorla(runs)
    ikkinchi = H.yurish_tayyorla(runs)

    assert birinchi.run_dir.parent == ikkinchi.run_dir.parent == pathlib.Path(runs)
    assert birinchi.run_dir != ikkinchi.run_dir
    assert birinchi.run_dir not in ikkinchi.run_dir.parents
    assert ikkinchi.run_dir not in birinchi.run_dir.parents
    assert birinchi.request["output_dir"] != ikkinchi.request["output_dir"]
    assert birinchi.request["nonce"] != ikkinchi.request["nonce"]

    # ── IKKISIGA ham yozildi (aralashtirilgan tartibda) ────────────────────────────────
    H.SoxtaYiguvchi().yoz(birinchi.run_dir)
    H.SoxtaYiguvchi().yoz(ikkinchi.run_dir)

    for yurish, nom in ((birinchi, "birinchi"), (ikkinchi, "ikkinchi")):
        natija = H.kutish(yurish)
        assert natija.ok is True, f"{nom} yurish MUSTAQIL qabul qilinishi SHART"
        assert natija.acceptance.status == bpr.STATUS_OK

    # ── KESISHMA YO'Q: biri ikkinchisining javobini QABUL QILMAYDI ─────────────────────
    almashgan = lch.wait_for_collector(
        run_dir=birinchi.run_dir, request=ikkinchi.request, timeout_seconds=1.0,
        poll_seconds=1.0, clock=X.oshuvchi_soat(H.SOAT_QADAMI), sleeper=lambda _s: None)
    assert almashgan.code == bp.CODE_STALE_OUTPUT, \
        "boshqa yurishning papkasidagi javob RAD etiladi"
    assert almashgan.acceptance is None

    # ── ILDIZDA UMUMIY FAYL YO'Q ───────────────────────────────────────────────────────
    ildiz = pathlib.Path(runs)
    assert sorted(p.name for p in ildiz.iterdir()) == \
        sorted([birinchi.run_dir.name, ikkinchi.run_dir.name]), \
        "yurishlar ildizida FAQAT yurish papkalari turadi (umumiy natija fayli YO'Q)"

    # ── BIR BOSISHLI OQIM ikki marta: IKKI PAPKA, IKKI NATIJA ─────────────────────────
    oqim_runs = H.runs_ildizi(tmp_path, "runs-oqim")
    yakunlar = []
    korilgan: list[str] = []
    for i in (1, 2):
        yiguvchi = H.SoxtaYiguvchi()
        model = H.agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), nom=f"natija-{i}",
                        sleeper=yiguvchi.sleeper_sifatida(oqim_runs, chetla=korilgan))
        yakun, _ = H.bir_bosish(model, runs_root=oqim_runs)
        assert yakun.state == st.COMPLETE
        yakun_darvozasi(yakun)
        yakunlar.append(yakun)
        korilgan = [p.name for p in H.yurish_papkalari(oqim_runs)]

    assert len(H.yurish_papkalari(oqim_runs)) == 2, "har yurish O'Z papkasini oladi"
    assert yakunlar[0].run_id != yakunlar[1].run_id
    assert yakunlar[0].run_dir != yakunlar[1].run_dir
    assert yakunlar[0].result_dir != yakunlar[1].result_dir
    for yakun in yakunlar:
        yaroqli_paket(yakun.result_dir)


# ══════════════════════════════════════════════════════════════════════════════════════════
# MATRITSANING O'ZI — da'vo HALOL bo'lib qolishi
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_soxta_harness_degan_ogohlantirish_bilan_keladi():
    """⚠️⚠️ Harnessning QIYMATI shu ogohlantirishda: yashil to'plam «1C da ishladi» EMAS.

    Shu bois da'vo IKKI joyda qulflanadi: harnessning doimiysida va bu modulning
    sarlavhasida. Ogohlantirish yumshatilsa yoki o'chirilsa — test YIQILADI.
    """
    assert H.MATRITSA_OGOHLANTIRISHI == \
        "BU SOXTA HARNESS. HAQIQIY 1C MUVAFFAQIYATINI ISBOTLAMAYDI."
    assert H.MATRITSA_OGOHLANTIRISHI in (__doc__ or "")
    assert H.MATRITSA_OGOHLANTIRISHI in (H.__doc__ or "")

    # ⚠️ `.epf` IKKILIK fayli QURILGAN deb atalmaydi: holat nomi AYNAN `EPF_SOURCE_READY`.
    assert bp.EPF_SOURCE_READY == "EPF_SOURCE_READY"
    for hujjat in (__doc__ or "", H.__doc__ or ""):
        assert "EPF_BUILT" not in hujjat and "epf qurildi" not in hujjat.casefold()

    # ⚠️ Avtomatik ishga tushirish yo'li SINALMAGAN deb BELGILANADI.
    assert bp.AUTOMATIC_LAUNCH_VERIFICATION == "UNVERIFIED_ON_REAL_1C"

    # ⚠️ Faza xaritasi TO'LIQ: har faza AYNAN bitta holatga, «spinner-only» faza YO'Q.
    assert set(bp.PHASE_TO_STATE) == set(bp.BRIDGE_PHASES) == set(bp.PHASE_TEXT)
    assert len(bp.BRIDGE_PHASES) == 12
    for faza in bp.BRIDGE_PHASES:
        assert bp.phase_text(faza).strip(), f"«spinner-only» faza: {faza}"
        assert bp.phase_state(faza) in st.STATES
    assert len(st.NORMAL_STATES) == 12 and len(st.FAILURE_STATES) == 11, \
        "ko'prik qatlami MAVJUD holat mashinasini ALMASHTIRMAYDI"
