import pytest
from sqlalchemy import select

from semantic_db.domain.collection import Collection
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Payload, Record
from semantic_db.domain.rendering import render
from semantic_db.infrastructure.db.models import EmbeddingModel, RecordModel
from semantic_db.infrastructure.db.session_types import SessionFactory
from semantic_db.infrastructure.mappers import payload_from_jsonb
from semantic_db.infrastructure.repositories import SqlCollectionRepository, SqlRecordRepository
from tests.schemas import BOOKS, PRODUCTS

pytestmark = pytest.mark.integration

VECTOR = [0.01] * 1024


async def test_collection_round_trips_through_jsonb(session_factory: SessionFactory) -> None:
    repository = SqlCollectionRepository(session_factory)

    created = await repository.create(Collection(name="products", schema=PRODUCTS))
    loaded = await repository.get("products")

    assert created.id is not None
    assert loaded is not None
    assert loaded.schema == PRODUCTS  # enum values, flags and units all survive


async def test_get_returns_none_for_an_unknown_collection(session_factory: SessionFactory) -> None:
    assert await SqlCollectionRepository(session_factory).get("nothing") is None


async def test_duplicate_name_is_rejected_by_the_database(session_factory: SessionFactory) -> None:
    repository = SqlCollectionRepository(session_factory)
    await repository.create(Collection(name="products", schema=PRODUCTS))

    with pytest.raises(DuplicateCollectionError):
        await repository.create(Collection(name="products", schema=PRODUCTS))


async def test_add_writes_record_and_embedding_together(session_factory: SessionFactory) -> None:
    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="products", schema=PRODUCTS))
    assert collection.id is not None
    records = SqlRecordRepository(session_factory, "bge-m3")

    payload: Payload = {"title": "Pump", "category": "pumps", "year": 2019, "price": 4200.0}
    rendered = render(PRODUCTS, payload)
    stored = await records.add(collection.id, Record(collection.id, payload, rendered), VECTOR)

    async with session_factory() as session:
        embedding = await session.get(EmbeddingModel, stored.id)
        assert embedding is not None
        assert embedding.model == "bge-m3"
        assert len(embedding.vec) == 1024


async def test_rendered_text_matches_a_freshly_loaded_payload(
    session_factory: SessionFactory,
) -> None:
    """payload, rendered and vec must describe the same version of the record."""
    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="books", schema=BOOKS))
    assert collection.id is not None
    records = SqlRecordRepository(session_factory, "bge-m3")

    from datetime import date

    payload: Payload = {
        "author": "Lem",
        "published": date(1961, 5, 4),
        "genres": ["sci-fi", "philosophy"],
        "in_print": True,
    }
    rendered = render(BOOKS, payload)
    await records.add(collection.id, Record(collection.id, payload, rendered), VECTOR)

    async with session_factory() as session:
        model = await session.scalar(select(RecordModel))
        assert model is not None
        reloaded = payload_from_jsonb(BOOKS, model.payload)
        assert render(BOOKS, reloaded) == model.rendered  # dates survive JSONB


async def test_deleting_a_collection_cascades(session_factory: SessionFactory) -> None:
    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="products", schema=PRODUCTS))
    assert collection.id is not None
    records = SqlRecordRepository(session_factory, "bge-m3")
    payload = {"title": "Pump"}
    await records.add(
        collection.id, Record(collection.id, payload, render(PRODUCTS, payload)), VECTOR
    )

    async with session_factory() as session, session.begin():
        from sqlalchemy import text

        await session.execute(text("DELETE FROM collections WHERE name = 'products'"))

    async with session_factory() as session:
        assert (await session.scalars(select(RecordModel))).all() == []
        assert (await session.scalars(select(EmbeddingModel))).all() == []
