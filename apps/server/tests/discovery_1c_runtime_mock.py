# -*- coding: utf-8 -*-
"""MOCK RUNTIME — sintetik runtime paketi GENERATORLARI (§10).

⚠️⚠️ BU MOCK REAL 1C ISHLASHINI ISBOTLAMAYDI. U faqat BinOS tomonidagi o'rash mantiqini
     (validator, fail-safe talqini) sinaydi.

⚠️⚠️ Aniqroq aytilsa: bu fayl `.epf` ni kompilyatsiya QILMAYDI, 1C ga ULANMAYDI va
     `BinOSDiscovery.bsl` ning birorta satrini BAJARMAYDI. U shunchaki `runtime_bundle.py`
     ta'riflagan yetti artefakt SHAKLIDA baytlar yozadi. Ya'ni bu generatorlar javob
     beradigan savol: «paket shunday ko'rinsa, BinOS tomoni TO'G'RI hukm chiqaradimi?».
     Yig'uvchining runtime holati bundan keyin ham `RUNTIME-UNKNOWN` bo'lib qoladi.

⚠️⚠️ SHU BOIS BU FAYL «SIMULYATOR» EMAS, «SHAKL GENERATORI». Haqiqiy 1C nima yozishini u
     BILA OLMAYDI — u men (BinOS tomoni) KUTGAN shaklni yozadi. Agar yig'uvchi boshqa shakl
     yozsa, bu fayldagi hech narsa yiqilmaydi: shu asimmetriya ochiq aytiladi, chunki
     «mock o'tdi» degan gap «yig'uvchi to'g'ri yozadi» degani EMAS.

NOMLAR HAQIQIY. Bo'lim nomlari (`metadata_sweep`, `chart_of_accounts`, `write_export`, ...)
va oila nomlari (`Справочники`, `ПланыСчетов`, ...) `BinOSDiscovery.bsl` ning O'ZIDAN olingan
(`ОтметитьЗапуск` chaqiruvlari va `ОписанияКоллекций()`), o'ylab chiqarilmagan. Metadata
obyektlarining nomlari esa sintetik fiksturalardan keladi va ULAR to'qima.

⚠️ SHAKL YAGONA HAQIQIY SHAKLGA MOSLANDI (`runtime_bundle` docstringi): yurish jurnali
   `probes` (ilgari `probes_run`), `run_status` da `platform`, `error_count` va `notes` ham
   bor, `errors.json` va `manifest.json` da `notes` (+ `collected_at`) turadi. Sabab: ilgari
   faqat ARTEFAKT JADVALI kelishilgan edi, KALIT NOMLARI emas — natijada yig'uvchi va
   validator bir-biriga zid shakl yozdi va har bir real paket rad etilardi.

⚠️ `collector.version` `BinOSDiscovery.bsl` dagi `ОписаниеСборщика` bilan AYNI bo'lishi SHART.
   Mockda ilgari `0.1.0-UNVERIFIED` turardi, yig'uvchida esa `0.2.0-UNVERIFIED` — ya'ni
   fikstura yig'uvchining o'zi yozadigan qiymatni sinamayotgan edi.

⚠️ `probes` BO'LIMI (bo'lim jurnalidagi `skipped` qatori) bu generatorlarda ATAYLAB YO'Q,
   lekin SABAB ENDI BOSHQA. `derive_overall` tuzatildi: `skipped` bo'lim ham, `absent` oila
   ham `SUCCESS` ni BUZMAYDI (ilgari buzardi va shu tufayli HAR BIR halol `METADATA_ONLY`
   yurishi rad etilardi). Bu generatorlar bo'lim holatlarini BIR XIL (`ok`) qoldiradi, chunki
   ularning o'lchash mavzusi OILALAR va XATOLAR: `skipped` bo'lim qo'shilsa, «yagona iz»
   fiksturalari ikki narsani bir vaqtda o'zgartirgan bo'lardi. `skipped` bo'limning `SUCCESS`
   ni buzmasligi validator testida (`test_discovery_1c_runtime_bundle.py`) QULFLANGAN.
"""
from __future__ import annotations

import copy
import pathlib

from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.bundle import dumps
from app.services.migrator_1c.bundle import sha256_bytes
from tests.discovery_1c_export_synth import export_dict
from tests.discovery_1c_metadata_synth import CONFIG_A_STANDARD_RU, doc as metadata_doc
from tests.discovery_1c_metadata_synth import field, obj, section

# ══════════════════════════════════════════════════════════════════════════════════════════
# SHARTNOMA QIYMATLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Versiyada `UNVERIFIED` ATAYLAB turadi: yig'uvchi birorta haqiqiy konfiguratsiyada
#: tasdiqlanmagan. U ayni vaqtda `VERIFIED` darvozasining eng nozik holati — so'z chegarasi
#: bo'lmaganda bu HALOL versiya har bir paketni rad etardi.
#: ⚠️ QIYMAT `BinOSDiscovery.bsl` ning `ОписаниеСборщика()` funksiyasidan OLINGAN, o'ylab
#: chiqarilmagan: fikstura yig'uvchi AYNAN nima yozishini sinashi kerak.
COLLECTOR = {"name": "BinOSDiscovery", "version": "0.2.0-UNVERIFIED"}

