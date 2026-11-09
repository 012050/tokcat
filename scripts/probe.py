#!/usr/bin/env python3
"""Pixel probe for tokcat captures — objective screen verification.

Usage: probe.py capture.png
"""
import sys

from PIL import Image

im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
px = im.load()
print("size %dx%d" % (w, h))

# background corners (expect ~ (11,14,19))
print("corners:", px[5, 5], px[w - 5, 5], px[5, h - 5], px[w - 5, h - 5])

# count non-background pixels (anything drawn)
bg = (11, 14, 19)
diff = sum(1 for y in range(h) for x in range(w)
           if any(abs(px[x, y][i] - bg[i]) > 24 for i in range(3)))
print("non-bg pixels: %d / %d (%.1f%%)" % (diff, w * h, 100.0 * diff / (w * h)))


def region(name, x0, y0, x1, y1):
    best = (0, None)
    for y in range(y0, y1):
        for x in range(x0, x1):
            s = sum(px[x, y])
            if s > best[0]:
                best = (s, px[x, y])
    print("%s brightest: %s" % (name, best[1]))


region("title   ", 16, 9, 140, 34)     # 'runcater' text
region("time    ", 250, 10, 420, 34)   # clock
region("badge   ", 420, 10, 464, 36)   # status badge (accent green)
region("catbox  ", 165, 62, 315, 188)  # placeholder outline + hint
region("metrics ", 16, 205, 464, 262)  # metric rows
region("inflight", 16, 276, 200, 298)  # in-flight row
