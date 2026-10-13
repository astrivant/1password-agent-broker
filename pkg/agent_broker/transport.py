"""
Authenticate workloads through mutual TLS and expose a small bounded JSON protocol.
"""

from __future__ import annotations

import json
import ssl
import threading
from http.client import HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from agent_broker.api.server import BrokerServer as BrokerServer
from agent_broker.contracts import encode, structure
from agent_broker.exceptions import Rejected
from agent_broker.models import Result

if TYPE_CHECKING:
    import socket
    from pathlib import Path


class TLSServer(ThreadingHTTPServer):
    """
    Limit concurrent handlers and close idle sockets before draining worker threads.

    Attributes:
        daemon_threads (bool): Keep owned workers alive until drained.
        block_on_close (bool): Join handlers when the listener closes.
    """

    daemon_threads: bool = False
    block_on_close: bool = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], context: ssl.SSLContext) -> None:
        """
        Bind a TLS listener with bounded worker capacity.

        Args:
            address (tuple[str, int]): Bind host and port.
            handler (type[BaseHTTPRequestHandler]): Application request handler.
            context (ssl.SSLContext): Operator-configured TLS authority.
        """
        self.context = context
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        """
        Apply a handshake timeout before handing a socket to a worker.

        Returns:
            tuple[socket.socket, tuple[str, int]]: Verified TLS connection and peer address.
        """
        connection, address = self.socket.accept()
        connection.settimeout(5)
        try:
            return self.context.wrap_socket(connection, server_side=True), address
        except OSError:
            connection.close()
            raise

    def process_request(self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]) -> None:
        """
        Refuse excess work without creating an unbounded thread population.

        Args:
            request (socket.socket | tuple[bytes, socket.socket]): Accepted connection.
            client_address (tuple[str, int]): Transport peer.

        Returns:
            None: Start a bounded worker or close the connection.
        """
        if isinstance(request, tuple):
            raise TypeError("TCP transport required")
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except RuntimeError:
            self.slots.release()
            self.shutdown_request(request)

    def process_request_thread(self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]) -> None:
        """
        Return worker capacity even when request handling fails.

        Args:
            request (socket.socket | tuple[bytes, socket.socket]): Accepted connection.
            client_address (tuple[str, int]): Transport peer.

        Returns:
            None: Drain and release the worker.
        """
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]) -> None:
        """
        Suppress exception bodies at the untrusted network boundary.

        Args:
            request (socket.socket | tuple[bytes, socket.socket]): Failed connection.
            client_address (tuple[str, int]): Transport peer; never logged.

        Returns:
            None: Preserve pending ledger state for an uncertain outcome.
        """
        return None


class Client:
    """
    Project capability requests without possessing downstream or 1Password credentials.
    """

    def __init__(self, url: str, ca: Path, cert: Path, key: Path) -> None:
        """
        Configure an authenticated broker endpoint independently of model input.

        Args:
            url (str): Broker HTTPS origin only.
            ca (Path): Broker certificate authority.
            cert (Path): Workload certificate.
            key (Path): Workload private key, scoped to its permitted capabilities.

        Raises:
            Rejected: The endpoint is not an HTTPS origin.
        """
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
            raise Rejected("Invalid broker origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Rejected("Invalid broker origin")
        self.host = parsed.hostname
        self.port = parsed.port or 443
        self.context = ssl.create_default_context(cafile=ca)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.context.load_cert_chain(cert, key)

    def call(self, raw: object, *, cancel: bool = False, inspect: bool = False) -> Result:
        """
        Send once; a caller can retry the same UUID to recover a recorded result.

        Args:
            raw (object): Closed request payload.
            cancel (bool): Send to the cancellation endpoint.
            inspect (bool): Read existing state through the status endpoint.

        Returns:
            Result: Validated server result or an explicit unknown transport outcome.
        """
        connection = HTTPSConnection(self.host, self.port, context=self.context, timeout=30)
        try:
            connection.request(
                "POST",
                "/status" if inspect else "/cancel" if cancel else "/execute",
                body=encode(raw),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = response.read(4097)
            if response.status != 200 or len(payload) > 4096:
                raise Rejected("Invalid broker response")
            return structure(json.loads(payload), Result, "result")
        except (OSError, HTTPException, ValueError, Rejected):
            return Result("uncertain", "unknown")
        finally:
            connection.close()
