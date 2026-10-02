# -*- coding: utf-8 -*-
"""BIR BOSISHLI OQIM — MAVJUD quvurni OPERATOR fazalariga BOG'LAYDI (yangi dvigatel EMAS).

Operator uchun bitta buyruq, ichida esa HECH QANDAY yangi qaror qatlami yo'q:

    DETECTING_1C          -> `detector` (`ui.UiModel.refresh_environment`)
    NO_1C                 -> `states.FAILED_NO_1C` (hukm `presence_verdict` dan)
    DISCOVERING_INFOBASES -> AYNI skanerning infobaza ro'yxati
    SELECT_TARGET         -> `bridge_protocol.assert_unique_target` (qaror OPERATORDA)
    PREPARING_COLLECTOR   -> `bridge_protocol.prepare_run_dir` + `write_request`
    LAUNCHING_1C          -> `launcher.open_infobase` (FAIL-CLOSED darvoza, HAQIQIY kirish)
    WAITING_FOR_COLLECTOR -> `launcher.wait_for_collector` (CHEKLI + KOOPERATIV bekor)
    COLLECTOR_COMPLETE    -> `bridge_protocol.accept_collector_output` (kutish ichida)
    COLLECTOR_FAILED      -> AYNI darvozaning rad etishi (har sabab O'Z kodi bilan)
    INGESTING / ANALYZING -> `ui.UiModel.start()` ichidagi `pipeline.run_pipeline`
    COMPLETE              -> `result_package` yozgan va TEKSHIRGAN papka

⚠️⚠️ NEGA BU MODUL JUDA KICHIK: brief «ikkinchi razvedka dvigateli qurilmaydi / semantik
     dublikat bo'lmaydi» deydi. Shu bois bu yerda IKKINCHI validator, IKKINCHI graf,
     IKKINCHI analitik va IKKINCHI holat mashinasi YO'Q. Yurishning O'ZINI mavjud
     `ui.UiModel.start()` yuritadi; bu modul faqat (1) ko'prik hujjatlarini tayyorlaydi,
     (2) yig'uvchi javobini SHARTNOMA bo'yicha qabul qiladi, (3) mavjud HOLATLARNI
     operator KO'RADIGAN fazaga tarjima qiladi.
⚠️⚠️ HOLAT HUKMI MANBASI O'ZGARMAYDI: yakuniy `state` quvur yozgan `agent_status.json` dan
     keladi (`ui.RunOutcome.state`). Bu modul «COMPLETE» deb O'ZI YOZMAYDI.

⚠️⚠️ `.epf` IKKILIK FAYLI QURILGAN DEB AYTILMAYDI. Yig'uvchining MANBA matni tayyor
     (`bridge_phase.EPF_SOURCE_READY`), ikkilik `.epf` ni esa 1C konfiguratorida OPERATOR
     yig'adi. Shu bois «bir bosishda hammasi tayyor» DEGAN DA'VO YO'Q: hozirgi haqiqiy yo'l
     — operator yig'uvchini O'Z 1C sessiyasida bir marta ochadi, agent esa yurishning O'Z
     papkasini kuzatadi. Operator FAYLLARNI QO'LDA KO'CHIRMAYDI: chiqish papkasi
     `request.json` da ko'rsatiladi va u yurishning papkasi ichida.

⚠️ 1C GA ULANMAYDI, tarmoqqa chiqmaydi, COM ishlatmaydi, o'ylab chiqarilgan buyruq satri
   parametri YO'Q. Avtomatik ishga tushirish holati `UNVERIFIED_ON_REAL_1C` bo'lib qoladi
   (`bridge_phase.AUTOMATIC_LAUNCH_VERIFICATION`): bu modulda jarayon ochadigan kod YO'Q —
   ochish ALMASHTIRILADIGAN `opener` ga qoladi (`launcher.Opener`) va u STANDART holda
   BERILMAYDI, ya'ni shipped yo'lda 1C ni OPERATOR ochadi.
⚠️⚠️ ISHGA TUSHIRISH DARVOZASI HAQIQIY KIRISHGA BOG'LANGAN: `run_one_click`
     `operator_confirmed` ni PARAMETR bo'lib oladi va `opener` berilgan holda tasdiq
     yo'qligi yurishni `COLLECTOR_EXECUTION_NOT_ALLOWED` bilan TO'XTATADI (ochuvchi
     CHAQIRILMAYDI). Ilgari darvoza QOTIRILGAN `False` bilan chaqirilib, istisnosi darrov
     yutilardi — ya'ni BEZAK edi.
⚠️ BEKOR QILISH KOOPERATIV va u ENDI YETIB BORADI: `run_one_click(cancel=...)`
   `launcher.CancelToken` ni kutish halqasiga uzatadi, agent KUTISHNI to'xtatadi va holat
   `states.ABORTED_BY_OPERATOR` bo'ladi. Bu modulda `taskkill`, jarayon daraxtini tugatish
   yoki `rmtree` naqshi YO'Q. Papka BO'SH bo'lmasa — TO'XTAYDI, tozalamaydi.
⚠️ KREDENSIAL: parol uchun maydon ham, bayroq ham, kirish parametri ham YO'Q. Parolni 1C
   ning O'Z oynasi oladi.

⚠️⚠️ HALOL QAYD — `agent_status.json` GA KO'PRIK KALITLARI YOZILMADI. `status.py` bu
     bosqichda berilmagan fayl va unda `bridge_phase`/`run_id` uchun maydon YO'Q;
     `ui.UiModel.notes` esa yurish yozuviga UMUMAN ko'chmaydi (u ishlatilmaydigan maydon).
     Shu bois ko'prik o'zligi FAQAT `OneClickOutcome` da va operator ekranida qoladi, va
     `status.py` egasiga ANIQ so'rov qoldirilgan (modul oxiridagi `STATUS_SO_ROVI`).
     Soxta kalit yozish yoki `notes` ga tiqishtirish — aynan Phase 4 ni yiqitgan «ikki
     haqiqat» naqshi bo'lardi.
⚠️⚠️ `nonce` HISOBOTGA YOZILMAYDI va bu ATAYLAB: u soxta javobni ANIQLASHNING yagona
     vositasi. Natija paketi qo'ldan-qo'lga o'tadi, yurish papkasi esa operatorda qoladi.
     `OneClickOutcome` da ham `nonce` ning O'ZI emas, UZUNLIGI turadi.
"""
from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field

from . import BUNDLE_SUBDIR
from . import bridge_phase as bp
from . import bridge_protocol as bpr
from . import detector as det
from . import launcher as ln
from . import states as st

# ══════════════════════════════════════════════════════════════════════════════════════════
# KUTILADIGAN YIG'UVCHI O'ZLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️⚠️ TUZATILGAN P0 — IKKI O'ZLIK ARALASHGAN EDI. `response.json` ni YOZADIGAN modul —
#:      KO'PRIK QATLAMI, ya'ni javobdagi `collector` maydoni KO'PRIKNING o'zligini
#:      ko'rsatadi: `integrations/1c/collector/VERSION.json` va
#:      `integrations/1c/collector/BinOSDiscoveryCollector.bsl` AYNAN shu nom va versiyani
#:      e'lon qiladi. Agent esa ICHKI yig'uvchining o'zligini
#:      (`BinOSDiscovery` / `0.2.0-UNVERIFIED`) kutardi — natijada HAR BIR haqiqiy javob
#:      `WRONG_COLLECTOR_VERSION` bilan rad etilardi, ya'ni bir-bosishli ko'prik haqiqiy
#:      1C da HECH QACHON ishlamasdi. To'plam yashil bo'lishi buni YASHIRARDI.
#: ⚠️⚠️ IKKI O'ZLIK ARALASHTIRILMAYDI va ikkinchisi YO'QOLMAYDI: ICHKI yig'uvchi
#:      (`integrations/1c/extractor/BinOSDiscovery.bsl` dagi `ОписаниеСборщика` —
#:      `BinOSDiscovery` / `0.2.0-UNVERIFIED`) o'z o'zligini Phase 4 shartnomasi bo'yicha
#:      `bundle/export.json` ning `collector` maydonida qoldiradi va u yerda
#:      TEKSHIRILADI. Ko'prik javobi uni `notes` da eslatishi mumkin, lekin
#:      `response.collector` ga YOZMAYDI.
#: ⚠️ Bu yerdagi qiymat O'YLAB CHIQARILMAGAN: `tests/test_agent_one_click.py` uni
#:    `VERSION.json` va ko'prik MANBASI bilan solishtiradi — ikki haqiqat paydo bo'lishi
#:    test paytida YIQILADI.
#: ⚠️ Mos kelmasa yurish RAD etiladi (`WRONG_COLLECTOR_VERSION`) — JIMGINA o'tmaydi.
#: ⚠️ `-source` qo'shimchasi SHARTNOMA: `.epf` IKKILIK fayli QURILMAGAN (holat AYNAN
#:    `bridge_phase.EPF_SOURCE_READY`) va versiya satri shuni AYTIB turadi.
#: ⚠️ Buyruq satriga versiya bayrog'i QO'SHILMAYDI: eski yig'uvchini «mayli» deb o'tkazish
#:    yo'li ochilsa, to'liq bo'lmagan paket bo'yicha xulosa chiqarilardi. Kerak bo'lsa
#:    chaqiruvchi `expected_collector` ni API orqali beradi.
EXPECTED_COLLECTOR_NAME = "BinOSDiscoveryCollector"
EXPECTED_COLLECTOR_VERSION = "0.1.0-source"

