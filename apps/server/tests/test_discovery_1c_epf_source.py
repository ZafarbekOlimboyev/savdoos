# -*- coding: utf-8 -*-
"""Ekstraktor MANBASINING darvozasi — 1C runtime'isiz bajariladigan yagona haqiqiy tekshiruv.

⚠️ NIMANI ISBOTLAYDI: yuborilayotgan `.bsl` manbasida birorta yozuv/o'tkazish/o'chirish/tarozi
   chaqiruvi YO'Q, va u o'zini runtime'da sinalmagan deb ochiq belgilaydi.
⚠️ NIMANI ISBOTLAMAYDI: modul kompilyatsiya bo'lishini yoki 1C'da ishlashini. Bu yerda 1C
   platformasi YO'Q. Kompilyatsiya — mijozning 1C mutaxassisi zimmasida.

Testning yarmi AUDITNI SINAYDI: har bir qoida uchun buzuvchi satr kiritiladi va qoida uni
tutishi tekshiriladi. Ushlamaydigan audit — yolg'on xotirjamlik.
"""
from __future__ import annotations

import pathlib

import pytest

from app.services.discovery_1c.epf_audit import (FORBIDDEN_MARKERS, REQUIRED_MARKERS, RULES,
                                                 audit_file, audit_source)

EPF_SRC = (pathlib.Path(__file__).resolve().parents[3]
           / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl")


def test_manba_fayli_REPODA_mavjud():
    assert EPF_SRC.is_file(), f"ekstraktor manbasi topilmadi: {EPF_SRC}"


def test_yuborilayotgan_manba_AUDITDAN_otadi():
    findings = audit_file(EPF_SRC)
    assert not findings, "manbada taqiqlangan chaqiruv bor:\n" + "\n".join(
        f"  {f.code} satr {f.line_no}: {f.line}  ({f.why})" for f in findings)


def test_manba_ozini_SINALMAGAN_deb_belgilaydi():
    text = EPF_SRC.read_text(encoding="utf-8")
    for marker, _why in REQUIRED_MARKERS:
        assert marker in text, marker


def test_manba_DARAJANI_UMUMAN_bermaydi():
    """Yig'uvchi ishonch darajasini o'zi bera olmaydi.

    Ilgari u `CANDIDATE` ni o'zi yozardi, keyin faqat DALIL yozardi. Universal kraulyerda u
    nomzod haqida UMUMAN gapirmaydi: `candidates` bo'sh, daraja ham dalil ham BinOS tomonida
    hisoblanadi. Shu bois bu test ilgari `Доказательства` (dalil yozilishi) ni talab qilardi,
    endi esa TALAB QILMAYDI — kafolat kuchaydi, sust bo'lmadi: yig'uvchi nomzod haqida hech
    narsa yozmasa, o'zini o'zi tasdiqlashi ham mumkin emas."""
    text = EPF_SRC.read_text(encoding="utf-8")
    for marker, why in FORBIDDEN_MARKERS:
        assert marker not in text, f"{marker}: {why}"
    assert "binos-1c-export-v1" in text          # AYNAN eksport shartnomasini chiqaradi


def test_manba_IKKI_hujjat_yozadi():
    """Universal kraulyer `export.json` dan tashqari `metadata.json` ni ham yozadi.

    Inventarizatsiya bo'lmasa yig'uvchi yana faqat nishonlar bo'yicha ishlagan bo'lardi, ya'ni
    konfiguratsiyada UMUMAN nima borligi hech qachon ko'rinmasdi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "binos-1c-metadata-v1" in text, "inventarizatsiya shartnomasi manbada yo'q"
    assert "metadata.json" in text, "ikkinchi fayl nomi manbada yo'q"
    assert "export.json" in text
    # Ikkinchi hujjatning YOZILISHI `export.json` jurnalida qayd etiladi — aks holda yozish
    # yiqilsa, xato bilan birga yo'qolardi.
    assert "write_metadata" in text


def test_manbada_QATTIQ_YOZILGAN_konfiguratsiya_nomi_YOQ():
    """⚠️ ENG MUHIM UNIVERSALLIK TESTI.

    Ilgari yig'uvchi kutilgan katalog va registr NOMLARINI o'zida saqlardi, ya'ni u bitta
    konfiguratsiya oilasiga moslangan edi: boshqa konfiguratsiyada jimgina «hech narsa
    topilmadi» deb qaytarardi va bu YOLG'ON xotirjamlik bo'lardi.

    Nomzod aniqlash endi BinOS tomonidagi analitik qatlamda bajariladi, shu bois yig'uvchi
    manbasida amaliy konfiguratsiya nomi BO'LMASLIGI kerak. PLATFORMA nomlari (`Справочники`,
    `РегистрыСведений`, `Измерения` …) ruxsat etiladi — ular har qanday konfiguratsiyada bir
    xil, ya'ni universal bilim."""
    text = EPF_SRC.read_text(encoding="utf-8")
    qattiq_nomlar = ("Номенклатура", "Штрихкоды", "ТоварыНаСкладах", "ВидыЦен", "Склады")
    topilgan = sorted(n for n in qattiq_nomlar if n in text)
    assert not topilgan, (
        f"yig'uvchi manbasida qattiq yozilgan konfiguratsiya nom(lar)i: {topilgan}. "
        "Nomzod aniqlash BinOS tomonida bajariladi — yig'uvchi nom bilmaydi.")


