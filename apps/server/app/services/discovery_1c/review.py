# -*- coding: utf-8 -*-
"""KO'RIK ARTEFAKTI — `discovery_ai_candidates.json` (`binos-1c-ai-candidates-v1`).

Bu modul AI tahlilining natijasini ODAM O'QIYDIGAN va ODAM QAROR QILADIGAN shaklga keltiradi:
mashina uchun deterministik JSON (`dumps_review`) va operator uchun Markdown varaq
(`build_operator_worksheet`).

⚠️ ARTEFAKT XARITA EMAS, SAVOLLAR RO'YXATI. Har bir qatori — «shunday bo'lishi mumkin» degan
   taxmin, dalili va NIMANI ko'rish kerakligi bilan. Bu yerda hech narsa tasdiqlanmagan.
⚠️ `VERIFIED` bu artefaktda YO'Q va bo'lishi ham mumkin emas (`ai.FORBIDDEN_STATUS`). Ko'rikdan
   keyingi eng yuqori holat — `HUMAN_CONFIRMED`, va u SHU faylga yozilmaydi: u operatorning
   ALOHIDA tasdiq hujjatidan (`confirmations.py`) keladi. Ikkisi bir faylda bo'lsa, modelning
   chiqishi o'zini tasdiq deb e'lon qila olardi.
⚠️ QARALMAGAN KONSEPT TASHLANMAYDI: u `unknown_concepts` ro'yxatida UNKNOWN bo'lib turadi.
   Tushirib qoldirilgan konsept keyinchalik «tekshirilgan va topilmagan» deb o'qilardi, ya'ni
   «qaralmadi» jimgina «yo'q» ga aylanardi.
⚠️ JIM QISISH YO'Q: tahlilchining izohlari (`analyzer_notes`) artefaktga ham, operator
   varaqasining BOSHIGA ham chiqadi. Aynan ular «nomzodlar soni chegaraga qisilgan» deb aytadi,
   ya'ni ro'yxatdan ishonchli nomzod chiqarilganining YAGONA yozuvi. Izoh berilmagan bo'lsa,
   varaq buni ham OCHIQ aytadi: bo'sh ro'yxat «hech narsa qisilmadi» degani emas.
⚠️ ARTEFAKTNI YOZISHDAN OLDIN `redact.scan()` (fail-closed): sir shubhasi bo'lsa ISTISNO va
   hech narsa yozilmaydi. Bu fayl qo'ldan-qo'lga o'tadi, ya'ni u do'konning sirini olib
   chiqadigan eng qulay yo'l.
⚠️ Vaqt tamg'asi bu yerda O'YLAB CHIQARILMAYDI: artefaktda umuman vaqt yo'q. Kim qachon
   tasdiqlagani — tasdiq hujjatining maydoni, va u yerga OPERATOR yozadi.

DETERMINIZM: nomzodlar `Hypothesis.sort_key` bo'yicha, dalillar va matnlar tahlil validatorida
tartiblangan holda keladi, JSON esa `bundle.dumps` bilan yoziladi (tartiblangan kalit, UTF-8,
ortiqcha probelsiz). Bir xil kirish — AYNAN bir xil bayt, ya'ni ikki ko'rikni diff bilan
solishtirib ko'rish mumkin.

Bu modulda birorta konfiguratsiya nomi YO'Q. Izohdagi misollar (`X17`, `R41`) — TO'QIMA nomlar.
"""
from __future__ import annotations

import re

from . import redact as redaction
from .ai import (AnalysisError, FORBIDDEN_STATUS, Hypothesis, STATUSES, hypothesis_to_json,
                 unknown_concepts)
from .bundle import dumps
from .confirmations import CONFIRMATIONS_VERSION, DECISIONS
from .graph import DiscoveryGraph, graph_stats

REVIEW_VERSION = "binos-1c-ai-candidates-v1"

#: Artefaktning fayl nomi — shartnomaning bir qismi: operator ayni shu nomni izlaydi.
REVIEW_FILENAME = "discovery_ai_candidates.json"

