# repohealth-mcp v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the breadth of GitHub signals exposed by repohealth-mcp — add commits, per-commit file diffs, PR reviews, PR review comments, dependency graph, star history, CI / workflow runs, and funding metadata — plus freshness tracking on cached snapshots. No architectural changes.

**Architecture:** Each new signal type is a new loader, a new SQLite table, and where relevant an entry in the `repo://signals` resource and / or a new prompt scaffold. The existing parallel orchestrator (`tools/load_repo.py`) accepts any number of entity loaders by name; v2 loaders plug in by adding to `VALID_ENTITIES` and `_dispatch`. Cross-repo features are explicitly out of scope and deferred to v3.

**Tech Stack:** Python ≥3.11, FastMCP (`mcp[cli]`), httpx, SQLite (no new dependencies — `pyyaml` is already in v1's deps for the funding signal). All loaders use the existing `GitHubClient`, `parse_range`, `date_in_range`, `upsert_rows`, `record_snapshot` primitives.

**Source spec:** none separate — v2 was scoped in conversation. Decisions captured in this plan.

**Working directory for all paths:** `/Users/brycekan/Downloads/repohealth-mcp/`

**v1 reference:** `docs/superpowers/plans/v0.1.0-implementation-plan.md`

---

## Out of scope (for v3)

- Cross-repo bulk-load helper (e.g. `load_repos(list[str])`).
- Built-in comparison prompts that target N repos.
- Maintainer-overlap / contributor-graph analyses.
- Cross-repo commit-file hotspot comparisons. Single-repo `commit_files` loading is included in v2.
- Any architectural changes to parallel orchestration, retry budgets, or caching.

---

## Task 1: Schema migration for v2 tables

**Files:**
- Modify: `src/repohealth_mcp/database.py` (add tables to `SCHEMA_SQL`, add to `EXPECTED_TABLES`)
- Modify: `tests/unit/test_database.py` (assert new tables exist with key columns)

- [ ] **Step 1: Write failing tests**

Add to the bottom of `tests/unit/test_database.py`:

```python
def test_commits_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(commits)").fetchall()}
    expected = {"repo", "sha", "author", "author_email", "committed_at", "message"}
    assert expected.issubset(cols)


def test_commit_files_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(commit_files)").fetchall()}
    expected = {"repo", "sha", "filename", "status", "additions", "deletions", "changes"}
    assert expected.issubset(cols)


def test_pr_reviews_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_reviews)").fetchall()}
    expected = {"repo", "pr_number", "id", "reviewer", "state", "submitted_at"}
    assert expected.issubset(cols)


def test_pr_review_comments_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_review_comments)").fetchall()}
    expected = {
        "repo", "pr_number", "id", "reviewer", "body",
        "path", "line", "position", "created_at",
    }
    assert expected.issubset(cols)


def test_dependencies_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(dependencies)").fetchall()}
    expected = {"repo", "package_name", "package_manager", "version", "license"}
    assert expected.issubset(cols)


def test_star_history_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(star_history)").fetchall()}
    expected = {"repo", "starred_at", "user"}
    assert expected.issubset(cols)


def test_workflow_runs_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    expected = {
        "repo", "id", "workflow_name", "head_branch", "event",
        "status", "conclusion", "created_at", "run_started_at", "duration_seconds",
    }
    assert expected.issubset(cols)


def test_repos_table_has_funding_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    assert "funding_json" in cols
    assert "has_sponsors" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_database.py -k "commits or pr_reviews or dependencies or star_history or workflow_runs or funding" -v
```
Expected: FAIL — tables / columns do not exist.

- [ ] **Step 3: Extend `SCHEMA_SQL` and `EXPECTED_TABLES`**

In `src/repohealth_mcp/database.py`, update `EXPECTED_TABLES`:

```python
EXPECTED_TABLES = {
    "repos",
    "prs",
    "issues",
    "releases",
    "commit_activity",
    "contributors",
    "snapshots",
    "commits",
    "commit_files",
    "pr_reviews",
    "pr_review_comments",
    "dependencies",
    "star_history",
    "workflow_runs",
}
```

Append to `SCHEMA_SQL` (after the existing `snapshots` table block, before the closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS commits (
    repo            TEXT NOT NULL,
    sha             TEXT NOT NULL,
    author          TEXT,
    author_email    TEXT,
    committed_at    TEXT,
    message         TEXT,
    PRIMARY KEY (repo, sha)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_date   ON commits(repo, committed_at);
CREATE INDEX IF NOT EXISTS idx_commits_repo_author ON commits(repo, author);

CREATE TABLE IF NOT EXISTS commit_files (
    repo         TEXT NOT NULL,
    sha          TEXT NOT NULL,
    filename     TEXT NOT NULL,
    status       TEXT,
    additions    INTEGER,
    deletions    INTEGER,
    changes      INTEGER,
    PRIMARY KEY (repo, sha, filename)
);
CREATE INDEX IF NOT EXISTS idx_commit_files_repo_filename ON commit_files(repo, filename);

CREATE TABLE IF NOT EXISTS pr_reviews (
    repo            TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    id              INTEGER NOT NULL,
    reviewer        TEXT,
    state           TEXT,
    submitted_at    TEXT,
    PRIMARY KEY (repo, pr_number, id)
);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_repo_pr ON pr_reviews(repo, pr_number);

CREATE TABLE IF NOT EXISTS pr_review_comments (
    repo            TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    id              INTEGER NOT NULL,
    reviewer        TEXT,
    body            TEXT,
    path            TEXT,
    line            INTEGER,
    position        INTEGER,
    created_at      TEXT,
    PRIMARY KEY (repo, pr_number, id)
);
CREATE INDEX IF NOT EXISTS idx_pr_review_comments_repo_pr ON pr_review_comments(repo, pr_number);

CREATE TABLE IF NOT EXISTS dependencies (
    repo             TEXT NOT NULL,
    package_name     TEXT NOT NULL,
    package_manager  TEXT,
    version          TEXT,
    license          TEXT,
    PRIMARY KEY (repo, package_name)
);

CREATE TABLE IF NOT EXISTS star_history (
    repo         TEXT NOT NULL,
    starred_at   TEXT NOT NULL,
    user         TEXT NOT NULL,
    PRIMARY KEY (repo, starred_at, user)
);
CREATE INDEX IF NOT EXISTS idx_star_history_repo_at ON star_history(repo, starred_at);

CREATE TABLE IF NOT EXISTS workflow_runs (
    repo              TEXT NOT NULL,
    id                INTEGER NOT NULL,
    workflow_name     TEXT,
    head_branch       TEXT,
    event             TEXT,
    status            TEXT,
    conclusion        TEXT,
    created_at        TEXT,
    run_started_at    TEXT,
    duration_seconds  INTEGER,
    PRIMARY KEY (repo, id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_repo_created ON workflow_runs(repo, created_at);
```

Also extend the existing `repos` table block to include funding columns. Replace the `repos` CREATE block with:

```sql
CREATE TABLE IF NOT EXISTS repos (
    repo              TEXT PRIMARY KEY,
    description       TEXT,
    default_branch    TEXT,
    stars             INTEGER,
    forks             INTEGER,
    open_issues_count INTEGER,
    created_at        TEXT,
    pushed_at         TEXT,
    archived          INTEGER,
    disabled          INTEGER,
    license           TEXT,
    funding_json      TEXT,
    has_sponsors      INTEGER,
    cached_at         TEXT NOT NULL
);
```

> **Migration note:** the schema uses `CREATE TABLE IF NOT EXISTS`. For users on v0.1.0, the existing `repos` table will not pick up the new columns automatically. Add a migration block immediately after `executescript(SCHEMA_SQL)` in `init_schema`:

```python
def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes if missing. Idempotent. Adds v2 columns to existing repos table."""
    conn.executescript(SCHEMA_SQL)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    for col, decl in (("funding_json", "TEXT"), ("has_sponsors", "INTEGER")):
        if col not in existing:
            conn.execute(f"ALTER TABLE repos ADD COLUMN {col} {decl}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_database.py -v
```
Expected: all pass, including the 6 new column-check tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && git add -A && git commit -m "feat(db): v2 schema — commits, pr_reviews, dependencies, star_history, workflow_runs, funding columns"
```

---

## Task 2: Commits loader

**Files:**
- Create: `src/repohealth_mcp/loaders/commits.py`
- Create: `tests/fixtures/commits_sample.json`
- Create: `tests/unit/test_commits_loader.py`

- [ ] **Step 1: Create fixture**

Path: `tests/fixtures/commits_sample.json`

```json
[
  {
    "sha": "abc111",
    "commit": {
      "author": {
        "name": "Alice",
        "email": "alice@example.com",
        "date": "2026-04-10T10:00:00Z"
      },
      "message": "Add feature X"
    },
    "author": {"login": "alice"}
  },
  {
    "sha": "abc222",
    "commit": {
      "author": {
        "name": "Bot",
        "email": "bot@example.com",
        "date": "2026-04-12T15:00:00Z"
      },
      "message": "chore: bump deps"
    },
    "author": null
  },
  {
    "sha": "abc333",
    "commit": {
      "author": {
        "name": "Carol",
        "email": "carol@example.com",
        "date": "2024-01-01T00:00:00Z"
      },
      "message": "Old commit"
    },
    "author": {"login": "carol"}
  }
]
```

- [ ] **Step 2: Write failing tests**

Path: `tests/unit/test_commits_loader.py`

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.commits import load_commits

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_commits():
    fixture = json.loads((FIXTURES / "commits_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_commits_writes_in_range(conn, client_with_commits) -> None:
    result = load_commits(
        conn, client_with_commits, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 2
    cur = conn.execute("SELECT sha FROM commits ORDER BY sha")
    assert [r[0] for r in cur.fetchall()] == ["abc111", "abc222"]


def test_load_commits_prefers_github_login_over_commit_author_name(conn, client_with_commits) -> None:
    load_commits(
        conn, client_with_commits, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT author FROM commits WHERE sha='abc111'")
    assert cur.fetchone()[0] == "alice"


def test_load_commits_falls_back_to_commit_author_name_when_login_missing(conn, client_with_commits) -> None:
    load_commits(
        conn, client_with_commits, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT author FROM commits WHERE sha='abc222'")
    assert cur.fetchone()[0] == "Bot"


def test_load_commits_passes_since_until_params(conn, client_with_commits) -> None:
    load_commits(
        conn, client_with_commits, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    call_kwargs = client_with_commits.paginate.call_args.kwargs
    assert call_kwargs.get("since") == "2026-01-01T00:00:00Z"
    assert call_kwargs.get("until") == "2026-06-01T23:59:59Z"


def test_load_commits_writes_snapshot(conn, client_with_commits) -> None:
    load_commits(
        conn, client_with_commits, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='commits' AND repo='o/r'")
    assert cur.fetchone()[0] == 2


def test_load_commits_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([
        {"sha": f"s{i}",
         "commit": {"author": {"name": "u", "email": "u@x", "date": "2026-04-01T00:00:00Z"},
                    "message": "m"},
         "author": {"login": "u"}}
        for i in range(10)
    ])
    result = load_commits(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=5,
    )
    assert result.row_count == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commits_loader.py -v
```
Expected: ImportError on `repohealth_mcp.loaders.commits`.

- [ ] **Step 4: Implement `loaders/commits.py`**

Path: `src/repohealth_mcp/loaders/commits.py`

```python
"""Loader for /repos/{repo}/commits."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _shape(item: dict) -> dict:
    commit = item.get("commit") or {}
    commit_author = commit.get("author") or {}
    gh_user = (item.get("author") or {}).get("login")
    return {
        "repo": None,
        "sha": item["sha"],
        "author": gh_user or commit_author.get("name"),
        "author_email": commit_author.get("email"),
        "committed_at": commit_author.get("date"),
        "message": commit.get("message"),
    }


def load_commits(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    iterator = client.paginate(
        f"/repos/{repo}/commits",
        per_page=100,
        since=f"{range_start}T00:00:00Z",
        until=f"{range_end}T23:59:59Z",
    )
    rows: list[dict] = []
    for item in iterator:
        row = _shape(item)
        if not date_in_range(row["committed_at"], range_start, range_end):
            continue
        row["repo"] = repo
        rows.append(row)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "commits", rows, pk=("repo", "sha"))
    record_snapshot(
        conn, repo=repo, entity="commits",
        range_start=range_start, range_end=range_end, row_count=len(rows),
    )
    return LoaderResult(entity="commits", row_count=len(rows), api_calls=max(1, len(rows) // 100 + 1))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commits_loader.py -v
```
Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(loaders): commits — per-commit author / message / date"
```

---

## Task 3: PR reviews loader

**Notes:** Reviews live at `/repos/{repo}/pulls/{number}/reviews`, one call per PR. Because this is N+1 against the PR table, `pr_reviews` is an **opt-in** entity — the client must include it in `entities=[...]` explicitly. Inside the loader, review-fetch is done with a small `ThreadPoolExecutor` so the N PR-review fetches run concurrently.

**Files:**
- Create: `src/repohealth_mcp/loaders/pr_reviews.py`
- Create: `tests/unit/test_pr_reviews_loader.py`

- [ ] **Step 1: Write failing tests**

Path: `tests/unit/test_pr_reviews_loader.py`

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.pr_reviews import load_pr_reviews


@pytest.fixture
def conn_with_prs(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    # Pre-seed prs so the reviews loader has something to enumerate.
    c.execute(
        "INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)", ("o/r", 1, "2026-04-01T00:00:00Z")
    )
    c.execute(
        "INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)", ("o/r", 2, "2026-04-15T00:00:00Z")
    )
    return c


def test_load_pr_reviews_writes_rows_per_pr(conn_with_prs) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r/pulls/1/reviews":
            return ([
                {"id": 10, "user": {"login": "carol"}, "state": "APPROVED",
                 "submitted_at": "2026-04-02T12:00:00Z"},
                {"id": 11, "user": {"login": "dave"}, "state": "COMMENTED",
                 "submitted_at": "2026-04-02T13:00:00Z"},
            ], ResponseMeta(200, 4999, None, None))
        if url == "/repos/o/r/pulls/2/reviews":
            return ([
                {"id": 20, "user": {"login": "carol"}, "state": "CHANGES_REQUESTED",
                 "submitted_at": "2026-04-16T09:00:00Z"},
            ], ResponseMeta(200, 4999, None, None))
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get

    result = load_pr_reviews(
        conn_with_prs, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_prs.execute("SELECT pr_number, reviewer, state FROM pr_reviews ORDER BY pr_number, id")
    rows = cur.fetchall()
    assert rows == [
        (1, "carol", "APPROVED"),
        (1, "dave", "COMMENTED"),
        (2, "carol", "CHANGES_REQUESTED"),
    ]


def test_load_pr_reviews_handles_pr_with_no_reviews(conn_with_prs) -> None:
    client = MagicMock()
    client.get.return_value = ([], ResponseMeta(200, 4999, None, None))
    result = load_pr_reviews(
        conn_with_prs, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0


def test_load_pr_reviews_skips_when_no_prs_cached(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_pr_reviews(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0
    assert client.get.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_pr_reviews_loader.py -v
```
Expected: ImportError on `pr_reviews` module.

- [ ] **Step 3: Implement `loaders/pr_reviews.py`**

Path: `src/repohealth_mcp/loaders/pr_reviews.py`

```python
"""Loader for /repos/{repo}/pulls/{number}/reviews.

This is an N+1 endpoint: one call per cached PR. The loader enumerates PRs already in
the local snapshot for this repo + range and fetches reviews for each concurrently.

Opt-in: include "pr_reviews" in entities to enable.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import LoaderResult, record_snapshot, upsert_rows

_MAX_WORKERS = 8


def _shape(repo: str, pr_number: int, review: dict) -> dict:
    return {
        "repo": repo,
        "pr_number": pr_number,
        "id": review["id"],
        "reviewer": (review.get("user") or {}).get("login"),
        "state": review.get("state"),
        "submitted_at": review.get("submitted_at"),
    }


def _list_target_prs(conn: sqlite3.Connection, repo: str, range_start: str, range_end: str) -> list[int]:
    cur = conn.execute(
        "SELECT number FROM prs WHERE repo=? AND created_at >= ? AND created_at <= ?",
        (repo, f"{range_start}T00:00:00Z", f"{range_end}T23:59:59Z"),
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_reviews_for_pr(client, repo: str, pr_number: int) -> list[dict]:
    body, _ = client.get(f"/repos/{repo}/pulls/{pr_number}/reviews")
    if not isinstance(body, list):
        return []
    return [_shape(repo, pr_number, r) for r in body]


def load_pr_reviews(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    pr_numbers = _list_target_prs(conn, repo, range_start, range_end)
    if not pr_numbers:
        record_snapshot(conn, repo=repo, entity="pr_reviews",
                        range_start=range_start, range_end=range_end, row_count=0)
        return LoaderResult(entity="pr_reviews", row_count=0, api_calls=0)

    rows: list[dict] = []
    api_calls = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(pr_numbers))) as ex:
        futures = {ex.submit(_fetch_reviews_for_pr, client, repo, n): n for n in pr_numbers}
        for fut in as_completed(futures):
            api_calls += 1
            if len(rows) >= max_rows:
                continue
            rows.extend(fut.result())
            rows = rows[:max_rows]

    upsert_rows(conn, "pr_reviews", rows, pk=("repo", "pr_number", "id"))
    record_snapshot(conn, repo=repo, entity="pr_reviews",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="pr_reviews", row_count=len(rows), api_calls=api_calls)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_pr_reviews_loader.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(loaders): pr_reviews — concurrent per-PR review fetch (opt-in)"
```

---

## Task 4: Dependency graph (SBOM) loader

**Notes:** Endpoint is `/repos/{repo}/dependency-graph/sbom`. Returns a single SPDX-format document. No pagination.

**Files:**
- Create: `src/repohealth_mcp/loaders/dependencies.py`
- Create: `tests/fixtures/sbom_sample.json`
- Create: `tests/unit/test_dependencies_loader.py`

- [ ] **Step 1: Create fixture**

Path: `tests/fixtures/sbom_sample.json`

```json
{
  "sbom": {
    "SPDXID": "SPDXRef-DOCUMENT",
    "spdxVersion": "SPDX-2.3",
    "packages": [
      {
        "SPDXID": "SPDXRef-Package-pkg:npm/lodash@4.17.21",
        "name": "npm:lodash",
        "versionInfo": "4.17.21",
        "licenseConcluded": "MIT"
      },
      {
        "SPDXID": "SPDXRef-Package-pkg:pypi/requests@2.31.0",
        "name": "pypi:requests",
        "versionInfo": "2.31.0",
        "licenseConcluded": "Apache-2.0"
      },
      {
        "SPDXID": "SPDXRef-Package-pkg:githubactions/actions/checkout@v4",
        "name": "actions:actions/checkout",
        "versionInfo": "v4"
      }
    ]
  }
}
```

- [ ] **Step 2: Write failing tests**

Path: `tests/unit/test_dependencies_loader.py`

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.dependencies import load_dependencies

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _client_with_sbom():
    fixture = json.loads((FIXTURES / "sbom_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_dependencies_writes_packages(conn) -> None:
    result = load_dependencies(
        conn, _client_with_sbom(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert result.row_count == 3
    cur = conn.execute("SELECT package_name FROM dependencies ORDER BY package_name")
    assert {r[0] for r in cur.fetchall()} == {"lodash", "requests", "actions/checkout"}


def test_load_dependencies_extracts_package_manager(conn) -> None:
    load_dependencies(
        conn, _client_with_sbom(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    cur = conn.execute(
        "SELECT package_name, package_manager FROM dependencies WHERE package_name='lodash'"
    )
    assert cur.fetchone() == ("lodash", "npm")


def test_load_dependencies_extracts_version_and_license(conn) -> None:
    load_dependencies(
        conn, _client_with_sbom(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    cur = conn.execute(
        "SELECT version, license FROM dependencies WHERE package_name='lodash'"
    )
    assert cur.fetchone() == ("4.17.21", "MIT")


def test_load_dependencies_handles_missing_license(conn) -> None:
    load_dependencies(
        conn, _client_with_sbom(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    cur = conn.execute(
        "SELECT license FROM dependencies WHERE package_name='actions/checkout'"
    )
    assert cur.fetchone()[0] is None


def test_load_dependencies_writes_snapshot(conn) -> None:
    load_dependencies(
        conn, _client_with_sbom(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='dependencies' AND repo='o/r'")
    assert cur.fetchone()[0] == 3


def test_load_dependencies_handles_empty_sbom(conn) -> None:
    client = MagicMock()
    client.get.return_value = ({"sbom": {"packages": []}}, ResponseMeta(200, 4999, None, None))
    result = load_dependencies(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert result.row_count == 0


def test_load_dependencies_handles_404_gracefully(conn) -> None:
    from repohealth_mcp.github_client import GitHubError
    client = MagicMock()
    client.get.side_effect = GitHubError(404, "no SBOM available")
    result = load_dependencies(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert result.row_count == 0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_dependencies_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/dependencies.py`**

Path: `src/repohealth_mcp/loaders/dependencies.py`

```python
"""Loader for /repos/{repo}/dependency-graph/sbom."""

from __future__ import annotations

import sqlite3

from ..github_client import GitHubError
from .base import LoaderResult, record_snapshot, upsert_rows


def _split_name(raw: str | None) -> tuple[str | None, str]:
    """Split 'manager:name' into (manager, name). Names without a manager prefix pass through."""
    if not raw:
        return None, ""
    if ":" in raw:
        manager, _, name = raw.partition(":")
        return manager, name
    return None, raw


def _shape(repo: str, pkg: dict) -> dict:
    manager, name = _split_name(pkg.get("name"))
    return {
        "repo": repo,
        "package_name": name,
        "package_manager": manager,
        "version": pkg.get("versionInfo"),
        "license": pkg.get("licenseConcluded") if pkg.get("licenseConcluded") not in ("NOASSERTION",) else None,
    }


def load_dependencies(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
) -> LoaderResult:
    try:
        body, _meta = client.get(f"/repos/{repo}/dependency-graph/sbom")
    except GitHubError as exc:
        if exc.status == 404:
            record_snapshot(conn, repo=repo, entity="dependencies",
                            range_start=range_start, range_end=range_end, row_count=0)
            return LoaderResult(entity="dependencies", row_count=0, api_calls=1)
        raise

    packages = ((body or {}).get("sbom") or {}).get("packages") or []
    rows = [_shape(repo, p) for p in packages if p.get("name")]

    upsert_rows(conn, "dependencies", rows, pk=("repo", "package_name"))
    record_snapshot(conn, repo=repo, entity="dependencies",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="dependencies", row_count=len(rows), api_calls=1)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_dependencies_loader.py -v
```
Expected: 7 pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(loaders): dependencies via SBOM endpoint"
```

---

## Task 5: Star history loader

**Notes:** `/repos/{repo}/stargazers` returns timestamped star events when the `Accept: application/vnd.github.star+json` media type is set. Existing `GitHubClient` always sends `application/vnd.github+json`; we need to pass through a custom Accept for this loader. Easiest path: extend the client with a `media_type=` kwarg.

**Files:**
- Modify: `src/repohealth_mcp/github_client.py` (accept `media_type=` on `get` and `paginate`)
- Modify: `tests/unit/test_github_client.py` (assert Accept header changes)
- Create: `src/repohealth_mcp/loaders/star_history.py`
- Create: `tests/unit/test_star_history_loader.py`

- [ ] **Step 1: Write failing tests for client media-type support**

Append to `tests/unit/test_github_client.py`:

```python
@respx.mock
def test_get_sends_custom_accept_when_media_type_set() -> None:
    client = GitHubClient(token=None)
    route = respx.get("https://api.github.com/x").mock(return_value=httpx.Response(200, json=[]))
    client.get("/x", media_type="application/vnd.github.star+json")
    assert route.calls[0].request.headers["accept"] == "application/vnd.github.star+json"


@respx.mock
def test_get_default_accept_when_media_type_unset() -> None:
    client = GitHubClient(token=None)
    route = respx.get("https://api.github.com/x").mock(return_value=httpx.Response(200, json=[]))
    client.get("/x")
    assert route.calls[0].request.headers["accept"] == "application/vnd.github+json"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_github_client.py -k "media_type" -v
```
Expected: FAIL — `get()` does not accept `media_type`.

- [ ] **Step 3: Implement `media_type=` on the client**

In `src/repohealth_mcp/github_client.py`, modify `GitHubClient.get`:

```python
def get(self, path_or_url: str, media_type: str | None = None, **params: Any) -> tuple[Any, ResponseMeta]:
    """Single GET with retries. Returns (body, meta)."""
    url = path_or_url if path_or_url.startswith("http") else f"{self._base_url}{path_or_url}"
    headers = {"Accept": media_type} if media_type else None

    for attempt, backoff in enumerate([0.0, *_RETRY_BACKOFFS]):
        if backoff:
            self._sleep(backoff)
        try:
            response = self._client.get(url, params=params or None, headers=headers)
        except httpx.RequestError as e:
            if attempt == len(_RETRY_BACKOFFS):
                raise GitHubError(0, f"network error: {e}") from e
            continue
        # ... rest unchanged
```

Modify `paginate` similarly to thread `media_type=` through to each `get` call:

```python
def paginate(
    self,
    path: str,
    max_rows: int | None = None,
    media_type: str | None = None,
    **params: Any,
) -> Iterator[dict]:
    url: str | None = path if path.startswith("http") else f"{self._base_url}{path}"
    if params:
        url = str(httpx.URL(url, params=params))
    yielded = 0
    while url is not None:
        body, meta = self.get(url, media_type=media_type)
        if not isinstance(body, list):
            raise GitHubError(0, f"expected list from paginated endpoint, got {type(body)}")
        for item in body:
            if max_rows is not None and yielded >= max_rows:
                return
            yield item
            yielded += 1
        url = meta.next_url
```

- [ ] **Step 4: Run media-type tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_github_client.py -v
```
Expected: all pass (existing + 2 new).

- [ ] **Step 5: Write failing tests for star_history loader**

Path: `tests/unit/test_star_history_loader.py`

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.star_history import load_star_history


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_load_star_history_writes_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([
        {"starred_at": "2026-04-01T00:00:00Z", "user": {"login": "a"}},
        {"starred_at": "2026-04-15T00:00:00Z", "user": {"login": "b"}},
        {"starred_at": "2025-12-31T00:00:00Z", "user": {"login": "c"}},
    ])
    result = load_star_history(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    # 2 in range (the 2026-04-* ones); the 2025-12-31 one is filtered out.
    assert result.row_count == 2


def test_load_star_history_uses_star_media_type(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    load_star_history(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    call_kwargs = client.paginate.call_args.kwargs
    assert call_kwargs.get("media_type") == "application/vnd.github.star+json"


def test_load_star_history_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([
        {"starred_at": f"2026-04-{i:02d}T00:00:00Z", "user": {"login": f"u{i}"}}
        for i in range(1, 11)
    ])
    result = load_star_history(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=5,
    )
    assert result.row_count == 5
```

- [ ] **Step 6: Run to verify failure**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_star_history_loader.py -v
```
Expected: ImportError.

- [ ] **Step 7: Implement `loaders/star_history.py`**

Path: `src/repohealth_mcp/loaders/star_history.py`

```python
"""Loader for /repos/{repo}/stargazers with star+json media type for timestamps."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows

_MEDIA = "application/vnd.github.star+json"


def _shape(repo: str, item: dict) -> dict | None:
    starred_at = item.get("starred_at")
    user = (item.get("user") or {}).get("login")
    if not starred_at or not user:
        return None
    return {"repo": repo, "starred_at": starred_at, "user": user}


def load_star_history(
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
        f"/repos/{repo}/stargazers", per_page=100, media_type=_MEDIA,
    ):
        if not date_in_range(item.get("starred_at"), range_start, range_end):
            continue
        row = _shape(repo, item)
        if row is None:
            continue
        rows.append(row)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "star_history", rows, pk=("repo", "starred_at", "user"))
    record_snapshot(conn, repo=repo, entity="star_history",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="star_history", row_count=len(rows),
                        api_calls=max(1, len(rows) // 100 + 1))
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_star_history_loader.py tests/unit/test_github_client.py -v
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(loaders): star_history via stargazers + custom Accept media-type"
```

---

## Task 6: Workflow runs (CI health) loader

**Files:**
- Create: `src/repohealth_mcp/loaders/workflow_runs.py`
- Create: `tests/fixtures/workflow_runs_sample.json`
- Create: `tests/unit/test_workflow_runs_loader.py`

- [ ] **Step 1: Create fixture**

Path: `tests/fixtures/workflow_runs_sample.json`

```json
[
  {
    "id": 1001,
    "name": "ci",
    "head_branch": "main",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "created_at": "2026-04-10T10:00:00Z",
    "run_started_at": "2026-04-10T10:00:05Z",
    "updated_at": "2026-04-10T10:03:30Z"
  },
  {
    "id": 1002,
    "name": "ci",
    "head_branch": "feat/x",
    "event": "pull_request",
    "status": "completed",
    "conclusion": "failure",
    "created_at": "2026-04-11T08:00:00Z",
    "run_started_at": "2026-04-11T08:00:02Z",
    "updated_at": "2026-04-11T08:05:00Z"
  },
  {
    "id": 1003,
    "name": "lint",
    "head_branch": "main",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "created_at": "2024-01-01T00:00:00Z",
    "run_started_at": "2024-01-01T00:00:05Z",
    "updated_at": "2024-01-01T00:01:00Z"
  }
]
```

- [ ] **Step 2: Write failing tests**

Path: `tests/unit/test_workflow_runs_loader.py`

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.workflow_runs import load_workflow_runs

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _client_with_workflow_runs():
    fixture = json.loads((FIXTURES / "workflow_runs_sample.json").read_text())
    # /actions/runs returns {"workflow_runs": [...]}, paginated as a top-level dict.
    # GitHubClient.paginate expects a list, so workflow_runs loader will use client.get.
    client = MagicMock()
    client.get.return_value = ({"workflow_runs": fixture, "total_count": len(fixture)},
                                ResponseMeta(200, 4999, None, None))
    return client


def test_load_workflow_runs_writes_in_range(conn) -> None:
    result = load_workflow_runs(
        conn, _client_with_workflow_runs(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 2  # the 2024 entry is filtered out


def test_load_workflow_runs_computes_duration_seconds(conn) -> None:
    load_workflow_runs(
        conn, _client_with_workflow_runs(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT duration_seconds FROM workflow_runs WHERE id=1001")
    # 10:00:05 → 10:03:30 = 205 seconds
    assert cur.fetchone()[0] == 205


def test_load_workflow_runs_records_conclusion(conn) -> None:
    load_workflow_runs(
        conn, _client_with_workflow_runs(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT conclusion FROM workflow_runs WHERE id=1002")
    assert cur.fetchone()[0] == "failure"


def test_load_workflow_runs_writes_snapshot(conn) -> None:
    load_workflow_runs(
        conn, _client_with_workflow_runs(), repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='workflow_runs' AND repo='o/r'")
    assert cur.fetchone()[0] == 2
```

- [ ] **Step 3: Run to verify failure**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_workflow_runs_loader.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `loaders/workflow_runs.py`**

Path: `src/repohealth_mcp/loaders/workflow_runs.py`

```python
"""Loader for /repos/{repo}/actions/runs (CI / GitHub Actions runs)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(started: str | None, ended: str | None) -> int | None:
    s, e = _parse_iso(started), _parse_iso(ended)
    if s is None or e is None:
        return None
    delta = (e - s).total_seconds()
    return int(delta) if delta >= 0 else None


def _shape(repo: str, item: dict) -> dict:
    return {
        "repo": repo,
        "id": item["id"],
        "workflow_name": item.get("name"),
        "head_branch": item.get("head_branch"),
        "event": item.get("event"),
        "status": item.get("status"),
        "conclusion": item.get("conclusion"),
        "created_at": item.get("created_at"),
        "run_started_at": item.get("run_started_at"),
        "duration_seconds": _duration_seconds(item.get("run_started_at"), item.get("updated_at")),
    }


def load_workflow_runs(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    rows: list[dict] = []
    api_calls = 0
    page = 1
    while len(rows) < max_rows:
        body, _meta = client.get(
            f"/repos/{repo}/actions/runs",
            per_page=100,
            page=page,
            created=f">={range_start}",
        )
        api_calls += 1
        runs = (body or {}).get("workflow_runs") or []
        if not runs:
            break
        for item in runs:
            if not date_in_range(item.get("created_at"), range_start, range_end):
                continue
            rows.append(_shape(repo, item))
            if len(rows) >= max_rows:
                break
        if len(runs) < 100:
            break
        page += 1

    upsert_rows(conn, "workflow_runs", rows, pk=("repo", "id"))
    record_snapshot(conn, repo=repo, entity="workflow_runs",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="workflow_runs", row_count=len(rows), api_calls=api_calls)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_workflow_runs_loader.py -v
```
Expected: 4 pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(loaders): workflow_runs — CI health from /actions/runs"
```

---

## Task 7: Per-commit file diffs loader

**Notes:** Second hop on `/repos/{repo}/commits/{sha}` for each commit already cached in the `commits` table. Returns `{files: [{filename, additions, deletions, changes, status, ...}, ...]}`. N+1 on commits — concurrent fetch via ThreadPoolExecutor, identical pattern to `pr_reviews`. **Opt-in** entity.

**Files:**
- Create: `src/repohealth_mcp/loaders/commit_files.py`
- Create: `tests/unit/test_commit_files_loader.py`

- [ ] **Step 1: Write failing tests**

Path: `tests/unit/test_commit_files_loader.py`

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.commit_files import load_commit_files


@pytest.fixture
def conn_with_commits(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    c.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "abc111", "alice", "a@x", "2026-04-10T10:00:00Z", "feat"),
    )
    c.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "abc222", "bot", "b@x", "2026-04-12T10:00:00Z", "chore"),
    )
    return c


def test_load_commit_files_writes_one_row_per_changed_file(conn_with_commits) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r/commits/abc111":
            return ({"files": [
                {"filename": "src/a.py", "status": "modified",
                 "additions": 10, "deletions": 2, "changes": 12},
                {"filename": "tests/test_a.py", "status": "added",
                 "additions": 50, "deletions": 0, "changes": 50},
            ]}, ResponseMeta(200, 4999, None, None))
        if url == "/repos/o/r/commits/abc222":
            return ({"files": [
                {"filename": "pyproject.toml", "status": "modified",
                 "additions": 1, "deletions": 1, "changes": 2},
            ]}, ResponseMeta(200, 4999, None, None))
        return ({"files": []}, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    result = load_commit_files(
        conn_with_commits, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_commits.execute(
        "SELECT sha, filename, additions FROM commit_files ORDER BY sha, filename"
    )
    rows = cur.fetchall()
    assert rows == [
        ("abc111", "src/a.py", 10),
        ("abc111", "tests/test_a.py", 50),
        ("abc222", "pyproject.toml", 1),
    ]


def test_load_commit_files_skips_when_no_commits_cached(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_commit_files(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0
    assert client.get.call_count == 0


def test_load_commit_files_handles_commit_with_no_files(conn_with_commits) -> None:
    client = MagicMock()
    client.get.return_value = ({"files": []}, ResponseMeta(200, 4999, None, None))
    result = load_commit_files(
        conn_with_commits, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0


def test_load_commit_files_respects_max_rows(conn_with_commits) -> None:
    client = MagicMock()
    client.get.return_value = ({"files": [
        {"filename": f"f{i}.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1}
        for i in range(20)
    ]}, ResponseMeta(200, 4999, None, None))
    result = load_commit_files(
        conn_with_commits, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=10,
    )
    assert result.row_count == 10
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commit_files_loader.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `loaders/commit_files.py`**

Path: `src/repohealth_mcp/loaders/commit_files.py`

```python
"""Loader for /repos/{repo}/commits/{sha} (per-commit file diffs).

Opt-in: include "commit_files" in entities. Requires the `commits` table to be populated
first — it enumerates cached commits and fans out one request per sha concurrently.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import LoaderResult, record_snapshot, upsert_rows

_MAX_WORKERS = 8


def _shape(repo: str, sha: str, file: dict) -> dict:
    return {
        "repo": repo,
        "sha": sha,
        "filename": file.get("filename", ""),
        "status": file.get("status"),
        "additions": file.get("additions"),
        "deletions": file.get("deletions"),
        "changes": file.get("changes"),
    }


def _list_target_shas(conn: sqlite3.Connection, repo: str, range_start: str, range_end: str) -> list[str]:
    cur = conn.execute(
        "SELECT sha FROM commits WHERE repo=? AND committed_at >= ? AND committed_at <= ?",
        (repo, f"{range_start}T00:00:00Z", f"{range_end}T23:59:59Z"),
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_files_for_commit(client, repo: str, sha: str) -> list[dict]:
    body, _ = client.get(f"/repos/{repo}/commits/{sha}")
    files = (body or {}).get("files") or []
    return [_shape(repo, sha, f) for f in files if f.get("filename")]


def load_commit_files(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    shas = _list_target_shas(conn, repo, range_start, range_end)
    if not shas:
        record_snapshot(conn, repo=repo, entity="commit_files",
                        range_start=range_start, range_end=range_end, row_count=0)
        return LoaderResult(entity="commit_files", row_count=0, api_calls=0)

    rows: list[dict] = []
    api_calls = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(shas))) as ex:
        futures = {ex.submit(_fetch_files_for_commit, client, repo, s): s for s in shas}
        for fut in as_completed(futures):
            api_calls += 1
            if len(rows) >= max_rows:
                continue
            rows.extend(fut.result())
            rows = rows[:max_rows]

    upsert_rows(conn, "commit_files", rows, pk=("repo", "sha", "filename"))
    record_snapshot(conn, repo=repo, entity="commit_files",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="commit_files", row_count=len(rows), api_calls=api_calls)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_commit_files_loader.py -v
```
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(loaders): commit_files — per-commit file diffs (opt-in, N+1 on commits)"
```

---

## Task 8: PR review comments loader

**Notes:** Mirror of Task 3 (pr_reviews) for inline review comments. Endpoint `/repos/{repo}/pulls/{number}/comments` returns review comments with `path`, `line`, `position`, `body`. N+1 on PRs, concurrent fetch. **Opt-in.**

**Files:**
- Create: `src/repohealth_mcp/loaders/pr_review_comments.py`
- Create: `tests/unit/test_pr_review_comments_loader.py`

- [ ] **Step 1: Write failing tests**

Path: `tests/unit/test_pr_review_comments_loader.py`

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.pr_review_comments import load_pr_review_comments


@pytest.fixture
def conn_with_prs(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    c.execute("INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)",
              ("o/r", 1, "2026-04-01T00:00:00Z"))
    c.execute("INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)",
              ("o/r", 2, "2026-04-15T00:00:00Z"))
    return c


def test_load_pr_review_comments_writes_rows_per_pr(conn_with_prs) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r/pulls/1/comments":
            return ([
                {"id": 100, "user": {"login": "alice"}, "body": "nit",
                 "path": "src/a.py", "line": 42, "position": 5,
                 "created_at": "2026-04-02T10:00:00Z"},
                {"id": 101, "user": {"login": "bob"}, "body": "lgtm",
                 "path": "src/a.py", "line": 100, "position": 30,
                 "created_at": "2026-04-02T11:00:00Z"},
            ], ResponseMeta(200, 4999, None, None))
        if url == "/repos/o/r/pulls/2/comments":
            return ([
                {"id": 200, "user": {"login": "alice"}, "body": "consider X",
                 "path": "README.md", "line": 3, "position": 1,
                 "created_at": "2026-04-16T09:00:00Z"},
            ], ResponseMeta(200, 4999, None, None))
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    result = load_pr_review_comments(
        conn_with_prs, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_prs.execute(
        "SELECT pr_number, reviewer, path, line FROM pr_review_comments "
        "ORDER BY pr_number, id"
    )
    assert cur.fetchall() == [
        (1, "alice", "src/a.py", 42),
        (1, "bob", "src/a.py", 100),
        (2, "alice", "README.md", 3),
    ]


def test_load_pr_review_comments_skips_when_no_prs(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_pr_review_comments(
        conn, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0
    assert client.get.call_count == 0


def test_load_pr_review_comments_handles_pr_with_no_comments(conn_with_prs) -> None:
    client = MagicMock()
    client.get.return_value = ([], ResponseMeta(200, 4999, None, None))
    result = load_pr_review_comments(
        conn_with_prs, client, repo="o/r",
        range_start="2026-01-01", range_end="2026-06-01", max_rows=500,
    )
    assert result.row_count == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_pr_review_comments_loader.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `loaders/pr_review_comments.py`**

Path: `src/repohealth_mcp/loaders/pr_review_comments.py`

```python
"""Loader for /repos/{repo}/pulls/{number}/comments (inline review comments).

Opt-in: include "pr_review_comments" in entities. N+1 on cached PRs.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import LoaderResult, record_snapshot, upsert_rows

_MAX_WORKERS = 8


def _shape(repo: str, pr_number: int, c: dict) -> dict:
    return {
        "repo": repo,
        "pr_number": pr_number,
        "id": c["id"],
        "reviewer": (c.get("user") or {}).get("login"),
        "body": c.get("body"),
        "path": c.get("path"),
        "line": c.get("line"),
        "position": c.get("position"),
        "created_at": c.get("created_at"),
    }


def _list_target_prs(conn: sqlite3.Connection, repo: str, range_start: str, range_end: str) -> list[int]:
    cur = conn.execute(
        "SELECT number FROM prs WHERE repo=? AND created_at >= ? AND created_at <= ?",
        (repo, f"{range_start}T00:00:00Z", f"{range_end}T23:59:59Z"),
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_comments_for_pr(client, repo: str, pr_number: int) -> list[dict]:
    body, _ = client.get(f"/repos/{repo}/pulls/{pr_number}/comments")
    if not isinstance(body, list):
        return []
    return [_shape(repo, pr_number, c) for c in body]


def load_pr_review_comments(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    pr_numbers = _list_target_prs(conn, repo, range_start, range_end)
    if not pr_numbers:
        record_snapshot(conn, repo=repo, entity="pr_review_comments",
                        range_start=range_start, range_end=range_end, row_count=0)
        return LoaderResult(entity="pr_review_comments", row_count=0, api_calls=0)

    rows: list[dict] = []
    api_calls = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(pr_numbers))) as ex:
        futures = {ex.submit(_fetch_comments_for_pr, client, repo, n): n for n in pr_numbers}
        for fut in as_completed(futures):
            api_calls += 1
            if len(rows) >= max_rows:
                continue
            rows.extend(fut.result())
            rows = rows[:max_rows]

    upsert_rows(conn, "pr_review_comments", rows, pk=("repo", "pr_number", "id"))
    record_snapshot(conn, repo=repo, entity="pr_review_comments",
                    range_start=range_start, range_end=range_end, row_count=len(rows))
    return LoaderResult(entity="pr_review_comments", row_count=len(rows), api_calls=api_calls)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_pr_review_comments_loader.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(loaders): pr_review_comments — inline PR comments (opt-in, N+1 on PRs)"
```

---

## Task 9: Funding signal (FUNDING.yml + sponsors) in repo_meta

**Notes:** Endpoint is `/repos/{repo}/contents/.github/FUNDING.yml` — returns base64-encoded content if the file exists, 404 if not. Parse with the existing `pyyaml` dep. Populate the `funding_json` and `has_sponsors` columns added in Task 1.

**Files:**
- Modify: `src/repohealth_mcp/loaders/repo_meta.py` (add a FUNDING.yml fetch)
- Modify: `tests/unit/test_repo_meta_loader.py` (add tests for funding fields)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_repo_meta_loader.py`:

```python
import base64

def test_load_repo_meta_extracts_funding_when_present(conn) -> None:
    client = MagicMock()
    funding_yaml = "github: [octocat]\npatreon: octocat\n"
    funding_b64 = base64.b64encode(funding_yaml.encode()).decode()

    def _get(url, **_):
        if url == "/repos/o/r":
            return ({"full_name": "o/r", "description": None, "default_branch": "main",
                     "stargazers_count": 1, "forks_count": 0, "open_issues_count": 0,
                     "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-01-01T00:00:00Z",
                     "archived": False, "disabled": False, "license": {"spdx_id": "MIT"}},
                    ResponseMeta(200, 4999, None, None))
        if url == "/repos/o/r/contents/.github/FUNDING.yml":
            return ({"encoding": "base64", "content": funding_b64},
                    ResponseMeta(200, 4999, None, None))
        return (None, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT funding_json, has_sponsors FROM repos WHERE repo='o/r'")
    funding_json, has_sponsors = cur.fetchone()
    parsed = json.loads(funding_json)
    assert parsed.get("github") == ["octocat"]
    assert parsed.get("patreon") == "octocat"
    assert has_sponsors == 1


def test_load_repo_meta_handles_missing_funding(conn) -> None:
    client = MagicMock()
    from repohealth_mcp.github_client import GitHubError

    def _get(url, **_):
        if url == "/repos/o/r":
            return ({"full_name": "o/r", "description": None, "default_branch": "main",
                     "stargazers_count": 1, "forks_count": 0, "open_issues_count": 0,
                     "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-01-01T00:00:00Z",
                     "archived": False, "disabled": False, "license": None},
                    ResponseMeta(200, 4999, None, None))
        if url == "/repos/o/r/contents/.github/FUNDING.yml":
            raise GitHubError(404, "Not Found")
        return (None, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT funding_json, has_sponsors FROM repos WHERE repo='o/r'")
    funding_json, has_sponsors = cur.fetchone()
    assert funding_json is None
    assert has_sponsors == 0
```

Make sure `import json` and `from unittest.mock import MagicMock` are at top of the file (probably already are).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_repo_meta_loader.py -v
```
Expected: 2 new failures (existing tests still pass).

- [ ] **Step 3: Implement funding fetch in `loaders/repo_meta.py`**

Add to `loaders/repo_meta.py` (alongside existing logic):

```python
import base64
import json

import yaml

from ..github_client import GitHubError

GITHUB_SPONSOR_KEYS = {"github"}


def _fetch_funding(client, repo: str) -> tuple[str | None, int]:
    """Returns (funding_json, has_sponsors). Returns (None, 0) on 404."""
    try:
        body, _ = client.get(f"/repos/{repo}/contents/.github/FUNDING.yml")
    except GitHubError as exc:
        if exc.status == 404:
            return None, 0
        return None, 0
    if not isinstance(body, dict) or body.get("encoding") != "base64":
        return None, 0
    try:
        raw = base64.b64decode(body.get("content", "")).decode()
        parsed = yaml.safe_load(raw) or {}
    except Exception:
        return None, 0
    if not isinstance(parsed, dict):
        return None, 0
    has_sponsors = 1 if any(k in parsed and parsed[k] for k in GITHUB_SPONSOR_KEYS) else 0
    return json.dumps(parsed), has_sponsors
```

Then modify the existing `load_repo_meta` to call `_fetch_funding` and include the columns in the row dict. The exact UPSERT in `load_repo_meta` already inserts into `repos` — make sure the row dict now includes `funding_json` and `has_sponsors`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_repo_meta_loader.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(loaders): funding signal (FUNDING.yml) on repos table"
```

---

## Task 10: Freshness tracking in `check_coverage`

**Notes:** Today `check_coverage` returns `{cached: bool, cached_at, rows}`. Add an `age_seconds` field (int or None) and a `stale` flag based on a configurable threshold. Default threshold: 7 days (604800 s).

**Files:**
- Modify: `src/repohealth_mcp/coverage.py` (add age_seconds, stale)
- Modify: `src/repohealth_mcp/tools/introspection.py` (surface the new fields)
- Modify: `tests/unit/test_introspection.py` (assert new fields)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_introspection.py`:

```python
def test_check_coverage_includes_age_seconds_when_cached(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)
    # Pretend snapshot was cached 1 hour ago.
    from datetime import datetime, timedelta, timezone
    cached_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "prs", "2026-01-01", "2026-06-01", cached_at, 42),
    )
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r", entity="prs",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert out["cached"] is True
    assert 3500 < out["age_seconds"] < 3700  # ~1h
    assert out["stale"] is False


def test_check_coverage_marks_stale_after_threshold(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)
    from datetime import datetime, timedelta, timezone
    cached_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "prs", "2026-01-01", "2026-06-01", cached_at, 42),
    )
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r", entity="prs",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert out["stale"] is True


def test_check_coverage_returns_age_none_on_miss(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r", entity="prs",
        range_start="2026-01-01", range_end="2026-06-01",
    )
    assert out["cached"] is False
    assert out["age_seconds"] is None
    assert out["stale"] is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_introspection.py -v
```
Expected: 3 new failures.

- [ ] **Step 3: Implement freshness in `coverage.py` and `introspection.py`**

In `src/repohealth_mcp/coverage.py`, extend `CoverageStatus` and `check_coverage`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

STALE_AFTER_SECONDS = 7 * 24 * 60 * 60  # 7 days


@dataclass
class CoverageStatus:
    cached: bool
    cached_at: str | None
    rows: int
    age_seconds: int | None
    stale: bool


def check_coverage(conn, *, repo, entity, range_start, range_end) -> CoverageStatus:
    cur = conn.execute(
        "SELECT cached_at, row_count FROM snapshots "
        "WHERE repo=? AND entity=? AND range_start=? AND range_end=?",
        (repo, entity, range_start, range_end),
    )
    row = cur.fetchone()
    if not row:
        return CoverageStatus(cached=False, cached_at=None, rows=0,
                              age_seconds=None, stale=False)
    cached_at, rows = row
    age = None
    stale = False
    try:
        ts = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        age = int((datetime.now(timezone.utc) - ts).total_seconds())
        stale = age > STALE_AFTER_SECONDS
    except (ValueError, AttributeError):
        pass
    return CoverageStatus(cached=True, cached_at=cached_at, rows=rows,
                          age_seconds=age, stale=stale)
```

In `src/repohealth_mcp/tools/introspection.py`, update `check_coverage_tool` to surface the new fields:

```python
def check_coverage_tool(
    db_path: Path | str, *, repo: str, entity: str, range_start: str, range_end: str,
) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        status = check_coverage(conn, repo=repo, entity=entity,
                                range_start=range_start, range_end=range_end)
        return {
            "cached": status.cached,
            "cached_at": status.cached_at,
            "rows": status.rows,
            "age_seconds": status.age_seconds,
            "stale": status.stale,
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_introspection.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(coverage): freshness tracking — age_seconds + stale flag"
```

---

## Task 11: Wire new entities into load_repo

**Files:**
- Modify: `src/repohealth_mcp/tools/load_repo.py` (add new entity names to `VALID_ENTITIES`, extend `_dispatch`)
- Modify: `tests/unit/test_load_repo.py` (assert new entities loadable)

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_load_repo.py`:

```python
def test_load_repo_loads_v2_entities(tmp_path) -> None:
    """v2 entities (commits, dependencies, star_history, workflow_runs) must be loadable."""
    from repohealth_mcp.github_client import ResponseMeta
    conn = connect(tmp_path / "v2.sqlite")
    init_schema(conn)
    client = MagicMock()

    repo_meta_body = {
        "full_name": "o/r", "description": None, "default_branch": "main",
        "stargazers_count": 1, "forks_count": 0, "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z", "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False, "disabled": False, "license": None,
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            from repohealth_mcp.github_client import GitHubError
            raise GitHubError(404, "no funding")
        if "actions/runs" in url:
            return ({"workflow_runs": []}, ResponseMeta(200, 4999, None, None))
        if "dependency-graph" in url:
            return ({"sbom": {"packages": []}}, ResponseMeta(200, 4999, None, None))
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])

    result = load_repo(
        conn, client, repo="o/r",
        entities=["commits", "dependencies", "star_history", "workflow_runs"],
        range_spec="6mo", max_rows_per_entity=500,
        now=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )
    assert set(result["fetched"].keys()) == {
        "commits", "dependencies", "star_history", "workflow_runs",
    }
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_load_repo.py::test_load_repo_loads_v2_entities -v
```
Expected: ValueError "unknown entity".

- [ ] **Step 3: Extend `VALID_ENTITIES` and `_dispatch`**

In `src/repohealth_mcp/tools/load_repo.py`:

```python
from ..loaders.commit_files import load_commit_files
from ..loaders.commits import load_commits
from ..loaders.dependencies import load_dependencies
from ..loaders.pr_review_comments import load_pr_review_comments
from ..loaders.pr_reviews import load_pr_reviews
from ..loaders.star_history import load_star_history
from ..loaders.workflow_runs import load_workflow_runs

VALID_ENTITIES = (
    "prs", "issues", "releases", "commit_activity", "contributors",
    "commits", "commit_files",
    "pr_reviews", "pr_review_comments",
    "dependencies", "star_history", "workflow_runs",
)
```

Extend `_dispatch` with the new branches (each follows the pattern of existing branches):

```python
    if entity == "commits":
        return load_commits(conn, client, repo=repo, range_start=range_start,
                            range_end=range_end, max_rows=max_rows)
    if entity == "commit_files":
        return load_commit_files(conn, client, repo=repo, range_start=range_start,
                                 range_end=range_end, max_rows=max_rows)
    if entity == "pr_reviews":
        return load_pr_reviews(conn, client, repo=repo, range_start=range_start,
                               range_end=range_end, max_rows=max_rows)
    if entity == "pr_review_comments":
        return load_pr_review_comments(conn, client, repo=repo, range_start=range_start,
                                       range_end=range_end, max_rows=max_rows)
    if entity == "dependencies":
        return load_dependencies(conn, client, repo=repo,
                                 range_start=range_start, range_end=range_end)
    if entity == "star_history":
        return load_star_history(conn, client, repo=repo, range_start=range_start,
                                 range_end=range_end, max_rows=max_rows)
    if entity == "workflow_runs":
        return load_workflow_runs(conn, client, repo=repo, range_start=range_start,
                                  range_end=range_end, max_rows=max_rows)
```

Also update the default-entity behavior in `server.py`'s `load_repo` wrapper: it currently defaults `entities` to `VALID_ENTITIES`. With v2, expanding the default would make every call N+1 due to `pr_reviews`. Keep the default to the v1 set:

```python
DEFAULT_ENTITIES = ("prs", "issues", "releases", "commit_activity", "contributors")
```

Wire `DEFAULT_ENTITIES` through the server wrappers instead of `VALID_ENTITIES`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_load_repo.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(orchestrator): wire v2 entities into load_repo (opt-in for pr_reviews)"
```

---

## Task 12: Update `repo://signals` resource with v2 SQL recipes

**Files:**
- Modify: `src/repohealth_mcp/server.py` (extend `get_signals_resource`)
- Modify: `tests/unit/test_resources.py` (assert new recipes present)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_resources.py`:

```python
def test_signals_resource_includes_v2_recipes() -> None:
    body = get_signals_resource()
    for recipe in (
        "commits_by_author_90d",
        "ci_pass_rate_90d",
        "stars_growth_curve",
        "dependency_license_breakdown",
        "review_responsiveness",
        "file_hotspots_90d",
        "review_comment_volume",
    ):
        assert recipe in body, f"missing recipe: {recipe}"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_resources.py -v
```
Expected: failure on missing recipes.

- [ ] **Step 3: Append v2 recipes to `get_signals_resource`**

In `src/repohealth_mcp/server.py`, append to the multi-line return string (before the closing `"""`):

```markdown

## commits_by_author_90d

```sql
SELECT repo, author, COUNT(*) AS commit_count
FROM commits
WHERE committed_at > date('now', '-90 days')
GROUP BY repo, author
ORDER BY commit_count DESC;
```

## ci_pass_rate_90d

```sql
SELECT repo,
       SUM(CASE WHEN conclusion='success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pass_pct,
       median(duration_seconds) AS median_duration_s,
       COUNT(*) AS run_count
FROM workflow_runs
WHERE created_at > date('now', '-90 days')
GROUP BY repo;
```

## stars_growth_curve

```sql
SELECT repo, date(starred_at) AS day, COUNT(*) AS stars_that_day
FROM star_history
GROUP BY repo, date(starred_at)
ORDER BY day;
```

## dependency_license_breakdown

```sql
SELECT repo, package_manager, license, COUNT(*) AS pkg_count
FROM dependencies
GROUP BY repo, package_manager, license
ORDER BY pkg_count DESC;
```

## review_responsiveness

```sql
WITH first_review AS (
  SELECT repo, pr_number, MIN(submitted_at) AS first_review_at
  FROM pr_reviews
  GROUP BY repo, pr_number
)
SELECT prs.repo,
       median(julianday(fr.first_review_at) - julianday(prs.created_at)) AS median_hours_to_first_review
FROM prs
JOIN first_review fr ON fr.repo = prs.repo AND fr.pr_number = prs.number
GROUP BY prs.repo;
```

## file_hotspots_90d

```sql
SELECT cf.repo, cf.filename,
       COUNT(*) AS touch_count,
       SUM(cf.changes) AS total_changes
FROM commit_files cf
JOIN commits c ON c.repo = cf.repo AND c.sha = cf.sha
WHERE c.committed_at > date('now', '-90 days')
GROUP BY cf.repo, cf.filename
ORDER BY touch_count DESC
LIMIT 25;
```

## review_comment_volume

```sql
SELECT repo,
       COUNT(*)                            AS total_comments,
       COUNT(DISTINCT reviewer)            AS distinct_reviewers,
       median(comments_per_pr.cnt)         AS median_comments_per_pr
FROM (SELECT repo, pr_number, COUNT(*) AS cnt
      FROM pr_review_comments GROUP BY repo, pr_number) comments_per_pr
JOIN pr_review_comments USING (repo, pr_number)
GROUP BY repo;
```
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_resources.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(resources): v2 signal recipes (commits, ci, stars, deps, reviews)"
```

---

## Task 13: New SQL prompt scaffolds for v2 signals

**Files:**
- Modify: `src/repohealth_mcp/server.py` (add five new `@mcp.prompt()` functions)
- Modify: `tests/unit/test_prompts.py` (assert new prompts return non-empty SQL referencing the right tables)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_prompts.py`:

```python
def test_commit_history_query_references_commits_table() -> None:
    body = commit_history_query("o/r")
    assert "commits" in body
    assert "o/r" in body

def test_ci_health_query_references_workflow_runs() -> None:
    body = ci_health_query("o/r")
    assert "workflow_runs" in body

def test_dep_audit_query_references_dependencies() -> None:
    body = dep_audit_query("o/r")
    assert "dependencies" in body

def test_star_trajectory_query_references_star_history() -> None:
    body = star_trajectory_query("o/r")
    assert "star_history" in body

def test_review_responsiveness_query_references_pr_reviews() -> None:
    body = review_responsiveness_query("o/r")
    assert "pr_reviews" in body

def test_file_hotspots_query_references_commit_files() -> None:
    body = file_hotspots_query("o/r")
    assert "commit_files" in body

def test_review_comment_volume_query_references_pr_review_comments() -> None:
    body = review_comment_volume_query("o/r")
    assert "pr_review_comments" in body
```

Make sure imports at the top of the test file include each new function from `repohealth_mcp.server`.

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prompts.py -v
```
Expected: ImportError on the new prompt names.

- [ ] **Step 3: Add the five prompt scaffolds**

Append to `src/repohealth_mcp/server.py` (after the existing `@mcp.prompt()` definitions):

```python
@mcp.prompt()
def commit_history_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
Commit activity over 90 days for {repo}:

```sql
SELECT author, COUNT(*) AS commits
FROM commits
WHERE repo={repo_sql} AND committed_at > date('now','-90 days')
GROUP BY author
ORDER BY commits DESC
LIMIT 20;
```
"""


@mcp.prompt()
def ci_health_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
CI / workflow_runs health for {repo}:

```sql
SELECT workflow_name,
       SUM(CASE WHEN conclusion='success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pass_pct,
       median(duration_seconds) AS median_duration_s,
       COUNT(*) AS runs
FROM workflow_runs
WHERE repo={repo_sql} AND created_at > date('now','-90 days')
GROUP BY workflow_name
ORDER BY runs DESC;
```
"""


@mcp.prompt()
def dep_audit_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
Dependency audit for {repo}:

```sql
SELECT package_manager, license, COUNT(*) AS pkg_count
FROM dependencies
WHERE repo={repo_sql}
GROUP BY package_manager, license
ORDER BY pkg_count DESC;
```
"""


@mcp.prompt()
def star_trajectory_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
Star-growth trajectory for {repo} (last 12 months, weekly buckets):

```sql
SELECT strftime('%Y-W%W', starred_at) AS week, COUNT(*) AS stars_added
FROM star_history
WHERE repo={repo_sql} AND starred_at > date('now','-365 days')
GROUP BY week
ORDER BY week;
```
"""


@mcp.prompt()
def review_responsiveness_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
Median time-to-first-review for {repo}:

```sql
WITH first_review AS (
  SELECT pr_number, MIN(submitted_at) AS first_review_at
  FROM pr_reviews
  WHERE repo={repo_sql}
  GROUP BY pr_number
)
SELECT median(julianday(fr.first_review_at) - julianday(prs.created_at)) * 24
         AS median_hours_to_first_review,
       COUNT(*) AS reviewed_prs
FROM prs
JOIN first_review fr ON fr.pr_number = prs.number
WHERE prs.repo={repo_sql};
```
"""


@mcp.prompt()
def file_hotspots_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
File hotspots (most-touched files in the last 90 days) for {repo}:

```sql
SELECT cf.filename, COUNT(*) AS touch_count, SUM(cf.changes) AS total_changes
FROM commit_files cf
JOIN commits c ON c.repo = cf.repo AND c.sha = cf.sha
WHERE cf.repo={repo_sql} AND c.committed_at > date('now','-90 days')
GROUP BY cf.filename
ORDER BY touch_count DESC
LIMIT 25;
```
"""


@mcp.prompt()
def review_comment_volume_query(repo: str) -> str:
    repo_sql = _sql_literal(repo)
    return f"""\
Review-comment intensity for {repo} (signal for how hands-on review is):

```sql
WITH per_pr AS (
  SELECT pr_number, COUNT(*) AS comments
  FROM pr_review_comments
  WHERE repo={repo_sql}
  GROUP BY pr_number
)
SELECT COUNT(*)                     AS prs_with_review_comments,
       COUNT(DISTINCT reviewer)     AS distinct_reviewers,
       median(comments)             AS median_comments_per_pr,
       MAX(comments)                AS max_comments_on_one_pr
FROM per_pr
JOIN pr_review_comments USING (pr_number)
WHERE pr_review_comments.repo={repo_sql};
```
"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest tests/unit/test_prompts.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(prompts): v2 SQL scaffolds (commits, CI, deps, stars, reviews)"
```

---

## Task 14: Integration tests for v2 loaders against real GitHub

**Files:**
- Modify: `tests/integration/test_real_github.py` (add `@pytest.mark.integration` tests for each new loader)

- [ ] **Step 1: Add integration tests**

Append to `tests/integration/test_real_github.py`:

```python
def test_real_commits(conn, client):
    from repohealth_mcp.loaders.commits import load_commits
    result = load_commits(
        conn, client, repo=REPO,
        range_start="2010-01-01", range_end="2026-12-31", max_rows=10,
    )
    assert result.row_count >= 1


def test_real_dependencies(conn, client):
    from repohealth_mcp.loaders.dependencies import load_dependencies
    # Hello-World has no SBOM — must complete with row_count=0, not raise.
    result = load_dependencies(
        conn, client, repo=REPO,
        range_start="2010-01-01", range_end="2026-12-31",
    )
    assert result.row_count >= 0


def test_real_star_history(conn, client):
    from repohealth_mcp.loaders.star_history import load_star_history
    result = load_star_history(
        conn, client, repo=REPO,
        range_start="2010-01-01", range_end="2026-12-31", max_rows=5,
    )
    assert result.row_count >= 1


def test_real_workflow_runs(conn, client):
    from repohealth_mcp.loaders.workflow_runs import load_workflow_runs
    # Hello-World has no Actions — must return 0, not raise.
    result = load_workflow_runs(
        conn, client, repo=REPO,
        range_start="2024-01-01", range_end="2026-12-31", max_rows=5,
    )
    assert result.row_count >= 0


def test_real_commit_files(conn, client):
    from repohealth_mcp.loaders.commits import load_commits
    from repohealth_mcp.loaders.commit_files import load_commit_files
    load_commits(conn, client, repo=REPO,
                 range_start="2010-01-01", range_end="2026-12-31", max_rows=3)
    result = load_commit_files(
        conn, client, repo=REPO,
        range_start="2010-01-01", range_end="2026-12-31", max_rows=20,
    )
    # Hello-World has at least one commit with a README file change.
    assert result.row_count >= 1


def test_real_pr_review_comments(conn, client):
    from repohealth_mcp.loaders.prs import load_prs
    from repohealth_mcp.loaders.pr_review_comments import load_pr_review_comments
    load_prs(conn, client, repo=REPO,
             range_start="2010-01-01", range_end="2026-12-31", max_rows=3)
    result = load_pr_review_comments(
        conn, client, repo=REPO,
        range_start="2010-01-01", range_end="2026-12-31", max_rows=10,
    )
    # Hello-World may or may not have review comments; just verify no crash.
    assert result.row_count >= 0
```

- [ ] **Step 2: Run integration tests**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && GITHUB_TOKEN=$(gh auth token) uv run pytest tests/integration -m integration -v
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test(integration): v2 loaders against real GitHub (octocat/Hello-World)"
```

---

## Task 15: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the data-model table**

Replace the existing data-model table with:

```markdown
| Table | Source | Grain |
|---|---|---|
| `repos` | `/repos/{owner}/{name}` + `.github/FUNDING.yml` | one row per repo |
| `prs` | `/pulls` | one row per PR |
| `issues` | `/issues` (PRs filtered out) | one row per issue |
| `releases` | `/releases` | one row per release |
| `commit_activity` | `/stats/commit_activity` | one row per repo-week |
| `contributors` | `/stats/contributors` | one row per repo-author-week |
| `commits` | `/commits` | one row per commit |
| `commit_files` | `/commits/{sha}` | one row per file touched per commit (opt-in) |
| `pr_reviews` | `/pulls/{n}/reviews` | one row per review (opt-in) |
| `pr_review_comments` | `/pulls/{n}/comments` | one row per inline review comment (opt-in) |
| `dependencies` | `/dependency-graph/sbom` | one row per package |
| `star_history` | `/stargazers` (star+json) | one row per star event |
| `workflow_runs` | `/actions/runs` | one row per CI run |
| `snapshots` | bookkeeping | one row per `(repo, entity, range)` slice |
```

- [ ] **Step 2: Update the prompts list**

Replace the `**Prompts:**` line with:

```markdown
**Prompts:** `dep_health_query`, `compare_repos_query`, `release_cadence_query`, `responsiveness_query`, `contributor_health_query`, `commit_history_query`, `ci_health_query`, `dep_audit_query`, `star_trajectory_query`, `review_responsiveness_query`, `file_hotspots_query`, `review_comment_volume_query`.
```

- [ ] **Step 3: Add an opt-in note for pr_reviews under Architecture**

Insert below the architecture diagram:

```markdown
> `pr_reviews`, `pr_review_comments`, and `commit_files` are **opt-in**. Include them in `entities=[...]` explicitly when calling `load_repo`. Each fans out one API call per cached parent row (concurrently): PR-count for the review loaders, commit-count for `commit_files`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md && git commit -m "docs: v2 tables, prompts, and pr_reviews opt-in note"
```

---

## Task 16: Tag v0.2.0

- [ ] **Step 1: Run the full suite one more time**

```bash
cd /Users/brycekan/Downloads/repohealth-mcp && uv run pytest && uv run ruff check src tests
```
Expected: all pass, all checks pass.

- [ ] **Step 2: Tag and push**

```bash
git tag v0.2.0 && git push origin main && git push origin v0.2.0
```

- [ ] **Step 3: Verify uvx picks up the new tag**

```bash
uv cache clean
uvx --from git+https://github.com/brycekan123/repohealth-mcp@v0.2.0 repohealth-mcp --help 2>&1 | head -5
```
Expected: prints help / connects without error.

---

## Out-of-scope reminders (v3 backlog)

- **Cross-repo helpers** — `load_repos(list[str])`, `compare_repos_*` prompts, contributor-overlap signals.
- **Security advisories** — `/repos/.../security-advisories` and the Dependabot API.
- **GitHub Discussions** — community Q&A signals.
- **Languages + topics** — `/repos/.../languages` and `/repos/.../topics` (cheap, low effort — could be a v2.1 add).
- **Cache containment matching** — let `check_coverage` accept a `range_start/range_end` that is *contained* by a wider cached snapshot. UX win for daily users.
- **Architectural changes** — async pagination within a single loader, configurable retry budgets via env, freshness-driven auto-refresh.
