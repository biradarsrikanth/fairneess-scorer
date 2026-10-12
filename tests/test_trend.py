from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from src.api.deps import get_data_loader
from src.main import app
from src.services.trend import periods
from tests.conftest import API_KEY, WINDOW, WINDOW_PARAMS, FakeLoader, make_alerts

TZ = ZoneInfo("Asia/Kolkata")


def test_periods_follow_the_calendar():
    # 1 Sep 2026 is a Tuesday: a partial first week, then Mondays, then a partial last week
    weeks = periods(WINDOW, "week")
    assert [p.start.day for p in weeks] == [1, 7, 14, 21, 28]
    assert weeks[0].end == datetime(2026, 9, 7, tzinfo=TZ)
    assert weeks[-1].end == WINDOW.end
    assert [(p.start, p.end) for p in periods(WINDOW, "month")] == [(WINDOW.start, WINDOW.end)]


def test_each_period_is_scored_like_a_request_for_it_alone(client):
    body = client.get("/v1/scores/trend", params={**WINDOW_PARAMS, "team": "SRE"}).json()
    assert body["granularity"] == "week" and body["team"] == "SRE"
    by_start = {p["start"][:10]: p for p in body["periods"]}
    # All four SRE alerts (22-27 Sep, Sunday 23:30 included) fall in the week starting Monday 21 Sep
    assert [by_start[d]["alert_count"] for d in ["2026-09-01", "2026-09-07", "2026-09-14", "2026-09-21",
                                                 "2026-09-28"]] == [0, 0, 0, 4, 0]

    week = client.get("/v1/scores/fairness", params={"start": "2026-09-21", "end": "2026-09-27",
                                                     "team": "SRE"}).json()
    assert by_start["2026-09-21"]["gini"] == week["gini"]
    assert by_start["2026-09-21"]["label"] == week["label"]
    assert set(by_start["2026-09-21"]) == {"start", "end", "alert_count", "gini", "label", "confidence",
                                           "average_burnout", "high_risk_count"}


def test_months_and_too_many_periods(client):
    body = client.get("/v1/scores/trend", params={"start": "2026-07-15", "end": "2026-09-30",
                                                  "granularity": "month"}).json()
    assert [p["start"][:10] for p in body["periods"]] == ["2026-07-15", "2026-08-01", "2026-09-01"]

    too_many = client.get("/v1/scores/trend", params={"days": 3650, "granularity": "week"})
    assert too_many.status_code == 422
    assert client.get("/v1/scores/trend", params={**WINDOW_PARAMS, "granularity": "day"}).status_code == 422


def test_a_quiet_period_still_compares_active_engineers():
    app.dependency_overrides[get_data_loader] = lambda: FakeLoader(alerts=make_alerts().iloc[0:0])
    try:
        with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
            body = c.get("/v1/scores/trend", params={**WINDOW_PARAMS, "team": "SRE"}).json()
        assert all(p["alert_count"] == 0 for p in body["periods"])
        # Active engineers are compared even with no alerts (all at zero), so the average is 0, not missing
        assert {p["average_burnout"] for p in body["periods"]} == {0.0}
    finally:
        app.dependency_overrides.clear()
