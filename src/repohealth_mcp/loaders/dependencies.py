"""Loader for /repos/{repo}/dependency-graph/sbom."""

from __future__ import annotations

import sqlite3

from ..github_client import GitHubError
from .base import LoaderResult, record_snapshot, upsert_rows


def _split_name(raw: str | None) -> tuple[str | None, str]:
    """Split 'manager:name' into (manager, name). Names without a prefix pass through."""
    if not raw:
        return None, ""
    if ":" in raw:
        manager, _, name = raw.partition(":")
        return manager, name
    return None, raw


def _shape(repo: str, pkg: dict) -> dict:
    manager, name = _split_name(pkg.get("name"))
    license_name = pkg.get("licenseConcluded")
    return {
        "repo": repo,
        "package_name": name,
        "package_manager": manager,
        "version": pkg.get("versionInfo"),
        "license": license_name if license_name not in (None, "NOASSERTION") else None,
    }


def load_dependencies(
    conn: sqlite3.Connection,
    client,
    *,
    repo: str,
    range_start: str,
    range_end: str,
) -> LoaderResult:
    try:
        body, _meta = client.get(f"/repos/{repo}/dependency-graph/sbom")
    except GitHubError as exc:
        if exc.status == 404:
            record_snapshot(
                conn,
                repo=repo,
                entity="dependencies",
                range_start=range_start,
                range_end=range_end,
                row_count=0,
            )
            return LoaderResult(entity="dependencies", row_count=0, api_calls=1)
        raise

    packages = ((body or {}).get("sbom") or {}).get("packages") or []
    rows = [_shape(repo, package) for package in packages if package.get("name")]

    upsert_rows(conn, "dependencies", rows, pk=("repo", "package_name"))
    record_snapshot(
        conn,
        repo=repo,
        entity="dependencies",
        range_start=range_start,
        range_end=range_end,
        row_count=len(rows),
    )
    return LoaderResult(entity="dependencies", row_count=len(rows), api_calls=1)
