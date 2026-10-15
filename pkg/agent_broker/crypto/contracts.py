"""
Validate service-only key requests and construct their shared authenticated context.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING
from uuid import UUID

from agent_broker import contracts
from agent_broker.crypto.models import Binding, Policy, Request
from agent_broker.exceptions import Rejected

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["aad", "decode", "load_policy", "parse_request"]


def aad(binding: Binding) -> bytes:
    """
    Encode the single versioned associated-data contract shared by broker and service SDK.

    Args:
        binding (Binding): Validated expected record context, never inferred from ciphertext.

    Returns:
        bytes: Domain-separated canonical JSON context; payload encoding remains independent.
    """
    return b"agent-broker-record-v1\x00" + contracts.encode(contracts.data(binding))


def decode(value: str, maximum: int) -> bytes:
    """
    Reject noncanonical or oversized base64 without reflecting input in diagnostics.

    Args:
        value (str): Untrusted encoded bytes.
        maximum (int): Maximum decoded size.

    Returns:
        bytes: Canonically encoded bounded payload.

    Raises:
        Rejected: Encoding or size is invalid.
    """
    try:
        if len(value) > ((maximum + 2) // 3) * 4:
            raise Rejected("Invalid crypto payload")
        result = base64.b64decode(value, validate=True)
        if len(result) > maximum or base64.b64encode(result).decode() != value:
            raise Rejected("Invalid crypto payload")
        return result
    except (ValueError, UnicodeError):
        raise Rejected("Invalid crypto payload") from None


def parse_request(value: object) -> Request:
    """
    Enforce closed schema and canonical opaque identifiers before credential access.

    Args:
        value (object): Untrusted decoded request.

    Returns:
        Request: Exact typed service request.

    Raises:
        Rejected: A field or identifier is invalid.
    """
    request = contracts.structure(value, Request, "crypto-request")
    identifiers = (request.request_id, request.grant, request.key, request.task, request.authority, request.policy) + tuple(
        getattr(request.binding, name) for name in ("tenant", "identity", "record")
    )
    try:
        if any(str(UUID(value)) != value for value in identifiers):
            raise Rejected("Invalid crypto scope")
    except ValueError:
        raise Rejected("Invalid crypto scope") from None
    return request


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
