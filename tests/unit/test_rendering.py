from datetime import date

import pytest

from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.field_types import FieldType
from semantic_db.domain.record import Payload, PayloadValue
from semantic_db.domain.rendering import format_value, render, render_preview
from tests.schemas import BOOKS, PRODUCTS

PRODUCT: Payload = {
    "title": "Hydraulic pump HP-400",
    "category": "pumps",
    "year": 2019,
    "price": 4200.0,
    "description": "Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.",
}


def test_renders_the_card_from_the_prd() -> None:
    assert render(PRODUCTS, PRODUCT) == (
        "Title: Hydraulic pump HP-400\n"
        "Description: Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.\n"
        "Category: pumps\n"
        "Year: 2019\n"
        "Price: 4200 PLN"
    )


def test_renders_in_declaration_order_not_payload_order() -> None:
    reversed_payload = dict(reversed(list(PRODUCT.items())))
    assert render(PRODUCTS, reversed_payload) == render(PRODUCTS, PRODUCT)


def test_omits_non_embedded_fields() -> None:
    rendered = render(BOOKS, {"author": "Lem", "shelf_code": "A-12"})
    assert "Shelf code" not in rendered
    assert rendered == "Author: Lem"


@pytest.mark.parametrize("absent", [None, "", []])
def test_omits_absent_optional_values(absent: PayloadValue | None) -> None:
    payload = {"title": "Pump", "description": absent}
    assert render(PRODUCTS, payload) == "Title: Pump"  # type: ignore[arg-type]


def test_renders_dates_arrays_and_bools() -> None:
    rendered = render(
        BOOKS,
        {
            "author": "Lem",
            "published": date(1961, 1, 1),
            "genres": ["sci-fi", "philosophy"],
            "in_print": True,
        },
    )
    assert rendered == (
        "Author: Lem\nPublished: 1961-01-01\nGenres: sci-fi, philosophy\nIn print: yes"
    )


def test_renders_false_bool_as_no() -> None:
    assert render(BOOKS, {"author": "Lem", "in_print": False}) == "Author: Lem\nIn print: no"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4200.0, "4200 PLN"), (4200.5, "4200.5 PLN"), (0.0, "0 PLN")],
)
def test_float_trims_trailing_zero_and_appends_unit(value: float, expected: str) -> None:
    price = FieldDefinition(name="price", type=FieldType.FLOAT, embed=True, unit="PLN")
    assert format_value(price, value) == expected


def test_number_without_unit_renders_bare() -> None:
    year = FieldDefinition(name="year", type=FieldType.INT, embed=True)
    assert format_value(year, 2019) == "2019"


def test_preview_uses_placeholders_for_embedded_fields_only() -> None:
    assert render_preview(BOOKS) == (
        "Author: <author>\nPublished: <published>\nGenres: <genres>\nIn print: <in_print>"
    )


def test_empty_payload_renders_empty_string() -> None:
    schema = CollectionSchema(
        fields=(FieldDefinition(name="title", type=FieldType.TEXT, embed=True),)
    )
    assert render(schema, {}) == ""