def test_zond_katalogining_HAMMA_turi_manbada_bor():
    """1C tomoni `binos-1c-probe-v1` katalogidagi AYNAN shu turlarni bilishi kerak.

    Katalogda bor, lekin yig'uvchida yo'q tur — model tanlay oladigan, lekin bajarilmaydigan
    zond, ya'ni jimgina bo'sh javob. Teskarisi (yig'uvchida bor, katalogda yo'q) esa katalog
    darvozasini aylanib o'tish bo'lardi."""
    from app.services.discovery_1c.probe import PROBE_CATALOG
    text = EPF_SRC.read_text(encoding="utf-8")
    yoq = sorted(t for t in PROBE_CATALOG if f'"{t}"' not in text)
    assert not yoq, f"zond turi yig'uvchida qaralmagan: {yoq}"
    # ⚠️ AI dan kelgan MATN kod sifatida bajarilmaydi: `ВыполнитьЗонд` faqat katalog kalitini
    #    Если/ИначеЕсли bilan taniydi, dinamik bajarish YO'Q (DYNAMIC_EXEC/EVAL qoidalari).
    assert "ВыполнитьЗонд" in text


# ── AUDITNING O'ZI ISHLAYAPTIMI (salbiy nazorat) ──────────────────────────────────────────
BUZUVCHI_SATRLAR = {
    "WRITE_OBJECT": "	ОбъектСсылка.Записать();",
    "WRITE_RECORDSET": "	НаборЗаписей.ЗаписатьНаборЗаписей(Истина);",
    "POST_DOCUMENT": "	Документ.Провести(РежимПроведения.Оперативный);",
    "UNPOST_DOCUMENT": "	Документ.ОтменитьПроведение();",
    "DELETE": "	Элемент.Удалить();",
    "DELETE_DIRECTLY": "	УдалитьОбъекты(Массив);",
    "EXCLUSIVE_MODE": "	УстановитьМонопольныйРежим(Истина);",
    "PRIVILEGED_MODE": "	УстановитьПривилегированныйРежим(Истина);",
    "TXN_BEGIN": "	НачатьТранзакцию();",
    "TXN_COMMIT": "	ЗафиксироватьТранзакцию();",
    "TXN_ROLLBACK": "	ОтменитьТранзакцию();",
    "FILL_PROCESSING": "	ВыполнитьОбработкуЗаполнения(Основание);",
    "DYNAMIC_EXEC": '	Выполнить("Объект.Записать()");',
    "DYNAMIC_EVAL": '	Знач = Вычислить("1+1");',
    "SCALE_EXCHANGE": "	ОбменСВесами(Товары);",
    "EXTERNAL_CONNECTION": '	Конн = Новый COMОбъект("V83.ComConnector");',
    # ── Universal kraulyer bilan qo'shilgan qoidalar ───────────────────────────────────────
    "COM_OBJECT_GET": '	Объект = ПолучитьCOMОбъект("C:\\otchet.xls");',
    "RUN_APPLICATION": '	ЗапуститьПриложение("cmd /c dir");',
    "COPY_FILE": "	КопироватьФайл(Источник, Приемник);",
    "MOVE_FILE": "	ПереместитьФайл(Источник, Приемник);",
    "DELETE_FILES": "	УдалитьФайлы(КаталогВыгрузки);",
    "CREATE_DIRECTORY": "	СоздатьКаталог(КаталогВыгрузки);",
    "FOREIGN_WRITER_OBJECT": "	Поток = Новый ЗаписьТекста(ИмяФайла);",
    "VALUE_TO_FILE": "	ЗначениеВФайл(ИмяФайла, Данные);",
    "SAFE_MODE_EVAL": '	Значение = ВычислитьВБезопасномРежиме("1+1");',
    "EXTERNAL_PROCESSING_LOAD": "	Обработка = ВнешниеОбработки.Создать(Путь);",
    "QUERY_TEXT_FROM_VARIABLE": "	Запрос.Текст = ТекстОтМодели;",
    "QUERY_TEXT_CONCAT_SOURCE": '	Запрос.Текст = "ВЫБРАТЬ * ИЗ " + ТекстОтМодели;',
    "CONSTANT_SET": "	Константы.РежимРаботы.Установить(Истина);",
    "SETTINGS_STORAGE_SAVE": '	ХранилищеОбщихНастроек.Сохранить("binos", "flag", Истина);',
    "EXCHANGE_PLAN_REGISTER": "	ПланыОбмена.БинОС.ЗарегистрироватьИзменения(Узел, Объект);",
}


