"""Integration smoke tests against a tiny stable public GitHub repo."""

from pathlib import Path

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubClient, resolve_token
from repohealth_mcp.loaders.releases import load_releases
from repohealth_mcp.loaders.repo_meta import load_repo_meta

pytestmark = pytest.mark.integration

REPO = "octocat/Hello-World"


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "integ.sqlite")
    init_schema(c)
    return c


@pytest.fixture
def client():
    token = resolve_token()
    if token is None:
        pytest.skip("no GITHUB_TOKEN; integration test requires auth to avoid 60/hr cap")
    with GitHubClient(token=token) as c:
        yield c


def test_real_repo_meta(conn, client) -> None:
    load_repo_meta(conn, client, repo=REPO)
    row = conn.execute("SELECT repo, default_branch FROM repos WHERE repo=?", (REPO,)).fetchone()
    assert row is not None
    assert row[0] == REPO
    assert row[1] in ("main", "master")


def test_real_releases(conn, client) -> None:
    result = load_releases(
        conn,
        client,
        repo=REPO,
        range_start="2020-01-01",
        range_end="2026-12-31",
        max_rows=10,
    )
    assert result.entity == "releases"
    assert result.row_count >= 0