#: §11 ishga tushirish maydonlari (`run_status.platform`). ⚠️ HAMMA QIYMAT MATN yoki `null`:
#: uchulik mantiq (`"unknown"`) JSON booleani bilan almashtirilmaydi, aks holda «qaralmadi»
#: «yo'q» bo'lib qolardi. ⚠️ Nomlar BSL dagi `СобратьПлатформуЗапуска` dan, qiymatlar esa
#: SINTETIK: bu hech kimning haqiqiy bazasi emas, shu bois ichida server nomi ham, ulanish
#: satri ham YO'Q (aks holda paket o'z sir skanidan o'tmasdi).
PLATFORM: dict[str, str | None] = {
    "platform_version": "8.3.24.1548",
    "configuration_name": "SintetikKonfiguratsiya",
    "configuration_version": "1.0.0.1",
    "configuration_modified": "unknown",
    "infobase_mode": "unknown",
    "infobase_id": None,
    "client_application_name": None,
    "client_kind": "unknown",
    "locale": "ru",
    "db_type": "unknown",
    "application_mode": "managed",
    "os_version": None,
}

#: Yurish izohlari (`run_status.notes`). ⚠️ «Ishlaydi» degan da'vo YO'Q va bu ataylab:
#: yig'uvchining runtime holati `RUNTIME-UNKNOWN` bo'lib qoladi.
RUN_NOTES: tuple[str, ...] = (
    "Bu yurish SINTETIK fiksturadan qurilgan — 1C da bajarilmagan.",
    "Rejim METADATA_ONLY: aktiv zond YO'Q, `probes` jurnali BO'SH.",
)

#: `errors.json` va `manifest.json` izohlari — ikkisi ham YANGI shaklda MAJBURIY kalit.
ERROR_NOTES: tuple[str, ...] = (
    "Bo'sh `errors` — hech qanday xato chiqmagani. Fayl BARIBIR yoziladi: faylning yo'qligi "
    "«xato bo'lmadi» degani emas, «yig'uvchi tugamadi» degani.",
)
MANIFEST_NOTES: tuple[str, ...] = (
    "Manifest FAQAT yozilgan baytlarni tavsiflaydi: fayl nomi, bayt hajmi, sha256.",
    "⚠️ PROVENANS DA'VOSI YO'Q va `manifest.json` O'ZI ro'yxatda turmaydi.",
)

#: ⚠️ Vaqt GENERATORNING KIRISHI, hisoblanmaydi: `ТекущаяДата()` kabi narsa determinizmni
#: buzardi va AYNI paketning ikki nusxasi ikki xil bayt berardi.
STARTED = "2026-09-30T10:14:30+06:00"
FINISHED = "2026-09-30T10:15:00+06:00"

#: Yig'uvchining bo'limlari — `BinOSDiscovery.bsl` dagi `ОтметитьЗапуск` nomlari.
#: ⚠️ `probes` YO'Q: modul docstringidagi izohga qarang.
SECTION_NAMES: tuple[str, ...] = (
    "mode",
    "platform_extended",
    "metadata_sweep",
    "counts",
    "catalogs",
    "documents",
    "information_registers",
    "accumulation_registers",
    "characteristic_type_plans",
    "enums",
    "constants",
    "common_attributes",
    "chart_of_accounts",
    "write_export",
    "write_metadata",
    "write_run_summary",
)

#: Metadata OILALARI — `ОписанияКоллекций()` dagi `collection` nomlari + `ПланыСчетов`
#: (u BSL da ataylab alohida ko'riladi, chunki `binos-1c-metadata-v1` ning `kind` lug'atida
#: hisob rejasi uchun qiymat yo'q).
FAMILY_NAMES: tuple[str, ...] = (
    "Справочники",
    "Документы",
    "РегистрыСведений",
    "РегистрыНакопления",
    "ПланыВидовХарактеристик",
    "Перечисления",
    "Константы",
    "ОбщиеРеквизиты",
    "ПланыСчетов",
)

#: Oila nomidan bo'lim nomiga — `unreadable` oila o'z bo'limini ham yiqitadi, ya'ni ikkisi
#: bir-biriga BOG'LIQ va generator ularni ALOHIDA yozib, bir-biriga zid qilib qo'ymasligi kerak.
FAMILY_SECTION: dict[str, str] = {
    "Справочники": "catalogs",
    "Документы": "documents",
    "РегистрыСведений": "information_registers",
    "РегистрыНакопления": "accumulation_registers",
    "ПланыВидовХарактеристик": "characteristic_type_plans",
    "Перечисления": "enums",
    "Константы": "constants",
    "ОбщиеРеквизиты": "common_attributes",
    "ПланыСчетов": "chart_of_accounts",
}

