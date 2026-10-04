from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: str) -> AsyncEngine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, ":memory:"}:
        Path(str(parsed.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, echo=False)
    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_options(connection: Any, record: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine
