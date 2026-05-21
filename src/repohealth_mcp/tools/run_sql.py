"""Read-only SQL execution against the snapshot SQLite."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ..database import connect_readonly

_ROW_CAP = 1000
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


def run_sql(db_path: Path | str, query: str) -> dict[str, Any]:
    _validate(query)
    conn = connect_readonly(db_path)
    try:
        cur = conn.execute(query)
        columns = [description[0] for description in cur.description] if cur.description else []
        rows_raw = cur.fetchmany(_ROW_CAP)
        rows = [dict(zip(columns, row)) for row in rows_raw]
        return {"columns": columns, "rows": rows}
    except sqlite3.Error as exc:
        raise RunSqlError(f"sql error: {exc}") from exc
    finally:
        conn.close()
