# -*- coding: utf-8 -*-
"""`detector.py` shartnomasi — SINTETIK fiksturalar, HAQIQIY reestrga TEGMAYDI.

⚠️ Bu faylning birinchi qoidasi: HECH BIR test haqiqiy Windows reestrini va haqiqiy
`C:\\Program Files` ni O'QIMAYDI. Hamma manba (`RegistryReader`, `FileReader`, `which`,
soat) almashtiriladi. Sababi — bu mashinada 1C UMUMAN O'RNATILMAGAN, boshqa mashinada esa
BOR bo'lishi mumkin: haqiqiy muhitga qaragan test ikkinchi mashinada yiqilardi, ya'ni
to'plam «yashil» bo'lishini mashinaning holati hal qilardi.

⚠️ ENG MUHIM TEST — `test_reestr_oqilmadi_ornatma_yoqligi_bilan_aralashmaydi`:
«1C topilmadi» (`absent`, `FAILED_NO_1C` haqli) va «manbani o'qiy olmadim» (`unknown`,
`FAILED_NO_1C` HAQLI EMAS) IKKI XIL natija. Jimgina birlashtirish — ma'lumot yo'qotadigan
nuqson: huquqi cheklangan hisobda 1C BOR bo'lsa ham agent «yo'q» deb to'xtardi.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from app.services.discovery_agent import detector as D

HKLM = D.HKLM
INSTALL_KEY = r"SOFTWARE\1C\1Cv8"

#: Testlarning asosiy reestr sozlamasi — BITTA shox, izohlar shovqini kamroq bo'lsin.
ONE_HIVE = ((HKLM, INSTALL_KEY, "x64"),)


# ── Sintetik manbalar ───────────────────────────────────────────────────────────────────────
class FakeRegistry:
    """Xotiradagi reestr. ⚠️ `unreadable_prefixes` — «huquq yetmadi» ni taqlid qiladi."""

    def __init__(self, tree: dict | None = None, unreadable_prefixes: tuple[str, ...] = ()):
        self.tree = dict(tree or {})
        self.unreadable_prefixes = tuple(unreadable_prefixes)
        self.writes: list[str] = []  # ⚠️ hech qachon to'lmasligi kerak: yozish yo'q

    @staticmethod
    def key(hive: str, key: str) -> str:
        return f"{hive}|{key}"

    def _unreadable(self, full: str) -> bool:
        return any(full.startswith(p) for p in self.unreadable_prefixes)

    def subkeys(self, hive: str, key: str) -> D.ReadResult:
        full = self.key(hive, key)
        if self._unreadable(full):
            return D.unreadable("huquq yetmadi: PermissionError")
        node = self.tree.get(full)
        if node is None:
            return D.absent("reestr kaliti yo'q")
        return D.ok(sorted(node.get("subkeys", [])))

    def values(self, hive: str, key: str) -> D.ReadResult:
        full = self.key(hive, key)
        if self._unreadable(full):
            return D.unreadable("huquq yetmadi: PermissionError")
        node = self.tree.get(full)
        if node is None:
            return D.absent("reestr kaliti yo'q")
        return D.ok(dict(node.get("values", {})))

    def key_exists(self, hive: str, key: str) -> D.ReadResult:
        full = self.key(hive, key)
        if self._unreadable(full):
            return D.unreadable("huquq yetmadi: PermissionError")
        return D.ok(True) if full in self.tree else D.absent("reestr kaliti yo'q")


class FakeFiles:
    """Xotiradagi fayl tizimi. `listdir` DOIM tartiblangan — determinizm uchun."""

    def __init__(self, dirs: dict | None = None, files: tuple[str, ...] = (),
                 texts: dict | None = None, unreadable: tuple[str, ...] = ()):
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


def fixed_clock() -> str:
    return "2026-10-01T09:00:00+00:00"


def fixed_os() -> str | None:
    return "Windows-11-10.0.26200-SP0"


def no_path(_name: str) -> str | None:
    return None


def run(*, registry=None, files=None, which=no_path, config=None) -> D.EnvironmentScan:
    """Aniqlovchini FAQAT sintetik manbalar bilan yurgizadi."""
    return D.scan_environment(
        config=config if config is not None else D.DetectorConfig(registry_install_keys=ONE_HIVE),
        registry=registry if registry is not None else FakeRegistry(),
        files=files if files is not None else FakeFiles(),
        which=which,
        now=fixed_clock,
        os_version=fixed_os,
    )


def registry_with_versions(*versions: str, root: str = r"C:\Program Files\1cv8") -> FakeRegistry:
    """`HKLM\\SOFTWARE\\1C\\1Cv8` ostida berilgan versiyalar."""
    tree = {FakeRegistry.key(HKLM, INSTALL_KEY): {"subkeys": list(versions)}}
    for ver in versions:
        tree[FakeRegistry.key(HKLM, rf"{INSTALL_KEY}\{ver}")] = {
            "values": {"Path": rf"{root}\{ver}\bin\1cv8.exe"},
        }
    return FakeRegistry(tree)


# ── 1. 1C UMUMAN YO'Q -> absent ─────────────────────────────────────────────────────────────
def test_1c_umuman_yoq_absent_deb_belgilanadi():
    """Hamma manba o'qildi va bo'sh chiqdi -> `FAILED_NO_1C` HAQLI."""
    scan = run()
    assert scan.installs == ()
    assert scan.presence_verdict == D.PRESENCE_ABSENT
    assert scan.is_absent_proven is True
    assert [u for u in scan.unreadables if u.code in D._PRESENCE_CODES] == []


def test_absent_xulosasi_hisobotda_ochiq_yozilgan():
    """⚠️ Odam o'qiydigan izohda ham `absent` va `unknown` ADASHTIRILMASLIGI kerak."""
    notes = " | ".join(run().notes)
    assert "absent" in notes
    assert "unknown" not in notes


