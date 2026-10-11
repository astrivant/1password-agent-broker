"""
Keep credential resolution and authenticated destination I/O outside the agent process.
"""

from __future__ import annotations

import os
import ssl
import subprocess
from http.client import HTTPException, HTTPSConnection
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

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
    Read exact fields through the official CLI using a broker-only service account.
    """

    def __init__(self, executable: Path) -> None:
        """
        Select an operator-installed executable, never a client-controlled command.

        Args:
            executable (Path): Absolute path to the trusted op executable.
        """
        if not executable.is_absolute() or not executable.is_file():
            raise ProviderFailure("1Password CLI unavailable")
        self.executable = executable

    def resolve(self, credential: Credential) -> str:
        """
        Resolve a field without shell expansion, secret arguments, or diagnostic forwarding.

        Args:
            credential (Credential): Policy-selected field reference.

        Returns:
            str: Nonempty, bounded single-line credential.

        Raises:
            ProviderFailure: Bootstrap, CLI execution, or credential shape is invalid.
        """
        token = os.environ.get(credential.bootstrap_env)
        if not token:
            raise ProviderFailure("Credential provider unavailable")
        environment = {"OP_SERVICE_ACCOUNT_TOKEN": token, "OP_BIOMETRIC_UNLOCK_ENABLED": "false"}

        # Preserve only platform support variables, excluding agent and alternate account credentials.
        for name in ("PATH", "HOME", "SYSTEMROOT", "TMPDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        try:
            completed = subprocess.run(
                [str(self.executable), "read", credential.reference, "--no-newline"],
                env=environment,
                capture_output=True,
                timeout=10,
                check=False,
            )
            secret = completed.stdout.decode("utf-8")
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ProviderFailure("Credential provider unavailable") from None
        if completed.returncode != 0 or not secret or len(secret) > 16384 or any(character.isspace() for character in secret):
            raise ProviderFailure("Credential provider unavailable")
        return secret


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
