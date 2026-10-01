# -*- coding: utf-8 -*-
"""Agent HOLAT MASHINASI — ruxsat etilgan o'tishlar va ANIQ yiqilish holatlari.

Bu modul 1C'ga ULANMAYDI, fayl o'qimaydi, vaqtni o'zi olmaydi va tarmoqqa chiqmaydi. U faqat
«qaysi holatdan qaysi holatga o'tish mumkin» degan savolga javob beradi. Shu bois u to'liq
deterministik va 1C'siz sinaladi.

FAIL-CLOSED ASOSIY QOIDA: `TRANSITIONS` da YOZILMAGAN o'tish — ISTISNO. «Balki shunga
o'xshash holat mo'ljallangandir» degan zaxira yo'l YO'Q. Sabab: agent quvurining o'rtasida
holatni jimgina «to'g'rilash» yiqilishni muvaffaqiyatga aylantiradi, operator esa hisobotni
to'liq deb o'qiydi.

⚠️⚠️ `UNKNOWN` HECH QACHON `NOT_FOUND` ga AYLANMAYDI. Bu qoida yadroda (`runtime_bundle`
     dagi `absent` / `unreadable`) allaqachon amal qiladi va agent qatlamida ham AYNI
     kuchda saqlanadi:
       · `FAILED_NO_1C`                  — qaradim, 1C O'RNATILMAGAN (bu JAVOB);
       · `FAILED_COLLECTOR_UNAVAILABLE`  — 1C BOR, lekin yig'uvchi natija bermadi (javob YO'Q).
     Ikkisini bitta holatga qo'shib yuborish operatorni butunlay boshqa yo'lga yuboradi:
     birinchisida 1C o'rnatiladi, ikkinchisida `watch_folder` yo'li bilan davom etiladi.

⚠️ BU MASHINADA 1C UMUMAN O'RNATILMAGAN (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q,
   `pywin32` yo'q). Shu bois integratsiya yo'llari (`batch_execute`, `watch_folder`) HAQIQIY
   1C ga qarshi SINALMAGAN va `RUNTIME-UNKNOWN` deb belgilanadi. Bu modul esa sof mantiq —
   u 1C'ni TALAB QILMAYDI va shu sababli to'liq isbotlanadi.
"""
from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════════════════
# HOLATLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Normal quvur (12 holat). Nomlari ARXITEKTOR BELGILAGAN — o'z-o'zidan «yaxshilanmaydi».
START = "START"
ENVIRONMENT_SCAN = "ENVIRONMENT_SCAN"
TARGET_SELECTION = "TARGET_SELECTION"
SAFETY_CHECK = "SAFETY_CHECK"
METADATA_DISCOVERY = "METADATA_DISCOVERY"
VALIDATION = "VALIDATION"
GRAPH_BUILD = "GRAPH_BUILD"
ANALYSIS = "ANALYSIS"
OPTIONAL_APPROVED_PROBES = "OPTIONAL_APPROVED_PROBES"
REVALIDATE = "REVALIDATE"
REPORT = "REPORT"
COMPLETE = "COMPLETE"

#: ANIQ yiqilish holatlari (11). ⚠️ Umumiy «FAILED» YO'Q: bitta umumiy yiqilish operatorga
#: nima qilishni aytmaydi va shu bois har bir qo'ng'iroq qo'lda tekshiruvga aylanadi.
FAILED_NO_1C = "FAILED_NO_1C"
FAILED_NO_TARGET = "FAILED_NO_TARGET"
FAILED_AUTH_REQUIRED = "FAILED_AUTH_REQUIRED"
FAILED_COLLECTOR_UNAVAILABLE = "FAILED_COLLECTOR_UNAVAILABLE"
FAILED_SAFETY = "FAILED_SAFETY"
FAILED_VALIDATION = "FAILED_VALIDATION"
FAILED_ANALYSIS = "FAILED_ANALYSIS"
FAILED_REPORT = "FAILED_REPORT"
FAILED_TIMEOUT = "FAILED_TIMEOUT"
FAILED_INTERNAL = "FAILED_INTERNAL"
ABORTED_BY_OPERATOR = "ABORTED_BY_OPERATOR"

