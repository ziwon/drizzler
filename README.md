# 🌧️ drizzler
Adaptive, host-aware, large-scale HTTP fetcher + YouTube video downloader — with intelligent throttling, persistence, retries, and visual observability. <br/>
> ⚠️ Use responsibly. Only download content you have the rights to. 

<p align="center">
    <image src="drizzler.png" width="50%">
</p>

## Why drizzler?
Forget one-file toy scripts that hammer servers and get you blocked. **drizzler** is a battle-tested, production-grade engine built for:
- Fetching millions of URLs without triggering rate limits
- Downloading YouTube videos at scale — politely and efficiently
- Surviving restarts, network blips, and server throttling
- Giving you full visibility via logs, histograms, and timelines


## Features
- Dual-Mode Engine
  - Fetch webpages (HTTP)
  - Download videos + metadata + thumbnails (via yt-dlp)
  - All under the same adaptive throttling umbrella.

- YouTube-Optimized by Design
   - Groups *.googlevideo.com CDN hosts to avoid per-host throttling.
   - Automatically strips whitespace/malformed URLs.
   - Applies conservative defaults (start at 0.5–1.0 RPS).

- Intelligent Throttling & Concurrency
   - Bounded Token Bucket — prevents micro-bursts that trigger 429s.
   - Slow Start Ramp-Up — gradually increases load to avoid shocking servers.
   - Per-Host Rate & Concurrency Limits — fairness across domains
   - Adaptive Rate Control — slows down on 429/503, speeds up on success
   - Circuit Breakers — auto-pauses misbehaving hosts to save quota.

- Resilient & Production-Ready
   - Exponential Backoff + Jitter — handles transient errors gracefully.
   - Respects Retry-After Headers — plays nice with server cooldowns.
   - State Persistence — resumes token buckets, cooldowns, and breakers after restart.
   - Graceful Shutdown — Ctrl+C saves progress and exits cleanly.
   - Deduplication — never fetches the same URL twice.

- Observability & Debugging
   - Structured Logging — real-time console + optional file output.
   - ASCII Latency Histogram — visualize p50/p90/p95/p99.
   - Per-Worker Timeline (Gantt Chart) — debug request patterns visually
   - Detailed Metrics — success/error rates, status code distributions.
   - Metrics Callbacks — plug in Prometheus, StatsD, or custom exporters.

- Anti-Detection & Politeness
   - Header Rotation — randomizes User-Agent, Accept-Language, etc
   - Host-Aware Throttling — respects logical service boundaries.- Configurable Concurrency — avoid overwhelming targets.

- CLI-First Experience
   - Full command-line interface:
  `-write-video`, `--write-info-json`, `--write-thumbnail`, `--simulate`, `--output-dir`, `--concurrency`, `--rate`, `--debug`, `--log-file`
   - Install once, run anywhere: `drizzler "https://youtube.com/..." --write-video`

## Prerequisites
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) installed (`pipx install uv` or see repo)

## Setup
```bash
uv venv
uv pip install -e .
cp .env.sample .env  # edit as needed
```

## Usage
Fetch Webpages (HTTP Mode)
```
drizzler \
  "https://httpbin.org/delay/1" \
  "https://httpbin.org/status/200" \
  --rate 2.0 \
  --concurrency 5 \
  --debug
```

Download YouTube Videos
```
drizzler \
  "https://www.youtube.com/watch?v=WKY-KFCvm-A" \
  --write-video \
  --write-info-json \
  --write-thumbnail \
  --output-dir ./downloads \
  --concurrency 3 \
  --rate 0.8 \
  --debug
```

Simulate Only (Metadata Extraction, No File Writes)
```
drizzler \
  "https://www.youtube.com/watch?v=m0Db3CAxzsE" \
  --simulate \
  --debug
```

Log to File + Quiet Run
```
drizzler \
  "https://www.youtube.com/watch?v=fAgAE9JmnOs" \
  --write-video \
  --log-file drizzler_run.log
```

