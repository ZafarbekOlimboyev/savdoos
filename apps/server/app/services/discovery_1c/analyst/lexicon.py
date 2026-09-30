# -*- coding: utf-8 -*-
"""KO'P TILLI LEKSIK QATLAM — deterministik normalizatsiya va KUCHSIZ ishoralar.

⚠️ LEKSIK MOSLIK O'ZI BILAN HECH QACHON TASDIQLANGAN XARITA BERMAYDI. Bu modulning butun
   chiqishi — `schema.WEAK_EVIDENCE_KINDS` ichidagi `name_match` / `synonym_match` darajasidagi
   dalil, ya'ni `CANDIDATE` dan yuqorisiga yetmaydi. Kengaytirilgan yoki qo'lda o'zgartirilgan
   konfiguratsiyada nom bir xil, ma'no esa boshqa bo'lishi mumkin — aynan shu sabab.

⚠️ NEGA BU FAYL YADRODAN TASHQARIDA. Yadroning statik qo'riqchisi yadro manbasida
   konfiguratsiyaga oid AMALIY nom bo'lmasligini talab qiladi, ko'p tilli lug'at esa aynan
   shunday so'zlardan iborat. Shu bois TALQIN bilimi deterministik yadrodan AJRATILGAN va
   `analyst/` paketida yashaydi. Yadro bu faylni import qilmaydi.

⚠️ ISHORALAR LOTIN SHAKLIDA SAQLANADI — bu ataylab, ikki sabab bilan:
   (1) taqqoslash BIR XIL bo'shliqda ketadi: kirish matni ham `to_latin(normalize(...))` dan
       o'tadi, ya'ni rus, o'zbek kirill, o'zbek lotin va qirg'iz shakllari bitta lug'atga
       tushadi;
   (2) lug'atning o'zi yadroning qo'riqchisiga tegmaydi.
   Bu invariant import paytida TEKSHIRILADI (`_check_tables`): lotinlashtirilmagan ishora
   qo'shilsa modul import qilinishida yiqiladi, testda emas.

DETERMINIZM: translyatsiya jadvali kod nuqtasi bo'yicha tartiblangan, har ishora ro'yxati
alifbo bo'yicha tartiblangan va takrorsiz. Bir xil matn — AYNAN bir xil tokenlar va ball.
"""
from __future__ import annotations

import unicodedata

#: Ishoralarda va normalizatsiya natijasida ishlatiladigan YAGONA apostrof.
APOSTROPHE = "'"

#: Apostrofning boshqa yozilishlari. O'zbek lotin yozuvida `oʻ`/`gʻ` uchun turli belgi
#: ishlatiladi, matn esa qo'ldan yozilgani uchun ular aralashib keladi.
#: ⚠️ Bu almashtirish diakritika olib tashlashdan OLDIN bajariladi: `ʻ` va `ʼ` — harf
#:    turkumidagi belgilar (`Lm`), ya'ni ular filtrda harf bo'lib omon qolardi.
_APOSTROPHE_VARIANTS = "'`´ʹʻʼʽ‘’‛′"

#: Kirill kod nuqtalarining oralig'i.
#: ⚠️ Diakritika olib tashlash kirill harflariga TEGMAYDI: `NFD` ba'zi kirill harflarini
#:    asos + belgi ga ajratadi, ya'ni ular translyatsiyadan OLDIN boshqa harfga aylanib
#:    ketardi va talaffuz bilan birga ma'no yo'qolardi.
_CYRILLIC_FIRST = "Ѐ"
_CYRILLIC_LAST = "ӿ"


class LexiconError(ValueError):
    """Leksik qatlamga noma'lum konsept yoki matn bo'lmagan qiymat berildi.

    `ValueError` dan meros: bu kirishning xatosi, hujjat shartnomasining buzilishi emas."""


# ── Kirill -> lotin ────────────────────────────────────────────────────────────────────────
#: Translyatsiya jadvali. Kalitlar KOD NUQTASI bo'yicha tartiblangan (import paytida
#: tekshiriladi), qiymatlar lotin.
#: ⚠️ Jadval UCH yozuvni qamraydi: rus, o'zbek kirill (qo'shimcha harflari bilan) va qirg'iz
#:    (qo'shimcha harflari bilan). Bitta jadval ataylab: uch yozuv bir matnda aralashib
#:    kelishi mumkin, uchta alohida jadval esa qaysi birini qo'llash haqida taxmin talab
#:    qilardi.
#: ⚠️ Qattiq va yumshoq belgi BO'SH satrga aylanadi — ular lotin shaklida yo'q.
CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a",    # a
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",     # qattiq belgi — lotin shaklida yo'q
    "ы": "y",
    "ь": "",     # yumshoq belgi — lotin shaklida yo'q
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "ё": "yo",
    "ў": "o" + APOSTROPHE,   # o'zbek kirill
    "ғ": "g" + APOSTROPHE,   # o'zbek kirill
    "қ": "q",                # o'zbek kirill
    "ҥ": "ng",               # qirg'iz
    "ү": "u",                # qirg'iz
    "ҳ": "h",                # o'zbek kirill
    "ө": "o",                # qirg'iz
}


