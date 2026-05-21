"""Loader for /repos/{repo}/commits."""

from __future__ import annotations

import sqlite3

from .base import LoaderResult, date_in_range, record_snapshot, upsert_rows


def _shape(item: dict) -> dict:
    commit = item.get("commit") or {}
    commit_author = commit.get("author") or {}
    gh_user = (item.get("author") or {}).get("login")
    return {
        "repo": None,
        "sha": item["sha"],
        "author": gh_user or commit_author.get("name"),
        "author_email": commit_author.get("email"),
        "committed_at": commit_author.get("date"),
        "message": commit.get("message"),
    }


def load_commits(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    iterator = client.paginate(
        f"/repos/{repo}/commits",
        per_page=100,
        since=f"{range_start}T00:00:00Z",
        until=f"{range_end}T23:59:59Z",
    )
    rows: list[dict] = []
    for item in iterator:
        row = _shape(item)
        if not date_in_range(row["committed_at"], range_start, range_end):
            continue
        row["repo"] = repo
        rows.append(row)
        if len(rows) >= max_rows:
            break

    upsert_rows(conn, "commits", rows, pk=("repo", "sha"))
    record_snapshot(
        conn,
        repo=repo,
        entity="commits",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="commits", row_count=len(rows), api_calls=max(1, len(rows) // 100 + 1))
