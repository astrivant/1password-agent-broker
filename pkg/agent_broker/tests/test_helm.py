"""
Check deployment invariants across supported HA and observability configurations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from agent_broker import contracts
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import ValidationError, validate

CHART = Path(__file__).resolve().parents[3] / "helm/1password-agent-broker"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None or not CHART.exists(), reason="Helm source checks run in the chart CI job")


@settings(max_examples=12, deadline=None, derandomize=True)
@given(replicas=st.integers(2, 16), capacity=st.integers(1, 64), network=st.booleans(), destination=st.booleans(), crypto=st.booleans())
def test_ha_contract(replicas: int, capacity: int, network: bool, destination: bool, crypto: bool) -> None:
    """
    Keep security, durability, and operational contracts intact across supported scale settings.

    Args:
        replicas (int): Desired HA replica count.
        capacity (int): Per-process execution capacity.
        network (bool): Whether the operator delegates ingress filtering to this chart.
        destination (bool): Whether the destination uses a private trust anchor.
        crypto (bool): Whether to explicitly enable the service-only key boundary.

    Returns:
        None: Assert rendered objects retain the intended cross-resource relationships.
    """
    completed = subprocess.run(
        [
            "helm",
            "template",
            "test",
            str(CHART),
            "--set",
            f"replicaCount={replicas},capacity={capacity}",
            "--set",
            f"networkPolicy.enabled={str(network).lower()},crypto.enabled={str(crypto).lower()}",
            "--set-string",
            f"secrets.destinationCA={'destination-ca' if destination else ''}",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    resources = {item["kind"]: item for item in yaml.safe_load_all(completed.stdout)}
    deployment = resources["Deployment"]["spec"]
    pod = deployment["template"]["spec"]
    container = pod["containers"][0]
    assert deployment["replicas"] == replicas
    assert deployment["strategy"]["rollingUpdate"] == {"maxSurge": 1, "maxUnavailable": 0}
    assert pod["topologySpreadConstraints"][0]["minDomains"] == 2
    assert pod["automountServiceAccountToken"] is False
    assert "--storage=postgresql" in container["args"]
    assert f"--capacity={capacity}" in container["args"]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["readinessProbe"]["httpGet"] == {"path": "/readyz", "port": "metrics"}
    assert not any("subPath" in mount for mount in container["volumeMounts"])
    assert any(mount["name"] == "destination" for mount in container["volumeMounts"]) == destination
    assert ("NetworkPolicy" in resources) == network
    assert "Secret" not in resources and "PersistentVolumeClaim" not in resources
    config = resources["ConfigMap"]["data"]
    assert ("--crypto-policy=/etc/broker/config/crypto.json" in container["args"]) == crypto
    assert ("crypto.json" in config) == crypto
    if crypto:
        validate(json.loads(config["crypto.json"]), contracts.schema("crypto-policy"))
    validate(json.loads(config["policy.json"]), contracts.schema("policy"))
    validate(json.loads(config["approvals.json"]), contracts.schema("approvals"))


@pytest.mark.parametrize("override", [{"replicaCount": 1}, {"capacity": 65}, {"configuration": {"policy": {"token": "canary"}}}])
def test_values_reject_unsafe_input(override: dict[str, object]) -> None:
    """
    Reject configuration outside HA and authorization schema boundaries.

    Args:
        override (dict[str, object]): Invalid root-level replacement.

    Returns:
        None: Assert a schema error instead of silently ignoring operator intent.
    """
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    values.update(override)
    with pytest.raises(ValidationError):
        validate(values, json.loads((CHART / "values.schema.json").read_text()))
