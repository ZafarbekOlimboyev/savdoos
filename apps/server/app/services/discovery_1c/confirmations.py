# -*- coding: utf-8 -*-
"""OPERATOR TASDIG'I — `binos-1c-confirmations-v1` (AI chiqishidan AJRALGAN hujjat).

⚠️ ENG MUHIM QOIDA: AI O'ZINI OPERATOR SIFATIDA KO'RSATA OLMAYDI. Shu bois tasdiq ALOHIDA
   hujjatda yashaydi va AI chiqishi bilan BIR FAYLGA aralashmaydi. Ikkisi bitta hujjatda
   bo'lsa, model o'z javobiga «operator tasdiqladi» degan qatorni qo'shib qo'yishi kifoya
   bo'lardi — va tashqaridan bu haqiqiy tasdiqdan farq qilmasdi. Fayl ajratilgani texnik
   qulaylik emas, aynan SHU hujumni imkonsiz qiladigan chegara.
⚠️ Shu sababli `validate_analysis` odatiy rejimda `HUMAN_CONFIRMED` ni RAD etadi
   (`ai.AI_STATUSES`), va shu modul — `HUMAN_CONFIRMED` ga OLIB BORADIGAN YAGONA yo'l.

NEGA TASDIQ MODEL BALLIDAN KELMAYDI. `confidence_score` — modelning O'Z bahosi, ya'ni
taxminning o'ziga o'zi qo'ygan bahosi. Odam tasdig'i esa BOSHQA TURDAGI bilim: u ekranda
ko'rilgan narsa haqida. Shu bois tasdiq ballni KO'TARMAYDI (`apply_confirmations` ni qarang):
ikki o'lchov qo'shilsa, «model juda ishonchli edi» degani «odam ko'rdi» degan ma'noga o'tib
ketardi.

⚠️ HUMAN_CONFIRMED ≠ VERIFIED. Bu ikkisi BOSHQA-BOSHQA qatlamning qarori:
  · `HUMAN_CONFIRMED` — SHU tahlil oqimidagi eng yuqori holat: «operator nomzodni ko'rdi va
    to'g'ri deb aytdi». U ko'chirish ruxsati EMAS.
  · `VERIFIED` (`schema.py`) — MIGRATOR darvozasi: ko'chirishga kirishdan oldin kuchli dalil
    talab qiladigan alohida qaror. Bu modul uni UMUMAN chiqarmaydi va bu yerda bunday holat
    yo'q (`ai.FORBIDDEN_STATUS` qarang). Ya'ni operator tasdiqlagani bilan ma'lumot ko'chirishga
    yaroqli bo'lib qolmaydi — u faqat keyingi qadamga TEKShiruvga tushadi.

QAT'IY QOIDALAR:
  1. `operator` bo'sh bo'lsa — RAD. ANONIM TASDIQ YO'Q: kim aytganini bilmasdan tasdiqni
     qaytarib tekshirib bo'lmaydi, ya'ni u tasdiq emas.
  2. `decided_at` bo'sh bo'lsa — RAD, va u vaqt zonasi bilan haqiqiy ISO 8601 bo'lishi SHART
     (`parse_ts`). Vaqt BU YERDA O'YLAB CHIQARILMAYDI — u hujjatdan keladi.
  3. Noma'lum kalit ham, tushib qolgan kalit ham — RAD (oq ro'yxat).
  4. Graf berilgan bo'lsa `candidate_object` grafda bo'lishi SHART: mavjud bo'lmagan obyektni
     tasdiqlash — hech narsani tasdiqlamaslik.
  5. Tasdiqda ko'rsatilgan, lekin gipotezalar ichida YO'Q nomzod JIMGINA TASHLANMAYDI — xato.
     Jim tushib qolish eng xavfli nosozlik: operator «tasdiqladim» deb o'ylaydi, hujjatda esa
     hech narsa o'zgarmagan.
  6. Tasdiq QAYSI shaklda kelishi (xom lug'at yoki tayyor `Confirmation` obyekti) HECH QANDAY
     yengillik bermaydi: ikki yo'l ham AYNI darvozadan o'tadi (`_gate_confirmation` obyektning
     o'zida, `validate_confirmations` esa hujjat darajasida). ⚠️ Obyekt yo'li darvozani aylanib
     o'tsa, yuqoridagi qoidalarning HAMMASI bir vaqtda kuchini yo'qotardi — qo'lda qurilgan
     obyekt bilan anonim, soxta vaqtli va sirli tasdiq `HUMAN_CONFIRMED` bo'lib chiqardi.
  7. Noma'lum `decision` — RAD (fail-open YO'Q). Ro'yxatda yo'q qiymat «operator qo'shimcha
     dalil so'radi» deb O'QILMAYDI: operator aytmagan ma'no hujjatga yozilmaydi.

Bu modulda birorta konfiguratsiya nomi YO'Q. Izohdagi misollar (`X17`, `R41`) — TO'QIMA nomlar.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace

from . import redact as redaction
from .ai import (AI_STATUSES, CONCEPTS, FORBIDDEN_STATUS, STATUS_AMBIGUOUS,
                 STATUS_HUMAN_CONFIRMED, STATUS_REJECTED, STATUSES, AnalysisError, Evidence,
                 Hypothesis, WEIGHT_STRONG)
from .graph import DiscoveryGraph
from .probe import ProbeError, assert_no_raw_code
from ..migrator_1c.bundle import BundleError, parse_ts

CONFIRMATIONS_VERSION = "binos-1c-confirmations-v1"

#: Operator bera oladigan qarorlar. ⚠️ Uchtasi ATAYLAB: «tasdiqlayman» va «rad etaman»
#: yonida «hali yetarli dalil yo'q» ham QAROR bo'lishi kerak, aks holda ikkilangan operator
#: majburan tanlab qo'yardi va ikkilanish hujjatdan yo'qolardi.
DECISIONS = ("CONFIRM", "REJECT", "NEEDS_MORE_EVIDENCE")

DECISION_CONFIRM, DECISION_REJECT, DECISION_NEEDS_MORE = DECISIONS

#: ⚠️ Odam tasdig'ining dalil TURI bitta: `human_confirmed` (`schema.STRONG_EVIDENCE_KINDS`).
#: Tur bilimning MANBASINI aytadi («odam ekranda ko'rdi»), yo'nalishni esa dalil qaysi ro'yxatga
#: tushgani aytadi: `evidence` — foydasiga, `counter_evidence` — qarshisiga. Shu bois rad etish
#: uchun alohida tur o'ylab chiqarilmaydi: manba o'sha odam.
HUMAN_EVIDENCE_KIND = "human_confirmed"

CONFIRMATIONS_KEYS = {"confirmations_version", "confirmations", "notes"}
CONFIRMATION_KEYS = {"target_concept", "candidate_object", "candidate_field", "decision",
                     "operator", "decided_at", "note"}


class ConfirmationError(AnalysisError):
    """Tasdiq hujjati shartnomaga mos emas — O'QILMAYDI va hech qanday holat o'zgarmaydi.

    `AnalysisError` dan meros: tahlil oqimini o'qiydigan kod bitta `except` bilan bularni ham
    qamrab oladi (`AnalysisError` esa `bundle.DiscoveryError` dan)."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfirmationError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra, f"{where}: noma'lum kalit(lar) {extra} — {CONFIRMATIONS_VERSION} da yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {missing}")


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v.strip()


