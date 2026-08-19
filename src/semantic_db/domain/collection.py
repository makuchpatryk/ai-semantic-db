import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, model_validator

from semantic_db.domain.errors import SchemaError
from semantic_db.domain.field_types import UNIT_TYPES, FieldType

FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COLLECTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
MAX_NAME_LENGTH = 63


class FieldDefinition(BaseModel):
    """One declared field of a collection schema."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: FieldType
    embed: bool = False
    required: bool = False
    enum_values: tuple[str, ...] | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "FieldDefinition":
        if not FIELD_NAME_RE.match(self.name):
            raise SchemaError(
                f"field name '{self.name}' must be lowercase, start with a letter, "
                "and contain only letters, digits and underscores"
            )
        if len(self.name) > MAX_NAME_LENGTH:
            raise SchemaError(f"field name '{self.name}' exceeds {MAX_NAME_LENGTH} characters")

        if self.type is FieldType.ENUM:
            if not self.enum_values:
                raise SchemaError(f"field '{self.name}' is an enum but declares no values")
            if len(set(self.enum_values)) != len(self.enum_values):
                raise SchemaError(f"field '{self.name}' declares duplicate enum values")
            if any(not value.strip() for value in self.enum_values):
                raise SchemaError(f"field '{self.name}' declares an empty enum value")
        elif self.enum_values is not None:
            raise SchemaError(f"field '{self.name}' is {self.type} and cannot declare enum values")

        if self.unit is not None and self.type not in UNIT_TYPES:
            raise SchemaError(
                f"field '{self.name}' is {self.type}; a unit is only allowed on int and float"
            )
        return self

    @property
    def label(self) -> str:
        """Label used when rendering: 'unit_price' -> 'Unit price'."""
        return self.name.replace("_", " ").capitalize()


class CollectionSchema(BaseModel):
    """The ordered field definitions of a collection. Declaration order is render order."""

    model_config = ConfigDict(frozen=True)

    fields: tuple[FieldDefinition, ...]

    @model_validator(mode="after")
    def _check(self) -> "CollectionSchema":
        if not self.fields:
            raise SchemaError("a collection needs at least one field")
        names = [field.name for field in self.fields]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise SchemaError(f"duplicate field names: {', '.join(sorted(duplicates))}")
        if not any(field.embed for field in self.fields):
            raise SchemaError(
                "at least one field must be embedded, otherwise nothing is searchable"
            )
        return self

    def field(self, name: str) -> FieldDefinition | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    @property
    def embedded_fields(self) -> tuple[FieldDefinition, ...]:
        return tuple(f for f in self.fields if f.embed)


@dataclass(frozen=True)
class Collection:
    """A named collection and its schema.

    Plain dataclass rather than a pydantic model: `schema` shadows an attribute on
    pydantic's BaseModel, and the validation that matters already lives in CollectionSchema.
    """

    name: str
    schema: CollectionSchema
    id: int | None = None

    def __post_init__(self) -> None:
        if not COLLECTION_NAME_RE.match(self.name):
            raise SchemaError(
                f"collection name '{self.name}' must be lowercase, start with a letter, "
                "and contain only letters, digits, underscores and hyphens"
            )
        if len(self.name) > MAX_NAME_LENGTH:
            raise SchemaError(f"collection name '{self.name}' exceeds {MAX_NAME_LENGTH} characters")


@dataclass(frozen=True)
class CollectionSummary:
    """Listing projection (PRD 7.1); populated from M6 onwards."""

    name: str
    field_count: int
    record_count: int
