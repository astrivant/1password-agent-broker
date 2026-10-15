"""
Require PyPI release metadata to agree with independently verified distribution bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


class PublicationPendingError(ValueError):
    """
    Indicate missing registry files without accepting a contradictory file identity.
    """


def release_files(payload: object) -> dict[str, str]:
    """
    Read a closed set of published filename/digest pairs, rejecting ambiguous releases.

    Args:
        payload (object): Decoded PyPI version JSON response.

    Returns:
        dict[str, str]: Unique non-yanked filenames and SHA-256 digests.

    Raises:
        ValueError: Metadata is malformed, duplicated or yanked.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("urls"), list):
        raise ValueError("PyPI response has no release files")
    files: dict[str, str] = {}

    # Reject ambiguity rather than allowing later entries to replace an earlier digest.
    for item in payload["urls"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid PyPI file metadata")
        name, digests = item.get("filename"), item.get("digests")
        if not isinstance(name, str) or not isinstance(digests, dict) or item.get("yanked") is not False:
            raise ValueError("Invalid or yanked PyPI file")
        digest = digests.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None or name in files:
            raise ValueError("Invalid or duplicate PyPI digest")
        files[name] = digest
    return files


def read_release(version: str, project: str = "1password-agent-broker") -> dict[str, str]:
    """
    Query the exact public version without conflating registry failures with absence.

    Args:
        version (str): Validated numeric release version.
        project (str): Reviewed distribution name.

    Returns:
        dict[str, str]: Registry file digests, or an empty mapping for HTTP 404.

    Raises:
        HTTPError: The registry returns an error other than 404.
        ValueError: The response does not satisfy the file metadata contract.
    """
    try:
        with urlopen(f"https://pypi.org/pypi/{project}/{version}/json", timeout=20) as response:
            payload: object = json.load(response)
    except HTTPError as error:
        if error.code != HTTPStatus.NOT_FOUND:
            raise
        return {}
    return release_files(payload)


def verify_files(expected: dict[str, str], published: dict[str, str], *, allow_missing: bool) -> None:
    """
    Permit retries only when every existing file has the originally verified bytes.

    Args:
        expected (dict[str, str]): Verified distribution filenames and digests.
        published (dict[str, str]): Observed PyPI distribution filenames and digests.
        allow_missing (bool): Whether absent files may be uploaded by the following job.

    Returns:
        None: The observed release satisfies the selected publication phase.

    Raises:
        ValueError: Files are unexpected or changed.
        PublicationPendingError: Expected files are not yet visible after publication.
    """
    for name, digest in published.items():
        if expected.get(name) != digest:
            raise ValueError(f"PyPI file does not match the verified release: {name}")
    if not allow_missing and expected != published:
        raise PublicationPendingError("PyPI is missing verified release files")


def verify_release(expected: dict[str, str], version: str, *, allow_missing: bool, project: str = "1password-agent-broker") -> None:
    """
    Bound the wait for registry metadata visibility after a successful upload.

    Args:
        expected (dict[str, str]): Independently authenticated filenames and hashes.
        version (str): Exact release version to query.
        allow_missing (bool): Whether this is the pre-upload compatibility check.
        project (str): Reviewed distribution name.

    Returns:
        None: Registry files satisfy the selected publication phase.

    Raises:
        PublicationPendingError: Missing files remain after sixty seconds of backoff.
        ValueError: Registry identity contradicts the verified release.
        HTTPError: The registry request failed for a reason other than absence.
    """
    delays = (0, 2, 4, 8, 16, 30)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            verify_files(expected, read_release(version, project), allow_missing=allow_missing)
        except PublicationPendingError:
            # A newly uploaded release can outpace public metadata; mismatches must never enter this retry path.
            if attempt == len(delays) - 1:
                raise
            print("Waiting for PyPI release metadata to become visible", flush=True)
        else:
            return


def main() -> None:
    """
    Compare only the selected wheel and source distribution with live registry metadata.

    Returns:
        None: All requested comparisons passed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version) is None:
        parser.error("Expected a numeric major.minor.patch version")
    projects = ["1password-agent-broker"]
    if any(args.directory.glob("1password_agent_broker_sdk-*.whl")):
        projects.append("1password-agent-broker-sdk")
    packages = {
        project: {f"{project.replace('-', '_')}-{args.version}-py3-none-any.whl", f"{project.replace('-', '_')}-{args.version}.tar.gz"}
        for project in projects
    }
    if {path.name for path in args.directory.iterdir()} != set().union(*packages.values()):
        parser.error("Expected exactly the authenticated release's Python distributions")
    for project, names in packages.items():
        expected = {name: hashlib.sha256((args.directory / name).read_bytes()).hexdigest() for name in names}
        verify_release(expected, args.version, allow_missing=args.allow_missing, project=project)
    print("PyPI file identity verified" if not args.allow_missing else "PyPI upload preflight passed")


if __name__ == "__main__":
    main()
