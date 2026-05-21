"""Loader for top-level repo metadata."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import upsert_rows


def load_repo_meta(conn: sqlite3.Connection, client, *, repo: str) -> None:
    body, _meta = client.get(f"/repos/{repo}")
    row = {
        "repo": repo,
        "description": body.get("description"),
        "default_branch": body.get("default_branch"),
        "stars": body.get("stargazers_count", 0),
        "forks": body.get("forks_count", 0),
        "open_issues_count": body.get("open_issues_count", 0),
        "created_at": body.get("created_at"),
        "pushed_at": body.get("pushed_at"),
        "archived": 1 if body.get("archived") else 0,
        "disabled": 1 if body.get("disabled") else 0,
        "license": (body.get("license") or {}).get("spdx_id"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_rows(conn, "repos", [row], pk=("repo",))
