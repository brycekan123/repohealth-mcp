"""Shared helpers for entity loaders: UPSERT, snapshot bookkeeping, range parsing."""

from __future__ import annotations

import calendar
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

_RANGE_REL_RE = re.compile(r"^(\d+)(d|mo|y)$")
_RANGE_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


@dataclass
class LoaderResult:
    entity: str
    row_count: int
    api_calls: int


def parse_range(spec: str, now: datetime) -> tuple[str, str]:
    """Convert range spec ('6mo', '30d', '1y', 'all', 'ISO..ISO') to ISO dates."""
    if spec == "all":
        return ("1970-01-01", now.date().isoformat())

    m = _RANGE_ISO_RE.match(spec)
    if m:
        start = date.fromisoformat(m.group(1))
        end = date.fromisoformat(m.group(2))
        return (start.isoformat(), end.isoformat())

    m = _RANGE_REL_RE.match(spec)
    if not m:
        raise ValueError(f"unrecognized range: {spec!r}")

    n, unit = int(m.group(1)), m.group(2)
    end_date = now.date()
    if unit == "d":
        start_date = end_date - timedelta(days=n)
    elif unit == "mo":
        start_date = _subtract_months(end_date, n)
    elif unit == "y":
        start_date = _subtract_months(end_date, n * 12)
    else:
        raise ValueError(f"unsupported unit {unit}")

    return (start_date.isoformat(), end_date.isoformat())


def date_in_range(value: str | None, range_start: str, range_end: str) -> bool:
    """Return whether an ISO date/datetime string falls within an inclusive date range."""
    if value is None:
        return False
    try:
        item_date = date.fromisoformat(value[:10])
        start = date.fromisoformat(range_start)
        end = date.fromisoformat(range_end)
    except ValueError:
        return False
    return start <= item_date <= end


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: Sequence[dict],
    pk: tuple[str, ...],
) -> None:
    """Insert rows; on PK conflict, update non-PK columns."""
    if not rows:
        return

    columns = list(rows[0].keys())
    expected_keys = set(columns)
    for index, row in enumerate(rows[1:], start=1):
        if set(row.keys()) != expected_keys:
            raise ValueError(
                f"all rows must have the same keys; row 0 has {sorted(expected_keys)!r} "
                f"but row {index} has {sorted(row.keys())!r}"
            )

    placeholders = ", ".join("?" for _ in columns)
    cols_sql = ", ".join(columns)
    non_pk_cols = [c for c in columns if c not in pk]
    pk_sql = ", ".join(pk)

    if non_pk_cols:
        update_sql = ", ".join(f"{c}=excluded.{c}" for c in non_pk_cols)
        conflict_sql = f"DO UPDATE SET {update_sql}"
    else:
        conflict_sql = "DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_sql}) {conflict_sql}"
    )
    values = [tuple(row.get(c) for c in columns) for row in rows]
    conn.executemany(sql, values)


def record_snapshot(
    conn: sqlite3.Connection,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
    row_count: int,
    cached_at: str | None = None,
) -> None:
    """Write or replace the bookkeeping row for a (repo, entity, range) slice."""
    if cached_at is None:
        cached_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo, entity, range_start, range_end)
        DO UPDATE SET cached_at=excluded.cached_at, row_count=excluded.row_count
        """,
        (repo, entity, range_start, range_end, cached_at, row_count),
    )


