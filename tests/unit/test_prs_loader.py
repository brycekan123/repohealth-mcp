import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.prs import load_prs

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_prs():
    fixture = json.loads((FIXTURES / "prs_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_prs_writes_all_rows(conn, client_with_prs) -> None:
    result = load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM prs")
    assert cur.fetchone()[0] == 3


def test_load_prs_extracts_author(conn, client_with_prs) -> None:
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM prs WHERE number=1")
    assert cur.fetchone()[0] == "alice"


def test_load_prs_handles_null_user(conn, client_with_prs) -> None:
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM prs WHERE number=3")
    assert cur.fetchone()[0] is None


def test_load_prs_extracts_base_branch(conn, client_with_prs) -> None:
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT base_branch FROM prs WHERE number=2")
    assert cur.fetchone()[0] == "develop"


def test_load_prs_preserves_null_merged_at(conn, client_with_prs) -> None:
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT merged_at FROM prs WHERE number=3")
    assert cur.fetchone()[0] is None


def test_load_prs_writes_snapshot(conn, client_with_prs) -> None:
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE repo='o/r' AND entity='prs'")
    assert cur.fetchone()[0] == 3


def test_load_prs_paginates_sorted_by_created_desc(conn, client_with_prs) -> None:
    """Sort by created desc so we can break early at the range boundary."""
    load_prs(
        conn,
        client_with_prs,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    call_kwargs = client_with_prs.paginate.call_args.kwargs
    assert call_kwargs.get("state") == "all"
    assert call_kwargs.get("sort") == "created"
    assert call_kwargs.get("direction") == "desc"
    # since= is an updated_at filter; using it with a created_at filter causes
    # excessive pagination on repos with many stale PRs. It must not be passed.
    assert "since" not in call_kwargs


def test_load_prs_stops_paginating_after_pr_older_than_range(conn) -> None:
    """With desc-by-created sort, the loader must stop on the first too-old PR."""
    yielded: list[int] = []

    def fake_paginate(_path, **_kw):
        items = [
            {"number": 1, "user": {"login": "u"}, "state": "open", "draft": False,
             "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
             "closed_at": None, "merged_at": None, "comments": 0, "base": {"ref": "main"}},
            {"number": 2, "user": {"login": "u"}, "state": "open", "draft": False,
             "created_at": "2024-01-01T00:00:00Z", "updated_at": "2026-05-15T00:00:00Z",
             "closed_at": None, "merged_at": None, "comments": 0, "base": {"ref": "main"}},
            {"number": 3, "user": {"login": "u"}, "state": "open", "draft": False,
             "created_at": "2023-01-01T00:00:00Z", "updated_at": "2026-05-15T00:00:00Z",
             "closed_at": None, "merged_at": None, "comments": 0, "base": {"ref": "main"}},
        ]
        for item in items:
            yielded.append(item["number"])
            yield item

    client = MagicMock()
    client.paginate.side_effect = fake_paginate

    result = load_prs(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 1  # only PR #1 in range
    # Must have stopped at #2 (out of range) — never seen #3.
    assert yielded == [1, 2], f"expected to stop after #2, yielded {yielded}"


def test_load_prs_filters_created_at_to_range(conn) -> None:
    client = MagicMock()
    # Sorted by created desc — newer PR first, then the out-of-range one.
    client.paginate.return_value = iter(
        [
            {
                "number": 2,
                "title": "in range",
                "user": {"login": "u"},
                "state": "open",
                "draft": False,
                "created_at": "2026-02-01T00:00:00Z",
                "updated_at": "2026-02-01T00:00:00Z",
                "closed_at": None,
                "merged_at": None,
                "comments": 0,
                "base": {"ref": "main"},
            },
            {
                "number": 1,
                "title": "old",
                "user": {"login": "u"},
                "state": "closed",
                "draft": False,
                "created_at": "2025-12-31T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "closed_at": "2026-01-02T00:00:00Z",
                "merged_at": None,
                "comments": 0,
                "base": {"ref": "main"},
            },
        ]
    )
    result = load_prs(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=10,
    )
    assert result.row_count == 1
    cur = conn.execute("SELECT number FROM prs")
    assert cur.fetchall() == [(2,)]
