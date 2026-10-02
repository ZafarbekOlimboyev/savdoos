# -*- coding: utf-8 -*-
"""Runtime tayyorligi auditining testlari — STATIK, 1C'ga ulanmasdan.

⚠️ NIMANI ISBOTLAYDI: `runtime_audit.py` dagi har tekshiruv BUZUQ namunada
   nuqsonni TUTISHINI va SOG'LOM namunada tutmasligini; `INVENTORY_ITEMS` va
   `RUNTIME_READINESS.md` bir-biriga MOS ekanini; audit mavjud
   `BinOSDiscovery.bsl` ustida ishlashini.
⚠️ NIMANI ISBOTLAMAYDI: manbaning 1C da kompilyatsiya bo'lishini yoki ishlashini.
   Bu mashinada 1C:Enterprise YO'Q. Auditning O'ZI ham hech narsani isbotlamaydi —
   u faqat matnni ko'radi.

⚠️ NEGA HAR TEKSHIRUV UCHUN IKKI NAMUNA: tutmaydigan tekshiruv — yolg'on
   xotirjamlik; hamma narsani tutadigan tekshiruv — o'chirilgan darvoza. Ikkisi
   ham bir xil foydasiz, shu bois ikki tomoni ham qulflanadi.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.services.discovery_1c import runtime_audit as ra
from app.services.discovery_1c.runtime_audit import (
    CHECKS, EXTRACTOR_SOURCE, FINDING_STATUSES, INVENTORY_EVIDENCE, INVENTORY_ITEMS,
    MANIFEST_ALLOWED_KEYS, MANIFEST_FORBIDDEN_KEYS, MODES, OPTIONAL_FAMILIES,
    READINESS_DOC, RUNTIME_PACKAGE_REQUIRED, STATUS_KNOWN, STATUS_RUNTIME_UNKNOWN,
    STATUS_SOURCE_VALIDATED, TRISTATE_TEXTS, api_surface, audit_file, audit_source,
    check_api_surface, check_balanced_blocks, check_client_server_context,
    check_count_as_text, check_file_api_usage, check_identifier_charset,
    check_json_writer_usage, check_optional_family_guard, check_tristate_text,
    check_try_except_coverage, code_lines, findings_by_status, literal_defects,
    normalize_mode, procedures,
)

# ── Namunalar ──────────────────────────────────────────────────────────────────────────────
#: ⚠️ Namunalar TO'QIMA: ular mijoz konfiguratsiyasidan olinmagan va birorta
#:    haqiqiy metadata nomini ko'chirmaydi. Obyekt nomlari `X17`, `R41` shaklida.


#: Modulning O'Z manbasi: topilma kodlari rostdan chiqarilishini statik tekshirish uchun.
_MODUL_MANBASI = pathlib.Path(ra.__file__).read_text(encoding="utf-8")


def _kodlar(findings) -> set[str]:
    return {f.code for f in findings}


#: Minimal, «sog'lom» modul: hamma tekshiruv undan o'tishi kerak.
SOG_LOM = '''\
// BinOS test moduli (ObjectModule).
#Область ПрограммныйИнтерфейс

Функция ВыполнитьРазведку(КаталогВыгрузки) Экспорт

	Попытка
		Документ = Новый Структура;
		Документ.Вставить("hierarchical", ?(Истина, "true", "false"));
		Документ.Вставить("row_count", Формат(ОписанияКоллекций().Количество(), "ЧГ=0"));
		ВыгрузитьВФайл(КаталогВыгрузки, Документ);
	Исключение
		ОтметитьРаздел("run", "failed", ОписаниеОшибки());
	КонецПопытки;
	Возврат Неопределено;

КонецФункции

#КонецОбласти

#Область СлужебныеПроцедуры

Процедура ОтметитьРаздел(Имя, Состояние, Описание = Неопределено)
	Возврат;
КонецПроцедуры

Функция ОписанияКоллекций()
	Список = Новый Массив;
	Список.Добавить(ОписаниеКоллекции("ПланыСчетов"));
	Список.Добавить(ОписаниеКоллекции("ПланыВидовХарактеристик"));
	Список.Добавить(ОписаниеКоллекции("ОбщиеРеквизиты"));
	Список.Добавить(ОписаниеКоллекции("ПланыОбмена"));
	Возврат Список;
КонецФункции

Функция ОписаниеКоллекции(ИмяКоллекции)
	Возврат ИмяКоллекции;
КонецФункции

Процедура ВыгрузитьВФайл(КаталогВыгрузки, Документ)
	Попытка
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(ОбъединитьПути(КаталогВыгрузки, "export.json"), "UTF-8", Ложь);
		ЗаписатьJSON(ПотокJSON, Документ);
		ПотокJSON.Закрыть();
		ОтметитьРаздел("write_export", "ok");
	Исключение
		ПотокJSON.Закрыть();
		ОтметитьРаздел("write_export", "failed", ОписаниеОшибки());
	КонецПопытки;
КонецПроцедуры

#КонецОбласти
'''


def test_SOG_LOM_namuna_birorta_NUQSON_bermaydi():
    """Sog'lom namunada `KNOWN` topilma BO'LMASLIGI kerak.

    ⚠️ `SOURCE-VALIDATED` va `RUNTIME-UNKNOWN` topilmalar KUTILADI: birinchisi
    «tekshirdim, buzilmagan», ikkinchisi «buni faqat real 1C ko'rsatadi». Ular
    NUQSON emas, shu bois bu test faqat `KNOWN` ni taqiqlaydi.
    """
    findings = audit_source(SOG_LOM)
    buzuq = [f for f in findings if f.status == STATUS_KNOWN]
    assert not buzuq, "sog'lom namunada nuqson topildi:\n" + "\n".join(
        f"  {f.code} satr {f.line_no}: {f.line}  ({f.why})" for f in buzuq)


# ── 1. identifier_charset ──────────────────────────────────────────────────────────────────
def test_charset_BEGONA_kirill_harfini_tutadi():
    buzuq = SOG_LOM.replace("ВыгрузитьВФайл", "ВыгрузитьВФайлҚ")
    kodlar = _kodlar(check_identifier_charset(buzuq))
    assert "CHARSET_FOREIGN_LETTER" in kodlar


def test_charset_IZOH_va_SATR_LITERALIDAGI_begona_harfni_TUTMAYDI():
    """Izohdagi va literal ichidagi begona harf KOD emas — u kompilyatsiyaga
    ta'sir qilmaydi, shu bois tutilishi YOLG'ON IJOBIY bo'lardi."""
    tinch = SOG_LOM.replace(
        '// BinOS test moduli (ObjectModule).',
        '// BinOS test moduli (ObjectModule). Қозоқча изоҳ.\n'
        '// Ва Ў, Ғ, Ҳ ҳарфлари ҳам.')
    tinch = tinch.replace('"export.json"', '"экспортҚ.json"')
    assert "CHARSET_FOREIGN_LETTER" not in _kodlar(check_identifier_charset(tinch))


