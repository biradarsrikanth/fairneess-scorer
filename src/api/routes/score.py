from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from src.api.deps import LoaderDep, ScopeDep, SettingsDep, WindowDep, load_scope
from src.core.security import require_api_key
from src.schemas.scores import (
    BurnoutReport,
    EngineerReport,
    FairnessReport,
    TimeOfDayReport,
)
from src.services.burnout import burnout_scores
from src.services.fairness import team_fairness
from src.services.scope import Scope, ScoreWindow
from src.services.timeofday import timeofday_counts

router = APIRouter(prefix="/v1/scores", tags=["scores"], dependencies=[Depends(require_api_key)],
                   responses={401: {"description": "Missing or invalid X-API-Key"}})


def _window(window: ScoreWindow, timezone: str) -> dict:
    return {"start": window.start, "end": window.end, "timezone": timezone}


@router.get("/fairness", response_model=FairnessReport, summary="Fairness (Gini) of on-call load")
def fairness(scope: ScopeDep, settings: SettingsDep):
    return {"window": _window(scope.window, settings.team_timezone), **team_fairness(scope)}


@router.get("/burnout", response_model=BurnoutReport, summary="Burnout risk per engineer")
def burnout(scope: ScopeDep, settings: SettingsDep):
    return {"window": _window(scope.window, settings.team_timezone), "team": scope.team,
            "engineers": burnout_scores(scope)}


@router.get("/timeofday", response_model=TimeOfDayReport, summary="Alert counts by time of day")
def timeofday(scope: ScopeDep, settings: SettingsDep):
    return {"window": _window(scope.window, settings.team_timezone), "team": scope.team,
            "engineers": timeofday_counts(scope)}


@router.get("/engineers/{engineer_id}", response_model=EngineerReport,
            summary="All scores for one engineer, relative to their team",
            responses={404: {"description": "Unknown engineer"}})
def engineer(engineer_id: Annotated[int, Path(ge=1)], window: WindowDep, loader: LoaderDep,
             settings: SettingsDep):
    engineers = loader.engineers()
    match = engineers[engineers["engineer_id"] == engineer_id]
    if match.empty:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Engineer {engineer_id} not found")
    info = match.iloc[0]

    # Score against the engineer's own team; include them even if inactive or off the rotation
    scope: Scope = load_scope(loader, window, info["team"], include_engineer_id=engineer_id)

    burnout = next(b for b in burnout_scores(scope) if b["engineer_id"] == engineer_id)
    share = next(e["share_pct"] for e in team_fairness(scope)["engineers"] if e["engineer_id"] == engineer_id)
    tod = next(t for t in timeofday_counts(scope) if t["engineer_id"] == engineer_id)
    return {
        "window": _window(window, settings.team_timezone),
        "engineer": {"engineer_id": engineer_id, "name": info["name"], "team": info["team"]},
        "active": bool(info["active"]),
        "burnout": burnout,
        "team_share_pct": share,
        "time_of_day": tod,
    }
