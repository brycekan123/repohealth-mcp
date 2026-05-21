from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.loaders.repo_meta import load_repo_meta


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_load_repo_meta_writes_row(conn) -> None:
    client = MagicMock()
    client.get.return_value = (
        {
            "full_name": "o/r",
            "description": "test repo",
            "default_branch": "main",
            "stargazers_count": 100,
            "forks_count": 10,
            "open_issues_count": 5,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2026-05-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": {"spdx_id": "MIT"},
        },
        ResponseMeta(200, 5000, None, None),
    )
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT stars, forks, license FROM repos WHERE repo='o/r'")
    assert cur.fetchone() == (100, 10, "MIT")


def test_load_repo_meta_handles_null_license(conn) -> None:
    client = MagicMock()
    client.get.return_value = (
        {
            "full_name": "o/r",
            "description": None,
            "default_branch": "main",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2020-01-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": None,
        },
        ResponseMeta(200, 5000, None, None),
    )
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT license FROM repos WHERE repo='o/r'")
    assert cur.fetchone()[0] is None
