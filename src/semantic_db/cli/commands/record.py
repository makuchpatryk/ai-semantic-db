import sys
from collections.abc import Mapping
from time import perf_counter
from typing import Annotated

import typer
from rich.panel import Panel

from semantic_db.application.use_cases.add_record import AddRecordCommand
from semantic_db.cli.prompts import confirm, prompt_record_values
from semantic_db.cli.render_preview import preview_panel
from semantic_db.cli.runner import console, guard, run
from semantic_db.cli.set_spec import parse_set_specs
from semantic_db.cli.tables import record_table
from semantic_db.domain.errors import SemanticDbError
from semantic_db.domain.record import Payload
from semantic_db.domain.rendering import format_value
from semantic_db.settings import get_settings

record_app = typer.Typer(no_args_is_help=True, help="Add and inspect records.")

SET_HELP = "Field value, repeatable: key=value (e.g. 'year=2019'). Coerced by declared type."


@record_app.command("add")
def add(
    collection: Annotated[str, typer.Argument(help="Collection name")],
    set_: Annotated[list[str] | None, typer.Option("--set", "-s", help=SET_HELP)] = None,
) -> None:
    """Add a record; it is rendered and embedded before it is stored."""
    with guard():
        if set_:
            values = parse_set_specs(set_)
            _add_with_values(collection, values)
        elif not sys.stdin.isatty():
            raise SemanticDbError(
                "interactive record entry requires a TTY; pass values with --set key=value"
            )
        else:
            _add_interactive(collection)


def _add_with_values(collection: str, values: Mapping[str, object]) -> None:
    """Add a record with --set flags."""
    cmd = AddRecordCommand(collection_name=collection, values=values)
    started = perf_counter()
    record = run(lambda container: container.add_record.execute(cmd))
    elapsed_ms = int((perf_counter() - started) * 1000)

    console.print(Panel(record.rendered, title="Saved", title_align="left"))
    console.print(
        f"[green]✓[/] saved record {record.id}, embedded with {_model_name()} ({elapsed_ms}ms)"
    )


def _add_interactive(collection: str) -> None:
    """Add records interactively, with schema-driven prompts."""
    defaults: Payload = {}

    while True:
        schema = run(lambda c: c.queries.get_collection(collection))
        values = prompt_record_values(schema.schema, defaults)
        console.print(preview_panel(schema.schema, values))

        if not confirm("Save?", default=True):
            continue

        cmd = AddRecordCommand(collection_name=collection, values=values)
        started = perf_counter()

        async def _execute(container, cmd=cmd):  # type: ignore[no-untyped-def]
            return await container.add_record.execute(cmd)

        record = run(_execute)
        elapsed_ms = int((perf_counter() - started) * 1000)

        console.print(Panel(record.rendered, title="Saved", title_align="left"))
        console.print(
            f"[green]✓[/] saved record {record.id}, embedded with {_model_name()} ({elapsed_ms}ms)"
        )

        defaults = record.payload
        if not confirm("Add another?", default=True):
            break


def _model_name() -> str:
    return get_settings().embedding_model


@record_app.command("list")
def list_cmd(
    collection: Annotated[str, typer.Argument(help="Collection name")],
    limit: Annotated[int, typer.Option("--limit", min=1, help="Number of records per page")] = 20,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Starting record index")] = 0,
) -> None:
    """List records in a collection."""
    page = run(lambda c: c.queries.list_records(collection, limit, offset))

    if not page.records:
        console.print("No records.")
        return

    table = record_table(page.schema, page.records)
    console.print(table)

    # Footer with pagination info
    end = offset + len(page.records)
    console.print(f"showing {offset + 1}-{end} of {page.total}")


@record_app.command("show")
def show_cmd(
    collection: Annotated[str, typer.Argument(help="Collection name")],
    record_id: Annotated[int, typer.Argument(help="Record ID")],
) -> None:
    """Show a single record with all details."""
    view = run(lambda c: c.queries.show_record(collection, record_id))

    # Show full payload
    console.print("[bold]Full Record[/]")
    for field in view.schema.fields:
        value = view.detail.record.payload.get(field.name)
        formatted = format_value(field, value) if value is not None else "(empty)"
        console.print(f"  {field.label}: {formatted}")

    console.print()
    console.print("[bold]Rendered[/]")
    console.print(view.detail.record.rendered)

    console.print()
    model_text = view.detail.model if view.detail.model else "(no embedding)"
    console.print(f"[bold]Model:[/] {model_text}")
