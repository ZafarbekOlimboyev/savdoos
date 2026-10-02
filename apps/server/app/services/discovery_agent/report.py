# -*- coding: utf-8 -*-
"""`discovery_report.md` — ODAM O'QIYDIGAN hisobot: TAXMINLAR ro'yxati, xarita EMAS.

Bu modul yurish yozuvini (`status.AgentStatus`), ko'rik artefaktini (`discovery_1c.review`
qurgan lug'at) va validator hisobotini (`discovery_1c.runtime_bundle.Report`) bitta Markdown
matnga tizadi. U HECH NARSA HISOBLAMAYDI va hech qanday yangi da'vo qo'shmaydi: har bir satr
kirishdagi hujjatlarning birortasidan keladi.

⚠️⚠️ HISOBOTNING BOSHIDA OGOHLANTIRISH TURADI va u OLIB TASHLANMAYDI. Sabab oddiy: bu fayl
     qo'ldan-qo'lga o'tadi va ogohlantirishsiz u «tayyor xarita» ko'rinishida o'qiladi.
     Ogohlantirish to'rtta narsani aytadi: (1) bu TAXMIN, (2) hech narsa tasdiqlanmagan,
     (3) `VERIFIED` bu kanalda UMUMAN yo'q, (4) yig'uvchi `.epf` birorta HAQIQIY 1C da
     sinalmagan — `watch_folder` yo'li bo'lsa, AYNI SHU YURISH uning birinchi haqiqiy sinovi.

QAT'IY QOIDALAR:
  · ⚠️ YOZISHDAN OLDIN `discovery_1c.redact` darvozasi: matnda shubhali qiymat topilsa
    `ReportError` va HECH NARSA qaytmaydi (fail-closed). Niqoblab o'tkazib yuborish YO'Q:
    niqob operatordan qaysi qiymat yo'qolganini yashirardi, bu yerda esa SABABI bilan rad
    etiladi. Tashqi manbadan kelgan matn (validator nuqsonlari, xato tafsilotlari) esa
    chaqiruvchi tomonida ATAYLAB `redact.redact` dan o'tkaziladi — bu modul uni o'zi
    «tuzatmaydi».
  · ⚠️ DETERMINIZM: bir xil kirish — AYNAN bir xil bayt. Shu bois bu modulda VAQT
    O'YLAB CHIQARILMAYDI (hamma vaqt tamg'asi `status` dan keladi), fayl tizimiga murojaat
    YO'Q va ro'yxatlar kirishdagi (allaqachon tartiblangan) navbatda qoladi.
  · ⚠️ ABSOLYUT YO'L YOZILMAYDI: `status.bundle_dir` nisbiy nom, `redact` esa absolyut
    Windows yo'lini sir deb biladi — ya'ni yo'l yozgan kod butun hisobotni bloklardi.
  · ⚠️ `UNKNOWN` KONSEPTLAR TASHLANMAYDI: ular alohida bo'limda SANAB o'tiladi. «Qaralmadi»
    va «yo'q» bir xil narsa emas, va bu farqni faqat shu ro'yxat saqlaydi.
  · ⚠️ SANOQLAR MATN bo'lib yoziladi (hisobot matni, demak bu o'z-o'zidan bajariladi), ball
    esa O'LCHOV: u uch kasr xona bilan yoziladi — modelning uzun kasri bayt darajasida
    farqlanadigan chiqish berardi, ma'no esa o'zgarmaydi.
  · ⚠️⚠️ YO'L HAQQONIYLIGI (brief §7): hisobot «avtomatik 1C razvedkasi bajarildi»
    ma'nosini beradigan IBORANI chiqara OLMAYDI — `_assert_no_automatic_claim` darvozasi
    topilsa `ReportError` beradi va HECH NARSA qaytmaydi. Sabab: shipped yo'lda yig'uvchini
    OPERATOR qo'lda ishga tushiradi, agent esa faqat papkani kuzatadi; «avtomatik» so'zi esa
    odamning ishini agentga yozib qo'yardi. ⚠️ Darvoza yo'l NOMA'LUM (`route is None`)
    bo'lganda HAM ishlaydi (fail-closed) — faqat ANIQ `batch_execute` dan o'tadi.
    Shuning yonida ALOHIDA bo'lim (`_route_section`) uchta savolga ANIQ javob beradi: qaysi
    yo'l · operator aralashuvi bo'ldimi · `batch_execute` NEGA ishlatilmadi.
  · TARMOQ YO'Q, 1C GA ULANISH YO'Q, TASHQI KUTUBXONA YO'Q.

⚠️ NEGA BU MODUL `collector_bridge` DAN IKKITA BELGI OLADI (va nusxa KO'CHIRMAYDI):
   `batch_execute` ning sabab yozuvini TOPISH uchun uning `scope` i va xato KODI kerak, va
   ularning ikkinchi nusxasi bir kun birinchisidan ajralib ketardi — shunda hisobot sababni
   TOPA olmay, «sabab qayd etilmagan» deb YOLG'ON nuqson e'lon qilardi. Aylanma import YO'Q:
   `collector_bridge` bu moduldan hech nima import qilmaydi (`states`/`status`/yadro).

⚠️ HISOBOT YIQILGAN YURISH UCHUN HAM QURILADI: `build_report` har qanday holatni qabul
   qiladi va yiqilish ma'nosini (`states.failure_meaning`) matnga chiqaradi. Quvurning o'zi
   hisobotni faqat `REPORT` holatida yozadi, lekin UI qatlami yiqilishni ham shu modul bilan
   ko'rsatishi mumkin — ikkinchi «hisobot yozuvchi» paydo bo'lmasligi uchun.

⚠️ PROZADA «KREDENSIAL» SO'ZI ATAYLAB TANLANGAN: `redact.VALUE_PATTERNS` sir yorliqlarini
   (to'rt tilda) QIYMATI bilan tutadi, ya'ni hisobotning O'Z ogohlantirish matni shu
   darvozaga tushib, har bir hisobotni bloklab qo'yishi mumkin edi. Bu YOLG'ON IJOBIY
   bo'lardi — shu bois matn darvozani chetlab o'tmaydi, balki uning so'zlarini ISHLATMAYDI.
"""
from __future__ import annotations

