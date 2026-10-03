# Live proxy acceptance benchmark

This opt-in harness follows PR #1 (merged as `c45ef0b`). It uses the real
`RequestDrizzler._fetch_once`, `_fetch_with_policy`, and `_download_with_ytdlp`
paths. Production routing/retry logic is unchanged. No live credentials are
bundled. This is a small correctness benchmark, not a throughput/load test.

## Prerequisites and safe inputs

- Two to eight distinct HTTP/HTTPS proxy URLs. Ask the provider for **different
  exit IPs** and, for YouTube, **sticky sessions** lasting longer than a job.
  Different proxy URLs do not guarantee different exit IPs. Use percent-encoded
  credentials. A provider rotating every request cannot establish job-long IP
  stickiness merely because Drizzler pins one proxy URL.
- A publicly reachable HTTPS origin you control (below). A local-only origin
  cannot see requests from residential/mobile proxy exits.
- A short public YouTube video you own or may download, ideally under 30 seconds
  and under 25 MiB. No cookies, account login, or playlist. The harness retains
  core's format choice, caps each media file at 25 MiB, uses native downloaders,
  and deletes temporary media on normal exit. The cap is not a strict total
  bandwidth limit; streams without a known size and retries can exceed it.

Install the locked environment; this dependency setup needs network access:

```bash
uv sync --frozen --group test
uv run --frozen python -m benchmarks.proxy_live
# {"status": "not_run", "network": false, ...}; no credentials are read
```

Create the secret file **outside the checkout**, using an editor or a secret
manager; do not paste credentials into commands, issues, or this repository:

```bash
install -d -m 700 "$HOME/.config/drizzler"
install -m 600 /dev/null "$HOME/.config/drizzler/trial-proxies.txt"
${EDITOR:-vi} "$HOME/.config/drizzler/trial-proxies.txt"
export DRIZZLER_BENCH_PROXY_FILE="$HOME/.config/drizzler/trial-proxies.txt"
install -d -m 700 "$HOME/drizzler-benchmark-results"
```

One proxy URL per line; blank lines/comments and duplicates follow PR #1 rules.
Alternatively inject newline-delimited `DRIZZLER_BENCH_PROXIES` from your secret
manager, **instead of** the file variable/`--proxy-file`. Environment variables
are readable by privileged processes; a read-only secret file is preferable.
The harness never writes a proxy list, includes credentials in argv, or emits
raw third-party logs/errors. Results contain only aliases (`p1`, `p2`), observed
public IPs, timings, statuses, byte counts, and versions. Review IPs before sharing.
Files under the checkout and files with group/other permissions are rejected.
Results use exclusive creation and mode 0600; existing files are never overwritten.

## Controlled origin

On a small server reachable by the trial proxies, run:

```bash
python3 benchmarks/origin.py --bind 127.0.0.1 --port 8765 --trusted-peer 127.0.0.1
```

Place a TLS reverse proxy on the same host in front of port 8765. For example,
inside an existing nginx HTTPS server with a valid certificate:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_cache off;
    proxy_intercept_errors off;
    access_log off;
}
```

Keep the Python port private. `--trusted-peer` trusts exactly that socket peer;
the reverse proxy must **overwrite** X-Real-IP from its observed client address.
Do not use a CDN or another proxy in front without correctly configuring trusted
client-IP handling. Otherwise the observation is the CDN's address or spoofable.
`/ip` returns `{"ip": "observed source IP"}`. A unique `/retry/<32-hex-id>` returns
503, then 429 (`Retry-After: 1`), then 200, each with the observed IP. State is
thread-safe, capped at 1,000 runs and expires after 10 minutes. Run **one origin
process** without load balancing so attempts share state. Stop it after testing.

## Native commands

Replace the two public URLs below with your origin and authorized short video.
Run from the checkout. No live request occurs without `--live` AND valid inputs.

```bash
uv run --frozen python -m benchmarks.proxy_live --live --mode http \
  --origin-url https://benchmark.example.com \
  --revision "$(git rev-parse HEAD)" \
  --output "$HOME/drizzler-benchmark-results/native-http.json"

uv run --frozen python -m benchmarks.proxy_live --live \
  --origin-url https://benchmark.example.com \
  --youtube-url 'https://www.youtube.com/watch?v=YOUR_VIDEO_ID' \
  --require-sticky-ip --revision "$(git rev-parse HEAD)" \
  --output "$HOME/drizzler-benchmark-results/native-all.json"
