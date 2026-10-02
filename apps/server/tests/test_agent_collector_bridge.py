# -*- coding: utf-8 -*-
"""Yig'uvchi KO'PRIGI (`collector_bridge.py`) — SINTETIK fiksturalar, HAQIQIY 1C YO'Q.

⚠️⚠️ BIRINCHI QOIDA: birorta test `1cv8.exe` ni ISHGA TUSHIRMAYDI. Bu mashinada 1C umuman
     o'rnatilmagan (`1cv8.exe` yo'q, COM klasslari ro'yxatda yo'q, `pywin32` yo'q), lekin
     boshqa mashinada BOR bo'lishi mumkin — shu bois taqiq fikstura bilan MAJBURLANADI:
     `_jarayon_ishga_tushirish_taqiqlangan` fikstura `subprocess.run` ni ISTISNO bilan
     almashtiradi va u AVTOMATIK (autouse) ishlaydi. Natijada «1C bor» mashinada ham
     to'plam hech narsani ishga tushirmaydi, aks holda to'plamning xavfsizligini
     MASHINANING holati hal qilardi.

⚠️ Shu sababli bu fayl 1C ning XULQI haqida HECH QANDAY da'vo qilmaydi: integratsiya
   yo'llari (`batch_execute`, `watch_folder`) `RUNTIME-UNKNOWN` bo'lib qoladi. Isbotlanadigan
   narsa — KO'PRIKNING O'Z mantiqi:

  · `build_command` AYNAN kutilgan argument ro'yxatini beradi (qulflangan) va SOF;
  · buyruq satrida PAROL (`/P`) va foydalanuvchi (`/N`) kaliti HECH QACHON chiqmaydi,
    `CollectPlan` da kredensial MAYDONI UMUMAN yo'q;
  · `requires_auth` `"true"`/`"unknown"` bo'lsa paketli yo'l BOSHLANMAYDI (fail-closed);
  · argumentda `"`/`;`/`&`/`|`/yangi qator bo'lsa RAD etiladi;
  · `shell=True` manbada YO'Q va jarayon `list` argument bilan chaqiriladi;
  · `.epf` yo'q -> `FAILED_COLLECTOR_UNAVAILABLE` (`FAILED_NO_1C` EMAS: `UNKNOWN` ≠ `NOT_FOUND`);
  · nol bo'lmagan chiqish kodi -> ANIQ yiqilish, jimgina o'tish YO'Q;
  · `watch_folder`: `manifest.json` paydo bo'lmasa -> `FAILED_TIMEOUT`;
  · ⚠️ YARIM yozilgan `manifest.json` TAYYOR deb hisoblanMAYDI (Phase 4 da aynan shu nuqson
    yolg'on SUCCESS bergan edi);
  · to'liq paket -> `ok=True` va `bundle_dir` to'g'ri;
  · yiqilish yozuvlari `agent_status.json` ga sir darvozasidan O'TIB yoziladi.

ATAYLAB SINALMAYDI:
  · paketning MAZMUNI — u yadroning ishi (`runtime_bundle.validate_runtime_bundle`), ko'prik
    esa faqat «to'liq YOZILDI» faktini isbotlaydi. Ikki validator bir kun ajralib ketardi.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import pathlib
import re

import pytest

from app.services.discovery_1c import redact as redaction
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c.runtime_bundle import (MANIFEST_FILE, MANIFEST_VERSION,
                                                      MODE_APPROVED_PROBES,
                                                      MODE_METADATA_ONLY, REQUIRED_FILES)
from app.services.discovery_agent import ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER
from app.services.discovery_agent import collector_bridge as cb
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as ss
from tests import discovery_1c_runtime_mock as M

T0 = "2026-10-01T09:00:00+06:00"

#: Manifestning MAZMUNI ataylab MINIMAL, LEKIN BO'SH EMAS: ko'prik TO'LIQ sxemani
#: tekshirmaydi (bu yadroning ishi), u faqat «yozish TUGADIMI» faktini o'lchaydi — va shu
#: o'lchov MINIMAL SHAKLNI talab qiladi: `manifest_version` AYNAN kutilgan qiymat va `files`
#: BO'SH BO'LMAGAN ro'yxat.
#: ⚠️ Avval bu fikstura `files: []` edi va shu tufayli ikki baytlik `{}` ham «tayyor» bo'lib
#:    o'tib ketardi — nuqson aynan shu yerda ko'rinmay qolgan edi.
MANIFEST_DOC = {"manifest_version": MANIFEST_VERSION,
                "files": [{"name": "export.json", "bytes": "2", "sha256": None}],
                "notes": []}

#: Repo ildizi — hujjat va yig'uvchi manbasi testlari uchun.
_REPO = pathlib.Path(cb.__file__).resolve().parents[5]
#: ⚠️ Yig'uvchi MANBASI (`.bsl`). Repoda `.epf` KONTEYNERI YO'Q va bu ataylab tekshiriladi.
_YIGUVCHI_MANBA = _REPO / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl"
#: Operator oqimi hujjati — brief §4 va §7 ning odam o'qiydigan tomoni.
_OQIM_HUJJATI = _REPO / "integrations" / "1c" / "AGENT_OPERATOR_FLOW.md"


# ══════════════════════════════════════════════════════════════════════════════════════════
# FIKSTURALAR va YORDAMCHILAR
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _jarayon_ishga_tushirish_taqiqlangan(monkeypatch):
    """⚠️ HAR BIR testda `subprocess.run` ISTISNO beradi — tasodifan ham hech narsa yurmaydi.

    Chaqiruv SHAKLINI sinaydigan yagona test bu almashtirishni O'Z josusi bilan qayta
    yozadi; qolgan hamma testda ko'prik soxta yurituvchi (`runner=`) oladi.
    """
    def portlat(*a, **kw):   # pragma: no cover - chaqirilmasligi KERAK
        raise AssertionError("test HAQIQIY jarayon ishga tushirmaydi: subprocess.run taqiq")
    monkeypatch.setattr(cb.subprocess, "run", portlat)


class SoxtaSoat:
    """Soxta soat: `__call__` — hozirgi qiymat, `sleep` — vaqtni SURADI.

    ⚠️ Vaqt KIRISHDAN kelgani uchun kutish mantiqi haqiqiy soniyalarni kutmasdan sinaladi:
    aks holda `FAILED_TIMEOUT` testi to'plamni daqiqalarga cho'zardi.
    """

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.sleeps.append(dt)
        self.t += dt


class SoxtaYurituvchi:
    """Soxta 1C: chaqiruvni YOZIB OLADI va kerak bo'lsa paketni «yozib» qo'yadi."""

    def __init__(self, exit_code: int | None = 0, timed_out: bool = False,
                 writes_to: pathlib.Path | None = None, detail: str = "") -> None:
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.writes_to = writes_to
        self.detail = detail
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(self, command, timeout_seconds):
        self.calls.append((tuple(command), timeout_seconds))
        if self.writes_to is not None:
            paket_yoz(self.writes_to)
        return cb.RunOutcome(exit_code=self.exit_code, timed_out=self.timed_out,
                             detail=self.detail)


def paket_yoz(folder: pathlib.Path, *, manifest_text: str | None = None) -> None:
    """Olti majburiy artefaktni yozadi. ⚠️ `manifest.json` ENG OXIRIDA — Phase 4 tartibi."""
    for nom in REQUIRED_FILES:
        if nom == MANIFEST_FILE:
            continue
        (folder / nom).write_text("{}" if nom.endswith(".json") else "# hisobot\n",
                                  encoding="utf-8")
    matn = (json.dumps(MANIFEST_DOC, ensure_ascii=False) if manifest_text is None
            else manifest_text)
    (folder / MANIFEST_FILE).write_text(matn, encoding="utf-8")


def muhit(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """`(exe, epf, bo'sh chiqish papkasi)`. ⚠️ `exe` — oddiy FAYL, u BAJARILMAYDI."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    exe = tmp_path / "1cv8.exe"
    exe.write_bytes(b"bu 1C emas, bu fikstura")
    epf = tmp_path / "BinOSDiscovery.epf"
    epf.write_bytes(b"bu .epf emas, bu fikstura")
    out = tmp_path / "chiqish"
    out.mkdir()
    return exe, epf, out


def reja(tmp_path: pathlib.Path, **kw) -> cb.CollectPlan:
    """Ishlaydigan standart reja; `kw` bilan bitta shart buziladi."""
    exe, epf, out = muhit(tmp_path)
    maydonlar = dict(
        epf_path=str(epf), output_dir=str(out), exe_path=str(exe),
        infobase_kind="file", infobase_locator=str(tmp_path / "baza" / "1Cv8.1CD"),
        requires_auth="false", mode=MODE_METADATA_ONLY,
        timeout_seconds=100.0, poll_seconds=2.0,
    )
    maydonlar.update(kw)
    return cb.CollectPlan(**maydonlar)


def xato_kodlari(res: cb.BridgeResult) -> list[str]:
    return [e.code for e in res.errors]


def kutish_bilan(soat: SoxtaSoat, hodisalar: dict):
    """Soxta `sleeper`: belgilangan KUTUVDA faylni yozadi — haqiqiy yozuvchi taqlidi.

    ⚠️ NEGA KUTISH PAYTIDA: chiqish papkasi KUZATUV BOSHLANGANDA BO'SH bo'lishi SHART
    (aks holda eski paket yangi natija deb o'qilardi), demak «to'liq paket» holati faqat
    kutish davomida tug'ilishi mumkin — haqiqiy oqimda ham shunday bo'ladi.
    """
    def sleeper(dt: float) -> None:
        soat.sleep(dt)
        hodisa = hodisalar.get(len(soat.sleeps))
        if hodisa is not None:
            hodisa()
    return sleeper


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. BUYRUQ SATRI — QULFLANGAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_build_command_aynan_kutilgan_argumentlarni_beradi():
    """⚠️ QULF: shakl o'zgarsa test yiqiladi. 1C yo'q, demak YAGONA himoya shu."""
    plan = cb.CollectPlan(
        epf_path=r"D:\binos\BinOSDiscovery.epf",
        output_dir=r"D:\binos\chiqish",
        exe_path=r"C:\Program Files\1cv8\8.3.24.1548\bin\1cv8.exe",
        infobase_kind="file",
        infobase_locator=r"D:\bazalar\fayzan",
        requires_auth="false",
    )
    assert cb.build_command(plan) == (
        r"C:\Program Files\1cv8\8.3.24.1548\bin\1cv8.exe",
        "ENTERPRISE",
        r"/FD:\bazalar\fayzan",
        "/Execute",
        r"D:\binos\BinOSDiscovery.epf",
        r"/CD:\binos\chiqish",
    )


def test_build_command_sof_funksiya_va_deterministik():
    """Fayl tizimiga TEGMAYDI (yo'llar mavjud emas) va ikki chaqiruv AYNI natija beradi."""
    plan = cb.CollectPlan(epf_path=r"Z:\yoq\a.epf", output_dir=r"Z:\yoq\out",
                          exe_path=r"Z:\yoq\1cv8.exe", infobase_kind="file",
                          infobase_locator=r"Z:\yoq\baza", requires_auth="false")
    assert cb.build_command(plan) == cb.build_command(plan)


