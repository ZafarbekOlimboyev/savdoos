# -*- coding: utf-8 -*-
"""OPERATOR TASDIG'I VA KO'RIK ARTEFAKTI — `binos-1c-confirmations-v1` shartnomasi.

Bu fayl tasdiq oqimining ENG MUHIM chegarasini qulflaydi: `HUMAN_CONFIRMED` ga olib boradigan
YAGONA yo'l — operatorning ALOHIDA hujjati, va shu yo'ldan `VERIFIED` HECH QACHON chiqmaydi.

⚠️ NIMA SINALADI: shartnoma va INVARIANTLAR — kim tasdiqlagani majburiyligi, ballning
   o'zgarmasligi, jim tushib qolishning yo'qligi, determinizm va fail-closed redaksiya.
⚠️ NIMA ISBOTLANMAYDI: birorta haqiqiy konfiguratsiyada tahlilning to'g'riligini. Fikstura
   `discovery_1c_metadata_synth` dagi TO'QIMA `G` konfiguratsiyasi (`Catalog.X17`,
   `InformationRegister.ABCD`) — nomlardan hech narsa bilinmaydi va bu ataylab.
⚠️ Vaqt BU FAYLNING KIRISHI (`DECIDED_AT`), hisoblanmaydi: `Date.now()` kabi narsa testni
   determinizmdan ayirardi va bir xil kirish har yurishda boshqa bayt berardi.
"""
from __future__ import annotations

import pytest

from app.services.discovery_1c import confirmations as C
from app.services.discovery_1c import review as V
from app.services.discovery_1c.ai import (FORBIDDEN_STATUS, STATUS_AMBIGUOUS, STATUS_CANDIDATE,
                                          STATUS_HUMAN_CONFIRMED, STATUS_REJECTED,
                                          AnalysisError, hypotheses_to_json,
                                          hypothesis_to_json, validate_analysis)
from app.services.discovery_1c.bundle import dumps
from app.services.discovery_1c.graph import build_graph
from tests.discovery_1c_metadata_synth import config

# ── Fikstura ───────────────────────────────────────────────────────────────────────────────
#: ⚠️ `G` ataylab: nomlar ma'nosiz (`X17`, `ABCD`), ya'ni bitta test ham nom mosligiga
#: tayanib qolmaydi. Manzillar grafdan olinadi, o'ylab chiqarilmaydi.
GRAF = build_graph(config("G"))

OBYEKT = "Catalog.X17"
MAYDON = "F1"
OBYEKT_2 = "InformationRegister.ABCD"
MAYDON_2 = "V1"

#: ⚠️ Operator ISM yoki xodim ID si bilan yoziladi, aloqa ma'lumoti bilan EMAS: aks holda
#: tasdiq hujjati do'konning shaxsiy ma'lumotini olib chiqib ketardi (redaksiya darvozasi).
OPERATOR = "Sotuvchi-7 (xodim ID 41)"
DECIDED_AT = "2026-09-30T11:20:00+05:00"


def dalil(kind: str = "name_match", detail: str = "obyekt nomi kutilgan atamaga uzoqdan mos",
          weight: str = "weak") -> dict:
    """Bitta KUCHSIZ dalil. ⚠️ AI kanalida faqat kuchsiz dalil bo'ladi."""
    return {"kind": kind, "detail": detail, "weight": weight}


def xom_gipoteza(*, concept: str = "product", obj: str = OBYEKT, field=None,
                 status: str = STATUS_CANDIDATE, score: float = 0.4, evidence=None,
                 counter=(), ambiguity=(), confirmation=None, probes=()) -> dict:
    """Modeldan kelishi mumkin bo'lgan XOM gipoteza lug'ati (hamma kalit to'ldirilgan)."""
    return {
        "target_concept": concept,
        "candidate_object": obj,
        "candidate_field": field,
        "confidence_score": score,
        "evidence": [dalil()] if evidence is None else list(evidence),
        "counter_evidence": list(counter),
        "ambiguity": list(ambiguity),
        "required_confirmation": (["operator 1C da obyekt tarkibini ochib ko'rsin"]
                                  if confirmation is None else list(confirmation)),
        "recommended_next_probe": list(probes),
        "status": status,
    }


def gipotezalar(*rows):
    """Xom gipotezalarni `validate_analysis` dan o'tkazadi — `apply_confirmations` AYNAN
    shunday obyektlarni kutadi (tekshirilmagan lug'at holat o'zgartira olmaydi)."""
    return validate_analysis(list(rows), graph=GRAF)


def xom_tasdiq(*, concept: str = "product", obj: str = OBYEKT, field=None,
               decision: str = C.DECISION_CONFIRM, operator: str = OPERATOR,
               decided_at: str = DECIDED_AT, note=None) -> dict:
    return {"target_concept": concept, "candidate_object": obj, "candidate_field": field,
            "decision": decision, "operator": operator, "decided_at": decided_at, "note": note}


def hujjat(*rows, notes=()) -> dict:
    return {"confirmations_version": C.CONFIRMATIONS_VERSION,
            "confirmations": list(rows), "notes": list(notes)}


#: ⚠️ Versiya matnida `UNVERIFIED` ATAYLAB ISHLATILMAYDI, garchi yig'uvchining haqiqiy
#: versiyasi shunday bo'lsa ham: u `VERIFIED` ni SUBSTRING sifatida o'z ichiga oladi va
#: «artefaktda `VERIFIED` so'zi umuman yo'q» degan statik tekshiruvni ma'nosiz qilardi.
TAHLILCHI_VERSIYASI = "0.1.0-sinovda"


