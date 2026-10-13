"""
Persist intent before credential access and retain secret-free, replayable outcomes.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from importlib.resources import files
from typing import TYPE_CHECKING

from attrs import evolve
from jsonschema import ValidationError, validate
from psycopg import Connection, Error
from psycopg_pool import ConnectionPool

from agent_broker.contracts import data, encode, schema, structure
from agent_broker.exceptions import AuditFailure
from agent_broker.models import Result
from agent_broker.telemetry import Telemetry

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

    def __init__(self, path: Path | None, exporter: Callable[[dict[str, object]], None] | None = None) -> None:
        """
        Create a private ledger in an operator-owned directory.

        Args:
            path (Path | None): Private SQLite destination, or None for PostgreSQL using native PG environment settings.
            exporter (Callable[[dict[str, object]], None] | None): Optional redacted event sink.
        """
        self.path = path
        self.exporter = exporter
        self.telemetry = Telemetry()
        self.pool: ConnectionPool[Connection[tuple[object, ...]]] | None = None
        if path is None:
            # Connection diagnostics may include private host/account data; expose only the fixed failure contract.
            logger = logging.getLogger("psycopg.pool")
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            self.pool = ConnectionPool(
                "",
                min_size=1,
                max_size=4,
                max_waiting=16,
                timeout=2,
                open=False,
                kwargs={
                    "connect_timeout": 3,
                    "sslmode": os.environ.get("PGSSLMODE", "verify-full"),
                    "target_session_attrs": "read-write",
                    "options": "-c statement_timeout=5000 -c lock_timeout=3000",
                },
            )
            self.pool.open()
        self.telemetry.observe_queue("database", self.waiting)
        try:
            with self.connection() as connection:
                if isinstance(connection, sqlite3.Connection):
                    connection.executescript(statement("schema"))
                else:
                    connection.execute(self.query("postgres_schema"))
            if path is not None:
                path.chmod(0o600)
        except AuditFailure:
            self.close()
            raise

    def query(self, name: str) -> str:
        """
        Select placeholders for fixed packaged statements, keeping data parameterized.

        Args:
            name (str): Packaged SQL filename stem.

        Returns:
            str: Statement in the selected driver's parameter style.
        """
        sql = statement(name)
        return sql.replace("?", "%s") if self.pool is not None else sql

    def waiting(self) -> int:
        """
        Read pool waiters without querying PostgreSQL.

        Returns:
            int: Waiting connection requests, or zero for local SQLite.
        """
        return self.pool.get_stats().get("requests_waiting", 0) if self.pool is not None else 0

    def ready(self) -> bool:
        """
        Check the durable primary with the same bounded connection contract as requests.

        Returns:
            bool: Whether a ledger transaction can reach storage.
        """
        try:
            with self.connection() as connection:
                if isinstance(connection, sqlite3.Connection):
                    connection.execute("SELECT 1")
                else:
                    row = connection.execute("SHOW transaction_read_only").fetchone()
                    return row == ("off",)
            return True
        except AuditFailure:
            return False

    def close(self) -> None:
        """
        Close PostgreSQL pool workers after request handlers have drained.

        Returns:
            None: All owned pool workers are stopped.
        """
        if self.pool is not None:
            self.pool.close(timeout=5)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection | Connection[tuple[object, ...]]]:
        """
        Own one immediate transaction and redact storage diagnostics.

        Yields:
            sqlite3.Connection | Connection[tuple[object, ...]]: Transaction using the selected durable backend.

        Raises:
            AuditFailure: Durable state cannot be read or committed.
        """
        connection: sqlite3.Connection | None = None
        try:
            if self.pool is not None:
                with self.telemetry.phase("ledger"), self.pool.connection() as pooled:
                    yield pooled
                return
            if self.path is None:
                raise AuditFailure("Ledger unavailable")
            connection = sqlite3.connect(self.path, timeout=5, isolation_level="IMMEDIATE")
            with self.telemetry.phase("ledger"):
                yield connection
                connection.commit()
        except (sqlite3.Error, Error):
            if connection is not None:
                connection.rollback()
            raise AuditFailure("Ledger unavailable") from None
        finally:
            if connection is not None:
                connection.close()

    def claim(self, request_id: str, principal: str, binding: str, recovery_binding: str | None = None) -> Result | None:
        """
        Reserve an exact operation or return its previous safe result.

        Args:
            request_id (str): Canonical request UUID.
            principal (str): Authenticated workload identity.
            binding (str): Hash binding input and policy revision.
            recovery_binding (str | None): Exact request and authenticated identity snapshot, for recovery only.

        Returns:
            Result | None: Cached, conflicting, or uncertain result; None permits execution.
        """
        with self.connection() as connection:
            inserted = connection.execute(self.query("insert_request"), (request_id, principal, binding)).rowcount
            if inserted and recovery_binding is not None:
                connection.execute(self.query("insert_context"), (request_id, recovery_binding))
            row = connection.execute(self.query("select_request"), (request_id,)).fetchone()
            if not inserted and row is not None:
                if row[0] != principal or row[1] != binding:
                    return Result("denied", "denied")
                if row[2] is None:
                    return Result("uncertain", "unknown", replayed=True)
                return evolve(stored_result(row[2]), replayed=True)
        return None

    def finish(self, request_id: str, result: Result) -> Result:
        """
        Persist a bounded result for lost-response retries.

        Args:
            request_id (str): Reserved request UUID.
            result (Result): Secret-free terminal outcome.

        Returns:
            Result: Committed outcome, accounting for cancellation racing completion.
        """
        with self.connection() as connection:
            # The driver's IMMEDIATE transaction starts on this no-op write, before reading cancellation.
            connection.execute(self.query("lock_request"), (request_id,))
            row = connection.execute(self.query("select_request"), (request_id,)).fetchone()
            context = connection.execute(self.query("select_context"), (request_id,)).fetchone()
            if row is None:
                raise AuditFailure("Reservation missing")
            if row[3] and (context is None or context[1]):
                result = Result("uncertain", "unknown", audit_warning=result.audit_warning)
            connection.execute(self.query("finish"), (encode(data(result)).decode(), request_id))
        return result

    def inspect(self, request_id: str, principal: str, recovery_binding: str) -> Result:
        """
        Recover only existing state bound to this exact request and identity snapshot.

        Args:
            request_id (str): Request UUID to inspect.
            principal (str): Currently authenticated workload name.
            recovery_binding (str): Original request and authenticated identity snapshot hash.

        Returns:
            Result: Recorded result or uncertainty; never reserve or execute work.
        """
        with self.connection() as connection:
            row = connection.execute(self.query("select_request"), (request_id,)).fetchone()
            context = connection.execute(self.query("select_context"), (request_id,)).fetchone()
            if row is None or row[0] != principal or context is None or context[0] != recovery_binding:
                return Result("denied", "denied")
            if row[2] is None:
                return Result("uncertain", "unknown", replayed=True)
            return evolve(stored_result(row[2]), replayed=True)

    def begin(self, request_id: str) -> bool:
        """
        Serialize the submission boundary against cancellation in the shared ledger.

        Args:
            request_id (str): Owned request with recovery context.

        Returns:
            bool: Whether this owner may attempt the destination operation.
        """
        with self.connection() as connection:
            # Both drivers lock the request before its context, serializing admission against cancellation.
            connection.execute(self.query("lock_request"), (request_id,))
            return connection.execute(self.query("begin"), (request_id, request_id)).rowcount == 1

    def cancel(self, request_id: str, principal: str, binding: str, recovery_binding: str | None = None) -> Result:
        """
        Record a cancellation even when execution has not started.

        Args:
            request_id (str): Request UUID to cancel.
            principal (str): Verified owner.
            binding (str): Exact request and policy binding.
            recovery_binding (str | None): Request and identity snapshot binding independent of mutable policy.

        Returns:
            Result: Cancellation acknowledgement or a safe previous outcome.
        """
        with self.connection() as connection:
            inserted = connection.execute(self.query("insert_request"), (request_id, principal, binding)).rowcount
            connection.execute(self.query("lock_request"), (request_id,))
            row = connection.execute(self.query("select_request"), (request_id,)).fetchone()
            context = connection.execute(self.query("select_context"), (request_id,)).fetchone()
            if row is None:
                raise AuditFailure("Reservation missing")
            if inserted:
                if recovery_binding is not None:
                    connection.execute(self.query("insert_context"), (request_id, recovery_binding))
                result = Result("cancelled", "cancelled")
                connection.execute(self.query("finish"), (encode(data(result)).decode(), request_id))
            elif row[0] != principal or (context[0] != recovery_binding if context is not None else row[1] != binding):
                return Result("denied", "denied")
            elif row[2] is not None:
                return evolve(stored_result(row[2]), replayed=True)
            connection.execute(self.query("cancel"), (request_id,))
            if not inserted and (context is None or context[1]):
                return Result("uncertain", "unknown")
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
            row = connection.execute(self.query("select_request"), (request_id,)).fetchone()
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
            "attributes": dict(attributes),
            "resource": {"attributes": {"service.name": "1password-agent-broker"}},
        }

        # Reject unexpected fields before either durable storage or optional export receives them.
        try:
            validate(event, schema("event"))
        except ValidationError:
            raise AuditFailure("Invalid audit event") from None
        with self.connection() as connection:
            connection.execute(self.query("event"), (encode(event).decode(),))

        # Export availability must not cause a successfully completed operation to run twice.
        if self.exporter is not None:
            try:
                self.exporter(event)
            except OSError:
                return True
        return False


def stored_result(value: object) -> Result:
    """
    Validate persisted outcomes before replaying them through either storage adapter.

    Args:
        value (object): Stored result column.

    Returns:
        Result: Closed, secret-free result.

    Raises:
        AuditFailure: Durable result is malformed or has an unknown schema.
    """
    try:
        if not isinstance(value, str):
            raise ValueError("Invalid stored result")
        return structure(json.loads(value), Result, "result")
    except (ValueError, TypeError):
        raise AuditFailure("Invalid stored result") from None
