from enum import StrEnum


class FieldType(StrEnum):
    """The declarable field types (PRD 4.1)."""

    STRING = "string"
    TEXT = "text"
    ENUM = "enum"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    DATE = "date"
    ARRAY_STRING = "array<string>"


#: Types that accept a `unit` label used only when rendering.
UNIT_TYPES = frozenset({FieldType.INT, FieldType.FLOAT})
