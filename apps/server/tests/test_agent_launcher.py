# -*- coding: utf-8 -*-
"""`launcher.py` va `detector` ning KLIENT TURLARI shartnomasi — 1C SIZ, SINTETIK.

⚠️ Bu faylning birinchi qoidasi: BIRORTA test HAQIQIY 1C ni ishga tushirmaydi va haqiqiy
   reestrni o'qimaydi. Bu mashinada 1C umuman o'rnatilmagan, shu bois «ochish» yo'li
   SOXTA `Opener` bilan sinaladi, soat va uxlash esa KIRISHDAN beriladi — test birorta
   soniya kutmaydi.
⚠️ ENG MUHIM UCHTA DARVOZA:
     1. `test_manbada_jarayon_oldirish_naqshi_YOQ` — bekor qilish KOOPERATIV: manbada
        jarayonni tugatish naqshi BO'LMASLIGI kerak;
     2. `test_bekor_qilinganda_muvaffaqiyat_QAYTMAYDI` — bekor qilingan yurish tasodifan
        «tayyor» deb qaytmaydi;
     3. `test_avtomatik_bajarish_DEKLARATSIYA` — `.epf` va avtomatik bajarish «ishlaydi»
        deb DA'VO QILINMAYDI.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.services.discovery_1c import redact as redaction
from app.services.discovery_1c.runtime_bundle import MODE_METADATA_ONLY, REQUIRED_FILES
from app.services.discovery_agent import BUNDLE_SUBDIR
from app.services.discovery_agent import bridge_phase as bp
from app.services.discovery_agent import bridge_protocol as pr
from app.services.discovery_agent import collector_bridge as cb
from app.services.discovery_agent import detector as D
from app.services.discovery_agent import launcher as L
from app.services.discovery_agent import states as st

T_REQ = "2026-10-01T09:00:00+06:00"
T_START = "2026-10-01T09:00:05+06:00"
T_END = "2026-10-01T09:01:05+06:00"
T_DONE = "2026-10-01T09:01:06+06:00"

COLLECTOR_NAME = "BinOS1CCollector"
COLLECTOR_VERSION = "0.1.0-UNVERIFIED"

#: ⚠️ SINTETIK yo'l: haqiqiy bazaga ishora qilmaydi.
LOCATOR = r"C:\BinOS-sintetik\baza"
EXE = r"C:\Program Files\1cv8\8.3.24.1234\bin\1cv8.exe"


# ══════════════════════════════════════════════════════════════════════════════════════════
# FIKSTURALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
class FakeFiles:
    """Xotiradagi fayl tizimi (aniqlovchi fiksturasi bilan AYNI shaklda)."""

    def __init__(self, dirs=None, files=(), texts=None, unreadable=()):
        self.dirs = dict(dirs or {})
        self.files = set(files)
        self.texts = dict(texts or {})
        self.unreadable = set(unreadable)

    def listdir(self, path: str) -> D.ReadResult:
        if path in self.unreadable:
            return D.unreadable("papka o'qilmadi: PermissionError")
        if path not in self.dirs:
            return D.absent("papka yo'q")
        return D.ok(sorted(self.dirs[path]))

    def exists_file(self, path: str) -> D.ReadResult:
        if path in self.unreadable:
            return D.unreadable("fayl tekshirilmadi: PermissionError")
        return D.ok(path in self.files)

    def read_text(self, path: str) -> D.ReadResult:
        if path in self.unreadable:
            return D.unreadable("fayl o'qilmadi: PermissionError")
        if path not in self.texts:
            return D.absent("fayl yo'q")
        return D.ok(self.texts[path])


def nishon(kind: str = D.KIND_FILE, locator: str = LOCATOR,
           name: str = "Savdo bazasi") -> L.LaunchTarget:
    return L.LaunchTarget(kind=kind, locator=locator, name=name)


def sorov(identity=None, **kw) -> dict:
    ident = identity or pr.new_run(now=T_REQ)
    arg = dict(
        output_dir=r"C:\BinOS\runs\sintetik",
        collector_name=COLLECTOR_NAME,
        collector_version=COLLECTOR_VERSION,
        target_fingerprint=nishon().fingerprint,
        mode=MODE_METADATA_ONLY,
    )
    arg.update(kw)
    return pr.build_request(ident, **arg)


def javob(req: dict, **kw) -> dict:
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


def belgi(req: dict, **kw) -> dict:
    doc = {
        "done_version": pr.DONE_VERSION,
        "run_id": req["run_id"],
        "nonce": req["nonce"],
        "written_at": T_DONE,
    }
    doc.update(kw)
    return doc


def yoz(papka: pathlib.Path, nom: str, doc: dict) -> None:
    """⚠️ Fiksturada DETERMINISTIK serializator (`bundle.dumps`) ishlatiladi."""
    from app.services.discovery_1c.bundle import dumps

    (papka / nom).write_text(dumps(doc), encoding="utf-8", newline="\n")


class SoxtaSoat:
    """Kirishdan keladigan soat: har o'qishda belgilangan qadam qo'shiladi."""

    def __init__(self, qadam: float = 1.0) -> None:
        self.hozir = 0.0
        self.qadam = qadam
        self.oqishlar = 0

    def __call__(self) -> float:
        qiymat = self.hozir
        self.hozir += self.qadam
        self.oqishlar += 1
        return qiymat


class SoxtaUyqu:
    """Uxlamaydigan uyqu: faqat so'ralgan vaqtlarni QAYD etadi."""

    def __init__(self) -> None:
        self.chaqiruvlar: list[float] = []

    def __call__(self, soniya: float) -> None:
        self.chaqiruvlar.append(soniya)


class SoxtaOchuvchi:
    """1C ni ochmaydigan ochuvchi: buyruqni QAYD etadi va berilgan natijani qaytaradi.

    ⚠️ Jarayon TUG'ILMAYDI: shu bois test haqiqiy 1C ni ham, boshqa birorta `.exe` ni ham
       ishga tushirmaydi.
    """

    def __init__(self, natija: L.OpenerOutcome | None = None) -> None:
        self.natija = natija or L.OpenerOutcome(started=D.TRI_TRUE, handle="sintetik-1")
        self.buyruqlar: list[tuple[str, ...]] = []

    def __call__(self, command):
        self.buyruqlar.append(tuple(command))
        return self.natija


def install(path, version, *, source=D.SOURCE_REGISTRY, bitness="x64",
            clients=()) -> D.Install:
    return D.Install(path=path, version=version, bitness=bitness, source=source,
                     clients=clients)


def klient(path, *, tur=D.CLIENT_THICK, present=D.TRI_TRUE,
           source=D.SOURCE_FILESYSTEM) -> D.ClientBinary:
    return D.ClientBinary(client_type=tur, path=path, bitness="x64", source=source,
                          present=present)


def _rad(code: str, fn, *a, **kw):
    """Chaqiruv AYNAN shu kod bilan rad etilishi SHART."""
    with pytest.raises(L.LauncherError) as e:
        fn(*a, **kw)
    assert e.value.code == code, (
        f"kutilgan kod {code!r}, kelgani {e.value.code!r} — har rad etish sababi O'Z "
        f"kodini olishi SHART")
    return e.value


