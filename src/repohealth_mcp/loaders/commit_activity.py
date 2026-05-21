"""Loader for /repos/{repo}/stats/commit_activity."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _shape(week_obj: dict) -> dict:
    iso = datetime.fromtimestamp(week_obj["week"], tz=timezone.utc).isoformat()
    days = week_obj.get("days", [0] * 7)
    sun, mon, tue, wed, thu, fri, sat = (days + [0] * 7)[:7]
    return {
        "repo": None,
        "week_start_at": iso,
        "total_commits": week_obj.get("total", 0),
        "mon": mon,
        "tue": tue,
        "wed": wed,
        "thu": thu,
        "fri": fri,
        "sat": sat,
        "sun": sun,
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

    rows = []
    for week_obj in body:
        row = _shape(week_obj)
        if not date_in_range(row["week_start_at"], range_start, range_end):
            continue
        row["repo"] = repo
        rows.append(row)

    upsert_rows(conn, "commit_activity", rows, pk=("repo", "week_start_at"))
    record_snapshot(
        conn,
        repo=repo,
        entity="commit_activity",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="commit_activity", row_count=len(rows), api_calls=1)
