# -*- coding: utf-8 -*-
"""BIR BOSISHLI OQIM — operator oqimining UCHIGA-UCH sintetik isboti.

⚠️⚠️ BU REAL 1C ISBOTI EMAS. Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI,
     `.epf` BAJARILMAYDI, COM ishlatilmaydi, haqiqiy reestr O'QILMAYDI va tarmoq YO'Q. Bu
     mashinada 1C:Enterprise umuman o'rnatilmagan. Kirish — SINTETIK reestr, SINTETIK
     `ibases.v8i` va SINTETIK Phase 4 paketlari; yig'uvchining O'RNIDA esa `sleeper` ichida
     ishlaydigan fikstura turadi (ya'ni «1C da yig'uvchi bajarildi» holati TAQLID qilinadi).
     Shu bois bu fayl javob beradigan savol: «yig'uvchi papkaga SHUNDAY yozsa, agent TO'G'RI
     qabul/rad qiladimi, operator NIMA ko'radi va qo'lida YAROQLI paket qoladimi?».
     Avtomatik ishga tushirish yo'li `UNVERIFIED_ON_REAL_1C` bo'lib QOLADI.

NEGA BU FAYL MAVJUD TESTLARNI TAKRORLAMAYDI:
    `test_agent_e2e_watch_folder.py` — operator papkani O'ZI ko'rsatgan oqim
    (`--headless`); bu fayl esa BIR BOSISHLI oqimni o'lchaydi, ya'ni chiqish papkasi
    YURISHGA BOG'LANGAN (`request.json` → `response.json` → `bridge_done.json`) va
    operator hech narsani QO'LDA KO'CHIRMAYDI.

O'ZAK INVARIANTLAR:
    1. YANGI DVIGATEL YO'Q: `INGESTING`/`ANALYZING` mavjud `pipeline.run_pipeline` ga
       boradi va natija paketini mavjud `result_package` yozadi (A, E).
    2. HAR RAD ETISH O'Z KODI bilan: `STALE_OUTPUT`, `NONCE_MISMATCH`,
       `WRONG_COLLECTOR_VERSION`, `PARTIAL_PACKAGE`, `OUTPUT_PREDATES_REQUEST`,
       `TARGET_FINGERPRINT_MISMATCH`, `RESPONSE_MISSING`, `DONE_MARKER_MISSING`,
       `OPERATOR_CANCELLED`, `RUN_DIR_NOT_EMPTY`, `RUNS_ROOT_UNKNOWN`, `TARGET_AMBIGUOUS`,
       `COLLECTOR_EXECUTION_NOT_ALLOWED` (H..R).
    3. IKKI BIR VAQTDA YURISH bir-birini KO'RMAYDI (S).
    4. FAZA ORQAGA QAYTMAYDI va har fazada BO'SH BO'LMAGAN operator matni bor (T, U).
    5. CHEKSIZ KUTISH YO'Q va kutish KO'RINADI (F, V).
    6. PAROL va YO'L hech qayerga tushmaydi; jarayon O'LDIRISH va `rmtree` naqshi YO'Q
       (W, X, Y).
"""
from __future__ import annotations

import ast
import json
import os
import pathlib

import pytest

from app.services.discovery_1c import redact
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_agent import BUNDLE_SUBDIR
from app.services.discovery_agent import __main__ as cli
from app.services.discovery_agent import bridge_phase as bp
from app.services.discovery_agent import bridge_protocol as bpr
from app.services.discovery_agent import collector_bridge as cb
from app.services.discovery_agent import detector as det
from app.services.discovery_agent import launcher as ln
from app.services.discovery_agent import one_click as oc
from app.services.discovery_agent import result_package as rp
from app.services.discovery_agent import states as st
from tests import agent_bridge_mock as H
from tests import agent_scenario_mock as X
from tests import discovery_1c_runtime_mock as M

#: 1C papkasining ildizi.
_1C = pathlib.Path(__file__).resolve().parents[3] / "integrations" / "1c"

#: ICHKI yig'uvchining manbasi (`BinOSDiscovery` / `0.2.0-UNVERIFIED`). ⚠️ Uning o'zligi
#: Phase 4 shartnomasi bo'yicha `bundle/export.json`.`collector` da qoladi.
EXTRACTOR_SOURCE = _1C / "extractor" / "BinOSDiscovery.bsl"

#: KO'PRIK qatlamining manbasi va o'zligi — `response.json`.`collector` AYNAN shu.
#: ⚠️⚠️ AGENT KUTADIGAN O'ZLIK SHU FAYLLARDAN olinadi: ikki o'zlikni aralashtirish
#:      HAR BIR haqiqiy javobni `WRONG_COLLECTOR_VERSION` bilan rad etgan P0 nuqson edi.
BRIDGE_SOURCE = _1C / "collector" / "BinOSDiscoveryCollector.bsl"
BRIDGE_VERSION = _1C / "collector" / "VERSION.json"

#: Operator oqimi hujjati — mavjudligi va mazmuni tekshiriladi.
FLOW_DOC = (pathlib.Path(__file__).resolve().parents[3]
            / "integrations" / "1c" / "AGENT_ONE_CLICK_FLOW.md")

#: Bu modulning manbasi — statik taqiqlar uchun.
ONE_CLICK_SRC = pathlib.Path(oc.__file__)


# ══════════════════════════════════════════════════════════════════════════════════════════
# YORDAMCHILAR — YIG'UVCHINING O'RNIDA
# ══════════════════════════════════════════════════════════════════════════════════════════
def _yoz_json(yol, doc) -> None:
    """⚠️ UTF-8, BOM'siz: chiqish kodlashi shartnoma."""
    pathlib.Path(yol).write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                 encoding="utf-8", newline="\n")


def yurish_papkasi(runs_root, chetla=()) -> pathlib.Path:
    """Yurishning papkasi (nomi `run_id` — tasodifiy, shu bois DISKDAN topiladi)."""
    kok = pathlib.Path(runs_root)
    papkalar = [p for p in sorted(kok.iterdir()) if p.is_dir() and p.name not in set(chetla)]
    assert len(papkalar) == 1, f"aynan bitta yangi yurish papkasi kutilgan: {papkalar}"
    return papkalar[0]


def sorov_hujjati(run_dir) -> dict:
    return json.loads((pathlib.Path(run_dir) / bpr.REQUEST_FILE).read_text(encoding="utf-8"))


def javob_hujjati(req, *, status=bpr.STATUS_OK, run_id=None, nonce=None, xesh=None,
                  collector=None, vaqt=None) -> dict:
    """`binos-bridge-response-v1` — YIG'UVCHI yozadigan hujjat (fikstura)."""
    t = X.NOW_ISO if vaqt is None else vaqt
    return {
        "response_version": bpr.RESPONSE_VERSION,
        "run_id": req["run_id"] if run_id is None else run_id,
        "nonce": req["nonce"] if nonce is None else nonce,
        "collector": dict(req["expected_collector"] if collector is None else collector),
        "target_fingerprint": req["target_fingerprint"] if xesh is None else xesh,
        "status": status,
        "started_at": t,
        "finished_at": t,
        "notes": [],
    }


def belgi_hujjati(req, *, run_id=None, nonce=None, vaqt=None) -> dict:
    """`binos-bridge-done-v1` — ENG OXIRIDA yoziladigan tugallanish belgisi."""
    return {
        "done_version": bpr.DONE_VERSION,
        "run_id": req["run_id"] if run_id is None else run_id,
        "nonce": req["nonce"] if nonce is None else nonce,
        "written_at": X.NOW_ISO if vaqt is None else vaqt,
    }


def paket_yarim(papka) -> str:
    """SOG'LOM paket, LEKIN majburiy fayllardan BITTASI olib tashlangan.

    ⚠️ Fayl nomi SHARTNOMADAN (`runtime_bundle.REQUIRED_FILES`) olinadi, qo'lda yozilmaydi.
    """
    M.paket_sog_lom(papka)
    os.remove(os.path.join(papka, rb.RUN_SUMMARY_FILE))
    return papka


