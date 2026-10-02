# -*- coding: utf-8 -*-
"""MANBA ↔ YIG'MA SEMANTIK PARITY (brief §5) + KODLASH NUQSONINING UCHIGA-UCH QULFI.

Bu modul AYNI sintetik fikstura bilan IKKI yurishni bajaradi — biri manba Python'dan
(`python -m app.services.discovery_agent`), ikkinchisi yig'ilgan `.exe` dan — va natijalarni
CHUQUR (JSON daraxti bo'ylab) solishtiradi. Isbotlanadigan da'vo bitta:
**PyInstaller o'rami agentning QARORINI o'zgartirmaydi.**

⚠️⚠️ BU REAL 1C ISBOTI EMAS. Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI,
     `.epf` BAJARILMAYDI va TARMOQ ishlatilmaydi — bu mashinada 1C umuman o'rnatilmagan.
     Kuzatiladigan papkani Phase 4 ning O'Z generatorlari yozadi
     (`tests.discovery_1c_runtime_mock`), ya'ni paket SHAKLI shartnomaga mos SINTETIK paket.
     Shu bois bu yerdagi hech narsa «real 1C kolleksiyasi» DEB ATALMAYDI: o'lchanadigan
     narsa — IKKI YIG'MANING bir xil kirishdagi semantikasi. Integratsiya yo'llarining 1C
     bilan ishlaydigan qismi `RUNTIME-UNKNOWN` bo'lib QOLADI.

NEGA BU FAYL MAVJUD (haqiqiy, topilgan nuqson): yig'ilgan `.exe` ni ROSTDAN yurgizganda
    operator matnlaridagi `⚠`, `═`, `─` va kirill harflari `cp1252` ga SIG'MAY
    `UnicodeEncodeError` berardi — Windows'da chiqish quvurga yo'naltirilganda
    `sys.stdout.encoding` AYNAN `cp1252` bo'ladi. Natija: yurish CHOP ETISH paytida uzilib,
    NATIJA PAPKASI UMUMAN YOZILMASDI. To'plam buni TUTMAGAN, chunki pytest chiqishni UTF-8
    bilan ushlaydi. Tuzatish `__main__.py` da (`_utf8ga_otkaz` + `_XavfsizOqim`).

NEGA QULF SHU YERDA (va `test_agent_packaging.py` da TAKRORLANMAYDI): u fayl himoyaning
    BO'LAKLARINI o'lchaydi — `_XavfsizOqim` yozishda yiqilmaydi, `_utf8ga_otkaz`
    `reconfigure` chaqiradi, manbada sig'maydigan belgi bor. Bu fayl esa NUQSONNING O'Z
    OQIBATINI o'lchaydi: `cp1252` sharoitida `main()` OXIRIGACHA yuradi va NATIJA PAPKASI
    DISKDA PAYDO BO'LADI — manbada ham, YIG'MADA ham (yig'mada haqiqiy quvur bilan). Bo'lak
    testlari yashil bo'lib turib ham paket yozilmay qolishi MUMKIN edi, aynan shu
    bo'shliqdan nuqson o'tib ketgan.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import io
import json
import marshal
import os
import pathlib
import struct
import sys

import pytest

from app.services.discovery_agent import (AGENT_MANIFEST_FILE, AGENT_STATUS_FILE,
                                          BUNDLE_SUBDIR, ENVIRONMENT_FILE, REPORT_FILE)
from app.services.discovery_agent import __main__ as M
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from tests import discovery_1c_runtime_mock as RM
# ⚠️ `cp1252` oqimi NUSXA KO'CHIRILMAYDI: u allaqachon `test_agent_packaging.py` da bor va
#    AYNI nuqsonni tasvirlaydi. Ikki nusxa bir kun bir-biridan ajralib ketardi (loyihadagi
#    naqsh: `tests/agent_scenario_mock.py` ham fiksturani test modulidan IMPORT qiladi).
# ⚠️ IMPORT GRAFI o'quvchisi ham SHU YERDAN olinadi (`_manbadan_yetib_boriladigan`,
#    `_spec_excludes`): u yig'ma TARKIBI darvozasining asbobi va ikkinchi nusxasi bir kun
#    ajralib ketardi. Pastdagi `test_A_spec_ikki_oquvchi_...` ikki o'quvchini QULFLAYDI.
from tests import test_agent_packaging as PKG
from tests.test_agent_packaging import _Cp1252Oqim
# ⚠️ FAQAT ildiz-drifti qo'riqchisi uchun (`test_A_yigma_ILDIZI_UCH_modulda_AYNI`):
#    portativlik darvozasi ham AYNI yig'ma ildizini o'qiydi va tengligi SHU YERDA
#    qulflanadi. Boshqa hech narsa bu moduldan olinmaydi.
from tests import test_agent_portability as PORT

# ══════════════════════════════════════════════════════════════════════════════════════════
# HARNESSNI YUKLASH — ⚠️ NOMLAR TO'QNASHUVI TUFAYLI YO'L BILAN
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ `from packaging.parity_harness import ...` ISHLAMAYDI va ishlatilmaydi: `packaging`
#      nomi PyPI paketi bilan to'qnashadi — u `site-packages/packaging/__init__.py` bilan
#      ODDIY paket, ODDIY paket esa nom bo'shliqli paketdan USTUN turadi. Shu bois
#      `import packaging` DOIM kutubxonani beradi va `packaging.parity_harness`
#      `ModuleNotFoundError` bo'ladi (tekshirilgan). Fayl YO'L bilan yuklanadi — bu chetlab
#      o'tish emas, to'qnashuvning yagona to'g'ri yechimi. `packaging/` papkasining nomini
#      o'zgartirish esa yig'ma sozlamasini (`.spec`) va uning testini ham siljitardi.
_HARNESS_YOLI = pathlib.Path(__file__).resolve().parents[1] / "packaging" / "parity_harness.py"


def _harnessni_yukla():
    spec = importlib.util.spec_from_file_location("binos_parity_harness", _HARNESS_YOLI)
    assert spec is not None and spec.loader is not None, \
        f"parity harnessi yuklanmadi: {_HARNESS_YOLI}"
    modul = importlib.util.module_from_spec(spec)
    # ⚠️ `sys.modules` ga EXEC'DAN OLDIN qo'yiladi: `@dataclass` sinfning modulini
    #    `sys.modules` dan izlaydi va u yerda bo'lmasa `AttributeError` beradi (`KW_ONLY`
    #    tekshiruvi). Bu yo'l bilan yuklashning MA'LUM talabi, hiyla emas.
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


PH = _harnessni_yukla()


# ══════════════════════════════════════════════════════════════════════════════════════════
# UCH SSENARIY — har biri BIR MARTA yuriladi (jarayon ochish qimmat)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: (nom, generator, kutish, kutilgan terminal holat, kutilgan chiqish kodi, paket olinadimi)
#: ⚠️⚠️ KUTILGAN NATIJA HAM QULFLANADI: parity «ikkisi ham bir xil» bilan CHEKLANMAYDI —
#:      ikki yurish BIRGALIKDA boshqa yo'ldan ketib (masalan ikkisi ham `FAILED_INTERNAL`
#:      bo'lib) jimgina «teng» bo'lib qolishi mumkin edi va test yashil turardi. Shu bois
#:      ssenariy AYNAN o'lchamoqchi bo'lgan holatga yetgani alohida tekshiriladi.
SSENARIYLAR = (
    # 1) sog'lom SUCCESS paketi -> COMPLETE
    ("sog-lom-success", RM.paket_sog_lom, PH.SOG_LOM_KUTISH, st.COMPLETE, 0, True),
    # 2) BO'SH kuzatilgan papka -> vaqt tugashi (paket UMUMAN olinmaydi)
    ("bosh-papka-timeout", None, PH.TIMEOUT_KUTISH, st.FAILED_TIMEOUT, 1, False),
    # 3) buzuq paket (manifest xeshlari mos emas) -> validatsiya yiqilishi
    ("buzuq-paket", RM.paket_manifest_mos_emas, PH.SOG_LOM_KUTISH, st.FAILED_VALIDATION,
     1, True),
)
_SSENARIY_ID = [s[0] for s in SSENARIYLAR]


# ══════════════════════════════════════════════════════════════════════════════════════════
# KAFOLATNING IKKI EGASI — DARVOZA
# ══════════════════════════════════════════════════════════════════════════════════════════
def _exe_darvozasi(*, toza_shart: bool = True) -> str:
    """Haqiqiy `.exe` parity'sini yurgizish MUMKINMI — va mumkin bo'lmasa QANDAY tugaydi.

    ⚠️⚠️ «EXE yo'q bo'lsa YIQIL» xulqi SHARTSIZ skip'ga AYLANTIRILMADI. Uch xil tugash:
      · `.exe` YO'Q va platforma Windows — YIQILADI. Bu mashinada yig'ma QURILISHI
        mumkin, demak yo'qligi operatorning ishi, muhit cheklovi EMAS.
      · `.exe` YO'Q va platforma Windows EMAS — MUHIT skip'i. Linux Windows `.exe` ni
        QURA OLMAYDI; o'rniga kafolatning Linux'da isbotlanadigan qismi (yig'ma
        SHARTNOMASI) `test_A_*` da BAJARILADI va skip `ci_expected_skips.txt` da ANIQ id
        bilan ratifikatsiya qilingan.
      · `.exe` BOR, lekin JORIY manbadan qurilgani ISBOTLANMAGAN — YIQILADI (jim skip
        EMAS). Eskirgan yig'ma parity'dan jimgina o'tib ketishi mumkin edi: o'zgargan
        modul tanlangan fiksturada farq bermasa solishtirish YASHIL bo'lardi.

    `toza_shart=False` — darvozaning O'ZINI o'lchaydigan testlar uchun: ESKIRGAN yig'ma
    ham O'QILADI (ular «eskirgan ekanini topdimi» degan savolga javob beradi).
    """
    holat, sabab = PH.yigma_tayyorligi()
    if holat == PH.HOLAT_TOZA:
        return holat
    if holat == PH.HOLAT_YOQ:
        if PH.exe_qurish_mumkinmi():
            pytest.fail(sabab)
        pytest.skip(sabab)
    if holat == PH.HOLAT_ESKIRGAN and not toza_shart:
        return holat
    pytest.fail(sabab)


@pytest.fixture(scope="module", params=SSENARIYLAR, ids=_SSENARIY_ID)
def juftlik(request, tmp_path_factory):
    """AYNI fikstura bilan MANBA va YIG'MA yurishlari + ssenariyning kutilgan natijasi.

    ⚠️ `scope="module"`: har ssenariy IKKI jarayon ochadi va tayyorlik o'lchovi uchun
       haqiqiy `poll` uyqusini kutadi. Har test uchun qaytadan yurgizish to'plamni bir necha
       baravar sekinlashtirardi va HECH NARSA qo'shmasdi — natijalar o'zgarmas.
    ⚠️ EXE YO'Q BO'LSA JIMGINA O'TKAZIB YUBORILMAYDI: `_exe_darvozasi()` qarorni Windows'da
       YIQILISH, Linux'da esa RATIFIKATSIYA QILINGAN muhit skip'i qiladi; eskirgan yig'ma
       esa HAR IKKI platformada BALAND yiqiladi.
    """
    nom, generator, kutish, kutilgan_holat, kutilgan_kod, paket_bor = request.param
    _exe_darvozasi()
    ildiz = tmp_path_factory.mktemp(f"parity-{nom}")
    manba, yigma = PH.ikki_yurish(str(ildiz), generator, kutish=kutish)
    return nom, manba, yigma, kutilgan_holat, kutilgan_kod, paket_bor


def _ichki_yurish(ildiz: str, generator, *, kutish: str) -> PH.Yurish:
    """MANBA yurishi — JARAYON OCHMASDAN, `main()` ni SHU jarayonda chaqirib.

    ⚠️ NEGA IN-PROCESS: `.exe` yo'q bo'lgan muhitda (Linux CI) solishtiruvchining O'ZI
       baribir o'lchanishi kerak. Manba tarafni jarayon ochmasdan yurgizish buni mumkin
       qiladi va `sys.executable` ga ham, platformaga ham TAYANMAYDI.
    ⚠️ `PH.Yurish` AYNI shakl bo'lib qoladi, demak `semantik()`/`farqlar()` ikkala tarafda
       ham AYNI kod bilan ishlaydi — ikkinchi, parallel solishtiruvchi YOZILMAYDI.
    """
    kuzatilgan = PH.fikstura_yoz(ildiz, "ichki-kuzatilgan", generator)
    natija_otasi = os.path.join(ildiz, "ichki-natija")
    os.makedirs(natija_otasi, exist_ok=True)
    out, err = io.StringIO(), io.StringIO()
    kod = M.main(["--headless", kuzatilgan, "--result-dir", natija_otasi,
                  "--timestamp", PH.TAMGA, "--wait-seconds", kutish], out=out, err=err)
    papka = os.path.join(natija_otasi, rp.result_dir_name(PH.TAMGA))
    bor = os.path.isdir(papka)
    return PH.Yurish(
        nom="MANBA/ichki", kod=kod, stdout=out.getvalue(), stderr=err.getvalue(),
        kuzatilgan=kuzatilgan, natija_otasi=natija_otasi,
        natija_papkasi=papka if bor else None,
        fayllar=PH.papka_baytlari(papka) if bor else {})


@pytest.fixture(scope="module", params=SSENARIYLAR, ids=_SSENARIY_ID)
def manba_yurishi(request, tmp_path_factory):
    """MANBA tarafning yurishi — `.exe` KERAK EMAS, demak Linux CI'da ham BAJARILADI.

    ⚠️⚠️ BU EXE PARITY'SINING O'RNINI BOSMAYDI va bosmoqchi ham emas. U faqat
         solishtiruvchining O'ZI va allowlist Linux'da ham o'lchanishini ta'minlaydi:
         pastdagi testlar yig'maga TEGMAYDI — ular manba natijasini O'ZIGA (yoki
         ataylab buzilgan nusxasiga) solishtiradi.
    """
    nom, generator, kutish, kutilgan_holat, kutilgan_kod, paket_bor = request.param
    ildiz = tmp_path_factory.mktemp(f"manba-{nom}")
    return (nom, _ichki_yurish(str(ildiz), generator, kutish=kutish),
            kutilgan_holat, kutilgan_kod, paket_bor)


# ══════════════════════════════════════════════════════════════════════════════════════════
# PARITY — ASOSIY DA'VO
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ssenariy_semantik_jihatdan_teng(juftlik):
    """⚠️⚠️ ASOSIY DA'VO: ikki yurishning SEMANTIKASI AYNAN teng (allowlistdan tashqari).

    Solishtirish CHUQUR: `semantik()` ko'rinishi JSON daraxti bo'ylab bargma-barg yoyiladi
    (`barglar`), ya'ni «ikkisi ham bo'sh emas» kabi bo'sh tekshiruv EMAS. Bitta kalit
    yo'qolsa ham, bitta ro'yxat elementi siljisa ham farq bo'lib ko'rinadi.
    """
    _nom, manba, yigma, *_ = juftlik
    taqiq, _ruxsat = PH.farqlar(manba, yigma)
    assert not taqiq, PH.hisobot(manba, yigma, taqiq)


def test_ssenariy_kutilgan_yolgacha_bordi(juftlik):
    """Ikki yurish KUTILGAN qarorga keldi — «birga noto'g'ri» bo'lib teng chiqmadi."""
    _nom, manba, yigma, kutilgan_holat, kutilgan_kod, _paket = juftlik
    for yurish in (manba, yigma):
        s = PH.semantik(yurish)
        assert s["terminal_holat"] == kutilgan_holat, \
            f"{yurish.nom}: holat {s['terminal_holat']} (kutilgan {kutilgan_holat})"
        assert s["chiqish_kodi"] == kutilgan_kod, \
            f"{yurish.nom}: kod {s['chiqish_kodi']} (kutilgan {kutilgan_kod})"
        # ⚠️ YIQILGAN YURISH HAM NATIJA PAPKASINI QOLDIRADI — agentning o'zak kafolati.
        assert s["natija_papkasi_yozildi"], f"{yurish.nom}: natija papkasi yozilmadi"
        assert s["route"] == "watch_folder", f"{yurish.nom}: yo'l {s['route']}"
        # ⚠️ Bu mashinada 1C YO'Q va hamma manba O'QILDI: hukm `absent` («qaradim va yo'q»),
        #    `unknown` («qaray olmadim») EMAS. Ikkisi aralashsa agent yolg'on javob berardi.
        assert s["presence_verdict"] == "absent", \
            f"{yurish.nom}: hukm {s['presence_verdict']}"


