#!/usr/bin/env python3
"""tokcat — 3.5" TFT kiosk: vLLM live status + RunCat on /dev/fb0.

P1: polls tokenbills /api/live (1s), shows live metrics and runs the RunCat
animation with the gputils speed model. No X server: renders directly to
/dev/fb0 (16bpp RGB565) via mmap.

P2: vLLM /metrics direct fallback — after N consecutive primary failures
(fallback_after) the poller serves 5 metrics straight from vLLM (in-flight
detail unavailable -> "n/a") and the status badge gains a "· vLLM" suffix.
Returns to primary on the first successful probe.

Console VT: the boot getty on /dev/tty1 (fbcon) shares /dev/fb0 and was
flashing its cursor + kernel printk lines over the UI (erased by the next
full frame within ~1 s). While running, tokcat holds the VT in KD_GRAPHICS
mode so fbcon stops drawing entirely; it is restored to KD_TEXT on exit.

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
from collections import deque
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

# Console VT (getty prompt on /dev/tty1) also draws cursor+text into fb0
# (fbcon). While tokcat owns the framebuffer, the VT is put into
# KD_GRAPHICS so fbcon stops drawing entirely (cursor, kernel printk,
# getty redraws) — without it the console cursor flashes over the UI.
VT_DEFAULT = "/dev/tty1"
KDGETMODE = 0x4B3B  # arg: pointer to int (current mode)
KDSETMODE = 0x4B3A  # arg: the mode VALUE itself (vt_kdsetmode(vc, arg))
KD_TEXT = 0x00
KD_GRAPHICS = 0x01

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

# cat zone: top-left block (P4 layout); sprite 56x36 scaled to width 150
# (must stay consistent with [cat] width in config.toml)
CAT_W = 150
CAT_H = 96  # 150 * 36 / 56 (56:36 aspect)
CAT_X0 = 16
CAT_Y0 = 60  # vertically centered in the top-left block (y 48..168)

# token-rate graph history (rolling window, ~1 sample per rebuild ≈ 1s)
HIST_MAX = 60

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


def _vt_get_mode(fd):
    buf = bytearray(4)
    fcntl.ioctl(fd, KDGETMODE, buf)
    return struct.unpack("i", buf)[0]


def grab_vt(path=VT_DEFAULT):
    """Put the console VT into KD_GRAPHICS mode: fbcon stops drawing the
    cursor and text into the framebuffer (verified 2026-11-18: the getty
    cursor + printk lines flash over the UI, erased by the next full
    frame within ~1 s).

    KDSETMODE takes the mode value directly as the ioctl arg (see
    drivers/tty/vt/vt_ioctl.c: vt_kdsetmode(vc, arg)); KDGETMODE takes a
    pointer. Returns (fd, old_mode) or (None, None) when unavailable.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError as exc:
        print(f"tokcat: vt open {path} failed: {exc}", flush=True)
        return None, None
    old_mode = _vt_get_mode(fd)
    if old_mode != KD_GRAPHICS:
        fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS)
    print(f"tokcat: vt {path} mode {old_mode} -> graphics", flush=True)
    return fd, old_mode


def release_vt(fd, old_mode):
    """Restore the console VT (KD_TEXT) and close it. On restore the
    kernel does a full console redraw (buffered printk + prompt), which
    tokcat's next full frame overwrites within ~1 s."""
    if fd is None:
        return
    try:
        if old_mode == KD_TEXT:
            fcntl.ioctl(fd, KDSETMODE, KD_TEXT)
            print(f"tokcat: vt restored to text mode", flush=True)
    except OSError as exc:
        print(f"tokcat: vt release failed: {exc}", flush=True)
    finally:
        os.close(fd)


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
        "mono_xs": ttf("DejaVuSansMono.ttf", f["mono_xs_size"]),
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
    cache_rate: float | None = None  # prefix cache hit rate 0..1 (cumulative, direct vLLM)
    decode_tps: float | None = None
    prefill_tps: float | None = None
    in_flight: tuple | None = None # None = no source (offline/fallback), () = no requests
    source: str | None = None      # "primary" | "fallback" | None
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