def yiguvchi(runs_root, *, paket=M.paket_sog_lom, status=bpr.STATUS_OK, javob=True,
             belgi=True, run_id=None, nonce=None, xesh=None, collector=None,
             belgi_vaqti=None, chetla=()):
    """YIG'UVCHINING O'RNIDA ishlaydigan `sleeper`: papkaga BIR MARTA yozadi.

    ⚠️⚠️ NEGA `sleeper` ICHIDA: agent yig'uvchining chiqishini KUTADI, demak fayllar
         kutish BOSHLANGANDAN KEYIN paydo bo'lishi kerak — aks holda test kutish yo'lini
         umuman o'lchamagan bo'lardi. `sleeper` KIRISHDAN keladi, ya'ni haqiqiy soniyalar
         kutilmaydi.
    ⚠️ YOZISH TARTIBI SHARTNOMA BO'YICHA: avval paket (ichida `manifest.json` oxirgi),
       keyin `response.json`, ENG OXIRIDA `bridge_done.json`.
    """
    holat = {"yozildi": False}

    def uxla(_soniya: float) -> None:
        if holat["yozildi"]:
            return
        holat["yozildi"] = True
        rd = yurish_papkasi(runs_root, chetla)
        req = sorov_hujjati(rd)
        if paket is not None:
            paket(str(rd / BUNDLE_SUBDIR))
        if javob:
            _yoz_json(rd / bpr.RESPONSE_FILE,
                      javob_hujjati(req, status=status, run_id=run_id, nonce=nonce,
                                    xesh=xesh, collector=collector))
        if belgi:
            _yoz_json(rd / bpr.DONE_FILE,
                      belgi_hujjati(req, run_id=run_id, nonce=nonce, vaqt=belgi_vaqti))

    return uxla


def agent(tmp_path, *, scan, sleeper=None, timeout_seconds: float = 30.0,
          poll_seconds: float = 2.0, nom: str = "natija"):
    """Sinovga tayyor `UiModel` — oyna OCHMAYDI, soatga QARAMAYDI, 1C ga ULANMAYDI.

    ⚠️ `bundle_dir` BERILMAYDI: uni `one_click` yurishning O'Z papkasiga bog'laydi.
    """
    ota = tmp_path / nom
    ota.mkdir(parents=True, exist_ok=True)
    model = X.agent(ota, scan=scan)
    model.clock = X.oshuvchi_soat(1.0)
    model.sleeper = (lambda _s: None) if sleeper is None else sleeper
    model.watch_timeout_seconds = timeout_seconds
    model.watch_poll_seconds = poll_seconds
    return model


def muhit_bitta_baza(tmp_path):
    return X.muhit_bazali(tmp_path, X.baza_oddiy(tmp_path))


def muhit_ikki_baza(tmp_path):
    """⚠️ IKKI BAZA — `locator` lari ham BOSHQA: `agent_scenario_mock.baza_oddiy` hamma
    bazaga AYNI yo'lni beradi, `detector` esa bir xil ulanish satrini BIR baza deb o'qiydi
    (ya'ni ikkita e'lon bitta nishon bo'lib qolardi va test «noaniqlik» ni umuman
    o'lchamagan bo'lardi)."""
    return X.muhit_bazali(
        tmp_path,
        X.Baza(nom="Birinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-1")),
        X.Baza(nom="Ikkinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-2")),
    )


def runs(tmp_path, nom: str = "runs") -> str:
    """Yurishlar ildizi — MANBA DARAXTIDAN TASHQARIDA (testda `tmp_path`)."""
    p = tmp_path / nom
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def bir_bosish(model, *, runs_root, select_index=None, kutish_jurnali=None):
    """`run_one_click` ni hodisa va kutish jurnali bilan yurgizadi."""
    hodisalar: list = []
    model.on_progress = None
    natija = oc.run_one_click(
        model, runs_root=runs_root, select_index=select_index,
        on_event=hodisalar.append,
        on_wait=None if kutish_jurnali is None else kutish_jurnali.append,
    )
    return natija, hodisalar


# ══════════════════════════════════════════════════════════════════════════════════════════
# A — MUVAFFAQIYATLI YURISH: MAVJUD QUVUR ISHLATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_a_muvaffaqiyatli_yurish_mavjud_quvurni_ishlatadi(tmp_path):
    """Bir bosishli yurish `COMPLETE` bo'ladi va YAROQLI natija paketi qoldiradi."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija, hodisalar = bir_bosish(model, runs_root=kok)

    assert natija.state == st.COMPLETE and natija.is_complete
    assert natija.phase == bp.COMPLETE
    assert natija.code is None
    # ⚠️ Natija papkasi DISKDAN tekshiriladi: manifest xeshlari, ildiz artefaktlari,
    #    `bundle/` ning Phase 4 tekshiruvlari — hammasi `result_package` ning darvozasi.
    rp.validate_result_package(natija.result_dir)
    # ⚠️ Phase 4 paketi natija papkasiga KO'CHDI, ya'ni `INGESTING` haqiqiy paket bo'yicha
    #    ishladi (bo'sh papka bo'yicha «muvaffaqiyat» emas).
    assert X.fayl_bor(natija.result_dir, f"{BUNDLE_SUBDIR}/{rb.MANIFEST_FILE}")
    # Fazalar TO'LIQ zanjir bo'ylab, AYNAN shu tartibda.
    assert [h.phase for h in hodisalar] == [
        bp.DETECTING_1C, bp.DISCOVERING_INFOBASES, bp.SELECT_TARGET, bp.PREPARING_COLLECTOR,
        bp.LAUNCHING_1C, bp.WAITING_FOR_COLLECTOR, bp.COLLECTOR_COMPLETE, bp.INGESTING,
        bp.ANALYZING, bp.COMPLETE,
    ]


def test_a2_yurish_papkasida_uchta_kaprik_hujjati_bor(tmp_path):
    """So'rov AGENT tomonidan, javob va belgi YIG'UVCHI tomonidan — uchovi yurish papkasida."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok)

    rd = pathlib.Path(natija.run_dir)
    for nom in (bpr.REQUEST_FILE, bpr.RESPONSE_FILE, bpr.DONE_FILE):
        assert (rd / nom).is_file(), f"{nom} yurish papkasida bo'lishi kerak"
    # ⚠️ Yurish o'zligi natijada BOR, `nonce` NING O'ZI esa YO'Q (faqat uzunligi).
    assert natija.run_id == rd.name
    assert natija.nonce_len >= 32
    assert natija.run_id not in ("", None)


def test_a3_sorov_hujjati_shartnomaga_mos_va_kredensialsiz(tmp_path):
    """`request.json` validatordan o'tadi, XOM `locator` esa unga TUSHMAYDI."""
    kok = runs(tmp_path)
    muhit = muhit_bitta_baza(tmp_path)
    model = agent(tmp_path, scan=muhit, sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok)

    rd = pathlib.Path(natija.run_dir)
    req = sorov_hujjati(rd)
    bpr.validate_request(req)                      # shakl buzilsa — ISTISNO
    assert req["request_version"] == bpr.REQUEST_VERSION
    assert req["expected_collector"] == {"name": oc.EXPECTED_COLLECTOR_NAME,
                                         "version": oc.EXPECTED_COLLECTOR_VERSION}
    # ⚠️ Chiqish papkasi YURISHGA BOG'LANGAN: operator hech narsani qo'lda ko'chirmaydi.
    assert pathlib.Path(req["output_dir"]) == rd / BUNDLE_SUBDIR
    # ⚠️ XOM `locator` protokolga YOZILMAYDI — faqat xeshi.
    xom = (rd / bpr.REQUEST_FILE).read_text(encoding="utf-8")
    locator = muhit.infobases[0].locator
    assert locator not in xom
    assert req["target_fingerprint"] == oc.target_fingerprint_of(muhit.infobases[0])
    # ⚠️ PAROL/FOYDALANUVCHI kalitlari hujjatda BO'LMAYDI.
    for taqiq in ("Pwd", "Usr", "password", "parol"):
        assert taqiq not in xom


def test_a4_kaprik_hujjatlari_natija_paketiga_kochmaydi(tmp_path):
    """⚠️ `request/response/bridge_done` natija paketiga TUSHMAYDI (`bundle/` dan tashqarida).

    Sabab `bridge_protocol._notes` da yozilgan: ko'prik hujjatlari yurish papkasida qoladi
    va hisobotga ko'chirilmaydi. Shu bois `nonce` natija paketida HECH QACHON bo'lmaydi.
    """
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok)

    nomlar = set(X.papka_baytlari(natija.result_dir))
    for taqiq in (bpr.REQUEST_FILE, bpr.RESPONSE_FILE, bpr.DONE_FILE):
        assert taqiq not in nomlar
        assert f"{BUNDLE_SUBDIR}/{taqiq}" not in nomlar
    nonce = sorov_hujjati(natija.run_dir)["nonce"]
    baytlar = b"".join(X.papka_baytlari(natija.result_dir).values())
    assert nonce.encode("ascii") not in baytlar, "bir martalik belgi paketga SIZIB CHIQDI"