def _is_cyrillic(ch: str) -> bool:
    return _CYRILLIC_FIRST <= ch <= _CYRILLIC_LAST


def _strip_diacritics(text: str) -> str:
    """Lotin diakritikasini olib tashlaydi, kirill harflariga TEGMAYDI.

    ⚠️ Kirill himoyasi ataylab: `NFD` ba'zi kirill harflarini asos harf + belgi ga ajratadi,
       belgini tashlab yuborish esa ularni BOSHQA harfga aylantirardi va translyatsiya
       jadvalidagi yozuvi ishlamay qolardi."""
    bo_laklar: list[str] = []
    for ch in text:
        if _is_cyrillic(ch):
            bo_laklar.append(ch)
            continue
        ajralgan = unicodedata.normalize("NFD", ch)
        bo_laklar.append("".join(c for c in ajralgan if not unicodedata.combining(c)))
    return unicodedata.normalize("NFC", "".join(bo_laklar))


def normalize(text: str) -> str:
    """Matnni taqqoslash bo'shlig'iga keltiradi: kichik harf, diakritikasiz, tinishsiz.

    Qadamlar (tartibi SHARTNOMA):
      1. `NFC` — bir xil harfning ikki xil yozilishi bitta shaklga keladi;
      2. kichik harf;
      3. apostrofning hamma yozilishi bitta `'` ga;
      4. lotin diakritikasi olib tashlanadi (kirill saqlanadi);
      5. harf, raqam va apostrofdan boshqa hamma narsa BO'SHLIQQA aylanadi — ya'ni tinish
         belgisi ham, pastki tire ham so'z ajratuvchisi bo'lib qoladi;
      6. ketma-ket bo'shliqlar bittaga, chetlari qirqiladi.

    ⚠️ Bu funksiya KICHIK HARFGA keltiradi, ya'ni CamelCase ma'lumoti yo'qoladi. Shu bois
       `tokens()` bo'lishni XOM matnda bajaradi va normalizatsiyani undan KEYIN qo'llaydi."""
    if not isinstance(text, str):
        raise LexiconError(f"normalize matn kutadi, kelgani {type(text).__name__}")

    s = unicodedata.normalize("NFC", text).lower()
    for ch in _APOSTROPHE_VARIANTS:
        if ch != APOSTROPHE:
            s = s.replace(ch, APOSTROPHE)
    s = _strip_diacritics(s)
    s = "".join(ch if (ch.isalnum() or ch == APOSTROPHE) else " " for ch in s)
    return " ".join(s.split())


def to_latin(text: str) -> str:
    """Kirill harflarini lotinga o'giradi. Lotin va raqamlar o'zgarmaydi.

    ⚠️ Chiqish KICHIK harfda bo'ladi: jadval kichik harfli, katta kirill harfi esa kichigining
       o'girmasi bilan almashtiriladi. Taqqoslash kichik harfda ketadi, shu bois bu yo'qotish
       emas."""
    if not isinstance(text, str):
        raise LexiconError(f"to_latin matn kutadi, kelgani {type(text).__name__}")

    bo_laklar: list[str] = []
    for ch in text:
        o_girma = CYRILLIC_TO_LATIN.get(ch)
        if o_girma is None:
            o_girma = CYRILLIC_TO_LATIN.get(ch.lower())
        bo_laklar.append(ch if o_girma is None else o_girma)
    return "".join(bo_laklar)


def _split_camel(text: str) -> list[str]:
    """XOM matnni CamelCase chegaralarida bo'ladi (katta-kichik harf o'tishi bo'yicha).

    ⚠️ Registr (harf katta-kichikligi) bilan ishlaydi, harflarning ro'yxati bilan EMAS: shu
       bois u kirill, lotin va aralash yozuvda bir xil ishlaydi va yozuv qo'shilganda
       o'zgartirish talab qilmaydi.
    ⚠️ Ikki naqsh bir vaqtda hisobga olinadi: kichik->KATTA (yangi so'z boshlandi) va
       KATTA-ketma-ketligi->kichik (oxirgi katta harf keyingi so'zning boshi). Ikkinchisi
       bo'lmasa qisqartma bilan boshlangan nom bitta bo'lak bo'lib qolardi."""
    bo_laklar: list[str] = []
    joriy = ""
    oldingi: str | None = None
    for ch in text:
        if joriy and ch.isupper() and oldingi is not None and (oldingi.islower() or oldingi.isdigit()):
            bo_laklar.append(joriy)
            joriy = ch
        elif (len(joriy) > 1 and ch.islower() and oldingi is not None and oldingi.isupper()):
            bo_laklar.append(joriy[:-1])
            joriy = joriy[-1] + ch
        else:
            joriy += ch
        oldingi = ch
    if joriy:
        bo_laklar.append(joriy)
    return bo_laklar


