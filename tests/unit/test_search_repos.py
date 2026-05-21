from unittest.mock import MagicMock

import pytest

from repohealth_mcp.github_client import ResponseMeta
from repohealth_mcp.tools.search_repos import search_repos


def _client_with_response(items, total_count=None):
    client = MagicMock()
    payload = {
        "total_count": total_count if total_count is not None else len(items),
        "items": items,
    }
    client.get.return_value = (payload, ResponseMeta(200, 4999, None, None))
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


def test_search_repos_composes_query_from_keywords():
    client = _client_with_response([])
    search_repos(client, query="logging", language="python", sort="stars", limit=5)
    args, kwargs = client.get.call_args
    assert args[0] == "/search/repositories"
    assert "logging" in kwargs["q"]
    assert "language:python" in kwargs["q"]
    assert kwargs["sort"] == "stars"


def test_search_repos_handles_owner_and_topic_qualifiers():
    client = _client_with_response([])
    search_repos(client, owner="rails", topic="api", limit=3)
    _args, kwargs = client.get.call_args
    assert "user:rails" in kwargs["q"]
    assert "topic:api" in kwargs["q"]


def test_search_repos_rejects_involves_kwarg():
    client = _client_with_response([])
    with pytest.raises(TypeError):
        search_repos(client, involves="someone")  # type: ignore[call-arg]


def test_search_repos_filters_archived_and_forks_by_default():
    items = [
        {
            "full_name": "ok/repo",
            "stargazers_count": 100,
            "language": "Python",
            "pushed_at": "2026-05-20T00:00:00Z",
            "archived": False,
            "fork": False,
            "description": "fine",
        },
        {
            "full_name": "stale/repo",
            "stargazers_count": 5,
            "language": "Python",
            "pushed_at": "2018-01-01T00:00:00Z",
            "archived": True,
            "fork": False,
            "description": None,
        },
        {
            "full_name": "fork/repo",
            "stargazers_count": 2,
            "language": "Python",
            "pushed_at": "2026-01-01T00:00:00Z",
            "archived": False,
            "fork": True,
            "description": None,
        },
    ]
    client = _client_with_response(items, total_count=3)
    result = search_repos(client, query="anything", limit=5)
    assert [repo["repo"] for repo in result["repos"]] == ["ok/repo"]
    assert result["total_count"] == 3


def test_search_repos_caps_limit_at_100():
    client = _client_with_response([])
    search_repos(client, query="anything", limit=10_000)
    _args, kwargs = client.get.call_args
    assert kwargs["per_page"] <= 100


def test_search_repos_returns_rate_limit_summary():
    client = _client_with_response([])
    result = search_repos(client, query="anything", limit=5)
    assert result["rate_limit_summary"]["remaining"] == 4999
