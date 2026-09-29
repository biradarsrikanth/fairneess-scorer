"""Runs the real SQL against PostgreSQL. Needs TEST_DATABASE_URL, e.g.
postgresql+psycopg://postgres:postgres@localhost:5432/postgres."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.api.deps import get_data_loader
from src.db.loader import DataLoader
from src.main import app
from tests.conftest import API_KEY

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TZ = ZoneInfo("Asia/Kolkata")
SEPTEMBER = (datetime(2026, 9, 1, tzinfo=TZ), datetime(2026, 10, 1, tzinfo=TZ))


@pytest.fixture(scope="module")
def engine():
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.exec_driver_sql((Path(__file__).parent / "schema.sql").read_text())
        conn.execute(text("""
            INSERT INTO team (id, name, timezone) VALUES
              (1, 'SRE', 'Asia/Kolkata'), (2, 'EU', 'Europe/London')
        """))
        conn.execute(text("""
            INSERT INTO engineer_data (id, email, name, team_id, active) VALUES
              (1, 'a@x.io', 'Asha', 1, TRUE),
              (2, 'b@x.io', 'Bala', 1, TRUE),
              (3, 'c@x.io', 'Chen', 1, FALSE),
              (4, 'e@x.io', 'Emma', 2, TRUE)
        """))
        # UTC timestamps: 18:00 UTC is 23:30 in India (night) but 19:00 in London (evening)
        conn.execute(text("""
            INSERT INTO alert_event (id, pager_duty_incident_id, severity, status, triggered_at,
                                     acknowledged_at, resolved_at, engineer_id) VALUES
              (1, 'Q1', 'P1', 'resolved', '2026-09-27 18:00', '2026-09-27 18:10', '2026-09-27 20:00', 1),
              (2, 'Q2', 'P3', 'resolved', '2026-09-22 04:00', NULL, '2026-09-22 04:30', 1),
              (3, 'Q3', 'P3', 'triggered', '2026-09-23 08:30', NULL, NULL, 2),
              (4, 'Q4', 'P2', 'resolved', '2026-09-24 08:30', NULL, '2026-09-24 09:00', NULL),
              (5, 'Q5', 'P3', 'resolved', '2026-08-01 08:30', NULL, '2026-08-01 09:00', 2),
              (6, 'Q6', 'P2', 'resolved', '2026-09-27 18:00', NULL, '2026-09-27 18:30', 4)
        """))
        conn.execute(text("""
            INSERT INTO alert_assignment (alert_id, engineer_id, kind, assigned_at) VALUES
              (1, 1, 'PAGED', '2026-09-27 18:00'),
              (1, 2, 'ESCALATED', '2026-09-27 18:15'),
              (3, NULL, 'ESCALATED', '2026-09-23 09:00')
        """))
        conn.execute(text("""
            INSERT INTO oncall_shift (engineer_id, escalation_level, starts_at, ends_at) VALUES
              (1, 1, '2026-09-01 00:00', '2026-09-16 00:00'),
              (2, 1, '2026-09-16 00:00', '2026-10-01 00:00'),
              (2, 1, '2026-06-01 00:00', '2026-06-08 00:00')
        """))
    yield engine
    engine.dispose()


def test_views_filter_and_localise_per_team(engine):
    loader = DataLoader(engine, ttl_seconds=0)
    alerts = loader.alerts(*SEPTEMBER).set_index("alert_id")

    assert sorted(alerts.index) == [1, 2, 3, 6]  # unattributed Q4 and August Q5 excluded
    assert alerts.loc[1, "triggered_at_local"] == datetime(2026, 9, 27, 23, 30)  # India
    assert alerts.loc[6, "triggered_at_local"] == datetime(2026, 9, 27, 19, 0)  # London
    assert alerts.loc[1, "escalation_count"] == 1
    assert loader.engineers()["timezone"].tolist() == ["Asia/Kolkata"] * 3 + ["Europe/London"]


def test_assignment_and_oncall_views(engine):
    loader = DataLoader(engine, ttl_seconds=0)
    assignments = loader.assignments(*SEPTEMBER)
    # PAGED rows and escalations to non-engineers are not part of the view
    assert assignments[["alert_id", "engineer_id", "kind"]].values.tolist() == [[1, 2, "ESCALATED"]]
    assert sorted(loader.oncall(*SEPTEMBER)["engineer_id"]) == [1, 2]  # June shift excluded


def test_cache_returns_independent_copies(engine):
    loader = DataLoader(engine, ttl_seconds=60)
    first = loader.alerts(*SEPTEMBER)
    first["severity"] = "changed"
    assert "changed" not in loader.alerts(*SEPTEMBER)["severity"].tolist()


def test_api_end_to_end(engine):
    app.dependency_overrides[get_data_loader] = lambda: DataLoader(engine, ttl_seconds=0)
    try:
        with TestClient(app, headers={"X-API-Key": API_KEY}) as client:
            params = {"start": "2026-09-01", "end": "2026-09-30", "team": "SRE"}
            fairness = client.get("/v1/scores/fairness", params=params).json()
            timeofday = client.get("/v1/scores/timeofday", params=params).json()
            burnout = client.get("/v1/scores/burnout", params=params).json()
    finally:
        app.dependency_overrides.clear()

    rows = {e["name"]: e for e in fairness["engineers"]}
    assert fairness["basis"] == "ONCALL_ROTATION"
    assert set(rows) == {"Asha", "Bala"}  # Chen: inactive, no shifts, no pages
    assert rows["Bala"]["escalations_received"] == 1
    assert fairness["alert_count"] == 3
    asha = next(r for r in timeofday["engineers"] if r["name"] == "Asha")
    assert (asha["night"], asha["morning"]) == (1, 1)
    asha_burnout = next(b for b in burnout["engineers"] if b["name"] == "Asha")
    assert asha_burnout["median_ack_minutes"] == 10.0
