"""
Regenerate the root README's bounded table of contents from its actual headings.
"""

from __future__ import annotations

import re
from pathlib import Path


def main() -> None:
    """
    Update maintained markers, excluding fenced examples and headings below level three.

    Returns:
        None: Write the README only when generated navigation changed.
    """
    path = Path(__file__).resolve().parents[2] / "README.md"
    source = path.read_text()
    rows = []
    fenced = False

    for line in source.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        match = re.fullmatch(r"(#{2,3}) (.+)", line)
        if fenced or match is None:
            continue
        level, title = match.groups()
        anchor = re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")
        rows.append(f"{'  ' * (len(level) - 2)}- [{title}](#{anchor})")
    generated = "<!-- toc -->\n\n" + "\n".join(rows) + "\n\n<!-- /toc -->"
    result, count = re.subn(r"<!-- toc -->.*?<!-- /toc -->", generated, source, flags=re.DOTALL)
    if count != 1:
        raise ValueError("README must have one TOC marker pair")
    if result != source:
        path.write_text(result)


if __name__ == "__main__":
    main()
