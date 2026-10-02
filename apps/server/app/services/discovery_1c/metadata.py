# -*- coding: utf-8 -*-
"""`binos-1c-metadata-v1` — UNIVERSAL metadata inventarizatsiyasi (IKKINCHI hujjat).

NEGA YANGI HUJJAT, NEGA ESKI SHAKL KENGAYTIRILMADI. Phase 2 ning `binos-1c-export-v1` shakli
allaqachon yozilgan, sinalgan va uning ustida to'plam ko'prigi (`export_adapter.py`) turadi.
Unga maydon qo'shish — o'sha shartnomani va uni tekshiradigan hamma narsani qo'zg'atish
bo'lardi. Shu bois inventarizatsiya ALOHIDA fayl bo'lib chiqadi (`metadata.json`):

  · `binos-1c-export-v1`   — NISHONLAR bo'yicha nomzodlar (Phase 2). BAYTIGA TEGILMAYDI.
  · `binos-1c-metadata-v1` — konfiguratsiyada UMUMAN NIMA BOR (Phase 3). Bu fayl.

⚠️ BU HUJJATDA TALQIN YO'Q. U «nima bor» ni yozadi, «nima ma'nosi» ni EMAS: nishon, ishonch
darajasi, xarita — hech biri bu yerda yo'q. Ma'no berish keyingi qadam va u ALOHIDA hujjatda
yashaydi, chunki inventarizatsiyani talqin bilan qo'shib yuborsa, taxmin dalilga o'xshab
qoladi.

KUCHGA KIRITILADIGAN INVARIANTLAR (`binos-1c-discovery-v1` bilan bir xil qat'iylik):
  1. JSON SONI TAQIQLANGAN. Har qanday sanoq — MATN ("7137"). Sabab: `0000123` soni `123`
     bo'lib qoladi va boshidagi nollar bilan birga ma'no yo'qoladi.
  2. Kalitlar OQ RO'YXAT bilan: noma'lum kalit — RAD, tushib qolgan kalit ham — RAD. Yangi
     maydon faqat sxema versiyasi oshganda qo'shiladi.
  3. `full_name` SHAKLI qat'iy (`<Prefiks>.<Nom>`, faqat identifikator belgilari, oxirgi bo'lak
     `name` ga mos — `FULL_NAME_RE` izohiga qarang) va takrorlanmaydi; maydon, jadval bo'limi
     va sanab o'tilgan qiymat nomlari
     BITTA manzil maydonini bo'lishadi (grafda hammasi `<obyekt>.<nom>`) va u yerda
     takrorlanmaydi. ⚠️ Ularning HAR BIRI ham 1C identifikatorining BELGI TO'PLAMIDA bo'lishi
     shart (`_ident` -> `_IDENT_RE`): manzilga chiqadigan nom bajarish yo'lidagi qiymat, ya'ni
     undagi qo'shtirnoq yoki qavs 1C tomonidagi satr literalini yopish yo'li bo'lardi.
  4. Ko'rilmagan narsa TASHLAB KETILMAYDI: yig'uvchi qaramagan joyni `unknown`/`null` bilan
     yozadi. «Qaralmadi» va «yo'q» bir xil narsa emas.
  5. Sir topilsa — RAD (`redact.scan`, fail-closed).
  6. `reference_targets` hujjatda YO'Q obyektni ko'rsatsa — RAD ETILMAYDI. Konfiguratsiya
     bo'lak-bo'lak olinishi mumkin, shuning uchun bunday havola «tashqi/aniqlanmagan» deb
     SAQLANADI (`unresolved_references`). Jimgina o'chirib tashlash — ma'lumot yo'qotish.
  7. Bo'sh `objects` RAD ETILMAYDI (bo'sh konfiguratsiya ham javob), lekin `sections` bo'sh
     bo'lmaydi: yig'uvchi nimani urinib ko'rganini AYTISHI shart.
  8. Vaqt bu yerda O'YLAB CHIQARILMAYDI — `collected_at` faqat kirishdan keladi.

Bu modulda birorta konfiguratsiyaga oid nom YO'Q: obyekt nomlari hujjat ICHIDAN kelgan
MA'LUMOT. Misollar to'qima: `X17`, `R41`, `ABCD`.
"""
from __future__ import annotations