```

Default workload: two complete rounds through the pool, one three-attempt HTTP
retry job, and two sequential YouTube downloads with fresh output directories
and the same shared pool. `--mode ytdlp` runs only YouTube; `--jobs 2|3|4` adjusts
jobs. `--timeout 20` bounds each HTTP request/yt-dlp socket wait, **not the entire
video job**. For a hard runtime budget on Linux, prefix either live command with
`timeout --kill-after=10s 5m`. A timeout/nonzero exit or unfinished report never
counts as a pass. Use a new output filename for each attempt.

## Docker path (production Dockerfile)

The image's default entrypoint is the API (`uvicorn`), so passing CLI flags to the
default entrypoint is insufficient. Build from the exact checkout; do not assume
`latest` contains these changes. Build/setup can download packages but never gets
proxy credentials. The benchmark is mounted read-only, not added to the image:

```bash
docker build --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
  -t drizzler-bench:local .

bash benchmarks/docker-run.sh drizzler-bench:local \
  "$DRIZZLER_BENCH_PROXY_FILE" "$HOME/drizzler-benchmark-results" \
  --live --origin-url https://benchmark.example.com \
  --youtube-url 'https://www.youtube.com/watch?v=YOUR_VIDEO_ID' \
  --require-sticky-ip --output /results/docker-all.json
```

The wrapper validates the source-revision label, checks `drizzler --help` for
`--proxy-list`, and runs the harness dry with `--network none` before the live
container. It overrides the entrypoint explicitly, mounts credentials read-only,
and runs with a read-only root filesystem and temporary media in tmpfs. The
production Dockerfile currently installs dependencies without a frozen uv sync;
compare the recorded package versions with the native report. Native and Docker
are separate runs: **both must pass** to claim both execution paths verified.
Docker runtime/build errors are failures even if a previous report passed.

## Success/failure criteria

| Check | PASS requires | Failure meaning |
|---|---|---|
| HTTP round robin | Two exact `p1 → ... → pN` cycles; all 200 with valid public IPs | Routing/order, connectivity, auth or origin problem |
| Outbound IP rotation | At least two distinct origin-observed IPs in those cycles | Exit rotation not demonstrated; aliases alone are insufficient |
| HTTP retry rotation | Real policy produces 503 → 429 → 200, cyclic proxy aliases, one success and no final error | Retry/route/fixture failure |
| Retry egress change | Observed IP changes between **each** retry attempt | Proxy changed in code but exit change was not demonstrated |
| yt-dlp job proxy pinned | Successful real media file; every observed transport send uses that job's selected proxy; non-probe requests observed | Download failure, bypass, adapter incompatibility, or missing evidence |
| Between-job rotation | Successful jobs select successive proxies from the same pool | Per-job routing failure |
| Sampled sticky IP | Pre/post probes through that same yt-dlp instance see the same public IP | Provider session changed; enforced only with `--require-sticky-ip` |
| Docker | CLI smoke/dry checks and live container succeed with a matching revision label | Container path unverified or broken |

Exit codes: **0** = requested checks passed (or explicit dry run marked
`not_run`), **1** = a live check failed, **2** = configuration/preflight error.
Skipped modes are marked `skip`, never a full-suite pass. No credentials means
configuration error and **zero benchmark traffic**; dry runs do not load secrets.

Observations include per-attempt latency and per-job elapsed time/bytes. They are
acceptance evidence, not statistically meaningful performance comparisons.
Failures are not automatically Drizzler bugs: authentication, provider routing,
blocked exits, YouTube challenges/extractor changes, TLS and origin configuration
can all fail checks. Reports intentionally exclude raw error text.

The yt-dlp adapter observes effective proxy selection at the installed Python
request handlers, including media requests that pass through those handlers. It
does not rewrite proxy routing. Internal transport redirects/retries are not
individually counted. Pre/post IP samples do **not** prove the source IP of every
YouTube/CDN request; provider session/request logs are needed for that stronger
claim. Native downloaders avoid an unobserved external ffmpeg download path.
Dependency changes can break this observation adapter; that must fail, not pass.

Offline regression checks (no live services or local sockets):

```bash
uv run --frozen --group test pytest -q --disable-warnings
uv run --frozen ruff check benchmarks tests/test_live_benchmark.py
```
