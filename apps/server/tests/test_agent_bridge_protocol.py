# -*- coding: utf-8 -*-
"""KO'PRIK FAZALARI (`bridge_phase`) va YURISHGA BOG'LANGAN PROTOKOL (`bridge_protocol`).

⚠️⚠️ BU TESTLAR 1C GA TEGMAYDI va tegishi ham mumkin emas: bu mashinada 1C UMUMAN
     O'RNATILMAGAN. Shu bois ular MANTIQNI va SHARTNOMANI isbotlaydi, yig'uvchining
     haqiqiy xulqi haqida esa HECH QANDAY da'vo qilmaydi.

ISBOTLANADIGAN INVARIANTLAR:
  · 12 faza, `PHASE_TO_STATE` TO'LIQ va YAGONA; diapazon mavjud holatlardan CHIQMAYDI va
    diapazondagi har holat `START` dan ERISHIB BO'LADIGAN;
  · «spinner-only» faza YO'Q: har fazada bo'sh bo'lmagan operator matni bor;
  · mavjud holat mashinasi O'ZGARMAGAN: 12 normal + 11 yiqilish holati;
  · nosozlik UCHLIGI: har kod uchun kod + operator matni + keyingi qadam, hammasi bo'sh
    emas, kod shakli `[A-Z][A-Z0-9_]*`;
  · YURISHGA BOG'LANGANLIK: javob boshqa yurishdan, boshqa bir martalik belgidan, boshqa
    yig'uvchi versiyasidan yoki boshqa nishondan kelsa — RAD, har biri O'Z KODI bilan;
  · tugallanish belgisi YO'Q bo'lsa — RAD; chiqish so'rovdan OLDIN yozilgan bo'lsa — RAD;
  · shakl darvozasi: noma'lum kalit RAD, tushib qolgan kalit RAD, JSON soni/booleani RAD;
  · `target_fingerprint` XOM `locator` ni OSHKOR QILMAYDI;
  · yurish papkasi BO'SH bo'lmasa — yurish BOSHLANMAYDI va hech narsa O'CHIRILMAYDI;
  · manbada WILDCARD O'CHIRISH naqshi YO'Q (statik darvoza);
  · determinizm: bir xil hujjat — AYNAN bir xil baytlar.

ATAYLAB SINALMAYDI:
  · 1C ning haqiqiy xulqi, `.epf` ning ishlashi va avtomatik ishga tushirish yo'li — ular
    `UNVERIFIED_ON_REAL_1C` va bu yerda ularga da'vo qilinmaydi;
  · yurish papkasining STANDART joyi (`%LOCALAPPDATA%`) — haqiqiy foydalanuvchi papkasiga
    yozib ko'rilmaydi; testlar DOIM `runs_root` ni ANIQ beradi.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.services.discovery_1c import redact as redaction
from app.services.discovery_1c.probe import PROBE_CATALOG
from app.services.discovery_1c.runtime_bundle import (MODE_APPROVED_PROBES,
                                                      MODE_METADATA_ONLY, MODES,
                                                      OVERALL_FAILED, OVERALL_PARTIAL,
                                                      OVERALL_SUCCESS, REQUIRED_FILES)
from app.services.discovery_agent import bridge_phase as bp
from app.services.discovery_agent import bridge_protocol as pr
from app.services.discovery_agent import states as st
from app.services.discovery_agent.status import RUN_ID_RE as STATUS_RUN_ID_RE

T_REQ = "2026-10-01T09:00:00+06:00"
T_START = "2026-10-01T09:00:05+06:00"
T_END = "2026-10-01T09:01:05+06:00"
T_DONE = "2026-10-01T09:01:06+06:00"
#: ⚠️ So'rovdan OLDINGI vaqt — eski natijani qayta ishlatish urinishi.
T_OLD = "2026-09-30T23:59:59+06:00"

COLLECTOR_NAME = "BinOS1CCollector"
COLLECTOR_VERSION = "0.1.0-UNVERIFIED"

#: ⚠️ SINTETIK `locator`: haqiqiy bazaga ishora qilmaydi, lekin SIR ko'rinishida —
#: xeshning uni oshkor qilmasligini isbotlash uchun aynan shunday bo'lishi kerak.
LOCATOR = r"C:\Fayzan\baza\1Cv8.1CD"

AGENT_DIR = pathlib.Path(bp.__file__).resolve().parent
YANGI_MODULLAR: tuple[pathlib.Path, ...] = (
    AGENT_DIR / "bridge_phase.py", AGENT_DIR / "bridge_protocol.py",
)


# ══════════════════════════════════════════════════════════════════════════════════════════
# FIKSTURALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def _fingerprint() -> str:
    return pr.target_fingerprint("file", "Fayzan savdo", LOCATOR)


def _identity() -> pr.RunIdentity:
    return pr.new_run(now=T_REQ)


def _request(identity: pr.RunIdentity | None = None, **kw) -> dict:
    ident = identity or _identity()
    arg = dict(
        output_dir="C:\\BinOS\\runs\\out",
        collector_name=COLLECTOR_NAME,
        collector_version=COLLECTOR_VERSION,
        target_fingerprint=_fingerprint(),
        mode=MODE_METADATA_ONLY,
    )
    arg.update(kw)
    return pr.build_request(ident, **arg)


def _response(req: dict, **kw) -> dict:
    doc = {
        "response_version": pr.RESPONSE_VERSION,
        "run_id": req["run_id"],
        "nonce": req["nonce"],
        "collector": {"name": COLLECTOR_NAME, "version": COLLECTOR_VERSION},
        "target_fingerprint": req["target_fingerprint"],
        "status": pr.STATUS_OK,
        "started_at": T_START,
        "finished_at": T_END,
        "notes": [],
    }
    doc.update(kw)
    return doc


def _done(req: dict, **kw) -> dict:
    doc = {
        "done_version": pr.DONE_VERSION,
        "run_id": req["run_id"],
        "nonce": req["nonce"],
        "written_at": T_DONE,
    }
    doc.update(kw)
    return doc


def _rad(code: str, fn, *a, **kw) -> pr.BridgeProtocolError:
    """Chaqiruv AYNAN shu kod bilan rad etilishi SHART."""
    with pytest.raises(pr.BridgeProtocolError) as e:
        fn(*a, **kw)
    assert e.value.code == code, (
        f"kutilgan kod {code!r}, kelgani {e.value.code!r} — har rad etish sababi O'Z "
        f"kodini olishi SHART, aks holda operator nima qilishini bilmaydi")
    return e.value


#: Satr oxiridagi izohlar va docstringlar OLIB TASHLANGAN manba (statik darvozalar uchun).
#: ⚠️ NEGA KERAK: bu modullarning izohlari ATAYLAB «o'chirish YO'Q» deb yozadi; darvoza
#:    IZOHNI emas, BAJARILADIGAN KODNI o'lchashi kerak — aks holda u o'z hujjatidan
#:    yiqilardi.
_DOCSTRING_RE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')


def _kod_faqat(p: pathlib.Path) -> str:
    matn = _DOCSTRING_RE.sub('""', p.read_text(encoding="utf-8"))
    return "\n".join(satr.split("#", 1)[0] for satr in matn.splitlines())


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA A — FAZALAR va MOSLIK
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_fazalar_AYNAN_12_ta_va_nomlari_shartnomadagi():
    assert len(bp.BRIDGE_PHASES) == 12 and len(set(bp.BRIDGE_PHASES)) == 12
    assert set(bp.BRIDGE_PHASES) == {
        "DETECTING_1C", "NO_1C", "DISCOVERING_INFOBASES", "SELECT_TARGET",
        "PREPARING_COLLECTOR", "LAUNCHING_1C", "WAITING_FOR_COLLECTOR",
        "COLLECTOR_COMPLETE", "COLLECTOR_FAILED", "INGESTING", "ANALYZING", "COMPLETE",
    }


def test_har_faza_AYNAN_bir_mavjud_holatga_mos():
    """⚠️ Moslik TO'LIQ (har faza) va YAGONA (bitta holat) bo'lishi SHART: faza ikki
    holatga tushsa, `agent_status.json` ga nima yozilishini KOD hal qilardi."""
    assert set(bp.PHASE_TO_STATE) == set(bp.BRIDGE_PHASES)
    for faza in bp.BRIDGE_PHASES:
        holat = bp.phase_state(faza)
        assert isinstance(holat, str) and st.is_known(holat), faza


def test_moslik_DIAPAZONI_mavjud_holatlardan_chiqmaydi():
    """⚠️ Yangi holat QO'SHILMAYDI: ko'prik qatlami ikkinchi holat mashinasi EMAS."""
    chetda = sorted(set(bp.PHASE_TO_STATE.values()) - set(st.STATES))
    assert not chetda, f"moslik mavjud bo'lmagan holatga ishora qiladi: {chetda}"


def test_moslik_diapazonidagi_har_holat_START_dan_ERISHIB_BOLADIGAN():
    """⚠️ Erishib bo'lmaydigan holatga faza bog'lash — o'lik yo'l: operator hech qachon
    ko'rmaydigan matn yozilardi va u eskirib ketardi."""
    korilgan = {st.START}
    navbat = [st.START]
    while navbat:
        joriy = navbat.pop()
        for keyingi in st.TRANSITIONS[joriy]:
            if keyingi not in korilgan:
                korilgan.add(keyingi)
                navbat.append(keyingi)
    erishilmagan = sorted(set(bp.PHASE_TO_STATE.values()) - korilgan)
    assert not erishilmagan, f"faza erishib bo'lmaydigan holatga bog'langan: {erishilmagan}"


