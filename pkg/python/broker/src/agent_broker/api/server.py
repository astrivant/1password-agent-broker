"""
Own production WSGI listeners sharing one application and distinct trusted route scopes.
"""

from __future__ import annotations

import ssl
import threading
from typing import TYPE_CHECKING, Literal

from cheroot.ssl.builtin import BuiltinSSLAdapter
from cheroot.workers.threadpool import ThreadPool
from cheroot.wsgi import Server

from agent_broker.api.builder import APIBuilder

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from _typeshed.wsgi import StartResponse, WSGIEnvironment
    from flask import Flask

    from agent_broker.crypto.service import CryptoService
    from agent_broker.engine import Broker


class Listener(Server):
    """
    Supply socket-owned routing metadata and suppress unbounded HTTP diagnostics.
    """

    def __init__(
        self,
        address: tuple[str, int],
        application: Flask,
        scope: Literal["control", "observability"],
        workers: int,
        adapter: BuiltinSSLAdapter | None = None,
    ) -> None:
        """
        Prepare a bounded listener without running its accept loop.

        Args:
            address (tuple[str, int]): Operator-selected bind address.
            application (Flask): Sole process application.
            scope (Literal["control", "observability"]): Trusted route family.
            workers (int): Fixed worker capacity for this listener.
            adapter (BuiltinSSLAdapter | None): Verified mTLS adapter for the control listener.
        """

        def scoped(environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
            """
            Inject listener identity independently of untrusted HTTP headers.

            Args:
                environ (WSGIEnvironment): Server-owned WSGI environment.
                start_response (StartResponse): Server response callback.

            Returns:
                Iterable[bytes]: Application response iterable.
            """
            environ["broker.listener"] = scope
            return application(environ, start_response)

        super().__init__(
            address,
            scoped,
            numthreads=workers,
            max=workers,
            request_queue_size=16,
            accepted_queue_size=workers,
            accepted_queue_timeout=1,
            timeout=5,
            shutdown_timeout=70,
        )
        self.max_request_body_size = 4096
        self.max_request_header_size = 8192
        self.keep_alive_conn_limit = 16
        self.ssl_adapter = adapter
        self.prepare()

    def error_log(self, msg: str = "", level: int = 20, traceback: bool = False) -> None:
        """
        Keep peer data, exception bodies, and provider context out of transport logs.

        Args:
            msg (str): Untrusted diagnostic; discarded.
            level (int): Library logging level.
            traceback (bool): Whether the library requested exception details.

        Returns:
            None: Domain audit and bounded operational metrics remain authoritative.
        """
        return None

    def queue_size(self) -> int:
        """
        Read the maintained server's accepted-connection queue.

        Returns:
            int: Accepted connections waiting for a worker.
        """
        pool = self.requests
        if not isinstance(pool, ThreadPool):
            raise RuntimeError("Unexpected HTTP worker pool")
        return pool.qsize


class BrokerServer:
    """
    Retain one app and own control/observability listeners through graceful shutdown.
    """

    def __init__(
        self,
        address: tuple[str, int],
        broker: Broker,
        cert: Path,
        key: Path,
        client_ca: Path,
        metrics_address: tuple[str, int] | None = None,
        capacity: int = 8,
        crypto: CryptoService | None = None,
    ) -> None:
        """
        Bind verified mTLS capability routes and optional private operational routes.

        Args:
            address (tuple[str, int]): Capability listener address.
            broker (Broker): Ready domain service.
            cert (Path): Server certificate chain.
            key (Path): Server private key.
            client_ca (Path): Workload certificate authority.
            metrics_address (tuple[str, int] | None): Internal monitoring listener, when enabled.
            capacity (int): Maximum concurrent capability handlers.
            crypto (CryptoService | None): Explicit service-only key operations, disabled by default.
        """
        self.broker = broker
        self.app = APIBuilder(capacity=capacity, crypto=crypto).with_broker(broker).build()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(cert, key)
        context.load_verify_locations(client_ca)
        context.verify_mode = ssl.CERT_REQUIRED
        adapter = BuiltinSSLAdapter(str(cert), str(key))
        adapter.context = context

        # Match execution slots plus the separate recovery allowance, keeping recovery reachable under load.
        self.control = Listener(address, self.app, "control", capacity + 2, adapter)
        self.metrics: Listener | None = None
        try:
            if metrics_address is not None:
                self.metrics = Listener(metrics_address, self.app, "observability", 2)
        except OSError:
            # A failed second bind must release the first listener instead of leaving a partially constructed service.
            self.control.stop()
            raise
        self.server_port = int(self.control.bind_addr[1])
        self.metrics_port = int(self.metrics.bind_addr[1]) if self.metrics is not None else None
        broker.ledger.telemetry.observe_queue("http", self.control.queue_size)
        if self.metrics is not None:
            broker.ledger.telemetry.observe_queue("observability", self.metrics.queue_size)
        self._metrics_thread: threading.Thread | None = None
        self._closed = False

    def serve_forever(self) -> None:
        """
        Start the monitoring listener and serve authenticated requests until shutdown.

        Returns:
            None: Both listeners leave their accept loops after shutdown.
        """
        if self.metrics is not None:
            self._metrics_thread = threading.Thread(target=self.metrics.serve, name="broker-observability")
            self._metrics_thread.start()
        self.broker.ledger.telemetry.state("ready")
        self.control.serve()

    def shutdown(self) -> None:
        """
        Stop admission, drain owned handlers, and join the monitoring listener.

        Returns:
            None: Repeated shutdown is safe.
        """
        if self._closed:
            return
        self._closed = True

        # Close admission before stopping listeners; keep storage alive until their handlers finish.
        self.broker.ledger.telemetry.state("draining")
        self.control.stop()
        if self.metrics is not None:
            self.metrics.stop()
        if self._metrics_thread is not None:
            self._metrics_thread.join(timeout=10)
            if self._metrics_thread.is_alive():
                raise RuntimeError("Monitoring listener did not drain")

    def server_close(self) -> None:
        """
        Finish listener ownership after its serving thread has stopped.

        Returns:
            None: Listener shutdown is idempotent.
        """
        self.shutdown()
