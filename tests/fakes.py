from hashlib import sha256

from semantic_db.domain.collection import Collection
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Record


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}
        self._next_id = 1

    async def create(self, collection: Collection) -> Collection:
        if collection.name in self.collections:
            raise DuplicateCollectionError(collection.name)
        stored = Collection(id=self._next_id, name=collection.name, schema=collection.schema)
        self._next_id += 1
        self.collections[stored.name] = stored
        return stored

    async def get(self, name: str) -> Collection | None:
        return self.collections.get(name)


class InMemoryRecordRepository:
    def __init__(self) -> None:
        self.records: list[Record] = []
        self.vectors: list[list[float]] = []
        self._next_id = 1

    async def add(self, collection_id: int, record: Record, vec: list[float]) -> Record:
        stored = Record(
            id=self._next_id,
            collection_id=collection_id,
            payload=record.payload,
            rendered=record.rendered,
        )
        self._next_id += 1
        self.records.append(stored)
        self.vectors.append(vec)
        return stored


class FakeEmbeddingProvider:
    """Deterministic vectors derived from the text, so use-case tests need no Ollama."""

    def __init__(self, model_name: str = "fake-model", dim: int = 1024) -> None:
        self.model_name = model_name
        self.dim = dim
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        digest = sha256(text.encode()).digest()
        return [digest[index % len(digest)] / 255 for index in range(self.dim)]


class BrokenEmbeddingProvider(FakeEmbeddingProvider):
    """Returns the wrong dimension — i.e. the wrong model is pulled."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * (self.dim - 1) for _ in texts]
