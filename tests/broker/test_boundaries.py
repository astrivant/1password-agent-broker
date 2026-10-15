"""
Verify identity, input, authority, replay, and audit boundaries through real TLS.
"""

from __future__ import annotations

import json
import sqlite3
import ssl
from contextlib import closing
from http.client import HTTPSConnection
from typing import TYPE_CHECKING

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.ledger import statement
from agent_broker.models import Result
from attrs import evolve

if TYPE_CHECKING:
    from agent_broker.testing.scenario import Scenario


@pytest.mark.parametrize("principal", ["alpha", "bravo"])
def test_tls_execution_and_replay(fixture: Scenario, principal: str) -> None:
    """
    Execute each identity's own operation exactly once, including response-loss recovery.

    Args:
        fixture (Scenario): Synthetic environment.
        principal (str): Selected workload identity.

    Returns:
        None: Assert a fresh result and a durable replay share one side effect.
    """
    request = contracts.data(fixture.request(principal))
    first = fixture.clients[principal].call(request)
    replay = fixture.clients[principal].call(request)
    assert first == Result("completed", "healthy", 204)
    assert replay == evolve(first, replayed=True)
    assert len(fixture.provider.calls) == len(fixture.destination_calls) == 1
    assert not any(secret.encode() in (fixture.root / "audit.db").read_bytes() for secret in fixture.provider.secrets.values())


def test_cross_identity_and_missing_certificate(fixture: Scenario) -> None:
    """
    Reject another workload's request and clients without a TLS credential.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert neither attack reaches credential resolution.
    """
    request = contracts.data(fixture.request("bravo"))
    assert fixture.clients["alpha"].call(request).state == "denied"
    client = fixture.clients["alpha"]
    connection = HTTPSConnection(client.host, client.port, context=ssl.create_default_context(cafile=fixture.root / "ca.pem"))
    try:
        with pytest.raises(OSError):
            connection.request("POST", "/execute", body=contracts.encode(request), headers={"Content-Type": "application/json"})
            connection.getresponse()
    finally:
        connection.close()
    assert fixture.provider.calls == fixture.destination_calls == []


@pytest.mark.parametrize("field", ["url", "method", "headers", "reference", "vault", "item", "field", "identity", "instructions"])
def test_injected_fields_rejected(fixture: Scenario, field: str) -> None:
    """
    Keep model instructions and arbitrary credential selectors outside the schema.

    Args:
        fixture (Scenario): Synthetic environment.
        field (str): Disallowed selector or instruction field.

    Returns:
        None: Assert rejection happens before secret access.
    """
    payload = {**contracts.data(fixture.request()), field: "untrusted-input"}
    assert fixture.clients["alpha"].call(payload).state == "denied"
    assert not fixture.provider.calls and not fixture.destination_calls


@pytest.mark.parametrize("change", ["expired", "revoked", "policy"])
def test_current_authority_required(fixture: Scenario, change: str) -> None:
    """
    Revalidate grants and policy rather than treating cached sessions as authorization.

    Args:
        fixture (Scenario): Synthetic environment.
        change (str): Authority mutation before execution.

    Returns:
        None: Assert stale authorization cannot resolve a credential.
    """
    request = fixture.request()
    if change == "policy":
        policy, _ = contracts.policy(fixture.root / "policy.json")
        policy.principals["alpha"] = evolve(policy.principals["alpha"], identity_revision="reviewed-v2")
        write_private(fixture.root / "policy.json", contracts.data(policy))
    else:
        grants = contracts.approvals(fixture.root / "approvals.json")
        grant = grants[request.approval_id]
        grants[request.approval_id] = evolve(grant, expires_at=0) if change == "expired" else evolve(grant, revoked=True)
        write_private(fixture.root / "approvals.json", {key: contracts.data(value) for key, value in grants.items()})
    assert fixture.clients["alpha"].call(contracts.data(request)).state == "denied"
    assert not fixture.provider.calls


def test_rotation_and_audit_events(fixture: Scenario) -> None:
    """
    Resolve the current token on every approved operation and retain attributable events.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert rotation needs no agent restart and events contain no secret values.
    """
    first = fixture.request()
    assert fixture.clients["alpha"].call(contracts.data(first)).code == "healthy"
    fixture.provider.secrets["op://synthetic/alpha/token"] = "rotated-synthetic-canary"
    assert fixture.clients["alpha"].call(contracts.data(fixture.request())).code == "healthy"
    with closing(sqlite3.connect(fixture.root / "audit.db")) as connection:
        events = [json.loads(row[0]) for row in connection.execute(statement("events"))]
    assert {event["body"] for event in events} >= {"requested", "allowed", "attempted", "completed"}
    assert all(event["attributes"]["identity.id"] == "alpha" for event in events)
    assert all(len(event["attributes"]["trace.id"]) == 32 for event in events)
    assert "rotated-synthetic-canary" not in json.dumps(events)


def test_pending_and_conflicting_replays(fixture: Scenario) -> None:
    """
    Treat interrupted attempts as uncertain and reject UUID reuse with changed input.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert a durable reservation prevents re-execution after process loss.
    """
    request = fixture.request()
    _, revision = contracts.policy(fixture.root / "policy.json")
    binding = contracts.digest({"request": contracts.data(request), "principal": "alpha", "policy": revision})
    assert fixture.broker.ledger.claim(request.request_id, "alpha", binding) is None
    assert fixture.clients["alpha"].call(contracts.data(request)) == Result("uncertain", "unknown", replayed=True)
    crossed = fixture.broker.ledger.claim(request.request_id, "bravo", binding)
    changed = fixture.broker.ledger.claim(request.request_id, "alpha", "different")
    assert crossed is not None and crossed.state == "denied"
    assert changed is not None and changed.state == "denied"
    assert fixture.provider.calls == fixture.destination_calls == []


def test_cancel_before_execution(fixture: Scenario) -> None:
    """
    Retain cancellation even when it arrives before execution starts.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert cancelled work never reads a secret or contacts a destination.
    """
    payload = contracts.data(fixture.request())
    assert fixture.clients["alpha"].call(payload, cancel=True).state == "cancelled"
    assert fixture.clients["alpha"].call(payload).state == "cancelled"
    assert fixture.provider.calls == fixture.destination_calls == []