#: Nomsiz baza uchun xesh KIRISHI. ⚠️ Bu EKRAN MATNI EMAS: faqat `target_fingerprint` ga
#: beriladi, chunki xesh bo'sh bo'lmagan nom talab qiladi. Ikki nomsiz baza bir xil nom
#: olishi — NUQSON emas: ularning `locator` i farq qiladi, bir xil bo'lsa esa tanlov
#: OPERATORGA qaytadi (`TARGET_AMBIGUOUS`).
UNNAMED_TARGET = "(nomsiz baza)"

#: `request.json` ga yoziladigan izohlar. ⚠️ YO'L YO'Q, `kalit: qiymat` namunasi YO'Q,
#: misol kirish ma'lumoti YO'Q — hujjat `redact.scan` darvozasidan o'tadi.
REQUEST_NOTES: tuple[str, ...] = (
    "Yig'uvchi FAQAT O'QIYDI: 1C da hech narsa yozilmaydi, o'zgartirilmaydi va "
    "o'chirilmaydi.",
    "Natija shu yurishning papkasiga yoziladi; tugallanish belgisi ENG OXIRIDA yoziladi.",
    "Kirish ma'lumotini 1C ning O'Z oynasi so'raydi — agent uni ko'rmaydi va hech qayerga "
    "yozmaydi.",
)

#: Kutish paytida operatorga KO'RSATILADIGAN matn.
#: ⚠️⚠️ MATN KANALI (soxta `WaitTick` EMAS): `collector_bridge.WaitTick` ning matni paket
#:      FAYLLARI haqida gapiradi va uni ko'prik qo'l berishini kutishga yopishtirish
#:      operatorga YOLG'ON sabab ko'rsatardi.
#: ⚠️ YO'L YO'Q: bu matn jurnalga tushadi.
WAIT_NOTICE = ("kutilmoqda: yig'uvchi ishini tugatganini hali bildirmadi "
               "(1C oynasini yig'uvchi tugatguncha yopmang)")

#: `status.py` EGASIGA SO'ROV (shu relizda BAJARILMAGAN, da'vo ham qilinmaydi).
STATUS_SO_ROVI = (
    "`status.AgentStatus` ga ko'prik o'zligi uchun IKKI kalit kerak: `bridge_phase` "
    "(`bridge_phase.BRIDGE_PHASES` dan bitta nom) va `run_id` "
    "(`status.RUN_ID_RE` shaklida). `nonce` SO'RALMAYDI va yozilmasligi SHART — u soxta "
    "javobni aniqlashning yagona vositasi, natija paketi esa qo'ldan-qo'lga o'tadi."
)


class OneClickError(RuntimeError):
    """Bir bosishli oqimning O'Z nuqsoni (shartnoma buzilishi), muhit muammosi EMAS.

    ⚠️ Operator xatosi bu istisno bilan QAYTMAYDI: operatorga tegishli har sabab
       `OneClickOutcome` bo'lib, ko'prik kodi va keyingi qadam bilan qaytadi.
    """


# ══════════════════════════════════════════════════════════════════════════════════════════
# HOLAT TARTIBI — `states.py` DAN HISOBLANADI (qo'lda YOZILMAYDI)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Normal holatlarning TARTIB raqami. ⚠️ Manba — `states.NORMAL_STATES`: ikkinchi ro'yxat
#: yozilsa, u bir kun birinchisidan ajralib ketardi.
_NORMAL_INDEX: dict[str, int] = {s: i for i, s in enumerate(st.NORMAL_STATES)}

#: Faza tartibi (operator ko'radigan tartib) — `bridge_phase.BRIDGE_PHASES` dan.
_PHASE_INDEX: dict[str, int] = {p: i for i, p in enumerate(bp.BRIDGE_PHASES)}


def failure_sources(state: str) -> tuple[str, ...]:
    """Shu YIQILISH qaysi NORMAL holatlardan yozilishi mumkin (`states.TRANSITIONS` dan).

    ⚠️ Jadval YAGONA manba: «qaysi yiqilish qayerdan» degan savolga javobni bu modul
       O'ZIDAN YOZMAYDI.
    """
    if not st.is_known(state):
        raise OneClickError(f"noma'lum holat: {state!r}")
    return tuple(s for s in st.NORMAL_STATES if state in st.TRANSITIONS[s])


def assert_outcome_consistent(phase: str, state: str) -> None:
    """Faza va holat ZID EMASLIGI (fail-closed darvoza).

    Ruxsat etilgan uchta vaziyat:
      (a) holat — fazaning O'Z holati (`PHASE_TO_STATE`);
      (b) holat fazaning holatidan RUXSAT ETILGAN o'tish (`states.can_transition`);
      (c) holat — KEYINGI qadamdagi yiqilish: yiqilishning HAMMA manbasi fazaning
          holatidan KEYIN turadi. Bu (c) ataylab bor, chunki ko'prik qatlami ATAYLAB
          hamma holatga faza qo'ymaydi (`GRAPH_BUILD`, `REPORT`, `REVALIDATE`,
          `OPTIONAL_APPROVED_PROBES` operator uchun alohida ekran emas).

    ⚠️⚠️ TAQIQLANGAN vaziyat AYNAN BITTA va eng xavflisi: holat fazadan ORQADA bo'lishi,
         ya'ni ekranda «tahlil qilinyapti» turganda yiqilish sababi «1C topilmadi» bo'lishi.
         Phase 4 da yiqilish sababining almashib ketishi operatorni butunlay boshqa yo'lga
         yuborgan edi.
    """
    bp.phase_state(phase)        # noma'lum faza — ISTISNO (`bridge_phase` darvozasi)
    if not st.is_known(state):
        raise OneClickError(f"noma'lum holat: {state!r} — holat nomlari `states.py` da")
    faza_holati = bp.phase_state(phase)
    if state == faza_holati or st.can_transition(faza_holati, state):
        return
    if st.is_failure(state):
        manbalar = failure_sources(state)
        joriy = _NORMAL_INDEX.get(faza_holati)
        if manbalar and joriy is not None and all(
                _NORMAL_INDEX.get(m, -1) > joriy for m in manbalar):
            return
    raise OneClickError(
        f"faza ({phase} -> {faza_holati}) va holat ({state}) ZID: holat fazadan ORQADA "
        f"bo'lishi mumkin emas — yiqilish sababi almashib ketardi"
    )


