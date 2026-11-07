# -*- coding: utf-8 -*-
"""RELIZ IDENTITETI — ARTEFAKTNING O'ZIDAN, PLATFORMADAN EMAS.

MUAMMO (jonli o'lchandi 2026-11-06/07)
──────────────────────────────────────
`health.build_info()` commit SHA'ni FAQAT muhit o'zgaruvchilaridan olardi.
Nazoratli tajriba ko'rsatdi: Railway git o'zgaruvchilarini `deploy`/
`redeploy` da BERADI, `rollback` da BERMAYDI —

    binos-demo-api   reason=deploy     -> build.commit = ab758d17…  BOR
    savdoos          reason=rollback   -> build.commit = null       YO'Q

Natijada production AYNAN kutilgan relizga (`6ef666bb`) qaytarilgan bo'lsa
ham ilova O'Z commitini AYTA OLMADI, demo worker'ning SHA darvozasi yolg'on
yiqildi va demo do'kon 22,8 soat muzladi.

⚠️  MUHIT O'ZGARUVCHISI IDENTITET UCHUN YAROQSIZ: u artefaktdan TASHQARIDA
    yashaydi. Rollback kodni qaytaradi, o'zgaruvchini esa yo'qotadi yoki
    (battari) ESKI qiymat bilan qoldiradi — unda server YOLG'ON commit
    aytadi. `build_info()` docstringi aynan shuni ogohlantiradi:
    «yolg'on commit ko'rsatgandan ko'ra «bilmayman» degan afzal».

TO'RT XIL IDENTITET — ATAYLAB AJRATILGAN
────────────────────────────────────────
Topshiriq §2 aniq talab qiladi; ularni aralashtirish Phase A da haqiqiy
xato keltirgan («bir xil API sirti -> bir xil kod» degan noto'g'ri xulosa).

| identitet          | kim biladi            | bu modul |
|--------------------|-----------------------|----------|
| `git_commit`       | faqat MUHRLASH vaqti  | muhrdan O'QIYDI (da'vo) |
| `source_digest`    | ARTEFAKTNING O'ZI     | HAR SAFAR HISOBLAYDI |
| `image_digest`     | platforma (Railway)   | ilovaga KO'RINMAYDI |
| `deployment_id`    | platforma (env)       | o'zgaruvchidan o'qiydi |

`source_digest` — yagona qiymat: u KOD bilan birga ko'chadi, shu bois
rollback uni YO'QOTA OLMAYDI va redeploy O'ZGARTIRMAYDI.

⚠️  `source_digest` != `git_commit`. Ikki xil commit AYNI manba daraxtini
    berishi mumkin (masalan faqat hujjat o'zgargan commit). Digest MANBA
    DARAXTINI aniqlaydi, COMMITNI emas. Teskarisi ham: muhr commitni
    DA'VO qiladi, ISBOTLAMAYDI.

⚠️  `source_digest` != API BARMOQ IZI. O'lchangan dalil: 192 marshrutli
    sirt `6ef666bb`, uning otasi `3f76b62e` va `2457b98a` uchun AYNAN bir
    xil. Ya'ni bir xil qobiliyat manifesti bir xil kodni ISBOTLAMAYDI —
    `release.fingerprint()` o'zgarish DETEKTORI, identitet isboti EMAS.

O'ZINI TEKSHIRADIGAN MUHR
─────────────────────────
Muhr (`app/_build_info.py`) o'zidan BOSHQA hamma manba faylining
digestini saqlaydi. Runtime o'sha digestni QAYTA hisoblab solishtiradi:

  * mos      -> muhr kod bilan IZCHIL; `commit` e'lon qilinadi;
  * mos emas -> artefakt muhrlangandan KEYIN o'zgartirilgan; `commit`
                E'LON QILINMAYDI (fail-closed) va sabab aytiladi;
  * muhr yo'q -> `commit=None`, lekin `source_digest` HAMON beriladi.

HALOL CHEKLOVLAR
────────────────
* Digest FAQAT ilova manbasini qamraydi. AYNI manba + BOSHQA kutubxona
  versiyalari = AYNI digest. `requirements.txt` ataylab qamralmaydi: u
  runtime image'da mavjud bo'lishi KAFOLATLANMAYDI, demak digestning
  «har safar hisoblanadi» xususiyati yo'qolardi. Bog'liqlik identiteti
  ALOHIDA masala (lock fayl + image digest).
* Digest MANBA DARAXTINI aniqlaydi, COMMITNI emas: faqat hujjat
  o'zgargan ikki commit AYNI digest beradi.
* Digest `app/` dan TASHQARIDAGI kodni (masalan `scripts/`) qamramaydi —
  u runtime xatti-harakatiga kirmaydi.

TAHDID MODELI — «PROVEN» DEB BELGILANMAYDI
──────────────────────────────────────────
| tahdid | holat |
|---|---|
| Rollback/redeploy SHA'ni yo'qotadi | **YOPILDI** (muhr artefakt ichida) |
| Eskirgan `APP_COMMIT_SHA` yolg'on aytadi | **YOPILDI** (muhr o'zgaruvchidan USTUN) |
| Artefakt muhrlangandan keyin tahrirlangan | **ANIQLANADI** (digest mos emas) |
| Repo yozuv huquqi bo'lgan hujumchi qayta muhrlaydi | **YOPILMAGAN** |
| Image yozuv huquqi bo'lgan hujumchi kod+muhrni birga o'zgartiradi | **YOPILMAGAN** |

Demak bu mexanizm **TASODIFGA QARSHI BUTUNLIK** beradi, **AUTENTIKLIK
EMAS**. Kriptografik kafolat uchun commit imzolash (GPG/SSH) va build
vaqtida imzo TEKSHIRUVI kerak; u ham ishonchni kalit saqlovchisiga
ko'chiradi, yo'q qilmaydi. Shu bois hech qayerda `PROVEN` deb
yozilmaydi — `TAMPER_EVIDENT` darajasi ishlatiladi.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
from typing import Iterable

#: Digest qaysi fayllarni qamraydi. SQL ham KIRADI: `db/cash/*.sql`
#: xatti-harakatni belgilaydi (sxema), ya'ni u ham relizning qismi.
PATTERNS: tuple[str, ...] = ("app/**/*.py", "app/**/*.sql")

#: Digestdan CHIQARILADIGAN yo'l bo'laklari.
#:
#: ⚠️  `_build_info.py` ATAYLAB chiqariladi: muhr o'zidan boshqa hamma
#:     narsaning digestini saqlashi kerak, aks holda «o'z digestini o'z
#:     ichiga yozish» imkonsiz aylanma bo'lardi.
EXCLUDE_PARTS: tuple[str, ...] = ("__pycache__",)
EXCLUDE_NAMES: tuple[str, ...] = ("_build_info.py",)

#: Muhr moduli (generatsiya qilinadi, qo'lda tahrirlanmaydi).
STAMP_MODULE = "app._build_info"

#: Digest versiyasi — ALGORITM o'zgarsa oshiriladi, aks holda eski va
#: yangi qiymatlar jimgina solishtirilib yolg'on «mos emas» berardi.
DIGEST_VERSION = "sd1"

#: Ishonch darajalari (hech biri `PROVEN` EMAS — docstringdagi tahdid
#: modeliga qara).
TRUST_STAMPED = "TAMPER_EVIDENT"      # muhr bor va kod bilan izchil
TRUST_MISMATCH = "STAMP_MISMATCH"     # muhr bor, lekin kod o'zgargan
TRUST_UNSTAMPED = "UNSTAMPED"         # muhr yo'q
TRUST_ENV_ONLY = "ENV_ONLY"           # faqat muhit o'zgaruvchisi (ishonchsiz)

#: `build_info()` eski xulqi uchun o'qiladigan o'zgaruvchilar (orqaga
#: moslik). Muhr bo'lsa ULAR E'TIBORGA OLINMAYDI.
ENV_KEYS: tuple[str, ...] = ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT",
                             "SOURCE_COMMIT", "GIT_COMMIT", "APP_COMMIT_SHA")

#: Hisoblangan digest keshi: ikkinchi chaqiruv fayl o'qimaydi.
#:
#: ⚠️  `/health` ARZON qolishi SHART (tiriklik tekshiruvi). 230 fayl
#:     ~5 MB — bir marta ~20-50 ms, keyin nol. Kesh jarayon umri uchun.
_CACHE: dict[str, str] = {}


def server_root() -> pathlib.Path:
    """`apps/server` katalogi — bu faylning joylashuvidan hisoblanadi.

    ⚠️  CWD GA TAYANMAYDI: Railway start buyrug'i katalogi va test
        ishga tushirish katalogi FARQ qiladi, shu bois nisbiy yo'l
        digestni muhitga bog'lab qo'yardi.
    """
    #  app/core/build_identity.py -> app/core -> app -> apps/server
    return pathlib.Path(__file__).resolve().parent.parent.parent


def iter_source_files(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Digestga kiradigan fayllar — BARQAROR tartibda.

    ⚠️  Tartib `as_posix()` bo'yicha: `pathlib.glob` tartibi platformaga
        va fayl tizimiga bog'liq, ya'ni u yolg'on digest farqi berardi.
    """
    root = root or server_root()
    topildi: set[pathlib.Path] = set()
    for naqsh in PATTERNS:
        for p in root.glob(naqsh):
            if not p.is_file():
                continue
            nisbiy = p.relative_to(root)
            if any(part in EXCLUDE_PARTS for part in nisbiy.parts):
                continue
            if p.name in EXCLUDE_NAMES:
                continue
            topildi.add(p)
    return sorted(topildi, key=lambda p: p.relative_to(root).as_posix())


