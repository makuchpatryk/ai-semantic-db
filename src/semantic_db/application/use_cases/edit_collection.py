from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from semantic_db.application.ports import (
    CollectionRepository,
    EmbeddingProvider,
    RecordRepository,
)
from semantic_db.domain.collection import (
    Collection,
    CollectionSchema,
    FieldDefinition,
)
from semantic_db.domain.errors import (
    CollectionNotFoundError,
    DuplicateCollectionError,
    SchemaError,
    UnknownFieldError,
    UnsupportedSchemaChangeError,
)
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import Record
from semantic_db.domain.rendering import render

REEMBED_BATCH_SIZE = 32


@dataclass(frozen=True)
class EditCollectionCommand:
    name: str
    rename_to: str | None = None
    add_fields: Sequence[FieldDefinition] = field(default_factory=tuple)
    embed_on: frozenset[str] = frozenset()
    embed_off: frozenset[str] = frozenset()
    enum_additions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class EditCollectionResult:
    collection: Collection
    reembedded_count: int


class EditCollection:
    """Rename, add optional fields, toggle embed, add enum values — the four schema
    changes v1 allows (PRD 7.3). Everything else is inexpressible via `EditCollectionCommand`
    and so has nothing to reject here."""

    def __init__(
        self,
        collections: CollectionRepository,
        records: RecordRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._collections = collections
        self._records = records
        self._embedder = embedder

    async def execute(
        self,
        cmd: EditCollectionCommand,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> EditCollectionResult:
        collection = await self._collections.get(cmd.name)
        if collection is None or collection.id is None:
            raise CollectionNotFoundError(cmd.name)

        for new_field in cmd.add_fields:
            if new_field.required:
                raise UnsupportedSchemaChangeError(
                    f"cannot add required field '{new_field.name}' to an existing collection"
                )

        fields = list(collection.schema.fields)
        _apply_embed_toggles(fields, cmd.embed_on, cmd.embed_off)
        _apply_enum_additions(fields, cmd.enum_additions)
        fields.extend(cmd.add_fields)
        new_schema = CollectionSchema(fields=tuple(fields))

        new_name = cmd.rename_to or collection.name
        if new_name != collection.name and await self._collections.get(new_name) is not None:
            raise DuplicateCollectionError(new_name)

        reembed_needed = bool(cmd.add_fields or cmd.embed_on or cmd.embed_off)
        reembedded_count = 0
        if reembed_needed:
            reembedded_count = await self._reembed_all(collection.id, new_schema, on_progress)

        updated = await self._collections.update(
            Collection(id=collection.id, name=new_name, schema=new_schema)
        )
        return EditCollectionResult(collection=updated, reembedded_count=reembedded_count)

    async def _reembed_all(
        self,
        collection_id: int,
        new_schema: CollectionSchema,
        on_progress: Callable[[int, int], None] | None,
    ) -> int:
        total = await self._records.count(collection_id)
        existing = await self._records.list(collection_id, limit=total, offset=0)

        batches = [
            existing[start : start + REEMBED_BATCH_SIZE]
            for start in range(0, len(existing), REEMBED_BATCH_SIZE)
        ]
        total_batches = len(batches)

        updates: list[tuple[Record, list[float]]] = []
        for batch_index, batch in enumerate(batches, start=1):
            texts = [render(new_schema, record.payload) for record in batch]
            vecs = await self._embedder.embed(texts)
            for record, text, vec in zip(batch, texts, vecs, strict=True):
                updates.append(
                    (
                        Record(
                            id=record.id,
                            collection_id=record.collection_id,
                            payload=record.payload,
                            rendered=text,
                        ),
                        vec,
                    )
                )
            if on_progress is not None:
                on_progress(batch_index, total_batches)

        if updates:
            await self._records.update_all(updates)
        return len(updates)


def _apply_embed_toggles(
    fields: list[FieldDefinition], embed_on: frozenset[str], embed_off: frozenset[str]
) -> None:
    """embed_off is applied after embed_on, so a field named in both ends up off."""
    for name in embed_on | embed_off:
        if not any(f.name == name for f in fields):
            raise UnknownFieldError(name, tuple(f.name for f in fields))

    for index, current in enumerate(fields):
        if current.name in embed_on:
            fields[index] = current.model_copy(update={"embed": True})
    for index, current in enumerate(fields):
        if current.name in embed_off:
            fields[index] = current.model_copy(update={"embed": False})


def _apply_enum_additions(
    fields: list[FieldDefinition], enum_additions: Mapping[str, tuple[str, ...]]
) -> None:
    for name, added_values in enum_additions.items():
        index = next((i for i, f in enumerate(fields) if f.name == name), None)
        if index is None:
            raise UnknownFieldError(name, tuple(f.name for f in fields))
        current = fields[index]
        if current.type is not FieldType.ENUM:
            raise SchemaError(f"field '{name}' is {current.type}, not an enum")
        fields[index] = current.model_copy(
            update={"enum_values": (current.enum_values or ()) + added_values}
        )
