import pytest

from semantic_db.application.use_cases.add_record import AddRecord, AddRecordCommand
from semantic_db.application.use_cases.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from semantic_db.application.use_cases.search_records import SearchRecords, SearchRecordsCommand
from semantic_db.domain.errors import (
    CollectionNotFoundError,
    DuplicateCollectionError,
    EmbeddingModelMismatchError,
    EmbeddingUnavailableError,
    MissingRequiredFieldError,
    SchemaError,
)
from tests.fakes import (
    BrokenEmbeddingProvider,
    FakeEmbeddingProvider,
    InMemoryCollectionRepository,
    InMemoryRecordRepository,
    RecordingTelemetry,
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
    use_case = CreateCollection(collections, RecordingTelemetry())

    collection = await use_case.execute(
        CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    )

    assert collection.id == 1
    assert collections.collections["products"].schema == PRODUCTS


async def test_create_collection_rejects_a_duplicate_name() -> None:
    collections = InMemoryCollectionRepository()
    use_case = CreateCollection(collections, RecordingTelemetry())
    cmd = CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    await use_case.execute(cmd)

    with pytest.raises(DuplicateCollectionError):
        await use_case.execute(cmd)


async def test_create_collection_rejects_a_schema_with_nothing_embedded() -> None:
    use_case = CreateCollection(InMemoryCollectionRepository(), RecordingTelemetry())
    fields = tuple(field.model_copy(update={"embed": False}) for field in PRODUCTS.fields)

    with pytest.raises(SchemaError, match="at least one field must be embedded"):
        await use_case.execute(CreateCollectionCommand(name="products", fields=fields))


async def _seeded() -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository]:
    collections = InMemoryCollectionRepository()
    await CreateCollection(collections, RecordingTelemetry()).execute(
        CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    )
    return collections, InMemoryRecordRepository()


async def test_add_record_renders_embeds_and_stores() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    use_case = AddRecord(collections, records, embedder, RecordingTelemetry())

    record = await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))

    assert record.id == 1
    assert record.payload["year"] == 2019
    assert record.rendered.startswith("Title: Hydraulic pump HP-400")
    assert embedder.calls == [[record.rendered]]  # the stored text is the embedded text
    assert len(records.vectors[0]) == embedder.dim


async def test_add_record_rejects_an_unknown_collection() -> None:
    _, records = await _seeded()
    use_case = AddRecord(
        InMemoryCollectionRepository(), records, FakeEmbeddingProvider(), RecordingTelemetry()
    )

    with pytest.raises(CollectionNotFoundError):
        await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))


async def test_add_record_validates_before_embedding() -> None:
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    use_case = AddRecord(collections, records, embedder, RecordingTelemetry())

    with pytest.raises(MissingRequiredFieldError):
        await use_case.execute(AddRecordCommand("products", {"year": "2019"}))

    assert embedder.calls == []
    assert records.records == []


async def test_add_record_rejects_a_wrong_dimension_vector() -> None:
    collections, records = await _seeded()
    use_case = AddRecord(collections, records, BrokenEmbeddingProvider(), RecordingTelemetry())

    with pytest.raises(EmbeddingUnavailableError, match="1023 dimensions, expected 1024"):
        await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))

    assert records.records == []


async def _with_records(
    *titles: str,
) -> tuple[InMemoryCollectionRepository, InMemoryRecordRepository, FakeEmbeddingProvider]:
    """A products collection holding one record per title, embedded by the fake provider."""
    collections, records = await _seeded()
    embedder = FakeEmbeddingProvider()
    add = AddRecord(collections, records, embedder, RecordingTelemetry())
    for title in titles:
        await add.execute(AddRecordCommand("products", {**PRODUCT_VALUES, "title": title}))
    embedder.calls.clear()
    return collections, records, embedder


async def test_search_embeds_the_query_and_nothing_else() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B")

    await SearchRecords(collections, records, embedder, RecordingTelemetry()).execute(
        SearchRecordsCommand("products", "quiet pump", k=10)
    )

    assert embedder.calls == [["quiet pump"]]


async def test_search_ranks_the_nearest_record_first() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B", "Pump C")
    # The fake embeds text deterministically, so a record's own card is its own nearest hit.
    target = records.records[1]

    result = await SearchRecords(collections, records, embedder, RecordingTelemetry()).execute(
        SearchRecordsCommand("products", target.rendered, k=10)
    )

    assert [hit.record.id for hit in result.hits][0] == target.id
    assert result.hits[0].distance == pytest.approx(0.0)
    distances = [hit.distance for hit in result.hits]
    assert distances == sorted(distances)


async def test_search_returns_at_most_k_hits() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B", "Pump C")

    result = await SearchRecords(collections, records, embedder, RecordingTelemetry()).execute(
        SearchRecordsCommand("products", "pump", k=2)
    )

    assert len(result.hits) == 2


