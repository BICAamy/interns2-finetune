"""FastAPI application and React static-file host for Step 11."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .runtime import WebRuntime
from .sessions import SessionConflict, SessionNotFound
from .websocket import router as websocket_router


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIC_DIR = PROJECT_ROOT / "web" / "frontend" / "dist"


def create_app(
    runtime: WebRuntime | None = None,
    *,
    static_dir: str | Path | None = None,
) -> FastAPI:
    provided_runtime = runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        selected = provided_runtime or WebRuntime.from_env()
        app.state.runtime = selected
        try:
            yield
        finally:
            if provided_runtime is None:
                selected.close()

    app = FastAPI(
        title="InternS2 Surgical Navigation Web Console",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.exception_handler(SessionNotFound)
    async def session_not_found(_request: Request, error: SessionNotFound):
        return JSONResponse(
            status_code=404,
            content={
                "code": "SESSION_NOT_FOUND",
                "message": f"unknown session: {error.args[0]}",
                "details": {},
            },
        )

    @app.exception_handler(SessionConflict)
    async def session_conflict(_request: Request, error: SessionConflict):
        return JSONResponse(
            status_code=409,
            content={
                "code": "SESSION_CONFLICT",
                "message": str(error),
                "details": {},
            },
        )

    app.include_router(api_router)
    app.include_router(websocket_router)

    selected_static = Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR
    assets_dir = selected_static / "assets"
    index_file = selected_static / "index.html"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def frontend(frontend_path: str):
        if frontend_path.startswith(("api/", "ws/")):
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": "route not found"},
            )
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse(
            status_code=503,
            content={
                "code": "FRONTEND_NOT_BUILT",
                "message": "React assets are missing; build web/frontend first",
            },
        )

    return app


app = create_app()


def main() -> None:
    import os
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("AGENT_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_WEB_PORT", "8000")),
        log_level=os.getenv("AGENT_WEB_LOG_LEVEL", "info"),
        workers=1,
    )


if __name__ == "__main__":
    main()
