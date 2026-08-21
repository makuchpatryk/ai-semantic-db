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
from semantic_db.container import Container
from semantic_db.domain.errors import SemanticDbError
from semantic_db.domain.record import PayloadValue, Record
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
    record, elapsed_ms = _add(AddRecordCommand(collection_name=collection, values=values))
    _print_saved(record, elapsed_ms)


def _add_interactive(collection: str) -> None:
    """Add records interactively, with schema-driven prompts."""
    defaults: Mapping[str, PayloadValue] = {}

    while True:
        schema = run(lambda c: c.queries.get_collection(collection), "record schema")
        values = prompt_record_values(schema.schema, defaults)
        console.print(preview_panel(schema.schema, values))

        if not confirm("Save?", default=True):
            continue

        record, elapsed_ms = _add(AddRecordCommand(collection_name=collection, values=values))
        _print_saved(record, elapsed_ms)

        defaults = record.payload
        if not confirm("Add another?", default=True):
            break


def _add(cmd: AddRecordCommand) -> tuple[Record, int]:
    """Add a record and time it. The clock sits inside the container so the number the user
    reads is the work itself, not the container build and the telemetry flush around it."""

    async def _execute(container: Container) -> tuple[Record, int]:
        started = perf_counter()
        record = await container.add_record.execute(cmd)
        return record, int((perf_counter() - started) * 1000)

    return run(_execute, "record add")


def _print_saved(record: Record, elapsed_ms: int) -> None:
    console.print(Panel(record.rendered, title="Saved", title_align="left"))
    console.print(
        f"[green]✓[/] saved record {record.id}, embedded with {_model_name()} ({elapsed_ms}ms)"
    )


def _model_name() -> str:
    return get_settings().embedding_model
