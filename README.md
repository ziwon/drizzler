# 🌧️ drizzler

**Adaptive, host-aware, large-scale HTTP fetcher and YouTube downloader.**

Drizzler is a production-grade engine designed for high-performance scraping and media extraction. It features intelligent throttling, state persistence, and real-time observability to handle millions of requests without triggering rate limits.

<p align="center">
  <img src="docs/screencapture.png" alt="Drizzler Web Console" width="800" />
</p>

---

## 🚀 Quickstart

Run a simulation with Docker:
```bash
docker run --rm ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=SYRlTISvjww" \
  --simulate
```

> [!IMPORTANT]
> To save files to your host machine, you must mount a volume using `-v $(pwd)/downloads:/app/downloads`.

---

## ✨ Key Features

- **Dual-Mode Engine**: High-speed HTTP fetching + Comprehensive YouTube extraction (Video, Subs, Metadata).
- **Intelligent Throttling**: Bounded Token Bucket with slow-start ramp-up and adaptive rate control.
- **Resilient Design**: Exponential backoff, host-based circuit breakers, and state persistence for resume support.
- **YouTube Optimized**: Automatic CDN host grouping and automated playlist expansion.
- **Proxy Support**: A single HTTP/HTTPS proxy or a shared round-robin proxy list for CLI fetches and yt-dlp jobs.
- **Observability**: Real-time terminal progress bars, ASCII latency histograms, and worker timelines.
- **AI Integration**: Seamless subtitle extraction and AI summarization via Ollama, Gemini, or local models.

---

## 🛠 Usage Guide

### 1. Web & API Fetching
```bash
docker run --rm ghcr.io/ziwon/drizzler:latest \
  "https://httpbin.org/status/200" --rate 2.0 --concurrency 5
```

### 2. YouTube Media Extraction
```bash
# Save to host's ./downloads folder
docker run --rm -v "$(pwd)/downloads:/app/downloads" ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=WKY-KFCvm-A" \
  --write-video --write-info-json --write-thumbnail -o ./downloads
```

### 3. Subtitles & AI Summarization
```bash
# Extract text and save to host (Local Ollama or Gemini)
docker run --rm -v "$(pwd)/downloads:/app/downloads" \
  -e GOOGLE_API_KEY="your_api_key" \
  ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=JvvQTFqWv-U" \
  --summarize --summary-lang ko --llm-model gemini-3-flash-preview -o ./downloads
```

<p align="center">
  <img src="docs/screencapture-summary.png" alt="AI Summary Preview" width="800" />
</p>

### 4. Playlist Processing
```bash
# Automatically expands and saves items to host
docker run --rm -v "$(pwd)/downloads:/app/downloads" ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/playlist?list=PLoROMvodv4rMC33Ucp4aumGNn8SpjEork" \
  -o ./downloads
```

### 5. Proxy Usage

Use a single HTTP/HTTPS proxy with the existing `--proxy` option:

```bash
# Route all requests through a proxy server
docker run --rm ghcr.io/ziwon/drizzler:latest \
  "https://httpbin.org/ip" \
  --proxy "http://user:pass@proxy-host:port"
```

Replace the placeholders (including `port`) with your proxy settings. With neither
proxy option, Drizzler keeps its existing connection behavior.

To rotate proxies, create a UTF-8 file with one HTTP/HTTPS proxy URL per line.
For example, `proxies.txt` (all addresses and credentials below are fictitious):

```text
# Proxies are selected in this order
http://proxy-a.example:8080
https://proxy-b.example:8443
http://example-user:example-password@proxy-c.example:3128
```

```bash
drizzler "https://httpbin.org/ip" --proxy-list ./proxies.txt
```

Docker can read the same file through a **read-only** mount:

```bash
docker run --rm \
  -v "$(pwd)/proxies.txt:/app/proxies.txt:ro" \
  ghcr.io/ziwon/drizzler:latest \
  "https://httpbin.org/ip" --proxy-list /app/proxies.txt
```

