# -*- coding: utf-8 -*-
"""Ekstraktor manbasining REAL 1C RUNTIME nuqtai nazaridan STATIK auditi.

`epf_audit.py` bilan ADASHTIRMANG. U XAVFSIZLIKNI tekshiradi: manbada yozuv amali
bo'lmasligini. Bu modul BOSHQA savolga javob berad: manba REAL 1C mashinasida ishga
tushishga QANCHALIK tayyor va qaysi joyi runtime'da hal qilinadi.

⚠️ BU MODUL HECH NARSANI ISBOTLAMAYDI. Bizda 1C:Enterprise platformasi YO'Q, demak
   manbani kompilyatsiya qilib yoki ishlatib ko'rish imkoniyati YO'Q. Bu modul faqat
   MATNNI ko'radi. Shu bois:
     · «kompilyatsiya qilinadi», «ishlaydi», «runtime tasdiqlangan» degan da'vo
       bu faylda ham, uning topilmalarida ham YO'Q;
     · matn bilan isbotlanmagan hamma narsa `RUNTIME-UNKNOWN` deb belgilanadi.

TOPILMA HOLATLARI (uchtasi, aralashtirilmaydi):
  · `KNOWN`            — MATN BILAN ISBOTLANGAN fakt: manbani o'qib aynan shu xulosaga
                         kelish mumkin (muvozanatsiz blok, begona harf, kafolatlanmagan
                         `Закрыть()`). Bu — nuqson yoki matn majburlagan xatti-harakat.
  · `SOURCE-VALIDATED` — tekshiruv MANBA MATNIDA bajarildi va talab QONDIRILDI. Bu
                         «runtime'da ishlaydi» degani EMAS, «matnda buzilmagan» degani.
  · `RUNTIME-UNKNOWN`  — kuzatilgan narsa matn fakti, lekin u NUQSONMI yoki yo'qmi —
                         faqat real 1C da hal qilinadi (platforma versiyasi, huquqlar,
                         fayl tizimi, kompilyator).

⚠️ QAMROV CHEGARASI OCHIQ YOZILADI: bu modul BSL PARSERI EMAS. U izoh va satr
   literallarini o'chirib (`code_lines`), keyin naqsh va sanoq bilan ishlaydi. Shu bois
   u sintaksis to'g'riligini AYTA OLMAYDI — faqat bir nechta MAJBURIY invariantni
   (belgi to'plami, blok muvozanati) tekshiradi.

Foydalanish:
    findings = audit_source(matn)          # hamma tekshiruv
    findings = check_json_writer_usage(m)  # bittasi

Inventar (`integrations/1c/RUNTIME_READINESS.md`) shu faylning `INVENTORY_ITEMS`
ro'yxatiga QULFLANGAN: hujjatdagi qator soni va identifikatorlari kod bilan mos
kelishini test majburlaydi (`tests/test_discovery_1c_runtime_audit.py`).
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

# ── Holatlar ───────────────────────────────────────────────────────────────────────────────
STATUS_KNOWN = "KNOWN"
STATUS_SOURCE_VALIDATED = "SOURCE-VALIDATED"
STATUS_RUNTIME_UNKNOWN = "RUNTIME-UNKNOWN"
FINDING_STATUSES = (STATUS_KNOWN, STATUS_SOURCE_VALIDATED, STATUS_RUNTIME_UNKNOWN)


@dataclass(frozen=True)
class Finding:
    """Bitta kuzatuv. `line_no = 0` — butun faylga tegishli topilma (satri yo'q)."""

    code: str
    line_no: int
    line: str
    why: str
    status: str


# ── MATNNI KOD QISMIGA KELTIRISH ───────────────────────────────────────────────────────────
#: Rus kirillicha harflar — 1C identifikatorida RUXSAT ETILGAN YAGONA kirill to'plami.
#: ⚠️ `Ё`/`ё` ham bor: platforma ularni identifikatorda qabul qiladi.
_RU_CYRILLIC = frozenset(
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
)

#: Kirill bloki: bu oraliqdagi, lekin rus to'plamida BO'LMAGAN harf — begona alifbo
#: (qozoq `Қ`, o'zbek kirilli `Ў`, ukrain `і` va boshqalar).
_CYRILLIC_LO = "\u0400"
_CYRILLIC_HI = "\u04ff"


def code_lines(text: str, strip_literals: bool = True) -> list[str]:
    """Izoh (va so'rovga ko'ra satr literallari) OLIB TASHLANGAN satrlar.

    Uzunlik va tartib SAQLANADI: har olib tashlangan belgi probel bilan
    almashtiriladi, ya'ni satr raqami ham, ustun ham o'zgarmaydi — topilmadagi satr
    raqami XOM manbaga to'g'ri keladi.

    ⚠️ `strip_literals=False` KERAK BO'LADIGAN joylar: tekshiruv literalning
       MAZMUNINI ko'rishi kerak bo'lganda (`ОткрытьФайл(…, "UTF-8", …)`,
       `ОтметитьРаздел(…, "ok")`, `КоллекцияМетаданных("ПланыСчетов", …)`). Bunda
       izoh HAMON olib tashlanadi: izohda eslangan nom KOD emas, ya'ni kafolat
       bermaydi.

    ⚠️ ISBOTLAYDI: qaytgan satrlarda `//` izohi va `"..."` literali ichidagi matn YO'Q.
    ⚠️ ISBOTLAMAYDI: bu BSL lekseri emas. Ko'p satrli literal `"` juftligi bilan
       kuzatiladi (1C da aynan shunday), lekin manbada YOPILMAGAN qo'shtirnoq bo'lsa
       fayl oxirigacha literal deb hisoblanadi — bu holda tekshiruvlar KAMROQ topadi,
       ko'proq emas (fail-quiet, fail-loud emas). Shu bois muvozanat tekshiruvi ham
       XOM matn ustida QAYTA sanaladi (`check_balanced_blocks` izohiga qarang).
    """
    natija: list[str] = []
    literalda = False
    for xom in text.splitlines():
        bufer: list[str] = []
        i = 0
        uzunlik = len(xom)
        while i < uzunlik:
            belgi = xom[i]
            if literalda:
                if belgi == '"':
                    if i + 1 < uzunlik and xom[i + 1] == '"':
                        bufer.append('""' if not strip_literals else "  ")
                        i += 2
                        continue
                    literalda = False
                    bufer.append('"')
                    i += 1
                    continue
                bufer.append(" " if strip_literals else belgi)
                i += 1
                continue
            if belgi == '"':
                literalda = True
                bufer.append('"')
                i += 1
                continue
            if belgi == "/" and i + 1 < uzunlik and xom[i + 1] == "/":
                bufer.append(" " * (uzunlik - i))
                break
            bufer.append(belgi)
            i += 1
        natija.append("".join(bufer))
    return natija


#: 1C tilining kalit so'zlari va preprotsessor atamalari — global API yuzasiga KIRMAYDI.
_KEYWORDS = frozenset((
    "Процедура", "КонецПроцедуры", "Функция", "КонецФункции", "Перем", "Экспорт", "Знач",
    "Если", "Тогда", "ИначеЕсли", "Иначе", "КонецЕсли",
    "Для", "Каждого", "Из", "По", "Цикл", "КонецЦикла", "Пока",
    "Попытка", "Исключение", "КонецПопытки", "ВызватьИсключение",
    "Возврат", "Продолжить", "Прервать", "Новый", "Перейти",
    "Неопределено", "Истина", "Ложь", "Null", "И", "Или", "Не",
    "Область", "КонецОбласти",                       # preprotsessor `#Область`
))

#: 1C:Enterprise 8.3 da MAVJUDLIGI hujjatlashtirilgan deb HISOBLANADIGAN global nomlar.
#:
#: ⚠️⚠️ BU RO'YXAT QO'LDA YOZILGAN BILIM, platformadan olingan emas. Undan kelib
#:      chiqadigan YAGONA xulosa: «bu nom bizga tanish». U:
#:        · nomning shu platforma VERSIYASIDA borligini ISBOTLAMAYDI;
#:        · nom TO'G'RI ishlatilganini (argumentlar, kontekst, qaytish turi)
#:          ISBOTLAMAYDI;
#:        · nom shu KONTEKSTDA (mijoz/server, oddiy/boshqariladigan ilova)
#:          chaqirilishi mumkinligini ISBOTLAMAYDI.
#:      Shu bois `check_api_surface` tanish nom uchun `SOURCE-VALIDATED` emas, HECH
#:      QANDAY topilma bermaydi — «tanish» hech qanday kafolat bermaydi.
KNOWN_GLOBAL_API: frozenset[str] = frozenset((
    # global funksiyalar
    "ТекущаяДата", "Формат", "Строка", "Число", "Дата", "Цел", "Окр", "Мин", "Макс",
    "СтрНайти", "СтрЗаменить", "СтрДлина", "СтрРазделить", "СтрСоединить",
    "ВРег", "НРег", "ТРег", "Лев", "Прав", "Сред", "СокрЛП", "СокрЛ", "СокрП",
    "ПустаяСтрока", "ЗначениеЗаполнено", "Тип", "ТипЗнч",
    "ОписаниеОшибки", "ИнформацияОбОшибке",
    "СтрокаСоединенияИнформационнойБазы",
    "СмещениеСтандартногоВремени", "ЧасовойПоясСеанса",
    "ЗаписатьJSON", "ПрочитатьJSON", "ОбъединитьПути",
    "ПолучитьHexСтрокуИзДвоичныхДанных", "ПолучитьДвоичныеДанныеИзФайла",
    "ИмяКлиентскогоПриложения", "КодЛокализацииИнформационнойБазы",
    "КонфигурацияИзменена",
    # global obyekt
    "Метаданные",
    # `Новый` bilan quriladigan turlar
    "Массив", "Структура", "Соответствие", "СписокЗначений", "ТаблицаЗначений",
    "Запрос", "ЗаписьJSON", "ПараметрыЗаписиJSON", "СистемнаяИнформация",
    "ОписаниеТипов", "ХешированиеДанных", "ДвоичныеДанные", "Файл",
    # tizim sanab o'tilganlari
    "ПереносСтрокJSON", "ХешФункция", "Символы",
    "РежимЗапускаКлиентскогоПриложения",
))

#: `Метаданные` dan boshlanadigan, BIZGA TANISH a'zo zanjirlari.
#: ⚠️ Yuqoridagi ogohlantirish bu ro'yxatga ham TO'LIQ tegishli: «tanish» ≠ «bor» ≠
#:    «to'g'ri ishlatilgan».
#: ⚠️ `Метаданные.СвойстваОбъектов.*` shoxi ATAYLAB ro'yxatga KIRITILMAGAN: bu
#:    sanab o'tilgan qiymatlar (`ВидРегистраНакопления`,
#:    `ИспользованиеОбщегоРеквизита`) platforma versiyalari orasida eng ko'p
#:    o'zgargan joy va menda ularni tekshiradigan platforma YO'Q. Ularni «tanish»
#:    deb yozish — isbotlanmagan da'vo bo'lardi, shu bois ular
#:    `API_NAME_UNVERIFIED` bo'lib chiqadi va inventarning metadata API qatoriga
#:    boradi.
KNOWN_METADATA_PATHS: frozenset[str] = frozenset((
    "Метаданные.Имя",
    "Метаданные.Версия",
    "Метаданные.НайтиПоПолномуИмени",
    "Метаданные.НайтиПоТипу",
))

_IDENT = r"[^\W\d]\w*"
_IDENT_RE = re.compile(_IDENT)
_PROC_START_RE = re.compile(rf"^\s*(?:Процедура|Функция)\s+({_IDENT})\s*\((?P<args>[^)]*)\)")
_PROC_END_RE = re.compile(r"^\s*(?:КонецПроцедуры|КонецФункции)\b")


@dataclass(frozen=True)
class Procedure:
    """Manbadagi bitta protsedura/funksiya: nomi, chegaralari, eksportmi."""

    name: str
    params: tuple[str, ...]
    start: int              # 1-dan boshlangan satr raqami (`Процедура`/`Функция` satri)
    end: int                # `КонецПроцедуры`/`КонецФункции` satri
    exported: bool
    body: tuple[str, ...]   # KOD satrlari (izoh/literal o'chirilgan), start+1 .. end-1


def procedures(kod: list[str]) -> list[Procedure]:
    """Manbadagi protsedura/funksiyalarni ajratadi.

    ⚠️ ISBOTLAYDI: `Процедура`/`Функция` … `КонецПроцедуры`/`КонецФункции` juftlari
       matnda qayerda turganini.
    ⚠️ ISBOTLAMAYDI: ular kompilyatsiya bo'lishini. Argument ro'yxati BIR SATRDA
       yopilmasa (`(` va `)` boshqa satrlarda), u protsedura `params` si BO'SH
       bo'ladi — bu yerda u faqat «mahalliy nom» ro'yxati uchun ishlatiladi, ya'ni
       natijada API yuzasi KENGROQ ko'rinadi (ko'proq noma'lum nom), kamroq emas.
    """
    natija: list[Procedure] = []
    joriy: tuple[str, tuple[str, ...], int, bool] | None = None
    for i, satr in enumerate(kod, 1):
        bosh = _PROC_START_RE.match(satr)
        if bosh is not None and joriy is None:
            params = tuple(
                m.group(0) for bolak in bosh.group("args").split(",")
                #: ⚠️ `Знач` — KALIT SO'Z, oddiy almashtirish emas: `.replace("Знач", …)`
                #:    `ОписаниеТипаЗначения` nomining ICHIDAN bo'lak yulib olib
                #:    parametrni `ОписаниеТипа` deb qayd etardi va haqiqiy parametr
                #:    «noma'lum global nom» bo'lib chiqardi. Bu TOPILGAN xato.
                for m in [_IDENT_RE.search(re.sub(r"^\s*Знач(?!\w)", " ", bolak))] if m
            )
            #: ⚠️ `Экспорт` FAQAT yopiluvchi qavsdan KEYIN izlanadi: aks holda
            #:    `Функция ЗаметкиЭкспорта()` (nom ichida) va
            #:    `Процедура ВыгрузитьВФайл(…, Экспорт)` (PARAMETR nomi) ham
            #:    «eksport qilingan» bo'lib ko'rinardi. Ikkovi ham TOPILGAN xato.
            quyruq = satr[bosh.end():]
            eksport = re.search(r"(?<!\w)Экспорт(?!\w)", quyruq) is not None
            joriy = (bosh.group(1), params, i, eksport)
            continue
        if joriy is not None and _PROC_END_RE.match(satr):
            nom, params, boshi, eksport = joriy
            natija.append(Procedure(nom, params, boshi, i, eksport, tuple(kod[boshi:i - 1])))
            joriy = None
    return natija


def _local_names(kod: list[str], proclar: list[Procedure]) -> set[str]:
    """Manbada E'LON QILINGAN nomlar: modul o'zgaruvchilari, protsedura nomlari,
    parametrlar, tayinlash chap tomonlari va sikl o'zgaruvchilari."""
    nomlar: set[str] = set()
    for p in proclar:
        nomlar.add(p.name)
        nomlar.update(p.params)
    for satr in kod:
        perem = re.match(r"^\s*Перем\s+(.*)$", satr)
        if perem:
            nomlar.update(m.group(0) for m in _IDENT_RE.finditer(perem.group(1)))
        tayin = re.match(rf"^\s*({_IDENT})\s*=[^=]", satr)
        if tayin:
            nomlar.add(tayin.group(1))
        for naqsh in (rf"Для\s+Каждого\s+({_IDENT})\s+Из\b", rf"Для\s+({_IDENT})\s*="):
            m = re.search(naqsh, satr)
            if m:
                nomlar.add(m.group(1))
    return nomlar


# ── 1. BELGI TO'PLAMI ──────────────────────────────────────────────────────────────────────
def check_identifier_charset(text: str) -> list[Finding]:
    """Kod qismidagi identifikatorlar faqat rus kirill + lotin + raqam + `_` dan iboratmi.

    ⚠️ ISBOTLAYDI: kod qismida (izoh va satr literallari TASHQARIDA) rus kirill
       to'plamiga KIRMAYDIGAN kirill harfi bor yoki yo'qligini — bu MATN FAKTI, shu
       bois topilma `KNOWN`. Shuningdek kirill va KICHIK lotin harflari BIR
       identifikatorda aralashganini (gomoglif tuzog'i: `о`/`o`, `а`/`a`, `р`/`p`).
    ⚠️ ISBOTLAMAYDI: platforma aynan shu harfni rad etishini. Bu yerdagi qat'iylik
       ATAYLAB PLATFORMADAN QAT'IYROQ: begona alifbo harfi ko'z bilan farq
       qilinmaydi va identifikatorni ikki xil yozishga olib keladi — ya'ni «nomi
       to'g'ri, lekin chaqiruv topilmadi» degan, izlash mumkin bo'lmagan xato.

    ⚠️ AKRONIM ISTISNOSI: BO'LIB-BO'LIB yozilgan BOSH HARFLI lotin bo'lagi
       (`ЗаписьJSON`, `ВСтрокуISO`) QONUNIY — platforma nomlarining o'zi shunday.
       Faqat KICHIK lotin harfi aralashgani tutiladi, chunki gomogliflar aynan
       kichik harflarda uchraydi.
    """
    findings: list[Finding] = []
    for i, satr in enumerate(code_lines(text), 1):
        for belgi in satr:
            if _CYRILLIC_LO <= belgi <= _CYRILLIC_HI and belgi not in _RU_CYRILLIC:
                findings.append(Finding(
                    "CHARSET_FOREIGN_LETTER", i, satr.strip()[:120],
                    f"kod qismida rus kirill to'plamidan TASHQARIDAGI harf: "
                    f"{belgi!r} (U+{ord(belgi):04X}) — identifikatorni ko'z bilan "
                    f"farq qilinmaydigan qilib ikkiga bo'ladi",
                    STATUS_KNOWN,
                ))
                break
        for m in _IDENT_RE.finditer(satr):
            token = m.group(0)
            if not any(b in _RU_CYRILLIC for b in token):
                continue
            for lotin in re.findall(r"[A-Za-z]+", token):
                #: ⚠️ RUXSAT ETILGAN LOTIN BO'LAGI: to'liq BOSH HARFLI akronim
                #:    (`JSON`, `ISO`) yoki BOSH HARF bilan boshlangan so'z (`Hex`).
                #:    Ikkinchisi KERAK: platformaning O'ZIDA shunday nomlar bor —
                #:    `ПолучитьHexСтрокуИзДвоичныхДанных`. Uni tutish YOLG'ON
                #:    IJOBIY edi va bu TOPILGAN xato.
                #: ⚠️ Gomoglif esa aynan shu qolipga TUSHMAYDI: `Запрoс` dagi `o`
                #:    va `Потокjson` dagi `json` — kichik harfdan boshlanadi.
                if re.fullmatch(r"[A-Z]+|[A-Z][a-z]+", lotin):
                    continue
                findings.append(Finding(
                    "CHARSET_MIXED_SCRIPT", i, satr.strip()[:120],
                    f"`{token}` ichida `{lotin}` — kirill bilan aralashgan, BOSH "
                    f"HARFSIZ lotin bo'lagi; gomoglif (о/o, а/a, е/e, р/p, с/c, х/x) "
                    f"ko'z bilan farq qilinmaydi",
                    STATUS_KNOWN,
                ))
                break
    if not findings:
        # ⚠️ FAIL-CLOSED: «topilma yo'q» ni «toza» deb TALQIN QILMAYMIZ, agar manbani
        #    ishonchli o'qiy olmagan bo'lsak. Yopilmagan qo'shtirnoq `code_lines` ni
        #    faylning qolgan qismini LITERAL deb belgilashga majbur qiladi, ya'ni
        #    begona harf o'sha «literal» ichida KO'RINMAY qoladi. Ilgari shu holatda
        #    `CHARSET_CLEAN` + SOURCE-VALIDATED chiqardi — audit O'QIY OLMAGAN manba
        #    haqida TASDIQLOVCHI hukm yozardi, va bu tekshiruvning ma'nosini teskariga
        #    aylantiradi.
        o_qilmadi = [f for f in literal_defects(text) if f.code == "LITERAL_UNTERMINATED"]
        if o_qilmadi:
            findings.append(Finding(
                "CHARSET_UNREADABLE", o_qilmadi[0].line_no, o_qilmadi[0].line,
                "belgi to'plami TEKSHIRILMADI: manbada yopilmagan satr literali bor, shu "
                "bois kod qismi ishonchli ajratilmaydi — «topilmadi» degan xulosa "
                "CHIQARILMAYDI (avval literalni yoping)",
                STATUS_RUNTIME_UNKNOWN,
            ))
        else:
            findings.append(Finding(
                "CHARSET_CLEAN", 0, "",
                "kod qismida begona alifbo harfi va kirill/kichik-lotin aralashmasi "
                "TOPILMADI — bu SINTAKSIS to'g'ri degani EMAS, faqat belgi to'plami toza",
                STATUS_SOURCE_VALIDATED,
            ))
    return findings


# ── 2. BLOK MUVOZANATI ─────────────────────────────────────────────────────────────────────
#: (ochuvchi, yopuvchi) juftlari. ⚠️ `#Область` — preprotsessor, `#` bilan.
BLOCK_PAIRS: tuple[tuple[str, str], ...] = (
    ("Процедура", "КонецПроцедуры"),
    ("Функция", "КонецФункции"),
    ("Если", "КонецЕсли"),
    ("Цикл", "КонецЦикла"),
    ("Попытка", "КонецПопытки"),
    ("#Область", "#КонецОбласти"),
)


def _block_re(so_z: str) -> re.Pattern[str]:
    """Blok kalit so'zi uchun naqsh. `#` bilan boshlanadigani preprotsessor."""
    if so_z.startswith("#"):
        return re.compile(rf"#\s*{so_z[1:]}(?!\w)")
    #: ⚠️ `(?<![\w#])`: `ИначеЕсли` dagi `Если` ni ham, preprotsessor `#Если` ni ham
    #:    TUTMAYDI. Ikkinchisi muhim: `#Если`/`#КонецЕсли` oddiy `Если` bilan bir
    #:    hisobga qo'shilsa muvozanat YOLG'ON buziq ko'rinardi.
    return re.compile(rf"(?<![\w#]){so_z}(?!\w)")


def literal_defects(text: str) -> list[Finding]:
    """Satr literallarining YOPILISHI: BSL qoidasi bo'yicha.

    ⚠️ BSL da literal ichidagi qo'shtirnoq IKKI MARTA yoziladi (`""`), teskari
       chiziq bilan qochirilMAYDI. Shu bois `\\"` — literalni SHU YERDA yopadi va
       teskari chiziqni MAZMUN sifatida qoldiradi: satrning qolgan qismi KODGA
       aylanib qoladi. Bu odatda JSON/Python qochirishi ko'chirib yozilganda
       bo'ladi va MANBANI KOMPILYATSIYADAN CHIQARADI.

    ⚠️ ISBOTLAYDI: literal ICHIDA `\\"` yozilganini va fayl oxirida literal ochiq
       qolganini. Ikkisi ham MATN FAKTI — shu bois `KNOWN`.
    ⚠️ ISBOTLAMAYDI: platformaning xato matnini yoki qolgan sintaksisni.
    """
    findings: list[Finding] = []
    literalda = False
    ochilgan_satr = 0
    satrlar = text.splitlines()
    for i, xom in enumerate(satrlar, 1):
        j = 0
        n = len(xom)
        while j < n:
            belgi = xom[j]
            if literalda:
                if belgi == "\\" and j + 1 < n and xom[j + 1] == '"':
                    findings.append(Finding(
                        "LITERAL_BACKSLASH_QUOTE", i, xom.strip()[:120],
                        "literal ichida `\\\"` — BSL da qo'shtirnoq `\"\"` bilan "
                        "yoziladi, teskari chiziq qochirmaydi: literal SHU YERDA "
                        "yopiladi va satrning qolgani KODGA aylanadi",
                        STATUS_KNOWN,
                    ))
                    j += 2
                    continue
                if belgi == '"':
                    if j + 1 < n and xom[j + 1] == '"':
                        j += 2
                        continue
                    literalda = False
                j += 1
                continue
            if belgi == '"':
                literalda = True
                ochilgan_satr = i
                j += 1
                continue
            if belgi == "/" and j + 1 < n and xom[j + 1] == "/":
                break
            j += 1
    if literalda:
        findings.append(Finding(
            "LITERAL_UNTERMINATED", ochilgan_satr,
            satrlar[ochilgan_satr - 1].strip()[:120] if ochilgan_satr else "",
            "satr literali fayl oxirigacha yopilmagan — modul kompilyatsiya bo'lmaydi",
            STATUS_KNOWN,
        ))
    return findings


def check_balanced_blocks(text: str) -> list[Finding]:
    """`Процедура`/`Функция`/`Если`/`Цикл`/`Попытка`/`#Область` juftlari muvozanatda mi.

    ⚠️ ISBOTLAYDI: har juft uchun ochuvchi va yopuvchi kalit so'zlarning SONI teng
       ekanini va hech qaysi yopuvchi o'zining ochuvchisidan OLDIN kelmaganini.
       Bu MATN FAKTI — shu bois buzilishi `KNOWN`.
    ⚠️ ISBOTLAMAYDI: modul kompilyatsiya bo'lishini. Muvozanat — sintaksisning
       ZARURIY sharti, YETARLI sharti EMAS: `Иначе` ning noto'g'ri joyi, tushib
       qolgan `Тогда`, yopilmagan qavs — hammasi muvozanatni buzmaydi.
    ⚠️ Bir satrga sig'gan blok (`Если X Тогда Y; КонецЕсли;`) ham to'g'ri sanaladi,
       chunki sanoq SATRGA emas, KALIT SO'ZGA bog'langan.

    ⚠️ BU TEKSHIRUV SATR LITERALLARINING YOPILISHINI HAM QAMRAYDI
       (`literal_defects`). NEGA BIRGA: ikkisi ham kompilyatsiyaning ZARURIY
       matn sharti va ikkisi ham PARSERSIZ tekshiriladi; bundan tashqari
       yopilmagan literal blok sanog'ini ham buzadi, ya'ni ular BIR xatoning
       ikki ko'rinishi.
    """
    findings: list[Finding] = literal_defects(text)
    kod = code_lines(text)
    for ochuvchi, yopuvchi in BLOCK_PAIRS:
        rx_o, rx_y = _block_re(ochuvchi), _block_re(yopuvchi)
        chuqurlik = 0
        birinchi_manfiy = 0
        jami_o = jami_y = 0
        for i, satr in enumerate(kod, 1):
            n_y = len(rx_y.findall(satr))
            n_o = len(rx_o.findall(satr))
            #: ⚠️ Yopuvchi OLDIN ayiriladi: `КонецЦикла` va keyingi `Цикл` bir satrda
            #:    bo'lsa ham tartib to'g'ri hisoblanadi.
            jami_y += n_y
            jami_o += n_o
            chuqurlik -= n_y
            if chuqurlik < 0 and birinchi_manfiy == 0:
                birinchi_manfiy = i
            chuqurlik += n_o
        if birinchi_manfiy:
            findings.append(Finding(
                "BLOCK_CLOSER_BEFORE_OPENER", birinchi_manfiy,
                kod[birinchi_manfiy - 1].strip()[:120],
                f"`{yopuvchi}` o'zining `{ochuvchi}` sidan OLDIN keldi — "
                f"blok tuzilmasi buzilgan",
                STATUS_KNOWN,
            ))
        if jami_o != jami_y:
            findings.append(Finding(
                "BLOCK_UNBALANCED", 0, f"{ochuvchi}={jami_o} {yopuvchi}={jami_y}",
                f"`{ochuvchi}` {jami_o} marta, `{yopuvchi}` {jami_y} marta — "
                f"muvozanat buzilgan, modul kompilyatsiya bo'lmaydi",
                STATUS_KNOWN,
            ))
    if not findings:
        findings.append(Finding(
            "BLOCKS_BALANCED", 0, "",
            "hamma blok juftligi muvozanatda va hech bir yopuvchi o'z ochuvchisidan "
            "oldin kelmaydi — bu sintaksisning ZARURIY sharti, YETARLI sharti EMAS",
            STATUS_SOURCE_VALIDATED,
        ))
    return findings


# ── 3. API YUZASI ──────────────────────────────────────────────────────────────────────────
def api_surface(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Manbada ishlatilgan GLOBAL nomlarni ikki ro'yxatga ajratadi: (tanish, noma'lum).

    «Global nom» = kod qismidagi identifikator, u:
      · oldida nuqta YO'Q (ya'ni a'zo emas — a'zo nomlari obyekt turiga bog'liq va
        statik matndan aniqlanmaydi);
      · 1C kalit so'zi EMAS;
      · shu manbada E'LON QILINMAGAN (modul o'zgaruvchisi, protsedura nomi,
        parametr, tayinlash chap tomoni, sikl o'zgaruvchisi emas).
    Bundan tashqari `Метаданные` dan boshlangan a'zo ZANJIRLARI to'liq holda olinadi.

    ⚠️ ISBOTLAYDI: manbada qaysi global nomlar YOZILGANINI.
    ⚠️ ISBOTLAMAYDI: ularning platformada BORLIGINI ham, TO'G'RI ishlatilganini ham
       (`KNOWN_GLOBAL_API` izohiga qarang). «Tanish» ro'yxati QO'LDA yozilgan bilim.
    """
    kod = code_lines(text)
    proclar = procedures(kod)
    mahalliy = _local_names(kod, proclar)

    zanjirlar: set[str] = set()
    nomlar: set[str] = set()
    for satr in kod:
        #: ⚠️ Preprotsessor satri TASHLANADI: `#Область ПеременныеМодуля` dagi
        #:    hudud NOMI identifikator shaklida, lekin u chaqiriluvchi nom EMAS —
        #:    u API yuzasiga kirsa har hudud «noma'lum global nom» bo'lib chiqardi.
        if satr.lstrip().startswith("#"):
            continue
        for m in re.finditer(rf"Метаданные(?:\s*\.\s*{_IDENT})+", satr):
            zanjirlar.add(re.sub(r"\s+", "", m.group(0)))
        for m in _IDENT_RE.finditer(satr):
            oldin = satr[:m.start()].rstrip()
            if oldin.endswith("."):
                continue
            token = m.group(0)
            if token in _KEYWORDS or token in mahalliy:
                continue
            nomlar.add(token)

    tanish = {n for n in nomlar if n in KNOWN_GLOBAL_API}
    nomalum = nomlar - tanish
    tanish |= {z for z in zanjirlar if z in KNOWN_METADATA_PATHS}
    nomalum |= {z for z in zanjirlar if z not in KNOWN_METADATA_PATHS}
    return tuple(sorted(tanish)), tuple(sorted(nomalum))


def check_api_surface(text: str) -> list[Finding]:
    """Noma'lum global nom uchun `RUNTIME-UNKNOWN` topilma beradi.

    ⚠️ Tanish nom uchun topilma BERILMAYDI va `SOURCE-VALIDATED` ham yozilmaydi:
       «bizga tanish» hech qanday kafolat emas — `KNOWN_GLOBAL_API` izohiga qarang.
    ⚠️ Noma'lum nom NUQSON DEGANI EMAS. U «bu nomni statik audit tasdiqlay
       olmaydi» degani: 1C mutaxassisi Konfiguratorda sintaksis yordamchisi bilan
       tekshirishi kerak.
    """
    tanish, nomalum = api_surface(text)
    kod = code_lines(text)
    findings: list[Finding] = []
    if tanish:
        findings.append(Finding(
            "API_SURFACE_UNVERIFIED", 0, "",
            f"{len(tanish)} ta global nom BIZGA TANISH ro'yxatda, lekin bu "
            f"platformada borligini ham, TO'G'RI ishlatilganini (argumentlar, "
            f"kontekst, qaytish turi) ham ISBOTLAMAYDI — ro'yxat qo'lda yozilgan "
            f"bilim, platformadan olingan emas",
            STATUS_RUNTIME_UNKNOWN,
        ))
    for nom in nomalum:
        satr_no = 0
        satr = nom
        naqsh = re.compile(re.escape(nom) if "." in nom else rf"(?<!\w){re.escape(nom)}(?!\w)")
        for i, k in enumerate(kod, 1):
            if naqsh.search(re.sub(r"\s+", "", k) if "." in nom else k):
                satr_no, satr = i, k.strip()[:120]
                break
        findings.append(Finding(
            "API_NAME_UNVERIFIED", satr_no, satr,
            f"`{nom}` — statik audit uning 1C:Enterprise 8.3 da borligini ham, "
            f"to'g'ri ishlatilganini ham tasdiqlay olmaydi; Konfiguratorda "
            f"sintaksis tekshiruvi SHART",
            STATUS_RUNTIME_UNKNOWN,
        ))
    return findings


# ── 4. MIJOZ/SERVER KONTEKSTI ──────────────────────────────────────────────────────────────
_DIRECTIVE_RE = re.compile(r"&\s*(На[А-Яа-я]+)")


def check_client_server_context(text: str) -> list[Finding]:
    """Kompilyatsiya direktivalari va kontekst talablari.

    ⚠️ ISBOTLAYDI: manbada `&НаКлиенте`/`&НаСервере` direktivasi bor yoki yo'qligini,
       `Экспорт` kirish nuqtalari borligini, modul turi izohda e'lon qilinganini.
    ⚠️ ISBOTLAMAYDI: modul QAYSI kontekstda kompilyatsiya bo'lishini va fayl QAYSI
       mashinaning diskiga yozilishini. Tashqi qayta ishlashning ObjectModule i
       oddiy (неуправляемое) va boshqariladigan ilovada, fayl va klient-server
       bazasida BOSHQACHA joyda bajariladi; `ОткрытьФайл` ham shunga qarab
       operatorning mashinasiga yoki SERVER mashinasiga yozadi. Buni faqat real 1C
       ko'rsatadi.
    """
    findings: list[Finding] = []
    kod = code_lines(text)
    direktivalar = [(i, m.group(1)) for i, satr in enumerate(kod, 1)
                    for m in [_DIRECTIVE_RE.search(satr)] if m]

    for i, nom in direktivalar:
        if nom == "НаКлиенте":
            findings.append(Finding(
                "CONTEXT_CLIENT_DIRECTIVE", i, kod[i - 1].strip()[:120],
                "`&НаКлиенте` — bu manba o'zini ObjectModule deb e'lon qiladi, "
                "direktiva esa shakl moduli tushunchasi; e'lon bilan matn ZID",
                STATUS_KNOWN,
            ))
        else:
            findings.append(Finding(
                "CONTEXT_DIRECTIVE_PRESENT", i, kod[i - 1].strip()[:120],
                f"`&{nom}` direktivasi — ObjectModule da uning ta'siri platforma "
                f"rejimiga bog'liq; real 1C da tekshirilishi kerak",
                STATUS_RUNTIME_UNKNOWN,
            ))

    if not direktivalar:
        findings.append(Finding(
            "CONTEXT_NO_DIRECTIVE", 0, "",
            "birorta kompilyatsiya direktivasi yo'q — tashqi qayta ishlashning "
            "ObjectModule i uchun bu NORMAL, lekin shu bois modul QAYSI tomonda "
            "(operator mashinasi yoki 1C serveri) bajarilishi MANBADAN ko'rinmaydi; "
            "fayl yozish shu tomonning diskiga tushadi",
            STATUS_RUNTIME_UNKNOWN,
        ))

    if "ObjectModule" not in text:
        findings.append(Finding(
            "CONTEXT_MODULE_KIND_UNDECLARED", 0, "",
            "manba o'zining MODUL TURINI e'lon qilmaydi — operator uni qayerga "
            "qo'yishini bilmaydi, ya'ni kontekst talabini tekshirib ham bo'lmaydi",
            STATUS_KNOWN,
        ))

    eksportlar = [p for p in procedures(kod) if p.exported]
    if not eksportlar:
        findings.append(Finding(
            "CONTEXT_NO_EXPORT", 0, "",
            "birorta `Экспорт` kirish nuqtasi yo'q — tashqi qayta ishlashni "
            "tashqaridan chaqirib bo'lmaydi",
            STATUS_KNOWN,
        ))
    return findings


# ── 5. `Попытка` QAMROVI ───────────────────────────────────────────────────────────────────
#: Metadata MANBASIDAN qiymat olinayotgan tayinlash shakllari.
_META_ASSIGN_RE = re.compile(
    rf"=\s*Метаданные(?!\w)"
    rf"|=\s*КоллекцияМетаданных\s*\("
    rf"|=\s*{_IDENT}\s*\[\s*{_IDENT}\s*\]"
    rf"|=\s*{_IDENT}\s*\.\s*(?:ТабличныеЧасти|СтандартныеРеквизиты|Реквизиты"
    rf"|Измерения|Ресурсы|Состав|ЗначенияПеречисления|ПредопределенныеЭлементы)(?!\w)"
)
#: To'g'ridan-to'g'ri metadata kolleksiyasi ustidan kezish.
_META_INLINE_RE = re.compile(
    rf"Метаданные(?!\w)"
    rf"|{_IDENT}\s*\.\s*(?:ТабличныеЧасти|СтандартныеРеквизиты|Реквизиты|Измерения"
    rf"|Ресурсы|Состав|ЗначенияПеречисления|ПредопределенныеЭлементы|Типы\s*\(\s*\))(?!\w)"
)
_FOREACH_RE = re.compile(rf"Для\s+Каждого\s+{_IDENT}\s+Из\s+(?P<src>.+?)\s+Цикл")


def check_try_except_coverage(text: str) -> list[Finding]:
    """Metadata kolleksiyasini KEZADIGAN joy `Попытка` bilan o'ralganmi (fail-safe).

    NEGA MUHIM: 1C da kolleksiyani KEZISHNING O'ZI (`Для Каждого … Из`) istisno
    berishi mumkin — huquq yo'q, kolleksiya bu obyekt turida yo'q, kengaytma uni
    o'zgartirgan. Kezish `Попытка` dan tashqarida bo'lsa, istisno butun kirish
    nuqtasidan CHIQIB ketadi: hech qanday fayl yozilmaydi, hech qanday xato
    hujjatlanmaydi — operator bo'sh papka ko'radi.

    ⚠️ ISBOTLAYDI: `Для Каждого … Из <metadata manbasi>` satri `Попытка` blokining
       ICHIDA yozilgan yoki yozilmaganini; va `Экспорт` kirish nuqtasi tanasida
       `Попытка` umuman bor yoki yo'qligini. Bu MATN FAKTLARI — shu bois `KNOWN`.
    ⚠️ ISBOTLAMAYDI: istisno rostdan ham yuz berishini, `Попытка` ni tutgan kod
       to'g'ri ish qilishini yoki `Исключение` shoxi xatoni YO'QOTMASLIGINI.
    ⚠️ QAMRAMAYDI: metadata kolleksiyasi PARAMETR bo'lib kelgan protsedurani
       (`ДобавитьКоллекцию(Объекты, Коллекция, …)`) — parametrning ichida nima
       borligini statik matn bila olmaydi. Bu OCHIQ CHEGARA, yolg'on kafolat emas.
    """
    findings: list[Finding] = []
    kod = code_lines(text)
    for p in procedures(kod):
        if p.exported and not any(re.search(r"(?<!\w)Попытка(?!\w)", s) for s in p.body):
            findings.append(Finding(
                "ENTRY_WITHOUT_TRY", p.start, kod[p.start - 1].strip()[:120],
                f"`{p.name}` — `Экспорт` kirish nuqtasi, lekin tanasida birorta "
                f"`Попытка` yo'q: ichkaridan chiqqan istisno CHAQIRUVCHIGA ketadi, "
                f"ya'ni na `run_status.json`, na `errors.json` yozilmaydi",
                STATUS_KNOWN,
            ))

        meta_vars: set[str] = set()
        chuqurlik = 0
        for ofset, satr in enumerate(p.body):
            satr_no = p.start + 1 + ofset
            chuqurlik -= len(re.findall(r"(?<!\w)КонецПопытки(?!\w)", satr))
            chuqurlik = max(chuqurlik, 0)

            tayin = re.match(rf"^\s*({_IDENT})\s*(=[^=].*)$", satr)
            if tayin and _META_ASSIGN_RE.search(tayin.group(2)):
                meta_vars.add(tayin.group(1))

            sikl = _FOREACH_RE.search(satr)
            if sikl is not None and chuqurlik == 0:
                manba = sikl.group("src").strip()
                bosh_token = _IDENT_RE.match(manba)
                metadata_manbasi = (
                    _META_INLINE_RE.search(manba) is not None
                    or (bosh_token is not None and bosh_token.group(0) in meta_vars
                        and "(" not in manba)
                )
                if metadata_manbasi:
                    findings.append(Finding(
                        "LOOP_WITHOUT_TRY", satr_no, satr.strip()[:120],
                        f"`{p.name}` ichida metadata kolleksiyasi `Попытка` "
                        f"TASHQARISIDA kezilyapti — kezishning O'ZI istisno berishi "
                        f"mumkin va u butun kirish nuqtasidan chiqib ketadi",
                        STATUS_KNOWN,
                    ))

            chuqurlik += len(re.findall(r"(?<!\w)Попытка(?!\w)", satr))
    return findings


# ── 6. FAYL API SI ────────────────────────────────────────────────────────────────────────
_OPENFILE_RE = re.compile(r"\.\s*ОткрытьФайл\s*\(")


def _arg_split(satr: str, ochilish: int) -> list[str]:
    """`(` dan keyingi argumentlarni yuqori darajadagi vergul bo'yicha ajratadi."""
    daraja = 0
    joriy: list[str] = []
    natija: list[str] = []
    for belgi in satr[ochilish:]:
        if belgi == "(":
            daraja += 1
            if daraja == 1:
                continue
        elif belgi == ")":
            daraja -= 1
            if daraja == 0:
                break
        if daraja == 1 and belgi == ",":
            natija.append("".join(joriy).strip())
            joriy = []
            continue
        joriy.append(belgi)
    natija.append("".join(joriy).strip())
    return natija


