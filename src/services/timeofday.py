import pandas as pd

from src.services.model import BUCKETS
from src.services.scope import Scope


def timeofday_counts(scope: Scope) -> list[dict]:
    """Pages received (first pages and escalations) per engineer and time-of-day bucket, in each engineer's
    team timezone. Every bucket is present, 0 when empty."""
    counts = (pd.crosstab(scope.work["engineer_id"], scope.work["bucket"])
              if not scope.work.empty else pd.DataFrame())
    counts = (counts.reindex(index=scope.engineers["engineer_id"], columns=BUCKETS, fill_value=0)
              .fillna(0).astype(int))
    rows = scope.engineers[["engineer_id", "name", "team"]].merge(
        counts, left_on="engineer_id", right_index=True)
    return rows.sort_values("name").to_dict(orient="records")
