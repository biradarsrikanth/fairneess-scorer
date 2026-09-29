import pandas as pd

from src.services.fairness import per_engineer_load
from src.services.model import (
    BURNOUT_FULL_CONFIDENCE_PAGES,
    BURNOUT_WEIGHTS,
    TREND_WINDOW_DAYS,
    risk_label,
)
from src.services.scope import Scope


def _trend_ratio(triggered: pd.Series, end: pd.Timestamp) -> float:
    recent_start = end - pd.Timedelta(days=TREND_WINDOW_DAYS)
    prior_start = end - pd.Timedelta(days=2 * TREND_WINDOW_DAYS)
    recent = int(((triggered >= recent_start) & (triggered < end)).sum())
    prior = int(((triggered >= prior_start) & (triggered < recent_start)).sum())
    # +1 smoothing: no data at all gives 1.0 (flat), and 0 -> 1 page isn't an infinite increase
    return (recent + 1) / (prior + 1)


def burnout_scores(scope: Scope) -> list[dict]:
    loads = per_engineer_load(scope)
    mean_load = float(loads["load"].mean()) if len(loads) else 0.0
    by_engineer = dict(tuple(scope.work.groupby("engineer_id")))
    empty = scope.work.iloc[0:0]
    end = scope.window.utc_end

    results = []
    for row in loads.to_dict(orient="records"):
        pages = by_engineer.get(row["engineer_id"], empty)
        n = len(pages)
        exposure = float(pages["exposure"].mean()) if n else 0.0
        relative_load = min(1.0, float(row["load"]) / (2 * mean_load)) if mean_load > 0 else 0.0
        ratio = _trend_ratio(pages["triggered_at"], end)
        trend = min(1.0, max(0.0, ratio - 1))
        confidence = min(1.0, n / BURNOUT_FULL_CONFIDENCE_PAGES)

        raw = (BURNOUT_WEIGHTS["exposure"] * exposure
               + BURNOUT_WEIGHTS["relative_load"] * relative_load
               + BURNOUT_WEIGHTS["trend"] * trend)
        score = round(raw * confidence, 1)
        ack = pages["ack_minutes"].dropna()

        def pct(flag: str, pages: pd.DataFrame = pages, n: int = n) -> float:
            return round(float(pages[flag].mean()) * 100, 1) if n else 0.0

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
            "median_ack_minutes": round(float(ack.median()), 1) if len(ack) else None,
            "oncall_hours": round(float(row["oncall_hours"]), 1) if scope.has_rotation else None,
            "components": {
                "exposure": round(exposure, 3),
                "relative_load": round(relative_load, 3),
                "trend": round(trend, 3),
            },
        })
    return sorted(results, key=lambda r: (-r["score"], r["name"]))
