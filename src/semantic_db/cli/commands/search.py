from collections.abc import Mapping
from typing import Annotated

import typer
from rich.table import Table

from semantic_db.application.use_cases.search_records import SearchRecordsCommand
from semantic_db.cli.runner import console, run
from semantic_db.domain.collection import CollectionSchema
from semantic_db.domain.record import PayloadValue


def search(
    collection: Annotated[str, typer.Argument(help="Collection name")],
    query: Annotated[str, typer.Argument(help="Search query")],
    k: Annotated[int, typer.Option("--k", "-k", min=1, help="Maximum number of results")] = 10,
    explain: Annotated[bool, typer.Option("--explain", help="Show full rendered text")] = False,
) -> None:
    """Search a collection for records similar to the query."""
    cmd = SearchRecordsCommand(collection_name=collection, query=query, k=k)
    result = run(lambda c: c.search_records.execute(cmd), "search")

    if not result.hits:
        console.print("[yellow]No results found.[/]")
        return

    # Print table with rank, distance, and first embeddable field
    table = Table(title=f"Top {len(result.hits)} results")
    table.add_column("Rank", style="cyan")
    table.add_column("Distance", style="magenta")
    table.add_column(_first_embeddable_label(result.schema), style="green")

    for idx, hit in enumerate(result.hits, 1):
        first_field = _first_embeddable_field(result.schema, hit.record.payload)
        table.add_row(str(idx), f"{hit.distance:.4f}", str(first_field) if first_field else "")

    console.print(table)

    if explain:
        console.print()
        for idx, hit in enumerate(result.hits, 1):
            from rich.panel import Panel

            panel = Panel(hit.record.rendered, title=f"Result {idx} (distance: {hit.distance:.4f})")
            console.print(panel)


def _first_embeddable_label(schema: CollectionSchema) -> str:
    """Get the label of the first embeddable field."""
    for field in schema.fields:
        if field.embed:
            return field.label
    return "Value"


def _first_embeddable_field(
    schema: CollectionSchema, payload: Mapping[str, PayloadValue]
) -> PayloadValue | None:
    """Get the value of the first embeddable field."""
    for field in schema.fields:
        if field.embed and field.name in payload:
            return payload[field.name]
    return None
