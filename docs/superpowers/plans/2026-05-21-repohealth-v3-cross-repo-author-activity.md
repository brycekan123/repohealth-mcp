# repohealth-mcp v3 Implementation Plan — Cross-Repo + Author Activity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn repohealth from "is this *repo* healthy?" into "what is this *maintainer or community* doing across GitHub?" by adding three new MCP tools layered cleanly over the v2 loaders: `load_repos` (parallel fan-out), `load_author_activity` (author-centric loading with internal `/search/commits`-based discovery), and `search_repos` (general repo discovery via `/search/repositories`).

**Architecture:** No refactor of v2 loaders. All existing tables already partition by `repo` and store the GitHub login in their `author`/`reviewer` columns, so cross-repo and author-filtered SQL falls out for free. v3 adds (a) a `normalize_repo` helper for URL/clone-line inputs, (b) one new SQLite bookkeeping table (`author_searches`), (c) a planner field for `author`, (d) three new MCP tools that compose over `load_repo`, (e) three new SQL prompt scaffolds, and (f) updated MCP routing instructions. Default author-activity discovery uses `/search/commits?q=author:<login>` — *not* `/search/repositories?involves=…`, which GitHub does not support.

**Tech Stack:** Python ≥3.11, FastMCP (`mcp[cli]`), httpx, SQLite. No new dependencies. All new code uses the existing `GitHubClient`, `parse_range`, `upsert_rows`, `record_snapshot`, `LoaderResult` primitives.

**Source spec:** `docs/superpowers/specs/2026-05-21-repohealth-v3-cross-repo-author-activity-design.md`

**Working directory for all paths:** `/Users/brycekan/Downloads/repohealth-mcp/`

**v2 reference:** `docs/superpowers/plans/2026-05-21-repohealth-mcp-v2.md`

---

## Test conventions to follow

- Unit tests stub the `GitHubClient` with `MagicMock` — see `tests/unit/test_load_repo.py` for the pattern (`_stub_client_for_all_entities`). Set `client.get.side_effect` and `client.paginate.return_value` / `client.paginate.side_effect`. Return `ResponseMeta(status, rate_limit_remaining, rate_limit_reset, next_url)` from `client.get`.
- Use `tmp_path` fixture for isolated SQLite databases. Build with `conn = connect(tmp_path / "x.sqlite"); init_schema(conn)`.
- Integration tests use the `@pytest.mark.integration` marker and hit real GitHub. They run via `uv run pytest tests/integration -m integration`.
- E2E tests live in `tests/e2e/`. Existing e2e file: `tests/e2e/test_full_flow.py`.

## Commit convention

Commits at the end of each task. Optional — batch if the user prefers, but each task is shaped so its diff makes sense as one commit.

## Verification cadence (subagent checkpoints)

Tasks are grouped into four implementation buckets, each ending in a **subagent verification checkpoint**. Run the agent at the bucket boundary, not after every task. The final Task 13 has its own live-probe-plus-subagent flow against the running MCP server.

| Bucket | Tasks | Checkpoint section |
|---|---|---|
| **A — Foundation primitives** | 1, 2, 3 | After Task 3 |
| **B — New tools** | 4, 5, 6, 7 | After Task 7 |
| **C — Server wiring + version** | 8, 9 | After Task 9 |
| **D — Tests + docs** | 10, 11, 12 | After Task 12 |
| **Live verification** | 13 | Task 13 itself |

Each checkpoint dispatches one `general-purpose` subagent with a self-contained prompt and explicit PASS/FAIL criteria. If a checkpoint reports FAIL, fix the issue inside its bucket before moving to the next bucket. If the user prefers a single agent at the very end instead of four bucket checkpoints, skip checkpoints A–D and rely on Task 13 alone.

---

## Task 1: `normalize_repo` URL/clone-line helper

**Files:**
- Create: `src/repohealth_mcp/util.py`
- Create: `tests/unit/test_util.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_util.py`:

```python
import pytest

from repohealth_mcp.util import normalize_repo


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("tanstack/query", "tanstack/query"),
        ("  tanstack/query  ", "tanstack/query"),
        ("https://github.com/tanstack/query", "tanstack/query"),
        ("https://github.com/tanstack/query.git", "tanstack/query"),
        ("http://github.com/tanstack/query", "tanstack/query"),
        ("github.com/tanstack/query", "tanstack/query"),
        ("git@github.com:tanstack/query.git", "tanstack/query"),
        ("https://github.com/tanstack/query/pulls/123", "tanstack/query"),
        ("https://github.com/tanstack/query/tree/main", "tanstack/query"),
        ("owner-with-dash/name.with.dots", "owner-with-dash/name.with.dots"),
    ],
)
def test_normalize_repo_canonicalizes_known_shapes(raw, expected):
    assert normalize_repo(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no-slash",
        "https://github.com/",
        "https://example.com/foo/bar",
        "git@gitlab.com:foo/bar.git",
    ],
)
def test_normalize_repo_rejects_unparseable(raw):
    with pytest.raises(ValueError):
        normalize_repo(raw)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_util.py -v
```

Expected: collection error or ImportError on `repohealth_mcp.util` (module does not exist).

- [ ] **Step 3: Write minimal implementation**

Create `src/repohealth_mcp/util.py`:

```python
"""Small input-normalization helpers shared across tools."""

from __future__ import annotations

import re

_REPO_NORMALIZE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?"
    r"([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$"
)


def normalize_repo(text: str) -> str:
    """Canonicalize a repo reference to `owner/name`.

    Accepts:
      - `owner/name`
      - `https://github.com/owner/name`
      - `https://github.com/owner/name.git`
      - `git@github.com:owner/name.git`
      - `github.com/owner/name`
      - any of the above with trailing path segments (e.g. `/pulls/123`)

    Raises ValueError if the input does not parse to two non-empty
    `[\\w.-]+` segments separated by `/`.
    """
    if not isinstance(text, str):
        raise ValueError(f"normalize_repo expects a string, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise ValueError("normalize_repo got empty string")
    match = _REPO_NORMALIZE.match(stripped)
    if not match:
        raise ValueError(f"can't parse repo from: {text!r}")
    owner, name = match.group(1), match.group(2)
    if not owner or not name:
        raise ValueError(f"can't parse repo from: {text!r}")
    return f"{owner}/{name}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_util.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/util.py tests/unit/test_util.py
git commit -m "feat(v3): add normalize_repo helper for URL/clone-line inputs"
```

---

## Task 2: Add `author_searches` table to schema

**Files:**
- Modify: `src/repohealth_mcp/database.py` (extend `SCHEMA_SQL` and `EXPECTED_TABLES`)
- Modify: `tests/unit/test_database.py` (add table assertion)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_database.py`:

```python
def test_author_searches_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(author_searches)").fetchall()}
    expected = {"login", "discovery", "range_start", "range_end", "repos_json", "discovered_at"}
    assert expected.issubset(cols)


def test_author_searches_in_expected_tables_set() -> None:
    from repohealth_mcp.database import EXPECTED_TABLES
    assert "author_searches" in EXPECTED_TABLES
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_database.py::test_author_searches_table_has_expected_columns tests/unit/test_database.py::test_author_searches_in_expected_tables_set -v
```

Expected: both fail — `PRAGMA table_info` returns empty (table missing) and `author_searches` not in `EXPECTED_TABLES`.

- [ ] **Step 3: Add the table to schema**

In `src/repohealth_mcp/database.py`:

1. Add `"author_searches"` to the `EXPECTED_TABLES` set:

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
    "author_searches",
}
```

2. Append this CREATE TABLE to `SCHEMA_SQL` (just before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS author_searches (
    login           TEXT NOT NULL,
    discovery       TEXT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    repos_json      TEXT NOT NULL,
    discovered_at   TEXT NOT NULL,
    PRIMARY KEY (login, discovery, range_start, range_end)
);
CREATE INDEX IF NOT EXISTS idx_author_searches_login ON author_searches(login);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_database.py -v
```

Expected: previously-passing tests still pass; new two tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/database.py tests/unit/test_database.py
git commit -m "feat(v3): add author_searches table for author-discovery bookkeeping"
```

---

## Task 3: Planner — `author` field + expand entity allowlist

**Files:**
- Modify: `src/repohealth_mcp/planner.py`
- Modify: `tests/unit/test_planner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_planner.py`:

```python
def test_planner_round_trips_author_field():
    from repohealth_mcp.planner import extract_plan_from_text

    plan = extract_plan_from_text(
        '{"repos": [], "entities": ["commits"], "range": "6mo", "author": "gaearon"}'
    )
    assert plan.author == "gaearon"
    assert plan.repos == []
    assert plan.entities == ["commits"]


def test_planner_author_defaults_to_none():
    from repohealth_mcp.planner import extract_plan_from_text

    plan = extract_plan_from_text(
        '{"repos": ["facebook/react"], "entities": ["prs"], "range": "6mo"}'
    )
    assert plan.author is None


def test_planner_accepts_commits_in_entities():
    from repohealth_mcp.planner import extract_plan_from_text

    plan = extract_plan_from_text(
        '{"repos": ["facebook/react"], "entities": ["prs", "commits"], "range": "6mo"}'
    )
    assert "commits" in plan.entities
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_planner.py -v
```

Expected:
- `test_planner_round_trips_author_field` fails: `PlanResult` has no `author` attribute (or `extract_plan_from_text` discards it).
- `test_planner_author_defaults_to_none` may pass or fail depending on dataclass default; if `PlanResult` has no `author`, AttributeError.
- `test_planner_accepts_commits_in_entities` fails: `commits` is not in `_DEFAULT_ENTITY_SET` so the planner raises "unknown entities in plan: ['commits']".

- [ ] **Step 3: Update planner**

In `src/repohealth_mcp/planner.py`:

1. Change the `_DEFAULT_ENTITY_SET` to a separate allowlist that includes `commits`:

```python
DEFAULT_ENTITIES = ["prs", "issues", "releases", "commit_activity", "contributors"]
ALLOWED_PLAN_ENTITIES = {
    "prs", "issues", "releases", "commit_activity", "contributors", "commits",
}
DEFAULT_RANGE = "6mo"
```

2. Add `author: str | None = None` to `PlanResult`:

```python
@dataclass
class PlanResult:
    repos: list[str]
    entities: list[str]
    range_spec: str
    author: str | None = None
```

3. Update `PLANNER_SYSTEM_PROMPT` to mention `author` and the broader entity set:

```python
PLANNER_SYSTEM_PROMPT = """\
You parse a user's natural-language question about GitHub repos or maintainers into a fetch plan.

