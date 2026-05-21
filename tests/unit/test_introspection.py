import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import record_snapshot
from repohealth_mcp.tools.introspection import (
    check_coverage_tool,
    get_loaded_tables,
    list_loaded_repos,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.execute("INSERT INTO prs (repo, number) VALUES ('a/b', 1)")
    conn.execute("INSERT INTO prs (repo, number) VALUES ('a/b', 2)")
    conn.execute("INSERT INTO issues (repo, number) VALUES ('a/b', 100)")
    record_snapshot(
        conn,
        repo="a/b",
        entity="prs",
        range_start="2025-11-20",
        range_end="2026-05-20",
        row_count=2,
        cached_at="2026-05-20T12:00:00Z",
    )
    record_snapshot(
        conn,
        repo="a/b",
        entity="issues",
        range_start="2025-11-20",
        range_end="2026-05-20",
        row_count=1,
        cached_at="2026-05-20T12:00:00Z",
    )
    conn.close()
    return path


def test_get_loaded_tables_lists_tables_with_counts(db_path) -> None:
    result = get_loaded_tables(db_path)
    tables = {table["name"]: table for table in result["tables"]}
    assert tables["prs"]["row_count"] == 2
    assert tables["issues"]["row_count"] == 1
    assert "columns" in tables["prs"]
    assert "repo" in tables["prs"]["columns"]


def test_list_loaded_repos_returns_snapshots(db_path) -> None:
    result = list_loaded_repos(db_path)
    repos = result["repos"]
    assert len(repos) == 2
    prs_entry = next(row for row in repos if row["entity"] == "prs")
    assert prs_entry["repo"] == "a/b"
    assert prs_entry["row_count"] == 2
    assert prs_entry["cached_at"] == "2026-05-20T12:00:00Z"


def test_check_coverage_tool_returns_dict(db_path) -> None:
    result = check_coverage_tool(
        db_path,
        repo="a/b",
        entity="prs",
        range_start="2025-11-20",
        range_end="2026-05-20",
    )
    assert result["cached"] is True
    assert result["rows"] == 2


def test_check_coverage_tool_miss(db_path) -> None:
    result = check_coverage_tool(
        db_path,
        repo="x/y",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
    )
    assert result["cached"] is False
    assert result["rows"] == 0


def test_check_coverage_includes_age_seconds_when_cached(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)

    from datetime import datetime, timedelta, timezone

    cached_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "prs", "2026-01-01", "2026-06-01", cached_at, 42),
    )
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r",
        entity="prs",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert out["cached"] is True
    assert 3500 < out["age_seconds"] < 3700
    assert out["stale"] is False


def test_check_coverage_marks_stale_after_threshold(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)

    from datetime import datetime, timedelta, timezone

    cached_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "prs", "2026-01-01", "2026-06-01", cached_at, 42),
    )
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r",
        entity="prs",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert out["stale"] is True


def test_check_coverage_returns_age_none_on_miss(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r",
        entity="prs",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert out["cached"] is False
    assert out["age_seconds"] is None
    assert out["stale"] is False


def test_check_coverage_handles_naive_cached_at(tmp_path) -> None:
    conn = connect(tmp_path / "x.sqlite")
    init_schema(conn)
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "prs", "2026-01-01", "2026-06-01", "2026-05-21T12:00:00", 42),
    )
    conn.close()
    out = check_coverage_tool(
        tmp_path / "x.sqlite",
        repo="o/r",
        entity="prs",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert out["cached"] is True
    assert isinstance(out["age_seconds"], int)
