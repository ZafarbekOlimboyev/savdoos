"""BinOS promo videosi uchun SINTETIK do'kon ma'lumoti.

Nega alohida dataset. Standart demo seed (`apps/server/app/seed.py`) testlar
uchun yozilgan: unda uchinchi tomon savdo belgilari bor (Coca-Cola, Pepsi,
Fanta, Nestle) va narxlar shartli (80 so'm). Reklamada boshqa kompaniya
belgisi ko'rinsa — bu ular tomonidan ma'qullangan degan taassurot beradi,
shartli narx esa mahsulotni o'yinchoqdek ko'rsatadi. Shu bois reklama
suratlari FAQAT shu ro'yxat bilan olinadi:

  * nomlar umumiy (brend yo'q), narxlar real bozor tartibida (so'm);
  * shtrix-kodlar seed'dagi bilan bir xil boshlanadi, lekin oxirgi raqami
    HAQIQIY EAN-13 nazorat raqami (seed kodlari tekshiruvdan o'tmaydi): videodagi
    stikerni telefon bilan skanerlasa ham aynan shu mahsulot chiqadi;
  * kategoriyalar, birliklar va qoldiqlar seed bilan AYNI — mahsulotning
    haqiqiy mantiqi (skan, qoldiq, kategoriya) o'zgarmaydi;
  * mijozlar — ism + bosh harf, telefonlar ataylab soxta ko'rinishda
    (+998 90 000 00 0X), real shaxsga ishora qilmaydi;
  * yetkazib beruvchilar — tavsifiy nomlar, real kompaniya emas.

⚠️  Bu fayl FAQAT lokal SQLite promo bazasini to'ldiradi
    (`capture/promo_backend.py`). Production'ga hech qachon yozilmaydi.
"""

# name, barcode, category, buy, sell, stock, min, unit  (seed.CATALOG bilan bir xil shakl)
CATALOG = [
    ("Limonad 0.5L",             "4780012340016", "Ichimliklar",       6500,  9000,  48, 10, "dona"),
    ("Gazli ichimlik 1L",        "4780012340023", "Ichimliklar",       8500, 12000,  36, 10, "dona"),
    ("Apelsin sharbati 1L",      "4780012340030", "Ichimliklar",      12000, 16000,  29, 10, "dona"),
    ("Toza suv 1.5L",            "4780012340047", "Ichimliklar",       3000,  5000, 120, 20, "dona"),
    ("Issiq non",                "4780012340054", "Oziq-ovqat",        3000,  4000,  64, 15, "dona"),
    ("Shakar 1kg",               "4780012340061", "Oziq-ovqat",       11000, 14000,  40, 10, "kg"),
    ("Guruch 1kg",               "4780012340078", "Oziq-ovqat",       17000, 22000,  33, 10, "kg"),
    ("Tuxum 10 dona",            "4780012340085", "Oziq-ovqat",       14500, 18000,  15,  5, "upak"),
    ("Kungaboqar yog‘i 1L", "4780012340092", "Oziq-ovqat",       21000, 26000,   4,  5, "litr"),
    ("Sut 1L",                   "4780012340108", "Sut mahsulotlari", 10000, 13000,  38, 10, "litr"),
    ("Kefir 1L",                 "4780012340115", "Sut mahsulotlari",  9000, 12000,  24,  8, "dona"),
    ("Tvorog 400g",              "4780012340122", "Sut mahsulotlari", 14000, 18000,   3,  5, "dona"),
    ("Shokolad 90g",             "4780012340139", "Shirinliklar",     11000, 15000,  52, 10, "dona"),
    ("Pechenye 300g",            "4780012340146", "Shirinliklar",      8000, 11000,  41, 10, "dona"),
    ("Konfet assorti 1kg",       "4780012340153", "Shirinliklar",     36000, 45000,  16,  5, "kg"),
    ("Sovun 90g",                "4780012340160", "Gigiyena",          4000,  6000,  44, 10, "dona"),
    ("Shampun 400ml",            "4780012340177", "Gigiyena",         25000, 32000,  12,  5, "dona"),
    ("Tish pastasi 100ml",       "4780012340184", "Gigiyena",         13000, 17000,   2,  5, "dona"),
    ("Salfetka 100 dona",        "4780012340191", "Gigiyena",          5000,  7000,  70, 15, "dona"),
]

