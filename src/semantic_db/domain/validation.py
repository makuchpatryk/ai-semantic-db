from collections.abc import Mapping
from datetime import date

from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.errors import (
    MissingRequiredFieldError,
    PayloadValidationError,
    UnknownFieldError,
)
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import Payload, PayloadValue

TRUE_LITERALS = frozenset({"y", "yes", "true", "1"})
FALSE_LITERALS = frozenset({"n", "no", "false", "0"})


def coerce_payload(schema: CollectionSchema, raw: Mapping[str, object]) -> Payload:
    """Validate a raw payload against the schema and coerce it to declared types.

    Accepts both strings (the `--set` flag path) and already-typed values (prompts).
    Absent optional fields are omitted from the result rather than stored as null,
    so "was never set" is one state and `render` skips exactly the same fields.
    """
    for name in raw:
        if schema.field(name) is None:
            raise UnknownFieldError(name, schema.names)

    payload: Payload = {}
    for field in schema.fields:
        if field.name not in raw or _is_blank(raw[field.name]):
            if field.required:
                raise MissingRequiredFieldError(field.name)
            continue
        payload[field.name] = _coerce(field, raw[field.name])
    return payload


def _coerce(field: FieldDefinition, value: object) -> PayloadValue:
    match field.type:
        case FieldType.STRING | FieldType.TEXT:
            return str(value)
        case FieldType.ENUM:
            return _coerce_enum(field, value)
        case FieldType.INT:
            return _coerce_int(field, value)
        case FieldType.FLOAT:
            return _coerce_float(field, value)
        case FieldType.BOOL:
            return _coerce_bool(field, value)
        case FieldType.DATE:
            return _coerce_date(field, value)
        case FieldType.ARRAY_STRING:
            return _coerce_array(value)


def _coerce_enum(field: FieldDefinition, value: object) -> str:
    allowed = field.enum_values or ()
    text = str(value)
    if text not in allowed:
        raise PayloadValidationError(
            field.name, str(field.type), value, f"allowed: {', '.join(allowed)}"
        )
    return text


def _coerce_int(field: FieldDefinition, value: object) -> int:
    if isinstance(value, bool):
        raise PayloadValidationError(field.name, str(field.type), value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        raise PayloadValidationError(field.name, str(field.type), value) from None


def _coerce_float(field: FieldDefinition, value: object) -> float:
    if isinstance(value, bool):
        raise PayloadValidationError(field.name, str(field.type), value)
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        raise PayloadValidationError(field.name, str(field.type), value) from None


def _coerce_bool(field: FieldDefinition, value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_LITERALS:
        return True
    if text in FALSE_LITERALS:
        return False
    raise PayloadValidationError(field.name, str(field.type), value, "expected y/n")


def _coerce_date(field: FieldDefinition, value: object) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise PayloadValidationError(
            field.name, str(field.type), value, "expected ISO format YYYY-MM-DD"
        ) from None


def _coerce_array(value: object) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [item.strip() for item in str(value).split(",")]
    return [item for item in items if item]


def _is_blank(value: object) -> bool:
    return value is None or value == "" or value == []