def phase_for_state(state: str, *, reached: str) -> str:
    """Holatga MOS faza: holatning O'Z fazasi bo'lsa — u, aks holda ERISHILGAN faza.

    ⚠️ `phases_for_state` ko'p faza qaytarsa (masalan `METADATA_DISCOVERY` — uchta), qaror
       ERISHILGAN fazada qoladi: fazani «oldinga» surib qo'yish operatorga bajarilmagan
       qadamni bajarilgan deb ko'rsatardi.
    ⚠️ Natija HAR DOIM `assert_outcome_consistent` dan o'tadi (chaqiruvchida).
    """
    fazalar = bp.phases_for_state(state)
    if len(fazalar) == 1 and _PHASE_INDEX[fazalar[0]] >= _PHASE_INDEX[reached]:
        return fazalar[0]
    return reached


# ══════════════════════════════════════════════════════════════════════════════════════════
# FAZA HODISASI va YAKUNIY NATIJA
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class PhaseEvent:
    """Operator KO'RADIGAN bitta faza. ⚠️ `text` HECH QACHON bo'sh bo'lmaydi."""

    phase: str
    state: str
    text: str
    #: Shu fazaga tegishli QO'SHIMCHA fakt (bo'sh bo'lishi mumkin). ⚠️ YO'L YOZILMAYDI.
    detail: str = ""


@dataclass(frozen=True)
class OneClickOutcome:
    """Bir bosishli yurishning YAKUNI — operator uchun ham, mashina uchun ham.

    ⚠️ `code` — FAQAT `bridge_phase.BRIDGE_CODES` dan (yoki `None`), ya'ni unga
       `failure_triple` DOIM topiladi: operator matni va keyingi qadam KAFOLATLANGAN.
    ⚠️ `run_code` — mavjud qatlamning (`ui.RunOutcome.code`) kodi AYNI holda: u qayta
       talqin QILINMAYDI va ko'prik kodi bilan ARALASHTIRILMAYDI.
    ⚠️ `run_dir` FAQAT operatorning O'Z ekraniga chiqadi (ui ning «natija papkasi:» qatori
       bilan AYNI qoida): hisobotga, izohga va hujjatga yo'l YOZILMAYDI.
    """

    phase: str
    state: str
    detail: str
    code: str | None = None
    run_code: str | None = None
    run_id: str | None = None
    #: ⚠️ `nonce` NING O'ZI EMAS, uzunligi: qiymat yurish papkasida qoladi.
    nonce_len: int = 0
    run_dir: str | None = None
    result_dir: str | None = None
    events: tuple[PhaseEvent, ...] = ()
    problems: tuple[str, ...] = ()
    #: Tugallanish belgisi NECHA marta «hali yo'q» deb o'lchandi (0 — kutilmadi).
    waited_ticks: int = 0
    #: ⚠️ YURISH BOSHLANMADI (qaror OPERATORDA): holat YAKUNIY emas. Chiqish kodi `2`.
    waiting_for_operator: bool = False

    def __post_init__(self) -> None:
        # ⚠️ DARVOZA OBYEKT QURILGANDA: zid natija umuman tug'ilmasin.
        assert_outcome_consistent(self.phase, self.state)
        if self.code is not None:
            bp.failure_triple(self.code)      # noma'lum kod — ISTISNO
        if self.waiting_for_operator and st.is_terminal(self.state):
            raise OneClickError(
                "«qaror operatorda» YAKUNIY holat bilan birga bo'lmaydi: yakunlangan "
                "yurish operatorni kutmaydi")

    @property
    def is_failure(self) -> bool:
        return st.is_failure(self.state)

    @property
    def is_complete(self) -> bool:
        return self.state == st.COMPLETE

    def operator_text(self) -> str:
        """Operator uchun NIMA bo'ldi. ⚠️ Matn MANBADAN olinadi, bu yerda yozilmaydi."""
        if self.code is not None:
            return bp.failure_triple(self.code).operator
        if st.is_failure(self.state):
            return st.failure_meaning(self.state, presence_verdict=self._verdict())
        return bp.phase_text(self.phase)

    def next_action(self) -> str:
        """Keyingi qadam. ⚠️ Nosozlik uchligi bo'lsa — AYNAN uning uchinchi qismi."""
        if self.code is not None:
            return bp.failure_triple(self.code).next_action
        if st.is_failure(self.state):
            # ⚠️ `failure_meaning` ikki qismdan (nima bo'ldi + keyingi qadam) va u YAGONA
            #    manba: ikkinchi matn yozish hisobot bilan ziddiyat yasardi.
            return st.failure_meaning(self.state, presence_verdict=self._verdict())
        return bp.phase_text(self.phase)

    def _verdict(self) -> str | None:
        """`FAILED_NO_1C` ning ma'nosi hukmga bog'liq (`absent` / `unknown`)."""
        return self._presence_verdict or None

    #: ⚠️ Hukm KO'CHIRILADI, QAYTA HISOBLANMAYDI: u `detector` da tug'iladi.
    _presence_verdict: str = ""


# ══════════════════════════════════════════════════════════════════════════════════════════
# FAZA OQIMI — faqat OLDINGA
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class _Oqim:
    """Fazalarni YOZIB BORADI va faqat OLDINGA yurishini ta'minlaydi.

    ⚠️ NEGA FAQAT OLDINGA: operator ekranida «tahlil» dan keyin «1C qidirilyapti» chiqishi
       — yurish qayta boshlandi degan YOLG'ON xabar. Orqaga qadam ISTISNO beradi.
    """

    on_event: Callable[[PhaseEvent], None] | None = None
    events: list[PhaseEvent] = field(default_factory=list)

    @property
    def reached(self) -> str:
        return self.events[-1].phase if self.events else bp.DETECTING_1C

    @property
    def reached_index(self) -> int:
        return _PHASE_INDEX[self.reached] if self.events else -1

    def emit(self, phase: str, detail: str = "") -> PhaseEvent:
        if _PHASE_INDEX[phase] <= self.reached_index:
            raise OneClickError(
                f"faza ORQAGA qaytdi: {self.reached} -> {phase} — operator ekranida bu "
                f"«yurish qayta boshlandi» degan yolg'on xabar bo'lardi")
        hodisa = PhaseEvent(phase=phase, state=bp.phase_state(phase),
                            text=bp.phase_text(phase), detail=detail)
        self.events.append(hodisa)
        if self.on_event is not None:
            self.on_event(hodisa)
        return hodisa


# ══════════════════════════════════════════════════════════════════════════════════════════
# NISHON O'ZLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
def target_fingerprint_of(infobase) -> str:
    """Infobazaning KREDENSIALSIZ xeshi (`bridge_protocol.target_fingerprint`).

    ⚠️ XOM `locator` FAQAT xesh ichiga kiradi va protokolga YOZILMAYDI.
    """
    return bpr.target_fingerprint(
        kind=infobase.kind,
        name=infobase.name if infobase.name else UNNAMED_TARGET,
        locator=infobase.locator,
    )


def _select_target(model, select_index):
    """Nishonni tanlaydi yoki tanlovni OPERATORGA qaytaradi.

    Qaytaradi: `(fingerprint, infobase)` yoki `(None, None)` — tanlov operatorda.

    ⚠️⚠️ AGENT O'ZI TANLAMAYDI: ikki baza bir xil darajada mos kelsa, noto'g'ri bazadan
         chiqqan hisobot O'ZINI TO'LIQ deb ko'rsatardi — bu jimgina xato. Shu bois
         `assert_unique_target` darvozasi: BITTA nishon qolmasa — `TARGET_AMBIGUOUS`.
    ⚠️ AYNI bazaning ikki marta e'lon qilinishi NOANIQLIK EMAS: xeshlar bir xil bo'lsa
       darvoza bitta nishon ko'radi (shu bois ro'yxat uzunligi emas, XESH sanaladi).
    ⚠️ `requires_auth` bu oqimda YIQILISH EMAS (`FAILED_AUTH_REQUIRED` CHIQARILMAYDI):
       agent 1C ga ULANMAYDI va parol UZATMAYDI — kirish ma'lumotini 1C ning O'Z oynasi
       so'raydi. `FAILED_AUTH_REQUIRED` paketli yo'lning holati bo'lib qoladi.
    """
    env = model.environment
    xeshlar = [target_fingerprint_of(ib) for ib in env.infobases]
    if select_index is not None:
        model.select_target(select_index)       # oraliqdan tashqari — `ui.UiError`
        nishon = model.selected_infobase()
        return target_fingerprint_of(nishon), nishon
    try:
        xesh = bpr.assert_unique_target(xeshlar)
    except bpr.BridgeProtocolError:
        return None, None
    nishon = env.infobases[xeshlar.index(xesh)]
    model.select_target(xeshlar.index(xesh))
    return xesh, nishon


