import math
from collections.abc import Hashable
from typing import Any

import pandas as pd

from src.services.fairness import per_engineer_load
from src.services.model import (
    BURNOUT_FULL_CONFIDENCE_PAGES,
    BURNOUT_WEIGHTS,
    TREND_WINDOW_DAYS,
    risk_label,
)
from src.services.scope import Scope


def _per_engineer_pages(work: pd.DataFrame, end: pd.Timestamp) -> dict[Hashable, dict[Hashable, Any]]:
    """Each engineer's page figures in one grouped pass (looping over engineers was most of the trend's time):
    pages, mean exposure, the night/evening/weekend shares, pages in the last and the previous
    TREND_WINDOW_DAYS, and the median time to acknowledge."""
    recent_start = end - pd.Timedelta(days=TREND_WINDOW_DAYS)
    prior_start = end - pd.Timedelta(days=2 * TREND_WINDOW_DAYS)
    triggered = work["triggered_at"]
    grouped = work.assign(
        recent=(triggered >= recent_start) & (triggered < end),
        prior=(triggered >= prior_start) & (triggered < recent_start),
    ).groupby("engineer_id").agg(
        pages=("alert_id", "size"),
        exposure=("exposure", "mean"),
        night=("night", "mean"),
        evening=("evening", "mean"),
        weekend=("weekend", "mean"),
        recent=("recent", "sum"),
        prior=("prior", "sum"),
        median_ack=("ack_minutes", "median"),
    )
    return grouped.to_dict(orient="index")


# An engineer with no pages in the window
NO_PAGES: dict[Hashable, Any] = {"pages": 0, "exposure": 0.0, "night": 0.0, "evening": 0.0, "weekend": 0.0,
                                 "recent": 0, "prior": 0, "median_ack": math.nan}


def burnout_scores(scope: Scope) -> list[dict]:
    loads = per_engineer_load(scope)
    # Load is compared with the engineer's own team: across teams it would mostly measure team volume
    team_mean_load = loads.groupby("team")["load"].transform("mean") if len(loads) else loads["load"]
    loads = loads.assign(team_mean_load=team_mean_load)
    pages_by_engineer = _per_engineer_pages(scope.work, scope.window.utc_end)

    results = []
    for row in loads.to_dict(orient="records"):
        pages = pages_by_engineer.get(row["engineer_id"], NO_PAGES)
        n = int(pages["pages"])
        exposure = float(pages["exposure"]) if n else 0.0
        mean_load = float(row["team_mean_load"])
        relative_load = min(1.0, float(row["load"]) / (2 * mean_load)) if mean_load > 0 else 0.0
        # +1 smoothing: no data at all gives 1.0 (flat), and 0 -> 1 page isn't an infinite increase
        ratio = (int(pages["recent"]) + 1) / (int(pages["prior"]) + 1)
        trend = min(1.0, max(0.0, ratio - 1))
        confidence = min(1.0, n / BURNOUT_FULL_CONFIDENCE_PAGES)

        raw = (BURNOUT_WEIGHTS["exposure"] * exposure
               + BURNOUT_WEIGHTS["relative_load"] * relative_load
               + BURNOUT_WEIGHTS["trend"] * trend)
        score = round(raw * confidence, 1)
        median_ack = float(pages["median_ack"])

        def pct(flag: str, pages: dict[Hashable, Any] = pages, n: int = n) -> float:
            return round(float(pages[flag]) * 100, 1) if n else 0.0

        results.append({
            "engineer_id": int(row["engineer_id"]),
            "name": row["name"],
            "team": row["team"],
            "alert_count": int(row["alert_count"]),
            "escalations_received": int(row["escalations_received"]),
            "score": score,
            "risk": risk_label(score),
            "night_pct": pct("night"),
            "evening_pct": pct("evening"),
            "weekend_pct": pct("weekend"),
            "trend_ratio": round(ratio, 2),
            "median_ack_minutes": None if math.isnan(median_ack) else round(median_ack, 1),
            "oncall_hours": round(float(row["oncall_hours"]), 1) if scope.has_rotation else None,
            "components": {
                "exposure": round(exposure, 3),
                "relative_load": round(relative_load, 3),
                "trend": round(trend, 3),
            },
        })
    return sorted(results, key=lambda r: (-r["score"], r["name"]))
