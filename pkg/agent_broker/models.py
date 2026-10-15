"""
Keep request, policy, approval, and result contracts closed and independent of transport.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

ResultState = Literal["completed", "denied", "failed", "uncertain", "cancelled"]
ResultCode = Literal[
    "healthy", "unhealthy", "denied", "invalid_request", "provider_failed", "unknown", "cancelled", "audit_failed", "crypto_completed"
]


@frozen
class Request:
    """
    Select an operator-approved capability; identity and credential inputs are absent.

    Attributes:
        request_id (str): Caller-owned UUID retained across retries.
        operation (str): Named capability in the operator policy.
        approval_id (str): Opaque reference to an exact operator grant.
    """

    request_id: str
    operation: str
    approval_id: str


@frozen
class Principal:
    """
    Bind a verified client certificate to a curated identity revision and one run.

    Attributes:
        certificate_sha256 (str): SHA-256 of the verified workload certificate DER.
        identity_id (str): Reviewed identity collection identifier.
        identity_revision (str): Immutable reviewed knowledge revision.
        run_id (str): Operator-assigned execution run.
        operations (tuple[str, ...]): Permitted named capabilities.
        task_id (str | None): Optional operator-owned task attribution; absent on legacy policies.
    """

    certificate_sha256: str
    identity_id: str
    identity_revision: str
    run_id: str
    operations: tuple[str, ...]
    task_id: str | None = None


@frozen
class Credential:
    """
    Select an exact 1Password field and the broker-only bootstrap environment variable.

    Attributes:
        reference (str): Exact 1Password field URI, never supplied by the agent.
        bootstrap_env (str): Broker-only token selector, defaulting to the official service-account variable.
    """

    reference: str
    bootstrap_env: str = "OP_SERVICE_ACCOUNT_TOKEN"


@frozen
class Operation:
    """
    Declare a fixed destination and credential alias for an implemented capability.

    Attributes:
        credential (str): Alias selecting one operator-owned credential.
        url (str): Fixed HTTPS destination without user info, query, or fragment.
        kind (Literal['health']): Implemented capability adapter.
    """

    credential: str
    url: str
    kind: Literal["health"] = "health"


@frozen
class Policy:
    """
    Describe operator-owned authorization state reloaded for every request.

    Attributes:
        principals (dict[str, Principal]): Workload names bound to verified certificates.
        credentials (dict[str, Credential]): Credential aliases scoped by operator configuration.
        operations (dict[str, Operation]): Implemented capabilities and fixed destinations.
        version (Literal[1]): Contract schema version.
    """

    principals: dict[str, Principal]
    credentials: dict[str, Credential]
    operations: dict[str, Operation]
    version: Literal[1] = 1


@frozen
class Approval:
    """
    Authorize one exact request and policy revision until a UTC epoch deadline.

    Attributes:
        request_id (str): Caller-owned UUID retained across retries.
        principal (str): Exact workload approved for this request.
        operation (str): Named capability in the operator policy.
        policy_sha256 (str): Canonical policy hash invalidating stale grants after edits.
        expires_at (int): Grant expiry as UTC epoch seconds.
        revoked (bool): Immediate operator cancellation of this grant.
    """

    request_id: str
    principal: str
    operation: str
    policy_sha256: str
    expires_at: int
    revoked: bool = False


@frozen
class Result:
    """
    Return bounded status information without bodies, headers, URLs, or credentials.

    Attributes:
        state (ResultState): Execution certainty and completion state.
        code (ResultCode): Bounded diagnostic code without remote content.
        status_code (int | None): Remote HTTP status only, when known.
        replayed (bool): Whether the durable ledger supplied this outcome.
        audit_warning (bool): Whether optional export failed while durable recording succeeded.
    """

    state: ResultState
    code: ResultCode
    status_code: int | None = None
    replayed: bool = False
    audit_warning: bool = False
