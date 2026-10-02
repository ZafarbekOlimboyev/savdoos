# -*- coding: utf-8 -*-
"""UCH TOMONLI ANTI-DRIFT DARVOZASI — ko'prik shartnomasi UCH manbadan tortib solishtiriladi.

⚠️⚠️ NEGA BU FAYL BOR. Bu bosqichda IKKI P0 topildi va IKKISI HAM bitta sinfdan:
     «ikki tomon BIR XIL shartnomani HAR XIL tushundi».
       · yig'uvchi o'zligi: agent ICHKI yig'uvchining nomini kutardi
         (`BinOSDiscovery`/`0.2.0-UNVERIFIED`), ko'prik esa O'Z nomini yozadi
         (`BinOSDiscoveryCollector`/`0.1.0-source`) — HAR BIR haqiqiy javob
         `WRONG_COLLECTOR_VERSION` bilan rad etilardi;
       · `status` lug'ati: agent `"OK"` kutardi, yig'uvchi esa `"SUCCESS"` yozadi — HAR BIR
         muvaffaqiyatli yurish `BRIDGE_SHAPE_INVALID` bilan rad etilardi.
     Phase 4 da AYNAN shu sinf bir marta bo'lgan, bu ikkitasi esa IKKINCHI marta. Ikkisi
     ham to'plam YASHIL bo'lganda yashiringan, chunki har tomonning testi O'Z tomonini
     o'lchardi.

⚠️⚠️ SHU BOIS BU DARVOZANING O'LCHOV USULI BOSHQA: u BIR tomonni emas, UCH manbani
     bir-biriga qarshi qo'yadi va faqat AYNAN moslikni qabul qiladi:
       (1) PYTHON   — `bridge_protocol` / `one_click` doimiylari (agent kutadigan qiymat);
       (2) VERSION  — `integrations/1c/collector/VERSION.json` (reliz e'loni);
       (3) MANBA    — `integrations/1c/collector/BinOSDiscoveryCollector.bsl` MATNI
                      (1C ichida ROSTDAN yoziladigan qiymat).
     `status` lug'atining yadro qismi uchun uchinchi manba — `runtime_bundle.OVERALL_*`
     (Phase 4 ning `overall` lug'ati), chunki `VERSION.json` holat haqida hech nima
     aytmaydi.

⚠️ NIMANI ISBOTLAYDI: uch manbadagi NOM, VERSIYA, `status` QIYMATLARI, hujjat KALITLARI va
   sxema versiya satrlari BIR XIL ekanini — ya'ni bir tomon o'zgarsa CI QIZIL bo'ladi.
⚠️ NIMANI ISBOTLAMAYDI: `.bsl` kompilyatsiya bo'lishini yoki 1C da yurishini. Bu mashinada
   1C YO'Q va `.epf` IKKILIK fayli QURILMAGAN — holat AYNAN `EPF_SOURCE_READY`.
   Bu test faqat STATIK MATNNI o'qiydi: 1C ga ULANMAYDI, tarmoqqa chiqmaydi, jarayon
   ishga tushirmaydi.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

from app.services.discovery_1c import runtime_audit
from app.services.discovery_1c.runtime_bundle import (OVERALL_FAILED, OVERALL_PARTIAL,
                                                      OVERALL_SUCCESS)
from app.services.discovery_agent import bridge_protocol as proto
from app.services.discovery_agent import one_click as oc

_1C = pathlib.Path(__file__).resolve().parents[3] / "integrations" / "1c"

COLLECTOR_DIR = _1C / "collector"
#: (3) MANBA — 1C ichida ROSTDAN ishlaydigan ko'prik fragmenti.
BRIDGE_SRC = COLLECTOR_DIR / "BinOSDiscoveryCollector.bsl"
#: (2) VERSION — reliz e'loni.
BRIDGE_VERSION = COLLECTOR_DIR / "VERSION.json"
#: Operator oqimi hujjati — sxema versiya satrlari uchun UCHINCHI manba.
FLOW_DOC = _1C / "AGENT_ONE_CLICK_FLOW.md"

#: ⚠️ TO'RTINCHI NUSXA. `test_agent_collector_source.py` kalit ro'yxatlarini O'ZIDA QAYTA
#: e'lon qiladi (`REQUEST_KEYS`, `RESPONSE_KEYS`, `DONE_KEYS`). Nusxa borligining O'ZI
#: drift kanali, shu bois u ham shu darvozadan o'tadi — pastdagi
#: `test_TORTINCHI_NUSXA...` testiga qarang.
SOURCE_TEST = pathlib.Path(__file__).with_name("test_agent_collector_source.py")


# ══════════════════════════════════════════════════════════════════════════════════════════
# `.bsl` DAN STATIK AJRATISH — FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ HAR AJRATUVCHI BO'SH NATIJAGA QARSHI HIMOYALANGAN. Agar regexp hech narsa topmasa,
#      «ikki to'plam ham bo'sh» degan YOLG'ON MOSLIK chiqardi va darvoza JIMGINA o'chardi —
#      bu nuqsonni topish kerak bo'lgan darvoza uchun eng yomon yiqilish turi.
# ⚠️⚠️ NOMA'LUM SHAKL — ISTISNO, TASHLAB YUBORISH EMAS. Ajratuvchi tushunmagan yozuvni jim
#      o'tkazsa, `status` qiymati shu yo'l bilan kirib kelishi mumkin edi.


def _matn(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _bsl_kod() -> str:
    """Ko'prik manbasining KODI — IZOHLAR OLIB TASHLANGAN, literallar SAQLANGAN.

    ⚠️ Izoh hisobga OLINMAYDI: izohda eslangan qiymat 1C da hech narsa yozmaydi. Aynan shu
       ajrim bu darvozani `grep` dan farqlaydi — izohdagi eski qiymat uni chalg'itmasin.
    ⚠️ Literal esa SAQLANADI: biz AYNAN literal MAZMUNINI (`"SUCCESS"`) o'lchayapmiz.
    """
    satrlar = runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False)
    assert satrlar, "fikstura: ko'prik manbasidan kod satri ajratilmadi"
    return "\n".join(satrlar)


def _vstavit_kalitlari(kod: str, struktura: str) -> set[str]:
    """`<struktura>.Вставить("kalit", ...)` dan KALIT nomlari."""
    topilgan = set(re.findall(rf'{struktura}\.Вставить\(\s*"([^"]+)"', kod))
    assert topilgan, f"fikstura: `{struktura}.Вставить` chaqiruvi topilmadi"
    return topilgan


def _sorov_oqilgan_kalitlar(kod: str) -> set[str]:
    """`МостПоле(<so'rov>, "kalit", ...)` — ko'prik ROSTDAN O'QIYDIGAN so'rov maydonlari."""
    topilgan = set(re.findall(r'МостПоле\(\s*(?:Мост)?Запрос\s*,\s*"([^"]+)"', kod))
    assert topilgan, "fikstura: so'rov maydonini o'qiydigan chaqiruv topilmadi"
    return topilgan


