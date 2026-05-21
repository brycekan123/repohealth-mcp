"""Loader for /repos/{repo}/commits/{sha} file diffs."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import LoaderResult, record_snapshot, upsert_rows

_MAX_WORKERS = 8


def _shape(repo: str, sha: str, file: dict) -> dict:
    return {
        "repo": repo,
        "sha": sha,
        "filename": file.get("filename", ""),
        "status": file.get("status"),
        "additions": file.get("additions"),
        "deletions": file.get("deletions"),
        "changes": file.get("changes"),
    }


def _list_target_shas(
    conn: sqlite3.Connection, repo: str, range_start: str, range_end: str
) -> list[str]:
    cur = conn.execute(
        "SELECT sha FROM commits WHERE repo=? AND committed_at >= ? AND committed_at <= ?",
        (repo, f"{range_start}T00:00:00Z", f"{range_end}T23:59:59Z"),
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_files_for_commit(client, repo: str, sha: str) -> list[dict]:
    body, _ = client.get(f"/repos/{repo}/commits/{sha}")
    files = (body or {}).get("files") or []
    return [_shape(repo, sha, file) for file in files if file.get("filename")]


def load_commit_files(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    shas = _list_target_shas(conn, repo, range_start, range_end)
    if not shas:
        record_snapshot(
            conn,
            repo=repo,
            entity="commit_files",
            range_start=range_start,
            range_end=range_end,
            row_count=0,
        )
        return LoaderResult(entity="commit_files", row_count=0, api_calls=0)

    rows: list[dict] = []
    api_calls = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(shas))) as executor:
        futures = {executor.submit(_fetch_files_for_commit, client, repo, sha): sha for sha in shas}
        for future in as_completed(futures):
            api_calls += 1
            if len(rows) >= max_rows:
                continue
            rows.extend(future.result())
            rows = rows[:max_rows]

    upsert_rows(conn, "commit_files", rows, pk=("repo", "sha", "filename"))
    record_snapshot(
        conn,
        repo=repo,
        entity="commit_files",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="commit_files", row_count=len(rows), api_calls=api_calls)
