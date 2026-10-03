#!/usr/bin/env bash
# Usage: bash benchmarks/docker-run.sh IMAGE EXTERNAL_PROXY_FILE EXTERNAL_RESULTS_DIR [harness args]
set -euo pipefail
if (( $# < 3 )); then
  echo 'Usage: docker-run.sh IMAGE PROXY_FILE RESULTS_DIR [harness args]' >&2
  exit 2
fi
image=$1
proxy_file=$(realpath "$2")
results_dir=$(realpath "$3")
shift 3
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
case "$proxy_file/" in "$repo/"*) echo 'Proxy file must be outside checkout' >&2; exit 2;; esac
case "$results_dir/" in "$repo/"*) echo 'Results must be outside checkout' >&2; exit 2;; esac
test -f "$proxy_file"
test -d "$results_dir"
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]] || [[ "$revision" != "$(git -C "$repo" rev-parse HEAD)" ]]; then
  echo 'Build the image from this checkout with the documented revision label first' >&2
  exit 2
fi
# The production image defaults to uvicorn. Check the actual CLI explicitly.
docker run --rm --network none --entrypoint drizzler "$image" --help | grep -q -- '--proxy-list'
docker run --rm --network none \
  --mount "type=bind,src=$repo/benchmarks,dst=/app/benchmarks,readonly" \
  --entrypoint python "$image" -m benchmarks.proxy_live
# A missing --live remains a dry run; the harness refuses missing credentials.
# File contents never enter argv, environment, image layers, or Docker inspect.
exec docker run --rm --init --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m \
  --mount "type=bind,src=$repo/benchmarks,dst=/app/benchmarks,readonly" \
  --mount "type=bind,src=$proxy_file,dst=/run/secrets/proxies,readonly" \
  --mount "type=bind,src=$results_dir,dst=/results" \
  --entrypoint python "$image" -m benchmarks.proxy_live \
  --proxy-file /run/secrets/proxies --revision "$revision" "$@"
