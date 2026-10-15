"""
Combine Bitnami's generated value structure with broker-owned semantic contracts.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml
from agent_broker.contracts import schema
from jsonschema import Draft7Validator


def mapping(value: object) -> dict[str, object]:
    """
    Require a string-keyed JSON object at a schema boundary.

    Args:
        value (object): Decoded schema node.

    Returns:
        dict[str, object]: Typed node preserving its values.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected schema object")
    return {str(key): item for key, item in value.items()}


def close(node: dict[str, object]) -> dict[str, object]:
    """
    Close generated fixed-key objects so spelling mistakes cannot silently change deployment intent.

    Args:
        node (dict[str, object]): Generated structural schema.

    Returns:
        dict[str, object]: Closed structure with all documented defaults required after Helm merge.
    """
    result = dict(node)

    # Close only fixed-key structures; caller-supplied maps keep their source schema semantics.
    if "properties" in result:
        properties = mapping(result["properties"])
        result.update(
            additionalProperties=False,
            required=sorted(properties),
            properties={key: close(mapping(value)) for key, value in properties.items()},
        )
    return result


def main() -> None:
    """
    Generate the self-contained Helm schema from authoritative source inputs.

    Returns:
        None: Write deterministic schema output after validating its dialect.
    """
    metadata = yaml.safe_load(Path("helm/1password-agent-broker/Chart.yaml").read_text())
    defaults = yaml.safe_load(Path("helm/1password-agent-broker/values.yaml").read_text())
    project = tomllib.loads(Path("pkg/python/broker/pyproject.toml").read_text())["project"]

    # Fail generation on mismatched release identities before writing a schema for the wrong image or chart.
    if not metadata["version"] == metadata["appVersion"] == defaults["image"]["tag"] == project["version"]:
        raise ValueError("Package, chart, appVersion, and default image tag must agree")
    generated = close(mapping(json.loads(Path(".cache/helm/values.schema.json").read_text())))
    generated["$schema"] = "http://json-schema.org/draft-07/schema#"
    properties = mapping(generated["properties"])
    properties["replicaCount"] = {**mapping(properties["replicaCount"]), "type": "integer", "minimum": 2, "maximum": 16}
    properties["capacity"] = {**mapping(properties["capacity"]), "type": "integer", "minimum": 1, "maximum": 64}
    image = mapping(properties["image"])
    image_properties = mapping(image["properties"])
    image_properties["repository"] = {"type": "string", "pattern": r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]+$"}
    image_properties["tag"] = {"type": "string", "pattern": r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$"}
    image_properties["digest"] = {"type": "string", "pattern": r"^$|^sha256:[a-f0-9]{64}$"}
    image_properties["pullPolicy"] = {"enum": ["Always", "IfNotPresent", "Never"]}
    image["properties"] = image_properties
    properties["image"] = image
    secret = {"type": "string", "maxLength": 63, "pattern": r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"}
    secrets = mapping(properties["secrets"])
    secrets["properties"] = {
        "tls": secret,
        "provider": secret,
        "postgresql": secret,
        "destinationCA": {"anyOf": [secret, {"const": ""}]},
    }
    properties["secrets"] = secrets
    network = mapping(properties["networkPolicy"])
    network["properties"] = {"enabled": {"type": "boolean"}, "clientNamespace": secret, "monitoringNamespace": secret}
    properties["networkPolicy"] = network
    # Limit resource quantities to a portable documented subset of Kubernetes quantity syntax.
    resources = mapping(properties["resources"])
    budgets = mapping(resources["properties"])
    for responsibility in ("requests", "limits"):
        budget = mapping(budgets[responsibility])
        quantities = mapping(budget["properties"])
        for name, pattern in {
            "cpu": r"^[1-9][0-9]*(m)?$|^[0-9]+\.[0-9]+$",
            "memory": r"^[1-9][0-9]*(Ki|Mi|Gi|Ti|K|M|G|T)?$",
        }.items():
            quantities[name] = {**mapping(quantities[name]), "pattern": pattern}
        budget["properties"] = quantities
        budgets[responsibility] = budget
    resources["properties"] = budgets
    properties["resources"] = resources
    # Reuse the exact runtime policy/grant definitions instead of maintaining a second authorization schema.
    configuration: dict[str, object] = {"type": "object", "additionalProperties": False, "required": ["policy", "approvals"]}
    configuration["properties"] = {"policy": schema("policy"), "approvals": schema("approvals")}
    properties["configuration"] = configuration
    properties["crypto"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["enabled", "policy"],
        "properties": {"enabled": {"type": "boolean"}, "policy": schema("crypto-policy")},
    }
    generated["properties"] = properties
    generated["required"] = sorted(properties)

    # Validate the assembled dialect before replacing the committed generated contract.
    Draft7Validator.check_schema(generated)
    Path("helm/1password-agent-broker/values.schema.json").write_text(json.dumps(generated, indent=2) + "\n")


if __name__ == "__main__":
    main()
