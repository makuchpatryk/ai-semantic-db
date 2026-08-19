import pytest

from semantic_db.application.use_cases.add_record import AddRecord, AddRecordCommand
from semantic_db.application.use_cases.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from semantic_db.domain.errors import (
    CollectionNotFoundError,
    DuplicateCollectionError,
    EmbeddingUnavailableError,
    MissingRequiredFieldError,
    SchemaError,
)
from tests.fakes import (
    BrokenEmbeddingProvider,
    FakeEmbeddingProvider,
    InMemoryCollectionRepository,
    InMemoryRecordRepository,
)
from tests.schemas import PRODUCTS

PRODUCT_VALUES = {
    "title": "Hydraulic pump HP-400",
    "category": "pumps",
    "year": "2019",
    "price": "4200",
}


async def test_create_collection_persists_and_assigns_an_id() -> None:
    collections = InMemoryCollectionRepository()
    use_case = CreateCollection(collections)

    collection = await use_case.execute(
        CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    )

    assert collection.id == 1
    assert collections.collections["products"].schema == PRODUCTS


async def test_create_collection_rejects_a_duplicate_name() -> None:
    collections = InMemoryCollectionRepository()
    use_case = CreateCollection(collections)
    cmd = CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    await use_case.execute(cmd)

    with pytest.raises(DuplicateCollectionError):
        await use_case.execute(cmd)


async def test_create_collection_rejects_a_schema_with_nothing_embedded() -> None:
    use_case = CreateCollection(InMemoryCollectionRepository())
    fields = tuple(field.model_copy(update={"embed": False}) for field in PRODUCTS.fields)

    with pytest.raises(SchemaError, match="at least one field must be embedded"):
        await use_case.execute(CreateCollectionCommand(name="products", fields=fields))


async def _seeded() -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository]:
    collections = InMemoryCollectionRepository()
    await CreateCollection(collections).execute(
        CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    )
    return collections, InMemoryRecordRepository()


async def test_add_record_renders_embeds_and_stores() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    use_case = AddRecord(collections, records, embedder)

    record = await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))

    assert record.id == 1
    assert record.payload["year"] == 2019
    assert record.rendered.startswith("Title: Hydraulic pump HP-400")
    assert embedder.calls == [[record.rendered]]  # the stored text is the embedded text
    assert len(records.vectors[0]) == embedder.dim


async def test_add_record_rejects_an_unknown_collection() -> None:
    _, records = await _seeded()
    use_case = AddRecord(InMemoryCollectionRepository(), records, FakeEmbeddingProvider())

    with pytest.raises(CollectionNotFoundError):
        await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))


async def test_add_record_validates_before_embedding() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    use_case = AddRecord(collections, records, embedder)

    with pytest.raises(MissingRequiredFieldError):
        await use_case.execute(AddRecordCommand("products", {"year": "2019"}))

    assert embedder.calls == []
    assert records.records == []


async def test_add_record_rejects_a_wrong_dimension_vector() -> None:
    collections, records = await _seeded()
    use_case = AddRecord(collections, records, BrokenEmbeddingProvider())

    with pytest.raises(EmbeddingUnavailableError, match="1023 dimensions, expected 1024"):
        await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))

    assert records.records == []
