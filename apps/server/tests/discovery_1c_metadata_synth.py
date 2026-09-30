# -*- coding: utf-8 -*-
"""SINTETIK `binos-1c-metadata-v1` INVENTARIZATSIYALARI — 15 xayoliy konfiguratsiya (A–O).

⚠️⚠️ BU YERDAGI HAMMA 1C NOMI — TO'QIMA. «Товарчик», «Tauarlar», «X17», «MasulJoylar» kabi
     nomlar ATAYLAB hech qanday haqiqiy mijoz konfiguratsiyasidan olinmagan. Agar fikstura
     haqiqiy nomlarni ishlatganda, testlar o'sha konfiguratsiya haqidagi TAXMINNI qulflab
     qo'yardi va heuristika «to'g'ri» ko'rinardi — aslida esa faqat bitta do'konga moslangan
     bo'lardi.

⚠️⚠️ HECH BIR SINTETIK FIKSTURA HAQIQIY 1C RUNTIME ISHLASHINI ISBOTLAMAYDI. Bu fayl 1C'ga
     ulanmaydi, `.epf` yig'uvchisini ishga tushirmaydi va biror konfiguratsiyada ekstraktor
     ishlashini KO'RSATMAYDI. U faqat TALQIN qatlamini sinaydi: graf, tahlil shartnomasi va
     zond rejasi turli tuzilmalarga QANDAY javob berishini.

⚠️⚠️ FIKSTURA «TO'G'RI JAVOB» EMAS. Shu bois `EXPECTED` da xarita qattiq yozilmaydi —
     unda KUTILGAN XULQ turadi (ikkilanish bo'lishi shart, qarshi dalil bo'lishi shart,
     `VERIFIED` bo'lmasligi shart). Heuristika o'zgarishi mumkin; INVARIANT o'zgarmaydi.

NIMA QAMRALGAN. Har bir konfiguratsiya bitta og'riq nuqtasini ushlab turadi:

    A  tipik rus nomlari                 J  ikkita jiddiy mahsulot nomzodi (AMBIGUOUS)
    B  rus, lekin nostandart nomlar      K  shtrix-kod alohida registrda
    C  qirg'iz nomlari                   L  o'lchov birligi BILVOSITA (ikki qadam)
    D  o'zbek lotin                      M  xarakteristikalar havolalar orqali
    E  o'zbek kirill                     N  qoldiq registrining g'alati o'lchovlari
    F  inglizcha nomlar                  O  qarama-qarshi dalil (nom ↔ struktura)
    G  mutlaqo tushunarsiz nomlar
    H  aldaydigan nomlar
    I  mahsulotga o'xshagan, lekin mahsulot EMAS

TILLARNING MA'NOSI. A–F bir XIL tuzilmani olti xil tilda takrorlaydi. Sabab: agar talqin
qatlami faqat rus nomlarini tushunsa, u xato emas — u FAQAT BITTA TILGA moslangan bo'ladi,
va bu nuqson boshqa do'konda birinchi kunda chiqadi. G esa tilni butunlay olib tashlaydi:
struktura o'zi bilan nimani ko'rsata olishi faqat shu yerda ko'rinadi.

PREFIKS HAQIDA. `full_name` boshidagi metadata turi (Справочник./РегистрСведений./Catalog.)
platformaning O'Z atamasi, obyekt nomi esa ishlab chiquvchi tanlagan nom. Shu bois D, E, N
da lotin/kirill nomlar rus prefiksi bilan turadi (aynan shunday bo'ladi), F va G da esa
ingliz prefiksi bilan — bu ikki xil platforma lokalizatsiyasi, fikstura ikkalasini ham
qamraydi.

STANDART REKVIZITLAR HAQIDA. A, B, C, H–M, O da standart rekvizitlar platforma nomi bilan
turadi (`Код`, `Наименование`), D, E, F, N da esa lokalizatsiya qilingan (`Kod`/`Коди`/
`Code`/`Nomi`). Bu QARAMA-QARSHILIK EMAS, ATAYLAB: ikki shakl ham uchraydi, va talqin
qatlami ikkalasini ham ko'rishi kerak. Bitta shaklni «standart» deb qabul qilgan joy
ikkinchisida jimgina bo'sh natija berardi.
"""
from __future__ import annotations

import copy

# ── Fikstura umumiy qiymatlari ─────────────────────────────────────────────────────────────
#: ⚠️ Vaqt FIKSTURANING KIRISHI, hisoblanmaydi. `Date.now()` kabi narsa bu yerda bo'lishi
#: mumkin emas: o'ylab chiqarilgan vaqt determinizmni buzadi va bir xil kirish har yurishda
#: boshqa bayt berardi (`binos-1c-metadata-v1` 8-invarianti).
COLLECTED_AT = "2026-09-30T09:00:00+05:00"

#: ⚠️ Versiyada `UNVERIFIED` ATAYLAB turadi: yig'uvchi hali birorta haqiqiy konfiguratsiyada
#: tasdiqlanmagan va fikstura buni yashirmasligi kerak.
COLLECTOR = {"name": "BinOSMetadataSweep", "version": "0.1.0-UNVERIFIED"}


# ── Yordamchilar ───────────────────────────────────────────────────────────────────────────
def field(name, kind, type_, *, synonym=None, refs=(), digits=None, scale=None,
          length=None) -> dict:
    """Bitta maydon (`FieldDoc`) — hamma kalit TO'LDIRILADI, tushib qolgan kalit RAD etiladi.

    ⚠️ `digits`/`scale`/`length` — MATN yoki `None`. JSON soni ataylab yozilmaydi: `"0013"`
    soni `13` bo'lib qolardi va boshidagi nollar bilan birga ma'no yo'qolardi.
    ⚠️ `type_` — platformaning XOM tip tavsifi. Fikstura uni bo'laklarga AJRATMAYDI: ajratish
    platforma versiyasiga bog'liq talqin bo'lardi, shu bois raqamli aniqlik va uzunlik
    alohida maydonlarda keladi."""
    return {
        "name": name,
        "synonym": synonym,
        "kind": kind,
        "type": type_,
        "reference_targets": list(refs),
        "numeric_digits": digits,
        "numeric_scale": scale,
        "string_length": length,
    }


def tabular(name, attributes, *, synonym=None) -> dict:
    """Jadval bo'limi (`TabularSectionDoc`)."""
    return {"name": name, "synonym": synonym, "attributes": list(attributes)}


def obj(full_name, kind, name, *, synonym=None, comment=None, hierarchical="false",
        row_count=None, attributes=(), dimensions=(), resources=(), tabular_sections=(),
        enum_values=(), predefined=(), register_kind=None, periodicity=None,
        errors=()) -> dict:
    """Bitta metadata obyekti (`ObjectDoc`).

    ⚠️ `hierarchical` — UCHULIK MATN: `"true"` / `"false"` / `"unknown"`. `"unknown"` =
    «yig'uvchi qaramadi», `"false"` = «qaradi va yo'q». Fikstura ikkisini QO'SHIB
    YUBORMAYDI, chunki aynan shu farq «qaralmadi» ni «yo'q» deb o'qishdan saqlaydi.
    ⚠️ `register_kind=None` = «bu obyekt registr emas». Ma'lumot registrlarida `"unknown"`
    yoziladi: shartnomada faqat `balance`/`turnover` bor, ma'lumot registri esa ikkalasi ham
    emas — ya'ni yig'uvchi uni ROSTDAN tasniflay olmaydi. Fikstura bu shartnoma savolini
    HAL QILMAYDI, faqat halol javob yozadi."""
    return {
        "full_name": full_name,
        "kind": kind,
        "name": name,
        "synonym": synonym,
        "comment": comment,
        "hierarchical": hierarchical,
        "row_count": row_count,
        "attributes": list(attributes),
        "dimensions": list(dimensions),
        "resources": list(resources),
        "tabular_sections": list(tabular_sections),
        "enum_values": list(enum_values),
        "predefined": list(predefined),
        "register_kind": register_kind,
        "periodicity": periodicity,
        "errors": list(errors),
    }


