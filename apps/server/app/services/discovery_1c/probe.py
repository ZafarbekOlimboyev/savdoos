# -*- coding: utf-8 -*-
"""TASDIQLANGAN FAQAT-O'QISH ZONDLAR KATALOGI — `binos-1c-probe-v1`.

⚠️ AI (yoki boshqa avtomat) 1C ga O'Z SO'ROVINI YUBORA OLMAYDI. U faqat SHU katalogdagi
   zond TURINI so'ray oladi; ekstraktor esa aynan shu turlarni biladi va boshqasini
   bajarmaydi. Ya'ni bajariladigan amallar ro'yxati QO'LDA yozilgan va o'zgarmas, model esa
   shu ro'yxatdan TANLAYDI.

NEGA AYNAN SHUNDAY. «Modelga so'rov yozdirish» eng qisqa yo'l ko'rinadi, lekin u ikki narsani
buzadi: (1) auditni — bajarilgan amalni oldindan bilib bo'lmaydi, ya'ni «faqat o'qiydi»
kafolati yo'qoladi; (2) mijoz bazasini — noto'g'ri so'rov jonli bazani bloklashi yoki
metadatani o'zgartirishi mumkin. Katalog esa har bir amalni OLDINDAN ko'rinadigan qiladi:
zond turi -> nima qaytaradi -> nega kerak.

⚠️ KATALOGDA KONFIGURATSIYA NOMI YO'Q. Zond turlari 1C PLATFORMASINING umumiy tushunchalari
   (obyekt maydonlari, jadval bo'limlari, havolalar, registr shakli). Qaysi obyektni so'rash —
   `target_object`, ya'ni MA'LUMOT: u grafdan keladi, katalogdan emas.

⚠️ NISHON SHAKLI ZOND TURIDAN KELIB CHIQADI (`FIELD_TARGET_PROBE_TYPES`): maydon tafsilotini
   so'raydigan zond MAYDON MANZILINI oladi (`<obyekt>.<maydon>`), qolganlari OBYEKTNI. Shartnoma
   BITTA joyda yozilgan, chunki uni ikki tomon (validator va bajaruvchi) bajaradi va ular
   bir-birining talabini TAXMIN QILMASLIGI kerak.

⚠️ HAMMA ZOND FAQAT O'QIYDI. Katalogda `read_only: False` bo'lgan yozuv YO'Q va bo'lishi ham
   mumkin emas: yozuvchi zond bu qatlamning butun ma'nosini yo'qotadi. Shu invariant import
   paytida tekshiriladi, ya'ni ro'yxatga yozuvchi zond qo'shilsa modul import qilinishida
   yiqiladi, testda emas.

DETERMINIZM: zond rejasi tartiblanadi va takrori birlashtiriladi, bir xil kirish — AYNAN bir
xil reja. Modelning navbati ma'no tashimaydi: u bir xil savolni ikki xil tartibda berishi
mumkin, bajariladigan ish esa bir xil bo'lishi kerak.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .bundle import DiscoveryError
from .schema import WEAK_EVIDENCE_KINDS

if TYPE_CHECKING:  # faqat annotatsiya uchun — ishlash vaqtida import qilinmaydi
    from .graph import DiscoveryGraph

PROBE_VERSION = "binos-1c-probe-v1"

#: Bitta rejadagi zondlarning yuqori chegarasi.
#: ⚠️ Chegara ataylab bor: chegarasiz reja operatorning vaqtini cheksiz sarflaydi va modelni
#: tanlashga majburlamaydi. «Hammasini so'ray» — tahlil emas, ro'yxat ko'chirish.
MAX_PROBES_DEFAULT = 32

PROBE_KEYS = {"probe_type", "target_object", "reason", "expected_evidence"}
CATALOG_KEYS = {"why", "returns", "read_only"}

#: Nishoni OBYEKT emas, MAYDON MANZILI bo'lgan zond turlari.
#: ⚠️ NISHON SHARTNOMASI (ikki tomon uchun BITTA):
#:     · `field_type_details`  -> `<obyekt>.<maydon>` yoki `<obyekt>.<bo'lim>.<maydon>`
#:     · qolgan HAMMA zond turi -> `<obyekt>`
#: ⚠️ NEGA SHART: ilgari ikki tomon ZID talab qilardi. BinOS tomoni nishonni HAR DOIM obyekt
#:    deb tekshirardi (graf faqat obyektlar bilan kalitlangan), bajaruvchi tomon esa bu zond
#:    uchun MAYDON YO'LINI talab qiladi va yo'l bo'sh bo'lsa xato qaytaradi. Natijada zond
#:    HECH QACHON natija bermasdi: maydonli nishon validatorda RAD etilardi, obyektli nishon
#:    esa bajaruvchida xatoga uchrardi — ya'ni katalogda TIRIK ko'rinadigan, amalda O'LIK zond.
#:    Shartnoma bitta joyda yozilgani uchun ikki tomon endi bir narsani tushunadi.
FIELD_TARGET_PROBE_TYPES = ("field_type_details",)

#: Nishon manzilidagi ota-bola ajratuvchisi (`graph.PATH_SEP` bilan AYNAN bir xil belgi).
#: ⚠️ `graph` bu yerga IMPORT QILINMAYDI (bog'liqlik bir tomonlama: `graph` -> `probe` emas,
#:    `ai` ikkisini ham biladi), shu bois belgi shu yerda takrorlanadi va uni testlar solishtiradi.
TARGET_SEP = "."

#: Takroriy zondlar birlashganda sabablar shu ajratuvchi bilan qo'shiladi.
#: ⚠️ Ajratuvchi `assert_no_raw_code` dan O'TISHI SHART (nuqtali vergul EMAS), aks holda
#: birlashtirilgan reja o'zining validatoridan o'tmay qolardi.
REASON_SEP = " | "

#: ── Katalog ────────────────────────────────────────────────────────────────────────────────
#: Har bir yozuv: nega kerak (`why`), nima qaytaradi (`returns`), faqat o'qiydimi (`read_only`).
#: ⚠️ `returns` da BIZNES QATORI yo'q — zondlar metadata va SANOQ qaytaradi. Yagona istisno
#: `row_count`, u ham faqat sanoqni (MATN) qaytaradi, qatorlarning o'zini emas.
PROBE_CATALOG: dict[str, dict] = {
    "object_attributes": {
        "why": "obyektning maydon tarkibi bilinmasa birorta gipoteza tekshirilmaydi",
        "returns": "maydon nomlari, sinonimlari, xom tip tavsifi va havola nishonlari",
        "read_only": True,
    },
    "tabular_sections": {
        "why": "hujjat va katalogning qator darajasidagi tuzilmasi jadval bo'limlarida turadi",
        "returns": "bo'lim nomlari va har bo'limning maydon tarkibi",
        "read_only": True,
    },
    "referencing_objects": {
        "why": "kim shu obyektga havola qilishi uning haqiqiy rolini nomdan ko'ra aniq ko'rsatadi",
        "returns": "shu obyektga havola qiladigan obyekt va maydon manzillari",
        "read_only": True,
    },
    "referenced_objects": {
        "why": "obyekt kimga havola qilishi uning qaysi zanjirda turganini ko'rsatadi",
        "returns": "shu obyekt havola qiladigan obyektlar va havola qilgan maydon manzillari",
        "read_only": True,
    },
    "register_shape": {
        "why": "registrning o'lchov va resurs taqsimoti uning qoldiq yoki aylanma ekanini ochadi",
        "returns": "o'lchov, resurs va rekvizit tarkibi, registr turi, davriylik",
        "read_only": True,
    },
    "enum_values": {
        "why": "holat va turlar sanab o'tilgan qiymatlar ichida yashiringan bo'lishi mumkin",
        "returns": "sanab o'tilgan qiymatlarning NOMLARI (indeks va tartib raqami yo'q)",
        "read_only": True,
    },
    "predefined_names": {
        "why": "oldindan belgilangan elementlar konfiguratsiya kutgan ma'noni ochib beradi",
        "returns": "oldindan belgilangan element nomlari",
        "read_only": True,
    },
    "row_count": {
        "why": "sanoq gipotezaning kattaligi mantiqiyligini tekshiradi — kichik ro'yxat katta "
               "ro'yxatning o'rnini bosa olmaydi",
        "returns": "qatorlar SONI, MATN sifatida; qatorlarning O'ZI qaytmaydi",
        "read_only": True,
    },
    "field_type_details": {
        "why": "tip shakli (raqamli aniqlik, kasr xona, uzunlik) nomdan mustaqil dalil beradi",
        # ⚠️ Nishon shakli KATALOGDA aytiladi, chunki katalog modelga YUBORILADI: shartnomani
        #    faqat validator bilishi «aytilmagan qoida bo'yicha rad etish» bo'lardi.
        "returns": "bitta maydonning tip tavsifi tafsilotlari, hammasi MATN. Nishon — MAYDON "
                   "MANZILI (`<obyekt>.<maydon>` yoki `<obyekt>.<bo'lim>.<maydon>`), obyekt emas",
        "read_only": True,
    },
    "common_attributes": {
        "why": "umumiy rekvizit obyektning o'z ro'yxatida ko'rinmaydi, lekin uning maydoni "
               "bo'lib ishlaydi",
        "returns": "umumiy rekvizit nomlari va ular ulangan obyektlar ro'yxati",
        "read_only": True,
    },
    "characteristic_plans": {
        "why": "kengaytirilgan konfiguratsiyada qo'shimcha maydonlar xarakteristika turlari "
               "rejasi orqali qo'shiladi va oddiy rekvizit ro'yxatida ko'rinmaydi",
        "returns": "xarakteristika turlari rejasining tarkibi va u qaysi obyektlarga tegishli",
        "read_only": True,
    },
}


class ProbeError(DiscoveryError):
    """Zond so'rovi katalogga, grafga yoki faqat-o'qish qoidasiga mos emas — BAJARILMAYDI.

    `DiscoveryError` dan meros: discovery hujjatlarini o'qiydigan mavjud kod bitta `except`
    bilan bularni ham qamrab oladi."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ProbeError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra, f"{where}: noma'lum kalit(lar) {extra} — {PROBE_VERSION} da yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {missing}")


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


