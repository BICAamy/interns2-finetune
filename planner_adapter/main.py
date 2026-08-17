"""FastAPI entry point for the standalone planner-adapter service."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from surgical_contracts import (
    ErrorCode,
    ErrorResponse,
    PlannerHealth,
    PlanPunctureRequest,
    PlanPunctureResult,
)

from .config import PlannerAdapterSettings
from .providers import PlannerProvider
from .service import PlannerAdapter


def _error_payload(
    code: ErrorCode,
    message: str,
    *,
    details: dict | None = None,
) -> dict:
    return ErrorResponse(
        code=code,
        message=message,
        details=details or {},
    ).model_dump(mode="json")


def create_app(
    settings: PlannerAdapterSettings | None = None,
    provider: PlannerProvider | None = None,
) -> FastAPI:
    configured = settings or PlannerAdapterSettings.from_env()
    adapter = PlannerAdapter(configured, provider)
    app = FastAPI(
        title="InternS2 Puncture Planner Adapter",
        version="1.0.0",
    )
    app.state.planner_adapter = adapter

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                ErrorCode.INVALID_COMMAND_SCHEMA,
                "Request did not match the planner API contract",
                details={"errors": jsonable_encoder(error.errors())},
            ),
        )

    @app.get("/health", response_model=PlannerHealth)
    def health() -> PlannerHealth:
        return adapter.health()

    @app.post(
        "/v1/plan",
        response_model=PlanPunctureResult,
        responses={503: {"model": PlanPunctureResult}},
    )
    def plan(request: PlanPunctureRequest):
        result = adapter.plan(request)
        if adapter.is_unavailable(result):
            return JSONResponse(
                status_code=503,
                content=adapter.result_payload(result),
            )
        return result

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = app.state.planner_adapter.settings
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        workers=1,
    )


if __name__ == "__main__":
    main()
