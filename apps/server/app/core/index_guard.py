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

import os
import time

from fastapi import HTTPException

from app.core import error_codes as EC

#: Barqaror kod — mijoz shu bo'yicha ishlov beradi (`X-Error-Code` + matn prefiksi).
SCHEMA_GUARANTEE_MISSING = "SCHEMA_GUARANTEE_MISSING"

#: Uch holat.
OK = "ok"
BAD = "bad"
UNVERIFIABLE = "unverifiable"

#: Indeks SHAKLI faqat DDL bilan o'zgaradi (operator amali yoki yiqilgan CONCURRENTLY
#: qurilishi) — u o'z-o'zidan buzilmaydi, shu bois qisqa TTL yetarli.
#:
#: ⚠️  ESKIRGAN MUSBAT JAVOB OYNASI. Kafolat BOR deb keshlangach, o'sha oyna ichida
#:     indeks buzilsa yozuv qo'riqlanmay o'tadi. Oynani NOLGA tushirish = har yozuvda
#:     katalog so'rovi (`doc_seq` har sotuvda chaqiriladi — bu issiq yo'l). Muvozanat:
#:     oyna QISQA va SOZLANADI. Buzilish operator DDL amali bilan sodir bo'ladi, ya'ni
#:     u kutilmagan emas — operator indeksni tuzatgach `/health/ready` ni tekshiradi.
#: ⚠️  MANFIY javob ham AYNI TTL bilan keshlanadi, lekin u XAVFSIZ tomonga xato qiladi
#:     (ortiqcha rad etish), shu bois uni uzaytirish kerak emas.
#:
#: HUJJATLASHTIRILGAN DIAPAZON (SAFE-03, 2026-10-01)
#: =================================================
#: ⚠️  `0` QONUNIY va eng xavfsiz sozlama: kesh butunlay o'chadi, har qo'riqlangan
#:     yozuv katalogni qaytadan so'raydi (sekinroq, lekin eskirgan musbat javob oynasi
#:     YO'Q). Keshni o'chirishning HUJJATLASHTIRILGAN yo'li — aynan `0`.
#: ⚠️  YUQORI CHEGARA NEGA KERAK. Yuqoridagi izoh oynani «QISQA» deb ta'riflaydi, lekin
#:     eski kod `999999999999` ni ham qabul qilardi — bu ~31 700 yillik kesh, ya'ni
#:     BIRINCHI `OK` dan keyin gard amalda BUTUNLAY o'chadi. Bu fail-open. Endi hech
#:     qanday env qiymati TTL ni `_TTL_MAX` dan oshira olmaydi, ya'ni eskirgan musbat
#:     javob oynasi QURILISH BO'YICHA cheklangan.
_TTL_DEFAULT = 10.0
_TTL_MIN = 0.0
_TTL_MAX = 300.0


def _env_ttl(name: str = "SAVDOOS_INDEX_GUARD_TTL") -> float:
    """Env'dan TTL — yaroqsiz qiymat SERVERNI YIQITMAYDI, default'ga tushadi.

    ⚠️  KONVENSIYA. Bu `app/db/session._envint()` ning AYNI shartnomasi: parse
        xatosi YOKI diapazondan tashqari qiymat -> HUJJATLASHTIRILGAN DEFAULT (clamp
        EMAS). Bitta qoida, ikkita natija — operator xatosi jim o'tmaydi, lekin ishlab
        turgan do'konni ham to'xtatmaydi.
    ⚠️  NEGA MUHIM (SAFE-03). Ilgari bu qator MODUL DARAJASIDA `float(...)` edi va
        `SAVDOOS_INDEX_GUARD_TTL=abc` `ValueError` berardi. Modul esa qo'riqlangan
        YOZUVCHILAR ichida LAZY import qilinadi (`doc_seq.allocate`,
        `payments.record_payment`), ya'ni boot OMON qolardi, lekin:
          · har qo'riqlangan yozuv `ValueError` bilan yiqilardi -> 409 emas, **500**;
          · import yiqilgan modul `sys.modules` da QOLMAYDI, ya'ni xato HAR so'rovda
            qaytadan ko'tarilardi (o'lchangan: 3/3 urinish);
          · `/health` va boot esa SOG'LOM ko'rinardi, `doc_seq` har SOTUVda chaqiriladi.
        Ya'ni bitta noto'g'ri yozilgan env qiymati deploy tekshiruvidan o'tib, keyin
        har sotuvni jimgina sindirardi.
    ⚠️  `inf`/`nan` ham shu yerda tutiladi: `float("inf")` parse bo'ladi, lekin
        diapazon tekshiruvidan o'tmaydi (`nan` uchun har qanday taqqoslash `False`).
    """
    xom = os.getenv(name)
    if xom is None or not xom.strip():
        return _TTL_DEFAULT
    try:
        v = float(xom)
    except (ValueError, TypeError):
        print(f"[schema] {name}={xom!r} son emas -> {_TTL_DEFAULT} s ishlatiladi")
        return _TTL_DEFAULT
    if not (_TTL_MIN <= v <= _TTL_MAX):
        print(f"[schema] {name}={xom!r} diapazondan tashqari "
              f"[{_TTL_MIN}, {_TTL_MAX}] -> {_TTL_DEFAULT} s ishlatiladi")
        return _TTL_DEFAULT
    return v


