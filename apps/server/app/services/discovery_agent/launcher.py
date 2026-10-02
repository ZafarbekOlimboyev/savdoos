# -*- coding: utf-8 -*-
"""ISHGA TUSHIRISH ABSTRAKSIYASI, KOOPERATIV BEKOR QILISH va TIMEOUT.

Bu modul UCH savolga javob beradi va BOSHQA hech narsa qilmaydi:

  1. 1C ni TANLANGAN baza bilan QANDAY ochish kerak (`open_infobase`) — buyruq SHAKLI,
     kredensial darvozasi va operatorga beriladigan ANIQ ko'rsatma.
  2. Yig'uvchini 1C ning O'ZI avtomatik bajarishi mumkinmi (`auto_run_processor`) —
     javob: DEKLARATSIYA, bu mashinada TASDIQLANMAGAN.
  3. Kutishni QANDAY to'xtatish kerak (`CancelToken`, `wait_for_collector`) — kooperativ
     bekor qilish va CHEKLI kutish.

══════════════════════════════════════════════════════════════════════════════════════════
⚠️⚠️ ENG MUHIM QOIDA — JARAYON O'LDIRILMAYDI
     Bu modulda birorta jarayonni tugatish yo'li YO'Q: na `taskkill`, na jarayon daraxtini
     tugatish, na bitta jarayonni to'xtatish. Sabab shunchaki «xavfli» emas: agent 1C ni
     OPERATORNING ish sessiyasi sifatida ochadi. Uni majburan yopish operatorning
     SAQLANMAGAN ishini yo'qotardi — ya'ni razvedka (faqat O'QIYDIGAN ish) do'konga ZARAR
     yetkazardi. Shu bois bekor qilish KOOPERATIV: agent KUTISHNI to'xtatadi, 1C oynasini
     esa operator O'ZI yopadi. Bu da'vo STATIK test bilan qulflangan
     (`test_agent_launcher.py` -> `test_manbada_jarayon_oldirish_naqshi_YOQ`).

⚠️⚠️ NEGA STANDART ISHGA TUSHIRGICH YO'Q (va bu NUQSON emas, QAROR)
     Paketda jarayon ishga tushiradigan YAGONA joy — `collector_bridge.run_1c_batch`
     (`subprocess` faqat shu modulda bo'lishi testlar bilan qulflangan). Lekin u
     PAKETLI rejim uchun yozilgan: vaqt tugaganda u jarayonni TUGATADI. Operatorning 1C
     oynasi uchun bu YARAMAYDI (yuqoridagi qoidaga qarang), ikkinchi `subprocess` joyi
     ochish esa auditni buzadi. Shu bois:
       · `open_infobase` buyruqni QURADI, TEKSHIRADI va operatorga ko'rsatma BERADI;
       · jarayonni ochish esa ALMASHTIRILADIGAN `Opener` ga qoldiriladi va STANDART
         qiymati YO'Q — berilmasa agent 1C ni O'ZI OCHMAYDI
         (`COLLECTOR_EXECUTION_NOT_ALLOWED`) va operator yo'lini ko'rsatadi.
     Ya'ni shipped paketda 1C ni OPERATOR ochadi. Bu QOBILIYAT CHEGARASI va u
     YASHIRILMAYDI.

⚠️⚠️ COM YO'Q va O'YLAB CHIQARILGAN PARAMETR YO'Q (QAROR 6)
     COM avtomatizatsiyasi (`V83.COMConnector`) bu modulga QO'SHILMAYDI: u 1C ni ishga
     tushirib bazaga ULANADI, ya'ni «faqat o'qish» kafolatidan tashqariga chiqadi va
     parolni ham TALAB qiladi. Yangi buyruq satri kaliti ham O'YLAB CHIQARILMAYDI: nishon
     kaliti FAQAT `/F` yoki `/S` (`bridge_protocol.ALLOWED_TARGET_SWITCHES`), fe'l esa
     `ENTERPRISE` — u `collector_bridge` da ALLAQACHON bor va test bilan qulflangan.
     Konfigurator rejimi (`detector.DESIGNER_MODE_VERB`) bu modulda ISHLATILMAYDI: u
     bazani O'ZGARTIRISH huquqiga ega rejim, razvedka uchun esa KERAK EMAS.

⚠️⚠️ PAROL (QAROR 5)
     Parol `argv` ga, jurnalga, natija fayliga, doimiy konfiguratsiyaga va buyruq
     tarixiga HECH QACHON tushmaydi. Bu modulda kredensial MAYDONI ham, PARAMETRI ham
     YO'Q, qurilgan buyruq esa mavjud `collector_bridge._assert_no_credentials`
     darvozasidan o'tadi (`bridge_protocol.assert_launch_command` orqali) — darvoza
     IKKINCHI NUSXADA YOZILMAYDI. Parolni 1C NING O'Z oynasi oladi va agent uni KO'RMAYDI.

⚠️⚠️ 1C ALLAQACHON ISHLAYOTGAN BO'LSA — TASODIFIY JARAYONGA ULANMAYDI
     Bu modulda jarayon ro'yxatini o'qish yo'li YO'Q (`tasklist`/`wmic`/`psutil`/
     `OpenProcess` — birortasi ham). Agent FAQAT O'ZI ochgan jarayonni biladi: uni
     `Opener` qaytaradi (`OpenerOutcome`), ya'ni «qaysi 1C mening 1C?» savoliga javob
     TAXMIN bilan emas, QAYTARILGAN NATIJA bilan beriladi. Operator o'z 1C sessiyasini
     ochiq qoldirgan bo'lsa, agent unga ARALASHMAYDI va uni YOPMAYDI; yig'uvchi natijasi
     esa baribir YURISHGA BOG'LANGAN (`run_id` + `nonce`), shu bois begona sessiyaning
     chiqishi QABUL QILINMAYDI.

⚠️ 1C XAVFSIZLIGI ZAIFLASHTIRILMAYDI: xavfsiz rejimni chetlab o'tish, xavfsizlik
   profilini o'zgartirish yoki rol tahrirlash — bu modulda YO'Q va keyingi qadam
   matnlarida ham TAVSIYA QILINMAYDI. 1C tashqi qayta ishlashni rad etsa, bu NORMAL
   holat (`security_refusal`) va qaror do'konning xavfsizlik siyosatida qoladi.

⚠️ VAQT KIRISHDAN: bu modul soatni O'ZI olmaydi (`clock` parametri), kutishni ham O'ZI
   uxlamaydi (`sleeper`). Shu bois kutish mantiqi SOXTA soat bilan to'liq isbotlanadi va
   test birorta soniya kutmaydi.
⚠️ CHEKSIZ KUTISH YO'Q: `timeout_seconds` har doim CHEKLI va chegara KIRISHDAN keladi.
⚠️ Hujjatga tushadigan har qanday sanoq MATN bo'lib qaytadi (`ticks`, `elapsed_seconds`):
   JSON'da son ham, boolean ham bo'lmaydi degan yadrodagi qoida bilan AYNI.
⚠️ Bu modul HECH NARSA O'CHIRMAYDI: na wildcard bo'yicha, na yolg'iz fayl bo'yicha. U
   yurish papkasini O'QIYDI (`iterdir`) va unga YOZMAYDI.
⚠️ HAQIQIY 1C ga ULANMAYDI va bu mashinada 1C umuman O'RNATILMAGAN: hamma test SOXTA
   `Opener` va sintetik fayllar bilan yuradi. Ishga tushirish yo'lining holati —
   `AUTO_RUN_STATUS` (`UNVERIFIED_ON_REAL_1C`).

⚠️⚠️ BU MODUL SHIPPED YO'LDA ISHLATILADI (TUZATILGAN NUQSON). Ilgari uni FAQAT o'z testi
     import qilardi: `one_click`, `__main__` va `ui` — birortasi ham chaqirmasdi, ya'ni
     ishga tushirish abstraksiyasi ham, KOOPERATIV BEKOR QILISH ham e'lon qilingan-u
     YETIB BO'LMAYDIGAN qobiliyat edi (CP2 dagi `ABORTED_BY_OPERATOR` nuqsonining aynan
     o'zi). Endi `one_click.run_one_click`:
       · 1C ni ochish buyrug'ini SHU YERDA quradi va tekshiradi (`open_infobase`), ya'ni
         ishga tushirish darvozasi (`operator_confirmed`) ROSTDAN hukm chiqaradi;
       · yig'uvchining javobini SHU YERDA kutadi (`wait_for_collector`) va bekor qilish
         tokenini (`CancelToken`) o'sha halqaga uzatadi.
     ⚠️ YANGI DVIGATEL YOZILMADI: kutish halqasi `collector_bridge` ning qoidasi va
        standart qiymatlari bilan AYNI (ikki mustaqil chegara, `clock`/`sleeper`
        kirishdan), qabul qilish qarori esa `bridge_protocol` ning YAGONA darvozasida.
"""
from __future__ import annotations