import re

from . import AGENT_NAME, AI_CANDIDATES_FILE, ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER
from . import collector_bridge as bridge
from . import states as st
from .status import AgentStatus
from ..discovery_1c import redact as redaction
from ..discovery_1c.runtime_bundle import OVERALL_SUCCESS, VERIFIED_WORD_RE, Report

#: Hisobot fayli nomi shartnomada (`__init__.REPORT_FILE`) turadi; bu modul faqat MATN beradi.
REPORT_TITLE = "BinOS 1C Discovery — HISOBOT (TAXMINLAR)"

#: ⚠️ Bo'sh joy belgisi: hisobotda «yo'q» va «qayd etilmagan» FARQ QILADI. Birinchisi
#: «qaradim va topmadim», ikkinchisi «bu maydon to'ldirilmagan». Ikkisini bitta so'zga
#: qo'shib yuborish aynan `UNKNOWN` ni `NOT_FOUND` ga aylantirish bo'lardi.
NONE_FOUND = "yo'q"
NOT_RECORDED = "qayd etilmagan"

#: ⚠️⚠️ TAQIQLANGAN TASDIQ SO'ZINING O'RNI. Yadro agent chiqaradigan HAR QANDAY matnda
#: tasdiq so'zining O'ZINI taqiqlaydi (`runtime_bundle.VERIFIED_WORD_RE`, so'z chegarasi
#: bilan — `0.1.0-UNVERIFIED` halol versiya va u o'tadi). Sabab: so'zning o'zi artefaktda
#: turmasa, hech bir artefakt tasdiq DA'VOSINI olib yura olmaydi — nasrda ham, mashina
#: o'qiydigan maydonda ham.
#: ⚠️ ALMASHTIRISH JIM EMAS: `_header` da buni OCHIQ aytadigan satr bor. Sabab: hisobotga
#: tashqi matn ham tushadi (tahlilchining izohlari AYNI shu so'zni ishlatadi — «bu daraja
#: yo'q» deb aytish uchun), va uni JIMGINA tahrir qilish analitikning so'zini o'zgartirish
#: bo'lardi. Mazmun saqlanadi, so'z esa chiqishga yetib bormaydi.
FORBIDDEN_WORD_LABEL = "«TAQIQLANGAN TASDIQ DARAJASI»"

#: Hisobotning boshidagi OGOHLANTIRISH. ⚠️ Har bir band MAJBURIY va olib tashlanmaydi; ro'yxat
#: testda qulflangan (`test_agent_pipeline`). Bandlar «nima emas» ni aytadi, chunki operator
#: eng avval shuni bilishi kerak.
HEADER_WARNINGS: tuple[str, ...] = (
    "Bu hisobot TAXMINLAR ro'yxati. Hech bir qatori TASDIQLANMAGAN va ko'chirishga ruxsat "
    "bermaydi.",
    f"Tasdiqlangan daraja ({FORBIDDEN_WORD_LABEL} — yadro taqiqlagan so'z) bu kanalda "
    f"UMUMAN YO'Q va bo'lishi ham mumkin emas. Eng yuqori avtomat daraja — `CANDIDATE`.",
    "`HUMAN_CONFIRMED` faqat OPERATORNING ALOHIDA tasdiq hujjatidan keladi — bu hisobotdan "
    "ham, tahlilchining ishonchidan ham EMAS.",
    "Tahlil DETERMINISTIK va LOKAL: tarmoq chaqiruvi YO'Q, cloud AI YO'Q, do'konning "
    "ma'lumoti hech qayerga yuborilmadi.",
    "Yig'uvchi `.epf` birorta HAQIQIY 1C o'rnatmasida SINALMAGAN: integratsiya yo'llari "
    "`RUNTIME-UNKNOWN` deb belgilangan.",
    "Agent FAQAT O'QIDI: yozish, o'tkazish, o'chirish, hujjat yaratish va o'zboshimcha kod "
    "bajarish yo'li bu quvurda umuman mavjud emas.",
)

#: ⚠️ `watch_folder` yo'li uchun QO'SHIMCHA ogohlantirish: bu yo'lda `.epf` ni operator O'Z
#: 1C sessiyasida QO'LDA ochgan, ya'ni AYNI SHU YURISH yig'uvchining birinchi HAQIQIY sinovi.
#: Buni aytmaslik — «sinalgan» degan jim da'vo bo'lardi.
WATCH_FOLDER_WARNING = (
    "Bu yurish `watch_folder` yo'li bilan ketdi: yig'uvchini operator O'Z 1C sessiyasida "
    "QO'LDA ochdi. Demak AYNI SHU YURISH yig'uvchining BIRINCHI HAQIQIY sinovi — undan "
    "oldin u hech qachon haqiqiy 1C da bajarilmagan."
)