def check_file_api_usage(text: str) -> list[Finding]:
    """Fayl yozish uchun qanday API va qanday YO'L QURISH usuli ishlatilgan.

    ⚠️ ISBOTLAYDI: `ОткрытьФайл` chaqiruvlari borligini, yo'l konkatenatsiya bilan
       qurilganini, ajratuvchi `/` yoki `\\` ekanini va `ОбъединитьПути`
       ishlatilmaganini. Bu MATN FAKTLARI.
    ⚠️ ISBOTLAMAYDI: yo'lning real fayl tizimida ISHLASHINI. Windows'da 1C `/` ni
       qabul qiladi degan da'vo bu yerda YOZILMAYDI — u sinalmagan. Operator
       papkani `D:\\Chiqish\\` ko'rinishida (oxirida ajratuvchi bilan) bersa yo'l
       ikki ajratuvchili bo'lib qoladi; bunday yo'lning taqdiri ham
       `RUNTIME-UNKNOWN`.
    """
    findings: list[Finding] = []
    #: ⚠️ Literal MAZMUNI kerak (yo'ldagi `/`), izoh esa KERAK EMAS: izohdagi
    #:    misol yo'l hech narsani majburlamaydi.
    xom = code_lines(text, strip_literals=False)
    kod = code_lines(text)

    proclar = procedures(kod)
    for i, satr in enumerate(kod, 1):
        m = _OPENFILE_RE.search(satr)
        if m is None:
            continue
        args = _arg_split(xom[i - 1], xom[i - 1].find("(", m.start()))
        yol = args[0] if args else ""
        #: ⚠️ Yo'l BITTA O'ZGARUVCHIDA bo'lsa, uning TAYINLASHI ochiladi.
        #:    NEGA KERAK: `Путь = Каталог + "/" + Nom;` keyin `ОткрытьФайл(Путь, …)`
        #:    — bu ayni konkatenatsiya, faqat bir qadam nariroq. Buni ko'rmaslik
        #:    tekshiruvni yordamchiga ko'chirish bilan JIMGINA o'chirib qo'yardi.
        #: ⚠️ CHEGARA: faqat BITTA qadam va FAQAT shu protsedura ichida. Parametr
        #:    orqali kelgan yo'l ko'rinmaydi — bu ochiq chegara.
        if _IDENT_RE.fullmatch(yol):
            egasi = next((p for p in proclar if p.start < i < p.end), None)
            if egasi is not None:
                for ofset in range(i - egasi.start - 2, -1, -1):
                    tayin = re.match(rf"^\s*{re.escape(yol)}\s*=([^=].*)$",
                                     xom[egasi.start + ofset])
                    if tayin:
                        yol = tayin.group(1)
                        i = egasi.start + 1 + ofset
                        break
        if "+" in yol:
            findings.append(Finding(
                "PATH_BUILT_BY_CONCAT", i, xom[i - 1].strip()[:120],
                "yo'l matn qo'shish bilan qurilgan: operator bergan papka oxirida "
                "ajratuvchi bo'lsa yo'lda IKKI ajratuvchi qoladi; `ОбъединитьПути` "
                "bu holatni platformaning O'ZIGA topshirardi",
                STATUS_RUNTIME_UNKNOWN,
            ))
        if "/" in yol:
            findings.append(Finding(
                "PATH_FORWARD_SLASH", i, xom[i - 1].strip()[:120],
                "yo'l ajratuvchisi `/` — do'kon mashinasi Windows; 1C ning `/` ni "
                "qabul qilishi SINALMAGAN, shu bois bu xulosa runtime'da hal bo'ladi",
                STATUS_RUNTIME_UNKNOWN,
            ))
        if "\\" in yol:
            findings.append(Finding(
                "PATH_BACKSLASH", i, xom[i - 1].strip()[:120],
                "yo'l ajratuvchisi `\\` — BSL satr literalida teskari chiziq oddiy "
                "belgi, lekin ikki ajratuvchi va qochirish masalasi runtime'da "
                "hal bo'ladi",
                STATUS_RUNTIME_UNKNOWN,
            ))

    if _OPENFILE_RE.search("\n".join(kod)) and "ОбъединитьПути" not in "\n".join(kod):
        findings.append(Finding(
            "PATH_NO_JOIN_HELPER", 0, "",
            "`ОбъединитьПути` ishlatilmagan — yo'l qurish qoidasi manbada QO'LDA "
            "yozilgan, ya'ni har platforma farqi bizning zimmamizda",
            STATUS_RUNTIME_UNKNOWN,
        ))

    if not any(_OPENFILE_RE.search(s) for s in kod):
        findings.append(Finding(
            "FILE_NO_WRITE_CHANNEL", 0, "",
            "birorta `ОткрытьФайл` yo'q — manba hech qanday fayl yozmaydi, ya'ni "
            "runtime paketi (`export.json` … `manifest.json`) UMUMAN chiqmaydi",
            STATUS_KNOWN,
        ))
    return findings