def compute_source_digest(root: pathlib.Path | None = None,
                          files: Iterable[pathlib.Path] | None = None) -> str:
    """Manba daraxtining DETERMINISTIK digesti (`sd1:<64 hex>`).

    ⚠️  QATOR OXIRI NORMALLASHTIRILADI (`\\r\\n` -> `\\n`). Windows
        checkout'ida `core.autocrlf=true` fayllarni CRLF bilan yozadi
        (shu loyihada O'LCHANGAN: `release.py` diskda 15595 bayt / 323 CR,
        HEAD blob'ida 15272 bayt / 0 CR). Normallashtirmasa AYNI kod
        platformaga qarab BOSHQA digest berardi va muhr har safar «mos
        emas» bo'lardi.

    ⚠️  YO'L VA UZUNLIK HAM HASH GA KIRADI: aks holda ikki faylning
        mazmunini almashtirish yoki chegarani surish digestni
        o'zgartirmasdan kodni o'zgartirishga imkon berardi.
    """
    root = root or server_root()
    h = hashlib.sha256()
    h.update(DIGEST_VERSION.encode("ascii"))
    h.update(b"\0")
    for p in (files if files is not None else iter_source_files(root)):
        nisbiy = pathlib.Path(p).resolve().relative_to(root).as_posix()
        xom = pathlib.Path(p).read_bytes().replace(b"\r\n", b"\n")
        h.update(nisbiy.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(xom)).encode("ascii"))
        h.update(b"\0")
        h.update(xom)
        h.update(b"\0")
    return f"{DIGEST_VERSION}:{h.hexdigest()}"


