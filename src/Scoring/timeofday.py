from src.database.data_access import get_alerts_df


def bucket(hour: int) -> str:
    if 23 <= hour or hour < 6:
        return "Night"
    if 6 <= hour < 12:
        return "Morning"
    if 12 <= hour < 18:
        return "Afternoon"
    return "Evening"


def timeofday_heatmap(days: int = 365) -> dict:
    df = get_alerts_df(days)

    df["bucket"] = df["triggered_at"].dt.hour.apply(bucket)

    pivot = df.pivot_table(
        index="engineer_name",
        columns="bucket",
        values="id",
        aggfunc="count",
        fill_value=0
    )

    return pivot.to_dict(orient="index")