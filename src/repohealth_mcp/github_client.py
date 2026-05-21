"""HTTP client for GitHub REST API: auth, pagination, retries, rate-limit tracking."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

DEFAULT_BASE_URL = "https://api.github.com"
USER_AGENT = "repohealth-mcp/0.1.0"

_RETRY_BACKOFFS = [1.0, 2.0, 4.0]
_STATS_BACKOFFS = [2.0, 4.0, 8.0]
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubError(Exception):
    def __init__(self, status: int, message: str, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class RateLimitExceeded(GitHubError):
    def __init__(self, reset_at_epoch: int | None) -> None:
        super().__init__(403, f"GitHub rate limit exceeded; resets at {reset_at_epoch}")
        self.reset_at_epoch = reset_at_epoch


@dataclass
class ResponseMeta:
    status: int
    rate_limit_remaining: int | None
    rate_limit_reset: int | None
    next_url: str | None


def _gh_cli_token() -> str | None:
    """Return the gh CLI's stored token from ~/.config/gh/hosts.yml, if present."""
    cfg = Path.home() / ".config" / "gh" / "hosts.yml"
    if not cfg.exists():
        return None
    try:
        data = yaml.safe_load(cfg.read_text())
        host = data.get("github.com", {}) if isinstance(data, dict) else {}
        return host.get("oauth_token")
    except Exception:
        return None


def resolve_token() -> str | None:
    """Look up GITHUB_TOKEN in env, then gh CLI's stored token, else None."""
    return os.environ.get("GITHUB_TOKEN") or _gh_cli_token()


class GitHubClient:
    """Thin httpx wrapper with GitHub-aware retries and pagination."""

    def __init__(
        self,
        token: str | None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self.last_meta: ResponseMeta | None = None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get(self, path_or_url: str, **params: Any) -> tuple[Any, ResponseMeta]:
        """Single GET with retries. Returns (body, meta)."""
        url = path_or_url if path_or_url.startswith("http") else f"{self._base_url}{path_or_url}"

        for attempt, backoff in enumerate([0.0, *_RETRY_BACKOFFS]):
            if backoff:
                self._sleep(backoff)
            try:
                response = self._client.get(url, params=params or None)
            except httpx.RequestError as e:
                if attempt == len(_RETRY_BACKOFFS):
                    raise GitHubError(0, f"network error: {e}") from e
                continue

            if response.status_code == 202:
                for stats_backoff in _STATS_BACKOFFS:
                    self._sleep(stats_backoff)
                    try:
                        response = self._client.get(url, params=params or None)
                    except httpx.RequestError as e:
                        raise GitHubError(0, f"network error: {e}") from e
                    if response.status_code != 202:
                        break
                if response.status_code == 202:
                    raise GitHubError(202, "GitHub stats still computing after retries")

            if 500 <= response.status_code < 600:
                if attempt == len(_RETRY_BACKOFFS):
                    raise GitHubError(response.status_code, f"server error: {response.text[:200]}")
                continue

            return self._handle(response)

        raise GitHubError(0, "exhausted retries")

    def paginate(self, path: str, max_rows: int | None = None, **params: Any) -> Iterator[dict]:
        """Iterate items across paginated endpoints; respects max_rows cap."""
        url: str | None = path if path.startswith("http") else f"{self._base_url}{path}"
        if params:
            url = str(httpx.URL(url, params=params))
        yielded = 0
        while url is not None:
            body, meta = self.get(url)
            if not isinstance(body, list):
                raise GitHubError(0, f"expected list from paginated endpoint, got {type(body)}")
            for item in body:
                if max_rows is not None and yielded >= max_rows:
                    return
                yield item
                yielded += 1
            url = meta.next_url

    def _handle(self, r: httpx.Response) -> tuple[Any, ResponseMeta]:
        meta = ResponseMeta(
            status=r.status_code,
            rate_limit_remaining=_int_header(r, "x-ratelimit-remaining"),
            rate_limit_reset=_int_header(r, "x-ratelimit-reset"),
            next_url=_next_url(r.headers.get("link")),
        )
        self.last_meta = meta
        if r.status_code == 200:
            return r.json(), meta
        if r.status_code == 403 and meta.rate_limit_remaining == 0:
            raise RateLimitExceeded(meta.rate_limit_reset)
        if r.status_code == 403 and "Retry-After" in r.headers:
            self._sleep(float(r.headers["Retry-After"]))
            retry = self._client.get(str(r.request.url))
            if retry.status_code == 200:
                return self._handle(retry)
            raise GitHubError(retry.status_code, "abuse-rate retry failed")
        try:
            body = r.json()
        except Exception:
            body = r.text
        raise GitHubError(r.status_code, f"GitHub {r.status_code}: {body}", body=body)


def _int_header(r: httpx.Response, name: str) -> int | None:
    val = r.headers.get(name)
    return int(val) if val is not None and val.isdigit() else None


def _next_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = _LINK_NEXT_RE.search(link_header)
    return match.group(1) if match else None
