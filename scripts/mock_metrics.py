#!/usr/bin/env python3
# P2 test helper: mock vLLM /metrics on 127.0.0.1:18002.
# Static gauges + static counters (delta 0 -> rates None -> "—"), so the
# fallback screen is fully deterministic for pixel verification.
#
#   running=2  waiting=0  kv=0.42  -> speed=12.6 -> WALK
#   badge = "WALK · vLLM", req "2/0", KV "42%", MTP/decode/prefill "—",
#   in-flight "n/a"
import http.server

METRICS = """# HELP vllm:num_requests_running x
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="qwen"} 2.0
# HELP vllm:num_requests_waiting x
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{engine="0",model_name="qwen"} 0.0
# HELP vllm:kv_cache_usage_perc x
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{engine="0",model_name="qwen"} 0.42
# HELP vllm:generation_tokens_total x
# TYPE vllm:generation_tokens_total counter
vllm:generation_tokens_total{engine="0",model_name="qwen"} 1000.0
# HELP vllm:prompt_tokens_total x
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{engine="0",model_name="qwen"} 5000.0
vllm:inter_token_latency_seconds_sum{engine="0",model_name="qwen"} 100.0
vllm:time_to_first_token_seconds_sum{engine="0",model_name="qwen"} 50.0
# HELP vllm:spec_decode_num_draft_tokens_total x
# TYPE vllm:spec_decode_num_draft_tokens_total counter
vllm:spec_decode_num_draft_tokens_total{engine="0",model_name="qwen"} 200.0
vllm:spec_decode_num_accepted_tokens_total{engine="0",model_name="qwen"} 150.0
"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = METRICS.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", 18002), H).serve_forever()