def tokens(text: str) -> tuple[str, ...]:
    """Matnni taqqoslashga tayyor tokenlarga bo'ladi (tartib SAQLANADI, takror OLIB
    TASHLANMAYDI).

    Oqim: CamelCase bo'lish (XOM matnda) -> `normalize` -> `to_latin` -> bo'shliq bo'yicha
    bo'lish. Pastki tire va tinish belgisi `normalize` da bo'shliqqa aylanadi, ya'ni ular ham
    so'z ajratuvchisi.

    ⚠️ Harf va raqam chegarasida BO'LINMAYDI: qisqartma bilan raqam ko'pincha bitta atama
       bo'ladi va ularni ajratish mavjud ishorani buzardi."""
    if not isinstance(text, str):
        raise LexiconError(f"tokens matn kutadi, kelgani {type(text).__name__}")

    natija: list[str] = []
    for bo_lak in _split_camel(text):
        tayyor = to_latin(normalize(bo_lak))
        natija.extend(so_z for so_z in tayyor.split(" ") if so_z)
    return tuple(natija)


# ── Ball berish chegaralari ────────────────────────────────────────────────────────────────
#: To'liq token mosligi — eng kuchli LEKSIK signal (lekin baribir KUCHSIZ dalil).
SCORE_EXACT = 0.90
#: Prefiks mosligi: tokenning boshi ishora bilan (yoki teskarisi) ustma-ust tushadi.
SCORE_PREFIX = 0.55
#: Substring mosligi — ENG PAST ball: ishora tokenning o'rtasida uchrashi tasodif bo'lishi
#: mumkin (masalan qisqa bo'lak uzun boshqa so'z ichida).
SCORE_SUBSTRING = 0.25

#: Prefiks va substring uchun eng kichik uzunlik.
#: ⚠️ Qisqa ishora (`kg`, `plu`, `vat`) faqat TO'LIQ moslikda hisobga olinadi: uch harfli
#:    bo'lak tasodifan boshqa so'zda uchrab, jimgina yolg'on dalil berardi.
PREFIX_MIN_LEN = 4
SUBSTRING_MIN_LEN = 5

#: Qo'shimcha moslik uchun bonus va uning chegarasi.
#: ⚠️ Bonus CHEGARALANGAN, aks holda bir nechta substring mosligi bitta prefiks mosligidan
#:    kuchli bo'lib ketardi va «to'liq > prefiks > substring» tartibi buzilardi.
SCORE_BONUS_STEP = 0.05
SCORE_BONUS_MAX_HITS = 3


