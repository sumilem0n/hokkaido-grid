"""Minimal JSON endpoint over the captured demand data.

Stdlib only, deliberately: a web framework would emit the CORS headers for you,
and the headers are the entire point of this exercise.
"""
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DB_PATH = Path.home() / "hokkaido-grid" / "sql" / "hokkaido.db"
PORT = 8000


def fetch_rows(day: str) -> list[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            "SELECT datetime_jst, demand_mw FROM area_demand "
            "WHERE datetime_jst LIKE ? ORDER BY datetime_jst",
            (f"{day}%",),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/api/demand":
            self.send_error(404, "no such path")
            return

        day = parse_qs(url.query).get("date", ["2026-04-01"])[0]
        try:
            rows = fetch_rows(day)
        except sqlite3.Error as exc:
            self.send_error(500, f"database error: {type(exc).__name__}")
            return

        body = json.dumps({"date": day, "count": len(rows), "rows": rows}).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8001")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8001")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[api] {self.command} {self.path} -> {fmt % args}")


if __name__ == "__main__":
    print(f"[api] serving {DB_PATH} on http://127.0.0.1:{PORT}/api/demand")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