# ⚠️⚠️ `os` ATAYLAB IMPORT QILINMAYDI, `ntpath` esa qilinadi.
#      Bu modulda yo'l bilan bajariladigan YAGONA amal — yig'uvchi faylining NOMINI
#      ajratish, u esa WINDOWS yo'li. `os.path` HOST ajratuvchisini biladi, shu bois
#      POSIX hostda Windows yo'lini AJRATMAY, butun yo'lni qaytaradi — operator
#      ko'rsatmasiga xom yo'l oqib ketardi. `ntpath` standart kutubxona, har hostda bor
#      va AYNI natijani beradi. `os` ni qaytarib qo'ymaslikni
#      `test_launcherda_WINDOWS_yolini_os_path_ISHLAMAYDI` darvozasi qulflaydi.
import ntpath
import pathlib
from dataclasses import dataclass
from typing import Callable, Protocol

from . import BUNDLE_SUBDIR
from . import bridge_phase as bp
from . import bridge_protocol as pr
from . import collector_bridge as cb
from . import detector as det
from . import states as st

# ══════════════════════════════════════════════════════════════════════════════════════════
# SHARTNOMA QIYMATLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Kim 1C ni ochadi. ⚠️ Shipped paketda STANDART — operator (yuqoridagi izohga qarang).
LAUNCH_MODE_OPERATOR = "operator_opens"
LAUNCH_MODE_AGENT = "agent_opens"
LAUNCH_MODES: tuple[str, ...] = (LAUNCH_MODE_AGENT, LAUNCH_MODE_OPERATOR)

#: Avtomatik ishga tushirish yo'lining ISBOT holati — `bridge_phase` dan OLINADI (ikkinchi
#: belgi e'lon QILINMAYDI).
AUTO_RUN_STATUS = bp.AUTOMATIC_LAUNCH_VERIFICATION

#: Avtomatik ishga tushirish QURILGANMI. ⚠️ Uchlik MATN lug'ati `detector` dan: `"false"` —
#: «qurilmagan» degan ANIQ javob (JSON'da boolean YO'Q).
AUTO_RUN_IMPLEMENTED = det.TRI_FALSE

#: Ishlab turgan begona 1C jarayoniga ULANISH qurilganmi — YO'Q va qurilmaydi.
ATTACH_TO_RUNNING = det.TRI_FALSE

#: Fe'l va nishon kalitlari — MAVJUD shartnomadan, qayta YOZILMAYDI.
VERB_ENTERPRISE = cb.VERB_ENTERPRISE
SWITCH_FILE_TARGET, SWITCH_SERVER_TARGET = pr.ALLOWED_TARGET_SWITCHES

#: Vaqt va soat — ko'prikdan (ikkinchi standart qiymat YOZILMAYDI).
DEFAULT_TIMEOUT_SECONDS = cb.DEFAULT_TIMEOUT_SECONDS
DEFAULT_POLL_SECONDS = cb.DEFAULT_POLL_SECONDS
DEFAULT_CLOCK: Callable[[], float] = cb.DEFAULT_CLOCK
DEFAULT_SLEEPER: Callable[[float], None] = cb.DEFAULT_SLEEPER

#: Bekor qilishning standart sababi (operator tugmasi).
CANCEL_REASON_OPERATOR = "operator bekor qildi"

# ── 1C NING XAVFSIZLIK RADDI (NORMAL HOLAT) ───────────────────────────────────────────────
#: ⚠️ Lug'at YOPIQ: noma'lum sabab — ISTISNO. «Boshqa sabab» degan qop bo'lsa, u bir kun
#:    haqiqiy nuqsonni ham yashirardi.
REFUSAL_SAFE_MODE = "safe_mode"
REFUSAL_INSUFFICIENT_RIGHTS = "insufficient_rights"
REFUSAL_SECURITY_PROFILE = "security_profile"
SECURITY_REFUSALS: tuple[str, ...] = (REFUSAL_INSUFFICIENT_RIGHTS, REFUSAL_SAFE_MODE,
                                      REFUSAL_SECURITY_PROFILE)

#: Har sabab uchun (operator matni, keyingi qadam).
#: ⚠️⚠️ KEYINGI QADAM HECH QAYERDA XAVFSIZLIKNI ZAIFLASHTIRISHGA CHAQIRMAYDI: «xavfsiz
#:      rejimni o'chiring», «profilni tahrirlang», «rolga huquq qo'shing» kabi maslahat
#:      BERILMAYDI. Agent razvedkani FAQAT O'QISH uchun qiladi, ruxsat masalasi esa
#:      do'konning xavfsizlik siyosati — qarorni odam beradi.
SECURITY_REFUSAL_TEXT: dict[str, tuple[str, str]] = {
    REFUSAL_SAFE_MODE: (
        "1C tashqi qayta ishlashni XAVFSIZ REJIMDA bajarishni rad etdi. Bu nuqson emas — "
        "1C o'z xavfsizlik qoidasini qo'lladi.",
        "1C administratoringizga ko'rsating: yig'uvchi FAQAT O'QIYDI, hech narsa yozmaydi "
        "va o'zgartirmaydi. Ruxsat berish-bermaslik qarorini u qabul qiladi. Agent "
        "xavfsiz rejimni CHETLAB O'TMAYDI.",
    ),
    REFUSAL_INSUFFICIENT_RIGHTS: (
        "Joriy 1C foydalanuvchisining huquqi tashqi qayta ishlashni bajarishga yetmadi.",
        "Kerakli huquqga ega 1C foydalanuvchisi bilan kirib ko'ring yoki "
        "administratoringizga murojaat qiling. Agent 1C dagi ROLLARNI va huquqlarni "
        "TAHRIRLAMAYDI.",
    ),
    REFUSAL_SECURITY_PROFILE: (
        "1C ning xavfsizlik profili tashqi qayta ishlashga ruxsat bermadi.",
        "Administratoringizga murojaat qiling. Agent xavfsizlik profilini "
        "O'ZGARTIRMAYDI va uni chetlab o'tishga urinmaydi.",
    ),
}

# ── BOSHQA MODULGA SO'ROV (halol qayd) ────────────────────────────────────────────────────
#: ⚠️⚠️ `detector.Install.clients` XOTIRADA bor, `environment.json` ga esa TUSHMAYDI:
#:      `installs[]` kalitlari `result_package.py` validatorida va iki testda qulflangan.
#:      Bu matn SHU SO'ROVNI kodda ko'rinadigan joyda qoldiradi — u `notes` ga ham
#:      ko'chiriladi va «keyinroq eslaymiz» degan yo'l yopiladi.
RESULT_PACKAGE_SOROVI = (
    "SO'ROV (result_package.py egasiga): `environment.json` -> `installs[]` uchun "
    "ruxsat etilgan kalitlar to'plamiga `clients` QO'SHILSIN va uning shakli "
    "tekshirilsin (`client_type` -> `detector.CLIENT_TYPES`, `present` -> "
    "`true`|`unknown`, `path` -> niqoblangan, `mode_verb` -> matn yoki `null`). Shundan "
    "keyin `detector.Install.as_document()` da bitta kalit qo'shiladi. Hozir u ATAYLAB "
    "qo'shilmagan: bugun qo'shilsa HAR BIR real natija paketi validatorda rad etilardi."
)

#: ⚠️ `ABORTED_BY_OPERATOR` holati ENDI SHIPPED KODDA ISHLATILADI (pastdagi
#:    `wait_for_collector` ga qarang) — CP2 da u faqat lug'atda turardi. ⚠️ VA U ENDI
#:    OPERATORGA YETIB BORADI: `one_click.run_one_click(cancel=...)` shu kutishni
#:    chaqiradi, ya'ni «qobiliyat e'lon qilingan, lekin yetib bo'lmaydi» nuqsoni YOPILDI.
STATES_TEST_SOROVI = (
    "SO'ROV (test_agent_states.py egasiga): "
    "`test_ABORTED_BY_OPERATOR_shipped_kodda_ISHLATILMAYDI_va_hujjat_shuni_AYTADI` "
    "ENDI ESKIRGAN: holat `launcher.py` da ROSTDAN ishlatiladi (kooperativ bekor "
    "qilish) va unga `one_click.py` dagi bir bosishli oqimdan YETIB BORILADI "
    "(`run_one_click(cancel=...)`). Test aksini qulflashi kerak: holat FAQAT "
    "`launcher.py` va `one_click.py` da YOZILSIN (boshqa shipped modullar bu holatni "
    "YOZMAYDI: `ui.py`, `pipeline.py`, `collector_bridge.py`, `status.py`, `report.py`, "
    "`__main__.py` — birortasi ham) va "
    "`states.py` ning docstringi hamda `FAILURE_MEANING[ABORTED_BY_OPERATOR]` matni "
    "«ISHLATILMAYDI / QURILMAGAN» da'vosidan TOZALANSIN (aks holda paket o'zi haqida "
    "yolg'on yozadi). Bu fayl bizga berilmagan, shu bois O'ZIMIZ tahrirlamadik."
)

