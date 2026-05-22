import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.tools.run_sql import RunSqlError, run_sql


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = connect(path)
    init_schema(conn)
    conn.executemany(
        "INSERT INTO prs (repo, number, author) VALUES (?, ?, ?)",
        [("a/b", 1, "alice"), ("a/b", 2, "bob"), ("c/d", 1, "alice")],
    )
    conn.close()
    return path


def test_run_sql_returns_columns_and_rows(db_path) -> None:
    result = run_sql(db_path, "SELECT number, author FROM prs WHERE repo='a/b' ORDER BY number")
    assert result["columns"] == ["number", "author"]
    assert result["rows"] == [[1, "alice"], [2, "bob"]]


def test_run_sql_with_aggregate(db_path) -> None:
    result = run_sql(db_path, "SELECT COUNT(*) AS n FROM prs")
    assert result["rows"] == [[3]]


def test_run_sql_rejects_insert(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "INSERT INTO prs (repo, number) VALUES ('x/y', 1)")


def test_run_sql_rejects_update(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "UPDATE prs SET author='x'")


def test_run_sql_rejects_delete(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "DELETE FROM prs")


def test_run_sql_rejects_drop(db_path) -> None:
    with pytest.raises(RunSqlError, match="read-only"):
        run_sql(db_path, "DROP TABLE prs")


def test_run_sql_rejects_attach(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "ATTACH DATABASE 'foo.db' AS f")


def test_run_sql_rejects_pragma(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "PRAGMA table_info(prs)")


def test_run_sql_allows_with_cte(db_path) -> None:
    result = run_sql(db_path, "WITH a AS (SELECT * FROM prs) SELECT COUNT(*) AS n FROM a")
    assert result["rows"] == [[3]]


def test_run_sql_cte_with_trailing_limit_works(db_path) -> None:
    """Bug 1: CTE queries with a trailing LIMIT must not break pagination."""
    conn = connect(db_path)
    conn.executemany(
        "INSERT INTO issues (repo, number, author) VALUES (?, ?, ?)",
        [("a/b", i + 100, f"user{i}") for i in range(20)],
    )
    conn.close()
    result = run_sql(
        db_path,
        "WITH cte AS (SELECT author, COUNT(*) AS n FROM issues GROUP BY author) "
        "SELECT author, n FROM cte ORDER BY n DESC LIMIT 5",
    )
    assert "error" not in result
    assert len(result["rows"]) <= 5


def test_run_sql_explicit_author_email_select_returns_column(db_path) -> None:
    """Bug 2: explicit single-column SELECT of author_email must return it."""
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES ('a/b', 'abc1234', 'alice', 'alice@example.com', '2024-01-01', 'fix')"
    )
    conn.close()
    result = run_sql(db_path, "SELECT author_email FROM commits")
    assert result["columns"] == ["author_email"]
    assert result["rows"] == [["alice@example.com"]]


def test_run_sql_comment_prefixed_cte_works(db_path) -> None:
    """Bug 3: queries with a leading comment must be classified correctly."""
    result = run_sql(db_path, "-- a comment\nWITH a AS (SELECT 1 AS n) SELECT * FROM a")
    assert "error" not in result
    assert result["rows"] == [[1]]


def test_run_sql_query_with_trailing_tab_works(db_path) -> None:
    """Bug 4: queries terminated by tab/CR must not produce syntax errors."""
    result = run_sql(db_path, "SELECT number FROM prs WHERE repo='a/b';\t")
    assert "error" not in result
    assert len(result["rows"]) == 2


def test_run_sql_default_cap_is_200(db_path) -> None:
    conn = connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
        [("a/b", i) for i in range(300)],
    )
    conn.close()
    result = run_sql(db_path, "SELECT number FROM issues")
    assert len(result["rows"]) == 200


def test_run_sql_has_more_true_when_results_exceed_cap(db_path) -> None:
    conn = connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
        [("a/b", i) for i in range(300)],
    )
    conn.close()
    result = run_sql(db_path, "SELECT number FROM issues", row_cap=200)
    assert result["has_more"] is True
    assert len(result["rows"]) == 200


def test_run_sql_has_more_false_when_results_fit(db_path) -> None:
    result = run_sql(db_path, "SELECT number FROM prs WHERE repo='a/b'")
    assert result["has_more"] is False


def test_run_sql_note_present_when_truncated(db_path) -> None:
    conn = connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
        [("a/b", i) for i in range(10)],
    )
    conn.close()
    result = run_sql(db_path, "SELECT number FROM issues", row_cap=5)
    assert result["has_more"] is True
    assert result["note"] is not None
    assert "offset" in result["note"]


def test_run_sql_note_absent_when_not_truncated(db_path) -> None:
    result = run_sql(db_path, "SELECT number FROM prs WHERE repo='a/b'")
    assert result.get("note") is None


def test_run_sql_offset_skips_rows(db_path) -> None:
    conn = connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
        [("a/b", i) for i in range(10)],
    )
    conn.close()
    page1 = run_sql(db_path, "SELECT number FROM issues ORDER BY number", row_cap=5, offset=0)
    page2 = run_sql(db_path, "SELECT number FROM issues ORDER BY number", row_cap=5, offset=5)
    all_numbers = [row[0] for row in page1["rows"]] + [row[0] for row in page2["rows"]]
    assert len(all_numbers) == 10
    assert all_numbers == sorted(all_numbers)


def test_run_sql_strips_author_email_from_select_star(db_path) -> None:
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO commits (repo, sha, author, author_email, committed_at, message) "
        "VALUES ('a/b', 'abc1234', 'alice', 'alice@example.com', '2024-01-01', 'fix bug')"
    )
    conn.close()
    result = run_sql(db_path, "SELECT * FROM commits")
    assert "author_email" not in result["columns"]
    # Each row is a list of values matching columns
    assert len(result["rows"][0]) == len(result["columns"])
    assert "alice@example.com" not in result["rows"][0]


def test_run_sql_surfaces_syntax_error(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "SELCT * FROM prs")


def test_run_sql_uses_median_udf(db_path) -> None:
    result = run_sql(db_path, "SELECT median(number) AS m FROM prs WHERE repo='a/b'")
    assert result["rows"] == [[1.5]]