import re

from .bundle import COUNT_TEXT_RE, SECTION_STATUSES, DiscoveryError, dumps
from . import redact as redaction
from .schema import SOURCE_KINDS
from ..migrator_1c.bundle import BundleError, parse_ts

METADATA_VERSION = "binos-1c-metadata-v1"

# ── Kalit oq ro'yxatlari ───────────────────────────────────────────────────────────────────
METADATA_KEYS = {"metadata_version", "collector", "collected_at", "objects", "sections", "notes"}
COLLECTOR_KEYS = {"name", "version"}
OBJECT_KEYS = {"full_name", "kind", "name", "synonym", "comment", "hierarchical", "row_count",
               "attributes", "dimensions", "resources", "tabular_sections", "enum_values",
               "predefined", "register_kind", "periodicity", "errors"}
FIELD_KEYS = {"name", "synonym", "kind", "type", "reference_targets", "numeric_digits",
              "numeric_scale", "string_length"}
TABULAR_KEYS = {"name", "synonym", "attributes"}
SECTION_KEYS = {"name", "status", "error"}

#: Obyekt darajasidagi maydon ro'yxatlari (tartibi SHARTNOMA: grafda ham shu tartib).
FIELD_LISTS = ("attributes", "dimensions", "resources")

#: 1C uchulik mantiqi MATN bilan keladi — `Булево` JSON'da `true` bo'lib ketmasin.
#: ⚠️ `"unknown"` = «yig'uvchi qaramadi», `"false"` = «qaradi va yo'q». Ikkisi bir xil emas.
HIERARCHICAL = {"true": True, "false": False, "unknown": None}

#: Registr turi. `"unknown"` va `null` farqi: `null` — bu obyekt registr emas.
REGISTER_KINDS = ("balance", "turnover", "unknown")

#: ⚠️ Nomda nuqta BO'LMAYDI: nuqta grafda ota-bola manzilini ajratadi (`<bo'lim>.<maydon>`),
#: ya'ni nomdagi nuqta manzilni ikki xil o'qishga imkon berardi. 1C identifikatorida ham
#: nuqta bo'lmaydi, shuning uchun bu cheklov hech narsani yo'qotmaydi.
NAME_SEP = "."

#: 1C identifikatorining BELGI TO'PLAMI: harf yoki pastki chiziq bilan boshlanadi, keyin harf,
#: raqam yoki pastki chiziq. Harflar har qanday alifboda bo'lishi mumkin (`\w` unicode) —
#: platforma nomlari kirill ham, lotin ham bo'ladi va yadro ularning birortasini afzal ko'rmaydi.
#: ⚠️ `[^\W\d]` = «so'z belgisi, lekin raqam emas»: identifikator raqam bilan boshlanmaydi.
_IDENT_RE = re.compile(r"[^\W\d]\w*")

#: `full_name` SHAKLI: AYNAN `<Prefiks>.<Nom>` — ikki identifikator, bitta ajratuvchi nuqta.
#: ⚠️ NEGA SHAKL TEKSHIRILADI (bu TOPILGAN TESHIK edi). `full_name` faqat «bo'sh bo'lmagan matn»
#:    deb tekshirilganda uning ichida qo'shtirnoq, nuqtali vergul yoki qavs bo'lishi mumkin edi.
#:    Bu qiymat KO'CHIB BORADI: grafga tushadi, zond nishoni bo'lib `validate_probe` dan O'TADI
#:    (chunki u rostdan grafda bor), ko'rik artefaktiga `target_object` bo'lib chiqadi va
#:    operator uni 1C tomonidagi SATR LITERALIGA qo'yadi. Ya'ni yig'uvchi (yoki uning yukini
#:    o'zgartirgan kim) nom ichiga literalni yopib, ortidan YOZUVCHI amal qo'shib yuborishi
#:    mumkin bo'lardi — «faqat o'qiydi» kafolati nomning SHAKLIGA suyanadi.
#: ⚠️ Shakl 1C ning O'Z qoidasidan qat'iyroq EMAS: platformada to'liq nom aynan
#:    `<metadata turi>.<identifikator>` va identifikatorda nuqta ham, tinish belgisi ham yo'q.
#:    Shu bois bu cheklov hech qanday haqiqiy nomni yo'qotmaydi.
FULL_NAME_RE = re.compile(rf"{_IDENT_RE.pattern}\{NAME_SEP}{_IDENT_RE.pattern}")


