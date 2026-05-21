"""FastMCP server wiring."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .database import SCHEMA_SQL, connect, init_schema, sqlite_path
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
    """Parse a natural-language question into repos, entities, and range."""
    plan = _plan_data_load(question)
    return {"repos": plan.repos, "entities": plan.entities, "range": plan.range_spec}


@mcp.tool()
def check_coverage(repo: str, entity: str, range_start: str, range_end: str) -> dict[str, Any]:
    """Report whether a snapshot is already in the local cache."""
    return check_coverage_tool(
        sqlite_path(),
        repo=repo,
        entity=entity,
        range_start=range_start,
        range_end=range_end,
    )


@mcp.tool()
def load_repo(
    repo: str,
    entities: list[str] | None = None,
    range: str = "6mo",
    max_rows_per_entity: int = 500,
) -> dict[str, Any]:
    """Fetch missing GitHub data for one repo into local SQLite."""
    _path, conn = _get_db()
    client = _get_client()
    try:
        return _load_repo(
            conn,
            client,
            repo=repo,
            entities=list(entities or VALID_ENTITIES),
            range_spec=range,
            max_rows_per_entity=max_rows_per_entity,
        )
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
    """Drop cached rows for a repo/entity set, then reload them."""
    _path, conn = _get_db()
    client = _get_client()
    try:
        return _refresh_repo(
            conn,
            client,
            repo=repo,
            entities=list(entities or VALID_ENTITIES),
            range_spec=range,
            max_rows_per_entity=max_rows_per_entity,
        )
    finally:
        client.close()
        conn.close()


@mcp.tool()
def run_sql(query: str) -> dict[str, Any]:
    """Run a read-only SELECT/WITH query against the local snapshot SQLite."""
    try:
        return _run_sql(sqlite_path(), query)
    except RunSqlError as exc:
        return {"error": str(exc), "query": query}


@mcp.tool()
def get_loaded_tables() -> dict[str, Any]:
    """Return schema and row counts for local snapshot tables."""
    return _get_loaded_tables(sqlite_path())


@mcp.tool()
def list_loaded_repos() -> dict[str, Any]:
    """Return all cached repo/entity/range snapshots."""
    return _list_loaded_repos(sqlite_path())


def get_schema_resource() -> str:
    """Return SQL CREATE TABLE definitions."""
    return SCHEMA_SQL.strip()


def get_signals_resource() -> str:
    """Return canonical health-signal SQL recipes."""
    return """\
# Dep-Health Signals

## activity_commits_last_90d

```sql
SELECT repo, SUM(total_commits) AS commits_90d
FROM commit_activity
WHERE week_start_at > date('now', '-90 days')
GROUP BY repo
ORDER BY commits_90d DESC;
```

## median_pr_time_to_merge

```sql
SELECT repo, median(julianday(merged_at) - julianday(created_at)) AS median_days
FROM prs
WHERE merged_at IS NOT NULL
GROUP BY repo;
```

## release_cadence

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

```sql
SELECT repo,
       MAX(author_commits) * 100.0 / SUM(author_commits) AS top_contrib_pct
FROM (SELECT repo, author, SUM(commits) AS author_commits
      FROM contributors GROUP BY repo, author)
GROUP BY repo;
```

## active_maintainers_90d

```sql
SELECT repo, COUNT(DISTINCT author) AS active_maintainers
FROM contributors
WHERE week_start_at > date('now', '-90 days') AND commits > 0
GROUP BY repo;
```

## backlog_trajectory

```sql
SELECT repo,
       SUM(CASE WHEN state='open'   THEN 1 ELSE 0 END) AS open_count,
       SUM(CASE WHEN state='closed' THEN 1 ELSE 0 END) AS closed_count
FROM issues
GROUP BY repo;
```
"""


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@mcp.resource("repo://schema")
def _resource_schema() -> str:
    return get_schema_resource()


@mcp.resource("repo://signals")
def _resource_signals() -> str:
    return get_signals_resource()


@mcp.prompt()
def dep_health_query(repo: str) -> str:
    """SQL scaffold for a single-repo dep-health summary."""
    repo_sql = _sql_literal(repo)
    return f"""\
Run this query to summarize dep-health for {repo}:

```sql
SELECT
  (SELECT stars FROM repos WHERE repo={repo_sql}) AS stars,
  (SELECT julianday('now') - julianday(MAX(published_at))
     FROM releases WHERE repo={repo_sql}) AS days_since_release,
  (SELECT COUNT(DISTINCT author) FROM contributors
     WHERE repo={repo_sql} AND week_start_at > date('now', '-90 days') AND commits > 0
  ) AS active_maintainers_90d,
  (SELECT median(julianday(merged_at) - julianday(created_at))
     FROM prs WHERE repo={repo_sql} AND merged_at IS NOT NULL
  ) AS median_merge_days,
  (SELECT SUM(total_commits) FROM commit_activity
     WHERE repo={repo_sql} AND week_start_at > date('now', '-90 days')
  ) AS commits_90d;
```
"""


@mcp.prompt()
def compare_repos_query(repos: list[str]) -> str:
    """SQL scaffold for cross-repo maintainership comparison."""
    quoted = ", ".join(_sql_literal(repo) for repo in repos)
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
    repo_sql = _sql_literal(repo)
    return f"""\
Release cadence for {repo}:

```sql
WITH ordered AS (
  SELECT published_at,
         LAG(published_at) OVER (ORDER BY published_at) AS prev
  FROM releases
  WHERE repo={repo_sql} AND published_at IS NOT NULL
)
SELECT median(julianday(published_at) - julianday(prev)) AS median_days_between,
       MAX(published_at) AS most_recent_release
FROM ordered WHERE prev IS NOT NULL;
```
"""


@mcp.prompt()
def responsiveness_query(repo: str) -> str:
    """SQL scaffold for PR/issue response times."""
    repo_sql = _sql_literal(repo)
    return f"""\
Responsiveness signals for {repo}:

```sql
SELECT
  (SELECT median(julianday(merged_at) - julianday(created_at))
     FROM prs WHERE repo={repo_sql} AND merged_at IS NOT NULL
  ) AS median_pr_merge_days,
  (SELECT median(julianday(closed_at) - julianday(created_at))
     FROM issues WHERE repo={repo_sql} AND closed_at IS NOT NULL
  ) AS median_issue_close_days,
  (SELECT COUNT(*) FROM issues
     WHERE repo={repo_sql} AND state='open' AND created_at < date('now','-90 days')
  ) AS stale_open_issues_90d;
```
"""


@mcp.prompt()
def contributor_health_query(repo: str) -> str:
    """SQL scaffold for contributor concentration analysis."""
    repo_sql = _sql_literal(repo)
    return f"""\
Contributor concentration for {repo}:

```sql
WITH totals AS (
  SELECT author, SUM(commits) AS commits
  FROM contributors
  WHERE repo={repo_sql}
  GROUP BY author
)
SELECT author, commits,
       ROUND(100.0 * commits / SUM(commits) OVER (), 1) AS pct
FROM totals
ORDER BY commits DESC
LIMIT 10;
```
"""


def main() -> None:
    """Run the MCP server over stdio."""
    _path, conn = _get_db()
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
