from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from semantic_db.infrastructure.db.session_types import SessionFactory


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)
