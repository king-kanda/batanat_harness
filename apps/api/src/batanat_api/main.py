"""FastAPI application entrypoint.

Run locally with:  uv run fastapi dev src/batanat_api/main.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from batanat_api.config import get_settings
from batanat_api.contracts.health import ErrorResponse
from batanat_api.core.db_bootstrap import ensure_database
from batanat_api.core.logging import configure_logging, get_logger
from batanat_api.core.middleware import RunContextMiddleware
from batanat_api.core.run_context import get_run_id
from batanat_api.health.router import router as health_router
from batanat_api.version import __version__

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "api.startup",
        version=__version__,
        app_env=settings.app_env,
        demo_mode=settings.demo_mode,
        kill_switch=settings.kill_switch,
    )

    # Provision the database on first run. A failure here is not fatal: the app
    # still serves the health page, which is where the operator finds out why.
    try:
        await ensure_database(settings.database_url)
    except Exception as exc:  # noqa: BLE001
        log.error("db.bootstrap.failed", error=f"{type(exc).__name__}: {exc}")

    yield
    log.info("api.shutdown", version=__version__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Batanat Agentic Harness API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
    )

    app.add_middleware(RunContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-run-id"],
    )

    app.include_router(health_router)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Never leak an internal error to the client; the run id links to the log."""
        log.exception("api.unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="An unexpected error occurred.",
                run_id=get_run_id(),
            ).model_dump(),
        )

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"service": "batanat-api", "version": __version__, "health": "/api/health"}

    return app


app = create_app()
