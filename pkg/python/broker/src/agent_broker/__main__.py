"""
Support module execution through the same installed CLI entry point.
"""

from __future__ import annotations

from agent_broker.cli import main

raise SystemExit(main())
