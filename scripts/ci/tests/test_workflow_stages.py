"""
Protect source, artifact, permission, and failure boundaries across reusable CI stages.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"
INDEPENDENT = ("lint", "tests", "package", "charts", "security")
VALIDATION = (*INDEPENDENT, "release-contract")


def test_stages_use_the_callers_source_without_adding_event_triggers() -> None:
    """
    Keep stage execution in one run and bind every checkout to its caller's source.

    Returns:
        None: Every extracted stage has a matching call, required source input, and immutable checkout.
    """
    workflow = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)
    called = set()

    # The merge gate keeps its check name; all implementation stages are locally composed.
    for name, caller in workflow["jobs"].items():
        if name == "quality-gate":
            continue
        reference = caller["uses"]
        assert reference.startswith("./.github/workflows/stage-")
        assert caller["with"]["source_sha"] == "${{ github.sha }}"
        path = ROOT / reference
        called.add(path.name)
        stage = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        assert set(stage["on"]) == {"workflow_call"}
        contract = stage["on"]["workflow_call"]["inputs"]["source_sha"]
        assert contract["type"] == "string" and contract["required"] == "true"
        assert "concurrency" not in stage
        for job in stage["jobs"].values():
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    assert step["with"]["ref"] == "${{ inputs.source_sha }}"
    assert called == {path.name for path in WORKFLOWS.glob("stage-*.yml")}


def test_independent_stages_and_their_consumers_keep_a_shallow_graph() -> None:
    """
    Prevent extraction from serializing source checks or detaching artifact consumers.

    Returns:
        None: Only real producer dependencies delay validation and coverage.
    """
    jobs = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]
    for name in INDEPENDENT:
        assert "needs" not in jobs[name]
        stage = yaml.load((ROOT / jobs[name]["uses"]).read_text(), Loader=yaml.BaseLoader)
        assert all("needs" not in job and "if" not in job for job in stage["jobs"].values())
    assert set(jobs["release-contract"]["needs"]) == {"package", "charts"}
    assert jobs["coverage"]["needs"] == "tests"


@pytest.mark.parametrize("consumer", ["release-contract", "release"])
def test_release_consumers_use_the_current_runs_build_artifacts(consumer: str) -> None:
    """
    Follow artifact producers and consumers across the extracted workflow files.

    Args:
        consumer (str): Stage that verifies or publishes the package and chart archives.

    Returns:
        None: The consumer uses both current-run outputs without rebuilding or selecting another run.
    """
    produced = set()
    for name in ("package", "charts"):
        stage = yaml.load((WORKFLOWS / f"stage-{name}.yml").read_text(), Loader=yaml.BaseLoader)
        for step in stage["jobs"][name]["steps"]:
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                produced.add(step["with"]["name"])
    stage = yaml.load((WORKFLOWS / f"stage-{consumer}.yml").read_text(), Loader=yaml.BaseLoader)
    downloads = [step["with"] for step in stage["jobs"][consumer]["steps"] if step.get("uses", "").startswith("actions/download-artifact@")]
    assert {item["name"] for item in downloads} == produced == {"distributions", "helm-chart"}
    assert all(set(item) == {"name", "path"} and item["path"] == "dist/" for item in downloads)


def test_stage_secrets_and_write_permissions_stay_scoped() -> None:
    """
    Keep publisher credentials and branch writers out of independent source checks.

    Returns:
        None: Only publishing callers pass secrets or grant write permission, and PyPI retains approval and serialization.
    """
    workflow = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert {name for name, job in jobs.items() if job.get("permissions") == {"contents": "write"}} == {"coverage", "release"}
    assert {name for name, job in jobs.items() if "secrets" in job} == {"release", "pypi"}
    for name, expected in (("release", {"COSIGN_PRIVATE_KEY", "COSIGN_PASSWORD"}), ("pypi", {"PYPI_API_TOKEN"})):
        assert set(jobs[name]["secrets"]) == expected
        stage = yaml.load((ROOT / jobs[name]["uses"]).read_text(), Loader=yaml.BaseLoader)
        assert set(stage["on"]["workflow_call"]["secrets"]) == expected
        assert all(value["required"] == "true" for value in stage["on"]["workflow_call"]["secrets"].values())
    pypi = yaml.load((WORKFLOWS / "stage-pypi.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]["pypi"]
    assert pypi["environment"]["name"] == "pypi"
    assert pypi["concurrency"] == {"group": "pypi-${{ needs.pypi-prepare.outputs.version }}", "cancel-in-progress": "false"}


def test_terminal_tag_check_and_manual_pypi_retry_keep_their_failure_gates() -> None:
    """
    Retain explicit status checks where optional skipped ancestors otherwise block execution.

    Returns:
        None: Tag verification remains terminal and manual retries cannot bypass failed validation.
    """
    jobs = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]
    assert jobs["release-verification"]["needs"] == "release"
    assert " ".join(jobs["release-verification"]["if"].split()) == (
        "always() && startsWith(github.ref, 'refs/tags/v') && github.repository == 'astrivant/1password-agent-broker'"
    )
    assert set(jobs["pypi"]["needs"]) == {*VALIDATION, "release-verification"}
    retry = " ".join(jobs["pypi"]["if"].split())
    authorization, paths = retry.split(" && ((", 1)
    required = {"!cancelled()", "github.repository == 'astrivant/1password-agent-broker'"}
    required.update(f"needs.{name}.result == 'success'" for name in VALIDATION)
    # Conjunction order is immaterial, but every prerequisite must guard both event paths.
    assert set(authorization.split(" && ")) == required
    assert paths == (
        "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
        " && needs.release-verification.result == 'success')"
        " || (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && inputs.pypi_release != ''))"
    )
    stage = yaml.load((WORKFLOWS / "stage-pypi.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]
    assert stage["pypi"]["needs"] == "pypi-prepare"
    assert set(stage["pypi-verification"]["needs"]) == {"pypi-prepare", "pypi"}
    assert " ".join(stage["pypi-verification"]["if"].split()) == "!cancelled() && needs.pypi-prepare.result == 'success'"
    check = next(step for step in stage["pypi-verification"]["steps"] if step.get("env", {}).get("PUBLISH_RESULT"))
    assert check["env"]["PUBLISH_RESULT"] == "${{ needs.pypi.result }}"
    assert check["run"] == 'test "$PUBLISH_RESULT" = success'
