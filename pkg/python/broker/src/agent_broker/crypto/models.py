"""
Describe the closed service-only key boundary without retaining secret values in representations.
"""

from __future__ import annotations

from typing import Literal

from agent_broker_sdk.models import Binding, CryptoAction, Request, Response
from attrs import frozen

from agent_broker.models import Credential  # noqa: TC001 - cattrs resolves the nested runtime contract.

__all__ = ["Binding", "CryptoAction", "Grant", "Key", "Policy", "Request", "Response"]


@frozen
class Key:
    """
    Locate one generation without placing private key material in workload configuration.

    Attributes:
        credential (Credential): Broker-owned reference to a base64 PKCS8 DER private key.
        kind (Literal["wrapping", "signing"]): Dedicated RSA-OAEP or Ed25519 purpose.
        public_sha256 (str): Independently pinned SHA-256 of DER SubjectPublicKeyInfo.
    """

    credential: Credential
    kind: Literal["wrapping", "signing"]
    public_sha256: str


@frozen
class Grant:
    """
    Authorize one service certificate for an explicit current identity and key scope.

    Attributes:
        certificate_sha256 (str): Verified service certificate fingerprint; no header-derived identity.
        tenant (str): Permitted opaque tenant UUID.
        identity (str): Permitted opaque identity UUID.
        task (str): Permitted task UUID.
        authority (str): Current external fence UUID, changed on migration or recovery.
        policy (str): Authorization revision UUID, changed on scope changes.
        actions (tuple[CryptoAction, ...]): Explicit allowed key operations.
        keys (tuple[str, ...]): Allowed key-generation UUIDs.
        expires_at (int): UTC expiry in epoch seconds.
        records (tuple[str, ...]): Explicit immutable record UUID allowlist.
        all_records (bool): Explicit identity-wide permission, disabled by default.
        revoked (bool): Immediate denial on the next authorization check.
    """

    certificate_sha256: str
    tenant: str
    identity: str
    task: str
    authority: str
    policy: str
    actions: tuple[CryptoAction, ...]
    keys: tuple[str, ...]
    expires_at: int
    records: tuple[str, ...] = ()
    all_records: bool = False
    revoked: bool = False


@frozen
class Policy:
    """
    Keep cryptographic custody and service admission separate from agent capabilities.

    Attributes:
        keys (dict[str, Key]): Opaque generation IDs with distinct encryption/signing roles.
        grants (dict[str, Grant]): Operator-owned service grants keyed by opaque UUIDs.
        version (Literal[1]): Closed wire contract version.
    """

    keys: dict[str, Key]
    grants: dict[str, Grant]
    version: Literal[1] = 1