# ── 7. JSON YOZUVCHISI ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TryBlock:
    """Bitta `Попытка` … `Исключение` … `КонецПопытки` bloki (kod satrlari bilan)."""

    start: int
    except_at: int
    end: int
    try_part: tuple[str, ...]
    except_part: tuple[str, ...]


def try_blocks(kod: list[str]) -> list[TryBlock]:
    """Eng TASHQI `Попытка` bloklarini ajratadi (ichkilari `try_part` ga kiradi)."""
    natija: list[TryBlock] = []
    stack: list[int] = []
    except_at: dict[int, int] = {}
    for i, satr in enumerate(kod, 1):
        if re.search(r"(?<!\w)КонецПопытки(?!\w)", satr):
            if stack:
                boshi = stack.pop()
                istisno = except_at.pop(boshi, i)
                natija.append(TryBlock(
                    boshi, istisno, i,
                    tuple(kod[boshi:istisno - 1]),
                    tuple(kod[istisno:i - 1]),
                ))
        if re.search(r"(?<!\w)Исключение(?!\w)", satr) and stack:
            except_at[stack[-1]] = i
        if re.search(r"(?<!\w)Попытка(?!\w)", satr):
            stack.append(i)
    return sorted(natija, key=lambda b: b.start)


def check_json_writer_usage(text: str) -> list[Finding]:
    """`ЗаписьJSON` oqimi to'g'ri ochilib, kodlanib va YOPILAYOTGANMI.

    ⚠️ ISBOTLAYDI (MATN FAKTI):
       · `Новый ЗаписьJSON` va `ЗаписатьJSON(` juftligi ishlatilganini;
       · `ОткрытьФайл` ga kodlash `"UTF-8"` va BOM argumenti berilganini;
       · `Закрыть()` chaqiruvi `Попытка` ning MUVAFFAQIYAT shoxidagina turganini,
         `Исключение` shoxida YO'Q ekanini — ya'ni `ЗаписатьJSON` yiqilsa oqim
         OCHIQ qoladi va faylda YARIM yozilgan JSON qoladi;
       · yozish MUVAFFAQIYATLI tugaganda bo'lim jurnalida `ok` belgisi qo'yilmaganini.
    ⚠️ ISBOTLAMAYDI: platforma faylga aynan qanday baytlar yozishini, BOM borligini,
       yarim yozilgan fayl qanday ko'rinishini. Buni faqat real 1C ko'rsatadi.

    ⚠️ NEGA YARIM FAYL XAVFLI: yarim JSON `SUCCESS` deb belgilanishi mumkin, chunki
       xato belgisi `export.json` ning O'ZIGA yoziladi — ya'ni yiqilgan yozuvning
       xatosi yiqilgan fayl ichida qoladi va operatorga YETIB BORMAYDI. Aynan shu
       sabab runtime paketida ALOHIDA `run_status.json` va `errors.json` bor.
    """
    findings: list[Finding] = []
    kod = code_lines(text)
    #: ⚠️ Literal MAZMUNI kerak: `"UTF-8"`, `"ok"` — ikkisi ham SHARTNOMA qiymati.
    xom = code_lines(text, strip_literals=False)
    kod_matn = "\n".join(kod)

    if "ЗаписьJSON" in kod_matn and "ЗаписатьJSON" in kod_matn:
        findings.append(Finding(
            "JSON_WRITER_PAIR_PRESENT", 0, "",
            "`Новый ЗаписьJSON` + `ЗаписатьJSON(` juftligi ishlatilgan — eksport "
            "shartnomasi talab qilgan yozuv kanali",
            STATUS_SOURCE_VALIDATED,
        ))
    elif "ЗаписьJSON" in kod_matn or "ЗаписатьJSON" in kod_matn:
        findings.append(Finding(
            "JSON_WRITER_PAIR_INCOMPLETE", 0, "",
            "`ЗаписьJSON` va `ЗаписатьJSON` dan faqat bittasi bor — oqim ochilib "
            "yozilmaydi yoki yozilib ochilmaydi",
            STATUS_KNOWN,
        ))

    for i, satr in enumerate(kod, 1):
        m = _OPENFILE_RE.search(satr)
        if m is None:
            continue
        args = _arg_split(xom[i - 1], xom[i - 1].find("(", m.start()))
        kodlash = args[1].strip('" ') if len(args) > 1 else ""
        if kodlash.upper() != "UTF-8":
            findings.append(Finding(
                "JSON_ENCODING_NOT_UTF8", i, xom[i - 1].strip()[:120],
                f"kodlash argumenti `{kodlash or '<berilmagan>'}` — BinOS tomoni "
                f"faylni UTF-8 deb o'qiydi, boshqa kodlash hujjatni o'qilmas qiladi",
                STATUS_KNOWN,
            ))
        else:
            findings.append(Finding(
                "JSON_ENCODING_UTF8", i, xom[i - 1].strip()[:120],
                "kodlash `\"UTF-8\"` deb ANIQ berilgan (standartga tashlanmagan)",
                STATUS_SOURCE_VALIDATED,
            ))
        bom = args[2].strip() if len(args) > 2 else ""
        if bom == "Ложь":
            findings.append(Finding(
                "JSON_BOM_DISABLED", i, xom[i - 1].strip()[:120],
                "BOM argumenti `Ложь` — BOM yozilmasligi SO'RALGAN; baytlarning "
                "o'zi runtime'da tekshiriladi",
                STATUS_SOURCE_VALIDATED,
            ))
        elif bom:
            findings.append(Finding(
                "JSON_BOM_REQUESTED", i, xom[i - 1].strip()[:120],
                f"BOM argumenti `{bom}` — BOM bilan fayl Python tomonida "
                f"`utf-8` sifatida o'qilganda birinchi belgi buziladi",
                STATUS_KNOWN,
            ))
        else:
            findings.append(Finding(
                "JSON_BOM_UNSET", i, xom[i - 1].strip()[:120],
                "BOM argumenti berilmagan — platformaning standarti nima ekani "
                "manbadan ko'rinmaydi",
                STATUS_RUNTIME_UNKNOWN,
            ))

    for blok in try_blocks(kod):
        try_matn = "\n".join(blok.try_part)
        if "ЗаписьJSON" not in try_matn:
            continue
        if not re.search(r"(?<!\w)Закрыть\s*\(", try_matn):
            findings.append(Finding(
                "JSON_CLOSE_MISSING", blok.start, kod[blok.start - 1].strip()[:120],
                "oqim `Попытка` ichida ochildi, lekin `Закрыть()` UMUMAN yo'q — "
                "fayl deskriptori ochiq qoladi",
                STATUS_KNOWN,
            ))
            continue
        if not re.search(r"(?<!\w)Закрыть\s*\(", "\n".join(blok.except_part)):
            findings.append(Finding(
                "JSON_CLOSE_NOT_GUARANTEED", blok.start, kod[blok.start - 1].strip()[:120],
                "`Закрыть()` faqat MUVAFFAQIYAT shoxida: `ЗаписатьJSON` yiqilsa oqim "
                "OCHIQ qoladi va diskda YARIM yozilgan JSON qoladi — uni keyin "
                "`SUCCESS` deb belgilash mumkin",
                STATUS_KNOWN,
            ))

    for p in procedures(kod):
        #: ⚠️ Tana LITERALLAR bilan olinadi: `"ok"` qiymatining O'ZI tekshiriladi.
        tana = "\n".join(xom[p.start:p.end - 1])
        if "ЗаписьJSON" not in tana:
            continue
        #: Muvaffaqiyat IKKI yo'ldan biri bilan bildirilishi mumkin:
        #:   · bo'lim jurnalida `"ok"` belgisi;
        #:   · chaqiruvchiga QAYTARILGAN `Истина` (chaqiruvchi shuni jurnalga yozadi).
        #: ⚠️ Ikkinchi yo'l ATAYLAB qabul qilinadi: aks holda `Возврат Истина` bilan
        #:    ishlaydigan yozuvchi YOLG'ON tutilardi — bu TOPILGAN yolg'on ijobiy edi.
        if not (re.search(r'Отметить[А-Яа-я]*\s*\([^)]*"ok"', tana)
                or re.search(r"(?<!\w)Возврат\s+Истина(?!\w)", tana)):
            findings.append(Finding(
                "WRITE_SUCCESS_UNRECORDED", p.start, kod[p.start - 1].strip()[:120],
                f"`{p.name}` fayl yozadi, lekin MUVAFFAQIYATNI na bo'lim jurnaliga "
                f"yozadi, na chaqiruvchiga qaytaradi — «yozildi» va «umuman "
                f"urinilmadi» bir xil ko'rinadi",
                STATUS_KNOWN,
            ))
    return findings


