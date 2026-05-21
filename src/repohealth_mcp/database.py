"""SQLite connection management, schema, and UDFs."""

from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from platformdirs import user_data_dir

EXPECTED_TABLES = {
    "repos",
    "prs",
    "issues",
    "releases",
    "commit_activity",
    "contributors",
    "snapshots",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repos (
    repo            TEXT PRIMARY KEY,
    description     TEXT,
    default_branch  TEXT,
    stars           INTEGER,
    forks           INTEGER,
    open_issues_count INTEGER,
    created_at      TEXT,
    pushed_at       TEXT,
    archived        INTEGER,
    disabled        INTEGER,
    license         TEXT,
    cached_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prs (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,
    draft           INTEGER,
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    merged_at       TEXT,
    comments_count  INTEGER,
    base_branch     TEXT,
    PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_prs_repo_merged ON prs(repo, merged_at);
CREATE INDEX IF NOT EXISTS idx_prs_repo_author ON prs(repo, author);

CREATE TABLE IF NOT EXISTS issues (
    repo            TEXT NOT NULL,
    number          INTEGER NOT NULL,
    title           TEXT,
    author          TEXT,
    state           TEXT,
    state_reason    TEXT,
    labels          TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    closed_at       TEXT,
    comments_count  INTEGER,
    PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_issues_repo_state ON issues(repo, state);
CREATE INDEX IF NOT EXISTS idx_issues_repo_created ON issues(repo, created_at);

CREATE TABLE IF NOT EXISTS releases (
    repo            TEXT NOT NULL,
    id              INTEGER NOT NULL,
    tag_name        TEXT,
    name            TEXT,
    author          TEXT,
    published_at    TEXT,
    created_at      TEXT,
    draft           INTEGER,
    prerelease      INTEGER,
    PRIMARY KEY (repo, id)
);
CREATE INDEX IF NOT EXISTS idx_releases_repo_published ON releases(repo, published_at);

CREATE TABLE IF NOT EXISTS commit_activity (
    repo            TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,
    total_commits   INTEGER,
    mon INTEGER, tue INTEGER, wed INTEGER, thu INTEGER,
    fri INTEGER, sat INTEGER, sun INTEGER,
    PRIMARY KEY (repo, week_start_at)
);

CREATE TABLE IF NOT EXISTS contributors (
    repo            TEXT NOT NULL,
    author          TEXT NOT NULL,
    week_start_at   TEXT NOT NULL,
    commits         INTEGER,
    additions       INTEGER,
    deletions       INTEGER,
    PRIMARY KEY (repo, author, week_start_at)
);
CREATE INDEX IF NOT EXISTS idx_contributors_repo_author ON contributors(repo, author);

CREATE TABLE IF NOT EXISTS snapshots (
    repo            TEXT NOT NULL,
    entity          TEXT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    cached_at       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    PRIMARY KEY (repo, entity, range_start, range_end)
);
"""


class _MedianAggregate:
    """SQLite aggregate UDF: median, ignoring NULLs."""

    def __init__(self) -> None:
        self._values: list[float] = []

    def step(self, value: float | None) -> None:
        if value is not None:
            self._values.append(value)

    def finalize(self) -> float | None:
        if not self._values:
            return None
        return statistics.median(self._values)


def sqlite_path() -> Path:
    """Return path to the cross-platform user-data sqlite file."""
    data_dir = Path(user_data_dir("repohealth-mcp", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "repohealth.sqlite"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a sqlite connection with foreign keys + UDFs registered."""
    if path is None:
        path = sqlite_path()
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_aggregate("median", 1, _MedianAggregate)
    return conn


def connect_readonly(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a sqlite connection in read-only mode (for run_sql safety)."""
    if path is None:
        path = sqlite_path()
    resolved = Path(path).expanduser().resolve()
    uri = f"{resolved.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.create_aggregate("median", 1, _MedianAggregate)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes if missing. Idempotent."""
    conn.executescript(SCHEMA_SQL)
