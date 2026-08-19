from collections.abc import Sequence
from dataclasses import dataclass

from semantic_db.application.ports import CollectionRepository
from semantic_db.domain.collection import Collection, CollectionSchema, FieldDefinition
from semantic_db.domain.errors import DuplicateCollectionError


@dataclass(frozen=True)
class CreateCollectionCommand:
    name: str
    fields: Sequence[FieldDefinition]


class CreateCollection:
    def __init__(self, collections: CollectionRepository) -> None:
        self._collections = collections

    async def execute(self, cmd: CreateCollectionCommand) -> Collection:
        collection = Collection(name=cmd.name, schema=CollectionSchema(fields=tuple(cmd.fields)))
        if await self._collections.get(collection.name) is not None:
            raise DuplicateCollectionError(collection.name)
        return await self._collections.create(collection)
