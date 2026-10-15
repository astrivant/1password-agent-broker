"""
Verify PEP 561 markers in independently installed distribution files.
"""

from __future__ import annotations

import argparse
from importlib.metadata import distribution


def main() -> None:
    """
    Require each selected installed distribution to advertise its bundled inline annotations.

    Returns:
        None: Wheel or rebuilt-sdist installation contains the selected package's typing marker.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="+", choices=("agent_broker", "agent_broker_sdk"))
    selected = parser.parse_args().packages
    distributions = {"agent_broker": "1password-agent-broker", "agent_broker_sdk": "1password-agent-broker-sdk"}
    for package in selected:
        installed = distribution(distributions[package])
        marker = f"{package}/py.typed"
        assert installed.files is not None and marker in {str(path) for path in installed.files}, f"Missing installed marker: {marker}"
        installed.locate_file(marker).read_text()


if __name__ == "__main__":
    main()
