"""
Define redacted failure categories; callers never expose provider exception bodies.
"""

from __future__ import annotations


class Rejected(ValueError):
    """
    Reject malformed contracts or authorization without inspecting credentials.
    """


class ProviderFailure(RuntimeError):
    """
    Indicate that credential resolution did not produce a usable value.
    """


class DestinationFailure(RuntimeError):
    """
    Indicate an uncertain network outcome without retaining response data.
    """


class AuditFailure(RuntimeError):
    """
    Stop execution when required durable evidence cannot be recorded.
    """