REVIEW_KEYS = {"review_version", "analyzer", "analyzer_notes", "graph", "coverage", "candidates",
               "unknown_concepts", "counts", "warnings"}
CANDIDATE_KEYS = {"concept", "candidate_object", "candidate_field", "confidence_score",
                  "status", "evidence", "counter_evidence", "ambiguity", "explanation",
                  "required_confirmation", "recommended_next_probe"}

#: Sanoq MATNining shakli (`bundle.COUNT_TEXT_RE` bilan bir xil qat'iylik).
_COUNT_RE = re.compile(r"[0-9]{1,18}")

#: Bo'laklarni ajratuvchi. ⚠️ Nuqtali vergul EMAS: `probe.assert_no_raw_code` uni kod belgisi
#: deb biladi, va bu matnlar biror kun zond sababi bo'lib qaytishi mumkin.
_SEP = " · "

#: Artefakt O'ZI bilan olib yuradigan ogohlantirishlar.
#: ⚠️ Ular ATAYLAB JSON ichida ham turadi, faqat Markdown varaqda emas: JSON ni o'qigan dastur
#: (yoki keyingi model) varaqni ko'rmaydi, va ogohlantirishsiz bu ro'yxat tayyor xaritaga
#: o'xshab ketardi.
WARNINGS = (
    "Bu artefakt TAXMINLAR ro'yxati. Hech bir qatori tasdiqlanmagan va ko'chirishga ruxsat "
    "bermaydi.",
    "confidence_score — modelning O'Z bahosi, DALIL EMAS. U faqat ko'rik NAVBATINI belgilaydi.",
    "Nom mosligi o'zi bilan hech narsani tasdiqlamaydi — u eng kuchsiz dalil turi.",
    "unknown_concepts — QARALMAGAN konseptlar. «Qaralmadi» «yo'q» degani EMAS.",
    f"Tasdiq faqat ALOHIDA hujjatdan keladi ({CONFIRMATIONS_VERSION}) — bu faylga yozilmaydi.",
    "analyzer_notes — tahlilchining O'Z izohlari: nomzodlar soni CHEGARAGA QISILGANI ham shu "
    "yerda aytiladi. Bo'sh ro'yxat «hech narsa qisilmadi» degani EMAS — u «izoh berilmadi».",
)


class ReviewError(AnalysisError):
    """Ko'rik artefakti shartnomaga mos emas — YOZILMAYDI.

    `AnalysisError` dan meros: tahlil oqimini o'qiydigan kod bitta `except` bilan bularni ham
    qamrab oladi."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ReviewError(msg)


def _keys(obj, allowed: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra, f"{where}: noma'lum kalit(lar) {extra} — {REVIEW_VERSION} da yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, f"{where}: kalit(lar) tushib qolgan {missing}")


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip(), f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v.strip()


def _coverage(raw, where: str = "coverage") -> dict[str, str]:
    """Ixtiyoriy qamrov sanoqlari: nom -> SANOQ MATNI.

    ⚠️ Qiymatlar MATN, son EMAS (`binos-1c-metadata-v1` 1-invarianti): sanoq JSON soni bo'lib
       qolsa boshidagi nollar bilan birga ma'no yo'qoladi.
    ⚠️ Qamrov bu yerda HISOBLANMAYDI, faqat KO'CHIRILADI: uni kim o'lchagan bo'lsa, o'sha
       javobgar. O'ylab chiqarilgan qamrov «hammasi ko'rildi» degan yolg'on xotirjamlik berardi.
    ⚠️ `None` va `{}` FARQ QILADI — birinchisi «o'lchanmadi», ikkinchisi «o'lchandi va bo'sh».
       Shu bois `None` da kalit umuman qo'shilmaydi."""
    _need(isinstance(raw, dict), f"{where} obyekt bo'lishi kerak")
    out: dict[str, str] = {}
    for k in sorted(raw):
        _nonempty(k, f"{where} kaliti")
        v = raw[k]
        _need(isinstance(v, str) and _COUNT_RE.fullmatch(v),
              f"{where}[{k!r}] sanoq MATNI bo'lishi kerak (JSON soni TAQIQLANGAN) — "
              f"kelgani {v!r}")
        out[k] = v
    return out