@contextmanager
def _code_gate(where: str):
    """Xom kod darvozasining xatosini `ConfirmationError` ga o'raydi (`ai._probe_gate` naqshi).

    ⚠️ Xato MATNI SAQLANADI va sabab zanjiri (`from e`) uzilmaydi. O'rash faqat TURNI
       birlashtiradi: shu moduldan chiqadigan xato HAR DOIM `ConfirmationError`, ya'ni
       chaqiruvchi `ProbeError` ni alohida ushlab yurmaydi."""
    try:
        yield
    except ProbeError as e:
        msg = str(e)
        raise ConfirmationError(msg if msg.startswith(where) else f"{where}: {msg}") from e


def _clean_text(v, where: str) -> str:
    """Bo'sh bo'lmagan matn + XOM KOD darvozasi.

    ⚠️ Operator matni (ism, vaqt, izoh) keyinchalik gipotezaning `required_confirmation` va
       `ambiguity` ro'yxatlariga tushadi, ular esa `ai._validate_hypothesis` da
       `assert_no_raw_code` dan o'tadi. Darvozani SHU YERDA ham qo'yamiz, chunki aks holda
       tasdiq qabul qilinar, keyin esa natijani qayta o'qishning o'zi yiqilardi — ya'ni xato
       sababidan uzoqda, tushunarsiz joyda chiqardi."""
    s = _nonempty(v, where)
    with _code_gate(where):
        assert_no_raw_code(s, where=where)
    return s