_TTL_SECONDS = _env_ttl()

#: ⚠️  KALIT BIND'NI HAM O'Z ICHIGA OLADI: bitta jarayon bir nechta bazaga ulanishi
#:     mumkin (testlar, ko'p-tenant zondlari). Bindsiz kalit bir bazaning javobini
#:     boshqasiga qo'llardi.
#: ⚠️  KALITDA SXEMA HAM BOR — bu MAJBURIY, qulaylik emas. Bu bazada `shifts`
#:     jadvali PUBLIC'da HAM, CASH'da HAM bor; indeks nomlari ham ikki sxemada bir
#:     xil bo'lishi mumkin. Sxemasiz kalit bitta sxemaning hukmini ikkinchisiga
#:     qo'llardi — ya'ni bitta `OK` butun TTL davomida BOSHQA sxemadagi yo'q
#:     kafolatni «bor» deb ko'rsatardi (o'lchangan: mutatsiya A).
_cache: dict[tuple[int, str, str, str], tuple[float, str]] = {}


def reset_cache() -> None:
    """Testlar va operator tuzatishidan keyin — keshni bo'shatadi."""
    _cache.clear()


def _bind_of(db):
    return db.get_bind() if hasattr(db, "get_bind") else db


def index_state(bind, index: str, table: str, *,
                schema: str = "public") -> str:
    """`OK` | `BAD` | `UNVERIFIABLE`. Ta'rif ro'yxatda bo'lsa SHAKL ham tekshiriladi.

    `schema` — qaysi SXEMADAGI indeks so'ralayapti. Standart `public`, ya'ni
    mavjud chaqiruvchilar uchun xulq AYNI.

    ⚠️  MAVJUD BO'LMAGAN SXEMA FAIL-CLOSED: nom katalogga BIND parametri bo'lib
        boradi, topilmasa hukm yo'q -> `BAD` -> yozuv rad etiladi. Hech qanday
        xato yozilgan sxema nomi `OK` bera OLMAYDI.
    ⚠️  SHAKL HAR SXEMANING O'Z registridan tekshiriladi
        (`required_schema.definitions_for`): public -> `REQUIRED_INDEX_DEFINITIONS`,
        cash -> `CASH_INDEX_DEFINITIONS`. Registri BO'LMAGAN sxemada faqat NOYOBLIK
        tekshiriladi — ya'ni ayni nomli, boshqa ustunli indeks SEZILMAYDI. Bu
        fail-open EMAS (noyoblik zondi sxemani topmasa `BAD` beradi), lekin shakl
        ko'rligi — ro'yxatga olinmagan HAR indeksdagi AYNI qoldiq.
    """
    key = (id(bind), schema, index, table)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < _TTL_SECONDS:
        return hit[1]

    from app.core import required_schema as rs
    try:
        state = rs._unique_index_states(
            bind, [(index, table)], schema=schema).get((index, table))
    except Exception as e:      # noqa: BLE001
        print(f"[schema] {index} noyobligini o'qib bo'lmadi: {e}")
        return UNVERIFIABLE     # ⚠️  KESHLANMAYDI — o'tkinchi nosozlik uzilishga aylanmasin
    if state is None or state != rs.IX_OK:
        _cache[key] = (now, BAD)
        return BAD

    #  SHAKL: ta'rif ro'yxatga olingan bo'lsa ustunlar/predikat ham mos kelsin.
    #  ⚠️  REGISTR SXEMAGA BOG'LANGAN (`rs.definitions_for`). Usiz ayni nomli CASH
    #      indeksi PUBLIC registriga tushib, public shakliga solishtirilardi —
    #      ya'ni yolg'on `IX_DEF_WRONG` (sog'lom cash indeksi uchun abadiy 409)
    #      yoki yolg'on `IX_DEF_OK`. Noma'lum sxemada registr BO'SH bo'ladi va
    #      shakl tekshirilmaydi, lekin NOYOBLIK zondi sxemani topmasdan `BAD`
    #      berganligi uchun fail-open BO'LMAYDI.
    if index in rs.definitions_for(schema):
        try:
            defs = rs.index_definition_states(bind, schema=schema)
        except Exception as e:      # noqa: BLE001
            print(f"[schema] {index} ta'rifini o'qib bo'lmadi: {e}")
            return UNVERIFIABLE
        d = defs.get(index)
        #  ⚠️  HUKM YO'Q = TEKSHIRILMADI, «TO'G'RI» EMAS (SAFE-02, 2026-10-01).
        #      `index_definition_states` FAQAT topilgan indekslar uchun kalit qaytaradi
        #      (uning docstring'i: «Faqat TOPILGANLARI»). Ya'ni bu yerda `None` —
        #      «noyoblik zondi indeksni KO'RDI, shakl zondi esa KO'RMADI» degani.
        #      Ikki zond IKKI ALOHIDA ulanishda o'qiydi (`_con_of(bind)` har birida
        #      o'z kontekst menejeri), shu bois oraliqda `DROP INDEX` bo'lsa AYNAN shu
        #      holat yuzaga keladi. Ilgari bu shox pastga tushib `OK` KESHLAGAN edi —
        #      o'lchangan: indeks bazada YO'Q bo'lsa ham qo'riqlangan yozuv o'tib
        #      ketardi va bitta poyga keshni butun TTL davomida zaharlardi.
        #      `UNVERIFIABLE` KESHLANMAYDI: o'tkinchi poyga shu so'rovni rad etadi,
        #      keyingi so'rov qaytadan tekshiradi (uzilishga aylanmaydi).
        if d is None:
            print(f"[schema] {index} shakli uchun hukm YO'Q (noyoblik zondi ko'rdi, "
                  f"shakl zondi ko'rmadi) -> tekshirilmadi deb sanaladi")
            return UNVERIFIABLE
        if d == rs.IX_DEF_UNREADABLE:
            return UNVERIFIABLE
        if d != rs.IX_DEF_OK:
            _cache[key] = (now, BAD)
            return BAD
    _cache[key] = (now, OK)
    return OK