def ko_rik(hyps, *, name: str = "HeuristicAnalyzer",
           version: str = TAHLILCHI_VERSIYASI, coverage=None, analyzer_notes=()) -> dict:
    return V.build_review(hyps, graph=GRAF, analyzer_name=name, analyzer_version=version,
                          coverage=coverage, analyzer_notes=analyzer_notes)


def qolda_tasdiq(**kw) -> C.Confirmation:
    """QO'LDA qurilgan `Confirmation` — ya'ni hujjat validatoridan O'TMAGAN yo'l.

    ⚠️ `apply_confirmations` tayyor `Confirmation` ro'yxatini ham qabul qiladi, va AI chiqishini
       o'qiyotgan kod ayni shunday obyektni yasab bera olardi. Shu bois bu yo'lning darvozasi
       xom lug'at yo'lining darvozasi bilan AYNAN bir xil bo'lishi kerak."""
    base = dict(target_concept="product", candidate_object=OBYEKT, candidate_field=None,
                decision=C.DECISION_CONFIRM, operator=OPERATOR, decided_at=DECIDED_AT,
                note=None)
    base.update(kw)
    return C.Confirmation(**base)


#: ⚠️ Parol ATAYLAB alohida doimiy: testlar uni BAYTLAR ichida izlaydi. Nuqtali vergul yo'q,
#: chunki uni xom kod darvozasi birinchi bo'lib ushlab qolardi va sir skaneri sinalmagan
#: bo'lib qolardi — bu yerda AYNAN redaksiya darvozasi sinaladi.
PAROL = "P@ssw0rd123"
SIRLI_IZOH = f"baza egasi aytdi, parol: {PAROL} — shuni ko'rdim"


# ══════════════════════════════════════════════════════════════════════════════════════════
# validate_confirmations — HUJJAT SHARTNOMASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_togri_hujjat_oqiladi():
    rows = C.validate_confirmations(hujjat(xom_tasdiq()), graph=GRAF)
    assert len(rows) == 1
    assert rows[0].decision == C.DECISION_CONFIRM
    assert rows[0].key == ("product", OBYEKT)
    assert rows[0].who_when == f"operator {OPERATOR} · {DECIDED_AT}"


def test_notanish_qaror_rad_etiladi():
    """⚠️ Qaror ro'yxati KOD o'zgarishi bilan kengayadi, hujjat bilan emas."""
    with pytest.raises(C.ConfirmationError, match="decision noma'lum"):
        C.validate_confirmations(hujjat(xom_tasdiq(decision="APPROVE")), graph=GRAF)


@pytest.mark.parametrize("operator", ["", "   ", None, 41])
def test_anonim_tasdiq_rad_etiladi(operator):
    """⚠️ ANONIM TASDIQ YO'Q: kim aytganini bilmasdan tasdiqni qaytarib tekshirib bo'lmaydi,
    ya'ni u tasdiq emas. Bo'sh `operator` — aynan shu yo'l bilan AI o'zini operator qilib
    ko'rsatishga urinadigan joy."""
    with pytest.raises(C.ConfirmationError, match="operator"):
        C.validate_confirmations(hujjat(xom_tasdiq(operator=operator)), graph=GRAF)


@pytest.mark.parametrize("decided_at", ["", "   ", None])
def test_bosh_decided_at_rad_etiladi(decided_at):
    with pytest.raises(C.ConfirmationError, match="decided_at"):
        C.validate_confirmations(hujjat(xom_tasdiq(decided_at=decided_at)), graph=GRAF)


@pytest.mark.parametrize("decided_at", ["kecha", "2026-09-30", "2026-09-30T11:20:00",
                                        "1999-09-30T11:20:00+05:00"])
def test_ishonarsiz_vaqt_rad_etiladi(decided_at):
    """⚠️ Vaqt zonasi bilan ISO 8601 SHART: «kecha» deb yozilgan tasdiqni auditda
    joylashtirib bo'lmaydi. Vaqt bu yerda O'YLAB CHIQARILMAYDI — faqat kelgani tekshiriladi."""
    with pytest.raises(C.ConfirmationError, match="decided_at"):
        C.validate_confirmations(hujjat(xom_tasdiq(decided_at=decided_at)), graph=GRAF)


def test_notanish_kalit_rad_etiladi():
    raw = xom_tasdiq()
    raw["confidence_score"] = 0.99
    with pytest.raises(C.ConfirmationError, match="noma'lum kalit"):
        C.validate_confirmations(hujjat(raw), graph=GRAF)


def test_tushib_qolgan_kalit_rad_etiladi():
    raw = xom_tasdiq()
    del raw["note"]
    with pytest.raises(C.ConfirmationError, match="tushib qolgan"):
        C.validate_confirmations(hujjat(raw), graph=GRAF)


def test_hujjatning_notanish_kaliti_rad_etiladi():
    d = hujjat(xom_tasdiq())
    d["approved_by_ai"] = True
    with pytest.raises(C.ConfirmationError, match="noma'lum kalit"):
        C.validate_confirmations(d, graph=GRAF)


def test_notanish_konsept_rad_etiladi():
    with pytest.raises(C.ConfirmationError, match="target_concept noma'lum"):
        C.validate_confirmations(hujjat(xom_tasdiq(concept="tovar_nomi")), graph=GRAF)