# ── Katalogning o'z invarianti (import paytida) ────────────────────────────────────────────
def _check_catalog() -> None:
    """Katalog o'zi shartnomaga mos bo'lsin: kalitlar to'liq, hamma zond FAQAT O'QIYDI.

    ⚠️ `assert` ATAYLAB ISHLATILMAYDI: `assert` optimizatsiya rejimida o'chib qoladi, ya'ni
    yozuvchi zond jimgina katalogda qolib ketardi."""
    for probe_type, spec in PROBE_CATALOG.items():
        _nonempty(probe_type, "PROBE_CATALOG kaliti")
        _keys(spec, CATALOG_KEYS, f"PROBE_CATALOG[{probe_type!r}]")
        _nonempty(spec["why"], f"PROBE_CATALOG[{probe_type!r}].why")
        _nonempty(spec["returns"], f"PROBE_CATALOG[{probe_type!r}].returns")
        _need(spec["read_only"] is True,
              f"PROBE_CATALOG[{probe_type!r}].read_only AYNAN True bo'lishi kerak — "
              f"yozuvchi zond bu qatlamning ma'nosini yo'qotadi")


_check_catalog()


# ── Xom kod darvozasi ──────────────────────────────────────────────────────────────────────
#: PROZA ro'yxati: har qanday matn maydonida (`reason`, dalil matni, izoh) kod TOKENI
#: bo'lmasligi kerak. Nishon MANZILI uchun bunga `_ADDRESS_CODE_PATTERNS` QO'SHILADI.
#: ⚠️ NEGA KERAK: agar model tushuntirish maydoniga so'rov matnini yozib yuborsa va biror kun
#: ekstraktor shu matnni «izoh» deb olib jurnaliga yoki so'rov tanasiga qo'shsa — katalog
#: darvozasi aylanib o'tilgan bo'ladi. Shu bois kod belgilari MATNGA ham kiritilmaydi: kod
#: bo'lmaydigan joyda kodga o'xshash narsa turishi kerak emas.
#: ⚠️ Ataylab EHTIYOTKOR. Yolg'on ijobiy — sababni boshqa so'z bilan yozish; yolg'on salbiy —
#: auditdan tashqarida bajarilgan amal.
_RAW_CODE_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    ("statement_separator", re.compile(r";"),
     "nuqtali vergul — operator ajratuvchisi, tushuntirishda kerak emas"),
    ("query_keyword", re.compile(r"(?i)\b(select|insert|update|upsert|delete|drop|truncate|"
                                 r"alter|grant|union|exec|execute)\b"),
     "so'rov yoki o'zgartirish kaliti"),
    ("query_keyword_platform",
     re.compile(r"ВЫБРАТЬ|ВЫРАЗИТЬ|Запрос|Выполнить|Вычислить|Записать|Провести|Удалить"),
     "platforma so'rovi yoki amal chaqiruvi"),
    ("new_object", re.compile(r"Новый\s"),
     "obyekt yaratish — zond so'rovi faqat TANLAYDI, kod tuzmaydi"),
    ("block_braces", re.compile(r"[{}]"),
     "figurali qavs — kod yoki shablon belgisi"),
)

