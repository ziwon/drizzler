"""Validated HTTP proxy lists and a shared, thread-safe round-robin pool."""

import base64
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit


def validate_proxy_url(url: str) -> str:
    """Validate without including the URL or parser exceptions in diagnostics."""
    try:
        if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            raise ValueError
        if re.search(r"%(?![0-9a-fA-F]{2})", url):
            raise ValueError
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise ValueError
        host = parts.hostname
        if not host or parts.netloc.count("@") > 1:
            raise ValueError
        if parts.path not in ("", "/") or "?" in url or "#" in url:
            raise ValueError
        if parts.netloc.endswith(":") or parts.port == 0:
            raise ValueError
        # urlsplit validates bracketed IPv6; validate DNS names without resolving them.
        if ":" in host:
            authority = parts.netloc.rsplit("@", 1)[-1]
            if not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", authority):
                raise ValueError
        else:
            labels = host.rstrip(".").encode("idna").decode("ascii").split(".")
            if any(
                not re.fullmatch(
                    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label
                )
                for label in labels
            ):
                raise ValueError
        if parts.username is not None and not parts.username:
            raise ValueError
        # aiohttp's BasicAuth cannot represent colons in a decoded username.
        if parts.username and ":" in unquote(parts.username):
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError(
            "Invalid proxy URL; expected an HTTP/HTTPS URL with a host and optional port"
        ) from None
    return url


def load_proxy_list(path: str | Path) -> tuple[str, ...]:
    """Read a UTF-8 list, rejecting every invalid entry before any network work."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, ValueError):
        raise ValueError(
            "Cannot read proxy list; expected a readable UTF-8 file"
        ) from None
    proxies = []
    for line_number, line in enumerate(lines, 1):
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        try:
            proxies.append(validate_proxy_url(url))
        except ValueError:
            raise ValueError(
                f"Invalid proxy on line {line_number}; expected an HTTP/HTTPS proxy URL"
            ) from None
    if not proxies:
        raise ValueError("Proxy list contains no proxy URLs")
    return tuple(dict.fromkeys(proxies))


class ProxyPool:
    """One pool per run, shared by asyncio workers and yt-dlp executor threads."""

    def __init__(self, proxies: Iterable[str]) -> None:
        self._proxies = tuple(dict.fromkeys(validate_proxy_url(p) for p in proxies))
        if not self._proxies:
            raise ValueError("Proxy pool must contain at least one proxy")
        self._index = 0
        self._lock = Lock()
        secrets: set[str] = set()
        for proxy in self._proxies:
            parts = urlsplit(proxy)
            for value in (parts.username, parts.password):
                if value:
                    for variant in (value, unquote(value)):
                        escaped = variant.replace("\\", "\\\\")
                        secrets.update(
                            (
                                variant,
                                repr(variant)[1:-1],
                                escaped.replace("'", "\\'"),
                                escaped.replace('"', '\\"'),
                            )
                        )
            if parts.username:
                auth = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
                secrets.add(base64.b64encode(auth.encode()).decode())
        self._credentials = (
            re.compile(
                "|".join(re.escape(s) for s in sorted(secrets, key=len, reverse=True)),
                re.IGNORECASE,
            )
            if secrets
            else None
        )

    def next_proxy(self) -> str:
        # Only selection is synchronized; never hold the lock during network I/O.
        with self._lock:
            proxy = self._proxies[self._index]
            self._index = (self._index + 1) % len(self._proxies)
            return proxy

    def redact(self, message: object) -> str:
        """Also scrub decoded credentials and auth reprs from third-party errors."""
        text = str(message)
        return self._credentials.sub("[REDACTED]", text) if self._credentials else text


class ProxySafeLogger:
    """Route yt-dlp diagnostics through logging without exposing proxy credentials."""

    def __init__(self, logger: logging.Logger, pool: ProxyPool) -> None:
        self._logger = logger
        self._pool = pool

    def debug(self, message: str) -> None:
        self._logger.debug(self._pool.redact(message))

    def warning(self, message: str) -> None:
        self._logger.warning(self._pool.redact(message))

    def error(self, message: str) -> None:
        self._logger.error(self._pool.redact(message))
