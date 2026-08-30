import pandas as pd
from src.database.data_access import get_alerts_df


def risk_label(score: float) -> str:
    if score < 30: return "LOW"
    if score < 60: return "MEDIUM"
    return "HIGH"


def burnout_scores(days: int = 365) -> list[dict]:
    df = get_alerts_df(days)
    now = pd.Timestamp.utcnow().tz_localize(None)

    results = []
    for name, g in df.groupby("engineer_name"):
        total = len(g)
        off_hours = g["triggered_at"].dt.hour.isin(range(23, 24)).sum() \
                    + g["triggered_at"].dt.hour.isin(range(0, 6)).sum()
        weekend = g["triggered_at"].dt.dayofweek.isin([5, 6]).sum()
        off_pct = off_hours / total if total else 0
        wknd_pct = weekend / total if total else 0

        last_30 = g[g["triggered_at"] >= now - pd.Timedelta(days=30)]
        prior_30 = g[(g["triggered_at"] < now - pd.Timedelta(days=30)) &
                     (g["triggered_at"] >= now - pd.Timedelta(days=60))]
        trend = (len(last_30) / len(prior_30)) if len(prior_30) else 1.0

        score = (off_pct * 40) + (wknd_pct * 30) + (min(trend, 2) / 2 * 30)
        score = round(min(score, 100), 1)

        results.append({
            "engineer": name, "score": score, "risk": risk_label(score),
            "off_hours_pct": round(off_pct * 100, 1),
            "weekend_pct": round(wknd_pct * 100, 1),
            "trend": round(trend, 2),
        })
    return sorted(results, key=lambda r: r["score"], reverse=True)
