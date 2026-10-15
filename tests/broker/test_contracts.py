"""
Check configuration invariants and ensure CI reports cannot publish raw secret matches.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from agent_broker import contracts
from agent_broker.approval import write_private
from agent_broker.exceptions import Rejected
from agent_broker.models import Credential
from attrs import evolve

if TYPE_CHECKING:
    from agent_broker.testing.scenario import Scenario


def test_native_bootstrap_default(fixture: Scenario) -> None:
    """
    Accept existing explicit selectors and default omitted selectors to the native variable.

    Args:
        fixture (Scenario): Synthetic policy environment.

    Returns:
        None: Assert policy loading preserves both supported configuration forms.
    """
    path = fixture.root / "policy.json"
    raw = json.loads(path.read_text())
    del raw["credentials"]["alpha"]["bootstrap_env"]
    del raw["principals"]["alpha"]["task_id"]
    write_private(path, raw)
    policy, _ = contracts.policy(path)
    assert policy.credentials["alpha"] == Credential("op://synthetic/alpha/token")
    assert policy.credentials["bravo"].bootstrap_env == "SYNTHETIC_UNUSED"
    assert policy.principals["alpha"].task_id is None


def test_noncanonical_request_is_rejected() -> None:
    """
    Convert UUID parsing errors into the same safe contract denial as schema errors.

    Returns:
        None: Assert a trailing newline cannot escape the request-validation boundary.
    """
    with pytest.raises(Rejected):
        contracts.request({"request_id": "00000000-0000-0000-0000-000000000000\n", "operation": "health", "approval_id": "approval"})


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/?token=value",
        "https://example.test/#fragment",
        "https://example.test:invalid/",
        "https://example.test:65536/",
        "https://example.test:0/",
        "https://[invalid/",
        "https://example.test/?",
        "https://example.test/#",
        "https://@example.test/",
        "https://example.test/\u00e9",
        "https://example.test/\u007f",
    ],
)
def test_policy_rejects_unsafe_destinations(fixture: Scenario, url: str) -> None:
    """
    Reject destinations that could move secrets outside the fixed HTTPS boundary.

    Args:
        fixture (Scenario): Synthetic policy environment.
        url (str): Forbidden destination form.

    Returns:
        None: Assert configuration validation rejects the destination.
    """
    policy, _ = contracts.policy(fixture.root / "policy.json")
    policy.operations["alpha-health"] = evolve(policy.operations["alpha-health"], url=url)
    write_private(fixture.root / "policy.json", contracts.data(policy))
    with pytest.raises(Rejected):
        contracts.policy(fixture.root / "policy.json")


def test_ci_report_drops_matches(tmp_path: Path) -> None:
    """
    Exercise the actual redaction command rather than trusting scan output formatting.

    Args:
        tmp_path (Path): Temporary scanner output location.

    Returns:
        None: Assert only safe counts and advisory identifiers survive publication.
    """
    canary = "synthetic-secret-match-must-not-escape"
    source, output = tmp_path / "raw.json", tmp_path / "public.json"
    source.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "Results": [
                    {
                        "Target": canary,
                        "Secrets": [{"Match": canary, "Code": {"Lines": [canary]}}],
                        "Vulnerabilities": [{"Severity": "HIGH", "VulnerabilityID": "CVE-2026-12345", "Description": canary}],
                    }
                ],
            }
        )
    )
    script = Path(__file__).resolve().parents[2] / "scripts/ci/checks/trivy_report.py"
    result = subprocess.run([sys.executable, str(script), str(source), str(output)], capture_output=True, check=False)
    assert result.returncode == 1
    public = output.read_text()
    assert json.loads(public) == {"secret_findings": 1, "high_critical_vulnerabilities": 1, "advisories": ["CVE-2026-12345"]}
    assert canary not in public and canary.encode() not in result.stdout + result.stderr
