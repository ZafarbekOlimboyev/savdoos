# -*- coding: utf-8 -*-
"""MAJBURIY indeks KAFOLATI yo'q bo'lsa — unga tayangan YOZUV FAIL-CLOSED.

═══ NEGA BU MODUL BOR ═══════════════════════════════════════════════════════
Ega qarori (2026-09-29): nomi bor, lekin **noyob bo'lmagan** majburiy indeks
boot'ni **to'xtatmaydi** — ishlab turgan do'konni shakl muammosi uchun ishdan
chiqarib bo'lmaydi. U tayyorlikni QIZIL qiladi (`required_schema.unique_index_problems`).

⚠️  LEKIN TAYYORLIK QIZIL **YETARLI EMAS**: `/health/ready` — monitoring signali,
    u hech qanday yozuvni to'smaydi. Kafolatga tayangan yozuvchi yo'llar avval
    SELECT qilib keyin INSERT qiladi (klassik TOCTOU) — indeks kafolati yo'qolsa
    o'sha oyna ochiladi. Shu bois yozuv SHU YERDA rad etiladi.

⚠️  MA'LUMOT BUZILMAYDI: amal bajarilmaydi, xolos. Operator indeksni tuzatgach
    ayni so'rov qaytadan yuboriladi (`LOT_SCHEMA_NOT_READY` naqshi, AYNI 409).

═══ UCH HOLAT — «TEKSHIRIB BO'LMADI» ≠ «BUZUQ» ══════════════════════════════
⚠️  Bu modulning BIRINCHI versiyasi katalog o'qish XATOSINI ham `False` deb
    KESHLAGAN edi: bitta o'tkinchi nosozlik 30 soniyaga HAMMA qo'riqlangan
    yozuvni sog'lom sxemada ham rad etardi (o'z-o'zini kuchaytiruvchi uzilish).
    Endi uch holat ajratiladi:
      · OK           — tekshirildi, kafolat BOR   -> keshlanadi
      · BAD          — tekshirildi, kafolat YO'Q  -> keshlanadi
      · UNVERIFIABLE — tekshirib bo'lmadi          -> KESHLANMAYDI, lekin
                       SHU so'rov uchun fail-closed (rad etiladi)

═══ SHAKL KO'RLIGI YO'Q ═════════════════════════════════════════════════════
⚠️  `indisunique` YETARLI EMAS. Nomi to'g'ri, NOYOB, lekin BOSHQA ustunli yoki
    predikatsiz indeks kafolatni BERMAYDI: `ux_print_jobs_original` `WHERE
    copy = 'ORIGINAL'` siz qurilsa «sog'lom» ko'rinadi, lekin har REPRINT ni
    23505 bilan yiqitadi. Shu bois ta'rif ro'yxatga olingan bo'lsa
    (`required_schema.REQUIRED_INDEX_DEFINITIONS`) — USTUNLAR va PREDIKAT ham
    tekshiriladi.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

from app.core import error_codes as EC

#: Barqaror kod — mijoz shu bo'yicha ishlov beradi (`X-Error-Code` + matn prefiksi).
SCHEMA_GUARANTEE_MISSING = "SCHEMA_GUARANTEE_MISSING"

#: Uch holat.
OK = "ok"
BAD = "bad"
UNVERIFIABLE = "unverifiable"

#: Indeks SHAKLI faqat DDL bilan o'zgaradi (operator amali yoki yiqilgan
#: CONCURRENTLY qurilishi) — u o'z-o'zidan buzilmaydi, shu bois qisqa TTL yetarli.
_TTL_SECONDS = 30.0

#: ⚠️  KALIT BIND'NI HAM O'Z ICHIGA OLADI: bitta jarayon bir nechta bazaga ulanishi
#:     mumkin (testlar, ko'p-tenant zondlari). Bindsiz kalit bir bazaning javobini
#:     boshqasiga qo'llardi.
_cache: dict[tuple[int, str, str], tuple[float, str]] = {}


def reset_cache() -> None:
    """Testlar va operator tuzatishidan keyin — keshni bo'shatadi."""
    _cache.clear()


def _bind_of(db):
    return db.get_bind() if hasattr(db, "get_bind") else db


def index_state(bind, index: str, table: str) -> str:
    """`OK` | `BAD` | `UNVERIFIABLE`. Ta'rif ro'yxatda bo'lsa SHAKL ham tekshiriladi."""
    key = (id(bind), index, table)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < _TTL_SECONDS:
        return hit[1]

    from app.core import required_schema as rs
    try:
        state = rs._unique_index_states(bind, [(index, table)]).get((index, table))
    except Exception as e:      # noqa: BLE001
        print(f"[schema] {index} noyobligini o'qib bo'lmadi: {e}")
        return UNVERIFIABLE     # ⚠️  KESHLANMAYDI — o'tkinchi nosozlik uzilishga aylanmasin
    if state is None or state != rs.IX_OK:
        _cache[key] = (now, BAD)
        return BAD

    #  SHAKL: ta'rif ro'yxatga olingan bo'lsa ustunlar/predikat ham mos kelsin.
    if index in rs.REQUIRED_INDEX_DEFINITIONS:
        try:
            defs = rs.index_definition_states(bind)
        except Exception as e:      # noqa: BLE001
            print(f"[schema] {index} ta'rifini o'qib bo'lmadi: {e}")
            return UNVERIFIABLE
        d = defs.get(index)
        if d == rs.IX_DEF_UNREADABLE:
            return UNVERIFIABLE
        if d is not None and d != rs.IX_DEF_OK:
            _cache[key] = (now, BAD)
            return BAD
    _cache[key] = (now, OK)
    return OK


def index_healthy(bind, index: str, table: str) -> bool:
    """Kafolat ISBOTLANDIMI. «Tekshirib bo'lmadi» -> `False` (fail-closed)."""
    return index_state(bind, index, table) == OK


def require_index(db, index: str, table: str, *, operation: str) -> None:
    """Kafolat isbotlanmasa 409 bilan FAIL-CLOSED.

    ⚠️  CHAQIRUVCHIGA OGOHLANTIRISH: bu `HTTPException` ko'taradi. Uni
        `except HTTPException` bilan yutadigan yo'lga qo'ymang — `cutover_guard`
        ning `dry_run`/custody shoxi shunday yutadi va gard JIM o'chib qolardi.
    """
    state = index_state(_bind_of(db), index, table)
    if state == OK:
        return
    # ⚠️  MATNGA obyekt nomi QO'SHILMAYDI: javob do'kon xodimiga ketadi va sxema
    #     ichki tuzilishini oshkor qilishi shart emas. Nom — JURNALDA.
    print(f"[schema] YOZUV RAD ETILDI ({operation}): {index} ({table}) holati={state}")
    raise HTTPException(
        409,
        f"{SCHEMA_GUARANTEE_MISSING}: Baza indeksi tayyor emas — takror yozuvdan "
        "himoya ishlamayapti, shu bois amal BAJARILMADI. Administrator sxemani "
        "tuzatgach qaytadan urinib ko'ring.",
        headers=EC.headers(SCHEMA_GUARANTEE_MISSING),
    )
