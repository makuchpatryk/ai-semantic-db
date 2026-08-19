from sqlalchemy import select

from semantic_db.domain.collection import Collection
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Record
from semantic_db.infrastructure.db.models import CollectionModel, EmbeddingModel
from semantic_db.infrastructure.db.session_types import SessionFactory
from semantic_db.infrastructure.mappers import (
    collection_from_model,
    collection_to_model,
    record_from_model,
    record_to_model,
)


class SqlCollectionRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create(self, collection: Collection) -> Collection:
        model = collection_to_model(collection)
        async with self._session_factory() as session, session.begin():
            session.add(model)
            try:
                await session.flush()
            except Exception as exc:  # unique violation is the only expected failure here
                if "collections_name_key" in str(exc):
                    raise DuplicateCollectionError(collection.name) from exc
                raise
            return collection_from_model(model)

    async def get(self, name: str) -> Collection | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(CollectionModel).where(CollectionModel.name == name)
            )
            return collection_from_model(model) if model is not None else None


class SqlRecordRepository:
    def __init__(self, session_factory: SessionFactory, model_name: str) -> None:
        self._session_factory = session_factory
        self._model_name = model_name

    async def add(self, collection_id: int, record: Record, vec: list[float]) -> Record:
        """Record and embedding are written together — a record without a vector is
        invisible to search, which must never be a reachable state."""
        model = record_to_model(record)
        model.collection_id = collection_id
        async with self._session_factory() as session, session.begin():
            session.add(model)
            await session.flush()
            session.add(EmbeddingModel(record_id=model.id, model=self._model_name, vec=vec))
            collection = await session.get(CollectionModel, collection_id)
            assert collection is not None  # guarded by the FK, restated for the mapper
            return record_from_model(model, collection_from_model(collection).schema)
