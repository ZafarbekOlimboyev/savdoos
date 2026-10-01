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
from app.services.discovery_1c.runtime_bundle import (MANIFEST_FILE, MODE_APPROVED_PROBES,
                                                      MODE_METADATA_ONLY, REQUIRED_FILES)
from app.services.discovery_agent import ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER
from app.services.discovery_agent import collector_bridge as cb
from app.services.discovery_agent import states as st
from app.services.discovery_agent import status as ss

T0 = "2026-10-01T09:00:00+06:00"

#: Manifestning MAZMUNI ataylab MINIMAL: ko'prik sxemani tekshirmaydi (bu yadroning ishi),
#: u faqat «JSON bo'lib o'qildi + hajmi barqaror» faktini o'lchaydi.
MANIFEST_DOC = {"manifest_version": "binos-1c-manifest-v1", "files": [], "notes": []}


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


def test_kuprik_paket_sxemasini_tekshirmaydi(tmp_path):
    """⚠️ MAS'ULIYAT CHEGARASI: mazmun `runtime_bundle` ning ishi.

    Bo'sh JSON obyektli manifest ham «yozib tugatilgan» hisoblanadi — uni RAD etish ikkinchi
    validator yasardi va ikkisi bir kun ajralib ketardi.
    """
    plan = reja(tmp_path, route=ROUTE_WATCH_FOLDER)
    out = pathlib.Path(plan.output_dir)
    soat = SoxtaSoat()
    res = cb.collect(plan, clock=soat,
                     sleeper=kutish_bilan(soat, {1: lambda: paket_yoz(out, manifest_text="{}")}))
    assert res.ok is True


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
