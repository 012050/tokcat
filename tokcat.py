#!/usr/bin/env python3
"""tokcat — 3.5" TFT kiosk: vLLM live status + RunCat on /dev/fb0.

P1: polls tokenbills /api/live (1s), shows live metrics and runs the RunCat
animation with the gputils speed model. No X server: renders directly to
/dev/fb0 (16bpp RGB565) via mmap.

Rendering strategy: the static screen (bars / clock / metrics) is composed
once per data sample or clock tick with Pillow ("base" frame). Cat
animation frames are pre-converted RGB565 blobs that get spliced into the
base region, so an animation tick costs a memcpy, not a full re-render.
"""

import fcntl
import json
import mmap
import os
import signal
import struct
import sys
import threading
import time
import tomllib
import urllib.request
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover - pure-python fallback (P0 path)
    _HAVE_NUMPY = False

FB_DEFAULT = "/dev/fb0"
FBIOGET_VSCREENINFO = 0x4600  # struct fb_var_screeninfo: xres(0) yres(1) ... bpp(6)
FBIOGET_FSCREENINFO = 0x4602  # struct fb_fix_screeninfo: smem_len(24) ... line_length(48)
FONT_DIR = "/usr/share/fonts/truetype/dejavu"

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# gputils core.py — frame interval per state (sec/frame, None = static)
FRAME_INTERVALS = {
    "sleep": None,
    "offline": None,
    "walk": 0.55,
    "run": 0.22,
    "sprint": 0.11,
    "overload": 0.08,
}
RUN_FRAME_COUNT = 5
SLEEP_FRAME = RUN_FRAME_COUNT  # index of the sleeping frame in cat565

# cat zone: centered in the 62..188 band; sprite 56x36 scaled to width 150
# (must stay consistent with [cat] width in config.toml)
CAT_W = 150
CAT_H = 96  # 150 * 36 / 56 (56:36 aspect)
CAT_X0 = (480 - CAT_W) // 2
CAT_Y0 = 77  # vertically centered: 62 + (126 - 96) // 2

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


def rgb_to_565(img):
    """Convert an RGB image to little-endian RGB565 bytes (fbtft 16bpp).

    v = (r5 << 11) | (g6 << 5) | b5, stored little-endian per pixel.
    """
    if _HAVE_NUMPY:
        arr = np.frombuffer(img.tobytes(), np.uint8).reshape(-1, 3).astype(np.uint16)
        v = (arr[:, 0] >> 3) * 2048 | (arr[:, 1] >> 2) * 32 | (arr[:, 2] >> 3)
        return v.astype("<u2").tobytes()
    # pure-python fallback (P0 implementation)
    rgb = img.tobytes()
    r = rgb[0::3].translate(bytes(i >> 3 for i in range(256)))
    g = rgb[1::3].translate(bytes(i >> 2 for i in range(256)))
    b = rgb[2::3].translate(bytes(i >> 3 for i in range(256)))
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


# ---------------------------------------------------------------------------
# Live data: /api/live polling + gputils speed model port
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    online: bool = False
    running: int = 0
    waiting: int = 0
    kv: float = 0.0                # 0..1
    mtp_rate: float | None = None  # 0..1
    decode_tps: float | None = None
    prefill_tps: float | None = None
    in_flight: tuple = ()          # pre-formatted "client · tag · model · Ns"
    tok_s: float = 0.0
    speed: float = 0.0
    state: str = "offline"
    error: str | None = None


class SpeedModel:
    """gputils core.py SpeedModel port — EMA(decode rate) + kv + waiting."""

    def __init__(self, scfg):
        self.cfg = scfg
        self.ema = 0.0

    def update(self, decode_tps, kv, waiting):
        rate = decode_tps if decode_tps is not None else 0.0
        alpha = self.cfg["ema_alpha"]
        self.ema = alpha * rate + (1 - alpha) * self.ema
        speed = 100.0 * (
            self.cfg["weight_tok"] * min(self.ema / self.cfg["tok_cap"], 1.0)
            + self.cfg["weight_cache"] * kv
            + self.cfg["weight_wait"] * min(waiting / 5.0, 1.0)
        )
        return self.ema, min(max(speed, 0.0), 100.0)


def state_for(scfg, speed, waiting, online):
    if not online:
        return "offline"
    if waiting >= scfg["wait_overload"] or speed >= scfg["band_overload"]:
        return "overload"
    if speed >= scfg["band_sprint"]:
        return "sprint"
    if speed >= scfg["band_run"]:
        return "run"
    if speed >= 1:
        return "walk"
    return "sleep"


def _opt_f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _path_tag(path):
    parts = [p for p in (path or "").split("/") if p]
    if not parts:
        return "?"
    last = parts[-1]
    if last == "completions":
        return "chat" if len(parts) >= 2 and parts[-2] == "chat" else "completion"
    if last == "embeddings":
        return "embed"
    return last