# ── 8. UCHLIK MANTIQ MATN BILAN ────────────────────────────────────────────────────────────
#: Ruxsat etilgan uchlik qiymatlar (shakl lug'atlari bilan AYNAN bir xil).
TRISTATE_TEXTS = ("true", "false", "unknown")


def check_tristate_text(text: str) -> list[Finding]:
    """Uchlik mantiq JSON'ga MATN bo'lib chiqayotganmi (`Булево` emas).

    NEGA: `Булево` JSON'da `true`/`false` bo'lib ketadi va «bilmayman» ni «yo'q»
    dan ajratib bo'lmaydi. Shakl lug'atlari (`metadata.py`) uchlik qiymatni MATN
    deb talab qiladi: `"true"` | `"false"` | `"unknown"`.

    ⚠️ ISBOTLAYDI: LITERAL kalit bilan `Вставить("kalit", Истина|Ложь)` yozilgan
       joyni va `<obyekt>.<maydon> = Истина|Ложь` tayinlashini. Bu MATN FAKTLARI.
    ⚠️ ISBOTLAMAYDI: o'zgaruvchi ICHIDA nima borligini. `Вставить("k", Значение)`
       da `Значение` `Булево` bo'lishi mumkin va statik matn buni KO'RMAYDI —
       OCHIQ CHEGARA. Shu bois bu tekshiruv «hamma uchlik to'g'ri» demaydi.
    ⚠️ ATAYLAB QAMRAMAYDI: kalit LITERAL bo'lmagan `Вставить` (masalan
       `Виденные.Вставить(Имя, Истина)`) — u ichki `Соответствие`, JSON'ga
       chiqmaydi; uni tutish YOLG'ON IJOBIY bo'lardi.
    """
    findings: list[Finding] = []
    #: ⚠️ Izohsiz, lekin literallar bilan: izohdagi misol (`Вставить("k", Истина)`)
    #:    kodda hech narsani majburlamaydi, kalit LITERALI esa kerak.
    xom = code_lines(text, strip_literals=False)
    for i, satr in enumerate(xom, 1):
        for m in re.finditer(r'Вставить\s*\(\s*"([^"]*)"\s*,\s*([^,)]+?)\s*\)', satr):
            kalit, qiymat = m.group(1), m.group(2).strip()
            if qiymat in ("Истина", "Ложь"):
                findings.append(Finding(
                    "TRISTATE_BOOLEAN_VALUE", i, satr.strip()[:120],
                    f"`{kalit}` kalitiga `{qiymat}` — `Булево` JSON'da `true`/`false` "
                    f"bo'lib ketadi va «bilmayman» ni «yo'q» dan ajratib bo'lmaydi; "
                    f"MATN yozilishi kerak: {', '.join(TRISTATE_TEXTS)}",
                    STATUS_KNOWN,
                ))
        m2 = re.search(rf"^\s*{_IDENT}\s*\.\s*{_IDENT}\s*=\s*(Истина|Ложь)\s*;", satr)
        if m2:
            findings.append(Finding(
                "TRISTATE_BOOLEAN_FIELD", i, satr.strip()[:120],
                f"struktura maydoniga `{m2.group(1)}` tayinlandi — JSON'ga `Булево` "
                f"bo'lib chiqadi",
                STATUS_KNOWN,
            ))
    #: Uchlik mantiqning uchlik SHOXI: `?(shart, "…", "…")`.
    #: ⚠️ FAQAT BITTA shoxi lug'atda bo'lsa tutiladi. IKKOVI ham lug'atdan tashqarida
    #:    bo'lgan ternar (`?(Смещение < 0, "-", "+")`) UCHLIK MANTIQ EMAS — uni
    #:    tutish YOLG'ON IJOBIY bo'lardi va bu aynan TOPILGAN xato edi.
    uchlik_bor = False
    for m3 in re.finditer(r'\?\s*\([^()]*?,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)',
                          "\n".join(code_lines(text, strip_literals=False))):
        lugatda = [q for q in m3.groups() if q in TRISTATE_TEXTS]
        if len(lugatda) == 2:
            uchlik_bor = True
            continue
        if len(lugatda) == 1:
            begona = next(q for q in m3.groups() if q not in TRISTATE_TEXTS)
            findings.append(Finding(
                "TRISTATE_UNKNOWN_VOCABULARY", 0, m3.group(0)[:120],
                f"uchlik shoxida `{begona}` — lug'atda faqat "
                f"{', '.join(TRISTATE_TEXTS)} bor",
                STATUS_KNOWN,
            ))
    if not findings and uchlik_bor:
        findings.append(Finding(
            "TRISTATE_TEXT_ONLY", 0, "",
            "uchlik mantiq MATN bilan berilgan va lug'at buzilmagan — `Булево` "
            "JSON'ga chiqadigan joy TOPILMADI",
            STATUS_SOURCE_VALIDATED,
        ))
    return findings


