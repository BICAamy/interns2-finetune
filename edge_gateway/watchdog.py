"""Mac-local freshness checks; never compare monotonic clocks across hosts."""

from __future__ import annotations

import time
from typing import Callable

from .huayan.models import DatasheetSample


class StateWatchdog:
    def __init__(
        self, *, stale_ms: int = 250, clock_ns: Callable[[], int] = time.monotonic_ns
    ) -> None:
        if stale_ms <= 0:
            raise ValueError("stale_ms must be positive")
        self.stale_ms = stale_ms
        self._clock_ns = clock_ns

    def age_ms(self, sample: DatasheetSample) -> float:
        elapsed = self._clock_ns() - sample.received_monotonic_ns
        if elapsed < 0:
            raise ValueError("Mac monotonic clock moved backwards")
        return elapsed / 1_000_000

    def is_fresh(self, sample: DatasheetSample) -> bool:
        return self.age_ms(sample) <= self.stale_ms