# ══════════════════════════════════════════════════════════════════════════════════════════
# B, C, D, E — MUHIT va NISHON DARVOZALARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_b_1c_yoq_bolsa_yurish_boshlanmaydi_va_papka_yaratilmaydi(tmp_path):
    """`absent` hukmi: `NO_1C` fazasi, `FAILED_NO_1C` holati, yurish papkasi YARATILMAYDI."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=X.muhit_1c_yoq())
    natija, hodisalar = bir_bosish(model, runs_root=kok)

    assert natija.phase == bp.NO_1C and natija.state == st.FAILED_NO_1C
    assert natija.run_id is None and natija.run_dir is None
    assert list(pathlib.Path(kok).iterdir()) == [], "1C yo'q bo'lsa papka yaratilmaydi"
    # ⚠️ «Qaradim va YO'Q» ma'nosi YAGONA manbadan keladi.
    assert natija.operator_text() == st.failure_meaning(
        st.FAILED_NO_1C, presence_verdict=det.PRESENCE_ABSENT)
    assert [h.phase for h in hodisalar] == [bp.DETECTING_1C, bp.NO_1C]


def test_b2_1c_holati_nomalum_bolsa_ham_davom_etilmaydi_lekin_mano_boshqa(tmp_path):
    """`unknown`: «qaray olmadim» — `absent` dan AJRATILGAN matn bilan."""
    model = agent(tmp_path, scan=X.muhit_huquq_yoq())
    natija, _ = bir_bosish(model, runs_root=runs(tmp_path))

    assert natija.phase == bp.NO_1C and natija.state == st.FAILED_NO_1C
    nomalum = st.failure_meaning(st.FAILED_NO_1C, presence_verdict=det.PRESENCE_UNKNOWN)
    yoq = st.failure_meaning(st.FAILED_NO_1C, presence_verdict=det.PRESENCE_ABSENT)
    assert natija.operator_text() == nomalum != yoq


def test_c_baza_royxati_bosh_bolsa_nishon_yoq(tmp_path):
    """1C BOR, baza YO'Q: faza `DISCOVERING_INFOBASES`, holat `FAILED_NO_TARGET`."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=X.muhit_bazasiz(tmp_path))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.phase == bp.DISCOVERING_INFOBASES
    assert natija.state == st.FAILED_NO_TARGET
    assert list(pathlib.Path(kok).iterdir()) == []
    assert natija.next_action().strip() != ""


def test_d_ikki_baza_bolsa_agent_ozi_tanlamaydi(tmp_path):
    """`TARGET_AMBIGUOUS`: qaror OPERATORDA, holat YAKUNIY EMAS, papka yaratilmaydi."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_ikki_baza(tmp_path))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.phase == bp.SELECT_TARGET
    assert natija.state == st.TARGET_SELECTION and not st.is_terminal(natija.state)
    assert natija.code == bp.CODE_TARGET_AMBIGUOUS
    assert natija.waiting_for_operator is True
    assert not natija.is_failure, "tanlovni kutish YIQILISH emas"
    assert list(pathlib.Path(kok).iterdir()) == []


def test_d2_bir_xil_baza_ikki_marta_elon_qilinsa_noaniqlik_yoq(tmp_path):
    """AYNI baza ikki marta e'lon qilinsa — NOANIQLIK paydo bo'lMAYDI, yurish davom etadi.

    ⚠️ Takrorni `detector` ning O'ZI yig'adi (bir xil ulanish satri — bitta baza), nishon
       darvozasi esa XESHLARNI sanaydi. Ya'ni ikki qatlam ham AYNI xulosaga keladi va
       operator ma'nosiz tanlovga majbur qilinmaydi.
    """
    kok = runs(tmp_path)
    baza = X.baza_oddiy(tmp_path, "Takrorlangan baza")
    scan = X.muhit_bazali(tmp_path, baza, baza)
    model = agent(tmp_path, scan=scan, sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert len(scan.infobases) == 1
    xeshlar = [oc.target_fingerprint_of(ib) for ib in scan.infobases]
    assert bpr.assert_unique_target(xeshlar * 2) == xeshlar[0]
    assert natija.state == st.COMPLETE, "bir xil nishonning ikki e'loni NOANIQLIK emas"


def test_e_operator_bazani_tanlasa_yurish_oxirigacha_boradi(tmp_path):
    """Tanlov operatordan (`select_index`) kelsa — yurish `COMPLETE` bo'ladi."""
    kok = runs(tmp_path)
    scan = muhit_ikki_baza(tmp_path)
    model = agent(tmp_path, scan=scan, sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok, select_index=1)

    assert natija.state == st.COMPLETE
    req = sorov_hujjati(natija.run_dir)
    assert req["target_fingerprint"] == oc.target_fingerprint_of(scan.infobases[1])
    rp.validate_result_package(natija.result_dir)


def test_e2_parol_talab_qiladigan_baza_oqimni_toxtatmaydi(tmp_path):
    """⚠️ `requires_auth` bu oqimda YIQILISH EMAS: parolni 1C ning O'Z oynasi oladi."""
    kok = runs(tmp_path)
    scan = X.muhit_bazali(tmp_path, X.baza_parolli(tmp_path))
    model = agent(tmp_path, scan=scan, sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert scan.infobases[0].requires_auth == det.TRI_TRUE
    assert natija.state == st.COMPLETE
    assert natija.state != st.FAILED_AUTH_REQUIRED


# ══════════════════════════════════════════════════════════════════════════════════════════
# F, G — KUTISH: CHEKLI va KO'RINADIGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_f_yiguvchi_hech_narsa_yozmasa_kutish_chekli_tugaydi(tmp_path):
    """Javob YO'Q: `RESPONSE_MISSING`, holat `FAILED_TIMEOUT`, kutish CHEKLI."""
    kok = runs(tmp_path)
    uyqular: list = []
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path),
                  sleeper=X.yozib_oluvchi_uyqu(uyqular), timeout_seconds=6.0)
    kutishlar: list = []
    natija, _ = bir_bosish(model, runs_root=kok, kutish_jurnali=kutishlar)

    assert natija.phase == bp.WAITING_FOR_COLLECTOR
    assert natija.state == st.FAILED_TIMEOUT
    assert natija.code == bp.CODE_RESPONSE_MISSING
    # ⚠️ CHEKSIZ KUTISH YO'Q: o'lchov soni ikki mustaqil chegara bilan cheklangan.
    assert 0 < natija.waited_ticks <= int(6.0 / 2.0) + 2
    assert len(uyqular) == natija.waited_ticks
    # ⚠️ KUTISH KO'RINADI va matnida YO'L YO'Q.
    assert kutishlar and all(m.strip() for m in kutishlar)
    assert not any(":\\" in m or "/" in m for m in kutishlar)


def test_g_paket_bor_lekin_belgi_yoq_bolsa_natija_qabul_qilinmaydi(tmp_path):
    """Tugallanish belgisi YO'Q: `DONE_MARKER_MISSING` — «yarim yozilgan» natija rad etiladi."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), timeout_seconds=6.0,
                  sleeper=yiguvchi(kok, belgi=False))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.state == st.FAILED_TIMEOUT
    assert natija.code == bp.CODE_DONE_MARKER_MISSING
    assert natija.result_dir is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# H..N — YURISHGA BOG'LANGAN RAD ETISHLAR (har biri O'Z KODI bilan)
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kw, kod", [
    # ⚠️ BEGONA `run_id` SHAKLI TO'G'RI bo'lishi SHART: aks holda rad etish sababi
    #    `STALE_OUTPUT` emas, `BRIDGE_SHAPE_INVALID` bo'lib ketardi va bu ssenariy
    #    «boshqa yurishning javobi» ni umuman O'LCHAMAGAN bo'lardi.
    ({"run_id": "0f0f0f0f0f0f0f0f"}, bp.CODE_STALE_OUTPUT),
    ({"nonce": "f" * 32}, bp.CODE_NONCE_MISMATCH),
    ({"collector": {"name": "BinOSDiscovery", "version": "0.2.0-UNVERIFIED"}},
     bp.CODE_WRONG_COLLECTOR_VERSION),
    ({"xesh": "a" * 64}, bp.CODE_TARGET_FINGERPRINT_MISMATCH),
    ({"paket": paket_yarim}, bp.CODE_PARTIAL_PACKAGE),
    ({"belgi_vaqti": "2020-01-01T00:00:00+00:00"}, bp.CODE_OUTPUT_PREDATES_REQUEST),
    ({"status": bpr.STATUS_CANCELLED}, bp.CODE_OPERATOR_CANCELLED),
])
def test_h_begona_yoki_nosoz_javob_oz_kodi_bilan_rad_etiladi(tmp_path, kw, kod):
    """HAR rad etish sababi ALOHIDA kod bilan qaytadi va uchligi TO'LIQ bo'ladi."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path),
                  sleeper=yiguvchi(kok, **kw))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.code == kod
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE
    uchlik = bp.failure_triple(kod)
    assert natija.operator_text() == uchlik.operator
    assert natija.next_action() == uchlik.next_action
    assert natija.result_dir is None, "qabul qilinmagan natija bo'yicha xulosa chiqarilmaydi"


