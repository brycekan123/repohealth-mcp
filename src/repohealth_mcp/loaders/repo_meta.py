"""Loader for top-level repo metadata."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timezone

import yaml

from ..github_client import GitHubError
from .base import upsert_rows

GITHUB_SPONSOR_KEYS = {"github"}


def _fetch_funding(client, repo: str) -> tuple[str | None, int]:
    """Return (funding_json, has_sponsors), or (None, 0) when unavailable."""
    try:
        body, _ = client.get(f"/repos/{repo}/contents/.github/FUNDING.yml")
    except GitHubError as exc:
        if exc.status == 404:
            return None, 0
        raise
    if not isinstance(body, dict) or body.get("encoding") != "base64":
        return None, 0
    try:
        raw = base64.b64decode(body.get("content", "")).decode()
        parsed = yaml.safe_load(raw) or {}
    except Exception:
        return None, 0
    if not isinstance(parsed, dict):
        return None, 0
    has_sponsors = 1 if any(key in parsed and parsed[key] for key in GITHUB_SPONSOR_KEYS) else 0
    return json.dumps(parsed), has_sponsors


def load_repo_meta(conn: sqlite3.Connection, client, *, repo: str) -> None:
    body, _meta = client.get(f"/repos/{repo}")
    funding_json, has_sponsors = _fetch_funding(client, repo)
    row = {
        "repo": repo,
        "description": body.get("description"),
        "default_branch": body.get("default_branch"),
        "stars": body.get("stargazers_count", 0),
        "forks": body.get("forks_count", 0),
        "open_issues_count": body.get("open_issues_count", 0),
        "created_at": body.get("created_at"),
        "pushed_at": body.get("pushed_at"),
        "archived": 1 if body.get("archived") else 0,
        "disabled": 1 if body.get("disabled") else 0,
        "license": (body.get("license") or {}).get("spdx_id"),
        "funding_json": funding_json,
        "has_sponsors": has_sponsors,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_rows(conn, "repos", [row], pk=("repo",))