def test_har_bir_hujjatda_runtime_unknown_izohi_bor():
    """⚠️ 1C yo'q, demak aniqlash yo'li sinalmagan — buni hisobot O'ZI aytadi."""
    doc = run().to_document()
    assert D.RUNTIME_UNKNOWN_NOTE in doc["notes"]
    assert doc["notes"][0] == D.RUNTIME_UNKNOWN_NOTE


# ── 2. Bir nechta o'rnatma ──────────────────────────────────────────────────────────────────
def test_bir_nechta_ornatma_hammasi_royxatda_va_tartiblangan():
    """8.3.21 / 8.3.24 / 8.3.25 — uchalasi ham bor, versiya O'SISH tartibida."""
    scan = run(registry=registry_with_versions("8.3.25", "8.3.21", "8.3.24"))
    assert [i.version for i in scan.installs] == ["8.3.21", "8.3.24", "8.3.25"]
    assert {i.source for i in scan.installs} == {D.SOURCE_REGISTRY}
    assert scan.presence_verdict == D.PRESENCE_FOUND
    assert scan.is_absent_proven is False


def test_eng_yangi_ornatma_tanlanadi():
    """`batch_execute` yo'li uchun agent eng yangi `1cv8.exe` ni oladi."""
    scan = run(registry=registry_with_versions("8.3.21", "8.3.25", "8.3.24"))
    newest = scan.newest_install()
    assert newest is not None and newest.version == "8.3.25"
    assert newest.path is not None and newest.path.endswith(r"8.3.25\bin\1cv8.exe")


def test_versiyasi_nomalum_ornatma_oxirida_turadi():
    """⚠️ Versiyasi yo'q yozuv ENG YANGI deb tanlanmaydi — bilmaslik ustunlik bermaydi."""
    scan = run(registry=registry_with_versions("8.3.24"),
               which=lambda name: r"C:\1c\bin\1cv8.exe" if name == "1cv8.exe" else None)
    assert [i.version for i in scan.installs] == ["8.3.24", None]
    newest = scan.newest_install()
    assert newest is not None and newest.version == "8.3.24"


# ── 3. ⚠️ ASOSIY TEST: o'qilmadi != yo'q ────────────────────────────────────────────────────
def test_reestr_oqilmadi_ornatma_yoqligi_bilan_aralashmaydi():
    """⚠️ Huquq yetmagan reestr JIMGINA «1C topilmadi» ga aylanMAYDI."""
    reg = FakeRegistry(unreadable_prefixes=(FakeRegistry.key(HKLM, INSTALL_KEY),))
    scan = run(registry=reg)

    assert scan.installs == (), "o'qilmagan reestrdan o'rnatma o'ylab topilmasin"
    assert scan.presence_verdict == D.PRESENCE_UNKNOWN
    assert scan.is_absent_proven is False, "«yo'q» xulosasi HAQLI EMAS"

    codes = [u.code for u in scan.unreadables]
    assert D.CODE_REGISTRY_UNREADABLE in codes
    assert any("O'QILMADI" in n for n in scan.notes)
    assert any("HAQLI EMAS" in n for n in scan.notes)


