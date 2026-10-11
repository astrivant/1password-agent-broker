"""
Create operator-reviewed, short-lived grants without passing authority through the model.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_broker import contracts
from agent_broker.exceptions import Rejected
from agent_broker.models import Approval, Request

if TYPE_CHECKING:
    from pathlib import Path


def write_private(path: Path, value: object) -> None:
    """
    Replace an operator file atomically with owner-only permissions.

    Args:
        path (Path): Destination in a trusted private directory.
        value (object): JSON-compatible data.

    Returns:
        None: Commit a complete file; callers serialize concurrent configuration edits.
    """
    descriptor, temporary = tempfile.mkstemp(prefix=".broker-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contracts.encode(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def approve(policy_path: Path, approvals_path: Path, principal: str, operation: str, ttl: int) -> Request:
    """
    Bind one new request to a permitted capability and the current policy revision.

    Args:
        policy_path (Path): Operator-owned policy.
        approvals_path (Path): Operator-owned grant file.
        principal (str): Reviewed workload name.
        operation (str): Exact permitted capability.
        ttl (int): Validity in seconds, from 1 to 3600.

    Returns:
        Request: Safe identifiers to pass to the agent.

    Raises:
        Rejected: The principal, capability, or duration is invalid.
    """
    policy, revision = contracts.policy(policy_path)
    if principal not in policy.principals or operation not in policy.principals[principal].operations or not 1 <= ttl <= 3600:
        raise Rejected("Invalid approval")
    grants = contracts.approvals(approvals_path) if approvals_path.exists() else {}
    request = Request(str(uuid4()), operation, str(uuid4()))
    grants[request.approval_id] = Approval(request.request_id, principal, operation, revision, int(time.time()) + ttl)
    write_private(approvals_path, {name: contracts.data(grant) for name, grant in grants.items()})
    return request
