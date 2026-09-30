# -*- coding: utf-8 -*-
"""IKKI TOMON SHAKLINI SOLISHTIRADIGAN DARVOZA — `BinOSDiscovery.bsl` ↔ `runtime_bundle.py`.

⚠️ NIMANI ISBOTLAYDI: yig'uvchi (BSL) `run_status.json`, `errors.json`, `manifest.json` va
   zond natijasiga AYNAN qaysi KALITLARNI yozishini — manbadan STATIK ajratib olib —
   validatorning oq ro'yxatlari bilan solishtiradi. Shuningdek `overall` ning TA'RIFI ikki
   tomonda bir xil javob berishini sanoqli holatlar jadvali bilan tekshiradi.
⚠️ NIMANI ISBOTLAMAYDI: modulning 1C da ISHLASHINI. Bu mashinada 1C:Enterprise YO'Q.
   Shakllar tengligi — ZARURIY shart, YETARLI emas: yig'uvchining runtime holati
   `RUNTIME-UNKNOWN` bo'lib qoladi.

⚠️ NEGA BU FAYL BOR — ILDIZ SABAB. Ko'rik topdi: `binos-1c-run-v1`, `binos-1c-errors-v1`,
   `binos-1c-manifest-v1` va zond natijasining IKKI TOMONI bir-biriga ZID edi, ya'ni HAR BIR
   real paket validatordan RAD etilardi. To'plam shunda ham YASHIL edi, chunki BIRORTA test
   ikki tomonni SOLISHTIRMAGAN: har tomon O'Z shaklini sinardi. Bu Phase 2 dagi nuqsonning
   AYNAN O'ZI (BSL to'plam sxemasiga mos kelmasdi), faqat bir qatlam yuqorida. Shu bois
   himoya SHAKLLAR TENGLIGINI tekshiradi, har tomonni alohida EMAS.

⚠️ NEGA STATIK TAHLIL, NEGA ISHLATISH EMAS. BSL ni bajarib ko'rish uchun 1C kerak. Lekin
   KALIT NOMLARI manbada MATN LITERALI bo'lib turadi (`Вставить("<kalit>", …)`), ya'ni
   ularni bajarmasdan ham ANIQ o'qish mumkin. Shakl tengligi — aynan shu literallar haqidagi
   savol, xatti-harakat haqidagi savol emas.

⚠️ BU DARVOZA KELAJAK UCHUN: kimdir BIR tomonga kalit qo'shsa yoki lug'atni o'zgartirsa, CI
   shu yerda QIZIL bo'ladi va xato matni qaysi kalit QAYSI funksiyada yo'qligini aytadi.
"""
from __future__ import annotations

import itertools
import pathlib
import re

import pytest

from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.bundle import SECTION_STATUSES
from app.services.discovery_1c.probe import PROBE_VERSION

from tests.discovery_1c_runtime_mock import COLLECTOR

_REPO = pathlib.Path(rb.__file__).resolve().parents[5]
BSL = _REPO / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl"


# ══════════════════════════════════════════════════════════════════════════════════════════
# BSL MANBASINI STATIK O'QISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def _izohsiz(matn: str) -> str:
    """BSL matnini IZOHLARSIZ qaytaradi.

    ⚠️ NEGA IZOHLAR OLIB TASHLANADI: bu fayldagi izohlar shakl haqida GAPIRADI va ularda
       `Вставить("...")` kabi namunalar uchrashi mumkin. Izohdagi namuna «yozilgan kalit»
       bo'lib sanalsa, darvoza YOLG'ON yashil bo'lardi: kimdir kalitni kod'dan olib
       tashlab izohda qoldirsa test o'tib ketardi.
    ⚠️ QO'SHTIRNOQ HISOBGA OLINADI: `//` faqat juft sonli qo'shtirnoqdan KEYIN kelsa izoh
       deb qaraladi, ya'ni satr literali ichidagi `//` kesilmaydi. (Hozirgi manbada bunday
       literal YO'Q — `test_izoh_kesuvchisi_SATR_LITERALINI_buzmaydi` buni qulflaydi.)"""
    satrlar = []
    for satr in matn.splitlines():
        i = satr.find("//")
        while i >= 0:
            if satr.count('"', 0, i) % 2 == 0:
                satr = satr[:i]
                break
            i = satr.find("//", i + 2)
        satrlar.append(satr)
    return "\n".join(satrlar)


@pytest.fixture(scope="module")
def bsl() -> str:
    assert BSL.is_file(), f"yig'uvchi manbasi topilmadi: {BSL}"
    return _izohsiz(BSL.read_text(encoding="utf-8"))


def _tana(bsl_matni: str, nom: str) -> str:
    """`Функция`/`Процедура <nom>` ning TANASI (e'londan `КонецФункции`/`КонецПроцедуры` gacha).

    ⚠️ Xato matni AMALIY: funksiya topilmasa nomi bilan aytiladi, chunki funksiya QAYTA
       NOMLANGANDA darvoza jimgina bo'shab qolmasligi kerak."""
    bosh = re.search(rf"^(?:Функция|Процедура)\s+{re.escape(nom)}\s*\(", bsl_matni, re.M)
    assert bosh, (f"BSL da `{nom}` funksiyasi/protsedurasi topilmadi — qayta nomlangan bo'lsa "
                  f"bu darvoza ham yangilanishi SHART (aks holda u hech narsani tekshirmaydi)")
    oxir = re.search(r"^(?:КонецФункции|КонецПроцедуры)", bsl_matni[bosh.start():], re.M)
    assert oxir, f"`{nom}` ning tanasi yopilmagan"
    return bsl_matni[bosh.start():bosh.start() + oxir.end()]


