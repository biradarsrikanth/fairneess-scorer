import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
# Only accept ids that are safe to write to logs; anything else gets a fresh id
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

logger = logging.getLogger("src.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id (reusing the gateway's), logs one line per request and echoes the id back."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            if not request.url.path.startswith(("/health", "/metrics")):
                logger.info("%s %s %s", request.method, request.url.path, status_code, extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                })
            request_id_var.reset(token)
