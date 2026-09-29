from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from src.services.model import ESCALATION_LOAD_SHARE, PRIMARY_ESCALATION_LEVEL, enrich

WORK_COLUMNS = ["alert_id", "engineer_id", "role", "triggered_at", "night", "evening", "weekend",
                "bucket", "load", "exposure", "ack_minutes"]


@dataclass(frozen=True)
class ScoreWindow:
    """Half-open interval [start, end) in the default timezone (both timezone-aware)."""

    start: datetime
    end: datetime

    @property
    def utc_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.start.astimezone(UTC).replace(tzinfo=None))

    @property
    def utc_end(self) -> pd.Timestamp:
        return pd.Timestamp(self.end.astimezone(UTC).replace(tzinfo=None))


@dataclass(frozen=True)
class Scope:
    """Everything the scoring functions need.

    ``work`` has one row per page an engineer received: ``role`` is "primary" for the first-paged engineer
    (full load) and "escalation" for escalations/reassignments (a share of the load).
    ``engineers`` are the engineers being compared, with their primary on-call hours in the window.
    """

    window: ScoreWindow
    team: str | None
    engineers: pd.DataFrame  # engineer_id, name, team, active, oncall_hours
    work: pd.DataFrame
    has_rotation: bool  # True when on-call shifts exist for the engineers in scope


def _oncall_hours(oncall: pd.DataFrame, window: ScoreWindow) -> pd.Series:
    primary = oncall[oncall["escalation_level"] == PRIMARY_ESCALATION_LEVEL]
    if primary.empty:
        return pd.Series(dtype=float)
    starts = primary["starts_at"].mask(primary["starts_at"] < window.utc_start, window.utc_start)
    ends = primary["ends_at"].mask(primary["ends_at"] > window.utc_end, window.utc_end)
    hours = ((ends - starts).dt.total_seconds() / 3600).clip(lower=0)
    return hours.groupby(primary["engineer_id"]).sum()


def build_scope(alerts: pd.DataFrame, engineers: pd.DataFrame, assignments: pd.DataFrame,
                oncall: pd.DataFrame, window: ScoreWindow, team: str | None,
                include_engineer_id: int | None = None) -> Scope:
    if team is not None:
        engineers = engineers[engineers["team"] == team]
    ids = set(engineers["engineer_id"])
    enriched = enrich(alerts, window.utc_end)

    primary = enriched[enriched["engineer_id"].isin(ids)].assign(role="primary")
    # Escalations to engineers in scope, from any team's alert, excluding the first-paged engineer themselves
    escalated = (assignments[assignments["engineer_id"].isin(ids)]
                 .drop_duplicates(["alert_id", "engineer_id"])
                 .merge(enriched.drop(columns=["engineer_id"]).assign(first_paged=enriched["engineer_id"]),
                        on="alert_id"))
    escalated = escalated[escalated["engineer_id"] != escalated["first_paged"]]
    escalated = escalated.assign(role="escalation", load=escalated["load"] * ESCALATION_LOAD_SHARE,
                                 ack_minutes=float("nan"))
    work = pd.concat([primary[WORK_COLUMNS], escalated[WORK_COLUMNS]], ignore_index=True)

    hours = _oncall_hours(oncall[oncall["engineer_id"].isin(ids)], window)
    engineers = engineers.assign(
        oncall_hours=engineers["engineer_id"].map(hours).fillna(0.0).astype(float))
    has_rotation = bool(engineers["oncall_hours"].sum() > 0)

    # Who is compared: with shift data, people on the rotation (or who got paged anyway); without it,
    # active engineers (zero alerts is a data point) plus anyone who got paged
    paged = engineers["engineer_id"].isin(work["engineer_id"])
    eligible = (engineers["oncall_hours"] > 0) if has_rotation else engineers["active"]
    requested = engineers["engineer_id"] == include_engineer_id
    in_scope = engineers[eligible | paged | requested].reset_index(drop=True)

    return Scope(window=window, team=team, engineers=in_scope, work=work, has_rotation=has_rotation)