class MetadataError(DiscoveryError):
    """Inventarizatsiya hujjati buzuq, to'liqsiz yoki ichida sir bor — o'qilmaydi.

    `DiscoveryError` dan meros: to'plamni o'qiydigan mavjud kod bitta `except` bilan
    ikkala hujjatni ham qamrab oladi."""


# ── Kichik yordamchilar (bundle.py dagi bilan bir xil shakl, boshqa xato turi) ─────────────
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise MetadataError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = set(obj) - allowed
    _need(not extra, f"{where}: noma'lum kalit(lar) {sorted(extra)} — {METADATA_VERSION} da yo'q")
    missing = allowed - set(obj)
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {sorted(missing)}")


def _text_or_none(v, where: str):
    _need(v is None or isinstance(v, str), f"{where} matn yoki null bo'lishi kerak")
    return v


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _ident(v, where: str) -> str:
    """1C IDENTIFIKATORI: bo'sh emas, ichida nuqta yo'q va `_IDENT_RE` belgi to'plamida.

    ⚠️ BELGI TO'PLAMI TEKSHIRUVI TOPILGAN TESHIK edi. Ilgari `_IDENT_RE` FAQAT `FULL_NAME_RE`
       ni yasash uchun ishlatilardi, `_ident()` ning o'zi esa (a) bo'sh emas, (b) nuqta yo'q
       deb tekshirardi. Ya'ni `Tovar"Nomi`, `Tovar; DROP`, `Tovar)`, `Tovar Nomi` kabi
       qiymatlar O'TIB KETARDI.
    ⚠️ NEGA BU BAJARISH YO'LIDAGI QIYMAT. `_ident()` ni uch joy chaqiradi va UCHOVI HAM grafda
       `<obyekt>.<nom>` MANZILIGA aylanadi:
         · `_validate_field(...).name`          — maydon nomi (rekvizit, o'lchov, resurs va
                                                  jadval bo'limi maydoni);
         · `tabular_sections[i].name`           — jadval bo'limi nomi;
         · `_ident_list` -> `enum_values[i]`    — sanab o'tilgan qiymat.
       Bu manzil `field_type_details` zondining `target_object` iga AYNAN shunday chiqadi
       (`ai._field_addresses`), ko'rik artefaktida ko'rinadi va operator uni 1C tomonidagi
       SATR LITERALIGA qo'yadi. Nom ichidagi qo'shtirnoq literalni YOPIB, ortidan yozuvchi
       amal qo'shish yo'lini ochardi — «faqat o'qiydi» kafolati nomning SHAKLIGA suyanadi.
    ⚠️ Cheklov 1C ning O'Z qoidasidan qat'iyroq EMAS: platforma identifikatori harf yoki
       pastki chiziq bilan boshlanadi, keyin harf/raqam/pastki chiziq. ALIFBO AHAMIYATSIZ —
       kirill nom ham, lotin nom ham (`X17`, `Qoldiq_2`), pastki chiziq bilan boshlangan
       `_Holat` ham QONUNIY va rad ETILMAYDI. Shu bois `_IDENT_RE` unicode `\\w` ga tayanadi,
       ASCII ro'yxatiga emas: bitta alifboni «standart» deb olgan darvoza boshqa tildagi
       do'konda birinchi kunda yiqilardi.
    ⚠️ Nuqta tekshiruvi BIRINCHI turadi va o'z xato matnini saqlaydi: nuqtali nom «belgi
       to'plami» muammosi emas, MANZIL IKKI XIL O'QILISHI muammosi, va sababni aralashtirish
       operatorni noto'g'ri tuzatishga undardi."""
    _nonempty(v, where)
    _need(NAME_SEP not in v,
          f"{where} ichida nuqta bo'lmasligi kerak (manzil ikki xil o'qilib qoladi): {v!r}")
    _need(_IDENT_RE.fullmatch(v),
          f"{where} 1C IDENTIFIKATORI bo'lishi kerak — harf yoki pastki chiziq bilan "
          f"boshlanadi, keyin faqat harf (kirill ham, lotin ham), raqam yoki pastki chiziq. "
          f"Kelgani {v!r}. Sabab: bu nom grafda `<obyekt>.<nom>` MANZILI bo'ladi, zond "
          f"nishoniga va ko'rik artefaktiga chiqadi, ya'ni ichidagi tinish belgisi 1C "
          f"tomonidagi satr literalini YOPIB, ortidan boshqa amal qo'shish yo'lini ochardi")
    return v