def test_brief_sanagan_hamma_maydon_solishtirildi(manba_yurishi):
    """⚠️ Brief §5 sanagan HAMMA maydon semantik ko'rinishda BOR.

    Aks holda parity testi jimgina qisqarib qolardi: maydon `semantik()` dan yo'qolsa
    solishtirish ham yo'qoladi va test baribir yashil bo'lardi.

    ⚠️ MANBA yurishiga tayanadi (`.exe` kerak emas): «solishtirish nimani qamraydi» degan
       da'vo yig'maga BOG'LIQ emas, demak u Linux CI'da ham BAJARILISHI kerak.
    """
    _nom, manba, *_ = manba_yurishi
    ko_rinish = PH.semantik(manba)
    kutilgan = set(PH.solishtirilgan_maydonlar())
    assert kutilgan == set(ko_rinish), (
        "semantik ko'rinish e'lon qilingan maydonlarga mos emas: "
        f"yo'q={sorted(kutilgan - set(ko_rinish))} "
        f"ortiqcha={sorted(set(ko_rinish) - kutilgan)}")
    # ⚠️ BARGLARNING SONI ham qulflanadi: hujjatlar ROSTDAN yoyilganini isbotlaydi — bitta
    #    «hammasi teng» bargi emas, o'nlab mustaqil barg solishtiriladi.
    barglar = PH.barglar(ko_rinish)
    assert len(barglar) > 60, f"solishtirish yuzaki ko'rinadi: {len(barglar)} barg"
    # ⚠️ ENG MUHIM UCH HUJJAT ichi ham ROSTDAN yoyilgan bo'lsin.
    for nom in (AGENT_STATUS_FILE, ENVIRONMENT_FILE, AGENT_MANIFEST_FILE):
        ichki = [y for y in barglar if y.startswith(f"hujjat:{nom}/")]
        assert len(ichki) >= 5, f"{nom} yoyilmadi: {len(ichki)} barg"


@pytest.mark.parametrize("nom,generator", [(s[0], s[1]) for s in SSENARIYLAR],
                         ids=_SSENARIY_ID)
def test_kuzatilgan_papkalar_bayt_ba_bayt_ayni(tmp_path, nom, generator):
    """Ikki yurishga berilgan fikstura AYNAN bir xil edi — farq KIRISHDAN kelmaydi.

    ⚠️ Usiz parity testining ma'nosi yo'q: generator deterministik bo'lmasa «yig'ma boshqa
       qaror chiqardi» degan xulosa aslida «kirish boshqa edi» bo'lib qolardi.
    ⚠️ YURISH KERAK EMAS va shu bois `.exe` ham kerak emas: da'vo FAQAT generator haqida.
       Ilgari bu test parity juftligidan papkalarni olardi, ya'ni `.exe` yo'q bo'lsa
       generator determinizmi jimgina TEKSHIRILMAY qolardi — kirish determinizmi esa
       parity'ning SHARTI, uning natijasi emas.
    """
    a = PH.papka_baytlari(PH.fikstura_yoz(str(tmp_path), "a", generator))
    b = PH.papka_baytlari(PH.fikstura_yoz(str(tmp_path), "b", generator))
    farqli = sorted(set(a) ^ set(b)) or sorted(n for n in a if a[n] != b.get(n))
    assert a == b, f"kuzatilgan papkalar BIR XIL emas (generator deterministik emas): {farqli}"
    if generator is None:
        assert not a, f"vaqt tugashi ssenariysida papka BO'SH bo'lishi kerak: {sorted(a)}"
    else:
        assert a, "generator paket yozmadi — fikstura bo'sh"


def test_bundle_shartnomaga_mos_kochirildi(juftlik):
    """`bundle/` — kuzatilgan papkaning O'ZGARMAGAN nusxasi; paket olinmasa esa YO'Q.

    ⚠️ Parity bilan BIRGA boradi, lekin boshqa narsani o'lchaydi: paket to'g'ri KO'CHIRILDI
       (bayt o'zgarmadi), faqat «ikki nusxa bir xil» emas.
    ⚠️ Vaqt tugagan yurishda `bundle/` BO'LMASLIGI ham SHARTNOMA, shu bois u `skip` emas —
       TEKSHIRILADIGAN da'vo: paket olinmagan bo'lsa agent paket DA'VO QILMAYDI.
    """
    _nom, manba, yigma, _holat, _kod, paket_bor = juftlik
    for yurish in (manba, yigma):
        chiqish = {nom.split("/", 1)[1]: xom for nom, xom in yurish.fayllar.items()
                   if nom.startswith(f"{BUNDLE_SUBDIR}/")}
        if not paket_bor:
            assert not chiqish, \
                f"{yurish.nom}: paket OLINMAGAN, lekin `bundle/` yozilgan: {sorted(chiqish)}"
            continue
        kirish = PH.papka_baytlari(yurish.kuzatilgan)
        assert chiqish == kirish, f"{yurish.nom}: `bundle/` o'zgargan yoki to'liq emas"


# ══════════════════════════════════════════════════════════════════════════════════════════
# ALLOWLIST — QISQA, SABABLI va O'LIK EMAS
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_allowlist_qisqa_va_har_biriga_sabab_bor():
    """⚠️⚠️ ALLOWLIST KENGAYTIRILMASIN: shakli va hajmi QULFLANGAN.

    Da'vo: ro'yxatda AYNAN ikki satr bor, ikkisi ham `environment.json` ning skaner vaqtiga
    (va uning manifestdagi bevosita oqibatiga) tegishli, va har biriga uzun SABAB yozilgan.
    """
    assert len(PH.ALLOWLIST) == 2, (
        f"allowlist kengaydi ({len(PH.ALLOWLIST)} satr) — har yangi satr ALOHIDA ko'rik "
        f"talab qiladi: {sorted(PH.ALLOWLIST_YO_LLARI)}")
    assert PH.ALLOWLIST_YO_LLARI == {
        f"hujjat:{ENVIRONMENT_FILE}/scanned_at",
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/sha256",
    }
    for yo_l, sabab in PH.ALLOWLIST:
        assert len(sabab) > 80, f"{yo_l}: sabab juda qisqa — «nega muqarrar» yozilishi kerak"


def test_allowlistda_qaror_semantikasi_yoq():
    """⚠️⚠️ BIZNES/QAROR semantikasi allowlistga HECH QACHON tushmaydi.

    Holat, chiqish kodi, yo'l, hukm, xatolar, hisobot, paket mazmuni — AYNAN teng bo'lishi
    SHART. Bu tekshiruv TO'G'RIDAN-TO'G'RI yozilgan, chunki aynan shu narsa allowlistning
    ma'nosini yo'qotardi.
    """
    taqiqlangan = ("terminal_holat", "chiqish_kodi", "route", "presence_verdict", "hisobot",
                   "paket_nuqsonlari", "bundle_xeshlari", "fayl_nomlari", "stdout", "stderr",
                   "natija_papkasi_yozildi", "/state", "/errors", "/notes", "/route",
                   f"hujjat:{AGENT_STATUS_FILE}", "files_tartibi")
    for yo_l in PH.ALLOWLIST_YO_LLARI:
        for bolak in taqiqlangan:
            assert bolak not in yo_l, f"allowlistda QAROR maydoni bor: {yo_l} ⊃ {bolak}"


