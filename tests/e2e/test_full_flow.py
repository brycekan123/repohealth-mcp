"""E2E test: plan -> load -> run_sql against a mock GitHub client."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.github_client import GitHubError, ResponseMeta
from repohealth_mcp.planner import extract_plan_from_text
from repohealth_mcp.tools.load_repo import load_repo
from repohealth_mcp.tools.run_sql import run_sql


def _make_client(
    repo_meta_body,
    prs_body,
    issues_body,
    releases_body,
    commit_activity_body,
    contributors_body,
) -> MagicMock:
    client = MagicMock()

    def _get(url, **_):
        if url == f"/repos/{repo_meta_body['full_name']}":
            return (repo_meta_body, ResponseMeta(200, 4990, None, None))
        if "FUNDING.yml" in url:
            raise GitHubError(404, "no funding")
        if "stats/commit_activity" in url:
            return (commit_activity_body, ResponseMeta(200, 4989, None, None))
        if "stats/contributors" in url:
            return (contributors_body, ResponseMeta(200, 4988, None, None))
        raise AssertionError(f"unexpected GET {url}")

    def _paginate(path, max_rows=None, **_):
        if "/pulls" in path:
            return iter(prs_body[: max_rows or len(prs_body)])
        if "/issues" in path:
            return iter(issues_body[: max_rows or len(issues_body)])
        if "/releases" in path:
            return iter(releases_body[: max_rows or len(releases_body)])
        raise AssertionError(f"unexpected paginate {path}")

    client.get.side_effect = _get
    client.paginate.side_effect = _paginate
    return client


def test_full_flow_plan_load_sql(tmp_path: Path) -> None:
    db_path = tmp_path / "e2e.sqlite"
    conn = connect(db_path)
    init_schema(conn)

    fake_llm_output = json.dumps(
        {
            "repos": ["o/r"],
            "entities": ["prs", "issues", "releases", "commit_activity", "contributors"],
            "range": "6mo",
        }
    )
    plan = extract_plan_from_text(fake_llm_output)
    assert plan.repos == ["o/r"]

    client = _make_client(
        repo_meta_body={
            "full_name": "o/r",
            "description": "demo",
            "default_branch": "main",
            "stargazers_count": 10,
            "forks_count": 1,
            "open_issues_count": 0,
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2026-05-01T00:00:00Z",
            "archived": False,
            "disabled": False,
            "license": {"spdx_id": "MIT"},
        },
        prs_body=[
            {
                "number": 1,
                "title": "a",
                "user": {"login": "alice"},
                "state": "closed",
                "draft": False,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-03T00:00:00Z",
                "closed_at": "2026-04-03T00:00:00Z",
                "merged_at": "2026-04-03T00:00:00Z",
                "comments": 0,
                "base": {"ref": "main"},
            },
            {
                "number": 2,
                "title": "b",
                "user": {"login": "bob"},
                "state": "closed",
                "draft": False,
                "created_at": "2026-04-05T00:00:00Z",
                "updated_at": "2026-04-10T00:00:00Z",
                "closed_at": "2026-04-10T00:00:00Z",
                "merged_at": "2026-04-10T00:00:00Z",
                "comments": 0,
                "base": {"ref": "main"},
            },
        ],
        issues_body=[
            {
                "number": 100,
                "title": "i1",
                "user": {"login": "carol"},
                "state": "open",
                "state_reason": None,
                "labels": [],
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
        ],
        releases_body=[
            {
                "id": 1,
                "tag_name": "v1",
                "name": "r1",
                "author": {"login": "alice"},
                "published_at": "2026-05-01T00:00:00Z",
                "created_at": "2026-05-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
        ],
        commit_activity_body=[
            {"week": 1700000000, "total": 5, "days": [0, 1, 1, 1, 1, 1, 0]},
        ],
        contributors_body=[
            {
                "author": {"login": "alice"},
                "total": 5,
                "weeks": [{"w": 1700000000, "a": 100, "d": 10, "c": 5}],
            },
        ],
    )

    summary = load_repo(
        conn,
        client,
        repo="o/r",
        entities=plan.entities,
        range_spec=plan.range_spec,
        max_rows_per_entity=500,
        now=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert summary["fetched"]["prs"] == 2
    assert summary["fetched"]["issues"] == 1
    assert summary["fetched"]["releases"] == 1
    conn.close()

    result = run_sql(
        db_path,
        "SELECT median(julianday(merged_at) - julianday(created_at)) AS days "
        "FROM prs WHERE repo='o/r' AND merged_at IS NOT NULL",
    )
    assert result["rows"][0]["days"] == pytest.approx(3.5, abs=0.01)
