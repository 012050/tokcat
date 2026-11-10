#!/usr/bin/env python3
# P2 unit test (run ON runcater): LivePoller primary/fallback transitions.
#
# Usage: python3 test_p2_poller.py [seconds]
#   primary  = 127.0.0.1:18000 (proxy_live.py — up/down toggled via pkill)
#   fallback = 192.168.1.221:8001/metrics (real vLLM, read-only)
#
# Expect: dead primary -> 3 offline samples, then source=fallback;
#         live primary -> source=primary.
import sys
import time

sys.path.insert(0, "/opt/tokcat")
import tomllib

import tokcat

cfg = tomllib.load(open("/opt/tokcat/config.toml", "rb"))
samples = []


def on_sample(s):
    samples.append((time.monotonic(), s))


poller = tokcat.LivePoller(
    "http://127.0.0.1:18000/api/live",
    "http://192.168.1.221:8001/metrics",
    1.0, 2.0, cfg["speed"], on_sample, fallback_after=3)
poller.start()
t_end = time.monotonic() + float(sys.argv[1] if len(sys.argv) > 1 else 8)
while time.monotonic() < t_end:
    time.sleep(0.2)
poller.stop()

t0 = samples[0][0] if samples else 0.0
for t, s in samples:
    dec = f"{s.decode_tps:.1f}" if s.decode_tps is not None else "-"
    pre = f"{s.prefill_tps:.1f}" if s.prefill_tps is not None else "-"
    mtp = f"{s.mtp_rate:.2f}" if s.mtp_rate is not None else "-"
    print(f"t={t - t0:5.1f} src={str(s.source):9s} online={s.online!s:5s} "
          f"req={s.running}/{s.waiting} kv={s.kv:.2f} mtp={mtp} "
          f"dec={dec} pre={pre} inflight={s.in_flight} state={s.state}")