def test_i_yiguvchi_yiqilganini_ozi_aytsa_bu_javob_lekin_complete_emas(tmp_path):
    """`status=FAILED` — JAVOB, lekin `COMPLETE` emas; AYB kodi YOZILMAYDI."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path),
                  sleeper=yiguvchi(kok, status=bpr.STATUS_FAILED, paket=paket_yarim))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE
    # ⚠️ `FAILED` da paketning to'liqligi SABAB emas, NATIJA — shu bois `PARTIAL_PACKAGE`
    #    kodi YOZILMAYDI.
    assert natija.code is None
    assert natija.next_action().strip() != ""


def test_j_javob_buzuq_json_bolsa_shakl_kodi_bilan_rad_etiladi(tmp_path):
    """Fayl bor, lekin o'qilmaydi: `BRIDGE_SHAPE_INVALID` («mos emas» dan AJRATILGAN)."""
    kok = runs(tmp_path)

    def buzuq(_soniya: float) -> None:
        rd = yurish_papkasi(kok)
        if (rd / bpr.DONE_FILE).exists():
            return
        req = sorov_hujjati(rd)
        M.paket_sog_lom(str(rd / BUNDLE_SUBDIR))
        (rd / bpr.RESPONSE_FILE).write_text("{bu JSON emas", encoding="utf-8")
        _yoz_json(rd / bpr.DONE_FILE, belgi_hujjati(req))

    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=buzuq)
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.code == bp.CODE_BRIDGE_SHAPE_INVALID
    assert natija.phase == bp.COLLECTOR_FAILED


# ══════════════════════════════════════════════════════════════════════════════════════════
# O, P — YURISH PAPKASI: HECH NARSA O'CHIRILMAYDI, TAXMIN QILINMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_o_yurish_papkasi_bosh_bolmasa_agent_yozmaydi_va_ochirmaydi(tmp_path, monkeypatch):
    """`RUN_DIR_NOT_EMPTY`: begona fayl JOYIDA qoladi, agent uni O'CHIRMAYDI.

    ⚠️ `run_id` tasodifiy, shu bois shu testda u QOTIRILADI (`new_run` almashtiriladi) —
       darvozaning O'ZI esa HAQIQIY `prepare_run_dir`.
    """
    kok = runs(tmp_path)
    qotgan = bpr.RunIdentity(run_id="a" * 16, nonce="b" * 32, requested_at=X.NOW_ISO)
    monkeypatch.setattr(bpr, "new_run", lambda *, now: qotgan)
    band = pathlib.Path(kok) / qotgan.run_id
    band.mkdir()
    (band / "begona.txt").write_text("operatorning fayli", encoding="utf-8")

    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path))
    natija, _ = bir_bosish(model, runs_root=kok)

    assert natija.code == bp.CODE_RUN_DIR_NOT_EMPTY
    assert natija.phase == bp.PREPARING_COLLECTOR and natija.state == st.FAILED_SAFETY
    assert (band / "begona.txt").is_file(), "agent BEGONA faylga TEGMAYDI"
    assert not (band / bpr.REQUEST_FILE).exists()


def test_p_yurish_ildizi_nomalum_bolsa_taxmin_qilinmaydi(tmp_path, monkeypatch):
    """`RUNS_ROOT_UNKNOWN`: muhit o'zgaruvchisi yo'q bo'lsa — FAIL-CLOSED, zaxira joy YO'Q."""
    monkeypatch.delenv(bpr.LOCALAPPDATA_ENV, raising=False)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path))
    natija, _ = bir_bosish(model, runs_root=None)

    assert natija.code == bp.CODE_RUNS_ROOT_UNKNOWN
    assert natija.state == st.FAILED_SAFETY
    # ⚠️ Joriy papkaga ham, manba daraxtiga ham hech narsa yozilmagan.
    assert natija.run_dir is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# S — IKKI BIR VAQTDA YURISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_s_ikki_yurish_bir_birining_natijasini_kormaydi(tmp_path):
    """Har yurish O'Z `run_id`/papkasini oladi; begona javob `STALE_OUTPUT` bilan rad etiladi."""
    kok = runs(tmp_path)
    birinchi = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok),
                     nom="natija-1")
    n1, _ = bir_bosish(birinchi, runs_root=kok)
    assert n1.state == st.COMPLETE

    # ⚠️ IKKINCHI yurish: BIRINCHISINING tayyor natijasi papkada TURADI, lekin u BOSHQA
    #    papkada va ikkinchi yurish uni KO'RMAYDI. Javobni qo'lda ko'chirsak ham — RAD.
    oldingi = {pathlib.Path(n1.run_dir).name}
    ikkinchi_yozuvchi = _kochiruvchi(kok, n1.run_dir, oldingi)
    ikkinchi = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=ikkinchi_yozuvchi,
                     nom="natija-2", timeout_seconds=6.0)
    n2, _ = bir_bosish(ikkinchi, runs_root=kok)

    assert n2.run_id != n1.run_id
    assert n2.run_dir != n1.run_dir
    assert n2.code == bp.CODE_STALE_OUTPUT
    assert n2.result_dir is None
    # ⚠️ BIRINCHI yurishning natijasi BUZILMAGAN va O'CHIRILMAGAN.
    rp.validate_result_package(n1.result_dir)
    assert (pathlib.Path(n1.run_dir) / bpr.DONE_FILE).is_file()


def _kochiruvchi(runs_root, manba_run_dir, oldingi):
    """BEGONA yurishning javobini va paketini YANGI yurish papkasiga KO'CHIRADI (fikstura).

    ⚠️ Bu «eski natijani qayta ishlatish» hujumining AYNAN o'zi: fayllar to'g'ri, lekin
       yurish BOSHQA. Protokol buni `run_id` bo'yicha tutadi.
    """
    holat = {"yozildi": False}

    def uxla(_soniya: float) -> None:
        if holat["yozildi"]:
            return
        holat["yozildi"] = True
        yangi = yurish_papkasi(runs_root, oldingi)
        manba = pathlib.Path(manba_run_dir)
        M.paket_sog_lom(str(yangi / BUNDLE_SUBDIR))
        for nom in (bpr.RESPONSE_FILE, bpr.DONE_FILE):
            (yangi / nom).write_text((manba / nom).read_text(encoding="utf-8"),
                                     encoding="utf-8")

    return uxla


# ══════════════════════════════════════════════════════════════════════════════════════════
# T, U — FAZALAR: FAQAT OLDINGA, HAR FAZADA MATN BOR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_t_fazalar_faqat_oldinga_yuradi_va_holat_bilan_zid_emas(tmp_path):
    """Har hodisa: faza bir ma'noli holatga mos va tartib FAQAT oldinga."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    _, hodisalar = bir_bosish(model, runs_root=kok)

    indekslar = [bp.BRIDGE_PHASES.index(h.phase) for h in hodisalar]
    assert indekslar == sorted(set(indekslar)), "faza ORQAGA qaytdi yoki takrorlandi"
    for h in hodisalar:
        assert h.state == bp.phase_state(h.phase)
        assert h.text == bp.phase_text(h.phase)
        assert h.text.strip() != "", "«spinner-only» faza BO'LMAYDI"


def test_t2_faza_orqaga_qaytarilsa_istisno_boladi():
    """⚠️ Ekranda «tahlil» dan keyin «1C qidirilyapti» chiqishi — YOLG'ON xabar, TAQIQ."""
    oqim = oc._Oqim()
    oqim.emit(bp.ANALYZING)
    with pytest.raises(oc.OneClickError):
        oqim.emit(bp.DETECTING_1C)


