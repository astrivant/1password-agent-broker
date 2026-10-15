"""
Expose trusted-service cryptography only on the broker's authenticated control listener.
"""

from __future__ import annotations

import hashlib
import json
import ssl
from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import Blueprint, Response, request

from agent_broker import contracts
from agent_broker.crypto.models import Response as CryptoResponse

if TYPE_CHECKING:
    import threading

    from agent_broker.crypto.service import CryptoService


def routes(service: CryptoService, slots: threading.BoundedSemaphore) -> Blueprint:
    """
    Compose bounded key operations without adding any MCP tool or opening a second application.

    Args:
        service (CryptoService): Operator-selected key service.
        slots (threading.BoundedSemaphore): Shared execution budget, preserving reserved recovery capacity.

    Returns:
        Blueprint: Service-only cryptographic route.
    """
    blueprint = Blueprint("crypto", __name__)
    telemetry = service.ledger.telemetry

    @blueprint.post("/crypto")
    def dispatch() -> Response:
        """
        Admit only a verified TLS peer and release every owned concurrency slot.

        Returns:
            Response: Uncacheable bounded key-service response with no reflected diagnostics.
        """
        if telemetry.draining.is_set() or not slots.acquire(blocking=False):
            telemetry.rejected.inc()
            return Response('{"code":"unavailable"}', status=HTTPStatus.SERVICE_UNAVAILABLE, content_type="application/json")
        try:
            with telemetry.request():
                result = CryptoResponse("denied")
                certificate = request.environ.get("SSL_CLIENT_CERT")
                if (
                    request.environ.get("SSL_CLIENT_VERIFY") == "SUCCESS"
                    and isinstance(certificate, str)
                    and request.content_length is not None
                    and 0 < request.content_length <= 4096
                    and not request.headers.get("Transfer-Encoding")
                    and request.mimetype == "application/json"
                ):
                    try:
                        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
                        raw = json.loads(request.get_data())
                    except (ValueError, OSError):
                        pass
                    else:
                        result = service.handle(fingerprint, raw)
                telemetry.responses.labels("crypto", result.code).inc()
                return Response(contracts.encode(contracts.data(result)), content_type="application/json")
        finally:
            slots.release()

    return blueprint
