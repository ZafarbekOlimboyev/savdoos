# -*- coding: utf-8 -*-
"""NATIJA PAKETI — `binos-discovery-<timestamp>/` papkasini quradi va TEKSHIRADI.

Operator oxirida FAQAT shu papkani ko'radi va shu papkani uzatadi. Shu bois papkaning shakli
shartnoma, qurish esa FAIL-CLOSED: bironta darvoza yiqilsa HECH NARSA yozilmaydi (yarim
yozilgan papka «hammasi joyida» ko'rinishini beradi, ichida esa yo'q narsa bo'ladi).

Shakl (arxitektor belgilagan, o'z-o'zidan «yaxshilanmaydi»):

    binos-discovery-<timestamp>/
        agent_status.json              agent yurishi        (`binos-agent-run-v1`)
        environment.json               muhit skaneri        (`binos-agent-env-v1`)
        agent_manifest.json            BUTUN papka xeshlari (`binos-agent-manifest-v1`)
        discovery_ai_candidates.json   analitik nomzodlari  (`binos-1c-ai-candidates-v1`)
        discovery_report.md            odam o'qiydigan hisobot
        bundle/                        Phase 4 runtime paketi — O'ZGARMAGAN holda
            export.json metadata.json run_status.json errors.json run_summary.md manifest.json
            probes/NN_<tur>.json       (faqat `APPROVED_PROBES`)

⚠️⚠️ YUQORIDAGI SHAKL — TUGAGAN (`COMPLETE`) YURISHNING shakli. YIQILGAN yurish ham PAPKA
     QOLDIRADI, lekin kamroq fayl bilan: `discovery_ai_candidates.json` faqat tahlilga
     yetgan yurishda bo'ladi, `bundle/` esa faqat paket OLINGANDA. Shakl ALOHIDA e'lon
     qilinmaydi — u `agent_status.json` dan CHIQARILADI (`_check_status_cross_refs`):
     `bundle_dir` ning `null` bo'lishi «paket olinmadi» degan MA'NOLI javob va u paketning
     yo'qligi bilan AYNAN mos kelishi kerak. Sabab: `states.FAILURE_MEANING` operatorga
     «natija papkasini hisoboti bilan saqlab, ishlab chiquvchiga uzating» deydi — papka
     yozilmasa, bu ko'rsatma bajarilmas bo'lib qolardi.

⚠️⚠️ NEGA `bundle/` OSTKI PAPKA va NEGA `agent_manifest.json`, `manifest.json` EMAS
Phase 4 runtime paketining O'Z `manifest.json` i bor va u `binos-1c-manifest-v1` sxemasida.
Agar agent ham ildizda `manifest.json` yozsa — BIR XIL NOM, IKKI XIL SXEMA: paketni o'qigan
kod (va operator skripti) qaysi hujjatni ushlab turganini aniqlay olmaydi. Phase 4 da aynan
shu nuqson butun paketni rad etgan edi, shu bois:
  · Phase 4 paketi TEGILMASDAN `bundle/` ichida yashaydi (nomlari ham, baytlari ham o'sha);
  · agentning manifesti ATAYLAB boshqacha ataladi — `agent_manifest.json`.
Brief «papka ichida kamida shu fayllar» deydi — ostki papka ham ICHIDA, va bu «Phase 4
kontraktini buzma» talabining YAGONA to'g'ri o'qilishi.

⚠️ IKKI MANIFEST — IKKI XIL HUJJAT:
  · `bundle/manifest.json`  — Phase 4: `{manifest_version, files, notes}`, faqat paket ichini
                               xeshlaydi, validatori `runtime_bundle.validate_manifest`;
  · `agent_manifest.json`   — agent: `{files, notes}`, BUTUN natija papkasini (shu jumladan
                               `bundle/...` fayllarini) xeshlaydi, validatori shu modulda.
Ularni «birlashtirish» yoki nomini bir xil qilish TAQIQ.

QAT'IY INVARIANTLAR:
  1. FAQAT BAYT XESHI. `source_copy` / `snapshot_at` / `plan_sha256` kabi MANBA provenansi
     maydonlari TAQIQLANGAN (Phase 2 qoidasi) — manifest «bu fayllar shu baytlar» deydi,
     «bu fayllar o'sha bazadan» DEMAYDI.
  2. Manifest O'ZINI xeshlamaydi (xeshni yozish xeshni o'zgartiradi — aylanma).
  3. Manifest papkadagi HAMMA faylni qamraydi: manifestda yo'q fayl — RAD, papkada yo'q
     manifest yozuvi — RAD. Ya'ni «ortiqcha fayl» jimgina qolib ketmaydi.
  4. `bundle/` Phase 4 VALIDATORIDAN o'tadi — mantiq QAYTA YOZILMAYDI,
     `runtime_bundle.validate_runtime_members` / `validate_runtime_bundle` CHAQIRILADI.
  5. JSON soni ham, JSON booleani ham YO'Q: har qanday sanoq MATN, uchulik mantiq
     `"true"`/`"false"`/`"unknown"` MATNI.
  6. SIR topilsa — RAD (`discovery_1c.redact.scan`), fail-closed, niqoblab «tuzatish» YO'Q.
  7. TIMESTAMP KIRISHDAN keladi. Bu modul soatga ham, muhitga ham qaramaydi — shu bois
     «bir xil kirish -> bir xil bayt» isbotlanadi.
  8. Mavjud papkaga YOZMAYDI: har yurish O'Z papkasini oladi, oldingisi o'chmaydi va ustiga
     yozilmaydi.

⚠️ XATO MATNLARIDA MAHALLIY YO'L YO'Q: papkaning absolyut yo'li do'kon mashinasining
   tuzilmasini oshkor qiladi (`redact` ni ham ishga soladi), bu matnlar esa ekrandan
   jurnalga, jurnaldan xabar almashinuviga ko'chadi. Shu bois nuqsonlar FAQAT natija
   papkasi ICHIDAGI nisbiy nomlar bilan yoziladi.

⚠️ 1C BU MODULDA YO'Q: u fayllar bilan ishlaydi, hech qaerga ulanmaydi, hech narsa
   bajarmaydi. Shu bois u TO'LIQ sinaladi — integratsiya yo'llarining `RUNTIME-UNKNOWN`
   holati bu modulga taalluqli emas.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import timezone
from typing import Mapping

from . import (AGENT_ARTIFACTS, AGENT_MANIFEST_FILE, AGENT_STATUS_FILE, AI_CANDIDATES_FILE,
               BUNDLE_SUBDIR, ENVIRONMENT_FILE, MANIFEST_VERSION, REPORT_FILE,
               RESULT_DIR_PREFIX)
from . import detector as det
from . import states as st
from . import status as agent_status
from ..discovery_1c import redact as redaction
from ..discovery_1c import runtime_bundle as rb
from ..discovery_1c.bundle import dumps
from ..discovery_1c.review import REVIEW_FILENAME, dumps_review
from ..migrator_1c.bundle import BundleError, parse_ts, sha256_bytes, strict_json_loads

#: Manifest hujjatining kalitlari — AYNAN IKKITA.
#: ⚠️ `manifest_version` kaliti ATAYLAB YO'Q. Phase 4 darsi: shartnomada berilgan kalit
#:    ro'yxatiga «aniqroq bo'lsin» deb maydon qo'shish — aynan o'sha bir tomonlama
#:    «yaxshilash», va u har bir real paketni rad etadi. Hujjatning o'zligi FAYL NOMI bilan
#:    beriladi (`agent_manifest.json`), sxema nomi esa `MANIFEST_VERSION` konstantasida
#:    yashaydi va XATO MATNLARIDA ko'rinadi.
AGENT_MANIFEST_KEYS: frozenset[str] = frozenset({"files", "notes"})
MANIFEST_FILE_KEYS: frozenset[str] = frozenset({"name", "bytes", "sha256"})

#: ⚠️ TAQIQLANGAN maydonlar Phase 4 dan QAYTA ISHLATILADI — ikkinchi ro'yxat yozilsa, u bir
#:    kun birinchisidan ajralib ketardi va taqiq bitta joyda qolardi.
FORBIDDEN_MANIFEST_KEYS: tuple[str, ...] = rb.FORBIDDEN_MANIFEST_KEYS

#: Manifestning O'Z izohlari — hujjat o'z chegarasini O'ZI bilan olib yuradi.
MANIFEST_NOTES: tuple[str, ...] = (
    "Bu manifest faqat YOZILGAN BAYTLARNI tasdiqlaydi — manba provenansi da'vosi EMAS.",
    "agent_manifest.json O'ZINI xeshlamaydi: o'z xeshini o'z ichiga yozish aylanma bo'lardi.",
    "bundle/ ostki papkasi Phase 4 runtime paketi va uning O'Z manifest.json i bor; bu fayl "
    "undan ATAYLAB boshqacha ataladi (bir xil nom, ikki xil sxema TAQIQ).",
)

#: Papka nomining vaqt qismi. ⚠️ ISO 8601 (`2026-09-30T10:15:00+06:00`) QABUL QILINMAYDI:
#: Windows fayl nomida `:` TAQIQLANGAN va `+` bilan papka nomi shubhali ko'rinadi. Shu bois
#: nomga faqat ASCII harf/raqam/`-`/`_` kiradi, tavsiya etilgan shakl — `compact_timestamp()`.
TIMESTAMP_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z_\-]{0,63}")

#: TAVSIYA ETILGAN (va kirish nuqtasi talab qiladigan) qisqa shakl: `YYYYMMDDTHHMMSSZ`.
#: ⚠️ `compact_timestamp()` AYNAN shu shaklni chiqaradi, `iso_from_compact()` esa uni ISO ga
#: qaytaradi — ikkisi bir-birining teskarisi va bu test bilan qulflangan.
COMPACT_TS_RE = re.compile(r"(?P<yil>[0-9]{4})(?P<oy>[0-9]{2})(?P<kun>[0-9]{2})T"
                           r"(?P<soat>[0-9]{2})(?P<daqiqa>[0-9]{2})(?P<sekund>[0-9]{2})Z")

#: Sanoq — ASCII raqamli MATN (yadrodagi va `status.py` dagi qoida bilan AYNI).
COUNT_TEXT_RE = re.compile(r"[0-9]{1,18}")

#: SHA-256: AYNAN 64 ta KICHIK harfli hex. ⚠️ Phase 4 `null` ga ruxsat beradi (yig'uvchi
#: ba'zi faylni o'qiy olmasligi mumkin), agent manifestida esa `null` TAQIQ: fayllarni
#: agentning O'ZI yozadi, demak «xeshini bilmayman» degan halol sabab YO'Q.
SHA256_RE = re.compile(r"[0-9a-f]{64}")

#: `bundle/` ichidagi fayl nomining old qo'shimchasi (yo'l har doim `/` bilan).
_BUNDLE_PREFIX = f"{BUNDLE_SUBDIR}/"

# ══════════════════════════════════════════════════════════════════════════════════════════
# PAPKANING SHAKLI HOLATDAN KELIB CHIQADI (ikkinchi e'lon YO'Q)
# ══════════════════════════════════════════════════════════════════════════════════════════
#: HAR QANDAY yurishda — muvaffaqiyatli ham, yiqilgan ham — BO'LISHI SHART bo'lgan fayllar.
#: ⚠️⚠️ NEGA YIQILGAN YURISH HAM PAPKA QOLDIRADI: `states.FAILURE_MEANING` operatorga
#:    «natija papkasini butunlay (hisoboti bilan) saqlab, ishlab chiquvchiga uzating» deydi.
#:    Agar yiqilishda papka umuman yozilmasa, bu ko'rsatma bajarilmaydigan bo'lib qolardi va
#:    nosozlikning YAGONA izi operator ekranidagi bir qatorlik xabar bo'lib qolardi.
ALWAYS_FILES: tuple[str, ...] = (AGENT_MANIFEST_FILE, AGENT_STATUS_FILE, ENVIRONMENT_FILE,
                                 REPORT_FILE)

#: FAQAT tahlil bosqichiga yetgan yurishda bo'ladigan fayl.
#: ⚠️ `COMPLETE` da MAJBURIY, boshqa holatda esa BO'LMASLIGI ham mumkin — lekin «bo'sh
#:    fayl yozib qo'yish» TAQIQ: bo'sh artefakt «tahlil bo'ldi, nomzod chiqmadi» degan
#:    boshqa ma'noni beradi.
OPTIONAL_AGENT_FILES: tuple[str, ...] = (AI_CANDIDATES_FILE,)

#: Yiqilgan yurishda ham MAJBURIY qoladigan Phase 4 tekshiruvlari — SIR darvozalari.
#: ⚠️⚠️ ASIMMETRIYA ATAYLAB: `COMPLETE` yurishda `bundle/` Phase 4 validatoridan TO'LIQ
#:    o'tishi SHART; yiqilgan yurishda esa paket AYNAN NUQSONI BILAN saqlanadi, chunki
#:    operator va ishlab chiquvchi shu baytlarni ko'rishi kerak — rad etilgan paketni
#:    tashlab yuborish YAGONA dalilni yo'q qilardi. LEKIN sir darvozasi ikki holatda ham
#:    ochilmaydi: nuqsonli paket bilan birga mijozning paroli tashqariga chiqib ketishi
#:    «dalilni saqlash» bilan oqlanmaydi.
BUNDLE_SECRET_CHECKS: tuple[str, ...] = ("maxfiylik_skani", "taqiqlangan_sir_naqshlari")


class ResultPackageError(ValueError):
    """Natija paketi shakli yoki invarianti buzilgan — HECH NARSA yozilmaydi."""


# ══════════════════════════════════════════════════════════════════════════════════════════
# KICHIK YORDAMCHILAR
# ══════════════════════════════════════════════════════════════════════════════════════════
def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ResultPackageError(msg)


def _keys(obj, allowed: frozenset[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} obyekt bo'lishi kerak")
    extra = sorted(set(obj) - allowed)
    _need(not extra,
          f"{where}: noma'lum kalit(lar) {extra} — {MANIFEST_VERSION} da yo'q")
    missing = sorted(allowed - set(obj))
    _need(not missing, f"{where}: kalit(lar) yetishmayapti {missing}")


def _nonempty(v, where: str) -> str:
    _need(isinstance(v, str) and v.strip() != "", f"{where} bo'sh bo'lmagan matn bo'lishi kerak")
    return v


def _rel_name(v, where: str) -> str:
    """Natija papkasi ICHIDAGI nisbiy fayl nomi.

    ⚠️ Qoida `status._rel_path` BILAN AYNI va u ATAYLAB takrorlangan: `status.py` dagi
    yordamchi MODUL-ICHKI (ostki chiziqli) va u bu agentning boshqa faylida turadi; uni
    ommaviy qilish — boshqa modulning shartnomasini o'zgartirish bo'lardi. To'rt qatorlik
    darvozani takrorlash arzonroq, va ikkisining AYNI xulqi test bilan QULFLANGAN.
    ⚠️ NEGA QAT'IY: absolyut yo'l mahalliy tuzilmani oshkor qiladi (va `redact` uni rad
    etadi); `..` papkadan tashqariga chiqadi, manifest esa faqat papka ichini xeshlaydi;
    teskari slesh platformaga bog'liq, ya'ni determinizmni buzadi.
    """
    _nonempty(v, where)
    _need("\\" not in v, f"{where}: teskari slesh YO'Q, yo'l `/` bilan yoziladi: {v!r}")
    _need(not v.startswith("/"), f"{where}: nisbiy nom bo'lishi kerak: {v!r}")
    _need(re.match(r"^[A-Za-z]:", v) is None, f"{where}: absolyut yo'l YO'Q: {v!r}")
    _need(".." not in v.split("/"), f"{where}: `..` bo'lagi YO'Q: {v!r}")
    return v


def _scalar_paths(node, path: str) -> list[str]:
    """JSON SONI yoki `true`/`false` turgan yo'llar (tartiblangan, takrorsiz)."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += _scalar_paths(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _scalar_paths(v, f"{path}[{i}]")
    elif isinstance(node, (bool, int, float)):
        out.append(f"{path} ({node!r})")
    return sorted(set(out))