#: ⚠️⚠️ YO'L HAQQONIYLIGI DARVOZASI (brief §7). Hisobot «avtomatik 1C razvedkasi
#:    bajarildi» ma'nosini beradigan IBORANI chiqara OLMAYDI: topilsa `ReportError` va HECH
#:    NARSA qaytmaydi. Bu TESTDAN ham kuchli darvoza — test yurgizilmagan yig'mada ham
#:    ishlaydi. ⚠️ Yo'l YOZILMAGAN hisobot ham darvozadan o'tadi (fail-closed).
#: ⚠️ NAQSHLAR TASDIQ SHAKLIDA: «bajarildi» tutiladi, «bajarilMADI» tutilmaydi. Shu bois
#:    hisobotning O'Z inkor satrlari darvozani yolg'on ijobiy bilan bloklamaydi — ular
#:    ATAYLAB inkor fe'li bilan yozilgan.
#: ⚠️ NEGA NAQSH, RO'YXAT EMAS: bu matn hisobotga TASHQI manbadan ham tushadi (ko'prikning
#:    izohlari, xato tafsilotlari) va uchta joyni alohida qo'riqlash bitta yo'lni bir kun
#:    o'tkazib yuborishdan boshqa narsa bermasdi.
AUTOMATIC_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("avtomatik_razvedka_bajarildi",
     re.compile(r"(?i)avtomatik\s+(?:\S+\s+){0,2}?razvedka(?:si|sini)?\s+bajarildi")),
    ("avtomatik_bajarildi", re.compile(r"(?i)avtomatik\s+(?:ravishda\s+)?bajarildi")),
    ("agent_1c_ni_ishga_tushirdi",
     re.compile(r"(?i)agent\s+1C\s+ni\s+(?:o'zi\s+)?ishga\s+tushirdi")),
    ("paketli_yol_bilan_olindi", re.compile(r"(?i)paketli\s+yo'l\s+bilan\s+olindi")),
    ("batch_execute_bajarildi",
     re.compile(r"(?i)`?batch_execute`?\s+(?:yo'li\s+)?(?:bilan\s+)?bajarildi")),
    ("bitta_bosishda_avtomatik", re.compile(r"(?i)(?:bitta|bir)\s+bosishda\s+avtomatik")),
)

#: ⚠️ `watch_folder` yo'lining ANIQ, INKOR shaklidagi e'loni — hisobotning o'zagi (brief §7).
NO_AUTOMATION_LINE = (
    "Bu yurishda agent 1C ni ISHGA TUSHIRMADI va birorta buyruq BAJARMADI: yig'uvchini "
    "OPERATOR o'z 1C sessiyasida qo'lda ochdi, agent esa faqat chiqish papkasini kuzatdi. "
    "Ya'ni bu yurish AVTOMATIK razvedka EMAS."
)

#: Operator aralashuvi qatorining IKKI qiymati — uchinchisi YO'Q (yo'l yozilmagan holat
#: alohida aytiladi). ⚠️ «Bo'ldi» va «bo'lmadi» ni bitta so'zga qo'shish aynan shu ajrimni
#: yo'q qilardi.
INTERVENTION_BY_ROUTE: dict[str, str] = {
    ROUTE_WATCH_FOLDER: (
        "BO'LDI — yig'uvchini OPERATOR qo'lda ishga tushirdi. Agentning ishi KUZATISH bilan "
        "cheklandi."
    ),
    ROUTE_BATCH_EXECUTE: (
        "Agent paketli chaqiruvni O'ZI qurib yurgizishga URINDI (`batch_execute`). Natijasi "
        "quyidagi xatolar va izohlar bo'limlarida; «urindi» «muvaffaqiyat» DEGANI EMAS."
    ),
}

#: Validator chiqish kodlarining MA'NOSI (`discovery_1c.cli` shartnomasi).
#: ⚠️ `1` va `2` ni ajratish SHARTNOMANING O'ZAGI: «fayllarga ishonib bo'lmaydi» va «fayllar
#: butun, lekin yurishning O'ZI to'liq tugamagan» IKKI XIL vaziyat, operatorning harakati ham
#: boshqa. Shu bois hisobot kodni raqam bilan ham, so'z bilan ham yozadi.
EXIT_MEANING: dict[str, str] = {
    "0": "paket TO'G'RI va yurish TO'LIQ (`overall=SUCCESS`) — quvur davom etdi",
    "1": "paket NOTO'G'RI: fayllarga ISHONIB BO'LMAYDI. Tahlil QILINMADI — noto'g'ri "
         "paketdan chiqarilgan xulosa noto'g'ri bo'ladi",
    "2": "paket to'g'ri, LEKIN yurishning O'ZI TO'LIQ EMAS (`overall != SUCCESS`). Bu "
         "TO'XTASH sharti: quvur davom ETMADI va buni JIMGINA o'tkazib yubormadi",
}


class ReportError(ValueError):
    """Hisobotni qurish yoki yozish mumkin emas (shakl buzuq yoki matnda sir shubhasi)."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ReportError(msg)


def _ball(value) -> str:
    """O'lchovning DETERMINISTIK yozilishi (uch kasr xona).

    ⚠️ Ball SANOQ EMAS, O'LCHOV: boshidagi nol unda ma'no tashimaydi. Shu bois «sanoqlar
       matn» qoidasi unga tegishli emas, lekin YOZILISHI qat'iy — modelning uzun kasri bayt
       darajasida farqlanadigan hisobot berardi."""
    if value is None:
        return NOT_RECORDED
    _need(isinstance(value, (int, float)) and not isinstance(value, bool),
          f"ball son bo'lishi kerak, kelgani {value!r}")
    return f"{float(value):.3f}"


def _bullets(rows, *, bo_sh: str, prefix: str = "  - ") -> list[str]:
    """Ro'yxat — bo'sh bo'lsa ham OCHIQ aytiladi (jim tashlab ketish YO'Q)."""
    rows = list(rows)
    if not rows:
        return [f"{prefix}{bo_sh}"]
    return [f"{prefix}{s}" for s in rows]


def _evidence_lines(rows) -> list[str]:
    """Dalil satrlari: `kind` (`weight`) — tafsilot. Tartib kirishdan (tartiblangan) keladi."""
    out = []
    for e in rows:
        _need(isinstance(e, dict), "dalil lug'at bo'lishi kerak")
        out.append(f"`{e.get('kind')}` ({e.get('weight')}) — {e.get('detail')}")
    return out


def _probe_lines(rows) -> list[str]:
    """Tavsiya etilgan zondlar. ⚠️ TAVSIYA, BAJARILGAN AMAL EMAS: zond faqat operator
    tasdig'idan keyin va `probe.validate_probe` dan o'tgandan so'ng bajariladi."""
    out = []
    for p in rows:
        _need(isinstance(p, dict), "zond lug'at bo'lishi kerak")
        kutilgan = ", ".join(p.get("expected_evidence") or []) or NOT_RECORDED
        out.append(f"`{p.get('probe_type')}` -> `{p.get('target_object')}` — "
                   f"{p.get('reason')} (kutilgan dalil: {kutilgan})")
    return out