#: Normal holatlar — QUVUR TARTIBIDA (alfavit bo'yicha emas: tartib hisobotda ko'rinadi).
NORMAL_STATES: tuple[str, ...] = (
    START, ENVIRONMENT_SCAN, TARGET_SELECTION, SAFETY_CHECK, METADATA_DISCOVERY, VALIDATION,
    GRAPH_BUILD, ANALYSIS, OPTIONAL_APPROVED_PROBES, REVALIDATE, REPORT, COMPLETE,
)

#: Muvaffaqiyatsiz yakunlar. ⚠️ `ABORTED_BY_OPERATOR` shu ro'yxatda, chunki u ham
#: `COMPLETE` EMAS: «muvaffaqiyat emas» degan yakunni jimgina muvaffaqiyat deb o'qish
#: aynan shu ro'yxat bilan to'siladi. Lekin u AYB EMAS — `is_operator_abort()` bilan
#: ajratiladi va hisobotda boshqacha ko'rsatiladi.
FAILURE_STATES: tuple[str, ...] = (
    FAILED_NO_1C, FAILED_NO_TARGET, FAILED_AUTH_REQUIRED, FAILED_COLLECTOR_UNAVAILABLE,
    FAILED_SAFETY, FAILED_VALIDATION, FAILED_ANALYSIS, FAILED_REPORT, FAILED_TIMEOUT,
    FAILED_INTERNAL, ABORTED_BY_OPERATOR,
)

#: Hamma holat.
STATES: tuple[str, ...] = NORMAL_STATES + FAILURE_STATES

#: Yakuniy holatlar: `COMPLETE` + hamma yiqilish.
TERMINAL: frozenset[str] = frozenset((COMPLETE,)) | frozenset(FAILURE_STATES)


class TransitionError(ValueError):
    """Ruxsat etilmagan holat o'tishi yoki noma'lum holat nomi."""


# ══════════════════════════════════════════════════════════════════════════════════════════
# O'TISHLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
#: HAR QANDAY yakunlanmagan holatdan mumkin bo'lgan uchta chiqish.
#: ⚠️ NEGA UCHALASI HAMMA JOYDA: (1) vaqt chegarasi quvurning har qadamida urib ketishi
#:    mumkin — 1C paketli rejimda osilib qolishi odatiy; (2) kutilmagan ichki xato ham
#:    har qadamda bo'ladi va u JIM yutilmasligi kerak; (3) operator «to'xtat» tugmasini
#:    istalgan paytda bosadi va bu HUQUQI — agent operator ishga tushirganda ishlaydi,
#:    demak operator to'xtatganda TO'XTAYDI.
_ANY_EXIT: tuple[str, ...] = (FAILED_TIMEOUT, FAILED_INTERNAL, ABORTED_BY_OPERATOR)

