"""
Translate bounded authenticated HTTP input into the existing broker service contract.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import threading
from typing import TYPE_CHECKING

from flask import Blueprint, Response, request

from agent_broker.contracts import data, encode
from agent_broker.models import Result

if TYPE_CHECKING:
    from agent_broker.engine import Broker


def routes(broker: Broker, capacity: int) -> Blueprint:
    """
    Create a thin capability blueprint with bounded, nonblocking admission.

    Args:
        broker (Broker): Injected domain service.
        capacity (int): Maximum active handlers; excess work receives 503.

    Returns:
        Blueprint: Execution, cancellation, and result-inspection routes.
    """
    blueprint = Blueprint("broker", __name__)
    slots = threading.BoundedSemaphore(capacity)
    recovery = threading.BoundedSemaphore(2)
    telemetry = broker.ledger.telemetry

    @blueprint.post("/execute")
    @blueprint.post("/cancel")
    @blueprint.post("/status")
    def dispatch() -> Response:
        """
        Bind identity to the TLS server's verified certificate before domain dispatch.

        Returns:
            Response: Closed broker result or a fixed admission failure.
        """
        # Keep cancellation and inspection available while execution consumes its budget.
        admission = slots if request.path == "/execute" else recovery
        if telemetry.draining.is_set() or not admission.acquire(blocking=False):
            telemetry.rejected.inc()
            return Response('{"error":"broker unavailable"}', status=503, content_type="application/json")
        try:
            with telemetry.request():
                result = Result("denied", "invalid_request")

                # Accept attribution only from the TLS adapter and reject ambiguous or oversized body framing.
                certificate = request.environ.get("SSL_CLIENT_CERT")
                length = request.content_length
                if (
                    request.environ.get("SSL_CLIENT_VERIFY") == "SUCCESS"
                    and isinstance(certificate, str)
                    and length is not None
                    and 0 < length <= 4096
                    and not request.headers.get("Transfer-Encoding")
                    and request.mimetype == "application/json"
                ):
                    try:
                        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
                        raw = json.loads(request.get_data())
                    except (ValueError, OSError):
                        pass
                    else:
                        result = broker.handle(fingerprint, raw, cancel=request.path == "/cancel", inspect=request.path == "/status")
                telemetry.responses.labels(request.path[1:], result.state).inc()
                return Response(encode(data(result)), content_type="application/json")
        finally:
            # Exceptions and malformed requests must return capacity just like successful executions.
            admission.release()

    return blueprint
