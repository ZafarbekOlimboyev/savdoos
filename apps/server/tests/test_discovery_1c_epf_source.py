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
    # ── Runtime paketi bilan qo'shilgan qoidalar ────────────────────────────────────────────
    "SET_DELETION_MARK": "	Объект.УстановитьПометкуУдаления(Истина);",
    "OBJECT_CREATE_FOR_WRITE": "	Новый = Документы.Поступление.СоздатьДокумент();",
    "EVENT_LOG_WRITE": '	ЗаписатьВЖурналРегистрации("БинОС", УровеньЖурналаРегистрации.Информация);',
    "DATA_EXCHANGE_LOAD": "	Объект.ОбменДанными.Загрузка = Истина;",
    "DATA_SYNC_RUN": "	ВыполнитьОбменДанными(Узел);",
    "EQUIPMENT_COMMAND": "	ВыполнитьКомандуОборудования(Устройство, Команда);",
    "NONSTANDARD_IDENT_CHAR": "	Результат = ЗондСанокҚаторлар(ПолноеИмяОбъекта, Ошибки);",
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
    findings = audit_source(qonuniy + "\n" + _BELGILAR)
    assert not findings, [f"{f.code}: {f.line}" for f in findings]


def test_audit_IZOHDAGI_chaqiruvni_ham_tutadi():
    """Izohga yashirilgan yozuv chaqiruvi ham tutiladi — keyin uni izohdan chiqarish bir qadam."""
    src = EPF_SRC.read_text(encoding="utf-8") + "\n	// Объект.Записать();\n"
    assert any(f.code == "WRITE_OBJECT" for f in audit_source(src))


# ── QOIDA TESHIKLARI (har biri: BUZUQ tutiladi + QONUNIY tutilmaydi) ──────────────────────
#: Audit `REQUIRED_MARKERS` ni ham tekshiradi, shu bois alohida satrni sinaganda belgilar
#: qo'shib qo'yiladi — aks holda har chaqiruv `MISSING_MARKER` bilan ko'milib ketardi.
#: ⚠️ RO'YXAT MODULDAN OLINADI, QO'LDA KO'CHIRILMAYDI: ilgari bu yerda belgilar qo'lda yozilgan
#: edi, ya'ni `REQUIRED_MARKERS` ga yangi belgi qo'shilsa BU FIXTURE eskirib, o'ntacha test
#: `MISSING_MARKER` bilan yiqilardi va sabab qoidaga emas, fixture'ga tegishli bo'lardi.
#: Bu KAFOLATNI SUSTLASHTIRMAYDI: belgilarning MANBADA borligini boshqa test
#: (`test_manba_ozini_SINALMAGAN_deb_belgilaydi`) HAQIQIY fayl ustida tekshiradi.
_BELGILAR = " ".join(marker for marker, _why in REQUIRED_MARKERS)


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


# ══ NUQSON 5: NOSTANDART IDENTIFIKATOR HARFI (kompilyatsiyani yiqitadi) ═══════════════════
# ⚠️ TOPILGAN HAQIQIY NUQSON: manbada `ЗондСанокҚаторлар` funksiyasi bor edi — nomdagi `Қ`
#    U+049A (CYRILLIC CAPITAL LETTER KA WITH DESCENDER), QOZOQ/O'ZBEK kirill harfi. Rus
#    alifbosida bunday harf YO'Q, 1C identifikatori esa rus kirilli, lotin, raqam va pastki
#    chiziqdan iborat. Ya'ni `row_count` zondi (11 zonddan biri) kompilyatsiyani yiqitishi
#    KUCHLI EHTIMOL edi — va bu audit tomonidan tutilmasdi.
def test_manbada_NOSTANDART_identifikator_harfi_YOQ():
    """Kod qismida rus kirill / lotin / raqam / `_` dan boshqa harf QOLMASLIGI shart.

    ⚠️ BU NIMANI ISBOTLAYDI: manba matnidagi BELGI TO'PLAMINI. Kompilyatsiyani ISBOTLAMAYDI —
    bu yerda 1C platformasi yo'q, sintaksis tekshiruvi 1C mutaxassisi zimmasida."""
    topilgan = [f for f in audit_file(EPF_SRC) if f.code == "NONSTANDARD_IDENT_CHAR"]
    assert not topilgan, "kod qismida nostandart harf bor:\n" + "\n".join(
        f"  satr {f.line_no}: {f.line}" for f in topilgan)


def test_NOSTANDART_harf_IZOHDA_va_LITERALDA_yolgon_signal_bermaydi():
    """⚠️ Izoh o'zbek kirillida bo'lishi QONUNIY, satr literalidagi matn ham kod emas.

    Ikkovini tutadigan qoida ishlatib bo'lmaydigan darajada shovqinli bo'lardi: bu loyihada
    izohlar o'zbekcha va xato matnlari ham o'zbekcha."""
    qonuniy = (
        "\t// Izoh: Қаторлар сони — o'zbek kirilli IZOHDA qonuniy",
        '\tОшибки.Добавить("Қаторлар сони o\'qilmadi");',
        "\tРезультат = ЗондКоличествоСтрок(ПолноеИмяОбъекта, Ошибки);",
    )
    kodlar = _kodlar(*qonuniy)
    assert "NONSTANDARD_IDENT_CHAR" not in kodlar, (
        f"izoh yoki satr literali YOLG'ON tutildi: {sorted(kodlar)}")


