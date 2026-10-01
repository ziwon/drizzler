import asyncio
import base64
import logging
from collections import Counter
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import aiohttp
import pytest
import yt_dlp

from drizzler import core
from drizzler.proxies import ProxyPool


PROXIES = ("http://a.example:8001", "https://b.example:8002", "http://c.example:8003")
URL = "https://target.example/resource"


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        # Allow concurrent requests to overlap without opening sockets.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args):
        pass

    async def read(self):
        return b"response body"


class FakeSession:
    def __init__(self, outcomes=()):
        self.outcomes = iter(outcomes)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url, **options):
        self.calls.append((url, options))
        outcome = next(self.outcomes, FakeResponse())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def proxies(self):
        return [options["proxy"] for _, options in self.calls]


@pytest.fixture
def make_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "GracefulKiller", lambda: SimpleNamespace(kill_now=False))

    def bucket_factory(*args, **kwargs):
        return SimpleNamespace(
            start=AsyncMock(),
            stop=AsyncMock(),
            acquire=AsyncMock(),
            cooldown_until=AsyncMock(),
            adjust_rate=Mock(),
        )

    monkeypatch.setattr(core, "BoundedTokenBucket", bucket_factory)

    def make(**kwargs):
        return core.RequestDrizzler(
            urls=kwargs.pop("urls", [URL]),
            output_dir=str(tmp_path / "downloads"),
            state_file=str(tmp_path / "state.json"),
            use_progress_bar=False,
            **kwargs,
        )

    return make


@pytest.mark.parametrize("proxy", [None, PROXIES[0]])
def test_http_direct_and_legacy_single_proxy(make_engine, proxy):
    async def run():
        engine = make_engine(proxy=proxy)
        session = FakeSession([FakeResponse(503), FakeResponse(200)])
        engine._sleep_backoff = AsyncMock()
        await engine._fetch_with_policy(session, URL, 0)
        assert session.proxies == [proxy, proxy]
        assert engine.success_count == 1
        assert engine.error_count == 0

    asyncio.run(run())


def test_http_rotates_on_existing_network_and_status_retries(make_engine):
    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES), max_retries=4)
        session = FakeSession(
            [
                aiohttp.ClientConnectionError("fake connection failure"),
                FakeResponse(429),
                FakeResponse(503),
                FakeResponse(200),
            ]
        )
        engine._sleep_backoff = AsyncMock()
        await engine._fetch_with_policy(session, URL, 0)
        assert session.proxies == [*PROXIES, PROXIES[0]]
        assert [u for u, _ in session.calls] == [URL] * 4
        engine._sleep_backoff.assert_has_awaits([call(1), call(2), call(3)])
        assert (
            len(engine._buckets) == len(engine._breakers) == len(engine._host_sema) == 1
        )
        bucket = engine._buckets["target.example"]
        bucket.acquire.assert_awaited_once()
        assert bucket.adjust_rate.call_args_list == [call(0.8)] * 3
        assert engine.status_counts == {429: 1, 503: 1, 200: 1}
        assert engine.success_count == 1
        assert engine._breakers["target.example"].failures == 0

    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 403, 404, 500])
def test_rotation_does_not_add_retries_for_other_statuses(make_engine, status):
    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES))
        session = FakeSession([FakeResponse(status)])
        engine._sleep_backoff = AsyncMock()
        await engine._fetch_with_policy(session, URL, 0)
        assert session.proxies == [PROXIES[0]]
        engine._sleep_backoff.assert_not_awaited()
        assert engine.error_count == 1

    asyncio.run(run())


def test_http_attempt_cap_and_open_breaker_do_not_reset_pool(make_engine):
    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES), max_retries=3)
        session = FakeSession([FakeResponse(503) for _ in range(6)])
        engine._sleep_backoff = AsyncMock()
        await engine._fetch_with_policy(session, URL, 0)
        await engine._fetch_with_policy(session, URL, 1)
        await engine._fetch_with_policy(session, URL, 2)
        assert session.proxies == list(PROXIES) * 2
        assert engine.error_count == 3
        assert engine._sleep_backoff.await_count == 4
        assert engine._buckets["target.example"].acquire.await_count == 2
        assert engine.proxy_pool.next_proxy() == PROXIES[0]

    asyncio.run(run())