# ══════════════════════════════════════════════════════════════════════════════════════════
# TUGALLANISH BELGISINI KUTISH — CHEKLI
# ══════════════════════════════════════════════════════════════════════════════════════════
def _kutish_kanali(sleeper, on_wait):
    """`launcher.wait_for_collector` ning `sleeper` iga OPERATOR matnini ulaydi.

    ⚠️⚠️ NEGA SHU YO'L: kutish dvigateli `launcher.wait_for_collector` da va u IKKINCHI
         NUSXADA YOZILMAYDI. Unda `on_wait` kanali yo'q — uning o'rniga `diagnostics`
         bor, lekin diagnostika yurish TUGAGANDAN KEYIN qaytadi, operator esa kutish
         PAYTIDA «osilgan emas» degan belgini ko'rishi kerak. Halqa har aylanishda AYNAN
         bir marta `sleeper` ni chaqiradi, demak matn har o'lchovda bir marta chiqadi va
         SOXTA hodisa to'qib chiqarilmaydi.
    ⚠️ `on_wait` berilmasa ORIGINAL `sleeper` qaytadi: o'rama ham, qo'shimcha chaqiruv ham
       bo'lmaydi.
    """
    if on_wait is None:
        return sleeper

    def _uxla(soniya: float) -> None:
        on_wait(WAIT_NOTICE)
        sleeper(soniya)

    return _uxla


def _bundle_file_names(bundle_dir) -> tuple[str, ...]:
    """Paket papkasining ILDIZIDAGI fayl nomlari (papka yo'q bo'lsa — bo'sh)."""
    p = pathlib.Path(bundle_dir)
    if not p.is_dir():
        return ()
    return tuple(sorted(x.name for x in p.iterdir() if x.is_file()))


# ══════════════════════════════════════════════════════════════════════════════════════════
# ISHGA TUSHIRISH — `launcher` ning O'ZI (ikkinchi abstraksiya YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
def _launch_target(infobase) -> "ln.LaunchTarget":
    """`detector.Infobase` -> `launcher.LaunchTarget`, NOM FALLBACK'i AYNI qoida bilan.

    ⚠️⚠️ NOM MANBASI BITTA: `target_fingerprint_of` nomsiz baza uchun `UNNAMED_TARGET` ni
         beradi, shu bois ishga tushirish nishoni ham AYNAN shu fallback bilan quriladi.
         `launcher.LaunchTarget.from_infobase` nomsiz yozuvni RAD etadi (o'z yo'lida bu
         to'g'ri), lekin bu oqimda nishon ALLAQACHON tanlangan va uning XESHI
         `request.json` ga yozilgan — ya'ni ikki xil nom qo'yilsa ikki xil xesh chiqib,
         1C ochiladigan baza bilan so'rovdagi nishon JIMGINA ajralib ketardi.
    """
    return ln.LaunchTarget(
        kind=infobase.kind,
        locator=infobase.locator,
        name=infobase.name if infobase.name else UNNAMED_TARGET,
    )


def _launch_1c(infobase, *, env, fingerprint: str, output_dir: str,
               operator_confirmed: bool, opener):
    """1C ni ochish BUYRUG'INI `launcher` da quradi va (ochuvchi bo'lsa) ROSTDAN ochadi.

    Qaytaradi: `(launcher.LaunchOutcome | None, launcher kodi | None)`.

    ⚠️⚠️ BU FUNKSIYA ISTISNO TASHLAMAYDI: `launcher` ning o'z kodlari (`EXE_MISSING`,
         `BUNDLE_DIR_MISSING`) KO'PRIK kodlari EMAS, demak ularni `OneClickOutcome.code`
         ga qo'yib bo'lmaydi (u `bridge_phase.failure_triple` dan kod talab qiladi).
         Shu bois kod ALOHIDA qaytadi va chaqiruvchi uni operator FAKTI qilib ko'rsatadi,
         KO'PRIK kodi deb ATAMAYDI.
    ⚠️ ISBOTLANGAN `.exe` topilmasa yurish TO'XTAMAYDI: 1C ni operator O'ZI ochadi va bu
       yo'l SHIPPED paketning NORMAL yo'li (`launcher` modul docstringi). Lekin fakt
       JIMGINA yutilmaydi — u izohga chiqadi.
    ⚠️⚠️ NISHON O'ZLIGI SHU YERDA HAM TEKSHIRILADI: 1C ochiladigan baza `request.json`
         dagi xesh bilan AYNI bo'lishi SHART. Ikki nom-fallback qoidasi bir kun ajralib
         ketsa, agent BOSHQA bazani ochib, javobni esa birinchisining xeshi bilan
         kutardi — ya'ni operator soatlab kutib, oxirida `TARGET_FINGERPRINT_MISMATCH`
         olardi. Mos kelmasa 1C UMUMAN OCHILMAYDI (`TARGET_AMBIGUOUS`).
    """
    try:
        nishon = _launch_target(infobase)
    except (ln.LauncherError, bpr.BridgeProtocolError) as e:
        return None, getattr(e, "code", bp.CODE_BRIDGE_SHAPE_INVALID)
    if nishon.fingerprint != fingerprint:   # pragma: no cover - ikki qoida ajralsa tutadi
        return None, bp.CODE_TARGET_AMBIGUOUS
    try:
        tanlov = ln.choose_exe(env.installs, path_clients=env.path_clients)
    except ln.LauncherError as e:
        return None, e.code
    try:
        return ln.open_infobase(
            exe_path=tanlov.path, target=nishon,
            operator_confirmed=operator_confirmed, opener=opener, output_dir=output_dir,
            # ⚠️ `collector_file` BERILMAYDI: `.epf` IKKILIK fayli QURILMAGAN (holat AYNAN
            #    `bridge_phase.EPF_SOURCE_READY`), shu bois fayl nomini ko'rsatish
            #    «tayyor fayl bor» degan YOLG'ON da'vo bo'lardi.
            notes=tanlov.notes,
        ), None
    except (ln.LauncherError, bpr.BridgeProtocolError) as e:
        # ⚠️ Buyruq qurilmadi (masalan yo'lda qo'shtirnoq/`;` bor): agent 1C ni OCHMAYDI,
        #    lekin yurish davom etadi — operator 1C ni O'ZI ochadi.
        return None, getattr(e, "code", bp.CODE_BRIDGE_SHAPE_INVALID)


def _reconfirm_target(model, xesh: str) -> bool:
    """Nishonni O'ZLIGI (xesh) bo'yicha QAYTA TASDIQLAYDI va indeksni TIKLAYDI.

    Qaytaradi: tasdiq o'tdimi.

    ⚠️⚠️ TUZATILGAN NUQSON — NISHON O'ZLIGI SIYLIB KETARDI. `one_click` nishonni INDEKS
         bo'yicha tanlaydi va uning XESHINI `request.json` ga yozadi; keyin
         `ui.UiModel.start()` -> `_collect` muhitni QAYTA SKANERLAYDI va
         `refresh_environment` indeksni faqat ORALIQDA ekaniga qarab saqlaydi. Ro'yxat
         o'zgargan bo'lsa AYNI indeks BOSHQA bazani ko'rsatardi — ya'ni so'rov bitta
         bazaga bog'langan, hisobot esa boshqasining muhitini yozardi. Bu jimgina xato:
         hisobot O'ZINI to'liq deb ko'rsatardi.
    ⚠️ Tasdiq INDEKS bo'yicha EMAS, O'ZLIK bo'yicha: xesh topilsa indeks SHU o'zlikka
       qarab tiklanadi (`select_target`), topilmasa — tasdiq O'TMAYDI va chaqiruvchi
       `TARGET_AMBIGUOUS` bilan to'xtaydi (tanlov OPERATORGA qaytadi).
    ⚠️ AYNI baza ikki marta e'lon qilingan bo'lsa xeshlar BIR XIL bo'ladi — bu NOANIQLIK
       emas, shu bois ro'yxatdagi BIRINCHI mos keluvchi olinadi (`assert_unique_target`
       ham xeshlarni takrorsizlaydi).
    """
    env = model.environment
    if env is None or not env.infobases:
        return False
    xeshlar = [target_fingerprint_of(ib) for ib in env.infobases]
    if xesh not in xeshlar:
        return False
    model.select_target(xeshlar.index(xesh))
    return True


