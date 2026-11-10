#!/usr/bin/env python3
# Run ON runcater: dump a coarse grid of the top-right region of a capture
# vs a rendered candidate badge, to see what is actually there.
import sys

sys.path.insert(0, "/opt/tokcat")
import tomllib

from PIL import Image, ImageDraw, ImageFont

import tokcat

cfg = tomllib.load(open("/opt/tokcat/config.toml", "rb"))
cap = Image.open(sys.argv[1]).convert("RGB")
c = cfg["color"]
bg = tokcat.hexcolor(c["bg"])
badge_bg = tokcat.hexcolor(c["badge_bg"])
accent = tokcat.hexcolor(c["accent"])
font = tokcat.load_fonts(cfg)["badge"]

text = "SLEEP · vLLM"
bw = int(font.getlength(text))
bx0, by0 = 480 - 16 - bw - 16, 10
img = Image.new("RGB", (480, 40), bg)
d = ImageDraw.Draw(img)
d.rounded_rectangle([bx0, by0, bx0 + bw + 16, by0 + 24], radius=6,
                    fill=badge_bg)
d.text((bx0 + 8, by0 + 4), text, font=font, fill=accent)
print("candidate bw:", bw, "rect:", bx0, "..", bx0 + bw + 16)

print("x:", "  ".join(str(x) for x in range(340, 480, 8)))
for y in range(8, 38, 2):
    row_c = [cap.getpixel((x, y)) for x in range(340, 480, 8)]
    row_p = [img.getpixel((x, y)) for x in range(340, 480, 8)]
    print("y=%2d cap:" % y, " ".join("%3d" % sum(v) for v in row_c))
    print("y=%2d exp:" % y, " ".join("%3d" % sum(v) for v in row_p))