def _explanation(h: Hypothesis) -> str:
    """AI tushuntirishi — DALILLARDAN YIG'ILADI, o'ylab chiqarilmaydi.

    ⚠️ Bu qator BIR BAYT YANGI DA'VO qo'shmaydi: u faqat holatni, dalil tafsilotlarini, qarshi
       dalilni va ikkilanish sababini bitta o'qiladigan gapga tizadi. Sabab: erkin «tushuntirish»
       maydoni dalilsiz gapni hujjatga olib kiradigan eng qulay teshik bo'lardi — modelning
       chiroyli jumlasi dalil o'rnini egallab qolardi. Shu bois tushuntirishda ko'ringan har bir
       narsa yonidagi `evidence` ro'yxatida ham turadi va tekshirilgan.
    ⚠️ `confidence_score` bu gapga ATAYLAB kirmaydi: baho tushuntirishga qo'shilsa, u dalil
       qatoriga o'xshab ketardi."""
    bo_laklar = [f"holat {h.status}"]
    if h.evidence:
        bo_laklar.append("dalil: " + _SEP.join(f"{e.kind} — {e.detail}" for e in h.evidence))
    else:
        # ⚠️ `ai` bo'yicha CANDIDATE va AMBIGUOUS dalilsiz bo'lmaydi, ya'ni bu shoxga faqat
        #    REJECTED tushadi. Baribir OCHIQ yozamiz: dalil yo'qligi ham javobning bir qismi.
        bo_laklar.append("dalil YO'Q")
    if h.counter_evidence:
        bo_laklar.append("qarshi dalil: "
                         + _SEP.join(f"{e.kind} — {e.detail}" for e in h.counter_evidence))
    if h.ambiguity:
        bo_laklar.append("ikkilanish: " + _SEP.join(h.ambiguity))
    return ". ".join(bo_laklar)


def _candidate(h: Hypothesis, *, where: str, graph: DiscoveryGraph) -> dict:
    """Bitta nomzodning artefakt qatori."""
    _need(isinstance(h, Hypothesis),
          f"{where} `Hypothesis` bo'lishi kerak (ya'ni `validate_analysis` dan o'tgan), "
          f"kelgani {type(h).__name__}")
    # ⚠️ Holat darvozasi shu yerda ham: artefakt `VERIFIED` ni HECH QANDAY yo'l bilan olib
    #    chiqmasligi kerak. Tekshiruv arzon, jim buzilish esa artefaktni «tasdiqlangan xarita»
    #    qilib ko'rsatardi.
    _need(h.status != FORBIDDEN_STATUS and h.status in STATUSES,
          f"{where}.status ruxsat etilmagan: {h.status!r} — {FORBIDDEN_STATUS} bu artefaktda "
          f"BO'LMAYDI, ruxsat etilgani {list(STATUSES)}")
    # ⚠️ Nomzod SHU grafda ham bo'lishi kerak. Bu `validate_analysis` tekshiruvining takrori
    #    EMAS: tahlil BOSHQA (eskiroq) inventarizatsiya ustida qilingan bo'lishi mumkin, va
    #    bunda artefakt operatorni endi mavjud bo'lmagan obyektni izlashga yuborardi.
    _need(graph.by_full_name(h.candidate_object) is not None,
          f"{where}.candidate_object berilgan grafda yo'q: {h.candidate_object!r} — tahlil "
          f"boshqa inventarizatsiya ustida qilingan bo'lishi mumkin, artefakt esa operator "
          f"TEKSHIRA OLADIGAN nomzodni ko'rsatishi kerak")

    row = hypothesis_to_json(h)
    return {
        # ⚠️ Kalit `concept` (tahlildagi `target_concept` emas): artefaktda «nishon» so'zi
        #    `schema.TARGETS` ni eslatardi, bu esa ko'chirish rejasining lug'ati. Ko'rik hali
        #    reja emas.
        "concept": row["target_concept"],
        "candidate_object": row["candidate_object"],
        "candidate_field": row["candidate_field"],
        "confidence_score": row["confidence_score"],
        "status": row["status"],
        "evidence": row["evidence"],
        "counter_evidence": row["counter_evidence"],
        "ambiguity": row["ambiguity"],
        "explanation": _explanation(h),
        "required_confirmation": row["required_confirmation"],
        "recommended_next_probe": row["recommended_next_probe"],
    }


