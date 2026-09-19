# -*- coding: utf-8 -*-
"""PHASE 5F — CHEK LOGOSI (`POST /receipt/logos`, `GET /receipt/logos/{id}`).

Barcha rasmlar SINOV ICHIDA Pillow bilan yasaladi (repoda ikkilik fayl yo'q).

Isbotlanadi:
  · format FAQAT sehrli baytlardan: PNG/JPEG/WebP qabul; GIF, BMP, SVG matni rad;
  · dekoder hujumlari: 20000×20000 1-bit PNG bombasi (90 KB), animatsiya (APNG, WebP),
    kesilgan PNG, «PNG sarlavhasi + HTML», noto'g'ri base64, > 2 MiB — hammasi 400;
  · polyglot (haqiqiy PNG + HTML dumi) qabul qilinadi, LEKIN mijozga faqat rastrdan
    QAYTA kodlangan PNG boradi — dum yuk, metama'lumot va original bayt HECH QACHON;
  · qayta ishlash: EXIF burilish, shaffoflik → oq, 2× dan ortiq kattalashtirmaslik,
    kenglik 8 ga karrali, rastr == PNG (1 = qora), deterministik;
  · CPU/xotira: 2048×2048 chegarasi, ko'p skanli progressiv JPEG dekodlashsiz tez rad,
    JPEG `draft` masshtabi, jarayon semafori (band — 503), dekodlash paytida DB
    tranzaksiyasi ochiq emas;
  · takror yuklash — ayni id (uuid5), 200 `duplicate: true`;
  · doira: kompaniya logosi faqat cheklovsiz xodim, filial logosi faqat ko'rinadigan
    filial; sozlama `logo_id` havolasi qoidasi; o'qish izolyatsiyasi.
"""
import base64
import hashlib
import io
import os
import struct
import time
import uuid

import pytest
from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.services.receipt import errors as E
from app.services.receipt import logo as RL
from tests.test_receipt_settings import _asosiy, _db, _dokon, _put
from tests.test_sales_read_permissions import _filial, _xodim

URL = "/api/v1/receipt/logos"


# ── RASM YASASH ──────────────────────────────────────────────────────────────
def _save(img, fmt, **kw) -> bytes:
    b = io.BytesIO()
    img.save(b, fmt, **kw)
    return b.getvalue()


