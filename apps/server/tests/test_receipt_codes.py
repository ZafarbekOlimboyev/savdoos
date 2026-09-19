# -*- coding: utf-8 -*-
"""PHASE 5F — CHEKDAGI CODE128 va QR (`app/services/receipt/codes.py`).

Bazaga ulanmaydi (`client` yo'q).

CODE128 — MUSTAQIL tekshiruv:
  · jadval yaxlitligi (ISO/IEC 15417): 107 belgi, har biri 11 modul (STOP 13), bar bilan
    boshlanadi, bar-modullar soni JUFT, hammasi noyob;
  · standartdan ma'lum literal naqshlar (0, 1, 2, START A/B/C, STOP);
  · kodlovchidan MUSTAQIL dekoder: modullar → belgilar → nazorat yig'indisi → matn,
    ko'plab payload'da (B↔C almashinuvi, toq/juft raqam qatorlari) aynan qaytadi;
  · ma'lum vektorlar: sof raqamli `uid` to'liq C to'plamida (qisqa kod).
QR — xatoni tuzatish darajasi M (format ma'lumotidan BCH bilan dekodlanadi), chegara 0,
  o'lcham = 17 + 4·versiya, finder/timing naqshlari, deterministik.
"""
import pytest

from app.services.receipt import codes as C

# ── MUSTAQIL DEKODER ─────────────────────────────────────────────────────────
_REV = {p: v for v, p in enumerate(C.PATTERNS)}


def _decode(modules: str) -> str:
    assert modules.endswith(C.PATTERNS[C.STOP]), "STOP yo'q"
    body = modules[: -len(C.PATTERNS[C.STOP])]
    assert len(body) % 11 == 0
    vals = [_REV[body[i:i + 11]] for i in range(0, len(body), 11)]
    *data, check = vals
    assert (data[0] + sum(k * v for k, v in enumerate(data[1:], start=1))) % 103 == check, "checksum"
    start = data[0]
    assert start in (104, 105), start
    mode = "B" if start == 104 else "C"
    out = []
    for v in data[1:]:
        if mode == "B":
            if v == 99:
                mode = "C"
            else:
                assert v < 95, v
                out.append(chr(v + 32))
        else:
            if v == 100:
                mode = "B"
            else:
                assert v < 100, v
                out.append(f"{v:02d}")
    return "".join(out)


def test_JADVAL_yaxlitligi():
    assert len(C.PATTERNS) == 107
    for v, p in enumerate(C.PATTERNS):
        assert len(p) == (13 if v == C.STOP else 11), v
        assert p[0] == "1" and p[-1] == ("1" if v == C.STOP else "0"), v
        widths = C._WIDTHS[v]
        assert sum(int(w) for w in widths[0::2]) % 2 == 0, (v, "bar-modullar soni toq")
    assert len(set(C.PATTERNS)) == 107


def test_MALUM_literal_naqshlar():
    assert C.PATTERNS[0] == "11011001100"
    assert C.PATTERNS[1] == "11001101100"
    assert C.PATTERNS[2] == "11001100110"
    assert C.PATTERNS[103] == "11010000100"      # START A
    assert C.PATTERNS[104] == "11010010000"      # START B
    assert C.PATTERNS[105] == "11010011100"      # START C
    assert C.PATTERNS[106] == "1100011101011"    # STOP


@pytest.mark.parametrize("payload", [
    "2609191288", "12345", "1", "12", "123", "1234", "Wikipedia", "TEST000000", "PJJ123C",
    "AB1234567CD", "A12B", "0000", "x" * 30, "9" * 31, "abc123456", "123456abc", "#1288",
    " !~", "QAY-1000", "a1234567890123b",
])
def test_ROUNDTRIP_mustaqil_dekoder_bilan(payload):
    assert _decode(C.code128_modules(payload)) == payload


