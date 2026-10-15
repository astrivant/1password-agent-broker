"""
Expose bounded client failures independently of the broker runtime.
"""

from __future__ import annotations

__all__ = ["BrokerError"]


class BrokerError(RuntimeError):
    """
    Report a fixed transport or contract error without reflecting sensitive payloads.
    """