def test_charset_KIRILL_va_KICHIK_LOTIN_aralashmasini_tutadi():
    """Gomoglif tuzog'i: `Запрoс` dagi `o` — lotin, ko'z bilan farq qilinmaydi."""
    buzuq = SOG_LOM.replace("ПотокJSON =", "Потокjson =")
    assert "CHARSET_MIXED_SCRIPT" in _kodlar(check_identifier_charset(buzuq))


def test_charset_BOSH_HARFLI_akronimni_TUTMAYDI():
    """`ЗаписьJSON`, `ВСтрокуISO` — platforma nomlarining O'ZI shunday."""
    assert "CHARSET_MIXED_SCRIPT" not in _kodlar(check_identifier_charset(SOG_LOM))


def test_charset_BOSH_HARFDAN_boshlangan_lotin_sozini_TUTMAYDI():
    """⚠️ Platformaning O'ZIDA shunday nom bor:
    `ПолучитьHexСтрокуИзДвоичныхДанных`. Uni tutish YOLG'ON IJOBIY edi va bu
    TOPILGAN xato — qoida faqat BOSH HARFLI akronimni ruxsat etardi."""
    matn = SOG_LOM.replace(
        "\tВозврат Неопределено;\n",
        "\tХеш = ПолучитьHexСтрокуИзДвоичныхДанных(Данные);\n"
        "\tВозврат Хеш;\n", 1)
    assert "CHARSET_MIXED_SCRIPT" not in _kodlar(check_identifier_charset(matn))


# ── 2. balanced_blocks ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ochuvchi,yopuvchi", [
    ("Процедура", "КонецПроцедуры"),
    ("Функция", "КонецФункции"),
    ("Попытка", "КонецПопытки"),
    ("#Область", "#КонецОбласти"),
])
def test_muvozanat_YOPUVCHI_tushib_qolganini_tutadi(ochuvchi, yopuvchi):
    buzuq = SOG_LOM.replace(yopuvchi, "", 1)
    findings = check_balanced_blocks(buzuq)
    assert "BLOCK_UNBALANCED" in _kodlar(findings)
    assert any(ochuvchi in f.why for f in findings if f.code == "BLOCK_UNBALANCED")


def test_muvozanat_YOPUVCHI_OCHUVCHIDAN_OLDIN_kelganini_tutadi():
    buzuq = SOG_LOM.replace("\tПопытка\n", "\tКонецПопытки;\n\tПопытка\n\tПопытка\n", 1)
    assert "BLOCK_CLOSER_BEFORE_OPENER" in _kodlar(check_balanced_blocks(buzuq))


def test_muvozanat_IНАЧЕЕСЛИ_ni_ochuvchi_deb_SANAMAYDI():
    """`ИначеЕсли` yangi blok OCHMAYDI — uni `Если` deb sanash muvozanatni
    yolg'on buzardi."""
    matn = SOG_LOM.replace(
        "\tВозврат Неопределено;\n",
        "\tЕсли Истина Тогда\n\t\tВозврат Неопределено;\n"
        "\tИначеЕсли Ложь Тогда\n\t\tВозврат Неопределено;\n\tКонецЕсли;\n", 1)
    assert "BLOCK_UNBALANCED" not in _kodlar(check_balanced_blocks(matn))


def test_muvozanat_SOG_LOM_namunada_tasdiqlanadi():
    findings = check_balanced_blocks(SOG_LOM)
    assert [f.code for f in findings] == ["BLOCKS_BALANCED"]
    assert findings[0].status == STATUS_SOURCE_VALIDATED


# ── 2b. satr literallari (`literal_defects`, `check_balanced_blocks` ichida) ────────────────
def test_literal_TESKARI_CHIZIQLI_qoshtirnoqni_tutadi():
    """⚠️ BSL da qo'shtirnoq `\"\"` bilan yoziladi. `\\\"` — JSON/Python
    qochirishi ko'chirib yozilganda bo'ladi va literalni SHU YERDA yopadi:
    satrning qolgani KODGA aylanib, modul kompilyatsiyadan chiqadi."""
    buzuq = SOG_LOM.replace('ОтметитьРаздел("run", "failed", ОписаниеОшибки())',
                            'ОтметитьРаздел("run", "\\"failed\\"", ОписаниеОшибки())')
    findings = [f for f in literal_defects(buzuq)
                if f.code == "LITERAL_BACKSLASH_QUOTE"]
    assert findings and all(f.status == STATUS_KNOWN for f in findings)
    assert "LITERAL_BACKSLASH_QUOTE" in _kodlar(check_balanced_blocks(buzuq))


def test_literal_YOPILMAGANINI_tutadi():
    buzuq = SOG_LOM + '\nПроцедура X()\n\tА = "yopilmagan;\nКонецПроцедуры\n'
    findings = [f for f in literal_defects(buzuq) if f.code == "LITERAL_UNTERMINATED"]
    assert findings and findings[0].status == STATUS_KNOWN


def test_literal_IKKILANGAN_qoshtirnoqni_TUTMAYDI():
    """`""` — BSL ning O'Z qochirish usuli, u nuqson EMAS."""
    tinch = SOG_LOM.replace('"failed"', '"""failed"""')
    assert not literal_defects(tinch)


def test_literal_SOG_LOM_namunada_jim():
    assert not literal_defects(SOG_LOM)


# ── 3. api_surface ─────────────────────────────────────────────────────────────────────────
def test_api_NOMALUM_global_nomni_RUNTIME_UNKNOWN_deb_belgilaydi():
    buzuq = SOG_LOM.replace("Новый Структура", "Новый ХитройНеизвестныйТип")
    findings = [f for f in check_api_surface(buzuq) if f.code == "API_NAME_UNVERIFIED"]
    assert any("ХитройНеизвестныйТип" in f.why for f in findings)
    assert all(f.status == STATUS_RUNTIME_UNKNOWN for f in findings)


