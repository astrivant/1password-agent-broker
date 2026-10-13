"""
Register metrics, dependency readiness, and fixed status messages on the shared app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import frozen
from flask import Blueprint, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from agent_broker import contracts
from agent_broker.exceptions import Rejected

if TYPE_CHECKING:
    from flask import Flask

    from agent_broker.engine import Broker


@frozen
class MetricsBuilder:
    """
    Attach operational views without constructing a second Flask application.

    Attributes:
        broker (Broker): Service whose lifecycle and storage are observed.
    """

    broker: Broker

    def build(self, application: Flask) -> Flask:
        """
        Register read-only operational endpoints on the required shared application.

        Args:
            application (Flask): Existing process application.

        Returns:
            Flask: The same application with its metrics blueprint registered.
        """
        blueprint = Blueprint("observability", __name__)
        telemetry = self.broker.ledger.telemetry

        @blueprint.get("/metrics")
        def metrics() -> Response:
            """
            Export local measurements without making provider or storage calls.

            Returns:
                Response: Prometheus metrics with fixed, bounded labels.
            """
            return Response(generate_latest(telemetry.registry), content_type=CONTENT_TYPE_LATEST)

        @blueprint.get("/healthz")
        @blueprint.get("/livez")
        def status() -> Response:
            """
            Report process liveness, queue sizes, and a fixed lifecycle message.

            Returns:
                Response: Local operational snapshot; draining does not imply a crashed process.
            """
            return Response(contracts.encode(telemetry.snapshot()), content_type="application/json")

        @blueprint.get("/readyz")
        def ready() -> Response:
            """
            Check configuration and durable storage without resolving any credential.

            Returns:
                Response: Ready status, or 503 while unavailable or draining.
            """
            available = False
            if not telemetry.draining.is_set():
                try:
                    contracts.policy(self.broker.policy)
                    contracts.approvals(self.broker.approvals)
                    available = self.broker.ledger.ready()
                except (Rejected, OSError, ValueError):
                    pass
            available = available and not telemetry.draining.is_set()
            telemetry.state("ready" if available else "unavailable")
            return Response(contracts.encode(telemetry.snapshot()), status=200 if available else 503, content_type="application/json")

        application.register_blueprint(blueprint)
        return application
