# -*- coding: utf-8 -*-
"""NAKLADNOY RASMI DARVOZASI — tur tekshiruvi, o'lcham chegarasi, EXIF/GPS tozalash.

NIMA UCHUN SERVER TOMONDA. Rasm tashqi AI provayderiga YUBORILADI, ya'ni u do'kon
nazoratidan chiqadi. Mijozga ishonib bo'lmaydi:
  · mobil (`image_capture.dart:32`) `imageQuality: 70` bilan JPEG ga qayta kodlaydi,
    LEKIN `:35` da `f.mimeType` ni O'ZI qanday bo'lsa uzatadi — ya'ni e'lon qilingan
    tur `image/heic` bo'lib, baytlar JPEG bo'lishi mumkin;
  · desktop (`Purchases.tsx:1233`) `f.type || "image/jpeg"` yuboradi — bu brauzer
    bergan qiymat va foydalanuvchi ISTALGAN faylni tanlashi mumkin;
  · web qurilishida `image_picker_for_web` `imageQuality` ni UMUMAN e'tiborsiz
    qoldiradi (`image_capture.dart:11`, audit B6) — ya'ni asl fayl o'zgarmasdan keladi.
Shu bois tur FAQAT BAYTLARDAN aniqlanadi (`sniff`), e'lon qilingan `media_type`
esa faqat diagnostika uchun.

NEGA PILLOW ISHLATILMAYDI. `pyproject.toml` da `pillow>=11.3` BOR, lekin bu modul
uni TALAB QILMAYDI: EXIF tozalash JPEG segment va PNG chunk darajasida bajariladi —
bu standart kutubxona bilan to'liq yechiladigan, deterministik va sinovdan
o'tkazilishi oson ish. Qo'shimcha bog'liqlik kiritmaslik — ataylab.

⚠️  TOZALASH «QAYTA KODLASH» EMAS. Piksellar TEGILMAYDI: biz faqat metama'lumot
    tashuvchi segmentlarni OLIB TASHLAYMIZ. Shu bois AI o'qish aniqligi
    o'zgarmaydi va jim buzilish (silent corruption) xavfi yo'q.
"""
from __future__ import annotations

import struct

# ── CHEGARALAR ───────────────────────────────────────────────────────────────
#  Nakladnoy — matnli hujjat: 1800px (mobil `maxWidth: 1800`) dan kattasi AI
#  aniqligiga hech narsa qo'shmaydi, lekin narx va xotira to'lovini oshiradi.
MAX_BYTES = 10 * 1024 * 1024          # tozalangan baytlar uchun yuqori chegara
MAX_SIDE = 6000                        # har tomon uchun piksel chegarasi
MIN_SIDE = 16                          # bundan kichigi hujjat bo'lishi mumkin emas

JPEG = "image/jpeg"
PNG = "image/png"
SUPPORTED = (JPEG, PNG)

# `sniff` aniqlay oladigan, LEKIN qabul QILINMAYDIGAN turlar — xato matni aniq
# bo'lsin (operator «nega ishlamadi» deb qolmasin).
_ANIQLANADI_LEKIN_QABUL_QILINMAYDI = {
    "image/heic": "HEIC/HEIF",
    "image/webp": "WebP",
    "image/gif": "GIF",
    "application/pdf": "PDF",
}


class ImageRejected(ValueError):
    """Rasm qabul qilinmadi — matn OPERATORGA ATAYLAB yozilgan ko'rsatma.

    ⚠️  NOMLANGAN DOMEN ISTISNOSI (`CorrectionError`/`ResolutionError` bilan AYNI
        naqsh). Matn SHU YERDA, server kodida yoziladi va mijoz lug'atiga
        tushadi (`packages/shared/src/lib/serverErrorsLots.ts`); u ichki
        istisnodan, kutubxonadan yoki provayderdan KELMAYDI. Shu bois
        chaqiruvchi uni `str(e)` bilan uzatishi mumkin —
        `tests/test_lot_error_texts.py` ni ko'r: `DOMAIN`, `RAISERS`, `SOURCES`.

    ⚠️  HAR BIR MATN OPERATOR BAJARA OLADIGAN AMALNI aytadi: boshqa format
        tanlash, qayta suratga olish yoki kichikroq rasm yuborish. Fayl
        mazmuni, bayt bo'lagi va ichki tafsilot xabarga TUSHMAYDI.

    ⚠️  MATN QAT'IY (o'rin-belgisiz) — MIJOZDA TARJIMA QILINISHI UCHUN (CH-17A).
        Mobil tarjimon `errors.dart:_translateKnown` AYNIY mos kelishni va
        `"PREFIKS: qolgan matn"` bo'linishini biladi; REGEX ni BILMAYDI. Shu
        bois o'lcham raqamlari matndan OLIB TASHLANDI (ular operator uchun amal
        emas), format nomi esa PREFIKS qilindi (`"HEIC/HEIF: ..."`) — shunda
        ru/ky foydalanuvchisi o'zbekcha matn ko'rib qolmaydi.
    """