def test_api_TANISH_nom_uchun_topilma_BERMAYDI():
    tanish, nomalum = api_surface(SOG_LOM)
    assert "Формат" in tanish and "ЗаписьJSON" in tanish
    assert not nomalum, f"sog'lom namunada noma'lum nom: {nomalum}"


def test_api_MAHALLIY_nomlar_global_yuzaga_KIRMAYDI():
    """Parametr, protsedura nomi va tayinlash chap tomoni global nom EMAS."""
    _, nomalum = api_surface(SOG_LOM)
    for mahalliy in ("КаталогВыгрузки", "Документ", "ОтметитьРаздел", "ПотокJSON"):
        assert mahalliy not in nomalum


def test_api_ZNACH_kalit_sozi_parametr_nomini_KESMAYDI():
    """`Знач ОписаниеТипаЗначения` — `Знач` ni oddiy almashtirish bilan olib
    tashlash nomni `ОписаниеТипа` ga aylantirardi (TOPILGAN xato)."""
    matn = SOG_LOM.replace(
        "Функция ОписаниеКоллекции(ИмяКоллекции)",
        "Функция ОписаниеКоллекции(Знач ОписаниеТипаЗначения)").replace(
        "\tВозврат ИмяКоллекции;", "\tВозврат ОписаниеТипаЗначения;")
    _, nomalum = api_surface(matn)
    assert "ОписаниеТипа" not in nomalum
    assert "ОписаниеТипаЗначения" not in nomalum


def test_api_HUDUD_nomi_global_yuzaga_KIRMAYDI():
    """`#Область ПрограммныйИнтерфейс` — hudud nomi chaqiriluvchi nom EMAS."""
    _, nomalum = api_surface(SOG_LOM)
    assert "ПрограммныйИнтерфейс" not in nomalum
    assert "СлужебныеПроцедуры" not in nomalum


# ── 4. client_server_context ───────────────────────────────────────────────────────────────
def test_kontekst_NA_KLIENTE_direktivasini_tutadi():
    buzuq = SOG_LOM.replace("Функция ВыполнитьРазведку",
                            "&НаКлиенте\nФункция ВыполнитьРазведку", 1)
    findings = check_client_server_context(buzuq)
    assert "CONTEXT_CLIENT_DIRECTIVE" in _kodlar(findings)


def test_kontekst_DIREKTIVASIZ_modulni_RUNTIME_UNKNOWN_deb_yozadi():
    findings = [f for f in check_client_server_context(SOG_LOM)
                if f.code == "CONTEXT_NO_DIRECTIVE"]
    assert len(findings) == 1
    assert findings[0].status == STATUS_RUNTIME_UNKNOWN


def test_kontekst_MODUL_TURI_elon_qilinmaganini_tutadi():
    buzuq = SOG_LOM.replace("(ObjectModule)", "(qandaydir modul)")
    assert "CONTEXT_MODULE_KIND_UNDECLARED" in _kodlar(
        check_client_server_context(buzuq))


def test_kontekst_EKSPORT_kirish_nuqtasi_yoqligini_tutadi():
    buzuq = SOG_LOM.replace("(КаталогВыгрузки) Экспорт", "(КаталогВыгрузки)")
    assert "CONTEXT_NO_EXPORT" in _kodlar(check_client_server_context(buzuq))


def test_EKSPORT_aniqlash_NOM_va_PARAMETR_bilan_chalkashmaydi():
    """`ЗаметкиЭкспорта` (nom ichida) va `(…, Экспорт)` (parametr nomi) — ikkovi
    ham eksport DEGANI EMAS. Ikkisi ham TOPILGAN xato edi."""
    matn = SOG_LOM + (
        "\nФункция ЗаметкиЭкспорта()\n\tВозврат Новый Массив;\nКонецФункции\n"
        "\nПроцедура СохранитьПакет(Каталог, Экспорт)\n\tВозврат;\nКонецПроцедуры\n")
    eksportlar = {p.name for p in procedures(code_lines(matn)) if p.exported}
    assert eksportlar == {"ВыполнитьРазведку"}


# ── 5. try_except_coverage ─────────────────────────────────────────────────────────────────
def test_try_metadata_siklini_POPYTKA_tashqarisida_tutadi():
    buzuq = SOG_LOM.replace(
        "Функция ОписаниеКоллекции(ИмяКоллекции)\n\tВозврат ИмяКоллекции;",
        "Функция ОписаниеКоллекции(ИмяКоллекции)\n"
        "\tКоллекция = Метаданные[ИмяКоллекции];\n"
        "\tДля Каждого ОбъектМД Из Коллекция Цикл\n"
        "\t\tВозврат ОбъектМД;\n"
        "\tКонецЦикла;\n"
        "\tВозврат ИмяКоллекции;", 1)
    findings = check_try_except_coverage(buzuq)
    assert "LOOP_WITHOUT_TRY" in _kodlar(findings)
    assert all(f.status == STATUS_KNOWN for f in findings
               if f.code == "LOOP_WITHOUT_TRY")


def test_try_POPYTKA_ichidagi_siklni_TUTMAYDI():
    tinch = SOG_LOM.replace(
        "Функция ОписаниеКоллекции(ИмяКоллекции)\n\tВозврат ИмяКоллекции;",
        "Функция ОписаниеКоллекции(ИмяКоллекции)\n"
        "\tПопытка\n"
        "\t\tКоллекция = Метаданные[ИмяКоллекции];\n"
        "\t\tДля Каждого ОбъектМД Из Коллекция Цикл\n"
        "\t\t\tВозврат ОбъектМД;\n"
        "\t\tКонецЦикла;\n"
        "\tИсключение\n"
        "\t\tВозврат Неопределено;\n"
        "\tКонецПопытки;\n"
        "\tВозврат ИмяКоллекции;", 1)
    assert "LOOP_WITHOUT_TRY" not in _kodlar(check_try_except_coverage(tinch))