def _funksiya_tanasi(kod: str, nom: str) -> str:
    """`Функция <nom>(...) ... КонецФункции` orasidagi matn."""
    moslik = re.search(rf"Функция\s+{nom}\s*\(.*?КонецФункции", kod, re.S)
    assert moslik, f"fikstura: `{nom}` funksiyasi manbada topilmadi"
    return moslik.group(0)


def _argumentlar(xom: str) -> list[str]:
    """Ichki qavssiz chaqiruv argumentlarini vergul bo'yicha ajratadi."""
    return [a.strip() for a in xom.split(",")]


def _funksiya_qaytargan_holatlar(kod: str, nom: str) -> set[str]:
    """`<nom>` funksiyasi QAYTARA OLADIGAN holat literallari.

    Ikki manba hisobga olinadi va IKKISI HAM kerak:
      · `Возврат "X"` — funksiyaning O'Z literali (fail-closed yo'llar: `"FAILED"`);
      · `Возврат <o'zgaruvchi>` bo'lsa — shu o'zgaruvchi uchun manbada yozilgan OQ RO'YXAT
        (`Состояние <> "X"` solishtirishlari), chunki funksiya diskdan o'qilgan qiymatni
        AYNAN shu ro'yxat bo'yicha filtrlab o'tkazadi.
    ⚠️ Oq ro'yxatni «o'qimasdan» faqat `Возврат "..."` ni olish `SUCCESS`/`PARTIAL` ni
       YO'QOTARDI va darvoza yolg'on mos kelardi.
    """
    tana = _funksiya_tanasi(kod, nom)
    natija = set(re.findall(r'Возврат\s+"([^"]+)"', tana))
    for ozgaruvchi in re.findall(r"Возврат\s+([A-Za-zА-Яа-яЁё_][\w]*)\s*;", tana):
        oq = set(re.findall(rf'{ozgaruvchi}\s*<>\s*"([^"]+)"', tana))
        assert oq, (
            f"`{nom}` ichida `Возврат {ozgaruvchi}` bor, lekin uning OQ RO'YXATI "
            f"(`{ozgaruvchi} <> \"...\"`) topilmadi — ajratuvchi qiymat to'plamini "
            f"ISBOTLAY OLMAYDI va shu bois JIM O'TMAYDI")
        natija |= oq
    assert natija, f"fikstura: `{nom}` qaytaradigan holat literali topilmadi"
    return natija


def _ozgaruvchi_holatlari(kod: str, nom: str) -> set[str]:
    """`<nom> = ...` tayinlashlaridan kelib chiqadigan holat to'plami."""
    tayinlashlar = re.findall(rf"{nom}\s*=\s*([^;]+);", kod, re.S)
    assert tayinlashlar, f"fikstura: `{nom}` o'zgaruvchisiga tayinlash topilmadi"
    natija: set[str] = set()
    for xom in tayinlashlar:
        xom = xom.strip()
        literal = re.fullmatch(r'"([^"]*)"', xom)
        if literal:
            natija.add(literal.group(1))
            continue
        chaqiruv = re.match(r"([A-Za-zА-Яа-яЁё_][\w]*)\s*\(", xom)
        assert chaqiruv, (
            f"`{nom}` ga TUSHUNARSIZ qiymat tayinlanyapti: {xom!r}. Ajratuvchi uni "
            f"ISBOTLAY OLMAYDI — qiymat shu yo'ldan JIMGINA kirib kelmasligi uchun test "
            f"YIQILADI, tashlab YUBORMAYDI")
        natija |= _funksiya_qaytargan_holatlar(kod, chaqiruv.group(1))
    return natija


