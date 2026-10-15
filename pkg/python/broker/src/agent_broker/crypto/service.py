"""
Keep long-lived wrapping and signing keys inside the independently operated broker.
"""

from __future__ import annotations

import base64
import hashlib
import time
from importlib.resources import as_file, files
from typing import TYPE_CHECKING, Protocol

from casbin import Enforcer
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from agent_broker import contracts
from agent_broker.crypto.contracts import aad, decode, load_policy, parse_request
from agent_broker.crypto.models import Key, Policy, Request, Response
from agent_broker.exceptions import AuditFailure, ProviderFailure, Rejected
from agent_broker.models import Result

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agent_broker.ledger import Ledger
    from agent_broker.providers import Provider

__all__ = ["CryptoService", "signature_input"]


class Evaluator(Protocol):
    """
    Type the maintained evaluator's public variadic boundary without spreading untyped calls.
    """

    def enforce(self, *rvals: object) -> bool:
        """
        Evaluate request attributes through the packaged authorization model.

        Args:
            *rvals (object): Attributes matching the model's ordered request definition.

        Returns:
            bool: Explicit authorization decision from the maintained evaluator.
        """
        ...


def signature_input(request: Request, digest: bytes) -> bytes:
    """
    Separate envelope signatures from arbitrary signatures and bind them to the expected context.

    Args:
        request (Request): Validated service request.
        digest (bytes): SHA-256 of final ciphertext envelope bytes, never a plaintext record digest.

    Returns:
        bytes: Domain-separated Ed25519 message shared with service verifiers.
    """
    return b"agent-broker-sign-v1\x00" + hashlib.sha256(aad(request.binding)).digest() + digest


class CryptoService:
    """
    Reauthorize bounded pure cryptographic operations before key access and before result release.
    """

    def __init__(self, policy: Path, provider: Provider, ledger: Ledger, clock: Callable[[], float] = time.time) -> None:
        """
        Inject operator-owned custody, durable redacted auditing, and an explicit clock boundary.

        Args:
            policy (Path): Closed operator policy; no private key bytes.
            provider (Provider): Existing official-SDK-backed 1Password resolver.
            ledger (Ledger): Shared durable ledger; never receives payloads or returned data keys.
            clock (Callable[[], float]): UTC epoch clock, replaceable for deterministic expiry tests.
        """
        self.policy = policy
        self.provider = provider
        self.ledger = ledger
        self.clock = clock

    def authorize(self, fingerprint: str, request: Request) -> tuple[Policy, str]:
        """
        Re-read a service grant and enforce every independent scope binding.

        Args:
            fingerprint (str): Verified TLS client certificate SHA-256.
            request (Request): Typed cryptographic request.

        Returns:
            tuple[Policy, str]: Current policy and its exact snapshot digest.

        Raises:
            Rejected: Any scope, key, action, record, deadline or revocation check fails.
        """
        policy, revision = load_policy(self.policy)
        grant = policy.grants.get(request.grant)
        if grant is None:
            raise Rejected("Crypto scope denied")

        # Casbin evaluates the fixed ABAC model against this newly loaded operator grant.
        # No policy cache can outlive a revocation, and SDK fields never define policy code.
        with as_file(files("agent_broker").joinpath("resources/crypto-authorization.conf")) as model:
            enforcer: Evaluator = Enforcer(str(model), enable_log=False)
        if enforcer.enforce(fingerprint, grant, request, self.clock()) is not True:
            raise Rejected("Crypto scope denied")
        return policy, revision

    def handle(self, fingerprint: str, raw: object) -> Response:
        """
        Execute an explicit service operation while retaining only bounded audit metadata.

        Args:
            fingerprint (str): Verified TLS client fingerprint, never an HTTP identity header.
            raw (object): Untrusted service request; absent from logs and persistent results.

        Returns:
            Response: Transient authorized data or a fixed error category.
        """
        claimed = False
        request: Request | None = None
        try:
            request = parse_request(raw)
            policy, revision = self.authorize(fingerprint, request)
            binding = contracts.digest({"request": contracts.data(request), "policy": revision, "peer": fingerprint})
            attributes: dict[str, object] = {"request.id": request.request_id, "operation": "crypto", "action": "execute"}
            self.ledger.event("requested", attributes)
            previous = self.ledger.claim(request.request_id, request.grant, binding)
            if previous is not None and previous.state != "completed":
                return Response("denied" if previous.state == "denied" else "unavailable")
            claimed = True
            key = policy.keys[request.key]
            with self.ledger.telemetry.phase("provider"):
                secret = self.provider.resolve(key.credential)

            # A policy edit or revocation during the SDK call cannot authorize a key operation.
            if self.authorize(fingerprint, request)[1] != revision:
                raise Rejected("Crypto scope changed")
            result = self.perform(request, key, secret)
            del secret
            if self.authorize(fingerprint, request)[1] != revision:
                raise Rejected("Crypto scope changed")

            # Pure operations may be recomputed after an exact completed retry; no plaintext result is cached.
            finished = self.ledger.finish(request.request_id, Result("completed", "crypto_completed"))
            if finished.state != "completed":
                return Response("unavailable")
            self.ledger.event("completed", {**attributes, "result.code": "crypto_completed"})
            if self.authorize(fingerprint, request)[1] != revision:
                raise Rejected("Crypto scope changed")
            return Response("ok", base64.b64encode(result).decode())
        except Rejected:
            response = Response("denied")
        except (ProviderFailure, AuditFailure, OSError, ValueError, UnsupportedAlgorithm):
            response = Response("unavailable")
        if claimed and request is not None:
            try:
                self.ledger.finish(request.request_id, Result("failed", "provider_failed"))
            except AuditFailure:
                pass
        return response

    @staticmethod
    def perform(request: Request, key: Key, secret: str) -> bytes:
        """
        Use maintained cryptographic primitives with separately pinned key purposes.

        Args:
            request (Request): Authorized context and bounded encoded operation input.
            key (Key): Operator-selected generation and trusted public fingerprint.
            secret (str): Base64 PKCS8 DER from the broker-local SDK worker.

        Returns:
            bytes: Wrapped key, transient data key, signature, or public verification material.

        Raises:
            Rejected: Key identity, algorithm, input size or operation purpose is invalid.
            ValueError: Key decoding or cryptographic authentication fails; handled without diagnostic reflection.
        """
        private = serialization.load_der_private_key(decode(secret, 12288), password=None)
        public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if hashlib.sha256(public).hexdigest() != key.public_sha256:
            raise Rejected("Crypto key differs from its trust pin")
        wrapping = isinstance(private, rsa.RSAPrivateKey) and 3072 <= private.key_size <= 8192 and key.kind == "wrapping"
        signing = isinstance(private, ed25519.Ed25519PrivateKey) and key.kind == "signing"
        if not (wrapping or signing):
            raise Rejected("Crypto key purpose differs")
        payload = decode(request.payload, 1024)
        if request.action == "public" and not payload:
            return public
        if isinstance(private, rsa.RSAPrivateKey) and wrapping:
            oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad(request.binding))
            if request.action == "wrap" and len(payload) == 32:
                return private.public_key().encrypt(payload, oaep)
            if request.action == "unwrap" and len(payload) == private.key_size // 8:
                result = private.decrypt(payload, oaep)
                if len(result) == 32:
                    return result
        if request.action == "sign" and signing and isinstance(private, ed25519.Ed25519PrivateKey) and len(payload) == 32:
            return private.sign(signature_input(request, payload))
        raise Rejected("Crypto input or action differs")
