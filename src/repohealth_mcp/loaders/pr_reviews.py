"""Loader for /repos/{repo}/pulls/{number}/reviews."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import LoaderResult, record_snapshot, upsert_rows

_MAX_WORKERS = 8


def _shape(repo: str, pr_number: int, review: dict) -> dict:
    return {
        "repo": repo,
        "pr_number": pr_number,
        "id": review["id"],
        "reviewer": (review.get("user") or {}).get("login"),
        "state": review.get("state"),
        "submitted_at": review.get("submitted_at"),
    }


def _list_target_prs(
    conn: sqlite3.Connection, repo: str, range_start: str, range_end: str
) -> list[int]:
    cur = conn.execute(
        "SELECT number FROM prs WHERE repo=? AND created_at >= ? AND created_at <= ?",
        (repo, f"{range_start}T00:00:00Z", f"{range_end}T23:59:59Z"),
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_reviews_for_pr(client, repo: str, pr_number: int) -> list[dict]:
    return [
        _shape(repo, pr_number, review)
        for review in client.paginate(f"/repos/{repo}/pulls/{pr_number}/reviews", per_page=100)
    ]


def load_pr_reviews(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    pr_numbers = _list_target_prs(conn, repo, range_start, range_end)
    if not pr_numbers:
        record_snapshot(
            conn,
            repo=repo,
            entity="pr_reviews",
            range_start=range_start,
            range_end=range_end,
            row_count=0,
        )
        return LoaderResult(entity="pr_reviews", row_count=0, api_calls=0)

    rows: list[dict] = []
    api_calls = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(pr_numbers))) as executor:
        futures = {executor.submit(_fetch_reviews_for_pr, client, repo, n): n for n in pr_numbers}
        for future in as_completed(futures):
            api_calls += 1
            if len(rows) >= max_rows:
                continue
            rows.extend(future.result())
            rows = rows[:max_rows]

    upsert_rows(conn, "pr_reviews", rows, pk=("repo", "pr_number", "id"))
    record_snapshot(
        conn,
        repo=repo,
        entity="pr_reviews",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="pr_reviews", row_count=len(rows), api_calls=api_calls)