def test_u_zid_natija_umuman_tugilmaydi():
    """Holat fazadan ORQADA bo'lishi — fail-closed TAQIQ (yiqilish sababi almashmasin)."""
    with pytest.raises(oc.OneClickError):
        oc.OneClickOutcome(phase=bp.ANALYZING, state=st.FAILED_NO_1C, detail="zid")
    # Ruxsat etilgan uchta shakl ISHLAYDI.
    oc.OneClickOutcome(phase=bp.COMPLETE, state=st.COMPLETE, detail="ok")
    oc.OneClickOutcome(phase=bp.INGESTING, state=st.FAILED_VALIDATION, detail="ok")
    oc.OneClickOutcome(phase=bp.ANALYZING, state=st.FAILED_REPORT, detail="ok")


def test_u2_noanaiq_kod_yoki_kutish_bilan_yakun_qabul_qilinmaydi():
    """Noma'lum ko'prik kodi va «yakunlangan yurish operatorni kutadi» — ISTISNO."""
    with pytest.raises(bp.BridgePhaseError):
        oc.OneClickOutcome(phase=bp.COMPLETE, state=st.COMPLETE, detail="ok",
                           code="OYLAB_CHIQARILGAN_KOD")
    with pytest.raises(oc.OneClickError):
        oc.OneClickOutcome(phase=bp.COMPLETE, state=st.COMPLETE, detail="ok",
                           waiting_for_operator=True)


def test_u3_faza_xaritasi_bu_modulda_almashtirilmaydi():
    """⚠️ `one_click` xaritani O'ZGARTIRMAYDI, unga TAYANADI: har faza AYNAN bir holatda."""
    assert len(bp.BRIDGE_PHASES) == 12
    assert set(oc._PHASE_INDEX) == set(bp.BRIDGE_PHASES)
    for faza in bp.BRIDGE_PHASES:
        assert bp.phase_state(faza) in st.STATES


# ══════════════════════════════════════════════════════════════════════════════════════════
# V, W — AVTOMATIK ISHGA TUSHIRISH DARVOZASI va SIRLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_v_agent_1c_ni_ozi_ishga_tushirmaydi(tmp_path):
    """`LAUNCHING_1C` fazasida operatorga AYNAN «yig'uvchini O'ZINGIZ bajaring» deyiladi."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    _, hodisalar = bir_bosish(model, runs_root=kok)

    ishga = [h for h in hodisalar if h.phase == bp.LAUNCHING_1C]
    assert len(ishga) == 1
    uchlik = bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
    assert ishga[0].detail == uchlik.next_action
    # ⚠️ Darvoza FAIL-CLOSED va u shipped yo'lda chaqiriladi (o'lik kod EMAS).
    with pytest.raises(bpr.BridgeProtocolError):
        bpr.assert_launch_allowed(operator_confirmed=False)
    assert bp.AUTOMATIC_LAUNCH_VERIFICATION == "UNVERIFIED_ON_REAL_1C"


def test_w_operator_matnlarida_sir_va_yol_yoq(tmp_path):
    """Hodisa matnlari, xulosa va keyingi qadam `redact.scan` darvozasidan O'TADI."""
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija, hodisalar = bir_bosish(model, runs_root=kok)

    matnlar = [h.text for h in hodisalar] + [h.detail for h in hodisalar if h.detail]
    matnlar += [natija.operator_text(), natija.next_action(), natija.detail]
    matnlar += list(oc.REQUEST_NOTES)
    topilgan = redact.scan(matnlar)
    assert topilgan == [], f"operator matnlarida shubhali qiymat: {topilgan}"


def test_w2_epf_binari_qurilgan_deb_atalmaydi():
    """⚠️ Holat nomi AYNAN `EPF_SOURCE_READY` — ikkilik `.epf` qurilgan DEB AYTILMAYDI."""
    assert bp.EPF_SOURCE_READY == "EPF_SOURCE_READY"
    matn = ONE_CLICK_SRC.read_text(encoding="utf-8") + FLOW_DOC.read_text(encoding="utf-8")
    for yolgon in ("`.epf` qurildi", ".epf tayyor", "bir bosishda tayyor"):
        assert yolgon.lower() not in matn.lower()


def test_w3_hujjat_besh_qadam_va_ichki_atamalar_faqat_diagnostikada():
    """Operator oqimi: BESH qadam, ichki atamalar FAQAT yig'iladigan diagnostikada."""
    matn = FLOW_DOC.read_text(encoding="utf-8")
    asosiy, ajratuvchi, diagnostika = matn.partition("<details>")
    assert ajratuvchi, "«batafsil diagnostika» bo'limi YIG'ILADIGAN bo'lishi kerak"
    for qadam in ("Qadam 1 — «1C topildi»", "Qadam 2 — «Bazani tanlang»",
                  "Qadam 3 — «Discovery boshlash»", "Qadam 4 — Progress",
                  "Qadam 5 — Muvaffaqiyat yoki nosozlik"):
        assert qadam in asosiy, f"operator oqimida qadam yo'q: {qadam}"
    # ⚠️ ICHKI ATAMA ASOSIY OQIMDA KO'RSATILMAYDI: operator uchun u shovqin, va u
    #    «men bu yerda nimani tushunmayapman?» degan savol tug'diradi.
    for atama in ("nonce", "bundle/", "run_id", "PHASE_TO_STATE", "binos-bridge",
                  "allowed_probes", "target_fingerprint"):
        assert atama not in asosiy, f"ichki atama asosiy oqimga chiqib ketdi: {atama}"
        assert atama in diagnostika, f"ichki atama diagnostikada bo'lishi kerak: {atama}"
    # ⚠️ ENG MUHIM IKKI DA'VO: operator fayl ko'chirmaydi va `.epf` HALI yig'ilmagan.
    assert "qo'lda ko'chirish KERAK EMAS" in asosiy
    assert bp.EPF_SOURCE_READY in asosiy
    # ⚠️ Chiqish kodlari shartnomasi hujjatda ham turadi (skript yozadigan operator uchun).
    for kod in ("`0`", "`1`", "`2`"):
        assert kod in asosiy


def test_x_kutilgan_ozlik_KOPRIK_manbasi_va_VERSION_json_bilan_AYNAN_MOS():
    """⚠️⚠️ TUZATILGAN P0: agent KO'PRIKNING o'zligini kutishi SHART.

    `response.json` ni YOZADIGAN modul — ko'prik qatlami
    (`integrations/1c/collector/BinOSDiscoveryCollector.bsl`), demak javobdagi
    `collector` maydoni UNING nomi va versiyasi. Manba haqiqati `VERSION.json` da.
    Ilgari agent ICHKI yig'uvchining o'zligini (`BinOSDiscovery` / `0.2.0-UNVERIFIED`)
    kutardi — natijada HAR BIR haqiqiy javob `WRONG_COLLECTOR_VERSION` bilan rad
    etilardi va bu nuqsonni yashil to'plam YASHIRARDI.
    """
    yozilgan = json.loads(BRIDGE_VERSION.read_text(encoding="utf-8-sig"))["collector"]
    assert (oc.EXPECTED_COLLECTOR_NAME, oc.EXPECTED_COLLECTOR_VERSION) == \
        (yozilgan["name"], yozilgan["version"]), \
        "kutilgan o'zlik `VERSION.json` dan AYNAN olinadi (ikki haqiqat bo'lmasin)"
    manba = BRIDGE_SOURCE.read_text(encoding="utf-8-sig")
    assert f'"{oc.EXPECTED_COLLECTOR_NAME}"' in manba
    assert f'"{oc.EXPECTED_COLLECTOR_VERSION}"' in manba
    # ⚠️ `.epf` IKKILIK fayli QURILMAGAN: versiya satri shuni AYTIB turishi SHART.
    assert oc.EXPECTED_COLLECTOR_VERSION.endswith("-source")


