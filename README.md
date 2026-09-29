# fairneess-scorer

Internal FastAPI service that scores on-call fairness and burnout from PagerDuty alerts. It is called only
by the [Fairness-Checker](https://github.com/biradarsrikanth/Fairness-Checker) gateway; see its
`docs/ARCHITECTURE.md` for how the two fit together, and [docs/SCORING.md](docs/SCORING.md) for the model.

## API

All `/v1` routes need the `X-API-Key` header. Interactive docs: `http://localhost:8000/docs`.

| Route | Returns |
|---|---|
| `GET /v1/scores/fairness` | Gini of on-call load, per-engineer share |
| `GET /v1/scores/burnout` | Burnout score (0–100) and its components per engineer |
| `GET /v1/scores/timeofday` | Alert counts per engineer by night / morning / afternoon / evening |
| `GET /v1/scores/engineers/{id}` | All of the above for one engineer, within their team |
| `GET /health/live`, `GET /health` | Liveness; readiness (includes database) |
| `GET /metrics` | Prometheus metrics |

Window: `days` (default 365, max 3650) **or** `start`/`end` ISO dates (inclusive, team timezone).
Scope: optional `team`.

## Run locally

```bash
cp .env.example .env         # then fill in AZURE_DB_URL and SCORER_API_KEY
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/uvicorn src.main:app --reload
```

### With Docker

```bash
cp .env.example .env              # AZURE_DB_URL and SCORER_API_KEY (same key as the gateway)
docker network create fairness-net   # once per machine; shared with Fairness-Checker
docker compose up --build
```

The compose file doesn't run a database; it connects to the one in `AZURE_DB_URL`. The gateway, started from
its own repo on `fairness-net`, reaches this service at `http://scorer:8000`.

## Checks

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy
.venv/bin/pytest                      # unit tests; integration tests skip without a database
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres .venv/bin/pytest
```

## Layout

```
src/
  main.py            app, middleware, error handlers, metrics
  core/              settings, logging, API-key auth, request-id middleware
  db/                engine, queries (views only), cached loader
  schemas/           response models (the v1 contract)
  services/          scoring model: pure functions over DataFrames
  api/               dependencies (window, scope) and routes
tests/               unit, API and integration tests
```