def test_params_satri_faqat_chiqish_papkasini_tashiydi():
    """⚠️ `/C` ichiga rejim ham, zond ro'yxati ham QO'SHILMAYDI — shartnoma o'ylab
    chiqarilmaydi: paketli parametrni faqat BSL o'qiydi va u bugun faqat papkani kutadi."""
    plan = cb.CollectPlan(epf_path="a.epf", output_dir=r"D:\out", exe_path="1cv8.exe",
                          infobase_kind="file", infobase_locator=r"D:\baza",
                          requires_auth="false")
    params = [t for t in cb.build_command(plan) if t.startswith(cb.SWITCH_PARAMS)]
    assert params == [r"/CD:\out"]


def test_build_command_server_bazasi_uchun_qurilmaydi():
    """⚠️ `/S` shakli bu yerda tekshirib bo'lmaydi, shu bois O'YLAB CHIQARILMAYDI."""
    plan = cb.CollectPlan(epf_path="a.epf", output_dir="out", exe_path="1cv8.exe",
                          infobase_kind="server", infobase_locator="srv/fayzan",
                          requires_auth="false")
    with pytest.raises(cb.BridgeError):
        cb.build_command(plan)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. PAROL TAQIG'I
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("locator,epf,out", [
    (r"D:\bazalar\fayzan", r"D:\a.epf", r"D:\out"),
    (r"C:\parollar\baza", r"C:\yig.epf", r"C:\chiqish"),          # «parol» so'zli yo'l
    (r"\\server\ulanish\baza", r"D:\a.epf", r"D:\out"),            # UNC yo'l
    ("baza", "a.epf", "out"),                                      # nisbiy yo'llar
])
def test_buyruq_satrida_parol_kaliti_hech_qachon_chiqmaydi(locator, epf, out):
    """⚠️ `/P<parol>` jarayon ro'yxatida KO'RINADI — shu bois u hech bir shaklda chiqmaydi.

    Tekshiruv KALIT bo'yicha, qiymat bo'yicha emas: operator papkasini «parollar» deb
    atashi mumkin va bu ko'prikning aybi emas.
    """
    plan = cb.CollectPlan(epf_path=epf, output_dir=out, exe_path="1cv8.exe",
                          infobase_kind="file", infobase_locator=locator,
                          requires_auth="false")
    command = cb.build_command(plan)
    kalitlar = [t for t in command if t.startswith("/")]
    assert not [t for t in kalitlar if t.upper().startswith("/P")]
    assert not [t for t in kalitlar if t.upper().startswith("/N")]
    assert len(command) == 6, "buyruqqa yangi argument qo'shilgan — shakl qulfini yangilang"


@pytest.mark.parametrize("token", ["/P1234", "/pMaxfiy", "/Nadmin", "/n admin"])
def test_kredensial_kalitini_qoshish_istisno_beradi(token):
    """⚠️ KELAJAKDAGI TAHRIRdan himoya: kalit qo'shilsa KOD o'zi yiqiladi."""
    with pytest.raises(cb.BridgeError):
        cb._assert_no_credentials(("1cv8.exe", "ENTERPRISE", token))


def test_rejada_kredensial_maydoni_umuman_yoq():
    """⚠️ «Maydon bor, lekin bo'sh» yo'li yaramaydi: bir kun kimdir uni to'ldiradi."""
    taqiq = re.compile(r"(?i)pass|parol|пароль|pwd|secret|token|credential|user|usr|login")
    nomlar = [f.name for f in dataclasses.fields(cb.CollectPlan)]
    assert not [n for n in nomlar if taqiq.search(n)], nomlar
    assert "requires_auth" in nomlar, "parol KERAKLIGI yoziladi, parolning O'ZI yozilmaydi"


@pytest.mark.parametrize("requires_auth", ["true", "unknown"])
def test_auth_kerak_bolsa_paketli_yol_tanlanmaydi(tmp_path, requires_auth):
    """⚠️ `unknown` HAM to'xtatadi: fail-closed, noma'lumlik ruxsatga aylanmaydi."""
    yurituvchi = SoxtaYurituvchi()
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, requires_auth=requires_auth), clock=soat,
                     sleeper=soat.sleep, runner=yurituvchi)
    assert res.ok is False
    assert res.state_hint == st.FAILED_AUTH_REQUIRED
    assert res.route == ROUTE_BATCH_EXECUTE
    assert xato_kodlari(res) == [cb.CODE_AUTH_REQUIRED]
    assert cb.WATCH_FOLDER_SUGGESTION in res.notes, "zaxira yo'l TAKLIF qilinishi kerak"
    assert yurituvchi.calls == [], "1C UMUMAN ishga tushirilmasligi kerak"
    assert res.bundle_dir is None


def test_auth_kerak_bolganda_jimgina_zaxiraga_otilmaydi(tmp_path):
    """⚠️ Ko'prik `watch_folder` ni O'ZI boshlab ketmaydi: u yo'l ODAM ishini talab qiladi.

    Jimgina o'tish «o'zi urinib ko'rdi, o'zi o'tdi» xulqini berardi va hisobotda qaysi yo'l
    aslida ishlaganini aniqlab bo'lmasdi.
    """
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, requires_auth="unknown"), clock=soat,
                     sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.route == ROUTE_BATCH_EXECUTE
    assert soat.sleeps == [], "kuzatuv halqasi boshlanmasligi kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. ARGUMENT INYEKSIYASI
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("belgi", ['"', ";", "&", "|", "\n", "\r", "<", ">", "^", "`"])
def test_xavfli_belgili_argument_rad_etiladi(belgi):
    plan = cb.CollectPlan(epf_path="a.epf", output_dir="out", exe_path="1cv8.exe",
                          infobase_kind="file",
                          infobase_locator=f"D:\\baza{belgi}zarar", requires_auth="false")
    with pytest.raises(cb.BridgeError):
        cb.build_command(plan)


def test_boshqaruv_belgisi_ham_rad_etiladi():
    with pytest.raises(cb.BridgeError):
        cb._safe_arg("D:\\baza\x00zarar", "infobase_locator")


@pytest.mark.parametrize("belgi", ['"', ";", "&", "|", "\n"])
def test_xavfli_belgi_collect_darajasida_safety_beradi(tmp_path, belgi):
    """⚠️ Inyeksiya urinishi — XAVFSIZLIK chegarasi (`FAILED_SAFETY`), «yig'uvchi yo'q» emas.

    ⚠️ Belgi LOKATORGA qo'yiladi: uning mavjudligi tekshirilmaydi, shu bois sinov Windows
    fayl nomi cheklovlariga bog'lanib qolmaydi.
    """
    yurituvchi = SoxtaYurituvchi()
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, infobase_locator=f"D:\\baza{belgi}zarar"),
                     clock=soat, sleeper=soat.sleep, runner=yurituvchi)
    assert res.ok is False
    assert res.state_hint == st.FAILED_SAFETY
    assert xato_kodlari(res) == [cb.CODE_UNSAFE_ARGUMENT]
    assert yurituvchi.calls == [], "xavfsiz bo'lmagan buyruq ISHGA TUSHMASLIGI kerak"


def test_xato_matnida_qiymatning_ozi_korsatilmaydi():
    """⚠️ Xabar jurnalga tushadi, yo'l esa sir bo'lishi mumkin — faqat BELGI nomi yoziladi."""
    with pytest.raises(cb.BridgeError) as ko:
        cb._safe_arg('D:\\maxfiy-baza"zarar', "infobase_locator")
    assert "maxfiy-baza" not in str(ko.value)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. QOBIQ YO'Q — `shell=True` ISHLATILMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
_SOURCE = pathlib.Path(cb.__file__).read_text(encoding="utf-8")


def test_manbada_shell_true_yoq():
    """⚠️ STATIK darvoza: `shell=True` manbada UMUMAN bo'lmasin (izohda ham)."""
    assert "shell=True" not in _SOURCE
    assert "shell = True" not in _SOURCE
    assert "os.system" not in _SOURCE
    assert "startfile" not in _SOURCE


def test_jarayon_royxat_argument_bilan_qobiqsiz_chaqiriladi(monkeypatch):
    """Standart yurituvchining chaqiruv SHAKLI — HAQIQIY 1C ishga tushirilmasdan.

    ⚠️ `subprocess.run` josus bilan almashtiriladi, ya'ni hech qanday jarayon tug'ilmaydi.
    ⚠️ `stdout`/`stderr` — `DEVNULL`: 1C xato matni ulanish satrini chiqarishi mumkin va u
       jurnalga tushib sirni oshkor qilardi.
    """
    yozilgan: dict = {}

    class Natija:
        returncode = 0

    def josus(*args, **kwargs):
        yozilgan["args"] = args
        yozilgan["kwargs"] = kwargs
        return Natija()

    monkeypatch.setattr(cb.subprocess, "run", josus)
    out = cb.run_1c_batch(("1cv8.exe", "ENTERPRISE", "/Fbaza"), 42.0)
    assert out == cb.RunOutcome(exit_code=0, timed_out=False, detail="")
    assert isinstance(yozilgan["args"][0], list), "buyruq LIST bo'lib uzatiladi"
    kw = yozilgan["kwargs"]
    assert kw["shell"] is False
    assert kw["stdout"] is cb.subprocess.DEVNULL
    assert kw["stderr"] is cb.subprocess.DEVNULL
    assert kw["check"] is False
    assert kw["timeout"] == 42.0


def test_jarayon_vaqti_tugasa_va_ishga_tushmasa_aniq_natija(monkeypatch):
    """⚠️ Istisno JIM yutilmaydi: ikkisi ham ANIQ `RunOutcome` ga aylanadi."""
    def vaqt_tugadi(*a, **kw):
        raise cb.subprocess.TimeoutExpired(cmd="1cv8.exe", timeout=1.0)

    monkeypatch.setattr(cb.subprocess, "run", vaqt_tugadi)
    assert cb.run_1c_batch(("1cv8.exe",), 1.0).timed_out is True

    def topilmadi(*a, **kw):
        raise FileNotFoundError(2, "yo'q", r"C:\maxfiy\1cv8.exe")

    monkeypatch.setattr(cb.subprocess, "run", topilmadi)
    out = cb.run_1c_batch(("1cv8.exe",), 1.0)
    assert out.exit_code is None and out.timed_out is False
    assert "maxfiy" not in out.detail, "istisno MATNI (yo'l bilan) ko'chirilmaydi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. DARVOZALAR — ANIQ YIQILISH HOLATLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_epf_yoq_collector_unavailable_beradi(tmp_path):
    """⚠️ `UNKNOWN` ≠ `NOT_FOUND`: `.epf` yo'qligi 1C bor-yo'qligi haqida hech narsa demaydi."""
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, epf_path=str(tmp_path / "yoq.epf")), clock=soat,
                     sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert res.state_hint != st.FAILED_NO_1C
    assert xato_kodlari(res) == [cb.CODE_EPF_MISSING]


