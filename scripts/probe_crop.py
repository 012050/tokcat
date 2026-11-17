#!/usr/bin/env python3
# Run ON runcater: ASCII-render a region of a capture.
# '#' = light-gray (console fg 150..200), 'o' = bright (>200 any channel),
# '.' = mid, ' ' = background.
# Usage: probe_crop.py capture.png x0 y0 x1 y1 [step]
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
x0, y0 = int(sys.argv[2]), int(sys.argv[3])
x1, y1 = int(sys.argv[4]), int(sys.argv[5])
step = int(sys.argv[6]) if len(sys.argv) > 6 else 1
px = im.load()
for y in range(y0, y1, step):
    row = []
    for x in range(x0, x1, step):
        r, g, b = px[x, y]
        if 150 <= r <= 200 and 150 <= g <= 200 and 150 <= b <= 200:
            row.append("#")
        elif max(r, g, b) > 200:
            row.append("o")
        elif r + g + b > 120:
            row.append(".")
        else:
            row.append(" ")
    print("y%3d| %s" % (y, "".join(row)))