def test_oqilmagan_reestr_absent_xulosasini_yozmaydi():
    """`absent` va `unknown` bir vaqtda e'lon qilinmaydi."""
    reg = FakeRegistry(unreadable_prefixes=(FakeRegistry.key(HKLM, INSTALL_KEY),))
    notes = " | ".join(run(registry=reg).notes)
    assert "unknown" in notes
    assert "(absent)" not in notes


def test_papka_oqilmadi_ham_unknown_beradi():
    """Fayl tizimi shoxi ham AYNI ajrimga bo'ysunadi."""
    root = r"C:\Program Files\1cv8"
    cfg = D.DetectorConfig(registry_install_keys=(),
                           filesystem_roots=(("program_files", root, "x64"),))
    scan = run(files=FakeFiles(unreadable=(root,)), config=cfg)
    assert scan.installs == ()
    assert scan.presence_verdict == D.PRESENCE_UNKNOWN
    assert [u.code for u in scan.unreadables] == [D.CODE_FILESYSTEM_UNREADABLE]


def test_papka_yoq_bu_absent_dalili():
    """Papkaning YO'QLIGI — to'liq javob, xato emas."""
    cfg = D.DetectorConfig(registry_install_keys=(),
                           filesystem_roots=(("program_files", r"C:\Program Files\1cv8", "x64"),))
    scan = run(config=cfg)
    assert scan.presence_verdict == D.PRESENCE_ABSENT
    assert scan.unreadables == ()


def test_reestrda_versiya_bor_yoli_oqilmadi_yozuv_qolib_ketadi():
    """⚠️ Versiya MA'LUM, yo'l o'qilmadi -> yozuv `path=None` bilan QOLADI, tashlanmaydi."""
    reg = FakeRegistry(
        tree={FakeRegistry.key(HKLM, INSTALL_KEY): {"subkeys": ["8.3.24"]}},
        unreadable_prefixes=(FakeRegistry.key(HKLM, rf"{INSTALL_KEY}\8.3.24"),),
    )
    scan = run(registry=reg)
    assert [(i.version, i.path) for i in scan.installs] == [("8.3.24", None)]
    assert scan.presence_verdict == D.PRESENCE_FOUND
    assert D.CODE_REGISTRY_UNREADABLE in [u.code for u in scan.unreadables]


def test_reestrda_yol_qiymati_yoq_yozuv_qolib_ketadi():
    reg = FakeRegistry(tree={
        FakeRegistry.key(HKLM, INSTALL_KEY): {"subkeys": ["8.3.24"]},
        FakeRegistry.key(HKLM, rf"{INSTALL_KEY}\8.3.24"): {"values": {"Foo": "bar"}},
    })
    scan = run(registry=reg)
    assert [(i.version, i.path) for i in scan.installs] == [("8.3.24", None)]
    assert any("yo'l noma'lum" in n for n in scan.notes)


def test_versiya_bolmagan_kichik_kalitlar_tashlanadi():
    """`HKLM\\...\\1Cv8\\AppCtx` kabi kalitlar versiya EMAS."""
    reg = FakeRegistry(tree={FakeRegistry.key(HKLM, INSTALL_KEY): {"subkeys": ["AppCtx", "Srvr"]}})
    scan = run(registry=reg)
    assert scan.installs == ()
    assert any("versiya kichik kaliti yo'q" in n for n in scan.notes)


# ── 4. COM — uchlik MATN ────────────────────────────────────────────────────────────────────
def test_com_royxatda_yoq_false():
    scan = run()
    assert scan.com_registered == D.TRI_FALSE


def test_com_royxatda_bor_true():
    reg = FakeRegistry(tree={FakeRegistry.key(D.HKCR, "V83.COMConnector"): {}})
    scan = run(registry=reg)
    assert scan.com_registered == D.TRI_TRUE
    assert any("RUNTIME-UNKNOWN" in n and "com:" in n for n in scan.notes)


def test_com_reestr_oqilmadi_unknown_false_emas():
    """⚠️ O'qiy olmaslik «yo'q» degani emas."""
    reg = FakeRegistry(unreadable_prefixes=("HKCR|", r"HKLM|SOFTWARE\Classes",
                                            r"HKLM|SOFTWARE\WOW6432Node\Classes"))
    scan = run(registry=reg)
    assert scan.com_registered == D.TRI_UNKNOWN
    assert D.CODE_COM_UNREADABLE in [u.code for u in scan.unreadables]


def test_com_oqilmagani_ornatma_xulosasini_buzmaydi():
    """⚠️ COM — o'rnatma manbasi EMAS: uning o'qilmagani `FAILED_NO_1C` ni yashirmaydi."""
    reg = FakeRegistry(unreadable_prefixes=("HKCR|", r"HKLM|SOFTWARE\Classes",
                                            r"HKLM|SOFTWARE\WOW6432Node\Classes"))
    scan = run(registry=reg)
    assert scan.com_registered == D.TRI_UNKNOWN
    assert scan.presence_verdict == D.PRESENCE_ABSENT


