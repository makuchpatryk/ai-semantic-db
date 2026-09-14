import pytest

from semantic_db.application.use_cases.add_record import AddRecord, AddRecordCommand
from semantic_db.application.use_cases.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from semantic_db.application.use_cases.delete_collection import (
    DeleteCollection,
    DeleteCollectionCommand,
)
from semantic_db.application.use_cases.delete_record import DeleteRecord, DeleteRecordCommand
from semantic_db.application.use_cases.edit_record import EditRecord, EditRecordCommand
from semantic_db.application.use_cases.search_records import SearchRecords, SearchRecordsCommand
from semantic_db.domain.errors import (
    CollectionNotFoundError,
    DuplicateCollectionError,
    EmbeddingModelMismatchError,
    EmbeddingUnavailableError,
    MissingRequiredFieldError,
    RecordNotFoundError,
    SchemaError,
    UnknownFieldError,
)
from tests.fakes import (
    BrokenEmbeddingProvider,
    FakeEmbeddingProvider,
    InMemoryCollectionRepository,
    InMemoryRecordRepository,
)
from tests.schemas import BOOKS, PRODUCTS

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


async def test_delete_record_removes_the_target_and_leaves_others_untouched() -> None:
    collections, records = await _seeded()
    add = AddRecord(collections, records, FakeEmbeddingProvider())
    kept = await add.execute(AddRecordCommand("products", PRODUCT_VALUES))
    target = await add.execute(AddRecordCommand("products", {**PRODUCT_VALUES, "title": "Other"}))
    assert target.id is not None

    await DeleteRecord(collections, records).execute(DeleteRecordCommand("products", target.id))

    remaining_ids = [r.id for r in records.records]
    assert remaining_ids == [kept.id]


async def test_delete_record_rejects_an_unknown_collection() -> None:
    _, records = await _seeded()
    use_case = DeleteRecord(InMemoryCollectionRepository(), records)

    with pytest.raises(CollectionNotFoundError):
        await use_case.execute(DeleteRecordCommand("products", 1))


async def test_delete_record_rejects_an_unknown_record_id() -> None:
    collections, records = await _seeded()
    use_case = DeleteRecord(collections, records)

    with pytest.raises(RecordNotFoundError):
        await use_case.execute(DeleteRecordCommand("products", 999))


async def _seeded_books() -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository]:
    collections = InMemoryCollectionRepository()
    await CreateCollection(collections).execute(
        CreateCollectionCommand(name="books", fields=BOOKS.fields)
    )
    return collections, InMemoryRecordRepository()


BOOK_VALUES = {
    "author": "Stanisław Lem",
    "published": "1961-05-04",
    "genres": "sci-fi, philosophy",
    "in_print": "y",
    "shelf_code": "A-12",
}


async def test_edit_record_merges_set_onto_the_existing_payload() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )
    assert added.id is not None

    result = await EditRecord(collections, records, embedder).execute(
        EditRecordCommand("products", added.id, {"price": "4300"}, frozenset())
    )

    assert result.record.payload["price"] == 4300.0
    assert result.record.payload["title"] == "Hydraulic pump HP-400"  # untouched fields survive


async def test_edit_record_unset_removes_an_optional_field() -> None:
    collections, records = await _seeded_books()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("books", BOOK_VALUES)
    )
    assert added.id is not None

    result = await EditRecord(collections, records, embedder).execute(
        EditRecordCommand("books", added.id, {}, frozenset({"genres"}))
    )

    assert "genres" not in result.record.payload
    assert "Genres" not in result.record.rendered


async def test_edit_record_unset_on_a_required_field_raises() -> None:
    collections, records = await _seeded_books()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("books", BOOK_VALUES)
    )
    assert added.id is not None

    with pytest.raises(MissingRequiredFieldError):
        await EditRecord(collections, records, embedder).execute(
            EditRecordCommand("books", added.id, {}, frozenset({"author"}))
        )


async def test_edit_record_rejects_an_unknown_field_in_set() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )
    assert added.id is not None

    with pytest.raises(UnknownFieldError):
        await EditRecord(collections, records, embedder).execute(
            EditRecordCommand("products", added.id, {"weight": "10"}, frozenset())
        )


async def test_edit_record_rejects_an_unknown_field_in_unset() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )
    assert added.id is not None

    with pytest.raises(UnknownFieldError):
        await EditRecord(collections, records, embedder).execute(
            EditRecordCommand("products", added.id, {}, frozenset({"weight"}))
        )


async def test_edit_record_editing_only_a_non_embed_field_skips_reembed() -> None:
    collections, records = await _seeded_books()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("books", BOOK_VALUES)
    )
    assert added.id is not None
    stored_vec = records.vectors[0]
    embedder.calls.clear()

    result = await EditRecord(collections, records, embedder).execute(
        EditRecordCommand("books", added.id, {"shelf_code": "B-01"}, frozenset())
    )

    assert result.reembedded is False
    assert embedder.calls == []
    assert records.vectors[0] == stored_vec  # untouched, byte-identical


async def test_edit_record_editing_an_embed_field_reembeds_once() -> None:
    collections, records = await _seeded_books()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("books", BOOK_VALUES)
    )
    assert added.id is not None
    embedder.calls.clear()

    result = await EditRecord(collections, records, embedder).execute(
        EditRecordCommand("books", added.id, {"author": "Stanislaw Lem"}, frozenset())
    )

    assert result.reembedded is True
    assert embedder.calls == [[result.record.rendered]]
    assert records.vectors[0] == embedder._vector(result.record.rendered)