#: Satr oxiridagi izohlar va docstringlar OLIB TASHLANGAN manba (statik darvozalar uchun).
#: ⚠️ NEGA KERAK: `launcher.py` ning izohlari ATAYLAB «o'ldirish YO'Q» deb yozadi; darvoza
#:    IZOHNI emas, BAJARILADIGAN KODNI o'lchashi kerak.
_DOCSTRING_RE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')
AGENT_DIR = pathlib.Path(L.__file__).resolve().parent


def _kod_faqat(p: pathlib.Path) -> str:
    matn = _DOCSTRING_RE.sub('""', p.read_text(encoding="utf-8"))
    return "\n".join(satr.split("#", 1)[0] for satr in matn.splitlines())


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA A — KLIENT TURLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_klient_turlari_AYNAN_tortta_va_designer_ALOHIDA_fayl_EMAS():
    """⚠️ Konfigurator `1cv8.exe` ning REJIMI: unga `.exe` nomi O'YLAB CHIQARILMAYDI."""
    assert set(D.CLIENT_TYPES) == {"thick_client", "thin_client", "designer",
                                   "server_agent"}
    assert set(D.CLIENT_EXECUTABLES) == {D.CLIENT_THICK, D.CLIENT_THIN,
                                         D.CLIENT_SERVER_AGENT}
    assert D.CLIENT_DESIGNER not in D.CLIENT_EXECUTABLES, \
        "Konfigurator ALOHIDA bajariluvchi EMAS — u semiz klientning rejimi"
    assert D.DESIGNER_MODE_OF == D.CLIENT_THICK
    assert D.CLIENT_EXECUTABLES[D.CLIENT_THICK] == "1cv8.exe"
    assert D.CLIENT_EXECUTABLES[D.CLIENT_THIN] == "1cv8c.exe"
    assert D.CLIENT_EXECUTABLES[D.CLIENT_SERVER_AGENT] == "ragent.exe"
    assert D.DESIGNER_VERIFICATION == "UNVERIFIED_ON_REAL_1C", \
        "Konfigurator rejimi haqiqiy 1C da tekshirilmagan va buni BELGI aytadi"


def test_designer_fe_li_birorta_buyruqda_ISHLATILMAYDI():
    """⚠️⚠️ Konfigurator bazani O'ZGARTIRISH huquqiga ega rejim — razvedka uni ochmaydi."""
    kod = _kod_faqat(AGENT_DIR / "launcher.py")
    assert "DESIGNER_MODE_VERB" not in kod, \
        "ishga tushiruvchi Konfigurator rejimida hech narsa ochmasligi SHART"
    assert L.VERB_ENTERPRISE == "ENTERPRISE"


def test_klient_turlari_bin_papkasidan_UCHOVI_HAM_topiladi():
    """Semiz + Konfigurator (rejim) + yupqa + server agenti — AYNI `bin` papkasidan."""
    papka = r"C:\Program Files\1cv8\8.3.24.1234\bin"
    fayllar = FakeFiles(
        dirs={r"C:\Program Files\1cv8": ["8.3.24.1234"]},
        files=(EXE, papka + r"\1cv8c.exe", papka + r"\ragent.exe"),
    )
    cfg = D.DetectorConfig(
        registry_install_keys=(),
        filesystem_roots=(("program_files", r"C:\Program Files\1cv8", "x64"),),
    )
    scan = D.scan_environment(config=cfg, registry=_BoshReestr(), files=fayllar,
                              which=lambda _n: None, now=lambda: T_REQ,
                              os_version=lambda: None)
    (bitta,) = scan.installs
    turlar = {c.client_type: c for c in bitta.clients}
    assert set(turlar) == set(D.CLIENT_TYPES), f"klient turlari to'liq emas: {sorted(turlar)}"
    assert all(c.present == D.TRI_TRUE for c in turlar.values())
    assert turlar[D.CLIENT_DESIGNER].path == turlar[D.CLIENT_THICK].path, \
        "Konfigurator AYNI faylning rejimi"
    assert turlar[D.CLIENT_DESIGNER].mode_verb == D.DESIGNER_MODE_VERB
    assert turlar[D.CLIENT_THIN].path.endswith("1cv8c.exe")
    assert turlar[D.CLIENT_SERVER_AGENT].path.endswith("ragent.exe")


def test_reestrda_yol_bor_fayl_YOQ_bolsa_semiz_klient_DAVO_QILINMAYDI():
    """⚠️⚠️ Reestr yozuvi «fayl bor» DEGANI EMAS: 1C olib tashlangan bo'lishi mumkin."""
    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.24.1234"),
                              files=FakeFiles(), which=lambda _n: None,
                              now=lambda: T_REQ, os_version=lambda: None)
    (bitta,) = scan.installs
    assert bitta.clients == (), "fayl topilmasa klient yozuvi BO'LMASLIGI kerak"
    assert bitta.version == "8.3.24.1234", "o'rnatma FAKTI esa yo'qolmaydi"
    assert any("topilmadi" in n for n in scan.notes)


def test_klient_OQILMADI_yozuv_unknown_bolib_QOLADI():
    """⚠️⚠️ `UNKNOWN` hech qachon `NOT_FOUND` ga aylanmaydi: o'qilmagan fayl KO'RINADI."""
    papka = r"C:\Program Files\1cv8\8.3.24.1234\bin"
    fayllar = FakeFiles(
        dirs={r"C:\Program Files\1cv8": ["8.3.24.1234"]},
        files=(EXE,), unreadable=(papka + r"\1cv8c.exe",),
    )
    cfg = D.DetectorConfig(
        registry_install_keys=(),
        filesystem_roots=(("program_files", r"C:\Program Files\1cv8", "x64"),),
    )
    scan = D.scan_environment(config=cfg, registry=_BoshReestr(), files=fayllar,
                              which=lambda _n: None, now=lambda: T_REQ,
                              os_version=lambda: None)
    (bitta,) = scan.installs
    yupqa = bitta.client(D.CLIENT_THIN)
    assert yupqa is not None and yupqa.present == D.TRI_UNKNOWN
    assert any("TEKSHIRILMADI" in n for n in scan.notes)
    assert any(u.scope.startswith("clients:") for u in scan.unreadables), \
        "o'qilmagan manba `errors` ga ham tushishi kerak"


def test_PATH_dagi_klient_ornatmaga_BOGLANMAYDI():
    """⚠️ `PATH` dagi fayl qaysi o'rnatmaga tegishli ekani bilinmaydi — TAXMIN YO'Q."""
    yol = r"C:\1cv8c.exe"
    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.24.1234"),
                              files=FakeFiles(files=(EXE,)),
                              which=lambda n: yol if n == "1cv8c.exe" else None,
                              now=lambda: T_REQ, os_version=lambda: None)
    turlar = {c.client_type for c in scan.path_clients}
    assert turlar == {D.CLIENT_THIN}, f"PATH klientlari: {sorted(turlar)}"
    assert all(c.source == D.SOURCE_PATH for c in scan.path_clients)
    assert all(c.client_type != D.CLIENT_THIN for i in scan.installs for c in i.clients), \
        "PATH dagi yupqa klient o'rnatmaga BOG'LANMASLIGI kerak"


