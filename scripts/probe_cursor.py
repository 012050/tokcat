#!/usr/bin/env python3
# Run ON runcater: find the fbcon console cursor in a /dev/fb0 capture.
#
# The fbcon block cursor is a solid rectangle of the console fg color
# (light gray, ~ (198,195,198) after the 565 round-trip) sized one char
# cell (~8x16 px, default 8x16 font). The cat sprite is excluded by
# region, text glyphs by height (glyph strokes are a few px tall, the
# block cursor is a full cell).
#
# Usage: probe_cursor.py capture.png
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
px = im.load()

CAT_BOX = (165, 77, 315, 173)  # cat region (same as verify_*)


def in_cat(x, y):
    return CAT_BOX[0] <= x < CAT_BOX[2] and CAT_BOX[1] <= y < CAT_BOX[3]


def run_width(x, y, c):
    x2 = x
    while x2 + 1 < w and all(abs(px[x2 + 1, y][i] - c[i]) <= 16 for i in range(3)):
        x2 += 1
    return x2 - x + 1


def block_extent(x, y, x1, c):
    """Extend vertically while every pixel of the block row matches c."""
    y1 = y
    while y1 + 1 < h and all(
            all(abs(px[xx, y1 + 1][i] - c[i]) <= 16 for i in range(3))
            for xx in range(x, x1 + 1)):
        y1 += 1
    return y1


blocks = []
for y in range(h):
    x = 0
    while x < w:
        c = px[x, y]
        run = run_width(x, y, c)
        # candidate: bright solid horizontal run of cell-ish width
        if 5 <= run <= 24 and max(c) > 120 and not in_cat(x, y):
            x1 = x + run - 1
            y1 = block_extent(x, y, x1, c)
            bh = y1 - y + 1
            if 2 <= bh <= 24:
                blocks.append((x, y, x1, y1, c))
        x += max(run, 1)

# dedupe overlapping detections
out = []
for b in blocks:
    if not any(not (b[2] < o[0] or o[2] < b[0] or b[3] < o[1] or o[3] < b[1])
               for o in out):
        out.append(b)

cell = [b for b in out if b[3] - b[1] + 1 >= 8]
small = [b for b in out if b[3] - b[1] + 1 < 8]
if not out:
    print("no solid bright blocks found")
for x0, y0, x1, y1, c in cell:
    print("CELL  x %3d..%3d  y %3d..%3d  (%dx%d)  color %s"
          % (x0, x1, y0, y1, x1 - x0 + 1, y1 - y0 + 1, c))
for x0, y0, x1, y1, c in small:
    print("small x %3d..%3d  y %3d..%3d  (%dx%d)  color %s"
          % (x0, x1, y0, y1, x1 - x0 + 1, y1 - y0 + 1, c))
