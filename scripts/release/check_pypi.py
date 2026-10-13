"""
Require PyPI release metadata to agree with independently verified distribution bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


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


def read_release(version: str) -> dict[str, str]:
    """
    Query the exact public version without conflating registry failures with absence.

    Args:
        version (str): Validated numeric release version.

    Returns:
        dict[str, str]: Registry file digests, or an empty mapping for HTTP 404.

    Raises:
        HTTPError: The registry returns an error other than 404.
        ValueError: The response does not satisfy the file metadata contract.
    """
    try:
        with urlopen(f"https://pypi.org/pypi/1password-agent-broker/{version}/json", timeout=20) as response:
            payload: object = json.load(response)
    except HTTPError as error:
        if error.code != 404:
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
        ValueError: Files are unexpected, changed, or missing after publication.
    """
    for name, digest in published.items():
        if expected.get(name) != digest:
            raise ValueError(f"PyPI file does not match the verified release: {name}")
    if not allow_missing and expected != published:
        raise ValueError("PyPI is missing verified release files")


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
    names = {f"1password_agent_broker-{args.version}-py3-none-any.whl", f"1password_agent_broker-{args.version}.tar.gz"}
    if {path.name for path in args.directory.iterdir()} != names:
        parser.error("Expected exactly the selected release's wheel and source distribution")
    expected = {name: hashlib.sha256((args.directory / name).read_bytes()).hexdigest() for name in names}
    verify_files(expected, read_release(args.version), allow_missing=args.allow_missing)
    print("PyPI file identity verified" if not args.allow_missing else "PyPI upload preflight passed")


if __name__ == "__main__":
    main()
