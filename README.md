# 🌧️ drizzler
Adaptive, host-aware, large-scale HTTP fetcher + YouTube video downloader — with intelligent throttling, persistence, retries, and visual observability. <br/>
> ⚠️ Use responsibly. Only download content you have the rights to.

<p align="center">
    <image src="drizzler.png" width="40%">
</p>

## Why drizzler?
Forget one-file toy scripts that hammer servers and get you blocked. **drizzler 🌧️** is a battle-tested, production-grade engine built for:
- Fetching millions of URLs without triggering rate limits
- Downloading YouTube videos at scale — politely and efficiently
- Surviving restarts, network blips, and server throttling
- Giving you full visibility via logs, histograms, and timelines


## Features
- Dual-Mode Engine
  - Fetch webpages (HTTP)
  - Download videos + metadata + thumbnails (via yt-dlp)
  - Extract captions/subtitles as plain text
  - Generate AI summaries using open-source LLMs
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

## Quickstart
```bash
docker run ghcr.io/ziwon/drizzler:latest \
  "https://www.youtube.com/watch?v=SYRlTISvjww" \
  "https://www.youtube.com/watch?v=yebNIHKAC4A" \
  "https://www.youtube.com/watch?v=cPJiPphm8tg" \
  --simulate
```

## Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) installed (`pipx install uv` or see repo)
- [justfile](https://github.com/casey/just) installed (optional)
- [Ollama](https://ollama.ai) installed (optional, for AI summarization)

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

Download Videos with Captions/Subtitles
```
drizzler \
  "https://www.youtube.com/watch?v=Ljf671BSu2g" \
  --write-video \
  --write-subs \
  --output-dir ./downloads \
  --rate 0.5
```

Extract Text Only from Captions (removes timestamps)
```
drizzler \
  "https://www.youtube.com/watch?v=JvvQTFqWv-U" \
  --write-txt \
  --output-dir ./downloads
```

Download Both Subtitles and Extracted Text
```
drizzler \
  "https://www.youtube.com/watch?v=Ljf671BSu2g" \
  --write-subs \
  --write-txt \
  --output-dir ./downloads
```

Generate AI Summary with Ollama (Requires Ollama Running)
```
# First, install and run Ollama with a model
ollama pull qwen2.5:3b  # Multilingual model (Chinese/English/Korean)
ollama serve  # Run in another terminal

# Then use drizzler with summarization
drizzler \
  "https://www.youtube.com/watch?v=JvvQTFqWv-U" \
  --summarize \
  --llm-model qwen2.5:3b \
  --output-dir ./downloads
```

Alternative Models for Summarization
```
# For Chinese content
ollama pull qwen2.5:7b
ollama pull chatglm3:6b

# For general multilingual
ollama pull gemma2:2b
ollama pull llama3.2:3b

# Use with drizzler
drizzler <url> --summarize --llm-model gemma2:2b
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
usage: drizzler [-h] [--write-video] [--write-info-json] [--write-thumbnail] [--write-subs] [--write-txt] [--summarize] [--llm-provider {ollama,transformers}] [--llm-model MODEL] [--simulate] [-o OUTPUT_DIR] [--concurrency CONCURRENCY] [--rate RATE] [--debug] [--log-file LOG_FILE] urls [urls ...]

🌧️ Drizzler: Adaptive HTTP/Video Downloader with Host-Aware Throttling

positional arguments:
  urls                  YouTube URLs or HTTP endpoints to fetch/download

options:
  -h, --help            show this help message and exit
  --write-video         Download actual video file (via yt-dlp) (default: False)
  --write-info-json     Write video metadata to .info.json file (default: False)
  --write-thumbnail     Download thumbnail image (default: False)
  --write-subs         Download subtitles/captions (default: False)
  --write-txt          Extract text only from captions (removes timestamps and metadata) (default: False)
  --summarize          Generate AI summary of caption text in markdown format (default: False)
  --llm-provider       LLM provider for summarization: ollama or transformers (default: ollama)
  --llm-model          Model to use for summarization (default: qwen2.5:3b)
  --simulate            Simulate only — fetch webpage or metadata, but do NOT download files (default: False)
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for downloads (default: ./downloads)
  --concurrency CONCURRENCY
                        Global concurrency (reduce for video downloads) (default: 5)
  --rate RATE           Per-host rate limit (requests per second) (default: 1.0)
  --debug               Enable debug-level logging (default: False)
  --log-file LOG_FILE   Optional file to write logs to (e.g., drizzler.log) (default: None)
```

## Downloading 1M URLs
 Let's deploy drizzler on a 3-node Kubernetes cluster, each with 256 CPU cores and 512GB RAM, is a high-scale, enterprise-grade deployment. We’re likely downloading millions of videos or scraping at massive scale.

### Goal
Run drizzler as a Kubernetes Job or Deployment (depending on use case) with optimal:

- Pod resource requests/limits
- Concurrency and rate settings
- Anti-throttling safeguards
- Logging, monitoring, and restart policies

### Assumptions
- Downloading YouTube videos → high I/O, moderate CPU, network-bound.
- Each node: 256 CPU / 512GB RAM → very powerful → we can run many pods per node.
- To maximize parallelism without triggering YouTube rate limits or CDN blocks.
- `--write-video` → heavy on disk I/O and network.

### Architecture overview
```
[3 Kubernetes Nodes]
│
├── [Pod 1] drizzler --concurrency 10 --rate 0.5 --urls [batch-1]
├── [Pod 2] drizzler --concurrency 8  --rate 0.5 --urls [batch-2]
├── [Pod 3] drizzler --concurrency 10 --rate 0.5 --urls [batch-3]
...
└── [Pod N] ...
```

#### STEP 1: CONTAINERIZE DRIZZLERContainerize dizzler
```Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps for yt-dlp (including ffmpeg for video processing)
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    brotli \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uvc

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv pip install --system --no-cache -e .

# Create downloads dir (In prod, it mounts to the NAS storage)
RUN mkdir -p /downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
ENTRYPOINT ["python", "-m", "drizzler.cli"]
```

#### STEP 2: OPTIMIZE DRIZZLER CONFIG FOR K8S
```bash
drizzler \
  --urls "URL1" "URL2" ... "URL50" \
  --write-video \
  --write-info-json \
  --write-thumbnail \
  --output-dir /downloads \
  --concurrency 8 \          # ← Conservative for video downloads
  --rate 0.5 \               # ← Per host (youtube-frontend, youtube-cdn)
  --log-file /logs/drizzler.log
```
  - 8 concurrency per pod → balances CPU, network, and disk I/O.
  - 0.5 RPS per host → avoids triggering YouTube’s frontend or CDN limits.
  - 50 URLs per pod → manageable batch size.

#### STEP 3: KUBERNETES DEPLOYMENT — JOB PER BATCH (RECOMMENDED)

```yaml
# job-template.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: drizzler-job-{{batch_id}}
  labels:
    app: drizzler
spec:
  parallelism: 1
  completions: 1
  backoffLimit: 2
  template:
    meta
      labels:
        app: drizzler
    spec:
      restartPolicy: OnFailure
      containers:
        - name: drizzler
          image: your-registry/drizzler:latest
          command: ["python", "-m", "drizzler.cli"]
          args:
            - "--write-video"
            - "--write-info-json"
            - "--write-thumbnail"
            - "--output-dir"
            - "/downloads"
            - "--concurrency"
            - "8"
            - "--rate"
            - "0.5"
            - "--log-file"
            - "/logs/drizzler.log"
            - "https://youtube.com/watch?v=..."
            - "https://youtube.com/watch?v=..."
            # ... up to 50 URLs
          resources:
            requests:
              cpu: "4"
              memory: "8Gi"
            limits:
              cpu: "8"
              memory: "16Gi"
          volumeMounts:
            - name: downloads
              mountPath: /downloads
            - name: logs
              mountPath: /logs
      volumes:
        - name: downloads
          persistentVolumeClaim:
            claimName: drizzler-downloads-pvc
        - name: logs
          persistentVolumeClaim:
            claimName: drizzler-logs-pvc
```
####  STEP 4: RESOURCE ALLOCATION — HOW MANY PODS PER NODE?
Each pod:
- Requests: 4 CPU, 8Gi RAM
- Limits: 8 CPU, 16Gi RAM

Each node: 256 CPU, 512Gi RAM
- Max pods per node (by CPU request): 256 / 4 = 64 pods
- Max pods per node (by RAM request): 512 / 8 = 64 pods

Perfectly balanced → 64 pods per node → 192 pods total

> 💡You can go higher (e.g., 128 pods/node) by reducing requests to 2 CPU / 4Gi — but 64 is safer for I/O-heavy work.

#### STEP 5: PVC SETUP — PERSISTENT STORAGE

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
meta
  name: drizzler-downloads-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Ti
  storageClassName: fast-ssd  # ← Use your storage class

---
apiVersion: v1
kind: PersistentVolumeClaim
meta
  name: drizzler-logs-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  storageClassName: fast-ssd
```
  Use `ReadWriteMany` if multiple pods write to same volume (e.g., NFS, CephFS, EFS, GPFS).

> 💡 If not available, mount node-local storage or use separate PVCs per pod.

#### STEP 6: DEPLOYMENT STRATEGY — BATCH PROCESSING
Use a Job Controller (e.g., Argo Workflows, Kueue, or simple script) to:
- Split 1M URLs into 20,000 batches of 50 URLs.
- Submit 192 Jobs (max parallel) → as Jobs complete, submit more.
- Monitor success/failure → retry failed batches.

```bash
#!/bin/bash
# launch-jobs.sh
BATCH_SIZE=50
MAX_JOBS=192

URLS=($(cat urls.txt))  # One URL per line
TOTAL=${#URLS[@]}

for ((i=0; i<TOTAL; i+=BATCH_SIZE)); do
    while [[ $(kubectl get jobs -l app=drizzler --no-headers | wc -l) -ge $MAX_JOBS ]]; do
        sleep 10
    done

    BATCH=("${URLS[@]:i:BATCH_SIZE}")
    JOB_NAME="drizzler-job-$(date +%s)-$i"

    # Generate job YAML with these URLs
    envsubst <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  labels:
    app: drizzler
spec:
  template:
    spec:
      containers:
      - name: drizzler
        image: your-registry/drizzler:latest
        command: ["python", "-m", "drizzler.cli"]
        args:
          - "--write-video"
          - "--write-info-json"
          - "--write-thumbnail"
          - "--output-dir"
          - "/downloads"
          - "--concurrency"
          - "8"
          - "--rate"
          - "0.5"
          - "--log-file"
          - "/logs/\$JOB_NAME.log"
$(for url in "${BATCH[@]}"; do echo "          - \"$url\""; done)
        resources:
          requests:
            cpu: "4"
            memory: "8Gi"
          limits:
            cpu: "8"
            memory: "16Gi"
        volumeMounts:
          - name: downloads
            mountPath: /downloads
          - name: logs
            mountPath: /logs
      restartPolicy: OnFailure
      volumes:
        - name: downloads
          persistentVolumeClaim:
            claimName: drizzler-downloads-pvc
        - name: logs
          persistentVolumeClaim:
            claimName: drizzler-logs-pvc
EOF
done
```

####  STEP 7: MONITORING & OBSERVABILITY
In core.py, expose metrics via callback:

```python
from prometheus_client import Counter, Histogram, start_http_server

REQUESTS_TOTAL = Counter('drizzler_requests_total', 'Total requests', ['status'])
LATENCY_HIST = Histogram('drizzler_request_latency_seconds', 'Request latency')

def prometheus_callback(stats_dict):
    for status, count in stats_dict.get("status_counts", {}).items():
        REQUESTS_TOTAL.labels(status=status).inc(count)
    for lat in self.latencies:  # need to store or pass
        LATENCY_HIST.observe(lat)
```
Then expose /metrics endpoint.

#### STEP 8: ANTI-THROTTLING BEST PRACTICES
Even with 192 pods, you must avoid triggering YouTube’s global/IP-based rate limits.

**Use Proxy Rotation (CRITICAL)**
Modify `core.py` to rotate proxies
```python
# In _fetch_once
proxies = [
    "http://proxy1:3128",
    "http://proxy2:3128",
    # ... or use rotating proxy service
]
proxy = random.choice(proxies)

async with session.get(url, headers=headers, proxy=proxy) as resp:
```
> 💡 Use residential proxies (e.g., BrightData, Oxylabs) — datacenter IPs get blocked fast.


▶ Limit Total RPS per IP

With 192 pods × 0.5 RPS = 96 RPS per IP → **TOO HIGH** for YouTube.

*SOLUTION*: Use proxy per pod or limit global concurrency.


#### FINAL RECOMMENDED SETTINGS PER POD
| Setting             | Value   | Why                          |
| ------------------- | ------- | ---------------------------- |
| `--concurrency`     | 6–8     | Balance CPU, network, disk   |
| `--rate`            | 0.3–0.5 | Conservative for YouTube     |
| CPU request         | 2       | Leave room for system        |
| Memory request      | 8 Gi    | yt-dlp can be memory-heavy   |
| URLs per pod        | 30–50   | Small batches = easy retries |
| Max pods per node   | 64      | 256 CPU / 4 = 64             |
| Total parallel pods | 192     | 3 nodes × 64                 |

### SCALING BEYOND — IF NEEDED
- Add more nodes → linear scale.
- Use Kueue or Argo Workflows for advanced job scheduling.
- Add horizontal pod autoscaler if using Deployment (not Job).
- Use Redis to coordinate global rate limits across pods.

## Contribute
PRs welcome! Ideas:
- Add progress bars
- Support playlists/channels
- Export to Prometheus
- Dockerize for cluster deployment

---

Happy drizzling! 🌧️🎥📊
