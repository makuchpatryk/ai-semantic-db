from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from semantic_db.application.queries import Queries
from semantic_db.application.use_cases.add_record import AddRecord
from semantic_db.application.use_cases.create_collection import CreateCollection
from semantic_db.application.use_cases.search_records import SearchRecords
from semantic_db.infrastructure.db.session import create_engine, create_session_factory
from semantic_db.infrastructure.ollama import OllamaEmbeddingProvider
from semantic_db.infrastructure.repositories import SqlCollectionRepository, SqlRecordRepository
from semantic_db.settings import Settings, get_settings


@dataclass(frozen=True)
class Container:
    """Everything the CLI is allowed to see. The only place that wires."""

    create_collection: CreateCollection
    add_record: AddRecord
    search_records: SearchRecords
    queries: Queries
    embedding_model: str


@asynccontextmanager
async def build_container(settings: Settings | None = None) -> AsyncIterator[Container]:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    collections = SqlCollectionRepository(session_factory)
    records = SqlRecordRepository(session_factory, settings.embedding_model)
    embedder = OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.embedding_model,
        dim=settings.embedding_dim,
    )

    try:
        yield Container(
            create_collection=CreateCollection(collections),
            add_record=AddRecord(collections, records, embedder),
            search_records=SearchRecords(collections, records, embedder),
            queries=Queries(collections),
            embedding_model=settings.embedding_model,
        )
    finally:
        await engine.dispose()