@pytest.mark.parametrize("value", [D.TRI_TRUE, D.TRI_FALSE, D.TRI_UNKNOWN])
def test_com_qiymatlari_matn(value):
    """JSON'da boolean YO'Q — loyiha qoidasi."""
    assert isinstance(value, str)


# ── 5. Fayl tizimi va PATH ──────────────────────────────────────────────────────────────────
def test_fayl_tizimidan_ornatma_topiladi():
    root = r"C:\Program Files\1cv8"
    cfg = D.DetectorConfig(registry_install_keys=(),
                           filesystem_roots=(("program_files", root, "x64"),))
    files = FakeFiles(dirs={root: ["8.3.24.1234", "common", "8.3.25.1"]},
                      files=(rf"{root}\8.3.24.1234\bin\1cv8.exe",
                             rf"{root}\8.3.25.1\bin\1cv8.exe"))
    scan = run(files=files, config=cfg)
    assert [i.version for i in scan.installs] == ["8.3.24.1234", "8.3.25.1"]
    assert {i.source for i in scan.installs} == {D.SOURCE_FILESYSTEM}


def test_versiya_papkasi_bor_exe_yoq_royxatga_tushmaydi():
    root = r"C:\Program Files\1cv8"
    cfg = D.DetectorConfig(registry_install_keys=(),
                           filesystem_roots=(("program_files", root, "x64"),))
    scan = run(files=FakeFiles(dirs={root: ["8.3.24"]}), config=cfg)
    assert scan.installs == ()
    assert any("1cv8.exe yo'q" in n for n in scan.notes)


def test_x86_yoli_bitlikni_aniqlaydi():
    root = r"C:\Program Files (x86)\1cv8"
    cfg = D.DetectorConfig(registry_install_keys=(),
                           filesystem_roots=(("program_files_x86", root, "x86"),))
    files = FakeFiles(dirs={root: ["8.3.24"]}, files=(rf"{root}\8.3.24\bin\1cv8.exe",))
    scan = run(files=files, config=cfg)
    assert [i.bitness for i in scan.installs] == ["x86"]


def test_path_manbasi_alohida_belgilanadi():
    """PATH dagi exe — ALOHIDA `source`, versiyasi yo'ldan olinadi."""
    which = {"1cv8.exe": r"C:\1cv8\8.3.24.1234\bin\1cv8.exe",
             "ibcmd.exe": r"C:\1cv8\8.3.24.1234\bin\ibcmd.exe"}
    scan = run(which=which.get)
    assert {i.source for i in scan.installs} == {D.SOURCE_PATH}
    assert {i.version for i in scan.installs} == {"8.3.24.1234"}


def test_path_versiyasi_bilinmasa_none_bolib_qoladi():
    """⚠️ Versiya o'ylab topilmaydi: bilmaslik `None` bo'lib yozuvda qoladi."""
    scan = run(which=lambda n: r"C:\1c\1cv8.exe" if n == "1cv8.exe" else None)
    assert [i.version for i in scan.installs] == [None]
    assert any("versiya yo'ldan bilinmadi" in n for n in scan.notes)


def test_bir_xil_exe_ikki_manbadan_bir_marta_sanaladi():
    """⚠️ Dedup: reestr yozuvi fayl tizimidagi AYNI exe bilan birlashadi, manba ISHONCHLISI."""
    root = r"C:\Program Files\1cv8"
    exe = rf"{root}\8.3.24\bin\1cv8.exe"
    cfg = D.DetectorConfig(registry_install_keys=ONE_HIVE,
                           filesystem_roots=(("program_files", root, "x64"),))
    scan = run(registry=registry_with_versions("8.3.24", root=root),
               files=FakeFiles(dirs={root: ["8.3.24"]}, files=(exe,)),
               which=lambda n: exe if n == "1cv8.exe" else None,
               config=cfg)
    assert len(scan.installs) == 1
    assert scan.installs[0].source == D.SOURCE_REGISTRY
    assert any("takrorlandi" in n for n in scan.notes)


# ── 6. `ibases.v8i` ─────────────────────────────────────────────────────────────────────────
IBASES_USER = r"C:\Users\kassir\AppData\Roaming\1C\1CEStart\ibases.v8i"
IBASES_COMMON = r"C:\ProgramData\1C\1CEStart\ibases.v8i"

