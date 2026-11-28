#!/usr/bin/env python3
# Unit test (run ON runcater): LivePoller with vLLM /metrics as the primary
# source (P5) and tokenbills /api/live as the best-effort in-flight source.
#
# Usage: python3 test_p2_poller.py [seconds]
#   metrics  = 192.168.1.221:8001/metrics (real vLLM, read-only)
#   inflight = 127.0.0.1:18000 (proxy_live.py — up/down toggled via pkill)
#
# Expect: online stays True while vLLM is up; killing the proxy ->
#         inflight=n/a (badge would gain "· vLLM"), restarting -> list.
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
    "http://192.168.1.221:8001/metrics",
    "http://127.0.0.1:18000/api/live",
    1.0, 2.0, cfg["speed"], on_sample)
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
    inf = "n/a" if s.in_flight is None else f"{len(s.in_flight)}"
    print(f"t={t - t0:5.1f} online={s.online!s:5s} req={s.running}/{s.waiting} "
          f"kv={s.kv:.2f} mtp={mtp} dec={dec} pre={pre} inflight={inf} "
          f"state={s.state}")
