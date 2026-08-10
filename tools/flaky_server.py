#!/usr/bin/env python
"""Fail the first FAIL_TIMES requests with 503 + Retry-After, then serve 200.

    python tools/flaky_server.py        # 127.0.0.1:8099

Edit FAIL_TIMES between runs and restart -- the counter is process state, so
a restart is the reset. Stdlib only and no threading: one request at a time
is exactly the shape the retry loop makes.

Not a test fixture. It lives in tools/ because nothing in hokkaido_grid/
imports it and pytest never collects it.
"""

import http.server

FAIL_TIMES = 99      # run 1: 2. run 2: 99.
PORT = 8099

# Seconds, or None to omit the header. 2 differs from BASE_DELAY, which is
# what makes run 1 legible: a first sleep of 2s could only have come from the
# header. Run 2 wants the bare formula, so set this to None there -- left at 2
# the sleeps are 2, 2, 2 and the doubling it is meant to show is invisible.
RETRY_AFTER = None
BODY = b"date,demand\n20260802,1193000\n"

seen = 0


class Handler(http.server.BaseHTTPRequestHandler):
    # Default protocol_version, i.e. HTTP/1.0: respond, close, accept the next.
    # HTTP/1.1 here breaks the runs -- mechanism unverified.

    def do_GET(self):
        global seen
        seen += 1
        if seen <= FAIL_TIMES:
            self.send_response(503)
            if RETRY_AFTER is not None:
                self.send_header("Retry-After", str(RETRY_AFTER))
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.log_message("request %d -> 503 (Retry-After: %s)",
                             seen, RETRY_AFTER)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)
        self.log_message("request %d -> 200", seen)


if __name__ == "__main__":
    print(f"flaky server on http://127.0.0.1:{PORT} "
          f"(FAIL_TIMES={FAIL_TIMES}, Retry-After={RETRY_AFTER})")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
