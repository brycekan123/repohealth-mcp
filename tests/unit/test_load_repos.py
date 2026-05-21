from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.load_repos import _worker_count, load_repos


def _stub_client():
    client = MagicMock()
    repo_meta_body = {
        "full_name": "x/y",
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

    def _get(_url, **_):
        return (repo_meta_body, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    client.paginate.return_value = iter([])
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "v3.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.close()
    return path


def test_load_repos_dispatches_each_repo(db_path):
    with patch("repohealth_mcp.tools.load_repos._make_client", side_effect=_stub_client):
        result = load_repos(
            db_path,
            repos=["octocat/Hello-World", "github/gitignore", "foo/bar"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            max_concurrency=2,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert set(result["per_repo"].keys()) == {
        "octocat/Hello-World",
        "github/gitignore",
        "foo/bar",
    }
    assert result["api_calls_used"] >= 3
    assert "errors" in result


def test_load_repos_normalizes_url_inputs(db_path):
    with patch("repohealth_mcp.tools.load_repos._make_client", side_effect=_stub_client):
        result = load_repos(
            db_path,
            repos=[
                "https://github.com/octocat/Hello-World",
                "git@github.com:github/gitignore.git",
            ],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert set(result["per_repo"].keys()) == {"octocat/Hello-World", "github/gitignore"}


def test_load_repos_reports_per_repo_errors_without_aborting_batch(db_path):
    call_count = {"n": 0}

    def make_client():
        client = _stub_client()
        repo_meta_body = {
            "full_name": "x/y",
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
            call_count["n"] += 1
            if call_count["n"] == 1 and "/repos/bad/repo" in url:
                raise RuntimeError("simulated 500")
            return (repo_meta_body, ResponseMeta(200, 4999, None, None))

        client.get.side_effect = _get
        return client

    with patch("repohealth_mcp.tools.load_repos._make_client", side_effect=make_client):
        result = load_repos(
            db_path,
            repos=["bad/repo", "good/repo"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            max_concurrency=1,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert "good/repo" in result["per_repo"]
    assert any(err["repo"] == "bad/repo" for err in result["errors"])


def test_load_repos_drops_unparseable_repo_inputs(db_path):
    with patch("repohealth_mcp.tools.load_repos._make_client", side_effect=_stub_client):
        result = load_repos(
            db_path,
            repos=["good/repo", "totally not a repo"],
            entities=["prs"],
            range_spec="6mo",
            max_rows_per_entity=10,
            now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        )

    assert "good/repo" in result["per_repo"]
    assert any(
        err.get("repo") == "totally not a repo" and "parse" in err["error"].lower()
        for err in result["errors"]
    )


def test_load_repos_worker_count_is_capped_at_four():
    assert _worker_count(repo_count=10, max_concurrency=99) == 4
    assert _worker_count(repo_count=2, max_concurrency=99) == 2
    assert _worker_count(repo_count=10, max_concurrency=0) == 1