Return ONLY a single JSON object with these keys:
  - "repos": list of "owner/name" strings mentioned in the question. May be empty
    if the question is author-centric and names no repos.
  - "entities": list, subset of:
        ["prs", "issues", "releases", "commit_activity", "contributors", "commits"].
  - "range": one of "30d", "90d", "6mo", "1y", "all", or "YYYY-MM-DD..YYYY-MM-DD".
  - "author": optional string. If the question names a GitHub user (e.g. a contributor
    or maintainer), set this to their login. Omit or set to null otherwise.

Default to ["prs","issues","releases","commit_activity","contributors"] entities
and "6mo" range if the question is general.
"""
```

4. Update `extract_plan_from_text` to use the broader allowlist and read `author`:

```python
def extract_plan_from_text(text: str) -> PlanResult:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError(f"could not find JSON object in LLM output: {text[:200]}")

    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON from LLM: {exc}") from exc

    repos = obj.get("repos") or []
    if not isinstance(repos, list) or not all(isinstance(repo, str) for repo in repos):
        raise ValueError("plan repos must be a list of strings")

    entities = obj.get("entities") or DEFAULT_ENTITIES
    if not isinstance(entities, list) or not all(isinstance(entity, str) for entity in entities):
        raise ValueError("plan entities must be a list of strings")
    unknown_entities = set(entities) - ALLOWED_PLAN_ENTITIES
    if unknown_entities:
        raise ValueError(f"unknown entities in plan: {sorted(unknown_entities)}")

    range_spec = obj.get("range") or DEFAULT_RANGE
    if not isinstance(range_spec, str):
        raise ValueError("plan range must be a string")

    author = obj.get("author")
    if author is not None and not isinstance(author, str):
        raise ValueError("plan author must be a string or null")
    if isinstance(author, str) and not author.strip():
        author = None

    return PlanResult(
        repos=list(repos),
        entities=list(entities),
        range_spec=range_spec,
        author=author,
    )
```

Note: the v1/v2 plan required at least one repo. v3 relaxes this — author-only plans are valid. Any existing test that asserts "plan requires at least one repo" needs to be updated or removed; check `tests/unit/test_planner.py` and adjust accordingly.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_planner.py -v
```

Expected: all green. If a pre-existing test asserted "plan requires at least one repo", update it to assert this behavior moved (author-only plans are now allowed; an entirely empty plan with no repos and no author is still invalid — add an explicit check if you want one).

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/planner.py tests/unit/test_planner.py
git commit -m "feat(v3): planner accepts optional author field; allow 'commits' entity"
```

---

## Bucket A Checkpoint — Foundation primitives

**State at this checkpoint:** Tasks 1–3 complete. `normalize_repo` helper exists, `author_searches` table is in the schema, and the planner accepts an optional `author` field plus `commits` in its entity allowlist. No MCP-facing tools yet.

- [ ] **Dispatch a `general-purpose` subagent with this prompt (paste verbatim):**

```text
Verify foundation primitives for repohealth-mcp v3. Working dir: /Users/brycekan/Downloads/repohealth-mcp.

Run these checks and report PASS/FAIL for each with one line of evidence:

1. `uv run pytest tests/unit/test_util.py tests/unit/test_database.py tests/unit/test_planner.py -q` must be green.
2. `uv run python -c "from repohealth_mcp.util import normalize_repo; print(normalize_repo('https://github.com/foo/bar.git'))"` prints `foo/bar`.
3. `uv run python -c "from repohealth_mcp.database import EXPECTED_TABLES; print('author_searches' in EXPECTED_TABLES)"` prints `True`.
4. `uv run python -c "from repohealth_mcp.planner import PlanResult; print(PlanResult(repos=[], entities=[], range_spec='6mo').author is None)"` prints `True`.
5. `uv run python -c "from repohealth_mcp.planner import extract_plan_from_text; p = extract_plan_from_text('{\"repos\":[],\"entities\":[\"commits\"],\"range\":\"6mo\",\"author\":\"gaearon\"}'); print(p.author)"` prints `gaearon`.

Do not edit code. Report under 150 words.
```

**Expected:** 5/5 PASS. If any FAIL, fix inside Bucket A before starting Task 4.

---

## Task 4: `load_repos` cross-repo orchestrator

**Files:**
- Create: `src/repohealth_mcp/tools/load_repos.py`
- Create: `tests/unit/test_load_repos.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_load_repos.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.load_repos import load_repos


def _stub_client():
    client = MagicMock()
    repo_meta_body = {
        "full_name": "x/y",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }

    def _get(url, **_):
        return (repo_meta_body, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "v3.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.close()
    return path


def test_load_repos_dispatches_each_repo(db_path):
    def make_client():
        return _stub_client()

    with patch(
        "repohealth_mcp.tools.load_repos._make_client", side_effect=make_client
    ):
        result = load_repos(
            db_path,
            repos=["octocat/Hello-World", "github/gitignore", "foo/bar"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            max_concurrency=2,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert set(result["per_repo"].keys()) == {
        "octocat/Hello-World",
        "github/gitignore",
        "foo/bar",
    }
    assert result["api_calls_used"] >= 3  # at least one per-repo meta call
    assert "errors" in result


def test_load_repos_normalizes_url_inputs(db_path):
    with patch(
        "repohealth_mcp.tools.load_repos._make_client", side_effect=lambda: _stub_client()
    ):
        result = load_repos(
            db_path,
            repos=[
                "https://github.com/octocat/Hello-World",
                "git@github.com:github/gitignore.git",
            ],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert set(result["per_repo"].keys()) == {"octocat/Hello-World", "github/gitignore"}


def test_load_repos_reports_per_repo_errors_without_aborting_batch(db_path):
    def make_client():
        client = MagicMock()
        repo_meta_body = {
            "full_name": "x/y",
            "description": "t",
            "default_branch": "main",
            "stargazers_count": 1,
            "forks_count": 0,
            "open_issues_count": 0,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2026-01-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": {"spdx_id": "MIT"},
        }

        call_count = {"n": 0}

        def _get(url, **_):
            call_count["n"] += 1
            if call_count["n"] == 1 and "/repos/bad/repo" in url:
                raise RuntimeError("simulated 500")
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))

        client.get.side_effect = _get
        client.paginate.return_value = iter([])
        client.last_meta = ResponseMeta(200, 4999, None, None)
        return client

    # Use a single shared client across threads so the side_effect counts globally.
    shared = make_client()
    with patch(
        "repohealth_mcp.tools.load_repos._make_client", side_effect=lambda: shared
    ):
        result = load_repos(
            db_path,
            repos=["bad/repo", "good/repo"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            max_concurrency=1,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert "good/repo" in result["per_repo"]
    assert any(err["repo"] == "bad/repo" for err in result["errors"])


def test_load_repos_drops_unparseable_repo_inputs(db_path):
    with patch(
        "repohealth_mcp.tools.load_repos._make_client", side_effect=lambda: _stub_client()
    ):
        result = load_repos(
            db_path,
            repos=["good/repo", "totally not a repo"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert "good/repo" in result["per_repo"]
    assert any(
        err.get("repo") == "totally not a repo" and "parse" in err["error"].lower()
        for err in result["errors"]
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_load_repos.py -v
```

Expected: ImportError on `repohealth_mcp.tools.load_repos` (module does not exist).

- [ ] **Step 3: Implement `load_repos`**

Create `src/repohealth_mcp/tools/load_repos.py`:

```python
"""load_repos: fan out v2's load_repo across multiple repos in parallel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import connect
from ..github_client import GitHubClient, resolve_token
from ..util import normalize_repo
from .load_repo import DEFAULT_ENTITIES, load_repo