@pytest.mark.parametrize("satr", [
    "\tФункция ЗондСанокҚаторлар(ПолноеИмяОбъекта, Ошибки)",   # Қ — U+049A
    "\tЎзгарувчи = 1;",                                        # Ў — U+040E
    "\tҒалат = Истина;",                                       # Ғ — U+0492
    "\tПеременнаяĥ = 1;",                                 # ĥ — lotin emas, kengaytirilgan
])
def test_NOSTANDART_harf_KOD_qismida_TUTILADI(satr):
    """Har qanday alifbodagi begona harf tutilishi shart, faqat `Қ` emas."""
    assert "NONSTANDARD_IDENT_CHAR" in _kodlar(satr), f"tutilmadi: {satr!r}"


# ══ NUQSON 6: §4 MUTATSIYA TOKENLARI QAMROVI ══════════════════════════════════════════════
# ⚠️ Yig'uvchi endi ZOND bajaradi va BESH artefakt yozadi — kod yuzasi yana kengaydi. Quyidagi
#    mutatsiya oilalari eski 31 qoidaning BIRORTASI bilan ham tutilmasdi.
MUTATSIYA_BUZUQ = {
    "SET_DELETION_MARK": (
        "\tОбъект.УстановитьПометкуУдаления(Истина);",
        "\tОбъект.УдалитьПометкуУдаления();",
    ),
    "OBJECT_CREATE_FOR_WRITE": (
        "\tНовыйДок = Документы.Поступление.СоздатьДокумент();",
        "\tНовыйЭл = Справочники.Товары.СоздатьЭлемент();",
        "\tНовыйЭл = Справочники.Товары.СоздатьГруппу();",
        "\tНабор = РегистрыСведений.Цены.СоздатьНаборЗаписей();",
    ),
    "EVENT_LOG_WRITE": (
        '\tЗаписатьВЖурналРегистрации("БинОС.Разведка", УровеньЖурналаРегистрации.Информация);',
    ),
    "DATA_EXCHANGE_LOAD": (
        "\tОбъект.ОбменДанными.Загрузка = Истина;",
        "\tНабор.ОбменДанными . Загрузка = Истина;",
    ),
    "DATA_SYNC_RUN": (
        "\tВыполнитьОбменДанными(Узел);",
        "\tСинхронизироватьДанные(Настройка);",
    ),
    "EQUIPMENT_COMMAND": (
        "\tВыполнитьКомандуОборудования(Устройство, Команда);",
        "\tЗагрузитьТоварыВВесы(Устройство, Таблица);",
        "\tПодключаемоеОборудование.ПодключитьОборудование(Устройство);",
    ),
}


@pytest.mark.parametrize("code", sorted(MUTATSIYA_BUZUQ))
def test_KENGAYTIRILGAN_mutatsiya_tokeni_TUTILADI(code):
    for satr in MUTATSIYA_BUZUQ[code]:
        assert code in _kodlar(satr), f"{code} tutmadi: {satr!r}"


def test_KENGAYTIRILGAN_mutatsiya_qoidalari_OQISHNI_tutmaydi():
    """⚠️ Yaqin turgan O'QISH amallari tutilmasligi SHART — aks holda yig'uvchini yozib bo'lmasdi.

    Masalan `ПометкаУдаления` standart rekviziti inventarizatsiyada O'QILADI, `Метаданные.Документы`
    kezish esa butun kraulyerning asosi."""
    qonuniy = (
        "\tЗначение = ОбъектМД.ПометкаУдаления;",
        '\tДобавитьПолеОдин(Поля, "ПометкаУдаления", "Булево", ВидПоля, Синоним, Занятые, Ошибки);',
        "\tДля Каждого ОбъектМД Из Метаданные.Документы Цикл",
        "\tДля Каждого ОбъектМД Из Метаданные.ПланыОбмена Цикл",
        "\tКоллекция = ОбъектМД.ТабличныеЧасти;",
        "\tСведения = Новый СистемнаяИнформация;",
        "\tЕсли ОбменДанными = Неопределено Тогда",
    )
    assert _kodlar(*qonuniy) == set(), "o'qish amali YOLG'ON ijobiy berdi"


# ══ NUQSON 7: REJIM DARVOZASI MANBADA KO'RINMASDI (§5) ════════════════════════════════════
def test_DEFAULT_rejim_belgisi_YOQ_bolsa_audit_QIZIL():
    """⚠️ Belgi olib tashlansa audit qizil bo'lishi shart — aks holda da'vo qulflanmagan."""
    belgilar = [m for m, _ in REQUIRED_MARKERS if m != "DEFAULT REJIM: METADATA_ONLY"]
    kodlar = {f.code for f in audit_source("\n".join(belgilar))}
    assert "MISSING_MARKER" in kodlar, "default rejim belgisining yo'qligi tutilmadi"


def test_DEFAULT_rejim_belgisi_BOR_bolsa_audit_JIM():
    """Belgilar to'liq bo'lsa `MISSING_MARKER` chiqmasligi shart (yolg'on ijobiy yo'q)."""
    assert "MISSING_MARKER" not in _kodlar(), "belgilar to'liq, lekin MISSING_MARKER chiqdi"


