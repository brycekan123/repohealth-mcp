import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.contributors import load_contributors

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_contributors():
    fixture = json.loads((FIXTURES / "contributors_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_contributors_writes_one_row_per_author_week(conn, client_with_contributors) -> None:
    result = load_contributors(
        conn,
        client_with_contributors,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT COUNT(*) FROM contributors")
    assert cur.fetchone()[0] == 4
    assert result.row_count == 4


def test_load_contributors_skips_zero_commit_weeks(conn) -> None:
    client = MagicMock()
    client.get.return_value = (
        [
            {
                "author": {"login": "alice"},
                "total": 1,
                "weeks": [
                    {"w": 1700000000, "a": 0, "d": 0, "c": 0},
                    {"w": 1700604800, "a": 1, "d": 0, "c": 1},
                ],
            }
        ],
        ResponseMeta(200, 5000, None, None),
    )
    load_contributors(
        conn,
        client,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT COUNT(*) FROM contributors")
    assert cur.fetchone()[0] == 1


def test_load_contributors_records_additions_deletions(conn, client_with_contributors) -> None:
    load_contributors(
        conn,
        client_with_contributors,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute(
        "SELECT additions, deletions, commits FROM contributors "
        "WHERE author='alice' ORDER BY week_start_at"
    )
    assert cur.fetchall() == [(100, 20, 5), (200, 30, 8)]


def test_load_contributors_uses_anonymous_for_null_author(conn, client_with_contributors) -> None:
    load_contributors(
        conn,
        client_with_contributors,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT COUNT(*) FROM contributors WHERE author='anonymous'")
    assert cur.fetchone()[0] == 1


def test_load_contributors_writes_snapshot(conn, client_with_contributors) -> None:
    load_contributors(
        conn,
        client_with_contributors,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='contributors'")
    assert cur.fetchone()[0] == 4


def test_load_contributors_filters_range(conn, client_with_contributors) -> None:
    result = load_contributors(
        conn,
        client_with_contributors,
        repo="o/r",
        range_start="2023-11-20",
        range_end="2023-11-30",
    )
    assert result.row_count == 1
