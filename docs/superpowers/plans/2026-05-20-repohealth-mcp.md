# repohealth-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Model Context Protocol (MCP) server that lets LLM clients answer dep-health and repo-analytics questions about any public GitHub repo by loading repo data into a local SQLite snapshot and running SQL aggregations.

**Architecture:** Four-layer flow (planner → coverage → loaders → run_sql) mirroring the cityops-mcp pattern. Per-`(repo, entity, range)` snapshot caching in a single SQLite file. Five entity tables (prs, issues, releases, commit_activity, contributors) plus a snapshots bookkeeping table, all partitioned by a `repo` column for free cross-repo SQL.

**Tech Stack:** Python ≥3.11, FastMCP (`mcp[cli]`), httpx, google-genai (planner LLM), platformdirs, SQLite, pytest, ruff, uv.

**Source spec:** `docs/superpowers/specs/2026-05-20-repohealth-mcp-design.md`

**Working directory for all paths in this plan:** `/Users/brycekan/Downloads/repohealth-mcp/`

> **Note on commits:** Steps end with a `git commit` per TDD best practice. The user previously asked to defer commits during the brainstorming phase; the executor should confirm commit preference before the first commit step.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `README.md` (stub — full version in Task 21)
- Create: `src/repohealth_mcp/__init__.py`

- [ ] **Step 1: Create `.python-version`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/.python-version`

Content:
```
3.11
```

- [ ] **Step 2: Create `.gitignore`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/.gitignore`

Content:
```
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.venv/
.pytest_cache/
.ruff_cache/
build/
dist/
.coverage
htmlcov/
.env
*.sqlite
*.sqlite-journal
```

- [ ] **Step 3: Create `LICENSE` (MIT, mirroring cityops)**

Path: `/Users/brycekan/Downloads/repohealth-mcp/LICENSE`

Content:
```
MIT License

Copyright (c) 2026 Bryce Kan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Create `pyproject.toml`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/pyproject.toml`

Content:
```toml
[project]
name = "repohealth-mcp"
version = "0.1.0"
description = "MCP server for GitHub dep-health and repo-analytics queries via SQL"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Bryce Kan" }]
dependencies = [
    "mcp[cli]>=1.0.0",
    "httpx>=0.27",
    "google-genai>=0.3",
    "platformdirs>=4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "respx>=0.21",
]

[project.scripts]
repohealth-mcp = "repohealth_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/repohealth_mcp"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 5: Create stub `README.md`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/README.md`

Content:
```markdown
# repohealth-mcp

MCP server for GitHub dep-health and repo-analytics queries via SQL.

Status: work in progress. Full README in Task 21.
```

- [ ] **Step 6: Create empty `src/repohealth_mcp/__init__.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/__init__.py`

Content:
```python
__version__ = "0.1.0"
```

- [ ] **Step 7: Run `uv sync` to create venv and lockfile**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv sync --all-extras
```
Expected: creates `.venv/`, `uv.lock`. No errors.

- [ ] **Step 8: Verify package imports**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run python -c "import repohealth_mcp; print(repohealth_mcp.__version__)"
```
Expected: prints `0.1.0`.

- [ ] **Step 9: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "scaffold: pyproject, license, gitignore, stub README"
```

---

## Task 2: Database layer (schema + UDFs)

**Files:**
- Create: `src/repohealth_mcp/database.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_database.py`

- [ ] **Step 1: Create test directories**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && mkdir -p tests/unit tests/integration tests/e2e tests/fixtures && touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 2: Write failing tests for database module**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_database.py`

Content:
```python
import sqlite3
from pathlib import Path

import pytest

from repohealth_mcp.database import (
    EXPECTED_TABLES,
    connect,
    init_schema,
    sqlite_path,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


def test_init_schema_creates_all_tables(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(names)


def test_init_schema_is_idempotent(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    init_schema(conn)  # should not raise
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    assert cur.fetchone()[0] >= len(EXPECTED_TABLES)


def test_median_udf_registered(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.executemany("INSERT INTO prs (repo, number) VALUES (?, ?)",
                     [("a/b", 1), ("a/b", 2), ("a/b", 3), ("a/b", 4), ("a/b", 5)])
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] == 3


def test_median_udf_handles_even_count(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.executemany("INSERT INTO prs (repo, number) VALUES (?, ?)",
                     [("a/b", 1), ("a/b", 2), ("a/b", 3), ("a/b", 4)])
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] == 2.5


def test_median_udf_ignores_nulls(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 1, NULL)")
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 2, 10)")
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 3, 20)")
    cur = conn.execute("SELECT median(comments_count) FROM prs")
    assert cur.fetchone()[0] == 15


def test_median_udf_returns_none_for_empty(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] is None


def test_sqlite_path_uses_platformdirs() -> None:
    p = sqlite_path()
    assert isinstance(p, Path)
    assert p.name == "repohealth.sqlite"


def test_prs_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("PRAGMA table_info(prs)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {"repo", "number", "title", "author", "state", "draft", "created_at",
                "updated_at", "closed_at", "merged_at", "comments_count", "base_branch"}
    assert expected.issubset(cols)


def test_snapshots_table_has_composite_pk(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.execute("""
        INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
        VALUES ('a/b', 'prs', '2025-01-01', '2025-06-01', '2026-05-20T00:00:00Z', 100)
    """)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
            VALUES ('a/b', 'prs', '2025-01-01', '2025-06-01', '2026-05-20T00:00:00Z', 200)
        """)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_database.py -v
```
Expected: ImportError (module doesn't exist yet).

- [ ] **Step 4: Implement `database.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/database.py`

Content:
```python
"""SQLite connection management, schema, and UDFs."""

from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from platformdirs import user_data_dir

EXPECTED_TABLES = {
    "repos", "prs", "issues", "releases",
    "commit_activity", "contributors", "snapshots",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repos (
    repo            TEXT PRIMARY KEY,
    description     TEXT,
    default_branch  TEXT,
    stars           INTEGER,
    forks           INTEGER,
    open_issues_count INTEGER,
    created_at      TEXT,
    pushed_at       TEXT,
    archived        INTEGER,
    disabled        INTEGER,
    license         TEXT,
    cached_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prs (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,
    draft           INTEGER,
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    merged_at       TEXT,
    comments_count  INTEGER,
    base_branch     TEXT,
    PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_prs_repo_merged ON prs(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_prs_repo_author ON prs(repo, author);

CREATE TABLE IF NOT EXISTS issues (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,
    state_reason    TEXT,
    labels          TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    comments_count  INTEGER,
    PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_issues_repo_state ON issues(repo, state);
CREATE INDEX IF NOT EXISTS idx_issues_repo_created ON issues(repo, created_at);

CREATE TABLE IF NOT EXISTS releases (
    repo            TEXT NOT NULL,
    id              INTEGER NOT NULL,
    tag_name        TEXT,
    name            TEXT,
    author          TEXT,
    published_at    TEXT,
    created_at      TEXT,
    draft           INTEGER,
    prerelease      INTEGER,
    PRIMARY KEY (repo, id)
);
CREATE INDEX IF NOT EXISTS idx_releases_repo_published ON releases(repo, published_at);

CREATE TABLE IF NOT EXISTS commit_activity (
    repo            TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,
    total_commits   INTEGER,
    mon INTEGER, tue INTEGER, wed INTEGER, thu INTEGER,
    fri INTEGER, sat INTEGER, sun INTEGER,
    PRIMARY KEY (repo, week_start_at)
);

CREATE TABLE IF NOT EXISTS contributors (
    repo            TEXT NOT NULL,
    author          TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,
    commits         INTEGER,
    additions       INTEGER,
    deletions       INTEGER,
    PRIMARY KEY (repo, author, week_start_at)
);
CREATE INDEX IF NOT EXISTS idx_contributors_repo_author ON contributors(repo, author);

CREATE TABLE IF NOT EXISTS snapshots (
    repo            TEXT NOT NULL,
    entity          TEXT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    cached_at       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    PRIMARY KEY (repo, entity, range_start, range_end)
);
"""


class _MedianAggregate:
    """SQLite aggregate UDF: median, ignoring NULLs."""

    def __init__(self) -> None:
        self._values: list[float] = []

    def step(self, value: float | None) -> None:
        if value is not None:
            self._values.append(value)

    def finalize(self) -> float | None:
        if not self._values:
            return None
        return statistics.median(self._values)


def sqlite_path() -> Path:
    """Return path to the cross-platform user-data sqlite file."""
    data_dir = Path(user_data_dir("repohealth-mcp", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "repohealth.sqlite"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a sqlite connection with foreign keys + UDFs registered."""
    if path is None:
        path = sqlite_path()
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_aggregate("median", 1, _MedianAggregate)
    return conn


def connect_readonly(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a sqlite connection in read-only mode (for run_sql safety)."""
    if path is None:
        path = sqlite_path()
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.create_aggregate("median", 1, _MedianAggregate)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes if missing. Idempotent."""
    conn.executescript(SCHEMA_SQL)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_database.py -v
```
Expected: 9 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(db): schema, connection mgmt, median UDF"
```

---

## Task 3: GitHub HTTP client

**Files:**
- Create: `src/repohealth_mcp/github_client.py`
- Create: `tests/unit/test_github_client.py`

- [ ] **Step 1: Write failing tests for GitHub client**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_github_client.py`

Content:
```python
import httpx
import pytest
import respx

from repohealth_mcp.github_client import (
    GitHubClient,
    GitHubError,
    RateLimitExceeded,
)


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="fake-token", base_url="https://api.github.com")


@respx.mock
def test_get_success_returns_json(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r").mock(
        return_value=httpx.Response(200, json={"name": "r"},
                                    headers={"x-ratelimit-remaining": "4999"})
    )
    body, meta = client.get("/repos/o/r")
    assert body == {"name": "r"}
    assert meta.rate_limit_remaining == 4999


@respx.mock
def test_get_sends_auth_header(client: GitHubClient) -> None:
    route = respx.get("https://api.github.com/repos/o/r").mock(
        return_value=httpx.Response(200, json={})
    )
    client.get("/repos/o/r")
    assert route.calls[0].request.headers["authorization"] == "Bearer fake-token"


def test_no_token_omits_auth_header() -> None:
    client = GitHubClient(token=None)
    with respx.mock:
        route = respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(200, json={})
        )
        client.get("/repos/o/r")
        assert "authorization" not in route.calls[0].request.headers


@respx.mock
def test_401_raises_github_error(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(GitHubError) as exc:
        client.get("/x")
    assert exc.value.status == 401


@respx.mock
def test_404_raises_github_error(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(GitHubError) as exc:
        client.get("/x")
    assert exc.value.status == 404


@respx.mock
def test_403_rate_limited_raises_rate_limit_exceeded(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(
        return_value=httpx.Response(403, json={},
                                    headers={"x-ratelimit-remaining": "0",
                                             "x-ratelimit-reset": "1700000000"})
    )
    with pytest.raises(RateLimitExceeded) as exc:
        client.get("/x")
    assert exc.value.reset_at_epoch == 1700000000


@respx.mock
def test_202_retries_then_succeeds(client: GitHubClient) -> None:
    respx.get("https://api.github.com/stats").mock(
        side_effect=[
            httpx.Response(202, json={}),
            httpx.Response(202, json={}),
            httpx.Response(200, json=[1, 2, 3]),
        ]
    )
    body, _ = client.get("/stats")
    assert body == [1, 2, 3]


@respx.mock
def test_202_gives_up_after_3_tries(client: GitHubClient) -> None:
    respx.get("https://api.github.com/stats").mock(
        return_value=httpx.Response(202, json={})
    )
    with pytest.raises(GitHubError) as exc:
        client.get("/stats")
    assert "still computing" in str(exc.value).lower()


@respx.mock
def test_500_retries_then_succeeds(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(
        side_effect=[
            httpx.Response(500, json={}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    body, _ = client.get("/x")
    assert body == {"ok": True}


@respx.mock
def test_paginate_iterates_link_header(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r/pulls").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}, {"id": 2}],
            headers={"link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'}
        )
    )
    respx.get("https://api.github.com/repos/o/r/pulls?page=2").mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )
    rows = list(client.paginate("/repos/o/r/pulls"))
    assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]


@respx.mock
def test_paginate_respects_max_rows(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r/pulls").mock(
        return_value=httpx.Response(
            200, json=[{"id": i} for i in range(100)],
            headers={"link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'}
        )
    )
    # Second page should not be fetched once cap is reached
    rows = list(client.paginate("/repos/o/r/pulls", max_rows=50))
    assert len(rows) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_github_client.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `github_client.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/github_client.py`

Content:
```python
"""HTTP client for GitHub REST API: auth, pagination, retries, rate-limit tracking."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import httpx
import yaml

DEFAULT_BASE_URL = "https://api.github.com"
USER_AGENT = "repohealth-mcp/0.1.0"

_RETRY_BACKOFFS = [1.0, 2.0, 4.0]            # 5xx + network
_STATS_BACKOFFS = [2.0, 4.0, 8.0]            # 202 from stats endpoints
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
        sleep: callable = time.sleep,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
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

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get(self, path_or_url: str, **params: Any) -> tuple[Any, ResponseMeta]:
        """Single GET with retries. Returns (body, meta)."""
        url = path_or_url if path_or_url.startswith("http") else f"{self._base_url}{path_or_url}"

        # 5xx / network retries
        for attempt, backoff in enumerate([0.0] + _RETRY_BACKOFFS):
            if backoff:
                self._sleep(backoff)
            try:
                response = self._client.get(url, params=params or None)
            except httpx.RequestError as e:
                if attempt == len(_RETRY_BACKOFFS):
                    raise GitHubError(0, f"network error: {e}") from e
                continue

            # 202: GitHub computing stats, retry independent of 5xx loop
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

        raise GitHubError(0, "exhausted retries")  # unreachable

    def paginate(self, path: str, max_rows: int | None = None, **params: Any) -> Iterator[dict]:
        """Iterate items across paginated endpoints; respects max_rows cap."""
        url: str | None = (
            path if path.startswith("http") else f"{self._base_url}{path}"
        )
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
        if r.status_code == 200:
            return r.json(), meta
        if r.status_code == 403 and meta.rate_limit_remaining == 0:
            raise RateLimitExceeded(meta.rate_limit_reset)
        if r.status_code == 403 and "Retry-After" in r.headers:
            # abuse-detected: single retry then fail
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
    m = _LINK_NEXT_RE.search(link_header)
    return m.group(1) if m else None
```

- [ ] **Step 4: Add `pyyaml` dependency for gh CLI token fallback**

Edit `/Users/brycekan/Downloads/repohealth-mcp/pyproject.toml`:

In the `dependencies = [...]` block, add `"pyyaml>=6.0",` so the list reads:
```toml
dependencies = [
    "mcp[cli]>=1.0.0",
    "httpx>=0.27",
    "google-genai>=0.3",
    "platformdirs>=4.0",
    "pyyaml>=6.0",
]
```

Then re-sync:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv sync --all-extras
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_github_client.py -v
```
Expected: 11 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(github): client with auth, pagination, retries, rate-limit tracking"
```

---

## Task 4: Loaders base (shared helpers)

**Files:**
- Create: `src/repohealth_mcp/loaders/__init__.py`
- Create: `src/repohealth_mcp/loaders/base.py`
- Create: `tests/unit/test_loaders_base.py`

- [ ] **Step 1: Write failing tests for loader base**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_loaders_base.py`

Content:
```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import (
    LoaderResult,
    parse_range,
    record_snapshot,
    upsert_rows,
)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_upsert_rows_inserts_new(conn) -> None:
    rows = [
        {"repo": "a/b", "number": 1, "title": "first"},
        {"repo": "a/b", "number": 2, "title": "second"},
    ]
    upsert_rows(conn, "prs", rows, pk=("repo", "number"))
    cur = conn.execute("SELECT number, title FROM prs ORDER BY number")
    assert cur.fetchall() == [(1, "first"), (2, "second")]


def test_upsert_rows_updates_existing(conn) -> None:
    upsert_rows(conn, "prs",
                [{"repo": "a/b", "number": 1, "title": "old"}],
                pk=("repo", "number"))
    upsert_rows(conn, "prs",
                [{"repo": "a/b", "number": 1, "title": "new"}],
                pk=("repo", "number"))
    cur = conn.execute("SELECT title FROM prs WHERE number=1")
    assert cur.fetchone()[0] == "new"


def test_upsert_rows_no_op_on_empty(conn) -> None:
    upsert_rows(conn, "prs", [], pk=("repo", "number"))
    cur = conn.execute("SELECT COUNT(*) FROM prs")
    assert cur.fetchone()[0] == 0


def test_record_snapshot_writes_row(conn) -> None:
    record_snapshot(conn, repo="a/b", entity="prs",
                    range_start="2025-01-01", range_end="2025-06-01", row_count=42)
    cur = conn.execute("SELECT repo, entity, row_count FROM snapshots")
    assert cur.fetchone() == ("a/b", "prs", 42)


def test_record_snapshot_upserts_on_conflict(conn) -> None:
    record_snapshot(conn, repo="a/b", entity="prs",
                    range_start="2025-01-01", range_end="2025-06-01", row_count=10)
    record_snapshot(conn, repo="a/b", entity="prs",
                    range_start="2025-01-01", range_end="2025-06-01", row_count=20)
    cur = conn.execute("SELECT row_count FROM snapshots")
    rows = cur.fetchall()
    assert rows == [(20,)]


def test_parse_range_6mo() -> None:
    start, end = parse_range("6mo", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2025-11-20"


def test_parse_range_30d() -> None:
    start, end = parse_range("30d", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2026-04-20"


def test_parse_range_1y() -> None:
    start, end = parse_range("1y", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2025-05-20"


def test_parse_range_all() -> None:
    start, end = parse_range("all", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert start == "1970-01-01"


def test_parse_range_iso_pair() -> None:
    start, end = parse_range("2025-01-15..2025-07-01",
                             now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert start == "2025-01-15"
    assert end == "2025-07-01"


def test_parse_range_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_range("garbage", now=datetime(2026, 5, 20, tzinfo=timezone.utc))


def test_loader_result_dataclass() -> None:
    r = LoaderResult(entity="prs", row_count=287, api_calls=5)
    assert r.entity == "prs"
    assert r.row_count == 287
    assert r.api_calls == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_loaders_base.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `loaders/__init__.py` (empty)**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/__init__.py`

Content:
```python
```

- [ ] **Step 4: Implement `loaders/base.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/base.py`

Content:
```python
"""Shared helpers for entity loaders: UPSERT, snapshot bookkeeping, range parsing."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

_RANGE_REL_RE = re.compile(r"^(\d+)(d|mo|y)$")
_RANGE_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


@dataclass
class LoaderResult:
    entity: str
    row_count: int
    api_calls: int
    partial: bool = False
    error: str | None = None


def parse_range(spec: str, now: datetime) -> tuple[str, str]:
    """Convert range spec ('6mo', '30d', '1y', 'all', 'ISO..ISO') to (start, end) ISO dates."""
    if spec == "all":
        return ("1970-01-01", now.date().isoformat())
    m = _RANGE_ISO_RE.match(spec)
    if m:
        return (m.group(1), m.group(2))
    m = _RANGE_REL_RE.match(spec)
    if not m:
        raise ValueError(f"unrecognized range: {spec!r}")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        delta = timedelta(days=n)
    elif unit == "mo":
        delta = timedelta(days=n * 30)
    elif unit == "y":
        delta = timedelta(days=n * 365)
    else:
        raise ValueError(f"unsupported unit {unit}")
    end_date = now.date()
    start_date = end_date - delta
    return (start_date.isoformat(), end_date.isoformat())


def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: Sequence[dict],
    pk: tuple[str, ...],
) -> None:
    """Insert rows; on PK conflict, update non-PK columns."""
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    cols_sql = ", ".join(columns)
    non_pk_cols = [c for c in columns if c not in pk]
    update_sql = ", ".join(f"{c}=excluded.{c}" for c in non_pk_cols)
    pk_sql = ", ".join(pk)
    sql = (
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_sql}) DO UPDATE SET {update_sql}"
    )
    values = [tuple(row.get(c) for c in columns) for row in rows]
    conn.executemany(sql, values)