def test_manba_DEFAULT_rejimni_METADATA_ONLY_deb_elon_qiladi():
    """§5: argument berilmasa yoki noma'lum rejim kelsa — `METADATA_ONLY` (fail-safe)."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "DEFAULT REJIM: METADATA_ONLY" in text
    assert "APPROVED_PROBES" in text, "ikkinchi rejim manbada e'lon qilinmagan"
    assert "Функция ВыполнитьРазведку(КаталогВыгрузки, Режим = Неопределено, " \
           "РазрешенныеЗонды = Неопределено) Экспорт" in text, (
        "`ВыполнитьРазведку` rejim va allowlist argumentlarini olmaydi")


def test_zond_MODUL_darajasidagi_REJIMNI_hurmat_qiladi():
    """⚠️ `ВыполнитьЗонд` to'g'ridan-to'g'ri chaqirilsa ham rejim darvozasidan o'tishi shart.

    Rejim o'rnatilmagan bo'lsa (`ВыполнитьРазведку` chaqirilmagan) — DEFAULT `METADATA_ONLY`,
    ya'ni zond RAD etiladi. Aks holda rejim shartnomasi faqat bitta kirish nuqtasini qo'riqlardi
    va ikkinchisi ochiq qolardi.
    ⚠️ BU FAQAT MANBA MATNINI isbotlaydi, guardning BAJARILISHINI emas."""
    tana = _zond_tanasi()
    assert "ЗондРазрешен(ТипЗонда, ЦелевойОбъект)" in tana, (
        "`ВыполнитьЗонд` rejim/allowlist darvozasini chaqirmaydi")
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "Функция ТекущийРежим()" in text, "rejimni o'qishning yagona joyi yo'q"
    assert "Функция ЗондРазрешен(ТипЗонда, ЦелевойОбъект)" in text


def test_ALLOWLIST_bosh_bolsa_birorta_zond_bajarilmaydi():
    """§5 fail-closed: `APPROVED_PROBES` + bo'sh allowlist = birorta zond YO'Q."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "allowlist bo'sh — fail-closed" in text, (
        "bo'sh allowlist uchun fail-closed yo'l manbada ko'rinmaydi")
    # Sabab MAJBURIY: sababsiz element RAD etiladi (uchlik shartnomasi).
    assert "Функция НормализоватьЗаявку(Элемент)" in text
    assert '"reason"' in text, "allowlist elementining SABABI shartnomada yo'q"


# ══ NUQSON 8: RUNTIME PAKETI ARTEFAKTLARI (§6, §7, §11) ═══════════════════════════════════
RUNTIME_ARTEFAKTLAR = ("run_status.json", "errors.json", "run_summary.md", "manifest.json")
RUNTIME_SHARTNOMALAR = ("binos-1c-run-v1", "binos-1c-errors-v1", "binos-1c-manifest-v1")


@pytest.mark.parametrize("nom", RUNTIME_ARTEFAKTLAR + RUNTIME_SHARTNOMALAR)
def test_RUNTIME_paketining_har_azosi_manbada_bor(nom):
    """Paket jadvalidagi har bir majburiy artefakt va shartnoma manbada nomlanishi shart."""
    assert nom in EPF_SRC.read_text(encoding="utf-8"), f"runtime paketida yo'q: {nom}"


def test_RUNTIME_paketi_TOPLAM_nomlarini_TAKRORLAMAYDI():
    """⚠️ `status.json` / `summary.md` — `binos-1c-discovery-v1` TO'PLAMINING a'zolari va ularni
    ADAPTER quradi. Bir xil nom ikki xil sxema operator uchun ham, kod uchun ham tuzoq bo'lardi,
    shu bois runtime paketi `run_status.json` / `run_summary.md` nomlarini oladi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    for adashtiruvchi in ('"status.json"', '"summary.md"', "/status.json", "/summary.md"):
        assert adashtiruvchi not in text, (
            f"yig'uvchi to'plam a'zosining nomini yozadi: {adashtiruvchi}")


def test_MANIFEST_provenans_DAVOSI_qilmaydi():
    """⚠️ Manifest faqat YOZILGAN BAYTLARNING sha256'si. Phase 2 qoidasi MANBA provenansi
    maydonlarini ATAYLAB taqiqlagan: ular metadata razvedkasidan kelib chiqmaydi.

    ⚠️ FAQAT KOD QISMI tekshiriladi: izohda bu nomlar NEGA yo'qligi tushuntirilgan, ya'ni
    butun faylni qidirish hujjatni yozgan odamni jazolardi."""
    from app.services.discovery_1c.epf_audit import kod_satrlari
    kod = "\n".join(satr for _no, satr in
                    kod_satrlari(EPF_SRC.read_text(encoding="utf-8").splitlines()))
    for taqiq in ("source_copy", "snapshot_at", "plan_sha256"):
        assert taqiq not in kod, f"manifest KODIDA provenans da'vosi: {taqiq}"
    text = EPF_SRC.read_text(encoding="utf-8")
    assert '"sha256"' in text and '"bytes"' in text, "manifest maydonlari yo'q"


def test_MANIFEST_eng_OXIRIDA_yoziladi():
    """⚠️ Manifest qolgan fayllarni xeshlaydi, shu bois u ENG OXIRGI yoziladigan artefakt.

    ⚠️ TARTIB `ВыполнитьРазведку` TANASIDA o'lchanadi, butun faylda EMAS: modul boshidagi
    hujjat jadvalida fayllar boshqa tartibda sanab o'tilgan va u bajarilish tartibi emas."""
    text = EPF_SRC.read_text(encoding="utf-8")
    bosh = text.index("Функция ВыполнитьРазведку(")
    tana = text[bosh:text.index("КонецФункции", bosh)]
    joylar = {nom: tana.index(f'"{nom}"') for nom in
              ("errors.json", "run_status.json", "manifest.json")}
    # `run_summary.md` nomi `ЗаписатьСводку` ichida; tanada CHAQIRUV turadi.
    joylar["run_summary.md"] = tana.index("ЗаписатьСводку(")
    assert joylar["manifest.json"] > joylar["run_status.json"], (
        "manifest `run_status.json` dan OLDIN yozilsa, uni xeshlay olmaydi")
    assert joylar["manifest.json"] > joylar["errors.json"]
    assert joylar["run_status.json"] > joylar["errors.json"], (
        "`run_status.json` `errors.json` dan keyin yozilishi kerak — u yozilgan faylga "
        "havola qiladi")
    assert joylar["run_summary.md"] < joylar["run_status.json"], (
        "`run_summary.md` `run_status.json` dan OLDIN yozilishi kerak, aks holda uning "
        "yozilishi `overall` ga kirmaydi")


