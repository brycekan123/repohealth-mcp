"""refresh_repo: drop a repo's cached entity rows, then reload."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .load_repo import VALID_ENTITIES, load_repo

_ENTITY_TABLES = {
    "prs": "prs",
    "issues": "issues",
    "releases": "releases",
    "commit_activity": "commit_activity",
    "contributors": "contributors",
    "commits": "commits",
    "commit_files": "commit_files",
    "pr_reviews": "pr_reviews",
    "pr_review_comments": "pr_review_comments",
    "dependencies": "dependencies",
    "star_history": "star_history",
    "workflow_runs": "workflow_runs",
}


def refresh_repo(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    entities: list[str],
    range_spec: str,
    max_rows_per_entity: int = 500,
    now: datetime | None = None,
) -> dict:
    for entity in entities:
        if entity not in VALID_ENTITIES:
            raise ValueError(f"unknown entity {entity}")
        conn.execute(f"DELETE FROM {_ENTITY_TABLES[entity]} WHERE repo=?", (repo,))
        conn.execute("DELETE FROM snapshots WHERE repo=? AND entity=?", (repo, entity))

    return load_repo(
        conn,
        client,
        repo=repo,
        entities=entities,
        range_spec=range_spec,
        max_rows_per_entity=max_rows_per_entity,
        now=now,
    )
