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

    def identify(self, fingerprint: str) -> tuple[str, Principal, Policy, str]:
        """
        Resolve attribution from current operator policy and a verified certificate.

        Args:
            fingerprint (str): SHA-256 of a TLS-verified peer certificate.

        Returns:
            tuple[str, Principal, Policy, str]: Workload, identity, policy, and policy revision.

        Raises:
            Rejected: The certificate has no unique current owner.
        """
        policy, revision = contracts.policy(self.policy)

        # Resolve ownership from current operator policy, never from caller-supplied attribution.
        matches = [(name, item) for name, item in policy.principals.items() if item.certificate_sha256 == fingerprint]
        if len(matches) != 1:
            raise Rejected("Denied")
        name, principal = matches[0]
        return name, principal, policy, revision

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
        name, principal, policy, revision = self.identify(fingerprint)
        if request.operation not in principal.operations:
            raise Rejected("Denied")

        # A grant authorizes this exact request at this policy revision, not future uses of the capability.
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

    def outcome(self, result: Result, attributes: dict[str, object], warning: bool = False) -> Result:
        """
        Record the actual response, including denial, replay, and recovery outcomes.

        Args:
            result (Result): Bounded response to record.
            attributes (dict[str, object]): Trusted attribution for this invocation.
            warning (bool): Whether an earlier optional export failed.

        Returns:
            Result: Response with any export warning surfaced.
        """
        fields = {**attributes, "result.code": result.code, "result.replayed": result.replayed}
        if result.status_code is not None:
            fields["result.status_code"] = result.status_code
        warning |= self.ledger.event(result.state, fields)
        return evolve(result, audit_warning=warning or result.audit_warning)

    def handle(self, fingerprint: str, raw: object, *, cancel: bool = False, inspect: bool = False) -> Result:
        """
        Execute at most once per durable request identity and return only safe status.

        Args:
            fingerprint (str): Verified TLS peer fingerprint supplied by the server.
            raw (object): Untrusted parsed JSON.
            cancel (bool): Request cancellation instead of execution.
            inspect (bool): Read existing state without authorizing execution.

        Returns:
            Result: Bounded outcome; uncertainty never triggers another submission.
        """
        attempted = False
        span = trace.get_current_span().get_span_context()
        attributes: dict[str, object] = {
            "trace.id": f"{span.trace_id:032x}" if span.is_valid else secrets.token_hex(16),
            "span.id": f"{span.span_id:016x}" if span.is_valid else secrets.token_hex(8),
            "action": "status" if inspect else "cancel" if cancel else "execute",
        }
        warning = False
        try:
            name, principal, policy, revision = self.identify(fingerprint)
            attributes.update(
                {
                    "principal": name,
                    "identity.id": principal.identity_id,
                    "identity.revision": principal.identity_revision,
                    "run.id": principal.run_id,
                    "policy.sha256": revision,
                }
            )
            if principal.task_id is not None:
                attributes["task.id"] = principal.task_id

            # Attribute schema and authorization denials without recording arbitrary input values.
            request = contracts.request(raw)
            attributes["request.id"] = request.request_id
            if request.operation in policy.operations:
                attributes["operation"] = request.operation

            # Recovery survives capability removal but remains bound to the original request and identity snapshot.
            recovery_binding = contracts.digest(
                {
                    "request": contracts.data(request),
                    "principal": name,
                    "identity": {key: value for key, value in contracts.data(principal).items() if key != "operations"},
                }
            )

            # Execution additionally binds the entire policy so a policy edit cannot reuse old authority.
            binding = contracts.digest({"request": contracts.data(request), "principal": name, "policy": revision})
            warning = self.ledger.event("requested", attributes)

            # Recovery authenticates the original request and identity without reviving a grant.
            if inspect:
                return self.outcome(self.ledger.inspect(request.request_id, name, recovery_binding), attributes, warning)
            if cancel:
                prior = self.ledger.inspect(request.request_id, name, recovery_binding)
                if prior.state == "denied":
                    self.authorize(fingerprint, request, require_approval=False)
                result = self.ledger.cancel(request.request_id, name, binding, recovery_binding)
                return self.outcome(result, attributes, warning)
            _, _, _, current_revision = self.authorize(fingerprint, request)
            if current_revision != revision:
                raise Rejected("Denied")
            attributes.update(
                {
                    "approval.id": request.approval_id,
                    "credential.alias": policy.operations[request.operation].credential,
                    "destination.class": "https-health",
                }
            )

            # Persist ownership before resolving credentials; concurrent owners can only recover existing state.
            previous = self.ledger.claim(request.request_id, name, binding, recovery_binding)
            if previous is not None:
                return self.outcome(previous, attributes, warning)

            warning |= self.ledger.event("allowed", attributes)
            operation = policy.operations[request.operation]
            result = Result("cancelled", "cancelled")
            if not self.ledger.cancelled(request.request_id):
                try:
                    with self.ledger.telemetry.phase("provider"):
                        secret = self.provider.resolve(policy.credentials[operation.credential])

                    # Revocation, rotation of policy, and cancellation are checked again after provider latency.
                    _, _, _, current_revision = self.authorize(fingerprint, request)
                    if current_revision != revision:
                        raise Rejected("Denied")
                    if not self.ledger.cancelled(request.request_id):
                        warning |= self.ledger.event("attempted", attributes)

                        # Commit submission admission before I/O so cancellation cannot falsely promise to undo it.
                        if self.ledger.begin(request.request_id):
                            attempted = True
                            with self.ledger.telemetry.phase("destination"):
                                status = self.executor.execute(operation, secret)
                            result = Result("completed", "healthy" if 200 <= status < 300 else "unhealthy", status)
                    del secret
                except ProviderFailure:
                    result = Result("failed", "provider_failed")
                except DestinationFailure:
                    result = Result("uncertain", "unknown")
                except Rejected:
                    result = Result("denied", "denied")

            result = evolve(result, audit_warning=warning)
            result = self.ledger.finish(request.request_id, result)
            return self.outcome(result, attributes, warning)
        except Rejected:
            try:
                return self.outcome(Result("denied", "denied"), attributes, warning)
            except AuditFailure:
                return Result("failed", "audit_failed")
        except AuditFailure:
            # A storage failure after submission cannot establish whether the destination performed the operation.
            return Result("uncertain" if attempted else "failed", "audit_failed")
