import os

import pandas as pd
from sqlalchemy import text

from src.database.database import engine

# Timestamps are stored in UTC; scoring buckets (night, weekend) use the team's local time
TEAM_TIMEZONE = os.environ.get("TEAM_TIMEZONE", "Asia/Kolkata")


#Current time in the team's timezone, naive to match the alert timestamps
def local_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz=TEAM_TIMEZONE).tz_localize(None)


#Get alerts From the DATABASE for the past "X" days(Default is 730 days)
def get_alerts_df(days: int = 730) -> pd.DataFrame:
    query = text("""
        SELECT a.id, \
               a.severity, a.triggered_at, a.resolved_at,
               a.engineer_id, e.name AS engineer_name
        FROM alert_event a
                 JOIN engineer_data e ON a.engineer_id = e.id
        WHERE a.triggered_at >= NOW() - (:days || ' days')::interval
    """)
    df = pd.read_sql(query, engine,params={"days": days})
    df["triggered_at"] = (pd.to_datetime(df["triggered_at"])
                          .dt.tz_localize("UTC")
                          .dt.tz_convert(TEAM_TIMEZONE)
                          .dt.tz_localize(None))
    return df

#Get All Engineers Data
def get_engineers_df() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM engineer_data", engine)