def test_PATH_oqilmasa_unknown_va_yoqlik_DAVO_QILINMAYDI():
    def portlat(_nom):
        raise OSError("PATH o'qilmadi")

    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.24.1234"),
                              files=FakeFiles(files=(EXE,)), which=portlat,
                              now=lambda: T_REQ, os_version=lambda: None)
    assert scan.path_clients == ()
    assert any("TEKSHIRILMADI" in n and "clients:path" in n for n in scan.notes)


def test_environment_hujjati_kalitlari_OZGARMADI():
    """⚠️⚠️ PHASE 4 DARSI: `installs[]` kalitlari IKKI joyda qulflangan (validator va
    test). Yangi kalit bugun qo'shilsa HAR BIR real paket rad etilardi — shu bois
    `clients` XOTIRADA qoladi va so'rov `launcher.RESULT_PACKAGE_SOROVI` da yozilgan."""
    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.24.1234"),
                              files=FakeFiles(files=(EXE,)), which=lambda _n: None,
                              now=lambda: T_REQ, os_version=lambda: None)
    doc = scan.to_document()
    assert list(doc["installs"][0]) == ["path", "version", "bitness", "source"]
    assert "clients" not in doc and "path_clients" not in doc
    assert scan.installs[0].clients, "xotirada esa klient yozuvi BOR"
    assert "result_package" in L.RESULT_PACKAGE_SOROVI and "clients" in L.RESULT_PACKAGE_SOROVI


def test_hujjatda_sanoq_va_boolean_YOQ_hamda_YOL_NIQOBLANGAN():
    """⚠️ Klient qo'shilgandan keyin ham hujjat qoidalari BUZILMADI."""
    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.24.1234"),
                              files=FakeFiles(files=(EXE,)), which=lambda _n: None,
                              now=lambda: T_REQ, os_version=lambda: None)
    doc = scan.to_document()

    def yur(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from yur(v)
        elif isinstance(node, list):
            for v in node:
                yield from yur(v)
        else:
            yield node

    assert not [v for v in yur(doc) if isinstance(v, (int, float, bool))]
    assert doc["installs"][0]["path"] == redaction.MASK
    assert "Program Files" not in str(doc), "izohlarga ham xom yo'l tushmasin"


# ── Tartiblash ────────────────────────────────────────────────────────────────────────────
def test_rank_installs_eng_yangisi_BIRINCHI():
    royxat = (install(r"C:\a\8.3.21\bin\1cv8.exe", "8.3.21"),
              install(r"C:\a\8.3.24.1234\bin\1cv8.exe", "8.3.24.1234"),
              install(r"C:\a\8.3.22\bin\1cv8.exe", "8.3.22"))
    tartib = D.rank_installs(royxat)
    assert [i.version for i in tartib] == ["8.3.24.1234", "8.3.22", "8.3.21"]


def test_rank_installs_NOMALUM_versiya_OXIRIDA():
    """⚠️ «Noma'lum» hech qachon «eng yangi» deb ko'rsatilmaydi."""
    royxat = (install(None, None, source=D.SOURCE_PATH),
              install(r"C:\a\8.3.21\bin\1cv8.exe", "8.3.21"))
    assert [i.version for i in D.rank_installs(royxat)] == ["8.3.21", None]


def test_rank_installs_TENG_versiyada_DETERMINISTIK():
    """⚠️⚠️ Kirish tartibi O'ZGARSA ham natija AYNI: aks holda bir kun boshqa `.exe`
    ochilardi."""
    a = install(r"C:\b\8.3.24\bin\1cv8.exe", "8.3.24", source=D.SOURCE_FILESYSTEM)
    b = install(r"C:\a\8.3.24\bin\1cv8.exe", "8.3.24", source=D.SOURCE_REGISTRY)
    assert D.rank_installs((a, b)) == D.rank_installs((b, a))
    assert D.rank_installs((a, b))[0] is b, "yo'l bo'yicha o'sish tartibi"


def test_ranked_installs_metodi_AYNI_javobni_beradi():
    scan = D.scan_environment(config=_REESTR_CFG, registry=_Reestr("8.3.21", "8.3.24"),
                              files=FakeFiles(), which=lambda _n: None,
                              now=lambda: T_REQ, os_version=lambda: None)
    assert scan.ranked_installs() == D.rank_installs(scan.installs)
    assert scan.ranked_installs()[0].version == "8.3.24"
    assert scan.newest_install().version == "8.3.24", \
        "versiyalar FARQ qilganda ikki so'rov AYNI yozuvni ko'rsatadi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# `.exe` TANLASH
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_choose_exe_eng_yangi_ISBOTLANGAN_faylni_tanlaydi():
    eski = install(r"C:\a\8.3.21\bin\1cv8.exe", "8.3.21",
                   clients=(klient(r"C:\a\8.3.21\bin\1cv8.exe"),))
    yangi = install(EXE, "8.3.24.1234", clients=(klient(EXE),))
    tanlov = L.choose_exe((eski, yangi))
    assert tanlov.path == EXE and tanlov.client_type == D.CLIENT_THICK
    assert tanlov.version == "8.3.24.1234"
    assert any("tanlandi" in n for n in tanlov.notes), "tanlov SABABI bilan qaytadi"


def test_choose_exe_TEKSHIRIB_BOLMAGAN_nomzodni_TANLAMAYDI_lekin_YOZADI():
    """⚠️⚠️ Isbotlanmagan yo'lni ochish «1C yo'q» degan YOLG'ON xulosaga olib kelardi."""
    noaniq = install(EXE, "8.3.24.1234", clients=(klient(EXE, present=D.TRI_UNKNOWN),))
    eski = install(r"C:\a\8.3.21\bin\1cv8.exe", "8.3.21",
                   clients=(klient(r"C:\a\8.3.21\bin\1cv8.exe"),))
    tanlov = L.choose_exe((noaniq, eski))
    assert tanlov.version == "8.3.21", "tekshirib bo'lmagan yangi versiya TANLANMAYDI"
    assert any("isbotlanmagan" in n for n in tanlov.notes)


def test_choose_exe_hech_narsa_topilmasa_EXE_MISSING():
    _rad(cb.CODE_EXE_MISSING, L.choose_exe, ())
    noaniq = install(EXE, "8.3.24", clients=(klient(EXE, present=D.TRI_UNKNOWN),))
    _rad(cb.CODE_EXE_MISSING, L.choose_exe, (noaniq,))


def test_choose_exe_PATH_klienti_ENG_OXIRGI_chora():
    yoq = install(None, "8.3.24")
    tanlov = L.choose_exe((yoq,), path_clients=(klient(r"C:\1cv8.exe",
                                                       source=D.SOURCE_PATH),))
    assert tanlov.source == D.SOURCE_PATH and tanlov.version is None
    assert any("PATH" in n for n in tanlov.notes)


def test_choose_exe_yupqa_klient_AVTOMATIK_tanlanmaydi():
    """⚠️ Yupqa klient qaysi baza turini ocha olishi haqiqiy 1C da tekshirilmagan."""
    semiz_va_yupqa = install(EXE, "8.3.24",
                             clients=(klient(EXE),
                                      klient(r"C:\bin\1cv8c.exe", tur=D.CLIENT_THIN)))
    assert L.choose_exe((semiz_va_yupqa,)).client_type == D.CLIENT_THICK
    assert L.choose_exe((semiz_va_yupqa,),
                        client_type=D.CLIENT_THIN).client_type == D.CLIENT_THIN


def test_choose_exe_notanish_klient_turi_RAD():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.choose_exe, (), client_type="super_client")


