"""Read-only SQL execution against the snapshot SQLite."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ..database import connect_readonly

_DEFAULT_ROW_CAP = 200
_STRIP_COLUMNS = {"author_email"}
_ALLOWED_START = re.compile(r"^\s*(?:--[^\n]*\n|\s)*(select|with)\b", re.IGNORECASE)
_DENY_TOKENS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|replace)\b",
    re.IGNORECASE,
)


class RunSqlError(Exception):
    """Raised when a query violates safety rules or SQLite rejects it."""


def _validate(query: str) -> None:
    if not _ALLOWED_START.match(query):
        raise RunSqlError("only read-only SELECT or WITH queries are allowed")
    if _DENY_TOKENS.search(query):
        raise RunSqlError("query contains disallowed keyword (read-only mode)")


def _strip_indices(columns: list[str]) -> set[int]:
    """Drop columns in _STRIP_COLUMNS, but only if at least one other column remains.

    Preserves explicit single-column SELECTs like `SELECT author_email FROM commits`.
    """
    keep_count = sum(1 for c in columns if c not in _STRIP_COLUMNS)
    if keep_count == 0:
        return set()
    return {i for i, c in enumerate(columns) if c in _STRIP_COLUMNS}


def run_sql(
    db_path: Path | str,
    query: str,
    row_cap: int = _DEFAULT_ROW_CAP,
    offset: int = 0,
) -> dict[str, Any]:
    _validate(query)
    conn = connect_readonly(db_path)
    try:
        cur = conn.execute(query)
        all_columns = [d[0] for d in cur.description] if cur.description else []
        drop = _strip_indices(all_columns)
        columns = [c for i, c in enumerate(all_columns) if i not in drop]

        if offset > 0:
            cur.fetchmany(offset)
        rows_raw = cur.fetchmany(row_cap + 1)
        has_more = len(rows_raw) > row_cap
        rows = [
            [v for i, v in enumerate(row) if i not in drop]
            for row in rows_raw[:row_cap]
        ]

        result: dict[str, Any] = {"columns": columns, "rows": rows, "has_more": has_more}
        if has_more:
            result["note"] = (
                f"capped at {row_cap} rows (offset={offset}) — "
                f"call again with offset={offset + row_cap} for next page, "
                "or narrow with WHERE/LIMIT"
            )
        return result
    except sqlite3.Error as exc:
        raise RunSqlError(f"sql error: {exc}") from exc
    finally:
        conn.close()