def test_x2_ikki_ozlik_ARALASHTIRILMAYDI_va_ichki_yiguvchi_YOQOLMAYDI():
    """⚠️⚠️ IKKI O'ZLIK IKKI JOYDA QOLADI va bir-birini ALMASHTIRMAYDI.

    · KO'PRIK (`BinOSDiscoveryCollector` / `0.1.0-source`) — `response.json`.`collector`;
    · ICHKI yig'uvchi (`BinOSDiscovery` / `0.2.0-UNVERIFIED`) — Phase 4 shartnomasi
      bo'yicha `bundle/export.json`.`collector`, ya'ni uning o'zligi YO'QOLMAYDI.
    Agar agent ichki o'zlikni kutsa — P0 qaytadi; agar ichki o'zlik manbadan yo'qolsa —
    Phase 4 paketi o'z yig'uvchisini atamay qoladi. Shu bois IKKISI ham qulflanadi.
    """
    ichki = EXTRACTOR_SOURCE.read_text(encoding="utf-8-sig")
    assert '"BinOSDiscovery"' in ichki, "ichki yig'uvchining o'zligi manbada QOLISHI SHART"
    assert oc.EXPECTED_COLLECTOR_NAME != "BinOSDiscovery", \
        "agent ICHKI yig'uvchining nomini kutmasligi SHART (P0 nuqsonning o'zi)"
    assert oc.EXPECTED_COLLECTOR_VERSION != "0.2.0-UNVERIFIED"
    # ⚠️ Ikki nom bir-birining prefiksi: solishtirish AYNAN tenglik bo'lishi SHART,
    #    «boshlanadi» (`startswith`) bo'lsa ichki o'zlik jimgina o'tib ketardi.
    assert oc.EXPECTED_COLLECTOR_NAME.startswith("BinOSDiscovery")
    # ⚠️ Darvoza `bridge_protocol.validate_response` da AYNAN TENGLIK bilan: prefiks
    #    naqshi bo'lsa ichki o'zlik jimgina o'tib ketardi.
    req = bpr.build_request(
        bpr.new_run(now=X.NOW_ISO), output_dir=str(pathlib.Path(oc.__file__).parent),
        collector_name=oc.EXPECTED_COLLECTOR_NAME,
        collector_version=oc.EXPECTED_COLLECTOR_VERSION,
        target_fingerprint="a" * 64, mode=rb.MODE_METADATA_ONLY, notes=(),
    )
    resp = javob_hujjati(req, collector={"name": "BinOSDiscovery",
                                         "version": oc.EXPECTED_COLLECTOR_VERSION})
    with pytest.raises(bpr.BridgeProtocolError) as xato:
        bpr.validate_response(resp, request=req)
    assert xato.value.code == bp.CODE_WRONG_COLLECTOR_VERSION


# ══════════════════════════════════════════════════════════════════════════════════════════
# Y — STATIK TAQIQLAR (manba matni bo'yicha)
# ══════════════════════════════════════════════════════════════════════════════════════════
def kod_matni(yol) -> str:
    """Manba matni IZOH va DOCSTRING larsiz.

    ⚠️⚠️ NEGA SHUNDAY: taqiqlar KODDA tekshirilishi kerak, IZOHDA emas. Oddiy matn
         qidiruvi «`rmtree` naqshi YO'Q» degan izohning O'ZINI topib, taqiqni ISBOT
         o'rniga NIQOB qilib qo'yardi — ya'ni to'g'ri yozilgan izoh testni yiqitardi va
         izohni o'chirishga majbur qilardi.
    ⚠️ Izohlar AST ga umuman tushmaydi; docstringlar esa `Pass` bilan almashtiriladi.
    """
    daraxt = ast.parse(pathlib.Path(yol).read_text(encoding="utf-8"))
    for tugun in ast.walk(daraxt):
        tana = getattr(tugun, "body", None)
        if not isinstance(tana, list) or not tana:
            continue
        birinchi = tana[0]
        if (isinstance(birinchi, ast.Expr) and isinstance(birinchi.value, ast.Constant)
                and isinstance(birinchi.value.value, str)):
            tana[0] = ast.Pass()
    return ast.unparse(ast.fix_missing_locations(daraxt))


def test_y_jarayon_oldirish_va_wildcard_ochirish_naqshi_yoq():
    """⚠️ Bekor qilish KOOPERATIV: jarayon daraxtini tugatish va `rmtree` naqshi YO'Q."""
    matn = kod_matni(ONE_CLICK_SRC)
    for taqiq in ("taskkill", "rmtree", "terminate(", "kill(", "unlink(", "shutil",
                  "subprocess", "win32com", "CreateObject", "Popen", "os.remove",
                  "glob", "/C "):
        assert taqiq not in matn, f"taqiqlangan naqsh topildi: {taqiq}"
    # ⚠️ Papka YARATISH bor (o'z yurish papkasi), O'CHIRISH esa YO'Q.
    assert "mkdir" in matn


def test_y2_kredensial_bayrogi_va_parol_maydoni_yoq():
    """⚠️ Parol uchun bayroq ham, kirish parametri ham YO'Q (buyruq satri ko'rinadi)."""
    yordam = cli.build_parser().format_help()
    for taqiq in ("--password", "--parol", "--user", "/P", "/N"):
        assert taqiq not in yordam
    matn = kod_matni(ONE_CLICK_SRC)
    for taqiq in ("password=", "parol=", "Pwd=", "Usr="):
        assert taqiq not in matn


# ══════════════════════════════════════════════════════════════════════════════════════════
# Z — BUYRUQ SATRI (`--one-click`)
# ══════════════════════════════════════════════════════════════════════════════════════════
class _Oqim:
    """Chiqishni yig'adigan soxta oqim (chop etish testni to'xtatmaydi)."""

    def __init__(self) -> None:
        self.satrlar: list[str] = []

    def write(self, s):
        self.satrlar.append(s)
        return len(s)

    def flush(self):
        return None

    @property
    def matn(self) -> str:
        return "".join(self.satrlar)


def _cli(argv, *, scan, sleeper=None, out=None, err=None):
    out = _Oqim() if out is None else out
    err = _Oqim() if err is None else err
    kod = cli.main(argv, out=out, err=err, scan=lambda: scan, now=lambda: X.NOW_ISO,
                   clock=X.oshuvchi_soat(1.0),
                   sleeper=(lambda _s: None) if sleeper is None else sleeper)
    return kod, out, err


def test_z_bir_bosishli_oqim_buyruq_satridan_yuradi(tmp_path):
    """`--one-click`: chiqish kodi `0`, fazalar ko'rinadi, natija papkasi yoziladi."""
    kok = runs(tmp_path)
    ota = tmp_path / "cli-natija"
    ota.mkdir()
    kod, out, _ = _cli(["--one-click", "--result-dir", str(ota), "--runs-dir", kok],
                       scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))

    assert kod == cli.EXIT_OK
    assert f"faza: {bp.COMPLETE}" in out.matn
    assert "yurish o'zligi:" in out.matn
    papkalar = [p for p in ota.iterdir() if p.is_dir()]
    assert len(papkalar) == 1
    rp.validate_result_package(str(papkalar[0]))


def test_z2_bir_bosish_va_headless_birga_ishlamaydi(tmp_path):
    """⚠️ Ikki papka da'vosi — «ikki haqiqat»: ANIQ rad etish (kod `2`)."""
    kod, _, err = _cli(["--one-click", "--headless", str(tmp_path)],
                       scan=muhit_bitta_baza(tmp_path))
    assert kod == cli.EXIT_CANNOT_RUN
    assert "--one-click" in err.matn and "--headless" in err.matn


@pytest.mark.parametrize("argv", [
    ["--runs-dir", "."],
    ["--target", "1"],
])
def test_z3_bir_bosishsiz_bayroqlar_jim_tashlab_yuborilmaydi(tmp_path, argv):
    """⚠️ Jim e'tiborsizlik YO'Q: bayroq qabul qilinmasa — ANIQ aytiladi."""
    kod, _, err = _cli(argv + ["--headless", str(tmp_path)],
                       scan=muhit_bitta_baza(tmp_path))
    assert kod == cli.EXIT_CANNOT_RUN
    assert "--one-click" in err.matn


def test_z4_nishon_tanlanmasa_royxat_korsatiladi_va_kod_ikki(tmp_path):
    """Ikki baza: yurish BOSHLANMADI (kod `2`) va operator RO'YXATNI ko'radi."""
    kok = runs(tmp_path)
    kod, _, err = _cli(["--one-click", "--result-dir", str(tmp_path), "--runs-dir", kok],
                       scan=muhit_ikki_baza(tmp_path))

    assert kod == cli.EXIT_CANNOT_RUN
    assert "1." in err.matn and "2." in err.matn
    assert bp.failure_triple(bp.CODE_TARGET_AMBIGUOUS).next_action in err.matn


def test_z5_notogri_nishon_raqami_yurishni_boshlamaydi(tmp_path):
    """`--target` noto'g'ri bo'lsa — kod `2` va ro'yxat ko'rsatiladi (jim rad etish YO'Q)."""
    kok = runs(tmp_path)
    kod, _, err = _cli(["--one-click", "--result-dir", str(tmp_path), "--runs-dir", kok,
                        "--target", "9"], scan=muhit_ikki_baza(tmp_path))
    assert kod == cli.EXIT_CANNOT_RUN
    assert "2." in err.matn

    kod2, _, _ = _cli(["--one-click", "--result-dir", str(tmp_path), "--runs-dir", kok,
                       "--target", "nol"], scan=muhit_ikki_baza(tmp_path))
    assert kod2 == cli.EXIT_CANNOT_RUN


