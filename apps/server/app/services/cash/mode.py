# -*- coding: utf-8 -*-
"""Cash Ledger — Phase 2 dual-write FEATURE GATE / migration holati.

Uch holat migration bosqichini ANIQ ajratadi (tasodifiy prod cutover'ni to'sadi):

  LEGACY_ONLY        — ledger'ga UMUMAN yozilmaydi. Legacy yagona (Phase 0/1'gача, yoki
                       ledger vaqtincha o'chirilса).
  DUAL_WRITE_SHADOW  — legacy YAGONA AVTORITET; ledger SOYA hisob (yoziladi, lekin HECH QANDAY
                       o'qish/qaror/UI ledger'ga tayanmaydi). Phase 2 holati.
  LEDGER_PRIMARY     — cutover: ledger avtoritet (o'qish yo'llari ledger'ga o'tadi). BU HOLAT
                       Phase 2'да YOQILMAYDI — qo'shimcha aniq flag talab qiladi (himoya).

Manba: env `SAVDOOS_CASH_MODE` (default DUAL_WRITE_SHADOW). LEDGER_PRIMARY qo'shimcha
`SAVDOOS_CASH_ALLOW_PRIMARY=1` talab qiladi — aks holда cash_mode() XATO ko'taradi (fail-safe:
tasodifiy prod cutover bo'lmaydi). Testlar uchun set_mode()/reset_mode() override.

MUHIM: bu modul FAQAT holatni O'QIYDI — hech narsa yozmaydi va ledger'ni O'QIMAYDI.
"""
from __future__ import annotations

import enum
import os


class CashMode(str, enum.Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    DUAL_WRITE_SHADOW = "DUAL_WRITE_SHADOW"
    LEDGER_PRIMARY = "LEDGER_PRIMARY"


_DEFAULT = CashMode.DUAL_WRITE_SHADOW
_OVERRIDE: CashMode | None = None   # FAQAT testlar uchun (env'ni bosib o'tadi)


def set_mode(m) -> None:
    """Test-only: rejimni majburan o'rnatadi. reset_mode() bilan tiklang."""
    global _OVERRIDE
    _OVERRIDE = CashMode(m) if m is not None else None


def reset_mode() -> None:
    global _OVERRIDE
    _OVERRIDE = None


def cash_mode() -> CashMode:
    """Joriy migration rejimi. LEDGER_PRIMARY (env orqali) qo'shimcha ALLOW flag talab qiladi —
    aks holда fail-safe XATO (tasodifiy cutover himoyasi)."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    raw = (os.getenv("SAVDOOS_CASH_MODE") or _DEFAULT.value).strip().upper()
    try:
        m = CashMode(raw)
    except ValueError:
        return _DEFAULT
    if m == CashMode.LEDGER_PRIMARY and os.getenv("SAVDOOS_CASH_ALLOW_PRIMARY") != "1":
        # Tasodifiy prod cutover himoyasi: LEDGER_PRIMARY faqat ikkinchi ANIQ flag bilan.
        raise RuntimeError(
            "CASH CUTOVER HIMOYASI: LEDGER_PRIMARY uchun SAVDOOS_CASH_ALLOW_PRIMARY=1 ham kerak. "
            "Phase 2'да ledger SOYA — cutover Phase 4/5.")
    return m


def dual_write_active() -> bool:
    """Ledger'ga YOZISH kerakmi? DUAL_WRITE_SHADOW yoki LEDGER_PRIMARY -> True. LEGACY_ONLY -> False."""
    return cash_mode() != CashMode.LEGACY_ONLY


def ledger_is_authority() -> bool:
    """O'qish/qaror/UI ledger'ga tayanadimi? FAQAT LEDGER_PRIMARY. Phase 2 (SHADOW)'да DOIM False —
    hech qanday read-path ledger'ga o'tmaydi."""
    return cash_mode() == CashMode.LEDGER_PRIMARY
