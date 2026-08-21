from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256

from semantic_db.application.telemetry import AttrValue, SpanScope, qualify
from semantic_db.domain.collection import Collection
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Record, ScoredRecord


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


@dataclass
class RecordedSpan:
    name: str
    attributes: dict[str, AttrValue] = field(default_factory=dict)
    error_type: str | None = None
    ended: bool = False

    def set(self, **attributes: AttrValue) -> None:
        self.attributes.update(qualify(attributes))


class RecordingTelemetry:
    """Captures span shape without an SDK, so use-case tests assert what is instrumented.

    Attribute names are qualified exactly as the exporter qualifies them, so a test that
    passes here asserts the names that really reach Tempo."""

    def __init__(self) -> None:
        self.spans: list[RecordedSpan] = []

    @contextmanager
    def span(self, name: str, **attributes: AttrValue) -> Iterator[SpanScope]:
        recorded = RecordedSpan(name=name, attributes=qualify(attributes))
        self.spans.append(recorded)
        try:
            yield recorded
        except BaseException as exc:
            recorded.error_type = type(exc).__name__
            raise
        finally:
            recorded.ended = True

    def named(self, name: str) -> RecordedSpan:
        """The single span with this name, or an assertion failure."""
        matches = [span for span in self.spans if span.name == name]
        assert len(matches) == 1, f"expected one {name!r} span, got {len(matches)}"
        return matches[0]


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
