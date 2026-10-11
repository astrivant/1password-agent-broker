"""
Persist intent before credential access and retain secret-free, replayable outcomes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from importlib.resources import files
from typing import TYPE_CHECKING

from attrs import evolve

from agent_broker.contracts import data, encode, structure
from agent_broker.exceptions import AuditFailure
from agent_broker.models import Result

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


def statement(name: str) -> str:
    """
    Load maintained SQL independently of Python source.

    Args:
        name (str): Packaged SQL filename stem.

    Returns:
        str: Parameterized SQL statement.
    """
    return files("agent_broker").joinpath(f"resources/sql/{name}.sql").read_text()


class Ledger:
    """
    Serialize reservations across processes and keep audit export subordinate to durability.
    """

    def __init__(self, path: Path, exporter: Callable[[dict[str, object]], None] | None = None) -> None:
        """
        Create a private ledger in an operator-owned directory.

        Args:
            path (Path): SQLite destination; its parent must be private to the broker.
            exporter (Callable[[dict[str, object]], None] | None): Optional redacted event sink.
        """
        self.path = path
        self.exporter = exporter
        with self.connection() as connection:
            connection.executescript(statement("schema"))
        path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """
        Own one immediate transaction and redact storage diagnostics.

        Yields:
            sqlite3.Connection: Connection with an exclusive writer reservation.

        Raises:
            AuditFailure: Durable state cannot be read or committed.
        """
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level="IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.Error:
            if connection is not None:
                connection.rollback()
            raise AuditFailure("Ledger unavailable") from None
        finally:
            if connection is not None:
                connection.close()

    def claim(self, request_id: str, principal: str, binding: str) -> Result | None:
        """
        Reserve an exact operation or return its previous safe result.

        Args:
            request_id (str): Canonical request UUID.
            principal (str): Authenticated workload identity.
            binding (str): Hash binding input and policy revision.

        Returns:
            Result | None: Cached, conflicting, or uncertain result; None permits execution.
        """
        with self.connection() as connection:
            inserted = connection.execute(statement("insert_request"), (request_id, principal, binding)).rowcount
            row = connection.execute(statement("select_request"), (request_id,)).fetchone()
            if not inserted and row is not None:
                if row[0] != principal or row[1] != binding:
                    return Result("denied", "denied")
                if row[2] is None:
                    return Result("uncertain", "unknown", replayed=True)
                return evolve(structure(json.loads(row[2]), Result, "result"), replayed=True)
        return None

    def finish(self, request_id: str, result: Result) -> None:
        """
        Persist a bounded result for lost-response retries.

        Args:
            request_id (str): Reserved request UUID.
            result (Result): Secret-free terminal outcome.

        Returns:
            None: Commit the outcome.
        """
        with self.connection() as connection:
            connection.execute(statement("finish"), (encode(data(result)).decode(), request_id))

    def cancel(self, request_id: str, principal: str, binding: str) -> Result:
        """
        Record a cancellation even when execution has not started.

        Args:
            request_id (str): Request UUID to cancel.
            principal (str): Verified owner.
            binding (str): Exact request and policy binding.

        Returns:
            Result: Cancellation acknowledgement or a safe previous outcome.
        """
        with self.connection() as connection:
            inserted = connection.execute(statement("insert_request"), (request_id, principal, binding)).rowcount
            row = connection.execute(statement("select_request"), (request_id,)).fetchone()
            if row is None:
                raise AuditFailure("Reservation missing")
            if inserted:
                result = Result("cancelled", "cancelled")
                connection.execute(statement("finish"), (encode(data(result)).decode(), request_id))
            elif row[0] != principal or row[1] != binding:
                return Result("denied", "denied")
            elif row[2] is not None:
                return evolve(structure(json.loads(row[2]), Result, "result"), replayed=True)
            connection.execute(statement("cancel"), (request_id,))
        return Result("cancelled", "cancelled")

    def cancelled(self, request_id: str) -> bool:
        """
        Check durable cancellation at each execution boundary.

        Args:
            request_id (str): Reserved request UUID.

        Returns:
            bool: Whether its owner has requested cancellation.
        """
        with self.connection() as connection:
            row = connection.execute(statement("select_request"), (request_id,)).fetchone()
        return row is not None and bool(row[3])

    def event(self, name: str, attributes: dict[str, object]) -> bool:
        """
        Commit an OpenTelemetry-shaped event before optional stdout export.

        Args:
            name (str): Fixed event name selected by broker code.
            attributes (dict[str, object]): Allowlisted, secret-free audit attributes.

        Returns:
            bool: True when optional export failed; the durable event still exists.
        """
        event: dict[str, object] = {
            "time_unix_nano": time.time_ns(),
            "observed_time_unix_nano": time.time_ns(),
            "severity_number": 9,
            "severity_text": "INFO",
            "body": name,
            "attributes": attributes,
            "resource": {"attributes": {"service.name": "1password-agent-broker"}},
        }
        with self.connection() as connection:
            connection.execute(statement("event"), (encode(event).decode(),))

        # Export availability must not cause a successfully completed operation to run twice.
        if self.exporter is not None:
            try:
                self.exporter(event)
            except OSError:
                return True
        return False
