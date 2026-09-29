import numpy as np
import pandas as pd
import pytest

from src.services.burnout import burnout_scores
from src.services.fairness import gini, team_fairness
from src.services.model import ESCALATION_LOAD_SHARE, enrich
from src.services.timeofday import timeofday_counts
from tests.conftest import IST, WINDOW, make_alerts, make_engineers, no_assignments, scope_for


def by_id(rows: list[dict]) -> dict[int, dict]:
    return {r["engineer_id"]: r for r in rows}


def test_gini_edge_cases():
    assert gini(np.array([3, 3, 3])) == 0.0
    assert gini(np.array([])) == 0.0
    assert gini(np.array([0, 0])) == 0.0
    assert gini(np.array([0, 0, 9])) == pytest.approx(2 / 3)


def test_alert_load_weights_severity_duration_and_time():
    df = enrich(make_alerts(), WINDOW.utc_end).set_index("alert_id")
    # P1 (4) x open 4h (2.0) x Sunday night (1 + 0.5 + 0.25)
    assert df.loc[1, "load"] == pytest.approx(4 * 2.0 * 1.75)
    # P3 (2) x 30 min (1.125) x weekday morning (1.0)
    assert df.loc[2, "load"] == pytest.approx(2 * 1.125)
    assert df.loc[1, "bucket"] == "night" and df.loc[2, "bucket"] == "morning"
    assert df.loc[1, "exposure"] == 1.0 and df.loc[2, "exposure"] == 0.0
    assert df.loc[1, "ack_minutes"] == 10


def test_time_of_day_uses_the_teams_own_timezone():
    # Same UTC instant (18:00 UTC); a London team sees 19:00 (evening), not India's 23:30 (night)
    alerts = make_alerts().iloc[[0]].assign(triggered_at_local=pd.Timestamp("2026-09-27 19:00"))
    df = enrich(alerts, WINDOW.utc_end)
    assert df["bucket"].iloc[0] == "evening" and not df["night"].iloc[0]


def test_open_incident_counts_until_window_end():
    last_hour = pd.Timestamp("2026-09-30 23:00")
    alerts = make_alerts().iloc[[0]].assign(resolved_at=pd.NaT, triggered_at_local=last_hour,
                                            triggered_at=last_hour - IST)
    df = enrich(alerts, WINDOW.utc_end)
    # Open for the last hour of the window: duration factor 1.25, night 1.5
    assert df["load"].iloc[0] == pytest.approx(4 * 1.25 * 1.5)


def test_fairness_includes_active_engineers_without_alerts(scope):
    report = team_fairness(scope)
    rows = by_id(report["engineers"])
    assert set(rows) == {1, 2, 3}  # Dev is another team
    assert rows[3]["alert_count"] == 0 and rows[3]["load"] == 0
    assert report["basis"] == "ACTIVE_ENGINEERS" and report["rotation_gini"] is None
    assert rows[1]["oncall_hours"] is None
    assert report["alert_count"] == 4
    assert report["confidence"] == "LOW"
    assert sum(e["share_pct"] for e in report["engineers"]) == pytest.approx(100, abs=0.2)


def test_inactive_engineer_with_alerts_stays_in_scope():
    assert scope_for("Platform").engineers["engineer_id"].tolist() == [4]


def test_inactive_engineer_without_alerts_is_excluded():
    scope = scope_for("SRE", engineers=make_engineers().assign(active=[True, True, False, True]))
    assert 3 not in scope.engineers["engineer_id"].tolist()


def test_escalation_adds_a_share_of_the_load_to_the_receiver():
    assignments = pd.concat([no_assignments(), pd.DataFrame({
        "alert_id": [1, 1], "engineer_id": [3, 1], "kind": ["ESCALATED", "ESCALATED"],
        "assigned_at": [pd.Timestamp("2026-09-27 18:15")] * 2})])  # Asha escalating to herself is ignored
    report = team_fairness(scope_for("SRE", assignments=assignments))
    rows = by_id(report["engineers"])
    asha_alert_load = 4 * 2.0 * 1.75
    assert rows[3]["escalations_received"] == 1 and rows[3]["alert_count"] == 0
    assert rows[3]["load"] == pytest.approx(asha_alert_load * ESCALATION_LOAD_SHARE, abs=0.01)
    assert rows[1]["escalations_received"] == 0

    burnout = by_id(burnout_scores(scope_for("SRE", assignments=assignments)))
    assert burnout[3]["night_pct"] == 100.0 and burnout[3]["escalations_received"] == 1


def test_rotation_basis_compares_only_people_on_call():
    # Asha and Bala were on primary call for 10 days each; Chen had no shifts and no pages
    oncall = pd.DataFrame({
        "engineer_id": [1, 2, 3], "escalation_level": [1, 1, 2],
        "starts_at": pd.to_datetime(["2026-09-01", "2026-09-11", "2026-09-21"]),
        "ends_at": pd.to_datetime(["2026-09-11", "2026-09-21", "2026-10-01"]),
    })
    report = team_fairness(scope_for("SRE", oncall=oncall))
    rows = by_id(report["engineers"])
    assert report["basis"] == "ONCALL_ROTATION"
    assert set(rows) == {1, 2}  # Chen was only a level-2 backup
    assert rows[1]["oncall_hours"] == 240.0 and rows[2]["oncall_hours"] == 240.0
    assert report["rotation_gini"] == 0.0
    assert rows[1]["load_per_oncall_hour"] == pytest.approx(rows[1]["load"] / 240, abs=0.001)


def test_oncall_hours_are_clipped_to_the_window():
    oncall = pd.DataFrame({"engineer_id": [1], "escalation_level": [1],
                           "starts_at": pd.to_datetime(["2026-08-20"]),
                           "ends_at": pd.to_datetime(["2026-09-02"])})
    scope = scope_for("SRE", oncall=oncall)
    hours = scope.engineers.set_index("engineer_id")["oncall_hours"]
    # Window starts 1 Sep 00:00 India time = 31 Aug 18:30 UTC
    assert hours[1] == pytest.approx(29.5)


def test_burnout_components_and_confidence(scope):
    scores = by_id(burnout_scores(scope))
    asha, chen = scores[1], scores[3]
    assert asha["night_pct"] == 50.0 and asha["weekend_pct"] == 50.0
    assert asha["components"]["exposure"] == 0.5
    assert asha["median_ack_minutes"] == 10.0
    # Two pages only: confidence 2/5 caps the score
    assert asha["score"] < 40
    assert chen["score"] == 0.0 and chen["risk"] == "LOW"
    assert chen["trend_ratio"] == 1.0 and chen["median_ack_minutes"] is None


def test_trend_rises_when_recent_pages_increase(scope):
    asha = by_id(burnout_scores(scope))[1]
    # 2 pages in the last 30 days, none before: (2 + 1) / (0 + 1)
    assert asha["trend_ratio"] == 3.0
    assert asha["components"]["trend"] == 1.0


def test_timeofday_has_every_bucket_for_every_engineer(scope):
    rows = by_id(timeofday_counts(scope))
    assert rows[1] == {"engineer_id": 1, "name": "Asha", "team": "SRE",
                       "night": 1, "morning": 1, "afternoon": 0, "evening": 0}
    assert rows[3]["night"] == rows[3]["afternoon"] == 0


def test_empty_window():
    scope = scope_for(None, alerts=make_alerts().iloc[0:0])
    assert team_fairness(scope)["gini"] == 0.0
    assert all(s["score"] == 0 for s in burnout_scores(scope))
    assert all(r["night"] == 0 for r in timeofday_counts(scope))