def test_choose_exe_teng_versiya_FAKTI_izohga_tushadi():
    a = install(r"C:\a\8.3.24\bin\1cv8.exe", "8.3.24",
                clients=(klient(r"C:\a\8.3.24\bin\1cv8.exe"),))
    b = install(r"C:\b\8.3.24\bin\1cv8.exe", "8.3.24",
                clients=(klient(r"C:\b\8.3.24\bin\1cv8.exe"),))
    assert any("bir xil versiyali" in n for n in L.choose_exe((a, b)).notes)


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA B — BUYRUQ SATRI va IKKI YO'L
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_fayl_bazasi_uchun_buyruq_FAQAT_F_kaliti_bilan():
    assert L.build_open_command(exe_path=EXE, target=nishon()) == (
        EXE, "ENTERPRISE", f"/F{LOCATOR}")


def test_server_bazasi_uchun_buyruq_FAQAT_S_kaliti_bilan():
    hedef = nishon(kind=D.KIND_SERVER, locator="srv1/trade", name="Trade")
    assert L.build_open_command(exe_path=EXE, target=hedef) == (
        EXE, "ENTERPRISE", "/Ssrv1/trade")


def test_buyruqda_KREDENSIAL_kaliti_YOQ_va_darvoza_MAVJUDI_ishlatiladi():
    """⚠️⚠️ Darvoza IKKINCHI NUSXADA yozilmaydi: `collector_bridge` dagi AYNI tekshiruv."""
    buyruq = L.build_open_command(exe_path=EXE, target=nishon())
    for token in buyruq:
        for taqiq in cb.FORBIDDEN_SWITCHES:
            assert not token.upper().startswith(taqiq.upper())
    with pytest.raises(cb.BridgeError):
        pr.assert_launch_command(buyruq + ("/Psintetik00",))
    assert (L.SWITCH_FILE_TARGET, L.SWITCH_SERVER_TARGET) == pr.ALLOWED_TARGET_SWITCHES


def test_buyruqda_Execute_va_C_kaliti_YOQ():
    """⚠️ Bu yo'l 1C ni OPERATOR uchun ochadi; paketli bajarish ko'prikning ishi."""
    buyruq = L.build_open_command(exe_path=EXE, target=nishon())
    assert not [t for t in buyruq if t.upper().startswith("/C")]
    assert cb.SWITCH_EXECUTE not in buyruq


def test_xavfsiz_bolmagan_argument_buyruqni_QURMAYDI():
    """⚠️ Qo'shtirnoq Windows argv chegarasini buzadi — buyruq umuman qurilmaydi."""
    with pytest.raises(cb.BridgeError):
        L.build_open_command(exe_path=EXE, target=nishon(locator='C:\\a"b'))
    with pytest.raises(cb.BridgeError):
        L.build_open_command(exe_path="", target=nishon())


def test_nishon_turi_notanish_bolsa_RAD():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.LaunchTarget, "veb", LOCATOR, "A")
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.LaunchTarget, D.KIND_FILE, "  ", "A")


def test_nishon_ozligi_XESH_va_xom_locator_unda_YOQ():
    """⚠️⚠️ `locator` sir bo'lishi mumkin — protokolga FAQAT xesh boradi."""
    hedef = nishon()
    assert pr.FINGERPRINT_RE.fullmatch(hedef.fingerprint)
    assert LOCATOR not in hedef.fingerprint
    assert hedef.fingerprint == pr.target_fingerprint(D.KIND_FILE, hedef.name, LOCATOR)


def test_nomsiz_bazadan_nishon_QURILMAYDI():
    """⚠️ «Nom = lokator» deb JIMGINA to'ldirish YO'Q: xesh shartnomasi buzilardi."""
    nomsiz = D.Infobase(D.KIND_FILE, LOCATOR, None, D.SOURCE_IBASES_USER, D.TRI_UNKNOWN)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.LaunchTarget.from_infobase, nomsiz)
    nomli = D.Infobase(D.KIND_FILE, LOCATOR, "Savdo", D.SOURCE_IBASES_USER, D.TRI_TRUE)
    assert L.LaunchTarget.from_infobase(nomli).name == "Savdo"


# ── Yo'l 1: `open_infobase` ───────────────────────────────────────────────────────────────
def test_tasdiqsiz_1C_OCHILMAYDI_va_operator_yoli_KORSATILADI():
    """⚠️⚠️ FAIL-CLOSED: tasdiq yo'qligi ruxsat BERMAYDI."""
    natija = L.open_infobase(exe_path=EXE, target=nishon(), opener=SoxtaOchuvchi())
    assert natija.launched == D.TRI_FALSE and natija.mode == L.LAUNCH_MODE_OPERATOR
    assert natija.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
    assert natija.state_hint is None, "bu YIQILISH emas: operator qo'lda ochadi"
    assert natija.operator and natija.next_action
    assert natija.command == (EXE, "ENTERPRISE", f"/F{LOCATOR}"), \
        "ochilmasa ham buyruq KO'RSATILADI"


def test_ochuvchi_berilmasa_1C_OCHILMAYDI_va_SABABI_aytiladi():
    """⚠️⚠️ Shipped paketda standart ochuvchi YO'Q: yagona `subprocess` joyi vaqt
    tugaganda jarayonni tugatadi, operatorning oynasini tugatish esa TAQIQLANGAN."""
    natija = L.open_infobase(exe_path=EXE, target=nishon(), operator_confirmed=True)
    assert natija.launched == D.TRI_FALSE
    assert natija.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
    assert any("TUGATADI" in n or "TAQIQLANGAN" in n for n in natija.notes)


def test_tasdiq_va_ochuvchi_bolsa_1C_ochiladi():
    ochuvchi = SoxtaOchuvchi(L.OpenerOutcome(started=D.TRI_TRUE, exit_code=0,
                                             handle="sintetik-7"))
    natija = L.open_infobase(exe_path=EXE, target=nishon(), operator_confirmed=True,
                             opener=ochuvchi, output_dir=r"C:\BinOS\runs\x",
                             collector_file=r"C:\yashirin\papka\BinOSDiscovery.epf")
    assert natija.launched == D.TRI_TRUE and natija.mode == L.LAUNCH_MODE_AGENT
    assert natija.code is None and natija.state_hint is None
    assert natija.exit_code == 0 and natija.exit_code_text == "0"
    assert ochuvchi.buyruqlar == [(EXE, "ENTERPRISE", f"/F{LOCATOR}")]
    assert natija.output_dir == r"C:\BinOS\runs\x"
    assert any("YOPMAYDI" in n for n in natija.notes)


