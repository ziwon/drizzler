import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from benchmarks import proxy_live as bench
from benchmarks.origin import RetrySequence


PROXIES = ("http://fake-user:fake-secret@a.example:8001", "http://b.example:8002")
IPS = ("8.8.8.8", "1.1.1.1")  # Inert fixture values; no requests are sent.


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Offline benchmark tests must not connect")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.delenv("DRIZZLER_BENCH_PROXIES", raising=False)
    monkeypatch.delenv("DRIZZLER_BENCH_PROXY_FILE", raising=False)


def secret_file(tmp_path):
    path = tmp_path / "proxies.txt"
    path.write_text("\n".join(PROXIES))
    path.chmod(0o600)
    return path


def test_dry_run_never_reads_credentials_or_starts_checks(monkeypatch, capsys):
    monkeypatch.setattr(bench, "read_proxies", lambda *_: pytest.fail("read secrets"))
    monkeypatch.setattr(bench, "run_checks", lambda *_: pytest.fail("ran checks"))
    assert bench.main([]) == 0
    assert json.loads(capsys.readouterr().out)["network"] is False


@pytest.mark.parametrize("value", [None, "http://fake-user:fake-secret@host:bad"])
def test_missing_or_invalid_credentials_never_run(monkeypatch, capsys, value):
    if value:
        monkeypatch.setenv("DRIZZLER_BENCH_PROXIES", value)
    monkeypatch.setattr(bench, "run_checks", lambda *_: pytest.fail("ran checks"))
    assert bench.main(["--live"]) == 2
    output = capsys.readouterr().out
    assert "fake-user" not in output and "fake-secret" not in output


def test_external_file_env_and_conflicts(tmp_path, monkeypatch):
    path = secret_file(tmp_path)
    assert bench.read_proxies(str(path)) == PROXIES
    monkeypatch.setenv("DRIZZLER_BENCH_PROXIES", "\n".join(PROXIES * 2))
    assert bench.read_proxies() == PROXIES
    with pytest.raises(ValueError):
        bench.read_proxies(str(path))
    monkeypatch.delenv("DRIZZLER_BENCH_PROXIES")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        bench.read_proxies(str(path))
    with pytest.raises(ValueError):
        bench.external_path(bench.ROOT / "trial.txt")
    link = tmp_path / "link"
    link.symlink_to(bench.ROOT / "README.md")
    with pytest.raises(ValueError):
        bench.external_path(link)


@pytest.mark.parametrize(
    "body", [b'{"ip":"127.0.0.1"}', b'{"ip":"fake-secret"}', b"not json"]
)
def test_invalid_ip_evidence_rejected(body):
    with pytest.raises(ValueError):
        bench.observed_ip(body)


def test_oracles_reject_alias_only_rotation_and_missing_retries():
    attempts = [
        {"proxy": f"p{i % 2 + 1}", "status": 200, "ip": IPS[0]} for i in range(4)
    ]
    checks = bench.rotation_checks(attempts, 2)
    assert checks["http_round_robin"]["status"] == "pass"
    assert checks["outbound_ip_rotation"]["status"] == "fail"
    for i, attempt in enumerate(attempts):
        attempt["ip"] = IPS[i % 2]
    assert (
        bench.rotation_checks(attempts, 2)["outbound_ip_rotation"]["status"] == "pass"
    )
    attempts = [
        {"proxy": f"p{i % 2 + 1}", "status": status, "ip": IPS[i % 2]}
        for i, status in enumerate((503, 429, 200))
    ]
    assert all(
        c["status"] == "pass" for c in bench.retry_checks(attempts, 2, 1, 0).values()
    )
    assert (
        bench.retry_checks(attempts[1:], 2, 1, 0)["http_retry_rotation"]["status"]
        == "fail"
    )
    attempts[1]["ip"] = IPS[0]
    assert (
        bench.retry_checks(attempts, 2, 1, 0)["http_retry_egress_change"]["status"]
        == "fail"
    )


def test_observer_and_real_retry_policy(tmp_path, monkeypatch):
    from drizzler import core

    class Response:
        def __init__(self, status, ip):
            self.status = status
            self.ip = ip
            self.headers = {"Retry-After": "0.01"} if status == 429 else {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def read(self):
            return json.dumps({"ip": self.ip, "ignored": "fake-secret"}).encode()

    class Session:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            self.retry = iter((503, 429, 200))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, proxy, **kwargs):
            assert kwargs["allow_redirects"] is False
            status = next(self.retry) if "/retry/" in url else 200
            return Response(status, IPS[PROXIES.index(proxy)])

    monkeypatch.setattr(core.aiohttp, "ClientSession", Session)
    monkeypatch.setattr(core.RequestDrizzler, "_sleep_backoff", AsyncMock())
    result = asyncio.run(
        bench.run_http(PROXIES, "https://origin.example", tmp_path, 20)
    )
    assert all(c["status"] == "pass" for c in result["checks"].values())
    assert len(result["rotation"]) == 4 and len(result["retry"]) == 3
    assert "fake-secret" not in json.dumps(result)


