"""
Share owned, synthetic integration resources without external credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from agent_broker.testing.scenario import scenario

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agent_broker.testing.scenario import Scenario


@pytest.fixture
def fixture(tmp_path: Path) -> Iterator[Scenario]:
    """
    Start two TLS identities and their local HTTPS target.

    Args:
        tmp_path (Path): Pytest-owned temporary directory.

    Yields:
        Scenario: Isolated policy, ledger, provider, and network endpoints.
    """
    with scenario(tmp_path) as item:
        yield item
