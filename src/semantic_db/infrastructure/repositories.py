from sqlalchemy import func, select

from semantic_db.domain.collection import Collection, CollectionSchema, CollectionSummary
from semantic_db.domain.errors import DuplicateCollectionError
from semantic_db.domain.record import Record, RecordDetail, ScoredRecord
from semantic_db.infrastructure.db.models import CollectionModel, EmbeddingModel, RecordModel
from semantic_db.infrastructure.db.session_types import SessionFactory
from semantic_db.infrastructure.mappers import (
    collection_from_model,
    collection_to_model,
    payload_from_jsonb,
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

    async def list(self) -> list[CollectionSummary]:
        async with self._session_factory() as session:
            stmt = (
                select(
                    CollectionModel.name,
                    CollectionModel.schema,
                    func.count(RecordModel.id).label("record_count"),
                )
                .outerjoin(RecordModel, RecordModel.collection_id == CollectionModel.id)
                .group_by(CollectionModel.id, CollectionModel.name, CollectionModel.schema)
                .order_by(CollectionModel.name)
            )
            rows = await session.execute(stmt)
            results = []
            for row in rows:
                row_dict = dict(row._mapping)
                schema = CollectionSchema.model_validate(row_dict["schema"])
                summary = CollectionSummary(
                    name=row_dict["name"],
                    field_count=len(schema.fields),
                    record_count=int(row_dict["record_count"]),
                )
                results.append(summary)
            return results


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

    async def search(self, collection_id: int, vec: list[float], k: int) -> list[ScoredRecord]:
        """Search for records similar to vec using cosine distance via pgvector."""
        async with self._session_factory() as session:
            stmt = (
                select(
                    RecordModel.id,
                    RecordModel.collection_id,
                    RecordModel.payload,
                    RecordModel.rendered,
                    EmbeddingModel.vec.cosine_distance(vec).label("distance"),
                    CollectionModel.schema,
                )
                .join(EmbeddingModel, EmbeddingModel.record_id == RecordModel.id)
                .join(CollectionModel, CollectionModel.id == RecordModel.collection_id)
                .where(RecordModel.collection_id == collection_id)
                .order_by("distance")
                .limit(k)
            )

            rows = await session.execute(stmt)
            results = []
            for row in rows:
                model_dict = dict(row._mapping)
                schema = CollectionSchema.model_validate(model_dict["schema"])
                record = Record(
                    id=model_dict["id"],
                    collection_id=model_dict["collection_id"],
                    payload=payload_from_jsonb(schema, model_dict["payload"]),
                    rendered=model_dict["rendered"],
                )
                results.append(ScoredRecord(record=record, distance=float(model_dict["distance"])))
            return results

    async def embedding_models(self, collection_id: int) -> frozenset[str]:
        """Get the set of embedding models used for a collection."""
        async with self._session_factory() as session:
            stmt = (
                select(EmbeddingModel.model.distinct())
                .join(RecordModel, RecordModel.id == EmbeddingModel.record_id)
                .where(RecordModel.collection_id == collection_id)
            )
            rows = await session.execute(stmt)
            return frozenset(str(row[0]) for row in rows if row[0] is not None)

    async def get(self, collection_id: int, record_id: int) -> RecordDetail | None:
        async with self._session_factory() as session:
            stmt = (
                select(
                    RecordModel.id,
                    RecordModel.collection_id,
                    RecordModel.payload,
                    RecordModel.rendered,
                    CollectionModel.schema,
                    EmbeddingModel.model,
                )
                .join(CollectionModel, CollectionModel.id == RecordModel.collection_id)
                .outerjoin(EmbeddingModel, EmbeddingModel.record_id == RecordModel.id)
                .where(RecordModel.collection_id == collection_id)
                .where(RecordModel.id == record_id)
            )
            row = await session.execute(stmt)
            result = row.first()
            if result is None:
                return None

            row_dict = dict(result._mapping)
            schema = CollectionSchema.model_validate(row_dict["schema"])
            record = Record(
                id=row_dict["id"],
                collection_id=row_dict["collection_id"],
                payload=payload_from_jsonb(schema, row_dict["payload"]),
                rendered=row_dict["rendered"],
            )
            return RecordDetail(record=record, model=row_dict["model"])

    async def list(self, collection_id: int, limit: int, offset: int) -> list[Record]:
        async with self._session_factory() as session:
            stmt = (
                select(
                    RecordModel.id,
                    RecordModel.collection_id,
                    RecordModel.payload,
                    RecordModel.rendered,
                    CollectionModel.schema,
                )
                .join(CollectionModel, CollectionModel.id == RecordModel.collection_id)
                .where(RecordModel.collection_id == collection_id)
                .order_by(RecordModel.id)
                .limit(limit)
                .offset(offset)
            )
            rows = await session.execute(stmt)
            results = []
            for row in rows:
                row_dict = dict(row._mapping)
                schema = CollectionSchema.model_validate(row_dict["schema"])
                record = Record(
                    id=row_dict["id"],
                    collection_id=row_dict["collection_id"],
                    payload=payload_from_jsonb(schema, row_dict["payload"]),
                    rendered=row_dict["rendered"],
                )
                results.append(record)
            return results

    async def count(self, collection_id: int) -> int:
        async with self._session_factory() as session:
            stmt = select(func.count(RecordModel.id)).where(
                RecordModel.collection_id == collection_id
            )
            result = await session.scalar(stmt)
            return int(result) if result is not None else 0
