from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from src.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the engine on first use, so importing the app doesn't need a database."""
    return create_engine(get_settings().database_url.get_secret_value(),
                         pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800)


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()


def check_connection(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