def _analyzer_notes(raw, where: str = "analyzer_notes") -> list[str]:
    """Tahlilchining izohlari — KO'CHIRILADI, talqin qilinmaydi.

    ⚠️ NEGA KERAK: analitik `notes` da «Nomzodlar soni chegaraga qisilgan konseptlar» ni
       yozadi, va bu `keep_window`/`max_per_concept` tufayli ishonchli nomzod ro'yxatdan
       CHIQARILGANINING YAGONA yozuvi. Izoh artefaktga yetmasa, operator kesilgan nomzodni
       ko'rmaydi va umuman biror narsa kesilganini BILMAYDI — ya'ni «jim qisish yo'q» qoidasi
       jimgina buzilardi.
    ⚠️ Izohdan XULOSA o'qilmaydi (`ai._analysis_rows` bilan bir xil qoida): u dalil emas,
       ogohlantirish. Shu bois artefaktda alohida kalitda turadi va nomzod qatoriga
       aralashmaydi.
    ⚠️ TARTIB O'ZGARTIRILMAYDI: izohlar analitik yozgan navbatda turadi (qisish haqidagi
       ogohlantirish oxirida keladi), tartiblash uni boshqa joyga surib qo'yardi. Determinizm
       shundan ham buzilmaydi: kirish bir xil bo'lsa, chiqish ham bir xil."""
    _need(isinstance(raw, (list, tuple)), f"{where} ro'yxat bo'lishi kerak")
    return [_nonempty(n, f"{where}[{i}]") for i, n in enumerate(raw)]


