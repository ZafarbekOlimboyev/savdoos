#!/usr/bin/env python3
"""BinOS brend assetlari: ORIGINAL logodan `icon.png` va `icon_fg.png` ni yasaydi.

    apps/mobile/assets/icon/binos-logo-source.webp   (ORIGINAL — tegilmaydi)
        -> apps/mobile/assets/icon/icon.png          (1024 RGB, to'la-kvadrat)
        -> apps/mobile/assets/icon/icon_fg.png       (1024 RGBA, shaffof belgi)

Keyin `scripts/pwa_icons.py` shu ikkitasidan butun PWA ikonka to'plamini va
Apple touch ikonkasini yasaydi (mavjud, o'zgarmagan quvur).

NIMA QILINADI VA NIMA QILINMAYDI
--------------------------------
Original rastrda nishon (to'q ko'k dumaloq-kvadrat + gradientli "B") atrofida
QORA kanvas bor. O'lchangan: nishon `bbox` (45,49)-(1209,1204), ya'ni chekkada
~3.6% qora hoshiya; nishon foni #011A44. Qora maydon dizayn EMAS — u fon:
  * hoshiya butun perimetr bo'ylab bir xil,
  * dumaloq burchaklardan TASHQARIDAGI piksellar ham aynan o'sha qora.
Shu bois:
  * `icon.png` — nishon kesib olinadi va qora qoldiq nishonning O'Z foni
    (#011A44) bilan to'ldiriladi -> TO'LA-KVADRAT. iOS o'z maskasini qo'llaydi,
    ya'ni ikki marta dumaloqlanish va burchakdagi qora parchalar YO'Q.
  * `icon_fg.png` — faqat "B" belgisi, shaffof fonda, maskable xavfsiz zonaga
    (ichki ~80%) sig'adigan o'lchamda.

⚠️  LOGO DIZAYNI O'ZGARTIRILMAYDI: shakl, geometriya va ranglar originaldan
    piksel-ba-piksel olinadi. Bu skript faqat FONNI ajratadi va o'lcham beradi.
    Original asset repo'da saqlanadi va hech qachon qayta yozilmaydi.

Ishga tushirish (repo ildizidan):
    apps/server/.venv/Scripts/python scripts/binos_logo_assets.py
Idempotent: bir xil kirish -> bir xil chiqish.
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "apps" / "mobile" / "assets" / "icon"
SOURCE = SRC_DIR / "binos-logo-source.webp"

#: Nishon foni (originaldan o'lchangan, eng ko'p uchraydigan rang).
BADGE_BG = (1, 26, 68)
#: Shu masofadan yaqin piksel "fon" deb hisoblanadi (nishon foni yoki qora).
BG_TOLERANCE = 46
#: Maskable xavfsiz zona — ichki 80% DOIRA (radius = 0.40 * tomon). Belgi shu
#: doiraga TO'LIQ sig'adigan qilib kichraytiriladi: o'lcham TAXMIN qilinmaydi,
#: belgining markazdan eng uzoq NOSHAFFOF pikseli bo'yicha hisoblanadi. Shu
#: sababli agressiv iOS/Android maskasi ham belgini kesmaydi.
SAFE_RADIUS = 0.40
SIDE = 1024


def _is_bg(p: tuple[int, int, int]) -> bool:
    if p[0] < 30 and p[1] < 30 and p[2] < 30:
        return True                                    # tashqi qora kanvas
    d = sum((p[i] - BADGE_BG[i]) ** 2 for i in range(3)) ** 0.5
    return d <= BG_TOLERANCE                           # nishonning o'z foni


def _badge_box(im: Image.Image) -> tuple[int, int, int, int]:
    """Qora hoshiyadan ichkaridagi nishon to'rtburchagi."""
    w, h = im.size
    px = im.load()

    def not_black(p: tuple[int, int, int]) -> bool:
        return p[0] > 28 or p[1] > 28 or p[2] > 28

    left = next(x for x in range(w) if not_black(px[x, h // 2]))
    right = next(x for x in range(w - 1, -1, -1) if not_black(px[x, h // 2]))
    top = next(y for y in range(h) if not_black(px[w // 2, y]))
    bottom = next(y for y in range(h - 1, -1, -1) if not_black(px[w // 2, y]))
    return (left, top, right + 1, bottom + 1)


def build_icon(badge: Image.Image) -> Image.Image:
    """To'la-kvadrat ikonka: qora qoldiq nishon foniga almashtiriladi."""
    out = badge.convert("RGB").copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[0] < 30 and p[1] < 30 and p[2] < 30:
                px[x, y] = BADGE_BG
    return out.resize((SIDE, SIDE), Image.LANCZOS)


def build_foreground(badge: Image.Image) -> Image.Image:
    """Shaffof fonli belgi, maskable xavfsiz zonaga markazlangan."""
    rgba = badge.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            if _is_bg((r, g, b)):
                px[x, y] = (r, g, b, 0)
    box = rgba.getbbox()
    if box is None:
        sys.exit("belgi topilmadi — BG_TOLERANCE juda katta")
    mark = rgba.crop(box)

    # Belgining markazidan eng uzoq noshaffof piksel — HAQIQIY radius.
    mw, mh = mark.size
    cx, cy = (mw - 1) / 2, (mh - 1) / 2
    alpha = mark.getchannel("A").load()
    worst = 0.0
    for y in range(mh):
        for x in range(mw):
            if alpha[x, y] > 8:
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if d > worst:
                    worst = d
    if worst <= 0:
        sys.exit("belgi bo'sh")

    target = SIDE * SAFE_RADIUS
    scale = target / worst
    mark = mark.resize((max(1, round(mw * scale)), max(1, round(mh * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    canvas.alpha_composite(mark, ((SIDE - mark.size[0]) // 2, (SIDE - mark.size[1]) // 2))
    return canvas


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"original topilmadi: {SOURCE.relative_to(ROOT)}")
    im = Image.open(SOURCE).convert("RGB")
    box = _badge_box(im)
    badge = im.crop(box)
    print(f"original {im.size} -> nishon {box} {badge.size}; fon {BADGE_BG}")

    icon = build_icon(badge)
    icon.save(SRC_DIR / "icon.png", format="PNG", optimize=True)
    print(f"  assets/icon/icon.png     {icon.size[0]}x{icon.size[1]}  "
          f"{(SRC_DIR / 'icon.png').stat().st_size} B")

    fg = build_foreground(badge)
    fg.save(SRC_DIR / "icon_fg.png", format="PNG", optimize=True)
    alpha = fg.getchannel("A")
    covered = sum(1 for v in alpha.getdata() if v > 0) / (SIDE * SIDE)
    print(f"  assets/icon/icon_fg.png  {fg.size[0]}x{fg.size[1]}  "
          f"{(SRC_DIR / 'icon_fg.png').stat().st_size} B  belgi maydoni {covered:.1%}")


if __name__ == "__main__":
    main()