# ── 9. SANOQLAR MATN SIFATIDA ──────────────────────────────────────────────────────────────
def check_count_as_text(text: str) -> list[Finding]:
    """Sanoq JSON'ga MATN bo'lib chiqayotganmi (`Формат`/`Строка` bilan).

    NEGA: JSON SONI TAQIQLANGAN — `0000123` soni `123` bo'lib qoladi va boshidagi
    nollar bilan birga ma'no yo'qoladi (PLU va Код aynan shunday yo'qoladi).

    ⚠️ ISBOTLAYDI: `Количество()` yoki so'rov natijasi HUJJATGA chiqayotgan gapda
       (`Вставить("kalit", …)` yoki `Возврат …`) `Формат(`/`Строка(` o'ramasi bor
       yoki yo'qligini. Bu MATN FAKTI.
    ⚠️ ISBOTLAMAYDI: `Формат` ning aynan qanday matn berishini (`"ЧГ=0"` guruh
       ajratuvchisini o'chiradi degan da'vo bu yerda sinalmagan) va sanoqning
       o'zgaruvchi orqali aylanib chiqmasligini.
    ⚠️ ATAYLAB QAMRAMAYDI: taqqoslash va sikl chegarasi (`Если …Количество() = 0`,
       `Для Сч = 0 По …Количество() - 1`) — u yerda son SONLIGIDA kerak.
    """
    findings: list[Finding] = []
    kod = code_lines(text)
    sanoq_bor = False
    for i, satr in enumerate(kod, 1):
        if "Количество" not in satr and "Выборка." not in satr:
            continue
        hujjatga = "Вставить" in satr or re.match(r"^\s*Возврат\b", satr)
        if not hujjatga:
            continue
        if re.search(r"(?<!\w)(?:Если|ИначеЕсли|Пока)(?!\w)", satr):
            continue
        sanoq_bor = True
        if re.search(r"(?<!\w)(?:Формат|Строка)\s*\(", satr):
            continue
        findings.append(Finding(
            "COUNT_NOT_TEXT", i, satr.strip()[:120],
            "sanoq `Формат(`/`Строка(` bilan MATNGA aylantirilmagan — JSON soni "
            "boshidagi nollarni yo'qotadi",
            STATUS_KNOWN,
        ))
    if not findings and sanoq_bor:
        findings.append(Finding(
            "COUNT_TEXT_ONLY", 0, "",
            "hujjatga chiqadigan hamma sanoq `Формат(`/`Строка(` bilan o'ralgan — "
            "JSON soni bo'lib chiqadigan joy TOPILMADI",
            STATUS_SOURCE_VALIDATED,
        ))
    return findings