# ══════════════════════════════════════════════════════════════════════════════════════════
# ASOSIY OQIM
# ══════════════════════════════════════════════════════════════════════════════════════════
def run_one_click(model, *, runs_root=None, select_index=None, on_event=None, on_wait=None,
                  expected_collector: tuple[str, str] = (EXPECTED_COLLECTOR_NAME,
                                                         EXPECTED_COLLECTOR_VERSION),
                  operator_confirmed: bool = False, opener=None,
                  cancel: "ln.CancelToken | None" = None,
                  ) -> OneClickOutcome:
    """BIR BOSISHLI yurish. `model` — MAVJUD `ui.UiModel` (yangi qobiq QURILMAYDI).

    Ishga tushirish va kutish uchun `launcher` ISHLATILADI (ikkinchi dvigatel YO'Q):
      · `launcher.open_infobase` — buyruq SHAKLI, kredensial darvozasi va operator
        ko'rsatmasi; 1C ni ochish esa ALMASHTIRILADIGAN `opener` ga qoladi;
      · `launcher.wait_for_collector` — CHEKLI kutish + KOOPERATIV bekor qilish;
      · `cancel` (`launcher.CancelToken`) — operator to'xtatsa agent KUTISHNI to'xtatadi,
        1C oynasini esa operator O'ZI yopadi (jarayon O'LDIRILMAYDI).

    ⚠️⚠️ ISHGA TUSHIRISH DARVOZASI BEZAK EMAS (TUZATILGAN NUQSON). Ilgari bu funksiya
         `assert_launch_allowed(operator_confirmed=False)` ni QOTIRILGAN `False` bilan
         chaqirib, istisnoni darrov ushlab, faqat faza TAFSILOTIGA aylantirardi — ya'ni
         darvoza hech narsani darvozalamasdi. Endi qoida ANIQ:
           · `opener` BERILGAN (chaqiruvchi agentning O'ZI 1C ni ochishini so'raydi) va
             `operator_confirmed` ROST EMAS  ->  yurish `COLLECTOR_EXECUTION_NOT_ALLOWED`
             bilan TO'XTAYDI, ochuvchi CHAQIRILMAYDI, qaror OPERATORDA (chiqish kodi 2);
           · `opener` berilgan va tasdiq ROST  ->  1C ROSTDAN ochiladi va natija
             (`exit_code`) qaytadi; ochilmasa yurish `LAUNCH_FAILED` bilan to'xtaydi;
           · `opener` BERILMAGAN  ->  agent 1C ni ochmaydi va buni DA'VO ham qilmaydi:
             bu SHIPPED paketning NORMAL yo'li (`launcher` modul docstringi), 1C ni
             OPERATOR ochadi. Darvoza bu yo'lda hukm chiqarmaydi, chunki darvozalanadigan
             AMAL YO'Q — soxta «tekshirdim» qaydi ham yozilmaydi.
         ⚠️ 1C XAVFSIZLIGI ZAIFLASHTIRILMAYDI: bu faqat operator tasdig'i; COM ham,
            o'ylab chiqarilgan buyruq satri parametri ham QO'SHILMAYDI.

    ⚠️⚠️ `model.bundle_dir` SHU FUNKSIYA tomonidan qo'yiladi: kuzatiladigan papka —
         YURISHNING O'Z papkasi ichidagi `bundle/`. Operator hech narsani QO'LDA
         KO'CHIRMAYDI: aynan shu yo'l `request.json` dagi `output_dir` da turadi.
    ⚠️ IKKI BIR VAQTDA YURISH: har chaqiruv O'Z `run_id` ini (`secrets.token_hex`) va O'Z
       papkasini oladi; biri ikkinchisining javobini KO'RMAYDI — begona javob `run_id`
       (`STALE_OUTPUT`) yoki `nonce` (`NONCE_MISMATCH`) bo'yicha RAD etiladi.
    ⚠️ Hamma tashqi bog'liqlik `model` dan keladi (soat, `sleeper`, skaner, analitik), shu
       bois bu funksiya 1C siz va haqiqiy vaqtni kutmasdan to'liq sinaladi.
    """
    flow = _Oqim(on_event=on_event)
    nom, versiya = expected_collector

    # ── DETECTING_1C ─────────────────────────────────────────────────────────────────────
    flow.emit(bp.DETECTING_1C)
    env = model.refresh_environment()
    hukm = env.presence_verdict

    # ── NO_1C ────────────────────────────────────────────────────────────────────────────
    # ⚠️⚠️ FAIL-CLOSED: `found` BO'LMASA yurish boshlanmaydi. `absent` («qaradim va yo'q») va
    #      `unknown` («qaray olmadim») AJRATILADI, lekin IKKISIDA ham davom etilmaydi:
    #      1C yo'qligi noma'lum bo'lsa, yig'uvchini kutish soniyalarni behuda sarflardi.
    #      Ajrim HOLAT nomida emas, hukmda yashaydi (parallel lug'at TAQIQ).
    if hukm != det.PRESENCE_FOUND:
        flow.emit(bp.NO_1C, detail=st.failure_meaning(st.FAILED_NO_1C,
                                                      presence_verdict=hukm))
        # ⚠️⚠️ HALOL QAYD: bu yo'lda NATIJA PAPKASI YOZILMAYDI. Paketni mavjud
        #      `ui.UiModel._paket` yozadi va unga faqat YURISH orqali kirish bor; yurish
        #      esa bu holatda `watch_folder` yo'liga tushib, sababni
        #      `FAILED_COLLECTOR_UNAVAILABLE` ga ALMASHTIRIB qo'yardi — ya'ni ekranda
        #      «1C yo'q», papkada «yig'uvchi javob bermadi» turardi. Ikki haqiqat yozishdan
        #      ko'ra paket yozmaslik TO'G'RI: operator ekranda TO'LIQ sabab va keyingi
        #      qadamni oladi. `ui.py` egasiga so'rov: yiqilish paketini quvurdan TASHQARI
        #      yozadigan kirish nuqtasi (`package_only(state=...)`).
        return _outcome(flow, phase=bp.NO_1C, state=st.FAILED_NO_1C, verdict=hukm,
                        detail=st.failure_meaning(st.FAILED_NO_1C, presence_verdict=hukm))

    # ── DISCOVERING_INFOBASES ────────────────────────────────────────────────────────────
    flow.emit(bp.DISCOVERING_INFOBASES,
              detail=f"ro'yxatdan {len(env.infobases)} ta ma'lumot bazasi o'qildi")
    if not env.infobases:
        return _outcome(flow, phase=bp.DISCOVERING_INFOBASES, state=st.FAILED_NO_TARGET,
                        verdict=hukm, detail=st.failure_meaning(st.FAILED_NO_TARGET))

    # ── SELECT_TARGET ────────────────────────────────────────────────────────────────────
    xesh, nishon = _select_target(model, select_index)
    if xesh is None:
        flow.emit(bp.SELECT_TARGET,
                  detail=bp.failure_triple(bp.CODE_TARGET_AMBIGUOUS).next_action)
        # ⚠️ Holat YAKUNIY EMAS (`TARGET_SELECTION`): yurish YIQILMADI, qaror OPERATORDA.
        #    Yiqilish deb yozish «agent urinib ko'rdi va bo'lmadi» degan yolg'on bo'lardi.
        return _outcome(flow, phase=bp.SELECT_TARGET, state=st.TARGET_SELECTION,
                        verdict=hukm, code=bp.CODE_TARGET_AMBIGUOUS,
                        detail=bp.failure_triple(bp.CODE_TARGET_AMBIGUOUS).operator,
                        waiting=True)
    # ⚠️ `requires_auth` FAKT bo'lib ko'rsatiladi, YIQILISH bo'lib EMAS: kirish ma'lumotini
    #    1C ning O'Z oynasi so'raydi va agent uni ko'rmaydi.
    kerakmi = ("kerak bo'lishi mumkin" if nishon.requires_auth != det.TRI_FALSE
               else "kerak emas")
    flow.emit(bp.SELECT_TARGET,
              detail=(f"nishon tanlandi; kirish ma'lumoti {kerakmi} va uni 1C ning O'Z "
                      f"oynasi so'raydi"))

    # ── PREPARING_COLLECTOR ──────────────────────────────────────────────────────────────
    t = model.now()
    try:
        identity = bpr.new_run(now=t)
        run_dir = bpr.prepare_run_dir(identity.run_id, runs_root=runs_root)
        bundle_dir = run_dir / BUNDLE_SUBDIR
        # ⚠️ FAQAT O'Z yurish papkasining ICHIDA papka yaratiladi; begona faylga
        #    TEGILMAYDI va hech narsa O'CHIRILMAYDI.
        bundle_dir.mkdir()
        sorov = bpr.build_request(
            identity, output_dir=str(bundle_dir), collector_name=nom,
            collector_version=versiya, target_fingerprint=xesh, mode=model.mode,
            allowed_probes=(), notes=REQUEST_NOTES,
        )
        bpr.write_request(run_dir, sorov)
    except bpr.BridgeProtocolError as e:
        # ⚠️ Papka BO'SH EMAS yoki ildiz NOMA'LUM — bu XAVFSIZLIK rad etishi: agent
        #    tozalamaydi va taxmin qilmaydi (`FAILED_SAFETY` darvozasi).
        flow.emit(bp.PREPARING_COLLECTOR, detail=bp.failure_triple(e.code).next_action)
        return _outcome(flow, phase=bp.PREPARING_COLLECTOR, state=st.FAILED_SAFETY,
                        verdict=hukm, code=e.code,
                        detail=bp.failure_triple(e.code).operator)
    flow.emit(bp.PREPARING_COLLECTOR,
              detail="yurishning bo'sh papkasi tayyorlandi va so'rov hujjati yozildi")

    # ── LAUNCHING_1C ─────────────────────────────────────────────────────────────────────
    # ⚠️⚠️ DARVOZA ROSTDAN HUKM CHIQARADI (funksiya docstringidagi uch yo'lga qarang) va
    #      ishga tushirish BUYRUG'I `launcher` da quriladi — ikkinchi abstraksiya YO'Q.
    ishga_kod: str | None = None
    ochish = None
    if opener is not None and operator_confirmed is not True:
        # ⚠️⚠️ FAIL-CLOSED va ANIQ TO'XTASH: chaqiruvchi agentning O'ZI 1C ni ochishini
        #      so'radi, tasdiq esa YO'Q. Ochuvchi CHAQIRILMAYDI va yurish DAVOM ETMAYDI:
        #      «tasdiqsiz ochishga urinib ko'rdim» ham, «jimgina operator yo'liga
        #      o'tdim» ham operator so'ramagan qarorni uning nomidan qabul qilish bo'lardi.
        # ⚠️ Holat YAKUNIY EMAS: yurish YIQILMADI, qaror OPERATORDA (chiqish kodi 2).
        uchlik = bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
        flow.emit(bp.LAUNCHING_1C, detail=uchlik.next_action)
        return _outcome(flow, phase=bp.LAUNCHING_1C,
                        state=bp.phase_state(bp.LAUNCHING_1C), verdict=hukm,
                        code=bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, run_dir=run_dir,
                        identity=identity, detail=uchlik.operator, waiting=True)
    # ⚠️⚠️ NEGA BUYRUQ FAQAT SHU SHOXDA QURILADI (va bu QAROR, kamchilik emas): buyruqni
    #      HAR yurishda qurish ustunlikdek ko'rinadi, lekin `launcher.build_open_command`
    #      mavjud `collector_bridge._safe_arg` darvozasidan o'tadi va u ATAYLAB o'z
    #      istisnosini (`BridgeError`, ko'prik KODI YO'Q) tashlaydi — u ishlab chiquvchi
    #      uchun tripwire. Shu istisnoni o'z kodimizga o'rash «nuqsonni operator xatosiga
    #      aylantirish» bo'lardi (launcher docstringi buni TAQIQLAYDI), o'ramasdan esa
    #      qo'shtirnoq yoki `;` belgisi bo'lgan mahalliy yo'l HAR BIR yurishni uzib
    #      qo'yardi — 1C ochmoqchi ham bo'lmagan yurishni. Shu bois buyruq AYNAN agent
    #      ochadigan yo'lda quriladi; operator yo'lida esa matn MAVJUD uchlikdan keladi.
    if opener is not None:
        ochish, ishga_kod = _launch_1c(
            nishon, env=env, fingerprint=xesh, output_dir=str(bundle_dir),
            operator_confirmed=operator_confirmed, opener=opener,
        )
        if ochish is not None and ochish.state_hint is not None:
            # ⚠️ 1C OCHILMADI (`LAUNCH_FAILED`): bu yurishning to'xtashi, chunki agent
            #    ochishni O'Z ustiga olgan edi. Kod `launcher` dan AYNI holda olinadi va
            #    `OneClickOutcome.run_code` ga tushadi — KO'PRIK kodi deb ATALMAYDI.
            flow.emit(bp.LAUNCHING_1C, detail=str(ochish.next_action))
            return _outcome(flow, phase=bp.COLLECTOR_FAILED,
                            state=bp.phase_state(bp.COLLECTOR_FAILED), verdict=hukm,
                            run_code=ochish.code, run_dir=run_dir, identity=identity,
                            detail=str(ochish.operator), problems=ochish.notes)
    if ochish is not None and ochish.launched == det.TRI_TRUE:
        flow.emit(bp.LAUNCHING_1C,
                  detail="1C agent tomonidan ochildi; agent uni YOPMAYDI va bazaga "
                         "O'ZI ulanmaydi")
    elif ishga_kod is not None:
        # ⚠️ ISHGA TUSHIRISH TAYYORLANMADI (masalan ISBOTLANGAN `.exe` topilmadi):
        #    `launcher` ning KODI operatorga FAKT bo'lib ko'rsatiladi va JIMGINA
        #    yutilmaydi. Yurish TO'XTAMAYDI: 1C ni operator O'ZI ochadi.
        flow.emit(bp.LAUNCHING_1C,
                  detail=(f"agent 1C ni o'zi OCHMADI ({ishga_kod}); "
                          + bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
                          .next_action))
    else:
        # ⚠️⚠️ SHIPPED PAKETNING NORMAL YO'LI: 1C ni OPERATOR ochadi. Matn `bridge_phase`
        #      uchligidan olinadi (ikkinchi matn yozilmaydi) va u `launcher.failure_text`
        #      bergan matn bilan AYNI — ya'ni ikki qatlam BIR MANBADAN o'qiydi.
        flow.emit(bp.LAUNCHING_1C,
                  detail=bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
                  .next_action)

    # ── WAITING_FOR_COLLECTOR ────────────────────────────────────────────────────────────
    flow.emit(bp.WAITING_FOR_COLLECTOR,
              detail=("yig'uvchini 1C da bajarganingizdan keyin natija SHU yurishning "
                      "papkasiga tushadi — fayllarni qo'lda ko'chirish KERAK EMAS"))
    # ⚠️⚠️ KUTISH DVIGATELI `launcher.wait_for_collector` DA va u IKKINCHI NUSXADA
    #      YOZILMAYDI: cheksiz kutish yo'qligi, `clock`/`sleeper` ning KIRISHDAN kelishi,
    #      javobni qabul qilish darvozasi (`accept_collector_output`) va KOOPERATIV bekor
    #      qilish — hammasi o'sha halqada. Bu modul faqat (1) bekor qilish tokenini
    #      uzatadi, (2) natijani operator KO'RADIGAN fazaga tarjima qiladi.
    kutish = ln.wait_for_collector(
        run_dir=run_dir, request=sorov, cancel=cancel,
        timeout_seconds=model.watch_timeout_seconds,
        poll_seconds=model.watch_poll_seconds, clock=model.clock,
        sleeper=_kutish_kanali(model.sleeper, on_wait),
        members=lambda: _bundle_file_names(bundle_dir),
    )
    olchov = int(kutish.ticks)
    muammolar = tuple(kutish.diagnostics)

    if kutish.state_hint == st.ABORTED_BY_OPERATOR and kutish.acceptance is None:
        # ⚠️⚠️ OPERATOR KUTISHNI TO'XTATDI — bu AYB EMAS, lekin COMPLETE ham emas.
        #      Holat MAVJUD `states.ABORTED_BY_OPERATOR` (yangi holat QO'SHILMAYDI) va u
        #      `METADATA_DISCOVERY` dan ruxsat etilgan chiqish, shu bois faza
        #      `WAITING_FOR_COLLECTOR` da QOLADI: `COLLECTOR_FAILED` fazasi
        #      `FAILED_COLLECTOR_UNAVAILABLE` ga bog'langan va «yig'uvchi javob bermadi»
        #      degan BOSHQA sababni ko'rsatardi.
        # ⚠️ 1C YOPILMAYDI va birorta jarayon tugatilmaydi: bekor qilish KOOPERATIV.
        return _outcome(flow, phase=bp.WAITING_FOR_COLLECTOR, state=st.ABORTED_BY_OPERATOR,
                        verdict=hukm, code=kutish.code, run_dir=run_dir,
                        identity=identity, detail=str(kutish.operator), waited=olchov,
                        problems=muammolar)

    if kutish.state_hint == st.FAILED_TIMEOUT:
        # ⚠️ IKKI SABAB AJRATILADI: papka butunlay bo'sh va javob yo'q bo'lsa — yig'uvchi
        #    UMUMAN boshlanmagan (`RESPONSE_MISSING`); nimadir yozilgan bo'lsa — u ishini
        #    TUGATMAGAN (`DONE_MARKER_MISSING`). Operatorning qadami ikkisida boshqa.
        # ⚠️⚠️ KOD KUTISH QATLAMIDAN OLINMAYDI: `launcher` `WAIT_TIMEOUT` beradi, lekin u
        #      KO'PRIK kodi EMAS va operatorga «nima qilaman?» savoliga javob bermaydi.
        #      Shu bois ko'prik lug'atidan ANIQ kod tanlanadi, holat esa `launcher` dan
        #      AYNI holda ko'chadi.
        # ⚠️ HOLAT `FAILED_TIMEOUT` (va `FAILED_COLLECTOR_UNAVAILABLE` EMAS): chekli vaqt
        #    ichida hech narsa chiqmasligi yig'uvchining O'LGANINI ISBOTLAMAYDI.
        bosh = (bpr.response_path(run_dir).exists() is False
                and not _bundle_file_names(bundle_dir))
        kod = bp.CODE_RESPONSE_MISSING if bosh else bp.CODE_DONE_MARKER_MISSING
        return _outcome(flow, phase=bp.WAITING_FOR_COLLECTOR, state=st.FAILED_TIMEOUT,
                        verdict=hukm, code=kod, run_dir=run_dir, identity=identity,
                        detail=bp.failure_triple(kod).operator, waited=olchov,
                        problems=muammolar)

    # ── COLLECTOR_COMPLETE / COLLECTOR_FAILED ────────────────────────────────────────────
    if kutish.acceptance is None:
        # ⚠️ Javob SHAKLI yoki O'ZLIGI bo'yicha RAD etildi — kod `bridge_protocol` dan
        #    AYNI holda keladi (`STALE_OUTPUT`, `NONCE_MISMATCH`,
        #    `WRONG_COLLECTOR_VERSION`, `PARTIAL_PACKAGE`, ...).
        uchlik = bp.failure_triple(str(kutish.code))
        flow.emit(bp.COLLECTOR_FAILED, detail=uchlik.next_action)
        return _outcome(flow, phase=bp.COLLECTOR_FAILED,
                        state=bp.phase_state(bp.COLLECTOR_FAILED), verdict=hukm,
                        code=kutish.code, run_dir=run_dir, identity=identity,
                        detail=uchlik.operator, waited=olchov, problems=muammolar)
    qabul = kutish.acceptance
    if qabul.phase != bp.COLLECTOR_COMPLETE:
        # ⚠️ Yig'uvchi «yiqildim» yoki «bekor qilindi» deb AYTDI — bu JAVOB, lekin
        #    COMPLETE emas. Faza va kod `accept_collector_output` dan AYNI holda olinadi:
        #    ikkinchi talqin yozilsa, bitta vaziyat ikki xil nom olardi.
        uchlik = None if qabul.code is None else bp.failure_triple(qabul.code)
        flow.emit(qabul.phase,
                  detail=(uchlik.next_action if uchlik is not None else
                          "yig'uvchi xato bilan to'xtaganini O'ZI bildirdi"))
        return _outcome(flow, phase=qabul.phase, state=bp.phase_state(qabul.phase),
                        verdict=hukm, code=qabul.code, run_dir=run_dir, identity=identity,
                        detail=(uchlik.operator if uchlik is not None else
                                "yig'uvchi xato bilan to'xtaganini O'ZI bildirdi"),
                        waited=olchov, problems=muammolar)
    # ⚠️⚠️ YIG'UVCHINING O'Z HOLATI ATALADI (`SUCCESS` yoki `PARTIAL`): `PARTIAL` javob ham
    #      shu fazaga o'tadi, chunki javob SHU yurishga tegishli va paketning fayllari
    #      to'liq — LEKIN u JIMGINA MUVAFFAQIYAT EMAS. Hukmni QUVUR beradi: Phase 4
    #      validatori yarim paketda kod `2` ni qaytaradi va yurish SHU SABAB bilan
    #      to'xtaydi. Ko'prik «tugadi» deb ham, «yiqildi» deb ham ATAMAYDI.
    flow.emit(bp.COLLECTOR_COMPLETE,
              detail=(f"javob SHU yurishga tegishli va paketning fayllari to'liq; "
                      f"yig'uvchi aytgan holat: {qabul.status}"))

    # ── INGESTING / ANALYZING / COMPLETE — MAVJUD QUVUR ──────────────────────────────────
    # ⚠️⚠️ BU YERDAN KEYIN YANGI MANTIQ YO'Q: `ui.UiModel.start()` mavjud ko'prikning
    #      kuzatish/tayyorlik o'lchovini, `pipeline.run_pipeline` ni (validatsiya, graf,
    #      analitik, hisobot) va `result_package` ni chaqiradi. Fazalar quvur yozgan
    #      HOLATLARDAN tarjima qilinadi.
    model.bundle_dir = str(bundle_dir)
    asl = model.on_progress
    #: `[nishon o'zligi TASDIQLANMADI, tasdiq ALLAQACHON o'lchandi]`
    nishon_holati = [False, False]

    def _progress(holat: str) -> None:
        if asl is not None:
            asl(holat)
        if not st.is_known(holat):
            return
        # ⚠️⚠️ NISHON O'ZLIGI SHU YERDA QAYTA TASDIQLANADI va AYNAN SHU NUQTADA: quvur
        #      `TARGET_SELECTION` ga o'tgan payt — muhit QAYTA SKANERLANGANDAN keyingi
        #      birinchi lahza, ya'ni indeks siyilib ketgan bo'lsa u SHU YERDA ko'rinadi.
        #      Tasdiq INDEKS bo'yicha emas, XESH bo'yicha (`_reconfirm_target`).
        # ⚠️ ISTISNO TASHLANMAYDI: `ui.UiModel.start()` har qanday istisnoni
        #    `FAILED_INTERNAL` ga aylantiradi, holbuki bu NUQSON emas — muhit o'zgargan.
        #    Shu bois fakt BELGILANADI va faza oqimi MUZLATILADI (keyingi fazalar
        #    ekranga chiqmaydi: tasdiqlanmagan nishon bo'yicha «tahlil qilinyapti» deb
        #    ko'rsatish yolg'on bo'lardi).
        if holat == st.TARGET_SELECTION and not nishon_holati[1]:
            nishon_holati[1] = True
            if not _reconfirm_target(model, xesh):
                nishon_holati[0] = True
        if nishon_holati[0]:
            return
        fazalar = bp.phases_for_state(holat)
        # ⚠️ FAQAT BIR MA'NOLI va FAQAT OLDINGA: ko'p fazaga mos holat (masalan
        #    `METADATA_DISCOVERY`) ekranda allaqachon o'tgan qadamni qaytarardi.
        if len(fazalar) == 1 and _PHASE_INDEX[fazalar[0]] > flow.reached_index:
            flow.emit(fazalar[0])

    model.on_progress = _progress
    try:
        natija = model.start()
    finally:
        # ⚠️ Chaqiruvchining progress kanali QAYTARILADI: biz uni O'ZLASHTIRMAYMIZ.
        model.on_progress = asl

    if nishon_holati[0]:
        # ⚠️⚠️ NISHON O'ZLIGI TASDIQLANMADI: so'rov AYNAN bitta bazaga bog'langan edi,
        #      qayta skanerlashdan keyin esa o'sha o'zlik ro'yxatda YO'Q. Yurishning
        #      xulosasi DA'VO QILINMAYDI (`natija.state` ko'chirilmaydi) va natija
        #      papkasi ham KO'RSATILMAYDI: u qaysi bazaning muhiti ekani ENDI
        #      ISBOTLANMAYDI, ya'ni «hisobot o'zini to'liq deb ko'rsatishi» aynan shu
        #      bilan to'siladi.
        # ⚠️ Holat YAKUNIY EMAS: yurish YIQILMADI, tanlov OPERATORGA qaytadi (chiqish
        #    kodi 2) — u `--target` bilan yangi yurish boshlaydi (har yurish O'Z papkasini
        #    oladi va bu papka O'CHIRILMAYDI).
        uchlik = bp.failure_triple(bp.CODE_TARGET_AMBIGUOUS)
        return _outcome(flow, phase=flow.reached, state=bp.phase_state(flow.reached),
                        verdict=hukm, code=bp.CODE_TARGET_AMBIGUOUS, run_dir=run_dir,
                        identity=identity, detail=uchlik.operator, waited=olchov,
                        waiting=True,
                        problems=muammolar + (
                            "nishon o'zligi yurish ichida QAYTA TASDIQLANMADI: muhit "
                            "qayta skanerlanganda so'rovdagi nishon ro'yxatda topilmadi",))

    faza = (bp.COMPLETE if natija.state == st.COMPLETE
            else phase_for_state(natija.state, reached=flow.reached))
    if faza != flow.reached and _PHASE_INDEX[faza] > flow.reached_index:
        flow.emit(faza)
    return _outcome(flow, phase=faza, state=natija.state, verdict=hukm,
                    detail=natija.detail, run_code=natija.code, run_dir=run_dir,
                    identity=identity, result_dir=natija.result_dir,
                    problems=tuple(natija.problems), waited=olchov)