#: ⚠️ `absent` va `unreadable` ning IZOHI shu ikki matnda QULFLANGAN va generatorlar ikkisini
#: ARALASHTIRMAYDI: `absent` — «o'qildi va BO'SH» (JAVOB), `unreadable` — «o'qiy olmadim»
#: (javob YO'QLIGI). ⚠️ Matnda `absence_proven` kabi KUCHLI dalil turi ATAYLAB yozilmaydi:
#: bo'shlikni ko'rish uning ISBOTI emas, va `yiguvchidan_verified_yoq` darvozasi bunday so'zni
#: yig'uvchining chiqishida umuman ko'rmasligi kerak.
ABSENT_DETAIL = ("o'qildi va BO'SH: bu konfiguratsiyada bu turdagi obyekt YO'Q. "
                 "Bu TO'LIQ javob, «o'qilmadi» EMAS")
UNREADABLE_DETAIL = ("O'QIY OLMADIM: huquq yetmadi. Bu «bu konfiguratsiyada YO'Q» degani "
                     "EMAS — javobning O'ZI yo'q")

#: Xato kodlari — `ERROR_CODE_RE` shakli (bosh harf, `A-Z0-9_`).
#: ⚠️ BSL tomonidagi `kind` lug'ati KICHIK harfda (`unreadable`, `object_failed`) va bu
#: FARQ hisobotda qayd etiladi; generator BinOS shartnomasiga yozadi.
CODE_FAMILY_UNREADABLE = "FAMILY_UNREADABLE"
CODE_OBJECT_FAILED = "OBJECT_FAILED"
CODE_RUN_FAILED = "RUN_FAILED"


def _xulosa(*satrlar: str) -> str:
    """Operator uchun `run_summary.md`.

    ⚠️ Ichida fayl yo'li, e-mail, telefon va `IP:port` BO'LMAYDI: aks holda paket sir skanidan
       o'tmasdi va test o'zi qo'ygan tuzoqqa tushardi (sabab boshqa bo'lib, nuqson «topilgan»
       ko'rinardi)."""
    return "\n".join(("# BinOS Discovery — yurish xulosasi", "") + satrlar + ("",)) + "\n"


SUMMARY_MD = _xulosa(
    "- Rejim: METADATA_ONLY (aktiv zond YO'Q)",
    "- Ikki hujjat yozildi, bo'limlarning hammasi tugadi",
    "",
    "Bu hisobot yig'uvchining 1C da ISHLAGANINI isbotlamaydi.",
)


def bolimlar(**holat: tuple[str, str]) -> list[dict]:
    """`SECTION_NAMES` bo'yicha bo'limlar; `holat` da nomlangani almashtiriladi.

    `holat` qiymati — `(status, error)` juftligi. ⚠️ `ok` bo'limda `error` BO'LMAYDI va
    `ok` BO'LMAGAN bo'lim SABABSIZ qolmaydi — ikkisi ham `validate_run_status` da
    majburlanadi, shu bois generator ularni buzib qo'ymasligi uchun shakl bitta joyda."""
    out = []
    for nom in SECTION_NAMES:
        status, error = holat.get(nom, ("ok", None))
        out.append({"name": nom, "status": status, "error": error})
    return out


def oilalar(**holat: tuple[str, str | None]) -> list[dict]:
    """`FAMILY_NAMES` bo'yicha oilalar; `holat` da nomlangani almashtiriladi.

    ⚠️ Standart holat `present`. `absent` va `unreadable` ni CHAQIRUVCHI ANIQ so'raydi —
    jimgina standart qilib qo'yilmaydi, chunki aynan shu ikki qiymatning farqi sinaladi."""
    out = []
    for nom in FAMILY_NAMES:
        state, detail = holat.get(nom, ("present", None))
        out.append({"name": nom, "state": state, "detail": detail})
    return out


def xato(*, scope, family=None, obyekt=None, code, detail) -> dict:
    """`errors.json` ning bitta qatori (`binos-1c-errors-v1`).

    ⚠️ `obyekt` nomi ataylab `object` EMAS: `object` Python'da o'rnatilgan nom va uni
       argument nomi qilish yordamchini o'qishni qiyinlashtirardi."""
    return {"scope": scope, "family": family, "object": obyekt, "code": code, "detail": detail}


def xatolar(*rows: dict, collected_at: str | None = None) -> dict:
    """`errors.json` hujjati. BO'SH `errors[]` — QONUNIY javob (fayl esa SHART).

    ⚠️ `collected_at` — yig'ish vaqti; `null` bo'lishi MUMKIN (eski platformada vaqt olish
       yiqilsa YOLG'ON vaqt yozilmaydi). Fiksturada u KIRISH, hisoblanmaydi — aks holda
       determinizm buzilardi."""
    return {"errors_version": rb.ERRORS_VERSION,
            "collected_at": FINISHED if collected_at is None else collected_at,
            "errors": list(rows),
            "notes": list(ERROR_NOTES)}


