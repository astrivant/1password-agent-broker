"""
Send service-only key requests over authenticated TLS without provider or server dependencies.
"""

from __future__ import annotations

import json
import ssl
from http import HTTPStatus
from http.client import HTTPException, HTTPSConnection
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from agent_broker_sdk import contracts
from agent_broker_sdk.exceptions import BrokerError

if TYPE_CHECKING:
    from pathlib import Path

    from agent_broker_sdk.models import Request

__all__ = ["CryptoClient"]


class CryptoClient:
    """
    Own transport configuration while the deployed broker owns authorization and key custody.
    """

    def __init__(self, url: str, ca: Path, cert: Path, key: Path) -> None:
        """
        Load a trusted HTTPS origin and the workload's scoped client certificate.

        Args:
            url (str): Broker HTTPS origin without credentials, query or fragment.
            ca (Path): Trusted broker certificate authority.
            cert (Path): Workload certificate approved by the broker operator.
            key (Path): Workload TLS key; never a provider credential or custodial key.

        Raises:
            BrokerError: Origin or certificate configuration is invalid, without reflecting input.
        """
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path not in ("", "/")
                or parsed.username is not None
                or parsed.password is not None
                or "?" in url
                or "#" in url
                or parsed.port == 0
                or not url.isascii()
                or any(ord(character) < 33 or ord(character) == 127 for character in url)
            ):
                raise BrokerError("Invalid broker origin")
            self.host = parsed.hostname
            self.port = parsed.port or 443
            self.context = ssl.create_default_context(cafile=ca)
            self.context.minimum_version = ssl.TLSVersion.TLSv1_3
            self.context.load_cert_chain(cert, key)
        except (OSError, ValueError):
            raise BrokerError("Invalid broker transport configuration") from None

    def invoke(self, request: Request) -> bytes:
        """
        Send one bounded operation without implicit retries or payload logging.

        Args:
            request (Request): Exact scoped request, including its retry identity.

        Returns:
            bytes: Authorized result; transient data keys must remain outside logs and agent context.

        Raises:
            BrokerError: Validation, admission, authorization or transport failed. No plaintext fallback.
        """
        connection = HTTPSConnection(self.host, self.port, context=self.context, timeout=30)
        try:
            body = contracts.encode(contracts.data(contracts.parse_request(contracts.data(request))))
            if len(body) > 4096:
                raise BrokerError("Invalid broker request")
            connection.request("POST", "/crypto", body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()

            # One extra byte distinguishes an oversized body from a complete bounded response.
            payload = response.read(4097)
            if response.status != HTTPStatus.OK or len(payload) > 4096:
                raise BrokerError("Invalid broker response")
            result = contracts.parse_response(json.loads(payload))
            if result.code != "ok":
                raise BrokerError("Broker operation unavailable")
            return contracts.decode(result.payload, 1024)
        except (OSError, HTTPException, ValueError, BrokerError):
            raise BrokerError("Broker operation unavailable") from None
        finally:
            connection.close()
