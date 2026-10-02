# -*- coding: utf-8 -*-
"""1C MUHITINI ANIQLOVCHI — `binos-agent-env-v1` hujjatini quradi. FAQAT O'QISH.

Agentning BIRINCHI holati (`ENVIRONMENT_SCAN`) shu modulni chaqiradi: do'kon kompyuterida
1C bormi, qaysi versiyalar, COM klassi ro'yxatdanmi va qanday infobazalar e'lon qilingan.
Keyin `TARGET_SELECTION` natijadan nishon tanlaydi.

⚠️⚠️ RUNTIME-UNKNOWN — OCHIQ YOZILADI
Bu kod HAQIQIY 1C o'rnatmasiga qarshi HECH QACHON sinalmagan. Yozilgan mashinada 1C
UMUMAN O'RNATILMAGAN: `C:\\Program Files\\1cv8` yo'q, `HKLM\\SOFTWARE\\1C\\1Cv8` yo'q,
`1cv8.exe`/`1cestart.exe`/`ibcmd.exe` PATH da yo'q, `V83.COMConnector`/`V82.COMConnector`/
`V83.Application`/`V82.Application` klasslari ro'yxatda yo'q. Shu bois modulning testlari
FAQAT SINTETIK reestr va fayl tizimi fiksturalariga qarshi yuradi. «Ishlaydi» deb aytish
mumkin emas — aniqlash yo'li `RUNTIME-UNKNOWN`, va shu `RUNTIME_UNKNOWN_NOTE` bilan har bir
chiqish hujjatiga YOZILADI, hisobotni o'qigan odam buni taxmin qilib qolmasin.

QAT'IY CHEKLOVLAR (buzilishi = regressiya):
  · FAQAT O'QISH. Reestr `KEY_READ` bilan ochiladi, COM OBYEKTI YARATILMAYDI (klass BORMI
    degan savolga reestrni O'QIB javob beriladi), `.v8i` fayli o'qiladi va YOZILMAYDI.
  · TARMOQ YO'Q: bu modulda `socket`/`urllib`/`http.client`/`requests` importi YO'Q.
  · TASHQI KUTUBXONA YO'Q: faqat stdlib (`winreg`, `shutil`, `platform`, `json`, `re`, `os`).
    Sabab: do'kon kompyuterida `pywin32` yo'q va Python o'rnatish talab qilinmasligi kerak.
  · KREDENSIAL YO'Q: na parol, na login, na to'liq ulanish satri hujjatga TUSHMAYDI.

⚠️ ASOSIY AJRIM — «YO'Q» va «O'QIB BO'LMADI» IKKI XIL NATIJA
`UNKNOWN` hech qachon `NOT_FOUND` ga aylanmaydi. Shu bois har bir o'qish uch holatli
(`ReadResult`: `ok` | `absent` | `unreadable`) va natijada:
  · `installs == []` va o'qilmagan manba YO'Q      -> `presence_verdict == "absent"`  (FAILED_NO_1C)
  · `installs == []` va manba O'QILMADI (huquq)    -> `presence_verdict == "unknown"` (FAILED_NO_1C EMAS)
⚠️ Hukmning O'ZI `environment.json` ga ham YOZILADI (`to_document()`): u faqat
`agent_status.json` da turganda muhit hujjatini o'qigan odam `installs: []` ni ko'rib
sababni BILA olmasdi (`to_document` docstringiga qarang).
Ikkinchi holatda sabab `unreadable` yozuvlarida qoladi va JIMGINA «1C topilmadi» ga
aylanMAYDI. Aynan shu jimgina aylanish ma'lumot yo'qotadigan nuqson bo'lardi: huquqi
cheklangan kassir hisobida 1C BOR bo'lsa ham agent «yo'q» deb to'xtardi.

⚠️ NEGA IKKI XIL CHIQISH: `EnvironmentScan` (xotirada, XOM yo'llar bilan) va
`to_document()` (diskka yoziladigan, NIQOBLANGAN). Agent `batch_execute` yo'lida
`1cv8.exe` ning HAQIQIY yo'liga muhtoj, hujjat esa do'kondan tashqariga chiqadi va unda
mashina ichki tuzilmasi bo'lmasligi kerak. Brief faqat `locator` ni talab qiladi, lekin
`installs[].path` ham xuddi shunday mahalliy yo'l — uni qoldirish yarim chora bo'lardi.
⚠️ NARXI OCHIQ: niqoblashdan keyin IKKI fayl infobazasining `locator` i bir xil
`[REDACTED]` ko'rinadi. Odam ularni `name` bo'yicha ajratadi; agent esa hujjatdan EMAS,
`EnvironmentScan` dan ishlaydi, shu bois bu faqat hisobotga taalluqli.

⚠️⚠️ TOPILGAN CHEKLOV — `redact` O'ZI YETARLI EMAS (bu yerda qulflangan)
`redact.VALUE_PATTERNS` dagi `windows_file_path` naqshi `(?i)\\b[a-z]:\\\\[^\\s"';,]*` —
ya'ni u PROBELDA TO'XTAYDI. 1C ning odatiy yo'li esa AYNAN probelli:
`C:\\Program Files\\1cv8\\8.3.24\\bin\\1cv8.exe` dan faqat `C:\\Program` niqoblanadi va
qolgan `Files\\1cv8\\8.3.24\\bin\\1cv8.exe` hujjatda QOLADI. Shu bois yo'l maydonlari
(`installs[].path`, `infobases[].locator`) ASOSIY nazorat sifatida BU MODULDA to'liq
`MASK` bilan almashtiriladi, `redact` esa ikkinchi qatlam (zaxira) bo'lib qoladi:
`redact` ni «tuzatish» butun Phase 3/4 darvozasining xulqini o'zgartirardi, shu bois
unga TEGILMAYDI, kamchiligi esa shu yerda yopiladi va test bilan qulflanadi.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.services.discovery_1c import redact as _redact

# ⚠️ `winreg` FAQAT Windows'da bor. Import HIMOYALANGAN: modul Windows'siz muhitda ham
#    IMPORT QILINADI (CI Linux'da yuradi), natija esa `"unknown"` bo'ladi — `"false"` EMAS.
try:  # pragma: no cover - platformaga bog'liq shox
    import winreg as _winreg
except ImportError:  # pragma: no cover - Windows emas
    _winreg = None  # type: ignore[assignment]

ENV_VERSION = "binos-agent-env-v1"

#: Har bir chiqish hujjatiga MAJBURIY qo'shiladigan izoh — yuqoridagi docstring'ning qisqasi.
RUNTIME_UNKNOWN_NOTE = (
    "RUNTIME-UNKNOWN: aniqlovchi HAQIQIY 1C o'rnatmasiga qarshi sinalmagan "
    "(faqat sintetik reestr va fayl tizimi fiksturalari)"
)

# ── Uch holatli MATN qiymatlari ─────────────────────────────────────────────────────────────
# ⚠️ Loyiha qoidasi: JSON'da boolean YO'Q, uchlik esa MATN. `"unknown"` — to'liq huquqli
#    javob, `"false"` o'rniga ishlatiladi.
TRI_TRUE = "true"
TRI_FALSE = "false"
TRI_UNKNOWN = "unknown"

# ── O'qish natijasi: ok | absent | unreadable ───────────────────────────────────────────────
READ_OK = "ok"
READ_ABSENT = "absent"
READ_UNREADABLE = "unreadable"

# ── O'rnatma manbalari (brief lug'ati) ──────────────────────────────────────────────────────
SOURCE_REGISTRY = "registry"
SOURCE_FILESYSTEM = "filesystem"
SOURCE_PATH = "path"
INSTALL_SOURCES = (SOURCE_REGISTRY, SOURCE_FILESYSTEM, SOURCE_PATH)

#: Dedup ustuvorligi: reestr eng ishonchli (versiyani O'ZI aytadi), `PATH` eng kuchsizi
#: (faqat bitta exe, versiya odatda noma'lum).
_SOURCE_RANK = {SOURCE_REGISTRY: 0, SOURCE_FILESYSTEM: 1, SOURCE_PATH: 2}

# ── Infobaza manbalari ──────────────────────────────────────────────────────────────────────
# ⚠️ Brief `source` lug'atini FAQAT `installs` uchun belgilagan (registry|filesystem|path).
#    `infobases` uchun esa MUHIMI — qaysi RO'YXATdan kelgani: foydalanuvchi ro'yxati
#    (`%APPDATA%`) va butun mashina ro'yxati (`%ALLUSERSPROFILE%`) egasi va ishonchi bilan
#    farq qiladi, ikkisini «filesystem» deb birlashtirish ma'lumot yo'qotardi.
SOURCE_IBASES_USER = "ibases_user"
SOURCE_IBASES_COMMON = "ibases_common"

# ── Infobaza turlari ────────────────────────────────────────────────────────────────────────
KIND_FILE = "file"
KIND_SERVER = "server"

# ── `presence_verdict` ──────────────────────────────────────────────────────────────────────
PRESENCE_FOUND = "found"
PRESENCE_ABSENT = "absent"
PRESENCE_UNKNOWN = "unknown"

# ── `unreadable` kodlari ────────────────────────────────────────────────────────────────────
CODE_REGISTRY_UNREADABLE = "registry_unreadable"
CODE_FILESYSTEM_UNREADABLE = "filesystem_unreadable"
CODE_PATH_UNREADABLE = "path_unreadable"
CODE_COM_UNREADABLE = "com_unreadable"
CODE_IBASES_UNREADABLE = "ibases_unreadable"

#: ⚠️ FAQAT shu kodlar «1C bor-yo'qligini bilmadim» degan xulosaga olib keladi. COM va
#:    infobaza ro'yxati o'qilmagani o'rnatma bor-yo'qligi haqida hech narsa demaydi, shu bois
#:    ular `presence_verdict` ni `"unknown"` ga BURMAYDI (aks holda har bir cheklangan
#:    hisobda agent `FAILED_NO_1C` ni ko'rmay qolardi).
_PRESENCE_CODES = frozenset({CODE_REGISTRY_UNREADABLE, CODE_FILESYSTEM_UNREADABLE,
                             CODE_PATH_UNREADABLE})

# ── Reestr va fayl tizimi nishonlari ────────────────────────────────────────────────────────
HKLM = "HKLM"
HKCU = "HKCU"
HKCR = "HKCR"

#: Brief belgilagan uchta shox. Uchinchi element — BITLIK ISHORASI (yo'ldagi `(x86)` ustun).
#: ⚠️ `WOW6432Node` — 64-bit Windows'da 32-bit ilovalar ko'radigan ko'rinish, shu bois u
#:    yerdagi yozuv 32-bitli o'rnatma haqida. `HKCU` esa foydalanuvchi o'rnatmasi: bitligi
#:    yo'lidan boshqa hech narsadan bilinmaydi -> `"unknown"`.
REGISTRY_INSTALL_KEYS: tuple[tuple[str, str, str], ...] = (
    (HKLM, r"SOFTWARE\1C\1Cv8", "x64"),
    (HKLM, r"SOFTWARE\WOW6432Node\1C\1Cv8", "x86"),
    (HKCU, r"SOFTWARE\1C\1Cv8", TRI_UNKNOWN),
)

#: COM klasslari — reestrda BORMI degan savol. ⚠️ `CreateObject` CHAQIRILMAYDI: COM obyektini
#: yaratish 1C ni ishga tushirib, bazaga ULANISHga urinishi mumkin, bu esa «faqat o'qish»
#: kafolatidan tashqari.
COM_CLASS_IDS: tuple[str, ...] = (
    "V83.COMConnector",
    "V82.COMConnector",
    "V83.Application",
    "V82.Application",
)

#: Har bir klass shu uch joyda qaraladi (ProgID → `HKCR` va `Classes` nusxalari).
_COM_KEY_TEMPLATES: tuple[tuple[str, str], ...] = (
    (HKCR, "{cls}"),
    (HKLM, r"SOFTWARE\Classes\{cls}"),
    (HKLM, r"SOFTWARE\WOW6432Node\Classes\{cls}"),
)

#: Reestrda o'rnatma yo'li shu nomlardan birida turadi (`""` — kalitning standart qiymati).
_REGISTRY_PATH_VALUE_NAMES = ("Path", "InstalledLocation", "InstallLocation", "")

#: `PATH` da qaraladigan bajariladigan fayllar.
PATH_EXECUTABLES: tuple[str, ...] = ("1cv8.exe", "1cestart.exe", "ibcmd.exe")

# ── KLIENT TURLARI ──────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ NEGA KERAK: ishga tushiruvchi (`launcher.py`) «1C ni oching» deyishdan oldin QAYSI
#      bajariluvchi fayl bilan ochilishini bilishi kerak. Semiz klient (`1cv8.exe`) fayl
#      bazasini ham, serverni ham ochadi; yupqa klient (`1cv8c.exe`) esa FAQAT server/veb
#      ulanishi uchun. Ikkisini «1C» deb birlashtirish operatorga mavjud bo'lmagan yo'lni
#      ko'rsatishga olib kelardi.
# ⚠️ Mavjud aniqlash O'ZGARMAYDI: `installs` ro'yxati, uning tartibi va `environment.json`
#    kalitlari AVVALGIDEK qoladi — bu yerda FAQAT yangi maydon QO'SHILADI.
CLIENT_THICK = "thick_client"
CLIENT_THIN = "thin_client"
CLIENT_DESIGNER = "designer"
CLIENT_SERVER_AGENT = "server_agent"
CLIENT_TYPES: tuple[str, ...] = (CLIENT_DESIGNER, CLIENT_SERVER_AGENT, CLIENT_THICK,
                                 CLIENT_THIN)

#: Klient turining BAJARILUVCHI fayli.
#: ⚠️⚠️ `designer` BU RO'YXATDA YO'Q va bu ATAYLAB: Konfigurator ALOHIDA `.exe` EMAS, u
#:      semiz klientning (`1cv8.exe`) REJIMI. Shu bois pastda `DESIGNER_MODE_OF` bilan
#:      semiz klientga bog'lanadi. «1cv8d.exe» kabi fayl nomi O'YLAB CHIQARILMAYDI.
CLIENT_EXECUTABLES: dict[str, str] = {
    CLIENT_THICK: "1cv8.exe",
    CLIENT_THIN: "1cv8c.exe",
    CLIENT_SERVER_AGENT: "ragent.exe",
}

#: Konfigurator QAYSI bajariluvchining rejimi.
DESIGNER_MODE_OF = CLIENT_THICK

#: Konfigurator rejimining buyruq satri fe'li.
#: ⚠️⚠️ DEKLARATSIYA, QOBILIYAT EMAS: bu modul birorta buyruq QURMAYDI va bu fe'l bilan
#:      hech narsa ishga TUSHIRILMAYDI. U shu mashinada tekshirib bo'lmaydi (1C yo'q), shu
#:      bois `DESIGNER_VERIFICATION` bilan ochiq belgilanadi. Ishga tushiruvchi ham faqat
#:      `ENTERPRISE` fe'lini ishlatadi (u `collector_bridge` da ALLAQACHON bor va
#:      qulflangan) — Konfigurator rejimida hech narsa ochilmaydi, chunki razvedka uchun u
#:      KERAK EMAS va u bazani O'ZGARTIRISH huquqiga ega rejim.
DESIGNER_MODE_VERB = "DESIGNER"
DESIGNER_VERIFICATION = "UNVERIFIED_ON_REAL_1C"

#: `PATH` dan izlanadigan klient fayllari (UCHINCHI manba).
#: ⚠️ `PATH_EXECUTABLES` ga TEGILMAYDI: u `installs` ro'yxatini quradi va unga yangi fayl
#:    qo'shilsa topilgan o'rnatmalar soni O'ZGARARDI (ya'ni mavjud xulq buzilardi). Klient
#:    turlari esa ALOHIDA o'lchanadi va `installs` ni O'ZGARTIRMAYDI.
CLIENT_PATH_EXECUTABLES: tuple[str, ...] = (
    CLIENT_EXECUTABLES[CLIENT_THICK], CLIENT_EXECUTABLES[CLIENT_THIN],
    CLIENT_EXECUTABLES[CLIENT_SERVER_AGENT],
)

#: Versiya papkasi/kalit nomi: `8.3.24.1234`, `8.3.21`.
_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")

#: Yo'l ichidan versiyani ajratish (`...\1cv8\8.3.24.1234\bin\1cv8.exe`).
_VERSION_IN_PATH_RE = re.compile(r"[\\/](\d+(?:\.\d+){2,3})[\\/]")

#: `.v8i` bo'lim sarlavhasi.
_V8I_SECTION_RE = re.compile(r"^\[(?P<name>.*)\]\s*$")

#: `Connect=` satri ichidagi `Kalit="qiymat"` va `Kalit=qiymat` juftliklari.
_CONNECT_PAIR_RE = re.compile(r'([A-Za-z][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|([^;]*))')

#: ⚠️ Autentifikatsiya ISHORASI: `.v8i` da foydalanuvchi yoki parol yozilgan bo'lsa, bazaga
#:    kirish autentifikatsiya talab qiladi. QIYMATLARI O'QILMAYDI — faqat KALIT borligi.
_AUTH_HINT_KEYS = frozenset({"usr", "pwd", "dbuser", "dbpwd"})

#: `Connect=` dan FAQAT shu kalitlar olinadi. Qolgani (ayniqsa `Usr`/`Pwd`) hatto o'zgaruvchiga
#: ham yozilmaydi.
_LOCATOR_KEYS = frozenset({"file", "srvr", "ref"})

#: `.v8i` kodirovkalari: 1CEStart faylni UTF-8 (BOM bilan) yoki `cp1251` da yozadi.
_V8I_ENCODINGS = ("utf-8-sig", "cp1251")


# ── O'qish natijasi ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ReadResult:
    """Uch holatli o'qish natijasi.

    ⚠️ `absent` va `unreadable` ni BIR xil `None` bilan qaytarish — aynan shu modul
    oldini olishi kerak bo'lgan nuqson. Shu bois holat ALOHIDA maydonda.
    """

    status: str
    value: object | None = None
    detail: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.status == READ_OK

    @property
    def is_absent(self) -> bool:
        return self.status == READ_ABSENT

    @property
    def is_unreadable(self) -> bool:
        return self.status == READ_UNREADABLE


def ok(value: object) -> ReadResult:
    return ReadResult(READ_OK, value)


def absent(detail: str | None = None) -> ReadResult:
    return ReadResult(READ_ABSENT, None, detail)


def unreadable(detail: str) -> ReadResult:
    return ReadResult(READ_UNREADABLE, None, detail)


# ── Manba interfeyslari (testlar shularni almashtiradi) ─────────────────────────────────────
class RegistryReader(Protocol):
    """Reestrni FAQAT O'QIYDIGAN interfeys."""

    def subkeys(self, hive: str, key: str) -> ReadResult: ...

    def values(self, hive: str, key: str) -> ReadResult: ...

    def key_exists(self, hive: str, key: str) -> ReadResult: ...


