"""
Quick sanity test: drizzled(throttled) GETs against a set of URLs.
Run: uv run examples/fetch_with_drizzler.py
"""
import asyncio
import os

from drizzler import RequestDrizzler

URLS = [
    "https://example.com/",
    "https://httpbin.org/get",
] * 10

async def main():
    per_host_rate = 3.0
    per_host_burst = 2
    per_host_conc = 2
    global_conc = 6

    d = RequestDrizzler(
        URLS,
        per_host_rate=per_host_rate,
        per_host_burst=per_host_burst,
        per_host_concurrency=per_host_conc,
        global_concurrency=global_conc,
        request_timeout_s=float(os.getenv("HTTP_REQUEST_TIMEOUT_S", "10")),
        max_retries=3,
        backoff_base_s=0.5,
        slow_start_ramp_up_s=6.0,
        histogram_bins=24,
        timeline_width=100,
    )
    stats = await d.run()
    print("\nStats:", stats)

if __name__ == "__main__":
    asyncio.run(main())