# ── 10. IXTIYORIY METADATA OILALARI ────────────────────────────────────────────────────────
#: ⚠️ Bu oilalar KO'P konfiguratsiyada YO'Q. «Yo'q» ham JAVOB va u JIMGINA
#: tashlanmasligi kerak: shakl qoidasi «qaralmadi» ni «yo'q» dan ajratishni talab
#: qiladi. `ПланыОбмена` alohida muhim — u mijozning boshqa integratsiyalari
#: borligini ko'rsatadigan YAGONA metadata belgisi.
OPTIONAL_FAMILIES = ("ПланыСчетов", "ПланыВидовХарактеристик", "ОбщиеРеквизиты",
                     "ПланыОбмена")


def check_optional_family_guard(text: str) -> list[Finding]:
    """Ixtiyoriy metadata oilasi YO'Q bo'lsa, bu JURNALGA tushadimi.

    Oila «qo'riqlangan» deb hisoblanadi, agar u:
      (a) `ОписаниеКоллекции(` ro'yxatiga kirgan bo'lsa — bu UMUMIY yo'l, u
          kolleksiya o'qilmaganda `skipped` bo'lim yozadi; yoki
      (b) `Отметить…Раздел…` chaqiruvi BOR protsedurada eslangan bo'lsa.

    ⚠️ ISBOTLAYDI: oila nomi manbada bor yoki yo'qligini va u yuqoridagi ikki
       yo'ldan birida turganini. Bu MATN FAKTI — shu bois `KNOWN`.
    ⚠️ ISBOTLAMAYDI: bo'lim jurnali real 1C da rostdan to'ldirilishini, va oila
       shu konfiguratsiyada borligini. Manbada UMUMAN eslanmagan oila esa
       runtime'da JIMGINA yo'qoladi — bu topilmaning butun ma'nosi.
    """
    findings: list[Finding] = []
    #: ⚠️ Oila nomlari manbada SATR LITERALI bo'lib turadi
    #:    (`КоллекцияМетаданных("ПланыСчетов", …)`), shu bois literallar SAQLANADI.
    #:    Izoh esa olib tashlanadi: izohda eslangan oila runtime'da hech narsa
    #:    qilmaydi, ya'ni «eslangan» deb hisoblanishi YOLG'ON kafolat bo'lardi.
    xom = code_lines(text, strip_literals=False)
    kod = code_lines(text)
    kod_matn = "\n".join(xom)
    proclar = procedures(kod)

    umumiy_yol = {
        m.group(1)
        for m in re.finditer(rf'ОписаниеКоллекции\s*\(\s*"({_IDENT})"', kod_matn)
    }
    for oila in OPTIONAL_FAMILIES:
        if oila not in kod_matn:
            findings.append(Finding(
                "OPTIONAL_FAMILY_UNMENTIONED", 0, oila,
                f"`{oila}` manbada UMUMAN eslanmagan — bu oila bor bo'lsa ham, "
                f"yo'q bo'lsa ham hujjatda hech qanday iz qoldirmaydi, ya'ni "
                f"JIMGINA tashlab ketiladi",
                STATUS_KNOWN,
            ))
            continue
        if oila in umumiy_yol:
            findings.append(Finding(
                "OPTIONAL_FAMILY_GUARDED", 0, oila,
                f"`{oila}` umumiy kolleksiya ro'yxatida — o'qilmasa bo'lim "
                f"jurnalida sababi bilan qoladi",
                STATUS_SOURCE_VALIDATED,
            ))
            continue
        jurnalli = any(
            oila in "\n".join(xom[p.start:p.end - 1])
            and re.search(r"Отметить[А-Яа-я]*Раздел[А-Яа-я]*\s*\(",
                          "\n".join(xom[p.start:p.end - 1]))
            for p in proclar
        )
        if jurnalli:
            findings.append(Finding(
                "OPTIONAL_FAMILY_GUARDED", 0, oila,
                f"`{oila}` bo'lim jurnali bor protsedurada ishlanadi — yo'qligi "
                f"sababi bilan qayd etiladi",
                STATUS_SOURCE_VALIDATED,
            ))
        else:
            findings.append(Finding(
                "OPTIONAL_FAMILY_UNLOGGED", 0, oila,
                f"`{oila}` manbada bor, lekin uning yo'qligini bo'lim jurnaliga "
                f"yozadigan yo'l KO'RINMAYDI — «qaralmadi» «yo'q» ga aylanadi",
                STATUS_KNOWN,
            ))
    return findings