def test_1cv8_yoq_no_1c_beradi(tmp_path):
    """⚠️ Bu ALOHIDA holat: 1C YO'Q (javob), yig'uvchi javob bermadi (javob yo'q) — emas."""
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, exe_path=str(tmp_path / "yoq" / "1cv8.exe")),
                     clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_NO_1C
    assert xato_kodlari(res) == [cb.CODE_EXE_MISSING]
    assert cb.WATCH_FOLDER_SUGGESTION in res.notes


def test_nishon_tanlanmagan_no_target_beradi(tmp_path):
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, infobase_locator=""), clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_NO_TARGET
    assert xato_kodlari(res) == [cb.CODE_NO_TARGET]


def test_server_nishoni_paketli_yolda_boshlanmaydi(tmp_path):
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, infobase_kind="server", infobase_locator="srv/fayzan"),
                     clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert xato_kodlari(res) == [cb.CODE_SERVER_TARGET_UNSUPPORTED]


def test_zond_rejimi_paketli_yol_bilan_uzatilmaydi(tmp_path):
    """⚠️ QOBILIYAT CHEGARASI, yashirilmaydi: `/C` faqat chiqish papkasini tashiydi."""
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, mode=MODE_APPROVED_PROBES), clock=soat,
                     sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert xato_kodlari(res) == [cb.CODE_MODE_UNSUPPORTED]
    assert cb.WATCH_FOLDER_SUGGESTION in res.notes


def test_chiqish_papkasi_yoq_safety_beradi(tmp_path):
    """⚠️ Ko'prik papka YARATMAYDI: faqat-o'qish chegarasi."""
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, output_dir=str(tmp_path / "yoq")), clock=soat,
                     sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_SAFETY
    assert xato_kodlari(res) == [cb.CODE_OUTPUT_DIR_MISSING]


@pytest.mark.parametrize("route", [ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER])
def test_chiqish_papkasi_bosh_emas_safety_beradi(tmp_path, route):
    """⚠️ Eski fayl qolsa, kuzatuvchi uni YANGI natija deb o'qib yolg'on SUCCESS berardi."""
    plan = reja(tmp_path, route=route)
    (pathlib.Path(plan.output_dir) / "eski.json").write_text("{}", encoding="utf-8")
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_SAFETY
    assert xato_kodlari(res) == [cb.CODE_OUTPUT_DIR_NOT_EMPTY]
    assert res.route == route, "urinilgan YO'L to'g'ri yozilishi kerak"


def test_notogri_yol_nomi_ichki_nuqson(tmp_path):
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, route="com_connector"), clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi())
    assert res.state_hint == st.FAILED_INTERNAL
    assert xato_kodlari(res) == [cb.CODE_BAD_PLAN]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. PAKETLI YO'L — YURISH NATIJASI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_paketli_yol_tolik_paket_bilan_ok(tmp_path):
    plan = reja(tmp_path)
    soat = SoxtaSoat()
    yurituvchi = SoxtaYurituvchi(exit_code=0, writes_to=pathlib.Path(plan.output_dir))
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=yurituvchi)
    assert res.ok is True
    assert res.route == ROUTE_BATCH_EXECUTE
    assert res.bundle_dir == plan.output_dir
    assert res.exit_code == 0 and res.exit_code_text == "0"
    assert res.state_hint is None
    assert len(yurituvchi.calls) == 1
    buyruq, timeout = yurituvchi.calls[0]
    assert buyruq == cb.build_command(plan) and timeout == plan.timeout_seconds


@pytest.mark.parametrize("exit_code", [1, 2, 255, -1])
def test_nol_bolmagan_chiqish_kodi_aniq_yiqilish(tmp_path, exit_code):
    """⚠️ JIMGINA O'TISH YO'Q: papkada to'liq paket bo'lsa ham natija QABUL QILINMAYDI.

    Sabab: yarim yurgan 1C to'liq ko'rinadigan paket qoldirishi mumkin, chiqish kodi esa
    aynan «yurish tugamadi» deydi — ikkisidan birini tanlash kerak bo'lsa, KODGA ishonamiz.
    """
    plan = reja(tmp_path)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi(exit_code=exit_code,
                                            writes_to=pathlib.Path(plan.output_dir)))
    assert res.ok is False
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert res.exit_code == exit_code
    assert xato_kodlari(res) == [cb.CODE_EXIT_CODE_NONZERO]
    assert res.bundle_dir is None, "rad etilgan natija PAKET sifatida uzatilmaydi"


def test_paketli_yol_bosh_papka_qoldirsa_collector_unavailable(tmp_path):
    """⚠️ BU «BSL BO'SHLIG'I» KO'RINADIGAN JOY: jarayon 0 qaytardi, papka esa BO'SH.

    Kutish ma'nosiz (jarayon allaqachon tugagan), shu bois darhol ANIQ yiqilish.
    """
    plan = reja(tmp_path)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi(exit_code=0))
    assert res.ok is False
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert xato_kodlari(res) == [cb.CODE_BUNDLE_INCOMPLETE]
    assert soat.sleeps == [], "tugagan jarayonni KUTISH ma'nosiz"


def test_paketli_yol_vaqti_tugasa_timeout(tmp_path):
    plan = reja(tmp_path)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi(exit_code=None, timed_out=True))
    assert res.state_hint == st.FAILED_TIMEOUT
    assert res.exit_code is None


def test_jarayon_ishga_tushmasa_collector_unavailable(tmp_path):
    plan = reja(tmp_path)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep,
                     runner=SoxtaYurituvchi(exit_code=None, detail="ishga tushmadi: OSError"))
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert xato_kodlari(res) == [cb.CODE_LAUNCH_FAILED]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7. KUZATUV YO'LI — TUGALLANISH ISBOTI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_watch_folder_tolik_paket_ok_beradi(tmp_path):
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, {1: lambda: paket_yoz(out)}))
    assert res.ok is True
    assert res.route == ROUTE_WATCH_FOLDER
    assert res.bundle_dir == plan.output_dir
    assert res.exit_code is None, "jarayon BIZDA emas — chiqish kodi ham yo'q"


def test_watch_folder_manifest_paydo_bolmasa_timeout(tmp_path):
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=10.0, poll_seconds=2.0)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep)
    assert res.ok is False
    assert res.state_hint == st.FAILED_TIMEOUT
    assert xato_kodlari(res) == [cb.CODE_WAIT_TIMEOUT]
    assert res.bundle_dir is None
    assert soat.t >= plan.timeout_seconds, "cheksiz kutish YO'Q, vaqt chegarasi ishladi"


def test_watch_folder_yarim_yozilgan_manifest_tayyor_deb_hisoblanmaydi(tmp_path):
    """⚠️⚠️ ENG MUHIM TEST: Phase 4 da aynan YARIM fayl yolg'on SUCCESS bergan edi.

    Olti majburiy fayl HAMMASI joyida, `manifest.json` ham BOR — faqat u yarim yozilgan.
    «Fayl bor» mezoni bu paketni TAYYOR deb o'qirdi.
    """
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=10.0, poll_seconds=2.0)
    out = pathlib.Path(plan.output_dir)

    def yarim_yoz():
        paket_yoz(out, manifest_text='{"manifest_version": "binos-1c-manifest-v1", "files": [')
        assert (out / MANIFEST_FILE).exists(), "fikstura: fayl BOR, lekin to'liq emas"

    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, {1: yarim_yoz}))
    assert res.ok is False
    assert res.state_hint == st.FAILED_TIMEOUT
    assert res.bundle_dir is None
    assert MANIFEST_FILE in res.errors[0].detail


def test_watch_folder_oxirigacha_yozilgan_manifest_tayyor_boladi(tmp_path):
    """Barqarorlik kutuvi QOTIB QOLMAYDI: fayl to'lgach paket QABUL qilinadi.

    ⚠️ Soxta `sleeper` kutish paytida faylni OXIRIGACHA yozadi — ya'ni «hajmi o'sayotgan
    fayl» holati haqiqiy yozuvchi kabi taqlid qilinadi.
    """
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=100.0, poll_seconds=2.0)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    hodisalar = {
        1: lambda: paket_yoz(
            out, manifest_text='{"manifest_version": "binos-1c-manifest-v1", "files": ['),
        2: lambda: (out / MANIFEST_FILE).write_text(json.dumps(MANIFEST_DOC),
                                                    encoding="utf-8"),
    }
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, hodisalar))
    assert res.ok is True
    assert res.bundle_dir == plan.output_dir
    assert len(soat.sleeps) >= 3, "hajm BARQARORLASHGANI ikki o'lchov bilan tekshiriladi"


@pytest.mark.parametrize("yoq", list(REQUIRED_FILES))
def test_watch_folder_bitta_majburiy_fayl_yetishmasa_tayyor_emas(tmp_path, yoq):
    """⚠️ Olti artefaktning BIRORTASI yetishmasa paket tayyor EMAS — `manifest.json` ham."""
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=10.0, poll_seconds=2.0)
    out = pathlib.Path(plan.output_dir)

    def kam_yoz():
        paket_yoz(out)
        (out / yoq).unlink()

    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, {1: kam_yoz}))
    assert res.ok is False
    assert res.state_hint == st.FAILED_TIMEOUT


@pytest.mark.parametrize("manifest_text", [
    "{}",                                                      # ⚠️ IKKI BAYT — nuqsonning o'zi
    '{"notes": []}',                                           # tugallanish belgisi YO'Q
    '{"manifest_version": "binos-1c-manifest-v2", "files": [{"name": "export.json"}]}',
    '{"manifest_version": "binos-1c-manifest-v1", "files": []}',      # ro'yxat BO'SH
    '{"manifest_version": "binos-1c-manifest-v1", "files": {}}',      # ro'yxat EMAS
    '{"manifest_version": null, "files": [{"name": "export.json"}]}',
])
def test_MINIMAL_SHAKLI_yoq_manifest_TUGALLANISH_BELGISI_deb_qabul_QILINMAYDI(tmp_path,
                                                                             manifest_text):
    """⚠️⚠️ NUQSON: `{}` ham «tayyor» deb qabul qilinardi.

    Tayyorlik o'lchovi faqat uchta xossaga qarardi (fayl BOR · `dict` bo'lib parse bo'ladi ·
    hajmi barqaror), ya'ni IKKI BAYTLIK `{}` ham tugallanish belgisi bo'lib o'tib ketardi.
    Bu `AGENT_OPERATOR_FLOW.md` va `WATCH_FOLDER_OPERATOR_STEPS` dagi «yarim yozilgan fayl
    tayyor deb hisoblanmaydi» KAFOLATINI YOLG'ON qilardi: 1C manifestni ENG OXIRIDA yozadi,
    lekin `{` dan keyin uzilgan yozuv ham `{}` ga o'xshash bo'lib qolishi mumkin.
    """
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=10.0, poll_seconds=2.0)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat,
                     sleeper=kutish_bilan(soat, {1: lambda: paket_yoz(out,
                                                                     manifest_text=manifest_text)}))
    assert res.ok is False, "minimal shakli yo'q manifest TAYYOR deb qabul qilindi"
    assert res.bundle_dir is None
    assert MANIFEST_FILE in res.errors[0].detail


