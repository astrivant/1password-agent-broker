"""
Keep README navigation reproducible across supported editor marker styles.
"""

from __future__ import annotations

import pytest

from scripts.documentation.contents import contents


@pytest.mark.parametrize("marker", ["toc", "TOC"])
def test_editor_markers_preserve_surrounding_content(marker: str) -> None:
    """
    Refresh stale navigation without changing editor markers or authored content.

    Args:
        marker (str): Supported marker spelling emitted by an editor or generator.

    Returns:
        None: Navigation reflects headings and stays unchanged on a second pass.
    """
    before = "# Example\n\nKeep this introduction.\n\n"
    after = "\n\n## Inputs\n\nDocumented values.\n\n### Runtime\n\n```markdown\n## Example only\n```\n"
    source = f"{before}<!-- {marker} -->\n\n- [Removed](#removed)\n\n<!-- /{marker} -->{after}"
    result = contents(source)

    assert result == (f"{before}<!-- {marker} -->\n\n- [Inputs](#inputs)\n  - [Runtime](#runtime)\n\n<!-- /{marker} -->{after}")
    assert contents(result) == result


@pytest.mark.parametrize("source", ["## Missing markers\n", "<!-- TOC -->\n<!-- /TOC -->\n<!-- toc -->\n<!-- /toc -->"])
def test_missing_or_duplicate_markers_are_rejected(source: str) -> None:
    """
    Retain the single-region contract when accepting either marker spelling.

    Args:
        source (str): README with no marker pair or multiple generated regions.

    Returns:
        None: Invalid navigation regions fail visibly instead of silently updating.
    """
    with pytest.raises(ValueError, match="one TOC marker pair"):
        contents(source)
