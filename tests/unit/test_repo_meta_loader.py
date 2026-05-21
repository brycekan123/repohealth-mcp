import base64
import json
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubError, ResponseMeta
from repohealth_mcp.loaders.repo_meta import load_repo_meta


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_load_repo_meta_writes_row(conn) -> None:
    client = MagicMock()
    client.get.return_value = (
        {
            "full_name": "o/r",
            "description": "test repo",
            "default_branch": "main",
            "stargazers_count": 100,
            "forks_count": 10,
            "open_issues_count": 5,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2026-05-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": {"spdx_id": "MIT"},
        },
        ResponseMeta(200, 5000, None, None),
    )
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT stars, forks, license FROM repos WHERE repo='o/r'")
    assert cur.fetchone() == (100, 10, "MIT")


def test_load_repo_meta_handles_null_license(conn) -> None:
    client = MagicMock()
    client.get.return_value = (
        {
            "full_name": "o/r",
            "description": None,
            "default_branch": "main",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2020-01-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": None,
        },
        ResponseMeta(200, 5000, None, None),
    )
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT license FROM repos WHERE repo='o/r'")
    assert cur.fetchone()[0] is None


def test_load_repo_meta_extracts_funding_when_present(conn) -> None:
    client = MagicMock()
    funding_yaml = "github: [octocat]\npatreon: octocat\n"
    funding_b64 = base64.b64encode(funding_yaml.encode()).decode()

    def _get(url, **_):
        if url == "/repos/o/r":
            return (
                {
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
                    "license": {"spdx_id": "MIT"},
                },
                ResponseMeta(200, 4999, None, None),
            )
        if url == "/repos/o/r/contents/.github/FUNDING.yml":
            return (
                {"encoding": "base64", "content": funding_b64},
                ResponseMeta(200, 4999, None, None),
            )
        return (None, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT funding_json, has_sponsors FROM repos WHERE repo='o/r'")
    funding_json, has_sponsors = cur.fetchone()
    parsed = json.loads(funding_json)
    assert parsed.get("github") == ["octocat"]
    assert parsed.get("patreon") == "octocat"
    assert has_sponsors == 1


def test_load_repo_meta_handles_missing_funding(conn) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r":
            return (
                {
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
                },
                ResponseMeta(200, 4999, None, None),
            )
        if url == "/repos/o/r/contents/.github/FUNDING.yml":
            raise GitHubError(404, "Not Found")
        return (None, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    load_repo_meta(conn, client, repo="o/r")
    cur = conn.execute("SELECT funding_json, has_sponsors FROM repos WHERE repo='o/r'")
    funding_json, has_sponsors = cur.fetchone()
    assert funding_json is None
    assert has_sponsors == 0


def test_load_repo_meta_reraises_non_404_funding_error(conn) -> None:
    client = MagicMock()

    def _get(url, **_):
        if url == "/repos/o/r":
            return (
                {
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
                },
                ResponseMeta(200, 4999, None, None),
            )
        if url == "/repos/o/r/contents/.github/FUNDING.yml":
            raise GitHubError(403, "rate limited")
        return (None, ResponseMeta(200, 4999, None, None))

    client.get.side_effect = _get
    with pytest.raises(GitHubError, match="rate limited"):
        load_repo_meta(conn, client, repo="o/r")