def build_review(hypotheses, *, graph: DiscoveryGraph, analyzer_name: str,
                 analyzer_version: str, coverage=None, analyzer_notes=()) -> dict:
    """Ko'rik artefaktining lug'atini quradi. Xato — `ReviewError`.

    `hypotheses` — `validate_analysis` qaytargan `Hypothesis` obyektlari (xom lug'at EMAS:
    tekshirilmagan ma'lumot bu yo'l bilan artefaktga tusha olmaydi).
    `graph`      — AYNAN shu artefakt tegishli bo'lgan inventarizatsiya grafi.
    `analyzer_*` — tahlilni kim qilgani. ⚠️ MAJBURIY: qaysi tahlilchi aytganini bilmasdan
                   natijani qaytarib tekshirib bo'lmaydi, va uni yaxshilab ham bo'lmaydi.
    `coverage`   — ixtiyoriy qamrov sanoqlari (`None` = o'lchanmadi).
    `analyzer_notes` — tahlilchining izohlari (`ai` ning `notes` i). ⚠️ IXTIYORIY, chunki
                   `validate_analysis` hozircha `notes` ni CHIQARMAYDI: u faqat tekshiradi va
                   gipotezalarni qaytaradi, izohlar esa yo'lda tushib qoladi. Shu bois
                   chaqiruvchi izohlarni O'ZI uzatishi kerak; uzatilmasa, artefakt va operator
                   varaqasi buni OCHIQ aytadi («izoh berilmagan»), chunki bo'sh ro'yxat «hech
                   narsa qisilmadi» degani emas.

    Qaytaradi: DETERMINISTIK lug'at. Kirish O'ZGARTIRILMAYDI."""
    _need(isinstance(graph, DiscoveryGraph),
          f"build_review `DiscoveryGraph` kutadi, kelgani {type(graph).__name__}")
    _need(isinstance(hypotheses, (list, tuple)), "build_review gipotezalar ro'yxatini kutadi")
    name = _nonempty(analyzer_name, "analyzer_name")
    version = _nonempty(analyzer_version, "analyzer_version")

    # ⚠️ Tur AVVAL tekshiriladi, tartiblashdan OLDIN: aks holda xom lug'at `sort_key` da
    #    tushunarsiz `AttributeError` bilan yiqilardi, ya'ni xato sababi ko'rinmasdi.
    for i, h in enumerate(hypotheses):
        _need(isinstance(h, Hypothesis),
              f"hypotheses[{i}] `Hypothesis` bo'lishi kerak (ya'ni `validate_analysis` dan "
              f"o'tgan), kelgani {type(h).__name__}")
    rows = sorted(hypotheses, key=lambda h: h.sort_key) if hypotheses else []
    candidates = [_candidate(h, where=f"candidates[{i}]", graph=graph)
                  for i, h in enumerate(rows)]

    # ⚠️ Bir manzil ikki marta chiqmasligi kerak: artefaktda ikki qator bo'lsa, operator
    #    qaysi birini tasdiqlaganini `confirmations` ayta olmasdi (u manzil bo'yicha moslaydi).
    manzillar = [(h.target_concept, h.address) for h in rows]
    dupes = sorted({f"{c} <- {a}" for c, a in manzillar if manzillar.count((c, a)) > 1})
    _need(not dupes,
          f"artefaktda takroriy manzil: {dupes} — ikkilanish AMBIGUOUS bilan aytiladi, takror "
          f"qator bilan emas")

    holat_bo_yicha: dict[str, int] = {}
    for h in rows:
        holat_bo_yicha[h.status] = holat_bo_yicha.get(h.status, 0) + 1

    noma_lum = list(unknown_concepts(rows))
    doc = {
        "review_version": REVIEW_VERSION,
        "analyzer": {"name": name, "version": version},
        # ⚠️ Tahlilchining izohlari artefaktga YETIB BORADI: qisilgan nomzod haqidagi
        #    ogohlantirish shu ro'yxatda yashaydi va u yo'qolsa hech narsa o'rnini bosmaydi.
        "analyzer_notes": _analyzer_notes(analyzer_notes),
        # ⚠️ Graf SANOQLARI kiradi, grafning O'ZI kirmaydi: artefakt ko'rik varaqasi, to'liq
        #    inventarizatsiyaning nusxasi emas. Sanoqlar esa nomzod qanchalik katta maydondan
        #    tanlanganini ko'rsatadi — bittadan bittani «tanlash» tahlil emas.
        "graph": graph_stats(graph),
        "candidates": candidates,
        "unknown_concepts": noma_lum,
        "counts": {
            "candidates": str(len(candidates)),
            "by_status": {k: str(holat_bo_yicha[k]) for k in sorted(holat_bo_yicha)},
            "unknown_concepts": str(len(noma_lum)),
        },
        "warnings": list(WARNINGS),
    }
    # ⚠️ `None` va `{}` farqi saqlanadi: o'lchanmagan qamrov uchun kalit UMUMAN bo'lmaydi,
    #    aks holda bo'sh lug'at «o'lchandi va hech narsa topilmadi» deb o'qilardi.
    doc["coverage"] = _coverage(coverage) if coverage is not None else None

    _scan(doc, where="build_review")
    return doc


def _scan(doc, *, where: str) -> None:
    """Redaksiya darvozasi (fail-closed): sir shubhasi bo'lsa ISTISNO.

    ⚠️ Artefakt ichiga sir uch yo'l bilan tushishi mumkin: obyekt izohi (u metadatadan keladi),
       operatorning matni (u tasdiq orqali dalil `detail` iga tushadi) va `analyzer_*`. Uchovi
       ham SHU darvozadan o'tadi.
    ⚠️ Yolg'on ijobiy — bir marta qo'lda ko'rish; yolg'on salbiy — mijozning sirini artefakt
       bilan birga tashqariga chiqarish."""
    findings = redaction.scan(doc)
    _need(not findings,
          f"{where}: artefaktda sir shubhasi bor — HECH NARSA YOZILMAYDI: "
          + "; ".join(str(f) for f in findings[:10]))