#: Ruxsat etilgan o'tishlar. Kalitda HAMMA holat bor (yakunlarda — bo'sh juftlik), chunki
#: «kalit yo'q» va «chiqish yo'q» ni ajratib bo'lmasa, fail-closed darvoza xato nomini
#: ruxsat etilmagan o'tishdan farqlay olmaydi.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    # Boshlanish: faqat muhitni skanerlash. ⚠️ Nishonni skanersiz tanlash YO'Q —
    # tanlash uchun nimadan tanlashni bilish kerak.
    START: (ENVIRONMENT_SCAN,) + _ANY_EXIT,
    # Skaner yakuni: 1C topildi (tanlashga o'tamiz) yoki TOPILMADI (bu JAVOB, taxmin emas).
    ENVIRONMENT_SCAN: (TARGET_SELECTION, FAILED_NO_1C) + _ANY_EXIT,
    # Nishon tanlash: baza yo'q — `FAILED_NO_TARGET`; baza bor, lekin autentifikatsiya
    # talab qiladi — `FAILED_AUTH_REQUIRED` (parol buyruq satriga QO'YILMAYDI).
    TARGET_SELECTION: (SAFETY_CHECK, FAILED_NO_TARGET, FAILED_AUTH_REQUIRED) + _ANY_EXIT,
    # Xavfsizlik darvozasi: faqat-o'qish invariantlari. Buzilsa — QUVUR TO'XTAYDI.
    SAFETY_CHECK: (METADATA_DISCOVERY, FAILED_SAFETY) + _ANY_EXIT,
    # Yig'uvchini ishga tushirish. Yig'uvchi natija bermasa — `FAILED_COLLECTOR_UNAVAILABLE`
    # (1C BOR, javob YO'Q), 1C parol so'rab to'xtasa — `FAILED_AUTH_REQUIRED`.
    METADATA_DISCOVERY: (VALIDATION, FAILED_COLLECTOR_UNAVAILABLE,
                         FAILED_AUTH_REQUIRED) + _ANY_EXIT,
    # Phase 4 validatori (`runtime_bundle`). Paket rad etilsa — tahlilga O'TILMAYDI.
    VALIDATION: (GRAPH_BUILD, FAILED_VALIDATION) + _ANY_EXIT,
    GRAPH_BUILD: (ANALYSIS, FAILED_ANALYSIS) + _ANY_EXIT,
    # Tahlildan keyin IKKI yo'l: operator tasdiqlagan zondlar bo'lsa — zondlar, bo'lmasa
    # TO'G'RIDAN hisobot. ⚠️ Zondlar MAJBURIY EMAS: `METADATA_ONLY` — DEFAULT rejim.
    ANALYSIS: (OPTIONAL_APPROVED_PROBES, REPORT, FAILED_ANALYSIS) + _ANY_EXIT,
    # Zondlardan keyin paket O'ZGARDI, demak QAYTA tekshiriladi. ⚠️ Zond allowlistdan
    # chiqsa — bu xavfsizlik buzilishi (`FAILED_SAFETY`), tahlil xatosi emas.
    OPTIONAL_APPROVED_PROBES: (REVALIDATE, FAILED_SAFETY,
                               FAILED_COLLECTOR_UNAVAILABLE) + _ANY_EXIT,
    REVALIDATE: (REPORT, FAILED_VALIDATION) + _ANY_EXIT,
    REPORT: (COMPLETE, FAILED_REPORT) + _ANY_EXIT,
    # ── Yakunlar: chiqish YO'Q ────────────────────────────────────────────────────────────
    # ⚠️ Yakundan keyin o'tish bo'lmasligi — shartnoma: yakunlangan yurish qayta tirilmaydi,
    #    yangi yurish YANGI `run_id` oladi. Aks holda bitta `agent_status.json` da ikki
    #    yurish aralashib, hisobot kimning natijasi ekani aniqlanmay qolardi.
    COMPLETE: (),
    FAILED_NO_1C: (),
    FAILED_NO_TARGET: (),
    FAILED_AUTH_REQUIRED: (),
    FAILED_COLLECTOR_UNAVAILABLE: (),
    FAILED_SAFETY: (),
    FAILED_VALIDATION: (),
    FAILED_ANALYSIS: (),
    FAILED_REPORT: (),
    FAILED_TIMEOUT: (),
    FAILED_INTERNAL: (),
    ABORTED_BY_OPERATOR: (),
}

