from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.pr_review_comments import load_pr_review_comments


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


def test_load_pr_review_comments_writes_rows_per_pr(conn_with_prs) -> None:
    client = MagicMock()

    def _paginate(path, **_):
        if path == "/repos/o/r/pulls/1/comments":
            return iter(
                [
                    {
                        "id": 100,
                        "user": {"login": "alice"},
                        "body": "nit",
                        "path": "src/a.py",
                        "line": 42,
                        "position": 5,
                        "created_at": "2026-04-02T10:00:00Z",
                    },
                    {
                        "id": 101,
                        "user": {"login": "bob"},
                        "body": "lgtm",
                        "path": "src/a.py",
                        "line": 100,
                        "position": 30,
                        "created_at": "2026-04-02T11:00:00Z",
                    },
                ]
            )
        if path == "/repos/o/r/pulls/2/comments":
            return iter(
                [
                    {
                        "id": 200,
                        "user": {"login": "alice"},
                        "body": "consider X",
                        "path": "README.md",
                        "line": 3,
                        "position": 1,
                        "created_at": "2026-04-16T09:00:00Z",
                    }
                ]
            )
        return iter([])

    client.paginate.side_effect = _paginate
    result = load_pr_review_comments(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_prs.execute(
        "SELECT pr_number, reviewer, path, line FROM pr_review_comments "
        "ORDER BY pr_number, id"
    )
    assert cur.fetchall() == [
        (1, "alice", "src/a.py", 42),
        (1, "bob", "src/a.py", 100),
        (2, "alice", "README.md", 3),
    ]


def test_load_pr_review_comments_skips_when_no_prs(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_pr_review_comments(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0
    assert client.paginate.call_count == 0


def test_load_pr_review_comments_handles_pr_with_no_comments(conn_with_prs) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    result = load_pr_review_comments(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0


def test_load_pr_review_comments_uses_paginated_endpoint(conn_with_prs) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    load_pr_review_comments(
        conn_with_prs,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert client.paginate.call_args.kwargs["per_page"] == 100
