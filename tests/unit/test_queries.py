import pytest

from semantic_db.application.queries import Queries
from semantic_db.domain.collection import Collection, CollectionSchema, FieldDefinition
from semantic_db.domain.errors import CollectionNotFoundError, RecordNotFoundError
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import Record
from tests.fakes import InMemoryCollectionRepository, InMemoryRecordRepository


@pytest.fixture
async def repos() -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository]:
    collections = InMemoryCollectionRepository()
    records = InMemoryRecordRepository()
    collections._record_repo = records
    return collections, records


@pytest.mark.asyncio
async def test_list_collections(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    # Create two collections
    schema1 = CollectionSchema(
        fields=(
            FieldDefinition(name="title", type=FieldType.TEXT, embed=True),
            FieldDefinition(name="description", type=FieldType.TEXT, embed=False),
        )
    )
    schema2 = CollectionSchema(
        fields=(FieldDefinition(name="name", type=FieldType.TEXT, embed=True),)
    )
    coll1 = await collections.create(Collection(name="products", schema=schema1))
    coll2 = await collections.create(Collection(name="articles", schema=schema2))
    assert coll1.id is not None
    assert coll2.id is not None

    # Add some records to coll1
    for i in range(3):
        record = Record(
            collection_id=coll1.id,
            payload={"title": f"Product {i}"},
            rendered=f"Product {i}",
        )
        await records.add(coll1.id, record, [0.0] * 1024)

    # Add one record to coll2
    record = Record(
        collection_id=coll2.id,
        payload={"name": "Article 1"},
        rendered="Article 1",
    )
    await records.add(coll2.id, record, [0.0] * 1024)

    summaries = await queries.list_collections()

    # Should be sorted by name
    assert len(summaries) == 2
    assert summaries[0].name == "articles"
    assert summaries[0].field_count == 1
    assert summaries[0].record_count == 1

    assert summaries[1].name == "products"
    assert summaries[1].field_count == 2
    assert summaries[1].record_count == 3


@pytest.mark.asyncio
async def test_list_records_pagination(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    schema = CollectionSchema(
        fields=(FieldDefinition(name="title", type=FieldType.TEXT, embed=True),)
    )

    coll = await collections.create(Collection(name="products", schema=schema))
    assert coll.id is not None

    # Add 25 records
    for i in range(25):
        record = Record(
            collection_id=coll.id,
            payload={"title": f"Product {i}"},
            rendered=f"Product {i}",
        )
        await records.add(coll.id, record, [0.0] * 1024)

    # Get first page (limit 10)
    page = await queries.list_records("products", limit=10, offset=0)
    assert len(page.records) == 10
    assert page.total == 25
    assert page.limit == 10
    assert page.offset == 0

    # Get second page
    page = await queries.list_records("products", limit=10, offset=10)
    assert len(page.records) == 10
    assert page.total == 25
    assert page.offset == 10

    # Get third page (only 5 left)
    page = await queries.list_records("products", limit=10, offset=20)
    assert len(page.records) == 5
    assert page.total == 25

    # Offset past end returns empty page with true total
    page = await queries.list_records("products", limit=10, offset=30)
    assert len(page.records) == 0
    assert page.total == 25


@pytest.mark.asyncio
async def test_show_record_not_found(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    schema = CollectionSchema(
        fields=(FieldDefinition(name="title", type=FieldType.TEXT, embed=True),)
    )
    coll = await collections.create(Collection(name="products", schema=schema))
    assert coll.id is not None

    # Try to show non-existent record
    with pytest.raises(RecordNotFoundError) as exc_info:
        await queries.show_record("products", 999)
    assert "record 999 not found in collection 'products'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_show_record_wrong_collection(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    schema = CollectionSchema(
        fields=(FieldDefinition(name="title", type=FieldType.TEXT, embed=True),)
    )
    coll1 = await collections.create(Collection(name="products", schema=schema))
    coll2 = await collections.create(Collection(name="articles", schema=schema))
    assert coll1.id is not None
    assert coll2.id is not None

    # Add a record to coll1
    record = Record(
        collection_id=coll1.id,
        payload={"title": "Product 1"},
        rendered="Product 1",
    )
    added = await records.add(coll1.id, record, [0.0] * 1024)
    assert added.id is not None

    # Try to show it from coll2
    with pytest.raises(RecordNotFoundError) as exc_info:
        await queries.show_record("articles", added.id)
    assert f"record {added.id} not found in collection 'articles'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_show_collection_not_found(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    with pytest.raises(CollectionNotFoundError):
        await queries.show_collection("nonexistent")


@pytest.mark.asyncio
async def test_show_record(
    repos: tuple[InMemoryCollectionRepository, InMemoryRecordRepository],
) -> None:
    collections, records = repos
    queries = Queries(collections, records)

    schema = CollectionSchema(
        fields=(FieldDefinition(name="title", type=FieldType.TEXT, embed=True),)
    )
    coll = await collections.create(Collection(name="products", schema=schema))
    assert coll.id is not None

    record = Record(
        collection_id=coll.id,
        payload={"title": "Product 1"},
        rendered="Product 1",
    )
    added = await records.add(coll.id, record, [0.0] * 1024)
    assert added.id is not None

    view = await queries.show_record("products", added.id)

    assert view.detail.record.id == added.id
    assert view.detail.record.payload["title"] == "Product 1"
    assert view.detail.model == "fake-model"