def test_har_fazada_operator_matni_BOR_spinner_only_faza_YOQ():
    assert set(bp.PHASE_TEXT) == set(bp.BRIDGE_PHASES)
    for faza in bp.BRIDGE_PHASES:
        matn = bp.phase_text(faza)
        assert isinstance(matn, str) and matn.strip(), faza
        assert len(matn.strip()) >= 20, f"{faza}: matn operatorga hech narsa aytmaydi"


def test_faza_matnlarida_SIR_YOQ():
    """⚠️ Matnlar `agent_status.notes` ga tushishi mumkin — ularda yo'l ham, misol kirish
    ma'lumoti ham BO'LMASLIGI kerak (fail-closed)."""
    topilgan = redaction.scan(dict(bp.PHASE_TEXT))
    assert not topilgan, f"faza matnida shubhali qiymat: {[str(f) for f in topilgan]}"
    uchlik = {c: [t.operator, t.next_action] for c, t in bp.FAILURE_TRIPLE.items()}
    topilgan = redaction.scan(uchlik)
    assert not topilgan, f"uchlik matnida shubhali qiymat: {[str(f) for f in topilgan]}"


def test_mavjud_holat_mashinasi_OZGARMAGAN():
    """⚠️⚠️ REGRESSIYA DARVOZASI: ko'prik qatlami holat QO'SHMAYDI va OLIB TASHLAMAYDI."""
    assert len(st.NORMAL_STATES) == 12, "normal holatlar AYNAN 12 ta bo'lib qoladi"
    assert len(st.FAILURE_STATES) == 11, "yiqilish holatlari AYNAN 11 ta bo'lib qoladi"


def test_yiqilish_fazalari_yiqilish_holatiga_tushadi():
    assert bp.is_failure_phase(bp.NO_1C) and bp.is_failure_phase(bp.COLLECTOR_FAILED)
    assert not bp.is_failure_phase(bp.COMPLETE)
    assert bp.is_terminal_phase(bp.COMPLETE) and bp.is_terminal_phase(bp.NO_1C)
    assert not bp.is_terminal_phase(bp.INGESTING)
    # ⚠️ «1C yo'q» va «1C bor, javob yo'q» ARALASHMAYDI.
    assert bp.phase_state(bp.NO_1C) == st.FAILED_NO_1C
    assert bp.phase_state(bp.COLLECTOR_FAILED) == st.FAILED_COLLECTOR_UNAVAILABLE


def test_phases_for_state_ikki_fazani_ham_qaytaradi():
    """⚠️ Ko'p-bittaga moslik RUXSAT ETILGAN va u YO'QOLMASLIGI kerak: ro'yxatni o'qish va
    tanlashni kutish — operator uchun ikki boshqa ekran."""
    assert bp.phases_for_state(st.TARGET_SELECTION) == (bp.DISCOVERING_INFOBASES,
                                                        bp.SELECT_TARGET)
    assert bp.phases_for_state(st.METADATA_DISCOVERY) == (bp.LAUNCHING_1C,
                                                          bp.WAITING_FOR_COLLECTOR,
                                                          bp.COLLECTOR_COMPLETE)
    # ⚠️ Fazasi YO'Q holat ham bor va bu ATAYLAB (ko'prik 1C bilan almashuvni ta'riflaydi).
    assert bp.phases_for_state(st.REPORT) == ()


def test_notanish_faza_va_holat_ISTISNO_fail_closed():
    with pytest.raises(bp.BridgePhaseError):
        bp.phase_state("WAITING")
    with pytest.raises(bp.BridgePhaseError):
        bp.phase_text("")
    with pytest.raises(bp.BridgePhaseError):
        bp.phases_for_state("FAILED_EVERYTHING")
    assert not bp.is_phase("WAITING") and bp.is_phase(bp.INGESTING)


