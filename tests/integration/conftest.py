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

    An already-running database wins if `SEMANTIC_DB_DATABASE_URL` is set — that is how CI
    reaches its service container (PRD 11). Otherwise testcontainers starts one, which is
    what happens locally. Either way the URL is exported so the CLI's own settings pick it
    up, and the tests themselves never branch on where the database came from.
    """
    provided = os.environ.get("SEMANTIC_DB_DATABASE_URL")
    if provided:
        get_settings.cache_clear()  # alembic's env.py reads the URL through the same cache
        _migrate()
        yield provided
        get_settings.cache_clear()
        return

    with PostgresContainer(IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        os.environ["SEMANTIC_DB_DATABASE_URL"] = url
        get_settings.cache_clear()

        _migrate()

        yield url

        get_settings.cache_clear()


def _migrate() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(REPO_ROOT / "src/semantic_db/infrastructure/db/migrations")
    )
    command.upgrade(config, "head")


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
