"""
Authorize exact requests, reserve them durably, and execute without exposing credentials.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING

from attrs import evolve
from opentelemetry import trace

from agent_broker import contracts
from agent_broker.exceptions import AuditFailure, DestinationFailure, ProviderFailure, Rejected
from agent_broker.models import Policy, Principal, Request, Result

if TYPE_CHECKING:
    from pathlib import Path

    from agent_broker.ledger import Ledger
    from agent_broker.providers import Executor, Provider


class Broker:
    """
    Keep authentication, policy, approval, audit, and execution under one ownership boundary.
    """

    def __init__(self, policy: Path, approvals: Path, ledger: Ledger, provider: Provider, executor: Executor) -> None:
        """
        Inject operator-owned dependencies without retaining resolved credentials.

        Args:
            policy (Path): Closed capability policy.
            approvals (Path): Exact-request grants, editable only by the operator.
            ledger (Ledger): Durable request and audit storage.
            provider (Provider): Broker-only credential resolver.
            executor (Executor): Bounded operation implementation.
        """
        self.policy = policy
        self.approvals = approvals
        self.ledger = ledger
        self.provider = provider
        self.executor = executor

    def authorize(self, fingerprint: str, request: Request, *, require_approval: bool = True) -> tuple[str, Principal, Policy, str]:
        """
        Re-read current authority, binding grants to the complete policy revision.

        Args:
            fingerprint (str): SHA-256 of a TLS-verified peer certificate.
            request (Request): Validated capability request.
            require_approval (bool): False only for an authenticated cancellation.

        Returns:
            tuple[str, Principal, Policy, str]: Principal name, identity, policy, and revision.

        Raises:
            Rejected: Identity, capability, grant, expiry, or revision does not match.
        """
        policy, revision = contracts.policy(self.policy)
        matches = [(name, item) for name, item in policy.principals.items() if item.certificate_sha256 == fingerprint]
        if len(matches) != 1:
            raise Rejected("Denied")
        name, principal = matches[0]
        if request.operation not in principal.operations:
            raise Rejected("Denied")

        if require_approval:
            approval = contracts.approvals(self.approvals).get(request.approval_id)
            if approval is None or approval.revoked or approval.expires_at <= time.time():
                raise Rejected("Denied")
            if (approval.request_id, approval.principal, approval.operation, approval.policy_sha256) != (
                request.request_id,
                name,
                request.operation,
                revision,
            ):
                raise Rejected("Denied")
        return name, principal, policy, revision

    def handle(self, fingerprint: str, raw: object, *, cancel: bool = False) -> Result:
        """
        Execute at most once per durable request identity and return only safe status.

        Args:
            fingerprint (str): Verified TLS peer fingerprint supplied by the server.
            raw (object): Untrusted parsed JSON.
            cancel (bool): Request cancellation instead of execution.

        Returns:
            Result: Bounded outcome; uncertainty never triggers another submission.
        """
        attempted = False
        attributes: dict[str, object] = {}
        try:
            request = contracts.request(raw)
            name, principal, policy, revision = self.authorize(fingerprint, request, require_approval=not cancel)
            span = trace.get_current_span().get_span_context()
            attributes = {
                "request.id": request.request_id,
                "principal": name,
                "identity.id": principal.identity_id,
                "identity.revision": principal.identity_revision,
                "run.id": principal.run_id,
                "policy.sha256": revision,
                "operation": request.operation,
                "approval.id": request.approval_id,
                "credential.alias": policy.operations[request.operation].credential,
                "destination.class": "https-health",
                "trace.id": f"{span.trace_id:032x}" if span.is_valid else secrets.token_hex(16),
                "span.id": f"{span.span_id:016x}" if span.is_valid else secrets.token_hex(8),
            }
            binding = contracts.digest({"request": contracts.data(request), "principal": name, "policy": revision})
            warning = self.ledger.event("requested", attributes)

            if cancel:
                result = self.ledger.cancel(request.request_id, name, binding)
                warning |= self.ledger.event("cancelled", attributes)
                return evolve(result, audit_warning=warning or result.audit_warning)
            previous = self.ledger.claim(request.request_id, name, binding)
            if previous is not None:
                return evolve(previous, audit_warning=warning or previous.audit_warning)

            warning |= self.ledger.event("allowed", attributes)
            operation = policy.operations[request.operation]
            result = Result("cancelled", "cancelled")
            if not self.ledger.cancelled(request.request_id):
                try:
                    secret = self.provider.resolve(policy.credentials[operation.credential])

                    # Revocation, rotation of policy, and cancellation are checked again after provider latency.
                    _, _, _, current_revision = self.authorize(fingerprint, request)
                    if current_revision != revision:
                        raise Rejected("Denied")
                    if not self.ledger.cancelled(request.request_id):
                        warning |= self.ledger.event("attempted", attributes)
                        attempted = True
                        status = self.executor.execute(operation, secret)
                        result = Result("completed", "healthy" if 200 <= status < 300 else "unhealthy", status)
                        if self.ledger.cancelled(request.request_id):
                            result = Result("uncertain", "unknown")
                    del secret
                except ProviderFailure:
                    result = Result("failed", "provider_failed")
                except DestinationFailure:
                    result = Result("uncertain", "unknown")
                except Rejected:
                    result = Result("denied", "denied")

            warning |= self.ledger.event(result.state, attributes)
            result = evolve(result, audit_warning=warning)
            self.ledger.finish(request.request_id, result)
            return result
        except Rejected:
            try:
                warning = self.ledger.event("denied", attributes)
                return Result("denied", "denied", audit_warning=warning)
            except AuditFailure:
                return Result("failed", "audit_failed")
        except AuditFailure:
            return Result("uncertain" if attempted else "failed", "audit_failed")
