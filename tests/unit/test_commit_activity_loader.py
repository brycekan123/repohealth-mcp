import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.commit_activity import load_commit_activity

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client_with_activity():
    fixture = json.loads((FIXTURES / "commit_activity_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_commit_activity_writes_rows(conn, client_with_activity) -> None:
    result = load_commit_activity(
        conn,
        client_with_activity,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM commit_activity")
    assert cur.fetchone()[0] == 3


def test_load_commit_activity_converts_epoch_to_iso(conn, client_with_activity) -> None:
    load_commit_activity(
        conn,
        client_with_activity,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT week_start_at FROM commit_activity ORDER BY week_start_at")
    weeks = [row[0] for row in cur.fetchall()]
    assert all("T" in w for w in weeks)


def test_load_commit_activity_splits_days(conn, client_with_activity) -> None:
    load_commit_activity(
        conn,
        client_with_activity,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute(
        "SELECT sun, mon, tue, wed, thu, fri, sat FROM commit_activity "
        "WHERE total_commits=10"
    )
    row = cur.fetchone()
    assert row == (1, 2, 3, 1, 1, 1, 1)


def test_load_commit_activity_writes_snapshot(conn, client_with_activity) -> None:
    load_commit_activity(
        conn,
        client_with_activity,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    cur = conn.execute("SELECT row_count FROM snapshots WHERE entity='commit_activity'")
    assert cur.fetchone()[0] == 3


def test_load_commit_activity_handles_empty(conn) -> None:
    client = MagicMock()
    client.get.return_value = ([], ResponseMeta(200, 5000, None, None))
    result = load_commit_activity(
        conn,
        client,
        repo="o/r",
        range_start="2023-01-01",
        range_end="2024-12-31",
    )
    assert result.row_count == 0


def test_load_commit_activity_filters_range(conn, client_with_activity) -> None:
    result = load_commit_activity(
        conn,
        client_with_activity,
        repo="o/r",
        range_start="2023-11-20",
        range_end="2023-11-30",
    )
    assert result.row_count == 2