def _bsl_javob_holatlari() -> set[str]:
    """`response.json` ning `status` iga ROSTDAN YOZILADIGAN qiymatlar to'plami.

    `МостЗаписатьОтвет(Каталог, Ключ, <holat>, ...)` ning UCHINCHI argumenti o'lchanadi:
    literal bo'lsa — o'zi, o'zgaruvchi bo'lsa — uning to'plami yoyib chiqiladi.
    """
    kod = _bsl_kod()
    chaqiruvlar = re.findall(r"МостЗаписатьОтвет\(([^()]*)\)", kod, re.S)
    #: ⚠️ `Функция МостЗаписатьОтвет(...)` e'loni ham shu naqshga tushadi — e'lonning
    #:    uchinchi argumenti PARAMETR nomi (`Состояние`), chaqiruvning uchinchisi esa
    #:    QIYMAT. E'lon tashlab yuboriladi, chaqiruvlar esa QOLADI va kamida ikkita
    #:    bo'lishi SHART (rad etish yo'li + normal yo'l).
    qiymatlar: set[str] = set()
    chaqiruv_soni = 0
    for xom in chaqiruvlar:
        argumentlar = _argumentlar(xom)
        assert len(argumentlar) >= 3, f"`МостЗаписатьОтвет` argumentlari kam: {xom!r}"
        uchinchi = argumentlar[2]
        if uchinchi == "Состояние":
            continue  # funksiya E'LONI, chaqiruv emas
        chaqiruv_soni += 1
        literal = re.fullmatch(r'"([^"]*)"', uchinchi)
        if literal:
            qiymatlar.add(literal.group(1))
        else:
            qiymatlar |= _ozgaruvchi_holatlari(kod, uchinchi)
    assert chaqiruv_soni >= 2, (
        "javob yozish chaqiruvi IKKITADAN kam topildi — ajratuvchi manbaning shaklini "
        "endi tushunmayapti va shu holda to'plamni ISBOTLAY OLMAYDI")
    assert qiymatlar, "fikstura: javobga yozilgan holat qiymati topilmadi"
    return qiymatlar


def _bsl_yiguvchi_ozligi() -> tuple[str, str]:
    """`МостОписаниеСборщика()` ning `name` / `version` literallari — KO'PRIK o'zligi."""
    tana = _funksiya_tanasi(_bsl_kod(), "МостОписаниеСборщика")
    nom = re.search(r'Вставить\(\s*"name"\s*,\s*"([^"]+)"', tana)
    versiya = re.search(r'Вставить\(\s*"version"\s*,\s*"([^"]+)"', tana)
    assert nom and versiya, "fikstura: ko'prik o'zligi manbadan ajratilmadi"
    return nom.group(1), versiya.group(1)


def _bsl_sxema_versiyalari() -> set[str]:
    """Manbadagi `binos-bridge-*-v1` sxema nomlari."""
    topilgan = set(re.findall(r'"(binos-bridge-[a-z-]+-v1)"', _bsl_kod()))
    assert topilgan, "fikstura: sxema versiya satri manbada topilmadi"
    return topilgan


def _version_json_ozligi() -> tuple[str, str]:
    yozilgan = json.loads(_matn(BRIDGE_VERSION))
    assert set(yozilgan) == {"collector"}, "VERSION.json shakli SHARTNOMA: faqat `collector`"
    sborshchik = yozilgan["collector"]
    assert set(sborshchik) == {"name", "version"}, "`collector` da AYNAN `name` + `version`"
    return sborshchik["name"], sborshchik["version"]


def _uch_manba(nima: str, python: object, version_json: object, bsl: object) -> str:
    """Xato matni AMALIY bo'lsin: QAYSI manba QAYSI qiymatni aytadi."""
    return (
        f"{nima} UCH manbada BIR XIL bo'lishi SHART, lekin ajralib ketdi:\n"
        f"  (1) PYTHON  ({proto.__name__} / {oc.__name__}): {python!r}\n"
        f"  (2) VERSION ({BRIDGE_VERSION.name}):             {version_json!r}\n"
        f"  (3) MANBA   ({BRIDGE_SRC.name}):                 {bsl!r}\n"
        f"⚠️ Bitta tomonni «tez tuzatish» YETMAYDI: uchovi bir vaqtda o'zgaradi, aks holda "
        f"to'plam yashil bo'lib turganda haqiqiy 1C da yurish rad etiladi.")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. YIG'UVCHI O'ZLIGI — UCHOVIDA AYNAN BIR XIL (QAROR A)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_YIGUVCHI_NOMI_UCH_manbada_AYNAN_bir_xil():
    """⚠️ TUZATILGAN P0 NING QULFI. `response.json` ni YOZADIGAN qatlam — KO'PRIK, demak
    `collector.name` ham KO'PRIKNING nomi. Agent ICHKI yig'uvchining nomini kutganida HAR
    BIR haqiqiy javob `WRONG_COLLECTOR_VERSION` bilan rad etilardi."""
    python = oc.EXPECTED_COLLECTOR_NAME
    version_json, _ = _version_json_ozligi()
    bsl, _ = _bsl_yiguvchi_ozligi()
    assert python == version_json == bsl, _uch_manba("yig'uvchi NOMI", python, version_json,
                                                     bsl)