async def test_edit_record_coercion_does_not_falsely_trigger_reembed() -> None:
    """4200 vs 4200.0 must compare equal post-coercion, or an untouched field would
    look 'changed' and waste an embed call."""
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    added = await AddRecord(collections, records, embedder).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )
    assert added.id is not None
    embedder.calls.clear()

    result = await EditRecord(collections, records, embedder).execute(
        EditRecordCommand("products", added.id, {"price": "4200"}, frozenset())
    )

    assert result.reembedded is False
    assert embedder.calls == []


async def test_edit_record_embedder_failure_writes_nothing() -> None:
    collections, records = await _seeded_books()
    added = await AddRecord(collections, records, FakeEmbeddingProvider()).execute(
        AddRecordCommand("books", BOOK_VALUES)
    )
    assert added.id is not None
    original = records.records[0]

    with pytest.raises(EmbeddingUnavailableError):
        await EditRecord(collections, records, BrokenEmbeddingProvider()).execute(
            EditRecordCommand("books", added.id, {"author": "Someone Else"}, frozenset())
        )

    assert records.records[0] == original  # nothing committed


async def test_edit_record_rejects_an_unknown_collection() -> None:
    _, records = await _seeded()
    use_case = EditRecord(InMemoryCollectionRepository(), records, FakeEmbeddingProvider())

    with pytest.raises(CollectionNotFoundError):
        await use_case.execute(EditRecordCommand("products", 1, {"price": "1"}, frozenset()))


async def test_edit_record_rejects_an_unknown_record_id() -> None:
    collections, records = await _seeded()
    use_case = EditRecord(collections, records, FakeEmbeddingProvider())

    with pytest.raises(RecordNotFoundError):
        await use_case.execute(EditRecordCommand("products", 999, {"price": "1"}, frozenset()))


async def test_delete_collection_removes_it() -> None:
    collections, _ = await _seeded()

    await DeleteCollection(collections).execute(DeleteCollectionCommand("products"))

    assert await collections.get("products") is None


async def test_delete_collection_rejects_an_unknown_name() -> None:
    collections = InMemoryCollectionRepository()

    with pytest.raises(CollectionNotFoundError):
        await DeleteCollection(collections).execute(DeleteCollectionCommand("ghosts"))


async def _with_records(
    *titles: str,
) -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository, FakeEmbeddingProvider]:
    """A products collection holding one record per title, embedded by the fake provider."""
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    add = AddRecord(collections, records, embedder)
    for title in titles:
        await add.execute(AddRecordCommand("products", {**PRODUCT_VALUES, "title": title}))
    embedder.calls.clear()
    return collections, records, embedder


async def test_search_embeds_the_query_and_nothing_else() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B")

    await SearchRecords(collections, records, embedder).execute(
        SearchRecordsCommand("products", "quiet pump", k=10)
    )

    assert embedder.calls == [["quiet pump"]]


async def test_search_ranks_the_nearest_record_first() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B", "Pump C")
    # The fake embeds text deterministically, so a record's own card is its own nearest hit.
    target = records.records[1]

    result = await SearchRecords(collections, records, embedder).execute(
        SearchRecordsCommand("products", target.rendered, k=10)
    )

    assert [hit.record.id for hit in result.hits][0] == target.id
    assert result.hits[0].distance == pytest.approx(0.0)
    distances = [hit.distance for hit in result.hits]
    assert distances == sorted(distances)


async def test_search_returns_at_most_k_hits() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B", "Pump C")

    result = await SearchRecords(collections, records, embedder).execute(
        SearchRecordsCommand("products", "pump", k=2)
    )

    assert len(result.hits) == 2


async def test_search_returns_the_schema_the_cli_renders_with() -> None:
    collections, records, embedder = await _with_records("Pump A")

    result = await SearchRecords(collections, records, embedder).execute(
        SearchRecordsCommand("products", "pump", k=10)
    )

    assert result.schema == PRODUCTS


async def test_search_rejects_an_unknown_collection() -> None:
    collections, records, embedder = await _with_records("Pump A")

    with pytest.raises(CollectionNotFoundError):
        await SearchRecords(collections, records, embedder).execute(
            SearchRecordsCommand("ghosts", "pump", k=10)
        )


async def test_search_on_an_empty_collection_returns_no_hits() -> None:
    """No records means no stored model, which must not read as a model mismatch."""
    collections, records = await _seeded()

    result = await SearchRecords(collections, records, FakeEmbeddingProvider()).execute(
        SearchRecordsCommand("products", "pump", k=10)
    )

    assert result.hits == []
    assert result.schema == PRODUCTS


async def test_search_rejects_a_collection_embedded_with_another_model() -> None:
    collections, _ = await _seeded()
    records = InMemoryRecordRepository(model_name="bge-m3")
    await AddRecord(collections, records, FakeEmbeddingProvider("bge-m3")).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )
    switched = FakeEmbeddingProvider("nomic-embed-text")

    with pytest.raises(EmbeddingModelMismatchError, match="bge-m3"):
        await SearchRecords(collections, records, switched).execute(
            SearchRecordsCommand("products", "pump", k=10)
        )

    assert switched.calls == []  # the guard runs before the query is embedded
