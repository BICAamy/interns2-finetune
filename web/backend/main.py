"""FastAPI application, React host, simulation proxy, local ASR, and gestures."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .gesture.routes import router as gesture_router
from .runtime import WebRuntime
from .manual_control import router as manual_router
from .random_commands import router as random_commands_router
from .sessions import SessionConflict, SessionNotFound
from .websocket import router as websocket_router


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_STATIC_DIR = PROJECT_ROOT / "web" / "frontend" / "dist"
INSIDE_STATIC_DIR = PROJECT_ROOT / "web_inside" / "frontend" / "dist"
ROBOT_MODEL_DIR = PROJECT_ROOT / "third_party" / "elfin_model" / "model" / "485" / "elfin5"
DEFAULT_STATIC_DIR = DEMO_STATIC_DIR
WEB_VARIANTS = frozenset({"web", "web_inside", "both"})


def _normalize_frontend_variant(value: str | None) -> str:
    selected = (value or os.getenv("INTERNS2_WEB_VARIANT", "web")).strip()
    if selected not in WEB_VARIANTS:
        choices = "|".join(sorted(WEB_VARIANTS))
        raise ValueError(
            f"INTERNS2_WEB_VARIANT must be one of {choices}; got {selected!r}"
        )
    return selected


def _frontend_not_built(static_root: Path) -> JSONResponse:
    try:
        display_path = static_root.relative_to(PROJECT_ROOT)
    except ValueError:
        display_path = static_root
    return JSONResponse(
        status_code=503,
        content={
            "code": "FRONTEND_NOT_BUILT",
            "message": f"React assets are missing; build {display_path.parent} first",
        },
    )


def create_app(
    runtime: WebRuntime | None = None,
    *,
    static_dir: str | Path | None = None,
    frontend_variant: str | None = None,
    demo_static_dir: str | Path | None = None,
    inside_static_dir: str | Path | None = None,
) -> FastAPI:
    provided_runtime = runtime
    selected_variant = _normalize_frontend_variant(frontend_variant)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        selected = provided_runtime or WebRuntime.from_env()
        app.state.runtime = selected
        try:
            yield
        finally:
            try:
                if hasattr(selected, 'manual'):
                    await selected.manual.shutdown()
            finally:
                if provided_runtime is None:
                    selected.close()

    app = FastAPI(
        title="InternS2 Surgical Navigation Web Console",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.web_variant = selected_variant

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
    app.include_router(manual_router)
    app.include_router(random_commands_router)
    app.include_router(gesture_router)
    app.include_router(websocket_router)

    # Static geometry is downloaded once by the browser and then rendered by
    # the user's GPU.  No robot image frames pass through this route.
    if ROBOT_MODEL_DIR.is_dir():
        app.mount(
            "/robot-assets/e05",
            StaticFiles(directory=ROBOT_MODEL_DIR),
            name="e05-browser-model",
        )

    demo_root = Path(demo_static_dir) if demo_static_dir is not None else DEMO_STATIC_DIR
    inside_root = (
        Path(inside_static_dir) if inside_static_dir is not None else INSIDE_STATIC_DIR
    )
    if static_dir is not None:
        root_static = Path(static_dir)
    elif selected_variant == "web_inside":
        root_static = inside_root
    else:
        root_static = demo_root

    root_assets = root_static / "assets"
    root_index = root_static / "index.html"
    if root_assets.is_dir():
        app.mount("/assets", StaticFiles(directory=root_assets), name="frontend-assets")

    if selected_variant == "both":
        inside_assets = inside_root / "assets"
        inside_index = inside_root / "index.html"
        if inside_assets.is_dir():
            app.mount(
                "/inside/assets",
                StaticFiles(directory=inside_assets),
                name="inside-frontend-assets",
            )

        @app.get("/inside", include_in_schema=False)
        async def inside_redirect():
            return RedirectResponse(url="/inside/", status_code=307)

        @app.get("/inside/{frontend_path:path}", include_in_schema=False)
        async def inside_frontend(frontend_path: str):
            if inside_index.is_file():
                return FileResponse(inside_index)
            return _frontend_not_built(inside_root)

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def frontend(frontend_path: str):
        if frontend_path.startswith(("api/", "ws/")):
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": "route not found"},
            )
        if root_index.is_file():
            return FileResponse(root_index)
        return _frontend_not_built(root_static)

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
