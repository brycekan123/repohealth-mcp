"""Loader for /repos/{repo}/pulls."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


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
        state="all",
        sort="created",
        direction="desc",
        per_page=100,
    )
    rows: list[dict] = []
    for item in iterator:
        created = item.get("created_at")
        # Sorted by created desc — once we cross the lower boundary, all remaining are older.
        if created and created[:10] < range_start:
            break
        if not date_in_range(created, range_start, range_end):
            continue
        row = _shape(item)
        row["repo"] = repo
        rows.append(row)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "prs", rows, pk=("repo", "number"))
    record_snapshot(
        conn,
        repo=repo,
        entity="prs",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="prs", row_count=len(rows), api_calls=max(1, len(rows) // 100 + 1))
