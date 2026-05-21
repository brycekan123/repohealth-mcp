import sqlite3
from pathlib import Path

import pytest

from repohealth_mcp.database import (
    EXPECTED_TABLES,
    connect,
    connect_readonly,
    init_schema,
    sqlite_path,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


def test_init_schema_creates_all_tables(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(names)


def test_init_schema_is_idempotent(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    init_schema(conn)  # should not raise
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    assert cur.fetchone()[0] >= len(EXPECTED_TABLES)


def test_median_udf_registered(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO prs (repo, number) VALUES (?, ?)",
        [("a/b", 1), ("a/b", 2), ("a/b", 3), ("a/b", 4), ("a/b", 5)],
    )
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] == 3


def test_median_udf_handles_even_count(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO prs (repo, number) VALUES (?, ?)",
        [("a/b", 1), ("a/b", 2), ("a/b", 3), ("a/b", 4)],
    )
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] == 2.5


def test_median_udf_ignores_nulls(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 1, NULL)")
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 2, 10)")
    conn.execute("INSERT INTO prs (repo, number, comments_count) VALUES ('a/b', 3, 20)")
    cur = conn.execute("SELECT median(comments_count) FROM prs")
    assert cur.fetchone()[0] == 15


def test_median_udf_returns_none_for_empty(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("SELECT median(number) FROM prs")
    assert cur.fetchone()[0] is None


def test_connect_readonly_reads_existing_database(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.execute("INSERT INTO repos (repo, cached_at) VALUES ('a/b', '2026-05-20T00:00:00Z')")
    conn.close()

    readonly = connect_readonly(db_path)
    cur = readonly.execute("SELECT repo FROM repos")

    assert cur.fetchone()[0] == "a/b"


def test_connect_readonly_rejects_writes(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.close()

    readonly = connect_readonly(db_path)

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.execute("INSERT INTO repos (repo, cached_at) VALUES ('a/b', '2026-05-20T00:00:00Z')")


def test_connect_readonly_handles_reserved_uri_characters(tmp_path: Path) -> None:
    reserved_path = tmp_path / "db #1?.sqlite"
    conn = connect(reserved_path)
    init_schema(conn)
    conn.execute("INSERT INTO repos (repo, cached_at) VALUES ('a/b', '2026-05-20T00:00:00Z')")
    conn.close()

    readonly = connect_readonly(str(reserved_path))
    cur = readonly.execute("SELECT repo FROM repos")

    assert cur.fetchone()[0] == "a/b"


def test_connect_sets_busy_timeout(db_path: Path) -> None:
    """Concurrent writers from parallel loaders need busy_timeout to avoid 'database is locked'."""
    conn = connect(db_path)
    timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout_ms >= 1000, f"busy_timeout should be >= 1s, got {timeout_ms}ms"


def test_sqlite_path_uses_platformdirs() -> None:
    p = sqlite_path()
    assert isinstance(p, Path)
    assert p.name == "repohealth.sqlite"


def test_prs_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cur = conn.execute("PRAGMA table_info(prs)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {
        "repo",
        "number",
        "title",
        "author",
        "state",
        "draft",
        "created_at",
        "updated_at",
        "closed_at",
        "merged_at",
        "comments_count",
        "base_branch",
    }
    assert expected.issubset(cols)


def test_snapshots_table_has_composite_pk(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
        VALUES ('a/b', 'prs', '2025-01-01', '2025-06-01', '2026-05-20T00:00:00Z', 100)
    """
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO snapshots (repo, entity, range_start, range_end, cached_at, row_count)
            VALUES ('a/b', 'prs', '2025-01-01', '2025-06-01', '2026-05-20T00:00:00Z', 200)
        """
        )


def test_commits_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(commits)").fetchall()}
    expected = {"repo", "sha", "author", "author_email", "committed_at", "message"}
    assert expected.issubset(cols)


def test_commit_files_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(commit_files)").fetchall()}
    expected = {"repo", "sha", "filename", "status", "additions", "deletions", "changes"}
    assert expected.issubset(cols)


def test_pr_reviews_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_reviews)").fetchall()}
    expected = {"repo", "pr_number", "id", "reviewer", "state", "submitted_at"}
    assert expected.issubset(cols)


def test_pr_review_comments_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pr_review_comments)").fetchall()}
    expected = {
        "repo",
        "pr_number",
        "id",
        "reviewer",
        "body",
        "path",
        "line",
        "position",
        "created_at",
    }
    assert expected.issubset(cols)


def test_dependencies_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(dependencies)").fetchall()}
    expected = {"repo", "package_name", "package_manager", "version", "license"}
    assert expected.issubset(cols)


def test_star_history_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(star_history)").fetchall()}
    expected = {"repo", "starred_at", "user"}
    assert expected.issubset(cols)


def test_workflow_runs_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    expected = {
        "repo",
        "id",
        "workflow_name",
        "head_branch",
        "event",
        "status",
        "conclusion",
        "created_at",
        "run_started_at",
        "duration_seconds",
    }
    assert expected.issubset(cols)


def test_repos_table_has_funding_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}
    assert "funding_json" in cols
    assert "has_sponsors" in cols


def test_author_searches_table_has_expected_columns(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(author_searches)").fetchall()}
    expected = {"login", "discovery", "range_start", "range_end", "repos_json", "discovered_at"}
    assert expected.issubset(cols)


def test_author_searches_in_expected_tables_set() -> None:
    assert "author_searches" in EXPECTED_TABLES