#: Nishon MANZILI uchun QO'SHIMCHA (qat'iyroq) naqshlar — `address=True` bo'lganda qo'llanadi.
#: ⚠️ NEGA ALOHIDA RO'YXAT VA NEGA HAMMA JOYGA EMAS. `assert_no_raw_code` ikki XIL TURDAGI
#:    matnga qo'llanadi:
#:      · PROZA — modelning tushuntirishlari (`reason`, `evidence.detail`, `ambiguity`,
#:        `required_confirmation`, `notes`, tasdiqning `operator`/`note`/`decided_at`). Bu
#:        matnlar vergul, qavs, kvadrat qavs, qo'shtirnoq va plyusni QONUNIY ishlatadi:
#:        leksik ball hissasi `(hissa +0.30)` bo'lib yoziladi, ishoralar ro'yxati
#:        `['birlik', 'birliklar']` bo'lib ko'rsatiladi, `decided_at` esa `+05:00` vaqt
#:        mintaqasini olib yuradi. Bu belgilarni prozada to'sish tahlil qatlamini o'ldirardi —
#:        ya'ni bu YOLG'ON IJOBIY bo'lardi, xavfsizlik emas.
#:      · MANZIL — `target_object`, ya'ni AYNAN operator shablonidagi joyga qo'yiladigan
#:        qiymat. Uning qonuniy shakli `<obyekt>[.<bo'lim>].<maydon>`, ya'ni 1C identifikator
#:        belgilari + ajratuvchi nuqta. Bu yerda tinish belgisining birortasi ham QONUNIY
#:        EMAS, shu bois darvoza to'la kuchda ishlaydi.
#: ⚠️ Darvoza prozada yumshoq, BAJARISH maydonida qat'iy — bu asimmetriya ATAYLAB va
#:    yo'nalishi to'g'ri: ilgari asimmetriya TESKARI edi (tushuntirish qo'riqlanar, bajarish
#:    maydoni esa qo'shtirnoq va qavsni o'tkazib yuborardi).
#: ⚠️ NUQTA BU RO'YXATDA YO'Q va bo'lishi ham mumkin emas: nuqta — nishonning O'Z ajratuvchisi
#:    (`TARGET_SEP`). Uni to'sish `field_type_details` zondini butunlay o'lik qilardi.
_ADDRESS_CODE_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    ("string_literal_quote", re.compile(r"[\"'`]"),
     "qo'shtirnoq yoki apostrof — 1C/SQL satr literalini YOPADI"),
    ("call_parens", re.compile(r"[()]"),
     "qavs — amal chaqiruvini ochadi yoki yopadi"),
    ("argument_separator", re.compile(r","),
     "vergul — argument ajratuvchisi, nishonda kerak emas"),
    ("concatenation", re.compile(r"\+"),
     "plyus — satr birlashtirish (nishonni qismlardan yig'ish yo'li)"),
    ("index_brackets", re.compile(r"[\[\]]"),
     "kvadrat qavs — indeks yoki shablon o'rni"),
    ("whitespace", re.compile(r"\s"),
     "bo'sh joy — nishon BITTA manzil, ikki so'z emas"),
)


