import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.tools.load_author_activity import (
    DEFAULT_AUTHOR_ENTITIES,
    load_author_activity,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "author.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.close()
    return path


def _fake_load_repos(*, expected_repos, return_summary=None):
    def _impl(db_path, *, repos, entities, range_spec, max_rows_per_entity, max_concurrency, now):
        assert set(repos) == set(expected_repos)
        assert "commits" in entities
        return return_summary or {
            "per_repo": {repo: {"fetched": {"commits": 1}, "api_calls_used": 2} for repo in repos},
            "errors": [],
            "api_calls_used": 2 * len(repos),
            "rate_limit_summary": {"remaining": 4999, "resets_in_minutes": 1, "warning": None},
            "cached_at": now.isoformat(),
        }

    return _impl


def test_load_author_activity_with_explicit_repos_skips_discovery(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x", "b/y"])

    with (
        patch("repohealth_mcp.tools.load_author_activity._make_client") as mock_client_factory,
        patch(
            "repohealth_mcp.tools.load_author_activity.load_repos",
            side_effect=fake_load_repos,
        ),
        patch("repohealth_mcp.tools.load_author_activity.discover_repos_by_commits") as mock_search,
        patch("repohealth_mcp.tools.load_author_activity.discover_owned_repos") as mock_owned,
    ):
        result = load_author_activity(
            db_path,
            login="someone",
            repos=["a/x", "b/y"],
            range_spec="6mo",
            entities=["prs"],
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["login"] == "someone"
    assert result["discovery_source"] == "caller"
    assert set(result["discovered_repos"]) == {"a/x", "b/y"}
    mock_search.assert_not_called()
    mock_owned.assert_not_called()
    mock_client_factory.assert_not_called()


def test_load_author_activity_default_discovery_uses_search_commits(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x", "b/y"])

    with (
        patch("repohealth_mcp.tools.load_author_activity._make_client"),
        patch(
            "repohealth_mcp.tools.load_author_activity.load_repos",
            side_effect=fake_load_repos,
        ),
        patch(
            "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
            return_value=["a/x", "b/y"],
        ) as mock_search,
        patch("repohealth_mcp.tools.load_author_activity.discover_owned_repos") as mock_owned,
    ):
        result = load_author_activity(
            db_path,
            login="someone",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["discovery_source"] == "search"
    assert result["discovery_limits"]["max_search_pages"] == 10
    mock_search.assert_called_once()
    mock_owned.assert_not_called()


def test_load_author_activity_owned_discovery_uses_users_repos(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with (
        patch("repohealth_mcp.tools.load_author_activity._make_client"),
        patch(
            "repohealth_mcp.tools.load_author_activity.load_repos",
            side_effect=fake_load_repos,
        ),
        patch("repohealth_mcp.tools.load_author_activity.discover_repos_by_commits") as mock_search,
        patch(
            "repohealth_mcp.tools.load_author_activity.discover_owned_repos",
            return_value=["a/x"],
        ) as mock_owned,
    ):
        result = load_author_activity(
            db_path,
            login="someone",
            discovery="owned",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert result["discovery_source"] == "owned"
    mock_owned.assert_called_once()
    mock_search.assert_not_called()


def test_load_author_activity_writes_author_searches_row(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with (
        patch("repohealth_mcp.tools.load_author_activity._make_client"),
        patch(
            "repohealth_mcp.tools.load_author_activity.load_repos",
            side_effect=fake_load_repos,
        ),
        patch(
            "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
            return_value=["a/x"],
        ),
    ):
        load_author_activity(
            db_path,
            login="someone",
            range_spec="6mo",
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT login, discovery, repos_json FROM author_searches WHERE login=?",
            ("someone",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "someone"
    assert row[1] == "search"
    assert json.loads(row[2]) == ["a/x"]


def test_load_author_activity_default_entities_excludes_pr_reviews():
    assert "commits" in DEFAULT_AUTHOR_ENTITIES
    assert "prs" in DEFAULT_AUTHOR_ENTITIES
    assert "issues" in DEFAULT_AUTHOR_ENTITIES
    assert "pr_reviews" not in DEFAULT_AUTHOR_ENTITIES


def test_load_author_activity_emits_note_when_pr_reviews_not_loaded(db_path):
    fake_load_repos = _fake_load_repos(expected_repos=["a/x"])

    with (
        patch("repohealth_mcp.tools.load_author_activity._make_client"),
        patch(
            "repohealth_mcp.tools.load_author_activity.load_repos",
            side_effect=fake_load_repos,
        ),
        patch(
            "repohealth_mcp.tools.load_author_activity.discover_repos_by_commits",
            return_value=["a/x"],
        ),
    ):
        result = load_author_activity(
            db_path,
            login="someone",
            entities=["commits", "prs", "issues"],
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert any("pr_reviews" in note for note in result["notes"])