# ── Ko'p tilli KUCHSIZ ishoralar ───────────────────────────────────────────────────────────
#: Konsept ID (`ai.CONCEPTS` dan) -> shu konseptga ishora qilishi MUMKIN bo'lgan shakllar.
#: Har ro'yxatda rus, o'zbek kirill, o'zbek lotin, qirg'iz va ingliz shakllari hamda amalda
#: uchraydigan qisqartmalar bor — HAMMASI lotinlashtirilgan holda.
#: ⚠️ BU ISHORALAR KUCHSIZ. Ro'yxatda turgan nom topilgani biror narsani ISBOTLAMAYDI: u faqat
#:    odam ko'rigining navbatini belgilashga yaraydi.
#: ⚠️ Ro'yxatlar ataylab KENG: yo'qolgan ishora — ko'rinmay qolgan nomzod, ortiqcha ishora esa
#:    faqat past ballli taxmin. Ikkinchisi arzonroq xato.
CONCEPT_CLUES: dict[str, tuple[str, ...]] = {
    "product": (
        "buyum", "goods", "item", "items", "izdelie", "mahsulot", "mahsulotlar", "maxsulot",
        # ⚠️ `nomenklatur` — ATAYLAB o'zak: kelishik qo'shimchasi bilan kelgan shakl to'liq
        # moslikka tushmaydi, o'zak esa prefiks moslik berib uni tutib oladi.
        "nomenklatur", "nomenklatura", "product", "products", "produkciya", "produkt",
        "tauar", "tauarlar",
        "tov", "tovar", "tovarlar", "tovarov", "tovary",
    ),
    "sku_article": (
        "art", "article", "artikl", "artikul", "code", "kod", "kodi", "nomer", "number",
        "shifr", "sku",
    ),
    "barcode": (
        "barcode", "barcodes", "barkod", "barkodi", "barkodlar", "ean", "ean13", "gtin",
        "shtrih", "shtrihkod", "shtrihkody", "shtrihovoy", "shtrikh", "shtrix", "shtrixkod",
        "upc",
    ),
    "unit_of_measure": (
        "birdik", "birligi", "birlik", "birliklar", "ed", "edinica", "edinicy", "izm",
        "izmerenie", "izmereniya", "measure", "measurement", "o'lchov", "o'lchovi", "olchom",
        "olchov", "unit", "units", "uom",
    ),
    "product_variant": (
        "characteristic", "characteristics", "color", "cvet", "harakteristika",
        "harakteristiki", "modifikaciya", "olcham", "rang", "razmer", "size", "svoystvo",
        "variant", "variantlar", "varianty", "xarakteristika",
    ),
    "warehouse": (
        "depot", "kampa", "ombor", "omborlar", "omborxona", "sklad", "skladov", "skladskoy",
        "sklady", "storage", "storehouse", "warehouse", "warehouses",
    ),
    "stock_balance": (
        "balance", "balances", "inventory", "kaldyk", "nalichie", "onhand", "ostatka",
        "ostatki", "ostatok", "qoldiq", "qoldiqlar", "saldo", "stock", "zapas", "zapasy",
    ),
    "stock_movement": (
        "aylanma", "dvijenie", "dvijeniya", "harakat", "harakatlar", "ko'chirish", "kochirish",
        "movement", "movements", "oborot", "oboroty", "peremeshenie", "peremesheniya",
        "prihod", "rashod", "rasxod", "transfer", "transfers", "turnover",
    ),
    "goods_receipt": (
        "grn", "kabyl", "kirim", "kirimlar", "postavka", "postavki", "postuplenie",
        "postupleniya", "priemka", "prihod", "prihodnaya", "priyomka", "purchase",
        "purchases", "qabul", "receipt", "receipts", "receiving", "zakup", "zakupka",
    ),
    "supplier": (
        "beruvchi", "jetkiruuchu", "postavshik", "postavshiki", "supplier", "suppliers",
        "ta'minotchi", "taminotchi", "vendor", "vendors", "yetkazib",
    ),
    "customer": (
        "aluuchu", "buyer", "buyers", "client", "clients", "customer", "customers", "haridor",
        "klient", "klienty", "mijoz", "mijozlar", "pokupatel", "pokupateli", "satyp",
        "xaridor", "xaridorlar",
    ),
    "counterparty": (
        "counterparties", "counterparty", "hamkor", "kontragent", "kontragentlar",
        "kontragentlary", "kontragenty", "partner", "partners", "partnyor",
    ),
    "sale_document": (
        "bill", "chek", "cheki", "invoice", "prodaja", "prodaji", "realizacii", "realizaciya",
        "sale", "sales", "satuu", "savdo", "sotish", "sotuv", "sotuvlar", "ticket",
    ),
    "sales_return": (
        "kaytaruu", "qaytarilgan", "qaytarish", "qaytarma", "refund", "refunds", "return",
        "returns", "vozvrat", "vozvraty",
    ),
    "price": (
        "baa", "baho", "bahosi", "cen", "cena", "cenovaya", "cenovoy", "ceny", "narx", "narxi",
        "narxlar", "prays", "price", "prices", "pricing", "tarif", "tarify",
    ),
    "cost": (
        "cogs", "cost", "costing", "costs", "izderjki", "sebestoimost", "sebestoimosti",
        "tannarh", "tannarx", "tannarxi", "zakupochnaya", "zakupochnyy", "zatrata", "zatraty",
    ),
    "tax_vat": (
        "akciz", "excise", "gst", "nalog", "nalogi", "nalogovyy", "nds", "qqs", "salyk",
        "soliq", "soliqlar", "tax", "taxes", "vat",
    ),
    "batch_lot": (
        "batch", "batches", "lot", "lots", "partii", "partiya", "partiyalar", "serii",
        "seriya", "seriyalar", "seriynyy",
    ),
    "expiry_date": (
        "expiration", "expire", "expires", "expiry", "godnost", "godnosti", "istecheniya",
        "moonot", "muddat", "muddati", "shelf", "srok", "sroki", "yaroqlilik",
    ),
    "cash_register": (
        "cashbox", "fiscal", "fiskal", "fiskalnyy", "kassa", "kassovyy", "kassy", "kkm", "kkt",
        "pos", "terminal", "till", "tills",
    ),
    "employee_cashier": (
        "cashier", "cashiers", "employee", "employees", "hodim", "ishchi", "kassir", "kassiry",
        "kyzmatker", "operator", "operatory", "polzovatel", "polzovateli", "sotrudnik",
        "sotrudniki", "staff", "user", "users", "xodim", "xodimlar",
    ),
    "scale_plu": (
        "etiketka", "plu", "scale", "scales", "taraza", "tarozi", "tarozilar", "ves",
        "vesovoy", "vesovye", "vesy", "weigher", "weighing",
    ),
    "weighted_product": (
        "brutto", "gramm", "kg", "massa", "netto", "salmak", "vazn", "vaznli", "ves",
        "vesovaya", "vesovoy", "vesovye", "weighable", "weight", "weighted",
    ),
}


#: ⚠️ «HAMMA KONSEPT» sentineli. Ba'zi ishora MA'LUMOTNING O'ZI haqida gapiradi (arxiv,
#: nusxa, sinov, vaqtinchalik) — u qaysi konsept qidirilayotganiga bog'liq emas. Sentinel
#: `*` ataylab: konsept ID lari ASCII snake_case, ya'ni `*` ular bilan HECH QACHON
#: to'qnashmaydi (`test_konsept_idlari_ascii`).
ANY_CONCEPT = "*"


def _bundan_tashqari(*istisnolar: str) -> tuple[str, ...]:
    """Konseptlar: sanab o'tilganlardan TASHQARI hammasi (tartiblangan, takrorsiz).

    ⚠️ Istisno NOTO'G'RI yozilsa modul import qilinishida yiqiladi: jimgina o'tib ketgan
       xato istisno butun ishorani o'chirib qo'yardi va buni hech narsa aytmasdi."""
    yo_q = sorted(c for c in istisnolar if c not in CONCEPT_CLUES)
    if yo_q:
        raise LexiconError(
            f"MISLEADING_CLUES istisnosida noma'lum konsept(lar) {yo_q} — konsept ID lari "
            f"`CONCEPT_CLUES` (ya'ni `ai.CONCEPTS`) dan olinadi")
    return tuple(sorted(set(CONCEPT_CLUES) - set(istisnolar)))


