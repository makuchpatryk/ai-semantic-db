from collections.abc import Mapping
from datetime import date
from typing import Any

from semantic_db.domain.collection import Collection, CollectionSchema
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import Payload, PayloadValue, Record
from semantic_db.infrastructure.db.models import CollectionModel, RecordModel

# The single place that knows JSONB has no date type. Everything else works with
# `datetime.date`, so a value cannot round-trip as a string and render differently.


def collection_to_model(collection: Collection) -> CollectionModel:
    return CollectionModel(name=collection.name, schema=collection.schema.model_dump(mode="json"))


def collection_from_model(model: CollectionModel) -> Collection:
    return Collection(
        id=model.id,
        name=model.name,
        schema=CollectionSchema.model_validate(model.schema),
    )


def record_to_model(record: Record) -> RecordModel:
    return RecordModel(
        collection_id=record.collection_id,
        payload=payload_to_jsonb(record.payload),
        rendered=record.rendered,
    )


def record_from_model(model: RecordModel, schema: CollectionSchema) -> Record:
    return Record(
        id=model.id,
        collection_id=model.collection_id,
        payload=payload_from_jsonb(schema, model.payload),
        rendered=model.rendered,
    )


def payload_to_jsonb(payload: Mapping[str, PayloadValue]) -> dict[str, Any]:
    return {
        name: value.isoformat() if isinstance(value, date) else value
        for name, value in payload.items()
    }


def payload_from_jsonb(schema: CollectionSchema, raw: Mapping[str, Any]) -> Payload:
    payload: Payload = {}
    for name, value in raw.items():
        field = schema.field(name)
        if field is not None and field.type is FieldType.DATE and isinstance(value, str):
            payload[name] = date.fromisoformat(value)
        else:
            payload[name] = value
    return payload
