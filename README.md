# 🌧️ drizzler

**Adaptive, host-aware, large-scale HTTP fetcher and YouTube downloader.**

Drizzler is a production-grade engine designed for high-performance scraping and media extraction. It features intelligent throttling, state persistence, and real-time observability to handle millions of requests without triggering rate limits.

---

## 🚀 Quickstart

Run a simulation with Docker:
```bash
docker run ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=SYRlTISvjww" \
  --simulate
```

---

## ✨ Key Features

- **Dual-Mode Engine**: High-speed HTTP fetching + Comprehensive YouTube extraction (Video, Subs, Metadata).
- **Intelligent Throttling**: Bounded Token Bucket with slow-start ramp-up and adaptive rate control.
- **Resilient Design**: Exponential backoff, host-based circuit breakers, and state persistence for resume support.
- **YouTube Optimized**: Automatic CDN host grouping and automated playlist expansion.
- **Observability**: Real-time terminal progress bars, ASCII latency histograms, and worker timelines.
- **AI Integration**: Seamless subtitle extraction and AI summarization via Ollama/Transformers.

---

## 🛠 Usage Guide

### 1. Web & API Fetching
```bash
docker run ghcr.io/ziwon/drizzler:latest \
  "https://httpbin.org/status/200" --rate 2.0 --concurrency 5
```

### 2. YouTube Media Extraction
```bash
# Download video, metadata, and thumbnail
docker run ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=WKY-KFCvm-A" \
  --write-video --write-info-json --write-thumbnail -o ./downloads
```

### 3. Subtitles & AI Summarization
```bash
# Extract text and generate AI summary (requires Ollama)
docker run ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=JvvQTFqWv-U" \
  --summarize --llm-model qwen2.5:3b -o ./downloads
```

### 4. Playlist Processing
```bash
# Automatically expands any YouTube playlist link
docker run ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/playlist?list=PLoROMvodv4rMC33Ucp4aumGNn8SpjEork" \
  --simulate
```

---

## 🏗 Scaling to Millions (Reference Architecture)

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
| `--no-progress` | Disable visual UI for CI/CD. |

---

## 🤝 Contribution

Drizzler is open-source. We welcome contributions to:
- Prometheus/Grafana integration.
- Distributed rate-limiting (Redis).
- Enhanced proxy rotation logic.

---
**Happy drizzling! 🌧️**
