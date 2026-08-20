import pytest

from semantic_db.cli.field_spec import parse_field_spec
from semantic_db.cli.set_spec import parse_set_specs
from semantic_db.domain.errors import SchemaError, SemanticDbError
from semantic_db.domain.field_types import FieldType
from tests.schemas import PRODUCTS, PRODUCTS_FIELD_SPECS


def test_parses_the_products_schema_from_the_prd() -> None:
    assert tuple(parse_field_spec(spec) for spec in PRODUCTS_FIELD_SPECS) == PRODUCTS.fields


def test_bare_field_has_no_flags() -> None:
    field = parse_field_spec("notes:text")
    assert (field.type, field.embed, field.required) == (FieldType.TEXT, False, False)


def test_flags_are_comma_separated() -> None:
    field = parse_field_spec("title:text:embed,required")
    assert (field.embed, field.required) == (True, True)


def test_flags_may_be_separate_segments() -> None:
    field = parse_field_spec("title:text:embed:required")
    assert (field.embed, field.required) == (True, True)


def test_enum_values_are_inline() -> None:
    field = parse_field_spec("category:enum(pumps|motors):embed")
    assert field.enum_values == ("pumps", "motors")


def test_unit_is_a_key_value_option() -> None:
    assert parse_field_spec("price:float:embed:unit=PLN").unit == "PLN"


def test_array_type_is_parsed_despite_its_brackets() -> None:
    assert parse_field_spec("genres:array<string>:embed").type == FieldType.ARRAY_STRING


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("title", "expected name:type"),
        (":text:embed", "expected name:type"),
        ("title:strng", "unknown type 'strng'"),
        ("category:enum:embed", "enum needs its values inline"),
        ("category:enum():embed", "enum declares no values"),
        ("title:text:embeded", "unknown flag 'embeded'"),
        ("price:float:embed:currency=PLN", "unknown option 'currency'"),
        ("Title:text:embed", "field name 'Title'"),
        ("title:text:embed:unit=PLN", "unit is only allowed"),
    ],
)
def test_rejects_malformed_specs(spec: str, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        parse_field_spec(spec)


def test_parses_repeated_set_values() -> None:
    assert parse_set_specs(["title=Pump", "year=2019"]) == {"title": "Pump", "year": "2019"}


def test_set_splits_on_the_first_equals_only() -> None:
    assert parse_set_specs(["note=a=b"]) == {"note": "a=b"}


def test_set_accepts_an_empty_value() -> None:
    assert parse_set_specs(["description="]) == {"description": ""}


@pytest.mark.parametrize("spec", ["title", "=Pump"])
def test_set_rejects_malformed_values(spec: str) -> None:
    with pytest.raises(SemanticDbError, match="expected key=value"):
        parse_set_specs([spec])


def test_set_rejects_a_duplicate_key() -> None:
    with pytest.raises(SemanticDbError, match="given twice"):
        parse_set_specs(["title=a", "title=b"])