def _rgba_png(w=200, h=100) -> bytes:
    """Shaffof fon + o'rtada qora to'rtburchak."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((w // 4, h // 4, 3 * w // 4, 3 * h // 4), fill=(0, 0, 0, 255))
    return _save(img, "PNG")


def _rgb(w=120, h=60, color=(20, 20, 20)):
    img = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(img).rectangle((0, 0, w // 2, h - 1), fill=color)
    return img


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _up(client, h, raw=None, branch_id=None, data_b64=None):
    return client.post(URL, headers=h, json={
        "branch_id": branch_id, "data_b64": data_b64 if data_b64 is not None else _b64(raw)})


def _bit(raster: bytes, w: int, x: int, y: int) -> int:
    return (raster[y * (w // 8) + x // 8] >> (7 - x % 8)) & 1


def _variant_bytes(v):
    raster = base64.b64decode(v["raster_b64"])
    assert v["png_data_uri"].startswith("data:image/png;base64,")
    png = base64.b64decode(v["png_data_uri"].split(",", 1)[1])
    return raster, png


def _png_chunks(png: bytes) -> list[str]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    out, i = [], 8
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        out.append(png[i + 4:i + 8].decode("ascii"))
        i += 12 + n
    return out


@pytest.fixture(scope="module")
def m(client):
    ega = _dokon(client, name="QA logo do'koni")
    H = ega["h"]
    a1, a2 = _filial(client, H, "Logo A1"), _filial(client, H, "Logo A2")
    x = {"ega": ega,
         "administrator@A1": _xodim(client, H, "administrator", filial=a1),
         "menejer": _xodim(client, H, "menejer"),
         "menejer@A1": _xodim(client, H, "menejer", filial=a1),
         "kassir@A1": _xodim(client, H, "kassir", filial=a1)}
    begona = _dokon(client, plan="start", name="Begona logo do'koni")
    x["begona-ega"] = begona
    return {"x": x, "cid": ega["cid"], "a0": _asosiy(client, H), "a1": a1, "a2": a2,
            "begona_cid": begona["cid"]}


# ══ 1 · QABUL VA QAYTA ISHLASH ═══════════════════════════════════════════════
def test_PNG_shaffof_QABUL_rastr_PNG_mos_oq_fon_8_ga_karrali(client, m):
    raw = _rgba_png()
    r = _up(client, m["x"]["ega"]["h"], raw)
    assert r.status_code == 201, r.text
    b = r.json()
    assert set(b) == {"id", "sha256", "mime", "width", "height", "byte_size", "branch_id",
                      "variants", "duplicate"}
    assert b["duplicate"] is False and b["mime"] == "image/png" and b["branch_id"] is None
    assert (b["width"], b["height"], b["byte_size"]) == (200, 100, len(raw))
    assert b["sha256"] == hashlib.sha256(raw).hexdigest()
    assert b["id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, f"binos-logo:{m['cid']}:-:{b['sha256']}"))
    # 58 mm: quti 384×160 → 1.6× → 320×160; 80 mm: quti 512×200 → 2× → 400×200.
    assert (b["variants"]["58"]["width"], b["variants"]["58"]["height"]) == (320, 160)
    assert (b["variants"]["80"]["width"], b["variants"]["80"]["height"]) == (400, 200)
    for k, v in b["variants"].items():
        raster, png = _variant_bytes(v)
        w, h = v["width"], v["height"]
        assert w % 8 == 0 and len(raster) == w // 8 * h, k
        # PNG — AYNAN rastr (PIL "1": 1 = oq; rastr: 1 = qora).
        im = Image.open(io.BytesIO(png))
        assert im.size == (w, h) and im.mode == "1", k
        assert bytes(255 - c for c in im.tobytes()) == raster, k
        # Metama'lumotsiz: faqat IHDR/IDAT/IEND.
        assert set(_png_chunks(png)) == {"IHDR", "IDAT", "IEND"}, (k, _png_chunks(png))
        # Shaffof burchak — OQ (0), markaz — QORA (1).
        assert _bit(raster, w, 0, 0) == 0 and _bit(raster, w, w - 1, h - 1) == 0, k
        assert _bit(raster, w, w // 2, h // 2) == 1, k


def test_JPEG_WebP_QABUL(client, m):
    H = m["x"]["ega"]["h"]
    r = _up(client, H, _save(_rgb(), "JPEG", quality=90))
    assert r.status_code == 201 and r.json()["mime"] == "image/jpeg", r.text
    r = _up(client, H, _save(_rgb(130, 70), "WEBP", quality=90))
    assert r.status_code == 201 and r.json()["mime"] == "image/webp", r.text


def test_EXIF_burilishi_QOLLANADI(client, m):
    img = _rgb(300, 100)
    exif = Image.Exif()
    exif[0x0112] = 6                      # ko'rsatishda 90° burish
    r = _up(client, m["x"]["ega"]["h"], _save(img, "JPEG", exif=exif.tobytes(), quality=90))
    assert r.status_code == 201, r.text
    v = r.json()["variants"]["58"]
    # Burilgan 100×300: 160/300 → 53×160 → kenglik 56. Burilmasa 384×128 bo'lardi.
    assert (v["width"], v["height"]) == (56, 160)


def test_KICHIK_rasm_2x_dan_ORTIQ_kattalashtirilmaydi(client, m):
    r = _up(client, m["x"]["ega"]["h"], _save(_rgb(20, 20), "PNG"))
    assert r.status_code == 201, r.text
    for k in ("58", "80"):
        v = r.json()["variants"][k]
        assert (v["width"], v["height"]) == (40, 40), k


def test_16_bit_kulrang_PNG_OQ_bolib_qolmaydi():
    raw = _save(Image.new("I;16", (64, 64), 32768), "PNG")          # ~50% kulrang
    v = RL.process(raw).variants[58]
    ones = sum(bin(c).count("1") for c in v.raster)
    assert 0.3 < ones / (v.width * v.height) < 0.7, ones


def test_qayta_ishlash_DETERMINISTIK():
    raw = _save(_rgb(333, 111, (90, 90, 90)), "PNG")
    a, b = RL.process(raw), RL.process(raw)
    assert a.variants == b.variants


def test_TAKROR_yuklash_AYNI_id_200_duplicate_filial_boshqa_id(client, m):
    H = m["x"]["ega"]["h"]
    raw = _save(_rgb(90, 45, (10, 10, 10)), "PNG")
    r1 = _up(client, H, raw)
    r2 = _up(client, H, data_b64="data:image/png;base64," + _b64(raw))   # data-URI prefiksi ham
    assert (r1.status_code, r2.status_code) == (201, 200), (r1.text, r2.text)
    assert r2.json()["duplicate"] is True and r2.json()["id"] == r1.json()["id"]
    r3 = _up(client, H, raw, branch_id=m["a1"])
    assert r3.status_code == 201 and r3.json()["id"] != r1.json()["id"]
    assert r3.json()["branch_id"] == m["a1"]


def test_AUDIT_logo_yaratish(client, m):
    from app.models.sync import AuditLog
    r = _up(client, m["x"]["ega"]["h"], _save(_rgb(77, 33), "PNG"))
    assert r.status_code == 201
    with _db() as db:
        a = db.query(AuditLog).filter(AuditLog.entity == "receipt_logo",
                                      AuditLog.entity_id == uuid.UUID(r.json()["id"])).one()
    assert a.action == "create" and a.after["sha256"] == r.json()["sha256"]


# ══ 2 · RAD ETISH ════════════════════════════════════════════════════════════
def _bomb() -> bytes:
    return _save(Image.new("1", (20000, 20000), 1), "PNG")


def _animated(fmt) -> bytes:
    frames = [Image.new("RGB", (32, 32), (i * 60, 0, 0)) for i in range(3)]
    return _save(frames[0], fmt, save_all=True, append_images=frames[1:])


RAD = {
    "gif": (lambda: _save(_rgb(), "GIF"), E.LOGO_BAD_FORMAT),
    "bmp": (lambda: _save(_rgb(), "BMP"), E.LOGO_BAD_FORMAT),
    "svg": (lambda: b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                    b'<script>alert(1)</script></svg>', E.LOGO_BAD_FORMAT),
    "bo'sh": (lambda: b"", E.LOGO_BAD_FORMAT),
    "png-sarlavha+html": (lambda: b"\x89PNG\r\n\x1a\n<html><script>alert(1)</script></html>",
                          E.LOGO_CORRUPT),
    "kesilgan-png": (lambda: (lambda b: b[: len(b) // 2])(_save(_rgb(400, 300), "PNG")),
                     E.LOGO_CORRUPT),
    "kesilgan-jpeg": (lambda: _save(_rgb(400, 300), "JPEG")[:500], E.LOGO_CORRUPT),
    "bomba-20000": (_bomb, E.LOGO_CORRUPT),
    "5000x5000": (lambda: _save(Image.new("1", (5000, 5000), 1), "PNG"), E.LOGO_DIMENSIONS),
    "3000x3000": (lambda: _save(Image.new("1", (3000, 3000), 1), "PNG"), E.LOGO_DIMENSIONS),
    "3000x3000-jpeg": (lambda: _save(Image.new("L", (3000, 3000), 255), "JPEG"), E.LOGO_DIMENSIONS),
    "2049-keng": (lambda: _save(Image.new("L", (2049, 16), 255), "PNG"), E.LOGO_DIMENSIONS),
    "2049-baland": (lambda: _save(Image.new("L", (16, 2049), 255), "PNG"), E.LOGO_DIMENSIONS),
    "4097-keng": (lambda: _save(Image.new("L", (4097, 16), 255), "PNG"), E.LOGO_DIMENSIONS),
    "4097-baland": (lambda: _save(Image.new("L", (16, 4097), 255), "PNG"), E.LOGO_DIMENSIONS),
    "15-kichik": (lambda: _save(Image.new("L", (15, 100), 255), "PNG"), E.LOGO_TOO_SMALL),
    "apng": (lambda: _animated("PNG"), E.LOGO_ANIMATED),
    "webp-animatsiya": (lambda: _animated("WEBP"), E.LOGO_ANIMATED),
    "katta-2MiB": (lambda: b"\x89PNG\r\n\x1a\n" + os.urandom(2 * 1024 * 1024), E.LOGO_TOO_LARGE),
}


@pytest.mark.parametrize("nom", list(RAD))
def test_RAD_ETILADI_bazaga_HECH_NARSA_yozilmaydi(client, m, nom):
    from app.models.receipt import ReceiptLogo
    make, msg = RAD[nom]
    with _db() as db:
        before = db.query(ReceiptLogo).count()
    r = _up(client, m["x"]["ega"]["h"], make())
    assert r.status_code == 400, (nom, r.text)
    assert r.json() == {"detail": msg}, nom
    with _db() as db:
        assert db.query(ReceiptLogo).count() == before


def test_16x16_CHEGARA_qabul_2048x2048_sarlavha_ruxsat():
    assert RL.process(_save(Image.new("L", (16, 16), 0), "PNG")).width == 16
    # 2048×2048 = aynan 4 194 304 piksel — chegarada (dekodlash ham o'tadi).
    assert (RL.MAX_SIDE, RL.MAX_PIXELS) == (2048, 2048 * 2048)
    p = RL.process(_save(Image.new("1", (2048, 2048), 1), "PNG"))
    assert (p.width, p.height) == (2048, 2048)
    assert E.LOGO_DIMENSIONS == "Logo o'lchami juda katta (ko'pi bilan 2048×2048 piksel)"


# ══ 2b · CPU / XOTIRA CHEGARASI (bitta jarayon — barcha do'konlar) ═══════════
def _jpeg_segments(raw: bytes) -> list[tuple[int, int, int]]:
    """(marker, boshi, oxiri) — SOS entropiya ma'lumoti keyingi markergacha."""
    out, i = [], 2
    while i < len(raw):
        m = raw[i + 1]
        if m == 0xD9:
            out.append((m, i, i + 2))
            break
        end = i + 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
        if m == 0xDA:
            while not (raw[end] == 0xFF and raw[end + 1] != 0x00
                       and not 0xD0 <= raw[end + 1] <= 0xD7):
                end += 1
        out.append((m, i, end))
        i = end
    return out


