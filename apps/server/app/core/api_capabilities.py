# -*- coding: utf-8 -*-
"""API QOBILIYAT DARAJASI — server O'ZI e'lon qiladigan shartnoma versiyasi.

NEGA KERAK: uy qoidasi «AVVAL SERVER, KEYIN KLIENT» (CLAUDE.md). Lekin telefon
ilovasi (Android / PWA) o'rnatilgach, uni QAYSI serverga ulanishini biz emas,
operator hal qiladi — ya'ni YANGI mijoz ESKI serverga urilishi MUMKIN.

Production `99b1da7` da `/auth/context`, `/products/scan`, `/cash/custody-preview`,
sahifalangan `/products` (`X-Total-Count`), `/sales/{id}/receipt`,
`/receiving/{id}/corrections` va `X-Error-Code` YO'Q. O'sha serverga qarshi
mijoz: skanerlashda 422 olib operatorni AYBLAYDI, `/products` sahifalashda
`hasMore` hech qachon `false` bo'lmaydi (tugamaydigan takror), chek va tuzatish
ekranlari 404 beradi. Bularning HECH BIRI operatorga «server eski» demaydi.

YECHIM: `GET /health` javobiga BITTA blok — `{"level": N, "features": [...]}`.
Eski server bu blokni umuman yubormaydi va mijoz uni `level 0`, qobiliyatsiz deb
o'qiydi — mijozda ALOHIDA HOLAT kerak emas.

⚠️  SHA EMAS, DARAJA. `build.commit` — tartibsiz identifikator, platforma
    bermasa `None` (`health.build_info`). Daraja esa MONOTON: faqat o'sadi.

QOIDALAR (`tests/test_capability_gate.py` ushlab turadi):
  * `LEVEL_FEATURES` — «shu darajada QO'SHILGAN» nomlar. Qator O'CHIRILMAYDI va
    o'zgartirilmaydi; yangi qobiliyat — YANGI daraja. Qobiliyat olib tashlash
    mijozlar uchun buzuvchi va sinov uni yiqitadi.
  * Nom — QOBILIYAT nomi, marshrut EMAS: marshrutlar o'zgaradi, shartnoma esa
    barqaror qoladi (va ochiq endpointda ichki yo'llar oshkor bo'lmaydi).
  * O'YLAB TOPILGAN QOBILIYAT YO'Q: har nom AYNAN shu SHA da mavjud marshrutga
    (yoki `error_codes` kabi o'lchanadigan xatti-harakatga) mos keladi.
  * Bu modul na bazani, na ilovani import qiladi — `/health` ARZON va BAZASIZ
    qolishi shart (tiriklik tekshiruvi).
"""
from __future__ import annotations

# Har daraja — OLDINGISINING USTIGA. Bu yerda faqat O'SHA darajada qo'shilgan
# nomlar turadi; yakuniy ro'yxat — birlashma (`features`).
#
# 1-daraja (Phase 5G + 5G.1): mobil/PWA mijoz tayangan hamma narsa. Aynan shular
# production `99b1da7` da YO'Q.
LEVEL_FEATURES: dict[int, tuple[str, ...]] = {
    1: (
        "auth_context",            # GET /auth/context — kim, ruxsatlar, filiallar
        "cash_custody_preview",    # GET /cash/custody-preview — pul manbai bloki
        "error_codes",             # X-Error-Code + CORS expose_headers (brauzer o'qiy olsin)
        "products_paging",         # GET /products?limit&offset + X-Total-Count
        "products_scan",           # GET /products/scan — shtrix-kod / tarozi etiketkasi
        "receiving_corrections",   # POST /receiving/{id}/corrections — qabulni tuzatish
        "sale_receipt",            # GET /sales|returns/{id}/receipt — server chek DTO'si
    ),
}

#: Shu kod e'lon qiladigan eng yuqori daraja.
API_LEVEL: int = max(LEVEL_FEATURES)


def features(level: int = API_LEVEL) -> list[str]:
    """[level] gacha (shu daraja ham) to'plangan qobiliyat nomlari, barqaror tartibda.

    `features(0)` — BO'SH: 0 «server hech narsa e'lon qilmadi» degani (eski server).
    """
    out: set[str] = set()
    for lv, names in LEVEL_FEATURES.items():
        if lv <= level:
            out.update(names)
    return sorted(out)


def declaration() -> dict:
    """`GET /health` javobidagi `api` bloki. Sir YO'Q, baza YO'Q, hisob-kitob YO'Q."""
    return {"level": API_LEVEL, "features": features()}
