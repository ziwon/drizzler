import asyncio
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .ascii_render import render_latency_histogram, render_timeline


def now() -> float:
    return time.perf_counter()


@dataclass
class Stats:
    total: int
    success: int
    errors: int
    mean: Optional[float]
    std: Optional[float]
    p50: Optional[float]
    p90: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    min_lat: Optional[float]
    max_lat: Optional[float]
    error_rate: float
    status_counts: Dict[int, int]


class BoundedTokenBucket:
    def __init__(
        self,
        rate_per_sec: float,
        burst: int = 2,
        jitter_ratio: float = 0.15,
        ramp_up_s: float = 10.0,
        name: str = "",
    ) -> None:
        assert rate_per_sec > 0 and burst >= 1
        self.rate = rate_per_sec
        self.burst = burst
        self.q: asyncio.Queue = asyncio.Queue(maxsize=burst)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.jitter_ratio = jitter_ratio
        self.ramp_up_s = ramp_up_s
        self._start_t: Optional[float] = None
        self.name = name
        self._cooldown_until: float = 0.0
        self._cooldown_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._start_t = now()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._stop.set()
            await self._task
            self._task = None

    async def acquire(self) -> None:
        async with self._cooldown_lock:
            cd = self._cooldown_until - now()
        if cd > 0:
            await asyncio.sleep(cd)
        await self.q.get()
        self.q.task_done()

    async def cooldown_until(self, wake_ts: float) -> None:
        async with self._cooldown_lock:
            if wake_ts > self._cooldown_until:
                self._cooldown_until = wake_ts

    def _current_rate(self) -> float:
        if self.ramp_up_s <= 0 or self._start_t is None:
            return self.rate
        elapsed = max(0.0, now() - self._start_t)
        base = 0.2 * self.rate
        r = base + (self.rate - base) * min(1.0, elapsed / self.ramp_up_s)
        return max(0.1, r)

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                r = self._current_rate()
                delay = 1.0 / r
                jitter = 1.0 + random.uniform(-self.jitter_ratio, self.jitter_ratio)
                delay *= max(0.2, jitter)
                if self.q.full():
                    await asyncio.sleep(min(0.01, delay))
                    continue
                await self.q.put(None)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass


