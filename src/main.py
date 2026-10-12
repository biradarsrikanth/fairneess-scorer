import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.errors import register_error_handlers
from src.api.routes import health, score
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.middleware import RequestContextMiddleware
from src.db.session import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # fail fast on missing or invalid configuration
    configure_logging(settings.log_level, settings.log_format)
    logger.info("Fairness Scorer starting", extra={"timezone": settings.team_timezone,
                                                    "cache_ttl_seconds": settings.cache_ttl_seconds})
    yield
    dispose_engine()


app = FastAPI(
    title="Fairness Scorer",
    version="1.0.0",
    description="Scores on-call fairness and burnout from PagerDuty alerts. "
                "Internal service: called by the Fairness-Checker gateway only.",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
Instrumentator(excluded_handlers=["/metrics", "/health.*"]).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False)


register_error_handlers(app)


@app.get("/", include_in_schema=False)
def root():
    return {"message": "Welcome to the Fairness Scorer API!"}


app.include_router(health.router)
app.include_router(score.router)
