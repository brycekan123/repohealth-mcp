"""load_repos: fan out v2's load_repo across multiple repos in parallel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import connect
from ..github_client import GitHubClient, resolve_token
from ..util import normalize_repo
from .load_repo import DEFAULT_ENTITIES, load_repo

_MAX_CONCURRENCY_CAP = 4


def _make_client() -> GitHubClient:
    """Return a fresh GitHubClient. Indirection exists so tests can patch it."""
    return GitHubClient(token=resolve_token())


def _aggregate_rate_limit(per_repo: dict[str, dict[str, Any]]) -> dict[str, Any]:
    remainings: list[int] = []
    resets: list[int] = []
    warnings: list[str] = []
    for summary in per_repo.values():
        rate_limit = summary.get("rate_limit_summary") or {}
        remaining = rate_limit.get("remaining")
        reset = rate_limit.get("resets_in_minutes")
        if isinstance(remaining, int):
            remainings.append(remaining)
        if isinstance(reset, int):
            resets.append(reset)
        if rate_limit.get("warning"):
            warnings.append(rate_limit["warning"])
    return {
        "remaining": min(remainings) if remainings else None,
        "resets_in_minutes": min(resets) if resets else None,
        "warning": "; ".join(warnings) if warnings else None,
    }


def _worker_count(repo_count: int, max_concurrency: int) -> int:
    """Return bounded worker count for GitHub fan-out."""
    requested = max(1, max_concurrency)
    return max(1, min(_MAX_CONCURRENCY_CAP, requested, repo_count or 1))


def load_repos(
    db_path: Path | str,
    *,
    repos: list[str],
    entities: list[str] | None = None,
    range_spec: str = "6mo",
    max_rows_per_entity: int = 500,
    max_concurrency: int = 4,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fan out ``load_repo`` across multiple repos in parallel."""
    now = now or datetime.now(timezone.utc)
    entity_list = list(entities or DEFAULT_ENTITIES)

    normalized: list[str] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in repos:
        try:
            canonical = normalize_repo(raw)
        except ValueError as exc:
            errors.append({"repo": raw, "error": f"normalize_repo: {exc}"})
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)

    per_repo: dict[str, dict[str, Any]] = {}
    max_workers = _worker_count(len(normalized), max_concurrency)

    def _one(repo: str) -> tuple[str, dict[str, Any] | None, str | None]:
        client = _make_client()
        conn = connect(db_path)
        try:
            summary = load_repo(
                conn,
                client,
                repo=repo,
                entities=entity_list,
                range_spec=range_spec,
                max_rows_per_entity=max_rows_per_entity,
                now=now,
            )
            return repo, summary, None
        except Exception as exc:  # noqa: BLE001 - batch callers need per-repo errors
            return repo, None, str(exc)
        finally:
            try:
                client.close()
            finally:
                conn.close()

    if normalized:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_one, repo): repo for repo in normalized}
            for future in as_completed(futures):
                repo, summary, error = future.result()
                if error is not None:
                    errors.append({"repo": repo, "error": error})
                elif summary is not None:
                    per_repo[repo] = summary

    api_calls_used = sum(int(summary.get("api_calls_used") or 0) for summary in per_repo.values())
    return {
        "per_repo": per_repo,
        "errors": errors,
        "api_calls_used": api_calls_used,
        "rate_limit_summary": _aggregate_rate_limit(per_repo),
        "cached_at": now.isoformat(),
    }
