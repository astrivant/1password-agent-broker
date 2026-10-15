"""
Preserve the runtime client import while standalone consumers install agent_broker_sdk.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_broker_sdk.client import CryptoClient as SDKClient
from agent_broker_sdk.exceptions import BrokerError

from agent_broker.exceptions import ProviderFailure, Rejected
from agent_broker.transport import Client

if TYPE_CHECKING:
    from pathlib import Path

    from agent_broker_sdk.models import Request

__all__ = ["CryptoClient"]


class CryptoClient(SDKClient, Client):
    """
    Translate SDK errors for callers of the original broker runtime import.
    """

    def __init__(self, url: str, ca: Path, cert: Path, key: Path) -> None:
        """
        Preserve the runtime constructor and its configuration exception contract.

        Args:
            url (str): Trusted HTTPS broker origin.
            ca (Path): Broker certificate authority.
            cert (Path): Scoped workload certificate.
            key (Path): Workload TLS private key.

        Raises:
            Rejected: Transport configuration is invalid.
        """
        try:
            super().__init__(url, ca, cert, key)
        except BrokerError:
            raise Rejected("Invalid broker transport configuration") from None

    def invoke(self, request: Request) -> bytes:
        """
        Delegate one key request without installing this compatibility wrapper in SDK consumers.

        Args:
            request (Request): Exact versioned request.

        Returns:
            bytes: Transient authorized result.

        Raises:
            ProviderFailure: The service operation failed without an implicit retry.
        """
        try:
            return super().invoke(request)
        except BrokerError:
            raise ProviderFailure("Crypto operation unavailable") from None
