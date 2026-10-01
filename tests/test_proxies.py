from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from drizzler.proxies import ProxyPool, load_proxy_list, validate_proxy_url


PROXIES = ("http://a.example:8001", "https://b.example:8002", "http://c.example:8003")


def test_load_proxy_list(tmp_path):
    path = tmp_path / "proxies.txt"
    path.write_text(
        f"  # Example proxies\n\n  {PROXIES[0]}  \n{PROXIES[1]}\n"
        f"{PROXIES[0]}\n\t{PROXIES[2]}\r\n",
        encoding="utf-8",
    )
    assert load_proxy_list(path) == PROXIES


@pytest.mark.parametrize("content", ["", " \n# comment only\n"])
def test_empty_proxy_list(tmp_path, content):
    path = tmp_path / "empty.txt"
    path.write_text(content)
    with pytest.raises(ValueError, match="no proxy URLs"):
        load_proxy_list(path)


def test_unreadable_proxy_lists(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Cannot read"):
        load_proxy_list(tmp_path / "missing.txt")
    with pytest.raises(ValueError, match="Cannot read"):
        load_proxy_list(tmp_path)
    path = tmp_path / "invalid-utf8.txt"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="Cannot read"):
        load_proxy_list(path)

    def denied(*args, **kwargs):
        raise PermissionError("fake-user:fake-password")

    monkeypatch.setattr(type(path), "read_text", denied)
    with pytest.raises(ValueError, match="Cannot read") as exc:
        load_proxy_list(path)
    assert "fake-user" not in str(exc.value)
    assert "fake-password" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "https://proxy.example:443/",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
        "http://fake-user:p%40ss@proxy.example:3128",
    ],
)
def test_valid_proxy_urls_are_preserved(url):
    assert validate_proxy_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "proxy.example:8080",
        "socks5://proxy.example:1080",
        "ftp://proxy.example",
        "http://",
        "http://:8080",
        "http://proxy.example:",
        "http://proxy.example:nope",
        "http://proxy.example:0",
        "http://proxy.example:65536",
        "http://proxy.example:-1",
        "http://proxy.example/path",
        "http://proxy.example?token=secret",
        "http://proxy.example#fragment",
        "http://bad host:80",
        "http://bad\nhost:80",
        "http://[invalid]:80",
        "http://[::1",
        "http://[::1]junk",
        "http://bad\\host:80",
        "http://-invalid:80",
        "http://fake-user:pass%ZZ@proxy.example",
        "http://@proxy.example",
        "http://u%3Aser:pass@proxy.example",
        "http://u:raw@pass@proxy.example",
    ],
)
def test_invalid_proxy_urls_are_rejected_without_echo(url):
    with pytest.raises(ValueError, match="Invalid proxy URL") as exc:
        validate_proxy_url(url)
    if url:
        assert url not in str(exc.value)


def test_invalid_line_rejects_entire_list_without_credentials(tmp_path):
    path = tmp_path / "invalid.txt"
    path.write_text(
        f"# header\n{PROXIES[0]}\nsocks5://fake-user:fake-password@host:80\n"
    )
    with pytest.raises(ValueError, match="line 3") as exc:
        load_proxy_list(path)
    assert "fake-user" not in str(exc.value)
    assert "fake-password" not in str(exc.value)


def test_round_robin_and_single_proxy():
    pool = ProxyPool(PROXIES)
    assert [pool.next_proxy() for _ in range(4)] == [*PROXIES, PROXIES[0]]
    single = ProxyPool([PROXIES[0], PROXIES[0]])
    assert [single.next_proxy() for _ in range(4)] == [PROXIES[0]] * 4
    with pytest.raises(ValueError, match="at least one"):
        ProxyPool([])


def test_pool_concurrent_threads_share_one_cursor():
    pool = ProxyPool(PROXIES)
    with ThreadPoolExecutor(max_workers=16) as executor:
        choices = list(executor.map(lambda _: pool.next_proxy(), range(3001)))
    assert Counter(choices) == Counter(
        {PROXIES[0]: 1001, PROXIES[1]: 1000, PROXIES[2]: 1000}
    )
    assert pool.next_proxy() == PROXIES[1]


def test_redaction_handles_encoded_decoded_and_repr_credentials():
    pool = ProxyPool(["http://fake%2Duser:fake%27password@proxy.example:80"])
    message = "fake%2duser fake%27password fake-user fake'password fake\\'password"
    assert pool.redact(message) == " ".join(["[REDACTED]"] * 5)
    assert "fake" not in repr(pool)
