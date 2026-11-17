#!/usr/bin/env python3
# Run ON runcater as root: get/set the console VT mode (linux/kd.h).
#   KDGETMODE = 0x4B3B, KDSETMODE = 0x4B3A, KD_TEXT=0, KD_GRAPHICS=1
# Usage: vt_set.py [0|1]   (no arg = get only)
import fcntl
import os
import struct
import sys

fd = os.open("/dev/tty1", os.O_RDWR)
buf = bytearray(4)
fcntl.ioctl(fd, 0x4B3B, buf)
print("current mode:", struct.unpack("i", buf)[0])
if len(sys.argv) > 1:
    # KDSETMODE takes the mode value DIRECTLY as the ioctl arg (not a
    # pointer) — see drivers/tty/vt/vt_ioctl.c vt_kdsetmode(vc, arg).
    new = int(sys.argv[1])
    fcntl.ioctl(fd, 0x4B3A, new)
    buf2 = bytearray(4)
    fcntl.ioctl(fd, 0x4B3B, buf2)
    print("new mode:", struct.unpack("i", buf2)[0])
os.close(fd)