def _kop_skanli_jpeg(side: int, takror: int) -> bytes:
    """Haqiqiy progressiv JPEG + oxirgi skan `takror` marta qayta — libjpeg har skanni
    butun koeffitsiyent buferi bo'ylab qayta ishlaydi (ogohlantirish, xato emas)."""
    raw = _save(Image.new("L", (side, side), 255), "JPEG", progressive=True, quality=90)
    sos = [s for s in _jpeg_segments(raw) if s[0] == 0xDA]
    assert 2 <= len(sos) < 20, len(sos)                # oddiy progressiv fayl — bir necha skan
    _, a, b = sos[-1]
    return raw[:b] + raw[a:b] * takror + b"\xff\xd9"


def test_KOP_SKANLI_progressiv_JPEG_TEZ_rad_etiladi(client, m):
    """~70 KB, 3006 skan, 2048×2048: chegarasiz dekodlash ~13 s CPU (2 MB fayl — daqiqalar)
    va logo QABUL qilinardi. Skanlar dekodlashdan OLDIN sanaladi."""
    from app.models.receipt import ReceiptLogo
    raw = _kop_skanli_jpeg(2048, 3000)
    assert raw.count(b"\xff\xda") > RL.MAX_JPEG_SCANS and len(raw) < 100_000
    with _db() as db:
        before = db.query(ReceiptLogo).count()
    t0 = time.perf_counter()
    r = _up(client, m["x"]["ega"]["h"], raw)
    dt = time.perf_counter() - t0
    assert r.status_code == 400 and r.json() == {"detail": E.LOGO_CORRUPT}, r.text
    assert dt < 2.0, dt
    with _db() as db:
        assert db.query(ReceiptLogo).count() == before