@pytest.mark.parametrize("code", [r.code for r in RULES])
def test_HAR_qoida_buzuvchi_satrni_TUTADI(code):
    """Salbiy nazorat: qoida hech narsa tutmasa, u darvoza emas — bezak."""
    assert code in BUZUVCHI_SATRLAR, f"{code} uchun buzuvchi namuna yozilmagan"
    ok_src = EPF_SRC.read_text(encoding="utf-8")
    buzuq = ok_src + "\n" + BUZUVCHI_SATRLAR[code] + "\n"
    kodlar = {f.code for f in audit_source(buzuq)}
    assert code in kodlar, f"{code} qoidasi buzuvchi satrni TUTMADI: {BUZUVCHI_SATRLAR[code]!r}"


def test_QONUNIY_chaqiruvlar_YOLGON_signal_bermaydi():
    """Eng nozik joy: `ЗаписатьJSON(` va `Запрос.Выполнить()` QONUNIY va SHART.

    Audit ularni tutsa, yig'uvchini umuman yozib bo'lmasdi — ya'ni darvoza foydasiz bo'lardi."""
    qonuniy = "\n".join([
        '	ЗаписатьJSON(ПотокJSON, Результат);',
        '	ЗаписатьРезультат(Каталог, Результат);',
        '	Процедура ЗаписатьРезультат(Каталог, Результат)',
        '	Выборка = Запрос.Выполнить().Выбрать();',
        '	Результат = Запрос.Выполнить();',
        '	Функция ВыполнитьРазведку(Каталог)',
        '	Функция ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект)',
        '	ПотокJSON = Новый ЗаписьJSON;',
        '	ПотокJSON.ОткрытьФайл(Каталог + "/metadata.json", "UTF-8", Ложь, ПараметрыJSON);',
        '	ПотокJSON.Закрыть();',
        # ⚠️ ENG NOZIK SATR: so'rov matni LITERAL bilan boshlanadi va metadata nomi qo'shiladi.
        #    Bu QONUNIY va SHART; QUERY_TEXT_FROM_VARIABLE qoidasi buni tutsa, sanoqlarni
        #    umuman olib bo'lmasdi.
        '	Запрос.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмя;',
        '	Запрос.Текст	=	"ВЫБРАТЬ 1";',
    ])
    findings = audit_source(
        qonuniy + "\nRUNTIME'DA SINALMAGAN FAQAT AJRATILGAN NUSXADA "
                  "binos-1c-export-v1 binos-1c-metadata-v1")
    assert not findings, [f"{f.code}: {f.line}" for f in findings]