def _vstavit_kalitlari(tana: str) -> list[str]:
    """Tanadagi `<nimadir>.Вставить("<kalit>"` literallari — YOZILISH TARTIBIDA."""
    return re.findall(r'\.Вставить\(\s*"([^"]+)"', tana)


def _chaqiruvlar(bsl_matni: str, nom: str) -> list[str]:
    """`<nom>(...)` CHAQIRUVLARINING argument matni.

    ⚠️ E'LONNING O'ZI (`Функция`/`Процедура <nom>(`) tushib qoladi va bu POZITSIYA bo'yicha
       hal qilinadi, matn qidirish bilan EMAS: e'londagi parametr nomlari bilan bir xil
       matn boshqa joyda ham uchrashi mumkin edi va u holda haqiqiy chaqiruv jimgina
       tashlanib ketardi (darvoza bo'shab qolardi)."""
    natija = []
    for mos in re.finditer(rf"(?<![А-Яа-яЁёA-Za-z_]){re.escape(nom)}\(\s*(.*?)\)\s*;",
                           bsl_matni, re.S):
        satr_boshi = bsl_matni.rfind("\n", 0, mos.start()) + 1
        oldi = bsl_matni[satr_boshi:mos.start()]
        if re.fullmatch(r"\s*(?:Функция|Процедура)\s+", oldi):
            continue
        natija.append(mos.group(1))
    return natija


def _arg_literali(argumentlar: str, orin: int) -> str | None:
    """Argument ro'yxatining `orin`-chi (0 dan) elementi MATN LITERALI bo'lsa — uning qiymati.

    ⚠️ Yuqori darajadagi vergul bo'yicha bo'linadi: qo'shtirnoq ichidagi vergul va
       qavs ichidagi vergul AJRATUVCHI emas (`Формат(X, "ЧГ=0")` bitta argument)."""
    bolaklar, joriy, chuqurlik, literalda = [], [], 0, False
    for ch in argumentlar:
        if ch == '"':
            literalda = not literalda
        if not literalda:
            if ch in "([":
                chuqurlik += 1
            elif ch in ")]":
                chuqurlik -= 1
            elif ch == "," and chuqurlik == 0:
                bolaklar.append("".join(joriy))
                joriy = []
                continue
        joriy.append(ch)
    bolaklar.append("".join(joriy))
    if orin >= len(bolaklar):
        return None
    mos = re.fullmatch(r'\s*"([^"]*)"\s*', bolaklar[orin], re.S)
    return mos.group(1) if mos else None


def _chaqiruv_literallari(bsl_matni: str, nom: str, orin: int) -> list[str]:
    """`<nom>` ning HAR chaqiruvidagi `orin`-chi argument literali (literal bo'lmaganlar tashlanadi)."""
    natija = []
    for arg in _chaqiruvlar(bsl_matni, nom):
        qiymat = _arg_literali(arg, orin)
        if qiymat is not None:
            natija.append(qiymat)
    return natija


def _solishtir(bsl_kalitlari: set[str], validator_kalitlari: set[str], *,
               funksiya: str, hujjat: str) -> None:
    """Ikki tomonning kalit to'plamini SOLISHTIRADI va farqni ALOHIDA-ALOHIDA aytadi.

    ⚠️ NEGA IKKI RO'YXAT ALOHIDA: «mos kelmadi» degan xato bilan hech kim hech narsani
       tuzatmaydi. Yetishmaydigan kalit — yig'uvchi YOZMAYDIGAN maydon (validator uni
       TALAB qiladi, ya'ni paket rad etiladi); qo'shimcha kalit — yig'uvchi YOZADIGAN,
       lekin validator TANIMAYDIGAN maydon (oq ro'yxat uni rad etadi). Ikki nuqson,
       ikki xil tuzatish."""
    yetishmaydi = sorted(validator_kalitlari - bsl_kalitlari)
    qoshimcha = sorted(bsl_kalitlari - validator_kalitlari)
    assert not yetishmaydi and not qoshimcha, (
        f"{hujjat}: IKKI TOMON SHAKLI ZID.\n"
        f"  · validator TALAB qiladi, BSL `{funksiya}` da YOZILMAGAN: {yetishmaydi}\n"
        f"  · BSL `{funksiya}` YOZADI, validator oq ro'yxatida YO'Q: {qoshimcha}\n"
        f"  BSL yozadigan kalitlar: {sorted(bsl_kalitlari)}\n"
        f"  validator oq ro'yxati:  {sorted(validator_kalitlari)}")