def test_epf_ikkilik_fayli_QURILGAN_deb_ATALMAYDI():
    """⚠️⚠️ Holat nomi AYNAN `EPF_SOURCE_READY`: manba matni tayyor, IKKILIK `.epf` ni
    operator 1C konfiguratorida yig'adi. «Qurildi» degan da'vo ISBOTLANMAGAN bo'lardi."""
    assert bp.EPF_SOURCE_READY == "EPF_SOURCE_READY"
    assert bp.AUTOMATIC_LAUNCH_VERIFICATION == "UNVERIFIED_ON_REAL_1C"
    hujjat = (bp.__doc__ or "") + (pr.__doc__ or "")
    assert "EPF_SOURCE_READY" in hujjat and "COM" in hujjat


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA A — NOSOZLIK UCHLIGI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_arxitektor_bergan_TOQQIZ_kod_bor_va_ajralib_turadi():
    assert bp.ARCHITECT_CODES == (
        "COLLECTOR_EXECUTION_NOT_ALLOWED", "STALE_OUTPUT", "NONCE_MISMATCH",
        "WRONG_COLLECTOR_VERSION", "PARTIAL_PACKAGE", "OUTPUT_PREDATES_REQUEST",
        "OPERATOR_CANCELLED", "RUN_DIR_NOT_EMPTY", "TARGET_AMBIGUOUS",
    )
    assert len(bp.ARCHITECT_CODES) == 9
    assert not set(bp.ARCHITECT_CODES) & set(bp.DERIVED_CODES)


def test_har_kod_UCHLIK_oladi_va_kod_shakli_togri():
    assert set(bp.FAILURE_TRIPLE) == set(bp.BRIDGE_CODES)
    for kod in bp.BRIDGE_CODES:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", kod), kod
        u = bp.failure_triple(kod)
        assert u.code == kod
        assert u.operator.strip() and u.next_action.strip(), kod
        assert len(u.next_action.strip()) >= 20, f"{kod}: keyingi qadam YO'Q darajada qisqa"


def test_notanish_kod_uchun_UMUMIY_xato_QAYTARILMAYDI():
    with pytest.raises(bp.BridgePhaseError):
        bp.failure_triple("SOMETHING_WENT_WRONG")


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B — NISHON XESHI (XOM `locator` OSHKOR QILINMAYDI)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_target_fingerprint_XOM_locatorni_OSHKOR_QILMAYDI():
    """⚠️⚠️ ENG MUHIM DARVOZA: `locator` sir bo'lishi mumkin (fayl yo'li, UNC, server
    ulanish satri) — protokolga u YOZILMAYDI, faqat xesh ketadi."""
    fp = pr.target_fingerprint("file", "Fayzan savdo", LOCATOR)
    assert re.fullmatch(r"[0-9a-f]{64}", fp)
    assert LOCATOR not in fp
    for bolak in ("Fayzan", "1Cv8.1CD", "baza", "C:"):
        assert bolak not in fp, f"xeshda `locator` bo'lagi ko'rinib qoldi: {bolak}"
    # ⚠️ So'rov hujjatining BUTUN matnida ham xom `locator` BO'LMAYDI.
    matn = pr.dump_request(_request(target_fingerprint=fp))
    assert LOCATOR not in matn and "1Cv8.1CD" not in matn
    # ⚠️ Rad etish MATNIDA ham qiymat ko'rsatilmaydi.
    xato = _rad(pr.bp.CODE_BRIDGE_SHAPE_INVALID, pr.target_fingerprint, "file", "x", "")
    assert LOCATOR not in str(xato)


def test_fingerprint_locatorga_SEZGIR_va_DETERMINISTIK():
    a = pr.target_fingerprint("file", "Baza", LOCATOR)
    b = pr.target_fingerprint("file", "Baza", LOCATOR + "2")
    assert a != b, "ikki boshqa baza bir xil xesh olmasligi kerak"
    assert a == pr.target_fingerprint("file", "Baza", LOCATOR), "xesh DETERMINISTIK"
    assert pr.target_fingerprint("server", "Baza", LOCATOR) != a, "tur ham xeshga kiradi"


def test_notanish_nishon_turi_RAD():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.target_fingerprint, "cloud", "Baza", LOCATOR)


def test_bir_nechta_nishon_mos_kelsa_TARGET_AMBIGUOUS():
    """⚠️ Agent o'zi tanlamaydi: noto'g'ri baza tanlansa butun hisobot noto'g'ri bo'ladi."""
    a, b = _fingerprint(), pr.target_fingerprint("file", "Ikkinchi", LOCATOR)
    assert pr.assert_unique_target([a, a]) == a
    _rad(bp.CODE_TARGET_AMBIGUOUS, pr.assert_unique_target, [a, b])


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B — SO'ROV
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_new_run_secrets_bilan_va_vaqt_KIRISHDAN():
    i1, i2 = _identity(), _identity()
    assert i1.run_id != i2.run_id and i1.nonce != i2.nonce, "qiymatlar TAXMIN QILINMASIN"
    assert len(i1.nonce) >= 32, "nonce kamida 32 hex belgi"
    assert re.fullmatch(r"[0-9a-f]+", i1.run_id) and re.fullmatch(r"[0-9a-f]+", i1.nonce)
    assert i1.requested_at == T_REQ, "vaqt KIRISHDAN keladi, modul soatni o'qimaydi"
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.new_run, now="hozir")


def test_togri_sorov_OTADI_va_kalitlari_SHARTNOMADAGI():
    req = _request()
    assert set(req) == pr.REQUEST_KEYS == {
        "request_version", "run_id", "nonce", "requested_at", "output_dir",
        "expected_collector", "target_fingerprint", "mode", "allowed_probes", "notes",
    }
    assert req["request_version"] == "binos-bridge-request-v1"
    assert set(req["expected_collector"]) == {"name", "version"}
    assert pr.validate_request(req) is req


def test_sorovda_notanish_kalit_RAD_va_tushib_qolgan_kalit_ham_RAD():
    req = _request()
    buzuq = dict(req, qoshimcha="x")
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, buzuq)
    kam = {k: v for k, v in req.items() if k != "mode"}
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, kam)


def test_sorovda_JSON_SONI_va_BOOLEANI_RAD():
    """⚠️ Sanoq MATN: `0000123` soni `123` bo'lib qoladi, boolean esa uchinchi holatni
    JIMGINA yo'q qiladi."""
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, dict(req, notes=[1]))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request,
         dict(req, expected_collector={"name": COLLECTOR_NAME, "version": 1}))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, dict(req, notes=[True]))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request,
         dict(req, allowed_probes=[0]))


