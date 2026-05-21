from repohealth_mcp.server import get_schema_resource, get_signals_resource


def test_schema_resource_lists_all_tables() -> None:
    content = get_schema_resource()
    for table in (
        "repos",
        "prs",
        "issues",
        "releases",
        "commit_activity",
        "contributors",
        "snapshots",
    ):
        assert "CREATE TABLE" in content
        assert table in content


def test_signals_resource_has_at_least_5_signals() -> None:
    content = get_signals_resource()
    assert content.count("##") >= 5
    assert "median" in content.lower() or "average" in content.lower()


def test_signals_resource_includes_sql_examples() -> None:
    content = get_signals_resource()
    assert "```sql" in content
    assert "SELECT" in content
