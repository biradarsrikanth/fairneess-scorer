"""Fairness and burnout per calendar week or month, from one load of the whole window.

Each period is scored exactly as a request for that period alone would be: its alerts, the escalations of
those alerts, and the shifts overlapping it."""
from datetime import datetime, time, timedelta
from typing import Literal

import pandas as pd

from src.services.burnout import burnout_scores
from src.services.fairness import team_fairness
from src.services.scope import ScoreWindow, build_scope

Granularity = Literal["week", "month"]
MAX_PERIODS = 120


def periods(window: ScoreWindow, granularity: Granularity) -> list[ScoreWindow]:
    """Calendar weeks (from Monday) or months in the window's timezone; the first and last may be partial."""
    result = []
    current = window.start
    while current < window.end:
        following = _next_boundary(current, granularity)
        result.append(ScoreWindow(start=current, end=min(following, window.end)))
        current = following
    return result


def _next_boundary(moment: datetime, granularity: Granularity) -> datetime:
    day = moment.date()
    if granularity == "week":
        following = day + timedelta(days=7 - day.weekday())
    else:
        following = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    return datetime.combine(following, time.min, moment.tzinfo)


def score_trend(alerts: pd.DataFrame, engineers: pd.DataFrame, assignments: pd.DataFrame,
                oncall: pd.DataFrame, window: ScoreWindow, team: str | None,
                granularity: Granularity) -> list[dict]:
    rows = []
    for period in periods(window, granularity):
        start, end = period.utc_start, period.utc_end
        period_alerts = alerts[(alerts["triggered_at"] >= start) & (alerts["triggered_at"] < end)]
        period_assignments = assignments[assignments["alert_id"].isin(period_alerts["alert_id"])]
        period_oncall = oncall[(oncall["starts_at"] < end) & (oncall["ends_at"] > start)]
        scope = build_scope(period_alerts, engineers, period_assignments, period_oncall, period, team)

        fairness = team_fairness(scope)
        burnout = burnout_scores(scope)
        scores = [b["score"] for b in burnout]
        rows.append({
            "start": period.start,
            "end": period.end,
            "alert_count": fairness["alert_count"],
            "gini": fairness["gini"],
            "label": fairness["label"],
            "confidence": fairness["confidence"],
            "average_burnout": round(sum(scores) / len(scores), 1) if scores else None,
            "high_risk_count": sum(1 for b in burnout if b["risk"] == "HIGH"),
        })
    return rows