#: Keyingi qadamni holat ma'nosidan ajratadigan belgi (`states.FAILURE_MEANING` ichida).
#: ⚠️ Ikkinchi ma'no lug'ati YOZILMAYDI: matn `states.py` dan OLINADI va shu belgidan
#:    ikkiga bo'linadi. Belgi yo'q bo'lsa — import paytida yiqiladi (pastdagi darvoza).
NEXT_ACTION_MARKER = "Keyingi qadam:"

#: Bu modul ishlatadigan kodlar: ko'prik kodlari + ko'prikning MAVJUD kodlari.
#: ⚠️ Yangi kod O'YLAB CHIQARILMAYDI: kerak bo'lgan hammasi allaqachon e'lon qilingan.
KNOWN_CODES: frozenset[str] = frozenset(bp.BRIDGE_CODES) | frozenset({
    cb.CODE_WAIT_TIMEOUT, cb.CODE_EXIT_CODE_NONZERO, cb.CODE_LAUNCH_FAILED,
    cb.CODE_EXE_MISSING, cb.CODE_BUNDLE_DIR_MISSING,
})


class LauncherError(ValueError):
    """Ishga tushirish shartnomasi buzildi. `.code` — `KNOWN_CODES` dan BITTA kod.

    ⚠️ Xato matnida QIYMATNING O'ZI (yo'l, `locator`) ko'rsatilmaydi: xabar jurnalga
       tushadi, jurnal esa qo'ldan-qo'lga o'tadi.
    ⚠️ Noma'lum kod — ISTISNO: «umumiy xato» operatorga nima qilishni aytmaydi.
    """

    def __init__(self, code: str, message: str) -> None:
        if code not in KNOWN_CODES:
            raise LauncherError(bp.CODE_BRIDGE_SHAPE_INVALID,
                                f"noma'lum kod: {code!r}; ruxsat etilganlari "
                                f"{sorted(KNOWN_CODES)}")
        self.code = code
        super().__init__(f"[{code}] {message}")


def _need(cond: bool, code: str, msg: str) -> None:
    if not cond:
        raise LauncherError(code, msg)


# ══════════════════════════════════════════════════════════════════════════════════════════
# NOSOZLIK UCHLIGI — matn MAVJUD lug'atlardan olinadi
# ══════════════════════════════════════════════════════════════════════════════════════════
def failure_text(code: str, *, state: str | None = None) -> tuple[str, str]:
    """(operator matni, keyingi qadam) — IKKINCHI lug'at yozmasdan.

    Manba tartibi ANIQ:
      1. kod `bridge_phase.FAILURE_TRIPLE` da bo'lsa — uchlikdan (eng aniq matn);
      2. aks holda `states.FAILURE_MEANING[state]` dan, `NEXT_ACTION_MARKER` bo'yicha
         ikkiga bo'lib.
    ⚠️ Ikkinchi yo'lda `state` SHART: holatsiz matn manbasi YO'Q, taxmin esa qilinmaydi.
    """
    if code in bp.FAILURE_TRIPLE:
        uchlik = bp.failure_triple(code)
        return uchlik.operator, uchlik.next_action
    _need(isinstance(state, str) and state in st.FAILURE_MEANING,
          bp.CODE_BRIDGE_SHAPE_INVALID,
          f"{code} uchun matn manbasi YO'Q: yiqilish holati berilmagan")
    matn = st.FAILURE_MEANING[str(state)]
    oldi, _belgi, keyin = matn.partition(NEXT_ACTION_MARKER)
    return oldi.strip(), keyin.strip()


# ══════════════════════════════════════════════════════════════════════════════════════════
# NISHON
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class LaunchTarget:
    """Ochiladigan baza: turi, XOM lokatori va nomi.

    ⚠️⚠️ XOM `locator` FAQAT buyruq satriga boradi: protokolga (`request.json`) u
         YOZILMAYDI — u yerga `target_fingerprint` (sha256) tushadi. Sabab: `locator`
         sir bo'lishi mumkin (UNC yo'li, server ulanish satri).
    ⚠️ `name` SHART: nishon o'zligi xeshi `kind + name + locator` dan quriladi
       (`bridge_protocol.target_fingerprint`), ya'ni nomsiz yozuv uchun xesh shartnomaga
       MOS kelmasdi. `.v8i` da nomsiz bo'lim uchrasa yo'l shu yerda to'xtaydi — bu
       QOBILIYAT CHEGARASI va u jimgina «nom = lokator» ga AYLANTIRILMAYDI.
    """

    kind: str
    locator: str
    name: str

    def __post_init__(self) -> None:
        _need(self.kind in pr.TARGET_KINDS, bp.CODE_BRIDGE_SHAPE_INVALID,
              f"noma'lum nishon turi: {self.kind!r}; ruxsat etilganlari "
              f"{sorted(pr.TARGET_KINDS)}")
        for nom, qiymat in (("locator", self.locator), ("name", self.name)):
            _need(isinstance(qiymat, str) and qiymat.strip() != "",
                  bp.CODE_BRIDGE_SHAPE_INVALID,
                  f"nishon {nom}: bo'sh bo'lmagan matn bo'lishi kerak (qiymat ataylab "
                  f"ko'rsatilmayapti)")

    @property
    def fingerprint(self) -> str:
        """Nishonning KREDENSIALSIZ o'zligi — ko'prik protokolidagi AYNI funksiya bilan."""
        return pr.target_fingerprint(self.kind, self.name, self.locator)

    @classmethod
    def from_infobase(cls, infobase) -> "LaunchTarget":
        """`detector.Infobase` dan nishon (nomsiz yozuv — RAD, taxmin YO'Q)."""
        _need(getattr(infobase, "name", None), bp.CODE_BRIDGE_SHAPE_INVALID,
              "ma'lumot bazasining NOMI yo'q — nishon o'zligi nomsiz qurilmaydi; "
              "ro'yxatdan nomli yozuvni tanlang")
        return cls(kind=infobase.kind, locator=infobase.locator, name=str(infobase.name))


# ══════════════════════════════════════════════════════════════════════════════════════════
# `.exe` TANLASH — DETERMINISTIK
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ExeChoice:
    """Tanlangan bajariluvchi va tanlovning SABABI.

    ⚠️ `notes` BO'SH bo'lishi mumkin, lekin tanlov HAR DOIM sababi bilan qaytadi: qaysi
       o'rnatma, qaysi klient turi, qaysi manba.
    """

    path: str
    client_type: str
    version: str | None
    bitness: str
    source: str
    notes: tuple[str, ...] = ()