def _run_summary(status: AgentStatus, *, validation, exit_code, revalidation,
                 revalidation_exit_code, unresolved_references) -> list[str]:
    """Yurish xulosasi: rejim, yo'l, holat, artefaktlar, xatolar.

    ⚠️ HOLAT QACHON O'LCHANGANI OCHIQ YOZILADI. Quvur hisobotni `REPORT` holatida yozadi va
       keyin `COMPLETE` ga o'tadi, ya'ni bu matndagi holat YAKUNIY holat BO'LMASLIGI mumkin.
       Buni aytmaslik hisobotni yurish yozuvi (`agent_status.json`) bilan zid qilib qo'yardi
       va «qaysi biri haqiqat» degan savol javobsiz qolardi."""
    yakuniy = st.is_terminal(status.state)
    satrlar = [
        "## Yurish xulosasi",
        "",
        f"- **Yurish (`run_id`):** `{status.run_id}`",
        f"- **Agent:** `{status.agent_name}` `{status.agent_version}`",
        f"- **Boshlandi:** `{status.started_at}`",
        f"- **Tugadi:** " + (f"`{status.finished_at}`" if status.finished_at else NOT_RECORDED),
        f"- **Rejim:** `{status.mode}`",
        f"- **Yo'l:** " + (f"`{status.route}`" if status.route else
                           f"{NOT_RECORDED} (yo'l tanlovi agent ichida bo'ladi)"),
        f"- **Faqat o'qish (`read_only`):** `{status.read_only}` — boshqa qiymat MUMKIN EMAS",
        # ⚠️⚠️ HUKM AYNAN SHU YERDA KO'RINADI: «1C yo'q» (`absent`) va «1C holatini aniqlab
        #    bo'lmadi» (`unknown`) IKKI XIL javob, va hisobotni o'qigan odam qaysi biri
        #    ekanini `environment.json` ni ochmasdan bilishi kerak. Qiymat yurish yozuvidan
        #    keladi (u ham `detector` dan) — hisobot o'zi hukm CHIQARMAYDI.
        f"- **1C mavjudligi hukmi (`presence_verdict`):** `{status.presence_verdict}`"
        + " — `absent` «qaradim va yo'q» (JAVOB), `unknown` «qaray olmadim» (javob YO'Q)",
        f"- **Paket papkasi:** " + (f"`{status.bundle_dir}`" if status.bundle_dir else
                                    NOT_RECORDED)
        + " (nisbiy nom; absolyut yo'l ATAYLAB yozilmaydi)",
        f"- **Holat:** `{status.state}`"
        + ("" if yakuniy else " — ⚠️ bu hisobot YOZILAYOTGAN paytdagi holat; YAKUNIY holat "
                             "`agent_status.json` da"),
    ]
    if yakuniy and st.is_failure(status.state):
        # ⚠️⚠️ MA'NO MATNI `presence_verdict` BILAN SO'RALADI: `FAILED_NO_1C` ning shartsiz
        #    matni «1C O'RNATILMAGAN … Bu JAVOB, taxmin emas» deb da'vo qilardi — holbuki
        #    hukm `unknown` bo'lishi mumkin. Shu bois hisobotning XULOSASI va
        #    `environment.json` ning hukmi BITTA manbadan keladi va zid bo'lishi mumkin emas.
        ma_no = st.failure_meaning(status.state, presence_verdict=status.presence_verdict)
        satrlar += ["", f"> ⚠️ **{status.state}** — {ma_no}"]

    satrlar += ["", "### Validator (Phase 4 `runtime_bundle`)", ""]
    satrlar += _validation_lines(validation, exit_code, sarlavha="Birinchi validatsiya")
    if revalidation is not None or revalidation_exit_code is not None:
        # ⚠️ Zond bajarilgan bo'lsa paket O'ZGARDI, demak QAYTA tekshirilgan. Ikkinchi
        #    hisobotni ko'rsatmaslik «o'zgargan paket tekshirilmagan» degan bo'shliq bo'lardi.
        satrlar += [""]
        satrlar += _validation_lines(revalidation, revalidation_exit_code,
                                     sarlavha="Qayta validatsiya (zonddan keyin)")

    satrlar += ["", "### Aniqlanmagan havolalar", ""]
    satrlar += _bullets(
        [f"`{s}`" for s in unresolved_references],
        bo_sh="yo'q (hamma havola inventarizatsiyadagi obyektga tushdi)", prefix="- ")
    satrlar += ["",
                "> ⚠️ Aniqlanmagan havola NUQSON EMAS: konfiguratsiya bo'lak-bo'lak olingan "
                "bo'lishi mumkin. Lekin u JIMGINA tashlanmaydi."]

    # ⚠️⚠️ RO'YXAT YURISH YOZUVIDAN OLINADI va bu modul uni TO'LDIRMAYDI: hisobot papkani
    #      O'ZI o'qimaydi (determinizm: fayl tizimiga murojaat YO'Q). Demak MOSLIK
    #      CHAQIRUVCHINING majburiyati — hisobot YAKUNIY ro'yxat qo'yilgandan KEYIN
    #      qurilishi SHART. Aks holda bitta papkada `discovery_report.md` bir ro'yxat,
    #      `agent_status.json` esa BOSHQA ro'yxat sanaydi va operator «qaysi biri haqiqat»
    #      savoli bilan qoladi. Aynan shu nuqson bor edi: `pipeline.step_report` quvurning
    #      O'Z uchta nomi bilan hisobot qurardi, `ui._paket` esa keyin o'n ikkita nom
    #      yozardi. Tuzatish `ui._yakunla` da: ro'yxat YAKUNLANADI, hisobot SO'NG quriladi.
    #      Ikki tomonni solishtiradigan test:
    #      `test_agent_e2e_watch_folder.test_D2_hisobot_sanagan_artefaktlar_...`.
    satrlar += ["", "### Artefaktlar", ""]
    satrlar += _bullets([f"`{n}`" for n in status.artifacts],
                        bo_sh="hali birorta artefakt yozilmagan", prefix="- ")

    satrlar += ["", "### Zondlar", ""]
    if status.probes:
        for p in status.probes:
            satrlar.append(f"- `{p.probe_type}` -> `{p.target_object}` — holat "
                           f"`{p.status}`, sabab: {p.reason} (natija: `{p.file}`)")
    else:
        satrlar.append("- bajarilgan yoki rejalashtirilgan zond YO'Q "
                       "(`METADATA_ONLY` — bu quvurning DEFAULT rejimi)")

    satrlar += ["", "### Xatolar", ""]
    if status.errors:
        for e in status.errors:
            satrlar.append(f"- `{e.code}` ({e.scope}) — {e.detail}")
    else:
        satrlar.append(f"- {NONE_FOUND}")

    satrlar += ["", "### Izohlar", ""]
    satrlar += _bullets(status.notes, bo_sh="izoh yozilmadi", prefix="- ")
    return satrlar