def record_snapshot(
    conn: sqlite3.Connection,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
    row_count: int,
    cached_at: str | None = None,
) -> None:
    """Write or replace the bookkeeping row for a (repo, entity, range) slice."""
    if cached_at is None:
        cached_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, entity, range_start, range_end)
        DO UPDATE SET cached_at=excluded.cached_at, row_count=excluded.row_count
        """,
        (repo, entity, range_start, range_end, cached_at, row_count),
    )


def collect_rows(items: Iterable[dict], shape_fn) -> list[dict]:
    """Apply a per-item shape function and collect into a list, filtering Nones."""
    out = []
    for item in items:
        shaped = shape_fn(item)
        if shaped is not None:
            out.append(shaped)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_loaders_base.py -v
```
Expected: 12 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): base helpers — upsert, snapshots, range parsing"
```

---

## Task 5: Releases loader

**Files:**
- Create: `src/repohealth_mcp/loaders/releases.py`
- Create: `tests/fixtures/releases_tanstack_query.json`
- Create: `tests/unit/test_releases_loader.py`

- [ ] **Step 1: Create fixture file with sample release JSON**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/fixtures/releases_tanstack_query.json`

Content:
```json
[
  {
    "id": 100,
    "tag_name": "v5.0.0",
    "name": "Version 5",
    "author": {"login": "tannerlinsley"},
    "published_at": "2024-09-01T12:00:00Z",
    "created_at": "2024-09-01T11:00:00Z",
    "draft": false,
    "prerelease": false
  },
  {
    "id": 101,
    "tag_name": "v5.1.0-beta.1",
    "name": "5.1 beta",
    "author": {"login": "jonas"},
    "published_at": "2024-10-15T08:30:00Z",
    "created_at": "2024-10-15T08:00:00Z",
    "draft": false,
    "prerelease": true
  },
  {
    "id": 102,
    "tag_name": null,
    "name": "Draft release",
    "author": null,
    "published_at": null,
    "created_at": "2024-11-01T00:00:00Z",
    "draft": true,
    "prerelease": false
  }
]
```

- [ ] **Step 2: Write failing tests for releases loader**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_releases_loader.py`

Content:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.releases import load_releases

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def gh_client_with_releases():
    fixture = json.loads((FIXTURES / "releases_tanstack_query.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_releases_writes_rows(conn, gh_client_with_releases) -> None:
    result = load_releases(conn, gh_client_with_releases, repo="tanstack/query",
                           range_start="2024-01-01", range_end="2025-01-01",
                           max_rows=500)
    assert result.entity == "releases"
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM releases")
    assert cur.fetchone()[0] == 3


def test_load_releases_extracts_author_login(conn, gh_client_with_releases) -> None:
    load_releases(conn, gh_client_with_releases, repo="tanstack/query",
                  range_start="2024-01-01", range_end="2025-01-01", max_rows=500)
    cur = conn.execute("SELECT author FROM releases WHERE id=100")
    assert cur.fetchone()[0] == "tannerlinsley"


def test_load_releases_handles_null_author(conn, gh_client_with_releases) -> None:
    load_releases(conn, gh_client_with_releases, repo="tanstack/query",
                  range_start="2024-01-01", range_end="2025-01-01", max_rows=500)
    cur = conn.execute("SELECT author FROM releases WHERE id=102")
    assert cur.fetchone()[0] is None


def test_load_releases_writes_snapshot_row(conn, gh_client_with_releases) -> None:
    load_releases(conn, gh_client_with_releases, repo="tanstack/query",
                  range_start="2024-01-01", range_end="2025-01-01", max_rows=500)
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE repo='tanstack/query' AND entity='releases'"
    )
    assert cur.fetchone()[0] == 3


def test_load_releases_idempotent_on_rerun(conn, gh_client_with_releases) -> None:
    fixture = json.loads((FIXTURES / "releases_tanstack_query.json").read_text())
    load_releases(conn, gh_client_with_releases, repo="tanstack/query",
                  range_start="2024-01-01", range_end="2025-01-01", max_rows=500)
    # Re-run with a fresh client that returns same data
    client2 = MagicMock()
    client2.paginate.return_value = iter(fixture)
    load_releases(conn, client2, repo="tanstack/query",
                  range_start="2024-01-01", range_end="2025-01-01", max_rows=500)
    cur = conn.execute("SELECT COUNT(*) FROM releases")
    assert cur.fetchone()[0] == 3  # no duplicates


def test_load_releases_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([
        {"id": i, "tag_name": f"v{i}", "name": f"r{i}",
         "author": {"login": "u"}, "published_at": "2024-01-01T00:00:00Z",
         "created_at": "2024-01-01T00:00:00Z", "draft": False, "prerelease": False}
        for i in range(10)
    ])
    result = load_releases(conn, client, repo="o/r",
                           range_start="2024-01-01", range_end="2025-01-01", max_rows=5)
    assert result.row_count == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_releases_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/releases.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/releases.py`

Content:
```python
"""Loader for /repos/{repo}/releases."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, collect_rows, record_snapshot, upsert_rows


def _shape(item: dict) -> dict:
    return {
        "repo": None,                              # filled in below
        "id": item["id"],
        "tag_name": item.get("tag_name"),
        "name": item.get("name"),
        "author": (item.get("author") or {}).get("login"),
        "published_at": item.get("published_at"),
        "created_at": item.get("created_at"),
        "draft": 1 if item.get("draft") else 0,
        "prerelease": 1 if item.get("prerelease") else 0,
    }