def sniff(data: bytes) -> str | None:
    """Turni FAQAT baytlardan aniqlaydi. Noma'lum bo'lsa `None`."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return PNG
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF: ISO-BMFF `ftyp` qutisi, brendi heic/heix/hevc/mif1/msf1
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"hevx",
                                               b"mif1", b"msf1"):
        return "image/heic"
    return None


def dimensions(data: bytes, kind: str) -> tuple[int, int]:
    """(kenglik, balandlik). Sarlavhadan o'qiladi — rasm DEKODLANMAYDI."""
    if kind == PNG:
        # Signature(8) + LEN(4) + "IHDR"(4) -> kenglik, balandlik (big-endian)
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ImageRejected("Rasm sarlavhasi buzuq — qayta suratga oling")
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    # JPEG: SOF segmentini topamiz (progressive/arifmetik variantlari ham)
    SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
           0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:                      # SOS — sarlavhalar tugadi
            break
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in SOF:
            if i + 9 > n:
                break
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    raise ImageRejected("Rasm sarlavhasi buzuq — qayta suratga oling")


# ── JPEG: metama'lumot tashuvchi segmentlarni OLIB TASHLASH ─────────────────
#  APP0 (JFIF) QOLDIRILADI — u faqat zichlik/versiya, shaxsiy ma'lumot tashimaydi
#  va ba'zi dekoderlar uni kutadi. APP1..APP15 (EXIF, XMP, IPTC, Photoshop) va
#  COM (izoh) OLIB TASHLANADI: GPS koordinatasi, qurilma seriyasi, egasining ismi
#  va qo'lda yozilgan izohlar AYNAN shu yerda yashaydi.
_JPEG_TASHLANADI = set(range(0xE1, 0xF0)) | {0xFE}       # APP1..APP15 + COM


def _jpeg_tozalash(data: bytes) -> bytes:
    out = bytearray(data[:2])                 # SOI
    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            # Segment tuzilishi buzildi — qolganini o'zgartirmasdan ko'chiramiz
            out += data[i:]
            return bytes(out)
        marker = data[i + 1]
        if marker == 0xDA:                    # SOS: qolgani — entropiya ma'lumoti
            out += data[i:]
            return bytes(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg_end = i + 2 + seg_len
        if marker not in _JPEG_TASHLANADI:
            out += data[i:seg_end]
        i = seg_end
    out += data[i:]
    return bytes(out)


# ── PNG: faqat RUXSAT BERILGAN chunk'lar qoldiriladi ───────────────────────
#  Ruxsat ro'yxati (allowlist), inkor ro'yxati EMAS: kelajakda yangi
#  metama'lumot chunk turi paydo bo'lsa, u AVTOMATIK tashlanadi.
_PNG_RUXSAT = {
    b"IHDR", b"PLTE", b"IDAT", b"IEND",       # kritik
    b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"bKGD", b"pHYs", b"sBIT",
}
#  Tashlanadi (ro'yxatda yo'q): eXIf, tEXt, iTXt, zTXt, tIME, dSIG, ...


def _png_tozalash(data: bytes) -> bytes:
    out = bytearray(data[:8])                 # signature
    i = 8
    n = len(data)
    while i + 8 <= n:
        ln = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        nxt = i + 12 + ln                     # LEN + TYPE + DATA + CRC
        if nxt > n:
            break                             # buzuq oxiri — tashlanadi
        if ctype in _PNG_RUXSAT:
            out += data[i:nxt]
        i = nxt
        if ctype == b"IEND":
            break
    return bytes(out)


def sanitize(raw: bytes, declared: str | None = None) -> tuple[bytes, str]:
    """Tekshiradi, chegaralarni qo'llaydi va metama'lumotni olib tashlaydi.

    `(tozalangan_baytlar, haqiqiy_media_type)` qaytaradi.
    Rad etilsa `ImageRejected` — matni operatorga ko'rsatish uchun yozilgan.
    `declared` FAQAT diagnostika uchun: qaror BAYTLAR bo'yicha qabul qilinadi.
    """
    if not raw:
        raise ImageRejected("Rasm bo'sh — qayta suratga oling")
    kind = sniff(raw)
    if kind is None:
        raise ImageRejected("Fayl turi aniqlanmadi — JPEG yoki PNG rasm tanlang")
    if kind not in SUPPORTED:
        nom = _ANIQLANADI_LEKIN_QABUL_QILINMAYDI.get(kind, kind)
        raise ImageRejected(f"{nom}: bu rasm turi qo'llab-quvvatlanmaydi — "
                            f"JPEG yoki PNG rasm tanlang")
    w, h = dimensions(raw, kind)
    if w < MIN_SIDE or h < MIN_SIDE:
        raise ImageRejected("Rasm juda kichik — nakladnoy o'qilmaydi")
    if w > MAX_SIDE or h > MAX_SIDE:
        raise ImageRejected("Rasm juda katta — kichikroq rasm yuboring")
    clean = _jpeg_tozalash(raw) if kind == JPEG else _png_tozalash(raw)
    if len(clean) > MAX_BYTES:
        raise ImageRejected("Rasm hajmi juda katta — kichikroq rasm yuboring")
    return clean, kind
