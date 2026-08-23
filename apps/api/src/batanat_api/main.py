"""FastAPI application entrypoint.

Run locally with:  uv run fastapi dev src/batanat_api/main.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from batanat_api.agent import tools as _tools  # noqa: F401 — registers every tool
from batanat_api.agent.capabilities import audit_policy, validate_policy
from batanat_api.api.operations import router as operations_router
from batanat_api.auth.router import router as auth_router
from batanat_api.config import get_settings
from batanat_api.connections.router import router as connections_router
from batanat_api.connections.service import register_refreshers
from batanat_api.contracts.health import ErrorResponse
from batanat_api.core.db_bootstrap import ensure_database
from batanat_api.core.logging import configure_logging, get_logger
from batanat_api.core.middleware import RunContextMiddleware
from batanat_api.core.run_context import get_run_id
from batanat_api.db.mongo import ensure_indexes
from batanat_api.health.router import router as health_router
from batanat_api.version import __version__
from batanat_api.webhooks.gmail import router as gmail_webhook_router
from batanat_api.webhooks.whatsapp import router as whatsapp_webhook_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Fail the boot rather than serve with development credentials.
    settings.assert_safe_for_environment()

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

    # Mongo indexes are idempotent; creating them here means a fresh clone needs
    # no separate archive setup step.
    try:
        await ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        log.error("mongo.indexes.failed", error=f"{type(exc).__name__}: {exc}")

    # Teach the token vault how to refresh each provider's tokens.
    register_refreshers()

    # Fail fast if the capability table and the tool registry disagree. A typo
    # here would mean a run silently getting the wrong tools.
    validate_policy()
    log.info("agent.policy.validated", triggers=len(audit_policy()))

    if not settings.token_encryption_key:
        log.warning(
            "vault.master_key.missing",
            detail="TOKEN_ENCRYPTION_KEY is unset; connections cannot be stored.",
        )

    # Vector collection and cron jobs. Both tolerate being unavailable: the
    # health page is how the operator finds out, not a failed boot.
    try:
        from batanat_api.memory.store import ensure_collection

        await ensure_collection()
    except Exception as exc:  # noqa: BLE001
        log.error("memory.collection.failed", error=f"{type(exc).__name__}: {exc}")

    scheduler = None
    if settings.enable_scheduler:
        try:
            from batanat_api.scheduler.jobs import start_scheduler

            scheduler = start_scheduler()
        except Exception as exc:  # noqa: BLE001
            log.error("scheduler.start_failed", error=f"{type(exc).__name__}: {exc}")

    yield

    if scheduler is not None:
        from batanat_api.scheduler.jobs import stop_scheduler

        stop_scheduler()
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
    app.include_router(connections_router)
    app.include_router(whatsapp_webhook_router)
    app.include_router(gmail_webhook_router)
    app.include_router(auth_router)
    app.include_router(operations_router)

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
