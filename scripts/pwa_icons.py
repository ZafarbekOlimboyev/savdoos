#!/usr/bin/env python3
"""Generate the PWA icon set for apps/mobile/web from the BRAND assets.

Phase 5G.1 / package C1. The Flutter scaffold ships four Flutter-logo
placeholders; these are the real ones, derived from exactly the same sources
the Android launcher icon uses, so the installed PWA and the installed APK
cannot drift apart:

    assets/icon/icon.png      -> "any" icons + the Apple touch icon + favicon
    assets/icon/icon_fg.png   -> the maskable icons, composited on the Android
                                 adaptive background colour from pubspec.yaml

`flutter_launcher_icons` is configured for Android only (`android: true,
ios: false`) and adding a `web:` block would rewrite pubspec.yaml, which this
package does not own. Hence this script.

Run (from the repo root):
    apps/server/.venv/Scripts/python scripts/pwa_icons.py

It is idempotent: same inputs -> byte-identical outputs.
"""

from __future__ import annotations

import pathlib
import re
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOBILE = ROOT / "apps" / "mobile"
SRC = MOBILE / "assets" / "icon"
OUT = MOBILE / "web" / "icons"

# Android composites an adaptive icon by drawing the FULL foreground layer over
# the FULL background layer and masking to the inner 72/108 of the canvas —
# `icon_fg.png` therefore already carries that padding. Draw it at 1.0 (exactly
# what the launcher does) and the glyph lands at ~66% of the tile, well inside
# the maskable safe zone (the inner 80% circle). Scaling it again would shrink
# the mark to a speck.
FOREGROUND_RATIO = 1.0


def brand_colour() -> tuple[int, int, int]:
    """The adaptive-icon background from pubspec.yaml (single source of truth)."""
    text = (MOBILE / "pubspec.yaml").read_text(encoding="utf-8")
    m = re.search(r'adaptive_icon_background:\s*"(#[0-9A-Fa-f]{6})"', text)
    if not m:
        sys.exit("pubspec.yaml: adaptive_icon_background not found")
    h = m.group(1).lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def save(im: Image.Image, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format="PNG", optimize=True)
    print(f"  {path.relative_to(ROOT)}  {im.size[0]}x{im.size[1]}  {path.stat().st_size} B")


def main() -> None:
    icon = Image.open(SRC / "icon.png").convert("RGBA")
    fg = Image.open(SRC / "icon_fg.png").convert("RGBA")
    bg = brand_colour()

    print(f"brand background {bg} (from pubspec.yaml)")

    for side in (192, 512):
        save(icon.resize((side, side), Image.LANCZOS).convert("RGB"), OUT / f"Icon-{side}.png")

    for side in (192, 512):
        canvas = Image.new("RGBA", (side, side), bg + (255,))
        inner = max(1, round(side * FOREGROUND_RATIO))
        art = fg.resize((inner, inner), Image.LANCZOS)
        off = (side - inner) // 2
        canvas.alpha_composite(art, (off, off))
        save(canvas.convert("RGB"), OUT / f"Icon-maskable-{side}.png")

    # iOS Home Screen: 180px, opaque (iOS puts no background behind it).
    save(icon.resize((180, 180), Image.LANCZOS).convert("RGB"), OUT / "apple-touch-icon-180.png")
    save(icon.resize((64, 64), Image.LANCZOS).convert("RGB"), MOBILE / "web" / "favicon.png")


if __name__ == "__main__":
    main()