# ══════════════════════════════════════════════════════════════════════════════════════════
# PAKET QURUVCHI
# ══════════════════════════════════════════════════════════════════════════════════════════
def _run_status(*, sections, families, mode=rb.MODE_METADATA_ONLY, mode_note=None,
                overall=None, probes=(), artifacts=(), error_count="0") -> dict:
    """`binos-1c-run-v1` — YAGONA HAQIQIY SHAKL. `overall` berilmasa HISOBLANADI.

    ⚠️ `overall` YAGONA TA'RIF bo'yicha hisoblanadi (`derive_overall`): majburiy artefaktlar
       yozilgan + `failed` bo'lim yo'q + `unreadable` oila yo'q. Ya'ni u bo'limlardan
       TASHQARI oilalarga va `artifacts` ga ham tayanadi — fikstura shu bois uchovini ham
       beradi.
    ⚠️ `overall` ni ATAYLAB berish mumkin: aynan shu yo'l bilan YOLG'ON `SUCCESS` quriladi
       va validator ziddiyatni ko'rishi tekshiriladi."""
    secs = copy.deepcopy(list(sections))
    fams = copy.deepcopy(list(families))
    arts = sorted(artifacts)
    return {
        "run_version": rb.RUN_VERSION,
        "collector": dict(COLLECTOR),
        "mode": mode,
        "mode_note": mode_note,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "overall": (rb.derive_overall(secs, families=fams, artifacts=arts)
                    if overall is None else overall),
        "platform": dict(PLATFORM),
        "sections": secs,
        "families": fams,
        "probes": [dict(p) for p in probes],
        "artifacts": arts,
        # ⚠️ SANOQ MATN: `0` soni emas, `"0"` matni (JSON soni TAQIQLANGAN).
        "error_count": error_count,
        "notes": list(RUN_NOTES),
    }


def _yolgon_xesh(raw: bytes) -> str:
    """SHAKLI TO'G'RI, lekin mazmuniga MOS KELMAYDIGAN sha256.

    ⚠️ Shakli ataylab to'g'ri (64 ta kichik hex): shaklni buzsak, validator «sha256 shakli
       xato» deb rad etardi va MOSLIK tekshiruvi umuman bajarilmay qolardi — ya'ni test
       boshqa darvozani o'lchagan bo'lardi."""
    return sha256_bytes(raw + b"\x00buzilgan")


def baytlar(*, export=None, metadata=None, errors=None, summary=None, sections=None,
            families=None, mode=rb.MODE_METADATA_ONLY, mode_note=None, overall=None,
            kesish=None, xesh_buzuq=(), drop=()) -> dict[str, bytes]:
    """SINTETIK runtime paketi: `nom -> baytlar`.

    QURILISH NAVBATI shartnomadagi YOZISH NAVBATI bilan AYNI, chunki shartnoma faqat shu
    navbatda bajarilishi mumkin:
      1. mazmun fayllari (`export.json`, `metadata.json`, `errors.json`, `run_summary.md`);
      2. `run_status.json` — `artifacts` da O'ZI ham, `manifest.json` ham SANALADI (nomni
         sanash mazmunga tegmaydi, shu bois aylanma YO'Q);
      3. `manifest.json` — 1 va 2 da yozilgan HAMMA faylning xeshi, O'ZIDAN tashqari.

    ⚠️ `kesish` (nom, ulush) manifest QURILISHIDAN OLDIN ishlaydi: yig'uvchi faylni yarim
       yozib to'xtagan bo'lsa, manifest ANIQ shu yarim baytlarni xeshlaydi, ya'ni xesh MOS
       bo'ladi. Shu bois yarim yozilishni FAQAT JSON parse tuta oladi — agar kesishni
       manifestdan keyin qilsak, test aslida xesh darvozasini o'lchagan bo'lardi.
    ⚠️ `drop` esa manifest QURILGANDAN KEYIN ishlaydi: haqiqiy nuqson aynan shunday
       ko'rinadi — fayl yo'qoladi, uni da'vo qilgan yozuvlar joyida qoladi.
    """
    export = export_dict() if export is None else export
    metadata = copy.deepcopy(CONFIG_A_STANDARD_RU) if metadata is None else metadata
    errors = xatolar() if errors is None else errors
    summary = SUMMARY_MD if summary is None else summary
    sections = bolimlar() if sections is None else sections
    families = oilalar() if families is None else families

    m: dict[str, bytes] = {
        rb.EXPORT_FILE: dumps(export).encode("utf-8"),
        rb.METADATA_FILE: dumps(metadata).encode("utf-8"),
        rb.ERRORS_FILE: dumps(errors).encode("utf-8"),
        rb.RUN_SUMMARY_FILE: summary.encode("utf-8"),
    }
    if kesish is not None:
        nom, ulush = kesish
        xom = m[nom]
        m[nom] = xom[:max(1, int(len(xom) * ulush))]

    run = _run_status(sections=sections, families=families, mode=mode, mode_note=mode_note,
                      overall=overall,
                      artifacts=sorted(set(m) | {rb.RUN_STATUS_FILE, rb.MANIFEST_FILE}),
                      # ⚠️ Sanoq `errors.json` dagi QATORLAR SONIDAN olinadi: fikstura
                      #    o'zining ikki hujjatini bir-biriga zid qilib qo'ymasligi kerak.
                      error_count=str(len(errors["errors"])))
    m[rb.RUN_STATUS_FILE] = dumps(run).encode("utf-8")

    files = [{"name": n, "bytes": str(len(m[n])),
              "sha256": _yolgon_xesh(m[n]) if n in xesh_buzuq else sha256_bytes(m[n])}
             for n in sorted(m)]
    m[rb.MANIFEST_FILE] = dumps({"manifest_version": rb.MANIFEST_VERSION, "files": files,
                                 "notes": list(MANIFEST_NOTES)}).encode("utf-8")

    for n in drop:
        m.pop(n, None)
    return m


