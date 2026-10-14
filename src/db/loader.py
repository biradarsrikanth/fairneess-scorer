from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

import pandas as pd
from cachetools import TTLCache
from sqlalchemy import Engine

from src.db.queries import fetch_alerts, fetch_assignments, fetch_engineers, fetch_oncall


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


class DataLoader:
    """Loads scoring data, caching each query result for a short time.

    Scores change slowly, and the gateway often requests several scores for the same window at once (the
    analytics page asks for four in parallel). Only one of them runs each query; the others wait for its
    result. Callers get copies, so nothing can modify the cached frames. All times are naive UTC, except
    ``triggered_at_local`` (the engineer's team timezone).
    """

    def __init__(self, engine: Engine, ttl_seconds: int) -> None:
        self._engine = engine
        self._cache: TTLCache[tuple, pd.DataFrame] = TTLCache(maxsize=256, ttl=max(ttl_seconds, 1))
        self._enabled = ttl_seconds > 0
        self._lock = Lock()
        # A lock per query being loaded: concurrent callers of the same query wait instead of repeating it
        self._loading: dict[tuple, Lock] = {}

    def alerts(self, start: datetime, end: datetime) -> pd.DataFrame:
        s, e = _utc_naive(start), _utc_naive(end)
        return self._cached(("alerts", s, e), lambda: fetch_alerts(self._engine, s, e))

    def engineers(self) -> pd.DataFrame:
        return self._cached(("engineers",), lambda: fetch_engineers(self._engine))

    def assignments(self, start: datetime, end: datetime) -> pd.DataFrame:
        s, e = _utc_naive(start), _utc_naive(end)
        return self._cached(("assignments", s, e), lambda: fetch_assignments(self._engine, s, e))

    def oncall(self, start: datetime, end: datetime) -> pd.DataFrame:
        s, e = _utc_naive(start), _utc_naive(end)
        return self._cached(("oncall", s, e), lambda: fetch_oncall(self._engine, s, e))

    def _cached(self, key: tuple, load: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        if not self._enabled:
            return load()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                return hit.copy()
            loading = self._loading.setdefault(key, Lock())
        try:
            with loading:
                # Whoever held the lock may have loaded it meanwhile
                with self._lock:
                    hit = self._cache.get(key)
                if hit is None:
                    hit = load()
                    with self._lock:
                        self._cache[key] = hit
        finally:
            with self._lock:
                self._loading.pop(key, None)
        return hit.copy()
