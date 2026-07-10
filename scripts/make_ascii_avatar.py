#!/usr/bin/env python3
"""One-off tool: convert the GitHub avatar into cached ASCII art.

Run manually whenever the avatar changes:
    python scripts/make_ascii_avatar.py
Output is committed as assets/avatar_ascii.txt and reused by generate_card.py
on every scheduled run, so the (fixed) cost of this conversion is paid once.

A plain grayscale ramp over the full photo washes out the face: portrait
photos are typically a light background + a very dark subject (hair,
shirt), which squeezes the face into a narrow mid-tone band. Instead we
threshold out the background first, then contrast-stretch only the
subject's tonal range so facial features (glasses, eyes, jawline) become
visible in the ramp.
"""
import io
import os
import sys

import numpy as np
import requests
from PIL import Image

AVATAR_URL = "https://avatars.githubusercontent.com/u/76993406?v=4"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "avatar_ascii.txt")

RAMP = "@%#*+=-:. "
WIDTH = 70
CHAR_ASPECT = 0.55  # terminal cells are taller than wide; compensate
BG_THRESHOLD = 192  # pixels lighter than this are treated as background


def image_to_ascii(img: Image.Image, width: int = WIDTH) -> str:
    img = img.convert("L")
    w, h = img.size
    img = img.crop((int(w * 0.05), 0, int(w * 0.95), int(h * 0.95)))

    ratio = img.height / img.width
    height = max(1, int(width * ratio * CHAR_ASPECT))
    img = img.resize((width, height))

    arr = np.array(img, dtype=np.float32)
    mask = arr < BG_THRESHOLD
    subject = arr[mask]
    lo, hi = np.percentile(subject, 2), np.percentile(subject, 98)
    hi = max(hi, lo + 1)
    stretched = np.clip((arr - lo) / (hi - lo), 0, 1)

    scale = len(RAMP) - 1
    lines = []
    for y in range(height):
        row = []
        for x in range(width):
            if not mask[y, x]:
                row.append(" ")
            else:
                idx = int((1 - stretched[y, x]) * scale)
                row.append(RAMP[max(0, min(scale, idx))])
        lines.append("".join(row))
    return "\n".join(lines)


def main() -> int:
    resp = requests.get(AVATAR_URL, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))
    art = image_to_ascii(img)
    with open(OUT_PATH, "w") as f:
        f.write(art + "\n")
    print(f"Wrote {OUT_PATH} ({len(art.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
