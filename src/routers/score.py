from fastapi import APIRouter, Query
from src.Scoring.fairness import team_fairness_score

router = APIRouter(prefix="/score")


@router.get("")
def score(days: int = Query(90, ge=1, le=365)):
    return team_fairness_score(days)