def assert_no_raw_code(text: str, *, where: str = "matn", address: bool = False) -> None:
    """Matnda kod belgisi bo'lsa RAD etadi. Muvaffaqiyatda hech narsa qaytmaydi.

    `address=False` (standart) — PROZA rejimi: kod TOKENLARI to'siladi (`;`, figurali qavs,
    so'rov va platforma kalit so'zlari, `Новый `), tinish belgilari esa o'tadi.
    `address=True` — MANZIL rejimi: yuqoridagilarga `_ADDRESS_CODE_PATTERNS` qo'shiladi
    (qo'shtirnoq/apostrof, qavs, vergul, plyus, kvadrat qavs, bo'sh joy). Nuqta AYRIM HOLDA
    QOLDIRILADI — u nishonning o'z ajratuvchisi.

    ⚠️ NEGA IKKI REJIM: `_ADDRESS_CODE_PATTERNS` izohiga qarang — prozada bu belgilar QONUNIY
       va ularni to'sish yolg'on ijobiy bo'lardi, manzilda esa QONUNIY EMAS.
    ⚠️ Standart qiymat ATAYLAB `False`: manzil rejimini CHAQIRUVCHI ataylab so'raydi, ya'ni
       prozani tekshiradigan mavjud chaqiruvlar jimgina qat'iylashib qolmaydi.
    ⚠️ Bu funksiya kodni «tozalamaydi» va tozalangan matnni qaytarmaydi. Tozalash jimgina
    davom etish bo'lardi (fail-open): chaqiruvchi matnda kod bor edimi-yo'qmi bilmay qolardi."""
    _need(isinstance(text, str), f"{where} matn bo'lishi kerak")
    naqshlar = _RAW_CODE_PATTERNS + (_ADDRESS_CODE_PATTERNS if address else ())
    for name, rx, detail in naqshlar:
        m = rx.search(text)
        if m is not None:
            # ⚠️ Xato matnida topilgan bo'lak QISQARTIRILADI: uzun kodni xato matniga to'liq
            #    ko'chirish uni jurnal orqali tarqatish bo'lardi.
            raise ProbeError(
                f"{where}: xom kod belgisi topildi ({name}: {detail}) — {m.group(0)[:24]!r}. "
                f"Zond so'rovida kod BO'LMAYDI: bajariladigan amalni katalog belgilaydi "
                f"(ruxsat etilgan turlar: {', '.join(sorted(PROBE_CATALOG))})")


