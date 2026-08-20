import pytest

from semantic_db.domain.collection import Collection, CollectionSchema, FieldDefinition
from semantic_db.domain.errors import SchemaError
from semantic_db.domain.field_types import FieldType


def field(name: str = "title", **kwargs: object) -> FieldDefinition:
    defaults: dict[str, object] = {"type": FieldType.TEXT, "embed": True}
    return FieldDefinition(name=name, **{**defaults, **kwargs})


def test_label_humanises_the_field_name() -> None:
    assert field("unit_price", type=FieldType.FLOAT).label == "Unit price"


@pytest.mark.parametrize("name", ["Title", "1title", "ti tle", "ti-tle", ""])
def test_rejects_invalid_field_names(name: str) -> None:
    with pytest.raises(SchemaError):
        field(name)


def test_enum_needs_values() -> None:
    with pytest.raises(SchemaError, match="declares no values"):
        field("category", type=FieldType.ENUM)


def test_enum_rejects_duplicate_values() -> None:
    with pytest.raises(SchemaError, match="duplicate enum values"):
        field("category", type=FieldType.ENUM, enum_values=("a", "a"))


def test_non_enum_rejects_enum_values() -> None:
    with pytest.raises(SchemaError, match="cannot declare enum values"):
        field("title", enum_values=("a",))


def test_unit_only_on_numeric_types() -> None:
    with pytest.raises(SchemaError, match="unit is only allowed"):
        field("title", unit="PLN")
    assert field("price", type=FieldType.FLOAT, unit="PLN").unit == "PLN"


def test_schema_needs_at_least_one_field() -> None:
    with pytest.raises(SchemaError, match="at least one field"):
        CollectionSchema(fields=())


def test_schema_rejects_duplicate_field_names() -> None:
    with pytest.raises(SchemaError, match="duplicate field names: title"):
        CollectionSchema(fields=(field("title"), field("title")))


def test_schema_needs_something_embedded() -> None:
    with pytest.raises(SchemaError, match="at least one field must be embedded"):
        CollectionSchema(fields=(field("title", embed=False),))


def test_schema_exposes_names_and_embedded_fields() -> None:
    schema = CollectionSchema(fields=(field("title"), field("notes", embed=False)))
    assert schema.names == ("title", "notes")
    assert [f.name for f in schema.embedded_fields] == ["title"]
    assert schema.field("notes") is not None
    assert schema.field("missing") is None


@pytest.mark.parametrize("name", ["Products", "1products", "pro ducts"])
def test_rejects_invalid_collection_names(name: str) -> None:
    with pytest.raises(SchemaError, match="collection name"):
        Collection(name=name, schema=CollectionSchema(fields=(field(),)))


def test_accepts_hyphenated_collection_name() -> None:
    collection = Collection(name="spare-parts", schema=CollectionSchema(fields=(field(),)))
    assert collection.name == "spare-parts"
