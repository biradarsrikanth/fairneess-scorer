# Scoring model (v1)

All constants live in `src/services/model.py`. Time of day (night, evening, weekend) uses each engineer's
**team timezone** (`team.timezone`, converted in the `scoring_alert_v` view); durations and trends use UTC.
`TEAM_TIMEZONE` only sets how `start`/`end` dates and the reported window are interpreted.

## 0. Pages

Scores are built from **pages**: every time an engineer was paged for an alert.
- The first-paged engineer (`alert_event.engineer_id`) carries the alert's full load.
- Engineers it was **escalated or reassigned** to (`alert_assignment`) carry `ESCALATION_LOAD_SHARE` = 50% of
  its load on top: they were woken up too, but the first responder usually did more of the work.
- `alert_count` counts first pages; `escalations_received` counts the rest.

## 1. Load of one alert

Counting alerts treats a two-minute P4 the same as a three-hour P1 at 3 a.m. Each alert therefore gets a
**load**:

```
load = severity_weight × duration_factor × time_multiplier
```

| Factor | Values | Why |
|---|---|---|
| `severity_weight` | P1 = 4, P2 = 3, P3 = 2, P4 = 1, P5 = 1, missing = 2 | Higher priority means more pressure and more people watching |
| `duration_factor` | `1 + min(hours open, 4) / 4`, so 1.0 to 2.0 | Longer incidents cost more; capped so one stuck incident can't dominate. Open incidents count up to the end of the window |
| `time_multiplier` | 1.0 daytime, +0.25 evening (18:00–23:00), +0.5 night (23:00–06:00), +0.25 weekend | Out-of-hours pages cost sleep and personal time |

## 2. Fairness: Gini coefficient of load

The Gini coefficient of load across engineers: 0 means perfectly even, 1 means one person does everything.

Who is compared (`basis`):
- **`ONCALL_ROTATION`** when on-call shifts exist for the scope: engineers with primary (level 1) on-call time
  in the window, plus anyone paged anyway. Someone off the rotation with no pages isn't "lucky", just not on
  call, so they are left out. The report adds `oncall_hours`, `load_per_oncall_hour` and **`rotation_gini`**
  (the Gini of on-call hours: is the rotation itself even?).
- **`ACTIVE_ENGINEERS`** without shift data: every active engineer, with 0 load if they had no alerts
  (excluding them would hide the most uneven cases), plus inactive engineers who had alerts.
- Scope is one team (`team=`) or everyone. Comparing across teams with different rotations is usually less
  meaningful, so prefer a team filter.

| Gini | Label |
|---|---|
| < 0.2 | FAIR |
| < 0.4 | MODERATE |
| < 0.6 | UNEQUAL |
| ≥ 0.6 | CRITICAL |

`confidence` is `LOW` when there are fewer than 20 alerts or fewer than 3 engineers; a single alert can swing
the Gini a lot at that size, so treat the label as indicative only.

## 3. Burnout score (0–100)

Three components, each between 0 and 1:

| Component | Weight | Definition |
|---|---|---|
| `exposure` | 50 | Average per alert of `min(1, night × 1.0 + evening × 0.5 + weekend × 0.5)` |
| `relative_load` | 30 | Engineer's load ÷ (2 × mean load of engineers in scope), capped at 1; twice the average is the maximum |
| `trend` | 20 | `min(1, max(0, ratio − 1))` with `ratio = (pages in last 30 days + 1) / (pages in the 30 days before + 1)`; doubling is the maximum, and no data at all gives 0 |

```
burnout = (50 × exposure + 30 × relative_load + 20 × trend) × confidence
confidence = min(1, pages / 5)
```

Also reported, not part of the score: `median_ack_minutes` (time from trigger to acknowledgement of first
pages, from the incident log) and `oncall_hours`.

The confidence factor stops one night-time alert from producing a HIGH score. The 30-day windows are
measured back from the end of the scoring window, so historical windows are scored consistently.

| Score | Risk |
|---|---|
| < 30 | LOW |
| < 60 | MEDIUM |
| ≥ 60 | HIGH |

## 4. Time of day

Pages per engineer in four local-time buckets (team timezone): Night 23:00–06:00, Morning 06:00–12:00,
Afternoon 12:00–18:00, Evening 18:00–23:00. Every bucket is always present.

## Changing the model

Constants are product decisions; change them in `model.py` together with this document and the unit tests
in `tests/test_services.py`.