def test_YOLGON_XESH_yozilmaydi():
    """⚠️ `ХешированиеДанных` bo'lmasa — `sha256` `Неопределено` va sabab `errors.json` da.

    Yo'qligini aytish soxta xeshdan YAXSHI: soxta xesh butun manifestni ma'nosiz qiladi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "ХешированиеДанных" in text and "ХешФункция.SHA256" in text
    assert "UNHASHABLE" in text, "xesh hisoblanmaganini belgilaydigan xato KODI yo'q"


def test_manbada_TESKARI_CHIZIQ_bilan_EKRANLANGAN_qoshtirnoq_YOQ():
    """⚠️ TOPILGAN NUQSON (shu bosqichda kiritilgan va tutilgan): BSL da teskari chiziq
    EKRANLASH BELGISI EMAS — satr literalidagi qo'shtirnoq faqat IKKILANTIRISH bilan yoziladi.

    `"... \\"sha256\\": ..."` yozilgan satr literalni AYNAN shu joyda YOPADI va qolgan qismini
    KOD qilib qo'yadi, ya'ni modul kompilyatsiya bo'lmaydi. Nuqson `run_status.json` ning
    izoh matnida edi va uni qo'shni agentning `runtime_audit` tekshiruvi ko'rsatdi.

    ⚠️ Bu MATNIY tekshiruv, kompilyator emas: u faqat shu naqshni tutadi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    yomon = [(i, s.strip()) for i, s in enumerate(text.splitlines(), 1) if '\\"' in s]
    assert not yomon, ("satr literalida teskari chiziq bilan ekranlangan qo'shtirnoq:\n"
                       + "\n".join(f"  satr {i}: {s[:110]}" for i, s in yomon))


def test_UNREADABLE_va_ABSENT_ALOHIDA_belgilanadi():
    """⚠️ «o'qiy olmadim» (`unreadable`) va «yo'q» (`absent`) IKKI XIL holat.

    `UNKNOWN` ni `NOT_FOUND` deb talqin qilish razvedkaning eng katta yolg'oni bo'lardi:
    o'qilmagan oila «bu konfiguratsiyada yo'q» bo'lib ko'rinardi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert '"unreadable"' in text, "`unreadable` belgisi yo'q"
    assert '"absent"' in text, "`absent` belgisi yo'q"


def test_UMUMIY_HOLAT_uch_qiymatdan_iborat():
    """§6: `SUCCESS` | `PARTIAL` | `FAILED`. `SUCCESS` FAQAT hamma majburiy artefakt yozilgan
    VA birorta bo'lim yiqilmagan holda beriladi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    for holat in ('"SUCCESS"', '"PARTIAL"', '"FAILED"'):
        assert holat in text, f"umumiy holat qiymati yo'q: {holat}"
    assert "Функция ОбщееСостояние(ОбязательныеЗаписаны)" in text, (
        "umumiy holat bitta joyda hisoblanmaydi")


def test_HAR_OBYEKT_ALOHIDA_Popytka_ichida():
    """⚠️ §6: bitta obyekt inspeksiyasi yiqilsa BUTUN yurish buzilmasin.

    Ilgari kolleksiya sikli BITTA `Попытка` ichida edi: bir obyekt xato bersa qolgan yuzlab
    obyekt JIMGINA tushib qolardi va bo'lim shunchaki `failed` bo'lardi."""
    text = EPF_SRC.read_text(encoding="utf-8")
    assert "OBJECT_FAILED" in text, "obyekt darajasidagi xato KODI yo'q"
    assert "Процедура ДобавитьОдинОбъектЭкспорта(" in text, (
        "eksport tomonidagi obyekt sikli hali ham bitta Попытка ichida")


def test_PLATFORMA_maydonlari_EXPORT_shartnomasini_BUZMAYDI():
    """⚠️ §11 yangi maydonlar `export.json` ning `platform` bo'limiga TUSHMASLIGI shart.

    `binos-1c-export-v1` ning `platform` kalitlari QAT'IY oq ro'yxatda va adapter noma'lum
    kalitni ham, tushib qolgan kalitni ham RAD etadi. Shu bois yangi maydonlar `run_status.json`
    ga tushdi (`binos-1c-run-v1` — YANGI shartnoma, mavjud validatorga tegmaydi)."""
    from app.services.discovery_1c.export_adapter import PLATFORM_KEYS
    text = EPF_SRC.read_text(encoding="utf-8")
    bosh = text.index("Функция СобратьПлатформу()")
    tana = text[bosh:text.index("КонецФункции", bosh)]
    qoshilgan = {"client_kind", "locale", "db_type", "application_mode",
                 "client_application_name"}
    for kalit in qoshilgan:
        assert kalit not in tana, (
            f"`{kalit}` `export.json` ning `platform` bo'limiga qo'shilgan — "
            f"`binos-1c-export-v1` shartnomasi BUZILADI (oq ro'yxat: {sorted(PLATFORM_KEYS)})")
    # Yangi maydonlar KENGAYTIRILGAN yig'uvchida bo'lishi shart — jimgina tashlanmasin.
    kengaytirilgan_bosh = text.index("Функция СобратьПлатформуЗапуска(")
    kengaytirilgan = text[kengaytirilgan_bosh:text.index("КонецФункции", kengaytirilgan_bosh)]
    for kalit in qoshilgan:
        assert kalit in kengaytirilgan, f"§11 maydoni yig'uvchida yo'q: {kalit}"


