from fastapi import FastAPI
from src.routers import health,score

app = FastAPI(title="Fairness Scorer",version="0.0.1")
app.include_router(health.router)
app.include_router(score.router)

