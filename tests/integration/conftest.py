import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from semantic_db.infrastructure.db.session import create_engine, create_session_factory
from semantic_db.infrastructure.db.session_types import SessionFactory
from semantic_db.settings import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:pg17"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """One migrated Postgres for the whole session.

    The URL is exported so the CLI's own settings pick it up — test code never
    branches on where the database came from (PRD 11).
    """
    with PostgresContainer(IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        os.environ["SEMANTIC_DB_DATABASE_URL"] = url
        get_settings.cache_clear()

        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option(
            "script_location", str(REPO_ROOT / "src/semantic_db/infrastructure/db/migrations")
        )
        command.upgrade(config, "head")

        yield url

        get_settings.cache_clear()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url)


@pytest.fixture
async def session_factory(database_url: str) -> AsyncIterator[SessionFactory]:
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE collections RESTART IDENTITY CASCADE"))
    yield create_session_factory(engine)
    await engine.dispose()