def choose_exe(installs, *, client_type: str = det.CLIENT_THICK,
               path_clients=()) -> ExeChoice:
    """ENG YANGI o'rnatmaning kerakli klientini tanlaydi (`rank_installs` tartibida).

    ⚠️⚠️ FAQAT ISBOTLANGAN FAYL TANLANADI: `present == "unknown"` nomzod (fayl o'qilmadi)
         TANLANMAYDI, lekin u IZOHDA qoladi. Sabab: tekshirib bo'lmagan yo'lni ochishga
         urinish «1C yo'q» degan YOLG'ON xulosaga olib kelardi, holbuki haqiqiy sabab —
         huquq yetmasligi.
    ⚠️ Standart tur — SEMIZ klient (`1cv8.exe`). Yupqa klient (`1cv8c.exe`) AVTOMATIK
       tanlanmaydi: qaysi baza turini u ocha olishi HAQIQIY 1C da tekshirilmagan, demak
       avtomatik tanlov O'YLAB CHIQARISH bo'lardi. Kerak bo'lsa chaqiruvchi ANIQ beradi.
    ⚠️ `PATH` dan topilgan klient — ENG OXIRGI chora (manbasi eng kuchsiz) va u ham
       izohga yoziladi: operator «qaysi 1C ochildi?» degan savolga javob topa olsin.
    ⚠️ Teng versiyali ikki nomzod bo'lsa tanlov `rank_installs` ning ikkinchi qatlami
       bilan ANIQ bo'ladi (yo'l bo'yicha), lekin bu FAKT izohga yoziladi: jimgina tanlov
       bir kun boshqa `.exe` ga o'tib ketardi.
    """
    _need(client_type in det.CLIENT_TYPES, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"noma'lum klient turi: {client_type!r}; ruxsat etilganlari "
          f"{sorted(det.CLIENT_TYPES)}")
    tartib = det.rank_installs(installs)
    izoh: list[str] = []
    noaniq = [i for i in tartib
              if (i.client(client_type) is not None
                  and i.client(client_type).present == det.TRI_UNKNOWN)]
    for i in noaniq:
        izoh.append(f"{client_type}: tekshirib bo'lmagan nomzod bor "
                    f"(versiya {i.version or det.TRI_UNKNOWN}, manba {i.source}) — "
                    f"TANLANMADI, chunki fayl borligi isbotlanmagan")
    if len(tartib) > 1 and tartib[0].version and tartib[0].version == tartib[1].version:
        izoh.append(f"bir xil versiyali ({tartib[0].version}) bir nechta o'rnatma bor — "
                    f"tanlov yo'l bo'yicha deterministik qilindi")
    for install in tartib:
        yozuv = install.client(client_type)
        if yozuv is not None and yozuv.present == det.TRI_TRUE:
            izoh.append(f"tanlandi: {client_type}, versiya "
                        f"{install.version or det.TRI_UNKNOWN}, manba {yozuv.source}")
            return ExeChoice(path=yozuv.path, client_type=client_type,
                             version=install.version, bitness=yozuv.bitness,
                             source=yozuv.source, notes=tuple(izoh))
    for yozuv in path_clients:
        if yozuv.client_type == client_type and yozuv.present == det.TRI_TRUE:
            izoh.append(f"o'rnatmalar ichida {client_type} topilmadi — PATH dagi fayl "
                        f"ishlatildi (manba {yozuv.source}, versiyasi noma'lum)")
            return ExeChoice(path=yozuv.path, client_type=client_type, version=None,
                             bitness=yozuv.bitness, source=yozuv.source,
                             notes=tuple(izoh))
    raise LauncherError(
        cb.CODE_EXE_MISSING,
        f"{client_type} uchun isbotlangan bajariluvchi fayl topilmadi "
        f"({len(tuple(tartib))} o'rnatma qaraldi, tekshirib bo'lmaganlari "
        f"{len(noaniq)} ta) — yo'l ataylab ko'rsatilmayapti")