def _format_in_flight(info):
    client = str(info.get("client") or "?")
    model = str(info.get("model") or "?").rsplit("/", 1)[-1]
    if len(model) > 16:
        model = model[:15] + "…"
    el = float(info.get("elapsed_s") or 0.0)
    return f"{client} · {_path_tag(info.get('path'))} · {model} · {el:.0f}s"


def fetch_live(url, timeout):
    """GET /api/live -> Snapshot. Raises on network/HTTP errors."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    up = payload.get("upstream") or {}
    rates = payload.get("rates") or {}
    ok = bool(up.get("ok"))
    inflight = []
    for item in (payload.get("in_flight") or [])[:3]:
        try:
            inflight.append(_format_in_flight(item))
        except (TypeError, ValueError):
            continue
    return Snapshot(
        online=ok,
        running=int(up.get("requests_running") or 0) if ok else 0,
        waiting=int(up.get("requests_waiting") or 0) if ok else 0,
        kv=_opt_f(up.get("kv_cache_usage")) or 0.0,
        mtp_rate=_opt_f(rates.get("mtp_hit_rate")),
        decode_tps=_opt_f(rates.get("decode_tokens_per_s")),
        prefill_tps=_opt_f(rates.get("prefill_tokens_per_s")),
        in_flight=tuple(inflight),
    )


class LivePoller(threading.Thread):
    """Poll /api/live on a fixed cadence; deliver Snapshots via on_sample.

    The poll loop never dies: any fetch error yields an offline sample
    (mirrors gputils core.Poller).
    """

    def __init__(self, url, interval, timeout, scfg, on_sample):
        super().__init__(daemon=True)
        self.url, self.interval, self.timeout = url, interval, timeout
        self.scfg, self.on_sample = scfg, on_sample
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def run(self):
        model = SpeedModel(self.scfg)
        while not self._stop_evt.is_set():
            t0 = time.monotonic()
            try:
                snap = fetch_live(self.url, self.timeout)
                if snap.online:
                    snap.tok_s, snap.speed = model.update(
                        snap.decode_tps, snap.kv, snap.waiting)
                snap.state = state_for(self.scfg, snap.speed, snap.waiting,
                                       snap.online)
            except Exception as exc:  # noqa: BLE001 - the loop must not die
                snap = Snapshot(online=False, error=str(exc))
            self.on_sample(snap)
            # timeout independent of the poll cadence (see gputils core.Poller)
            self._stop_evt.wait(max(0.2, self.interval - (time.monotonic() - t0)))


class _SnapshotBox:
    """Latest-sample holder shared between the poller thread and main loop."""

    def __init__(self):
        self.lock = threading.Lock()
        self.snap = Snapshot()
        self.seq = 0

    def on_sample(self, snap):
        with self.lock:
            self.snap, self.seq = snap, self.seq + 1

    def take(self):
        with self.lock:
            return self.snap, self.seq


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _prep_cat_frame(path, w, h, color, bg):
    """RGBA silhouette -> bg-composited RGB565 bytes (tinted, scaled).

    Tinting = solid cat color through the silhouette alpha (same approach
    as gputils' cairo mask recolor); composite over the panel bg so the
    region can be spliced with a plain memcpy.
    """
    img = Image.open(path).convert("RGBA").resize((w, h), Image.BILINEAR)
    solid = Image.new("RGBA", img.size, color + (255,))
    tinted = Image.new("RGBA", img.size, (0, 0, 0, 0))
    tinted.paste(solid, (0, 0), img)
    comp = Image.new("RGBA", img.size, bg + (255,))
    comp.paste(tinted, (0, 0), tinted)
    return rgb_to_565(comp.convert("RGB"))


def load_cat_frames(cfg):
    cc, c = cfg["cat"], cfg["color"]
    color, bg = hexcolor(cc["color"]), hexcolor(c["bg"])
    w, h = int(cc["width"]), int(cc["width"] * 36 / 56)
    cwd = os.path.join(APP_DIR, cc["frames_dir"])
    frames = [_prep_cat_frame(os.path.join(cwd, f"cat_{i}.png"), w, h, color, bg)
              for i in range(RUN_FRAME_COUNT)]
    frames.append(_prep_cat_frame(os.path.join(cwd, "sleeping.png"), w, h, color, bg))
    return frames


def render_base(cfg, fonts, now, snap):
    """Full static screen (no cat) -> RGB565 bytes. The cat is spliced later."""
    w, h = 480, 320  # fixed panel size
    c = cfg["color"]
    bg, fg = hexcolor(c["bg"]), hexcolor(c["fg"])
    dim, accent = hexcolor(c["dim"]), hexcolor(c["accent"])
    warn, error = hexcolor(c["warn"]), hexcolor(c["error"])
    badge_bg = hexcolor(c["badge_bg"])
    sep = (dim[0] // 3, dim[1] // 3, dim[2] // 3)
    m = 16  # margin

    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    # --- top bar: title | time | [status] ---
    d.text((m, 9), cfg["display"]["title"], font=fonts["title"], fill=fg)

    badge = snap.state.upper()
    badge_color = {"overload": error, "offline": error, "sprint": warn}.get(
        snap.state, accent)
    bw = int(d.textlength(badge, font=fonts["badge"]))
    bx0, by0 = w - m - bw - 16, 10
    d.rounded_rectangle([bx0, by0, bx0 + bw + 16, by0 + 24], radius=6, fill=badge_bg)
    d.text((bx0 + 8, by0 + 4), badge, font=fonts["badge"], fill=badge_color)

    tstr = time.strftime("%H:%M %a %m-%d", time.localtime(now))
    tw = d.textlength(tstr, font=fonts["time"])
    d.text((bx0 - 10 - tw, 13), tstr, font=fonts["time"], fill=dim)

    d.line([(m, 44), (w - m, 44)], fill=sep, width=2)

    # --- center: cat zone (stays empty — the cat frame is spliced in) ---

    # --- metrics rows ---
    if snap.online:
        req = f"{snap.running}/{snap.waiting}"
        kv = f"{snap.kv * 100:.0f}%"
        mtp = f"{snap.mtp_rate * 100:.0f}%" if snap.mtp_rate is not None else "—"
        dec = f"{snap.decode_tps:.1f} t/s" if snap.decode_tps is not None else "—"
        pre = f"{snap.prefill_tps:.1f} t/s" if snap.prefill_tps is not None else "—"
        inflight = snap.in_flight[0] if snap.in_flight else "—"
    else:
        req = kv = mtp = dec = pre = "—"
        inflight = "n/a"

    draw_kv_row(d, m, 208, [("req", req), ("KV", kv), ("MTP", mtp)],
                fonts["mono"], fg, dim)
    draw_kv_row(d, m, 238, [("decode", dec), ("prefill", pre)],
                fonts["mono"], fg, dim)

    # --- in-flight row ---
    d.line([(m, 268), (w - m, 268)], fill=sep, width=2)
    d.text((m, 280), "in-flight:", font=fonts["mono_sm"], fill=dim)
    d.text((m + d.textlength("in-flight:", font=fonts["mono_sm"]) + 6, 280),
           inflight, font=fonts["mono_sm"], fill=fg)

    return rgb_to_565(img)


def splice_cat(base, cat565, line_length):
    """Copy base and overwrite the cat region with a pre-converted frame."""
    out = bytearray(base)
    row2 = CAT_W * 2
    for y in range(CAT_H):
        off = (CAT_Y0 + y) * line_length + CAT_X0 * 2
        out[off:off + row2] = cat565[y * row2:(y + 1) * row2]
    return out


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/tokcat/config.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    fd, mm, xres, yres, line_length = open_fb()
    fonts = load_fonts(cfg)
    cat565 = load_cat_frames(cfg)
    print(f"tokcat: fb0 {xres}x{yres} line_length={line_length} "
          f"numpy={_HAVE_NUMPY}", flush=True)

    box = _SnapshotBox()
    poll = cfg["poll"]
    poller = LivePoller(poll["primary"], float(poll["interval"]),
                        float(poll.get("timeout", 2.0)), cfg["speed"],
                        box.on_sample)
    poller.start()

    last_base = None
    last_cat = None
    last_seq, last_sec = -1, -1
    frame_idx = 0
    next_anim = 0.0
    while not _stop:
        t = time.monotonic()
        snap, seq = box.take()
        sec = int(t)
        rebuild = (last_base is None or seq != last_seq or sec != last_sec)
        interval = FRAME_INTERVALS[snap.state]
        if interval is None:
            cat_idx = SLEEP_FRAME
        elif t >= next_anim:
            frame_idx = (frame_idx + 1) % RUN_FRAME_COUNT
            next_anim = t + interval
            cat_idx = frame_idx
        else:
            cat_idx = frame_idx  # current run frame stays until the next tick
        if rebuild or cat_idx != last_cat:
            if rebuild:
                last_base = render_base(cfg, fonts, time.time(), snap)
                last_seq, last_sec = seq, sec
            mm[: len(last_base)] = splice_cat(last_base, cat565[cat_idx],
                                              line_length)
            last_cat = cat_idx
        time.sleep(0.02)

    poller.stop()
    mm.close()
    os.close(fd)
    print("tokcat: stopped", flush=True)


if __name__ == "__main__":
    main()
