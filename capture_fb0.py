#!/usr/bin/env python3
"""Capture /dev/fb0 (16bpp RGB565) to PNG — agent screen-verification loop.

Usage: capture_fb0.py [out.png]   (default: /tmp/tokcat-capture.png)
"""

import fcntl
import os
import struct
import sys

from PIL import Image

FB_DEFAULT = "/dev/fb0"
FBIOGET_VSCREENINFO = 0x4600  # struct fb_var_screeninfo: xres(0) yres(1) ... bpp(6)
FBIOGET_FSCREENINFO = 0x4602  # struct fb_fix_screeninfo: smem_len(24) ... line_length(48)


def decode_565(data, n):
    """Little-endian RGB565 bytes -> RGB bytes (5/6-bit channels expanded)."""
    px = struct.unpack("<%dH" % n, data[: n * 2])
    rgb = bytearray(3 * n)
    for i, v in enumerate(px):
        r5, g6, b5 = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
        rgb[3 * i] = (r5 << 3) | (r5 >> 2)
        rgb[3 * i + 1] = (g6 << 2) | (g6 >> 4)
        rgb[3 * i + 2] = (b5 << 3) | (b5 >> 2)
    return bytes(rgb)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tokcat-capture.png"
    fd = os.open(FB_DEFAULT, os.O_RDONLY)
    try:
        vinfo = bytearray(160)  # 40 x u32
        fcntl.ioctl(fd, FBIOGET_VSCREENINFO, vinfo)
        v = struct.unpack_from("40I", vinfo)
        xres, yres, bpp = v[0], v[1], v[6]
        if bpp != 16:
            sys.exit(f"capture: expected 16bpp, got {bpp}")
        finfo = bytearray(80)
        fcntl.ioctl(fd, FBIOGET_FSCREENINFO, finfo)
        line_length = struct.unpack_from("I", finfo, 48)[0]
        data = os.read(fd, yres * line_length)
        # crop each row to xres (line_length may carry padding)
        if line_length > xres * 2:
            data = b"".join(data[y * line_length:y * line_length + xres * 2]
                            for y in range(yres))
        img = Image.frombytes("RGB", (xres, yres), decode_565(data, xres * yres))
        img.save(out)
        print(f"saved {out} ({xres}x{yres})")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
