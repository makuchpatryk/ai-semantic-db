from typing import Protocol

from semantic_db.domain.collection import Collection
from semantic_db.domain.record import Record

# Three ports, no fourth: a port earns its place only with a second implementation or a
# test that needs the seam (PRD 9.1). Methods are added as their milestone lands, so
# nothing here is a stub — `list`, `update`, `delete` and `search` arrive with M5-M9.


class EmbeddingProvider(Protocol):
    model_name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class CollectionRepository(Protocol):
    async def create(self, collection: Collection) -> Collection: ...

    async def get(self, name: str) -> Collection | None: ...


class RecordRepository(Protocol):
    async def add(self, collection_id: int, record: Record, vec: list[float]) -> Record: ...