def _assert_no_secrets(data, where: str) -> None:
    """Sir darvozasi (fail-closed). ⚠️ Xato matnida QIYMATNING O'ZI ko'rsatilmaydi."""
    topilgan = redaction.scan(data)
    _need(not topilgan,
          f"{where}: shubhali qiymat(lar) topildi, yozish RAD etildi — "
          f"{[str(f) for f in topilgan[:10]]}")


def _loads(text: str, where: str):
    try:
        return strict_json_loads(text)
    except BundleError as e:
        raise ResultPackageError(f"{where}: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════════════════
# PAPKA NOMI
# ══════════════════════════════════════════════════════════════════════════════════════════
def compact_timestamp(iso: str) -> str:
    """ISO 8601 vaqtni fayl nomiga yaroqli `YYYYMMDDTHHMMSSZ` ga aylantiradi (UTC).

    ⚠️ NEGA UTC: do'kon mashinasining zonasi o'zgarsa (yoki ikki filial papkasi bir joyga
       yig'ilsa) mahalliy vaqtli nomlar tartibsiz aralashadi. UTC da nom LEKSIK tartibda
       vaqt tartibiga teng bo'ladi.
    ⚠️ Vaqtni KIRISH beradi: bu funksiya ham soatga qaramaydi, faqat shakl o'zgartiradi.
    """
    try:
        vaqt = parse_ts(iso, "timestamp")
    except BundleError as e:
        raise ResultPackageError(str(e)) from e
    return vaqt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_from_compact(timestamp: str) -> str:
    """`YYYYMMDDTHHMMSSZ` -> ISO 8601 (`+00:00`). `compact_timestamp()` ning TESKARISI.

    ⚠️ NEGA KERAK: operator (va `--timestamp` bayrog'i) papka nomining qisqa shaklini beradi,
       modullar esa vaqtni ISO 8601 da (offset bilan) kutadi. Aylantirishni chaqiruvchining
       o'ziga qoldirish — har chaqiruvchida boshqacha satr qirqishi degani, ya'ni bir kun
       ikkisi ajralib ketardi.
    ⚠️ Sana HAQIQIYLIGI ham tekshiriladi (`parse_ts`): `20261345T999999Z` shaklga mos, lekin
       sana EMAS.
    """
    _nonempty(timestamp, "timestamp")
    _need(COMPACT_TS_RE.fullmatch(timestamp) is not None,
          f"timestamp `YYYYMMDDTHHMMSSZ` shaklida bo'lishi kerak, kelgani {timestamp!r}")
    m = COMPACT_TS_RE.fullmatch(timestamp)
    assert m is not None  # yuqoridagi darvoza
    iso = (f"{m.group('yil')}-{m.group('oy')}-{m.group('kun')}T"
           f"{m.group('soat')}:{m.group('daqiqa')}:{m.group('sekund')}+00:00")
    try:
        parse_ts(iso, "timestamp")
    except BundleError as e:
        raise ResultPackageError(str(e)) from e
    return iso


def result_dir_name(timestamp: str) -> str:
    """`binos-discovery-<timestamp>`. ⚠️ Timestamp KIRISHDAN keladi, o'ylab chiqarilmaydi."""
    _nonempty(timestamp, "timestamp")
    _need(TIMESTAMP_RE.fullmatch(timestamp) is not None,
          f"timestamp fayl nomiga yaroqli bo'lishi kerak (ASCII harf/raqam/`-`/`_`, "
          f"`:` va `+` TAQIQ — Windows fayl nomi): {timestamp!r}; tavsiya: "
          f"`compact_timestamp()`")
    return f"{RESULT_DIR_PREFIX}{timestamp}"


def timestamp_from_dir_name(name: str) -> str:
    """Papka nomidan vaqt qismini ajratadi (nom shartnomaga mos bo'lmasa — ISTISNO)."""
    _nonempty(name, "papka nomi")
    _need(name.startswith(RESULT_DIR_PREFIX),
          f"natija papkasining nomi {RESULT_DIR_PREFIX!r} bilan boshlanishi kerak, "
          f"kelgani {name!r}")
    ts = name[len(RESULT_DIR_PREFIX):]
    _need(TIMESTAMP_RE.fullmatch(ts) is not None,
          f"papka nomidagi vaqt qismi shartnomaga mos emas: {ts!r}")
    return ts


# ══════════════════════════════════════════════════════════════════════════════════════════
# MANIFEST
# ══════════════════════════════════════════════════════════════════════════════════════════
def build_agent_manifest(members: Mapping[str, bytes], *, notes=MANIFEST_NOTES) -> dict:
    """`binos-agent-manifest-v1` hujjati: `{files:[{name,bytes,sha256}], notes}`.

    ⚠️ `AGENT_MANIFEST_FILE` o'zi ro'yxatga KIRMAYDI (aylanma), `bundle/...` fayllari esa
       KIRADI — manifest BUTUN papkaning yozuvi, Phase 4 paketining o'z manifesti esa faqat
       o'z ichini tasdiqlaydi.
    ⚠️ Faqat UCH maydon: nom, bayt hajmi (MATN), sha256. Boshqasi — provenans da'vosi.
    """
    _need(isinstance(members, Mapping), "members `nom -> baytlar` ko'rinishida bo'lishi kerak")
    rows = []
    for nom in sorted(members):
        _rel_name(nom, "manifest fayl nomi")
        if nom == AGENT_MANIFEST_FILE:
            continue
        raw = members[nom]
        _need(isinstance(raw, (bytes, bytearray)),
              f"{nom}: mazmun BAYT bo'lishi kerak (matn emas) — xesh baytdan hisoblanadi")
        raw = bytes(raw)
        rows.append({"name": nom, "bytes": str(len(raw)), "sha256": sha256_bytes(raw)})
    _need(rows, "manifest bo'sh bo'lmasligi kerak: xeshlanadigan fayl yo'q")
    izohlar = [_nonempty(n, "manifest.notes[]") for n in notes]
    return {"files": rows, "notes": izohlar}


def validate_agent_manifest(doc, *, where: str = "agent_manifest") -> None:
    """Manifest hujjatini QAT'IY tekshiradi (shakl + taqiqlar + determinizm)."""
    _need(isinstance(doc, dict), f"{where} obyekt bo'lishi kerak")
    taqiq = sorted(k for k in FORBIDDEN_MANIFEST_KEYS if k in doc)
    _need(not taqiq,
          f"{where}: MANBA provenansi maydon(lar)i {taqiq} — manifest faqat YOZILGAN "
          f"BAYTLARNI tasdiqlaydi. Bunday da'volar metadata razvedkasidan kelib chiqmaydi "
          f"va mustaqil tasdiqlanishi shart (Phase 2 qoidasi ularni ATAYLAB taqiqlagan)")
    _keys(doc, AGENT_MANIFEST_KEYS, where)

    sonlar = _scalar_paths(doc, where)
    _need(not sonlar,
          f"{where}: JSON soni/booleani TAQIQLANGAN (qiymatni MATN qilib yozing) — {sonlar}")

    rows = doc["files"]
    _need(isinstance(rows, list) and rows,
          f"{where}.files bo'sh bo'lmagan ro'yxat bo'lishi kerak")
    nomlar: list[str] = []
    for i, f in enumerate(rows):
        w = f"{where}.files[{i}]"
        taqiq = sorted(k for k in FORBIDDEN_MANIFEST_KEYS
                       if isinstance(f, dict) and k in f)
        _need(not taqiq, f"{w}: MANBA provenansi maydon(lar)i {taqiq} — manifestda faqat "
                         f"fayl nomi, bayt hajmi va sha256 bo'ladi")
        _keys(f, MANIFEST_FILE_KEYS, w)
        nom = _rel_name(f["name"], f"{w}.name")
        # ⚠️ MANIFEST O'ZINI XESHLAMAYDI: xeshni yozish xeshni o'zgartiradi (aylanma).
        _need(nom != AGENT_MANIFEST_FILE,
              f"{w}.name: manifest O'ZINI xeshlay olmaydi — {AGENT_MANIFEST_FILE!r} "
              f"ro'yxatda turmaydi")
        nomlar.append(nom)
        hajm = f["bytes"]
        _need(isinstance(hajm, str) and COUNT_TEXT_RE.fullmatch(hajm) is not None,
              f"{w}.bytes ASCII raqamli MATN bo'lishi kerak (JSON soni TAQIQ): {hajm!r}")
        _need(isinstance(f["sha256"], str) and SHA256_RE.fullmatch(f["sha256"]) is not None,
              f"{w}.sha256 AYNAN 64 ta KICHIK harfli hex bo'lishi kerak (`null` ham TAQIQ: "
              f"fayllarni agent O'ZI yozadi, «xeshini bilmayman» degan sabab yo'q)")
    _need(len(set(nomlar)) == len(nomlar),
          f"{where}.files: fayl nomi takrorlangan "
          f"{sorted({n for n in nomlar if nomlar.count(n) > 1})}")
    # ⚠️ TARTIB SHARTNOMA: papka ro'yxatining tabiiy tartibi OS va fayl tizimiga bog'liq,
    #    ya'ni aynan shu joy «bir xil kirish — bir xil bayt» ni buzadi.
    _need(nomlar == sorted(nomlar), f"{where}.files tartiblangan bo'lishi kerak (determinizm)")

    izohlar = doc["notes"]
    _need(isinstance(izohlar, list) and all(isinstance(x, str) for x in izohlar),
          f"{where}.notes matnlar ro'yxati bo'lishi kerak")
    _assert_no_secrets(doc, where)


# ══════════════════════════════════════════════════════════════════════════════════════════
# AGENT ARTEFAKTLARINING DARVOZALARI (yozishdan OLDIN)
# ══════════════════════════════════════════════════════════════════════════════════════════
def _check_status(text: str, problems: list[str]) -> dict | None:
    """`agent_status.json`: YADRONI chaqiradi (`status.validate_agent_status`) va baytlarni
    solishtiradi.

    ⚠️ Shakl tekshiruvi QAYTA YOZILMAYDI — `status.py` ning validatori CHAQIRILADI.
    ⚠️ Baytlar `AgentStatus.to_json()` (ya'ni `bundle.dumps`) chiqishiga TENG bo'lishi kerak:
       ikkinchi yozuvchi paydo bo'lsa, bir xil hujjat ikki xil bayt berib, xesh manifestini
       ma'nosiz qilardi.
    """
    try:
        doc = _loads(text, AGENT_STATUS_FILE)
        agent_status.validate_agent_status(doc)
    except (ResultPackageError, agent_status.AgentStatusError) as e:
        problems.append(f"{AGENT_STATUS_FILE}: {e}")
        return None
    if text != dumps(doc):
        problems.append(f"{AGENT_STATUS_FILE}: baytlar deterministik shaklda emas "
                        f"(`bundle.dumps`: kalitlar tartiblangan, ortiqcha probel yo'q)")
    return doc


def _check_environment(text: str, problems: list[str]) -> dict | None:
    """`environment.json`: sxema nomi, kalitlar, uchulik mantiq, sanoq-matn va sir.

    ⚠️ BAYT SHAKLI BU YERDA MAJBURLANMAYDI: `environment.json` ning yozuvchisi
       `detector.dump_document` (u `indent=2` va kalit tartibini SAQLAB yozadi). Shu baytlarni
       bu yerda qayta ta'riflash IKKINCHI yozuvchi yasardi — loyiha aynan shuni taqiqlaydi.
    ⚠️ `selected` ning `infobases[].locator` lardan biri bo'lishi TEKSHIRILMAYDI: fayl
       bazalarining `locator` i niqoblanadi (`[REDACTED]`), ya'ni ikki baza bir xil
       ko'rinadi va bunday tekshiruv HALOL hujjatni rad etardi (`detector` docstringi).
    """
    doc = None
    try:
        doc = _loads(text, ENVIRONMENT_FILE)
    except ResultPackageError as e:
        problems.append(str(e))
        return None
    if not isinstance(doc, dict):
        problems.append(f"{ENVIRONMENT_FILE}: obyekt bo'lishi kerak")
        return None

    kutilgan = {"env_version", "scanned_at", "os_version", "installs", "com_registered",
                "infobases", "selected", "notes"}
    extra = sorted(set(doc) - kutilgan)
    missing = sorted(kutilgan - set(doc))
    if extra:
        problems.append(f"{ENVIRONMENT_FILE}: noma'lum kalit(lar) {extra} — "
                        f"{det.ENV_VERSION} da yo'q")
    if missing:
        problems.append(f"{ENVIRONMENT_FILE}: kalit(lar) yetishmayapti {missing}")
    if doc.get("env_version") != det.ENV_VERSION:
        problems.append(f"{ENVIRONMENT_FILE}.env_version {det.ENV_VERSION!r} bo'lishi kerak, "
                        f"kelgani {doc.get('env_version')!r}")
    sonlar = _scalar_paths(doc, ENVIRONMENT_FILE)
    if sonlar:
        problems.append(f"{ENVIRONMENT_FILE}: JSON soni/booleani TAQIQLANGAN — {sonlar}")

    # ⚠️ UCHULIK MANTIQ MATN: `"unknown"` ni booleanga siqish «1C yo'q» xulosasini
    #    «ko'rolmadim» holatidan ajratmay qo'yardi — agent qatlamining asosiy ajrimi.
    com = doc.get("com_registered")
    if com not in (det.TRI_TRUE, det.TRI_FALSE, det.TRI_UNKNOWN):
        problems.append(f"{ENVIRONMENT_FILE}.com_registered "
                        f"{[det.TRI_TRUE, det.TRI_FALSE, det.TRI_UNKNOWN]} dan biri "
                        f"(MATN) bo'lishi kerak, kelgani {com!r}")

    if isinstance(doc.get("installs"), list):
        for i, inst in enumerate(doc["installs"]):
            w = f"{ENVIRONMENT_FILE}.installs[{i}]"
            if not isinstance(inst, dict) or set(inst) != {"path", "version", "bitness",
                                                           "source"}:
                problems.append(f"{w}: kalitlar AYNAN `path`, `version`, `bitness`, `source`")
                continue
            if inst["source"] not in det.INSTALL_SOURCES:
                problems.append(f"{w}.source {list(det.INSTALL_SOURCES)} dan biri bo'lishi "
                                f"kerak, kelgani {inst['source']!r}")
    else:
        problems.append(f"{ENVIRONMENT_FILE}.installs ro'yxat bo'lishi kerak")

    if isinstance(doc.get("infobases"), list):
        for i, ib in enumerate(doc["infobases"]):
            w = f"{ENVIRONMENT_FILE}.infobases[{i}]"
            if not isinstance(ib, dict) or set(ib) != {"kind", "locator", "name", "source",
                                                       "requires_auth"}:
                problems.append(f"{w}: kalitlar AYNAN `kind`, `locator`, `name`, `source`, "
                                f"`requires_auth`")
                continue
            if ib["kind"] not in (det.KIND_FILE, det.KIND_SERVER):
                problems.append(f"{w}.kind {[det.KIND_FILE, det.KIND_SERVER]} dan biri "
                                f"bo'lishi kerak, kelgani {ib['kind']!r}")
            if ib["requires_auth"] not in (det.TRI_TRUE, det.TRI_FALSE, det.TRI_UNKNOWN):
                problems.append(f"{w}.requires_auth uchulik MATN bo'lishi kerak "
                                f"({det.TRI_UNKNOWN!r} ham QONUNIY qiymat), kelgani "
                                f"{ib['requires_auth']!r}")
    else:
        problems.append(f"{ENVIRONMENT_FILE}.infobases ro'yxat bo'lishi kerak")

    if not isinstance(doc.get("notes"), list) or not all(isinstance(x, str)
                                                        for x in doc.get("notes") or []):
        problems.append(f"{ENVIRONMENT_FILE}.notes matnlar ro'yxati bo'lishi kerak")

    try:
        _assert_no_secrets(doc, ENVIRONMENT_FILE)
    except ResultPackageError as e:
        problems.append(str(e))
    return doc


def _check_ai_candidates(text: str, problems: list[str]) -> None:
    """`discovery_ai_candidates.json`: YADRONING yozuvchisi bilan solishtiriladi.

    ⚠️ `review.dumps_review` BITTA chaqiruvda uch ishni bajaradi: shaklni tekshiradi, sirni
       skanerlaydi va DETERMINISTIK baytlarni qaytaradi. Shu bois bu yerda shakl qaytadan
       ta'riflanmaydi — natija baytlari yadroning chiqishiga TENG bo'lishi talab qilinadi.
    ⚠️ Fayl nomi ham yadrodan (`review.REVIEW_FILENAME`): operator AYNAN shu nomni izlaydi.
    ⚠️⚠️ BU FAYL `strict_json_loads` BILAN O'QILMAYDI va bu ATAYLAB. «Sanoqlar JSON'da MATN»
         qoidasi `confidence_score` ga TEGISHLI EMAS va buni yadro OCHIQ aytadi
         (`ai._confidence`: «Bu SANOQ EMAS, u o'lchov — o'lchovda boshidagi nol ma'no
         tashimaydi»). Ya'ni analitik artefaktida HAQIQIY JSON kasr soni QONUNIY, va uni
         sanoq darvozasi bilan rad etish YADRONING chiqishini rad etish bo'lardi. Haqiqiy
         darvoza — pastdagi BAYT solishtiruvi: u yadroning O'Z validatorini va sir skanerini
         ishga soladi, takror kalit esa baytlar mos kelmasligi bilan tutiladi.
    """
    try:
        doc = json.loads(text)
    except ValueError as e:
        problems.append(f"{AI_CANDIDATES_FILE}: JSON buzuq: {e}")
        return
    try:
        kutilgan = dumps_review(doc)
    except Exception as e:  # ReviewError va u meros olgan turlar
        problems.append(f"{AI_CANDIDATES_FILE}: yadro validatori rad etdi — {e}")
        return
    if text.encode("utf-8") != kutilgan:
        problems.append(f"{AI_CANDIDATES_FILE}: baytlar yadroning deterministik chiqishiga "
                        f"({REVIEW_FILENAME} yozuvchisi) teng emas")


def _check_report(text: str, problems: list[str]) -> None:
    """`discovery_report.md`: bo'sh emas, sir yo'q, `VERIFIED` DA'VOSI yo'q.

    ⚠️ `VERIFIED` darvozasi yadrodan QAYTA ISHLATILADI (`runtime_bundle.VERIFIED_WORD_RE`):
       agent hech narsani tasdiqlamaydi, `HUMAN_CONFIRMED` esa faqat operator tasdig'idan
       tug'iladi. So'z CHEGARASI shart — `0.1.0-UNVERIFIED` halol versiya va u RAD
       ETILMASLIGI kerak.
    ⚠️ Hisobot MATNIGA mazmun talabi (masalan «RUNTIME-UNKNOWN deb yozilgan bo'lsin»)
       QO'YILMAYDI: nasr ichidagi so'z darvozasi osongina qanoatlantiriladi va hech narsa
       isbotlamaydi. Halollik majburlanadigan joy — `environment.json` ning izohlari
       (`detector.RUNTIME_UNKNOWN_NOTE`) va `agent_status.json` ning holatlari.
    """
    if not text.strip():
        problems.append(f"{REPORT_FILE}: bo'sh — hisobotsiz paket uzatilmaydi")
    if rb.VERIFIED_WORD_RE.search(text):
        problems.append(f"{REPORT_FILE}: `VERIFIED` so'zi bor — agent hech narsani "
                        f"tasdiqlamaydi (tasdiq faqat operatordan: HUMAN_CONFIRMED)")
    try:
        _assert_no_secrets(text, REPORT_FILE)
    except ResultPackageError as e:
        problems.append(str(e))


def _is_complete(doc) -> bool:
    """Yurish `COMPLETE` bilan tugadimi (shakl buzuq bo'lsa — `False`, fail-closed)."""
    return isinstance(doc, dict) and doc.get("state") == st.COMPLETE


def _bundle_problems(report: rb.Report, *, complete: bool) -> list[str]:
    """Phase 4 hisobotidan nuqsonlar: `COMPLETE` da HAMMASI, yiqilishda faqat SIR.

    ⚠️ Sabab `BUNDLE_SECRET_CHECKS` izohida: yiqilgan paket DALIL bo'lib saqlanadi, lekin
       sir bilan birga saqlanmaydi.
    """
    if complete:
        return [] if report.ok else [f"{BUNDLE_SUBDIR}/: {p}" for p in report.problems]
    return [f"{BUNDLE_SUBDIR}/: {c.name}: {c.detail}" for c in report.checks
            if c.name in BUNDLE_SECRET_CHECKS and not c.ok]


def _check_status_cross_refs(doc: dict, names: set[str], problems: list[str]) -> None:
    """Yurish yozuvi papkaning O'ZI bilan mos kelishi.

    ⚠️ NEGA KERAK: `agent_status.json` papkaning mazmunini DA'VO qiladi (`bundle_dir`,
       `environment_file`, `artifacts`). Da'vo papkaga mos kelmasa, hisobotni o'qigan odam
       yo'q narsani izlaydi — bu «jimgina yarim natija» ning aynan o'zi.
    ⚠️ PAPKANING SHAKLI SHU YERDA HOLATDAN CHIQARILADI: `bundle_dir` ning `null` bo'lishi
       «paket OLINMADI» degan MA'NOLI javob (brief shaklida `matn|null`), shu bois u paketning
       YO'Qligi bilan AYNAN mos kelishi kerak — ikki tomonlama.
    """
    paket_bor = any(n.startswith(_BUNDLE_PREFIX) for n in names)
    complete = _is_complete(doc)
    bd = doc.get("bundle_dir")
    if bd is None and paket_bor:
        problems.append(f"{AGENT_STATUS_FILE}.bundle_dir `null`, lekin {BUNDLE_SUBDIR}/ "
                        f"papkasida fayl bor — yetim paket: yozuv uni DA'VO QILMAYDI")
    if bd is not None and not paket_bor:
        problems.append(f"{AGENT_STATUS_FILE}.bundle_dir {bd!r} deb da'vo qilingan, lekin "
                        f"{BUNDLE_SUBDIR}/ papkasida fayl YO'Q — da'vo bo'sh")
    if complete and not paket_bor:
        problems.append(f"{AGENT_STATUS_FILE}.state {st.COMPLETE} bo'lishi mumkin emas: "
                        f"razvedka paketsiz TUGAMAYDI")
    if complete and AI_CANDIDATES_FILE not in names:
        problems.append(f"{AGENT_STATUS_FILE}.state {st.COMPLETE}, lekin "
                        f"{AI_CANDIDATES_FILE} YO'Q — tahlilsiz yurish tugagan deb "
                        f"hisoblanmaydi")
    if bd is not None and bd.rstrip("/") != BUNDLE_SUBDIR:
        problems.append(f"{AGENT_STATUS_FILE}.bundle_dir {BUNDLE_SUBDIR!r} bo'lishi kerak "
                        f"(Phase 4 paketi AYNAN shu ostki papkada yashaydi), kelgani {bd!r}")
    ef = doc.get("environment_file")
    if ef is not None and ef != ENVIRONMENT_FILE:
        problems.append(f"{AGENT_STATUS_FILE}.environment_file {ENVIRONMENT_FILE!r} bo'lishi "
                        f"kerak, kelgani {ef!r}")
    yoq = sorted(n for n in doc.get("artifacts") or [] if n not in names)
    if yoq:
        problems.append(f"{AGENT_STATUS_FILE}.artifacts da'vo qilgan fayl(lar) papkada YO'Q: "
                        f"{yoq}")
    for p in doc.get("probes") or []:
        fayl = p.get("file")
        if isinstance(fayl, str) and f"{_BUNDLE_PREFIX}{fayl}" not in names and fayl not in names:
            problems.append(f"{AGENT_STATUS_FILE}.probes: zond fayli papkada YO'Q: {fayl!r}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# PAKET (immutable)
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ResultPackage:
    """Natija papkasining TO'LIQ mazmuni — O'ZGARMAS yozuv.

    ⚠️ Hamma qism KIRISHDAN keladi: vaqt tamg'asi, agent artefaktlari va Phase 4 paketi.
       Bu modul hech narsa O'YLAB CHIQARMAYDI va soatga qaramaydi — shu bois «bir xil
       kirish -> bir xil bayt» isbotlanadi.
    ⚠️ `bundle` JUFTLIKLAR KO'RINISHIDA (lug'at emas): frozen dataclass ichidagi lug'at
       tashqaridan o'zgartirilishi mumkin edi, ya'ni «o'zgarmas» so'zi yolg'on bo'lardi.
       `from_parts()` lug'atdan quradi.
    ⚠️ `ai_candidates_json` va `bundle` IXTIYORIY: yurish tahlilga yetmasdan yoki paket
       OLINMASDAN yiqilishi mumkin, va bunda ham papka yoziladi (`ALWAYS_FILES` izohiga
       qarang). Shakl HOLATDAN chiqariladi — `_check_status_cross_refs` ni ko'ring.
    """

    timestamp: str
    status_json: str
    environment_json: str
    report_md: str
    ai_candidates_json: str | None = None
    bundle: tuple[tuple[str, bytes], ...] = ()

    # ── Qurish ────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def from_parts(*, timestamp: str, status_json: str, environment_json: str,
                   report_md: str, ai_candidates_json: str | None = None,
                   bundle: Mapping[str, bytes] | None = None) -> "ResultPackage":
        """Phase 4 paketini lug'atdan oladi (nomlar `/` bilan, Phase 4 shartnomasidagidek)."""
        bundle = {} if bundle is None else bundle
        _need(isinstance(bundle, Mapping),
              "bundle `nom -> baytlar` lug'ati bo'lishi kerak (Phase 4 paketi)")
        rows = tuple((k, bytes(v)) for k, v in sorted(bundle.items()))
        return ResultPackage(timestamp=timestamp, status_json=status_json,
                             environment_json=environment_json,
                             ai_candidates_json=ai_candidates_json, report_md=report_md,
                             bundle=rows)

    # ── Hosila qiymatlar ──────────────────────────────────────────────────────────────────
    @property
    def dir_name(self) -> str:
        return result_dir_name(self.timestamp)

    def bundle_members(self) -> dict[str, bytes]:
        """Phase 4 paketi — O'ZGARMAGAN holda (`nom -> baytlar`)."""
        return {k: v for k, v in self.bundle}

    # ── Baytlar ───────────────────────────────────────────────────────────────────────────
    def members(self) -> dict[str, bytes]:
        """BUTUN papka: `nisbiy nom -> baytlar`, manifest bilan birga, tartiblangan.

        Navbat SHARTNOMA va u YAGONA mumkin bo'lgan navbat:
          1. Phase 4 paketi Phase 4 VALIDATORIDAN o'tadi (rad etilgan paket YOZILMAYDI);
          2. agent artefaktlari o'z darvozalaridan o'tadi (shakl, determinizm, sir);
          3. `agent_manifest.json` 1 va 2 dagi HAMMA faylning xeshini oladi (o'zidan tashqari).

        ⚠️ Bironta darvoza yiqilsa ISTISNO va HECH NARSA qaytmaydi (fail-closed): yarim
           yozilgan papka «hammasi joyida» ko'rinadi, ichida esa yo'q narsa bo'ladi.
        """
        result_dir_name(self.timestamp)  # ⚠️ nom darvozasi — eng arzoni, birinchi.
        problems = self.problems()
        _need(not problems,
              "natija paketi qurilmadi (HECH NARSA yozilmadi):\n  - "
              + "\n  - ".join(problems))
        return self._members_unchecked()

    def _members_unchecked(self) -> dict[str, bytes]:
        """Baytlarni YIG'ADI (tekshirmaydi) — `problems()` ham shu ko'rinishdan ishlaydi."""
        out: dict[str, bytes] = {
            AGENT_STATUS_FILE: self.status_json.encode("utf-8"),
            ENVIRONMENT_FILE: self.environment_json.encode("utf-8"),
            REPORT_FILE: self.report_md.encode("utf-8"),
        }
        # ⚠️ Tahlil bo'lmagan yurishda BO'SH fayl yozilmaydi: bo'sh artefakt «tahlil bo'ldi,
        #    nomzod chiqmadi» degan BOSHQA ma'noni beradi.
        if self.ai_candidates_json is not None:
            out[AI_CANDIDATES_FILE] = self.ai_candidates_json.encode("utf-8")
        for nom, raw in self.bundle:
            out[f"{_BUNDLE_PREFIX}{nom}"] = raw
        out[AGENT_MANIFEST_FILE] = dumps(build_agent_manifest(out)).encode("utf-8")
        return dict(sorted(out.items()))

    def problems(self) -> list[str]:
        """HAMMA nuqson bir yurishda (birinchisida to'xtamaydi).

        ⚠️ NEGA RO'YXAT: operator (va UI) o'nta nuqsonni o'n marta urinmasdan ko'rishi kerak —
           Phase 4 validatorining AYNI qarori.
        """
        problems: list[str] = []
        try:
            result_dir_name(self.timestamp)
        except ResultPackageError as e:
            problems.append(str(e))

        doc = _check_status(self.status_json, problems)
        paket = self.bundle_members()
        if paket:
            # ⚠️ `overall` (`PARTIAL`) HALOL paketning holati bo'lishi mumkin — yiqilgan
            #    bo'limi sababi bilan yozilgan paket ham UZATILADI. Shu bois faqat `ok`
            #    qaraladi: «fayllarga ishonib bo'ladimi» degan BOSHQA savol (`Report`
            #    docstringi), va u ham holatga qarab qat'iylashadi (`_bundle_problems`).
            problems += _bundle_problems(rb.validate_runtime_members(paket),
                                         complete=_is_complete(doc))

        # ⚠️ Agent o'z faylini Phase 4 paketining ustiga yozib yubormasligi kerak.
        for nom, _raw in self.bundle:
            try:
                _rel_name(nom, f"{BUNDLE_SUBDIR}/ fayl nomi")
            except ResultPackageError as e:
                problems.append(str(e))

        _check_environment(self.environment_json, problems)
        if self.ai_candidates_json is not None:
            _check_ai_candidates(self.ai_candidates_json, problems)
        _check_report(self.report_md, problems)
        if doc is not None:
            # ⚠️ Nomlar RO'YXATI manifest qurilishidan o'tadi, ya'ni u ham yiqilishi mumkin
            #    (masalan mazmun BAYT emas). Bu ham NUQSON, ISTISNO emas: `problems()` ning
            #    vazifasi — hamma nuqsonni bir yurishda ko'rsatish.
            try:
                nomlar = set(self._members_unchecked())
            except ResultPackageError as e:
                problems.append(str(e))
            else:
                _check_status_cross_refs(doc, nomlar, problems)
        return problems

    # ── Yozish ────────────────────────────────────────────────────────────────────────────
    def write(self, parent_dir: str) -> str:
        """Papkani `parent_dir` ichida quradi va YO'LINI qaytaradi.

        ⚠️ MAVJUD papkaga YOZMAYDI: har yurish O'Z papkasini oladi (`FileExistsError`
           ko'rinishidagi ISTISNO), oldingisi o'chmaydi va ustiga yozilmaydi.
        ⚠️ YASHIRIN YOZUV YO'Q: faqat shu papka ichiga, faqat shartnomadagi nomlar bilan.
           Reestrga ham, avtoyuklanishga ham, vaqtinchalik papkaga ham hech narsa yozilmaydi.
        ⚠️ Avval HAMMA bayt tayyorlanadi, keyin papka yaratiladi: rad etilgan paket bo'sh
           papka ham qoldirmaydi.
        """
        _nonempty(parent_dir, "parent_dir")
        members = self.members()
        root = os.path.join(parent_dir, self.dir_name)
        os.makedirs(root, exist_ok=False)
        for nom, raw in members.items():
            full = os.path.join(root, *nom.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(raw)
        return root


# ══════════════════════════════════════════════════════════════════════════════════════════
# PAPKA VALIDATORI (diskdagi natija uchun)
# ══════════════════════════════════════════════════════════════════════════════════════════
def read_folder_bytes(folder: str) -> dict[str, bytes]:
    """Papkani `nisbiy nom -> baytlar` ga o'qiydi (nom har doim `/` bilan, Windows ham).

    ⚠️ Papka YO'LI xato matniga TUSHMAYDI — faqat «papka topilmadi» degan fakt.
    ⚠️ Phase 4 paketini natija paketiga BAYT-BA-BAYT ko'chirish uchun ham shu funksiya
       ishlatiladi (`ui` qatlami): ikkinchi o'quvchi yozilsa, u bir kun boshqacha
       normallashtirib, xeshlarni ajratib qo'yardi.
    """
    _nonempty(folder, "papka yo'li")
    _need(os.path.isdir(folder), "papka topilmadi yoki papka emas")
    out: dict[str, bytes] = {}
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            with open(full, "rb") as fh:
                out[rel] = fh.read()
    return dict(sorted(out.items()))


def read_result_package(folder: str) -> dict[str, bytes]:
    """Natija papkasining HAMMA fayli (`read_folder_bytes` ning nomli ko'rinishi)."""
    return read_folder_bytes(folder)


def check_result_package(folder: str) -> list[str]:
    """Diskdagi natija papkasining HAMMA nuqsoni (bo'sh ro'yxat — paket to'g'ri).

    Tekshiriladi:
      1. papka nomi shartnomaga mos (`binos-discovery-<timestamp>`);
      2. ildizda MAJBURIY artefaktlar bor (`ALWAYS_FILES`, `COMPLETE` da `OPTIONAL_AGENT_FILES`
         ham) va ortiqcha fayl yo'q;
      3. `bundle/` PHASE 4 VALIDATORIDAN o'tadi (`runtime_bundle.validate_runtime_bundle`)
         — `COMPLETE` da TO'LIQ, yiqilgan yurishda esa SIR darvozalari
         (`BUNDLE_SECRET_CHECKS`);
      4. `agent_manifest.json` shakli to'g'ri va papkaning HAMMA faylini (shu jumladan
         `bundle/...`) QAMRAYDI — xeshlar va bayt hajmlari MOS;
      5. agent artefaktlarining shakli, determinizmi va sirdan tozaligi;
      6. yurish yozuvining da'volari papkaga mos.

    ⚠️ ISTISNO TASHLAMAYDI (nuqsonlar RO'YXAT bo'lib qaytadi) — `validate_result_package`
       esa ro'yxat bo'sh bo'lmasa ISTISNO beradi. Ikki shakl ataylab: UI ro'yxatni
       ko'rsatadi, quvur esa darvoza sifatida istisnoga tayanadi.
    """
    problems: list[str] = []
    try:
        timestamp_from_dir_name(os.path.basename(os.path.normpath(folder)))
    except ResultPackageError as e:
        problems.append(str(e))
    try:
        members = read_result_package(folder)
    except ResultPackageError as e:
        return problems + [str(e)]

    nomlar = set(members)

    # ── 2 · Yurish yozuvi BIRINCHI o'qiladi: papkaning SHAKLI undan kelib chiqadi ────────
    doc = None
    if AGENT_STATUS_FILE in members:
        doc = _check_status(_text(members[AGENT_STATUS_FILE], AGENT_STATUS_FILE, problems),
                            problems)
    complete = _is_complete(doc)
    # ⚠️ FAIL-CLOSED: yozuv o'qilmasa shakl CHIQARIB BO'LMAYDI, demak eng QAT'IY talab
    #    qo'llanadi (hamma artefakt). «Bilmayman» yengillikka aylanmaydi.
    kerakli = set(ALWAYS_FILES) | (set(OPTIONAL_AGENT_FILES) if complete or doc is None
                                   else set())
    yoq = sorted(n for n in kerakli if n not in nomlar)
    if yoq:
        problems.append(f"ildizdagi majburiy artefakt(lar) yo'q: {yoq}")

    # ── 3 · Phase 4 paketi — YADRO VALIDATORI ────────────────────────────────────────────
    bundle_dir = os.path.join(folder, BUNDLE_SUBDIR)
    if os.path.isdir(bundle_dir):
        problems += _bundle_problems(rb.validate_runtime_bundle(bundle_dir),
                                     complete=complete)
    elif complete:
        problems.append(f"{BUNDLE_SUBDIR}/ ostki papkasi yo'q — Phase 4 runtime paketi "
                        f"AYNAN shu yerda yashaydi (ildizda `manifest.json` YOZILMAYDI: "
                        f"bir xil nom, ikki xil sxema TAQIQ)")

    # ⚠️ Ildizda Phase 4 nomlari turmasligi kerak: `manifest.json` ikki sxemaga bo'linib
    #    ketgan joy aynan shu.
    ildiz_nomlari = {n for n in nomlar if "/" not in n}
    adashgan = sorted(ildiz_nomlari & set(rb.REQUIRED_FILES))
    if adashgan:
        problems.append(f"ildizda Phase 4 paketining fayl(lar)i turibdi: {adashgan} — ular "
                        f"{BUNDLE_SUBDIR}/ ichida bo'lishi kerak (bir xil nom, ikki xil "
                        f"sxema TAQIQ)")

    # ── 4 · MANIFEST ─────────────────────────────────────────────────────────────────────
    xom = members.get(AGENT_MANIFEST_FILE)
    if xom is not None:
        problems += _check_manifest_against_folder(xom, members)

    # ── 5 · AGENT ARTEFAKTLARI ───────────────────────────────────────────────────────────
    if ENVIRONMENT_FILE in members:
        _check_environment(_text(members[ENVIRONMENT_FILE], ENVIRONMENT_FILE, problems),
                           problems)
    if AI_CANDIDATES_FILE in members:
        _check_ai_candidates(_text(members[AI_CANDIDATES_FILE], AI_CANDIDATES_FILE, problems),
                             problems)
    if REPORT_FILE in members:
        _check_report(_text(members[REPORT_FILE], REPORT_FILE, problems), problems)
    if doc is not None:
        _check_status_cross_refs(doc, nomlar, problems)
    return problems


def _text(raw: bytes, nom: str, problems: list[str]) -> str:
    """Baytni UTF-8 matnga aylantiradi. ⚠️ BOM TAQIQ: u baytlarni va xeshni o'zgartiradi."""
    try:
        matn = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(f"{nom}: UTF-8 emas")
        return ""
    if matn.startswith("﻿"):
        problems.append(f"{nom}: UTF-8 BOM bor — determinizmni buzadi, BOM'siz yoziladi")
    return matn


def _check_manifest_against_folder(xom: bytes, members: Mapping[str, bytes]) -> list[str]:
    """Manifest papkaning HAMMA faylini qamraydi va xeshlar MOS keladi."""
    problems: list[str] = []
    try:
        matn = xom.decode("utf-8")
        doc = _loads(matn, AGENT_MANIFEST_FILE)
        validate_agent_manifest(doc)
    except (UnicodeDecodeError, ResultPackageError) as e:
        return [f"{AGENT_MANIFEST_FILE}: {e}"]
    if matn != dumps(doc):
        problems.append(f"{AGENT_MANIFEST_FILE}: baytlar deterministik shaklda emas "
                        f"(`bundle.dumps`)")

    dalvo = {f["name"]: f for f in doc["files"]}
    bor = {n for n in members if n != AGENT_MANIFEST_FILE}
    # ⚠️ IKKI TOMONLAMA: manifestda yo'q fayl ham, papkada yo'q yozuv ham NUQSON. Birinchisi
    #    «ortiqcha fayl jimgina qo'shildi», ikkinchisi «fayl yo'qoldi, da'vo qoldi».
    qamralmagan = sorted(bor - set(dalvo))
    if qamralmagan:
        problems.append(f"{AGENT_MANIFEST_FILE}: papkadagi fayl(lar) manifestda YO'Q: "
                        f"{qamralmagan}")
    yetim = sorted(set(dalvo) - bor)
    if yetim:
        problems.append(f"{AGENT_MANIFEST_FILE}: manifest da'vo qilgan fayl(lar) papkada "
                        f"YO'Q: {yetim}")
    for nom in sorted(bor & set(dalvo)):
        raw = members[nom]
        row = dalvo[nom]
        if row["bytes"] != str(len(raw)):
            problems.append(f"{AGENT_MANIFEST_FILE}: {nom} bayt hajmi mos emas "
                            f"(da'vo {row['bytes']}, haqiqiy {len(raw)})")
        if row["sha256"] != sha256_bytes(raw):
            # ⚠️ Xeshlarning O'ZI xato matnida ko'rsatilmaydi: faktning o'zi yetarli va
            #    qiymatlar jurnalga ko'chib yurishi kerak emas.
            problems.append(f"{AGENT_MANIFEST_FILE}: {nom} sha256 MOS KELMADI — fayl "
                            f"manifest yozilgandan keyin o'zgargan yoki manifest noto'g'ri")
    return problems


def validate_result_package(folder: str) -> None:
    """Diskdagi natija papkasining DARVOZASI: nuqson bo'lsa `ResultPackageError`.

    ⚠️ HAMMA nuqson BITTA istisno matnida beriladi (`check_result_package` ro'yxati): birinchi
       nuqsonda to'xtash qolgan o'ntasini keyingi yurishga qoldirardi.
    """
    problems = check_result_package(folder)
    _need(not problems,
          "natija paketi RAD etildi:\n  - " + "\n  - ".join(problems))


# ⚠️ IMPORT PAYTIDAGI SHARTNOMA TEKSHIRUVI: ro'yxatlar bir-biridan va YADRODAN ajralib
#    ketmasin. Testlar ham shu invariantlarni qulflaydi, lekin modul import bo'lgan ZAHOTI
#    yiqilishi — eng arzon darvoza (testi yurgizilmagan yo'l ham shu yerdan o'tadi).
assert set(ALWAYS_FILES) | set(OPTIONAL_AGENT_FILES) == set(AGENT_ARTIFACTS), \
    "ALWAYS_FILES + OPTIONAL_AGENT_FILES paket shartnomasidagi artefaktlarga teng emas"
assert not (set(ALWAYS_FILES) & set(OPTIONAL_AGENT_FILES)), \
    "bitta artefakt bir vaqtda majburiy ham, ixtiyoriy ham bo'lmaydi"
assert all(n in rb.CHECK_NAMES for n in BUNDLE_SECRET_CHECKS), \
    "BUNDLE_SECRET_CHECKS yadroning tekshiruv nomlaridan ajralib ketdi (runtime_bundle.CHECK_NAMES)"