class FileReader(Protocol):
    """Fayl tizimini FAQAT O'QIYDIGAN interfeys."""

    def listdir(self, path: str) -> ReadResult: ...

    def exists_file(self, path: str) -> ReadResult: ...

    def read_text(self, path: str) -> ReadResult: ...


class WinregRegistry:
    """Haqiqiy Windows reestri — `KEY_READ`, YOZISH YO'Q.

    ⚠️ `winreg` bo'lmasa (Windows emas) HAR BIR o'qish `unreadable` qaytaradi, `absent` EMAS:
    «bu platformada qaray olmadim» — «yo'q» degani emas.
    """

    _HIVE_NAMES = {HKLM: "HKEY_LOCAL_MACHINE", HKCU: "HKEY_CURRENT_USER",
                   HKCR: "HKEY_CLASSES_ROOT"}

    def _hive(self, hive: str):
        return getattr(_winreg, self._HIVE_NAMES[hive])

    def _open(self, hive: str, key: str):
        return _winreg.OpenKey(self._hive(hive), key, 0, _winreg.KEY_READ)

    @staticmethod
    def _no_winreg() -> ReadResult:
        return unreadable("winreg mavjud emas (Windows emas)")

    def subkeys(self, hive: str, key: str) -> ReadResult:
        if _winreg is None:
            return self._no_winreg()
        try:
            with self._open(hive, key) as handle:
                count = _winreg.QueryInfoKey(handle)[0]
                # ⚠️ Sanoq OLDIN olinadi: `EnumKey` ni `OSError` da jimgina to'xtatish
                #    huquq xatosini «ro'yxat tugadi» ga aylantirib, UNREADABLE ni ABSENT
                #    qilib ko'rsatardi.
                names = [_winreg.EnumKey(handle, i) for i in range(count)]
            return ok(names)
        except FileNotFoundError:
            return absent("reestr kaliti yo'q")
        except OSError as exc:
            return unreadable(f"reestr kaliti o'qilmadi: {type(exc).__name__}")

    def values(self, hive: str, key: str) -> ReadResult:
        if _winreg is None:
            return self._no_winreg()
        try:
            out: dict[str, str] = {}
            with self._open(hive, key) as handle:
                count = _winreg.QueryInfoKey(handle)[1]
                for i in range(count):
                    name, data, _vtype = _winreg.EnumValue(handle, i)
                    out[name] = data if isinstance(data, str) else ""
            return ok(out)
        except FileNotFoundError:
            return absent("reestr kaliti yo'q")
        except OSError as exc:
            return unreadable(f"reestr qiymatlari o'qilmadi: {type(exc).__name__}")

    def key_exists(self, hive: str, key: str) -> ReadResult:
        if _winreg is None:
            return self._no_winreg()
        try:
            with self._open(hive, key):
                pass
            return ok(True)
        except FileNotFoundError:
            return absent("reestr kaliti yo'q")
        except OSError as exc:
            return unreadable(f"reestr kaliti o'qilmadi: {type(exc).__name__}")