def test_audit_IZOHDAGI_chaqiruvni_ham_tutadi():
    """Izohga yashirilgan yozuv chaqiruvi ham tutiladi — keyin uni izohdan chiqarish bir qadam."""
    src = EPF_SRC.read_text(encoding="utf-8") + "\n	// Объект.Записать();\n"
    assert any(f.code == "WRITE_OBJECT" for f in audit_source(src))


# ── QOIDA TESHIKLARI (har biri: BUZUQ tutiladi + QONUNIY tutilmaydi) ──────────────────────
#: Audit `REQUIRED_MARKERS` ni ham tekshiradi, shu bois alohida satrni sinaganda belgilar
#: qo'shib qo'yiladi — aks holda har chaqiruv `MISSING_MARKER` bilan ko'milib ketardi.
_BELGILAR = ("RUNTIME'DA SINALMAGAN FAQAT AJRATILGAN NUSXADA "
             "binos-1c-export-v1 binos-1c-metadata-v1")


def _kodlar(*satrlar: str) -> set[str]:
    """Berilgan satrlarni auditdan o'tkazib, topilma KODLARINI qaytaradi."""
    return {f.code for f in audit_source("\n".join(satrlar) + "\n" + _BELGILAR)}


# ── NUQSON 1: `TEXT_FILE_WRITE` faqat `ЗаписьТекста` ni tutardi ────────────────────────────
# ⚠️ Qoidaning O'Z izohi «eksport FAQAT `ЗаписьJSON` bilan yoziladi, boshqa YOZUVCHI OBYEKT
#    nazoratdan chiqqan chiqish yo'li bo'lardi» deydi. Lekin boshqa yozuvchi obyektlar —
#    `ЗаписьДанных`, `ЗаписьXML`, `ЗаписатьXML`, `ЗаписьZipФайла` — qamralmagan edi, ya'ni
#    qoida e'lon qilgan kafolatini BAJARMAYDI: ikkinchi fayl kanalini ochib olish mumkin edi.
BOSHQA_YOZUVCHILAR = {
    "ЗаписьДанных": "\tПоток = Новый ЗаписьДанных(ИмяФайла);",
    "ЗаписьXML": "\tПоток = Новый ЗаписьXML;",
    "ЗаписатьXML": "\tЗаписатьXML(Поток, Данные);",
    "ЗаписьZipФайла": "\tАрхив = Новый ЗаписьZipФайла(ИмяФайла);",
    "ЗаписьHTML": "\tПоток = Новый ЗаписьHTML;",
    "ЗаписьFastInfoset": "\tПоток = Новый ЗаписьFastInfoset;",
}


@pytest.mark.parametrize("nom", sorted(BOSHQA_YOZUVCHILAR))
def test_BOSHQA_yozuvchi_obyekt_TUTILADI(nom):
    """Har qanday yozuvchi obyekt tutilishi shart, faqat `ЗаписьТекста` emas."""
    assert "FOREIGN_WRITER_OBJECT" in _kodlar(BOSHQA_YOZUVCHILAR[nom]), (
        f"{nom} tutilmadi — ikkinchi fayl yozish kanali auditdan o'tib ketadi")


def test_JSON_yozuvchisi_YOLGON_signal_bermaydi():
    """⚠️ `ЗаписьJSON`/`ЗаписатьJSON` QONUNIY: eksport AYNAN shu bilan yoziladi.

    Kengaytirilgan qoida ularni tutsa, yig'uvchini umuman yozib bo'lmasdi."""
    qonuniy = (
        '\tПараметрыJSON = Новый ПараметрыЗаписиJSON(ПереносСтрокJSON.Авто, "  ");',
        "\tПотокJSON = Новый ЗаписьJSON;",
        "\tЗаписатьJSON(ПотокJSON, Результат);",
        "\tПотокJSON.Закрыть();",
    )
    assert _kodlar(*qonuniy) == set(), "JSON yozuvchisi YOLG'ON ijobiy berdi"