# ══════════════════════════════════════════════════════════════════════════════════════════
# YIQILISH MA'NOLARI — operator uchun NIMA bo'ldi va NIMA QILISH kerak
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Har bir matn IKKI qismdan: (1) NIMA aniqlandi, (2) KEYINGI QADAM. Faqat birinchi qism
#: yozilgan xato xabari operatorni qo'ng'iroq qilishga majbur qiladi.
#: ⚠️ Bu matnlar `agent_status.notes` ga tushishi mumkin, demak ularning O'ZIDA sir
#: BO'LMASLIGI kerak (`redact.scan` bilan test qulflaydi): na yo'l, na misol parol, na
#: `kalit: qiymat` shaklidagi namuna.
FAILURE_MEANING: dict[str, str] = {
    FAILED_NO_1C: (
        "Qaradim: bu kompyuterda 1C:Enterprise O'RNATILMAGAN (reestrda ham, fayl tizimida "
        "ham, PATH da ham topilmadi). Bu JAVOB, taxmin emas. Keyingi qadam: 1C ni "
        "o'rnatgan kompyuterda ishga tushiring yoki shu kompyuterga 1C ni o'rnatib qayta "
        "urinib ko'ring."
    ),
    FAILED_NO_TARGET: (
        "1C topildi, lekin birorta ma'lumot bazasi (infobase) aniqlanmadi. Keyingi qadam: "
        "1C ni bir marta qo'lda ochib, kerakli bazani ro'yxatga qo'shing — agent shu "
        "ro'yxatdan o'qiydi."
    ),
    FAILED_AUTH_REQUIRED: (
        "Baza topildi, lekin unga kirish uchun foydalanuvchi tasdig'i kerak. Agent sirni "
        "buyruq satriga HECH QACHON qo'ymaydi (u jarayon ro'yxatida ko'rinib qoladi), shu "
        "bois bu yo'ldan davom etmadi. Keyingi qadam: yig'uvchi faylni O'Z 1C sessiyangizda "
        "bir marta ochib bajaring — kirish oynasini 1C ning o'zi ko'rsatadi, agent esa "
        "chiqish papkasini kuzatib quvurni davom ettiradi (`watch_folder` yo'li)."
    ),
    FAILED_COLLECTOR_UNAVAILABLE: (
        "1C BOR va baza tanlandi, lekin yig'uvchi natija QAYTARMADI — ya'ni javob YO'Q "
        "(«topilmadi» EMAS). Keyingi qadam: 1C versiyasi va yig'uvchi faylining mosligini "
        "tekshirib, `watch_folder` yo'li bilan qayta urinib ko'ring; chiqish papkasidagi "
        "xato jurnalini saqlab qo'ying."
    ),
    FAILED_SAFETY: (
        "Xavfsizlik darvozasi quvurni TO'XTATDI: so'ralgan amal faqat-o'qish chegarasidan "
        "chiqadi yoki ruxsat etilgan zondlar ro'yxatida yo'q. Hech narsa o'zgartirilmadi. "
        "Keyingi qadam: hisobotdagi sababni o'qing; zond kerak bo'lsa uni operator sifatida "
        "ALOHIDA tasdiqlash kerak."
    ),
    FAILED_VALIDATION: (
        "Yig'uvchi chiqargan paket tekshiruvdan O'TMADI (majburiy artefakt yo'q, shakl "
        "buzuq yoki sanoq matn emas). Tahlil QILINMADI — noto'g'ri paketdan chiqarilgan "
        "xulosa noto'g'ri bo'ladi. Keyingi qadam: paketni qayta yig'ing va validator "
        "xabarini o'zgartirmasdan saqlang."
    ),
    FAILED_ANALYSIS: (
        "Paket to'g'ri, lekin tahlil bosqichi yakunlanmadi (graf qurilmadi yoki analitik "
        "xato berdi). Paketning O'ZI joyida qoldi. Keyingi qadam: paketni saqlab qo'ying — "
        "tahlilni 1C siz, keyinroq ham qayta yurgizish mumkin."
    ),
    FAILED_REPORT: (
        "Tahlil tugadi, lekin natija papkasiga yozish yakunlanmadi (joy yetmasligi, kirish "
        "huquqi yoki chiqishda shubhali qiymat topilishi). Keyingi qadam: diskda joy va "
        "yozish huquqini tekshirib, qayta yurgizing."
    ),
    FAILED_TIMEOUT: (
        "Qadam ajratilgan vaqtdan oshdi va agent kutishni to'xtatdi. Hech narsa "
        "o'zgartirilmadi. Keyingi qadam: 1C band bo'lmagan paytda (masalan ish kunidan "
        "keyin) qayta yurgizing."
    ),
    FAILED_INTERNAL: (
        "Agentning o'zida kutilmagan xato: bu NUQSON, muhit muammosi emas va u JIM "
        "yutilmadi. Keyingi qadam: natija papkasini butunlay (hisoboti bilan) saqlab, "
        "ishlab chiquvchiga uzating — ichida sir yo'q, u yozishdan oldin tozalanadi."
    ),
    ABORTED_BY_OPERATOR: (
        "Yurishni OPERATOR to'xtatdi — bu nuqson emas. To'xtash paytigacha yig'ilgan "
        "natijalar joyida. Keyingi qadam: xohlasangiz qaytadan ishga tushiring; har yurish "
        "o'z papkasini oladi, oldingisi o'chmaydi."
    ),
}


