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


async def invoke(args: list[str], input: str | None = None) -> Result:
    """The CLI owns its event loop (`asyncio.run`), so it runs off the test's loop."""
    return await asyncio.to_thread(lambda: runner.invoke(app, args, input=input))


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


async def add_product(title: str, description: str, category: str) -> None:
    result = await invoke(
        [
            "record",
            "add",
            "products",
            *set_args(
                {
                    "title": title,
                    "description": description,
                    "category": category,
                    "year": "2019",
                    "price": "4200",
                }
            ),
        ],
    )
    assert result.exit_code == 0, result.output


async def test_search_finds_the_record_that_matches_the_query(
    session_factory: SessionFactory,
) -> None:
    """The whole point of the tool: added means searchable, in natural language."""
    await create_products()
    await add_product("Hydraulic pump HP-400", "Cast-iron housing, rated 400 l/min.", "pumps")
    await add_product("Brass gate valve GV-20", "Manual shut-off for water lines.", "valves")

    result = await invoke(["search", "products", "quiet pump for industrial use", "--k", "1"])

    assert result.exit_code == 0, result.output
    assert "Hydraulic" in result.stdout
    assert "Brass" not in result.stdout


async def test_search_explain_shows_the_embedded_card(session_factory: SessionFactory) -> None:
    await create_products()
    await add_product("Hydraulic pump HP-400", "Cast-iron housing, rated 400 l/min.", "pumps")

    result = await invoke(["search", "products", "pump", "--explain"])

    assert result.exit_code == 0, result.output
    assert "Cast-iron" in result.stdout  # --explain prints the rendered text, not just the title


async def test_search_on_an_empty_collection_says_so(session_factory: SessionFactory) -> None:
    await create_products()

    result = await invoke(["search", "products", "anything"])

    assert result.exit_code == 0, result.output
    assert "No results" in result.stdout


async def test_search_on_an_unknown_collection_is_rejected(
    session_factory: SessionFactory,
) -> None:
    result = await invoke(["search", "ghosts", "anything"])
    assert result.exit_code == 2


async def test_collection_list_shows_field_and_record_counts(
    session_factory: SessionFactory,
) -> None:
    """Collection list shows all collections with their metadata."""
    await create_products()
    await invoke(["collection", "create", "books", *field_args(BOOKS_FIELD_SPECS)])

    # Add 3 records to products
    for i in range(3):
        await add_product(f"Product {i}", f"Description {i}", "pumps")

    # Add 1 record to books
    await invoke(
        [
            "record",
            "add",
            "books",
            *set_args(
                {
                    "author": "Author 1",
                    "published": "1961-05-04",
                    "genres": "sci-fi",
                    "in_print": "y",
                    "shelf_code": "A-12",
                }
            ),
        ],
    )

    result = await invoke(["collection", "list"])

    assert result.exit_code == 0, result.output
    # Should show both collections in alphabetical order
    assert "books" in result.stdout
    assert "products" in result.stdout
    # Both have 5 fields, 3 records in products, 1 in books
    # Just check that both show up with their data
    lines = result.stdout.split("\n")
    # Find lines with books and products data
    books_line = [line for line in lines if "books" in line]
    products_line = [line for line in lines if "products" in line]
    assert len(books_line) > 0
    assert len(products_line) > 0
    # products should have 3 records, books should have 1
    assert "│ products │ 5      │ 3       │" in result.stdout
    assert "│ books    │ 5      │ 1       │" in result.stdout


async def test_collection_show_displays_schema(session_factory: SessionFactory) -> None:
    """Collection show displays the full schema with field details."""
    await create_products()

    result = await invoke(["collection", "show", "products"])

    assert result.exit_code == 0, result.output
    # Should show field names
    assert "title" in result.stdout
    assert "description" in result.stdout
    assert "category" in result.stdout
    # Should show field types
    assert "text" in result.stdout
    assert "int" in result.stdout
    assert "enum" in result.stdout
    # Should show flags
    assert "embed" in result.stdout
    # Should show enum values
    assert "pumps" in result.stdout


async def test_collection_list_on_empty_database_says_so(session_factory: SessionFactory) -> None:
    """Collection list on empty database shows friendly message."""
    result = await invoke(["collection", "list"])
    assert result.exit_code == 0, result.output
    assert "No collections yet" in result.stdout