def test_allowlist_aniq_tenglik_bilan_moslashadi():
    """⚠️ Moslashtirish NAQSH emas, AYNIQ TENGLIK: allowlist jimgina kengaymaydi."""
    assert PH.allowlist_sababi(f"hujjat:{ENVIRONMENT_FILE}/scanned_at")
    assert PH.allowlist_sababi(
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/sha256")
    for begona in (
        # ⚠️ BOSHQA faylning xeshi — ruxsat ETILMAYDI.
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{REPORT_FILE}/sha256",
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{AGENT_STATUS_FILE}/sha256",
        # ⚠️ AYNI faylning HAJMI — ruxsat ETILMAYDI (ISO tamg'a qat'iy kenglikda).
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/bytes",
        # ⚠️ Muhit hujjatining boshqa maydonlari — ruxsat ETILMAYDI.
        f"hujjat:{ENVIRONMENT_FILE}/presence_verdict",
        f"hujjat:{ENVIRONMENT_FILE}/os_version",
        f"hujjat:{ENVIRONMENT_FILE}/com_registered",
        # ⚠️ Prefiks yoki qo'shimcha bilan ham o'tmaydi.
        f"hujjat:{ENVIRONMENT_FILE}/scanned_at/qoshimcha",
        "scanned_at",
        f"{ENVIRONMENT_FILE}/scanned_at",
    ):
        assert PH.allowlist_sababi(begona) is None, f"allowlist juda keng: {begona} o'tdi"
        assert not PH._allowlistda(begona)


def test_allowlist_olik_qoida_emas(juftlik):
    """⚠️ ALLOWLIST ROSTDAN ISHLATILADI: ruxsat etilgan farqlar faqat ro'yxatdagi joylarda.

    Agar skaner vaqtining farqi bir kun YO'QOLSA (masalan `--timestamp` muhit skanerining
    soatini ham chetlab o'tadigan bo'lsa), allowlist KERAKSIZ bo'lib qoladi va uni OLIB
    TASHLASH kerak — o'lik ruxsat keyinchalik haqiqiy farqni yashirishi mumkin.
    ⚠️ `scanned_at` ning SHAKLI esa baribir teng bo'lishi SHART (kenglik va `+00:00`), aks
       holda «vaqt» niqobi ostida boshqa nuqson yashiringan bo'lardi.
    """
    _nom, manba, yigma, *_ = juftlik
    _taqiq, ruxsat = PH.farqlar(manba, yigma)
    yo_llar = {f.yo_l for f in ruxsat}
    assert yo_llar <= PH.ALLOWLIST_YO_LLARI, \
        f"ruxsat etilgan farq allowlistdan tashqarida: {sorted(yo_llar)}"
    vaqt_yoli = f"hujjat:{ENVIRONMENT_FILE}/scanned_at"
    xesh_yoli = f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/sha256"
    # ⚠️ Ikki jarayon AYNI sekundda boshlanishi MUMKIN (va bu nuqson EMAS). Shunda IKKI
    #    satr ham farq bermasligi kerak: xesh farqi vaqt farqining OQIBATI, mustaqil emas.
    if vaqt_yoli not in yo_llar:
        assert not yo_llar, (
            f"vaqt teng, lekin boshqa ruxsat etilgan farq bor: {sorted(yo_llar)} — "
            f"demak {xesh_yoli} vaqtdan BOSHQA sababdan farq qilgan")
    a = json.loads(manba.fayllar[ENVIRONMENT_FILE].decode("utf-8"))
    b = json.loads(yigma.fayllar[ENVIRONMENT_FILE].decode("utf-8"))
    assert len(a["scanned_at"]) == len(b["scanned_at"]), \
        "skaner vaqtining KENGLIGI boshqa — manifestdagi `bytes` ham siljiydi"
    assert a["scanned_at"].endswith("+00:00") and b["scanned_at"].endswith("+00:00")


# ══════════════════════════════════════════════════════════════════════════════════════════
# SOLISHTIRUVCHINING TISHI — «yashil» degani «ko'r» EMASLIGI isbotlanadi
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_solishtiruvchi_haqiqiy_farqni_rostdan_topadi(manba_yurishi):
    """⚠️⚠️ MUTATSIYA: natijaga BITTA o'zgarish kiritilsa, solishtiruvchi uni TOPISHI shart.

    Asosiy parity testi YASHIL bo'lgani «farq yo'q» degani, lekin u solishtiruvchining KO'R
    bo'lmagani haqida hech narsa demaydi. Shu bois HAQIQIY natija olinadi, undan bitta
    hujjatning bitta maydoni buziladi va farq KO'RINISHI tekshiriladi.
    ⚠️ Diskdagi fayl O'ZGARTIRILMAYDI: `Yurish` nusxasi xotirada quriladi (u `frozen`), ya'ni
       bu test boshqa testlarning natijasini buzmaydi.
    ⚠️ Topilgan farqlar TO'PLAMI emas, KIRISHI tekshiriladi (`in`): hujjat qayta
       serializatsiya qilinganda agentning deterministik shakli bilan bir xil bayt chiqmaydi
       va yo'l-yo'lakay boshqa farqlar ham paydo bo'ladi. Bu testning da'vosi esa boshqa —
       «o'zgartirilgan MAYDON ko'rinadimi». Shaklning o'zi
       `test_tabiiy_vaqt_farqi_...` da bayt darajasida qulflanadi.
    ⚠️ MANBA yurishiga tayanadi: solishtiruvchining TISHI yig'maga BOG'LIQ emas, demak
       uni `.exe` yo'q muhitda ham o'lchash SHART — aks holda Linux'da «solishtiruvchi
       ko'r emas» degan isbot butunlay yo'qolardi.
    """
    import dataclasses

    _nom, manba, *_ = manba_yurishi
    for nom, kalit, yangi in (
        (AGENT_STATUS_FILE, "state", "SOXTA_HOLAT"),
        (ENVIRONMENT_FILE, "presence_verdict", "unknown"),
    ):
        doc = json.loads(manba.fayllar[nom].decode("utf-8"))
        assert doc.get(kalit) != yangi, f"mutatsiya hech narsani o'zgartirmadi: {nom}/{kalit}"
        doc[kalit] = yangi
        buzuq = dict(manba.fayllar)
        buzuq[nom] = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        taqiq, _ruxsat = PH.farqlar(manba, dataclasses.replace(manba, fayllar=buzuq))
        yo_llar = {f.yo_l for f in taqiq}
        assert f"hujjat:{nom}/{kalit}" in yo_llar, (
            f"solishtiruvchi {nom}/{kalit} dagi o'zgarishni TOPMADI — chuqur solishtirish "
            f"ishlamayapti; topilgan farqlar: {sorted(yo_llar)}")


def _vaqti_siljigan_nusxa(yurish):
    """Yurishning nusxasi: `scanned_at` BIR SEKUNDGA siljigan, manifest xeshi QAYTA hisoblangan.

    ⚠️ Bu AYNAN tabiiy farqning o'zi: ikki jarayon bir sekundda boshlanmasa `environment.json`
       shunday farq qiladi. Qo'lda qurilgani — determinizm uchun: haqiqiy ikki yurish AYNI
       sekundda ham boshlanib qolishi mumkin (nuqson EMAS) va shunda test o'lchamoqchi
       bo'lgan narsa tasodifan yo'qolardi.
    ⚠️ KENGLIK saqlanadi (bir raqam almashtiriladi), ya'ni manifestdagi `bytes` O'ZGARMAYDI —
       shartnomaning o'zi shunday.
    """
    import dataclasses
    import hashlib

    # ⚠️⚠️ BAYT DARAJASIDA ALMASHTIRILADI, QAYTA SERIALIZATSIYA QILINMAYDI: agentning
    #      deterministik yozuv shakli (ajratgich, chekinish, oxirgi qator) `json.dumps` ning
    #      standart shakliga TENG EMAS. Qayta serializatsiya qilinganda fikstura O'ZI farq
    #      kiritardi va test o'lchamoqchi bo'lgan narsani YASHIRARDI — buni aynan shu
    #      solishtiruvchi tutdi (`bytes` 883 ↔ 882).
    eski_xom = yurish.fayllar[ENVIRONMENT_FILE]
    eski_vaqt = json.loads(eski_xom.decode("utf-8"))["scanned_at"]
    # Sekundning oxirgi raqami almashtiriladi: KENGLIK o'zgarmaydi, demak `bytes` ham.
    yangi_vaqt = eski_vaqt[:-7] + ("0" if eski_vaqt[-7] != "0" else "1") + eski_vaqt[-6:]
    assert len(yangi_vaqt) == len(eski_vaqt) and yangi_vaqt != eski_vaqt
    yangi_xom = eski_xom.replace(eski_vaqt.encode(), yangi_vaqt.encode())
    assert len(yangi_xom) == len(eski_xom) and yangi_xom != eski_xom

    # Manifestdagi xesh ham AYNI usulda: eski xeshni yangisiga (AYNI uzunlikda) almashtiramiz.
    eski_manifest = yurish.fayllar[AGENT_MANIFEST_FILE]
    eski_xesh = hashlib.sha256(eski_xom).hexdigest().encode()
    yangi_xesh = hashlib.sha256(yangi_xom).hexdigest().encode()
    assert eski_xesh in eski_manifest, \
        "manifest `environment.json` ning xeshini tutmayapti — fikstura eskirgan"
    yangi_manifest = eski_manifest.replace(eski_xesh, yangi_xesh)

    fayllar = dict(yurish.fayllar)
    fayllar[ENVIRONMENT_FILE] = yangi_xom
    fayllar[AGENT_MANIFEST_FILE] = yangi_manifest
    return dataclasses.replace(yurish, fayllar=fayllar)


def test_tabiiy_vaqt_farqi_allowlist_bilan_otadi_bosh_allowlistda_otmaydi(manba_yurishi,
                                                                         monkeypatch):
    """⚠️⚠️ ALLOWLIST ROSTDAN ISHLAYAPTI — IKKI TOMONGA ham o'lchanadi.

    (a) Allowlist BILAN: `scanned_at` ning (va uning manifestdagi oqibatining) farqi
        TAQIQLANGAN farq BO'LMAYDI, lekin RUXSAT ETILGAN farq bo'lib QAYD ETILADI — jimgina
        yo'qolmaydi.
    (b) Allowlist BO'SHATILSA: AYNAN shu ikki yo'l taqiqlangan farq bo'lib CHIQADI — ya'ni
        ruxsat bezak emas, u rostdan bir narsani o'tkazayotgan edi.

    ⚠️ Farq QO'LDA quriladi (`_vaqti_siljigan_nusxa`), haqiqiy ikki yurishdan olinmaydi:
       ular AYNI sekundda boshlanib qolsa test tasodifan HECH NARSA o'lchamasdi.
    ⚠️ Farq QO'LDA qurilgani uchun yig'ma ham KERAK EMAS: allowlistning ishlashi `.exe`
       ga bog'liq emas, demak u Linux CI'da ham o'lchanadi.
    """
    _nom, manba, *_ = manba_yurishi
    siljigan = _vaqti_siljigan_nusxa(manba)
    kutilgan_ikki = {
        f"hujjat:{ENVIRONMENT_FILE}/scanned_at",
        f"hujjat:{AGENT_MANIFEST_FILE}/files/{ENVIRONMENT_FILE}/sha256",
    }

    taqiq, ruxsat = PH.farqlar(manba, siljigan)
    assert not taqiq, PH.hisobot(manba, siljigan, taqiq)
    assert {f.yo_l for f in ruxsat} == kutilgan_ikki, \
        f"ruxsat etilgan farqlar kutilganidan boshqa: {sorted(f.yo_l for f in ruxsat)}"
    assert all(f.ruxsat for f in ruxsat), "ruxsat etilgan farqda SABAB yozilmagan"

    monkeypatch.setattr(PH, "ALLOWLIST", ())
    monkeypatch.setattr(PH, "ALLOWLIST_YO_LLARI", frozenset())
    taqiq, ruxsat = PH.farqlar(manba, siljigan)
    assert not ruxsat
    assert {f.yo_l for f in taqiq} == kutilgan_ikki, (
        "allowlist bo'shatilganda AYNAN shu ikki farq taqiqlangan bo'lishi kerak edi: "
        f"{sorted(f.yo_l for f in taqiq)}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# KODLASH — HAQIQIY NUQSONNING UCHIGA-UCH QULFI (IKKI TARAF)
# ══════════════════════════════════════════════════════════════════════════════════════════
def _cp1252ga_sigadi(ch: str) -> bool:
    try:
        ch.encode("cp1252", "strict")
        return True
    except UnicodeEncodeError:
        return False


def test_cp1252_oqim_rostdan_dushman():
    """⚠️ TISH TEKSHIRUVI: o'ramsiz `cp1252` oqim agentning HAQIQIY matnini rad etadi.

    Usiz pastdagi testlar BO'SH bo'lib qolardi: «istisno bo'lmadi» degan da'vo, oqim hamma
    narsani qabul qiladigan bo'lsa, hech narsani isbotlamaydi.
    ⚠️ Sintetik satr emas, agent ROSTDAN chop etadigan matn olinadi (operator qadamlari —
       u `⚠` ham, kirill ham ishlatadi).
    """
    from app.services.discovery_agent import collector_bridge as bridge

    haqiqiy = "\n".join(bridge.WATCH_FOLDER_OPERATOR_STEPS)
    sig_maydi = sorted({ch for ch in haqiqiy if not _cp1252ga_sigadi(ch)})
    assert sig_maydi, ("agent chop etadigan matnda cp1252'ga sig'maydigan belgi qolmadi — "
                       "himoya hali ham keraklimi? (matnlar o'zgargan bo'lishi mumkin)")
    with pytest.raises(UnicodeEncodeError):
        _Cp1252Oqim().write(haqiqiy)


def test_manba_cp1252_oqimda_yiqilmaydi_va_paket_yoziladi(tmp_path):
    """⚠️⚠️ NUQSON QULFI (MANBA, IKKINCHI qatlam): `cp1252` oqimda `main()`

    (a) ISTISNO BERMAYDI, (b) natija papkasini YOZADI (validatordan O'TADI),
    (c) chiqish kodi TO'G'RI.

    ⚠️ `_Cp1252Oqim` ning `reconfigure` i YO'Q, demak birinchi qatlam (`_utf8ga_otkaz`) JIM
       o'tadi va AYNAN `_XavfsizOqim` o'lchanadi: sig'maydigan belgi ALMASHTIRILADI va chop
       etish yurishni TO'XTATMAYDI.
    """
    kuzatilgan = tmp_path / "kuzatilgan"
    kuzatilgan.mkdir()
    RM.paket_sog_lom(str(kuzatilgan))
    natija = tmp_path / "natija"
    natija.mkdir()
    out, err = _Cp1252Oqim(), _Cp1252Oqim()
    kod = M.main(["--headless", str(kuzatilgan), "--result-dir", str(natija),
                  "--timestamp", PH.TAMGA, "--wait-seconds", PH.SOG_LOM_KUTISH],
                 out=out, err=err)
    assert kod == M.EXIT_OK, f"chiqish kodi {kod} (kutilgan {M.EXIT_OK})"
    papka = natija / rp.result_dir_name(PH.TAMGA)
    assert papka.is_dir(), "natija papkasi YOZILMADI — aynan tuzatilgan nuqsonning belgisi"
    # ⚠️ «Papka bor» YETARLI EMAS: u YAROQLI ham bo'lishi kerak (yarim yozilgan papka ham
    #    `is_dir()` ni qondirardi).
    rp.validate_result_package(str(papka))
    # ⚠️ Chop etish JIMGINA yo'qolmadi: operator ekranida matn BOR.
    chiqdi = "".join(out.yozilgan)
    assert "BinOSDiscoveryAgent" in chiqdi and st.COMPLETE in chiqdi, \
        f"operator ekrani bo'sh yoki chala: {chiqdi[:300]!r}"


def test_manba_qayta_sozlanadigan_cp1252_oqimda_belgilar_saqlanadi(tmp_path):
    """⚠️ NUQSON QULFI (MANBA, BIRINCHI qatlam): HAQIQIY `cp1252` oqim UTF-8 ga O'TKAZILADI.

    `io.TextIOWrapper` qayta sozlanadi, demak `_utf8ga_otkaz` ishlaydi va belgilar
    YO'QOLMAYDI — eng yaxshi holat. ⚠️ IKKI QATLAM ALOHIDA o'lchanadi (yuqoridagi test
    ikkinchisini oladi): bittasi olib tashlansa bitta test yiqilishi kerak, ikkitasi emas.
    """
    kuzatilgan = tmp_path / "kuzatilgan"
    kuzatilgan.mkdir()
    RM.paket_sog_lom(str(kuzatilgan))
    natija = tmp_path / "natija"
    natija.mkdir()
    xom_out, xom_err = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(xom_out, encoding="cp1252", errors="strict", newline="")
    err = io.TextIOWrapper(xom_err, encoding="cp1252", errors="strict", newline="")
    kod = M.main(["--headless", str(kuzatilgan), "--result-dir", str(natija),
                  "--timestamp", PH.TAMGA, "--wait-seconds", PH.SOG_LOM_KUTISH],
                 out=out, err=err)
    out.flush()
    err.flush()
    assert kod == M.EXIT_OK
    papka = natija / rp.result_dir_name(PH.TAMGA)
    assert papka.is_dir(), "natija papkasi YOZILMADI"
    rp.validate_result_package(str(papka))
    matn = xom_out.getvalue().decode("utf-8")
    sig_maydi = sorted({ch for ch in matn if not _cp1252ga_sigadi(ch)})
    assert sig_maydi, ("oqim UTF-8 ga o'tmadi: chiqishda cp1252'ga sig'maydigan belgi yo'q, "
                       "demak birinchi qatlam ishlamayapti (belgilar almashtirilgan)")


def test_yigma_quvur_orqali_natija_papkasini_yozadi(tmp_path):
    """⚠️⚠️ NUQSON QULFI (YIG'MA): `.exe` chiqishi QUVURGA yo'naltirilgan, kodlash `cp1252`.

    AYNAN shu sharoitda tuzatishdan OLDIN yurish chop etish paytida uzilib, natija papkasi
    UMUMAN yozilmasdi. Qulf: (a) traceback YO'Q, (b) natija papkasi yozildi va validatordan
    O'TDI, (c) chiqish kodi `0`.

    ⚠️ `PYTHONIOENCODING=cp1252` ATAYLAB QO'YILADI: mashinaning mahalliy kodlashiga tayanish
       testni muhitga bog'lab qo'yardi — UTF-8 lokalli mashinada u jimgina HECH NARSA
       sinamasdi.
    """
    _exe_darvozasi()
    kuzatilgan = PH.fikstura_yoz(str(tmp_path), "kuzatilgan", RM.paket_sog_lom)
    yurish = PH.yurgiz(PH.yigma_buyruq(), nom="YIG'MA/cp1252", kuzatilgan=kuzatilgan,
                       natija_otasi=str(tmp_path / "natija"),
                       muhit_qoshimcha={"PYTHONIOENCODING": "cp1252"})
    assert "Traceback" not in yurish.stdout + yurish.stderr, (
        f"yig'ma traceback berdi:\n{yurish.stdout[-1500:]}\n{yurish.stderr[-1500:]}")
    assert "UnicodeEncodeError" not in yurish.stdout + yurish.stderr
    assert yurish.natija_papkasi is not None, \
        "YIG'MA natija papkasini YOZMADI — aynan tuzatilgan nuqsonning belgisi"
    rp.validate_result_package(yurish.natija_papkasi)
    assert yurish.kod == 0, f"chiqish kodi {yurish.kod} (kutilgan 0)"
    # ⚠️ TISH: chiqishda `cp1252` ga SIG'MAYDIGAN belgi BOR, ya'ni himoya olib tashlansa bu
    #    yurish chop etish paytida uzilardi — test bo'sh emas.
    sig_maydi = sorted({ch for ch in yurish.stdout if not _cp1252ga_sigadi(ch)})
    assert sig_maydi, ("yig'maning chiqishida cp1252'ga sig'maydigan belgi yo'q — test "
                       "nuqsonni O'LCHAMAYAPTI (matnlar o'zgargan bo'lishi mumkin)")


def test_yigma_quvur_orqali_yiqilgan_yurishda_ham_paket_qoldiradi(tmp_path):
    """⚠️ AYNI qulf YIQILGAN yurish uchun: `cp1252` quvurda ham paket operator qo'lida qoladi.

    Yiqilish matnlari (`states.failure_meaning`) `⚠` va kirillni ENG KO'P ishlatadigan joy,
    ya'ni kodlash nuqsoni aynan shu yo'lda eng og'ir edi: operator hech narsasiz qolardi.
    """
    _exe_darvozasi()
    kuzatilgan = PH.fikstura_yoz(str(tmp_path), "kuzatilgan", None)   # BO'SH -> timeout
    yurish = PH.yurgiz(PH.yigma_buyruq(), nom="YIG'MA/cp1252-timeout",
                       kuzatilgan=kuzatilgan, natija_otasi=str(tmp_path / "natija"),
                       kutish=PH.TIMEOUT_KUTISH,
                       muhit_qoshimcha={"PYTHONIOENCODING": "cp1252"})
    assert "Traceback" not in yurish.stdout + yurish.stderr
    assert yurish.kod == 1, f"chiqish kodi {yurish.kod} (kutilgan 1)"
    assert yurish.natija_papkasi is not None, "yiqilgan yurish natija papkasini qoldirmadi"
    # ⚠️ BESHTA ILDIZ ARTEFAKTI — yiqilgan yurishda ham (nomzodlar fayli `COMPLETE` da).
    ildiz = sorted(n for n in yurish.fayllar if "/" not in n)
    assert ildiz == sorted(rp.ALWAYS_FILES), f"ildiz artefaktlari: {ildiz}"
    assert st.FAILED_TIMEOUT in yurish.stdout + yurish.stderr, \
        "operator ekranida yiqilish holati ko'rinmadi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# HARNESSNING O'ZI — solishtirish ASBOBI ham sinaladi
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_harness_ikki_yurishga_ham_ayni_tamgani_beradi():
    """⚠️⚠️ AYNI `--timestamp`: usiz farq «tabiiy» bo'lib qolardi va solishtirish ma'nosiz.

    Tamg'a `yurgiz` ning STANDART qiymatida turadi, ya'ni ikki yurish uni BIR MANBADAN
    oladi — ikki joyda yozilsa bir kun ajralib ketardi.
    """
    imzo = inspect.signature(PH.yurgiz)
    assert imzo.parameters["tamga"].default == PH.TAMGA
    assert inspect.signature(PH.ikki_yurish).parameters["tamga"].default == PH.TAMGA
    # ⚠️ Tamg'a `result_package` shartnomasiga MOS bo'lsin: aks holda ikki yurish ham
    #    «yurgizib bo'lmadi» (2) bilan tugab, test JIMGINA teng bo'lib qolardi.
    assert rp.iso_from_compact(PH.TAMGA)
    assert rp.result_dir_name(PH.TAMGA).startswith("binos-discovery-")


def test_harness_muhitni_ikki_yurish_uchun_tenglashtiradi(monkeypatch):
    """⚠️ Kodlashga ta'sir qiladigan o'zgaruvchilar OLIB TASHLANADI.

    `PYTHONIOENCODING` faqat MANBA tarafga ta'sir qilardi (interpretator o'sha), ya'ni
    solishtirish jimgina NOTENG sharoitda ketardi va «yig'ma boshqacha» degan xulosa aslida
    «manba boshqa kodlashda yurdi» bo'lib qolardi.
    """
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONPATH", "C:/begona")
    toza = PH.toza_muhit()
    for kalit in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONPATH"):
        assert kalit not in toza, f"{kalit} muhitda qoldi"
    # ⚠️ ATAYLAB berilgan qiymat esa O'TADI — kodlash testlari shunga tayanadi.
    assert PH.toza_muhit({"PYTHONIOENCODING": "cp1252"})["PYTHONIOENCODING"] == "cp1252"


def test_harness_yollarni_niqoblaydi_lekin_tashlamaydi():
    """⚠️ Mutlaq yo'l TASHLANMAYDI, yurishga NISBIY qilinadi — nuqson ko'rinib qoladi.

    Ya'ni «hisobotga mutlaq yo'l chiqib ketdi» kabi haqiqiy nuqson baribir farq bo'lib
    ko'rinadi: faqat har yurishning O'Z ildizi barqaror belgiga aylanadi.
    """
    yurish = PH.Yurish(nom="sinov", kod=0, stdout="", stderr="",
                       kuzatilgan=r"C:\a\kuzatilgan", natija_otasi=r"C:\a\res",
                       natija_papkasi=r"C:\a\res\binos-discovery-X")
    chiqish = PH.niqobla(
        "natija papkasi: C:\\a\\res\\binos-discovery-X\n"
        "kuzatilgan: C:\\a\\kuzatilgan\n"
        "begona: C:\\Windows\\System32", yurish)
    assert "<NATIJA-PAPKASI>" in chiqish and "<KUZATILGAN-PAPKA>" in chiqish
    # ⚠️ UZUNDAN QISQAGA: natija papkasi otaning ICHIDA — yarim niqoblangan qoldiq bo'lmasin.
    assert "binos-discovery-X" not in chiqish
    # ⚠️ BEGONA yo'l TEGILMAYDI: u haqiqiy farq bo'lib qolishi kerak.
    assert r"C:\Windows\System32" in chiqish


def test_harness_barglari_chuqur_yoyadi():
    """⚠️ Solishtirish CHUQUR: ichma-ich lug'at va ro'yxat BARGLARGA yoyiladi."""
    assert PH.barglar({"a": {"b": [1, {"c": "d"}]}, "bosh": {}, "royxat": []}) == {
        "a/b[0]": 1, "a/b[1]/c": "d", "bosh": "<BO'SH LUG'AT>", "royxat": "<BO'SH RO'YXAT>"}


def test_harness_yoqolgan_kalitni_farq_deb_koradi():
    """⚠️ «Bu kalit faqat bittasida bor» holati JIM YUTILMAYDI."""
    a, b = PH.barglar({"x": 1, "faqat_manbada": 2}), PH.barglar({"x": 1})
    yo_llar = {y for y in set(a) | set(b) if a.get(y, "<YO'Q>") != b.get(y, "<YO'Q>")}
    assert yo_llar == {"faqat_manbada"}


def test_harness_manifestni_nom_boyicha_kalitlaydi():
    """⚠️ `files` ro'yxati NOM bo'yicha kalitlanadi, TARTIB esa ALOHIDA solishtiriladi.

    Indeks bo'yicha solishtirilsa, ikki yurish fayllarni boshqa tartibda yozsa HAMMA satr
    «farq» bo'lib chiqardi va haqiqiy farq ko'rinmay qolardi. Tartibning o'zi ham shartnoma,
    shu bois u yo'qolmaydi — alohida maydon bo'ladi.
    """
    ko_rinish = PH._manifest_ko_rinishi(
        {"files": [{"name": "b.json", "sha256": "2", "bytes": "2"},
                   {"name": "a.json", "sha256": "1", "bytes": "1"}], "notes": ["x"]})
    assert ko_rinish["files"] == {"b.json": {"sha256": "2", "bytes": "2"},
                                 "a.json": {"sha256": "1", "bytes": "1"}}
    assert ko_rinish["files_tartibi"] == ["b.json", "a.json"]
    assert ko_rinish["notes"] == ["x"]


def test_harness_exe_yoqligini_jim_otkazmaydi():
    """⚠️ EXE yo'q bo'lsa SABAB aniq va hisobotda KO'RINADI (jim `skip` EMAS)."""
    sabab = PH.yigma_yoqligi_sababi()
    assert "PARITY TEKSHIRILMADI" in sabab
    assert PH.YIGMA_ENV_KALITI in sabab, "sabab matni yo'lni QANDAY ko'rsatishni aytmaydi"
    assert PH.YIGMA_EXE in sabab, "sabab matni QAYERGA qaralganini aytmaydi"


def test_B_yigma_joyida_TOZA_va_parity_otkazib_yuborilmadi():
    """⚠️⚠️ YIG'MA JOYIDA va JORIY MANBADAN — demak haqiqiy parity ROSTDAN o'lchangan.

    Bu test yo'q bo'lsa butun modul jimgina `skip` bo'lib, to'plam «yashil» ko'rinardi va
    hech kim parity tekshirilmaganini bilmasdi.

    ⚠️ IKKI EGA naqshi SHU YERDA ko'rinadi: Windows'da yig'ma YO'Q bo'lsa — YIQILISH;
       Linux'da — ratifikatsiya qilingan MUHIT skip'i; yig'ma BOR, lekin eskirgan yoki
       yangiligi isbotsiz bo'lsa — HAR IKKI platformada YIQILISH. Ya'ni «skip» faqat
       `.exe` ni QURIB BO'LMAYDIGAN joyda, va faqat `test_A_*` kafolatning manba
       qismini o'sha yurishda ISBOTLAGANI uchun mumkin.
    """
    _exe_darvozasi()
    assert os.path.isdir(os.path.join(os.path.dirname(PH.YIGMA_EXE), "_internal")), \
        "ONE-DIR yig'ma kutilgan: `.exe` yonida `_internal/` bo'lishi kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# OWNER A — YIG'MA SHARTNOMASI MANBADAN (`.exe` KERAK EMAS, Linux CI'da BAJARILADI)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ BU TESTLAR EXE PARITY'SINING O'RNINI BOSMAYDI. Ular `.exe` haqida HECH NARSA
#      demaydi — ular yig'ma SHARTNOMASI haqida gapiradi: yig'maga NIMA kirishi kerak,
#      NIMA taqiqlangan, kirish nuqtasi qanday va chiqish kodlari qaysi. Shartnoma
#      MANBADAN hisoblanadi, demak Linux'da ham AYNI javob chiqadi. `test_agent_packaging.py`
#      esa shu shartnomani HAQIQIY yig'ma bilan solishtiradi — o'sha tomon `.exe` ni talab
#      qiladi va Windows'da bajariladi. Ikki yarim BIRGA bitta kafolatni tashkil qiladi.


#: ⚠️⚠️ RATIFIKATSIYA QILINGAN YAGONA ZIDLIK: `migrator_1c.normalize` spec'da TAQIQLANGAN,
#:      lekin import grafida KO'RINADI — chunki `migrator_1c/bundle.py` dagi
#:      `_canon_guid_text()` FUNKSIYA ICHIDA `from .normalize import canon_guid` qiladi.
#:      Grafni o'qiydigan `_app_importlari` `ast.walk` bilan ishlaydi, ya'ni funksiya
#:      tanasiga ham kiradi va YUQORIDAN-BAHOLAYDI (over-approximation). Bu zidlik xavf
#:      EMAS, lekin u o'z-o'zidan ham xavfsiz emas: yig'madagi kod shu yo'lga TUSHSA
#:      `ModuleNotFoundError` berardi va manba bilan yig'ma AJRALARDI.
#:      ⚠️ ISBOT BU YERDA TAKRORLANMAYDI, EGASI BOR:
#:         `tests/test_agent_packaging.py::test_bundle_dan_faqat_tort_yordamchi_olinadi`
#:         yig'maga kiradigan HAR BIR manba faylini skaner qilib, `bundle` dan faqat
#:         `normalize` ga tegmaydigan TO'RT nom olinishini va `_canon_guid_text` hech
#:         qayerda ishlatilmasligini qulflaydi (u ham `.exe` SIZ ishlaydi).
#:      ⚠️ BU YERDAGI DA'VO BOSHQA: ro'yxat KENGAYMASIN. Yangi zidlik paydo bo'lsa, u
#:         ALOHIDA ko'rik talab qiladi — jimgina «ma'lum nuqson» bo'lib qolmaydi.
RATIFIKATSIYA_QILINGAN_ZIDLIK: frozenset[str] = frozenset({
    "app.services.migrator_1c.normalize",
})


def test_A_manba_yopigi_spec_TAQIQLARI_bilan_zidlashmaydi():
    """⚠️ Taqiqlangan va manbadan KERAK bo'lgan modullar kesishmasi QULFLANGAN.

    Bu spec'ning eng xavfli yolg'oni: taqiqlangan modul ASLIDA kerak bo'lsa, yig'ma yo uni
    OLIB KIRADI (taqiq yolg'on), yo kirmaydi va agent ishga tushgandan keyin shu yo'lda
    YIQILADI. Ikkisi ham `.exe` SIZ, faqat manbadan aniqlanadi — demak Linux CI'da.
    """
    yopiq = PKG._manbadan_yetib_boriladigan()
    assert len(yopiq) > 15, f"import grafi juda kichik — o'qish usuli buzilgan: {sorted(yopiq)}"
    zid = {m for t in PH.spec_royxati("EXCLUDES") for m in yopiq
           if PH.taqiq_qamraydi(m, t)}
    assert zid == set(RATIFIKATSIYA_QILINGAN_ZIDLIK), (
        f"Spec taqiqlari va manba zidligi O'ZGARDI. Kutilgan (ratifikatsiya qilingan): "
        f"{sorted(RATIFIKATSIYA_QILINGAN_ZIDLIK)}; topilgan: {sorted(zid)}. "
        f"YANGI zidlik — STOP: taqiqlangan modul yig'mada KERAK bo'lib qolgan, demak yoki "
        f"spec yolg'on kafolat beradi, yoki yig'ma shu yo'lda `ModuleNotFoundError` beradi.")


def test_A_ratifikatsiya_qilingan_zidlik_hali_ham_KECHIKKAN_import():
    """⚠️⚠️ YUQORIDAGI RUXSATNING SHARTI: `normalize` importi MODUL DARAJASIDA BO'LMASIN.

    Agar `from .normalize import canon_guid` bir kun `bundle.py` ning tepasiga ko'chsa,
    yig'ma uni IMPORT PAYTIDA talab qilardi va agent UMUMAN ishga tushmasdi — ya'ni
    ratifikatsiya qilingan «xavf yo'q» xulosasi YOLG'ON bo'lib qolardi, lekin ro'yxat
    o'zgarmagani uchun yuqoridagi test baribir YASHIL bo'lardi. Shu bois ruxsatning SHARTI
    alohida qulflanadi: import FUNKSIYA ICHIDA va AYNAN `_canon_guid_text` da.
    """
    yo_l = pathlib.Path(PH.SERVER_ROOT) / "app" / "services" / "migrator_1c" / "bundle.py"
    daraxt = ast.parse(yo_l.read_text(encoding="utf-8"))

    def normalize_importlari(tugun) -> list[ast.ImportFrom]:
        return [n for n in ast.walk(tugun) if isinstance(n, ast.ImportFrom)
                and (n.module or "").endswith("normalize")]

    # (a) MODUL DARAJASIDA bo'lmasin: yuqori darajadagi yozuvlar ichida yo'q.
    yuqorida = [n for n in daraxt.body if isinstance(n, ast.ImportFrom)
                and (n.module or "").endswith("normalize")]
    assert not yuqorida, (
        "`migrator_1c/bundle.py` da `normalize` importi MODUL DARAJASIGA ko'chgan — "
        "yig'ma endi import paytida `normalize` ni talab qiladi va ishga TUSHMAYDI. "
        "Spec'ning `excludes` ro'yxatini QAYTA ko'rib chiqing.")
    # (b) va u AYNAN ratifikatsiya qilingan funksiyada.
    egalar = sorted(f.name for f in ast.walk(daraxt)
                    if isinstance(f, ast.FunctionDef) and normalize_importlari(f))
    assert egalar == ["_canon_guid_text"], (
        f"`normalize` ni chaqiradigan funksiyalar o'zgardi: {egalar} (kutilgan "
        f"`_canon_guid_text`). Har yangi egasi `test_bundle_dan_faqat_tort_yordamchi_"
        f"olinadi` darvozasi bilan QAYTA ko'rilishi kerak.")
    assert normalize_importlari(daraxt), \
        "`normalize` importi umuman yo'qolgan — ratifikatsiya ESKIRGAN, ro'yxatni tozalang"


def test_A_migrator_dan_MANBADAN_faqat_bundle_ga_yetib_boriladi():
    """⚠️ Migrator APPLY yig'maga KIRMASLIGI kerak — va u TRANZITIV ham tortilmaydi.

    `test_agent_packaging.py` buni YIG'MA ichida o'lchaydi (`.exe` kerak). Bu yerda AYNI
    da'vo MANBADAN o'lchanadi: import grafida `migrator_1c` dan faqat paketning o'zi,
    `bundle` va ratifikatsiya qilingan kechikkan `normalize` ko'rinadi. Shu bois
    `__init__.py` ga bir kun import qo'shilsa, darvoza Linux'da ham DARHOL qizil bo'ladi —
    yig'ma qurilishini kutmasdan.
    """
    migrator = {m for m in PKG._manbadan_yetib_boriladigan()
                if PH.taqiq_qamraydi(m, "app.services.migrator_1c")}
    assert migrator == {"app.services.migrator_1c", "app.services.migrator_1c.bundle",
                        *RATIFIKATSIYA_QILINGAN_ZIDLIK}, \
        f"migrator_1c dan kutilmagan modul kerak bo'lib qoldi: {sorted(migrator)}"
    assert "app.services.migrator_1c.apply" in PH.spec_royxati("EXCLUDES"), \
        "APPLY `excludes` dan tushib qolgan — tranzitiv import qo'shilsa to'siq yo'q"


def test_A_spec_taqiqlari_HIMOYA_oilalarini_qamraydi():
    """⚠️⚠️ TAQIQ RO'YXATI QISQARTIRILMASIN: «agent offline va faqat-o'qish» da'vosi shunga
    tayanadi.

    Ro'yxatdan bir satr jimgina olib tashlanishi mumkin edi va buni FAQAT yig'ma qurilgan
    mashinada sezardik. Bu test uni MANBADA qulflaydi.
    ⚠️ To'liq ro'yxat KO'CHIRILMAYDI (u spec'da yashaydi): tekshiriladigan narsa — HAR
       HIMOYA OILASIDAN kamida bitta nomning borligi, ya'ni oila butunlay yo'qolmagani.
    """
    taqiqlar = set(PH.spec_royxati("EXCLUDES"))
    oilalar = {
        "migrator APPLY": {"app.services.migrator_1c.apply"},
        "testlar": {"pytest", "_pytest"},
        "server freymvorki": {"fastapi", "starlette", "uvicorn"},
        "ma'lumotlar bazasi": {"sqlalchemy", "psycopg", "asyncpg", "sqlite3"},
        "tarmoq": {"requests", "httpx", "urllib3", "smtplib", "ftplib"},
        "ishlab chiquvchi vositalari": {"setuptools", "pip", "pkg_resources"},
    }
    yoq = {nom: sorted(kerak - taqiqlar) for nom, kerak in oilalar.items()
           if kerak - taqiqlar}
    assert not yoq, f"spec `excludes` dan HIMOYA nomlari tushib qolgan: {yoq}"


def test_A_hidden_importlar_tkinter_OILASINI_qamraydi():
    """⚠️ `tkinter` himoyalangan `import` ichida — statik tahlil uni O'TKAZIB YUBORADI.

    `hiddenimports` qisqarsa yig'ma oynasiz chiqib ketardi va buni faqat operator
    mashinasida sezardik. Shartnoma MANBADA qulflanadi.
    """
    hidden = set(PH.spec_royxati("HIDDEN"))
    kerak = {"tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"}
    assert kerak <= hidden, f"`hiddenimports` dan tushib qolgan: {sorted(kerak - hidden)}"


def test_A_kirish_nuqtasi_main_ga_YUPQA_oram_va_chiqish_kodlari_MOS():
    """⚠️⚠️ KIRISH NUQTASI SHARTNOMASI: yig'ma `__main__.main` ni chaqiradi, MANTIQ
    TAKRORLAMAYDI.

    PyInstaller `python -m <paket>` ni emas, SKRIPTni yig'adi — ya'ni yig'ma va manba
    AJRALIB KETISHI mumkin bo'lgan yagona joy shu fayl. Shu bois u AST bilan o'qiladi:
    ichida `app.*` dan FAQAT `__main__` import qilinishi va olinadigan nomlar AYNAN
    `main` + `EXIT_CANNOT_RUN` bo'lishi tekshiriladi. Bu `.exe` SIZ isbotlanadi.
    """
    daraxt = ast.parse(pathlib.Path(PH.ENTRY_YOLI).read_text(encoding="utf-8"))
    manbalar: dict[str, set[str]] = {}
    for n in ast.walk(daraxt):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app"):
            manbalar.setdefault(n.module, set()).update(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            for a in n.names:
                assert not a.name.startswith("app"), \
                    f"kirish skripti `app` ni TO'G'RIDAN-TO'G'RI import qilmasin: {a.name}"
    assert manbalar == {
        "app.services.discovery_agent.__main__": {"main", "EXIT_CANNOT_RUN"}}, \
        f"kirish skriptining `app.*` importlari kutilganidan boshqa: {manbalar}"
    # ⚠️ CHIQISH KODI SHARTNOMASI: skriptning docstring'i uchta kodni e'lon qiladi, demak
    #    ular `__main__` da AYNI qiymatda bo'lishi SHART (0/1/2) — aks holda operator
    #    skriptlari jimgina boshqa ma'no o'qirdi.
    assert (M.EXIT_OK, M.EXIT_FAILED_RUN, M.EXIT_CANNOT_RUN) == (0, 1, 2), (
        f"chiqish kodi shartnomasi o'zgardi: {M.EXIT_OK}/{M.EXIT_FAILED_RUN}/"
        f"{M.EXIT_CANNOT_RUN} — kirish skriptining hujjati va operator skriptlari buziladi")


def test_A_manba_imzosi_HAMMA_yigma_kirishini_qamraydi():
    """⚠️ Yig'ma imzosi: agent + `discovery_1c` yadrosi + `bundle` + spec + kirish skripti.

    Imzo TO'LIQ bo'lmasa eskirgan-yig'ma darvozasining hisobotдаги raqami yolg'on bo'lardi.
    ⚠️ Taqiqlangan modul (`migrator_1c/apply.py`) imzoga KIRMASLIGI ham tekshiriladi: u
       yig'maga kirmaydi, demak uning o'zgarishi yig'mani eskirtirmaydi.
    """
    kirishlar = PH.manba_kirishlari()
    for kerak in ("app/services/discovery_agent/__main__.py",
                  "app/services/discovery_agent/detector.py",
                  "app/services/discovery_1c/redact.py",
                  "app/services/migrator_1c/bundle.py",
                  "packaging/binos_agent_entry.py",
                  "packaging/BinOSDiscoveryAgent.spec"):
        assert kerak in kirishlar, f"yig'ma imzosida kirish YO'Q: {kerak}"
    assert "app/services/migrator_1c/apply.py" not in kirishlar, \
        "TAQIQLANGAN modul yig'ma imzosiga kirib qolgan"
    assert not any(k.endswith(".pyc") or "__pycache__" in k for k in kirishlar), \
        "imzoga `.pyc` tushgan — u Python versiyasiga bog'liq va imzoni beqaror qiladi"
    assert len(PH.manba_xeshi()) == 64


def test_A_manba_imzosini_JAMLASH_TISHLI():
    """⚠️ Jamlash KO'R EMAS: bitta fayl o'zgarsa ham, QAYTA NOMLANSA ham imzo o'zgaradi.

    Aks holda «yig'ma eskirdimi» savobiga ishlatiladigan raqam bezak bo'lib qolardi.
    ⚠️ Diskka TEGMAYDI: sintetik kirish lug'ati bilan o'lchanadi, demak boshqa testlarning
       fayllariga bog'liq emas.
    """
    asos = {"a.py": "11", "b.py": "22"}
    assert PH.xesh_jamlash(asos) == PH.xesh_jamlash({"b.py": "22", "a.py": "11"}), \
        "jamlash kalit TARTIBIGA bog'liq — imzo beqaror bo'lardi"
    assert PH.xesh_jamlash(asos) != PH.xesh_jamlash({"a.py": "11", "b.py": "23"}), \
        "fayl MAZMUNI o'zgardi, imzo esa o'zgarmadi"
    assert PH.xesh_jamlash(asos) != PH.xesh_jamlash({"a.py": "11", "c.py": "22"}), \
        "fayl QAYTA NOMLANDI, imzo esa o'zgarmadi"
    assert PH.xesh_jamlash(asos) != PH.xesh_jamlash({**asos, "c.py": "33"}), \
        "YANGI fayl qo'shildi, imzo esa o'zgarmadi"


def test_A_spec_ikki_oquvchi_BITTA_javob_beradi():
    """⚠️⚠️ DRIFT QO'RIQCHISI: spec'ni ikki modul o'qiydi — ikkisi AYNI javobni berishi SHART.

    `parity_harness.spec_royxati` (OWNER A) va `test_agent_packaging._spec_excludes`
    (yig'ma tarkibi darvozasi) bir xil faylni mustaqil o'qiydi. Biri o'zgarib, ikkinchisi
    qolsa — ikki darvoza jimgina BOSHQA ro'yxatni qo'riqlardi.
    """
    assert PH.spec_royxati("EXCLUDES") == PKG._spec_excludes(), (
        "spec'ning ikki o'quvchisi BOSHQA ro'yxat berdi — biri eskirgan")


def test_A_yigma_ILDIZI_UCH_modulda_AYNI():
    """⚠️⚠️ DRIFT QO'RIQCHISI: UCHTA darvoza (parity · yig'ma tarkibi · portativlik) AYNI
         yig'mani tekshirsin.

    Ilgari `test_agent_packaging.py` ildizni QO'LDA `C:/Users/Developer/...` deb yozardi —
    ya'ni (a) ishlab chiquvchining mutlaq yo'li (spec'ning O'Z qoidasiga zid) va (b) ikki
    fayl BOSHQA yig'mani tekshirishi mumkin edi: biri eskisini «toza» deb, ikkinchisi
    yangisini o'lchab. Endi hammasi AYNI muhit o'zgaruvchisidan keladi.

    ⚠️ UCHINCHISI 2026-10-02 da QO'SHILDI: `tests/test_agent_portability.py` AYNI
       qotirilgan yo'lni saqlab qolgan edi va bu qo'riqchi uni QAMRAMAGANI uchun drift
       ko'rinmay turardi — ya'ni «ikki modulda AYNI» kafolati UCHINCHI modulni nazardan
       chetda qoldirardi.
    """
    assert PKG._YIGMA_ILDIZ == PH.YIGMA_ILDIZ, (
        f"yig'ma ildizi parity/packaging da BOSHQA: {PKG._YIGMA_ILDIZ} vs {PH.YIGMA_ILDIZ}")
    assert PKG._BUILD == pathlib.Path(PH.YIGMA_BUILD), (
        f"build papkasi ikki modulda BOSHQA: {PKG._BUILD} vs {PH.YIGMA_BUILD}")
    assert PORT._YIGMA_ILDIZ == PH.YIGMA_ILDIZ, (
        f"yig'ma ildizi portativlik modulida BOSHQA: {PORT._YIGMA_ILDIZ} vs "
        f"{PH.YIGMA_ILDIZ}")
    assert PORT._DIST == PKG._DIST, (
        f"dist papkasi portativlik va yig'ma-tarkibi modullarida BOSHQA: {PORT._DIST} vs "
        f"{PKG._DIST}")


def test_A_manba_yurishi_KUTILGAN_yolgacha_bordi(manba_yurishi):
    """⚠️ Ssenariy AYNAN o'lchamoqchi bo'lgan holatga yetdi — `.exe` SIZ ham.

    `test_ssenariy_kutilgan_yolgacha_bordi` AYNI da'voni IKKI yurish uchun o'lchaydi, lekin
    u `.exe` ni talab qiladi. Bu yerda MANBA tarafning o'zi tekshiriladi: fikstura hali ham
    kutilgan qarorni keltirib chiqaradi, ya'ni Linux'da ssenariylar JIM o'lib qolmaydi.
    ⚠️ `presence_verdict` BU YERDA tekshirilmaydi va bu ataylab: u HOST ga bog'liq
       (CI mashinasida 1C yo'q, lekin reyestr/fayl tizimi boshqa javob berishi mumkin).
       Hukmning `absent` bo'lishi `.exe` li testda, AYNI mashinada, ikki yurish uchun
       solishtirilganda o'lchanadi.
    """
    _nom, manba, kutilgan_holat, kutilgan_kod, _paket = manba_yurishi
    s = PH.semantik(manba)
    assert s["terminal_holat"] == kutilgan_holat, \
        f"holat {s['terminal_holat']} (kutilgan {kutilgan_holat})"
    assert s["chiqish_kodi"] == kutilgan_kod, \
        f"kod {s['chiqish_kodi']} (kutilgan {kutilgan_kod})"
    assert s["natija_papkasi_yozildi"], "yiqilgan yurish ham natija papkasini QOLDIRADI"
    assert s["route"] == "watch_folder", f"yo'l {s['route']}"
    assert s["paket_nuqsonlari"] == [], f"natija paketi validatordan o'tmadi: " \
                                        f"{s['paket_nuqsonlari']}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# OWNER B — ESKIRGAN YIG'MA DARVOZASI (brief: «eskirgan EXE jimgina o'tmasligi SHART»)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ TOPILGAN HAQIQIY TESHIK (bu darvoza yozilgan kun, shu worktree'da): manbada
#      `redact.py`, `detector.py` va `launcher.py` o'zgargan edi, mahalliy `.exe` esa
#      ularning ESKI nusxasi bilan qurilgan — va parity to'plami 3067/3067 YASHIL o'tdi.
#      Ya'ni «yig'ma manbaga teng» degan kafolat o'sha yurishda ASOSSIZ edi: o'zgarishlar
#      tanlangan fiksturada kuzatiladigan farq bermadi. Darvoza shuni topadi.


def test_B_imzo_bitta_SATR_ozgarsa_FARQ_beradi():
    """⚠️⚠️ TISH: eskirgan-yig'ma darvozasining solishtiruvchisi KO'R EMAS.

    Usiz `yigma_tayyorligi()` ning «TOZA» javobi hech narsani isbotlamasdi: hamma narsani
    teng deb ko'radigan solishtiruvchi ham AYNI javobni berardi.
    """
    asos = "def f(x):\n    return x + 1\n"
    buzuq = "def f(x):\n    return x + 2\n"
    a = PH.kod_imzosi(compile(asos, "f.py", "exec", dont_inherit=True, optimize=0))
    b = PH.kod_imzosi(compile(buzuq, "f.py", "exec", dont_inherit=True, optimize=0))
    assert a != b, "bitta konstanta o'zgardi, imzo esa o'zgarmadi"
    # ⚠️ ICHKI funksiya ham qamraladi: yuqori daraja o'zgarmasa ham farq ko'rinishi kerak.
    ichki_a = "def o():\n    def ich():\n        return 1\n    return ich\n"
    ichki_b = "def o():\n    def ich():\n        return 2\n    return ich\n"
    assert PH.kod_imzosi(compile(ichki_a, "f.py", "exec", dont_inherit=True, optimize=0)) \
        != PH.kod_imzosi(compile(ichki_b, "f.py", "exec", dont_inherit=True, optimize=0)), \
        "ichki funksiyadagi o'zgarish imzoda ko'rinmadi — rekursiya ishlamayapti"


def test_B_imzo_YOLGON_FARQ_bermaydi():
    """⚠️⚠️ YOLG'ON QIZIL HAM NUQSON: sog'lom yig'ma «eskirgan» deb ko'rsatilmasin.

    Bu sintetik ehtimollik emas, HAQIQATAN uchragan tuzoq: solishtiruvchining birinchi
    nusxasi `co_consts` ni `repr()` bilan o'qirdi va `in {...}` dan kelgan `frozenset`
    ning `repr` TARTIBI satr xeshiga (ya'ni JARAYONGA) bog'liq bo'lgani uchun
    `redact.py` va `result_package.py` jimgina FARQ bo'lib chiqdi — garchi ikkisi ham
    o'zgarmagan edi. Agar darvoza shunday qolsa, operator uni «shovqin» deb o'chirib
    qo'yardi va kafolat yo'qolardi.
    """
    # (a) to'plam konstantasi TARTIBGA bog'liq emas.
    assert PH._konst_imzosi(frozenset(("a", "b", "c"))) \
        == PH._konst_imzosi(frozenset(("c", "a", "b")))
    imzo = PH._konst_imzosi(frozenset(("b", "a")))
    assert imzo[0] == "set" and list(imzo[1]) == sorted(imzo[1]), \
        "to'plam imzosi TARTIBLANMAGAN — `repr` tuzog'i qaytib kelgan"
    # (b) `nan` o'z-o'ziga teng emas, lekin imzosi TENG bo'lishi kerak.
    assert PH._konst_imzosi(float("nan")) == PH._konst_imzosi(float("nan")), \
        "`nan` konstantasi sog'lom yig'mani «eskirgan» qilardi"
    # (c) AYNI manbani ikki marta kompilyatsiya qilish AYNI imzo beradi.
    manba = "A = {'x', 'y', 'z'}\nB = 0.1\nC = (1, True, None, b'z')\n"
    assert PH.kod_imzosi(compile(manba, "m.py", "exec", dont_inherit=True, optimize=0)) \
        == PH.kod_imzosi(compile(manba, "m.py", "exec", dont_inherit=True, optimize=0))
    # (d) TUR esa AJRATILADI: `1` va `True` bytecode'da BOSHQA konstanta.
    assert PH._konst_imzosi(1) != PH._konst_imzosi(True), \
        "`1` va `True` imzoda aralashdi — haqiqiy o'zgarish ko'rinmay qolardi"


def test_B_darvoza_EXE_YOQ_bolsa_YO_Q_deydi(monkeypatch, tmp_path):
    """⚠️ Darvozaning birinchi holati: yig'ma umuman YO'Q (Linux CI'dagi holat)."""
    monkeypatch.setattr(PH, "YIGMA_EXE", str(tmp_path / "umuman-yoq.exe"))
    holat, sabab = PH.yigma_tayyorligi()
    assert holat == PH.HOLAT_YOQ
    # ⚠️ Sabab MUHIT sababi bo'lishi SHART va `ci_expected_skips.txt` dagi bo'lak bilan
    #    AYNAN mos kelishi kerak — aks holda ratifikatsiya qilingan skip CI'da mos
    #    kelmaydi va backend job QIZIL bo'ladi.
    assert PH.MUHIT_SABABI in sabab
    assert "BUILD_GATE.md" in sabab, "sabab matni ikkinchi egani (reliz darvozasi) aytmaydi"
    assert "test_A_" in sabab, "sabab matni Linux'da NIMA isbotlanganini aytmaydi"


def test_B_darvoza_PYZ_YOQ_bolsa_ISBOTSIZ_deydi(monkeypatch, tmp_path):
    """⚠️⚠️ ENG MUHIM HOLAT: yig'ma BOR, lekin yangiligini isbotlab BO'LMAYDI.

    Bunda darvoza «toza» DEMAYDI va `skip` ham BERMAYDI — natija ISBOTSIZ bo'lib
    yiqiladi. Aks holda build papkasini tozalagan operator eskirgan `.exe` bilan
    yashil parity olardi.
    """
    exe = tmp_path / "BinOSDiscoveryAgent.exe"
    exe.write_bytes(b"soxta")
    monkeypatch.setattr(PH, "YIGMA_EXE", str(exe))
    monkeypatch.setattr(PH, "YIGMA_BUILD", str(tmp_path / "build-yoq"))
    holat, sabab = PH.yigma_tayyorligi()
    assert holat == PH.HOLAT_ISBOTSIZ, f"holat {holat} — isbotsizlik «toza» ga aylandi"
    assert "ISBOTSIZ" in sabab and PH.MUHIT_SABABI not in sabab, \
        "isbotsizlik MUHIT sababi bo'lib ko'rinmasin — u skip bo'lib o'tib ketardi"


def test_B_darvoza_build_exe_FARQ_qilsa_ISBOTSIZ_deydi(monkeypatch, tmp_path):
    """⚠️ Build papkasidagi PYZ TARQATILADIGAN `.exe` ni tasvirlashi ISBOTLANSIN.

    Build papkasi oldingi yurishdan qolgan bo'lsa PYZ boshqa yig'mani tasvirlaydi va
    solishtirish YOLG'ON «toza» berardi.
    """
    build = tmp_path / "build"
    build.mkdir()
    (build / PH.PYZ_FAYL_NOMI).write_bytes(b"PYZ\0" + b"\0" * 8)
    (build / PH.BUILD_EXE_NOMI).write_bytes(b"eski yig'ma")
    exe = tmp_path / "BinOSDiscoveryAgent.exe"
    exe.write_bytes(b"yangi yig'ma")
    monkeypatch.setattr(PH, "YIGMA_EXE", str(exe))
    monkeypatch.setattr(PH, "YIGMA_BUILD", str(build))
    holat, sabab = PH.yigma_tayyorligi()
    assert holat == PH.HOLAT_ISBOTSIZ
    assert PH.PYZ_FAYL_NOMI in sabab


def test_B_darvoza_BOSHQA_python_bilan_qurilgan_yigmani_ISBOTSIZ_deydi(monkeypatch, tmp_path):
    """⚠️ Boshqa Python bilan qurilgan yig'maning bytecode'i BOSHQA bo'ladi.

    Bunda «eskirgan» deb aytish ham, «toza» deb aytish ham YOLG'ON bo'lardi: solishtirish
    MA'NOSIZ. Darvoza ISBOTSIZ beradi va yiqiladi — jim o'tish YO'Q.
    """
    build = tmp_path / "build"
    build.mkdir()
    begona_magic = bytes(b ^ 0xFF for b in importlib.util.MAGIC_NUMBER)
    (build / PH.PYZ_FAYL_NOMI).write_bytes(b"PYZ\0" + begona_magic + b"\0" * 4)
    (build / PH.BUILD_EXE_NOMI).write_bytes(b"ayni")
    exe = tmp_path / "BinOSDiscoveryAgent.exe"
    exe.write_bytes(b"ayni")
    monkeypatch.setattr(PH, "YIGMA_EXE", str(exe))
    monkeypatch.setattr(PH, "YIGMA_BUILD", str(build))
    holat, sabab = PH.yigma_tayyorligi()
    assert holat == PH.HOLAT_ISBOTSIZ
    assert "BOSHQA Python" in sabab


def test_B_darvoza_BOSH_PYZ_ni_TOZA_demaydi(monkeypatch, tmp_path):
    """⚠️⚠️ SHAKL DARVOZASI: agent modullari topilmasa «hammasi mos» degan xulosa BO'SH.

    PyInstaller arxiv shaklini o'zgartirsa yoki o'qish usuli buzilsa, `eskirgan_modullar()`
    bo'sh ro'yxat qaytarib darvozani JIMGINA yashil qilardi — bu solishtiruvchi o'lganini
    yashiradigan eng xavfli holat.
    """
    build = tmp_path / "build"
    build.mkdir()
    bosh_toc = marshal.dumps([("os", (0, 0, 0))])
    xom = b"PYZ\0" + importlib.util.MAGIC_NUMBER + struct.pack("!i", 12) + bosh_toc
    (build / PH.PYZ_FAYL_NOMI).write_bytes(xom)
    (build / PH.BUILD_EXE_NOMI).write_bytes(b"ayni")
    exe = tmp_path / "BinOSDiscoveryAgent.exe"
    exe.write_bytes(b"ayni")
    monkeypatch.setattr(PH, "YIGMA_EXE", str(exe))
    monkeypatch.setattr(PH, "YIGMA_BUILD", str(build))
    holat, sabab = PH.yigma_tayyorligi()
    assert holat == PH.HOLAT_ISBOTSIZ, f"bo'sh PYZ «{holat}» bo'lib o'tdi"
    assert "o'qish usuli buzilgan" in sabab


def test_B_darvoza_HAQIQIY_yigmani_MODULMA_MODUL_oqiydi():
    """⚠️ Darvoza HAQIQIY yig'mada ham ishlaydi: `app.*` modullari O'QILDI va solishtirildi.

    ⚠️ `toza_shart=False`: bu test «yig'ma toza» degan da'voni emas, DARVOZANING O'ZI
       haqiqiy arxivni o'qiy olishini o'lchaydi. Eskirgan yig'mada ham bajarilishi kerak —
       aks holda darvoza aynan kerak bo'lgan paytda tekshirilmagan bo'lib qolardi.
    ⚠️ `.exe` yo'q platformada MUHIT skip'i (ratifikatsiya qilingan).
    """
    _exe_darvozasi(toza_shart=False)
    _xom, toc = PH.pyz_toc()
    app = sorted(n for n in toc if n == "app" or n.startswith("app."))
    assert len(app) > 25, f"yig'mada `app.*` modullari juda kam: {len(app)}"
    assert "app.services.discovery_agent.__main__" in app
    assert "app.services.discovery_1c.redact" in app
    # ⚠️ TAQIQLANGAN modul arxivda BO'LMASIN (yig'ma tarkibi darvozasining mustaqil
    #    takrori emas: bu yerda manba PYZ arxivi, u yerda yig'uvchi manifesti).
    assert not [n for n in app if PH.taqiq_qamraydi(n, "app.services.migrator_1c.apply")], \
        "migrator APPLY yig'ma arxividan topildi"
    # ⚠️ Solishtirish TRIVIAL emas: modullarning KO'PCHILIGI mos kelishi kerak. Hammasi
    #    farq qilsa — usul buzilgan, hech biri farq qilmasa — tish yo'q (u yuqorida
    #    sintetik manba bilan alohida o'lchangan).
    nomos = PH.eskirgan_modullar()
    assert len(nomos) < len(app) / 2, (
        f"yig'madagi modullarning yarmidan ko'pi manbaga mos kelmadi ({len(nomos)}/{len(app)}) "
        f"— solishtirish usuli buzilgan bo'lishi mumkin: {nomos[:10]}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# OWNER B — DARVOZANING SIMLANISHI VA QAMROVI (⚠️ MUSTAQIL KO'RIK TOPGAN TESHIK)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ NEGA BU BO'LIM BOR — O'LCHANGAN TESHIK, taxmin EMAS. Yig'maga tayanadigan BESH
#      modulning TO'RTTASIDA (`test_agent_packaging.py:405`, `test_agent_portability.py:337`,
#      `test_agent_packaged_e2e.py:242`, `test_agent_packaged_safety.py:586`) darvoza SIMINI
#      AST bilan TALAB qiladigan test bor. SHU MODULDA U YO'Q edi, chunki uning darvozasi
#      `_dist_talab()` emas, `_exe_darvozasi()` (yuqorida).
#
#      Oqibati O'LCHANDI: `_exe_darvozasi()` ning BESH chaqiruv joyini olib tashlasa,
#      inventar qo'riqchisi (`tests/test_agent_build_inventory.py`) 6/6 YASHIL qolardi — u
#      modul MATNIDA `pytest.skip`/`pytest.fail` izini izlaydi, izlar esa darvoza
#      TA'RIFIDA va docstringlarda SAQLANADI. Ya'ni STRUKTURAVIY detektsiya NOL edi.
#      Mahalliy Windows'da yiqilish faqat TASODIFAN kelardi (fikstura `.exe` yo'qligidan
#      yiqilardi); TOZA yig'ma BOR Windows CI'da esa parity darvozasi JIMGINA o'tib
#      ketardi va «parity o'lchandi» degan YOLG'ON kafolat qolardi.
#
# ⚠️ `_chaqirilgan_nomlar()` QAYTA YOZILMAYDI va BESHINCHI NUSXA OLINMAYDI: u allaqachon
#    `test_agent_packaging.py` da bor, bu modul esa o'sha moduldan ALLAQACHON `PKG`
#    sifatida import qiladi (`cp1252` oqimi va spec o'quvchisi ham shu yerdan olinadi —
#    yuqoridagi import izohi). Ikki nusxa bir kun bir-biridan ajralib ketardi.

#: ⚠️⚠️ DARVOZA QAMROVI — {funksiya nomi: `toza_shart` ning KUTILGAN MA'NOSI}.
#:      `True`  — QAT'IY: faqat TOZA yig'ma DAVOM etadi (kwarg BERILMAYDI, ya'ni imzodagi
#:                standart ishlaydi; `toza_shart=True` ni OCHIQ yozish ham qabul qilinadi).
#:      `False` — ATAYLAB YUMSHOQ: darvozaning O'ZINI o'lchaydigan test. U eskirgan
#:                yig'mada ham BAJARILISHI kerak, aks holda darvoza AYNAN kerak bo'lgan
#:                paytda tekshirilmagan bo'lib qolardi. SHU MODULDA U AYNAN BITTA.
#: ⚠️ Ro'yxat AYNAN teng bo'lishi talab qilinadi — IKKI TOMONLAMA:
#:      · chaqiruv YO'QOLSA (mutatsiya M2) test QIZIL beradi;
#:      · yangi, darvozaga tayanadigan test JIMGINA qo'shilsa ham QIZIL beradi — bu
#:        `tests/ci_expected_skips.txt` ga ratifikatsiya YOZILISHI shart bo'lgan YANGI
#:        Linux skip'i degani (ro'yxatning EGASI: `test_agent_build_inventory.py` §4).
EXE_DARVOZAGA_TAYANADIGANLAR: dict[str, bool] = {
    # Uch ssenariyni IKKI yurish bilan yurgizadigan fikstura — undan 4 test × 3 param
    # oziqlanadi, ya'ni BU chaqiruv yo'qolsa 12 test darvozasiz qolardi.
    "juftlik": True,
    "test_yigma_quvur_orqali_natija_papkasini_yozadi": True,
    "test_yigma_quvur_orqali_yiqilgan_yurishda_ham_paket_qoldiradi": True,
    "test_B_yigma_joyida_TOZA_va_parity_otkazib_yuborilmadi": True,
    # ⚠️ ATAYLAB YUMSHOQ — pastdagi testda OCHIQ qulflangan, YOLG'ON QIZIL EMAS.
    "test_B_darvoza_HAQIQIY_yigmani_MODULMA_MODUL_oqiydi": False,
}

#: ⚠️ DARVOZANING O'ZINI o'lchaydigan testlar: ular HAQIQIY `.exe` ga TEGMAYDI (harness
#:    hukmi `monkeypatch` bilan almashtiriladi), demak Linux'da ham BAJARILADI va
#:    `ci_expected_skips.txt` ga YOZILMAYDI. Ular ham darvozani chaqiradi, shu bois
#:    qamrov TENGLIGIDA hisobga olinadi — aks holda tenglik yolg'on qizil berardi.
EXE_DARVOZANI_OZINI_SINOVCHILAR: frozenset[str] = frozenset({
    "test_B_darvoza_QAROR_JADVALI_holatma_holat_qulflangan",
})


class _KwargBerilmagan:
    """`toza_shart` UMUMAN berilmagan chaqiruv — imzodagi STANDART qiymat ishlaydi."""

    def __repr__(self) -> str:
        return "<kwarg BERILMAGAN>"


_STANDART = _KwargBerilmagan()


# ──────────────────────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ QAMROV O'LCHOVINING MEZONI — «BAJARILADIGAN YO'LDAGI CHAQIRUV»
# ──────────────────────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ NEGA MEZON KERAK — O'LCHANGAN TESHIK (F-1), taxmin EMAS. Ilgari qamrov o'lchovi
#      yuqori darajadagi funksiya ichida `ast.walk` qilardi, ya'ni tugunning JOYIGA
#      QARAMASDI. Shu bois IKKI shakl «darvoza chaqirilgan» deb SANALARDI, holbuki
#      chaqiruv HECH QACHON BAJARILMAYDI:
#        · B2 — test tanasidan CHAQIRILMAYDIGAN ichki funksiya:
#               `def _olik_ichki(): _exe_darvozasi()`
#        · B4 — ANIQ o'lik shox: `if False: _exe_darvozasi()`
#      Umumiy sanoq (`_exe_darvoza_chaqiruv_soni()`) ham AYNI tugunni sanaganligi uchun
#      «TISH» assert'i ham MOS kelardi. O'LCHANGAN OQIBAT: harness hukmi ESKIRGAN qilib
#      qo'yilganda `test_yigma_quvur_orqali_natija_papkasini_yozadi` ASL kodda `1 failed`,
#      B2/B4 bilan esa `1 passed` berardi; uchala darvoza qo'riqchisi (SIMI/QAMROVI/
#      QAROR_JADVALI) va inventar qo'riqchisi esa YASHIL qolardi — ya'ni ESKIRGAN yig'ma
#      parity'dan JIMGINA o'tib ketardi.
#
# ⚠️ MEZON (ANIQ TA'RIF). Chaqiruv faqat SHU uch shartning HAMMASI bajarilganda sanaladi:
#      1. u YUQORI DARAJADAGI `FunctionDef` ning TANASIDA joylashgan (`daraxt.body`);
#      2. uning yo'lida KECHIKTIRILGAN DOIRA YO'Q — ichki `def` / `async def`, `lambda`,
#         generator ifodasi: ular test tanasi bajarilganda faqat OBYEKT yaratadi, ichidagi
#         kod esa ALOHIDA chaqiruv (yoki iste'mol) bo'lmasa BAJARILMAYDI;
#      3. u ANIQ O'LIK shoxda EMAS — ya'ni: statik LITERAL yolg'on shartning TANASI
#         (`if False:`, `if 0:`, `while False:`), statik LITERAL rost shartning `else`
#         bo'lagi, va AYNI BLOKDA `return`/`raise`/`break`/`continue` dan KEYIN kelgan
#         gaplar.
#
# ⚠️ NEGA AYNAN SHU CHEGARA (va undan NARIGA EMAS). Yuqoridagi uchlik — o'zgaruvchi
#    qiymatiga, platformaga yoki ma'lumotga BOG'LIQ BO'LMAGAN, AST'da BIR QARASHDA
#    ko'rinadigan shakllar. Ularni kesish YOLG'ON QIZIL bera OLMAYDI, chunki hech bir
#    haqiqiy test darvozani `lambda` ichiga yoki `if False:` tagiga qo'ymaydi. To'liq
#    YETIB BORISH (reachability) tahlili esa umumiy holda HAL QILINMAYDIGAN masala:
#    unga urinish qo'riqchini o'zini og'ir va noishonchli qilardi va har yangi test
#    shaklida yolg'on qizil berardi. Shu bois mezon ATAYLAB «ANIQ O'LIK» bilan cheklangan.
#
# ⚠️ FAIL-CLOSED YO'NALISHI OCHIQ YOZILADI: bu o'lchov KAM sanashga moyil bo'lishi SHART.
#    Kam sanash qo'riqchini QIZIL qiladi (nom qamrov jadvalidan YO'QOLADI, yoki umumiy
#    sanoq jadvaldagidan FARQ qiladi), KO'P sanash esa uni YASHIL qilardi — ya'ni
#    bypass. Shu bois noaniq shakllarda o'lchov ATAYLAB «sanamaslik» tomonga yiqiladi.

#: ⚠️ KECHIKTIRILGAN DOIRALAR — ularning ichi test tanasi bajarilganda YURMAYDI.
#:    `Lambda` va `GeneratorExp` ham shu yerda: genexp FAQAT iste'mol qilinganda yuradi.
#: ⚠️ `ListComp`/`SetComp`/`DictComp` bu ro'yxatda ATAYLAB YO'Q — ular DARHOL bajariladi,
#:    demak ular ichidagi chaqiruv ROSTDAN yuradi va SANALISHI kerak (yolg'on qizil emas).
_KECHIKTIRILGAN_DOIRALAR = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                            ast.GeneratorExp)

#: ⚠️ AYNI BLOKDA o'zidan KEYINGI gaplarni O'LIK qiladigan SHARTSIZ boshqaruv uzatuvchilari.
#:    `break`/`continue` ham shu ro'yxatda: ta'rif bo'yicha ulardan keyingi gap shu blokda
#:    hech qachon bajarilmaydi (`return`/`raise` bilan AYNI qat'iylikda).
_UZIB_YUBORUVCHILAR = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _modul_daraxti() -> ast.Module:
    """SHU modulning AST'i — qo'riqchilar uchun YAGONA o'quvchi.

    ⚠️ Faylni qayta o'qiydi (keshlamaydi): qo'riqchi diskdagi HOLATNI o'lchasin, import
       paytida yuklangan nusxani emas.
    """
    return ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))


def _statik_haqiqat(shart: ast.expr) -> bool | None:
    """Shartning STATIK rost/yolg'onligi — FAQAT literal konstantada; aks holda `None`.

    ⚠️ ATAYLAB faqat `ast.Constant`: `if False:` / `if 0:` / `while False:` ANIQ o'lik.
       `if sys.platform == "win32":` (`Compare`) yoki `if bayroq:` (`Name`) esa STATIK
       EMAS — ularda `None` qaytadi va IKKI shox ham BAJARILADIGAN deb olinadi. Bu
       YOLG'ON QIZIL bermaslikning sharti: haqiqiy shartli yo'lni «o'lik» deb kesish
       qo'riqchini ishlab turgan testda yiqitardi.
    """
    if isinstance(shart, ast.Constant):
        return bool(shart.value)
    return None


def _ifoda_chaqiruvlari(tugun: ast.AST):
    """Bitta IFODA daraxtidagi `ast.Call` tugunlari — KECHIKTIRILGAN doiraga KIRMASDAN.

    ⚠️ Gaplar (`ast.stmt`) va GAP TANASINI saqlovchi bo'laklar (`except` bo'lagi,
       `match` holati) bu yerda ATAYLAB o'tkazib yuboriladi: ular GAP darajasidagi
       yuruvchida — o'lik shox kesimi BILAN — ko'riladi.
    """
    if isinstance(tugun, _KECHIKTIRILGAN_DOIRALAR):
        return
    if isinstance(tugun, ast.Call):
        yield tugun
    for bola in ast.iter_child_nodes(tugun):
        if isinstance(bola, ast.stmt) or isinstance(getattr(bola, "body", None), list):
            continue
        yield from _ifoda_chaqiruvlari(bola)


def _bolak_chaqiruvlari(bolak: ast.AST):
    """`except` bo'lagi yoki `match` holati: o'z IFODALARI (tur / soqchi / naqsh) + TANASI.

    ⚠️ TANA ro'yxati BUTUNLIGICHA `_gap_chaqiruvlari()` ga beriladi — gapma-gap berilsa
       o'lik-kod kesimi (`return`/`raise` dan keyingi gap) ISHLAMAY qolardi. Bu AYNAN
       o'lchangan nuqson: mezon matritsasida `for` tanasidagi `break`/`continue` dan
       keyingi chaqiruv birinchi urinishda SANALIB ketgan edi.
    """
    for maydon, qiymat in ast.iter_fields(bolak):
        if maydon == "body":
            continue
        for q in (qiymat if isinstance(qiymat, list) else [qiymat]):
            if isinstance(q, ast.AST):
                yield from _ifoda_chaqiruvlari(q)
    yield from _gap_chaqiruvlari(bolak.body)


def _gap_chaqiruvlari(gaplar: list):
    """BITTA BLOKDAGI gaplar bo'ylab BAJARILADIGAN yo'ldagi `ast.Call` tugunlari.

    ⚠️ Nima SANALADI (bajarilish yo'lida): `with` / `try` / `except` / `else` /
       `finally` / `for` / `match` / `while <ifoda>` tanalari, ichki SINF tanasi va
       oddiy `if <haqiqiy ifoda>` ning IKKI shoxi ham. Bu ro'yxat YOLG'ON QIZIL
       tekshiruvi bilan o'lchangan (45 shaklli sintetik mezon matritsasi bilan).
    ⚠️ Nima SANALMAYDI: ichki `def`/`async def` tanasi (obyekt yaratiladi, yurmaydi);
       statik literal yolg'on shartning tanasi va statik literal rost shartning `else`
       bo'lagi; shu blokda `return`/`raise`/`break`/`continue` dan keyingi gaplar.
    ⚠️⚠️ GAP RO'YXATI HAR DOIM BUTUNLIGICHA uzatiladi (`ast.iter_fields` bilan maydon
       bo'yicha), gapma-gap EMAS: aks holda o'lik-kod kesimi faqat ENG TASHQI ro'yxatda
       ishlab, `for`/`with`/`try` TANASIDAGI `return` dan keyingi chaqiruv SANALIB
       ketardi (birinchi urinishda aynan shunday bo'lgan — matritsa tutdi).
    """
    for gap in gaplar:
        if isinstance(gap, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # ⚠️ ICHKI FUNKSIYA (B2): tanasi test tanasi bilan BIRGA bajarilmaydi.
            #    Dekorator va standart qiymat ifodalari ham ATAYLAB o'tkazib yuboriladi —
            #    kam sanash fail-closed (umumiy sanoq bilan FARQ beradi va TISH QIZIL).
            continue
        if isinstance(gap, (ast.If, ast.While)):
            # ⚠️ SHART IFODASINING O'ZI har holda baholanadi, demak undagi chaqiruv sanaladi.
            yield from _ifoda_chaqiruvlari(gap.test)
            haqiqat = _statik_haqiqat(gap.test)
            if haqiqat is not False:               # `if False:` / `while False:` TANASI o'lik
                yield from _gap_chaqiruvlari(gap.body)
            if haqiqat is not True:                # `if True: ... else:` — `else` o'lik
                yield from _gap_chaqiruvlari(gap.orelse)
            continue
        for _maydon, qiymat in ast.iter_fields(gap):
            royxat = qiymat if isinstance(qiymat, list) else [qiymat]
            gaplar_bolagi = [q for q in royxat if isinstance(q, ast.stmt)]
            if gaplar_bolagi:
                # ⚠️ BUTUN ro'yxat BIRGA — o'lik-kod kesimi shu yerda ishlashi SHART.
                yield from _gap_chaqiruvlari(gaplar_bolagi)
            for q in royxat:
                if isinstance(q, ast.stmt) or not isinstance(q, ast.AST):
                    continue
                if isinstance(getattr(q, "body", None), list):
                    yield from _bolak_chaqiruvlari(q)
                else:
                    yield from _ifoda_chaqiruvlari(q)
        if isinstance(gap, _UZIB_YUBORUVCHILAR):
            # ⚠️ SHU BLOKDAGI qolgan gaplar O'LIK. Faqat SHU blok kesiladi: tashqi blok
            #    (masalan `if` dan keyingi kod) BAJARILADIGAN bo'lib qoladi — buni
            #    aniqlash allaqachon YETIB BORISH tahlili bo'lardi.
            return


def _exe_darvoza_chaqiruvlari() -> dict[str, list[object]]:
    """{funksiya nomi: [HAR chaqiruvning `toza_shart` qiymati]} — MODUL AST'idan.

    ⚠️ NEGA `PKG._chaqirilgan_nomlar()` BU YERDA YETMAYDI (va bu uning nusxasi EMAS): u
       BOSHQA savolga javob beradi — «SHU funksiya qaysi nomlarni chaqiradi». Bu yerdagi
       savol TESKARI va MODUL darajasida: «darvozani QAYSI funksiyalar chaqiradi va QANDAY
       ARGUMENT bilan». Argument ajralmas qism, chunki `toza_shart=False` darvozani
       ATAYLAB yumshatadi — qamrovni argumentsiz o'lchash «chaqirdi» deb hisoblab,
       yumshatilgan chaqiruvni TOZA talab deb qabul qilardi.
    ⚠️ MATN qidiruvi ISHLATILMAYDI: `nom in inspect.getsource(...)` docstringdagi eslatmani
       ham «chaqiruv» deb hisoblaydi va qo'riqchi O'LIK bo'lib qolardi (bu o'lchangan —
       qolgan to'rt modulning §0 izohida yozilgan).
    ⚠️ Nom QATTIQ YOZILMAYDI: `_exe_darvozasi.__name__` dan olinadi, ya'ni darvoza qayta
       nomlansa qo'riqchi ergashadi (eski nomni izlab JIMGINA bo'sh qolmaydi).
    ⚠️⚠️ `ast.walk` ISHLATILMAYDI (F-1 nuqsoni): u tugunning JOYIGA qaramaydi, shu bois
       ichki funksiyadagi va `if False:` tagidagi — ya'ni HECH QACHON BAJARILMAYDIGAN —
       chaqiruvni «chaqirilgan» deb sanardi. O'rniga `_gap_chaqiruvlari()` BAJARILISH
       YO'LI bo'ylab yuradi; mezon va uning chegaralari yuqoridagi bo'limda ANIQ yozilgan.

    ⚠️⚠️ GARDNING CHEGARALARI (halol ro'yxat — bu bo'lim O'CHIRILMAYDI, YANGILANADI):
      · O'lchov YUQORI DARAJADAGI funksiyalarning TANASINI ko'radi. MODUL darajasidagi
        chaqiruv bu jadvalga TUSHMAYDI — uni `_exe_darvoza_chaqiruv_soni()` bilan
        solishtirish (pastdagi «TISH» assert'i) tutadi.
      · O'lik shox mezoni FAQAT LITERAL konstantani statik deb oladi: `if 1 == 2:` yoki
        `if BAYROQ:` (modul konstantasi `False` bo'lsa ham) BAJARILADIGAN deb SANALADI.
        Bu ATAYLAB: ifodani baholash qo'riqchini noaniq qilardi.
      · HAMMA shoxi `return`/`raise` bilan tugaydigan `if/else` dan KEYINGI gaplar
        BAJARILADIGAN deb olinadi — bu allaqachon YETIB BORISH tahlili.
      · CHAQIRILMAYDIGAN YUQORI DARAJADAGI yordamchidagi chaqiruv SANALADI. Bu bo'shliq
        OCHIQ qoldirilgan, chunki u qamrov jadvalida YANGI NOM bo'lib ko'rinadi va
        tenglik assert'i QIZIL beradi (mutatsiya B3 aynan shunday tutiladi).
      · Dekorator ifodasidagi, funksiya IMZOSIDAGI standart qiymat ifodasidagi va
        yuqori darajadagi `async def` ichidagi chaqiruv SANALMAYDI (import paytida yoki
        korutina kutilganda yuradi). Ular umumiy sanoq bilan FARQ beradi, demak «TISH»
        assert'i QIZIL bo'ladi va ro'yxatni YANGILASHNI talab qiladi.
      · Generator ifodasi ROSTDAN iste'mol qilinsa ham SANALMAYDI — fail-closed tanlov
        (kam sanash QIZIL, ko'p sanash bypass bo'lardi).
      · Bu o'lchov DINAMIK chaqiruvni (`getattr(mod, "_exe_darvozasi")()`, `eval`) ko'ra
        OLMAYDI — AST'da `ast.Name` yo'q. Darvozani shunday chaqirish bu modulda
        TAQIQLANADI va qamrov jadvali uni «yo'q» deb QIZIL beradi.
    """
    nom = _exe_darvozasi.__name__
    topilgan: dict[str, list[object]] = {}
    for tugun in _modul_daraxti().body:
        if not isinstance(tugun, ast.FunctionDef):
            continue
        for n in _gap_chaqiruvlari(tugun.body):
            if not isinstance(n.func, ast.Name) or n.func.id != nom:
                continue
            qiymat: object = _STANDART
            for kw in n.keywords:
                assert kw.arg == "toza_shart", (
                    f"`{tugun.name}` darvozani KUTILMAGAN argument bilan chaqirdi: "
                    f"{kw.arg!r} — qo'riqchi uning ma'nosini BILMAYDI")
                assert isinstance(kw.value, ast.Constant), (
                    f"`{tugun.name}` da `toza_shart` O'ZGARUVCHI/ifoda bilan berilgan — "
                    f"qamrov AST'dan O'QILMAYDI, demak darvoza yumshatilganini qo'riqchi "
                    f"KO'RMAY qolardi. Qiymat LITERAL bo'lishi SHART.")
                qiymat = kw.value.value
            topilgan.setdefault(tugun.name, []).append(qiymat)
    return topilgan


def _exe_darvoza_chaqiruv_soni() -> int:
    """MODULDAGI darvoza chaqiruvlarining UMUMIY soni — joyidan QAT'I NAZAR.

    ⚠️ `_exe_darvoza_chaqiruvlari()` faqat yuqori darajadagi funksiyalarning BAJARILADIGAN
       yo'lini ko'radi. Bu o'lchov esa butun daraxtni `ast.walk` bilan ko'radi — AYNAN shu
       yerda `ast.walk` TO'G'RI asbob, chunki savol «qaysi joyda» emas, «UMUMAN bormi».
       Ikki son FARQ qilsa — chaqiruv bajarilish yo'lidan TASHQARIDA: modul darajasida,
       ichki funksiya/`lambda`/genexp ichida yoki ANIQ o'lik shoxda. Uchalasi ham qamrovni
       chalg'itadi, shu bois farq QIZIL beradi (mutatsiya B2 va B4 aynan shunday tutiladi).
    """
    nom = _exe_darvozasi.__name__
    return len([n for n in ast.walk(_modul_daraxti())
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == nom])


def _exe_darvoza_BAJARILMAYDIGAN_chaqiruvlari() -> list[int]:
    """BAJARILISH yo'lidan TASHQARIDAGI darvoza chaqiruvlarining SATR raqamlari.

    ⚠️ Faqat DIAGNOSTIKA uchun: «TISH» assert'i yiqilganda operator qaysi SATRNI
       ko'rishini aytadi. Hukmni (`passed`/`failed`) bu funksiya O'ZGARTIRMAYDI — qaror
       UMUMIY sanoq ↔ jadval tengligida chiqadi, ya'ni diagnostika yiqilib qolsa ham
       darvoza fail-closed bo'lib qoladi.
    """
    nom = _exe_darvozasi.__name__
    daraxt = _modul_daraxti()
    hammasi = [n.lineno for n in ast.walk(daraxt)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == nom]
    for tugun in daraxt.body:
        if not isinstance(tugun, ast.FunctionDef):
            continue
        for n in _gap_chaqiruvlari(tugun.body):
            if isinstance(n.func, ast.Name) and n.func.id == nom:
                hammasi.remove(n.lineno)
    return sorted(hammasi)


def test_B_darvoza_SIMI_AST_bilan_TALAB_qilinadi():
    """⚠️⚠️ `_exe_darvozasi()` harness HUKMINI ROSTDAN chaqirsin — qog'ozdagi darvoza EMAS.

    Mutatsiya M1 (`PH.yigma_tayyorligi()` chaqiruvini tanadan olib tashlash) AYNAN shu
    yerda tutiladi: nom AST'dan yo'qoladi. Docstringda nomning qolishi YORDAM BERMAYDI —
    `PKG._chaqirilgan_nomlar()` faqat HAQIQIY `ast.Call` tugunlarini ko'radi.

    ⚠️ Uch tugash yo'li ham TALAB qilinadi: `exe_qurish_mumkinmi` (platforma qarori),
       `fail` va `skip`. Biri yo'qolsa darvoza uch holatdan birini jimgina «davom et» ga
       aylantirgan bo'lardi — aynan fail-open.
    ⚠️ IMZO ham qulflanadi (mutatsiya M3): standart QAT'IY bo'lib qolsin. Standart `False`
       ga o'zgarsa, kwarg BERMAYDIGAN TO'RT chaqiruv joyi JIMGINA yumshoq bo'lib qolardi
       va ESKIRGAN yig'ma parity'dan o'tib ketardi. Qaror jadvalining O'ZI pastdagi
       `test_B_darvoza_QAROR_JADVALI_...` da alohida o'lchanadi.
    """
    chaqirilgan = PKG._chaqirilgan_nomlar(_exe_darvozasi)
    for chaqiruv in ("yigma_tayyorligi", "exe_qurish_mumkinmi", "fail", "skip"):
        assert chaqiruv in chaqirilgan, (
            f"`_exe_darvozasi()` `{chaqiruv}` ni CHAQIRMAYDI — darvoza SIMLANMAGAN "
            f"(topilgan chaqiruvlar: {sorted(chaqirilgan)})")

    p = inspect.signature(_exe_darvozasi).parameters["toza_shart"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        "`toza_shart` POZITSION bo'lib qoldi — chaqiruv joylarining ma'nosini qamrov "
        "qo'riqchisi `keywords` dan O'QIY OLMAYDI")
    assert p.default is True, (
        "`toza_shart` STANDARTI QAT'IY emas — kwarg bermaydigan chaqiruv joylari "
        "eskirgan yig'mani JIMGINA qabul qilib, parity'ni o'lchanmagan holda "
        "«yashil» qilardi")


def test_B_darvoza_QAMROVI_HAR_chaqiruv_joyida_SAQLANADI():
    """⚠️⚠️ QAMROV QULFI: darvozaga tayanishi SHART bo'lgan HAR funksiya uni ROSTDAN
         chaqirsin, va YUMSHATISH faqat ATAYLAB qilingan BITTA joyda bo'lsin.

    Mutatsiya M2 (bitta testdan `_exe_darvozasi(...)` chaqiruvini olib tashlash) shu
    yerda tutiladi — ilgari uni HECH NARSA tutmasdi: inventar qo'riqchisi matndagi izga
    qaraydi, iz esa darvoza TA'RIFIDA qoladi.

    ⚠️ `toza_shart=False` ning MA'NOSI ham qulflanadi:
       `test_B_darvoza_HAQIQIY_yigmani_MODULMA_MODUL_oqiydi` ATAYLAB yumshoq ishlaydi
       (u darvozaning O'ZI haqiqiy arxivni o'qiy olishini o'lchaydi, «yig'ma toza» degan
       da'voni EMAS) — bu YOLG'ON QIZIL qilinmaydi, lekin ATAYLAB ekani OCHIQ yozilgan va
       u YAGONA yumshoq joy bo'lib QOLADI.

    ⚠️⚠️ MUTATSIYA B2 va B4 (O'LIK-KOD AYLANIB O'TISH) ham SHU YERDA — pastdagi
       «TISH» assert'ida — tutiladi: chaqirilmaydigan ICHKI funksiyadagi
       (`def _olik(): _exe_darvozasi()`) yoki ANIQ o'lik shoxdagi
       (`if False: _exe_darvozasi()`) chaqiruv qamrovga SANALMAYDI, umumiy sanoqqa
       esa KIRADI. Mezonning ANIQ ta'rifi va uning CHEGARALARI
       `_exe_darvoza_chaqiruvlari()` ustidagi bo'limda yozilgan.
    """
    topilgan = _exe_darvoza_chaqiruvlari()
    kutilgan = set(EXE_DARVOZAGA_TAYANADIGANLAR) | set(EXE_DARVOZANI_OZINI_SINOVCHILAR)
    assert set(topilgan) == kutilgan, (
        f"DARVOZA QAMROVI O'ZGARDI. Yo'qolgan: {sorted(kutilgan - set(topilgan))} — "
        f"ular yig'ma bilan ishlaydi, lekin darvozani CHAQIRMAYDI, ya'ni eskirgan yoki "
        f"yo'q `.exe` jimgina «parity o'lchandi» bo'lib ketardi. Yangi: "
        f"{sorted(set(topilgan) - kutilgan)} — yangi, darvozaga tayanadigan funksiya "
        f"`EXE_DARVOZAGA_TAYANADIGANLAR` ga YOZILISHI va (test bo'lsa) Linux skip'i "
        f"`tests/ci_expected_skips.txt` da RATIFIKATSIYA qilinishi shart.")

    for nom, qat_iy in sorted(EXE_DARVOZAGA_TAYANADIGANLAR.items()):
        qiymatlar = topilgan[nom]
        assert len(qiymatlar) == 1, (
            f"`{nom}` darvozani {len(qiymatlar)} marta chaqiradi ({qiymatlar!r}) — "
            f"takroriy chaqiruv qamrov ma'nosini chalg'itadi")
        qiymat = qiymatlar[0]
        if qat_iy:
            assert qiymat is _STANDART or qiymat is True, (
                f"`{nom}` darvozani YUMSHATDI (`toza_shart={qiymat!r}`) — bu funksiya "
                f"TOZA yig'ma TALAB qilishi SHART, aks holda ESKIRGAN yig'ma parity'dan "
                f"o'tib ketardi")
        else:
            assert qiymat is False, (
                f"`{nom}` ATAYLAB `toza_shart=False` bilan ishlashi kerak — u darvozaning "
                f"O'ZINI eskirgan yig'mada ham o'lchaydi; topilgani: {qiymat!r}")

    yumshoq = sorted(n for n, q in EXE_DARVOZAGA_TAYANADIGANLAR.items() if not q)
    assert yumshoq == ["test_B_darvoza_HAQIQIY_yigmani_MODULMA_MODUL_oqiydi"], (
        f"ATAYLAB yumshoq joylar ro'yxati O'SDI: {yumshoq} — har yangi yumshatish "
        f"parity kafolatidan bir bo'lak OLADI va ALOHIDA ko'rik talab qiladi")

    # ⚠️⚠️ TISH: HAR chaqiruv BAJARILADIGAN yo'lda bo'lsin. Bu assert F-1 (O'LIK-KOD
    #      AYLANIB O'TISH) ning YOPILISH NUQTASI: `_exe_darvoza_chaqiruvlari()` endi ichki
    #      funksiya, `lambda`, generator ifodasi va ANIQ o'lik shoxdagi chaqiruvni
    #      SANAMAYDI, umumiy sanoq esa ularni KO'RADI — demak ikki son FARQ qiladi.
    jadvaldagi = sum(len(v) for v in topilgan.values())
    umumiy = _exe_darvoza_chaqiruv_soni()
    assert umumiy == jadvaldagi, (
        f"moduldagi darvoza chaqiruvlari soni ({umumiy}) qamrov jadvalidagidan "
        f"({jadvaldagi}) FARQ qiladi — {umumiy - jadvaldagi} chaqiruv BAJARILISH "
        f"YO'LIDAN TASHQARIDA. Satr(lar): "
        f"{_exe_darvoza_BAJARILMAYDIGAN_chaqiruvlari()}. Mumkin bo'lgan sabablar: "
        f"(a) MODUL darajasidagi chaqiruv; (b) ICHKI `def`/`async def`/`lambda`/generator "
        f"ifodasi ichidagi chaqiruv — u test tanasi bajarilganda YURMAYDI; (c) ANIQ "
        f"O'LIK shox — `if False:`/`if 0:`/`while False:` tanasi, `if True: ... else:` "
        f"bo'lagi, yoki `return`/`raise`/`break`/`continue` dan KEYINGI gap. Bunday "
        f"chaqiruv «darvoza chaqirildi» DEGANI EMAS: u ESKIRGAN yoki yo'q yig'mani "
        f"parity'dan JIMGINA o'tkazib yuborardi.")


def test_B_darvoza_QAROR_JADVALI_holatma_holat_qulflangan(monkeypatch):
    """⚠️⚠️ DARVOZANING MA'NOSI: to'rt harness holati × `toza_shart` ning ikki qiymati.

    AST sim borligini isbotlaydi; bu test simning NIMA qilishini isbotlaydi. Ikkisi
    BIRGALIKDA mutatsiya M3 ni tutadi: imzodagi standart `False` ga o'zgarsa, `ESKIRGAN`
    holatda `_exe_darvozasi()` YIQILISH O'RNIGA qiymat qaytaradi.

    ⚠️ HAQIQIY `.exe` KERAK EMAS: harness hukmi `monkeypatch` bilan almashtiriladi, ya'ni
       bu test Linux CI'da ham BAJARILADI va `ci_expected_skips.txt` ga YOZILMAYDI
       (parity skip soni O'ZGARMAYDI).
    ⚠️ `HOLAT_YOQ` da platforma qarori ham `monkeypatch` qilinadi — aks holda test
       `sys.platform` ga bog'lanib, Linux'da yarmi o'lchanmagan bo'lib qolardi.
    ⚠️ SABAB MATNI ham o'lchanadi: harness sababi YO'QOLSA, `ci_expected_skips.txt`
       dagi sabab bo'lagi mos kelmay, Linux'da skip KUTILMAGAN bo'lib qolardi.
    """
    def hukm(holat: str) -> None:
        monkeypatch.setattr(PH, "yigma_tayyorligi", lambda: (holat, f"<SABAB:{holat}>"))

    # 1) TOZA — YAGONA davom etiladigan holat, ikki qiymatda ham.
    hukm(PH.HOLAT_TOZA)
    assert _exe_darvozasi() == PH.HOLAT_TOZA, "TOZA holatda darvoza davom etmadi"
    assert _exe_darvozasi(toza_shart=False) == PH.HOLAT_TOZA

    # 2) ESKIRGAN — QAT'IY rejimda YIQILADI (jim skip EMAS), yumshoq rejimda O'QILADI.
    hukm(PH.HOLAT_ESKIRGAN)
    with pytest.raises(pytest.fail.Exception) as xato:
        _exe_darvozasi()
    assert f"<SABAB:{PH.HOLAT_ESKIRGAN}>" in str(xato.value), (
        f"yiqilish matnida harness sababi YO'Q: {xato.value}")
    assert _exe_darvozasi(toza_shart=False) == PH.HOLAT_ESKIRGAN, (
        "yumshoq rejim ESKIRGAN yig'mani O'QIMADI — darvozaning O'ZINI o'lchaydigan "
        "test aynan kerak bo'lgan paytda bajarilmay qolardi")

    # 3) ISBOTSIZ — HAR IKKI rejimda YIQILADI. ⚠️ Yumshoq rejim ham ISBOTSIZ ni QABUL
    #    QILMAYDI: «isbotlab bo'lmadi» ni «eskirgan» bilan tenglashtirish fail-open edi.
    hukm(PH.HOLAT_ISBOTSIZ)
    with pytest.raises(pytest.fail.Exception):
        _exe_darvozasi()
    with pytest.raises(pytest.fail.Exception):
        _exe_darvozasi(toza_shart=False)

    # 4) YO_Q — platformaga QARAB ikki xil tugash (IKKI EGA naqshi).
    hukm(PH.HOLAT_YOQ)
    monkeypatch.setattr(PH, "exe_qurish_mumkinmi", lambda: True)
    with pytest.raises(pytest.fail.Exception):
        _exe_darvozasi()
    monkeypatch.setattr(PH, "exe_qurish_mumkinmi", lambda: False)
    with pytest.raises(pytest.skip.Exception) as skip:
        _exe_darvozasi()
    assert f"<SABAB:{PH.HOLAT_YOQ}>" in str(skip.value), (
        f"muhit skip'i harness sababini TASHLAB yubordi: {skip.value}")