def section(name, status="ok", error=None) -> dict:
    """Yig'uvchining bo'limi: NIMANI urinib ko'rgani.

    ⚠️ Yiqilgan bo'lim JIMGINA TUSHIB QOLMAYDI — u sababi bilan ro'yxatda qoladi. Bo'sh
    bo'lim ro'yxati «hech narsa qaralmadi» degani va validator uni RAD etadi."""
    return {"name": name, "status": status, "error": error}


#: Yig'uvchi HAR SAFAR urinib ko'radigan bo'limlar. ⚠️ Bo'lim ro'yxati konfiguratsiyaga
#: bog'liq emas: u yig'uvchining o'z ish rejasi, ya'ni «nimaga qaradim» degan javob.
DEFAULT_SECTIONS = ("catalogs", "documents", "registers", "enums", "characteristic_plans",
                    "common_attributes", "counts")


def doc(objects, *, sections=None, notes=(), collected_at=COLLECTED_AT,
        collector=None) -> dict:
    """To'liq `binos-1c-metadata-v1` hujjati. Nusxa qaytariladi — chaqiruvchi o'zgartirsa
    fikstura buzilmaydi."""
    d = {
        "metadata_version": "binos-1c-metadata-v1",
        "collector": dict(collector or COLLECTOR),
        "collected_at": collected_at,
        "objects": list(objects),
        "sections": [section(n) for n in DEFAULT_SECTIONS] if sections is None
                    else list(sections),
        "notes": list(notes),
    }
    return copy.deepcopy(d)


# Tez-tez takrorlanadigan maydonlar. ⚠️ Faqat QISQARTMA: bular «standart mahsulot maydoni»
# degan bilim EMAS, shunchaki fiksturada bir necha marta yozilishi kerak bo'lgan shakl.
def _kod(length="11", *, name="Код"):
    return field(name, "standard_attribute", f"Строка({length})", length=length)


def _nom(length="100", *, name="Наименование"):
    return field(name, "standard_attribute", f"Строка({length})", length=length)


def _son(name, digits="15", scale="3", *, kind="resource"):
    return field(name, kind, f"Число({digits},{scale})", digits=digits, scale=scale)


def _ssilka(name, target, *, kind="attribute", prefix="СправочникСсылка"):
    """Havola maydoni: tip tavsifi + `reference_targets`.

    ⚠️ `reference_targets` hujjatdagi HAQIQIY bog'lanish; uni tip matnidan CHIQARIB OLISH
    talqin bo'lardi, shu bois fiksturada ikkisi ALOHIDA yoziladi."""
    return field(name, kind, f"{prefix}.{target.split('.', 1)[1]}", refs=[target])