def _format_in_flight(info):
    """One-line in-flight entry: 'client · elapsed'."""
    client = str(info.get("client") or "?")
    el = float(info.get("elapsed_s") or 0.0)
    return f"{client} · {el:.0f}s"


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
        source="primary",
    )


# vLLM /metrics names (verified on the tokenbills box 2026-11-10).
# Note: the two latency _sum series carry NO "vllm:" prefix.
_VLLM_NAMES = (
    "num_requests_running", "num_requests_waiting", "kv_cache_usage_perc",
    "generation_tokens_total", "prompt_tokens_total",
    "inter_token_latency_seconds_sum", "time_to_first_token_seconds_sum",
    "spec_decode_num_draft_tokens_total",
    "spec_decode_num_accepted_tokens_total",
    "prefix_cache_queries_total",
    "prefix_cache_hits_total",
)


def fetch_metrics(url, timeout):
    """GET vLLM /metrics (Prometheus text) -> {metric name: float}.

    Labels are stripped; first series per name wins (single-engine box).
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode(errors="replace")
    vals = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, raw = line.rpartition(" ")
        base = name.split("{", 1)[0]
        if base.startswith("vllm:"):
            base = base[len("vllm:"):]
        if base not in vals:
            try:
                vals[base] = float(raw)
            except ValueError:
                continue
    return {k: v for k, v in vals.items() if k in _VLLM_NAMES}


def _delta(prev, cur, key):
    if prev is None or key not in prev or key not in cur:
        return None
    d = cur[key] - prev[key]
    return d if d >= 0 else None  # counter reset -> no rate


def delta_rates(prev, cur):
    """(mtp_rate, decode_tps, prefill_tps) from counter/histogram deltas.

    Mirrors the tokenbills rate definitions (PLAN.md §4.2). None when the
    denominator is missing or zero (e.g. no prefill activity in the window).
    """
    mtp = decode = prefill = None
    d_acc = _delta(prev, cur, "spec_decode_num_accepted_tokens_total")
    d_dra = _delta(prev, cur, "spec_decode_num_draft_tokens_total")
    if d_acc is not None and d_dra is not None and d_dra > 0:
        mtp = min(d_acc / d_dra, 1.0)
    d_gen = _delta(prev, cur, "generation_tokens_total")
    d_itl = _delta(prev, cur, "inter_token_latency_seconds_sum")
    if d_gen is not None and d_itl is not None and d_itl > 0:
        decode = d_gen / d_itl
    d_pro = _delta(prev, cur, "prompt_tokens_total")
    d_ttft = _delta(prev, cur, "time_to_first_token_seconds_sum")
    if d_pro is not None and d_ttft is not None and d_ttft > 0:
        prefill = d_pro / d_ttft
    return mtp, decode, prefill


def prefix_cache_rate(vals):
    """Cumulative prefix cache hit rate = hits / queries (0..1), else None.

    Same figure vLLM itself logs ("Prefix cache hit rate") — a plain ratio of
    the running counters, no window needed.
    """
    q = vals.get("prefix_cache_queries_total")
    h = vals.get("prefix_cache_hits_total")
    if q is None or h is None or q <= 0:
        return None
    return min(h / q, 1.0)


class LivePoller(threading.Thread):
    """Poll the primary (tokenbills /api/live) on a fixed cadence, falling
    back to vLLM /metrics after `fallback_after` consecutive primary
    failures (P2). Returns to primary on the first successful probe.

    In primary mode vLLM /metrics is also fetched each cycle, solely for the
    prefix cache hit rate (tokenbills exposes no such field).

    The poll loop never dies: any fetch error yields an offline sample
    (mirrors gputils core.Poller).
    """

    def __init__(self, primary, fallback, interval, timeout, scfg, on_sample,
                 fallback_after=3):
        super().__init__(daemon=True)
        self.primary, self.fallback = primary, fallback
        self.interval, self.timeout = interval, timeout
        self.fallback_after = fallback_after
        self.scfg, self.on_sample = scfg, on_sample
        self._stop_evt = threading.Event()
        self._mode = "primary"
        self._fails = 0
        self._prev_fb = None  # last vLLM /metrics sample (for rate deltas)

    def stop(self):
        self._stop_evt.set()

    def _set_mode(self, new):
        if new != self._mode:
            print(f"tokcat: poll mode {self._mode} -> {new}", flush=True)
            self._mode = new

    def _poll_once(self, model):
        try:
            snap = fetch_live(self.primary, self.timeout)
            # primary (back) up: reset fail count + fallback delta baseline
            self._set_mode("primary")
            self._fails, self._prev_fb = 0, None
            try:
                # prefix cache rate straight from vLLM (tokenbills has no
                # such field) — best effort, primary data unaffected
                snap.cache_rate = prefix_cache_rate(
                    fetch_metrics(self.fallback, self.timeout))
            except Exception:  # noqa: BLE001 - cache rate is best-effort
                snap.cache_rate = None
            if snap.online:
                snap.tok_s, snap.speed = model.update(
                    snap.decode_tps, snap.kv, snap.waiting)
            return snap
        except Exception:  # noqa: BLE001 - the loop must not die
            self._fails += 1
            if self._mode != "fallback" and self._fails < self.fallback_after:
                # transient window: offline until the primary is confirmed
                return Snapshot(online=False, error="primary unavailable")
            self._set_mode("fallback")
            try:
                vals = fetch_metrics(self.fallback, self.timeout)
                mtp, dec, pre = delta_rates(self._prev_fb, vals)
                snap = Snapshot(
                    online=True,
                    running=int(vals.get("num_requests_running", 0)),
                    waiting=int(vals.get("num_requests_waiting", 0)),
                    kv=float(vals.get("kv_cache_usage_perc", 0.0)),
                    mtp_rate=mtp, decode_tps=dec, prefill_tps=pre,
                    cache_rate=prefix_cache_rate(vals),
                    in_flight=None,  # tokenbills-only detail
                    source="fallback",
                )
                self._prev_fb = vals
            except Exception as exc:  # noqa: BLE001 - both sources down
                snap, self._prev_fb = Snapshot(online=False, error=str(exc)), None
            if snap.online:
                snap.tok_s, snap.speed = model.update(
                    snap.decode_tps, snap.kv, snap.waiting)
            return snap

    def run(self):
        model = SpeedModel(self.scfg)
        while not self._stop_evt.is_set():
            t0 = time.monotonic()
            snap = self._poll_once(model)
            snap.state = state_for(self.scfg, snap.speed, snap.waiting,
                                   snap.online)
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


def total_tok_s(snap):
    """Total token generation rate = running × avg decode (t/s). 0 if no data."""
    if snap.online and snap.decode_tps is not None:
        return snap.running * snap.decode_tps
    return 0.0


def _rate(v):
    """Format a tokens/s value compactly: 1 decimal under 100, else 0."""
    if v is None:
        return "—"
    return f"{v:.1f} t/s" if v < 100 else f"{v:.0f} t/s"


def _blend(c1, c2, t):
    """Linear blend of two RGB colors (t=0 -> c1, t=1 -> c2)."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _wrap(d, text, font, max_w):
    """Greedy word-wrap to max_w pixels; returns a list of lines."""
    words = text.split(" ")
    lines, cur = [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if not cur or d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def draw_gauge(d, cx, cy, r, frac, accent, track, dim, fg, pct_font, lbl_font):
    """Circular 0..1 usage gauge: track ring + accent arc from 12 o'clock."""
    frac = max(0.0, min(1.0, frac))
    bbox = [cx - r, cy - r, cx + r, cy + r]
    d.arc(bbox, start=0, end=359.9, fill=track, width=8)
    if frac > 0:
        d.arc(bbox, start=-90, end=-90 + 360 * frac, fill=accent, width=8)
    lw = d.textlength("KV", font=lbl_font)
    d.text((cx - lw / 2, cy - 22), "KV", font=lbl_font, fill=dim)
    pct = f"{frac * 100:.0f}%"
    pw = d.textlength(pct, font=pct_font)
    d.text((cx - pw / 2, cy - 4), pct, font=pct_font, fill=fg)


def draw_graph(d, x0, y0, w, h, hist, maxlen, accent, dim, bg, vmax=100.0,
               label_font=None):
    """Area chart of a value history (newest at right, right-aligned).

    vmax is a fixed Y-axis max (default 100 tok/s) so the scale is stable and
    comparable over time. Values above vmax are clamped to the top.

    The chart area is enclosed by a full rectangular border (dim) so its max
    height (top edge = vmax) and bottom (0 level) are always visible. With
    label_font, the scale-max label (right) and the current speed (left,
    "t/s") are drawn in a row above the border (outside the chart) so they
    never crowd the data.
    """
    label_h = 15 if label_font is not None else 0
    frame_top = y0 + label_h
    y_base = y0 + h
    # full rectangular border around the chart area only (below the label row)
    d.rectangle([x0, frame_top, x0 + w, y_base], outline=dim, width=1)
    n = len(hist)
    if n > 0:
        vmax = max(vmax, 1.0)
        span = max(maxlen - 1, 1)
        amp = (y_base - frame_top) - 6
        pts = [(x0 + ((maxlen - n + i) / span) * w,
                y_base - 2 - (min(v, vmax) / vmax) * amp)
               for i, v in enumerate(hist)]
        d.polygon([(x0, y_base)] + pts + [(x0 + w, y_base)],
                  fill=_blend(bg, accent, 0.35))
        d.line(pts, fill=accent, width=2)
    # labels sit in the row above the border (outside the chart)
    if label_font is not None:
        top_lbl = f"{vmax:.0f}"
        d.text((x0 + w - d.textlength(top_lbl, font=label_font) - 2, y0),
               top_lbl, font=label_font, fill=dim)
        if n > 0:
            d.text((x0 + 2, y0), f"{hist[-1]:.0f} t/s",
                   font=label_font, fill=accent)


def draw_request_list(d, x0, y0, max_w, items, font, fg):
    """In-flight entries (one line each: 'client · elapsed'), up to 3 items."""
    y = y0
    for item in items[:3]:
        for ln in item.split("\n"):
            for wl in _wrap(d, ln, font, max_w):
                if y >= y0 + 7 * 15:
                    return
                d.text((x0, y), wl, font=font, fill=fg)
                y += 15


def render_base(cfg, fonts, now, snap, hist):
    """Full static screen (no cat) -> RGB565 bytes. The cat is spliced later.

    P4 layout: top-left cat · top-right KV gauge · center metrics (incl. total
    token rate) · bottom-left in-flight list · bottom-right token-rate graph.
    """
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

    # --- top bar: title | time | [status] (unchanged) ---
    d.text((m, 9), cfg["display"]["title"], font=fonts["title"], fill=fg)

    badge = snap.state.upper()
    if snap.online and snap.source == "fallback":
        badge += " · vLLM"
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

    # --- layout columns / rows ---
    lx0, lx1 = 16, 166      # left: cat (top), request list (bottom)
    mx0, mx1 = 174, 334     # center: metrics
    rx0, rx1 = 342, 464     # right: KV gauge (top), graph (bottom)
    ty0, ty1 = 48, 168      # top row
    by0, by1 = 176, 316     # bottom row

    # --- top-right: KV cache gauge (single host -> aggregate) ---
    gcx, gcy = (rx0 + rx1) // 2, ty0 + (ty1 - ty0) // 2
    gr = min(rx1 - rx0, ty1 - ty0) // 2 - 6
    draw_gauge(d, gcx, gcy, gr, snap.kv, accent, sep, dim, fg,
               fonts["mono"], fonts["mono_sm"])

    # --- center: metrics (cache hit / mtp hit / prefill / decode / running /
    #     TOTAL) ---
    hx0, hx1 = mx0 + 6, mx1 - 6
    if snap.online:
        hit = f"{snap.cache_rate * 100:.0f}%" if snap.cache_rate is not None else "—"
        mtp = f"{snap.mtp_rate * 100:.0f}%" if snap.mtp_rate is not None else "—"
        pre = _rate(snap.prefill_tps)
        dec = _rate(snap.decode_tps)
        run = str(snap.running)
    else:
        hit = mtp = pre = dec = run = "—"
    ry = 64
    for label, value in (("cache hit", hit), ("mtp hit", mtp),
                         ("prefill", pre), ("decode", dec), ("× running", run)):
        d.text((hx0, ry), label, font=fonts["mono_sm"], fill=dim)
        vw = d.textlength(value, font=fonts["mono_sm"])
        d.text((hx1 - vw, ry), value, font=fonts["mono_sm"], fill=fg)
        ry += 26
    d.line([(hx0, ry), (hx1, ry)], fill=sep, width=2)
    tval = f"{total_tok_s(snap):.1f} t/s"
    d.text((hx0, ry + 14), "TOTAL", font=fonts["mono_sm"], fill=dim)
    tw2 = d.textlength(tval, font=fonts["mono"])
    d.text((hx1 - tw2, ry + 8), tval, font=fonts["mono"], fill=accent)

    # --- bottom-left: in-flight request list ---
    d.text((lx0 + 6, by0 + 6), "in-flight", font=fonts["mono_sm"], fill=dim)
    if not snap.online or snap.in_flight is None:
        d.text((lx0 + 6, by0 + 28), "n/a", font=fonts["mono_sm"], fill=dim)
    elif snap.in_flight:
        draw_request_list(d, lx0 + 6, by0 + 28, lx1 - lx0 - 12,
                          list(snap.in_flight), fonts["mono_xs"], fg)
    else:
        d.text((lx0 + 6, by0 + 28), "—", font=fonts["mono_sm"], fill=dim)

    # --- bottom-right: total token-rate graph (fixed Y max + labels) ---
    gmax = float(cfg["display"].get("graph_max_tok_s", 100.0))
    draw_graph(d, rx0, by0 + 6, rx1 - rx0, 107, hist, HIST_MAX, accent, dim, bg,
               gmax, fonts["mono_xs"])
    d.text((rx0 + 2, by1 - 14), "total tok/s", font=fonts["mono_sm"], fill=dim)

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

    vt_fd, vt_old = grab_vt()
    fd = mm = None
    poller = None
    try:
        fd, mm, xres, yres, line_length = open_fb()
        fonts = load_fonts(cfg)
        cat565 = load_cat_frames(cfg)
        print(f"tokcat: fb0 {xres}x{yres} line_length={line_length} "
              f"numpy={_HAVE_NUMPY}", flush=True)

        box = _SnapshotBox()
        poll = cfg["poll"]
        poller = LivePoller(poll["primary"], poll["fallback"],
                            float(poll["interval"]),
                            float(poll.get("timeout", 2.0)),
                            cfg["speed"], box.on_sample,
                            int(poll.get("fallback_after", 3)))
        poller.start()

        last_base = None
        last_cat = None
        last_seq, last_sec = -1, -1
        frame_idx = 0
        next_anim = 0.0
        hist = deque(maxlen=HIST_MAX)  # total token-rate history for the graph
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
                    hist.append(total_tok_s(snap))
                    last_base = render_base(cfg, fonts, time.time(), snap, hist)
                    last_seq, last_sec = seq, sec
                mm[: len(last_base)] = splice_cat(last_base, cat565[cat_idx],
                                                  line_length)
                last_cat = cat_idx
            time.sleep(0.02)
    finally:
        if poller is not None:
            poller.stop()
        if mm is not None:
            mm.close()
        if fd is not None:
            os.close(fd)
        release_vt(vt_fd, vt_old)
    print("tokcat: stopped", flush=True)


if __name__ == "__main__":
    main()