def test_kuprik_TOLIQ_sxemani_tekshirmaydi_faqat_MINIMAL_shaklni(tmp_path):
    """⚠️ MAS'ULIYAT CHEGARASI: mazmun `runtime_bundle` ning ishi, ko'prikning EMAS.

    Minimal shakl (`manifest_version` + bo'sh bo'lmagan `files`) bor, lekin Phase 4 validatori
    bu manifestni RAD etadi: `sha256` xato uzunlikda, `files[]` da shartnomada yo'q kalit
    (`source_copy` — MANBA PROVENANSI, Phase 2 da ATAYLAB taqiqlangan) va shartnomada yo'q
    fayl nomi bor. Ko'prik baribir «yozish TUGADI» deydi — chunki uning savoli SHU va ikkinchi
    validator yasash ikkisini bir kun ajratib qo'yardi.
    """
    buzuq = json.dumps({
        "manifest_version": MANIFEST_VERSION,
        "files": [{"name": "allaqanday.json", "bytes": "-7", "sha256": "QISQA",
                   "source_copy": "C:\baza"}],
        "notes": [""],
        "ortiqcha_kalit": "Phase 4 validatori buni ham rad etadi",
    }, ensure_ascii=False)
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat,
                     sleeper=kutish_bilan(soat, {1: lambda: paket_yoz(out, manifest_text=buzuq)}))
    assert res.ok is True, "ko'prik SXEMA validatoriga aylanib ketdi"
    # ⚠️ Mazmun hukmini YADRO chiqaradi — ko'prik aytgan «tayyor» «to'g'ri» DEGANI EMAS.
    assert not rb.validate_runtime_bundle(str(out)).ok,         "fikstura: Phase 4 validatori bu manifestni RAD etishi kerak"


def test_HAQIQIY_TOLIQ_manifest_QABUL_QILINADI(tmp_path):
    """⚠️⚠️ YOLG'ON IJOBIY DARVOZASI: minimal shakl talabi haqiqiy paketni RAD ETMASLIGI SHART.

    Fikstura — Phase 4 ning O'Z generatoridan olingan SOG'LOM paket (`discovery_1c_runtime_mock`),
    ya'ni manifest ham uning O'Z yozuvchisi bilan qurilgan. Agar minimal shakl talabi haqiqiy
    manifestdan ajralib ketsa, bu test darhol QIZIL bo'ladi.
    """
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat,
                     sleeper=kutish_bilan(soat, {1: lambda: M.paket_sog_lom(str(out))}))
    assert res.ok is True, "HAQIQIY to'liq manifest RAD etildi — yolg'on ijobiy"
    assert rb.validate_runtime_bundle(str(out)).ok, "fikstura: paket Phase 4 ga ko'ra SOG'LOM"


def test_manifest_json_boolmasa_tayyor_emas(tmp_path):
    """JSON ildizi MASSIV bo'lsa ham «to'liq yozildi» deb hisoblanmaydi."""
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=10.0, poll_seconds=2.0)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat,
                     sleeper=kutish_bilan(soat, {1: lambda: paket_yoz(out, manifest_text="[]")}))
    assert res.ok is False


def test_bom_bilan_yozilgan_manifest_qabul_qilinadi(tmp_path):
    """⚠️ 1C/PowerShell BOM qo'shadi — bu BUZILGAN fayl EMAS (yadroda ham shu qoida)."""
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER)
    out = pathlib.Path(plan.output_dir)

    def bom_bilan_yoz():
        paket_yoz(out)
        (out / MANIFEST_FILE).write_bytes(b"\xef\xbb\xbf" + json.dumps(MANIFEST_DOC).encode())

    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, {1: bom_bilan_yoz}))
    assert res.ok is True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7b. NORMAL `watch_folder` OQIMI (`cb.watch`) — AGENT HECH NARSA ISHGA TUSHIRMAYDI
#
# ⚠️ NEGA ALOHIDA BO'LIM: yuqoridagi 7-bo'lim `collect(route=watch_folder)` ni o'lchaydi, ya'ni
#    `.epf` ham, BO'SH chiqish papkasi ham TALAB QILINADIGAN yo'lni. SHIPPED oqim esa boshqa:
#    `.epf` UMUMAN YO'Q (operator yig'uvchini o'zi yurgizadi) va papkada tayyor paket turgan
#    bo'lishi MUMKIN. Avval shipped oqim ko'prikni chetlab o'tardi — aynan shu nuqson
#    tuzatilgani uchun bu bo'lim bor.
# ══════════════════════════════════════════════════════════════════════════════════════════
def kuzatish_rejasi(papka, **kw) -> cb.WatchPlan:
    """Kuzatish rejasi. ⚠️ `.epf` ham, `1cv8.exe` ham KERAK EMAS — agent hech narsa
    ishga tushirmaydi."""
    maydonlar = dict(bundle_dir=str(papka), mode=MODE_METADATA_ONLY,
                     timeout_seconds=10.0, poll_seconds=2.0)
    maydonlar.update(kw)
    return cb.WatchPlan(**maydonlar)


def test_watch_rejasida_epf_ham_exe_ham_kredensial_ham_YOQ():
    """⚠️ Bu yo'lda agent hech narsa ishga tushirmaydi, demak ishga tushirish maydonlari ham
    bo'lmasligi SHART: maydon bo'lsa, bir kun kimdir uni to'ldiradi."""
    maydonlar = {f.name for f in dataclasses.fields(cb.WatchPlan)}
    assert maydonlar == {"bundle_dir", "mode", "timeout_seconds", "poll_seconds"}, maydonlar
    taqiq = re.compile(r"(?i)parol|password|pwd|user|login|epf|exe|locator|auth")
    assert not [m for m in maydonlar if taqiq.search(m)], maydonlar


def test_watch_bosh_papka_YIQILISH_emas_balki_KUTISH(tmp_path):
    """⚠️⚠️ BRIEF §6C: bo'sh papka — kutishning BOSHLANG'ICH holati, yiqilish EMAS. Avval UI
         bo'sh papkani darhol «paket yo'q» deb hukm qilardi, ya'ni yig'uvchi hali yozmagan
         NORMAL holat yiqilish bo'lib ko'rinardi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    assert cb.watch_preflight(kuzatish_rejasi(papka)) is None, \
        "bo'sh papka DARVOZADA to'xtatilmasligi kerak"
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka), clock=soat,
                   sleeper=kutish_bilan(soat, {2: lambda: paket_yoz(papka)}))
    assert res.ok is True, "kutish davomida yozilgan paket QABUL QILINADI"
    assert soat.sleeps, "kutish ROSTDAN bo'ldi (hodisa darhol qaytmadi)"


def test_watch_bosh_papka_vaqt_tugasa_FAILED_TIMEOUT(tmp_path):
    """⚠️ Cheksiz kutish YO'Q va yakun `FAILED_TIMEOUT` — `FAILED_COLLECTOR_UNAVAILABLE` EMAS:
    yig'uvchi hali ishlab turgan bo'lishi MUMKIN va «javob bermadi» degan hukm noto'g'ri
    bo'lardi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka, timeout_seconds=8.0), clock=soat, sleeper=soat.sleep)
    assert res.ok is False
    assert res.state_hint == st.FAILED_TIMEOUT
    assert res.state_hint != st.FAILED_COLLECTOR_UNAVAILABLE
    assert xato_kodlari(res) == [cb.CODE_WAIT_TIMEOUT]
    assert res.bundle_dir is None, "yiqilgan yurish paket DA'VO QILMAYDI"
    assert soat.t >= 8.0, "vaqt chegarasi ROSTDAN ishladi"


def test_watch_papka_yoq_bolsa_KUTMAYDI_balki_darhol_yiqiladi(tmp_path):
    """⚠️ FAIL-CLOSED va TEZ: kutish papkani YARATMAYDI, demak kutish bu holatni hech qachon
    tuzatmaydi. Soniyalarni behuda sarflash operatorni chalg'itardi."""
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(tmp_path / "umuman-yoq"), clock=soat, sleeper=soat.sleep)
    assert res.ok is False
    assert res.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert res.state_hint != st.FAILED_NO_1C, "1C bor-yo'qligi haqida bu HECH NARSA demaydi"
    assert xato_kodlari(res) == [cb.CODE_BUNDLE_DIR_MISSING]
    assert soat.sleeps == [], "papka yo'q bo'lsa kutish UMUMAN boshlanmaydi"


def test_watch_yarim_yozilgan_manifest_TAYYOR_deb_hisoblanmaydi(tmp_path):
    """⚠️⚠️ PHASE 4 NUQSONI: yarim yozilgan `manifest.json` «paket bor» deb qabul qilinsa,
         yurish yolg'on SUCCESS berardi. Shipped oqim endi AYNI shu isbotdan o'tadi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    paket_yoz(papka, manifest_text='{"manifest_version": "binos-1c-mani')
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka, timeout_seconds=8.0), clock=soat, sleeper=soat.sleep)
    assert res.ok is False
    assert res.state_hint == st.FAILED_TIMEOUT
    assert res.bundle_dir is None


def test_watch_tolik_paket_ok_va_chiqish_kodi_YOQ(tmp_path):
    """⚠️ `exit_code is None`: jarayon agentda emas. Uni `0` deb yozish «biz ishga tushirdik»
    degan YOLG'ON da'vo bo'lardi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    paket_yoz(papka)
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka), clock=soat, sleeper=soat.sleep)
    assert res.ok is True
    assert res.route == ROUTE_WATCH_FOLDER
    assert res.bundle_dir == str(papka)
    assert res.exit_code is None and res.exit_code_text is None


def test_watch_ok_bolganda_ham_OPERATOR_ISHGA_TUSHIRGANI_yoziladi(tmp_path):
    """⚠️⚠️ YO'L HAQQONIYLIGI (brief §7): muvaffaqiyatli yurishda ham «agent 1C ni ishga
         tushirMADI» fakti izohga tushadi. Faqat yiqilishda aytish «muvaffaqiyat avtomatik
         bo'ldi» degan jim da'vo bo'lardi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    paket_yoz(papka)
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka), clock=soat, sleeper=soat.sleep)
    assert cb.OPERATOR_RAN_COLLECTOR_NOTE in res.notes
    # ⚠️ Paketning YANGILIGI isbotlanmagani ham ochiq aytiladi.
    assert cb.WATCH_FOLDER_PROVENANCE_NOTE in res.notes


def test_watch_kutish_hodisasi_HAR_olchovda_chaqiriladi(tmp_path):
    """⚠️ KUTISH KO'RINADI: bo'sh papkada agent jim turardi va operator «osilgan» deb
    o'qirdi. Hodisa QAROR QABUL QILMAYDI — faqat xabar beradi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    soat = SoxtaSoat()
    hodisalar: list[cb.WaitTick] = []
    res = cb.watch(kuzatish_rejasi(papka, timeout_seconds=8.0, poll_seconds=2.0),
                   clock=soat, sleeper=soat.sleep, on_wait=hodisalar.append)
    assert res.state_hint == st.FAILED_TIMEOUT
    assert len(hodisalar) == len(soat.sleeps) >= 3
    assert [t.elapsed_seconds for t in hodisalar] == sorted(
        t.elapsed_seconds for t in hodisalar), "o'tgan vaqt ORQAGA ketmaydi"
    assert all(MANIFEST_FILE in t.missing for t in hodisalar)