## Sample Output
```
$ drizzler \
  "https://www.youtube.com/watch?v=m0Db3CAxzsE" \
  "https://www.youtube.com/watch?v=fAgAE9JmnOs" \
  "https://www.youtube.com/watch?v=WKY-KFCvm-A" \
  --write-video \
  --write-info-json \
  --write-thumbnail \
  --output-dir ./downloads \
  --concurrency 3 \
  --rate 0.8
2025-09-06 20:16:20 | INFO     | drizzler.core        | Initialized Drizzler with 3 URLs, global_concurrency=3, per_host_rate=0.8
2025-09-06 20:16:20 | INFO     | root                 | Starting Drizzler with 3 URLs | Mode: DOWNLOAD | Concurrency: 3 | Rate: 0.8 RPS
2025-09-06 20:16:20 | INFO     | drizzler.core        | Starting Drizzler run...
2025-09-06 20:16:20 | INFO     | drizzler.persistence | Loaded state for 2 buckets and 2 breakers
2025-09-06 20:16:20 | INFO     | drizzler.core        | Loaded 2 persisted buckets, 2 breakers
2025-09-06 20:16:20 | INFO     | drizzler.throttling  | Token bucket 'httpbin.org' started
2025-09-06 20:16:20 | INFO     | drizzler.throttling  | Token bucket 'youtube-frontend' started
2025-09-06 20:16:20 | INFO     | drizzler.core        | Starting 3 requests with 3 workers
2025-09-06 20:16:24 | INFO     | drizzler.core        | [W2] Downloaded https://www.youtube.com/watch?v=WKY-KFCvm-A in 4.16s
2025-09-06 20:16:25 | INFO     | drizzler.core        | [W1] Downloaded https://www.youtube.com/watch?v=fAgAE9JmnOs in 5.38s
2025-09-06 20:16:29 | INFO     | drizzler.core        | [W0] Downloaded https://www.youtube.com/watch?v=m0Db3CAxzsE in 8.72s
2025-09-06 20:16:29 | INFO     | drizzler.persistence | State saved to drizzler_state.json
2025-09-06 20:16:29 | INFO     | drizzler.core        | State persisted
2025-09-06 20:16:29 | INFO     | drizzler.throttling  | Token bucket 'httpbin.org' stopped
2025-09-06 20:16:32 | INFO     | drizzler.throttling  | Token bucket 'youtube-frontend' stopped
2025-09-06 20:16:32 | INFO     | drizzler.metrics     | Stats computed: success=3, errors=0, mean=6.086s, p95=5.380s, error_rate=0.0%

============================================================
Latency Histogram
4.160s – 4.388s | ######################################## (1)
4.388s – 4.616s | # (0)
4.616s – 4.844s | # (0)
4.844s – 5.072s | # (0)
5.072s – 5.299s | # (0)
5.299s – 5.527s | ######################################## (1)
5.527s – 5.755s | # (0)
5.755s – 5.983s | # (0)
5.983s – 6.211s | # (0)
6.211s – 6.439s | # (0)
6.439s – 6.667s | # (0)
6.667s – 6.894s | # (0)
6.894s – 7.122s | # (0)
7.122s – 7.350s | # (0)
7.350s – 7.578s | # (0)
7.578s – 7.806s | # (0)
7.806s – 8.034s | # (0)
8.034s – 8.262s | # (0)
8.262s – 8.490s | # (0)
8.490s – 8.717s | ######################################## (1)

Request Timeline (relative seconds)
W00 |================================================================================|
W01 |=================================================                               |
W02 |======================================                                          |
0s                                                                          ~ 8.72s
============================================================
2025-09-06 20:16:32 | INFO     | drizzler.core        | Run completed: 3 successes, 0 errors, error_rate=0.00%
2025-09-06 20:16:32 | INFO     | root                 | Run completed: 3 succeeded, 0 failed | Error rate: 0.0% | Mean latency: 6.09s
```

## CLI Options
```
$ drizzler --help
usage: drizzler [-h] [--write-video] [--write-info-json] [--write-thumbnail] [--simulate] [-o OUTPUT_DIR] [--concurrency CONCURRENCY] [--rate RATE] [--debug] [--log-file LOG_FILE] urls [urls ...]

🌧️ Drizzler: Adaptive HTTP/Video Downloader with Host-Aware Throttling

positional arguments:
  urls                  YouTube URLs or HTTP endpoints to fetch/download

options:
  -h, --help            show this help message and exit
  --write-video         Download actual video file (via yt-dlp) (default: False)
  --write-info-json     Write video metadata to .info.json file (default: False)
  --write-thumbnail     Download thumbnail image (default: False)
  --simulate            Simulate only — fetch webpage or metadata, but do NOT download files (default: False)
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for downloads (default: ./downloads)
  --concurrency CONCURRENCY
                        Global concurrency (reduce for video downloads) (default: 5)
  --rate RATE           Per-host rate limit (requests per second) (default: 1.0)
  --debug               Enable debug-level logging (default: False)
  --log-file LOG_FILE   Optional file to write logs to (e.g., drizzler.log) (default: None)
```


## Contribute
PRs welcome! Ideas:
- Add progress bars
- Support playlists/channels
- Export to Prometheus
- Dockerize for cluster deployment

---

Happy drizzling! 🌧️🎥📊