def test_try_metadata_BOLMAGAN_siklni_TUTMAYDI():
    """O'zimizning massivimiz ustidan kezish istisno bermaydi — uni tutish
    darvozani shovqinga ko'mardi."""
    tinch = SOG_LOM.replace(
        "\tВозврат Список;",
        "\tДля Каждого Элемент Из Список Цикл\n\t\tВозврат Элемент;\n\tКонецЦикла;\n"
        "\tВозврат Список;", 1)
    assert "LOOP_WITHOUT_TRY" not in _kodlar(check_try_except_coverage(tinch))


def test_try_EKSPORT_kirish_nuqtasida_POPYTKA_yoqligini_tutadi():
    buzuq = (SOG_LOM.replace("\tПопытка\n\t\tДокумент", "\t\tДокумент", 1)
             .replace("\tИсключение\n\t\tОтметитьРаздел(\"run\", \"failed\", "
                      "ОписаниеОшибки());\n\tКонецПопытки;\n", "", 1))
    findings = [f for f in check_try_except_coverage(buzuq)
                if f.code == "ENTRY_WITHOUT_TRY"]
    assert findings and "ВыполнитьРазведку" in findings[0].why


# ── 6. file_api_usage ──────────────────────────────────────────────────────────────────────
def test_fayl_KONKATENATSIYA_bilan_qurilgan_yolni_tutadi():
    buzuq = SOG_LOM.replace(
        'ОбъединитьПути(КаталогВыгрузки, "export.json")',
        'КаталогВыгрузки + "/export.json"')
    kodlar = _kodlar(check_file_api_usage(buzuq))
    assert {"PATH_BUILT_BY_CONCAT", "PATH_FORWARD_SLASH", "PATH_NO_JOIN_HELPER"} <= kodlar


def test_fayl_TESKARI_CHIZIQNI_ham_tutadi():
    buzuq = SOG_LOM.replace(
        'ОбъединитьПути(КаталогВыгрузки, "export.json")',
        'КаталогВыгрузки + "\\\\export.json"')
    assert "PATH_BACKSLASH" in _kodlar(check_file_api_usage(buzuq))


def test_fayl_OBJEDINITPUTI_ishlatilganda_jim_turadi():
    kodlar = _kodlar(check_file_api_usage(SOG_LOM))
    assert not ({"PATH_BUILT_BY_CONCAT", "PATH_FORWARD_SLASH", "PATH_BACKSLASH",
                 "PATH_NO_JOIN_HELPER"} & kodlar)


def test_fayl_YOLNI_OZGARUVCHIDA_qurishni_ham_tutadi():
    """⚠️ Yo'lni bir qadam nariga (`Путь = Каталог + "/" + Nom;`) ko'chirish
    tekshiruvni JIMGINA o'chirib qo'yardi — tekshiruv bir qadam ochadi."""
    buzuq = SOG_LOM.replace(
        '\t\tПотокJSON.ОткрытьФайл(ОбъединитьПути(КаталогВыгрузки, "export.json"), '
        '"UTF-8", Ложь);\n',
        '\t\tПуть = КаталогВыгрузки + "/export.json";\n'
        '\t\tПотокJSON.ОткрытьФайл(Путь, "UTF-8", Ложь);\n', 1)
    findings = check_file_api_usage(buzuq)
    kodlar = _kodlar(findings)
    assert {"PATH_BUILT_BY_CONCAT", "PATH_FORWARD_SLASH"} <= kodlar
    #: Topilma TAYINLASH satrida ko'rsatiladi, `ОткрытьФайл` satrida emas.
    assert any("Путь = КаталогВыгрузки" in f.line for f in findings
               if f.code == "PATH_BUILT_BY_CONCAT")


def test_fayl_YOZUV_KANALI_yoqligini_tutadi():
    buzuq = SOG_LOM.replace("ПотокJSON.ОткрытьФайл", "ПотокJSON.ЧтоТоДругое")
    assert "FILE_NO_WRITE_CHANNEL" in _kodlar(check_file_api_usage(buzuq))


# ── 7. json_writer_usage ───────────────────────────────────────────────────────────────────
def test_json_ZAKRYT_ISKLYUCHENIE_shoxida_yoqligini_tutadi():
    """⚠️ ENG MUHIM TOPILMA: `Закрыть()` faqat muvaffaqiyat shoxida bo'lsa,
    `ЗаписатьJSON` yiqilganda oqim OCHIQ qoladi va diskda YARIM yozilgan JSON
    qoladi — uni keyin `SUCCESS` deb belgilash mumkin."""
    buzuq = SOG_LOM.replace("\tИсключение\n\t\tПотокJSON.Закрыть();\n",
                            "\tИсключение\n", 1)
    findings = [f for f in check_json_writer_usage(buzuq)
                if f.code == "JSON_CLOSE_NOT_GUARANTEED"]
    assert len(findings) == 1 and findings[0].status == STATUS_KNOWN


def test_json_ZAKRYT_UMUMAN_yoqligini_tutadi():
    buzuq = SOG_LOM.replace("ПотокJSON.Закрыть();", "ОтметитьРаздел(\"x\", \"ok\");")
    assert "JSON_CLOSE_MISSING" in _kodlar(check_json_writer_usage(buzuq))


def test_json_KODLASH_UTF8_emasligini_tutadi():
    buzuq = SOG_LOM.replace('"UTF-8", Ложь', '"windows-1251", Ложь')
    findings = [f for f in check_json_writer_usage(buzuq)
                if f.code == "JSON_ENCODING_NOT_UTF8"]
    assert findings and "windows-1251" in findings[0].why


def test_json_BOM_sorovini_tutadi():
    buzuq = SOG_LOM.replace('"UTF-8", Ложь', '"UTF-8", Истина')
    assert "JSON_BOM_REQUESTED" in _kodlar(check_json_writer_usage(buzuq))


def test_json_BOM_argumenti_berilmaganini_RUNTIME_UNKNOWN_qiladi():
    buzuq = SOG_LOM.replace('"UTF-8", Ложь', '"UTF-8"')
    findings = [f for f in check_json_writer_usage(buzuq) if f.code == "JSON_BOM_UNSET"]
    assert findings and findings[0].status == STATUS_RUNTIME_UNKNOWN


def test_json_MUVAFFAQIYAT_jurnalga_yozilmaganini_tutadi():
    buzuq = SOG_LOM.replace('\t\tОтметитьРаздел("write_export", "ok");\n', "", 1)
    findings = [f for f in check_json_writer_usage(buzuq)
                if f.code == "WRITE_SUCCESS_UNRECORDED"]
    assert findings and "ВыгрузитьВФайл" in findings[0].why