class RealFileReader:
    """Haqiqiy fayl tizimi — FAQAT O'QISH."""

    def listdir(self, path: str) -> ReadResult:
        try:
            return ok(sorted(os.listdir(path)))
        except FileNotFoundError:
            return absent("papka yo'q")
        except NotADirectoryError:
            return absent("papka emas")
        except OSError as exc:
            return unreadable(f"papka o'qilmadi: {type(exc).__name__}")

    def exists_file(self, path: str) -> ReadResult:
        try:
            return ok(os.path.isfile(path))
        except OSError as exc:  # pragma: no cover - kam uchraydigan I/O xatosi
            return unreadable(f"fayl tekshirilmadi: {type(exc).__name__}")

    def read_text(self, path: str) -> ReadResult:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return absent("fayl yo'q")
        except OSError as exc:
            return unreadable(f"fayl o'qilmadi: {type(exc).__name__}")
        for enc in _V8I_ENCODINGS:
            try:
                return ok(raw.decode(enc))
            except UnicodeDecodeError:
                continue
        # ⚠️ Oxirgi chora: istisno TASHLAMAYMIZ. Buzuq kodirovka «fayl yo'q» ga aylanmasligi
        #    kerak, lekin butun aniqlashni ham to'xtatmasligi kerak.
        return ok(raw.decode("utf-8", errors="replace"))


