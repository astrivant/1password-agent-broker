"""
Verify the installed SDK in a clean environment that excludes the server runtime.
"""

from __future__ import annotations

from importlib.metadata import version
from importlib.util import find_spec
from uuid import uuid4


def main() -> None:
    """
    Check import closure and a canonical request round trip without contacting a broker.

    Returns:
        None: The standalone client imports and validates with no service dependencies.
    """
    from agent_broker_sdk import Binding, Request
    from agent_broker_sdk.contracts import data, parse_request

    for module in ("agent_broker", "flask", "onepassword", "mcp", "psycopg", "casbin"):
        assert find_spec(module) is None, f"Unexpected service dependency: {module}"
    identifiers = [str(uuid4()) for _ in range(9)]
    request = Request(
        identifiers[0],
        identifiers[1],
        "public",
        identifiers[2],
        Binding(identifiers[3], identifiers[4], identifiers[5], kind=1),
        identifiers[6],
        identifiers[7],
        identifiers[8],
        "",
    )
    assert parse_request(data(request)) == request
    print(f"Standalone SDK {version('1password-agent-broker-sdk')} imports and validates without the server")


if __name__ == "__main__":
    main()
