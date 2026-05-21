"""Snapshot-table-based coverage check for the cache layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class CoverageStatus:
    cached: bool
    cached_at: str | None
    rows: int


def check_coverage(
    conn: sqlite3.Connection,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
) -> CoverageStatus:
    cur = conn.execute(
        """
        SELECT cached_at, row_count FROM snapshots
        WHERE repo=? AND entity=? AND range_start=? AND range_end=?
        """,
        (repo, entity, range_start, range_end),
    )
    row = cur.fetchone()
    if row is None:
        return CoverageStatus(cached=False, cached_at=None, rows=0)
    return CoverageStatus(cached=True, cached_at=row[0], rows=row[1])