# ── Zond so'rovi ───────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ProbeRequest:
    """Bitta zond so'rovi: KATALOGDAN tanlangan tur + grafdan olingan nishon.

    `probe_type`        — `PROBE_CATALOG` kalitlaridan biri, boshqasi RAD.
    `target_object`     — grafda MAVJUD nishon (o'ylab chiqarilgani RAD). Nishon SHAKLI zond
                          TURIDAN kelib chiqadi (`FIELD_TARGET_PROBE_TYPES`):
                          `field_type_details` uchun MAYDON MANZILI (`<obyekt>.<maydon>` yoki
                          `<obyekt>.<bo'lim>.<maydon>`), qolganlari uchun OBYEKT (`<obyekt>`).
                          ⚠️ Maydon nomi `target_object` ichida turadi, chunki so'rovda
                          alohida maydon maydoni YO'Q: qo'shilsa, u boshqa zond turlarida
                          ma'nosiz bo'lib yotardi va «to'ldirilmagan maydon» jimgina
                          «hamma maydon» degan ma'noga o'tib ketardi.
    `reason`            — nega shu zond so'ralayotgani; bo'sh bo'lsa RAD.
    `expected_evidence` — zond qanday DALIL berishi kutilayotgani.

    ⚠️ `expected_evidence` faqat KUCHSIZ dalil turlaridan bo'ladi (`schema.py`): zond metadata
       o'qiydi, ya'ni nom/tip/shakl darajasidagi dalil beradi. Kuchli dalil (odam tasdig'i,
       arifmetik isbot, yo'qlik isboti) zonddan CHIQMAYDI — u alohida qadamdan keladi. Zondga
       kuchli dalil kutilishini yozish «avtomat o'zini tasdiqladi» degan yolg'on xotirjamlik.
    ⚠️ `expected_evidence` — KUTILGAN dalil, OLINGAN dalil emas. Zond bajarilgach natija dalil
       bo'lib qaytadi yoki qaytmaydi; kutishning o'zi hech narsani isbotlamaydi."""

    probe_type: str
    target_object: str
    reason: str
    expected_evidence: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        """Birlashtirish va tartiblash kaliti: bir obyektga bir turdagi zond BIR MARTA."""
        return (self.probe_type, self.target_object)


