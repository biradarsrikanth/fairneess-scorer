"""Scoring constants and per-alert features. See docs/SCORING.md before changing any value here."""
import numpy as np
import pandas as pd

SEVERITY_WEIGHTS = {"P1": 4.0, "P2": 3.0, "P3": 2.0, "P4": 1.0, "P5": 1.0}
DEFAULT_SEVERITY_WEIGHT = 2.0
MAX_DURATION_HOURS = 4.0

NIGHT_MULTIPLIER = 0.5
EVENING_MULTIPLIER = 0.25
WEEKEND_MULTIPLIER = 0.25

NIGHT_EXPOSURE = 1.0
EVENING_EXPOSURE = 0.5
WEEKEND_EXPOSURE = 0.5

# Someone escalated to (or handed) an alert carries part of its load, on top of the first-paged engineer
ESCALATION_LOAD_SHARE = 0.5
# Only primary (level 1) on-call time counts towards rotation hours
PRIMARY_ESCALATION_LEVEL = 1

BURNOUT_WEIGHTS = {"exposure": 50.0, "relative_load": 30.0, "trend": 20.0}
BURNOUT_FULL_CONFIDENCE_PAGES = 5
TREND_WINDOW_DAYS = 30

FAIRNESS_MIN_ALERTS = 20
FAIRNESS_MIN_ENGINEERS = 3

BUCKETS = ["night", "morning", "afternoon", "evening"]


def fairness_label(g: float) -> str:
    if g < 0.2:
        return "FAIR"
    if g < 0.4:
        return "MODERATE"
    if g < 0.6:
        return "UNEQUAL"
    return "CRITICAL"


def risk_label(score: float) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MEDIUM"
    return "HIGH"


def enrich(alerts: pd.DataFrame, window_end_utc: pd.Timestamp) -> pd.DataFrame:
    """Per-alert features. Time of day uses ``triggered_at_local`` (the team's timezone);
    durations use UTC."""
    df = alerts.copy()
    local = df["triggered_at_local"]
    hour = local.dt.hour
    night = (hour >= 23) | (hour < 6)
    evening = (hour >= 18) & (hour < 23)
    weekend = local.dt.dayofweek >= 5

    df["night"] = night
    df["evening"] = evening
    df["weekend"] = weekend
    df["bucket"] = np.select([night, hour < 12, hour < 18], ["night", "morning", "afternoon"], "evening")

    triggered = df["triggered_at"]
    # Open incidents count until the end of the window
    resolved = df["resolved_at"].fillna(window_end_utc)
    resolved = resolved.mask(resolved > window_end_utc, window_end_utc)
    hours_open = ((resolved - triggered).dt.total_seconds() / 3600).clip(lower=0, upper=MAX_DURATION_HOURS)
    duration_factor = 1 + hours_open / MAX_DURATION_HOURS
    severity_weight = df["severity"].map(SEVERITY_WEIGHTS).fillna(DEFAULT_SEVERITY_WEIGHT)
    time_multiplier = (1 + NIGHT_MULTIPLIER * night + EVENING_MULTIPLIER * evening
                       + WEEKEND_MULTIPLIER * weekend)

    df["load"] = (severity_weight * duration_factor * time_multiplier).astype(float)
    df["exposure"] = (NIGHT_EXPOSURE * night + EVENING_EXPOSURE * evening
                      + WEEKEND_EXPOSURE * weekend).clip(upper=1).astype(float)
    df["ack_minutes"] = (df["acknowledged_at"] - triggered).dt.total_seconds() / 60
    return df