def _full_name(v, name: str, where: str) -> str:
    """Obyektning to'liq nomi: `<Prefiks>.<Nom>`, va oxirgi bo'lak `name` ga AYNAN mos.

    ⚠️ Uchta tekshiruv ham KERAK va ularning birortasi qolganini almashtirmaydi:
       1. SHAKL — ikki identifikator + bitta nuqta (`FULL_NAME_RE` izohiga qarang: bu qiymat
          operator qo'lidagi shablonga tushadi, ya'ni undagi tinish belgisi bajariladigan
          amalga aylanib ketishi mumkin);
       2. BELGI TO'PLAMI — faqat harf/raqam/pastki chiziq (shaklning o'zi buni qamraydi, lekin
          sabab boshqa: `full_name` ning IKKI BO'LAGIDAGI qo'shtirnoq, qavs, vergul, probel va
          nuqtali vergul AYNAN shu yerda to'sib qolinadi).
          ⚠️ QAMROVNI ANIQ O'QING: bu yer FAQAT `full_name` ni qo'riqlaydi. Grafda manzil
             bo'lib ketadigan QOLGAN nomlar — maydon nomi (`attributes`/`dimensions`/
             `resources` va jadval bo'limi maydonlari), jadval bo'limi nomi va `enum_values`
             a'zolari — o'z belgi to'plami darvozasini `_ident()` da oladi (u ham `_IDENT_RE`
             ni qo'llaydi). Ilgari shunday emas edi: `_ident()` faqat «bo'sh emas + nuqta yo'q»
             deb tekshirardi, ya'ni shu izohdagi da'vo maydon nomi uchun YOLG'ON edi va
             `objects[i].attributes[j].name` ga qo'shtirnoqli qiymat qo'ysa, hujjat ham,
             graf ham, `validate_probe` ham uni QABUL QILARDI;
       3. `name` bilan MOSLIK — aks holda bir obyekt ikki xil nom bilan yurardi: graf va ko'rik
          artefakti `full_name` ni ko'rsatardi, tasdiq hujjati esa `name` ni, va operator
          nimani tasdiqlaganini keyin isbotlab bo'lmasdi."""
    _nonempty(v, where)
    _need(FULL_NAME_RE.fullmatch(v),
          f"{where} shakli `<Prefiks>{NAME_SEP}<Nom>` bo'lishi kerak — faqat 1C identifikator "
          f"belgilari (harf, raqam, pastki chiziq) va BITTA ajratuvchi nuqta. Kelgani {v!r}. "
          f"Sabab: bu nom zond nishoni va ko'rik artefaktiga chiqadi, ya'ni ichidagi tinish "
          f"belgisi 1C tomonidagi satr literalini YOPIB, ortidan boshqa amal qo'shish yo'lini "
          f"ochardi")
    oxirgi = v.rsplit(NAME_SEP, 1)[1]
    _need(oxirgi == name,
          f"{where} oxirgi bo'lagi `name` ga mos emas: {oxirgi!r} != {name!r} — bitta obyekt "
          f"ikki xil nom bilan yura olmaydi (graf `full_name` ni, tasdiq hujjati `name` ni "
          f"ko'rsatardi va ikkisi bir-birini tekshirmay qolardi)")
    return v


def _count_or_none(v, where: str):
    """Sanoq — MATN yoki `null`. JSON soni ATAYLAB RAD etiladi."""
    if v is None:
        return None
    if isinstance(v, (bool, int, float)):
        _need(False, f"{where} JSON SONI bo'lmasligi kerak — MATN yozing "
                     f"(0000123 soni 123 bo'lib qoladi, boshidagi nollar yo'qoladi): {v!r}")
    _need(isinstance(v, str) and COUNT_TEXT_RE.fullmatch(v),
          f"{where} ASCII raqamli MATN yoki null bo'lishi kerak "
          f"(JSON soni TAQIQLANGAN) — kelgani {v!r}")
    return v