def test_z6_1c_yoq_bolsa_chiqish_kodi_bir(tmp_path):
    """⚠️ `1` — yurish YIQILDI (bu JAVOB), `2` — yurish BOSHLANMADI. Ajrim SAQLANADI."""
    kok = runs(tmp_path)
    kod, _, err = _cli(["--one-click", "--result-dir", str(tmp_path), "--runs-dir", kok],
                       scan=X.muhit_1c_yoq())
    assert kod == cli.EXIT_FAILED_RUN
    assert "keyingi qadam:" in err.matn


def test_z7_yordam_matni_quriladi_va_uchta_yangi_bayroq_bor():
    """⚠️ `--help` ning O'ZI yiqilmasligi (argparse `%` tuzog'i) qulflanadi."""
    yordam = cli.build_parser().format_help()
    for bayroq in ("--one-click", "--runs-dir", "--target"):
        assert bayroq in yordam
    assert bpr.LOCALAPPDATA_ENV in yordam


# ══════════════════════════════════════════════════════════════════════════════════════════
# AA..AF — `launcher` SHIPPED KODDA: ISHGA TUSHIRISH DARVOZASI, BEKOR QILISH, NISHON O'ZLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_aa_ishga_tushirish_darvozasi_TASDIQSIZ_yurishni_ANIQ_TOXTATADI(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON: darvoza BEZAK edi.

    Ilgari `run_one_click` `assert_launch_allowed(operator_confirmed=False)` ni QOTIRILGAN
    `False` bilan chaqirib, istisnoni darrov ushlab, faqat faza TAFSILOTIGA aylantirardi —
    ya'ni «tasdiq» hech narsani darvozalamasdi. Endi chaqiruvchi agentning O'ZI 1C ni
    ochishini so'rasa (`opener` berilgan) va tasdiq YO'Q bo'lsa, yurish ANIQ TO'XTAYDI va
    ochuvchi UMUMAN chaqirilmaydi.
    ⚠️ Holat YAKUNIY EMAS: yurish YIQILMADI, qaror OPERATORDA (chiqish kodi 2).
    """
    kok = runs(tmp_path)
    ochuvchi = H.SoxtaIshgaTushiruvchi()
    model = agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), sleeper=yiguvchi(kok))
    hodisalar: list = []
    natija = oc.run_one_click(model, runs_root=kok, opener=ochuvchi,
                              on_event=hodisalar.append)

    assert natija.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
    assert natija.phase == bp.LAUNCHING_1C
    assert natija.state == bp.phase_state(bp.LAUNCHING_1C) == st.METADATA_DISCOVERY
    assert natija.waiting_for_operator is True, "qaror OPERATORDA — yurish YIQILMADI"
    assert not natija.is_failure and not natija.is_complete
    assert ochuvchi.chaqiruvlar == 0, "tasdiq yo'q bo'lsa ochuvchi CHAQIRILMAYDI"
    assert hodisalar[-1].phase == bp.LAUNCHING_1C, "kutish BOSHLANMAYDI"
    assert natija.waited_ticks == 0 and natija.result_dir is None
    uchlik = bp.failure_triple(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED)
    assert natija.operator_text() == uchlik.operator
    assert natija.next_action() == uchlik.next_action


def test_ab_tasdiq_berilsa_1C_ROSTDAN_ochiladi_va_jarayon_OLDIRILMAYDI(tmp_path):
    """⚠️⚠️ DARVOZA IKKI TOMONGA ISHLAYDI: tasdiq bo'lsa `launcher` 1C ni ROSTDAN ochadi.

    ⚠️ Buyruq `launcher.build_open_command` da quriladi va KREDENSIAL darvozasidan
       o'tadi: nishon kaliti AYNAN bitta (`/F` yoki `/S`), parol kaliti YO'Q.
    ⚠️ JARAYON O'LDIRILMAYDI: ochilgan soxta jarayon yurish TUGAGANDAN keyin ham TIRIK va
       tugatish sanog'i NOL (bekor qilish KOOPERATIV).
    """
    kok = runs(tmp_path)
    ochuvchi = H.SoxtaIshgaTushiruvchi()
    model = agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), sleeper=yiguvchi(kok))
    hodisalar: list = []
    natija = oc.run_one_click(model, runs_root=kok, opener=ochuvchi,
                              operator_confirmed=True, on_event=hodisalar.append)

    assert natija.state == st.COMPLETE and natija.phase == bp.COMPLETE
    assert ochuvchi.chaqiruvlar == 1, "1C AYNAN bir marta ochiladi"
    buyruq = ochuvchi.buyruqlar[0]
    assert buyruq[1] == ln.VERB_ENTERPRISE
    kalitlar = [t for t in buyruq if t.upper().startswith(bpr.ALLOWED_TARGET_SWITCHES)]
    assert len(kalitlar) == 1, "nishon kaliti AYNAN bitta"
    for taqiq in ("/N", "/P", "/C"):
        assert not any(t.upper().startswith(taqiq) for t in buyruq), \
            f"buyruqda {taqiq} bo'lmasligi SHART (kredensial va o'ylab chiqarilgan kalit)"
    assert ochuvchi.hammasi_tirik and ochuvchi.tugatish_chaqirildi == 0
    launching = [h for h in hodisalar if h.phase == bp.LAUNCHING_1C]
    assert len(launching) == 1 and "agent tomonidan ochildi" in launching[0].detail


def test_ab2_1C_ochilmasa_yurish_TOXTAYDI_va_SABAB_launcher_dan_keladi(tmp_path):
    """⚠️ Agent ochishni O'Z ustiga olgan bo'lsa va 1C OCHILMASA — yurish to'xtaydi.

    ⚠️ Kod `collector_bridge.CODE_LAUNCH_FAILED` — u KO'PRIK kodi EMAS, shu bois u
       `run_code` da qaytadi va ko'prik kodi deb ATALMAYDI (`code` bo'sh qoladi).
    """
    kok = runs(tmp_path)
    ochuvchi = H.SoxtaIshgaTushiruvchi(ocha_oladimi=False)
    model = agent(tmp_path, scan=H.muhit_bir_baza(tmp_path), sleeper=yiguvchi(kok))
    natija = oc.run_one_click(model, runs_root=kok, opener=ochuvchi,
                              operator_confirmed=True)

    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.state == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.code is None, "ko'prik kodi YO'Q — sabab ishga tushirish qatlamidan"
    assert natija.run_code == cb.CODE_LAUNCH_FAILED
    assert ochuvchi.chaqiruvlar == 1 and ochuvchi.tugatish_chaqirildi == 0
    assert natija.next_action().strip() != ""


def test_ac_bekor_qilish_KOOPERATIV_va_OPERATORGA_YETIB_BORADI(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON: `launcher` ni shipped kodda HECH KIM chaqirmasdi, ya'ni
    KOOPERATIV BEKOR QILISH e'lon qilingan-u, YETIB BO'LMAYDIGAN qobiliyat edi.

    ⚠️ Holat MAVJUD `states.ABORTED_BY_OPERATOR` — YANGI holat QO'SHILMAYDI.
    ⚠️ Faza `WAITING_FOR_COLLECTOR` da QOLADI: `COLLECTOR_FAILED` fazasi
       `FAILED_COLLECTOR_UNAVAILABLE` ga bog'langan va «yig'uvchi javob bermadi» degan
       BOSHQA sababni ko'rsatardi.
    ⚠️ YURISH PAPKASIGA TO'RTINCHI HUJJAT YOZILMAYDI: bekor qilish XOTIRADA.
    """
    kok = runs(tmp_path)
    belgi = ln.CancelToken()
    belgi.cancel()
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija = oc.run_one_click(model, runs_root=kok, cancel=belgi)

    assert natija.code == bp.CODE_OPERATOR_CANCELLED
    assert natija.state == st.ABORTED_BY_OPERATOR
    assert natija.phase == bp.WAITING_FOR_COLLECTOR
    assert natija.result_dir is None, "bekor qilingan yurish xulosa BERMAYDI"
    assert natija.next_action().strip() != ""
    rd = yurish_papkasi(kok)
    assert not bpr.cancel_marker_path(rd).exists(), \
        "bekor qilish belgisi FAYL bo'lib yozilmaydi (shartnoma halol qoladi)"
    assert sorted(p.name for p in rd.iterdir()) == sorted([BUNDLE_SUBDIR,
                                                           bpr.REQUEST_FILE])
    assert st.ABORTED_BY_OPERATOR in st.FAILURE_STATES
    assert len(st.FAILURE_STATES) == 11, "yangi holat QO'SHILMADI"


