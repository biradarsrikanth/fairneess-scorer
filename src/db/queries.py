# The scorer only reads the scoring_*_v views; they are the contract with the gateway, which owns the
# tables (Fairness-Checker: db/migration V2 and V3). View timestamps are UTC, except *_local columns,
# which are in the engineer's team timezone. All values come back as naive datetimes.
from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, text

ALERTS_QUERY = text("""
    SELECT alert_id, engineer_id, severity, triggered_at, resolved_at, acknowledged_at,
           triggered_at_local, escalation_count
    FROM scoring_alert_v
    WHERE triggered_at >= :start AND triggered_at < :end
""")

ENGINEERS_QUERY = text("SELECT engineer_id, name, team, active, team_id, timezone FROM scoring_engineer_v")

# Escalations/reassignments of alerts triggered in the window
ASSIGNMENTS_QUERY = text("""
    SELECT x.alert_id, x.engineer_id, x.kind, x.assigned_at
    FROM scoring_assignment_v x
             JOIN scoring_alert_v a ON a.alert_id = x.alert_id
    WHERE a.triggered_at >= :start AND a.triggered_at < :end
""")

# Shifts overlapping the window
ONCALL_QUERY = text("""
    SELECT engineer_id, escalation_level, starts_at, ends_at
    FROM scoring_oncall_v
    WHERE starts_at < :end AND ends_at > :start
""")

_DATETIME_COLUMNS = ("triggered_at", "resolved_at", "acknowledged_at", "triggered_at_local",
                     "assigned_at", "starts_at", "ends_at")


def _read(engine: Engine, query, params: dict | None = None) -> pd.DataFrame:
    df = pd.read_sql(query, engine, params=params)
    for column in _DATETIME_COLUMNS:
        if column in df:
            df[column] = pd.to_datetime(df[column])
    return df


def fetch_alerts(engine: Engine, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    return _read(engine, ALERTS_QUERY, {"start": start_utc, "end": end_utc})


def fetch_engineers(engine: Engine) -> pd.DataFrame:
    return _read(engine, ENGINEERS_QUERY).astype({"active": bool})


def fetch_assignments(engine: Engine, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    return _read(engine, ASSIGNMENTS_QUERY, {"start": start_utc, "end": end_utc})


def fetch_oncall(engine: Engine, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    return _read(engine, ONCALL_QUERY, {"start": start_utc, "end": end_utc})
