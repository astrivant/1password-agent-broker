"""
Exercise cross-replica replay invariants against an explicitly selected disposable PostgreSQL database.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.engine import Broker
from agent_broker.ledger import Ledger
from agent_broker.models import Result

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agent_broker.testing.scenario import Scenario

pytestmark = pytest.mark.skipif(os.getenv("BROKER_TEST_POSTGRES") != "1", reason="Disposable PostgreSQL not selected")


@pytest.fixture
def replicas() -> Iterator[tuple[Ledger, Ledger]]:
    """
    Open independent pools using native PG settings in a dedicated test database.

    Yields:
        tuple[Ledger, Ledger]: Two application replicas sharing durable reservations.
    """
    first = Ledger(None)
    try:
        second = Ledger(None)
        try:
            yield first, second
        finally:
            second.close()
    finally:
        first.close()


def test_cross_replica_claim_and_recovery(replicas: tuple[Ledger, Ledger]) -> None:
    """
    Permit one owner under simultaneous claims and recover its outcome on another replica.

    Args:
        replicas (tuple[Ledger, Ledger]): Independent database pools.

    Returns:
        None: Verify unique admission, shared cancellation, and permanent replay protection.
    """
    first, second = replicas
    request_id = str(uuid4())
    barrier = threading.Barrier(2)

    def claim(ledger: Ledger) -> Result | None:
        """
        Release two competing owners at the same reservation boundary.

        Args:
            ledger (Ledger): Candidate replica.

        Returns:
            Result | None: Ownership or the existing pending outcome.
        """
        barrier.wait(timeout=5)
        return ledger.claim(request_id, "workload", "binding", "recovery")

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, replicas))
    assert outcomes.count(None) == 1
    assert Result("uncertain", "unknown", replayed=True) in outcomes
    assert first.begin(request_id)
    assert not second.begin(request_id)
    assert second.cancel(request_id, "workload", "binding", "recovery").state == "uncertain"
    assert first.finish(request_id, Result("completed", "healthy", HTTPStatus.NO_CONTENT)).state == "uncertain"
    assert second.inspect(request_id, "workload", "recovery").state == "uncertain"
    assert second.inspect(request_id, "other", "recovery").state == "denied"
    assert first.ready() and second.ready()


def test_cancel_before_submission(replicas: tuple[Ledger, Ledger]) -> None:
    """
    Observe cancellation committed by another replica before any destination submission.

    Args:
        replicas (tuple[Ledger, Ledger]): Independent database pools.

    Returns:
        None: Verify cancellation prevents begin and replay preserves the stored outcome.
    """
    first, second = replicas
    request_id = str(uuid4())
    assert first.claim(request_id, "workload", "binding", "recovery") is None
    assert second.cancel(request_id, "workload", "binding", "recovery").state == "cancelled"
    assert not first.begin(request_id)
    result = first.finish(request_id, Result("cancelled", "cancelled"))
    assert second.inspect(request_id, "workload", "recovery").state == result.state
    replayed = second.claim(request_id, "workload", "binding", "recovery")
    assert replayed is not None and replayed.replayed


def test_two_brokers_execute_once(replicas: tuple[Ledger, Ledger], fixture: Scenario) -> None:
    """
    Send the same request to independent broker engines backed by the shared database.

    Args:
        replicas (tuple[Ledger, Ledger]): Independent database pools.
        fixture (Scenario): Real synthetic HTTPS destination and workload identity.

    Returns:
        None: Verify one destination call and cross-replica recovery after grant revocation.
    """
    first, second = replicas
    original = fixture.broker.ledger
    fixture.broker.ledger = first
    peer = Broker(fixture.broker.policy, fixture.broker.approvals, second, fixture.provider, fixture.broker.executor)
    payload = contracts.data(fixture.request())
    barrier = threading.Barrier(2)

    def execute(broker: Broker) -> Result:
        """
        Race replica admission with identical authenticated input.

        Args:
            broker (Broker): Independent service instance.

        Returns:
            Result: Completed work or the shared pending reservation.
        """
        barrier.wait(timeout=5)
        return broker.handle(fixture.fingerprints["alpha"], payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(execute, (fixture.broker, peer)))
        assert any(result.state == "completed" for result in outcomes)
        assert len(fixture.provider.calls) == len(fixture.destination_calls) == 1
        write_private(fixture.broker.approvals, {})
        assert peer.handle(fixture.fingerprints["alpha"], payload, inspect=True).state == "completed"
        assert peer.handle(fixture.fingerprints["alpha"], payload).state == "denied"
    finally:
        fixture.broker.ledger = original
