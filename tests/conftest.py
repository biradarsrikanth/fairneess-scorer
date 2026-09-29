import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Settings are validated at startup; unit tests never connect because the data loader is replaced
API_KEY = "test-api-key-0123456789abcdef0123456789"
os.environ.setdefault("AZURE_DB_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ["SCORER_API_KEY"] = API_KEY
os.environ["TEAM_TIMEZONE"] = "Asia/Kolkata"

from src.api.deps import get_data_loader  # noqa: E402
from src.main import app  # noqa: E402
from src.services.scope import ScoreWindow, build_scope  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
IST = pd.Timedelta(hours=5, minutes=30)
# Window: 1 Sep to 30 Sep 2026 inclusive (India time)
WINDOW = ScoreWindow(start=datetime(2026, 9, 1, tzinfo=TZ), end=datetime(2026, 10, 1, tzinfo=TZ))
WINDOW_PARAMS = {"start": "2026-09-01", "end": "2026-09-30"}


def make_engineers() -> pd.DataFrame:
    return pd.DataFrame({
        "engineer_id": [1, 2, 3, 4],
        "name": ["Asha", "Bala", "Chen", "Dev"],
        "team": ["SRE", "SRE", "SRE", "Platform"],
        "active": [True, True, True, False],
        "team_id": [1, 1, 1, 2],
        "timezone": ["Asia/Kolkata"] * 4,
    })


def make_alerts() -> pd.DataFrame:
    """Local (India) times shown; UTC is 5:30 earlier. Asha: a P1 on Sunday night open 4h (acked after
    10 min) + a P3 on Tuesday morning open 30 min. Bala: two P3s on weekday afternoons. Chen: none.
    Dev (inactive, Platform): one P2."""
    local = pd.to_datetime(["2026-09-27 23:30", "2026-09-22 09:30", "2026-09-23 14:00",
                            "2026-09-24 14:30", "2026-09-10 12:00"])
    resolved_local = pd.to_datetime(["2026-09-28 03:30", "2026-09-22 10:00", "2026-09-23 14:30",
                                     "2026-09-24 15:00", "2026-09-10 13:00"])
    acked_local = pd.to_datetime(["2026-09-27 23:40", None, None, None, None])
    return pd.DataFrame({
        "alert_id": [1, 2, 3, 4, 5],
        "engineer_id": [1, 1, 2, 2, 4],
        "severity": ["P1", "P3", "P3", "P3", "P2"],
        "triggered_at": local - IST,
        "resolved_at": resolved_local - IST,
        "acknowledged_at": acked_local - IST,
        "triggered_at_local": local,
        "escalation_count": [0, 0, 0, 0, 0],
    })


def no_assignments() -> pd.DataFrame:
    return pd.DataFrame({"alert_id": pd.Series(dtype=int), "engineer_id": pd.Series(dtype=int),
                         "kind": pd.Series(dtype=str), "assigned_at": pd.Series(dtype="datetime64[ns]")})


def no_oncall() -> pd.DataFrame:
    return pd.DataFrame({"engineer_id": pd.Series(dtype=int), "escalation_level": pd.Series(dtype=int),
                         "starts_at": pd.Series(dtype="datetime64[ns]"),
                         "ends_at": pd.Series(dtype="datetime64[ns]")})


class FakeLoader:
    def __init__(self, alerts: pd.DataFrame | None = None, engineers: pd.DataFrame | None = None,
                 assignments: pd.DataFrame | None = None, oncall: pd.DataFrame | None = None) -> None:
        self._alerts = make_alerts() if alerts is None else alerts
        self._engineers = make_engineers() if engineers is None else engineers
        self._assignments = no_assignments() if assignments is None else assignments
        self._oncall = no_oncall() if oncall is None else oncall

    @staticmethod
    def _utc(value: datetime) -> pd.Timestamp:
        return pd.Timestamp(value).tz_convert("UTC").tz_localize(None)

    def alerts(self, start: datetime, end: datetime) -> pd.DataFrame:
        a = self._alerts
        return a[(a["triggered_at"] >= self._utc(start)) & (a["triggered_at"] < self._utc(end))].copy()

    def engineers(self) -> pd.DataFrame:
        return self._engineers.copy()

    def assignments(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self._assignments.copy()

    def oncall(self, start: datetime, end: datetime) -> pd.DataFrame:
        return self._oncall.copy()


def scope_for(team: str | None = "SRE", **data) -> object:
    loader = FakeLoader(**data)
    return build_scope(loader.alerts(WINDOW.start, WINDOW.end), loader.engineers(),
                       loader.assignments(WINDOW.start, WINDOW.end), loader.oncall(WINDOW.start, WINDOW.end),
                       WINDOW, team)


@pytest.fixture
def scope():
    return scope_for("SRE")


@pytest.fixture
def client():
    app.dependency_overrides[get_data_loader] = lambda: FakeLoader()
    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c
    app.dependency_overrides.clear()