def test_EXPORT_platform_kalitlari_AYNAN_oq_royxatga_teng():
    """⚠️ DRIFT DARVOZASI: yig'uvchi `platform` ga qo'shgan kalit adapter oq ro'yxatidan
    chiqib ketsa, eksport BinOS tomonida RAD etiladi — va buni faqat haqiqiy yurish ko'rsatardi."""
    import re as _re
    from app.services.discovery_1c.export_adapter import PLATFORM_KEYS
    text = EPF_SRC.read_text(encoding="utf-8")
    bosh = text.index("Функция СобратьПлатформу()")
    tana = text[bosh:text.index("КонецФункции", bosh)]
    kalitlar = set(_re.findall(r'Сведения\.Вставить\("([a-z_]+)"', tana))
    assert kalitlar == PLATFORM_KEYS, (
        f"`export.platform` kalitlari adapter oq ro'yxatiga teng emas: "
        f"ortiqcha {sorted(kalitlar - PLATFORM_KEYS)}, tushib qolgan "
        f"{sorted(PLATFORM_KEYS - kalitlar)}")


# ══ NUQSON 9: AUDIT FAIL-OPEN — yopilmagan satr literali charset darvozasini KO'R qiladi ═══
# ⚠️ NEGA BU ALOHIDA BO'LIM: `kod_satrlari` satr literali HOLATINI satrlar ORASIDA saqlaydi.
#    Bitta yopilmagan qo'shtirnoq faylning QOLGAN QISMINI «literal» deb belgilaydi va
#    `NONSTANDARD_IDENT_CHAR` — kompilyatsiyani yiqitadigan `Қ` ni tutadigan YAGONA CI
#    darvozasi — jimgina KO'R bo'lib qoladi. Bu FAIL-OPEN: nuqson auditni o'chiradi.
BUZUQ_LITERAL = 'X = "ochildi\nФункция ЗондҚ()\n\tВозврат 1;\nКонецФункции\n'


def test_YOPILMAGAN_literal_OZI_topilma_boladi():
    """⚠️ Yopilmagan literal MATN FAKTI va u modulni kompilyatsiyadan chiqaradi — shu bois
    audit uni JIMGINA o'tkazmasligi kerak."""
    kodlar = [f.code for f in audit_source(BUZUQ_LITERAL)]
    assert "LITERAL_UNTERMINATED" in kodlar, (
        f"yopilmagan satr literali topilma bo'lmadi: {kodlar}")


def test_YOPILMAGAN_literal_CHARSET_darvozasini_KOR_qilmaydi():
    """⚠️ FAIL-CLOSED TALABI: yopilmagan literaldan KEYINGI satrlar KOD deb tekshirilishi
    kerak. Aks holda `Функция ЗондҚ()` dagi `Қ` (U+049A — rus alifbosida YO'Q harf) auditdan
    o'tib ketadi va kompilyatsiya mijozning mashinasida yiqiladi."""
    kodlar = [f.code for f in audit_source(BUZUQ_LITERAL)]
    assert "NONSTANDARD_IDENT_CHAR" in kodlar, (
        "yopilmagan literal charset qoidasini KO'R qildi — audit FAIL-OPEN: " + str(kodlar))


def test_KOP_SATRLI_literal_QONUNIY_naqsh_boladi():
    """⚠️ BSL da literal `|` bilan keyingi satrga CHO'ZILADI (so'rov matni shunday yoziladi).
    Fail-closed tuzatish bu QONUNIY naqshni topilma qilib qo'ymasligi kerak, aks holda
    darvoza shovqinga aylanardi."""
    manba = 'Запрос.Текст = "ВЫБРАТЬ\n|\t*\n|ИЗ Справочник.Товары";\n'
    kodlar = [f.code for f in audit_source(manba)]
    assert "LITERAL_UNTERMINATED" not in kodlar, f"ko'p satrli literal RAD etildi: {kodlar}"


def test_kod_satrlari_CHOZILGAN_literal_davomini_KOD_deb_oqimaydi():
    """⚠️ `|` bilan cho'zilgan literalning davomi KOD emas: u o'chirilib probel qo'yiladi."""
    from app.services.discovery_1c.epf_audit import kod_satrlari
    satrlar = 'Запрос.Текст = "ВЫБРАТЬ\n|\tҚҚҚ\n|ИЗ Т";\n'.splitlines()
    kod = dict(kod_satrlari(satrlar))
    assert "Қ" not in kod[2], f"literal davomi KOD deb o'qildi: {kod[2]!r}"


