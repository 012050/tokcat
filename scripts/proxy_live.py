#!/usr/bin/env python3
# P2 test helper: local proxy 127.0.0.1:18000/api/live -> tokenbills :8000.
# Lets us toggle the "primary" up/down from the Pi without touching the
# tokenbills production box. Start:
#   nohup python3 /tmp/proxy_live.py > /tmp/proxy_live.log 2>&1 &
# Stop: pkill -f proxy_live.py
import http.server
import urllib.request

UP = "http://192.168.1.221:8000/api/live"


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with urllib.request.urlopen(UP, timeout=3) as r:
                body = r.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(502)
            self.end_headers()

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", 18000), H).serve_forever()