CUSTOMERS = [
    ("Aziza K.",   "+998 90 000 00 01",  480000),
    ("Bekzod R.",  "+998 90 000 00 02",       0),
    ("Dildora S.", "+998 90 000 00 03", 1240000),
    ("Jahongir T.","+998 90 000 00 04",       0),
    ("Madina U.",  "+998 90 000 00 05",  320000),
]

SUPPLIERS = [
    ("Ichimliklar ta‘minotchisi", "+998 71 000 00 01",       0),
    ("Sut zavodi (namuna)",            "+998 71 000 00 02", 3150000),
    ("Oziq-ovqat bazasi",              "+998 71 000 00 03",       0),
    ("Shirinlik distribyutori",        "+998 71 000 00 04", 2100000),
    ("Gigiyena ta‘minotchisi",    "+998 71 000 00 05",       0),
]


# ── Boshqa tillar ─────────────────────────────────────────────────────────────
# POS valyuta belgisini TILGA qarab qo'yadi (`packages/shared/src/lib/format.ts`:
# uz → so'm, ru/ky → сом — Qirg'iziston). Shu bois rus va qirg'iz variantlarida
# narxlar SOM tartibida (o'zbekcha so'm narxi "9 000 сом" bo'lib chiqardi) va
# nomlar o'sha tilda. Shtrix-kodlar, kategoriya tartibi, birliklar va qoldiqlar
# o'zbekcha dataset bilan AYNI — skan ketma-ketligi va sahna tuzilishi o'zgarmaydi.

# barcode -> (ru nomi, ky nomi, kelish narxi, sotish narxi)  [so'm emas, SOM]
_KGS = {
    "4780012340016": ("Лимонад 0,5 л",              "Лимонад 0,5 л",              50,  70),
    "4780012340023": ("Газированный напиток 1 л",   "Газдалган суусундук 1 л",    65,  90),
    "4780012340030": ("Апельсиновый сок 1 л",       "Апельсин ширеси 1 л",       120, 160),
    "4780012340047": ("Вода питьевая 1,5 л",        "Ичүүчү суу 1,5 л",           30,  45),
    "4780012340054": ("Лепёшка",                    "Нан",                        25,  35),
    "4780012340061": ("Сахар 1 кг",                 "Кант 1 кг",                  75,  95),
    "4780012340078": ("Рис 1 кг",                   "Күрүч 1 кг",                115, 150),
    "4780012340085": ("Яйца 10 шт",                 "Жумуртка 10 даана",         100, 130),
    "4780012340092": ("Масло подсолнечное 1 л",     "Күн карама майы 1 л",       140, 180),
    "4780012340108": ("Молоко 1 л",                 "Сүт 1 л",                    65,  85),
    "4780012340115": ("Кефир 1 л",                  "Кефир 1 л",                  70,  90),
    "4780012340122": ("Творог 400 г",               "Творог 400 г",              140, 180),
    "4780012340139": ("Шоколад 90 г",               "Шоколад 90 г",               80, 110),
    "4780012340146": ("Печенье 300 г",              "Печенье 300 г",              70,  95),
    "4780012340153": ("Конфеты ассорти 1 кг",       "Ассорти момпосуй 1 кг",     350, 450),
    "4780012340160": ("Мыло 90 г",                  "Самын 90 г",                 32,  45),
    "4780012340177": ("Шампунь 400 мл",             "Шампунь 400 мл",            250, 320),
    "4780012340184": ("Зубная паста 100 мл",        "Тиш пастасы 100 мл",        115, 150),
    "4780012340191": ("Салфетки 100 шт",            "Салфетка 100 даана",         45,  60),
}

# o'zbekcha kategoriya -> (ru, ky)
_CATS = {
    "Ichimliklar":      ("Напитки",          "Суусундуктар"),
    "Oziq-ovqat":       ("Продукты",         "Азык-түлүк"),
    "Sut mahsulotlari": ("Молочные продукты", "Сүт азыктары"),
    "Shirinliklar":     ("Сладости",         "Таттуулар"),
    "Gigiyena":         ("Гигиена",          "Гигиена"),
}


