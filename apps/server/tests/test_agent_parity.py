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

import importlib.util
import inspect
import io
import json
import os
import pathlib
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
from tests.test_agent_packaging import _Cp1252Oqim

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


@pytest.fixture(scope="module", params=SSENARIYLAR, ids=_SSENARIY_ID)
def juftlik(request, tmp_path_factory):
    """AYNI fikstura bilan MANBA va YIG'MA yurishlari + ssenariyning kutilgan natijasi.

    ⚠️ `scope="module"`: har ssenariy IKKI jarayon ochadi va tayyorlik o'lchovi uchun
       haqiqiy `poll` uyqusini kutadi. Har test uchun qaytadan yurgizish to'plamni bir necha
       baravar sekinlashtirardi va HECH NARSA qo'shmasdi — natijalar o'zgarmas.
    ⚠️ EXE YO'Q BO'LSA JIMGINA O'TKAZIB YUBORILMAYDI: `test_yigma_joyida_...` ALOHIDA va
       KO'RINADIGAN yiqilish beradi, ya'ni «hamma test o'tdi» degan noto'g'ri taassurot
       bo'lmaydi. Bu yerdagi sabab matni esa QAYERGA qaralgani va NIMA qilish kerakligini
       aytadi.
    """
    nom, generator, kutish, kutilgan_holat, kutilgan_kod, paket_bor = request.param
    if not PH.yigma_bor():
        pytest.skip(PH.yigma_yoqligi_sababi())
    ildiz = tmp_path_factory.mktemp(f"parity-{nom}")
    manba, yigma = PH.ikki_yurish(str(ildiz), generator, kutish=kutish)
    return nom, manba, yigma, kutilgan_holat, kutilgan_kod, paket_bor


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


def test_brief_sanagan_hamma_maydon_solishtirildi(juftlik):
    """⚠️ Brief §5 sanagan HAMMA maydon semantik ko'rinishda BOR.

    Aks holda parity testi jimgina qisqarib qolardi: maydon `semantik()` dan yo'qolsa
    solishtirish ham yo'qoladi va test baribir yashil bo'lardi.
    """
    _nom, manba, _yigma, *_ = juftlik
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


def test_kuzatilgan_papkalar_bayt_ba_bayt_ayni(juftlik):
    """Ikki yurishga berilgan fikstura AYNAN bir xil edi — farq KIRISHDAN kelmaydi.

    ⚠️ Usiz parity testining ma'nosi yo'q: generator deterministik bo'lmasa «yig'ma boshqa
       qaror chiqardi» degan xulosa aslida «kirish boshqa edi» bo'lib qolardi.
    """
    _nom, manba, yigma, *_ = juftlik
    a = PH.papka_baytlari(manba.kuzatilgan)
    b = PH.papka_baytlari(yigma.kuzatilgan)
    farqli = sorted(set(a) ^ set(b)) or sorted(n for n in a if a[n] != b.get(n))
    assert a == b, f"kuzatilgan papkalar BIR XIL emas (generator deterministik emas): {farqli}"


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
def test_solishtiruvchi_haqiqiy_farqni_rostdan_topadi(juftlik):
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
    """
    import dataclasses

    _nom, manba, _yigma, *_ = juftlik
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


def test_tabiiy_vaqt_farqi_allowlist_bilan_otadi_bosh_allowlistda_otmaydi(juftlik,
                                                                         monkeypatch):
    """⚠️⚠️ ALLOWLIST ROSTDAN ISHLAYAPTI — IKKI TOMONGA ham o'lchanadi.

    (a) Allowlist BILAN: `scanned_at` ning (va uning manifestdagi oqibatining) farqi
        TAQIQLANGAN farq BO'LMAYDI, lekin RUXSAT ETILGAN farq bo'lib QAYD ETILADI — jimgina
        yo'qolmaydi.
    (b) Allowlist BO'SHATILSA: AYNAN shu ikki yo'l taqiqlangan farq bo'lib CHIQADI — ya'ni
        ruxsat bezak emas, u rostdan bir narsani o'tkazayotgan edi.

    ⚠️ Farq QO'LDA quriladi (`_vaqti_siljigan_nusxa`), haqiqiy ikki yurishdan olinmaydi:
       ular AYNI sekundda boshlanib qolsa test tasodifan HECH NARSA o'lchamasdi.
    """
    _nom, manba, _yigma, *_ = juftlik
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
    assert PH.yigma_bor(), PH.yigma_yoqligi_sababi()
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
    assert PH.yigma_bor(), PH.yigma_yoqligi_sababi()
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


def test_yigma_joyida_va_parity_otkazib_yuborilmadi():
    """⚠️⚠️ YIG'MA JOYIDA BO'LISHI KUTILADI — demak parity ROSTDAN o'lchangan.

    Bu test yo'q bo'lsa butun modul jimgina `skip` bo'lib, to'plam «yashil» ko'rinardi va
    hech kim parity tekshirilmaganini bilmasdi. Shu bois yo'qlik ALOHIDA va KO'RINADIGAN
    yiqilish bo'ladi (boshqa joyda bo'lsa `BINOS_AGENT_EXE` bilan ko'rsatiladi).
    """
    assert PH.yigma_bor(), PH.yigma_yoqligi_sababi()
    assert os.path.isdir(os.path.join(os.path.dirname(PH.YIGMA_EXE), "_internal")), \
        "ONE-DIR yig'ma kutilgan: `.exe` yonida `_internal/` bo'lishi kerak"