async def test_record_list_shows_id_and_embedded_fields(session_factory: SessionFactory) -> None:
    """Record list shows paginated results with ID and embedded fields."""
    await create_products()

    # Add 3 records
    await add_product("Pump A", "Desc A", "pumps")
    await add_product("Valve B", "Desc B", "valves")
    await add_product("Motor C", "Desc C", "motors")

    result = await invoke(["record", "list", "products"])

    assert result.exit_code == 0, result.output
    # Should show ID column and data
    assert "ID" in result.stdout
    # Should show embedded fields (title is the first embeddable)
    assert "Title" in result.stdout or "title" in result.stdout.lower()
    # Should show the records
    assert "Pump A" in result.stdout
    assert "Valve B" in result.stdout
    assert "Motor C" in result.stdout
    # Should show pagination footer
    assert "showing" in result.stdout
    assert "of" in result.stdout


async def test_record_list_with_pagination(session_factory: SessionFactory) -> None:
    """Record list respects limit and offset."""
    await create_products()

    # Add 5 records
    for i in range(5):
        await add_product(f"Product {i}", f"Desc {i}", "pumps")

    # First page: limit 2, offset 0
    result = await invoke(["record", "list", "products", "--limit", "2", "--offset", "0"])
    assert result.exit_code == 0, result.output
    assert "showing 1-2 of 5" in result.stdout

    # Second page: limit 2, offset 2
    result = await invoke(["record", "list", "products", "--limit", "2", "--offset", "2"])
    assert result.exit_code == 0, result.output
    assert "showing 3-4 of 5" in result.stdout


async def test_record_list_on_empty_collection_says_so(session_factory: SessionFactory) -> None:
    """Record list on empty collection shows friendly message."""
    await create_products()

    result = await invoke(["record", "list", "products"])

    assert result.exit_code == 0, result.output
    assert "No records" in result.stdout


async def test_record_show_displays_full_record_details(session_factory: SessionFactory) -> None:
    """Record show displays the full record payload and rendering."""
    await create_products()
    await add_product("Pump A", "Description of pump A", "pumps")

    # Get the record ID
    async with session_factory() as session:
        record = await session.scalar(select(RecordModel))
        assert record is not None
        record_id = record.id

    result = await invoke(["record", "show", "products", str(record_id)])

    assert result.exit_code == 0, result.output
    # Should show the rendered text
    assert "Pump A" in result.stdout
    # Should show full payload (including non-embedded fields like description)
    assert "Description of pump A" in result.stdout or "description" in result.stdout.lower()
    # Should show model name
    assert "Model:" in result.stdout
    assert "bge-m3" in result.stdout


async def test_record_show_not_found(session_factory: SessionFactory) -> None:
    """Record show with non-existent ID exits 2."""
    await create_products()

    result = await invoke(["record", "show", "products", "999"])

    assert result.exit_code == 2
    assert "not found" in result.stdout or "not found" in result.stderr


async def _added_record_id(session_factory: SessionFactory) -> int:
    async with session_factory() as session:
        record = await session.scalar(select(RecordModel))
        assert record is not None
        assert record.id is not None
        return record.id


async def test_record_delete_with_yes_removes_the_record_and_its_embedding(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    result = await invoke(["record", "delete", "products", str(record_id), "--yes"])

    assert result.exit_code == 0, result.output
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 0
        assert await session.scalar(select(func.count()).select_from(EmbeddingModel)) == 0


async def test_record_delete_confirmed_with_y_deletes(session_factory: SessionFactory) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    result = await invoke(["record", "delete", "products", str(record_id)], input="y\n")

    assert result.exit_code == 0, result.output
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 0


async def test_record_delete_declined_leaves_the_record(session_factory: SessionFactory) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    result = await invoke(["record", "delete", "products", str(record_id)], input="n\n")

    assert result.exit_code == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 1


async def test_record_delete_defaults_to_no_on_bare_enter(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    result = await invoke(["record", "delete", "products", str(record_id)], input="\n")

    assert result.exit_code == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 1


async def test_record_delete_unknown_id_is_rejected(session_factory: SessionFactory) -> None:
    await create_products()

    result = await invoke(["record", "delete", "products", "999", "--yes"])

    assert result.exit_code == 2


async def test_record_delete_unknown_collection_is_rejected(
    session_factory: SessionFactory,
) -> None:
    result = await invoke(["record", "delete", "ghosts", "1", "--yes"])

    assert result.exit_code == 2


async def test_collection_delete_with_yes_cascades_to_records_and_embeddings(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    await add_product("Valve B", "Desc B", "valves")

    result = await invoke(["collection", "delete", "products", "--yes"])

    assert result.exit_code == 0, result.output
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CollectionModel)) == 0
        assert await session.scalar(select(func.count()).select_from(RecordModel)) == 0
        assert await session.scalar(select(func.count()).select_from(EmbeddingModel)) == 0


async def test_collection_delete_with_yes_skips_display_and_prompt(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    result = await invoke(["collection", "delete", "products", "--yes"])

    assert result.exit_code == 0, result.output
    assert "This deletes collection" not in result.output
    assert "Type the collection name" not in result.output


async def test_collection_delete_confirmed_with_typed_name_deletes(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    result = await invoke(["collection", "delete", "products"], input="products\n")

    assert result.exit_code == 0, result.output
    assert "This deletes collection 'products': 5 fields, 1 records, 1 embeddings." in (
        result.output
    )
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CollectionModel)) == 0


async def test_collection_delete_mismatched_typed_name_aborts(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    result = await invoke(["collection", "delete", "products"], input="not-products\n")

    assert result.exit_code == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CollectionModel)) == 1


