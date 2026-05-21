import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.workflow_runs import load_workflow_runs

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _client_with_workflow_runs():
    fixture = json.loads((FIXTURES / "workflow_runs_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (
        {"workflow_runs": fixture, "total_count": len(fixture)},
        ResponseMeta(200, 4999, None, None),
    )
    return client


def test_load_workflow_runs_writes_in_range(conn) -> None:
    result = load_workflow_runs(
        conn,
        _client_with_workflow_runs(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 2


def test_load_workflow_runs_computes_duration_seconds(conn) -> None:
    load_workflow_runs(
        conn,
        _client_with_workflow_runs(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT duration_seconds FROM workflow_runs WHERE id=1001")
    assert cur.fetchone()[0] == 205


def test_load_workflow_runs_records_conclusion(conn) -> None:
    load_workflow_runs(
        conn,
        _client_with_workflow_runs(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT conclusion FROM workflow_runs WHERE id=1002")
    assert cur.fetchone()[0] == "failure"


def test_load_workflow_runs_writes_snapshot(conn) -> None:
    load_workflow_runs(
        conn,
        _client_with_workflow_runs(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE entity='workflow_runs' AND repo='o/r'"
    )
    assert cur.fetchone()[0] == 2
