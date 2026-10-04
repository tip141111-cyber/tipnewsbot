import asyncio

from alembic import context
from sqlalchemy import Connection

from tipnews.adapters.persistence.database import create_engine
from tipnews.adapters.persistence.models import Base
from tipnews.config import Settings


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_engine(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


asyncio.run(online())