def test_ochish_muvaffaqiyatsiz_bolsa_ANIQ_yiqilish():
    ochuvchi = SoxtaOchuvchi(L.OpenerOutcome(started=D.TRI_FALSE,
                                             detail="jarayon boshlanmadi"))
    natija = L.open_infobase(exe_path=EXE, target=nishon(), operator_confirmed=True,
                             opener=ochuvchi)
    assert natija.code == cb.CODE_LAUNCH_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.operator and natija.next_action


def test_korsatmada_XOM_YOL_va_LOCATOR_YOQ_lekin_FAYL_NOMI_bor():
    """⚠️⚠️ Ko'rsatma `notes`/hisobotga tushishi mumkin: unda yo'l BO'LMASLIGI kerak."""
    natija = L.open_infobase(exe_path=EXE, target=nishon(), operator_confirmed=True,
                             opener=SoxtaOchuvchi(),
                             collector_file=r"C:\yashirin\papka\BinOSDiscovery.epf")
    matn = "\n".join(natija.instructions)
    assert "BinOSDiscovery.epf" in matn, "operator QAYSI faylni ochishini bilishi kerak"
    assert "yashirin" not in matn and LOCATOR not in matn
    assert "Savdo bazasi" in matn, "baza NOMI esa ko'rsatiladi"
    assert redaction.scan({"note": matn}) == [], "ko'rsatmada shubhali qiymat bo'lmasin"


def test_korsatma_HAR_HOLATDA_bosh_bolmaydi():
    """⚠️ «Spinner-only» holat YO'Q: har natijada operator nima qilishini biladi."""
    for natija in (
        L.open_infobase(exe_path=EXE, target=nishon()),
        L.open_infobase(exe_path=EXE, target=nishon(), operator_confirmed=True,
                        opener=SoxtaOchuvchi()),
        L.security_refusal(L.REFUSAL_SAFE_MODE, target=nishon()),
    ):
        assert natija.instructions and all(s.strip() for s in natija.instructions)
    assert "parol" in "\n".join(
        L.operator_instructions(target=nishon(), mode=L.LAUNCH_MODE_OPERATOR)).lower()


def test_natija_invariantlari_fail_closed():
    """⚠️ Yiqilish holati bo'lsa KOD ham, uchlik ham SHART — jimgina yiqilish YO'Q."""
    with pytest.raises(L.LauncherError):
        L.LaunchOutcome(mode=L.LAUNCH_MODE_OPERATOR, launched=D.TRI_FALSE,
                        command=("a",), instructions=("b",),
                        state_hint=st.FAILED_TIMEOUT)
    with pytest.raises(L.LauncherError):
        L.LaunchOutcome(mode=L.LAUNCH_MODE_OPERATOR, launched=D.TRI_TRUE,
                        command=("a",), instructions=("b",))
    with pytest.raises(L.LauncherError):
        L.LaunchOutcome(mode=L.LAUNCH_MODE_AGENT, launched=D.TRI_FALSE,
                        command=("a",), instructions=())
    with pytest.raises(L.LauncherError):
        L.LaunchOutcome(mode="o'zim", launched=D.TRI_FALSE, command=("a",),
                        instructions=("b",))


# ── Yo'l 2: `auto_run_processor` ──────────────────────────────────────────────────────────
def test_avtomatik_bajarish_DEKLARATSIYA():
    """⚠️⚠️ `.epf` IKKILIK fayli QURILGAN deb AYTILMAYDI va avtomatik bajarish
    «ishlaydi» deb DA'VO QILINMAYDI."""
    d = L.auto_run_processor()
    assert d.status == "UNVERIFIED_ON_REAL_1C"
    assert d.implemented == D.TRI_FALSE
    assert d.command is None, "hech qanday buyruq QURILMAYDI"
    assert d.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
    assert d.operator and d.next_action and d.reason
    assert "COM" in d.reason and "o'ylab chiqarilgan" in d.reason
    assert L.AUTO_RUN_STATUS == bp.AUTOMATIC_LAUNCH_VERIFICATION, \
        "belgi `bridge_phase` dan olinadi, ikkinchi nusxa yozilmaydi"


def test_epf_SOURCE_READY_nomi_OZGARMAYDI():
    """⚠️ Holat nomi AYNAN `EPF_SOURCE_READY` — «qurildi» emas."""
    assert bp.EPF_SOURCE_READY == "EPF_SOURCE_READY"


# ── Xavfsizlik raddi ─────────────────────────────────────────────────────────────────────
def test_xavfsizlik_raddi_NORMAL_holat_va_UCHTA_sabab():
    assert set(L.SECURITY_REFUSALS) == {"safe_mode", "insufficient_rights",
                                        "security_profile"}
    for sabab in L.SECURITY_REFUSALS:
        natija = L.security_refusal(sabab, target=nishon())
        assert natija.code == bp.CODE_COLLECTOR_EXECUTION_NOT_ALLOWED
        assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE, \
            "1C BOR, javob YO'Q — «topilmadi» EMAS"
        assert natija.operator and natija.next_action
        assert any(sabab in n for n in natija.notes)


def test_xavfsizlik_ZAIFLASHTIRISH_tavsiyasi_YOQ():
    """⚠️⚠️ Keyingi qadam HECH QACHON xavfsiz rejimni o'chirishga, profilni tahrirlashga
    yoki rolga huquq qo'shishga CHAQIRMAYDI."""
    taqiq = ("xavfsiz rejimni o'chir", "o'chirib qo'y", "profilni o'zgartir",
             "profilni tahrirla", "rolga huquq qo'sh", "to'liq huquq ber",
             "administrator huquqi bilan ishga tushir")
    for matn, keyingi in L.SECURITY_REFUSAL_TEXT.values():
        past = (matn + " " + keyingi).lower()
        assert not [t for t in taqiq if t in past], f"zaiflashtirish tavsiyasi: {past}"
        assert "administrator" in past, "qaror ODAMGA havola qilinishi kerak"


def test_notanish_radd_sababi_RAD():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.security_refusal, "nimadir")


# ══════════════════════════════════════════════════════════════════════════════════════════
# VAZIFA C — BEKOR QILISH va TIMEOUT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_cancel_token_IDEMPOTENT_va_BIRINCHI_sabab_qoladi():
    cancel = L.CancelToken()
    assert not cancel.cancelled and cancel.reason is None
    cancel.cancel("birinchi")
    cancel.cancel("ikkinchi")
    assert cancel.cancelled and cancel.reason == "birinchi"


def test_cancel_SABABSIZ_bolmaydi():
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.CancelToken().cancel, "   ")


def test_bekor_qilinganda_kutish_TOXTAYDI_va_DIAGNOSTIKA_saqlanadi(tmp_path):
    cancel = L.CancelToken()
    cancel.cancel()
    uyqu = SoxtaUyqu()
    natija = L.wait_for_collector(run_dir=tmp_path, request=sorov(), cancel=cancel,
                                  clock=SoxtaSoat(), sleeper=uyqu, members=lambda: ())
    assert natija.code == bp.CODE_OPERATOR_CANCELLED
    assert natija.state_hint == st.ABORTED_BY_OPERATOR
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.operator and natija.next_action
    assert any("bekor qilish sababi" in d for d in natija.diagnostics)
    assert uyqu.chaqiruvlar == [], "bekor qilingan yurish UXLAMAYDI"
    assert natija.ticks == "0" and isinstance(natija.elapsed_seconds, str)


