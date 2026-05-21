from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.pr_reviews import load_pr_reviews


@pytest.fixture
def conn_with_prs(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    c.execute(
        "INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)",
        ("o/r", 1, "2026-04-01T00:00:00Z"),
    )
    c.execute(
        "INSERT INTO prs (repo, number, created_at) VALUES (?, ?, ?)",
        ("o/r", 2, "2026-04-15T00:00:00Z"),
    )
    return c


def test_load_pr_reviews_writes_rows_per_pr(conn_with_prs) -> None:
    client = MagicMock()

    def _paginate(path, **_):
        if path == "/repos/o/r/pulls/1/reviews":
            return iter(
                [
                    {
                        "id": 10,
                        "user": {"login": "carol"},
                        "state": "APPROVED",
                        "submitted_at": "2026-04-02T12:00:00Z",
                    },
                    {
                        "id": 11,
                        "user": {"login": "dave"},
                        "state": "COMMENTED",
                        "submitted_at": "2026-04-02T13:00:00Z",
                    },
                ]
            )
        if path == "/repos/o/r/pulls/2/reviews":
            return iter(
                [
                    {
                        "id": 20,
                        "user": {"login": "carol"},
                        "state": "CHANGES_REQUESTED",
                        "submitted_at": "2026-04-16T09:00:00Z",
                    }
                ]
            )
        return iter([])

    client.paginate.side_effect = _paginate

    result = load_pr_reviews(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_prs.execute(
        "SELECT pr_number, reviewer, state FROM pr_reviews ORDER BY pr_number, id"
    )
    rows = cur.fetchall()
    assert rows == [
        (1, "carol", "APPROVED"),
        (1, "dave", "COMMENTED"),
        (2, "carol", "CHANGES_REQUESTED"),
    ]


def test_load_pr_reviews_handles_pr_with_no_reviews(conn_with_prs) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    result = load_pr_reviews(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0


def test_load_pr_reviews_skips_when_no_prs_cached(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_pr_reviews(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0
    assert client.paginate.call_count == 0


def test_load_pr_reviews_uses_paginated_endpoint(conn_with_prs) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    load_pr_reviews(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert client.paginate.call_args.kwargs["per_page"] == 100


def test_load_pr_reviews_enforces_global_max_rows(conn_with_prs) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {
                "id": i,
                "user": {"login": "reviewer"},
                "state": "COMMENTED",
                "submitted_at": "2026-04-02T12:00:00Z",
            }
            for i in range(20)
        ]
    )
    result = load_pr_reviews(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=7,
    )
    assert result.row_count == 7
