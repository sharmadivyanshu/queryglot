"""MCP surface: tools registered with real descriptions."""

import pytest


@pytest.mark.asyncio
async def test_tools_are_registered():
    from queryglot.mcp_server import server

    tools = {t.name: t for t in await server.list_tools()}
    assert set(tools) >= {"search", "list_schema", "refresh_schema"}
    assert "abstain" in tools["search"].description.lower()


def test_engine_requires_a_backend():
    from queryglot.engine import Engine

    with pytest.raises(ValueError):
        Engine([])
