"""load_repo orchestrator: fetches one repo across selected entities."""

from __future__ import annotations

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ..database import connect
from ..loaders.base import LoaderResult, parse_range
from ..loaders.commit_activity import load_commit_activity
from ..loaders.commit_files import load_commit_files
from ..loaders.commits import load_commits
from ..loaders.contributors import load_contributors
from ..loaders.dependencies import load_dependencies
from ..loaders.issues import load_issues
from ..loaders.pr_review_comments import load_pr_review_comments
from ..loaders.pr_reviews import load_pr_reviews
from ..loaders.prs import load_prs
from ..loaders.releases import load_releases
from ..loaders.repo_meta import load_repo_meta
from ..loaders.star_history import load_star_history
from ..loaders.workflow_runs import load_workflow_runs

DEFAULT_ENTITIES = ("prs", "issues", "releases", "commit_activity", "contributors")
VALID_ENTITIES = (
    "prs",
    "issues",
    "releases",
    "commit_activity",
    "contributors",
    "commits",
    "commit_files",
    "pr_reviews",
    "pr_review_comments",
    "dependencies",
    "star_history",
    "workflow_runs",
)
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_MAX_ROWS_CAP = 5000
_DEPENDENT_ENTITIES = {"commit_files", "pr_reviews", "pr_review_comments"}
_DEPENDENT_PARENTS = {
    "commit_files": "commits",
    "pr_reviews": "prs",
    "pr_review_comments": "prs",
}


def _validate_repo(repo: str) -> None:
    if not _REPO_RE.match(repo) or len(repo) > 100:
        raise ValueError(f"invalid repo format: {repo!r} (expected 'owner/name')")


def _validate_entities(entities: list[str]) -> None:
    unknown = set(entities) - set(VALID_ENTITIES)
    if unknown:
        raise ValueError(f"unknown entity: {sorted(unknown)}; valid: {VALID_ENTITIES}")


def _summarize_rate_limit(last_remaining: int | None, last_reset: int | None) -> dict:
    if last_remaining is None:
        return {"remaining": None, "resets_in_minutes": None, "warning": None}

    warning = None
    if last_remaining < 500:
        warning = f"low: {last_remaining} remaining"

    resets_in = None
    if last_reset is not None:
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        resets_in = max(0, (last_reset - now_epoch) // 60)

    return {"remaining": last_remaining, "resets_in_minutes": resets_in, "warning": warning}


def _client_rate_meta(client) -> tuple[int | None, int | None]:
    last_meta = getattr(client, "last_meta", None)
    remaining = getattr(last_meta, "rate_limit_remaining", None)
    reset = getattr(last_meta, "rate_limit_reset", None)
    return (
        remaining if isinstance(remaining, int) else None,
        reset if isinstance(reset, int) else None,
    )


def _entity_phases(entities: list[str]) -> list[list[str]]:
    independent = [entity for entity in entities if entity not in _DEPENDENT_ENTITIES]
    dependent = [entity for entity in entities if entity in _DEPENDENT_ENTITIES]
    return [phase for phase in (independent, dependent) if phase]


def _db_path(conn: sqlite3.Connection) -> str:
    """Return the on-disk path of the connection's main database."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2]


def _run_entity(
    db_path: str,
    client,
    entity: str,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    """Run one entity loader in its own sqlite connection (thread-safe)."""
    worker_conn = connect(db_path)
    try:
        return _dispatch(worker_conn, client, entity, repo, range_start, range_end, max_rows)
    finally:
        worker_conn.close()


def load_repo(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    entities: list[str],
    range_spec: str,
    max_rows_per_entity: int = 500,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_repo(repo)
    _validate_entities(entities)

    max_rows = max(1, min(_MAX_ROWS_CAP, max_rows_per_entity))
    now = now or datetime.now(timezone.utc)
    range_start, range_end = parse_range(range_spec, now=now)

    load_repo_meta(conn, client, repo=repo)
    api_calls = 1

    fetched: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    failed_entities: set[str] = set()
    if entities:
        db_path = _db_path(conn)
        for phase in _entity_phases(entities):
            runnable = []
            for entity in phase:
                parent = _DEPENDENT_PARENTS.get(entity)
                if parent in entities and parent in failed_entities:
                    errors.append(
                        {
                            "entity": entity,
                            "error": f"skipped because parent entity {parent!r} failed",
                        }
                    )
                    failed_entities.add(entity)
                else:
                    runnable.append(entity)
            if not runnable:
                continue
            with ThreadPoolExecutor(max_workers=len(runnable)) as executor:
                futures = {
                    executor.submit(
                        _run_entity, db_path, client, entity, repo, range_start, range_end, max_rows
                    ): entity
                    for entity in runnable
                }
                for future in as_completed(futures):
                    entity = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        failed_entities.add(entity)
                        errors.append({"entity": entity, "error": str(exc)})
                        continue
                    fetched[entity] = result.row_count
                    api_calls += result.api_calls

    last_remaining, last_reset = _client_rate_meta(client)
    summary = {
        "repo": repo,
        "fetched": fetched,
        "api_calls_used": api_calls,
        "rate_limit_summary": _summarize_rate_limit(last_remaining, last_reset),
        "cached_at": now.isoformat(),
        "range_start": range_start,
        "range_end": range_end,
    }
    if errors:
        summary["errors"] = errors
    return summary


def _dispatch(
    conn: sqlite3.Connection,
    client,
    entity: str,
    repo: str,
    range_start: str,
    range_end: str,
    max_rows: int,
) -> LoaderResult:
    if entity == "prs":
        return load_prs(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "issues":
        return load_issues(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "releases":
        return load_releases(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "commit_activity":
        return load_commit_activity(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
        )
    if entity == "contributors":
        return load_contributors(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
        )
    if entity == "commits":
        return load_commits(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "commit_files":
        return load_commit_files(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "pr_reviews":
        return load_pr_reviews(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "pr_review_comments":
        return load_pr_review_comments(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "dependencies":
        return load_dependencies(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
        )
    if entity == "star_history":
        return load_star_history(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    if entity == "workflow_runs":
        return load_workflow_runs(
            conn,
            client,
            repo=repo,
            range_start=range_start,
            range_end=range_end,
            max_rows=max_rows,
        )
    raise ValueError(f"unhandled entity {entity}")