#: TAKSONOMIYA ishoralari («tur», «sinf», «turkum») QAYSI konseptlar uchun aldovchi.
#: ⚠️ ISTISNOLAR ATAYLAB: uchta konseptning O'ZI «turlar ro'yxati» bo'ladi, ya'ni ularda
#:    «tur» — TO'G'RI so'z, qarshi dalil emas:
#:      · `product_variant` — xarakteristika TURLARI aynan shu konsept
#:        (`ПланВидовХарактеристик` shakli),
#:      · `price` — narx TURLARI katalogi (`schema.BUNDLE_TARGETS` dagi `price_types` AYNAN
#:        shu obyekt), ya'ni jarima haqiqiy nishonni o'chirardi,
#:      · `tax_vat` — soliq stavkasining TURLARI.
_TAKSONOMIYA = _bundan_tashqari("price", "product_variant", "tax_vat")

#: JURNAL ishoralari: «hodisalar ro'yxati, holat emas». ⚠️ Hodisa/hujjat konseptlari uchun bu
#: qarshi dalil EMAS — ular ROSTDAN hodisalar ro'yxati, ya'ni sabab ularga tegishli emas.
_HOLAT_KUTILADI = _bundan_tashqari("goods_receipt", "sale_document", "sales_return",
                                   "stock_movement")

#: REGISTR ishorasi: «platforma registri — konseptning o'zi emas». ⚠️ Registrda YASHASHI
#: kutilgan konseptlar istisno: ular uchun registr kutilgan joy, jarima esa eng to'g'ri
#: nomzodni pasaytirardi. Ro'yxat `heuristics.CONCEPT_OBJECT_KINDS` dagi registrli
#: konseptlar bilan bir xil (u yerdan IMPORT QILINMAYDI: bog'liqlik teskari yo'nalishda).
_REGISTRDA_YASHAMAYDI = _bundan_tashqari("barcode", "batch_lot", "cost", "expiry_date",
                                         "price", "scale_plu", "stock_balance",
                                         "stock_movement", "tax_vat")

#: ZAXIRA ishorasi: «zaxiraga olingan miqdor — erkin qoldiq emas» — faqat qoldiq/aylanma
#: konseptlariga tegishli.
_QOLDIQ = ("stock_balance", "stock_movement")

#: TASHKILIY BO'LINMA ishorasi: «jismoniy joy bo'lishi shart emas» — faqat omborga tegishli.
_OMBOR = ("warehouse",)


