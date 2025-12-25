import asyncio
import aiohttp
import random
import logging

from collections.abc import Iterable
from collections import defaultdict
from .models import TimelineType, MetricsCallback
from .utils import now, normalize_host, get_random_headers, GracefulKiller
from .throttling import BoundedTokenBucket, HostCircuitBreaker
from .metrics import compute_stats
from .rendering import render_latency_histogram, render_timeline
from .persistence import StateManager
from .summarizer import TextSummarizer

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, MofNCompleteColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


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
        default_headers: dict[str, str] | None = None,
        histogram_bins: int = 20,
        timeline_width: int = 80,
        state_file: str = "drizzler_state.json",
        metrics_callback: MetricsCallback | None = None,
        deduplicate: bool = True,
        download_video: bool = False,  # --write-video
        download_info: bool = False,  # --write-info-json
        download_thumbnail: bool = False,  # --write-thumbnail
        download_subs: bool = False,  # --write-subs
        download_txt: bool = False,  # --write-txt
        summarize: bool = False,  # --summarize
        llm_provider: str = "ollama",  # LLM provider
        llm_model: str = "qwen2.5:3b",  # LLM model
        output_dir: str = "./downloads",  # -o
        simulate: bool = False,
        use_progress_bar: bool = True,
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
        self.download_subs = download_subs
        self.download_txt = download_txt
        self.summarize = summarize
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.output_dir = output_dir
        self.simulate = simulate
        self.use_progress_bar = use_progress_bar and RICH_AVAILABLE

        import os

        os.makedirs(self.output_dir, exist_ok=True)

        # Runtime state
        self.latencies: list[float] = []
        self.success_count = 0
        self.error_count = 0
        self.status_counts: dict[int, int] = defaultdict(int)
        self.timeline: TimelineType = defaultdict(list)
        self._t0: float | None = None

        # Concurrency control
        self._global_sema = asyncio.Semaphore(self.global_concurrency)
        self._host_sema: dict[str, asyncio.Semaphore] = {}
        self._buckets: dict[str, BoundedTokenBucket] = {}
        self._breakers: dict[str, HostCircuitBreaker] = {}

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
            logger.debug(
                f"Initializing semaphore for host: {host} (concurrency={self.per_host_concurrency})"
            )
            self._buckets[host] = BoundedTokenBucket(
                self.per_host_rate,
                burst=self.per_host_burst,
                ramp_up_s=self.slow_start_ramp_up_s,
                name=host,
            )
            await self._buckets[host].start()

        if host not in self._host_sema:
            logger.debug(
                f"Initializing semaphore for host: {host} (concurrency={self.per_host_concurrency})"
            )
            self._host_sema[host] = asyncio.Semaphore(self.per_host_concurrency)

        if host not in self._breakers:
            logger.debug(f"Initializing circuit breaker for host: {host}")
            self._breakers[host] = HostCircuitBreaker(
                failure_threshold=5, cooldown_s=60.0
            )

    # ────────────────────────────────
    # Retry & Backoff Logic
    # ────────────────────────────────

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.backoff_base_s * (2 ** (attempt - 1))
        jitter = 1.0 + random.uniform(
            -self.backoff_jitter_ratio, self.backoff_jitter_ratio
        )
        await asyncio.sleep(max(0.05, base * jitter))

    @staticmethod
    def _retry_after_seconds_from_headers(headers: dict[str, str]) -> float | None:
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
    async def _fetch_once(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[int | None, float | None, dict[str, str]]:
        start = now()
        headers = get_random_headers(self.default_headers)
        try:
            async with session.get(url, headers=headers) as resp:
                content = await resp.read()  # or just: await resp.text() for HTML
                latency = now() - start
                headers_dict = {k: v for k, v in resp.headers.items()}
                logger.debug(
                    f"Fetched {url}: status={resp.status}, size={len(content)} bytes"
                )
                return resp.status, latency, headers_dict
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Connection error for {url}: {e}")
            return None, None, {}
        except TimeoutError:
            logger.warning(f"Timeout for {url}")
            return None, None, {}
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None, None, {}

    # ────────────────────────────────
    # Summary Generation
    # ────────────────────────────────
    def _generate_summary(self, video_id: str, lang_code: str, text: str) -> None:
        """Generate AI summary of the text content"""
        try:
            logger.info(f"Generating summary for {video_id}.{lang_code}")

            # Initialize summarizer
            summarizer = TextSummarizer(
                provider=self.llm_provider, model=self.llm_model
            )

            # Generate summary
            summary = summarizer.summarize(text, lang=lang_code)

            if summary:
                # Save summary as markdown file
                summary_file = f"{self.output_dir}/{video_id}.{lang_code}.summary.md"
                with open(summary_file, "w", encoding="utf-8") as f:
                    # Add metadata header
                    f.write("---\n")
                    f.write(f"video_id: {video_id}\n")
                    f.write(f"language: {lang_code}\n")
                    f.write(f"model: {self.llm_model}\n")
                    f.write(f"provider: {self.llm_provider}\n")
                    f.write("---\n\n")
                    f.write(summary)

                logger.info(f"Summary saved to {summary_file}")
            else:
                logger.warning(f"Failed to generate summary for {video_id}.{lang_code}")

        except Exception as e:
            logger.error(f"Error generating summary: {e}")

    # ────────────────────────────────
    # Subtitle Processing
    # ────────────────────────────────
    def _extract_text_from_subtitles(self, video_id: str) -> None:
        """Extract text only from VTT/SRT files and save as .txt"""
        import os
        import re
        import glob

        # Find all subtitle files for this video
        subtitle_patterns = [
            f"{self.output_dir}/{video_id}.*.vtt",
            f"{self.output_dir}/{video_id}.*.srt",
        ]

        for pattern in subtitle_patterns:
            for subtitle_file in glob.glob(pattern):
                try:
                    with open(subtitle_file, encoding="utf-8") as f:
                        content = f.read()

                    # Extract language code from filename (e.g., video_id.en.vtt -> en)
                    base_name = os.path.basename(subtitle_file)
                    parts = base_name.rsplit(".", 2)
                    if len(parts) >= 3:
                        lang_code = parts[1]
                    else:
                        lang_code = "unknown"

                    # Process VTT format
                    if subtitle_file.endswith(".vtt"):
                        # Remove WEBVTT header
                        content = re.sub(
                            r"^WEBVTT.*?\n\n", "", content, flags=re.DOTALL
                        )
                        # Remove timestamps and cue settings
                        content = re.sub(
                            r"^\d{2}:\d{2}:\d{2}\.\d{3}.*?$",
                            "",
                            content,
                            flags=re.MULTILINE,
                        )
                        # Remove position/align tags
                        content = re.sub(r"</?[^>]+>", "", content)
                        # Remove cue identifiers (numbers at the beginning of lines)
                        content = re.sub(r"^\d+\s*$", "", content, flags=re.MULTILINE)

                    # Process SRT format
                    elif subtitle_file.endswith(".srt"):
                        # Remove subtitle numbers
                        content = re.sub(r"^\d+\s*$", "", content, flags=re.MULTILINE)
                        # Remove timestamps
                        content = re.sub(
                            r"^\d{2}:\d{2}:\d{2},\d{3}.*?$",
                            "",
                            content,
                            flags=re.MULTILINE,
                        )
                        # Remove HTML tags
                        content = re.sub(r"</?[^>]+>", "", content)

                    # Clean up the text
                    lines = []
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("-->"):
                            lines.append(line)

                    # Remove duplicate consecutive lines
                    cleaned_lines = []
                    prev_line = None
                    for line in lines:
                        if line != prev_line:
                            cleaned_lines.append(line)
                            prev_line = line

                    # Save as text file
                    text_content = "\n".join(cleaned_lines)
                    text_file = f"{self.output_dir}/{video_id}.{lang_code}.txt"
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(text_content)

                    logger.info(f"Extracted text to {text_file}")

                    # Generate summary if requested
                    if self.summarize:
                        self._generate_summary(video_id, lang_code, text_content)

                    # If user only wants text, remove the original subtitle file
                    if self.download_txt and not self.download_subs:
                        os.remove(subtitle_file)
                        logger.debug(f"Removed subtitle file {subtitle_file}")

                except Exception as e:
                    logger.error(f"Failed to extract text from {subtitle_file}: {e}")

    # ────────────────────────────────
    # yt-dlp Download Logic
    # ────────────────────────────────
    async def _download_with_ytdlp(
        self, url: str, worker_id: int
    ) -> tuple[bool, float | None, str | None]:
        """Download video/info/thumbnail using yt-dlp in thread pool."""
        start = now()
        loop = asyncio.get_event_loop()

        def _run_ytdlp():
            import yt_dlp

            # Enable subtitle download if either subs, txt, or summarize is requested
            download_any_subs = (
                self.download_subs or self.download_txt or self.summarize
            )

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "outtmpl": f"{self.output_dir}/%(id)s.%(ext)s",
                "format": "best[ext=mp4]/best",  # prefer mp4
                "writesubtitles": download_any_subs,
                "writeautomaticsub": download_any_subs,  # Also get auto-generated subs
                "subtitleslangs": ["en", "ko"]
                if download_any_subs
                else [],  # Download English and Korean
                "subtitlesformat": "vtt/srt/best",  # Prefer VTT, then SRT
                "writeinfojson": self.download_info,
                "writethumbnail": self.download_thumbnail,
                "skip_download": not self.download_video or self.simulate,
                "ignoreerrors": True,  # Continue on download errors
                "extractor_retries": 3,  # Retry on extraction errors
                "fragment_retries": 3,  # Retry on fragment errors
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=not self.simulate)
                    if info is None:
                        return False, None

                    # If we need text extraction or summarization, process the subtitle files
                    if (self.download_txt or self.summarize) and info:
                        video_id = info.get("id")
                        if video_id:
                            self._extract_text_from_subtitles(video_id)

                    return True, info.get("url")  # actual CDN URL if downloaded
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
        # If any download option is True, use yt-dlp instead of HTTP fetch
        if (
            self.download_video
            or self.download_info
            or self.download_thumbnail
            or self.download_subs
            or self.download_txt
            or self.summarize
            or self.simulate  # Force yt-dlp for simulation if it's a known video site
        ):
            success, latency, host = await self._download_with_ytdlp(url, worker_id)

            # Record in stats
            if success and latency is not None:
                self.success_count += 1
                self.latencies.append(latency)
                if self._t0 is not None:
                    end_req = now() - self._t0
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
            logger.warning(
                f"[W{worker_id}] Circuit breaker OPEN for {host}, skipping {url}"
            )
            self.error_count += 1
            end_req = now()
            if self._t0 is not None:
                self.timeline[worker_id].append(
                    (now() - self._t0, end_req - self._t0, host, None)
                )
            return

        async with self._global_sema, self._host_sema[host]:
            logger.debug(f"[W{worker_id}] Acquiring token for {host}")
            await bucket.acquire()
            logger.debug(f"[W{worker_id}] Token acquired for {host}")

            start_req = now()
            last_status: int | None = None

            for attempt in range(1, self.max_retries + 1):
                if self.graceful_killer.kill_now:
                    logger.info(
                        f"[W{worker_id}] Graceful shutdown requested. Aborting {url}"
                    )
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
                    logger.info(
                        f"[W{worker_id}] Success {url} ({latency:.3f}s, status={status})"
                    )
                    return

                retry_after_s = self._retry_after_seconds_from_headers(headers)
                should_retry = False

                # Handle 429, 503, or network errors with retries
                if status in (429, 503) or status is None:
                    breaker.record_failure()
                    bucket.adjust_rate(0.8)
                    if retry_after_s and retry_after_s > 0:
                        logger.warning(
                            f"[W{worker_id}] Retry-After: {retry_after_s:.1f}s for {url}"
                        )
                        await bucket.cooldown_until(now() + retry_after_s)
                        await asyncio.sleep(retry_after_s)
                        should_retry = True
                    elif attempt < self.max_retries:
                        await self._sleep_backoff(attempt)
                        should_retry = True
                        logger.debug(
                            f"[W{worker_id}] Backing off before retry {attempt + 1}"
                        )

                if not should_retry:
                    break

            # If we reach here, all attempts failed
            self.error_count += 1
            end_req = now()
            if self._t0 is not None:
                self.timeline[worker_id].append(
                    (start_req - self._t0, end_req - self._t0, host, last_status)
                )
            logger.warning(
                f"[W{worker_id}] Failed {url} after {self.max_retries} attempts. Last status: {last_status}"
            )

    # ────────────────────────────────
    # Main Runner
    # ────────────────────────────────

    async def _expand_playlists(self) -> list[str]:
        """Expand playlist URLs into individual video URLs using yt-dlp."""
        logger.info("Checking for playlists to expand...")
        expanded_urls = []
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "force_generic_extractor": False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for url in self.urls:
                if "list=" in url or "playlist" in url:
                    try:
                        logger.info(f"Expanding playlist: {url}")
                        info = ydl.extract_info(url, download=False)
                        if "entries" in info:
                            entries = list(info["entries"])
                            logger.info(f"Found {len(entries)} entries in playlist")
                            for entry in entries:
                                video_url = entry.get("url")
                                if not video_url:
                                    # Try to construct URL from id
                                    video_id = entry.get("id")
                                    if video_id:
                                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                                if video_url:
                                    expanded_urls.append(video_url)
                    except Exception as e:
                        logger.error(f"Failed to expand playlist {url}: {e}")
                        expanded_urls.append(url)
                else:
                    expanded_urls.append(url)

        return expanded_urls

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
        logger.info(
            f"Loaded {len(loaded_buckets)} persisted buckets, {len(loaded_breakers)} breakers"
        )

        for bucket in self._buckets.values():
            if bucket._task is None:  # Not started yet
                await bucket.start()
                logger.debug(f"Started loaded bucket: {bucket.name}")

        # Expand playlists
        self.urls = await self._expand_playlists()
        if not self.urls:
            logger.warning("No URLs to process after expansion.")
            return None

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
            logger.info(
                f"Starting {len(self.urls)} requests with {self.global_concurrency} workers"
            )

            # Progress Bar Setup
            progress = None
            task_id = None
            if self.use_progress_bar:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                )
                progress.start()
                task_id = progress.add_task("[cyan]Drizzling...", total=len(self.urls))

            async def worker(worker_id: int):
                while not self.graceful_killer.kill_now:
                    try:
                        _, u = await asyncio.wait_for(q.get(), timeout=1.0)
                    except TimeoutError:
                        if q.empty():
                            break
                        continue
                    except asyncio.CancelledError:
                        break
                    try:
                        await self._fetch_with_policy(session, u, worker_id)
                        if progress and task_id is not None:
                            progress.advance(task_id)
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
                if progress:
                    progress.stop()
            except KeyboardInterrupt:
                if progress:
                    progress.stop()
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

        print("\n" + "=" * 60)
        print(render_latency_histogram(self.latencies, self.histogram_bins))
        print()
        print(render_timeline(self.timeline, self.timeline_width))
        print("=" * 60)

        logger.info(
            f"Run completed: {stats.success} successes, {stats.errors} errors, "
            f"error_rate={stats.error_rate * 100:.2f}%"
        )

        return stats
