from datetime import date

import pytest

from semantic_db.domain.errors import (
    MissingRequiredFieldError,
    PayloadValidationError,
    UnknownFieldError,
)
from semantic_db.domain.validation import coerce_payload
from tests.schemas import BOOKS, PRODUCTS


def test_coerces_strings_to_declared_types() -> None:
    payload = coerce_payload(
        PRODUCTS,
        {"title": "Pump", "category": "pumps", "year": "2019", "price": "4200"},
    )
    assert payload == {"title": "Pump", "category": "pumps", "year": 2019, "price": 4200.0}
    assert isinstance(payload["year"], int)
    assert isinstance(payload["price"], float)


def test_accepts_already_typed_values() -> None:
    payload = coerce_payload(BOOKS, {"author": "Lem", "published": date(1961, 1, 1)})
    assert payload["published"] == date(1961, 1, 1)


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(MissingRequiredFieldError, match="'title' is required"):
        coerce_payload(PRODUCTS, {"year": "2019"})


def test_blank_required_field_is_rejected() -> None:
    with pytest.raises(MissingRequiredFieldError):
        coerce_payload(PRODUCTS, {"title": ""})


def test_absent_optional_field_is_omitted_not_nulled() -> None:
    payload = coerce_payload(PRODUCTS, {"title": "Pump"})
    assert payload == {"title": "Pump"}


def test_unknown_field_is_rejected_with_the_known_names() -> None:
    with pytest.raises(UnknownFieldError, match="unknown field 'colour'"):
        coerce_payload(PRODUCTS, {"title": "Pump", "colour": "red"})


def test_bad_int_names_field_and_type() -> None:
    with pytest.raises(PayloadValidationError) as caught:
        coerce_payload(PRODUCTS, {"title": "Pump", "year": "abc"})
    assert str(caught.value) == "field 'year' expects int, got 'abc'"
    assert caught.value.field == "year"
    assert caught.value.declared_type == "int"


def test_bad_float_is_rejected() -> None:
    with pytest.raises(PayloadValidationError, match="expects float"):
        coerce_payload(PRODUCTS, {"title": "Pump", "price": "cheap"})


def test_bool_rejects_int_typed_input() -> None:
    with pytest.raises(PayloadValidationError, match="expects int"):
        coerce_payload(PRODUCTS, {"title": "Pump", "year": True})


def test_enum_rejects_undeclared_value_and_lists_allowed() -> None:
    with pytest.raises(PayloadValidationError, match="allowed: pumps, motors"):
        coerce_payload(PRODUCTS, {"title": "Pump", "category": "turbines"})


@pytest.mark.parametrize("literal", ["y", "yes", "true", "1", "TRUE"])
def test_bool_accepts_true_literals(literal: str) -> None:
    assert coerce_payload(BOOKS, {"author": "Lem", "in_print": literal})["in_print"] is True


@pytest.mark.parametrize("literal", ["n", "no", "false", "0"])
def test_bool_accepts_false_literals(literal: str) -> None:
    assert coerce_payload(BOOKS, {"author": "Lem", "in_print": literal})["in_print"] is False


def test_bool_rejects_anything_else() -> None:
    with pytest.raises(PayloadValidationError, match="expected y/n"):
        coerce_payload(BOOKS, {"author": "Lem", "in_print": "maybe"})


def test_date_parses_iso() -> None:
    payload = coerce_payload(BOOKS, {"author": "Lem", "published": "1961-05-04"})
    assert payload["published"] == date(1961, 5, 4)


def test_date_rejects_non_iso() -> None:
    with pytest.raises(PayloadValidationError, match="YYYY-MM-DD"):
        coerce_payload(BOOKS, {"author": "Lem", "published": "04/05/1961"})


def test_array_splits_strips_and_drops_empties() -> None:
    payload = coerce_payload(BOOKS, {"author": "Lem", "genres": "sci-fi, philosophy, ,"})
    assert payload["genres"] == ["sci-fi", "philosophy"]


def test_array_accepts_a_list() -> None:
    payload = coerce_payload(BOOKS, {"author": "Lem", "genres": ["sci-fi", " essays "]})
    assert payload["genres"] == ["sci-fi", "essays"]