Leading/trailing whitespace, blank lines, and lines starting with `#` after
trimming are ignored. Exact duplicate URLs are removed, preserving their first
occurrence. Inline comments are not supported. A one-proxy list is valid.
`--proxy` and `--proxy-list` are mutually exclusive. Unreadable or empty lists,
malformed URLs, and schemes other than HTTP/HTTPS fail before network work starts;
an invalid line rejects the entire list. Percent-encode reserved characters in
credentials. Keep files containing real proxy addresses or credentials outside
version control; proxy credentials are redacted from Drizzler diagnostics.

One in-memory pool is shared by all workers in a run and selects proxies in
round-robin order (`A → B → C → A`). Concurrent work receives proxies in selection
order, which need not match input URL or completion order.

- **HTTP: rotation per request attempt.** Each `session.get` call selects the next
  proxy, including attempts made by the existing retry loop. Automatic redirects
  within that call keep its proxy. Network errors, 429, and 503 retain the existing
  bounded retry policy, exponential backoff, and numeric-seconds `Retry-After`
  handling. Host rate limits and circuit breakers remain shared across proxies.
- **yt-dlp: rotation per call/job.** Each video extraction/download and each
  playlist expansion selects one proxy. That proxy stays fixed for the entire
  invocation, including fragments and yt-dlp's internal retries. Concurrent jobs
  use separate options; playlist expansion and downloads consume the same pool.

Selection errors do not silently fall back to a direct connection. There are no
health checks, permanent blacklists, provider integrations, automatic proxy
discovery, random/weighted strategies, SOCKS support, or fragment-level rotation.
A failing proxy remains in the cycle. Proxy configuration here applies to HTTP
fetches and yt-dlp, not AI provider calls. Web UI/API and Helm configuration have
not been extended with proxy-list controls.

For opt-in live acceptance checks (observed exit IPs, HTTP retry rotation,
yt-dlp job pinning, and the Docker path), see
[Live proxy benchmark](docs/live-proxy-benchmark.md). It requires externally
supplied trial credentials; the default dry run makes no network requests.

---

## 🏗 Scaling to Millions

For enterprise-grade deployments, Drizzler is designed to scale horizontally across Kubernetes clusters.

### Recommended Node Configuration
- **Hardware**: High-core nodes (e.g., 256 CPU / 512GB RAM) handle the high I/O and network density.
- **Storage**: Mount high-speed NAS/NFS storage with `ReadWriteMany` for distributed writes.

### Deployment Pattern: Job-per-Batch
Instead of a single giant run, split URLs into batches (e.g., 50 URLs/batch) and dispatch them as Kubernetes Jobs. This approach ensures:
- **Fairness**: Distributes load across IPs/Proxies.
- **Resilience**: Failed batches can be retried independently without restarting the entire run.
- **Observability**: Job status reflects progress directly in your orchestration layer.

> [!TIP]
> Use **Residential Proxy Rotation** when scaling beyond 100 concurrent requests to YouTube to avoid global IP-based rate limiting.

---

## ⌨️ CLI Reference

| Option | Description |
| :--- | :--- |
| `--write-video` | Download actual video files. |
| `--write-info-json` | Save metadata as JSON. |
| `--write-subs` | Download raw subtitles. |
| `--write-txt` | Extract clean text from subtitles. |
| `--summarize` | Generate AI summaries (requires LLM). |
| `--simulate` | Simulation mode (no file writes). |
| `--rate` | Request rate limit (RPS). |
| `--concurrency` | Maximum active workers. |
| `--proxy` | Proxy URL (e.g., http://user:pass@host:port). |
| `--proxy-list PATH` | UTF-8 HTTP/HTTPS proxy list; round-robin rotation, mutually exclusive with `--proxy`. |
| `--no-progress` | Disable visual UI for CI/CD. |

---

## 🤝 Contribution

Drizzler is open-source. We welcome contributions to:
- Prometheus/Grafana integration.
- Distributed rate-limiting (Redis).
- Extensions to built-in round-robin rotation, such as optional health checks or provider integrations (not currently implemented).

---
**Happy drizzling! 🌧️**
