#!/usr/bin/env python3
# Run ON runcater: diff two /dev/fb0 captures with the dynamic tokcat
# regions masked out (clock+badge / cat / metrics+in-flight). Whatever
# remains is static-screen content that differs between the two shots —
# i.e. console artifacts (cursor blink, text) or one-off glitches.
#
# Usage: probe_diff.py capA.png capB.png
import sys

from PIL import Image

a = Image.open(sys.argv[1]).convert("RGB")
b = Image.open(sys.argv[2]).convert("RGB")
w, h = a.size
pa, pb = a.load(), b.load()

MASK = [
    (150, 6, 464, 36),     # clock + badge (positions/widths move)
    (165, 77, 315, 173),   # cat (animation)
    (16, 205, 464, 298),   # metrics rows + in-flight (live values)
]


def masked(x, y):
    return any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in MASK)


diff = []
for y in range(h):
    for x in range(w):
        if masked(x, y):
            continue
        if pa[x, y] != pb[x, y]:
            diff.append((x, y, pa[x, y], pb[x, y]))

print("diff pixels (masked):", len(diff))
if not diff:
    sys.exit()
xs = [d[0] for d in diff]
ys = [d[1] for d in diff]
print("bbox x %d..%d  y %d..%d" % (min(xs), max(xs), min(ys), max(ys)))
for d in diff[:12]:
    print("  (%3d,%3d) A=%s B=%s" % (d[0], d[1], d[2], d[3]))

# coarse ascii map, 1 char per 2x2 px
grid = set((d[0] // 2, d[1] // 2) for d in diff)
for y2 in range(0, h // 2):
    row = "".join("#" if (x2, y2) in grid else "." for x2 in range(0, w // 2))
    if "#" in row:
        print("y%3d %s" % (y2 * 2, row))
