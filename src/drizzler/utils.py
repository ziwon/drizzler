import logging
import random
import time
import signal
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ────────────────────────────────
# Time Helpers
# ────────────────────────────────


def now() -> float:
    return time.perf_counter()


# ────────────────────────────────
# Host Normalization (YouTube CDN aware)
# ────────────────────────────────


def normalize_host(url: str) -> str:
    netloc = urlparse(url).netloc
    if not netloc:
        logger.debug(f"URL {url} has no netloc, using 'default'")
        return "default"
    if ".googlevideo.com" in netloc:
        logger.debug(f"Normalized YouTube CDN host: {netloc} → youtube-cdn")
        return "youtube-cdn"
    if ".ytimg.com" in netloc:
        logger.debug(f"Normalized YouTube static host: {netloc} → youtube-static")
        return "youtube-static"
    if netloc == "www.youtube.com":
        logger.debug(f"Normalized YouTube frontend host: {netloc} → youtube-frontend")
        return "youtube-frontend"  # ← ADD THIS
    return netloc


# ────────────────────────────────
# Header Rotation
# ────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


def get_random_headers(base_headers: dict | None = None) -> dict:
    base = base_headers or {}
    return {
        **base,
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": random.choice(
            ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en;q=0.7"]
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


# ────────────────────────────────
# Signal Handling
# ────────────────────────────────


class GracefulKiller:
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        print("\n[!] Received shutdown signal. Cleaning up...")
        self.kill_now = True
