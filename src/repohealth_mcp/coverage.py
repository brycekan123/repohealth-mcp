"""Snapshot-table-based coverage check for the cache layer."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

STALE_AFTER_SECONDS = 7 * 24 * 60 * 60


@dataclass
class CoverageStatus:
    cached: bool
    cached_at: str | None
    rows: int
    age_seconds: int | None
    stale: bool


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
        return CoverageStatus(cached=False, cached_at=None, rows=0, age_seconds=None, stale=False)

    cached_at, rows = row
    age_seconds = None
    stale = False
    try:
        ts = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_seconds = int((datetime.now(timezone.utc) - ts).total_seconds())
        stale = age_seconds > STALE_AFTER_SECONDS
    except (ValueError, AttributeError, TypeError):
        pass
    return CoverageStatus(
        cached=True,
        cached_at=cached_at,
        rows=rows,
        age_seconds=age_seconds,
        stale=stale,
    )
