#!/usr/bin/env python3
"""tokcat — 3.5" TFT kiosk: vLLM live status + RunCat on /dev/fb0.

P0 skeleton: no X server. Renders title / clock / status badge and
placeholder metrics directly to /dev/fb0 (16bpp RGB565) via mmap.
Data polling (/api/live) and the cat animation land in P1.
"""

import fcntl
import mmap
import os
import signal
import struct
import sys
import time
import tomllib

from PIL import Image, ImageDraw, ImageFont

FB_DEFAULT = "/dev/fb0"
FBIOGET_VSCREENINFO = 0x4600  # struct fb_var_screeninfo: xres(0) yres(1) ... bpp(6)
FBIOGET_FSCREENINFO = 0x4602  # struct fb_fix_screeninfo: smem_len(24) ... line_length(48)
FONT_DIR = "/usr/share/fonts/truetype/dejavu"

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


def open_fb(path=FB_DEFAULT):
    """Open the framebuffer. Returns (fd, mmap, xres, yres, line_length)."""
    fd = os.open(path, os.O_RDWR)
    vinfo = bytearray(160)  # 40 x u32
    fcntl.ioctl(fd, FBIOGET_VSCREENINFO, vinfo)
    v = struct.unpack_from("40I", vinfo)
    xres, yres, bpp = v[0], v[1], v[6]
    if bpp != 16:
        raise RuntimeError(f"expected 16bpp framebuffer, got {bpp}bpp")
    finfo = bytearray(80)
    fcntl.ioctl(fd, FBIOGET_FSCREENINFO, finfo)
    smem_len = struct.unpack_from("I", finfo, 24)[0]
    line_length = struct.unpack_from("I", finfo, 48)[0]
    mm = mmap.mmap(fd, smem_len)
    return fd, mm, xres, yres, line_length


def hexcolor(s):
    v = int(s.lstrip("#"), 16)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


# lookup tables: 8-bit channel -> 5/6-bit value
_T5 = bytes(i >> 3 for i in range(256))
_T6 = bytes(i >> 2 for i in range(256))


def rgb_to_565(img):
    """Convert an RGB image to little-endian RGB565 bytes (fbtft 16bpp).

    v = (r5 << 11) | (g6 << 5) | b5, stored little-endian per pixel.
    hi byte: r5 at bits 4..0 (fb bits 15..11), g6 top 3 bits at 2..0 (fb 10..8)
    lo byte: g6 bottom 3 bits at 7..5 (fb 7..5), b5 at 4..0 (fb 4..0)
    """
    rgb = img.tobytes()
    r = rgb[0::3].translate(_T5)
    g = rgb[1::3].translate(_T6)
    b = rgb[2::3].translate(_T5)
    n = len(r)
    hi = bytes(((r[i] << 3) | ((g[i] >> 3) & 7)) for i in range(n))
    lo = bytes((b[i] | ((g[i] & 7) << 5)) for i in range(n))
    out = bytearray(2 * n)
    out[0::2] = lo
    out[1::2] = hi
    return bytes(out)


def load_fonts(cfg):
    f = cfg["font"]

    def ttf(name, size):
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

    return {
        "title": ttf("DejaVuSans-Bold.ttf", f["title_size"]),
        "time": ttf("DejaVuSans.ttf", f["time_size"]),
        "badge": ttf("DejaVuSans-Bold.ttf", f["badge_size"]),
        "mono": ttf("DejaVuSansMono.ttf", f["mono_size"]),
        "mono_sm": ttf("DejaVuSansMono.ttf", f["mono_small_size"]),
    }


def draw_kv_row(d, x0, y, pairs, font, fg, dim):
    """Draw (label, value) pairs left to right; label in dim, value in fg."""
    x = x0
    for label, value in pairs:
        d.text((x, y), label, font=font, fill=dim)
        x += d.textlength(label, font=font) + 6
        d.text((x, y), value, font=font, fill=fg)
        x += d.textlength(value, font=font) + 30
    return x


def render(cfg, fonts, now):
    w, h = 480, 320  # fixed panel size
    c = cfg["color"]
    bg, fg = hexcolor(c["bg"]), hexcolor(c["fg"])
    dim, accent = hexcolor(c["dim"]), hexcolor(c["accent"])
    badge_bg = hexcolor(c["badge_bg"])
    sep = (dim[0] // 3, dim[1] // 3, dim[2] // 3)
    m = 16  # margin

    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    # --- top bar: title | time | [status] ---
    d.text((m, 9), cfg["display"]["title"], font=fonts["title"], fill=fg)

    badge = cfg["display"]["status_text"]
    bw = int(d.textlength(badge, font=fonts["badge"]))
    bx0, by0 = w - m - bw - 16, 10
    d.rounded_rectangle([bx0, by0, bx0 + bw + 16, by0 + 24], radius=6, fill=badge_bg)
    d.text((bx0 + 8, by0 + 4), badge, font=fonts["badge"], fill=accent)

    tstr = time.strftime("%H:%M %a %m-%d", time.localtime(now))
    tw = d.textlength(tstr, font=fonts["time"])
    d.text((bx0 - 10 - tw, 13), tstr, font=fonts["time"], fill=dim)

    d.line([(m, 44), (w - m, 44)], fill=sep, width=2)

    # --- center: cat placeholder (P1: RunCat sprite ~150x95) ---
    cx = w // 2
    d.rounded_rectangle([cx - 75, 62, cx + 75, 188], radius=8, outline=dim)
    hint = "[ cat 150x95 ]"
    hw = d.textlength(hint, font=fonts["mono_sm"])
    d.text((cx - hw / 2, 120), hint, font=fonts["mono_sm"], fill=dim)

    # --- metrics rows (P0: placeholders) ---
    draw_kv_row(d, m, 208, [("req", "--/--"), ("KV", "--%"), ("MTP", "--%")],
                fonts["mono"], fg, dim)
    draw_kv_row(d, m, 238, [("decode", "-- t/s"), ("prefill", "-- t/s")],
                fonts["mono"], fg, dim)

    # --- in-flight row (P0: placeholder) ---
    d.line([(m, 268), (w - m, 268)], fill=sep, width=2)
    d.text((m, 280), "in-flight:", font=fonts["mono_sm"], fill=dim)
    d.text((m + d.textlength("in-flight:", font=fonts["mono_sm"]) + 6, 280), "--",
           font=fonts["mono_sm"], fill=fg)

    return img


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/tokcat/config.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    fd, mm, xres, yres, line_length = open_fb()
    fonts = load_fonts(cfg)
    print(f"tokcat: fb0 {xres}x{yres} line_length={line_length}", flush=True)

    last_sec = -1
    while not _stop:
        now = time.time()
        sec = int(now)
        if sec != last_sec:  # P0: re-render every clock tick (P1: animation frames)
            data = rgb_to_565(render(cfg, fonts, now))
            mm[: len(data)] = data
            last_sec = sec
        time.sleep(0.05)

    mm.close()
    os.close(fd)
    print("tokcat: stopped", flush=True)


if __name__ == "__main__":
    main()