def test_sorov_versiyasi_nonce_va_xesh_SHAKLI_tekshiriladi():
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request,
         dict(req, request_version="binos-bridge-request-v2"))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, dict(req, nonce="qisqa"))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request,
         dict(req, target_fingerprint="ZZZ"))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, dict(req, run_id="../boshqa"))


def test_rejim_va_zond_royxati_YOPIQ_lugatdan():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, _request, mode="FULL_DUMP")
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, _request,
         mode=MODE_APPROVED_PROBES, allowed_probes=["o_zboshimcha_so_rov"])
    # ⚠️ `METADATA_ONLY` + zond — O'Z-O'ZIGA ZID hujjat.
    birinchi = sorted(PROBE_CATALOG)[0]
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, _request,
         mode=MODE_METADATA_ONLY, allowed_probes=[birinchi])
    ok = _request(mode=MODE_APPROVED_PROBES, allowed_probes=[birinchi, birinchi])
    assert ok["allowed_probes"] == [birinchi], "TARTIBLANGAN va TAKRORSIZ (determinizm)"
    assert set(MODES) == {MODE_METADATA_ONLY, MODE_APPROVED_PROBES}


def test_sorovdagi_notes_SIR_darvozasidan_otadi():
    """⚠️ `notes` — YAGONA erkin matn maydoni, ya'ni sir aynan shu yerdan sizib chiqadi."""
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, _request, notes=["Srvr=buxgalteriya;Ref=savdo"])
    assert _request(notes=["qo'lda boshlandi"])["notes"] == ["qo'lda boshlandi"]


def test_sorov_matni_DETERMINISTIK_va_UTF8():
    req = _request()
    assert pr.dump_request(req) == pr.dump_request(dict(reversed(list(req.items()))))
    matn = pr.dump_request(req)
    assert matn.endswith("\n") and ": " not in matn, "ortiqcha probel YO'Q"
    assert json.loads(matn) == req
    assert matn.encode("utf-8").decode("utf-8") == matn


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B/C — JAVOB: HAR RAD ETISH SABABI O'Z KODI BILAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_togri_javob_va_belgi_OTADI():
    req = _request()
    natija = pr.accept_collector_output(request=req, response=_response(req),
                                        done=_done(req), bundle_files=REQUIRED_FILES)
    assert natija.status == pr.STATUS_OK
    assert natija.phase == bp.COLLECTOR_COMPLETE and natija.code is None
    assert bp.phase_state(natija.phase) == st.METADATA_DISCOVERY


def test_javob_YOQ_bolsa_RESPONSE_MISSING():
    req = _request()
    _rad(bp.CODE_RESPONSE_MISSING, pr.accept_collector_output,
         request=req, response=None, done=_done(req), bundle_files=REQUIRED_FILES)


def test_run_id_mos_emas_STALE_OUTPUT():
    req = _request()
    boshqa = _request()
    _rad(bp.CODE_STALE_OUTPUT, pr.validate_response,
         _response(req, run_id=boshqa["run_id"]), request=req)


def test_nonce_mos_emas_NONCE_MISMATCH():
    req = _request()
    boshqa = _request()
    _rad(bp.CODE_NONCE_MISMATCH, pr.validate_response,
         _response(req, nonce=boshqa["nonce"]), request=req)


def test_yiguvchi_versiyasi_mos_emas_WRONG_COLLECTOR_VERSION():
    req = _request()
    _rad(bp.CODE_WRONG_COLLECTOR_VERSION, pr.validate_response,
         _response(req, collector={"name": COLLECTOR_NAME, "version": "0.0.9"}),
         request=req)
    _rad(bp.CODE_WRONG_COLLECTOR_VERSION, pr.validate_response,
         _response(req, collector={"name": "BoshqaYiguvchi",
                                   "version": COLLECTOR_VERSION}), request=req)


def test_nishon_mos_emas_TARGET_FINGERPRINT_MISMATCH():
    """⚠️ Bu `STALE_OUTPUT` EMAS: fayl eski emas, NISHON boshqa — operatorning qadami ham
    boshqa (1C da bazani moslash)."""
    req = _request()
    boshqa = pr.target_fingerprint("file", "Boshqa baza", LOCATOR)
    _rad(bp.CODE_TARGET_FINGERPRINT_MISMATCH, pr.validate_response,
         _response(req, target_fingerprint=boshqa), request=req)


def test_javobda_notanish_kalit_notanish_holat_va_SON_RAD():
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         dict(_response(req), ortiqcha="x"), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req, status="DONE"), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req, notes=[0]), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req, response_version="binos-bridge-response-v2"), request=req)
    # ⚠️ Tugash vaqti boshlanishdan OLDIN bo'lishi mumkin emas.
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req, started_at=T_END, finished_at=T_START), request=req)


