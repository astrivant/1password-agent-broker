"""
Publish counts and vulnerability identifiers while discarding every secret-match field.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def summarize(raw: object) -> dict[str, object]:
    """
    Reduce a Trivy report to an explicit public allowlist.

    Args:
        raw (object): Untrusted scanner JSON, including potentially sensitive matches.

    Returns:
        dict[str, object]: Secret counts and syntactically bounded advisory identifiers.

    Raises:
        ValueError: The scanner envelope is invalid or incomplete.
    """
    if not isinstance(raw, dict) or raw.get("SchemaVersion") != 2:
        raise ValueError("Invalid scanner report")
    results = raw.get("Results", [])
    if not isinstance(results, list):
        raise ValueError("Invalid scanner results")
    secret_count = 0
    vulnerabilities: set[str] = set()
    vulnerability_count = 0

    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Invalid scanner result")
        secrets = result.get("Secrets", [])
        findings = result.get("Vulnerabilities", [])
        if not isinstance(secrets, list) or not isinstance(findings, list):
            raise ValueError("Invalid scanner findings")
        secret_count += len(secrets)

        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError("Invalid scanner vulnerability")
            if finding.get("Severity") not in ("HIGH", "CRITICAL"):
                continue
            vulnerability_count += 1
            identifier = finding.get("VulnerabilityID", "")
            if isinstance(identifier, str) and re.fullmatch(r"(?:CVE-[0-9]{4}-[0-9]{4,10}|GHSA-[a-z0-9-]{14})", identifier):
                vulnerabilities.add(identifier)
    return {"secret_findings": secret_count, "high_critical_vulnerabilities": vulnerability_count, "advisories": sorted(vulnerabilities)}


def main() -> int:
    """
    Sanitize before writing artifacts or stdout, then enforce the scan gate.

    Returns:
        int: One for findings, two for malformed output, otherwise zero.
    """
    try:
        report = summarize(json.loads(Path(sys.argv[1]).read_bytes()))
        output = json.dumps(report, sort_keys=True, indent=2) + "\n"
        Path(sys.argv[2]).write_text(output)
        print(output, end="")
        return int(bool(report["secret_findings"] or report["high_critical_vulnerabilities"]))
    except (OSError, ValueError, IndexError):
        print("Security scan report could not be validated.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
