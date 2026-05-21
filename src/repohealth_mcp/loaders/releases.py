"""Loader for /repos/{repo}/releases."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _shape(item: dict) -> dict:
    return {
        "repo": None,
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
    rows: list[dict] = []
    for item in client.paginate(f"/repos/{repo}/releases"):
        if not date_in_range(item.get("published_at") or item.get("created_at"), range_start, range_end):
            continue
        row = _shape(item)
        row["repo"] = repo
        rows.append(row)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "releases", rows, pk=("repo", "id"))
    record_snapshot(
        conn,
        repo=repo,
        entity="releases",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="releases", row_count=len(rows), api_calls=1)
