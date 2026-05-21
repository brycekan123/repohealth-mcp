import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.dependencies import load_dependencies

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _client_with_sbom():
    fixture = json.loads((FIXTURES / "sbom_sample.json").read_text())
    client = MagicMock()
    client.get.return_value = (fixture, ResponseMeta(200, 4999, None, None))
    return client


def test_load_dependencies_writes_packages(conn) -> None:
    result = load_dependencies(
        conn,
        _client_with_sbom(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert result.row_count == 3
    cur = conn.execute("SELECT package_name FROM dependencies ORDER BY package_name")
    assert {r[0] for r in cur.fetchall()} == {"lodash", "requests", "actions/checkout"}


def test_load_dependencies_extracts_package_manager(conn) -> None:
    load_dependencies(
        conn,
        _client_with_sbom(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    cur = conn.execute(
        "SELECT package_name, package_manager FROM dependencies WHERE package_name='lodash'"
    )
    assert cur.fetchone() == ("lodash", "npm")


def test_load_dependencies_extracts_version_and_license(conn) -> None:
    load_dependencies(
        conn,
        _client_with_sbom(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    cur = conn.execute("SELECT version, license FROM dependencies WHERE package_name='lodash'")
    assert cur.fetchone() == ("4.17.21", "MIT")


def test_load_dependencies_handles_missing_license(conn) -> None:
    load_dependencies(
        conn,
        _client_with_sbom(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    cur = conn.execute("SELECT license FROM dependencies WHERE package_name='actions/checkout'")
    assert cur.fetchone()[0] is None


def test_load_dependencies_writes_snapshot(conn) -> None:
    load_dependencies(
        conn,
        _client_with_sbom(),
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE entity='dependencies' AND repo='o/r'"
    )
    assert cur.fetchone()[0] == 3


def test_load_dependencies_handles_empty_sbom(conn) -> None:
    client = MagicMock()
    client.get.return_value = ({"sbom": {"packages": []}}, ResponseMeta(200, 4999, None, None))
    result = load_dependencies(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert result.row_count == 0


def test_load_dependencies_handles_404_gracefully(conn) -> None:
    from repohealth_mcp.github_client import GitHubError

    client = MagicMock()
    client.get.side_effect = GitHubError(404, "no SBOM available")
    result = load_dependencies(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
    )
    assert result.row_count == 0
