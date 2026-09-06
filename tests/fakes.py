from hashlib import sha256

from semantic_db.domain.collection import Collection, CollectionSummary
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Record, RecordDetail, ScoredRecord


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}
        self._next_id = 1
        self._record_repo: InMemoryRecordRepository | None = None

    async def create(self, collection: Collection) -> Collection:
        if collection.name in self.collections:
            raise DuplicateCollectionError(collection.name)
        stored = Collection(id=self._next_id, name=collection.name, schema=collection.schema)
        self._next_id += 1
        self.collections[stored.name] = stored
        return stored

    async def get(self, name: str) -> Collection | None:
        return self.collections.get(name)

    async def list(self) -> list[CollectionSummary]:
        summaries = []
        for collection in sorted(self.collections.values(), key=lambda c: c.name):
            record_count = 0
            if self._record_repo is not None:
                record_count = sum(
                    1 for r in self._record_repo.records if r.collection_id == collection.id
                )
            summaries.append(
                CollectionSummary(
                    name=collection.name,
                    field_count=len(collection.schema.fields),
                    record_count=record_count,
                )
            )
        return summaries


class InMemoryRecordRepository:
    def __init__(self, model_name: str = "fake-model") -> None:
        self.records: list[Record] = []
        self.vectors: list[list[float]] = []
        self._next_id = 1
        self._model_name = model_name
        self.collections_with_records: set[int] = set()

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
        self.collections_with_records.add(collection_id)
        return stored

    async def search(self, collection_id: int, vec: list[float], k: int) -> list[ScoredRecord]:
        """Search for records similar to vec using cosine distance."""
        hits = []
        for record, stored_vec in zip(self.records, self.vectors, strict=True):
            if record.collection_id != collection_id:
                continue
            distance = _cosine_distance(vec, stored_vec)
            hits.append((distance, ScoredRecord(record=record, distance=distance)))

        hits.sort(key=lambda x: x[0])
        return [scored for _, scored in hits[:k]]

    async def embedding_models(self, collection_id: int) -> frozenset[str]:
        """Get the set of embedding models used for a collection."""
        if collection_id in self.collections_with_records:
            return frozenset({self._model_name})
        return frozenset()

    async def get(self, collection_id: int, record_id: int) -> RecordDetail | None:
        for record in self.records:
            if record.collection_id == collection_id and record.id == record_id:
                return RecordDetail(record=record, model=self._model_name)
        return None

    async def list(self, collection_id: int, limit: int, offset: int) -> list[Record]:
        filtered = [r for r in self.records if r.collection_id == collection_id]
        filtered.sort(key=lambda r: r.id or 0)
        return filtered[offset : offset + limit]

    async def count(self, collection_id: int) -> int:
        return sum(1 for r in self.records if r.collection_id == collection_id)


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


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Compute cosine distance between two vectors (1 - cosine_similarity)."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 1.0

    similarity = dot / (norm_a * norm_b)
    return float(max(0.0, 1.0 - similarity))