def test_nosoz_SOROVGA_nisbatan_solishtirish_BOSHLANMAYDI():
    """⚠️ Avval so'rovning O'ZI yaroqli bo'lishi kerak: nosoz so'rov bilan solishtirish
    ma'nosiz va u «javob to'g'ri» degan yolg'on xulosaga olib kelardi."""
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req), request=dict(req, mode="FULL_DUMP"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B/C — TUGALLANISH BELGISI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_bridge_done_YOQ_bolsa_DONE_MARKER_MISSING():
    """⚠️⚠️ `response.json` ning O'ZI yozilib bo'lgani bilinmaydi — yarim yozilgan fayl ham
    diskda turadi. Shu bois belgi YO'Q bo'lsa javob QABUL QILINMAYDI."""
    req = _request()
    _rad(bp.CODE_DONE_MARKER_MISSING, pr.accept_collector_output,
         request=req, response=_response(req), done=None, bundle_files=REQUIRED_FILES)
    _rad(bp.CODE_DONE_MARKER_MISSING, pr.validate_done_marker, None, request=req)


def test_chiqish_sorovdan_OLDIN_yozilgan_OUTPUT_PREDATES_REQUEST():
    req = _request()
    _rad(bp.CODE_OUTPUT_PREDATES_REQUEST, pr.validate_done_marker,
         _done(req, written_at=T_OLD), request=req)
    _rad(bp.CODE_OUTPUT_PREDATES_REQUEST, pr.accept_collector_output,
         request=req, response=_response(req), done=_done(req, written_at=T_OLD),
         bundle_files=REQUIRED_FILES)


def test_belgidagi_run_id_va_nonce_ham_solishtiriladi():
    req, boshqa = _request(), _request()
    _rad(bp.CODE_STALE_OUTPUT, pr.validate_done_marker,
         _done(req, run_id=boshqa["run_id"]), request=req)
    _rad(bp.CODE_NONCE_MISMATCH, pr.validate_done_marker,
         _done(req, nonce=boshqa["nonce"]), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_done_marker,
         _done(req, done_version="binos-bridge-done-v2"), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_done_marker,
         dict(_done(req), ortiqcha="x"), request=req)


def test_belgi_Phase_4_manifesti_bilan_ARALASHMAYDI():
    """⚠️⚠️ Phase 4 paketining `manifest.json` i `bundle/` ichida va u O'ZGARMAYDI; ko'prik
    belgisi — QO'SHIMCHA qatlam, boshqa nomda."""
    assert pr.DONE_FILE == "bridge_done.json"
    assert pr.DONE_FILE not in REQUIRED_FILES and "manifest.json" in REQUIRED_FILES
    assert len({pr.REQUEST_FILE, pr.RESPONSE_FILE, pr.DONE_FILE, pr.CANCEL_FILE}) == 4


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B/C — PAKET TO'LIQLIGI va JAVOB HOLATLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_paket_toliq_emas_PARTIAL_PACKAGE():
    req = _request()
    yarim = tuple(n for n in REQUIRED_FILES if n != "errors.json")
    _rad(bp.CODE_PARTIAL_PACKAGE, pr.accept_collector_output,
         request=req, response=_response(req), done=_done(req), bundle_files=yarim)
    xato = _rad(bp.CODE_PARTIAL_PACKAGE, pr.validate_package_complete, yarim)
    assert "errors.json" in str(xato), "yetishmagan fayl NOMI aytilsin (u sir emas)"
    assert pr.validate_package_complete(REQUIRED_FILES) == REQUIRED_FILES


def test_yiguvchi_yiqilgan_javob_RAD_ETILMAYDI_balki_FAZA_bilan_qaytadi():
    """⚠️ «Javob yo'q» va «javob bor, lekin yig'uvchi yiqildi» BOSHQA narsa: birinchisida
    yig'uvchi umuman ishlamagan, ikkinchisida sabab paketning xato hujjatida."""
    req = _request()
    natija = pr.accept_collector_output(request=req,
                                        response=_response(req, status=pr.STATUS_FAILED),
                                        done=_done(req), bundle_files=())
    assert natija.status == pr.STATUS_FAILED and natija.code is None
    assert natija.phase == bp.COLLECTOR_FAILED
    assert bp.phase_state(natija.phase) == st.FAILED_COLLECTOR_UNAVAILABLE


def test_bekor_qilingan_javob_OPERATOR_CANCELLED_kodini_oladi():
    """⚠️ Bekor qilish KOOPERATIV: agent kutishni to'xtatadi, jarayon O'LDIRILMAYDI."""
    req = _request()
    natija = pr.accept_collector_output(request=req,
                                        response=_response(req,
                                                           status=pr.STATUS_CANCELLED),
                                        done=_done(req), bundle_files=())
    assert natija.status == pr.STATUS_CANCELLED
    assert natija.code == bp.CODE_OPERATOR_CANCELLED
    uchlik = bp.failure_triple(natija.code)
    assert "o'zingiz yoping" in uchlik.next_action


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B/C — YURISH PAPKASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_standart_yurish_ildizi_LOCALAPPDATA_ostida(monkeypatch, tmp_path):
    monkeypatch.setenv(pr.LOCALAPPDATA_ENV, str(tmp_path))
    ildiz = pr.resolve_runs_root()
    assert ildiz == tmp_path / "BinOS" / "Discovery" / "runs"
    assert pr.RUNS_SUBPATH == ("BinOS", "Discovery", "runs")


def test_LOCALAPPDATA_YOQ_bolsa_FAIL_CLOSED_RUNS_ROOT_UNKNOWN(monkeypatch):
    """⚠️⚠️ O'zgaruvchi yo'qligi HECH QACHON ruxsat bermasin: zaxira yo'l manba daraxtiga
    yoki joriy papkaga yozishga olib kelardi."""
    monkeypatch.delenv(pr.LOCALAPPDATA_ENV, raising=False)
    xato = _rad(bp.CODE_RUNS_ROOT_UNKNOWN, pr.resolve_runs_root)
    assert pr.RUNS_DIR_OPTION in str(xato), "operatorga almashtirish kaliti aytilsin"
    monkeypatch.setenv(pr.LOCALAPPDATA_ENV, "   ")
    _rad(bp.CODE_RUNS_ROOT_UNKNOWN, pr.resolve_runs_root)


def test_yurish_papkasi_FAQAT_OZI_yaratiladi_va_fayllari_NISBIY(tmp_path):
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    assert d == tmp_path / i.run_id and d.is_dir()
    assert not any(d.iterdir()), "yangi papka BO'SH bo'lishi kerak"
    # ⚠️ Umumiy global natija fayli YO'Q: hamma nom NISBIY va papka ichida qoladi.
    for nom in (pr.REQUEST_FILE, pr.RESPONSE_FILE, pr.DONE_FILE, pr.CANCEL_FILE):
        assert "/" not in nom and "\\" not in nom and ".." not in nom
    assert pr.request_path(d).parent == d and pr.done_marker_path(d).parent == d
    assert pr.response_path(d).parent == d and pr.cancel_marker_path(d).parent == d


def test_BOSH_BOLMAGAN_papkada_yurish_BOSHLANMAYDI_va_fayl_OCHIRILMAYDI(tmp_path):
    """⚠️⚠️ Avtomatik tozalash — eng xavfli naqsh: bir kun noto'g'ri papka berilsa, u
    operatorning fayllarini olib ketardi."""
    i = _identity()
    d = tmp_path / i.run_id
    d.mkdir(parents=True)
    begona = d / "operator_qaydlari.txt"
    begona.write_text("tegilmasin", encoding="utf-8")
    _rad(bp.CODE_RUN_DIR_NOT_EMPTY, pr.prepare_run_dir, i.run_id, runs_root=tmp_path)
    assert begona.exists() and begona.read_text(encoding="utf-8") == "tegilmasin"


def test_yol_belgili_run_id_papkadan_CHIQIB_ketmaydi(tmp_path):
    for yomon in ("../boshqa", "a/b", "a\\b", "", "."):
        _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.run_dir_for, yomon, runs_root=tmp_path)


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B/C — O'QISH / YOZISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_sorov_UTF8_BOMSIZ_va_LF_bilan_yoziladi(tmp_path):
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    req = _request(i)
    p = pr.write_request(d, req)
    xom = p.read_bytes()
    assert not xom.startswith(b"\xef\xbb\xbf"), "YOZISHDA BOM QO'YILMAYDI (determinizm)"
    assert b"\r\n" not in xom, "satr oxiri LF bo'lishi kerak"
    assert xom.decode("utf-8") == pr.dump_request(req)
    # ⚠️ Mavjud fayl USTIGA yozilmaydi: boshqa yurishning so'rovi jimgina almashmaydi.
    with pytest.raises(FileExistsError):
        pr.write_request(d, req)