IBASES_CFG = D.DetectorConfig(
    registry_install_keys=(),
    ibases_files=((D.SOURCE_IBASES_USER, IBASES_USER),
                  (D.SOURCE_IBASES_COMMON, IBASES_COMMON)),
)

V8I_OK = (
    "[Fayzan savdo]\n"
    'Connect=File="C:\\bases\\fayzan";\n'
    "ID=4a1d\n"
    "OrderInList=100\n"
    "\n"
    "[Markaziy server]\n"
    'Connect=Srvr="srv1";Ref="trade";\n'
    "OrderInList=200\n"
)


def test_ibases_fayl_bazasi_va_server_bazasi_oqiladi():
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_OK}), config=IBASES_CFG)
    assert [(b.kind, b.locator, b.name) for b in scan.infobases] == [
        (D.KIND_FILE, r"C:\bases\fayzan", "Fayzan savdo"),
        (D.KIND_SERVER, "srv1/trade", "Markaziy server"),
    ]
    assert {b.source for b in scan.infobases} == {D.SOURCE_IBASES_USER}


def test_ibases_fayli_yoq_aniq_qayd_istisno_yoq():
    scan = run(config=IBASES_CFG)
    assert scan.infobases == ()
    assert sum("ibases.v8i yo'q" in n for n in scan.notes) == 2
    assert scan.unreadables == ()


def test_ibases_fayli_bosh_aniq_qayd():
    scan = run(files=FakeFiles(texts={IBASES_USER: "   \n\n"}), config=IBASES_CFG)
    assert scan.infobases == ()
    assert any("BO'SH" in n for n in scan.notes)


def test_ibases_buzuq_fayl_istisno_tashlamaydi():
    """Bo'limsiz, kalitlari osilgan, qavslari yarim — qayd etiladi, yiqilmaydi."""
    broken = "bu umuman v8i emas\nConnect=File=\"C:\\x\"\n[yarim\n=qiymat\n"
    scan = run(files=FakeFiles(texts={IBASES_USER: broken}), config=IBASES_CFG)
    assert scan.infobases == ()
    assert any("buzuq" in n or "tanilmadi" in n for n in scan.notes)


def test_ibases_oqilmadi_unreadable_bolib_qoladi():
    scan = run(files=FakeFiles(unreadable=(IBASES_USER,)), config=IBASES_CFG)
    assert [u.code for u in scan.unreadables] == [D.CODE_IBASES_UNREADABLE]
    # ⚠️ Infobaza ro'yxati o'rnatma dalili EMAS — `presence` ga ta'sir qilmaydi.
    assert scan.presence_verdict == D.PRESENCE_ABSENT


def test_ibases_takrorlangan_baza_bir_marta():
    files = FakeFiles(texts={IBASES_USER: V8I_OK, IBASES_COMMON: V8I_OK})
    scan = run(files=files, config=IBASES_CFG)
    assert len(scan.infobases) == 2
    assert any("takrorlangan" in n for n in scan.notes)


def test_connect_tanilmasa_aniq_qayd():
    text = "[Begona]\nConnect=Ws=\"http://x\";\n"
    scan = run(files=FakeFiles(texts={IBASES_USER: text}), config=IBASES_CFG)
    assert scan.infobases == ()
    assert any("Connect yo'q" in n for n in scan.notes)


# ── 7. ⚠️ PAROL CHIQISHGA TUSHMAYDI ─────────────────────────────────────────────────────────
V8I_WITH_PASSWORD = (
    "[Fayzan savdo]\n"
    'Connect=File="C:\\bases\\fayzan";Usr="Администратор";Pwd="hunter2";\n'
    "ID=4a1d\n"
    "[Server bazasi]\n"
    'Connect=Srvr="srv1";Ref="trade";Usr="admin";Pwd="qwerty123";\n'
)


def test_ibases_paroli_hujjatga_tushmaydi():
    """⚠⚠ `.v8i` da parol BO'LISHI MUMKIN — chiqishda na parol, na login qolmaydi."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_WITH_PASSWORD}), config=IBASES_CFG)
    blob = D.dump_document(scan)
    for secret in ("hunter2", "qwerty123", "Администратор", "admin", "Pwd", "Usr"):
        assert secret not in blob, f"sir chiqishga tushdi: {secret!r}"


def test_parol_xotiradagi_obyektda_ham_saqlanmaydi():
    """⚠️ Redaksiya oxirgi to'siq, BIRINCHISI emas: parol umuman O'QILMAYDI."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_WITH_PASSWORD}), config=IBASES_CFG)
    blob = repr(scan)
    assert "hunter2" not in blob and "qwerty123" not in blob


