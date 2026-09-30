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


#: ⚠️ `.Текст` TAYINLASHIDA konkatenatsiya qilinishi RUXSAT ETILGAN o'zgaruvchi nomlari.
#: NEGA OQ RO'YXAT: audit o'zgaruvchi ICHIDA nima borligini bila olmaydi — `+ ПолноеИмя` va
#: `+ ТекстОтМодели` matn sifatida bir xil shakl. Shu bois kafolat NOMGA bog'landi: so'rov
#: matniga faqat AYNAN shu nomlar qo'shilishi mumkin, boshqa nom qo'shilsa audit qizil bo'ladi.
#: Bu «o'zgaruvchi xavfsiz» degani EMAS — bu «yangi manba qo'shish uchun SHU faylni tahrirlash
#: shart» degani, ya'ni yangi konkatenatsiya manbasi ko'rikdan o'tmasdan kirib kelmaydi.
#: ⚠️ CHEGARA (ochiq yozilgan): haqiqiy himoya statik auditda EMAS — u BSL tomonida, jadval
#: nomi `Метаданные.НайтиПоПолномуИмени(...)` topgan obyektning O'Z `ПолноеИмя()` sidan
#: olinishida. Audit faqat shu nomlar ro'yxatini QULFLAYDI.
QUERY_CONCAT_ALLOWED: tuple[str, ...] = ("ПолноеИмяОбъекта", "ПолноеИмя")

#: `.Текст` TAYINLASHI (taqqoslash emas): mantiqiy gap `<obyekt zanjiri>.Текст =` bilan
#: BOSHLANISHI shart. `Если Поле.Текст = ИмяПоля Тогда` gapi `Если` bilan boshlanadi, shu bois
#: bu anker unga TUSHMAYDI.
_TEXT_ASSIGN = rf"^(?:{_ID}+\s*\.\s*)+Текст\s*="

#  ⚠️ Shu bois `_TEXT_ASSIGN` `=` da TUGAYDI: undan keyingi probellar ikki qoidada ham
#     LOOKAHEAD ICHIDA hisoblanadi. NEGA: `=\s*` lookahead TASHQARISIDA qolsa, regex `\s*` ni
#     NOLGA qisqartirib probel ustida lookaheadni bajaradi va `= "ВЫБРАТЬ` satri uchun ham
#     YOLG'ON ijobiy beradi. Bu aynan shu faylda bir marta yo'l qo'yilgan xato.