# ══ NUQSON 10: RUNTIME ARTEFAKTLARINING YAGONA SHAKLI (arxitektor qarori) ══════════════════
# ⚠️ NEGA BU BO'LIM BOR. Ilgari faqat artefakt JADVALI qulflangan edi, KALIT NOMLARI esa
#    YO'Q. Natijada yig'uvchi va BinOS tomonidagi validator bir-biriga ZID shakl yozdi va
#    HAR BIR haqiqiy paket rad etilardi — nuqson faqat birinchi jonli yurishda ko'rinardi.
#    Endi shakl QAT'IY va u AYNAN shu testlarda qulflanadi.
RUN_KALITLARI = ("run_version", "collector", "mode", "mode_note", "started_at", "finished_at",
                 "overall", "platform", "sections", "families", "probes", "artifacts",
                 "error_count", "notes")
BOLIM_HOLATLARI = ('"ok"', '"failed"', '"skipped"')
OILA_HOLATLARI = ('"present"', '"absent"', '"unreadable"')
XATO_DOIRALARI = ('"platform"', '"family"', '"object"', '"probe"', '"write"', '"mode"')
MAJBURIY_ARTEFAKTLAR = ("export.json", "metadata.json", "run_status.json", "errors.json",
                        "run_summary.md", "manifest.json")


def _bsl() -> str:
    return EPF_SRC.read_text(encoding="utf-8")


def _tana(text: str, sarlavha: str) -> str:
    """`Функция`/`Процедура` TANASI — butun fayl emas.

    ⚠️ NEGA KERAK: butun faylda qidirish izohdagi tushuntirishni ham «kod» deb sanardi, ya'ni
    nuqsonni tushuntirgan odam jazolanardi va tuzatilganini isbotlab bo'lmasdi."""
    bosh = text.index(sarlavha)
    oxir = min((text.index(so_z, bosh) for so_z in ("КонецФункции", "КонецПроцедуры")
                if so_z in text[bosh:]), default=len(text))
    return text[bosh:oxir]


def _chaqiruv_arglari(text: str, nom: str) -> list[tuple[int, list[str]]]:
    """`nom(...)` chaqiruvlarining YUQORI DARAJADAGI argumentlari: (satr raqami, arglar).

    ⚠️ BU PARSER EMAS, QAVS SANOG'I: satr literali ichidagi qavs va vergul hisobga olinmaydi,
    ichki chaqiruvlar esa BITTA argument bo'lib qoladi. Shu yerda yetarli — tekshirilayotgan
    narsa argumentlarning SONI va LITERAL qiymati."""
    import re as _re
    natija: list[tuple[int, list[str]]] = []
    for m in _re.finditer(rf"(?<![А-Яа-яЁёA-Za-z0-9_]){_re.escape(nom)}\s*\(", text):
        j = m.end()
        daraja = 1
        literalda = False
        arglar: list[str] = []
        bufer = ""
        while j < len(text) and daraja > 0:
            b = text[j]
            if literalda:
                if b == '"':
                    literalda = False
                bufer += b
            elif b == '"':
                literalda = True
                bufer += b
            elif b == "(":
                daraja += 1
                bufer += b
            elif b == ")":
                daraja -= 1
                if daraja > 0:
                    bufer += b
            elif b == "," and daraja == 1:
                arglar.append(bufer)
                bufer = ""
            else:
                bufer += b
            j += 1
        arglar.append(bufer)
        natija.append((text.count("\n", 0, m.start()) + 1,
                       [" ".join(a.split()) for a in arglar]))
    return natija


# ── VAZIFA A: run_status.json shakli ───────────────────────────────────────────────────────
def test_run_status_kalitlari_AYNAN_yagona_shaklga_teng():
    """⚠️ DRIFT DARVOZASI: ortiqcha kalit ham, tushib qolgan kalit ham paketni RAD ettiradi
    (`runtime_bundle` yuqori darajadagi kalitlarni QAT'IY oq ro'yxat bilan tekshiradi)."""
    import re as _re
    tana = _tana(_bsl(), "Функция СобратьСостояниеЗапуска(")
    kalitlar = _re.findall(r'Документ\.Вставить\("([a-z_]+)"', tana)
    assert len(kalitlar) == len(set(kalitlar)), f"kalit TAKRORLANGAN: {kalitlar}"
    assert sorted(kalitlar) == sorted(RUN_KALITLARI), (
        f"ortiqcha {sorted(set(kalitlar) - set(RUN_KALITLARI))}, "
        f"tushib qolgan {sorted(set(RUN_KALITLARI) - set(kalitlar))}")


def test_EXPORT_va_METADATA_jurnallari_sections_ga_BIRLASHADI():
    """⚠️ `export_sections`/`metadata_sections` shaklda YO'Q, lekin ularni TASHLASH ham mumkin
    emas: `platform` bo'limining yiqilishi FAQAT eksport jurnalida qayd etiladi va u
    `run_status` ga tushmasa, `overall` ikki tomonda BOSHQACHA hisoblanardi.

    ⚠️ Nom TAKRORLANMASLIGI SHART (`sections` da takroriy nom RAD etiladi), shu bois qo'shilgan
    jurnallar prefiks oladi."""
    text = _bsl()
    assert '"export_sections"' not in text and '"metadata_sections"' not in text
    tana = _tana(text, "Функция СобратьРазделыЗапуска(")
    for jurnal in ("ЖурналЗапуска", "ЖурналРазделов", "ЖурналМетаданных"):
        assert jurnal in tana, f"`sections` ga {jurnal} qo'shilmagan — ma'lumot YO'QOLADI"
    assert '"export:"' in tana and '"metadata:"' in tana, "prefiks yo'q — nom takrorlanadi"