async def test_collection_delete_unknown_name_is_rejected(
    session_factory: SessionFactory,
) -> None:
    result = await invoke(["collection", "delete", "ghosts", "--yes"])

    assert result.exit_code == 2


async def test_record_edit_of_an_embedded_field_changes_search_ranking(
    session_factory: SessionFactory,
) -> None:
    """`edit --set` on an embedded field must re-embed, so search ranks the edited record
    by its NEW text, not the text it was added with (a stale vector would rank it by the
    old, pump-flavoured text and lose to the untouched valve record)."""
    await create_products()
    await add_product("Hydraulic pump HP-400", "Cast-iron housing, rated 400 l/min.", "pumps")
    record_id = await _added_record_id(session_factory)
    await add_product("Old rusty valve", "Reclaimed from a demolition site.", "valves")

    result = await invoke(
        [
            "record",
            "edit",
            "products",
            str(record_id),
            "--set",
            "title=Brass gate valve GV-20",
            "--set",
            "description=Manual shut-off for water lines.",
        ]
    )
    assert result.exit_code == 0, result.output

    found = await invoke(["search", "products", "brass gate valve manual shut-off", "--k", "1"])
    assert found.exit_code == 0, found.output
    assert "Brass gate valve" in found.stdout
    assert "Old rusty valve" not in found.stdout


