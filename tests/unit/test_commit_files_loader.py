from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.commit_files import load_commit_files


@pytest.fixture
def conn_with_commits(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    c.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "abc111", "alice", "a@x", "2026-04-10T10:00:00Z", "feat"),
    )
    c.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("o/r", "abc222", "bot", "b@x", "2026-04-12T10:00:00Z", "chore"),
    )
    return c


def test_load_commit_files_writes_one_row_per_changed_file(conn_with_commits) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r/commits/abc111":
            return (
                {
                    "files": [
                        {
                            "filename": "src/a.py",
                            "status": "modified",
                            "additions": 10,
                            "deletions": 2,
                            "changes": 12,
                        },
                        {
                            "filename": "tests/test_a.py",
                            "status": "added",
                            "additions": 50,
                            "deletions": 0,
                            "changes": 50,
                        },
                    ]
                },
                ResponseMeta(200, 4999, None, None),
            )
        if url == "/repos/o/r/commits/abc222":
            return (
                {
                    "files": [
                        {
                            "filename": "pyproject.toml",
                            "status": "modified",
                            "additions": 1,
                            "deletions": 1,
                            "changes": 2,
                        },
                    ]
                },
                ResponseMeta(200, 4999, None, None),
            )
        return ({"files": []}, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    result = load_commit_files(
        conn_with_commits,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 3
    cur = conn_with_commits.execute(
        "SELECT sha, filename, additions FROM commit_files ORDER BY sha, filename"
    )
    rows = cur.fetchall()
    assert rows == [
        ("abc111", "src/a.py", 10),
        ("abc111", "tests/test_a.py", 50),
        ("abc222", "pyproject.toml", 1),
    ]


def test_load_commit_files_skips_when_no_commits_cached(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    init_schema(conn)
    client = MagicMock()
    result = load_commit_files(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0
    assert client.get.call_count == 0


def test_load_commit_files_handles_commit_with_no_files(conn_with_commits) -> None:
    client = MagicMock()
    client.get.return_value = ({"files": []}, ResponseMeta(200, 4999, None, None))
    result = load_commit_files(
        conn_with_commits,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 0


def test_load_commit_files_respects_max_rows(conn_with_commits) -> None:
    client = MagicMock()
    client.get.return_value = (
        {
            "files": [
                {
                    "filename": f"f{i}.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                }
                for i in range(20)
            ]
        },
        ResponseMeta(200, 4999, None, None),
    )
    result = load_commit_files(
        conn_with_commits,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=10,
    )
    assert result.row_count == 10
