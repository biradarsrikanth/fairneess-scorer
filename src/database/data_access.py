import pandas as pd
from sqlalchemy import text

from src.database.database import engine


#Get alerts From the DATABASE for the past "X" days(Default is 90 days)
def get_alerts_df(days: int = 90) -> pd.DataFrame:
    query = text("""
        SELECT a.id, \
               a.severity, a.triggered_at, a.resolved_at,
               a.engineer_id, e.name AS engineer_name
        FROM alert_event a
                 JOIN engineer_data e ON a.engineer_id = e.id
        WHERE a.triggered_at >= NOW() - (:days || ' days')::interval
    """)
    df = pd.read_sql(query, engine,params={"days": days})
    df["triggered_at"] = pd.to_datetime(df["triggered_at"])
    return df

#Get All Engineers Data
def get_engineers_df(days: int = 90) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM engineer_data", engine)
