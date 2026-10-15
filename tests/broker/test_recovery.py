"""
Verify identity-attributed recovery and cancellation independently of execution grants.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.exceptions import AuditFailure, DestinationFailure
from agent_broker.ledger import Ledger, statement
from agent_broker.models import Result
from attrs import evolve
from jsonschema import validate

if TYPE_CHECKING:
    from agent_broker.models import Operation
    from agent_broker.testing.scenario import Scenario


def events(fixture: Scenario) -> list[dict[str, object]]:
    """
    Read and validate the durable audit rather than trusting response diagnostics.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        list[dict[str, object]]: Closed audit records in insertion order.
    """
    with closing(sqlite3.connect(fixture.root / "audit.db")) as connection:
        records: list[dict[str, object]] = [json.loads(row[0]) for row in connection.execute(statement("events"))]
    for record in records:
        validate(record, contracts.schema("event"))
    return records


@pytest.mark.parametrize("reason", ["expired", "cross-identity", "injected"])
def test_denial_attribution(fixture: Scenario, reason: str) -> None:
    """
    Preserve verified caller attribution while excluding client-supplied metadata.

    Args:
        fixture (Scenario): Synthetic broker environment.
        reason (str): Denial boundary to exercise.

    Returns:
        None: Assert the audit identifies the caller without recording rejected text.
    """
    request = fixture.request("bravo" if reason == "cross-identity" else "alpha")
    payload = contracts.data(request)
    canary = "untrusted-attribution-canary"
    if reason == "expired":
        grants = contracts.approvals(fixture.root / "approvals.json")
        grants[request.approval_id] = evolve(grants[request.approval_id], expires_at=0)
        write_private(fixture.root / "approvals.json", {key: contracts.data(value) for key, value in grants.items()})
    elif reason == "injected":
        payload["task_id"] = canary
    assert fixture.clients["alpha"].call(payload).state == "denied"
    records = events(fixture)
    assert records[-1]["body"] == "denied"
    attributes = records[-1]["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["identity.id"] == "alpha"
    assert attributes["run.id"] == "demo-run"
    assert canary not in json.dumps(records)
    assert fixture.provider.calls == fixture.destination_calls == []


def test_recovery_after_revocation_and_policy_edit(fixture: Scenario) -> None:
    """
    Inspect completed work after expiry or capability removal without restoring authority.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert recovery remains read-only and execution remains denied.
    """
    payload = contracts.data(fixture.request())
    first = fixture.clients["alpha"].call(payload)
    write_private(fixture.root / "approvals.json", {})
    policy, _ = contracts.policy(fixture.root / "policy.json")
    policy.principals["alpha"] = evolve(policy.principals["alpha"], operations=())
    del policy.operations["alpha-health"]
    write_private(fixture.root / "policy.json", contracts.data(policy))
    assert fixture.clients["alpha"].call(payload, inspect=True) == evolve(first, replayed=True)
    assert fixture.clients["alpha"].call(payload, cancel=True) == evolve(first, replayed=True)
    assert fixture.clients["alpha"].call(payload).state == "denied"
    assert len(fixture.provider.calls) == len(fixture.destination_calls) == 1
    records = events(fixture)
    assert [record["body"] for record in records][-5:] == ["completed", "requested", "completed", "requested", "denied"]


@pytest.mark.parametrize("change", ["approval", "operation", "identity", "revision", "run", "task", "retired", "caller"])
def test_recovery_requires_original_identity_and_request(fixture: Scenario, change: str) -> None:
    """
    Keep recovery results scoped to their exact original request and identity snapshot.

    Args:
        fixture (Scenario): Synthetic broker environment.
        change (str): Forged request or changed operator binding.

    Returns:
        None: Assert another request or identity context cannot recover the result.
    """
    payload = contracts.data(fixture.request())
    assert fixture.clients["alpha"].call(payload).state == "completed"
    policy, _ = contracts.policy(fixture.root / "policy.json")
    principal = policy.principals["alpha"]
    if change == "approval":
        payload["approval_id"] = "another-approval"
    elif change == "operation":
        payload["operation"] = "bravo-health"
    elif change == "identity":
        policy.principals["alpha"] = evolve(principal, identity_id="another-identity")
    elif change == "revision":
        policy.principals["alpha"] = evolve(principal, identity_revision="reviewed-v2")
    elif change == "run":
        policy.principals["alpha"] = evolve(principal, run_id="another-run")
    elif change == "task":
        policy.principals["alpha"] = evolve(principal, task_id="another-task")
    elif change == "retired":
        del policy.principals["alpha"]
    write_private(fixture.root / "policy.json", contracts.data(policy))
    client = fixture.clients["bravo" if change == "caller" else "alpha"]
    assert client.call(payload, inspect=True).state == "denied"
    assert len(fixture.provider.calls) == len(fixture.destination_calls) == 1


def test_inspection_does_not_reserve_or_execute(fixture: Scenario) -> None:
    """
    Inspect an unknown request without consuming its grant or creating a reservation.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert the subsequent approved execution still runs exactly once.
    """
    payload = contracts.data(fixture.request())
    assert fixture.clients["alpha"].call(payload, inspect=True).state == "denied"
    assert fixture.provider.calls == []
    assert fixture.clients["alpha"].call(payload).state == "completed"
    assert len(fixture.destination_calls) == 1


def test_task_attribution_and_replay_outcomes(fixture: Scenario) -> None:
    """
    Bind task attribution to operator policy and record actual replay outcomes.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert task identity and replay evidence survive the complete request flow.
    """
    policy, _ = contracts.policy(fixture.root / "policy.json")
    policy.principals["alpha"] = evolve(policy.principals["alpha"], task_id="synthetic-task")
    write_private(fixture.root / "policy.json", contracts.data(policy))
    payload = contracts.data(fixture.request())
    assert fixture.clients["alpha"].call(payload).state == "completed"
    assert fixture.clients["alpha"].call(payload).replayed
    records = events(fixture)
    attributes = records[-1]["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["task.id"] == "synthetic-task"
    assert attributes["result.replayed"] is True
    assert records[-1]["body"] == "completed"


def test_cancel_after_submission_is_uncertain(fixture: Scenario) -> None:
    """
    Serialize cancellation against destination admission and retain ambiguous outcomes.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert cancellation cannot claim to undo submitted work or enable a retry.
    """
    entered, release = threading.Event(), threading.Event()
    original = fixture.broker.executor

    class BlockingExecutor:
        """
        Hold an admitted destination operation until cancellation has been observed.
        """

        def execute(self, operation: Operation, secret: str) -> int:
            """
            Coordinate the submission race without timing-dependent sleeps.

            Args:
                operation (Operation): Approved destination.
                secret (str): Synthetic credential.

            Returns:
                int: Real synthetic service response after release.
            """
            entered.set()
            if not release.wait(10):
                raise DestinationFailure("Synthetic coordination timed out")
            return original.execute(operation, secret)

    fixture.broker.executor = BlockingExecutor()
    payload = contracts.data(fixture.request())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(fixture.clients["alpha"].call, payload)
        try:
            # The event proves submission was admitted before cancellation, avoiding a scheduler-dependent race.
            assert entered.wait(10)
            assert fixture.clients["alpha"].call(payload).state == "uncertain"
            assert fixture.clients["alpha"].call(payload, cancel=True).state == "uncertain"
        finally:
            # Always unblock the owned worker, including when an assertion fails.
            release.set()
        assert pending.result(timeout=10).state == "uncertain"
    assert fixture.clients["alpha"].call(payload, inspect=True) == Result("uncertain", "unknown", replayed=True)
    assert len(fixture.provider.calls) == len(fixture.destination_calls) == 1


def test_legacy_reservations_are_not_guessed(fixture: Scenario) -> None:
    """
    Preserve old reservations without inventing missing identity or submission evidence.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert reopening the ledger retains uncertainty and prevents execution.
    """
    request = fixture.request()
    payload = contracts.data(request)
    _, revision = contracts.policy(fixture.root / "policy.json")
    binding = contracts.digest({"request": payload, "principal": "alpha", "policy": revision})
    assert fixture.broker.ledger.claim(request.request_id, "alpha", binding) is None
    with fixture.broker.ledger.connection() as connection:
        connection.execute("DROP TABLE request_context")
    fixture.broker.ledger = Ledger(fixture.root / "audit.db")
    assert fixture.clients["alpha"].call(payload, inspect=True).state == "denied"
    assert fixture.clients["alpha"].call(payload, cancel=True).state == "uncertain"
    assert fixture.clients["alpha"].call(payload).state == "uncertain"
    assert fixture.provider.calls == fixture.destination_calls == []


def test_audit_schema_fails_before_storage_and_export(fixture: Scenario) -> None:
    """
    Reject unexpected audit attributes at the producer rather than relying on a collector.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert forbidden text reaches neither storage nor the exporter.
    """
    exported: list[dict[str, object]] = []
    fixture.broker.ledger.exporter = exported.append
    canary = "synthetic-unexpected-audit-value"
    with pytest.raises(AuditFailure, match="Invalid audit event"):
        fixture.broker.ledger.event("denied", {"provider.stderr": canary})
    assert not exported and not events(fixture)
    assert canary.encode() not in (fixture.root / "audit.db").read_bytes()


def test_terminal_audit_failure_preserves_result(fixture: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Surface missing terminal evidence while retaining the already completed result.

    Args:
        fixture (Scenario): Synthetic broker environment.
        monkeypatch (pytest.MonkeyPatch): Scoped storage failure injection.

    Returns:
        None: Assert inspection recovers completion without another destination attempt.
    """
    original = fixture.broker.ledger.event

    def unavailable(name: str, attributes: dict[str, object]) -> bool:
        """
        Fail only the terminal audit write after the result has been committed.

        Args:
            name (str): Event selected by the engine.
            attributes (dict[str, object]): Validated attribution.

        Returns:
            bool: Original exporter warning for nonterminal events.
        """
        if name == "completed":
            raise AuditFailure("Synthetic terminal storage failure")
        return original(name, attributes)

    payload = contracts.data(fixture.request())
    with monkeypatch.context() as patch:
        patch.setattr(fixture.broker.ledger, "event", unavailable)
        assert fixture.clients["alpha"].call(payload) == Result("uncertain", "audit_failed")
    assert fixture.clients["alpha"].call(payload, inspect=True) == Result("completed", "healthy", HTTPStatus.NO_CONTENT, replayed=True)
    assert len(fixture.destination_calls) == 1


def test_exporter_does_not_mutate_caller_attributes(fixture: Scenario) -> None:
    """
    Keep mutable export records separate from the engine's attribution state.

    Args:
        fixture (Scenario): Synthetic broker environment.

    Returns:
        None: Assert a sink cannot alter future identity fields through shared dictionaries.
    """

    def mutate(event: dict[str, object]) -> None:
        """
        Model a sink which enriches its own record in place.

        Args:
            event (dict[str, object]): Isolated export record.

        Returns:
            None: Modify only the export's copy.
        """
        attributes = event["attributes"]
        assert isinstance(attributes, dict)
        attributes["identity.id"] = "changed-by-sink"

    fixture.broker.ledger.exporter = mutate
    attributes: dict[str, object] = {"identity.id": "alpha"}
    fixture.broker.ledger.event("requested", attributes)
    assert attributes == {"identity.id": "alpha"}
    assert events(fixture)[0]["attributes"] == attributes