@pytest.mark.parametrize(
    "retry_after", ["2.5", "Wed, 21 Oct 2015 07:28:00 GMT", "0", "invalid"]
)
def test_retry_after_keeps_numeric_only_semantics(
    make_engine, monkeypatch, retry_after
):
    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES), max_retries=2)
        session = FakeSession(
            [FakeResponse(429, {"Retry-After": retry_after}), FakeResponse()]
        )
        engine._sleep_backoff = AsyncMock()
        sleep = AsyncMock()
        monkeypatch.setattr(core.asyncio, "sleep", sleep)
        await engine._fetch_with_policy(session, URL, 0)
        assert session.proxies == list(PROXIES[:2])
        cooldown = engine._buckets["target.example"].cooldown_until
        if retry_after == "2.5":
            cooldown.assert_awaited_once()
            assert call(2.5) in sleep.await_args_list
            engine._sleep_backoff.assert_not_awaited()
        else:
            cooldown.assert_not_awaited()
            engine._sleep_backoff.assert_awaited_once_with(1)

    asyncio.run(run())


def test_http_concurrent_requests_use_one_pool(make_engine):
    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES))
        session = FakeSession()
        results = await asyncio.gather(
            *[engine._fetch_once(session, f"{URL}/{i}") for i in range(61)]
        )
        assert all(status == 200 for status, _, _ in results)
        assert session.proxies == [PROXIES[i % 3] for i in range(61)]
        assert engine.proxy_pool.next_proxy() == PROXIES[1]

    asyncio.run(run())


def test_run_workers_share_pool_and_report_progress(make_engine, monkeypatch):
    async def run():
        progress = Mock()
        engine = make_engine(
            urls=[f"{URL}/{i}" for i in range(12)],
            proxy_pool=ProxyPool(PROXIES),
            global_concurrency=4,
            progress_callback=progress,
        )
        engine.state_manager = Mock(load_state=Mock(return_value=({}, {})))
        session = FakeSession()
        monkeypatch.setattr(core.aiohttp, "ClientSession", lambda **kwargs: session)
        monkeypatch.setattr(core.aiohttp, "TCPConnector", Mock())
        stats = await engine.run()
        assert session.proxies == list(PROXIES) * 4
        assert stats.success == 12 and stats.errors == 0
        assert progress.call_count == 12
        assert len(engine._buckets) == 1

    asyncio.run(run())


