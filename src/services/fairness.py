import math

import numpy as np
import pandas as pd

from src.services.model import FAIRNESS_MIN_ALERTS, FAIRNESS_MIN_ENGINEERS, fairness_label
from src.services.scope import Scope


def gini(values: np.ndarray) -> float:
    values = np.sort(np.asarray(values, dtype=float))
    n = values.shape[0]
    if n == 0 or values.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * values) - (n + 1) * np.sum(values)) / (n * np.sum(values)))


def per_engineer_load(scope: Scope) -> pd.DataFrame:
    """One row per engineer in scope: alert_count (first pages), escalations_received, load, share_pct,
    oncall_hours and load_per_oncall_hour."""
    work = scope.work
    # Boolean columns summed per engineer: much faster than a Python function per group
    totals = work.assign(
        is_primary=work["role"] == "primary",
        is_escalation=work["role"] == "escalation",
    ).groupby("engineer_id").agg(
        alert_count=("is_primary", "sum"),
        escalations_received=("is_escalation", "sum"),
        load=("load", "sum"),
    )
    df = scope.engineers.merge(totals, on="engineer_id", how="left")
    df = df.fillna({"alert_count": 0, "escalations_received": 0, "load": 0.0})
    df = df.astype({"alert_count": int, "escalations_received": int, "load": float})
    total = df["load"].sum()
    df["share_pct"] = (df["load"] / total * 100).round(1) if total else 0.0
    df["load_per_oncall_hour"] = [
        round(load / hours, 3) if hours > 0 else None
        for load, hours in zip(df["load"], df["oncall_hours"], strict=True)
    ]
    return df


def _optional(value: float) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _by_team(df: pd.DataFrame) -> list[dict]:
    """Each team's own fairness: Gini of load, and of primary on-call hours when it has shifts."""
    teams = []
    for name, group in df.groupby("team", sort=True):
        g = gini(group["load"].to_numpy())
        hours = group["oncall_hours"].to_numpy()
        teams.append({
            "team": name,
            "gini": round(g, 3),
            "label": fairness_label(g),
            "rotation_gini": round(gini(hours), 3) if hours.sum() > 0 else None,
            "alert_count": int(group["alert_count"].sum()),
            "engineer_count": len(group),
            "oncall_hours": float(hours.sum()),
        })
    return teams


def _weighted(values: list[tuple[float, float]]) -> float:
    total = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total if total else 0.0


def team_fairness(scope: Scope) -> dict:
    """How evenly load falls on the engineers of a team. For several teams (scope.team is None), each team
    is scored on its own and the Gini is the average of theirs, weighted by alerts: pooling every engineer
    together would read differences in team size and volume as unfairness."""
    df = per_engineer_load(scope)
    teams = _by_team(df)
    if len(teams) <= 1:
        g = gini(df["load"].to_numpy())
        rotation = gini(df["oncall_hours"].to_numpy())
    else:
        g = _weighted([(t["gini"], t["alert_count"]) for t in teams])
        rotation = _weighted([(t["rotation_gini"], t["oncall_hours"]) for t in teams
                              if t["rotation_gini"] is not None])
    g = round(g, 3)
    alert_count = int(df["alert_count"].sum())
    low_confidence = alert_count < FAIRNESS_MIN_ALERTS or len(df) < FAIRNESS_MIN_ENGINEERS
    engineers = [
        {
            "engineer_id": int(row["engineer_id"]),
            "name": row["name"],
            "team": row["team"],
            "alert_count": int(row["alert_count"]),
            "escalations_received": int(row["escalations_received"]),
            "load": round(float(row["load"]), 2),
            "share_pct": float(row["share_pct"]),
            "oncall_hours": round(float(row["oncall_hours"]), 1) if scope.has_rotation else None,
            "load_per_oncall_hour": _optional(row["load_per_oncall_hour"]),
        }
        for row in df.sort_values(["load", "name"], ascending=[False, True]).to_dict(orient="records")
    ]
    return {
        "team": scope.team,
        "basis": "ONCALL_ROTATION" if scope.has_rotation else "ACTIVE_ENGINEERS",
        "gini": g,
        "label": fairness_label(g),
        "rotation_gini": round(rotation, 3) if scope.has_rotation else None,
        "confidence": "LOW" if low_confidence else "OK",
        "alert_count": alert_count,
        "engineers": engineers,
        "teams": [{key: value for key, value in t.items() if key != "oncall_hours"} for t in teams],
    }
