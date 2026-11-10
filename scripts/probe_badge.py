#!/usr/bin/env python3
# Run ON runcater: find the badge rectangle in a capture (badge_bg fill).
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
px = im.load()
hits = [(x, y) for y in range(4, 40) for x in range(150, 479)
        if all(abs(px[x, y][i] - (16, 52, 32)[i]) <= 8 for i in range(3))]
if hits:
    xs = [x for x, _ in hits]
    ys = [y for _, y in hits]
    print("badge_bg rect: x %d..%d  y %d..%d  (w=%d)" %
          (min(xs), max(xs), min(ys), max(ys), max(xs) - min(xs) + 1))
else:
    print("no badge_bg found")
