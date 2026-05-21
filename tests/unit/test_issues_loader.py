import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.issues import load_issues

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_issues():
    fixture = json.loads((FIXTURES / "issues_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_issues_filters_out_prs(conn, client_with_issues) -> None:
    result = load_issues(
        conn,
        client_with_issues,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 2
    cur = conn.execute("SELECT number FROM issues ORDER BY number")
    assert [r[0] for r in cur.fetchall()] == [100, 102]


def test_load_issues_serializes_labels_as_json(conn, client_with_issues) -> None:
    load_issues(
        conn,
        client_with_issues,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT labels FROM issues WHERE number=100")
    labels = json.loads(cur.fetchone()[0])
    assert labels == ["bug", "p1"]


def test_load_issues_handles_empty_labels(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {
                "number": 1,
                "title": "x",
                "user": {"login": "u"},
                "state": "open",
                "state_reason": None,
                "labels": [],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
        ]
    )
    load_issues(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT labels FROM issues WHERE number=1")
    assert json.loads(cur.fetchone()[0]) == []


def test_load_issues_handles_null_state_reason(conn, client_with_issues) -> None:
    load_issues(
        conn,
        client_with_issues,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT state_reason FROM issues WHERE number=100")
    assert cur.fetchone()[0] is None


def test_load_issues_writes_snapshot(conn, client_with_issues) -> None:
    load_issues(
        conn,
        client_with_issues,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='issues' AND repo='o/r'")
    assert cur.fetchone()[0] == 2


def test_load_issues_caps_after_filtering_prs(conn) -> None:
    raw_items = [
        {
            "number": 1,
            "title": "pr",
            "user": {"login": "u"},
            "state": "closed",
            "state_reason": None,
            "labels": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": "2026-01-01T00:00:00Z",
            "comments": 0,
            "pull_request": {"url": "https://example/pulls/1"},
        },
        {
            "number": 2,
            "title": "also pr",
            "user": {"login": "u"},
            "state": "closed",
            "state_reason": None,
            "labels": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": "2026-01-01T00:00:00Z",
            "comments": 0,
            "pull_request": {"url": "https://example/pulls/2"},
        },
        {
            "number": 3,
            "title": "real issue",
            "user": {"login": "u"},
            "state": "open",
            "state_reason": None,
            "labels": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": None,
            "comments": 0,
        },
        {
            "number": 4,
            "title": "second issue",
            "user": {"login": "u"},
            "state": "open",
            "state_reason": None,
            "labels": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": None,
            "comments": 0,
        },
    ]
    client = MagicMock()

    def _paginate(*_, max_rows=None, **__):
        return iter(raw_items[:max_rows] if max_rows is not None else raw_items)

    client.paginate.side_effect = _paginate

    result = load_issues(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=2,
    )

    assert result.row_count == 2
    cur = conn.execute("SELECT number FROM issues ORDER BY number")
    assert [row[0] for row in cur.fetchall()] == [3, 4]


def test_load_issues_filters_created_at_to_range(conn) -> None:
    client = MagicMock()
    # Sorted by created desc — newer first, then the old one.
    client.paginate.return_value = iter(
        [
            {
                "number": 2,
                "title": "in range",
                "user": {"login": "u"},
                "state": "open",
                "state_reason": None,
                "labels": [],
                "created_at": "2026-02-01T00:00:00Z",
                "updated_at": "2026-02-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
            {
                "number": 1,
                "title": "old",
                "user": {"login": "u"},
                "state": "open",
                "state_reason": None,
                "labels": [],
                "created_at": "2025-12-31T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
        ]
    )
    result = load_issues(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=10,
    )
    assert result.row_count == 1
    cur = conn.execute("SELECT number FROM issues")
    assert cur.fetchall() == [(2,)]


def test_load_issues_paginates_sorted_by_created_desc(conn, client_with_issues) -> None:
    """Sort by created desc + no `since` so we can break early at the range boundary."""
    load_issues(
        conn,
        client_with_issues,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    call_kwargs = client_with_issues.paginate.call_args.kwargs
    assert call_kwargs.get("state") == "all"
    assert call_kwargs.get("sort") == "created"
    assert call_kwargs.get("direction") == "desc"
    assert "since" not in call_kwargs


def test_load_issues_stops_paginating_after_issue_older_than_range(conn) -> None:
    """With desc-by-created sort, the loader must stop on the first too-old issue."""
    yielded: list[int] = []

    def fake_paginate(_path, **_kw):
        items = [
            {"number": 1, "user": {"login": "u"}, "state": "open", "state_reason": None,
             "labels": [], "created_at": "2026-05-01T00:00:00Z",
             "updated_at": "2026-05-01T00:00:00Z", "closed_at": None, "comments": 0},
            {"number": 2, "user": {"login": "u"}, "state": "open", "state_reason": None,
             "labels": [], "created_at": "2024-01-01T00:00:00Z",
             "updated_at": "2026-05-15T00:00:00Z", "closed_at": None, "comments": 0},
            {"number": 3, "user": {"login": "u"}, "state": "open", "state_reason": None,
             "labels": [], "created_at": "2023-01-01T00:00:00Z",
             "updated_at": "2026-05-15T00:00:00Z", "closed_at": None, "comments": 0},
        ]
        for item in items:
            yielded.append(item["number"])
            yield item

    client = MagicMock()
    client.paginate.side_effect = fake_paginate

    result = load_issues(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 1
    assert yielded == [1, 2], f"expected to stop after #2, yielded {yielded}"
