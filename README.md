# drizzler

Adaptive host-aware throttling for HTTP fetches + a **minimal YouTube download test** (via `yt-dlp`).
> ⚠️ Use responsibly. Only download content you have the rights to.

<p align="center">
    <image src="drizzler.png" width="50%">
</p>

## Features
- **Bounded Token Bucket** – avoids unbounded token accumulation, eliminating micro-bursts that could trigger server throttling.
- **Slow Start Ramp-Up** – requests gradually increase to the configured rate, preventing sudden load spikes.
- **Per-Host Concurrency & Rate Limits** – enforces fairness across multiple hosts/domains.
- **Adaptive Backoff** – respects Retry-After headers and applies exponential backoff + jitter on transient errors.
- **Detailed Metrics** – computes percentiles (p50/p90/p95/p99), error rates, and status distributions.
- **Visual Insights** – ASCII latency histogram and per-worker timeline (Gantt-like) for quick debugging of request patterns.

## Prerequisites
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) installed (`pipx install uv` or see repo)

## Setup
```bash
uv venv
uv pip install -e .
cp .env.sample .env  # edit as needed
```

## Run drizzeld(throttled) fetch example
```bash
uv run python examples/fetch_with_drizzler.py
```
This prints latency histogram and a worker timeline.

## Run YouTube download test
```bash
# simulate only (metadata fetch; no file writes)
 uv run examples/download_youtube.py "https://www.youtube.com/watch?v=m0Db3CAxzsE"
[youtube] Extracting URL: https://www.youtube.com/watch?v=m0Db3CAxzsE
[youtube] m0Db3CAxzsE: Downloading webpage
[youtube] m0Db3CAxzsE: Downloading tv simply player API JSON
[youtube] m0Db3CAxzsE: Downloading tv client config
[youtube] m0Db3CAxzsE: Downloading tv player API JSON
Title: YOASOBI - 군청(群青) | 시라유키 히나 Cover
ID: m0Db3CAxzsE
Duration: 249
Uploader: 시라유키 히나 SHIRAYUKI HINA
Formats (sample): ['sb3', 'sb2', 'sb1', 'sb0', '249']

# actually download
 uv run examples/download_youtube.py --write "https://www.youtube.com/watch?v=m0Db3CAxzsE"
[youtube] Extracting URL: https://www.youtube.com/watch?v=m0Db3CAxzsE
[youtube] m0Db3CAxzsE: Downloading webpage
[youtube] m0Db3CAxzsE: Downloading tv simply player API JSON
[youtube] m0Db3CAxzsE: Downloading tv client config
[youtube] m0Db3CAxzsE: Downloading tv player API JSON
[info] m0Db3CAxzsE: Downloading 1 format(s): 399+251
[download] Sleeping 4.00 seconds as required by the site...
[download] Destination: downloads/YOASOBI_-_Cover-m0Db3CAxzsE.f399.mp4
[download] 100% of   32.00MiB in 00:00:01 at 27.67MiB/s
[download] Destination: downloads/YOASOBI_-_Cover-m0Db3CAxzsE.f251.webm
[download] 100% of    4.03MiB in 00:00:00 at 39.37MiB/s
[Merger] Merging formats into "downloads/YOASOBI_-_Cover-m0Db3CAxzsE.webm"
Deleting original file downloads/YOASOBI_-_Cover-m0Db3CAxzsE.f399.mp4 (pass -k to keep)
Deleting original file downloads/YOASOBI_-_Cover-m0Db3CAxzsE.f251.webm (pass -k to keep)

# with cookies (optional)
# put a Netscape-format cookies.txt somewhere and set YTDLP_COOKIES_PATH in .env
```

## Notes
- The HTTP drizzler is **not** meant to bypass platform rules. It reduces micro-bursts and respects `Retry-After`.
- `yt-dlp` has many options (format selection, rate limiting, proxies). Add them in `build_ydl_opts()` as needed.