def _route_section(status: AgentStatus) -> list[str]:
    """YO'L HAQQONIYLIGI bo'limi (brief §7) — uchta savolga ANIQ javob.

    (1) QAYSI yo'l ishlatildi · (2) OPERATOR ARALASHUVI bo'ldimi · (3) `batch_execute`
    NEGA ishlatilmadi.

    ⚠️⚠️ NEGA ALOHIDA BO'LIM, «Yurish xulosasi» ichidagi bitta qator emas: hisobotni o'qigan
         odam «avtomatik razvedka bo'ldi» deb o'ylab qolmasligi kerak, va buni bitta qator
         ishonchli qila olmaydi. Bo'lim yurish yozuvidan O'QIYDI — hisobot o'zi hech narsa
         HISOBLAMAYDI.
    ⚠️ SABAB YOZUVDAN OLINADI, o'ylab chiqarilmaydi: `batch_execute` ga tegishli xatolar
       (`scope` i shu yo'lni ko'rsatadiganlar) AYNI holda ko'chiriladi. Birorta sabab yozilmagan
       bo'lsa — bu NUQSON va hisobot shuni OCHIQ aytadi («sabab qayd etilmagan»), jimgina
       bo'sh bo'lim QOLDIRMAYDI.
    """
    yol = status.route
    out = ["## Yo'l va operator aralashuvi", ""]
    out += [f"- **Ishlatilgan yo'l:** " + (f"`{yol}`" if yol else
                                          f"{NOT_RECORDED} — bu NUQSON: yurish yozuvi "
                                          f"qaysi yo'l bilan ketganini aytmaydi")]
    aralashuv = INTERVENTION_BY_ROUTE.get(yol or "")
    out += [f"- **Operator aralashuvi:** " + (aralashuv if aralashuv else
                                             f"{NOT_RECORDED} (yo'l yozilmagani uchun "
                                             f"aytib bo'lmaydi)")]

    sabablar = [f"`{e.code}` ({e.scope}) — {e.detail}"
                for e in status.errors if e.scope == bridge.SCOPE_BATCH]
    out += [f"- **`{ROUTE_BATCH_EXECUTE}` nega ishlatilmadi:**"]
    if yol == ROUTE_BATCH_EXECUTE and not sabablar:
        out += ["  - ishlatildi (yoki urinildi) — bu savol bu yurishga tegishli emas"]
    else:
        out += _bullets(sabablar,
                        bo_sh=("sabab QAYD ETILMAGAN — bu NUQSON: yo'l tanlovi jimgina "
                               "bo'lmasligi kerak edi"))
    if yol == ROUTE_WATCH_FOLDER:
        out += ["", f"> ⚠️ {NO_AUTOMATION_LINE}"]
    return out


def _assert_no_automatic_claim(matn: str, status: AgentStatus) -> None:
    """⚠️ FAIL-CLOSED: hisobot avtomatlashtirish DA'VOSINI olib yura olmaydi.

    ⚠️⚠️ DARVOZA `route is None` DA HAM ISHLAYDI va bu TUZATILGAN NUQSON: oldin bu
         yerda `route != watch_folder` bo'lsa ERTA qaytilardi, ya'ni yo'li YOZILMAGAN
         (`route=None`) OXIRGI hisobotda taqiqlangan ibora BARIBIR yozilib ketardi va paket
         `check_result_package` dan TOZA o'tardi. «Bilmayman» RUXSATGA aylanmaydi: yo'l
         noma'lum bo'lsa avtomatlashtirish da'vosi OQLANMAYDI. Erta qaytish ENDI faqat ANIQ
         `batch_execute` da bo'ladi — u yo'lda paketli chaqiruvni agentning O'ZI qurib
         yurgizishga urinadi, demak «avtomatik» so'zi odamning ishini agentga yozib
         qo'ymaydi. (Amalda bu yo'l hozir bajarilmaydi: repoda `.epf` konteyneri yo'q.)
    ⚠️⚠️ XATO MATNIDA IBORANING O'ZI KO'RSATILMAYDI — faqat SATR RAQAMI va NAQSH NOMI
         (tuzatish uchun shu KIFOYA). Ibora sir EMAS, lekin uni xato matniga kiritish
         darvozani O'Z-O'ZIGA QARSHI ishlatardi: matn `ui._yakunla` orqali `status.errors`
         ga tushar, ZAHIRA hisobot uni `### Xatolar` bo'limida QAYTA chiqarar va darvoza
         IKKINCHI marta urardi. Natijada analitik bitta izoh qo'shgani uchun SOG'LOM yurish
         `FAILED_INTERNAL` bo'lar, `route` yo'qolar va yetkazilgan hisobot «Ishlatilgan
         yo'l: qayd etilmagan — bu NUQSON» deb yozardi.
    ⚠️ NAQSH NOMLARI xato matniga CHIQADI va bu xavfsiz: nomlar pastki chiziq bilan
       yozilgan (`avtomatik_bajarildi`), naqshlar esa BO'SH JOY talab qiladi — ya'ni nom
       o'zi tutilmaydi. Bu tasodif emas, shart: `test_agent_e2e_watch_folder` buni qulflaydi.
    """
    if status.route == ROUTE_BATCH_EXECUTE:
        return
    topilgan: list[str] = []
    for i, satr in enumerate(matn.splitlines(), start=1):
        for nom, rx in AUTOMATIC_CLAIM_PATTERNS:
            if rx.search(satr) is not None:
                topilgan.append(f"satr {i}: {nom}")
    _need(not topilgan,
          f"hisobot yo'li `{status.route or NOT_RECORDED}` (darvoza FAQAT ANIQ "
          f"`{ROUTE_BATCH_EXECUTE}` da ochiq — `{ROUTE_WATCH_FOLDER}` da ham, yo'l "
          f"YOZILMAGANDA ham YOPIQ), lekin matnda AVTOMATLASHTIRISH da'vosining NAQSHI "
          f"topildi — yozish RAD etildi: yig'uvchini OPERATOR qo'lda ishga tushiradi va "
          f"buni hisobot o'zgartira olmaydi. Quyida FAQAT satr raqami va naqsh nomi: "
          f"topilgan iboraning O'ZI ATAYLAB ko'chirilmaydi, aks holda shu xato matni "
          f"darvozani QAYTA urardi. {sorted(set(topilgan))}")