#: Yozuvchi obyekt/funksiya nomlari. ⚠️ `ЗаписьJSON` va `ЗаписатьJSON` ro'yxatda YO'Q —
#: eksport AYNAN ular bilan yoziladi, ular QONUNIY.
_WRITER_NAMES = ("ЗаписьТекста", "ЗаписьДанных", "ЗаписьXML", "ЗаписатьXML",
                 "ЗаписьZipФайла", "ЗаписьHTML", "ЗаписьFastInfoset")


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: str
    why: str
    #: "line" — naqsh bitta FIZIK satrga qo'yiladi (standart);
    #: "statement" — naqsh MANTIQIY gapga qo'yiladi (ko'p satrga cho'zilgan tayinlash uchun).
    scope: str = "line"


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

    # ── Universal kraulyer bilan qo'shilgan qoidalar ───────────────────────────────────────
    # ⚠️ NEGA YANGI QOIDA KERAK BO'LDI: yig'uvchi endi ikki hujjat yozadi va zond katalogini
    #    (`probe.py`) bajaradi, ya'ni undagi fayl va kod yuzasi kengaydi. Kengaygan yuzani
    #    eski 16 qoida qamramaydi.
    Rule("COM_OBJECT_GET", rf"(?<!{_ID})ПолучитьCOMОбъект\s*\(",
         "OS COM obyektini olish — fayl tizimi va tashqi ilovaga yo'l. EXTERNAL_CONNECTION bu "
         "satrni `COMОбъект` bo'lagi bilan allaqachon tutadi; ATAYLAB takrorlangan, chunki "
         "aynan nomlangan qoida topilmani o'qiyotgan odamga nima bo'lganini aytadi"),
    Rule("RUN_APPLICATION", rf"(?<!{_ID})ЗапуститьПриложение\s*\(",
         "tashqi jarayon ishga tushirish — bajarilgan amal auditdan butunlay tashqarida qoladi"),
    Rule("COPY_FILE", rf"(?<!{_ID})КопироватьФайл\s*\(",
         "fayl nusxalash — bazaning o'zini yoki mijoz hujjatlarini ko'chirish yo'li; "
         "yig'uvchi FAQAT o'z eksportini yozadi"),
    Rule("MOVE_FILE", rf"(?<!{_ID})ПереместитьФайл\s*\(",
         "faylni ko'chirish — mijoz fayllarini joyidan olib qo'yish, o'qish emas"),
    Rule("DELETE_FILES", rf"(?<!{_ID})УдалитьФайлы\s*\(",
         "fayl o'chirish; DELETE qoidasi `Удалить(` ni tutadi, bu esa BOSHQA identifikator "
         "va u qoida tomonidan TUTILMAYDI"),
    Rule("CREATE_DIRECTORY", rf"(?<!{_ID})СоздатьКаталог\s*\(",
         "katalog yaratish — eksport operator ko'rsatgan MAVJUD bo'sh papkaga yoziladi, "
         "yig'uvchi disk tuzilmasini o'zgartirmaydi"),
    # ⚠️ NEGA KENGAYTIRILDI: bu qoida ilgari FAQAT `ЗаписьТекста` ni tutardi, lekin o'z izohida
    #    «BOSHQA YOZUVCHI OBYEKT nazoratdan chiqqan chiqish yo'li bo'lardi» deb yozilgan edi —
    #    ya'ni e'lon qilgan kafolatini BAJARMAYDI. `Новый ЗаписьДанных(...)`,
    #    `Новый ЗаписьXML`, `ЗаписатьXML(...)` va `ЗаписьZipФайла` auditdan O'TIB KETARDI.
    #    Nom ham o'zgartirildi: qoida endi bitta obyekt emas, YOZUVCHI OBYEKTLAR sinfini tutadi.
    # ⚠️ `ЗаписьJSON`/`ЗаписатьJSON` ro'yxatda ATAYLAB yo'q: eksport aynan ular bilan yoziladi.
    Rule("FOREIGN_WRITER_OBJECT", rf"(?<!{_ID})(?:{'|'.join(_WRITER_NAMES)})",
         "ikkinchi fayl yozish kanali: eksport FAQAT `ЗаписьJSON` bilan yoziladi, shu bois "
         "boshqa yozuvchi obyekt nazoratdan chiqqan chiqish yo'li bo'lardi"),
    Rule("VALUE_TO_FILE", rf"(?<!{_ID})ЗначениеВФайл\s*\(",
         "ixtiyoriy qiymatni faylga tashlash — biznes qatorlari shu yo'l bilan hujjatga "
         "tushib ketardi, ma'lumotni minimallashtirish buzilardi"),
    # ⚠️ DYNAMIC_EXEC va DYNAMIC_EVAL bu nomlarni TUTMAYDI: ularda nomdan keyin darhol `(`
    #    turishi shart, bu yerda esa `В` keladi. Ya'ni bu haqiqiy teshik edi.
    Rule("SAFE_MODE_EVAL", r"ВычислитьВБезопасномРежиме|ВыполнитьВБезопасномРежиме",
         "xavfsiz rejimda dinamik kod bajarish — «xavfsiz» so'zi auditni tiklamaydi: "
         "bajarilgan amalni oldindan bilib bo'lmaydi"),
    Rule("EXTERNAL_PROCESSING_LOAD", r"ВнешниеОбработки\s*\.|ВнешниеОтчеты\s*\.",
         "diskdan ixtiyoriy tashqi qayta ishlash yuklash — bu ixtiyoriy kod bajarish; "
         "yig'uvchining O'ZI tashqi qayta ishlash, u boshqasini yuklamaydi"),
    # ⚠️ ENG NOZIK QOIDA. `Запрос.Текст` ni literal bilan boshlash SHART: so'rov matni manbada
    #    KO'RINIB turishi kerak. O'zgaruvchidan kelgan matn (masalan modeldan kelgan satr)
    #    auditni ma'nosiz qiladi, chunki bajariladigan so'rovni manbadan o'qib bo'lmaydi.
    #
    # ⚠️ NEGA QAYTA YOZILDI. Eski naqsh `\.Текст\s*=(?!\s*\")` IKKI TOMONDAN buzuq edi:
    #    (a) TESHIK: u `=` dan keyingi BIRINCHI belgini ko'rardi, shu bois bo'sh literal
    #        (`= "" + ТекстОтМодели;`) o'tib ketardi — «literal bilan boshlandi» deb;
    #    (b) YOLG'ON IJOBIY: `Запрос.Текст =` satr oxirida qolib matn keyingi satrga
    #        tushganda (QONUNIY, ko'p satrli tayinlash) va 1C dagi `=` TAQQOSLASH ma'nosida
    #        (`Если Поле.Текст = ИмяПоля Тогда`) — ikkovi ham tutilardi.
    #    Endi naqsh MANTIQIY GAPGA qo'yiladi (ko'p satrli tayinlash birlashtiriladi) va
    #    gap boshiga ankerlanadi (taqqoslash `Если` bilan boshlanadi, anker unga tushmaydi).
    #    Lookahead `"[^"]` — literal BO'SH bo'lmasligi shart.
    Rule("QUERY_TEXT_FROM_VARIABLE", _TEXT_ASSIGN + r'(?!\s*"[^"])',
         "so'rov matni MANBADA BO'SH BO'LMAGAN literal bilan boshlanishi shart — "
         "o'zgaruvchidan yasalgan so'rovni statik audit ko'ra olmaydi",
         "statement"),
    # ⚠️ NEGA IKKINCHI QOIDA KERAK BO'LDI: literal bilan boshlanib, keyin o'zgaruvchi QO'SHILGAN
    #    so'rov (`= "ВЫБРАТЬ * ИЗ " + ТекстОтМодели;`) ham TO'LIQ dinamik — jadval nomi manbada
    #    KO'RINMAYDI. Birinchi qoida buni tuta olmaydi, chunki literal prefiksi bor.
    # ⚠️ CHEGARA, YOLG'ON KAFOLAT YOZILMAYDI: `+ ПолноеИмя` va `+ ТекстОтМодели` STATIK matn
    #    sifatida FARQ QILMAYDI. Shu bois bu qoida «o'zgaruvchi xavfsizligini» tekshirmaydi —
    #    u faqat `QUERY_CONCAT_ALLOWED` oq ro'yxatini QULFLAYDI: boshqa nom qo'shilsa audit
    #    qizil bo'ladi va odam ko'rigidan o'tishi kerak. HAQIQIY himoya BSL tomonida: jadval
    #    nomi `Метаданные.НайтиПоПолномуИмени(...)` topgan obyektning `ПолноеИмя()` sidan
    #    olinadi, kelgan matndan EMAS (`test_zond_maydon_manzilini_OBYEKT_va_YOL_ga_ajratadi`).
    Rule("QUERY_TEXT_CONCAT_SOURCE",
         _TEXT_ASSIGN + rf'[^;]*\+(?!\s*"|\s*(?:{"|".join(QUERY_CONCAT_ALLOWED)})(?!{_ID}))',
         "so'rov matniga faqat oq ro'yxatdagi metadata nomi qo'shilishi mumkin — boshqa "
         "o'zgaruvchi qo'shilsa, bajariladigan so'rovni manbadan o'qib bo'lmaydi",
         "statement"),

    # ── Zond yuzasi bilan qo'shilgan qoidalar ──────────────────────────────────────────────
    # ⚠️ NEGA YANGI QOIDA KERAK BO'LDI: yig'uvchi AYNAN shu bosqichda `Константы` kolleksiyasini
    #    kezishni BOSHLADI, ya'ni teshik YANGI ochilgan yuzada edi. `Установить(` — konstantani
    #    BAZAGA YOZISH amali, `СоздатьМенеджерЗначения()` esa unga boradigan YAGONA yo'l.
    #    O'qish (`Константы.X.Получить()`) va metadata kezish (`Метаданные.Константы`) TUTILMAYDI.
    Rule("CONSTANT_SET",
         rf"(?<!{_ID})Константы\s*\.\s*{_ID}+\s*\.\s*(?:Установить|СоздатьМенеджерЗначения)\s*\(",
         "konstantani yozish — discovery FAQAT o'qiydi; `СоздатьМенеджерЗначения` ham "
         "taqiqlangan, chunki konstantaga yozishning boshqa yo'li yo'q"),
    # ⚠️ Sozlama omboriga yozish BAZAGA yozishdir: u konfiguratsiya jadvalida saqlanadi va
    #    boshqa foydalanuvchilarning ish rejimini o'zgartirishi mumkin. O'qish (`Загрузить`)
    #    tutilmaydi — u holat o'zgartirmaydi.
    Rule("SETTINGS_STORAGE_SAVE",
         rf"(?<!{_ID})Хранилище{_ID}*Настроек\s*\.\s*Сохранить\s*\(",
         "sozlama omboriga yozish — bu ham bazaga yozish; discovery hech narsani "
         "o'zgartirmaydi"),
    # ⚠️ `ПланыОбмена...ЗарегистрироватьИзменения(` almashinuv navbatiga QATOR QO'SHADI, ya'ni
    #    mijozning boshqa integratsiyalari keyin o'zgargan obyektlarni qayta yuboradi. Bu
    #    «o'qish» emas: ta'siri discovery tugagandan KEYIN ham davom etadi.
    Rule("EXCHANGE_PLAN_REGISTER",
         rf"(?<!{_ID})(?:ЗарегистрироватьИзменения|УдалитьРегистрациюИзменений)\s*\(",
         "almashinuv rejasida o'zgarishlarni qayd etish — mijozning boshqa integratsiyalarini "
         "qo'zg'atadi, ta'siri discovery tugagach ham qoladi"),
)