def test_ad_nishon_OZLIGI_siyilib_ketsa_TARGET_AMBIGUOUS(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON — NISHON O'ZLIGI SIYLIB KETARDI.

    `one_click` nishonni INDEKS bo'yicha tanlaydi va XESHINI `request.json` ga yozadi;
    `ui.UiModel.start()` esa muhitni QAYTA SKANERLAYDI. Ro'yxat o'zgargan bo'lsa AYNI
    indeks BOSHQA bazani ko'rsatardi — ya'ni so'rov bitta bazaga bog'langan, hisobot esa
    boshqasining muhitini yozardi va bu JIMGINA sodir bo'lardi.
    ⚠️ Endi tasdiq O'ZLIK bo'yicha: topilmasa yurishning xulosasi DA'VO QILINMAYDI.
    """
    kok = runs(tmp_path)
    birinchi = muhit_ikki_baza(tmp_path)
    ikkinchi = X.muhit_bazali(
        tmp_path,
        X.Baza(nom="Uchinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-3")),
        X.Baza(nom="To'rtinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-4")),
    )
    model = agent(tmp_path, scan=birinchi, sleeper=yiguvchi(kok))
    navbat = [birinchi, ikkinchi]
    model.scan = lambda: navbat.pop(0) if navbat else ikkinchi

    natija, _ = bir_bosish(model, runs_root=kok, select_index=1)

    assert natija.code == bp.CODE_TARGET_AMBIGUOUS
    assert natija.waiting_for_operator is True, "tanlov OPERATORGA qaytadi"
    assert not natija.is_complete, "tasdiqlanmagan nishon bo'yicha COMPLETE YOZILMAYDI"
    assert natija.result_dir is None, \
        "qaysi bazaning muhiti ekani ISBOTLANMAGAN paketga YO'L ko'rsatilmaydi"
    assert natija.phase == bp.COLLECTOR_COMPLETE
    assert natija.state == st.METADATA_DISCOVERY, "holat YAKUNIY EMAS"
    assert any("QAYTA TASDIQLANMADI" in p for p in natija.problems)


def test_ae_indeks_siyilsa_nishon_OZLIK_boyicha_TIKLANADI(tmp_path):
    """⚠️⚠️ TASDIQ INDEKS BO'YICHA EMAS: ro'yxat TARTIBI o'zgarsa ham AYNI baza qoladi.

    Ikkinchi skanerda ro'yxat TESKARI tartibda keladi, ya'ni eski indeks BOSHQA bazani
    ko'rsatardi. Tasdiq XESH bo'yicha bo'lgani uchun indeks TIKLANADI va yurish davom
    etadi — ya'ni tuzatish «har holda to'xtatish» emas, O'ZLIKKA tayanish.
    """
    kok = runs(tmp_path)
    b1 = X.Baza(nom="Birinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-1"))
    b2 = X.Baza(nom="Ikkinchi sintetik baza", yol=str(tmp_path / "sintetik-baza-2"))
    birinchi = X.muhit_bazali(tmp_path, b1, b2)
    teskari = X.muhit_bazali(tmp_path, b2, b1)
    kutilgan_xesh = oc.target_fingerprint_of(birinchi.infobases[1])

    model = agent(tmp_path, scan=birinchi, sleeper=yiguvchi(kok))
    navbat = [birinchi, teskari]
    model.scan = lambda: navbat.pop(0) if navbat else teskari

    natija, _ = bir_bosish(model, runs_root=kok, select_index=1)

    assert natija.state == st.COMPLETE and natija.code is None
    assert model.selected_index == 0, "indeks O'ZLIK bo'yicha TIKLANDI"
    assert oc.target_fingerprint_of(model.selected_infobase()) == kutilgan_xesh
    assert sorov_hujjati(yurish_papkasi(kok))["target_fingerprint"] == kutilgan_xesh


def test_af_launcher_SHIPPED_kodda_ROSTDAN_ULANGAN_va_ikkinchi_dvigatel_YOQ():
    """⚠️⚠️ TUZATILGAN NUQSON: `launcher.py` (55 KB) ni shipped kodda HECH KIM import
    qilmasdi — faqat o'z testi. Ya'ni ishga tushirish abstraksiyasi ham, kooperativ
    bekor qilish ham AMALDA MAVJUD EMAS edi (CP2 dagi `ABORTED_BY_OPERATOR` nuqsonining
    aynan o'zi: qobiliyat e'lon qilingan, lekin yetib bo'lmaydi).

    ⚠️ IKKINCHI DVIGATEL YOZILMAGANI ham o'lchanadi: bu modulda kutish HALQASI YO'Q va
       eski maxsus halqa (`_wait_for_done_marker`) OLIB TASHLANGAN.
    """
    matn = kod_matni(ONE_CLICK_SRC)
    for nom in ("wait_for_collector", "open_infobase", "choose_exe", "CancelToken",
                "LaunchTarget"):
        assert nom in matn, f"`launcher` ning kirish nuqtasi ishlatilmayapti: {nom}"
    assert "while" not in matn, "bu modulda KUTISH HALQASI bo'lmasligi SHART"
    assert "_wait_for_done_marker" not in matn, "eski maxsus halqa QAYTIB KELDI"
    # ⚠️ Jarayon O'LDIRISH va TOZALASH naqshlari ham YO'Q bo'lib qoladi.
    for taqiq in ("taskkill", "rmtree", "terminate", "kill("):
        assert taqiq not in matn, f"taqiqlangan naqsh: {taqiq}"


def test_ag_kutish_matni_launcher_HALQASIDAN_har_olchovda_CHIQADI(tmp_path):
    """⚠️ Kutish KO'RINADI: dvigatel `launcher` da bo'lsa ham operator «osilgan emas»
    belgisini oladi, va matn SOXTA hodisa emas — u har o'lchovda AYNAN bir marta chiqadi.
    """
    kok = runs(tmp_path)
    kutishlar: list[str] = []
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path), sleeper=yiguvchi(kok))
    natija, _ = bir_bosish(model, runs_root=kok, kutish_jurnali=kutishlar)

    assert natija.state == st.COMPLETE
    assert kutishlar and all(s.strip() for s in kutishlar)
    assert len(kutishlar) == natija.waited_ticks, \
        "matn har o'lchovda AYNAN bir marta chiqadi (soxta hodisa YO'Q)"
    assert kutishlar[0] == oc.WAIT_NOTICE
    assert not redact.scan(kutishlar), "kutish matnida shubhali qiymat BO'LMASIN"


def test_ah_PARTIAL_javob_quvurga_boradi_lekin_JIMGINA_muvaffaqiyat_EMAS(tmp_path):
    """⚠️⚠️ `PARTIAL` — yig'uvchining O'Z lug'atidagi qiymat (Phase 4 `overall`).

    Faza `COLLECTOR_COMPLETE` bo'ladi (javob bor, paket to'liq), lekin operator EKRANDA
    yarim natijani YARIM deb ko'radi: faza tafsiloti yig'uvchining holatini ATAYDI.
    Hukmni esa QUVUR beradi — Phase 4 validatori yarim paketda kod `2` ni hurmat qiladi.
    """
    kok = runs(tmp_path)
    model = agent(tmp_path, scan=muhit_bitta_baza(tmp_path),
                  sleeper=yiguvchi(kok, status=bpr.STATUS_PARTIAL))
    natija, hodisalar = bir_bosish(model, runs_root=kok)

    tugallangan = [h for h in hodisalar if h.phase == bp.COLLECTOR_COMPLETE]
    assert len(tugallangan) == 1
    assert bpr.STATUS_PARTIAL in tugallangan[0].detail, \
        "yarim natija JIMGINA «qabul qilindi» bo'lib qolmasligi SHART"
    # ⚠️ Yurish quvurga BORADI (to'liq paket bilan `COMPLETE` bo'lishi mumkin), lekin
    #    ko'prik uni «tugadi» deb O'ZI ATAMAYDI: hukm quvurning holatidan keladi.
    assert natija.state in (st.COMPLETE,) + st.FAILURE_STATES
    assert natija.code is None, "bu ko'prikning rad etishi EMAS"