def object_prefix(target: str, *, graph: DiscoveryGraph) -> str | None:
    """Nishondagi ENG UZUN obyekt prefiksi, yoki `None`.

    ⚠️ Ajratish NOMDAN TAXMIN QILINMAYDI. Nuqta IKKI ma'noda uchraydi: obyektning to'liq
       nomida (`<Prefiks>.<Nom>`) va manzilda (`<obyekt>.<bo'lim>.<maydon>`). Shu bois
       «oxirgi nuqta bo'yicha ajratish» jadval bo'limi maydonini obyekt nomiga qo'shib
       yuborardi yoki obyekt nomini ikkiga bo'lib tashlardi. Yagona ishonchli yo'l — GRAFDAN
       so'rash: eng uzun prefiks obyekt bo'lsa, qolgani maydon yo'li bo'lishi mumkin."""
    bo_laklar = target.split(TARGET_SEP)
    for k in range(len(bo_laklar) - 1, 0, -1):
        nomzod = TARGET_SEP.join(bo_laklar[:k])
        if graph.by_full_name(nomzod) is not None:
            return nomzod
    return None


def split_field_target(target: str, *, graph: DiscoveryGraph) -> tuple[str, str] | None:
    """`<obyekt>.<maydon yo'li>` -> `(obyekt, yo'l)`; maydon GRAFDA bo'lmasa `None`.

    ⚠️ `None` ikki xil holatni birlashtiradi: obyekt topilmadi va maydon topilmadi. Chaqiruvchi
       xato MATNINI aniq yozishi uchun `object_prefix` ni alohida so'raydi — «nima topilmadi»
       aytilmagan rad etish operatorni kodni qaytadan o'qishga majbur qiladi."""
    egasi = object_prefix(target, graph=graph)
    if egasi is None:
        return None
    yo_l = target[len(egasi) + len(TARGET_SEP):]
    if yo_l and yo_l in {f.path for f in graph.fields_of(egasi)}:
        return (egasi, yo_l)
    return None


