"""
Describe the closed service-only key boundary without retaining secret values in representations.
"""

from __future__ import annotations

from typing import Literal

from attrs import field, frozen

from agent_broker.models import Credential  # noqa: TC001 - cattrs resolves the nested runtime contract.

CryptoAction = Literal["wrap", "unwrap", "sign", "public"]


@frozen
class Binding:
    """
    Bind a cryptographic result to independently authorized opaque scope and immutable content identity.

    Attributes:
        tenant (str): Opaque tenant UUID.
        identity (str): Opaque identity UUID.
        record (str): Immutable record or representation UUID.
        kind (int): Versioned record-kind code, without a private label.
        schema (int): Logical record schema version.
        codec (int): Deterministic payload codec version.
        hash (int): Semantic hash-domain version.
        envelope (int): Encryption envelope version.
    """

    tenant: str
    identity: str
    record: str
    kind: int
    schema: int = 1
    codec: int = 1
    hash: int = 1
    envelope: int = 1


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


@frozen
class Request:
    """
    Request one bounded cryptographic operation without a 1Password reference or private key.

    Attributes:
        request_id (str): Fresh request UUID, retained for exact retries.
        grant (str): Operator-issued grant UUID.
        action (CryptoAction): Requested service operation.
        key (str): Allowed key generation UUID.
        binding (Binding): Immutable record context checked against current operator policy.
        task (str): Current authorized task UUID, separate from permanent cryptographic context.
        authority (str): Current authority fence UUID.
        policy (str): Current access-policy revision UUID.
        payload (str): Base64 data key, wrapped key or ciphertext digest; excluded from repr.
    """

    request_id: str
    grant: str
    action: CryptoAction
    key: str
    binding: Binding
    task: str
    authority: str
    policy: str
    payload: str = field(repr=False)


@frozen
class Response:
    """
    Carry a service response whose key material must never enter logs or agent context.

    Attributes:
        code (Literal["ok", "denied", "unavailable"]): Bounded result category.
        payload (str): Base64 result; transient data keys are service-only and excluded from repr.
    """

    code: Literal["ok", "denied", "unavailable"]
    payload: str = field(default="", repr=False)
