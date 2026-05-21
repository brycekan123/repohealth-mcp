"""load_author_activity: load a GitHub user's recent activity across repos."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..author_discovery import DEFAULT_COMMIT_SEARCH_PAGES, discover_owned_repos
from ..author_discovery import discover_repos_by_commits
from ..database import connect
from ..github_client import GitHubClient, resolve_token
from ..loaders.base import parse_range
from ..util import normalize_repo
from .load_repos import load_repos

DEFAULT_AUTHOR_ENTITIES: tuple[str, ...] = ("commits", "prs", "issues")
VALID_DISCOVERY: tuple[str, ...] = ("search", "owned")


def _make_client() -> GitHubClient:
    """Return a fresh GitHubClient. Indirection exists so tests can patch it."""
    return GitHubClient(token=resolve_token())


def _record_author_search(
    db_path: Path | str,
    *,
    login: str,
    discovery: str,
    range_start: str,
    range_end: str,
    repos: list[str],
    discovered_at: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO author_searches
                (login, discovery, range_start, range_end, repos_json, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(login, discovery, range_start, range_end)
            DO UPDATE SET repos_json=excluded.repos_json,
                          discovered_at=excluded.discovered_at
            """,
            (login, discovery, range_start, range_end, json.dumps(repos), discovered_at),
        )
    finally:
        conn.close()


def _normalize_repos(raw_repos: list[str], notes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_repos:
        try:
            canonical = normalize_repo(raw)
        except ValueError as exc:
            notes.append(f"dropped {raw!r}: {exc}")
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def load_author_activity(
    db_path: Path | str,
    *,
    login: str,
    repos: list[str] | None = None,
    range_spec: str = "1y",
    discovery: str = "search",
    entities: list[str] | None = None,
    max_repos: int = 10,
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
    max_search_pages: int = DEFAULT_COMMIT_SEARCH_PAGES,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load a GitHub login's activity across explicit or discovered repos."""
    login = login.strip() if login else ""
    if not login:
        raise ValueError("login is required")
    if discovery not in VALID_DISCOVERY:
        raise ValueError(f"discovery must be one of {VALID_DISCOVERY}; got {discovery!r}")
    if max_repos < 1:
        raise ValueError("max_repos must be >= 1")

    now = now or datetime.now(timezone.utc)
    range_start, range_end = parse_range(range_spec, now=now)

    entity_list = list(entities or DEFAULT_AUTHOR_ENTITIES)
    if "commits" not in entity_list:
        entity_list = ["commits", *entity_list]

    notes: list[str] = []
    if "pr_reviews" not in entity_list:
        notes.append(
            "pr_reviews not loaded; include 'pr_reviews' to capture review activity "
            "(one extra API call per cached PR)."
        )

    if repos:
        discovery_source = "caller"
        discovered = _normalize_repos(repos, notes)
    else:
        client = _make_client()
        try:
            if discovery == "search":
                discovery_source = "search"
                discovered = discover_repos_by_commits(
                    client,
                    login=login,
                    max_repos=max_repos,
                    max_pages=max_search_pages,
                    range_start=range_start,
                    range_end=range_end,
                )
            else:
                discovery_source = "owned"
                discovered = discover_owned_repos(client, login=login, max_repos=max_repos)
        finally:
            client.close()

    if not discovered:
        notes.append(f"no repos discovered for {login!r} via {discovery_source}")
        fetched: dict[str, Any] = {
            "per_repo": {},
            "errors": [],
            "api_calls_used": 0,
            "rate_limit_summary": {
                "remaining": None,
                "resets_in_minutes": None,
                "warning": None,
            },
            "cached_at": now.isoformat(),
        }
    else:
        fetched = load_repos(
            db_path,
            repos=discovered,
            entities=entity_list,
            range_spec=range_spec,
            max_rows_per_entity=max_rows_per_entity,
            max_concurrency=max_concurrency,
            now=now,
        )

    _record_author_search(
        db_path,
        login=login,
        discovery=discovery_source,
        range_start=range_start,
        range_end=range_end,
        repos=discovered,
        discovered_at=now.isoformat(),
    )

    return {
        "login": login,
        "discovered_repos": discovered,
        "discovery_source": discovery_source,
        "discovery_limits": {
            "max_repos": max_repos,
            "max_search_pages": max_search_pages if discovery_source == "search" else None,
        },
        "range_start": range_start,
        "range_end": range_end,
        "entities": entity_list,
        "fetched": fetched,
        "notes": notes,
        "cached_at": now.isoformat(),
    }