def validate_probe(req: ProbeRequest, *, graph: DiscoveryGraph) -> None:
    """Bitta zond so'rovini tekshiradi. Xato — `ProbeError`.

    ⚠️ `target_object` grafda bo'lishi SHART. Model obyekt nomini O'YLAB CHIQARA OLMAYDI:
       mavjud bo'lmagan nishonga yuborilgan zond eng yaxshi holatda xato, eng yomonida —
       boshqa obyektga tushib ketgan so'rov.
    ⚠️ NISHON TURI ZOND TURIDAN kelib chiqadi (`FIELD_TARGET_PROBE_TYPES`): `field_type_details`
       MAYDON manzilini talab qiladi, qolganlari OBYEKTNI. Aralashtirib yuborilgan nishon
       «bajarilmaydigan zond» degani, shu bois u SHU YERDA to'xtaydi."""
    _need(isinstance(req, ProbeRequest),
          f"zond so'rovi `ProbeRequest` bo'lishi kerak, kelgani {type(req).__name__}")
    _need(req.probe_type in PROBE_CATALOG,
          f"noma'lum zond turi {req.probe_type!r} — katalogda yo'q. Ruxsat etilgani: "
          f"{', '.join(sorted(PROBE_CATALOG))}")
    _nonempty(req.target_object, "zond.target_object")
    # ⚠️ NISHON HAM XOM KOD DARVOZASIDAN O'TADI. Ilgari darvoza faqat `reason` ga qo'llanardi,
    #    holbuki AYNAN `target_object` operatorning qo'lidagi shablonga QO'YILADIGAN qiymat
    #    (u ko'rik artefaktiga `target_object` bo'lib chiqadi va operator uni 1C tomonidagi
    #    so'rov satriga ko'chiradi). Ichida qo'shtirnoq, `;` yoki amal chaqiruvi bo'lgan nom
    #    shu shablonni YOPIB, ortidan boshqa amal qo'shish imkonini berardi — ya'ni butun
    #    katalog darvozasi aylanib o'tilardi. Tushuntirish maydoni qo'riqlanib, BAJARISH
    #    maydoni qo'riqlanmasligi — darvozaning eng qimmat turdagi asimmetriyasi.
    # ⚠️ `address=True` — MANZIL rejimi. Darvoza `;` va figurali qavsni tutgani bilan
    #    QO'SHTIRNOQNI o'tkazib yuborardi, holbuki AYNAN qo'shtirnoq BSL satr literalini
    #    yopadigan belgi: `Справочник.Tovar"); Объект.Записать(); Zond("row_count", "X` dagi
    #    birinchi belgi ham qo'shtirnoq. Nishonning qonuniy shakli
    #    `<obyekt>[.<bo'lim>].<maydon>` — identifikator belgilari + nuqta, boshqa hech narsa,
    #    shu bois bu yerda qat'iy rejim YOLG'ON IJOBIY bermaydi (proza rejimi o'zgarmadi:
    #    `_ADDRESS_CODE_PATTERNS` izohiga qarang).
    assert_no_raw_code(req.target_object, where="zond.target_object", address=True)

    if req.probe_type in FIELD_TARGET_PROBE_TYPES:
        egasi = object_prefix(req.target_object, graph=graph)
        _need(egasi is not None,
              f"zond.target_object grafda yo'q: {req.target_object!r} — {req.probe_type!r} "
              f"nishoni MAYDON MANZILI (`<obyekt>.<maydon>` yoki "
              f"`<obyekt>.<bo'lim>.<maydon>`), va uning obyekti inventarizatsiya hujjatidan "
              f"kelishi kerak")
        _need(split_field_target(req.target_object, graph=graph) is not None,
              f"zond.target_object {egasi!r} obyektida bunday maydon YO'Q: "
              f"{req.target_object!r} — {req.probe_type!r} bitta MAYDONNING tip tafsilotini "
              f"o'qiydi, ya'ni maydon yo'li grafda bo'lishi SHART (maydon nomi ham O'YLAB "
              f"CHIQARILMAYDI; obyektdagi maydonlar soni: {len(graph.fields_of(egasi))})")
    elif graph.by_full_name(req.target_object) is None:
        # ⚠️ Maydon manzili boshqa zond turlariga BERILMAYDI va u alohida xato matni oladi:
        #    «grafda yo'q» deb rad etish bu holatda YOLG'ON sabab bo'lardi — manzil rostdan
        #    bor, faqat u OBYEKT emas, va shu farqni ko'rsatmaslik chaqiruvchini nomni
        #    «tuzatish» ga undardi.
        maydon = split_field_target(req.target_object, graph=graph)
        _need(maydon is None,
              f"zond.target_object MAYDON manzili: {req.target_object!r} — {req.probe_type!r} "
              f"OBYEKT bilan ishlaydi. Maydon manzili faqat shu zond tur(lar)i uchun: "
              f"{', '.join(FIELD_TARGET_PROBE_TYPES)}")
        _need(False,
              f"zond.target_object grafda yo'q: {req.target_object!r} — obyekt nomi O'YLAB "
              f"CHIQARILMAYDI, u inventarizatsiya hujjatidan kelishi kerak")

    _nonempty(req.reason, "zond.reason")
    assert_no_raw_code(req.reason, where="zond.reason")

    kutilgan = req.expected_evidence
    _need(isinstance(kutilgan, tuple) and kutilgan,
          "zond.expected_evidence bo'sh bo'lmagan tuple bo'lishi kerak — nima kutilayotgani "
          "aytilmagan zondning natijasini baholab bo'lmaydi")
    for kind in kutilgan:
        _nonempty(kind, "zond.expected_evidence elementi")
        _need(kind in WEAK_EVIDENCE_KINDS,
              f"zond.expected_evidence {kind!r} — zonddan faqat KUCHSIZ dalil chiqadi "
              f"({', '.join(WEAK_EVIDENCE_KINDS)}); kuchli dalil alohida qadamdan keladi")
    dupes = sorted({k for k in kutilgan if kutilgan.count(k) > 1})
    _need(not dupes, f"zond.expected_evidence: dalil turi takrorlangan {dupes}")