# ── NUQSON 2a: konkatenatsiya bilan yasalgan so'rov O'TIB KETARDI ─────────────────────────
def test_MODELDAN_kelgan_satr_LITERALGA_QOSHILSA_ham_tutiladi():
    """⚠️ Teshik: `= "ВЫБРАТЬ * ИЗ " + ТекстОтМодели;` — jadval nomi TO'LIQ dinamik.

    Eski regex `=` dan keyingi BIRINCHI belgini tekshirardi, shu bois literal bilan
    boshlanib keyin o'zgaruvchi QO'SHILGAN so'rov auditdan o'tib ketardi."""
    kodlar = _kodlar('\tЗапрос.Текст = "ВЫБРАТЬ * ИЗ " + ТекстОтМодели;')
    assert "QUERY_TEXT_CONCAT_SOURCE" in kodlar, (
        "literalga qo'shilgan NOMA'LUM o'zgaruvchi tutilmadi")


def test_BOSH_literal_bilan_boshlangan_sorov_tutiladi():
    """⚠️ `= "" + ТекстОтМодели;` — bo'sh literal literal EMAS: so'rov butunlay dinamik."""
    kodlar = _kodlar('\tЗапрос.Текст = "" + ТекстОтМодели;')
    assert "QUERY_TEXT_FROM_VARIABLE" in kodlar, "bo'sh literal prefiksi tutilmadi"


def test_METADATA_nomini_QOSHISH_yolgon_signal_bermaydi():
    """Jadval nomini `ПолноеИмя()` dan qo'shish QONUNIY va SHART — sanoqlar shunday olinadi."""
    qonuniy = (
        '\tЗапрос.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмя;',
        '\tЗапрос.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмяОбъекта;',
    )
    assert _kodlar(*qonuniy) == set(), "metadata nomini qo'shish YOLG'ON ijobiy berdi"


# ── NUQSON 2b: ikki QONUNIY naqsh YOLG'ON tutilardi ───────────────────────────────────────
def test_KOP_SATRLI_tayinlash_yolgon_signal_bermaydi():
    """⚠️ `Запрос.Текст =` satr oxirida qolsa, matn esa keyingi satrda bo'lsa — bu QONUNIY.

    Eski regex bir SATRNI ko'rardi, shu bois uzun so'rovni ikki satrga bo'lish auditni
    qizil qilardi: qoida kodni to'g'ri yozganni jazolardi."""
    kodlar = _kodlar(
        "\tЗапрос.Текст =",
        '\t\t"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмя;',
    )
    assert kodlar == set(), f"ko'p satrli tayinlash YOLG'ON tutildi: {sorted(kodlar)}"


def test_TAQQOSLASH_yolgon_signal_bermaydi():
    """⚠️ 1C da `=` TAQQOSLASH ham bo'ladi: `Если Поле.Текст = ИмяПоля Тогда`.

    Bu tayinlash EMAS va so'rov ham emas, lekin eski regex uni tutardi."""
    kodlar = _kodlar(
        "\tЕсли Поле.Текст = ИмяПоля Тогда",
        "\tИначеЕсли Реквизит.Текст = ЭталонныйТекст Тогда",
    )
    assert kodlar == set(), f"taqqoslash YOLG'ON tutildi: {sorted(kodlar)}"


# ── NUQSON 3: YANGI ochilgan yuzadagi yozuv amallari ──────────────────────────────────────
YANGI_YUZA_BUZUQ = {
    "CONSTANT_SET": (
        "\tКонстанты.РежимРаботы.Установить(Истина);",
        "\tМенеджер = Константы.РежимРаботы.СоздатьМенеджерЗначения();",
    ),
    "SETTINGS_STORAGE_SAVE": (
        '\tХранилищеОбщихНастроек.Сохранить("binos", "flag", Истина);',
        '\tХранилищеСистемныхНастроек.Сохранить("binos", "flag", Истина);',
    ),
    "EXCHANGE_PLAN_REGISTER": (
        "\tПланыОбмена.БинОСОбмен.ЗарегистрироватьИзменения(Узел, Объект);",
        "\tПланыОбмена.БинОСОбмен.УдалитьРегистрациюИзменений(Узел, Объект);",
    ),
}


