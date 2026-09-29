from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import Engine

from src.core.config import Settings, get_settings
from src.db.loader import DataLoader
from src.db.session import get_engine
from src.services.scope import Scope, ScoreWindow, build_scope

DEFAULT_DAYS = 365
MAX_DAYS = 3650

SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]


@lru_cache
def get_data_loader() -> DataLoader:
    settings = get_settings()
    return DataLoader(get_engine(), settings.cache_ttl_seconds)


LoaderDep = Annotated[DataLoader, Depends(get_data_loader)]


def get_window(
    settings: SettingsDep,
    days: Annotated[int | None, Query(ge=1, le=MAX_DAYS,
                                      description=f"Days before `end` (default {DEFAULT_DAYS})")] = None,
    start: Annotated[date | None, Query(description="First day, inclusive (team timezone)")] = None,
    end: Annotated[date | None, Query(description="Last day, inclusive (default: now)")] = None,
) -> ScoreWindow:
    tz = settings.timezone
    if start is not None and days is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use either `start` or `days`, not both")

    if end is not None:
        end_dt = datetime.combine(end + timedelta(days=1), time.min, tz)
    else:
        # Round "now" up to the minute so repeated requests share a cache entry
        end_dt = datetime.now(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    start_dt = (datetime.combine(start, time.min, tz) if start is not None
                else end_dt - timedelta(days=days or DEFAULT_DAYS))

    if start_dt >= end_dt:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`start` must be before `end`")
    if end_dt - start_dt > timedelta(days=MAX_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Window is longer than {MAX_DAYS} days")
    return ScoreWindow(start=start_dt, end=end_dt)


WindowDep = Annotated[ScoreWindow, Depends(get_window)]
Team = Annotated[str | None, Query(max_length=255, description="Only score this team")]


def load_scope(loader: DataLoader, window: ScoreWindow, team: str | None,
               include_engineer_id: int | None = None) -> Scope:
    return build_scope(loader.alerts(window.start, window.end), loader.engineers(),
                       loader.assignments(window.start, window.end),
                       loader.oncall(window.start, window.end),
                       window, team, include_engineer_id)


def get_scope(window: WindowDep, loader: LoaderDep, team: Team = None) -> Scope:
    return load_scope(loader, window, team)


ScopeDep = Annotated[Scope, Depends(get_scope)]