def test_bekor_qilinganda_muvaffaqiyat_QAYTMAYDI(tmp_path):
    """⚠️⚠️ Papkada TAYYOR javob turgan bo'lsa ham bekor qilingan yurish MUVAFFAQIYAT
    bilan tugamaydi: tekshiruv tartibida bekor qilish BIRINCHI."""
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    cancel = L.CancelToken()
    cancel.cancel()
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, cancel=cancel,
                                  clock=SoxtaSoat(), sleeper=SoxtaUyqu(),
                                  members=lambda: REQUIRED_FILES)
    assert not natija.ok and natija.state_hint == st.ABORTED_BY_OPERATOR


def test_bekor_qilish_halqa_ORTASIDA_ham_ishlaydi(tmp_path):
    """Kooperativ: halqa aylanayotganda bosilsa, keyingi aylanishda to'xtaydi."""
    cancel = L.CancelToken()
    uyqu_sanogi = {"n": 0}

    def uxla(_soniya):
        uyqu_sanogi["n"] += 1
        if uyqu_sanogi["n"] == 2:
            cancel.cancel("operator ikkinchi aylanishda bosdi")

    natija = L.wait_for_collector(run_dir=tmp_path, request=sorov(), cancel=cancel,
                                  timeout_seconds=100.0, poll_seconds=1.0,
                                  clock=SoxtaSoat(), sleeper=uxla, members=lambda: ())
    assert natija.state_hint == st.ABORTED_BY_OPERATOR
    assert natija.ticks == "2", "to'xtaguncha ikki o'lchov bo'ldi"
    assert "ikkinchi aylanishda" in " ".join(natija.diagnostics)


def test_vaqt_tugasa_HALOL_yiqilish(tmp_path):
    uyqu = SoxtaUyqu()
    natija = L.wait_for_collector(run_dir=tmp_path, request=sorov(),
                                  timeout_seconds=3.0, poll_seconds=2.0,
                                  clock=SoxtaSoat(qadam=1.0), sleeper=uyqu,
                                  members=lambda: ())
    assert natija.code == cb.CODE_WAIT_TIMEOUT
    assert natija.state_hint == st.FAILED_TIMEOUT
    assert natija.phase == bp.WAITING_FOR_COLLECTOR
    assert natija.operator and natija.next_action
    assert any("vaqt tugadi" in d for d in natija.diagnostics)
    assert any(pr.RESPONSE_FILE in d for d in natija.diagnostics), \
        "nima yetishmaganini DIAGNOSTIKA aytadi"
    assert max(uyqu.chaqiruvlar) <= 3.0, "uxlash chegaradan OSHMAYDI"


def test_cheksiz_kutish_YOQ(tmp_path):
    for yomon in (0, -1, "ko'p"):
        _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.wait_for_collector, run_dir=tmp_path,
             request=sorov(), timeout_seconds=yomon)
    _rad(bp.CODE_BRIDGE_SHAPE_INVALID, L.wait_for_collector, run_dir=tmp_path,
         request=sorov(), poll_seconds=0)


def test_javob_kelsa_QABUL_qilinadi(tmp_path):
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.ok and natija.phase == bp.COLLECTOR_COMPLETE
    assert natija.code is None and natija.state_hint is None
    assert natija.acceptance is not None and natija.acceptance.status == pr.STATUS_OK


def test_javob_RAD_etilsa_KOPRIK_kodi_bilan_qaytadi(tmp_path):
    """⚠️ Ikkinchi tekshiruv YOZILMAYDI: kod `bridge_protocol` dan keladi."""
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req, nonce="f" * 32))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.code == bp.CODE_NONCE_MISMATCH
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE


def test_paket_TOLIQ_EMAS_bolsa_PARTIAL_PACKAGE(tmp_path):
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(),
                                  members=lambda: REQUIRED_FILES[:-1])
    assert natija.code == bp.CODE_PARTIAL_PACKAGE


def test_yiguvchi_BEKOR_qildi_deb_aytsa_holat_ABORTED(tmp_path):
    """⚠️ Yig'uvchining «bekor qilindi» javobi ham JAVOB va u AYNI holatga tushadi."""
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req, status=pr.STATUS_CANCELLED))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.code == bp.CODE_OPERATOR_CANCELLED
    assert natija.state_hint == st.ABORTED_BY_OPERATOR


def test_yiguvchi_YIQILDI_deb_aytsa_javob_BOR_natija_YOQ(tmp_path):
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req, status=pr.STATUS_FAILED))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: ())
    assert not natija.ok and natija.phase == bp.COLLECTOR_FAILED
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE


def test_paket_papkasi_YOQ_bosh_royxat_OQILMADI_esa_ISTISNO(tmp_path, monkeypatch):
    """⚠️⚠️ «Yo'q» va «o'qib bo'lmadi» AJRATILGAN: birinchisi NORMAL (yig'uvchi hali
    yozmagan), ikkinchisi esa ISTISNO — «ko'rolmadim» ni «bo'sh» deb o'qish yolg'on
    xulosa bo'lardi."""
    assert L.bundle_members(tmp_path) == ()
    paket = tmp_path / BUNDLE_SUBDIR
    paket.mkdir()
    (paket / "manifest.json").write_text("{}", encoding="utf-8")
    assert L.bundle_members(tmp_path) == ("manifest.json",)

    def portlat(_ozi):
        raise PermissionError("huquq yetmadi")

    # ⚠️ `monkeypatch` ishlatiladi: test tugagach almashtirish O'ZI qaytariladi.
    monkeypatch.setattr(pathlib.Path, "iterdir", portlat)
    xato = _rad(cb.CODE_BUNDLE_DIR_MISSING, L.bundle_members, tmp_path)
    assert "huquq yetmadi" not in str(xato), "istisno MATNI ko'chirilmaydi (yo'l bo'lishi mumkin)"
    assert "PermissionError" in str(xato), "faqat TURI yoziladi"


def test_WaitOutcome_sanoqlari_MATN():
    """⚠️ Hujjatga tushadigan sanoq MATN bo'lishi kerak (JSON'da son YO'Q)."""
    natija = L._cancelled(3, 7.9, ())
    assert natija.ticks == "3" and natija.elapsed_seconds == "7"
    assert isinstance(natija.ticks, str) and isinstance(natija.elapsed_seconds, str)


def test_WaitOutcome_invariantlari():
    with pytest.raises(L.LauncherError):
        L.WaitOutcome(phase="QAYERDADIR", ticks="0", elapsed_seconds="0")
    with pytest.raises(L.LauncherError):
        L.WaitOutcome(phase=bp.COLLECTOR_FAILED, ticks="0", elapsed_seconds="0",
                      state_hint=st.FAILED_TIMEOUT)


def test_bekor_qilish_HOLATI_mavjud_lugatdan_va_YANGI_holat_YOQ():
    """⚠️ Bu modul yangi holat ham, yangi faza ham QO'SHMAYDI."""
    assert len(st.FAILURE_STATES) == 11 and len(st.NORMAL_STATES) == 12
    assert len(bp.BRIDGE_PHASES) == 12
    assert st.ABORTED_BY_OPERATOR in st.FAILURE_STATES


