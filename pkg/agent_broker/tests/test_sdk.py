"""
Verify the official SDK call path and worker boundary without accessing a 1Password account.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from importlib.metadata import version
from typing import TYPE_CHECKING

import pytest
from agent_broker import contracts, sdk_worker
from agent_broker.exceptions import ProviderFailure
from agent_broker.models import Credential
from agent_broker.providers import OnePasswordProvider
from onepassword.core import UniffiCore
from onepassword.secrets import Secrets

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.mark.parametrize("failure", ["none", "authenticate", "resolve", "empty", "whitespace", "control", "unicode", "oversized"])
def test_sdk_worker_contract(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """
    Exercise real SDK authentication and resolution adapters against a synthetic core.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped native-boundary and pipe replacements.
        failure (str): Failure boundary or invalid credential shape to exercise.

    Returns:
        None: Assert exact account/reference use and diagnostic redaction.
    """
    token, reference, canary = "synthetic-service-token", "op://synthetic/item/token", "synthetic-sensitive-diagnostic"
    configs: list[dict[str, object]] = []
    invocations: list[dict[str, object]] = []
    values = {"empty": "", "whitespace": "has space", "control": "has\x00control", "unicode": "caf\u00e9", "oversized": "x" * 16385}

    async def initialize(self: UniffiCore, client_config: dict[str, object]) -> str:
        """
        Capture the SDK's explicit service-account configuration without network access.

        Args:
            self (UniffiCore): Real SDK core adapter.
            client_config (dict[str, object]): SDK-generated configuration.

        Returns:
            str: Synthetic native client identifier.
        """
        configs.append(client_config)
        if failure == "authenticate":
            raise Exception(canary)
        return "1"

    async def invoke(self: UniffiCore, invoke_config: dict[str, object]) -> str:
        """
        Return one synthetic native response for the SDK's JSON conversion.

        Args:
            self (UniffiCore): Real SDK core adapter.
            invoke_config (dict[str, object]): SDK-generated field-resolution invocation.

        Returns:
            str: Encoded value accepted by the actual SDK response parser.
        """
        invocations.append(invoke_config)
        if failure == "resolve":
            raise Exception(canary)
        return json.dumps(values.get(failure, "synthetic-field-value"))

    def release(self: UniffiCore, client_id: int) -> None:
        """
        Keep synthetic IDs out of the actual native session finalizer.

        Args:
            self (UniffiCore): Real SDK core adapter.
            client_id (int): Synthetic client identifier.

        Returns:
            None: No real native session was created.
        """
        return None

    monkeypatch.setattr(UniffiCore, "init_client", initialize)
    monkeypatch.setattr(UniffiCore, "invoke", invoke)
    monkeypatch.setattr(UniffiCore, "release_client", release)
    output, errors = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(contracts.encode({"token": token, "reference": reference}))))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    assert sdk_worker.main() == (0 if failure == "none" else 2)
    assert output.getvalue() == ("synthetic-field-value" if failure == "none" else "")
    assert errors.getvalue() == ""
    assert token not in output.getvalue() + errors.getvalue()
    assert canary not in output.getvalue() + errors.getvalue()
    assert configs[0]["serviceAccountToken"] == token
    assert configs[0]["integrationName"] == "1password-agent-broker"
    assert configs[0]["integrationVersion"] == version("1password-agent-broker")
    if failure != "authenticate":
        assert invocations == [
            {"invocation": {"clientId": 1, "parameters": {"name": "SecretsResolve", "parameters": {"secret_reference": reference}}}}
        ]


@pytest.mark.parametrize("payload", [b"{}", b"not-json", b"[]", b'{"token":false,"reference":"op://synthetic/item/token"}'])
def test_real_worker_rejects_malformed_input(payload: bytes) -> None:
    """
    Launch the installed worker without usable authority and reject malformed private input.

    Args:
        payload (bytes): Invalid worker envelope.

    Returns:
        None: Assert the isolated process returns no stdout or diagnostics.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-m", "agent_broker.sdk_worker"], input=payload, capture_output=True, timeout=10, check=False
    )
    assert result.returncode == 2
    assert result.stdout == result.stderr == b""


def test_sdk_native_reference_validation() -> None:
    """
    Load the actual platform library and exercise a documented, offline SDK operation.

    Returns:
        None: Assert native loading and reference validation succeed without credentials.
    """
    Secrets.validate_secret_reference("op://synthetic/item/token")


def test_provider_scopes_and_rotates_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Re-read selected bootstrap tokens and keep them off argv and inherited environments.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped environment and worker replacement.

    Returns:
        None: Assert every resolution uses only the current selected service account.
    """
    observed: list[object] = []
    values: Iterator[str] = iter(["first-secret", "rotated-secret", "second-account-secret"])

    def worker(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """
        Inspect the broker-owned pipes instead of resolving a real credential.

        Args:
            *args (object): Fixed interpreter command.
            **kwargs (object): Private input and platform-only environment.

        Returns:
            subprocess.CompletedProcess[bytes]: Synthetic successful worker output.
        """
        assert args == ([sys.executable, "-I", "-m", "agent_broker.sdk_worker"],)
        assert kwargs["timeout"] == 10
        assert "synthetic-bootstrap" not in str(args) + str(kwargs["env"])
        payload = kwargs["input"]
        assert isinstance(payload, bytes)
        observed.append(json.loads(payload))
        return subprocess.CompletedProcess([], 0, next(values).encode(), b"")

    monkeypatch.setattr(subprocess, "run", worker)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-bootstrap-first")
    monkeypatch.setenv("SECOND_ACCOUNT_TOKEN", "synthetic-bootstrap-second")
    provider = OnePasswordProvider()
    credential = Credential("op://synthetic/item/token")
    assert provider.resolve(credential) == "first-secret"
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-bootstrap-rotated")
    assert provider.resolve(credential) == "rotated-secret"
    assert provider.resolve(Credential(credential.reference, "SECOND_ACCOUNT_TOKEN")) == "second-account-secret"
    assert observed == [
        {"token": token, "reference": credential.reference}
        for token in ("synthetic-bootstrap-first", "synthetic-bootstrap-rotated", "synthetic-bootstrap-second")
    ]


def test_provider_timeout_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep subprocess timeout diagnostics and captured secret output out of broker failures.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped worker timeout replacement.

    Returns:
        None: Assert timeout diagnostics are replaced by a fixed provider failure.
    """

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """
        Model the standard library killing and reaping a timed-out SDK process.

        Args:
            *args (object): Worker command.
            **kwargs (object): Worker timeout and pipes.

        Returns:
            subprocess.CompletedProcess[bytes]: Never returned for this timeout fixture.
        """
        assert kwargs["timeout"] == 10
        raise subprocess.TimeoutExpired("synthetic-secret-diagnostic", 10, output=b"synthetic-secret-output")

    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "synthetic-bootstrap")
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ProviderFailure, match="^Credential provider unavailable$"):
        OnePasswordProvider().resolve(Credential("op://synthetic/item/token"))