# ══════════════════════════════════════════════════════════════════════════════════════════
# BUYRUQ SATRI — SOF FUNKSIYA
# ══════════════════════════════════════════════════════════════════════════════════════════
def build_open_command(*, exe_path: str, target: LaunchTarget) -> tuple[str, ...]:
    """`1cv8.exe ENTERPRISE /F<baza>` yoki `... /S<server>` — YON TA'SIRSIZ.

    ⚠️ SOF: fayl tekshirmaydi, jarayon ochmaydi, vaqt olmaydi — faqat matn quradi va
       TEKSHIRADI. Shu bois 1C bo'lmagan mashinada ham aynan nima yuborilishi test bilan
       qulflanadi.
    ⚠️⚠️ KREDENSIAL KALITI QO'SHILMAYDI va chiqish `bridge_protocol.assert_launch_command`
         dan o'tadi — u mavjud `collector_bridge._assert_no_credentials` ni QAYTA
         ISHLATADI va nishon kaliti AYNAN bitta ekanini ham tekshiradi.
    ⚠️ `/Execute` va `/C` QO'SHILMAYDI: bu yo'l 1C ni OPERATOR uchun ochadi, yig'uvchini
       esa operator O'ZI bajaradi. Paketli bajarish `collector_bridge` ning ishi va u
       yerda shakl allaqachon qulflangan — ikkinchi nusxa yozilmaydi.
    """
    _need(isinstance(target, LaunchTarget), bp.CODE_BRIDGE_SHAPE_INVALID,
          "target `LaunchTarget` bo'lishi kerak")
    # ⚠️ `_safe_arg` MAVJUD darvoza (qo'shtirnoq, `;`, boshqaruv belgisi) va u
    #    `collector_bridge.BridgeError` tashlaydi — ya'ni ko'prik KODI YO'Q. Bu ATAYLAB:
    #    bu darvoza operator yo'li emas, ishlab chiquvchi uchun tripwire (`bridge_protocol.
    #    assert_launch_command` dagi AYNI izohga qarang). Istisnoni o'ramiz = nuqsonni
    #    operator xatosiga aylantiramiz.
    exe = cb._safe_arg(exe_path, "exe_path")
    locator = cb._safe_arg(target.locator, "infobase_locator")
    kalit = SWITCH_FILE_TARGET if target.kind == det.KIND_FILE else SWITCH_SERVER_TARGET
    return pr.assert_launch_command((exe, VERB_ENTERPRISE, f"{kalit}{locator}"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# JARAYONNI OCHUVCHI — ALMASHTIRILADIGAN, STANDART QIYMATI YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class OpenerOutcome:
    """1C ni ochish urinishining natijasi.

    ⚠️ `handle` — ochuvchi qaytargan O'ZLIK (masalan jarayon o'zligi). Agent FAQAT SHU
       o'zlikni biladi: begona jarayonni izlash yo'li umuman yo'q. U hujjatga
       YOZILMAYDI — faqat shu yurish ichida ishlatiladi.
    ⚠️ `exit_code` `None` bo'lishi mumkin: jarayon hali yurib turgan bo'lishi mumkin
       (ochuvchi KUTMAYDI) yoki umuman boshlanmagan bo'lishi mumkin.
    """

    started: str
    exit_code: int | None = None
    handle: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        _need(self.started in (det.TRI_TRUE, det.TRI_FALSE), bp.CODE_BRIDGE_SHAPE_INVALID,
              f"OpenerOutcome.started `{det.TRI_TRUE}`/`{det.TRI_FALSE}` bo'lishi kerak: "
              f"{self.started!r}")


class Opener(Protocol):
    """1C oynasini OCHADIGAN interfeys — bu paketda AMALGA OSHIRILMAGAN.

    ⚠️⚠️ SHARTNOMA: ochuvchi jarayonni BOSHLAYDI va QAYTADI; u jarayonni KUTMAYDI va
         HECH QACHON tugatmaydi (na vaqt tugaganda, na bekor qilinganda). `subprocess.run`
         ga vaqt chegarasi berib ishlatish bu shartnomani BUZADI: u vaqt tugaganda
         bolasini o'ldiradi.
    """

    def __call__(self, command: tuple[str, ...]) -> OpenerOutcome:
        ...


# ══════════════════════════════════════════════════════════════════════════════════════════
# NATIJA
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class LaunchOutcome:
    """Ochish urinishining natijasi + operatorga ANIQ ko'rsatma.

    ⚠️⚠️ `code` BOR, `state_hint` YO'Q bo'lishi NORMAL: «agent 1C ni o'zi ochmadi» —
         YIQILISH EMAS, quvur davom etadi (operator qo'lda ochadi). `state_hint` FAQAT
         yurish TO'XTAGANDA to'ladi.
    ⚠️ `instructions` HECH QACHON BO'SH bo'lmaydi: «spinner-only» holat yo'q — operator
       har holatda nima qilishini biladi.
    ⚠️ `exit_code` — Python soni; hujjatga yozilganda MATNGA aylantirilishi kerak
       (`exit_code_text`).
    """

    mode: str
    launched: str
    command: tuple[str, ...]
    instructions: tuple[str, ...]
    phase: str = bp.LAUNCHING_1C
    exit_code: int | None = None
    code: str | None = None
    state_hint: str | None = None
    operator: str | None = None
    next_action: str | None = None
    output_dir: str | None = None
    verification: str = AUTO_RUN_STATUS
    notes: tuple[str, ...] = ()

    @property
    def exit_code_text(self) -> str | None:
        """Hujjat uchun MATN shakli (`None` — `null` bo'lib qoladi)."""
        return None if self.exit_code is None else str(self.exit_code)

    def __post_init__(self) -> None:
        _need(self.mode in LAUNCH_MODES, bp.CODE_BRIDGE_SHAPE_INVALID,
              f"mode {sorted(LAUNCH_MODES)} dan biri bo'lishi kerak: {self.mode!r}")
        _need(self.launched in (det.TRI_TRUE, det.TRI_FALSE),
              bp.CODE_BRIDGE_SHAPE_INVALID,
              f"launched MATN uchligidan bo'lishi kerak: {self.launched!r}")
        _need(self.launched == det.TRI_FALSE or self.mode == LAUNCH_MODE_AGENT,
              bp.CODE_BRIDGE_SHAPE_INVALID,
              "1C ochilgan bo'lsa mode `agent_opens` bo'lishi SHART")
        _need(bp.is_phase(self.phase), bp.CODE_BRIDGE_SHAPE_INVALID,
              f"noma'lum ko'prik fazasi: {self.phase!r}")
        _need(bool(self.command), bp.CODE_BRIDGE_SHAPE_INVALID,
              "qurilgan buyruq BO'SH bo'lmasin: operator nima ishga tushganini bilsin")
        _need(bool(self.instructions) and all(s.strip() for s in self.instructions),
              bp.CODE_BRIDGE_SHAPE_INVALID,
              "ko'rsatma BO'SH bo'lmasin: «spinner-only» holat YO'Q")
        if self.code is not None:
            _need(self.code in KNOWN_CODES, bp.CODE_BRIDGE_SHAPE_INVALID,
                  f"noma'lum kod: {self.code!r}")
            _need(bool(self.operator and self.operator.strip())
                  and bool(self.next_action and self.next_action.strip()),
                  bp.CODE_BRIDGE_SHAPE_INVALID,
                  "kod bo'lsa operator matni va keyingi qadam ham SHART (uchlik)")
        if self.state_hint is not None:
            _need(self.state_hint in st.FAILURE_STATES, bp.CODE_BRIDGE_SHAPE_INVALID,
                  f"state_hint yiqilish holati bo'lishi kerak: {self.state_hint!r}")
            _need(self.code is not None, bp.CODE_BRIDGE_SHAPE_INVALID,
                  "yiqilish holati bo'lsa KOD ham SHART — jimgina yiqilish YO'Q")


@dataclass(frozen=True)
class AutomaticRunDeclaration:
    """Avtomatik bajarish yo'li — DEKLARATSIYA, qobiliyat EMAS.

    ⚠️ NOMI ATAYLAB `Automatic...` va `Auto` + `Run` bo'laklari YONMA-YON QO'YILMAYDI:
       qo'shilgan shakl Windows'ning avtoyuklanish kalitiga o'xshab qoladi va «yashirin
       davomiylik belgisi» darvozasini (`test_agent_result_package`) YOLG'ON qizil
       qilardi. Darvoza HAQLI (agent avtoyuklanmaydi) — nomni moslash uni o'chirishdan
       ARZON. Shu bois bu izohda ham o'sha bo'laklar qo'shib yozilmaydi.
    """

    status: str
    implemented: str
    code: str
    operator: str
    next_action: str
    reason: str
    command: tuple[str, ...] | None = None


# ══════════════════════════════════════════════════════════════════════════════════════════
# OPERATOR KO'RSATMASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def operator_instructions(*, target: LaunchTarget, mode: str,
                          collector_file: str | None = None) -> tuple[str, ...]:
    """Operator uchun ANIQ qadamlar: qaysi baza, qaysi fayl, qaysi papka.

    ⚠️⚠️ MATNDA XOM YO'L YO'Q: bu satrlar `notes` ga va hisobotga tushishi mumkin, yo'l
         esa sir bo'lishi mumkin (`redact` uni baribir `[REDACTED]` qilib, izohni
         ma'nosiz qilardi). Shu bois fayl nomi FAQAT asosiy nomi bilan ko'rsatiladi
         (`ntpath.basename`), natija papkasi esa `LaunchOutcome.output_dir` maydonida
         ALOHIDA turadi — ekranda ko'rsatish uchun.
    ⚠️ Baza NOMI ko'rsatiladi (u `environment.json` da ham niqoblanmaydi), lokator esa
       KO'RSATILMAYDI.
    """
    _need(mode in LAUNCH_MODES, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"noma'lum rejim: {mode!r}")
    # ⚠️⚠️ `ntpath.basename`, `os.path.basename` EMAS — bu XAVFSIZLIK tuzatishi.
    #      `collector_file` WINDOWS yo'li. POSIX hostda `os.path.basename` unda
    #      ajratuvchi KO'RMAYDI va BUTUN yo'lni qaytaradi, ya'ni yuqoridagi «matnda xom
    #      yo'l yo'q» va'dasi JIMGINA buzilib, yo'l `notes`/hisobotga oqardi. `ntpath`
    #      standart kutubxona va `/` ni ham ajratuvchi deb biladi — demak Windows yo'li
    #      ham, POSIX yo'li ham to'g'ri ajratiladi, hostdan QAT'I NAZAR.
    yiguvchi = ntpath.basename(collector_file) if collector_file else None
    qadamlar: list[str] = []
    if mode == LAUNCH_MODE_AGENT:
        qadamlar.append(
            f"1C agent tomonidan «{target.name}» bazasi bilan ochildi. Agent bazaga "
            f"o'zi ULANMAYDI va unda hech narsa o'zgartirmaydi."
        )
    else:
        qadamlar.append(
            f"1C ni O'ZINGIZ oching va «{target.name}» bazasini tanlang. Agent 1C ni "
            f"o'zi ochmadi — bu yo'l haqiqiy 1C da sinalmagan."
        )
    qadamlar.append(
        f"Yig'uvchini ({yiguvchi}) shu sessiyada BIR MARTA ochib bajaring."
        if yiguvchi else
        "Yig'uvchi faylini shu sessiyada BIR MARTA ochib bajaring."
    )
    qadamlar.append(
        "Natija papkasini qo'lda tanlash KERAK EMAS: u so'rov hujjatida allaqachon "
        "ko'rsatilgan va yig'uvchi uni o'zi o'qiydi. Papkaning yo'li agent ekranida "
        "alohida ko'rsatiladi."
    )
    qadamlar.append(
        "Kirish ma'lumoti so'ralsa, uni 1C NING O'Z oynasi so'raydi — agent parolni "
        "ko'rmaydi va hech qayerga yozmaydi."
    )
    qadamlar.append(
        "Bekor qilsangiz agent faqat KUTISHNI to'xtatadi: 1C oynasini o'zingiz yopasiz, "
        "agent birorta jarayonni majburan tugatmaydi."
    )
    return tuple(qadamlar)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YO'L 1 — `open_infobase` (ZAXIRA YO'L: 1C ochiladi, qolgani OPERATORDA)