def test_YIGUVCHI_VERSIYASI_UCH_manbada_AYNAN_bir_xil():
    python = oc.EXPECTED_COLLECTOR_VERSION
    _, version_json = _version_json_ozligi()
    _, bsl = _bsl_yiguvchi_ozligi()
    assert python == version_json == bsl, _uch_manba("yig'uvchi VERSIYASI", python,
                                                     version_json, bsl)


def test_YIGUVCHI_VERSIYASI_EPF_QURILMAGANINI_aytadi():
    """⚠️ `.epf` IKKILIK fayli QURILMAGAN — holat AYNAN `EPF_SOURCE_READY`. Versiya satri
    shuni AYTIB turishi SHART: `-source` qo'shimchasi yo'qolsa reliz «qurilgan» deb
    o'qilardi."""
    python = oc.EXPECTED_COLLECTOR_VERSION
    _, version_json = _version_json_ozligi()
    _, bsl = _bsl_yiguvchi_ozligi()
    for nima, qiymat in (("PYTHON", python), ("VERSION.json", version_json),
                         ("MANBA", bsl)):
        assert qiymat.endswith("-source"), (
            f"{nima} dagi versiya `-source` bilan tugamayapti: {qiymat!r}. `.epf` "
            f"QURILMAGAN va versiya buni OCHIQ aytishi SHART")


def test_ICHKI_YIGUVCHINING_ozligi_KOPRIK_ozligi_bilan_ARALASHMAYDI():
    """⚠️ IKKI O'ZLIK IKKITA BO'LIB QOLADI. ICHKI yig'uvchi (`BinOSDiscovery` /
    `0.2.0-UNVERIFIED`) o'z o'zligini Phase 4 shartnomasi bo'yicha `bundle/export.json`
    ning `collector` maydonida qoldiradi; ko'prik javobining `collector` i esa KO'PRIKNING
    o'zligi. Ikkisini aralashtirish — aynan tuzatilgan P0."""
    assert (oc.EXPECTED_COLLECTOR_NAME, oc.EXPECTED_COLLECTOR_VERSION) != (
        "BinOSDiscovery", "0.2.0-UNVERIFIED"), (
        "agent yana ICHKI yig'uvchining o'zligini kutyapti — `response.collector` ni "
        "KO'PRIK yozadi (`VERSION.json`), ICHKI yig'uvchi emas")
    assert oc.EXPECTED_COLLECTOR_NAME != "BinOSDiscovery", \
        "ko'prik o'zligi ICHKI yig'uvchining nomi bilan BIR XIL bo'lmasligi SHART"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. `status` LUG'ATI — PYTHON == MANBA, YADRO QISMI == `OVERALL_*` (QAROR B)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_HOLAT_lugati_PYTHON_va_MANBA_da_AYNAN_bir_xil():
    """⚠️⚠️ BU DARVOZANING ENG MUHIM TEKSHIRUVI. Tuzatilgan P0 (`OK` ↔ `SUCCESS`) AYNAN
         shu solishtiruv qilinmagani uchun to'plamdan o'tib ketgan edi: agent tomoni O'Z
         lug'atini, manba tomoni esa O'Z lug'atini o'lchardi va ikkisi hech qachon
         uchrashmasdi.

    ⚠️ IKKI YO'NALISH ham o'lchanadi va ikkisining ma'nosi BOSHQA:
       · MANBA yozadigan, PYTHON qabul qilmaydigan qiymat — HAR BIR shunday yurish
         `BRIDGE_SHAPE_INVALID` bilan rad etiladi, ya'ni yig'uvchining ANIQ javobi
         «fayl o'qilmadi» degan BOSHQA ma'noga aylanadi va operator boshqa yo'lga ketadi;
       · PYTHON qabul qiladigan, MANBA hech qachon yozmaydigan qiymat — E'LON QILINGAN,
         lekin YETIB BO'LMAYDIGAN tarmoq (o'lik shox). Bu `ABORTED_BY_OPERATOR`
         nuqsonining aynan sinfi.
    """
    python = set(proto.RESPONSE_STATUSES)
    bsl = _bsl_javob_holatlari()
    #: ⚠️ `CANCELLED` — ATAYLAB farq va u YOZIB QO'YILGAN (QAROR B): bekor qilish AGENT
    #:    tomonida sodir bo'ladi (`launcher.CancelToken`) va bunda yig'uvchi javob
    #:    YOZMAYDI, demak bu qiymatni manba hech qachon yozmaydi. Farq SHUNDAN BOSHQA
    #:    bo'lishi mumkin EMAS — ro'yxat ochiq qoldirilmaydi.
    KUTILGAN_FARQ = {proto.STATUS_CANCELLED}
    faqat_python = python - bsl
    faqat_bsl = bsl - python
    assert (faqat_python, faqat_bsl) == (KUTILGAN_FARQ, set()), (
        f"`status` lug'ati PYTHON va MANBA da AJRALIB KETDI:\n"
        f"  (1) PYTHON ({proto.__name__}.RESPONSE_STATUSES): {sorted(python)}\n"
        f"  (3) MANBA  ({BRIDGE_SRC.name} `response.json` ga YOZADI): {sorted(bsl)}\n"
        f"  · MANBA yozadi, PYTHON RAD ETADI: {sorted(faqat_bsl)}\n"
        f"      → har bir shunday yurish `BRIDGE_SHAPE_INVALID` bo'lib qaytadi, ya'ni\n"
        f"        yig'uvchining ANIQ javobi operatorga BOSHQA sabab bo'lib ko'rinadi;\n"
        f"  · PYTHON qabul qiladi, MANBA YOZMAYDI: {sorted(faqat_python)}\n"
        f"      → kutilgani FAQAT {sorted(KUTILGAN_FARQ)} (bekor qilish AGENT tomonida\n"
        f"        bo'ladi va bunda javob umuman yozilmaydi).\n"
        f"⚠️ TUZATISH YO'LI BITTA EMAS: yoki PYTHON lug'ati qiymatni QABUL QILADI, yoki\n"
        f"   MANBA uni YOZMAYDI. Qaysi biri — ARXITEKTOR qarori; «lug'atga qo'shib\n"
        f"   qo'yish» bilan o'tib ketish TAQIQLANGAN, chunki qiymatning MA'NOSI (operator\n"
        f"   keyingi qadami) ham belgilanishi kerak.")