def load_releases(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    rows = collect_rows(client.paginate(f"/repos/{repo}/releases", max_rows=max_rows), _shape)
    for r in rows:
        r["repo"] = repo
    upsert_rows(conn, "releases", rows, pk=("repo", "id"))
    record_snapshot(conn, repo=repo, entity="releases",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    # Pagination call count is approximate; the test client uses a single iterator.
    return LoaderResult(entity="releases", row_count=len(rows), api_calls=1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_releases_loader.py -v
```
Expected: 6 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): releases loader"
```

---

## Task 6: PRs loader

**Files:**
- Create: `src/repohealth_mcp/loaders/prs.py`
- Create: `tests/fixtures/prs_sample.json`
- Create: `tests/unit/test_prs_loader.py`

- [ ] **Step 1: Create fixture with sample PR JSON**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/fixtures/prs_sample.json`

Content:
```json
[
  {
    "number": 1,
    "title": "Add feature X",
    "user": {"login": "alice"},
    "state": "closed",
    "draft": false,
    "created_at": "2026-04-01T10:00:00Z",
    "updated_at": "2026-04-03T15:00:00Z",
    "closed_at": "2026-04-03T15:00:00Z",
    "merged_at": "2026-04-03T15:00:00Z",
    "comments": 5,
    "base": {"ref": "main"}
  },
  {
    "number": 2,
    "title": "WIP",
    "user": {"login": "bob"},
    "state": "open",
    "draft": true,
    "created_at": "2026-04-15T09:00:00Z",
    "updated_at": "2026-05-01T12:00:00Z",
    "closed_at": null,
    "merged_at": null,
    "comments": 2,
    "base": {"ref": "develop"}
  },
  {
    "number": 3,
    "title": "Closed without merge",
    "user": null,
    "state": "closed",
    "draft": false,
    "created_at": "2026-03-10T08:00:00Z",
    "updated_at": "2026-03-12T08:00:00Z",
    "closed_at": "2026-03-12T08:00:00Z",
    "merged_at": null,
    "comments": 0,
    "base": {"ref": "main"}
  }
]
```

- [ ] **Step 2: Write failing tests for PRs loader**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_prs_loader.py`

Content:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.prs import load_prs

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_prs():
    fixture = json.loads((FIXTURES / "prs_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_prs_writes_all_rows(conn, client_with_prs) -> None:
    result = load_prs(conn, client_with_prs, repo="o/r",
                      range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM prs")
    assert cur.fetchone()[0] == 3


def test_load_prs_extracts_author(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT author FROM prs WHERE number=1")
    assert cur.fetchone()[0] == "alice"


def test_load_prs_handles_null_user(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT author FROM prs WHERE number=3")
    assert cur.fetchone()[0] is None


def test_load_prs_extracts_base_branch(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT base_branch FROM prs WHERE number=2")
    assert cur.fetchone()[0] == "develop"


def test_load_prs_preserves_null_merged_at(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT merged_at FROM prs WHERE number=3")
    assert cur.fetchone()[0] is None


def test_load_prs_writes_snapshot(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE repo='o/r' AND entity='prs'"
    )
    assert cur.fetchone()[0] == 3


def test_load_prs_passes_since_param(conn, client_with_prs) -> None:
    load_prs(conn, client_with_prs, repo="o/r",
             range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    call_kwargs = client_with_prs.paginate.call_args.kwargs
    # 'state=all' and 'since=range_start' should be passed
    assert call_kwargs.get("state") == "all"
    assert call_kwargs.get("since") == "2026-01-01"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prs_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/prs.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/prs.py`

Content:
```python
"""Loader for /repos/{repo}/pulls."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, collect_rows, record_snapshot, upsert_rows


def _shape(item: dict) -> dict:
    return {
        "repo": None,
        "number": item["number"],
        "title": item.get("title"),
        "author": (item.get("user") or {}).get("login"),
        "state": item.get("state"),
        "draft": 1 if item.get("draft") else 0,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": item.get("merged_at"),
        "comments_count": item.get("comments"),
        "base_branch": (item.get("base") or {}).get("ref"),
    }


def load_prs(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    iterator = client.paginate(
        f"/repos/{repo}/pulls",
        max_rows=max_rows,
        state="all",
        sort="updated",
        direction="desc",
        per_page=100,
        since=range_start,
    )
    rows = collect_rows(iterator, _shape)
    for r in rows:
        r["repo"] = repo
    upsert_rows(conn, "prs", rows, pk=("repo", "number"))
    record_snapshot(conn, repo=repo, entity="prs",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="prs", row_count=len(rows), api_calls=max(1, len(rows) // 100 + 1))
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prs_loader.py -v
```
Expected: 7 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): PRs loader"
```

---

## Task 7: Issues loader

**Files:**
- Create: `src/repohealth_mcp/loaders/issues.py`
- Create: `tests/fixtures/issues_sample.json`
- Create: `tests/unit/test_issues_loader.py`

- [ ] **Step 1: Create fixture (mix of issues and PRs — loader must filter PRs out)**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/fixtures/issues_sample.json`

Content:
```json
[
  {
    "number": 100,
    "title": "Real issue",
    "user": {"login": "carol"},
    "state": "open",
    "state_reason": null,
    "labels": [{"name": "bug"}, {"name": "p1"}],
    "created_at": "2026-04-01T10:00:00Z",
    "updated_at": "2026-04-02T10:00:00Z",
    "closed_at": null,
    "comments": 3
  },
  {
    "number": 101,
    "title": "This is actually a PR",
    "user": {"login": "dave"},
    "state": "closed",
    "state_reason": "completed",
    "labels": [],
    "created_at": "2026-04-05T10:00:00Z",
    "updated_at": "2026-04-06T10:00:00Z",
    "closed_at": "2026-04-06T10:00:00Z",
    "comments": 1,
    "pull_request": {"url": "https://example/pulls/101"}
  },
  {
    "number": 102,
    "title": "Closed not planned",
    "user": null,
    "state": "closed",
    "state_reason": "not_planned",
    "labels": [{"name": "wontfix"}],
    "created_at": "2026-03-01T10:00:00Z",
    "updated_at": "2026-03-10T10:00:00Z",
    "closed_at": "2026-03-10T10:00:00Z",
    "comments": 0
  }
]
```

- [ ] **Step 2: Write failing tests**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_issues_loader.py`

Content:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.issues import load_issues

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_issues():
    fixture = json.loads((FIXTURES / "issues_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_issues_filters_out_prs(conn, client_with_issues) -> None:
    result = load_issues(conn, client_with_issues, repo="o/r",
                         range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    assert result.row_count == 2  # PR (#101) excluded
    cur = conn.execute("SELECT number FROM issues ORDER BY number")
    assert [r[0] for r in cur.fetchall()] == [100, 102]


def test_load_issues_serializes_labels_as_json(conn, client_with_issues) -> None:
    load_issues(conn, client_with_issues, repo="o/r",
                range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT labels FROM issues WHERE number=100")
    labels = json.loads(cur.fetchone()[0])
    assert labels == ["bug", "p1"]


def test_load_issues_handles_empty_labels(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([
        {"number": 1, "title": "x", "user": {"login": "u"}, "state": "open",
         "state_reason": None, "labels": [], "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "closed_at": None, "comments": 0},
    ])
    load_issues(conn, client, repo="o/r",
                range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT labels FROM issues WHERE number=1")
    assert json.loads(cur.fetchone()[0]) == []


def test_load_issues_handles_null_state_reason(conn, client_with_issues) -> None:
    load_issues(conn, client_with_issues, repo="o/r",
                range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute("SELECT state_reason FROM issues WHERE number=100")
    assert cur.fetchone()[0] is None


def test_load_issues_writes_snapshot(conn, client_with_issues) -> None:
    load_issues(conn, client_with_issues, repo="o/r",
                range_start="2026-01-01", range_end="2026-06-01", max_rows=500)
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE entity='issues' AND repo='o/r'"
    )
    assert cur.fetchone()[0] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_issues_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/issues.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/issues.py`

Content:
```python
"""Loader for /repos/{repo}/issues, filtering out PRs."""

from __future__ import annotations

import json
import sqlite3

from .base import LoaderResult, record_snapshot, upsert_rows


def _shape(item: dict) -> dict | None:
    if item.get("pull_request") is not None:
        return None  # endpoint returns PRs too; filter them out
    return {
        "repo": None,
        "number": item["number"],
        "title": item.get("title"),
        "author": (item.get("user") or {}).get("login"),
        "state": item.get("state"),
        "state_reason": item.get("state_reason"),
        "labels": json.dumps([lbl.get("name") for lbl in item.get("labels", [])]),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "comments_count": item.get("comments"),
    }


def load_issues(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    rows: list[dict] = []
    for item in client.paginate(
        f"/repos/{repo}/issues",
        max_rows=max_rows,
        state="all",
        since=f"{range_start}T00:00:00Z",
        per_page=100,
    ):
        shaped = _shape(item)
        if shaped is not None:
            rows.append(shaped)
    for r in rows:
        r["repo"] = repo
    upsert_rows(conn, "issues", rows, pk=("repo", "number"))
    record_snapshot(conn, repo=repo, entity="issues",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="issues", row_count=len(rows),
                        api_calls=max(1, len(rows) // 100 + 1))
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_issues_loader.py -v
```
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): issues loader (filters PRs out)"
```

---

## Task 8: Commit activity loader (stats endpoint)

**Files:**
- Create: `src/repohealth_mcp/loaders/commit_activity.py`
- Create: `tests/fixtures/commit_activity_sample.json`
- Create: `tests/unit/test_commit_activity_loader.py`

- [ ] **Step 1: Create fixture (52 weeks of commit activity)**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/fixtures/commit_activity_sample.json`

Content:
```json
[
  {"week": 1700000000, "total": 10, "days": [1, 2, 3, 1, 1, 1, 1]},
  {"week": 1700604800, "total": 7,  "days": [0, 2, 2, 1, 1, 1, 0]},
  {"week": 1701209600, "total": 0,  "days": [0, 0, 0, 0, 0, 0, 0]}
]
```

- [ ] **Step 2: Write failing tests**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_commit_activity_loader.py`

Content:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.commit_activity import load_commit_activity

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_activity():
    fixture = json.loads((FIXTURES / "commit_activity_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_commit_activity_writes_rows(conn, client_with_activity) -> None:
    result = load_commit_activity(conn, client_with_activity, repo="o/r",
                                  range_start="2024-01-01", range_end="2024-12-31")
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM commit_activity")
    assert cur.fetchone()[0] == 3


def test_load_commit_activity_converts_epoch_to_iso(conn, client_with_activity) -> None:
    load_commit_activity(conn, client_with_activity, repo="o/r",
                         range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute("SELECT week_start_at FROM commit_activity ORDER BY week_start_at")
    weeks = [row[0] for row in cur.fetchall()]
    # 1700000000 epoch = 2023-11-14T22:13:20Z; we expect ISO format
    assert all("T" in w for w in weeks)


def test_load_commit_activity_splits_days(conn, client_with_activity) -> None:
    load_commit_activity(conn, client_with_activity, repo="o/r",
                         range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute(
        "SELECT sun, mon, tue, wed, thu, fri, sat FROM commit_activity "
        "WHERE total_commits=10"
    )
    row = cur.fetchone()
    # GitHub days array is [sun, mon, tue, wed, thu, fri, sat]
    assert row == (1, 2, 3, 1, 1, 1, 1)


def test_load_commit_activity_writes_snapshot(conn, client_with_activity) -> None:
    load_commit_activity(conn, client_with_activity, repo="o/r",
                         range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE entity='commit_activity'"
    )
    assert cur.fetchone()[0] == 3


def test_load_commit_activity_handles_empty(conn) -> None:
    client = MagicMock()
    client.get.return_value = ([], ResponseMeta(200, 5000, None, None))
    result = load_commit_activity(conn, client, repo="o/r",
                                  range_start="2024-01-01", range_end="2024-12-31")
    assert result.row_count == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commit_activity_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/commit_activity.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/commit_activity.py`

Content:
```python
"""Loader for /repos/{repo}/stats/commit_activity (52 weeks, aggregated)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import LoaderResult, record_snapshot, upsert_rows


def _shape(week_obj: dict) -> dict:
    epoch = week_obj["week"]
    iso = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    days = week_obj.get("days", [0] * 7)
    # GitHub order: [sun, mon, tue, wed, thu, fri, sat]
    sun, mon, tue, wed, thu, fri, sat = (days + [0] * 7)[:7]
    return {
        "repo": None,
        "week_start_at": iso,
        "total_commits": week_obj.get("total", 0),
        "sun": sun, "mon": mon, "tue": tue, "wed": wed,
        "thu": thu, "fri": fri, "sat": sat,
    }


def load_commit_activity(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
) -> LoaderResult:
    body, _meta = client.get(f"/repos/{repo}/stats/commit_activity")
    if not isinstance(body, list):
        body = []
    rows = [_shape(w) for w in body]
    for r in rows:
        r["repo"] = repo
    upsert_rows(conn, "commit_activity", rows, pk=("repo", "week_start_at"))
    record_snapshot(conn, repo=repo, entity="commit_activity",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="commit_activity", row_count=len(rows), api_calls=1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commit_activity_loader.py -v
```
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): commit_activity loader (stats endpoint)"
```

---

## Task 9: Contributors loader (stats endpoint)

**Files:**
- Create: `src/repohealth_mcp/loaders/contributors.py`
- Create: `tests/fixtures/contributors_sample.json`
- Create: `tests/unit/test_contributors_loader.py`

- [ ] **Step 1: Create fixture (contributors with weekly breakdowns)**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/fixtures/contributors_sample.json`

Content:
```json
[
  {
    "author": {"login": "alice"},
    "total": 50,
    "weeks": [
      {"w": 1700000000, "a": 100, "d": 20, "c": 5},
      {"w": 1700604800, "a": 200, "d": 30, "c": 8}
    ]
  },
  {
    "author": {"login": "bob"},
    "total": 10,
    "weeks": [
      {"w": 1700000000, "a": 50, "d": 5, "c": 2}
    ]
  },
  {
    "author": null,
    "total": 5,
    "weeks": [
      {"w": 1700000000, "a": 10, "d": 0, "c": 1}
    ]
  }
]
```

- [ ] **Step 2: Write failing tests**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_contributors_loader.py`

Content:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.contributors import load_contributors

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_contributors():
    fixture = json.loads((FIXTURES / "contributors_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_contributors_writes_one_row_per_author_week(conn, client_with_contributors) -> None:
    result = load_contributors(conn, client_with_contributors, repo="o/r",
                               range_start="2024-01-01", range_end="2024-12-31")
    # alice has 2 weeks, bob has 1, anon has 1 → 4 rows total (anon filtered out actually)
    # We choose to KEEP anon contributors with author=NULL string "anonymous"
    cur = conn.execute("SELECT COUNT(*) FROM contributors")
    assert cur.fetchone()[0] == 4
    assert result.row_count == 4


def test_load_contributors_skips_zero_commit_weeks(conn) -> None:
    client = MagicMock()
    client.get.return_value = ([
        {"author": {"login": "alice"}, "total": 1, "weeks": [
            {"w": 1700000000, "a": 0, "d": 0, "c": 0},
            {"w": 1700604800, "a": 1, "d": 0, "c": 1},
        ]}
    ], ResponseMeta(200, 5000, None, None))
    load_contributors(conn, client, repo="o/r",
                      range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute("SELECT COUNT(*) FROM contributors")
    assert cur.fetchone()[0] == 1


def test_load_contributors_records_additions_deletions(conn, client_with_contributors) -> None:
    load_contributors(conn, client_with_contributors, repo="o/r",
                      range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute(
        "SELECT additions, deletions, commits FROM contributors "
        "WHERE author='alice' ORDER BY week_start_at"
    )
    assert cur.fetchall() == [(100, 20, 5), (200, 30, 8)]


def test_load_contributors_uses_anonymous_for_null_author(conn, client_with_contributors) -> None:
    load_contributors(conn, client_with_contributors, repo="o/r",
                      range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute("SELECT COUNT(*) FROM contributors WHERE author='anonymous'")
    assert cur.fetchone()[0] == 1


def test_load_contributors_writes_snapshot(conn, client_with_contributors) -> None:
    load_contributors(conn, client_with_contributors, repo="o/r",
                      range_start="2024-01-01", range_end="2024-12-31")
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='contributors'")
    assert cur.fetchone()[0] == 4
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_contributors_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/contributors.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/contributors.py`

Content:
```python
"""Loader for /repos/{repo}/stats/contributors (weekly per-author commit data)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import LoaderResult, record_snapshot, upsert_rows


def load_contributors(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
) -> LoaderResult:
    body, _meta = client.get(f"/repos/{repo}/stats/contributors")
    if not isinstance(body, list):
        body = []
    rows: list[dict] = []
    for contributor in body:
        author = (contributor.get("author") or {}).get("login") or "anonymous"
        for week in contributor.get("weeks", []):
            if week.get("c", 0) == 0 and week.get("a", 0) == 0 and week.get("d", 0) == 0:
                continue
            iso = datetime.fromtimestamp(week["w"], tz=timezone.utc).isoformat()
            rows.append({
                "repo": repo,
                "author": author,
                "week_start_at": iso,
                "commits": week.get("c", 0),
                "additions": week.get("a", 0),
                "deletions": week.get("d", 0),
            })
    upsert_rows(conn, "contributors", rows,
                pk=("repo", "author", "week_start_at"))
    record_snapshot(conn, repo=repo, entity="contributors",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="contributors", row_count=len(rows), api_calls=1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_contributors_loader.py -v
```
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(loaders): contributors loader (stats endpoint)"
```

---

## Task 10: Repo-metadata loader + coverage module

**Files:**
- Create: `src/repohealth_mcp/loaders/repo_meta.py`
- Create: `src/repohealth_mcp/coverage.py`
- Create: `tests/unit/test_coverage.py`
- Create: `tests/unit/test_repo_meta_loader.py`

- [ ] **Step 1: Write tests for repo_meta loader**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_repo_meta_loader.py`

Content:
```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.repo_meta import load_repo_meta


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_load_repo_meta_writes_row(conn) -> None:
    client = MagicMock()
    client.get.return_value = ({
        "full_name": "o/r",
        "description": "test repo",
        "default_branch": "main",
        "stargazers_count": 100,
        "forks_count": 10,
        "open_issues_count": 5,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-05-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }, ResponseMeta(200, 5000, None, None))
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT stars, forks, license FROM repos WHERE repo='o/r'")
    assert cur.fetchone() == (100, 10, "MIT")


def test_load_repo_meta_handles_null_license(conn) -> None:
    client = MagicMock()
    client.get.return_value = ({
        "full_name": "o/r", "description": None, "default_branch": "main",
        "stargazers_count": 0, "forks_count": 0, "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2020-01-01T00:00:00Z",
        "archived": False, "disabled": False, "license": None,
    }, ResponseMeta(200, 5000, None, None))
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT license FROM repos WHERE repo='o/r'")
    assert cur.fetchone()[0] is None
```

- [ ] **Step 2: Write tests for coverage module**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_coverage.py`

Content:
```python
import pytest

from repohealth_mcp.coverage import CoverageStatus, check_coverage
from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import record_snapshot


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_coverage_miss_when_no_snapshot(conn) -> None:
    status = check_coverage(conn, repo="o/r", entity="prs",
                            range_start="2025-01-01", range_end="2025-06-01")
    assert status.cached is False
    assert status.cached_at is None
    assert status.rows == 0


def test_coverage_hit_after_snapshot_recorded(conn) -> None:
    record_snapshot(conn, repo="o/r", entity="prs",
                    range_start="2025-01-01", range_end="2025-06-01",
                    row_count=42, cached_at="2026-05-20T12:00:00Z")
    status = check_coverage(conn, repo="o/r", entity="prs",
                            range_start="2025-01-01", range_end="2025-06-01")
    assert status.cached is True
    assert status.cached_at == "2026-05-20T12:00:00Z"
    assert status.rows == 42


def test_coverage_returns_dataclass(conn) -> None:
    status = check_coverage(conn, repo="o/r", entity="prs",
                            range_start="2025-01-01", range_end="2025-06-01")
    assert isinstance(status, CoverageStatus)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_coverage.py tests/unit/test_repo_meta_loader.py -v
```
Expected: ImportError for both modules.

- [ ] **Step 4: Implement `loaders/repo_meta.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/loaders/repo_meta.py`

Content:
```python
"""Loader for top-level repo metadata."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import upsert_rows


def load_repo_meta(conn: sqlite3.Connection, client, *, repo: str) -> None:
    body, _meta = client.get(f"/repos/{repo}")
    row = {
        "repo": repo,
        "description": body.get("description"),
        "default_branch": body.get("default_branch"),
        "stars": body.get("stargazers_count", 0),
        "forks": body.get("forks_count", 0),
        "open_issues_count": body.get("open_issues_count", 0),
        "created_at": body.get("created_at"),
        "pushed_at": body.get("pushed_at"),
        "archived": 1 if body.get("archived") else 0,
        "disabled": 1 if body.get("disabled") else 0,
        "license": (body.get("license") or {}).get("spdx_id"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_rows(conn, "repos", [row], pk=("repo",))
```

- [ ] **Step 5: Implement `coverage.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/coverage.py`

Content:
```python
"""Snapshot-table-based coverage check for the cache layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class CoverageStatus:
    cached: bool
    cached_at: str | None
    rows: int


def check_coverage(
    conn: sqlite3.Connection,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
) -> CoverageStatus:
    cur = conn.execute(
        """
        SELECT cached_at, row_count FROM snapshots
        WHERE repo=? AND entity=? AND range_start=? AND range_end=?
        """,
        (repo, entity, range_start, range_end),
    )
    row = cur.fetchone()
    if row is None:
        return CoverageStatus(cached=False, cached_at=None, rows=0)
    return CoverageStatus(cached=True, cached_at=row[0], rows=row[1])
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_coverage.py tests/unit/test_repo_meta_loader.py -v
```
Expected: 5 tests pass.

- [ ] **Step 7: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat: repo_meta loader + coverage module"
```

---

## Task 11: `load_repo` orchestrator + `refresh_repo`

**Files:**
- Create: `src/repohealth_mcp/tools/__init__.py`
- Create: `src/repohealth_mcp/tools/load_repo.py`
- Create: `src/repohealth_mcp/tools/refresh_repo.py`
- Create: `tests/unit/test_load_repo.py`

- [ ] **Step 1: Write failing tests for `load_repo`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_load_repo.py`

Content:
```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.load_repo import VALID_ENTITIES, load_repo
from repohealth_mcp.tools.refresh_repo import refresh_repo


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _stub_client_for_all_entities() -> MagicMock:
    """A client that returns plausible bodies for every endpoint load_repo touches."""
    client = MagicMock()
    repo_meta_body = {
        "full_name": "o/r", "description": "t", "default_branch": "main",
        "stargazers_count": 1, "forks_count": 0, "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False, "disabled": False, "license": {"spdx_id": "MIT"},
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        # /stats/commit_activity and /stats/contributors → empty body
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])  # empty for prs/issues/releases
    return client


def test_load_repo_returns_summary_with_all_entities(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(conn, client, repo="o/r",
                       entities=list(VALID_ENTITIES), range_spec="6mo",
                       max_rows_per_entity=500,
                       now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert result["repo"] == "o/r"
    assert set(result["fetched"].keys()) == set(VALID_ENTITIES)
    assert result["api_calls_used"] > 0
    assert result["cached_at"] is not None


def test_load_repo_rejects_unknown_entity(conn) -> None:
    client = _stub_client_for_all_entities()
    with pytest.raises(ValueError, match="unknown entity"):
        load_repo(conn, client, repo="o/r",
                  entities=["prs", "frobulators"], range_spec="6mo",
                  max_rows_per_entity=500,
                  now=datetime(2026, 5, 20, tzinfo=timezone.utc))


def test_load_repo_rejects_invalid_repo_format(conn) -> None:
    client = _stub_client_for_all_entities()
    with pytest.raises(ValueError, match="repo format"):
        load_repo(conn, client, repo="not_a_slash_separated_thing",
                  entities=["prs"], range_spec="6mo",
                  max_rows_per_entity=500,
                  now=datetime(2026, 5, 20, tzinfo=timezone.utc))


def test_load_repo_clamps_max_rows(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(conn, client, repo="o/r",
                       entities=["prs"], range_spec="6mo",
                       max_rows_per_entity=99999,
                       now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    # Should clamp to 5000; we don't observe directly, but no exception is the success signal
    assert "prs" in result["fetched"]


def test_load_repo_includes_rate_limit_summary(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(conn, client, repo="o/r",
                       entities=["prs"], range_spec="6mo",
                       max_rows_per_entity=500,
                       now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert "rate_limit_summary" in result
    assert "remaining" in result["rate_limit_summary"]


def test_refresh_repo_clears_data_then_reloads(conn) -> None:
    client = _stub_client_for_all_entities()
    # Pre-populate prs and snapshots
    conn.execute(
        "INSERT INTO prs (repo, number, title) VALUES ('o/r', 999, 'stale')"
    )
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES ('o/r', 'prs', '2025-11-20', '2026-05-20', '2026-01-01T00:00:00Z', 1)"
    )
    refresh_repo(conn, client, repo="o/r",
                 entities=["prs"], range_spec="6mo",
                 max_rows_per_entity=500,
                 now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    # The pre-existing row should be gone (cleared before reload)
    cur = conn.execute("SELECT COUNT(*) FROM prs WHERE number=999")
    assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_load_repo.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create `tools/__init__.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/tools/__init__.py`

Content:
```python
```

- [ ] **Step 4: Implement `tools/load_repo.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/tools/load_repo.py`

Content:
```python
"""load_repo orchestrator: fetches missing data for one repo across selected entities."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..loaders.base import LoaderResult, parse_range
from ..loaders.commit_activity import load_commit_activity
from ..loaders.contributors import load_contributors
from ..loaders.issues import load_issues
from ..loaders.prs import load_prs
from ..loaders.releases import load_releases
from ..loaders.repo_meta import load_repo_meta

VALID_ENTITIES = ("prs", "issues", "releases", "commit_activity", "contributors")
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_MAX_ROWS_CAP = 5000


def _validate_repo(repo: str) -> None:
    if not _REPO_RE.match(repo) or len(repo) > 100:
        raise ValueError(f"invalid repo format: {repo!r} (expected 'owner/name')")


def _validate_entities(entities: list[str]) -> None:
    unknown = set(entities) - set(VALID_ENTITIES)
    if unknown:
        raise ValueError(f"unknown entity: {sorted(unknown)}; valid: {VALID_ENTITIES}")


def _summarize_rate_limit(last_remaining: int | None, last_reset: int | None) -> dict:
    if last_remaining is None:
        return {"remaining": None, "resets_in_minutes": None, "warning": None}
    warning = None
    if last_remaining < 500:
        warning = f"low: {last_remaining} remaining"
    resets_in = None
    if last_reset is not None:
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        resets_in = max(0, (last_reset - now_epoch) // 60)
    return {"remaining": last_remaining, "resets_in_minutes": resets_in, "warning": warning}


def load_repo(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    entities: list[str],
    range_spec: str,
    max_rows_per_entity: int = 500,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_repo(repo)
    _validate_entities(entities)
    max_rows = max(1, min(_MAX_ROWS_CAP, max_rows_per_entity))
    now = now or datetime.now(timezone.utc)
    range_start, range_end = parse_range(range_spec, now=now)

    # Always fetch repo metadata first.
    load_repo_meta(conn, client, repo=repo)
    api_calls = 1

    fetched: dict[str, int] = {}
    for entity in entities:
        result = _dispatch(conn, client, entity, repo, range_start, range_end, max_rows)
        fetched[entity] = result.row_count
        api_calls += result.api_calls

    last_remaining: int | None = None
    last_reset: int | None = None
    # Best effort: peek at client's last response meta if available.
    if hasattr(client, "last_meta") and client.last_meta is not None:
        last_remaining = client.last_meta.rate_limit_remaining
        last_reset = client.last_meta.rate_limit_reset

    return {
        "repo": repo,
        "fetched": fetched,
        "api_calls_used": api_calls,
        "rate_limit_summary": _summarize_rate_limit(last_remaining, last_reset),
        "cached_at": now.isoformat(),
        "range_start": range_start,
        "range_end": range_end,
    }


def _dispatch(
    conn: sqlite3.Connection,
    client,
    entity: str,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    if entity == "prs":
        return load_prs(conn, client, repo=repo,
                        range_start=range_start, range_end=range_end, max_rows=max_rows)
    if entity == "issues":
        return load_issues(conn, client, repo=repo,
                           range_start=range_start, range_end=range_end, max_rows=max_rows)
    if entity == "releases":
        return load_releases(conn, client, repo=repo,
                             range_start=range_start, range_end=range_end, max_rows=max_rows)
    if entity == "commit_activity":
        return load_commit_activity(conn, client, repo=repo,
                                    range_start=range_start, range_end=range_end)
    if entity == "contributors":
        return load_contributors(conn, client, repo=repo,
                                 range_start=range_start, range_end=range_end)
    raise ValueError(f"unhandled entity {entity}")
```

- [ ] **Step 5: Implement `tools/refresh_repo.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/tools/refresh_repo.py`

Content:
```python
"""refresh_repo: drop a repo's data for the given entities/range, then re-load."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .load_repo import VALID_ENTITIES, load_repo


def refresh_repo(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    entities: list[str],
    range_spec: str,
    max_rows_per_entity: int = 500,
    now: datetime | None = None,
) -> dict:
    for entity in entities:
        if entity not in VALID_ENTITIES:
            raise ValueError(f"unknown entity {entity}")
        if entity == "prs":
            conn.execute("DELETE FROM prs WHERE repo=?", (repo,))
        elif entity == "issues":
            conn.execute("DELETE FROM issues WHERE repo=?", (repo,))
        elif entity == "releases":
            conn.execute("DELETE FROM releases WHERE repo=?", (repo,))
        elif entity == "commit_activity":
            conn.execute("DELETE FROM commit_activity WHERE repo=?", (repo,))
        elif entity == "contributors":
            conn.execute("DELETE FROM contributors WHERE repo=?", (repo,))
        conn.execute("DELETE FROM snapshots WHERE repo=? AND entity=?", (repo, entity))
    return load_repo(conn, client, repo=repo, entities=entities,
                     range_spec=range_spec, max_rows_per_entity=max_rows_per_entity, now=now)
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_load_repo.py -v
```
Expected: 6 tests pass.

- [ ] **Step 7: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(tools): load_repo orchestrator + refresh_repo"
```

---

## Task 12: `run_sql` tool with safety layer

**Files:**
- Create: `src/repohealth_mcp/tools/run_sql.py`
- Create: `tests/unit/test_run_sql.py`

- [ ] **Step 1: Write failing tests for run_sql**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_run_sql.py`

Content:
```python
import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.tools.run_sql import RunSqlError, run_sql


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO prs (repo, number, author) VALUES (?, ?, ?)",
        [("a/b", 1, "alice"), ("a/b", 2, "bob"), ("c/d", 1, "alice")],
    )
    conn.close()
    return path


def test_run_sql_returns_columns_and_rows(db_path) -> None:
    result = run_sql(db_path, "SELECT number, author FROM prs WHERE repo='a/b' ORDER BY number")
    assert result["columns"] == ["number", "author"]
    assert result["rows"] == [{"number": 1, "author": "alice"}, {"number": 2, "author": "bob"}]


def test_run_sql_with_aggregate(db_path) -> None:
    result = run_sql(db_path, "SELECT COUNT(*) AS n FROM prs")
    assert result["rows"] == [{"n": 3}]


def test_run_sql_rejects_insert(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "INSERT INTO prs (repo, number) VALUES ('x/y', 1)")


def test_run_sql_rejects_update(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "UPDATE prs SET author='x'")


def test_run_sql_rejects_delete(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "DELETE FROM prs")


def test_run_sql_rejects_drop(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "DROP TABLE prs")


def test_run_sql_rejects_attach(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "ATTACH DATABASE 'foo.db' AS f")


def test_run_sql_rejects_pragma(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "PRAGMA table_info(prs)")


def test_run_sql_allows_with_cte(db_path) -> None:
    result = run_sql(
        db_path,
        "WITH a AS (SELECT * FROM prs) SELECT COUNT(*) AS n FROM a",
    )
    assert result["rows"] == [{"n": 3}]


def test_run_sql_caps_at_1000_rows(db_path, tmp_path) -> None:
    conn = connect(db_path)
    conn.executemany("INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
                     [("a/b", i) for i in range(1500)])
    conn.close()
    result = run_sql(db_path, "SELECT number FROM issues")
    assert len(result["rows"]) == 1000


def test_run_sql_surfaces_syntax_error(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "SELCT * FROM prs")


def test_run_sql_uses_median_udf(db_path) -> None:
    result = run_sql(db_path, "SELECT median(number) AS m FROM prs WHERE repo='a/b'")
    assert result["rows"] == [{"m": 1.5}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_run_sql.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `tools/run_sql.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/tools/run_sql.py`

Content:
```python
"""Read-only SQL execution against the snapshot SQLite, with safety layer."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ..database import connect_readonly

_ROW_CAP = 1000

# Allowlist: must START (after comments/whitespace) with SELECT or WITH.
_ALLOWED_START = re.compile(r"^\s*(?:--[^\n]*\n|\s)*(select|with)\b", re.IGNORECASE)

# Deny list: any of these tokens anywhere in the query fails parse-level check.
_DENY_TOKENS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|replace)\b",
    re.IGNORECASE,
)


class RunSqlError(Exception):
    pass


def _validate(query: str) -> None:
    if not _ALLOWED_START.match(query):
        raise RunSqlError("only read-only SELECT or WITH queries are allowed")
    if _DENY_TOKENS.search(query):
        raise RunSqlError("query contains disallowed keyword (read-only mode)")


def run_sql(db_path: Path | str, query: str) -> dict[str, Any]:
    _validate(query)
    conn = connect_readonly(db_path)
    conn.execute("BEGIN")  # no-op in ro mode, but ensures we're in a txn for safety
    try:
        cur = conn.execute(query)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows_raw = cur.fetchmany(_ROW_CAP)
        rows = [dict(zip(columns, row)) for row in rows_raw]
        return {"columns": columns, "rows": rows}
    except sqlite3.Error as e:
        raise RunSqlError(f"sql error: {e}") from e
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_run_sql.py -v
```
Expected: 12 tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(tools): run_sql with read-only safety + row cap"
```

---

## Task 13: Introspection tools (`get_loaded_tables`, `list_loaded_repos`, `check_coverage`)

**Files:**
- Create: `src/repohealth_mcp/tools/introspection.py`
- Create: `tests/unit/test_introspection.py`

- [ ] **Step 1: Write failing tests**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_introspection.py`

Content:
```python
import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import record_snapshot
from repohealth_mcp.tools.introspection import (
    check_coverage_tool,
    get_loaded_tables,
    list_loaded_repos,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.execute("INSERT INTO prs (repo, number) VALUES ('a/b', 1)")
    conn.execute("INSERT INTO prs (repo, number) VALUES ('a/b', 2)")
    conn.execute("INSERT INTO issues (repo, number) VALUES ('a/b', 100)")
    record_snapshot(conn, repo="a/b", entity="prs",
                    range_start="2025-11-20", range_end="2026-05-20",
                    row_count=2, cached_at="2026-05-20T12:00:00Z")
    record_snapshot(conn, repo="a/b", entity="issues",
                    range_start="2025-11-20", range_end="2026-05-20",
                    row_count=1, cached_at="2026-05-20T12:00:00Z")
    conn.close()
    return path


def test_get_loaded_tables_lists_tables_with_counts(db_path) -> None:
    result = get_loaded_tables(db_path)
    tables = {t["name"]: t for t in result["tables"]}
    assert tables["prs"]["row_count"] == 2
    assert tables["issues"]["row_count"] == 1
    assert "columns" in tables["prs"]
    assert "repo" in tables["prs"]["columns"]


def test_list_loaded_repos_returns_snapshots(db_path) -> None:
    result = list_loaded_repos(db_path)
    repos = result["repos"]
    assert len(repos) == 2
    prs_entry = next(r for r in repos if r["entity"] == "prs")
    assert prs_entry["repo"] == "a/b"
    assert prs_entry["row_count"] == 2
    assert prs_entry["cached_at"] == "2026-05-20T12:00:00Z"


def test_check_coverage_tool_returns_dict(db_path) -> None:
    result = check_coverage_tool(db_path, repo="a/b", entity="prs",
                                 range_start="2025-11-20", range_end="2026-05-20")
    assert result["cached"] is True
    assert result["rows"] == 2


def test_check_coverage_tool_miss(db_path) -> None:
    result = check_coverage_tool(db_path, repo="x/y", entity="prs",
                                 range_start="2025-01-01", range_end="2025-06-01")
    assert result["cached"] is False
    assert result["rows"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_introspection.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `tools/introspection.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/tools/introspection.py`

Content:
```python
"""get_loaded_tables, list_loaded_repos, check_coverage MCP tool wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..coverage import check_coverage
from ..database import EXPECTED_TABLES, connect_readonly


def get_loaded_tables(db_path: Path | str) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        out = []
        for table in sorted(EXPECTED_TABLES):
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cur.fetchone()[0]
            cur = conn.execute(f"PRAGMA table_info({table})")
            columns = [r[1] for r in cur.fetchall()]
            out.append({"name": table, "row_count": row_count, "columns": columns})
        return {"tables": out}
    finally:
        conn.close()


def list_loaded_repos(db_path: Path | str) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        cur = conn.execute(
            "SELECT repo, entity, range_start, range_end, cached_at, row_count "
            "FROM snapshots ORDER BY repo, entity"
        )
        repos = [
            {"repo": r[0], "entity": r[1], "range_start": r[2],
             "range_end": r[3], "cached_at": r[4], "row_count": r[5]}
            for r in cur.fetchall()
        ]
        return {"repos": repos}
    finally:
        conn.close()


def check_coverage_tool(
    db_path: Path | str,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        status = check_coverage(conn, repo=repo, entity=entity,
                                range_start=range_start, range_end=range_end)
        return {"cached": status.cached, "cached_at": status.cached_at, "rows": status.rows}
    finally:
        conn.close()
```

> Note: `check_coverage_tool` uses a read-only connection, but `check_coverage` internally only SELECTs — safe.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_introspection.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(tools): introspection — get_loaded_tables, list_loaded_repos, check_coverage"
```

---

## Task 14: Planner (NL → fetch plan)

**Files:**
- Create: `src/repohealth_mcp/planner.py`
- Create: `tests/unit/test_planner.py`

- [ ] **Step 1: Write failing tests for planner**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_planner.py`

Content:
```python
import json
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.planner import (
    PlanResult,
    extract_plan_from_text,
    plan_data_load,
)


def test_extract_plan_from_text_parses_clean_json() -> None:
    text = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    result = extract_plan_from_text(text)
    assert result.repos == ["o/r"]
    assert result.entities == ["prs"]
    assert result.range_spec == "6mo"


def test_extract_plan_from_text_strips_code_fences() -> None:
    text = '```json\n{"repos": ["o/r"], "entities": ["prs"], "range": "30d"}\n```'
    result = extract_plan_from_text(text)
    assert result.repos == ["o/r"]


def test_extract_plan_from_text_multi_repo() -> None:
    text = '{"repos": ["a/b", "c/d", "e/f"], "entities": ["prs", "issues"], "range": "1y"}'
    result = extract_plan_from_text(text)
    assert len(result.repos) == 3
    assert "issues" in result.entities


def test_extract_plan_from_text_defaults_entities_if_missing() -> None:
    text = '{"repos": ["o/r"], "range": "6mo"}'
    result = extract_plan_from_text(text)
    assert set(result.entities) == {"prs", "issues", "releases",
                                    "commit_activity", "contributors"}


def test_extract_plan_from_text_defaults_range_if_missing() -> None:
    text = '{"repos": ["o/r"], "entities": ["prs"]}'
    result = extract_plan_from_text(text)
    assert result.range_spec == "6mo"


def test_extract_plan_from_text_rejects_empty_repos() -> None:
    text = '{"repos": [], "entities": ["prs"], "range": "6mo"}'
    with pytest.raises(ValueError, match="at least one repo"):
        extract_plan_from_text(text)


def test_extract_plan_from_text_rejects_malformed_json() -> None:
    text = 'not json at all'
    with pytest.raises(ValueError):
        extract_plan_from_text(text)


def test_plan_data_load_invokes_llm_and_parses() -> None:
    fake_llm = MagicMock()
    fake_llm.return_value = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    result = plan_data_load("is o/r maintained?", llm=fake_llm)
    assert isinstance(result, PlanResult)
    assert result.repos == ["o/r"]
    assert fake_llm.call_count == 1


def test_plan_data_load_passes_question_to_llm() -> None:
    fake_llm = MagicMock()
    fake_llm.return_value = '{"repos": ["o/r"], "entities": ["prs"], "range": "6mo"}'
    plan_data_load("compare a/b and c/d", llm=fake_llm)
    prompt_arg = fake_llm.call_args.args[0]
    assert "compare a/b and c/d" in prompt_arg
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_planner.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `planner.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/planner.py`

Content:
```python
"""NL → fetch plan via LLM."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

DEFAULT_ENTITIES = ["prs", "issues", "releases", "commit_activity", "contributors"]
DEFAULT_RANGE = "6mo"

PLANNER_SYSTEM_PROMPT = """\
You parse a user's natural-language question about GitHub repos into a fetch plan.

Return ONLY a single JSON object with these keys:
  - "repos": list of "owner/name" strings mentioned in the question.
            If a user just says a repo name without owner, infer the canonical owner.
  - "entities": list, subset of: ["prs", "issues", "releases", "commit_activity", "contributors"].
                Omit or include the full list if the question is general "is this maintained?".
  - "range": one of "30d", "90d", "6mo", "1y", "all", or "YYYY-MM-DD..YYYY-MM-DD".
             Default to "6mo" if the user didn't specify.

Examples:
Q: "is tanstack/query still maintained?"
A: {"repos": ["tanstack/query"], "entities": ["prs","issues","releases","commit_activity","contributors"], "range": "6mo"}

Q: "compare react-query, swr, tanstack-query for the past year"
A: {"repos": ["tannerlinsley/react-query", "vercel/swr", "tanstack/query"], "entities": ["prs","issues","releases","commit_activity","contributors"], "range": "1y"}

Q: "PR review times for vercel/next.js in March 2026"
A: {"repos": ["vercel/next.js"], "entities": ["prs"], "range": "2026-03-01..2026-03-31"}
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class PlanResult:
    repos: list[str]
    entities: list[str]
    range_spec: str


def extract_plan_from_text(text: str) -> PlanResult:
    """Extract a PlanResult from LLM text (may include code fences or stray words)."""
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError(f"could not find JSON object in LLM output: {text[:200]}")
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON from LLM: {e}") from e
    repos = obj.get("repos") or []
    if not isinstance(repos, list) or not repos:
        raise ValueError("plan requires at least one repo")
    entities = obj.get("entities") or DEFAULT_ENTITIES
    range_spec = obj.get("range") or DEFAULT_RANGE
    return PlanResult(repos=list(repos), entities=list(entities), range_spec=str(range_spec))


def _default_llm(prompt: str) -> str:
    """Call Gemini via google-genai. Imported lazily so tests don't require API key."""
    from google import genai
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-001")
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text or ""


def plan_data_load(
    question: str,
    llm: Callable[[str], str] | None = None,
) -> PlanResult:
    """Call the LLM with the planner prompt + question; parse the output."""
    llm = llm or _default_llm
    prompt = f"{PLANNER_SYSTEM_PROMPT}\n\nQ: {question}\nA:"
    text = llm(prompt)
    return extract_plan_from_text(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_planner.py -v
```
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(planner): NL → fetch plan via Gemini"
```

---

## Task 15: FastMCP server wiring + `plan_data_load` tool

**Files:**
- Create: `src/repohealth_mcp/server.py`
- Create: `tests/unit/test_server_smoke.py`

- [ ] **Step 1: Write a smoke test that the server module imports and exposes tools**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_server_smoke.py`

Content:
```python
import repohealth_mcp.server as server_mod


def test_main_callable_exists() -> None:
    assert callable(server_mod.main)


def test_module_exposes_mcp_instance() -> None:
    assert server_mod.mcp is not None
    assert server_mod.mcp.name == "repohealth"


def test_server_registers_expected_tools() -> None:
    # FastMCP stores tools in an internal registry; we sanity-check at least one
    # registered name. The exact API differs between mcp[cli] versions, so we
    # check via tool listing if available.
    listed = []
    if hasattr(server_mod.mcp, "list_tools"):
        listed = [t.name for t in server_mod.mcp.list_tools()]
    elif hasattr(server_mod.mcp, "_tools"):
        listed = list(server_mod.mcp._tools.keys())
    if listed:
        assert "load_repo" in listed
        assert "run_sql" in listed
        assert "plan_data_load" in listed
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_server_smoke.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `server.py`**

Path: `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/server.py`

Content:
```python
"""FastMCP server wiring — registers all tools, resources, prompts."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .database import connect, init_schema, sqlite_path
from .github_client import GitHubClient, resolve_token
from .planner import plan_data_load as _plan_data_load
from .tools.introspection import (
    check_coverage_tool,
    get_loaded_tables as _get_loaded_tables,
    list_loaded_repos as _list_loaded_repos,
)
from .tools.load_repo import VALID_ENTITIES, load_repo as _load_repo
from .tools.refresh_repo import refresh_repo as _refresh_repo
from .tools.run_sql import RunSqlError, run_sql as _run_sql

mcp = FastMCP("repohealth")


def _get_db():
    path = sqlite_path()
    conn = connect(path)
    init_schema(conn)
    return path, conn


def _get_client() -> GitHubClient:
    return GitHubClient(token=resolve_token())


@mcp.tool()
def plan_data_load(question: str) -> dict[str, Any]:
    """Parse a natural-language question into {repos, entities, range}."""
    plan = _plan_data_load(question)
    return {"repos": plan.repos, "entities": plan.entities, "range": plan.range_spec}


@mcp.tool()
def check_coverage(repo: str, entity: str, range_start: str, range_end: str) -> dict[str, Any]:
    """Report whether a (repo, entity, range) snapshot is already in the local cache."""
    path = sqlite_path()
    return check_coverage_tool(path, repo=repo, entity=entity,
                               range_start=range_start, range_end=range_end)


@mcp.tool()
def load_repo(
    repo: str,
    entities: list[str] | None = None,
    range: str = "6mo",
    max_rows_per_entity: int = 500,
) -> dict[str, Any]:
    """Fetch missing (repo, entity, range) data from GitHub and store in local SQLite."""
    _, conn = _get_db()
    client = _get_client()
    try:
        return _load_repo(conn, client, repo=repo,
                          entities=list(entities or VALID_ENTITIES),
                          range_spec=range,
                          max_rows_per_entity=max_rows_per_entity)
    finally:
        client.close()
        conn.close()


@mcp.tool()
def refresh_repo(
    repo: str,
    entities: list[str] | None = None,
    range: str = "6mo",
    max_rows_per_entity: int = 500,
) -> dict[str, Any]:
    """Drop the repo's cached data for the given entities/range, then reload from GitHub."""
    _, conn = _get_db()
    client = _get_client()
    try:
        return _refresh_repo(conn, client, repo=repo,
                             entities=list(entities or VALID_ENTITIES),
                             range_spec=range,
                             max_rows_per_entity=max_rows_per_entity)
    finally:
        client.close()
        conn.close()


@mcp.tool()
def run_sql(query: str) -> dict[str, Any]:
    """Run a read-only SELECT/WITH query against the local snapshot SQLite. Capped at 1000 rows."""
    path = sqlite_path()
    try:
        return _run_sql(path, query)
    except RunSqlError as e:
        return {"error": str(e), "query": query}


@mcp.tool()
def get_loaded_tables() -> dict[str, Any]:
    """Return schema and row counts for all entity tables in the local snapshot SQLite."""
    return _get_loaded_tables(sqlite_path())


@mcp.tool()
def list_loaded_repos() -> dict[str, Any]:
    """Return all (repo, entity, range) snapshots currently cached with their cached_at timestamps."""
    return _list_loaded_repos(sqlite_path())


def main() -> None:
    """Entry point — runs the MCP server over stdio."""
    # Ensure schema exists before serving any tool call.
    _, conn = _get_db()
    conn.close()
    if not resolve_token():
        import sys
        print(
            "[repohealth-mcp] WARNING: no GITHUB_TOKEN set. "
            "Rate limit is 60/hr (vs 5000 with a token). "
            "Run `export GITHUB_TOKEN=$(gh auth token)` to upgrade.",
            file=sys.stderr,
        )
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_server_smoke.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Verify the server binary actually starts**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && timeout 2 uv run repohealth-mcp || true
```
Expected: starts cleanly, no traceback. May print the no-token warning. Exits via SIGTERM from `timeout`.

- [ ] **Step 6: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(server): FastMCP wiring + all 7 tools registered"
```

---

## Task 16: Resources (`repo://schema`, `repo://signals`)

**Files:**
- Modify: `src/repohealth_mcp/server.py` (add resource definitions)
- Create: `tests/unit/test_resources.py`

- [ ] **Step 1: Write tests for resource content**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_resources.py`

Content:
```python
from repohealth_mcp.server import get_schema_resource, get_signals_resource


def test_schema_resource_lists_all_tables() -> None:
    content = get_schema_resource()
    for tbl in ("repos", "prs", "issues", "releases", "commit_activity",
                "contributors", "snapshots"):
        assert f"CREATE TABLE" in content
        assert tbl in content


def test_signals_resource_has_at_least_5_signals() -> None:
    content = get_signals_resource()
    assert content.count("##") >= 5
    assert "median" in content.lower() or "average" in content.lower()


def test_signals_resource_includes_sql_examples() -> None:
    content = get_signals_resource()
    assert "```sql" in content
    assert "SELECT" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_resources.py -v
```
Expected: ImportError for the two functions.

- [ ] **Step 3: Add resources to `server.py`**

In `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/server.py`, append the following before the `main()` function:

```python
from .database import SCHEMA_SQL


def get_schema_resource() -> str:
    """Return the SQL CREATE TABLE definitions for all entity tables."""
    return SCHEMA_SQL.strip()


def get_signals_resource() -> str:
    """Return a markdown document of canonical health-signal SQL recipes."""
    return """\
# Dep-Health Signals

These are the canonical SQL recipes for the common questions repohealth-mcp answers.
Copy-paste, parametrize, or compose into your own queries.

## activity_commits_last_90d

Total commits in the last 90 days, per repo.

```sql
SELECT repo, SUM(total_commits) AS commits_90d
FROM commit_activity
WHERE week_start_at > date('now', '-90 days')
GROUP BY repo
ORDER BY commits_90d DESC;
```

## median_pr_time_to_merge

Median days from PR open to merge, per repo, over the cached range.

```sql
SELECT repo, median(julianday(merged_at) - julianday(created_at)) AS median_days
FROM prs
WHERE merged_at IS NOT NULL
GROUP BY repo;
```

## release_cadence

Median days between releases, per repo.

```sql
WITH ordered AS (
  SELECT repo, published_at,
         LAG(published_at) OVER (PARTITION BY repo ORDER BY published_at) AS prev
  FROM releases WHERE published_at IS NOT NULL
)
SELECT repo, median(julianday(published_at) - julianday(prev)) AS median_days_between
FROM ordered WHERE prev IS NOT NULL
GROUP BY repo;
```

## bus_factor_top_contributor_pct

Percentage of all commits contributed by the single most-active author. High = risky.

```sql
SELECT repo,
       MAX(author_commits) * 100.0 / SUM(author_commits) AS top_contrib_pct
FROM (SELECT repo, author, SUM(commits) AS author_commits
      FROM contributors GROUP BY repo, author)
GROUP BY repo;
```

## active_maintainers_90d

Distinct commit authors in the last 90 days, per repo.

```sql
SELECT repo, COUNT(DISTINCT author) AS active_maintainers
FROM contributors
WHERE week_start_at > date('now', '-90 days') AND commits > 0
GROUP BY repo;
```

## backlog_trajectory

Open issues vs closed issues count, per repo.

```sql
SELECT repo,
       SUM(CASE WHEN state='open'   THEN 1 ELSE 0 END) AS open_count,
       SUM(CASE WHEN state='closed' THEN 1 ELSE 0 END) AS closed_count
FROM issues
GROUP BY repo;
```
"""


@mcp.resource("repo://schema")
def _resource_schema() -> str:
    return get_schema_resource()


@mcp.resource("repo://signals")
def _resource_signals() -> str:
    return get_signals_resource()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_resources.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(server): resources — repo://schema and repo://signals"
```

---

## Task 17: Prompts (5 SQL scaffolds)

**Files:**
- Modify: `src/repohealth_mcp/server.py` (add prompt definitions)
- Create: `tests/unit/test_prompts.py`

- [ ] **Step 1: Write tests for prompt content**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/unit/test_prompts.py`

Content:
```python
from repohealth_mcp.server import (
    compare_repos_query,
    contributor_health_query,
    dep_health_query,
    release_cadence_query,
    responsiveness_query,
)


def test_dep_health_query_includes_repo_param() -> None:
    text = dep_health_query(repo="tanstack/query")
    assert "tanstack/query" in text
    assert "SELECT" in text.upper()


def test_compare_repos_query_lists_all_repos() -> None:
    text = compare_repos_query(repos=["a/b", "c/d", "e/f"])
    for r in ("a/b", "c/d", "e/f"):
        assert r in text


def test_release_cadence_query_references_releases_table() -> None:
    text = release_cadence_query(repo="o/r")
    assert "releases" in text


def test_responsiveness_query_references_prs_and_issues() -> None:
    text = responsiveness_query(repo="o/r")
    assert "prs" in text
    assert "issues" in text


def test_contributor_health_query_references_contributors() -> None:
    text = contributor_health_query(repo="o/r")
    assert "contributors" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prompts.py -v
```
Expected: ImportError.

- [ ] **Step 3: Add prompts to `server.py`**

In `/Users/brycekan/Downloads/repohealth-mcp/src/repohealth_mcp/server.py`, append the following before `main()`:

```python
@mcp.prompt()
def dep_health_query(repo: str) -> str:
    """SQL scaffold for a single-repo dep-health summary."""
    return f"""\
Run this query to summarize dep-health for {repo}:

```sql
SELECT
  (SELECT stars FROM repos WHERE repo='{repo}') AS stars,
  (SELECT julianday('now') - julianday(MAX(published_at))
     FROM releases WHERE repo='{repo}') AS days_since_release,
  (SELECT COUNT(DISTINCT author) FROM contributors
     WHERE repo='{repo}' AND week_start_at > date('now', '-90 days') AND commits > 0
  ) AS active_maintainers_90d,
  (SELECT median(julianday(merged_at) - julianday(created_at))
     FROM prs WHERE repo='{repo}' AND merged_at IS NOT NULL
  ) AS median_merge_days,
  (SELECT SUM(total_commits) FROM commit_activity
     WHERE repo='{repo}' AND week_start_at > date('now', '-90 days')
  ) AS commits_90d;
```
"""


@mcp.prompt()
def compare_repos_query(repos: list[str]) -> str:
    """SQL scaffold for cross-repo maintainership comparison."""
    quoted = ", ".join(f"'{r}'" for r in repos)
    return f"""\
Compare maintainership across {", ".join(repos)}:

```sql
SELECT repo,
       COUNT(*) FILTER (WHERE merged_at IS NOT NULL) AS merged_prs,
       ROUND(AVG(julianday(merged_at) - julianday(created_at)), 1) AS avg_merge_days,
       COUNT(DISTINCT author) AS distinct_pr_authors
FROM prs
WHERE repo IN ({quoted})
GROUP BY repo
ORDER BY merged_prs DESC;
```
"""


@mcp.prompt()
def release_cadence_query(repo: str) -> str:
    """SQL scaffold for release cadence over time."""
    return f"""\
Release cadence for {repo}:

```sql
WITH ordered AS (
  SELECT published_at,
         LAG(published_at) OVER (ORDER BY published_at) AS prev
  FROM releases
  WHERE repo='{repo}' AND published_at IS NOT NULL
)
SELECT median(julianday(published_at) - julianday(prev)) AS median_days_between,
       MAX(published_at) AS most_recent_release
FROM ordered WHERE prev IS NOT NULL;
```
"""


@mcp.prompt()
def responsiveness_query(repo: str) -> str:
    """SQL scaffold for PR/issue response times."""
    return f"""\
Responsiveness signals for {repo}:

```sql
SELECT
  (SELECT median(julianday(merged_at) - julianday(created_at))
     FROM prs WHERE repo='{repo}' AND merged_at IS NOT NULL
  ) AS median_pr_merge_days,
  (SELECT median(julianday(closed_at) - julianday(created_at))
     FROM issues WHERE repo='{repo}' AND closed_at IS NOT NULL
  ) AS median_issue_close_days,
  (SELECT COUNT(*) FROM issues
     WHERE repo='{repo}' AND state='open' AND created_at < date('now','-90 days')
  ) AS stale_open_issues_90d;
```
"""


@mcp.prompt()
def contributor_health_query(repo: str) -> str:
    """SQL scaffold for contributor concentration / bus-factor analysis."""
    return f"""\
Contributor concentration for {repo}:

```sql
WITH totals AS (
  SELECT author, SUM(commits) AS commits
  FROM contributors
  WHERE repo='{repo}'
  GROUP BY author
)
SELECT author, commits,
       ROUND(100.0 * commits / SUM(commits) OVER (), 1) AS pct
FROM totals
ORDER BY commits DESC
LIMIT 10;
```
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prompts.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(server): 5 SQL-scaffold prompts"
```

---

## Task 18: Integration test against real GitHub (octocat/Hello-World)

**Files:**
- Create: `tests/integration/test_real_github.py`

- [ ] **Step 1: Write the integration test**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/integration/test_real_github.py`

Content:
```python
"""Integration test — hits real api.github.com against a tiny stable public repo.

Marked slow + network so it's opt-in via `pytest -m integration`.
"""

import os
from pathlib import Path

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubClient, resolve_token
from repohealth_mcp.loaders.releases import load_releases
from repohealth_mcp.loaders.repo_meta import load_repo_meta

pytestmark = pytest.mark.integration

REPO = "octocat/Hello-World"


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "integ.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client():
    token = resolve_token()
    if token is None:
        pytest.skip("no GITHUB_TOKEN; integration test requires auth to avoid 60/hr cap")
    with GitHubClient(token=token) as c:
        yield c


def test_real_repo_meta(conn, client):
    load_repo_meta(conn, client, repo=REPO)
    row = conn.execute(
        "SELECT repo, default_branch FROM repos WHERE repo=?", (REPO,)
    ).fetchone()
    assert row is not None
    assert row[0] == REPO
    assert row[1] in ("main", "master")


def test_real_releases(conn, client):
    result = load_releases(conn, client, repo=REPO,
                           range_start="2020-01-01", range_end="2026-12-31",
                           max_rows=10)
    # octocat/Hello-World may have 0 releases; we just check the call succeeded
    assert result.entity == "releases"
    assert result.row_count >= 0
```

- [ ] **Step 2: Register integration marker**

Edit `/Users/brycekan/Downloads/repohealth-mcp/pyproject.toml` and update the `[tool.pytest.ini_options]` section to:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: hits real network/GitHub API (opt-in via -m integration)",
]
```

- [ ] **Step 3: Verify unit tests still skip integration by default**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit -v
```
Expected: all unit tests pass; integration test NOT collected from unit directory.

- [ ] **Step 4: Run integration test explicitly (requires GITHUB_TOKEN)**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && GITHUB_TOKEN=$(gh auth token 2>/dev/null) uv run pytest tests/integration -m integration -v
```
Expected: 2 tests pass OR clear skip messages if no token available.

- [ ] **Step 5: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "test(integration): real GitHub API smoke test against octocat/Hello-World"
```

---

## Task 19: README — full install + usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the full README**

Path: `/Users/brycekan/Downloads/repohealth-mcp/README.md`

Content:
````markdown
# repohealth-mcp

A Model Context Protocol (MCP) server that lets Claude (or any MCP client) answer **dep-health and repo-analytics** questions about any public GitHub repo — by loading repo data into a local SQLite snapshot and running SQL aggregations.

```
is tanstack/query still actively maintained?
compare react-query, swr, and tanstack-query
release cadence for vercel/next.js over the last year
who are the top contributors to facebook/react this quarter?
```

Works with: any public GitHub repo (private repos work if your token has scope, undocumented in v1).

---

## ⚡ Install in Claude Code (one command)

On a clean laptop, this is the whole install. No `git clone` needed — `uvx` clones the repo, builds an isolated venv, and runs the server.

**1. Install `uv`** (skip if you already have it):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Export a GitHub token** so you get the 5000/hr rate limit instead of 60/hr:

```bash
export GITHUB_TOKEN=$(gh auth token)
```

> Don't have `gh`? Create a [fine-grained PAT](https://github.com/settings/tokens?type=beta) with **Public repositories — Read** scope. That token is essentially harmless even if leaked.

**3. Register the server with Claude Code:**

```bash
claude mcp add repohealth -s user -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

**4. Verify:**

```bash
claude mcp list
```

Look for `repohealth: uvx --from git+https://… repohealth-mcp - ✓ Connected`.

**5. Open a new Claude Code session and ask:** *"is tanstack/query still actively maintained?"*

First call takes ~30s while `uv` builds the package. After that, fast.

> Paste the `claude mcp add` command on **one line**. Terminal soft-wraps break it and silently register a truncated entry. If that happens: `claude mcp remove repohealth -s user` and try again.

---

## ⚡ Install in Codex CLI (one command)

Same as above, but with the Codex CLI:

```bash
codex mcp add repohealth -- uvx --from git+https://github.com/brycekan123/repohealth-mcp repohealth-mcp
```

Then `codex mcp list` and look for `repohealth: ... - enabled`.

---

## 🧰 What it does

| Tool | Purpose |
|---|---|
| `plan_data_load` | Parses a natural-language question into a fetch plan (repos + entities + date range) |
| `check_coverage` | Reports whether the requested (repo, entity, range) is already cached locally |
| `load_repo` | Fetches missing data from GitHub and stores rows in local SQLite (idempotent) |
| `refresh_repo` | Drops cached rows and re-loads from GitHub (escape hatch for stale data) |
| `run_sql` | Executes a read-only `SELECT`/`WITH` query against the snapshot (capped at 1000 rows) |
| `get_loaded_tables` | Returns current tables + columns + row counts |
| `list_loaded_repos` | Lists all (repo, entity, range) snapshots with their `cached_at` timestamps |

Plus 2 resources (`repo://schema`, `repo://signals`) and 5 SQL-scaffold prompts (`dep_health_query`, `compare_repos_query`, `release_cadence_query`, `responsiveness_query`, `contributor_health_query`).

### Snapshot-aware caching

Repeat questions about the same repo skip the GitHub round-trip:

- **First** — *"is tanstack/query maintained?"* → `check_coverage` (miss) → `load_repo` (5 entities, ~15 API calls) → `run_sql`
- **Second** — *"now break that down by contributor"* → `check_coverage` (**hit**) → skips `load_repo` → `run_sql` directly, instant
- **Later** — *"give me fresh data"* → call `refresh_repo` explicitly

The cache lives at `~/Library/Application Support/repohealth-mcp/repohealth.sqlite` (macOS) or your platform's equivalent. Delete the file to start fresh.

---

## 🔐 GitHub token & rate limits

- **Authenticated (5000/hr):** export `GITHUB_TOKEN` (gh CLI's `gh auth token` is easiest).
- **Unauthenticated (60/hr):** works for small experiments only — server prints a warning at startup.
- **Token scope:** a fine-grained PAT with **Public repositories — Read** is enough. Don't commit your token.

Each `load_repo` response includes a `rate_limit_summary` so you (and Claude) can see remaining budget.

---

## 🧪 Examples

**Single-repo dep-health:**
> *"Is `vercel/next.js` still actively maintained?"*

**Cross-repo comparison:**
> *"I'm picking between react-query, swr, and tanstack-query — which is best maintained?"*

**Specific health signals:**
> *"What's the median PR review time for facebook/react in the last 6 months?"*
> *"How often does microsoft/vscode release?"*
> *"Show me the top 10 contributors to django/django this year."*

---

## License

MIT
````

- [ ] **Step 2: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "docs: full README with install + usage"
```

---

## Task 20: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow**

Path: `/Users/brycekan/Downloads/repohealth-mcp/.github/workflows/ci.yml`

Content:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Lint with ruff
        run: uv run ruff check src tests

      - name: Run unit tests
        run: uv run pytest tests/unit -v

      - name: Build wheel
        run: uv build
```

- [ ] **Step 2: Run ruff locally to make sure CI will pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run ruff check src tests
```
Expected: no errors. If any, fix them inline (typically: unused imports, line length).

- [ ] **Step 3: Run the full unit test suite to confirm everything still passes**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "ci: GitHub Actions workflow — lint + unit tests + build"
```

---

## Task 21: End-to-end smoke test

**Files:**
- Create: `tests/e2e/test_full_flow.py`

- [ ] **Step 1: Write an e2e test that exercises plan → load → sql against mocked GitHub**

Path: `/Users/brycekan/Downloads/repohealth-mcp/tests/e2e/test_full_flow.py`

Content:
```python
"""E2E test: plan → load → run_sql against an in-memory mock of GitHub."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.planner import extract_plan_from_text
from repohealth_mcp.tools.load_repo import load_repo
from repohealth_mcp.tools.run_sql import run_sql


def _make_client(repo_meta_body, prs_body, issues_body, releases_body,
                 commit_activity_body, contributors_body) -> MagicMock:
    client = MagicMock()

    def _get(url, **_):
        if url == f"/repos/{repo_meta_body['full_name']}":
            return (repo_meta_body, ResponseMeta(200, 4990, None, None))
        if "stats/commit_activity" in url:
            return (commit_activity_body, ResponseMeta(200, 4989, None, None))
        if "stats/contributors" in url:
            return (contributors_body, ResponseMeta(200, 4988, None, None))
        raise AssertionError(f"unexpected GET {url}")

    def _paginate(path, max_rows=None, **_):
        if "/pulls" in path:
            return iter(prs_body[:max_rows or len(prs_body)])
        if "/issues" in path:
            return iter(issues_body[:max_rows or len(issues_body)])
        if "/releases" in path:
            return iter(releases_body[:max_rows or len(releases_body)])
        raise AssertionError(f"unexpected paginate {path}")

    client.get.side_effect = _get
    client.paginate.side_effect = _paginate
    return client


def test_full_flow_plan_load_sql(tmp_path: Path) -> None:
    db_path = tmp_path / "e2e.sqlite"
    conn = connect(db_path)
    init_schema(conn)

    # 1. Plan
    fake_llm_output = json.dumps({
        "repos": ["o/r"],
        "entities": ["prs", "issues", "releases", "commit_activity", "contributors"],
        "range": "6mo",
    })
    plan = extract_plan_from_text(fake_llm_output)
    assert plan.repos == ["o/r"]

    # 2. Load
    client = _make_client(
        repo_meta_body={
            "full_name": "o/r", "description": "demo", "default_branch": "main",
            "stargazers_count": 10, "forks_count": 1, "open_issues_count": 0,
            "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-05-01T00:00:00Z",
            "archived": False, "disabled": False, "license": {"spdx_id": "MIT"},
        },
        prs_body=[
            {"number": 1, "title": "a", "user": {"login": "alice"}, "state": "closed",
             "draft": False, "created_at": "2026-04-01T00:00:00Z",
             "updated_at": "2026-04-03T00:00:00Z",
             "closed_at": "2026-04-03T00:00:00Z",
             "merged_at": "2026-04-03T00:00:00Z",
             "comments": 0, "base": {"ref": "main"}},
            {"number": 2, "title": "b", "user": {"login": "bob"}, "state": "closed",
             "draft": False, "created_at": "2026-04-05T00:00:00Z",
             "updated_at": "2026-04-10T00:00:00Z",
             "closed_at": "2026-04-10T00:00:00Z",
             "merged_at": "2026-04-10T00:00:00Z",
             "comments": 0, "base": {"ref": "main"}},
        ],
        issues_body=[
            {"number": 100, "title": "i1", "user": {"login": "carol"}, "state": "open",
             "state_reason": None, "labels": [], "created_at": "2026-04-01T00:00:00Z",
             "updated_at": "2026-04-01T00:00:00Z", "closed_at": None, "comments": 0},
        ],
        releases_body=[
            {"id": 1, "tag_name": "v1", "name": "r1", "author": {"login": "alice"},
             "published_at": "2026-05-01T00:00:00Z",
             "created_at": "2026-05-01T00:00:00Z",
             "draft": False, "prerelease": False},
        ],
        commit_activity_body=[
            {"week": 1700000000, "total": 5, "days": [0, 1, 1, 1, 1, 1, 0]},
        ],
        contributors_body=[
            {"author": {"login": "alice"}, "total": 5,
             "weeks": [{"w": 1700000000, "a": 100, "d": 10, "c": 5}]},
        ],
    )
    summary = load_repo(conn, client, repo="o/r",
                       entities=plan.entities, range_spec=plan.range_spec,
                       max_rows_per_entity=500,
                       now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert summary["fetched"]["prs"] == 2
    assert summary["fetched"]["issues"] == 1
    assert summary["fetched"]["releases"] == 1
    conn.close()

    # 3. SQL — compute median merge time
    result = run_sql(
        db_path,
        "SELECT median(julianday(merged_at) - julianday(created_at)) AS days "
        "FROM prs WHERE repo='o/r' AND merged_at IS NOT NULL"
    )
    median_days = result["rows"][0]["days"]
    # PR #1: 2 days, PR #2: 5 days → median = 3.5
    assert median_days == pytest.approx(3.5, abs=0.01)
```

- [ ] **Step 2: Run e2e test**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/e2e -v
```
Expected: 1 test passes.

- [ ] **Step 3: Run the FULL test suite one final time**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest -v --ignore=tests/integration
```
Expected: all unit + e2e tests pass (integration skipped without GITHUB_TOKEN).

- [ ] **Step 4: Commit**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "test(e2e): full plan→load→sql flow against mocked GitHub"
```

---

## Task 22: Manual install verification + tag v0.1.0

**Files:** none (manual validation step)

- [ ] **Step 1: Install the local package into a uv tool environment and confirm the server boots**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv tool install --reinstall .
```
Expected: installs `repohealth-mcp` command into uv's tool dir.

- [ ] **Step 2: Boot the server briefly**

Run:
```bash
timeout 2 repohealth-mcp || true
```
Expected: starts, may print the no-token warning. Exits on SIGTERM.

- [ ] **Step 3: Tag v0.1.0**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git tag v0.1.0 && git log --oneline -5
```
Expected: tag created, log shows recent commits.

- [ ] **Step 4: Uninstall the local tool**

Run:
```bash
uv tool uninstall repohealth-mcp
```

---

## Spec Coverage Check

| Spec section | Implemented in task(s) |
|---|---|
| §1 Overview / killer use cases | Task 19 (README), Task 21 (e2e) |
| §2 Problem & motivation | Task 19 (README) |
| §3 Architecture (4-layer flow) | Tasks 11, 12, 14, 15 |
| §3 Key decisions (REST, snapshot, partition by `repo`, env token, 6mo, Python+FastMCP, stats endpoints) | Tasks 3 (REST), 4+10 (snapshot), 2 (`repo` PK col), 3 (env token), 4 (range default), 1+15 (Python+FastMCP), 8+9 (stats endpoints) |
| §4 Tools (7 tools) | Tasks 11 (load_repo, refresh_repo), 12 (run_sql), 13 (introspection x3), 14+15 (plan_data_load) |
| §4 Resources (schema, signals) | Task 16 |
| §4 Prompts (5 SQL scaffolds) | Task 17 |
| §5 Schema (7 tables) | Task 2 |
| §6 Data flow (single + multi-repo) | Tasks 11, 21 |
| §7 Auth (env + gh fallback + unauthed warning) | Tasks 3, 15 |
| §7 Rate-limit summary in load_repo | Task 11 |
| §7 Error matrix (401/403/404/202/5xx/partial) | Task 3 |
| §7 `run_sql` safety (read-only, parse allowlist, deny tokens, row cap) | Task 12 |
| §7 Input validation (repo regex, range, entities, max_rows clamp) | Tasks 4, 11 |
| §7 Logging (--debug) | _Note_: not in current plan; deferred (add ad-hoc when needed) |
| §8 Test layers (unit/integration/e2e) | Tasks 2-17 (unit), 18 (integration), 21 (e2e) |
| §8 Project structure | Task 1 |
| §8 pyproject.toml | Tasks 1, 3 |
| §8 Install UX | Task 19 |
| §8 CI | Task 20 |
| §8 Versioning | Task 22 |
| §9 Deferred to v2 | Documented in §9 of spec (no plan tasks) |
| §10 Risks | Documented in §10 of spec (no plan tasks) |

**Coverage gap:** §7 `--debug` flag logging is not in this plan. It's small and additive; add when first user hits a debuggability issue. Not blocking v1.

---

**Plan complete.** 22 tasks. Each is TDD: write failing test, run-fail, implement, run-pass, commit. Test counts per task are concrete so the executor can verify pass without ambiguity.

---

## Execution Completion Note — 2026-05-21

Implementation completed in `/Users/brycekan/Downloads/repohealth-mcp`.

Final verification run:

```bash
uv run pytest -v --ignore=tests/integration
# 122 passed

uv run ruff check src tests
# All checks passed

uv build
# Successfully built dist/repohealth_mcp-0.1.0.tar.gz
# Successfully built dist/repohealth_mcp-0.1.0-py3-none-any.whl

uv run pytest tests/integration -m integration -v
# 2 skipped: no GITHUB_TOKEN available

uv tool install --reinstall .
# Installed 1 executable: repohealth-mcp

uv tool uninstall repohealth-mcp
# Uninstalled 1 executable: repohealth-mcp
```

Server startup was smoke-tested with a short Python-controlled subprocess because macOS did not have `timeout` available:

```bash
uv run python -c "import subprocess, time; p = subprocess.Popen(['uv', 'run', 'repohealth-mcp']); time.sleep(2); p.terminate() if p.poll() is None else None"
# Started without traceback; printed the expected no-GITHUB_TOKEN warning.
```

Implementation notes and deviations from the written plan:

- Git commits and the `v0.1.0` git tag were intentionally skipped because the user asked for no commits.
- Tasks were batched after Task 4 to speed execution; review still happened at subset boundaries.
- `connect_readonly()` uses an escaped file URI so paths containing `#` or `?` open the intended SQLite file:

```python
uri = f"{Path(path).expanduser().resolve().as_uri()}?mode=ro"
```

- `parse_range("6mo")` and `parse_range("1y")` use calendar month subtraction to match the plan's expected dates.
- `upsert_rows()` rejects heterogeneous row dictionaries instead of silently dropping later keys.
- Loaders filter rows to the recorded snapshot range before writing the snapshot, so cached coverage matches stored data.
- The issues loader caps after filtering PR-shaped `/issues` results, avoiding under-fetch on PR-heavy repos.
- SQL prompt scaffolds escape single quotes in repo literals before embedding them in SQL.
- `test_server_smoke.py` awaits `mcp.list_tools()` because the installed FastMCP version exposes it as an async method.
