"""
Provide a maintained mTLS SDK for trusted services without exposing key operations through MCP.
"""

from __future__ import annotations

import json
from http.client import HTTPException, HTTPSConnection

from agent_broker import contracts
from agent_broker.crypto.contracts import decode, parse_request
from agent_broker.crypto.models import Request, Response
from agent_broker.exceptions import ProviderFailure, Rejected
from agent_broker.transport import Client

__all__ = ["CryptoClient"]


class CryptoClient(Client):
    """
    Reuse the broker's certificate-authenticated origin validation and transport configuration.
    """

    def invoke(self, request: Request) -> bytes:
        """
        Send one service-only key operation and return transient output without logging it.

        Args:
            request (Request): Exact scoped request, including its retry identity.

        Returns:
            bytes: Authorized result, possibly a transient data key; callers must never serialize it to logs.

        Raises:
            ProviderFailure: Admission, transport or cryptography failed; no plaintext fallback or implicit retry.
        """
        connection = HTTPSConnection(self.host, self.port, context=self.context, timeout=30)
        try:
            body = contracts.encode(contracts.data(parse_request(contracts.data(request))))
            if len(body) > 4096:
                raise Rejected("Crypto request exceeds transport budget")
            connection.request("POST", "/crypto", body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            payload = response.read(4097)
            if response.status != 200 or len(payload) > 4096:
                raise Rejected("Invalid crypto response")
            result = contracts.structure(json.loads(payload), Response, "crypto-response")
            if result.code != "ok":
                raise Rejected("Crypto request unavailable")
            return decode(result.payload, 1024)
        except (OSError, HTTPException, ValueError, Rejected):
            raise ProviderFailure("Crypto operation unavailable") from None
        finally:
            connection.close()