def test_SKAN_chegarasi_64_QABUL_65_RAD_oddiy_progressiv_QABUL(client, m):
    ok = _kop_skanli_jpeg(64, 0)
    k = ok.count(b"\xff\xda")
    assert RL.process(ok).width == 64
    assert RL.process(_kop_skanli_jpeg(64, RL.MAX_JPEG_SCANS - k)).width == 64
    with pytest.raises(HTTPException) as e:
        RL.process(_kop_skanli_jpeg(64, RL.MAX_JPEG_SCANS - k + 1))
    assert e.value.status_code == 400 and e.value.detail == E.LOGO_CORRUPT
    # Oddiy (Pillow yozgan) progressiv JPEG — API orqali qabul.
    r = _up(client, m["x"]["ega"]["h"],
            _save(_rgb(180, 90, (40, 40, 40)), "JPEG", progressive=True, quality=85))
    assert r.status_code == 201 and r.json()["mime"] == "image/jpeg", r.text


def test_JPEG_KICHRAYTIRILGAN_masshtabda_dekodlanadi(monkeypatch):
    """`draft`: 2048×2048 JPEG 512×512 da dekodlanadi (xotira 16× kam); natija o'lchami
    to'liq masshtabdagidek."""
    from PIL import JpegImagePlugin
    seen = []
    orig = JpegImagePlugin.JpegImageFile.load

    def spy(self):
        seen.append(self.size)
        return orig(self)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", spy)
    p = RL.process(_save(_rgb(2048, 2048), "JPEG", quality=80))
    assert (p.width, p.height) == (2048, 2048)
    assert seen and seen[-1] == (512, 512), seen
    assert (p.variants[80].width, p.variants[80].height) == (200, 200)
    assert (p.variants[58].width, p.variants[58].height) == (160, 160)


