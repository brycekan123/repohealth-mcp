"""get_loaded_tables, list_loaded_repos, check_coverage tool wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..coverage import check_coverage
from ..database import EXPECTED_TABLES, connect_readonly


def get_loaded_tables(db_path: Path | str) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        tables = []
        for table in sorted(EXPECTED_TABLES):
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            tables.append({"name": table, "row_count": row_count, "columns": columns})
        return {"tables": tables}
    finally:
        conn.close()


def list_loaded_repos(db_path: Path | str) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        cur = conn.execute(
            "SELECT repo, entity, range_start, range_end, cached_at, row_count "
            "FROM snapshots ORDER BY repo, entity"
        )
        repos = [
            {
                "repo": row[0],
                "entity": row[1],
                "range_start": row[2],
                "range_end": row[3],
                "cached_at": row[4],
                "row_count": row[5],
            }
            for row in cur.fetchall()
        ]
        return {"repos": repos}
    finally:
        conn.close()


def check_coverage_tool(
    db_path: Path | str,
    *,
    repo: str,
    entity: str,
    range_start: str,
    range_end: str,
) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        status = check_coverage(
            conn,
            repo=repo,
            entity=entity,
            range_start=range_start,
            range_end=range_end,
        )
        return {
            "cached": status.cached,
            "cached_at": status.cached_at,
            "rows": status.rows,
            "age_seconds": status.age_seconds,
            "stale": status.stale,
        }
    finally:
        conn.close()