def test_grafda_yoq_obyekt_rad_etiladi():
    """⚠️ Mavjud bo'lmagan obyektni tasdiqlash — hech narsani tasdiqlamaslik."""
    with pytest.raises(C.ConfirmationError, match="grafda yo'q"):
        C.validate_confirmations(hujjat(xom_tasdiq(obj="Catalog.YOQ")), graph=GRAF)


def test_grafsiz_ham_oqiladi():
    """⚠️ Graf IXTIYORIY: arxivdan olingan tasdiq hujjati grafsiz ham o'qilishi kerak."""
    rows = C.validate_confirmations(hujjat(xom_tasdiq(obj="Catalog.YOQ")))
    assert rows[0].candidate_object == "Catalog.YOQ"


@pytest.mark.parametrize("decision", [C.DECISION_REJECT, C.DECISION_NEEDS_MORE])
def test_sababsiz_rad_yoki_sorov_rad_etiladi(decision):
    """⚠️ Sababi aytilmagan qaror — tekshirib bo'lmaydigan qaror."""
    with pytest.raises(C.ConfirmationError, match="MAJBURIY"):
        C.validate_confirmations(hujjat(xom_tasdiq(decision=decision)), graph=GRAF)


def test_bir_manzil_uchun_ikki_qaror_rad_etiladi():
    """⚠️ Fikr o'zgargan bo'lsa YANGI hujjat yoziladi — bir hujjat ichida ikki qaror yo'q."""
    d = hujjat(xom_tasdiq(),
               xom_tasdiq(decision=C.DECISION_REJECT, note="ikkinchi fikr"))
    with pytest.raises(C.ConfirmationError, match="bir nechta qaror"):
        C.validate_confirmations(d, graph=GRAF)


def test_sir_shubhasi_hujjatni_rad_etadi():
    """⚠️ Operator izohi ERKIN MATN va u ko'rik artefaktiga ko'chadi — fail-closed."""
    d = hujjat(xom_tasdiq(decision=C.DECISION_REJECT,
                          note="batafsil: sotuvchi@example.com ga yozdim"))
    with pytest.raises(C.ConfirmationError, match="sir shubhasi"):
        C.validate_confirmations(d, graph=GRAF)


def test_xom_kod_izohda_rad_etiladi():
    d = hujjat(xom_tasdiq(decision=C.DECISION_REJECT,
                          note="ВЫБРАТЬ bilan qarab ko'rdim"))
    with pytest.raises(C.ConfirmationError, match="xom kod"):
        C.validate_confirmations(d, graph=GRAF)


def test_qaytgan_royxat_deterministik_tartibda():
    """Kirish tartibi natijaga TA'SIR QILMAYDI (`sort_key`)."""
    a = xom_tasdiq(concept="barcode", obj=OBYEKT_2, field=MAYDON_2,
                   decision=C.DECISION_REJECT, note="resurs boshqa narsa uchun")
    b = xom_tasdiq()
    birinchi = [c.sort_key for c in C.validate_confirmations(hujjat(a, b), graph=GRAF)]
    ikkinchi = [c.sort_key for c in C.validate_confirmations(hujjat(b, a), graph=GRAF)]
    assert birinchi == ikkinchi == sorted(birinchi)


# ══════════════════════════════════════════════════════════════════════════════════════════
# apply_confirmations — QAROR -> HOLAT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_confirm_human_confirmed_beradi():
    """CONFIRM -> `HUMAN_CONFIRMED` va `human_confirmed` dalili QO'SHILADI (kim + qachon)."""
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza()), hujjat(xom_tasdiq()))
    assert h.status == STATUS_HUMAN_CONFIRMED
    odam = [e for e in h.evidence if e.kind == C.HUMAN_EVIDENCE_KIND]
    assert len(odam) == 1
    assert odam[0].weight == "strong"
    assert OPERATOR in odam[0].detail and DECIDED_AT in odam[0].detail
    # ⚠️ Eski kuchsiz dalil O'CHIRILMAYDI: tasdiq dalil almashtirmaydi, QO'SHADI.
    assert any(e.kind == "name_match" for e in h.evidence)


def test_confirm_ballni_ozgartirmaydi():
    """⚠️ `confidence_score` O'ZGARMAYDI. Odam tasdig'i modelning ballini oshirmaydi: ball —
    modelning O'Z bahosi, tasdiq esa BOSHQA TURDAGI bilim (ekranda ko'rilgan narsa)."""
    [avval] = gipotezalar(xom_gipoteza(score=0.317))
    [keyin] = C.apply_confirmations([avval], hujjat(xom_tasdiq()))
    assert keyin.confidence_score == avval.confidence_score == 0.317
    assert keyin.confidence_score != 1.0


def test_confirm_qarshi_dalilni_ochirmaydi():
    """⚠️ Model rad etgan nomzodni operator tasdiqlagan bo'lsa, KELISHMOVCHILIK hujjatda
    ko'rinib turishi kerak — u keyingi ko'rik uchun signal."""
    qarshi = [dalil("structural_link", "birorta registr bu obyektga havola qilmaydi")]
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza(counter=qarshi)),
                                hujjat(xom_tasdiq()))
    assert h.status == STATUS_HUMAN_CONFIRMED
    assert any("havola qilmaydi" in e.detail for e in h.counter_evidence)


