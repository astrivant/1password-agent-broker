"""
Exercise key scopes, independently pinned signatures, reauthorization and bounded failure diagnostics.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.crypto.models import Response
from agent_broker.crypto.service import signature_input
from attrs import evolve
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

if TYPE_CHECKING:
    from agent_broker.models import Credential
    from agent_broker.testing.scenario import SyntheticProvider
    from pytest import CaptureFixture, MonkeyPatch

    from tests.crypto.conftest import Fixture


def test_wrap_unwrap_and_separate_signature(fixture: Fixture) -> None:
    """
    Recover only the data key and authenticate ciphertext with an independent signing generation.

    Args:
        fixture (Fixture): Synthetic service and trust pins.

    Returns:
        None: Round trip and signature verification succeed without exporting long-lived keys.
    """
    wrapped = fixture.service.handle("a" * 64, contracts.data(fixture.request))
    assert wrapped.code == "ok"
    request = evolve(fixture.request, request_id=str(uuid4()), action="unwrap", payload=wrapped.payload)
    assert fixture.service.handle("a" * 64, contracts.data(request)).payload == fixture.request.payload
    digest = hashlib.sha256(base64.b64decode(wrapped.payload)).digest()
    request = evolve(
        fixture.request, request_id=str(uuid4()), action="sign", key=fixture.signing, payload=base64.b64encode(digest).decode()
    )
    result = fixture.service.handle("a" * 64, contracts.data(request))
    assert result.code == "ok"
    key = serialization.load_der_public_key(fixture.public)
    assert isinstance(key, ed25519.Ed25519PublicKey)
    key.verify(base64.b64decode(result.payload), signature_input(request, digest))
    with pytest.raises(InvalidSignature):
        key.verify(
            base64.b64decode(result.payload), signature_input(evolve(request, binding=evolve(request.binding, record=str(uuid4()))), digest)
        )
    assert fixture.request.payload not in repr(fixture.request)
    assert result.payload not in repr(result)
    stored = fixture.ledger_path.read_bytes()
    assert b"d" * 32 not in stored
    assert fixture.request.payload.encode() not in stored
    assert all(secret.encode() not in stored for secret in fixture.provider.secrets.values())


@pytest.mark.parametrize("field", ["tenant", "identity", "record", "task", "authority", "policy"])
def test_scope_rejection_precedes_key_access(fixture: Fixture, field: str) -> None:
    """
    Reject every independent scope substitution before resolving a 1Password reference.

    Args:
        fixture (Fixture): Synthetic service and grant.
        field (str): One independent authorization field to substitute.

    Returns:
        None: Cross-tenant, identity, record, task, fence and policy requests are denied.
    """
    raw = contracts.data(fixture.request)
    if field in {"tenant", "identity", "record"}:
        raw["binding"] = {**contracts.data(fixture.request.binding), field: str(uuid4())}
    else:
        raw[field] = str(uuid4())
    response = fixture.service.handle("a" * 64, raw)
    assert response == Response("denied")
    assert not fixture.provider.calls


def test_wrong_certificate_and_expiry_fail_closed(fixture: Fixture) -> None:
    """
    Require the exact admitted workload certificate and a current grant.

    Args:
        fixture (Fixture): Synthetic service and fixed clock.

    Returns:
        None: Wrong peers and expired grants cannot retrieve keys.
    """
    assert fixture.service.handle("b" * 64, contracts.data(fixture.request)).code == "denied"
    fixture.service.clock = lambda: 2000
    assert fixture.service.handle("a" * 64, contracts.data(fixture.request)).code == "denied"
    assert not fixture.provider.calls


def test_revocation_during_resolution_blocks_release(fixture: Fixture, monkeypatch: MonkeyPatch) -> None:
    """
    Re-read authority after provider work instead of relying on a TTL or initial grant check.

    Args:
        fixture (Fixture): Synthetic service and grant.
        monkeypatch (MonkeyPatch): Deterministic provider-boundary fault injection.

    Returns:
        None: A grant revoked during resolution releases no result.
    """
    original = fixture.provider.resolve

    def revoke(self: SyntheticProvider, credential: Credential) -> str:
        """
        Revoke the grant exactly while the SDK boundary is executing.

        Args:
            self (SyntheticProvider): Synthetic provider receiving the request.
            credential (Credential): Broker-owned key reference.

        Returns:
            str: Synthetic key bytes, which the revoked operation must withhold.
        """
        grant = evolve(fixture.policy.grants[fixture.request.grant], revoked=True)
        policy = evolve(fixture.policy, grants={fixture.request.grant: grant})
        write_private(fixture.service.policy, contracts.data(policy))
        return original(credential)

    monkeypatch.setattr(type(fixture.provider), "resolve", revoke)
    assert fixture.service.handle("a" * 64, contracts.data(fixture.request)) == Response("denied")


def test_replay_reauthorizes_without_persisting_keys(fixture: Fixture) -> None:
    """
    Permit exact pure-operation retries while rejecting changed payloads under an existing request ID.

    Args:
        fixture (Fixture): Isolated durable ledger and provider.

    Returns:
        None: Completed retries remain scoped; conflicting and revoked retries fail.
    """
    first = fixture.service.handle("a" * 64, contracts.data(fixture.request))
    retry = fixture.service.handle("a" * 64, contracts.data(fixture.request))
    assert first.code == retry.code == "ok"
    changed = evolve(fixture.request, payload=base64.b64encode(b"e" * 32).decode())
    assert fixture.service.handle("a" * 64, contracts.data(changed)).code == "denied"
    grant = evolve(fixture.policy.grants[fixture.request.grant], revoked=True)
    write_private(fixture.service.policy, contracts.data(evolve(fixture.policy, grants={fixture.request.grant: grant})))
    assert fixture.service.handle("a" * 64, contracts.data(fixture.request)).code == "denied"


@pytest.mark.parametrize("payload", ["", "not-base64", "YQ==", "x" * 2000])
def test_invalid_payload_never_reflects_secret(fixture: Fixture, capsys: CaptureFixture[str], payload: str) -> None:
    """
    Reject malformed key inputs without printing provider or request material.

    Args:
        fixture (Fixture): Synthetic broker with valid custody.
        capsys (CaptureFixture[str]): Captured diagnostic streams.
        payload (str): Invalid encoded operation input.

    Returns:
        None: Only a bounded denied or unavailable result is returned.
    """
    response = fixture.service.handle("a" * 64, contracts.data(evolve(fixture.request, payload=payload)))
    assert response.code in ("denied", "unavailable")
    assert response.payload == ""
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_wrong_key_pin_and_tampering_fail(fixture: Fixture) -> None:
    """
    Check independent custody pins and OAEP authentication instead of trusting stored key identifiers.

    Args:
        fixture (Fixture): Synthetic keys and provider.

    Returns:
        None: Modified wrapping context, ciphertext and public-key pins reject safely.
    """
    result = fixture.service.handle("a" * 64, contracts.data(fixture.request))
    raw = bytearray(base64.b64decode(result.payload))
    raw[0] ^= 1
    request = evolve(fixture.request, request_id=str(uuid4()), action="unwrap", payload=base64.b64encode(raw).decode())
    assert fixture.service.handle("a" * 64, contracts.data(request)) == Response("unavailable")
    key = evolve(fixture.policy.keys[fixture.request.key], public_sha256="0" * 64)
    policy = evolve(fixture.policy, keys={**fixture.policy.keys, fixture.request.key: key})
    write_private(fixture.service.policy, contracts.data(policy))
    assert fixture.service.handle("a" * 64, contracts.data(evolve(fixture.request, request_id=str(uuid4())))) == Response("denied")


def test_authority_change_preserves_authorized_history(fixture: Fixture) -> None:
    """
    Rotate access authority without changing the immutable record's cryptographic identity.

    Args:
        fixture (Fixture): Synthetic key custody with an initial authorized workload.

    Returns:
        None: Old authority is denied and the newly authorized workload recovers the same historical data key.
    """
    wrapped = fixture.service.handle("a" * 64, contracts.data(fixture.request))
    assert wrapped.code == "ok"
    grant = evolve(fixture.policy.grants[fixture.request.grant], task=str(uuid4()), authority=str(uuid4()), policy=str(uuid4()))
    policy = evolve(fixture.policy, grants={fixture.request.grant: grant})
    write_private(fixture.service.policy, contracts.data(policy))
    old = evolve(fixture.request, request_id=str(uuid4()), action="unwrap", payload=wrapped.payload)
    assert fixture.service.handle("a" * 64, contracts.data(old)) == Response("denied")
    current = evolve(old, task=grant.task, authority=grant.authority, policy=grant.policy)
    assert fixture.service.handle("a" * 64, contracts.data(current)).payload == fixture.request.payload