class RequestDrizzler:
    def __init__(
        self,
        urls: Iterable[str],
        per_host_rate: float = 5.0,
        per_host_burst: int = 2,
        per_host_concurrency: int = 2,
        global_concurrency: int = 10,
        request_timeout_s: float = 10.0,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        backoff_jitter_ratio: float = 0.2,
        slow_start_ramp_up_s: float = 10.0,
        default_headers: Optional[Dict[str, str]] = None,
        histogram_bins: int = 20,
        timeline_width: int = 80,
    ) -> None:
        self.urls = list(urls)
        self.per_host_rate = per_host_rate
        self.per_host_burst = per_host_burst
        self.per_host_concurrency = per_host_concurrency
        self.global_concurrency = global_concurrency
        self.request_timeout_s = request_timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_jitter_ratio = backoff_jitter_ratio
        self.slow_start_ramp_up_s = slow_start_ramp_up_s
        self.default_headers = default_headers or {
            "User-Agent": "Drizzler/1.0 (+contact@restack.tech)"
        }
        self.histogram_bins = histogram_bins
        self.timeline_width = timeline_width

        self.latencies: List[float] = []
        self.success_count = 0
        self.error_count = 0
        self.status_counts: Dict[int, int] = defaultdict(int)

        self._buckets: Dict[str, BoundedTokenBucket] = {}
        self._host_sema: Dict[str, asyncio.Semaphore] = {}
        self._global_sema = asyncio.Semaphore(self.global_concurrency)

        self._t0: Optional[float] = None
        self.timeline: Dict[int, List[Tuple[float, float, str, Optional[int]]]] = defaultdict(list)

    def _host_of(self, url: str) -> str:
        return urlparse(url).netloc or "default"

    async def _ensure_host_structs(self, host: str) -> None:
        if host not in self._buckets:
            self._buckets[host] = BoundedTokenBucket(
                self.per_host_rate,
                burst=self.per_host_burst,
                ramp_up_s=self.slow_start_ramp_up_s,
                name=host,
            )
            await self._buckets[host].start()
        if host not in self._host_sema:
            self._host_sema[host] = asyncio.Semaphore(self.per_host_concurrency)

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.backoff_base_s * (2 ** (attempt - 1))
        jitter = 1.0 + random.uniform(-self.backoff_jitter_ratio, self.backoff_jitter_ratio)
        await asyncio.sleep(max(0.05, base * jitter))

    @staticmethod
    def _retry_after_seconds_from_headers(headers: Dict[str, str]) -> Optional[float]:
        if not headers:
            return None
        ra = headers.get("Retry-After")
        if not ra:
            return None
        try:
            secs = float(ra)
            return max(0.0, secs)
        except Exception:
            return None

    async def _fetch_once(
        self, session: aiohttp.ClientSession, url: str
    ) -> Tuple[Optional[int], Optional[float], Dict[str, str]]:
        start = now()
        try:
            async with session.get(url) as resp:
                await resp.read()
                latency = now() - start
                headers = {k: v for k, v in resp.headers.items()}
                return resp.status, latency, headers
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None, None, {}

    async def _fetch_with_policy(
        self, session: aiohttp.ClientSession, url: str, worker_id: int
    ) -> None:
        host = self._host_of(url)
        await self._ensure_host_structs(host)
        bucket = self._buckets[host]

        async with self._global_sema, self._host_sema[host]:
            await bucket.acquire()

            last_status: Optional[int] = None
            start_req = now()
            for attempt in range(1, self.max_retries + 1):
                status, latency, headers = await self._fetch_once(session, url)
                last_status = status

                if status is not None:
                    self.status_counts[status] += 1

                if status and 200 <= status < 400 and latency is not None:
                    self.success_count += 1
                    self.latencies.append(latency)
                    end_req = start_req + latency
                    if self._t0 is not None:
                        self.timeline[worker_id].append(
                            (start_req - self._t0, end_req - self._t0, host, status)
                        )
                    return

                retry_after_s = self._retry_after_seconds_from_headers(headers)
                if status in (429, 503) or status is None:
                    if retry_after_s and retry_after_s > 0:
                        await bucket.cooldown_until(now() + retry_after_s)
                        await asyncio.sleep(retry_after_s)
                    elif attempt < self.max_retries:
                        await self._sleep_backoff(attempt)
                        continue

                self.error_count += 1
                end_req = now()
                if self._t0 is not None:
                    self.timeline[worker_id].append(
                        (start_req - self._t0, end_req - self._t0, host, last_status)
                    )
                return

    def compute_stats(self):
        total = self.success_count + self.error_count
        if not total:
            return None

        n = len(self.latencies)
        if n == 0:
            return {
                "total": total,
                "success": self.success_count,
                "errors": self.error_count,
                "mean": None,
                "std": None,
                "p50": None,
                "p90": None,
                "p95": None,
                "p99": None,
                "min": None,
                "max": None,
                "error_rate": self.error_count / total,
                "status_counts": dict(self.status_counts),
            }

        mean = sum(self.latencies) / n
        sum_sq = sum(x * x for x in self.latencies)
        std = math.sqrt(max(0.0, (sum_sq / n) - (mean * mean)))

        sl = sorted(self.latencies)
        pct = lambda p: sl[max(0, min(n - 1, int(p * (n - 1))))]

        return {
            "total": total,
            "success": self.success_count,
            "errors": self.error_count,
            "mean": mean,
            "std": std,
            "p50": pct(0.50),
            "p90": pct(0.90),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "min": sl[0],
            "max": sl[-1],
            "error_rate": self.error_count / total,
            "status_counts": dict(self.status_counts),
        }

    async def run(self):
        hosts = {self._host_of(u) for u in self.urls}
        for h in hosts:
            await self._ensure_host_structs(h)

        connector = aiohttp.TCPConnector(limit=0)
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_s)
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, headers=self.default_headers
        ) as session:
            q: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
            for idx, u in enumerate(self.urls):
                await q.put((idx, u))

            self._t0 = now()

            async def worker(worker_id: int):
                while True:
                    try:
                        _, u = await q.get()
                    except asyncio.CancelledError:
                        return
                    try:
                        await self._fetch_with_policy(session, u, worker_id)
                    finally:
                        q.task_done()

            workers = [asyncio.create_task(worker(i)) for i in range(self.global_concurrency)]
            await q.join()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        await asyncio.gather(*[b.stop() for b in self._buckets.values()], return_exceptions=True)

        stats = self.compute_stats()
        print(render_latency_histogram(self.latencies, self.histogram_bins))
        print()
        print(render_timeline(self.timeline, self.timeline_width))
        return stats