def test_ABSENT_va_UNREADABLE_faqat_OILA_jurnalida_yashaydi():
    """⚠️ Bo'lim lug'ati `bundle.SECTION_STATUSES` bilan BIR XIL qoladi (`ok|failed|skipped`).
    `absent`/`unreadable` — OILA holati, bo'lim holati EMAS."""
    text = _bsl()
    for chaqiruv in ("ОтметитьЗапуск", "ОтметитьРаздел", "ОтметитьРазделМетаданных"):
        for satr_no, arglar in _chaqiruv_arglari(text, chaqiruv):
            assert arglar[1] not in ('"absent"', '"unreadable"'), (
                f"satr {satr_no}: {chaqiruv} ga OILA holati berilgan: {arglar[1]}")
    oilalar = _chaqiruv_arglari(text, "ОтметитьСемейство")
    assert oilalar, "`ОтметитьСемейство` YO'Q — oila jurnali qurilmagan"
    berilgan = {a[1] for _n, a in oilalar if a[1].startswith('"')}
    assert berilgan <= set(OILA_HOLATLARI), f"noma'lum oila holati: {berilgan}"
    assert berilgan == set(OILA_HOLATLARI), (
        f"oila holatlarining hammasi ishlatilmagan: {set(OILA_HOLATLARI) - berilgan}")


def test_BOLIM_holatlari_faqat_UCH_qiymat_va_ok_da_IZOH_YOQ():
    """⚠️ `ok` bo'limda `error` BO'LMAYDI (`bundle._validate_status` majburlaydi), `ok`
    BO'LMAGAN bo'lim esa SABABSIZ qolmaydi. Rejim izohi `mode_note` da yashaydi.

    ⚠️ HOLAT ARGUMENTI SHARTLI IFODA (`?(...)`) BO'LMASLIGI SHART: shartli ifoda bilan bu
    invariantni MATNDAN tekshirib bo'lmaydi, ya'ni darvoza ko'r bo'lib qolardi."""
    text = _bsl()
    for chaqiruv in ("ОтметитьЗапуск", "ОтметитьРаздел", "ОтметитьРазделМетаданных"):
        for satr_no, arglar in _chaqiruv_arglari(text, chaqiruv):
            if arglar[1] == "Состояние":
                continue                    # protsedurani TA'RIFLAGAN satr
            assert not arglar[1].startswith("?("), (
                f"satr {satr_no}: {chaqiruv} holati shartli ifoda — invariant ko'r qoladi")
            assert arglar[1] in BOLIM_HOLATLARI, (
                f"satr {satr_no}: noma'lum bo'lim holati {arglar[1]}")
            if arglar[1] == '"ok"':
                assert len(arglar) == 2, (
                    f"satr {satr_no}: `ok` bo'limga izoh berilgan: {arglar}")
            else:
                assert len(arglar) >= 3, f"satr {satr_no}: sababsiz {arglar[1]} bo'lim"


def test_errors_json_yozuvi_SCOPE_oladi_va_KOD_KATTA_HARF():
    """⚠️ `kind` -> `code` (BARQAROR KOD, `[A-Z][A-Z0-9_]*`), `message` -> `detail`,
    `scope` QO'SHILADI. Kichik harfli `kind` qiymatlari validator regexidan O'TMAYDI."""
    import re as _re
    text = _bsl()
    tana = _tana(text, "Процедура ДобавитьОшибку(")
    kalitlar = _re.findall(r'Запись\.Вставить\("([a-z_]+)"', tana)
    assert kalitlar == ["scope", "family", "object", "code", "detail"], kalitlar
    chaqiruvlar = _chaqiruv_arglari(text, "ДобавитьОшибку")
    assert len(chaqiruvlar) > 20, "chaqiruvlar topilmadi — test o'zini sinamayapti"
    for satr_no, arglar in chaqiruvlar:
        if arglar[0].startswith("Доира"):
            continue                        # ta'rifning O'ZI
        assert len(arglar) == 5, f"satr {satr_no}: 5 argument kutilgan: {arglar}"
        assert arglar[0] in XATO_DOIRALARI, f"satr {satr_no}: noma'lum doira {arglar[0]}"
        assert _re.fullmatch(r'"[A-Z][A-Z0-9_]*"', arglar[3]), (
            f"satr {satr_no}: xato KODI barqaror shaklda emas: {arglar[3]}")


def test_manifest_fayl_kaliti_NAME_deb_ataladi():
    """⚠️ `file` -> `name`: validator `MANIFEST_FILE_KEYS` ni QAT'IY tekshiradi."""
    import re as _re
    tana = _tana(_bsl(), "Процедура ЗарегистрироватьФайл(")
    kalitlar = _re.findall(r'Запись\.Вставить\("([a-z0-9_]+)"', tana)
    assert kalitlar == ["name", "bytes", "sha256"], kalitlar


def test_ZOND_QAYDI_shakl_kalitlarini_yozadi():
    """⚠️ `probes` yozuvi: `no, probe_type, target_object, reason, file, status`."""
    import re as _re
    tana = _tana(_bsl(), "Процедура ВыполнитьРазрешенныеЗонды(")
    kalitlar = _re.findall(r'Запись\.Вставить\("([a-z_]+)"', tana)
    assert kalitlar == ["no", "probe_type", "target_object", "reason", "file", "status"], kalitlar


