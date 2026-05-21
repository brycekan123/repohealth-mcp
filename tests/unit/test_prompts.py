from repohealth_mcp.server import (
    compare_repos_query,
    contributor_health_query,
    dep_health_query,
    release_cadence_query,
    responsiveness_query,
)


def test_dep_health_query_includes_repo_param() -> None:
    text = dep_health_query(repo="tanstack/query")
    assert "tanstack/query" in text
    assert "SELECT" in text.upper()


def test_compare_repos_query_lists_all_repos() -> None:
    text = compare_repos_query(repos=["a/b", "c/d", "e/f"])
    for repo in ("a/b", "c/d", "e/f"):
        assert repo in text


def test_release_cadence_query_references_releases_table() -> None:
    text = release_cadence_query(repo="o/r")
    assert "releases" in text


def test_responsiveness_query_references_prs_and_issues() -> None:
    text = responsiveness_query(repo="o/r")
    assert "prs" in text
    assert "issues" in text


def test_contributor_health_query_references_contributors() -> None:
    text = contributor_health_query(repo="o/r")
    assert "contributors" in text


def test_prompt_sql_literals_escape_quotes() -> None:
    text = dep_health_query(repo="o/r' OR 1=1 --")
    assert "o/r'' OR 1=1 --" in text
    assert "repo='o/r' OR 1=1 --'" not in text