def test_json_VOZVRAT_ISTINA_ham_MUVAFFAQIYAT_bildirishi_hisoblanadi():
    """⚠️ `Возврат Истина` bilan ishlaydigan yozuvchi YOLG'ON tutilardi — bu
    TOPILGAN yolg'on ijobiy edi: muvaffaqiyatni chaqiruvchi jurnalga yozadi."""
    matn = SOG_LOM.replace('\t\tОтметитьРаздел("write_export", "ok");\n',
                           "\t\tВозврат Истина;\n", 1)
    assert "WRITE_SUCCESS_UNRECORDED" not in _kodlar(check_json_writer_usage(matn))


def test_json_SOG_LOM_namunada_faqat_TASDIQ_beradi():
    findings = check_json_writer_usage(SOG_LOM)
    assert not [f for f in findings if f.status == STATUS_KNOWN]
    assert {"JSON_WRITER_PAIR_PRESENT", "JSON_ENCODING_UTF8", "JSON_BOM_DISABLED"} <= _kodlar(findings)


# ── 8. tristate_text ───────────────────────────────────────────────────────────────────────
def test_uchlik_BULEVO_qiymatini_tutadi():
    buzuq = SOG_LOM.replace('?(Истина, "true", "false")', "Истина")
    findings = [f for f in check_tristate_text(buzuq)
                if f.code == "TRISTATE_BOOLEAN_VALUE"]
    assert findings and "hierarchical" in findings[0].why


def test_uchlik_STRUKTURA_MAYDONIGA_bulevo_tayinlashini_tutadi():
    buzuq = SOG_LOM.replace("\tВозврат Неопределено;\n",
                            "\tДокумент.hierarchical = Истина;\n\tВозврат Неопределено;\n", 1)
    assert "TRISTATE_BOOLEAN_FIELD" in _kodlar(check_tristate_text(buzuq))


def test_uchlik_LUGATDAN_TASHQARI_shoxni_tutadi():
    buzuq = SOG_LOM.replace('?(Истина, "true", "false")', '?(Истина, "true", "yes")')
    findings = [f for f in check_tristate_text(buzuq)
                if f.code == "TRISTATE_UNKNOWN_VOCABULARY"]
    assert findings and "yes" in findings[0].why


def test_uchlik_UCHLIK_BOLMAGAN_ternarni_TUTMAYDI():
    """`?(Смещение < 0, "-", "+")` — uchlik mantiq EMAS, ishora tanlash. Uni
    tutish YOLG'ON IJOBIY edi (TOPILGAN xato)."""
    tinch = SOG_LOM.replace("\tВозврат Неопределено;\n",
                            '\tЗнак = ?(Истина, "-", "+");\n\tВозврат Знак;\n', 1)
    assert "TRISTATE_UNKNOWN_VOCABULARY" not in _kodlar(check_tristate_text(tinch))


def test_uchlik_LITERAL_BOLMAGAN_kalitni_TUTMAYDI():
    """`Виденные.Вставить(Имя, Истина)` — ichki `Соответствие`, JSON'ga chiqmaydi."""
    tinch = SOG_LOM.replace("\tВозврат Неопределено;\n",
                            "\tВиденные.Вставить(Имя, Истина);\n\tВозврат Неопределено;\n", 1)
    assert "TRISTATE_BOOLEAN_VALUE" not in _kodlar(check_tristate_text(tinch))


# ── 9. count_as_text ───────────────────────────────────────────────────────────────────────
def test_sanoq_FORMAT_siz_yozilganini_tutadi():
    buzuq = SOG_LOM.replace('Формат(ОписанияКоллекций().Количество(), "ЧГ=0")',
                            "ОписанияКоллекций().Количество()")
    findings = [f for f in check_count_as_text(buzuq) if f.code == "COUNT_NOT_TEXT"]
    assert findings and findings[0].status == STATUS_KNOWN


def test_sanoq_TAQQOSLASHNI_va_SIKL_CHEGARASINI_tutmaydi():
    """`Если …Количество() = 0` da son SONLIGIDA kerak."""
    tinch = SOG_LOM.replace(
        "\tВозврат Список;",
        "\tЕсли Список.Количество() = 0 Тогда\n\t\tВозврат Список;\n\tКонецЕсли;\n"
        "\tВозврат Список;", 1)
    assert "COUNT_NOT_TEXT" not in _kodlar(check_count_as_text(tinch))


def test_sanoq_SOG_LOM_namunada_tasdiqlanadi():
    findings = check_count_as_text(SOG_LOM)
    assert [f.code for f in findings] == ["COUNT_TEXT_ONLY"]


# ── 10. optional_family_guard ──────────────────────────────────────────────────────────────
def test_oila_UMUMAN_ESLANMAGANINI_tutadi():
    buzuq = SOG_LOM.replace('\tСписок.Добавить(ОписаниеКоллекции("ПланыОбмена"));\n', "", 1)
    findings = [f for f in check_optional_family_guard(buzuq)
                if f.code == "OPTIONAL_FAMILY_UNMENTIONED"]
    assert [f.line for f in findings] == ["ПланыОбмена"]
    assert findings[0].status == STATUS_KNOWN


def test_oila_JURNALSIZ_ishlanganini_tutadi():
    buzuq = SOG_LOM.replace('\tСписок.Добавить(ОписаниеКоллекции("ПланыОбмена"));\n', "", 1)
    buzuq += ('\nФункция ЗондПланыОбмена()\n'
              '\tВозврат Метаданные["ПланыОбмена"];\n'
              'КонецФункции\n')
    findings = [f for f in check_optional_family_guard(buzuq)
                if f.code == "OPTIONAL_FAMILY_UNLOGGED"]
    assert [f.line for f in findings] == ["ПланыОбмена"]


def test_oila_IZOHDA_eslanishi_QORIQLASH_deb_hisoblanmaydi():
    """Izohdagi nom runtime'da hech narsa qilmaydi — «eslangan» deb hisoblanishi
    YOLG'ON kafolat bo'lardi."""
    buzuq = SOG_LOM.replace('\tСписок.Добавить(ОписаниеКоллекции("ПланыОбмена"));\n',
                            "\t// ПланыОбмена keyinroq qo'shiladi\n", 1)
    findings = [f for f in check_optional_family_guard(buzuq)
                if f.code == "OPTIONAL_FAMILY_UNMENTIONED"]
    assert [f.line for f in findings] == ["ПланыОбмена"]