def test_izoh_kesuvchisi_SATR_LITERALINI_buzmaydi():
    """⚠️ `_izohsiz` ning O'ZI tekshiriladi: hozirgi manbada satr literali ichida `//`
       YO'Q, ya'ni kesuvchi birorta kalitni yo'qotmaydi. Bunday literal qo'shilsa bu test
       yiqiladi va kesuvchi qayta yozilishi kerak bo'ladi — jimgina kalit yo'qolmaydi."""
    xom = BSL.read_text(encoding="utf-8")
    shubhali = []
    for nomer, satr in enumerate(xom.splitlines(), 1):
        i = satr.find("//")
        while i >= 0:
            if satr.count('"', 0, i) % 2 == 1:
                shubhali.append(nomer)
                break
            i = satr.find("//", i + 2)
    assert not shubhali, (f"satr literali ichida `//` bor (satrlar {shubhali}) — `_izohsiz` "
                          f"uni izoh deb kesib, kalit literalini yo'qotishi mumkin")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · `run_status.json` KALITLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_run_status_kalitlari_IKKI_TOMONDA_AYNAN_MOS(bsl):
    """`СобратьСостояниеЗапуска` yozadigan kalitlar == `runtime_bundle.RUN_KEYS`."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "СобратьСостояниеЗапуска"))
    assert kalitlar, "`СобратьСостояниеЗапуска` da birorta `Вставить(\"...\")` topilmadi"
    _solishtir(set(kalitlar), set(rb.RUN_KEYS),
               funksiya="СобратьСостояниеЗапуска", hujjat="run_status.json (binos-1c-run-v1)")


def test_run_status_kalitini_IKKI_MARTA_yozmaydi(bsl):
    """⚠️ Takroriy `Вставить` 1C da ISTISNO beradi (`Структура` ga bir xil kalitni ikki marta
       qo'yib bo'lmaydi), ya'ni yurish o'sha yerda uzilardi — va bu yozilmagan nuqson
       bo'lardi, chunki kalit TO'PLAMI baribir to'g'ri ko'rinadi."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "СобратьСостояниеЗапуска"))
    takror = sorted({k for k in kalitlar if kalitlar.count(k) > 1})
    assert not takror, f"`СобратьСостояниеЗапуска` kalitni takror yozadi: {takror}"


def test_run_status_VERSIYA_literali_IKKI_TOMONDA_MOS(bsl):
    tana = _tana(bsl, "СобратьСостояниеЗапуска")
    assert f'"{rb.RUN_VERSION}"' in tana, (
        f"`СобратьСостояниеЗапуска` `run_version` ni {rb.RUN_VERSION!r} deb yozmaydi — "
        f"validator AYNAN shu matnni talab qiladi")


def test_collector_kalitlari_IKKI_TOMONDA_MOS(bsl):
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ОписаниеСборщика"))
    _solishtir(set(kalitlar), set(rb.COLLECTOR_KEYS),
               funksiya="ОписаниеСборщика", hujjat="run_status.collector")


def test_collector_version_BSL_va_mock_fiksturada_BIR_XIL(bsl):
    """⚠️ Mock fikstura yig'uvchining O'RNIDA turadi. Versiyasi ajralib ketsa, to'plam
       REAL paketda bo'lmagan versiyani sinab, «tekshirildi» degan yolg'on qoldirardi."""
    tana = _tana(bsl, "ОписаниеСборщика")
    mos = re.search(r'\.Вставить\(\s*"version",\s*"([^"]+)"', tana)
    assert mos, "`ОписаниеСборщика` `version` ni MATN LITERALI bilan yozmaydi"
    assert mos.group(1) == COLLECTOR["version"], (
        f"collector.version ajralgan: BSL {mos.group(1)!r}, mock fikstura "
        f"{COLLECTOR['version']!r} — biri o'zgarsa ikkinchisi ham o'zgarishi SHART")
    mos_nom = re.search(r'\.Вставить\(\s*"name",\s*"([^"]+)"', tana)
    assert mos_nom and mos_nom.group(1) == COLLECTOR["name"], (
        f"collector.name ajralgan: BSL {mos_nom and mos_nom.group(1)!r}, mock "
        f"{COLLECTOR['name']!r}")


def test_bolim_yozuvi_kalitlari_IKKI_TOMONDA_MOS(bsl):
    """`НовыйРаздел` — UCHALA jurnalning yozuv quruvchisi (`sections[]`)."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "НовыйРаздел"))
    _solishtir(set(kalitlar), set(rb.RUN_SECTION_KEYS),
               funksiya="НовыйРаздел", hujjat="run_status.sections[]")


def test_oila_yozuvi_kalitlari_IKKI_TOMONDA_MOS(bsl):
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ОтметитьСемейство"))
    _solishtir(set(kalitlar), set(rb.FAMILY_KEYS),
               funksiya="ОтметитьСемейство", hujjat="run_status.families[]")


def test_zond_jurnali_kalitlari_IKKI_TOMONDA_MOS(bsl):
    """`ВыполнитьРазрешенныеЗонды` da qurilgan JURNAL qatori (`run_status.probes[]`).

    ⚠️ Zond NATIJASI boshqa hujjat (`PROBE_RESULT_KEYS`) va u alohida tekshiriladi."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ВыполнитьРазрешенныеЗонды"))
    _solishtir(set(kalitlar), set(rb.PROBE_LOG_KEYS),
               funksiya="ВыполнитьРазрешенныеЗонды", hujjat="run_status.probes[]")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · `errors.json` KALITLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_errors_hujjati_kalitlari_IKKI_TOMONDA_MOS(bsl):
    kalitlar = _vstavit_kalitlari(_tana(bsl, "СобратьОшибки"))
    _solishtir(set(kalitlar), set(rb.ERRORS_DOC_KEYS),
               funksiya="СобратьОшибки", hujjat="errors.json (binos-1c-errors-v1)")


def test_errors_VERSIYA_literali_IKKI_TOMONDA_MOS(bsl):
    assert f'"{rb.ERRORS_VERSION}"' in _tana(bsl, "СобратьОшибки"), (
        f"`СобратьОшибки` `errors_version` ni {rb.ERRORS_VERSION!r} deb yozmaydi")