def test_reject_sababni_qarshi_dalilga_yozadi():
    d = hujjat(xom_tasdiq(decision=C.DECISION_REJECT,
                          note="ekranda ko'rdim: bu ro'yxat sotiladigan tovar emas"))
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza()), d)
    assert h.status == STATUS_REJECTED
    odam = [e for e in h.counter_evidence if e.kind == C.HUMAN_EVIDENCE_KIND]
    assert len(odam) == 1
    assert "sotiladigan tovar emas" in odam[0].detail
    assert OPERATOR in odam[0].detail and DECIDED_AT in odam[0].detail


def test_needs_more_evidence_ambiguous_qoldiradi():
    """NEEDS_MORE_EVIDENCE -> nomzod TIRIK qoladi, lekin ikkilanish holatida."""
    d = hujjat(xom_tasdiq(decision=C.DECISION_NEEDS_MORE,
                          note="ikkinchi ombor bo'yicha qoldiqni ham ko'rish kerak"))
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza()), d)
    assert h.status == STATUS_AMBIGUOUS
    # ⚠️ Ikkisi ham to'ldiriladi: `ai` bo'yicha AMBIGUOUS gipotezada ikkilanish SABABI ham,
    #    odam NIMANI ko'rishi ham bo'sh bo'lmaydi.
    assert any("qo'shimcha dalil so'radi" in s for s in h.required_confirmation)
    assert any("hozircha tasdiqlamadi" in s for s in h.ambiguity)
    assert any(OPERATOR in s for s in h.ambiguity)


def test_needs_more_evidence_dalilsiz_gipotezada_rad_etiladi():
    """⚠️ REJECTED gipotezada `evidence` BO'SH bo'lishi mumkin (faqat qarshi dalil bor). Uni
    AMBIGUOUS ga ko'chirish `ai` invariantini buzardi (AMBIGUOUS dalilsiz bo'lmaydi), ya'ni
    shu funksiya o'zining validatoridan O'TMAYDIGAN gipoteza yasagan bo'lardi. Fail-closed:
    jimgina buzuq holat yasashdan ko'ra RAD etib, sababini aytish kerak."""
    rad = gipotezalar(xom_gipoteza(status=STATUS_REJECTED, evidence=[],
                                   counter=[dalil("structural_link", "havola yo'q")],
                                   confirmation=[]))
    d = hujjat(xom_tasdiq(decision=C.DECISION_NEEDS_MORE, note="yana bir qarab chiqing"))
    with pytest.raises(C.ConfirmationError, match="dalil"):
        C.apply_confirmations(rad, d)


