#!/usr/bin/env python3
# Run ON runcater: identify the actual badge text in a capture.
# Diffs only the badge rectangle region (x >= 356) against candidate
# badges rendered with the exact render_base geometry (right edge = 464).
import sys

sys.path.insert(0, "/opt/tokcat")
import tomllib

from PIL import Image, ImageDraw, ImageFont

import tokcat
from capture_fb0 import decode_565

cfg = tomllib.load(open("/opt/tokcat/config.toml", "rb"))
cap = Image.open(sys.argv[1]).convert("RGB")
c = cfg["color"]
bg = tokcat.hexcolor(c["bg"])
badge_bg = tokcat.hexcolor(c["badge_bg"])
accent = tokcat.hexcolor(c["accent"])
error = tokcat.hexcolor(c["error"])
fonts = tokcat.load_fonts(cfg)
font = fonts["badge"]

candidates = [
    ("SLEEP", accent), ("SLEEP · vLLM", accent), ("SLEEP·vLLM", accent),
    ("SLEEP ·vLLM", accent), ("SLEEP· vLLM", accent),
    ("OFFLINE", error), ("WALK", accent), ("WALK · vLLM", accent),
    ("RUN", accent), ("RUN · vLLM", accent),
]

W = 480
results = []
for text, color in candidates:
    bw = int(font.getlength(text))
    bx0, by0 = W - 16 - bw - 16, 10
    img = Image.new("RGB", (W, 40), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([bx0, by0, bx0 + bw + 16, by0 + 24], radius=6,
                        fill=badge_bg)
    d.text((bx0 + 8, by0 + 4), text, font=font, fill=color)
    # 565 round-trip so colors match the decoded capture (else every pixel diffs)
    img = Image.frombytes("RGB", (W, 40),
                          decode_565(tokcat.rgb_to_565(img), W * 40))
    diff = 0
    for y in range(8, 36):
        for x in range(356, W):
            if img.getpixel((x, y)) != cap.getpixel((x, y)):
                diff += 1
    results.append((diff, bw, text))

results.sort()
for diff, bw, text in results:
    print(f"{diff:6d}  bw={bw:4d}  {text!r}")
