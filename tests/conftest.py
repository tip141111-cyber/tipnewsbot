from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from tipnews.adapters.persistence.database import create_engine
from tipnews.adapters.persistence.models import Base
from tipnews.adapters.persistence.repository import SqlStore
from tipnews.domain.models import Article, Topic


@pytest.fixture
async def store() -> AsyncIterator[SqlStore]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield SqlStore(engine)
    await engine.dispose()


@pytest.fixture
def article() -> Article:
    return Article(
        "a1",
        "test",
        "Test source",
        Topic.IT,
        "Release 12",
        "https://example.org/news/12",
        "Version 12 improves storage performance.",
        datetime.now(UTC),
    )
