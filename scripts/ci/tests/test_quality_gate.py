"""
Keep merge protection tied to a complete, successful set of CI prerequisites.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = ("charts", "lint", "package", "release-contract", "security", "tests")


def gate_result(payload: str) -> int:
    """
    Exercise the same shell boundary used by GitHub Actions without network access.

    Args:
        payload (str): Serialized prerequisite results, including malformed cases.

    Returns:
        int: Shell exit status, with zero reserved for complete success.
    """
    return subprocess.run(
        ["bash", str(ROOT / "scripts/ci/checks/quality-gate.sh")],
        env={**os.environ, "NEEDS_JSON": payload},
        capture_output=True,
        check=False,
        timeout=10,
    ).returncode


def test_all_prerequisites_succeed() -> None:
    """
    Permit the merge gate only when every required producer succeeded.

    Returns:
        None: The complete success path passes.
    """
    assert gate_result(json.dumps({name: {"result": "success"} for name in REQUIRED})) == 0


@pytest.mark.parametrize("job_id", REQUIRED)
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_unsuccessful_prerequisite_blocks_merge(job_id: str, result: str) -> None:
    """
    Reject failure, cancellation and optional-skip leakage from every producer.

    Args:
        job_id (str): Required producer whose result changes.
        result (str): Non-success state supplied by GitHub Actions.

    Returns:
        None: The unsuccessful gate cannot permit a normal merge.
    """
    payload = {name: {"result": "success"} for name in REQUIRED}
    payload[job_id]["result"] = result
    assert gate_result(json.dumps(payload)) != 0


@pytest.mark.parametrize("payload", ["{}", "[]", "null", "invalid", "", '{"tests":{"result":"success"}}'])
def test_incomplete_or_malformed_results_block_merge(payload: str) -> None:
    """
    Reject empty, incomplete and malformed result sets rather than vacuous success.

    Args:
        payload (str): Invalid prerequisite payload.

    Returns:
        None: Every invalid boundary input fails.
    """
    assert gate_result(payload) != 0


def test_gate_matches_workflow_and_branch_policy() -> None:
    """
    Prevent settings drift, filtered PR triggers and silently omitted producers.

    Returns:
        None: The stable required check covers the entire validation graph.
    """
    # BaseLoader preserves GitHub's YAML key "on" instead of treating it as a YAML 1.1 boolean.
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    gate = jobs["quality-gate"]
    assert sorted(gate["needs"]) == list(REQUIRED)
    assert set(gate["needs"]) == set(jobs["release"]["needs"])
    assert all(name in jobs and "if" not in jobs[name] for name in REQUIRED)
    assert gate["if"] == "always()"
    assert workflow["on"]["pull_request"] == ""
    assert "main" in workflow["on"]["push"]["branches"]
    assert gate["steps"][-1]["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert gate["steps"][-1]["run"] == "bash scripts/ci/checks/quality-gate.sh"

    settings = yaml.safe_load((ROOT / ".github/settings.yml").read_text())
    policy = next(branch["protection"] for branch in settings["branches"] if branch["name"] == "main")
    assert policy["required_status_checks"] == {
        "strict": True,
        "checks": [{"context": gate["name"], "app_id": 15368}],
    }
    assert policy["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert policy["required_pull_request_reviews"]["dismiss_stale_reviews"] is True
    assert policy["enforce_admins"] is False
    assert policy["required_conversation_resolution"] is True
    assert policy["restrictions"] is None
    assert policy["allow_force_pushes"] is False
    assert policy["allow_deletions"] is False


def test_app_bound_checks_do_not_include_legacy_contexts() -> None:
    """
    Reject the mutually exclusive status-check fields refused by GitHub's API.

    Returns:
        None: The policy uses only the app-bound form of required status checks.
    """
    settings = yaml.safe_load((ROOT / ".github/settings.yml").read_text())
    for branch in settings["branches"]:
        checks = branch["protection"]["required_status_checks"]
        assert not {"contexts", "checks"}.issubset(checks)