def test_parol_borligi_requires_auth_ni_true_qiladi():
    """Parol/login yozilgan baza — autentifikatsiya talab qiladi (`FAILED_AUTH_REQUIRED` yo'li)."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_WITH_PASSWORD}), config=IBASES_CFG)
    assert [b.requires_auth for b in scan.infobases] == [D.TRI_TRUE, D.TRI_TRUE]


def test_requires_auth_aniqlanmasa_unknown():
    """⚠️ `"false"` HECH QACHON berilmaydi: parolsizlikni ULANMASDAN isbotlab bo'lmaydi."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_OK}), config=IBASES_CFG)
    values = {b.requires_auth for b in scan.infobases}
    assert values == {D.TRI_UNKNOWN}
    assert D.TRI_FALSE not in values


def test_fayl_yoli_hujjatda_redaksiyalanadi_xotirada_xom_qoladi():
    """⚠️ Agent XOM yo'l bilan ishlaydi, hujjat esa do'kondan chiqadi — unda yo'l qolmaydi."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_OK}), config=IBASES_CFG)
    assert scan.infobases[0].locator == r"C:\bases\fayzan"
    doc = scan.to_document()
    assert doc["infobases"][0]["locator"] == "[REDACTED]"
    assert r"C:\bases" not in json.dumps(doc, ensure_ascii=False)


def test_ornatma_yoli_ham_hujjatda_niqoblanadi():
    scan = run(registry=registry_with_versions("8.3.24"))
    assert scan.installs[0].path is not None
    doc = scan.to_document()
    assert doc["installs"][0]["path"] == D._redact.MASK
    assert doc["installs"][0]["version"] == "8.3.24", "versiya niqoblanmaydi — u sir emas"


def test_probelli_windows_yoli_TOLIQ_niqoblanadi():
    """⚠️⚠️ `redact` ning TOPILGAN kamchiligi shu yerda qulflanadi.

    `redact.windows_file_path` naqshi probelda TO'XTAYDI, 1C yo'li esa aynan probelli
    (`C:\\Program Files\\...`): faqat `redact` ga tayanilsa hujjatda
    `Files\\1cv8\\8.3.24\\bin\\1cv8.exe` QOLARDI. Shu bois yo'l maydonlari aniqlovchining
    O'ZIDA to'liq niqoblanadi.
    """
    root = r"C:\Program Files\1cv8"
    scan = run(registry=registry_with_versions("8.3.24", root=root))
    blob = json.dumps(scan.to_document(), ensure_ascii=False)
    for leak in ("Program", "Files", "1cv8.exe", r"\bin"):
        assert leak not in blob, f"yo'lning bo'lagi hujjatda qoldi: {leak!r}"


def test_server_bazasining_locatori_niqoblanmaydi():
    """⚠️ `srvr/ref` yo'l EMAS: uni niqoblash «qaysi bazani tanladim?» savolini o'chirardi."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_OK}), config=IBASES_CFG)
    server = [b for b in scan.to_document()["infobases"] if b["kind"] == D.KIND_SERVER]
    assert [b["locator"] for b in server] == ["srv1/trade"]


def test_ip_portli_server_manzili_redact_bilan_niqoblanadi():
    """Server manzili IP:port bo'lsa — `redact` ning zaxira qatlami ishlaydi."""
    text = '[Baza]\nConnect=Srvr="192.168.1.5:1541";Ref="trade";\n'
    scan = run(files=FakeFiles(texts={IBASES_USER: text}), config=IBASES_CFG)
    assert "192.168.1.5" not in json.dumps(scan.to_document(), ensure_ascii=False)


def test_unreadable_izohlarida_xom_yol_yoq():
    """⚠️ `scope`/`detail` yorliq bilan yoziladi — aks holda redaksiya izohni o'chirardi."""
    scan = run(files=FakeFiles(unreadable=(IBASES_USER,)), config=IBASES_CFG)
    for u in scan.unreadables:
        assert "\\" not in u.detail
        assert ":\\" not in u.scope


# ── 8. Windows EMAS ─────────────────────────────────────────────────────────────────────────
def test_winreg_yoq_bolsa_modul_ishlaydi_va_unknown_beradi(monkeypatch):
    """⚠️ `winreg` yo'q (Linux/CI) -> modul IMPORT QILINADI, natija `unknown`, `false` EMAS."""
    monkeypatch.setattr(D, "_winreg", None)
    scan = D.scan_environment(
        config=D.DetectorConfig(registry_install_keys=ONE_HIVE),
        registry=D.WinregRegistry(),   # haqiqiy sinf, lekin winreg YO'Q
        files=FakeFiles(),
        which=no_path,
        now=fixed_clock,
        os_version=fixed_os,
    )
    assert scan.com_registered == D.TRI_UNKNOWN
    assert scan.installs == ()
    assert scan.presence_verdict == D.PRESENCE_UNKNOWN
    assert scan.is_absent_proven is False
    assert all("winreg" in u.detail for u in scan.unreadables)


