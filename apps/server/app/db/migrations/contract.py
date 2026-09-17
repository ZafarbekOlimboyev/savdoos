# -*- coding: utf-8 -*-
"""ANIQ SXEMA MIGRATSIYASI — hisobot shartnomasi (hukm, topilma, barqaror sha256).

Bu modul HECH QANDAY SQL bajarmaydi. U faqat:
  · hukm (`verdict`) va topilma (`finding`) lug'atini,
  · barqaror (kanonik) JSON va sha256 ni,
  · `plan_sha256` MANBASINI — ya'ni hisobotning QAYSI qismi reja identifikatori ekanini,
  · CLI chiqish kodlari xaritasini belgilaydi.

⚠️  `plan_sha256` ga FAQAT struktura (jadval/ustun/indeks/bog'liqlik) va baza identiteti
    kiradi. QATOR SONLARI va digest'lar ATAYLAB kirmaydi: jonli, lekin sokin bazada
    preflight va apply orasida bitta INSERT bo'lishi mumkin — bu rejani o'zgartirmaydi.
    Strukturaviy o'zgarish esa (indeks, cheklov, ustun tipi) rejani BEKOR qiladi.

⚠️  Hisobotga qiymat HECH QACHON tushmaydi — faqat SANOQ. Xato matni ham chiqmaydi
    (22P02 matni aynan o'sha qiymatni o'z ichiga oladi).
"""
from __future__ import annotations

import hashlib
import json

REPORT_SCHEMA_VERSION = "binos-schema-migrate-v1"

# ── Hukmlar ──────────────────────────────────────────────────────────────────
VERDICT_READY = "READY"                       # og'ish bor, bloker yo'q — apply mumkin
VERDICT_ALREADY_APPLIED = "ALREADY_APPLIED"   # maqsad holat allaqachon o'rnatilgan
VERDICT_BLOCKED = "BLOCKED"                   # operator qarori kerak — apply RAD etiladi
VERDICT_NOT_APPLICABLE = "NOT_APPLICABLE"     # bu dialektda migratsiyaning ma'nosi yo'q

# ── Topilma og'irliklari ─────────────────────────────────────────────────────
SEVERITY_BLOCK = "BLOCK"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_INFO = "INFO"

# ── Amal natijalari (apply/revert/verify) ────────────────────────────────────
RESULT_APPLIED = "APPLIED"
RESULT_ALREADY_APPLIED = "ALREADY_APPLIED"
RESULT_REHEARSED = "REHEARSED"
RESULT_NOT_APPLICABLE = "NOT_APPLICABLE"
RESULT_VERIFIED = "VERIFIED"

# ── Chiqish kodlari — `app/tools/_common.py` bilan AYNI shartnoma ────────────
EXIT_OK = 0          # READY / ALREADY_APPLIED / APPLIED / REHEARSED / VERIFIED / NOT_APPLICABLE
EXIT_USAGE = 1       # noto'g'ri argument yoki darvoza RAD etdi
EXIT_REVIEW = 2      # REVIEW bandlari yoki qayta urinsa bo'ladigan holat (qulf, vaqt chegarasi)
EXIT_BLOCK = 3       # BLOCKED / REJECTED / verify FAIL — davom etib bo'lmaydi


class MigrationError(RuntimeError):
    """Migratsiya bajarilmadi — tranzaksiya TO'LIQ qaytariladi."""


class MigrationBlocked(MigrationError):
    """Blokerlar bor (qiymat sinfi, kutilmagan bog'liqlik, ustun/jadval yo'q)."""


class MigrationRejected(MigrationError):
    """Ko'rib chiqilgan hisobot bu holatga MOS EMAS (struktura yoki baza o'zgargan)."""


class MigrationVerifyFailed(MigrationError):
    """Tranzaksiya ichidagi yakuniy tekshiruv o'tmadi — hech narsa saqlanmaydi."""


def finding(severity: str, code: str, detail: str) -> dict:
    """Topilma — O'ZGARMAS kod + qisqa tavsif. Tavsifda QIYMAT bo'lmaydi (faqat sanoq)."""
    return {"severity": severity, "code": code, "detail": detail}


def split_severity(findings) -> tuple[list[dict], list[dict], list[dict]]:
    block = [f for f in findings if f.get("severity") == SEVERITY_BLOCK]
    review = [f for f in findings if f.get("severity") == SEVERITY_REVIEW]
    info = [f for f in findings if f.get("severity") not in (SEVERITY_BLOCK, SEVERITY_REVIEW)]
    return block, review, info


def canonical_json(obj) -> str:
    """Barqaror JSON: kalitlar tartiblangan, bo'shliqsiz, ASCII majburlanmaydi."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def plan_source(report: dict) -> dict:
    """`plan_sha256` HISOBLANADIGAN qism — struktura + identitet + bloker kodlari.

    SONLAR (qator soni, qiymat sinflari, digest) ATAYLAB YO'Q — pastdagi izohga qarang.
    """
    db = report.get("database") or {}
    block, _review, _info = split_severity(report.get("findings") or [])
    return {
        "migration_id": report.get("migration_id"),
        "schema_version": report.get("schema_version"),
        "identity": {k: db.get(k) for k in ("dialect", "system_identifier", "database")},
        "structure": report.get("structure"),
        "blockers": sorted(f.get("code") for f in block),
    }


def plan_sha256(report: dict) -> str:
    return sha256_of(plan_source(report))


def report_sha256(report: dict) -> str:
    """Butun hisobot (o'zining `report_sha256` maydonisiz) — buzilganini aniqlash uchun."""
    return sha256_of({k: v for k, v in report.items() if k != "report_sha256"})


def seal(report: dict) -> dict:
    """Hisobotga `plan_sha256` va `report_sha256` ni qo'yadi (tartib: avval reja)."""
    report["plan_sha256"] = plan_sha256(report)
    report["report_sha256"] = report_sha256(report)
    return report


def exit_code_for(report: dict) -> int:
    """Hukm + topilmalar -> CLI chiqish kodi."""
    block, review, _info = split_severity(report.get("findings") or [])
    if report.get("verdict") == VERDICT_BLOCKED or block:
        return EXIT_BLOCK
    return EXIT_REVIEW if review else EXIT_OK