@dataclass(frozen=True)
class Confirmation:
    """Bitta qaror: KIM, QACHON, QAYSI nomzod haqida, NIMA dedi.

    `target_concept`   — `ai.CONCEPTS` dan (bizning shartnomamiz nomi).
    `candidate_object` — grafdagi obyektning to'liq nomi (to'qima misol: `X17`).
    `candidate_field`  — obyekt ichidagi manzil yoki `None` (to'qima misol: `R41`).
    `decision`         — `DECISIONS` dan biri.
    `operator`         — KIM tasdiqladi. Bo'sh bo'lsa RAD: anonim tasdiq tasdiq emas.
    `decided_at`       — QACHON tasdiqladi (vaqt zonasi bilan ISO 8601, MATN).
    `note`             — nima ko'rilgani yoki nega rad etilgani. `REJECT` va
                         `NEEDS_MORE_EVIDENCE` uchun MAJBURIY (pastdagi izohga qarang).

    ⚠️ Bu yozuvda `confidence_score` YO'Q va bo'lishi ham mumkin emas: odam ball qo'ymaydi, u
       KO'RADI. Ball — modelning o'lchovi, va tasdiq uni o'zgartirmaydi."""

    target_concept: str
    candidate_object: str
    candidate_field: str | None
    decision: str
    operator: str
    decided_at: str
    note: str | None

    def __post_init__(self) -> None:
        """⚠️ DARVOZA OBYEKTNING O'ZIDA. Sabab: `apply_confirmations` ga tayyor `Confirmation`
           ro'yxatini berish mumkin, va ilgari SHU yo'l `validate_confirmations` ni UMUMAN
           chaqirmasdi — ya'ni qo'lda qurilgan obyekt bilan yuqoridagi QAT'IY QOIDALARNING
           HAMMASI aylanib o'tilardi: anonim (`operator=''`) tasdiq `HUMAN_CONFIRMED` bo'lib
           chiqardi, «kecha» deb yozilgan vaqt qabul qilinardi, izohdagi parol esa dalil
           `detail` iga ko'chib artefakt baytlariga yozilardi. Frozen dataclass o'zi hech
           narsani tekshirmaydi, shu bois tekshiruv SHU YERGA qo'yiladi: obyekt MAVJUD bo'lsa,
           u darvozadan o'tgan bo'ladi.
        ⚠️ Bu `validate_confirmations` ning O'RNINI BOSMAYDI (u hujjat qobig'ini, grafni va
           takroriy manzilni ham tekshiradi) — ikkisi QATLAM: biri hujjatni, ikkinchisi
           yozuvning o'zini qulflaydi."""
        _gate_confirmation(self)

    @property
    def address(self) -> str:
        """Nomzodning to'liq manzili — `Hypothesis.address` bilan AYNAN bir xil shakl."""
        if self.candidate_field is None:
            return self.candidate_object
        return f"{self.candidate_object}.{self.candidate_field}"

    @property
    def key(self) -> tuple[str, str]:
        """Moslash kaliti: bitta konsept + bitta manzilga BITTA qaror."""
        return (self.target_concept, self.address)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.target_concept, self.address, self.decision)

    @property
    def who_when(self) -> str:
        """Dalil `detail` iga yoziladigan «kim va qachon» bo'lagi."""
        return f"operator {self.operator} · {self.decided_at}"