# ══════════════════════════════════════════════════════════════════════════════════════════
# STATIK DARVOZALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_manbada_jarayon_oldirish_naqshi_YOQ():
    """⚠️⚠️ ENG MUHIM DARVOZA: bekor qilish KOOPERATIV, jarayon O'LDIRILMAYDI.

    Operatorning 1C sessiyasini majburan yopish uning SAQLANMAGAN ishini yo'qotardi —
    ya'ni FAQAT O'QIYDIGAN razvedka do'konga zarar yetkazardi.
    """
    taqiq = (r"taskkill", r"\.kill\s*\(", r"\.terminate\s*\(", r"TerminateProcess",
             r"os\.kill", r"SIGKILL", r"SIGTERM", r"\.send_signal\s*\(",
             r"^\s*import\s+signal", r"^\s*import\s+subprocess", r"Popen",
             r"os\.system", r"os\.popen", r"startfile")
    kod = _kod_faqat(AGENT_DIR / "launcher.py")
    topildi = [t for t in taqiq if re.search(t, kod, re.M)]
    assert not topildi, f"jarayonni o'ldirish/ochish naqshi topildi: {topildi}"


def test_manbada_JARAYON_ROYXATINI_oqish_yoli_YOQ():
    """⚠️⚠️ 1C allaqachon ishlayotgan bo'lsa — TASODIFIY jarayonga ULANMAYDI."""
    taqiq = (r"tasklist", r"wmic", r"psutil", r"EnumProcesses", r"OpenProcess",
             r"CreateToolhelp", r"win32process", r"\.pid\b")
    kod = _kod_faqat(AGENT_DIR / "launcher.py")
    topildi = [t for t in taqiq if re.search(t, kod)]
    assert not topildi, f"jarayon ro'yxatini o'qish izi: {topildi}"
    assert L.ATTACH_TO_RUNNING == D.TRI_FALSE


def test_manbada_OCHIRISH_va_COM_naqshi_YOQ():
    """⚠️ O'chirish YO'Q (na wildcard, na yolg'iz fayl), COM avtomatizatsiyasi ham YO'Q."""
    taqiq = (r"rmtree", r"os\.remove", r"os\.unlink", r"\.unlink\s*\(", r"\.rmdir\s*\(",
             r"glob\s*\(", r"rglob", r"\*\.json", r"win32com", r"pythoncom",
             r"Dispatch\s*\(", r"CreateObject", r"COMConnector",
             r"^\s*import\s+socket", r"urlopen", r"\.mkdir\s*\(", r"write_text",
             r"write_bytes")
    kod = _kod_faqat(AGENT_DIR / "launcher.py")
    topildi = [t for t in taqiq if re.search(t, kod, re.M)]
    assert not topildi, f"taqiqlangan naqsh topildi: {topildi}"


def test_manbada_KREDENSIAL_maydoni_va_parametri_YOQ():
    """⚠️ Parol MAYDONI ham, PARAMETRI ham bo'lmaydi: «bo'sh qoldiramiz» yo'li yaramaydi."""
    taqiq = re.compile(r"pwd|passw|parol|secret|credential|token|connect_string", re.I)
    daraxt = ast.parse((AGENT_DIR / "launcher.py").read_text("utf-8"))
    for tugun in ast.walk(daraxt):
        if isinstance(tugun, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nomlar = [a.arg for a in tugun.args.args + tugun.args.kwonlyargs]
            assert not [a for a in nomlar if taqiq.search(a)], \
                f"{tugun.name}: kredensial parametrini oladi"
        if isinstance(tugun, ast.Constant) and isinstance(tugun.value, str):
            assert tugun.value[:2].upper() not in ("/P", "/N") or \
                tugun.value in cb.FORBIDDEN_SWITCHES, \
                f"kredensial kaliti qiymat bilan yozilgan: {tugun.value!r}"
    for sinf in (L.LaunchTarget, L.LaunchOutcome, L.ExeChoice, L.WaitOutcome,
                 L.OpenerOutcome, L.AutomaticRunDeclaration):
        assert not [m for m in sinf.__dataclass_fields__ if taqiq.search(m)], \
            f"{sinf.__name__}: kredensial maydoni bor"


def test_matnlarda_SIR_YOQ():
    """⚠️ Bu matnlar `notes` ga tushishi mumkin — sir bo'lsa chiqish BLOKLANARDI."""
    matnlar = {"radd": [a + " " + b for a, b in L.SECURITY_REFUSAL_TEXT.values()],
               "sorov": [L.RESULT_PACKAGE_SOROVI, L.STATES_TEST_SOROVI],
               "sabab": [L.auto_run_processor().reason]}
    assert redaction.scan(matnlar) == [], "matnda shubhali qiymat topildi"


def test_subprocess_YAGONA_joyda_qoldi():
    """⚠️⚠️ Jarayon ishga tushirish YAGONA modulda (`collector_bridge`) qoladi — ishga
    tushiruvchi ikkinchi joy OCHMAYDI."""
    manbalar = sorted(p for p in AGENT_DIR.glob("*.py"))
    ishlatganlar = [p.name for p in manbalar
                    if re.search(r"^\s*import subprocess", _kod_faqat(p), re.M)]
    assert ishlatganlar == ["collector_bridge.py"], \
        f"`subprocess` tarqalib ketdi: {ishlatganlar}"


def test_boshqa_agentga_SOROVLAR_kodda_YOZILGAN():
    """⚠️⚠️ «Keyinroq eslaymiz» yo'li YOPIQ: ikkala so'rov KODDA turadi va ularda nima
    qilish kerakligi ANIQ yozilgan."""
    assert "result_package.py" in L.RESULT_PACKAGE_SOROVI
    assert "test_agent_states.py" in L.STATES_TEST_SOROVI
    assert "ABORTED_BY_OPERATOR" in L.STATES_TEST_SOROVI
    assert "launcher.py" in L.STATES_TEST_SOROVI


# ══════════════════════════════════════════════════════════════════════════════════════════
# YORDAMCHI FIKSTURALAR (reestr)
# ══════════════════════════════════════════════════════════════════════════════════════════
INSTALL_KEY = r"SOFTWARE\1C\1Cv8"
_REESTR_CFG = D.DetectorConfig(registry_install_keys=((D.HKLM, INSTALL_KEY, "x64"),))


class _BoshReestr:
    """Hamma so'roqqa «kalit yo'q» deb javob beradigan reestr."""

    def subkeys(self, hive, key):
        return D.absent("reestr kaliti yo'q")

    def values(self, hive, key):
        return D.absent("reestr kaliti yo'q")

    def key_exists(self, hive, key):
        return D.absent("reestr kaliti yo'q")


class _Reestr(_BoshReestr):
    """Berilgan versiyalarni va ularning yo'lini qaytaradigan sintetik reestr."""

    def __init__(self, *versiyalar: str) -> None:
        self.versiyalar = versiyalar

    def subkeys(self, hive, key):
        if key == INSTALL_KEY:
            return D.ok(sorted(self.versiyalar))
        return D.absent("reestr kaliti yo'q")

    def values(self, hive, key):
        for v in self.versiyalar:
            if key == f"{INSTALL_KEY}\\{v}":
                return D.ok({"Path": rf"C:\Program Files\1cv8\{v}\bin\1cv8.exe"})
        return D.absent("reestr kaliti yo'q")


# ══════════════════════════════════════════════════════════════════════════════════════════
# BUZUQ HUJJAT — HALQADAN ISTISNO BO'LIB CHIQMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_buzuq_javob_BELGI_bor_bolsa_RAD_etiladi_ISTISNO_EMAS(tmp_path):
    """⚠️⚠️ TUZATILGAN NUQSON (ulanishdan keyin ko'rindi): `read_response` yaroqsiz JSON
    uchun `BridgeProtocolError` tashlaydi va u halqada USHLANMASDI — ya'ni bir bosishli
    oqim yurish O'RTASIDA istisno bilan uzilardi va operator na faza, na keyingi qadam
    olardi.

    ⚠️ Belgi BOR: yig'uvchi ishini tugatganini AYTDI, demak o'qilmaydigan hujjat HAQIQIY
       rad etish (`BRIDGE_SHAPE_INVALID`), «hali yozilyapti» EMAS.
    """
    req = sorov()
    (tmp_path / pr.RESPONSE_FILE).write_text("{bu yaroqli JSON emas", encoding="utf-8")
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.code == bp.CODE_BRIDGE_SHAPE_INVALID
    assert natija.state_hint == st.FAILED_COLLECTOR_UNAVAILABLE
    assert natija.phase == bp.COLLECTOR_FAILED
    assert natija.acceptance is None
    assert natija.operator and natija.next_action, "uchlik TO'LIQ"
    assert any("O'QILMADI" in d for d in natija.diagnostics)


def test_buzuq_belgi_hujjati_ham_RAD_etiladi(tmp_path):
    """⚠️ Belgining O'ZI o'qilmasa ham sabab AYNI: fayl bor, lekin hujjat emas."""
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req))
    (tmp_path / pr.DONE_FILE).write_text("[", encoding="utf-8")
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.code == bp.CODE_BRIDGE_SHAPE_INVALID
    assert natija.acceptance is None


