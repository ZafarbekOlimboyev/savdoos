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


def test_manba_VERIFIED_bermaydi():
    """Yig'uvchi ishonch darajasini o'zi ko'tara olmaydi — bu BinOS tomonining qarori."""
    text = EPF_SRC.read_text(encoding="utf-8")
    for marker, _why in FORBIDDEN_MARKERS:
        assert marker not in text
    assert '"CANDIDATE"' in text


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
        '	ПотокJSON.Закрыть();',
    ])
    findings = audit_source(qonuniy + '\nRUNTIME\'DA SINALMAGAN FAQAT AJRATILGAN NUSXADA "CANDIDATE"')
    assert not findings, [f"{f.code}: {f.line}" for f in findings]


def test_audit_IZOHDAGI_chaqiruvni_ham_tutadi():
    """Izohga yashirilgan yozuv chaqiruvi ham tutiladi — keyin uni izohdan chiqarish bir qadam."""
    src = EPF_SRC.read_text(encoding="utf-8") + "\n	// Объект.Записать();\n"
    assert any(f.code == "WRITE_OBJECT" for f in audit_source(src))
