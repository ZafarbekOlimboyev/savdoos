# -*- coding: utf-8 -*-
"""Yig'uvchi KO'PRIGI — IKKI YO'L, BITTA interfeys (`collect`).

Bu modul agentning 1C bilan yagona aloqa nuqtasi. U Phase 4 paketini O'ZI YASAMAYDI,
tekshirmaydi, tahlil qilmaydi va redaksiya qilmaydi — bularning hammasi yadroda
(`..discovery_1c.runtime_bundle`, `graph`, `ai`, `redact`) ALLAQACHON bor va qayta yozilishi
regressiya bo'lardi. Ko'prikning YAGONA ishi: paket QAYERDAN kelishini hal qilish va
«paket TAYYOR» degan faktni ANIQ isbotlash.

IKKI YO'L (ikkisi ham operator uchun BITTA workflow: UI faqat «Start Discovery» ko'rsatadi):

  · PRIMARY — `batch_execute`: `1cv8.exe ENTERPRISE /F<baza> /Execute <epf> /C<params>`.
    Auditdan o'tgan AYNI `.epf` paketli rejimda yuritiladi. COM YO'Q, o'zboshimcha BSL YO'Q,
    o'zboshimcha so'rov YO'Q — xavfsizlik yuzasi operator qo'lda ochadigan yo'l bilan AYNI.
  · FALLBACK — `watch_folder`: operator `.epf` ni O'Z 1C sessiyasida bir marta ochadi
    (kirish oynasini 1C ning O'ZI ko'rsatadi — ko'prik sirni KO'RMAYDI), ko'prik esa chiqish
    papkasini KUZATADI va paket to'liq yozilganini isbotlab qaytaradi.

⚠️⚠️ `subprocess` NEGA BU YERDA QONUNIY va NEGA FAQAT SHU YERDA.
     Brief o'zboshimcha kod bajarishni taqiqlaydi — va bu taqiq buzilmaydi: biz BITTA
     ma'lum binarni (`1cv8.exe`) qat'iy belgilangan kalitlar bilan ishga tushiramiz, uning
     bajaradigan ishi esa statik auditdan o'tgan AYNI `.epf` (`epf_audit.py`). Ya'ni bu
     «kod bajarish» emas, «1C ni ishga tushirish». Shu bois:
       · qobiq rejimi (`shell`) HECH QACHON YOQILMAYDI — buyruq `list` argument sifatida
         beriladi,
         demak qobiq metabelgilari UMUMAN talqin qilinmaydi;
       · buyruq satri SOF funksiyada (`build_command`) quriladi va TEST bilan QULFLANADI,
         ya'ni 1C bo'lmagan mashinada ham aynan nima yuborilishi isbotlangan;
       · jarayonning `stdout`/`stderr` i UMUMAN O'QILMAYDI (`DEVNULL`): 1C xato matnida
         ulanish satrini chiqarishi mumkin, u esa jurnalga tushib sirni oshkor qilardi.
         Diagnostika paketning O'Z `errors.json` idan olinadi.
     Ko'prikdan tashqari HECH BIR agent moduli `subprocess` import qilmaydi.

⚠️ PAROL TAQIG'I (brief: ochiq matnli kredensial saqlash YO'Q).
   `/P<parol>` kaliti buyruq satrida parol qoldiradi va u JARAYON RO'YXATIDA ko'rinadi
   (Task Manager, WMI, audit jurnali) — ya'ni «saqlamaymiz» deyish ham yetarli emas, u
   baribir yozib olinadi. Shu bois ko'prik parolni (va foydalanuvchi nomini) buyruq satriga
   QO'YMAYDI, `CollectPlan` da kredensial MAYDONI UMUMAN YO'Q, va qurilgan buyruq
   `_assert_no_credentials` darvozasidan o'tadi: `/P...` yoki `/N...` ko'ringan zahoti
   ISTISNO. `requires_auth` `"false"` BO'LMASA — `batch_execute` BOSHLANMAYDI:
   `FAILED_AUTH_REQUIRED` qaytadi va `watch_folder` TAKLIF qilinadi.
   ⚠️ `unknown` ham to'xtatadi: fail-closed, noma'lumlik «parol kerak emas» degani EMAS.

⚠️ JIMGINA ZAXIRAGA O'TISH YO'Q. Ko'prik `batch_execute` yiqilganda `watch_folder` ni O'ZI
   boshlab ketmaydi — chunki u yo'l ODAM ishini talab qiladi (operator `.epf` ni o'z
   sessiyasida ochishi kerak), ko'prik esa odam emas. Shu bois u ANIQ yiqilish holatini
   (`state_hint`) va TAKLIFNI (`notes`) qaytaradi, qarorni esa quvur va operator qabul
   qiladi. «O'zi urinib ko'rdi, o'zi o'tdi» xulqi aynan Phase 4 da yolg'on SUCCESS bergan
   naqsh edi.

⚠️⚠️ RUNTIME HOLATI — «ISHLAYDI» DEMAYMIZ. Bu mashinada 1C:Enterprise UMUMAN O'RNATILMAGAN
     (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q, `pywin32` yo'q), `.epf` konteyneri esa
     repoda yo'q. Shu bois `batch_execute` BAJARILMAGAN va `RUNTIME-UNKNOWN`
     (`integrations/1c/AGENT_INTEGRATION_MATRIX.md`). Testlar ko'prikning O'Z mantiqini
     (buyruq shakli, darvozalar, tayyorlik isboti) sintetik fiksturalarda isbotlaydi va 1C
     ning xulqi haqida HECH QANDAY da'vo qilmaydi. Bundan tashqari bugun `.epf` da paketli
     parametrni o'qiydigan kirish nuqtasi YO'Q («BSL BO'SHLIG'I»), demak PRIMARY yo'l
     amalda chiqish papkasini bo'sh qoldiradi va `BUNDLE_INCOMPLETE` bilan yiqiladi — bu
     QOBILIYAT CHEGARASI, yashirilmaydi.

⚠️ BUNING USTIGA: aniqlovchi (`detector._parse_connect`) `requires_auth` ni HECH QACHON
   `"false"` qilmaydi (parolsizlikni ULANMASDAN isbotlab bo'lmaydi). Demak `"false"` faqat
   operator tasdig'idan kelishi mumkin, ya'ni bugungi holatda PRIMARY yo'l ikki tomondan
   yopiq. Buni ham yozib qo'yamiz, chunki «PRIMARY» so'zi o'z-o'zidan «ishlaydi» degan
   taassurot beradi.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER, ROUTES
from . import states as st
from .detector import (KIND_FILE, KIND_SERVER, PRESENCE_ABSENT, PRESENCE_FOUND,
                       PRESENCE_UNKNOWN, TRI_FALSE)
from .status import AgentError
from ..discovery_1c.runtime_bundle import (MANIFEST_FILE, MANIFEST_VERSION,
                                           MODE_METADATA_ONLY, MODES, REQUIRED_FILES)

# ══════════════════════════════════════════════════════════════════════════════════════════
# SHARTNOMA QIYMATLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Paketli rejim kalitlari. ⚠️ Matn sifatida KONSTANTA: ularni joy-joyda qayta yozish
#: buyruq shaklini bir kun ikkiga ajratardi.
VERB_ENTERPRISE = "ENTERPRISE"
SWITCH_FILE_BASE = "/F"
SWITCH_EXECUTE = "/Execute"
SWITCH_PARAMS = "/C"

#: ⚠️ TAQIQLANGAN kalitlar: `/P` — parol, `/N` — foydalanuvchi nomi. Ikkisi ham kredensial
#: va ikkisi ham jarayon ro'yxatida ko'rinadi. Ko'prik kredensial UZATMAYDI, shu bois bu
#: ro'yxat «sozlama» emas — u faqat KELAJAKDAGI TAHRIRNI to'sish uchun turadi.
FORBIDDEN_SWITCHES: tuple[str, ...] = ("/P", "/N")

#: Argumentda RAD etiladigan belgilar.
#: ⚠️ Qobiq rejimi YOQILMAGANI uchun qobiq metabelgilari AMALDA talqin qilinmaydi — ya'ni
#:    bu ro'yxat IKKINCHI himoya qatlami. HAQIQIY xavf — qo'shtirnoq: Windows argv ni
#:    satrga aylantirganda aynan u chegarani buzadi. Yangi qator esa yo'lda bo'lishi
#:    UMUMAN mumkin emas va u jurnal satrini ikkiga bo'lib, izni soxtalashtirardi.
#: ⚠️ `%` va `$` ATAYLAB ro'yxatda YO'Q: ular Windows yo'lida qonuniy uchraydi, qobiq esa
#:    chaqirilmaydi — ularni taqiqlash haqiqiy papkani sababsiz rad etardi.
FORBIDDEN_ARG_CHARS: tuple[str, ...] = ('"', ";", "&", "|", "\n", "\r", "<", ">", "^", "`")

#: Xato kodlari. ⚠️ Shakl `status.ERROR_CODE_RE` ga MOS (`[A-Z][A-Z0-9_]{1,47}`), chunki bu
#: yozuvlar to'g'ridan-to'g'ri `agent_status.json` ning `errors` iga ko'chadi.
CODE_EPF_MISSING = "EPF_MISSING"
CODE_OUTPUT_DIR_MISSING = "OUTPUT_DIR_MISSING"
CODE_OUTPUT_DIR_NOT_EMPTY = "OUTPUT_DIR_NOT_EMPTY"
CODE_EXE_MISSING = "EXE_MISSING"
CODE_NO_TARGET = "NO_TARGET"
CODE_AUTH_REQUIRED = "AUTH_REQUIRED"
CODE_SERVER_TARGET_UNSUPPORTED = "SERVER_TARGET_UNSUPPORTED"
CODE_MODE_UNSUPPORTED = "MODE_UNSUPPORTED"
CODE_UNSAFE_ARGUMENT = "UNSAFE_ARGUMENT"
CODE_EXIT_CODE_NONZERO = "EXIT_CODE_NONZERO"
CODE_LAUNCH_FAILED = "LAUNCH_FAILED"
CODE_BUNDLE_INCOMPLETE = "BUNDLE_INCOMPLETE"
CODE_WAIT_TIMEOUT = "WAIT_TIMEOUT"
CODE_BAD_PLAN = "BAD_PLAN"
#: ⚠️ Kuzatiladigan papkaning O'ZI ko'rsatilmagan/topilmagan/o'qilmagan. Nomi ATAYLAB
#: `ui.py` dagi eski kod bilan AYNI (`BUNDLE_DIR_MISSING`): u allaqachon chiqishga tushgan
#: BARQAROR belgi va uni «ko'chirish paytida chiroyliroq qilish» mashina o'qiydigan
#: shartnomani jimgina sindirardi.
CODE_BUNDLE_DIR_MISSING = "BUNDLE_DIR_MISSING"
#: ⚠️⚠️ PAKETLI YO'L UMUMAN URINILMADI degan FAKT. Bu «yiqildi» EMAS: hech narsa ishga
#: tushirilmagan. Lekin u `errors` ga AYNAN yoziladi, chunki brief §4 «jimgina yiqilish
#: YO'Q» deydi — «urinib ham ko'rmadim» ni yozmaslik eng jim yiqilish bo'lardi.
CODE_BATCH_NOT_ATTEMPTED = "BATCH_EXECUTE_NOT_ATTEMPTED"

#: Xato yozuvlarining `scope` lari — ikki joyda qayta yozilmasligi uchun KONSTANTA.
SCOPE_BATCH = f"collector:{ROUTE_BATCH_EXECUTE}"
SCOPE_WATCH = f"collector:{ROUTE_WATCH_FOLDER}"

#: Yig'uvchining MANBASI va KIRISH NUQTASI — operatorga aytiladigan ANIQ nom.
#: ⚠️ Repoda `.epf` konteyneri YO'Q (`AGENT_INTEGRATION_MATRIX.md`), shu bois operatorga
#:    «mana shu faylni ikki marta bosing» deb aytib bo'lmaydi: u Konfiguratorda yig'iladi.
COLLECTOR_SOURCE_FILE = "integrations/1c/extractor/BinOSDiscovery.bsl"
COLLECTOR_ENTRY_POINT = "ВыполнитьРазведку"

#: ⚠️⚠️ `batch_execute` NEGA URINILMAGANINING ANIQ SABABI — YAGONA manba.
#:    Hisobot ham, yurish yozuvi ham SHU matndan o'qiydi, demak ikkisi zid bo'lishi mumkin
#:    emas. Matnda uchta BO'SHLIQ sanaladi va hech biri «vaqtincha» deb yumshatilmaydi.
BATCH_NOT_ATTEMPTED_REASON = (
    "Paketli yo'l (`batch_execute`) bu yurishda UMUMAN URINILMADI va bu «yiqildi» degani "
    "EMAS: agent 1C ni ishga tushirmadi. Sabab uchta va hammasi BUGUNGI qobiliyat "
    "chegarasi: (1) yig'uvchining `.epf` konteyneri repoda YO'Q, demak paketli rejimda "
    "bajariladigan fayl ko'rsatib bo'lmaydi; (2) yig'uvchi manbasida paketli ishga "
    "tushirish parametrini o'qiydigan kirish nuqtasi YO'Q — eksport funksiyasi chiqish "
    "papkasini ARGUMENT bilan talab qiladi, paketli rejim esa argument uzatmaydi; "
    "(3) aniqlovchi birorta bazani «tasdiq talab qilmaydi» deb isbotlay olmaydi, shu bois "
    "paketli darvoza fail-closed tomonda yopiq turadi. Shu bois agent `watch_folder` "
    "yo'liga o'tdi: yig'uvchini OPERATOR o'z 1C sessiyasida ishga tushiradi."
)

#: ⚠️ OPERATOR UCHUN ANIQ QADAMLAR — `notes` ga AYNAN shu ko'rinishda tushadi.
#:    Nega yo'l YOZILMAYDI: `notes` `redact.scan` darvozasidan o'tadi va absolyut yo'l butun
#:    yurish yozuvini RAD etardi. Shu bois papka YO'LI emas, papkaning KIM TOMONIDAN
#:    ko'rsatilgani aytiladi — operator uni o'z ekranida ko'radi.
WATCH_FOLDER_OPERATOR_STEPS: tuple[str, ...] = (
    "1-qadam (OPERATOR): 1C ni O'ZINGIZ oching va kerakli bazaga kiring. Kirish oynasini "
    "1C ning o'zi ko'rsatadi va agent u oynani KO'RMAYDI.",
    f"2-qadam (OPERATOR): faqat-o'qish yig'uvchisini ishga tushiring. Manbasi "
    f"`{COLLECTOR_SOURCE_FILE}`, chaqiriladigan eksport funksiyasi "
    f"`{COLLECTOR_ENTRY_POINT}(<chiqish papkasi>)`. ⚠️ Tayyor `.epf` repoda YO'Q — "
    f"yig'uvchi Konfiguratorda yig'iladi.",
    f"3-qadam (OPERATOR): chiqish papkasi sifatida AGENT KUZATAYOTGAN papkani ko'rsating — "
    f"bu agentga `--headless` bilan berilgan (yoki oynada tanlangan) papka. Papkaning yo'li "
    f"bu matnda ATAYLAB yozilmaydi; u operator ekranida turadi.",
    f"4-qadam (AGENT): agent shu papkani KUZATADI va yig'uvchi tugallanish belgisini "
    f"(`{MANIFEST_FILE}`) TO'LIQ yozguncha kutadi. Yarim yozilgan fayl «tayyor» deb "
    f"hisoblanmaydi. Vaqt tugasa yurish {st.FAILED_TIMEOUT} bilan to'xtaydi — cheksiz "
    f"kutish YO'Q.",
)

#: ⚠️⚠️ BU YO'LDA AGENT 1C NI ISHGA TUSHIRMADI — hisobot va UI shu faktni AYNAN shu matndan
#:    oladi (brief §7). Matn «avtomatik bajarildi» ma'nosini BERMAYDI va bermasligi testda
#:    qulflangan.
OPERATOR_RAN_COLLECTOR_NOTE = (
    "Yo'l `watch_folder`: yig'uvchini OPERATOR qo'lda ishga tushirdi, agent esa faqat chiqish "
    "papkasini kuzatdi. Agent 1C ni ishga TUSHIRMADI, birorta buyruq bajarMADI va shu bois "
    "bu yurish AVTOMATIK razvedka EMAS."
)

#: ⚠️ BU YO'LNING ISBOTLAB BO'LMAYDIGAN JOYI, ochiq yoziladi: agent papkadagi paketning
#:    AYNI SHU YURISH uchun yozilganini isbotlay olmaydi (jarayon uning qo'lida emas, chiqish
#:    kodi ham yo'q). Paketli yo'lda bu bo'sh papka talabi bilan to'siladi, bu yerda esa
#:    papkani operator KO'RSATADI va unda eski paket turgan bo'lishi MUMKIN.
WATCH_FOLDER_PROVENANCE_NOTE = (
    "⚠️ Bu yo'lda agent paketning AYNI SHU YURISH uchun yozilganini ISBOTLAY OLMAYDI: "
    "jarayon agentning qo'lida emas, demak chiqish kodi ham yo'q. Papkada oldingi yurishdan "
    "qolgan paket turgan bo'lsa, agent uni shu yurishning natijasi deb o'qiydi. Keyingi "
    "qadam: har yurish uchun TOZA papka ko'rsating."
)

#: ⚠️ `notes` ga tushadigan TAKLIF matni. Unda YO'L ham, sir ham YO'Q (notes `redact.scan`
#: darvozasidan o'tadi), lekin KEYINGI QADAM bor — faqat «yiqildi» deydigan izoh operatorni
#: qo'ng'iroq qilishga majbur qilardi.
WATCH_FOLDER_SUGGESTION = (
    "Paketli yo'l (`batch_execute`) boshlanmadi. Keyingi qadam: yig'uvchi faylni O'Z 1C "
    "sessiyangizda bir marta ochib bajaring — kirish oynasini 1C ning o'zi ko'rsatadi va "
    "agent sirni ko'rmaydi; agent esa chiqish papkasini kuzatib quvurni davom ettiradi "
    "(`watch_folder` yo'li)."
)

#: ⚠️⚠️ QAYSI QUVUR HOLATIDAN qaysi `state_hint` ga O'TISH MUMKIN.
#:    Sabab (Phase 4 darsi: kalit nomlari OLDIN belgilanadi): `states.TRANSITIONS` har bir
#:    yiqilishni FAQAT o'z joyidan ruxsat etadi — `FAILED_NO_1C` faqat `ENVIRONMENT_SCAN`
#:    dan, `FAILED_NO_TARGET` faqat `TARGET_SELECTION` dan, `FAILED_SAFETY` faqat
#:    `SAFETY_CHECK` dan. Ko'prik esa ANIQ sababni biladi, demak «qulay» umumiy holatga
#:    siltab yuborish ma'lumot yo'qotardi. Shu bois ko'prik ANIQ sababni qaytaradi va SHU
#:    JADVAL quvurga «bu sababni qaysi holatdan yozish kerak» deb aytadi: darvozalarni
#:    (`preflight`) quvur ERTA, o'z holatida chaqiradi, `collect` ni esa
#:    `METADATA_DISCOVERY` da.
#: ⚠️ Jadval import paytida `states.can_transition` bilan TEKSHIRILADI (fayl oxiriga qarang),
#:    ya'ni u hech qachon holat mashinasidan ajralib ketmaydi.
HINT_SOURCE_STATE: dict[str, str] = {
    st.FAILED_NO_1C: st.ENVIRONMENT_SCAN,
    st.FAILED_NO_TARGET: st.TARGET_SELECTION,
    st.FAILED_SAFETY: st.SAFETY_CHECK,
    st.FAILED_AUTH_REQUIRED: st.METADATA_DISCOVERY,
    st.FAILED_COLLECTOR_UNAVAILABLE: st.METADATA_DISCOVERY,
    st.FAILED_TIMEOUT: st.METADATA_DISCOVERY,
    st.FAILED_INTERNAL: st.METADATA_DISCOVERY,
}

#: Tayyorlikni o'lchash natijalari (modul ichki lug'ati).
_PROBE_MISSING = "missing"    # `manifest.json` HALI yo'q
_PROBE_PARTIAL = "partial"    # fayl bor, lekin paket to'liq emas yoki JSON parse bo'lmadi
_PROBE_PARSED = "parsed"      # hamma majburiy fayl bor va `manifest.json` parse bo'ldi

#: Standart kutish parametrlari. ⚠️ Cheksiz kutish YO'Q: brief talabi va amaliy sabab —
#: osilgan 1C sessiyasi agentni butun kechaga qoldirardi.
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_SECONDS = 2.0

#: ⚠️ Ishlab chiqarishda uzatiladigan soat. Modul «hozir»ni O'ZI olmaydi (pastdagi `collect`
#: ga qarang) — chaqiruvchi SHU qiymatni beradi, test esa soxta soatni.
DEFAULT_CLOCK: Callable[[], float] = time.monotonic
DEFAULT_SLEEPER: Callable[[float], None] = time.sleep


class BridgeError(ValueError):
    """Ko'prik shartnomasi buzildi: xavfsiz bo'lmagan argument, taqiqlangan kalit, buzuq reja.

    ⚠️ Bu ISTISNO `collect` dan CHIQMAYDI: u yerda ushlanib ANIQ yiqilish holatiga
    (`state_hint`) aylanadi. Istisno `build_command` ni TO'G'RIDAN chaqirgan kodga qaytadi,
    chunki u sof funksiya va u buyruqni «yarim xavfsiz» qaytarmasligi kerak.
    """


# ══════════════════════════════════════════════════════════════════════════════════════════
# KIRISH va CHIQISH TUZILMALARI
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CollectPlan:
    """Yig'ish REJASI — ko'prikka beriladigan HAMMA narsa.

    ⚠️⚠️ KREDENSIAL MAYDONI ATAYLAB YO'Q: na `password`, na `user`, na `connect_string`.
         «Maydon bor, lekin bo'sh qoldiramiz» yo'li yaramaydi — bir kun kimdir uni to'ldiradi.
         Parol kerak bo'lsa yo'l UMUMAN boshlanmaydi (`FAILED_AUTH_REQUIRED`).
    ⚠️ `requires_auth` aniqlovchidan AYNI holda ko'chadi (`"true"`/`"false"`/`"unknown"`) va
       faqat `"false"` paketli yo'lni ochadi.
    ⚠️ `route=None` — «ko'prik o'zi tanlasin»: PRIMARY dan boshlanadi. Aniq qiymat berilsa
       u HURMAT qilinadi, LEKIN xavfsizlik darvozalari (parol, argument) baribir ishlaydi —
       argument bilan ularni chetlab o'tish yo'li YO'Q.
    """

    epf_path: str
    output_dir: str
    exe_path: str | None = None
    infobase_kind: str | None = None
    infobase_locator: str | None = None
    #: ⚠️⚠️ MUHIT SKANERINING HUKMI (`detector.EnvironmentScan.presence_verdict`). Bu maydon
    #: ko'prikka «1C bor-yo'qligini KIM aytdi» degan savolga javob beradi: `exe_path` ning
    #: fayl emasligi O'ZICHA 1C yo'qligini ISBOTLAMAYDI (yo'l eskirgan ham bo'lishi mumkin,
    #: manba esa umuman o'qilmagan bo'lishi mumkin). DEFAULT — `unknown`: hukm berilmaganda
    #: ko'prik «isbotlangan yo'qlik» DA'VO QILMAYDI (fail-closed).
    presence_verdict: str = PRESENCE_UNKNOWN
    requires_auth: str = "unknown"
    mode: str = MODE_METADATA_ONLY
    route: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS


@dataclass(frozen=True)
class WatchPlan:
    """KUZATISH rejasi — `watch_folder` yo'lining NORMAL (shipped) oqimi.

    ⚠️⚠️ NEGA `CollectPlan` DAN AJRATILGAN (va nega unga maydon QO'SHILMADI): `CollectPlan`
         1C NI ISHGA TUSHIRISH rejasi — unda `.epf`, `1cv8.exe` yo'li, baza lokatori va
         tasdiq talabi bor. Bu yo'lda ularning BIRORTASI YO'Q: agent hech narsa ishga
         tushirmaydi. `CollectPlan` ni shu yo'lga majburlash uchun soxta `.epf` yo'li
         yozishga to'g'ri kelardi — ya'ni YOZUVGA YOLG'ON kiritish, va aynan shu naqsh
         Phase 4 da «paket olindi» degan yolg'on SUCCESS bergan edi.
    ⚠️ `bundle_dir` BO'SH bo'lishi NORMAL: yig'uvchi hali yozmagan bo'lishi mumkin va
       kutishning MA'NOSI aynan shu. Paketli yo'lning «papka bo'sh bo'lsin» talabi esa bu
       yerda AKSINCHA ishlaydi (papkada tayyor paket turishi mumkin), shu bois bu yo'l
       paketning YANGILIGINI isbotlay olmaydi — `WATCH_FOLDER_PROVENANCE_NOTE` shuni ochiq
       aytadi.
    ⚠️ KREDENSIAL MAYDONI BU YERDA HAM YO'Q va bo'lmaydi: parolni 1C ning O'Z oynasi oladi.
    """

    bundle_dir: str
    mode: str = MODE_METADATA_ONLY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS


@dataclass(frozen=True)
class WaitTick:
    """BITTA kutish o'lchovi — «hali tayyor emas» degan FAKT, progress uchun.

    ⚠️ NEGA KERAK: papka bo'sh bo'lsa agent jim turardi va operator oynani «osilgan» deb
       o'qirdi. Bu yozuv kutish KO'RINISHINI beradi va yangi HOLAT yaratmaydi — holat
       `METADATA_DISCOVERY` bo'lib qoladi (yangi parallel lug'at TAQIQ).
    ⚠️ `elapsed_seconds` — Python soni va u HUJJATGA YOZILMAYDI. Hujjatga tushadigan har
       qanday sanoq MATN bo'lishi kerak; shu bois bu qiymat faqat EKRANGA chiqadi
       (`human()`), yurish yozuviga esa KUTISHNING O'ZI izoh bo'lib tushadi.
    ⚠️ `missing` — `runtime_bundle.REQUIRED_FILES` nomlari: ular SHARTNOMA, sir emas.
    """

    elapsed_seconds: float
    probe: str
    missing: tuple[str, ...]

    def human(self) -> str:
        """Operator ekranidagi bitta qator. ⚠️ Yo'l YOZILMAYDI (sir bo'lishi mumkin)."""
        qolgan = (f"yetishmagan majburiy fayl: {list(self.missing)}" if self.missing
                  else f"`{MANIFEST_FILE}` hali to'liq yozilmadi")
        return (f"kutilmoqda: yig'uvchining chiqishi hali TAYYOR emas ({qolgan}); "
                f"o'tgan vaqt {self.elapsed_seconds:.0f} s")


@dataclass(frozen=True)
class RunOutcome:
    """Jarayon yurishining natijasi — `subprocess` dan AJRATILGAN shakl.

    ⚠️ Ajratilgani uchun testda soxta yurituvchi beriladi va HAQIQIY `1cv8.exe` hech qachon
    ishga tushmaydi (u bu mashinada yo'q ham).
    ⚠️ `exit_code` `None` bo'lishi mumkin: jarayon umuman boshlanmadi yoki vaqti tugadi.
    """

    exit_code: int | None
    timed_out: bool = False
    detail: str = ""


@dataclass(frozen=True)
class BridgeResult:
    """Ko'prik natijasi.

    ⚠️ `bundle_dir` FAQAT `ok=True` da to'ladi. Yarim yozilgan yoki bo'sh papkani «paket» deb
       uzatish — Phase 4 da yolg'on SUCCESS bergan aynan shu nuqson: validator keyin uni
       baribir rad etardi, lekin hisobotda «paket olindi» deb qolardi.
    ⚠️ `exit_code` — INT (yoki `None`), chunki bu Python qiymati. Hujjatga (`agent_status`,
       `discovery_report.md`) yozilganda u MATNGA aylantirilishi kerak: JSON'da sanoq matn.
    ⚠️ `state_hint` — `states.py` dagi yiqilish holati NOMI. Ko'prik holatni O'ZI
       o'zgartirmaydi: o'tishni quvur `status.AgentStatus.advance()` bilan qiladi, shu bois
       ruxsat etilgan o'tishlar darvozasi bitta joyda qoladi.
    """

    route: str
    ok: bool
    bundle_dir: str | None = None
    exit_code: int | None = None
    state_hint: str | None = None
    errors: tuple[AgentError, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def exit_code_text(self) -> str | None:
        """Hujjatga yozish uchun MATN shakli (`None` — `null` bo'lib qoladi)."""
        return None if self.exit_code is None else str(self.exit_code)

    def __post_init__(self) -> None:
        # ⚠️ IMPORT PAYTIDAGI EMAS, OBYEKT PAYTIDAGI darvoza: `state_hint` faqat HAQIQIY
        #    yiqilish nomi bo'lsin. O'ylab topilgan nom quvurda `TransitionError` bo'lib
        #    chiqardi — lekin ALLAQACHON hisobotga yozilgandan keyin.
        if self.route not in ROUTES:
            raise BridgeError(f"route {sorted(ROUTES)} dan biri bo'lishi kerak: {self.route!r}")
        # ⚠️ `states.is_failure` noma'lum nomda O'Z istisnosini tashlaydi; bu yerda esa
        #    shartnoma buzilishi HAR DOIM `BridgeError` bo'lishi kerak, shu bois ro'yxatga
        #    TO'G'RIDAN qaraladi.
        if self.state_hint is not None and self.state_hint not in st.FAILURE_STATES:
            raise BridgeError(f"state_hint yiqilish holati bo'lishi kerak: {self.state_hint!r}")
        if self.ok and self.state_hint is not None:
            raise BridgeError("ok=True bo'lsa state_hint bo'lmaydi")
        if not self.ok and self.state_hint is None:
            raise BridgeError("ok=False bo'lsa ANIQ state_hint SHART — jimgina yiqilish YO'Q")
        if self.ok and not self.bundle_dir:
            raise BridgeError("ok=True bo'lsa bundle_dir SHART")
        if not self.ok and self.bundle_dir:
            raise BridgeError("ok=False bo'lsa bundle_dir bo'sh qoladi (yarim paket uzatilmaydi)")


class Runner(Protocol):
    """1C ni ishga tushiruvchi. ⚠️ Testda almashtiriladi — shu bois HAQIQIY 1C kerak emas."""

    def __call__(self, command: tuple[str, ...], timeout_seconds: float) -> RunOutcome:
        ...


# ══════════════════════════════════════════════════════════════════════════════════════════
# BUYRUQ SATRI — SOF FUNKSIYA
# ══════════════════════════════════════════════════════════════════════════════════════════
def build_command(plan: CollectPlan) -> tuple[str, ...]:
    """`1cv8.exe ENTERPRISE /F<baza> /Execute <epf> /C<params>` — YON TA'SIRSIZ.

    ⚠️ NEGA SOF: 1C bo'lmagan mashinada ham buyruq satri TEST bilan qulflanishi kerak. Fayl
       tekshirmaydi, jarayon ochmaydi, vaqt olmaydi — faqat matn quradi.
    ⚠️ `/C<params>` ichida FAQAT CHIQISH PAPKASI boradi. Sabab: paketli rejimda `/C` satrini
       faqat BSL o'qiy oladi, mavjud minimal talab esa aynan «chiqish papkasini (va faqat
       uni) o'qib razvedkani boshlash». Rejimni ham shu satrga tiqish shartnomani O'YLAB
       CHIQARISH bo'lardi, zond ro'yxatini esa — undan ham kattasi.
    ⚠️ FAQAT FAYL bazasi (`/F`). Server bazasining paketli shakli (`/S`) bu yerda TEKSHIRIB
       BO'LMAYDI (1C yo'q), shu bois u O'YLAB CHIQARILMAYDI: server nishoni uchun ko'prik
       `watch_folder` ni taklif qiladi.
    ⚠️ Parol/foydalanuvchi kaliti QO'SHILMAYDI va chiqish `_assert_no_credentials` dan
       o'tadi.
    """
    if not isinstance(plan, CollectPlan):
        raise BridgeError("plan `CollectPlan` bo'lishi kerak")
    exe = _safe_arg(plan.exe_path, "exe_path")
    epf = _safe_arg(plan.epf_path, "epf_path")
    out = _safe_arg(plan.output_dir, "output_dir")
    locator = _safe_arg(plan.infobase_locator, "infobase_locator")
    if plan.infobase_kind != KIND_FILE:
        raise BridgeError(
            f"paketli buyruq FAQAT fayl bazasi uchun quriladi ({KIND_FILE!r}); kelgani "
            f"{plan.infobase_kind!r} — server bazasining paketli shakli bu yerda tekshirib "
            f"bo'lmaydi, shu bois o'ylab chiqarilmaydi"
        )
    command = (exe, VERB_ENTERPRISE, f"{SWITCH_FILE_BASE}{locator}",
               SWITCH_EXECUTE, epf, f"{SWITCH_PARAMS}{out}")
    _assert_no_credentials(command)
    return command


def _safe_arg(value, where: str) -> str:
    """Argument sifatida ruxsat etilgan matn (aks holda `BridgeError`).

    ⚠️ Xato matnida QIYMATNING O'ZI ko'rsatilmaydi — faqat BELGI nomi: xabar jurnalga
    tushadi, yo'l esa sir bo'lishi mumkin (`redact` yo'lni `[REDACTED]` qiladi).
    """
    if not isinstance(value, str) or value.strip() == "":
        raise BridgeError(f"{where}: bo'sh bo'lmagan matn bo'lishi kerak")
    for ch in FORBIDDEN_ARG_CHARS:
        if ch in value:
            raise BridgeError(
                f"{where}: argumentda ruxsat etilmagan belgi {ch!r} bor — buyruq qurilmaydi "
                f"(qiymat ataylab ko'rsatilmayapti). Keyingi qadam: papkani/faylni shu "
                f"belgisiz nomga ko'chiring"
            )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise BridgeError(f"{where}: argumentda boshqaruv belgisi bor — buyruq qurilmaydi")
    return value


def _assert_no_credentials(command: tuple[str, ...]) -> None:
    """⚠️ PAROL DARVOZASI: `/P...`/`/N...` ko'ringan zahoti ISTISNO.

    Bu tekshiruv «hozir kerak emas», chunki hech bir joy bu kalitlarni qo'shmaydi. U
    KELAJAK uchun: kimdir bir kun «parolni ham uzatamiz-da» deb qo'shsa, test yiqilishidan
    oldin KOD o'zi yiqiladi.
    """
    for token in command:
        if not token.startswith("/"):
            continue
        upper = token.upper()
        for taqiq in FORBIDDEN_SWITCHES:
            if upper.startswith(taqiq.upper()):
                raise BridgeError(
                    f"{taqiq} kaliti TAQIQLANGAN: kredensial buyruq satrida jarayon "
                    f"ro'yxatida ko'rinib qoladi. Parol kerak bo'lsa yo'l umuman "
                    f"boshlanmaydi ({st.FAILED_AUTH_REQUIRED})"
                )


# ══════════════════════════════════════════════════════════════════════════════════════════
# JARAYONNI ISHGA TUSHIRISH (yagona `subprocess` joyi)
# ══════════════════════════════════════════════════════════════════════════════════════════
def run_1c_batch(command: tuple[str, ...], timeout_seconds: float) -> RunOutcome:
    """`1cv8.exe` ni paketli rejimda ishga tushiradi.

    ⚠️ `shell` ATAYLAB `False` (va boshqa qiymat bu modulda hech qachon berilmaydi): buyruq
       `list` bo'lib uzatiladi, demak qobiq metabelgilari talqin qilinmaydi.
    ⚠️ `stdout`/`stderr` — `DEVNULL`: 1C xato matnida ulanish satrini chiqarishi mumkin,
       u esa jurnalga tushib sirni oshkor qilardi. Diagnostika paketning `errors.json` idan.
    ⚠️ BU FUNKSIYA BU MASHINADA BAJARILMAGAN (`1cv8.exe` yo'q) va testlar uni soxta
       yurituvchi bilan almashtiradi — chaqiruv SHAKLI tekshiriladi, 1C xulqi EMAS.
    """
    try:
        completed = subprocess.run(
            list(command),
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunOutcome(exit_code=None, timed_out=True,
                          detail="jarayon ajratilgan vaqtda tugamadi")
    except OSError as e:
        # ⚠️ Istisno MATNI ko'chirilmaydi: unda yo'l bo'ladi. Faqat TURI yoziladi.
        return RunOutcome(exit_code=None, timed_out=False,
                          detail=f"jarayon ishga tushmadi: {type(e).__name__}")
    return RunOutcome(exit_code=int(completed.returncode), timed_out=False, detail="")


# ══════════════════════════════════════════════════════════════════════════════════════════
# TAYYORLIK ISBOTI
# ══════════════════════════════════════════════════════════════════════════════════════════
def _probe_bundle(output_dir: str, *,
                  require_all_files: bool = True) -> tuple[str, int | None, tuple[str, ...]]:
    """`(holat, manifest hajmi, yetishmagan majburiy fayllar)`.

    ⚠️⚠️ `require_all_files=False` — FAQAT shipped `watch` oqimi uchun (pastdagi `watch`
         docstringiga qarang): tugallanish belgisi TO'LIQ bo'lsa paket TAYYOR deb beriladi,
         majburiy fayl yetishmasa esa buni VALIDATOR aytadi. Sabab qisqa: «yig'uvchi
         tugatdi, lekin chiqishi to'liq emas» — bu KUTISH bilan tuzalmaydigan ANIQ javob va
         uni `WAIT_TIMEOUT` deb atash sababni ALMASHTIRARDI; bundan tashqari paket
         uzatilmagani uchun BUZUQ PAKET DALIL bo'lib ham saqlanmasdi.

    ⚠️⚠️ TUGALLANISH BELGISI — `manifest.json`. Phase 4 da u ENG OXIRIDA yoziladi, ya'ni
         «hammasi yozildi» degan yagona ishonchli belgi. LEKIN FAYL BORLIGI YETMAYDI:
         yarim yozilgan faylni «tayyor» deb hisoblash aynan Phase 4 da yolg'on SUCCESS
         bergan nuqson edi. Shu bois to'rt shart birgalikda talab qiladi:
           1) olti majburiy fayl HAMMASI bor;
           2) `manifest.json` JSON bo'lib PARSE bo'ladi (va ildizi obyekt);
           3) hujjat MINIMAL SHAKLDA (pastdagi `_manifest_minimal_shape` — CHEGARASI bilan);
           4) hajmi IKKI o'lchov orasida O'ZGARMAYDI (barqarorlik — `_wait_until_ready` da).
    ⚠️ TO'LIQ SXEMA TEKSHIRILMAYDI: paketning mazmuni `runtime_bundle.validate_runtime_bundle`
       ishi va u ALOHIDA holatda (`VALIDATION`) chaqiriladi. Bu yerda sxemani qayta
       tekshirish ikki validator yasardi va ular bir kun ajralib ketardi.
    """
    missing = tuple(n for n in REQUIRED_FILES
                    if not os.path.isfile(os.path.join(output_dir, n)))
    manifest = os.path.join(output_dir, MANIFEST_FILE)
    if not os.path.isfile(manifest):
        return _PROBE_MISSING, None, missing
    try:
        raw = _read_bytes(manifest)
    except OSError:
        # ⚠️ O'qilmadi — bu «yo'q» EMAS: yozuvchi faylni hali ushlab turgan bo'lishi mumkin.
        return _PROBE_PARTIAL, None, missing
    size = len(raw)
    if missing and require_all_files:
        return _PROBE_PARTIAL, size, missing
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw   # 1C/PowerShell BOM
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _PROBE_PARTIAL, size, missing
    if not isinstance(doc, dict):
        return _PROBE_PARTIAL, size, missing
    if not _manifest_minimal_shape(doc):
        # ⚠️⚠️ TUZATILGAN NUQSON: avval shu shox UMUMAN yo'q edi va IKKI BAYTLIK `{}` ham
        #    «tayyor» bo'lib o'tib ketardi — ya'ni operator hujjatidagi («yarim yozilgan
        #    fayl tayyor deb hisoblanmaydi») KAFOLAT YOLG'ON bo'lardi.
        return _PROBE_PARTIAL, size, missing
    # ⚠️ `missing` QAYTARILADI (tashlanmaydi) — chaqiruvchi tayyor paketda ham nima
    #    yetishmaganini biladi va bu izohga tushadi; HUKMNI esa validator chiqaradi.
    return _PROBE_PARSED, size, missing


def _manifest_minimal_shape(doc: dict) -> bool:
    """«YOZISH TUGADIMI» signalining MINIMAL SHAKLI — AYNAN IKKI shart, uchinchisi YO'Q.

    ⚠️⚠️ CHEGARA ANIQ VA ATAYLAB TOR. Tekshiriladigan narsa:
           1) `manifest_version` AYNAN `MANIFEST_VERSION` (boshqa hujjat ham, kesilgan satr
              ham, `null` ham o'tmaydi);
           2) `files` — BO'SH BO'LMAGAN ro'yxat (Phase 4 yozuvchisi paketdagi har bir faylni
              shu ro'yxatga qo'yadi, demak bo'sh ro'yxat «yozish hali tugamagan» degani).
         TekshirilMAYDIGAN narsa — QOLGAN HAMMASI: `files[]` qatorlarining kalitlari, `bytes`
         ning shakli, `sha256` ning uzunligi, `notes`, fayl nomlarining shartnomada borligi,
         takror nomlar, taqiqlangan provenans maydonlari va manifestning papka bilan mosligi.
         ⚠️ NEGA: bu FAQAT «yozish TUGADIMI» signali. To'liq hukmni
            `runtime_bundle.validate_runtime_bundle` chiqaradi va u ko'prikdan KEYIN, ALOHIDA
            holatda (`VALIDATION`) chaqiriladi. Shu ikki shartdan ko'pini bu yerga olib kirish
            IKKINCHI VALIDATOR yasardi va ikkisi bir kun ajralib ketardi — aynan shu bois
            buzuq (lekin TO'LIQ yozilgan) paket bu darvozadan O'TADI va DALIL bo'lib saqlanadi.
    ⚠️ Yolg'on ijobiy xavfi test bilan qulflangan: HAQIQIY to'liq manifest (Phase 4 ning O'Z
       yozuvchisidan) bu darvozadan O'TISHI SHART
       (`test_HAQIQIY_TOLIQ_manifest_QABUL_QILINADI`).
    """
    if doc.get("manifest_version") != MANIFEST_VERSION:
        return False
    rows = doc.get("files")
    return isinstance(rows, list) and bool(rows)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _wait_until_ready(output_dir: str, *, clock: Callable[[], float],
                      sleeper: Callable[[float], None], timeout_seconds: float,
                      poll_seconds: float, wait_for_appearance: bool,
                      on_wait: Callable[[WaitTick], None] | None = None,
                      require_all_files: bool = True,
                      ) -> tuple[bool, str, tuple[str, ...]]:
    """Paket TO'LIQ yozilgunicha kutadi. `(tayyormi, kod, yetishmagan fayllar)`.

    ⚠️ VAQT KIRISHDAN: `clock` va `sleeper` parametr — modul «hozir»ni o'zi olmaydi, shu
       bois test soxta soat bilan haqiqiy kutmasdan yuradi (va to'plam tez qoladi).
    ⚠️ `wait_for_appearance=False` — PAKETLI yo'l: jarayon ALLAQACHON tugagan, demak
       `manifest.json` umuman yo'qligi KUTISH bilan tuzalmaydi va darhol
       `BUNDLE_INCOMPLETE` bo'ladi (bu yerda «BSL bo'shlig'i» ko'rinadi). Yarim yozilgan
       fayl esa OS buferi tufayli bo'lishi mumkin — unga qisqa barqarorlik kutuvi beriladi.
    ⚠️ Cheksiz kutish YO'Q: vaqt tugasa `WAIT_TIMEOUT`.
    ⚠️ `on_wait` — HAR BIR «hali tayyor emas» o'lchovida chaqiriladi (uxlashdan OLDIN).
       Sabab: kutish KO'RINISHI kerak, aks holda bo'sh papkada agent «osilgan» ko'rinadi.
       Bu chaqiruv QAROR QABUL QILMAYDI va natijaga ta'sir qilmaydi — faqat xabar beradi.
    ⚠️⚠️ IKKI MUSTAQIL CHEGARA: VAQT va O'LCHOV SONI. Sabab: `clock` KIRISHDAN keladi, demak
         u QOTIB QOLGAN bo'lishi mumkin (doim bir xil qiymat qaytaradigan soxta soat yoki
         juda qo'pol taymer). Faqat vaqtga tayangan halqa bunday soatda CHEKSIZ aylanardi —
         ya'ni «cheksiz kutish YO'Q» qoidasi soat sozligiga bog'liq bo'lib qolardi. O'lchov
         soni chegarasi shu bog'liqlikni UZADI: qotib qolgan soatda ham kutish `WAIT_TIMEOUT`
         bilan TUGAYDI. Chegara `timeout/poll` dan hisoblanadi va ikki o'lchov zaxirasi
         beriladi — ya'ni SOZ soatda u hech qachon birinchi bo'lib urmaydi va haqiqiy xulq
         O'ZGARMAYDI.
    """
    boshlandi = clock()
    oxirgi_hajm: int | None = None
    oxirgi_holat = _PROBE_MISSING
    yetishmagan: tuple[str, ...] = REQUIRED_FILES
    eng_kop_olchov = int(timeout_seconds / poll_seconds) + 2
    olchov = 0
    while True:
        holat, hajm, yetishmagan = _probe_bundle(output_dir,
                                                 require_all_files=require_all_files)
        oxirgi_holat = holat
        olchov += 1
        if holat == _PROBE_PARSED and oxirgi_hajm is not None and hajm == oxirgi_hajm:
            # ⚠️ IKKI o'lchov bir xil hajm ko'rsatdi + JSON parse bo'ldi -> TAYYOR.
            # ⚠️ `yetishmagan` TAYYOR holatda ham QAYTARILADI: `require_all_files=False` da u
            #    bo'sh bo'lmasligi mumkin va chaqiruvchi buni IZOHGA yozishi kerak — jim
            #    tashlab ketish «paket butun» degan yolg'on da'vo bo'lardi. Qat'iy rejimda
            #    u baribir bo'sh bo'ladi (aks holda bu shoxga yetib kelinmaydi).
            return True, "", yetishmagan
        if holat == _PROBE_MISSING and not wait_for_appearance:
            return False, CODE_BUNDLE_INCOMPLETE, yetishmagan
        oxirgi_hajm = hajm
        if clock() - boshlandi >= timeout_seconds or olchov >= eng_kop_olchov:
            kod = (CODE_BUNDLE_INCOMPLETE
                   if oxirgi_holat == _PROBE_PARTIAL and not wait_for_appearance
                   else CODE_WAIT_TIMEOUT)
            return False, kod, yetishmagan
        if on_wait is not None:
            on_wait(WaitTick(elapsed_seconds=clock() - boshlandi, probe=holat,
                             missing=yetishmagan))
        sleeper(poll_seconds)


# ══════════════════════════════════════════════════════════════════════════════════════════
# DARVOZALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def _shared_preflight(plan: CollectPlan, route: str) -> BridgeResult | None:
    """IKKI yo'lga ham tegishli shartlar. Yiqilsa — TAYYOR natija, aks holda `None`.

    ⚠️ `route` KIRISHDAN keladi va natijaga AYNI holda yoziladi: urinilgan yo'lni
    `plan.route` dan qayta hisoblash `None` (ya'ni «o'zi tanlasin») holatida yolg'on yo'l
    nomini yozardi — hisobotda esa «qaysi yo'l yiqildi» savoliga javob shu maydondan olinadi.

    ⚠️ TARTIB SABABLI: yo'lga BOG'LIQ BO'LMAGAN faktlar birinchi tekshiriladi, chunki ular
       IKKI yo'lni ham yiqitadi va bunda `watch_folder` ni taklif qilish ma'nosiz bo'lardi
       («o'sha faylni o'zingiz ochib ko'ring» deyish, fayl yo'q ekan).
    ⚠️ `.epf` yo'qligi — `FAILED_COLLECTOR_UNAVAILABLE`, `FAILED_NO_1C` EMAS: 1C bor-yo'qligi
       haqida bu HECH NARSA demaydi. `UNKNOWN` ni `NOT_FOUND` ga aylantirmaslik qoidasi.
    ⚠️ Chiqish papkasi BO'SH bo'lishi SHART: ichida eski paket qolsa, kuzatuvchi uni YANGI
       natija deb o'qib yolg'on SUCCESS berardi.
    """
    scope = f"collector:{route}"
    if not isinstance(plan.epf_path, str) or not os.path.isfile(plan.epf_path):
        return _fail(plan, st.FAILED_COLLECTOR_UNAVAILABLE, scope, CODE_EPF_MISSING,
                     "yig'uvchi fayli (`.epf`) ko'rsatilgan joyda topilmadi — demak javob "
                     "YO'Q (1C bor-yo'qligi haqida bu hech narsa demaydi). Keyingi qadam: "
                     "Konfiguratorda qurilgan yig'uvchi faylini ko'rsating", route=route)
    if not isinstance(plan.output_dir, str) or not os.path.isdir(plan.output_dir):
        return _fail(plan, st.FAILED_SAFETY, scope, CODE_OUTPUT_DIR_MISSING,
                     "chiqish papkasi mavjud emas. Ko'prik papka YARATMAYDI (faqat-o'qish "
                     "chegarasi). Keyingi qadam: bo'sh papka tayyorlab ko'rsating",
                     route=route)
    try:
        ichida = os.listdir(plan.output_dir)
    except OSError as e:
        return _fail(plan, st.FAILED_SAFETY, scope, CODE_OUTPUT_DIR_MISSING,
                     f"chiqish papkasi o'qilmadi: {type(e).__name__}. Keyingi qadam: kirish "
                     f"huquqini tekshiring", route=route)
    if ichida:
        return _fail(plan, st.FAILED_SAFETY, scope, CODE_OUTPUT_DIR_NOT_EMPTY,
                     "chiqish papkasi BO'SH EMAS. Eski fayllar yangi natija deb o'qilib "
                     "ketishi mumkin, shu bois quvur to'xtatildi va hech narsa "
                     "o'zgartirilmadi. Keyingi qadam: bo'sh papka ko'rsating", route=route)
    if plan.mode not in MODES:
        return _fail(plan, st.FAILED_INTERNAL, scope, CODE_BAD_PLAN,
                     "rejada noma'lum rejim ko'rsatilgan — bu agentning nuqsoni, muhit "
                     "muammosi emas", route=route)
    if plan.timeout_seconds <= 0 or plan.poll_seconds <= 0:
        return _fail(plan, st.FAILED_INTERNAL, scope, CODE_BAD_PLAN,
                     "kutish yoki so'rov oralig'i musbat bo'lishi kerak — bu agentning "
                     "nuqsoni", route=route)
    return None


def _batch_preflight(plan: CollectPlan) -> BridgeResult | None:
    """PAKETLI yo'lning O'Z darvozalari. Yiqilsa `watch_folder` TAKLIF qilinadi.

    ⚠️ Birinchi darvoza `presence_verdict` ni HISOBGA OLADI: fayl yo'qligi 1C yo'qligini
       ISBOTLAMAYDI, shu bois sabab matni hukmga qarab o'zgaradi va hukm `unknown` bo'lsa
       paket «isbotlangan yo'qlik» DA'VO QILMAYDI.
    ⚠️ Parol darvozasi (`requires_auth != "false"`) kodda IKKI joyda turadi: bu yerda
       (yo'l boshlanmaydi) va `_assert_no_credentials` da (buyruqqa kalit tushmaydi). Ikki
       qatlam ataylab: birinchisi QAROR, ikkinchisi KELAJAKDAGI TAHRIRdan himoya.
    """
    scope = f"collector:{ROUTE_BATCH_EXECUTE}"
    if not isinstance(plan.exe_path, str) or not os.path.isfile(plan.exe_path):
        # ⚠️⚠️ TUZATILGAN NUQSON: avval bu darvoza FAQAT faylning yo'qligiga qarab
        #    `FAILED_NO_1C` ni chiqarardi va `presence_verdict` ga UMUMAN qaramasdi — ya'ni
        #    reestrni O'QIY OLMAGAN mashinada ham paket «1C o'rnatilmagan» degan ISBOTLANGAN
        #    yo'qlikni da'vo qilardi. `UNKNOWN` ni `NOT_FOUND` ga aylantirish — bu quvurning
        #    eng qimmat xatosi, shu bois sabab matni HUKMGA bog'liq.
        # ⚠️ YANGI HOLAT QO'SHILMAYDI (`FAILED_1C_UNKNOWN` kabi): `absent` va `unknown`
        #    ikkisi ham `FAILED_NO_1C` («yaroqli 1C bo'lmagani uchun davom eta olmadim»),
        #    ajrim esa `agent_status.presence_verdict` da va ma'no matnida ko'rinadi.
        if plan.presence_verdict == PRESENCE_FOUND:
            # ⚠️ Hukm «topildi», ijro fayli esa joyida emas — bu 1C ning YO'QLIGI haqidagi
            #    da'vo EMAS: javob YO'Q. Shu bois holat `FAILED_COLLECTOR_UNAVAILABLE`.
            return _fail(plan, st.FAILED_COLLECTOR_UNAVAILABLE, scope, CODE_EXE_MISSING,
                         "muhit skaneri 1C ni TOPDI, lekin paketli yo'l uchun ko'rsatilgan "
                         "ijro fayli joyida emas — ya'ni javob YO'Q («1C o'rnatilmagan» "
                         "DEGANI EMAS). Keyingi qadam: 1C ni bir marta qo'lda ochib, "
                         "o'rnatmaning haqiqiy joyini tekshiring",
                         route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
        if plan.presence_verdict == PRESENCE_ABSENT:
            return _fail(plan, st.FAILED_NO_1C, scope, CODE_EXE_MISSING,
                         "muhit skanerining hukmi: hamma manba o'qildi va 1C TOPILMADI; "
                         "paketli yo'l uchun ijro fayli ham yo'q. Keyingi qadam: 1C "
                         "o'rnatilgan kompyuterda ishga tushiring",
                         route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
        return _fail(plan, st.FAILED_NO_1C, scope, CODE_EXE_MISSING,
                     "paketli yo'l uchun 1C ijro fayli ko'rsatilgan joyda topilmadi, 1C "
                     "holati esa NOMA'LUM (manba o'qilmadi) — shu bois bu paket «1C "
                     "o'rnatilmagan» deb DA'VO QILMAYDI. Keyingi qadam: agentni 1C ni ko'ra "
                     "oladigan hisobdan qayta yurgizing",
                     route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
    if not plan.infobase_locator or not str(plan.infobase_locator).strip():
        return _fail(plan, st.FAILED_NO_TARGET, scope, CODE_NO_TARGET,
                     "nishon ma'lumot bazasi tanlanmagan. Keyingi qadam: 1C ni bir marta "
                     "qo'lda ochib kerakli bazani ro'yxatga qo'shing",
                     route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
    if plan.requires_auth != TRI_FALSE:
        # ⚠️ `"unknown"` HAM to'xtatadi: fail-closed. Aniqlovchi `requires_auth` ni hech
        #    qachon `"false"` qilmaydi (parolsizlikni ulanmasdan isbotlab bo'lmaydi), demak
        #    amalda bu darvoza faqat OPERATOR tasdig'i bilan ochiladi.
        return _fail(plan, st.FAILED_AUTH_REQUIRED, scope, CODE_AUTH_REQUIRED,
                     "bazaga kirish uchun foydalanuvchi tasdig'i kerak yoki kerakligi "
                     "NOMA'LUM. Agent sirni buyruq satriga qo'ymaydi (u jarayon ro'yxatida "
                     "ko'rinadi), shu bois paketli yo'l boshlanmadi",
                     route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
    if plan.infobase_kind != KIND_FILE:
        return _fail(plan, st.FAILED_COLLECTOR_UNAVAILABLE, scope,
                     CODE_SERVER_TARGET_UNSUPPORTED,
                     f"nishon fayl bazasi emas ({KIND_SERVER!r} yoki noma'lum tur). Server "
                     f"bazasining paketli chaqiruv shakli tekshirib bo'lmagan, shu bois u "
                     f"o'ylab chiqarilmaydi",
                     route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
    if plan.mode != MODE_METADATA_ONLY:
        # ⚠️ Paketli parametr satri FAQAT chiqish papkasini uzatadi (`build_command` ga
        #    qarang), demak tasdiqlangan zond RO'YXATINI u BERA OLMAYDI. Zondlar kerak
        #    bo'lsa — `watch_folder`. Bu qobiliyat chegarasi, yashirilmaydi.
        return _fail(plan, st.FAILED_COLLECTOR_UNAVAILABLE, scope, CODE_MODE_UNSUPPORTED,
                     "tasdiqlangan zondlar rejimi paketli yo'l bilan uzatilmaydi: paketli "
                     "parametr satri faqat chiqish papkasini tashiydi",
                     route=ROUTE_BATCH_EXECUTE, suggest_watch=True)
    return None


def _fail(plan: CollectPlan, state_hint: str, scope: str, code: str, detail: str, *,
          route: str | None = None, suggest_watch: bool = False) -> BridgeResult:
    """Yiqilish natijasi. ⚠️ `detail` ga XOM yo'l QO'SHILMAYDI — yorliq va sabab yoziladi.

    Sababi: bu yozuvlar `agent_status.json` ga ko'chadi, u esa yozilishdan oldin
    `redact.scan` dan o'tadi — yo'l yozgan matn butun faylni RAD etardi.
    """
    yol = route or plan.route or ROUTE_WATCH_FOLDER
    notes = (WATCH_FOLDER_SUGGESTION,) if suggest_watch else ()
    return BridgeResult(route=yol, ok=False, state_hint=state_hint, exit_code=None,
                        errors=(AgentError(scope, code, detail),), notes=notes)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YAGONA INTERFEYS
# ══════════════════════════════════════════════════════════════════════════════════════════
def preflight(plan: CollectPlan) -> BridgeResult | None:
    """HAMMA darvoza, jarayon ISHGA TUSHIRILMASDAN. Yiqilsa natija, aks holda `None`.

    ⚠️ NEGA OCHIQ (public): yiqilish sabablari quvurning HAR XIL holatlariga tegishli
       (`HINT_SOURCE_STATE`), `collect` esa `METADATA_DISCOVERY` da chaqiriladi. Quvur shu
       funksiyani ERTA chaqirib, sababni O'Z holatidan yozishi mumkin — shunda aniqlik ham,
       ruxsat etilgan o'tishlar darvozasi ham buzilmaydi.
    ⚠️ Fayl tizimini O'QIYDI (mavjudlik, papka bo'shligi), lekin HECH NARSA yozmaydi va
       jarayon ochmaydi.
    """
    route = plan.route or ROUTE_BATCH_EXECUTE
    if route not in ROUTES:
        return BridgeResult(
            route=ROUTE_WATCH_FOLDER, ok=False, state_hint=st.FAILED_INTERNAL,
            errors=(AgentError("collector:plan", CODE_BAD_PLAN,
                               "rejada noma'lum yo'l ko'rsatilgan — bu agentning nuqsoni"),),
        )
    yiqildi = _shared_preflight(plan, route)
    if yiqildi is not None:
        return yiqildi
    if route == ROUTE_BATCH_EXECUTE:
        return _batch_preflight(plan)
    return None


def collect(plan: CollectPlan, *, clock: Callable[[], float],
            sleeper: Callable[[float], None] = DEFAULT_SLEEPER,
            runner: Runner | None = None) -> BridgeResult:
    """Paketni OLIB KELADI — ikki yo'l, bitta chiqish shakli (`BridgeResult`).

    ⚠️ `clock` MAJBURIY nomli argument: modul «hozir»ni O'ZI olmaydi, aks holda bir xil
       kirish bir xil natija bermaydi va kutish mantiqini sinash uchun haqiqiy soniyalar
       kutishga to'g'ri kelardi.
    ⚠️ ISTISNO CHIQARMAYDI (`BridgeError` ni ham o'zi ushlaydi): har qanday yiqilish ANIQ
       `state_hint` bo'lib qaytadi. Jimgina o'tish ham, jimgina istisno ham YO'Q.
    ⚠️ VALIDATSIYA BU YERDA EMAS: paket mazmunini `runtime_bundle.validate_runtime_bundle`
       alohida holatda tekshiradi. Ko'prik faqat «to'liq YOZILDI» faktini isbotlaydi.
    """
    # ⚠️ Darvozalar BITTA joyda (`preflight`): ikki nusxa bir kun ajralib ketardi va
    #    `collect` zaifroq tekshiradigan yo'l bo'lib qolardi.
    yiqildi = preflight(plan)
    if yiqildi is not None:
        return yiqildi
    if (plan.route or ROUTE_BATCH_EXECUTE) == ROUTE_BATCH_EXECUTE:
        return _collect_batch(plan, clock=clock, sleeper=sleeper,
                              runner=runner or run_1c_batch)
    return _collect_watch(plan, clock=clock, sleeper=sleeper)


def _collect_batch(plan: CollectPlan, *, clock: Callable[[], float],
                   sleeper: Callable[[float], None], runner: Runner) -> BridgeResult:
    """PRIMARY yo'l. ⚠️ Nol bo'lmagan chiqish kodi — ANIQ yiqilish, jimgina o'tish YO'Q."""
    scope = f"collector:{ROUTE_BATCH_EXECUTE}"
    # ⚠️ Darvoza `collect` da ALLAQACHON o'tgan; bu takroriy chaqiruv AYNI funksiyaga
    #    (nusxa EMAS) va faqat shu uchun turadi: kimdir `_collect_batch` ni to'g'ridan
    #    chaqirsa ham 1C darvozasiz ishga tushmasin.
    yiqildi = _batch_preflight(plan)
    if yiqildi is not None:
        return yiqildi
    try:
        command = build_command(plan)
    except BridgeError as e:
        # ⚠️ Xavfsiz bo'lmagan argument — XAVFSIZLIK chegarasi, «yig'uvchi yo'q» emas.
        return _fail(plan, st.FAILED_SAFETY, scope, CODE_UNSAFE_ARGUMENT,
                     f"buyruq satri qurilmadi: {e}", route=ROUTE_BATCH_EXECUTE,
                     suggest_watch=True)
    outcome = runner(command, plan.timeout_seconds)
    if outcome.timed_out:
        return BridgeResult(
            route=ROUTE_BATCH_EXECUTE, ok=False, state_hint=st.FAILED_TIMEOUT,
            exit_code=None,
            errors=(AgentError(scope, CODE_WAIT_TIMEOUT,
                               "1C paketli yurishi ajratilgan vaqtda tugamadi va kutish "
                               "to'xtatildi; hech narsa o'zgartirilmadi"),),
            notes=(WATCH_FOLDER_SUGGESTION,),
        )
    if outcome.exit_code is None:
        return BridgeResult(
            route=ROUTE_BATCH_EXECUTE, ok=False, state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
            exit_code=None,
            errors=(AgentError(scope, CODE_LAUNCH_FAILED,
                               outcome.detail or "jarayon ishga tushmadi"),),
            notes=(WATCH_FOLDER_SUGGESTION,),
        )
    if outcome.exit_code != 0:
        # ⚠️ ANIQ YIQILISH: chiqish kodi nol emas. Papkada fayl bo'lsa ham u NATIJA deb
        #    qabul qilinmaydi — yarim yurish yarim paket qoldiradi.
        return BridgeResult(
            route=ROUTE_BATCH_EXECUTE, ok=False, state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
            exit_code=outcome.exit_code,
            errors=(AgentError(scope, CODE_EXIT_CODE_NONZERO,
                               f"1C paketli yurishi nol bo'lmagan chiqish kodi qaytardi "
                               f"({outcome.exit_code}); natija QABUL QILINMADI"),),
            notes=(WATCH_FOLDER_SUGGESTION,),
        )
    tayyor, kod, yetishmagan = _wait_until_ready(
        plan.output_dir, clock=clock, sleeper=sleeper,
        timeout_seconds=plan.timeout_seconds, poll_seconds=plan.poll_seconds,
        wait_for_appearance=False,
    )
    if not tayyor:
        return BridgeResult(
            route=ROUTE_BATCH_EXECUTE, ok=False,
            state_hint=(st.FAILED_TIMEOUT if kod == CODE_WAIT_TIMEOUT
                        else st.FAILED_COLLECTOR_UNAVAILABLE),
            exit_code=outcome.exit_code,
            errors=(AgentError(scope, kod, _incomplete_detail(yetishmagan)),),
            notes=(WATCH_FOLDER_SUGGESTION,),
        )
    return BridgeResult(route=ROUTE_BATCH_EXECUTE, ok=True, bundle_dir=plan.output_dir,
                        exit_code=outcome.exit_code,
                        notes=("paket paketli yo'l bilan olindi; mazmuni ALOHIDA "
                               "tekshiriladi",))


def _collect_watch(plan: CollectPlan, *, clock: Callable[[], float],
                   sleeper: Callable[[float], None]) -> BridgeResult:
    """FALLBACK yo'l: 1C ga UMUMAN ulanmaydi, jarayon ochmaydi — faqat papkani KUZATADI.

    ⚠️ Kredensial OQIMI UMUMAN YO'Q: parolni 1C ning O'Z oynasi oladi, ko'prik uni ko'rmaydi.
    ⚠️ `exit_code` doim `None`: bu yo'lda jarayon BIZDA emas, demak chiqish kodi ham yo'q.
       Uni `0` deb yozish «biz ishga tushirdik» degan YOLG'ON da'vo bo'lardi.
    """
    scope = f"collector:{ROUTE_WATCH_FOLDER}"
    tayyor, kod, yetishmagan = _wait_until_ready(
        plan.output_dir, clock=clock, sleeper=sleeper,
        timeout_seconds=plan.timeout_seconds, poll_seconds=plan.poll_seconds,
        wait_for_appearance=True,
    )
    if not tayyor:
        return BridgeResult(
            route=ROUTE_WATCH_FOLDER, ok=False, state_hint=st.FAILED_TIMEOUT, exit_code=None,
            errors=(AgentError(scope, kod, _incomplete_detail(yetishmagan)),),
            notes=("Keyingi qadam: 1C band bo'lmagan paytda qayta yurgizing va yig'uvchini "
                   "oxirigacha bajarilishini kutib turing.",),
        )
    return BridgeResult(route=ROUTE_WATCH_FOLDER, ok=True, bundle_dir=plan.output_dir,
                        exit_code=None,
                        notes=("paket kuzatilgan papkadan olindi; mazmuni ALOHIDA "
                               "tekshiriladi",))


# ══════════════════════════════════════════════════════════════════════════════════════════
# NORMAL `watch_folder` OQIMI — AGENT HECH NARSA ISHGA TUSHIRMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def watch_preflight(plan: WatchPlan) -> BridgeResult | None:
    """Kuzatish darvozalari. Yiqilsa TAYYOR natija, aks holda `None`.

    ⚠️⚠️ NEGA ALOHIDA DARVOZA (`_shared_preflight` EMAS): umumiy darvoza IKKI narsani
         talab qiladi — mavjud `.epf` va BO'SH chiqish papkasi. Bu yo'lda ikkisi ham
         NOTO'G'RI: `.epf` ni agent ishga tushirmaydi (operator o'z sessiyasida ochadi), va
         papkada tayyor paket TURGAN bo'lishi mumkin — aynan shuning uchun u kuzatiladi.
         Umumiy darvozani bu yo'lga majburlash «yig'uvchi fayli topilmadi» degan YOLG'ON
         sababni yozardi.
    ⚠️ BO'SH PAPKA — YIQILISH EMAS: u kutishning BOSHLANG'ICH holati (brief §6C).
    ⚠️ FAIL-CLOSED: papka ko'rsatilmagan, papka EMAS yoki O'QILMAYDI bo'lsa — darhol
       `FAILED_COLLECTOR_UNAVAILABLE`. Sabab: kutish papkani YARATMAYDI, demak kutish bu
       holatni hech qachon tuzatmaydi va soniyalarni behuda sarflash operatorni chalg'itardi.
    ⚠️ FAYL TIZIMINI FAQAT O'QIYDI: papka yaratmaydi, hech narsa yozmaydi.
    """
    if not isinstance(plan, WatchPlan):
        return BridgeResult(
            route=ROUTE_WATCH_FOLDER, ok=False, state_hint=st.FAILED_INTERNAL,
            errors=(AgentError(SCOPE_WATCH, CODE_BAD_PLAN,
                               "kuzatish rejasi `WatchPlan` bo'lishi kerak — bu agentning "
                               "nuqsoni, muhit muammosi emas"),),
        )
    if not isinstance(plan.bundle_dir, str) or not os.path.isdir(plan.bundle_dir):
        return _watch_fail(st.FAILED_COLLECTOR_UNAVAILABLE, CODE_BUNDLE_DIR_MISSING,
                           "kuzatiladigan papka ko'rsatilmadi yoki topilmadi — yig'uvchi "
                           "natija yozadigan joy yo'q (javob YO'Q; 1C bor-yo'qligi haqida "
                           "bu HECH NARSA demaydi). Keyingi qadam: yig'uvchi yozadigan "
                           "papkani ko'rsatib qayta yurgizing")
    try:
        os.listdir(plan.bundle_dir)
    except OSError as e:
        # ⚠️ O'qilmadi — «bo'sh» DEMAYDI: `UNKNOWN` ni `NOT_FOUND` ga aylantirmaslik qoidasi.
        return _watch_fail(st.FAILED_COLLECTOR_UNAVAILABLE, CODE_BUNDLE_DIR_MISSING,
                           f"kuzatiladigan papka O'QILMADI: {type(e).__name__} — demak uning "
                           f"bo'sh yoki to'laligi ham NOMA'LUM. Keyingi qadam: papkaga kirish "
                           f"huquqini tekshiring")
    if plan.mode not in MODES:
        return _watch_fail(st.FAILED_INTERNAL, CODE_BAD_PLAN,
                           "rejada noma'lum rejim ko'rsatilgan — bu agentning nuqsoni")
    if plan.timeout_seconds <= 0 or plan.poll_seconds <= 0:
        return _watch_fail(st.FAILED_INTERNAL, CODE_BAD_PLAN,
                           "kutish yoki so'rov oralig'i musbat bo'lishi kerak — bu agentning "
                           "nuqsoni. Cheksiz yoki nol kutish bu yo'lda ham YO'Q")
    return None


def watch(plan: WatchPlan, *, clock: Callable[[], float],
          sleeper: Callable[[float], None] = DEFAULT_SLEEPER,
          on_wait: Callable[[WaitTick], None] | None = None) -> BridgeResult:
    """Kuzatiladigan papkadan paketni OLIB KELADI. 1C ga ULANMAYDI, jarayon OCHMAYDI.

    ⚠️⚠️ BU NORMAL (shipped) `watch_folder` OQIMI va u ko'prikning TAYYORLIK ISBOTIDAN
         O'TADI. Avval UI «papkada yozuv bormi» deb qarardi — ya'ni YARIM yozilgan
         `manifest.json` ni «paket bor» deb qabul qilardi va ko'prikning rad etish mantig'i
         shipped yo'lda UMUMAN ishlatilmasdi. Phase 4 da yolg'on SUCCESS bergan nuqson aynan
         shu edi, shu bois bu yerda YAGONA tayyorlik o'lchovi ishlatiladi.
    ⚠️ ISTISNO CHIQARMAYDI: har qanday yiqilish ANIQ `state_hint` bo'lib qaytadi.
    ⚠️ `exit_code` DOIM `None`: jarayon agentda emas. Uni `0` deb yozish «biz ishga
       tushirdik» degan YOLG'ON da'vo bo'lardi.
    ⚠️⚠️ VALIDATSIYA BU YERDA EMAS va BU YERDA AYNIQSA EMAS: tayyorlik o'lchovi FAQAT
         tugallanish belgisiga (`manifest.json` — bor, JSON bo'lib parse bo'ladi, MINIMAL
         SHAKLDA — `_manifest_minimal_shape` — va hajmi barqaror) qaraydi. Majburiy fayl yetishmasa, buni `runtime_bundle` validatori
         ANIQ nomi bilan aytadi va BUZUQ PAKET DALIL bo'lib `bundle/` da saqlanadi.
         Bu yerda «hamma fayl bormi» deb turib olish ikki narsani buzardi: (1) sabab
         «chiqish to'liq emas» dan «vaqt tugadi» ga ALMASHARDI, (2) paket uzatilmagani
         uchun yagona dalil YO'Q QILINARDI. ⚠️ Yarim yozilgan `manifest.json` esa BARIBIR
         tayyor deb hisoblanmaydi — Phase 4 nuqsoni aynan shu edi va darvoza joyida.
         ⚠️ `collect(route=watch_folder)` da qoida BOSHQA (hamma fayl TALAB qilinadi) va bu
            ATAYLAB: u yerda chiqish papkasi AGENTNING talabi bilan BO'SH bo'lgan, demak
            fayllarning paydo bo'lishi tugallanishning xavfsiz o'lchovi. Bu yerda papka
            OPERATORNING va unda paket agent ko'rmagan holda paydo bo'lgan bo'lishi mumkin.
    """
    yiqildi = watch_preflight(plan)
    if yiqildi is not None:
        return yiqildi
    tayyor, kod, yetishmagan = _wait_until_ready(
        plan.bundle_dir, clock=clock, sleeper=sleeper,
        timeout_seconds=plan.timeout_seconds, poll_seconds=plan.poll_seconds,
        wait_for_appearance=True, on_wait=on_wait, require_all_files=False,
    )
    if not tayyor:
        # ⚠️ Vaqt tugadi: `FAILED_TIMEOUT`. Bu `FAILED_COLLECTOR_UNAVAILABLE` EMAS —
        #    yig'uvchi hali ishlab turgan bo'lishi MUMKIN va «javob bermadi» deb hukm
        #    chiqarish noto'g'ri bo'lardi. Cheksiz kutish esa YO'Q.
        return BridgeResult(
            route=ROUTE_WATCH_FOLDER, ok=False, state_hint=st.FAILED_TIMEOUT, exit_code=None,
            errors=(AgentError(SCOPE_WATCH, kod, _incomplete_detail(yetishmagan)),),
            notes=(OPERATOR_RAN_COLLECTOR_NOTE,
                   "Keyingi qadam: yig'uvchini oxirigacha bajarilishini kutib, agentni qayta "
                   "yurgizing; 1C band bo'lmagan paytni tanlang."),
        )
    # ⚠️ Tugallanish belgisi TO'LIQ, lekin majburiy fayl yetishmaydi: BU JIM O'TMAYDI —
    #    izoh yoziladi va validator sababni o'z nomi bilan aytadi (quvur `FAILED_VALIDATION`
    #    da to'xtaydi). Ya'ni «paket olindi» «paket to'g'ri» DEGANI EMAS.
    kam = ((f"⚠️ Tugallanish belgisi (`{MANIFEST_FILE}`) to'liq yozilgan, LEKIN majburiy "
            f"fayl(lar) yetishmayapti {list(yetishmagan)}. Paket shu holda UZATILADI, "
            f"chunki hukmni validator chiqaradi va buzuq paket DALIL bo'lib saqlanadi — "
            f"kutish bu holatni tuzatmaydi.",) if yetishmagan else ())
    return BridgeResult(
        route=ROUTE_WATCH_FOLDER, ok=True, bundle_dir=plan.bundle_dir, exit_code=None,
        notes=(OPERATOR_RAN_COLLECTOR_NOTE, WATCH_FOLDER_PROVENANCE_NOTE) + kam + (
               "Paket kuzatilgan papkadan tugallanish belgisi bilan olindi; mazmuni ALOHIDA "
               "tekshiriladi.",),
    )


def _watch_fail(state_hint: str, code: str, detail: str) -> BridgeResult:
    """Kuzatish yo'lining yiqilish natijasi. ⚠️ `route` DOIM `watch_folder` — urinilgan yo'l
    shu va boshqasini yozish hisobotda yolg'on sabab bo'lardi.

    ⚠️ OPERATOR QADAMLARI BU YERDA TAKRORLANMAYDI (`WATCH_FOLDER_OPERATOR_STEPS`): ularni
       chaqiruvchi yurishning BOSHIDA, bir marta yozadi. Ikki marta yozilgan AYNI to'rt satr
       hisobotga bitta ham yangi fakt qo'shmay, uni o'qilmas qilardi.
    """
    return BridgeResult(route=ROUTE_WATCH_FOLDER, ok=False, state_hint=state_hint,
                        exit_code=None, errors=(AgentError(SCOPE_WATCH, code, detail),),
                        notes=(OPERATOR_RAN_COLLECTOR_NOTE,))


def _incomplete_detail(missing: tuple[str, ...]) -> str:
    """⚠️ Fayl nomlari SHARTNOMADAN (`REQUIRED_FILES`) — ular sir emas va tozalanmaydi."""
    if missing:
        return (f"paket to'liq yozilmadi: majburiy fayl(lar) yo'q {list(missing)}. "
                f"Tugallanish belgisi `{MANIFEST_FILE}` ENG OXIRIDA yoziladi, shu bois "
                f"yarim paket TAYYOR deb hisoblanmaydi")
    return (f"`{MANIFEST_FILE}` to'liq yozilganiga ishonch yo'q (hajmi barqarorlashmadi, "
            f"JSON bo'lib o'qilmadi yoki tugallanish belgisining MINIMAL SHAKLI yo'q: "
            f"`manifest_version` kutilgan qiymatda va `files` bo'sh bo'lmagan ro'yxat "
            f"bo'lishi kerak), shu bois paket TAYYOR deb hisoblanmadi")


# ⚠️ IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI — testdan ham arzon darvoza.
assert MANIFEST_FILE in REQUIRED_FILES, "tugallanish belgisi majburiy fayllar ichida bo'lsin"
assert "/P" in FORBIDDEN_SWITCHES, "parol kaliti taqiqlar ro'yxatida bo'lishi SHART"
assert '"' in FORBIDDEN_ARG_CHARS, "qo'shtirnoq taqiqlar ro'yxatida bo'lishi SHART"
assert all(st.is_failure(h) for h in HINT_SOURCE_STATE), \
    "HINT_SOURCE_STATE kaliti yiqilish holati bo'lishi kerak"
assert all(st.can_transition(src, hint) for hint, src in HINT_SOURCE_STATE.items()), \
    "HINT_SOURCE_STATE holat mashinasidan ajralib ketgan — ko'rsatilgan holatdan o'tish YO'Q"
# ⚠️ KUZATISH yo'li FAQAT shu uchta yiqilishni chiqaradi va UCHALASI ham
#    `METADATA_DISCOVERY` dan yoziladi — shu bois chaqiruvchi (`ui._collect`) zanjirni
#    `METADATA_DISCOVERY` ga keltirib qo'yib, keyin `watch` ni chaqirishi YETARLI. Agar bu
#    ro'yxat kengaysa, bu assert import paytida yiqiladi va chaqiruvchi ham tuzatiladi.
WATCH_STATE_HINTS: tuple[str, ...] = (st.FAILED_COLLECTOR_UNAVAILABLE, st.FAILED_TIMEOUT,
                                      st.FAILED_INTERNAL)
assert all(HINT_SOURCE_STATE[h] == st.METADATA_DISCOVERY for h in WATCH_STATE_HINTS), \
    "kuzatish yo'lining yiqilishlari `METADATA_DISCOVERY` dan yozilishi SHART"
# ⚠️ `COLLECTOR_ENTRY_POINT` ning yig'uvchi manbasida ROSTDAN turgani TESTDA tekshiriladi
#    (`test_agent_collector_bridge`), bu yerda EMAS: import paytida fayl o'qish bu modulning
#    «faqat o'qish, faqat kerak bo'lganda» chegarasini buzardi va `.epf`/manba repoda
#    bo'lmagan yig'mada agentni UMUMAN import qilinmas qilib qo'yardi.
assert SCOPE_BATCH.endswith(ROUTE_BATCH_EXECUTE) and SCOPE_WATCH.endswith(ROUTE_WATCH_FOLDER), \
    "xato yozuvlarining `scope` lari marshrut nomlaridan ajralib ketdi"