def test_YARIM_YOZILGAN_javob_BELGI_yoq_bolsa_KUTISH_DAVOM_etadi(tmp_path):
    """⚠️⚠️ «YARIM YOZILGAN» va «BUZUQ» AJRATILADI va ajrim TUGALLANISH BELGISIGA tayanadi.

    Belgi shartnoma bo'yicha ENG OXIRIDA yoziladi. U hali YO'Q bo'lsa `response.json`
    yozilayotgan bo'lishi MUMKIN, demak parse xatosi «hali tayyor emas» degani va kutish
    DAVOM etadi — aks holda agent yig'uvchi yozib bo'lishidan OLDIN uni rad etardi
    (aynan Phase 4 da yarim paketni to'liq deb o'qigan nuqsonning teskarisi).
    """
    req = sorov()
    (tmp_path / pr.RESPONSE_FILE).write_text('{"response_version": "bi', encoding="utf-8")
    uyqu = SoxtaUyqu()
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, timeout_seconds=3.0,
                                  poll_seconds=1.0, clock=SoxtaSoat(qadam=1.0),
                                  sleeper=uyqu, members=lambda: ())
    assert natija.code == cb.CODE_WAIT_TIMEOUT, "rad etish EMAS — kutish davom etdi"
    assert natija.state_hint == st.FAILED_TIMEOUT
    assert int(natija.ticks) >= 1 and uyqu.chaqiruvlar, "halqa ROSTDAN aylandi"
    assert any(pr.DONE_FILE in d for d in natija.diagnostics)


# ══════════════════════════════════════════════════════════════════════════════════════════
# `PARTIAL` — QABUL QILINADI, LEKIN JIMGINA MUVAFFAQIYAT EMAS
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_PARTIAL_javob_QABUL_qilinadi_va_DIAGNOSTIKADA_ATALADI(tmp_path):
    """⚠️⚠️ `PARTIAL` yig'uvchining O'Z lug'atidagi qiymat (Phase 4 `overall`).

    Faza `COLLECTOR_COMPLETE` (javob bor, paket to'liq) va ko'prik kodi YO'Q — hukmni
    QUVUR beradi (validator kodi `2`). Lekin u JIMGINA «qabul qilindi» bo'lib qolmaydi:
    yig'uvchining holati DIAGNOSTIKADA ATALADI, aks holda operator yarim natijani
    to'liq deb o'qirdi.
    """
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req, status=pr.STATUS_PARTIAL))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.ok and natija.phase == bp.COLLECTOR_COMPLETE
    assert natija.code is None and natija.state_hint is None
    assert natija.acceptance.status == pr.STATUS_PARTIAL
    assert any(pr.STATUS_PARTIAL in d for d in natija.diagnostics), \
        "yarim natija DIAGNOSTIKADA atalishi SHART"


def test_SUCCESS_javobi_ham_DIAGNOSTIKADA_ATALADI(tmp_path):
    """⚠️ «Qabul qilindi» yetarli emas: NIMA qabul qilingani ham yozilib qoladi."""
    req = sorov()
    yoz(tmp_path, pr.RESPONSE_FILE, javob(req, status=pr.STATUS_SUCCESS))
    yoz(tmp_path, pr.DONE_FILE, belgi(req))
    natija = L.wait_for_collector(run_dir=tmp_path, request=req, clock=SoxtaSoat(),
                                  sleeper=SoxtaUyqu(), members=lambda: REQUIRED_FILES)
    assert natija.ok and natija.acceptance.status == pr.STATUS_SUCCESS
    assert any(pr.STATUS_SUCCESS in d for d in natija.diagnostics)


# ══════════════════════════════════════════════════════════════════════════════════════════
# BU MODUL SHIPPED KODDA ISHLATILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_launcher_SHIPPED_kodda_one_click_tomonidan_ISHLATILADI():
    """⚠️⚠️ TUZATILGAN NUQSON: bu modulni shipped kodda HECH KIM import qilmasdi — faqat
    o'z testi. Ya'ni ishga tushirish abstraksiyasi ham, kooperativ bekor qilish ham
    e'lon qilingan-u YETIB BO'LMAYDIGAN qobiliyat edi.
    """
    from app.services.discovery_agent import one_click as oc

    manba = pathlib.Path(oc.__file__).read_text(encoding="utf-8")
    assert "import launcher as ln" in manba, "`one_click` `launcher` ni IMPORT qiladi"
    for nom in ("ln.wait_for_collector", "ln.open_infobase", "ln.choose_exe",
                "ln.LaunchTarget"):
        assert nom in manba, f"shipped yo'lda ishlatilmayapti: {nom}"
    # ⚠️ Bekor qilish tokeni ham UZATILADI (parametr bo'lib).
    assert "cancel=cancel" in manba
    # ⚠️ HALOL QAYD ham YANGILANADI: so'rov `one_click` ni ham ATAYDI.
    assert "one_click.py" in L.STATES_TEST_SOROVI
    assert "launcher.py" in L.STATES_TEST_SOROVI
    assert "ABORTED_BY_OPERATOR" in L.STATES_TEST_SOROVI