def yoz(papka, members: dict[str, bytes]) -> str:
    """Paketni DISKKA yozadi va papka yo'lini qaytaradi.

    ⚠️ Papka yo'li hisobotga CHIQMAYDI (`Report.to_json` da yo'l ataylab yo'q), shu bois
       ikki xil `tmp_path` ga yozilgan AYNI paket AYNAN bir xil hisobot beradi — determinizm
       testi shunga tayanadi."""
    kok = pathlib.Path(papka)
    for nom, raw in sorted(members.items()):
        p = kok / nom
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    return str(kok)


# ══════════════════════════════════════════════════════════════════════════════════════════
# GENERATORLAR — har biri TO'LIQ runtime paketini `papka` ga YOZADI va yo'lini qaytaradi
# ══════════════════════════════════════════════════════════════════════════════════════════
def paket_sog_lom(papka) -> str:
    """HAMMA artefakt joyida, `overall=SUCCESS`, rejim `METADATA_ONLY`.

    Oilalar HAMMASI `present`, `errors[]` BO'SH, zond YO'Q. ⚠️ Bu boshqa generatorlarning
    BAZASI: ular shu paketdan BITTA narsani o'zgartiradi, shunda yiqilgan tekshiruv aynan
    o'sha o'zgarishga tegishli bo'ladi."""
    return yoz(papka, baytlar())


def paket_oila_yoq(papka) -> str:
    """Ixtiyoriy oila `absent`: `ПланыСчетов` O'QILDI va BO'SH.

    ⚠️ BU JAVOB, NUQSON EMAS. Shu bois: bo'lim `ok` (kolleksiyaga MUROJAAT muvaffaqiyatli
       bo'ldi, natijasi — bo'shlik), `errors.json` BO'SH (yo'qlik xato emas) va `overall`
       `SUCCESS` bo'lib qoladi. `paket_oila_oqilmadi` bilan solishtirilsa, ikki holatning
       farqi AYNAN shu uch joyda ko'rinadi."""
    return yoz(papka, baytlar(
        families=oilalar(ПланыСчетов=("absent", ABSENT_DETAIL)),
    ))


def paket_oila_oqilmadi(papka, *, yolgon_success: bool = False,
                        xato_yashirilgan: bool = False) -> str:
    """Oila `unreadable`: `ПланыСчетов` ga huquq yetmadi.

    ⚠️ JAVOB YO'Q, «yo'q» EMAS. Shu bois: bo'lim `failed` (sababi bilan), `errors.json` da
       `FAMILY_UNREADABLE` qatori bor va `overall` `PARTIAL` — o'qilmagan oila bilan yurish
       TO'LIQ deb e'lon qilinmaydi.
    ⚠️ `yolgon_success=True` bo'lsa AYNI paket `overall=SUCCESS` deb YOZILADI. Bu — `UNKNOWN`
       ni `NOT_FOUND` deb talqin qilishning paketdagi ko'rinishi: «o'qiy olmadim» jimgina
       «muammo yo'q» ga aylanadi. Validator buni ZIDDIYAT deb belgilashi SHART.
    ⚠️ `xato_yashirilgan=True` bo'lsa yurish o'qish xatosini `errors.json` ga ham, bo'lim
       jurnaliga ham YOZMAYDI: oila holatidan boshqa hech qanday iz qolmaydi. BU VARIANT
       KERAK, chunki oldingi variantda paket AYNI VAQTDA ikki qoidani buzadi (`errors[]`
       bo'sh emas + o'qilmagan oila) va shu bois `unreadable` qoidasini olib tashlasa ham
       paket rad etilib qolardi — ya'ni himoya O'LCHANMAY qolardi. Bu variantda YAGONA
       mumkin bo'lgan signal — o'qilmagan oila."""
    yashirilgan = xato_yashirilgan
    return yoz(papka, baytlar(
        sections=bolimlar() if yashirilgan
                 else bolimlar(chart_of_accounts=("failed", UNREADABLE_DETAIL)),
        families=oilalar(ПланыСчетов=("unreadable", UNREADABLE_DETAIL)),
        errors=xatolar() if yashirilgan
               else xatolar(xato(scope="family", family="ПланыСчетов",
                                 code=CODE_FAMILY_UNREADABLE, detail=UNREADABLE_DETAIL)),
        overall=rb.OVERALL_SUCCESS if (yolgon_success or yashirilgan) else None,
    ))


