"""
Keep credential resolution and authenticated destination I/O outside the agent process.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
from http.client import HTTPException, HTTPSConnection
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from agent_broker.contracts import encode
from agent_broker.exceptions import DestinationFailure, ProviderFailure

if TYPE_CHECKING:
    from pathlib import Path

    from agent_broker.models import Credential, Operation


class Provider(Protocol):
    """
    Resolve one operator-selected reference inside the trusted broker boundary.
    """

    def resolve(self, credential: Credential) -> str:
        """
        Return a credential without exporting provider diagnostics.

        Args:
            credential (Credential): Operator-owned exact reference and bootstrap selector.

        Returns:
            str: Secret used only for this operation.
        """
        ...


class Executor(Protocol):
    """
    Implement a named, bounded capability without returning arbitrary remote content.
    """

    def execute(self, operation: Operation, secret: str) -> int:
        """
        Submit one fixed operation; unknown outcomes must not be retried implicitly.

        Args:
            operation (Operation): Trusted destination and capability definition.
            secret (str): Broker-local credential.

        Returns:
            int: HTTP response status only.
        """
        ...


class OnePasswordProvider:
    """
    Resolve fields with the official SDK in a bounded, broker-owned worker process.
    """

    def resolve(self, credential: Credential) -> str:
        """
        Pass one explicit service account and field to the SDK through a private input pipe.

        Args:
            credential (Credential): Policy-selected field reference.

        Returns:
            str: Nonempty, bounded single-line credential.

        Raises:
            ProviderFailure: Bootstrap, SDK execution, timeout, or credential shape is invalid.
        """
        token = os.environ.get(credential.bootstrap_env)
        if not token or len(token) > 65536:
            raise ProviderFailure("Credential provider unavailable")
        environment = {}

        # The worker receives one token on stdin, never ambient provider or desktop-session credentials.
        for name in ("PATH", "HOME", "SYSTEMROOT", "TMPDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-m", "agent_broker.sdk_worker"],
                input=encode({"token": token, "reference": credential.reference}),
                env=environment,
                capture_output=True,
                timeout=10,
                check=False,
            )
            secret = completed.stdout.decode("utf-8")
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ProviderFailure("Credential provider unavailable") from None
        if completed.returncode != 0 or not valid_secret(secret):
            raise ProviderFailure("Credential provider unavailable")
        return secret


def valid_secret(secret: str) -> bool:
    """
    Accept only bounded visible ASCII credentials suitable for an HTTP bearer header.

    Args:
        secret (str): Resolved credential kept within the broker boundary.

    Returns:
        bool: Whether the value can be passed to the fixed health executor.
    """
    return 0 < len(secret) <= 16384 and all(33 <= ord(character) <= 126 for character in secret)


class HealthExecutor:
    """
    Perform one fixed HTTPS GET without redirects, ambient proxies, or response bodies.
    """

    def __init__(self, ca: Path | None = None) -> None:
        """
        Use public roots or an explicit operator-owned destination CA.

        Args:
            ca (Path | None): Optional private service CA.
        """
        self.context = ssl.create_default_context(cafile=ca)

    def execute(self, operation: Operation, secret: str) -> int:
        """
        Send the credential only to the policy's authenticated destination.

        Args:
            operation (Operation): Fixed HTTPS health endpoint.
            secret (str): Bearer token retained only during execution.

        Returns:
            int: Remote HTTP status, without headers or body.

        Raises:
            DestinationFailure: Transport failed and the remote outcome may be unknown.
        """
        url = urlsplit(operation.url)
        connection = HTTPSConnection(url.hostname or "", url.port or 443, timeout=5, context=self.context)
        try:
            connection.request("GET", url.path or "/", headers={"Authorization": f"Bearer {secret}"})
            return connection.getresponse().status
        except (OSError, HTTPException, ValueError):
            raise DestinationFailure("Destination outcome unknown") from None
        finally:
            connection.close()
