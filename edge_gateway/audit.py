"""Bounded, secret-free local audit output for the observe-only gateway."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time

_SAFE_FIELDS = frozenset({
    "gateway_id", "session_id", "device_sn", "sequence", "event",
    "reason", "fsm_code", "vendor_error_code", "freshness", "mode",
})


class EdgeAudit:
    def __init__(self, path: str | Path) -> None:
        selected = Path(path)
        selected.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"edge-audit-{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        handler = RotatingFileHandler(selected, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        self._handler = handler

    def record(self, event: str, **fields: object) -> None:
        if not event or len(event) > 64:
            raise ValueError("invalid audit event")
        if any(key not in _SAFE_FIELDS for key in fields):
            raise ValueError("audit field is not allowlisted")
        message = {"at_ms": time.time_ns() // 1_000_000, "event": event}
        message.update({key: str(value)[:128] for key, value in fields.items()})
        self._logger.info(json.dumps(message, ensure_ascii=False, separators=(",", ":")))

    def close(self) -> None:
        self._logger.removeHandler(self._handler)
        self._handler.close()
