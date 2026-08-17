"""Stable parsing failures returned before any robot tool can run."""

from __future__ import annotations

from typing import Any

from surgical_contracts import ErrorCode, ErrorResponse


class CommandParsingError(RuntimeError):
    """An InternS2 request or output could not produce a safe command."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return ErrorResponse(
            code=self.error_code,
            message=str(self),
            details=self.details,
        ).model_dump(mode="json")
