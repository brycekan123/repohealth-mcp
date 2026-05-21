"""Integration smoke tests against a tiny stable public GitHub repo."""

from pathlib import Path

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubClient, resolve_token
from repohealth_mcp.loaders.releases import load_releases
from repohealth_mcp.loaders.repo_meta import load_repo_meta
from repohealth_mcp.tools.load_author_activity import load_author_activity
from repohealth_mcp.tools.search_repos import search_repos

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


def test_search_repos_returns_results_for_defunkt(client) -> None:
    result = search_repos(client, owner="defunkt", limit=3)
    assert result["total_count"] >= 1
    assert len(result["repos"]) >= 1
    assert all("/" in row["repo"] for row in result["repos"])


def test_load_author_activity_owned_discovery_against_defunkt(tmp_path: Path) -> None:
    if not resolve_token():
        pytest.skip("GITHUB_TOKEN not set")
    db_path = tmp_path / "v3_int.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    result = load_author_activity(
        db_path,
        login="defunkt",
        discovery="owned",
        range_spec="1y",
        max_repos=2,
        max_rows_per_entity=50,
    )
    assert result["login"] == "defunkt"
    assert result["discovery_source"] == "owned"
    assert len(result["discovered_repos"]) >= 1


def test_load_author_activity_search_discovery_against_defunkt(tmp_path: Path) -> None:
    if not resolve_token():
        pytest.skip("GITHUB_TOKEN not set")
    db_path = tmp_path / "v3_int_search.sqlite"
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    result = load_author_activity(
        db_path,
        login="defunkt",
        discovery="search",
        range_spec="6mo",
        max_repos=2,
        max_rows_per_entity=50,
    )
    assert result["discovery_source"] == "search"
    assert isinstance(result["discovered_repos"], list)
