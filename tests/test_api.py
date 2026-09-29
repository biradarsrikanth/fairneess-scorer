from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from src.api.deps import get_data_loader
from src.db.session import get_engine
from src.main import app
from tests.conftest import WINDOW_PARAMS


def test_requires_api_key(client):
    anonymous = TestClient(app)
    assert anonymous.get("/v1/scores/fairness").status_code == 401
    assert anonymous.get("/v1/scores/fairness", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/v1/scores/fairness", params=WINDOW_PARAMS).status_code == 200


def test_fairness_contract(client):
    body = client.get("/v1/scores/fairness", params={**WINDOW_PARAMS, "team": "SRE"}).json()
    assert set(body) == {"window", "team", "basis", "gini", "label", "rotation_gini", "confidence",
                         "alert_count", "engineers"}
    assert body["window"] == {"start": "2026-09-01T00:00:00+05:30", "end": "2026-10-01T00:00:00+05:30",
                              "timezone": "Asia/Kolkata"}
    assert set(body["engineers"][0]) == {"engineer_id", "name", "team", "alert_count", "escalations_received",
                                         "load", "share_pct", "oncall_hours", "load_per_oncall_hour"}


def test_burnout_contract(client):
    body = client.get("/v1/scores/burnout", params=WINDOW_PARAMS).json()
    first = body["engineers"][0]
    assert set(first) == {"engineer_id", "name", "team", "alert_count", "escalations_received", "score",
                          "risk", "night_pct", "evening_pct", "weekend_pct", "trend_ratio",
                          "median_ack_minutes", "oncall_hours", "components"}
    assert set(first["components"]) == {"exposure", "relative_load", "trend"}


def test_timeofday_contract(client):
    rows = client.get("/v1/scores/timeofday", params=WINDOW_PARAMS).json()["engineers"]
    asha = next(r for r in rows if r["engineer_id"] == 1)
    assert (asha["night"], asha["morning"], asha["afternoon"], asha["evening"]) == (1, 1, 0, 0)


def test_engineer_report_is_scored_within_their_team(client):
    body = client.get("/v1/scores/engineers/1", params=WINDOW_PARAMS).json()
    assert body["engineer"] == {"engineer_id": 1, "name": "Asha", "team": "SRE"}
    assert body["time_of_day"] == {"night": 1, "morning": 1, "afternoon": 0, "evening": 0}
    assert 0 < body["team_share_pct"] < 100


def test_engineer_without_alerts_gets_zero_scores(client):
    body = client.get("/v1/scores/engineers/3", params=WINDOW_PARAMS).json()
    assert body["burnout"]["score"] == 0 and body["team_share_pct"] == 0


def test_unknown_engineer_is_404(client):
    response = client.get("/v1/scores/engineers/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Engineer 999 not found"}


def test_window_validation(client):
    assert client.get("/v1/scores/fairness", params={"days": 0}).status_code == 422
    assert client.get("/v1/scores/fairness", params={"days": 3651}).status_code == 422
    assert client.get("/v1/scores/fairness", params={"start": "2026-09-10", "days": 5}).status_code == 422
    assert client.get("/v1/scores/fairness",
                      params={"start": "2026-09-10", "end": "2026-09-01"}).status_code == 422


def test_request_id_is_echoed_or_generated(client):
    echoed = client.get("/health/live", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
    assert echoed == "abc-123"
    generated = client.get("/health/live", headers={"X-Request-ID": "bad id\n"}).headers["X-Request-ID"]
    assert generated != "bad id\n" and len(generated) == 32


def test_liveness(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_metrics_exposed(client):
    client.get("/v1/scores/fairness", params=WINDOW_PARAMS)
    assert "http_requests_total" in client.get("/metrics").text


def test_readiness_hides_database_error(client):
    class DownEngine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("password=secret"))

    app.dependency_overrides[get_engine] = lambda: DownEngine()
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
    assert "secret" not in response.text


def test_database_error_returns_503_without_details(client):
    class FailingLoader:
        def alerts(self, *args):
            raise OperationalError("SELECT", {}, Exception("password=secret"))

        engineers = alerts

    app.dependency_overrides[get_data_loader] = lambda: FailingLoader()
    response = client.get("/v1/scores/fairness")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_engineer_off_the_rotation_still_gets_a_report():
    import pandas as pd

    from tests.conftest import API_KEY, FakeLoader

    oncall = pd.DataFrame({"engineer_id": [1, 2], "escalation_level": [1, 1],
                           "starts_at": pd.to_datetime(["2026-09-01", "2026-09-15"]),
                           "ends_at": pd.to_datetime(["2026-09-15", "2026-09-30"])})
    app.dependency_overrides[get_data_loader] = lambda: FakeLoader(oncall=oncall)
    try:
        with TestClient(app, headers={"X-API-Key": API_KEY}) as client:
            body = client.get("/v1/scores/engineers/3", params=WINDOW_PARAMS).json()
    finally:
        app.dependency_overrides.clear()
    assert body["engineer"]["name"] == "Chen"
    assert body["burnout"]["oncall_hours"] == 0.0 and body["team_share_pct"] == 0.0


def test_database_error_wrapped_by_pandas_returns_503(client):
    from pandas.errors import DatabaseError

    class MissingViewLoader:
        def alerts(self, *args):
            raise DatabaseError("Execution failed on sql: relation \"scoring_alert_v\" does not exist")

        engineers = assignments = oncall = alerts

    app.dependency_overrides[get_data_loader] = lambda: MissingViewLoader()
    response = client.get("/v1/scores/fairness")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