def _gate_confirmation(c: Confirmation, *, where: str = "Confirmation") -> None:
    """Bitta yozuvning MAYDON darvozasi — `_validate_one` bilan AYNAN bir xil qat'iylikda.

    ⚠️ Nima uchun alohida funksiya: `_validate_one` XOM lug'atni tekshiradi va qiymatlarni
       tozalaydi (`strip`), bu funksiya esa TAYYOR obyektni tekshiradi. Ikkinchisi bo'lmasa,
       qo'lda qurilgan obyekt hech qanday darvozadan o'tmasdi.
    ⚠️ Grafni bu yerda tekshirib BO'LMAYDI (obyekt grafni bilmaydi) va takroriy manzil ham
       bu yerda ko'rinmaydi — ular hujjat darajasidagi tekshiruv, `validate_confirmations` da.
    ⚠️ Sir skaneri HAM shu yerda: operator izohi ERKIN MATN va u dalil `detail` iga, keyin
       ko'rik artefaktining BAYTLARIGA ko'chadi. Fail-closed."""
    decision = _nonempty(c.decision, f"{where}.decision")
    _need(decision in DECISIONS,
          f"{where}.decision noma'lum: {decision!r} — ruxsat etilgani {list(DECISIONS)}. "
          f"Qaror ro'yxati KOD o'zgarishi bilan kengayadi, hujjat bilan emas")

    concept = _nonempty(c.target_concept, f"{where}.target_concept")
    _need(concept in CONCEPTS,
          f"{where}.target_concept noma'lum: {concept!r} — konsept ID lari BIZNING "
          f"shartnomamiz nomlari, ular o'ylab chiqarilmaydi")

    _nonempty(c.candidate_object, f"{where}.candidate_object")
    _need(c.candidate_field is None or isinstance(c.candidate_field, str),
          f"{where}.candidate_field matn yoki null bo'lishi kerak")
    if c.candidate_field is not None:
        _nonempty(c.candidate_field, f"{where}.candidate_field")

    # ⚠️ KIM va QACHON — ikkisi ham MAJBURIY (1- va 2-qoida). ANONIM tasdiq tasdiq emas:
    #    bo'sh `operator` bilan yozilgan qator «kim ko'rdi» degan savolga javob bermaydi, ya'ni
    #    uni AI ham yozib qo'ya olardi va tashqaridan farqi bilinmasdi.
    _clean_text(c.operator, f"{where}.operator")
    decided_at = _clean_text(c.decided_at, f"{where}.decided_at")
    try:
        # ⚠️ Vaqt SHAKLI tekshiriladi: «kecha» deb yozilgan tasdiqni auditda joylashtirib
        #    bo'lmaydi. Vaqt bu yerda O'YLAB CHIQARILMAYDI — faqat kelgani tekshiriladi.
        parse_ts(decided_at, f"{where}.decided_at")
    except BundleError as e:
        raise ConfirmationError(str(e)) from e

    _need(c.note is None or isinstance(c.note, str), f"{where}.note matn yoki null bo'lishi kerak")
    if c.note is not None:
        _clean_text(c.note, f"{where}.note")
    if decision in (DECISION_REJECT, DECISION_NEEDS_MORE):
        _need(c.note and c.note.strip(),
              f"{where}.note {decision} uchun MAJBURIY — sababi aytilmagan qaror "
              f"tekshirib bo'lmaydigan qaror")

    findings = redaction.scan(_to_json_rows([c]))
    _need(not findings,
          f"{where}: sir shubhasi bor — TASDIQ O'QILMAYDI: "
          + "; ".join(str(f) for f in findings[:10]))


def _validate_one(raw, *, where: str, graph: DiscoveryGraph | None) -> Confirmation:
    _keys(raw, CONFIRMATION_KEYS, where)

    decision = _nonempty(raw["decision"], f"{where}.decision")
    _need(decision in DECISIONS,
          f"{where}.decision noma'lum: {decision!r} — ruxsat etilgani {list(DECISIONS)}. "
          f"Qaror ro'yxati KOD o'zgarishi bilan kengayadi, hujjat bilan emas")

    concept = _nonempty(raw["target_concept"], f"{where}.target_concept")
    _need(concept in CONCEPTS,
          f"{where}.target_concept noma'lum: {concept!r} — konsept ID lari BIZNING "
          f"shartnomamiz nomlari, ular o'ylab chiqarilmaydi")

    obj = _nonempty(raw["candidate_object"], f"{where}.candidate_object")
    field = raw["candidate_field"]
    _need(field is None or isinstance(field, str),
          f"{where}.candidate_field matn yoki null bo'lishi kerak")
    if field is not None:
        field = _nonempty(field, f"{where}.candidate_field")

    # ⚠️ Graf IXTIYORIY: tasdiq hujjati grafsiz ham o'qilishi kerak (masalan arxivdan). Lekin
    #    graf berilgan bo'lsa tekshiruv MAJBURIY: grafda yo'q obyekt haqidagi tasdiq hech
    #    narsani tasdiqlamaydi, va u jimgina «mos nomzod topilmadi» bo'lib ketmasligi kerak.
    if graph is not None:
        _need(isinstance(graph, DiscoveryGraph),
              f"validate_confirmations `DiscoveryGraph` yoki None kutadi, "
              f"kelgani {type(graph).__name__}")
        _need(graph.by_full_name(obj) is not None,
              f"{where}.candidate_object grafda yo'q: {obj!r} — mavjud bo'lmagan obyektni "
              f"tasdiqlash hech narsani tasdiqlamaydi")

    # ⚠️ KIM va QACHON — ikkisi ham MAJBURIY. Ular tasdiqni qaytarib tekshirish (kimdan
    #    so'rash, qaysi holatdagi hujjatga qarab aytilgani) uchun YAGONA yo'l.
    operator = _clean_text(raw["operator"], f"{where}.operator")
    decided_at = _clean_text(raw["decided_at"], f"{where}.decided_at")
    try:
        # ⚠️ Vaqt SHAKLI tekshiriladi (vaqt zonasi bilan ISO 8601, ishonarli kalendar oynasi).
        #    Sabab: «kecha» yoki «bugun» deb yozilgan tasdiqni auditda joylashtirib bo'lmaydi.
        #    Bu yerda vaqt O'YLAB CHIQARILMAYDI — faqat kelganini tekshiramiz.
        parse_ts(decided_at, f"{where}.decided_at")
    except BundleError as e:
        raise ConfirmationError(str(e)) from e

    note = raw["note"]
    _need(note is None or isinstance(note, str), f"{where}.note matn yoki null bo'lishi kerak")
    if note is not None:
        note = _clean_text(note, f"{where}.note")
    # ⚠️ `REJECT` va `NEEDS_MORE_EVIDENCE` uchun izoh MAJBURIY: sababsiz rad etish ham,
    #    «nimasi yetmaydi» aytilmagan so'rov ham keyingi qadamga hech narsa bermaydi
    #    (`ai._validate_hypothesis` ham aynan shu sababdan `counter_evidence` va `ambiguity` ni
    #    bo'sh qoldirmaydi). `CONFIRM` da izoh ixtiyoriy: tasdiqning o'zi «ko'rdim» degani.
    if decision in (DECISION_REJECT, DECISION_NEEDS_MORE):
        _need(note, f"{where}.note {decision} uchun MAJBURIY — sababi aytilmagan qaror "
                    f"tekshirib bo'lmaydigan qaror")

    return Confirmation(target_concept=concept, candidate_object=obj, candidate_field=field,
                        decision=decision, operator=operator, decided_at=decided_at, note=note)


