from dataclasses import dataclass

from semantic_db.application.ports import CollectionRepository, RecordRepository
from semantic_db.domain.collection import Collection, CollectionSchema, CollectionSummary
from semantic_db.domain.errors import CollectionNotFoundError, RecordNotFoundError
from semantic_db.domain.record import Record, RecordDetail


@dataclass(frozen=True)
class RecordPage:
    schema: CollectionSchema
    records: list[Record]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class RecordView:
    schema: CollectionSchema
    detail: RecordDetail


class Queries:
    """Read-only façade for queries. M4 opens with get_collection (prompts need the schema);
    M6 adds list, show_collection, list_records, show_record."""

    def __init__(self, collections: CollectionRepository, records: RecordRepository) -> None:
        self._collections = collections
        self._records = records

    async def get_collection(self, name: str) -> Collection:
        """Get a collection by name, or raise CollectionNotFoundError."""
        collection = await self._collections.get(name)
        if collection is None:
            raise CollectionNotFoundError(name)
        return collection

    async def list_collections(self) -> list[CollectionSummary]:
        """List all collections with their summary info."""
        return await self._collections.list()

    async def show_collection(self, name: str) -> Collection:
        """Alias of get_collection for the CLI."""
        return await self.get_collection(name)

    async def list_records(self, name: str, limit: int, offset: int) -> RecordPage:
        """List records in a collection with pagination."""
        collection = await self.get_collection(name)
        assert collection.id is not None
        records = await self._records.list(collection.id, limit, offset)
        total = await self._records.count(collection.id)
        return RecordPage(
            schema=collection.schema,
            records=records,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def show_record(self, name: str, record_id: int) -> RecordView:
        """Show a single record with full details."""
        collection = await self.get_collection(name)
        assert collection.id is not None
        detail = await self._records.get(collection.id, record_id)
        if detail is None:
            raise RecordNotFoundError(name, record_id)
        return RecordView(schema=collection.schema, detail=detail)