def test_kutish_hodisasining_matnida_YOL_ham_SIR_ham_YOQ(tmp_path):
    """⚠️ `WaitTick.human()` ekrandan jurnalga ko'chadi: unda yo'l bo'lmasligi SHART."""
    papka = tmp_path / "maxfiy-kuzatilgan"
    papka.mkdir()
    soat = SoxtaSoat()
    hodisalar: list[cb.WaitTick] = []
    cb.watch(kuzatish_rejasi(papka, timeout_seconds=6.0), clock=soat, sleeper=soat.sleep,
             on_wait=hodisalar.append)
    for t in hodisalar:
        matn = t.human()
        assert str(papka) not in matn
        assert not redaction.scan(matn), [str(f) for f in redaction.scan(matn)]


def test_watch_notogri_reja_ICHKI_NUQSON_deb_yoziladi(tmp_path):
    """⚠️ Nol yoki manfiy kutish — «cheksiz kut» DEGANI EMAS: bu agentning nuqsoni."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    soat = SoxtaSoat()
    for kw in ({"timeout_seconds": 0.0}, {"poll_seconds": 0.0}, {"mode": "oylab-topilgan"}):
        res = cb.watch(kuzatish_rejasi(papka, **kw), clock=soat, sleeper=soat.sleep)
        assert res.ok is False and res.state_hint == st.FAILED_INTERNAL, kw
        assert xato_kodlari(res) == [cb.CODE_BAD_PLAN], kw
    # ⚠️ Umuman boshqa tur berilsa ham ISTISNO emas, ANIQ yiqilish.
    res = cb.watch_preflight(object())            # type: ignore[arg-type]
    assert res is not None and res.state_hint == st.FAILED_INTERNAL


def test_watch_yiqilishlari_METADATA_DISCOVERY_dan_yoziladi():
    """⚠️ Chaqiruvchi (`ui._collect`) zanjirni `METADATA_DISCOVERY` ga keltirib qo'yib `watch`
    ni chaqiradi. Ro'yxat kengaysa bu yerda ham, modul import paytida ham yiqiladi."""
    assert set(cb.WATCH_STATE_HINTS) == {st.FAILED_COLLECTOR_UNAVAILABLE, st.FAILED_TIMEOUT,
                                         st.FAILED_INTERNAL}
    for h in cb.WATCH_STATE_HINTS:
        assert cb.HINT_SOURCE_STATE[h] == st.METADATA_DISCOVERY
        assert st.can_transition(st.METADATA_DISCOVERY, h)


def test_watch_yozuvlari_agent_status_ga_SIRDAN_TOZA_tushadi(tmp_path):
    """⚠️ ZANJIR ISBOTI: kuzatish yo'lining HAMMA yozuvi (`BATCH_EXECUTE_NOT_ATTEMPTED` ham)
    `agent_status.json` validatoridan va `redact.scan` dan O'TADI."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka, timeout_seconds=4.0), clock=soat, sleeper=soat.sleep)
    run = ss.new_run("agent-kuzatuv-1", now=T0)
    for holat in (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                  st.METADATA_DISCOVERY):
        run = run.advance(holat, now=T0)
    run = run.with_route(res.route)
    run = run.with_error(cb.SCOPE_BATCH, cb.CODE_BATCH_NOT_ATTEMPTED,
                         cb.BATCH_NOT_ATTEMPTED_REASON)
    for n in cb.WATCH_FOLDER_OPERATOR_STEPS:
        run = run.with_note(n)
    for e in res.errors:
        run = run.with_error(e.scope, e.code, e.detail)
    for n in res.notes:
        run = run.with_note(n)
    run = run.advance(res.state_hint, now=T0, note="kuzatilgan papka paket bermadi")
    doc = json.loads(run.to_json())        # ⚠️ validator + `redact.scan` shu yerda ishlaydi
    assert doc["route"] == ROUTE_WATCH_FOLDER
    assert cb.CODE_BATCH_NOT_ATTEMPTED in [e["code"] for e in doc["errors"]]
    assert doc["state"] == st.FAILED_TIMEOUT


def test_operator_qadamlari_YIGUVCHI_MANBASINI_va_CHAQIRUVNI_aytadi():
    """⚠️ Brief §4: operatorga QAYSI yig'uvchini va QAYSI papkani ishlatishi AYTILADI.
    Fayl nomi va chaqiruv nomi — ko'prikda, bitta joyda."""
    matn = "\n".join(cb.WATCH_FOLDER_OPERATOR_STEPS)
    assert cb.COLLECTOR_SOURCE_FILE in matn
    assert cb.COLLECTOR_ENTRY_POINT in matn
    assert MANIFEST_FILE in matn, "tugallanish belgisi aytilmagan"
    assert "--headless" in matn, "qaysi papka ekani aytilmagan"
    # ⚠️ Papkaning HAQIQIY yo'li matnda bo'lmaydi: u `redact.scan` ni bloklardi.
    assert not redaction.scan(matn), [str(f) for f in redaction.scan(matn)]


def test_koprik_korsatgan_KIRISH_NUQTASI_yiguvchi_manbasida_ROSTDAN_bor():
    """⚠️⚠️ ENG MUHIM HUJJAT TESTI: operatorga aytilgan chaqiruv MANBADA bo'lmasa, ko'rsatma
         bajarilmas bo'lib qolardi va operator «agent yolg'on aytdi» holatida qolardi."""
    assert _YIGUVCHI_MANBA.is_file(), str(_YIGUVCHI_MANBA)
    bsl = _YIGUVCHI_MANBA.read_text(encoding="utf-8")
    assert f"Функция {cb.COLLECTOR_ENTRY_POINT}(" in bsl, cb.COLLECTOR_ENTRY_POINT


def test_watch_TUGALLANGAN_lekin_TOLIQ_EMAS_paket_VALIDATORGA_uzatiladi(tmp_path):
    """⚠️⚠️ DALILNI SAQLASH: tugallanish belgisi TO'LIQ, lekin majburiy fayl yetishmasa, bu
         KUTISH bilan tuzalmaydigan ANIQ javob. Shu bois paket UZATILADI — hukmni
         `runtime_bundle` validatori ANIQ nomi bilan chiqaradi va buzuq paket `bundle/` da
         DALIL bo'lib saqlanadi.
    ⚠️ Aks holda ikki narsa buzilardi: sabab «chiqish to'liq emas» dan «vaqt tugadi» ga
       ALMASHARDI va yagona dalil YO'Q QILINARDI.
    """
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    paket_yoz(papka)
    yoq = [n for n in REQUIRED_FILES if n != MANIFEST_FILE][0]
    (papka / yoq).unlink()
    soat = SoxtaSoat()
    res = cb.watch(kuzatish_rejasi(papka), clock=soat, sleeper=soat.sleep)
    assert res.ok is True, "paket UZATILADI — hukm validatorning ishi"
    assert res.bundle_dir == str(papka)
    # ⚠️ LEKIN JIM O'TMAYDI: nima yetishmaganini izoh AYTADI.
    izohlar = " ".join(res.notes)
    assert yoq in izohlar and "UZATILADI" in izohlar
    assert "DALIL" in izohlar


def test_collect_watch_folder_da_qoida_BOSHQA_va_bu_ATAYLAB(tmp_path):
    """⚠️⚠️ IKKI QOIDA — IKKI XIL EGALIK. `collect(route=watch_folder)` da chiqish papkasi
         AGENTNING talabi bilan BO'SH bo'lgan, demak fayllarning PAYDO BO'LISHI tugallanishning
         xavfsiz o'lchovi va u TALAB qilinadi. `watch()` da papka OPERATORNING va unda paket
         agent ko'rmagan holda paydo bo'lgan bo'lishi mumkin, shu bois o'lchov faqat
         tugallanish belgisiga qaraydi.
    ⚠️ Bu test farqni QULFLAYDI: u «nusxa ikkiga ajralib ketdi» holatini tutadi."""
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=8.0)
    out = pathlib.Path(plan.output_dir)
    yoq = [n for n in REQUIRED_FILES if n != MANIFEST_FILE][0]

    def toliqsiz_yoz() -> None:
        paket_yoz(out)
        (out / yoq).unlink()

    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=kutish_bilan(soat, {1: toliqsiz_yoz}))
    assert res.ok is False, "paketli-kuzatuv yo'lida HAMMA majburiy fayl TALAB qilinadi"
    assert res.state_hint == st.FAILED_TIMEOUT


def test_QOTIB_QOLGAN_soat_ham_CHEKSIZ_kutishga_aylanmaydi(tmp_path):
    """⚠️⚠️ FAIL-CLOSED ZAXIRA DARVOZASI: `clock` KIRISHDAN keladi, demak u qotib qolgan
         bo'lishi mumkin (doim bir xil qiymat). Faqat vaqtga tayangan halqa bunday soatda
         CHEKSIZ aylanardi — ya'ni «cheksiz kutish YO'Q» qoidasi soat sozligiga BOG'LIQ bo'lib
         qolardi. O'lchov soni chegarasi shu bog'liqlikni UZADI.
    ⚠️ Bu darvoza SOZ soatda hech qachon birinchi bo'lib urmaydi (zaxira ikki o'lchov), ya'ni
       haqiqiy xulq o'zgarmaydi — buni yuqoridagi vaqt testlari isbotlaydi."""
    papka = tmp_path / "kuzatilgan"
    papka.mkdir()
    uyqular: list[float] = []
    res = cb.watch(kuzatish_rejasi(papka, timeout_seconds=10.0, poll_seconds=2.0),
                   clock=lambda: 0.0, sleeper=uyqular.append)
    assert res.ok is False and res.state_hint == st.FAILED_TIMEOUT
    assert xato_kodlari(res) == [cb.CODE_WAIT_TIMEOUT]
    # ⚠️ O'lchov soni `timeout/poll + 2` dan oshmaydi: halqa CHEKSIZ emas.
    assert len(uyqular) <= int(10.0 / 2.0) + 2


def test_batch_execute_URINILMAGANI_SABABI_uchta_boshliqni_sanaydi():
    """⚠️ «Yiqildi» va «urinilmadi» BOSHQA narsa, va sabab MAVHUM bo'lmasligi kerak: uchta
    bo'shliqning HAR BIRI sanab o'tiladi (`.epf` yo'q · BSL kirish nuqtasi yo'q · parol
    darvozasi yopiq)."""
    sabab = cb.BATCH_NOT_ATTEMPTED_REASON
    assert "URINILMADI" in sabab
    assert "`.epf`" in sabab and "YO'Q" in sabab
    assert "kirish nuqtasi" in sabab
    assert "fail-closed" in sabab
    assert "ARGUMENT" in sabab
    assert not redaction.scan(sabab), [str(f) for f in redaction.scan(sabab)]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8. NATIJA SHARTNOMASI — FAIL-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_natija_shartnomasi_jimgina_yiqilishga_yol_bermaydi():
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route=ROUTE_WATCH_FOLDER, ok=False)            # hint YO'Q
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route=ROUTE_WATCH_FOLDER, ok=True)             # bundle_dir YO'Q
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route="com", ok=True, bundle_dir="x")           # noma'lum yo'l
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route=ROUTE_WATCH_FOLDER, ok=False,
                        state_hint="COMPLETE")                         # yiqilish EMAS
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route=ROUTE_WATCH_FOLDER, ok=False,
                        state_hint="FAILED_NIMADIR")                   # o'ylab topilgan nom
    with pytest.raises(cb.BridgeError):
        cb.BridgeResult(route=ROUTE_WATCH_FOLDER, ok=False,
                        state_hint=st.FAILED_TIMEOUT, bundle_dir="x")   # yarim paket


