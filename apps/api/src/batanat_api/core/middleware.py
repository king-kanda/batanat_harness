"""HTTP middleware: run-id correlation and request logging."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from batanat_api.core.logging import get_logger
from batanat_api.core.run_context import new_run_id, run_context

RUN_ID_HEADER = "x-run-id"

log = get_logger(__name__)


class RunContextMiddleware(BaseHTTPMiddleware):
    """Give every request a run id, log its outcome, echo the id back.

    An inbound `x-run-id` is honoured so a caller (the web app, a webhook
    relay) can correlate its own logs with ours.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        run_id = request.headers.get(RUN_ID_HEADER) or new_run_id()
        started = time.perf_counter()

        with run_context(run_id):
            try:
                response = await call_next(request)
            except Exception:
                log.exception(
                    "http.request.failed",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                raise

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            response.headers[RUN_ID_HEADER] = run_id
            return response
