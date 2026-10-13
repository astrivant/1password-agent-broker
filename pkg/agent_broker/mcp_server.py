"""
Expose approved capabilities through MCP 2 without loading a credential provider.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from agent_broker.contracts import data, encode, schema
from agent_broker.models import Result

if TYPE_CHECKING:
    from agent_broker.transport import Client


async def run(client: Client) -> None:
    """
    Serve structured status on stdio while retaining broker-side enforcement.

    Args:
        client (Client): Certificate-authenticated broker transport.

    Returns:
        None: Finish after the MCP client disconnects.
    """

    async def list_tools(
        context: ServerRequestContext[dict[str, object], object], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        """
        Describe closed capability and cancellation contracts.

        Args:
            context (ServerRequestContext[dict[str, object], object]): MCP request context.
            params (types.PaginatedRequestParams | None): Optional pagination state.

        Returns:
            types.ListToolsResult: Bounded execution, cancellation, and status tools.
        """
        return types.ListToolsResult(
            tools=[
                types.Tool(name=name, description=description, input_schema=schema("request"), output_schema=schema("result"))
                for name, description in (
                    ("execute_approved", "Execute an operator-approved capability using its request and approval IDs."),
                    ("cancel_approved", "Cancel a request you own. Cancellation cannot undo an operation already submitted."),
                    ("inspect_approved", "Inspect an existing request without executing it, including after its approval expires."),
                )
            ]
        )

    async def call_tool(
        context: ServerRequestContext[dict[str, object], object], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        """
        Forward input as data and mark non-success outcomes as tool failures.

        Args:
            context (ServerRequestContext[dict[str, object], object]): MCP request context.
            params (types.CallToolRequestParams): Tool name and untrusted arguments.

        Returns:
            types.CallToolResult: Schema-validated status without raw remote output.
        """
        if params.name not in ("execute_approved", "cancel_approved", "inspect_approved"):
            result = Result("denied", "invalid_request")
        else:
            # Keep blocking broker I/O off the MCP loop without moving credential resolution into this process.
            result = await asyncio.to_thread(
                client.call, params.arguments, cancel=params.name == "cancel_approved", inspect=params.name == "inspect_approved"
            )

        # Both MCP representations carry the same closed result, never downstream headers or bodies.
        payload = data(result)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=encode(payload).decode())],
            structured_content=payload,
            is_error=result.state != "completed" or result.code != "healthy",
        )

    app = Server("1password-agent-broker", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (reader, writer):
        await app.run(reader, writer, app.create_initialization_options())