def test_hamma_state_hint_haqiqiy_yiqilish_holati(tmp_path):
    """Hamma yiqilish yo'lini bosib o'tib, `state_hint` lar `states.py` da BORLIGINI isbotlash."""
    soat = SoxtaSoat()
    rejalar = [
        reja(tmp_path / "a", epf_path="yoq.epf"),
        reja(tmp_path / "b", exe_path="yoq.exe"),
        reja(tmp_path / "c", infobase_locator=""),
        reja(tmp_path / "d", requires_auth="unknown"),
        reja(tmp_path / "e", infobase_kind="server"),
        reja(tmp_path / "f", mode=MODE_APPROVED_PROBES),
        reja(tmp_path / "g", infobase_locator='D:\\a"b'),
        reja(tmp_path / "h", route=ROUTE_WATCH_FOLDER, timeout_seconds=4.0),
    ]
    for plan in rejalar:
        res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
        assert res.ok is False
        assert st.is_failure(res.state_hint)
        assert res.errors, "yiqilish ANIQ xato yozuvi bilan birga keladi"


def test_determinizm_bir_xil_kirish_bir_xil_natija(tmp_path):
    """⚠️ Fayl tizimi O'ZGARMAGAN holda ikki yurish AYNI natija beradi (vaqt KIRISHDAN)."""
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER, timeout_seconds=6.0, poll_seconds=2.0)
    natijalar = []
    for _ in range(2):
        soat = SoxtaSoat()
        natijalar.append(cb.collect(plan, clock=soat, sleeper=soat.sleep))
    assert natijalar[0] == natijalar[1]
    assert natijalar[0].state_hint == st.FAILED_TIMEOUT


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9. QUVUR BILAN BOG'LANISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_har_bir_state_hint_belgilangan_holatdan_otishi_mumkin():
    """⚠️ SHARTNOMA QULFI: `HINT_SOURCE_STATE` holat mashinasidan ajralib ketmasin.

    Phase 4 darsi: jadval berilgan, kalit nomlari berilmagan edi va ikki agent bo'shliqni
    har xil to'ldirdi. Bu yerda esa «qaysi sababni qaysi holatdan yozish kerak» savoliga
    javob KOD ichida va u `states.TRANSITIONS` bilan tekshiriladi.
    """
    for hint, manba in cb.HINT_SOURCE_STATE.items():
        assert st.is_failure(hint)
        assert st.can_transition(manba, hint), (manba, hint)


def test_koprik_qaytaradigan_hamma_hint_jadvalda_bor(tmp_path):
    """Ko'prik HAQIQATDA qaytaradigan har bir sabab uchun manba holati YOZILGAN bo'lsin."""
    soat = SoxtaSoat()
    rejalar = [
        reja(tmp_path / "a", epf_path="yoq.epf"),                       # COLLECTOR_UNAVAILABLE
        reja(tmp_path / "b", exe_path="yoq.exe"),                       # NO_1C
        reja(tmp_path / "c", infobase_locator=""),                      # NO_TARGET
        reja(tmp_path / "d", requires_auth="true"),                     # AUTH_REQUIRED
        reja(tmp_path / "e", output_dir=str(tmp_path / "e" / "yoq")),   # SAFETY
        reja(tmp_path / "f", route="com_connector"),                    # INTERNAL
        reja(tmp_path / "g", route=ROUTE_WATCH_FOLDER,
             timeout_seconds=4.0),                                      # TIMEOUT
    ]
    kuzatilgan = set()
    for plan in rejalar:
        res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
        assert res.state_hint in cb.HINT_SOURCE_STATE, res.state_hint
        kuzatilgan.add(res.state_hint)
    assert kuzatilgan == set(cb.HINT_SOURCE_STATE), set(cb.HINT_SOURCE_STATE) - kuzatilgan


def test_preflight_jarayonsiz_ayni_darvozani_beradi(tmp_path):
    """⚠️ `preflight` quvur uchun OCHIQ: sababni O'Z holatidan yozish uchun ERTA chaqiriladi.

    U `collect` bilan AYNI natijani beradi, chunki `collect` aynan shu funksiyani chaqiradi —
    ikki nusxa bo'lsa biri zaifroq tekshiradigan yo'l bo'lib qolardi.
    """
    plan = reja(tmp_path, requires_auth="unknown")
    oldin = cb.preflight(plan)
    assert oldin is not None and oldin.state_hint == st.FAILED_AUTH_REQUIRED
    soat = SoxtaSoat()
    keyin = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert oldin == keyin


def test_preflight_tolik_rejada_yol_ochadi(tmp_path):
    assert cb.preflight(reja(tmp_path)) is None


def test_kuprik_xatolari_agent_status_ga_yoziladi(tmp_path):
    """⚠️ ZANJIR ISBOTI: ko'prik yozuvlari `agent_status.json` ga TUSHADI va sir darvozasidan
    o'tadi. Agar `detail` ga xom yo'l tushsa, `redact.scan` butun faylni RAD etardi."""
    soat = SoxtaSoat()
    res = cb.collect(reja(tmp_path, exe_path=str(tmp_path / "yoq" / "1cv8.exe")),
                     clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert cb.HINT_SOURCE_STATE[res.state_hint] == st.ENVIRONMENT_SCAN
    run = ss.new_run("agent-koprik-1", now=T0)
    run = run.advance(st.ENVIRONMENT_SCAN, now=T0)
    run = run.with_route(res.route)
    for e in res.errors:
        run = run.with_error(e.scope, e.code, e.detail)
    for n in res.notes:
        run = run.with_note(n)
    run = run.advance(st.FAILED_NO_1C, now=T0, note="ko'prik: 1C ijro fayli topilmadi")
    doc = json.loads(run.to_json())        # ⚠️ validator + `redact.scan` shu yerda ishlaydi
    assert doc["state"] == st.FAILED_NO_1C
    assert doc["terminal"] == "true"
    assert doc["read_only"] == "true"
    assert [e["code"] for e in doc["errors"]] == [cb.CODE_EXE_MISSING]


def test_hamma_xato_yozuvi_va_izoh_sirdan_toza(tmp_path):
    """⚠️ Har bir yiqilish yo'li uchun `redact.scan` BO'SH bo'lishi SHART."""
    soat = SoxtaSoat()
    rejalar = [
        reja(tmp_path / "a", epf_path=str(tmp_path / "a" / "yoq.epf")),
        reja(tmp_path / "b", output_dir=str(tmp_path / "b" / "yoq")),
        reja(tmp_path / "c", requires_auth="true"),
        reja(tmp_path / "d", infobase_locator='D:\\maxfiy"baza'),
        reja(tmp_path / "e", route=ROUTE_WATCH_FOLDER, timeout_seconds=4.0),
    ]
    for plan in rejalar:
        res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
        hujjat = {"errors": [e.to_doc() for e in res.errors], "notes": list(res.notes)}
        assert not redaction.scan(hujjat), [str(f) for f in redaction.scan(hujjat)]


def test_xato_kodlari_status_shartnomasiga_mos():
    """⚠️ Kodlar `status.ERROR_CODE_RE` ga MOS bo'lmasa, ular hujjatga yozilmay qolardi."""
    kodlar = [v for k, v in vars(cb).items() if k.startswith("CODE_")]
    assert len(kodlar) >= 10
    for kod in kodlar:
        assert ss.ERROR_CODE_RE.fullmatch(kod), kod


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10. XAVFSIZLIK INVARIANTLARI (statik)
# ══════════════════════════════════════════════════════════════════════════════════════════
_TAQIQLANGAN_MODULLAR = frozenset({
    "socket", "requests", "urllib", "http", "ssl", "ftplib", "smtplib", "telnetlib",
    "asyncio", "win32com", "pythoncom", "win32api", "ctypes",
})
_RUXSAT_ETILGAN_MODULLAR = frozenset({
    "json", "os", "re", "subprocess", "time", "dataclasses", "typing", "__future__",
})


def test_tarmoq_importi_yoq_va_ruxsat_etilganlardan_boshqasi_yoq():
    """⚠️ Offline-first: `socket`/`urllib`/`http.client`/`requests` BO'LMASIN.

    ⚠️ `subprocess` — RUXSAT ETILGAN va bu YAGONA joy: biz 1C ni ishga tushiramiz,
       o'zboshimcha kod bajarmaymiz (modul docstringidagi asos).
    ⚠️ Tekshiruv `ast` bilan: oddiy matn qidiruvi docstringdagi ESLATMAni ham topardi.
    """
    imported: set[str] = set()
    for node in ast.walk(ast.parse(_SOURCE)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)
    roots = {n.split(".")[0] for n in imported}
    assert not (roots & _TAQIQLANGAN_MODULLAR), roots & _TAQIQLANGAN_MODULLAR
    assert roots <= _RUXSAT_ETILGAN_MODULLAR, roots - _RUXSAT_ETILGAN_MODULLAR


def test_subprocess_faqat_bitta_joyda_chaqiriladi():
    """⚠️ `subprocess` ning HAMMA ishlatilishi `run_1c_batch` ichida bo'lsin.

    Ikkinchi chaqiruv joyi — ikkinchi xavfsizlik yuzasi: u yerda `shell`, `DEVNULL` va
    taqiqlangan kalit darvozalari takrorlanmasligi mumkin.
    """
    tree = ast.parse(_SOURCE)
    joylar: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for ichki in ast.walk(node):
                if (isinstance(ichki, ast.Attribute) and isinstance(ichki.value, ast.Name)
                        and ichki.value.id == "subprocess"):
                    joylar.append(node.name)
                    break
    assert set(joylar) == {"run_1c_batch"}, joylar


def test_yozish_va_com_chaqiruvlari_yoq():
    """FAQAT O'QISH: ko'prik fayl YOZMAYDI, papka yaratmaydi, COM obyekti ochmaydi.

    ⚠️ 1C tomonidagi yozuv taqiqlari (`Записать`/`Провести`/`Удалить`) `epf_audit.py` da
       majburlanadi; bu yerda AGENT TOMONI tekshiriladi.
    """
    taqiq = frozenset({
        "mkdir", "makedirs", "remove", "unlink", "rmtree", "rename", "write_text",
        "write_bytes", "CreateObject", "Dispatch", "DispatchEx", "Записать", "Провести",
        "Удалить", "system", "startfile", "Popen", "eval", "exec", "__import__",
    })
    used: set[str] = set()
    for node in ast.walk(ast.parse(_SOURCE)):
        if isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Name):
            used.add(node.id)
    assert not (used & taqiq), used & taqiq