# ══════════════════════════════════════════════════════════════════════════════════════════
# A — TIPIK RUS KONFIGURATSIYASI
# ⚠️ SINAYDI: eng qulay holat — nom, tuzilma va munosabatlar hammasi bir yo'nalishni
#    ko'rsatadi. Talqin qatlami shu yerda nomzod TOPMASA, qolgan 14 tasida umuman umid yo'q.
# ⚠️ ISBOTLAMAYDI: bu yerda topilgan nomzod TO'G'RI ekanini. Nom mosligi kuchsiz dalil va
#    A ning o'zi ham `VERIFIED` bermaydi — hatto hamma dalil bir joyga qaraganda ham.
# ⚠️ `hierarchical="true"` ATAYLAB: haqiqiy mahsulot katalogi ODATDA ierarxik. Ya'ni
#    ierarxiklikning O'ZI «bu mahsulot emas» degan dalil BO'LA OLMAYDI (I va O ni qarang).
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_A_STANDARD_RU = doc(
    [
        obj("Справочник.Товары", "catalog", "Товары", synonym="Товары",
            hierarchical="true", row_count="4021",
            attributes=[
                _kod(), _nom(),
                field("ЭтоГруппа", "standard_attribute", "Булево"),
                field("ПометкаУдаления", "standard_attribute", "Булево"),
                field("Артикул", "attribute", "Строка(25)", length="25"),
                _ssilka("ЕдиницаИзмерения", "Справочник.ЕдиницыИзмерения"),
                field("Весовой", "attribute", "Булево"),
                field("КодВесовой", "attribute", "Строка(5)", length="5"),
            ]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
            attributes=[_kod("9"), _nom("50")]),
        obj("Справочник.ЕдиницыИзмерения", "catalog", "ЕдиницыИзмерения",
            synonym="Единицы измерения", row_count="14",
            attributes=[_kod("3"), _nom("25")]),
        obj("РегистрСведений.ШтрихКодыТоваров", "information_register", "ШтрихКодыТоваров",
            synonym="Штрих-коды товаров", row_count="3115",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Товар", "Справочник.Товары", kind="dimension")],
            resources=[field("ШтрихКод", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ОстаткиНаСкладах", "accumulation_register",
            "ОстаткиНаСкладах", synonym="Остатки на складах", row_count="18904",
            register_kind="balance",
            dimensions=[_ssilka("Товар", "Справочник.Товары", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
        obj("Документ.РеализацияТоваров", "document", "РеализацияТоваров",
            synonym="Реализация товаров", row_count="52310",
            attributes=[field("Номер", "standard_attribute", "Строка(11)", length="11"),
                        field("Дата", "standard_attribute", "Дата"),
                        _ssilka("Склад", "Справочник.Склады")],
            tabular_sections=[tabular("Товары", [
                _ssilka("Товар", "Справочник.Товары"),
                _son("Количество", kind="attribute"),
                _son("Цена", digits="15", scale="2", kind="attribute"),
            ])]),
    ],
    notes=["sintetik fikstura — nomlar to'qima, hech qanday haqiqiy konfiguratsiyadan olinmagan"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# B — RUS TILI, LEKIN NOSTANDART NOMLAR
# ⚠️ SINAYDI: ma'no A dagi bilan AYNAN bir xil, nomlar esa boshqa. Agar talqin qatlami
#    A da ishlab B da ishlamasa, u ma'noni emas, LUG'ATNI o'qigan bo'ladi — va bu nuqson
#    har bir «o'zi uchun moslashtirilgan» konfiguratsiyada chiqadi.
# ⚠️ ISBOTLAMAYDI: struktura bo'yicha topilgan nomzodning to'g'riligini. Struktura A dagi
#    bilan bir xil bo'lgani uchun bu yerda faqat NOMGA BOG'LIQLIK o'lchanadi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_B_CUSTOM_RU = doc(
    [
        obj("Справочник.Товарчик", "catalog", "Товарчик", synonym="Товарчики наши",
            hierarchical="true", row_count="3760",
            attributes=[
                _kod(), _nom(),
                field("ЭтоГруппа", "standard_attribute", "Булево"),
                field("НомерчикАртикула", "attribute", "Строка(25)", length="25"),
                _ssilka("МеркаШтучная", "Справочник.МеркиШтучные"),
                field("НаВесах", "attribute", "Булево"),
            ]),
        obj("Справочник.СкладикОсновной", "catalog", "СкладикОсновной",
            synonym="Складик основной", row_count="4", attributes=[_kod("9"), _nom("50")]),
        obj("Справочник.МеркиШтучные", "catalog", "МеркиШтучные", synonym="Мерки штучные",
            row_count="11", attributes=[_kod("3"), _nom("25")]),
        obj("РегистрСведений.КодикиШтрих", "information_register", "КодикиШтрих",
            synonym="Кодики штрих", row_count="2480",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Товарчик", "Справочник.Товарчик", kind="dimension")],
            resources=[field("Кодик", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ОстаточкиТекущие", "accumulation_register",
            "ОстаточкиТекущие", synonym="Остаточки текущие", row_count="14022",
            register_kind="balance",
            dimensions=[_ssilka("Товарчик", "Справочник.Товарчик", kind="dimension"),
                        _ssilka("Складик", "Справочник.СкладикОсновной", kind="dimension")],
            resources=[_son("Штуки")]),
    ],
    notes=["ma'no A bilan bir xil, nomlar boshqa — nomga bog'liqlikni o'lchaydi"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# C — QIRG'IZ NOMLARI
# ⚠️ SINAYDI: rus lug'atiga tushmaydigan til. Nomlar tanish atamalarga UZOQDAN o'xshaydi
#    (`Tauarlar`, `Skladdar`), ya'ni qisman moslik talqin qatlamini yolg'on ishonchga
#    olib borishi mumkin.
# ⚠️ ISBOTLAMAYDI: qirg'iz konfiguratsiyalarida ekstraktor ishlashini. Bu nomlar to'qima va
#    haqiqiy do'konda tuzilma boshqacha bo'lishi mumkin.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_C_KYRGYZ = doc(
    [
        obj("Справочник.Tauarlar", "catalog", "Tauarlar", synonym="Товарлар",
            hierarchical="true", row_count="2588",
            attributes=[_kod(), _nom(),
                        field("Artikul", "attribute", "Строка(25)", length="25"),
                        _ssilka("Birdik", "Справочник.Birdikter"),
                        field("Tarazduu", "attribute", "Булево")]),
        obj("Справочник.Skladdar", "catalog", "Skladdar", synonym="Складдар", row_count="5",
            attributes=[_kod("9"), _nom("50")]),
        obj("Справочник.Birdikter", "catalog", "Birdikter", synonym="Бирдиктер",
            row_count="11", attributes=[_kod("3"), _nom("25")]),
        obj("РегистрСведений.Shtrihkoddor", "information_register", "Shtrihkoddor",
            synonym="Штрихкоддор", row_count="1990",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Tauar", "Справочник.Tauarlar", kind="dimension")],
            resources=[field("Kod", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.Kaldyktar", "accumulation_register", "Kaldyktar",
            synonym="Калдыктар", row_count="9877", register_kind="balance",
            dimensions=[_ssilka("Tauar", "Справочник.Tauarlar", kind="dimension"),
                        _ssilka("Sklad", "Справочник.Skladdar", kind="dimension")],
            resources=[_son("San")]),
    ],
    notes=["qirg'iz nomlari — qisman moslik yolg'on ishonch berishi mumkin"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# D — O'ZBEK LOTIN
# ⚠️ SINAYDI: lotin yozuvidagi o'zbek nomlari rus prefiksi bilan — aynan shunday bo'ladi,
#    chunki metadata turi prefiksini PLATFORMA beradi, obyekt nomini esa ishlab chiquvchi.
# ⚠️ ISBOTLAMAYDI: hech bir o'zbek do'konida ishlashni. Bu shunchaki yozuv tizimi sinovi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_D_UZBEK_LATIN = doc(
    [
        obj("Справочник.Mahsulot", "catalog", "Mahsulot", synonym="Mahsulotlar",
            hierarchical="true", row_count="3120",
            attributes=[field("Kod", "standard_attribute", "Строка(11)", length="11"),
                        field("Nomi", "standard_attribute", "Строка(100)", length="100"),
                        field("Artikul", "attribute", "Строка(25)", length="25"),
                        _ssilka("Birlik", "Справочник.Birliklar"),
                        field("Vaznli", "attribute", "Булево"),
                        field("PluKodi", "attribute", "Строка(5)", length="5")]),
        obj("Справочник.Ombor", "catalog", "Ombor", synonym="Omborlar", row_count="7",
            attributes=[field("Kod", "standard_attribute", "Строка(9)", length="9"),
                        field("Nomi", "standard_attribute", "Строка(50)", length="50")]),
        obj("Справочник.Birliklar", "catalog", "Birliklar", synonym="O'lchov birliklari",
            row_count="12",
            attributes=[field("Kod", "standard_attribute", "Строка(3)", length="3"),
                        field("Nomi", "standard_attribute", "Строка(25)", length="25")]),
        obj("РегистрСведений.Shtrixkod", "information_register", "Shtrixkod",
            synonym="Shtrix kodlar", row_count="2604",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Mahsulot", "Справочник.Mahsulot", kind="dimension")],
            resources=[field("Shtrix", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.Qoldiq", "accumulation_register", "Qoldiq",
            synonym="Qoldiqlar", row_count="15330", register_kind="balance",
            dimensions=[_ssilka("Mahsulot", "Справочник.Mahsulot", kind="dimension"),
                        _ssilka("Ombor", "Справочник.Ombor", kind="dimension")],
            resources=[_son("Soni")]),
    ],
    notes=["o'zbek lotin nomlari, rus prefikslari — platforma shunday yozadi"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# E — O'ZBEK KIRILL
# ⚠️ SINAYDI: kirill, LEKIN rus tili EMAS. `Маҳсулот` da `ҳ` bor — rus alifbosida yo'q harf.
#    Shu bois «kirill = rus» deb qaragan har qanday normalizatsiya shu yerda yiqiladi.
# ⚠️ ISBOTLAMAYDI: kirill yozuvli do'konda ekstraktorning ishlashini.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_E_UZBEK_CYRILLIC = doc(
    [
        obj("Справочник.Маҳсулот", "catalog", "Маҳсулот", synonym="Маҳсулотлар",
            hierarchical="true", row_count="2140",
            attributes=[field("Коди", "standard_attribute", "Строка(11)", length="11"),
                        field("Номи", "standard_attribute", "Строка(100)", length="100"),
                        field("Артикули", "attribute", "Строка(25)", length="25"),
                        _ssilka("Бирлик", "Справочник.Бирликлар"),
                        field("Вазнли", "attribute", "Булево")]),
        obj("Справочник.Омбор", "catalog", "Омбор", synonym="Омборлар", row_count="3",
            attributes=[field("Коди", "standard_attribute", "Строка(9)", length="9"),
                        field("Номи", "standard_attribute", "Строка(50)", length="50")]),
        obj("Справочник.Бирликлар", "catalog", "Бирликлар", synonym="Ўлчов бирликлари",
            row_count="9",
            attributes=[field("Коди", "standard_attribute", "Строка(3)", length="3"),
                        field("Номи", "standard_attribute", "Строка(25)", length="25")]),
        obj("РегистрСведений.Штрихкодлар", "information_register", "Штрихкодлар",
            synonym="Штрих кодлар", row_count="1755",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Маҳсулот", "Справочник.Маҳсулот", kind="dimension")],
            resources=[field("Штрих", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.Қолдиқлар", "accumulation_register", "Қолдиқлар",
            synonym="Қолдиқлар", row_count="8412", register_kind="balance",
            dimensions=[_ssilka("Маҳсулот", "Справочник.Маҳсулот", kind="dimension"),
                        _ssilka("Омбор", "Справочник.Омбор", kind="dimension")],
            resources=[_son("Сони")]),
    ],
    notes=["o'zbek kirill — `ҳ`, `қ` harflari rus alifbosida yo'q"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# F — INGLIZCHA NOMLAR
# ⚠️ SINAYDI: ingliz lokalizatsiyasidagi platforma — prefiks ham, tip tavsifi ham inglizcha
#    (`String(13)`, `Number(15,3)`). Ya'ni tip matnini RUS shakliga bog'lab qo'ygan har
#    qanday joy shu yerda ochiladi.
# ⚠️ ISBOTLAMAYDI: ingliz konfiguratsiyasi bilan ishlashni; tip matnini talqin qilish
#    kerak bo'lsa, u ALOHIDA sinalishi kerak (graf uni ataylab ajratmaydi).
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_F_ENGLISH = doc(
    [
        obj("Catalog.Products", "catalog", "Products", synonym="Products",
            hierarchical="true", row_count="1880",
            attributes=[field("Code", "standard_attribute", "String(11)", length="11"),
                        field("Description", "standard_attribute", "String(100)",
                              length="100"),
                        field("IsFolder", "standard_attribute", "Boolean"),
                        field("Article", "attribute", "String(25)", length="25"),
                        field("Unit", "attribute", "CatalogRef.Units",
                              refs=["Catalog.Units"]),
                        field("Weighted", "attribute", "Boolean")]),
        obj("Catalog.Warehouses", "catalog", "Warehouses", synonym="Warehouses",
            row_count="4",
            attributes=[field("Code", "standard_attribute", "String(9)", length="9"),
                        field("Description", "standard_attribute", "String(50)",
                              length="50")]),
        obj("Catalog.Units", "catalog", "Units", synonym="Units of measure", row_count="8",
            attributes=[field("Code", "standard_attribute", "String(3)", length="3"),
                        field("Description", "standard_attribute", "String(25)",
                              length="25")]),
        obj("InformationRegister.Barcodes", "information_register", "Barcodes",
            synonym="Barcodes", row_count="1402",
            register_kind="unknown", periodicity="Nonperiodical",
            dimensions=[field("Product", "dimension", "CatalogRef.Products",
                              refs=["Catalog.Products"])],
            resources=[field("Barcode", "resource", "String(13)", length="13")]),
        obj("RegisterAccumulation.StockBalance", "accumulation_register", "StockBalance",
            synonym="Stock balance", row_count="7710", register_kind="balance",
            dimensions=[field("Product", "dimension", "CatalogRef.Products",
                              refs=["Catalog.Products"]),
                        field("Warehouse", "dimension", "CatalogRef.Warehouses",
                              refs=["Catalog.Warehouses"])],
            resources=[field("Quantity", "resource", "Number(15,3)", digits="15",
                             scale="3")]),
    ],
    notes=["ingliz lokalizatsiyasi: prefiks va tip tavsifi ham inglizcha"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# G — MUTLAQO TUSHUNARSIZ NOMLAR
# ⚠️ SINAYDI: NOMDAN HECH NARSA BILINMAYDIGAN holat. Sinonim yo'q, izoh yo'q, maydonlar
#    `F1`, `D1`, `M1`. Lekin STRUKTURA TO'LIQ SAQLANGAN:
#      · `RegisterAccumulation.R41` (balance) ning o'lchovi `Catalog.X17` ga havola qiladi,
#      · `InformationRegister.ABCD` ning o'lchovi HAM `Catalog.X17` ga havola qiladi va
#        resursi 13 uzunlikdagi satr,
#      · `Catalog.X23` esa faqat balans registrining ikkinchi o'lchovida uchraydi.
#    Ya'ni bu yerda struktura O'ZI BILAN nimani ko'rsata olishi o'lchanadi — lug'at emas.
# ⚠️ ISBOTLAMAYDI: strukturadan chiqqan nomzodning to'g'riligini. `X17` mahsulot bo'lishi ham,
#    umuman boshqa narsa bo'lishi ham mumkin: 13 uzunlikdagi satr shtrix-kod BO'LISHI SHART
#    emas. Shu bois G dan chiqadigan eng yuqori natija — DALILI STRUKTURAL bo'lgan nomzod,
#    va u AMBIGUOUS bo'lishi ham to'g'ri javob.
# ⚠️ Tushunarsiz nom — «yig'uvchi qaramadi» degani EMAS: `hierarchical="false"` (qaradi va
#    yo'q), sinonim esa rostdan bo'sh. Farq `sections` da ham ko'rinadi: hamma bo'lim `ok`.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_G_OPAQUE = doc(
    [
        obj("Catalog.X17", "catalog", "X17", row_count="2904",
            attributes=[field("F1", "attribute", "String(9)", length="9"),
                        field("F2", "attribute", "String(60)", length="60"),
                        field("F3", "attribute", "Boolean")]),
        obj("Catalog.X23", "catalog", "X23", row_count="5",
            attributes=[field("F1", "attribute", "String(4)", length="4"),
                        field("F2", "attribute", "String(40)", length="40")]),
        obj("InformationRegister.ABCD", "information_register", "ABCD", row_count="2631",
            register_kind="unknown", periodicity="Nonperiodical",
            dimensions=[field("D1", "dimension", "CatalogRef.X17", refs=["Catalog.X17"])],
            resources=[field("V1", "resource", "String(13)", length="13")]),
        obj("RegisterAccumulation.R41", "accumulation_register", "R41", row_count="11208",
            register_kind="balance",
            dimensions=[field("D1", "dimension", "CatalogRef.X17", refs=["Catalog.X17"]),
                        field("D2", "dimension", "CatalogRef.X23", refs=["Catalog.X23"])],
            resources=[field("M1", "resource", "Number(15,3)", digits="15", scale="3")]),
    ],
    notes=["nomlar ma'nosiz, sinonim yo'q — faqat struktura qoldi",
           "sinonimlar rostdan bo'sh: bo'limlar `ok`, ya'ni «qaralmadi» EMAS"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# H — ALDAYDIGAN NOMLAR
# ⚠️ SINAYDI: nom bilan ma'no QARAMA-QARSHI turgan holat.
#      · `Справочник.Товары` — nomi mahsulotdan boshqa narsani aytmaydi, lekin ichida
#        hujjat SHABLONLARI turadi va unga BIRORTA registr havola qilmaydi;
#      · `Справочник.КарточкиУчета` — nomi hisob kartochkasi, lekin qoldiq registri ham,
#        kod registri ham AYNAN unga havola qiladi va unda artikul, birlik, vaznlilik bor.
#    Nom bo'yicha ishlagan talqin `Товары` ni tanlaydi va JIMGINA xato qiladi.
# ⚠️ ISBOTLAMAYDI: «registr havola qilsa — bu mahsulot» degan qoidani. H da struktura
#    to'g'ri javobga olib boradi, lekin bu FIKSTURA shunday tuzilgani uchun; qoida sifatida
#    u faqat kuchsiz `structural_link` dalili bo'lib qoladi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_H_MISLEADING = doc(
    [
        obj("Справочник.Товары", "catalog", "Товары", synonym="Товары",
            comment="hujjat matni shablonlari ro'yxati", hierarchical="true",
            row_count="58",
            attributes=[_nom("80"),
                        field("ТекстШаблона", "attribute", "Строка(0)", length="0"),
                        field("ПрименяетсяКДокументу", "attribute", "Строка(60)",
                              length="60")]),
        obj("Справочник.КарточкиУчета", "catalog", "КарточкиУчета",
            synonym="Карточки учета", row_count="3890",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("ЕдиницаХранения", "Справочник.ЕдиницыХранения"),
                        field("Весовой", "attribute", "Булево")]),
        obj("Справочник.ЕдиницыХранения", "catalog", "ЕдиницыХранения",
            synonym="Единицы хранения", row_count="10", attributes=[_kod("3"), _nom("25")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрСведений.КодыМаркировки", "information_register", "КодыМаркировки",
            synonym="Коды маркировки", row_count="3115",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Позиция", "Справочник.КарточкиУчета", kind="dimension")],
            resources=[field("Значение", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ДвижениеПоСкладам", "accumulation_register",
            "ДвижениеПоСкладам", synonym="Движение по складам", row_count="16740",
            register_kind="balance",
            dimensions=[_ssilka("Позиция", "Справочник.КарточкиУчета", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["nom bilan ma'no qarama-qarshi: nomi mos kelgan katalog aslida shablonlar ro'yxati"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# I — MAHSULOTGA O'XSHAGAN, LEKIN MAHSULOT EMAS
# ⚠️ SINAYDI: `Справочник.ТоварныеГруппы` nomi mos, ierarxik, lekin:
#      · unga BIRORTA registr havola qilmaydi,
#      · narx, birlik, artikul, vaznlilik maydoni YO'Q,
#      · qoldiq registrining o'lchovi esa hujjatda UMUMAN YO'Q obyektga havola qiladi.
#    Ya'ni haqiqiy mahsulot INVENTARIZATSIYADAN TASHQARIDA qolgan va buni `sections` ochiq
#    aytadi (`catalogs_extension` — `skipped`). Kutilgan xulq: nomzod YO'Q yoki juda past,
#    va `unresolved_references` YO'QOLMAYDI.
# ⚠️ ISBOTLAMAYDI: bunday holatda javob «mahsulot yo'q» ekanini. To'g'ri javob — «BU
#    HUJJATDA topilmadi, chunki bir bo'lim o'qilmagan». «Qaralmadi» ≠ «yo'q», va aniqlanmagan
#    havolani jimgina o'chirib tashlash aynan shu farqni yo'q qiladi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_I_PRODUCTLIKE_NOT_PRODUCT = doc(
    [
        obj("Справочник.ТоварныеГруппы", "catalog", "ТоварныеГруппы",
            synonym="Товарные группы", hierarchical="true", row_count="42",
            attributes=[_nom("80"),
                        field("Описание", "attribute", "Строка(0)", length="0")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрНакопления.ОстаткиПоСкладам", "accumulation_register",
            "ОстаткиПоСкладам", synonym="Остатки по складам", row_count="9120",
            register_kind="balance",
            dimensions=[_ssilka("Позиция", "Справочник.ВнешниеПозиции", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    sections=[section(n) for n in DEFAULT_SECTIONS] + [
        section("catalogs_extension", "skipped",
                "kengaytma obyektlari o'qilmadi — «qaralmadi», «yo'q» EMAS"),
    ],
    notes=["qoldiq registri hujjatda YO'Q obyektga havola qiladi — aniqlanmagan havola",
           "nomi mos kelgan katalogga birorta registr havola qilmaydi"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# J — IKKITA JIDDIY MAHSULOT NOMZODI
# ⚠️ SINAYDI: TANLAB BO'LMAYDIGAN holat. `ТоварыОсновные` va `ТоварыДополнительные` —
#    ikkisi ham katalog, ikkisining ham nomi mos, ikkisiga ham ALOHIDA balans registri
#    havola qiladi, ikkisining maydon tarkibi ham bir xil. Ustiga shtrix-kod registrining
#    o'lchovi IKKALASIGA birga havola qiladi (ko'p tipli havola).
# ⚠️ KUTILGAN XULQ: `AMBIGUOUS`. Bittasini tanlab, ikkinchisini jimgina tashlab ketish —
#    eng xavfli natija, chunki u xato bo'lsa ham ishonchli KO'RINADI.
# ⚠️ ISBOTLAMAYDI: qaysi biri «haqiqiy» ekanini — hujjatdagi ma'lumot bilan bu savolga
#    javob BERILMAYDI. Javob faqat operator ko'rigidan yoki zonddan keladi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_J_MULTIPLE_PRODUCT_CATALOGS = doc(
    [
        obj("Справочник.ТоварыОсновные", "catalog", "ТоварыОсновные",
            synonym="Товары основные", hierarchical="true", row_count="2100",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("Единица", "Справочник.Единицы"),
                        field("Весовой", "attribute", "Булево")]),
        obj("Справочник.ТоварыДополнительные", "catalog", "ТоварыДополнительные",
            synonym="Товары дополнительные", hierarchical="true", row_count="1850",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("Единица", "Справочник.Единицы"),
                        field("Весовой", "attribute", "Булево")]),
        obj("Справочник.Единицы", "catalog", "Единицы", synonym="Единицы", row_count="9",
            attributes=[_kod("3"), _nom("25")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="5",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрСведений.КодыШтрих", "information_register", "КодыШтрих",
            synonym="Коды штрих", row_count="3010",
            register_kind="unknown", periodicity="НеПериодический",
            # ⚠️ Ko'p tipli o'lchov: bitta maydon IKKI obyektga havola qiladi. Grafda bu
            #    ikki `references` qirrasi bo'ladi, ya'ni ikkilanish STRUKTURADA turadi.
            dimensions=[field("Объект", "dimension",
                              "СправочникСсылка.ТоварыОсновные, СправочникСсылка.ТоварыДополнительные",
                              refs=["Справочник.ТоварыДополнительные",
                                    "Справочник.ТоварыОсновные"])],
            resources=[field("Код", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ОстаткиОсновные", "accumulation_register",
            "ОстаткиОсновные", synonym="Остатки основные", row_count="8900",
            register_kind="balance",
            dimensions=[_ssilka("Товар", "Справочник.ТоварыОсновные", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
        obj("РегистрНакопления.ОстаткиДополнительные", "accumulation_register",
            "ОстаткиДополнительные", synonym="Остатки дополнительные", row_count="7410",
            register_kind="balance",
            dimensions=[_ssilka("Товар", "Справочник.ТоварыДополнительные",
                                kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["ikki teng kuchli nomzod — tanlash EMAS, ikkilanishni AYTISH kutiladi"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# K — SHTRIX-KOD MAHSULOT KATALOGIDA EMAS
# ⚠️ SINAYDI: mahsulot katalogida 13 uzunlikdagi satr UMUMAN YO'Q — kod faqat alohida
#    ma'lumot registrida turadi (o'lchovi mahsulotga havola, resursi `Строка(13)`).
#    Katalog maydonlarini kezib chiqib «kod yo'q» degan xulosaga kelgan talqin xato qiladi.
# ⚠️ Registrda IKKI resurs bor (`Код` va `Основной`): bittasi satr, bittasi bulevo. Ya'ni
#    «registrning yagona resursi — kod» degan taxmin ham shu yerda sinaladi.
# ⚠️ ISBOTLAMAYDI: `Строка(13)` ning shtrix-kod ekanini. Uzunlik — kuchsiz `type_shape`
#    dalili; EAN-13 nazorat raqami tekshirilmaguncha bu faqat nomzod.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_K_BARCODE_IN_REGISTER = doc(
    [
        obj("Справочник.Продукция", "catalog", "Продукция", synonym="Продукция",
            hierarchical="true", row_count="2670",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("Единица", "Справочник.Единицы")]),
        obj("Справочник.Единицы", "catalog", "Единицы", synonym="Единицы", row_count="9",
            attributes=[_kod("3"), _nom("25")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрСведений.КодыУпаковок", "information_register", "КодыУпаковок",
            synonym="Коды упаковок", row_count="4180",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Продукт", "Справочник.Продукция", kind="dimension")],
            resources=[field("Код", "resource", "Строка(13)", length="13"),
                       field("Основной", "resource", "Булево")]),
        obj("РегистрНакопления.ОстаткиПродукции", "accumulation_register",
            "ОстаткиПродукции", synonym="Остатки продукции", row_count="12050",
            register_kind="balance",
            dimensions=[_ssilka("Продукт", "Справочник.Продукция", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["katalogda 13 uzunlikdagi satr yo'q — kod faqat registrda"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# L — O'LCHOV BIRLIGI BILVOSITA (IKKI QADAM)
# ⚠️ SINAYDI: mahsulot → `КлассификаторЕдиниц` → `БазовыеЕдиницы`. Ya'ni birlikni topish
#    uchun IKKI havola bo'ylab yurish kerak, birinchi havola esa «klassifikator», ya'ni
#    birlikning O'ZI emas. Bir qadam bilan to'xtagan talqin klassifikatorni birlik deb
#    o'qiydi va koeffitsientni butunlay o'tkazib yuboradi.
# ⚠️ ISBOTLAMAYDI: zanjirning ma'nosini. `Коэффициент` ni ko'chirish qoidasi bu hujjatda
#    YO'Q; zanjirni ko'rish bilan uni to'g'ri qo'llash bir narsa emas.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_L_UNIT_INDIRECT = doc(
    [
        obj("Справочник.Изделия", "catalog", "Изделия", synonym="Изделия",
            hierarchical="true", row_count="1420",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("ЕдиницаХранения", "Справочник.КлассификаторЕдиниц")]),
        obj("Справочник.КлассификаторЕдиниц", "catalog", "КлассификаторЕдиниц",
            synonym="Классификатор единиц", row_count="24",
            attributes=[_nom("30"),
                        _ssilka("БазоваяЕдиница", "Справочник.БазовыеЕдиницы"),
                        _son("Коэффициент", digits="10", scale="3", kind="attribute")]),
        obj("Справочник.БазовыеЕдиницы", "catalog", "БазовыеЕдиницы",
            synonym="Базовые единицы", row_count="7", attributes=[_kod("3"), _nom("20")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="4",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрСведений.КодыИзделий", "information_register", "КодыИзделий",
            synonym="Коды изделий", row_count="1610",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Изделие", "Справочник.Изделия", kind="dimension")],
            resources=[field("Код", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ОстаткиИзделий", "accumulation_register", "ОстаткиИзделий",
            synonym="Остатки изделий", row_count="6380", register_kind="balance",
            dimensions=[_ssilka("Изделие", "Справочник.Изделия", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["birlik ikki havola orqali: mahsulot → klassifikator → bazaviy birlik"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# M — XARAKTERISTIKALAR ПланВидовХарактеристик VA HAVOLALAR ORQALI
# ⚠️ SINAYDI: qo'shimcha maydonlar obyektning O'Z rekvizit ro'yxatida KO'RINMAYDI. Zanjir:
#    `Продукты` → `ПланВидовХарактеристик.СвойстваПродуктов` → `Справочник.ЗначенияСвойств`,
#    ustiga qiymatlar katalogi egasi bo'lgan rejaga QAYTA havola qiladi (ikki yo'nalishli
#    bog'lanish). Qoldiq registrida ham alohida `Характеристика` o'lchovi bor.
# ⚠️ ISBOTLAMAYDI: bu zanjirdan o'tib qiymat O'QISHNI. Reja tarkibini ko'rish — qiymat qaysi
#    jadvalda saqlanganini bilish EMAS; buni faqat zond yoki operator ko'rigi aniqlaydi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_M_CHARACTERISTICS_VIA_REFERENCE = doc(
    [
        obj("Справочник.Продукты", "catalog", "Продукты", synonym="Продукты",
            hierarchical="true", row_count="980",
            attributes=[_kod(), _nom(),
                        field("ВидХарактеристики", "attribute",
                              "ПланВидовХарактеристикСсылка.СвойстваПродуктов",
                              refs=["ПланВидовХарактеристик.СвойстваПродуктов"])]),
        obj("ПланВидовХарактеристик.СвойстваПродуктов", "chart_of_characteristic_types",
            "СвойстваПродуктов", synonym="Свойства продуктов", row_count="18",
            attributes=[_nom("50"),
                        _ssilka("ТипЗначения", "Справочник.ЗначенияСвойств")],
            predefined=["ЦветУпаковки", "РазмерУпаковки"]),
        obj("Справочник.ЗначенияСвойств", "catalog", "ЗначенияСвойств",
            synonym="Значения свойств", hierarchical="true", row_count="230",
            attributes=[_nom("60"),
                        field("Владелец", "standard_attribute",
                              "ПланВидовХарактеристикСсылка.СвойстваПродуктов",
                              refs=["ПланВидовХарактеристик.СвойстваПродуктов"])]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="4",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрНакопления.ОстаткиПродуктов", "accumulation_register",
            "ОстаткиПродуктов", synonym="Остатки продуктов", row_count="5420",
            register_kind="balance",
            dimensions=[_ssilka("Продукт", "Справочник.Продукты", kind="dimension"),
                        _ssilka("Характеристика", "Справочник.ЗначенияСвойств",
                                kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["qo'shimcha maydonlar rekvizit ro'yxatida ko'rinmaydi — reja va havola orqali"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# N — QOLDIQ REGISTRINING G'ALATI O'LCHOVLARI
# ⚠️ SINAYDI: balans registrida OMBOR O'LCHOVI YO'Q. O'rniga `MasulJoy` (mas'ul joy) va
#    `Partiya` turadi, resurslari esa IKKI XIL aniqlikdagi son (`Число(15,3)` va
#    `Число(15,2)`). «Qoldiq registri = mahsulot + ombor» deb qattiq yozilgan har qanday
#    shakl tekshiruvi shu yerda yiqiladi yoki — battari — omborni `MasulJoy` deb o'qiydi.
# ⚠️ ISBOTLAMAYDI: `MasulJoy` ning ombor EMASLIGINI. Hujjatdan buni bilib bo'lmaydi va
#    aynan shu sababli javob nomzod darajasida qolishi kerak: nom boshqa, rol noma'lum.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_N_UNUSUAL_STOCK_DIMENSIONS = doc(
    [
        obj("Справочник.Mahsulotlar", "catalog", "Mahsulotlar", synonym="Mahsulotlar",
            hierarchical="true", row_count="3410",
            attributes=[field("Kod", "standard_attribute", "Строка(11)", length="11"),
                        field("Nomi", "standard_attribute", "Строка(100)", length="100"),
                        _ssilka("Birlik", "Справочник.Birliklar")]),
        obj("Справочник.MasulJoylar", "catalog", "MasulJoylar", synonym="Mas'ul joylar",
            row_count="12",
            attributes=[field("Kod", "standard_attribute", "Строка(6)", length="6"),
                        field("Nomi", "standard_attribute", "Строка(40)", length="40")]),
        obj("Справочник.Partiyalar", "catalog", "Partiyalar", synonym="Partiyalar",
            row_count="740",
            attributes=[field("Nomi", "standard_attribute", "Строка(40)", length="40"),
                        field("Sana", "attribute", "Дата")]),
        obj("Справочник.Birliklar", "catalog", "Birliklar", synonym="Birliklar",
            row_count="8",
            attributes=[field("Kod", "standard_attribute", "Строка(3)", length="3"),
                        field("Nomi", "standard_attribute", "Строка(25)", length="25")]),
        obj("РегистрСведений.Shtrixkodlar", "information_register", "Shtrixkodlar",
            synonym="Shtrix kodlar", row_count="2890",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Mahsulot", "Справочник.Mahsulotlar", kind="dimension")],
            resources=[field("Shtrix", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.QoldiqHarakati", "accumulation_register", "QoldiqHarakati",
            synonym="Qoldiq harakati", row_count="20480", register_kind="balance",
            # ⚠️ OMBOR O'LCHOVI YO'Q — bu buzuq hujjat EMAS, boshqacha qurilgan hisob.
            dimensions=[_ssilka("Mahsulot", "Справочник.Mahsulotlar", kind="dimension"),
                        _ssilka("MasulJoy", "Справочник.MasulJoylar", kind="dimension"),
                        _ssilka("Partiya", "Справочник.Partiyalar", kind="dimension")],
            resources=[_son("Soni"), _son("Summa", digits="15", scale="2")]),
    ],
    notes=["balans registrida ombor o'lchovi yo'q; resurslari ikki xil aniqlikdagi son"],
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# O — QARAMA-QARSHI DALIL (NOM ↔ STRUKTURA)
# ⚠️ SINAYDI: dalillar BIR-BIRIGA QARSHI turgan holat.
#      · `Справочник.Товары` — nomi mukammal mos, LEKIN ierarxik, ichida faqat nom va
#        kirish guruhi bor, unga birorta qoldiq registri havola QILMAYDI;
#      · `Справочник.УчетныеЕдиницы` — nomi «hisob birliklari», ya'ni mahsulotdan uzoq va
#        ataylab birlik katalogiga o'xshaydi, LEKIN kod registri ham, balans registri ham
#        unga havola qiladi va unda kod, artikul, birlik havolasi, vaznlilik bor.
#    ⚠️ KUTILGAN XULQ: nomga qarab tanlanmasin va qarshi dalil YOZILSIN. Ikkilanishni
#    ochiq aytish ham, past ishonchli nomzod ham to'g'ri; jimgina `Товары` ni tanlash —
#    YO'Q. Aynan shu holat H dan farq qiladi: H da yolg'on nomzodning boshqa ma'nosi
#    hujjatda AYTILGAN (shablonlar), O da esa hech qanday tushuntirish yo'q — faqat
#    bo'sh struktura.
# ⚠️ ISBOTLAMAYDI: qaysi biri haqiqiy ekanini. Hatto struktura bir yoqqa qaraganda ham
#    javob `VERIFIED` bo'lmaydi: buning uchun operator tasdig'i yoki arifmetik isbot kerak.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_O_CONTRADICTORY = doc(
    [
        obj("Справочник.Товары", "catalog", "Товары", synonym="Товары",
            hierarchical="true", row_count="64",
            attributes=[_nom("80"),
                        field("ГруппаДоступа", "attribute", "Строка(30)", length="30")]),
        obj("Справочник.УчетныеЕдиницы", "catalog", "УчетныеЕдиницы",
            synonym="Учетные единицы", row_count="3305",
            attributes=[_kod(), _nom(),
                        field("Артикул", "attribute", "Строка(25)", length="25"),
                        _ssilka("ЕдиницаИзмерения", "Справочник.Измерители"),
                        field("Весовой", "attribute", "Булево")]),
        obj("Справочник.Измерители", "catalog", "Измерители", synonym="Измерители",
            row_count="9", attributes=[_kod("3"), _nom("25")]),
        obj("Справочник.Склады", "catalog", "Склады", synonym="Склады", row_count="6",
            attributes=[_kod("9"), _nom("50")]),
        obj("РегистрСведений.КодыПозиций", "information_register", "КодыПозиций",
            synonym="Коды позиций", row_count="2740",
            register_kind="unknown", periodicity="НеПериодический",
            dimensions=[_ssilka("Позиция", "Справочник.УчетныеЕдиницы", kind="dimension")],
            resources=[field("Код", "resource", "Строка(13)", length="13")]),
        obj("РегистрНакопления.ОстаткиПозиций", "accumulation_register", "ОстаткиПозиций",
            synonym="Остатки позиций", row_count="13980", register_kind="balance",
            dimensions=[_ssilka("Позиция", "Справочник.УчетныеЕдиницы", kind="dimension"),
                        _ssilka("Склад", "Справочник.Склады", kind="dimension")],
            resources=[_son("Количество")]),
    ],
    notes=["nom bir obyektni, struktura boshqasini ko'rsatadi — qarshi dalil yozilishi shart"],
)


# ══════════════════════════════════════════════════════════════════════════════════════════
# HAMMA KONFIGURATSIYA
# ⚠️ Tartiblangan: harf → hujjat. Determinizm uchun tartib SHARTNOMA — testlar bu lug'atni
#    kezib chiqadi va tartib o'zgarsa yurishlar bir-biriga o'xshamay qoladi.
# ══════════════════════════════════════════════════════════════════════════════════════════
ALL_CONFIGS: dict[str, dict] = {
    "A": CONFIG_A_STANDARD_RU,
    "B": CONFIG_B_CUSTOM_RU,
    "C": CONFIG_C_KYRGYZ,
    "D": CONFIG_D_UZBEK_LATIN,
    "E": CONFIG_E_UZBEK_CYRILLIC,
    "F": CONFIG_F_ENGLISH,
    "G": CONFIG_G_OPAQUE,
    "H": CONFIG_H_MISLEADING,
    "I": CONFIG_I_PRODUCTLIKE_NOT_PRODUCT,
    "J": CONFIG_J_MULTIPLE_PRODUCT_CATALOGS,
    "K": CONFIG_K_BARCODE_IN_REGISTER,
    "L": CONFIG_L_UNIT_INDIRECT,
    "M": CONFIG_M_CHARACTERISTICS_VIA_REFERENCE,
    "N": CONFIG_N_UNUSUAL_STOCK_DIMENSIONS,
    "O": CONFIG_O_CONTRADICTORY,
}


def config(letter: str) -> dict:
    """Nusxasini qaytaradi. ⚠️ Nusxa SHART: test hujjatni o'zgartirib sinasa (buzuq kalit,
    tushib qolgan maydon), asl fikstura keyingi testga buzilgan holda o'tib ketardi."""
    if letter not in ALL_CONFIGS:
        raise KeyError(f"bunday konfiguratsiya yo'q: {letter!r} — bori {sorted(ALL_CONFIGS)}")
    return copy.deepcopy(ALL_CONFIGS[letter])


# ══════════════════════════════════════════════════════════════════════════════════════════
# KUTILGAN XULQ
# ⚠️ BU YERDA «TO'G'RI JAVOB» QATTIQ YOZILMAYDI. Sabab: heuristika o'zgaradi — bugun
#    `Справочник.КарточкиУчета` ni topadigan qoida ertaga boshqacha ball qo'yishi mumkin va
#    bu o'zi bilan nuqson EMAS. Nuqson — INVARIANTNING buzilishi: `VERIFIED` chiqishi,
#    ikkilanishning yashirilishi, qarshi dalilning yozilmasligi, aniqlanmagan havolaning
#    jimgina o'chirilishi. Shu bois pastda faqat XULQ yoziladi.
# ⚠️ `leksik_yetarli` HAR JOYDA `False`: nom mosligi O'ZI BILAN hech qachon tasdiqlangan
#    xarita bermaydi (5-qoida). U alohida kalit sifatida turadi, chunki invariant sifatida
#    tekshirilishi kerak — izohda qolsa, u faqat niyat bo'lib qoladi.
# ══════════════════════════════════════════════════════════════════════════════════════════

#: Yig'uvchi ham, model ham, graf ham CHIQARA OLMAYDIGAN holatlar.
#: ⚠️ `VERIFIED` — bu kanalda umuman yo'q (`ai.FORBIDDEN_STATUS`).
#: ⚠️ `HUMAN_CONFIRMED` shartnomada BOR, lekin u FAQAT operatorning alohida tasdiq
#:    hujjatidan keladi; AI chiqishida uchrasa validator RAD etadi — model ishonchi
#:    qanchalik yuqori bo'lishidan qat'i nazar.
AI_TAQIQLANGAN_HOLATLAR = ("HUMAN_CONFIRMED", "VERIFIED")

# Xulq nomlari (qattiq javob EMAS, XULQ).
XULQ_NOMZOD_KUTILADI = "NOMZOD_KUTILADI"           # nomzod bo'lishi mumkin, lekin CANDIDATE dan oshmaydi
XULQ_AMBIGUOUS_SHART = "AMBIGUOUS_SHART"           # tanlash EMAS, ikkilanishni aytish
XULQ_NOMZOD_YOQ_YOKI_PAST = "NOMZOD_YOQ_YOKI_PAST"  # nomzod yo'q, yoki bor bo'lsa past ball
XULQ_FAQAT_STRUKTURA = "FAQAT_STRUKTURA_DALILI"    # nomdan hech narsa chiqmaydi
XULQ_QARSHI_DALIL_SHART = "QARSHI_DALIL_SHART"     # xulosa qarshi dalil bilan birga keladi
XULQLAR = (XULQ_AMBIGUOUS_SHART, XULQ_FAQAT_STRUKTURA, XULQ_NOMZOD_KUTILADI,
           XULQ_NOMZOD_YOQ_YOKI_PAST, XULQ_QARSHI_DALIL_SHART)

#: Har bir yozuvda bo'lishi SHART bo'lgan kalitlar — test shu shaklni tekshirsin.
EXPECTED_KEYS = frozenset({"xulq", "sinaydi", "isbotlamaydi", "ambiguous_shart",
                           "qarshi_dalil_shart", "leksik_yetarli",
                           "aniqlanmagan_havola_shart", "taqiqlangan_holatlar"})

EXPECTED: dict[str, dict] = {
    "A": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "eng qulay holat — nom, tuzilma va munosabatlar bir yo'nalishda",
        "isbotlamaydi": "topilgan nomzodning to'g'riligini; bu yerda ham VERIFIED yo'q",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "B": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "ma'no A bilan bir xil, nom boshqa — lug'atga bog'liqlik o'lchanadi",
        "isbotlamaydi": "nostandart nomli haqiqiy konfiguratsiyada ishlashni",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "C": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "qirg'iz nomlari; qisman moslik yolg'on ishonch bermasin",
        "isbotlamaydi": "qirg'iz do'konida ekstraktor ishlashini",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "D": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "o'zbek lotin nomlari rus prefiksi bilan",
        "isbotlamaydi": "hech bir haqiqiy o'zbek konfiguratsiyasida ishlashni",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "E": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "kirill, lekin rus EMAS — `ҳ`/`қ` harflari «kirill = rus» taxminini buzadi",
        "isbotlamaydi": "kirill yozuvli do'konda ishlashni",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "F": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "ingliz lokalizatsiyasi: prefiks va XOM tip tavsifi ham inglizcha",
        "isbotlamaydi": "tip matnini talqin qilishni — graf uni ataylab ajratmaydi",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "G": {
        "xulq": XULQ_FAQAT_STRUKTURA,
        "sinaydi": "nomdan HECH NARSA bilinmaydi; struktura va munosabatlar saqlangan",
        "isbotlamaydi": "strukturadan chiqqan nomzodning to'g'riligini — `String(13)` "
                        "shtrix-kod BO'LISHI SHART emas",
        "ambiguous_shart": False,   # ikkilanish ham to'g'ri javob, lekin SHART emas
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "H": {
        "xulq": XULQ_QARSHI_DALIL_SHART,
        "sinaydi": "nomi mos katalog aslida boshqa narsa; registrlar BOSHQA obyektga havola qiladi",
        "isbotlamaydi": "«registr havola qilsa — mahsulot» degan qoidani; bu kuchsiz "
                        "`structural_link` dalili bo'lib qoladi",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": True,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "I": {
        "xulq": XULQ_NOMZOD_YOQ_YOKI_PAST,
        "sinaydi": "nomi mos, lekin registr havolasi yo'q, narx/birlik yo'q; haqiqiy obyekt "
                   "inventarizatsiyadan TASHQARIDA (o'qilmagan bo'lim)",
        "isbotlamaydi": "«mahsulot yo'q» degan xulosani — to'g'ri javob «BU HUJJATDA topilmadi»",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": True,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": True,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "J": {
        "xulq": XULQ_AMBIGUOUS_SHART,
        "sinaydi": "ikki teng kuchli nomzod — ikkisiga ham registr havola qiladi, ikkisining "
                   "nomi ham mos, shtrix-kod o'lchovi IKKALASIGA havola qiladi",
        "isbotlamaydi": "qaysi biri haqiqiy ekanini — javob zonddan yoki operatordan keladi",
        "ambiguous_shart": True,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "K": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "shtrix-kod katalogda YO'Q, alohida registrda; registrda ikki resurs",
        "isbotlamaydi": "`Строка(13)` ning shtrix-kod ekanini — uzunlik kuchsiz dalil",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "L": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "birlik ikki qadam orqali; bir qadamda to'xtash klassifikatorni birlik deb o'qiydi",
        "isbotlamaydi": "koeffitsientni to'g'ri qo'llashni — bu qoida hujjatda yo'q",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "M": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "qo'shimcha maydonlar rekvizit ro'yxatida ko'rinmaydi — reja va havola orqali",
        "isbotlamaydi": "zanjirdan o'tib qiymat o'qishni",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "N": {
        "xulq": XULQ_NOMZOD_KUTILADI,
        "sinaydi": "balans registrida ombor o'lchovi YO'Q; resurslari ikki xil aniqlikdagi son",
        "isbotlamaydi": "`MasulJoy` ning ombor emasligini — hujjatdan bilinmaydi, shu bois "
                        "javob nomzod darajasida qolishi kerak",
        "ambiguous_shart": False,
        "qarshi_dalil_shart": False,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
    "O": {
        "xulq": XULQ_QARSHI_DALIL_SHART,
        "sinaydi": "nom bir obyektni, struktura boshqasini ko'rsatadi; nomi mos obyektning "
                   "hech qanday tushuntirishi YO'Q — faqat bo'sh struktura",
        "isbotlamaydi": "qaysi biri haqiqiy ekanini; struktura bir yoqqa qaraganda ham "
                        "VERIFIED bermaydi",
        "ambiguous_shart": False,   # ikkilanish ham, past ballli nomzod ham to'g'ri
        "qarshi_dalil_shart": True,
        "leksik_yetarli": False,
        "aniqlanmagan_havola_shart": False,
        "taqiqlangan_holatlar": AI_TAQIQLANGAN_HOLATLAR,
    },
}


# ══════════════════════════════════════════════════════════════════════════════════════════
# SIR SINOVI — ATAYLAB RAD ETILADIGAN FIKSTURA
# ⚠️ Bu YAGONA fikstura ichida sirga o'xshash matn bor va u `ALL_CONFIGS` ga ATAYLAB
#    KIRITILMAGAN: `ALL_CONFIGS` dagi hamma hujjat `validate_metadata` dan O'TISHI shart,
#    bu esa O'TMASLIGI shart.
# ⚠️ Sir A dagi TO'QIMA nomlar ustiga qo'yilgan `comment` ichida: ulanish satri bo'lagi.
#    Haqiqiy parol yoki haqiqiy server nomi EMAS — `redact.VALUE_PATTERNS` ni qo'zg'atadigan
#    SHAKL. Kutilgan natija: `MetadataError` (fail-closed).
# ⚠️ NEGA KERAK: yig'uvchi obyekt izohini 1C dan XOM oladi va operator o'sha izohga ulanish
#    satrini yozib qo'ygan bo'lishi mumkin. Agar validator faqat to'plamning «sir maydonlari»
#    ni qarasa, bu satr inventarizatsiya bilan birga qo'ldan-qo'lga o'tib ketardi.
# ══════════════════════════════════════════════════════════════════════════════════════════
CONFIG_SECRET_LEAK = doc(
    [
        obj("Справочник.Товары", "catalog", "Товары", synonym="Товары",
            comment="almashinuv bazasi: Srvr=sinov-srv;Ref=sinov;Usr=sinovchi",
            hierarchical="true", row_count="4021",
            attributes=[_kod(), _nom()]),
    ],
    notes=["ATAYLAB buzuq fikstura — sir shakli bor, validator RAD etishi SHART"],
)

#: ⚠️ Kutilgan natija XULQ sifatida yozilgan: xato MATNI emas, RAD ETILISHI. Xato matni
#: o'zgarishi mumkin; fail-closed qoida o'zgarmasligi kerak.
SECRET_LEAK_EXPECTED = {
    "xulq": "RAD_ETILADI",
    "sinaydi": "obyekt izohiga tushgan ulanish satri bo'lagini validator tutishini",
    "isbotlamaydi": "hamma sir shaklini tutishni — `redact` naqshlari to'liq ro'yxat EMAS",
    "xato_turi": "MetadataError",
}
