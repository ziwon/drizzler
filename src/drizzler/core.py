import asyncio
import aiohttp
import random
import logging

from typing import Iterable, Dict, List, Optional, Tuple, Set, Callable
from collections import defaultdict
from .models import TimelineType, MetricsCallback
from .utils import now, normalize_host, get_random_headers, GracefulKiller
from .throttling import BoundedTokenBucket, HostCircuitBreaker
from .metrics import compute_stats
from .rendering import render_latency_histogram, render_timeline
from .persistence import StateManager


logger = logging.getLogger(__name__)

class RequestDrizzler:
    def __init__(
        self,
        urls: Iterable[str],
        per_host_rate: float = 1.0,  # YouTube: start conservative
        per_host_burst: int = 2,
        per_host_concurrency: int = 2,
        global_concurrency: int = 10,
        request_timeout_s: float = 30.0,  # YouTube can be slow
        max_retries: int = 5,  # More retries for YouTube
        backoff_base_s: float = 1.0,
        backoff_jitter_ratio: float = 0.2,
        slow_start_ramp_up_s: float = 15.0,
        default_headers: Optional[Dict[str, str]] = None,
        histogram_bins: int = 20,
        timeline_width: int = 80,
        state_file: str = "drizzler_state.json",
        metrics_callback: Optional[MetricsCallback] = None,
        deduplicate: bool = True,
        download_video: bool = False,          # --write-video
        download_info: bool = False,           # --write-info-json
        download_thumbnail: bool = False,      # --write-thumbnail
        output_dir: str = "./downloads",       # -o
    ) -> None:
        self.urls = [u.strip() for u in urls]
        if deduplicate:
            seen = set()
            deduped = []
            for u in self.urls:
                if u not in seen:
                    seen.add(u)
                    deduped.append(u)
            self.urls = deduped

        self.per_host_rate = per_host_rate
        self.per_host_burst = per_host_burst
        self.per_host_concurrency = per_host_concurrency
        self.global_concurrency = global_concurrency
        self.request_timeout_s = request_timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_jitter_ratio = backoff_jitter_ratio
        self.slow_start_ramp_up_s = slow_start_ramp_up_s
        self.default_headers = default_headers
        self.histogram_bins = histogram_bins
        self.timeline_width = timeline_width
        self.metrics_callback = metrics_callback
        self.download_video = download_video
        self.download_info = download_info
        self.download_thumbnail = download_thumbnail
        self.output_dir = output_dir

        import os
        os.makedirs(self.output_dir, exist_ok=True)

        # Runtime state
        self.latencies: List[float] = []
        self.success_count = 0
        self.error_count = 0
        self.status_counts: Dict[int, int] = defaultdict(int)
        self.timeline: TimelineType = defaultdict(list)
        self._t0: Optional[float] = None

        # Concurrency control
        self._global_sema = asyncio.Semaphore(self.global_concurrency)
        self._host_sema: Dict[str, asyncio.Semaphore] = {}
        self._buckets: Dict[str, BoundedTokenBucket] = {}
        self._breakers: Dict[str, HostCircuitBreaker] = {}

        # Persistence
        self.state_manager = StateManager(state_file)
        self.graceful_killer = GracefulKiller()

        logger.info(
            f"Initialized Drizzler with {len(self.urls)} URLs, "
            f"global_concurrency={global_concurrency}, "
            f"per_host_rate={per_host_rate}"
        )

    # ────────────────────────────────
    # Host Structs Management
    # ────────────────────────────────

    async def _ensure_host_structs(self, host: str) -> None:
        if host not in self._buckets:
            logger.debug(f"Initializing semaphore for host: {host} (concurrency={self.per_host_concurrency})")
            self._buckets[host] = BoundedTokenBucket(
                self.per_host_rate,
                burst=self.per_host_burst,
                ramp_up_s=self.slow_start_ramp_up_s,
                name=host,
            )
            await self._buckets[host].start()

        if host not in self._host_sema:
            logger.debug(f"Initializing semaphore for host: {host} (concurrency={self.per_host_concurrency})")
            self._host_sema[host] = asyncio.Semaphore(self.per_host_concurrency)

        if host not in self._breakers:
            logger.debug(f"Initializing circuit breaker for host: {host}")
            self._breakers[host] = HostCircuitBreaker(failure_threshold=5, cooldown_s=60.0)

    # ────────────────────────────────
    # Retry & Backoff Logic
    # ────────────────────────────────

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.backoff_base_s * (2 ** (attempt - 1))
        jitter = 1.0 + random.uniform(-self.backoff_jitter_ratio, self.backoff_jitter_ratio)
        await asyncio.sleep(max(0.05, base * jitter))

    @staticmethod
    def _retry_after_seconds_from_headers(headers: Dict[str, str]) -> Optional[float]:
        ra = headers.get("Retry-After")
        if not ra:
            return None
        try:
            secs = float(ra)
            return max(0.0, secs)
        except Exception:
            return None

    # ────────────────────────────────
    # HTTP Fetch Logic
    # ────────────────────────────────
    async def _fetch_once(self, session: aiohttp.ClientSession, url: str) -> Tuple[Optional[int], Optional[float], Dict[str, str]]:
        start = now()
        headers = get_random_headers(self.default_headers)
        try:
            async with session.get(url, headers=headers) as resp:
                content = await resp.read()  # or just: await resp.text() for HTML
                latency = now() - start
                headers_dict = {k: v for k, v in resp.headers.items()}
                logger.debug(f"Fetched {url}: status={resp.status}, size={len(content)} bytes")
                return resp.status, latency, headers_dict
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Connection error for {url}: {e}")
            return None, None, {}
        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {url}")
            return None, None, {}
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None, None, {}


    # ────────────────────────────────
    # yt-dlp Download Logic
    # ────────────────────────────────
    async def _download_with_ytdlp(self, url: str, worker_id: int) -> Tuple[bool, Optional[float], Optional[int]]:
        """Download video/info/thumbnail using yt-dlp in thread pool."""
        start = now()
        loop = asyncio.get_event_loop()

        def _run_ytdlp():
            import yt_dlp
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'outtmpl': f'{self.output_dir}/%(id)s.%(ext)s',
                'format': 'best[ext=mp4]/best',  # prefer mp4
                'writesubtitles': False,
                'writeinfojson': self.download_info,
                'writethumbnail': self.download_thumbnail,
                'skip_download': not self.download_video,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info is None:
                        return False, None
                    return True, info.get('url')  # actual CDN URL if downloaded
            except Exception as e:
                logger.error(f"[W{worker_id}] yt-dlp failed for {url}: {e}")
                return False, None

        try:
            success, cdn_url = await loop.run_in_executor(None, _run_ytdlp)
            latency = now() - start

            if success:
                logger.info(f"[W{worker_id}] Downloaded {url} in {latency:.2f}s")
                # Extract host from cdn_url if available for timeline/stats
                host = normalize_host(cdn_url) if cdn_url else "youtube-frontend"
                return True, latency, host
            else:
                logger.warning(f"[W{worker_id}] yt-dlp failed for {url}")
                return False, latency, "youtube-frontend"
        except Exception as e:
            latency = now() - start
            logger.error(f"[W{worker_id}] Exception in yt-dlp executor: {e}")
            return False, latency, "youtube-frontend"


    async def _fetch_with_policy(
        self, session: aiohttp.ClientSession, url: str, worker_id: int
    ) -> None:
        # If download_video is True, use yt-dlp instead of HTTP fetch
        if self.download_video or self.download_info or self.download_thumbnail:
            success, latency, host = await self._download_with_ytdlp(url, worker_id)

            # Record in stats
            if success and latency is not None:
                self.success_count += 1
                self.latencies.append(latency)
                if self._t0 is not None:
                    end_req = (now() - self._t0)
                    start_req = end_req - latency
                    self.timeline[worker_id].append((start_req, end_req, host, 200))
            else:
                self.error_count += 1
                if self._t0 is not None:
                    end_req = now() - self._t0
                    start_req = end_req - (latency or 0)
                    self.timeline[worker_id].append((start_req, end_req, host, None))

            return

        # Otherwise, proceed with normal HTTP fetch logic
        host = normalize_host(url)
        await self._ensure_host_structs(host)
        bucket = self._buckets[host]
        breaker = self._breakers[host]

        if not breaker.can_attempt():
            logger.warning(f"[W{worker_id}] Circuit breaker OPEN for {host}, skipping {url}")
            self.error_count += 1
            end_req = now()
            if self._t0 is not None:
                self.timeline[worker_id].append((now() - self._t0, end_req - self._t0, host, None))
            return

        async with self._global_sema, self._host_sema[host]:
            logger.debug(f"[W{worker_id}] Acquiring token for {host}")
            await bucket.acquire()
            logger.debug(f"[W{worker_id}] Token acquired for {host}")

            start_req = now()
            last_status: Optional[int] = None

            for attempt in range(1, self.max_retries + 1):
                if self.graceful_killer.kill_now:
                    logger.info(f"[W{worker_id}] Graceful shutdown requested. Aborting {url}")
                    return

                logger.debug(f"[W{worker_id}] Attempt {attempt} for {url}")
                status, latency, headers = await self._fetch_once(session, url)
                last_status = status

                if status is not None:
                    self.status_counts[status] += 1
                    logger.debug(f"[W{worker_id}] Received status {status} for {url}")

                if status and 200 <= status < 400 and latency is not None:
                    self.success_count += 1
                    self.latencies.append(latency)
                    breaker.record_success()
                    if attempt == 1:
                        bucket.adjust_rate(1.05)
                    end_req = start_req + latency
                    if self._t0 is not None:
                        self.timeline[worker_id].append(
                            (start_req - self._t0, end_req - self._t0, host, status)
                        )
                    logger.info(f"[W{worker_id}] Success {url} ({latency:.3f}s, status={status})")
                    return

                retry_after_s = self._retry_after_seconds_from_headers(headers)
                should_retry = False

                # Handle 429, 503, or network errors with retries
                if status in (429, 503) or status is None:
                    breaker.record_failure()
                    bucket.adjust_rate(0.8)
                    if retry_after_s and retry_after_s > 0:
                        logger.warning(f"[W{worker_id}] Retry-After: {retry_after_s:.1f}s for {url}")
                        await bucket.cooldown_until(now() + retry_after_s)
                        await asyncio.sleep(retry_after_s)
                        should_retry = True
                    elif attempt < self.max_retries:
                        await self._sleep_backoff(attempt)
                        should_retry = True
                        logger.debug(f"[W{worker_id}] Backing off before retry {attempt + 1}")

                if not should_retry:
                    break

            # If we reach here, all attempts failed
            self.error_count += 1
            end_req = now()
            if self._t0 is not None:
                self.timeline[worker_id].append(
                    (start_req - self._t0, end_req - self._t0, host, last_status)
                )
            logger.warning(f"[W{worker_id}] Failed {url} after {self.max_retries} attempts. Last status: {last_status}")

    # ────────────────────────────────
    # Main Runner
    # ────────────────────────────────

    async def run(self):
        logger.info("Starting Drizzler run...")

        # Load persisted state
        bucket_config = lambda name: {
            "rate_per_sec": self.per_host_rate,
            "burst": self.per_host_burst,
            "ramp_up_s": self.slow_start_ramp_up_s,
            "name": name,
        }
        breaker_config = lambda name: {"failure_threshold": 5, "cooldown_s": 60.0}

        loaded_buckets, loaded_breakers = self.state_manager.load_state(
            bucket_config, breaker_config
        )
        self._buckets.update(loaded_buckets)
        self._breakers.update(loaded_breakers)
        logger.info(f"Loaded {len(loaded_buckets)} persisted buckets, {len(loaded_breakers)} breakers")

        for bucket in self._buckets.values():
            if bucket._task is None:  # Not started yet
                await bucket.start()
                logger.debug(f"Started loaded bucket: {bucket.name}")

        # Ensure all hosts are initialized
        hosts = {normalize_host(u) for u in self.urls}
        for h in hosts:
            await self._ensure_host_structs(h)

        connector = aiohttp.TCPConnector(limit=0)
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_s)
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout
        ) as session:
            q = asyncio.Queue()
            for idx, u in enumerate(self.urls):
                await q.put((idx, u))

            self._t0 = now()
            logger.info(f"Starting {len(self.urls)} requests with {self.global_concurrency} workers")

            async def worker(worker_id: int):
                while not self.graceful_killer.kill_now:
                    try:
                        _, u = await asyncio.wait_for(q.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if q.empty():
                            break
                        continue
                    except asyncio.CancelledError:
                        break
                    try:
                        await self._fetch_with_policy(session, u, worker_id)
                    finally:
                        q.task_done()
                        if self.graceful_killer.kill_now:
                            break

                logger.debug(f"Worker {worker_id} stopped")

            workers = [
                asyncio.create_task(worker(i)) for i in range(self.global_concurrency)
            ]

            try:
                await q.join()
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Cancelling workers...")
                pass

            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        # Persist state before exit
        self.state_manager.save_state(self._buckets, self._breakers)
        logger.info("State persisted")

        # Stop all buckets
        await asyncio.gather(
            *[b.stop() for b in self._buckets.values()], return_exceptions=True
        )

        # Compute and render final stats
        stats = compute_stats(
            self.latencies,
            self.success_count,
            self.error_count,
            self.status_counts,
            self.metrics_callback,
        )

        print("\n" + "="*60)
        print(render_latency_histogram(self.latencies, self.histogram_bins))
        print()
        print(render_timeline(self.timeline, self.timeline_width))
        print("="*60)

        logger.info(
            f"Run completed: {stats.success} successes, {stats.errors} errors, "
            f"error_rate={stats.error_rate*100:.2f}%"
        )

        return stats