def _str_list(v, where: str) -> list[str]:
    _need(isinstance(v, list) and all(isinstance(x, str) for x in v),
          f"{where} matnlar ro'yxati bo'lishi kerak")
    return v


def _name_list(v, where: str) -> list[str]:
    """Faqat NOMLAR ro'yxati (masalan `predefined`) — qiymat, indeks va tartib raqami YO'Q.

    ⚠️ Bu yerda nuqta TAQIQLANMAYDI: `reference_targets` ham shu yordamchidan o'tadi va unda
    obyektning TO'LIQ nomi turadi (nuqta bilan). Grafda MANZIL bo'lib ketadigan nomlar uchun
    `_ident_list` ishlatiladi."""
    _str_list(v, where)
    for i, x in enumerate(v):
        _nonempty(x, f"{where}[{i}]")
    dupes = sorted({x for x in v if v.count(x) > 1})
    _need(not dupes, f"{where}: nom takrorlangan {dupes}")
    return v


def _ident_list(v, where: str) -> list[str]:
    """Nomlar ro'yxati, lekin har biri IDENTIFIKATOR — grafda manzil bo'lib ketadigan nomlar.

    ⚠️ Nuqta TAQIQLANGAN (`NAME_SEP` ga qarang): sanab o'tilgan qiymat grafda
    `<obyekt>.<qiymat>` bo'lib manzillanadi, ya'ni nomdagi nuqta manzilni ikki xil o'qishga
    imkon berardi (`<obyekt>.<bo'lim>.<maydon>` bilan farqsiz bo'lib qolardi)."""
    _name_list(v, where)
    for i, x in enumerate(v):
        _ident(x, f"{where}[{i}]")
    return v


# ── Maydon (FieldDoc) ─────────────────────────────────────────────────────────────────────
def _validate_field(f, where: str) -> None:
    _keys(f, FIELD_KEYS, where)
    _ident(f["name"], f"{where}.name")
    _text_or_none(f["synonym"], f"{where}.synonym")
    _need(f["kind"] in SOURCE_KINDS, f"{where}.kind noma'lum: {f['kind']!r}")
    # ⚠️ `type` — 1C tip tavsifining MATN ko'rinishi (masalan "Строка(14)"). Uni bo'laklarga
    #    ajratish TALQIN bo'lardi: platforma versiyalari tavsifni boshqacha yozadi va
    #    noto'g'ri ajratish jimgina xato beradi. Xom matn saqlanadi.
    _nonempty(f["type"], f"{where}.type")
    _name_list(f["reference_targets"], f"{where}.reference_targets")
    for k in ("numeric_digits", "numeric_scale", "string_length"):
        _count_or_none(f[k], f"{where}.{k}")


def _field_names(rows: list, where: str) -> list[str]:
    _need(isinstance(rows, list), f"{where} ro'yxat bo'lishi kerak")
    names = []
    for i, f in enumerate(rows):
        _validate_field(f, f"{where}[{i}]")
        names.append(f["name"])
    return names


