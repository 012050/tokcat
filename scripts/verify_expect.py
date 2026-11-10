#!/usr/bin/env python3
# Run ON runcater: render the expected base from /tmp/verify-live.json and
# pixel-diff against /tmp/verify.png (excluding cat, badge, in-flight value).
import json
import sys

sys.path.insert(0, "/opt/tokcat")
import tomllib

from PIL import Image

import tokcat
from capture_fb0 import decode_565

cfg = tomllib.load(open("/opt/tokcat/config.toml", "rb"))
payload = json.load(open("/tmp/verify-live.json"))


class R:
    def read(self):
        return json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


tokcat.urllib.request.urlopen = lambda url, timeout: R()
snap = tokcat.fetch_live("http://x", 2.0)
sm = tokcat.SpeedModel(cfg["speed"])
ema, speed = 0.0, 0.0
for _ in range(60):
    ema, speed = sm.update(snap.decode_tps, snap.kv, snap.waiting)
snap.tok_s, snap.speed = ema, speed
snap.state = tokcat.state_for(cfg["speed"], snap.speed, snap.waiting, snap.online)
print("simulated state:", snap.state, "speed:", round(snap.speed, 1),
      "snap:", snap.running, snap.waiting, round(snap.kv, 3), snap.mtp_rate,
      snap.decode_tps, snap.prefill_tps, snap.in_flight)

fonts = tokcat.load_fonts(cfg)
# capture followed the json by <1s; ts+1 keeps the clock consistent
base = tokcat.render_base(cfg, fonts, payload["ts"] + 1.0, snap)
exp = Image.frombytes("RGB", (480, 320), decode_565(base, 480 * 320))
cap = Image.open("/tmp/verify.png").convert("RGB")

EXCL = [
    (165, 77, 315, 173),   # cat
    (230, 6, 464, 36),     # clock+badge (positions depend on badge width/state)
    (100, 276, 464, 298),  # in-flight value (elapsed may tick)
]


def excluded(x, y):
    return any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in EXCL)


pe, pc = exp.load(), cap.load()
diffs = 0
first = []
for y in range(320):
    for x in range(480):
        if excluded(x, y):
            continue
        if pe[x, y] != pc[x, y]:
            diffs += 1
            if len(first) < 10:
                first.append((x, y, pc[x, y], pe[x, y]))
print("pixel diffs (excl. cat/badge/inflight):", diffs)
for f in first:
    print("  ", f)
