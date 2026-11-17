#!/usr/bin/env python3
# Run ON runcater (as runcater, no sudo): burst-capture /dev/fb0 and probe
# for console artifacts (cursor / text) in vmem.
#
# Phase 1: N idle captures spaced by GAP seconds (catches a cursor that
#         is continuously redrawn/blinking in vmem).
# Phase 2: write one line to /dev/tty1 (console output event -> fbcon
#         redraws text + moves the cursor into vmem), then capture M
#         times fast, to catch it before tokcat's next full frame
#         overwrites vmem (tokcat rewrites all 480x320 px every ~1 s).
#
# The light-gray console fg (VGA 7 -> ~(173,170,173) after the 565
# round-trip) is distinct from tokcat fg (239,239,247); any such pixels
# in the capture are console artifacts.
#
# Usage: burst_probe.py [idle_n] [idle_gap_s] [fast_n]
import fcntl
import os
import struct
import sys
import time

from PIL import Image

sys.path.insert(0, "/opt/tokcat")
from capture_fb0 import decode_565  # noqa: E402

FB = "/dev/fb0"
N_IDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 10
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5
N_FAST = int(sys.argv[3]) if len(sys.argv) > 3 else 8


def open_fb():
    fd = os.open(FB, os.O_RDONLY)
    vinfo = bytearray(160)
    fcntl.ioctl(fd, 0x4600, vinfo)
    v = struct.unpack_from("40I", vinfo)
    finfo = bytearray(80)
    fcntl.ioctl(fd, 0x4602, finfo)
    line_length = struct.unpack_from("I", finfo, 48)[0]
    return fd, v[0], v[1], line_length


def snap(fd, xres, yres, line_length, out):
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, yres * line_length)
    if line_length > xres * 2:
        data = b"".join(data[y * line_length:y * line_length + xres * 2]
                        for y in range(yres))
    img = Image.frombytes("RGB", (xres, yres), decode_565(data, xres * yres))
    img.save(out)
    return img


def probe_gray(img):
    """Console-fg light-gray pixels (150..200 on all channels)."""
    px = img.load()
    w, h = img.size
    hits = [(x, y) for y in range(h) for x in range(w)
            if 150 <= px[x, y][0] <= 200
            and 150 <= px[x, y][1] <= 200
            and 150 <= px[x, y][2] <= 200]
    return hits


fd, xres, yres, line_length = open_fb()
stamp = time.strftime("%y%m%d-%H%M%S")
print("fb %dx%d line_length=%d  idle=%dx%.1fs  fast=%dx" %
      (xres, yres, line_length, N_IDLE, GAP, N_FAST))

imgs, tags = [], []
for i in range(N_IDLE):
    out = "/tmp/burst-%s-idle%02d.png" % (stamp, i)
    imgs.append(snap(fd, xres, yres, line_length, out))
    tags.append("idle%02d" % i)
    if i + 1 < N_IDLE:
        time.sleep(GAP)

# console output event -> fbcon draws the line + cursor into vmem
tty = os.open("/dev/tty1", os.O_WRONLY)
os.write(tty, b"tokcat-vt-probe\n")
os.close(tty)
for i in range(N_FAST):
    out = "/tmp/burst-%s-fast%02d.png" % (stamp, i)
    imgs.append(snap(fd, xres, yres, line_length, out))
    tags.append("fast%02d" % i)
    if i + 1 < N_FAST:
        time.sleep(0.25)

for tag, img in zip(tags, imgs):
    hits = probe_gray(img)
    if hits:
        xs = [p[0] for p in hits]
        ys = [p[1] for p in hits]
        print("%s: gray px %4d  bbox x %d..%d  y %d..%d"
              % (tag, len(hits), min(xs), max(xs), min(ys), max(ys)))
    else:
        print("%s: no gray pixels" % tag)
os.close(fd)
