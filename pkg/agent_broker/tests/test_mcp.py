"""
Exercise the actual MCP stdio subprocess against the certificate-authenticated broker.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING

from agent_broker import contracts
from mcp import ClientSession, StdioServerParameters, stdio_client

if TYPE_CHECKING:
    from agent_broker.testing.scenario import Scenario


def test_stdio_subprocess(fixture: Scenario) -> None:
    """
    Discover schemas, execute, retry, and reject injected fields through MCP 2.

    Args:
        fixture (Scenario): Synthetic TLS broker and two identities.

    Returns:
        None: Assert structured responses never contain generated canaries.
    """

    async def exercise() -> None:
        """
        Own the real adapter subprocess and session lifetime.

        Returns:
            None: Complete MCP initialization and bounded tool calls.
        """
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "agent_broker",
                "mcp",
                "--url",
                fixture.url,
                "--ca",
                str(fixture.root / "ca.pem"),
                "--cert",
                str(fixture.root / "alpha.pem"),
                "--key",
                str(fixture.root / "alpha.key"),
            ],
            env={"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"},
        )
        with (fixture.root / "mcp.stderr").open("w+") as diagnostics:
            async with stdio_client(parameters, errlog=diagnostics) as (reader, writer), ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"execute_approved", "cancel_approved", "inspect_approved"}
                assert all(tool.output_schema for tool in tools.tools)
                payload = contracts.data(fixture.request())
                first = await session.call_tool("execute_approved", payload)
                replay = await session.call_tool("execute_approved", payload)
                status = await session.call_tool("inspect_approved", payload)
                denied = await session.call_tool("execute_approved", {**payload, "reference": "op://other/item/secret"})
                assert not first.is_error and first.structured_content is not None
                assert first.structured_content["code"] == "healthy"
                assert replay.structured_content is not None and replay.structured_content["replayed"] is True
                assert status.structured_content == replay.structured_content
                assert denied.is_error
                observed = json.dumps([first.model_dump(), replay.model_dump(), status.model_dump(), denied.model_dump()])
            diagnostics.seek(0)
            observed += diagnostics.read()
        assert not any(token in observed for token in fixture.provider.secrets.values())
        assert len(fixture.destination_calls) == 1

    asyncio.run(exercise())