def test_winreg_yoq_bolsa_har_bir_oqish_unreadable(monkeypatch):
    monkeypatch.setattr(D, "_winreg", None)
    reg = D.WinregRegistry()
    for res in (reg.subkeys(HKLM, INSTALL_KEY), reg.values(HKLM, INSTALL_KEY),
                reg.key_exists(D.HKCR, "V83.COMConnector")):
        assert res.is_unreadable
        assert res.is_absent is False


# ── 9. Hujjat shakli va determinizm ─────────────────────────────────────────────────────────
def test_hujjat_kalitlari_aynan_shartnomadagidek():
    doc = run().to_document()
    assert list(doc) == ["env_version", "scanned_at", "os_version", "installs",
                         "com_registered", "infobases", "selected", "notes"]
    assert doc["env_version"] == "binos-agent-env-v1"
    assert doc["selected"] is None


def test_install_va_infobase_kalitlari_aynan_shartnomadagidek():
    files = FakeFiles(texts={IBASES_USER: V8I_OK})
    cfg = D.DetectorConfig(registry_install_keys=ONE_HIVE,
                           ibases_files=((D.SOURCE_IBASES_USER, IBASES_USER),))
    doc = run(registry=registry_with_versions("8.3.24"), files=files, config=cfg).to_document()
    assert list(doc["installs"][0]) == ["path", "version", "bitness", "source"]
    assert list(doc["infobases"][0]) == ["kind", "locator", "name", "source", "requires_auth"]


def test_aniqlovchi_ozi_nishon_tanlamaydi():
    """⚠️ `selected` — `TARGET_SELECTION` holatining ishi, aniqlovchining emas."""
    scan = run(files=FakeFiles(texts={IBASES_USER: V8I_OK}), config=IBASES_CFG)
    assert scan.selected is None
    chosen = scan.with_selection("srv1/trade")
    assert chosen.selected == "srv1/trade"
    assert scan.selected is None, "frozen dataclass — asl obyekt o'zgarmaydi"
    assert chosen.to_document()["selected"] == "srv1/trade"


def test_errors_agent_status_shaklida():
    reg = FakeRegistry(unreadable_prefixes=(FakeRegistry.key(HKLM, INSTALL_KEY),))
    errors = run(registry=reg).errors()
    assert errors and all(list(e) == ["scope", "code", "detail"] for e in errors)


def test_determinizm_bir_xil_fikstura_bir_xil_bayt():
    """⚠️ Bir xil kirish -> bir xil BAYT (hisobot farqi faqat haqiqiy o'zgarishdan bo'lsin)."""
    root = r"C:\Program Files\1cv8"
    cfg = D.DetectorConfig(
        registry_install_keys=ONE_HIVE,
        filesystem_roots=(("program_files", root, "x64"),),
        ibases_files=((D.SOURCE_IBASES_USER, IBASES_USER),),
    )

    def once() -> str:
        return D.dump_document(run(
            registry=registry_with_versions("8.3.25", "8.3.21", root=root),
            files=FakeFiles(dirs={root: ["8.3.24"]},
                            files=(rf"{root}\8.3.24\bin\1cv8.exe",),
                            texts={IBASES_USER: V8I_OK}),
            which=lambda n: r"C:\1c\8.3.26.1\bin\1cv8.exe" if n == "1cv8.exe" else None,
            config=cfg))

    first = once()
    assert first == once()
    assert first.encode("utf-8") == once().encode("utf-8")
    assert json.loads(first)["env_version"] == "binos-agent-env-v1"


