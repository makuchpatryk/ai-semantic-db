from time import perf_counter
from typing import Annotated

import click
import typer
from rich.progress import Progress
from rich.table import Table

from semantic_db.application.use_cases.create_collection import CreateCollectionCommand
from semantic_db.application.use_cases.delete_collection import DeleteCollectionCommand
from semantic_db.application.use_cases.edit_collection import EditCollectionCommand
from semantic_db.cli.field_spec import parse_enum_add_specs, parse_field_spec
from semantic_db.cli.prompts import PromptAborted, confirm, prompt_field_definitions
from semantic_db.cli.render_preview import print_schema_preview
from semantic_db.cli.runner import console, error_console, guard, run
from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.errors import SemanticDbError
from semantic_db.settings import get_settings

collection_app = typer.Typer(no_args_is_help=True, help="Define and inspect collections.")

FIELD_HELP = (
    "Field spec, repeatable: name:type[:flags][:key=value] "
    "(e.g. 'price:float:embed:unit=PLN'). Given at least once, the wizard is skipped."
)

ADD_FIELD_HELP = (
    "Field spec, repeatable, same grammar as --field (e.g. 'notes:text'). "
    "Only optional fields may be added."
)
ENUM_ADD_HELP = "Enum value to add, repeatable: field=value (e.g. 'category=drills')."


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


@collection_app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Argument(help="Collection name")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip confirmation")] = False,
) -> None:
    """Delete a collection, its records, and their embeddings."""
    if not yes:
        field_count, record_count = run(lambda c: c.queries.collection_stats(name))
        console.print(
            f"This deletes collection '{name}': "
            f"{field_count} fields, {record_count} records, {record_count} embeddings."
        )
        typed = click.prompt("Type the collection name to confirm", default="", show_default=False)
        if typed.strip() != name:
            error_console.print("Aborted.")
            raise typer.Exit(1)

    cmd = DeleteCollectionCommand(name=name)
    run(lambda container: container.delete_collection.execute(cmd))
    console.print("[green]✓[/] deleted")


@collection_app.command("edit")
def edit_cmd(
    name: Annotated[str, typer.Argument(help="Collection name")],
    rename: Annotated[str | None, typer.Option("--rename", help="New collection name")] = None,
    add_field: Annotated[list[str] | None, typer.Option("--add-field", help=ADD_FIELD_HELP)] = None,
    embed: Annotated[
        list[str] | None, typer.Option("--embed", help="Field to turn embedding on for")
    ] = None,
    no_embed: Annotated[
        list[str] | None, typer.Option("--no-embed", help="Field to turn embedding off for")
    ] = None,
    enum_add: Annotated[list[str] | None, typer.Option("--enum-add", help=ENUM_ADD_HELP)] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Skip confirmation")] = False,
) -> None:
    """Rename a collection, add an optional field, toggle embed on a field, or add enum
    values. Rejects removing a field, adding a required field, changing a type, or
    removing an enum value — delete and recreate the collection for those."""
    with guard():
        if not (rename or add_field or embed or no_embed or enum_add):
            raise SemanticDbError(
                "no changes given; use --rename, --add-field, --embed, --no-embed or --enum-add"
            )

        embed_on = frozenset(embed or [])
        embed_off = frozenset(no_embed or [])
        collision = sorted(embed_on & embed_off)
        if collision:
            raise SemanticDbError(
                f"field(s) {', '.join(collision)} given to both --embed and --no-embed"
            )

        add_fields = [parse_field_spec(spec) for spec in add_field or []]
        enum_additions = parse_enum_add_specs(enum_add) if enum_add else {}

    cmd = EditCollectionCommand(
        name=name,
        rename_to=rename,
        add_fields=add_fields,
        embed_on=embed_on,
        embed_off=embed_off,
        enum_additions=enum_additions,
    )

    if not (add_field or embed or no_embed):
        result = run(lambda container: container.edit_collection.execute(cmd))
        console.print(f"[green]✓[/] updated collection '{result.collection.name}'")
        return

    _, record_count = run(lambda c: c.queries.collection_stats(name))
    if not yes and not typer.confirm(
        f"This changes collection '{name}': {record_count} records will be "
        "re-rendered and re-embedded. Continue?"
    ):
        error_console.print("Aborted.")
        raise typer.Exit(1)

    started = perf_counter()
    with Progress(console=console) as progress:
        task = progress.add_task("Re-embedding", total=None)

        def on_progress(done_batches: int, total_batches: int) -> None:
            progress.update(task, completed=done_batches, total=total_batches)

        result = run(lambda container: container.edit_collection.execute(cmd, on_progress))
    elapsed_ms = int((perf_counter() - started) * 1000)

    console.print(
        f"[green]✓[/] updated collection '{result.collection.name}', "
        f"re-embedded {result.reembedded_count} records "
        f"with {get_settings().embedding_model} ({elapsed_ms}ms)"
    )