# ── VAZIFA B: yolg'on SUCCESS — `errors.json` hisobga olinmaydi ────────────────────────────
def test_errors_json_YOZILISHI_overall_ga_KIRADI():
    """⚠️ YOLG'ON SUCCESS YO'LI: `errors.json` yozilishining qaytargan qiymati O'QILMAY
    tashlanardi, ya'ni fayl UMUMAN yozilmasa ham `overall` `SUCCESS` bo'lib qolardi —
    holbuki `errors.json` MAJBURIY artefakt va uning yo'qligi «xato bo'lmadi» degani emas."""
    import re as _re
    tana = _tana(_bsl(), "Функция ВыполнитьРазведку(")
    assert _re.search(r'\w+\s*=\s*ЗаписатьJSONФайл\(КаталогВыгрузки,\s*"errors\.json"', tana), (
        "`errors.json` yozilishining natijasi O'QILMAYDI")
    m = _re.search(r"СобратьСостояниеЗапуска\(([^)]*)\)", tana)
    assert m, "`СобратьСостояниеЗапуска` chaqirilmagan"
    for bayroq in ("ЭкспортЗаписан", "МетаданныеЗаписаны", "СводкаЗаписана", "ОшибкиЗаписаны"):
        assert bayroq in m.group(1), f"majburiy artefakt bayrog'i hisobga olinmagan: {bayroq}"


def test_ALTI_majburiy_artefakt_artifacts_ga_TUSHADI():
    """⚠️ `artifacts` — YOZILGAN artefakt nomlari. Olti majburiy artefaktning HAMMASI shu
    ro'yxatga tushishi kerak, aks holda validator «majburiy artefakt yozilmagan» deb
    hisoblaydi va ikki tomon `overall` ni BOSHQACHA hisoblaydi."""
    text = _bsl()
    assert "Процедура ОтметитьАртефакт(" in text, "artefakt jurnali YO'Q"
    tana = _tana(text, "Функция СобратьСостояниеЗапуска(")
    for nom in ("run_status.json", "manifest.json"):
        assert f'ОтметитьАртефакт("{nom}")' in tana, (
            f"`{nom}` `artifacts` ga tushmaydi — u O'ZIDAN KEYIN yoziladi, shu bois ATAYLAB "
            f"e'lon qilinishi va sababi izohda yozilishi kerak")
    for nom in MAJBURIY_ARTEFAKTLAR:
        assert f'"{nom}"' in text, nom


def test_OQILMAGAN_OILA_SUCCESS_ni_BUZADI():
    """⚠️ `unreadable` oila bilan yurish TO'LIQ emas. `absent` va `skipped` esa BUZMAYDI:
    `METADATA_ONLY` da `probes` har doim `skipped` — bu HALOL default yurish."""
    tana = _tana(_bsl(), "Функция ОбщееСостояние(")
    assert "ЕстьНечитаемоеСемейство()" in tana, "oila holati `overall` ga kirmaydi"
    assert '"SUCCESS"' in tana and '"PARTIAL"' in tana and '"FAILED"' in tana


def test_NOMALUM_REJIM_SUCCESS_bermaydi():
    """⚠️ IKKINCHI YOLG'ON SUCCESS YO'LI: noma'lum rejim kelganda fail-safe ishlaydi, lekin
    operator SO'RAGAN rejim BAJARILMAGAN — bu `mode` bo'limining yiqilishi."""
    text = _bsl()
    assert 'ОтметитьЗапуск("mode", "ok", ЗаметкаРежима)' not in text, (
        "`ok` bo'limga izoh berilgan va noma'lum rejim `ok` deb yozilgan")
    assert "РежимОтклонен" in text, "rad etilgan rejim bayrog'i yo'q"


# ── VAZIFA C: zond qaydida yolg'on `ok` ───────────────────────────────────────────────────
def test_ZOND_natija_YOQ_yoki_XATO_bor_bolsa_FAILED():
    """⚠️ YOLG'ON `ok`: ilgari faqat ISTISNO `failed` deb sanalardi. Nishon topilmagan yoki
    REJIM DARVOZASI RAD etgan zond Структура QAYTARADI (`result`=Неопределено, `errors`
    to'ldirilgan) — u `ok` deb yozilardi va `overall` `SUCCESS` bo'lardi, holbuki
    `probes/NN.json` da `result: null` turardi."""
    text = _bsl()
    assert 'Запись.Вставить("status", ?(Результат = Неопределено, "failed", "ok"))' not in text
    assert "Функция СостояниеЗонда(" in text, "zond holati bitta joyda hisoblanmaydi"
    tana = _tana(text, "Функция СостояниеЗонда(")
    assert "Результат = Неопределено" in tana, "natija YO'QLIGI tekshirilmaydi"
    assert "Результат.errors.Количество()" in tana, "zond XATOLARI tekshirilmaydi"
    assert '"failed"' in tana and '"ok"' in tana


def test_PROBES_bolimi_zond_QAYDI_bilan_ZID_bolmaydi():
    """⚠️ Zond qaydi `failed` bo'lsa `probes` bo'limi HAM `failed` bo'lishi SHART.

    Aks holda `run_status.json` ning o'z ichida ziddiyat bo'lardi: `probes[0].status` =
    `failed`, `sections[probes].status` = `ok`, `overall` = `SUCCESS`. Ilgari bo'lim faqat
    ISTISNO va YOZISH xatosini sanardi."""
    import re as _re
    tana = _tana(_bsl(), "Процедура ВыполнитьРазрешенныеЗонды(")
    assert "СостояниеЗаписи = СостояниеЗонда(Результат)" in tana, (
        "zond holati bo'lim bilan BITTA manbadan olinmaydi")
    assert _re.search(r'Если СостояниеЗаписи = "failed" Тогда\s+ТекстОшибок', tana), (
        "`failed` zond qaydi `probes` bo'limini yiqitmaydi")
