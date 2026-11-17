#!/usr/bin/env python3
# Run ON runcater: map console fg-colored pixels in a /dev/fb0 capture.
#
# fbcon default fg (VGA palette 7 = 170,170,170) expands after the 565
# round-trip to ~(173,170,173) — distinct from tokcat fg (239,239,247).
# Any such pixels are console artifacts (login prompt text / cursor).
#
# Usage: probe_console.py capture.png
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
px = im.load()

hits = []
for y in range(h):
    for x in range(w):
        r, g, b = px[x, y]
        if 150 <= r <= 200 and 150 <= g <= 200 and 150 <= b <= 200:
            hits.append((x, y))

if not hits:
    print("no light-gray (console fg) pixels found")
    sys.exit()

xs = [p[0] for p in hits]
ys = [p[1] for p in hits]
print("console-fg pixels: %d  bbox x %d..%d  y %d..%d"
      % (len(hits), min(xs), max(xs), min(ys), max(ys)))

for y0 in range(0, h, 16):
    row = [p for p in hits if y0 <= p[1] < y0 + 16]
    if row:
        xx = [p[0] for p in row]
        print("row y %3d..%3d: %4d px  x %d..%d"
              % (y0, y0 + 15, len(row), min(xx), max(xx)))
