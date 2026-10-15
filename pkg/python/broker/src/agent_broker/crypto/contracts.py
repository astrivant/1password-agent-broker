"""
Validate service-only key requests and construct their shared authenticated context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_broker_sdk import contracts as sdk_contracts
from agent_broker_sdk.exceptions import BrokerError

from agent_broker import contracts
from agent_broker.crypto.models import Binding, Policy, Request
from agent_broker.exceptions import Rejected

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["aad", "decode", "load_policy", "parse_request"]


def aad(binding: Binding) -> bytes:
    """
    Preserve the public runtime import for the canonical SDK context contract.

    Args:
        binding (Binding): Independently validated record context.

    Returns:
        bytes: Version-one authenticated context.
    """
    return sdk_contracts.aad(binding)


def decode(value: str, maximum: int) -> bytes:
    """
    Translate SDK validation failures into the server's closed diagnostic boundary.

    Args:
        value (str): Untrusted base64 bytes.
        maximum (int): Decoded size budget.

    Returns:
        bytes: Bounded canonical payload.

    Raises:
        Rejected: The payload is invalid.
    """
    try:
        return sdk_contracts.decode(value, maximum)
    except BrokerError:
        raise Rejected("Invalid crypto payload") from None


def parse_request(value: object) -> Request:
    """
    Use the same request contract as clients before applying server-owned policy.

    Args:
        value (object): Untrusted decoded request.

    Returns:
        Request: Validated wire model.

    Raises:
        Rejected: The request is invalid.
    """
    try:
        return sdk_contracts.parse_request(value)
    except BrokerError:
        raise Rejected("Invalid crypto request") from None


def load_policy(path: Path) -> tuple[Policy, str]:
    """
    Reload operator custody and grants with their immutable snapshot digest.

    Args:
        path (Path): Operator-controlled policy file, containing references rather than secrets.

    Returns:
        tuple[Policy, str]: Validated policy and exact canonical revision.

    Raises:
        Rejected: The policy is invalid or references missing key generations.
    """
    raw = contracts.read(path)
    policy = contracts.structure(raw, Policy, "crypto-policy")
    if any(set(grant.keys) - policy.keys.keys() for grant in policy.grants.values()):
        raise Rejected("Invalid crypto key scope")
    return policy, contracts.digest(raw)
