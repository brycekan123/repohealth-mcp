from datetime import datetime, timezone
from pathlib import Path

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import (
    LoaderResult,
    parse_range,
    record_snapshot,
    upsert_rows,
)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_upsert_rows_inserts_new(conn) -> None:
    rows = [
        {"repo": "a/b", "number": 1, "title": "first"},
        {"repo": "a/b", "number": 2, "title": "second"},
    ]
    upsert_rows(conn, "prs", rows, pk=("repo", "number"))
    cur = conn.execute("SELECT number, title FROM prs ORDER BY number")
    assert cur.fetchall() == [(1, "first"), (2, "second")]


def test_upsert_rows_updates_existing(conn) -> None:
    upsert_rows(
        conn,
        "prs",
        [{"repo": "a/b", "number": 1, "title": "old"}],
        pk=("repo", "number"),
    )
    upsert_rows(
        conn,
        "prs",
        [{"repo": "a/b", "number": 1, "title": "new"}],
        pk=("repo", "number"),
    )
    cur = conn.execute("SELECT title FROM prs WHERE number=1")
    assert cur.fetchone()[0] == "new"


def test_upsert_rows_no_op_on_empty(conn) -> None:
    upsert_rows(conn, "prs", [], pk=("repo", "number"))
    cur = conn.execute("SELECT COUNT(*) FROM prs")
    assert cur.fetchone()[0] == 0


def test_upsert_rows_handles_pk_only_rows(conn) -> None:
    upsert_rows(conn, "prs", [{"repo": "a/b", "number": 1}], pk=("repo", "number"))
    upsert_rows(conn, "prs", [{"repo": "a/b", "number": 1}], pk=("repo", "number"))
    cur = conn.execute("SELECT repo, number FROM prs")
    assert cur.fetchall() == [("a/b", 1)]


def test_upsert_rows_rejects_heterogeneous_keys(conn) -> None:
    rows = [
        {"repo": "a/b", "number": 1, "title": "first"},
        {"repo": "a/b", "number": 2, "state": "open"},
    ]

    with pytest.raises(ValueError, match="same keys"):
        upsert_rows(conn, "prs", rows, pk=("repo", "number"))


def test_record_snapshot_writes_row(conn) -> None:
    record_snapshot(
        conn,
        repo="a/b",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
        row_count=42,
    )
    cur = conn.execute("SELECT repo, entity, row_count FROM snapshots")
    assert cur.fetchone() == ("a/b", "prs", 42)


def test_record_snapshot_upserts_on_conflict(conn) -> None:
    record_snapshot(
        conn,
        repo="a/b",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
        row_count=10,
    )
    record_snapshot(
        conn,
        repo="a/b",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
        row_count=20,
    )
    cur = conn.execute("SELECT row_count FROM snapshots")
    rows = cur.fetchall()
    assert rows == [(20,)]


def test_parse_range_6mo() -> None:
    start, end = parse_range("6mo", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2025-11-20"


def test_parse_range_30d() -> None:
    start, end = parse_range("30d", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2026-04-20"


def test_parse_range_1y() -> None:
    start, end = parse_range("1y", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert end == "2026-05-20"
    assert start == "2025-05-20"


def test_parse_range_all() -> None:
    start, end = parse_range("all", now=datetime(2026, 5, 20, tzinfo=timezone.utc))
    assert start == "1970-01-01"


def test_parse_range_iso_pair() -> None:
    start, end = parse_range(
        "2025-01-15..2025-07-01",
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert start == "2025-01-15"
    assert end == "2025-07-01"


def test_parse_range_invalid_iso_pair_raises() -> None:
    with pytest.raises(ValueError):
        parse_range(
            "2025-99-99..2025-01-01",
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )


def test_parse_range_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_range("garbage", now=datetime(2026, 5, 20, tzinfo=timezone.utc))


def test_loader_result_dataclass() -> None:
    r = LoaderResult(entity="prs", row_count=287, api_calls=5)
    assert r.entity == "prs"
    assert r.row_count == 287
    assert r.api_calls == 5
