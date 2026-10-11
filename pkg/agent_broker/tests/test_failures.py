"""
Exercise deterministic cancellation races and safe failures at credential and audit boundaries.
"""

from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from agent_broker import contracts
from agent_broker.exceptions import AuditFailure, DestinationFailure, ProviderFailure
from agent_broker.providers import OnePasswordProvider

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from agent_broker.models import Credential, Operation
    from agent_broker.testing.scenario import Scenario


def test_cancel_during_resolution(fixture: Scenario) -> None:
    """
    Coordinate cancellation without sleep-dependent timing or another network submission.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert cancellation after provider latency still blocks the operation.
    """
    entered, release = threading.Event(), threading.Event()
    original = fixture.broker.provider

    class BlockingProvider:
        """
        Hold credential resolution at a deterministic cancellation boundary.
        """

        def resolve(self, credential: Credential) -> str:
            """
            Notify the test and await explicit release.

            Args:
                credential (Credential): Exact synthetic credential.

            Returns:
                str: Original synthetic credential after release.
            """
            entered.set()
            if not release.wait(5):
                raise ProviderFailure("Synthetic coordination timed out")
            return original.resolve(credential)

    fixture.broker.provider = BlockingProvider()
    request = contracts.data(fixture.request())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(fixture.clients["alpha"].call, request)
        try:
            assert entered.wait(5)
            assert fixture.clients["alpha"].call(request, cancel=True).state == "cancelled"
        finally:
            release.set()
        assert pending.result(timeout=5).state == "cancelled"
    assert not fixture.destination_calls


def test_destination_timeout_not_resubmitted(fixture: Scenario) -> None:
    """
    Preserve ambiguity after submission instead of silently repeating an operation.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert a repeated request returns the durable unknown result.
    """
    attempts: list[str] = []

    class UncertainExecutor:
        """
        Simulate a destination which received work but lost its response.
        """

        def execute(self, operation: Operation, secret: str) -> int:
            """
            Record one attempted request and fail without forwarding diagnostic content.

            Args:
                operation (Operation): Synthetic capability.
                secret (str): Credential included in an internal synthetic error.

            Returns:
                int: Never returned for this failure fixture.
            """
            attempts.append(operation.kind)
            raise DestinationFailure(secret)

    fixture.broker.executor = UncertainExecutor()
    payload = contracts.data(fixture.request())
    result = fixture.clients["alpha"].call(payload)
    replay = fixture.clients["alpha"].call(payload)
    assert result.state == replay.state == "uncertain"
    assert replay.replayed and attempts == ["health"]
    assert not any(secret in str(result) for secret in fixture.provider.secrets.values())


def test_audit_export_failure_keeps_durable_result(fixture: Scenario) -> None:
    """
    Distinguish a failed log sink from a failed operation.

    Args:
        fixture (Scenario): Synthetic environment.

    Returns:
        None: Assert export failure is visible without causing resubmission.
    """

    def unavailable(event: dict[str, object]) -> None:
        """
        Simulate a disconnected stdout collector.

        Args:
            event (dict[str, object]): Secret-free audit event.

        Returns:
            None: Never returned by this fixture.
        """
        raise OSError("Synthetic collector unavailable")

    fixture.broker.ledger.exporter = unavailable
    payload = contracts.data(fixture.request())
    result = fixture.clients["alpha"].call(payload)
    assert result.code == "healthy" and result.audit_warning
    assert fixture.clients["alpha"].call(payload).replayed
    assert len(fixture.destination_calls) == 1


def test_audit_storage_failure_prevents_secret_access(fixture: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fail closed before resolving credentials when durable intent cannot be recorded.

    Args:
        fixture (Scenario): Synthetic environment.
        monkeypatch (pytest.MonkeyPatch): Scoped dependency replacement.

    Returns:
        None: Assert no credential or remote access takes place.
    """

    def unavailable(name: str, attributes: dict[str, object]) -> bool:
        """
        Model a full or unavailable audit volume.

        Args:
            name (str): Event name.
            attributes (dict[str, object]): Event attributes.

        Returns:
            bool: Never returned by this fixture.
        """
        raise AuditFailure("Synthetic disk failure")

    monkeypatch.setattr(fixture.broker.ledger, "event", unavailable)
    assert fixture.clients["alpha"].call(contracts.data(fixture.request())).code == "audit_failed"
    assert fixture.provider.calls == fixture.destination_calls == []


def test_provider_error_redaction(fixture: Scenario, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Keep CLI stdout, stderr, bootstrap values, and exception bodies out of returned status.

    Args:
        fixture (Scenario): Synthetic environment.
        monkeypatch (pytest.MonkeyPatch): Scoped process replacement.
        tmp_path (Path): Temporary trusted executable path.

    Returns:
        None: Assert safe failure and no secret-bearing command arguments.
    """
    executable = tmp_path / "op-synthetic"
    executable.touch()
    observed: list[object] = []
    canary = "synthetic-provider-error-canary"

    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """
        Return secret-bearing provider diagnostics to the trusted adapter only.

        Args:
            *args (object): Invocation arguments to inspect.
            **kwargs (object): Subprocess environment and pipe configuration.

        Returns:
            subprocess.CompletedProcess[bytes]: Synthetic failed CLI response.
        """
        observed.extend(args)
        assert kwargs["capture_output"] is True and kwargs["check"] is False
        return subprocess.CompletedProcess([], 1, canary.encode(), canary.encode())

    monkeypatch.setenv("SYNTHETIC_UNUSED", canary)
    monkeypatch.setattr(subprocess, "run", failed)
    fixture.broker.provider = OnePasswordProvider(executable)
    result = fixture.clients["alpha"].call(contracts.data(fixture.request()))
    assert result.code == "provider_failed" and canary not in str(result)
    assert canary not in str(observed)
    assert canary.encode() not in (fixture.root / "audit.db").read_bytes()
    assert not fixture.destination_calls