def test_HOLAT_lugatining_YADRO_qismi_OVERALL_dan_IMPORT_qilinadi():
    """⚠️ IKKINCHI NUSXA YOZILMAYDI. `SUCCESS`/`PARTIAL`/`FAILED` Phase 4 ning `overall`
    lug'ati bo'lib, u `runtime_bundle` da yashaydi. Ko'prik ularni QAYTA E'LON QILSA, bir
    kun nusxa asl qiymatdan ajralib ketardi — tuzatilgan P0 ning aynan mexanizmi."""
    koprik = (proto.STATUS_SUCCESS, proto.STATUS_PARTIAL, proto.STATUS_FAILED)
    yadro_tartibi = (OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED)
    assert koprik == yadro_tartibi, (
        f"ko'prik holatlari `runtime_bundle.OVERALL_*` dan AJRALDI:\n"
        f"  (1) PYTHON ko'prik:      {koprik!r}\n"
        f"  (3) YADRO  `OVERALL_*`:  {yadro_tartibi!r}")
    yadro = {OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED}
    assert yadro <= set(proto.RESPONSE_STATUSES), \
        "yadroning har bir `overall` qiymati ko'prik lug'atida BO'LISHI SHART"
    assert yadro <= _bsl_javob_holatlari(), \
        "yadroning har bir `overall` qiymati MANBADA ham yozilishi SHART"


def test_HOLAT_lugatida_OK_qiymati_QAYTIB_KELMAYDI():
    """⚠️ `"OK"` OLIB TASHLANGAN: u `SUCCESS` ning DUBLIKATI edi va aynan shu nomuvofiqlik
    P0 ni tug'dirdi (yig'uvchi `SUCCESS` yozadi, agent `OK` kutadi)."""
    assert "OK" not in proto.RESPONSE_STATUSES, (
        "`OK` qiymati lug'atga QAYTDI — u `SUCCESS` ning dublikati va ikki qiymat bir "
        "ma'noni bildirsa, ikki tomon har xil tomonni tanlardi")
    assert "OK" not in _bsl_javob_holatlari(), "manba `OK` yozmaydi va yozmasligi SHART"
    assert proto.STATUS_OK == proto.STATUS_SUCCESS, (
        "`STATUS_OK` — ESKIRGAN NOM va u `STATUS_SUCCESS` ning AYNAN O'ZI bo'lishi SHART; "
        "qiymat ikki xil bo'lsa «ikki haqiqat» qaytadi")


def test_HOLAT_lugati_YOPIQ_va_TAKRORSIZ():
    """⚠️ Noma'lum qiymat RAD (fail-closed) va lug'at TAKRORSIZ: bir ma'no ikki nom bilan
    atalsa, ikki tomon har xil nomni tanlardi."""
    assert len(proto.RESPONSE_STATUSES) == len(set(proto.RESPONSE_STATUSES)), \
        "lug'atda TAKROR qiymat bor"
    # ⚠️ 4 -> 5: `BRIDGE_REJECTED` qo'shildi, chunki `.bsl` uni ALLAQACHON yozardi va
    #    Python tomoni uni bilmay «hujjat buzuq» deb ko'rsatardi. Lug'at hamon YOPIQ.
    assert len(proto.RESPONSE_STATUSES) == 5, (
        f"lug'at YOPIQ: AYNAN 5 qiymat kutiladi, topildi "
        f"{sorted(proto.RESPONSE_STATUSES)}")
    assert proto.STATUS_BRIDGE_REJECTED not in (OVERALL_SUCCESS, OVERALL_PARTIAL,
                                               OVERALL_FAILED), \
        "`BRIDGE_REJECTED` — ko'prikka XOS: Phase 4 da «razvedka boshlanmadi» tushunchasi YO'Q"
    assert proto.STATUS_CANCELLED not in (OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED), \
        "`CANCELLED` — ko'prikka XOS qiymat: Phase 4 da bekor qilish tushunchasi YO'Q"