# ── Tekshiruvlar reyestri ──────────────────────────────────────────────────────────────────
#: ⚠️ Tartib SHARTNOMA: `RUNTIME_READINESS.md` dagi tavsif shu tartibda yozilgan.
CHECKS: tuple[tuple[str, object], ...] = (
    ("identifier_charset", check_identifier_charset),
    ("balanced_blocks", check_balanced_blocks),
    ("api_surface", check_api_surface),
    ("client_server_context", check_client_server_context),
    ("try_except_coverage", check_try_except_coverage),
    ("file_api_usage", check_file_api_usage),
    ("json_writer_usage", check_json_writer_usage),
    ("tristate_text", check_tristate_text),
    ("count_as_text", check_count_as_text),
    ("optional_family_guard", check_optional_family_guard),
)


def audit_source(text: str) -> list[Finding]:
    """Hamma tekshiruvni ishlatadi va topilmalarni deterministik tartibda qaytaradi.

    ⚠️ BO'SH RO'YXAT «tayyor» DEGANI EMAS. Bu audit runtime'ni almashtirmaydi:
       `RUNTIME-UNKNOWN` holatidagi topilma NUQSON emas, «buni faqat real 1C
       ko'rsatadi» degan YOZUV. Shu bois bu modul CI da darvoza bo'lib TURMAYDI —
       u inventarni to'ldiradi (`integrations/1c/RUNTIME_READINESS.md`).
    """
    findings: list[Finding] = []
    for _, tekshiruv in CHECKS:
        findings.extend(tekshiruv(text))          # type: ignore[operator]
    return sorted(findings, key=lambda f: (f.line_no, f.code, f.line))


def audit_file(path) -> list[Finding]:
    return audit_source(pathlib.Path(path).read_text(encoding="utf-8"))


def findings_by_status(findings: list[Finding]) -> dict[str, int]:
    """Holat bo'yicha sanoq — inventar va hisobot uchun."""
    return {h: sum(1 for f in findings if f.status == h) for h in FINDING_STATUSES}


# ── §2 BLOKERLAR INVENTARI ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class InventoryItem:
    """Inventar qatori: `RUNTIME_READINESS.md` dagi jadval qatori bilan AYNAN bir xil."""

    slug: str
    title: str
    status: str


