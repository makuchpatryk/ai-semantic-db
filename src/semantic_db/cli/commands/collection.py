from typing import Annotated

import typer

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
    collection = run(
        lambda container: container.create_collection.execute(cmd), "collection create"
    )
    console.print(
        f"[green]✓[/] created collection '{collection.name}' "
        f"with {len(collection.schema.fields)} fields"
    )


def _preview(fields: list[FieldDefinition]) -> None:
    # Validates the schema as a whole before anything is written or confirmed.
    print_schema_preview(CollectionSchema(fields=tuple(fields)))