# ── Obyekt (ObjectDoc) ────────────────────────────────────────────────────────────────────
def _validate_object(o, where: str) -> None:
    _keys(o, OBJECT_KEYS, where)
    _ident(o["name"], f"{where}.name")
    _full_name(o["full_name"], o["name"], f"{where}.full_name")
    _need(o["kind"] in SOURCE_KINDS, f"{where}.kind noma'lum: {o['kind']!r}")
    _text_or_none(o["synonym"], f"{where}.synonym")
    _text_or_none(o["comment"], f"{where}.comment")
    _need(o["hierarchical"] in HIERARCHICAL,
          f"{where}.hierarchical {sorted(HIERARCHICAL)} dan biri (MATN) bo'lishi kerak, "
          f"kelgani {o['hierarchical']!r}")
    _count_or_none(o["row_count"], f"{where}.row_count")

    # Obyekt darajasidagi maydonlar bitta nom maydonini bo'lishadi: grafda ularning manzili
    # `<obyekt>.<nom>` bo'ladi, ya'ni rekvizit va o'lchov bir xil nomli bo'lsa manzil ikkilanadi.
    egallangan: list[str] = []
    for list_name in FIELD_LISTS:
        egallangan += _field_names(o[list_name], f"{where}.{list_name}")
    dupes = sorted({n for n in egallangan if egallangan.count(n) > 1})
    _need(not dupes, f"{where}: maydon nomi takrorlangan {dupes} "
                     f"({', '.join(FIELD_LISTS)} bitta manzil maydonini bo'lishadi)")

    ts = o["tabular_sections"]
    _need(isinstance(ts, list), f"{where}.tabular_sections ro'yxat bo'lishi kerak")
    ts_names = []
    for i, sec in enumerate(ts):
        sw = f"{where}.tabular_sections[{i}]"
        _keys(sec, TABULAR_KEYS, sw)
        _ident(sec["name"], f"{sw}.name")
        _text_or_none(sec["synonym"], f"{sw}.synonym")
        _field_names(sec["attributes"], f"{sw}.attributes")
        snames = [f["name"] for f in sec["attributes"]]
        sdupes = sorted({n for n in snames if snames.count(n) > 1})
        _need(not sdupes, f"{sw}.attributes: maydon nomi takrorlangan {sdupes}")
        ts_names.append(sec["name"])
    tdupes = sorted({n for n in ts_names if ts_names.count(n) > 1})
    _need(not tdupes, f"{where}.tabular_sections: nom takrorlangan {tdupes}")

    _ident_list(o["enum_values"], f"{where}.enum_values")
    _name_list(o["predefined"], f"{where}.predefined")

    # ⚠️ GRAFDA MANZIL MAYDONI BITTA. Obyekt darajasidagi maydon, jadval bo'limi va sanab
    #    o'tilgan qiymat — uchalasi ham `<obyekt>.<nom>` shaklida manzillanadi, ya'ni ular
    #    BITTA nom maydonini bo'lishadi. Ilgari faqat maydonlar o'zaro va bo'limlar o'zaro
    #    tekshirilardi; shu bois rekvizit bilan jadval bo'limi bir xil nomli bo'lsa, ikki
    #    BOSHQA narsa bir xil manzilga ega bo'lib qolardi va operatorning tasdig'i qaysi
    #    biriga tegishli ekani aniqlanmay qolardi (tasdiq manzil bo'yicha bog'lanadi).
    manzillar = egallangan + ts_names + list(o["enum_values"])
    mdupes = sorted({n for n in manzillar if manzillar.count(n) > 1})
    _need(not mdupes,
          f"{where}: grafdagi manzil takrorlangan {mdupes} — maydon, jadval bo'limi va sanab "
          f"o'tilgan qiymat bitta manzil maydonini (`<obyekt>.<nom>`) bo'lishadi")
    _need(o["register_kind"] is None or o["register_kind"] in REGISTER_KINDS,
          f"{where}.register_kind {sorted(REGISTER_KINDS)} dan biri yoki null bo'lishi kerak, "
          f"kelgani {o['register_kind']!r}")
    _text_or_none(o["periodicity"], f"{where}.periodicity")
    _str_list(o["errors"], f"{where}.errors")


# ── Bo'limlar ─────────────────────────────────────────────────────────────────────────────
def _validate_sections(secs, where: str = "metadata.sections") -> None:
    """Yiqilgan bo'lim JIMGINA TUSHIB QOLMAYDI — u xatosi bilan ro'yxatda qoladi."""
    _need(isinstance(secs, list) and secs,
          f"{where} bo'sh bo'lmagan ro'yxat bo'lishi kerak — yig'uvchi nimani urinib "
          f"ko'rganini aytishi SHART (bo'sh ro'yxat «hech narsa qaralmadi» degani)")
    names = []
    for i, sec in enumerate(secs):
        w = f"{where}[{i}]"
        _keys(sec, SECTION_KEYS, w)
        _nonempty(sec["name"], f"{w}.name")
        _need(sec["status"] in SECTION_STATUSES, f"{w}.status noma'lum: {sec['status']!r}")
        _text_or_none(sec["error"], f"{w}.error")
        _need(sec["status"] == "ok" or (sec["error"] or "").strip(),
              f"{w}: `{sec['status']}` bo'lgan bo'lim sababsiz qolmaydi — `error` ni to'ldiring")
        _need(sec["status"] != "ok" or not sec["error"],
              f"{w}: `ok` bo'limda `error` bo'lmasligi kerak")
        names.append(sec["name"])
    dupes = sorted({n for n in names if names.count(n) > 1})
    _need(not dupes, f"{where}: bo'lim nomi takrorlangan {dupes}")


