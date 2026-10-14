"""Scoring several teams at once: each team is compared within itself."""
import pandas as pd
import pytest

from src.services.burnout import burnout_scores
from src.services.fairness import gini, team_fairness
from tests.conftest import IST, scope_for


def two_teams() -> pd.DataFrame:
    return pd.DataFrame({
        "engineer_id": [1, 2, 3, 4],
        "name": ["Asha", "Bala", "Chen", "Dev"],
        "team": ["SRE", "SRE", "Platform", "Platform"],
        "active": [True, True, True, True],
        "team_id": [1, 1, 2, 2],
        "timezone": ["Asia/Kolkata"] * 4,
    })


def even_alerts(pages: dict[int, int]) -> pd.DataFrame:
    """Identical P3s on weekday mornings, open 30 minutes: ``pages`` maps engineer id to how many."""
    rows = []
    for engineer_id, count in pages.items():
        for i in range(count):
            local = pd.Timestamp("2026-09-22 10:00") + pd.Timedelta(days=i % 3, hours=engineer_id)
            rows.append({"engineer_id": engineer_id, "triggered_at_local": local})
    local = pd.to_datetime([r["triggered_at_local"] for r in rows])
    return pd.DataFrame({
        "alert_id": range(1, len(rows) + 1),
        "engineer_id": [r["engineer_id"] for r in rows],
        "severity": ["P3"] * len(rows),
        "triggered_at": local - IST,
        "resolved_at": local - IST + pd.Timedelta(minutes=30),
        "acknowledged_at": pd.NaT,
        "triggered_at_local": local,
        "escalation_count": 0,
    })


# Each team shares its work evenly, but SRE is four times as busy as Platform
BUSY_AND_QUIET = {1: 8, 2: 8, 3: 2, 4: 2}


def test_several_teams_are_each_compared_within_themselves():
    report = team_fairness(scope_for(None, engineers=two_teams(), alerts=even_alerts(BUSY_AND_QUIET)))

    teams = {t["team"]: t for t in report["teams"]}
    assert set(teams) == {"SRE", "Platform"}
    assert teams["SRE"]["gini"] == 0.0 and teams["Platform"]["gini"] == 0.0
    assert teams["SRE"]["alert_count"] == 16 and teams["Platform"]["engineer_count"] == 2
    # Even within every team, so even overall; pooling all four would have read SRE's volume as unfairness
    assert report["gini"] == 0.0 and report["label"] == "FAIR"
    pooled = gini(pd.Series([e["load"] for e in report["engineers"]]).to_numpy())
    assert pooled > 0.2


def test_the_average_is_weighted_by_alerts():
    # SRE uneven (Asha does everything), Platform even; SRE has 4x the alerts
    report = team_fairness(scope_for(None, engineers=two_teams(), alerts=even_alerts({1: 8, 3: 1, 4: 1})))

    teams = {t["team"]: t for t in report["teams"]}
    assert teams["SRE"]["gini"] == 0.5 and teams["Platform"]["gini"] == 0.0
    assert report["gini"] == pytest.approx((0.5 * 8 + 0.0 * 2) / 10, abs=0.001)


def test_one_team_scores_exactly_as_before():
    report = team_fairness(scope_for("SRE", engineers=two_teams(), alerts=even_alerts({1: 8, 2: 2})))

    assert report["teams"] == [
        {"team": "SRE", "gini": report["gini"], "label": report["label"], "rotation_gini": None,
         "alert_count": 10, "engineer_count": 2}]
    loads = pd.Series([e["load"] for e in report["engineers"]]).to_numpy()
    assert report["gini"] == pytest.approx(gini(loads), abs=0.001)


def test_burnout_compares_load_with_the_engineers_own_team():
    burnout = {b["engineer_id"]: b for b in burnout_scores(
        scope_for(None, engineers=two_teams(), alerts=even_alerts(BUSY_AND_QUIET)))}

    # Everyone carries exactly their team's average: half the cap, whatever the team's volume
    assert {b["components"]["relative_load"] for b in burnout.values()} == {0.5}


def test_a_team_without_shifts_keeps_its_active_engineers():
    # SRE has a rotation (Asha); Platform has no shifts at all
    oncall = pd.DataFrame({"engineer_id": [1], "escalation_level": [1],
                           "starts_at": pd.to_datetime(["2026-09-01"]),
                           "ends_at": pd.to_datetime(["2026-09-30"])})
    report = team_fairness(scope_for(None, engineers=two_teams(), alerts=even_alerts({1: 4, 3: 2}),
                                     oncall=oncall))

    ids = {e["engineer_id"] for e in report["engineers"]}
    # Bala: on SRE's rotation basis and neither on call nor paged, so not compared. Dev: Platform has no
    # rotation, so as an active engineer with no pages he counts (as 0 load)
    assert ids == {1, 3, 4}
