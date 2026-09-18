"""Localhost-only DataSheet reader with latest-wins poses and lossless alerts."""

from __future__ import annotations

import math
import socket

from .command_client import _loopback_host
from .datasheet_codec import DatasheetFrameDecoder
from .models import DatasheetSample, ProtocolError


class DatasheetClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        byte_order: str,
        timeout_s: float = 1.0,
        max_events: int = 256,
    ) -> None:
        self.host = _loopback_host(host)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port is out of range")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.port = port
        self.timeout_s = timeout_s
        self.max_events = max_events
        self._byte_order = byte_order
        self._decoder = DatasheetFrameDecoder(byte_order=byte_order)
        self._socket: socket.socket | None = None
        self.latest: DatasheetSample | None = None
        self._events: list[DatasheetSample] = []
        self.received_samples = 0
        self.last_batch: tuple[DatasheetSample, ...] = ()

    def connect(self) -> None:
        if self._socket is not None:
            raise RuntimeError("already connected")
        self._socket = socket.create_connection((self.host, self.port), self.timeout_s)
        self._socket.settimeout(self.timeout_s)
        self._decoder = DatasheetFrameDecoder(byte_order=self._byte_order)
        self.latest = None
        self._events.clear()
        self.received_samples = 0
        self.last_batch = ()

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
        self._socket = None
        self._decoder = DatasheetFrameDecoder(byte_order=self._byte_order)
        self.latest = None
        self.last_batch = ()

    @property
    def pending_events(self) -> int:
        return len(self._events)

    def poll(self) -> DatasheetSample | None:
        if self._socket is None:
            raise RuntimeError("DataSheet socket is not connected")
        try:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ConnectionError("DataSheet stream closed")
            samples = self._decoder.feed(chunk)
            self.last_batch = tuple(samples)
            self.received_samples += len(samples)
            for sample in samples:
                previous = self.latest
                changed = previous is None or (
                    previous.fsm_code,
                    previous.enabled,
                    previous.moving,
                    previous.paused,
                    previous.error_code,
                    previous.error_axis,
                ) != (
                    sample.fsm_code,
                    sample.enabled,
                    sample.moving,
                    sample.paused,
                    sample.error_code,
                    sample.error_axis,
                )
                if changed or sample.error_code or any(sample.axis_error_codes):
                    if len(self._events) >= self.max_events:
                        raise ProtocolError("DataSheet event queue full; refusing to drop alerts")
                    self._events.append(sample)
                self.latest = sample
            return self.latest if samples else None
        except (OSError, ConnectionError, ProtocolError):
            self.close()
            raise

    def drain_events(self) -> list[DatasheetSample]:
        events, self._events = self._events, []
        return events

    def __enter__(self) -> "DatasheetClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