def _confirmation_rows(doc) -> list:
    """Hujjatning tashqi qobig'i: to'liq hujjat yoki shunchaki qarorlar ro'yxati.

    ⚠️ Ikki shakl `ai._analysis_rows` bilan bir xil sababdan qabul qilinadi: qobiq (versiya)
       BIZNING qo'shimchamiz, operatorning ishi esa QARORLAR. Ichki tekshiruv ikki holatda ham
       AYNAN bir xil qat'iy, ya'ni qobiqsiz shakl hech qanday yengillik bermaydi."""
    if isinstance(doc, (list, tuple)):
        return list(doc)
    _keys(doc, CONFIRMATIONS_KEYS, "confirmations")
    _need(doc["confirmations_version"] == CONFIRMATIONS_VERSION,
          f"confirmations.confirmations_version {CONFIRMATIONS_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['confirmations_version']!r}")
    _need(isinstance(doc["confirmations"], (list, tuple)),
          "confirmations.confirmations ro'yxat bo'lishi kerak")
    _need(isinstance(doc["notes"], (list, tuple)),
          "confirmations.notes ro'yxat bo'lishi kerak")
    for i, n in enumerate(doc["notes"]):
        _clean_text(n, f"confirmations.notes[{i}]")
    return list(doc["confirmations"])


def validate_confirmations(doc, *, graph: DiscoveryGraph | None = None) -> list[Confirmation]:
    """Tasdiq hujjatini ISHONMASDAN tekshiradi. Xato — `ConfirmationError`.

    Qaytaradi: DETERMINISTIK tartibdagi `Confirmation` ro'yxati. Kirish O'ZGARTIRILMAYDI.

    ⚠️ Hujjat `redact.scan()` dan ham o'tadi (fail-closed). Sabab: operatorning izohi ERKIN
       MATN va u ko'rik artefaktiga ko'chadi. Agar operator o'zini aloqa ma'lumoti bilan
       tanitgan yoki izohga ulanish satrini tashlab ketgan bo'lsa — SHU YERDA to'xtaydi, ya'ni
       xato sababiga yaqin joyda va tushunarli matn bilan. Kim tasdiqlagani ISM yoki xodim
       ID si bilan yoziladi, aloqa ma'lumoti bilan emas."""
    rows = _confirmation_rows(doc)
    out = [_validate_one(r, where=f"confirmations[{i}]", graph=graph)
           for i, r in enumerate(rows)]

    # ⚠️ Bir manzil uchun ikki qaror — RAD. Ular bir-birini jimgina almashtirardi va hujjatda
    #    qaysi biri «oxirgi» ekani ko'rinmasdi. Fikr o'zgargan bo'lsa YANGI hujjat yoziladi:
    #    tasdiq tarixi o'chirilmaydi, ustiga yozilmaydi.
    kalitlar = [c.key for c in out]
    dupes = sorted({f"{c} <- {a}" for c, a in kalitlar if kalitlar.count((c, a)) > 1})
    _need(not dupes,
          f"bir manzil uchun bir nechta qaror: {dupes} — fikr o'zgargan bo'lsa YANGI tasdiq "
          f"hujjati yoziladi, bir hujjat ichida ikki qaror bo'lmaydi")

    findings = redaction.scan(_to_json_rows(out))
    _need(not findings,
          "tasdiq hujjatida sir shubhasi bor — HUJJAT O'QILMAYDI: "
          + "; ".join(str(f) for f in findings[:10]))

    return sorted(out, key=lambda c: c.sort_key)