def _outcome(flow: _Oqim, *, phase: str, state: str, detail: str, verdict: str,
             code: str | None = None, run_code: str | None = None, run_dir=None,
             identity=None, result_dir=None, problems: tuple[str, ...] = (),
             waited: int = 0, waiting: bool = False) -> OneClickOutcome:
    """Yakunni quradi. ⚠️ Darvozalar `OneClickOutcome.__post_init__` da."""
    return OneClickOutcome(
        phase=phase, state=state, detail=detail, code=code, run_code=run_code,
        run_id=None if identity is None else identity.run_id,
        nonce_len=0 if identity is None else len(identity.nonce),
        run_dir=None if run_dir is None else str(run_dir),
        result_dir=result_dir, events=tuple(flow.events), problems=problems,
        waited_ticks=waited, waiting_for_operator=waiting, _presence_verdict=verdict,
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ Testlar ham shu invariantlarni qulflaydi, lekin import paytida yiqilish eng arzon
#    darvoza: test yurgizilmagan yo'l ham shu yerdan o'tadi.
assert st.can_transition(st.TARGET_SELECTION, st.FAILED_NO_TARGET), \
    "«baza yo'q» xulosasi nishon tanlash bosqichidan yozilishi SHART"
assert st.can_transition(st.SAFETY_CHECK, st.FAILED_SAFETY), \
    "yurish papkasi darvozasi `SAFETY_CHECK` dan yozilishi SHART"
assert st.can_transition(st.METADATA_DISCOVERY, st.FAILED_TIMEOUT), \
    "kutish chegarasi `METADATA_DISCOVERY` dan yozilishi SHART"
assert bp.phase_state(bp.COLLECTOR_FAILED) == st.FAILED_COLLECTOR_UNAVAILABLE, \
    "ko'prik faza xaritasi o'zgargan — bu modul uni ALMASHTIRMAYDI, unga TAYANADI"
assert set(_PHASE_INDEX) == set(bp.BRIDGE_PHASES) and len(_PHASE_INDEX) == 12, \
    "faza tartibi `bridge_phase.BRIDGE_PHASES` dan ajralib ketdi"
assert BUNDLE_SUBDIR and "/" not in BUNDLE_SUBDIR and "\\" not in BUNDLE_SUBDIR, \
    "paket papkasining nomi YAGONA manbadan (`discovery_agent.BUNDLE_SUBDIR`) olinadi"
assert all(n.strip() for n in REQUEST_NOTES), "so'rov izohlari bo'sh bo'lmasin"
assert WAIT_NOTICE.strip(), "kutish matni BO'SH bo'lmasin: «spinner-only» holat YO'Q"
# ⚠️ KO'PRIK QATLAMINING O'ZLIGI (P0): agent kutadigan qiymat YIG'UVCHINING ICHKI o'zligi
#    EMAS. Ikkisi ARALASHSA har bir haqiqiy javob `WRONG_COLLECTOR_VERSION` bilan rad
#    etilardi — testlar bu qiymatlarni MANBA fayllari bilan ham solishtiradi.
assert (EXPECTED_COLLECTOR_NAME, EXPECTED_COLLECTOR_VERSION) != ("BinOSDiscovery",
                                                                 "0.2.0-UNVERIFIED"), \
    "kutilgan o'zlik ICHKI yig'uvchining o'zligi EMAS: `response.collector` ni KO'PRIK " \
    "yozadi (`integrations/1c/collector/VERSION.json`)"
assert EXPECTED_COLLECTOR_VERSION.endswith("-source"), \
    "`.epf` IKKILIK fayli QURILMAGAN (holat `EPF_SOURCE_READY`) — versiya shuni AYTADI"
# ⚠️ YANGI HOLAT QO'SHILMAYDI: bekor qilish MAVJUD `ABORTED_BY_OPERATOR` ga tushadi va u
#    `METADATA_DISCOVERY` dan ruxsat etilgan chiqish (shu bois faza `WAITING_FOR_COLLECTOR`
#    da qoladi — `COLLECTOR_FAILED` fazasi BOSHQA sababni ko'rsatardi).
assert st.can_transition(st.METADATA_DISCOVERY, st.ABORTED_BY_OPERATOR), \
    "operator to'xtatishi `METADATA_DISCOVERY` dan yozilishi SHART"
assert bp.phase_state(bp.WAITING_FOR_COLLECTOR) == st.METADATA_DISCOVERY, \
    "kutish fazasining holati o'zgargan — bekor qilish yo'li shu moslikka TAYANADI"
assert len(st.FAILURE_STATES) == 11 and len(st.NORMAL_STATES) == 12, \
    "bu modul holat mashinasini ALMASHTIRMAYDI va yangi holat QO'SHMAYDI"
# ⚠️ Kutish dvigateli SHU MODULDA YO'Q: u `launcher` da va standart qiymatlari ko'prikdan.
assert hasattr(ln, "wait_for_collector") and hasattr(ln, "CancelToken"), \
    "ishga tushirish/kutish abstraksiyasi `launcher` dan OLINADI (ikkinchi dvigatel yo'q)"
