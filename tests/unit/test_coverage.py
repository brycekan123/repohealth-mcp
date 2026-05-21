import pytest

from repohealth_mcp.coverage import CoverageStatus, check_coverage
from repohealth_mcp.database import connect, init_schema
from repohealth_mcp.loaders.base import record_snapshot


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite")
    init_schema(c)
    return c


def test_coverage_miss_when_no_snapshot(conn) -> None:
    status = check_coverage(
        conn,
        repo="o/r",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
    )
    assert status.cached is False
    assert status.cached_at is None
    assert status.rows == 0


def test_coverage_hit_after_snapshot_recorded(conn) -> None:
    record_snapshot(
        conn,
        repo="o/r",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
        row_count=42,
        cached_at="2026-05-20T12:00:00Z",
    )
    status = check_coverage(
        conn,
        repo="o/r",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
    )
    assert status.cached is True
    assert status.cached_at == "2026-05-20T12:00:00Z"
    assert status.rows == 42


def test_coverage_returns_dataclass(conn) -> None:
    status = check_coverage(
        conn,
        repo="o/r",
        entity="prs",
        range_start="2025-01-01",
        range_end="2025-06-01",
    )
    assert isinstance(status, CoverageStatus)