# ── Sozlama ─────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DetectorConfig:
    """Qayerga qaraladi. ⚠️ Testlar BUNI almashtiradi — haqiqiy reestr/papkalarga tegmaydi."""

    registry_install_keys: tuple[tuple[str, str, str], ...] = REGISTRY_INSTALL_KEYS
    com_class_ids: tuple[str, ...] = COM_CLASS_IDS
    #: `(yorliq, ildiz, bitlik)` — yorliq izohlarda ishlatiladi, XOM yo'l emas.
    filesystem_roots: tuple[tuple[str, str, str], ...] = ()
    path_executables: tuple[str, ...] = PATH_EXECUTABLES
    #: `(manba, yo'l)` — `ibases.v8i` fayllari, foydalanuvchi ro'yxati BIRINCHI.
    ibases_files: tuple[tuple[str, str], ...] = ()


def default_config() -> DetectorConfig:
    """Windows'ning odatiy joylari. ⚠️ `%ProgramFiles%` yo'q bo'lsa `C:\\Program Files` ga tushadi."""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    appdata = os.environ.get("APPDATA")
    allusers = os.environ.get("ALLUSERSPROFILE") or os.environ.get("ProgramData")

    roots: list[tuple[str, str, str]] = [
        ("program_files", os.path.join(pf, "1cv8"), "x64"),
        ("program_files_x86", os.path.join(pf86, "1cv8"), "x86"),
    ]
    ibases: list[tuple[str, str]] = []
    if appdata:
        ibases.append((SOURCE_IBASES_USER, os.path.join(appdata, "1C", "1CEStart", "ibases.v8i")))
    if allusers:
        ibases.append((SOURCE_IBASES_COMMON,
                       os.path.join(allusers, "1C", "1CEStart", "ibases.v8i")))
    return DetectorConfig(filesystem_roots=tuple(roots), ibases_files=tuple(ibases))


def _mask_path(path: str | None) -> str | None:
    """Mahalliy yo'lni TO'LIQ niqoblash — `redact` ning probel kamchiligini yopadi.

    ⚠️ `None` niqoblanmaydi: «yo'l noma'lum» va «yo'l niqoblangan» IKKI XIL ma'no, ularni
    birlashtirish yana UNKNOWN ni boshqa narsaga aylantirardi.
    """
    return _redact.MASK if path else path


# ── Natija tuzilmalari ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ClientBinary:
    """O'rnatmaning BITTA klient turi: qaysi fayl, qaysi bitlik, qaysi manbadan.

    ⚠️⚠️ `present` UCH HOLATLI EMAS, IKKI HOLATLI va bu ATAYLAB: `"true"` (fayl bor) yoki
         `"unknown"` (qaray olmadim). «Yo'q» holati YOZUV SIFATIDA umuman qaytarilmaydi —
         topilmagan klient ro'yxatga TUSHMAYDI va buning izi `notes` da qoladi. Ya'ni
         `UNKNOWN` hech qachon `NOT_FOUND` ga aylanmaydi: o'qilmagan fayl ro'yxatda
         `"unknown"` bo'lib KO'RINIB turadi, yo'qligi esa ro'yxatda YO'Qligi bilan
         bildiriladi. Ikkisini bitta `"false"` ga qo'shish aynan shu ajrimni yo'qotardi.
    ⚠️ `mode_verb` FAQAT Konfigurator uchun to'ladi va u DEKLARATSIYA: bu modul u bilan
       buyruq QURMAYDI (`DESIGNER_MODE_VERB` izohiga qarang).
    ⚠️ `path` NIQOBLANMAYDI, chunki bu yozuv `environment.json` ga TUSHMAYDI (pastdagi
       `Install.as_document` izohiga qarang): u xotirada qoladi va ishga tushiruvchi
       HAQIQIY yo'lga muhtoj.
    """

    client_type: str
    path: str
    bitness: str
    source: str
    present: str
    mode_verb: str | None = None


@dataclass(frozen=True)
class Install:
    """Topilgan 1C o'rnatmasi.

    ⚠️ `path` `None` bo'lishi MUMKIN: reestrda versiya kaliti bor, yo'l qiymati esa yo'q yoki
    o'qilmadi. Bunda yozuvni TASHLAB YUBORISH «o'rnatma bor» faktini yo'qotardi — ya'ni yana
    UNKNOWN ni NOT_FOUND ga aylantirardi.
    ⚠️ `version` ham `None` bo'lishi mumkin (`PATH` dagi exe, versiyasi yo'ldan bilinmaydi).
    """

    path: str | None
    version: str | None
    bitness: str
    source: str
    #: ⚠️ YANGI MAYDON, OXIRIDA va STANDART QIYMAT bilan: mavjud chaqiruvlar (va testlardagi
    #: `Install(path=..., version=..., bitness=..., source=...)`) O'ZGARMAYDI.
    clients: tuple[ClientBinary, ...] = ()

    def as_document(self) -> dict:
        # ⚠️ Yo'l TO'LIQ niqoblanadi: `redact` ning yo'l naqshi probelda to'xtaydi, 1C yo'li
        #    esa `C:\Program Files\...` — probelli (modul docstringiga qarang).
        # ⚠️⚠️ `clients` BU HUJJATGA ATAYLAB TUSHMAYDI (hozircha). Sabab Phase 4 darsi:
        #      `installs[]` ning kalitlari IKKI joyda qulflangan — `result_package.py`
        #      validatori (`set(inst) != {"path","version","bitness","source"}` -> nuqson)
        #      va `test_agent_detector.test_install_va_infobase_kalitlari_...`. Kalitni
        #      bugun qo'shsak to'plam yashil bo'lishi mumkin, lekin HAR BIR real natija
        #      paketi validatorda rad etilardi — aynan Phase 4 ni yiqitgan naqsh. Shu bois
        #      klient turlari XOTIRADA (`EnvironmentScan`) yashaydi, hujjatga esa
        #      `notes` orqali SO'Z bilan chiqadi. Validator yangilangach shu yerda bitta
        #      kalit qo'shiladi (`launcher.RESULT_PACKAGE_SOROVI` ga qarang).
        return {"path": _mask_path(self.path), "version": self.version,
                "bitness": self.bitness, "source": self.source}

    def client(self, client_type: str) -> ClientBinary | None:
        """Shu turdagi klient yozuvi (yo'q bo'lsa `None` — taxmin QILINMAYDI)."""
        for c in self.clients:
            if c.client_type == client_type:
                return c
        return None


@dataclass(frozen=True)
class Infobase:
    """`ibases.v8i` da e'lon qilingan infobaza. ⚠️ Kredensial maydoni ATAYLAB YO'Q."""

    kind: str
    locator: str
    name: str | None
    source: str
    requires_auth: str

    def as_document(self) -> dict:
        # ⚠️ FAYL bazasining `locator` i — mahalliy yo'l, TO'LIQ niqoblanadi. SERVER bazasining
        #    `locator` i esa `srvr/ref`: u yo'l emas, va uni niqoblash hisobotni ma'nosiz
        #    qilardi («qaysi bazani tanladim?»). Server manzili IP:port bo'lsa — `redact`
        #    uni o'zi niqoblaydi (`ip_with_port` naqshi), bu esa aynan shu holat uchun bor.
        locator = _mask_path(self.locator) if self.kind == KIND_FILE else self.locator
        return {"kind": self.kind, "locator": locator, "name": self.name,
                "source": self.source, "requires_auth": self.requires_auth}


