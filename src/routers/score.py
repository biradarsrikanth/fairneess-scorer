from fastapi import APIRouter, Query,HTTPException
from src.Scoring.fairness import team_fairness_score
from src.Scoring.burnout import burnout_scores
from src.Scoring.timeofday import timeofday_heatmap

router = APIRouter(prefix="/score")


@router.get("")
def score(days: int = Query(365, ge=1, le=1000)):
    return team_fairness_score(days)

@router.get("/burnout")
def burnout(days: int = Query(365, ge=1, le=1000)):
    return burnout_scores(days)

@router.get("/timeofday")
def timeofday(days: int = Query(365, ge=1, le=1000)):
    return timeofday_heatmap(days)

@router.get("/engineer/{name}")
def engineer_detail(name: str, days: int = Query(365, ge=1, le=1000)):
    burnout = next((b for b in burnout_scores(days) if b["engineer"] == name), None)
    if burnout is None:
        raise HTTPException(status_code=404, detail=f"No data for engineer '{name}'")
    fairness = team_fairness_score(days)
    return {
        "engineer": name,
        "burnout": burnout,
        "team_share_pct": fairness["engineer_share_pct"].get(name),
    }
