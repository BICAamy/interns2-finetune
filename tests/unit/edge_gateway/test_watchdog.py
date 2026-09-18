from __future__ import annotations

import pytest

from edge_gateway.watchdog import StateWatchdog
from edge_gateway.huayan.datasheet_codec import DatasheetFrameDecoder
from tests.fakes.huayan_controller import datasheet_document, datasheet_frame


def test_freshness_uses_mac_monotonic_not_wall_clock() -> None:
    sample = DatasheetFrameDecoder(byte_order="little").feed(
        datasheet_frame(datasheet_document())
    )[0]
    sample = sample.__class__(**{**sample.__dict__, "received_wall_ms": 1})
    now = [sample.received_monotonic_ns + 10_000_000]
    watchdog = StateWatchdog(stale_ms=250, clock_ns=lambda: now[0])
    assert watchdog.age_ms(sample) == 10
    assert watchdog.is_fresh(sample)
    now[0] += 300_000_000
    assert not watchdog.is_fresh(sample)
    now[0] = sample.received_monotonic_ns - 1
    with pytest.raises(ValueError, match="backwards"):
        watchdog.age_ms(sample)