def validate_probe_plan(reqs, *, graph: DiscoveryGraph,
                        max_probes: int = MAX_PROBES_DEFAULT) -> tuple[ProbeRequest, ...]:
    """Rejani tekshiradi, TAKRORIY zondni birlashtiradi va DETERMINISTIK tartiblaydi.

    ⚠️ Takror JIMGINA TASHLANMAYDI, BIRLASHTIRILADI: ikki gipoteza bir obyektni bir xil usulda
       so'ragan bo'lsa, ikkalasining SABABI ham saqlanadi. Birini tashlab yuborish — zond nima
       uchun kerak bo'lganini yo'qotish.
    ⚠️ Chegara birlashtirishdan KEYIN tekshiriladi: takrorlar rejani soxta to'ldirmasin.
    ⚠️ Natija QAYTA tekshiriladi — birlashtirishning o'zi shartnomani buzmaganiga ishonch
       (masalan qo'shilgan sabablar xom kod darvozasidan o'tishi kerak)."""
    _need(isinstance(reqs, (list, tuple)), "zond rejasi ro'yxat yoki tuple bo'lishi kerak")
    _need(isinstance(max_probes, int) and not isinstance(max_probes, bool) and max_probes > 0,
          f"max_probes musbat butun son bo'lishi kerak, kelgani {max_probes!r}")

    for req in reqs:
        validate_probe(req, graph=graph)

    # Kalit bo'yicha birlashtirish. Sabablar tartiblangan va takrorsiz qo'shiladi, shu bois
    # kirish tartibi natijaga TA'SIR QILMAYDI.
    birlashgan: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for req in reqs:
        sabablar, dalillar = birlashgan.setdefault(req.key, (set(), set()))
        sabablar.add(req.reason.strip())
        dalillar.update(req.expected_evidence)

    reja = tuple(
        ProbeRequest(
            probe_type=key[0],
            target_object=key[1],
            reason=REASON_SEP.join(sorted(birlashgan[key][0])),
            expected_evidence=tuple(sorted(birlashgan[key][1])),
        )
        for key in sorted(birlashgan)
    )

    _need(len(reja) <= max_probes,
          f"zond rejasi juda katta: {len(reja)} ta zond, chegara {max_probes}. "
          f"Model tanlashi kerak — «hammasini so'ray» tahlil emas")

    for req in reja:
        validate_probe(req, graph=graph)
    return reja


def probe_from_json(raw, *, where: str = "probe") -> ProbeRequest:
    """Lug'atdan `ProbeRequest` yasaydi. Kalitlar OQ RO'YXAT bilan: noma'lum ham, tushib
    qolgan ham — RAD.

    ⚠️ Bu yerda graf YO'Q, ya'ni nishon mavjudligi TEKSHIRILMAYDI. To'liq tekshiruv —
       `validate_probe` (yoki `validate_probe_plan`) ning ishi va u MAJBURIY."""
    _keys(raw, PROBE_KEYS, where)
    _nonempty(raw["probe_type"], f"{where}.probe_type")
    _nonempty(raw["target_object"], f"{where}.target_object")
    _nonempty(raw["reason"], f"{where}.reason")
    kutilgan = raw["expected_evidence"]
    _need(isinstance(kutilgan, (list, tuple)),
          f"{where}.expected_evidence ro'yxat bo'lishi kerak")
    for i, kind in enumerate(kutilgan):
        _nonempty(kind, f"{where}.expected_evidence[{i}]")
    return ProbeRequest(
        probe_type=raw["probe_type"],
        target_object=raw["target_object"],
        reason=raw["reason"],
        expected_evidence=tuple(kutilgan),
    )


def probe_to_json(req: ProbeRequest) -> dict:
    """Zondni lug'atga aylantiradi — determinstik (dalil turlari tartiblangan).

    ⚠️ `read_only` bu yerda YOZILMAYDI: u so'rovning maydoni emas, KATALOGNING xossasi.
       So'rov ichida takrorlansa, kimdir uni `False` qilib yuborishi mumkin bo'lardi."""
    _need(isinstance(req, ProbeRequest),
          f"probe_to_json `ProbeRequest` kutadi, kelgani {type(req).__name__}")
    return {
        "probe_type": req.probe_type,
        "target_object": req.target_object,
        "reason": req.reason,
        "expected_evidence": sorted(req.expected_evidence),
    }


def catalog_to_json() -> dict:
    """Katalogning determinstik lug'ati — modelga yuboriladigan yukka shu qo'shiladi.

    ⚠️ Modelga katalog YUBORILADI, lekin katalogni modelga TO'LDIRTIRIB bo'lmaydi: yukdagi
       ro'yxat faqat «shulardan tanla» degani. Yangi zond turi kod o'zgarishi bilan qo'shiladi
       va uni odam ko'rikdan o'tkazadi."""
    return {
        probe_type: {
            "why": PROBE_CATALOG[probe_type]["why"],
            "returns": PROBE_CATALOG[probe_type]["returns"],
            "read_only": True,
        }
        for probe_type in sorted(PROBE_CATALOG)
    }
