"""Every error is RFC 9457 problem details, the same contract as the gateway's ApiError."""
from fastapi.testclient import TestClient

from src.api.deps import get_data_loader
from src.main import app
from tests.conftest import API_KEY

PROBLEM_KEYS = {"type", "title", "status", "detail", "instance", "code", "errors", "request_id", "timestamp"}


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == PROBLEM_KEYS
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    # The body's id is the one in the header, so a caller can quote either
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body


def test_missing_api_key_keeps_the_challenge_header():
    response = TestClient(app).get("/v1/scores/fairness", headers={"X-Request-ID": "err-401"})
    body = assert_problem(response, 401, "UNAUTHORIZED")
    assert body["detail"] == "Invalid or missing API key"
    assert body["request_id"] == "err-401"
    assert response.headers["WWW-Authenticate"] == "ApiKey"


def test_invalid_parameter_names_the_field(client):
    body = assert_problem(client.get("/v1/scores/fairness", params={"days": 0}), 422, "VALIDATION_FAILED")
    assert body["errors"] == [{"field": "days", "message": "Input should be greater than or equal to 1"}]
    assert body["detail"] == "days: Input should be greater than or equal to 1"
    assert body["instance"] == "/v1/scores/fairness"


def test_rule_across_parameters_is_a_validation_error_without_a_field(client):
    body = assert_problem(client.get("/v1/scores/fairness", params={"start": "2026-09-10", "days": 5}),
                          422, "VALIDATION_FAILED")
    assert body["detail"] == "Use either `start` or `days`, not both"
    assert body["errors"] == []


def test_unknown_route_is_a_problem_too(client):
    body = assert_problem(client.get("/v1/nope"), 404, "NOT_FOUND")
    assert body["detail"] == "Not Found"


def test_unexpected_error_is_generic_and_still_traceable():
    class BrokenLoader:
        def engineers(self):
            raise RuntimeError("connect to db-prod.internal failed, password=hunter2")

        alerts = assignments = oncall = engineers

    app.dependency_overrides[get_data_loader] = lambda: BrokenLoader()
    try:
        client = TestClient(app, raise_server_exceptions=False, headers={"X-API-Key": API_KEY})
        response = client.get("/v1/scores/engineers/1", headers={"X-Request-ID": "err-500"})
    finally:
        app.dependency_overrides.clear()

    body = assert_problem(response, 500, "INTERNAL_ERROR")
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == "err-500"
    assert "hunter2" not in response.text and "db-prod" not in response.text
