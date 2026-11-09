#!/usr/bin/env python3
"""Self-test: rgb_to_565 / decode_565 round-trip + known-value checks.

Usage: python3 test_565.py   (run in /opt/tokcat)
"""
import struct

from PIL import Image

from capture_fb0 import decode_565
from tokcat import rgb_to_565


def expand(r, g, b):
    """Expected 8-bit value after 565 quantize -> expand."""
    r5, g6, b5 = r >> 3, g >> 2, b >> 3
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


# 1) known 565 values
cases = [(248, 0, 0, 0xF800), (0, 252, 0, 0x07E0), (0, 0, 248, 0x001F),
         (248, 252, 248, 0xFFFF), (0, 0, 0, 0x0000)]
for r, g, b, want in cases:
    im = Image.new("RGB", (1, 1), (r, g, b))
    v = struct.unpack("<H", rgb_to_565(im))[0]
    assert v == want, "encode (%d,%d,%d) -> %04x, want %04x" % (r, g, b, v, want)
    back = decode_565(rgb_to_565(im), 1)
    assert back == bytes(expand(r, g, b)), "decode round-trip (%d,%d,%d) -> %r" % (r, g, b, back)
print("known-value checks OK")

# 2) full round-trip on a gradient
w, h = 480, 320
im = Image.new("RGB", (w, h))
px = im.load()
for y in range(h):
    for x in range(w):
        px[x, y] = ((x * 255) // (w - 1), (y * 255) // (h - 1), (x * y) % 256)
data = rgb_to_565(im)
assert len(data) == w * h * 2
back = Image.frombytes("RGB", (w, h), decode_565(data, w * h))
bp = back.load()
maxerr = 0
for y in range(h):
    for x in range(w):
        a, b = px[x, y], bp[x, y]
        maxerr = max(maxerr, max(abs(a[i] - b[i]) for i in range(3)))
# 565 quantization: r/b step 8 (err<=7), g step 4 (err<=3)
assert maxerr <= 7, "round-trip max error %d" % maxerr
print("gradient round-trip OK (max err %d)" % maxerr)
