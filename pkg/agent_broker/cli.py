"""
Keep command entry points thin and secret-bearing exceptions out of user output.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from agent_broker import contracts, demo, mcp_server
from agent_broker.approval import approve
from agent_broker.engine import Broker
from agent_broker.exceptions import AuditFailure, ProviderFailure, Rejected
from agent_broker.ledger import Ledger
from agent_broker.lifecycle import running
from agent_broker.providers import HealthExecutor, OnePasswordProvider
from agent_broker.transport import BrokerServer, Client

if TYPE_CHECKING:
    from types import FrameType


def parser() -> argparse.ArgumentParser:
    """
    Describe operator, agent, and synthetic workflows with explicit file ownership.

    Returns:
        argparse.ArgumentParser: Command parser.
    """
    root = argparse.ArgumentParser(prog="agent-broker")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Run a bounded synthetic demo with two identities")
    serve = commands.add_parser("serve", help="Start the operator-owned HTTPS broker")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8443)
    serve.add_argument("--database", type=Path, required=True)
    serve.add_argument("--client-ca", type=Path, required=True)
    serve.add_argument("--destination-ca", type=Path)
    serve.add_argument("--op", type=Path, required=True, help="Absolute trusted 1Password CLI path")
    grant = commands.add_parser("approve", help="Create one exact operator-approved request")
    grant.add_argument("--principal", required=True)
    grant.add_argument("--operation", required=True)
    grant.add_argument("--ttl", type=int, default=300)
    config = commands.add_parser("config", help="Validate local contracts")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    lint = config_commands.add_parser("lint")

    for command in (serve, grant, lint):
        command.add_argument("--policy", type=Path, required=True)
        command.add_argument("--approvals", type=Path, required=True)
    mcp = commands.add_parser("mcp", help="Expose an authenticated broker through MCP stdio")
    mcp.add_argument("--url", required=True)
    mcp.add_argument("--ca", type=Path, required=True)

    for command in (serve, mcp):
        command.add_argument("--cert", type=Path, required=True)
        command.add_argument("--key", type=Path, required=True)
    return root


def export(event: dict[str, object]) -> None:
    """
    Write only allowlisted audit fields to stdout in server mode.

    Args:
        event (dict[str, object]): Durable secret-free audit event.

    Returns:
        None: Flush one complete event.
    """
    print(contracts.encode(event).decode(), flush=True)


def serve(args: argparse.Namespace) -> None:
    """
    Drain active requests on SIGINT or SIGTERM without starting new work.

    Args:
        args (argparse.Namespace): Validated operator command arguments.

    Returns:
        None: Stop the listener and join owned worker threads.
    """
    contracts.policy(args.policy)
    contracts.approvals(args.approvals)
    broker = Broker(
        args.policy, args.approvals, Ledger(args.database, export), OnePasswordProvider(args.op), HealthExecutor(args.destination_ca)
    )
    server = BrokerServer((args.host, args.port), broker, args.cert, args.key, args.client_ca)
    stop = threading.Event()

    def shutdown(signum: int, frame: FrameType | None) -> None:
        """
        Notify the owner thread without deadlocking HTTPServer.shutdown.

        Args:
            signum (int): Delivered termination signal.
            frame (FrameType | None): Interrupted Python frame.

        Returns:
            None: Request graceful shutdown.
        """
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, shutdown)
    with running(server):
        stop.wait()


def main() -> int:
    """
    Dispatch commands and redact provider, TLS, and operator-file diagnostics.

    Returns:
        int: Zero on success, two for a safe operational error.
    """
    args = parser().parse_args()
    try:
        match args.command:
            case "demo":
                export(demo.run())
            case "serve":
                serve(args)
            case "mcp":
                asyncio.run(mcp_server.run(Client(args.url, args.ca, args.cert, args.key)))
            case "approve":
                export(contracts.data(approve(args.policy, args.approvals, args.principal, args.operation, args.ttl)))
            case "config":
                contracts.policy(args.policy)
                contracts.approvals(args.approvals)
                print("Configuration valid")
    except (Rejected, ProviderFailure, AuditFailure, OSError, ValueError):
        print(
            "Broker configuration or operation failed. Check operator-owned inputs; sensitive diagnostics were withheld.", file=sys.stderr
        )
        return 2
    return 0
