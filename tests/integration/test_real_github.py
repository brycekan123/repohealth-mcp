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


def test_real_commits(conn, client) -> None:
    from repohealth_mcp.loaders.commits import load_commits

    result = load_commits(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=10,
    )
    assert result.row_count >= 1


def test_real_dependencies(conn, client) -> None:
    from repohealth_mcp.loaders.dependencies import load_dependencies

    result = load_dependencies(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
    )
    assert result.row_count >= 0


def test_real_star_history(conn, client) -> None:
    from repohealth_mcp.loaders.star_history import load_star_history

    result = load_star_history(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=5,
    )
    assert result.row_count >= 1


def test_real_workflow_runs(conn, client) -> None:
    from repohealth_mcp.loaders.workflow_runs import load_workflow_runs

    result = load_workflow_runs(
        conn,
        client,
        repo=REPO,
        range_start="2024-01-01",
        range_end="2026-12-31",
        max_rows=5,
    )
    assert result.row_count >= 0


def test_real_commit_files(conn, client) -> None:
    from repohealth_mcp.loaders.commit_files import load_commit_files
    from repohealth_mcp.loaders.commits import load_commits

    load_commits(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=3,
    )
    result = load_commit_files(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=20,
    )
    assert result.row_count >= 1


def test_real_pr_review_comments(conn, client) -> None:
    from repohealth_mcp.loaders.pr_review_comments import load_pr_review_comments
    from repohealth_mcp.loaders.prs import load_prs

    load_prs(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=3,
    )
    result = load_pr_review_comments(
        conn,
        client,
        repo=REPO,
        range_start="2010-01-01",
        range_end="2026-12-31",
        max_rows=10,
    )
    assert result.row_count >= 0