# ── G'alati nomlar ─────────────────────────────────────────────────────────────────────────
#: ⚠️ «G'alati» = SHAKLAN QONUNIY, lekin odam kutmaydigan. 1C identifikatorining belgi
#: to'plami (`metadata._IDENT_RE`) harf/raqam/pastki chiziqdan iborat va ALIFBO AHAMIYATSIZ,
#: shu bois pastdagi nomlar HAMMASI qonuniy va ular RAD ETILMASLIGI kerak.
UZUN_NOM = "Ж" * 220                     # juda uzun nom (kirill)
ARALASH_NOM = "Товарlar_ITEMS"           # aralash alifbo: kirill + lotin bir nomda
CHIZIQ_NOM = "_Holat"                    # pastki chiziq bilan BOSHLANADI — qonuniy
RAQAM_ICHIDA = "X17_2026"                # raqam ichida — qonuniy

#: ⚠️ FAQAT RAQAMLI nom esa QONUNIY EMAS: 1C identifikatori raqam bilan boshlanmaydi
#: (`_IDENT_RE = [^\\W\\d]\\w*`). U JIMGINA TASHLANMASLIGI, balki SABABI bilan RAD ETILISHI
#: kerak — «tushunmadim, o'tkazib yubordim» razvedkada yo'qotishning eng jim turi.
RAQAMLI_NOM = "12345"


def _gala_metadata(*, raqamli_nom: bool) -> dict:
    """G'alati nomli inventarizatsiya (`binos-1c-metadata-v1`).

    ⚠️ QAMROV ANIQ: g'aliblik faqat `metadata.json` da. `export.json` standart fikstura
       bo'lib qoladi, chunki graf AYNAN `metadata.json` dan quriladi (`build_graph`) va
       nishon to'liqligi esa `export.json` dan — ikkisini bir vaqtda o'zgartirsak, yiqilgan
       tekshiruv qaysi o'zgarishga tegishli ekani noaniq bo'lardi."""
    nomlar = [UZUN_NOM, ARALASH_NOM, CHIZIQ_NOM, RAQAM_ICHIDA]
    if raqamli_nom:
        nomlar.append(RAQAMLI_NOM)
    obyektlar = []
    for i, nom in enumerate(nomlar):
        obyektlar.append(obj(
            f"Справочник.{nom}", "catalog", nom,
            # ⚠️ BO'SH SINONIM: `binos-1c-metadata-v1` da sinonim «matn yoki null», ya'ni
            #    bo'sh matn QONUNIY va u `null` dan FARQ QILADI («sinonim yo'q» va «sinonim
            #    bo'sh qo'yilgan» bir xil emas). Shu bois u jimgina `null` ga aylanmasligi
            #    kerak va bu yerda ataylab sinaladi.
            synonym="" if i % 2 == 0 else None,
            row_count=str(i + 1),
            attributes=[
                field("Код", "standard_attribute", "Строка(11)", length="11"),
                field(RAQAM_ICHIDA, "attribute", "Строка(5)", synonym="", length="5"),
            ]))
    return metadata_doc(obyektlar, sections=[section(n) for n in ("catalogs", "counts")],
                        notes=["g'alati, lekin SHAKLAN qonuniy nomlar"])


def paket_gala_nomlar(papka, *, raqamli_nom: bool = False) -> str:
    """G'alati nomlar: bo'sh sinonim, 220 belgili nom, aralash alifbo, `_` bilan boshlangan.

    ⚠️ `raqamli_nom=False` (standart): hamma nom SHAKLAN QONUNIY, ya'ni paket O'TISHI va graf
       QURILISHI kerak. Nomi g'alati bo'lgani uchun obyektni tashlab ketish — ma'lumot
       yo'qotish.
    ⚠️ `raqamli_nom=True`: qo'shimcha obyektning nomi FAQAT RAQAM (`12345`). U 1C
       identifikatori EMAS va paket SABABI bilan RAD ETILISHI kerak. «Jimgina tashlab
       ketish» va «rad etish» orasidagi farq shu bayroq bilan qulflanadi."""
    return yoz(papka, baytlar(metadata=_gala_metadata(raqamli_nom=raqamli_nom)))


