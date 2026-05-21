"""Helpers that discover candidate repos for a given GitHub login."""

from __future__ import annotations


DEFAULT_COMMIT_SEARCH_PAGES = 10


def discover_repos_by_commits(
    client,
    *,
    login: str,
    max_repos: int = 10,
    max_pages: int = DEFAULT_COMMIT_SEARCH_PAGES,
    per_page: int = 100,
    range_start: str | None = None,
    range_end: str | None = None,
) -> list[str]:
    """Aggregate unique ``owner/name`` values from ``/search/commits``."""
    if not login:
        raise ValueError("login is required")
    if max_repos < 1:
        raise ValueError("max_repos must be >= 1")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    query_parts = [f"author:{login}"]
    if range_start:
        query_parts.append(f"author-date:>={range_start}")
    if range_end:
        query_parts.append(f"author-date:<={range_end}")
    q = " ".join(query_parts)
    seen: list[str] = []
    seen_set: set[str] = set()
    url = "/search/commits"
    params = {
        "q": q,
        "sort": "author-date",
        "order": "desc",
        "per_page": min(100, max(1, per_page)),
    }
    pages_used = 0

    while pages_used < max_pages and len(seen) < max_repos:
        body, meta = client.get(url, **params)
        params = {}
        if not isinstance(body, dict):
            break
        for item in body.get("items") or []:
            if not isinstance(item, dict):
                continue
            repo_obj = item.get("repository")
            if not isinstance(repo_obj, dict):
                continue
            full_name = repo_obj.get("full_name")
            if not full_name or full_name in seen_set:
                continue
            seen_set.add(full_name)
            seen.append(full_name)
            if len(seen) >= max_repos:
                break

        pages_used += 1
        next_url = getattr(meta, "next_url", None)
        if not next_url:
            break
        url = next_url

    return seen


def discover_owned_repos(
    client,
    *,
    login: str,
    max_repos: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
) -> list[str]:
    """List repos owned by ``login``, sorted by most recent push."""
    if not login:
        raise ValueError("login is required")
    if max_repos < 1:
        raise ValueError("max_repos must be >= 1")

    body, _meta = client.get(
        f"/users/{login}/repos",
        sort="pushed",
        per_page=min(100, max(1, max_repos * 2)),
    )
    if not isinstance(body, list):
        return []

    out: list[str] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        if item.get("archived") and not include_archived:
            continue
        if item.get("fork") and not include_forks:
            continue
        full_name = item.get("full_name")
        if not full_name:
            continue
        out.append(full_name)
        if len(out) >= max_repos:
            break
    return out