def _to_json_rows(rows) -> list[dict]:
    """Redaksiya skaneri uchun tekis ko'rinish (`redact.scan` lug'at/ro'yxat kutadi)."""
    return [{"target_concept": c.target_concept, "candidate_object": c.candidate_object,
             "candidate_field": c.candidate_field, "decision": c.decision,
             "operator": c.operator, "decided_at": c.decided_at, "note": c.note}
            for c in rows]


def _human_evidence(c: Confirmation, *, prefix: str) -> Evidence:
    """Odam qarorining dalili. `detail` da KIM, QACHON va (bo'lsa) NIMA ko'rgani turadi."""
    detail = f"{prefix}: {c.who_when}"
    if c.note:
        detail = f"{detail} · {c.note}"
    return Evidence(kind=HUMAN_EVIDENCE_KIND, detail=detail, weight=WEIGHT_STRONG)


def _sorted_evidence(rows) -> tuple[Evidence, ...]:
    """Dalillarni `ai._evidence_tuple` bilan AYNAN bir xil tartibga soladi (determinizm)."""
    return tuple(sorted(set(rows), key=lambda e: (e.kind, e.detail)))


def _sorted_text(rows) -> tuple[str, ...]:
    """Matn ro'yxatini `ai._text_tuple` bilan AYNAN bir xil tartibga soladi."""
    return tuple(sorted({s.strip() for s in rows}))