def test_DEKODLASH_joylari_BAND_503_hech_narsa_yozilmaydi(client, m, monkeypatch):
    from app.models.receipt import ReceiptLogo
    monkeypatch.setattr(RL, "SLOT_WAIT_S", 0.2)
    H = m["x"]["ega"]["h"]
    dup = _save(_rgb(88, 44, (1, 1, 1)), "PNG")
    assert _up(client, H, dup).status_code == 201
    with _db() as db:
        before = db.query(ReceiptLogo).count()
    taken = 0
    try:
        while RL._SLOTS.acquire(blocking=False):
            taken += 1
        assert taken == RL.DECODE_SLOTS == 2
        r = _up(client, H, _save(_rgb(89, 45, (2, 2, 2)), "PNG"))
        assert r.status_code == 503 and r.json() == {"detail": E.LOGO_BUSY}, r.text
        # Takror yuklash dekodlanmaydi — band bo'lsa ham javob beradi.
        d = _up(client, H, dup)
        assert d.status_code == 200 and d.json()["duplicate"] is True
    finally:
        for _ in range(taken):
            RL._SLOTS.release()
    with _db() as db:
        assert db.query(ReceiptLogo).count() == before
    # Joy bo'shagach — odatdagidek.
    assert _up(client, H, _save(_rgb(89, 45, (2, 2, 2)), "PNG")).status_code == 201


