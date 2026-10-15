"""
Keep standalone clients within closed wire and transport contracts without granting authority.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from agent_broker_sdk import Binding, BrokerError, CryptoClient, Request
from agent_broker_sdk.contracts import data, decode, parse_request, parse_response

if TYPE_CHECKING:
    from pathlib import Path


def test_shared_request_rejects_extra_fields_and_noncanonical_ids() -> None:
    """
    Preserve exact scope identities and reject fields that could imply client-defined permissions.

    Returns:
        None: Closed request validation fails without reflecting the supplied values.
    """
    identifier = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    request = Request(
        identifier, identifier, "public", identifier, Binding(identifier, identifier, identifier, 1), identifier, identifier, identifier, ""
    )
    assert parse_request(data(request)) == request
    for raw in ({**data(request), "role": "administrator"}, {**data(request), "grant": identifier.upper()}):
        with pytest.raises(BrokerError) as caught:
            parse_request(raw)
        assert identifier not in str(caught.value)
        assert "administrator" not in str(caught.value)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        "https://localhost/path",
        "https://user@localhost",
        "https://localhost?",
        "https://localhost#",
        "https://localhost:0",
        "https://localhost:invalid",
        "https://local\nhost",
    ],
)
def test_invalid_origins_fail_before_loading_credentials(origin: str, tmp_path: Path) -> None:
    """
    Reject malformed or credential-bearing origins before accessing certificate files.

    Args:
        origin (str): Invalid endpoint configuration.
        tmp_path (Path): Directory containing no credentials.

    Returns:
        None: The diagnostic is bounded and contains no supplied URL.
    """
    with pytest.raises(BrokerError) as caught:
        CryptoClient(origin, tmp_path / "ca", tmp_path / "cert", tmp_path / "key")
    assert origin not in str(caught.value)


@pytest.mark.parametrize("value", [{"code": "ok", "payload": "", "admin": True}, {"code": "ok", "payload": 2}, {"code": "unknown"}])
def test_response_shape_is_closed(value: object) -> None:
    """
    Refuse unknown or coercible fields before returning service data.

    Args:
        value (object): Malformed response object.

    Returns:
        None: No response is accepted through coercion.
    """
    with pytest.raises(BrokerError):
        parse_response(value)


def test_payload_budget_and_canonical_base64() -> None:
    """
    Reject oversized decoded values and multiple encodings of the same bytes.

    Returns:
        None: Canonical bounded data alone survives.
    """
    assert decode("YQ==", 1) == b"a"
    for value in ("YR==", "YWE=", "YQ==\n", "not-base64"):
        with pytest.raises(BrokerError):
            decode(value, 1)
