"""
Publish bounded operational measurements without credential or workload labels.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Literal

from prometheus_client import CollectorRegistry, Counter, Enum, Gauge, Histogram, ProcessCollector

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

Phase = Literal["ledger", "provider", "destination"]
State = Literal["starting", "ready", "unavailable", "draining"]
MESSAGES: dict[State, str] = {
    "starting": "Broker is starting",
    "ready": "Broker accepts approved operations",
    "unavailable": "Operator configuration or durable storage is unavailable",
    "draining": "Broker is draining active requests",
}


class Telemetry:
    """
    Own one process registry and synchronized lifecycle state per broker application.
    """

    def __init__(self) -> None:
        """
        Create low-cardinality counters, timings, queue observers, and process measurements.
        """
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        self.in_flight = Gauge("broker_requests_in_flight", "Admitted API requests", registry=self.registry)
        self.phase_active = Gauge("broker_phase_active", "Active dependency operations", ["phase"], registry=self.registry)
        self.duration = Histogram(
            "broker_phase_seconds",
            "Dependency latency including bounded waits",
            ["phase"],
            buckets=(0.005, 0.025, 0.1, 0.5, 1, 2, 5, 10, 20),
            registry=self.registry,
        )
        self.responses = Counter("broker_responses", "Bounded broker outcomes", ["action", "state"], registry=self.registry)
        self.rejected = Counter("broker_capacity_rejections", "Requests refused at application admission", registry=self.registry)
        self.queue = Gauge("broker_queue_size", "Current HTTP or database wait queue size", ["queue"], registry=self.registry)
        self.lifecycle = Enum("broker_status", "Current broker lifecycle status", states=list(MESSAGES), registry=self.registry)
        self._lock = threading.Lock()
        self._state: State = "starting"
        self._active = 0
        self._queues: dict[str, Callable[[], int]] = {}
        self.draining = threading.Event()

    def state(self, state: State) -> None:
        """
        Publish a bounded status while making retirement irreversible.

        Args:
            state (State): Observed dependency or lifecycle state.

        Returns:
            None: Update the status atomically.
        """
        with self._lock:
            if state == "draining":
                self.draining.set()
            self._state = "draining" if self.draining.is_set() else state
            self.lifecycle.state(self._state)

    def observe_queue(self, name: Literal["http", "observability", "database"], size: Callable[[], int]) -> None:
        """
        Register a local snapshot callback that performs no network or database I/O.

        Args:
            name (Literal["http", "observability", "database"]): Fixed queue family.
            size (Callable[[], int]): Thread-safe queue size observer.

        Returns:
            None: Expose the observer through metrics and status snapshots.
        """
        with self._lock:
            self._queues[name] = size
        self.queue.labels(name).set_function(size)

    def snapshot(self) -> dict[str, object]:
        """
        Return a bounded operational status without consulting external services.

        Returns:
            dict[str, object]: Fixed message, active work, and current queue sizes.
        """
        with self._lock:
            return {
                "status": self._state,
                "message": MESSAGES[self._state],
                "in_flight": self._active,
                "queues": {name: size() for name, size in self._queues.items()},
            }

    @contextmanager
    def request(self) -> Iterator[None]:
        """
        Track admitted work until the actual handler completes.

        Yields:
            None: Request owns one active slot until context exit.
        """
        with self._lock:
            self._active += 1
        self.in_flight.inc()
        try:
            yield
        finally:
            self.in_flight.dec()
            with self._lock:
                self._active -= 1

    @contextmanager
    def phase(self, phase: Phase) -> Iterator[None]:
        """
        Measure a dependency call's real lifetime, including failures.

        Args:
            phase (Phase): Fixed dependency family.

        Yields:
            None: The caller owns the dependency operation.
        """
        start = perf_counter()
        self.phase_active.labels(phase).inc()
        try:
            yield
        finally:
            self.phase_active.labels(phase).dec()
            self.duration.labels(phase).observe(perf_counter() - start)