def test_PARTIAL_jimgina_MUVAFFAQIYAT_deb_qabul_QILINMAYDI():
    """⚠️ `PARTIAL` `COLLECTOR_COMPLETE` fazasiga o'tadi (javob BOR, paket TO'LIQ), lekin
    hukmni QUVUR beradi — Phase 4 validatori kodi `2` ni hurmat qilib TO'XTAYDI (CP2
    qoidasi). Shu bois `Acceptance.status` da AYNAN `PARTIAL` QOLADI: uni `SUCCESS` ga
    aylantirish yarim natijani «tugadi» deb atardi."""
    assert proto.STATUS_PARTIAL in proto.RESPONSE_STATUSES
    assert proto.STATUS_PARTIAL != proto.STATUS_SUCCESS, \
        "`PARTIAL` va `SUCCESS` BOSHQA-BOSHQA qiymat bo'lishi SHART"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. HUJJAT KALITLARI — PYTHON OQ RO'YXATI == MANBA YOZADIGAN/O'QIYDIGAN KALITLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_JAVOB_kalitlari_PYTHON_va_MANBA_da_AYNAN_bir_xil():
    """⚠️ Phase 4 DARSI: kalit nomlari berilmaganda ikki tomon bo'shliqni har xil
    to'ldirgan. Shu bois tushib qolgan kalit ham, ortiqcha kalit ham RAD etiladi."""
    python = set(proto.RESPONSE_KEYS)
    bsl = _vstavit_kalitlari(_bsl_kod(), "Ответ")
    assert python == bsl, (
        f"`{proto.RESPONSE_FILE}` kalitlari AJRALDI:\n"
        f"  (1) PYTHON (`RESPONSE_KEYS`): {sorted(python)}\n"
        f"  (3) MANBA  (`Ответ.Вставить`): {sorted(bsl)}\n"
        f"  · faqat PYTHON da (manba YOZMAYDI → agent kalit yo'q deb RAD etadi): "
        f"{sorted(python - bsl)}\n"
        f"  · faqat MANBA da (agent oq ro'yxatda YO'Q deb RAD etadi): "
        f"{sorted(bsl - python)}")


def test_TUGALLANISH_BELGISINING_kalitlari_PYTHON_va_MANBA_da_AYNAN_bir_xil():
    """⚠️ `done_version` SHU TEKSHIRUVNING SABABI: sxema o'zligi FAYL ICHIDA bo'lmasa,
    `bridge_done.json` nomli BOSHQA sxemali fayl jimgina qabul qilinardi."""
    python = set(proto.DONE_KEYS)
    bsl = _vstavit_kalitlari(_bsl_kod(), "Метка")
    assert python == bsl, (
        f"`{proto.DONE_FILE}` kalitlari AJRALDI:\n"
        f"  (1) PYTHON (`DONE_KEYS`): {sorted(python)}\n"
        f"  (3) MANBA  (`Метка.Вставить`): {sorted(bsl)}\n"
        f"  · faqat PYTHON da: {sorted(python - bsl)}\n"
        f"  · faqat MANBA da: {sorted(bsl - python)}")


def test_SOROV_kalitlari_MANBA_oqiydigan_royxatga_mos():
    """⚠️ YO'NALISH ASIMMETRIK va buning sababi bor: `request.json` ni AGENT yozadi, ko'prik
    esa uni O'QIYDI. Shu bois manba O'QIYDIGAN har kalit Python oq ro'yxatida bo'lishi
    SHART (aks holda ko'prik yo'q maydonni so'raydi), teskarisi esa SHART EMAS — lekin
    O'QILMAYDIGAN kalitlar ro'yxati YOZIB QO'YILADI, chunki «yubordim / olmadim» juftligi
    aynan shu bo'shliqda tug'iladi."""
    python = set(proto.REQUEST_KEYS)
    oqilgan = _sorov_oqilgan_kalitlar(_bsl_kod())
    assert oqilgan <= python, (
        f"MANBA Python oq ro'yxatida YO'Q so'rov maydonini o'qiyapti: "
        f"{sorted(oqilgan - python)}\n"
        f"  (1) PYTHON (`REQUEST_KEYS`): {sorted(python)}\n"
        f"  (3) MANBA  (`МостПоле(Запрос, ...)`): {sorted(oqilgan)}\n"
        f"⚠️ Agent bu maydonni HECH QACHON yozmaydi — ko'prik uni doim standart qiymat "
        f"bilan oladi va qaror JIMGINA o'zgaradi")
    #: ⚠️ `notes` — ATAYLAB o'qilmaydi: u OPERATORGA qaratilgan matn (`REQUEST_NOTES`) va
    #:    ko'prik undan BIRORTA qaror chiqarmaydi. Ro'yxat PINLANGAN: yangi o'qilmaydigan
    #:    maydon paydo bo'lsa, u «yuborildi, lekin hech kim ko'rmadi» bo'lib qolardi.
    KUTILGAN_OQILMAGAN = {"notes"}
    assert python - oqilgan == KUTILGAN_OQILMAGAN, (
        f"MANBA O'QIMAYDIGAN so'rov maydonlari o'zgardi: {sorted(python - oqilgan)}, "
        f"kutilgani {sorted(KUTILGAN_OQILMAGAN)}.\n"
        f"⚠️ Agent yozadigan, ko'prik esa o'qimaydigan maydon — JIM qoladigan shartnoma: "
        f"agent «cheklov yubordim» deb hisoblaydi, ko'prik esa uni KO'RMAYDI. Maydon "
        f"kerak bo'lsa MANBA uni o'qisin; kerak bo'lmasa `REQUEST_KEYS` dan OLINSIN.")


