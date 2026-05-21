from unittest.mock import MagicMock

import pytest

from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.star_history import load_star_history


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_load_star_history_writes_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {"starred_at": "2026-04-01T00:00:00Z", "user": {"login": "a"}},
            {"starred_at": "2026-04-15T00:00:00Z", "user": {"login": "b"}},
            {"starred_at": "2025-12-31T00:00:00Z", "user": {"login": "c"}},
        ]
    )
    result = load_star_history(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    assert result.row_count == 2


def test_load_star_history_uses_star_media_type(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    load_star_history(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=500,
    )
    call_kwargs = client.paginate.call_args.kwargs
    assert call_kwargs.get("media_type") == "application/vnd.github.star+json"


def test_load_star_history_respects_max_rows(conn) -> None:
    client = MagicMock()
    client.paginate.return_value = iter(
        [
            {"starred_at": f"2026-04-{i:02d}T00:00:00Z", "user": {"login": f"u{i}"}}
            for i in range(1, 11)
        ]
    )
    result = load_star_history(
        conn,
        client,
        repo="o/r",
        range_start="2026-01-01",
        range_end="2026-06-01",
        max_rows=5,
    )
    assert result.row_count == 5
