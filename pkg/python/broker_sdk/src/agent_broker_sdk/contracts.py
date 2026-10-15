"""
Validate versioned service wire data without importing the broker runtime.
"""

from __future__ import annotations

import base64
import json
from importlib.resources import files
from typing import TypeVar
from uuid import UUID

from cattrs import Converter
from cattrs.errors import BaseValidationError
from jsonschema import ValidationError, validate

from agent_broker_sdk.exceptions import BrokerError
from agent_broker_sdk.models import Binding, Request, Response

__all__ = ["aad", "data", "decode", "encode", "parse_request", "parse_response", "schema"]
CONVERTER = Converter(forbid_extra_keys=True)
T = TypeVar("T")


def encode(value: object) -> bytes:
    """
    Encode deterministic JSON for wire requests and immutable context bindings.

    Args:
        value (object): JSON-compatible input.

    Returns:
        bytes: Canonical UTF-8 serialization.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def data(value: Binding | Request | Response) -> dict[str, object]:
    """
    Convert one shared model into a JSON-compatible object.

    Args:
        value (Binding | Request | Response): Supported wire model.

    Returns:
        dict[str, object]: Unstructured representation; payloads remain sensitive.
    """
    result: dict[str, object] = CONVERTER.unstructure(value)
    return result


def schema(name: str) -> dict[str, object]:
    """
    Load a shared, closed wire schema from the installed SDK.

    Args:
        name (str): Request or response schema stem.

    Returns:
        dict[str, object]: Maintained schema, without network access.

    Raises:
        BrokerError: The schema name is unsupported.
    """
    if name not in ("crypto-request", "crypto-response"):
        raise BrokerError("Unsupported broker contract")
    result: dict[str, object] = json.loads(files("agent_broker_sdk").joinpath(f"resources/{name}.schema.json").read_text())
    return result


# Retain syntax supported by the project's pinned docstring checker.
def _structure(value: object, model: type[T], name: str) -> T:  # noqa: UP047
    """
    Validate before conversion while suppressing reflected untrusted values.

    Args:
        value (object): Untrusted decoded JSON.
        model (type[T]): Expected shared model.
        name (str): Packaged schema stem.

    Returns:
        T: Validated typed model.

    Raises:
        BrokerError: Input violates the closed wire contract.
    """
    try:
        validate(value, schema(name))
        return CONVERTER.structure(value, model)
    except (ValidationError, BaseValidationError, TypeError, ValueError):
        raise BrokerError("Invalid broker contract") from None


def aad(binding: Binding) -> bytes:
    """
    Bind cryptography to immutable context independently of current access policy.

    Args:
        binding (Binding): Independently validated expected record context.

    Returns:
        bytes: Domain-separated canonical JSON, unchanged from protocol version one.
    """
    return b"agent-broker-record-v1\x00" + encode(data(binding))


def decode(value: str, maximum: int) -> bytes:
    """
    Reject oversized or noncanonical base64 without reflecting payloads.

    Args:
        value (str): Untrusted encoded bytes.
        maximum (int): Maximum decoded size.

    Returns:
        bytes: Bounded decoded payload.

    Raises:
        BrokerError: Encoding or size is invalid.
    """
    try:
        if len(value) > ((maximum + 2) // 3) * 4:
            raise BrokerError("Invalid broker payload")
        result = base64.b64decode(value, validate=True)
        if len(result) > maximum or base64.b64encode(result).decode() != value:
            raise BrokerError("Invalid broker payload")
        return result
    except (ValueError, UnicodeError):
        raise BrokerError("Invalid broker payload") from None


def parse_request(value: object) -> Request:
    """
    Enforce closed fields and canonical identifiers without evaluating authorization.

    Args:
        value (object): Untrusted decoded request.

    Returns:
        Request: Valid wire request; permission remains a server decision.

    Raises:
        BrokerError: A field or opaque identifier is invalid.
    """
    request = _structure(value, Request, "crypto-request")
    identifiers = (
        request.request_id,
        request.grant,
        request.key,
        request.task,
        request.authority,
        request.policy,
        request.binding.tenant,
        request.binding.identity,
        request.binding.record,
    )
    try:
        if any(str(UUID(value)) != value for value in identifiers):
            raise BrokerError("Invalid broker scope")
    except ValueError:
        raise BrokerError("Invalid broker scope") from None
    return request


def parse_response(value: object) -> Response:
    """
    Validate a bounded response before exposing any returned key bytes.

    Args:
        value (object): Untrusted decoded response.

    Returns:
        Response: Closed result contract.

    Raises:
        BrokerError: A response field is invalid.
    """
    return _structure(value, Response, "crypto-response")
