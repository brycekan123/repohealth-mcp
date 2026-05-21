import pytest

import repohealth_mcp.server as server_mod


def test_main_callable_exists() -> None:
    assert callable(server_mod.main)


def test_module_exposes_mcp_instance() -> None:
    assert server_mod.mcp is not None
    assert server_mod.mcp.name == "repohealth"


@pytest.mark.asyncio
async def test_server_registers_expected_tools() -> None:
    tools = await server_mod.mcp.list_tools()
    listed = [tool.name for tool in tools]
    assert {
        "plan_data_load",
        "check_coverage",
        "load_repo",
        "refresh_repo",
        "load_repos",
        "load_author_activity",
        "search_repos",
        "run_sql",
        "get_loaded_tables",
        "list_loaded_repos",
    }.issubset(listed)


def test_server_exposes_v3_tool_functions() -> None:
    assert callable(server_mod.load_repos)
    assert callable(server_mod.load_author_activity)
    assert callable(server_mod.search_repos)


def test_mcp_instructions_mention_author_activity() -> None:
    text = server_mod.MCP_INSTRUCTIONS.lower()
    assert "author" in text or "user" in text
    assert "cross-repo" in text or "across" in text


def test_mcp_instructions_avoid_reserved_test_prompts() -> None:
    text = server_mod.MCP_INSTRUCTIONS.lower()
    for forbidden in ("karpathy", "tkdodo", "react-query", "vue", "solid"):
        assert forbidden not in text, f"reserved test-prompt token {forbidden!r} found"