def dumps_review(doc) -> bytes:
    """Artefaktni DETERMINISTIK baytlarga aylantiradi (`bundle.dumps` uslubi).

    ⚠️ `bundle.dumps` QAYTA ISHLATILADI, o'z serializatsiyasi yozilmaydi: ikki joyda ikki xil
       yozuvchi bo'lsa, ular bir kun bir-biridan ajralib ketardi va «bir xil kirish — bir xil
       bayt» kafolati jimgina yo'qolardi.
    ⚠️ Redaksiya QAYTA tekshiriladi, garchi `build_review` allaqachon tekshirgan bo'lsa ham:
       lug'at ikki chaqiruv orasida o'zgartirilgan bo'lishi mumkin, va YOZISHDAN OLDINGI holat
       muhim. Skanerni yozuvchining o'ziga yopishtirib qo'yamiz, ya'ni uni chetlab o'tib
       yozishning yo'li yo'q."""
    _validate_review(doc)
    _scan(doc, where="dumps_review")
    return dumps(doc).encode("utf-8")


def _validate_review(doc) -> dict:
    """Artefakt lug'atining SHAKLINI tekshiradi (yozishdan va varaq yasashdan oldin).

    ⚠️ Tekshiruv `build_review` ga ishonmaydi: artefakt fayldan qayta o'qilgan yoki qo'lda
       tahrirlangan bo'lishi mumkin, va varaq shundan yasaladi."""
    _keys(doc, REVIEW_KEYS, "review")
    _need(doc["review_version"] == REVIEW_VERSION,
          f"review.review_version {REVIEW_VERSION!r} bo'lishi kerak, "
          f"kelgani {doc['review_version']!r}")
    _keys(doc["analyzer"], {"name", "version"}, "review.analyzer")
    for k in ("name", "version"):
        _nonempty(doc["analyzer"][k], f"review.analyzer.{k}")
    # ⚠️ Fayldan qayta o'qilgan artefaktda ham izohlar kaliti BO'LISHI SHART: kalitning o'zi
    #    yo'qolsa, «izoh berilmagan» va «izoh bor edi, yo'qoldi» farqi bilinmasdi.
    _analyzer_notes(doc["analyzer_notes"], "review.analyzer_notes")
    _need(isinstance(doc["graph"], dict), "review.graph obyekt bo'lishi kerak")
    _need(doc["coverage"] is None or isinstance(doc["coverage"], dict),
          "review.coverage obyekt yoki null bo'lishi kerak (null = o'lchanmadi)")
    _need(isinstance(doc["candidates"], list), "review.candidates ro'yxat bo'lishi kerak")
    _need(isinstance(doc["unknown_concepts"], list),
          "review.unknown_concepts ro'yxat bo'lishi kerak")
    _need(isinstance(doc["warnings"], list) and doc["warnings"],
          "review.warnings bo'sh bo'lmagan ro'yxat bo'lishi kerak — artefakt o'z "
          "ogohlantirishini O'ZI bilan olib yuradi")
    _need(isinstance(doc["counts"], dict), "review.counts obyekt bo'lishi kerak")

    for i, c in enumerate(doc["candidates"]):
        w = f"review.candidates[{i}]"
        _keys(c, CANDIDATE_KEYS, w)
        _need(c["status"] != FORBIDDEN_STATUS and c["status"] in STATUSES,
              f"{w}.status ruxsat etilmagan: {c['status']!r} — {FORBIDDEN_STATUS} bu "
              f"artefaktda BO'LMAYDI")
        _nonempty(c["concept"], f"{w}.concept")
        _nonempty(c["candidate_object"], f"{w}.candidate_object")
        _nonempty(c["explanation"], f"{w}.explanation")
    return doc


