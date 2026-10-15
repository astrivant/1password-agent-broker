"""
Exercise the maintained service SDK across real mutual TLS and listener boundaries.
"""

from __future__ import annotations

import base64
import hashlib
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agent_broker import contracts
from agent_broker.api.builder import APIBuilder
from agent_broker.api.server import BrokerServer
from agent_broker.approval import write_private
from agent_broker.crypto.models import Response
from agent_broker.crypto.service import CryptoService
from agent_broker.lifecycle import running
from agent_broker.testing.scenario import scenario
from agent_broker_sdk.client import CryptoClient
from agent_broker_sdk.exceptions import BrokerError
from attrs import evolve

if TYPE_CHECKING:
    from pathlib import Path

    from tests.crypto.conftest import Fixture


def test_real_mtls_sdk(fixture: Fixture, tmp_path: Path) -> None:
    """
    Authenticate the real SDK through TLS and reject a separately issued client certificate.

    Args:
        fixture (Fixture): Synthetic key custody and independently scoped grant.
        tmp_path (Path): Disposable network test environment.

    Returns:
        None: Wrapping and unwrapping succeed only for the enrolled certificate.
    """
    root = tmp_path / "transport"
    root.mkdir()
    with scenario(root) as application:
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((root / "alpha.pem").read_text())).hexdigest()
        grant = evolve(fixture.policy.grants[fixture.request.grant], certificate_sha256=fingerprint)
        write_private(fixture.service.policy, contracts.data(evolve(fixture.policy, grants={fixture.request.grant: grant})))
        service = CryptoService(fixture.service.policy, fixture.provider, application.broker.ledger, fixture.service.clock)
        server = BrokerServer(
            ("127.0.0.1", 0), application.broker, root / "server.pem", root / "server.key", root / "ca.pem", crypto=service
        )
        with running(server):
            origin = f"https://localhost:{server.server_port}"
            client = CryptoClient(origin, root / "ca.pem", root / "alpha.pem", root / "alpha.key")
            wrapped = client.invoke(fixture.request)
            request = evolve(fixture.request, request_id=str(uuid4()), action="unwrap", payload=base64.b64encode(wrapped).decode())
            assert client.invoke(request) == b"d" * 32
            denied = CryptoClient(origin, root / "ca.pem", root / "bravo.pem", root / "bravo.key")
            with pytest.raises(BrokerError, match="^Broker operation unavailable$"):
                denied.invoke(fixture.request)


def test_service_route_is_opt_in_and_control_only(fixture: Fixture, tmp_path: Path) -> None:
    """
    Keep key operations absent by default and inaccessible through monitoring or claimed identity headers.

    Args:
        fixture (Fixture): Synthetic key service.
        tmp_path (Path): Disposable broker environment.

    Returns:
        None: Untrusted routing and client identity claims never cause a key lookup.
    """
    root = tmp_path / "application"
    root.mkdir()
    with scenario(root) as application:
        default = APIBuilder(broker=application.broker).build()
        assert "crypto" not in default.blueprints
        app = APIBuilder(broker=application.broker, crypto=fixture.service).build()
        client = app.test_client()
        payload = contracts.data(fixture.request)
        assert (
            client.post("/crypto", json=payload, environ_overrides={"broker.listener": "observability"}).status_code == HTTPStatus.NOT_FOUND
        )
        result = client.post(
            "/crypto", json=payload, headers={"SSL-Client-Verify": "SUCCESS"}, environ_overrides={"broker.listener": "control"}
        )
        assert result.json == {"code": "denied", "payload": ""}
        assert result.headers["Cache-Control"] == "no-store"
        assert not fixture.provider.calls


def test_crypto_shares_execution_admission(fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Preserve recovery admission when the key service consumes the process execution budget.

    Args:
        fixture (Fixture): Synthetic cryptographic service.
        tmp_path (Path): Disposable listener configuration.
        monkeypatch (pytest.MonkeyPatch): Event-controlled domain handler replacement.

    Returns:
        None: Cryptography and execution share capacity while status remains reachable.
    """
    entered, release = threading.Event(), threading.Event()

    def blocked(fingerprint: str, raw: object) -> Response:
        """
        Hold a domain request at a deterministic coordination boundary.

        Args:
            fingerprint (str): Transport-verified peer, unused for this admission test.
            raw (object): Untrusted request, unused by the replacement.

        Returns:
            Response: Fixed denial after the test releases its worker.
        """
        entered.set()
        assert release.wait(10)
        return Response("denied")

    monkeypatch.setattr(fixture.service, "handle", blocked)
    root = tmp_path / "admission"
    root.mkdir()
    with scenario(root) as application:
        client = APIBuilder(broker=application.broker, crypto=fixture.service, capacity=1).build().test_client()
        scope = {"broker.listener": "control", "SSL_CLIENT_VERIFY": "SUCCESS", "SSL_CLIENT_CERT": (root / "alpha.pem").read_text()}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, "/crypto", json=contracts.data(fixture.request), environ_overrides=scope)
            try:
                assert entered.wait(10)
                assert (
                    client.post("/execute", json=contracts.data(application.request()), environ_overrides=scope).status_code
                    == HTTPStatus.SERVICE_UNAVAILABLE
                )
                assert (
                    client.post("/status", json=contracts.data(application.request()), environ_overrides=scope).status_code == HTTPStatus.OK
                )
            finally:
                release.set()
            assert pending.result(timeout=10).status_code == HTTPStatus.OK
