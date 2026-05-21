"""Loader for /repos/{repo}/actions/runs."""

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
    start, end = _parse_iso(started), _parse_iso(ended)
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds()
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
    record_snapshot(
        conn,
        repo=repo,
        entity="workflow_runs",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="workflow_runs", row_count=len(rows), api_calls=api_calls)
