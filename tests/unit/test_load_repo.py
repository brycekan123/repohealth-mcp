import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubError, ResponseMeta
from repohealth_mcp.tools.load_repo import DEFAULT_ENTITIES, VALID_ENTITIES, load_repo
from repohealth_mcp.tools.refresh_repo import refresh_repo


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def _stub_client_for_all_entities() -> MagicMock:
    client = MagicMock()
    repo_meta_body = {
        "full_name": "o/r",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])
    return client


def test_load_repo_returns_summary_with_all_entities(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=list(VALID_ENTITIES),
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert result["repo"] == "o/r"
    assert set(result["fetched"].keys()) == set(VALID_ENTITIES)
    assert result["api_calls_used"] > 0
    assert result["cached_at"] is not None


def test_load_repo_rejects_unknown_entity(conn) -> None:
    client = _stub_client_for_all_entities()
    with pytest.raises(ValueError, match="unknown entity"):
        load_repo(
            conn,
            client,
            repo="o/r",
            entities=["prs", "frobulators"],
            range_spec="6mo",
            max_rows_per_entity=500,
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )


def test_load_repo_rejects_invalid_repo_format(conn) -> None:
    client = _stub_client_for_all_entities()
    with pytest.raises(ValueError, match="parse repo|repo format"):
        load_repo(
            conn,
            client,
            repo="not_a_slash_separated_thing",
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=500,
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )


def test_load_repo_normalizes_url_inputs(tmp_path) -> None:
    conn = connect(tmp_path / "normalize.sqlite")
    init_schema(conn)
    client = MagicMock()

    repo_meta_body = {
        "full_name": "o/r",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])
    result = load_repo(
        conn,
        client,
        repo="https://github.com/o/r/pulls/1",
        entities=["prs"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert result["repo"] == "o/r"


def test_load_repo_clamps_max_rows(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=["prs"],
        range_spec="6mo",
        max_rows_per_entity=99999,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert "prs" in result["fetched"]


def test_load_repo_includes_rate_limit_summary(conn) -> None:
    client = _stub_client_for_all_entities()
    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=["prs"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert "rate_limit_summary" in result
    assert "remaining" in result["rate_limit_summary"]


def test_load_repo_runs_entity_loaders_in_parallel(tmp_path) -> None:
    """Entity loaders must run concurrently — observe distinct worker threads."""
    conn = connect(tmp_path / "parallel.sqlite")
    init_schema(conn)

    repo_meta_body = {
        "full_name": "o/r",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }
    client = MagicMock()
    main_thread_id = threading.get_ident()
    entity_thread_ids: set[int] = set()
    lock = threading.Lock()

    def track_get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        # stats endpoints called from entity loaders
        with lock:
            entity_thread_ids.add(threading.get_ident())
        return ([], ResponseMeta(200, 4999, None, None))

    def track_paginate(*_args, **_kwargs):
        with lock:
            entity_thread_ids.add(threading.get_ident())
        return iter([])

    client.get.side_effect = track_get
    client.paginate.side_effect = track_paginate

    load_repo(
        conn,
        client,
        repo="o/r",
        entities=list(DEFAULT_ENTITIES),
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    # 5 entity loaders should run on threads distinct from main, and >1 worker thread.
    assert main_thread_id not in entity_thread_ids, "entity loaders ran on main thread"
    assert len(entity_thread_ids) > 1, (
        f"expected multiple worker threads, saw {len(entity_thread_ids)}"
    )


def test_load_repo_continues_when_one_loader_fails(tmp_path) -> None:
    """A 202/error on one entity must not discard data from the other entities."""
    conn = connect(tmp_path / "partial.sqlite")
    init_schema(conn)

    repo_meta_body = {
        "full_name": "o/r",
        "description": "t",
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": {"spdx_id": "MIT"},
    }
    client = MagicMock()

    def flaky_get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        if "stats/commit_activity" in url:
            raise GitHubError(202, "GitHub stats still computing")
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = flaky_get
    client.paginate.return_value = iter([])

    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=list(DEFAULT_ENTITIES),
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    # 4 entities succeeded, 1 errored
    assert set(result["fetched"].keys()) == {"prs", "issues", "releases", "contributors"}
    assert "commit_activity" not in result["fetched"]
    assert "errors" in result
    failed = [e for e in result["errors"] if e["entity"] == "commit_activity"]
    assert len(failed) == 1
    assert "stats still computing" in failed[0]["error"].lower()


def test_refresh_repo_clears_data_then_reloads(conn) -> None:
    client = _stub_client_for_all_entities()
    conn.execute("INSERT INTO prs (repo, number, title) VALUES ('o/r', 999, 'stale')")
    conn.execute(
        "INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count) "
        "VALUES ('o/r', 'prs', '2025-11-20', '2026-05-20', '2026-01-01T00:00:00Z', 1)"
    )
    refresh_repo(
        conn,
        client,
        repo="o/r",
        entities=["prs"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    cur = conn.execute("SELECT COUNT(*) FROM prs WHERE number=999")
    assert cur.fetchone()[0] == 0


def test_load_repo_loads_v2_entities(tmp_path) -> None:
    """v2 entities must be loadable by explicit request."""
    conn = connect(tmp_path / "v2.sqlite")
    init_schema(conn)
    client = MagicMock()

    repo_meta_body = {
        "full_name": "o/r",
        "description": None,
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": None,
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        if "actions/runs" in url:
            return ({"workflow_runs": []}, ResponseMeta(200, 4999, None, None))
        if "dependency-graph" in url:
            return ({"sbom": {"packages": []}}, ResponseMeta(200, 4999, None, None))
        return ([], ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])

    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=["commits", "dependencies", "star_history", "workflow_runs"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )
    assert set(result["fetched"].keys()) == {
        "commits",
        "dependencies",
        "star_history",
        "workflow_runs",
    }


def test_load_repo_loads_parent_entities_before_dependent_entities(tmp_path) -> None:
    conn = connect(tmp_path / "dependent.sqlite")
    init_schema(conn)
    client = MagicMock()

    repo_meta_body = {
        "full_name": "o/r",
        "description": None,
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": None,
    }

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        return ([], ResponseMeta(200, 4999, None, None))

    def _paginate(path, **_):
        if path == "/repos/o/r/pulls":
            time.sleep(0.05)
            return iter(
                [
                    {
                        "number": 1,
                        "title": "p",
                        "user": {"login": "author"},
                        "state": "closed",
                        "draft": False,
                        "created_at": "2026-04-01T00:00:00Z",
                        "updated_at": "2026-04-02T00:00:00Z",
                        "closed_at": "2026-04-02T00:00:00Z",
                        "merged_at": "2026-04-02T00:00:00Z",
                        "comments": 0,
                        "base": {"ref": "main"},
                    }
                ]
            )
        if path == "/repos/o/r/pulls/1/reviews":
            return iter(
                [
                    {
                        "id": 1,
                        "user": {"login": "reviewer"},
                        "state": "APPROVED",
                        "submitted_at": "2026-04-02T00:00:00Z",
                    }
                ]
            )
        return iter([])

    client.get.side_effect = _get
    client.paginate.side_effect = _paginate

    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=["prs", "pr_reviews"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert result["fetched"]["prs"] == 1
    assert result["fetched"]["pr_reviews"] == 1


def test_load_repo_skips_dependent_entity_when_requested_parent_fails(tmp_path) -> None:
    conn = connect(tmp_path / "dependent-failure.sqlite")
    init_schema(conn)
    client = MagicMock()

    repo_meta_body = {
        "full_name": "o/r",
        "description": None,
        "default_branch": "main",
        "stargazers_count": 1,
        "forks_count": 0,
        "open_issues_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "disabled": False,
        "license": None,
    }
    review_paths: list[str] = []

    def _get(url, **_):
        if url == "/repos/o/r":
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        return ([], ResponseMeta(200, 4999, None, None))

    def _paginate(path, **_):
        if path == "/repos/o/r/pulls":
            raise RuntimeError("prs failed")
        if path.endswith("/reviews"):
            review_paths.append(path)
            return iter(
                [
                    {
                        "id": 1,
                        "user": {"login": "reviewer"},
                        "state": "APPROVED",
                        "submitted_at": "2026-04-02T00:00:00Z",
                    }
                ]
            )
        return iter([])

    client.get.side_effect = _get
    client.paginate.side_effect = _paginate

    result = load_repo(
        conn,
        client,
        repo="o/r",
        entities=["prs", "pr_reviews"],
        range_spec="6mo",
        max_rows_per_entity=500,
        now=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert "prs" not in result["fetched"]
    assert "pr_reviews" not in result["fetched"]
    assert review_paths == []
    assert {error["entity"] for error in result["errors"]} == {"prs", "pr_reviews"}
    cur = conn.execute("SELECT COUNT(*) FROM snapshots WHERE entity='pr_reviews'")
    assert cur.fetchone()[0] == 0