def test_CPU_ishi_paytida_DB_tranzaksiyasi_OCHIQ_EMAS(client, m, monkeypatch):
    """Dekodlash vaqtida so'rov sessiyasi tranzaksiyada emas — pooled ulanish qaytgan."""
    from app.db.session import SessionLocal, get_db
    from app.main import app
    sessions, seen = [], []

    def _get_db():
        db = SessionLocal()
        sessions.append(db)
        try:
            yield db
        finally:
            db.close()
    real = RL.process

    def spy(raw):
        seen.append(sessions[-1].in_transaction())
        return real(raw)
    monkeypatch.setattr(RL, "process", spy)
    app.dependency_overrides[get_db] = _get_db
    try:
        r = _up(client, m["x"]["ega"]["h"], _save(_rgb(91, 47, (3, 3, 3)), "PNG"))
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 201, r.text
    assert seen == [False], seen


@pytest.mark.parametrize("tana,msg", [
    ({"data_b64": "@@@@"}, E.LOGO_CORRUPT),
    ({"data_b64": "iVBORw0KGgo=\n"}, E.LOGO_CORRUPT),
    ({"data_b64": 123}, E.LOGO_CORRUPT),
    ({}, E.LOGO_CORRUPT),
    ({"data_b64": "A" * 2_900_004}, E.LOGO_TOO_LARGE),
])
def test_BASE64_va_TANA_xatolari(client, m, tana, msg):
    r = client.post(URL, headers=m["x"]["ega"]["h"], json=tana)
    assert r.status_code == 400 and r.json() == {"detail": msg}, r.text
    r = client.post(URL, headers=m["x"]["ega"]["h"], json=[1, 2])
    assert r.status_code == 400 and r.json() == {"detail": E.LOGO_CORRUPT}


def test_POLYGLOT_haqiqiy_PNG_HTML_dum_QABUL_lekin_DUM_HECH_QACHON_QAYTMAYDI(client, m):
    raw = _rgba_png(64, 32) + b"<html><script>alert(document.cookie)</script></html>"
    r = _up(client, m["x"]["ega"]["h"], raw)
    assert r.status_code == 201, r.text
    body = r.content
    assert b"<script" not in body and _b64(raw).encode() not in body
    for v in r.json()["variants"].values():
        _, png = _variant_bytes(v)
        assert b"<script" not in png and png != raw
    g = client.get(f"{URL}/{r.json()['id']}", headers=m["x"]["ega"]["h"])
    assert g.status_code == 200 and b"<script" not in g.content and "original" not in g.json()


# ══ 3 · DOIRA ════════════════════════════════════════════════════════════════
_DOIRA_RAW = _save(_rgb(64, 64, (5, 5, 5)), "PNG")


@pytest.fixture(scope="module")
def ids(client, m):
    """A1 logosi (A1 administratori yuklagan), A2 logosi va kompaniya logosi (ega)."""
    x = m["x"]
    r_a1 = _up(client, x["administrator@A1"]["h"], _DOIRA_RAW, branch_id=m["a1"])
    r_a2 = _up(client, x["ega"]["h"], _DOIRA_RAW, branch_id=m["a2"])
    r_c = _up(client, x["ega"]["h"], _save(_rgb(66, 66, (5, 5, 5)), "PNG"))
    assert (r_a1.status_code, r_a2.status_code, r_c.status_code) == (201, 201, 201), r_a1.text
    return {"a1": r_a1.json()["id"], "a2": r_a2.json()["id"], "c": r_c.json()["id"]}