#: Manbada BO'LISHI SHART bo'lgan belgilar.
REQUIRED_MARKERS: tuple[tuple[str, str], ...] = (
    ("RUNTIME'DA SINALMAGAN", "manba runtime'da sinalmagani OCHIQ yozilishi shart"),
    ("FAQAT AJRATILGAN NUSXADA", "jonli bazada ishlatmaslik ogohlantirishi shart"),
    ("binos-1c-export-v1", "yig'uvchi AYNAN eksport shartnomasini chiqarishi shart"),
    # ⚠️ IKKINCHI HUJJAT MAJBURIY. Universal kraulyer `metadata.json` ni ham yozadi; u
    #    bo'lmasa yig'uvchi yana faqat nishonlar bo'yicha ishlagan bo'lardi, ya'ni
    #    konfiguratsiyada UMUMAN nima borligi hech qachon ko'rinmasdi.
    ("binos-1c-metadata-v1", "yig'uvchi IKKINCHI hujjatni — inventarizatsiyani — ham "
                             "chiqarishi shart"),
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


#: Satr oxiridagi shu belgilar gap DAVOM ETAYOTGANINI ko'rsatadi (1C da gap `;` bilan tugaydi,
#: lekin uzun tayinlash bir necha satrga bo'linishi mumkin).
_CONTINUES = ("=", "+", ",", "(", ".")


def _statements(lines: list[str]) -> list[tuple[int, str]]:
    """Fizik satrlarni MANTIQIY gaplarga qo'shadi: (birinchi satr raqami, gap matni).

    ⚠️ NEGA KERAK: `Запрос.Текст =` satr oxirida qolib, so'rov matni keyingi satrga tushishi
    QONUNIY naqsh. Bitta FIZIK satrni ko'radigan qoida uni «o'zgaruvchidan kelgan so'rov» deb
    YOLG'ON tutardi, ya'ni uzun so'rovni ikki satrga bo'lgan odamni jazolardi.
    ⚠️ BU TO'LIQ PARSER EMAS: satr ichidagi izoh va satr literalidagi `;` hisobga olinmaydi.
    Bu yerda yetarli, chunki qoidalar gap BOSHIGA ankerlangan — keraksiz qo'shilish topilmani
    yo'qotmaydi, faqat gap matnini uzaytiradi."""
    natija: list[tuple[int, str]] = []
    bufer = ""
    boshi = 0
    for i, xom in enumerate(lines, 1):
        satr = xom.strip()
        if bufer:
            bufer = f"{bufer} {satr}"
        else:
            bufer, boshi = satr, i
        if satr.endswith(_CONTINUES) and not satr.startswith("//"):
            continue          # gap tugamagan — keyingi satr davomi
        natija.append((boshi, bufer))
        bufer = ""
    if bufer:
        natija.append((boshi, bufer))
    return natija


def audit_source(text: str) -> list[Finding]:
    """Ekstraktor manbasini tekshiradi. Bo'sh ro'yxat = darvozadan o'tdi.

    Izohlar OLIB TASHLANMAYDI: izohda ham `Записать(` yozilmasin, chunki keyin kimdir uni
    izohdan chiqarib qo'yishi mumkin va diff bexosdan «zararsiz» ko'rinadi."""
    findings: list[Finding] = []
    lines = text.splitlines()
    statements = _statements(lines)

    for rule in RULES:
        rx = re.compile(rule.pattern)
        # `statement` doirasidagi qoida MANTIQIY gapni ko'radi (gap matni allaqachon
        # trimlangan, shu bois `^` ankeri ishlaydi); qolganlari FIZIK satrni.
        birliklar = statements if rule.scope == "statement" else list(enumerate(lines, 1))
        for i, birlik in birliklar:
            if rx.search(birlik):
                findings.append(Finding(rule.code, i, birlik.strip()[:120], rule.why))

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
