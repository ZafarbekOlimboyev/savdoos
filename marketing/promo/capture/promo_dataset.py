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