# ══════════════════════════════════════════════════════════════════════════════════════════
def open_infobase(*, exe_path: str, target: LaunchTarget, operator_confirmed: bool = False,
                  opener: Opener | None = None, output_dir: str | None = None,
                  collector_file: str | None = None, notes=()) -> LaunchOutcome:
    """1C ni TANLANGAN baza bilan ochadi (yoki ochmaganini ANIQ aytadi).

    Qaytish yo'llari UCHTA va ularning HAMMASI operator ko'rsatmasi bilan qaytadi:
      · tasdiq YO'Q                 -> `COLLECTOR_EXECUTION_NOT_ALLOWED`, operator ochadi;
      · ochuvchi berilmagan         -> AYNI kod, sababi BOSHQA (modul docstringiga qarang);
      · ochuvchi bor va tasdiq bor  -> 1C ochiladi, natija (`exit_code`, `handle`) qaytadi.

    ⚠️⚠️ FAIL-CLOSED: `operator_confirmed` berilmasa agent HECH NARSA ochmaydi. Darvoza
         IKKINCHI NUSXADA YOZILMAYDI — mavjud `bridge_protocol.assert_launch_allowed`
         chaqiriladi.
    ⚠️ Buyruq HAR HOLATDA quriladi va TEKSHIRILADI, hatto ochilmasa ham: operator aynan
       nima ishga tushishini ko'rishi kerak, va kredensial darvozasi ham shu yerda ishlaydi.
    ⚠️ `shell` TUSHUNCHASI BU YERDA UMUMAN YO'Q: buyruq `tuple` bo'lib uzatiladi, qobiq
       chaqirilmaydi va bu modulda jarayon ochadigan kod ham yo'q.
    """
    buyruq = build_open_command(exe_path=exe_path, target=target)
    qoshimcha = tuple(str(n) for n in notes)

    if operator_confirmed is not True or opener is None:
        sabab = (
            "operator tasdig'i YO'Q"
            if operator_confirmed is not True else
            "agentda 1C ni o'zi ochadigan ishga tushirgich YO'Q: paketdagi yagona "
            "jarayon ishga tushirish joyi vaqt tugaganda jarayonni TUGATADI, "
            "operatorning 1C oynasini tugatish esa TAQIQLANGAN"
        )
        operator, keyingi = failure_text(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
        return LaunchOutcome(
            mode=LAUNCH_MODE_OPERATOR, launched=det.TRI_FALSE, command=buyruq,
            instructions=operator_instructions(target=target, mode=LAUNCH_MODE_OPERATOR,
                                               collector_file=collector_file),
            code=bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, operator=operator,
            next_action=keyingi, output_dir=output_dir,
            notes=qoshimcha + (f"avtomatik ochish BAJARILMADI: {sabab}",),
        )

    # ⚠️ MAVJUD darvoza (fail-closed) — tasdiq rost bo'lsa `None` qaytaradi, aks holda
    #    `bridge_protocol` ning O'Z istisnosi chiqadi va u shu kodni olib keladi.
    pr.assert_launch_allowed(operator_confirmed=True)
    natija = opener(buyruq)
    _need(isinstance(natija, OpenerOutcome), bp.CODE_BRIDGE_SHAPE_INVALID,
          "ochuvchi `OpenerOutcome` qaytarishi kerak")

    if natija.started != det.TRI_TRUE:
        operator, keyingi = failure_text(cb.CODE_LAUNCH_FAILED,
                                         state=st.FAILED_COLLECTOR_UNAVAILABLE)
        return LaunchOutcome(
            mode=LAUNCH_MODE_AGENT, launched=det.TRI_FALSE, command=buyruq,
            instructions=operator_instructions(target=target, mode=LAUNCH_MODE_OPERATOR,
                                               collector_file=collector_file),
            code=cb.CODE_LAUNCH_FAILED, state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
            operator=operator, next_action=keyingi, output_dir=output_dir,
            notes=qoshimcha + ("1C ochilmadi — yo'l ataylab ko'rsatilmayapti",),
        )
    return LaunchOutcome(
        mode=LAUNCH_MODE_AGENT, launched=det.TRI_TRUE, command=buyruq,
        instructions=operator_instructions(target=target, mode=LAUNCH_MODE_AGENT,
                                           collector_file=collector_file),
        exit_code=natija.exit_code, output_dir=output_dir,
        notes=qoshimcha + ("1C agent tomonidan ochildi; agent uni YOPMAYDI",),
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# YO'L 2 — `auto_run_processor` (DEKLARATSIYA, BAJARILMAYDI)
# ══════════════════════════════════════════════════════════════════════════════════════════
def auto_run_processor() -> AutomaticRunDeclaration:
    """Yig'uvchini 1C ning O'ZI avtomatik bajarishi — DEKLARATSIYA, BAJARILMAYDI.

    ⚠️⚠️ NEGA ISTISNO EMAS: operator bu yo'lni so'raganda unga «qila olmadim» deb
         JAVOB berish kerak, dastur esa yiqilmasligi kerak — aks holda chaqiruvchi
         istisnoni ushlab, matnni O'ZI o'ylab topishga majbur bo'lardi. Shu bois natija
         ANIQ: holat `UNVERIFIED_ON_REAL_1C`, kod `COLLECTOR_EXECUTION_NOT_ALLOWED`,
         buyruq esa `None` — ya'ni hech narsa qurilmagan.
    ⚠️⚠️ NEGA QURILMAYDI (uchta sabab, uchovi ham o'z-o'zidan yetarli):
         1. Rasmiy hujjatlashtirilgan va XAVFSIZ yo'l bu mashinada TASDIQLANMAGAN: bu
            kompyuterda 1C umuman o'rnatilmagan, shu bois «ishlaydi» degan da'vo
            ISBOTSIZ bo'lardi.
         2. O'ylab chiqarilgan buyruq satri parametri QO'SHILMAYDI: ko'rinishidan
            ishlaydigan, amalda esa 1C tomonidan jim yutiladigan kalit eng yomon
            natijani beradi — bo'sh papka va «muvaffaqiyat» deb o'qilgan yurish.
         3. COM avtomatizatsiyasi QO'SHILMAYDI: u bazaga ULANADI (parol talab qiladi) va
            «faqat o'qish» kafolatidan tashqariga chiqadi.
    ⚠️ Zaxira yo'l MAVJUD va u ishlaydi: operator yig'uvchini O'Z sessiyasida bajaradi,
       agent esa natijani KUTADI (`wait_for_collector`).
    """
    operator, keyingi = failure_text(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
    return AutomaticRunDeclaration(
        status=AUTO_RUN_STATUS,
        implemented=AUTO_RUN_IMPLEMENTED,
        code=bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED,
        operator=operator,
        next_action=keyingi,
        reason=(
            "avtomatik bajarish yo'li QURILMAGAN: rasmiy hujjatlashtirilgan va xavfsiz "
            "yo'l bu mashinada tasdiqlanmagan (1C o'rnatilmagan), o'ylab chiqarilgan "
            "buyruq satri parametri qo'shilmaydi, COM avtomatizatsiyasi ham qo'shilmaydi"
        ),
        command=None,
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1C NING XAVFSIZLIK RADDI — NORMAL HOLAT
# ══════════════════════════════════════════════════════════════════════════════════════════
def security_refusal(reason: str, *, command=(), output_dir: str | None = None,
                     target: LaunchTarget | None = None,
                     collector_file: str | None = None) -> LaunchOutcome:
    """1C tashqi qayta ishlashni rad etdi — NORMAL natija, nuqson emas.

    ⚠️⚠️ XAVFSIZLIK ZAIFLASHTIRILMAYDI: keyingi qadam matnlari xavfsiz rejimni o'chirish,
         xavfsizlik profilini tahrirlash yoki rolga huquq qo'shishni TAVSIYA QILMAYDI
         (`SECURITY_REFUSAL_TEXT` izohiga qarang). Qarorni do'konning 1C administratori
         beradi, agent esa raddi QAYD etadi va to'xtaydi.
    ⚠️ Holat `FAILED_COLLECTOR_UNAVAILABLE`: 1C BOR, baza ham tanlangan, lekin yig'uvchi
       natija bermadi — ya'ni «javob YO'Q», «topilmadi» EMAS.
    """
    _need(reason in SECURITY_REFUSALS, bp.CODE_BRIDGE_SHAPE_INVALID,
          f"noma'lum radd sababi: {reason!r}; ruxsat etilganlari "
          f"{sorted(SECURITY_REFUSALS)}")
    matn, keyingi = SECURITY_REFUSAL_TEXT[reason]
    korsatma = (
        operator_instructions(target=target, mode=LAUNCH_MODE_OPERATOR,
                              collector_file=collector_file)
        if target is not None else (matn, keyingi)
    )
    return LaunchOutcome(
        mode=LAUNCH_MODE_OPERATOR, launched=det.TRI_FALSE,
        command=tuple(command) or ("<buyruq qurilmadi>",),
        instructions=korsatma, phase=bp.COLLECTOR_FAILED,
        code=bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED,
        state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
        operator=matn, next_action=keyingi, output_dir=output_dir,
        notes=(f"1C ning raddi qayd etildi: {reason}; xavfsizlik sozlamalari "
               f"O'ZGARTIRILMADI",),
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# BEKOR QILISH — KOOPERATIV
# ══════════════════════════════════════════════════════════════════════════════════════════
class CancelToken:
    """Kooperativ bekor qilish BAYROG'I — jarayon O'LDIRMAYDI.

    ⚠️⚠️ BU SINF JARAYONGA UMUMAN TEGMAYDI: u bitta sababni saqlaydi, kutish halqasi esa
         uni TEKSHIRADI va o'zi to'xtaydi. Shu bois «bekor qilish» 1C ni ham,
         operatorning sessiyasini ham yopmaydi.
    ⚠️ IDEMPOTENT va BIRINCHI SABAB QOLADI: ikkinchi bosish sababni o'zgartirmaydi —
       hisobotda «nega to'xtadi» savoliga BIR javob bo'lishi kerak.
    ⚠️ Bekor qilinganini «unutish» yo'li ATAYLAB YO'Q: bekor qilingan yurish davom
       etmaydi, u yangi yurish bilan boshlanadi (har yurish o'z papkasini oladi).
    """

    __slots__ = ("_reason",)

    def __init__(self) -> None:
        self._reason: str | None = None

    def cancel(self, reason: str = CANCEL_REASON_OPERATOR) -> None:
        """Bekor qilishni belgilaydi (sababsiz bekor qilish YO'Q)."""
        _need(isinstance(reason, str) and reason.strip() != "",
              bp.CODE_BRIDGE_SHAPE_INVALID,
              "bekor qilish sababi bo'sh bo'lmagan matn bo'lishi kerak")
        if self._reason is None:
            self._reason = reason

    @property
    def cancelled(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason


# ══════════════════════════════════════════════════════════════════════════════════════════
# KUTISH — CHEKLI, BEKOR QILINADIGAN, DIAGNOSTIKALI
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class WaitOutcome:
    """Kutishning natijasi: faza + (yiqilsa) uchlik + DIAGNOSTIKA.

    ⚠️ `ticks` va `elapsed_seconds` — MATN: hujjatga tushadigan sanoq matn bo'lishi kerak.
    ⚠️ `diagnostics` BEKOR QILINGANDA ham, VAQT TUGAGANDA ham SAQLANADI: «nima kutildi va
       nima topilmadi» savoli javobsiz qolmaydi. Ichida YO'L YO'Q — faqat fayl nomlari
       (ular shartnoma) va sanoqlar.
    ⚠️ `acceptance` FAQAT javob QABUL QILINGANDA to'ladi (`bridge_protocol.Acceptance`).
    """

    phase: str
    ticks: str
    elapsed_seconds: str
    diagnostics: tuple[str, ...] = ()
    acceptance: object | None = None
    code: str | None = None
    state_hint: str | None = None
    operator: str | None = None
    next_action: str | None = None

    @property
    def ok(self) -> bool:
        """Javob qabul qilindimi (`COLLECTOR_COMPLETE` fazasi)."""
        return self.state_hint is None and self.phase == bp.COLLECTOR_COMPLETE

    def __post_init__(self) -> None:
        _need(bp.is_phase(self.phase), bp.CODE_BRIDGE_SHAPE_INVALID,
              f"noma'lum ko'prik fazasi: {self.phase!r}")
        if self.state_hint is not None:
            _need(self.state_hint in st.FAILURE_STATES, bp.CODE_BRIDGE_SHAPE_INVALID,
                  f"state_hint yiqilish holati bo'lishi kerak: {self.state_hint!r}")
            _need(self.code is not None and bool(self.operator)
                  and bool(self.next_action), bp.CODE_BRIDGE_SHAPE_INVALID,
                  "yiqilishda kod + operator matni + keyingi qadam SHART (uchlik)")


def bundle_members(run_dir) -> tuple[str, ...]:
    """Yurish papkasidagi Phase 4 paketining fayl NOMLARI (papka yo'q bo'lsa — bo'sh).

    ⚠️⚠️ «YO'Q» va «O'QIB BO'LMADI» AJRATILGAN: papka hali yaratilmagan bo'lishi NORMAL
         (yig'uvchi yozmagan) va bo'sh ro'yxat qaytadi — paket to'liqligi keyin
         `PARTIAL_PACKAGE` bilan hal qilinadi. Huquq yetmasa esa ISTISNO
         (`BUNDLE_DIR_MISSING`): «ko'rolmadim» ni «bo'sh» deb o'qish yolg'on xulosa
         bo'lardi.
    ⚠️ FAQAT O'QISH: bu funksiya hech narsa yaratmaydi va O'CHIRMAYDI.
    """
    papka = pathlib.Path(run_dir) / BUNDLE_SUBDIR
    try:
        return tuple(sorted(a.name for a in papka.iterdir()))
    except (FileNotFoundError, NotADirectoryError):
        return ()
    except OSError as e:
        # ⚠️ Istisno MATNI ko'chirilmaydi — unda yo'l bo'ladi. Faqat TURI.
        raise LauncherError(cb.CODE_BUNDLE_DIR_MISSING,
                            f"paket papkasi o'qilmadi: {type(e).__name__}") from e


def wait_for_collector(*, run_dir, request, cancel: CancelToken | None = None,
                       timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                       poll_seconds: float = DEFAULT_POLL_SECONDS,
                       clock: Callable[[], float] = DEFAULT_CLOCK,
                       sleeper: Callable[[float], None] = DEFAULT_SLEEPER,
                       members: Callable[[], tuple[str, ...]] | None = None) -> WaitOutcome:
    """Yig'uvchining javobini KUTADI: kooperativ bekor qilish + CHEKLI vaqt.

    Halqa har aylanishda UCH savolni SHU TARTIBDA so'raydi:
      1. bekor qilindimi?   -> kutish TO'XTAYDI (`OPERATOR_CANCELLED` /
                               `ABORTED_BY_OPERATOR`), 1C YOPILMAYDI;
      2. javob + tugallanish belgisi BORMI? -> `bridge_protocol` darvozasi hal qiladi;
      3. vaqt tugadimi?     -> HALOL yiqilish (`WAIT_TIMEOUT` / `FAILED_TIMEOUT`).

    ⚠️⚠️ BEKOR QILISH TEKSHIRUVI BIRINCHI: operator tugmani bosgandan keyin agent yana
         bir marta fayl o'qib, «tasodifan» muvaffaqiyat deb qaytmasligi kerak — bekor
         qilingan yurish MUVAFFAQIYAT bilan tugamaydi.
    ⚠️⚠️ VAQT KIRISHDAN (`clock`) va UXLASH ham KIRISHDAN (`sleeper`): modul soatni o'zi
         olmaydi, shu bois test birorta soniya kutmaydi va natija DETERMINISTIK.
    ⚠️ Uxlash vaqti CHEGARADAN OSHMAYDI (`min`): aks holda agent muddatdan keyin ham
       uxlab turardi va `FAILED_TIMEOUT` kech kelardi.
    ⚠️ Javob SHAKLI yoki o'zligi mos kelmasa — `bridge_protocol` ning O'Z kodi bilan
       qaytadi (`STALE_OUTPUT`, `NONCE_MISMATCH`, `WRONG_COLLECTOR_VERSION`,
       `PARTIAL_PACKAGE`, `OUTPUT_PREDATES_REQUEST`, ...). Bu modul ikkinchi tekshiruv
       YOZMAYDI.
    ⚠️ HECH NARSA O'CHIRILMAYDI va YOZILMAYDI: halqa faqat O'QIYDI.
    """
    _need(isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0,
          bp.CODE_BRIDGE_SHAPE_INVALID,
          "kutish chegarasi MUSBAT bo'lishi kerak — cheksiz kutish YO'Q")
    _need(isinstance(poll_seconds, (int, float)) and poll_seconds > 0,
          bp.CODE_BRIDGE_SHAPE_INVALID, "so'rash qadami musbat bo'lishi kerak")
    fayllar = members if members is not None else (lambda: bundle_members(run_dir))

    boshlandi = clock()
    olchov = 0
    diagnostika: list[str] = []

    while True:
        otgan = max(0.0, clock() - boshlandi)
        if cancel is not None and cancel.cancelled:
            diagnostika.append(f"bekor qilish sababi: {cancel.reason}")
            return _cancelled(olchov, otgan, tuple(diagnostika))

        # ⚠️⚠️ BUZUQ HUJJAT HALQADAN ISTISNO BO'LIB CHIQMAYDI (TUZATILGAN NUQSON):
        #      `read_*` yaroqsiz JSON uchun `BridgeProtocolError` tashlaydi, va u
        #      ushlanmasa chaqiruvchi (bir bosishli oqim) yurish o'rtasida istisno bilan
        #      uzilardi — operator na faza, na keyingi qadam olardi.
        # ⚠️⚠️ «YARIM YOZILGAN» va «BUZUQ» AJRATILADI va ajrim TUGALLANISH BELGISIGA
        #      tayanadi: belgi shartnoma bo'yicha ENG OXIRIDA yoziladi, demak u FAYL
        #      bo'lib paydo bo'lmaguncha javob hali yozilayotgan bo'lishi MUMKIN va
        #      parse xatosi «hali tayyor emas» degani (kutish DAVOM etadi). Belgi
        #      paydo bo'lgandan keyin esa yig'uvchi ishini tugatganini AYTGAN bo'ladi —
        #      shu paytdagi o'qilmaydigan hujjat HAQIQIY rad etish
        #      (`BRIDGE_SHAPE_INVALID`), chunki u o'zi tugallangan deb da'vo qilyapti.
        belgi_fayli_bor = pr.done_marker_path(run_dir).exists()
        javob, javob_kodi = _oqib_kor(pr.read_response, run_dir)
        belgi, belgi_kodi = _oqib_kor(pr.read_done_marker, run_dir)
        buzuq = javob_kodi or belgi_kodi
        if belgi_fayli_bor and buzuq is not None:
            operator, keyingi = failure_text(buzuq, state=st.FAILED_COLLECTOR_UNAVAILABLE)
            diagnostika.append(f"hujjat O'QILMADI, javob RAD etildi: {buzuq}")
            return WaitOutcome(
                phase=bp.COLLECTOR_FAILED, ticks=str(olchov),
                elapsed_seconds=_soniya(otgan), diagnostics=tuple(diagnostika),
                code=buzuq, state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
                operator=operator, next_action=keyingi,
            )
        if javob is not None and belgi is not None:
            try:
                qabul = pr.accept_collector_output(request=request, response=javob,
                                                   done=belgi, bundle_files=fayllar())
            except pr.BridgeProtocolError as e:
                operator, keyingi = failure_text(e.code,
                                                 state=st.FAILED_COLLECTOR_UNAVAILABLE)
                diagnostika.append(f"javob RAD etildi: {e.code}")
                return WaitOutcome(
                    phase=bp.COLLECTOR_FAILED, ticks=str(olchov),
                    elapsed_seconds=_soniya(otgan), diagnostics=tuple(diagnostika),
                    code=e.code, state_hint=st.FAILED_COLLECTOR_UNAVAILABLE,
                    operator=operator, next_action=keyingi,
                )
            return _accepted(qabul, olchov, otgan, tuple(diagnostika))

        yoq = [nom for nom, bor in ((pr.RESPONSE_FILE, javob), (pr.DONE_FILE, belgi))
               if bor is None]
        if otgan >= timeout_seconds:
            diagnostika.append(f"vaqt tugadi; yetishmagan fayl(lar): {', '.join(yoq)}")
            operator, keyingi = failure_text(cb.CODE_WAIT_TIMEOUT,
                                             state=st.FAILED_TIMEOUT)
            return WaitOutcome(
                phase=bp.WAITING_FOR_COLLECTOR, ticks=str(olchov),
                elapsed_seconds=_soniya(otgan), diagnostics=tuple(diagnostika),
                code=cb.CODE_WAIT_TIMEOUT, state_hint=st.FAILED_TIMEOUT,
                operator=operator, next_action=keyingi,
            )

        olchov += 1
        diagnostika.append(f"kutilmoqda ({olchov}); yetishmagan fayl(lar): "
                           f"{', '.join(yoq)}")
        sleeper(min(float(poll_seconds), max(0.0, timeout_seconds - otgan)))


def _oqib_kor(oqigich, run_dir):
    """`(hujjat | None, rad etish kodi | None)` — ISTISNO TASHLAMAYDI.

    ⚠️ «Fayl YO'Q» (`None`, kod ham `None`) va «fayl bor, lekin O'QILMADI» (`None` +
       kod) AJRATILGAN: operatorning qadami ikkisida boshqa va ularni bitta natijaga
       qo'shib yuborish sababni almashtirardi.
    """
    try:
        return oqigich(run_dir), None
    except pr.BridgeProtocolError as e:
        return None, e.code


def _soniya(qiymat: float) -> str:
    """Soniyalarni MATN qilib qaytaradi (hujjatda son bo'lmaydi)."""
    return f"{int(qiymat)}"


def _cancelled(olchov: int, otgan: float, diagnostika: tuple[str, ...]) -> WaitOutcome:
    """Operator to'xtatdi: `OPERATOR_CANCELLED` + `ABORTED_BY_OPERATOR`.

    ⚠️⚠️ SHU YERDA `ABORTED_BY_OPERATOR` HOLATI ROSTDAN ISHLATILADI (CP2 da u faqat
         lug'atda turardi va buni test qulflagan — `STATES_TEST_SOROVI` ga qarang).
    ⚠️ Bu nuqson EMAS: shu bois diagnostika SAQLANADI va 1C ga tegilmaydi.
    """
    operator, keyingi = failure_text(bp.CODE_OPERATOR_CANCELLED)
    return WaitOutcome(
        phase=bp.COLLECTOR_FAILED, ticks=str(olchov), elapsed_seconds=_soniya(otgan),
        diagnostics=diagnostika, code=bp.CODE_OPERATOR_CANCELLED,
        state_hint=st.ABORTED_BY_OPERATOR, operator=operator, next_action=keyingi,
    )


def _accepted(qabul, olchov: int, otgan: float,
              diagnostika: tuple[str, ...]) -> WaitOutcome:
    """Javob KELDI. ⚠️ `FAILED`/`CANCELLED` javobi ham JAVOB — fazasi boshqa."""
    kod = getattr(qabul, "code", None)
    faza = getattr(qabul, "phase", bp.COLLECTOR_COMPLETE)
    holat = getattr(qabul, "status", "?")
    if faza == bp.COLLECTOR_COMPLETE and kod is None:
        # ⚠️⚠️ YIG'UVCHINING O'Z HOLATI DIAGNOSTIKADA ATALIB QOLADI (`SUCCESS` yoki
        #      `PARTIAL`): `PARTIAL` javob ham shu shoxdan o'tadi, chunki paket TO'LIQ va
        #      hukmni QUVUR beradi (Phase 4 validatori kodi `2` ni hurmat qilib
        #      to'xtaydi). Lekin u JIMGINA «qabul qilindi» bo'lib qolmasligi kerak —
        #      operator yarim natijani YARIM deb ko'rishi SHART.
        return WaitOutcome(phase=faza, ticks=str(olchov), elapsed_seconds=_soniya(otgan),
                           diagnostics=diagnostika + (
                               f"yig'uvchining javobi QABUL qilindi; yig'uvchi aytgan "
                               f"holat: {holat}",),
                           acceptance=qabul)
    # ⚠️ Yig'uvchi «yiqildim» yoki «bekor qilindi» deb AYTDI: javob bor, natija yo'q.
    aniq_kod = kod or cb.CODE_EXIT_CODE_NONZERO
    holat_hint = (st.ABORTED_BY_OPERATOR if aniq_kod == bp.CODE_OPERATOR_CANCELLED
                  else st.FAILED_COLLECTOR_UNAVAILABLE)
    operator, keyingi = failure_text(aniq_kod, state=holat_hint)
    return WaitOutcome(
        phase=faza, ticks=str(olchov), elapsed_seconds=_soniya(otgan),
        diagnostics=diagnostika + (f"yig'uvchining javobi: {holat}",),
        acceptance=qabul, code=aniq_kod, state_hint=holat_hint, operator=operator,
        next_action=keyingi,
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ Testlar ham shu invariantlarni qulflaydi, lekin import paytida yiqilish eng arzon
#    darvoza: test yurgizilmagan yo'l ham shu yerdan o'tadi.
assert LAUNCH_MODES == ("agent_opens", "operator_opens"), "rejim nomlari SHARTNOMA"
assert AUTO_RUN_STATUS == "UNVERIFIED_ON_REAL_1C", \
    "avtomatik ishga tushirish holati AYNAN shu belgi bilan ataladi"
assert AUTO_RUN_IMPLEMENTED == det.TRI_FALSE and ATTACH_TO_RUNNING == det.TRI_FALSE, \
    "qurilmagan qobiliyat «false» deb ATALADI (jim qoldirilmaydi)"
assert (SWITCH_FILE_TARGET, SWITCH_SERVER_TARGET) == pr.ALLOWED_TARGET_SWITCHES, \
    "nishon kaliti FAQAT ko'prik shartnomasidan olinadi (ikkinchi nusxa yo'q)"
assert set(SECURITY_REFUSAL_TEXT) == set(SECURITY_REFUSALS), \
    "xavfsizlik raddi lug'ati YOPIQ va to'liq"
assert all(a.strip() and b.strip() for a, b in SECURITY_REFUSAL_TEXT.values()), \
    "radd matni va keyingi qadam BO'SH bo'lmasin"
assert KNOWN_CODES >= {bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, bp.CODE_OPERATOR_CANCELLED,
                       cb.CODE_WAIT_TIMEOUT}, "ishlatiladigan kodlar ro'yxatda bo'lishi SHART"
assert all(bp.BRIDGE_CODE_RE.fullmatch(c) for c in KNOWN_CODES), \
    "kod `[A-Z][A-Z0-9_]*` shaklida bo'lishi kerak"
for _holat in (st.FAILED_TIMEOUT, st.FAILED_COLLECTOR_UNAVAILABLE, st.ABORTED_BY_OPERATOR):
    assert NEXT_ACTION_MARKER in st.FAILURE_MEANING[_holat], (
        f"{_holat}: ma'no matnida «{NEXT_ACTION_MARKER}» bo'lishi SHART — keyingi qadam "
        f"shu matndan OLINADI va IKKINCHI lug'at yozilmaydi"
    )
del _holat
assert st.ABORTED_BY_OPERATOR in st.FAILURE_STATES and len(st.FAILURE_STATES) == 11, \
    "bu modul yangi holat QO'SHMAYDI: bekor qilish MAVJUD holatga tushadi"