# ── Operator varaqasi ──────────────────────────────────────────────────────────────────────
def _bullets(rows, *, bo_sh: str, prefix: str = "  - ") -> list[str]:
    """Ro'yxatni Markdown punktlariga aylantiradi. Bo'sh ro'yxat ham OCHIQ yoziladi.

    ⚠️ Bo'sh ro'yxat tushirib qoldirilmaydi: «qarshi dalil yo'q» va «qarshi dalil qaralmadi»
       operator uchun boshqa-boshqa narsa, va bo'sh sarlavha bo'lmasa u ikkinchisini
       birinchisi deb o'qib ketardi."""
    if not rows:
        return [f"{prefix}{bo_sh}"]
    return [f"{prefix}{s}" for s in rows]


def _evidence_lines(rows) -> list[str]:
    return [f"{e['kind']} ({e['weight']}) — {e['detail']}" for e in rows]


def build_operator_worksheet(doc) -> str:
    """Odam o'qiydigan Markdown varaq — operator ayni shu varaq bilan ekran oldida o'tiradi.

    Har nomzod uchun: konsept, nomzod manzili, ball, tushuntirish, dalil, qarshi dalil,
    ikkilanish, keyingi zond va OPERATOR NIMA QILISHI kerakligi.

    ⚠️ Varaq DETERMINISTIK: nomzodlar artefaktdagi tartibda, ro'yxatlar allaqachon tartiblangan.
    ⚠️ Varaq QAROR YOZILADIGAN JOY EMAS: qaror alohida hujjatga tushadi
       (`confirmations.py`), chunki varaqdagi belgi AI chiqishining ichida qolib, keyin
       «model o'zini tasdiqladi» degan holatga olib kelardi."""
    _validate_review(doc)

    a = doc["analyzer"]
    g = doc["graph"]
    n = doc["counts"]
    satrlar = [
        "# 1C discovery — AI nomzodlari (OPERATOR KO'RIGI)",
        "",
        f"- Tahlilchi: {a['name']} {a['version']}",
        f"- Nomzodlar: {n.get('candidates', '?')} · qaralmagan konseptlar: "
        f"{n.get('unknown_concepts', '?')}",
        f"- Graf: obyektlar {g.get('objects', '?')} · maydonlar {g.get('fields', '?')} · "
        f"bog'lanishlar {g.get('relationships', '?')}",
    ]
    holat = n.get("by_status") or {}
    if isinstance(holat, dict) and holat:
        satrlar.append("- Holatlar: " + _SEP.join(f"{k}: {holat[k]}" for k in sorted(holat)))
    if doc["coverage"] is None:
        # ⚠️ «O'lchanmadi» OCHIQ yoziladi: qamrov satri yo'qolsa, varaq to'liq ko'rinardi.
        satrlar.append("- Qamrov: O'LCHANMADI (bu «hammasi ko'rildi» degani EMAS)")
    else:
        cov = doc["coverage"]
        satrlar.append("- Qamrov: "
                       + (_SEP.join(f"{k}: {cov[k]}" for k in sorted(cov)) or "bo'sh"))
    # ⚠️ TAHLILCHI IZOHLARI VARAQNING BOSHIDA, nomzodlardan OLDIN: aynan shu yerda «nomzodlar
    #    soni chegaraga qisilgan» deb yoziladi, ya'ni quyidagi ro'yxat TO'LIQ EMASligi haqidagi
    #    yagona ogohlantirish shu. Oxiriga yashirilsa, operator ro'yxatni to'liq deb o'qib
    #    bo'lgan bo'lardi.
    satrlar += ["", "## Tahlilchi izohlari (CHEGARA VA QISILISH SHU YERDA aytiladi)", ""]
    if doc["analyzer_notes"]:
        satrlar += [f"- ⚠️ {n}" for n in doc["analyzer_notes"]]
    else:
        # ⚠️ Izoh yo'qligi JIM QOLDIRILMAYDI: bo'sh ro'yxat «hech narsa qisilmadi» degani emas.
        #    Ro'yxatning to'liqligi bu varaqda ISBOTLANMAGAN va buni operator bilishi kerak.
        satrlar.append(
            "- ⚠️ IZOH BERILMAGAN: tahlilchi izohlari bu artefaktga uzatilmagan. Nomzodlar "
            "soni chegara bilan QISILGAN bo'lsa, kesilgan nomzod bu varaqda KO'RINMAYDI — "
            "ya'ni quyidagi ro'yxatning to'liqligi ISBOTLANMAGAN.")
    satrlar += ["", f"Qaror `{CONFIRMATIONS_VERSION}` hujjatiga yoziladi — SHU VARAQQA EMAS.",
                ""]

    if not doc["candidates"]:
        satrlar += ["## Nomzod yo'q", "",
                    "Tahlil birorta nomzod bermadi. ⚠️ Bu «mos narsa yo'q» degani EMAS — "
                    "quyidagi qaralmagan konseptlar ro'yxatiga qarang.", ""]

    for c in doc["candidates"]:
        manzil = c["candidate_object"]
        if c["candidate_field"] is not None:
            manzil = f"{manzil}.{c['candidate_field']}"
        satrlar += [
            f"## {c['concept']} <- {manzil}",
            "",
            f"- Holat: {c['status']}",
            f"- Ball: {c['confidence_score']} ⚠️ modelning O'Z bahosi, DALIL EMAS",
            f"- Tushuntirish: {c['explanation']}",
            "- Dalil:",
            # ⚠️ Dalil yo'qligi BOSH HARF bilan: bu holat faqat REJECTED da qonuniy, boshqa
            #    holatda esa shartnoma buzilgani ko'rinib turishi kerak.
            *_bullets(_evidence_lines(c["evidence"]),
                      bo_sh="YO'Q — bu qator dalilsiz, ya'ni tekshirishga hech narsa bermaydi"),
            "- Qarshi dalil:",
            *_bullets(_evidence_lines(c["counter_evidence"]), bo_sh="yo'q"),
            "- Noaniqlik:",
            *_bullets(c["ambiguity"], bo_sh="aytilmagan"),
            "- Operator NIMANI ko'rishi kerak:",
            *_bullets(c["required_confirmation"],
                      bo_sh="AYTILMAGAN — bu gipotezani tekshirib bo'lmaydi"),
            "- Keyingi zond:",
            *_bullets([f"{p['probe_type']} -> {p['target_object']} — {p['reason']}"
                       for p in c["recommended_next_probe"]], bo_sh="tavsiya etilmagan"),
            f"- QAROR (bittasini tanlang): {' / '.join(f'`{d}`' for d in DECISIONS)}",
            f"  Tasdiq hujjatida manzil: concept={c['concept']} · "
            f"object={c['candidate_object']} · field={c['candidate_field']}",
            "",
        ]

    satrlar += ["## Qaralmagan konseptlar (UNKNOWN)", ""]
    if doc["unknown_concepts"]:
        satrlar += [f"- {x} — birorta nomzod topilmadi" for x in doc["unknown_concepts"]]
    else:
        satrlar.append("- yo'q: har bir konsept uchun kamida bitta nomzod bor")
    satrlar += [
        "",
        "⚠️ «Qaralmadi» «yo'q» degani EMAS. Bu ro'yxatdagi konsept uchun javob HALI yo'q, "
        "ya'ni uni «shu konfiguratsiyada mavjud emas» deb o'qish xato.",
        "",
        "---",
        "",
    ]
    # ⚠️ Ogohlantirish varaqning OXIRIDA, ya'ni operator qaror qilishdan oldin oxirgi
    #    o'qiydigan narsa shu bo'ladi.
    satrlar += [f"⚠️ {w}" for w in doc["warnings"]]
    satrlar += [
        f"⚠️ {FORBIDDEN_STATUS} bu varaqda BERILMAYDI va u umuman bu oqimning qarori emas: "
        "u migrator darvozasi va alohida kuchli dalil talab qiladi.",
        "",
    ]
    return "\n".join(satrlar)
