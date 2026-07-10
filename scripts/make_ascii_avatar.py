#!/usr/bin/env python3
"""One-off tool: convert the GitHub avatar into cached braille-art portraits.

Run manually whenever the avatar changes:
    python scripts/make_ascii_avatar.py
Outputs are committed as assets/avatar_dark.txt / assets/avatar_light.txt and
reused by generate_card.py on every scheduled run, so the (fixed) cost of the
conversion is paid once.

Braille cells pack 2x4 dots per character, giving ~8x the resolution of a
plain ASCII ramp — enough for the face to actually be recognizable. The
photo's light background is masked out first, then the subject's tonal range
is contrast-stretched and Floyd-Steinberg dithered to 1-bit dots. Dot
polarity is per theme: on the dark card bright pixels become dots (light on
dark), on the light card dark pixels do.
"""
import io
import os
import sys

import numpy as np
import requests
from PIL import Image

AVATAR_URL = "https://avatars.githubusercontent.com/u/76993406?v=4"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")

CHAR_WIDTH = 60  # output width in braille characters (120 dot columns)
BG_THRESHOLD = 192  # pixels lighter than this are background


def to_braille(img: Image.Image, invert: bool) -> str:
    img = img.convert("L")
    w, h = img.size
    img = img.crop((int(w * 0.10), 0, int(w * 0.92), int(h * 0.92)))

    px_w = CHAR_WIDTH * 2
    px_h = int(px_w * img.height / img.width)
    px_h -= px_h % 4
    img = img.resize((px_w, px_h))
    arr = np.array(img, dtype=np.float32)

    bg_mask = arr >= BG_THRESHOLD
    subject = arr[~bg_mask]
    lo, hi = np.percentile(subject, 2), np.percentile(subject, 98)
    hi = max(hi, lo + 1)
    norm = np.clip((arr - lo) / (hi - lo), 0, 1)
    level = norm if invert else (1 - norm)

    # Floyd-Steinberg dither to 1-bit dots
    on = np.zeros_like(level, dtype=bool)
    err = level.copy()
    H, W = err.shape
    for y in range(H):
        for x in range(W):
            old = err[y, x]
            new = 1.0 if old >= 0.5 else 0.0
            on[y, x] = bool(new)
            e = old - new
            if x + 1 < W:
                err[y, x + 1] += e * 7 / 16
            if y + 1 < H:
                if x > 0:
                    err[y + 1, x - 1] += e * 3 / 16
                err[y + 1, x] += e * 5 / 16
                if x + 1 < W:
                    err[y + 1, x + 1] += e * 1 / 16
    on[bg_mask] = False

    bits = [(0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
            (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80)]
    lines = []
    for cy in range(0, px_h, 4):
        row = []
        for cx in range(0, px_w, 2):
            code = 0
            for dx, dy, bit in bits:
                if on[cy + dy, cx + dx]:
                    code |= bit
            row.append(chr(0x2800 + code))
        lines.append("".join(row))
    return "\n".join(lines)


def main() -> int:
    resp = requests.get(AVATAR_URL, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))

    for theme, invert in (("dark", True), ("light", False)):
        art = to_braille(img, invert)
        path = os.path.join(ASSETS_DIR, f"avatar_{theme}.txt")
        with open(path, "w") as f:
            f.write(art + "\n")
        print(f"Wrote {path} ({len(art.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
