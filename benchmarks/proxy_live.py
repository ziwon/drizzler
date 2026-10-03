"""Small, opt-in proxy acceptance benchmark using Drizzler's real code paths."""

import argparse
import asyncio
from contextlib import (
    asynccontextmanager,
    contextmanager,
    redirect_stderr,
    redirect_stdout,
)
from datetime import datetime, timezone
from importlib.metadata import version
import ipaddress
import json
import logging
import os
from pathlib import Path
import platform
import tempfile
import time
from urllib.parse import urlsplit
import uuid
from unittest.mock import patch

from drizzler.proxies import ProxyPool, load_proxy_list, validate_proxy_url


ROOT = Path(__file__).resolve().parents[1]


def external_path(value):
    path = Path(value).expanduser().resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Secret and result files must be outside the checkout")
    return path


def read_proxies(path=None):
    path = path or os.environ.get("DRIZZLER_BENCH_PROXY_FILE")
    contents = os.environ.get("DRIZZLER_BENCH_PROXIES")
    if bool(path) == bool(contents):
        raise ValueError("Provide exactly one proxy file or DRIZZLER_BENCH_PROXIES")
    if path:
        path = external_path(path)
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError("Proxy file must have mode 0600 (or stricter)")
        proxies = load_proxy_list(path)
    else:
        proxies = tuple(
            dict.fromkeys(
                validate_proxy_url(line.strip())
                for line in contents.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
        )
    if not 2 <= len(proxies) <= 8:
        raise ValueError("Provide 2 to 8 distinct proxy URLs for this benchmark")
    return proxies


def target_url(value, youtube=False):
    parts = urlsplit(value or "")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or (not youtube and (parts.query or parts.path not in ("", "/")))
    ):
        raise ValueError(
            "Use an HTTPS URL without credentials; origin must be a base URL"
        )
    if youtube and (
        parts.hostname not in ("www.youtube.com", "youtube.com", "youtu.be")
        or "list=" in parts.query
    ):
        raise ValueError("Use a single YouTube video URL, without a playlist")
    return value.rstrip("/")


def observed_ip(body):
    # Never retain arbitrary response bodies, which can echo credentials/headers.
    value = json.loads(body)["ip"]
    address = ipaddress.ip_address(value)
    if not address.is_global:
        raise ValueError("Origin did not observe a public IP")
    return str(address)


def check(passed, **evidence):
    return {"status": "pass" if passed else "fail", **evidence}


@contextmanager
def quiet_libraries():
    # Drop raw third-party diagnostics altogether, including tracebacks/headers.
    # Only allowlisted observations and exception type names reach our report.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                yield
    finally:
        logging.disable(previous)


class ObservedSession:
    """Delegate to real aiohttp; observe the same response consumed by core."""

    def __init__(self, session, proxies):
        self.session = session
        self.ids = {proxy: f"p{i + 1}" for i, proxy in enumerate(proxies)}
        self.attempts = []

    @asynccontextmanager
    async def get(self, url, **kwargs):
        record = {"proxy": self.ids.get(kwargs.get("proxy"), "unexpected")}
        self.attempts.append(record)
        start = time.monotonic()
        try:
            if record["proxy"] == "unexpected":
                raise ValueError("Unexpected or direct route")
            # Refuse redirects to keep observations tied to the controlled origin.
            async with self.session.get(
                url, allow_redirects=False, **kwargs
            ) as response:
                record["status"] = response.status
                record["ip"] = observed_ip(await response.read())
                yield response
        except Exception as exc:
            record["error"] = type(exc).__name__
            raise
        finally:
            record["elapsed_s"] = round(time.monotonic() - start, 3)


def rotation_checks(attempts, count):
    expected = [f"p{i % count + 1}" for i in range(count * 2)]
    valid = len(attempts) == len(expected) and all(
        a.get("status") == 200 and "ip" in a and "error" not in a for a in attempts
    )
    ips = {a["ip"] for a in attempts if "ip" in a}
    return {
        "http_round_robin": check(valid and [a["proxy"] for a in attempts] == expected),
        "outbound_ip_rotation": check(valid and len(ips) >= 2, distinct_ips=len(ips)),
    }


def retry_checks(attempts, count, success, errors):
    expected = [f"p{i % count + 1}" for i in range(3)]
    valid = (
        [a.get("status") for a in attempts] == [503, 429, 200]
        and [a["proxy"] for a in attempts] == expected
        and all("ip" in a and "error" not in a for a in attempts)
        and success == 1
        and errors == 0
    )
    ips = [a.get("ip") for a in attempts]
    return {
        "http_retry_rotation": check(valid),
        "http_retry_egress_change": check(
            valid and all(left != right for left, right in zip(ips, ips[1:]))
        ),
    }


