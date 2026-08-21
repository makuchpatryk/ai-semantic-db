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


#: Hand-picked vectors: the query points along axis 0, so distance is known in advance.
QUERY_VEC = [1.0] + [0.0] * 1023
NEAR_VEC = [1.0] + [0.0] * 1023  # identical direction -> distance 0
MID_VEC = [1.0, 1.0] + [0.0] * 1022  # 45 degrees off -> 1 - 1/sqrt(2)
FAR_VEC = [0.0, 1.0] + [0.0] * 1022  # orthogonal -> distance 1


async def _products_with_vectors(
    session_factory: SessionFactory, **titled_vectors: list[float]
) -> tuple[int, SqlRecordRepository]:
    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="products", schema=PRODUCTS))
    assert collection.id is not None
    records = SqlRecordRepository(session_factory, "bge-m3")
    for title, vec in titled_vectors.items():
        payload: Payload = {"title": title}
        await records.add(
            collection.id, Record(collection.id, payload, render(PRODUCTS, payload)), vec
        )
    return collection.id, records


async def test_search_ranks_by_cosine_distance(session_factory: SessionFactory) -> None:
    collection_id, records = await _products_with_vectors(
        session_factory, near=NEAR_VEC, far=FAR_VEC, mid=MID_VEC
    )

    hits = await records.search(collection_id, QUERY_VEC, k=10)

    assert [hit.record.payload["title"] for hit in hits] == ["near", "mid", "far"]
    assert hits[0].distance == pytest.approx(0.0, abs=1e-3)
    assert hits[1].distance == pytest.approx(1 - 2**-0.5, abs=1e-3)
    assert hits[2].distance == pytest.approx(1.0, abs=1e-3)


async def test_search_returns_at_most_k_hits(session_factory: SessionFactory) -> None:
    collection_id, records = await _products_with_vectors(
        session_factory, near=NEAR_VEC, far=FAR_VEC, mid=MID_VEC
    )

    assert len(await records.search(collection_id, QUERY_VEC, k=2)) == 2


async def test_search_never_crosses_collections(session_factory: SessionFactory) -> None:
    collection_id, records = await _products_with_vectors(session_factory, near=NEAR_VEC)
    collections = SqlCollectionRepository(session_factory)
    other = await collections.create(Collection(name="books", schema=BOOKS))
    assert other.id is not None
    payload: Payload = {"author": "Lem"}
    await records.add(other.id, Record(other.id, payload, render(BOOKS, payload)), NEAR_VEC)

    hits = await records.search(collection_id, QUERY_VEC, k=10)

    assert [hit.record.payload["title"] for hit in hits] == ["near"]


async def test_search_hydrates_the_payload_through_the_schema(
    session_factory: SessionFactory,
) -> None:
    """The hit must carry the same typed payload `get` would return, dates included."""
    from datetime import date

    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="books", schema=BOOKS))
    assert collection.id is not None
    records = SqlRecordRepository(session_factory, "bge-m3")
    payload: Payload = {"author": "Lem", "published": date(1961, 5, 4), "genres": ["sci-fi"]}
    await records.add(
        collection.id, Record(collection.id, payload, render(BOOKS, payload)), NEAR_VEC
    )

    hits = await records.search(collection.id, QUERY_VEC, k=1)

    assert hits[0].record.payload == payload
    assert hits[0].record.rendered == render(BOOKS, payload)


async def test_embedding_models_reports_every_model_in_the_collection(
    session_factory: SessionFactory,
) -> None:
    collection_id, records = await _products_with_vectors(session_factory, near=NEAR_VEC)
    switched = SqlRecordRepository(session_factory, "nomic-embed-text")
    payload: Payload = {"title": "other"}
    await switched.add(
        collection_id, Record(collection_id, payload, render(PRODUCTS, payload)), FAR_VEC
    )

    assert await records.embedding_models(collection_id) == frozenset(
        {"bge-m3", "nomic-embed-text"}
    )


async def test_embedding_models_is_empty_for_a_collection_without_records(
    session_factory: SessionFactory,
) -> None:
    collections = SqlCollectionRepository(session_factory)
    collection = await collections.create(Collection(name="products", schema=PRODUCTS))
    assert collection.id is not None

    records = SqlRecordRepository(session_factory, "bge-m3")
    assert await records.embedding_models(collection.id) == frozenset()