def test_nosoz_sorov_DISKKA_CHIQMAYDI(tmp_path):
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.write_request, d,
         dict(_request(i), mode="FULL_DUMP"))
    assert not any(d.iterdir()), "nosoz hujjat yozilib qolmasin"


def test_YOQ_fayl_None_BUZUQ_fayl_SHAPE_INVALID(tmp_path):
    """⚠️ «Yo'q» va «buzuq» AJRATILGAN: yo'qligi — yig'uvchi tugatmagan, buzuqligi — fayl
    bor, lekin o'qilmaydi. Operatorning qadami ikkisida boshqa."""
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    assert pr.read_response(d) is None and pr.read_done_marker(d) is None
    pr.done_marker_path(d).write_text("{ buzuq", encoding="utf-8")
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.read_done_marker, d)


def test_1C_BOM_bilan_yozsa_ham_OQILADI(tmp_path):
    """⚠️⚠️ 1C JSON ni ko'pincha BOM bilan yozadi; `utf-8` o'qishda BOM birinchi kalitni
    buzadi va to'g'ri ishlagan yig'uvchining natijasi YO'QOLARDI."""
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    req = _request(i)
    pr.response_path(d).write_text(json.dumps(_response(req), ensure_ascii=False),
                                   encoding="utf-8-sig")
    oqilgan = pr.read_response(d)
    assert pr.validate_response(oqilgan, request=req) == oqilgan


def test_oxirigacha_yurish_fayllar_orqali(tmp_path):
    """Uchiga-uch: so'rov yoziladi, javob va belgi qo'yiladi, darvoza QABUL qiladi."""
    i = _identity()
    d = pr.prepare_run_dir(i.run_id, runs_root=tmp_path)
    req = _request(i)
    pr.write_request(d, req)
    pr.response_path(d).write_text(pr.dumps(_response(req)), encoding="utf-8")
    pr.done_marker_path(d).write_text(pr.dumps(_done(req)), encoding="utf-8")
    natija = pr.accept_collector_output(request=req, response=pr.read_response(d),
                                        done=pr.read_done_marker(d),
                                        bundle_files=REQUIRED_FILES)
    assert natija.phase == bp.COLLECTOR_COMPLETE


# ══════════════════════════════════════════════════════════════════════════════════════════
# QAROR 5, 6 — KREDENSIAL va AVTOMATIK ISHGA TUSHIRISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_avtomatik_ishga_tushirish_tasdiqsiz_BOSHLANMAYDI():
    """⚠️⚠️ FAIL-CLOSED: bu yo'l haqiqiy 1C da SINALMAGAN, shu bois u standart BO'LMAYDI."""
    _rad(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, pr.assert_launch_allowed,
         operator_confirmed=False)
    _rad(bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED, pr.assert_launch_allowed,
         operator_confirmed="ha")
    assert pr.assert_launch_allowed(operator_confirmed=True) is None


def test_parol_kaliti_buyruqqa_TUSHMAYDI_va_darvoza_IKKINCHI_NUSXADA_yozilmagan():
    """⚠️⚠️ Mavjud `collector_bridge._assert_no_credentials` QAYTA ISHLATILADI: ikki nusxa
    bir kun bir-biridan ajralib ketardi."""
    from app.services.discovery_agent import collector_bridge as cb

    yaxshi = ("1cv8.exe", "ENTERPRISE", "/FC:\\baza", "/Execute", "c.epf", "/Cout")
    assert pr.assert_launch_command(yaxshi) == yaxshi
    for yomon in (("1cv8.exe", "/FC:\\baza", "/Pmaxfiy"),
                  ("1cv8.exe", "/FC:\\baza", "/Nkassir")):
        with pytest.raises(cb.BridgeError):
            pr.assert_launch_command(yomon)
    # ⚠️ IJOBIY darvoza: nishon kaliti AYNAN bitta va faqat `/F` yoki `/S`.
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.assert_launch_command,
         ("1cv8.exe", "ENTERPRISE", "/Execute", "c.epf"))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.assert_launch_command,
         ("1cv8.exe", "/FC:\\baza", "/Ssrv/ib"))
    assert pr.ALLOWED_TARGET_SWITCHES == ("/F", "/S")
    assert pr.assert_launch_command(("1cv8.exe", "/Ssrv/ib")) == ("1cv8.exe", "/Ssrv/ib")


# ══════════════════════════════════════════════════════════════════════════════════════════
# STATIK DARVOZALAR — O'CHIRISH YO'Q, TARMOQ YO'Q, COM YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_manbada_WILDCARD_OCHIRISH_naqshi_YOQ():
    """⚠️⚠️ Bu modullarda birorta o'chirish naqshi BO'LMASLIGI kerak: na papka daraxtini,
    na yolg'iz faylni. «Avval papkani bo'shataman» naqshi bir kun operatorning fayllarini
    olib ketardi."""
    taqiq = (r"rmtree", r"shutil", r"os\.remove", r"os\.unlink", r"os\.rmdir",
             r"\.unlink\s*\(", r"\.rmdir\s*\(", r"glob\s*\(", r"rglob", r"iglob",
             r"\*\.json")
    topildi: dict[str, list[str]] = {}
    for p in YANGI_MODULLAR:
        kod = _kod_faqat(p)
        for t in taqiq:
            if re.search(t, kod):
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"o'chirish/wildcard naqshi topildi: {topildi}"


def test_manbada_COM_tarmoq_va_jarayon_oldirish_YOQ():
    """⚠️ COM avtomatizatsiyasi QO'SHILMAYDI, tarmoq YO'Q, jarayonni KENG O'LDIRISH YO'Q."""
    taqiq = (r"win32com", r"pythoncom", r"Dispatch\s*\(", r"CreateObject",
             r"^\s*import\s+socket", r"urlopen", r"taskkill", r"\.kill\s*\(",
             r"\.terminate\s*\(", r"TerminateProcess", r"^\s*import\s+subprocess")
    topildi: dict[str, list[str]] = {}
    for p in YANGI_MODULLAR:
        kod = _kod_faqat(p)
        for t in taqiq:
            if re.search(t, kod, re.M):
                topildi.setdefault(t, []).append(p.name)
    assert not topildi, f"taqiqlangan naqsh topildi: {topildi}"