def test_DOIRA_yuklash_va_oqish(client, m, ids):
    x = m["x"]
    raw = _DOIRA_RAW
    h1 = x["administrator@A1"]["h"]
    r = _up(client, h1, raw)
    assert r.status_code == 403 and r.headers.get("X-Error-Code") == "RECEIPT_SCOPE_COMPANY_FORBIDDEN"
    assert r.json() == {"detail": E.SCOPE_COMPANY_FORBIDDEN}
    assert _up(client, h1, raw, branch_id=m["a2"]).status_code == 404
    assert ids["a1"] != ids["a2"]            # ayni fayl, boshqa filial — boshqa id
    # O'qish: cheklovsiz menejer — hammasi; A1 menejer — kompaniya + A1; begona — hech biri.
    for who, ok in (("menejer", {"a1", "a2", "c"}), ("menejer@A1", {"a1", "c"}),
                    ("begona-ega", set())):
        for k, lid in ids.items():
            g = client.get(f"{URL}/{lid}", headers=x[who]["h"])
            if k in ok:
                assert g.status_code == 200 and g.json()["id"] == lid, (who, k)
            else:
                assert g.status_code == 404 and g.json() == {"detail": "Logo topilmadi"}, (who, k)
    assert client.get(f"{URL}/{ids['c']}", headers=x["kassir@A1"]["h"]).status_code == 403
    assert client.get(f"{URL}/buzuq", headers=x["ega"]["h"]).status_code == 404
    assert _up(client, x["menejer"]["h"], raw).status_code == 403


def test_SOZLAMA_logo_id_HAVOLA_qoidasi_va_profil(client, m, ids):
    x, H = m["x"], m["x"]["ega"]["h"]
    bad = {"detail": "Logo topilmadi"}
    # Kompaniya qatori — faqat kompaniya logosi.
    r = _put(client, H, {"logo_id": ids["a1"]})
    assert r.status_code == 400 and r.json() == bad
    for lid in (str(uuid.uuid4()),):
        assert _put(client, H, {"logo_id": lid}).json() == bad
    begona = _up(client, x["begona-ega"]["h"], _save(_rgb(50, 50), "PNG"))
    assert begona.status_code == 201
    assert _put(client, H, {"logo_id": begona.json()["id"]}).json() == bad
    assert _put(client, H, {"logo_id": ids["c"]}).status_code == 200
    # Filial qatori — kompaniya logosi yoki AYNAN o'z filiali logosi.
    assert _put(client, H, {"logo_id": ids["a1"]}, m["a2"]).json() == bad
    assert _put(client, H, {"logo_id": ids["a1"]}, m["a1"]).status_code == 200
    g = client.get("/api/v1/receipt/settings", headers=H, params={"branch_id": m["a1"]}).json()
    assert g["logo"]["id"] == ids["a1"] and g["effective"]["logo_id"] == ids["a1"]
    # Kassa profili — bitlar bilan; A2 kompaniya logosini meros oladi.
    p = client.get("/api/v1/receipt/profile", headers=x["kassir@A1"]["h"]).json()
    assert p["logo"]["id"] == ids["a1"] and set(p["logo"]["variants"]) == {"58", "80"}
    p2 = client.get("/api/v1/receipt/profile", headers=H, params={"branch_id": m["a2"]}).json()
    assert p2["logo"]["id"] == ids["c"]
    # show_logo=false — profil logosiz, sozlama ko'rinishi esa logoni ko'rsatadi (UI uchun).
    assert _put(client, H, {"show_logo": False}, m["a1"]).status_code == 200
    p = client.get("/api/v1/receipt/profile", headers=x["kassir@A1"]["h"]).json()
    assert p["logo"] is None
    g = client.get("/api/v1/receipt/settings", headers=H, params={"branch_id": m["a1"]}).json()
    assert g["logo"]["id"] == ids["a1"]
    # Logoni uzish — `logo_id: null`.
    assert _put(client, H, {"logo_id": None, "show_logo": None}, m["a1"]).status_code == 200
    p = client.get("/api/v1/receipt/profile", headers=x["kassir@A1"]["h"]).json()
    assert p["logo"]["id"] == ids["c"]


def test_ORIGINAL_bayt_deferred_oddiy_oqishda_YUKLANMAYDI(client, m, ids):
    from app.models.receipt import ReceiptLogo
    with _db() as db:
        row = db.get(ReceiptLogo, uuid.UUID(ids["c"]))
        assert "original" not in row.__dict__
        assert row.original[:8] == b"\x89PNG\r\n\x1a\n"     # talab qilinganda — o'qiladi
