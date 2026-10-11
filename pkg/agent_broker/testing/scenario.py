"""
Exercise two synthetic identities against a real local HTTPS destination and broker.
"""

from __future__ import annotations

import secrets
import ssl
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

from attrs import define

from agent_broker import contracts
from agent_broker.approval import approve, write_private
from agent_broker.engine import Broker
from agent_broker.ledger import Ledger
from agent_broker.lifecycle import running
from agent_broker.models import Credential, Operation, Policy, Principal
from agent_broker.providers import HealthExecutor
from agent_broker.testing.certificates import create
from agent_broker.transport import BrokerServer, Client, TLSServer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agent_broker.models import Request


@define
class SyntheticProvider:
    """
    Keep generated canaries in broker-owned memory, without touching 1Password.

    Attributes:
        secrets (dict[str, str]): Generated synthetic canaries, held only by the test broker.
        calls (list[str]): Credential references resolved during the test.
    """

    secrets: dict[str, str]
    calls: list[str]

    def resolve(self, credential: Credential) -> str:
        """
        Return a synthetic token and count resolution attempts.

        Args:
            credential (Credential): Policy-selected synthetic reference.

        Returns:
            str: Generated test canary.
        """
        self.calls.append(credential.reference)
        return self.secrets[credential.reference]


@define
class Scenario:
    """
    Expose owned fixture resources for deterministic, local regressions.

    Attributes:
        root (Path): Private temporary fixture directory.
        fingerprints (dict[str, str]): Synthetic certificate hashes by workload.
        provider (SyntheticProvider): Synthetic credential resolver.
        broker (Broker): Execution engine under test.
        clients (dict[str, Client]): Independent certificate-authenticated clients.
        url (str): Ephemeral local broker origin.
        destination_calls (list[str]): Paths observed by the synthetic service.
    """

    root: Path
    fingerprints: dict[str, str]
    provider: SyntheticProvider
    broker: Broker
    clients: dict[str, Client]
    url: str
    destination_calls: list[str]

    def request(self, principal: str = "alpha", operation: str | None = None) -> Request:
        """
        Create a real operator approval for one synthetic workload.

        Args:
            principal (str): Synthetic identity name.
            operation (str | None): Capability override or the identity's own health check.

        Returns:
            Request: Approved request bound to current policy.
        """
        return approve(self.root / "policy.json", self.root / "approvals.json", principal, operation or f"{principal}-health", 300)


@contextmanager
def scenario(root: Path) -> Iterator[Scenario]:
    """
    Construct an isolated, no-provider-call end-to-end environment.

    Args:
        root (Path): Empty, caller-owned temporary directory.

    Yields:
        Scenario: Two certificate-authenticated clients and a bounded credential broker.
    """
    fingerprints = create(root)
    tokens = {f"op://synthetic/{name}/token": secrets.token_hex(24) for name in ("alpha", "bravo")}
    provider = SyntheticProvider(tokens, [])
    destination_calls: list[str] = []

    class Destination(BaseHTTPRequestHandler):
        """
        Validate synthetic authentication without returning any secret content.
        """

        def log_message(self, format: str, *args: object) -> None:
            """
            Suppress request logging in the synthetic service.

            Args:
                format (str): Standard-library template.
                *args (object): Ignored request values.

            Returns:
                None: Keep canaries out of diagnostic output.
            """
            return None

        def do_GET(self) -> None:
            """
            Count requests and validate the endpoint's expected token.

            Returns:
                None: Write only an HTTP status.
            """
            destination_calls.append(self.path)
            expected = tokens.get(f"op://synthetic/{self.path.strip('/')}/token", "invalid")
            self.send_response(204 if self.headers.get("Authorization") == f"Bearer {expected}" else 403)
            self.send_header("Content-Length", "0")
            self.end_headers()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / "server.pem", root / "server.key")
    destination = TLSServer(("127.0.0.1", 0), Destination, context)

    with running(destination):
        policy = Policy(
            {name: Principal(fingerprints[name], name, "reviewed-v1", "demo-run", (f"{name}-health",)) for name in ("alpha", "bravo")},
            {name: Credential(f"op://synthetic/{name}/token", "SYNTHETIC_UNUSED") for name in ("alpha", "bravo")},
            {f"{name}-health": Operation(name, f"https://127.0.0.1:{destination.server_port}/{name}") for name in ("alpha", "bravo")},
        )
        write_private(root / "policy.json", contracts.data(policy))
        write_private(root / "approvals.json", {})
        broker = Broker(root / "policy.json", root / "approvals.json", Ledger(root / "audit.db"), provider, HealthExecutor(root / "ca.pem"))
        server = BrokerServer(("127.0.0.1", 0), broker, root / "server.pem", root / "server.key", root / "ca.pem")
        url = f"https://127.0.0.1:{server.server_port}"
        clients = {name: Client(url, root / "ca.pem", root / f"{name}.pem", root / f"{name}.key") for name in ("alpha", "bravo")}

        with running(server):
            yield Scenario(root, fingerprints, provider, broker, clients, url, destination_calls)
