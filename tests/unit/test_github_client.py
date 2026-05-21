import httpx
import pytest
import respx

from repohealth_mcp.github_client import (
    GitHubClient,
    GitHubError,
    RateLimitExceeded,
)


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="fake-token", base_url="https://api.github.com", sleep=lambda _: None)


@respx.mock
def test_get_success_returns_json(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r").mock(
        return_value=httpx.Response(
            200, json={"name": "r"}, headers={"x-ratelimit-remaining": "4999"}
        )
    )
    body, meta = client.get("/repos/o/r")
    assert body == {"name": "r"}
    assert meta.rate_limit_remaining == 4999


@respx.mock
def test_get_sends_auth_header(client: GitHubClient) -> None:
    route = respx.get("https://api.github.com/repos/o/r").mock(
        return_value=httpx.Response(200, json={})
    )
    client.get("/repos/o/r")
    assert route.calls[0].request.headers["authorization"] == "Bearer fake-token"


def test_no_token_omits_auth_header() -> None:
    client = GitHubClient(token=None)
    with respx.mock:
        route = respx.get("https://api.github.com/repos/o/r").mock(
            return_value=httpx.Response(200, json={})
        )
        client.get("/repos/o/r")
        assert "authorization" not in route.calls[0].request.headers


@respx.mock
def test_401_raises_github_error(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(GitHubError) as exc:
        client.get("/x")
    assert exc.value.status == 401


@respx.mock
def test_404_raises_github_error(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(GitHubError) as exc:
        client.get("/x")
    assert exc.value.status == 404


@respx.mock
def test_403_rate_limited_raises_rate_limit_exceeded(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(
        return_value=httpx.Response(
            403,
            json={},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
        )
    )
    with pytest.raises(RateLimitExceeded) as exc:
        client.get("/x")
    assert exc.value.reset_at_epoch == 1700000000


@respx.mock
def test_202_retries_then_succeeds(client: GitHubClient) -> None:
    respx.get("https://api.github.com/stats").mock(
        side_effect=[
            httpx.Response(202, json={}),
            httpx.Response(202, json={}),
            httpx.Response(200, json=[1, 2, 3]),
        ]
    )
    body, _ = client.get("/stats")
    assert body == [1, 2, 3]


@respx.mock
def test_202_gives_up_after_3_tries(client: GitHubClient) -> None:
    respx.get("https://api.github.com/stats").mock(return_value=httpx.Response(202, json={}))
    with pytest.raises(GitHubError) as exc:
        client.get("/stats")
    assert "still computing" in str(exc.value).lower()


@respx.mock
def test_500_retries_then_succeeds(client: GitHubClient) -> None:
    respx.get("https://api.github.com/x").mock(
        side_effect=[
            httpx.Response(500, json={}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    body, _ = client.get("/x")
    assert body == {"ok": True}


@respx.mock
def test_paginate_iterates_link_header(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r/pulls?page=2").mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )
    respx.get("https://api.github.com/repos/o/r/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={"link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'},
        )
    )
    rows = list(client.paginate("/repos/o/r/pulls"))
    assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]


@respx.mock
def test_paginate_respects_max_rows(client: GitHubClient) -> None:
    respx.get("https://api.github.com/repos/o/r/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": i} for i in range(100)],
            headers={"link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'},
        )
    )
    rows = list(client.paginate("/repos/o/r/pulls", max_rows=50))
    assert len(rows) == 50