def paket_ulkan(papka, *, obyektlar: int = 2000) -> str:
    """ULKAN metadata: standart holda 2000+ obyekt.

    NIMA UCHUN: validator ishlashini (`graf_qurilishi`, `ai_kirishiga_tayyor`, sir skani
    hammasi shu hujjatdan o'tadi) va DETERMINIZMNI o'lchash uchun. ⚠️ Fikstura ataylab
    TEKIS va bir xil: mazmun emas, HAJM sinaladi, shu bois hujjat 30 sekunddan ancha tez
    qurilishi kerak.
    ⚠️ Nomlar `Obj000001` shaklida: raqam nom ICHIDA, boshida emas — aks holda identifikator
       qoidasini buzgan bo'lardi (`paket_gala_nomlar(raqamli_nom=True)` ga qarang)."""
    ro_yxat = []
    for i in range(obyektlar):
        nom = f"Obj{i:06d}"
        ro_yxat.append(obj(
            f"Справочник.{nom}", "catalog", nom, synonym=None, row_count=str(i),
            attributes=[field("Код", "standard_attribute", "Строка(11)", length="11"),
                        field("Nomi", "standard_attribute", "Строка(150)", length="150")]))
    metadata = metadata_doc(ro_yxat, sections=[section("catalogs"), section("counts")],
                            notes=[f"ulkan sintetik fikstura: {obyektlar} obyekt"])
    return yoz(papka, baytlar(metadata=metadata))


def paket_huquq_yoq(papka) -> str:
    """KO'P oila `unreadable` (huquq yetmadi), `overall=PARTIAL`.

    ⚠️ `PARTIAL`, `FAILED` EMAS: hech bo'lmasa bitta bo'lim tugadi. Va `SUCCESS` ham emas —
       o'qilmagan oila bilan yurish to'liq deb e'lon qilinmaydi.
    ⚠️ Har bir `unreadable` oila UCH JOYDA iz qoldiradi: bo'limi `failed`, oila holati
       `unreadable` va `errors.json` da qatori. Uchovidan birortasi tushib qolsa, «o'qiy
       olmadim» jimgina yo'qolardi."""
    oqilmagan = ("Документы", "РегистрыСведений", "РегистрыНакопления",
                 "ПланыВидовХарактеристик", "ПланыСчетов")
    return yoz(papka, baytlar(
        sections=bolimlar(**{FAMILY_SECTION[f]: ("failed", UNREADABLE_DETAIL)
                             for f in oqilmagan}),
        families=oilalar(**{f: ("unreadable", UNREADABLE_DETAIL) for f in oqilmagan}),
        errors=xatolar(*[xato(scope="family", family=f, code=CODE_FAMILY_UNREADABLE,
                              detail=UNREADABLE_DETAIL) for f in sorted(oqilmagan)]),
    ))


def paket_serializatsiya_yarim(papka) -> str:
    """`metadata.json` YARIM yozilgan — buzuq JSON.

    ⚠️ MANIFEST YARIM BAYTLARNI XESHLAYDI va shu ATAYLAB: xesh MOS keladi, ya'ni nuqsonni
       FAQAT qat'iy JSON o'qish tuta oladi. Aks holda test «xesh mos emas» ni topib, o'zini
       yarim yozilishni ushlagan deb hisoblardi — bu yolg'on ishonch bo'lardi.
    ⚠️ Kesish 60% da: fayl boshidagi kalitlar O'QILADI, oxiri yo'q. Shunda «umuman bo'sh
       fayl» degan osonroq holatga tushib qolmaymiz."""
    return yoz(papka, baytlar(kesish=(rb.METADATA_FILE, 0.6)))


def paket_qismli_inspeksiya(papka) -> str:
    """Ba'zi obyektlarning `errors` i to'lgan, qolgani SOG'LOM.

    ⚠️ INVARIANT: obyekt darajasidagi xato JIMGINA YO'QOLMAYDI. U (a) `metadata.json` dagi
       obyektning O'Z `errors` ida, (b) `errors.json` da `scope="object"` qatori bo'lib
       TURADI. Ikkinchisi bo'lmasa, hisobotni faqat `errors.json` dan o'qiydigan operator
       muammoni umuman ko'rmasdi.
    ⚠️ `overall` `PARTIAL`: `errors[]` bo'sh bo'lmagan yurish `SUCCESS` deb e'lon qilinmaydi
       (`overall_ziddiyatsiz` shuni majburlaydi)."""
    metadata = copy.deepcopy(CONFIG_A_STANDARD_RU)
    buzuq = []
    for o in metadata["objects"][:2]:
        o["errors"] = [f"`{o['full_name']}` rekvizitlari o'qilmadi: huquq yetmadi"]
        buzuq.append(o)
    return yoz(papka, baytlar(
        metadata=metadata,
        sections=bolimlar(catalogs=("failed", "ikki obyekt inspeksiyasi yiqildi")),
        errors=xatolar(*[xato(scope="object", family="Справочники", obyekt=o["full_name"],
                              code=CODE_OBJECT_FAILED, detail=o["errors"][0])
                         for o in buzuq]),
    ))


