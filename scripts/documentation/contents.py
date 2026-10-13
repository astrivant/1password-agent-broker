"""
Maintain bounded navigation in root and nested project READMEs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def contents(source: str) -> str:
    """
    Render navigation from actual headings while excluding fenced examples.

    Args:
        source (str): README with exactly one navigation marker pair.

    Returns:
        str: README with a deterministic table of contents at most three levels deep.
    """
    rows = []
    fenced = False

    # Ignore headings inside examples so copied Markdown does not enter the document navigation.
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
    return result


def main() -> None:
    """
    Discover maintained READMEs with Git, including non-ignored new chart documentation.

    Returns:
        None: Update navigation, or fail check mode on stale output.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    # Discover tracked and new maintained files through Git, excluding installed dependencies and ignored outputs.
    paths = (
        subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    for name in sorted(set(paths)):
        if Path(name).name != "README.md":
            continue
        path = root / name
        source = path.read_text()
        result = contents(source)
        if result != source:
            if args.check:
                raise ValueError(f"Stale README contents: {name}")
            path.write_text(result)


if __name__ == "__main__":
    main()
