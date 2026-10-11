"""
Convert measured Python line coverage into a Shields endpoint badge.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree


def main() -> None:
    """
    Validate the test report and write a deterministic badge payload.

    Returns:
        None: Write artifacts/coverage/coverage.json without contacting a badge service.

    Raises:
        ValueError: Covered and total line counts cannot describe a nonempty test report.
    """
    report = ElementTree.parse("artifacts/coverage/coverage.xml").getroot()
    covered = int(report.attrib["lines-covered"])
    total = int(report.attrib["lines-valid"])

    # Never turn a missing or inconsistent measurement into a successful-looking badge.
    if total <= 0 or not 0 <= covered <= total:
        raise ValueError("Coverage requires valid line counts and a nonempty report")

    percent = Decimal(100 * covered) / Decimal(total)
    color = "brightgreen" if percent >= 90 else "green" if percent >= 75 else "yellow" if percent >= 60 else "red"
    badge = {"schemaVersion": 1, "label": "coverage", "message": f"{percent:.1f}%", "color": color}
    Path("artifacts/coverage/coverage.json").write_text(json.dumps(badge, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