def paket_yolgon_success(papka, *, yoq: str = rb.RUN_SUMMARY_FILE) -> str:
    """`overall=SUCCESS`, LEKIN majburiy artefakt YO'Q — §6 ning ziddiyati.

    ⚠️ Ziddiyat oddiy nuqsondan QO'RQINCHLIROQ: u paketning O'Z hisobotiga ishonib
       bo'lmasligini ko'rsatadi. Shu bois bu paket `ok=False` bo'lishi va sabab ANIQ
       «ZIDDIYAT» deb aytilishi kerak.
    ⚠️ Standart holda `run_summary.md` olib tashlanadi: u JSON emas, ya'ni yo'qligi JSON
       o'qishni buzmaydi va ziddiyat tekshiruvi ARALASHMAGAN holda ko'rinadi."""
    return yoz(papka, baytlar(drop=(yoq,)))


def paket_manifest_mos_emas(papka) -> str:
    """Manifest xeshi fayl mazmuniga MOS EMAS.

    ⚠️ Xesh SHAKLI to'g'ri, faqat QIYMATI boshqa (`_yolgon_xesh`): shaklni buzsak, boshqa
       darvoza ishlab, moslik tekshiruvi umuman bajarilmay qolardi."""
    return yoz(papka, baytlar(xesh_buzuq=(rb.METADATA_FILE,)))


#: ⚠️ SIR SINTETIK VA ATAYLAB SHUNDAY KO'RINADI. Bu hech kimning haqiqiy ulanish satri emas;
#: qiymatlar to'qima. Testning maqsadi — shu qiymatlarning hisobot matnida KO'RINMASLIGINI
#: isbotlash, shu bois ular ALOHIDA doimiy bo'lib turadi va test ularni nom bilan qidiradi.
SIR_ULANISH = 'Srvr="vydumannyj-srv";Ref="vydumannaya";Usr=admin;Pwd=hunter2'
SIR_QIYMATLAR: tuple[str, ...] = ("vydumannyj-srv", "vydumannaya", "hunter2", "Pwd=")


def paket_sir_oqqan(papka) -> str:
    """`errors.json` ICHIDA 1C ulanish satri — sir paket bilan chiqib ketgan.

    ⚠️ HAQIQIY OQIM SHUNDAY: yig'uvchi 1C ning xato tavsifini `errors.json` ga qo'yadi, SUBD
       xatosi esa ulanish satrini va server nomini O'Z ICHIGA OLADI. Ya'ni bu holat operator
       xatosi emas, QUVURNING TABIIY natijasi — shu bois darvoza shu yerda turadi.
    ⚠️ Sir FAQAT `errors.json` da: `run_status.json` va `run_summary.md` toza qoladi. Shunda
       test sir skanining `errors.json` ni ROSTDAN o'qiyotganini o'lchaydi."""
    return yoz(papka, baytlar(
        sections=bolimlar(platform_extended=("failed", "platforma ma'lumoti olinmadi")),
        families=oilalar(),
        errors=xatolar(xato(scope="write", code=CODE_RUN_FAILED,
                            detail=f"baza bilan ishlash xatosi: {SIR_ULANISH}")),
    ))


# ══════════════════════════════════════════════════════════════════════════════════════════
# RO'YXATLAR — parametrlashtirilgan testlar uchun
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Validator QABUL QILISHI kerak bo'lgan paketlar: hammasi HALOL: yiqilish yashirilmagan,
#: sababi bilan qayd etilgan.
QABUL_GENERATORLAR: tuple[tuple[str, object], ...] = (
    ("sog_lom", paket_sog_lom),
    ("oila_yoq", paket_oila_yoq),
    ("oila_oqilmadi", paket_oila_oqilmadi),
    ("gala_nomlar", paket_gala_nomlar),
    ("huquq_yoq", paket_huquq_yoq),
    ("qismli_inspeksiya", paket_qismli_inspeksiya),
)

#: Validator RAD ETISHI kerak bo'lgan paketlar.
RAD_GENERATORLAR: tuple[tuple[str, object], ...] = (
    ("serializatsiya_yarim", paket_serializatsiya_yarim),
    ("yolgon_success", paket_yolgon_success),
    ("manifest_mos_emas", paket_manifest_mos_emas),
    ("sir_oqqan", paket_sir_oqqan),
    ("gala_nomlar_raqamli",
     lambda p: paket_gala_nomlar(p, raqamli_nom=True)),
    ("oila_oqilmadi_yolgon_success",
     lambda p: paket_oila_oqilmadi(p, yolgon_success=True)),
    ("oila_oqilmadi_xato_yashirilgan",
     lambda p: paket_oila_oqilmadi(p, xato_yashirilgan=True)),
)

#: HAMMA generator — `paket_ulkan` ham (u sekinroq, shu bois alohida ko'rsatilgan).
HAMMA_GENERATORLAR: tuple[tuple[str, object], ...] = (
    QABUL_GENERATORLAR + RAD_GENERATORLAR + (("ulkan", paket_ulkan),))