def source_digest(*, refresh: bool = False) -> str | None:
    """Keshlangan digest. Xato bo'lsa `None` (`/health` YIQILMAYDI)."""
    if refresh:
        _CACHE.pop("digest", None)
        _CACHE.pop("error", None)
    if "digest" in _CACHE:
        return _CACHE["digest"]
    if "error" in _CACHE:
        return None
    try:
        d = compute_source_digest()
    except Exception as e:                           # noqa: BLE001
        #  ⚠️  SABAB SAQLANADI, lekin `/health` javobida fayl yo'llari
        #      CHIQMAYDI (ochiq endpoint): faqat xato SINFI.
        _CACHE["error"] = type(e).__name__
        return None
    _CACHE["digest"] = d
    return d


def digest_error() -> str | None:
    return _CACHE.get("error")


def read_stamp() -> dict | None:
    """Muhrni o'qiydi. Yo'q bo'lsa `None`; buzuq bo'lsa ham `None`.

    ⚠️  IMPORT XATOSI JIM YUTILADI (faqat sinfi qayd etiladi): muhr
        YO'QLIGI normal holat (mahalliy ishlab chiqish), shu bois u
        ilovani ko'tarilishdan TO'SMASLIGI kerak.
    """
    try:
        mod = __import__(STAMP_MODULE, fromlist=["COMMIT"])
    except Exception:                                # noqa: BLE001
        return None
    xom = {k: getattr(mod, k, None) for k in
           ("COMMIT", "SOURCE_DIGEST", "SEALED_AT", "SEALED_BY", "BRANCH_REF",
            "STAMP_VERSION")}
    if not str(xom.get("COMMIT") or "").strip():
        return None
    return xom


