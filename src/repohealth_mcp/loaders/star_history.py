"""Loader for /repos/{repo}/stargazers with timestamped star events."""

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
        f"/repos/{repo}/stargazers",
        per_page=100,
        media_type=_MEDIA,
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
    record_snapshot(
        conn,
        repo=repo,
        entity="star_history",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(
        entity="star_history",
        row_count=len(rows),
        api_calls=max(1, len(rows) // 100 + 1),
    )
