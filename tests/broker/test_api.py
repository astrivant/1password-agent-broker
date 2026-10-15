"""
Verify shared application composition, listener trust, and operational isolation.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.request import urlopen

import pytest
from agent_broker import contracts
from agent_broker.api import APIBuilder
from agent_broker.api.server import BrokerServer
from agent_broker.exceptions import DestinationFailure
from agent_broker.lifecycle import running

if TYPE_CHECKING:
    from agent_broker.models import Operation
    from agent_broker.testing.scenario import Scenario
    from werkzeug.test import TestResponse


def body(response: TestResponse) -> dict[str, object]:
    """
    Require structured JSON output before asserting individual operational fields.

    Args:
        response (TestResponse): Flask test response.

    Returns:
        dict[str, object]: Validated object envelope.
    """
    value = response.get_json()
    assert isinstance(value, dict)
    return {str(key): item for key, item in value.items()}


def test_builder_and_metrics(fixture: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Require dependencies and report local queues without provider or database work.

    Args:
        fixture (Scenario): Isolated broker service.
        monkeypatch (pytest.MonkeyPatch): Dependency failure injection.

    Returns:
        None: Verify immutable composition and redacted status on the shared app.
    """
    builder = APIBuilder()
    with pytest.raises(ValueError):
        builder.build()
    app = builder.with_broker(fixture.broker).build()
    assert builder.broker is None
    assert set(app.blueprints) == {"broker", "observability"}
    client = app.test_client()
    scope = {"broker.listener": "observability"}
    monkeypatch.setattr(fixture.broker.ledger, "ready", lambda: False)
    with fixture.broker.ledger.telemetry.request():
        response = client.get("/healthz", environ_overrides=scope)
        assert body(response)["in_flight"] == 1
        queues = body(response)["queues"]
        assert isinstance(queues, dict) and set(queues) == {"database", "http"}
        metrics = client.get("/metrics", environ_overrides=scope)
        assert b"broker_requests_in_flight 1.0" in metrics.data
        assert b"broker_queue_size" in metrics.data
    response = client.get("/readyz", environ_overrides=scope)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert body(response)["status"] == "unavailable"
    assert body(response)["message"] == "Operator configuration or durable storage is unavailable"
    fixture.broker.ledger.telemetry.state("draining")
    monkeypatch.setattr(fixture.broker.ledger, "ready", lambda: True)
    assert client.get("/readyz", environ_overrides=scope).status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert client.get("/livez", environ_overrides=scope).status_code == HTTPStatus.OK
    assert fixture.provider.calls == []
    assert response.headers["Cache-Control"] == "no-store"


def test_listener_boundary(fixture: Scenario) -> None:
    """
    Ignore attacker-controlled routing and client-certificate headers.

    Args:
        fixture (Scenario): Isolated broker service.

    Returns:
        None: Verify transport metadata, not HTTP headers, grants route access.
    """
    app = APIBuilder().with_broker(fixture.broker).build()
    client = app.test_client()
    payload = contracts.data(fixture.request())
    headers = {"X-Forwarded-Port": "8443", "SSL-Client-Verify": "SUCCESS", "Host": "broker:8443"}
    assert client.post("/execute", json=payload, headers=headers).status_code == HTTPStatus.NOT_FOUND
    assert client.post("/execute", json=payload, environ_overrides={"broker.listener": "observability"}).status_code == HTTPStatus.NOT_FOUND
    result = client.post("/execute", json=payload, headers=headers, environ_overrides={"broker.listener": "control"})
    assert body(result)["state"] == "denied"
    assert client.get("/metrics", environ_overrides={"broker.listener": "control"}).status_code == HTTPStatus.NOT_FOUND
    assert fixture.provider.calls == []


def test_saturation_retains_recovery(fixture: Scenario) -> None:
    """
    Preserve recovery admission while one permitted execution is actively blocked.

    Args:
        fixture (Scenario): Isolated broker service.

    Returns:
        None: Verify bounded execution, live metrics, and cooperative draining.
    """
    entered, release = threading.Event(), threading.Event()
    original = fixture.broker.executor

    class BlockingExecutor:
        """
        Coordinate saturation using events rather than elapsed-time assumptions.
        """

        def execute(self, operation: Operation, secret: str) -> int:
            """
            Hold destination admission until the test releases it.

            Args:
                operation (Operation): Approved synthetic destination.
                secret (str): Synthetic credential.

            Returns:
                int: Actual destination status after release.
            """
            entered.set()
            if not release.wait(10):
                raise DestinationFailure("Test coordination failed")
            return original.execute(operation, secret)

    fixture.broker.executor = BlockingExecutor()
    app = APIBuilder(capacity=1).with_broker(fixture.broker).build()
    scope = {
        "broker.listener": "control",
        "SSL_CLIENT_VERIFY": "SUCCESS",
        "SSL_CLIENT_CERT": (fixture.root / "alpha.pem").read_text(),
    }
    payload = contracts.data(fixture.request())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(app.test_client().post, "/execute", json=payload, environ_overrides=scope)
        try:
            assert entered.wait(10)
            client = app.test_client()
            assert client.post("/execute", json=payload, environ_overrides=scope).status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert body(client.post("/status", json=payload, environ_overrides=scope))["state"] == "uncertain"
            assert body(client.post("/cancel", json=payload, environ_overrides=scope))["state"] == "uncertain"
            fixture.broker.ledger.telemetry.state("draining")
            assert client.post("/execute", json=payload, environ_overrides=scope).status_code == HTTPStatus.SERVICE_UNAVAILABLE
        finally:
            release.set()
        assert body(pending.result(timeout=10))["state"] == "uncertain"
    assert len(fixture.destination_calls) == 1


def test_monitoring_socket_lifecycle(fixture: Scenario) -> None:
    """
    Exercise the real HTTP monitoring listener sharing the authenticated application.

    Args:
        fixture (Scenario): Isolated broker service and generated TLS material.

    Returns:
        None: Verify monitoring serves, shuts down, and leaves no owned worker threads.
    """
    root = fixture.root
    server = BrokerServer(("127.0.0.1", 0), fixture.broker, root / "server.pem", root / "server.key", root / "ca.pem", ("127.0.0.1", 0))
    with running(server), urlopen(f"http://127.0.0.1:{server.metrics_port}/readyz", timeout=5) as response:
        assert response.status == HTTPStatus.OK
        assert b"Broker accepts approved operations" in response.read()
    server.shutdown()
    assert fixture.broker.ledger.telemetry.snapshot()["status"] == "draining"
