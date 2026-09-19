# -*- coding: utf-8 -*-
"""Chek logosi — qabul qilish, tekshirish, termal rastrga aylantirish (Phase 5F).

⚠️  ISHONCHSIZ KIRISH. Rasm fayli — dekoder hujumlarining klassik kirish nuqtasi:
    dekompressiya bombasi (90 KB PNG → 400M piksel), animatsiya (har kadr alohida
    dekodlanadi), soxta kengaytma, polyglot (PNG + HTML). Shu bois:
      · format FAQAT sehrli baytlardan aniqlanadi (fayl nomi / e'lon qilingan MIME
        e'tiborga olinmaydi) va Pillow ham FAQAT o'sha dekoder bilan ochadi;
      · o'lcham DEKODLASHDAN OLDIN sarlavhadan o'qiladi;
      · Pillow ogohlantirishlari (DecompressionBombWarning) XATOGA aylantiriladi;
      · original bayt HECH QACHON qaytarilmaydi — mijoz faqat rastrdan QAYTA
        kodlangan 1-bit PNG va rastrni ko'radi (metama'lumot, dum yuk yo'q).
⚠️  BIR MARTA. Qayta ishlash (EXIF burilish → oq fonga kompozit → kulrang →
    LANCZOS → Floyd–Steinberg) yuklashda bajariladi va natija qatorda keshlanadi:
    kassa har chop etishda rasmni qayta dekodlamaydi va natija DETERMINISTIK.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
import warnings
from dataclasses import dataclass
from io import BytesIO

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.receipt import errors as E

MAX_BYTES = 2 * 1024 * 1024
MAX_B64_CHARS = 2_900_000            # 2 MiB base64 ≈ 2.8M belgi — dekodlashdan OLDIN kesamiz
MAX_SIDE = 4096
MAX_PIXELS = 16_777_216
MIN_SIDE = 16
MAX_UPSCALE = 2.0
# Qog'oz kengligi → logo qutisi (nuqta): 58 mm = 384 nuqta, 80 mm = 576 (logo 512 gacha).
BOXES: dict[int, tuple[int, int]] = {58: (384, 160), 80: (512, 200)}

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_DATA_URI = re.compile(r"^data:[A-Za-z0-9.+/-]{0,40};base64,")
# PIL "1" rejimi: 1 = OQ. ESC/POS rastri: 1 = QORA — har bayt teskari.
_INVERT = bytes(255 - i for i in range(256))


def _bad(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(status, msg)


def decode_b64(data_b64) -> bytes:
    """Qat'iy base64 (validate=True). `data:<mime>;base64,` prefiksi e'tiborsiz olinadi —
    e'lon qilingan MIME baribir ishlatilmaydi."""
    if not isinstance(data_b64, str):
        raise _bad(E.LOGO_CORRUPT)
    if len(data_b64) > MAX_B64_CHARS:
        raise _bad(E.LOGO_TOO_LARGE)
    s = _DATA_URI.sub("", data_b64, count=1)
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise _bad(E.LOGO_CORRUPT) from None
    if len(raw) > MAX_BYTES:
        raise _bad(E.LOGO_TOO_LARGE)
    return raw


def sniff(raw: bytes) -> tuple[str, str]:
    """(Pillow format nomi, MIME) — FAQAT sehrli baytlar bo'yicha."""
    if raw.startswith(_PNG):
        return "PNG", "image/png"
    if raw.startswith(_JPEG):
        return "JPEG", "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP", "image/webp"
    raise _bad(E.LOGO_BAD_FORMAT)


@dataclass(frozen=True)
class Variant:
    width: int          # nuqta, 8 ga karrali (rastr qatori to'liq baytlar)
    height: int
    raster: bytes       # qadoqlangan 1-bit, qatorma-qator, MSB birinchi, 1 = QORA
    png: bytes          # AYNAN shu rastrning 1-bit PNG'si (printer chop etadigan narsa)


@dataclass(frozen=True)
class Processed:
    fmt: str
    mime: str
    width: int
    height: int
    variants: dict[int, Variant]


def _to_gray(img):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(img)
    if img.mode.startswith("I") or img.mode == "F":
        # 16-bit kulrang PNG (0..65535) — to'g'ridan-to'g'ri "L" ga o'girish 255 ga
        # kesib, deyarli oq rasm berardi.
        img = img.convert("I").point(lambda v: v / 257)
    if img.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    return img.convert("L")


