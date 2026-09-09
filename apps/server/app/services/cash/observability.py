# -*- coding: utf-8 -*-
"""Naqd (pulga ta'sir qiluvchi) hodisalar uchun STRUKTURALI log.

MUAMMO: naqd amali yiqilganda hech narsa logga yozilmasdi — xato faqat HTTP javob bo'lib
kassirga ketardi. Production'da "kecha kimningdir naqd amali yiqildi" degan shikoyatni
tekshirishning yo'li yo'q edi: qaysi do'kon, qaysi filial, qaysi smena, qaysi sabab —
hech biri qolmasdi.

YECHIM: bitta qatorli JSON. `grep savdoos.cash` bilan topiladi, `jq` bilan filtrlanadi:

    {"evt":"cash_failure","code":"CASH_LEDGER_UNAVAILABLE","op":"cash_sale",
     "company_id":"...","branch_id":"...","shift_id":null,"source_type":"SALE",
     "source_id":"...","ts":"2026-09-09T07:00:00+00:00"}

SIR YOZILMAYDI — bu qat'iy qoida. Faqat texnik identifikatorlar:
  ✗ auth token / JWT      ✗ PIN / parol      ✗ DATABASE_URL / ulanish satri
  ✗ mijoz ismi / telefoni  ✗ to'lov rekvizitlari
  ✓ UUID, kod, operatsiya nomi, vaqt, summa (summa pul MIQDORI — shaxsiy ma'lumot emas)

Loglar Railway'da ushlanadi; alohida jurnal jadvali YARATILMAYDI (ledgerning o'zi allaqachon
append-only audit izi — ikkinchi haqiqat manbasi kerak emas).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("savdoos.cash")


def _s(v):
    """UUID/enum/None ni xavfsiz satrga aylantiradi."""
    if v is None:
        return None
    return str(getattr(v, "value", v))


def log_cash_failure(code: str, *, operation: str | None = None, company_id=None,
                     branch_id=None, shift_id=None, source_type=None, source_id=None,
                     amount=None, detail: str | None = None) -> None:
    """Pulga ta'sir qiluvchi NOSOZLIK. Hech qachon xato ko'tarmaydi — kuzatuv asosiy
    amalni buzmasligi shart (log yozolmaslik naqd amalini to'xtatmaydi)."""
    try:
        payload = {
            "evt": "cash_failure",
            "code": code,
            "op": operation,
            "company_id": _s(company_id),
            "branch_id": _s(branch_id),
            "shift_id": _s(shift_id),
            "source_type": _s(source_type),
            "source_id": _s(source_id),
            "amount": (str(amount) if amount is not None else None),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if detail:
            # Texnik tafsilot — QISQARTIRILADI (log qatori cheksiz o'smasin).
            payload["detail"] = str(detail)[:300]
        logger.warning(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:      # noqa: BLE001
        pass


def log_cash_event(evt: str, **fields) -> None:
    """Nosozlik bo'lmagan, lekin kuzatilishi kerak bo'lgan hodisa (masalan tiklash mashqi).
    Chaqiruvchi maydonlarni O'ZI beradi — bu yerda sir tekshiruvi YO'Q, shu bois faqat
    texnik qiymat uzating."""
    try:
        payload = {"evt": evt, "ts": datetime.now(timezone.utc).isoformat()}
        payload.update({k: _s(v) for k, v in fields.items()})
        logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:      # noqa: BLE001
        pass
