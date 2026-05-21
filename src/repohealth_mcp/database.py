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
    "commits",
    "commit_files",
    "pr_reviews",
    "pr_review_comments",
    "dependencies",
    "star_history",
    "workflow_runs",
    "author_searches",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repos (
    repo              TEXT PRIMARY KEY,
    description       TEXT,
    default_branch    TEXT,
    stars             INTEGER,
    forks             INTEGER,
    open_issues_count INTEGER,
    created_at        TEXT,
    pushed_at         TEXT,
    archived          INTEGER,
    disabled          INTEGER,
    license           TEXT,
    funding_json      TEXT,
    has_sponsors      INTEGER,
    cached_at         TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS commits (
    repo            TEXT NOT NULL,
    sha             TEXT NOT NULL,
    author          TEXT,
    author_email    TEXT,
    committed_at    TEXT,
    message         TEXT,
    PRIMARY KEY (repo, sha)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_date   ON commits(repo, committed_at);
CREATE INDEX IF NOT EXISTS idx_commits_repo_author ON commits(repo, author);

CREATE TABLE IF NOT EXISTS commit_files (
    repo         TEXT NOT NULL,
    sha          TEXT NOT NULL,
    filename     TEXT NOT NULL,
    status       TEXT,
    additions    INTEGER,
    deletions    INTEGER,
    changes      INTEGER,
    PRIMARY KEY (repo, sha, filename)
);
CREATE INDEX IF NOT EXISTS idx_commit_files_repo_filename ON commit_files(repo, filename);

CREATE TABLE IF NOT EXISTS pr_reviews (
    repo            TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    id              INTEGER NOT NULL,
    reviewer        TEXT,
    state           TEXT,
    submitted_at    TEXT,
    PRIMARY KEY (repo, pr_number, id)
);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_repo_pr ON pr_reviews(repo, pr_number);

CREATE TABLE IF NOT EXISTS pr_review_comments (
    repo            TEXT NOT NULL,
    pr_number       INTEGER NOT NULL,
    id              INTEGER NOT NULL,
    reviewer        TEXT,
    body            TEXT,
    path            TEXT,
    line            INTEGER,
    position        INTEGER,
    created_at      TEXT,
    PRIMARY KEY (repo, pr_number, id)
);
CREATE INDEX IF NOT EXISTS idx_pr_review_comments_repo_pr ON pr_review_comments(repo, pr_number);

CREATE TABLE IF NOT EXISTS dependencies (
    repo             TEXT NOT NULL,
    package_name     TEXT NOT NULL,
    package_manager  TEXT,
    version          TEXT,
    license          TEXT,
    PRIMARY KEY (repo, package_name)
);

CREATE TABLE IF NOT EXISTS star_history (
    repo         TEXT NOT NULL,
    starred_at   TEXT NOT NULL,
    user         TEXT NOT NULL,
    PRIMARY KEY (repo, starred_at, user)
);
CREATE INDEX IF NOT EXISTS idx_star_history_repo_at ON star_history(repo, starred_at);

CREATE TABLE IF NOT EXISTS workflow_runs (
    repo              TEXT NOT NULL,
    id                INTEGER NOT NULL,
    workflow_name     TEXT,
    head_branch       TEXT,
    event             TEXT,
    status            TEXT,
    conclusion        TEXT,
    created_at        TEXT,
    run_started_at    TEXT,
    duration_seconds  INTEGER,
    PRIMARY KEY (repo, id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_repo_created ON workflow_runs(repo, created_at);

CREATE TABLE IF NOT EXISTS author_searches (
    login           TEXT NOT NULL,
    discovery       TEXT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    repos_json      TEXT NOT NULL,
    discovered_at   TEXT NOT NULL,
    PRIMARY KEY (login, discovery, range_start, range_end)
);
CREATE INDEX IF NOT EXISTS idx_author_searches_login ON author_searches(login);
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
    existing = {row[1] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    for col, decl in (("funding_json", "TEXT"), ("has_sponsors", "INTEGER")):
        if col not in existing:
            conn.execute(f"ALTER TABLE repos ADD COLUMN {col} {decl}")