@dataclass(frozen=True)
class Unreadable:
    """O'qilmagan manba — `agent_status.json` dagi `errors` ga shu ko'rinishda ko'chadi.

    ⚠️ `scope` va `detail` da XOM fayl yo'li BO'LMAYDI: yorliq (`program_files_x86`,
    `ibases_user`) ishlatiladi. Sababi — bu matnlar hisobotga chiqadi, chiqishni esa
    redaksiya `[REDACTED]` ga aylantirib, izohni ma'nosiz qilib qo'yardi.
    """

    scope: str
    code: str
    detail: str

    def as_error(self) -> dict:
        return {"scope": self.scope, "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EnvironmentScan:
    """`ENVIRONMENT_SCAN` natijasi — XOM (redaksiyalanmagan) ko'rinish.

    Agent `batch_execute` yo'li uchun shu obyektdan `newest_install().path` ni oladi.
    Diskka esa FAQAT `to_document()` yoziladi.
    """

    scanned_at: str
    os_version: str | None
    installs: tuple[Install, ...]
    com_registered: str
    infobases: tuple[Infobase, ...]
    notes: tuple[str, ...]
    unreadables: tuple[Unreadable, ...]
    selected: str | None = None
    #: `PATH` dan topilgan klient fayllari — o'rnatmaga BOG'LANMAGAN.
    #: ⚠️⚠️ NEGA ALOHIDA: `PATH` dagi `1cv8c.exe` QAYSI o'rnatmaga tegishli ekani yo'ldan
    #:      bilinmasligi mumkin (versiya papkasi bo'lmasa). Uni «eng yangi o'rnatmaning
    #:      klienti» deb yozish TAXMIN bo'lardi, taxmin esa aynan shu moduldan taqiqlangan.
    #:      Shu bois u mustaqil ro'yxat: dalil bor, egasi esa noma'lum deb QOLADI.
    path_clients: tuple[ClientBinary, ...] = ()

    # ── Xulosalar ───────────────────────────────────────────────────────────────────────────
    @property
    def presence_verdict(self) -> str:
        """`found` | `absent` | `unknown` — ⚠️ `FAILED_NO_1C` FAQAT `absent` da haqli."""
        if self.installs:
            return PRESENCE_FOUND
        if any(u.code in _PRESENCE_CODES for u in self.unreadables):
            return PRESENCE_UNKNOWN
        return PRESENCE_ABSENT

    @property
    def is_absent_proven(self) -> bool:
        """1C yo'qligi ISBOTLANDIMI (hamma manba o'qildi va bo'sh chiqdi)."""
        return self.presence_verdict == PRESENCE_ABSENT

    def ranked_installs(self) -> tuple[Install, ...]:
        """O'rnatmalar ENG YANGISI BIRINCHI tartibda (`rank_installs` ga qarang)."""
        return rank_installs(self.installs)

    def newest_install(self) -> Install | None:
        """Versiyasi ENG YANGI o'rnatma (`installs` o'sish tartibida, oxirgisi eng yangi).

        ⚠️ Versiyasi noma'lum yozuvlar oxirida turadi, shu bois ular faqat BOSHQA tanlov
        bo'lmaganda qaytadi.
        """
        known = [i for i in self.installs if i.version]
        if known:
            return known[-1]
        return self.installs[-1] if self.installs else None

    def with_selection(self, locator: str | None) -> EnvironmentScan:
        """Nishon tanlangandan keyingi YANGI nusxa.

        ⚠️ Aniqlovchi O'ZI tanlamaydi: tanlov `TARGET_SELECTION` holatining ishi va u
        operator tasdig'iga bog'liq bo'lishi mumkin. Shu bois `selected` doim `None` bilan
        tug'iladi.
        """
        return replace(self, selected=locator)

    # ── Chiqish ─────────────────────────────────────────────────────────────────────────────
    def to_document(self) -> dict:
        """`binos-agent-env-v1` hujjati — NIQOBLANGAN. Kalitlar brief tartibida.

        ⚠️⚠️ TUZATILGAN NUQSON: `presence_verdict` avval FAQAT `agent_status.json` da bor edi,
             ya'ni MUHIT HUJJATINING O'ZI mashina o'qiydigan hukmni OLIB YURMASDI. Operator
             (va skript) `environment.json` ni ochib `installs: []` ni ko'rsa, «qaradim va
             TOPILMADI» (`absent`) bilan «qaray OLMADIM» (`unknown`) ni AJRATA olmasdi —
             ajrim esa boshqa faylda qolardi. Hukm shu yerga QO'SHILDI, demak:
               · ikki hujjat ZID bo'lishi uchun endi ikkisini ALOHIDA buzish kerak;
               · hukm O'Z DALILI (`installs`, `notes`) bilan BIR faylda turadi.
        ⚠️ Lug'at YANGI EMAS — `PRESENCE_FOUND`/`PRESENCE_ABSENT`/`PRESENCE_UNKNOWN`, ya'ni
           `agent_status.presence_verdict` BILAN AYNI uchta qiymat (`status.PRESENCE_VERDICTS`
           ham shu konstantalardan quriladi). Ikkinchi lug'at O'YLAB CHIQARILMADI.
        ⚠️ Kalit `installs` dan KEYIN turadi: hukm aynan shu ro'yxatdan (va o'qilmagan
           manbalardan) CHIQARILADI, shu bois dalilning yonida o'qilishi kerak.
        """
        doc = {
            "env_version": ENV_VERSION,
            "scanned_at": self.scanned_at,
            "os_version": self.os_version,
            "installs": [i.as_document() for i in self.installs],
            "presence_verdict": self.presence_verdict,
            "com_registered": self.com_registered,
            "infobases": [b.as_document() for b in self.infobases],
            "selected": self.selected,
            "notes": list(self.notes),
        }
        # ⚠️ IKKINCHI QATLAM. Yo'l maydonlari allaqachon `_mask_path` bilan to'liq niqoblangan
        #    (`redact` yo'l naqshi probelda to'xtaydi — docstringga qarang); bu chaqiruv esa
        #    QOLGAN hamma joyni (izohlar, baza nomlari, server manzili) tekshiradi, shu bois
        #    keyin qo'shilgan maydon ham nazoratsiz qolmaydi. `redact` nusxa qaytaradi.
        return _redact.redact(doc)

    def errors(self) -> list[dict]:
        """`agent_status.json` ning `errors` ro'yxatiga tayyor yozuvlar."""
        return [u.as_error() for u in self.unreadables]


def dump_document(scan: EnvironmentScan) -> str:
    """Hujjatning DETERMINISTIK bayt ko'rinishi (bir xil kirish -> bir xil bayt)."""
    return json.dumps(scan.to_document(), ensure_ascii=False, indent=2,
                      sort_keys=False) + "\n"


# ── Yordamchilar ────────────────────────────────────────────────────────────────────────────
def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _os_version() -> str | None:
    try:
        return platform.platform()
    except Exception:  # pragma: no cover - platform juda kam yiqiladi
        return None


def _norm_path(path: str) -> str:
    """Dedup kaliti — platformadan MUSTAQIL.

    ⚠️ `os.path.normcase` ishlatilmaydi: u Linux'da registrni saqlab qoladi, natijada AYNI
    fikstura Windows va CI'da BOSHQA natija berardi (determinizm buzilardi).
    """
    return path.replace("/", "\\").rstrip("\\").casefold()


def _version_key(version: str | None) -> tuple:
    """Tartiblash kaliti: versiyasi bor yozuvlar OLDIN, o'sish tartibida."""
    if not version:
        return (1, ())
    parts = tuple(int(p) for p in version.split(".") if p.isdigit())
    return (0, parts)


def _desc_version_key(version: str | None) -> tuple:
    """`rank_installs` uchun kalit: KATTA qiymat = YANGI versiya.

    ⚠️ Versiyasi NOMA'LUM yozuv eng past darajada (`(0, ())`), ya'ni kamayish tartibida
       ro'yxatning OXIRIDA qoladi: «noma'lum» hech qachon «eng yangi» deb KO'RSATILMAYDI.
    ⚠️ `_version_key` ga TEGILMAYDI: u o'sish tartibi uchun yozilgan va `installs` ning
       mavjud tartibini (hamda `newest_install`ni) belgilaydi — uni «umumiylashtirish»
       mavjud xulqni jimgina o'zgartirardi.
    """
    if not version:
        return (0, ())
    return (1, tuple(int(p) for p in version.split(".") if p.isdigit()))


def rank_installs(installs) -> tuple[Install, ...]:
    """O'rnatmalarni DETERMINISTIK tartiblaydi: ENG YANGISI BIRINCHI.

    Tartib kaliti ikki qatlamli va TO'LIQ aniq:
      1. versiya KAMAYISH tartibida (noma'lum versiya — oxirida);
      2. versiya TENG bo'lsa — niqoblanmagan yo'l bo'yicha O'SISH tartibida, undan keyin
         manba ishonchliligi bo'yicha (`registry` > `filesystem` > `path`).

    ⚠️⚠️ NEGA IKKINCHI QATLAM SHART: faqat versiya bo'yicha tartiblash bir xil versiyali
         ikki yozuvni `sorted` ning kirish tartibiga qoldirardi, kirish tartibi esa
         reestr/fayl tizimi o'qilish tartibiga bog'liq — ya'ni AYNI mashinada ham javob
         o'zgarib turardi va ishga tushiruvchi bir kun boshqa `.exe` ni ochardi.
    ⚠️ Barqarorlik: avval yo'l/manba bo'yicha, KEYIN versiya bo'yicha (Python saralashi
       barqaror) — natijada teng versiyalarning ichki tartibi ham aniq.
    ⚠️ `newest_install()` TEGILMAYDI (u mavjud xulq va testlar bilan qulflangan). Ikkisi
       versiyalar FARQ qilganda AYNI yozuvni ko'rsatadi; versiya TENG bo'lgan holatda esa
       ular turli yozuvni tanlashi mumkin, shu bois ishga tushiruvchi FAQAT bittasini
       (`rank_installs`) ishlatadi va tanlovini yozib qo'yadi — ikki «eng yangi» javobi
       bir hujjatda uchrashmaydi.
    """
    oldin = sorted(installs, key=lambda i: (_norm_path(i.path or ""),
                                            _SOURCE_RANK[i.source]))
    return tuple(sorted(oldin, key=lambda i: _desc_version_key(i.version), reverse=True))


def _bitness(path: str | None, hint: str) -> str:
    """Bitlik: yo'ldagi `(x86)` eng ishonchli dalil, aks holda manba ishorasi."""
    if path and "(x86)" in path.casefold():
        return "x86"
    return hint


def _version_from_path(path: str | None) -> str | None:
    if not path:
        return None
    match = _VERSION_IN_PATH_RE.search(path.replace("/", "\\"))
    return match.group(1) if match else None


def _exe_from_registry_value(value: str) -> str:
    """Reestr qiymatidan `1cv8.exe` yo'li. Qiymat exe bo'lsa — o'zi, papka bo'lsa — `bin\\1cv8.exe`."""
    cleaned = value.strip().strip('"')
    if cleaned.casefold().endswith(".exe"):
        return cleaned
    cleaned = cleaned.rstrip("\\/")
    if cleaned.casefold().endswith("\\bin") or cleaned.casefold().endswith("/bin"):
        return os.path.join(cleaned, "1cv8.exe")
    return os.path.join(cleaned, "bin", "1cv8.exe")


# ── 1. Reestr ───────────────────────────────────────────────────────────────────────────────
def _scan_registry(reg: RegistryReader, config: DetectorConfig,
                   notes: list[str], unreadables: list[Unreadable]) -> list[Install]:
    found: list[Install] = []
    for hive, key, hint in config.registry_install_keys:
        scope = f"registry:{hive}\\{key}"
        res = reg.subkeys(hive, key)
        if res.is_unreadable:
            unreadables.append(Unreadable(scope, CODE_REGISTRY_UNREADABLE,
                                          res.detail or "o'qilmadi"))
            notes.append(f"{scope}: O'QILMADI — «1C yo'q» DEGANI EMAS ({res.detail})")
            continue
        if res.is_absent:
            notes.append(f"{scope}: kalit yo'q")
            continue
        versions = [str(name) for name in (res.value or []) if _VERSION_RE.match(str(name))]
        if not versions:
            notes.append(f"{scope}: kalit bor, versiya kichik kaliti yo'q")
        for version in sorted(versions, key=_version_key):
            sub = f"{key}\\{version}"
            vals = reg.values(hive, sub)
            if vals.is_unreadable:
                unreadables.append(Unreadable(f"registry:{hive}\\{sub}",
                                              CODE_REGISTRY_UNREADABLE,
                                              vals.detail or "o'qilmadi"))
                # ⚠️ Versiya MA'LUM, yo'l esa yo'q: yozuv `path=None` bilan QOLADI.
                notes.append(f"registry:{hive}\\{sub}: qiymatlari o'qilmadi, yo'l noma'lum")
                found.append(Install(None, version, _bitness(None, hint), SOURCE_REGISTRY))
                continue
            data = vals.value if isinstance(vals.value, dict) else {}
            raw = next((str(data[name]) for name in _REGISTRY_PATH_VALUE_NAMES
                        if data.get(name)), None)
            path = _exe_from_registry_value(raw) if raw else None
            if path is None:
                notes.append(f"registry:{hive}\\{sub}: yo'l qiymati yo'q, yo'l noma'lum")
            found.append(Install(path, version, _bitness(path, hint), SOURCE_REGISTRY))
    return found


# ── 2. Fayl tizimi ──────────────────────────────────────────────────────────────────────────
def _scan_filesystem(files: FileReader, config: DetectorConfig,
                     notes: list[str], unreadables: list[Unreadable]) -> list[Install]:
    found: list[Install] = []
    for label, root, hint in config.filesystem_roots:
        scope = f"filesystem:{label}"
        res = files.listdir(root)
        if res.is_unreadable:
            unreadables.append(Unreadable(scope, CODE_FILESYSTEM_UNREADABLE,
                                          res.detail or "o'qilmadi"))
            notes.append(f"{scope}: O'QILMADI — «1C yo'q» DEGANI EMAS ({res.detail})")
            continue
        if res.is_absent:
            notes.append(f"{scope}: papka yo'q")
            continue
        names = [str(n) for n in (res.value or []) if _VERSION_RE.match(str(n))]
        for version in sorted(names, key=_version_key):
            exe = os.path.join(root, version, "bin", "1cv8.exe")
            chk = files.exists_file(exe)
            if chk.is_unreadable:
                unreadables.append(Unreadable(f"{scope}/{version}",
                                              CODE_FILESYSTEM_UNREADABLE,
                                              chk.detail or "o'qilmadi"))
                continue
            if chk.value is True:
                found.append(Install(exe, version, _bitness(exe, hint), SOURCE_FILESYSTEM))
            else:
                notes.append(f"{scope}/{version}: versiya papkasi bor, 1cv8.exe yo'q")
    return found


# ── 3. PATH ─────────────────────────────────────────────────────────────────────────────────
def _scan_path(which: Callable[[str], str | None], config: DetectorConfig,
               notes: list[str], unreadables: list[Unreadable]) -> list[Install]:
    found: list[Install] = []
    for exe_name in config.path_executables:
        try:
            hit = which(exe_name)
        except OSError as exc:
            unreadables.append(Unreadable(f"path:{exe_name}", CODE_PATH_UNREADABLE,
                                          f"PATH tekshirilmadi: {type(exc).__name__}"))
            continue
        if not hit:
            continue
        version = _version_from_path(hit)
        if version is None:
            notes.append(f"path:{exe_name}: topildi, versiya yo'ldan bilinmadi")
        found.append(Install(hit, version, _bitness(hit, TRI_UNKNOWN), SOURCE_PATH))
    return found


# ── 3b. KLIENT TURLARI (reestr yo'li + fayl tizimi + PATH) ──────────────────────────────────
#: Fayl nomidan klient turiga (kichik harfga keltirilgan kalit bilan).
_CLIENT_BY_EXECUTABLE: dict[str, str] = {
    nom.casefold(): tur for tur, nom in CLIENT_EXECUTABLES.items()
}


def _client_probe(files: FileReader, path: str, client_type: str, source: str,
                  bitness: str, scope: str, notes: list[str],
                  unreadables: list[Unreadable]) -> ClientBinary | None:
    """Bitta klient faylini FAYL TIZIMIDA tekshiradi (uch holatli javob bilan).

    ⚠️ `unreadable` -> yozuv `present="unknown"` bo'lib QOLADI (tashlab ketilmaydi):
       «qaray olmadim» — «yo'q» degani emas.
    ⚠️ `absent` -> yozuv YO'Q, lekin izoh qoladi: ro'yxatda yo'qligi «topilmadi» degani.
    """
    chk = files.exists_file(path)
    if chk.is_unreadable:
        unreadables.append(Unreadable(scope, CODE_FILESYSTEM_UNREADABLE,
                                      chk.detail or "o'qilmadi"))
        notes.append(f"{scope}: {client_type} TEKSHIRILMADI — «yo'q» DEGANI EMAS "
                     f"({chk.detail})")
        return ClientBinary(client_type, path, bitness, source, TRI_UNKNOWN)
    if chk.value is True:
        return ClientBinary(client_type, path, bitness, source, TRI_TRUE)
    notes.append(f"{scope}: {client_type} topilmadi")
    return None


def _install_clients(install: Install, files: FileReader, notes: list[str],
                     unreadables: list[Unreadable]) -> tuple[ClientBinary, ...]:
    """O'rnatmaning klient turlari: semiz, yupqa, Konfigurator (rejim), server agenti.

    ⚠️⚠️ SEMIZ KLIENT HAM TEKSHIRILADI, hatto yo'l REESTRDAN kelgan bo'lsa ham: reestrda
         yozuv qolib, fayl o'chirilgan bo'lishi mumkin (1C olib tashlangan, papka
         ko'chirilgan). Reestr yozuvini «fayl bor» deb o'qish ISBOTLANMAGAN da'vo bo'lardi
         va ishga tushiruvchi mavjud bo'lmagan `.exe` ni ochmoqchi bo'lardi.
    ⚠️⚠️ KONFIGURATOR ALOHIDA FAYL EMAS: u semiz klientning REJIMI, shu bois uning yozuvi
         semiz klient yozuvidan KELTIRIB CHIQARILADI (ayni yo'l, ayni `present`) va
         `mode_verb` bilan belgilanadi. Semiz klient topilmasa — Konfigurator yozuvi ham
         YO'Q: «rejim bor, fayl yo'q» degan holat mantiqsiz.
    ⚠️ Yupqa klient va server agenti AYNI `bin` papkasida qaraladi — ya'ni standart yo'lga
       TAYANMAYDI: papka o'rnatmaning O'Z yo'lidan (reestr yoki fayl tizimidan) olinadi.
    """
    scope = f"clients:{install.source}:{install.version or TRI_UNKNOWN}"
    if not install.path:
        notes.append(f"{scope}: o'rnatma yo'li NOMA'LUM — klient turlari fayl tizimidan "
                     f"tekshirilmadi (PATH bo'yicha alohida qaraladi)")
        return ()
    out: list[ClientBinary] = []
    semiz = _client_probe(files, install.path, CLIENT_THICK, install.source,
                          install.bitness, scope, notes, unreadables)
    if semiz is not None:
        out.append(semiz)
        out.append(ClientBinary(CLIENT_DESIGNER, semiz.path, semiz.bitness, semiz.source,
                                semiz.present, DESIGNER_MODE_VERB))
    else:
        notes.append(f"{scope}: {CLIENT_DESIGNER} yozuvi ham yo'q — u semiz klientning "
                     f"REJIMI, mustaqil fayli YO'Q")
    papka = os.path.dirname(install.path)
    for tur in (CLIENT_THIN, CLIENT_SERVER_AGENT):
        yozuv = _client_probe(files, os.path.join(papka, CLIENT_EXECUTABLES[tur]), tur,
                              SOURCE_FILESYSTEM, install.bitness, scope, notes, unreadables)
        if yozuv is not None:
            out.append(yozuv)
    # ⚠️ TARTIB DETERMINISTIK: tur nomi bo'yicha, keyin yo'l bo'yicha. Kirish tartibi
    #    fayl tizimi javobiga bog'liq bo'lib qolmasin.
    out.sort(key=lambda c: (c.client_type, _norm_path(c.path)))
    if out:
        notes.append(f"{scope}: klient turlari — "
                     f"{', '.join(f'{c.client_type}={c.present}' for c in out)}")
    return tuple(out)


def _scan_path_clients(which: Callable[[str], str | None], notes: list[str],
                       unreadables: list[Unreadable]) -> tuple[ClientBinary, ...]:
    """`PATH` dagi klient fayllari — UCHINCHI manba, o'rnatmaga BOG'LANMAGAN.

    ⚠️ Topilgan fayl qaysi o'rnatmaga tegishli ekani yo'ldan bilinmasligi mumkin, shu bois
       u eng yangi o'rnatmaga BOG'LANMAYDI (bu taxmin bo'lardi) va mustaqil ro'yxatda
       qoladi.
    """
    out: list[ClientBinary] = []
    for exe_name in CLIENT_PATH_EXECUTABLES:
        try:
            topilgan = which(exe_name)
        except OSError as exc:
            unreadables.append(Unreadable(f"clients:path:{exe_name}", CODE_PATH_UNREADABLE,
                                          f"PATH tekshirilmadi: {type(exc).__name__}"))
            notes.append(f"clients:path:{exe_name}: PATH TEKSHIRILMADI — «yo'q» DEGANI EMAS")
            continue
        if not topilgan:
            continue
        tur = _CLIENT_BY_EXECUTABLE[exe_name.casefold()]
        bit = _bitness(topilgan, TRI_UNKNOWN)
        out.append(ClientBinary(tur, topilgan, bit, SOURCE_PATH, TRI_TRUE))
        if tur == DESIGNER_MODE_OF:
            out.append(ClientBinary(CLIENT_DESIGNER, topilgan, bit, SOURCE_PATH, TRI_TRUE,
                                    DESIGNER_MODE_VERB))
        notes.append(f"clients:path:{exe_name}: topildi ({tur})")
    out.sort(key=lambda c: (c.client_type, _norm_path(c.path)))
    return tuple(out)


# ── 4. COM ──────────────────────────────────────────────────────────────────────────────────
def _scan_com(reg: RegistryReader, config: DetectorConfig,
              notes: list[str], unreadables: list[Unreadable]) -> str:
    """COM klassi ro'yxatdanmi — uchlik MATN.

    ⚠️ BU MASHINADA COM yo'lini SINAB BO'LMAYDI (klasslar ro'yxatda yo'q, `pywin32` ham yo'q).
    Shu bois natija FAQAT matritsa uchun baho: `"true"` ham «ishlaydi» degani emas, u
    `RUNTIME-UNKNOWN` bo'lib qoladi.
    ⚠️ Birorta klass o'qilmasa va birortasi ham topilmasa — `"unknown"`, `"false"` EMAS.
    """
    any_unreadable = False
    for cls in config.com_class_ids:
        for hive, template in _COM_KEY_TEMPLATES:
            key = template.format(cls=cls)
            res = reg.key_exists(hive, key)
            if res.is_ok:
                notes.append(f"com:{cls}: reestrda bor ({hive}) — ishlashi RUNTIME-UNKNOWN")
                return TRI_TRUE
            if res.is_unreadable:
                any_unreadable = True
                unreadables.append(Unreadable(f"com:{hive}\\{key}", CODE_COM_UNREADABLE,
                                              res.detail or "o'qilmadi"))
    if any_unreadable:
        notes.append("com: reestr o'qilmadi — klass bor-yo'qligi NOMA'LUM")
        return TRI_UNKNOWN
    notes.append("com: klasslarning birortasi ham ro'yxatda yo'q")
    return TRI_FALSE


# ── 5. Infobaza ro'yxati ────────────────────────────────────────────────────────────────────
def _parse_connect(connect: str) -> tuple[str | None, str | None, str]:
    """`Connect=` satridan (kind, locator, requires_auth).

    ⚠️ FAQAT `File`/`Srvr`/`Ref` o'qiladi. `Usr`/`Pwd` ning QIYMATI hech qaerga yozilmaydi —
    faqat KALIT borligi `requires_auth` ga ta'sir qiladi.
    ⚠️ `requires_auth` HECH QACHON `"false"` bo'lmaydi: parolsiz kirishni ULANMASDAN
    isbotlab bo'lmaydi, fail-closed esa `"unknown"` tomonda turadi.
    """
    locator_parts: dict[str, str] = {}
    auth_hint = False
    for match in _CONNECT_PAIR_RE.finditer(connect):
        key = match.group(1).casefold()
        if key in _AUTH_HINT_KEYS:
            auth_hint = True
            continue
        if key in _LOCATOR_KEYS:
            locator_parts[key] = (match.group(2) if match.group(2) is not None
                                  else (match.group(3) or "")).strip()
    requires_auth = TRI_TRUE if auth_hint else TRI_UNKNOWN
    if locator_parts.get("file"):
        return KIND_FILE, locator_parts["file"], requires_auth
    if locator_parts.get("srvr"):
        ref = locator_parts.get("ref") or ""
        locator = f"{locator_parts['srvr']}/{ref}" if ref else locator_parts["srvr"]
        return KIND_SERVER, locator, requires_auth
    return None, None, requires_auth


def _scan_ibases(files: FileReader, config: DetectorConfig,
                 notes: list[str], unreadables: list[Unreadable]) -> list[Infobase]:
    found: list[Infobase] = []
    seen: set[str] = set()
    for source, path in config.ibases_files:
        scope = f"ibases:{source}"
        res = files.read_text(path)
        if res.is_unreadable:
            unreadables.append(Unreadable(scope, CODE_IBASES_UNREADABLE,
                                          res.detail or "o'qilmadi"))
            notes.append(f"{scope}: O'QILMADI ({res.detail})")
            continue
        if res.is_absent:
            notes.append(f"{scope}: ibases.v8i yo'q")
            continue
        text = res.value if isinstance(res.value, str) else ""
        if not text.strip():
            notes.append(f"{scope}: ibases.v8i BO'SH")
            continue
        entries, parse_notes = _parse_v8i(text, scope)
        notes.extend(parse_notes)
        if not entries:
            notes.append(f"{scope}: bo'lim topilmadi — fayl shakli tanilmadi (buzuq bo'lishi mumkin)")
        for name, connect in entries:
            kind, locator, requires_auth = _parse_connect(connect)
            if not kind or not locator:
                notes.append(f"{scope}: «{name or '?'}» bo'limida tanilgan Connect yo'q")
                continue
            dedup = f"{kind}|{_norm_path(locator)}"
            if dedup in seen:
                notes.append(f"{scope}: «{name or '?'}» takrorlangan infobaza — tashlab ketildi")
                continue
            seen.add(dedup)
            found.append(Infobase(kind, locator, name or None, source, requires_auth))
    return found


def _parse_v8i(text: str, scope: str) -> tuple[list[tuple[str, str]], list[str]]:
    """`.v8i` — INI ko'rinishidagi matn. Istisno TASHLAMAYDI, buzuq joyni IZOHGA yozadi."""
    entries: list[tuple[str, str]] = []
    parse_notes: list[str] = []
    current: str | None = None
    connect: str | None = None
    orphan = False

    def close() -> None:
        if current is not None:
            entries.append((current, connect or ""))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        header = _V8I_SECTION_RE.match(line)
        if header:
            close()
            current = header.group("name").strip()
            connect = None
            if not current:
                parse_notes.append(f"{scope}: nomsiz bo'lim sarlavhasi")
            continue
        if "=" not in line:
            parse_notes.append(f"{scope}: «=» yo'q satr tashlab ketildi")
            continue
        key, _sep, value = line.partition("=")
        if current is None:
            orphan = True
            continue
        if key.strip().casefold() == "connect":
            connect = value.strip()
    close()
    if orphan:
        parse_notes.append(f"{scope}: bo'limdan TASHQARI kalitlar bor — fayl shakli buzuq")
    return entries, parse_notes


# ── Dedup ───────────────────────────────────────────────────────────────────────────────────
def _dedupe(installs: list[Install], notes: list[str]) -> tuple[Install, ...]:
    """Bir xil exe yo'li bir necha manbadan kelsa — ENG ISHONCHLI manba qoladi.

    ⚠️ Yo'li noma'lum (`None`) yozuvlar `(manba, versiya)` bo'yicha birlashtiriladi: ularni
    yo'l bo'yicha solishtirib bo'lmaydi, hammasini birlashtirish esa haqiqiy ikki o'rnatmani
    bittaga aylantirardi.
    """
    best: dict[str, Install] = {}
    for item in installs:
        key = (f"p|{_norm_path(item.path)}" if item.path
               else f"v|{item.source}|{item.version or ''}")
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        if _SOURCE_RANK[item.source] < _SOURCE_RANK[current.source]:
            best[key] = item
        notes.append(f"o'rnatma takrorlandi ({item.source} va {current.source}) — "
                     f"ishonchlisi qoldirildi")
    return tuple(sorted(best.values(),
                        key=lambda i: (_version_key(i.version), _norm_path(i.path or ""),
                                       _SOURCE_RANK[i.source])))


# ── Asosiy kirish nuqtasi ───────────────────────────────────────────────────────────────────
def scan_environment(
    *,
    config: DetectorConfig | None = None,
    registry: RegistryReader | None = None,
    files: FileReader | None = None,
    which: Callable[[str], str | None] | None = None,
    now: Callable[[], str] | None = None,
    os_version: Callable[[], str | None] | None = None,
) -> EnvironmentScan:
    """Muhitni aniqlaydi. ⚠️ Hech narsa YOZMAYDI, hech qaerga ULANMAYDI.

    Hamma manba ALMASHTIRILADIGAN (testlar sintetik fikstura beradi) — shu bois testlar
    HAQIQIY reestrni va haqiqiy papkalarni O'QIMAYDI va boshqa mashinada ham bir xil yuradi.
    """
    cfg = config if config is not None else default_config()
    reg: RegistryReader = registry if registry is not None else WinregRegistry()
    fsr: FileReader = files if files is not None else RealFileReader()
    which_fn = which if which is not None else shutil.which
    clock = now if now is not None else _utc_now
    osver = os_version if os_version is not None else _os_version

    notes: list[str] = [RUNTIME_UNKNOWN_NOTE]
    unreadables: list[Unreadable] = []

    installs = _scan_registry(reg, cfg, notes, unreadables)
    installs += _scan_filesystem(fsr, cfg, notes, unreadables)
    installs += _scan_path(which_fn, cfg, notes, unreadables)
    com = _scan_com(reg, cfg, notes, unreadables)
    infobases = _scan_ibases(fsr, cfg, notes, unreadables)

    deduped = _dedupe(installs, notes)
    # ⚠️ KLIENT TURLARI DEDUPDAN KEYIN: takrorlangan yozuv tashlab ketilgandan so'ng har
    #    o'rnatma uchun fayl tizimi BIR MARTA so'roq qilinadi (ikki marta so'rash ikki xil
    #    javob berishi mumkin bo'lgan yagona joy — I/O — shu bois u kamaytiriladi).
    deduped = tuple(replace(i, clients=_install_clients(i, fsr, notes, unreadables))
                    for i in deduped)
    path_clients = _scan_path_clients(which_fn, notes, unreadables)
    if not deduped:
        # ⚠️ ENG MUHIM AJRIM shu yerda MATNGA ham chiqadi: hisobotni o'qigan odam
        #    «topilmadi» va «ko'rolmadim» ni ADASHTIRMASLIGI kerak.
        if any(u.code in _PRESENCE_CODES for u in unreadables):
            notes.append("XULOSA: o'rnatma topilmadi, LEKIN manbalardan biri O'QILMADI — "
                         "«1C yo'q» xulosasi HAQLI EMAS (unknown)")
        else:
            notes.append("XULOSA: hamma manba o'qildi va bo'sh chiqdi — 1C o'rnatilmagan (absent)")

    return EnvironmentScan(
        scanned_at=clock(),
        os_version=osver(),
        installs=deduped,
        com_registered=com,
        infobases=tuple(infobases),
        notes=tuple(notes),
        unreadables=tuple(unreadables),
        path_clients=path_clients,
    )
