"""
Own one SDK session in a short-lived process whose private pipes belong to the broker.
"""

from __future__ import annotations

import asyncio
import json
import sys
from importlib.metadata import version

from onepassword.client import Client

from agent_broker.providers import valid_secret


async def resolve(token: str, reference: str) -> str:
    """
    Authenticate with one explicit service account and resolve one operator-selected field.

    Args:
        token (str): Bootstrap token received on the private broker pipe.
        reference (str): Exact field reference from operator policy.

    Returns:
        str: Resolved value, still within the trusted worker process.
    """
    client = await Client.authenticate(
        auth=token,
        integration_name="1password-agent-broker",
        integration_version=version("1password-agent-broker"),
    )
    return await client.secrets.resolve(reference)


def main() -> int:
    """
    Emit only a validated credential or an empty failed response on the broker-owned pipe.

    Returns:
        int: Zero for a usable credential; two for malformed input or SDK failure.
    """
    try:
        # Keep the pipe protocol closed and bounded; stdout is reserved for the validated credential alone.
        payload: object = json.loads(sys.stdin.buffer.read(131073))
        if not isinstance(payload, dict) or set(payload) != {"token", "reference"}:
            return 2
        token, reference = payload["token"], payload["reference"]
        if not isinstance(token, str) or not token or not isinstance(reference, str) or not reference:
            return 2

        # SDK 0.4.1 has no public close method; process exit owns native session cleanup.
        secret = asyncio.run(resolve(token, reference))
        if not valid_secret(secret):
            return 2
        sys.stdout.write(secret)
        sys.stdout.flush()
    except Exception:
        # The SDK raises plain Exception for some provider errors. Never forward their messages.
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
