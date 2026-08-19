from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import BigInteger, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from semantic_db.infrastructure.db.base import Base

EMBEDDING_DIM = 1024


class CollectionModel(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RecordModel(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rendered: Mapped[str] = mapped_column(Text, nullable=False)


class EmbeddingModel(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        Index(
            "embeddings_hnsw",
            "vec",
            postgresql_using="hnsw",
            postgresql_ops={"vec": "halfvec_cosine_ops"},
        ),
    )

    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    vec: Mapped[list[float]] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=False)