def make_engine(proxies, directory, **kwargs):
    from drizzler.core import RequestDrizzler

    return RequestDrizzler(
        urls=[],
        proxy_pool=ProxyPool(proxies),
        output_dir=str(directory),
        state_file=str(directory / "state.json"),
        use_progress_bar=False,
        global_concurrency=1,
        max_retries=3,
        backoff_jitter_ratio=0,
        **kwargs,
    )


async def run_http(proxies, origin, directory, timeout):
    import aiohttp

    engine = make_engine(proxies, directory)
    async with aiohttp.ClientSession(
        trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        observed = ObservedSession(session, proxies)
        for _ in range(len(proxies) * 2):
            await engine._fetch_once(session=observed, url=origin + "/ip")
        checks = rotation_checks(observed.attempts, len(proxies))
        rotation = observed.attempts
        observed.attempts = []
        # A fresh engine/pool makes the retry sequence independently reproducible.
        engine = make_engine(proxies, directory)
        try:
            await engine._fetch_with_policy(
                observed, origin + "/retry/" + uuid.uuid4().hex, 0
            )
        finally:
            for bucket in engine._buckets.values():
                await bucket.stop()
        checks.update(
            retry_checks(
                observed.attempts,
                len(proxies),
                engine.success_count,
                engine.error_count,
            )
        )
        return {"checks": checks, "rotation": rotation, "retry": observed.attempts}


def observe_handler(handler, pinned_proxy, events, probe_url):
    """Observe the effective route immediately before yt-dlp's transport sends."""
    from yt_dlp.utils.networking import select_proxy

    send = handler.send

    def observed_send(request):
        effective = select_proxy(request.url, handler._get_proxies(request))
        matches = effective == pinned_proxy
        events.append({"pinned": matches, "probe": request.url == probe_url})
        if not matches:
            raise ValueError("Unexpected or direct yt-dlp route")
        return send(request)

    handler.send = observed_send


async def run_ytdlp(proxies, origin, video, directory, timeout, jobs, require_sticky):
    import yt_dlp

    ids = {proxy: f"p{i + 1}" for i, proxy in enumerate(proxies)}
    results = []
    probe_url = origin + "/ip"
    real_ydl = yt_dlp.YoutubeDL

    class ObservedYDL(real_ydl):
        def __init__(self, opts):
            self.events = []
            self.record = {"proxy": ids.get(opts.get("proxy"), "unexpected")}
            results.append(self.record)
            self.pinned_proxy = opts.get("proxy")
            if self.record["proxy"] == "unexpected":
                raise ValueError("Missing proxy")
            # Keep core's format and retry settings. Bound file size and socket waits,
            # disable caches, and keep media transport in Python for observation.
            opts = {
                **opts,
                "cachedir": False,
                "socket_timeout": timeout,
                "max_filesize": 25 * 1024 * 1024,
                "hls_prefer_native": True,
                "external_downloader": {"default": "native"},
                "noprogress": True,
            }
            super().__init__(opts)

        def build_request_director(self, handlers, preferences=None):
            director = super().build_request_director(handlers, preferences)
            for handler in director.handlers.values():
                observe_handler(handler, self.pinned_proxy, self.events, probe_url)
            return director

        def probe(self):
            with self.urlopen(probe_url) as response:
                return observed_ip(response.read())

        def extract_info(self, *args, **kwargs):
            # yt-dlp may recursively call extract_info; probe only the outer job.
            if getattr(self, "inside_job", False):
                return super().extract_info(*args, **kwargs)
            self.inside_job = True
            try:
                self.record["ip_before"] = self.probe()
                info = super().extract_info(*args, **kwargs)
                self.record["download_errors"] = self._download_retcode
                self.record["ip_after"] = self.probe()
                return info
            except Exception as exc:
                self.record["error"] = type(exc).__name__
                raise
            finally:
                self.record["requests"] = len(self.events)
                self.record["non_probe_requests"] = sum(
                    not e["probe"] for e in self.events
                )
                self.record["all_requests_pinned"] = bool(self.events) and all(
                    e["pinned"] for e in self.events
                )
                self.inside_job = False

    engine = make_engine(proxies, directory, download_video=True)
    with patch.object(yt_dlp, "YoutubeDL", ObservedYDL):
        for job in range(jobs):
            job_dir = directory / str(job)
            job_dir.mkdir()
            engine.output_dir = str(job_dir)
            before = len(results)
            success, elapsed, _ = await engine._download_with_ytdlp(video, job)
            if len(results) != before + 1:
                results.append({"error": "UnexpectedJobCount"})
                break
            completed = [
                p
                for p in job_dir.iterdir()
                if p.suffix in (".mp4", ".webm", ".mkv", ".m4a")
            ]
            results[-1].update(
                success=success,
                elapsed_s=round(elapsed or 0, 3),
                media_bytes=sum(p.stat().st_size for p in completed),
            )

    valid = len(results) == jobs and all(
        r.get("success")
        and r.get("download_errors") == 0
        and r.get("media_bytes", 0) > 0
        and r.get("non_probe_requests", 0) > 0
        and r.get("all_requests_pinned")
        and r.get("ip_before")
        and r.get("ip_after")
        and "error" not in r
        for r in results
    )
    checks = {
        "ytdlp_job_proxy_pinned": check(valid),
        "ytdlp_between_job_rotation": check(
            valid
            and [r.get("proxy") for r in results]
            == [f"p{i % len(proxies) + 1}" for i in range(jobs)]
        ),
    }
    sticky = valid and all(r["ip_before"] == r["ip_after"] for r in results)
    checks["ytdlp_sampled_sticky_ip"] = (
        check(sticky)
        if require_sticky
        else {"status": "informational", "stable": sticky}
    )
    return {"checks": checks, "jobs": results}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly enable network checks"
    )
    parser.add_argument(
        "--proxy-file", help="External mode-0600 file; never pass proxy URLs on argv"
    )
    parser.add_argument(
        "--origin-url", help="HTTPS origin serving benchmarks/origin.py"
    )
    parser.add_argument(
        "--youtube-url", help="Short video you own or are authorized to download"
    )
    parser.add_argument("--mode", choices=("all", "http", "ytdlp"), default="all")
    parser.add_argument("--output", help="New JSON file outside the checkout")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--jobs", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--require-sticky-ip", action="store_true")
    parser.add_argument(
        "--revision", default="unknown", help="Source commit used for this run"
    )
    return parser.parse_args(argv)