async def test_search_returns_the_schema_the_cli_renders_with() -> None:
    collections, records, embedder = await _with_records("Pump A")

    result = await SearchRecords(collections, records, embedder, RecordingTelemetry()).execute(
        SearchRecordsCommand("products", "pump", k=10)
    )

    assert result.schema == PRODUCTS


async def test_search_rejects_an_unknown_collection() -> None:
    collections, records, embedder = await _with_records("Pump A")

    with pytest.raises(CollectionNotFoundError):
        await SearchRecords(collections, records, embedder, RecordingTelemetry()).execute(
            SearchRecordsCommand("ghosts", "pump", k=10)
        )


async def test_search_on_an_empty_collection_returns_no_hits() -> None:
    """No records means no stored model, which must not read as a model mismatch."""
    collections, records = await _seeded()

    result = await SearchRecords(
        collections, records, FakeEmbeddingProvider(), RecordingTelemetry()
    ).execute(SearchRecordsCommand("products", "pump", k=10))

    assert result.hits == []
    assert result.schema == PRODUCTS


async def test_search_rejects_a_collection_embedded_with_another_model() -> None:
    collections, _ = await _seeded()
    records = InMemoryRecordRepository(model_name="bge-m3")
    await AddRecord(
        collections, records, FakeEmbeddingProvider("bge-m3"), RecordingTelemetry()
    ).execute(AddRecordCommand("products", PRODUCT_VALUES))
    switched = FakeEmbeddingProvider("nomic-embed-text")

    with pytest.raises(EmbeddingModelMismatchError, match="bge-m3"):
        await SearchRecords(collections, records, switched, RecordingTelemetry()).execute(
            SearchRecordsCommand("products", "pump", k=10)
        )

    assert switched.calls == []  # the guard runs before the query is embedded


async def test_search_records_instruments_the_query_and_its_results() -> None:
    collections, records, embedder = await _with_records("Pump A", "Pump B")
    telemetry = RecordingTelemetry()

    await SearchRecords(collections, records, embedder, telemetry).execute(
        SearchRecordsCommand("products", "quiet pump", k=5)
    )

    span = telemetry.named("use_case.search_records")
    assert span.attributes["semantic_db.collection"] == "products"
    assert span.attributes["semantic_db.k"] == 5
    assert span.attributes["semantic_db.query"] == "quiet pump"
    assert span.attributes["semantic_db.hits"] == 2
    nearest = float(str(span.attributes["semantic_db.distance.min"]))
    average = float(str(span.attributes["semantic_db.distance.mean"]))
    assert nearest <= average
    assert span.ended and span.error_type is None

    assert [s.name for s in telemetry.spans] == [
        "use_case.search_records",
        "embed",
        "db.search",
    ]


async def test_search_on_an_empty_collection_reports_no_distances() -> None:
    collections, records = await _seeded()
    telemetry = RecordingTelemetry()

    await SearchRecords(collections, records, FakeEmbeddingProvider(), telemetry).execute(
        SearchRecordsCommand("products", "pump", k=10)
    )

    span = telemetry.named("use_case.search_records")
    assert span.attributes["semantic_db.hits"] == 0
    assert "semantic_db.distance.min" not in span.attributes


async def test_embed_span_carries_the_model_and_the_text_size() -> None:
    collections, records = await _seeded()
    telemetry = RecordingTelemetry()

    record = await AddRecord(collections, records, FakeEmbeddingProvider(), telemetry).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )

    span = telemetry.named("embed")
    assert span.attributes["semantic_db.embedding.model"] == "fake-model"
    assert span.attributes["semantic_db.embedding.dim"] == 1024
    assert span.attributes["semantic_db.text.chars"] == len(record.rendered)


async def test_add_record_instruments_the_collection_it_writes_to() -> None:
    collections, records = await _seeded()
    telemetry = RecordingTelemetry()

    await AddRecord(collections, records, FakeEmbeddingProvider(), telemetry).execute(
        AddRecordCommand("products", PRODUCT_VALUES)
    )

    assert telemetry.named("use_case.add_record").attributes["semantic_db.collection"] == "products"
    assert [s.name for s in telemetry.spans] == ["use_case.add_record", "embed", "db.add"]


async def test_a_failing_use_case_marks_its_span_and_still_raises() -> None:
    _, records = await _seeded()
    telemetry = RecordingTelemetry()
    use_case = AddRecord(
        InMemoryCollectionRepository(), records, FakeEmbeddingProvider(), telemetry
    )

    with pytest.raises(CollectionNotFoundError):
        await use_case.execute(AddRecordCommand("products", PRODUCT_VALUES))

    span = telemetry.named("use_case.add_record")
    assert span.error_type == "CollectionNotFoundError"
    assert span.ended