def test_KALIT_SONLARI_SHARTNOMA_bolib_qoladi():
    """⚠️ Yangi maydon FAQAT versiya oshganda qo'shiladi: sxema nomi o'zgarmasdan maydon
    qo'shilsa, eski agent yangi javobni jimgina boshqa ma'noda o'qirdi."""
    assert (len(proto.REQUEST_KEYS), len(proto.RESPONSE_KEYS), len(proto.DONE_KEYS)) == \
        (10, 9, 4), (
        f"kalit sonlari o'zgardi: so'rov {len(proto.REQUEST_KEYS)}, "
        f"javob {len(proto.RESPONSE_KEYS)}, belgi {len(proto.DONE_KEYS)}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. SXEMA VERSIYA SATRLARI VA FAYL NOMLARI — UCHOVIDA MOS
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_SXEMA_VERSIYA_satrlari_UCH_manbada_mos():
    """⚠️ UCHINCHI MANBA BU YERDA — OPERATOR HUJJATI (`VERSION.json` sxema nomlarini
    aytmaydi). Hujjat eskirsa, nosozlikni uzatgan operator ishlab chiquvchiga BOSHQA sxema
    nomini aytardi."""
    python = {proto.REQUEST_VERSION, proto.RESPONSE_VERSION, proto.DONE_VERSION}
    bsl = _bsl_sxema_versiyalari()
    hujjat = set(re.findall(r"binos-bridge-[a-z-]+-v1", _matn(FLOW_DOC)))
    assert python == bsl == hujjat, (
        f"sxema versiya satrlari AJRALDI:\n"
        f"  (1) PYTHON ({proto.__name__}): {sorted(python)}\n"
        f"  (3) MANBA  ({BRIDGE_SRC.name}): {sorted(bsl)}\n"
        f"  (3') HUJJAT ({FLOW_DOC.name}): {sorted(hujjat)}")
    assert len(python) == 3, "uch hujjat uch BOSHQA sxema nomiga ega bo'lishi SHART"


def test_FAYL_NOMLARI_PYTHON_va_MANBA_da_mos():
    kod = _bsl_kod()
    for nom in (proto.REQUEST_FILE, proto.RESPONSE_FILE, proto.DONE_FILE):
        assert f'"{nom}"' in kod, (
            f"shartnoma fayl nomi manbada YO'Q: {nom!r} — agent va ko'prik BOSHQA-BOSHQA "
            f"faylga qarardi va ikkisi ham «qarshi tomon yozmadi» deb hisoblardi")
    #: ⚠️ `cancel_requested.json` — nom SHARTNOMA sifatida band qilingan, lekin uni manba
    #:    O'QIMAYDI: bekor qilish AGENT tomonida (kooperativ kutishni to'xtatish). «1C
    #:    ichidagi yig'uvchi ham to'xtaydi» degan da'vo BERILMAYDI va bu test shu halol
    #:    qaydni qulflaydi.
    assert f'"{proto.CANCEL_FILE}"' not in kod, (
        f"manba ENDI {proto.CANCEL_FILE!r} ni o'qiyapti — agar bu ATAYLAB bo'lsa, "
        f"`bridge_protocol.CANCEL_FILE` izohidagi «yozadigan kod YO'Q» qaydi va "
        f"`AGENT_ONE_CLICK_FLOW.md` dagi bekor qilish bo'limi ham TUZATILSIN")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. TO'RTINCHI NUSXA — SHARTNOMA TEST FAYLIDA QAYTA E'LON QILINGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def _test_faylining_tuplasi(nom: str) -> set[str]:
    """`test_agent_collector_source.py` dagi `<nom> = (...)` to'plamini o'qiydi."""
    moslik = re.search(rf"^{nom}\s*=\s*\((.*?)\)\s*$", _matn(SOURCE_TEST),
                       re.S | re.M)
    assert moslik, f"fikstura: `{SOURCE_TEST.name}` da `{nom}` topilmadi"
    return set(re.findall(r'"([^"]+)"', moslik.group(1)))


def test_TORTINCHI_NUSXA_bridge_protocol_dan_AJRALIB_KETMAGAN():
    """⚠️⚠️ NUSXANING O'ZI DRIFT KANALI. `test_agent_collector_source.py` kalit
         ro'yxatlarini `bridge_protocol` dan IMPORT qilmaydi — ularni QAYTA e'lon qiladi.
         Ya'ni shartnomaning TO'RTINCHI nusxasi bor va u yashil bo'lib turganda ham asl
         ro'yxatdan ajralib ketishi mumkin. Aynan shu naqsh (ikki nusxa, biri eskirgan)
         bu bosqichdagi ikki P0 ning sababi edi.

    ⚠️ Nusxa o'z joyida qolishi mumkin, LEKIN u asl ro'yxat bilan AYNAN mos bo'lishi SHART.
       To'g'ri tuzatish — nusxani `bridge_protocol` dan IMPORT qilish.
    """
    for nom, asl in (("REQUEST_KEYS", proto.REQUEST_KEYS),
                     ("RESPONSE_KEYS", proto.RESPONSE_KEYS),
                     ("DONE_KEYS", proto.DONE_KEYS)):
        nusxa = _test_faylining_tuplasi(nom)
        assert nusxa == set(asl), (
            f"shartnomaning TO'RTINCHI nusxasi ajralib ketdi — `{nom}`:\n"
            f"  (1) ASL   ({proto.__name__}.{nom}): {sorted(asl)}\n"
            f"  (4) NUSXA ({SOURCE_TEST.name}.{nom}): {sorted(nusxa)}\n"
            f"  · faqat ASLDA: {sorted(set(asl) - nusxa)}\n"
            f"  · faqat NUSXADA: {sorted(nusxa - set(asl))}\n"
            f"⚠️ Nusxa KAMROQ kalitni sanasa, u «har maydon yoziladi» deb ATAB turib, "
            f"aslida bir qismini TEKSHIRMAYDI — darvoza o'zini kuchliroq ko'rsatadi. "
            f"TUZATISH: `{SOURCE_TEST.name}` da ro'yxatni qo'lda yozmasdan "
            f"`bridge_protocol` dan IMPORT qilish.")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. DARVOZANING O'ZI ISHLAYOTGANINING ISBOTI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ NEGA BU BO'LIM BOR: anti-drift darvozasining eng yomon yiqilishi — JIM O'CHISH.
#      Agar `.bsl` ning shakli o'zgarsa va ajratuvchilar bo'sh to'plam qaytarsa, yuqoridagi
#      hamma solishtiruv «bo'sh == bo'sh» bo'lib YASHIL qolardi. Shu bois ajratuvchilarning
#      HAR BIRI real qiymat qaytarishi ALOHIDA o'lchanadi.
def test_AJRATUVCHILAR_bosh_TOPLAM_qaytarmaydi():
    assert len(_bsl_javob_holatlari()) >= 3, "javob holatlari ajratuvchisi JIM o'chdi"
    assert len(_vstavit_kalitlari(_bsl_kod(), "Ответ")) >= 9, "javob kalitlari ajratilmadi"
    assert len(_vstavit_kalitlari(_bsl_kod(), "Метка")) >= 4, "belgi kalitlari ajratilmadi"
    assert len(_sorov_oqilgan_kalitlar(_bsl_kod())) >= 9, "so'rov kalitlari ajratilmadi"
    assert len(_bsl_sxema_versiyalari()) == 3, "sxema versiyalari ajratilmadi"
    nom, versiya = _bsl_yiguvchi_ozligi()
    assert nom and versiya, "ko'prik o'zligi ajratilmadi"


def test_AJRATUVCHI_IZOHDAGI_qiymatni_HISOBGA_OLMAYDI():
    """⚠️ Bu darvoza `grep` EMAS. Izohda eski qiymat («ilgari `OK` edi») turishi MUMKIN va
    u 1C da hech narsa yozmaydi. Ajratuvchi izohni hisoblasa, eskirgan izoh darvozani
    chalg'itardi."""
    xom = _matn(BRIDGE_SRC)
    kod = _bsl_kod()
    assert "// " in xom, "fikstura: manbada izoh yo'q"
    #: Manbadagi izoh satrlarining birortasi kodga TUSHMAGANINI o'lchash uchun: izohda
    #: uchraydigan, kodda esa UCHRAMAYDIGAN kamida bitta so'z bo'lishi SHART.
    assert "Phase 4" in xom and "Phase 4" not in kod, (
        "izoh matni kod satrlariga tushib qolgan — ajratuvchi izohni ham o'lchayapti va "
        "eskirgan izoh darvozani chalg'itishi mumkin")


def test_DARVOZA_1C_ga_ULANMAYDI_va_FAQAT_MATN_oqiydi():
    """⚠️ HALOL QAYD: bu fayl 1C ga ulanmaydi, tarmoqqa chiqmaydi va jarayon ishga
    tushirmaydi — u faqat repodagi UCH faylni O'QIYDI. `.epf` QURILMAGAN, holat AYNAN
    `EPF_SOURCE_READY` va bu test uni QURILGAN deb AYTMAYDI."""
    #: ⚠️ O'LCHOV IMPORT RO'YXATI BO'YICHA, MATN QIDIRUVI BILAN EMAS: bu faylning O'ZIDA
    #:    taqiqlangan modul NOMI matn bo'lib turadi (aynan shu ro'yxatda), ya'ni oddiy
    #:    `in` qidiruvi HAR DOIM yiqilardi — darvoza o'zini o'zi rad etardi.
    daraxt = ast.parse(_matn(pathlib.Path(__file__)))
    import_qilingan: set[str] = set()
    for tugun in ast.walk(daraxt):
        if isinstance(tugun, ast.Import):
            import_qilingan |= {a.name.split(".")[0] for a in tugun.names}
        elif isinstance(tugun, ast.ImportFrom) and tugun.module:
            import_qilingan.add(tugun.module.split(".")[0])
    TAQIQ = {"subprocess", "socket", "requests", "win32com", "urllib", "httpx", "os"}
    assert not (import_qilingan & TAQIQ), (
        f"bu darvoza TAQIQLANGAN modulni import qilyapti: "
        f"{sorted(import_qilingan & TAQIQ)}. U 1C ga ULANMAYDI, tarmoqqa CHIQMAYDI va "
        f"jarayon ISHGA TUSHIRMAYDI — faqat repodagi matnni o'qiydi")
    for yol in (BRIDGE_SRC, BRIDGE_VERSION, FLOW_DOC, SOURCE_TEST):
        assert yol.is_file(), f"shartnoma manbasi topilmadi: {yol}"