def _validation_lines(validation, exit_code, *, sarlavha: str) -> list[str]:
    """Validator hisobotining qisqasi: chiqish kodi, `overall`, yiqilgan tekshiruvlar.

    ⚠️ Tashqi matn (`problems`) `redact.redact` dan O'TKAZILADI: validator nuqsoni ichida
       papka yo'li bo'lishi mumkin (`papka topilmadi: ...`), absolyut yo'l esa yozish
       darvozasini bloklardi. Bu YAGONA joy, bu modul tashqi matnni ataylab niqoblaydi —
       va u qiymatni YASHIRMAYDI, balki niqob bilan ALMASHTIRADI, ya'ni operator qiymat
       borligini ko'radi."""
    if validation is None:
        return [f"- **{sarlavha}:** BAJARILMADI "
                f"(«bajarilmadi» «muammo yo'q» EMAS — FAIL-CLOSED)"]
    _need(isinstance(validation, Report),
          f"{sarlavha}: `runtime_bundle.Report` kutiladi, kelgani "
          f"{type(validation).__name__}")
    kod = NOT_RECORDED if exit_code is None else f"`{exit_code}`"
    ma_no = EXIT_MEANING.get(str(exit_code), "noma'lum kod")
    yiqilgan = [c for c in validation.checks if not c.ok]
    out = [
        f"- **{sarlavha} · chiqish kodi:** {kod} — {ma_no}",
        f"- **Paketga ishonish (`ok`):** `{'true' if validation.ok else 'false'}`",
        f"- **Yurish holati (`overall`):** "
        + (f"`{validation.overall}`" if validation.overall else "NOMA'LUM")
        + ("" if validation.overall == OVERALL_SUCCESS
           else " — ⚠️ `SUCCESS` EMAS, ya'ni yurish TO'LIQ tugamagan"),
        f"- **Tekshiruvlar:** {len(validation.checks) - len(yiqilgan)} / "
        f"{len(validation.checks)} o'tdi",
    ]
    if yiqilgan:
        out.append("- **Yiqilgan tekshiruvlar:**")
        for c in yiqilgan:
            out.append(f"  - `{c.name}` — {redaction.redact(c.detail)}")
    return out


def _candidate_block(no: int, row: dict) -> list[str]:
    """Bitta nomzodning bloki: konsept · obyekt/maydon · ball · dalil · QARSHI dalil ·
    noaniqlik · talab qilinadigan tasdiq · keyingi tavsiya etilgan zond.

    ⚠️ QARSHI DALIL VA NOANIQLIK MAJBURIY KO'RSATILADI, bo'sh bo'lsa ham: faqat ijobiy
       dalilni ko'rsatadigan hisobot nomzodni tasdiqlangandek ko'rsatardi."""
    _need(isinstance(row, dict), f"nomzod[{no}] lug'at bo'lishi kerak")
    manzil = f"`{row.get('candidate_object')}`"
    if row.get("candidate_field"):
        manzil += f" · maydon `{row['candidate_field']}`"
    out = [
        f"### {no}. `{row.get('concept')}` <- {manzil}",
        "",
        f"- **Holat:** `{row.get('status')}`",
        f"- **Ball (`confidence_score`):** {_ball(row.get('confidence_score'))} — "
        f"tahlilchining O'Z bahosi, DALIL EMAS: u faqat ko'rik NAVBATINI belgilaydi",
        "- **Dalil:**",
    ]
    out += _bullets(_evidence_lines(row.get("evidence") or []),
                    bo_sh=f"{NONE_FOUND} (dalilsiz xulosa — faqat `REJECTED` da bo'ladi)")
    out += ["- **Qarshi dalil:**"]
    out += _bullets(_evidence_lines(row.get("counter_evidence") or []), bo_sh=NONE_FOUND)
    out += ["- **Noaniqlik:**"]
    out += _bullets(row.get("ambiguity") or [], bo_sh=NONE_FOUND)
    out += ["- **Talab qilinadigan tasdiq:**"]
    out += _bullets(row.get("required_confirmation") or [], bo_sh=NOT_RECORDED)
    out += ["- **Keyingi tavsiya etilgan zond:**"]
    out += _bullets(_probe_lines(row.get("recommended_next_probe") or []),
                    bo_sh="tavsiya etilmadi")
    out += ["", f"> Tushuntirish: {row.get('explanation')}"]
    return out