def _apply_one(h: Hypothesis, c: Confirmation) -> Hypothesis:
    """Bitta gipotezaga bitta qarorni qo'llaydi. Yangi obyekt qaytadi, kirish o'zgarmaydi."""
    if c.decision == DECISION_CONFIRM:
        # ⚠️ `confidence_score` ATAYLAB O'ZGARMAYDI. Odam tasdig'i modelning ballini
        #    oshirmaydi: ball — modelning O'Z bahosi, tasdiq esa BOSHQA TURDAGI bilim (ekranda
        #    ko'rilgan narsa). Ikkisini qo'shib yuborish «model juda ishonchli edi» degan
        #    gapni «odam ko'rdi» degan ma'noga aylantirardi, va keyin balli yuqori, lekin
        #    hech kim ko'rmagan nomzodni tasdiqlangandan ajratib bo'lmasdi.
        # ⚠️ Qarshi dalil O'CHIRILMAYDI: model rad etgan nomzodni operator tasdiqlagan bo'lsa,
        #    kelishmovchilik hujjatda KO'RINIB turishi kerak — u keyingi ko'rik uchun signal.
        return replace(
            h,
            status=STATUS_HUMAN_CONFIRMED,
            evidence=_sorted_evidence(h.evidence + (_human_evidence(c, prefix="tasdiqladi"),)),
        )

    if c.decision == DECISION_REJECT:
        # ⚠️ Operatorning sababi `counter_evidence` ga QO'SHILADI (`ai` da REJECTED uchun
        #    qarshi dalil MAJBURIY). Dalil turi o'sha `human_confirmed`: tur bilimning
        #    manbasini aytadi, yo'nalishni esa ro'yxat aytadi.
        return replace(
            h,
            status=STATUS_REJECTED,
            counter_evidence=_sorted_evidence(
                h.counter_evidence + (_human_evidence(c, prefix="rad etdi"),)),
        )

    # ⚠️ FAIL-CLOSED: bu yergacha yetgan qaror FAQAT `NEEDS_MORE_EVIDENCE` bo'lishi mumkin.
    #    Ilgari `else` yo'q edi, ya'ni CONFIRM va REJECT dan boshqa HAR QANDAY qiymat jimgina
    #    quyidagi shoxga tushib AMBIGUOUS bo'lardi va hujjatda «operator qo'shimcha dalil
    #    so'radi» degan yozuv paydo bo'lardi — operator esa bunday DEMAGAN. Bu eng yomon
    #    shakldagi nosozlik: hujjat yo'qdan MA'NO yasaydi va tashqaridan u haqiqiy qarordan
    #    farq qilmaydi. Noma'lum qaror — RAD.
    _need(c.decision == DECISION_NEEDS_MORE,
          f"{c.target_concept} <- {c.address}: qaror noma'lum: {c.decision!r} — ruxsat etilgani "
          f"{list(DECISIONS)}. Noma'lum qaror {DECISION_NEEDS_MORE} deb O'QILMAYDI: operator "
          f"aytmagan ma'no hujjatga yozilmaydi")

    # NEEDS_MORE_EVIDENCE — nomzod TIRIK qoladi, lekin ikkilanish holatida.
    # ⚠️ `ambiguity` ham to'ldiriladi, faqat `required_confirmation` emas: `ai` bo'yicha
    #    AMBIGUOUS gipotezada ikkilanish SABABI bo'sh bo'lmaydi. Aks holda shu funksiya
    #    o'zining validatoridan o'tmaydigan gipoteza yasagan bo'lardi.
    # ⚠️ DALILSIZ gipotezani AMBIGUOUS ga KO'CHIRIB BO'LMAYDI. `ai` bo'yicha REJECTED
    #    gipotezada `evidence` bo'sh bo'lishi mumkin (faqat qarshi dalil bor), AMBIGUOUS da
    #    esa BO'LMAYDI: dalilsiz gipoteza shunchaki taxmin. Shu bois bunday ko'chirish
    #    o'zining validatoridan O'TMAYDIGAN gipoteza yasardi — va u jimgina, hujjat to'liq
    #    ko'rinib turgan holda hosil bo'lardi. Fail-closed: RAD etamiz va SABABINI aytamiz.
    _need(h.evidence,
          f"{c.target_concept} <- {c.address}: {DECISION_NEEDS_MORE} qarori dalilsiz "
          f"gipotezaga qo'llanmaydi — AMBIGUOUS gipotezada foydasiga kamida bitta dalil "
          f"bo'lishi SHART (`ai`), dalilsiz nomzod esa shunchaki taxmin. Bunday nomzod uchun "
          f"{DECISION_REJECT} yoziladi yoki tahlil QAYTA o'tkaziladi")
    # ⚠️ Izoh SHU YERDA ham talab qilinadi: `note=None` bo'lsa quyidagi satrga Python ning
    #    `None` literali yozilib, operatorga ko'rinadigan matn «... so'radi (...): None» bo'lib
    #    chiqardi — ya'ni «nimasi yetmaydi» degan savolga hujjat ichida SOXTA javob paydo
    #    bo'lardi. Izohsiz so'rov keyingi qadamga hech narsa bermaydi, shu bois RAD.
    _need(c.note and c.note.strip(),
          f"{c.target_concept} <- {c.address}: {DECISION_NEEDS_MORE} qarorida izoh MAJBURIY — "
          f"nimasi yetmagani aytilmagan so'rov tekshirib bo'lmaydigan so'rov")
    so_rov = f"operator qo'shimcha dalil so'radi ({c.who_when}): {c.note}"
    sabab = f"operator hozircha tasdiqlamadi ({c.who_when})"
    with _code_gate("required_confirmation"):
        assert_no_raw_code(so_rov, where="required_confirmation")
    with _code_gate("ambiguity"):
        assert_no_raw_code(sabab, where="ambiguity")
    return replace(
        h,
        status=STATUS_AMBIGUOUS,
        required_confirmation=_sorted_text(h.required_confirmation + (so_rov,)),
        ambiguity=_sorted_text(h.ambiguity + (sabab,)),
    )