def test_tasdiqlanmagan_gipoteza_ozgarmaydi():
    """⚠️ Tasdiqlanmagan gipoteza BIR BAYT ham o'zgarmaydi."""
    hyps = gipotezalar(xom_gipoteza(),
                       xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    natija = C.apply_confirmations(hyps, hujjat(xom_tasdiq()))
    tegilmagan = [h for h in natija if h.target_concept == "barcode"]
    assert tegilmagan == [h for h in hyps if h.target_concept == "barcode"]


def test_kirish_ozgartirilmaydi():
    hyps = gipotezalar(xom_gipoteza())
    nusxa = list(hyps)
    C.apply_confirmations(hyps, hujjat(xom_tasdiq()))
    assert hyps == nusxa
    assert hyps[0].status == STATUS_CANDIDATE


def test_gipotezalar_ichida_yoq_nomzod_jimgina_tashlanmaydi():
    """⚠️ ENG XAVFLI NOSOZLIK SHAKLI: operator «tasdiqladim» deb o'ylaydi, hujjatda esa hech
    narsa o'zgarmagan. Shu bois mos nomzod topilmasa — ISTISNO, jim o'tish emas."""
    hyps = gipotezalar(xom_gipoteza())
    d = hujjat(xom_tasdiq(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    with pytest.raises(C.ConfirmationError, match="gipotezalar ichida YO'Q"):
        C.apply_confirmations(hyps, d)


def test_manzil_ozgarsa_tasdiq_jimgina_yoqolmaydi():
    """Tahlil yangilangan va maydon manzili o'zgargan holat — eng ko'p uchraydigan sababi."""
    hyps = gipotezalar(xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    d = hujjat(xom_tasdiq(concept="barcode", obj=OBYEKT_2, field="D1"))
    with pytest.raises(C.ConfirmationError, match="gipotezalar ichida YO'Q"):
        C.apply_confirmations(hyps, d)


def test_tekshirilmagan_lugat_holat_ozgartirmaydi():
    """⚠️ `apply_confirmations` XOM lug'at qabul qilmaydi: tekshirilmagan ma'lumot bu yo'l
    bilan `HUMAN_CONFIRMED` yasay olmasligi kerak."""
    with pytest.raises(C.ConfirmationError, match="`Hypothesis` bo'lishi kerak"):
        C.apply_confirmations([xom_gipoteza()], hujjat(xom_tasdiq()))


def test_takroriy_manzilli_gipotezalar_rad_etiladi():
    [h] = gipotezalar(xom_gipoteza())
    with pytest.raises(C.ConfirmationError, match="takroriy manzil"):
        C.apply_confirmations([h, h], hujjat(xom_tasdiq()))


def test_natijada_verified_yoq():
    """⚠️ STATIK TEKSHIRUV: uchta qarorning HAMMASINI qo'llab, natijaning BAYTLARIDA
    `VERIFIED` so'zi umuman uchramasligini talab qilamiz. `HUMAN_CONFIRMED` ≠ `VERIFIED`:
    birinchisi shu oqimning eng yuqori holati, ikkinchisi MIGRATOR darvozasi."""
    hyps = gipotezalar(
        xom_gipoteza(),
        xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2),
        xom_gipoteza(concept="warehouse", obj="Catalog.X23"),
    )
    d = hujjat(
        xom_tasdiq(),
        xom_tasdiq(concept="barcode", obj=OBYEKT_2, field=MAYDON_2,
                   decision=C.DECISION_REJECT, note="bu resurs kod emas"),
        xom_tasdiq(concept="warehouse", obj="Catalog.X23",
                   decision=C.DECISION_NEEDS_MORE, note="joylar ro'yxatini ko'rish kerak"),
    )
    natija = C.apply_confirmations(hyps, d)
    holatlar = {h.target_concept: h.status for h in natija}
    assert holatlar == {"product": STATUS_HUMAN_CONFIRMED,
                        "barcode": STATUS_REJECTED,
                        "warehouse": STATUS_AMBIGUOUS}
    matn = dumps(hypotheses_to_json(natija))
    assert FORBIDDEN_STATUS not in matn


def test_natija_ai_validatoridan_otadi():
    """Yasalgan gipotezalar O'Z shartnomasidan qayta o'tadi (tasdiq rejimida)."""
    natija = C.apply_confirmations(gipotezalar(xom_gipoteza()), hujjat(xom_tasdiq()))
    xom = [hypothesis_to_json(h) for h in natija]
    qayta = validate_analysis(xom, graph=GRAF, allow_human_confirmed=True)
    assert [h.status for h in qayta] == [STATUS_HUMAN_CONFIRMED]
    # ⚠️ Odatiy (AI) rejimda AYNAN shu hujjat RAD etiladi: odam tasdig'i model kanalidan
    #    o'tmaydi, va tasdiqlangan natijani «model chiqishi» deb qayta kiritib bo'lmaydi.
    with pytest.raises(AnalysisError, match=STATUS_HUMAN_CONFIRMED):
        validate_analysis(xom, graph=GRAF)


def test_tekshirilgan_tasdiq_royxati_ham_qabul_qilinadi():
    rows = C.validate_confirmations(hujjat(xom_tasdiq()), graph=GRAF)
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza()), rows)
    assert h.status == STATUS_HUMAN_CONFIRMED


def test_apply_deterministik():
    hyps = gipotezalar(xom_gipoteza(),
                       xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    d = hujjat(xom_tasdiq())
    birinchi = dumps(hypotheses_to_json(C.apply_confirmations(hyps, d)))
    ikkinchi = dumps(hypotheses_to_json(C.apply_confirmations(list(reversed(hyps)), d)))
    assert birinchi == ikkinchi


# ══════════════════════════════════════════════════════════════════════════════════════════
# QO'LDA QURILGAN `Confirmation` — DARVOZA AYLANIB O'TILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Uchta hujum + noma'lum qaror. Har biri: qo'lda qurilgan tasdiqning maydonlari va natijada
#: HECH QACHON chiqmasligi kerak bo'lgan matn.
#: ⚠️ AYNI shu uchovi XOM LUG'AT bilan berilganda yuqoridagi testlarda RAD etiladi — ya'ni
#: darvoza mavjud, va gap uni aylanib o'tadigan YO'L haqida.
HUJUMLAR = {
    "anonim": (dict(operator="", decided_at=""), STATUS_HUMAN_CONFIRMED),
    "soxta_vaqt": (dict(decided_at="kecha"), "kecha"),
    "sirli_izoh": (dict(decision=C.DECISION_REJECT, note=SIRLI_IZOH), PAROL),
    "notanish_qaror": (dict(decision="APPROVE"), "qo'shimcha dalil so'radi"),
}


@pytest.mark.parametrize("nom", sorted(HUJUMLAR))
def test_qolda_qurilgan_tasdiq_ayni_darvozadan_otadi(nom):
    """⚠️ NUQSON (P0): `apply_confirmations` tayyor `Confirmation` ro'yxatini ko'rganda
    `validate_confirmations` ni (va uning ichidagi `parse_ts` + `redact.scan` ni) UMUMAN
    chaqirmasdi, `Confirmation` da esa `__post_init__` yo'q edi — ya'ni obyektning O'ZIDA ham
    darvoza yo'q. Natijada ANONIM tasdiq (`operator=''`) `HUMAN_CONFIRMED` bo'lib chiqardi
    (AI o'zini operator qilib KO'RSATA OLARDI), «kecha» deb yozilgan vaqt qabul qilinardi,
    izohdagi parol esa dalil `detail` iga ko'chib BAYTLARGA yozilardi.

    ⚠️ Isbot BAYTLAR darajasida: nuqson bo'lgan holda `pytest.raises` ichidagi kod oxirigacha
       ishlaydi va taqiqlangan matn natijaning baytlarida ko'rinadi (test AssertionError bilan
       yiqiladi). Tuzatilgan holda esa birinchi qatorning O'ZI RAD etiladi."""
    maydonlar, taqiqlangan = HUJUMLAR[nom]
    hyps = gipotezalar(xom_gipoteza())
    with pytest.raises(C.ConfirmationError):
        natija = C.apply_confirmations(hyps, [qolda_tasdiq(**maydonlar)])
        assert taqiqlangan not in dumps(hypotheses_to_json(natija)), (
            f"{nom}: qo'lda qurilgan tasdiq darvozani aylanib o'tdi — natijada "
            f"{taqiqlangan!r} bor")


@pytest.mark.parametrize("nom", sorted(HUJUMLAR))
def test_confirmation_obyektining_ozida_darvoza_bor(nom):
    """⚠️ Ikkinchi qatlam: darvoza OBYEKTNING O'ZIDA. `Confirmation` oddiy frozen dataclass
    bo'lgani uchun har qanday qiymat bilan qurilardi, ya'ni «tekshirilgan yozuv» degan tur
    kafolati YO'Q edi. Obyekt MAVJUD bo'lsa — u darvozadan o'tgan bo'lishi kerak."""
    maydonlar, _ = HUJUMLAR[nom]
    with pytest.raises(C.ConfirmationError):
        qolda_tasdiq(**maydonlar)


def test_qolda_qurilgan_togri_tasdiq_ishlaydi():
    """Darvoza qo'yilgani bilan hujjatning QONUNIY shakli yo'qolmaydi (regressiya)."""
    [h] = C.apply_confirmations(gipotezalar(xom_gipoteza()), [qolda_tasdiq()])
    assert h.status == STATUS_HUMAN_CONFIRMED
    odam = [e for e in h.evidence if e.kind == C.HUMAN_EVIDENCE_KIND]
    assert len(odam) == 1 and OPERATOR in odam[0].detail and DECIDED_AT in odam[0].detail


def test_qolda_qurilgan_takroriy_qaror_rad_etiladi():
    """⚠️ Obyekt yo'li HUJJAT darajasidagi qoidalarni ham aylanib o'tardi: bir manzil uchun
    ikki qaror jimgina bir-birini almashtirardi va qaysi biri «oxirgi» ekani ko'rinmasdi."""
    ikkita = [qolda_tasdiq(), qolda_tasdiq(decision=C.DECISION_REJECT, note="ikkinchi fikr")]
    with pytest.raises(C.ConfirmationError, match="bir nechta qaror"):
        C.apply_confirmations(gipotezalar(xom_gipoteza()), ikkita)


def test_aralash_royxat_rad_etiladi():
    """Yarmi obyekt, yarmi xom lug'at — qaysi yozuv qaysi yo'ldan kelgani ko'rinmaydi, RAD."""
    hyps = gipotezalar(xom_gipoteza(),
                       xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    aralash = [qolda_tasdiq(), xom_tasdiq(concept="barcode", obj=OBYEKT_2, field=MAYDON_2)]
    with pytest.raises(C.ConfirmationError, match="ARALASH"):
        C.apply_confirmations(hyps, aralash)


def buzuq_tasdiq(**kw) -> C.Confirmation:
    """Darvozadan O'TGAN, keyin qiymati O'ZGARTIRILGAN tasdiq (`NEEDS_MORE_EVIDENCE` asosida).

    ⚠️ `object.__setattr__` ATAYLAB: bu yerda `_apply_one` ning O'Z darvozasi sinaladi.
       Tekshiruvni faqat kirishdagi validatorga tashlab qo'yish qatlamni bittaga tushirardi,
       holbuki yozuvni boshqa joyda yasagan kod (masalan yangi qaror turi qo'shilganda) to'g'ri
       shu funksiyaga kelib tushadi."""
    [c] = C.validate_confirmations(
        hujjat(xom_tasdiq(decision=C.DECISION_NEEDS_MORE, note="omborni ham ko'rish kerak")),
        graph=GRAF)
    for k, v in kw.items():
        object.__setattr__(c, k, v)
    return c


@pytest.mark.parametrize("qaror", ["APPROVE", "confirm", "MAYBE", "", None])
def test_apply_one_notanish_qarorni_yoqdan_yasamaydi(qaror):
    """⚠️ NUQSON (P2) FAIL-OPEN: `_apply_one` da CONFIRM va REJECT dan boshqa HAR QANDAY
    qiymat jimgina `NEEDS_MORE_EVIDENCE` shoxiga tushardi — birorta `else` yo'q edi. Natijada
    hujjatda «operator qo'shimcha dalil so'radi» degan yozuv paydo bo'lardi, operator esa
    bunday DEMAGAN: fail-open yo'qdan MA'NO yasaydi va u haqiqiy qarordan farq qilmaydi."""
    [h] = gipotezalar(xom_gipoteza())
    with pytest.raises(C.ConfirmationError, match="noma'lum"):
        yasalgan = C._apply_one(h, buzuq_tasdiq(decision=qaror))
        assert "qo'shimcha dalil so'radi" not in " ".join(yasalgan.required_confirmation), (
            f"{qaror!r}: operator AYTMAGAN ma'no yo'qdan yasaldi")


def test_apply_one_izohsiz_sorovga_none_yozmaydi():
    """⚠️ Mayda, lekin OPERATORGA KO'RINADIGAN nuqson: `note=None` bo'lsa so'rov matniga
    Python ning `None` literali yozilardi, ya'ni «nimasi yetmaydi» degan savolga hujjat
    ichida soxta javob paydo bo'lardi."""
    [h] = gipotezalar(xom_gipoteza())
    with pytest.raises(C.ConfirmationError, match="izoh MAJBURIY"):
        yasalgan = C._apply_one(h, buzuq_tasdiq(note=None))
        assert "None" not in " ".join(yasalgan.required_confirmation), (
            "operatorga ko'rinadigan matnga Python `None` literali yozildi")


# ══════════════════════════════════════════════════════════════════════════════════════════
# review — KO'RIK ARTEFAKTI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_korik_artefakti_deterministik():
    """⚠️ Bir xil kirish — AYNAN bir xil bayt, ya'ni ikki ko'rikni diff bilan solishtirib
    ko'rish mumkin. Gipotezalarning KIRISH TARTIBI natijaga ta'sir qilmaydi."""
    hyps = gipotezalar(xom_gipoteza(),
                       xom_gipoteza(concept="barcode", obj=OBYEKT_2, field=MAYDON_2))
    a = V.dumps_review(ko_rik(hyps))
    b = V.dumps_review(ko_rik(list(reversed(hyps))))
    assert a == b
    # Ikki marta yozish ham bayt-bayt bir xil.
    assert V.dumps_review(ko_rik(hyps)) == a


def test_korikda_qaralmagan_konseptlar_ochiq_turadi():
    """⚠️ «Qaralmadi» «yo'q» degani EMAS: qaralmagan konsept artefaktda OCHIQ turadi."""
    doc = ko_rik(gipotezalar(xom_gipoteza()))
    noma_lum = doc["unknown_concepts"]
    assert noma_lum, "qaralmagan konseptlar ro'yxati bo'sh bo'lmasligi kerak"
    assert "product" not in noma_lum
    assert "barcode" in noma_lum and "scale_plu" in noma_lum
    # ⚠️ Sanoq MATN: `0000123` soni `123` bo'lib qolardi (1-invariant).
    assert doc["counts"]["unknown_concepts"] == str(len(noma_lum))
    assert isinstance(doc["counts"]["candidates"], str)


def test_korikda_tasdiqlangan_holat_korinadi_verified_esa_yoq():
    natija = C.apply_confirmations(gipotezalar(xom_gipoteza()), hujjat(xom_tasdiq()))
    doc = ko_rik(natija)
    assert doc["counts"]["by_status"] == {STATUS_HUMAN_CONFIRMED: "1"}
    assert FORBIDDEN_STATUS not in V.dumps_review(doc).decode("utf-8")


def test_korik_qurishda_sir_shubhasi_istisno_beradi():
    """⚠️ Fail-closed: artefakt qo'ldan-qo'lga o'tadi, ya'ni u sirni olib chiqadigan eng
    qulay yo'l. Shubha bo'lsa HECH NARSA yozilmaydi."""
    with pytest.raises(V.ReviewError, match="sir shubhasi"):
        ko_rik(gipotezalar(xom_gipoteza()), name="tahlilchi qo'li@example.com")


def test_yozishdan_oldin_sir_qayta_tekshiriladi():
    """⚠️ Skaner YOZUVCHINING O'ZIGA yopishtirilgan: lug'at ikki chaqiruv orasida
    o'zgartirilgan bo'lishi mumkin va MUHIMI — yozishdan OLDINGI holat."""
    doc = ko_rik(gipotezalar(xom_gipoteza()))
    doc["analyzer"]["version"] = "0.1.0 (savollar: usta@example.com)"
    with pytest.raises(V.ReviewError, match="sir shubhasi"):
        V.dumps_review(doc)


def test_qamrov_olchanmagani_ochiq_yoziladi():
    """⚠️ `None` va `{}` FARQ QILADI: birinchisi «o'lchanmadi», ikkinchisi «o'lchandi va
    bo'sh». Ikkisini qo'shib yuborish «hammasi ko'rildi» degan yolg'on xotirjamlik berardi."""
    hyps = gipotezalar(xom_gipoteza())
    assert ko_rik(hyps)["coverage"] is None
    assert ko_rik(hyps, coverage={})["coverage"] == {}
    assert ko_rik(hyps, coverage={"objects": "0004"})["coverage"] == {"objects": "0004"}
    with pytest.raises(V.ReviewError, match="sanoq MATNI"):
        ko_rik(hyps, coverage={"objects": 4})


# ── Operator varaqasi ──────────────────────────────────────────────────────────────────────
def test_varaqda_uchta_qaror_ham_korinadi():
    """⚠️ Uchta qaror ATAYLAB: «tasdiqlayman» va «rad etaman» yonida «hali yetarli dalil
    yo'q» ham QAROR bo'lishi kerak, aks holda ikkilanish hujjatdan yo'qolardi."""
    matn = V.build_operator_worksheet(ko_rik(gipotezalar(xom_gipoteza())))
    for qaror in C.DECISIONS:
        assert qaror in matn, f"varaqda {qaror!r} qarori ko'rsatilmagan"
    assert len(C.DECISIONS) == 3


def test_varaqda_ogohlantirishlar_saqlanadi():
    """⚠️ Artefakt o'z ogohlantirishini O'ZI bilan olib yuradi — varaqda ham, JSON da ham."""
    doc = ko_rik(gipotezalar(xom_gipoteza()))
    matn = V.build_operator_worksheet(doc)
    for w in V.WARNINGS:
        assert w in matn, f"varaqda ogohlantirish yo'q: {w!r}"
        assert w in doc["warnings"]
    # Qaror ALOHIDA hujjatga tushadi — varaqqa emas.
    assert C.CONFIRMATIONS_VERSION in matn
    assert "SHU VARAQQA EMAS" in matn
    # ⚠️ Varaq `VERIFIED` ni BERMAYDI, faqat u haqida ogohlantiradi.
    assert f"{FORBIDDEN_STATUS} bu varaqda BERILMAYDI" in matn


def test_varaqda_qaralmagan_konseptlar_va_manzil_korinadi():
    doc = ko_rik(gipotezalar(xom_gipoteza(obj=OBYEKT, field=MAYDON)))
    matn = V.build_operator_worksheet(doc)
    assert f"## product <- {OBYEKT}.{MAYDON}" in matn
    assert f"concept=product · object={OBYEKT} · field={MAYDON}" in matn
    assert "## Qaralmagan konseptlar (UNKNOWN)" in matn
    assert "«Qaralmadi» «yo'q» degani EMAS" in matn
    assert "- Qamrov: O'LCHANMADI" in matn


def test_nomzod_yoq_varaqda_ham_ochiq_aytiladi():
    """⚠️ Bo'sh tahlil «mos narsa yo'q» degani EMAS va varaq buni ochiq aytishi kerak."""
    doc = ko_rik([])
    matn = V.build_operator_worksheet(doc)
    assert "## Nomzod yo'q" in matn
    assert "«mos narsa yo'q» degani EMAS" in matn
    assert doc["counts"]["candidates"] == "0"
    assert len(doc["unknown_concepts"]) == len(V.unknown_concepts([]))


# ── Tahlilchi izohlari: JIM QISISH YO'Q ────────────────────────────────────────────────────
#: Analitik AYNAN shunday izoh yozadi (`HeuristicAnalyzer.analyze`): darcha (`keep_window`) yoki
#: chegara (`max_per_concept`) nomzodni kesib tashlagan bo'lsa, buning YAGONA yozuvi shu qator.
QISILGAN_IZOH = ("Nomzodlar soni chegaraga qisilgan konseptlar: product. "
                 "Qisilgani «yo'q» degani emas.")


def test_analitik_izohi_artefaktga_yetadi():
    """⚠️ NUQSON: `REVIEW_KEYS` da izohlar kaliti YO'Q edi va `build_review` ularni umuman
    qabul qilmasdi — ya'ni chegara kesib tashlagan ishonchli nomzod haqidagi YAGONA yozuv
    artefaktga yetib bormasdi. Operator kesilgan nomzodni ko'rmaydi va umuman biror narsa
    kesilganini BILMAYDI: «jim qisish yo'q» qoidasi jimgina buziladi."""
    doc = ko_rik(gipotezalar(xom_gipoteza()), analyzer_notes=[QISILGAN_IZOH])
    assert doc["analyzer_notes"] == [QISILGAN_IZOH]
    # ⚠️ Baytlarda ham turadi: JSON ni o'qigan dastur (yoki keyingi model) varaqni ko'rmaydi.
    assert QISILGAN_IZOH in V.dumps_review(doc).decode("utf-8")
    # ⚠️ Va OPERATORGA KO'RINADIGAN joyda — nomzodlar ro'yxatidan OLDIN, chunki bu ogohlantirish
    #    ro'yxatning TO'LIQ EMASligi haqida.
    matn = V.build_operator_worksheet(doc)
    assert QISILGAN_IZOH in matn
    assert matn.index(QISILGAN_IZOH) < matn.index(f"## product <- {OBYEKT}"), (
        "qisilish ogohlantirishi nomzodlar ro'yxatidan KEYIN turibdi — operator ro'yxatni "
        "to'liq deb o'qib bo'lgan bo'lardi")


def test_izoh_berilmagani_ochiq_aytiladi():
    """⚠️ Bo'sh ro'yxat «hech narsa qisilmadi» degani EMAS — u «izoh berilmadi». Hozir
    `validate_analysis` izohlarni CHIQARMAYDI, ya'ni bu holat ODATIY holat va varaq buni ochiq
    aytishi kerak."""
    doc = ko_rik(gipotezalar(xom_gipoteza()))
    assert doc["analyzer_notes"] == []
    matn = V.build_operator_worksheet(doc)
    assert "IZOH BERILMAGAN" in matn
    assert "to'liqligi ISBOTLANMAGAN" in matn


def test_izohlar_tartibi_saqlanadi_va_deterministik():
    """⚠️ Izohlar analitik yozgan NAVBATDA turadi (qisish haqidagi ogohlantirish oxirida
    keladi) — tartiblash uni boshqa joyga surib qo'yardi."""
    izohlar = ["zzz oxirgi izoh", "aaa birinchi izoh"]
    hyps = gipotezalar(xom_gipoteza())
    doc = ko_rik(hyps, analyzer_notes=izohlar)
    assert doc["analyzer_notes"] == izohlar
    assert V.dumps_review(doc) == V.dumps_review(ko_rik(hyps, analyzer_notes=izohlar))


def test_izohdagi_sir_artefaktni_rad_etadi():
    """⚠️ Izoh ham `redact.scan` dan o'tadi: u artefaktga ko'chadigan ERKIN MATN (fail-closed)."""
    with pytest.raises(V.ReviewError, match="sir shubhasi"):
        ko_rik(gipotezalar(xom_gipoteza()), analyzer_notes=[f"parol: {PAROL}"])


@pytest.mark.parametrize("izohlar", [["  "], [None], "matn emas", [41]])
def test_buzuq_izoh_royxati_rad_etiladi(izohlar):
    with pytest.raises(V.ReviewError, match="analyzer_notes"):
        ko_rik(gipotezalar(xom_gipoteza()), analyzer_notes=izohlar)


def test_izohlar_kaliti_artefaktdan_yoqolsa_rad_etiladi():
    """⚠️ Kalitning O'ZI shartnomada: u yo'qolsa, «izoh berilmagan» va «izoh bor edi, yo'qoldi»
    farqi bilinmasdi."""
    doc = ko_rik(gipotezalar(xom_gipoteza()), analyzer_notes=[QISILGAN_IZOH])
    del doc["analyzer_notes"]
    with pytest.raises(V.ReviewError, match="tushib qolgan"):
        V.dumps_review(doc)
