import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.releases import load_releases

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def gh_client_with_releases():
    fixture = json.loads((FIXTURES / "releases_tanstack_query.json").read_text())
    client = MagicMock()
    client.paginate.return_value = iter(fixture)
    return client


def test_load_releases_writes_rows(conn, gh_client_with_releases) -> None:
    result = load_releases(
        conn,
        gh_client_with_releases,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    assert result.entity == "releases"
    assert result.row_count == 3
    cur = conn.execute("SELECT COUNT(*) FROM releases")
    assert cur.fetchone()[0] == 3


def test_load_releases_extracts_author_login(conn, gh_client_with_releases) -> None:
    load_releases(
        conn,
        gh_client_with_releases,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM releases WHERE id=100")
    assert cur.fetchone()[0] == "tannerlinsley"


def test_load_releases_handles_null_author(conn, gh_client_with_releases) -> None:
    load_releases(
        conn,
        gh_client_with_releases,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT author FROM releases WHERE id=102")
    assert cur.fetchone()[0] is None


def test_load_releases_writes_snapshot_row(conn, gh_client_with_releases) -> None:
    load_releases(
        conn,
        gh_client_with_releases,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    cur = conn.execute(
        "SELECT row_count FROM snapshots WHERE repo='tanstack/query' AND entity='releases'"
    )
    assert cur.fetchone()[0] == 3


def test_load_releases_idempotent_on_rerun(conn, gh_client_with_releases) -> None:
    fixture = json.loads((FIXTURES / "releases_tanstack_query.json").read_text())
    load_releases(
        conn,
        gh_client_with_releases,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    client2 = MagicMock()
    client2.paginate.return_value = iter(fixture)
    load_releases(
        conn,
        client2,
        repo="tanstack/query",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=500,
    )
    cur = conn.execute("SELECT COUNT(*) FROM releases")
    assert cur.fetchone()[0] == 3


def test_load_releases_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {
                "id": i,
                "tag_name": f"v{i}",
                "name": f"r{i}",
                "author": {"login": "u"},
                "published_at": "2024-01-01T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
            }
            for i in range(10)
        ]
    )
    result = load_releases(
        conn,
        client,
        repo="o/r",
        range_start="2024-01-01",
        range_end="2025-01-01",
        max_rows=5,
    )
    assert result.row_count == 5


def test_load_releases_filters_to_range(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {
                "id": 1,
                "tag_name": "v1",
                "name": "old",
                "author": {"login": "u"},
                "published_at": "2023-01-01T00:00:00Z",
                "created_at": "2023-01-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "id": 2,
                "tag_name": "v2",
                "name": "in range",
                "author": {"login": "u"},
                "published_at": "2024-06-01T00:00:00Z",
                "created_at": "2024-06-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
        ]
    )
    result = load_releases(
        conn,
        client,
        repo="o/r",
        range_start="2024-01-01",
        range_end="2024-12-31",
        max_rows=10,
    )
    assert result.row_count == 1
    cur = conn.execute("SELECT id FROM releases")
    assert cur.fetchall() == [(2,)]