async def test_record_edit_of_a_non_embedded_field_leaves_the_vector_untouched(
    session_factory: SessionFactory,
) -> None:
    await invoke(["collection", "create", "books", *field_args(BOOKS_FIELD_SPECS)])
    added = await invoke(
        [
            "record",
            "add",
            "books",
            *set_args(
                {
                    "author": "Stanisław Lem",
                    "published": "1961-05-04",
                    "genres": "sci-fi",
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
        record_id = record.id
        embedding_before = await session.get(EmbeddingModel, record_id)
        assert embedding_before is not None
        before = list(embedding_before.vec)

    result = await invoke(["record", "edit", "books", str(record_id), "--set", "shelf_code=B-01"])
    assert result.exit_code == 0, result.output
    assert "unchanged embedding" in result.stdout

    async with session_factory() as session:
        embedding_after = await session.get(EmbeddingModel, record_id)
        assert embedding_after is not None
        reloaded = await session.get(RecordModel, record_id)
        assert reloaded is not None
        assert reloaded.payload["shelf_code"] == "B-01"
        after = list(embedding_after.vec)

    assert after == before  # byte-identical, no re-embed happened


async def test_record_edit_unset_on_a_required_field_is_rejected(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    async with session_factory() as session:
        before = await session.get(RecordModel, record_id)
        assert before is not None
        before_payload = dict(before.payload)

    result = await invoke(["record", "edit", "products", str(record_id), "--unset", "title"])

    assert result.exit_code == 2
    assert "required" in result.stdout or "required" in result.stderr
    async with session_factory() as session:
        after = await session.get(RecordModel, record_id)
        assert after is not None
        assert dict(after.payload) == before_payload


async def test_record_edit_wizard_prefills_with_current_values(
    session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No TTY, no --set/--unset -> wizard, pre-filled with the record's current payload."""
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")
    record_id = await _added_record_id(session_factory)

    import semantic_db.cli.commands.record as record_module
    from semantic_db.cli import prompts as prompts_module

    class ScriptedPromptSession:
        def __init__(self, answers: list[str]) -> None:
            self._answers = answers

        def prompt(self, *args: object, default: str = "", **kwargs: object) -> str:
            answer = self._answers.pop(0)
            return answer if answer else default

    class FakeStdin:
        def isatty(self) -> bool:
            return True

    class FakeSys:
        """CliRunner swaps `sys.stdin` per invoke, so patching the real one doesn't
        stick — patch the name `record.py` looks up instead."""

        stdin = FakeStdin()

        def __getattr__(self, name: str) -> object:
            import sys as real_sys

            return getattr(real_sys, name)

    # title, description, category, year, price — Enter (blank) keeps each default,
    # except title which is changed. Then "Save?" -> "y".
    answers = ["Pump A (rev 2)", "", "", "", "", "y"]
    monkeypatch.setattr(
        prompts_module, "PromptSession", lambda *a, **k: ScriptedPromptSession(answers)
    )
    monkeypatch.setattr(record_module, "sys", FakeSys())

    result = await invoke(["record", "edit", "products", str(record_id)])

    assert result.exit_code == 0, result.output
    async with session_factory() as session:
        record = await session.get(RecordModel, record_id)
        assert record is not None
        assert record.payload["title"] == "Pump A (rev 2)"
        assert record.payload["category"] == "pumps"  # untouched default survives


async def test_collection_edit_rename_moves_the_collection_and_its_records(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    result = await invoke(["collection", "edit", "products", "--rename", "parts"])
    assert result.exit_code == 0, result.output

    shown = await invoke(["collection", "show", "parts"])
    assert shown.exit_code == 0, shown.output

    gone = await invoke(["collection", "show", "products"])
    assert gone.exit_code == 2


async def test_collection_edit_add_field_leaves_existing_rendered_text_byte_identical(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    async with session_factory() as session:
        before = await session.scalar(select(RecordModel))
        assert before is not None
        rendered_before = before.rendered

    result = await invoke(["collection", "edit", "products", "--add-field", "notes:text", "--yes"])
    assert result.exit_code == 0, result.output

    shown = await invoke(["collection", "show", "products"])
    assert "notes" in shown.stdout

    async with session_factory() as session:
        after = await session.scalar(select(RecordModel))
        assert after is not None
        assert after.rendered == rendered_before  # optional field absent, so no text delta


async def test_collection_edit_embed_toggle_changes_search_ranking(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "General purpose pump.", "pumps")
    result = await invoke(
        [
            "record",
            "add",
            "products",
            *set_args(
                {
                    "title": "Valve B",
                    "description": "General purpose valve.",
                    "category": "valves",
                    "year": "1999",
                    "price": "10",
                }
            ),
        ]
    )
    assert result.exit_code == 0, result.output

    before = await invoke(["search", "products", "1999", "--k", "1"])
    assert before.exit_code == 0, before.output

    toggled = await invoke(["collection", "edit", "products", "--embed", "year", "--yes"])
    assert toggled.exit_code == 0, toggled.output

    after = await invoke(["search", "products", "1999", "--k", "1"])
    assert after.exit_code == 0, after.output
    assert "Valve B" in after.stdout  # now ranks first: "1999" only appears in its own text


async def test_collection_edit_enum_add_allows_the_new_value(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    result = await invoke(["collection", "edit", "products", "--enum-add", "category=drills"])
    assert result.exit_code == 0, result.output

    added = await invoke(
        [
            "record",
            "add",
            "products",
            *set_args({"title": "Drill D", "category": "drills", "year": "2020", "price": "50"}),
        ]
    )
    assert added.exit_code == 0, added.output


async def test_collection_edit_rejects_a_required_add_field(
    session_factory: SessionFactory,
) -> None:
    await create_products()

    result = await invoke(
        ["collection", "edit", "products", "--add-field", "sku:text:required", "--yes"]
    )

    assert result.exit_code == 2
    output = (result.stdout + result.stderr).replace("\n", " ")
    assert "required field 'sku'" in output
    shown = await invoke(["collection", "show", "products"])
    assert "sku" not in shown.stdout


async def test_collection_edit_confirmation_declined_leaves_the_collection_unchanged(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    result = await invoke(
        ["collection", "edit", "products", "--add-field", "notes:text"], input="n\n"
    )

    assert result.exit_code == 1
    shown = await invoke(["collection", "show", "products"])
    assert "notes" not in shown.stdout


async def test_collection_edit_confirmed_with_y_applies_the_change(
    session_factory: SessionFactory,
) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    result = await invoke(
        ["collection", "edit", "products", "--add-field", "notes:text"], input="y\n"
    )

    assert result.exit_code == 0, result.output
    shown = await invoke(["collection", "show", "products"])
    assert "notes" in shown.stdout


async def test_collection_edit_yes_skips_the_prompt(session_factory: SessionFactory) -> None:
    await create_products()
    await add_product("Pump A", "Desc A", "pumps")

    result = await invoke(["collection", "edit", "products", "--add-field", "notes:text", "--yes"])

    assert result.exit_code == 0, result.output
    assert "records will be re-rendered" not in result.output
