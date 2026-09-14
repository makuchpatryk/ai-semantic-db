from dataclasses import dataclass

from semantic_db.application.ports import CollectionRepository
from semantic_db.domain.errors import CollectionNotFoundError


@dataclass(frozen=True)
class DeleteCollectionCommand:
    name: str


class DeleteCollection:
    """Cascade handles records/embeddings — see `models.py` FK constraints."""

    def __init__(self, collections: CollectionRepository) -> None:
        self._collections = collections

    async def execute(self, cmd: DeleteCollectionCommand) -> None:
        if await self._collections.get(cmd.name) is None:
            raise CollectionNotFoundError(cmd.name)
        await self._collections.delete(cmd.name)