@pytest.mark.parametrize("proxy", [None, PROXIES[0]])
def test_ytdlp_direct_and_single_proxy(make_engine, monkeypatch, proxy):
    options = []

    class FakeYDL:
        def __init__(self, opts):
            options.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            return {"entries": [], "id": "fake-video"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    async def run():
        engine = make_engine(
            proxy=proxy, urls=["https://www.youtube.com/playlist?list=one"]
        )
        await engine._expand_playlists()
        assert (await engine._download_with_ytdlp(URL, 0))[0]
        assert (await engine._download_with_ytdlp(URL, 1))[0]

    asyncio.run(run())
    assert [opts["proxy"] for opts in options] == [proxy] * 3


def test_playlist_and_download_calls_share_round_robin(make_engine, monkeypatch):
    options = []
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            options.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            calls.append((url, download, self.opts["proxy"]))
            if "list=" in url:
                return {
                    "entries": [{"id": "first"}, {"url": "https://youtu.be/second"}]
                }
            return {"id": "fake-video"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    async def run():
        engine = make_engine(
            proxy_pool=ProxyPool(PROXIES),
            urls=[
                URL,
                "https://www.youtube.com/watch?v=one&list=one",
                "https://www.youtube.com/playlist?list=two",
            ],
        )
        expanded = await engine._expand_playlists()
        assert expanded == [
            URL,
            *["https://www.youtube.com/watch?v=first", "https://youtu.be/second"] * 2,
        ]
        for i in range(2):
            assert (await engine._download_with_ytdlp(URL, i))[0]

    asyncio.run(run())
    assert [opts["proxy"] for opts in options] == [*PROXIES, PROXIES[0]]
    assert len({id(opts) for opts in options}) == 4
    assert calls[0][0] == "https://www.youtube.com/playlist?list=one"
    assert [download for _, download, _ in calls] == [False, False, True, True]


def test_concurrent_ytdlp_calls_pin_proxy_and_do_not_share_options(
    make_engine, monkeypatch
):
    barrier = Barrier(3, timeout=10)
    options = []
    observed = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            options.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            proxy = self.opts["proxy"]
            barrier.wait()
            # Model multiple fragments and internal retries within one invocation.
            for _ in range(4):
                observed.append((url, self.opts["proxy"]))
                assert self.opts["proxy"] == proxy
                for hook in self.opts["progress_hooks"]:
                    hook(
                        {
                            "status": "downloading",
                            "downloaded_bytes": 5,
                            "total_bytes": 10,
                        }
                    )
            return {"id": "fake-video"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    async def run():
        engine = make_engine(proxy_pool=ProxyPool(PROXIES), download_video=True)
        results = await asyncio.gather(
            *[
                engine._download_with_ytdlp(f"https://youtu.be/video{i}", i)
                for i in range(3)
            ]
        )
        assert all(success for success, _, _ in results)
        assert engine.proxy_pool.next_proxy() == PROXIES[0]

    asyncio.run(run())
    assert Counter(opts["proxy"] for opts in options) == Counter(PROXIES)
    assert len({id(opts) for opts in options}) == 3
    assert len({id(opts["progress_hooks"]) for opts in options}) == 3
    for url, proxy in observed:
        assert {p for u, p in observed if u == url} == {proxy}
    assert all(
        opts["extractor_retries"] == opts["fragment_retries"] == 3 for opts in options
    )


def test_proxy_selection_failure_never_falls_back_to_direct(make_engine, monkeypatch):
    async def run():
        pool = ProxyPool(PROXIES)
        monkeypatch.setattr(
            pool, "next_proxy", Mock(side_effect=RuntimeError("selection failed"))
        )
        ydl = Mock()
        monkeypatch.setattr(yt_dlp, "YoutubeDL", ydl)
        engine = make_engine(
            proxy_pool=pool, urls=["https://www.youtube.com/playlist?list=one"]
        )
        session = FakeSession()
        assert (await engine._fetch_once(session, URL))[0] is None
        assert not session.calls
        assert not (await engine._download_with_ytdlp(URL, 0))[0]
        assert await engine._expand_playlists() == engine.urls
        ydl.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["single", "list"])
def test_proxy_credentials_are_redacted_in_errors_logs_and_progress(
    make_engine, monkeypatch, caplog, capsys, mode
):
    proxy = "http://fake%2Duser:fake%2Dpassword@proxy.example:8080"
    auth = base64.b64encode(b"fake-user:fake-password").decode()
    message = f"Proxy failure: {proxy}; BasicAuth(login='fake-user', password='fake-password'); Basic {auth}"
    caplog.set_level(logging.DEBUG)
    stages = []

    def stage_callback(stage, info):
        stages.append((stage, info))
        if stage == "Downloading video...":
            raise RuntimeError(message)

    # Use yt-dlp's real logging/error methods while replacing only network extraction.
    def fake_extract(ydl, url, download):
        ydl.to_screen(message)
        ydl.report_warning(message)
        for hook in ydl.params.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
        ydl.report_error(message, tb=False)
        raise RuntimeError(message)

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract)

    async def run():
        kwargs = (
            {"proxy": proxy} if mode == "single" else {"proxy_pool": ProxyPool([proxy])}
        )
        engine = make_engine(
            **kwargs,
            download_video=True,
            stage_callback=stage_callback,
            urls=["https://www.youtube.com/playlist?list=one"],
        )
        connector_error = aiohttp.ClientProxyConnectionError(
            SimpleNamespace(host="proxy.example", port=8080, ssl=False),
            OSError(message),
        )
        session = FakeSession([connector_error, RuntimeError(message)])
        await engine._fetch_once(session, URL)
        await engine._fetch_once(session, URL)
        assert session.proxies == [proxy, proxy]
        assert not (await engine._download_with_ytdlp(URL, 0))[0]
        assert await engine._expand_playlists() == engine.urls

    asyncio.run(run())
    output = capsys.readouterr()
    diagnostics = caplog.text + output.out + output.err + repr(stages)
    assert "[REDACTED]" in caplog.text
    for secret in (
        "fake-user",
        "fake-password",
        "fake%2Duser",
        "fake%2Dpassword",
        auth,
    ):
        assert secret not in diagnostics


def test_core_rejects_conflicting_proxy_configuration(make_engine):
    with pytest.raises(ValueError, match="cannot be used together"):
        make_engine(proxy=PROXIES[0], proxy_pool=ProxyPool(PROXIES))