def apply_confirmations(hypotheses, doc) -> list[Hypothesis]:
    """Tasdiq hujjatini gipotezalarga qo'llaydi — `HUMAN_CONFIRMED` ga YAGONA yo'l.

    `hypotheses` — `validate_analysis` qaytargan `Hypothesis` obyektlari (xom lug'at EMAS:
    tekshirilmagan ma'lumot bu yo'l bilan holat o'zgartira olmaydi).
    `doc` — tasdiq hujjati (xom lug'at/ro'yxat yoki allaqachon tekshirilgan `Confirmation`
    ro'yxati).

    Qaror -> natija:
      · `CONFIRM`             -> `HUMAN_CONFIRMED`, `human_confirmed` dalili QO'SHILADI
                                 (`detail` da kim va qachon). `confidence_score` O'ZGARMAYDI.
      · `REJECT`              -> `REJECTED`, sabab `counter_evidence` ga qo'shiladi.
      · `NEEDS_MORE_EVIDENCE` -> `AMBIGUOUS`, so'rov `required_confirmation` ga qo'shiladi.
      · Tasdiqlanmagan gipoteza — O'ZGARMAYDI (bir bayt ham).

    ⚠️ Tasdiqda ko'rsatilgan, lekin gipotezalar ichida YO'Q nomzod JIMGINA TASHLANMAYDI —
       `ConfirmationError`. Sabab: operator qaror qildi deb hisoblaydi, natija esa hech qayerga
       tushmaydi. Bu eng xavfli nosozlik shakli — hujjat to'liq ko'rinadi, aslida esa qaror
       yo'qolgan. Ko'p uchraydigan sababi — tahlil YANGILANGAN va manzil o'zgargan: bunda
       tasdiq YANGI tahlilga qayta berilishi kerak, eskisiga emas.
    ⚠️ `VERIFIED` bu yerda paydo BO'LMAYDI: natija holatlari faqat `ai.STATUSES` dan.
       `HUMAN_CONFIRMED` — shu oqimning eng yuqori holati, migrator darvozasi EMAS.

    Qaytaradi: DETERMINISTIK tartibdagi YANGI ro'yxat. Kirish O'ZGARTIRILMAYDI (`Hypothesis`
    frozen, `replace` yangi obyekt yasaydi)."""
    _need(isinstance(hypotheses, (list, tuple)), "apply_confirmations ro'yxat kutadi")
    for i, h in enumerate(hypotheses):
        _need(isinstance(h, Hypothesis),
              f"hypotheses[{i}] `Hypothesis` bo'lishi kerak (ya'ni `validate_analysis` dan "
              f"o'tgan), kelgani {type(h).__name__}")

    # ⚠️ TAYYOR `Confirmation` obyektlari ham AYNI validatsiyadan o'tadi. Ilgari bu shox
    #    `validate_confirmations` ni UMUMAN chaqirmasdi (faqat tartiblab qo'yardi), ya'ni
    #    qo'lda qurilgan obyekt bilan hujjat darvozasining HAMMASI — anonim tasdiq taqiqi,
    #    vaqt shakli, sir skaneri va bir manzilga bitta qaror qoidasi — aylanib o'tilardi, va
    #    natija baribir `HUMAN_CONFIRMED` + kuchli `human_confirmed` dalil bo'lib chiqardi.
    #    Obyektlarni lug'atga aylantirib AYNI yo'ldan o'tkazamiz: bir kirish, bir darvoza.
    if isinstance(doc, (list, tuple)) and any(isinstance(x, Confirmation) for x in doc):
        _need(all(isinstance(x, Confirmation) for x in doc),
              "tasdiq ro'yxati ARALASH: `Confirmation` obyektlari va xom lug'atlar bir ro'yxatda "
              "berilgan — qaysi yozuv tekshirilganini aytib bo'lmaydi, shu bois RAD etiladi")
        rows = validate_confirmations(_to_json_rows(doc))
    else:
        rows = validate_confirmations(doc)

    # ⚠️ Gipotezalar ichida ham bir manzil ikki marta bo'lmasligi kerak (`validate_analysis`
    #    buni RAD etadi). Shu yerda qayta tekshiramiz, chunki chaqiruvchi ikki tahlilning
    #    ro'yxatini qo'shib yuborgan bo'lishi mumkin — va bunda qaror ikkita gipotezaga
    #    tushib, qaysi biri o'zgarganini aytib bo'lmasdi.
    by_key: dict[tuple[str, str], Hypothesis] = {}
    for h in hypotheses:
        kalit = (h.target_concept, h.address)
        _need(kalit not in by_key,
              f"gipotezalar ichida takroriy manzil: {h.target_concept} <- {h.address} — "
              f"tasdiq qaysi biriga tegishli ekani aniqlanmaydi")
        by_key[kalit] = h

    yetim = sorted(f"{c.target_concept} <- {c.address}" for c in rows if c.key not in by_key)
    _need(not yetim,
          f"tasdiqda ko'rsatilgan nomzod gipotezalar ichida YO'Q: {yetim}. Qaror JIMGINA "
          f"tashlanmaydi — tahlil yangilangan bo'lsa tasdiq YANGI tahlilga berilishi kerak")

    natija = dict(by_key)
    for c in rows:
        natija[c.key] = _apply_one(by_key[c.key], c)

    for h in natija.values():
        # ⚠️ Chiqishning o'z darvozasi: shu funksiya `VERIFIED` ni ham, ro'yxatda yo'q holatni
        #    ham yasay olmasligi KERAK. Tekshiruv arzon, jim buzilish esa qimmat.
        _need(h.status != FORBIDDEN_STATUS and h.status in STATUSES,
              f"ichki xato: {h.target_concept} <- {h.address} uchun yasalgan holat "
              f"{h.status!r} ruxsat etilmagan (ruxsat etilgani "
              f"{list(AI_STATUSES) + [STATUS_HUMAN_CONFIRMED]})")

    return sorted(natija.values(), key=lambda h: h.sort_key)
