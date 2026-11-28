#!/usr/bin/env python3
# Run ON runcater: pixel-diff a /dev/fb0 capture against the expected
# NORMAL / NVLLM (tokenbills down) / OFFLINE screen (P5).
#
# NORMAL:  in-flight list from tokenbills -> badge WITHOUT the "· vLLM"
#          suffix (the in-flight region is excluded from the diff: its
#          content follows real tokenbills traffic, not the mock).
# NVLLM:   tokenbills unreachable -> in-flight "n/a", badge "<STATE> · vLLM".
# OFFLINE: vLLM unreachable.
#
# The cat state (SLEEP/WALK/RUN/...) comes from the EMA speed model and can
# lag after load, so the state is AUTO-DETECTED from the capture's badge
# rather than assumed. The system must be IDLE for the metric rows
# (0/0, 0%, —).
#
# The token-rate graph is expected to be a FULL 60-sample all-zero history:
# run the app with the (static) mock for >= 65 s before capturing so the
# rolling window is filled and pixel-stable.
#
# Usage: verify_fallback.py /tmp/fb-xxx.png [normal|nvllm|offline]
#        [running] [waiting] [kv] [cache_pct]
#   (running/waiting/kv override the idle 0/0/0.0 for a deterministic mock;
#    cache_pct < 0 or omitted -> cache hit "—" (mock has no prefix series))
#
# The status badge is INCLUDED in the diff — that is what we verify here.
import collections
import sys

sys.path.insert(0, "/opt/tokcat")
import tomllib

from PIL import Image, ImageDraw

import tokcat
from capture_fb0 import decode_565

cap_path = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "nvllm"

cfg = tomllib.load(open("/opt/tokcat/config.toml", "rb"))
c = cfg["color"]
bg = tokcat.hexcolor(c["bg"])
badge_bg = tokcat.hexcolor(c["badge_bg"])
accent = tokcat.hexcolor(c["accent"])
error = tokcat.hexcolor(c["error"])
fonts = tokcat.load_fonts(cfg)
cap = Image.open(cap_path).convert("RGB")
W = 480


def render_badge(text, color):
    bw = int(fonts["badge"].getlength(text))
    bx0, by0 = W - 16 - bw - 16, 10
    img = Image.new("RGB", (W, 40), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([bx0, by0, bx0 + bw + 16, by0 + 24], radius=6,
                        fill=badge_bg)
    d.text((bx0 + 8, by0 + 4), text, font=fonts["badge"], fill=color)
    return Image.frombytes("RGB", (W, 40),
                           decode_565(tokcat.rgb_to_565(img), W * 40))


def badge_diff(img):
    diff = 0
    for y in range(8, 36):
        for x in range(150, W):
            if img.getpixel((x, y)) != cap.getpixel((x, y)):
                diff += 1
    return diff


if mode == "offline":
    state = "offline"
else:
    suffix = "" if mode == "normal" else " · vLLM"
    cands = [(s.upper(), error if s in ("offline", "overload")
              else (tokcat.hexcolor(c["warn"]) if s == "sprint" else accent))
             for s in ("sleep", "walk", "run", "sprint", "overload")]
    best = None
    for st, col in cands:
        d = badge_diff(render_badge(st + suffix, col))
        if best is None or d < best[0]:
            best = (d, st)
    state = best[1]
    print("detected badge state:", state, "(diff", str(best[0]) + ")")

exp_running = int(sys.argv[3]) if len(sys.argv) > 3 else 0
exp_waiting = int(sys.argv[4]) if len(sys.argv) > 4 else 0
exp_kv = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
exp_cache = float(sys.argv[6]) if len(sys.argv) > 6 else -1.0
snap = tokcat.Snapshot(
    online=mode != "offline",
    running=exp_running, waiting=exp_waiting, kv=exp_kv,
    mtp_rate=None, decode_tps=None, prefill_tps=None,
    cache_rate=None if exp_cache < 0 else exp_cache / 100.0,
    in_flight=() if mode == "normal" else None,
    state=state,
)
# full all-zero history (static mock -> total_tok_s always 0.0)
hist = collections.deque([0.0] * tokcat.HIST_MAX, maxlen=tokcat.HIST_MAX)
base = tokcat.render_base(cfg, fonts, 0.0, snap, hist)  # clock excluded
exp = Image.frombytes("RGB", (480, 320), decode_565(base, 480 * 320))

pe = exp.load()
# clock is right-aligned before the badge; find the badge's left edge from
# the expected image so only the clock is excluded (badge stays in the diff)
badge_left = None
for x in range(150, 470):
    for y in range(8, 32):
        if all(abs(pe[x, y][i] - (16, 52, 32)[i]) <= 6 for i in range(3)):
            badge_left = x
            break
    if badge_left is not None:
        break

EXCL = [
    (14, 58, 168, 158),                        # cat (TL block, P4 layout)
    (150, 6, (badge_left or 330) - 2, 36),     # clock (time-of-day differs)
]
if mode == "normal":
    EXCL.append((20, 200, 162, 282))           # in-flight list (real traffic)
print("badge left edge:", badge_left)


def excluded(x, y):
    return any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in EXCL)


pc = cap.load()
diffs = 0
first = []
xmin, xmax, ymin, ymax = 999, -1, 999, -1
for y in range(320):
    for x in range(480):
        if excluded(x, y):
            continue
        if pe[x, y] != pc[x, y]:
            diffs += 1
            xmin, xmax = min(xmin, x), max(xmax, x)
            ymin, ymax = min(ymin, y), max(ymax, y)
            if len(first) < 10:
                first.append((x, y, pc[x, y], pe[x, y]))
print(f"{mode} screen pixel diffs (excl. cat/clock{', in-flight' if mode == 'normal' else ''}):", diffs)
if diffs:
    print("diff bbox: x %d..%d  y %d..%d" % (xmin, xmax, ymin, ymax))
for f in first:
    print("  ", f)
