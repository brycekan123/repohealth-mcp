from repohealth_mcp.server import (
    author_activity_query,
    compare_repos_query,
    compare_repos_activity_query,
    contributor_health_query,
    ci_health_query,
    commit_history_query,
    dep_health_query,
    dep_audit_query,
    file_hotspots_query,
    maintainer_overlap_query,
    release_cadence_query,
    review_comment_volume_query,
    review_responsiveness_query,
    responsiveness_query,
    star_trajectory_query,
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


def test_commit_history_query_references_commits_table() -> None:
    body = commit_history_query("o/r")
    assert "commits" in body
    assert "o/r" in body


def test_ci_health_query_references_workflow_runs() -> None:
    body = ci_health_query("o/r")
    assert "workflow_runs" in body


def test_dep_audit_query_references_dependencies() -> None:
    body = dep_audit_query("o/r")
    assert "dependencies" in body


def test_star_trajectory_query_references_star_history() -> None:
    body = star_trajectory_query("o/r")
    assert "star_history" in body


def test_review_responsiveness_query_references_pr_reviews() -> None:
    body = review_responsiveness_query("o/r")
    assert "pr_reviews" in body


def test_file_hotspots_query_references_commit_files() -> None:
    body = file_hotspots_query("o/r")
    assert "commit_files" in body


def test_review_comment_volume_query_references_pr_review_comments() -> None:
    body = review_comment_volume_query("o/r")
    assert "pr_review_comments" in body


def test_author_activity_query_prompt_returns_sql() -> None:
    text = author_activity_query("gaearon")
    assert "author" in text
    assert "gaearon" in text
    assert "date(committed_at) >= date('now','-1 year')" in text
    assert "date(created_at) >= date('now','-1 year')" in text


def test_maintainer_overlap_query_prompt_returns_sql() -> None:
    text = maintainer_overlap_query(["rails/rails", "django/django"])
    assert "rails/rails" in text and "django/django" in text


def test_compare_repos_activity_query_prompt_returns_sql() -> None:
    text = compare_repos_activity_query(["rails/rails", "django/django"])
    assert "rails/rails" in text and "django/django" in text
    assert "date(ca.week_start_at) >= date('now','-6 months')" in text
    assert "date(p.created_at) >= date('now','-6 months')" in text


def test_author_activity_query_prompt_supports_explicit_date_range() -> None:
    text = author_activity_query("gaearon", range="2026-01-01..2026-02-01")
    assert "date(committed_at) BETWEEN date('2026-01-01') AND date('2026-02-01')" in text
