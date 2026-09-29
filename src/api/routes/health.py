import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.api.deps import EngineDep
from src.db.session import check_connection
from src.schemas.scores import HealthStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthStatus, response_model_exclude_none=True,
            summary="Liveness: the process is up")
def live():
    return HealthStatus(status="ok")


@router.get("", response_model=HealthStatus, summary="Readiness: the database is reachable",
            responses={503: {"model": HealthStatus}})
def ready(engine: EngineDep):
    try:
        check_connection(engine)
    except SQLAlchemyError:
        # Details stay in the log; they can include the connection string
        logger.exception("Database health check failed")
        return JSONResponse(status_code=503,
                            content=HealthStatus(status="error", database="unavailable").model_dump())
    return HealthStatus(status="ok", database="ok")
