# -*- coding: utf-8 -*-
"""Chekdagi shtrix-kod (CODE128) va QR matritsasi — SERVERDA, bir marta (Phase 5F).

⚠️  NEGA SERVERDA. Mijoz (POS/Manager, Electron main jarayoni) kodni o'zi
    hisoblasa, ikki ilova ikki xil kod chiqarishi mumkin edi. Server tayyor
    MODULLAR qatorini beradi: renderer ularni faqat chizadi (SVG yoki ESC/POS rastr),
    hech narsani qayta kodlamaydi.
⚠️  QR ichida FAQAT ochiq ma'lumot: sotuv `uid` (/sales/find aynan shuni izlaydi)
    yoki do'kon o'zi kiritgan `https://` havola. Token, id, summa — HECH QACHON.
"""
from __future__ import annotations

# ── CODE128 ──────────────────────────────────────────────────────────────────
# ISO/IEC 15417 jadvali: har qiymat — 6 ta element kengligi (bar, bo'shliq, …),
# jami 11 modul; STOP — 7 element, 13 modul.
_WIDTHS = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212",
    "221213", "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221",
    "223211", "221132", "221231", "213212", "223112", "312131", "311222", "321122", "321221",
    "312212", "322112", "322211", "212123", "212321", "232121", "111323", "131123", "131321",
    "112313", "132113", "132311", "211313", "231113", "231311", "112133", "112331", "132131",
    "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131",
    "311123", "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111", "111242",
    "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311",
    "113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
)
START_B, START_C, CODE_B, CODE_C, STOP = 104, 105, 100, 99, 106


def _modules(widths: str) -> str:
    return "".join(("1" if i % 2 == 0 else "0") * int(w) for i, w in enumerate(widths))


PATTERNS: tuple[str, ...] = tuple(_modules(w) for w in _WIDTHS)


def _digits_run(s: str, i: int) -> int:
    n = i
    while n < len(s) and s[n].isascii() and s[n].isdigit():
        n += 1
    return n - i


def code128_values(payload: str) -> list[int]:
    """Belgilar qiymatlari (start … checksum), STOP'siz. B va C to'plamlari.

    C to'plami (ikki raqam = bir belgi) — raqamlar ketma-ketligi foyda bersa:
    boshida/oxirida ≥ 4, o'rtada ≥ 6 raqam (standart tavsiyasi). Toq uzunlikda
    ortiqcha bitta raqam B to'plamida qoladi."""
    if not payload or any(not (32 <= ord(ch) <= 126) for ch in payload):
        raise ValueError("CODE128: faqat ASCII 32..126")
    vals: list[int] = []
    cur = None
    i, n = 0, len(payload)
    while i < n:
        run = _digits_run(payload, i)
        at_edge = i == 0 or i + run == n
        use_c = run >= (4 if at_edge else 6) or (cur == "C" and run >= 2)
        if run == n and n >= 2 and n % 2 == 0:
            use_c = True          # butunlay juft raqamli — to'liq C
        if use_c:
            if run % 2 and cur != "C":
                # Toq uzunlik: bitta raqamni B da oldinroq chiqaramiz, qolgani juft C.
                if cur != "B":
                    vals.append(START_B if cur is None else CODE_B)
                    cur = "B"
                vals.append(ord(payload[i]) - 32)
                i += 1
                run -= 1
            if cur != "C":
                vals.append(START_C if cur is None else CODE_C)
                cur = "C"
            pairs = run // 2
            for k in range(pairs):
                vals.append(int(payload[i + 2 * k: i + 2 * k + 2]))
            i += 2 * pairs
            continue
        if cur != "B":
            vals.append(START_B if cur is None else CODE_B)
            cur = "B"
        vals.append(ord(payload[i]) - 32)
        i += 1
    check = (vals[0] + sum(k * v for k, v in enumerate(vals[1:], start=1))) % 103
    vals.append(check)
    return vals


def code128_modules(payload: str) -> str:
    """Modullar qatori ("1" = qora) — start, ma'lumot, nazorat belgisi, STOP."""
    return "".join(PATTERNS[v] for v in code128_values(payload)) + PATTERNS[STOP]


def barcode_block(payload: str | None) -> dict | None:
    if not payload:
        return None
    try:
        modules = code128_modules(payload)
    except ValueError:
        return None               # kodlab bo'lmaydigan payload — shtrix-kodsiz chek
    return {"format": "CODE128", "payload": payload, "modules": modules}


# ── QR ───────────────────────────────────────────────────────────────────────
def qr_matrix(payload: str) -> list[str]:
    """Xatoni tuzatish darajasi M, chegara 0 (sokin zonani renderer qo'shadi).

    `qrcode` kutubxonasi — niqobni jarima bo'yicha deterministik tanlaydi, versiya
    eng kichigi (`fit=True`)."""
    import qrcode
    import qrcode.constants
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    q.add_data(payload)
    q.make(fit=True)
    return ["".join("1" if c else "0" for c in row) for row in q.get_matrix()]


def qr_block(kind: str, payload: str | None) -> dict | None:
    if not payload:
        return None
    m = qr_matrix(payload)
    return {"kind": kind, "payload": payload, "size": len(m), "matrix": m}