# ── Aniqlanmagan havolalar ────────────────────────────────────────────────────────────────
def unresolved_references(doc: dict) -> tuple[str, ...]:
    """Hujjatda YO'Q obyektga qilingan havolalar (tartiblangan, takrorsiz).

    ⚠️ Bu XATO EMAS. Konfiguratsiya bo'lak-bo'lak olinishi mumkin (yig'uvchi bir qismini
    ko'rmagan bo'lishi mumkin), shuning uchun bunday havola «tashqi/aniqlanmagan» sifatida
    SAQLANADI. U jimgina o'chirilsa — grafda mavjud bog'lanish yo'qqa chiqadi."""
    mavjud = {o["full_name"] for o in doc["objects"]}
    topilmagan: set[str] = set()
    for o in doc["objects"]:
        for list_name in FIELD_LISTS:
            for f in o[list_name]:
                topilmagan |= {t for t in f["reference_targets"] if t not in mavjud}
        for sec in o["tabular_sections"]:
            for f in sec["attributes"]:
                topilmagan |= {t for t in f["reference_targets"] if t not in mavjud}
    return tuple(sorted(topilmagan))


# ── Validator ─────────────────────────────────────────────────────────────────────────────
def validate_metadata(doc) -> tuple[str, ...]:
    """Inventarizatsiya hujjatini QAT'IY tekshiradi. Xato — `MetadataError`.

    Qaytaradi: aniqlanmagan havolalar (`unresolved_references`) — chaqiruvchi ularni
    yo'qotmasligi uchun. Hujjat O'ZGARTIRILMAYDI."""
    _keys(doc, METADATA_KEYS, "metadata")
    _need(doc["metadata_version"] == METADATA_VERSION,
          f"metadata.metadata_version {METADATA_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['metadata_version']!r}")

    _keys(doc["collector"], COLLECTOR_KEYS, "metadata.collector")
    for k in sorted(COLLECTOR_KEYS):
        _nonempty(doc["collector"][k], f"metadata.collector.{k}")

    # ⚠️ Vaqt KIRISHDAN keladi; bu yerda «hozir» o'ylab chiqarilmaydi. `null` — yig'uvchi
    #    vaqtni bera olmagani, bu ham javob.
    if doc["collected_at"] is not None:
        _nonempty(doc["collected_at"], "metadata.collected_at")
        try:
            parse_ts(doc["collected_at"], "metadata.collected_at")
        except BundleError as e:
            raise MetadataError(str(e)) from e

    objs = doc["objects"]
    # ⚠️ Bo'sh `objects` — HAQIQIY javob (masalan yig'uvchi hamma bo'limda yiqilgan).
    #    Bo'limlar buni sababi bilan ko'rsatadi, shu bois bu yerda RAD YO'Q.
    _need(isinstance(objs, list), "metadata.objects ro'yxat bo'lishi kerak")
    for i, o in enumerate(objs):
        _validate_object(o, f"metadata.objects[{i}]")
    to_liq = [o["full_name"] for o in objs]
    dupes = sorted({n for n in to_liq if to_liq.count(n) > 1})
    _need(not dupes, f"metadata.objects: full_name takrorlangan {dupes}")

    _validate_sections(doc["sections"])
    _str_list(doc["notes"], "metadata.notes")

    # Fail-closed: sir shubhasi bo'lsa hujjat O'QILMAYDI. Yolg'on ijobiy — bir marta qo'lda
    # ko'rish; yolg'on salbiy — mijozning paroli hujjat bilan birga tarqaladi.
    findings = redaction.scan(doc)
    _need(not findings,
          "metadata hujjatida sir shubhasi bor — RAD: "
          + "; ".join(str(f) for f in findings[:10]))

    return unresolved_references(doc)


def dump_metadata(doc) -> str:
    """Tekshiradi va DETERMINISTIK yozadi: kalitlar tartiblangan, bir xil kirish — bir xil bayt."""
    validate_metadata(doc)
    return dumps(doc)