def test_sanoq_serializatori_QAYTA_ISHLATILGAN_ikkinchi_nusxa_YOQ():
    """⚠️ `bundle.dumps` QAYTA ISHLATILADI: ikkinchi serializator bir kun boshqa bayt
    berardi va xesh solishtirish ma'nosini yo'qotardi."""
    from app.services.discovery_1c.bundle import dumps

    assert pr.dumps is dumps
    kod = _kod_faqat(AGENT_DIR / "bridge_protocol.py")
    assert "json.dumps" not in kod, "o'z serializatori YOZILMAYDI"


# ══════════════════════════════════════════════════════════════════════════════════════════
# P0 — JAVOB HOLATI LUG'ATI YIG'UVCHINING `overall` LUG'ATI BILAN AYNI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_P0_javob_holati_lugati_YIGUVCHINING_overall_lugatidan_OLINADI():
    """⚠️⚠️ TOPILGAN P0: lug'at IKKI XIL edi va MUVAFFAQIYATLI yurish RAD etilardi.

    Yig'uvchi (`BinOSDiscoveryCollector.bsl`) `run_status.json` ning `overall` qiymatini
    qaytaradi — `SUCCESS` / `PARTIAL` / `FAILED`. Ko'prik esa `OK` kutardi, ya'ni
    `SUCCESS` yozilgan HAR BIR haqiqiy javob `BRIDGE_SHAPE_INVALID` bilan rad etilardi.
    ⚠️ Shu bois UCH qiymat YADRODAN IMPORT qilinadi va bu yerda QAYTA E'LON QILINMAYDI:
       ikkinchi nusxa bir kun yana ajralib ketardi.
    """
    # ⚠️⚠️ ARXITEKTOR QARORI B TUZATILDI: dastlab AYNAN to'rt qiymat belgilangan edi, lekin
    #      `.bsl` BESHINCHISINI — `BRIDGE_REJECTED` — allaqachon yozardi (ko'prik so'rovni
    #      o'qib RAD ETGANI). Uch tomonli konformans darvozasi shu driftni TUTDI. Bu test
    #      YUMSHATILMADI: shartnoma TUZATILDI va u hamon AYNAN beshta qiymatni va TARTIBNI
    #      qulflaydi. Drift sababi: dastlabki qarorda qiymat lug'ati `.bsl` dan
    #      TEKSHIRILMASDAN yozilgandi.
    assert pr.RESPONSE_STATUSES == ("SUCCESS", "PARTIAL", "FAILED", "CANCELLED",
                                    "BRIDGE_REJECTED"), \
        "lug'at va TARTIBI shartnoma (arxitektor QARORI B, tuzatilgan)"
    assert (pr.STATUS_SUCCESS, pr.STATUS_PARTIAL, pr.STATUS_FAILED) == \
        (OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED), \
        "qiymatlar `runtime_bundle.OVERALL_*` dan OLINADI (ikkinchi lug'at yozilmaydi)"
    # ⚠️ `OK` QIYMATI YO'Q: u `SUCCESS` ning dublikati edi va nomuvofiqlikni tug'dirardi.
    assert "OK" not in pr.RESPONSE_STATUSES
    assert pr.STATUS_OK == pr.STATUS_SUCCESS, "eskirgan NOM, qiymat esa BITTA"
    # ⚠️ `CANCELLED` — ko'prikka XOS: Phase 4 da bekor qilish tushunchasi YO'Q.
    assert pr.STATUS_CANCELLED not in (OVERALL_SUCCESS, OVERALL_PARTIAL, OVERALL_FAILED)


def test_P0_yiguvchining_SUCCESS_javobi_QABUL_qilinadi():
    """⚠️⚠️ P0 NING TO'G'RIDAN O'LCHOVI: aynan `SUCCESS` matni yozilgan javob O'TADI.

    Eski kodda bu test `BRIDGE_SHAPE_INVALID` bilan yiqilardi — ya'ni bir-bosishli
    ko'prik haqiqiy 1C da HECH QACHON ishlamasdi.
    """
    req = _request()
    natija = pr.accept_collector_output(request=req,
                                        response=_response(req, status="SUCCESS"),
                                        done=_done(req), bundle_files=REQUIRED_FILES)
    assert natija.status == "SUCCESS"
    assert natija.phase == bp.COLLECTOR_COMPLETE and natija.code is None


def test_P0_eski_OK_qiymati_ENDI_RAD_etiladi():
    """⚠️ Dublikat qiymat QAYTIB KELMASIN: `OK` noma'lum qiymat bo'lib RAD etiladi."""
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response, _response(req, status="OK"),
         request=req)


def test_PARTIAL_javob_COLLECTOR_COMPLETE_ga_otadi_lekin_PAKET_TOLIQ_bolishi_SHART():
    """⚠️⚠️ `PARTIAL` JIMGINA MUVAFFAQIYAT EMAS, lekin «yiqildi» ham EMAS.

    Faza `COLLECTOR_COMPLETE` (javob bor, paket to'liq), `status` esa AYNAN `PARTIAL`
    bo'lib qoladi — hukmni QUVUR beradi: Phase 4 validatori kodi `2` ni hurmat qilib
    TO'XTAYDI (CP2 qoidasi). Ko'prik yarim natijani «tugadi» deb ATAMAYDI.
    ⚠️ PAKET TO'LIQLIGI `PARTIAL` da ham TALAB QILINADI: yarim yozilgan paketni ingest
       qilish aynan Phase 4 da yolg'on SUCCESS bergan yo'l edi.
    """
    req = _request()
    natija = pr.accept_collector_output(
        request=req, response=_response(req, status=pr.STATUS_PARTIAL),
        done=_done(req), bundle_files=REQUIRED_FILES)
    assert natija.status == pr.STATUS_PARTIAL, "yarim natija AYNAN shu nom bilan qoladi"
    assert natija.phase == bp.COLLECTOR_COMPLETE
    assert natija.code is None, "bu ko'prikning rad etishi EMAS — hukm quvurda"
    # ⚠️ To'liq bo'lmagan paket bilan `PARTIAL` ham O'TMAYDI.
    _rad(bp.CODE_PARTIAL_PACKAGE, pr.accept_collector_output,
         request=req, response=_response(req, status=pr.STATUS_PARTIAL),
         done=_done(req), bundle_files=tuple(REQUIRED_FILES)[1:])