def test_transport_observer_blocks_direct_or_changed_proxy():
    from yt_dlp.networking import Request

    sent = []
    handler = SimpleNamespace(
        _get_proxies=lambda request: request.proxies or {"all": PROXIES[0]},
        send=lambda request: sent.append(request),
    )
    events = []
    bench.observe_handler(handler, PROXIES[0], events, "https://origin.example/ip")
    handler.send(Request("https://youtube.example"))
    for override in ({"all": "__noproxy__"}, {"all": PROXIES[1]}):
        with pytest.raises(ValueError):
            handler.send(Request("https://youtube.example", proxies=override))
    assert len(sent) == 1
    assert [e["pinned"] for e in events] == [True, False, False]


@pytest.mark.parametrize("download", [True, False])
def test_real_ytdlp_adapter_and_core_job_rotation(tmp_path, monkeypatch, download):
    import yt_dlp
    from yt_dlp.networking.common import Response
    from yt_dlp.networking import _requests, _urllib

    def fake_send(self, request):
        index = PROXIES.index(self._get_proxies(request)["all"])
        return Response(
            io.BytesIO(json.dumps({"ip": IPS[index]}).encode()), request.url, {}
        )

    # Replace only transport I/O and extraction; exercise real YDL/director/handlers.
    monkeypatch.setattr(_requests.RequestsRH, "send", fake_send)
    monkeypatch.setattr(_urllib.UrllibRH, "send", fake_send)

    def fake_extract(self, url, **kwargs):
        with self.urlopen(url) as response:
            response.read()
        with self.urlopen("https://media.example/video.mp4") as response:
            response.read()
        if download:
            path = Path(
                self.params["outtmpl"]["default"]
                .replace("%(id)s", "test")
                .replace("%(ext)s", "mp4")
            )
            path.write_bytes(b"fixture media")
        return {"id": "test", "url": "https://media.example/video.mp4"}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract)
    result = asyncio.run(
        bench.run_ytdlp(
            PROXIES,
            "https://origin.example",
            "https://youtu.be/test",
            tmp_path,
            20,
            2,
            True,
        )
    )
    assert [j["proxy"] for j in result["jobs"]] == ["p1", "p2"]
    assert all(j["non_probe_requests"] == 2 for j in result["jobs"])
    expected = "pass" if download else "fail"
    assert all(c["status"] == expected for c in result["checks"].values())


@pytest.mark.parametrize("crash", [False, True])
def test_report_drops_raw_diagnostics_and_refuses_overwrite(
    tmp_path, monkeypatch, capsys, crash
):
    path = secret_file(tmp_path)
    output = tmp_path / "result.json"

    async def run(*args):
        print(PROXIES[0])
        logging.error(PROXIES[0])
        if crash:
            raise RuntimeError(PROXIES[0])
        return {"checks": {"fixture": bench.check(False, error="RuntimeError")}}

    monkeypatch.setattr(bench, "run_checks", run)
    args = [
        "--live",
        "--mode",
        "http",
        "--proxy-file",
        str(path),
        "--origin-url",
        "https://origin.example",
        "--output",
        str(output),
    ]
    assert bench.main(args) == 1
    report = output.read_text()
    captured = capsys.readouterr()
    for value in ("fake-secret", "fake-user", "a.example"):
        assert value not in report + captured.out + captured.err
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert bench.main(args) == 2
    assert output.read_text() == report


def test_docker_wrapper_command_construction_without_docker(tmp_path, monkeypatch):
    proxy = secret_file(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    calls = tmp_path / "calls.jsonl"
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=bench.ROOT, text=True
    ).strip()
    docker = tmp_path / "docker"
    # No Docker daemon/container/network is invoked: this stub records argv only.
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['BENCH_TEST_CALLS'], 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['image', 'inspect']:\n"
        "    print(os.environ['BENCH_TEST_REVISION'])\n"
        "elif '--help' in sys.argv:\n"
        "    print('--proxy-list')\n"
    )
    docker.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("BENCH_TEST_CALLS", str(calls))
    monkeypatch.setenv("BENCH_TEST_REVISION", revision)
    subprocess.run(
        [
            "bash",
            str(bench.ROOT / "benchmarks/docker-run.sh"),
            "fixture:image",
            str(proxy),
            str(results),
            "--live",
            "--output",
            "/results/result.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(commands) == 4
    assert commands[1][commands[1].index("--entrypoint") + 1] == "drizzler"
    assert commands[2][commands[2].index("--network") + 1] == "none"
    live = commands[3]
    assert live[live.index("--entrypoint") + 1] == "python"
    assert live[live.index("--proxy-file") + 1] == "/run/secrets/proxies"
    assert f"type=bind,src={proxy},dst=/run/secrets/proxies,readonly" in live
    assert "--read-only" in live and "--env" not in live
    assert "fake-secret" not in calls.read_text()


def test_origin_retry_sequence_threadsafe_and_isolated():
    sequence = RetrySequence()
    with ThreadPoolExecutor(max_workers=3) as executor:
        statuses = list(executor.map(sequence.next_status, ["run"] * 3))
    assert sorted(statuses) == [200, 429, 503]
    assert sequence.next_status("other") == 503
