"""search_repos: wrap GitHub /search/repositories. No DB writes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_VALID_SORT = {"stars", "forks", "updated", "best-match"}


def _assemble_query(
    query: str | None,
    owner: str | None,
    language: str | None,
    topic: str | None,
) -> str:
    parts: list[str] = []
    if query:
        parts.append(query.strip())
    if owner:
        parts.append(f"user:{owner}")
    if language:
        parts.append(f"language:{language}")
    if topic:
        parts.append(f"topic:{topic}")
    return " ".join(part for part in parts if part)


def _rate_limit_summary(meta) -> dict[str, Any]:
    remaining = getattr(meta, "rate_limit_remaining", None)
    reset = getattr(meta, "rate_limit_reset", None)
    resets_in_minutes = None
    if isinstance(reset, int):
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        resets_in_minutes = max(0, (reset - now_epoch) // 60)

    warning = None
    if isinstance(remaining, int) and remaining < 5:
        warning = (
            "low search rate-limit remaining; GitHub search endpoints have tighter "
            "per-minute limits than core REST"
        )
    return {
        "remaining": remaining if isinstance(remaining, int) else None,
        "resets_in_minutes": resets_in_minutes,
        "warning": warning,
    }


def search_repos(
    client,
    *,
    query: str | None = None,
    owner: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    sort: str = "updated",
    limit: int = 20,
    include_forks: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Search GitHub repos and return canonical ``owner/name`` rows."""
    if sort not in _VALID_SORT:
        raise ValueError(f"sort must be one of {sorted(_VALID_SORT)}; got {sort!r}")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    assembled = _assemble_query(query, owner, language, topic)
    if not assembled:
        raise ValueError("search_repos requires at least one of: query, owner, language, topic")

    params: dict[str, Any] = {"q": assembled, "per_page": min(100, limit)}
    if sort != "best-match":
        params["sort"] = sort
    body, meta = client.get("/search/repositories", **params)
    if not isinstance(body, dict):
        raise ValueError(f"unexpected /search/repositories response: {type(body)}")

    items = body.get("items") or []
    total_count = body.get("total_count", len(items))
    rows: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        archived = bool(item.get("archived"))
        fork = bool(item.get("fork"))
        if archived and not include_archived:
            continue
        if fork and not include_forks:
            continue
        full_name = item.get("full_name")
        if not full_name:
            continue
        rows.append(
            {
                "repo": full_name,
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "pushed_at": item.get("pushed_at"),
                "archived": archived,
                "fork": fork,
                "description": item.get("description"),
            }
        )

    return {
        "query": assembled,
        "repos": rows,
        "total_count": total_count,
        "rate_limit_summary": _rate_limit_summary(meta),
    }