@pytest.mark.parametrize("code", sorted(YANGI_YUZA_BUZUQ))
def test_YANGI_yuzadagi_yozuv_amali_TUTILADI(code):
    """⚠️ Yig'uvchi aynan shu bosqichda `Константы` kolleksiyasini kezishni BOSHLADI —
    teshik YANGI ochilgan yuzada edi. Uchovi ham bazaga/sozlamaga YOZISH amali."""
    for satr in YANGI_YUZA_BUZUQ[code]:
        assert code in _kodlar(satr), f"{code} tutmadi: {satr!r}"


def test_YANGI_yuzadagi_OQISH_amallari_yolgon_signal_bermaydi():
    """O'qish amallari tutilmasligi shart — aks holda inventarizatsiyani yozib bo'lmasdi."""
    qonuniy = (
        "\tЗначение = Константы.РежимРаботы.Получить();",
        '\tСписок.Добавить(ОписаниеКоллекции("Константы", "Константа", "constant", "constants"));',
        "\tДля Каждого ОбъектМД Из Метаданные.Константы Цикл",
        '\tЗначение = ХранилищеОбщихНастроек.Загрузить("binos", "flag");',
        "\tДля Каждого ОбъектМД Из Метаданные.ПланыОбмена Цикл",
    )
    assert _kodlar(*qonuniy) == set(), "o'qish amali YOLG'ON ijobiy berdi"


# ── NUQSON 4 (BSL tomoni): `field_type_details` zondi O'LIK edi ───────────────────────────
# ⚠️ Shartnoma: `field_type_details` nishoni — MAYDON MANZILI (`<obyekt>.<maydon>` yoki
#    `<obyekt>.<bo'lim>.<maydon>`), QOLGAN hamma zond turining nishoni — OBYEKT (`<obyekt>`).
#    Ilgari yig'uvchi maydon yo'lini HAMMA tur uchun jimgina tashlab ketardi: `row_count`
#    ga maydon manzili kelsa, u BOSHQA nishonni — butun obyektni — o'lchab, natijani
#    xatosiz qaytarardi. Bu jimgina NOTO'G'RI javob.
# ⚠️ BU TEST NIMANI ISBOTLAYDI: MANBA MATNIDA darvoza borligini. Bu yerda 1C yo'q, shu bois
#    guardning BAJARILISHI isbotlanmaydi — faqat yozilgani.
def _zond_tanasi() -> str:
    """`ВыполнитьЗонд` funksiyasining tanasini manbadan ajratib beradi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    bosh = text.index("Функция ВыполнитьЗонд(")
    return text[bosh:text.index("КонецФункции", bosh)]


def test_zond_MAYDON_manzilini_faqat_field_type_details_uchun_QABUL_qiladi():
    """Boshqa tur uchun maydon yo'li kelsa — ANIQ XATO, jimgina boshqa nishon EMAS."""
    tana = _zond_tanasi()
    assert "ПутьПоля" in tana, "`ВыполнитьЗонд` maydon yo'lini umuman ko'rmaydi"
    assert 'ТипЗонда <> "field_type_details"' in tana, (
        "`ВыполнитьЗонд` maydon manzilini FAQAT `field_type_details` uchun qabul qilishi "
        "kerak; boshqa turga maydon yo'li kelsa jimgina OBYEKT o'lchanib ketadi")
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "field_type_details: maydon yo'li" in text, (
        "maydon yo'li YO'Q bo'lganda `field_type_details` aniq xato qaytarishi kerak")


