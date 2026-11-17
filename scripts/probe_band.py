#!/usr/bin/env python3
# Run ON runcater: exact gray-pixel bbox per row in a band.
# Usage: probe_band.py capture.png y0 y1 x0 x1
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
y0, y1 = int(sys.argv[2]), int(sys.argv[3])
x0, x1 = int(sys.argv[4]), int(sys.argv[5])
px = im.load()
pts = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
       if 150 <= px[x, y][0] <= 200
       and 150 <= px[x, y][1] <= 200
       and 150 <= px[x, y][2] <= 200]
if not pts:
    print("no gray pixels in band")
    sys.exit()
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
print("n=%d bbox x %d..%d y %d..%d" % (len(pts), min(xs), max(xs), min(ys), max(ys)))
for y in range(min(ys), max(ys) + 1):
    row = [x for x, yy in pts if yy == y]
    if row:
        print("y%d: %d px, x %d..%d" % (y, len(row), min(row), max(row)))
