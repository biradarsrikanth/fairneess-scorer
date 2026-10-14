# v1 HTTP contract with the gateway (Fairness-Checker dto/scoring). Adding fields is fine; renaming or
# removing one is a breaking change and belongs in a /v2 route.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FairnessLabel = Literal["FAIR", "MODERATE", "UNEQUAL", "CRITICAL"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class Window(BaseModel):
    start: datetime
    end: datetime
    timezone: str


class EngineerRef(BaseModel):
    engineer_id: int
    name: str
    team: str


class EngineerLoad(EngineerRef):
    alert_count: int = Field(description="Alerts where this engineer was paged first")
    escalations_received: int = Field(description="Alerts escalated or reassigned to this engineer")
    load: float = Field(description="Sum of alert loads (severity × duration × time of day); "
                                    "escalations count at a share")
    share_pct: float
    oncall_hours: float | None = Field(
        description="Primary on-call hours in the window; null without shift data")
    load_per_oncall_hour: float | None


class TeamFairness(BaseModel):
    team: str
    gini: float = Field(ge=0, le=1)
    label: FairnessLabel
    rotation_gini: float | None
    alert_count: int
    engineer_count: int


class FairnessReport(BaseModel):
    window: Window
    team: str | None
    basis: Literal["ONCALL_ROTATION", "ACTIVE_ENGINEERS"] = Field(
        description="Who is compared: engineers on the on-call rotation, or all active engineers "
                    "when there is no shift data")
    gini: float = Field(ge=0, le=1, description="Gini coefficient of load across engineers; for several "
                                                 "teams, the teams' own Ginis averaged, weighted by alerts")
    label: FairnessLabel
    rotation_gini: float | None = Field(
        description="Gini coefficient of primary on-call hours; null without shift data")
    confidence: Literal["LOW", "OK"] = Field(description="LOW when there are too few alerts or engineers")
    alert_count: int
    engineers: list[EngineerLoad]
    teams: list[TeamFairness] = Field(description="Each team's own fairness, by name")


class BurnoutComponents(BaseModel):
    exposure: float = Field(ge=0, le=1)
    relative_load: float = Field(ge=0, le=1)
    trend: float = Field(ge=0, le=1)


class BurnoutScore(EngineerRef):
    alert_count: int
    escalations_received: int
    score: float = Field(ge=0, le=100)
    risk: RiskLevel
    night_pct: float
    evening_pct: float
    weekend_pct: float
    trend_ratio: float = Field(
        description="(pages in last 30 days + 1) / (pages in the 30 days before + 1)")
    median_ack_minutes: float | None = Field(description="Median time to acknowledge first pages")
    oncall_hours: float | None
    components: BurnoutComponents


class BurnoutReport(BaseModel):
    window: Window
    team: str | None
    engineers: list[BurnoutScore]


class TimeOfDayCounts(BaseModel):
    night: int
    morning: int
    afternoon: int
    evening: int


class EngineerTimeOfDay(EngineerRef, TimeOfDayCounts):
    pass


class TimeOfDayReport(BaseModel):
    window: Window
    team: str | None
    engineers: list[EngineerTimeOfDay]


class EngineerReport(BaseModel):
    window: Window
    engineer: EngineerRef
    active: bool
    burnout: BurnoutScore
    team_share_pct: float
    time_of_day: TimeOfDayCounts


class TrendPeriod(BaseModel):
    start: datetime
    end: datetime = Field(description="Exclusive")
    alert_count: int
    gini: float = Field(ge=0, le=1)
    label: FairnessLabel
    confidence: Literal["LOW", "OK"]
    average_burnout: float | None = Field(description="Mean burnout score of the engineers compared; "
                                                      "null when nobody is")
    high_risk_count: int = Field(description="Engineers with HIGH burnout risk in the period")


class TrendReport(BaseModel):
    window: Window
    team: str | None
    granularity: Literal["week", "month"]
    periods: list[TrendPeriod] = Field(description="Calendar weeks (from Monday) or months; the first and "
                                                   "last may be partial")


class HealthStatus(BaseModel):
    status: Literal["ok", "error"]
    database: Literal["ok", "unavailable"] | None = None
