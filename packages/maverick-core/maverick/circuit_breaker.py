"""Per-key circuit breaker.

Lets callers wrap an external call site with a circuit that opens
after N consecutive failures and stays open for a cooldown window
before letting a single probe through.

Goal: when a provider is having an outage, fail fast (no 30-second
timeouts on every call) AND don't hammer the dead service with
retry storms.

Three states (classic):
  - CLOSED:   all calls go through
  - OPEN:     calls short-circuit and raise CircuitOpen until cooldown
  - HALF_OPEN: one probe call gets through; if it succeeds we close,
              if it fails we re-open with the cooldown reset

The breaker is **per-key** (one breaker per provider, per tool, etc.)
managed by a global registry so independent call sites don't share
state by accident. Thread-safe.

Wire it as a decorator OR call ``call()`` manually:

    from maverick.circuit_breaker import get
    br = get("anthropic")
    try:
        result = br.call(lambda: client.complete(...))
    except CircuitOpen:
        # fast-fail; let the caller fall back to another provider

Defaults: 5 consecutive failures opens; 30-second cooldown.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, TypeVar

log = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpen(Exception):
    """Raised by ``call()`` when the breaker is open."""


T = TypeVar("T")


@dataclass
class _Stats:
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_at: float = 0.0
    opened_at: float = 0.0


class CircuitBreaker:
    """One breaker per key. Defaults are aggressive enough for live use."""

    def __init__(
        self,
        key: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.key = key
        self.failure_threshold = int(failure_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self._state = CircuitState.CLOSED
        self._stats = _Stats()
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._tick(now=time.time())
            return self._state

    def _tick(self, *, now: float) -> None:
        # If we're OPEN and cooldown has elapsed, drop to HALF_OPEN
        # so the very next call() probes the dependency.
        if (
            self._state is CircuitState.OPEN
            and now - self._stats.opened_at >= self.cooldown_seconds
        ):
            self._state = CircuitState.HALF_OPEN

    def record_success(self) -> None:
        with self._lock:
            self._stats.consecutive_failures = 0
            self._stats.total_successes += 1
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            now = time.time()
            self._stats.consecutive_failures += 1
            self._stats.total_failures += 1
            self._stats.last_failure_at = now
            if self._state is CircuitState.HALF_OPEN:
                # Probe failed → reopen with fresh cooldown.
                self._state = CircuitState.OPEN
                self._stats.opened_at = now
                return
            if self._stats.consecutive_failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._stats.opened_at = now

    def call(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` if allowed; raise ``CircuitOpen`` otherwise."""
        with self._lock:
            self._tick(now=time.time())
            if self._state is CircuitState.OPEN:
                raise CircuitOpen(
                    f"circuit {self.key!r} OPEN "
                    f"(opened {time.time() - self._stats.opened_at:.1f}s ago, "
                    f"cooldown {self.cooldown_seconds:.0f}s)"
                )
        try:
            result = fn()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def reset(self) -> None:
        with self._lock:
            self._stats = _Stats()
            self._state = CircuitState.CLOSED

    def snapshot(self) -> dict:
        with self._lock:
            self._tick(now=time.time())
            return {
                "key": self.key,
                "state": self._state.value,
                "consecutive_failures": self._stats.consecutive_failures,
                "total_failures": self._stats.total_failures,
                "total_successes": self._stats.total_successes,
                "last_failure_at": self._stats.last_failure_at,
                "opened_at": self._stats.opened_at,
            }


@dataclass
class _Registry:
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_REG = _Registry()


def get(
    key: str,
    *,
    failure_threshold: int = 5,
    cooldown_seconds: float = 30.0,
) -> CircuitBreaker:
    """Return the breaker for ``key``, creating it on first call."""
    with _REG.lock:
        br = _REG.breakers.get(key)
        if br is None:
            br = CircuitBreaker(
                key,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
            _REG.breakers[key] = br
    return br


def snapshot() -> list[dict]:
    """Snapshot every breaker for dashboards / debugging."""
    with _REG.lock:
        return [b.snapshot() for b in _REG.breakers.values()]


def reset_all() -> None:
    with _REG.lock:
        _REG.breakers.clear()


__all__ = [
    "CircuitBreaker", "CircuitOpen", "CircuitState",
    "get", "snapshot", "reset_all",
]
