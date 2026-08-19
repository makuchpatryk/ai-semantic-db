from collections.abc import Mapping
from dataclasses import dataclass

from semantic_db.application.ports import (
    CollectionRepository,
    EmbeddingProvider,
    RecordRepository,
)
from semantic_db.domain.errors import CollectionNotFoundError, EmbeddingUnavailableError
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
        vec = await self._embed(rendered)

        record = Record(collection_id=collection.id, payload=payload, rendered=rendered)
        return await self._records.add(collection.id, record, vec)

    async def _embed(self, rendered: str) -> list[float]:
        vectors = await self._embedder.embed([rendered])
        if len(vectors) != 1:
            raise EmbeddingUnavailableError(
                f"{self._embedder.model_name} returned {len(vectors)} vectors for one text"
            )
        vec = vectors[0]
        # Fail here rather than deep inside the pgvector insert: a dimension mismatch
        # means the wrong model is pulled, and that message has to say so.
        if len(vec) != self._embedder.dim:
            raise EmbeddingUnavailableError(
                f"{self._embedder.model_name} returned {len(vec)} dimensions, "
                f"expected {self._embedder.dim}"
            )
        return vec
