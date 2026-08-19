from collections.abc import Mapping
from datetime import date

from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import PayloadValue

PLACEHOLDER = "<{name}>"


def render(schema: CollectionSchema, payload: Mapping[str, PayloadValue]) -> str:
    """Render a payload into the one labelled card that gets embedded (PRD 4.3).

    Pure function: no chunking, declaration order, `embed: false` fields omitted,
    absent optional values omitted.
    """
    lines = []
    for field in schema.fields:
        if not field.embed:
            continue
        value = payload.get(field.name)
        if value is None or value == "" or value == []:
            continue
        lines.append(f"{field.label}: {format_value(field, value)}")
    return "\n".join(lines)


def render_preview(schema: CollectionSchema) -> str:
    """The same card with `<field>` placeholders, shown before a collection exists."""
    return "\n".join(
        f"{field.label}: {PLACEHOLDER.format(name=field.name)}" for field in schema.embedded_fields
    )


def format_value(field: FieldDefinition, value: PayloadValue) -> str:
    match field.type:
        case FieldType.BOOL:
            return "yes" if value else "no"
        case FieldType.DATE:
            return value.isoformat() if isinstance(value, date) else str(value)
        case FieldType.ARRAY_STRING:
            return ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        case FieldType.FLOAT | FieldType.INT:
            return _with_unit(_format_number(value), field.unit)
        case _:
            return str(value)


def _format_number(value: PayloadValue) -> str:
    """Trim a trailing '.0' so 4200.0 renders as '4200', matching the PRD's card."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _with_unit(text: str, unit: str | None) -> str:
    return f"{text} {unit}" if unit else text