def _make_client() -> GitHubClient:
    """Return a fresh GitHubClient. Indirection exists so tests can patch it."""
    return GitHubClient(token=resolve_token())


def _aggregate_rate_limit(per_repo: dict[str, dict[str, Any]]) -> dict[str, Any]:
    remainings: list[int] = []
    resets: list[int] = []
    warnings: list[str] = []
    for summary in per_repo.values():
        rl = summary.get("rate_limit_summary") or {}
        if isinstance(rl.get("remaining"), int):
            remainings.append(rl["remaining"])
        if isinstance(rl.get("resets_in_minutes"), int):
            resets.append(rl["resets_in_minutes"])
        if rl.get("warning"):
            warnings.append(rl["warning"])
    return {
        "remaining": min(remainings) if remainings else None,
        "resets_in_minutes": min(resets) if resets else None,
        "warning": "; ".join(warnings) if warnings else None,
    }


def load_repos(
    db_path: Path | str,
    *,
    repos: list[str],
    entities: list[str] | None = None,
    range_spec: str = "6mo",
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fan out load_repo across multiple repos in parallel.

    - Each child opens its own GitHubClient and SQLite connection.
    - Per-repo failures land in `errors` without aborting the batch.
    - Inputs are run through normalize_repo first; unparseable entries go to errors.
    """
    now = now or datetime.now(timezone.utc)
    entity_list = list(entities or DEFAULT_ENTITIES)
    max_workers = max(1, min(max_concurrency, len(repos) or 1))

    normalized: list[str] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in repos:
        try:
            canonical = normalize_repo(raw)
        except ValueError as exc:
            errors.append({"repo": raw, "error": f"normalize_repo: {exc}"})
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)

    per_repo: dict[str, dict[str, Any]] = {}

    def _one(repo: str) -> tuple[str, dict[str, Any] | None, str | None]:
        client = _make_client()
        conn = connect(db_path)
        try:
            summary = load_repo(
                conn,
                client,
                repo=repo,
                entities=entity_list,
                range_spec=range_spec,
                max_rows_per_entity=max_rows_per_entity,
                now=now,
            )
            return repo, summary, None
        except Exception as exc:  # noqa: BLE001 — surface everything to caller
            return repo, None, str(exc)
        finally:
            try:
                client.close()
            finally:
                conn.close()

    if normalized:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_one, repo): repo for repo in normalized}
            for future in as_completed(futures):
                repo, summary, error = future.result()
                if error is not None:
                    errors.append({"repo": repo, "error": error})
                else:
                    per_repo[repo] = summary

    api_calls_used = sum(
        int(summary.get("api_calls_used") or 0) for summary in per_repo.values()
    )

    return {
        "per_repo": per_repo,
        "errors": errors,
        "api_calls_used": api_calls_used,
        "rate_limit_summary": _aggregate_rate_limit(per_repo),
        "cached_at": now.isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_load_repos.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/tools/load_repos.py tests/unit/test_load_repos.py
git commit -m "feat(v3): add load_repos cross-repo fan-out tool"
```

---

## Task 5: `search_repos` (general `/search/repositories` wrapper)

**Files:**
- Create: `src/repohealth_mcp/tools/search_repos.py`
- Create: `tests/unit/test_search_repos.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_search_repos.py`:

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.search_repos import search_repos


def _client_with_response(items, total_count=None):
    client = MagicMock()
    payload = {
        "total_count": total_count if total_count is not None else len(items),
        "items": items,
    }
    client.get.return_value = (payload, ResponseMeta(200, 4999, None, None))
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


def test_search_repos_composes_query_from_keywords():
    client = _client_with_response([])
    search_repos(client, query="logging", language="python", sort="stars", limit=5)
    args, kwargs = client.get.call_args
    assert args[0] == "/search/repositories"
    assembled_q = kwargs.get("q") or kwargs.get("params", {}).get("q") or ""
    # Implementation may pass `q` as a kwarg or via params; either is fine,
    # but the assembled string must contain both terms.
    assert "logging" in assembled_q
    assert "language:python" in assembled_q
    assert kwargs.get("sort") == "stars" or kwargs.get("params", {}).get("sort") == "stars"


def test_search_repos_handles_owner_and_topic_qualifiers():
    client = _client_with_response([])
    search_repos(client, owner="rails", topic="api", limit=3)
    _args, kwargs = client.get.call_args
    assembled_q = kwargs.get("q") or kwargs.get("params", {}).get("q") or ""
    assert "user:rails" in assembled_q
    assert "topic:api" in assembled_q


def test_search_repos_rejects_involves_kwarg():
    client = _client_with_response([])
    with pytest.raises(TypeError):
        search_repos(client, involves="someone")  # type: ignore[call-arg]


def test_search_repos_filters_archived_and_forks_by_default():
    items = [
        {
            "full_name": "ok/repo",
            "stargazers_count": 100,
            "language": "Python",
            "pushed_at": "2026-05-20T00:00:00Z",
            "archived": False,
            "fork": False,
            "description": "fine",
        },
        {
            "full_name": "stale/repo",
            "stargazers_count": 5,
            "language": "Python",
            "pushed_at": "2018-01-01T00:00:00Z",
            "archived": True,
            "fork": False,
            "description": None,
        },
        {
            "full_name": "fork/repo",
            "stargazers_count": 2,
            "language": "Python",
            "pushed_at": "2026-01-01T00:00:00Z",
            "archived": False,
            "fork": True,
            "description": None,
        },
    ]
    client = _client_with_response(items, total_count=3)
    result = search_repos(client, query="anything", limit=5)
    repos = [r["repo"] for r in result["repos"]]
    assert repos == ["ok/repo"]
    assert result["total_count"] == 3  # raw total reflects unfiltered count


def test_search_repos_caps_limit_at_100():
    client = _client_with_response([])
    search_repos(client, query="anything", limit=10_000)
    _args, kwargs = client.get.call_args
    per_page = kwargs.get("per_page") or kwargs.get("params", {}).get("per_page")
    assert per_page is not None and per_page <= 100
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_search_repos.py -v
```

Expected: ImportError on `repohealth_mcp.tools.search_repos`.

- [ ] **Step 3: Implement `search_repos`**

Create `src/repohealth_mcp/tools/search_repos.py`:

```python
"""search_repos: wrap GitHub /search/repositories. No DB writes."""

from __future__ import annotations

from typing import Any

_VALID_SORT = {"stars", "forks", "updated", "best-match"}


def _assemble_query(
    query: str | None,
    owner: str | None,
    language: str | None,
    topic: str | None,
) -> str:
    parts: list[str] = []
    if query:
        parts.append(query.strip())
    if owner:
        parts.append(f"user:{owner}")
    if language:
        parts.append(f"language:{language}")
    if topic:
        parts.append(f"topic:{topic}")
    return " ".join(p for p in parts if p)


def search_repos(
    client,
    *,
    query: str | None = None,
    owner: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    sort: str = "updated",
    limit: int = 20,
    include_forks: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Search GitHub repos and return canonical `owner/name` rows.

    Note: `/search/repositories` does NOT support an `involves:` qualifier.
    That use case (repos a given login contributed to) is handled internally
    by load_author_activity's /search/commits-based discovery helper.
    """
    if sort not in _VALID_SORT:
        raise ValueError(f"sort must be one of {sorted(_VALID_SORT)}; got {sort!r}")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    assembled = _assemble_query(query, owner, language, topic)
    if not assembled:
        raise ValueError("search_repos requires at least one of: query, owner, language, topic")

    per_page = min(100, limit)
    body, _meta = client.get(
        "/search/repositories",
        q=assembled,
        sort=sort if sort != "best-match" else None,
        per_page=per_page,
    )
    if not isinstance(body, dict):
        raise ValueError(f"unexpected /search/repositories response: {type(body)}")

    items = body.get("items") or []
    total_count = body.get("total_count", len(items))

    rows: list[dict[str, Any]] = []
    for item in items[:limit]:
        archived = bool(item.get("archived"))
        fork = bool(item.get("fork"))
        if archived and not include_archived:
            continue
        if fork and not include_forks:
            continue
        full_name = item.get("full_name")
        if not full_name:
            continue
        rows.append(
            {
                "repo": full_name,
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "pushed_at": item.get("pushed_at"),
                "archived": archived,
                "fork": fork,
                "description": item.get("description"),
            }
        )

    return {
        "query": assembled,
        "repos": rows,
        "total_count": total_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_search_repos.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/tools/search_repos.py tests/unit/test_search_repos.py
git commit -m "feat(v3): add search_repos tool (general /search/repositories wrapper)"
```

---

## Task 6: Author-discovery helper (`/search/commits` aggregator)

**Files:**
- Create: `src/repohealth_mcp/author_discovery.py`
- Create: `tests/unit/test_author_discovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_author_discovery.py`:

```python
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.author_discovery import discover_repos_by_commits, discover_owned_repos
from repohealth_mcp.github_client import ResponseMeta


def _client(get_side_effect):
    client = MagicMock()
    client.get.side_effect = get_side_effect
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


def test_discover_repos_by_commits_aggregates_unique_repos():
    pages = [
        {
            "total_count": 4,
            "items": [
                {"repository": {"full_name": "a/x"}},
                {"repository": {"full_name": "a/x"}},
                {"repository": {"full_name": "b/y"}},
            ],
        },
        {
            "total_count": 4,
            "items": [
                {"repository": {"full_name": "c/z"}},
            ],
        },
    ]
    state = {"i": 0}

    def _get(url, **_):
        page = pages[state["i"]]
        state["i"] += 1
        next_url = "/search/commits?page=2" if state["i"] == 1 else None
        return page, ResponseMeta(200, 4999, None, next_url)

    client = _client(_get)
    repos = discover_repos_by_commits(client, login="someone", max_repos=10, max_pages=10)
    assert repos == ["a/x", "b/y", "c/z"]


def test_discover_repos_by_commits_stops_at_max_repos():
    page = {
        "total_count": 3,
        "items": [
            {"repository": {"full_name": "a/x"}},
            {"repository": {"full_name": "b/y"}},
            {"repository": {"full_name": "c/z"}},
        ],
    }
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, None)))
    repos = discover_repos_by_commits(client, login="someone", max_repos=2)
    assert repos == ["a/x", "b/y"]


