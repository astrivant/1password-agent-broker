"""
Validate closed JSON contracts before conversion into typed broker objects.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from cattrs import Converter
from cattrs.errors import BaseValidationError
from jsonschema import ValidationError, validate

from agent_broker.exceptions import Rejected
from agent_broker.models import Approval, Policy, Request

if TYPE_CHECKING:
    from pathlib import Path

T = TypeVar("T")
CONVERTER = Converter(forbid_extra_keys=True)
SLUG = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}")


def encode(value: object) -> bytes:
    """
    Encode deterministic JSON for revision and request bindings.

    Args:
        value (object): JSON-compatible value.

    Returns:
        bytes: Canonical UTF-8 serialization.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    """
    Bind approval to exact canonical policy or request content.

    Args:
        value (object): JSON-compatible data.

    Returns:
        str: SHA-256 hex digest.
    """
    return hashlib.sha256(encode(value)).hexdigest()


def data(value: object) -> dict[str, object]:
    """
    Convert an attrs contract into a JSON object.

    Args:
        value (object): Supported attrs instance.

    Returns:
        dict[str, object]: Plain object representation.
    """
    result: dict[str, object] = CONVERTER.unstructure(value)
    return result


def schema(name: str) -> dict[str, object]:
    """
    Load a packaged, versioned JSON Schema without contacting the network.

    Args:
        name (str): Maintained schema filename stem.

    Returns:
        dict[str, object]: Schema for validation and MCP discovery.
    """
    result: dict[str, object] = json.loads(files("agent_broker").joinpath(f"resources/{name}.schema.json").read_text())
    return result


# pydocstyle 6.3 cannot parse PEP 695 function parameters; retain equivalent supported typing.
def structure(value: object, model: type[T], name: str) -> T:  # noqa: UP047
    """
    Validate before typed conversion and redact diagnostic values.

    Args:
        value (object): Untrusted JSON input.
        model (type[T]): Expected attrs contract.
        name (str): Schema filename stem.

    Returns:
        T: Validated model instance.

    Raises:
        Rejected: Any key, value, or structural constraint fails.
    """
    try:
        validate(value, schema(name))
        return CONVERTER.structure(value, model)
    except (ValidationError, BaseValidationError, TypeError, ValueError):
        raise Rejected("Invalid contract") from None


def request(value: object) -> Request:
    """
    Reject additional fields and require canonical request identifiers.

    Args:
        value (object): Client JSON object.

    Returns:
        Request: Closed capability request.

    Raises:
        Rejected: The request is invalid or has a noncanonical UUID.
    """
    item = structure(value, Request, "request")
    try:
        canonical = str(UUID(item.request_id))
    except ValueError:
        raise Rejected("Invalid request ID") from None
    if canonical != item.request_id:
        raise Rejected("Invalid request ID")
    return item


def read(path: Path) -> object:
    """
    Read bounded operator configuration without leaking its contents on failure.

    Args:
        path (Path): Trusted configuration file.

    Returns:
        object: Parsed JSON data.

    Raises:
        Rejected: The file is absent, oversized, or invalid.
    """
    try:
        if path.stat().st_size > 1024 * 1024:
            raise Rejected("Configuration too large")
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise Rejected("Invalid configuration") from None


def policy(path: Path) -> tuple[Policy, str]:
    """
    Validate references, destination restrictions, and unique certificate ownership.

    Args:
        path (Path): Operator-owned policy JSON.

    Returns:
        tuple[Policy, str]: Typed policy and canonical content hash.

    Raises:
        Rejected: References, certificates, or destinations violate the contract.
    """
    raw = read(path)
    item = structure(raw, Policy, "policy")
    certificates = [principal.certificate_sha256 for principal in item.principals.values()]
    if len(certificates) != len(set(certificates)):
        raise Rejected("Certificates must have unique owners")

    for principal in item.principals.values():
        if not set(principal.operations).issubset(item.operations):
            raise Rejected("Unknown capability")

    for operation in item.operations.values():
        try:
            url = urlsplit(operation.url)
            port = url.port
        except ValueError:
            raise Rejected("Invalid capability destination") from None
        if (
            operation.credential not in item.credentials
            or url.scheme != "https"
            or not url.hostname
            or port == 0
            or not operation.url.isascii()
            or any(ord(character) < 33 or ord(character) == 127 for character in operation.url)
        ):
            raise Rejected("Invalid capability destination")
        if url.username is not None or url.password is not None or "?" in operation.url or "#" in operation.url:
            raise Rejected("Destination contains forbidden URL components")
    return item, digest(raw)


def approvals(path: Path) -> dict[str, Approval]:
    """
    Read exact-request grants separately from the policy they authorize.

    Args:
        path (Path): Operator-owned approvals JSON.

    Returns:
        dict[str, Approval]: Validated grants keyed by opaque approval ID.

    Raises:
        Rejected: Any approval violates the closed schema.
    """
    raw = read(path)
    try:
        validate(raw, schema("approvals"))
        return CONVERTER.structure(raw, dict[str, Approval])
    except (ValidationError, BaseValidationError, TypeError, ValueError):
        raise Rejected("Invalid approvals") from None
