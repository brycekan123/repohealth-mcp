"""Loader for /repos/{repo}/stats/contributors."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


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
            commits = week.get("c", 0)
            additions = week.get("a", 0)
            deletions = week.get("d", 0)
            if commits == 0 and additions == 0 and deletions == 0:
                continue

            week_start_at = datetime.fromtimestamp(week["w"], tz=timezone.utc).isoformat()
            if not date_in_range(week_start_at, range_start, range_end):
                continue

            rows.append(
                {
                    "repo": repo,
                    "author": author,
                    "week_start_at": week_start_at,
                    "commits": commits,
                    "additions": additions,
                    "deletions": deletions,
                }
            )

    upsert_rows(conn, "contributors", rows, pk=("repo", "author", "week_start_at"))
    record_snapshot(
        conn,
        repo=repo,
        entity="contributors",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="contributors", row_count=len(rows), api_calls=1)
