# -*- coding: utf-8 -*-
"""Ekstraktor MANBASINING statik auditi — 1C runtime'isiz bajariladigan YAGONA darvoza.

NEGA BU BOR. Yig'uvchi 1C ICHIDA ishlaydi va u yerda to'liq huquqqa ega bo'ladi (xavfsiz
rejim fayl yozishni taqiqlaydi, ya'ni yig'uvchi oddiy rejimda ishlashi kerak). Bizda 1C
platformasi yo'q, demak manbani KOMPILYATSIYA qilib yoki ishlatib tekshira olmaymiz.
Tekshira oladigan narsamiz — MANBA MATNI: unda yozuv chaqiruvi umuman bo'lmasligi kerak.

⚠️ BU NIMANI ISBOTLAYDI: shu fayl ko'rsatilgan taqiqlangan chaqiruvlarni O'Z ICHIGA OLMAYDI.
⚠️ BU NIMANI ISBOTLAMAYDI: modul kompilyatsiya bo'lishini, to'g'ri ishlashini yoki 1C'da
   umuman yurishini. Uni faqat 1C mutaxassisi Konfiguratorda tekshira oladi.

Audit CI'da ishlaydi (`tests/test_discovery_1c_epf_source.py`), ya'ni taqiq ro'yxati hujjat
emas, DARVOZA: kimdir manbaga `Записать()` qo'shsa, to'plam qizil bo'ladi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Identifikator belgisi — qoidalar `Записать(` ni `ЗаписатьJSON(` dan ajratishi uchun.
_ID = r"[А-Яа-яЁёA-Za-z0-9_]"


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: str
    why: str


#: ⚠️ Har qoida AYNI chaqiruvni tutadi: nom + darhol `(`. Shu bois `ЗаписатьJSON(` va
#: `ЗаписатьРезультат(` TUTILMAYDI — ular boshqa identifikator.
RULES: tuple[Rule, ...] = (
    Rule("WRITE_OBJECT", rf"(?<!{_ID})Записать\s*\(",
         "obyektni bazaga yozish — discovery FAQAT o'qiydi"),
    Rule("WRITE_RECORDSET", rf"(?<!{_ID})ЗаписатьНаборЗаписей\s*\(",
         "registr yozuvlar to'plamini yozish"),
    Rule("POST_DOCUMENT", rf"(?<!{_ID})Провести\s*\(",
         "hujjatni o'tkazish — registrlarni o'zgartiradi"),
    Rule("UNPOST_DOCUMENT", rf"(?<!{_ID})ОтменитьПроведение\s*\(",
         "hujjat o'tkazishini bekor qilish"),
    Rule("DELETE", rf"(?<!{_ID})Удалить\s*\(",
         "o'chirish — massiv elementini o'chirish uchun ham ishlatilmasin, ikkisi matnda farq qilmaydi"),
    Rule("DELETE_DIRECTLY", rf"(?<!{_ID})УдалитьОбъекты\s*\(",
         "obyektlarni to'g'ridan-to'g'ri o'chirish"),
    Rule("EXCLUSIVE_MODE", rf"(?<!{_ID})УстановитьМонопольныйРежим\s*\(",
         "monopol rejim — jonli bazani bloklaydi, nusxada ham keraksiz"),
    Rule("PRIVILEGED_MODE", rf"(?<!{_ID})УстановитьПривилегированныйРежим\s*\(",
         "huquq tekshiruvini o'chirish — discovery uchun kerak emas"),
    Rule("TXN_BEGIN", rf"(?<!{_ID})НачатьТранзакцию\s*\(",
         "tranzaksiya — faqat yozuv uchun kerak bo'ladi"),
    Rule("TXN_COMMIT", rf"(?<!{_ID})ЗафиксироватьТранзакцию\s*\(", "tranzaksiyani fiksatsiya"),
    Rule("TXN_ROLLBACK", rf"(?<!{_ID})ОтменитьТранзакцию\s*\(", "tranzaksiyani bekor qilish"),
    Rule("FILL_PROCESSING", rf"(?<!{_ID})ВыполнитьОбработкуЗаполнения\s*\(",
         "to'ldirish ishlovi — obyekt holatini o'zgartiradi"),
    # ⚠️ `Запрос.Выполнить()` QONUNIY va SHART. Taqiq faqat NUQTASIZ `Выполнить(` ga —
    #    ya'ni dinamik kod bajarilishiga.
    Rule("DYNAMIC_EXEC", rf"(?<![.{_ID[1:-1]}])Выполнить\s*\(",
         "dinamik kod bajarish — auditni ma'nosiz qiladi"),
    Rule("DYNAMIC_EVAL", rf"(?<!{_ID})Вычислить\s*\(",
         "dinamik ifoda hisoblash — auditni ma'nosiz qiladi"),
    # Tarozi: 1C birinchi yuklashda YANGI PLU'larni O'Z registriga YOZISHI mumkin.
    Rule("SCALE_EXCHANGE", r"ОбменСВесами|ВыгрузитьВВесы|ЗагрузитьИзВесов|ПередатьВВесы"
                          r"|ЗаписатьPLU|ПолучитьМаксимальныйPLU",
         "tarozi almashinuvi — YOZUV amali, tarozi xotirasini o'zgartirishi mumkin"),
    Rule("EXTERNAL_CONNECTION", r"COMОбъект|V83\.ComConnector|V82\.ComConnector",
         "tashqi ulanish — nusxa ajratilgan bo'lishi kerak"),
)

#: Manbada BO'LISHI SHART bo'lgan belgilar.
REQUIRED_MARKERS: tuple[tuple[str, str], ...] = (
    ("RUNTIME'DA SINALMAGAN", "manba runtime'da sinalmagani OCHIQ yozilishi shart"),
    ("FAQAT AJRATILGAN NUSXADA", "jonli bazada ishlatmaslik ogohlantirishi shart"),
    ("binos-1c-export-v1", "yig'uvchi AYNAN eksport shartnomasini chiqarishi shart"),
)

#: Manbada BO'LMASLIGI SHART bo'lgan belgilar.
#: ⚠️ Yig'uvchi ishonch darajasini UMUMAN bermaydi — u faqat DALIL yozadi. Darajani adapter
#: hisoblaydi va u CANDIDATE dan oshmaydi. Shu bois manbada `confidence` ham, `VERIFIED` ham
#: bo'lmasligi kerak: o'zini o'zi tasdiqlaydigan yig'uvchi butun ishonch qoidasini ma'nosiz qiladi.
FORBIDDEN_MARKERS: tuple[tuple[str, str], ...] = (
    ('"VERIFIED"', "yig'uvchi HECH QACHON VERIFIED bera olmaydi — bu BinOS tomonining qarori"),
    ('"CANDIDATE"', "yig'uvchi darajani UMUMAN bermaydi — faqat dalil yozadi"),
    ('"confidence"', "daraja maydoni eksportda YO'Q: uni adapter hisoblaydi"),
)


@dataclass(frozen=True)
class Finding:
    code: str
    line_no: int
    line: str
    why: str


def audit_source(text: str) -> list[Finding]:
    """Ekstraktor manbasini tekshiradi. Bo'sh ro'yxat = darvozadan o'tdi.

    Izohlar OLIB TASHLANMAYDI: izohda ham `Записать(` yozilmasin, chunki keyin kimdir uni
    izohdan chiqarib qo'yishi mumkin va diff bexosdan «zararsiz» ko'rinadi."""
    findings: list[Finding] = []
    lines = text.splitlines()

    for rule in RULES:
        rx = re.compile(rule.pattern)
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                findings.append(Finding(rule.code, i, line.strip()[:120], rule.why))

    for marker, why in REQUIRED_MARKERS:
        if marker not in text:
            findings.append(Finding("MISSING_MARKER", 0, marker, why))

    for marker, why in FORBIDDEN_MARKERS:
        for i, line in enumerate(lines, 1):
            if marker in line:
                findings.append(Finding("FORBIDDEN_MARKER", i, line.strip()[:120], why))

    return findings


def audit_file(path) -> list[Finding]:
    import pathlib
    return audit_source(pathlib.Path(path).read_text(encoding="utf-8"))
