from time import perf_counter
from typing import Annotated

import typer
from rich.panel import Panel

from semantic_db.application.use_cases.add_record import AddRecordCommand
from semantic_db.cli.runner import console, guard, run
from semantic_db.cli.set_spec import parse_set_specs
from semantic_db.domain.errors import SemanticDbError
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
        if not set_:
            raise SemanticDbError(
                "interactive record entry arrives in M4; for now pass values with --set key=value"
            )
        values = parse_set_specs(set_)

    cmd = AddRecordCommand(collection_name=collection, values=values)
    started = perf_counter()
    record = run(lambda container: container.add_record.execute(cmd))
    elapsed_ms = int((perf_counter() - started) * 1000)

    console.print(Panel(record.rendered, title="Saved", title_align="left"))
    console.print(
        f"[green]✓[/] saved record {record.id}, embedded with {_model_name()} ({elapsed_ms}ms)"
    )


def _model_name() -> str:
    return get_settings().embedding_model