async def run_checks(args, proxies, origin, video):
    report = {"checks": {}, "observations": {}}
    with tempfile.TemporaryDirectory(prefix="drizzler-bench-") as directory:
        for name, enabled in (
            ("http", args.mode != "ytdlp"),
            ("ytdlp", args.mode != "http"),
        ):
            if not enabled:
                report["checks"][name] = {"status": "skip"}
                continue
            try:
                if name == "http":
                    result = await run_http(
                        proxies, origin, Path(directory), args.timeout
                    )
                else:
                    result = await run_ytdlp(
                        proxies,
                        origin,
                        video,
                        Path(directory),
                        args.timeout,
                        args.jobs,
                        args.require_sticky_ip,
                    )
                report["checks"].update(result.pop("checks"))
                report["observations"][name] = result
            except Exception as exc:
                report["checks"][name] = check(False, error=type(exc).__name__)
    return report


def main(argv=None):
    args = parse_args(argv)
    if not args.live:
        print(
            json.dumps(
                {
                    "status": "not_run",
                    "network": False,
                    "next": "See docs/live-proxy-benchmark.md",
                }
            )
        )
        return 0
    try:
        proxies = read_proxies(args.proxy_file)
        origin = target_url(args.origin_url)
        video = (
            target_url(args.youtube_url, youtube=True) if args.mode != "http" else None
        )
        if not args.output or not 0 < args.timeout <= 120:
            raise ValueError(
                "Specify an external output file and a timeout in (0, 120]"
            )
        output = external_path(args.output)
        # Reserve before any traffic; refuse overwrite/symlink, including secret files.
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except Exception as exc:
        print(
            json.dumps({"status": "configuration_error", "error": type(exc).__name__})
        )
        return 2
    with os.fdopen(fd, "w") as stream:
        # An interrupted run leaves explicit incomplete evidence, never a stale pass.
        stream.write('{"status": "incomplete"}\n')
        stream.flush()
        with quiet_libraries():
            try:
                report = asyncio.run(run_checks(args, proxies, origin, video))
            except (Exception, KeyboardInterrupt) as exc:
                report = {"checks": {"runner": check(False, error=type(exc).__name__)}}
        # Revision is constrained, so it cannot become a secret-bearing output field.
        revision = (
            args.revision
            if len(args.revision) == 40
            and all(c in "0123456789abcdef" for c in args.revision)
            else "unknown"
        )
        report.update(
            schema_version=1,
            utc=datetime.now(timezone.utc).isoformat(),
            revision=revision,
            python=platform.python_version(),
            versions={
                name: version(name) for name in ("drizzler", "aiohttp", "yt-dlp")
            },
            proxy_count=len(proxies),
            scope=args.mode,
        )
        report["status"] = (
            "fail"
            if any(c["status"] == "fail" for c in report["checks"].values())
            else "pass"
        )
        stream.seek(0)
        stream.truncate()
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "checks": report["checks"]}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