def build_identity() -> dict:
    """RELIZ IDENTITETI — to'rt manbani AJRATIB beradi.

    ⚠️  USTUNLIK TARTIBI: muhr > muhit o'zgaruvchisi. Sabab: muhr
        artefakt ICHIDA, o'zgaruvchi esa TASHQARIDA va eskirishi mumkin.

    ⚠️  MUHR MOS KELMASA `commit` E'LON QILINMAYDI. «Taxmin qilmaslik»
        talabi (topshiriq §2) aynan shu: artefakt muhrlangandan keyin
        o'zgargan bo'lsa, muhrdagi commit YOLG'ON bo'ladi va uni
        ko'rsatish `null` dan BATTAR.
    """
    muhr = read_stamp()
    hozirgi = source_digest()
    out: dict = {
        "commit": None,
        "commit_source": None,
        "trust": TRUST_UNSTAMPED,
        "source_digest": hozirgi,
        "stamp_digest": None,
        "stamp_matches_source": None,
        "sealed_at": None,
        "branch_ref": None,
        "deployment_id": (os.getenv("RAILWAY_DEPLOYMENT_ID") or "").strip() or None,
        "replica_id": (os.getenv("RAILWAY_REPLICA_ID") or "").strip() or None,
    }
    if hozirgi is None:
        out["source_digest_error"] = digest_error()

    if muhr is not None:
        out["stamp_digest"] = muhr.get("SOURCE_DIGEST")
        out["sealed_at"] = muhr.get("SEALED_AT")
        out["branch_ref"] = muhr.get("BRANCH_REF")
        mos = (hozirgi is not None
               and str(muhr.get("SOURCE_DIGEST") or "") == str(hozirgi))
        out["stamp_matches_source"] = mos
        if mos:
            out["commit"] = str(muhr["COMMIT"]).strip()
            out["commit_source"] = "stamp"
            out["trust"] = TRUST_STAMPED
        else:
            #  FAIL-CLOSED: commit AYTILMAYDI.
            out["trust"] = TRUST_MISMATCH
            out["commit_source"] = None
        return out

    #  Muhr yo'q — ORQAGA MOSLIK: muhit o'zgaruvchisi o'qiladi, lekin
    #  ishonch darajasi ANIQ `ENV_ONLY` deb belgilanadi.
    #
    #  ⚠️  NEGA UMUMAN O'QIYMIZ: muhrsiz eski artefaktlar va mahalliy
    #      ishlab chiqish buzilmasligi kerak. Lekin iste'molchi
    #      (worker, preflight) `trust` ni ko'rib qaror qabul qiladi.
    for key in ENV_KEYS:
        val = (os.getenv(key) or "").strip()
        if val:
            out["commit"] = val
            out["commit_source"] = f"env:{key}"
            out["trust"] = TRUST_ENV_ONLY
            break
    return out