# ══════════════════════════════════════════════════════════════════════════════════════════
# KO'PRIK `run_id` I — AYNAN UZUNLIKDA
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_koprik_run_id_AYNAN_uzunlikda_bolishi_SHART():
    """⚠️⚠️ TUZATILGAN NUQSON: shakl BO'SH edi — `status.RUN_ID_RE` `0000000` ni ham,
    `run-2026-10-02` ni ham qabul qiladi, ya'ni past entropiyali qiymat ko'prik
    hujjatiga tushib, «eski natijani qayta ishlatish» yo'lini KENGAYTIRARDI.
    ⚠️ Umumiy `status.RUN_ID_RE` BUZILMAYDI: u boshqa joyda ishlatiladi va ko'prik
       shartnomasi unga ZID emas (faqat QAT'IYROQ).
    """
    togri = "0" * (pr.RUN_ID_BYTES * 2)
    assert pr.BRIDGE_RUN_ID_RE.fullmatch(togri) and STATUS_RUN_ID_RE.fullmatch(togri)
    for yomon in ("0000000", "0" * (pr.RUN_ID_BYTES * 2 - 1),
                  "0" * (pr.RUN_ID_BYTES * 2 + 1), "0" * 15 + "A", "run-2026-10-02"):
        assert pr.BRIDGE_RUN_ID_RE.fullmatch(yomon) is None, yomon
    # ⚠️ Umumiy shakl ularning AYRIMLARINI qabul qiladi — ajrim AYNAN shu yerda.
    assert STATUS_RUN_ID_RE.fullmatch("0000000") is not None, \
        "umumiy shakl o'zgarmaydi (u boshqa joyda ishlatiladi)"


def test_koprik_run_id_SHAKLI_HAMMA_hujjatda_va_PAPKA_nomida_tekshiriladi(tmp_path):
    """⚠️ Qisqa `run_id` HAR UCH hujjatda va papka nomida RAD etiladi (fail-closed)."""
    qisqa = "0000000"
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.run_dir_for, qisqa, runs_root=tmp_path)
    req = _request()
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_request, dict(req, run_id=qisqa))
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_response,
         _response(req, run_id=qisqa), request=req)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, pr.validate_done_marker,
         _done(req, run_id=qisqa), request=req)


# ══════════════════════════════════════════════════════════════════════════════════════════
# DA'VOLAR HALOL: XESH va ESKIRGAN QAYDLAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_xesh_DAVOSI_kriptografik_kafolat_BERMAYDI():
    """⚠️⚠️ TUZATILGAN DA'VO: izoh «undan `locator` ni qaytarib bo'lmaydi» deyardi.

    Bu ANIQ EMAS: kirish past entropiyali (`kind` ikki qiymatli, `name`/`locator`
    tipik) va xesh TUZLANMAGAN — tipik fayl yo'llarini LUG'AT bilan qidirib topish
    mumkin. Shu bois da'vo haqiqatga moslangan: xesh xom qiymatni OLIB YURMAYDI, lekin
    «qaytarib bo'lmaydi» degan KAFOLAT berilmaydi.
    """
    hujjat = pr.target_fingerprint.__doc__ or ""
    # ⚠️ TEKSHIRUV IJOBIY: «qaytarib bo'lmaydi» iborasi izohda ATAYLAB QOLDIRILGAN, lekin
    #    FAQAT «kafolat BERILMAYDI» deb aytish uchun. Shu bois yo'qligi emas, AYNAN shu
    #    inkor jumlasi talab qilinadi — aks holda to'g'ri yozilgan izoh testni yiqitardi.
    tekis = " ".join(hujjat.split())
    assert "«qaytarib bo'lmaydi» degan KRIPTOGRAFIK kafolat BERILMAYDI" in tekis, \
        "da'vo CHEGARASI AYNAN inkor bilan yozilishi SHART"
    assert "OSHKOR" in hujjat and "past entropiyali" in hujjat, \
        "nega kafolat berilmasligi SABABI bilan yozilishi SHART"
    # ⚠️ LUG'AT HUJUMI O'LCHANADI: nomzodlar ro'yxatidan xesh TOPILADI.
    xesh = pr.target_fingerprint("file", "Fayzan savdo", LOCATOR)
    nomzodlar = ["C:\\baza\\1Cv8.1CD", LOCATOR, "D:\\1c\\1Cv8.1CD"]
    topildi = [n for n in nomzodlar
               if pr.target_fingerprint("file", "Fayzan savdo", n) == xesh]
    assert topildi == [LOCATOR], \
        "xesh past entropiyali kirish uchun LUG'AT bilan topiladi — kafolat DA'VO " \
        "QILINMASLIGI shuning uchun"
    # ⚠️ XOM QIYMAT esa CHIQISHGA TUSHMAYDI (asl da'vo SHU va u KUCHDA qoladi).
    assert pr.FINGERPRINT_RE.fullmatch(xesh) and LOCATOR not in xesh


def test_RUNS_DIR_OPTION_izohi_ESKIRMAGAN_bolishi_SHART():
    """⚠️⚠️ ESKIRGAN «HALOL QAYD» ham YOLG'ON: izoh «`__main__.py` tegilmagan, qobiliyat
    YO'Q» deyardi, holbuki bayroq ALLAQACHON bor va u `runs_root` ga uzatiladi.
    """
    from app.services.discovery_agent import __main__ as cli

    yordam = cli.build_parser().format_help()
    assert pr.RUNS_DIR_OPTION in yordam, "bayroq buyruq satrida BO'LISHI SHART"
    manba = pathlib.Path(pr.__file__).read_text(encoding="utf-8")
    boshi = manba.find("RUNS_DIR_OPTION =")
    izoh = manba[max(0, boshi - 1400):boshi]
    # ⚠️ TEKSHIRUV IJOBIY: eskirgan jumla izohda TUZATILGAN deb ATALADI, shu bois
    #    «tegilmagan» so'zining yo'qligi emas, uning INKOR qilinishi talab qilinadi.
    assert "ESKIRGAN DA'VO OLIB TASHLANDI" in izoh, "qayd yangilanganini AYTISHI SHART"
    assert "bu ENDI HAQIQAT" in izoh and "qobiliyat MAVJUD" in izoh, \
        "izoh yangi HAQIQATNI aytishi SHART (qobiliyat bor)"


def test_CANCEL_FILE_qaydi_AGENT_tomonidagi_bekor_qilishni_ATAYDI():
    """⚠️ Fayl hali YOZILMAYDI (bu HALOL qoladi), lekin AGENT tomonidagi bekor qilish
    ROSTDAN bor va qayd shuni AYTADI — aks holda paket o'zi haqida kam aytardi."""
    manba = pathlib.Path(pr.__file__).read_text(encoding="utf-8")
    boshi = manba.find("CANCEL_FILE =")
    izoh = manba[max(0, boshi - 1400):boshi]
    assert "CancelToken" in izoh, "agent tomonidagi bekor qilish yo'li ATALISHI SHART"
    assert "ABORTED_BY_OPERATOR" in izoh
    # ⚠️ DA'VO OSHIRILMAYDI: 1C ichidagi yig'uvchi bu belgini hali KO'RMAYDI.
    assert "BERILMAYDI" in izoh