def test_discover_repos_by_commits_skips_null_repository():
    page = {
        "total_count": 2,
        "items": [
            {"repository": None},
            {"repository": {"full_name": "a/x"}},
        ],
    }
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, None)))
    repos = discover_repos_by_commits(client, login="someone", max_repos=5)
    assert repos == ["a/x"]


def test_discover_owned_repos_filters_archived_and_forks():
    body = [
        {"full_name": "x/keep", "archived": False, "fork": False},
        {"full_name": "x/skip-archived", "archived": True, "fork": False},
        {"full_name": "x/skip-fork", "archived": False, "fork": True},
    ]
    client = _client(lambda *_a, **_kw: (body, ResponseMeta(200, 4999, None, None)))
    repos = discover_owned_repos(client, login="x", max_repos=5)
    assert repos == ["x/keep"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_author_discovery.py -v
```

Expected: ImportError on `repohealth_mcp.author_discovery`.

- [ ] **Step 3: Implement the discovery helpers**

Create `src/repohealth_mcp/author_discovery.py`:

```python
"""Helpers that discover candidate repos for a given GitHub login.

Used by load_author_activity. Lives outside tools/ because it is internal
to one tool, not its own MCP-facing tool.
"""

from __future__ import annotations

from typing import Any


def discover_repos_by_commits(
    client,
    *,
    login: str,
    max_repos: int = 10,
    max_pages: int = 10,
    per_page: int = 100,
    range_start: str | None = None,
    range_end: str | None = None,
) -> list[str]:
    """Aggregate unique `owner/name` from /search/commits?q=author:LOGIN.

    Caps both at `max_repos` (output size) and `max_pages` (search-API budget).
    Per-page hits the search API once. With per_page=100, max_pages=10 → 10 calls.
    """
    if not login:
        raise ValueError("login is required")

    query_parts = [f"author:{login}"]
    if range_start:
        query_parts.append(f"author-date:>={range_start}")
    if range_end:
        query_parts.append(f"author-date:<={range_end}")
    q = " ".join(query_parts)
    seen: list[str] = []
    seen_set: set[str] = set()
    url: str | Any = "/search/repositories-stub"  # overwritten on first iteration
    pages_used = 0

    # Initial call uses the /search/commits endpoint; subsequent pages follow next_url.
    url, params = "/search/commits", {
        "q": q,
        "sort": "author-date",
        "order": "desc",
        "per_page": per_page,
    }

    while pages_used < max_pages and len(seen) < max_repos:
        if isinstance(url, str) and url.startswith("/search"):
            body, meta = client.get(url, **params)
            params = {}  # next_url is fully qualified; no params needed
        else:
            body, meta = client.get(url)

        if not isinstance(body, dict):
            break
        for item in body.get("items") or []:
            repo_obj = item.get("repository")
            if not isinstance(repo_obj, dict):
                continue
            full_name = repo_obj.get("full_name")
            if not full_name or full_name in seen_set:
                continue
            seen_set.add(full_name)
            seen.append(full_name)
            if len(seen) >= max_repos:
                break

        pages_used += 1
        next_url = getattr(meta, "next_url", None)
        if not next_url:
            break
        url = next_url

    return seen


def discover_owned_repos(
    client,
    *,
    login: str,
    max_repos: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
) -> list[str]:
    """List repos owned by `login`, sorted by most recent push, filtered."""
    if not login:
        raise ValueError("login is required")
    per_page = min(100, max(1, max_repos * 2))  # over-fetch to survive filtering
    body, _meta = client.get(
        f"/users/{login}/repos",
        sort="pushed",
        per_page=per_page,
    )
    if not isinstance(body, list):
        return []
    out: list[str] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        if item.get("archived") and not include_archived:
            continue
        if item.get("fork") and not include_forks:
            continue
        full_name = item.get("full_name")
        if not full_name:
            continue
        out.append(full_name)
        if len(out) >= max_repos:
            break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_author_discovery.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/author_discovery.py tests/unit/test_author_discovery.py
git commit -m "feat(v3): add author-discovery helpers (/search/commits and /users/{login}/repos)"
```

---

## Task 7: `load_author_activity` tool

**Files:**
- Create: `src/repohealth_mcp/tools/load_author_activity.py`
- Create: `tests/unit/test_load_author_activity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_load_author_activity.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.tools.load_author_activity import (
    DEFAULT_AUTHOR_ENTITIES,
    load_author_activity,
)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "author.sqlite"
    conn = connect(p)
    init_schema(conn)
    conn.close()
    return p


def _fake_load_repos(*, expected_repos, return_summary=None):
    """Build a stand-in for load_repos that asserts repos and returns a summary."""
    def _impl(db_path, *, repos, entities, range_spec, max_rows_per_entity, max_concurrency, now):
        assert set(repos) == set(expected_repos)
        assert "commits" in entities
        return return_summary or {
            "per_repo": {r: {"fetched": {"commits": 1}, "api_calls_used": 2} for r in repos},
            "errors": [],
            "api_calls_used": 2 * len(repos),
            "rate_limit_summary": {"remaining": 4999, "resets_in_minutes": 1, "warning": None},
            "cached_at": now.isoformat(),
        }
    return _impl


def test_load_author_activity_with_explicit_repos_skips_discovery(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x", "b/y"])

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client"
    ) as mock_client_factory, patch(
        "repohealth_mcp.tools.load_author_activity.load_repos",
        side_effect=fake_load_repos,
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits"
    ) as mock_search, patch(
        "repohealth_mcp.tools.load_author_activity.discover_owned_repos"
    ) as mock_owned:
        result = load_author_activity(
            db_path,
            login="someone",
            repos=["a/x", "b/y"],
            range_spec="6mo",
            entities=["prs"],
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["login"] == "someone"
    assert result["discovery_source"] == "caller"
    assert set(result["discovered_repos"]) == {"a/x", "b/y"}
    mock_search.assert_not_called()
    mock_owned.assert_not_called()
    # Connection should not be opened for discovery path either.
    mock_client_factory.assert_not_called()


def test_load_author_activity_default_discovery_uses_search_commits(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x", "b/y"])

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client"
    ), patch(
        "repohealth_mcp.tools.load_author_activity.load_repos",
        side_effect=fake_load_repos,
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
        return_value=["a/x", "b/y"],
    ) as mock_search, patch(
        "repohealth_mcp.tools.load_author_activity.discover_owned_repos"
    ) as mock_owned:
        result = load_author_activity(
            db_path,
            login="someone",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["discovery_source"] == "search"
    mock_search.assert_called_once()
    mock_owned.assert_not_called()


def test_load_author_activity_owned_discovery_uses_users_repos(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client"
    ), patch(
        "repohealth_mcp.tools.load_author_activity.load_repos",
        side_effect=fake_load_repos,
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits"
    ) as mock_search, patch(
        "repohealth_mcp.tools.load_author_activity.discover_owned_repos",
        return_value=["a/x"],
    ) as mock_owned:
        result = load_author_activity(
            db_path,
            login="someone",
            discovery="owned",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["discovery_source"] == "owned"
    mock_owned.assert_called_once()
    mock_search.assert_not_called()


def test_load_author_activity_writes_author_searches_row(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client"
    ), patch(
        "repohealth_mcp.tools.load_author_activity.load_repos",
        side_effect=fake_load_repos,
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
        return_value=["a/x"],
    ):
        load_author_activity(
            db_path,
            login="someone",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT login, discovery, repos_json FROM author_searches WHERE login=?",
            ("someone",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "someone"
    assert row[1] == "search"
    assert json.loads(row[2]) == ["a/x"]


def test_load_author_activity_default_entities_excludes_pr_reviews():
    assert "commits" in DEFAULT_AUTHOR_ENTITIES
    assert "prs" in DEFAULT_AUTHOR_ENTITIES
    assert "issues" in DEFAULT_AUTHOR_ENTITIES
    assert "pr_reviews" not in DEFAULT_AUTHOR_ENTITIES


def test_load_author_activity_emits_note_when_pr_reviews_not_loaded(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client"
    ), patch(
        "repohealth_mcp.tools.load_author_activity.load_repos",
        side_effect=fake_load_repos,
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
        return_value=["a/x"],
    ):
        result = load_author_activity(
            db_path,
            login="someone",
            entities=["commits", "prs", "issues"],
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert any("pr_reviews" in n for n in result["notes"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_load_author_activity.py -v
```

Expected: ImportError on `repohealth_mcp.tools.load_author_activity`.

- [ ] **Step 3: Implement `load_author_activity`**

Create `src/repohealth_mcp/tools/load_author_activity.py`:

```python
"""load_author_activity: load a GitHub user's recent activity across repos."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..author_discovery import discover_owned_repos, discover_repos_by_commits
from ..database import connect
from ..github_client import GitHubClient, resolve_token
from ..loaders.base import parse_range
from ..util import normalize_repo
from .load_repos import load_repos

DEFAULT_AUTHOR_ENTITIES: tuple[str, ...] = ("commits", "prs", "issues")
VALID_DISCOVERY: tuple[str, ...] = ("search", "owned")


def _make_client() -> GitHubClient:
    """Return a fresh GitHubClient. Indirection exists so tests can patch it."""
    return GitHubClient(token=resolve_token())


def _record_author_search(
    db_path: Path | str,
    *,
    login: str,
    discovery: str,
    range_start: str,
    range_end: str,
    repos: list[str],
    discovered_at: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO author_searches
                (login, discovery, range_start, range_end, repos_json, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(login, discovery, range_start, range_end)
            DO UPDATE SET repos_json=excluded.repos_json,
                          discovered_at=excluded.discovered_at
            """,
            (login, discovery, range_start, range_end, json.dumps(repos), discovered_at),
        )
    finally:
        conn.close()


def load_author_activity(
    db_path: Path | str,
    *,
    login: str,
    repos: list[str] | None = None,
    range_spec: str = "1y",
    discovery: str = "search",
    entities: list[str] | None = None,
    max_repos: int = 10,
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not login or not login.strip():
        raise ValueError("login is required")
    if discovery not in VALID_DISCOVERY:
        raise ValueError(f"discovery must be one of {VALID_DISCOVERY}; got {discovery!r}")

    now = now or datetime.now(timezone.utc)
    range_start, range_end = parse_range(range_spec, now=now)

    entity_list = list(entities or DEFAULT_AUTHOR_ENTITIES)
    if "commits" not in entity_list:
        entity_list = ["commits", *entity_list]

    notes: list[str] = []
    if "pr_reviews" not in entity_list:
        notes.append(
            "pr_reviews not loaded; re-run with entities=[..., 'pr_reviews'] to include "
            "review activity (1 extra API call per cached PR)."
        )

    discovery_source: str
    discovered: list[str]
    if repos:
        discovery_source = "caller"
        discovered = []
        seen: set[str] = set()
        for raw in repos:
            try:
                canonical = normalize_repo(raw)
            except ValueError as exc:
                notes.append(f"dropped {raw!r}: {exc}")
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            discovered.append(canonical)
    else:
        client = _make_client()
        try:
            if discovery == "search":
                discovery_source = "search"
                discovered = discover_repos_by_commits(
                    client, login=login, max_repos=max_repos
                )
            else:
                discovery_source = "owned"
                discovered = discover_owned_repos(
                    client, login=login, max_repos=max_repos
                )
        finally:
            client.close()

    if not discovered:
        notes.append(f"no repos discovered for {login!r} via {discovery_source}")
        fetched: dict[str, Any] = {
            "per_repo": {},
            "errors": [],
            "api_calls_used": 0,
            "rate_limit_summary": {
                "remaining": None,
                "resets_in_minutes": None,
                "warning": None,
            },
            "cached_at": now.isoformat(),
        }
    else:
        fetched = load_repos(
            db_path,
            repos=discovered,
            entities=entity_list,
            range_spec=range_spec,
            max_rows_per_entity=max_rows_per_entity,
            max_concurrency=max_concurrency,
            now=now,
        )

    _record_author_search(
        db_path,
        login=login,
        discovery=discovery_source,
        range_start=range_start,
        range_end=range_end,
        repos=discovered,
        discovered_at=now.isoformat(),
    )

    return {
        "login": login,
        "discovered_repos": discovered,
        "discovery_source": discovery_source,
        "range_start": range_start,
        "range_end": range_end,
        "entities": entity_list,
        "fetched": fetched,
        "notes": notes,
        "cached_at": now.isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_load_author_activity.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/tools/load_author_activity.py tests/unit/test_load_author_activity.py
git commit -m "feat(v3): add load_author_activity tool with internal repo discovery"
```

---

## Bucket B Checkpoint — New tools

**State at this checkpoint:** Tasks 4–7 complete. `load_repos`, `search_repos`, the author-discovery helpers, and `load_author_activity` all exist with unit tests. Nothing is wired into `server.py` yet — these are still library-level functions.

- [ ] **Dispatch a `general-purpose` subagent with this prompt (paste verbatim):**

```text
Verify v3 tools for repohealth-mcp. Working dir: /Users/brycekan/Downloads/repohealth-mcp.

Run these checks and report PASS/FAIL for each with one line of evidence:

1. `uv run pytest tests/unit/test_load_repos.py tests/unit/test_search_repos.py tests/unit/test_author_discovery.py tests/unit/test_load_author_activity.py -q` must be green.
2. These imports succeed without error (run via `uv run python -c "..."` for each):
   - `from repohealth_mcp.tools.load_repos import load_repos`
   - `from repohealth_mcp.tools.search_repos import search_repos`
   - `from repohealth_mcp.tools.load_author_activity import load_author_activity, DEFAULT_AUTHOR_ENTITIES`
   - `from repohealth_mcp.author_discovery import discover_repos_by_commits, discover_owned_repos`
3. `uv run python -c "from repohealth_mcp.tools.load_author_activity import DEFAULT_AUTHOR_ENTITIES; print('commits' in DEFAULT_AUTHOR_ENTITIES and 'pr_reviews' not in DEFAULT_AUTHOR_ENTITIES)"` prints `True`.
4. `uv run python -c "import inspect; from repohealth_mcp.tools.search_repos import search_repos; print('involves' in inspect.signature(search_repos).parameters)"` prints `False`.

Do not edit code. Report under 150 words.
```

**Expected:** 4/4 PASS. If any FAIL, fix inside Bucket B before starting Task 8.

---

## Task 8: Wire all three tools (and prompts, and MCP_INSTRUCTIONS) into `server.py`

**Files:**
- Modify: `src/repohealth_mcp/server.py`
- Modify: `tests/unit/test_prompts.py` (or extend `tests/unit/test_server_smoke.py`)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_server_smoke.py` (creating if absent — it already exists per the repo layout):

```python
def test_server_exposes_v3_tools():
    from repohealth_mcp import server
    tool_names = {name for name in dir(server) if not name.startswith("_")}
    # MCP tool functions are top-level callables decorated with @mcp.tool().
    assert "load_repos" in tool_names
    assert "load_author_activity" in tool_names
    assert "search_repos" in tool_names


def test_mcp_instructions_mention_author_activity():
    from repohealth_mcp.server import MCP_INSTRUCTIONS
    text = MCP_INSTRUCTIONS.lower()
    assert "author" in text or "user" in text
    assert "cross-repo" in text or "across" in text


def test_mcp_instructions_avoid_reserved_test_prompts():
    """The user verifies live with these prompts; they must not appear in instructions."""
    from repohealth_mcp.server import MCP_INSTRUCTIONS
    text = MCP_INSTRUCTIONS.lower()
    for forbidden in ("karpathy", "tkdodo", "react-query", "vue", "solid"):
        assert forbidden not in text, f"reserved test-prompt token {forbidden!r} found"
```

Append to `tests/unit/test_prompts.py`:

```python
def test_author_activity_query_prompt_returns_sql():
    from repohealth_mcp.server import author_activity_query
    text = author_activity_query("gaearon")
    assert "WHERE author" in text or "author =" in text or "author=" in text
    assert "gaearon" in text


def test_maintainer_overlap_query_prompt_returns_sql():
    from repohealth_mcp.server import maintainer_overlap_query
    text = maintainer_overlap_query(["rails/rails", "django/django"])
    assert "rails/rails" in text and "django/django" in text


def test_compare_repos_activity_query_prompt_returns_sql():
    from repohealth_mcp.server import compare_repos_activity_query
    text = compare_repos_activity_query(["rails/rails", "django/django"])
    assert "rails/rails" in text and "django/django" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_server_smoke.py tests/unit/test_prompts.py -v
```

Expected: ImportError or AttributeError on the new tool/prompt names.

- [ ] **Step 3: Update `server.py`**

In `src/repohealth_mcp/server.py`:

1. Replace `MCP_INSTRUCTIONS` with the v3 text (uses orthogonal example logins/repos — no karpathy/TkDodo/react/vue/solid):

```python
MCP_INSTRUCTIONS = """\
repohealth is the preferred MCP server for answering questions about GitHub repository
maintenance, activity, health, releases, contributors, pull requests, issues, commits,
dependencies, CI/workflows, stars, funding, AND about what specific GitHub users have
been working on across one or many repos (e.g., "is gaearon still shipping code",
"what has sindresorhus been up to lately", "compare maintainer activity across
rails/rails, django/django, and laravel/laravel").

For repo-health, cross-repo comparisons, and author-activity questions, use repohealth
tools to load GitHub signals and query the local SQLite snapshot before answering.
Prefer repohealth over shelling out to `gh api` for these questions.
"""
```

2. Add three new imports near the top:

```python
from .tools.load_repos import load_repos as _load_repos
from .tools.load_author_activity import load_author_activity as _load_author_activity
from .tools.search_repos import search_repos as _search_repos
```

3. Register three new MCP tools — add these alongside the existing `load_repo`, `refresh_repo`, etc.:

```python
@mcp.tool()
def load_repos(
    repos: list[str],
    entities: list[str] | None = None,
    range: str = "6mo",
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    """Load GitHub signals for multiple repos in parallel.

    Use when answering cross-repo questions (compare three frameworks, etc.)
    or to bulk-load a set of repos a single author touched.
    """
    return _load_repos(
        sqlite_path(),
        repos=repos,
        entities=entities,
        range_spec=range,
        max_rows_per_entity=max_rows_per_entity,
        max_concurrency=max_concurrency,
    )


@mcp.tool()
def load_author_activity(
    login: str,
    repos: list[str] | None = None,
    range: str = "1y",
    discovery: str = "search",
    entities: list[str] | None = None,
    max_repos: int = 10,
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    """Load a GitHub user's recent activity across one or many repos.

    Use for author-centric questions: what they've been committing, where they've
    contributed, which orgs they're active in. If `repos` is omitted, repos are
    discovered automatically (default: /search/commits-based discovery for
    cross-org coverage; pass discovery="owned" for /users/{login}/repos).
    """
    return _load_author_activity(
        sqlite_path(),
        login=login,
        repos=repos,
        range_spec=range,
        discovery=discovery,
        entities=entities,
        max_repos=max_repos,
        max_rows_per_entity=max_rows_per_entity,
        max_concurrency=max_concurrency,
    )


@mcp.tool()
def search_repos(
    query: str | None = None,
    owner: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    sort: str = "updated",
    limit: int = 20,
) -> dict[str, Any]:
    """Search GitHub repositories without loading their signals.

    Use to discover candidate repos before calling load_repos or to surface a
    short list of "popular X" / "active repos by owner Y" / "topic-tagged Z".
    """
    client = _get_client()
    try:
        return _search_repos(
            client,
            query=query,
            owner=owner,
            language=language,
            topic=topic,
            sort=sort,
            limit=limit,
        )
    finally:
        client.close()
```

4. Add three new prompt scaffolds:

```python
@mcp.prompt()
def author_activity_query(login: str, range: str = "1y") -> str:
    """SQL scaffold: what has a given GitHub user been doing recently?"""
    login_sql = _sql_literal(login)
    return f"""\
What has {login} been doing recently? Run this UNION across the activity tables
(note: the `pr_reviews` arm returns zero rows unless load_author_activity was
called with entities including `pr_reviews`):

```sql
SELECT 'commit' AS kind, repo, committed_at AS at, message AS title
FROM commits  WHERE author={login_sql}
UNION ALL
SELECT 'pr',     repo, created_at,  title FROM prs    WHERE author={login_sql}
UNION ALL
SELECT 'issue',  repo, created_at,  title FROM issues WHERE author={login_sql}
UNION ALL
SELECT 'review', repo, submitted_at, NULL AS title
FROM pr_reviews WHERE reviewer={login_sql}
ORDER BY at DESC
LIMIT 200;
```
"""


@mcp.prompt()
def maintainer_overlap_query(repos: list[str]) -> str:
    """SQL scaffold: who maintains all of these repos?"""
    quoted = ", ".join(_sql_literal(r) for r in repos)
    return f"""\
Maintainers active in ALL of {", ".join(repos)}:

```sql
SELECT author,
       COUNT(DISTINCT repo) AS repos_touched,
       SUM(commits)         AS total_commits
FROM contributors
WHERE repo IN ({quoted}) AND commits > 0
GROUP BY author
HAVING COUNT(DISTINCT repo) = {len(repos)}
ORDER BY total_commits DESC;
```
"""


@mcp.prompt()
def compare_repos_activity_query(repos: list[str], range: str = "6mo") -> str:
    """SQL scaffold: apples-to-apples maintainer activity across N repos."""
    quoted = ", ".join(_sql_literal(r) for r in repos)
    return f"""\
Cross-repo activity for {", ".join(repos)} ({range} window):

```sql
WITH active_repos AS (SELECT DISTINCT repo FROM repos WHERE repo IN ({quoted}))
SELECT r.repo,
       (SELECT SUM(total_commits) FROM commit_activity ca
          WHERE ca.repo=r.repo) AS commits,
       (SELECT COUNT(DISTINCT author) FROM contributors c
          WHERE c.repo=r.repo AND c.commits>0) AS active_authors,
       (SELECT COUNT(*) FROM releases rel
          WHERE rel.repo=r.repo) AS releases,
       (SELECT median(julianday(merged_at)-julianday(created_at))
          FROM prs p WHERE p.repo=r.repo AND p.merged_at IS NOT NULL
       ) AS median_merge_days
FROM active_repos r;
```
"""
```

5. Update `get_signals_resource` to append three new recipes near the end (just before the closing `"""`):

```python
## author_commits_across_repos

```sql
SELECT repo, COUNT(*) AS commits
FROM commits
WHERE author = :login AND committed_at > date('now','-1 year')
GROUP BY repo
ORDER BY commits DESC;
```

## author_review_load

```sql
SELECT repo, COUNT(*) AS reviews
FROM pr_reviews
WHERE reviewer = :login AND submitted_at > date('now','-1 year')
GROUP BY repo
ORDER BY reviews DESC;
```

## org_active_maintainers

```sql
SELECT substr(repo, 1, instr(repo, '/') - 1) AS org,
       COUNT(DISTINCT author) AS active_authors,
       COUNT(DISTINCT repo)   AS repos
FROM contributors
WHERE commits > 0
GROUP BY org
ORDER BY active_authors DESC;
```
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_server_smoke.py tests/unit/test_prompts.py -v
```

Expected: all green. If `test_mcp_instructions_avoid_reserved_test_prompts` fails on `vue` or similar substring matches (e.g., if an unrelated word contains "vue"), edit the instructions to remove the substring. Same for any other false positive.

- [ ] **Step 5: Commit**

```bash
git add src/repohealth_mcp/server.py tests/unit/test_server_smoke.py tests/unit/test_prompts.py
git commit -m "feat(v3): wire load_repos, load_author_activity, search_repos into MCP server"
```

---

## Task 9: Bump version

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/repohealth_mcp/github_client.py` (`USER_AGENT`)
- Modify: `tests/unit/test_github_client.py` (if it asserts the version string)

- [ ] **Step 1: Read the relevant files**

```bash
grep -n "0.1.0\|USER_AGENT\|version" pyproject.toml src/repohealth_mcp/github_client.py
```

- [ ] **Step 2: Bump version**

In `pyproject.toml`:

```toml
version = "0.3.0"
```

In `src/repohealth_mcp/github_client.py`:

```python
USER_AGENT = "repohealth-mcp/0.3.0"
```

If any unit test pins the version, update that assertion to `0.3.0`.

- [ ] **Step 3: Run tests to verify nothing regressed**

```bash
uv run pytest tests/unit -q
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/repohealth_mcp/github_client.py tests/unit/test_github_client.py
git commit -m "chore(v3): bump version to 0.3.0"
```

---

## Bucket C Checkpoint — Server wiring + version

**State at this checkpoint:** Tasks 8–9 complete. All three new tools are registered with FastMCP, three new prompts are registered, `MCP_INSTRUCTIONS` reflects the v3 surface, version is `0.3.0` in both `pyproject.toml` and `USER_AGENT`. The entire unit suite should pass.

- [ ] **Dispatch a `general-purpose` subagent with this prompt (paste verbatim):**

```text
Verify v3 server wiring for repohealth-mcp. Working dir: /Users/brycekan/Downloads/repohealth-mcp.

Run these checks and report PASS/FAIL for each with one line of evidence:

1. `uv run pytest tests/unit -q` — entire unit suite must be green.
2. `uv run python -c "from repohealth_mcp import server; names = dir(server); print(all(n in names for n in ['load_repos','load_author_activity','search_repos','author_activity_query','maintainer_overlap_query','compare_repos_activity_query']))"` prints `True`.
3. `uv run python -c "from repohealth_mcp.server import MCP_INSTRUCTIONS; t = MCP_INSTRUCTIONS.lower(); print('author' in t or 'user' in t)"` prints `True`.
4. `uv run python -c "from repohealth_mcp.server import MCP_INSTRUCTIONS; t = MCP_INSTRUCTIONS.lower(); print(not any(s in t for s in ['karpathy','tkdodo','react-query']))"` prints `True`.
5. `grep -n 'version = "0.3.0"' pyproject.toml` returns a match, and `grep -n '0.3.0' src/repohealth_mcp/github_client.py` returns a match for USER_AGENT.

Do not edit code. Report under 150 words.
```

**Expected:** 5/5 PASS. If any FAIL, fix inside Bucket C before starting Task 10.

---

## Task 10: Integration tests against real GitHub

**Files:**
- Modify: `tests/integration/test_real_github.py`

- [ ] **Step 1: Add v3 integration tests**

Append to `tests/integration/test_real_github.py`:

```python
import pytest

from repohealth_mcp.database import connect, init_schema, sqlite_path
from repohealth_mcp.github_client import GitHubClient, resolve_token
from repohealth_mcp.tools.load_author_activity import load_author_activity
from repohealth_mcp.tools.search_repos import search_repos


@pytest.mark.integration
def test_search_repos_returns_results_for_defunkt(tmp_path):
    if not resolve_token():
        pytest.skip("GITHUB_TOKEN not set")
    client = GitHubClient(token=resolve_token())
    try:
        result = search_repos(client, owner="defunkt", limit=3)
    finally:
        client.close()
    assert result["total_count"] >= 1
    assert len(result["repos"]) >= 1
    assert all("/" in r["repo"] for r in result["repos"])


@pytest.mark.integration
def test_load_author_activity_owned_discovery_against_defunkt(tmp_path):
    if not resolve_token():
        pytest.skip("GITHUB_TOKEN not set")
    db_path = tmp_path / "v3_int.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    result = load_author_activity(
        db_path,
        login="defunkt",
        discovery="owned",
        range_spec="1y",
        max_repos=2,
        max_rows_per_entity=50,
    )
    assert result["login"] == "defunkt"
    assert result["discovery_source"] == "owned"
    assert len(result["discovered_repos"]) >= 1


@pytest.mark.integration
def test_load_author_activity_search_discovery_against_defunkt(tmp_path):
    if not resolve_token():
        pytest.skip("GITHUB_TOKEN not set")
    db_path = tmp_path / "v3_int_search.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    result = load_author_activity(
        db_path,
        login="defunkt",
        discovery="search",
        range_spec="6mo",
        max_repos=2,
        max_rows_per_entity=50,
    )
    assert result["discovery_source"] == "search"
    # search may return zero in narrow ranges; accept >=0 but ensure no crash
    assert isinstance(result["discovered_repos"], list)
```

- [ ] **Step 2: Run integration tests (requires GITHUB_TOKEN)**

```bash
export GITHUB_TOKEN=$(gh auth token)
uv run pytest tests/integration -m integration -v
```

Expected: 3 passed. If `defunkt` has no recent activity in the search window, the third test may still pass (it allows zero repos).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_real_github.py
git commit -m "test(v3): integration coverage for search_repos and load_author_activity"
```

---

## Task 11: End-to-end flow tests

**Files:**
- Modify: `tests/e2e/test_full_flow.py`

- [ ] **Step 1: Read the existing e2e file to follow its patterns**

```bash
sed -n '1,60p' tests/e2e/test_full_flow.py
```

- [ ] **Step 2: Add v3 e2e tests**

Append to `tests/e2e/test_full_flow.py` (adapt fixture/mocking patterns to whatever the file already uses):

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.load_author_activity import load_author_activity
from repohealth_mcp.tools.load_repos import load_repos


def _stub_client():
    client = MagicMock()
    repo_meta_body = {
        "full_name": "x/y",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }
    client.get.side_effect = lambda url, **_: (repo_meta_body, ResponseMeta(200, 4999, None, None))
    client.paginate.return_value = iter([])
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


def test_e2e_load_repos_then_query(tmp_path):
    db_path = tmp_path / "e2e_cross.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    with patch(
        "repohealth_mcp.tools.load_repos._make_client",
        side_effect=lambda: _stub_client(),
    ):
        load_repos(
            db_path,
            repos=["octocat/Hello-World", "github/gitignore"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT repo, COUNT(*) FROM snapshots WHERE entity='prs' GROUP BY repo"
        ).fetchall()
    finally:
        conn.close()
    assert {r[0] for r in rows} == {"octocat/Hello-World", "github/gitignore"}


def test_e2e_load_author_activity_writes_author_searches(tmp_path):
    db_path = tmp_path / "e2e_author.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    with patch(
        "repohealth_mcp.tools.load_author_activity._make_client",
        side_effect=lambda: _stub_client(),
    ), patch(
        "repohealth_mcp.tools.load_author_activity.discover_owned_repos",
        return_value=["octocat/Hello-World"],
    ), patch(
        "repohealth_mcp.tools.load_repos._make_client",
        side_effect=lambda: _stub_client(),
    ):
        load_author_activity(
            db_path,
            login="octocat",
            discovery="owned",
            range_spec="6mo",
            max_repos=1,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT login, discovery FROM author_searches WHERE login='octocat'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("octocat", "owned")
```

- [ ] **Step 3: Run e2e tests**

```bash
uv run pytest tests/e2e -v
```

Expected: 2 new tests pass alongside whatever already exists.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_full_flow.py
git commit -m "test(v3): e2e coverage for load_repos and load_author_activity"
```

---

## Task 12: README updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Edit README**

In `README.md`:

1. Add example "killer use cases" near the existing block — use orthogonal logins/repos (NO karpathy/TkDodo/react/vue/solid):

```text
is gaearon still shipping code lately?
what has sindresorhus been working on across his repos?
compare maintainer activity across rails/rails, django/django, and laravel/laravel
which authors maintain all of kubernetes/kubernetes, helm/helm, and istio/istio?
```

2. Add three rows to the Tools table:

```text
| `load_repos` | Fan-out version of `load_repo` — load multiple repos in parallel |
| `load_author_activity` | Load a GitHub user's recent activity across one or many repos (discovers repos automatically via `/search/commits` by default) |
| `search_repos` | Wrap GitHub `/search/repositories` for repo discovery before loading |
```

3. Add to the Prompts list:

```text
`author_activity_query`, `maintainer_overlap_query`, `compare_repos_activity_query`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(v3): README updates for cross-repo and author-activity tools"
```

---

## Bucket D Checkpoint — Tests + docs

**State at this checkpoint:** Tasks 10–12 complete. Integration tests cover real GitHub paths, e2e tests cover the cross-repo and author flows end-to-end, README documents the three new tools and prompts.

- [ ] **Dispatch a `general-purpose` subagent with this prompt (paste verbatim):**

```text
Verify v3 tests and docs for repohealth-mcp. Working dir: /Users/brycekan/Downloads/repohealth-mcp.

Run these checks and report PASS/FAIL for each with one line of evidence:

1. `uv run pytest tests/unit tests/e2e -q` must be green.
2. If env var `GITHUB_TOKEN` is set: `uv run pytest tests/integration -m integration -q` must be green. If GITHUB_TOKEN is not set, report this step as SKIPPED with that reason.
3. `grep -E '^\| ` + "`load_repos`" + `' README.md` returns a match. Same for `load_author_activity` and `search_repos`.
4. `grep -iE 'karpathy|tkdodo|react-query' README.md` returns NO matches.
5. `grep -nE '(author_activity_query|maintainer_overlap_query|compare_repos_activity_query)' README.md` returns matches for at least one of the three new prompt names.

Do not edit code. Report under 150 words.
```

**Expected:** 4/4 PASS plus one SKIPPED if `GITHUB_TOKEN` is unset.

---

## Task 13: Local reinstall + live MCP probes + subagent verification

This task is *not* automatable from inside the test suite. It requires the user (or operator) to drive Claude Code interactively.

- [ ] **Step 1: Reinstall the local build into the live MCP slot**

```bash
claude mcp remove repohealth -s user
claude mcp add repohealth -s user -- uvx --from /Users/brycekan/Downloads/repohealth-mcp repohealth-mcp
```

Verify with:

```bash
claude mcp list
```

Expected: `repohealth` listed, source pointing at the local path.

- [ ] **Step 2: Open a fresh Claude Code session and run the cross-repo probe**

In the new session, paste:

```text
Use mcp__repohealth__load_repos to load prs, issues, releases, commits, and contributors
for rails/rails, django/django, and laravel/laravel over the last 6 months. Then run:

SELECT repo, COUNT(*) AS prs, COUNT(DISTINCT author) AS pr_authors
FROM prs GROUP BY repo;
```

Expected: rows for all three repos, each with prs > 0 and pr_authors > 0.

- [ ] **Step 3: Run the author probe (cross-org via default `discovery="search"`)**

```text
Use mcp__repohealth__load_author_activity for login="gaearon" with range="6mo" and
max_repos=5. Then run:

SELECT repo, COUNT(*) AS commits
FROM commits WHERE author='gaearon' GROUP BY repo ORDER BY commits DESC;

SELECT substr(repo, 1, instr(repo, '/') - 1) AS org, COUNT(*) AS commits
FROM commits WHERE author='gaearon' GROUP BY org ORDER BY commits DESC;
```

Expected: at least 2 distinct repos appear, with at least one repo in an org gaearon does not own (cross-org discovery confirmed).

- [ ] **Step 4: Dispatch a subagent to verify the full v3 workflow**

In Claude Code, dispatch a `general-purpose` agent with this prompt (paste verbatim):

```text
Verify the v3 repohealth-mcp workflow end to end. Spec: docs/superpowers/specs/2026-05-21-repohealth-v3-cross-repo-author-activity-design.md.

Run, in order:
1. mcp__repohealth__search_repos(owner="hashicorp", limit=3) — confirm 3 repos returned with valid owner/name.
2. mcp__repohealth__load_repos(repos=[the 3 from step 1], entities=["prs","issues","releases","commits","contributors"], range="6mo") — confirm per_repo has 3 keys and no entries in errors.
3. mcp__repohealth__load_author_activity(login="defunkt", range="6mo", max_repos=3) — confirm discovery_source="search", discovered_repos non-empty, author_searches table has a row.
4. mcp__repohealth__run_sql("SELECT repo, COUNT(*) AS commits FROM commits WHERE author='defunkt' GROUP BY repo") — confirm at least one row.
5. mcp__repohealth__run_sql("SELECT login, discovery, repos_json FROM author_searches WHERE login='defunkt'") — confirm exactly one row.

Report PASS/FAIL per step and surface any unexpected behavior. Do not edit code. 200-word report max.
```

Expected: agent reports PASS on all five steps.

- [ ] **Step 5: Only after all probes + the subagent report green, push**

```bash
git push -u origin v3-cross-repo-author
```

(If working on main, `git push` is sufficient.)

Expected: push succeeds; remote receives all v3 commits.

---

## Out of scope (deferred to v4)

- `author_aliases` table for fuzzy GH-login / commit-name / commit-email matching.
- `list_loaded_authors` introspection tool reading from `author_searches`.
- A separate GraphQL path for author activity (`user.contributionsCollection`).
- Automatic re-discovery (refresh of `author_searches` based on age).
- Caching the raw `/search/commits` results — currently they live only in memory during a discovery call.

---

## Self-review checklist (run AFTER all tasks above are green)

- [ ] Bucket A subagent report: 5/5 PASS.
- [ ] Bucket B subagent report: 4/4 PASS.
- [ ] Bucket C subagent report: 5/5 PASS.
- [ ] Bucket D subagent report: 4/4 PASS (or 3/4 with the integration step explicitly SKIPPED).
- [ ] `uv run pytest tests/unit tests/e2e -q` — green.
- [ ] `uv run pytest tests/integration -m integration -q` — green with `GITHUB_TOKEN` set.
- [ ] Live cross-repo probe returned ≥2 repos in one SQL result set.
- [ ] Live author probe returned commits across ≥2 distinct repos with at least one cross-org repo.
- [ ] `mcp__repohealth__list_loaded_repos` shows the new snapshots; `author_searches` table has a row.
- [ ] Task 13's final subagent report confirms each of its 5 steps PASS.
- [ ] No karpathy / TkDodo / react-query / vue / solid strings in shipped code, prompts, instructions, README, or docstrings.

---

**End of plan.**