def test_oila_SOG_LOM_namunada_hammasi_QORIQLANGAN():
    findings = check_optional_family_guard(SOG_LOM)
    assert {f.code for f in findings} == {"OPTIONAL_FAMILY_GUARDED"}
    assert {f.line for f in findings} == set(OPTIONAL_FAMILIES)


# ── code_lines ─────────────────────────────────────────────────────────────────────────────
def test_code_lines_satr_RAQAMINI_va_UZUNLIGINI_saqlaydi():
    matn = 'A = 1;  // izoh\nB = "literal";\n'
    kod = code_lines(matn)
    assert len(kod) == 2
    assert [len(s) for s in kod] == [len(s) for s in matn.splitlines()]
    assert "izoh" not in kod[0] and "literal" not in kod[1]


def test_code_lines_LITERALNI_saqlash_rejimi():
    kod = code_lines('A = "UTF-8";  // izoh', strip_literals=False)
    assert '"UTF-8"' in kod[0] and "izoh" not in kod[0]


def test_code_lines_KO_P_SATRLI_literalni_kuzatadi():
    matn = 'Запрос.Текст = "ВЫБРАТЬ\n|  Записать(Объект)";\nA = 1;'
    kod = code_lines(matn)
    assert "Записать" not in "\n".join(kod)
    assert "A = 1;" in kod[2]


# ── Reyestr va holatlar ────────────────────────────────────────────────────────────────────
def test_CHECKS_reyestri_ONTA_tekshiruvni_qamraydi():
    assert len(CHECKS) == 10
    assert len({nom for nom, _ in CHECKS}) == 10


def test_har_tekshiruv_FAQAT_lugatdagi_holatni_beradi():
    for nom, tekshiruv in CHECKS:
        for f in tekshiruv(SOG_LOM):
            assert f.status in FINDING_STATUSES, f"{nom}: {f.code} -> {f.status}"


def test_audit_source_DETERMINISTIK_tartib_beradi():
    bir = [(f.code, f.line_no) for f in audit_source(SOG_LOM)]
    ikki = [(f.code, f.line_no) for f in audit_source(SOG_LOM)]
    assert bir == ikki == sorted(bir, key=lambda x: (x[1], x[0]))


# ── Mavjud manba ustida ────────────────────────────────────────────────────────────────────
def test_manba_fayli_REPODA_mavjud():
    assert EXTRACTOR_SOURCE.is_file(), f"ekstraktor manbasi topilmadi: {EXTRACTOR_SOURCE}"


def test_mavjud_MANBA_ustida_audit_ISHLAYDI():
    """⚠️ Bu test topilmalar BO'SH bo'lishini TALAB QILMAYDI. `RUNTIME-UNKNOWN`
    topilma NUQSON emas — u «buni faqat real 1C ko'rsatadi» degan yozuv, va
    bunday yozuv bo'lishi NORMAL."""
    findings = audit_file(EXTRACTOR_SOURCE)
    sanoq = findings_by_status(findings)
    assert findings, "audit mavjud manba ustida hech narsa ko'rmadi — bu shubhali"
    assert sanoq[STATUS_RUNTIME_UNKNOWN] > 0, (
        "mavjud manbada birorta RUNTIME-UNKNOWN yo'q — audit o'z chegarasini "
        "yashirib qo'ygan bo'lishi mumkin")
    assert set(sanoq) == set(FINDING_STATUSES)


def test_mavjud_manbada_topilma_KODLARI_reyestrda_bor():
    """Mavjud manbadan chiqqan har kod `runtime_audit.py` da rostdan yozilgan.

    ⚠️ NEGA AYNAN SHU SHAKLDA, «bu nuqsonlar bo'lishi shart» DEB EMAS: manba
    HOZIR boshqa agentlar tomonidan tahrirlanmoqda. Konkret nuqson kodlarini
    testga qotirish tuzatish kelganda suitani qizil qilardi va tuzatishni
    jazolardi. Inventar holatlari esa SNAPSHOT: ular
    `runtime_audit.INVENTORY_ITEMS` da, qayta hisoblash buyrug'i bilan birga
    yozilgan.
    """
    modul = _MODUL_MANBASI
    for kod in sorted(_kodlar(audit_file(EXTRACTOR_SOURCE))):
        assert f'"{kod}"' in modul, kod


def test_charset_tekshiruvi_mavjud_manbada_SOG_LOM_va_TO_LIQ():
    """Charset tekshiruvining IKKI TOMONI mustaqil sanoq bilan solishtiriladi.

    ⚠️ NEGA SHUNDAY YOZILGAN: hozirgi manbada `Қ` (U+049A) bor va uni BOSHQA
    agent tuzatmoqda. «Ikki topilma bo'lishi shart» deb yozilgan test tuzatish
    kelganda yiqilardi, «nol topilma» deb yozilgani esa hozir yiqilardi. Shu
    bois test FAYL HOLATIGA bog'lanmaydi: u SOG'LOMLIK (tutilgan har satrda
    rostdan begona harf bor) va TO'LIQLIK (begona harfli har satr tutilgan)
    xossalarini tekshiradi — ikkisi tuzatishdan OLDIN ham, KEYIN ham to'g'ri.
    """
    matn = EXTRACTOR_SOURCE.read_text(encoding="utf-8")
    kod = code_lines(matn)
    #: Mustaqil sanoq: auditning O'Z mantiqini takrorlamaydi, oddiy oraliq bilan.
    ru = set("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    kutilgan = {i for i, s in enumerate(kod, 1)
                if any("Ѐ" <= c <= "ӿ" and c not in ru for c in s)}
    topilgan = {f.line_no for f in check_identifier_charset(matn)
                if f.code == "CHARSET_FOREIGN_LETTER"}
    assert topilgan == kutilgan, (
        f"charset tekshiruvi mos kelmadi: topilgan {sorted(topilgan)}, "
        f"kutilgan {sorted(kutilgan)}")


