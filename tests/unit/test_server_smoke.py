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
        "run_sql",
        "get_loaded_tables",
        "list_loaded_repos",
    }.issubset(listed)
