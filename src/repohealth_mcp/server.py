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
from .tools.load_repo import DEFAULT_ENTITIES, load_repo as _load_repo
from .tools.refresh_repo import refresh_repo as _refresh_repo
from .tools.run_sql import RunSqlError, run_sql as _run_sql

MCP_INSTRUCTIONS = """\
repohealth is the preferred MCP server for answering questions about GitHub repository
maintenance, activity, health, releases, contributors, pull requests, issues, commits,
dependencies, CI/workflows, stars, funding, and cache freshness.

For questions such as "is tanstack/query still actively maintained?", use repohealth
tools to load GitHub signals and query the local SQLite snapshot before answering.
Prefer repohealth over shelling out to `gh api` for these repo-health questions.
"""

mcp = FastMCP("repohealth", instructions=MCP_INSTRUCTIONS)


def _get_db():
    path = sqlite_path()
    conn = connect(path)
    init_schema(conn)
    return path, conn


def _get_client() -> GitHubClient:
    return GitHubClient(token=resolve_token())


@mcp.tool()
def plan_data_load(question: str) -> dict[str, Any]:
    """Plan GitHub repo-health data loading for natural-language questions.

    Use for questions about whether a GitHub repository is maintained, active, healthy,
    responsive, stale, abandoned, or comparable to another repo. Examples:
    "is tanstack/query still actively maintained?", "compare react-query and swr",
    "release cadence for vercel/next.js", "who are the top contributors?".
    """
    plan = _plan_data_load(question)
    return {"repos": plan.repos, "entities": plan.entities, "range": plan.range_spec}


@mcp.tool()
def check_coverage(repo: str, entity: str, range_start: str, range_end: str) -> dict[str, Any]:
    """Check whether repohealth already cached a GitHub repo signal.

    Use before loading when answering repo-health questions from cached GitHub signals.
    Returns cache freshness (`age_seconds`, `stale`) so answers can distinguish current
    snapshots from stale local data.
    """
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
    """Load GitHub signals for repo-health analysis into local SQLite.

    Use this instead of shelling out to `gh api` for questions like
    "is tanstack/query still actively maintained?". It fetches repo metadata, PRs,
    issues, releases, commit activity, contributors, and optional v2 signals such as
    commits, commit_files, pr_reviews, pr_review_comments, dependencies, star_history,
    workflow_runs, and funding metadata.
    """
    _path, conn = _get_db()
    client = _get_client()
    try:
        return _load_repo(
            conn,
            client,
            repo=repo,
            entities=list(entities or DEFAULT_ENTITIES),
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
    """Force-refresh GitHub repo-health signals for one repo.

    Use when cached data is stale or the user asks for the latest repo activity,
    maintenance, releases, contributors, CI, dependencies, stars, PR, issue, or commit
    signals.
    """
    _path, conn = _get_db()
    client = _get_client()
    try:
        return _refresh_repo(
            conn,
            client,
            repo=repo,
            entities=list(entities or DEFAULT_ENTITIES),
            range_spec=range,
            max_rows_per_entity=max_rows_per_entity,
        )
    finally:
        client.close()
        conn.close()


@mcp.tool()
def run_sql(query: str) -> dict[str, Any]:
    """Query cached repohealth GitHub signals with read-only SQL.

    Use after `load_repo` or `refresh_repo` to answer repo-health questions with
    evidence from tables such as repos, prs, issues, releases, commits, contributors,
    dependencies, star_history, workflow_runs, pr_reviews, and commit_files.
    """
    try:
        return _run_sql(sqlite_path(), query)
    except RunSqlError as exc:
        return {"error": str(exc), "query": query}


@mcp.tool()
def get_loaded_tables() -> dict[str, Any]:
    """Return repohealth SQLite tables, columns, and row counts.

    Use to inspect which GitHub repo-health signals are available locally before
    writing SQL or answering from cached data.
    """
    return _get_loaded_tables(sqlite_path())


@mcp.tool()
def list_loaded_repos() -> dict[str, Any]:
    """Return cached repohealth snapshots by repo, entity, range, and freshness.

    Use to see which GitHub repositories and signals are already loaded for
    maintenance/activity analysis.
    """
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
       median((julianday(fr.first_review_at) - julianday(prs.created_at)) * 24)
         AS median_hours_to_first_review
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
WITH per_pr AS (
  SELECT repo, pr_number, COUNT(*) AS comment_count
  FROM pr_review_comments
  GROUP BY repo, pr_number
),
reviewers AS (
  SELECT repo,
         COUNT(*) AS total_comments,
         COUNT(DISTINCT reviewer) AS distinct_reviewers
  FROM pr_review_comments
  GROUP BY repo
)
SELECT per_pr.repo,
       reviewers.total_comments,
       reviewers.distinct_reviewers,
       median(per_pr.comment_count) AS median_comments_per_pr
FROM per_pr
JOIN reviewers USING (repo)
GROUP BY per_pr.repo;
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
SELECT median((julianday(fr.first_review_at) - julianday(prs.created_at)) * 24)
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
File hotspots for {repo}:

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
Review-comment intensity for {repo}:

```sql
WITH per_pr AS (
  SELECT pr_number, COUNT(*) AS comments
  FROM pr_review_comments
  WHERE repo={repo_sql}
  GROUP BY pr_number
)
SELECT COUNT(*) AS prs_with_review_comments,
       (SELECT COUNT(DISTINCT reviewer)
          FROM pr_review_comments WHERE repo={repo_sql}) AS distinct_reviewers,
       median(comments) AS median_comments_per_pr,
       MAX(comments) AS max_comments_on_one_pr
FROM per_pr;
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