#: Chalg'ituvchi shakllar: nomi konseptga o'xshaydi, ma'nosi esa ko'pincha BOSHQA.
#: Qiymat — (nega chalg'itishi, QAYSI konseptlar uchun chalg'ituvchi).
#: ⚠️ BULAR QARSHI DALIL uchun: ular gipotezani RAD etmaydi, lekin ballni PASAYTIRADI va sabab
#:    bilan yoziladi. Eng ko'p uchraydigani — sinf/turkum ro'yxatini sotiladigan tovar deb
#:    o'qish: nomi juda o'xshaydi, mazmuni esa butunlay boshqa.
#: ⚠️ JARIMA KONSEPTGA BOG'LANGAN. Har sabab konseptga XOS: «tur/sinf — sotiladigan birlik
#:    emas» degan sabab `product` uchun to'g'ri, `product_variant` uchun esa MA'NOSIZ — u
#:    konseptning o'zi turlar ro'yxati. Sababni hamma konseptga qo'llash TO'G'RI so'zni
#:    jarimaga aylantirardi va haqiqiy nishonni ro'yxatdan chiqarardi.
MISLEADING_CLUES: dict[str, tuple[str, tuple[str, ...]]] = {
    "archive": ("tarixiy nusxa — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "arxiv": ("tarixiy nusxa — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "category": ("turkum — sotiladigan birlik emas", _TAKSONOMIYA),
    "class": ("sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "classifier": ("tashqi klassifikator — o'z ma'lumoti emas", (ANY_CONCEPT,)),
    "copy": ("nusxa — asl manba emas", (ANY_CONCEPT,)),
    "deleted": ("o'chirilgan deb belgilangan yozuvlar", (ANY_CONCEPT,)),
    "demo": ("namoyish ma'lumoti — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "folder": ("papka — element emas", (ANY_CONCEPT,)),
    "gruppa": ("guruh/papka — sotiladigan birlik emas", (ANY_CONCEPT,)),
    "gruppy": ("guruh/papka — sotiladigan birlik emas", (ANY_CONCEPT,)),
    "guruh": ("guruh/papka — sotiladigan birlik emas", (ANY_CONCEPT,)),
    "guruhlar": ("guruh/papka — sotiladigan birlik emas", (ANY_CONCEPT,)),
    "journal": ("jurnal — hodisalar ro'yxati, holat emas", _HOLAT_KUTILADI),
    "jurnal": ("jurnal — hodisalar ro'yxati, holat emas", _HOLAT_KUTILADI),
    "kategoriya": ("turkum — sotiladigan birlik emas", _TAKSONOMIYA),
    "kategoriyalar": ("turkum — sotiladigan birlik emas", _TAKSONOMIYA),
    "klass": ("sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "klassifikaciya": ("tasniflash tizimi — o'z ma'lumoti emas", (ANY_CONCEPT,)),
    "klassifikator": ("tashqi klassifikator — o'z ma'lumoti emas", (ANY_CONCEPT,)),
    "kopiya": ("nusxa — asl manba emas", (ANY_CONCEPT,)),
    "log": ("jurnal — hodisalar ro'yxati, holat emas", _HOLAT_KUTILADI),
    "nastroyka": ("sozlama — biznes ma'lumoti emas", (ANY_CONCEPT,)),
    "nastroyki": ("sozlama — biznes ma'lumoti emas", (ANY_CONCEPT,)),
    "old": ("eski versiya — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "otdel": ("tashkiliy bo'lim — jismoniy joy bo'lishi shart emas", _OMBOR),
    "papka": ("papka — element emas", (ANY_CONCEPT,)),
    "papkalar": ("papka — element emas", (ANY_CONCEPT,)),
    "podrazdelenie": ("tashkiliy bo'linma — jismoniy joy bo'lishi shart emas", _OMBOR),
    "pometka": ("belgi — mazmun emas", (ANY_CONCEPT,)),
    "proba": ("sinov ma'lumoti — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "register": ("platforma registri — konseptning o'zi emas", _REGISTRDA_YASHAMAYDI),
    "registr": ("platforma registri — konseptning o'zi emas", _REGISTRDA_YASHAMAYDI),
    "registrator": ("yozuvni yaratgan hujjatga havola — konseptning o'zi emas",
                    (ANY_CONCEPT,)),
    "reserve": ("zaxiraga olingan miqdor — erkin qoldiq emas", _QOLDIQ),
    "rezerv": ("zaxiraga olingan miqdor — erkin qoldiq emas", _QOLDIQ),
    "setting": ("sozlama — biznes ma'lumoti emas", (ANY_CONCEPT,)),
    "settings": ("sozlama — biznes ma'lumoti emas", (ANY_CONCEPT,)),
    "shablon": ("shablon — haqiqiy yozuv emas", (ANY_CONCEPT,)),
    "sozlama": ("sozlama — biznes ma'lumoti emas", (ANY_CONCEPT,)),
    "staryy": ("eski versiya — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "temp": ("vaqtinchalik ma'lumot — ishonchli manba emas", (ANY_CONCEPT,)),
    "template": ("shablon — haqiqiy yozuv emas", (ANY_CONCEPT,)),
    "test": ("sinov ma'lumoti — jonli ma'lumot emas", (ANY_CONCEPT,)),
    "tip": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "tipi": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "tipy": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "toifa": ("turkum — sotiladigan birlik emas", _TAKSONOMIYA),
    "tur": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "turi": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "turlar": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "vid": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
    "vidy": ("tur/sinf — sotiladigan birlik emas", _TAKSONOMIYA),
}


#: Platformaning TIP tavsifi uchun ishoralar: tip matni har platforma versiyasida va har
#: yozuvda boshqacha yozilishi mumkin, shu bois u ham TOKEN darajasida taqqoslanadi.
#: ⚠️ Tip matni BO'LAKLARGA AJRATILMAYDI (aniqlik va uzunlik alohida maydonlarda keladi) —
#:    bu yerda faqat tipning TURKUMI taniladi.
TYPE_CLUES: dict[str, tuple[str, ...]] = {
    "boolean": ("bool", "boolean", "bulevo", "logical", "logicheskiy", "mantiqiy"),
    "date": ("data", "date", "datetime", "kun", "sana", "vaqt"),
    "number": ("chislo", "decimal", "number", "numeric", "raqam", "son"),
    "string": ("matn", "satr", "string", "stroka", "tekst", "text"),
}


# ── Ball ───────────────────────────────────────────────────────────────────────────────────
def lexical_score(text: str, concept: str) -> tuple[float, tuple[str, ...]]:
    """Matn shu konseptga qanchalik LEKSIK o'xshashi: (0..1 ball, mos kelgan ishoralar).

    Tartib QAT'IY: to'liq token mosligi > prefiks mosligi > substring mosligi. Bir nechta
    ishora mos kelsa kichik bonus qo'shiladi, lekin bonus CHEGARALANGAN — bir nechta substring
    mosligi bitta prefiks mosligidan kuchli bo'lib ketmaydi.

    ⚠️ Qaytgan ball TASDIQ EMAS va bo'lishi ham mumkin emas: u `name_match` darajasidagi
       KUCHSIZ dalil. 1.0 ball ham `CANDIDATE` dan yuqorisiga olib chiqmaydi.
    ⚠️ Mos kelgan ishoralar TARTIBLANGAN holda qaytadi: ular dalilning `detail` iga tushadi va
       hujjat bayt-bayt bir xil bo'lishi kerak."""
    if concept not in CONCEPT_CLUES:
        raise LexiconError(
            f"noma'lum konsept {concept!r} — ishoralar lug'ati `ai.CONCEPTS` bilan bir xil "
            f"bo'lishi kerak. Konsept KOD o'zgarishi bilan qo'shiladi, chaqiruv bilan emas")

    toks = tokens(text)
    if not toks:
        return (0.0, ())

    mos: dict[str, float] = {}
    for clue in CONCEPT_CLUES[concept]:
        eng_yaxshi = 0.0
        for tok in toks:
            if tok == clue:
                eng_yaxshi = max(eng_yaxshi, SCORE_EXACT)
            elif (len(clue) >= PREFIX_MIN_LEN and len(tok) >= PREFIX_MIN_LEN
                  and (tok.startswith(clue) or clue.startswith(tok))):
                eng_yaxshi = max(eng_yaxshi, SCORE_PREFIX)
            elif len(clue) >= SUBSTRING_MIN_LEN and clue in tok:
                eng_yaxshi = max(eng_yaxshi, SCORE_SUBSTRING)
        if eng_yaxshi > 0.0:
            mos[clue] = eng_yaxshi

    if not mos:
        return (0.0, ())

    asos = max(mos.values())
    bonus = SCORE_BONUS_STEP * min(len(mos) - 1, SCORE_BONUS_MAX_HITS)
    return (round(min(1.0, asos + bonus), 3), tuple(sorted(mos)))


def misleading_hits(text: str, concept: str) -> tuple[tuple[str, str], ...]:
    """Matndagi chalg'ituvchi shakllar SHU KONSEPT uchun: ((shakl, sabab), ...) — tartiblangan.

    ⚠️ FAQAT TO'LIQ TOKEN mosligi hisobga olinadi: chalg'ituvchi shakl qarshi dalil beradi,
       ya'ni yolg'on ijobiy bu yerda BALLNI PASAYTIRADI. Substring bo'yicha qidirish qonuniy
       nomlarni ham tutib olardi (masalan qisqa bo'lak uzun boshqa so'z ichida).
    ⚠️ KONSEPT MAJBURIY ARGUMENT. Sabab konseptga XOS: «tur/sinf — sotiladigan birlik emas»
       degan qarshi dalil `product` uchun to'g'ri, `product_variant` / `price` / `tax_vat`
       uchun esa TO'G'RI SO'ZNI jarimaga aylantirardi (narx TURLARI katalogi haqiqiy nishon).
       Shu bois konseptga bog'lanmagan jarima BO'LMAYDI: argumentni tushirib qoldirib
       «hammasiga qo'llash» mumkin emas."""
    if concept not in CONCEPT_CLUES:
        raise LexiconError(
            f"noma'lum konsept {concept!r} — chalg'ituvchi shakllar KONSEPTGA bog'langan va "
            f"konsept ID lari `ai.CONCEPTS` da yashaydi")
    toks = set(tokens(text))
    natija: list[tuple[str, str]] = []
    for clue in sorted(toks & set(MISLEADING_CLUES)):
        sabab, konseptlar = MISLEADING_CLUES[clue]
        if ANY_CONCEPT in konseptlar or concept in konseptlar:
            natija.append((clue, sabab))
    return tuple(natija)


def type_matches(type_text: str, type_kind: str) -> bool:
    """Tip tavsifi ko'rsatilgan TURKUMGA to'g'ri keladimi (`TYPE_CLUES` kalitlari bo'yicha).

    ⚠️ `False` — «ishora topilmadi», «tip boshqa» EMAS: platforma tavsifni kutilmagan so'z
       bilan yozgan bo'lishi mumkin. Shu bois chaqiruvchi buni DALIL YO'QLIGI deb oladi,
       qarshi dalil deb emas."""
    if type_kind not in TYPE_CLUES:
        raise LexiconError(
            f"noma'lum tip turkumi {type_kind!r} — ruxsat etilgani {sorted(TYPE_CLUES)}")
    if not isinstance(type_text, str) or not type_text.strip():
        return False
    return bool(set(tokens(type_text)) & set(TYPE_CLUES[type_kind]))


# ── Jadvallarning o'z invarianti (import paytida) ──────────────────────────────────────────
def _check_tables() -> None:
    """Lug'atlar o'zi shartnomaga mos bo'lsin.

    ⚠️ `assert` ATAYLAB ISHLATILMAYDI: `assert` optimizatsiya rejimida o'chib qoladi, ya'ni
       lotinlashtirilmagan ishora jimgina lug'atda qolib ketardi va u HECH QACHON mos
       kelmasdi — taqqoslash boshqa bo'shliqda ketgani uchun. Bu jimgina yo'qolgan nomzod
       degani, ya'ni eng yomon xato turi."""
    kalitlar = list(CYRILLIC_TO_LATIN)
    if kalitlar != sorted(kalitlar):
        raise LexiconError("CYRILLIC_TO_LATIN kalitlari kod nuqtasi bo'yicha tartiblanmagan")
    for ch in kalitlar:
        if len(ch) != 1 or not _is_cyrillic(ch):
            raise LexiconError(f"CYRILLIC_TO_LATIN kaliti bitta kirill harfi bo'lishi kerak: {ch!r}")

    for concept, clues in CONCEPT_CLUES.items():
        if list(clues) != sorted(set(clues)):
            raise LexiconError(
                f"CONCEPT_CLUES[{concept!r}] tartiblangan va takrorsiz bo'lishi kerak")
        for clue in clues:
            if not clue.strip():
                raise LexiconError(f"CONCEPT_CLUES[{concept!r}] da bo'sh ishora bor")
            tayyor = to_latin(normalize(clue))
            if tayyor != clue:
                raise LexiconError(
                    f"CONCEPT_CLUES[{concept!r}] dagi {clue!r} lotinlashtirilmagan — "
                    f"kutilgani {tayyor!r}. Ishora `to_latin(normalize(...))` dan O'TGAN "
                    f"shaklda saqlanishi SHART, aks holda taqqoslash boshqa bo'shliqda ketadi")

    yo_l = list(MISLEADING_CLUES)
    if yo_l != sorted(yo_l):
        raise LexiconError("MISLEADING_CLUES kalitlari tartiblanmagan")
    for clue, yozuv in MISLEADING_CLUES.items():
        if to_latin(normalize(clue)) != clue:
            raise LexiconError(f"MISLEADING_CLUES dagi {clue!r} lotinlashtirilmagan")
        if not (isinstance(yozuv, tuple) and len(yozuv) == 2):
            raise LexiconError(
                f"MISLEADING_CLUES[{clue!r}] (sabab, konseptlar) juftligi bo'lishi kerak — "
                f"konseptga bog'lanmagan jarima TO'G'RI so'zni ham jarimaga aylantirardi")
        sabab, konseptlar = yozuv
        if not isinstance(sabab, str) or not sabab.strip():
            raise LexiconError(f"MISLEADING_CLUES[{clue!r}] sababsiz — qarshi dalil sababsiz "
                               f"bo'lmaydi")
        # ⚠️ Konsept ro'yxati BO'SH BO'LMASLIGI kerak: bo'sh ro'yxat ishorani jimgina
        #    o'chirib qo'yardi — u lug'atda turardi, lekin HECH QACHON ishlamasdi.
        if not (isinstance(konseptlar, tuple) and konseptlar):
            raise LexiconError(
                f"MISLEADING_CLUES[{clue!r}] konsept ro'yxati bo'sh bo'lmagan tuple bo'lishi "
                f"kerak — bo'sh ro'yxat ishorani jimgina o'chirib qo'yardi")
        if list(konseptlar) != sorted(set(konseptlar)):
            raise LexiconError(
                f"MISLEADING_CLUES[{clue!r}] konseptlari tartiblangan va takrorsiz bo'lishi "
                f"kerak — determinizm uchun")
        if ANY_CONCEPT in konseptlar:
            # ⚠️ Sentinel ARALASHMAYDI: «hammasi + ba'zisi» degan yozuv ikki ma'noli bo'lardi.
            if konseptlar != (ANY_CONCEPT,):
                raise LexiconError(
                    f"MISLEADING_CLUES[{clue!r}]: {ANY_CONCEPT!r} sentineli boshqa konsept "
                    f"bilan ARALASHMAYDI — yozuv ikki ma'noli bo'lib qolardi")
            continue
        yo_q = sorted(c for c in konseptlar if c not in CONCEPT_CLUES)
        if yo_q:
            raise LexiconError(
                f"MISLEADING_CLUES[{clue!r}] da noma'lum konsept(lar) {yo_q} — konsept ID lari "
                f"`ai.CONCEPTS` da yashaydi va o'ylab chiqarilmaydi")

    for turkum, clues in TYPE_CLUES.items():
        if list(clues) != sorted(set(clues)):
            raise LexiconError(f"TYPE_CLUES[{turkum!r}] tartiblangan va takrorsiz bo'lishi kerak")
        for clue in clues:
            if to_latin(normalize(clue)) != clue:
                raise LexiconError(f"TYPE_CLUES[{turkum!r}] dagi {clue!r} lotinlashtirilmagan")

    if not (SCORE_EXACT > SCORE_PREFIX > SCORE_SUBSTRING > 0.0):
        raise LexiconError("ball tartibi buzilgan: to'liq > prefiks > substring bo'lishi SHART")
    if SCORE_SUBSTRING + SCORE_BONUS_STEP * SCORE_BONUS_MAX_HITS >= SCORE_PREFIX:
        raise LexiconError(
            "bonus juda katta: bir nechta substring mosligi bitta prefiks mosligidan kuchli "
            "bo'lib ketadi va ball tartibi ma'nosini yo'qotadi")
    if SCORE_PREFIX + SCORE_BONUS_STEP * SCORE_BONUS_MAX_HITS >= SCORE_EXACT:
        raise LexiconError(
            "bonus juda katta: bir nechta prefiks mosligi to'liq moslikdan kuchli bo'lib ketadi")


_check_tables()
