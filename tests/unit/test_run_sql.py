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
    assert result["rows"] == [{"number": 1, "author": "alice"}, {"number": 2, "author": "bob"}]


def test_run_sql_with_aggregate(db_path) -> None:
    result = run_sql(db_path, "SELECT COUNT(*) AS n FROM prs")
    assert result["rows"] == [{"n": 3}]


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
    assert result["rows"] == [{"n": 3}]


def test_run_sql_caps_at_1000_rows(db_path) -> None:
    conn = connect(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO issues (repo, number) VALUES (?, ?)",
        [("a/b", i) for i in range(1500)],
    )
    conn.close()
    result = run_sql(db_path, "SELECT number FROM issues")
    assert len(result["rows"]) == 1000


def test_run_sql_surfaces_syntax_error(db_path) -> None:
    with pytest.raises(RunSqlError):
        run_sql(db_path, "SELCT * FROM prs")


def test_run_sql_uses_median_udf(db_path) -> None:
    result = run_sql(db_path, "SELECT median(number) AS m FROM prs WHERE repo='a/b'")
    assert result["rows"] == [{"m": 1.5}]
