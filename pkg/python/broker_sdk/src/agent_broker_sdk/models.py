"""
Own the shared version-one service wire models without importing the server or provider SDK.
"""

from __future__ import annotations

from typing import Literal

from attrs import field, frozen

__all__ = ["Binding", "CryptoAction", "Request", "Response"]
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