def _variant(gray, box: tuple[int, int]) -> Variant:
    from PIL import Image
    bw, bh = box
    w, h = gray.size
    scale = min(bw / w, bh / h, MAX_UPSCALE)
    nw = min(bw, max(1, round(w * scale)))
    nh = min(bh, max(1, round(h * scale)))
    resized = gray if (nw, nh) == (w, h) else gray.resize((nw, nh), Image.Resampling.LANCZOS)
    mono = resized.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    pw = (nw + 7) // 8 * 8
    # Yangi, metama'lumotsiz tuval: kenglik 8 ga karrali, rasm o'rtada, chetlar OQ.
    canvas = Image.new("1", (pw, nh), 1)
    canvas.paste(mono, ((pw - nw) // 2, 0))
    raster = canvas.tobytes().translate(_INVERT)
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return Variant(pw, nh, raster, buf.getvalue())


def process(raw: bytes) -> Processed:
    """Tekshiradi va ikkala qog'oz kengligi uchun rastr quradi. Xato — 400."""
    from PIL import Image
    fmt, mime = sniff(raw)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        # 1-bosqich: faqat SARLAVHA (o'lcham, kadrlar) + verify — piksel dekodlanmaydi.
        try:
            img = Image.open(BytesIO(raw), formats=[fmt])
        except Exception:                      # noqa: BLE001 — Pillow istisnolari xilma-xil
            raise _bad(E.LOGO_CORRUPT) from None
        try:
            if img.format != fmt:
                raise _bad(E.LOGO_CORRUPT)
            w, h = img.size
            if w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
                raise _bad(E.LOGO_DIMENSIONS)
            if w < MIN_SIDE or h < MIN_SIDE:
                raise _bad(E.LOGO_TOO_SMALL)
            if getattr(img, "n_frames", 1) > 1:
                raise _bad(E.LOGO_ANIMATED)
            img.verify()
        except HTTPException:
            raise
        except Exception:                      # noqa: BLE001
            raise _bad(E.LOGO_CORRUPT) from None
        finally:
            img.close()
        # 2-bosqich: verify'dan keyin obyekt yaroqsiz — QAYTA ochib to'liq dekodlaymiz.
        try:
            with Image.open(BytesIO(raw), formats=[fmt]) as img:
                img.load()
                gray = _to_gray(img)
                variants = {k: _variant(gray, box) for k, box in BOXES.items()}
        except HTTPException:
            raise
        except Exception:                      # noqa: BLE001
            raise _bad(E.LOGO_CORRUPT) from None
    return Processed(fmt, mime, w, h, variants)


def logo_uuid(company_id, branch_id, sha256: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"binos-logo:{company_id}:{branch_id or '-'}:{sha256}")


def store_logo(db: Session, emp, branch_id, raw: bytes):
    """(qator, yangi_mi). COMMIT QILMAYDI. Ayni fayl ayni doirada — ayni qator (takror)."""
    from app.models.receipt import ReceiptLogo
    sha = hashlib.sha256(raw).hexdigest()
    lid = logo_uuid(emp.company_id, branch_id, sha)
    existing = db.get(ReceiptLogo, lid)
    if existing is not None:
        return existing, False
    p = process(raw)
    v58, v80 = p.variants[58], p.variants[80]
    row = ReceiptLogo(
        id=lid, company_id=emp.company_id, branch_id=branch_id, sha256=sha, mime=p.mime,
        width=p.width, height=p.height, byte_size=len(raw), original=raw,
        raster58=v58.raster, raster58_w=v58.width, raster58_h=v58.height,
        raster80=v80.raster, raster80_w=v80.width, raster80_h=v80.height,
        png58=v58.png, png80=v80.png, created_by=emp.id)
    sp = db.begin_nested()
    try:
        db.add(row)
        db.flush()
        sp.commit()
    except IntegrityError:
        # Ayni fayl parallel yuklandi — PK to'qnashuvi; g'olib qator takror sifatida qaytadi.
        sp.rollback()
        existing = db.get(ReceiptLogo, lid)
        if existing is None:
            raise
        return existing, False
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "receipt_logo", lid,
              after={"sha256": sha, "branch_id": str(branch_id) if branch_id else None,
                     "mime": p.mime, "byte_size": len(raw)})
    return row, True


def accessible_logo(db: Session, company_id, scope_branch_id, logo_id):
    """Doiraga ruxsat etilgan logo yoki None (yo'q / begona / boshqa filialniki)."""
    from app.models.receipt import ReceiptLogo
    from app.services.receipt.settings import logo_allowed, parse_uuid
    lid = parse_uuid(logo_id)
    if lid is None:
        return None
    row = db.get(ReceiptLogo, lid)
    if row is None or not logo_allowed(row.company_id, row.branch_id, company_id, scope_branch_id):
        return None
    return row


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def variants_out(row) -> dict:
    return {
        "58": {"width": row.raster58_w, "height": row.raster58_h,
               "png_data_uri": "data:image/png;base64," + _b64(row.png58),
               "raster_b64": _b64(row.raster58)},
        "80": {"width": row.raster80_w, "height": row.raster80_h,
               "png_data_uri": "data:image/png;base64," + _b64(row.png80),
               "raster_b64": _b64(row.raster80)},
    }


def logo_out(row) -> dict:
    return {"id": str(row.id), "sha256": row.sha256, "mime": row.mime, "width": row.width,
            "height": row.height, "byte_size": row.byte_size,
            "branch_id": str(row.branch_id) if row.branch_id else None,
            "variants": variants_out(row)}