def index_healthy(bind, index: str, table: str, *,
                  schema: str = "public") -> bool:
    """Kafolat ISBOTLANDIMI. «Tekshirib bo'lmadi» -> `False` (fail-closed)."""
    return index_state(bind, index, table, schema=schema) == OK


def require_index(db, index: str, table: str, *, operation: str,
                  schema: str = "public") -> None:
    """Kafolat isbotlanmasa 409 bilan FAIL-CLOSED.

    ⚠️  CHAQIRUVCHIGA OGOHLANTIRISH: bu `HTTPException` ko'taradi. Uni
        `except HTTPException` bilan yutadigan yo'lga qo'ymang — `cutover_guard`
        ning `dry_run`/custody shoxi shunday yutadi va gard JIM o'chib qolardi.
    """
    state = index_state(_bind_of(db), index, table, schema=schema)
    if state == OK:
        return
    # ⚠️  MATNGA obyekt nomi QO'SHILMAYDI: javob do'kon xodimiga ketadi va sxema
    #     ichki tuzilishini oshkor qilishi shart emas. Nom — JURNALDA.
    print(f"[schema] YOZUV RAD ETILDI ({operation}): "
          f"{schema}.{index} ({table}) holati={state}")
    raise HTTPException(
        409,
        f"{SCHEMA_GUARANTEE_MISSING}: Baza indeksi tayyor emas — takror yozuvdan "
        "himoya ishlamayapti, shu bois amal BAJARILMADI. Administrator sxemani "
        "tuzatgach qaytadan urinib ko'ring.",
        headers=EC.headers(SCHEMA_GUARANTEE_MISSING),
    )
