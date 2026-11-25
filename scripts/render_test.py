#!/usr/bin/env python3
"""Render P4 base frames to PNGs WITHOUT touching /dev/fb0 or the VT.

Verifies the new layout (cat TL, KV gauge TR, metrics C, request list BL,
token-rate graph BR) purely in-process. The running tokcat service is not
affected (no framebuffer open, no KD_GRAPHICS grab).

Usage: render_test.py <tokcat_dir> <config.toml> <out_prefix>
   -> <out_prefix>_online.png / _fallback.png / _offline.png
"""
import collections
import sys
import time
import tomllib

sys.path.insert(0, sys.argv[1])
import tokcat  # noqa: E402
from PIL import Image  # noqa: E402

# render_base returns rgb_to_565(img); patch it to raw RGB bytes for preview.
tokcat.rgb_to_565 = lambda img: img.tobytes()

with open(sys.argv[2], "rb") as f:
    cfg = tomllib.load(f)
fonts = tokcat.load_fonts(cfg)


def save(name, snap, hist):
    data = tokcat.render_base(cfg, fonts, time.time(), snap, hist)
    Image.frombytes("RGB", (480, 320), data).save(name)
    print("saved", name)


# a plausible total-token-rate history (t/s)
_hist_vals = (4, 6, 9, 14, 20, 27, 29, 27, 25, 27, 28, 27,
              26, 27, 27, 28, 27, 27, 26, 27, 27, 27, 27, 27)
hist = collections.deque((float(v) for v in _hist_vals), maxlen=tokcat.HIST_MAX)

_inf = [
    {"client": "127.0.0.1", "path": "/v1/chat/completions",
     "model": "orcarouter/Qwen3.8-27B-Uncensored-FP8", "elapsed_s": 42},
    {"client": "10.0.0.5", "path": "/v1/embeddings",
     "model": "qwen", "elapsed_s": 3},
    {"client": "192.168.1.9", "path": "/v1/completions",
     "model": "qwen3.8", "elapsed_s": 12},
]
online = tokcat.Snapshot(
    online=True, running=3, waiting=1, kv=0.42,
    mtp_rate=0.92, decode_tps=27.0, prefill_tps=28154.6, cache_rate=0.63,
    in_flight=tuple(tokcat._format_in_flight(i) for i in _inf),
    source="primary", state="run")
save(sys.argv[3] + "_online.png", online, hist)

fallback = tokcat.Snapshot(
    online=True, running=2, waiting=0, kv=0.55,
    mtp_rate=None, decode_tps=18.0, prefill_tps=None, cache_rate=0.63,
    in_flight=None, source="fallback", state="walk")
save(sys.argv[3] + "_fallback.png", fallback, hist)

offline = tokcat.Snapshot(online=False, source=None, state="offline")
save(sys.argv[3] + "_offline.png", offline,
     collections.deque(maxlen=tokcat.HIST_MAX))

print("done")