#: ⚠️ HOLAT BERISH QOIDASI (taxmin bilan `KNOWN` yozilmaydi):
#:   · `KNOWN` — MANBA MATNI shu xulosani MAJBURLAYDI (matndan o'qib aynan aytish
#:     mumkin), ya'ni tuzatilmasa runtime'da AYNAN shunday bo'ladi;
#:   · `SOURCE-VALIDATED` — statik tekshiruv bajarildi va talab QONDIRILDI;
#:   · `RUNTIME-UNKNOWN` — matn bilan hal qilinmaydi, real 1C kerak.
#:
#: ⚠️⚠️ HOLATLAR — SNAPSHOT, ABADIY HAQIQAT EMAS. Ular `BinOSDiscovery.bsl` ning
#:      SHU holati ustida hisoblangan. Manba o'zgarsa holatlar QAYTA HISOBLANISHI
#:      SHART:
#:          python -c "from app.services.discovery_1c import runtime_audit as r; \
#:                     import collections; \
#:                     print(collections.Counter(f.code for f in r.audit_file(r.EXTRACTOR_SOURCE)))"
#:      Keyin `INVENTORY_ITEMS` va `RUNTIME_READINESS.md` birga tahrirlanadi
#:      (ikkisining mosligini `test_inventar_jadvali_kod_bilan_MOS` qulflaydi).
#:      ⚠️ Nuqson tuzatilganda holatni pasaytirish ESDAN CHIQMASIN — aks holda
#:      hujjat mavjud bo'lmagan nuqsonni ko'rsatib turadi.
INVENTORY_ITEMS: tuple[InventoryItem, ...] = (
    InventoryItem("bsl_syntax", "BSL sintaksisi", STATUS_RUNTIME_UNKNOWN),
    InventoryItem("processor_module_compile", "Tashqi qayta ishlash moduli kompilyatsiyasi",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("metadata_api_compatibility", "Metadata API mosligi", STATUS_RUNTIME_UNKNOWN),
    InventoryItem("platform_version_compatibility", "Platforma versiyasi mosligi",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("managed_or_ordinary", "Boshqariladigan yoki oddiy ilova",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("file_write_permissions", "Fayl yozish huquqlari", STATUS_RUNTIME_UNKNOWN),
    InventoryItem("encoding", "Kodlash", STATUS_SOURCE_VALIDATED),
    InventoryItem("json_serialization", "JSON serializatsiyasi", STATUS_KNOWN),
    InventoryItem("large_configuration_performance", "Katta konfiguratsiyada unumdorlik",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("optional_metadata_families_absence", "Ixtiyoriy metadata oilalarining yo'qligi",
                  STATUS_KNOWN),
    InventoryItem("permissions_read_access_failures", "Huquq va o'qish xatolari",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("probe_execution_contract", "Zond bajarilish shartnomasi", STATUS_KNOWN),
    InventoryItem("timestamps", "Vaqt belgilari", STATUS_RUNTIME_UNKNOWN),
    InventoryItem("output_directory_behavior", "Chiqish papkasining xatti-harakati",
                  STATUS_RUNTIME_UNKNOWN),
    InventoryItem("exception_handling", "Istisnolarni ishlash", STATUS_KNOWN),
)

#: Har inventar qatorini QAYSI topilma kodlari qo'llab-quvvatlaydi.
#: ⚠️ NEGA KERAK: holat «taxmin bilan» yozilmasligi uchun. `KNOWN` yoki
#:    `SOURCE-VALIDATED` qator KAMIDA BITTA topilma kodiga tayanishi shart, va
#:    o'sha kod `runtime_audit.py` da rostdan chiqarilishi kerak — buni test
#:    statik tekshiradi. Bo'sh ro'yxat faqat `RUNTIME-UNKNOWN` qatorda bo'ladi:
#:    u yerda tayanadigan topilma YO'Q, javob runtime'da.
INVENTORY_EVIDENCE: dict[str, tuple[str, ...]] = {
    "bsl_syntax": ("LITERAL_BACKSLASH_QUOTE", "LITERAL_UNTERMINATED",
                   "BLOCK_UNBALANCED", "BLOCK_CLOSER_BEFORE_OPENER",
                   "CHARSET_FOREIGN_LETTER", "CHARSET_MIXED_SCRIPT"),
    "processor_module_compile": (),
    "metadata_api_compatibility": ("API_SURFACE_UNVERIFIED", "API_NAME_UNVERIFIED"),
    "platform_version_compatibility": (),
    "managed_or_ordinary": ("CONTEXT_NO_DIRECTIVE", "CONTEXT_CLIENT_DIRECTIVE"),
    "file_write_permissions": (),
    "encoding": ("JSON_ENCODING_UTF8", "JSON_BOM_DISABLED"),
    "json_serialization": ("JSON_CLOSE_NOT_GUARANTEED", "JSON_CLOSE_MISSING",
                           "JSON_WRITER_PAIR_INCOMPLETE", "WRITE_SUCCESS_UNRECORDED",
                           "JSON_ENCODING_NOT_UTF8", "JSON_BOM_REQUESTED"),
    "large_configuration_performance": (),
    "optional_metadata_families_absence": ("OPTIONAL_FAMILY_UNMENTIONED",
                                           "OPTIONAL_FAMILY_UNLOGGED"),
    "permissions_read_access_failures": (),
    "probe_execution_contract": ("ENTRY_WITHOUT_TRY",),
    "timestamps": (),
    "output_directory_behavior": ("PATH_BUILT_BY_CONCAT", "PATH_FORWARD_SLASH",
                                  "PATH_BACKSLASH", "PATH_NO_JOIN_HELPER",
                                  "FILE_NO_WRITE_CHANNEL"),
    "exception_handling": ("ENTRY_WITHOUT_TRY", "LOOP_WITHOUT_TRY"),
}

#: Inventar hujjati — jadval qatorlari shu faylga QULFLANGAN (testda solishtiriladi).
#: `runtime_audit.py` -> discovery_1c -> services -> app -> server -> apps -> ILDIZ
READINESS_DOC = (pathlib.Path(__file__).resolve().parents[5]
                 / "integrations" / "1c" / "RUNTIME_READINESS.md")
EXTRACTOR_SOURCE = (pathlib.Path(__file__).resolve().parents[5]
                    / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl")


# ── RUNTIME PAKETI SHARTNOMASI ────────────────────────────────────────────────────────────
#: Real 1C mashinasidan chiqadigan papkaning MAJBURIY tarkibi.
#:
#: ⚠️ NEGA `run_status.json` va `run_summary.md`, `status.json`/`summary.md` EMAS:
#:    to'plam (`binos-1c-discovery-v1`) a'zolari AYNAN `status.json` va `summary.md`
#:    deb ataladi (`__init__.REQUIRED_MEMBERS`) va ularni ADAPTER quradi
#:    (`export_adapter.py`). Bir xil nom ikki xil sxema — operator uchun ham, kod
#:    uchun ham tuzoq: papkani to'plam deb o'qishga urinish jimgina boshqa hujjatni
#:    validatorga berardi. Shu bois runtime paketi BOSHQA nom oladi.
#:
#: ⚠️ MANIFEST — PROVENANS DA'VOSI EMAS. U faqat YOZILGAN BAYTLARNING sha256'si:
#:    fayl nomi, bayt hajmi, sha256 — boshqa hech narsa. `source_copy`,
#:    `snapshot_at`, `plan_sha256` kabi MANBA provenansi maydonlari QO'SHILMAYDI:
#:    ular metadata razvedkasidan KELIB CHIQMAYDI, ya'ni yozilsa YOLG'ON kafolat
#:    bo'lardi (Phase 2 qoidasi ularni ataylab taqiqlagan).
RUNTIME_PACKAGE_REQUIRED: tuple[tuple[str, str | None], ...] = (
    ("export.json", "binos-1c-export-v1"),
    ("metadata.json", "binos-1c-metadata-v1"),
    ("run_status.json", "binos-1c-run-v1"),
    ("errors.json", "binos-1c-errors-v1"),
    ("run_summary.md", None),
    ("manifest.json", "binos-1c-manifest-v1"),
)

#: Ixtiyoriy a'zolar: faqat `APPROVED_PROBES` rejimida chiqadi.
RUNTIME_PACKAGE_OPTIONAL: tuple[str, ...] = ("probes/NN_<tur>.json",)

#: Manifestda RUXSAT ETILGAN YAGONA maydonlar (provenans maydonlari TAQIQLANGAN).
MANIFEST_ALLOWED_KEYS: tuple[str, ...] = ("name", "bytes", "sha256")
MANIFEST_FORBIDDEN_KEYS: tuple[str, ...] = ("source_copy", "snapshot_at", "plan_sha256")

# ── REJIMLAR ──────────────────────────────────────────────────────────────────────────────
#: ⚠️ DEFAULT HAR DOIM `METADATA_ONLY`: argument berilmasa ham, noma'lum rejim
#:    kelsa ham. Fail-safe — «balki zond ham kerak edi» degan taxmin mijoz bazasida
#:    amal bajarishga olib kelardi. Tanlov `run_status.json` da QAYD ETILADI, ya'ni
#:    noma'lum rejim JIMGINA metadata-only ga aylanmaydi.
MODE_METADATA_ONLY = "METADATA_ONLY"
MODE_APPROVED_PROBES = "APPROVED_PROBES"
MODES = (MODE_METADATA_ONLY, MODE_APPROVED_PROBES)
DEFAULT_MODE = MODE_METADATA_ONLY


def normalize_mode(xom: str | None) -> tuple[str, str | None]:
    """Rejimni fail-safe normallashtiradi: `(rejim, ogohlantirish)`.

    ⚠️ ISBOTLAYDI: bu FUNKSIYA noma'lum va bo'sh kirishni `METADATA_ONLY` ga
       aylantirishini va buning sababini QAYTARISHINI.
    ⚠️ ISBOTLAMAYDI: 1C tomonidagi kodning shu qoidani BAJARISHINI. BSL tomonida
       rejim tushunchasi BOR va u AYNI fail-safe qoidasiga yozilgan
       (`УстановитьРежимРазведки` / `ТекущийРежим` noma'lum va berilmagan rejimni
       `METADATA_ONLY` ga tushiradi, sababini `mode_note` da qoldiradi, noma'lum
       rejim uchun `mode` bo'limini `failed` qilib `REJECTED` xatosini yozadi) —
       lekin bu kod birorta 1C bazasida ishlatilmagan: `RUNTIME-UNKNOWN` aynan
       BAJARILISH haqida, mavjudlik haqida EMAS. Ikki tomonning rejim nomlari,
       defaulti va `overall` ta'rifi `tests/test_discovery_1c_conformance.py`
       darvozasi bilan solishtiriladi.
    """
    if xom is None or not str(xom).strip():
        return DEFAULT_MODE, ("rejim berilmadi — fail-safe "
                              f"{DEFAULT_MODE} tanlandi")
    nom = str(xom).strip()
    if nom in MODES:
        return nom, None
    return DEFAULT_MODE, (f"noma'lum rejim `{nom}` — fail-safe "
                          f"{DEFAULT_MODE} tanlandi")
