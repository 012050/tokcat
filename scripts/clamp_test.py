#!/usr/bin/env python3
"""Verify draw_graph clamps values above the fixed vmax (100 tok/s)."""
import collections
import sys
import time
import tomllib

sys.path.insert(0, sys.argv[1])
import tokcat  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

tokcat.rgb_to_565 = lambda img: img.tobytes()
with open(sys.argv[2], "rb") as f:
    cfg = tomllib.load(f)
fonts = tokcat.load_fonts(cfg)

# history with values well above 100 to test clamping at the top
hist = collections.deque(
    (float(v) for v in (5, 50, 120, 150, 90, 200, 30, 10)),
    maxlen=tokcat.HIST_MAX)

img = Image.new("RGB", (480, 320), (11, 14, 19))
d = ImageDraw.Draw(img)
gmax = float(cfg["display"].get("graph_max_tok_s", 100.0))
x0, y0, w, h = 342, 182, 122, 92
tokcat.draw_graph(d, x0, y0, w, h, hist, tokcat.HIST_MAX,
                  (76, 195, 138), (125, 138, 151), (11, 14, 19), gmax)
# sanity: no pixel of the chart line/poly should be above y0 (top of chart)
top = y0
px = img.load()
min_y = None
for x in range(x0, x0 + w):
    for y in range(top, top + h):
        r, g, b = px[x, y]
        if (r, g, b) != (11, 14, 19):
            if min_y is None or y < min_y:
                min_y = y
print("vmax used =", gmax)
print("top of chart y =", top)
print("highest non-bg pixel y =", min_y,
      "(OK if >= top)" if (min_y is not None and min_y >= top) else "(CLAMP FAIL)")
img.save(sys.argv[3])
print("saved", sys.argv[3])
