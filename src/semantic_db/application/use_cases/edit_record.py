from collections.abc import Mapping
from dataclasses import dataclass

from semantic_db.application.embedding import embed_one
from semantic_db.application.ports import (
    CollectionRepository,
    EmbeddingProvider,
    RecordRepository,
)
from semantic_db.domain.errors import (
    CollectionNotFoundError,
    RecordNotFoundError,
    UnknownFieldError,
)
from semantic_db.domain.record import Record
from semantic_db.domain.rendering import render
from semantic_db.domain.validation import coerce_payload


@dataclass(frozen=True)
class EditRecordCommand:
    collection_name: str
    record_id: int
    set_values: Mapping[str, object]
    unset_fields: frozenset[str]


@dataclass(frozen=True)
class EditRecordResult:
    record: Record
    reembedded: bool


class EditRecord:
    """Merge, re-validate and re-render a record; re-embed only if an embedded field
    actually changed — payload/rendered/vector must never diverge (PRD 5.1, M5's `add`)."""

    def __init__(
        self,
        collections: CollectionRepository,
        records: RecordRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._collections = collections
        self._records = records
        self._embedder = embedder

    async def execute(self, cmd: EditRecordCommand) -> EditRecordResult:
        collection = await self._collections.get(cmd.collection_name)
        if collection is None or collection.id is None:
            raise CollectionNotFoundError(cmd.collection_name)

        existing = await self._records.get(collection.id, cmd.record_id)
        if existing is None:
            raise RecordNotFoundError(cmd.collection_name, cmd.record_id)

        for name in cmd.unset_fields:
            if collection.schema.field(name) is None:
                raise UnknownFieldError(name, collection.schema.names)

        merged: dict[str, object] = dict(existing.record.payload)
        merged.update(cmd.set_values)
        for name in cmd.unset_fields:
            merged.pop(name, None)

        new_payload = coerce_payload(collection.schema, merged)
        rendered = render(collection.schema, new_payload)

        old_payload = existing.record.payload
        vec: list[float] | None = None
        if any(
            old_payload.get(field.name) != new_payload.get(field.name)
            for field in collection.schema.embedded_fields
        ):
            vec = await embed_one(self._embedder, rendered)

        record = Record(
            id=cmd.record_id,
            collection_id=collection.id,
            payload=new_payload,
            rendered=rendered,
        )
        stored = await self._records.update(record, vec)
        return EditRecordResult(record=stored, reembedded=vec is not None)
