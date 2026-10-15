"""
Build independent synthetic key custody and disposable operator policies.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.crypto.models import Binding, Grant, Key, Policy, Request
from agent_broker.crypto.service import CryptoService
from agent_broker.ledger import Ledger
from agent_broker.models import Credential
from agent_broker.testing.scenario import SyntheticProvider
from attrs import frozen
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@frozen
class Fixture:
    """
    Retain a disposable service and its independently generated key material.

    Attributes:
        service (CryptoService): Real authorization and cryptography service.
        provider (SyntheticProvider): In-memory synthetic 1Password boundary.
        policy (Policy): Operator-owned synthetic grants.
        request (Request): Initial wrapping request, with a fresh 256-bit test data key.
        signing (str): Separate signing-generation UUID.
        public (bytes): Independently retained signing public key.
        ledger_path (Path): Disposable SQLite audit location.
    """

    service: CryptoService
    provider: SyntheticProvider
    policy: Policy
    request: Request
    signing: str
    public: bytes
    ledger_path: Path


@pytest.fixture
def fixture(tmp_path: Path) -> Iterator[Fixture]:
    """
    Isolate each test's policy, ledger, data key and asymmetric key generations.

    Args:
        tmp_path (Path): Pytest-owned disposable directory.

    Yields:
        Fixture: Complete service fixture, closed after the test.
    """
    wrapping, signing = str(uuid4()), str(uuid4())
    private_keys: dict[str, rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey] = {
        wrapping: rsa.generate_private_key(public_exponent=65537, key_size=3072),
        signing: ed25519.Ed25519PrivateKey.generate(),
    }
    secrets = {
        "op://synthetic/" + identifier + "/key": base64.b64encode(
            key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        ).decode()
        for identifier, key in private_keys.items()
    }
    keys = {
        identifier: Key(
            Credential("op://synthetic/" + identifier + "/key"),
            "wrapping" if identifier == wrapping else "signing",
            hashlib.sha256(
                key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            ).hexdigest(),
        )
        for identifier, key in private_keys.items()
    }
    binding = Binding(str(uuid4()), str(uuid4()), str(uuid4()), kind=1)
    grant_id = str(uuid4())
    grant = Grant(
        "a" * 64,
        binding.tenant,
        binding.identity,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        ("wrap", "unwrap", "sign", "public"),
        (wrapping, signing),
        2000,
        (binding.record,),
    )
    policy = Policy(keys, {grant_id: grant})
    policy_path = tmp_path / "crypto.json"
    write_private(policy_path, contracts.data(policy))
    provider = SyntheticProvider(secrets, [])
    ledger_path = tmp_path / "audit.sqlite3"
    ledger = Ledger(ledger_path)
    service = CryptoService(policy_path, provider, ledger, lambda: 1000)
    request = Request(
        str(uuid4()), grant_id, "wrap", wrapping, binding, grant.task, grant.authority, grant.policy, base64.b64encode(b"d" * 32).decode()
    )
    public = private_keys[signing].public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    try:
        yield Fixture(service, provider, policy, request, signing, public, ledger_path)
    finally:
        ledger.close()