def test_fayl_ochish_faqat_oqish_rejimida():
    """⚠️ `open(...)` FAQAT `"rb"` bilan: ko'prik hech narsa YOZMAYDI."""
    for node in ast.walk(ast.parse(_SOURCE)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open":
            rejimlar = [a.value for a in node.args[1:] if isinstance(a, ast.Constant)]
            rejimlar += [k.value.value for k in node.keywords
                         if k.arg == "mode" and isinstance(k.value, ast.Constant)]
            assert rejimlar == ["rb"], rejimlar


# ══════════════════════════════════════════════════════════════════════════════════════════
# 11. `AGENT_OPERATOR_FLOW.md` — OPERATOR HUJJATI KOD BILAN BOG'LANGAN
#
# ⚠️⚠️ NEGA HUJJAT TESTLANADI: kod bilan bog'lanmagan operator hujjati jimgina eskiradi va
#      «qo'llanma bor» degan yolg'on xotirjamlik qoldiradi. Phase 4 darsi AYNAN shu. Shu bois
#      bu yerda hujjatning HAR BIR da'vosi KODDAN tekshiriladi, ro'yxat emas.
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def oqim() -> str:
    assert _OQIM_HUJJATI.is_file(), str(_OQIM_HUJJATI)
    return _OQIM_HUJJATI.read_text(encoding="utf-8")


def test_oqim_hujjati_REPODA_mavjud(oqim):
    assert oqim.strip(), "hujjat bo'sh"


@pytest.mark.parametrize("marshrut", [ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER])
def test_oqim_marshrut_nomlarini_AYNAN_shartnomadek_yozadi(oqim, marshrut):
    """⚠️ Nomni «chiroyliroq» yozish operatorni hisobotdagi (`agent_status.json`) qiymat
    bilan solishtira olmas holatga qo'yardi."""
    assert marshrut in oqim, marshrut


def test_oqim_BOSHIDA_batch_execute_ning_YOPIQLIGINI_aytadi(oqim):
    """⚠️ Brief talabi: bu fakt hujjatning BOSHIDA turishi kerak, oxirida emas — operator
    eng avval shuni bilishi kerak."""
    bosh = oqim[:oqim.index("## 1.")]
    assert ROUTE_BATCH_EXECUTE in bosh
    assert "FOYDALANIB BO'LMAYDI" in bosh
    assert "BO'SHLIQ" in bosh.upper()


@pytest.mark.parametrize("dalil", ["ПараметрЗапуска", "ВыполнитьРазведку", "`.epf`",
                                   "requires_auth"])
def test_oqim_UCHTA_boshliqni_ANIQ_nomlab_sanaydi(oqim, dalil):
    """⚠️ «Hozir ishlatilmaydi» yetarli emas: NEGA ishlatilmasligi ANIQ nomlar bilan
    yozilishi kerak, aks holda keyingi o'qiydigan odam taxmin qiladi."""
    assert dalil in oqim, dalil


def test_oqim_BITTA_BOSISHDA_AVTOMATIKNI_TAKLIF_QILMAYDI(oqim):
    """⚠️⚠️ BRIEF §7: hujjat «bir bosishda avtomatik» taassurotini BERMASLIGI kerak. Bu
         yerda hisobotning O'Z darvozasidagi AYNI naqshlar ishlatiladi — ikki ro'yxat bir
         kun ajralib ketardi."""
    from app.services.discovery_agent import report as _report
    for nom, rx in _report.AUTOMATIC_CLAIM_PATTERNS:
        uchraydi = rx.search(oqim)
        assert uchraydi is None, f"{nom}: {uchraydi.group(0)!r}"
    # ⚠️ Inkor shaklida esa AYTILISHI SHART: jim qoldirish taklif qilishdan farq qilmaydi.
    #    ⚠️ Naqsh INKOR fe'lini talab qiladi (`TAKLIF QIL(IN)MAYDI`), ya'ni hujjat tasdiq
    #       iborasini chetlab o'tib ham da'voni jimgina qaytarib kirita olmaydi.
    assert re.search(r"(?i)avtomat\w*[^.\n]{0,80}TAKLIF QIL(?:IN)?MAYDI",
                     " ".join(oqim.split())), \
        "hujjat avtomatlashtirish TAKLIF QILMASLIGINI ochiq aytmaydi"


@pytest.mark.parametrize("artefakt", ["agent_status.json", "environment.json", "errors.json",
                                      "agent_manifest.json", "discovery_ai_candidates.json",
                                      "discovery_report.md", "bundle/"])
def test_oqim_artefakt_nomlari_KOD_bilan_MOS(oqim, artefakt):
    """⚠️ Operator papkada KO'RADIGAN nomlar. Bitta harf farq qilsa, u «fayl yo'q» deb
    o'ylab ishlab chiquvchiga qo'ng'iroq qilardi."""
    assert artefakt in oqim, artefakt


def test_oqim_artefakt_royxati_SHARTNOMADAN_ajralib_ketmagan(oqim):
    """⚠️ TESKARI TOMON: koddagi HAR BIR agent artefakti hujjatda SANALGAN bo'lishi kerak —
    aks holda hujjat jimgina eskiradi."""
    from app.services.discovery_agent import AGENT_ARTIFACTS, BUNDLE_SUBDIR
    yoq = [n for n in AGENT_ARTIFACTS if n not in oqim]
    assert not yoq, yoq
    assert f"{BUNDLE_SUBDIR}/" in oqim


def test_oqim_manifest_NOMI_ADASHTIRILMAGANINI_aytadi(oqim):
    """⚠️ `manifest.json` (Phase 4) va `agent_manifest.json` (agent) — BIR XIL NOM, IKKI XIL
    SXEMA bo'lmasligi uchun ajratilgan. Hujjat shu ajrimni aytishi SHART: operator
    `bundle/` ichidagi faylni ildizdagisi bilan adashtirsa, xato hujjatni uzatardi."""
    assert "agent_manifest.json" in oqim
    assert "errors.json" in oqim
    assert "IKKI XIL sxema" in oqim


@pytest.mark.parametrize("holat", [st.FAILED_TIMEOUT, st.FAILED_COLLECTOR_UNAVAILABLE,
                                   st.FAILED_NO_1C, st.FAILED_VALIDATION, st.FAILED_INTERNAL])
def test_oqim_FAQAT_shartnoma_holatlarini_ishlatadi_va_ularni_izohlaydi(oqim, holat):
    """⚠️ Hujjat YANGI holat nomi O'YLAB CHIQARMAYDI (parallel lug'at TAQIQ) va ishlatganini
    IZOHLAYDI: «nima qilish» ustuni bo'sh qolmaydi."""
    assert holat in oqim, holat


def test_oqim_hujjatda_OYLAB_TOPILGAN_holat_nomi_YOQ(oqim):
    """⚠️ TESKARI DARVOZA: hujjatdagi har bir `FAILED_*`/`ABORTED_*` nomi `states.py` da
    ROSTDAN bo'lishi SHART."""
    nomlar = set(re.findall(r"\b(?:FAILED|ABORTED)_[A-Z_]+\b", oqim))
    yoq = sorted(n for n in nomlar if not st.is_known(n))
    assert not yoq, yoq


def test_oqim_presence_verdict_AJRIMINI_aytadi(oqim):
    """⚠️⚠️ `absent` (qaradim va yo'q — JAVOB) va `unknown` (qaray olmadim — javob YO'Q) bir
         xil ko'rsatma BERMAYDI. Hujjat ikkisini ajratmasa, operator `unknown` da bekorga 1C
         o'rnatib yurardi."""
    assert "presence_verdict" in oqim
    assert "`absent`" in oqim and "`unknown`" in oqim
    assert "CHIQARILMAYDI" in oqim


def test_oqim_CHEKSIZ_KUTISH_YOQLIGINI_aytadi(oqim):
    """⚠️ Brief §6C: kutish CHEKLI va buni operator bilishi kerak (`--wait-seconds`)."""
    assert "Cheksiz kutish YO'Q" in oqim
    assert "--wait-seconds" in oqim


def test_oqim_TOZA_PAPKA_talabini_va_SABABINI_aytadi(oqim):
    """⚠️ Bu yo'lning isbotlab bo'lmaydigan joyi: agent paketning AYNI SHU YURISH uchun
    yozilganini isbotlay olmaydi. Talabni sababsiz yozish operatorni ishontirmaydi."""
    assert "TOZA papka" in oqim
    assert "ISBOTLAY OLMAYDI" in oqim


#: ⚠️ ISBOTLANMAGAN DA'VOLAR — matritsa hujjatining ro'yxati bilan AYNI naqsh (`ishlamaydi`
#: ham taqiqlangan: inkor da'vosi ham dalil talab qiladi; to'g'ri ibora — «tekshirib
#: bo'lmaydi»). Ro'yxat ANIQ iboralardan, bitta so'zdan emas.
_ISBOTLANMAGAN: tuple[str, ...] = (
    "ishlaydi", "ishlab turadi", "ishlamaydi", "kompilyatsiya qilinadi",
    "kompilyatsiya qilingan", "runtime tasdiqlangan", "runtime tekshirilgan",
    "production tayyor", "ishlashi tasdiqlangan", "ishlashi kafolatlangan",
    "sinovdan o'tgan", "sinalgan va", "com ishlaydi",
)


@pytest.mark.parametrize("davo", _ISBOTLANMAGAN)
def test_oqim_hujjatida_ISBOTLANMAGAN_DAVO_YOQ(oqim, davo):
    assert davo not in oqim.lower(), \
        f"isbotlanmagan da'vo — «{davo}». To'g'ri holat: `RUNTIME-UNKNOWN`"


def test_oqim_RUNTIME_UNKNOWN_ni_va_1C_YOQLIGINI_ochiq_aytadi(oqim):
    """⚠️ Hujjat to'g'ri yozilgani — yo'l ishga tushishi EMAS. Bu farq OCHIQ turishi kerak."""
    assert "RUNTIME-UNKNOWN" in oqim
    assert "1C:Enterprise YO'Q" in oqim
    for olchov in ("1cv8.exe", "V83.COMConnector", "pywin32"):
        assert olchov in oqim, f"o'lchangan holatda «{olchov}» qayd etilmagan"


def test_oqim_TARMOQ_yoki_bulutli_model_TAKLIF_QILMAYDI(oqim):
    """⚠️ Offline-first: hujjat birorta qadamda tarmoq chaqiruvi taklif qilmasligi kerak."""
    past = oqim.lower()
    for taqiq in ("requests.", "urllib", "http.client", "cloud ai", "openai"):
        assert taqiq not in past, f"hujjat tarmoq/cloud yo'lini eslatgan: «{taqiq}»"


def test_oqim_OPERATOR_va_AGENT_ishini_AJRATADI(oqim):
    """⚠️ Brief §4 va §7: kim nima qilishi hujjatda ADASHTIRILMASLIGI kerak — 4- va
    5-qadamlarni agent BAJARA OLMAYDI va buni hujjat ochiq aytadi."""
    assert "OPERATOR" in oqim and "AGENT" in oqim
    assert "BAJARA OLMAYDI" in oqim
    # ⚠️ Bo'shliq NORMALLASHTIRILADI va kichik harfda izlanadi: hujjat bu gapni satr
    #    ko'chirishi bilan ham yozishi mumkin, MA'NOSI esa o'zgarmasligi kerak.
    assert "agent 1c ni ishga tushirmaydi" in " ".join(oqim.lower().split())


# ══════════════════════════════════════════════════════════════════════════════════════════
# `errors.json` — SXEMA ARALASHUVI (ikki yo'nalish, HOLATDAN MUSTAQIL)
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️⚠️ TESTLAR SHU FAYLDA, chunki o'lchanadigan narsa — KO'PRIK YETKAZGAN `bundle/` ning
#      shartnomasi: ko'prik paketni O'ZGARTIRMASDAN uzatadi (uning docstringi shunday deydi),
#      demak «bundle/ ichida FAQAT Phase 4 hujjati yashaydi» invarianti aynan shu uzatmaning
#      darvozasi. ⚠️ `result_package` ning fiksturalari QAYTA ISHLATILADI (ikkinchi «to'g'ri
#      paket» quruvchisi bir kun shartnomadan ajralib ketardi) va import FUNKSIYA ICHIDA
#      bo'ladi: bu fayl ko'prikning O'Z modulidan boshqa hech narsani modul darajasida
#      talab qilmasligi kerak.

#: UTF-8 BOM — 1C/PowerShell `bundle/` fayllariga shu uch baytni qo'shadi.
#: ⚠️ Darvoza BOM ni OLIB TASHLAYDI, aks holda BOM bilan yozilgan AGENT hujjati
#:    parse bo'lmay, sxema aralashuvi jimgina o'tib ketardi.
_BOM = bytes((0xEF, 0xBB, 0xBF))


def _yiqilgan_paket(bundle):
    """YIQILGAN yurishning natija paketi (`COMPLETE` EMAS) — darvoza shu holatda sinaladi.

    ⚠️ `FAILED_VALIDATION` ATAYLAB tanlangan: buzuq paket bilan haqiqatda shu holat
       chiqadi, va aynan shu holatda Phase 4 hisobotidan FAQAT sir tekshiruvlari olinadi
       (`result_package.BUNDLE_SECRET_CHECKS`) — ya'ni nuqson ko'rinadigan holat.
    ⚠️ Tahlil artefakti YO'Q (`ai_candidates_json=None`): yurish tahlilga YETMAGAN.
    """
    from app.services.discovery_agent import result_package as rp
    from tests import test_agent_result_package as RP

    nomlar = sorted(set(rp.ALWAYS_FILES) | {f"{rp.BUNDLE_SUBDIR}/{n}" for n in bundle})
    s = ss.new_run("run-0001", now=RP.T0)
    for holat in (st.ENVIRONMENT_SCAN, st.TARGET_SELECTION, st.SAFETY_CHECK,
                  st.METADATA_DISCOVERY, st.VALIDATION, st.FAILED_VALIDATION):
        s = s.advance(holat, now=RP.T0, note="sintetik fikstura")
    # ⚠️ `presence_verdict` AYNI skanerdan olinadi — `RP.env_matni()` ham o'sha
    #    `RP.env_scan()` dan quriladi. Avval bu fikstura hukmni UMUMAN yozmasdi, ya'ni
    #    yozuvda standart `unknown`, muhit hujjatida esa `found` turardi: paket o'z-o'ziga
    #    ZID bo'lardi. Yangi tenglik darvozasi (`_check_presence_agreement`) buni TO'G'RI
    #    tutdi — fikstura tuzatildi, darvoza YUMSHATILMADI.
    s = (s.with_route(ROUTE_WATCH_FOLDER).with_bundle_dir(rp.BUNDLE_SUBDIR)
         .with_environment_file(rp.ENVIRONMENT_FILE).with_artifacts(nomlar)
         .with_presence_verdict(RP.env_scan().presence_verdict))
    return rp.ResultPackage.from_parts(
        timestamp=RP.TS, status_json=s.to_json(), environment_json=RP.env_matni(),
        report_md=RP.REPORT_MD, ai_candidates_json=None, bundle=dict(bundle))


@pytest.mark.parametrize("bom", [b"", _BOM],
                         ids=["bom_yoq", "bom_bilan"])
def test_bundle_ichida_AGENT_hujjati_YIQILGAN_yurishda_HAM_RAD_etiladi(bom):
    """⚠️⚠️ NUQSON: `bundle/` ichida AGENT sxemasi YIQILGAN yurishda TUTILMASDI.

    «Bir xil nom, ikki xil sxema ARALASHMAYDI» qoidasining bu tomoni Phase 4
    VALIDATORIGA tayangan edi, yiqilgan yurishda esa `_bundle_problems(complete=False)`
    undan FAQAT sir tekshiruvlarini oladi (rad etilgan paket DALIL bo'lib saqlanishi
    kerak). Natijada `bundle/errors.json` da agentning `binos-agent-errors-v1` hujjati
    tursa, aralashuv UMUMAN tutilmasdi — va aynan yiqilgan yurishda bu xato ehtimoli ENG
    KATTA, chunki xatolarni yozadigan kod IKKI hujjatni ham «errors.json» deb biladi.
    """
    from app.services.discovery_agent import result_package as rp
    from tests import test_agent_result_package as RP

    sog_lom = _yiqilgan_paket(RP.phase4_bundle())
    assert sog_lom.problems() == [], "fikstura: yiqilgan yurishning paketi NUQSONSIZ bo'lsin"

    # ⚠️ ILDIZDAGI agent hujjati `bundle/` ga KO'CHIRILADI — aynan aralashuvning o'zi.
    aralash = dict(RP.phase4_bundle())
    # ⚠️ BOM BILAN HAM: `bundle/` fayllarini 1C/PowerShell yozadi va ular BOM qo'shadi —
    #    BOM ni hisobga olmagan darvoza aynan shu yerda TESHIK qoldirardi (hujjat parse
    #    bo'lmay, aralashuv jimgina o'tib ketardi).
    aralash[rp.ERRORS_FILE] = bom + sog_lom.errors_json().encode("utf-8")
    nuqsonlar = _yiqilgan_paket(aralash).problems()
    assert any(rp.ERRORS_VERSION in p and f"{rp.BUNDLE_SUBDIR}/" in p for p in nuqsonlar), \
        f"`bundle/` dagi AGENT hujjati TUTILMADI: {nuqsonlar}"


def test_ildizda_PHASE4_hujjati_YIQILGAN_yurishda_HAM_RAD_etiladi(tmp_path):
    """Darvozaning IKKINCHI yo'nalishi — u ALLAQACHON holatdan mustaqil edi, va shu test
    uni QULFLAYDI: `validate_agent_errors` ildizdagi faylni har qanday holatda tekshiradi.

    ⚠️ Ikki yo'nalish BIR testda emas, chunki ildizdagi hujjat XOTIRADA almashtirilmaydi:
       u `agent_status.json` dan HOSILA (`ResultPackage.errors_json`), shu bois aralashuv
       faqat DISKDA yasalishi mumkin — va shunday yasalgani ham yaxshi, sababi
       `check_result_package` ROSTDAN papkani o'qiydi.
    """
    from app.services.discovery_agent import result_package as rp
    from tests import test_agent_result_package as RP

    papka = pathlib.Path(_yiqilgan_paket(RP.phase4_bundle()).write(str(tmp_path)))
    assert rp.check_result_package(str(papka)) == [], "fikstura: papka NUQSONSIZ bo'lsin"

    # ⚠️ `bundle/` dagi Phase 4 hujjati ILDIZGA ko'chiriladi (teskari yo'nalish).
    (papka / rp.ERRORS_FILE).write_bytes(RP.phase4_bundle()[rp.ERRORS_FILE])
    nuqsonlar = rp.check_result_package(str(papka))
    assert any(rb.ERRORS_VERSION in p for p in nuqsonlar), \
        f"ildizdagi PHASE 4 hujjati TUTILMADI: {nuqsonlar}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# MATRITSA HUJJATI `route` HAQIDA KOD BILAN ZID YOZMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
#: Integratsiya matritsasi — brief §4 ning odam o'qiydigan tomoni.
_MATRITSA = _REPO / "integrations" / "1c" / "AGENT_INTEGRATION_MATRIX.md"


def test_matritsa_ETIROZ_bolimi_route_ni_KOD_BILAN_BIR_XIL_tushuntiradi(tmp_path):
    """⚠️⚠️ NUQSON: matritsaning «E'TIROZ» bo'limi KOD bilan ZID edi.

    Hujjat «darvoza yiqilganini yozadi va `route` ni `watch_folder` ga qo'yadi» deb yozardi,
    kod esa URINILGAN yo'lni yozadi (`_fail(..., route=ROUTE_BATCH_EXECUTE)`). HUJJAT KODGA
    MOSLANDI, kod hujjatga EMAS — chunki kodning tanlovi haqqoniyroq: `route` hisobotda
    «QAYSI yo'l yiqildi?» savoliga javob beradigan YAGONA maydon, zaxira yo'l esa yiqilish
    paytida hali BAJARILMAGAN (uni ODAM boshlaydi). Bajarilmagan yo'lni «tanlangan» deb
    yozish «o'zi urinib ko'rdi, o'zi o'tdi» degan yolg'on SUCCESS naqshi bo'lardi.

    ⚠️ Test IKKI TOMONNI BIR JOYDA solishtiradi: avval KOD o'lchanadi, keyin hujjat AYNAN
       shu natijani yozganmi deb qaraladi. Faqat matnni tekshirgan test hujjatni kod bilan
       ikkinchi marta ajralib ketishdan saqlamasdi.
    """
    # ── KOD: `.epf` BERILGAN yurishda paketli darvoza yiqildi ────────────────────────────
    plan = reja(tmp_path, route=ROUTE_BATCH_EXECUTE, requires_auth="unknown")
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat, sleeper=soat.sleep, runner=SoxtaYurituvchi())
    assert res.ok is False and res.state_hint == st.FAILED_AUTH_REQUIRED
    assert res.route == ROUTE_BATCH_EXECUTE, \
        "yiqilishda URINILGAN yo'l yozilishi kerak (hujjatning da'vosi shunga tayanadi)"
    assert cb.WATCH_FOLDER_SUGGESTION in res.notes, \
        "zaxira yo'l TAKLIF kanalida (`notes`) bo'lishi kerak — `route` da EMAS"

    # ── HUJJAT: aynan shu natijani yozadi ───────────────────────────────────────────────
    matn = _MATRITSA.read_text(encoding="utf-8")
    bolim = matn.split("## E'TIROZ", 1)[1].split("\n## ", 1)[0]
    normal = " ".join(bolim.split())
    assert f'`route == "{ROUTE_BATCH_EXECUTE}"`' in normal, \
        "hujjat yiqilgan paketli yurishdagi `route` qiymatini AYNAN yozmagan"
    assert "urinilgan yo'l" in normal.lower(), \
        "hujjat `route` ning MA'NOSINI (urinilgan yo'l) tushuntirmagan"
    assert "`notes`" in normal, "taklif kanali (`notes`) hujjatda ko'rsatilmagan"
    assert f'`route == "{ROUTE_WATCH_FOLDER}"`' in normal, \
        "zaxira yo'l QACHON `route` ga yozilishi hujjatda aytilmagan"
