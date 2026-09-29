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
    totals = work.groupby("engineer_id").agg(
        alert_count=("role", lambda r: int((r == "primary").sum())),
        escalations_received=("role", lambda r: int((r == "escalation").sum())),
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


def team_fairness(scope: Scope) -> dict:
    df = per_engineer_load(scope)
    g = round(gini(df["load"].to_numpy()), 3)
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
        "rotation_gini": round(gini(df["oncall_hours"].to_numpy()), 3) if scope.has_rotation else None,
        "confidence": "LOW" if low_confidence else "OK",
        "alert_count": alert_count,
        "engineers": engineers,
    }
