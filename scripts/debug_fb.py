#!/usr/bin/env python3
import fcntl
import os
import struct

fd = os.open("/dev/fb0", os.O_RDONLY)
buf = bytearray(164)
fcntl.ioctl(fd, 0x4600, buf)
v = struct.unpack_from("41I", buf)
print("raw:", v[:26])
print("xres=%d yres=%d xres_v=%d yres_v=%d bpp=%d grayscale=%d length=%d" % v[:7])
print("nonstd=%d activate=%d height=%d width=%d accmode=%d pixclock=%d" % v[7:13])
print("red=%d/%d/%d green=%d/%d/%d blue=%d/%d/%d trans=%d/%d/%d" % v[13:25])
print("line_length=%d" % v[25])
