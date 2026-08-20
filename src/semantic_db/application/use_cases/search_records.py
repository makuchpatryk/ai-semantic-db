from dataclasses import dataclass

from semantic_db.application.embedding import embed_one
from semantic_db.application.ports import (
    CollectionRepository,
    EmbeddingProvider,
    RecordRepository,
)
from semantic_db.domain.collection import CollectionSchema
from semantic_db.domain.errors import CollectionNotFoundError, EmbeddingModelMismatchError
from semantic_db.domain.record import ScoredRecord


@dataclass(frozen=True)
class SearchRecordsCommand:
    collection_name: str
    query: str
    k: int


@dataclass(frozen=True)
class SearchResult:
    schema: CollectionSchema
    hits: list[ScoredRecord]


class SearchRecords:
    """Search a collection for records similar to a query."""

    def __init__(
        self,
        collections: CollectionRepository,
        records: RecordRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._collections = collections
        self._records = records
        self._embedder = embedder

    async def execute(self, cmd: SearchRecordsCommand) -> SearchResult:
        collection = await self._collections.get(cmd.collection_name)
        if collection is None:
            raise CollectionNotFoundError(cmd.collection_name)

        collection_id = collection.id
        assert collection_id is not None

        stored_models = await self._records.embedding_models(collection_id)
        current_model = self._embedder.model_name

        if stored_models and current_model not in stored_models:
            stored = list(stored_models)[0] if stored_models else "unknown"
            raise EmbeddingModelMismatchError(cmd.collection_name, stored, current_model)

        query_vec = await embed_one(self._embedder, cmd.query)
        hits = await self._records.search(collection_id, query_vec, cmd.k)

        return SearchResult(schema=collection.schema, hits=hits)