def test_zond_maydon_manzilini_OBYEKT_va_YOL_ga_ajratadi():
    """Nishonni ajratish `НайтиЦелевойОбъект` da, so'rov jadvali esa METADATA obyektidan."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "Функция НайтиЦелевойОбъект(ЦелевойОбъект, ПутьПоля, Ошибки)" in text
    assert "Метаданные.НайтиПоПолномуИмени(ИмяОбъекта)" in text, (
        "obyekt METADATA dan izlanishi shart — kelgan matn so'rovga tushmasin")
    # Maydon topilmasa — ANIQ xato (jimgina bo'sh natija emas).
    assert "field_type_details: maydon topilmadi" in text


def test_zond_CHUQUR_maydon_yolini_JIMGINA_qisqartirmaydi():
    """⚠️ `<obyekt>.<b1>.<b2>.<maydon>` — shartnomada YO'Q shakl.

    Ilgari `ЗондДеталиТипаПоля` bunda `Части[0]` ni bo'lim, OXIRGISINI maydon deb olib,
    o'rtadagi bo'laklarni JIMGINA tashlab ketardi: natija BOSHQA maydonga tegishli bo'lardi va
    xato qaytmasdi. Shartnomadan chuqur yo'l FAIL-CLOSED bo'lishi kerak."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "field_type_details: maydon yo'li juda chuqur" in text, (
        "shartnomadan chuqur maydon yo'li rad etilmaydi — jimgina boshqa maydon o'lchanadi")


# ── README DA'VOLARI ↔ KOD (drift darvozasi) ──────────────────────────────────────────────
README = EPF_SRC.parent / "README.md"


def test_README_qoida_SONI_kod_bilan_mos():
    """README da'vo qilgan qoida soni haqiqiy songa teng bo'lishi shart.

    ⚠️ NEGA DARVOZA: «27 qoida» yozuvi qoida qo'shilganda jimgina eskirib qolardi va hujjat
    kafolatdan KO'PROQ yoki KAMROQ narsa da'vo qilardi."""
    matn = README.read_text(encoding="utf-8")
    assert f"**{len(RULES)} qoida**" in matn, (
        f"README da qoida soni eskirgan: haqiqiy son {len(RULES)}")


def test_README_ISHLASHNI_dav_qilmaydi():
    """⚠️ Ogohlantirish blokining O'ZIDA qobiliyat da'vosi bo'lmasligi shart.

    Ilgari eng yuqorida qalin harflar bilan «Yig'uvchi UNIVERSAL» yozilgan edi, holbuki
    isbotlangani FAQAT manba matnida konfiguratsiya nomi yo'qligi: modul kompilyatsiya
    QILINMAGAN va birorta 1C bazasida ISHLATILMAGAN. Bu ikki satr yuqoridagi «Ishlaydi degan
    da'vo yo'q» bilan ziddiyat hosil qilardi."""
    matn = README.read_text(encoding="utf-8")
    blok = matn[:matn.index("## Nima tekshirilgan")]
    assert "**Yig'uvchi UNIVERSAL:**" not in blok, "qobiliyat da'vosi qaytib keldi"
    assert "**Isbotlangani:**" in blok and "**Isbotlanmagani:**" in blok, (
        "ogohlantirish bloki isbotlangan va isbotlanmagan narsani ajratib ko'rsatishi shart")
    assert "har qanday konfiguratsiyada ISHLASHI" in blok, (
        "har qanday konfiguratsiyada ishlash SINALMAGANI ochiq yozilishi shart")


def test_README_zond_shabloni_QOLDA_literalga_yozishni_talab_qilmaydi():
    """⚠️ Operator shabloni INYEKSIYA yo'li edi: qiymat BSL satr literaliga QO'LDA kiritilardi.

    Matndagi bitta `"` literalni yopib, qolgan qismini KOD qilib qo'yardi. Shablon endi
    qiymatni o'zgaruvchiga oladi va qo'shtirnoqni tekshiradi."""
    matn = README.read_text(encoding="utf-8")
    assert 'ВыполнитьЗонд("register_shape"' not in matn, (
        "shablon yana qiymatni to'g'ridan-to'g'ri satr literaliga qo'yadi")
    assert "ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект)" in matn
    assert "СтрНайти" in matn, "shablon qo'shtirnoqni tekshirmaydi"
    assert "INYEKSIYA" in matn, "inyeksiya xavfi ochiq yozilishi shart"
