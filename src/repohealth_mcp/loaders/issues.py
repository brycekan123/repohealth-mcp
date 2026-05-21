"""Loader for /repos/{repo}/issues, filtering out PRs."""

from __future__ import annotations

import json
import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _shape(item: dict) -> dict | None:
    if item.get("pull_request") is not None:
        return None

    return {
        "repo": None,
        "number": item["number"],
        "title": item.get("title"),
        "author": (item.get("user") or {}).get("login"),
        "state": item.get("state"),
        "state_reason": item.get("state_reason"),
        "labels": json.dumps([label.get("name") for label in item.get("labels", [])]),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "comments_count": item.get("comments"),
    }


def load_issues(
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
        f"/repos/{repo}/issues",
        state="all",
        sort="created",
        direction="desc",
        per_page=100,
    ):
        created = item.get("created_at")
        # Sorted by created desc — once we cross the lower boundary, all remaining are older.
        if created and created[:10] < range_start:
            break
        shaped = _shape(item)
        if shaped is None:
            continue
        if not date_in_range(shaped.get("created_at"), range_start, range_end):
            continue
        shaped["repo"] = repo
        rows.append(shaped)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "issues", rows, pk=("repo", "number"))
    record_snapshot(
        conn,
        repo=repo,
        entity="issues",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="issues", row_count=len(rows), api_calls=max(1, len(rows) // 100 + 1))