def test_errors_yozuvi_kalitlari_IKKI_TOMONDA_MOS(bsl):
    """`ДобавитьОшибку` — `errors[]` yozuvining YAGONA quruvchisi."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ДобавитьОшибку"))
    _solishtir(set(kalitlar), set(rb.ERROR_KEYS),
               funksiya="ДобавитьОшибку", hujjat="errors.errors[]")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · `manifest.json` KALITLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_manifest_hujjati_kalitlari_IKKI_TOMONDA_MOS(bsl):
    kalitlar = _vstavit_kalitlari(_tana(bsl, "СобратьМанифест"))
    _solishtir(set(kalitlar), set(rb.MANIFEST_DOC_KEYS),
               funksiya="СобратьМанифест", hujjat="manifest.json (binos-1c-manifest-v1)")


def test_manifest_VERSIYA_literali_IKKI_TOMONDA_MOS(bsl):
    assert f'"{rb.MANIFEST_VERSION}"' in _tana(bsl, "СобратьМанифест"), (
        f"`СобратьМанифест` `manifest_version` ni {rb.MANIFEST_VERSION!r} deb yozmaydi")


def test_manifest_fayl_yozuvi_kalitlari_IKKI_TOMONDA_MOS(bsl):
    """`ЗарегистрироватьФайл` — `manifest.files[]` yozuvining quruvchisi."""
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ЗарегистрироватьФайл"))
    _solishtir(set(kalitlar), set(rb.MANIFEST_FILE_KEYS),
               funksiya="ЗарегистрироватьФайл", hujjat="manifest.files[]")


@pytest.mark.parametrize("taqiq", rb.FORBIDDEN_MANIFEST_KEYS)
def test_manifest_MANBA_provenansini_YOZMAYDI(bsl, taqiq):
    """⚠️ Phase 2 QOIDASI: `source_copy`, `snapshot_at`, `plan_sha256` QO'SHILMAYDI — ular
       metadata razvedkasidan kelib chiqmaydi, ya'ni yozilsa YOLG'ON kafolat bo'lardi.
       Kalit oq ro'yxati ularni allaqachon to'sadi, lekin nuqson shu yerda — MANBADA —
       aytilsa, sabab bilan aytiladi."""
    for funksiya in ("СобратьМанифест", "ЗарегистрироватьФайл"):
        kalitlar = _vstavit_kalitlari(_tana(bsl, funksiya))
        assert taqiq not in kalitlar, (
            f"`{funksiya}` manifestga MANBA provenansi maydonini yozadi: {taqiq!r}. "
            f"Manifest faqat YOZILGAN BAYTLARNI tasdiqlaydi")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · ZOND NATIJASI (`binos-1c-probe-v1`)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_zond_natijasi_kalitlari_IKKI_TOMONDA_MOS(bsl):
    kalitlar = _vstavit_kalitlari(_tana(bsl, "ВыполнитьЗонд"))
    _solishtir(set(kalitlar), set(rb.PROBE_RESULT_KEYS),
               funksiya="ВыполнитьЗонд", hujjat="probes/NN_<tur>.json (binos-1c-probe-v1)")


def test_zond_natijasi_VERSIYA_literali_IKKI_TOMONDA_MOS(bsl):
    assert f'"{PROBE_VERSION}"' in _tana(bsl, "ВыполнитьЗонд"), (
        f"`ВыполнитьЗонд` `probe_version` ni {PROBE_VERSION!r} deb yozmaydi")


def test_zond_natijasi_read_only_AYNAN_matn_true(bsl):
    """⚠️ Validator AYNAN `"true"` MATNINI talab qiladi: `Булево` JSON'da `true` bo'lib
       ketardi va uchinchi holat (`"unknown"`) yo'qolardi."""
    tana = _tana(bsl, "ВыполнитьЗонд")
    mos = re.search(r'\.Вставить\(\s*"read_only",\s*([^)]+)\)', tana)
    assert mos, "`ВыполнитьЗонд` `read_only` ni yozmaydi"
    assert mos.group(1).strip() == '"true"', (
        f"`read_only` AYNAN `\"true\"` MATNI bo'lishi kerak, BSL da: {mos.group(1).strip()}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · LUG'ATLAR: oila holati, xato qamrovi/kodi, bo'lim holati
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_oila_holatlari_VALIDATOR_lugatidan(bsl):
    """`ОтметитьСемейство(<nom>, "<holat>", …)` chaqiruvlaridagi holatlar ⊆ `FAMILY_STATES`."""
    holatlar = _chaqiruv_literallari(bsl, "ОтметитьСемейство", 1)
    assert holatlar, "`ОтметитьСемейство` birorta literal holat bilan chaqirilmagan"
    begona = sorted(set(holatlar) - set(rb.FAMILY_STATES))
    assert not begona, (f"`ОтметитьСемейство` validator lug'atida yo'q oila holatini yozadi: "
                        f"{begona}. Ruxsat: {list(rb.FAMILY_STATES)}")


def test_oila_holatlari_UCHOVI_HAM_ishlatilgan(bsl):
    """⚠️ NEGA UCHOVI SHART: `absent` («o'qildi va YO'Q») va `unreadable` («o'qiy olmadim»)
       farqi razvedkaning O'ZAGI. Biri manbada UMUMAN ishlatilmasa, ajrim faqat
       hujjatda yashardi va yig'uvchi ikkisini bir xil yozib yuborardi."""
    holatlar = set(_chaqiruv_literallari(bsl, "ОтметитьСемейство", 1))
    tushgan = sorted(set(rb.FAMILY_STATES) - holatlar)
    assert not tushgan, (f"BSL birorta joyda bu oila holat(lar)ini yozmaydi: {tushgan} — "
                         f"lug'at ikki tomonda bor, lekin manbada ishlatilmagan")


def test_bolim_holatlari_FAQAT_ok_failed_skipped(bsl):
    """⚠️ NUQSONNING AYNAN O'ZI: ilgari bo'lim jurnaliga `absent`/`unreadable` ham
       yozilardi, validator esa bo'lim lug'atida ularni UMUMAN qabul qilmaydi. Oila
       holati FAQAT `families[].state` da yashaydi."""
    for belgilovchi in ("ОтметитьЗапуск", "ОтметитьРаздел", "ОтметитьРазделМетаданных"):
        holatlar = _chaqiruv_literallari(bsl, belgilovchi, 1)
        assert holatlar, f"`{belgilovchi}` birorta literal holat bilan chaqirilmagan"
        begona = sorted(set(holatlar) - set(SECTION_STATUSES))
        assert not begona, (
            f"`{belgilovchi}` bo'lim holati sifatida {begona} yozadi — bo'lim lug'ati "
            f"{list(SECTION_STATUSES)}. ⚠️ `absent`/`unreadable` bo'lim holati EMAS, "
            f"ular FAQAT `families[].state` da")


def test_xato_qamrovlari_VALIDATOR_lugatidan(bsl):
    qamrovlar = _chaqiruv_literallari(bsl, "ДобавитьОшибку", 0)
    assert qamrovlar, "`ДобавитьОшибку` birorta literal qamrov bilan chaqirilmagan"
    begona = sorted(set(qamrovlar) - set(rb.ERROR_SCOPES))
    assert not begona, (f"`ДобавитьОшибку` validator lug'atida yo'q qamrov yozadi: {begona}. "
                        f"Ruxsat: {list(rb.ERROR_SCOPES)}")


def test_xato_kodlari_BARQAROR_shaklda(bsl):
    """⚠️ `code` — mashina o'qiydigan BARQAROR belgi (`[A-Z][A-Z0-9_]*`). Erkin jumla kod
       bo'lib ishlatilsa, kod bo'yicha filtr yozadigan operator har gal boshqa matnni
       ko'rardi — sabab `detail` da yashaydi."""
    kodlar = _chaqiruv_literallari(bsl, "ДобавитьОшибку", 3)
    assert kodlar, "`ДобавитьОшибку` birorta literal kod bilan chaqirilmagan"
    buzuq = sorted({k for k in kodlar if not rb.ERROR_CODE_RE.fullmatch(k)})
    assert not buzuq, (f"`ДобавитьОшибку` shakldan chetdagi kod yozadi: {buzuq} — "
                       f"validator naqshi: {rb.ERROR_CODE_RE.pattern}")


def test_xato_qamrovi_va_KODI_har_chaqiruvda_LITERAL(bsl):
    """⚠️ NEGA LITERAL SHART: qamrov yoki kod O'ZGARUVCHIDAN kelsa, bu darvoza uni
       KO'RMAYDI va lug'at tekshiruvi jimgina bo'shab qoladi."""
    chaqiruvlar = _chaqiruvlar(bsl, "ДобавитьОшибку")
    assert chaqiruvlar, "`ДобавитьОшибку` birorta joydan chaqirilmagan"
    nolitral = [" ".join(arg.split())[:80] for arg in chaqiruvlar
                if _arg_literali(arg, 0) is None or _arg_literali(arg, 3) is None]
    assert not nolitral, (f"`ДобавитьОшибку` chaqiruvida qamrov yoki kod LITERAL emas — "
                          f"darvoza ularni tekshira olmaydi:\n  " + "\n  ".join(nolitral))


def test_rejim_nomlari_IKKI_TOMONDA_MOS(bsl):
    """BSL rejim nomlarini FUNKSIYA bo'lib beradi; ikkisi ham `runtime_bundle.MODES` da bo'lsin."""
    nomlar = set()
    for funksiya in ("РежимТолькоМетаданные", "РежимРазрешенныеЗонды"):
        tana = _tana(bsl, funksiya)
        mos = re.search(r'Возврат\s+"([^"]+)"', tana)
        assert mos, f"`{funksiya}` matn literali qaytarmaydi"
        nomlar.add(mos.group(1))
    assert nomlar == set(rb.MODES), (
        f"rejim nomlari ajralgan: BSL {sorted(nomlar)}, validator {sorted(rb.MODES)}")
    # ⚠️ DEFAULT ham bir xil: `ТекущийРежим` o'rnatilmagan rejimni `РежимТолькоМетаданные`
    #    ga tushiradi, Python tomoni esa `DEFAULT_MODE` ga.
    joriy = _tana(bsl, "ТекущийРежим")
    assert "РежимТолькоМетаданные()" in joriy, (
        "`ТекущийРежим` o'rnatilmagan rejimni METADATA_ONLY ga tushirmaydi — fail-safe buzilgan")
    assert re.search(r'Возврат\s+"METADATA_ONLY"', _tana(bsl, "РежимТолькоМетаданные"))
    assert rb.DEFAULT_MODE == "METADATA_ONLY", (
        f"validator tomonidagi default o'zgargan ({rb.DEFAULT_MODE!r}) — BSL "
        f"`ТекущийРежим` ham o'zgarishi SHART")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · MAJBURIY ARTEFAKT NOMLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def _bsl_yozadigan_fayllar(bsl_matni: str) -> set[str]:
    """BSL YOZADIGAN literal fayl nomlari (zond fayllari DINAMIK, shu bois bu yerda yo'q)."""
    fayllar = set(re.findall(r'ЗаписатьJSONФайл\([^,]+,\s*"([^"]+)"', bsl_matni))
    fayllar |= set(re.findall(r'ОтносительныйПуть\s*=\s*"([^"/]+)"',
                             _tana(bsl_matni, "ЗаписатьСводку")))
    return fayllar


def test_MAJBURIY_artefakt_nomlari_IKKI_TOMONDA_MOS(bsl):
    """BSL yozadigan MAJBURIY fayllar == `runtime_bundle.REQUIRED_FILES` (OLTOVI).

    ⚠️ `errors.json` HAM MAJBURIY: uning yozilishi hisobga olinmasa, xatolar ro'yxati
       umuman yozilmagan yurish «hech qanday xato bo'lmadi» bilan bir xil ko'rinardi."""
    yozilgan = _bsl_yozadigan_fayllar(bsl)
    yetishmaydi = sorted(set(rb.REQUIRED_FILES) - yozilgan)
    qoshimcha = sorted(yozilgan - set(rb.REQUIRED_FILES))
    assert not yetishmaydi and not qoshimcha, (
        f"paket tarkibi ZID.\n"
        f"  · shartnoma MAJBURIY deydi, BSL YOZMAYDI: {yetishmaydi}\n"
        f"  · BSL yozadi, shartnomada YO'Q: {qoshimcha}\n"
        f"  BSL yozadigan: {sorted(yozilgan)}\n"
        f"  shartnoma:     {list(rb.REQUIRED_FILES)}")


def test_ARTEFAKT_dalvosi_FAQAT_shartnomadagi_nomlarni_qamraydi(bsl):
    """`ОтметитьАртефакт("...")` literallari — validatorning `artifacts` oq ro'yxatidan."""
    nomlar = [n for n in _chaqiruv_literallari(bsl, "ОтметитьАртефакт", 0)]
    assert nomlar, "`ОтметитьАртефакт` birorta literal nom bilan chaqirilmagan"
    begona = sorted(set(nomlar) - set(rb.REQUIRED_FILES))
    assert not begona, (f"`ОтметитьАртефакт` shartnomada yo'q artefakt e'lon qiladi: {begona}. "
                        f"Ruxsat: {list(rb.REQUIRED_FILES)} va {list(rb.OPTIONAL_FILES)}")


def test_zond_fayl_nomi_VALIDATOR_naqshiga_MOS(bsl):
    """⚠️ `probes/NN_<tur>.json` nomi BSL da QO'SHISH bilan quriladi: `"probes/"` + ikki
       raqam + `"_"` + tur + `".json"`. Naqsh ikki tomonda ajralsa, har zond fayli rad
       etilardi — shu bois namunali nom validator naqshi bilan sinaladi."""
    tana = _tana(bsl, "ВыполнитьРазрешенныеЗонды")
    assert '"probes/"' in tana, "zond fayli `probes/` papkasiga yozilmaydi"
    assert '"_"' in tana and '".json"' in tana, "zond fayl nomining shakli o'zgargan"
    assert rb.PROBE_NAME_RE.fullmatch("probes/01_row_count.json"), (
        "validator naqshi BSL quradigan nomni qabul qilmaydi")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · `overall` TA'RIFI — IKKI TOMON AYNAN BIR XIL JAVOB BERADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_BSL_umumiy_holat_MANTIQI_kutilgan_UCH_shoxdan_iborat(bsl):
    """⚠️ STATIK O'QISH: pastdagi jadval BSL mantiqini MODELLASHTIRADI, shu bois model
       qaysi matndan o'qilgani QULFLANADI. BSL shoxlari o'zgarsa bu test yiqiladi va
       model ham qayta yozilishi kerak bo'ladi — aks holda jadval eskirib, mavjud bo'lmagan
       tenglikni «isbotlab» turardi."""
    tana = _tana(bsl, "ОбщееСостояние")
    qaytishlar = re.findall(r'Возврат\s+"([A-Z]+)"', tana)
    assert qaytishlar == ["FAILED", "PARTIAL", "SUCCESS"], (
        f"`ОбщееСостояние` shoxlari o'zgargan: {qaytishlar} — model qayta yozilishi kerak")
    assert set(qaytishlar) == set(rb.OVERALLS), (
        f"umumiy holat lug'ati ajralgan: BSL {sorted(set(qaytishlar))}, "
        f"validator {sorted(rb.OVERALLS)}")
    assert re.search(r"Если\s+Не\s+ОбязательныеЗаписаны\s+Тогда", tana), (
        "`ОбщееСостояние` `FAILED` ni YOZISH yiqilishiga bog'lamaydi")
    assert re.search(r"ЕстьНеудача\(СобратьРазделыЗапуска\(\)\)\s+Или\s+"
                     r"ЕстьНечитаемоеСемейство\(\)", tana), (
        "`PARTIAL` sharti o'zgargan: u `failed` bo'lim YOKI `unreadable` oila bo'lishi kerak")
    # ⚠️ Solishtiriladigan MAYDON va QIYMAT ham qulflanadi: `ЕстьНеудача` bo'lim holatiga,
    #    `ЕстьНечитаемоеСемейство` esa FAQAT `unreadable` ga qaraydi (`absent` ga EMAS).
    assert re.search(r'Раздел\.status\s*=\s*"failed"', _tana(bsl, "ЕстьНеудача"))
    nechitaemoe = _tana(bsl, "ЕстьНечитаемоеСемейство")
    assert re.search(r'Семейство\.state\s*=\s*"unreadable"', nechitaemoe)
    assert '"absent"' not in nechitaemoe, (
        "`ЕстьНечитаемоеСемейство` `absent` ni ham sanaydi — `absent` TO'LIQ javob va u "
        "yurishni BUZMAYDI")


def test_BSL_majburiy_yozildi_bayrogi_TORT_YOZISHNI_qamraydi(bsl):
    """⚠️ `ОбязательныеЗаписаны` — TO'RT yozishning KONYUNKSIYASI (`export.json`,
       `metadata.json`, `run_summary.md`, `errors.json`), qolgan IKKI artefakt
       (`run_status.json`, `manifest.json`) `СобратьСостояниеЗапуска` da ATAYLAB e'lon
       qilinadi (ular undan KEYIN yoziladi). Ikkisi birga OLTOVI — Python tomonidagi
       `REQUIRED_FILES` bilan AYNI.
    ⚠️ `ОшибкиЗаписаны` shu konyunksiyada BO'LISHI SHART: ilgari u yo'q edi va bu YOLG'ON
       `SUCCESS` yo'li bo'lgan."""
    tana = _tana(bsl, "ВыполнитьРазведку")
    mos = re.search(r"СобратьСостояниеЗапуска\(\s*[A-Яа-яЁё\w]+\s*,\s*(.*?)\)\s*;",
                    tana, re.S)
    assert mos, "`СобратьСостояниеЗапуска` `ВыполнитьРазведку` dan chaqirilmagan"
    bayroqlar = [b.strip() for b in mos.group(1).split(" И ")]
    assert "ОшибкиЗаписаны" in bayroqlar, (
        f"`errors.json` yozilishi `ОбязательныеЗаписаны` ga KIRMAYDI — bu YOLG'ON SUCCESS "
        f"yo'li: kelgan bayroqlar {bayroqlar}")
    ozi_elon = set(_chaqiruv_literallari(_tana(bsl, "СобратьСостояниеЗапуска"),
                                        "ОтметитьАртефакт", 0))
    assert ozi_elon == {rb.RUN_STATUS_FILE, rb.MANIFEST_FILE}, (
        f"`СобратьСостояниеЗапуска` o'zi e'lon qiladigan artefaktlar o'zgargan: "
        f"{sorted(ozi_elon)} — kutilgani {sorted({rb.RUN_STATUS_FILE, rb.MANIFEST_FILE})}")
    assert len(bayroqlar) + len(ozi_elon) == len(rb.REQUIRED_FILES), (
        f"majburiy artefaktlar sanog'i ZID: BSL {len(bayroqlar)} yozish bayrog'i + "
        f"{len(ozi_elon)} e'lon = {len(bayroqlar) + len(ozi_elon)}, shartnomada "
        f"{len(rb.REQUIRED_FILES)} ({list(rb.REQUIRED_FILES)})")


def _bsl_overall(*, majburiy_yozilgan: bool, sections, families) -> str:
    """BSL `ОбщееСостояние` mantiqining MODELI — statik o'qilgan matndan ko'chirilgan.

    ⚠️ Bu Python tomonining nusxasi EMAS: u `artifacts` ro'yxatiga qaramaydi, chunki BSL
       ham qaramaydi — BSL o'rniga chaqiruvchi hisoblagan `ОбязательныеЗаписаны` bayrog'ini
       oladi. Ikki tomonning KIRISHI boshqacha, JAVOBI esa AYNAN bir xil bo'lishi SHART."""
    if not majburiy_yozilgan:
        return "FAILED"
    if any(s["status"] == "failed" for s in sections) \
            or any(f["state"] == "unreadable" for f in families):
        return "PARTIAL"
    return "SUCCESS"


def _bolim(nom: str, holat: str) -> dict:
    return {"name": nom, "status": holat,
            "error": None if holat == "ok" else f"{nom}: {holat}"}


def _oila(nom: str, holat: str) -> dict:
    return {"name": nom, "state": holat,
            "detail": "sabab" if holat == "unreadable" else None}


#: `overall` ning SANOQLI holatlari: (nom, bo'limlar, oilalar, majburiy_yozilgan, kutilgan).
#: ⚠️ Har qatorda IKKI TOMON ham chaqiriladi va javoblari bir-biriga VA kutilganga
#:    solishtiriladi. Bitta tomonni kutilgan bilan solishtirish YETARLI EMAS: nuqson aynan
#:    ikki tomonning bir-biridan AJRALIB ketishi edi.
_OVERALL_JADVALI: tuple[tuple, ...] = (
    ("hammasi_ok",
     [_bolim("write_export", "ok"), _bolim("write_metadata", "ok")],
     [_oila("catalogs", "present")], True, rb.OVERALL_SUCCESS),
    ("probes_skipped",
     [_bolim("write_export", "ok"), _bolim("probes", "skipped")],
     [_oila("catalogs", "present")], True, rb.OVERALL_SUCCESS),
    ("oila_absent",
     [_bolim("write_export", "ok")],
     [_oila("chart_of_accounts", "absent")], True, rb.OVERALL_SUCCESS),
    ("oila_absent_va_probes_skipped",
     [_bolim("write_export", "ok"), _bolim("probes", "skipped")],
     [_oila("catalogs", "present"), _oila("chart_of_accounts", "absent")],
     True, rb.OVERALL_SUCCESS),
    ("oila_unreadable_va_bolim_failed",
     [_bolim("write_export", "ok"), _bolim("catalogs", "failed")],
     [_oila("catalogs", "unreadable")], True, rb.OVERALL_PARTIAL),
    ("faqat_oila_unreadable",
     [_bolim("write_export", "ok")],
     [_oila("catalogs", "unreadable")], True, rb.OVERALL_PARTIAL),
    ("faqat_bolim_failed",
     [_bolim("write_export", "ok"), _bolim("counts", "failed")],
     [_oila("catalogs", "present")], True, rb.OVERALL_PARTIAL),
    ("yozish_yiqildi",
     [_bolim("write_export", "ok")],
     [_oila("catalogs", "present")], False, rb.OVERALL_FAILED),
    ("yozish_yiqildi_va_bolim_failed",
     [_bolim("write_errors", "failed")],
     [_oila("catalogs", "unreadable")], False, rb.OVERALL_FAILED),
)


@pytest.mark.parametrize("nom,sections,families,yozilgan,kutilgan", _OVERALL_JADVALI,
                         ids=[q[0] for q in _OVERALL_JADVALI])
def test_overall_TARIFI_IKKI_TOMONDA_AYNAN_BIR_XIL(nom, sections, families, yozilgan,
                                                   kutilgan):
    """⚠️ ASOSIY DARVOZA: `skipped` bo'lim va `absent` oila `SUCCESS` ni BUZMAYDI; yozish
       yiqilsa `FAILED`; `failed` bo'lim yoki `unreadable` oila esa `PARTIAL`.
       Ilgari validator `SUCCESS` uchun HAMMA bo'lim `ok` bo'lishini talab qilardi, BSL esa
       `METADATA_ONLY` da `probes` bo'limini HAR DOIM `skipped` yozardi — ya'ni HAR BIR
       halol default yurishda ikki tomon ZID javob berardi."""
    artefaktlar = list(rb.REQUIRED_FILES) if yozilgan else list(rb.REQUIRED_FILES[1:])
    python_javobi = rb.derive_overall(sections, families=families, artifacts=artefaktlar)
    bsl_javobi = _bsl_overall(majburiy_yozilgan=yozilgan, sections=sections,
                              families=families)
    assert bsl_javobi == python_javobi, (
        f"«{nom}» holatida IKKI TOMON ZID: BSL `ОбщееСостояние` -> {bsl_javobi}, "
        f"Python `derive_overall` -> {python_javobi}")
    assert python_javobi == kutilgan, (
        f"«{nom}» holatida kutilgan {kutilgan}, kelgani {python_javobi}")


@pytest.mark.parametrize("yoq", rb.REQUIRED_FILES)
def test_har_MAJBURIY_artefaktning_yoqligi_FAILED_beradi(yoq):
    """⚠️ OLTOVI TENG MAJBURIY, `errors.json` HAM. Uning yozilishi hisobga olinmasa,
       YOLG'ON `SUCCESS` chiqardi: xatolar ro'yxati yozilmagan yurish «hech qanday xato
       bo'lmadi» bilan bir xil ko'rinardi."""
    sections = [_bolim("write_export", "ok")]
    families = [_oila("catalogs", "present")]
    artefaktlar = [n for n in rb.REQUIRED_FILES if n != yoq]
    python_javobi = rb.derive_overall(sections, families=families, artifacts=artefaktlar)
    assert python_javobi == rb.OVERALL_FAILED, (
        f"{yoq!r} yozilmaganda {rb.OVERALL_FAILED} kutilgan, kelgani {python_javobi}")
    assert _bsl_overall(majburiy_yozilgan=False, sections=sections,
                        families=families) == python_javobi, (
        f"{yoq!r} uchun ikki tomon javobi ZID")


def test_overall_jadvali_UCH_holatni_HAM_qamraydi():
    """⚠️ Jadval bir shoxni tekshirmay qolsa, darvoza jimgina yarim bo'lardi."""
    qamralgan = {q[4] for q in _OVERALL_JADVALI}
    tushgan = sorted(set(rb.OVERALLS) - qamralgan)
    assert not tushgan, f"`overall` jadvalida bu holat(lar) yo'q: {tushgan}"


def test_overall_jadvali_HAR_juftlikda_ikki_tomonni_SOLISHTIRADI():
    """⚠️ Jadvaldagi har holat uchun IKKI TOMON chaqirilishi kerak — bu testning O'ZI
       shuni qulflaydi: `_bsl_overall` va `rb.derive_overall` bir xil kirishda bir xil
       javob berishi HAMMA sanoqli kombinatsiyada tekshiriladi."""
    holatlar = list(SECTION_STATUSES)
    oilalar = list(rb.FAMILY_STATES)
    for bolim_holati, oila_holati, yozilgan in itertools.product(holatlar, oilalar,
                                                                (True, False)):
        sections = [_bolim("write_export", "ok"), _bolim("sinov", bolim_holati)]
        families = [_oila("catalogs", oila_holati)]
        artefaktlar = list(rb.REQUIRED_FILES) if yozilgan else list(rb.REQUIRED_FILES[1:])
        py = rb.derive_overall(sections, families=families, artifacts=artefaktlar)
        bsl_javobi = _bsl_overall(majburiy_yozilgan=yozilgan, sections=sections,
                                  families=families)
        assert py == bsl_javobi, (
            f"bo'lim={bolim_holati}, oila={oila_holati}, yozilgan={yozilgan}: "
            f"BSL -> {bsl_javobi}, Python -> {py}")
