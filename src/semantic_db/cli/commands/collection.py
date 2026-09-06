from typing import Annotated

import typer
from rich.table import Table

from semantic_db.application.use_cases.create_collection import CreateCollectionCommand
from semantic_db.cli.field_spec import parse_field_spec
from semantic_db.cli.prompts import PromptAborted, confirm, prompt_field_definitions
from semantic_db.cli.render_preview import print_schema_preview
from semantic_db.cli.runner import console, error_console, guard, run
from semantic_db.domain.collection import CollectionSchema, FieldDefinition

collection_app = typer.Typer(no_args_is_help=True, help="Define and inspect collections.")

FIELD_HELP = (
    "Field spec, repeatable: name:type[:flags][:key=value] "
    "(e.g. 'price:float:embed:unit=PLN'). Given at least once, the wizard is skipped."
)


@collection_app.command("create")
def create(
    name: Annotated[str, typer.Argument(help="Collection name")],
    field: Annotated[list[str] | None, typer.Option("--field", "-f", help=FIELD_HELP)] = None,
) -> None:
    """Define a collection's fields and types."""
    interactive = not field

    with guard():
        if interactive:
            try:
                fields = prompt_field_definitions()
            except PromptAborted:
                error_console.print("Aborted.")
                raise typer.Exit(1) from None
        else:
            fields = [parse_field_spec(spec) for spec in field or []]

        _preview(fields)

        if interactive and not confirm(f"Create collection '{name}' with {len(fields)} fields?"):
            error_console.print("Aborted.")
            raise typer.Exit(1)

    cmd = CreateCollectionCommand(name=name, fields=fields)
    collection = run(lambda container: container.create_collection.execute(cmd))
    console.print(
        f"[green]✓[/] created collection '{collection.name}' "
        f"with {len(collection.schema.fields)} fields"
    )


def _preview(fields: list[FieldDefinition]) -> None:
    # Validates the schema as a whole before anything is written or confirmed.
    print_schema_preview(CollectionSchema(fields=tuple(fields)))


@collection_app.command("list")
def list_cmd() -> None:
    """List all collections with their field and record counts."""
    summaries = run(lambda c: c.queries.list_collections())

    if not summaries:
        console.print("No collections yet.")
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Fields", style="magenta")
    table.add_column("Records", style="green")

    for summary in summaries:
        table.add_row(summary.name, str(summary.field_count), str(summary.record_count))

    console.print(table)


@collection_app.command("show")
def show_cmd(name: Annotated[str, typer.Argument(help="Collection name")]) -> None:
    """Show the schema of a collection."""
    collection = run(lambda c: c.queries.show_collection(name))

    table = Table()
    table.add_column("Field", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Flags", style="yellow")
    table.add_column("Values/Unit", style="green")

    for field in collection.schema.fields:
        flags = []
        if field.embed:
            flags.append("embed")
        if field.required:
            flags.append("required")
        flags_str = ", ".join(flags) if flags else ""

        values_unit = ""
        if field.enum_values:
            values_unit = ", ".join(field.enum_values)
        elif field.unit:
            values_unit = field.unit

        table.add_row(field.name, str(field.type.value), flags_str, values_unit)

    console.print(table)
    print_schema_preview(collection.schema)
