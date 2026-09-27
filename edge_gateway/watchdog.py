"""判断“真机状态是不是还新鲜”，以及“机械臂自己上报的时间戳是不是正常往前走”"""

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
        self.stale_ms = stale_ms # 允许这一帧能老多长时间
        self._clock_ns = clock_ns

    def age_ms(self, sample: DatasheetSample) -> float:
        elapsed = self._clock_ns() - sample.received_monotonic_ns
        if elapsed < 0:
            raise ValueError("Mac monotonic clock moved backwards")
        return elapsed / 1_000_000

    def is_fresh(self, sample: DatasheetSample) -> bool:
        return self.age_ms(sample) <= self.stale_ms


class SourceStampWatchdog:
    """这里检查DataSheet 自己带的 source_timestamp_ms 有没有正常变化
    """

    def __init__(self, *, stale_ms: int) -> None:
        if stale_ms <= 0:
            raise ValueError("stale_ms must be positive")
        self._stale_ns = stale_ms * 1_000_000
        self._last_stamp_ms: int | None = None
        self._last_advance_ns: int | None = None

    def observe(self, sample: DatasheetSample) -> None:
        stamp_ms = sample.source_timestamp_ms
        received_ns = sample.received_monotonic_ns
        if self._last_stamp_ms is not None and stamp_ms < self._last_stamp_ms:
            raise ValueError("DataSheet source timestamp moved backwards")
        if self._last_stamp_ms is None or stamp_ms > self._last_stamp_ms:
            self._last_stamp_ms = stamp_ms
            self._last_advance_ns = received_ns
        elif received_ns - self._last_advance_ns > self._stale_ns:
            raise ValueError("DataSheet source timestamp stopped advancing")