def test_sanoqlar_hujjatda_son_sifatida_yozilmaydi():
    """Loyiha qoidasi: sanoq JSON'da MATN. Shakl umuman sonli maydon SAQLAMAYDI."""
    doc = run(registry=registry_with_versions("8.3.24")).to_document()
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)
        else:
            yield node
    assert not [v for v in walk(doc) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    assert not [v for v in walk(doc) if isinstance(v, bool)]


# ── 10. Xavfsizlik invariantlari ────────────────────────────────────────────────────────────
_DETECTOR_SOURCE = pathlib.Path(D.__file__).read_text(encoding="utf-8")

_FORBIDDEN_MODULES = frozenset({
    "socket", "requests", "urllib", "http", "ssl", "ftplib", "smtplib", "telnetlib",
    "asyncio", "subprocess", "win32com", "pythoncom", "win32api",
})
_ALLOWED_MODULES = frozenset({
    "json", "os", "platform", "re", "shutil", "dataclasses", "datetime", "typing",
    "winreg", "__future__", "app.services.discovery_1c",
})


def test_detectorda_tarmoq_importi_yoq():
    """⚠️ Offline-first: `socket`/`urllib`/`http.client`/`requests` BO'LMASIN.

    Tekshiruv `ast` bilan: oddiy matn qidiruvi docstring'dagi ESLATMAni ham topib,
    testni yolg'on yashil (yoki yolg'on qizil) qilardi.
    """
    imported: set[str] = set()
    for node in ast.walk(ast.parse(_DETECTOR_SOURCE)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    assert not (roots & _FORBIDDEN_MODULES), f"taqiqlangan import: {roots & _FORBIDDEN_MODULES}"
    assert imported <= _ALLOWED_MODULES, f"ruxsatsiz import: {imported - _ALLOWED_MODULES}"


_FORBIDDEN_NAMES = frozenset({
    "SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx",
    "DeleteValue", "SaveKey", "KEY_WRITE", "KEY_SET_VALUE", "KEY_CREATE_SUB_KEY",
    "KEY_ALL_ACCESS", "CreateObject", "Dispatch", "DispatchEx", "Записать", "Провести",
    "mkdir", "makedirs", "remove", "unlink", "rmtree", "rename", "write_text",
    "write_bytes", "run", "Popen", "system", "startfile",
})


def test_detectorda_yozish_va_com_chaqiruvlari_yoq():
    """FAQAT O'QISH: reestrga yozish, fayl yozish, COM obyekti yaratish BO'LMASIN.

    ⚠️ Tekshiruv `ast` bilan, matn qidiruvi bilan EMAS: modul docstringi `CreateObject`
    CHAQIRILMAYDI deb YOZADI, matn qidiruvi esa aynan shu izohga qarab yolg'on qizil berardi.
    """
    tree = ast.parse(_DETECTOR_SOURCE)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Name):
            used.add(node.id)
    assert not (used & _FORBIDDEN_NAMES), f"yozish/COM chaqiruvi: {sorted(used & _FORBIDDEN_NAMES)}"


def test_detectorda_fayl_faqat_oqish_rejimida_ochiladi():
    """`open(...)` faqat `rb` bilan — yozish rejimi BO'LMASIN."""
    modes = set()
    for node in ast.walk(ast.parse(_DETECTOR_SOURCE)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            modes.update(a.value for a in node.args[1:] if isinstance(a, ast.Constant))
            modes.update(k.value.value for k in node.keywords
                         if k.arg == "mode" and isinstance(k.value, ast.Constant))
    assert modes == {"rb"}, f"kutilmagan ochish rejimi: {sorted(modes)}"


def test_reestr_faqat_key_read_bilan_ochiladi():
    assert "KEY_READ" in _DETECTOR_SOURCE


def test_sintetik_fiksturalar_hech_narsa_yozmaydi():
    reg = FakeRegistry(tree={FakeRegistry.key(HKLM, INSTALL_KEY): {"subkeys": ["8.3.24"]}})
    run(registry=reg)
    assert reg.writes == []


# ── 11. Haqiqiy fayl o'qiydigan qatlam (faqat tmp_path) ─────────────────────────────────────
def test_real_file_reader_kodirovkalarni_oqiydi(tmp_path: pathlib.Path):
    """`.v8i` ni 1CEStart UTF-8 (BOM) yoki `cp1251` da yozadi — ikkisi ham o'qilsin."""
    reader = D.RealFileReader()
    utf = tmp_path / "utf.v8i"
    utf.write_bytes("[Файзан]\n".encode("utf-8-sig"))
    cp = tmp_path / "cp.v8i"
    cp.write_bytes("[Файзан]\n".encode("cp1251"))
    for path in (utf, cp):
        res = reader.read_text(str(path))
        assert res.is_ok and res.value is not None and "Файзан" in res.value


def test_real_file_reader_yoq_fayl_absent(tmp_path: pathlib.Path):
    """⚠️ Fayl YO'Q — `absent`, `unreadable` EMAS."""
    res = D.RealFileReader().read_text(str(tmp_path / "yoq.v8i"))
    assert res.is_absent and not res.is_unreadable


def test_real_file_reader_papka_yoq_absent(tmp_path: pathlib.Path):
    res = D.RealFileReader().listdir(str(tmp_path / "yoq"))
    assert res.is_absent and not res.is_unreadable
