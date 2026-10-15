"""
Construct the process application once after validating its service dependencies.
"""

from __future__ import annotations

import threading
from http import HTTPStatus
from typing import TYPE_CHECKING

from attrs import evolve, frozen
from flask import Flask, Response, request
from werkzeug.exceptions import HTTPException

from agent_broker.api.broker import routes
from agent_broker.api.metrics import MetricsBuilder
from agent_broker.crypto.api import routes as crypto_routes

if TYPE_CHECKING:
    from agent_broker.crypto.service import CryptoService
    from agent_broker.engine import Broker


@frozen
class APIBuilder:
    """
    Compose an application without opening sockets or creating global service instances.

    Attributes:
        broker (Broker | None): Injected authorization and execution service.
        capacity (int): Maximum concurrent broker handlers.
        crypto (CryptoService | None): Explicit opt-in service-only key boundary.
    """

    broker: Broker | None = None
    capacity: int = 8
    crypto: CryptoService | None = None

    def with_broker(self, broker: Broker) -> APIBuilder:
        """
        Return a configured copy while preserving the original builder.

        Args:
            broker (Broker): Ready service with operator-owned dependencies.

        Returns:
            APIBuilder: Copy containing the service.
        """
        return evolve(self, broker=broker)

    def build(self) -> Flask:
        """
        Assemble all blueprints and common response boundaries on one Flask instance.

        Returns:
            Flask: Application ready for the production WSGI runtime.

        Raises:
            ValueError: A required dependency or concurrency limit is invalid.
        """
        if self.broker is None or not 1 <= self.capacity <= 64:
            raise ValueError("A broker and capacity between 1 and 64 are required")

        # Compose both route families once; listeners supply their own trusted routing scope at dispatch.
        app = Flask(__name__, static_folder=None)
        app.config.update(MAX_CONTENT_LENGTH=4096, PROPAGATE_EXCEPTIONS=False)
        app.url_map.merge_slashes = False
        slots = threading.BoundedSemaphore(self.capacity)
        app.register_blueprint(routes(self.broker, slots))
        if self.crypto is not None:
            app.register_blueprint(crypto_routes(self.crypto, slots))
        MetricsBuilder(self.broker).build(app)

        @app.before_request
        def listener_boundary() -> Response | None:
            """
            Restrict route families to trusted listener metadata, never proxy or Host headers.

            Returns:
                Response | None: A fixed denial, or permission to dispatch the selected family.
            """

            # Host and forwarded headers cannot promote an observability request into a control request.
            expected = "control" if request.blueprint in {"broker", "crypto"} else "observability"
            if request.environ.get("broker.listener") != expected:
                return Response('{"error":"not found"}', status=HTTPStatus.NOT_FOUND, content_type="application/json")
            return None

        @app.after_request
        def uncached(response: Response) -> Response:
            """
            Keep all operational responses out of intermediary caches.

            Args:
                response (Response): Bounded route response.

            Returns:
                Response: Response with explicit cache policy.
            """
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.errorhandler(Exception)
        def failure(error: Exception) -> Response:
            """
            Redact unexpected exception text at the HTTP boundary.

            Args:
                error (Exception): Framework or service exception; never serialized or logged.

            Returns:
                Response: Fixed operational error without diagnostic content.
            """
            code = error.code or HTTPStatus.INTERNAL_SERVER_ERROR if isinstance(error, HTTPException) else HTTPStatus.INTERNAL_SERVER_ERROR
            return Response('{"error":"request unavailable"}', status=code, content_type="application/json")

        return app