def test_RAQAMLI_uid_TOLIQ_C_toplamida():
    v = C.code128_values("2609191288")
    assert v[:6] == [105, 26, 9, 19, 12, 88] and len(v) == 7
    assert v[-1] == (105 + 26 * 1 + 9 * 2 + 19 * 3 + 12 * 4 + 88 * 5) % 103
    # Toq uzunlik: bitta raqam B da, qolgani C da — 6 belgi + nazorat.
    assert len(C.code128_values("1234567")) == 7
    # O'rtadagi qisqa raqam qatori C ga o'tmaydi (foydasiz almashinuv yo'q).
    assert C.code128_values("A12B")[:5] == [104, 33, 17, 18, 34]


def test_KODLAB_BOLMAYDIGAN_payload_None():
    assert C.barcode_block("Чек") is None and C.barcode_block("") is None
    assert C.barcode_block(None) is None
    b = C.barcode_block("2609191288")
    assert b["format"] == "CODE128" and b["payload"] == "2609191288"
    assert set(b["modules"]) == {"0", "1"}


# ── QR ───────────────────────────────────────────────────────────────────────
_G15 = 0b10100110111
_MASK = 0b101010000010010


def _bch_ok(bits15: int) -> bool:
    v = bits15
    for i in range(14, 9, -1):
        if v & (1 << i):
            v ^= _G15 << (i - 10)
    return v == 0


def _format_bits(m: list[str]) -> int:
    """Format ma'lumoti — 8-ustun bo'ylab (chap-yuqori finder atrofi + chap-past)."""
    n = len(m)
    bits = 0
    for i in range(15):
        row = i if i < 6 else (i + 1 if i < 8 else n - 15 + i)
        if m[row][8] == "1":
            bits |= 1 << i
    return bits


@pytest.mark.parametrize("payload", ["2609191288", "TEST000000", "https://dokon.uz/fikr?x=1",
                                     "https://example.uz/" + "a" * 280])
def test_QR_M_daraja_chegara_0_finder_timing(payload):
    m = C.qr_matrix(payload)
    n = len(m)
    assert all(len(r) == n for r in m) and (n - 17) % 4 == 0 and 21 <= n <= 177
    finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
    for r in range(7):
        assert m[r][:7] == finder[r] and m[r][n - 7:] == finder[r] and m[n - 7 + r][:7] == finder[r]
    assert m[6][8:n - 8] == ("10" * n)[: n - 16]              # timing naqshi
    assert m[n - 8][8] == "1"                                   # «qorong'i modul»
    fmt = _format_bits(m)
    assert _bch_ok(fmt ^ _MASK), bin(fmt)                      # niqob olingach — BCH kod so'zi
    assert ((fmt ^ _MASK) >> 13) & 0b11 == 0b00, "xatoni tuzatish darajasi M emas"
    assert C.qr_matrix(payload) == m                            # deterministik
    blk = C.qr_block("store_url", payload)
    assert blk == {"kind": "store_url", "payload": payload, "size": n, "matrix": m}


def test_QR_bosh_payload_None():
    assert C.qr_block("receipt_id", None) is None and C.qr_block("receipt_id", "") is None


def test_QR_EC_dekoderi_SALBIY_nazorat_L_va_H_ni_farqlaydi():
    """Format dekoderi haqiqatan darajani o'qiydi: L → 01, H → 10 (M → 00 yuqorida)."""
    import qrcode
    import qrcode.constants as K
    for level, want in ((K.ERROR_CORRECT_L, 0b01), (K.ERROR_CORRECT_H, 0b10)):
        q = qrcode.QRCode(error_correction=level, box_size=1, border=0)
        q.add_data("2609191288")
        q.make(fit=True)
        m = ["".join("1" if c else "0" for c in row) for row in q.get_matrix()]
        fmt = _format_bits(m)
        assert _bch_ok(fmt ^ _MASK) and ((fmt ^ _MASK) >> 13) & 0b11 == want
