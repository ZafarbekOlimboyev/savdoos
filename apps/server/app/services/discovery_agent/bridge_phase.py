# -*- coding: utf-8 -*-
"""KO'PRIK FAZALARI — operatorga KO'RINADIGAN sub-holatlar va nosozlik UCHLIGI.

Bu modul YANGI HOLAT MASHINASI EMAS. Mavjud mashina (`states.py`) 12 normal + 11 yiqilish
holati bilan 2776 test tomonidan isbotlangan va u TEGILMAYDI. Bu yerdagi 12 nom — AYNI
quvurning operator KO'ZI BILAN ko'rinadigan qatlami (faza), va har faza MAVJUD bir holatga
1:1 bog'lanadi (`PHASE_TO_STATE`).

⚠️⚠️ NEGA IKKINCHI MASHINA QURILMAYDI: brief «ikkinchi razvedka dvigateli qurilmaydi /
     semantik dublikat bo'lmaydi» deydi. Parallel holat mashinasi aynan shu dublikat
     bo'lardi: ikki jadval bir kun bir-biridan ajralib ketadi va «qaysi holat haqiqat»
     degan savol tug'iladi — Phase 4 ni yiqitgan naqshning o'zi. Shu bois faza qatlami
     HOLATNI ALMASHTIRMAYDI, uni TARJIMA qiladi:
       · mashina o'qiydigan haqiqat — `states.py` dagi holat va `agent_status.json`;
       · odam o'qiydigan haqiqat — SHU YERDAGI faza nomi va `PHASE_TEXT` matni.
⚠️ Bu modul 1C ga ULANMAYDI, fayl o'qimaydi, vaqtni o'zi olmaydi, tarmoqqa chiqmaydi va
   jarayon ishga tushirmaydi. U sof LUG'AT — shu bois 1C siz to'liq isbotlanadi.

⚠️⚠️ «SPINNER-ONLY» FAZA BO'LMAYDI: har fazada operator uchun BO'SH BO'LMAGAN matn bor
     (`PHASE_TEXT`). Sabab: aylanayotgan belgi operatorga nima bo'layotganini aytmaydi va
     u qo'ng'iroq qilishga majbur bo'ladi — xuddi sababsiz xato xabari kabi.

⚠️⚠️ `.epf` IKKILIK FAYLI QURILGAN DEB AYTILMAYDI. Yig'uvchining MANBA matni tayyor
     (`EPF_SOURCE_READY`), ikkilik `.epf` ni esa 1C konfiguratorida OPERATOR yig'adi — bu
     mashinada 1C umuman o'rnatilmagan, demak binarni «qurildi» deb yozish ISBOTLANMAGAN
     da'vo bo'lardi.

⚠️⚠️ AVTOMATIK ISHGA TUSHIRISH DEKLARATSIYA: `LAUNCHING_1C` fazasi 1C ni agentning O'ZI
     ochishini TA'RIFLAYDI, lekin bu yo'l haqiqiy 1C da HECH QACHON sinalmagan va shu bois
     `AUTOMATIC_LAUNCH_VERIFICATION` bilan belgilanadi. COM avtomatizatsiyasi QO'SHILMAYDI,
     o'ylab chiqarilgan buyruq satri parametri ham QO'SHILMAYDI.

⚠️ BEKOR QILISH KOOPERATIV: agent kutishni TO'XTATADI, 1C jarayonini O'LDIRMAYDI. Shu bois
   `OPERATOR_CANCELLED` ning keyingi qadami «1C ni o'zingiz yopasiz» deydi va hech qanday
   jarayon daraxtini tugatish YO'LI bu yerda e'lon QILINMAYDI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import states as st

# ══════════════════════════════════════════════════════════════════════════════════════════
# FAZALAR (12) — nomlari ARXITEKTOR BELGILAGAN, o'z-o'zidan «yaxshilanmaydi»
# ══════════════════════════════════════════════════════════════════════════════════════════
DETECTING_1C = "DETECTING_1C"
NO_1C = "NO_1C"
DISCOVERING_INFOBASES = "DISCOVERING_INFOBASES"
SELECT_TARGET = "SELECT_TARGET"
PREPARING_COLLECTOR = "PREPARING_COLLECTOR"
LAUNCHING_1C = "LAUNCHING_1C"
WAITING_FOR_COLLECTOR = "WAITING_FOR_COLLECTOR"
COLLECTOR_COMPLETE = "COLLECTOR_COMPLETE"
COLLECTOR_FAILED = "COLLECTOR_FAILED"
INGESTING = "INGESTING"
ANALYZING = "ANALYZING"
COMPLETE = "COMPLETE"

#: Fazalar — OPERATOR KO'RADIGAN TARTIBDA (alfavit bo'yicha emas: tartib ekranda ko'rinadi).
BRIDGE_PHASES: tuple[str, ...] = (
    DETECTING_1C, NO_1C, DISCOVERING_INFOBASES, SELECT_TARGET, PREPARING_COLLECTOR,
    LAUNCHING_1C, WAITING_FOR_COLLECTOR, COLLECTOR_COMPLETE, COLLECTOR_FAILED, INGESTING,
    ANALYZING, COMPLETE,
)

#: Yig'uvchi manbasining holati. ⚠️ NOMI AYNAN SHU: `.epf` IKKILIK fayli qurilgan deb
#: ATALMAYDI — manba matni tayyor, binarni operator 1C konfiguratorida yig'adi.
EPF_SOURCE_READY = "EPF_SOURCE_READY"

#: Avtomatik ishga tushirish yo'lining isbot holati. ⚠️ Bu MATN emas, BELGI: yo'l
#: deklaratsiya sifatida turadi va «ishlaydi» deb DA'VO QILINMAYDI.
AUTOMATIC_LAUNCH_VERIFICATION = "UNVERIFIED_ON_REAL_1C"


class BridgePhaseError(ValueError):
    """Noma'lum faza nomi yoki noma'lum nosozlik kodi (fail-closed)."""


# ══════════════════════════════════════════════════════════════════════════════════════════
# FAZA -> HOLAT: TO'LIQ va YAGONA moslik
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ HAR FAZA AYNAN BIR HOLATGA. Ko'p-bittaga moslik RUXSAT ETILGAN (uchta faza
#:    `METADATA_DISCOVERY` ga tushadi), teskarisi — YO'Q: bitta faza ikki holatga tushsa,
#:    `agent_status.json` da qaysi holat yozilishini KOD hal qilardi va hisobot bilan
#:    hujjat ajralib ketardi.
#: ⚠️ Moslik DIAPAZONI `states.STATES` dan CHIQMAYDI va YANGI holat QO'SHILMAYDI
#:    (`FAILURE_STATES` 11 ta bo'lib qoladi) — bu import paytida ham, test bilan ham
#:    qulflangan.
PHASE_TO_STATE: dict[str, str] = {
    # Muhit skaneri: reestr, fayl tizimi, PATH o'qiladi.
    DETECTING_1C: st.ENVIRONMENT_SCAN,
    # ⚠️ «Qaradim va YO'Q» — bu JAVOB, taxmin emas. `unknown` («qaray olmadim») ajrimi
    #    holat nomida EMAS, `agent_status.presence_verdict` da yashaydi (parallel lug'at
    #    yasash taqiqlangan) — shu bois bu faza ham AYNI holatga tushadi.
    NO_1C: st.FAILED_NO_1C,
    # ⚠️ IKKI FAZA, BIR HOLAT: ro'yxatni O'QISH (agent ishlaydi) va TANLASHNI KUTISH
    #    (operator ishlaydi) operator uchun butunlay boshqa narsa, mashina uchun esa ikkisi
    #    ham nishon tanlash bosqichi. Ajrim FAZADA, holat esa BITTA bo'lib qoladi.
    DISCOVERING_INFOBASES: st.TARGET_SELECTION,
    SELECT_TARGET: st.TARGET_SELECTION,
    # ⚠️ Tayyorlash = faqat-o'qish invariantlari tekshiriladi, yurish papkasi va so'rov
    #    hujjati tayyorlanadi. Shu bois `SAFETY_CHECK`: darvoza buzilsa quvur TO'XTAYDI.
    PREPARING_COLLECTOR: st.SAFETY_CHECK,
    # ⚠️ UCH FAZA, BIR HOLAT: 1C ni ochish, natijani kutish va natijaning PAYDO BO'LISHI —
    #    operator uchun uchta boshqa ekran, mashina uchun esa bittasi: metadata yig'ish
    #    bosqichi hali tugamagan (tekshiruv `INGESTING` da boshlanadi).
    LAUNCHING_1C: st.METADATA_DISCOVERY,
    WAITING_FOR_COLLECTOR: st.METADATA_DISCOVERY,
    COLLECTOR_COMPLETE: st.METADATA_DISCOVERY,
    # ⚠️ «1C BOR, lekin javob YO'Q» — `FAILED_NO_1C` dan ATAYLAB ajratilgan: birinchisida
    #    1C o'rnatiladi, bu yerda esa kuzatilgan papka yo'li bilan davom etiladi.
    COLLECTOR_FAILED: st.FAILED_COLLECTOR_UNAVAILABLE,
    # ⚠️ Paketni O'QISH va TEKSHIRISH — bu Phase 4 validatori, ya'ni `VALIDATION`.
    INGESTING: st.VALIDATION,
    # ⚠️ `ANALYZING` grafni qurishni HAM qamraydi (`GRAPH_BUILD` operator uchun alohida
    #    ekran EMAS: u bir necha soniya va u haqda aytadigan qarori yo'q). Moslik esa
    #    bittaga: tahlil bosqichining nomi `ANALYSIS`.
    ANALYZING: st.ANALYSIS,
    # ⚠️ `COMPLETE` — hisobot YOZILGANDAN keyin. `OPTIONAL_APPROVED_PROBES`, `REVALIDATE`
    #    va `REPORT` holatlariga ko'prik fazasi QO'YILMAYDI: ko'prik 1C bilan ALMASHUVNI
    #    ta'riflaydi, bu uch holat esa 1C siz, agentning ichida kechadi. Diapazon to'liq
    #    bo'lishi SHART EMAS; TO'LIQLIK talabi FAZA tomonida (har faza holatga ega).
    COMPLETE: st.COMPLETE,
}

#: Yakun bilan tugaydigan fazalar (ularning holati `states.TERMINAL` ichida).
TERMINAL_PHASES: frozenset[str] = frozenset(
    p for p, s in PHASE_TO_STATE.items() if s in st.TERMINAL
)

#: Nosozlik bilan tugaydigan fazalar.
FAILURE_PHASES: frozenset[str] = frozenset(
    p for p, s in PHASE_TO_STATE.items() if s in st.FAILURE_STATES
)

# ══════════════════════════════════════════════════════════════════════════════════════════
# OPERATOR MATNI — har faza uchun BO'SH BO'LMAGAN matn
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Matnlarda ICHKI ATAMA YO'Q: «holat mashinasi», «validator», «DTO», «bir martalik
#:    qiymat» kabi so'zlar operatorga hech narsa aytmaydi. Fayl nomlari (`bridge_done.json`)
#:    ham bu matnlarga TUSHMAYDI — ular nosozlik UCHLIGIDA, ya'ni odam rostdan ham papkaga
#:    qaraydigan joyda ko'rsatiladi.
#: ⚠️ Matnlar `agent_status.notes` ga tushishi mumkin, demak ularda SIR BO'LMAYDI: na yo'l,
#:    na misol kirish ma'lumoti, na `kalit: qiymat` shaklidagi namuna (test `redact.scan`
#:    bilan qulflaydi).
PHASE_TEXT: dict[str, str] = {
    DETECTING_1C: (
        "Kompyuterda 1C:Enterprise bor-yo'qligi tekshirilyapti. Hech narsa o'zgartirilmaydi."
    ),
    NO_1C: (
        "Bu kompyuterda 1C:Enterprise topilmadi, shu bois razvedka boshlanmadi. Hech narsa "
        "o'zgartirilmadi."
    ),
    DISCOVERING_INFOBASES: (
        "1C ro'yxatidagi ma'lumot bazalari o'qilyapti. Bazalarning o'ziga TEGILMAYDI — "
        "faqat ro'yxat o'qiladi."
    ),
    SELECT_TARGET: (
        "Qaysi ma'lumot bazasi tekshirilishini TANLANG. Agent o'zi tanlamaydi: bir nechta "
        "baza mos kelsa ham qarorni siz berasiz."
    ),
    PREPARING_COLLECTOR: (
        "Yig'uvchi va uning natijasi uchun bo'sh papka tayyorlanyapti. Yig'uvchining o'zi "
        "faqat O'QIYDI: 1C da hech narsa yozilmaydi, o'zgartirilmaydi va o'chirilmaydi."
    ),
    LAUNCHING_1C: (
        "1C ochilyapti. Kirish ma'lumoti so'ralsa, uni 1C NING O'Z oynasi so'raydi — agent "
        "uni ko'rmaydi va hech qayerga yozmaydi."
    ),
    WAITING_FOR_COLLECTOR: (
        "Yig'uvchi 1C ichida ishlayapti, natija kutilyapti. Katta bazada bu bir necha "
        "daqiqa davom etadi. Bekor qilsangiz agent kutishni to'xtatadi, 1C ni esa o'zingiz "
        "yopasiz — agent birorta jarayonni majburan tugatmaydi."
    ),
    COLLECTOR_COMPLETE: (
        "Yig'uvchi natijani qoldirdi. Natija HALI tekshirilmagan: to'liqligi keyingi "
        "qadamda tekshiriladi."
    ),
    COLLECTOR_FAILED: (
        "1C topildi va baza tanlandi, lekin yig'uvchidan yaroqli natija kelmadi. Bu "
        "«ma'lumot yo'q» degani EMAS — javobning O'ZI yo'q."
    ),
    INGESTING: (
        "Natija o'qilyapti va to'liqligi tekshirilyapti. Tekshiruvdan o'tmagan natija "
        "bo'yicha xulosa CHIQARILMAYDI."
    ),
    ANALYZING: (
        "Ma'lumotlar bog'lanyapti va taqqoslanyapti. Bu qadam 1C ga umuman murojaat "
        "qilmaydi — faqat qo'lga olingan natija ustida ishlanadi."
    ),
    COMPLETE: (
        "Razvedka tugadi: natija papkasi va hisobot tayyor. 1C da hech narsa "
        "o'zgartirilmadi."
    ),
}

# ══════════════════════════════════════════════════════════════════════════════════════════
# NOSOZLIK UCHLIGI — kod + operator matni + keyingi qadam
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Xato kodi — BARQAROR, MASHINA O'QIYDIGAN belgi (tarjima qilinadigan matn EMAS).
#: ⚠️ Shakl `status.ERROR_CODE_RE` bilan AYNI: kodlar `errors.json` ga tushadi.
BRIDGE_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")


@dataclass(frozen=True)
class FailureTriple:
    """Nosozlikning UCHTA qismi — birortasi tushib qolmaydi.

    ⚠️ NEGA UCHTA: faqat `code` mashina uchun, faqat `operator` matni odam uchun, lekin
    ikkisi ham «nima qilaman?» degan savolga javob BERMAYDI. Keyingi qadamsiz xato xabari
    har safar qo'ng'iroqqa aylanadi — Phase 4 da aynan shu bo'lgan.
    """

    code: str
    operator: str
    next_action: str


# ── ARXITEKTOR BERGAN KODLAR (9) ──────────────────────────────────────────────────────────
CODE_COLLECTOR_EXECUTION_NOT_ALLOWED = "COLLECTOR_EXECUTION_NOT_ALLOWED"
CODE_STALE_OUTPUT = "STALE_OUTPUT"
CODE_NONCE_MISMATCH = "NONCE_MISMATCH"
CODE_WRONG_COLLECTOR_VERSION = "WRONG_COLLECTOR_VERSION"
CODE_PARTIAL_PACKAGE = "PARTIAL_PACKAGE"
CODE_OUTPUT_PREDATES_REQUEST = "OUTPUT_PREDATES_REQUEST"
CODE_OPERATOR_CANCELLED = "OPERATOR_CANCELLED"
CODE_RUN_DIR_NOT_EMPTY = "RUN_DIR_NOT_EMPTY"
CODE_TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"

ARCHITECT_CODES: tuple[str, ...] = (
    CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, CODE_STALE_OUTPUT, CODE_NONCE_MISMATCH,
    CODE_WRONG_COLLECTOR_VERSION, CODE_PARTIAL_PACKAGE, CODE_OUTPUT_PREDATES_REQUEST,
    CODE_OPERATOR_CANCELLED, CODE_RUN_DIR_NOT_EMPTY, CODE_TARGET_AMBIGUOUS,
)

# ── KELTIRIB CHIQARILGAN KODLAR (5) ───────────────────────────────────────────────────────
#: ⚠️⚠️ NEGA QO'SHILDI: shartnoma «AGENT RAD ETADI … har biri uchun ALOHIDA kod» deydi va
#:    YETTI rad etish sababini sanaydi. Arxitektor ro'yxatidagi kodlar ularning BESHTASINI
#:    qoplaydi; «javob yo'q» va «tugallanish belgisi yo'q» esa qoplanmagan, holbuki ular
#:    operator uchun BUTUNLAY boshqa qadam talab qiladi («yig'uvchi umuman ishlamadi» va
#:    «yig'uvchi ishini tugatmadi»). Ikkisini mavjud kodga qo'shib yuborish — aynan
#:    «ALOHIDA kod» talabini buzish. Qolgan uchtasi protokolning O'ZI uchun zarur va
#:    pastda alohida izohlangan.
#: ⚠️ Bu kodlar ALOHIDA ro'yxatda turadi, demak arxitektor bergan to'qqizta kod
#:    AUDIT QILINADIGAN holda ajralib qoladi (test ikkisini ham sanaydi).
CODE_RESPONSE_MISSING = "RESPONSE_MISSING"
CODE_DONE_MARKER_MISSING = "DONE_MARKER_MISSING"
#: ⚠️ Javob BOSHQA bazadan yig'ilgan bo'lsa — bu `STALE_OUTPUT` emas: fayl eski emas,
#:    nishon boshqa. Operatorning qadami ham boshqa (bazani moslash, yurishni qayta
#:    boshlash emas).
CODE_TARGET_FINGERPRINT_MISMATCH = "TARGET_FINGERPRINT_MISMATCH"
#: ⚠️ Shakl buzuq hujjat uchun: kalit yo'q, noma'lum kalit, sanoq MATN emas. Bu
#:    «mos emas» EMAS — hujjatni umuman o'qib bo'lmaydi.
CODE_BRIDGE_SHAPE_INVALID = "BRIDGE_SHAPE_INVALID"
#: ⚠️ Standart yurish papkasining ildizini ANIQLAB BO'LMASA — FAIL-CLOSED: o'zgaruvchi
#:    yo'qligi manba daraxtiga yoki joriy papkaga yozishga RUXSAT BERMAYDI.
CODE_RUNS_ROOT_UNKNOWN = "RUNS_ROOT_UNKNOWN"

#: ⚠️⚠️ Yig'uvchining KO'PRIK qatlami `request.json` ni o'qib RAD ETGANI. `FAILED` dan
#:      AJRATILADI: `FAILED` — razvedka YURDI va yiqildi (paketni ko'rish kerak);
#:      bu esa razvedka UMUMAN BOSHLANMAGANI (yurishni qaytadan boshlash kerak).
#: ⚠️ Bu kod konformans darvozasi topgan driftdan keyin qo'shildi: `.bsl` allaqachon
#:    `status="BRIDGE_REJECTED"` yozardi, Python tomoni esa uni bilmay «hujjat buzuq»
#:    deb ko'rsatardi — ya'ni operator HAQIQIY sababni olmasdi.
CODE_COLLECTOR_REJECTED_REQUEST = "COLLECTOR_REJECTED_REQUEST"

DERIVED_CODES: tuple[str, ...] = (
    CODE_RESPONSE_MISSING, CODE_DONE_MARKER_MISSING, CODE_TARGET_FINGERPRINT_MISMATCH,
    CODE_BRIDGE_SHAPE_INVALID, CODE_RUNS_ROOT_UNKNOWN, CODE_COLLECTOR_REJECTED_REQUEST,
)

#: Hamma ko'prik kodi.
BRIDGE_CODES: tuple[str, ...] = ARCHITECT_CODES + DERIVED_CODES

#: ⚠️ Nosozlik uchligida FAYL NOMI ataylab ko'rsatiladi (operator rostdan ham papkaga
#:    qaraydi), lekin YO'L ko'rsatilmaydi: yo'l sir bo'lishi mumkin.
FAILURE_TRIPLE: dict[str, FailureTriple] = {
    CODE_COLLECTOR_REJECTED_REQUEST: FailureTriple(
        code=CODE_COLLECTOR_REJECTED_REQUEST,
        operator=(
            "Yig'uvchi so'rovni RAD ETDI: so'rov fayli mos kelmadi (bir martalik belgi "
            "yoki yig'uvchi versiyasi boshqa). Razvedka UMUMAN BOSHLANMADI va 1C da hech "
            "narsa o'zgartirilmadi."
        ),
        next_action=(
            "Discovery ni QAYTA boshlang — agent yangi so'rov yaratadi. Takrorlansa, 1C da "
            "ochilgan yig'uvchi versiyasi agent kutgan versiyaga mos ekanini tekshiring."
        ),
    ),
    CODE_COLLECTOR_EXECUTION_NOT_ALLOWED: FailureTriple(
        code=CODE_COLLECTOR_EXECUTION_NOT_ALLOWED,
        operator=(
            "Agent 1C ni O'ZI ishga tushirmadi. Bu yo'l haqiqiy 1C da hech qachon "
            "sinalmagan, shu bois u o'z-o'zidan ishlatilmaydi."
        ),
        next_action=(
            "Yig'uvchini O'Z 1C sessiyangizda bir marta ochib bajaring. Agent natija "
            "papkasini kuzatadi va o'zi davom etadi."
        ),
    ),
    CODE_STALE_OUTPUT: FailureTriple(
        code=CODE_STALE_OUTPUT,
        operator=(
            "Papkadagi javob BOSHQA yurishga tegishli, ya'ni u eski. Eski javob bo'yicha "
            "xulosa chiqarilmaydi."
        ),
        next_action=(
            "Yangi yurish boshlang — har yurish o'z papkasini oladi. Eski papkani agent "
            "O'CHIRMAYDI: kerak bo'lsa uni o'zingiz chetga suring."
        ),
    ),
    CODE_NONCE_MISMATCH: FailureTriple(
        code=CODE_NONCE_MISMATCH,
        operator=(
            "Javob shu yurish uchun berilgan belgiga mos kelmadi, ya'ni u boshqa so'rovga "
            "yozilgan javob."
        ),
        next_action=(
            "Yig'uvchini SHU yurishning so'rovi bilan qaytadan bajaring: oldingi so'rov "
            "qolgan papkadan foydalanmang."
        ),
    ),
    CODE_WRONG_COLLECTOR_VERSION: FailureTriple(
        code=CODE_WRONG_COLLECTOR_VERSION,
        operator=(
            "Yig'uvchining versiyasi kutilganidan farq qiladi. Eski yig'uvchi natijasi "
            "to'liq bo'lmasligi mumkin, shu bois u qabul qilinmadi."
        ),
        next_action=(
            "Yig'uvchining yangi faylini 1C ga yuklab, yurishni qaytadan boshlang."
        ),
    ),
    CODE_PARTIAL_PACKAGE: FailureTriple(
        code=CODE_PARTIAL_PACKAGE,
        operator=(
            "Natija TO'LIQ EMAS: kutilgan fayllarning bir qismi yo'q. Yarim natija bo'yicha "
            "tahlil qilinmaydi."
        ),
        next_action=(
            "Yig'uvchini oxirigacha bajarilishini kutib, bo'sh papka bilan qaytadan "
            "urinib ko'ring. Yarim natijani o'chirmasdan saqlab qo'ying."
        ),
    ),
    CODE_OUTPUT_PREDATES_REQUEST: FailureTriple(
        code=CODE_OUTPUT_PREDATES_REQUEST,
        operator=(
            "Natija so'rovdan OLDIN yozilgan, ya'ni u shu yurishda yig'ilmagan."
        ),
        next_action=(
            "Bo'sh papka bilan yangi yurish boshlang va yig'uvchini SHUNDAN KEYIN bajaring."
        ),
    ),
    CODE_OPERATOR_CANCELLED: FailureTriple(
        code=CODE_OPERATOR_CANCELLED,
        operator=(
            "Yurishni SIZ bekor qildingiz — bu nuqson emas. Agent kutishni to'xtatdi va "
            "1C da hech narsa o'zgartirmadi."
        ),
        next_action=(
            "1C oynasini o'zingiz yoping: agent birorta jarayonni majburan tugatmaydi. "
            "Xohlasangiz yangi yurish boshlang — oldingi papka joyida qoladi."
        ),
    ),
    CODE_RUN_DIR_NOT_EMPTY: FailureTriple(
        code=CODE_RUN_DIR_NOT_EMPTY,
        operator=(
            "Ko'rsatilgan yurish papkasi BO'SH EMAS. Agent unga yozmadi, chunki begona "
            "fayllar natija bilan aralashib ketardi."
        ),
        next_action=(
            "Bo'sh papka ko'rsating yoki ichidagini o'zingiz chetga suring. Agent hech "
            "narsani o'chirmaydi."
        ),
    ),
    CODE_TARGET_AMBIGUOUS: FailureTriple(
        code=CODE_TARGET_AMBIGUOUS,
        operator=(
            "Bir nechta ma'lumot bazasi bir xil darajada mos keldi. Agent o'zi tanlamadi: "
            "noto'g'ri baza tanlansa butun hisobot noto'g'ri bo'ladi."
        ),
        next_action=(
            "Ro'yxatdan kerakli bazani O'ZINGIZ tanlang."
        ),
    ),
    CODE_RESPONSE_MISSING: FailureTriple(
        code=CODE_RESPONSE_MISSING,
        operator=(
            "Yig'uvchi javob qoldirmadi: papkada `response.json` yo'q. Ya'ni yig'uvchi "
            "umuman boshlanmagan yoki natijani boshqa joyga yozgan."
        ),
        next_action=(
            "Yig'uvchini qaytadan bajaring va unga agent ko'rsatgan papkani bering."
        ),
    ),
    CODE_DONE_MARKER_MISSING: FailureTriple(
        code=CODE_DONE_MARKER_MISSING,
        operator=(
            "Yig'uvchi ishini TUGATGANINI bildirmadi: papkada `bridge_done.json` yo'q. "
            "Natija yarim yozilgan bo'lishi mumkin, shu bois u qabul qilinmadi."
        ),
        next_action=(
            "Yig'uvchi oxirigacha ishlab bo'lgunicha kutib, qaytadan urinib ko'ring. 1C "
            "oynasini yig'uvchi o'zi tugatguncha yopmang."
        ),
    ),
    CODE_TARGET_FINGERPRINT_MISMATCH: FailureTriple(
        code=CODE_TARGET_FINGERPRINT_MISMATCH,
        operator=(
            "Javob BOSHQA ma'lumot bazasidan yig'ilgan: so'ralgan baza bilan yig'ilgan baza "
            "bir xil emas."
        ),
        next_action=(
            "1C da so'rovdagi bazani tanlab, yig'uvchini qaytadan bajaring."
        ),
    ),
    CODE_BRIDGE_SHAPE_INVALID: FailureTriple(
        code=CODE_BRIDGE_SHAPE_INVALID,
        operator=(
            "Yig'uvchi qoldirgan fayl kutilgan shaklda emas — uni o'qib bo'lmadi."
        ),
        next_action=(
            "Yig'uvchi versiyasi agent versiyasiga mosligini tekshirib, yangi yurish "
            "boshlang. Fayllarni o'chirmasdan saqlab qo'ying."
        ),
    ),
    CODE_RUNS_ROOT_UNKNOWN: FailureTriple(
        code=CODE_RUNS_ROOT_UNKNOWN,
        operator=(
            "Yurishlar uchun standart papka ANIQLANMADI. Agent taxmin qilmaydi va "
            "o'zboshimcha joyga yozmaydi."
        ),
        next_action=(
            "Agentni ishga tushirganda yurish papkasini O'ZINGIZ ko'rsating."
        ),
    ),
}


# ══════════════════════════════════════════════════════════════════════════════════════════
# SO'ROVLAR (fail-closed: noma'lum nom — ISTISNO, zaxira qiymat YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
def is_phase(phase: str) -> bool:
    """Faza nomi shartnomada bormi."""
    return phase in PHASE_TO_STATE


def phase_state(phase: str) -> str:
    """Fazaga MOS KELADIGAN mavjud holat (noma'lum faza — ISTISNO)."""
    _assert_phase(phase)
    return PHASE_TO_STATE[phase]


def phase_text(phase: str) -> str:
    """Faza uchun operator matni (noma'lum faza — ISTISNO).

    ⚠️ Bo'sh matn QAYTARILMAYDI: «spinner-only» faza bo'lmasligi import paytida ham,
    test bilan ham qulflangan.
    """
    _assert_phase(phase)
    return PHASE_TEXT[phase]


def is_failure_phase(phase: str) -> bool:
    """Faza nosozlik bilan tugaydimi (holati `states.FAILURE_STATES` ichidami)."""
    _assert_phase(phase)
    return phase in FAILURE_PHASES


def is_terminal_phase(phase: str) -> bool:
    """Faza YAKUNIY holatga tushadimi."""
    _assert_phase(phase)
    return phase in TERMINAL_PHASES


def phases_for_state(state: str) -> tuple[str, ...]:
    """Shu holatga mos keladigan fazalar (operator ko'rish tartibida).

    ⚠️ Noma'lum holat — ISTISNO (`states` ning o'z darvozasi orqali).
    """
    if not st.is_known(state):
        raise BridgePhaseError(
            f"noma'lum holat: {state!r} — holat nomlari `states.py` da, yangisi O'YLAB "
            f"CHIQARILMAYDI"
        )
    return tuple(p for p in BRIDGE_PHASES if PHASE_TO_STATE[p] == state)


def failure_triple(code: str) -> FailureTriple:
    """Nosozlik uchligi (noma'lum kod — ISTISNO: jim «umumiy xato» YO'Q)."""
    if code not in FAILURE_TRIPLE:
        raise BridgePhaseError(
            f"noma'lum ko'prik kodi: {code!r}; ruxsat etilganlari {sorted(FAILURE_TRIPLE)}"
        )
    return FAILURE_TRIPLE[code]


def _assert_phase(phase: str) -> None:
    if not isinstance(phase, str) or phase not in PHASE_TO_STATE:
        raise BridgePhaseError(
            f"noma'lum ko'prik fazasi: {phase!r}; ruxsat etilganlari "
            f"{sorted(PHASE_TO_STATE)}"
        )


# ══════════════════════════════════════════════════════════════════════════════════════════
# IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ Testlar ham shu invariantlarni qulflaydi, lekin modul import bo'lgan ZAHOTI yiqilishi —
#    eng arzon darvoza: test yurgizilmagan yo'l ham shu yerdan o'tadi.
assert len(BRIDGE_PHASES) == 12, "ko'prik fazalari AYNAN 12 ta bo'lishi kerak"
assert len(set(BRIDGE_PHASES)) == 12, "faza nomi takrorlangan"
assert set(PHASE_TO_STATE) == set(BRIDGE_PHASES), "PHASE_TO_STATE hamma fazani qamramaydi"
assert set(PHASE_TEXT) == set(BRIDGE_PHASES), "PHASE_TEXT hamma fazani qamramaydi"
assert all(PHASE_TEXT[p].strip() != "" for p in BRIDGE_PHASES), \
    "«spinner-only» faza BO'LMAYDI: har fazada operator matni bo'lishi SHART"
assert set(PHASE_TO_STATE.values()) <= set(st.STATES), \
    "moslik DIAPAZONI mavjud holatlardan chiqdi — yangi holat QO'SHILMAYDI"
assert len(st.FAILURE_STATES) == 11, \
    "ko'prik qatlami `states.FAILURE_STATES` ga holat QO'SHMAYDI (11 bo'lib qoladi)"
assert len(st.NORMAL_STATES) == 12, "ko'prik qatlami normal holatlarni O'ZGARTIRMAYDI"
assert len(set(BRIDGE_CODES)) == len(BRIDGE_CODES), "ko'prik kodi takrorlangan"
assert set(FAILURE_TRIPLE) == set(BRIDGE_CODES), \
    "FAILURE_TRIPLE kodlar ro'yxatidan ajralib ketdi"
assert all(BRIDGE_CODE_RE.fullmatch(c) for c in BRIDGE_CODES), \
    "ko'prik kodi `[A-Z][A-Z0-9_]*` shaklida bo'lishi kerak"
assert all(t.code == c and t.operator.strip() and t.next_action.strip()
           for c, t in FAILURE_TRIPLE.items()), \
    "nosozlik uchligining uchta qismi ham BO'SH BO'LMASLIGI kerak"
assert not set(ARCHITECT_CODES) & set(DERIVED_CODES), \
    "kod ikki ro'yxatda bir vaqtda turmaydi (audit ajrimi yo'qoladi)"
assert len(ARCHITECT_CODES) == 9, "arxitektor bergan kodlar AYNAN to'qqizta"
