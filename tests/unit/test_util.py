import pytest

from repohealth_mcp.util import normalize_repo


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("tanstack/query", "tanstack/query"),
        ("  tanstack/query  ", "tanstack/query"),
        ("https://github.com/tanstack/query", "tanstack/query"),
        ("https://github.com/tanstack/query.git", "tanstack/query"),
        ("http://github.com/tanstack/query", "tanstack/query"),
        ("github.com/tanstack/query", "tanstack/query"),
        ("git@github.com:tanstack/query.git", "tanstack/query"),
        ("https://github.com/tanstack/query/pulls/123", "tanstack/query"),
        ("https://github.com/tanstack/query/tree/main", "tanstack/query"),
        ("owner-with-dash/name.with.dots", "owner-with-dash/name.with.dots"),
    ],
)
def test_normalize_repo_canonicalizes_known_shapes(raw, expected):
    assert normalize_repo(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no-slash",
        "https://github.com/",
        "https://example.com/foo/bar",
        "git@gitlab.com:foo/bar.git",
    ],
)
def test_normalize_repo_rejects_unparseable(raw):
    with pytest.raises(ValueError):
        normalize_repo(raw)
