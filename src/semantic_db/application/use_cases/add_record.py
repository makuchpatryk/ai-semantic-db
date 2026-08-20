from collections.abc import Mapping
from dataclasses import dataclass

from semantic_db.application.embedding import embed_one
from semantic_db.application.ports import (
    CollectionRepository,
    EmbeddingProvider,
    RecordRepository,
)
from semantic_db.domain.errors import CollectionNotFoundError
from semantic_db.domain.record import Record
from semantic_db.domain.rendering import render
from semantic_db.domain.validation import coerce_payload


@dataclass(frozen=True)
class AddRecordCommand:
    collection_name: str
    values: Mapping[str, object]


class AddRecord:
    """Validate, render, embed and store a record — added means searchable (PRD 5.1)."""

    def __init__(
        self,
        collections: CollectionRepository,
        records: RecordRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._collections = collections
        self._records = records
        self._embedder = embedder

    async def execute(self, cmd: AddRecordCommand) -> Record:
        collection = await self._collections.get(cmd.collection_name)
        if collection is None or collection.id is None:
            raise CollectionNotFoundError(cmd.collection_name)

        payload = coerce_payload(collection.schema, cmd.values)
        rendered = render(collection.schema, payload)
        vec = await embed_one(self._embedder, rendered)

        record = Record(collection_id=collection.id, payload=payload, rendered=rendered)
        return await self._records.add(collection.id, record, vec)