def test_mavjud_manbada_blok_MUVOZANATI_buzilmagan():
    """⚠️ Faqat BLOK sanog'i: shu tekshiruv literal nuqsonlarini ham qaytaradi
    (`literal_defects`), ular alohida masala va alohida test bilan qulflangan."""
    kodlar = {f.code for f in check_balanced_blocks(
        EXTRACTOR_SOURCE.read_text(encoding="utf-8")) if f.code.startswith("BLOCK")}
    assert kodlar == {"BLOCKS_BALANCED"}


# ── Inventar hujjati ───────────────────────────────────────────────────────────────────────
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*`([a-z_]+)`\s*\|")


def _inventar_qatorlari() -> list[tuple[int, str, str]]:
    """`RUNTIME_READINESS.md` dagi §2 jadvalining qatorlari: (#, slug, holat).

    ⚠️ Holat AYNAN TO'RTINCHI ustundan olinadi, butun qatordan izlanmaydi:
    izoh ustunlarida holat nomi ATAYLAB eslanishi mumkin («shu bois `KNOWN`
    emas»), va butun qatorni izlash uni HOLAT deb o'qib qo'yardi.
    """
    natija: list[tuple[int, str, str]] = []
    for satr in READINESS_DOC.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(satr)
        if m is None:
            continue
        ustunlar = [u.strip() for u in satr.split("|")]
        holat = ustunlar[4].strip("`")
        assert holat in FINDING_STATUSES, f"qator {m.group(2)}: holat aniq emas {holat!r}"
        natija.append((int(m.group(1)), m.group(2), holat))
    return natija


def test_inventar_hujjati_mavjud():
    assert READINESS_DOC.is_file(), f"inventar hujjati topilmadi: {READINESS_DOC}"


def test_inventar_jadvali_kod_bilan_MOS():
    """⚠️ QULF: hujjatdagi qator SONI, TARTIBI, `slug` lari va HOLATLARI
    `INVENTORY_ITEMS` bilan aynan bir xil bo'lishi shart. Aks holda hujjat
    jimgina eskirardi va «inventar bor» degan yolg'on xotirjamlik qolardi."""
    qatorlar = _inventar_qatorlari()
    assert len(qatorlar) == len(INVENTORY_ITEMS) == 15
    assert [n for n, _, _ in qatorlar] == list(range(1, 16))
    assert [s for _, s, _ in qatorlar] == [i.slug for i in INVENTORY_ITEMS]
    assert [h for _, _, h in qatorlar] == [i.status for i in INVENTORY_ITEMS]


def test_inventar_hamma_SLUG_noyob():
    sluglar = [i.slug for i in INVENTORY_ITEMS]
    assert len(set(sluglar)) == len(sluglar)


def test_inventar_DALIL_xaritasi_hamma_qatorni_qamraydi():
    assert set(INVENTORY_EVIDENCE) == {i.slug for i in INVENTORY_ITEMS}


def test_inventar_KNOWN_va_SOURCE_VALIDATED_qatorlari_DALILGA_tayanadi():
    """Taxmin bilan holat yozilmasin: `KNOWN`/`SOURCE-VALIDATED` qator kamida
    bitta topilma kodiga tayanadi va o'sha kod modulda rostdan chiqariladi.

    ⚠️ NEGA «mavjud manbada shu kod BOR» deb tekshirilMAYDI: manba hozir boshqa
    agentlar tomonidan tahrirlanmoqda. Dalil XARITASI statik va barqaror; qator
    HOLATI esa snapshot va u `INVENTORY_ITEMS` izohidagi buyruq bilan qayta
    hisoblanadi.
    """
    modul = _MODUL_MANBASI
    dalilli = 0
    for item in INVENTORY_ITEMS:
        kodlar = INVENTORY_EVIDENCE[item.slug]
        if item.status == STATUS_RUNTIME_UNKNOWN:
            continue
        assert kodlar, f"{item.slug}: {item.status} qator DALILSIZ qolmasin"
        dalilli += 1
        for kod in kodlar:
            assert f'"{kod}"' in modul, f"{item.slug}: `{kod}` modulda chiqarilmaydi"
    assert dalilli >= 2, "inventar bo'shashib ketgan: dalilli qator juda kam"


def test_inventar_RUNTIME_UNKNOWN_qatorlari_KOPCHILIK():
    """1C bo'lmagan mashinada ko'pchilik savol OCHIQ qolishi NORMAL. Aks holda
    kimdir holatlarni taxmin bilan ko'targan bo'ladi."""
    ochiq = [i for i in INVENTORY_ITEMS if i.status == STATUS_RUNTIME_UNKNOWN]
    assert len(ochiq) > len(INVENTORY_ITEMS) / 2, (
        f"faqat {len(ochiq)}/{len(INVENTORY_ITEMS)} qator RUNTIME-UNKNOWN — "
        f"statik audit bunchalik ko'p narsani isbotlay olmaydi")


def test_inventar_hujjati_NIMA_ISBOTLAYDI_bolimini_ochiq_yozadi():
    matn = READINESS_DOC.read_text(encoding="utf-8")
    assert "BU HUJJAT NIMA ISBOTLAYDI va NIMA ISBOTLAMAYDI" in matn
    for taqiq in ("ishlaydi»", "kompilyatsiya qilinadi»", "runtime tasdiqlangan»"):
        assert taqiq in matn, f"taqiqlangan iboraning ochiq rad etilishi yo'q: {taqiq}"


# ── Runtime paketi shartnomasi ─────────────────────────────────────────────────────────────
def test_paket_ALTI_majburiy_azodan_iborat():
    nomlar = [n for n, _ in RUNTIME_PACKAGE_REQUIRED]
    assert nomlar == ["export.json", "metadata.json", "run_status.json",
                      "errors.json", "run_summary.md", "manifest.json"]


def test_paket_TOPLAM_azolari_bilan_NOM_TALASHMAYDI():
    """⚠️ `binos-1c-discovery-v1` to'plamining a'zolari AYNAN `status.json` va
    `summary.md` deb ataladi va ularni ADAPTER quradi. Runtime paketi shu
    nomlarni ishlatsa, bir xil nom ikki xil sxemani anglatardi."""
    from app.services.discovery_1c import REQUIRED_MEMBERS
    paket = {n for n, _ in RUNTIME_PACKAGE_REQUIRED}
    assert {"status.json", "summary.md"} <= set(REQUIRED_MEMBERS), (
        "to'plam a'zolari o'zgargan — bu test qaysi nomlarni qo'riqlashini "
        "qayta ko'rish kerak")
    assert not (paket & set(REQUIRED_MEMBERS)), (
        f"runtime paketi to'plam a'zosi bilan nom talashdi: "
        f"{sorted(paket & set(REQUIRED_MEMBERS))}")
    assert {"run_status.json", "run_summary.md"} <= paket