def _localized(idx: int) -> dict:
    catalog = []
    for name, bc, cat, _buy, _sell, stock, mn, unit in CATALOG:
        loc = _KGS[bc]
        catalog.append((loc[idx], bc, _CATS[cat][idx], loc[2], loc[3], stock, mn, unit))
    return {"categories": [c[idx] for c in _CATS.values()], "catalog": catalog}


# Mijoz va yetkazib beruvchilar — Qirg'iziston raqamlari ataylab soxta ko'rinishda.
_KG_CUSTOMERS_RU = [("Айгуль К.", "+996 700 000 001", 4800), ("Бакыт Р.", "+996 700 000 002", 0),
                    ("Жылдыз С.", "+996 700 000 003", 12400), ("Нурлан Т.", "+996 700 000 004", 0),
                    ("Мээрим У.", "+996 700 000 005", 3200)]
_KG_CUSTOMERS_KY = [("Айгүл К.", "+996 700 000 001", 4800), ("Бакыт Р.", "+996 700 000 002", 0),
                    ("Жылдыз С.", "+996 700 000 003", 12400), ("Нурлан Т.", "+996 700 000 004", 0),
                    ("Мээрим У.", "+996 700 000 005", 3200)]
_KG_SUPPLIERS_RU = [("Поставщик напитков", "+996 312 000 001", 0), ("Молочный завод (образец)", "+996 312 000 002", 31500),
                    ("Продуктовая база", "+996 312 000 003", 0), ("Дистрибьютор сладостей", "+996 312 000 004", 21000),
                    ("Поставщик гигиены", "+996 312 000 005", 0)]
_KG_SUPPLIERS_KY = [("Суусундук жеткирүүчү", "+996 312 000 001", 0), ("Сүт заводу (үлгү)", "+996 312 000 002", 31500),
                    ("Азык-түлүк базасы", "+996 312 000 003", 0), ("Таттуулар дистрибьютору", "+996 312 000 004", 21000),
                    ("Гигиена жеткирүүчү", "+996 312 000 005", 0)]

DATASETS = {
    "uz": {"categories": None, "catalog": CATALOG, "customers": CUSTOMERS, "suppliers": SUPPLIERS,
           "store": None, "branch": None, "currency": "KGS"},
    "ru": {**_localized(0), "customers": _KG_CUSTOMERS_RU, "suppliers": _KG_SUPPLIERS_RU,
           "store": "Магазин «Алтын»", "branch": "Центральный филиал", "currency": "KGS"},
    "ky": {**_localized(1), "customers": _KG_CUSTOMERS_KY, "suppliers": _KG_SUPPLIERS_KY,
           "store": "«Алтын» дүкөнү", "branch": "Борбордук филиал", "currency": "KGS"},
}
# "uz" — tasdiqlangan proof suratlari aynan shu qiymatlar bilan olingan; o'zgartirilmaydi.
# `categories: None` / `store: None` — seed'dagi asl qiymat qoladi.
#
# VALYUTA: uchala datasetda `currency="KGS"` — promo/demo HAMMASI KGS (сом), ega qoidasi.
# `uz` ning RAQAMLARI ataylab TEGILMADI (yuqoridagi muzlatish + kurs o'ylab topish TAQIQ),
# shuning uchun ular hali ham ming tartibida; faqat valyuta e'loni KGS ga keltirildi.
#
# ⚠️  QOLGAN BO'SHLIQ (promo ichidan yopilmaydi): POS ekranidagi valyuta BELGISI
#     `packages/shared/src/lib/format.ts:14` da `CUR[lang]` dan olinadi — ya'ni TILGA bog'liq,
#     `company.currency` UMUMAN o'qilmaydi (o'sha faylning 4-qatoridagi TODO shuni tan oladi).
#     Chek ham shunday: `packages/shared/src/receipt/format.ts` → `currencyLabel(lang)`.
#     Demak `PROMO_LANG=uz` da ekranda baribir "so'm" chiqadi. Buni yopishning uch yo'li bor
#     va hammasi promo'dan TASHQARIDA: (1) `format.ts` ni `company.currency` dan o'qitish,
#     (2) `uz` ni promo tillaridan olib tashlab faqat ru/ky qoldirish, (3) `uz` narxlarini
#     KGS tartibiga keltirish (bu tasdiqlangan proof suratlarini bekor qiladi).
