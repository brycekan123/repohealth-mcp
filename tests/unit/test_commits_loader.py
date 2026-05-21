import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.commits import load_commits

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_commits():
    fixture = json.loads((FIXTURES / "commits_sample.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_commits_writes_in_range(conn, client_with_commits) -> None:
    result = load_commits(
        conn,
        client_with_commits,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 2
    cur = conn.execute("SELECT sha FROM commits ORDER BY sha")
    assert [r[0] for r in cur.fetchall()] == ["abc111", "abc222"]


def test_load_commits_prefers_github_login_over_commit_author_name(
    conn, client_with_commits
) -> None:
    load_commits(
        conn,
        client_with_commits,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM commits WHERE sha='abc111'")
    assert cur.fetchone()[0] == "alice"


def test_load_commits_falls_back_to_commit_author_name_when_login_missing(
    conn, client_with_commits
) -> None:
    load_commits(
        conn,
        client_with_commits,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM commits WHERE sha='abc222'")
    assert cur.fetchone()[0] == "Bot"


def test_load_commits_passes_since_until_params(conn, client_with_commits) -> None:
    load_commits(
        conn,
        client_with_commits,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    call_kwargs = client_with_commits.paginate.call_args.kwargs
    assert call_kwargs.get("since") == "2026-01-01T00:00:00Z"
    assert call_kwargs.get("until") == "2026-06-01T23:59:59Z"


def test_load_commits_writes_snapshot(conn, client_with_commits) -> None:
    load_commits(
        conn,
        client_with_commits,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='commits' AND repo='o/r'")
    assert cur.fetchone()[0] == 2


def test_load_commits_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {
                "sha": f"s{i}",
                "commit": {
                    "author": {
                        "name": "u",
                        "email": "u@x",
                        "date": "2026-04-01T00:00:00Z",
                    },
                    "message": "m",
                },
                "author": {"login": "u"},
            }
            for i in range(10)
        ]
    )
    result = load_commits(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=5,
    )
    assert result.row_count == 5
