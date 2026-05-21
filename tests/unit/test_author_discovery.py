from unittest.mock import MagicMock

from repohealth_mcp.author_discovery import discover_owned_repos, discover_repos_by_commits
from repohealth_mcp.github_client import ResponseMeta


def _client(get_side_effect):
    client = MagicMock()
    client.get.side_effect = get_side_effect
    client.last_meta = ResponseMeta(200, 4999, None, None)
    return client


def test_discover_repos_by_commits_aggregates_unique_repos():
    pages = [
        {
            "total_count": 4,
            "items": [
                {"repository": {"full_name": "a/x"}},
                {"repository": {"full_name": "a/x"}},
                {"repository": {"full_name": "b/y"}},
            ],
        },
        {"total_count": 4, "items": [{"repository": {"full_name": "c/z"}}]},
    ]
    state = {"i": 0}

    def _get(_url, **_):
        page = pages[state["i"]]
        state["i"] += 1
        next_url = "/search/commits?page=2" if state["i"] == 1 else None
        return page, ResponseMeta(200, 4999, None, next_url)

    client = _client(_get)
    repos = discover_repos_by_commits(client, login="someone", max_repos=10, max_pages=3)
    assert repos == ["a/x", "b/y", "c/z"]


def test_discover_repos_by_commits_uses_sort_parameter_and_date_qualifiers():
    page = {"total_count": 1, "items": [{"repository": {"full_name": "a/x"}}]}
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, None)))
    discover_repos_by_commits(
        client,
        login="someone",
        max_repos=1,
        range_start="2026-02-20",
        range_end="2026-05-21",
    )
    _args, kwargs = client.get.call_args
    assert kwargs["q"] == "author:someone author-date:>=2026-02-20 author-date:<=2026-05-21"
    assert kwargs["sort"] == "author-date"
    assert kwargs["order"] == "desc"


def test_discover_repos_by_commits_stops_at_max_repos():
    page = {
        "total_count": 3,
        "items": [
            {"repository": {"full_name": "a/x"}},
            {"repository": {"full_name": "b/y"}},
            {"repository": {"full_name": "c/z"}},
        ],
    }
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, None)))
    repos = discover_repos_by_commits(client, login="someone", max_repos=2)
    assert repos == ["a/x", "b/y"]


def test_discover_repos_by_commits_skips_null_repository():
    page = {
        "total_count": 2,
        "items": [
            {"repository": None},
            {"repository": {"full_name": "a/x"}},
        ],
    }
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, None)))
    repos = discover_repos_by_commits(client, login="someone", max_repos=5)
    assert repos == ["a/x"]


def test_discover_repos_by_commits_defaults_to_ten_pages():
    page = {"total_count": 1000, "items": [{"repository": {"full_name": "a/x"}}]}
    client = _client(lambda *_a, **_kw: (page, ResponseMeta(200, 4999, None, "/next")))
    discover_repos_by_commits(client, login="someone", max_repos=20)
    assert client.get.call_count == 10


def test_discover_owned_repos_filters_archived_and_forks():
    body = [
        {"full_name": "x/keep", "archived": False, "fork": False},
        {"full_name": "x/skip-archived", "archived": True, "fork": False},
        {"full_name": "x/skip-fork", "archived": False, "fork": True},
    ]
    client = _client(lambda *_a, **_kw: (body, ResponseMeta(200, 4999, None, None)))
    repos = discover_owned_repos(client, login="x", max_repos=5)
    assert repos == ["x/keep"]