def _candidates_section(review) -> list[str]:
    """Nomzodlar bo'limi. ⚠️ Tahlil bo'lmasa — buni OCHIQ aytadi, bo'sh bo'lim QOLDIRMAYDI."""
    if review is None:
        return [
            "## Nomzodlar",
            "",
            "Tahlil BAJARILMADI yoki yakunlanmadi, shu bois nomzodlar ro'yxati YO'Q.",
            "",
            "> ⚠️ Bu «nomzod yo'q» degani EMAS: hech kim qaramadi. Sababini yuqoridagi "
            "«Xatolar» bo'limidan o'qing.",
        ]
    rows = list(review.get("candidates") or [])
    out = ["## Nomzodlar", "",
           f"Jami: {len(rows)} ta nomzod. Tartib `discovery_1c.review` dan keladi "
           f"(DETERMINISTIK), ya'ni ikki yurishni qatorga qator solishtirish mumkin.", ""]
    if not rows:
        out += ["Birorta nomzod chiqmadi.", "",
                "> ⚠️ Nomzod chiqmagani «konfiguratsiyada hech narsa yo'q» degani EMAS: "
                "dalilsiz gipoteza umuman yozilmaydi (`analyst` qoidasi)."]
        return out
    for i, row in enumerate(rows, start=1):
        out += _candidate_block(i, row)
        out += [""]
    return out


def _unknown_section(review) -> list[str]:
    """`UNKNOWN` konseptlar — TASHLANMAYDI, SANAB o'tiladi."""
    out = ["## `UNKNOWN` konseptlar (QARALMAGAN)", ""]
    if review is None:
        out += ["Tahlil bajarilmagani uchun HAMMA konsept qaralmagan holatda qoldi.", ""]
        return out
    rows = list(review.get("unknown_concepts") or [])
    out += [f"Jami: {len(rows)} ta konseptga birorta gipoteza TEGMADI.", ""]
    out += _bullets([f"`{c}`" for c in rows],
                    bo_sh="yo'q — har bir konseptga kamida bitta gipoteza tegdi", prefix="- ")
    out += ["",
            "> ⚠️ «Qaralmadi» va «yo'q» BIR XIL NARSA EMAS. Bu ro'yxat ATAYLAB saqlanadi: "
            "tushirib qoldirilgan konsept keyinchalik «tekshirilgan va topilmagan» deb "
            "o'qilardi."]
    return out


def _analyzer_section(review) -> list[str]:
    """Tahlilchi va uning izohlari. ⚠️ Izoh JIM QISILMAYDI: nomzodlar soni chegaraga
    qisilgani haqidagi YAGONA xabar aynan shu ro'yxatda yashaydi."""
    if review is None:
        return []
    tahlilchi = review.get("analyzer") or {}
    out = ["## Tahlilchi", "",
           f"- **Nomi:** `{tahlilchi.get('name')}`",
           f"- **Versiyasi:** `{tahlilchi.get('version')}`",
           "- **Izohlari:**"]
    out += _bullets(review.get("analyzer_notes") or [],
                   bo_sh="izoh berilmadi — bu «hech narsa qisilmadi» degani EMAS")
    ogohlar = list(review.get("warnings") or [])
    if ogohlar:
        out += ["", f"### `{AI_CANDIDATES_FILE}` artefaktining O'Z ogohlantirishlari", ""]
        out += _bullets(ogohlar, bo_sh=NONE_FOUND, prefix="- ")
    return out


def _header(status: AgentStatus) -> list[str]:
    """Sarlavha va OGOHLANTIRISH bloki — hisobotning eng boshida."""
    out = [f"# {REPORT_TITLE}", "", "## ⚠️ AVVAL O'QING", ""]
    out += [f"- {s}" for s in HEADER_WARNINGS]
    if status.route == ROUTE_WATCH_FOLDER:
        out += [f"- {WATCH_FOLDER_WARNING}"]
    out += ["",
            f"> Bu matnni `{AGENT_NAME}` yozdi va u yurish yozuvidan "
            f"(`agent_status.json`) hamda ko'rik artefaktidan (`{AI_CANDIDATES_FILE}`) "
            f"YIG'ILGAN: bir bayt yangi da'vo qo'shilmagan.",
            "",
            f"> ⚠️ {FORBIDDEN_WORD_LABEL} deb yozilgan joy — tasdiq so'zining O'RNI. "
            f"O'sha so'z agent chiqaradigan HAR QANDAY matnda taqiqlangan, shu bois u "
            f"ALMASHTIRILDI (jimgina emas — mana shu satr buni aytadi). Mazmun "
            f"o'zgarmagan: gap aynan shu darajaning YO'QLIGI haqida.", ""]
    return out


