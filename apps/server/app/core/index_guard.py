# -*- coding: utf-8 -*-
"""MAJBURIY indeks KAFOLATI yo'q bo'lsa — unga tayangan PUL YOZUVI FAIL-CLOSED.

═══ NEGA BU MODUL BOR ═══════════════════════════════════════════════════════
Ega qarori (2026-09-29): nomi bor, lekin **noyob bo'lmagan** majburiy indeks
boot'ni **to'xtatmaydi** — ishlab turgan do'konni shakl muammosi uchun ishdan
chiqarib bo'lmaydi. U tayyorlikni QIZIL qiladi (`required_schema.unique_index_problems`).

⚠️  LEKIN TAYYORLIK QIZIL **YETARLI EMAS**. `/health/ready` — monitoring signali;
    u hech qanday yozuvni to'smaydi. `ux_*_client_uuid` kabi indekslar esa
    idempotentlikning **OXIRGI** to'sig'i: yozuvchi yo'llar avval `client_uuid`
    bo'yicha SELECT qiladi, keyin INSERT — bu klassik TOCTOU. Indeks noyob
    bo'lmasa, ikki parallel qayta-yuborish o'sha oynadan sirg'alib o'tadi va
    **IKKI marta pul yoziladi** (ikkinchi to'lov, ikkinchi davr uzaytirish,
    ikkinchi sotuv...). Shu bois kafolat yo'qolganda YOZUV RAD ETILADI.

⚠️  MA'LUMOT BUZILMAYDI: amal bajarilmaydi, xolos. Operator indeksni tuzatib
    `/health/ready` ni yashil qilgach, ayni so'rov qaytadan yuboriladi. Bu
    `LOT_SCHEMA_NOT_READY` (partiya kuzatuvini yoqish darvozasi) bilan AYNI naqsh
    va AYNI HTTP holati (409 — holat ziddiyati, ma'lumot xatosi emas).

⚠️  JIMGINA O'TKAZIB YUBORISH YO'Q: tekshirib bo'lmasa ham RAD etiladi (fail-closed).
    «Bilmayman» — «xavfsiz» degani EMAS.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

from app.core import error_codes as EC

#: Barqaror kod — mijoz shu bo'yicha ishlov beradi (`X-Error-Code` + matn prefiksi).
SCHEMA_GUARANTEE_MISSING = "SCHEMA_GUARANTEE_MISSING"

#: Katalog so'rovi keshi. Indeks SHAKLI faqat DDL bilan o'zgaradi (operator amali yoki
#: yiqilgan CONCURRENTLY qurilishi), ya'ni u o'z-o'zidan buzilmaydi — qisqa TTL yetarli.
#: TTL kichik: operator indeksni tuzatgach do'kon ~yarim daqiqada o'ziga keladi.
_TTL_SECONDS = 30.0
_cache: dict[tuple[str, str], tuple[float, bool]] = {}


def reset_cache() -> None:
    """Testlar va operator tuzatishidan keyin — keshni bo'shatadi."""
    _cache.clear()


def index_healthy(bind, index: str, table: str) -> bool:
    """Indeks KAFOLATI bormi: mavjud VA noyob VA yaroqli.

    ⚠️  Tekshirib bo'lmasa `False` (fail-closed) — chaqiruvchi yozuvni rad etadi."""
    key = (index, table)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < _TTL_SECONDS:
        return hit[1]
    try:
        from app.core.required_schema import IX_OK, _unique_index_states
        ok = _unique_index_states(bind, [(index, table)]).get(key) == IX_OK
    except Exception as e:      # noqa: BLE001
        # Katalogni o'qib bo'lmadi -> KAFOLAT ISBOTLANMADI -> rad.
        print(f"[schema] {index} holatini o'qib bo'lmadi: {e}")
        ok = False
    _cache[key] = (now, bool(ok))
    return bool(ok)


def require_index(db, index: str, table: str, *, operation: str) -> None:
    """Kafolat yo'q bo'lsa 409 bilan FAIL-CLOSED.

    `db` — Session (yoki bind). `operation` — operator jumlasiga kirmaydi, faqat jurnalga.
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    if index_healthy(bind, index, table):
        return
    # ⚠️  MATNGA obyekt nomi QO'SHILMAYDI: bu javob do'kon xodimiga ketadi va
    #     sxema ichki tuzilishini oshkor qilishi shart emas. Nom — JURNALDA.
    print(f"[schema] YOZUV RAD ETILDI ({operation}): {index} ({table}) kafolati yo'q")
    raise HTTPException(
        409,
        f"{SCHEMA_GUARANTEE_MISSING}: Baza indeksi tayyor emas — takror yozuvdan "
        "himoya ishlamayapti, shu bois amal BAJARILMADI. Administrator sxemani "
        "tuzatgach qaytadan urinib ko'ring.",
        headers=EC.headers(SCHEMA_GUARANTEE_MISSING),
    )
