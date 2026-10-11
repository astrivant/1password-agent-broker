"""
Own listener and worker lifetimes, including graceful signal-driven shutdown.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agent_broker.transport import TLSServer


@contextmanager
def running(server: TLSServer) -> Iterator[None]:
    """
    Own listener and worker lifetime, including cleanup on failed assertions.

    Args:
        server (TLSServer): Bound local server.

    Yields:
        None: Server is listening until the context exits.
    """
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("Server did not drain")
