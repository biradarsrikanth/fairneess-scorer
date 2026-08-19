import numpy as np
from src.database.data_access import get_alerts_df


def label_for(g: float) -> str:
    if g < 0.2: return "FAIR"
    if g < 0.4: return "MODERATE"
    if g < 0.6: return "UNEQUAL"
    return "CRITICAL"


def gini(counts: np.ndarray) -> float:
    counts = np.sort(np.asarray(counts, dtype=float))
    n = counts.shape[0]
    if n == 0 or counts.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * counts) - (n + 1) * np.sum(counts))
                 / (n * np.sum(counts)))


def team_fairness_score(days: int = 90) -> dict:
    df = get_alerts_df(days)
    per_engineer = df.groupby("engineer_name").size()
    g = gini(per_engineer.values)
    total = per_engineer.sum()
    shares = (per_engineer / total * 100).round(1).to_dict() if total else {}
    return {"gini": round(g, 3), "label": label_for(g), "engineer_share_pct": shares}
