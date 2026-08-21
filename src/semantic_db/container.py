from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine

from semantic_db.application.queries import Queries
from semantic_db.application.telemetry import NullTelemetry, Telemetry
from semantic_db.application.use_cases.add_record import AddRecord
from semantic_db.application.use_cases.create_collection import CreateCollection
from semantic_db.application.use_cases.search_records import SearchRecords
from semantic_db.infrastructure.db.session import create_engine, create_session_factory
from semantic_db.infrastructure.ollama import OllamaEmbeddingProvider
from semantic_db.infrastructure.repositories import SqlCollectionRepository, SqlRecordRepository
from semantic_db.infrastructure.telemetry.otel import OtelTelemetry
from semantic_db.infrastructure.telemetry.providers import TelemetryProviders, build_providers
from semantic_db.settings import Settings, get_settings


@dataclass(frozen=True)
class Container:
    """Everything the CLI is allowed to see. The only place that wires."""

    create_collection: CreateCollection
    add_record: AddRecord
    search_records: SearchRecords
    queries: Queries
    telemetry: Telemetry
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

    # Inside the try, so a provider that fails to build still disposes the engine.
    providers: TelemetryProviders | None = None
    try:
        telemetry, providers = _build_telemetry(settings, engine)

        yield Container(
            create_collection=CreateCollection(collections, telemetry),
            add_record=AddRecord(collections, records, embedder, telemetry),
            search_records=SearchRecords(collections, records, embedder, telemetry),
            queries=Queries(collections),
            telemetry=telemetry,
            embedding_model=settings.embedding_model,
        )
    finally:
        if providers is not None:
            # Flush before the engine goes: the SQL spans are exported from here, and a
            # disposed engine mid-flush would be a teardown ordering bug.
            _uninstrument()
            providers.shutdown()
        await engine.dispose()


def _build_telemetry(
    settings: Settings, engine: AsyncEngine
) -> tuple[Telemetry, TelemetryProviders | None]:
    """Off means off: no providers, no exporter threads, no instrumentation (plan D5)."""
    if not settings.telemetry_enabled:
        return NullTelemetry(), None

    providers = build_providers(settings.otlp_endpoint)
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine, tracer_provider=providers.tracer_provider
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=providers.tracer_provider)
    return OtelTelemetry(providers.tracer_provider, providers.meter_provider), providers


def _uninstrument() -> None:
    """Instrumentors patch the libraries globally, so a second container in the same
    process — which is what the test suite is — would otherwise double-wrap them."""
    SQLAlchemyInstrumentor().uninstrument()
    HTTPXClientInstrumentor().uninstrument()