# ══════════════════════════════════════════════════════════════════════════════════════════
# SO'ROVLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def is_known(state: str) -> bool:
    """Holat nomi shartnomada bormi."""
    return state in TRANSITIONS


def is_failure(state: str) -> bool:
    """Yakun muvaffaqiyatsizmi (`COMPLETE` emasmi).

    ⚠️ Noma'lum nom — ISTISNO, `False` EMAS. Noma'lum holatni «yiqilish emas» deb aytish
    xato holatni muvaffaqiyat deb o'qishga olib keladi.
    """
    _assert_known(state, "holat")
    return state in FAILURE_STATES


def is_operator_abort(state: str) -> bool:
    """Operator to'xtatganmi. ⚠️ `is_failure()` ham `True` beradi; bu — AYB ajrimi."""
    _assert_known(state, "holat")
    return state == ABORTED_BY_OPERATOR


def is_terminal(state: str) -> bool:
    """Yakuniy holatmi (undan chiqish YO'Q)."""
    _assert_known(state, "holat")
    return state in TERMINAL


def can_transition(a: str, b: str) -> bool:
    """`a` dan `b` ga o'tish RUXSAT ETILGANMI (noma'lum nom — ISTISNO)."""
    _assert_known(a, "manba holat")
    _assert_known(b, "nishon holat")
    return b in TRANSITIONS[a]


def assert_transition(a: str, b: str) -> None:
    """Ruxsat etilmagan o'tishda `TransitionError`. ⚠️ Zaxira yo'l YO'Q."""
    if can_transition(a, b):
        return
    if a in TERMINAL:
        raise TransitionError(
            f"{a} — YAKUNIY holat, undan {b} ga o'tish YO'Q: yakunlangan yurish qayta "
            f"boshlanmaydi, yangi yurish yangi `run_id` oladi"
        )
    raise TransitionError(
        f"{a} -> {b} o'tishi ruxsat etilmagan; shu holatdan ruxsat etilganlari: "
        f"{sorted(TRANSITIONS[a])}"
    )


def failure_meaning(state: str) -> str:
    """Yiqilish holatining operator uchun ma'nosi (yiqilish bo'lmasa — ISTISNO)."""
    _assert_known(state, "holat")
    if state not in FAILURE_STATES:
        raise TransitionError(f"{state} — yiqilish holati emas, ma'no matni yo'q")
    return FAILURE_MEANING[state]


def _assert_known(state: str, role: str) -> None:
    if not isinstance(state, str) or state not in TRANSITIONS:
        raise TransitionError(f"noma'lum {role}: {state!r}")


# ⚠️ IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI: jadval va ro'yxatlar bir-biridan ajralib
#    ketmasin. Testlar ham shu invariantlarni qulflaydi, lekin modul import bo'lgan ZAHOTI
#    yiqilishi — eng arzon darvoza (test yurgizilmagan yo'l ham shu yerdan o'tadi).
assert len(NORMAL_STATES) == 12, "normal holatlar AYNAN 12 ta bo'lishi kerak"
assert len(FAILURE_STATES) == 11, "yiqilish holatlari AYNAN 11 ta bo'lishi kerak"
assert len(set(STATES)) == len(STATES), "holat nomi takrorlangan"
assert set(TRANSITIONS) == set(STATES), "TRANSITIONS hamma holatni qamramaydi"
assert all(t in TRANSITIONS for outs in TRANSITIONS.values() for t in outs), \
    "TRANSITIONS noma'lum nishonga ishora qiladi"
assert all(TRANSITIONS[s] == () for s in TERMINAL), "yakuniy holatdan chiqish bo'lmaydi"
assert set(FAILURE_MEANING) == set(FAILURE_STATES), \
    "FAILURE_MEANING yiqilish holatlari bilan mos emas"
