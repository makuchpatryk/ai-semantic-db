import asyncio

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner, Result

from semantic_db.cli.main import app
from semantic_db.infrastructure.db.models import CollectionModel, EmbeddingModel, RecordModel
from semantic_db.infrastructure.db.session_types import SessionFactory
from tests.schemas import BOOKS_FIELD_SPECS, PRODUCTS_FIELD_SPECS

pytestmark = pytest.mark.integration

runner = CliRunner()


async def invoke(args: list[str]) -> Result:
    """The CLI owns its event loop (`asyncio.run`), so it runs off the test's loop."""
    return await asyncio.to_thread(lambda: runner.invoke(app, args))


def field_args(specs: list[str]) -> list[str]:
    return [argument for spec in specs for argument in ("--field", spec)]


def set_args(values: dict[str, str]) -> list[str]:
    return [argument for item in values.items() for argument in ("--set", f"{item[0]}={item[1]}")]


async def create_products() -> None:
    result = await invoke(["collection", "create", "products", *field_args(PRODUCTS_FIELD_SPECS)])
    assert result.exit_code == 0, result.output


async def test_create_collection_writes_the_declared_schema(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    async with session_factory() as session:
        model = await session.scalar(select(CollectionModel))
        assert model is not None
        assert [field["name"] for field in model.schema["fields"]] == [
            "title",
            "description",
            "category",
            "year",
            "price",
        ]
        category = model.schema["fields"][2]
        assert category["enum_values"] == ["pumps", "motors", "valves", "sensors"]
        assert model.schema["fields"][4]["unit"] == "PLN"


async def test_duplicate_collection_is_rejected(session_factory: SessionFactory) -> None:
    await create_products()
    result = await invoke(["collection", "create", "products", *field_args(PRODUCTS_FIELD_SPECS)])
    assert result.exit_code == 2


async def test_record_add_stores_payload_rendered_and_vector(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    result = await invoke(
        [
            "record",
            "add",
            "products",
            *set_args(
                {
                    "title": "Hydraulic pump HP-400",
                    "category": "pumps",
                    "year": "2019",
                    "price": "4200",
                    "description": "Cast-iron housing, rated 400 l/min.",
                }
            ),
        ],
    )
    assert result.exit_code == 0, result.output

    async with session_factory() as session:
        record = await session.scalar(select(RecordModel))
        assert record is not None
        assert record.payload["year"] == 2019
        assert record.rendered.startswith("Title: Hydraulic pump HP-400")
        assert "Price: 4200 PLN" in record.rendered

        embedding = await session.get(EmbeddingModel, record.id)
        assert embedding is not None
        assert embedding.model == "bge-m3"
        assert len(embedding.vec) == 1024


async def test_bad_value_writes_nothing(session_factory: SessionFactory) -> None:
    await create_products()

    result = await invoke(["record", "add", "products", "--set", "title=Pump", "--set", "year=abc"])

    assert result.exit_code == 2
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 0


async def test_unknown_collection_is_rejected(session_factory: SessionFactory) -> None:
    result = await invoke(["record", "add", "ghosts", "--set", "title=Pump"])
    assert result.exit_code == 2


async def test_second_collection_with_a_different_shape(session_factory: SessionFactory) -> None:
    """PRD 12 / R1: if the schema abstraction only fits products, it breaks here."""
    created = await invoke(["collection", "create", "books", *field_args(BOOKS_FIELD_SPECS)])
    assert created.exit_code == 0, created.output

    added = await invoke(
        [
            "record",
            "add",
            "books",
            *set_args(
                {
                    "author": "Stanisław Lem",
                    "published": "1961-05-04",
                    "genres": "sci-fi, philosophy",
                    "in_print": "y",
                    "shelf_code": "A-12",
                }
            ),
        ],
    )
    assert added.exit_code == 0, added.output

    async with session_factory() as session:
        record = await session.scalar(select(RecordModel))
        assert record is not None
        assert record.payload["published"] == "1961-05-04"
        assert record.payload["genres"] == ["sci-fi", "philosophy"]
        assert record.rendered == (
            "Author: Stanisław Lem\n"
            "Published: 1961-05-04\n"
            "Genres: sci-fi, philosophy\n"
            "In print: yes"
        )  # shelf_code is not embedded, so it is not in the card