def build_report(*, status: AgentStatus, review=None, validation=None, exit_code=None,
                 revalidation=None, revalidation_exit_code=None,
                 unresolved_references=()) -> str:
    """`discovery_report.md` matnini quradi. Xato — `ReportError`.

    `status`  — yurish yozuvi (MAJBURIY). Undan rejim, yo'l, holat, artefaktlar, zondlar,
                xatolar va izohlar olinadi.
    `review`  — `discovery_1c.review.build_review` qurgan lug'at; `None` = tahlil bo'lmadi
                (va bu hisobotda OCHIQ aytiladi, bo'sh bo'lim qolmaydi).
    `validation` / `exit_code` — Phase 4 validatorining hisoboti va `0`/`1`/`2` kodi.
    `revalidation` / `revalidation_exit_code` — zonddan keyingi QAYTA validatsiya (bo'lsa).
    `unresolved_references` — inventarizatsiyadagi aniqlanmagan havolalar.

    ⚠️ Qaytarishdan OLDIN matn `redact.scan` darvozasidan o'tadi: shubhali qiymat topilsa
       ISTISNO va HECH NARSA qaytmaydi. Nuqson matnida qiymatning O'ZI ko'rsatilmaydi — faqat
       satr raqami, naqsh nomi va tavsifi (`redact.Finding.__str__` qoidasi). ⚠️ AYNI QOIDA
       avtomatlashtirish darvozasiga ham tegishli: u ham topilgan IBORANI ko'chirmaydi — aks
       holda uning O'Z xato matni darvozani qayta urardi."""
    _need(isinstance(status, AgentStatus),
          f"build_report `AgentStatus` kutadi, kelgani {type(status).__name__}")
    _need(review is None or isinstance(review, dict),
          f"review lug'at yoki `None` bo'lishi kerak, kelgani {type(review).__name__}")
    _need(isinstance(unresolved_references, (list, tuple)),
          "unresolved_references ro'yxat bo'lishi kerak")

    satrlar: list[str] = []
    satrlar += _header(status)
    # ⚠️ YO'L BO'LIMI XULOSADAN OLDIN: operator eng avval «bu avtomatik bo'ldimi» degan
    #    savolga javob olishi kerak, chunki qolgan hamma satr shu javob ostida o'qiladi.
    satrlar += _route_section(status)
    satrlar += [""]
    satrlar += _run_summary(status, validation=validation, exit_code=exit_code,
                           revalidation=revalidation,
                           revalidation_exit_code=revalidation_exit_code,
                           unresolved_references=unresolved_references)
    satrlar += [""]
    satrlar += _candidates_section(review)
    satrlar += [""]
    satrlar += _unknown_section(review)
    bo_lim = _analyzer_section(review)
    if bo_lim:
        satrlar += [""] + bo_lim
    satrlar += ["", "## Keyingi qadam", "",
                "1. Yuqoridagi nomzodlarni DALILI bilan birga o'qing — ball bo'yicha "
                "navbatlang, lekin ballga ISHONMANG.",
                "2. Tasdiqlashga arzigulik qatorni OPERATOR sifatida alohida tasdiq "
                "hujjatida qayd eting (`binos-1c-confirmations-v1`).",
                "3. Zond kerak bo'lsa, uni ALOHIDA tasdiqlang: tasdiqsiz zond bajarilmaydi "
                "va quvur xavfsizlik darvozasida to'xtaydi.",
                "4. `UNKNOWN` konseptlarni ro'yxatdan O'CHIRMANG — ular keyingi yurishning "
                "ishi.", ""]

    # ⚠️ TARTIB: avval taqiqlangan tasdiq so'zi almashtiriladi, keyin sir darvozasi. Ikkisi
    #    MUSTAQIL: biri tasdiq DA'VOSINI, ikkinchisi SIRNI to'sadi.
    matn = _replace_forbidden_word("\n".join(satrlar))
    # ⚠️ UCHINCHI, MUSTAQIL DARVOZA: tasdiq DA'VOSI, SIR va AVTOMATLASHTIRISH DA'VOSI — uch
    #    xil yolg'on va uchtasi alohida to'siladi.
    _assert_no_automatic_claim(matn, status)
    _assert_no_secrets(matn)
    return matn


def _replace_forbidden_word(matn: str) -> str:
    """Tasdiq so'zini O'RNI bilan almashtiradi va natijani FAIL-CLOSED tekshiradi.

    ⚠️ NEGA ALMASHTIRISH, RAD ETISH EMAS: so'z hisobotga TASHQI matndan tushadi —
       tahlilchining izohi aynan shu so'z bilan «bu daraja yo'q» deb aytadi
       (`analyst.heuristics` ning izohlari). Rad etish butun hisobotni bloklardi, so'zni
       JIMGINA o'chirish esa analitikning gapini buzardi. Shu bois so'z O'RNI bilan
       almashtiriladi, almashtirish esa hisobotning BOSHIDA ochiq aytiladi.
    ⚠️ NEGA BUTUN MATNGA: so'z hisobotga kamida uch yo'ldan tushadi (tahlilchi izohi,
       artefakt ogohlantirishlari, xato tafsiloti), va uchta joyni alohida qo'riqlash bitta
       yo'lni bir kun o'tkazib yuborishdan boshqa narsa bermasdi.
    ⚠️ Oxirgi tekshiruv — FAIL-CLOSED: almashtirishdan keyin so'z QOLGAN bo'lsa, bu nuqson
       va hisobot YOZILMAYDI."""
    tozalangan = VERIFIED_WORD_RE.sub(FORBIDDEN_WORD_LABEL, matn)
    _need(VERIFIED_WORD_RE.search(tozalangan) is None,
          "hisobotda taqiqlangan tasdiq so'zi QOLDI — yozish RAD etildi: agent hech narsani "
          "tasdiqlamaydi va bu so'z uning birorta artefaktida tura olmaydi")
    return tozalangan


def _assert_no_secrets(matn: str) -> None:
    """Chiqishda sir bo'lmasligi — FAIL-CLOSED darvoza (SATRMA-SATR).

    ⚠️ NEGA SATRMA-SATR, butun matnga emas: `redact.scan` bitta topilmani butun matn uchun
       bitta yo'l (`""`) bilan beradi, ya'ni operator nuqsonning QAYERDA ekanini bilmasdi.
       Satr raqami esa qiymatning O'ZINI oshkor qilmaydi.
    ⚠️ Niqoblab o'tkazib yuborish YO'Q: niqob yozuvni jimgina o'zgartirardi va operator
       qaysi qiymat yo'qolganini bilmasdi (`status.assert_no_secrets` bilan AYNI qoida)."""
    topilgan: list[str] = []
    for i, satr in enumerate(matn.splitlines(), start=1):
        for f in redaction.scan(satr):
            topilgan.append(f"satr {i}: {f.detail} ({f.pattern})")
    _need(not topilgan,
          "hisobotda shubhali qiymat(lar) topildi, yozish RAD etildi — "
          f"{sorted(set(topilgan))}")
