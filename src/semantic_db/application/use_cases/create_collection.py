from collections.abc import Sequence
from dataclasses import dataclass

from semantic_db.application.ports import CollectionRepository
from semantic_db.application.telemetry import Telemetry
from semantic_db.domain.collection import Collection, CollectionSchema, FieldDefinition
from semantic_db.domain.errors import DuplicateCollectionError


@dataclass(frozen=True)
class CreateCollectionCommand:
    name: str
    fields: Sequence[FieldDefinition]


class CreateCollection:
    def __init__(self, collections: CollectionRepository, telemetry: Telemetry) -> None:
        self._collections = collections
        self._telemetry = telemetry

    async def execute(self, cmd: CreateCollectionCommand) -> Collection:
        with self._telemetry.span(
            "use_case.create_collection", collection=cmd.name, fields=len(cmd.fields)
        ):
            collection = Collection(
                name=cmd.name, schema=CollectionSchema(fields=tuple(cmd.fields))
            )
            if await self._collections.get(collection.name) is not None:
                raise DuplicateCollectionError(collection.name)
            return await self._collections.create(collection)