def test_paket_HUJJATDAGI_jadval_kod_bilan_MOS():
    matn = READINESS_DOC.read_text(encoding="utf-8")
    for nom, versiya in RUNTIME_PACKAGE_REQUIRED:
        assert f"`{nom}`" in matn, nom
        if versiya:
            assert f"`{versiya}`" in matn, versiya


def test_manifest_PROVENANS_maydonlarini_QABUL_QILMAYDI():
    """⚠️ Manifest faqat YOZILGAN BAYTLARNING sha256'si. Manba provenansi
    maydonlari metadata razvedkasidan KELIB CHIQMAYDI — yozilsa yolg'on kafolat."""
    assert MANIFEST_ALLOWED_KEYS == ("name", "bytes", "sha256")
    assert not (set(MANIFEST_ALLOWED_KEYS) & set(MANIFEST_FORBIDDEN_KEYS))
    matn = READINESS_DOC.read_text(encoding="utf-8")
    for kalit in MANIFEST_FORBIDDEN_KEYS:
        assert f"`{kalit}`" in matn, f"taqiq hujjatda yozilmagan: {kalit}"


# ── Rejimlar ───────────────────────────────────────────────────────────────────────────────
def test_rejim_DEFAULT_metadata_only():
    assert ra.DEFAULT_MODE == ra.MODE_METADATA_ONLY
    assert MODES == ("METADATA_ONLY", "APPROVED_PROBES")


@pytest.mark.parametrize("xom", [None, "", "   ", "APPROVED", "approved_probes",
                                 "PROBES", "METADATA", "А"])
def test_rejim_NOMALUM_va_BOSH_kirish_fail_safe(xom):
    """⚠️ FAIL-SAFE: noma'lum yoki bo'sh rejim HECH QACHON zondga aylanmaydi."""
    rejim, sabab = normalize_mode(xom)
    assert rejim == ra.MODE_METADATA_ONLY
    assert sabab, "fail-safe tanlov JIMGINA bo'lmasin — sabab qaytishi shart"


@pytest.mark.parametrize("xom", ["METADATA_ONLY", "APPROVED_PROBES"])
def test_rejim_ANIQ_berilgani_saqlanadi(xom):
    rejim, sabab = normalize_mode(xom)
    assert (rejim, sabab) == (xom, None)


def test_rejim_hujjatda_DEFAULT_ochiq_yozilgan():
    matn = READINESS_DOC.read_text(encoding="utf-8")
    assert "METADATA_ONLY" in matn and "APPROVED_PROBES" in matn
    assert "DEFAULT" in matn


# ── Uchlik lug'at va shartnoma o'zgarmasligi ───────────────────────────────────────────────
def test_uchlik_LUGATI_metadata_shakli_bilan_AYNAN_bir_xil():
    from app.services.discovery_1c.metadata import HIERARCHICAL
    assert set(TRISTATE_TEXTS) == set(HIERARCHICAL)


# ══════════════════════════════════════════════════════════════════════════════════════════
# O'QIY OLMAGAN MANBA HAQIDA IJOBIY HUKM YOZILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ Eng nozik nuqson shakli: audit manbani ISHONCHLI o'qiy olmaydi, lekin topilma
#    yo'qligini «toza» deb TALQIN qilib TASDIQLOVCHI hukm yozadi. Yopilmagan qo'shtirnoq
#    `code_lines` ni faylning qolganini literal deb belgilashga majbur qiladi, ya'ni
#    kompilyatsiyani yiqitadigan begona harf (`Қ`, U+049A) «literal» ichida ko'rinmay
#    qoladi. «Topilmadi» va «qaray olmadim» BIR XIL NARSA EMAS.
_BUZUQ_LITERAL = 'X = "ochildi\n' + 'Функция ЗондҚ()\n\tВозврат 1;\nКонецФункции\n'
_YOPILGAN_LITERAL = 'X = "ok";\n' + 'Функция ЗондҚ()\n\tВозврат 1;\nКонецФункции\n'
_TOZA = 'Функция Zond()\n\tВозврат 1;\nКонецФункции\n'


def test_YOPILMAGAN_literal_TOZA_degan_hukm_BERMAYDI():
    kodlar = {f.code for f in ra.audit_source(_BUZUQ_LITERAL)}
    assert "CHARSET_CLEAN" not in kodlar, (
        "o'qiy olmagan manba haqida TASDIQLOVCHI `CHARSET_CLEAN` hukmi yozildi")
    assert "CHARSET_UNREADABLE" in kodlar, "o'qib bo'lmaganligi ochiq aytilmadi"


def test_YOPILMAGAN_literal_holati_RUNTIME_UNKNOWN():
    """⚠️ Holat ham muhim: `SOURCE-VALIDATED` «statik tekshirildi» degan ma'no beradi."""
    topilma = [f for f in ra.audit_source(_BUZUQ_LITERAL) if f.code == "CHARSET_UNREADABLE"]
    assert topilma, "CHARSET_UNREADABLE topilmadi"
    assert topilma[0].status == ra.STATUS_RUNTIME_UNKNOWN


def test_literal_YOPILGAN_bolsa_begona_harf_TUTILADI():
    """Nazorat: darvoza ishlayotganini ko'rsatadi (aks holda yuqoridagi test bo'sh bo'lardi)."""
    kodlar = {f.code for f in ra.audit_source(_YOPILGAN_LITERAL)}
    assert "CHARSET_FOREIGN_LETTER" in kodlar


def test_HAQIQATAN_toza_manba_CHARSET_CLEAN_oladi():
    """⚠️ YOLG'ON IJOBIY darvozasi: fail-closed tuzatish toza manbani ayblab qo'ymasin."""
    kodlar = {f.code for f in ra.audit_source(_TOZA)}
    assert "CHARSET_CLEAN" in kodlar
    assert "CHARSET_UNREADABLE" not in kodlar
