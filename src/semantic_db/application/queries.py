from semantic_db.application.ports import CollectionRepository
from semantic_db.domain.collection import Collection
from semantic_db.domain.errors import CollectionNotFoundError


class Queries:
    """Read-only façade for queries. M4 opens with get_collection (prompts need the schema);
    M6 adds list, show_collection, list_records, show_record."""

    def __init__(self, collections: CollectionRepository) -> None:
        self._collections = collections

    async def get_collection(self, name: str) -> Collection:
        """Get a collection by name, or raise CollectionNotFoundError."""
        collection = await self._collections.get(name)
        if collection is None:
            raise CollectionNotFoundError(name)
        return collection
