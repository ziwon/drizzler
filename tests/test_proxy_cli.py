import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from drizzler import cli


@pytest.mark.parametrize("mode", ["direct", "single", "list"])
def test_cli_passes_proxy_configuration_to_engine(tmp_path, monkeypatch, mode):
    argv = ["drizzler", "https://target.example", "--no-progress"]
    proxy = "http://proxy.example:8080"
    if mode == "single":
        argv += ["--proxy", proxy]
    elif mode == "list":
        path = tmp_path / "proxies.txt"
        path.write_text(f"{proxy}\nhttps://second.example:443\n")
        argv += ["--proxy-list", str(path)]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(cli, "setup_logging", Mock())
    engine = Mock(return_value=Mock(run=AsyncMock(return_value=None)))
    monkeypatch.setattr(cli, "RequestDrizzler", engine)
    asyncio.run(cli.run())
    options = engine.call_args.kwargs
    assert options["proxy"] == (proxy if mode == "single" else None)
    if mode == "list":
        assert options["proxy_pool"].next_proxy() == proxy
        assert options["proxy_pool"].next_proxy() == "https://second.example:443"
    else:
        assert options["proxy_pool"] is None
    engine.return_value.run.assert_awaited_once()


@pytest.mark.parametrize(
    "mode", ["conflict", "missing", "empty", "invalid", "single-invalid"]
)
def test_cli_rejects_bad_proxy_configuration_before_engine_start(
    tmp_path, monkeypatch, capsys, mode
):
    path = tmp_path / "proxies.txt"
    secret = "http://fake-user:fake-password@proxy.example:badport"
    if mode == "conflict":
        options = ["--proxy", secret, "--proxy-list", str(path)]
    elif mode == "single-invalid":
        options = ["--proxy", secret]
    else:
        if mode != "missing":
            path.write_text(secret if mode == "invalid" else "# empty\n")
        options = ["--proxy-list", str(path)]
    monkeypatch.setattr(sys, "argv", ["drizzler", "https://target.example", *options])
    engine = Mock()
    logging_setup = Mock()
    monkeypatch.setattr(cli, "RequestDrizzler", engine)
    monkeypatch.setattr(cli, "setup_logging", logging_setup)
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.run())
    assert exc.value.code == 2
    engine.assert_not_called()
    logging_setup.assert_not_called()
    output = capsys.readouterr().err
    assert "error:" in output
    assert "fake-user" not in output
    assert "fake-password" not in output
    if mode == "conflict":
        assert "not allowed with argument" in output
