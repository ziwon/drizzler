"""Controlled IP/retry origin. Run behind a trusted TLS reverse proxy."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import re
from threading import Lock
import time


class RetrySequence:
    def __init__(self):
        self.runs = {}
        self.lock = Lock()

    def next_status(self, run):
        with self.lock:
            now = time.monotonic()
            self.runs = {k: v for k, v in self.runs.items() if now - v[1] < 600}
            if run not in self.runs and len(self.runs) >= 1000:
                return 503
            index, _ = self.runs.get(run, (0, now))
            self.runs[run] = (index + 1, now)
            return (503, 429, 200)[min(index, 2)]


def make_handler(trusted_peer=None):
    sequence = RetrySequence()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not retain URLs, headers, or proxy-related diagnostics.

        def do_GET(self):
            peer = self.client_address[0]
            if trusted_peer and peer == trusted_peer:
                # The reverse proxy MUST overwrite this header, never append it.
                peer = self.headers.get("X-Real-IP", "")
            try:
                peer = str(ipaddress.ip_address(peer))
            except ValueError:
                self.send_error(400)
                return
            if self.path == "/ip":
                status = 200
            elif re.fullmatch(r"/retry/[0-9a-f]{32}", self.path):
                status = sequence.next_status(self.path)
            else:
                self.send_error(404)
                return
            body = json.dumps({"ip": peer}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if status == 429:
                self.send_header("Retry-After", "1")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--trusted-peer", type=ipaddress.ip_address)
    args = parser.parse_args()
    trusted = str(args.trusted_peer) if args.trusted_peer else None
    ThreadingHTTPServer((args.bind, args.port), make_handler(trusted)).serve_forever()


if __name__ == "__main__":
    main()
